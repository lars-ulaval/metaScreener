# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
plugins/_common/stage_state.py — what state an LLM stage is in, as plain data.

Every decision in here used to be an expression inside a Tk callback, which
made it untestable: ``tests/conftest.py`` replaces ``tkinter`` with a
``MagicMock``, so ``ttk.Frame`` is a mock and ``ELView`` cannot be
instantiated at all. Nothing in the suite asserted on a status label or a
button state, and the defects this module exists to fix — F-93, F-111,
F-118 — all live in exactly those expressions.

So the rule here is: **inputs are plain data, outputs are plain data, and
nothing imports Tk.** The View's job becomes reading widgets, calling one
of these, and writing widgets.

**Two arms, because the inputs arrive at two different times and answer two
different questions.** Before a run, the only facts available are
configuration — is a bundle loaded, is a key visible, is the model field
non-empty — and the question is *may I start, and if not, why not*. After a
run, the facts are the outcome counts and the run report the engine now
returns, and the question is *did that work, and may I export it*. A single
flat enumeration would have to mix the two, and §B1.4's own eleven-state
table does mix them: state 10 ("model blank") is a pre-run check, states
2–7 are probe results, and the post-run states are absent from it entirely
because that section was written about model discovery. Keeping the arms
separate is what lets wave 10 add its three endpoint states to the first
arm without touching the second.

*(Wave 8 part 2. Movement one of this file is a behaviour-preserving
extraction: ``control_states`` and ``run_outcome`` reproduce what the two
Views already did, expression for expression, so the characterisation tests
in ``tests/test_stage_state.py`` lock in today's behaviour — defects
included — before any of it is changed.)*
"""
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Tuple

from plugins._common.bundle import (
    CANCELLED_EXPORT_REASON,
    NOT_SCREENED,
    _run_summary_counts_text,
)


# ----------------------------
# Outcome — what the last run amounted to
# ----------------------------

OUTCOME_CANCELLED = "cancelled"
OUTCOME_NOT_SCREENED = "not_screened"
OUTCOME_NO_ANSWERS = "no_answers"
OUTCOME_NOTHING_SEPARATED = "nothing_separated"
OUTCOME_PARTIAL_FAILURE = "partial_failure"
OUTCOME_OK = "ok"

OUTCOME_CODES = (
    OUTCOME_CANCELLED, OUTCOME_NOT_SCREENED, OUTCOME_NO_ANSWERS,
    OUTCOME_NOTHING_SEPARATED, OUTCOME_PARTIAL_FAILURE, OUTCOME_OK,
)
"""The closed set of states a finished run can be in.

