# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""Offering and performing a model pull — D3.

The ceremony here is not polish, and the reason is a defect this
repository already has. ``_run_clicked`` starts a **billable** operation
with no cost estimate, no request count and no confirmation, and the only
cost statement in the documentation is wrong by two to three orders of
magnitude (F-125). Adding a multi-gigabyte download with *less* ceremony
than that deserves would repeat the mistake in a form the user cannot
undo — bytes already pulled over a metered connection are not refundable.

So a pull is:

* **refusable** — the size is known and reportable before a byte moves,
  from :func:`recommended_models`, and the offer says so in words;
* **interruptible** — :func:`pull` takes a ``cancel`` event and checks it
  between chunks, so a stalled or enormous download can be abandoned;
* **honest** — the up-front figure is labelled an estimate, because it
  comes from a config file rather than from the server, and the server's
  own ``total`` supersedes it as soon as the stream reports one.

Where the model name lives, and why not here
--------------------------------------------
``plugins/_common/recommended_models.json``, which the documentation
points at, with a user override in the settings directory. **A model name
in a Python constant is the enumeration this project keeps removing** —
it makes a new model a code change and a release. A test asserts that no
model-name-shaped literal appears in this module, and a missing config
therefore offers *nothing* rather than falling back to something stale.

The file is read, never written, so the frozen build is fine: reading
from ``sys._MEIPASS`` works, and it is bundled by the spec's
``datas = [('plugins', 'plugins')]``. That is the half of F-144 that is
safe — it is *writing* into that directory that silently loses data.

No process is spawned. D5's rule extends here: a pull is not an excuse to
shell out to the ``ollama`` CLI.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

CONFIG_NAME = "recommended_models.json"

#: How long to wait for the connection and for each read. A pull can take
#: many minutes in total, so this bounds *silence*, not the whole
#: operation.
DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class RecommendedModel:
    name: str
    size_bytes: int
    note: str = ""

    @property
    def human_size(self) -> str:
        gb = self.size_bytes / 1_000_000_000
        if gb >= 1:
            return f"{gb:.1f} GB"
        return f"{self.size_bytes / 1_000_000:.0f} MB"


@dataclass(frozen=True)
class PullProgress:
    status: str
    completed: int
    total: int

    @property
    def fraction(self) -> float:
        return (self.completed / self.total) if self.total > 0 else 0.0


@dataclass(frozen=True)
class PullResult:
    ok: bool
    cancelled: bool = False
    error: str = ""


def _shipped_config_path() -> Path:
    return Path(__file__).resolve().parent / CONFIG_NAME


def user_config_path() -> Path:
    """A user copy, which survives reinstalling metaScreener."""
    from plugins._common.settings import settings_dir
    return settings_dir() / CONFIG_NAME


def _read(path: Path) -> Optional[dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def recommended_models() -> Tuple[RecommendedModel, ...]:
    """What to offer, from data. The user copy wins.

    Every failure — missing, unreadable, wrong shape — yields an empty
    tuple. Offering nothing is correct: the alternative is a stale name
    baked into code, which is the thing this indirection exists to
    prevent.
    """
    raw = _read(user_config_path()) or _read(_shipped_config_path())
    if not raw:
        return ()
    entries = raw.get("recommended")
    if not isinstance(entries, list):
        return ()
    out = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        name = str(e.get("name") or "").strip()
        try:
            size = int(e.get("size_bytes") or 0)
        except (TypeError, ValueError):
            size = 0
        if name and size > 0:
            out.append(RecommendedModel(name, size,
                                        str(e.get("note") or "").strip()))
    return tuple(out)


def offer_text(model: RecommendedModel) -> str:
    """What the user is told **before** anything is downloaded.

    "about" is load-bearing: the figure comes from a config file, not from
    the server, and presenting an approximation as a fact is how "a few
    thousand API calls" got into the documentation.
    """
    note = f" {model.note}" if model.note else ""
    return (
        f"Download {model.name}? This is about {model.human_size} and will "
        f"be stored by Ollama, not by metaScreener.{note}\n\n"
        f"You can cancel at any point; a partial download is discarded by "
        f"the server. metaScreener makes no claim about how well this model "
        f"screens — that has not been measured."
    )


def pull_url(endpoint: str) -> str:
    """The native pull endpoint derived from the OpenAI-compatible one.

    The stored endpoint ends in ``/v1``, which is Ollama's
    OpenAI-compatible surface and has **no** pull operation; pulling lives
    at ``/api/pull`` on the same host. Derived rather than stored so there
    is one endpoint to configure, not two that can disagree.
    """
    base = (endpoint or "").rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return base + "/api/pull"


def pull(endpoint: str, name: str, *,
         on_progress: Callable[[PullProgress], Any],
         cancel: Any,
         timeout: float = DEFAULT_TIMEOUT) -> PullResult:
    """Stream a model pull, reporting progress and honouring ``cancel``.

    Blocking: intended for a worker thread. Never raises — every failure
    is a :class:`PullResult`, because this is reached from a GUI action
    and an exception there is a traceback the user cannot act on.
    """
    if cancel is not None and cancel.is_set():
        # Checked before the request so a cancel that arrives first costs
        # nothing at all.
        return PullResult(ok=False, cancelled=True)

    body = json.dumps({"name": name, "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        pull_url(endpoint), data=body,
        headers={"Content-Type": "application/json"}, method="POST")

    last_ok = False
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                return PullResult(ok=False, error=f"HTTP {resp.status}")
            for raw_line in resp:
                if cancel is not None and cancel.is_set():
                    # Abandoning the response closes the connection, which
                    # is what actually stops the transfer.
                    return PullResult(ok=False, cancelled=True)
                line = raw_line.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue            # a malformed line is not fatal
                if not isinstance(obj, dict):
                    continue
                if obj.get("error"):
                    return PullResult(ok=False, error=str(obj["error"]))
                status = str(obj.get("status") or "")
                try:
                    completed = int(obj.get("completed") or 0)
                    total = int(obj.get("total") or 0)
                except (TypeError, ValueError):
                    completed, total = 0, 0
                if on_progress is not None:
                    on_progress(PullProgress(status, completed, total))
                if status == "success":
                    last_ok = True
    except urllib.error.HTTPError as e:
        return PullResult(ok=False, error=f"HTTP {e.code}")
    except Exception as e:
        return PullResult(ok=False, error=f"{e.__class__.__name__}: {e}")

    return PullResult(ok=last_ok,
                      error="" if last_ok else "the server ended the stream "
                                               "without reporting success")
