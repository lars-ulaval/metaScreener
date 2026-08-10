
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_terminal_failure_guard.py — F-134: a failure must not destroy the
answers the same batch already received, and reporting on the work must not
be able to change the work.

The omission back-fill has always been guarded ``if (a_id, cid) not in out``.
The terminal-failure back-fill twelve lines below it was not, so it rewrote
*every* item of the batch as ``used: False, decision: "uncertain",
error: …`` — including ids whose real verdict had been parsed and stored
moments earlier in the same attempt.

This is F-26's shape reached through a different trigger. F-26's fix guards
``_Cancelled`` specifically; anything else raising in the window falls
through to the generic handler exactly as cancellation used to.

**The live route is the caller's own ``progress()`` callback.** The
``sub="batch_done"`` event is emitted *inside the same* ``try``, after both
the parse loop and the omission back-fill have written, so a failure in
progress *reporting* destroys the batch it was reporting on.
``plugins/06_el/ui.py::ELView._run_clicked`` passes a ``progress_evt`` that
marshals through ``self.after``, which raises once the Tk root is gone.

The contract these tests pin:
  - a verdict already in ``out`` is never replaced by an error entry;
  - records with no verdict still get one, so nothing is left unaccounted;
  - a callback that raises cannot mark a batch failed, cannot lose a
    verdict, and cannot stop the run — reporting is not the work.
