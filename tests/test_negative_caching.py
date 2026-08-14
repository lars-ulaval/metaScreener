
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_negative_caching.py — F-87: a non-answer must not be cached as a verdict.

Two halves, both here because they are one register row.

**The cache write-back.** EL's and IL's write-back merged *every* entry of
the result map into the cache with no filter on ``used`` or ``error``. A
transient 500, a timeout, an auth blip, an oversize failure or a model
refusal therefore landed in the persistent cache under a key that matches on
every later run, and ``ev.setdefault("used", True)`` on the read side then
served it back as though it were an answer. The direction of harm is safe —
``uncertain`` flags rather than excludes — but the user's remedy for a
network blip is to re-run, and re-running is precisely the action the cache
defeats. The raw SDK exception text also travelled into the exported bundle,
where it is neither wanted nor accurate.

**The duplicate-``local_id`` companion.** Two rows sharing one ``local_id``
collapse onto a single verdict, so a quote drawn from the first row's text
can exclude the second row, whose own text does not contain it. Measured at
``OUT = 2/3``. Until now the only thing standing in the way was the
loader: ``_load_bundle`` drops duplicate ids, and ``plugins/_common/parser``
dedupes as well since F-55. Both are upstream of the engine, so the safety
property was carried by the caller rather than by the gate, and any caller
constructing a ``ParseReport`` directly — which is what these tests do, and
what the standalone shells and the test suite already do — walked straight
past it. The guard now lives in the engine too. The loader keeps its own.
"""
import json
import threading

import pytest

from conftest import get_el, get_il

import plugins._common.llm_client as lc


# (loader, stage, column prefix, the stage's name for its flagged outcome —
# EL calls it PASS_FLAGGED and IL calls it REVIEW; see each module's OUTCOMES)
STAGES = [(get_el, "EL", "el", "PASS_FLAGGED"), (get_il, "IL", "il", "REVIEW")]
STAGE_IDS = ["el", "il"]

QUOTE = "randomised controlled trial of virtual reality"


def _abstract(i: int) -> str:
    return f"Record {i}: a {QUOTE} in stroke rehabilitation."


class _FakeResponse:
    def __init__(self, payload):
        msg = type("M", (), {"content": json.dumps(payload)})
        self.choices = [type("C", (), {"message": msg})]


class _Client:
    """Scripted stand-in for the OpenAI client.

    ``behaviour`` takes the a_ids the call was sent and returns a response
    payload, or raises to simulate an API failure.
    """

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.sent = []
        outer = self

        class _Completions:
            def create(self, *, model, messages, temperature, response_format=None):
                payload = json.loads(messages[1]["content"])
                a_ids = [it["a_id"] for it in payload["items"]]
                outer.sent.append(a_ids)
                return _FakeResponse(outer.behaviour(a_ids))

        self.chat = type("Chat", (), {"completions": _Completions()})()


def _answer(a_id, decision, quote, confidence=0.95, field="abstract"):
    return {"a_id": a_id, "decision": decision, "confidence": confidence,
            "field": field, "quote": quote, "span": [0, len(quote)]}


THE_500 = "Internal server error (500) from api.openai.com: upstream timeout"


def _always_fails(_a_ids):
    # Neither a rate-limit nor an oversize message, so the adaptive-split and
    # truncation-reduction paths are skipped and the batch goes straight to
    # the terminal back-fill that stamps `error` onto every item.
    raise RuntimeError(THE_500)


def _honest(a_ids):
    return [_answer(a, "not_meet", QUOTE) for a in a_ids]


def _criterion(mod, stage):
    return mod.Criterion(
        id=f"{stage[0]}C-1", stage=stage, ctype="exclude", enabled=True,
        operator="llm", targets=["abstract"], what_raw="vr",
        what_list=["vr"], threshold=0.6, source_text="uses VR", label="uses VR",
    )


def _parse(mod, rows):
    return mod.ParseReport(
        header=["local_id", "title", "abstract", "keywords"],
        rows=rows, skipped=[])


def _rows(n=4):
    return [{"local_id": f"A{i:03d}", "title": f"Title {i}",
             "abstract": _abstract(i), "keywords": "vr"} for i in range(n)]


def _run(mod, stage, monkeypatch, behaviour, *, rows=None, cache_in=None,
         batch_size=2):
    client = _Client(behaviour)
    monkeypatch.setattr(lc, "_openai_client_for", lambda *_a, **_k: client)
    monkeypatch.setattr(lc, "_has_openai_key", lambda *_a, **_k: True)
    run = mod.run_el_screen if stage == "EL" else mod.run_il_screen
    (full_rows, _surv, counts, _imp, _ev, cache_out, cancelled,
     _report) = run(
        _parse(mod, rows if rows is not None else _rows()),
        mod.CriteriaLoadReport(criteria=[_criterion(mod, stage)], warnings=[]),
        model="gpt-4o-mini", trunc_chars=1500, batch_size=batch_size,
        use_cache=True, cache_in=dict(cache_in or {}),
        cancel_event=threading.Event(),
    )
    assert cancelled is False
    return full_rows, counts, cache_out, client


# ---------------------------------------------------------------------------
# the write gate itself
# ---------------------------------------------------------------------------

class TestIsCacheableEvidence:
    """One predicate, used by both stages, so the rule has one definition."""

    def test_a_real_answer_is_cacheable(self):
        assert lc._is_cacheable_evidence(
            {"used": True, "decision": "meet", "valid_quote": True}) is True

    def test_an_entry_carrying_an_error_is_not(self):
        assert lc._is_cacheable_evidence(
            {"used": False, "decision": "uncertain", "error": THE_500}) is False

    def test_an_empty_error_string_still_counts_as_an_error(self):
        """`error` is set from `str(e)`, and an exception raised with no
        message stringifies to "". Presence of the key is what marks a
        terminal failure, not the truthiness of its value."""
        assert lc._is_cacheable_evidence(
            {"used": True, "decision": "meet", "error": ""}) is False

    def test_an_unused_entry_is_not(self):
        assert lc._is_cacheable_evidence(
            {"used": False, "decision": "uncertain"}) is False

    def test_an_entry_that_does_not_say_it_was_used_is_not(self):
        """The read side defaults a missing `used` to True, for cache files
        written before the field existed. The write side must not: an entry
        that does not record a model answer is not evidence of one."""
        assert lc._is_cacheable_evidence({"decision": "meet"}) is False

    def test_a_non_dict_is_not(self):
        assert lc._is_cacheable_evidence(None) is False
        assert lc._is_cacheable_evidence("meet") is False


# ---------------------------------------------------------------------------
# half one — failures, refusals and omissions must not be cached
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("getter,stage,_sl,flagged", STAGES, ids=STAGE_IDS)
class TestFailuresAreNotCached:

    def test_a_failed_call_writes_nothing_to_the_cache(self, getter, stage, _sl,
                                                       flagged, monkeypatch):
        mod = getter()
        _full, _counts, cache_out, client = _run(
            mod, stage, monkeypatch, _always_fails)
        assert client.sent, "the run must actually have tried to call"
        assert cache_out == {}, (
            f"F-87: {stage} cached {len(cache_out)} entry/entries produced by "
            f"an API failure. Each matches its key on every later run, so a "
            f"transient 500 has become a permanent verdict: {cache_out!r}"
        )

    def test_the_sdk_exception_text_does_not_reach_the_bundle(
            self, getter, stage, _sl, flagged, monkeypatch):
        """The cache member is serialised into the exported bundle, so the
        error string travelled with it."""
        mod = getter()
        _full, _counts, cache_out, _client = _run(
            mod, stage, monkeypatch, _always_fails)
        dumped = lc._dump_cache_to_jsonl(cache_out)
        assert "error" not in dumped
        assert "api.openai.com" not in dumped, (
            f"F-87: raw SDK exception text was serialised into {stage}'s "
            f"exported cache member: {dumped[:300]!r}"
        )

    def test_a_failure_does_not_survive_a_re_run(self, getter, stage, _sl,
                                                 flagged, monkeypatch):
        """The harm is not the failed run, it is that re-running cannot
        clear it. Fail once, keep the cache, run again against a healthy
        API, and every record must get a real answer."""
        mod = getter()
        _first, _c1, cache_out, _client = _run(
            mod, stage, monkeypatch, _always_fails)

        full_rows, _c2, _cache2, client2 = _run(
            mod, stage, monkeypatch, _honest, cache_in=cache_out)

        assert client2.sent, (
            f"F-87: the second run made no API call at all — {stage} served "
            f"the cached failures back as verdicts. Re-running is the user's "
            f"remedy and the cache defeats it."
        )
        for row in full_rows:
            ev = json.loads(row[f"{_sl}_evidence_json"])[f"{stage[0]}C-1"]
            assert ev["used"] is True, (
                f"F-87: {row['local_id']} is still carrying the cached "
                f"non-answer after a clean re-run: {ev!r}"
            )

    def test_an_omitted_record_is_not_cached_but_the_answered_ones_are(
            self, getter, stage, _sl, flagged, monkeypatch):
        """A model that simply leaves a record out of its response produces
        a back-filled `used: False` entry. That is a non-answer too."""
        mod = getter()

        def drops_a000(a_ids):
            return [_answer(a, "not_meet", QUOTE) for a in a_ids
                    if a != "A000"]

        _full, _counts, cache_out, _client = _run(
            mod, stage, monkeypatch, drops_a000)
        assert len(cache_out) == 3, (
            f"F-87: expected the three answered records to be cached and the "
            f"omitted one not, got {len(cache_out)}: {cache_out!r}"
        )
        assert all(v.get("used") is True for v in cache_out.values())

    def test_real_answers_are_still_cached(self, getter, stage, _sl,
                                           flagged, monkeypatch):
        """The gate must refuse non-answers, not the cache itself."""
        mod = getter()
        _full, _counts, cache_out, _client = _run(
            mod, stage, monkeypatch, _honest)
        assert len(cache_out) == 4
        assert all(v["decision"] == "not_meet" for v in cache_out.values())

        # and they are served back, at no further cost
        _full2, _c2, _cache2, client2 = _run(
            mod, stage, monkeypatch, _honest, cache_in=cache_out)
        assert client2.sent == [], (
            "the gate has cost the cache its purpose: a second run over "
            "answers that were all cached still called the API"
        )

    def test_a_cache_supplied_by_the_caller_is_left_alone(
            self, getter, stage, _sl, flagged, monkeypatch):
        """The gate governs what this run writes. Entries that arrived in
        ``cache_in`` — from a bundle captured before this fix, say — are
        carried through untouched; silently dropping a user's existing cache
        would be its own kind of data loss."""
        mod = getter()
        pre_existing = {"legacy-key": {"used": False, "decision": "uncertain",
                                       "error": "an old 500"}}
        _full, _counts, cache_out, _client = _run(
            mod, stage, monkeypatch, _honest, cache_in=pre_existing)
        assert cache_out["legacy-key"] == pre_existing["legacy-key"]


# ---------------------------------------------------------------------------
# half two — the duplicate-local_id companion
# ---------------------------------------------------------------------------

def _duplicate_id_rows():
    """Three rows, two of them sharing ``A001``.

    The victim is the FIRST row: its abstract is about something else
    entirely and does not contain the quote. Both the engine's ``id_to_item``
    and the client's per-batch text map are built by assignment, so the
    *last* row under a given id is the one whose text the quote is validated
    against — which is why the quote lives in the second row here. Get that
    ordering the wrong way round and the quote fails validation, the verdict
    degrades to uncertain, and the defect does not fire at all.
    """
    return [
        {"local_id": "A001", "title": "First",
         "abstract": "A qualitative interview study of ward handover.",
         "keywords": "handover"},
        {"local_id": "A001", "title": "Second",
         "abstract": f"Record 1: a {QUOTE} in stroke rehabilitation.",
         "keywords": "vr"},
        {"local_id": "A002", "title": "Third",
         "abstract": "Record 2: a survey of clinicians.", "keywords": "survey"},
    ]


@pytest.mark.parametrize("getter,stage,_sl,flagged", STAGES, ids=STAGE_IDS)
class TestDuplicateLocalIdCannotBorrowEvidence:

    def test_a_row_is_not_excluded_on_another_row_s_quote(
            self, getter, stage, _sl, flagged, monkeypatch):
        mod = getter()

        def meets(a_ids):
            return [_answer(a, "meet", QUOTE) for a in a_ids]

        full_rows, counts, _cache, _client = _run(
            mod, stage, monkeypatch, meets, rows=_duplicate_id_rows())

        outcomes = [r[f"{_sl}_outcome"] for r in full_rows]
        assert counts["OUT"] == 0, (
            f"F-87 companion: {counts['OUT']} of 3 rows were excluded. Two "
            f"rows share local_id A001, so a single verdict was applied to "
            f"both, and the first of them — an interview study of ward "
            f"handover — was excluded on a quote that appears nowhere in its "
            f"own text. Outcomes: {outcomes}"
        )
        assert len(full_rows) == 3, "no row may be dropped by the guard"

    def test_the_ambiguous_id_is_never_sent_to_the_model(
            self, getter, stage, _sl, flagged, monkeypatch):
        """Two different records under one ``a_id`` make the model's answer
        unattributable whatever it says, so there is nothing to be gained by
        asking — and it would be billed."""
        mod = getter()
        _full, _counts, _cache, client = _run(
            mod, stage, monkeypatch, _honest, rows=_duplicate_id_rows())
        sent = [a for call in client.sent for a in call]
        assert "A001" not in sent, (
            f"F-87 companion: the ambiguous id was sent anyway: {client.sent}"
        )
        assert sent == ["A002"]

    def test_the_duplicated_rows_are_flagged_not_silently_passed(
            self, getter, stage, _sl, flagged, monkeypatch):
        """Fail-safe means uncertain, which is the stage's flag — not a
        clean pass that would assert the criterion was evaluated."""
        mod = getter()

        def meets(a_ids):
            return [_answer(a, "meet", QUOTE) for a in a_ids]

        full_rows, _counts, _cache, _client = _run(
            mod, stage, monkeypatch, meets, rows=_duplicate_id_rows())
        cid = f"{stage[0]}C-1"
        for row in full_rows[:2]:
            assert row[f"{_sl}_outcome"] == flagged
            assert row[f"{_sl}_uncertain_ids"] == cid
            ev = json.loads(row[f"{_sl}_evidence_json"])[cid]
            assert ev["status"] == "UNCERTAIN"
            assert ev["used"] is False

    def test_a_unique_corpus_is_unaffected(self, getter, stage, _sl,
                                           flagged, monkeypatch):
        mod = getter()
        full_rows, counts, cache_out, client = _run(
            mod, stage, monkeypatch, _honest)
        assert [a for call in client.sent for a in call] == \
            ["A000", "A001", "A002", "A003"]
        assert counts["PASS_CLEAN"] == 4
        assert len(cache_out) == 4
        assert all(r[f"{_sl}_uncertain_ids"] == "" for r in full_rows)


# ---------------------------------------------------------------------------
# belt and braces — the upstream dedup stays where it is
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("getter,stage,_sl,flagged", STAGES, ids=STAGE_IDS)
def test_the_loader_still_drops_duplicate_ids(getter, stage, _sl, flagged,
                                             tmp_path):
    """Moving the guard into the engine does not license removing the one
    the loader already had. The engine's guard exists because a direct
    ``ParseReport`` caller never reaches the loader — not because the loader
    was wrong."""
    import zipfile

    mod = getter()
    zp = tmp_path / f"{stage}_dup.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"sha256": {}}))
        zf.writestr("data/current.csv",
                    "local_id,title,abstract,keywords\n"
                    "A001,First,alpha,vr\n"
                    "A001,Second,beta,vr\n"
                    "A002,Third,gamma,vr\n")
        zf.writestr("criteria/criteria_harmonized.csv",
                    "stage,id,type,scope,label,operator,target,what,"
                    "threshold,enabled,source_text\n")

    bundle = mod._load_bundle(str(zp))
    assert [r["local_id"] for r in bundle.parse.rows] == ["A001", "A002"]
    assert any(s.get("reason") == "duplicate local_id"
               for s in bundle.parse.skipped)
