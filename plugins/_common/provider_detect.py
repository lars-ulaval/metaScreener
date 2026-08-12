# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""Provider detection and model discovery — D4, D5, F-121.

Three failure states, because they are three different problems with
three different remedies:

======================  ==========================================
``NOT_INSTALLED``       no ``ollama`` on ``PATH`` and nothing
                        answering — install it, or use OpenAI
``NOT_RUNNING``         the binary is there and nothing answers —
                        start the server
``NO_MODELS``           the server answers and has nothing pulled —
                        pull one (D3 offers to)
======================  ==========================================

Telling a user to run ``ollama serve`` when they have no Ollama, or to
install it when it is merely stopped, wastes their afternoon. That is the
whole reason these are separate states rather than one "unavailable".

Two rules this module never breaks
----------------------------------
**It does not require Ollama to exist.** A machine with no Ollama at all
is a supported configuration; that user goes to OpenAI, and nothing about
their launch is slower or noisier for it. Every failure is a *state*, not
an exception — a launch path that can raise is a launch path that can
fail to launch.

**It does not start anything.** D5 says detect that the server is down,
give the command, and do not run it: metaScreener does not launch
background processes. So detection is ``shutil.which`` plus one HTTP GET,
and the absence of ``subprocess`` is asserted against this file's source
rather than mocked, so that adding one fails a test rather than appearing
in a user's process table.

Why the binary check is secondary
---------------------------------
If the server answers, whether a local binary exists is irrelevant — the
endpoint may be a remote Ollama, LM Studio, llama.cpp or vLLM, which all
speak the same wire protocol. ``which`` therefore only ever discriminates
the *message* in the case where nothing answered.

Discovery is an aid, never a gate
---------------------------------
``list_models`` returns an empty tuple on any failure rather than
raising, because the model control is an *editable* combobox: llama.cpp
ignores the model field entirely, so a readonly dropdown fed from this
would rebuild the enumeration problem the project keeps removing. A user
whose server will not list models must still be able to type one.

