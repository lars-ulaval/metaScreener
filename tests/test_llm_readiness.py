
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_llm_readiness.py — F-111: the interface must be able to tell the user
which situation they are in.

The GUI could not distinguish eleven endpoint/model states and reported the
same thing for all of them: ``"EL done."``, both export buttons live,
``cancelled: False``, and one log line in a sub-tab that is not the focused
one. The one provider-adjacent widget in the application,
``ELView._refresh_key_label``, can only ever render a tick in the shipped
hub, because the startup modal cannot be passed without a non-empty key and
nothing ever clears it — so it carries zero bits.

The model has two arms, and the split is the design:

  **before a run** — configuration only, and the question is *may I start,
  and if not, what do I fix first*;
  **after a run** — the outcome counts and the run report wave 8 part 1
  added, and the question is *did that work, and may I export it*.

§B1.4's eleven states are numbered 0–10 and **six of them are discovery
states** (0, 4, 5, 6, 7, 9) that need an endpoint and a ``/v1/models`` call.
Those are wave 10's. What is buildable today is the pre-run arm over
(bundle, key, model) and the post-run arm over (counts, report), and the
test at the bottom of this file pins the property wave 10 needs: adding a
state must not change any state that already exists.
"""
import types

import pytest

from plugins._common.stage_state import (
    NO_BUNDLE,
    NO_KEY,
    NO_MODEL,
    NOT_CONFIGURED,
    NOT_CHECKED,
    ENDPOINT_UNREACHABLE,
    NO_MODELS_PULLED,
    OUTCOME_CANCELLED,
    OUTCOME_NOTHING_SEPARATED,
    OUTCOME_NO_ANSWERS,
    OUTCOME_NOT_SCREENED,
    OUTCOME_OK,
    OUTCOME_PARTIAL_FAILURE,
    READINESS_CODES,
    READY,
    OUTCOME_CODES,
    llm_readiness,
    run_outcome,
)


STAGES = ["EL", "IL"]

WORKED = {"records": 85, "answered": 85, "no_answer": 0, "failed": 0,
          "decisions_rejected": 0, "fields_rejected": 0,
          "calls_made": 2, "calls_failed": 0, "batches_failed": 0}
ALL_UNCERTAIN = dict(WORKED)
WHOLLY_FAILED = {"records": 85, "answered": 0, "no_answer": 0, "failed": 85,
                 "decisions_rejected": 0, "fields_rejected": 0,
                 "calls_made": 2, "calls_failed": 2, "batches_failed": 2}

FLAGGED_ONLY = {"OUT": 0, "PASS_CLEAN": 0, "PASS_FLAGGED": 85}
NORMAL = {"OUT": 3, "PASS_CLEAN": 40, "PASS_FLAGGED": 42}


# ---------------------------------------------------------------------------
# The pre-run arm
# ---------------------------------------------------------------------------

# Wave 11 session B: "ready" now means *reachable*, so a case that
# expects READY must say what the probe found. Blocked cases
# short-circuit before the probe check, so passing it everywhere
# keeps these calls uniform without weakening any of them.
_LIVE = types.SimpleNamespace(state="ready", detail="")


class TestReadiness:

    def test_everything_present_is_ready(self):
        r = llm_readiness(stage="EL", has_bundle=True, provider="openai", api_key="sk-test",
                          model="gpt-4o-mini", probe=_LIVE)
        assert r.code == READY and r.can_run is True

    def test_no_bundle_blocks(self):
        r = llm_readiness(stage="EL", has_bundle=False, provider="openai", api_key="sk-test",
                          model="gpt-4o-mini", probe=_LIVE)
        assert r.code == NO_BUNDLE and r.can_run is False

    def test_no_key_blocks(self):
        r = llm_readiness(stage="EL", has_bundle=True, provider="openai", api_key="",
                          model="gpt-4o-mini", probe=_LIVE)
        assert r.code == NO_KEY and r.can_run is False

    @pytest.mark.parametrize("model", ["", "   ", "\t", "\n ", None])
    def test_an_empty_or_whitespace_model_blocks(self, model):
        """F-93's trigger. ``(self.var_model.get() or DEFAULT_MODEL).strip()``
        put the strip *outside* the ``or``, so a whitespace-only field is
        truthy, survives the fallback, and strips to ``""`` — which the
        engine takes as "no model" and skips silently."""
        r = llm_readiness(stage="EL", has_bundle=True, provider="openai", api_key="sk-test",
                          model=model, probe=_LIVE)
        assert r.code == NO_MODEL and r.can_run is False

    def test_a_model_with_surrounding_whitespace_is_accepted(self):
        """Padding is a typo, not a refusal. The engine receives the
        stripped form."""
        r = llm_readiness(stage="EL", has_bundle=True, provider="openai", api_key="sk-test",
                          model="  gpt-4o-mini  ", probe=_LIVE)
        assert r.code == READY and r.model == "gpt-4o-mini"

    def test_the_blocking_order_names_the_first_thing_to_fix(self):
        """With nothing set at all the user is told to load a bundle — the
        step that comes first — rather than sent to find an API key."""
        r = llm_readiness(stage="EL", has_bundle=False, provider="openai", api_key="",
                          model="", probe=_LIVE)
        assert r.code == NO_BUNDLE

    def test_every_blocked_state_explains_itself(self):
        for kw in ({"has_bundle": False, "provider": "openai", "api_key": "sk-test", "model": "m"},
                   {"has_bundle": True, "provider": "openai", "api_key": "", "model": "m"},
                   {"has_bundle": True, "provider": "openai", "api_key": "sk-test", "model": ""}):
            r = llm_readiness(stage="EL", probe=_LIVE, **kw)
            assert r.detail and r.detail.rstrip()[-1] in ".!", r.code

    def test_the_label_fits_the_widget_in_every_state(self):
        """Every code, not just the three the original loop reached.

        Wave 11 session B added four states and the loop below did not
        cover them, so three labels of 18, 18 and 20 characters shipped
        past a test whose whole subject is that this label must not
        exceed 16. A rendering constraint checked over a subset of the
        states is a rendering constraint that holds by luck.
        """
        seen = set()
        for kw in (
            {"has_bundle": False, "provider": "openai", "api_key": "k", "model": "m"},
            {"has_bundle": True, "provider": "", "api_key": "", "model": "m"},
            {"has_bundle": True, "provider": "openai", "api_key": "", "model": "m"},
            {"has_bundle": True, "provider": "openai", "api_key": "k", "model": " "},
            {"has_bundle": True, "provider": "openai", "api_key": "k", "model": "m",
             "probe": None},
            {"has_bundle": True, "provider": "local", "api_key": "", "model": "m",
             "probe": types.SimpleNamespace(state="not_running", detail="d")},
            {"has_bundle": True, "provider": "local", "api_key": "", "model": "m",
             "probe": types.SimpleNamespace(state="no_models", detail="d")},
            {"has_bundle": True, "provider": "openai", "api_key": "k", "model": "m",
             "probe": _LIVE},
        ):
            kw.setdefault("probe", _LIVE)
            r = llm_readiness(stage="EL", **kw)
            seen.add(r.code)
            assert len(r.label) <= 16, f"{r.label!r} is {len(r.label)} chars"
        assert seen == set(READINESS_CODES), (
            f"states never exercised: {set(READINESS_CODES) - seen}"
        )

    def test_the_label_fits_the_widget(self):
        """The indicator is a ``ttk.Label`` in a grid cell that has held
        ``"OPENAI_API_KEY ✓"`` — 16 characters. Nothing may be longer, or
        the actions frame reflows. This is the one property here that is
        genuinely about rendering, so it is pinned rather than eyeballed."""
        for kw in ({"has_bundle": False, "provider": "openai", "api_key": "sk-test", "model": "m"},
                   {"has_bundle": True, "provider": "openai", "api_key": "", "model": "m"},
                   {"has_bundle": True, "provider": "openai", "api_key": "sk-test", "model": " "},
                   {"has_bundle": True, "provider": "openai", "api_key": "sk-test", "model": "m"}):
            r = llm_readiness(stage="EL", probe=_LIVE, **kw)
            assert len(r.label) <= 16, f"{r.label!r} is {len(r.label)} chars"

    def test_the_widget_now_carries_more_than_one_bit(self):
        """F-111's actual complaint, as an assertion."""
        labels = {llm_readiness(stage="EL", has_bundle=b, provider="openai", api_key=("sk-test" if k else ""),
                                model=m, probe=_LIVE).label
                  for b, k, m in ((False, True, "m"), (True, False, "m"),
                                  (True, True, ""), (True, True, "m"))}
        assert len(labels) == 4

    @pytest.mark.parametrize("stage", STAGES)
    def test_it_is_stage_neutral_except_where_it_names_the_stage(self, stage):
        r = llm_readiness(stage=stage, has_bundle=True, provider="openai", api_key="",
                          model="m", probe=_LIVE)
        assert r.code == NO_KEY


