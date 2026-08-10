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
import urllib.error
import urllib.request
from dataclasses import dataclass
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
_LAST_PROBE: Optional["Detection"] = None


def last_known() -> Optional["Detection"]:
    """The most recent detection, or ``None`` if none has run yet."""
    return _LAST_PROBE


def remember(detection: Optional["Detection"]) -> None:
    global _LAST_PROBE
    _LAST_PROBE = detection


def forget() -> None:
    """Drop the cached status, so the next read reports *not yet checked*.

    Called when the provider changes: the previous answer describes a
    server the user is no longer pointing at, and reporting it would be a
    stale-cache defect of the kind this project keeps finding.
    """
    remember(None)


def refresh(endpoint: str, *, timeout: float = DEFAULT_TIMEOUT,
            which: Optional[Callable[[str], Optional[str]]] = None,
            api_key: str = "", provider: str = "") -> "Detection":
    """Detect and cache. Safe to call from a worker thread."""
    d = detect(endpoint, timeout=timeout, which=which,
               api_key=api_key, provider=provider)
    remember(d)
    return d


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
