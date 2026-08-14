
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
import types

import pytest

from plugins._common.bundle import NOT_SCREENED, _export_confirm_reason
from plugins._common.stage_state import (
    parse_numeric_settings,
    LOW_ANSWER_RATE,
    OUTCOME_CANCELLED,
    OUTCOME_CODES,
    OUTCOME_EXCLUSIONS_SUPPRESSED,
    OUTCOME_LOW_ANSWER_RATE,
    OUTCOME_NOTHING_SEPARATED,
    OUTCOME_NO_ANSWERS,
    OUTCOME_NOT_SCREENED,
    OUTCOME_OK,
    OUTCOME_PARTIAL_FAILURE,
    control_states,
    llm_readiness,
    run_outcome,
)
from plugins._common.bundle import EXCLUSION_SUPPRESSED


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
    kw = {"stage": "EL", "has_bundle": True, "provider": "openai",
          "api_key": "sk-test", "model": "m",
          "probe": types.SimpleNamespace(state="ready", detail="")}
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


# ---------------------------------------------------------------------------
# F-193 — the answer rate is a fact about the run, and nothing read it
# ---------------------------------------------------------------------------

def _rep(records=170, answered=137, no_answer=33, **kw):
    """A run report with a real answer rate. Every pre-existing fixture in this
    suite carries ``no_answer: 0`` — all 29 ``run_outcome`` call sites — which
    is why no test classified a partially-answered run before this wave."""
    base = {"records": records, "answered": answered, "no_answer": no_answer,
            "failed": 0, "decisions_rejected": 0, "fields_rejected": 0,
            "calls_made": 34, "calls_failed": 0, "batches_failed": 0}
    base.update(kw)
    return base


#: wave 12's committed run C — qwen2.5:7b, batch 5, EL — as its manifest
#: records it. 33 of 170 record-criterion pairs unanswered, and 42 records
#: separated, so it reaches `ok` today and exports with no acknowledgement.
RUN_C_REPORT = _rep()
RUN_C_COUNTS = {"OUT": 4, "PASS_CLEAN": 38, "PASS_FLAGGED": 43}


