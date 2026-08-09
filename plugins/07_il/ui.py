
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""ui.py - Plugin 07 IL (Screen A): Tkinter View and standalone shell.

After Conv 6 / Commit 3, this module owns the IL stage's UI surface:
  - DataTable: Treeview wrapper with click-to-sort and incremental rendering.
  - _now_stamp, _export_il_xlsx: small UI-side helpers for export actions.
  - Final-report aggregation helpers (_find_bundle_member,
    _load_csv_rows_from_zip, _load_master_rows, _stage_prefix,
    _extract_contract_stage_row, _compute_final_outcome,
    _build_final_report_xlsx_bytes): IL-specific because IL is the
    terminal stage that produces the cross-stage final report.
  - ILView: the Tk Notebook tab widget for the IL stage.
  - StandaloneILPlugin: the standalone-app shell wrapper around ILView.

Engine logic stays in plugins/07_il/plugin.py for now; ui.py imports
the symbols it needs from there. Subsequent Conv 6 commits will finish
moving engine code into plugins/_common/ and shrink
plugins/07_il/plugin.py to a thin shim.

This file is GUI-only; its behaviour is verified manually after the
final thin-shim commit lands.
"""

import csv
import io
import json
import os
import re
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# F-02: one shared export gate, so the rule that a cancelled run
# cannot be exported lives in one place for all four stages.
from plugins._common.bundle import (
    _export_block_reason,
    _write_llm_stage_bundle,
)

from plugins._common.input_errors import (
    from_dict_skipped,
    merge_input_errors_csv,
    read_input_errors,
)

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Engine + dataclasses + IL-specific constants stay in plugin.py for now
# (Conv 6 / Commit 3). These imports break the circular dependency
# cleanly because plugin.py defines all of these BEFORE it does
# `from .ui import ILView, ...` near the bottom.
from .plugin import (
    BundleInfo,
    CONTRACT_STAGE_SHEET_COLS,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MODEL,
    DEFAULT_TRUNC_CHARS,
    DEFAULT_USE_CACHE,
    FINAL_REPORT_NAME,
    FINAL_REPORT_REL,
    IL_CACHE_REL,
    RENDER_CHUNK,
    REPORTS_DIR_REL,
    _csv_read,
    _decode_bytes,
    _dump_cache_to_jsonl,
    _has_openai_key,
    _load_bundle,
    _load_cache_from_jsonl,
    _read_zip_bytes,
    _safe_str,
    _write_csv,
    run_il_screen,
)

# ------------------------------ UI helpers ------------------------------------

class DataTable(ttk.Frame):
    """
    Treeview wrapper with:
    - column setup
    - click-to-sort (optional)
    - incremental rendering to keep UI responsive
    - optional double-click callback

    Backward compatible:
      - DataTable(parent, on_sort_callable, on_row_activate=...)
      - DataTable(parent, ["col1","col2",...])  # legacy usage
    """
    def __init__(
        self,
        parent,
        on_sort=None,
        on_row_activate: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        super().__init__(parent)

        # Legacy signature: second arg is actually a list of columns
        cols_seed: Optional[List[str]] = None
        if on_sort is None:
            self.on_sort = lambda _c: None
        elif callable(on_sort):
            self.on_sort = on_sort
        else:
            # treat as columns list/tuple
            if isinstance(on_sort, (list, tuple)):
                cols_seed = list(on_sort)
            self.on_sort = lambda _c: None

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
        self._iid_to_row: Dict[str, Dict[str, Any]] = {}

        self.tree.bind("<Double-1>", self._on_double_click)

        if cols_seed:
            self.set_columns(cols_seed)

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

    def render_rows_incremental(self, rows: List[Dict[str, Any]]):
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

    # ---- legacy helpers used by Plugin(ttk.Frame) ----
    def set_rows(self, rows: List[Dict[str, Any]]):
        if not rows:
            self.clear()
            return
        if not self.columns:
            self.set_columns(list(rows[0].keys()))
        self.render_rows_incremental(rows)

    def get_selected_row(self) -> Optional[Dict[str, Any]]:
        sel = self.tree.selection()
        if not sel:
            return None
        return self._iid_to_row.get(sel[0])

    def _on_double_click(self, _evt):
        if not self.on_row_activate:
            return
        r = self.get_selected_row()
        if r is not None:
            self.on_row_activate(r)

def _now_stamp() -> str:
    # Same convention as EH/IH
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _export_il_xlsx(
    path: str,
    full_rows: List[Dict[str, Any]],
    survivors: List[Dict[str, Any]],
    base_header: List[str],
) -> None:
    """
    Writes a 2-sheet XLSX:
      - IL_FULL
      - IL_SURVIVORS
    Uses openpyxl (same approach as your EH/IH plugins).
    """
    try:
        from openpyxl import Workbook  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "openpyxl is required for XLSX export. Install it (pip install openpyxl)."
        ) from e

    def cell(v: Any) -> Any:
        if v is None:
            return ""
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return v

    wb = Workbook(write_only=True)

    # ---- headers (stable + tolerant) ----
    base = list(base_header or [])
    if "local_id" in base:
        base = ["local_id"] + [h for h in base if h != "local_id"]
    else:
        base = ["local_id"] + base

    el_cols = [
        "il_outcome",
        "il_failed_ids",
        "il_missing_ids",
        "il_met_ids",
        "il_uncertain_ids",
        "il_reason_summary",
        "il_evidence_json",
    ]

    # Full sheet header = base + IL cols + any extras present in data
    full_header = base + [c for c in el_cols if c not in base]
    if full_rows:
        extras = [k for k in full_rows[0].keys() if k not in full_header]
        full_header += extras

    # Survivors sheet header = base + any extras present in survivors (rare)
    surv_header = list(base)
    if survivors:
        extras2 = [k for k in survivors[0].keys() if k not in surv_header]
        surv_header += extras2

    # ---- sheet: IL_FULL ----
    ws1 = wb.create_sheet(title="IL_FULL")
    ws1.append(full_header)
    for r in full_rows:
        ws1.append([cell(r.get(h, "")) for h in full_header])

    # ---- sheet: IL_SURVIVORS ----
    ws2 = wb.create_sheet(title="IL_SURVIVORS")
    ws2.append(surv_header)
    for r in survivors:
        ws2.append([cell(r.get(h, "")) for h in surv_header])

    # Remove default sheet if present
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    wb.save(path)



def _find_bundle_member(zf: zipfile.ZipFile, root: str, rel: str) -> Optional[str]:
    """Return the member name for root+rel if present, else try suffix match case-insensitive."""
    exact = root + rel
    if exact in zf.namelist():
        return exact
    suffix = ("/" + rel).lower()
    for name in zf.namelist():
        if name.lower().endswith(suffix):
            return name
    return None


def _load_csv_rows_from_zip(zf: zipfile.ZipFile, member: str) -> Tuple[List[str], List[Dict[str, str]]]:
    b = _read_zip_bytes(zf, member)
    txt = _decode_bytes(b)
    return _csv_read(txt)


def _load_master_rows(zf: zipfile.ZipFile, root: str) -> Tuple[List[str], List[Dict[str, str]]]:
    """
    Best-effort: try to load the *original* A (all items) if present; else fall back to current.
    """
    candidates = [
        "data/A.csv",
        "data/original.csv",
        "data/aggregate.csv",
        "data/current.csv",
    ]
    for rel in candidates:
        mem = _find_bundle_member(zf, root, rel)
        if mem:
            try:
                return _load_csv_rows_from_zip(zf, mem)
            except Exception:
                continue
    return ([], [])


def _stage_prefix(stage: str) -> str:
    return stage.lower() + "_"


def _extract_contract_stage_row(stage: str, r: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map a stage FULL row (plugin convention: {prefix}outcome, {prefix}*_ids, {prefix}reason_summary, {prefix}evidence_json)
    to contract v2 standardized columns.
    """
    pref = _stage_prefix(stage)
    a_id = _safe_str(r.get("a_id") or r.get("local_id") or r.get("id") or r.get("doi") or "")
    stage_outcome = _safe_str(r.get(pref + "outcome") or r.get("stage_outcome") or "")
    failed = _safe_str(r.get(pref + "failed_ids") or "")
    missing = _safe_str(r.get(pref + "missing_ids") or "")
    uncertain = _safe_str(r.get(pref + "uncertain_ids") or "")
    met = _safe_str(r.get(pref + "met_ids") or "")
    matched_evidence = _safe_str(r.get(pref + "evidence_json") or r.get(pref + "matched_evidence") or "")
    reason = _safe_str(r.get(pref + "reason_summary") or r.get("stage_reason_summary") or "")
    passed_to_next = "true" if stage_outcome and stage_outcome != "OUT" else "false"
    return {
        "a_id": a_id,
        "stage": stage,
        "stage_outcome": stage_outcome,
        "passed_to_next": passed_to_next,
        "failed_criteria_ids": failed,
        "missing_criteria_ids": missing,
        "uncertain_criteria_ids": uncertain,
        "met_criteria_ids": met,
        "matched_evidence": matched_evidence,
        "stage_reason_summary": reason,
        "history": "",
    }


