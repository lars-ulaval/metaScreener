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


def defaults() -> Dict[str, Any]:
    """The shipped configuration.

    ``local`` is preselected (D1). The recommended model name is **not** a
    constant here — see ``recommended_model``.
    """
    return {
        "schema": SCHEMA,
        "provider": "local",
        "endpoint": DEFAULT_LOCAL_ENDPOINT,
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
    if not isinstance(merged.get("stages"), dict):
        merged["stages"] = {}
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
