# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
run_estimate.py — what a run is about to cost, said before it starts.

F-151. ``_run_clicked`` began a long, and on OpenAI a billable, operation
with no record count, no request count, no time estimate and no
confirmation. The maintainer's run took hours. The ceremony for a model
download already existed and was written with this gap named in its own
docstring — ``provider_dialog.py::_offer_pull`` says that adding a
multi-gigabyte download with *less* ceremony than a billable run deserves
would repeat the mistake — so the pattern to follow was already in the
tree.

Two kinds of number, kept apart on purpose
------------------------------------------
**Counts are certain.** Records, enabled LLM criteria, the
record-criterion pairs they multiply out to, and the number of requests
those become at the configured batch size are all arithmetic over things
already loaded. They are stated flatly.

**Duration is not.** It depends on the model, the hardware, and whether
the server found a GPU. So this module refuses to invent one: it reports
a duration only from a rate it has *observed on this endpoint and this
model in this session*, and says nothing about time until it has one.
That is the honest form of "record count times an observed rate", and
the alternative — a plausible seconds-per-request constant — is how
``F-125`` came to describe a cost figure wrong by two to three orders of
magnitude.

The rate memory is per session and in memory only. Persisting it would
mean deciding when a remembered rate has gone stale, and a rate measured
against a since-restarted server that has now found its GPU is worse than
no rate at all.

No tkinter here: the wording is decided in this module and rendered by
the Views, the same division ``stage_state`` follows and the reason the
sentences below can be asserted without a display.
"""
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

#: (endpoint, model) -> (total_seconds, total_calls), this session only.
_OBSERVED: Dict[Tuple[str, str], Tuple[float, int]] = {}


def _key(endpoint: str, model: str) -> Tuple[str, str]:
    return ((endpoint or "").strip().rstrip("/").lower(),
            (model or "").strip())


def remember_call(endpoint: str, model: str, seconds: float) -> None:
    """Record one completed request. Never raises.

    Accumulated rather than replaced, so the rate is a mean over the
    session instead of whatever the last call happened to be. A single
    slow call — a cold model load, a retry after a rate limit — should
    move the estimate, not become it.

    Called from the engine's innermost call site, so it must be cheap and
    must not be able to fail a run over a reporting nicety.
    """
    try:
        seconds = float(seconds)
        # `not (seconds >= 0)` rather than `seconds < 0`, because NaN is
        # false for both comparisons and would otherwise be accumulated:
        # one NaN makes the mean NaN for the rest of the session, and the
        # confirmation would offer the user "nan seconds". Caught by the
        # test rather than reasoned about.
        if not (seconds >= 0) or seconds == float("inf"):
            return
        k = _key(endpoint, model)
        total, calls = _OBSERVED.get(k, (0.0, 0))
        _OBSERVED[k] = (total + seconds, calls + 1)
    except Exception:
        pass


def observed_rate(endpoint: str, model: str) -> Optional[float]:
    """Mean seconds per request, or ``None`` if nothing has been timed.

    ``None`` is a real answer and callers must render it as one: the
    first run against a server has no basis for a duration, and saying so
    is better than a number with nothing behind it.
    """
    total, calls = _OBSERVED.get(_key(endpoint, model), (0.0, 0))
    if calls <= 0 or total <= 0:
        return None
    return total / calls


def forget_rates() -> None:
    """Drop every observed rate. For tests, and for a provider change."""
    _OBSERVED.clear()


@dataclass(frozen=True)
class RunPlan:
    """The arithmetic of a run, all of it certain."""

    records: int
    criteria: int
    batch_size: int

    @property
    def pairs(self) -> int:
        """Record-criterion pairs — what the model is asked to judge."""
        return self.records * self.criteria

    @property
    def requests(self) -> int:
        """Requests at this batch size, one criterion at a time.

        The engine batches *records* within a criterion and never mixes
        criteria in one call, so this is per-criterion ceiling division
        summed, not a ceiling over the pairs.
        """
        if self.records <= 0 or self.criteria <= 0:
            return 0
        size = max(1, int(self.batch_size))
        per_criterion = -(-self.records // size)     # ceiling division
        return per_criterion * self.criteria


def human_duration(seconds: float) -> str:
    """A duration a person reads without converting anything."""
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return f"{int(round(seconds))} seconds"
    minutes = seconds / 60.0
    if minutes < 90:
        return f"about {int(round(minutes))} minutes"
    hours = minutes / 60.0
    if hours < 10:
        return f"about {hours:.1f} hours"
    return f"about {int(round(hours))} hours"


def confirm_text(plan: RunPlan, *, stage: str, model: str,
                 rate: Optional[float] = None,
                 compute_detail: str = "",
                 flag_only: bool = False) -> str:
    """What to show before starting. Pure; the View only renders it.

    Ordered by what the user needs in order to answer the question:
    what is about to happen, how long it may take, what the machine is
    doing, and — because it changes what the run *means* rather than what
    it costs — whether exclusions will be acted on.
    """
    lines = [
        f"{stage} is about to screen {plan.records:,} record(s) against "
        f"{plan.criteria} LLM criterion/criteria.",
        "",
        f"That is {plan.pairs:,} record-criterion judgement(s), sent as "
        f"{plan.requests:,} request(s) of up to {max(1, int(plan.batch_size))} "
        f"record(s) each, to {model or 'the configured model'}.",
    ]

    if rate:
        lines += [
            "",
            f"At the {rate:.1f}s per request measured on this server so far, "
            f"that is {human_duration(rate * plan.requests)}. Cached answers "
            f"are not re-requested, so a re-run is usually faster.",
        ]
    else:
        lines += [
            "",
            "No request against this server has been timed yet, so there is "
            "no basis for a time estimate here.",
        ]

    if compute_detail:
        lines += ["", compute_detail]

    if flag_only:
        lines += [
            "",
            "Flag-only is in force: the model may flag records for review "
            "but will not exclude any.",
        ]

    lines += ["", "Start the run?"]
    return "\n".join(lines)
