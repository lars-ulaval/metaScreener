
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_run_report.py — wave 8: the engine and the bundle must be able to say
that a run did not work.

`_write_llm_stage_bundle` hard-coded ``cancelled: False`` and recorded no
error count, so a wholly failed run and a wholly uncertain run were
indistinguishable in the exported bundle. Both produce every record
``PASS_FLAGGED``, ``survivors == rows``, ``not_screened: False`` and
``cancelled: False`` — and the engine returned nothing a caller could use to
tell them apart either.

**The distinction the whole wave turns on is between a model that answered
"uncertain" and a model that did not answer.** They are opposite situations
with opposite remedies — one is a scientific result, the other is a
misconfiguration — and today they are one message.

The design these tests pin, in two rules:

  *A fact about a record is derived from the record.* ``records``,
  ``answered``, ``no_answer``, ``failed``, ``decisions_rejected`` and
  ``fields_rejected`` are recomputed by ``summarize_llm_evidence`` from the
  evidence map the decisions were actually made from. Nothing increments
  them, so they cannot drift from it — this project has been bitten four
  times by a count maintained alongside the thing it counts, most recently
  by the register's own severity totals (F-131).

  *A fact about a call is counted at the call*, because a call that raised
  and was then salvaged by halving leaves no record behind. ``calls_made``,
  ``calls_failed`` and ``batches_failed`` are the only stored numbers, and
  they are stored in a caller-supplied dict rather than returned, because
  ``run_m1_llm_for_criterion``'s return type is pinned as a plain mapping by
  fourteen existing tests.
