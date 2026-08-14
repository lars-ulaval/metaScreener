# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_flag_only.py — wave 12, F-145: an LLM verdict may flag a record for
review, but may not remove it from a systematic review, unless the user has
explicitly permitted exclusion for the configured provider.

Why this gate exists, measured rather than supposed
---------------------------------------------------
The maintainer ran the built application against two local models over the
same 85-record EL corpus and the same criteria as the committed goldens,
both runs fully attributed by wave 10's provenance block::

    gpt-4o-mini (golden):   1 exclusion.  Audited by the author: correct.
    llama3.2:latest      :  40 and 43 exclusions, two runs. NOT individually
                            audited; 39 and 42 of them were records the
                            audited run kept.
    qwen2.5:7b           :   4 exclusions. All 4 examined individually and
                            wrong, author-confirmed; all 4 baseline-kept.

qwen's four were A286 and A301 (brain-computer interface), A310 (neuromotor
rehabilitation) and A423 (teenagers and social media), all excluded against
EC-2, which asks whether the paper's primary focus is spatial navigation in
a virtual maze. None is a maze-navigation study. The likely mechanism is
that the model read EC-2's parenthetical — "(no social interaction or
collaboration)" — as an independent second condition.

**Every one of those exclusions passed the evidence gate**, with a verbatim
quote and a confidence above threshold. ``_quote_in_text`` verifies that a
quote is *real*; nothing in this pipeline can verify that a quote is
*relevant*. Wave 8's counters show it was not a format failure either:
llama3.2 answered 170 of 170 in perfect JSON with zero rejected
DECISIONS. (Field-vocabulary rejections were 1 and 3, not zero — the two
counters are separate.) It simply asserted matches that were not there.

The conclusion this file pins: a local model can read and annotate; it
cannot be trusted to REMOVE a paper. The cost is five more abstracts on
this corpus — EH removes 125, IH removes 566, EL and IL together remove 5,
so the deterministic stages do 99.3% of the work — in exchange for
eliminating the false-exclusion class entirely, while keeping everything
the model is good at: the reasons, the quotes, and the ordering.

It is §8 of the project's own commitment applied one level up. Every
failure path already routes to human review rather than exclusion; this
says the same rule holds when the *engine* cannot be trusted.

What is asserted here
---------------------
1.  the default follows the provider, and is computed rather than stored;
2.  an explicit user choice wins, in both directions;
3.  a suppressed exclusion is DISTINGUISHABLE from an uncertain flag —
    they are different facts about the record (this is F-34's lesson: a
    stage that reused the stronger label asserted the opposite of the
    truth);
4.  no route produces an exclusion while flag-only is in force;
5.  a suppressing stage does not report as a FAILED stage (the second-F-34
    trap: ``run_outcome``'s ``separated == 0`` branch would otherwise call
    a deliberate, correct run "nothing separated" and gate its export);
6.  the manifest records which artefact this is, and a pre-wave-12 bundle
    reads as *unrecorded* rather than as *exclusion permitted*.
