# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT
"""Wave 16a — the offline half of tools/run_criteria_experiment.py.

Covers: spec parsing (the committed experiment spec must load and validate),
call arithmetic (the tool's formula must agree with the engine's RunPlan on a
grid), baseline reproduction (the tool's dry pipeline must reproduce the
pinned chain 776 -> 16 -> 760 -> 738 -> 22 with IC-5 met=70/failed=690), the
F-205/F-208 raw-probe semantics, and the structural zero-network property of
dry mode (client construction patched to raise; the dry pipeline must complete
anyway).
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT

TOOLS_DIR = PROJECT_ROOT / "tools"
SPEC_PATH = PROJECT_ROOT / "docs" / "data" / "wave16_arms" / "experiment_spec.json"

# Import the script under test by file path (tools/ is not a package).
_spec = importlib.util.spec_from_file_location(
    "run_criteria_experiment", str(TOOLS_DIR / "run_criteria_experiment.py")
)
rce = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rce
_spec.loader.exec_module(rce)


@pytest.fixture(scope="module")
def mods():
    return rce._Mods()


@pytest.fixture(scope="module")
def spec():
    return rce.load_spec(SPEC_PATH)


@pytest.fixture(scope="module")
def corpus(mods, spec):
    corpus_path = PROJECT_ROOT / spec["corpus"]
    text = corpus_path.read_bytes().decode("utf-8-sig")
    parse = mods.common_parser._parse_csv_tolerant_text(text)
    a_columns, text_stats = mods.h_parser._load_a_header_and_stats(str(corpus_path))
    return parse, a_columns, text_stats


class TestSpecParsing:
    def test_committed_spec_loads(self, spec):
        assert spec["spec_version"] == 1
        keys = [a["key"] for a in spec["arms"]]
        assert keys[0] == "arm0_baseline"
        assert len(keys) == 8 and len(set(keys)) == 8

    def test_every_arm_has_intents_recorded(self, spec):
        """Landings-vs-intent is only honest if intent predates the run."""
        for arm in spec["arms"]:
            assert arm.get("intents"), f"arm {arm['key']} has no recorded intents"
            for intent in arm["intents"]:
                assert intent.get("rationale"), (
                    f"{arm['key']}/{intent.get('id')}: rationale required")

    def test_rejects_unknown_kind(self, tmp_path):
        bad = {"spec_version": 1, "corpus": "x", "corpus_sha256": "y",
               "window": 4096, "trunc_chars": 1500,
               "arms": [{"key": "k", "kind": "nope", "source": "s"}]}
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="unknown kind"):
            rce.load_spec(p)

    def test_rejects_duplicate_arm_keys(self, tmp_path):
        bad = {"spec_version": 1, "corpus": "x", "corpus_sha256": "y",
               "window": 4096, "trunc_chars": 1500,
               "arms": [{"key": "k", "kind": "free_text", "source": "s"},
                        {"key": "k", "kind": "free_text", "source": "s"}]}
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="duplicate arm key"):
            rce.load_spec(p)


class TestCallArithmetic:
    def test_matches_engine_runplan_on_a_grid(self, mods):
        RunPlan = mods.run_estimate.RunPlan
        for records in (0, 1, 4, 5, 22, 147, 776):
            for criteria in (0, 1, 2, 4):
                for batch in (1, 5, 10, 50):
                    assert rce.calls_for(records, criteria, batch) == RunPlan(
                        records=records, criteria=criteria,
                        batch_size=batch).requests

    def test_known_values(self):
        # The 15e acceptance decomposition: 147 records, 2 criteria.
        assert rce.calls_for(147, 2, 5) == 60
        assert rce.calls_for(147, 2, 1) == 294
        assert rce.calls_for(147, 2, 10) == 30
        # The pinned current-rules EL population.
        assert rce.calls_for(22, 2, 5) == 10


class TestBaselineReproduction:
    def test_dry_pipeline_reproduces_the_pinned_chain(self, mods, spec, corpus):
        parse, a_columns, text_stats = corpus
        arm0 = spec["arms"][0]
        manifest = rce.run_arm_dry(mods, spec, arm0, parse, a_columns, text_stats)
        assert manifest["pin_check"]["ok"], manifest["pin_check"]
        assert manifest["funnel"]["eh"]["out"] == 16
        assert manifest["funnel"]["ih"]["out"] == 738
        assert manifest["funnel"]["records_at_el"] == 22
        imp = manifest["funnel"]["ih"]["impacts"]
        assert imp["IC-5"]["met"] == 70 and imp["IC-5"]["failed"] == 690
        # Landings: the baseline translator output must match recorded intent.
        assert all(d["match"] for d in manifest["landings_vs_intent"]), (
            [d for d in manifest["landings_vs_intent"] if not d["match"]])

    def test_pin_mismatch_stops_hard(self, mods, spec, corpus):
        parse, a_columns, text_stats = corpus
        arm0 = dict(spec["arms"][0])
        arm0["pin"] = {"chain": {"input": 776, "eh_out": 999, "eh_surv": 1,
                                 "ih_out": 1, "ih_surv": 1}, "ih_impacts": {}}
        with pytest.raises(SystemExit, match="BASELINE PIN FAILED"):
            rce.run_arm_dry(mods, spec, arm0, parse, a_columns, text_stats)


class TestRawProbeSemantics:
    """The F-205/F-208 bundle-read semantics, pinned through the tool."""

    STAGELESS = (
        "id,type,scope,label,operator,target,what,threshold,enabled,source_text\n"
        "R1,include,metadata,probe,contains,title,virtual,,1,R1\n"
        "R2,exclude,metadata,probe blank op,,lang,de,,1,R2\n"
        "R4,include,metadata,probe blank enabled,contains,title,reality,,,R4\n"
    )

    def test_stageless_assume_all_at_eh_ih_and_drop_all_at_el_il(self, mods):
        probe = rce.raw_probe(mods, self.STAGELESS)
        # F-205 assume-all: R1 and R2 load at BOTH deterministic stages.
        assert [c["id"] for c in probe["EH"]["loaded"]] == ["R1", "R2"]
        assert [c["id"] for c in probe["IH"]["loaded"]] == ["R1", "R2"]
        # F-205 operator half: blank operator becomes equals here.
        assert probe["EH"]["loaded"][1]["operator"] == "equals"
        # F-205 drop-all: EL/IL load nothing, with the aggregate warning.
        assert probe["EL"]["loaded"] == [] and probe["IL"]["loaded"] == []
        assert any("No EL criteria found" in w for w in probe["EL"]["warnings"])
        # F-208: the blank-enabled row is silently absent at EH/IH.
        assert "R4" not in [c["id"] for c in probe["EH"]["loaded"]]
        assert not any("R4" in w for w in probe["EH"]["warnings"])


class TestDerivedArms:
    """Wave 16a-deltas: the s1 supplement arms (bundle corpus, derived rows)."""

    def test_spec_carries_the_two_supplement_arms(self, spec):
        keys = [a["key"] for a in spec["arms"]]
        assert keys[-2:] == ["s1a_wording_el", "s1b_polarity_il"]
        assert len(keys) == 8
        for arm in spec["arms"][-2:]:
            assert arm["kind"] == "derived_rows"
            assert arm.get("comparison"), "comparison plan must be recorded"
        assert "population_banner" in spec["corpus_bundle"]

    def test_rejects_derived_arm_without_bundle(self, tmp_path):
        bad = {"spec_version": 1, "corpus": "x", "corpus_sha256": "y",
               "window": 4096, "trunc_chars": 1500,
               "arms": [{"key": "p", "kind": "free_text", "source": "s"},
                        {"key": "d", "kind": "derived_rows", "source": "s",
                         "derive_from": "p", "ids": ["A"], "stage": "EL"}]}
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match="corpus_bundle"):
            rce.load_spec(p)

    def test_derivation_is_byte_identical_to_the_parent(self, mods, spec, corpus):
        _parse, a_columns, text_stats = corpus
        arm = next(a for a in spec["arms"] if a["key"] == "s1a_wording_el")
        rows, derived_csv, _psha = rce.derive_rows_from_parent(
            mods, spec, arm, a_columns, text_stats)
        assert [r["id"] for r in rows] == ["EC-2", "EC-3"]
        parent = next(a for a in spec["arms"] if a["key"] == "g1_paraphrase")
        parent_rows = rce.translate_free_text(
            mods, (PROJECT_ROOT / parent["source"]).read_text(encoding="utf-8-sig"),
            a_columns, text_stats)
        parent_csv = mods.h_exporters._criteria_csv_text(parent_rows)
        parent_lines = set(parent_csv.splitlines())
        for line in derived_csv.splitlines()[1:]:
            assert line in parent_lines

    def test_derivation_rejects_missing_ids(self, mods, spec, corpus):
        _parse, a_columns, text_stats = corpus
        arm = dict(next(a for a in spec["arms"] if a["key"] == "s1a_wording_el"))
        arm["ids"] = ["EC-2", "EC-999"]
        with pytest.raises(SystemExit, match="not all present"):
            rce.derive_rows_from_parent(mods, spec, arm, a_columns, text_stats)

    def test_supplement_call_arithmetic(self):
        assert rce.calls_for(147, 2, 5) == 60   # per supplement arm
        assert rce.calls_for(147, 2, 1) == 294

    @pytest.mark.skipif(
        not Path("S:/Alejandro_/projet julien (prisma-hub)/_archive_bundles").exists(),
        reason="external bundle archive not present on this machine")
    def test_bundle_identified_by_manifest_content_then_zip_digest(self, mods, spec):
        parse, ident = rce.resolve_bundle_corpus(mods, spec["corpus_bundle"])
        assert len(parse.rows) == 147
        assert ident["zip_sha256"] == spec["corpus_bundle"]["zip_sha256"]
        assert ident["member_sha256_verified"]["data/current.csv"] == (
            spec["corpus_bundle"]["member_sha256"]["data/current.csv"])
        assert ident["criteria_member_sha256"].startswith("5dd51aaa")
        assert ident["population_banner"]


class TestDryModeIsStructurallyOffline:
    def test_dry_arm_completes_with_client_construction_forbidden(
            self, mods, spec, corpus, monkeypatch):
        """The dry pipeline must never construct an LLM client: patch the one
        constructor to raise and run a full dry arm — translation, loaders,
        chain, budget guard, arithmetic — to completion."""
        def _boom(*a, **k):
            raise AssertionError("network path reached in dry mode")
        monkeypatch.setattr(mods.llm_client, "_openai_client_for", _boom)
        parse, a_columns, text_stats = corpus
        arm0 = spec["arms"][0]
        manifest = rce.run_arm_dry(mods, spec, arm0, parse, a_columns, text_stats)
        assert manifest["pin_check"]["ok"]

    def test_live_flag_requires_explicit_tripwire(self):
        with pytest.raises(SystemExit):
            rce.main(["--live", "--arm", "arm0_baseline"])  # no --budget/--yes-live