"""
import ast
import json
import threading
import types
import zipfile
from pathlib import Path

import httpx
import openai
import pytest

from conftest import PROJECT_ROOT, get_el, get_il

import plugins._common.llm_client as lc
from plugins._common.bundle import _write_llm_stage_bundle


CID = "EC-1"
_REQ = httpx.Request("POST", "http://localhost:11434/v1/chat/completions")


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        msg = type("M", (), {"content": json.dumps(payload)})
        self.choices = [type("C", (), {"message": msg})]


def _client(handler):
    """Build a fake OpenAI client from a function of the item list."""
    class _Completions:
        def create(self, *, model, messages, temperature):
            return handler(json.loads(messages[1]["content"])["items"])

    return type("C", (), {"chat": type("Chat", (), {
        "completions": _Completions()})()})()


def _answers(decision="meet", confidence=0.9):
    def _h(items):
        return _FakeResponse([
            {"a_id": it["a_id"], "decision": decision, "confidence": confidence,
             "field": "title", "quote": it["title"], "span": [0, 1]}
            for it in items
        ])
    return _h


def _raises(exc):
    def _h(_items):
        raise exc
    return _h


def _build_messages(criterion, items, trunc_chars):
    return [
        {"role": "system", "content": "score the items"},
        {"role": "user", "content": json.dumps(
            {"criterion": criterion, "items": items}, ensure_ascii=False)},
    ]


@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setattr(lc, "_has_openai_key", lambda *_a, **_k: True)
    monkeypatch.setattr(lc, "time", types.SimpleNamespace(sleep=lambda *_a: None))
    return lc


def _call(monkeypatch, handler, n_items=4, batch_size=2, stats=None):
    monkeypatch.setattr(lc, "_openai_client_for", lambda *_a, **_k: _client(handler))
    items = [{"a_id": f"A{i:03d}", "title": f"Title {i}", "abstract": "",
              "keywords": ""} for i in range(n_items)]
    return lc.run_m1_llm_for_criterion(
        {"id": CID, "type": "exclude", "operator": "llm", "target": "title",
         "what": ["x"], "how": "llm", "label": "x", "threshold": 0.6},
        items, stage="EL", build_messages=_build_messages, model="gemma3",
        trunc_chars=1500, batch_size=batch_size, stats=stats,
        cancel_token=threading.Event(),
    )


# ---------------------------------------------------------------------------
# The call-level counters
# ---------------------------------------------------------------------------

class TestCallStatsAreCountedAtTheCall:

    def test_a_clean_run_counts_its_calls(self, llm, monkeypatch):
        stats = lc.new_llm_call_stats()
        _call(monkeypatch, _answers(), n_items=4, batch_size=2, stats=stats)
        assert stats["calls_made"] == 2
        assert stats["calls_failed"] == 0
        assert stats["batches_failed"] == 0

    def test_a_failed_run_counts_its_failures(self, llm, monkeypatch):
        stats = lc.new_llm_call_stats()
        _call(monkeypatch, _raises(openai.APIConnectionError(
            message="Connection error.", request=_REQ)),
            n_items=4, batch_size=2, stats=stats)
        assert stats["calls_made"] == 2
        assert stats["calls_failed"] == 2
        assert stats["batches_failed"] == 2

    def test_a_call_that_raised_and_was_then_salvaged_leaves_no_record(
            self, llm, monkeypatch):
        """This is why the call-level facts cannot be derived. A batch that
        is refused, halved and then answered ends with every record carrying
        a good verdict — the failure that happened is invisible in the
        evidence map, and only a counter at the call site sees it."""
        state = {"n": 0}

        def _h(items):
            state["n"] += 1
            if len(items) > 2:
                raise RuntimeError("n_ctx exceeded")
            return _answers()(items)

        stats = lc.new_llm_call_stats()
        out = _call(monkeypatch, _h, n_items=4, batch_size=4, stats=stats)
        assert lc.summarize_llm_evidence(out)["failed"] == 0, (
            "no record carries an error — the salvage worked"
        )
        assert stats["calls_failed"] == 1, (
            "but a call did fail, and only the counter knows"
        )
        assert stats["batches_failed"] == 0, "the batch itself did not fail"

    def test_stats_is_optional(self, llm, monkeypatch):
        """Fourteen existing tests call this function without it, and the
        return type must stay a plain mapping for them."""
        out = _call(monkeypatch, _answers(), n_items=2, batch_size=2)
        assert isinstance(out, dict)
        assert out == dict(out)

    def test_a_caller_may_accumulate_across_criteria(self, llm, monkeypatch):
        """The engine runs criterion by criterion; one dict is threaded
        through all of them."""
        stats = lc.new_llm_call_stats()
        _call(monkeypatch, _answers(), n_items=2, batch_size=2, stats=stats)
        _call(monkeypatch, _answers(), n_items=2, batch_size=2, stats=stats)
        assert stats["calls_made"] == 2


# ---------------------------------------------------------------------------
# The derived record-level counts
# ---------------------------------------------------------------------------

class TestRecordCountsAreDerivedFromTheRecords:

    @pytest.mark.parametrize("handler,expected", [
        (_answers("meet"), {"answered": 4, "failed": 0, "no_answer": 0,
                            "decisions_rejected": 0}),
        (_answers("uncertain"), {"answered": 4, "failed": 0, "no_answer": 0,
                                 "decisions_rejected": 0}),
        (_answers("maybe"), {"answered": 0, "failed": 0, "no_answer": 0,
                             "decisions_rejected": 4}),
        (_raises(RuntimeError("boom")), {"answered": 0, "failed": 4,
                                         "no_answer": 0,
                                         "decisions_rejected": 0}),
    ])
    def test_the_four_buckets(self, llm, monkeypatch, handler, expected):
        out = _call(monkeypatch, handler, n_items=4, batch_size=4)
        got = lc.summarize_llm_evidence(out)
        for k, v in expected.items():
            assert got[k] == v, f"{k}: expected {v}, got {got[k]}"

    def test_the_buckets_always_partition_the_records(self, llm, monkeypatch):
        for handler in (_answers("meet"), _answers("maybe"),
                        _raises(RuntimeError("boom"))):
            got = lc.summarize_llm_evidence(
                _call(monkeypatch, handler, n_items=4, batch_size=4))
            assert got["records"] == (got["answered"] + got["no_answer"]
                                      + got["failed"]
                                      + got["decisions_rejected"])

    def test_an_omitted_record_is_no_answer_not_failed(self, llm, monkeypatch):
        def _h(items):
            return _answers()(items[:1])          # answer one, ignore the rest

        got = lc.summarize_llm_evidence(
            _call(monkeypatch, _h, n_items=3, batch_size=3))
        assert got["answered"] == 1
        assert got["no_answer"] == 2
        assert got["failed"] == 0

    def test_an_empty_map_summarises_to_zeroes(self):
        got = lc.summarize_llm_evidence({})
        assert got["records"] == 0 and got["answered"] == 0
        assert lc.summarize_llm_evidence(None)["records"] == 0


# ---------------------------------------------------------------------------
# The engine's run report
# ---------------------------------------------------------------------------

def _setup(mod, stage, rows=4):
    crit = mod.Criterion(
        id=CID, stage=stage, ctype="exclude", enabled=True, operator="llm",
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


def _run_stage(monkeypatch, mod, stage, handler, rows=4):
    monkeypatch.setattr(lc, "_openai_client_for", lambda *_a, **_k: _client(handler))
    parse, report, run = _setup(mod, stage, rows=rows)
    return run(parse, report, model="gemma3", trunc_chars=1500, batch_size=4,
               use_cache=False, cache_in={}, cancel_event=threading.Event())


PARAMS = [(get_el, "EL"), (get_il, "IL")]


class TestTheEngineReturnsARunReport:

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_it_is_the_eighth_element_and_a_mapping(self, llm, monkeypatch,
                                                    getter, stage):
        result = _run_stage(monkeypatch, getter(), stage, _answers())
        assert len(result) == 8
        assert isinstance(result[7], dict)

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_cancelled_stays_the_seventh_element(self, llm, monkeypatch,
                                                 getter, stage):
        """Position matters: `tests/test_cancellation.py` unpacked with
        `*_, cancelled`, which would silently bind the new element."""
        result = _run_stage(monkeypatch, getter(), stage, _answers())
        assert result[6] is False

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_a_working_run_reports_answers(self, llm, monkeypatch, getter,
                                           stage):
        rep = _run_stage(monkeypatch, getter(), stage, _answers())[7]
        assert rep["records"] == 4
        assert rep["answered"] == 4
        assert rep["failed"] == 0
        assert rep["calls_made"] == 1

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_a_wholly_failed_run_reports_no_answers(self, llm, monkeypatch,
                                                    getter, stage):
        rep = _run_stage(monkeypatch, getter(), stage,
                         _raises(openai.APIConnectionError(
                             message="Connection error.", request=_REQ)))[7]
        assert rep["answered"] == 0
        assert rep["failed"] == 4
        assert rep["calls_failed"] == 1

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_a_stage_with_no_criteria_reports_an_empty_run(
            self, llm, monkeypatch, getter, stage):
        mod = getter()
        parse, _report, run = _setup(mod, stage)
        empty = mod.CriteriaLoadReport(criteria=[], warnings=[])
        rep = run(parse, empty, model="gemma3", trunc_chars=1500,
                  batch_size=4, use_cache=False, cache_in={},
                  cancel_event=threading.Event())[7]
        assert rep["records"] == 0
        assert rep["calls_made"] == 0


class TestTheDistinctionTheWaveExistsFor:
    """A model that answered "uncertain" and a model that did not answer
    produce identical counts, identical outcomes, identical survivors and
    identical manifest markers. The report is the only thing that separates
    them."""

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_both_look_identical_everywhere_else(self, llm, monkeypatch,
                                                 getter, stage):
        mod = getter()
        unsure = _run_stage(monkeypatch, mod, stage, _answers("uncertain"))
        broken = _run_stage(monkeypatch, mod, stage,
                            _raises(openai.APIConnectionError(
                                message="Connection error.", request=_REQ)))
        assert unsure[2] == broken[2], "counts agree"
        assert len(unsure[1]) == len(broken[1]), "survivors agree"
        assert unsure[6] == broken[6] is False, "neither is cancelled"
        # EL calls the flagged-survivor outcome PASS_FLAGGED and IL calls it
        # REVIEW — the two stages carry different outcome vocabularies, which
        # is not this wave's business but does have to be spelled correctly.
        flagged = "PASS_FLAGGED" if stage == "EL" else "REVIEW"
        outcomes = {r[f"{stage.lower()}_outcome"] for r in unsure[0]}
        assert outcomes == {flagged} == {
            r[f"{stage.lower()}_outcome"] for r in broken[0]}

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_the_report_separates_them(self, llm, monkeypatch, getter, stage):
        mod = getter()
        unsure = _run_stage(monkeypatch, mod, stage, _answers("uncertain"))[7]
        broken = _run_stage(monkeypatch, mod, stage,
                            _raises(openai.APIConnectionError(
                                message="Connection error.", request=_REQ)))[7]
        assert unsure["answered"] == 4 and unsure["failed"] == 0, (
            "the model was asked and answered: this is a scientific result"
        )
        assert broken["answered"] == 0 and broken["failed"] == 4, (
            "the model was never heard from: this is a misconfiguration"
        )

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_a_model_answering_in_the_wrong_vocabulary_is_a_third_state(
            self, llm, monkeypatch, getter, stage):
        """F-90's case. Not a scientific result and not a dead server."""
        rep = _run_stage(monkeypatch, getter(), stage, _answers("Meet"))[7]
        assert rep["answered"] == 4 and rep["decisions_rejected"] == 0, (
            "after F-90 this is simply a working run"
        )
        rep2 = _run_stage(monkeypatch, getter(), stage, _answers("maybe"))[7]
        assert rep2["answered"] == 0 and rep2["decisions_rejected"] == 4
        assert rep2["failed"] == 0, "the server is fine; the vocabulary is not"


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------

