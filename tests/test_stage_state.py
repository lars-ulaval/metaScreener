
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_stage_state.py — the LLM stages' UI decisions, now that they are data.

**Movement one of wave 8 part 2 is a CHARACTERISATION suite.** Several
assertions below encode defects on purpose. They record what
``plugins/06_el/ui.py::ELView`` and ``plugins/07_il/ui.py::ILView`` do
*today*, so that when the fix commits change them the diff shows exactly
which user-visible behaviours moved and which did not. Every one of those
assertions carries a ``CHARACTERISATION`` marker in its message naming the
finding it is waiting for.

Why this file has to exist before any fix. ``tests/conftest.py`` replaces
``tkinter`` with a ``MagicMock``, so ``ttk.Frame`` is a mock, ``ELView`` is
not instantiable, and no test in the suite asserts on a status label or a
button state. The three findings in scope — F-93, F-111, F-118 — are all
defects *in those expressions*. Extracting them into
``plugins/_common/stage_state.py`` is what makes them assertable at all.
"""
import pytest

from plugins._common.bundle import NOT_SCREENED, _export_confirm_reason
from plugins._common.stage_state import (
    OUTCOME_CANCELLED,
    OUTCOME_NOT_SCREENED,
    OUTCOME_OK,
    control_states,
    run_button_enabled_after_load,
    run_outcome,
)


STAGES = ["EL", "IL"]

# The three corpora that matter, as the engine reports them. All three
# produce identical `counts`, identical survivor counts and identical
# manifest markers; only the run report tells them apart (wave 8 part 1).
WORKED = {"records": 85, "answered": 85, "no_answer": 0, "failed": 0,
          "decisions_rejected": 0, "fields_rejected": 0,
          "calls_made": 2, "calls_failed": 0, "batches_failed": 0}
ALL_UNCERTAIN = dict(WORKED)                    # the model answered, unsurely
WHOLLY_FAILED = {"records": 85, "answered": 0, "no_answer": 0, "failed": 85,
                 "decisions_rejected": 0, "fields_rejected": 0,
                 "calls_made": 2, "calls_failed": 2, "batches_failed": 2}

FLAGGED_ONLY = {"OUT": 0, "PASS_CLEAN": 0, "PASS_FLAGGED": 85}
NORMAL = {"OUT": 3, "PASS_CLEAN": 40, "PASS_FLAGGED": 42}


# ---------------------------------------------------------------------------
# run_outcome — the status line
# ---------------------------------------------------------------------------

class TestOutcomeAsItIsToday:

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_normal_run_says_done(self, stage):
        out = run_outcome(stage=stage, counts=NORMAL, cancelled=False,
                          not_screened=False, total_rows=85)
        assert out.code == OUTCOME_OK
        assert out.label == f"{stage} done."

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_cancelled_run_says_so(self, stage):
        out = run_outcome(stage=stage, counts={}, cancelled=True,
                          not_screened=False, total_rows=85)
        assert out.code == OUTCOME_CANCELLED
        assert out.label == "Cancelled — partial run, nothing exported."

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_no_criteria_run_says_so(self, stage):
        out = run_outcome(stage=stage, counts={NOT_SCREENED: 85},
                          cancelled=False, not_screened=True, total_rows=85)
        assert out.code == OUTCOME_NOT_SCREENED
        assert "no " in out.label and "criteri" in out.label
        assert out.label != f"{stage} done."

    @pytest.mark.parametrize("stage", STAGES)
    def test_cancellation_wins_over_everything_else(self, stage):
        """A run that stopped early tells you nothing about what it would
        have screened, so its own report must not be reported instead."""
        out = run_outcome(stage=stage, counts={NOT_SCREENED: 85},
                          cancelled=True, not_screened=True, total_rows=85)
        assert out.code == OUTCOME_CANCELLED

    @pytest.mark.parametrize("stage", STAGES)
    def test_CHARACTERISATION_a_wholly_failed_run_also_says_done(self, stage):
        """**This is the defect.** A run in which the server was unreachable
        and every record was written off produces a corpus of manufactured
        non-answers, and the interface reports it exactly as it reports a
        successful screening pass."""
        out = run_outcome(stage=stage, counts=FLAGGED_ONLY, cancelled=False,
                          not_screened=False, total_rows=85)
        assert out.label == f"{stage} done.", (
            "CHARACTERISATION (F-93/F-111): locking in today's behaviour. A "
            "wholly failed run is reported as a completed one. The fix "
            "commit changes this assertion."
        )

    @pytest.mark.parametrize("stage", STAGES)
    def test_CHARACTERISATION_failed_and_all_uncertain_are_indistinguishable(
            self, stage):
        """The distinction the wave exists for, stated as it stands today:
        the two are the *same object*."""
        broken = run_outcome(stage=stage, counts=FLAGGED_ONLY, cancelled=False,
                             not_screened=False, total_rows=85)
        unsure = run_outcome(stage=stage, counts=FLAGGED_ONLY, cancelled=False,
                             not_screened=False, total_rows=85)
        assert broken == unsure, (
            "CHARACTERISATION (F-111): run_outcome does not yet take the run "
            "report, so a dead server and an unsure model cannot differ."
        )


# ---------------------------------------------------------------------------
# _export_confirm_reason — the acknowledgement gate
# ---------------------------------------------------------------------------

class TestExportGateAsItIsToday:

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_no_criteria_run_still_needs_acknowledgement(self, stage):
        """F-34, unchanged. The regression net for anything done to this
        function."""
        reason = _export_confirm_reason(not_screened=True, stage=stage)
        assert reason is not None
        assert stage in reason
        assert "no" in reason.lower() and "criteri" in reason.lower()

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_normal_run_needs_no_acknowledgement(self, stage):
        assert _export_confirm_reason(not_screened=False, stage=stage) is None

    @pytest.mark.parametrize("stage", STAGES)
    def test_CHARACTERISATION_a_wholly_failed_run_exports_without_a_word(
            self, stage):
        """**This is the defect.** F-34 built the acknowledgement machinery
        for a stage that screened nothing; it keys solely on the
        NOT_SCREENED count, and a stage that screened everything and learned
        nothing produces zero of those."""
        assert _export_confirm_reason(not_screened=False, stage=stage) is None, (
            "CHARACTERISATION (F-93): a run that produced a full corpus of "
            "manufactured non-answers exports with no warning at all. The "
            "fix commit changes this assertion."
        )


# ---------------------------------------------------------------------------
# control_states — which buttons are live
# ---------------------------------------------------------------------------

class TestControlStatesAsTheyAreToday:

    def test_while_running_only_cancel_is_live(self):
        st = control_states(running=True, has_bundle=True, has_rows=True,
                            has_input_errors=True)
        assert st.cancel is True
        assert (st.run, st.export, st.export_errors, st.export_bundle) == \
            (False, False, False, False)

    def test_after_a_run_the_exports_follow_the_rows(self):
        st = control_states(running=False, has_bundle=True, has_rows=True,
                            has_input_errors=False)
        assert st.export is True and st.export_bundle is True
        assert st.export_errors is False
        assert st.cancel is False

    def test_with_no_rows_the_exports_are_dead(self):
        st = control_states(running=False, has_bundle=True, has_rows=False,
                            has_input_errors=True)
        assert st.export is False and st.export_bundle is False
        assert st.export_errors is True

    def test_CHARACTERISATION_run_is_live_with_no_key(self):
        """**This is the defect.** ``_set_controls_running`` consults the
        bundle path alone, and it runs in the ``finally`` of every run — so
        from the first run of a session onward it overwrites whatever gate
        the load path applied."""
        st = control_states(running=False, has_bundle=True, has_rows=False,
                            has_input_errors=False)
        assert st.run is True, (
            "CHARACTERISATION (F-118): the readiness gate is not consulted "
            "here at all. The fix commit changes this assertion."
        )

    def test_CHARACTERISATION_the_two_predicates_for_one_button_disagree(self):
        """**This is the defect, stated as a contradiction.** Two functions
        decide the same button's state from disjoint inputs, and the one
        that ignores readiness runs last."""
        from_controls = control_states(
            running=False, has_bundle=True, has_rows=False,
            has_input_errors=False).run
        from_load = run_button_enabled_after_load(has_key=False)
        assert from_controls is True and from_load is False, (
            "CHARACTERISATION (F-118): _set_controls_running says the Run "
            "button should be live and _load_bundle_inputs says it should "
            "not, for one and the same situation — a loaded bundle with no "
            "API key. The fix commit deletes one of them."
        )
