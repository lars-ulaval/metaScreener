# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
plugin.py — Screen A (IH-only) as a metaScreener tab plugin (Contract v2, IH stage)

UPDATED: Bundle-first input (Harmoniser ZIP)

✅ IH-only, self-contained (UI + engine)
✅ Expects a ScreenA bundle ZIP as input (produced by your harmoniser)
✅ Shows the IH criteria being applied (persistent left panel)
✅ Click-to-sort columns (full dataset; re-renders incrementally to keep UI responsive)
✅ Duplicate local_id: warn only (no enforcement)
✅ Row detail modal on double-click (recomputes per-criterion evaluation on demand)
✅ Criterion double-click filters reports to rows touched by that criterion (failed/missing/met/unknown)

IH semantics (same tags as EH; different assignment meaning)
- Per row, evaluate all IH criteria -> {MET, FAILED, MISSING, UNKNOWN}
- Outcome assignment:
    - OUT          if >=1 FAILED
    - PASS_FLAGGED if 0 FAILED and >=1 (MISSING or UNKNOWN)
    - PASS_CLEAN   if all MET
- Survivors = PASS_CLEAN + PASS_FLAGGED (forwarded to next stage bundle as data/current.csv)
- NOTE: In IH, OUT means "removed from pipeline after IH" (typically: confidently includable by heuristics).

Inputs (from bundle ZIP)
- data/current.csv (preferred)  [fallbacks supported: data/A.csv, data/aggregate.csv]
- criteria/criteria_harmonized.csv (preferred) [fallbacks supported: criteria/harmonized.csv, criteria/criteria.csv, criteria.csv]
- manifest.json (optional fields are OK; plugin will only warn if fields are missing)
Optional
- data/input_errors.csv (carried through; merged with any new parse skips)

Outputs
1) IH_FULL report (UI + export): all aggregate columns + outcome + reason columns
2) IH_SURVIVORS report (UI + export): survivors only (PASS_CLEAN + PASS_FLAGGED),
   in the exact same schema as the original aggregate input

Exports
- One XLSX with two sheets: IH_FULL, IH_SURVIVORS
- Optional input_errors.csv (skipped/invalid records)
- Next bundle ZIP (post-IH): survivors become new data/current.csv, manifest pipeline updated, and reports/ saved

Operator guardrails
- IH is heuristics-only. If a criterion uses operator "llm" (misconfig), it is treated as UNKNOWN (warn-only),
  and NEVER triggers any LLM call (same behavior spirit as EH).