# ---------------------------------------------------------------------------
# The post-run arm
# ---------------------------------------------------------------------------

class TestOutcomeStates:

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_wholly_failed_run_is_named(self, stage):
        out = run_outcome(stage=stage, counts=FLAGGED_ONLY,
                          llm_report=WHOLLY_FAILED, cancelled=False,
                          not_screened=False, total_rows=85)
        assert out.code == OUTCOME_NO_ANSWERS
        assert out.ack_reason is not None

    @pytest.mark.parametrize("stage", STAGES)
    def test_an_all_uncertain_run_is_named_differently(self, stage):
        out = run_outcome(stage=stage, counts=FLAGGED_ONLY,
                          llm_report=ALL_UNCERTAIN, cancelled=False,
                          not_screened=False, total_rows=85)
        assert out.code == OUTCOME_NOTHING_SEPARATED
        assert out.ack_reason is not None

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_partly_failed_run_reports_but_does_not_gate(self, stage):
        """A run with a documented hole is a real result. Gating it would
        train the user to click through the dialog that matters."""
        report = dict(WORKED, answered=60, failed=25, calls_failed=1,
                      batches_failed=1)
        out = run_outcome(stage=stage, counts=NORMAL, llm_report=report,
                          cancelled=False, not_screened=False, total_rows=85)
        assert out.code == OUTCOME_PARTIAL_FAILURE
        assert "25" in out.label
        assert out.ack_reason is None

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_vocabulary_mismatch_is_partial_not_dead(self, stage):
        """F-90's residue after its own fix: the model answers, in words
        this stage cannot read. That is neither `ok` nor `no answers`."""
        report = dict(WORKED, answered=60, decisions_rejected=25)
        out = run_outcome(stage=stage, counts=NORMAL, llm_report=report,
                          cancelled=False, not_screened=False, total_rows=85)
        assert out.code == OUTCOME_PARTIAL_FAILURE

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_clean_run_is_still_plainly_done(self, stage):
        out = run_outcome(stage=stage, counts=NORMAL, llm_report=WORKED,
                          cancelled=False, not_screened=False, total_rows=85)
        assert out.code == OUTCOME_OK
        assert out.label == f"{stage} done."
        assert out.ack_reason is None

    @pytest.mark.parametrize("stage", STAGES)
    def test_a_fully_cached_run_is_ok_not_a_failure(self, stage):
        """Zero calls and a full corpus of answers is the cheap re-run, not
        a dead server. They differ because ``answered`` counts records, not
        requests."""
        out = run_outcome(stage=stage, counts=NORMAL,
                          llm_report=dict(WORKED, calls_made=0),
                          cancelled=False, not_screened=False, total_rows=85)
        assert out.code == OUTCOME_OK

    @pytest.mark.parametrize("stage", STAGES)
    def test_no_answers_beats_nothing_separated(self, stage):
        """A dead server also separates nothing. The more specific cause has
        to win, because the two call for opposite responses from the user."""
        out = run_outcome(stage=stage, counts=FLAGGED_ONLY,
                          llm_report=WHOLLY_FAILED, cancelled=False,
                          not_screened=False, total_rows=85)
        assert out.code == OUTCOME_NO_ANSWERS

    @pytest.mark.parametrize("stage", STAGES)
    def test_the_two_gated_states_diagnose_differently(self, stage):
        """One gate, two diagnoses. That is what makes it worth stopping for
        rather than clicking through."""
        broken = run_outcome(stage=stage, counts=FLAGGED_ONLY,
                             llm_report=WHOLLY_FAILED, cancelled=False,
                             not_screened=False, total_rows=85).ack_reason
        unsure = run_outcome(stage=stage, counts=FLAGGED_ONLY,
                             llm_report=ALL_UNCERTAIN, cancelled=False,
                             not_screened=False, total_rows=85).ack_reason
        assert broken != unsure
        assert "Export anyway?" in broken and "Export anyway?" in unsure

    @pytest.mark.parametrize("stage", STAGES)
    def test_cancellation_and_no_criteria_still_win(self, stage):
        assert run_outcome(stage=stage, counts=FLAGGED_ONLY,
                           llm_report=WHOLLY_FAILED, cancelled=True,
                           not_screened=False,
                           total_rows=85).code == OUTCOME_CANCELLED
        assert run_outcome(stage=stage, counts={"NOT_SCREENED": 85},
                           llm_report={}, cancelled=False, not_screened=True,
                           total_rows=85).code == OUTCOME_NOT_SCREENED

    @pytest.mark.parametrize("stage", STAGES)
    def test_it_reads_the_report_rather_than_re_deriving_it(self, stage):
        """The counting substrate exists (wave 8 part 1). A second
        derivation would be two representations of one fact — F-69's shape,
        which this project has shipped four times. The proof is that the
        outcome follows the report even when the counts disagree with it."""
        out = run_outcome(stage=stage, counts=NORMAL,
                          llm_report=WHOLLY_FAILED, cancelled=False,
                          not_screened=False, total_rows=85)
        assert out.code == OUTCOME_NO_ANSWERS, (
            "counts say a normal screening pass; the report says nothing was "
            "answered. The report is the authority on whether the model was "
            "heard from."
        )