def _seed(tmp_path, name="in.zip"):
    zp = tmp_path / name
    manifest = {"pipeline": {"stages": {}, "history": []}, "sha256": {}}
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("data/current.csv", "local_id,title\nA001,x\n")
    return zp, manifest


def _export(tmp_path, **kw):
    zp, manifest = _seed(tmp_path)
    out = tmp_path / "out.zip"
    with zipfile.ZipFile(zp, "r") as zf_in:
        _write_llm_stage_bundle(
            str(out), zf_in, root="", manifest=manifest, stage="EL",
            reports_dir_rel="reports", cache_rel="cache/EL_cache.jsonl",
            parse_header=["local_id", "title"],
            survivors=[{"local_id": "A001", "title": "x"}],
            full_rows=[{"local_id": "A001", "title": "x"}],
            full_header=["local_id", "title"], skipped=[],
            counts={"OUT": 0, "PASS_FLAGGED": 1}, **kw)
    with zipfile.ZipFile(out, "r") as zf:
        return json.loads(zf.read("manifest.json"))["pipeline"]["history"][-1]


class TestTheManifestCarriesTheReport:

    def test_the_report_rides_on_the_history_entry(self, tmp_path):
        entry = _export(tmp_path, llm_report={"records": 85, "answered": 0,
                                              "failed": 85, "calls_made": 3,
                                              "calls_failed": 3})
        assert entry["llm"]["answered"] == 0
        assert entry["llm"]["failed"] == 85

    def test_it_is_a_sibling_of_counts_not_a_member_of_it(self, tmp_path):
        """`counts` is asserted by exact dict equality in
        tests/test_archived_bundle_manifest.py, and it is the outcome
        histogram — a call-failure count is not an outcome."""
        entry = _export(tmp_path, llm_report={"failed": 85})
        assert entry["counts"] == {"OUT": 0, "PASS_FLAGGED": 1}

    def test_cancelled_is_no_longer_hard_coded(self, tmp_path):
        assert _export(tmp_path, cancelled=True)["cancelled"] is True
        assert _export(tmp_path)["cancelled"] is False

    def test_a_cancelled_run_is_marked_in_the_stage_map_too(self, tmp_path):
        zp, manifest = _seed(tmp_path)
        out = tmp_path / "out.zip"
        with zipfile.ZipFile(zp, "r") as zf_in:
            _write_llm_stage_bundle(
                str(out), zf_in, root="", manifest=manifest, stage="EL",
                reports_dir_rel="reports", cache_rel="cache/EL_cache.jsonl",
                parse_header=["local_id", "title"], survivors=[],
                full_rows=[], full_header=["local_id", "title"], skipped=[],
                counts={}, cancelled=True)
        with zipfile.ZipFile(out, "r") as zf:
            m = json.loads(zf.read("manifest.json"))
        assert m["pipeline"]["stages"]["EL"] == "cancelled", (
            "EH/IH's writer has recorded this since F-02; the LLM writer "
            "said 'done' for a truncated corpus"
        )

    def test_omitting_the_report_leaves_no_misleading_key(self, tmp_path):
        """A stage that did not measure must not claim a zero. EH/IH call a
        different writer, but the same rule applies to any caller that has
        no report to give."""
        assert "llm" not in _export(tmp_path)

    def test_omitting_the_report_leaves_cancelled_at_its_real_value(
            self, tmp_path):
        assert _export(tmp_path)["cancelled"] is False

    def test_a_wholly_failed_run_is_distinguishable_in_the_bundle(
            self, tmp_path):
        """The whole point, at the artefact level."""
        broken = _export(tmp_path, llm_report={"records": 85, "answered": 0,
                                               "failed": 85})
        unsure = _export(tmp_path, llm_report={"records": 85, "answered": 85,
                                               "failed": 0})
        assert broken["counts"] == unsure["counts"]
        assert broken["not_screened"] == unsure["not_screened"] is False
        assert broken["llm"] != unsure["llm"], (
            "a wholly failed run and a wholly uncertain run were identical "
            "in every field the bundle recorded"
        )