"""
import inspect
import json
import threading

import pytest

from conftest import get_el, get_il

from plugins._common import llm_client as lc
from plugins._common import settings as S
from plugins._common import stage_state as st
from plugins._common.bundle import (
    EXCLUSION_SUPPRESSED,
    history_exclusion_policy,
)

CID = "EC-1"


# ---------------------------------------------------------------------------
# fakes — the house pattern from tests/test_run_report.py
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        msg = type("M", (), {"content": json.dumps(payload)})
        self.choices = [type("C", (), {"message": msg})]


def _client(handler):
    class _Completions:
        def create(self, *, model, messages, temperature, response_format=None):
            return handler(json.loads(messages[1]["content"])["items"])

    return type("C", (), {"chat": type("Chat", (), {
        "completions": _Completions()})()})()


def _answers(decision, confidence=0.9):
    """Every record answered, quote lifted verbatim from the title.

    The quote is the title, so ``_quote_in_text`` validates it: these are
    verdicts that PASS the evidence gate. That is the whole point — the
    measurement above is about confident, well-quoted, wrong exclusions,
    not about malformed ones. The malformed case is already fail-safe.
    """
    def _h(items):
        return _FakeResponse([
            {"a_id": it["a_id"], "decision": decision, "confidence": confidence,
             "field": "title", "quote": it["title"], "span": [0, 1]}
            for it in items
        ])
    return _h


def _build_messages(criterion, items, trunc_chars):
    return [
        {"role": "system", "content": "score the items"},
        {"role": "user", "content": json.dumps(
            {"criterion": criterion, "items": items}, ensure_ascii=False)},
    ]


def _setup(mod, stage, ctype, rows=4):
    crit = mod.Criterion(
        id=CID, stage=stage, ctype=ctype, enabled=True, operator="llm",
        targets=["title"], what_raw="x", what_list=["x"], threshold=0.6,
        source_text="x", label="x",
    )
    parse = mod.ParseReport(
        header=["local_id", "title", "abstract", "keywords"],
        rows=[{"local_id": f"A{i:03d}", "title": f"Title {i}",
               "abstract": "a", "keywords": "k"} for i in range(rows)],
        skipped=[])
    report = mod.CriteriaLoadReport(criteria=[crit], warnings=[])
    run = mod.run_el_screen if stage == "EL" else mod.run_il_screen
    return parse, report, run


def _run(monkeypatch, mod, stage, ctype, decision, *, allow, confidence=0.9,
         rows=4):
    """Drive one stage end to end against a fake client.

    ``allow`` is forced at the engine's own binding rather than by writing
    a settings file, so that the *engine's* behaviour is under test here
    and the *resolution* of the policy is under test separately above.
    Two tests, two subjects.

    It must be patched on the ``screen`` module, not on ``llm_client``:
    ``screen.py`` does ``from plugins._common.llm_client import
    llm_exclusion_allowed``, so it holds its own binding and a patch
    applied to the source module would be silently ignored — the test
    would then pass by testing the default.
    """
    engine = inspect.getmodule(mod.run_el_screen if stage == "EL"
                               else mod.run_il_screen)
    monkeypatch.setattr(lc, "_has_openai_key", lambda *_a, **_k: True)
    monkeypatch.setattr(lc, "_openai_client_for",
                        lambda *_a, **_k: _client(_answers(decision, confidence)))
    monkeypatch.setattr(engine, "llm_exclusion_allowed", lambda *_a, **_k: allow)
    parse, report, run = _setup(mod, stage, ctype, rows=rows)
    return run(parse, report, model="gemma3", trunc_chars=1500, batch_size=4,
               use_cache=False, cache_in={}, cancel_event=threading.Event())


#: The two ways a verdict removes a record, one per stage polarity.
#: EL's criteria are exclude-typed and exclude on ``meet``; IL's are
#: include-typed and exclude on ``not_meet``. The verdict polarity differs
#: but the ACTION is identical — ``failed`` -> ``OUT`` -> dropped from
#: ``survivors`` — which is why one rule covers both and neither stage
#: needs a special case.
EXCLUDING = [
    (get_el, "EL", "exclude", "meet"),
    (get_il, "IL", "include", "not_meet"),
    # The arms each engine labels "not expected", which are nonetheless
    # live: polarity is carried by the criterion's type cell, not by the
    # stage, so a mistyped or third-party criteria table reaches them.
    (get_el, "EL", "include", "not_meet"),
    (get_il, "IL", "exclude", "meet"),
]


# ---------------------------------------------------------------------------
# 1. the default follows the provider, and is computed rather than stored
# ---------------------------------------------------------------------------

class TestTheDefaultFollowsTheProvider:
    """OFF for local and custom; ON for OpenAI, the configuration the
    published validation study measured."""

    @pytest.mark.parametrize("provider", ["local", "custom"])
    def test_a_keyless_provider_may_not_exclude_by_default(self, provider):
        assert st.exclusion_allowed(provider=provider, setting=None) is False, (
            f"{provider!r} is a self-hosted engine, and the measurement in "
            f"this module's docstring is what forbids it to exclude."
        )

    def test_openai_may_exclude_by_default(self):
        assert st.exclusion_allowed(provider="openai", setting=None) is True

    def test_an_unchosen_provider_is_not_a_local_model(self):
        """UNCHOSEN must not be treated as keyless.

        This is not a preference. ``key_required("")`` is True — an
        unconfigured install has always needed a key and has always been
        blocked at ``NOT_CONFIGURED`` — and the golden replays resolve
        exactly this provider, because ``tests/conftest.py`` isolates
        APPDATA/XDG_CONFIG_HOME to an empty directory. A rule that read
        UNCHOSEN as flag-only would move ``tests/golden/el_filtered`` and
        ``il_filtered`` on a wave whose brief says nothing may move.
        """
        assert st.exclusion_allowed(provider=S.UNCHOSEN, setting=None) is True

    def test_the_default_is_the_keyless_predicate_and_not_a_second_one(self):
        """F-117's rule: one predicate per question, not two that drift.

        Asserted over the same cross product ``key_required`` is asserted
        over, so the two cannot disagree about what a keyless provider is.
        """
        for provider in ("local", "custom", "openai", "", "something-new"):
            assert (st.exclusion_allowed(provider=provider, setting=None)
                    is st.key_required(provider)), provider

    def test_nothing_is_stored_for_the_default(self):
        """A stored boolean would be wrong the moment the provider changes.

        ``defaults()`` shipping a concrete value is the shape that billed a
        fresh install (provider="local") and the shape that dropped every
        stage to batch size 5. A module that cannot see the input the
        decision depends on must not assert a value.
        """
        assert S.defaults()["allow_llm_exclusion"] is None


class TestAnExplicitChoiceWins:

    @pytest.mark.parametrize("provider", ["local", "custom", "openai", ""])
    def test_true_permits_and_false_forbids_whatever_the_provider(self, provider):
        assert st.exclusion_allowed(provider=provider, setting=True) is True
        assert st.exclusion_allowed(provider=provider, setting=False) is False

    def test_the_choice_round_trips_through_the_store(self, tmp_path,
                                                      monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        S.save_settings({**S.defaults(), "provider": "local",
                         "allow_llm_exclusion": True})
        cfg = S.resolve_stage(S.load_settings(), "EL")
        assert cfg.allow_llm_exclusion is True

    def test_a_non_boolean_in_the_store_falls_back_to_the_default(self):
        """A hand-edited or corrupted value must not be coerced.

        ``bool("no")`` is True, which would silently PERMIT exclusion for a
        local model — the exact direction of harm this wave exists to close.
        """
        for junk in ("yes", "no", 0, 1, [], "true"):
            cfg = S.resolve_stage(
                {**S.defaults(), "provider": "local",
                 "allow_llm_exclusion": junk}, "EL")
            assert cfg.allow_llm_exclusion is False, junk


# ---------------------------------------------------------------------------
# 2. a suppressed exclusion is distinguishable from an uncertain flag
# ---------------------------------------------------------------------------

class TestTheOutcomeIsItsOwnFact:

    @pytest.mark.parametrize("getter,stage,ctype,decision", EXCLUDING)
    def test_an_excluding_verdict_is_suppressed_not_acted_on(
            self, monkeypatch, getter, stage, ctype, decision):
        full, surv, counts, _imp, _ev, _c, _cx, _rep = _run(
            monkeypatch, getter(), stage, ctype, decision, allow=False)

        sl = stage.lower()
        assert {r[f"{sl}_outcome"] for r in full} == {EXCLUSION_SUPPRESSED}
        assert counts.get("OUT", 0) == 0
        assert len(surv) == 4, "a suppressed exclusion still survives"

    @pytest.mark.parametrize("getter,stage,ctype,decision", EXCLUDING)
    def test_it_is_not_the_label_an_uncertain_record_gets(
            self, monkeypatch, getter, stage, ctype, decision):
        """F-34's lesson, applied to a new outcome.

        "The model said exclude and we did not act on it" and "the model
        could not decide" are different facts about the record, and a
        reader must be able to tell them apart. Here the same corpus is run
        twice: once with a confident, well-quoted excluding verdict under
        flag-only, and once with the same verdict below threshold. The
        outcomes must differ.
        """
        mod = getter()
        sl = stage.lower()
        suppressed, *_ = _run(monkeypatch, mod, stage, ctype, decision,
                              allow=False)
        uncertain, *_ = _run(monkeypatch, mod, stage, ctype, decision,
                             allow=False, confidence=0.1)

        got_suppressed = {r[f"{sl}_outcome"] for r in suppressed}
        got_uncertain = {r[f"{sl}_outcome"] for r in uncertain}
        assert got_suppressed == {EXCLUSION_SUPPRESSED}
        assert got_uncertain.isdisjoint({EXCLUSION_SUPPRESSED}), (
            "a record the gate refused must not be labelled as one whose "
            "verdict was suppressed by policy — the gate rejecting a quote "
            "and the policy declining to act are different facts."
        )

    @pytest.mark.parametrize("getter,stage,ctype,decision", EXCLUDING)
    def test_the_criteria_the_model_wanted_to_exclude_on_are_named(
            self, monkeypatch, getter, stage, ctype, decision):
        """Nothing is thrown away: what the model said is still recorded.

        Kept in the evidence JSON rather than in a new column, because a
        new column moves tests/golden/{el,il}_filtered_v3.1.0.csv and this
        wave's brief says nothing may move.
        """
        full, *_ = _run(monkeypatch, getter(), stage, ctype, decision,
                        allow=False)
        sl = stage.lower()
        ev = json.loads(full[0][f"{sl}_evidence_json"])
        assert ev[CID]["status"] == "SUPPRESSED"
        assert ev[CID]["decision"] == decision
        assert ev[CID]["quote"], "the quote the model gave is still recorded"
        assert ev[CID]["quote_valid"] is True, (
            "the gate PASSED this verdict — that is what makes it a "
            "suppression rather than a rejection"
        )
        assert CID in full[0][f"{sl}_reason_summary"]

    @pytest.mark.parametrize("getter,stage,ctype,decision", EXCLUDING)
    def test_permitting_exclusion_restores_the_old_behaviour_exactly(
            self, monkeypatch, getter, stage, ctype, decision):
        full, surv, counts, _imp, _ev, _c, _cx, _rep = _run(
            monkeypatch, getter(), stage, ctype, decision, allow=True)

        sl = stage.lower()
        assert {r[f"{sl}_outcome"] for r in full} == {"OUT"}
        assert counts.get("OUT", 0) == 4
        assert surv == []


# ---------------------------------------------------------------------------
# 3. no route produces an exclusion while flag-only is in force
# ---------------------------------------------------------------------------

class TestNoRouteExcludes:
    """The mandatory lens for this wave, asserted rather than reasoned.

    Wave 11 produced its billing defect four times by four routes, and each
    time it was found by executing. The equivalent question here is whether
    ANY input can drive a record out of the corpus while flag-only is in
    force.
    """

    @pytest.mark.parametrize("getter,stage", [(get_el, "EL"), (get_il, "IL")])
    @pytest.mark.parametrize("ctype", ["exclude", "include"])
    @pytest.mark.parametrize("decision", ["meet", "not_meet", "uncertain"])
    @pytest.mark.parametrize("confidence", [0.0, 0.6, 1.0, 99.0])
    def test_the_cross_product_never_removes_a_record(
            self, monkeypatch, getter, stage, ctype, decision, confidence):
        full, surv, counts, _imp, _ev, _c, _cx, _rep = _run(
            monkeypatch, getter(), stage, ctype, decision, allow=False,
            confidence=confidence)

        assert counts.get("OUT", 0) == 0
        assert len(surv) == len(full) == 4
        sl = stage.lower()
        assert all(r[f"{sl}_outcome"] != "OUT" for r in full)
        assert all(not r[f"{sl}_failed_ids"] for r in full), (
            "failed_ids drives the OUT branch; a suppressed verdict must "
            "not be written there or the two representations disagree"
        )


# ---------------------------------------------------------------------------
# 4. a suppressing stage is not a failed stage
# ---------------------------------------------------------------------------

class TestASuppressingStageDoesNotReportAsFailed:
    """The second-F-34 trap, closed.

    ``run_outcome``'s fourth branch fires on ``separated == 0``, where
    ``separated = counts["OUT"] + counts["PASS_CLEAN"]``. Suppressing every
    exclusion drives OUT to zero, so without a branch of its own a
    deliberate, correctly configured, fully successful run would report
    "nothing separated — every record flagged" AND raise an export
    acknowledgement gate. That is F-34's shape exactly: the label asserting
    the opposite of what happened.
    """

    def test_it_is_not_reported_as_nothing_separated(self):
        out = st.run_outcome(
            stage="EL",
            counts={"OUT": 0, "PASS_CLEAN": 0, EXCLUSION_SUPPRESSED: 4},
            llm_report={"records": 4, "answered": 4},
            cancelled=False, not_screened=False, total_rows=4)

        assert out.code == st.OUTCOME_EXCLUSIONS_SUPPRESSED
        assert out.code != st.OUTCOME_NOTHING_SEPARATED

    def test_it_does_not_gate_the_export(self):
        out = st.run_outcome(
            stage="EL",
            counts={"OUT": 0, "PASS_CLEAN": 0, EXCLUSION_SUPPRESSED: 4},
            llm_report={"records": 4, "answered": 4},
            cancelled=False, not_screened=False, total_rows=4)

        assert out.ack_reason is None, (
            "a stage that suppressed exclusions did its job; asking the "
            "user to acknowledge it as damage is the F-34 error again"
        )

    def test_the_count_reaches_the_run_summary(self):
        out = st.run_outcome(
            stage="EL",
            counts={"OUT": 0, "PASS_CLEAN": 1, EXCLUSION_SUPPRESSED: 3},
            llm_report={"records": 4, "answered": 4},
            cancelled=False, not_screened=False, total_rows=4)

        assert "3" in out.label
        assert out.code == st.OUTCOME_EXCLUSIONS_SUPPRESSED

    def test_a_real_failure_still_beats_it(self):
        """Ordering: a dead server separates nothing AND suppresses
        nothing, and must still report as a dead server."""
        out = st.run_outcome(
            stage="EL", counts={"OUT": 0, "PASS_CLEAN": 0},
            llm_report={"records": 4, "answered": 0, "failed": 4},
            cancelled=False, not_screened=False, total_rows=4)

        assert out.code == st.OUTCOME_NO_ANSWERS

    def test_cancellation_still_beats_it(self):
        out = st.run_outcome(
            stage="EL", counts={EXCLUSION_SUPPRESSED: 4},
            llm_report={"records": 4, "answered": 4},
            cancelled=True, not_screened=False, total_rows=4)

        assert out.code == st.OUTCOME_CANCELLED

    def test_the_code_set_stays_closed(self):
        assert st.OUTCOME_EXCLUSIONS_SUPPRESSED in st.OUTCOME_CODES


# ---------------------------------------------------------------------------
# 5. the count comes from the substrate, not from a second derivation
# ---------------------------------------------------------------------------

class TestTheCountIsNotReDerived:
    """F-69's shape: two representations of one fact with nothing forcing
    them to agree. This project has shipped four instances."""

    @pytest.mark.parametrize("getter,stage,ctype,decision", EXCLUDING)
    def test_the_outcome_histogram_carries_it(self, monkeypatch, getter,
                                              stage, ctype, decision):
        full, _surv, counts, _imp, _ev, _c, _cx, _rep = _run(
            monkeypatch, getter(), stage, ctype, decision, allow=False)

        sl = stage.lower()
        assert counts[EXCLUSION_SUPPRESSED] == 4
        assert counts[EXCLUSION_SUPPRESSED] == sum(
            1 for r in full if r[f"{sl}_outcome"] == EXCLUSION_SUPPRESSED), (
            "the histogram and the rows must agree by construction, not by "
            "a second scan"
        )

    @pytest.mark.parametrize("getter,stage", [(get_el, "EL"), (get_il, "IL")])
    def test_it_is_a_member_of_the_declared_vocabulary(self, getter, stage):
        assert EXCLUSION_SUPPRESSED in getter().OUTCOMES


# ---------------------------------------------------------------------------
# 6. the manifest says which artefact this is
# ---------------------------------------------------------------------------

class TestTheManifestRecordsThePolicy:

    @pytest.mark.parametrize("getter,stage,ctype,decision", EXCLUDING)
    def test_the_run_report_carries_the_policy(self, monkeypatch, getter,
                                               stage, ctype, decision):
        *_rest, report = _run(monkeypatch, getter(), stage, ctype, decision,
                              allow=False)
        assert report["exclusion_policy"] == "flag_only"

    @pytest.mark.parametrize("getter,stage,ctype,decision", EXCLUDING)
    def test_a_permitting_run_says_so_too(self, monkeypatch, getter, stage,
                                          ctype, decision):
        *_rest, report = _run(monkeypatch, getter(), stage, ctype, decision,
                              allow=True)
        assert report["exclusion_policy"] == "exclusion_permitted"

    def test_it_is_not_inside_the_provenance_block(self, monkeypatch):
        """Deliberate disagreement with the brief, and the reason.

        Wave 10's contract is that a cached entry cannot be served into a
        run whose provenance differs in any recorded field except
        ``batch_size``. Flag-only cannot affect a verdict — it acts
        strictly downstream of one — so recording it inside provenance
        would force either a pointless cache invalidation on every policy
        toggle, or a second unexplained exception to a pinned contract.
        A sibling states the fact without touching either.
        """
        *_rest, report = _run(monkeypatch, get_el(), "EL", "exclude", "meet",
                              allow=False)
        assert "exclusion_policy" not in report.get("provenance", {})
        assert "exclusion_policy" in report

    def test_an_old_bundle_reads_as_unrecorded_not_as_permitted(self):
        """F-68's rule: 'not measured' must never coerce to a positive claim.

        Every bundle written before this wave lacks the key. Reading that
        as "exclusion was permitted" would put a false claim about a real
        screening decision into a reviewer's hands.
        """
        assert history_exclusion_policy({}) is None
        assert history_exclusion_policy({"exclusion_policy": None}) is None
        assert history_exclusion_policy({"stage": "EL"}) is None

    def test_a_recorded_policy_reads_back(self):
        assert history_exclusion_policy(
            {"exclusion_policy": "flag_only"}) is True
        assert history_exclusion_policy(
            {"exclusion_policy": "exclusion_permitted"}) is False

    def test_an_unrecognised_value_is_unknown_rather_than_guessed(self):
        for junk in ("", "yes", True, False, 0, [], {}):
            assert history_exclusion_policy(
                {"exclusion_policy": junk}) is None, junk


# ---------------------------------------------------------------------------
# 7. what the wave 12 review found — F-153
# ---------------------------------------------------------------------------

class TestSuppressionDoesNotCancelTheExportGate:
    """F-153. The review's confirmed finding, with its own repro.

    The branch added above for the second-F-34 problem was guarded on
    ``if suppressed:`` alone and sat above ``nothing_separated``. So
    **one** suppressed record among nineteen unresolved ones cancelled
    the export acknowledgement for the entire run: two runs over the same
    corpus, identical in every way that matters to a reader, one gated
    and one exporting in silence.

    Worse, it was self-reinforcing. Flag-only is on precisely for the
    weak local models that also produce unresolved verdicts, so the runs
    most likely to be degenerate were the runs most likely to contain a
    suppression that silenced the gate — F-93 built that gate so a
    degenerate run could not reach the next stage unnoticed.

    The repair is in ``separated``, not in the branch: a suppressed
    record received a confident, gate-passing verdict, so it is work
    done. The property that decides it is the last test here.
    """

    def _outcome(self, *, suppressed, flagged, clean=0, out=0, answered=20,
                 records=20, failed=0, total_rows=20):
        counts = {"OUT": out, "PASS_CLEAN": clean, "PASS_FLAGGED": flagged,
                  EXCLUSION_SUPPRESSED: suppressed}
        return st.run_outcome(
            stage="EL", counts=counts,
            llm_report={"records": records, "answered": answered,
                        "failed": failed},
            cancelled=False, not_screened=False, total_rows=total_rows)

    def test_a_degenerate_run_is_still_gated(self):
        """Run A: nothing separated, nothing suppressed."""
        out = self._outcome(suppressed=0, flagged=20)
        assert out.code == st.OUTCOME_NOTHING_SEPARATED
        assert out.ack_reason is not None

    def test_one_suppression_does_not_silence_that_gate(self):
        """Run B: the review's repro. Nothing separated, one suppressed.

        A single suppressed record must not buy silence for nineteen
        unresolved ones — but it is not nothing either, so the run is no
        longer *nothing* separated. What decides the case is the
        equivalence asserted below.
        """
        out = self._outcome(suppressed=1, flagged=19)
        assert out.code != st.OUTCOME_NOTHING_SEPARATED

    def test_a_wholly_suppressed_run_is_not_called_damage(self):
        """The case the branch exists for, still working."""
        out = self._outcome(suppressed=20, flagged=0)
        assert out.code == st.OUTCOME_EXCLUSIONS_SUPPRESSED
        assert out.ack_reason is None

    def test_the_two_policies_judge_a_run_identically(self):
        """**The property the repair turns on.**

        The same model behaviour produces ``1 OUT + 19 flagged`` with
        exclusion permitted and ``1 suppressed + 19 flagged`` under
        flag-only. A policy about what to *do* with verdicts must not
        change how the run's *quality* is judged — otherwise flag-only
        is stricter than exclusion-permitted about an outcome the model
        produced either way, which is a new inconsistency in place of the
        one being fixed.
        """
        permitted = self._outcome(suppressed=0, flagged=19, out=1)
        flag_only = self._outcome(suppressed=1, flagged=19, out=0)
        assert (permitted.ack_reason is None) == (flag_only.ack_reason is None)

    def test_gaps_are_still_reported_when_suppression_wins_the_branch(self):
        """``partial_failure``'s label is the only run-level statement of
        failed and unreadable calls, and this branch sits above it."""
        out = self._outcome(suppressed=5, flagged=5, failed=9, answered=11)
        assert out.code == st.OUTCOME_EXCLUSIONS_SUPPRESSED
        assert "9 failed" in out.label, out.label

    def test_a_dead_server_still_reports_as_one(self):
        out = self._outcome(suppressed=0, flagged=20, answered=0, failed=20)
        assert out.code == st.OUTCOME_NO_ANSWERS


class TestTheRunSummaryCountsTheNewOutcome:
    """F-153, second half: F-34's requirement 2, for the new value.

    ``_run_summary_counts_text`` is the line a user reads as the result
    of the run. F-145 added an outcome and did not add it here, so a
    flag-only run over 20 records reported ``OUT: 0 | PASS_CLEAN: 0 |
    PASS_FLAGGED: 19`` — a record missing and the arithmetic visibly
    wrong. Adding an outcome without adding it here reproduces the
    original F-34 defect for the new value.
    """

    def test_the_suppressed_records_appear(self):
        from plugins._common.bundle import _run_summary_counts_text
        text = _run_summary_counts_text(
            {"OUT": 0, "PASS_CLEAN": 0, "PASS_FLAGGED": 19,
             EXCLUSION_SUPPRESSED: 1},
            stage="EL", total_rows=20)
        assert EXCLUSION_SUPPRESSED in text, text
        assert "1" in text

    def test_the_numbers_account_for_every_record(self):
        from plugins._common.bundle import _run_summary_counts_text
        counts = {"OUT": 2, "PASS_CLEAN": 3, "PASS_FLAGGED": 4,
                  EXCLUSION_SUPPRESSED: 11}
        text = _run_summary_counts_text(counts, stage="EL", total_rows=20)
        shown = sum(int(p.split(":")[1]) for p in text.split(" | "))
        assert shown == 20, (shown, text)

    def test_a_run_without_suppressions_says_nothing_new(self):
        """No existing line moves."""
        from plugins._common.bundle import _run_summary_counts_text
        text = _run_summary_counts_text(
            {"OUT": 1, "PASS_CLEAN": 2, "PASS_FLAGGED": 3},
            stage="EL", total_rows=6)
        assert text == "OUT: 1 | PASS_CLEAN: 2 | PASS_FLAGGED: 3"


# ---------------------------------------------------------------------------
# 8. what session B's reproduction found — F-156
# ---------------------------------------------------------------------------

class TestTheCriterionDrillDownShowsSuppressedRecords:
    """F-156. The drill-down hid exactly the records flag-only exists for.

    ``_refresh_reports_view`` filters the FULL and SURVIVORS tables to the
    records a clicked criterion touched, by testing four lists: ``failed``,
    ``missing``, ``met``, ``uncertain``. F-145 added a fifth, ``suppressed``,
    and did not add it here — and by design a suppressed criterion goes into
    that list *instead of* ``failed``, because putting it in both is the
    two-representations defect ``_excluded_by`` exists to avoid.

    So the records the model asked to remove, which survive precisely so a
    human will read them, were absent from the view a human uses to read
    them. Measured before the fix, on a four-record flag-only run::

        crit_impacts                            : {'EC-1': {'failed': 4, ...}}
        records suppressed on EC-1              : 4
        records the EC-1 drill-down would show  : 0

    The criteria table said the criterion had acted on four records and the
    drill-down beside it showed none of them. Flag-only's whole value is
    that somebody reads the record; losing it at the point of reading gives
    back everything F-145 bought.
    """

    def test_every_list_counts_as_touched(self):
        for key in st.CRITERION_ROW_LISTS:
            ev = {k: ([] if k != key else ["EC-1"])
                  for k in st.CRITERION_ROW_LISTS}
            assert st.criterion_touched(ev, "EC-1") is True, key

    def test_an_untouched_criterion_is_not_shown(self):
        ev = {k: [] for k in st.CRITERION_ROW_LISTS}
        assert st.criterion_touched(ev, "EC-1") is False

    def test_a_missing_key_does_not_raise(self):
        """The Views pass a default dict on a short ``row_eval_lists``."""
        assert st.criterion_touched({}, "EC-1") is False
        assert st.criterion_touched({"failed": None}, "EC-1") is False

    # -- the vocabulary guard, rebuilt in wave 12 session C (F-161) --------
    #
    # What was here before::
    #
    #     LISTS = ("failed", "missing", "met", "uncertain", "suppressed")
    #     def test_the_vocabulary_is_the_engine_s(self):
    #         assert set(st.CRITERION_ROW_LISTS) == set(self.LISTS)
    #
    # Two copies of one literal, neither of them the engine. The engine
    # spelled the set out in four dict literals of its own and did not
    # import stage_state at all, so the two could diverge with nothing to
    # notice. Measured: splitting a sixth list out of ``uncertain`` on the
    # engine side left this file at 117 passed while the drill-down went
    # 4 of 4 to 0 of 4.
    #
    # This is the THIRD time this project has shipped a fixture certifying
    # a state the system cannot produce. Wave 11 session B's
    # ``probe=SimpleNamespace(state="ready")`` for ``provider="openai"``
    # was the first, and 926 tests were green while the OpenAI provider
    # could not run at all; ``test_model_discovery.py`` answered it by
    # building every fixture from the real producer and forbidding the
    # constructors by AST. The rule that came out of it, applied here: a
    # fixture that constructs a state by hand must be checkable against the
    # producer that would create it in production.
    #
    # So the vocabulary below is READ OFF THE ENGINE, by running it.

    @pytest.mark.parametrize("getter,stage,ctype,decision", EXCLUDING)
    def test_the_vocabulary_is_the_engine_s(
            self, monkeypatch, getter, stage, ctype, decision):
        """The names come from a real run, not from a literal."""
        _f, _s, _c, _i, evals, _ca, _cx, _r = _run(
            monkeypatch, getter(), stage, ctype, decision, allow=False)
        assert evals, "the engine produced no per-record lists to read"
        for produced in evals:
            assert set(produced) == set(st.CRITERION_ROW_LISTS), (
                "the engine emitted %s where stage_state names %s — the "
                "vocabulary grew on one side only, which is F-156 again"
                % (sorted(produced), sorted(st.CRITERION_ROW_LISTS))
            )

    @pytest.mark.parametrize("getter,stage,ctype", [
        (get_el, "EL", "exclude"), (get_il, "IL", "include")])
    def test_the_no_criteria_path_emits_the_same_vocabulary(
            self, monkeypatch, getter, stage, ctype):
        """The engine builds these lists at two sites, not one.

        The second is the "no enabled criteria" early return, which a run
        with everything disabled is the only way to reach. Reading only the
        normal path would leave half the producer unchecked.
        """
        mod = getter()
        crit = mod.Criterion(
            id=CID, stage=stage, ctype=ctype, enabled=False, operator="llm",
            targets=["title"], what_raw="x", what_list=["x"], threshold=0.6,
            source_text="x", label="x",
        )
        parse = mod.ParseReport(
            header=["local_id", "title", "abstract", "keywords"],
            rows=[{"local_id": "A%03d" % i, "title": "Title %d" % i,
                   "abstract": "a", "keywords": "k"} for i in range(3)],
            skipped=[])
        report = mod.CriteriaLoadReport(criteria=[crit], warnings=[])
        run = mod.run_el_screen if stage == "EL" else mod.run_il_screen
        _f, _s, _c, _i, evals, _ca, _cx, _r = run(
            parse, report, model="gemma3", trunc_chars=1500, batch_size=4,
            use_cache=False, cache_in={}, cancel_event=threading.Event())
        assert evals, "the no-criteria path produced no per-record lists"
        for produced in evals:
            assert set(produced) == set(st.CRITERION_ROW_LISTS)

    def test_the_engine_refuses_to_emit_a_vocabulary_it_did_not_declare(self):
        """The guarantee is at the producing site, not only here.

        ``criterion_row_lists`` raises when the keys and
        ``CRITERION_ROW_LISTS`` disagree, so a sixth list added on one side
        stops the run at the first record instead of travelling to a View
        that silently shows nothing. A test can be deleted; this cannot be
        stepped around.
        """
        ok = st.criterion_row_lists(
            **{k: [] for k in st.CRITERION_ROW_LISTS})
        assert list(ok) == list(st.CRITERION_ROW_LISTS)

        with pytest.raises(ValueError) as short:
            st.criterion_row_lists(
                **{k: [] for k in st.CRITERION_ROW_LISTS[:-1]})
        assert st.CRITERION_ROW_LISTS[-1] in str(short.value)

        with pytest.raises(ValueError) as sixth:
            st.criterion_row_lists(
                gate_rejected=[], **{k: [] for k in st.CRITERION_ROW_LISTS})
        assert "gate_rejected" in str(sixth.value)

    def test_this_file_holds_no_second_copy_of_the_vocabulary(self):
        """Read as structure, not as text: the comment above quotes the
        deleted literal in order to explain it, so a substring search would
        match the explanation rather than a violation.

        Flags any tuple/list/set literal holding two or more of the
        vocabulary's names. A single name as a dict subscript is fine and
        is used throughout; a *collection* of them is a second spelling.
        """
        import ast
        from pathlib import Path
        from conftest import PROJECT_ROOT

        vocab = set(st.CRITERION_ROW_LISTS)
        src = Path(PROJECT_ROOT, "tests", "test_flag_only.py").read_text(
            encoding="utf-8")
        offenders = []
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                continue
            names = [e.value for e in node.elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len(vocab.intersection(names)) >= 2:
                offenders.append("line %d: %s" % (node.lineno, sorted(names)))
        assert offenders == [], (
            "this file spells the criterion vocabulary out again:\n  "
            + "\n  ".join(offenders)
            + "\n\nRead it off the engine instead — that is F-161."
        )

    @pytest.mark.parametrize("getter,stage,ctype,decision", EXCLUDING)
    def test_a_suppressed_record_is_reachable_from_its_criterion(
            self, monkeypatch, getter, stage, ctype, decision):
        """End to end against the real engine: run flag-only, then apply
        the predicate the View applies."""
        full, _surv, _counts, impacts, evals, _c, _cx, _rep = _run(
            monkeypatch, getter(), stage, ctype, decision, allow=False)

        shown = [r for i, r in enumerate(full)
                 if st.criterion_touched(evals[i], CID)]
        assert len(shown) == len(full) == 4, (
            "the criterion's own drill-down must show the records it "
            "suppressed"
        )
        # and the count beside it must not contradict the table
        assert impacts[CID]["failed"] == len(shown)
