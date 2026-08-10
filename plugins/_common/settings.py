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
from dataclasses import dataclass
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
        # **Not chosen**, not 5. Session A shipped ``5`` here and nothing
        # read it; session C made the store's batch size live, and the
        # value would then have silently dropped every stage — including
        # a stage running against OpenAI — from the module default of 50
        # to 5, i.e. ten times the requests, with nothing said. Measured
        # before the change shipped, not after.
        #
        # ``None`` means *nobody has chosen*, which lets
        # ``stage_state.recommended_batch_size`` answer for the provider
        # (D6) and the stage's own module default answer otherwise. A
        # concrete number here is a choice this file is not entitled to
        # make, because it cannot see which provider is selected.
        "batch_size": None,
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


#: Keys a stage may override. **``provider`` is deliberately absent, and
#: that is a safety property rather than an omission.**
#:
#: There is one provider conversation, at the application level, and
#: ``llm_readiness`` blocks an unchosen provider *ahead of* the key and
#: model checks precisely because those can each be satisfied while the
#: path as a whole is unconfigured. A stage-level provider would let a
#: stage acquire an effective provider while the application is still
#: ``UNCHOSEN`` — a path reaching a run without passing that check, which
#: is the exact shape session B closed.
#:
#: Nothing is lost by refusing it. A stage that must talk to a different
#: OpenAI-compatible server says so with an **endpoint** override; that is
#: what the ``custom`` provider means and why one URL field covers LM
#: Studio, llama.cpp and vLLM at once.
STAGE_OVERRIDABLE = ("model", "endpoint", "batch_size")


class StageOverrideRefused(ValueError):
    """A key that must not vary per stage was offered as an override."""


def set_stage_override(stage: str, **updates: Any) -> Dict[str, Any]:
    """Set or clear one stage's override of an app-level value.

    An empty or whitespace-only value **clears** the override rather than
    storing one that resolves to nothing. That is F-93's shape: a
    whitespace-only field is truthy, survives an ``or`` fallback and
    reaches the engine as ``""``, which the engine takes as "no model"
    and skips silently.

    Only :data:`STAGE_OVERRIDABLE` may be overridden; anything else
    raises. See that constant for why ``provider`` is not among them.

    ``model`` used to be a named parameter for which ``None`` meant *not
    supplied*, while ``None`` in ``**extra`` meant nothing at all. Two
    readings of one value in one signature is the shape this project
    keeps finding, so it is now uniform: **``None`` clears, everywhere.**
    """
    refused = sorted(set(updates) - set(STAGE_OVERRIDABLE))
    if refused:
        raise StageOverrideRefused(
            f"{', '.join(refused)} cannot vary per stage; only "
            f"{', '.join(STAGE_OVERRIDABLE)} can. A stage that must reach a "
            f"different server says so with an endpoint override."
        )
    current = load_settings()
    stages = dict(current.get("stages") or {})
    entry = dict(stages.get(stage) or {})

    for key, value in updates.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            # ``None`` clears too, so a caller can retract a numeric
            # override the same way it retracts a text one. Without it the
            # only way to un-set ``batch_size`` would be to rewrite the
            # whole entry, and a retraction that is harder than a set is a
            # retraction that does not happen.
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


