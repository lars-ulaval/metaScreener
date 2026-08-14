
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_decision_whitelist.py — F-90: a model that answers in the right
vocabulary but the wrong case must not have every verdict destroyed, and a
model that answers outside the vocabulary must leave a trace.

``decision`` was compared against the inline literal set
``{"meet", "not_meet", "uncertain"}`` with only ``.strip()`` applied, while
``field`` on the *next* statement got ``.strip().lower()``. So a model
answering ``"Meet"``, ``"MEET"``, ``"Not_Meet"`` or ``"not meet"`` had every
decision silently rewritten to ``"uncertain"``.

What made that worse than a lost verdict is what the record then looked
like: ``used: True``, a genuine quote, ``valid_quote: True`` and a high
confidence — an audit record that contradicts itself, produced with no log
line and no count that looks wrong. The run is indistinguishable from one in
which the model was unsure about everything, which is the signature
``docs/llm-evaluation.md`` tells a reader to interpret as a lazy model.

The contract these tests pin:
  - the vocabulary is matched case-insensitively, and across the separator
    the model actually varies (``not meet`` / ``not-meet`` / ``not_meet``);
  - the widening is exact — ``meets``, ``does not meet`` and ``yes`` are
    still outside the vocabulary;
  - a rejection is *counted* on the record and *logged* once per criterion,
    so the condition has a signature of its own;
  - a rejected decision is not written to the persistent cache, because a
    cached rejection would serve the unusable answer for ever and destroy
    the very log line this finding asks for.
