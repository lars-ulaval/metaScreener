# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_verdict_gate.py — the wave-15e truth table, asserted cell by cell.

``plugins/_common/verdict_gate.py`` IS the spec (the adjudicated design
committed as data), and this file is its executable assertion: every
``(ctype, decision)`` cell at the unit layer, every
stage × type × decision × provider-mode cell at the engine layer, every
boundary of the substance floor, and the reason-summary branches that
name which policy declined.

The mutation battery targets this file's boundaries: swap a GATE_TABLE
row, move SUBSTANCE_MIN_CHARS by one, turn ``>=`` into ``>``, or revert
rule (c) to ``ACTION_EXCLUDE``, and something below must go red.
"""
import inspect
import json
import threading

import pytest

from conftest import get_el, get_il

from plugins._common import llm_client as lc
from plugins._common import verdict_gate as vg
from plugins._common.bundle import EXCLUSION_SUPPRESSED


# ---------------------------------------------------------------------------
# fakes — the house pattern from tests/test_flag_only.py
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        msg = type("M", (), {"content": json.dumps(payload)})
        self.choices = [type("C", (), {"message": msg})]


def _client(handler):
    """handler receives the whole parsed request body, so an answer can
    depend on WHICH criterion is being screened (the mixed-decliner test
    needs that; test_flag_only's items-only handler cannot express it)."""
    class _Completions:
        def create(self, *, model, messages, temperature, response_format=None):
            return handler(json.loads(messages[1]["content"]))

    return type("C", (), {"chat": type("Chat", (), {
        "completions": _Completions()})()})()


#: Long enough that its verbatim quote clears SUBSTANCE_MIN_CHARS.
def _title(i):
    return f"Title {i} carries enough verbatim substance for the strict gate"


def _answers_by_criterion(decisions, confidence=0.9):
    """{criterion_id: decision} -> a handler quoting each item's title."""
    def _h(body):
        d = decisions[body["criterion"]["id"]]
        return _FakeResponse([
            {"a_id": it["a_id"], "decision": d, "confidence": confidence,
             "field": "title", "quote": it["title"], "span": [0, 1]}
            for it in body["items"]
        ])
    return _h


def _run_engine(monkeypatch, mod, stage, crits_spec, decisions, *, allow,
                confidence=0.9, rows=4):
    """Drive one stage end to end against the by-criterion fake client.

    ``crits_spec`` is [(cid, ctype), ...]; ``decisions`` {cid: decision}.
    ``allow`` is forced at the engine's own binding, exactly as
    test_flag_only._run does and for the same reason.
    """
    engine = inspect.getmodule(mod.run_el_screen if stage == "EL"
                               else mod.run_il_screen)
    monkeypatch.setattr(lc, "_has_openai_key", lambda *_a, **_k: True)
    monkeypatch.setattr(
        lc, "_openai_client_for",
        lambda *_a, **_k: _client(_answers_by_criterion(decisions, confidence)))
    monkeypatch.setattr(engine, "llm_exclusion_allowed",
                        lambda *_a, **_k: allow)
    crits = [mod.Criterion(
        id=cid, stage=stage, ctype=ctype, enabled=True, operator="llm",
        targets=["title"], what_raw="x", what_list=["x"], threshold=0.6,
        source_text="x", label="x",
    ) for cid, ctype in crits_spec]
    parse = mod.ParseReport(
        header=["local_id", "title", "abstract", "keywords"],
        rows=[{"local_id": f"A{i:03d}", "title": _title(i),
               "abstract": "a", "keywords": "k"} for i in range(rows)],
        skipped=[])
    report = mod.CriteriaLoadReport(criteria=crits, warnings=[])
    run = mod.run_el_screen if stage == "EL" else mod.run_il_screen
    return run(parse, report, model="gemma3", trunc_chars=1500, batch_size=4,
               use_cache=False, cache_in={}, cancel_event=threading.Event())


LONG_VALID = "a quote of ample verbatim substance"      # 35 normalised chars


def _action(ctype, decision, *, conf=0.9, thr=0.6, quote=LONG_VALID,
            valid=True):
    return vg.verdict_action(ctype=ctype, decision=decision, confidence=conf,
                             threshold=thr, quote=quote, valid_quote=valid)


# ---------------------------------------------------------------------------
# 1. the table is the spec, pinned literally
# ---------------------------------------------------------------------------

class TestTheTableIsTheSpec:

    def test_the_four_cells_verbatim(self):
        assert vg.GATE_TABLE == {
            ("exclude", "meet"): vg.RULE_REMOVES_BY_PRESENCE,
            ("exclude", "not_meet"): vg.RULE_KEEPS,
            ("include", "meet"): vg.RULE_KEEPS,
            ("include", "not_meet"): vg.RULE_REMOVES_BY_ABSENCE,
        }

    def test_the_table_is_total_over_its_domain(self):
        for ctype in ("include", "exclude"):
            for decision in ("meet", "not_meet"):
                assert (ctype, decision) in vg.GATE_TABLE

    def test_the_substance_floor_is_the_calibrated_constant(self):
        """20, from the frozen wave-14d evidence: fabricated-pass 35 -> 14,
        while every committed genuine exclusion clears it (A499: 102). The
        calibration lives beside the constant; this pin makes moving it a
        deliberate act."""
        assert vg.SUBSTANCE_MIN_CHARS == 20

    def test_substance_uses_the_gates_own_normalisation(self):
        """The floor and ``_quote_in_text`` must agree on what whitespace
        is, or a quote could pass one and fail the other."""
        padded = "word \n\t word  word     word"      # 19 normalised chars
        assert len(lc._normalize_space(padded)) == 19
        assert vg.substance_ok(padded) is False
        assert vg.substance_ok(padded + "x") is True  # 21 normalised


# ---------------------------------------------------------------------------
# 2. the unit layer: every cell, every boundary
# ---------------------------------------------------------------------------

class TestKeepVerdicts:
    """(exclude, not_meet) and (include, meet): confidence only."""

    CELLS = [("exclude", "not_meet"), ("include", "meet")]

    @pytest.mark.parametrize("ctype,decision", CELLS)
    def test_confidence_at_threshold_is_met(self, ctype, decision):
        assert _action(ctype, decision, conf=0.6, thr=0.6) == vg.ACTION_MET

    @pytest.mark.parametrize("ctype,decision", CELLS)
    def test_confidence_below_threshold_is_uncertain(self, ctype, decision):
        assert _action(ctype, decision, conf=0.59, thr=0.6) == \
            vg.ACTION_UNCERTAIN

    @pytest.mark.parametrize("ctype,decision", CELLS)
    @pytest.mark.parametrize("quote,valid", [
        (LONG_VALID, True),   # offered and validated
        (LONG_VALID, False),  # offered and failed validation
        ("", False),          # nothing offered (the F-195 null)
    ])
    def test_the_quote_is_never_consulted(self, ctype, decision, quote, valid):
        """Rule (b): a keep verdict needs no substring — a keep justified
        by absence has none to give, and one justified by presence does
        not need its quote to leave the record in the review."""
        assert _action(ctype, decision, quote=quote, valid=valid) == \
            vg.ACTION_MET


class TestPresenceRemovals:
    """(exclude, meet): the full strict gate — F-191's three clauses plus
    F-21's substance floor."""

    def test_the_full_pass(self):
        assert _action("exclude", "meet") == vg.ACTION_EXCLUDE

    def test_an_invalid_quote_refuses(self):
        assert _action("exclude", "meet", valid=False) == vg.ACTION_UNCERTAIN

    def test_low_confidence_refuses(self):
        assert _action("exclude", "meet", conf=0.59) == vg.ACTION_UNCERTAIN

    def test_confidence_at_threshold_passes(self):
        assert _action("exclude", "meet", conf=0.6) == vg.ACTION_EXCLUDE

    @pytest.mark.parametrize("n,expected", [
        (19, vg.ACTION_UNCERTAIN),   # one short of the floor
        (20, vg.ACTION_EXCLUDE),     # the floor itself
        (21, vg.ACTION_EXCLUDE),
    ])
    def test_the_substance_boundary(self, n, expected):
        assert _action("exclude", "meet", quote="q" * n) == expected

    def test_substance_is_measured_after_normalisation(self):
        """25 raw chars that normalise to 19 must fail: whitespace padding
        cannot buy substance, or the floor would be a raw-length check
        the model can defeat with spaces."""
        padded = "  " + "q" * 9 + " \n\t " + "q" * 9 + "  "
        assert len(lc._normalize_space(padded)) == 19
        assert _action("exclude", "meet", quote=padded) == vg.ACTION_UNCERTAIN

    def test_the_modal_fabrication_is_below_the_floor(self):
        """The calibration's own exemplar: ``"virtual reality"`` is 15
        normalised chars — qwen2.5:7b's modal fabricated quote on the
        frozen 14d evidence — and must sit under the floor."""
        assert _action("exclude", "meet", quote="virtual reality") == \
            vg.ACTION_UNCERTAIN


class TestAbsenceRemovals:
    """(include, not_meet): never ACTION_EXCLUDE — rule (c)."""

    @pytest.mark.parametrize("quote,valid", [
        (LONG_VALID, True),
        (LONG_VALID, False),
        ("", False),
    ])
    def test_confident_absence_is_suppressed_whatever_the_quote(
            self, quote, valid):
        assert _action("include", "not_meet", quote=quote, valid=valid) == \
            vg.ACTION_SUPPRESS_ABSENCE

    def test_confidence_at_threshold_is_the_suppression_boundary(self):
        assert _action("include", "not_meet", conf=0.6) == \
            vg.ACTION_SUPPRESS_ABSENCE
        assert _action("include", "not_meet", conf=0.59) == \
            vg.ACTION_UNCERTAIN, (
                "below threshold it is an ordinary gate refusal — "
                "suppressed and uncertain stay different facts (F-145)"
            )

    def test_no_input_reaches_action_exclude(self):
        """The cell has no path to ACTION_EXCLUDE at any confidence or
        quote — the property the IL hazard re-proof rests on (§2 of the
        wave-15e design)."""
        for conf in (0.0, 0.6, 0.9, 1.0, 99.0):
            for quote, valid in ((LONG_VALID, True), ("", False)):
                assert _action("include", "not_meet", conf=conf, quote=quote,
                               valid=valid) != vg.ACTION_EXCLUDE


class TestTheWhitelistSurvivesEveryRule:
    """``uncertain`` — the model's or the back-fill's — passes nothing."""

    @pytest.mark.parametrize("ctype", ["include", "exclude"])
    @pytest.mark.parametrize("decision", ["uncertain", "maybe", "", "MEET "])
    def test_a_non_whitelisted_decision_is_uncertain(self, ctype, decision):
        """Note ``"MEET "`` — normalisation happens in the parser, not
        here; the gate sees only canonical strings and refuses the rest."""
        assert _action(ctype, decision, conf=1.0) == vg.ACTION_UNCERTAIN


class TestAnUnknownCtypeIsInclude:
    """F-04's closure means the engines can only pass include/exclude;
    anything else (a future caller's bug) must land on the include row —
    the engines' historical ``else`` arm, and the SAFE direction: at
    worst a keep, never an unchecked removal."""

    @pytest.mark.parametrize("ctype", ["", "banana", "EXCLUDE"])
    def test_meet_keeps_and_not_meet_suppresses(self, ctype):
        assert _action(ctype, "meet") == vg.ACTION_MET
        assert _action(ctype, "not_meet") == vg.ACTION_SUPPRESS_ABSENCE


# ---------------------------------------------------------------------------
# 3. the engine layer: every stage x type x decision x provider-mode cell
# ---------------------------------------------------------------------------

#: (ctype, decision, allow) -> (record outcome key, per-criterion status).
#: "FLAGGED" is resolved per stage: PASS_FLAGGED at EL, REVIEW at IL.
ENGINE_MATRIX = {
    ("exclude", "meet", True): ("OUT", "FAILED"),
    ("exclude", "meet", False): (EXCLUSION_SUPPRESSED, "SUPPRESSED"),
    ("exclude", "not_meet", True): ("PASS_CLEAN", "MET"),
    ("exclude", "not_meet", False): ("PASS_CLEAN", "MET"),
    ("include", "meet", True): ("PASS_CLEAN", "MET"),
    ("include", "meet", False): ("PASS_CLEAN", "MET"),
    ("include", "not_meet", True): (EXCLUSION_SUPPRESSED, "SUPPRESSED"),
    ("include", "not_meet", False): (EXCLUSION_SUPPRESSED, "SUPPRESSED"),
    ("exclude", "uncertain", True): ("FLAGGED", "UNCERTAIN"),
    ("exclude", "uncertain", False): ("FLAGGED", "UNCERTAIN"),
    ("include", "uncertain", True): ("FLAGGED", "UNCERTAIN"),
    ("include", "uncertain", False): ("FLAGGED", "UNCERTAIN"),
}


class TestEveryCellOfTheEngineMatrix:
    """24 runs: 2 stages x 2 ctypes x 3 decisions x 2 provider modes.

    This is the truth table exercised through the real engines — the
    binding requirement that every cell of
    stage x type x decision x justification x provider-mode gets a test.
    """

    @pytest.mark.parametrize("getter,stage", [(get_el, "EL"), (get_il, "IL")],
                             ids=["el", "il"])
    @pytest.mark.parametrize("ctype,decision,allow",
                             sorted(ENGINE_MATRIX, key=str))
    def test_the_cell(self, monkeypatch, getter, stage, ctype, decision,
                      allow):
        outcome_key, status = ENGINE_MATRIX[(ctype, decision, allow)]
        flagged = "PASS_FLAGGED" if stage == "EL" else "REVIEW"
        expected_outcome = flagged if outcome_key == "FLAGGED" else outcome_key

        mod = getter()
        full, surv, counts, _imp, _ev, _c, _cx, _rep = _run_engine(
            monkeypatch, mod, stage, [("C-1", ctype)], {"C-1": decision},
            allow=allow)

        sl = stage.lower()
        assert {r[f"{sl}_outcome"] for r in full} == {expected_outcome}, (
            f"cell {(stage, ctype, decision, allow)}"
        )
        ev = json.loads(full[0][f"{sl}_evidence_json"])
        assert ev["C-1"]["status"] == status
        if expected_outcome == "OUT":
            assert surv == []
        else:
            assert len(surv) == 4, "every non-OUT record survives"

    @pytest.mark.parametrize("getter,stage", [(get_el, "EL"), (get_il, "IL")],
                             ids=["el", "il"])
    def test_a_keep_records_the_failed_quote_it_did_not_consult(
            self, monkeypatch, getter, stage):
        """Rule (b)'s recording promise: a quote that is offered is
        validated and recorded, never required. An invalid quote on a
        keep verdict must leave status MET with quote_valid False on the
        record — visible in the modal, gating nothing."""
        mod = getter()
        engine = inspect.getmodule(mod.run_el_screen if stage == "EL"
                                   else mod.run_il_screen)
        monkeypatch.setattr(lc, "_has_openai_key", lambda *_a, **_k: True)

        def _bad_quote(body):
            return _FakeResponse([
                {"a_id": it["a_id"], "decision": "not_meet",
                 "confidence": 0.9, "field": "title",
                 "quote": "a fabricated quote the title does not contain",
                 "span": [0, 1]}
                for it in body["items"]
            ])
        monkeypatch.setattr(lc, "_openai_client_for",
                            lambda *_a, **_k: _client(_bad_quote))
        monkeypatch.setattr(engine, "llm_exclusion_allowed",
                            lambda *_a, **_k: True)
        crits = [mod.Criterion(
            id="C-1", stage=stage, ctype="exclude", enabled=True,
            operator="llm", targets=["title"], what_raw="x", what_list=["x"],
            threshold=0.6, source_text="x", label="x")]
        parse = mod.ParseReport(
            header=["local_id", "title", "abstract", "keywords"],
            rows=[{"local_id": "A000", "title": _title(0),
                   "abstract": "a", "keywords": "k"}],
            skipped=[])
        run = mod.run_el_screen if stage == "EL" else mod.run_il_screen
        full, *_ = run(parse, mod.CriteriaLoadReport(criteria=crits,
                                                     warnings=[]),
                       model="gemma3", trunc_chars=1500, batch_size=4,
                       use_cache=False, cache_in={},
                       cancel_event=threading.Event())
        sl = stage.lower()
        ev = json.loads(full[0][f"{sl}_evidence_json"])
        assert ev["C-1"]["status"] == "MET"
        assert ev["C-1"]["quote_valid"] is False
        assert ev["C-1"]["quote"], "what was offered stays on the record"


# ---------------------------------------------------------------------------
# 4. the reason summary names the decliner
# ---------------------------------------------------------------------------

class TestTheReasonNamesTheDecliner:

    def test_flag_only_presence_keeps_the_f145_text_verbatim(
            self, monkeypatch):
        """The original case, byte-for-byte: no churn for the common
        local-provider run whose suppressions are all flag-only."""
        full, *_ = _run_engine(
            monkeypatch, get_el(), "EL", [("C-1", "exclude")],
            {"C-1": "meet"}, allow=False)
        assert full[0]["el_reason_summary"] == (
            "EXCLUSION_SUPPRESSED: the model returned an excluding "
            "verdict on C-1 which passed the "
            "evidence gate. Flag-only is in force for this provider, so "
            "the record was NOT excluded and needs human review.")

    def test_permitted_absence_names_the_absence_rule_and_not_flag_only(
            self, monkeypatch):
        full, *_ = _run_engine(
            monkeypatch, get_il(), "IL", [("C-1", "include")],
            {"C-1": "not_meet"}, allow=True)
        reason = full[0]["il_reason_summary"]
        assert "never auto-acted, whatever the provider" in reason
        assert "Flag-only is in force" not in reason
        assert "besides" not in reason

    def test_flag_only_absence_names_both_decliners(self, monkeypatch):
        full, *_ = _run_engine(
            monkeypatch, get_il(), "IL", [("C-1", "include")],
            {"C-1": "not_meet"}, allow=False)
        reason = full[0]["il_reason_summary"]
        assert "never auto-acted" in reason
        assert "(flag-only is in force for this provider besides)" in reason

    def test_a_mixed_record_names_each_group(self, monkeypatch):
        """One record, two suppressed criteria with different decliners:
        a presence-removal declined by flag-only and an absence-removal
        declined by rule (c). The reviewer's line must carry both facts."""
        full, *_ = _run_engine(
            monkeypatch, get_el(), "EL",
            [("C-EX", "exclude"), ("C-IN", "include")],
            {"C-EX": "meet", "C-IN": "not_meet"}, allow=False)
        reason = full[0]["el_reason_summary"]
        assert reason.startswith("EXCLUSION_SUPPRESSED: ")
        assert "C-EX" in reason and "passed the evidence gate" in reason
        assert "C-IN" in reason and "never auto-acted" in reason


# ---------------------------------------------------------------------------
# 5. rule (c)'s named counter
# ---------------------------------------------------------------------------

class TestTheNamedCounter:

    def test_absence_suppressions_are_counted_in_the_run_report(
            self, monkeypatch):
        *_, rep = _run_engine(
            monkeypatch, get_il(), "IL", [("C-1", "include")],
            {"C-1": "not_meet"}, allow=False)
        assert rep["absence_suppressed"] == 4

    def test_a_presence_only_suppression_run_records_no_counter(
            self, monkeypatch):
        """Presence-by-key, like ``not_evaluated``: a run with no
        absence-declined verdict says nothing, so 'provider not trusted'
        and 'verdict class not provable' stay tellable apart in the
        manifest."""
        *_, rep = _run_engine(
            monkeypatch, get_el(), "EL", [("C-1", "exclude")],
            {"C-1": "meet"}, allow=False)
        assert "absence_suppressed" not in rep

    def test_a_keep_run_records_no_counter(self, monkeypatch):
        *_, rep = _run_engine(
            monkeypatch, get_il(), "IL", [("C-1", "include")],
            {"C-1": "meet"}, allow=True)
        assert "absence_suppressed" not in rep
