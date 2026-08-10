
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
    parse_numeric_settings,
    OUTCOME_CANCELLED,
    OUTCOME_NOTHING_SEPARATED,
    OUTCOME_NO_ANSWERS,
    OUTCOME_NOT_SCREENED,
    OUTCOME_OK,
    control_states,
    llm_readiness,
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
        out = run_outcome(stage=stage, counts=NORMAL, llm_report=WORKED,
                          cancelled=False, not_screened=False, total_rows=85)
        assert out.code == OUTCOME_OK
        assert out.label == f"{stage} done."

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_cancelled_run_says_so(self, stage):
        out = run_outcome(stage=stage, counts={}, llm_report={},
                          cancelled=True, not_screened=False, total_rows=85)
        assert out.code == OUTCOME_CANCELLED
        assert out.label == "Cancelled — partial run, nothing exported."

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_no_criteria_run_says_so(self, stage):
        out = run_outcome(stage=stage, counts={NOT_SCREENED: 85},
                          llm_report={}, cancelled=False, not_screened=True,
                          total_rows=85)
        assert out.code == OUTCOME_NOT_SCREENED
        assert "no " in out.label and "criteri" in out.label
        assert out.label != f"{stage} done."

    @pytest.mark.parametrize("stage", STAGES)
    def test_cancellation_wins_over_everything_else(self, stage):
        """A run that stopped early tells you nothing about what it would
        have screened, so its own report must not be reported instead."""
        out = run_outcome(stage=stage, counts={NOT_SCREENED: 85},
                          llm_report=WHOLLY_FAILED, cancelled=True,
                          not_screened=True, total_rows=85)
        assert out.code == OUTCOME_CANCELLED

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_wholly_failed_run_no_longer_says_done(self, stage):
        """F-93/F-111. Was a CHARACTERISATION assertion in `ed05fb3`, where
        it read ``== f"{stage} done."``. A run in which the server was
        unreachable and every record was written off produced a corpus of
        manufactured non-answers, and the interface reported it exactly as
        it reported a successful screening pass."""
        out = run_outcome(stage=stage, counts=FLAGGED_ONLY,
                          llm_report=WHOLLY_FAILED, cancelled=False,
                          not_screened=False, total_rows=85)
        assert out.code == OUTCOME_NO_ANSWERS
        assert out.label != f"{stage} done."
        assert "85" in out.label, "the count must be on the face of it"

    @pytest.mark.parametrize("stage", STAGES)
    def test_failed_and_all_uncertain_are_now_distinguishable(self, stage):
        """The distinction the wave exists for. Was a CHARACTERISATION
        assertion in `ed05fb3` reading ``broken == unsure``: the two used to
        be the same object, because run_outcome did not take the run report.

        Both corpora produce identical counts, identical survivors,
        identical manifest markers and every record flagged. Only the report
        separates them."""
        broken = run_outcome(stage=stage, counts=FLAGGED_ONLY,
                             llm_report=WHOLLY_FAILED, cancelled=False,
                             not_screened=False, total_rows=85)
        unsure = run_outcome(stage=stage, counts=FLAGGED_ONLY,
                             llm_report=ALL_UNCERTAIN, cancelled=False,
                             not_screened=False, total_rows=85)
        assert broken != unsure
        assert broken.code == OUTCOME_NO_ANSWERS, "never heard from"
        assert unsure.code == OUTCOME_NOTHING_SEPARATED, "heard, unconvinced"


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
    def test_a_wholly_failed_run_now_needs_acknowledgement(self, stage):
        """F-93. Was a CHARACTERISATION assertion in `ed05fb3` reading
        ``is None``: F-34 built this machinery for a stage that screened
        nothing, and it keyed solely on the NOT_SCREENED count — so a stage
        that screened everything and learned nothing produced zero of those
        and sailed through."""
        out = run_outcome(stage=stage, counts=FLAGGED_ONLY,
                          llm_report=WHOLLY_FAILED, cancelled=False,
                          not_screened=False, total_rows=85)
        reason = _export_confirm_reason(not_screened=False, stage=stage,
                                        outcome_reason=out.ack_reason)
        assert reason is not None
        assert "Export anyway?" in reason

    @pytest.mark.parametrize("stage", STAGES)
    def test_the_f34_question_still_wins_when_both_apply(self, stage):
        """A stage with no criteria never called anything, so its report is
        empty and would otherwise be read as "no answers". F-34's diagnosis
        is the correct one and is checked first."""
        reason = _export_confirm_reason(not_screened=True, stage=stage,
                                        outcome_reason="something else")
        assert "criteri" in reason.lower()
        assert reason != "something else"

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_good_run_still_needs_no_acknowledgement(self, stage):
        out = run_outcome(stage=stage, counts=NORMAL, llm_report=WORKED,
                          cancelled=False, not_screened=False, total_rows=85)
        assert _export_confirm_reason(not_screened=False, stage=stage,
                                      outcome_reason=out.ack_reason) is None

    @pytest.mark.parametrize("stage", STAGES)
    def test_the_eh_ih_two_argument_form_is_untouched(self, stage):
        """Twelve call sites across four stages, and EH/IH are not LLM
        stages and have no report to give. The new parameter defaults, so
        their behaviour is exactly what it was."""
        assert _export_confirm_reason(not_screened=False, stage=stage) is None
        assert _export_confirm_reason(not_screened=True, stage=stage) is not None


# ---------------------------------------------------------------------------
# control_states — which buttons are live
# ---------------------------------------------------------------------------

def _ready(**over):
    kw = {"stage": "EL", "has_bundle": True, "provider": "openai", "api_key": "sk-test", "model": "m"}
    kw.update(over)
    return llm_readiness(**kw)