def placeholder_key_for(provider: str, api_key: Optional[str], *,
                        endpoint: Optional[str] = None) -> str:
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

    **Session C decides this on the resolved pair.** A stage whose
    endpoint override points at the paid vendor must not be handed the
    literal string ``"local"`` as its credential because its *provider*
    field says local — that is the wave's billing defect wearing the
    credential's clothes. ``endpoint=None`` means unknown and reduces to
    the provider-only question.
    """
    real = (api_key or "").strip()
    if real:
        return real
    from plugins._common.stage_state import key_required_for
    return "" if key_required_for(provider, endpoint) else PLACEHOLDER_KEY


# ---------------------------------------------------------------------------
# The effective configuration of one stage
# ---------------------------------------------------------------------------

#: Where the resolved endpoint came from. Reported rather than inferred,
#: because F-119's lesson is that a user needs to see *which* source won:
#: "endpoint=https://api.openai.com/v1" alone does not distinguish "I
#: chose the public API" from "my configuration was not read".
ENDPOINT_FROM_STAGE = "stage override"
ENDPOINT_FROM_APP = "application setting"
ENDPOINT_FROM_KEYLESS_DEFAULT = "keyless default"
ENDPOINT_FROM_ENVIRONMENT = "OPENAI_BASE_URL"
ENDPOINT_FROM_VENDOR_DEFAULT = "vendor default"


@dataclass(frozen=True)
class StageConfig:
    """What one stage will actually talk to, as plain data.

    Every field is resolved: per-stage override first, then the
    application setting, then the environment, then a default. Nothing
    downstream re-derives any of it — two places deciding what the
    endpoint is would be F-89's shape, where the cache key and the client
    could disagree about where a run went.
    """

    stage: str
    provider: str
    endpoint: str
    api_key: str
    model: str
    batch_size: Optional[int]
    endpoint_source: str


def resolve_stage(settings: Mapping[str, Any], stage: str = "", *,
                  env_endpoint: str = "",
                  env_api_key: str = "") -> StageConfig:
    """Resolve one stage's effective configuration.

    ``stage=""`` means *the application level*, and resolves to exactly
    what the application resolved to before per-stage overrides existed —
    which is what keeps the golden replays valid.

    The environment is passed in rather than read here so that this stays
    a pure function of its arguments: it is the one place the endpoint is
    decided, and a decision that reads ambient state cannot be tested
    over a cross product.

    **The endpoint order, and why each step is where it is**

    1. an explicitly configured endpoint — the stage override, then the
       application setting. A stored choice is what a GUI control writes,
       so anything in the environment beating it would make the control
       the user just operated do nothing (F-91's family);
    2. **a keyless provider falls back to the local default, never to the
       vendor.** Session B's invariant. Falling back to the local default
       is wrong-but-harmless; falling back to the paid vendor is
       wrong-and-billable, and the same shape arrives with no user error
       at all from any settings file naming a provider and omitting an
       endpoint;
    3. ``OPENAI_BASE_URL``;
    4. the vendor default.

    Note what this function does **not** do: it does not decide whether a
    key is required. That is
    ``stage_state.key_required_for(provider, endpoint)``, and it is a
    question about the resolved *pair* — see that function for why the
    provider string alone stopped being sufficient the moment a stage
    could point somewhere else.
    """
    provider = (settings.get("provider") or "").strip()

    configured = effective(settings, stage, "endpoint", "")
    if configured:
        stages = settings.get("stages") or {}
        entry = stages.get(stage) or {}
        source = (ENDPOINT_FROM_STAGE
                  if isinstance(entry.get("endpoint"), str)
                  and entry["endpoint"].strip()
                  else ENDPOINT_FROM_APP)
        endpoint, endpoint_source = configured, source
    elif provider and not _needs_key(provider):
        endpoint = DEFAULT_LOCAL_ENDPOINT
        endpoint_source = ENDPOINT_FROM_KEYLESS_DEFAULT
    elif (env_endpoint or "").strip():
        endpoint = env_endpoint.strip()
        endpoint_source = ENDPOINT_FROM_ENVIRONMENT
    else:
        endpoint = DEFAULT_OPENAI_ENDPOINT
        endpoint_source = ENDPOINT_FROM_VENDOR_DEFAULT

    # D6. When nobody has chosen a batch size, the provider gets to
    # suggest one — 50 JSON objects in one reply is where small models
    # lose track. ``None`` still means "no suggestion either", and the
    # stage's own module default answers.
    from plugins._common.stage_state import recommended_batch_size
    batch = effective(settings, stage, "batch_size",
                      recommended_batch_size(provider))
    try:
        batch = int(batch) if batch is not None else None
    except (TypeError, ValueError):
        batch = None

    return StageConfig(
        stage=stage,
        provider=provider,
        endpoint=endpoint,
        api_key=(effective(settings, stage, "api_key", "")
                 or (env_api_key or "").strip()),
        model=effective_model(settings, stage),
        batch_size=batch,
        endpoint_source=endpoint_source,
    )


def stage_overrides_for(settings: Mapping[str, Any], stage: str,
                        **fields: Any) -> Dict[str, Any]:
    """What to store so that ``stage`` resolves to the given field values.

    The rule that makes this more than a dict copy: **a field equal to
    what the stage would resolve to *without* an override stores
    nothing.** It is compared against a resolution with this stage's
    entry removed, not against the raw application key, because the two
    differ whenever a default is doing the work — an unconfigured install
    shows the vendor endpoint in the box while the application setting is
    empty.

    Without that rule, opening a tab and pressing Run would pin a copy of
    whatever the field happened to be showing. The application setting
    would then stop reaching that stage, silently, and the next time the
    user changed the provider the stage they were not looking at would
    keep the old endpoint. That is a stale-cache defect wearing a
    persistence feature's clothes, and this project has shipped its shape
    before.

    A cleared value is returned as ``None``/``""``, which
    :func:`set_stage_override` reads as *drop this override*.
    """
    refused = sorted(set(fields) - set(STAGE_OVERRIDABLE))
    if refused:
        raise StageOverrideRefused(
            f"{', '.join(refused)} cannot vary per stage; only "
            f"{', '.join(STAGE_OVERRIDABLE)} can."
        )

    bare = dict(settings)
    stages = dict(bare.get("stages") or {})
    stages.pop(stage, None)
    bare["stages"] = stages
    without = resolve_stage(bare, stage)

    baseline = {
        "model": without.model,
        "endpoint": without.endpoint,
        "batch_size": without.batch_size,
    }

    out: Dict[str, Any] = {}
    for key, value in fields.items():
        if value is None:
            out[key] = None
            continue
        wanted = value.strip() if isinstance(value, str) else value
        if key == "batch_size":
            try:
                wanted = int(wanted)
            except (TypeError, ValueError):
                out[key] = None
                continue
        out[key] = None if wanted == baseline.get(key) else wanted
    return out


def apply_stage_fields(stage: str, **fields: Any) -> Dict[str, Any]:
    """Persist a stage tab's fields as overrides, and return the store.

    The tab's widgets and the engine must not be able to disagree about
    where a run goes: the engine resolves from the store, so the widgets
    have to reach the store before the run starts, not after it. Calling
    this is what makes the control the user just operated true.
    """
    current = load_settings()
    return set_stage_override(
        stage, **stage_overrides_for(current, stage, **fields))


def _needs_key(provider: str) -> bool:
    """``stage_state.key_required``, imported lazily.

    The two modules are mutually dependent by design — the key predicate
    belongs with the readiness vocabulary and the store belongs here — so
    the import is deferred the same way :func:`placeholder_key_for` defers
    it.
    """
    from plugins._common.stage_state import key_required
    return key_required(provider)


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