**Which path a caller takes matters (wave 11 session C).**
``list_models`` answers *what names are there* and flattens every failure
into ``()``, which is right for a caller whose remedy is identical in all
of them. A **stage tab** is not that caller: it must say *install
Ollama*, *start it with ``ollama serve``* and *pull a model* differently,
because those are three different actions. So the tabs use ``detect``
plus :func:`model_choices`, which carries the state and the message
through; the flattening helper is left alone rather than changed to suit
a caller it was not written for.
"""
from __future__ import annotations

import json
import shutil
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from time import monotonic
from typing import Callable, Optional, Tuple

READY = "ready"
NO_MODELS = "no_models"
NOT_RUNNING = "not_running"
NOT_INSTALLED = "not_installed"

STATES = (READY, NO_MODELS, NOT_RUNNING, NOT_INSTALLED)

#: Long enough for a loaded local server to answer a metadata call, short
#: enough that a launch path never feels stalled. Detection is expected to
#: run off the GUI thread regardless; this bounds the worst case.
DEFAULT_TIMEOUT = 2.0

OLLAMA_BINARY = "ollama"
OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"


@dataclass(frozen=True)
class Detection:
    """What was found, and what to tell the user about it."""

    state: str
    models: Tuple[str, ...] = ()
    detail: str = ""
    endpoint: str = ""

    @property
    def can_use(self) -> bool:
        """Whether a run could start against this provider right now."""
        return self.state == READY


# ---------------------------------------------------------------------------
# The last known status, shared between the app and the stage views
# ---------------------------------------------------------------------------
#
# Readiness must mean *reachable*, and the stage views decide readiness
# inside Tk callbacks — where a network call is exactly what must not
# happen. So detection runs off the GUI thread, deposits its answer here,
# and the views read it synchronously.
#
# ``None`` means *not yet checked*, which readiness reports as its own
# state rather than treating as either outcome. A module global rather
# than a field on the app object because the stage views are constructed
# by the plugin loader and do not have a reference to it.
# **Keyed by endpoint, and that is wave 11 session C's review talking.**
#
# It was one global. Session C then gave each stage its own endpoint, and
# the two together produced the defect session B's whole design exists to
# prevent: the application probed *its* endpoint, deposited the answer
# here, and a stage pointed somewhere else read it and reported
# ``Ready to run``. Measured, with nothing listening on EL's endpoint:
#
#     app endpoint probed : ... -> ready
#     EL readiness        : ready can_run=True 'Ready to run'
#     direct probe of EL's own endpoint: not_installed
#
# "Ready" must mean *this stage's server answered*, so the cache has to be
# per server. A stage whose endpoint nobody has probed now reads ``None``
# — ``NOT_CHECKED``, which blocks — rather than inheriting somebody
# else's answer. Being told nothing stays its own state.
_PROBES: "dict[str, Detection]" = {}


def _probe_key(endpoint: Optional[str]) -> str:
    """One server, one entry.

    Trailing slashes and case in the scheme/host are not routing
    differences, and leaving them in would give one server two entries —
    so the tab that probed and the tab that reads could disagree about a
    server they both point at. Deliberately *not* the same normalisation
    the cache key uses: that one must not normalise at all (F-89), because
    it partitions stored answers rather than an in-memory lookup.
    """
    return (endpoint or "").strip().rstrip("/").lower()


def last_known(endpoint: Optional[str] = None) -> Optional["Detection"]:
    """The most recent detection **for this endpoint**, or ``None``.

    ``None`` for an endpoint nobody has probed. Callers must pass the
    endpoint they are asking about; the no-argument form answers only
    when exactly one server has been probed, which keeps the single-
    provider case working without letting a multi-endpoint configuration
    silently pick one.
    """
    if endpoint is None:
        return next(iter(_PROBES.values())) if len(_PROBES) == 1 else None
    return _PROBES.get(_probe_key(endpoint))


def remember(detection: Optional["Detection"],
             endpoint: Optional[str] = None) -> None:
    """File a detection under the endpoint it describes.

    ``endpoint`` wins over the one the detection carries, because the
    caller knows which server it asked about and the answer may not —
    ``refresh`` passes it for exactly that reason. ``None`` is a no-op
    rather than a stored absence: *not yet checked* is the absence of an
    entry, which is what ``forget`` produces.
    """
    if detection is None:
        return
    key = _probe_key(endpoint if endpoint is not None
                     else getattr(detection, "endpoint", ""))
    _PROBES[key] = detection


def forget(endpoint: Optional[str] = None) -> None:
    """Drop cached status, so the next read reports *not yet checked*.

    Called when the provider changes: the previous answer describes a
    server the user is no longer pointing at, and reporting it would be a
    stale-cache defect of the kind this project keeps finding. Without an
    endpoint it clears everything, which is what a provider change means.
    """
    if endpoint is None:
        _PROBES.clear()
    else:
        _PROBES.pop(_probe_key(endpoint), None)


def known_endpoints() -> Tuple[str, ...]:
    """Which servers have been probed. For tests and for diagnostics."""
    return tuple(sorted(_PROBES))


def refresh(endpoint: str, *, timeout: float = DEFAULT_TIMEOUT,
            which: Optional[Callable[[str], Optional[str]]] = None,
            api_key: str = "", provider: str = "") -> "Detection":
    """Detect and cache. Safe to call from a worker thread."""
    d = detect(endpoint, timeout=timeout, which=which,
               api_key=api_key, provider=provider)
    # Filed under the endpoint we ASKED about, not the one the answer
    # reports. They are the same in production; keeping the caller
    # authoritative means a detector that forgot to echo the endpoint
    # cannot silently file its answer where no stage will find it.
    remember(d, endpoint)
    return d


# ----------------------------
# Compute mode — VRAM or system RAM (F-150)
# ----------------------------

COMPUTE_GPU = "gpu"
COMPUTE_CPU = "cpu"
COMPUTE_PARTIAL = "partial"
COMPUTE_UNKNOWN = "unknown"

COMPUTE_MODES = (COMPUTE_GPU, COMPUTE_CPU, COMPUTE_PARTIAL, COMPUTE_UNKNOWN)
"""Where the loaded model is actually running.

