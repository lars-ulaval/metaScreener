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

    def test_a_generic_400_is_not_mistaken_for_a_rejection(self, monkeypatch):
        """Found by the mutation battery: widening the predicate to ANY 400
        survived the suite. A malformed-request 400 that never names
        ``response_format`` must be terminal for the batch, exactly as
        before this wave — flipping to unconstrained on it would burn a
        retry on a request the server will never accept and record a false
        ``request_shape`` for the run."""
        def _h(call):
            raise openai.BadRequestError(
                "Error code: 400 - the request payload is malformed",
                response=httpx.Response(400, request=_REQ), body=None)
        stats = lc.new_llm_call_stats()
        rec = _Recorder(_h)
        out = _run(monkeypatch, rec, n_items=2, batch_size=2, stats=stats)
        assert len(rec.calls) == 1, "a generic 400 must not earn a retry"
        assert stats["request_shape"] == "json_schema", (
            "the run did not fall back; its record must not say it did"
        )
        assert all("error" in ev for ev in out.values()), (
            "terminal for the batch, as before this wave"
        )

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
        entry with ``used: True`` for it — under either request shape.

        Updated by F-197's re-ask in the same wave: a record the model
        answers on the re-ask is genuinely answered, so the invariant is
        asserted on the record the model addresses in NO reply — A002
        below, which both the first call and the re-ask omit."""
        def _first_only(call):
            return _FakeResponse([
                {"a_id": call["items"][0]["a_id"], "decision": "not_meet",
                 "confidence": 0.9, "field": "title",
                 "quote": call["items"][0]["title"], "span": [0, 1]}
            ])
        out = _run(monkeypatch, _Recorder(_first_only), n_items=3, batch_size=3)
        used = {k[0]: v["used"] for k, v in out.items()}
        assert used["A000"] is True
        assert used["A001"] is True, "answered on the re-ask — a real verdict"
        assert used["A002"] is False, (
            "omitted by the first reply AND by the re-ask: no code path may "
            "turn that absence into a verdict"
        )
        assert out[("A002", CID)]["decision"] == "uncertain"


class TestOmissionIsReAskedOnce:
    """F-197's fallback for partial omission (design §3.2): a reply short of
    the batch gets ONE re-ask of exactly the omitted subset; what is still
    missing after that lands in a named residue counter instead of a silent
    back-fill. F-191's "retry is measured worthless" does not transfer here —
    that was an unconstrained request re-sent verbatim; a re-ask of the
    omitted subset is a different item list, hence a different request. The
    replay measured the constrained re-ask filling 31/31 omitted pairs."""

    @staticmethod
    def _omit_after_first(call):
        return _FakeResponse([
            {"a_id": it["a_id"], "decision": "not_meet", "confidence": 0.9,
             "field": "title", "quote": it["title"], "span": [0, 1]}
            for it in call["items"][:1]
        ])

    def test_the_reask_carries_exactly_the_omitted_records(self, monkeypatch):
        rec = _Recorder(self._omit_after_first)
        _run(monkeypatch, rec, n_items=3, batch_size=3)
        assert len(rec.calls) == 2
        assert [it["a_id"] for it in rec.calls[0]["items"]] ==             ["A000", "A001", "A002"]
        assert [it["a_id"] for it in rec.calls[1]["items"]] ==             ["A001", "A002"], "the re-ask must carry the omitted subset only"

    def test_the_reask_is_constrained_to_its_own_cardinality(self, monkeypatch):
        rec = _Recorder(self._omit_after_first)
        _run(monkeypatch, rec, n_items=3, batch_size=3)
        arr = rec.calls[1]["response_format"]["json_schema"]["schema"][
            "properties"]["results"]
        assert arr["minItems"] == arr["maxItems"] == 2

    def test_a_full_reply_triggers_no_reask(self, monkeypatch):
        rec = _Recorder(_answers_all)
        _run(monkeypatch, rec, n_items=3, batch_size=3)
        assert len(rec.calls) == 1

    def test_the_reask_happens_once_and_the_residue_is_counted(self, monkeypatch):
        """A still-omitting re-ask does not recurse. The residue reaches the
        run report under its own name — a record that survived a re-ask
        unanswered is a stronger fact than a plain no_answer, and the silent
        back-fill is what wave 14b existed to end."""
        stats = lc.new_llm_call_stats()
        rec = _Recorder(self._omit_after_first)
        out = _run(monkeypatch, rec, n_items=3, batch_size=3, stats=stats)
        assert len(rec.calls) == 2, "exactly one re-ask, no recursion"
        assert stats["reasks_made"] == 1
        assert stats["no_answer_after_reask"] == 1
        rep = lc.summarize_llm_evidence(out)
        assert rep["answered"] == 2 and rep["no_answer"] == 1

    def test_an_answered_batch_counts_no_residue(self, monkeypatch):
        stats = lc.new_llm_call_stats()
        _run(monkeypatch, _Recorder(_answers_all), n_items=3, batch_size=3,
             stats=stats)
        assert stats["reasks_made"] == 0
        assert stats["no_answer_after_reask"] == 0

    def test_an_empty_reply_on_the_unconstrained_path_is_reasked_too(
            self, monkeypatch):
        """The detection is shape-independent by design (§3.2): on the
        F-107 fallback path the constrained guarantee is gone and ``[]``
        is expressible again, so the re-ask is the only line left."""
        state = {"n": 0}

        def _h(call):
            state["n"] += 1
            if call["response_format"] is not None:
                raise openai.BadRequestError(
                    "unsupported parameter 'response_format'",
                    response=httpx.Response(400, request=_REQ), body=None)
            if state["n"] == 2:            # first unconstrained attempt
                return _FakeResponse([])   # the F-191 reply
            return _answers_all(call)      # the re-ask answers
        stats = lc.new_llm_call_stats()
        rec = _Recorder(_h)
        out = _run(monkeypatch, rec, n_items=2, batch_size=2, stats=stats)
        assert stats["request_shape"] == "unconstrained"
        assert stats["reasks_made"] == 1
        assert all(ev["used"] is True for ev in out.values())

    def test_the_reask_counts_in_calls_made(self, monkeypatch):
        stats = lc.new_llm_call_stats()
        _run(monkeypatch, _Recorder(self._omit_after_first), n_items=3,
             batch_size=3, stats=stats)
        assert stats["calls_made"] == 2

    def test_the_f194_tally_records_the_reply_that_left_the_residue(
            self, monkeypatch):
        """After a re-ask, the record that is still unanswered was left so by
        the RE-ASK's reply — that is the reply a diagnostician needs, not the
        first one, whose omissions were repaired."""
        stats = lc.new_llm_call_stats()
        _run(monkeypatch, _Recorder(self._omit_after_first), n_items=3,
             batch_size=3, stats=stats)
        assert stats["no_answer_replies"], "the residue left no reply behind"
        (entry,) = stats["no_answer_replies"].values()
        assert entry["count"] == 1, (
            "one record survived the re-ask unanswered; the tally must "
            "count that record against the re-ask's reply"
        )
