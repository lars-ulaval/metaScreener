
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_cross_batch_substitution.py — F-86: a batch's answer must not be filed
against a record that batch did not contain.

``run_m1_llm_for_criterion`` built its acceptance map, ``idx_map``, from the
whole ``items`` list *before* batching. The guard on a returned answer was
therefore ``a_id in idx_map`` — "is this one of the records in the run?" —
when the only sound question is "is this one of the records in *this call's
prompt*?". The quote was then validated against the named record's real
text, so ``valid_quote`` came back True and the evidence gate in
``run_el_screen`` accepted it. Nothing was malformed: the response parsed,
the quote was genuine. It simply belonged to a different record.

Two routes, tested separately because they fail for different reasons:

  forward   a batch names a record that has not been processed yet. The
            fabricated verdict lands in ``out`` first, and the back-fill
            loop — which *is* guarded with ``if (a_id, cid) not in out`` —
            then declines to correct it when the record's own batch omits
            it. Needs an omission downstream.

  backward  a later batch names an earlier batch's record. The parse-loop
            write ``out[(a_id, cid)] = {...}`` was unguarded, so it
            destroyed a verdict that had already been received correctly.
            Needs no omission at all.

Both fire at ``batch_size = 1``, because the acceptance map was built
independently of batching; that is pinned below rather than argued.

The persistence half matters as much as the run: the stage write-back keys
the cache by (criterion, record), so a verdict fabricated for record X is
written under *X's own legitimate key* and replays on every later run as an
ordinary cache hit. Two tests cover that the poisoned entry never reaches
the cache and that the exclusion does not come back.

Finally, the guard must reject foreign ids and only foreign ids: a model
answering about a record that *is* in the batch — in any order, with an
unknown id mixed in — must work exactly as before.
"""
import json
import threading

import pytest

from conftest import get_el

import plugins._common.llm_client as lc


CID = "EC-1"

CRITERION = {"id": CID, "type": "exclude", "operator": "llm",
             "target": "title", "what": ["vr"], "how": "llm",
             "label": "uses VR", "threshold": 0.6}


def _title(i: int) -> str:
    return f"Record {i} on virtual reality rehabilitation"


def _items(n: int):
    return [{"a_id": f"A{i:03d}", "title": _title(i), "abstract": f"Abstract {i}.",
             "keywords": "vr"} for i in range(n)]


def _answer(a_id: str, decision: str, quote: str, confidence: float = 0.95):
    """One well-formed response object. The quote is a genuine substring of
    the named record's title — that is the whole point of the finding."""
    return {"a_id": a_id, "decision": decision, "confidence": confidence,
            "field": "title", "quote": quote, "span": [0, len(quote)]}


class _FakeResponse:
    def __init__(self, payload):
        msg = type("M", (), {"content": json.dumps(payload)})
        self.choices = [type("C", (), {"message": msg})]


class _ScriptedClient:
    """Stands in for the OpenAI client and returns a scripted payload per
    call, so a specific batch can be made to name a specific foreign id.

    ``script`` is a list of callables taking the a_ids the call was actually
    sent and returning the response payload. Recording ``sent`` lets a test
    assert that the batching it thinks it arranged is the batching that
    happened.
    """

    def __init__(self, script):
        self.script = list(script)
        self.sent = []
        outer = self

        class _Completions:
            def create(self, *, model, messages, temperature, response_format=None):
                payload = json.loads(messages[1]["content"])
                a_ids = [it["a_id"] for it in payload["items"]]
                outer.sent.append(a_ids)
                idx = len(outer.sent) - 1
                if idx >= len(outer.script):
                    raise AssertionError(
                        f"unscripted call {idx + 1} for {a_ids}")
                return _FakeResponse(outer.script[idx](a_ids))

        self.chat = type("Chat", (), {"completions": _Completions()})()


def _build_messages(criterion, items, trunc_chars):
    """The same two-message shape as the real per-stage prompt builders."""
    return [
        {"role": "system", "content": "score the items"},
        {"role": "user", "content": json.dumps(
            {"criterion": criterion, "items": items}, ensure_ascii=False)},
    ]


@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setattr(lc, "_has_openai_key", lambda *_a, **_k: True)
    return lc


def _run(monkeypatch, script, *, n_items=6, batch_size=3):
    client = _ScriptedClient(script)
    monkeypatch.setattr(lc, "_openai_client_for", lambda *_a, **_k: client)
    out = lc.run_m1_llm_for_criterion(
        CRITERION, _items(n_items), stage="EL",
        build_messages=_build_messages,
        model="gpt-4o-mini", trunc_chars=1500, batch_size=batch_size,
        cancel_token=threading.Event(),
    )
    return out, client


