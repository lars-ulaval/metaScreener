# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_final_report.py — the ScreenA_Report.xlsx workbook (F-69, F-70).

The workbook is the pipeline's final deliverable and had no test, which is
how both defects survived:

  F-69  The four stage sheets were built from CONTRACT_STAGE_SHEET_COLS
        while the row builder (_extract_contract_stage_row) emitted an
        entirely different key set — 2 of 7 names intersected, so five
        columns could never be populated and every data cell read back
        None. Row counts were right, which is why nobody noticed.

  F-70  The FINAL sheet's metadata columns come from _load_master_rows,
        whose fallback chain ends at data/current.csv — the terminal
        survivor set — because nothing ever wrote the pre-screening
        snapshot it looks for first. Every record excluded before IL
        appeared with the right verdict and no title.

The workbook builder is pure (zipfile in, bytes out); no Tk object is
involved. Fixtures follow the headless approach of
docs/internal/diagnostic/05_report_production.md.
"""
import io
import json
import zipfile

import pytest

from conftest import get_il

openpyxl = pytest.importorskip("openpyxl")


CORPUS_HEADER = "local_id,title,abstract,keywords"
CORPUS = {
    "R1": ("Kept to the end", "abstract one", "kw1"),
    "R2": ("Excluded at EL", "abstract two", "kw2"),
    "R3": ("Excluded at IH", "abstract three", "kw3"),
    "R4": ("Excluded at EH", "abstract four", "kw4"),
}


def _corpus_csv(ids):
    lines = [CORPUS_HEADER]
    for rid in ids:
        t, a, k = CORPUS[rid]
        lines.append(f"{rid},{t},{a},{k}")
    return "\n".join(lines) + "\n"


def _stage_full_csv(stage, outcomes):
    """A minimal but shape-correct reports/{STAGE}_FULL.csv."""
    sl = stage.lower()
    lines = [f"{CORPUS_HEADER},{sl}_outcome,{sl}_failed_ids,"
             f"{sl}_missing_ids,{sl}_met_ids,{sl}_reason_summary"]
    for rid, outcome in outcomes.items():
        t, a, k = CORPUS[rid]
        failed = f"{stage}-X" if outcome == "OUT" else ""
        reason = (f"OUT: failed {stage}-X" if outcome == "OUT"
                  else f"All {stage} criteria met.")
        lines.append(f"{rid},{t},{a},{k},{outcome},{failed},,,{reason}")
    return "\n".join(lines) + "\n"


def _il_full_rows():
    t, a, k = CORPUS["R1"]
    return [{
        "local_id": "R1", "title": t, "abstract": a, "keywords": k,
        "il_outcome": "PASS_CLEAN", "il_failed_ids": "", "il_missing_ids": "",
        "il_met_ids": "IL-1", "il_uncertain_ids": "",
        "il_reason_summary": "PASS_CLEAN: all IL criteria MET.",
        "il_evidence_json": "{}",
    }]


def _mini_bundle(tmp_path, *, with_original):
    """The bundle as IL sees it: EH excluded R4, IH excluded R3, EL
    excluded R2; data/current.csv is the EL survivor set."""
    zp = tmp_path / "post_el.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("manifest.json", json.dumps({}))
        zf.writestr("data/current.csv", _corpus_csv(["R1"]))
        if with_original:
            zf.writestr("data/original.csv",
                        _corpus_csv(["R1", "R2", "R3", "R4"]))
        zf.writestr("reports/EH_FULL.csv", _stage_full_csv("EH", {
            "R1": "PASS_CLEAN", "R2": "PASS_CLEAN",
            "R3": "PASS_CLEAN", "R4": "OUT"}))
        zf.writestr("reports/IH_FULL.csv", _stage_full_csv("IH", {
            "R1": "PASS_CLEAN", "R2": "PASS_CLEAN", "R3": "OUT"}))
        zf.writestr("reports/EL_FULL.csv", _stage_full_csv("EL", {
            "R1": "PASS_CLEAN", "R2": "OUT"}))
    return zp


def _build_workbook(zp):
    il = get_il()
    with zipfile.ZipFile(zp, "r") as zf:
        return openpyxl.load_workbook(io.BytesIO(
            il._build_final_report_xlsx_bytes(zf, "", _il_full_rows())))


def _sheet_dicts(ws):
    rows = list(ws.values)
    header = list(rows[0])
    return header, [dict(zip(header, r)) for r in rows[1:]]


class TestStageSheetsCarryData:
    """F-69: every stage-sheet column has a data source and is populated
    wherever the underlying stage report has the value."""

    def test_header_is_the_row_builders_schema(self):
        il = get_il()
        import sys
        ui = sys.modules["plugins.07_il.ui"]
        built = ui._extract_contract_stage_row(
            "EH", {"local_id": "R9", "eh_outcome": "OUT",
                   "eh_failed_ids": "EH-X", "eh_reason_summary": "OUT"})
        assert set(built.keys()) == set(il.CONTRACT_STAGE_SHEET_COLS), (
            "F-69: the sheet header and the row builder must share one "
            "schema — they intersected in 2 of 7 names, so five columns "
            "could never be populated."
        )

    def test_no_column_without_a_data_source(self):
        """decided_at had no producer anywhere; history was written as ""
        at every call site. Neither may ship as a permanently empty
        column."""
        il = get_il()
        assert "decided_at" not in il.CONTRACT_STAGE_SHEET_COLS
        assert "history" not in il.CONTRACT_STAGE_SHEET_COLS

    def test_every_stage_sheet_cell_is_populated(self, tmp_path):
        wb = _build_workbook(_mini_bundle(tmp_path, with_original=True))
        expected_counts = {"EH": 4, "IH": 3, "EL": 2, "IL": 1}
        for stage, n in expected_counts.items():
            header, rows = _sheet_dicts(wb[stage])
            assert len(rows) == n
            for r in rows:
                assert r.get("a_id"), (
                    f"F-69: {stage} sheet row has no a_id — the header and "
                    f"row builder do not line up (row: {r})."
                )
                assert r.get("stage") == stage
                assert r.get("stage_outcome")
                assert r.get("stage_reason_summary")
                assert r.get("passed_to_next") in ("true", "false")

    def test_out_rows_carry_their_failed_ids(self, tmp_path):
        wb = _build_workbook(_mini_bundle(tmp_path, with_original=True))
        _h, rows = _sheet_dicts(wb["EH"])
        out = [r for r in rows if r["stage_outcome"] == "OUT"]
        assert out and all(r.get("failed_criteria_ids") for r in out)

    def test_final_sheet_outcomes_are_intact(self, tmp_path):
        """The FINAL sheet was always right about outcomes; the fix must
        not disturb it."""
        wb = _build_workbook(_mini_bundle(tmp_path, with_original=True))
        _h, rows = _sheet_dicts(wb["FINAL"])
        by_id = {r["a_id"]: r for r in rows}
        assert by_id["R4"]["final_outcome"] == "OUT"
        assert by_id["R4"]["final_reason_summary"] == "OUT at EH"
        assert by_id["R3"]["final_reason_summary"] == "OUT at IH"
        assert by_id["R2"]["final_reason_summary"] == "OUT at EL"
        assert by_id["R1"]["final_outcome"] in ("PASS_CLEAN", "REVIEW")
