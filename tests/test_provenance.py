
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_provenance.py — F-88: record which engine produced a decision.

The gap
-------
Across ``plugins/`` and ``metascreener/`` the dict key ``"model"`` occurred
exactly once, inside the hashed-and-discarded JSON of the cache key. Not
the manifest, not the history entry, not the cache value, not the evidence
JSON, not any report column. **A finished bundle could not be attributed
to a model, a provider or an endpoint after the fact.**

That was survivable while there was effectively one engine. Once the
endpoint is switchable, the space of engines that could have produced a
bundle goes from a vendor catalogue to every quantisation of every
open-weight model, with nothing in any artefact narrowing it.

Where it is recorded, and why only there
----------------------------------------
**One artefact: the history entry of the manifest.** The other candidates
were considered and rejected, each for its own reason:

- *the evidence JSON* — per-decision attribution is tier 2 of §B8.1. It
  lives in the ``{el,il}_filtered`` CSVs, which are byte-identity goldens,
  so it carries the F-62/F-63/F-64 re-capture cost;
- *the cache value* — would move the cache goldens, and is **redundant**:
  since F-89 the cache *key* is a hash over the provenance itself (see
  ``TestWhatAPerRunClaimCoversForACachedDecision`` below), so a value
  restating it could only ever agree with its own key;
- *a report column* — a per-record column carrying a per-run constant,
  duplicated down every row, and a second representation of a fact the
  history entry already holds. That is F-69's shape, which this project
  has shipped four times.

The history entry is per stage *run*, which is the granularity the fact
actually has: one engine configuration produced one run.

Transport
---------
Inside the run report, not as a ninth tuple position. That is the
codebase's own instruction — ``run_el_screen``'s docstring says a key is
"safer, since a positional append is exactly what silently rebinds an
existing unpack", and names F-88 — and
``stage_state.py::run_outcome`` was already written to tolerate it:
"Unknown keys are ignored and missing keys default, so … provenance
fields and an older build's absent report are both non-events."