class TestControlStates:

    def test_while_running_only_cancel_is_live(self):
        st = control_states(running=True, readiness=_ready(), has_rows=True,
                            has_input_errors=True)
        assert st.cancel is True
        assert (st.run, st.export, st.export_errors, st.export_bundle) == \
            (False, False, False, False)

    def test_after_a_run_the_exports_follow_the_rows(self):
        st = control_states(running=False, readiness=_ready(), has_rows=True,
                            has_input_errors=False)
        assert st.export is True and st.export_bundle is True
        assert st.export_errors is False
        assert st.cancel is False

    def test_with_no_rows_the_exports_are_dead(self):
        st = control_states(running=False, readiness=_ready(), has_rows=False,
                            has_input_errors=True)
        assert st.export is False and st.export_bundle is False
        assert st.export_errors is True

    def test_run_is_dead_with_no_key(self):
        """F-118. Was a CHARACTERISATION assertion in `ed05fb3` reading
        ``st.run is True``. ``_set_controls_running`` consulted the bundle
        path alone and runs in the ``finally`` of every run, so from the
        first run of a session onward it overwrote the gate the load path
        had applied."""
        st = control_states(running=False, readiness=_ready(provider="openai", api_key=""),
                            has_rows=False, has_input_errors=False)
        assert st.run is False

    def test_run_is_dead_with_no_model(self):
        st = control_states(running=False, readiness=_ready(model="   "),
                            has_rows=False, has_input_errors=False)
        assert st.run is False

    def test_run_is_dead_with_no_bundle(self):
        st = control_states(running=False, readiness=_ready(has_bundle=False),
                            has_rows=False, has_input_errors=False)
        assert st.run is False

    def test_run_is_live_when_everything_is_ready(self):
        st = control_states(running=False, readiness=_ready(), has_rows=False,
                            has_input_errors=False)
        assert st.run is True

    def test_there_is_now_only_one_predicate_for_the_button(self):
        """F-118, stated as the absence of the contradiction. `ed05fb3`
        carried ``run_button_enabled_after_load`` purely so the
        disagreement could be asserted before it was fixed; the fix is that
        the second predicate no longer exists."""
        import plugins._common.stage_state as ss
        assert not hasattr(ss, "run_button_enabled_after_load"), (
            "the load path and the running path must not decide this button "
            "from disjoint inputs again"
        )


# ---------------------------------------------------------------------------
# F-118 — the numeric settings
# ---------------------------------------------------------------------------

class TestNumericSettings:
    """`trunc_chars` is a free-text Entry over a StringVar, guarded only by
    `try: int(...) except: default` — which rescues `"abc"` and accepts
    `"-100"`.

    A negative value reaches the prompt builder's
    ``if trunc_chars and len(s) > trunc_chars`` guard, where it is truthy
    and the comparison is unconditionally true, so `s[:trunc_chars]` runs as
    a negative slice. **Measured on the real builder:** `-100` cuts the last
    100 characters off the abstract AND empties the title and keywords
    outright, because any field shorter than 100 characters slices to "".
    Nothing logs it, and the run report scores the resulting records as
    `answered`.
    """

    def test_a_sane_pair_passes_through(self):
        s = parse_numeric_settings(batch_raw="50", trunc_raw="1500",
                                   batch_default=50, trunc_default=1500)
        assert (s.batch_size, s.trunc_chars) == (50, 1500)
        assert s.problems == ()

    @pytest.mark.parametrize("raw", ["-1", "-100", "-100000"])
    def test_a_negative_truncation_is_refused_and_reported(self, raw):
        s = parse_numeric_settings(batch_raw="50", trunc_raw=raw,
                                   batch_default=50, trunc_default=1500)
        assert s.trunc_chars == 1500
        assert s.problems, "silently correcting it is what let it happen"
        assert any(raw in p for p in s.problems), "say what was rejected"

    def test_zero_truncation_is_legitimate_and_kept(self):
        """0 means 'do not truncate' — the builder's guard is
        ``if trunc_chars and ...``, so falsy is a documented value, not an
        error. Correcting it would be a different defect."""
        s = parse_numeric_settings(batch_raw="50", trunc_raw="0",
                                   batch_default=50, trunc_default=1500)
        assert s.trunc_chars == 0
        assert s.problems == ()

    @pytest.mark.parametrize("raw", ["abc", "", "   ", "1.5"])
    def test_a_non_integer_falls_back_and_now_says_so(self, raw):
        """The fallback already existed; the silence is what changes."""
        s = parse_numeric_settings(batch_raw="50", trunc_raw=raw,
                                   batch_default=50, trunc_default=1500)
        assert s.trunc_chars == 1500
        assert s.problems

    @pytest.mark.parametrize("raw", ["0", "-5"])
    def test_a_batch_size_below_one_is_clamped_and_reported(self, raw):
        """The engine already clamps this twice — ``max(1, int(n))`` in
        ``chunked`` and again at its call site — so it was never silently
        WRONG, only silently different from what was typed. Reported for
        that reason and not corrected anywhere else."""
        s = parse_numeric_settings(batch_raw=raw, trunc_raw="1500",
                                   batch_default=50, trunc_default=1500)
        assert s.batch_size == 1
        assert s.problems

    def test_both_can_be_wrong_at_once(self):
        s = parse_numeric_settings(batch_raw="0", trunc_raw="-100",
                                   batch_default=50, trunc_default=1500)
        assert (s.batch_size, s.trunc_chars) == (1, 1500)
        assert len(s.problems) == 2

    def test_the_problems_are_sentences_a_user_can_act_on(self):
        s = parse_numeric_settings(batch_raw="50", trunc_raw="-100",
                                   batch_default=50, trunc_default=1500)
        text = " ".join(s.problems)
        assert "1500" in text, "say what was used instead"
        assert text.rstrip()[-1] in ".!"