The first two and the last are what the code distinguished before wave 8;
the middle three are the ones it could not, and they are the reason a
server that was down, a model name with a typo, a model that was never
pulled, an empty model field and a genuinely all-uncertain corpus all
reported ``"EL done."``.
"""


@dataclass(frozen=True)
class Outcome:
    """What the interface should say about the run that just finished.

    ``code``
        one of :data:`OUTCOME_CODES`. The thing to branch on.
    ``label``
        the status line, verbatim.
    ``ack_reason``
        the question the user must answer yes to before exporting, or
        ``None`` when export needs no acknowledgement. Rendered here rather
        than in ``plugins/_common/bundle.py`` only to keep the import
        one-way — ``bundle`` must not import this module, because this
        module imports ``bundle``.
    """

    code: str
    label: str
    ack_reason: Optional[str] = None


def run_outcome(*, stage: str, counts: Mapping[str, int],
                llm_report: Mapping[str, Any], cancelled: bool,
                not_screened: bool, total_rows: int) -> Outcome:
    """Classify a finished run.

    The first two branches and the last are the Views' own, transcribed in
    movement one; the middle two are F-111. The ordering is load-bearing
    throughout, and each step is the more specific cause winning over the
    more general one:

    1. **cancelled** beats everything. A run that stopped early tells you
       nothing about what it would have screened.
    2. **no criteria** (F-34) beats everything below it, because a stage
       that evaluated nothing cannot have failed to get an answer.
    3. **no answers** beats *nothing separated*, because a dead server also
       separates nothing — and the two call for opposite responses from the
       user, so reporting the general case would send them looking in the
       wrong place.
    4. **nothing separated** is the honest name for the case where the
       model *was* heard from and no record cleared the evidence gate. It
       is a screening result, not a misconfiguration, and it may well be
       genuine.
    5. **partial failure** is a real result with a documented hole.

    ``llm_report`` is the engine's, not re-derived here. The counting
    substrate exists (wave 8 part 1) and a second derivation would be two
    representations of one fact — F-69's shape, which this project has
    shipped four times. Unknown keys are ignored and missing keys default,
    so wave 9's provenance fields and an older build's absent report are
    both non-events.
    """
    if cancelled:
        return Outcome(
            code=OUTCOME_CANCELLED,
            label="Cancelled — partial run, nothing exported.",
            ack_reason=None,
        )
    if not_screened:
        return Outcome(
            code=OUTCOME_NOT_SCREENED,
            label=_run_summary_counts_text(
                counts, stage=stage, total_rows=total_rows),
            ack_reason=None,
        )

    records = int(llm_report.get("records", 0) or 0)
    answered = int(llm_report.get("answered", 0) or 0)
    failed = int(llm_report.get("failed", 0) or 0)
    rejected = int(llm_report.get("decisions_rejected", 0) or 0)
    calls_failed = int(llm_report.get("calls_failed", 0) or 0)
    separated = int(counts.get("OUT", 0) or 0) + int(counts.get("PASS_CLEAN", 0) or 0)

    if records and answered == 0:
        return Outcome(
            code=OUTCOME_NO_ANSWERS,
            label=(f"{stage}: NO ANSWERS — 0 of {records} record-criterion "
                   f"pairs carry a decision ({failed} failed)."),
            ack_reason=(
                f"{stage} did not obtain a usable answer for a single "
                f"record.\n\n"
                f"{failed} of {records} record-criterion pairs ended in a "
                f"failed call, and {calls_failed} call(s) raised. Every "
                f"record is therefore flagged rather than screened, and an "
                f"exported bundle will record that outcome as though the "
                f"stage had run normally.\n\n"
                f"This is what an unreachable server, a misspelled model "
                f"name, a model that was never pulled and a rejected key all "
                f"look like. The Log tab names the cause of each failed "
                f"call.\n\n"
                f"Export anyway?"
            ),
        )

    if total_rows and separated == 0:
        return Outcome(
            code=OUTCOME_NOTHING_SEPARATED,
            label=(f"{stage}: nothing separated — every record flagged "
                   f"(model answered {answered} of {records})."),
            ack_reason=(
                f"{stage} separated none of the {total_rows} records: none "
                f"was excluded and none passed cleanly.\n\n"
                f"The model was heard from — {answered} of {records} "
                f"record-criterion pairs carry a decision — so this is a "
                f"screening result rather than a misconfiguration, and it "
                f"may well be genuine: a corpus the model is unsure about "
                f"produces exactly this. Every record is recorded as "
                f"flagged for human review.\n\n"
                f"Export anyway?"
            ),
        )

    if failed or rejected:
        return Outcome(
            code=OUTCOME_PARTIAL_FAILURE,
            label=(f"{stage} done, with gaps — {failed} failed and "
                   f"{rejected} unreadable of {records}."),
            ack_reason=None,
        )

    return Outcome(code=OUTCOME_OK, label=f"{stage} done.", ack_reason=None)


# ----------------------------
# Readiness — whether a run may start at all
# ----------------------------

READY = "ready"
NO_BUNDLE = "no_bundle"
NO_KEY = "no_key"
NO_MODEL = "no_model"

READINESS_CODES = (READY, NO_BUNDLE, NO_KEY, NO_MODEL)
"""The closed set of pre-run states, over the inputs available today.