# ---------------------------------------------------------------------------
# Every unpack site must move with the tuple
# ---------------------------------------------------------------------------

ENGINES = {"run_el_screen": "plugins/06_el/screen.py",
           "run_il_screen": "plugins/07_il/screen.py"}


def _declared_arity(rel: str, fname: str) -> int:
    """How many elements the function's ``-> Tuple[...]`` annotation names."""
    tree = ast.parse((PROJECT_ROOT / rel).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == fname:
            ann = node.returns
            assert isinstance(ann, ast.Subscript), f"{fname} lost its Tuple[...]"
            sl = ann.slice
            assert isinstance(sl, ast.Tuple), f"{fname}'s annotation is not a tuple"
            return len(sl.elts)
    raise AssertionError(f"{fname} not found in {rel}")


def _unpack_sites():
    """(path, function, names bound) for every tuple-unpacking call of an
    engine across the production tree, the tools and the suite."""
    for root in ("plugins", "tools", "tests"):
        for path in sorted((PROJECT_ROOT / root).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:                              # pragma: no cover
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                    continue
                target, value = node.targets[0], node.value
                if not isinstance(value, ast.Call) or not isinstance(target, ast.Tuple):
                    continue
                fn = value.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
                if name in ENGINES:
                    yield path.relative_to(PROJECT_ROOT).as_posix(), name, target.elts


class TestEveryUnpackSiteMovesWithTheTuple:
    """The engines return a positional tuple, and this wave grew it. There
    are fourteen unpack sites across the tree; the suite catches most of
    them by failing loudly, but two do not appear in any test — the call in
    ``tools/capture_el_il_goldens.py`` that regenerates the goldens, one per
    stage. **Breaking those breaks the ability to re-capture a golden**, and
    nothing would say so until someone needed to. This is the check that
    would have said so."""

    @pytest.mark.parametrize("fname,rel", sorted(ENGINES.items()))
    def test_the_annotation_matches_the_number_of_values_returned(self, fname, rel):
        assert _declared_arity(rel, fname) == 8

    def test_every_production_site_is_found(self):
        """The vacuity guard, and the coverage claim. The finder matches a
        *direct* call by name, so a test that reaches the engine through a
        local alias (``run = mod.run_el_screen``) is invisible to it — those
        fail loudly on their own the moment the arity moves, which is why
        they need no static check. The six sites below do not all have that
        property, and two of them have no test at all."""
        found = {p for p, _f, _e in _unpack_sites()}
        for required in ("plugins/06_el/ui.py", "plugins/06_el/standalone.py",
                         "plugins/07_il/ui.py", "plugins/07_il/standalone.py",
                         "tools/capture_el_il_goldens.py"):
            assert required in found, f"{required} is no longer being checked"

    def test_every_site_binds_the_full_tuple(self):
        sites = list(_unpack_sites())
        assert len(sites) >= 9, (
            f"the finder found only {len(sites)} unpack sites, which means it "
            f"has stopped matching the code rather than that the code changed"
        )
        wrong = []
        for path, fname, elts in sites:
            if any(isinstance(e, ast.Starred) for e in elts):
                continue          # a star-unpack absorbs any arity by design
            if len(elts) != _declared_arity(ENGINES[fname], fname):
                wrong.append(f"{path}: {fname} unpacked into {len(elts)} names")
        assert not wrong, "\n".join(wrong)

    def test_the_golden_capture_tool_is_among_them(self):
        """Named explicitly, because it is the one site with no test of its
        own and the one whose breakage is discovered latest."""
        paths = {p for p, _f, _e in _unpack_sites()}
        assert "tools/capture_el_il_goldens.py" in paths