The writer then **lifts** it onto the history entry as a sibling of
``llm`` rather than leaving it nested inside, because ``llm`` is a
*counting* block — it records how many records were answered, failed or
rejected — and attribution is not a count.
"""
import json
import threading
import types
import zipfile

import pytest

from conftest import PROJECT_ROOT, get_el, get_il

import plugins._common.llm_client as lc
from plugins._common.bundle import _write_llm_stage_bundle
from plugins._common.llm_client import DEFAULT_OPENAI_BASE_URL

CID = "EC-1"

PROVENANCE_FIELDS = {
    "model", "endpoint", "temperature", "prompt_version",
    "trunc_chars", "batch_size",
}


# ---------------------------------------------------------------------------
# fakes — same shape as tests/test_run_report.py
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        msg = type("M", (), {"content": json.dumps(payload)})
        self.choices = [type("C", (), {"message": msg})]


def _client(handler):
    class _Completions:
        def create(self, *, model, messages, temperature, response_format=None):
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


@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setattr(lc, "_has_openai_key", lambda *_a, **_k: True)
    monkeypatch.setattr(lc, "time", types.SimpleNamespace(sleep=lambda *_a: None))
    return lc


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


def _run_stage(monkeypatch, mod, stage, handler=None, **kw):
    monkeypatch.setattr(lc, "_openai_client_for",
                        lambda *_a, **_k: _client(handler or _answers()))
    parse, report, run = _setup(mod, stage)
    opts = dict(model="gemma3", trunc_chars=1500, batch_size=4,
                use_cache=False, cache_in={}, cancel_event=threading.Event())
    opts.update(kw)
    return run(parse, report, **opts)


PARAMS = [(get_el, "EL"), (get_il, "IL")]


# ---------------------------------------------------------------------------
# The engine records it
# ---------------------------------------------------------------------------

class TestTheEngineRecordsItsProvenance:

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_the_run_report_carries_a_provenance_block(
            self, llm, monkeypatch, getter, stage):
        rep = _run_stage(monkeypatch, getter(), stage)[7]
        assert "provenance" in rep, (
            "the engine is the only layer that knows the resolved endpoint"
        )
        assert set(rep["provenance"]) == PROVENANCE_FIELDS

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_it_records_the_run_that_actually_happened(
            self, llm, monkeypatch, getter, stage):
        prov = _run_stage(monkeypatch, getter(), stage,
                          model="gemma3", trunc_chars=1500, batch_size=4,
                          temperature=0.25)[7]["provenance"]
        assert prov["model"] == "gemma3"
        assert prov["temperature"] == 0.25
        assert prov["trunc_chars"] == 1500
        assert prov["batch_size"] == 4
        assert prov["prompt_version"] == f"{stage}_v2_jsonschema"

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_the_endpoint_is_the_resolved_one(
            self, llm, monkeypatch, getter, stage):
        """Wave 9 made the endpoint a value the repository owns rather than
        one the SDK resolves invisibly. That is what makes it recordable."""
        prov = _run_stage(monkeypatch, getter(), stage)[7]["provenance"]
        assert prov["endpoint"] == DEFAULT_OPENAI_BASE_URL

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_a_local_endpoint_is_recorded_as_such(
            self, llm, monkeypatch, getter, stage):
        """The case the whole finding exists for: a bundle produced against
        a local server must not read as one produced against the vendor."""
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
        prov = _run_stage(monkeypatch, getter(), stage)[7]["provenance"]
        assert prov["endpoint"] == "http://localhost:11434/v1"

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_a_stage_with_no_criteria_claims_no_engine(
            self, llm, monkeypatch, getter, stage):
        """No criterion means no call, and a stage that consulted no model
        must not name one. Same rule as the `llm` block's own: a stage that
        did not measure must not claim it measured nothing."""
        mod = getter()
        parse, _r, run = _setup(mod, stage)
        empty = mod.CriteriaLoadReport(criteria=[], warnings=[])
        rep = run(parse, empty, model="gemma3", trunc_chars=1500,
                  batch_size=4, use_cache=False, cache_in={},
                  cancel_event=threading.Event())[7]
        assert "provenance" not in rep


# ---------------------------------------------------------------------------
# The bundle carries it
# ---------------------------------------------------------------------------

def _seed(tmp_path):
    from test_run_report import _seed as seed
    return seed(tmp_path)


def _export(tmp_path, **kw):
    from test_run_report import _export as export
    return export(tmp_path, **kw)


class TestTheBundleCarriesIt:

    def test_provenance_reaches_the_history_entry(self, tmp_path):
        entry = _export(tmp_path, llm_report={
            "records": 4, "answered": 4,
            "provenance": {"model": "gemma3",
                           "endpoint": "http://localhost:11434/v1",
                           "temperature": 0.0,
                           "prompt_version": "EL_v2_jsonschema",
                           "trunc_chars": 1500, "batch_size": 4}})
        assert entry["provenance"]["model"] == "gemma3"
        assert entry["provenance"]["endpoint"] == "http://localhost:11434/v1"

    def test_it_is_a_sibling_of_llm_not_a_member_of_it(self, tmp_path):
        """`llm` is the run-level *failure report* — how many records were
        answered, failed or rejected. Attribution is not a count, and a
        reader looking for the model should not have to find it inside a
        block named after counting."""
        entry = _export(tmp_path, llm_report={
            "records": 4, "answered": 4,
            "provenance": {"model": "gemma3"}})
        assert "provenance" not in entry["llm"]
        assert entry["llm"] == {"records": 4, "answered": 4}

    def test_the_counting_block_survives_unchanged(self, tmp_path):
        """`counts` is asserted by exact dict equality in two other
        modules; provenance must not leak into it."""
        entry = _export(tmp_path, llm_report={
            "failed": 4, "provenance": {"model": "gemma3"}})
        assert entry["counts"] == {"OUT": 0, "PASS_FLAGGED": 1}

    def test_a_report_without_provenance_leaves_no_key(self, tmp_path):
        """The wave-8 precedent, applied to this field."""
        entry = _export(tmp_path, llm_report={"records": 4, "answered": 4})
        assert "provenance" not in entry
        assert entry["llm"] == {"records": 4, "answered": 4}

    def test_no_report_at_all_leaves_no_key(self, tmp_path):
        entry = _export(tmp_path)
        assert "provenance" not in entry
        assert "llm" not in entry

    def test_an_empty_provenance_block_is_not_written(self, tmp_path):
        entry = _export(tmp_path, llm_report={"records": 4, "provenance": {}})
        assert "provenance" not in entry


class TestOldBundlesStillLoad:
    """F-68/F-70 precedent: legacy tolerance preserved and asserted."""

    def test_an_archived_manifest_gains_no_invented_provenance(self, tmp_path):
        """A bundle exported before this fix has no provenance anywhere.
        Re-exporting it must not manufacture one — an inferred engine
        recorded as an observed one is worse than a blank."""
        entry = _export(tmp_path)
        assert "provenance" not in entry

    def test_a_history_entry_without_provenance_is_readable(self, tmp_path):
        """The shape a pre-F-88 bundle has on disk: seven keys, no `llm`,
        no `provenance`. Nothing may require either."""
        entry = _export(tmp_path)
        assert set(entry) == {
            "stage", "ran_at", "counts", "survivors_rows",
            "out_rows_full", "cancelled", "not_screened",
        }


# ---------------------------------------------------------------------------
# The asymmetry: "answered" vs "was shown something"
# ---------------------------------------------------------------------------

class TestProvenanceDoesNotInheritTheAnsweredAmbiguity:
    """Wave 8 surfaced this: "the model answered" and "the model was shown
    something" are different claims, and only the first was recorded.

    A negative ``trunc_chars`` makes ``s[:trunc_chars]`` a negative slice,
    so fields are emptied rather than truncated — and the run report is
    *byte-identical* to a healthy run: 4 records, 4 answered, 0 failed.
    Provenance that recorded only model and endpoint would inherit that
    ambiguity exactly. Recording ``trunc_chars`` is what makes `answered`
    interpretable: the reader can see what the model was shown.
    """

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_the_counting_block_cannot_tell_the_two_apart(
            self, llm, monkeypatch, getter, stage):
        healthy = _run_stage(monkeypatch, getter(), stage, trunc_chars=1500)[7]
        starved = _run_stage(monkeypatch, getter(), stage, trunc_chars=-100)[7]
        counts_only = lambda r: {k: v for k, v in r.items() if k != "provenance"}
        assert counts_only(healthy) == counts_only(starved), (
            "if this ever differs, the ambiguity is gone and this test "
            "should be retired rather than repaired"
        )
        assert counts_only(starved)["answered"] == 4

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_provenance_separates_them(self, llm, monkeypatch, getter, stage):
        healthy = _run_stage(monkeypatch, getter(), stage,
                             trunc_chars=1500)[7]["provenance"]
        starved = _run_stage(monkeypatch, getter(), stage,
                             trunc_chars=-100)[7]["provenance"]
        assert healthy != starved
        assert starved["trunc_chars"] == -100, (
            "the artefact must record what the model was shown, not only "
            "that it answered"
        )


# ---------------------------------------------------------------------------
# What a per-run claim covers for a decision served from cache
# ---------------------------------------------------------------------------

class TestWhatAPerRunClaimCoversForACachedDecision:
    """The case that actually matters for a per-run answer.

    A bundle can carry decisions from several runs, because the cache
    persists across them. So: what may a reader conclude about a cached
    decision, from provenance recorded for the run that exported the
    bundle?

    Since F-89 the cache key is a SHA-256 over
    ``{prompt_version, model, endpoint, temperature, rendered_prompt}``.
    Four of those are recorded provenance fields, and ``trunc_chars``
    reaches the key through the bytes it removes from the rendered prompt.
    **A cached entry therefore cannot be served into a run whose
    provenance differs in any of them** — the lookup misses and the model
    is called again.

    That is what makes the per-run record a claim about every decision in
    the stage's output rather than only about the calls this run happened
    to make. These tests pin the mechanism the claim rests on, so that a
    future change to the key set fails here rather than silently widening
    what the manifest appears to assert.
    """

    def _key(self, mod, **kw):
        opts = dict(
            model="gemma3",
            criterion={"id": CID, "type": "exclude", "operator": "llm",
                       "target": "title", "what": ["x"], "how": "llm",
                       "label": "x", "threshold": 0.6},
            item={"a_id": "A001", "title": "Title 1", "abstract": "a",
                  "keywords": "k"},
            trunc_chars=1500,
            endpoint=DEFAULT_OPENAI_BASE_URL,
            temperature=0.0,
        )
        opts.update(kw)
        return mod._cache_key(**opts)

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    @pytest.mark.parametrize("field,value", [
        ("model", "gpt-4o-mini"),
        ("endpoint", "http://localhost:11434/v1"),
        ("temperature", 0.7),
    ])
    def test_a_change_of_provenance_cannot_hit_an_old_entry(
            self, getter, stage, field, value):
        mod = getter()
        assert self._key(mod) != self._key(mod, **{field: value}), (
            f"{field} is recorded as provenance but does not partition the "
            f"cache — a decision produced under a different {field} could "
            f"be served into this run, and the manifest would attribute it "
            f"to this run's engine."
        )

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_truncation_partitions_the_cache_when_it_changes_the_prompt(
            self, getter, stage):
        """`trunc_chars` is not a named key input; it reaches the key
        through the bytes it removes. So it partitions the cache exactly
        when it made a difference to what was sent, and not otherwise —
        which is the correct behaviour, not a gap."""
        mod = getter()
        # The fixture's fields are far shorter than either setting, so
        # neither truncates and the rendered prompt is identical.
        assert self._key(mod, trunc_chars=1500) == self._key(mod, trunc_chars=4000)
        # A negative setting empties fields, so the bytes differ.
        assert self._key(mod, trunc_chars=1500) != self._key(mod, trunc_chars=-100)

    @pytest.mark.parametrize("getter,stage", PARAMS, ids=["el", "il"])
    def test_batch_size_is_the_honest_residual(self, getter, stage):
        """`batch_size` is recorded but is **not** a cache-key input: the
        key renders a batch of one. So a cached decision may have been
        produced inside a differently-sized batch than the manifest
        records, and this is the one provenance field a reader may not
        carry back to a cached decision.

        Recorded here as a test rather than as a comment so that it is
        stated where it can stop being true silently.
        """
        mod = getter()
        import inspect
        params = inspect.signature(mod._cache_key).parameters
        assert "batch_size" not in params