# ---------------------------------------------------------------------------
# the two substitution routes
# ---------------------------------------------------------------------------

class TestForwardSubstitution:
    """A batch names a record that has not been reached yet."""

    def test_verdict_for_a_record_not_in_the_prompt_is_refused(self, llm,
                                                               monkeypatch):
        def call1(a_ids):
            # Batch 1 answers its own three records honestly, then adds a
            # fourth object for A004 — which is in batch 2, not this prompt.
            # The quote is A004's real title, so it validates.
            return ([_answer(a, "not_meet", _title(int(a[1:]))) for a in a_ids]
                    + [_answer("A004", "meet", _title(4))])

        def call2(a_ids):
            # A004's own batch omits it, so the guarded back-fill sees an
            # entry already present and declines to correct the fabrication.
            return [_answer(a, "not_meet", _title(int(a[1:])))
                    for a in a_ids if a != "A004"]

        def call3(a_ids):
            # Wave 14c: batch 2's omission of A004 now triggers ONE re-ask
            # of exactly [A004]. Scripted to omit again, so the record ends
            # unanswered and the assertions below keep testing what they
            # always tested: the FABRICATED verdict must not stand. That the
            # record now gets its own honest chance first is the fix working,
            # not the defence weakening.
            assert a_ids == ["A004"]
            return []

        out, client = _run(monkeypatch, [call1, call2, call3])

        assert client.sent == [["A000", "A001", "A002"],
                               ["A003", "A004", "A005"],
                               ["A004"]]

        ev = out[("A004", CID)]
        assert ev["used"] is False, (
            "F-86: A004's verdict was produced by a call whose prompt did "
            f"not contain A004. Got {ev!r}. The quote validated because it "
            "was checked against A004's own text, which the acceptance map "
            "made reachable from any batch."
        )
        assert ev["decision"] == "uncertain"
        assert ev["valid_quote"] is False

    def test_the_batch_that_did_answer_is_unharmed(self, llm, monkeypatch):
        """Refusing the foreign id must not cost the honest answers that
        arrived in the same response."""
        def call1(a_ids):
            return ([_answer(a, "not_meet", _title(int(a[1:]))) for a in a_ids]
                    + [_answer("A004", "meet", _title(4))])

        def call2(a_ids):
            return [_answer(a, "not_meet", _title(int(a[1:]))) for a in a_ids]

        out, _client = _run(monkeypatch, [call1, call2])
        for i in (0, 1, 2):
            ev = out[(f"A{i:03d}", CID)]
            assert ev["used"] is True
            assert ev["decision"] == "not_meet"
            assert ev["valid_quote"] is True


class TestBackwardSubstitution:
    """A later batch names an earlier batch's record. Unconditional: no
    omission anywhere is required."""

    def test_a_received_verdict_is_not_destroyed_by_a_later_batch(self, llm,
                                                                  monkeypatch):
        def call1(a_ids):
            return [_answer(a, "not_meet", _title(int(a[1:]))) for a in a_ids]

        def call2(a_ids):
            # Batch 2 answers its own records correctly and additionally
            # claims A000 — already answered "not_meet" by batch 1 — meets
            # the exclusion criterion. The quote is A000's real title.
            return ([_answer(a, "not_meet", _title(int(a[1:]))) for a in a_ids]
                    + [_answer("A000", "meet", _title(0))])

        out, _client = _run(monkeypatch, [call1, call2])

        ev = out[("A000", CID)]
        assert ev["decision"] == "not_meet", (
            "F-86 backward route: batch 2 named A000, a record from batch 1, "
            f"and the unguarded parse-loop write replaced A000's correct "
            f"verdict with {ev['decision']!r}. No omission was needed."
        )
        assert ev["used"] is True
        assert ev["valid_quote"] is True