**Wave 10 extends this set, and the extension is the point of the split.**
Once an endpoint is a first-class GUI value, three more states become
decidable — endpoint unreachable, endpoint reachable but the model was
never pulled, and a keyless server that must not be blocked for want of a
key. Each is a new member here and a new branch in ``llm_readiness``,
reached by new keyword arguments; none of them changes a state that already
exists. §B1.4's six *discovery* states (0, 4, 5, 6, 7, 9) arrive the same
way and for the same reason.
"""


@dataclass(frozen=True)
class Readiness:
    """Whether the stage may start, and what to say if not.

    ``model`` is the *normalised* model — stripped — so the caller uses this
    rather than re-deriving it. Two places deciding what the model is was
    how F-93 happened.
    """

    code: str
    can_run: bool
    label: str
    detail: str
    model: str = ""


def llm_readiness(*, stage: str, has_bundle: bool, has_key: bool,
                  model: Optional[str]) -> Readiness:
    """Decide whether an LLM stage may start.

    The order is the order the user encounters the steps in, so a user with
    nothing set up is told to load a bundle rather than sent to find an API
    key. Each check names the single next thing to fix.

    F-93 lives in the last one. ``(self.var_model.get() or
    DEFAULT_MODEL).strip()`` put the strip *outside* the ``or``, so a
    whitespace-only field is truthy, survives the fallback and reaches the
    engine as ``""`` — which the engine takes as "no model" and skips
    silently, producing a full corpus of unscreened records and a status
    line reading "done".
    """
    if not has_bundle:
        return Readiness(
            code=NO_BUNDLE, can_run=False, label="No bundle loaded",
            detail=f"Load a ScreenA bundle ZIP before running {stage}.",
        )
    if not has_key:
        return Readiness(
            code=NO_KEY, can_run=False, label="OPENAI_API_KEY ✗",
            detail=(
                f"No API key is visible in the environment.\n\n"
                f"{stage} sends each record to an OpenAI-compatible "
                f"endpoint, and the client requires OPENAI_API_KEY to be "
                f"set even when the endpoint ignores its value — a "
                f"placeholder such as \"local\" is enough for a server that "
                f"does not check it."
            ),
        )
    normalised = (model or "").strip()
    if not normalised:
        return Readiness(
            code=NO_MODEL, can_run=False, label="No model set",
            detail=(
                f"The {stage} model field is empty or contains only "
                f"whitespace.\n\n"
                f"Type the name of the model to screen with. A run started "
                f"without one would call nothing, return no answers, and "
                f"still report every record as processed."
            ),
        )
    return Readiness(code=READY, can_run=True, label="Ready to run",
                     detail="", model=normalised)


# ----------------------------
# Controls — which buttons are live
# ----------------------------

@dataclass(frozen=True)
class ControlStates:
    """Enabled/disabled for the five buttons every LLM stage carries.

    IL's sixth button, "Export ScreenA_Report.xlsx…", follows the same rule
    as ``export`` and reads it rather than getting a field of its own: a
    field that is always equal to another field is the two-representations
    -of-one-fact shape this project keeps being bitten by (F-69, F-131).
    """

    run: bool
    cancel: bool
    export: bool
    export_errors: bool
    export_bundle: bool


def control_states(*, running: bool, readiness: "Readiness", has_rows: bool,
                   has_input_errors: bool) -> ControlStates:
    """Decide every button's state, in one place, from the readiness the
    rest of the stage already agrees on.

    F-118. ``_set_controls_running`` used to re-enable the Run button on
    ``self.bundle_zip_path`` **alone**, while ``_load_bundle_inputs`` set it
    from ``_has_openai_key()`` alone. Two functions, two disjoint inputs,
    one button — and because ``_set_controls_running(False)`` runs in the
    ``finally`` of every run, the one that ignores readiness ran *last*. So
    the gate the load path applied survived exactly until the first run of a
    session finished, after which the Run button was live regardless.

    Taking a ``Readiness`` rather than a bundle flag is what makes the
    second predicate impossible to reintroduce: there is nowhere left to put
    a different one.
    """
    return ControlStates(
        run=(not running) and readiness.can_run,
        cancel=running,
        export=(not running) and has_rows,
        export_errors=(not running) and has_input_errors,
        export_bundle=(not running) and has_rows,
    )


# ----------------------------
# Numeric settings
# ----------------------------

@dataclass(frozen=True)
class NumericSettings:
    """The two numeric knobs, corrected, with what was wrong about them."""

    batch_size: int
    trunc_chars: int
    problems: Tuple[str, ...] = ()


def parse_numeric_settings(*, batch_raw: Any, trunc_raw: Any,
                           batch_default: int,
                           trunc_default: int) -> NumericSettings:
    """Read the two numeric settings, correct what cannot be used, and say
    what was corrected.

    F-118. Both are free-text entries guarded only by
    ``try: int(...) except: <default>``, which rescues ``"abc"`` and
    cheerfully accepts ``"-100"``.

    **A negative ``trunc_chars`` is the live defect, and it is worse than
    the row states.** It reaches the prompt builder's
    ``if trunc_chars and len(s) > trunc_chars`` guard, where it is truthy
    and the comparison is unconditionally true, so ``s[:trunc_chars]`` runs
    as a *negative slice*. Measured on the real builder with ``-100``: the
    last 100 characters are cut from the abstract, **and the title and
    keywords are emptied outright**, because any field shorter than 100
    characters slices to ``""``. Titles and keywords are routinely under
    100 characters, so a modest negative value blanks two of the three
    fields for essentially every record. Nothing logs it; ``valid_quote``
    collapses because there is no text left to validate a quote against;
    and the wave-8 run report scores the records as ``answered``, because
    the model did answer — about nothing.

    ``0`` is left alone. The builder's guard is ``if trunc_chars and …``,
    so falsy means "do not truncate" — a documented value, not an error.

    ``batch_size`` below 1 is clamped and reported but was never silently
    *wrong*: ``plugins/_common/llm_client.py::chunked`` does
    ``max(1, int(n))`` and its caller does it again, so 0 degrades to
    one-item batches. It is reported because what the user typed and what
    ran differed, which is the same complaint one level down.

    Correcting-and-reporting rather than refusing: a typo in a numeric box
    should not throw away a configured run, and the existing behaviour
    already substitutes a default for non-numeric input. What changes is
    that the substitution stops being silent.
    """
    problems: List[str] = []

    def _as_int(raw: Any) -> Optional[int]:
        try:
            return int(str(raw).strip())
        except Exception:
            return None

    batch = _as_int(batch_raw)
    if batch is None:
        problems.append(
            f"Batch size {str(batch_raw)!r} is not a whole number; "
            f"using {batch_default}.")
        batch = batch_default
    elif batch < 1:
        problems.append(
            f"Batch size {batch} is below 1; using 1. The engine clamps this "
            f"anyway, so the run would have used one-item batches whatever "
            f"the box said.")
        batch = 1

    trunc = _as_int(trunc_raw)
    if trunc is None:
        problems.append(
            f"Truncation {str(trunc_raw)!r} is not a whole number; "
            f"using {trunc_default}.")
        trunc = trunc_default
    elif trunc < 0:
        problems.append(
            f"Truncation {trunc} is negative; using {trunc_default}. A "
            f"negative value does not shorten a field, it removes the last "
            f"{abs(trunc)} characters of it — and empties any field shorter "
            f"than that, which for most records is the title and the "
            f"keywords.")
        trunc = trunc_default

    return NumericSettings(batch_size=batch, trunc_chars=trunc,
                           problems=tuple(problems))


def tk_state(enabled: bool) -> str:
    """``True``/``False`` to the two strings ``configure(state=…)`` wants.

    This is Tk *vocabulary*, not Tk: it imports nothing and takes no widget.
    It lives here so the Views' only remaining job is to read widgets, call
    one of these functions, and write widgets — which is the property that
    makes the decisions testable.
    """
    return "normal" if enabled else "disabled"
