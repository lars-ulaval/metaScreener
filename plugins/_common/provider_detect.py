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