# ---------------------------------------------------------------------------
# Extensibility — the property wave 10 needs
# ---------------------------------------------------------------------------

class TestTheModelIsExtensible:

    def test_the_code_sets_are_closed_and_published(self):
        """Wave 11 session B added `endpoint unreachable`, `endpoint set but no model
        pulled` and `keyless server` to the pre-run arm. They are new
        members of READINESS_CODES, reached by new inputs — not changes to
        the existing branches."""
        assert set(READINESS_CODES) == {
            READY, NO_BUNDLE, NO_KEY, NO_MODEL,
            NOT_CONFIGURED, NOT_CHECKED, ENDPOINT_UNREACHABLE,
            NO_MODELS_PULLED}
        assert set(OUTCOME_CODES) == {
            OUTCOME_CANCELLED, OUTCOME_NOT_SCREENED, OUTCOME_NO_ANSWERS,
            OUTCOME_NOTHING_SEPARATED, OUTCOME_PARTIAL_FAILURE, OUTCOME_OK}

    def test_readiness_takes_its_inputs_by_keyword_only(self):
        """So wave 10 can add an `endpoint=` and a `probe=` without
        disturbing a single existing call site."""
        import inspect
        sig = inspect.signature(llm_readiness)
        assert all(p.kind is inspect.Parameter.KEYWORD_ONLY
                   for p in sig.parameters.values())

    def test_run_outcome_takes_its_inputs_by_keyword_only(self):
        import inspect
        sig = inspect.signature(run_outcome)
        assert all(p.kind is inspect.Parameter.KEYWORD_ONLY
                   for p in sig.parameters.values())

    def test_an_unknown_report_key_is_ignored_not_fatal(self):
        """Wave 9 adds provenance to the same report. An outcome must not
        break when the dict grows."""
        out = run_outcome(stage="EL", counts=NORMAL,
                          llm_report=dict(WORKED, model="gemma3",
                                          endpoint="http://localhost:11434"),
                          cancelled=False, not_screened=False, total_rows=85)
        assert out.code == OUTCOME_OK

    def test_a_missing_report_key_is_ignored_not_fatal(self):
        """And a bundle written by an older build has no report at all."""
        out = run_outcome(stage="EL", counts=NORMAL, llm_report={},
                          cancelled=False, not_screened=False, total_rows=85)
        assert out.code == OUTCOME_OK
