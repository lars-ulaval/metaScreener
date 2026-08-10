# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""Persistent LLM settings — F-116.

One app-level setting with a per-stage override, stored beside the user's
other application data.

Why not ``.env`` (D2)
---------------------
``.env`` does not work in the shipped artefact, in either direction, and
its write fails **silently**. Established rather than assumed:

* the PyInstaller spec is **onefile** — ``EXE(pyz, a.scripts, a.binaries,
  a.datas, …)`` with no ``COLLECT`` — so the bundle is unpacked at
  runtime into a temporary directory named by ``sys._MEIPASS``;
* ``metascreener/main.py`` computes ``project_root =
  Path(__file__).resolve().parents[1]``, which under onefile *is* that
  temporary directory. ``main.py`` is not frozen-aware, unlike
  ``metascreener/plugin_manager.py``, which reads ``sys._MEIPASS``
  precisely because it must be;
* ``.env`` is not among the spec's ``datas``, so the read finds nothing
  and returns silently;
* the write succeeds, into a directory PyInstaller deletes on exit. So
  ``_save_env_key`` reports ``ok=True`` and the key is gone next launch —
  **F-139's own failure mode, a persist indistinguishable from one that
  worked, reintroduced by packaging.** F-139's fix cannot see it: it
  verifies that the write succeeded, not that the location survives.

So this module addresses its directory from the environment, never from
``__file__``.

Why here rather than in ``metascreener/``
-----------------------------------------
Both the application and the plugins must read it, and ``plugins`` is a
real package on ``sys.path`` in the app, in the frozen build (the spec
carries ``'plugins'`` in ``hiddenimports`` with a ``collect_submodules``
hook) and under the test conftest — whereas ``metascreener`` is replaced
by a stub module in ``tests/conftest.py``, so ``metascreener.settings``
would not be importable from a test. This module imports no tkinter for
the same reason: it must be testable without a display.

The write rules, and where they come from
-----------------------------------------
``metascreener/main.py::_save_env_key`` is F-139's write-up, and it names
three properties that were each a regression in the first version of that
fix. They are re-implemented here rather than assumed to generalise,
because this is a second writer of a user-authored file with the same
shape:

* **symlinks are followed** — renaming onto the link path would replace
  the *link* with a regular file, so a settings file symlinked to a
  shared location would silently stop being updated while the save
  reported success. That is this function's own defect class reached
  through its own fix, and wave 9's review caught it once already;
* **the temporary name is unique** — a constant one lets two instances
  overwrite each other's;
* **the write is atomic** — a sibling temporary moved into place with
  ``os.replace``, so a part-way failure cannot truncate the original.

One rule is stricter here than in ``.env``: this file may hold an API
key, so it is created ``0o600`` rather than inheriting the umask, and an
existing file's mode is preserved rather than widened.

And one rule is inherited unchanged: **absent is not unreadable.** A
missing file reads as defaults; a file that exists and cannot be parsed
raises, and is never overwritten. The user can repair it; they cannot
un-destroy it.