class TestFiresAtBatchSizeOne:
    """The acceptance map was built independently of batching, so making
    every batch a single record does not help."""

    def test_forward_route_at_batch_size_one(self, llm, monkeypatch):
        def call1(a_ids):
            assert a_ids == ["A000"]
            return [_answer("A000", "not_meet", _title(0)),
                    _answer("A001", "meet", _title(1))]

        def call2(a_ids):
            assert a_ids == ["A001"]
            return []

        def call3(a_ids):
            # Wave 14c's re-ask of the omitted record; omits again — see
            # the forward-substitution test above.
            assert a_ids == ["A001"]
            return []

        out, client = _run(monkeypatch, [call1, call2, call3],
                           n_items=2, batch_size=1)

        assert client.sent == [["A000"], ["A001"], ["A001"]]
        ev = out[("A001", CID)]
        assert ev["used"] is False, (
            "F-86 at batch_size=1: the single-record call for A000 filed a "
            f"verdict against A001 and it was accepted ({ev!r}). Batching is "
            "not what admits the foreign id; the whole-corpus acceptance map "
            "is."
        )
        assert ev["decision"] == "uncertain"

    def test_backward_route_at_batch_size_one(self, llm, monkeypatch):
        def call1(a_ids):
            return [_answer("A000", "not_meet", _title(0))]

        def call2(a_ids):
            return [_answer("A001", "not_meet", _title(1)),
                    _answer("A000", "meet", _title(0))]

        out, _client = _run(monkeypatch, [call1, call2],
                            n_items=2, batch_size=1)
        assert out[("A000", CID)]["decision"] == "not_meet"


# ---------------------------------------------------------------------------
# the guard must reject foreign ids and nothing else
# ---------------------------------------------------------------------------

class TestLegitimateAnswersStillWork:

    def test_every_id_in_the_batch_is_accepted(self, llm, monkeypatch):
        def honest(a_ids):
            return [_answer(a, "meet", _title(int(a[1:]))) for a in a_ids]

        out, _client = _run(monkeypatch, [honest, honest])
        assert len(out) == 6
        for i in range(6):
            ev = out[(f"A{i:03d}", CID)]
            assert ev["used"] is True
            assert ev["decision"] == "meet"
            assert ev["valid_quote"] is True
            assert ev["confidence"] == pytest.approx(0.95)
            assert ev["field"] == "title"

    def test_answers_returned_out_of_order_are_accepted(self, llm, monkeypatch):
        """Nothing requires the model to answer in prompt order, and the
        guard must not start requiring it."""
        def reversed_order(a_ids):
            return [_answer(a, "not_meet", _title(int(a[1:])))
                    for a in reversed(a_ids)]

        out, _client = _run(monkeypatch, [reversed_order, reversed_order])
        assert len(out) == 6
        assert all(out[(f"A{i:03d}", CID)]["used"] is True for i in range(6))

    def test_an_id_belonging_to_no_record_is_still_ignored(self, llm,
                                                           monkeypatch):
        """Pre-existing behaviour, retained: an invented id is dropped, and
        dropping it costs nothing else in the response."""
        def with_junk(a_ids):
            return ([_answer(a, "not_meet", _title(int(a[1:]))) for a in a_ids]
                    + [_answer("NOT-A-RECORD", "meet", "anything")])

        out, _client = _run(monkeypatch, [with_junk, with_junk])
        assert ("NOT-A-RECORD", CID) not in out
        assert len(out) == 6
        assert all(out[(f"A{i:03d}", CID)]["used"] is True for i in range(6))

    def test_a_blank_id_is_ignored(self, llm, monkeypatch):
        def with_blank(a_ids):
            return ([_answer(a, "not_meet", _title(int(a[1:]))) for a in a_ids]
                    + [_answer("", "meet", "anything")])

        out, _client = _run(monkeypatch, [with_blank, with_blank])
        assert ("", CID) not in out
        assert len(out) == 6

    def test_the_first_answer_for_an_id_wins(self, llm, monkeypatch):
        """Guarding the parse-loop write the way the back-fill is guarded
        makes a repeated object for the same id a no-op rather than an
        overwrite. Pinned so the choice is deliberate and visible: a model
        that contradicts itself inside one response cannot have the second,
        contradicting object silently win."""
        def contradicting(a_ids):
            first = [_answer(a, "not_meet", _title(int(a[1:]))) for a in a_ids]
            return first + [_answer(a_ids[0], "meet", _title(int(a_ids[0][1:])))]

        out, _client = _run(monkeypatch, [contradicting, contradicting])
        assert out[("A000", CID)]["decision"] == "not_meet"

    def test_omitted_records_still_get_the_unused_back_fill(self, llm,
                                                            monkeypatch):
        """The back-fill is the mechanism that turns a non-answer into a
        flag rather than a silent gap; the fix must leave it working."""
        def drops_one(a_ids):
            return [_answer(a, "not_meet", _title(int(a[1:])))
                    for a in a_ids[:-1]]

        out, _client = _run(monkeypatch, [drops_one, drops_one])
        assert len(out) == 6
        assert out[("A002", CID)]["used"] is False
        assert out[("A002", CID)]["decision"] == "uncertain"
        assert out[("A005", CID)]["used"] is False


