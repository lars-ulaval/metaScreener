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
from typing import Mapping, Optional

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
OUTCOME_OK = "ok"

OUTCOME_CODES = (OUTCOME_CANCELLED, OUTCOME_NOT_SCREENED, OUTCOME_OK)
"""The closed set of states a finished run can be in.

Wave 8 part 2, movement one: these three are exactly what the code
distinguishes today. Movement two adds the ones it cannot.
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
                cancelled: bool, not_screened: bool,
                total_rows: int) -> Outcome:
    """Classify a finished run.

    Extracted verbatim from the two Views' ``_run_clicked::work``. The
    ordering is theirs and is load-bearing: a cancelled run is reported as
    cancelled whatever else is true of it, because a run that stopped early
    tells you nothing about what it would have screened.

    ``counts`` and ``total_rows`` are only consulted for the no-criteria
    line, which delegates to ``bundle._run_summary_counts_text`` so that
    F-34's wording has one home.
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
    return Outcome(code=OUTCOME_OK, label=f"{stage} done.", ack_reason=None)


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


def control_states(*, running: bool, has_bundle: bool, has_rows: bool,
                   has_input_errors: bool) -> ControlStates:
    """Reproduce ``_set_controls_running`` exactly.

    The five expressions below are the two Views' own, transcribed. Note
    what ``run`` does *not* consult — that omission is F-118 and is fixed in
    movement two, not here.
    """
    return ControlStates(
        run=(not running) and has_bundle,
        cancel=running,
        export=(not running) and has_rows,
        export_errors=(not running) and has_input_errors,
        export_bundle=(not running) and has_rows,
    )


def tk_state(enabled: bool) -> str:
    """``True``/``False`` to the two strings ``configure(state=…)`` wants.

    This is Tk *vocabulary*, not Tk: it imports nothing and takes no widget.
    It lives here so the Views' only remaining job is to read widgets, call
    one of these functions, and write widgets — which is the property that
    makes the decisions testable.
    """
    return "normal" if enabled else "disabled"


def run_button_enabled_after_load(*, has_key: bool) -> bool:
    """The *other* predicate for the same button.

    ``_load_bundle_inputs`` sets ``btn_run`` from ``_has_openai_key()``
    alone, while ``_set_controls_running`` sets it from the bundle path
    alone. **They disagree**, and because ``_set_controls_running(False)``
    runs in the ``finally`` of every run, the second one wins from the first
    run of a session onward — so the readiness gate the load path applied is
    silently dropped. That is F-118.

    This function exists only so the disagreement can be *stated* in a test
    before it is fixed. Movement two deletes it.
    """
    return has_key