Known limit, carried forward deliberately
-----------------------------------------
The read-modify-write is not atomic *across processes*: the last writer
still wins on the file as a whole. ``_save_env_key``'s docstring records
the same limit and assigns the lock to this wave. It is not implemented
here because a lock that is wrong is worse than none, and the realistic
trigger — two instances editing settings simultaneously — is rarer than
the ``.env`` case that motivated it, since the settings dialog is modal.
Recorded rather than silently omitted.
"""
from __future__ import annotations

import errno
import json
import os
import stat
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

APP_DIR_NAME = "metaScreener"
SETTINGS_FILE_NAME = "settings.json"
SCHEMA = 1

#: Providers the application understands. ``custom`` covers LM Studio,
#: llama.cpp and vLLM alike — they speak the same wire protocol, so a URL
#: field covers them all with no new code and no new member here.
PROVIDERS = ("local", "openai", "custom")

DEFAULT_LOCAL_ENDPOINT = "http://localhost:11434/v1"
DEFAULT_OPENAI_ENDPOINT = "https://api.openai.com/v1"


class SettingsUnreadableError(ValueError):
    """The settings file exists and could not be parsed.

    A ``ValueError`` so that callers already catching broadly keep
    working — the precedent is ``plugins/_common/input_errors.py``'s
    ``InputErrorsUnreadableError`` (F-68).
    """


def _is_windows() -> bool:
    """Split out so a test can drive both branches on one platform."""
    return os.name == "nt"


def settings_dir() -> Path:
    """The directory the settings file lives in (D2).

    Addressed from the environment, never from ``__file__`` — see the
    module docstring for why that distinction is the whole point.
    """
    if _is_windows():
        base = os.environ.get("APPDATA", "").strip()
        if not base:
            base = str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", "").strip()
        if not base:
            base = str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME


def settings_path() -> Path:
    return settings_dir() / SETTINGS_FILE_NAME


#: The provider value meaning *the user has not been asked yet*.
UNCHOSEN = ""


def defaults() -> Dict[str, Any]:
    """The configuration before the user has chosen anything.

    **The provider is deliberately unset, and this is the fix for the
    worst defect this wave's review found.** An earlier version of this
    function shipped ``provider="local"`` on the reasoning that D1
    preselects local. D1 preselects it *in the popup* — it does not make
    it the effective configuration before the popup exists.

    Asserting it here was silently catastrophic. ``key_required("local")``
    is ``False``, so a fresh install with no settings file waived the key
    gate at every layer; meanwhile nothing yet read ``endpoint``, so the
    request still went to ``resolve_openai_base_url()``. A run the store
    called *local* was therefore sent to **the paid vendor endpoint**,
    with the literal string ``"local"`` as the credential — or, because
    the launch modal cannot be dismissed without a key, with the user's
    **real** key, billing their account for a run labelled local. Before
    that change the same user was correctly blocked at ``NO_KEY``.

    ``UNCHOSEN`` is not in ``_KEYLESS_PROVIDERS``, so an unconfigured
    install behaves exactly as it did before this wave: a key is
    required, and the endpoint falls through to the environment and then
    to the vendor default. The store becomes authoritative only once
    something has written a real choice into it.
    """
    return {
        "schema": SCHEMA,
        "provider": UNCHOSEN,
        "endpoint": "",
        "api_key": "",
        "model": "",
        "batch_size": 5,
        "stages": {},
    }


def load_settings() -> Dict[str, Any]:
    """Read the settings file, filling in anything absent from defaults.

    Absent is not unreadable: a missing file is the shipped configuration;
    a file that exists and cannot be parsed raises.
    """
    path = settings_path()
    if not path.exists():
        return defaults()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise SettingsUnreadableError(
            f"Could not read {path}: {e.__class__.__name__}: {e}\n\n"
            f"It has been left exactly as it is. Repair or delete it; "
            f"metaScreener will not overwrite a settings file it cannot "
            f"understand."
        ) from e
    if not isinstance(raw, dict):
        raise SettingsUnreadableError(
            f"{path} does not contain a JSON object, so it is not a "
            f"metaScreener settings file. It has been left unchanged."
        )
    merged = defaults()
    merged.update(raw)          # unknown keys survive; missing keys default
    # The container was validated and its entries were not, so a file
    # that is structurally wrong passed this gate and crashed later with
    # an unrelated exception type instead of the SettingsUnreadableError
    # this module promises. Entries that are not mappings are dropped;
    # `provider` is coerced, because `key_required` calls `.strip()` on
    # it and an integer there raised an AttributeError on a GUI
    # construction path. Found in this session's review.
    stages = merged.get("stages")
    merged["stages"] = ({
        str(k): dict(v) for k, v in stages.items() if isinstance(v, dict)
    } if isinstance(stages, dict) else {})
    if not isinstance(merged.get("provider"), str):
        merged["provider"] = UNCHOSEN
    for key in ("endpoint", "api_key", "model"):
        if not isinstance(merged.get(key), str):
            merged[key] = ""
    return merged


def save_settings(data: Mapping[str, Any]) -> Path:
    """Write the settings file atomically, following F-139's rules."""
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Follow a symlink to its target, so the link is updated rather than
    # replaced by a regular file.
    target = Path(os.path.realpath(path)) if path.is_symlink() else path

    mode: Optional[int] = None
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except OSError as e:
        if e.errno not in (errno.ENOENT,):
            raise

    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(
            json.dumps(dict(data), indent=2, ensure_ascii=False,
                       sort_keys=True) + "\n",
            encoding="utf-8",
        )
        # The file may hold an API key: 0o600 for a new file, and an
        # existing file's mode preserved rather than widened.
        try:
            os.chmod(tmp, mode if mode is not None else 0o600)
        except (OSError, NotImplementedError):
            pass                # best effort; Windows has no POSIX modes
        os.replace(tmp, target)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass                # a stray copy of a secret is its own defect
        raise
    return path