Notes
- SHA256 checks are WARN-ONLY (never block the run).
"""

import csv
import io
import json
import re
import threading
import zipfile
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from metascreener.plugin_api import BasePlugin, PluginMeta

from plugins._common.parser import (
    # Constants
    TRUTHY,
    DOC_TYPE_MAP,
    LANG_MAP,
    # Dataclasses
    Criterion,
    ParseReport,
    CriteriaLoadReport,
    # Utility functions
    _safe_str,
    _truthy,
    _split_targets,
    _split_what_list,
    _norm_basic,
    _norm_doc_type,
    _norm_lang,
    _norm_for_target,
    _norm_what_for_target,
    _now_stamp,
    _iso_now,
    _sha256_hex,
    _decode_bytes,
    # CSV parsing
    _split_csv_records,
    _parse_csv_tolerant_text,
    _load_input_errors_from_text,
    # Criteria loading
    _load_criteria_from_text,
    _detect_contradictions_simple,
)

from plugins._common.evaluator import (
    _get_first_nonempty,
    _eval_criterion,
    _eval_criterion_detail as _eval_criterion_detail_common,
    _summarize_reason as _summarize_reason_common,
)

from plugins._common.exporters import (
    _export_input_errors_csv,
    _write_csv_bytes,
    _export_xlsx as _export_xlsx_common,
)

from plugins._common.bundle import (
    BundleInfo,
    _detect_bundle_root,
    _read_zip_bytes,
    _find_first_member,
    _load_bundle,
    _export_next_bundle_zip as _export_next_bundle_zip_common,
)


TAB_TITLE = "Screen A — IH"

MAX_UI_ROWS_HINT = 2000  # only used for status text; we render all rows incrementally
RENDER_CHUNK = 300
PROGRESS_EVERY_N = 200

def _load_criteria_ih_from_text(text: str) -> CriteriaLoadReport:
    """Backward-compat wrapper. Real implementation in plugins._common.parser."""
    return _load_criteria_from_text(text, stage="IH")


# ----------------------------
# IH evaluation (delegates to plugins._common.evaluator)
# ----------------------------

def _eval_criterion_detail(row: Dict[str, str], header_set: set, c: Criterion) -> Dict[str, str]:
    """Backward-compat wrapper. Real implementation in plugins._common.evaluator."""
    return _eval_criterion_detail_common(row, header_set, c, stage="IH")


def _summarize_reason(outcome: str, failed: List[str], missing: List[str], met: List[str], unknown: List[str]) -> str:
    """Backward-compat wrapper. Real implementation in plugins._common.evaluator."""
    return _summarize_reason_common(outcome, failed, missing, met, unknown, stage="IH")


def run_ih_screen(
    parse: ParseReport,
    criteria_report: CriteriaLoadReport,
    cancel_event: threading.Event,
    progress_cb: Optional[Callable[[float], None]] = None,
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], Dict[str, int], Dict[str, Dict[str, int]], List[Dict[str, List[str]]]]:
    """
    Returns:
      full_rows: aggregate row dicts + IH columns appended
      survivor_rows: original aggregate row dicts (no extra columns)
      counts: summary counts
      crit_impacts: {cid: {"failed":n, "missing":n, "met":n, "unknown":n}}
      row_eval_lists: list aligned with full_rows, each is {"failed":[...], "missing":[...], "met":[...], "unknown":[...]}
    """
    header_set = set(parse.header)
    rows = parse.rows
    crits = criteria_report.criteria

    counts = {
        "OUT": 0,
        "PASS_CLEAN": 0,
        "PASS_FLAGGED": 0,
        "SKIPPED_INVALID": len(parse.skipped),
        "TOTAL_INTEGRAL": len(rows),
        "TOTAL_INPUT_RECORDS_EX_HEADER": len(parse.rows) + len(parse.skipped),
    }

    crit_impacts: Dict[str, Dict[str, int]] = {c.cid: {"failed": 0, "missing": 0, "met": 0, "unknown": 0} for c in crits}

    full_rows: List[Dict[str, str]] = []
    survivors: List[Dict[str, str]] = []
    row_eval_lists: List[Dict[str, List[str]]] = []

    if not crits:
        for r in rows:
            if cancel_event.is_set():
                break
            fr = dict(r)
            fr["ih_outcome"] = "PASS_CLEAN"
            fr["ih_failed_ids"] = ""
            fr["ih_missing_ids"] = ""
            fr["ih_met_ids"] = ""
            fr["ih_reason_summary"] = "No active IH criteria: default PASS_CLEAN."
            full_rows.append(fr)
            survivors.append(dict(r))
            row_eval_lists.append({"failed": [], "missing": [], "met": [], "unknown": []})
        counts["PASS_CLEAN"] = len(survivors)
        if progress_cb:
            progress_cb(1.0)
        return full_rows, survivors, counts, crit_impacts, row_eval_lists

    n = len(rows)
    for idx, r in enumerate(rows, start=1):
        if cancel_event.is_set():
            break

        failed: List[str] = []
        missing: List[str] = []
        met: List[str] = []
        unknown: List[str] = []

        for c in crits:
            status = _eval_criterion(r, header_set, c)
            if status == "FAILED":
                failed.append(c.cid)
                crit_impacts[c.cid]["failed"] += 1
            elif status == "MISSING":
                missing.append(c.cid)
                crit_impacts[c.cid]["missing"] += 1
            elif status == "MET":
                met.append(c.cid)
                crit_impacts[c.cid]["met"] += 1
            else:
                unknown.append(c.cid)
                crit_impacts[c.cid]["unknown"] += 1

        # IH outcome assignment (as requested)
        if failed:
            outcome = "OUT"
            counts["OUT"] += 1
        else:
            if unknown or missing:
                outcome = "PASS_FLAGGED"
                counts["PASS_FLAGGED"] += 1
            else:
                outcome = "PASS_CLEAN"
                counts["PASS_CLEAN"] += 1

        fr = dict(r)
        fr["ih_outcome"] = outcome
        fr["ih_failed_ids"] = ";".join(failed)
        fr["ih_missing_ids"] = ";".join(missing + unknown)  # keep one column for "non-deterministic/absent"
        fr["ih_met_ids"] = ";".join(met)
        fr["ih_reason_summary"] = _summarize_reason(outcome, failed, missing, met, unknown)

        full_rows.append(fr)
        row_eval_lists.append({"failed": failed, "missing": missing, "met": met, "unknown": unknown})

        # Survivors are those that continue to next stage
        if outcome != "OUT":
            survivors.append(dict(r))

        if progress_cb and (idx % PROGRESS_EVERY_N == 0 or idx == n):
            progress_cb(idx / max(1, n))

    return full_rows, survivors, counts, crit_impacts, row_eval_lists


# ----------------------------
# Export helpers (delegate to plugins._common.exporters)
# ----------------------------

def _export_xlsx(path: str, full_rows: List[Dict[str, str]], survivors: List[Dict[str, str]], aggregate_header: List[str]) -> None:
    """Backward-compat wrapper. Real implementation in plugins._common.exporters."""
    return _export_xlsx_common(path, full_rows, survivors, aggregate_header, stage="IH")


def _export_next_bundle_zip(
    out_zip_path: str,
    bundle: BundleInfo,
    data_rel: str,
    criteria_rel: str,
    input_errors_rel: Optional[str],
    parse_header: List[str],
    full_rows: List[Dict[str, str]],
    survivors: List[Dict[str, str]],
    skipped: List[Tuple[int, str, str]],
    counts: Dict[str, int],
) -> None:
    """Backward-compat wrapper. Real implementation in plugins._common.bundle."""
    return _export_next_bundle_zip_common(
        out_zip_path, bundle, data_rel, criteria_rel, input_errors_rel,
        parse_header, full_rows, survivors, skipped, counts,
        stage="IH",
    )


# ----------------------------
# UI Components
# ----------------------------

class DataTable(ttk.Frame):
    """
    Treeview wrapper with:
    - column setup
    - click-to-sort (requests sort callback)
    - incremental rendering to keep UI responsive
    - double-click callback to open details
    """
    def __init__(self, parent, on_sort: Callable[[str], None], on_row_activate: Optional[Callable[[Dict[str, str]], None]] = None):
        super().__init__(parent)
        self.on_sort = on_sort
        self.on_row_activate = on_row_activate

        self.tree = ttk.Treeview(self, show="headings", selectmode="browse")
        self.vs = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.hs = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=self.vs.set, xscrollcommand=self.hs.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        self.vs.grid(row=0, column=1, sticky="ns")
        self.hs.grid(row=1, column=0, sticky="ew")

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.columns: List[str] = []
        self._render_token = 0
        self._iid_to_row: Dict[str, Dict[str, str]] = {}

        self.tree.bind("<Double-1>", self._on_double_click)

    def set_columns(self, cols: List[str]):
        self.columns = cols
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = cols
        for c in cols:
            self.tree.heading(c, text=c, command=lambda col=c: self.on_sort(col))
            self.tree.column(c, width=140, minwidth=90, stretch=False)

    def clear(self):
        self._render_token += 1
        self._iid_to_row.clear()
        self.tree.delete(*self.tree.get_children())

    def render_rows_incremental(self, rows: List[Dict[str, str]]):
        self.clear()
        token = self._render_token

        def _insert_chunk(start: int):
            if token != self._render_token:
                return
            end = min(start + RENDER_CHUNK, len(rows))
            for i in range(start, end):
                r = rows[i]
                iid = f"r{i}"
                self._iid_to_row[iid] = r
                vals = [_safe_str(r.get(c, "")) for c in self.columns]
                self.tree.insert("", "end", iid=iid, values=vals)
            if end < len(rows):
                self.after(1, lambda: _insert_chunk(end))

        self.after(0, lambda: _insert_chunk(0))

    def _on_double_click(self, _evt):
        if not self.on_row_activate:
            return
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        r = self._iid_to_row.get(iid)
        if r:
            self.on_row_activate(r)


# ----------------------------
# Main View
# ----------------------------

class IHView(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self.bundle_zip_path: Optional[str] = None
        self.bundle: Optional[BundleInfo] = None

        self.data_full_member: Optional[str] = None
        self.data_rel_used: Optional[str] = None
        self.criteria_full_member: Optional[str] = None
        self.criteria_rel_used: Optional[str] = None
        self.input_errors_full_member: Optional[str] = None
        self.input_errors_rel_used: Optional[str] = None

        self.parse_report: Optional[ParseReport] = None
        self.criteria_report: Optional[CriteriaLoadReport] = None

        self.full_rows: List[Dict[str, str]] = []
        self.survivors: List[Dict[str, str]] = []
        self.counts: Dict[str, int] = {}

        self.crit_impacts: Dict[str, Dict[str, int]] = {}
        self.row_evals_full: List[Dict[str, List[str]]] = []

        self.active_criterion_id: Optional[str] = None

        self._worker: Optional[threading.Thread] = None
        self._cancel = threading.Event()

        self.sort_full: Tuple[Optional[str], bool] = (None, True)
        self.sort_surv: Tuple[Optional[str], bool] = (None, True)
        self.sort_crit: Tuple[Optional[str], bool] = (None, True)

        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        btn_b = ttk.Button(top, text="Load ScreenA bundle ZIP…", command=self._pick_bundle)
        btn_b.grid(row=0, column=0, padx=(0, 8), pady=2, sticky="w")

        self.lbl_bundle = ttk.Label(top, text="(no bundle loaded)")
        self.lbl_bundle.grid(row=0, column=1, sticky="w")

        self.lbl_bundle_meta = ttk.Label(top, text="")
        self.lbl_bundle_meta.grid(row=1, column=1, sticky="w")

        actions = ttk.Frame(top)
        actions.grid(row=0, column=2, rowspan=2, padx=(10, 0), sticky="e")

        self.btn_run = ttk.Button(actions, text="Run IH", command=self._run_clicked, state="disabled")
        self.btn_run.grid(row=0, column=0, padx=4, pady=2, sticky="e")

        self.btn_cancel = ttk.Button(actions, text="Cancel", command=self._cancel_run, state="disabled")
        self.btn_cancel.grid(row=1, column=0, padx=4, pady=2, sticky="e")

        self.btn_export = ttk.Button(actions, text="Export XLSX…", command=self._export_clicked, state="disabled")
        self.btn_export.grid(row=0, column=1, padx=4, pady=2, sticky="e")

        self.btn_export_err = ttk.Button(actions, text="Export input_errors.csv…", command=self._export_errors_clicked, state="disabled")
        self.btn_export_err.grid(row=1, column=1, padx=4, pady=2, sticky="e")

        self.btn_export_bundle = ttk.Button(actions, text="Export next bundle ZIP…", command=self._export_bundle_clicked, state="disabled")
        self.btn_export_bundle.grid(row=0, column=2, padx=4, pady=2, sticky="e")

        top.columnconfigure(1, weight=1)

        prog = ttk.Frame(self)
        prog.pack(fill="x", padx=10, pady=(0, 8))

        self.pbar = ttk.Progressbar(prog, orient="horizontal", mode="determinate")
        self.pbar.pack(fill="x", expand=True, side="left")

        self.lbl_status = ttk.Label(prog, text="Ready.")
        self.lbl_status.pack(side="left", padx=10)

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=1)
        paned.add(right, weight=4)

        crit_box = ttk.Labelframe(left, text="IH Criteria (read-only)")
        crit_box.pack(fill="both", expand=True)

        self.criteria_table = DataTable(
            crit_box,
            on_sort=self._sort_criteria_table,
            on_row_activate=self._on_criterion_activated,
        )
        self.criteria_table.pack(fill="both", expand=True, padx=6, pady=6)

        cf = ttk.Frame(left)
        cf.pack(fill="x", pady=(6, 0))
        self.lbl_crit_filter = ttk.Label(cf, text="Criterion filter: (none)")
        self.lbl_crit_filter.pack(side="left")
        self.btn_clear_filter = ttk.Button(cf, text="Clear filter", command=self._clear_criterion_filter, state="disabled")
        self.btn_clear_filter.pack(side="right")

        warn_box = ttk.Labelframe(left, text="Notes / warnings")
        warn_box.pack(fill="both", expand=False, pady=(6, 0))

        self.txt_warn = tk.Text(warn_box, height=8, wrap="word")
        self.txt_warn.pack(fill="both", expand=True, padx=6, pady=6)
        self.txt_warn.configure(state="disabled")

        nb = ttk.Notebook(right)
        nb.pack(fill="both", expand=True)

        tab_full = ttk.Frame(nb)
        tab_surv = ttk.Frame(nb)
        nb.add(tab_full, text="IH Full report")
        nb.add(tab_surv, text="IH Survivors")

        self.full_table = DataTable(tab_full, on_sort=self._sort_full_table, on_row_activate=self._open_row_detail_modal)
        self.full_table.pack(fill="both", expand=True, padx=6, pady=6)

        self.surv_table = DataTable(tab_surv, on_sort=self._sort_surv_table, on_row_activate=self._open_row_detail_modal)
        self.surv_table.pack(fill="both", expand=True, padx=6, pady=6)

        self.lbl_counts = ttk.Label(self, text="")
        self.lbl_counts.pack(fill="x", padx=10, pady=(0, 10))

    # -------- helpers --------

    def _set_warnings(self, lines: Sequence[str]) -> None:
        self.txt_warn.configure(state="normal")
        self.txt_warn.delete("1.0", "end")
        self.txt_warn.insert("end", "\n".join(lines) if lines else "(none)")
        self.txt_warn.configure(state="disabled")

    def _refresh_counts_label(self):
        if not self.parse_report:
            self.lbl_counts.configure(text="")
            return
        pr = self.parse_report
        msg = f"Integral rows: {len(pr.rows)} | Skipped invalid: {len(pr.skipped)}"
        if self.counts:
            msg += (
                f" | OUT: {self.counts.get('OUT',0)}"
                f" | PASS_CLEAN: {self.counts.get('PASS_CLEAN',0)}"
                f" | PASS_FLAGGED: {self.counts.get('PASS_FLAGGED',0)}"
            )
        self.lbl_counts.configure(text=msg)

    def _detect_duplicate_local_ids(self, rows: List[Dict[str, str]]) -> Tuple[int, List[str]]:
        seen = set()
        dups = []
        for r in rows:
            lid = _safe_str(r.get("local_id", "")).strip()
            if not lid:
                continue
            if lid in seen:
                dups.append(lid)
            else:
                seen.add(lid)
        uniq = []
        s2 = set()
        for x in dups:
            if x not in s2:
                uniq.append(x)
                s2.add(x)
        return len(uniq), uniq[:10]

    # -------- bundle load --------

    def _pick_bundle(self):
        p = filedialog.askopenfilename(
            title="Select ScreenA bundle ZIP",
            filetypes=[("ZIP", "*.zip"), ("All files", "*.*")],
        )
        if not p:
            return
        self.bundle_zip_path = p
        self.lbl_bundle.configure(text=Path(p).name)
        self._load_bundle_inputs()

    def _load_bundle_inputs(self):
        if not self.bundle_zip_path:
            return

        warns: List[str] = []
        self.full_rows = []
        self.survivors = []
        self.counts = {}
        self.crit_impacts = {}
        self.row_evals_full = []
        self.active_criterion_id = None
        self.lbl_crit_filter.configure(text="Criterion filter: (none)")
        self.btn_clear_filter.configure(state="disabled")

        try:
            self.bundle = _load_bundle(self.bundle_zip_path)
        except Exception as e:
            self.bundle = None
            messagebox.showerror("Bundle load failed", str(e))
            return

        m = self.bundle.manifest
        schema = _safe_str(m.get("bundle_schema", m.get("schema", ""))).strip() or "unknown"
        created_at = _safe_str(m.get("created_at", "")).strip()
        created_by = _safe_str(m.get("created_by", "")).strip()
        stages = (m.get("pipeline", {}) or {}).get("stages", {}) or {}
        st_ih = _safe_str(stages.get("IH", "")).strip() or "unknown"
        self.lbl_bundle_meta.configure(text=f"schema={schema} | created_at={created_at} | created_by={created_by} | IH={st_ih}")

        root = self.bundle.root

        data_candidates = ["data/current.csv", "data/A.csv", "data/aggregate.csv"]
        crit_candidates = ["criteria/criteria_harmonized.csv", "criteria/harmonized.csv", "criteria/criteria.csv", "criteria.csv"]
        err_candidates = ["data/input_errors.csv", "input_errors.csv"]

        try:
            with zipfile.ZipFile(self.bundle_zip_path, "r") as zf:
                self.data_full_member, self.data_rel_used = _find_first_member(zf, root, data_candidates)
                self.criteria_full_member, self.criteria_rel_used = _find_first_member(zf, root, crit_candidates)

                data_bytes = zf.read(self.data_full_member)
                crit_bytes = zf.read(self.criteria_full_member)
                data_text = _decode_bytes(data_bytes)
                crit_text = _decode_bytes(crit_bytes)

                # Optional input_errors
                try:
                    self.input_errors_full_member, self.input_errors_rel_used = _find_first_member(zf, root, err_candidates)
                    err_text = _decode_bytes(zf.read(self.input_errors_full_member))
                    carried_skipped = _load_input_errors_from_text(err_text)
                except Exception:
                    self.input_errors_full_member = None
                    self.input_errors_rel_used = None
                    carried_skipped = []

                # SHA checks (warn only)
                sha_map = m.get("sha256", {}) or {}
                if isinstance(sha_map, dict):
                    if self.data_rel_used in sha_map:
                        exp = _safe_str(sha_map.get(self.data_rel_used, "")).strip()
                        got = _sha256_hex(data_bytes)
                        if exp and exp != got:
                            warns.append(f"[bundle] sha256 mismatch for {self.data_rel_used} (warn only).")
                    if self.criteria_rel_used in sha_map:
                        exp = _safe_str(sha_map.get(self.criteria_rel_used, "")).strip()
                        got = _sha256_hex(crit_bytes)
                        if exp and exp != got:
                            warns.append(f"[bundle] sha256 mismatch for {self.criteria_rel_used} (warn only).")

        except Exception as e:
            messagebox.showerror("Bundle read failed", str(e))
            return

        # Parse data CSV (still enforce local_id and handle malformed records)
        try:
            pr = _parse_csv_tolerant_text(data_text, required_id="local_id")
        except Exception as e:
            messagebox.showerror("Data CSV parse failed", str(e))
            return

        # Merge skipped: carried-forward first, then newly detected
        skipped_all: List[Tuple[int, str, str]] = []
        if carried_skipped:
            skipped_all.extend(carried_skipped)
        if pr.skipped:
            skipped_all.extend(pr.skipped)
        pr = ParseReport(header=pr.header, rows=pr.rows, skipped=skipped_all)
        self.parse_report = pr

        # Criteria (IH stage only)
        try:
            self.criteria_report = _load_criteria_ih_from_text(crit_text)
        except Exception as e:
            self.criteria_report = None
            messagebox.showerror("Criteria load failed", str(e))
            return

        # Manifest warnings passthrough
        for w in (m.get("warnings", []) or []):
            ws = _safe_str(w).strip()
            if ws:
                warns.append(f"[manifest] {ws}")

        if self.criteria_report:
            warns.extend(self.criteria_report.warnings)

        # Chosen file notes
        warns.append(f"[bundle] Using data file: {self.data_rel_used}")
        warns.append(f"[bundle] Using criteria file: {self.criteria_rel_used}")
        if self.input_errors_rel_used:
            warns.append(f"[bundle] Imported previous input_errors: {self.input_errors_rel_used} ({len(carried_skipped)} rows)")

        if "local_id" not in pr.header:
            warns.append("[data] Column 'local_id' not found in header (unexpected). Rows may be skipped.")

        ndup, examples = self._detect_duplicate_local_ids(pr.rows)
        if ndup > 0:
            warns.append(f"[data] Duplicate local_id detected: {ndup} unique duplicates (examples: {', '.join(examples)}). Policy: WARN ONLY.")

        self._set_warnings(warns)

        self.btn_run.configure(state="normal")
        self.btn_export_err.configure(state="normal" if pr.skipped else "disabled")
        self.btn_export.configure(state="disabled")
        self.btn_export_bundle.configure(state="disabled")

        self._refresh_criteria_table(pre_run=True)

        self.lbl_status.configure(text="Ready.")
        self._refresh_counts_label()

        self.full_table.clear()
        self.surv_table.clear()

    # -------- Criteria table --------

    def _refresh_criteria_table(self, pre_run: bool):
        crits = self.criteria_report.criteria if self.criteria_report else []

        cols = ["id", "type", "targets", "operator", "what", "status", "notes"]
        if not pre_run:
            cols += ["n_failed", "n_missing", "n_met", "n_unknown"]

        rows: List[Dict[str, str]] = []
        header_set = set(self.parse_report.header) if self.parse_report else set()

        for c in crits:
            status = "OK"
            notes = ""

            if not c.targets:
                status = "WARNING"
                notes = "missing target -> treated as MISSING (PASS_FLAGGED)"
            elif header_set and not any(t in header_set for t in c.targets):
                status = "WARNING"
                notes = f"missing column(s): {', '.join(c.targets)} -> treated as MISSING (PASS_FLAGGED)"

            op = (c.operator or "").strip().lower()
            if op in ("llm",):
                status = "WARNING"
                notes = (notes + " | " if notes else "") + "operator 'llm' not supported in IH -> UNKNOWN (PASS_FLAGGED)"
            elif op not in ("equals", "contains", "regex", "in_list", "not_in", "gte", "lte", "between"):
                status = "WARNING"
                notes = (notes + " | " if notes else "") + f"unknown operator '{op}' -> UNKNOWN (PASS_FLAGGED)"

            d: Dict[str, str] = {
                "id": c.cid,
                "type": c.ctype,
                "targets": ",".join(c.targets),
                "operator": c.operator,
                "what": c.what_raw,
                "status": status,
                "notes": notes,
            }

            if not pre_run:
                imp = self.crit_impacts.get(c.cid, {"failed": 0, "missing": 0, "met": 0, "unknown": 0})
                d["n_failed"] = str(imp.get("failed", 0))
                d["n_missing"] = str(imp.get("missing", 0))
                d["n_met"] = str(imp.get("met", 0))
                d["n_unknown"] = str(imp.get("unknown", 0))

            rows.append(d)

        self.criteria_table.set_columns(cols)
        col, asc = self.sort_crit
        if col:
            rows = self._sorted_rows(rows, col, asc)
        self.criteria_table.render_rows_incremental(rows)

    def _on_criterion_activated(self, row: Dict[str, str]):
        cid = _safe_str(row.get("id", "")).strip()
        if not cid:
            return
        self.active_criterion_id = cid
        self.lbl_crit_filter.configure(text=f"Criterion filter: {cid}")
        self.btn_clear_filter.configure(state="normal")
        self._refresh_reports_view()

    def _clear_criterion_filter(self):
        self.active_criterion_id = None
        self.lbl_crit_filter.configure(text="Criterion filter: (none)")
        self.btn_clear_filter.configure(state="disabled")
        self._refresh_reports_view()

    # -------- Sorting --------

    def _sorted_rows(self, rows: List[Dict[str, str]], col: str, asc: bool) -> List[Dict[str, str]]:
        sample = []
        for r in rows[:200]:
            v = _safe_str(r.get(col, "")).strip()
            if v != "":
                sample.append(v)
        num_hits = 0
        for v in sample[:50]:
            try:
                float(v)
                num_hits += 1
            except Exception:
                pass
        is_numeric = (len(sample) > 0 and num_hits >= max(3, int(0.7 * min(len(sample[:50]), 50))))

        def key_num(r: Dict[str, str]):
            v = _safe_str(r.get(col, "")).strip()
            try:
                return (0, float(v))
            except Exception:
                return (1, float("inf"))

        def key_txt(r: Dict[str, str]):
            return _safe_str(r.get(col, "")).strip().lower()

        key_fn = key_num if is_numeric else key_txt
        return sorted(rows, key=key_fn, reverse=not asc)

    def _toggle_sort(self, current: Tuple[Optional[str], bool], col: str) -> Tuple[str, bool]:
        cur_col, cur_asc = current
        if cur_col == col:
            return (col, not cur_asc)
        return (col, True)

    def _sort_criteria_table(self, col: str):
        self.sort_crit = self._toggle_sort(self.sort_crit, col)
        self._refresh_criteria_table(pre_run=(not bool(self.full_rows)))

    def _sort_full_table(self, col: str):
        self.sort_full = self._toggle_sort(self.sort_full, col)
        self._refresh_reports_view()

    def _sort_surv_table(self, col: str):
        self.sort_surv = self._toggle_sort(self.sort_surv, col)
        self._refresh_reports_view()

    # -------- Run / Cancel --------

    def _cancel_run(self):
        if self._worker and self._worker.is_alive():
            self._cancel.set()
            self.lbl_status.configure(text="Cancelling…")

    def _run_clicked(self):
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("IH running", "A run is already in progress.")
            return
        if not self.parse_report:
            messagebox.showwarning("Missing input", "Load a ScreenA bundle ZIP first.")
            return
        if not self.criteria_report:
            messagebox.showwarning("Missing input", "Bundle criteria could not be loaded.")
            return

        self._cancel.clear()
        self.pbar["value"] = 0
        self.lbl_status.configure(text="Running IH…")
        self.btn_run.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.btn_export.configure(state="disabled")
        self.btn_export_bundle.configure(state="disabled")

        self.full_rows = []
        self.survivors = []
        self.counts = {}
        self.crit_impacts = {}
        self.row_evals_full = []

        self.full_table.clear()
        self.surv_table.clear()

        def progress_cb(frac: float):
            self.after(0, lambda: self._update_progress(frac))

        def worker():
            try:
                full, surv, counts, impacts, row_evals = run_ih_screen(
                    self.parse_report,
                    self.criteria_report,
                    self._cancel,
                    progress_cb=progress_cb,
                )
                self.after(0, lambda: self._finish_run(full, surv, counts, impacts, row_evals))
            except Exception as e:
                self.after(0, lambda msg=str(e): self._run_failed(msg))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _update_progress(self, frac: float):
        frac = max(0.0, min(1.0, float(frac)))
        self.pbar["value"] = frac * 100.0

    def _run_failed(self, err: str):
        self.lbl_status.configure(text="Run failed.")
        self.btn_run.configure(state="normal")
        self.btn_cancel.configure(state="disabled")
        messagebox.showerror("IH run failed", err)

    def _finish_run(
        self,
        full: List[Dict[str, str]],
        surv: List[Dict[str, str]],
        counts: Dict[str, int],
        impacts: Dict[str, Dict[str, int]],
        row_evals: List[Dict[str, List[str]]],
    ):
        self.full_rows = full
        self.survivors = surv
        self.counts = counts
        self.crit_impacts = impacts
        self.row_evals_full = row_evals

        self.btn_run.configure(state="normal")
        self.btn_cancel.configure(state="disabled")
        self.btn_export.configure(state="normal")
        self.btn_export_bundle.configure(state="normal")

        self._refresh_criteria_table(pre_run=False)
        self._refresh_reports_view()

        note = ""
        if len(full) > MAX_UI_ROWS_HINT or len(surv) > MAX_UI_ROWS_HINT:
            note = " (rendering incrementally; export contains all rows.)"

        self.lbl_status.configure(
            text=f"Done. OUT={counts.get('OUT',0)} CLEAN={counts.get('PASS_CLEAN',0)} FLAGGED={counts.get('PASS_FLAGGED',0)}{note}"
        )
        self._refresh_counts_label()

    # -------- Reports rendering --------

    def _refresh_reports_view(self):
        if not self.parse_report:
            return

        full_cols = list(self.parse_report.header) + ["ih_outcome", "ih_failed_ids", "ih_missing_ids", "ih_met_ids", "ih_reason_summary"]
        surv_cols = list(self.parse_report.header)

        full_view = self.full_rows
        if self.active_criterion_id:
            cid = self.active_criterion_id
            filtered = []
            for i, r in enumerate(self.full_rows):
                ev = self.row_evals_full[i] if i < len(self.row_evals_full) else {"failed": [], "missing": [], "met": [], "unknown": []}
                if (cid in ev["failed"]) or (cid in ev["missing"]) or (cid in ev["met"]) or (cid in ev["unknown"]):
                    filtered.append(r)
            full_view = filtered

        surv_view = self.survivors
        if self.active_criterion_id and self.full_rows:
            cid = self.active_criterion_id
            touched_survivor_ids = set()
            for i, r in enumerate(self.full_rows):
                if r.get("ih_outcome") == "OUT":
                    continue
                ev = self.row_evals_full[i]
                if (cid in ev["failed"]) or (cid in ev["missing"]) or (cid in ev["met"]) or (cid in ev["unknown"]):
                    touched_survivor_ids.add(_safe_str(r.get("local_id", "")).strip())
            surv_view = [r for r in self.survivors if _safe_str(r.get("local_id", "")).strip() in touched_survivor_ids]

        col, asc = self.sort_full
        if col and full_view:
            full_view = self._sorted_rows(full_view, col, asc)

        col2, asc2 = self.sort_surv
        if col2 and surv_view:
            surv_view = self._sorted_rows(surv_view, col2, asc2)

        self.full_table.set_columns(full_cols)
        self.full_table.render_rows_incremental(full_view)

        self.surv_table.set_columns(surv_cols)
        self.surv_table.render_rows_incremental(surv_view)

    # -------- Row detail modal --------

    def _open_row_detail_modal(self, row: Dict[str, str]):
        if not self.criteria_report or not self.parse_report:
            return

        win = tk.Toplevel(self)
        win.title("IH Row details")
        win.geometry("900x600")
        win.transient(self.winfo_toplevel())
        win.grab_set()

        lid = _safe_str(row.get("local_id", "")).strip()
        title = _safe_str(row.get("title", "")).strip() or _safe_str(row.get("Title", "")).strip()

        top = ttk.Frame(win)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text=f"local_id: {lid}").pack(anchor="w")
        if title:
            ttk.Label(top, text=f"title: {title[:250]}").pack(anchor="w")

        outcome = _safe_str(row.get("ih_outcome", "")).strip()
        if outcome:
            ttk.Label(top, text=f"IH outcome: {outcome}").pack(anchor="w")
            rs = _safe_str(row.get("ih_reason_summary", "")).strip()
            if rs:
                ttk.Label(top, text=f"summary: {rs}").pack(anchor="w")

        box = ttk.Labelframe(win, text="Per-criterion evaluation (recomputed)")
        box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        cols = ["cid", "type", "operator", "targets", "what", "status", "target_used", "norm_value", "note"]
        table = DataTable(box, on_sort=lambda _c: None, on_row_activate=None)
        table.pack(fill="both", expand=True, padx=6, pady=6)
        table.set_columns(cols)

        header_set = set(self.parse_report.header)
        crits = self.criteria_report.criteria

        detail_rows: List[Dict[str, str]] = []
        for c in crits:
            detail_rows.append(_eval_criterion_detail(row, header_set, c))

        table.render_rows_incremental(detail_rows)

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")
        win.bind("<Escape>", lambda _e: win.destroy())

    # -------- Export --------

    def _export_clicked(self):
        if not self.parse_report:
            messagebox.showwarning("Nothing to export", "Load a bundle first.")
            return
        if not self.full_rows:
            messagebox.showwarning("Nothing to export", "Run IH first.")
            return

        default_name = f"{_now_stamp()}_IH_reports.xlsx"
        p = filedialog.asksaveasfilename(
            title="Save IH reports",
            defaultextension=".xlsx",
            initialfile=default_name,
            filetypes=[("Excel Workbook", "*.xlsx")],
        )
        if not p:
            return

        try:
            _export_xlsx(p, self.full_rows, self.survivors, self.parse_report.header)
        except Exception as e:
            messagebox.showerror("Export failed", str(e))
            return

        self.lbl_status.configure(text=f"Exported: {Path(p).name}")

    def _export_errors_clicked(self):
        if not self.parse_report or not self.parse_report.skipped:
            messagebox.showinfo("No input errors", "No skipped/invalid records to export.")
            return

        default_name = f"{_now_stamp()}_input_errors.csv"
        p = filedialog.asksaveasfilename(
            title="Save input_errors.csv",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV", "*.csv")],
        )
        if not p:
            return
        try:
            _export_input_errors_csv(p, self.parse_report.skipped)
        except Exception as e:
            messagebox.showerror("Export failed", str(e))
            return
        self.lbl_status.configure(text=f"Exported: {Path(p).name}")

    def _export_bundle_clicked(self):
        if not self.bundle or not self.parse_report:
            messagebox.showwarning("Missing bundle", "Load a bundle first.")
            return
        if not self.full_rows:
            messagebox.showwarning("Nothing to export", "Run IH first.")
            return

        default_name = f"ScreenA_Bundle_IH_{_now_stamp()}.zip"
        p = filedialog.asksaveasfilename(
            title="Save next bundle (post-IH)",
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[("ZIP", "*.zip")],
        )
        if not p:
            return

        try:
            _export_next_bundle_zip(
                p,
                self.bundle,
                data_rel=(self.data_rel_used or "data/current.csv"),
                criteria_rel=(self.criteria_rel_used or "criteria/criteria_harmonized.csv"),
                input_errors_rel=self.input_errors_rel_used,
                parse_header=self.parse_report.header,
                full_rows=self.full_rows,
                survivors=self.survivors,
                skipped=self.parse_report.skipped,
                counts=self.counts,
            )
        except Exception as e:
            messagebox.showerror("Export failed", str(e))
            return

        self.lbl_status.configure(text=f"Exported bundle: {Path(p).name}")


# ----------------------------
# Hub plugin wrapper
# ----------------------------

class Plugin(BasePlugin):
    def __init__(self, app=None, meta: Optional[PluginMeta] = None):
        if meta is None:
            meta = PluginMeta(id="screen_a_ih", title=TAB_TITLE, version="2.2.1")
        super().__init__(app, meta)
        self.view: Optional[IHView] = None

    def build_tab(self, parent: ttk.Notebook) -> tk.Frame:
        frame = ttk.Frame(parent)
        self.view = IHView(frame)
        self.view.pack(fill="both", expand=True)
        return frame

    def on_close(self):
        try:
            if self.view:
                self.view.destroy()
        except Exception:
            pass
        self.view = None
