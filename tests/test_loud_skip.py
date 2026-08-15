# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""test_loud_skip.py — F-65's existing-bundle half (wave 15c): a criterion
the stage cannot evaluate is skipped LOUDLY now, with outcomes and exports
byte-identical.

What the engines did until this wave, measured and quoted in the wave
design: a non-`llm` criterion at EL/IL back-filled `llm_results` with an
inert stub per record, and `summarize_llm_evidence` counted every stub as
`no_answer` — model silence — so `run_outcome` diagnosed "low answer rate
… came back unreadable" about requests that were never sent, into the
manifest. Meanwhile the criterion's absence was named nowhere a user
looks: not the run report, not the manifest, not the completion message,
not the row-detail modal.

Now: the run report carries ``not_evaluated`` per criterion (and the
manifest inherits it, since `_write_llm_stage_bundle` copies the report
into ``pipeline.history[].llm``); the stubs are gone, so the answer-rate
arithmetic describes the model again; and `run_outcome` names the
criterion and the cause in the completion message, in F-173's register.
Record-level artefacts — outcomes, `*_uncertain_ids`, evidence JSON —
are unchanged, which the EL/IL golden replays prove corpus-wide.
"""
import json
import threading
import types

import pytest

from conftest import get_el, get_il

import plugins._common.llm_client as lc
from plugins._common.stage_state import run_outcome


class _FakeResponse:
    def __init__(self, payload):
        msg = type("M", (), {"content": json.dumps(payload)})
        self.choices = [type("C", (), {"message": msg})]


def _client():
    class _Completions:
        def create(self, *, model, messages, temperature, response_format=None):
            items = json.loads(messages[1]["content"])["items"]
            return _FakeResponse([
                {"a_id": it["a_id"], "decision": "meet", "confidence": 0.9,
                 "field": "title", "quote": it["title"], "span": [0, 1]}
                for it in items
            ])

    return type("C", (), {"chat": type("Chat", (), {
        "completions": _Completions()})()})()


def _crit(mod, cid, operator, stage):
    return mod.Criterion(
        id=cid, stage=stage, ctype="exclude", enabled=True,
        operator=operator, targets=["title"], what_raw="x", what_list=["x"],
        threshold=0.6 if operator == "llm" else None,
        source_text="x", label="x")


def _run(monkeypatch, get_mod, stage, operators, rows=4):
    mod = get_mod()
    calls = {"n": 0}

    def _counting_client(*_a, **_k):
        calls["n"] += 1
        return _client()

    monkeypatch.setattr(lc, "_has_openai_key", lambda *_a, **_k: True)
    monkeypatch.setattr(lc, "time",
                        types.SimpleNamespace(sleep=lambda *_a: None))
    monkeypatch.setattr(lc, "_openai_client_for", _counting_client)
    parse = mod.ParseReport(
        header=["local_id", "title", "abstract", "keywords"],
        rows=[{"local_id": f"A{i:03d}", "title": f"Title {i}",
               "abstract": "a", "keywords": "k"} for i in range(rows)],
        skipped=[])
    report = mod.CriteriaLoadReport(
        criteria=[_crit(mod, cid, op, stage) for cid, op in operators],
        warnings=[])
    run = mod.run_el_screen if stage == "EL" else mod.run_il_screen
    out = run(parse, report, model="gemma3", trunc_chars=1500, batch_size=4,
              use_cache=False, cache_in={}, cancel_event=threading.Event())
    return out, calls["n"]


PARAMS = [(get_el, "EL"), (get_il, "IL")]


class TestTheRunReportNamesTheSkip:
    @pytest.mark.parametrize("get_mod,stage", PARAMS)
    def test_not_evaluated_is_in_the_report_per_criterion(
            self, monkeypatch, get_mod, stage):
        out, _n = _run(monkeypatch, get_mod, stage,
                       [("EC-L", "llm"), ("EC-D", "contains")])
        report = out[7]
        assert "not_evaluated" in report
        assert set(report["not_evaluated"]) == {"EC-D"}
        reason = report["not_evaluated"]["EC-D"]
        assert "contains" in reason and stage in reason
        assert "F-65" in reason

    @pytest.mark.parametrize("get_mod,stage", PARAMS)
    def test_a_fully_llm_run_carries_no_such_key(
            self, monkeypatch, get_mod, stage):
        out, _n = _run(monkeypatch, get_mod, stage, [("EC-L", "llm")])
        assert "not_evaluated" not in out[7]


class TestTheStubsAreGoneFromTheArithmetic:
    @pytest.mark.parametrize("get_mod,stage", PARAMS)
    def test_records_count_llm_pairs_only(self, monkeypatch, get_mod, stage):
        """4 rows × 1 llm criterion = 4 pairs. The stub era counted 8
        (both criteria), with the deterministic half as no_answer —
        model silence that never involved the model."""
        out, _n = _run(monkeypatch, get_mod, stage,
                       [("EC-L", "llm"), ("EC-D", "contains")], rows=4)
        report = out[7]
        assert report["records"] == 4
        assert report["answered"] == 4
        assert report["no_answer"] == 0

    @pytest.mark.parametrize("get_mod,stage", PARAMS)
    def test_a_deterministic_only_run_reports_zero_records_and_calls(
            self, monkeypatch, get_mod, stage):
        out, n_clients = _run(monkeypatch, get_mod, stage,
                              [("EC-D", "contains")])
        report = out[7]
        assert report["records"] == 0
        assert report["not_evaluated"] and "EC-D" in report["not_evaluated"]
        assert n_clients == 0, "no model may be consulted for a run with " \
            "nothing to ask it"

    @pytest.mark.parametrize("get_mod,stage", PARAMS)
    def test_the_record_level_artefacts_are_unchanged(
            self, monkeypatch, get_mod, stage):
        """The skip stays UNCERTAIN with the same evidence note — the
        visibility lands in the report and the message, never in the
        rows, so already-harmonised bundles replay identically (the
        golden regressions prove the same corpus-wide)."""
        out, _n = _run(monkeypatch, get_mod, stage,
                       [("EC-L", "llm"), ("EC-D", "contains")])
        full_rows = out[0]
        sl = stage.lower()
        for fr in full_rows:
            ev = json.loads(fr[f"{sl}_evidence_json"])
            assert ev["EC-D"] == {
                "status": "UNCERTAIN",
                "note": f"non-llm operator in {stage} stage"}
            assert "EC-D" in fr[f"{sl}_uncertain_ids"]


class TestTheCompletionMessageNamesIt:
    def _report(self, **kw):
        base = {"records": 4, "answered": 4, "no_answer": 0, "failed": 0,
                "decisions_rejected": 0, "calls_failed": 0}
        base.update(kw)
        return base

    def _counts(self):
        return {"OUT": 2, "PASS_CLEAN": 0, "PASS_FLAGGED": 2}

    def test_the_label_and_ack_name_criterion_and_cause(self):
        o = run_outcome(
            stage="IL", counts=self._counts(),
            llm_report=self._report(not_evaluated={
                "IC-5": "not evaluated: deterministic operator 'contains' "
                        "at IL, which runs llm only (F-65)"}),
            cancelled=False, not_screened=False, total_rows=4)
        assert "IC-5" in o.label
        assert "not evaluated" in o.label
        assert o.ack_reason is not None
        assert "contains" in o.ack_reason
        assert "llm only" in o.ack_reason
        assert "recommend" not in (o.label + o.ack_reason).lower()

    def test_without_the_key_nothing_changes(self):
        base = run_outcome(
            stage="IL", counts=self._counts(), llm_report=self._report(),
            cancelled=False, not_screened=False, total_rows=4)
        assert "not evaluated" not in base.label

    def test_the_code_is_the_base_classification(self):
        """Naming the skip must not invent an outcome code — the run's
        classification stays whatever the arithmetic says, and the
        naming rides on it."""
        with_skip = run_outcome(
            stage="IL", counts=self._counts(),
            llm_report=self._report(not_evaluated={"IC-5": "reason"}),
            cancelled=False, not_screened=False, total_rows=4)
        without = run_outcome(
            stage="IL", counts=self._counts(), llm_report=self._report(),
            cancelled=False, not_screened=False, total_rows=4)
        assert with_skip.code == without.code

    def test_a_cancelled_run_stays_bare(self):
        o = run_outcome(
            stage="IL", counts={}, llm_report=self._report(
                not_evaluated={"IC-5": "reason"}),
            cancelled=True, not_screened=False, total_rows=4)
        assert "IC-5" not in o.label, (
            "a cancelled run tells you nothing about what it would have "
            "screened — including this")