# ---------------------------------------------------------------------------
# the persistence half — the fabricated verdict must not reach the cache
# ---------------------------------------------------------------------------

def _el_criterion(mod):
    return mod.Criterion(
        id=CID, stage="EL", ctype="exclude", enabled=True, operator="llm",
        targets=["title"], what_raw="vr", what_list=["vr"], threshold=0.6,
        source_text="uses VR", label="uses VR",
    )


def _el_parse(mod, n=6):
    rows = [{"local_id": f"A{i:03d}", "title": _title(i),
             "abstract": f"Abstract {i}.", "keywords": "vr"} for i in range(n)]
    return mod.ParseReport(
        header=["local_id", "title", "abstract", "keywords"],
        rows=rows, skipped=[])


def _run_el(mod, monkeypatch, script, *, cache_in, batch_size=3):
    """Drive the real EL engine — real prompt builder, real cache keys —
    with a scripted client, and hand back everything the caller needs."""
    client = _ScriptedClient(script)
    monkeypatch.setattr(lc, "_openai_client_for", lambda *_a, **_k: client)
    monkeypatch.setattr(lc, "_has_openai_key", lambda *_a, **_k: True)
    (full_rows, survivors, counts, _imp, _ev, cache_out, cancelled,
     _report) = \
        mod.run_el_screen(
            _el_parse(mod), mod.CriteriaLoadReport(
                criteria=[_el_criterion(mod)], warnings=[]),
            model="gpt-4o-mini", trunc_chars=1500, batch_size=batch_size,
            use_cache=True, cache_in=cache_in,
            cancel_event=threading.Event(),
        )
    assert cancelled is False
    return full_rows, counts, cache_out, client


def _outcome(full_rows, local_id):
    return next(r["el_outcome"] for r in full_rows if r["local_id"] == local_id)


def _substituting_script():
    """Batch 1 fabricates a "meet" for A004; A004's own batch omits it. In
    this scenario no record legitimately meets the exclusion criterion, so
    any "meet" anywhere is fabricated by construction."""
    def call1(a_ids):
        return ([_answer(a, "not_meet", _title(int(a[1:]))) for a in a_ids]
                + [_answer("A004", "meet", _title(4))])

    def call2(a_ids):
        return [_answer(a, "not_meet", _title(int(a[1:])))
                for a in a_ids if a != "A004"]

    return [call1, call2]


class TestSubstitutedVerdictDoesNotPersist:

    def test_the_run_does_not_exclude_the_substituted_record(self, monkeypatch):
        mod = get_el()
        full_rows, counts, _cache_out, _client = _run_el(
            mod, monkeypatch, _substituting_script(), cache_in={})
        assert _outcome(full_rows, "A004") != "OUT", (
            "F-86 end to end: A004 was excluded from the review on a verdict "
            "produced by a call whose prompt did not contain A004."
        )
        assert counts["OUT"] == 0

    def test_no_poisoned_entry_reaches_the_cache(self, monkeypatch):
        mod = get_el()
        _full_rows, _counts, cache_out, _client = _run_el(
            mod, monkeypatch, _substituting_script(), cache_in={})

        poisoned = [v for v in cache_out.values()
                    if v.get("decision") == "meet" and v.get("valid_quote")]
        assert poisoned == [], (
            "F-86 persistence: the fabricated verdict was written back under "
            "the substituted record's own legitimate cache key, so it replays "
            f"on every later run at zero cost. Cached: {poisoned!r}"
        )

    def test_the_exclusion_does_not_replay_from_the_cache(self, monkeypatch):
        """The harm the register describes is not one bad run but a bad run
        made permanent. Run once, keep the cache, run again against a client
        that answers honestly, and the exclusion must be gone."""
        mod = get_el()
        _first_rows, _counts, cache_out, _c1 = _run_el(
            mod, monkeypatch, _substituting_script(), cache_in={})

        def honest(a_ids):
            return [_answer(a, "not_meet", _title(int(a[1:]))) for a in a_ids]

        second_rows, second_counts, _cache2, client2 = _run_el(
            mod, monkeypatch, [honest, honest], cache_in=dict(cache_out))

        assert _outcome(second_rows, "A004") != "OUT", (
            "F-86 persistence: the second run reproduced the exclusion of "
            f"A004 from cache alone ({len(client2.sent)} API call(s) made). "
            "Re-running is the user's remedy and the cache defeats it."
        )
        assert second_counts["OUT"] == 0