def _compute_final_outcome(outcomes: Dict[str, str]) -> str:
    """
    Contract v2: FINAL outcome:
      - OUT if any stage outcome == OUT
      - PASS_CLEAN if ALL non-empty stage outcomes are PASS_CLEAN AND IL is PASS_CLEAN
      - REVIEW otherwise
    """
    for st in ("EH", "IH", "EL", "IL"):
        if outcomes.get(st) == "OUT":
            return "OUT"
    il_out = outcomes.get("IL", "")
    if il_out == "PASS_CLEAN" and all((outcomes.get(st, "") in {"", "PASS_CLEAN"} for st in ("EH", "IH", "EL", "IL"))):
        return "PASS_CLEAN"
    return "REVIEW"


def _build_final_report_xlsx_bytes(
    zf_in: zipfile.ZipFile,
    root: str,
    il_full_rows: List[Dict[str, Any]],
) -> bytes:
    """
    Build the contract v2 5-sheet Excel workbook:
      EH / IH / EL / IL / FINAL
    Uses stage FULL CSVs from the input bundle when available.
    """
    # Load prior stage FULL rows (best-effort)
    stage_full: Dict[str, List[Dict[str, str]]] = {}
    for st in ("EH", "IH", "EL"):
        mem = _find_bundle_member(zf_in, root, f"{REPORTS_DIR_REL}/{st}_FULL.csv")
        if mem:
            try:
                _, rows = _load_csv_rows_from_zip(zf_in, mem)
                stage_full[st] = rows
            except Exception:
                stage_full[st] = []
        else:
            stage_full[st] = []

    stage_full["IL"] = [{k: (_safe_str(v) if not isinstance(v, str) else v) for k, v in r.items()} for r in il_full_rows]

    # Master list (all items) for FINAL
    master_header, master_rows = _load_master_rows(zf_in, root)
    # Build meta lookup by a_id
    meta_by_id: Dict[str, Dict[str, str]] = {}
    for r in master_rows:
        a_id = _safe_str(r.get("a_id") or r.get("local_id") or r.get("id") or "")
        if a_id:
            meta_by_id[a_id] = r

    # Outcomes + reasons per stage
    stage_by_id: Dict[str, Dict[str, Dict[str, Any]]] = {st: {} for st in ("EH", "IH", "EL", "IL")}
    for st in ("EH", "IH", "EL", "IL"):
        for r in stage_full.get(st, []):
            a_id = _safe_str(r.get("a_id") or r.get("local_id") or r.get("id") or "")
            if not a_id:
                continue
            pref = _stage_prefix(st)
            stage_by_id[st][a_id] = {
                "outcome": _safe_str(r.get(pref + "outcome") or r.get("stage_outcome") or ""),
                "reason": _safe_str(r.get(pref + "reason_summary") or r.get("stage_reason_summary") or ""),
            }

    # Universe of ids
    all_ids = set(meta_by_id.keys())
    for st in ("EH", "IH", "EL", "IL"):
        all_ids.update(stage_by_id[st].keys())
    all_ids = sorted(all_ids, key=lambda x: (len(x), x))

    # Meta columns for FINAL (keep master header order, minus id columns)
    meta_cols = [c for c in master_header if c not in {"a_id", "local_id"}] if master_header else []

    try:
        from openpyxl import Workbook
    except Exception as e:
        raise RuntimeError("openpyxl is required to build the final report workbook.") from e

    wb = Workbook(write_only=True)

    # Stage sheets
    for st in ("EH", "IH", "EL", "IL"):
        ws = wb.create_sheet(title=st)
        ws.append(CONTRACT_STAGE_SHEET_COLS)
        for r in stage_full.get(st, []):
            row_obj = _extract_contract_stage_row(st, r)
            ws.append([row_obj.get(c, "") for c in CONTRACT_STAGE_SHEET_COLS])

    # FINAL sheet
    ws = wb.create_sheet(title="FINAL")
    final_cols = ["a_id"] + meta_cols + [
        "outcome_EH", "reason_EH",
        "outcome_IH", "reason_IH",
        "outcome_EL", "reason_EL",
        "outcome_IL", "reason_IL",
        "final_outcome", "final_reason_summary",
        "history",
    ]
    ws.append(final_cols)

    for a_id in all_ids:
        meta = meta_by_id.get(a_id, {})
        outcomes = {st: stage_by_id[st].get(a_id, {}).get("outcome", "") for st in ("EH", "IH", "EL", "IL")}
        reasons = {st: stage_by_id[st].get(a_id, {}).get("reason", "") for st in ("EH", "IH", "EL", "IL")}
        final_out = _compute_final_outcome(outcomes)
        if final_out == "OUT":
            # first stage that OUTed (in pipeline order)
            out_stage = next((st for st in ("EH", "IH", "EL", "IL") if outcomes.get(st) == "OUT"), "")
            final_reason = f"OUT at {out_stage}" if out_stage else "OUT"
        elif final_out == "PASS_CLEAN":
            final_reason = "PASS_CLEAN across all stages"
        else:
            final_reason = "Needs review after staged screening"

        row = [a_id]
        row.extend([meta.get(c, "") for c in meta_cols])
        row.extend([outcomes["EH"], reasons["EH"], outcomes["IH"], reasons["IH"], outcomes["EL"], reasons["EL"], outcomes["IL"], reasons["IL"]])
        row.extend([final_out, final_reason, ""])
        ws.append(row)

    # Ensure workbook has proper first sheet order (write_only creates default Sheet)
    # openpyxl write_only starts with a default sheet named "Sheet" sometimes; remove it if empty.
    # (In write_only mode, default may still exist.)
    try:
        if "Sheet" in wb.sheetnames and len(wb.sheetnames) > 5:
            wb.remove(wb["Sheet"])
    except Exception:
        pass

    from io import BytesIO
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