class TestTheAnswerRateIsRead:
    """F-193. ``no_answer`` was derived by ``summarize_llm_evidence``, written
    into the manifest, and read by nothing: ``run_outcome`` consulted
    ``records``, ``answered``, ``failed``, ``decisions_rejected``,
    ``calls_failed`` and the outcome histogram, and never the one number that
    says how much of the run the model declined to address.
    """

    @pytest.mark.parametrize("stage", STAGES)
    def test_wave_12s_own_run_c_no_longer_reports_as_a_clean_success(self, stage):
        """The measured case, from a committed artefact rather than a
        hypothetical: 19.4% of pairs unanswered, reported as "EL done." with
        no acknowledgement and both exports live."""
        out = run_outcome(stage=stage, counts=RUN_C_COUNTS,
                          llm_report=RUN_C_REPORT, cancelled=False,
                          not_screened=False, total_rows=85)
        assert out.code == OUTCOME_LOW_ANSWER_RATE
        assert out.label != f"{stage} done."
        assert out.ack_reason, "an unacknowledged warning is what this row is about"

    @pytest.mark.parametrize("stage", STAGES)
    def test_it_beats_nothing_separated(self, stage):
        """Ordering, and the same argument branch 3 already makes against
        branch 4: a near-silent model also separates nothing, and the two call
        for opposite responses from the user."""
        out = run_outcome(stage=stage, counts=FLAGGED_ONLY,
                          llm_report=_rep(records=85, answered=40, no_answer=45),
                          cancelled=False, not_screened=False, total_rows=85)
        assert out.code == OUTCOME_LOW_ANSWER_RATE

    @pytest.mark.parametrize("stage", STAGES)
    def test_it_beats_exclusions_suppressed(self, stage):
        """The branch that swallows run C's flag-only counterfactual. Placed
        below it, this guard would not fire in the configuration flag-only
        exists for — which is the configuration a weak local model runs in."""
        counts = {"OUT": 0, "PASS_CLEAN": 0, "PASS_FLAGGED": 45,
                  EXCLUSION_SUPPRESSED: 40}
        out = run_outcome(stage=stage, counts=counts, llm_report=RUN_C_REPORT,
                          cancelled=False, not_screened=False, total_rows=85)
        assert out.code == OUTCOME_LOW_ANSWER_RATE

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_wholly_unheard_run_is_still_no_answers(self, stage):
        """``answered == 0`` keeps its own diagnosis. A dead server, a typo'd
        model, an unpulled model and a rejected key are all false at a 5%
        answer rate — the server is up and the model is replying — so the two
        states name different remedies and must not merge."""
        out = run_outcome(stage=stage, counts=FLAGGED_ONLY,
                          llm_report=WHOLLY_FAILED, cancelled=False,
                          not_screened=False, total_rows=85)
        assert out.code == OUTCOME_NO_ANSWERS

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_fully_answered_run_is_untouched(self, stage):
        """The property that keeps all 29 existing call sites green."""
        out = run_outcome(stage=stage, counts=FLAGGED_ONLY, llm_report=WORKED,
                          cancelled=False, not_screened=False, total_rows=85)
        assert out.code == OUTCOME_NOTHING_SEPARATED

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_partially_failed_run_is_not_this(self, stage):
        """The predicate is on ``no_answer``, not on ``answered``. Keyed on
        ``answered`` this branch would steal a partially-*failed* run from
        ``partial_failure``, which already owns it."""
        out = run_outcome(stage=stage, counts=NORMAL,
                          llm_report=_rep(records=85, answered=60, no_answer=0,
                                          failed=25),
                          cancelled=False, not_screened=False, total_rows=85)
        assert out.code == OUTCOME_PARTIAL_FAILURE

    @pytest.mark.parametrize("stage", STAGES)
    def test_the_threshold_is_inclusive(self, stage):
        """Exactly at the threshold fires. A run sitting on the boundary is not
        a run to stay quiet about."""
        n = int(100 * LOW_ANSWER_RATE)
        out = run_outcome(stage=stage, counts=NORMAL,
                          llm_report=_rep(records=100, answered=100 - n,
                                          no_answer=n),
                          cancelled=False, not_screened=False, total_rows=85)
        assert out.code == OUTCOME_LOW_ANSWER_RATE

    @pytest.mark.parametrize("stage", STAGES)
    def test_below_the_threshold_falls_through(self, stage):
        out = run_outcome(stage=stage, counts=NORMAL,
                          llm_report=_rep(records=1000, answered=999,
                                          no_answer=1),
                          cancelled=False, not_screened=False, total_rows=85)
        assert out.code == OUTCOME_OK

    @pytest.mark.parametrize("stage", STAGES)
    def test_an_empty_report_does_not_divide_by_zero(self, stage):
        out = run_outcome(stage=stage, counts=NORMAL, llm_report={},
                          cancelled=False, not_screened=False, total_rows=85)
        assert out.code in OUTCOME_CODES

    @pytest.mark.parametrize("stage", STAGES)
    def test_cancellation_still_wins(self, stage):
        """A run that stopped early tells you nothing about what it would have
        screened, including about its answer rate."""
        out = run_outcome(stage=stage, counts=RUN_C_COUNTS,
                          llm_report=RUN_C_REPORT, cancelled=True,
                          not_screened=False, total_rows=85)
        assert out.code == OUTCOME_CANCELLED

    @pytest.mark.parametrize("stage", STAGES)
    def test_no_criteria_still_wins(self, stage):
        """A stage that evaluated nothing cannot have failed to get an answer."""
        out = run_outcome(stage=stage, counts={NOT_SCREENED: 85},
                          llm_report=RUN_C_REPORT, cancelled=False,
                          not_screened=True, total_rows=85)
        assert out.code == OUTCOME_NOT_SCREENED

    def test_the_new_code_is_in_the_published_vocabulary(self):
        """``OUTCOME_CODES`` is the closed set this module publishes; a member
        that is not in it is a state no caller can name."""
        assert OUTCOME_LOW_ANSWER_RATE in OUTCOME_CODES

    def test_the_threshold_is_a_named_constant(self):
        """It is a choice between two measured populations — 0/170 twice and
        33/170 once — not a measurement. Named so a later wave can move it on
        evidence rather than by grep."""
        assert 0.0 < LOW_ANSWER_RATE < 1.0

    @pytest.mark.parametrize("stage", STAGES)
    def test_the_export_gate_asks(self, stage):
        """The user-visible half: this is the run that used to export in
        silence. ``_export_confirm_reason`` returns the outcome's reason, and
        both export paths put it up as a yes/no."""
        out = run_outcome(stage=stage, counts=RUN_C_COUNTS,
                          llm_report=RUN_C_REPORT, cancelled=False,
                          not_screened=False, total_rows=85)
        assert _export_confirm_reason(not_screened=False, stage=stage,
                                      outcome_reason=out.ack_reason)

    @pytest.mark.parametrize("stage", STAGES)
    def test_no_criteria_still_wins_the_export_question(self, stage):
        """F-34 first: a stage with no criteria never called anything, so its
        report would otherwise read as an answer-rate problem."""
        body = _export_confirm_reason(not_screened=True, stage=stage,
                                      outcome_reason="whatever")
        assert "no enabled criteria" in body