"""
import json
import threading

import pytest

import plugins._common.llm_client as lc


# ---------------------------------------------------------------------------
# helpers — same fake-client shape as tests/test_cancellation.py
# ---------------------------------------------------------------------------

CID = "EC-1"


class _FakeResponse:
    def __init__(self, payload):
        msg = type("M", (), {"content": json.dumps(payload)})
        self.choices = [type("C", (), {"message": msg})]


class _DecisionClient:
    """Answers every item with a fixed ``decision`` string, a genuine quote
    drawn from the record's own title, and a confidence above any threshold.

    That combination is the point: it is exactly the record F-90 produces —
    everything about it looks like a good answer except the one field the
    parser reads.
    """

    def __init__(self, decision):
        self.decision = decision
        self.calls = 0
        outer = self

        class _Completions:
            def create(self, *, model, messages, temperature, response_format=None):
                outer.calls += 1
                payload = json.loads(messages[1]["content"])
                return _FakeResponse([
                    {"a_id": it["a_id"], "decision": outer.decision,
                     "confidence": 0.95, "field": "title",
                     "quote": it["title"], "span": [0, 1]}
                    for it in payload["items"]
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
    monkeypatch.setattr(lc, "_has_openai_key", lambda *_a, **_k: True)
    return lc


def _run(monkeypatch, decision, n_items=3, log=None):
    client = _DecisionClient(decision)
    monkeypatch.setattr(lc, "_openai_client_for", lambda *_a, **_k: client)
    criterion = {"id": CID, "type": "exclude", "operator": "llm",
                 "target": "title", "what": ["x"], "how": "llm",
                 "label": "x", "threshold": 0.6}
    items = [{"a_id": f"A{i:03d}", "title": f"Title {i}", "abstract": "",
              "keywords": ""} for i in range(n_items)]
    out = lc.run_m1_llm_for_criterion(
        criterion, items, stage="EL", build_messages=_build_messages,
        model="gpt-4o-mini", trunc_chars=1500, batch_size=10,
        log=log, cancel_token=threading.Event(),
    )
    return out


# ---------------------------------------------------------------------------
# F-90 — the vocabulary must be matched case-insensitively
# ---------------------------------------------------------------------------

class TestCaseFolding:

    @pytest.mark.parametrize("sent,expected", [
        ("Meet", "meet"),
        ("MEET", "meet"),
        ("meet", "meet"),
        ("  Meet  ", "meet"),
        ("Not_Meet", "not_meet"),
        ("NOT_MEET", "not_meet"),
        ("not_meet", "not_meet"),
        ("Uncertain", "uncertain"),
        ("UNCERTAIN", "uncertain"),
    ])
    def test_the_vocabulary_is_case_insensitive(self, llm, monkeypatch,
                                                sent, expected):
        out = _run(monkeypatch, sent)
        got = out[("A000", CID)]["decision"]
        assert got == expected, (
            f"F-90: the model answered {sent!r} and the parser recorded "
            f"{got!r}. `field` is case-folded two statements later; "
            f"`decision` was not, so every verdict in the run was destroyed."
        )

    @pytest.mark.parametrize("sent", ["not meet", "not-meet", "NOT MEET",
                                      "Not-Meet", "not  meet"])
    def test_the_separator_the_model_actually_varies_is_absorbed(
            self, llm, monkeypatch, sent):
        """F-90's own finding cell names ``"not meet"`` among the strings a
        model produces. Case-folding alone does not reach it: the model
        varies the separator as readily as the case, and a local model has
        no ``response_format`` to hold it to either."""
        out = _run(monkeypatch, sent)
        assert out[("A000", CID)]["decision"] == "not_meet"

    def test_every_record_in_the_run_is_recovered_not_just_the_first(
            self, llm, monkeypatch):
        out = _run(monkeypatch, "MEET", n_items=5)
        assert [out[(f"A{i:03d}", CID)]["decision"] for i in range(5)] == \
            ["meet"] * 5


class TestTheWideningIsExact:
    """A whitelist that has been widened too far is a worse defect than one
    that was too narrow, because it invents verdicts instead of losing
    them."""

    @pytest.mark.parametrize("sent", [
        "meets", "does not meet", "not_meets", "yes", "no", "maybe",
        "unsure", "meet_not", "", "notmeet",
    ])
    def test_a_value_outside_the_vocabulary_is_still_rejected(
            self, llm, monkeypatch, sent):
        out = _run(monkeypatch, sent)
        ev = out[("A000", CID)]
        assert ev["decision"] == "uncertain"


# ---------------------------------------------------------------------------
# F-90 — a rejection must have a signature of its own
# ---------------------------------------------------------------------------

class TestRejectionsAreVisible:

    def test_a_rejected_decision_is_recorded_on_the_record(self, llm,
                                                           monkeypatch):
        """The raw string, not just the fact of rejection: a user asking why
        every record is uncertain needs to see what the model actually said,
        and `maybe` and `Meet` call for opposite responses."""
        out = _run(monkeypatch, "maybe")
        ev = out[("A000", CID)]
        assert ev.get("decision_rejected") == "maybe", (
            "F-90: the record carries used=True, a valid quote and a high "
            "confidence, and nothing recording that its decision was thrown "
            "away. That is an audit record contradicting itself."
        )

    def test_an_accepted_decision_carries_no_rejection_marker(self, llm,
                                                             monkeypatch):
        out = _run(monkeypatch, "Meet")
        assert "decision_rejected" not in out[("A000", CID)]

    def test_the_rejection_is_logged_once_per_criterion(self, llm,
                                                        monkeypatch):
        lines = []
        _run(monkeypatch, "maybe", n_items=4, log=lines.append)
        text = "".join(lines)
        assert "maybe" in text, (
            "F-90: the failure is produced with no log line at all, so the "
            "only symptom is a run in which the model was unsure about "
            "everything."
        )
        assert text.count("decision") <= 2, (
            "one summary line per criterion, not one per record — a corpus "
            "of 800 would bury the log tab it is written to"
        )

    def test_an_accepted_run_logs_no_rejection_line(self, llm, monkeypatch):
        lines = []
        _run(monkeypatch, "Meet", n_items=4, log=lines.append)
        assert "reject" not in "".join(lines).lower()

    def test_the_count_is_derivable_from_the_records(self, llm, monkeypatch):
        """Derived, never stored: the count is a pure function of the
        evidence the decisions were actually made from, so it cannot drift
        from them the way a hand-maintained counter can (F-131, F-69)."""
        out = _run(monkeypatch, "maybe", n_items=4)
        summary = lc.summarize_llm_evidence(out)
        assert summary["decisions_rejected"] == 4
        assert summary["records"] == 4
        assert summary["answered"] == 0, (
            "a decision the parser cannot read is not an answer"
        )

    def test_field_rejections_are_counted_too(self, llm, monkeypatch):
        """F-136. Not fixed here — `field` is already case-folded, and
        widening its acceptance would change which text a quote is
        validated against. Counted so the row can be settled on
        measurement."""
        client = _DecisionClient("meet")

        class _BadField:
            def create(self, *, model, messages, temperature, response_format=None):
                payload = json.loads(messages[1]["content"])
                return _FakeResponse([
                    {"a_id": it["a_id"], "decision": "meet",
                     "confidence": 0.95, "field": "title/abstract",
                     "quote": it["title"], "span": [0, 1]}
                    for it in payload["items"]
                ])

        client.chat = type("Chat", (), {"completions": _BadField()})()
        monkeypatch.setattr(lc, "_openai_client_for", lambda *_a, **_k: client)
        out = lc.run_m1_llm_for_criterion(
            {"id": CID, "type": "exclude", "operator": "llm",
             "target": "title", "what": ["x"], "how": "llm", "label": "x",
             "threshold": 0.6},
            [{"a_id": "A000", "title": "T", "abstract": "", "keywords": ""}],
            stage="EL", build_messages=_build_messages,
            model="m", trunc_chars=1500, batch_size=10,
        )
        assert lc.summarize_llm_evidence(out)["fields_rejected"] == 1


# ---------------------------------------------------------------------------
# F-90 × F-87 — a rejection must not be served back for ever
# ---------------------------------------------------------------------------

class TestARejectedDecisionIsNotCached:

    def test_a_rejected_entry_is_refused_by_the_cache_predicate(self):
        """F-87's rule reaches this by extension: an entry whose decision
        the parser could not read does not record a verdict. Caching it
        would serve the unusable answer on every later run at zero cost —
        and destroy the log line F-90 exists to produce, since a cache hit
        never reaches the parser at all."""
        rejected = {"used": True, "decision": "uncertain", "confidence": 0.95,
                    "field": "title", "quote": "q", "span": None,
                    "valid_quote": True, "decision_rejected": "maybe"}
        assert lc._is_cacheable_evidence(rejected) is False

    def test_an_accepted_entry_is_still_cacheable(self):
        accepted = {"used": True, "decision": "meet", "confidence": 0.95,
                    "field": "title", "quote": "q", "span": None,
                    "valid_quote": True}
        assert lc._is_cacheable_evidence(accepted) is True


# ---------------------------------------------------------------------------
# F-119 — the skip line must report the value it observed
# ---------------------------------------------------------------------------

class TestTheSkipLineNamesTheActualModel:
    """``"model=None; skipping."`` asserted a value the code never looked
    at, and its reachable trigger was a *whitespace-only* field — so a user
    who trusted the line went looking for a null where there was a space."""

    @pytest.mark.parametrize("model,shown", [(None, "None"), ("", "''")])
    def test_the_line_shows_what_was_actually_set(self, llm, monkeypatch,
                                                  model, shown):
        lines = []
        out = lc.run_m1_llm_for_criterion(
            {"id": CID, "type": "exclude", "operator": "llm",
             "target": "title", "what": ["x"], "how": "llm", "label": "x",
             "threshold": 0.6},
            [{"a_id": "A000", "title": "T", "abstract": "", "keywords": ""}],
            stage="EL", build_messages=_build_messages, model=model,
            trunc_chars=1500, batch_size=1, log=lines.append,
        )
        assert out == {}
        text = "".join(lines)
        assert shown in text, f"expected {shown!r} in {text!r}"
        assert "model=None; skipping." not in text

    @pytest.mark.parametrize("model", ["   ", "\t"])
    def test_a_whitespace_model_is_NOT_caught_here_which_is_why_f93_exists(
            self, llm, monkeypatch, model):
        """The engine's guard is ``if not model:``, and a whitespace-only
        string is **truthy** — so it is not the engine that refuses one. The
        UI had already stripped it to ``""`` before this point, which is how
        the value reached the guard at all, and why the old line's `None`
        was wrong about what it had seen.

        Refusing whitespace belongs in the UI, where the user can be told
        about it: that is F-93's remaining half. Pinned here so the division
        of labour is recorded rather than assumed."""
        client = _DecisionClient("meet")
        monkeypatch.setattr(lc, "_openai_client_for", lambda *_a, **_k: client)
        lines = []
        lc.run_m1_llm_for_criterion(
            {"id": CID, "type": "exclude", "operator": "llm",
             "target": "title", "what": ["x"], "how": "llm", "label": "x",
             "threshold": 0.6},
            [{"a_id": "A000", "title": "T", "abstract": "", "keywords": ""}],
            stage="EL", build_messages=_build_messages, model=model,
            trunc_chars=1500, batch_size=1, log=lines.append,
        )
        assert client.calls == 1, (
            "a whitespace-only model reaches the wire: the engine cannot "
            "tell it from a real one"
        )
        assert "no model set" not in "".join(lines)
