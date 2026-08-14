# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_constrained_request.py — wave 14c: the request the model cannot answer
with ``[]``.

F-191's mechanism is specific to a batch of one: the honest reply to a
non-matching record *is* an empty list, and the pipeline reads ``[]`` as
"the model said nothing". F-197 measured the consequence — 17/294 answered
at batch 1 against 241/294 at batch 5, on the same corpus. The fix is a
``response_format`` JSON schema whose ``results`` array carries
``minItems == maxItems == len(batch)``, so an empty reply stops being
expressible **at the server**, not in the prompt.

Measured before designing (FIX_WAVE_14C_BATCH_INVARIANCE.md §2): Ollama
0.32.9 honours the constraint — ``minItems=1`` turned ``[]`` into a verdict
on the same record, twice, and 31/31 previously-omitted pairs filled on the
replayed batches. What a double can assert is the *mechanics*: the schema is
sent, its cardinality tracks the batch actually sent, the fallback fires on
a server that rejects the parameter, and the run records which path it took.

The fallback is F-107's answer, not its bypass: the minimal request stays
reachable, one flip per run, and the run report says which shape ran.
"""
import json
import threading
import types

import httpx
import openai
import pytest

import plugins._common.llm_client as lc

CID = "EC-1"
_REQ = httpx.Request("POST", "http://localhost:11434/v1/chat/completions")


class _FakeResponse:
    def __init__(self, payload):
        msg = type("M", (), {"content": json.dumps(payload)})
        self.choices = [type("C", (), {"message": msg})]


class _Recorder:
    """A client double that records every request's kwargs, replies via a
    handler, and — unlike the eleven legacy doubles — accepts
    ``response_format``."""

    def __init__(self, handler):
        self.calls = []
        outer = self

        class _Completions:
            def create(self, *, model, messages, temperature,
                       response_format=None):
                outer.calls.append({
                    "messages": messages,
                    "response_format": response_format,
                    "items": json.loads(messages[1]["content"])["items"],
                })
                return handler(outer.calls[-1])

        self.chat = type("Chat", (), {"completions": _Completions()})()


def _answers_all(call):
    return _FakeResponse([
        {"a_id": it["a_id"], "decision": "meet", "confidence": 0.9,
         "field": "title", "quote": it["title"], "span": [0, 1]}
        for it in call["items"]
    ])


def _build_messages(criterion, items, trunc_chars):
    return [
        {"role": "system", "content": "score the items"},
        {"role": "user", "content": json.dumps(
            {"criterion": criterion, "items": items}, ensure_ascii=False)},
    ]


def _run(monkeypatch, recorder, n_items=4, batch_size=2, stats=None, log=None):
    monkeypatch.setattr(lc, "_has_openai_key", lambda *_a, **_k: True)
    monkeypatch.setattr(lc, "_openai_client_for", lambda *_a, **_k: recorder)
    monkeypatch.setattr(lc, "time", types.SimpleNamespace(sleep=lambda *_a: None))
    items = [{"a_id": f"A{i:03d}", "title": f"Title {i}", "abstract": "",
              "keywords": ""} for i in range(n_items)]
    return lc.run_m1_llm_for_criterion(
        {"id": CID, "type": "exclude", "operator": "llm", "target": "title",
         "what": ["x"], "how": "llm", "label": "x", "threshold": 0.6},
        items, stage="EL", build_messages=_build_messages, model="gemma3",
        trunc_chars=1500, batch_size=batch_size, stats=stats, log=log,
        cancel_token=threading.Event(),
    )


class TestTheSchemaIsSent:

    def test_every_call_carries_a_json_schema_response_format(self, monkeypatch):
        rec = _Recorder(_answers_all)
        _run(monkeypatch, rec, n_items=4, batch_size=2)
        assert len(rec.calls) == 2
        for c in rec.calls:
            rf = c["response_format"]
            assert rf is not None, "the request went out unconstrained"
            assert rf["type"] == "json_schema"

    def test_cardinality_equals_the_batch_actually_sent(self, monkeypatch):
        """minItems == maxItems == len(batch), including the 3+3+... tail —
        an empty list and a partial reply both stop being expressible."""
        rec = _Recorder(_answers_all)
        _run(monkeypatch, rec, n_items=7, batch_size=3)   # batches of 3, 3, 1
        sizes = []
        for c in rec.calls:
            arr = c["response_format"]["json_schema"]["schema"][
                "properties"]["results"]
            assert arr["minItems"] == arr["maxItems"] == len(c["items"])
            sizes.append(len(c["items"]))
        assert sizes == [3, 3, 1]

    def test_cardinality_follows_an_adaptive_split(self, monkeypatch):
        """The most likely implementation error, named in the design: after
        the 429 ladder halves ``cur_batch``, the schema must demand the
        HALVED count — a schema demanding the original count asks the server
        for objects that cannot exist."""
        state = {"n": 0}

        def _handler(call):
            state["n"] += 1
            if state["n"] == 1:
                raise openai.RateLimitError(
                    "429", response=httpx.Response(429, request=_REQ), body=None)
            return _answers_all(call)

        rec = _Recorder(_handler)
        _run(monkeypatch, rec, n_items=4, batch_size=4)
        first, second = rec.calls[0], rec.calls[1]
        assert len(first["items"]) == 4
        assert len(second["items"]) == 2, "the 429 should have halved the batch"
        arr = second["response_format"]["json_schema"]["schema"][
            "properties"]["results"]
        assert arr["minItems"] == arr["maxItems"] == 2

    def test_the_enums_are_the_parsers_own_vocabularies(self, monkeypatch):
        """One source of truth: the schema's ``decision`` and ``field`` enums
        are DECISION_VOCABULARY and FIELD_VOCABULARY, not a third hand copy
        (F-108/F-109's shape, not repeated here)."""
        rec = _Recorder(_answers_all)
        _run(monkeypatch, rec, n_items=1, batch_size=1)
        item = rec.calls[0]["response_format"]["json_schema"]["schema"][
            "properties"]["results"]["items"]
        assert tuple(item["properties"]["decision"]["enum"]) == \
            lc.DECISION_VOCABULARY
        assert tuple(item["properties"]["field"]["enum"]) == \
            lc.FIELD_VOCABULARY

    def test_the_messages_are_unchanged_by_the_schema(self, monkeypatch):
        """The constraint rides on the request parameter, not the prompt:
        the rendered messages must be byte-identical to what the builder
        produced, or the cache key (which hashes the rendered prompt)
        stops covering what was sent."""
        rec = _Recorder(_answers_all)
        _run(monkeypatch, rec, n_items=1, batch_size=1)
        msgs = rec.calls[0]["messages"]
        assert msgs == _build_messages(
            {"id": CID, "type": "exclude", "operator": "llm", "target": "title",
             "what": ["x"], "how": "llm", "label": "x", "threshold": 0.6},
            rec.calls[0]["items"], 1500)

    def test_the_run_records_the_shape_it_ran(self, monkeypatch):
        stats = lc.new_llm_call_stats()
        _run(monkeypatch, _Recorder(_answers_all), stats=stats)
        assert stats["request_shape"] == "json_schema"


class TestTheFallback:

    @staticmethod
    def _rejecting(handler):
        """A server that 400s any request carrying response_format, with the
        message shape wave 14b measured misclassifying as `oversize`."""
        def _h(call):
            if call["response_format"] is not None:
                raise openai.BadRequestError(
                    "Error code: 400 - unsupported parameter "
                    "'response_format'; only max_tokens allowed",
                    response=httpx.Response(400, request=_REQ), body=None)
            return handler(call)
        return _h

    def test_a_rejecting_server_gets_one_unconstrained_retry(self, monkeypatch):
        stats = lc.new_llm_call_stats()
        rec = _Recorder(self._rejecting(_answers_all))
        out = _run(monkeypatch, rec, n_items=2, batch_size=2, stats=stats)
        assert len(rec.calls) == 2
        assert rec.calls[0]["response_format"] is not None
        assert rec.calls[1]["response_format"] is None
        assert all(ev["used"] is True for ev in out.values()), (
            "the fallback must proceed exactly as today, not fail the batch"
        )
        assert stats["request_shape"] == "unconstrained"

    def test_the_rejection_does_not_enter_the_salvage_ladder(self, monkeypatch):
        """Wave 14b measured the trap this pins: that 400's body contains
        'max_tokens', so ``_classify_llm_error`` calls it ``oversize`` —
        salvageable — and the ladder would halve the batch and step down the
        truncation, spending the same refusal repeatedly. The fallback check
        must run FIRST, and the batch must arrive intact."""
        rec = _Recorder(self._rejecting(_answers_all))
        _run(monkeypatch, rec, n_items=4, batch_size=4)
        assert len(rec.calls[1]["items"]) == 4, "the batch was halved"

    def test_the_fallback_is_sticky_for_the_rest_of_the_run(self, monkeypatch):
        """One flip per run, through the shared stats dict: later criteria
        must not re-probe a server that already said no."""
        stats = lc.new_llm_call_stats()
        rec = _Recorder(self._rejecting(_answers_all))
        _run(monkeypatch, rec, n_items=2, batch_size=1, stats=stats)
        # first batch: rejected once, then unconstrained; second batch:
        # straight to unconstrained — 3 calls, not 4
        assert len(rec.calls) == 3
        assert [c["response_format"] is None for c in rec.calls] == \
            [False, True, True]

    def test_a_rejection_is_counted_and_logged_but_not_terminal(self, monkeypatch):
        stats = lc.new_llm_call_stats()
        lines = []
        _run(monkeypatch, _Recorder(self._rejecting(_answers_all)),
             n_items=2, batch_size=2, stats=stats, log=lines.append)
        assert stats["calls_failed"] == 1
        assert stats["batches_failed"] == 0
        assert any("response_format" in ln for ln in lines), (
            "the flip must be visible in the log, or nobody can explain "
            "why one run was constrained and the next was not"
        )


class TestAbsenceNeverBecomesAVerdict:

    def test_an_omitting_reply_yields_no_used_true_entry_for_the_omitted(
            self, monkeypatch):
        """The IL hazard, held as an invariant (F-191): at IL, ``not_meet``
        on an include-typed criterion is the EXCLUDING verdict, so any code
        path from absence to a verdict would let a two-token reply ask for
        the corpus. No reply that omits a record may produce an evidence
        entry with ``used: True`` for it — under either request shape."""
        def _partial(call):
            return _FakeResponse([
                {"a_id": call["items"][0]["a_id"], "decision": "not_meet",
                 "confidence": 0.9, "field": "title",
                 "quote": call["items"][0]["title"], "span": [0, 1]}
            ])
        out = _run(monkeypatch, _Recorder(_partial), n_items=3, batch_size=3)
        used = {k[0]: v["used"] for k, v in out.items()}
        assert used["A000"] is True
        assert used["A001"] is False and used["A002"] is False
