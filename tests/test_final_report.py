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


# ---------------------------------------------------------------------------
# F-70: the FINAL sheet must cover the corpus, not the survivor set
# ---------------------------------------------------------------------------

def _run_real_pipeline_to_post_ih(tmp_path):
    """Real Harmoniser bundle export, then real EH and IH hops via the
    engine entry points (the headless approach of the diagnostic). EH
    excludes R4 (year 1990); IH excludes R3 (lang de)."""
    import csv as _csv
    import importlib
    import threading

    import conftest
    conftest.get_harmoniser()
    harm_bundle = importlib.import_module("plugins.03_harmoniser.bundle")

    from plugins._common.parser import (_decode_bytes, _load_criteria_from_text,
                                        _parse_csv_tolerant_text)
    from plugins._common.bundle import _export_next_bundle_zip, _load_bundle
    from plugins._common.runner import run_screen

    cols = ["local_id", "title", "abstract", "keywords", "year", "lang"]
    records = [
        {"local_id": "R1", "title": "Kept to the end", "abstract": "a1",
         "keywords": "k1", "year": "2021", "lang": "en"},
        {"local_id": "R2", "title": "Survives EH and IH", "abstract": "a2",
         "keywords": "k2", "year": "2022", "lang": "en"},
        {"local_id": "R3", "title": "Excluded at IH", "abstract": "a3",
         "keywords": "k3", "year": "2020", "lang": "de"},
        {"local_id": "R4", "title": "Excluded at EH", "abstract": "a4",
         "keywords": "k4", "year": "1990", "lang": "en"},
    ]
    corpus = tmp_path / "A.csv"
    with corpus.open("w", encoding="utf-8", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in records:
            w.writerow(r)

    crit = [
        {"stage": "EH", "id": "EC-1", "type": "exclude", "scope": "metadata",
         "label": "old", "operator": "lte", "target": "year",
         "what": ["1999"], "threshold": "", "enabled": True,
         "source_text": "Exclude pre-2000"},
        {"stage": "IH", "id": "IC-1", "type": "include", "scope": "metadata",
         "label": "lang", "operator": "in_list", "target": "lang",
         "what": ["en"], "threshold": "", "enabled": True,
         "source_text": "Include English"},
    ]
    z0 = str(tmp_path / "b0.zip")
    harm_bundle.export_screen_a_bundle(
        rows=crit, a_path=str(corpus), a_columns=cols,
        a_id_col_guess="local_id", criteria_path="c.csv",
        criteria_kind="csv", criteria_source_text="synthetic",
        zip_out_path=z0)

    def hop(stage, zin, zout):
        b = _load_bundle(str(zin))
        with zipfile.ZipFile(zin) as zf:
            data_text = _decode_bytes(
                zf.read(b.root + "data/current.csv"))
            crit_text = _decode_bytes(
                zf.read(b.root + "criteria/criteria_harmonized.csv"))
        pr = _parse_csv_tolerant_text(data_text, required_id="local_id")
        cr = _load_criteria_from_text(crit_text, stage=stage)
        full, surv, counts, _i, _e, _c = run_screen(
            pr, cr, threading.Event(), None, stage=stage)
        _export_next_bundle_zip(
            str(zout), b, "data/current.csv",
            "criteria/criteria_harmonized.csv", None, pr.header, full, surv,
            pr.skipped, counts, stage=stage)

    z1 = tmp_path / "b1_eh.zip"
    z2 = tmp_path / "b2_ih.zip"
    hop("EH", z0, z1)
    hop("IH", z1, z2)
    return z2


class TestHarmoniserWritesTheOriginalSnapshot:
    """F-70, first half: nothing in the pipeline ever wrote the
    pre-screening snapshot _load_master_rows looks for, so the FINAL
    sheet's 'master list' was always the terminal survivor set."""

    def _bundle(self, tmp_path):
        import importlib
        import conftest
        conftest.get_harmoniser()
        harm_bundle = importlib.import_module("plugins.03_harmoniser.bundle")
        corpus = tmp_path / "A.csv"
        corpus.write_text(
            "local_id,title\nR1,alpha\nR2,beta\n", encoding="utf-8")
        z0 = str(tmp_path / "b0.zip")
        harm_bundle.export_screen_a_bundle(
            rows=[], a_path=str(corpus), a_columns=["local_id", "title"],
            a_id_col_guess="local_id", criteria_path="c.csv",
            criteria_kind="csv", criteria_source_text="x", zip_out_path=z0)
        return z0

    def test_original_csv_exists_and_matches_current(self, tmp_path):
        z0 = self._bundle(tmp_path)
        with zipfile.ZipFile(z0) as zf:
            names = zf.namelist()
            assert "ScreenA_Bundle/data/original.csv" in names, (
                "F-70: the Harmoniser must write the pre-screening snapshot "
                "the FINAL sheet's master-row loader looks for."
            )
            assert (zf.read("ScreenA_Bundle/data/original.csv")
                    == zf.read("ScreenA_Bundle/data/current.csv"))

    def test_original_csv_is_in_the_sha256_map(self, tmp_path):
        import hashlib
        z0 = self._bundle(tmp_path)
        with zipfile.ZipFile(z0) as zf:
            manifest = json.loads(zf.read("ScreenA_Bundle/manifest.json"))
            body = zf.read("ScreenA_Bundle/data/original.csv")
        assert manifest["sha256"].get("data/original.csv") == \
            hashlib.sha256(body).hexdigest()


class TestFinalSheetCoversTheCorpus:
    """F-70, second half: with the snapshot in the bundle, every corpus
    record on the FINAL sheet carries its metadata — including the ones
    excluded before IL."""

    def test_excluded_records_have_metadata(self, tmp_path):
        post_ih = _run_real_pipeline_to_post_ih(tmp_path)
        il = get_il()
        with zipfile.ZipFile(post_ih, "r") as zf:
            wb = openpyxl.load_workbook(io.BytesIO(
                il._build_final_report_xlsx_bytes(
                    zf, "ScreenA_Bundle/", [])))
        _h, rows = _sheet_dicts(wb["FINAL"])
        by_id = {r["a_id"]: r for r in rows}
        assert set(by_id) == {"R1", "R2", "R3", "R4"}
        for rid, title in (("R4", "Excluded at EH"),
                           ("R3", "Excluded at IH"),
                           ("R1", "Kept to the end")):
            assert by_id[rid].get("title") == title, (
                f"F-70: {rid} has no metadata on the FINAL sheet — the "
                f"master list fell back to the terminal survivor set "
                f"(got: {by_id[rid].get('title')!r})."
            )
        assert by_id["R4"]["final_reason_summary"] == "OUT at EH"
        assert by_id["R3"]["final_reason_summary"] == "OUT at IH"

    def test_old_bundles_keep_the_degraded_fallback(self, tmp_path):
        """A bundle written before this fix has no data/original.csv; the
        builder must still work, falling back to data/current.csv exactly
        as before. (The degraded metadata for excluded records is the
        documented cost of an old bundle.)"""
        wb = _build_workbook(_mini_bundle(tmp_path, with_original=False))
        _h, rows = _sheet_dicts(wb["FINAL"])
        assert {r["a_id"] for r in rows} == {"R1", "R2", "R3", "R4"}