``COMPUTE_UNKNOWN`` is not a failure state and must never be reported as
``COMPUTE_CPU``. A server that is not Ollama has no ``/api/ps`` route at
all, and Ollama unloads idle models, so "we cannot say" is the ordinary
answer rather than the exceptional one. Telling a user with a working GPU
that they are on the CPU would send them to reinstall drivers they never
needed to touch — the same harm as conflating D5's three messages.
"""


@dataclass(frozen=True)
class ComputeMode:
    """What the server says about where it is running the model.

    ``known`` is redundant with ``mode != COMPUTE_UNKNOWN`` and is kept
    because the callers that matter are asking *"may I say anything at
    all?"*, and a caller that has to know the vocabulary to ask that
    question is a caller that can get it wrong.
    """

    mode: str
    detail: str
    model: str = ""

    @property
    def known(self) -> bool:
        return self.mode != COMPUTE_UNKNOWN


#: Ollama's `/api/ps` answer lists loaded models and nothing else; it is
#: a few hundred bytes. A cap three orders of magnitude above that is not
#: a limit anyone can reach honestly, and it bounds the damage a
#: misconfigured endpoint can do to a GUI thread.
_MAX_PS_BYTES = 512 * 1024


def _read_bounded(resp, timeout: float,
                  max_bytes: int = _MAX_PS_BYTES) -> bytes:
    """Read a response body under a **total** time and size bound.

    F-157. ``urlopen(..., timeout=t)`` bounds each socket operation, not
    the whole transfer. A server that sends its headers promptly and then
    dribbles the body never trips that timeout — every individual read
    arrives inside it — while the call as a whole takes as long as the
    server likes. Measured before this existed: a 4 KB body in 20 chunks
    held a 1.0-second call for 6.0 seconds.

    That is a GUI defect rather than a networking one, because
    ``compute_mode``'s caller runs on the GUI thread deliberately: the
    pre-run confirmation has to have the answer before the user decides,
    so the alternative to blocking briefly is showing the dialog and
    correcting it afterwards. Blocking briefly is the right trade; the
    bound is what keeps "briefly" true.

    Deliberately returns what it has rather than raising when the budget
    runs out. The caller parses the result and every failure there is
    already ``COMPUTE_UNKNOWN``, which is the honest answer for a server
    that would not finish a sentence.
    """
    deadline = monotonic() + max(0.0, float(timeout))
    # `read1` returns what has already arrived; `read(n)` blocks until it
    # has all n bytes or the stream ends, which would swallow an entire
    # slow transfer in ONE call and leave the deadline below checked
    # exactly once. That distinction is the whole fix: with `read` the
    # measured overrun stayed at 6.0s against a 1.0s budget.
    read = getattr(resp, "read1", None) or resp.read
    chunks = []
    total = 0
    truncated = False
    while total < max_bytes:
        if monotonic() > deadline:
            truncated = True
            break
        chunk = read(8192)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    body = b"".join(chunks)

    # F-162(c). `read()` raised ``IncompleteRead`` when the server sent
    # fewer bytes than it declared; ``read1`` returns b"" at EOF and says
    # nothing, so swapping to it for F-157 silently dropped the only
    # transport-level check that a confident answer describes a response
    # the server actually finished. Restored here rather than by going
    # back to ``read`` — the reason ``read1`` was chosen is still good.
    #
    # An exhaustive prefix search found no body that parses to one answer
    # whose truncation parses to a *different* one, so this was never a
    # route to a WRONG mode; what it cost was the ability to tell a
    # complete answer from a partial one, which is the difference between
    # ``cpu`` and ``unknown``.
    if not truncated:
        declared = getattr(getattr(resp, "headers", None), "get", lambda _k: None)(
            "Content-Length")
        if declared is not None:
            try:
                truncated = len(body) < int(declared)
            except (TypeError, ValueError):
                pass
    if truncated:
        # Empty parses to nothing, and every parse failure downstream is
        # already COMPUTE_UNKNOWN — the honest answer for a server that
        # would not finish a sentence.
        return b""
    return body


def _fetch_within_budget(url: str, timeout: float,
                         max_bytes: int = _MAX_PS_BYTES) -> Optional[bytes]:
    """Run the whole exchange under a bound the **caller** can rely on.

    F-162, and the reason F-157 did not finish the job. ``urlopen`` returns
    only after ``http.client`` has read the status line **and every
    header**, so :func:`_read_bounded` — which runs inside the ``with``
    block — cannot bound that phase at all. A server that dribbles header
    bytes, each arriving inside the per-operation socket timeout, is
    bounded by nothing: measured at ``timeout=1.0``, 8 padding bytes held
    the call 4.28 s, 40 held it 12.29 s, 120 held it 32.33 s — linear in
    header size, independent of the timeout, and every one of them
    returning a confident answer rather than an error.

    Through a real Tk mainloop that was **20.75 s of frozen application**
    on the pre-run confirmation, on both LLM stages. F-157's row called
    that "the most visible failure this wave could have shipped"; it was
    describing the defect its own fix left in place.

    So the bound moved off the phases and onto the call. The exchange runs
    on a daemon worker and the caller waits exactly ``timeout``; if the
    worker has not finished by then the answer is ``None`` and the caller
    reports ``COMPUTE_UNKNOWN``. **The GUI thread is now blocked by the
    budget rather than by the server**, which is the property
    ``ELView._confirm_run`` needs and the one it was documented as having.

    The orphaned worker is deliberate and is bounded twice over: the
    socket keeps its own ``timeout``, so it cannot outlive a server that
    stops sending, and the thread is a daemon, so it can never hold up
    interpreter exit. Cancelling it properly would mean owning the socket,
    which is a larger change than this row is worth — recorded rather than
    hidden.
    """
    box = {}

    def _work():
        try:
            req = urllib.request.Request(
                url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if getattr(resp, "status", 200) != 200:
                    return
                box["body"] = _read_bounded(resp, timeout, max_bytes)
        except Exception:
            pass

    worker = threading.Thread(target=_work, daemon=True,
                              name="metascreener-compute-mode")
    worker.start()
    worker.join(max(0.0, float(timeout)))
    if worker.is_alive():
        return None
    return box.get("body")


def compute_mode_url(endpoint: str) -> str:
    """Ollama's native ``/api/ps``, derived from the compatible endpoint.

    Same derivation as ``model_pull.pull_url``, and for the same reason:
    ``/api/ps`` lives on Ollama's own surface, not on the
    OpenAI-compatible ``/v1`` one.
    """
    base = (endpoint or "").rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return base + "/api/ps"


def compute_mode(endpoint: str, *, model: str = "",
                 timeout: float = DEFAULT_TIMEOUT) -> ComputeMode:
    """Whether the loaded model sits in VRAM or in system RAM.

    F-150. The maintainer's run took hours and pegged his CPU, and his
    own Ollama log explains it: ``inference compute id=cpu library=cpu``,
    ``total_vram="0 B"`` — Ollama never found his RTX 3060. metaScreener
    cannot fix that and does not try; GPU detection is Ollama's business
    and the user's machine is not ours to configure. What it can do is
    say so *before* a four-hour run instead of after, and Ollama already
    publishes the fact.

    Never raises, and never guesses. Every failure — unreachable, a
    server with no such route, a shape this code does not recognise, an
    absent ``size_vram`` on an older build, or simply no model loaded —
    is ``COMPUTE_UNKNOWN``. Absent is not zero (F-68), and "no model
    loaded" says nothing about where the next one will run.
    """
    # F-162. The whole exchange is bounded, not just the body — see
    # ``_fetch_within_budget``. This function is called on the GUI thread
    # on purpose, so "bounded" has to mean the call, not a phase of it.
    body = _fetch_within_budget(compute_mode_url(endpoint), timeout)
    if not body:
        return _compute_unknown()
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return _compute_unknown()

    if not isinstance(payload, dict):
        return _compute_unknown()
    entries = payload.get("models")
    if not isinstance(entries, list) or not entries:
        return _compute_unknown()

    wanted = (model or "").strip()
    chosen = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or entry.get("model") or "").strip()
        if wanted and name == wanted:
            chosen = entry
            break
        if not wanted and chosen is None:
            chosen = entry
    # F-153, found by the wave 12 review. When a model was named and was
    # NOT among the loaded ones, this fell back to the first entry and
    # reported ITS placement -- a confident answer about the wrong model.
    # A user about to run gemma on the CPU would have been told "GPU"
    # because something else happened to be resident.
    #
    # Not knowing is already a first-class state here, and this is one of
    # its cases: Ollama unloads idle models, so "the model you asked about
    # is not loaded" is ordinary and says nothing about where it will run.
    if not isinstance(chosen, dict):
        return _compute_unknown()

    size = chosen.get("size")
    vram = chosen.get("size_vram")
    # Both fields required, and required to be numbers. An older Ollama
    # that does not publish `size_vram` must read as "cannot say" rather
    # than as "zero bytes in VRAM", which would be a confident and wrong
    # claim about someone's working GPU.
    if not isinstance(size, (int, float)) or not isinstance(vram, (int, float)):
        return _compute_unknown()
    if size <= 0:
        return _compute_unknown()

    name = str(chosen.get("name") or chosen.get("model") or "").strip()
    if vram <= 0:
        return ComputeMode(
            COMPUTE_CPU,
            "This server is running the model on the CPU — no GPU memory "
            "is in use. Screening will work, and it will be considerably "
            "slower than on a GPU.",
            name)
    if vram >= size:
        return ComputeMode(
            COMPUTE_GPU,
            "This server is running the model in GPU memory.", name)
    pct = int(round(100.0 * float(vram) / float(size)))
    return ComputeMode(
        COMPUTE_PARTIAL,
        f"This server is running about {pct}% of the model in GPU memory "
        f"and the rest on the CPU. Expect speeds between the two.",
        name)


def _compute_unknown() -> ComputeMode:
    return ComputeMode(
        COMPUTE_UNKNOWN,
        "This server does not report where it is running the model, so "
        "the speed cannot be anticipated here.",
        "")


def _models_url(endpoint: str) -> str:
    return (endpoint or "").rstrip("/") + "/models"


def _fetch_models(endpoint: str, timeout: float,
                  api_key: str = "") -> Optional[Tuple[str, ...]]:
    """One request, tri-state.

    ``None`` means *the endpoint did not answer usably*; a tuple means it
    answered, and may be empty. Those two must never be conflated —
    "answered with nothing pulled" means pull a model, "did not answer"
    means start a server, and D5 exists because telling a user the wrong
    one wastes their afternoon.

    One request rather than two: an availability probe followed by a list
    call doubles the latency on a launch path, and the two could observe
    different states either side of a server starting or stopping.
    """
    # Authenticated when a key is available. Session B's review found the
    # unauthenticated form making the vendor **permanently unreachable**:
    # api.openai.com answers 401, urlopen raises, and a user with a valid
    # key was told to install Ollama. A probe that cannot succeed for a
    # supported provider is not a reachability check, it is a refusal.
    headers = {"Accept": "application/json"}
    if (api_key or "").strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    try:
        req = urllib.request.Request(_models_url(endpoint), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    entries = payload.get("data")
    if not isinstance(entries, list):
        # Answered, and in a shape this code does not understand. That is
        # a reachable server with nothing usable to offer, not a dead one.
        return ()

    names = set()
    for entry in entries:
        if isinstance(entry, dict):
            name = entry.get("id")
            if isinstance(name, str) and name.strip():
                names.add(name.strip())
    return tuple(sorted(names))


def list_models(endpoint: str,
                timeout: float = DEFAULT_TIMEOUT) -> Tuple[str, ...]:
    """The model ids the endpoint reports, or ``()`` if it will not say.

    Never raises. Every failure — unreachable, timeout, non-200,
    non-JSON, unexpected shape — is an empty tuple, because the caller's
    remedy is identical in all of them: let the user type a name.
    Discovery is an aid, never a gate.
    """
    return _fetch_models(endpoint, timeout) or ()


#: What a stage tab shows before any detection has run. Not a detection
#: state — ``last_known()`` returning ``None`` is the absence of one, and
#: "we have not looked" is a different claim from any of the four.
NOT_CHECKED = "not_checked"


@dataclass(frozen=True)
class ModelChoices:
    """What the model control offers, and what the line under it says.

    ``values``
        the names to drop down. **Never a constraint** — the control is
        an editable combobox, so this is a list of suggestions, and an
        empty one is a control with no suggestions rather than a control
        that cannot be used.
    ``note``
        one line, carried through from detection **verbatim** where
        detection had something to say. D4/D5 turn on three distinct and
        actionable messages; flattening them into one "unavailable" is
        the wasted afternoon those decisions exist to prevent, and
        discovery is the second place that flattening could happen.
    ``state``
        which detection state produced this, or ``NOT_CHECKED``. Carried
        so the caller can style or log it without re-deriving the
        classification — two derivations of one fact is F-69's shape.
    """

    values: Tuple[str, ...]
    note: str
    state: str


def model_choices(detection: Optional["Detection"]) -> ModelChoices:
    """Turn a detection into what the model control should show.

    **Discovery is an aid, never a gate.** Every branch here returns a
    usable control: the user can always type a name and always press Run,
    and whether the run may start is ``llm_readiness``'s question, not
    this one. Nothing in this function or its callers disables a widget,
    and nothing here returns a value that could be read as "you may not
    proceed".

    The three failures the brief names, and what each shows:

    * **the call fails** (refused, non-200, non-JSON, an unexpected
      shape): no suggestions, and detection's own message — *install
      Ollama* or *start it with ``ollama serve``*, whichever applies,
      because those are different problems;
    * **the call times out**: identical to the above by construction —
      ``_fetch_models`` returns ``None`` for a timeout exactly as it does
      for a refusal, and the remedy the user needs is the same one;
    * **the call returns nothing**: no suggestions, and *the server is
      running but has no models pulled yet*, which is a **third**
      message, because pulling a model and starting a server are
      different actions.

    And before any of them, ``None`` — not yet checked — which says so
    rather than showing an empty list as though the server had answered.
    """
    if detection is None:
        return ModelChoices(
            (), "Checking what this server offers…", NOT_CHECKED)

    models = tuple(getattr(detection, "models", ()) or ())
    state = getattr(detection, "state", "") or ""
    detail = (getattr(detection, "detail", "") or "").strip()

    if state == READY and models:
        return ModelChoices(
            models,
            f"{len(models)} model(s) offered by this server. "
            f"You can also type a name that is not listed.",
            READY)

    # Everything else: no suggestions, detection's own words, and a
    # control that still works. The fallback line is only reached if a
    # detection arrives with no detail, which the detector never does.
    return ModelChoices(
        (), detail or "This server did not offer a list of models. "
                      "Type the name you want to use.", state)


def detect(endpoint: str, *, timeout: float = DEFAULT_TIMEOUT,
           which: Optional[Callable[[str], Optional[str]]] = None,
           api_key: str = "", provider: str = "") -> Detection:
    """Classify a provider endpoint without starting anything.

    ``which`` is injected so both branches of the binary check can be
    driven on a machine that has Ollama and on one that does not.
    """
    which = which or shutil.which

    models = _fetch_models(endpoint, timeout, api_key)
    if models is not None:
        if models:
            return Detection(READY, models,
                             f"{len(models)} model(s) available.", endpoint)
        return Detection(
            NO_MODELS, (),
            "The server is running but has no models pulled yet. "
            "Pull one to start screening — a recommended model is offered "
            "below.",
            endpoint)

    # The Ollama discrimination only makes sense for a local endpoint.
    # Telling a user on OpenAI to run `ollama serve`, or to install Ollama,
    # sends them to fix something that has nothing to do with their
    # problem — the wasted afternoon D4/D5 exist to prevent, produced by
    # the very code meant to prevent it.
    if provider and provider not in ("local", ""):
        return Detection(
            NOT_RUNNING, (), endpoint=endpoint,
            detail=("The configured endpoint did not answer. Check the "
                    "endpoint and the API key, and that this machine can "
                    "reach it."))

    try:
        installed = bool(which(OLLAMA_BINARY))
    except Exception:
        installed = False

    if installed:
        return Detection(
            NOT_RUNNING, (),
            "Ollama is installed but not responding at this endpoint. "
            "Start it with `ollama serve`, then try again. "
            "metaScreener will not start it for you.",
            endpoint)

    return Detection(
        NOT_INSTALLED, (),
        "No local model server was detected at this endpoint, and Ollama "
        f"was not found on PATH. Install it from {OLLAMA_DOWNLOAD_URL}, or "
        "switch to OpenAI, which needs no local install.",
        endpoint)
