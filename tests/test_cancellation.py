
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_cancellation.py — F-02 and F-26: a cancelled run must not pass for a
complete one.

F-02. Every stage's row loop is ``if cancel_event.is_set(): break``. It
exits mid-corpus and returns the rows processed so far as though that were
the whole corpus. Nothing in the return value, the counts, the reports or
the manifest says the run stopped early, so an exported bundle from a
cancelled run is indistinguishable from a complete run over a smaller
corpus — and the smaller corpus is exactly what the next stage will screen.

F-26. ``_check_cancel()`` inside ``run_m1_llm_for_criterion`` raised
straight past ``return out``, discarding every LLM result already paid for
in earlier batches. Worse, the check that runs after a successful API call
sat *inside* the retry ``try``, so the generic handler caught it and marked
the whole batch ``uncertain`` with ``error="Cancelled"`` — turning results
that had been paid for and received into fabricated non-answers.

The contract these tests pin:
  - engines return a ``cancelled`` flag alongside their results;
  - the flag is False for a complete run and True for an interrupted one;
  - export is refused for a cancelled run;
  - if a cancelled run is written anyway, the manifest records it;
  - LLM results already received survive cancellation.
"""
import json
import threading
import zipfile
from pathlib import Path

import pytest

from conftest import get_el, get_il

from plugins._common.bundle import (
    BundleInfo,
    _export_block_reason,
    _export_next_bundle_zip,
)
from plugins._common.parser import CriteriaLoadReport, Criterion, ParseReport
from plugins._common.runner import run_screen


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _rows(n):
    return [{"local_id": f"A{i:03d}", "title": f"Title {i}",
             "abstract": f"Abstract {i} about virtual reality.",
             "keywords": "vr; nursing"} for i in range(n)]


def _parse(n):
    return ParseReport(header=["local_id", "title", "abstract", "keywords"],
                       rows=_rows(n), skipped=[])


def _crit(cid="EC-1", operator="contains", targets=("title",), what=("Title",)):
    return Criterion(
        stage="EH", cid=cid, ctype="exclude", scope="", label=cid,
        operator=operator, targets=list(targets), what_raw=";".join(what),
        what_list=list(what), threshold=None, enabled=True, source_text=cid,
    )


class _TripEvent:
    """A cancel event that reports 'not set' for the first ``after`` checks
    and 'set' from then on — i.e. a cancel that lands mid-corpus."""

    def __init__(self, after):
        self.after = after
        self.checks = 0

    def is_set(self):
        self.checks += 1
        return self.checks > self.after

    def set(self):
        self.after = -1


# ---------------------------------------------------------------------------
# F-02 — the engines must report that they stopped early
# ---------------------------------------------------------------------------

class TestRunnerReportsCancellation:
    """EH/IH share plugins/_common/runner.run_screen."""

    @pytest.mark.parametrize("stage", ["EH", "IH"])
    def test_complete_run_is_not_flagged(self, stage):
        report = CriteriaLoadReport(criteria=[_crit()], warnings=[])
        full, surv, counts, _imp, _ev, cancelled = run_screen(
            _parse(20), report, threading.Event(), None, stage=stage)
        assert cancelled is False
        assert len(full) == 20

    @pytest.mark.parametrize("stage", ["EH", "IH"])
    def test_cancelled_run_is_flagged_and_partial(self, stage):
        report = CriteriaLoadReport(criteria=[_crit()], warnings=[])
        full, surv, counts, _imp, _ev, cancelled = run_screen(
            _parse(20), report, _TripEvent(after=5), None, stage=stage)
        assert cancelled is True, (
            "F-02: run_screen returned no indication that it stopped early. "
            "The caller cannot distinguish this from a complete run over a "
            "5-record corpus."
        )
        assert len(full) < 20

    @pytest.mark.parametrize("stage", ["EH", "IH"])
    def test_cancelled_zero_criteria_run_is_flagged(self, stage):
        """The zero-criteria branch has its own row loop and its own
        ``break``; it needs the same flag."""
        report = CriteriaLoadReport(criteria=[], warnings=[])
        full, _surv, _counts, _imp, _ev, cancelled = run_screen(
            _parse(20), report, _TripEvent(after=5), None, stage=stage)
        assert cancelled is True
        assert len(full) < 20


class TestELILReportCancellation:
    """EL/IL keep their own Criterion / ParseReport dataclasses (see the
    module docstrings in 06_el/screen.py — deliberately not _common's, so
    the goldens stay valid), so these build stage-local objects."""

    @staticmethod
    def _setup(mod, stage):
        crit = mod.Criterion(
            id=f"{stage[0]}C-1", stage=stage, ctype="exclude", enabled=True,
            operator="contains", targets=["title"], what_raw="Title",
            what_list=["Title"], threshold=0.6, source_text="x", label="x",
        )
        parse = mod.ParseReport(
            header=["local_id", "title", "abstract", "keywords"],
            rows=_rows(10), skipped=[])
        report = mod.CriteriaLoadReport(criteria=[crit], warnings=[])
        run = mod.run_el_screen if stage == "EL" else mod.run_il_screen
        return parse, report, run

    @pytest.mark.parametrize("getter,stage", [(get_el, "EL"), (get_il, "IL")],
                             ids=["el", "il"])
    def test_complete_run_is_not_flagged(self, getter, stage):
        mod = getter()
        parse, report, run = self._setup(mod, stage)
        *_, cancelled = run(
            parse, report, model="gpt-4o-mini", trunc_chars=1500,
            batch_size=5, use_cache=False, cache_in={},
            cancel_event=threading.Event(),
        )
        assert cancelled is False

    @pytest.mark.parametrize("getter,stage", [(get_el, "EL"), (get_il, "IL")],
                             ids=["el", "il"])
    def test_cancelled_run_is_flagged(self, getter, stage):
        mod = getter()
        parse, report, run = self._setup(mod, stage)
        full_rows, _surv, _counts, _imp, _ev, _cache, cancelled = run(
            parse, report, model="gpt-4o-mini", trunc_chars=1500,
            batch_size=5, use_cache=False, cache_in={},
            cancel_event=_TripEvent(after=0),
        )
        assert cancelled is True
        assert len(full_rows) < 10


# ---------------------------------------------------------------------------
# F-02 — export must be refused for a cancelled run
# ---------------------------------------------------------------------------

class TestExportGate:
    """One rule, in one place, used by all four stage UIs."""

    def test_complete_run_with_rows_may_export(self):
        assert _export_block_reason(has_rows=True, cancelled=False) is None

    def test_cancelled_run_is_refused(self):
        reason = _export_block_reason(has_rows=True, cancelled=True)
        assert reason is not None
        assert "cancel" in reason.lower()

    def test_no_rows_is_refused(self):
        assert _export_block_reason(has_rows=False, cancelled=False) is not None

    def test_cancelled_takes_precedence_over_no_rows(self):
        """A cancelled run with nothing to show should still say it was
        cancelled — 'run the stage first' would be misleading."""
        reason = _export_block_reason(has_rows=False, cancelled=True)
        assert "cancel" in reason.lower()


# ---------------------------------------------------------------------------
# F-02 — if a cancelled run is written anyway, the bundle must say so
# ---------------------------------------------------------------------------

def _seed_bundle(tmp_path):
    zp = tmp_path / "in.zip"
    manifest = {"pipeline": {"stages": {}, "history": []}, "sha256": {}}
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("data/current.csv", "local_id,title\nA001,x\n")
    return BundleInfo(zip_path=str(zp), root="", manifest=manifest,
                      members=["manifest.json", "data/current.csv"])


def _history_of(zip_path):
    with zipfile.ZipFile(zip_path, "r") as zf:
        return json.loads(zf.read("manifest.json"))["pipeline"]["history"]


class TestManifestRecordsCancellation:

    def test_complete_run_history_entry_is_not_cancelled(self, tmp_path):
        b = _seed_bundle(tmp_path)
        out = tmp_path / "out.zip"
        _export_next_bundle_zip(
            str(out), b, "data/current.csv", "criteria/c.csv", None,
            ["local_id", "title"], [{"local_id": "A001", "title": "x"}],
            [{"local_id": "A001", "title": "x"}], [], {"OUT": 0},
            stage="EH",
        )
        assert _history_of(out)[-1]["cancelled"] is False

    def test_cancelled_run_history_entry_is_marked(self, tmp_path):
        b = _seed_bundle(tmp_path)
        out = tmp_path / "out.zip"
        _export_next_bundle_zip(
            str(out), b, "data/current.csv", "criteria/c.csv", None,
            ["local_id", "title"], [{"local_id": "A001", "title": "x"}],
            [{"local_id": "A001", "title": "x"}], [], {"OUT": 0},
            stage="EH", cancelled=True,
        )
        entry = _history_of(out)[-1]
        assert entry["cancelled"] is True, (
            "F-02: a bundle written from a cancelled run carries no record "
            "that the corpus was truncated. A reviewer reproducing the "
            "pipeline would read the survivor count as the whole corpus."
        )


# ---------------------------------------------------------------------------
# F-26 — LLM results already paid for must survive cancellation
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        msg = type("M", (), {"content": json.dumps(payload)})
        self.choices = [type("C", (), {"message": msg})]


class _FakeClient:
    """Stands in for the OpenAI client. Records how many batches were sent
    and trips the cancel token after ``cancel_after_calls`` of them."""

    def __init__(self, token, cancel_after_calls):
        self.calls = 0
        self.token = token
        self.cancel_after_calls = cancel_after_calls
        outer = self

        class _Completions:
            def create(self, *, model, messages, temperature):
                outer.calls += 1
                payload = json.loads(messages[1]["content"])
                items = payload["items"]
                if outer.calls >= outer.cancel_after_calls:
                    outer.token.set()
                return _FakeResponse([
                    {"a_id": it["a_id"], "decision": "meet", "confidence": 0.9,
                     "field": "title", "quote": it["title"], "span": [0, 1]}
                    for it in items
                ])

        self.chat = type("Chat", (), {"completions": _Completions()})()


@pytest.fixture
def llm(monkeypatch):
    import plugins._common.llm_client as lc
    monkeypatch.setattr(lc, "_has_openai_key", lambda: True)
    return lc


def _build_messages(criterion, items, trunc_chars):
    """Same two-message shape as the real per-stage prompt builders: a
    system string and a user string holding JSON with 'criterion' and
    'items'. _FakeClient reads the item list back out of it."""
    return [
        {"role": "system", "content": "score the items"},
        {"role": "user", "content": json.dumps(
            {"criterion": criterion, "items": items}, ensure_ascii=False)},
    ]


def _run_llm(lc, monkeypatch, token, cancel_after_calls, n_items, batch_size):
    client = _FakeClient(token, cancel_after_calls)
    monkeypatch.setattr(lc, "_openai_client_for", lambda: client)
    criterion = {"id": "EC-1", "type": "exclude", "operator": "llm",
                 "target": "title", "what": ["x"], "how": "llm",
                 "label": "x", "threshold": 0.6}
    items = [{"a_id": f"A{i:03d}", "title": f"Title {i}", "abstract": "",
              "keywords": ""} for i in range(n_items)]
    out = lc.run_m1_llm_for_criterion(
        criterion, items, stage="EL",
        build_messages=_build_messages,
        model="gpt-4o-mini", trunc_chars=1500, batch_size=batch_size,
        cancel_token=token,
    )
    return out, client


class TestLLMCancellationKeepsPaidResults:

    def test_earlier_batches_survive(self, llm, monkeypatch):
        """Cancel after the second batch. The first two batches were paid
        for and received; they must come back, not be discarded by an
        exception unwinding past ``return out``."""
        token = threading.Event()
        out, client = _run_llm(llm, monkeypatch, token,
                               cancel_after_calls=2, n_items=20, batch_size=5)
        assert client.calls == 2, "should have stopped sending after cancel"
        assert len(out) == 10, (
            f"F-26: expected the 10 records from the two completed batches, "
            f"got {len(out)}. Results already paid for were discarded."
        )
        assert all(v["decision"] == "meet" for v in out.values())

    def test_cancel_does_not_poison_the_in_flight_batch(self, llm, monkeypatch):
        """The post-call cancel check used to sit inside the retry ``try``,
        so the generic handler swallowed it and wrote the whole batch out as
        ``uncertain`` with ``error='Cancelled'``. A received answer must
        never be replaced by a fabricated non-answer."""
        token = threading.Event()
        out, _client = _run_llm(llm, monkeypatch, token,
                                cancel_after_calls=1, n_items=10, batch_size=5)
        assert out, "the completed batch must not be dropped"
        for key, val in out.items():
            assert val["decision"] != "uncertain", (
                f"F-26: {key} came back as a fabricated 'uncertain' after "
                f"cancellation, with error={val.get('error')!r}. The API "
                f"call succeeded and its answer was discarded."
            )
            assert "error" not in val

    def test_cancel_before_first_batch_returns_empty_not_raises(self, llm,
                                                               monkeypatch):
        token = threading.Event()
        token.set()
        out, client = _run_llm(llm, monkeypatch, token,
                               cancel_after_calls=99, n_items=10, batch_size=5)
        assert out == {}
        assert client.calls == 0
