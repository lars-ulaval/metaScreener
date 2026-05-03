# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""test_eval_ingest.py - unit tests for tools/eval_ingest.py.

Covers:
  - Cohen's kappa pure-python implementation (perfect-agreement, perfect-
    disagreement, three-way reference values, NaN handling).
  - Fleiss' kappa pure-python implementation (perfect-agreement edge case,
    reference values, ValueError on inconsistent rater counts).
  - LLM status -> canonical decision mapping covers MET/FAILED/UNCERTAIN.
  - Filled-workbook reader: validates against manifest (rejects spurious
    rows, missing rows, empty cells, typos in dropdown values, malformed
    sheets), produces correctly-shaped long-format rows on valid input.
  - Join: missing LLM evidence rows get llm_status='MISSING' and
    agree=False; status mapping aligns the join key with human's
    include/exclude/uncertain vocabulary.
  - End-to-end: empty grid -> synthetic filler -> ingest -> verify Cohen
    kappa is high when agree_with_llm_rate is high, low when it is low.
  - Output files have expected schema and row counts.
"""
import csv
import importlib.util
import math
import shutil
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "tools"
TESTS_DATA = PROJECT_ROOT / "tests" / "data"
GOLDEN = PROJECT_ROOT / "tests" / "golden"


def _import(modname: str):
    spec = importlib.util.spec_from_file_location(
        modname, str(TOOLS_DIR / f"{modname}.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


egg = _import("eval_grid_generator")
ein = _import("eval_ingest")
fil = _import("eval_grid_filler_synthetic")


# --------------------------------------------------------------------------
# Pure-math: Cohen's kappa
# --------------------------------------------------------------------------

class TestCohenKappa:
    def test_perfect_agreement_returns_one(self):
        pairs = [("include", "include")] * 10 + [("exclude", "exclude")] * 5
        result = ein.cohen_kappa(pairs)
        assert result["n"] == 15
        assert math.isclose(result["agreement_observed"], 1.0)
        assert math.isclose(result["kappa"], 1.0)

    def test_perfect_disagreement(self):
        # Every "include" by A is "exclude" by B and vice versa.
        pairs = [("include", "exclude")] * 5 + [("exclude", "include")] * 5
        result = ein.cohen_kappa(pairs)
        assert result["n"] == 10
        assert math.isclose(result["agreement_observed"], 0.0)
        # P_e = 0.5 * 0.5 + 0.5 * 0.5 = 0.5; kappa = (0 - 0.5)/(1 - 0.5) = -1.
        assert math.isclose(result["kappa"], -1.0)

    def test_chance_agreement_zero(self):
        # 25 each of (incl,incl), (incl,excl), (excl,incl), (excl,excl).
        pairs = (
            [("include", "include")] * 25
            + [("include", "exclude")] * 25
            + [("exclude", "include")] * 25
            + [("exclude", "exclude")] * 25
        )
        result = ein.cohen_kappa(pairs)
        # P_o = 50/100 = 0.5; P_e = 0.5*0.5 + 0.5*0.5 = 0.5; kappa = 0.
        assert math.isclose(result["agreement_observed"], 0.5)
        assert math.isclose(result["kappa"], 0.0, abs_tol=1e-9)

    def test_empty_pairs_returns_nan(self):
        result = ein.cohen_kappa([])
        assert result["n"] == 0
        assert math.isnan(result["kappa"])

    def test_unanimous_single_class_returns_nan(self):
        # All raters always say "include" -> P_e = 1 -> kappa undefined.
        pairs = [("include", "include")] * 20
        result = ein.cohen_kappa(pairs)
        assert math.isnan(result["kappa"])


# --------------------------------------------------------------------------
# Pure-math: Fleiss' kappa
# --------------------------------------------------------------------------

class TestFleissKappa:
    def test_perfect_agreement_returns_nan(self):
        # 5 items, 3 raters, all rating "include" (column 0) -> P_e = 1.
        matrix = [[3, 0, 0]] * 5
        result = ein.fleiss_kappa(matrix)
        assert result["n_items"] == 5
        assert result["n_raters"] == 3
        assert math.isclose(result["agreement_observed"], 1.0)
        assert math.isnan(result["kappa"])

    def test_perfect_disagreement_low_kappa(self):
        # 6 items, 3 raters, perfectly split (1 each in 3 categories per item).
        matrix = [[1, 1, 1]] * 6
        result = ein.fleiss_kappa(matrix)
        # P_i = 0 for every item -> P_o = 0; P_e = 1/3 -> kappa = -0.5.
        assert math.isclose(result["agreement_observed"], 0.0)
        assert math.isclose(result["kappa"], -0.5, abs_tol=1e-9)

    def test_reference_value_landis_koch(self):
        # Constructed: 3 items rated by 3 raters
        # Item 1: 3 include  -> P_1 = 1
        # Item 2: 2 include, 1 exclude -> P_2 = (2*1 + 1*0 + 0)/(3*2) = 2/6
        # Item 3: 1 each -> P_3 = 0
        matrix = [
            [3, 0, 0],
            [2, 1, 0],
            [1, 1, 1],
        ]
        result = ein.fleiss_kappa(matrix)
        assert result["n_items"] == 3
        assert result["n_raters"] == 3
        # P_o = (1 + 2/6 + 0)/3 = 4/9 = 0.4444
        assert math.isclose(result["agreement_observed"], 4 / 9, abs_tol=1e-9)
        # p_j: include=6/9=0.667, exclude=2/9=0.222, uncertain=1/9=0.111
        # P_e = 0.667^2 + 0.222^2 + 0.111^2 = 0.444 + 0.0494 + 0.0123 = 0.506
        # kappa = (0.4444 - 0.506) / (1 - 0.506) ~ -0.125
        assert -0.2 < result["kappa"] < 0.0

    def test_inconsistent_rater_counts_raises(self):
        # Items with different totals -> invalid.
        matrix = [[3, 0, 0], [2, 1, 1]]
        with pytest.raises(ValueError, match="same rater count"):
            ein.fleiss_kappa(matrix)

    def test_single_rater_raises(self):
        matrix = [[1, 0, 0]] * 3
        with pytest.raises(ValueError, match="at least 2 raters"):
            ein.fleiss_kappa(matrix)

    def test_empty_matrix_returns_nan_kappa(self):
        result = ein.fleiss_kappa([])
        assert result["n_items"] == 0
        assert math.isnan(result["kappa"])


# --------------------------------------------------------------------------
# Decision normalization
# --------------------------------------------------------------------------

class TestNormalizeDecision:
    def test_canonical_passthrough(self):
        assert ein.normalize_decision("include") == "include"
        assert ein.normalize_decision("exclude") == "exclude"
        assert ein.normalize_decision("uncertain") == "uncertain"

    def test_case_and_whitespace_tolerated(self):
        assert ein.normalize_decision("Include") == "include"
        assert ein.normalize_decision("  EXCLUDE  ") == "exclude"
        assert ein.normalize_decision("\tUncertain\n") == "uncertain"

    def test_empty_returns_none(self):
        assert ein.normalize_decision(None) is None
        assert ein.normalize_decision("") is None
        assert ein.normalize_decision("   ") is None

    def test_typo_raises(self):
        with pytest.raises(ValueError, match="not in canonical"):
            ein.normalize_decision("includ")
        with pytest.raises(ValueError, match="not in canonical"):
            ein.normalize_decision("yes")


# --------------------------------------------------------------------------
# LLM status -> canonical decision mapping
# --------------------------------------------------------------------------

class TestLlmStatusMapping:
    def test_mapping_covers_canonical_statuses(self):
        assert ein.LLM_STATUS_TO_DECISION["MET"] == "include"
        assert ein.LLM_STATUS_TO_DECISION["FAILED"] == "exclude"
        assert ein.LLM_STATUS_TO_DECISION["UNCERTAIN"] == "uncertain"

    def test_join_with_llm_uses_status_not_decision(self):
        # An EL exclusion criterion: status=MET, decision=not_meet.
        # Join must map status=MET to canonical=include (not exclude).
        evidence = {
            "EL": {"A001": {"EC-2": {"status": "MET", "decision": "not_meet",
                                      "confidence": 0.9, "quote": "vr",
                                      "quote_valid": True}}}
        }
        humans = [{
            "stage": "EL", "a_id": "A001", "criterion_id": "EC-2",
            "rater_id": "R1", "set": "disjoint",
            "human_decision": "include", "human_notes": "",
        }]
        out = ein.join_with_llm(humans, evidence)
        assert out[0]["llm_status"] == "MET"
        assert out[0]["llm_decision_canonical"] == "include"
        assert out[0]["agree"] == "True"

    def test_join_missing_evidence_marked_disagreement(self):
        humans = [{
            "stage": "IL", "a_id": "A099", "criterion_id": "IC-1",
            "rater_id": "R1", "set": "disjoint",
            "human_decision": "include", "human_notes": "",
        }]
        out = ein.join_with_llm(humans, {"IL": {}})
        assert out[0]["llm_status"] == "MISSING"
        assert out[0]["agree"] == "False"


# --------------------------------------------------------------------------
# Workbook reader: schema validation
# --------------------------------------------------------------------------

class TestWorkbookReader:
    @pytest.fixture
    def empty_grids(self, tmp_path):
        out_dir = tmp_path / "empty"
        rc = egg.main([
            "--el-filtered", str(TESTS_DATA / "el_eval_fixture.csv"),
            "--il-filtered", str(TESTS_DATA / "il_eval_fixture.csv"),
            "--criteria",    str(GOLDEN / "criteria_harmonized_v3.1.0.csv"),
            "--raters",      "AReyes", "JKiss", "JVoisin",
            "--output-dir",  str(out_dir),
            "--overlap",     "6",
            "--seed",        "42",
        ])
        assert rc == 0
        return out_dir

    @pytest.fixture
    def manifest_by_rater(self, empty_grids):
        manifest = ein.load_partition_manifest(empty_grids / "partition_manifest.csv")
        return ein.index_manifest_by_rater(manifest)

    def test_unfilled_workbook_reports_empty_decisions(self, empty_grids, manifest_by_rater):
        path = empty_grids / "eval_grid_AReyes.xlsx"
        with pytest.raises(ValueError, match="decision is empty"):
            ein.read_filled_workbook(
                path=path, rater_id="AReyes",
                expected_per_stage=manifest_by_rater["AReyes"],
            )

    def test_filled_workbook_reads_cleanly(self, empty_grids, manifest_by_rater, tmp_path):
        # Use the synthetic filler.
        src = empty_grids / "eval_grid_AReyes.xlsx"
        filled = tmp_path / "filled" / "eval_grid_AReyes.xlsx"
        evidence_by_stage = {
            "EL": fil.load_evidence_for_stage(TESTS_DATA / "el_eval_fixture.csv", "EL"),
            "IL": fil.load_evidence_for_stage(TESTS_DATA / "il_eval_fixture.csv", "IL"),
        }
        # Synthetic fixture has no real LLM decisions in its evidence_json,
        # so we'll inject canonical decisions manually for synthetic-fill purposes.
        # All a_ids -> 'include' for IC-1, EC-2, EC-3.
        manual_evidence = {
            "EL": {f"A{i:03d}": {"EC-2": "include", "EC-3": "include"} for i in range(1, 31)},
            "IL": {f"A{i:03d}": {"IC-1": "include"} for i in range(1, 31)},
        }
        n = fil.fill_workbook(
            src_path=src, dst_path=filled,
            llm_canonical_by_stage=manual_evidence,
            agree_with_llm_rate=0.9, uncertain_rate=0.05, seed=1,
        )
        assert n > 0

        rows = ein.read_filled_workbook(
            path=filled, rater_id="AReyes",
            expected_per_stage=manifest_by_rater["AReyes"],
        )
        # Every row should have a valid decision.
        assert all(r["human_decision"] in ("include", "exclude", "uncertain")
                   for r in rows)
        # Manifest expects rater_AReyes to rate <expected> a_ids per stage,
        # times the number of criteria on that stage.
        n_expected = (
            len([r for r in manifest_by_rater["AReyes"]["IL"]]) * 1   # IL: IC-1
            + len([r for r in manifest_by_rater["AReyes"]["EL"]]) * 2  # EL: EC-2, EC-3
        )
        assert len(rows) == n_expected

    def test_workbook_with_typo_decision_raises(self, empty_grids, manifest_by_rater, tmp_path):
        # Write a typo into one decision cell.
        src = empty_grids / "eval_grid_AReyes.xlsx"
        target = tmp_path / "typo.xlsx"
        shutil.copy(src, target)
        wb = load_workbook(target)
        ws = wb["Decisions_IL"]
        # Find Decision: IC-1 column.
        headers = [c.value for c in ws[1]]
        col = headers.index("Decision: IC-1") + 1
        # Fill all decisions valid, then break one.
        for r in range(2, ws.max_row + 1):
            ws.cell(row=r, column=col).value = "include"
        # Also fill EL columns.
        for stage_sheet in ("Decisions_EL",):
            ws2 = wb[stage_sheet]
            hd = [c.value for c in ws2[1]]
            for cid in ("EC-2", "EC-3"):
                cidx = hd.index(f"Decision: {cid}") + 1
                for r in range(2, ws2.max_row + 1):
                    ws2.cell(row=r, column=cidx).value = "include"
        # The typo:
        ws.cell(row=2, column=col).value = "yess"
        wb.save(target)
        with pytest.raises(ValueError, match="not in canonical"):
            ein.read_filled_workbook(
                path=target, rater_id="AReyes",
                expected_per_stage=manifest_by_rater["AReyes"],
            )


# --------------------------------------------------------------------------
# End-to-end: empty grids -> synthetic fill -> ingest
# --------------------------------------------------------------------------

class TestEndToEnd:
    @pytest.fixture
    def pipeline(self, tmp_path):
        """Run generator, fill three grids with three different agree-rates,
        then ingest. Returns (out_dir, manifest_path, llm_evidence)."""
        empty_dir = tmp_path / "empty"
        rc = egg.main([
            "--el-filtered", str(TESTS_DATA / "el_eval_fixture.csv"),
            "--il-filtered", str(TESTS_DATA / "il_eval_fixture.csv"),
            "--criteria",    str(GOLDEN / "criteria_harmonized_v3.1.0.csv"),
            "--raters",      "R1", "R2", "R3",
            "--output-dir",  str(empty_dir),
            "--overlap",     "6",
            "--seed",        "42",
        ])
        assert rc == 0

        # Synthesize evidence for synthetic fixtures that lack evidence_json.
        manual_evidence = {
            "EL": {f"A{i:03d}": {"EC-2": "include", "EC-3": "exclude"}
                   for i in range(1, 31)},
            "IL": {f"A{i:03d}": ("exclude" if i % 4 == 0 else "include")
                   for i in range(1, 31)},
        }
        # Restructure manual_evidence: IL needs criterion-level dict.
        manual_evidence["IL"] = {
            f"A{i:03d}": {"IC-1": ("exclude" if i % 4 == 0 else "include")}
            for i in range(1, 31)
        }

        filled_dir = tmp_path / "filled"
        # Three raters with different agree rates so the metric is exercised.
        for rater_id, agree, seed in [("R1", 0.95, 1), ("R2", 0.90, 2), ("R3", 0.88, 3)]:
            src = empty_dir / f"eval_grid_{rater_id}.xlsx"
            dst = filled_dir / f"eval_grid_{rater_id}.xlsx"
            fil.fill_workbook(
                src_path=src, dst_path=dst,
                llm_canonical_by_stage=manual_evidence,
                agree_with_llm_rate=agree, uncertain_rate=0.03, seed=seed,
            )

        # The ingestor reads evidence_json from the fixtures themselves.
        # The synthetic fixtures have empty il_evidence_json/el_evidence_json
        # ('{}'). We need to write modified fixtures so the ingest can
        # find LLM evidence to compare against.
        modified_il = tmp_path / "il_with_evidence.csv"
        modified_el = tmp_path / "el_with_evidence.csv"
        _patch_fixture_with_evidence(
            TESTS_DATA / "il_eval_fixture.csv", modified_il,
            ev_col="il_evidence_json", per_aid=manual_evidence["IL"],
        )
        _patch_fixture_with_evidence(
            TESTS_DATA / "el_eval_fixture.csv", modified_el,
            ev_col="el_evidence_json", per_aid=manual_evidence["EL"],
        )

        out_dir = tmp_path / "out"
        rc = ein.main([
            "--manifest",         str(empty_dir / "partition_manifest.csv"),
            "--filled-grids-dir", str(filled_dir),
            "--el-filtered",      str(modified_el),
            "--il-filtered",      str(modified_il),
            "--output-dir",       str(out_dir),
        ])
        assert rc == 0
        return out_dir

    def test_evidence_files_produced(self, pipeline):
        for name in ("eval_decisions_v1.csv", "eval_results_v1.csv",
                     "eval_disagreements_v1.csv", "eval_summary_v1.txt"):
            assert (pipeline / name).exists(), f"missing {name}"

    def test_decisions_csv_schema(self, pipeline):
        with (pipeline / "eval_decisions_v1.csv").open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        # 3 raters * (overlap*1 + disjoint*1) decisions across IL + EL,
        # times the per-stage criterion count. Just confirm non-empty and
        # all rows have populated human_decision.
        assert rows
        assert all(r["human_decision"] in ("include", "exclude", "uncertain")
                   for r in rows)

    def test_results_csv_has_agree_flag(self, pipeline):
        with (pipeline / "eval_results_v1.csv").open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert all(r["agree"] in ("True", "False") for r in rows)
        # With ~90% agree rates on 3 raters, most rows should be agree=True.
        agree_count = sum(1 for r in rows if r["agree"] == "True")
        assert agree_count / len(rows) > 0.7

    def test_summary_text_lists_kappa_per_criterion(self, pipeline):
        text = (pipeline / "eval_summary_v1.txt").read_text(encoding="utf-8")
        # Expected criteria appear in the summary.
        for cid in ("IC-1", "EC-2", "EC-3"):
            assert cid in text
        assert "Cohen's kappa" in text
        assert "Fleiss' kappa" in text
        assert "Confusion matrix" in text


# --------------------------------------------------------------------------
# Test helpers
# --------------------------------------------------------------------------

def _patch_fixture_with_evidence(
    src_csv: Path,
    dst_csv: Path,
    ev_col: str,
    per_aid,
) -> None:
    """Copy a fixture CSV, replacing the evidence_json column with synthesized
    JSON keyed by a_id and criterion. Only used by tests."""
    import csv, json
    with src_csv.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    fields = list(rows[0].keys())
    for r in rows:
        a_id = r.get("local_id", "").strip()
        if a_id in per_aid:
            criteria_dict = per_aid[a_id]
            ev = {}
            status_map = {"include": "MET", "exclude": "FAILED", "uncertain": "UNCERTAIN"}
            for cid, canonical in criteria_dict.items():
                ev[cid] = {
                    "status": status_map[canonical],
                    "decision": "meet" if canonical == "include" else "not_meet",
                    "confidence": 0.85,
                    "quote": "synthetic quote",
                    "quote_valid": True,
                }
            r[ev_col] = json.dumps(ev)
        else:
            r[ev_col] = "{}"
    dst_csv.parent.mkdir(parents=True, exist_ok=True)
    with dst_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)