# ----------------------------
# Main View
# ----------------------------

class ILView(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self.bundle_zip_path: Optional[str] = None
        self.bundle: Optional[BundleInfo] = None

        self.full_rows: List[Dict[str, Any]] = []
        self.cancelled: bool = False   # F-02: last run stopped mid-corpus
        self.survivors: List[Dict[str, str]] = []
        self.counts: Dict[str, int] = {}

        self.crit_impacts: Dict[str, Dict[str, int]] = {}
        self.row_eval_lists: List[Dict[str, List[str]]] = []

        self.cache_map: Dict[str, Dict[str, Any]] = {}

        self.active_criterion_id: Optional[str] = None

        self._worker: Optional[threading.Thread] = None
        self._cancel = threading.Event()

        self.sort_full: Tuple[Optional[str], bool] = (None, True)
        self.sort_surv: Tuple[Optional[str], bool] = (None, True)
        self.sort_crit: Tuple[Optional[str], bool] = (None, True)

        # Settings
        self.var_model = tk.StringVar(value=DEFAULT_MODEL)
        self.var_temp = tk.DoubleVar(value=0.0)
        self.var_batch = tk.StringVar(value=str(DEFAULT_BATCH_SIZE))
        self.var_trunc = tk.StringVar(value=str(DEFAULT_TRUNC_CHARS))
        self.var_use_cache = tk.BooleanVar(value=DEFAULT_USE_CACHE)

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

        self.btn_run = ttk.Button(actions, text="Run IL", command=self._run_clicked, state="disabled")
        self.btn_run.grid(row=0, column=0, padx=4, pady=2, sticky="e")

        self.btn_cancel = ttk.Button(actions, text="Cancel", command=self._cancel_run, state="disabled")
        self.btn_cancel.grid(row=1, column=0, padx=4, pady=2, sticky="e")

        self.btn_export = ttk.Button(actions, text="Export XLSX…", command=self._export_clicked, state="disabled")
        self.btn_export.grid(row=0, column=1, padx=4, pady=2, sticky="e")

        self.btn_export_err = ttk.Button(actions, text="Export input_errors.csv…", command=self._export_errors_clicked, state="disabled")
        self.btn_export_err.grid(row=1, column=1, padx=4, pady=2, sticky="e")

        self.btn_export_bundle = ttk.Button(actions, text="Export next bundle ZIP…", command=self._export_bundle_clicked, state="disabled")
        self.btn_export_bundle.grid(row=0, column=2, padx=4, pady=2, sticky="e")

        self.btn_export_final = ttk.Button(actions, text="Export ScreenA_Report.xlsx…", command=self._export_final_clicked, state="disabled")
        self.btn_export_final.grid(row=0, column=3, padx=4, pady=2, sticky="e")

        # API key indicator (IL requires OpenAI)
        self.lbl_key = ttk.Label(actions, text="")
        self.lbl_key.grid(row=1, column=3, padx=4, pady=2, sticky="e")
        self._refresh_key_label()

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

        crit_box = ttk.Labelframe(left, text="IL Criteria (read-only)")
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

        settings = ttk.Labelframe(left, text="IL Settings")
        settings.pack(fill="x", pady=(6, 0))

        ttk.Label(settings, text="Model").grid(row=0, column=0, sticky="w", padx=6, pady=2)
        ttk.Entry(settings, textvariable=self.var_model, width=24).grid(row=0, column=1, sticky="ew", padx=6, pady=2)

        ttk.Label(settings, text="Temperature").grid(row=1, column=0, sticky="w", padx=6, pady=2)
        ttk.Spinbox(settings, textvariable=self.var_temp, from_=0.0, to=2.0, increment=0.1, format="%.2f", width=10).grid(row=1, column=1, sticky="w", padx=6, pady=2)
        ttk.Label(settings, text="(0.0 = deterministic; non-zero invalidates cache)").grid(row=2, column=1, sticky="w", padx=6, pady=(0, 4))

        ttk.Label(settings, text="Batch size").grid(row=3, column=0, sticky="w", padx=6, pady=2)
        ttk.Entry(settings, textvariable=self.var_batch, width=10).grid(row=3, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(settings, text="Trunc chars").grid(row=4, column=0, sticky="w", padx=6, pady=2)
        ttk.Entry(settings, textvariable=self.var_trunc, width=10).grid(row=4, column=1, sticky="w", padx=6, pady=2)

        ttk.Checkbutton(settings, text="Use cache (bundle cache/IL_cache.jsonl)", variable=self.var_use_cache).grid(row=5, column=0, columnspan=2, sticky="w", padx=6, pady=2)

        settings.columnconfigure(1, weight=1)

        warn_box = ttk.Labelframe(left, text="Notes / warnings")
        warn_box.pack(fill="both", expand=False, pady=(6, 0))

        self.txt_warn = tk.Text(warn_box, height=8, wrap="word")
        self.txt_warn.pack(fill="both", expand=True, padx=6, pady=6)
        self.txt_warn.configure(state="disabled")

        nb = ttk.Notebook(right)
        nb.pack(fill="both", expand=True)

        tab_full = ttk.Frame(nb)
        tab_surv = ttk.Frame(nb)
        tab_log = ttk.Frame(nb)
        nb.add(tab_full, text="IL Full report")
        nb.add(tab_surv, text="IL Survivors")
        nb.add(tab_log, text="Log")

        self.full_table = DataTable(tab_full, on_sort=self._sort_full_table, on_row_activate=self._open_row_detail_modal)
        self.full_table.pack(fill="both", expand=True, padx=6, pady=6)

        self.surv_table = DataTable(tab_surv, on_sort=self._sort_surv_table, on_row_activate=self._open_row_detail_modal)
        self.surv_table.pack(fill="both", expand=True, padx=6, pady=6)

        self.txt_log = tk.Text(tab_log, wrap="word")
        self.txt_log.pack(fill="both", expand=True, padx=6, pady=6)
        self.txt_log.configure(state="disabled")

        self.lbl_counts = ttk.Label(self, text="")
        self.lbl_counts.pack(fill="x", padx=10, pady=(0, 10))

    # -------- helpers --------

    def _refresh_key_label(self):
        self.lbl_key.configure(text=("OPENAI_API_KEY ✓" if _has_openai_key() else "OPENAI_API_KEY ✗"))

    def _log(self, msg: str) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", msg)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _set_warnings(self, lines: Sequence[str]) -> None:
        self.txt_warn.configure(state="normal")
        self.txt_warn.delete("1.0", "end")
        self.txt_warn.insert("end", "\n".join(lines) if lines else "(none)")
        self.txt_warn.configure(state="disabled")

    def _refresh_counts_label(self):
        if not self.bundle:
            self.lbl_counts.configure(text="")
            return
        pr = self.bundle.parse
        msg = f"Integral rows: {len(pr.rows)} | Skipped invalid: {len(pr.skipped)}"
        if self.counts:
            msg += (
                f" | OUT: {self.counts.get('OUT',0)}"
                f" | PASS_CLEAN: {self.counts.get('PASS_CLEAN',0)}"
                f" | REVIEW: {self.counts.get('REVIEW',0)}"
            )
        self.lbl_counts.configure(text=msg)

    def _set_controls_running(self, running: bool) -> None:
        self.btn_cancel.configure(state=("normal" if running else "disabled"))
        self.btn_run.configure(state=("disabled" if running else ("normal" if self.bundle_zip_path else "disabled")))
        self.btn_export.configure(state=("disabled" if running else ("normal" if self.full_rows else "disabled")))
        self.btn_export_err.configure(state=("disabled" if running else ("normal" if (self.bundle and self.bundle.parse.skipped) else "disabled")))
        self.btn_export_bundle.configure(state=("disabled" if running else ("normal" if self.full_rows else "disabled")))
        self.btn_export_final.configure(state=("disabled" if running else ("normal" if self.full_rows else "disabled")))

    def _sorted_rows(self, rows: List[Dict[str, Any]], col: str, asc: bool) -> List[Dict[str, Any]]:
        def _key(r: Dict[str, Any]):
            v = r.get(col, "")
            s = _safe_str(v)
            # numeric sort if it looks like a number
            try:
                if s.strip() == "":
                    return (1, 0.0, s)
                return (0, float(s), s)
            except Exception:
                return (0, 0.0, s.lower())
        return sorted(rows, key=_key, reverse=(not asc))

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
        self.cancelled = False
        self.survivors = []
        self.counts = {}
        self.crit_impacts = {}
        self.row_eval_lists = []
        self.active_criterion_id = None
        self.lbl_crit_filter.configure(text="Criterion filter: (none)")
        self.btn_clear_filter.configure(state="disabled")

        self._refresh_key_label()

        try:
            self.bundle = _load_bundle(self.bundle_zip_path)
        except Exception as e:
            self.bundle = None
            messagebox.showerror("Bundle load failed", str(e))
            return

        # load cache if present
        self.cache_map = {}
        try:
            with zipfile.ZipFile(self.bundle_zip_path, "r") as zf:
                cache_member = self.bundle.root + IL_CACHE_REL
                if cache_member in zf.namelist():
                    self.cache_map = _load_cache_from_jsonl(_decode_bytes(_read_zip_bytes(zf, cache_member)))
        except Exception:
            self.cache_map = {}

        m = self.bundle.manifest
        schema = _safe_str(m.get("bundle_schema", m.get("schema", ""))).strip() or "unknown"
        created_at = _safe_str(m.get("created_at", "")).strip()
        created_by = _safe_str(m.get("created_by", "")).strip()
        stages = ((m.get("pipeline", {}) or {}).get("stages", None)) or ((m.get("pipeline_state", {}) or {}).get("stages", None)) or {}
        st_il = _safe_str(stages.get("IL", "")).strip() or "unknown"
        self.lbl_bundle_meta.configure(text=f"schema={schema} | created_at={created_at} | created_by={created_by} | IL={st_il}")

        # warnings: duplicates (they were moved to parse.skipped during load)
        dup_ids = []
        for e in (self.bundle.parse.skipped or []):
            if _safe_str(e.get("reason", "")).strip() == "duplicate local_id":
                lid = _safe_str((e.get("row") or {}).get("local_id", "")).strip()
                if lid:
                    dup_ids.append(lid)
        # unique sample
        sample = []
        seen = set()
        for x in dup_ids:
            if x not in seen:
                sample.append(x); seen.add(x)
            if len(sample) >= 10:
                break
        if dup_ids:
            warns.append(f"[data] duplicate local_id detected (n={len(set(dup_ids))}), sample={', '.join(sample)}")

        # refresh criteria table + notes
        self._refresh_criteria_table(pre_run=True)
        if self.bundle.criteria and self.bundle.criteria.warnings:
            warns.extend(self.bundle.criteria.warnings)
        self._set_warnings(warns)

        # clear report tables
        self.full_table.clear()
        self.surv_table.clear()
        self._refresh_counts_label()

        self.btn_run.configure(state="normal" if _has_openai_key() else "disabled")
        self.btn_export.configure(state="disabled")
        self.btn_export_bundle.configure(state="disabled")
        self.btn_export_err.configure(state=("normal" if self.bundle.parse.skipped else "disabled"))

        self.lbl_status.configure(text="Ready.")

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

    # -------- criteria table --------

    def _refresh_criteria_table(self, pre_run: bool):
        crits = self.bundle.criteria.criteria if (self.bundle and self.bundle.criteria) else []

        cols = ["id", "type", "targets", "operator", "what", "threshold", "status", "notes"]
        if not pre_run:
            cols += ["n_failed", "n_missing", "n_met", "n_uncertain"]

        rows: List[Dict[str, Any]] = []
        header_set = set(self.bundle.parse.header) if (self.bundle and self.bundle.parse) else set()
        header_set_l = {h.lower() for h in header_set}

        for c in crits:
            status = "OK"
            notes = ""

            if not c.targets:
                status = "WARNING"
                notes = "missing target -> treated as MISSING (REVIEW)"
            elif header_set and not any((t or "").lower() in header_set_l for t in c.targets):
                status = "WARNING"
                notes = f"missing column(s): {', '.join(c.targets)} -> treated as MISSING (REVIEW)"

            op = (c.operator or "").strip().lower()
            if op != "llm":
                status = "WARNING"
                notes = (notes + " | " if notes else "") + f"operator '{op}' treated as UNCERTAIN in IL"

            d: Dict[str, Any] = {
                "id": c.id,
                "type": c.ctype,
                "targets": ",".join(c.targets),
                "operator": c.operator,
                "what": c.what_raw,
                "threshold": _safe_str(c.threshold),
                "status": status,
                "notes": notes,
            }

            if not pre_run:
                imp = self.crit_impacts.get(c.id, {"failed": 0, "missing": 0, "met": 0, "uncertain": 0})
                d["n_failed"] = str(imp.get("failed", 0))
                d["n_missing"] = str(imp.get("missing", 0))
                d["n_met"] = str(imp.get("met", 0))
                d["n_uncertain"] = str(imp.get("uncertain", 0))

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

    def _sort_criteria_table(self, col: str):
        cur_col, asc = self.sort_crit
        if cur_col == col:
            asc = not asc
        else:
            asc = True
        self.sort_crit = (col, asc)
        self._refresh_criteria_table(pre_run=(not bool(self.full_rows)))

    # -------- reports --------

    def _refresh_reports_view(self):
        if not self.bundle:
            return

        full_cols = list(self.bundle.parse.header) + [
            "il_outcome", "il_failed_ids", "il_missing_ids", "il_met_ids", "il_uncertain_ids", "il_reason_summary"
        ]
        surv_cols = list(self.bundle.parse.header)

        full_view = self.full_rows
        if self.active_criterion_id:
            cid = self.active_criterion_id
            filtered = []
            for i, r in enumerate(self.full_rows):
                ev = self.row_eval_lists[i] if i < len(self.row_eval_lists) else {"failed": [], "missing": [], "met": [], "uncertain": []}
                if (cid in ev.get("failed", [])) or (cid in ev.get("missing", [])) or (cid in ev.get("met", [])) or (cid in ev.get("uncertain", [])):
                    filtered.append(r)
            full_view = filtered

        surv_view = self.survivors
        if self.active_criterion_id and self.full_rows:
            cid = self.active_criterion_id
            touched_survivor_ids = set()
            for i, r in enumerate(self.full_rows):
                if r.get("il_outcome") == "OUT":
                    continue
                ev = self.row_eval_lists[i]
                if (cid in ev.get("failed", [])) or (cid in ev.get("missing", [])) or (cid in ev.get("met", [])) or (cid in ev.get("uncertain", [])):
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

    def _sort_full_table(self, col: str):
        cur_col, asc = self.sort_full
        if cur_col == col:
            asc = not asc
        else:
            asc = True
        self.sort_full = (col, asc)
        self._refresh_reports_view()

    def _sort_surv_table(self, col: str):
        cur_col, asc = self.sort_surv
        if cur_col == col:
            asc = not asc
        else:
            asc = True
        self.sort_surv = (col, asc)
        self._refresh_reports_view()

    # -------- Row detail modal --------

    def _open_row_detail_modal(self, row: Dict[str, Any]):
        if not self.bundle:
            return

        win = tk.Toplevel(self)
        win.title("IL Row details")
        win.geometry("950x650")
        win.transient(self.winfo_toplevel())
        win.grab_set()

        lid = _safe_str(row.get("local_id", "")).strip()
        title = _safe_str(row.get("title", "")).strip() or _safe_str(row.get("Title", "")).strip()

        top = ttk.Frame(win)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text=f"local_id: {lid}").pack(anchor="w")
        if title:
            ttk.Label(top, text=f"title: {title[:250]}").pack(anchor="w")

        outcome = _safe_str(row.get("il_outcome", "")).strip()
        if outcome:
            ttk.Label(top, text=f"IL outcome: {outcome}").pack(anchor="w")
            rs = _safe_str(row.get("il_reason_summary", "")).strip()
            if rs:
                ttk.Label(top, text=f"summary: {rs}").pack(anchor="w")

        box = ttk.Labelframe(win, text="Per-criterion evidence (from il_evidence_json)")
        box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        cols = ["cid", "type", "operator", "targets", "what", "threshold", "status", "decision", "confidence", "field", "quote_valid", "quote"]
        table = DataTable(box, on_sort=lambda _c: None, on_row_activate=None)
        table.pack(fill="both", expand=True, padx=6, pady=6)
        table.set_columns(cols)

        # parse evidence dict
        ev_raw = _safe_str(row.get("il_evidence_json", "{}"))
        try:
            evj = json.loads(ev_raw) if ev_raw.strip() else {}
        except Exception:
            evj = {}

        detail_rows: List[Dict[str, Any]] = []
        for c in self.bundle.criteria.criteria:
            obj = evj.get(c.id, {}) if isinstance(evj, dict) else {}
            status = _safe_str(obj.get("status", ""))
            decision = _safe_str(obj.get("decision", ""))
            confidence = _safe_str(obj.get("confidence", ""))
            field = _safe_str(obj.get("field", ""))
            quote = _safe_str(obj.get("quote", ""))
            qv = _safe_str(obj.get("quote_valid", obj.get("quote_valid", "")))
            if isinstance(obj.get("quote_valid", None), bool):
                qv = "True" if obj.get("quote_valid") else "False"

            detail_rows.append({
                "cid": c.id,
                "type": c.ctype,
                "operator": c.operator,
                "targets": ",".join(c.targets),
                "what": c.what_raw,
                "threshold": _safe_str(c.threshold),
                "status": status,
                "decision": decision,
                "confidence": confidence,
                "field": field,
                "quote_valid": qv,
                "quote": quote,
            })

        table.render_rows_incremental(detail_rows)

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")
        win.bind("<Escape>", lambda _e: win.destroy())

    # -------- run --------

    def _run_clicked(self):
        if not self.bundle or self._worker:
            return
        if not _has_openai_key():
            messagebox.showerror("Missing OPENAI_API_KEY", "IL uses the OpenAI API. Set OPENAI_API_KEY in your environment (.env).")
            return

        # parse settings
        model = (self.var_model.get() or DEFAULT_MODEL).strip()
        try:
            temperature = float(self.var_temp.get())
        except Exception:
            temperature = 0.0
        try:
            batch_size = int(self.var_batch.get())
        except Exception:
            batch_size = DEFAULT_BATCH_SIZE
        try:
            trunc_chars = int(self.var_trunc.get())
        except Exception:
            trunc_chars = DEFAULT_TRUNC_CHARS
        use_cache = bool(self.var_use_cache.get())

        self._cancel.clear()
        self.pbar.configure(value=0.0, maximum=100.0)
        self.lbl_status.configure(text="Running IL…")
        self._set_controls_running(True)

        def progress_cb(frac: float):
            self.after(0, lambda: self.pbar.configure(value=max(0.0, min(100.0, frac * 100.0))))

        def progress_evt(evt: Dict[str, Any]):
            kind = _safe_str(evt.get("kind", ""))
            sub = _safe_str(evt.get("sub", ""))
            if kind == "l_batch" and sub == "sending":
                bi = evt.get("batch_idx"); bt = evt.get("batch_total")
                ci = evt.get("crit_idx"); ct = evt.get("crit_total")
                self.after(0, lambda: self.lbl_status.configure(text=f"LLM: criterion {ci}/{ct} batch {bi}/{bt}…"))

        def work():
            try:
                full_rows, survivors, counts, crit_impacts, row_eval_lists, cache_out, cancelled = run_il_screen(
                    self.bundle.parse,
                    self.bundle.criteria,
                    model=model,
                    trunc_chars=trunc_chars,
                    batch_size=batch_size,
                    temperature=temperature,
                    use_cache=use_cache,
                    cache_in=self.cache_map if use_cache else {},
                    cancel_event=self._cancel,  # ✅ ILView uses self._cancel
                    log_cb=lambda s: self.after(0, (lambda ss=s: self._log(ss))),
                    progress_cb=progress_cb,
                    progress_evt=progress_evt,
                )

                if cancelled:
                    # F-02: the engine reports that it stopped mid-corpus.
                    # Trust that rather than re-reading the event, drop the
                    # partial results instead of leaving them on screen, and
                    # latch the flag so the export handlers refuse even if an
                    # earlier complete run left rows behind.
                    self.cancelled = True
                    self.full_rows = []
                    self.survivors = []
                    self.after(0, lambda: self._log(
                        "\n[CANCELLED] Partial results discarded; export stays "
                        "disabled until IL is re-run to completion.\n"))
                    self.after(0, lambda: self.lbl_status.configure(
                        text="Cancelled — partial run, nothing exported."))
                    return

                self.full_rows = full_rows
                self.survivors = survivors
                self.counts = counts
                self.crit_impacts = crit_impacts
                self.row_eval_lists = row_eval_lists
                self.cache_map = cache_out

                # ✅ refresh views + counts + criteria impacts
                self.after(0, self._refresh_reports_view)
                self.after(0, lambda: self._refresh_criteria_table(pre_run=False))
                self.after(0, self._refresh_counts_label)
                self.after(0, lambda: self.lbl_status.configure(text="IL done."))

            except Exception as e:
                self.after(0, lambda m=str(e): messagebox.showerror("IL run failed", m))
                self.after(0, lambda: self.lbl_status.configure(text="IL failed."))
            finally:
                self.after(0, lambda: self._set_controls_running(False))
                # clear worker flag so you can run again
                self._worker = None

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _cancel_run(self):
        self._cancel.set()
        self._log("\n[Cancel requested]\n")
        self.lbl_status.configure(text="Cancelling…")

    # -------- Export --------

    def _export_clicked(self):
        if not self.bundle:
            messagebox.showwarning("Nothing to export", "Load a bundle first.")
            return
        blocked = _export_block_reason(has_rows=bool(self.full_rows),
                                       cancelled=self.cancelled)
        if blocked:
            messagebox.showwarning("Cannot export", blocked)
            return

        default_name = f"{_now_stamp()}_IL_reports.xlsx"
        p = filedialog.asksaveasfilename(
            title="Save IL reports",
            defaultextension=".xlsx",
            initialfile=default_name,
            filetypes=[("Excel Workbook", "*.xlsx")],
        )
        if not p:
            return

        try:
            _export_il_xlsx(p, self.full_rows, self.survivors, self.bundle.parse.header)
        except Exception as e:
            messagebox.showerror("Export failed", str(e))
            return

        self.lbl_status.configure(text=f"Exported: {Path(p).name}")

    def _export_final_clicked(self):
        blocked = (
            (None if self.bundle else "Load a bundle first.")
            or _export_block_reason(has_rows=bool(self.full_rows),
                                    cancelled=self.cancelled)
        )
        if blocked:
            messagebox.showinfo("Not ready", blocked)
            return

        default_name = f"{_now_stamp()}_{FINAL_REPORT_NAME}"
        p = filedialog.asksaveasfilename(
            title="Save ScreenA_Report.xlsx",
            defaultextension=".xlsx",
            initialfile=default_name,
            filetypes=[("Excel Workbook", "*.xlsx")],
        )
        if not p:
            return

        try:
            with zipfile.ZipFile(self.bundle.zip_path, "r") as zf:
                wb_bytes = _build_final_report_xlsx_bytes(zf, self.bundle.root, self.full_rows)
            Path(p).write_bytes(wb_bytes)
        except Exception as e:
            messagebox.showerror("Export failed", str(e))
            return

        self.lbl_status.configure(text=f"Exported: {Path(p).name}")

    def _export_errors_clicked(self):
        if not self.bundle:
            messagebox.showwarning("Nothing to export", "Load a bundle first.")
            return
        if not self.bundle.parse.skipped:
            messagebox.showinfo("No input errors", "No skipped/invalid rows were recorded for this bundle.")
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
            with open(p, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f, lineterminator="\n")
                w.writerow(["reason", "row_json"])
                for e in self.bundle.parse.skipped:
                    w.writerow([_safe_str(e.get("reason", "")), json.dumps(e.get("row", {}), ensure_ascii=False)])
        except Exception as e:
            messagebox.showerror("Export failed", str(e))
            return

        self.lbl_status.configure(text=f"Exported: {Path(p).name}")

    def _export_bundle_clicked(self):
        if not self.bundle:
            messagebox.showwarning("Nothing to export", "Load a bundle first.")
            return
        blocked = _export_block_reason(has_rows=bool(self.full_rows),
                                       cancelled=self.cancelled)
        if blocked:
            messagebox.showwarning("Cannot export", blocked)
            return

        default_name = f"{_now_stamp()}_post_IL_bundle.zip"
        out_zip = filedialog.asksaveasfilename(
            title="Save next bundle ZIP (post-IL)",
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[("ZIP", "*.zip")],
        )
        if not out_zip:
            return

        try:
            self._build_next_bundle_zip(out_zip)
        except Exception as e:
            messagebox.showerror("Bundle export failed", str(e))
            return

        self.lbl_status.configure(text=f"Bundle exported: {Path(out_zip).name}")

    def _build_next_bundle_zip(self, out_zip: str) -> None:
        """Create a new bundle zip where data/current.csv becomes the IL survivors.

        Keeps other files from the input bundle, updates manifest pipeline stage, adds reports, carries input_errors,
        and writes cache/IL_cache.jsonl when enabled.
        """
        assert self.bundle is not None

        with zipfile.ZipFile(self.bundle.zip_path, "r") as zf_in:
            members = zf_in.namelist()
            root = self.bundle.root

            manifest = dict(self.bundle.manifest)

            def _set_stage(m: Dict[str, Any], key: str, value: str):
                if "pipeline" in m and isinstance(m.get("pipeline"), dict):
                    m["pipeline"].setdefault("stages", {})
                    m["pipeline"]["stages"][key] = value
                if "pipeline_state" in m and isinstance(m.get("pipeline_state"), dict):
                    m["pipeline_state"].setdefault("stages", {})
                    m["pipeline_state"]["stages"][key] = value

            _set_stage(manifest, "IL", "done")
            manifest["updated_at"] = datetime.utcnow().isoformat() + "Z"

            header = list(self.bundle.parse.header)
            if "local_id" not in header:
                header = ["local_id"] + header

            header_full = [
                *header,
                "il_outcome", "il_failed_ids", "il_missing_ids", "il_met_ids", "il_uncertain_ids", "il_reason_summary", "il_evidence_json",
            ]

            # F-05: shared writer, which refreshes the manifest digests. See
            # the EL twin. IL additionally emits the cross-stage FINAL
            # workbook, passed through as an extra member so it is digested
            # alongside everything else rather than written behind the
            # manifest's back.
            _write_llm_stage_bundle(
                out_zip, zf_in,
                root=root,
                manifest=manifest,
                stage="IL",
                reports_dir_rel=REPORTS_DIR_REL,
                cache_rel=IL_CACHE_REL,
                parse_header=header,
                survivors=self.survivors,
                full_rows=self.full_rows,
                full_header=header_full,
                skipped=self.bundle.parse.skipped,
                cache_text=(_dump_cache_to_jsonl(self.cache_map)
                            if self.var_use_cache.get() else None),
                extra_members={
                    FINAL_REPORT_REL: _build_final_report_xlsx_bytes(
                        zf_in, root, self.full_rows),
                },
            )


# StandaloneILPlugin moved to plugins/07_il/standalone.py in
# Conv 6 / Commit 4. The plugin module re-exports it from there.