"""
import json
import threading
import types

import pytest

import plugins._common.llm_client as lc


CID = "EC-1"


class _FakeResponse:
    def __init__(self, payload):
        msg = type("M", (), {"content": json.dumps(payload)})
        self.choices = [type("C", (), {"message": msg})]


class _AnsweringClient:
    """Answers every item of every batch with a usable verdict."""

    def __init__(self):
        self.calls = 0
        outer = self

        class _Completions:
            def create(self, *, model, messages, temperature):
                outer.calls += 1
                items = json.loads(messages[1]["content"])["items"]
                return _FakeResponse([
                    {"a_id": it["a_id"], "decision": "meet", "confidence": 0.9,
                     "field": "title", "quote": it["title"], "span": [0, 1]}
                    for it in items
                ])

        self.chat = type("Chat", (), {"completions": _Completions()})()


def _build_messages(criterion, items, trunc_chars):
    return [
        {"role": "system", "content": "score the items"},
        {"role": "user", "content": json.dumps(
            {"criterion": criterion, "items": items}, ensure_ascii=False)},
    ]


@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setattr(lc, "_has_openai_key", lambda: True)
    monkeypatch.setattr(lc, "time", types.SimpleNamespace(sleep=lambda *_a: None))
    return lc


def _run(monkeypatch, n_items=4, batch_size=4, progress=None, log=None,
         client=None):
    client = client or _AnsweringClient()
    monkeypatch.setattr(lc, "_openai_client_for", lambda: client)
    items = [{"a_id": f"A{i:03d}", "title": f"Title {i}", "abstract": "",
              "keywords": ""} for i in range(n_items)]
    out = lc.run_m1_llm_for_criterion(
        {"id": CID, "type": "exclude", "operator": "llm", "target": "title",
         "what": ["x"], "how": "llm", "label": "x", "threshold": 0.6},
        items, stage="EL", build_messages=_build_messages,
        model="gemma3", trunc_chars=1500, batch_size=batch_size,
        progress=progress, log=log, cancel_token=threading.Event(),
    )
    return out, client


class _RaisesOn:
    """A progress callback that raises the first time it sees ``sub``."""

    def __init__(self, sub, exc=None):
        self.sub = sub
        self.exc = exc or RuntimeError("main thread is not in main loop")
        self.seen = []
        self.fired = False

    def __call__(self, evt):
        self.seen.append(evt.get("sub"))
        if evt.get("sub") == self.sub and not self.fired:
            self.fired = True
            raise self.exc


# ---------------------------------------------------------------------------
# F-134 — the live route
# ---------------------------------------------------------------------------

class TestProgressReportingCannotDestroyEvidence:

    def test_a_raising_progress_callback_does_not_overwrite_verdicts(
            self, llm, monkeypatch):
        """`sub="batch_done"` is emitted after the parse loop and the
        omission back-fill have both written. Today an exception there falls
        into the generic handler, matches no salvage class, and rewrites
        every record of the batch as an error entry — destroying four
        verdicts the API call was already paid for."""
        prog = _RaisesOn("batch_done")
        out, _client = _run(monkeypatch, n_items=4, batch_size=4,
                            progress=prog)
        assert prog.fired, "the test did not exercise the route it targets"
        for i in range(4):
            ev = out[(f"A{i:03d}", CID)]
            assert ev["decision"] == "meet", (
                f"F-134: A{i:03d} came back as a fabricated 'uncertain' with "
                f"error={ev.get('error')!r}. The call succeeded and its "
                f"answer was destroyed by the failure of the code reporting "
                f"on it."
            )
            assert "error" not in ev
            assert ev["used"] is True

    def test_a_raising_progress_callback_does_not_stop_the_run(
            self, llm, monkeypatch):
        """Progress reporting is not the work. A `self.after` that raises
        during Tk shutdown must not truncate the corpus."""
        prog = _RaisesOn("sending")
        out, client = _run(monkeypatch, n_items=6, batch_size=2,
                           progress=prog)
        assert client.calls == 3, "all three batches must still be sent"
        assert len(out) == 6

    @pytest.mark.parametrize("sub", ["sending", "parsing", "batch_done"])
    def test_no_progress_event_can_change_the_outcome(self, llm, monkeypatch,
                                                      sub):
        prog = _RaisesOn(sub)
        out, _client = _run(monkeypatch, n_items=4, batch_size=4,
                            progress=prog)
        assert prog.fired
        assert all(v["decision"] == "meet" for v in out.values())
        assert not any("error" in v for v in out.values())

    def test_a_raising_log_callback_cannot_change_the_outcome(self, llm,
                                                              monkeypatch):
        def _bad_log(_msg):
            raise RuntimeError("main thread is not in main loop")

        out, _client = _run(monkeypatch, n_items=4, batch_size=4,
                            log=_bad_log)
        assert all(v["decision"] == "meet" for v in out.values())


# ---------------------------------------------------------------------------
# F-134 — the guard itself, independent of how the window is reached
# ---------------------------------------------------------------------------

class TestTheTerminalArmDoesNotOverwriteReceivedVerdicts:
    """Exercised through ``_quote_in_text`` rather than ``progress``, so the
    guard is pinned independently of the callback isolation above. Either
    fix alone would leave the other route open."""

    @staticmethod
    def _raise_after(n):
        real = lc._quote_in_text
        state = {"n": 0}

        def _wrapped(quote, text):
            state["n"] += 1
            if state["n"] > n:
                raise ValueError("boom, mid parse loop")
            return real(quote, text)

        return _wrapped

    def test_a_verdict_written_before_the_raise_survives(self, llm,
                                                         monkeypatch):
        monkeypatch.setattr(lc, "_quote_in_text", self._raise_after(1))
        out, _client = _run(monkeypatch, n_items=3, batch_size=3)
        ev = out[("A000", CID)]
        assert ev["decision"] == "meet", (
            "F-134: the terminal back-fill has no `(a_id, cid) not in out` "
            "guard, so it rewrote a verdict that had already been parsed and "
            "stored. The omission back-fill twelve lines above it has always "
            "been guarded."
        )
        assert "error" not in ev

    def test_records_with_no_verdict_still_get_an_entry(self, llm,
                                                        monkeypatch):
        """The guard must not turn into a leak: everything the batch carried
        still needs an entry, or the row loop's `llm_results.get(...)` finds
        nothing and the record is silently unexplained."""
        monkeypatch.setattr(lc, "_quote_in_text", self._raise_after(1))
        out, _client = _run(monkeypatch, n_items=3, batch_size=3)
        assert len(out) == 3
        for i in (1, 2):
            ev = out[(f"A{i:03d}", CID)]
            assert ev["used"] is False
            assert "error" in ev
            assert ev["decision"] == "uncertain"

    def test_the_direction_of_harm_is_still_fail_safe(self, llm, monkeypatch):
        """What survives is a real verdict; what is written is `uncertain`.
        Nothing is ever promoted from uncertain to a decision."""
        monkeypatch.setattr(lc, "_quote_in_text", self._raise_after(2))
        out, _client = _run(monkeypatch, n_items=4, batch_size=4)
        decided = [k for k, v in out.items() if v["used"] is True]
        assert len(decided) == 2
        assert all(out[k]["decision"] == "meet" for k in decided)