# ---------------------------------------------------------------------------
# F-192 — what the acknowledgement says
# ---------------------------------------------------------------------------

#: nothing_separated, with a real but sub-threshold answer rate. 7 of 100
#: unanswered is 7%, under LOW_ANSWER_RATE, so F-193's branch does not take
#: this run and `nothing_separated` is what the user meets.
SUB_THRESHOLD = _rep(records=100, answered=93, no_answer=7)


def _nothing_separated(stage="EL"):
    return run_outcome(stage=stage, counts=FLAGGED_ONLY,
                       llm_report=SUB_THRESHOLD, cancelled=False,
                       not_screened=False, total_rows=85)


def _low_rate(stage="EL"):
    return run_outcome(stage=stage, counts=RUN_C_COUNTS,
                       llm_report=RUN_C_REPORT, cancelled=False,
                       not_screened=False, total_rows=85)


class TestTheAcknowledgementProse:
    """**CHARACTERISATION at this commit.** Every assertion in this class
    records what the acknowledgements say *today*, so the commit that changes
    them shows exactly which user-visible sentences moved. Four of them encode
    F-192's defect on purpose and are marked.

    The register these are measured against is F-173's, the wave-13c dialog:
    name the thing, say plainly what it does, and do not tell the user what to
    conclude — ending, in that dialog, *"Nothing here stops you … these are
    notes, not a gate."*
    """

    def test_nothing_separated_tells_the_user_the_result_may_be_genuine(self):
        """CHARACTERISATION, F-192. The sentence is now *true* — F-193's branch
        takes every run whose answer rate is bad — but it is asserted rather
        than shown, because the number it rests on is not in the text."""
        assert "may well be genuine" in _nothing_separated().ack_reason

    def test_nothing_separated_does_not_name_the_unanswered_count(self):
        """CHARACTERISATION, F-192. 7 of 100 pairs came back unreadable and the
        acknowledgement says only that 93 carry a decision. The reader is given
        the reassuring half of the arithmetic and asked to take the rest."""
        out = _nothing_separated()
        assert "7" not in out.ack_reason.replace("record-criterion", "")

    def test_the_low_rate_acknowledgement_names_no_cause(self):
        """CHARACTERISATION, F-192. F-193 landed the branch with a factual
        minimum. The `no_answers` acknowledgement one branch above lists what
        the condition looks like — an unreachable server, a misspelled model, a
        model never pulled, a rejected key — and this one lists nothing."""
        body = _low_rate().ack_reason
        assert not any(w in body for w in ("shape", "batch size", "engage"))

    def test_the_low_rate_acknowledgement_points_nowhere(self):
        """CHARACTERISATION, F-192. F-194 now retains a sample of what came
        back, and nothing in the text sends the reader to it."""
        assert "Log tab" not in _low_rate().ack_reason

    def test_the_low_rate_acknowledgement_already_names_its_numbers(self):
        """NOT a characterisation of a defect: this half is already right and
        must survive the fix. The count and the percentage are on the face of
        it."""
        body = _low_rate().ack_reason
        assert "137" in body and "170" in body and "33" in body and "19%" in body

    def test_the_no_answers_acknowledgement_is_the_register_to_follow(self):
        """The text F-192's replacement is measured against. It names the
        number, states the consequence for the artefact, lists the conditions
        that produce it, points at where to look, and asks — without telling
        the reader what to conclude."""
        out = run_outcome(stage="EL", counts=FLAGGED_ONLY,
                          llm_report=WHOLLY_FAILED, cancelled=False,
                          not_screened=False, total_rows=85)
        body = out.ack_reason
        assert "unreachable server" in body and "Log tab" in body
        assert "Export anyway?" in body
        assert "genuine" not in body