def update_settings(**changes: Any) -> Dict[str, Any]:
    """Read, apply ``changes``, write. Unrelated keys are preserved."""
    current = load_settings()
    current.update(changes)
    save_settings(current)
    return current


def set_stage_override(stage: str, *, model: Optional[str] = None,
                       **extra: Any) -> Dict[str, Any]:
    """Set or clear one stage's override of an app-level value.

    An empty or whitespace-only value **clears** the override rather than
    storing one that resolves to nothing. That is F-93's shape: a
    whitespace-only field is truthy, survives an ``or`` fallback and
    reaches the engine as ``""``, which the engine takes as "no model"
    and skips silently.
    """
    current = load_settings()
    stages = dict(current.get("stages") or {})
    entry = dict(stages.get(stage) or {})

    updates = dict(extra)
    if model is not None:
        updates["model"] = model

    for key, value in updates.items():
        if isinstance(value, str) and not value.strip():
            entry.pop(key, None)
        else:
            entry[key] = value.strip() if isinstance(value, str) else value

    if entry:
        stages[stage] = entry
    else:
        stages.pop(stage, None)
    current["stages"] = stages
    save_settings(current)
    return current


def effective(settings: Mapping[str, Any], stage: str, key: str,
              fallback: Any = "") -> Any:
    """Resolve one value: per-stage override, then app level, then
    ``fallback``. Whitespace never wins — see ``set_stage_override``."""
    stages = settings.get("stages") or {}
    entry = stages.get(stage) or {}
    for source in (entry, settings):
        value = source.get(key)
        if isinstance(value, str):
            if value.strip():
                return value.strip()
        elif value is not None:
            return value
    return fallback


def effective_model(settings: Mapping[str, Any], stage: str) -> str:
    return effective(settings, stage, "model", "")


#: What goes in the SDK's ``api_key`` slot for a server that ignores it.
#: Not a secret and not a credential — a placeholder the OpenAI client
#: requires to be non-empty before it will construct.
PLACEHOLDER_KEY = "local"


def placeholder_key_for(provider: str, api_key: Optional[str]) -> str:
    """The key to hand the client, which is not always the user's key.

    The SDK refuses to construct with an empty ``api_key`` even against a
    server that never reads it. Before F-117 that requirement was pushed
    onto the user: the ``NO_KEY`` message told every user to type a
    placeholder such as ``"local"``. Asking someone to invent a fake
    credential to reach a free local model is a GUI-first defect wearing a
    security gate's clothes, so the application satisfies the SDK itself.

    A real key is never replaced, so a local server that *does*
    authenticate still works. And ``openai`` is never given a placeholder:
    substituting one would turn "you forgot your key" into a 401 from the
    vendor — a worse error, further from its cause.
    """
    real = (api_key or "").strip()
    if real:
        return real
    from plugins._common.stage_state import key_required
    return "" if key_required(provider) else PLACEHOLDER_KEY


def mixed_models(settings: Mapping[str, Any],
                 stages: Iterable[str]) -> Tuple[str, ...]:
    """The distinct models the given stages would use, if more than one.

    Empty when they agree. The row this closes says accidental mixed-model
    pipelines are the *default* rather than an edge case and that nothing
    detects or records the disagreement — which is F-88 again, since no
    artefact would show it. Now something does: the caller reports this on
    the run, and F-88's provenance block records what each stage actually
    used.
    """
    seen = {effective_model(settings, s) for s in stages}
    seen.discard("")
    return tuple(sorted(seen)) if len(seen) > 1 else ()
