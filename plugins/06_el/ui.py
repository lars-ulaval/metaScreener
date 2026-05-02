
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""ui.py - Plugin 06 EL (Screen A): Tkinter View and standalone shell.

After Conv 6 / Commit 3, this module owns the EL stage's UI surface:
  - DataTable: Treeview wrapper with click-to-sort and incremental rendering.
  - _now_stamp, _export_el_xlsx: small UI-side helpers for export actions.
  - ELView: the Tk Notebook tab widget for the EL stage.
  - StandaloneELPlugin: the standalone-app shell wrapper around ELView.

Engine logic stays in plugins/06_el/plugin.py for now; ui.py imports
the symbols it needs from there. Subsequent Conv 6 commits (4-5) will
finish moving engine code into plugins/_common/ and shrink
plugins/06_el/plugin.py to a thin shim that wires the View into the
plugin manager.

This file is GUI-only; its behaviour is verified manually after the
final thin-shim commit lands (load a bundle, click Run, double-click a
row to open the detail modal).
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

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Engine + dataclasses stay in plugin.py for now (Conv 6 / Commit 3).
# These imports break the circular dependency cleanly because plugin.py
# defines all of these BEFORE it does `from .ui import ELView, ...` near
# the bottom.
from .plugin import (
    BundleInfo,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MODEL,
    DEFAULT_TRUNC_CHARS,
    DEFAULT_USE_CACHE,
    EL_CACHE_REL,
    RENDER_CHUNK,
    REPORTS_DIR_REL,
    _decode_bytes,
    _dump_cache_to_jsonl,
    _has_openai_key,
    _load_bundle,
    _load_cache_from_jsonl,
    _read_zip_bytes,
    _safe_str,
    _write_csv,
    run_el_screen,
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


def _export_el_xlsx(
    path: str,
    full_rows: List[Dict[str, Any]],
    survivors: List[Dict[str, Any]],
    base_header: List[str],
) -> None:
    """
    Writes a 2-sheet XLSX:
      - EL_FULL
      - EL_SURVIVORS
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
        "el_outcome",
        "el_failed_ids",
        "el_missing_ids",
        "el_met_ids",
        "el_uncertain_ids",
        "el_reason_summary",
        "el_evidence_json",
    ]

    # Full sheet header = base + EL cols + any extras present in data
    full_header = base + [c for c in el_cols if c not in base]
    if full_rows:
        extras = [k for k in full_rows[0].keys() if k not in full_header]
        full_header += extras

    # Survivors sheet header = base + any extras present in survivors (rare)
    surv_header = list(base)
    if survivors:
        extras2 = [k for k in survivors[0].keys() if k not in surv_header]
        surv_header += extras2

    # ---- sheet: EL_FULL ----
    ws1 = wb.create_sheet(title="EL_FULL")
    ws1.append(full_header)
    for r in full_rows:
        ws1.append([cell(r.get(h, "")) for h in full_header])

    # ---- sheet: EL_SURVIVORS ----
    ws2 = wb.create_sheet(title="EL_SURVIVORS")
    ws2.append(surv_header)
    for r in survivors:
        ws2.append([cell(r.get(h, "")) for h in surv_header])

    # Remove default sheet if present
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    wb.save(path)


# ----------------------------
# Main View
# ----------------------------

class ELView(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self.bundle_zip_path: Optional[str] = None
        self.bundle: Optional[BundleInfo] = None

        self.full_rows: List[Dict[str, Any]] = []
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

        self.btn_run = ttk.Button(actions, text="Run EL", command=self._run_clicked, state="disabled")
        self.btn_run.grid(row=0, column=0, padx=4, pady=2, sticky="e")

        self.btn_cancel = ttk.Button(actions, text="Cancel", command=self._cancel_run, state="disabled")
        self.btn_cancel.grid(row=1, column=0, padx=4, pady=2, sticky="e")

        self.btn_export = ttk.Button(actions, text="Export XLSX…", command=self._export_clicked, state="disabled")
        self.btn_export.grid(row=0, column=1, padx=4, pady=2, sticky="e")

        self.btn_export_err = ttk.Button(actions, text="Export input_errors.csv…", command=self._export_errors_clicked, state="disabled")
        self.btn_export_err.grid(row=1, column=1, padx=4, pady=2, sticky="e")

        self.btn_export_bundle = ttk.Button(actions, text="Export next bundle ZIP…", command=self._export_bundle_clicked, state="disabled")
        self.btn_export_bundle.grid(row=0, column=2, padx=4, pady=2, sticky="e")

        # API key indicator (EL requires OpenAI)
        self.lbl_key = ttk.Label(actions, text="")
        self.lbl_key.grid(row=1, column=2, padx=4, pady=2, sticky="e")
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

        crit_box = ttk.Labelframe(left, text="EL Criteria (read-only)")
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

        settings = ttk.Labelframe(left, text="EL Settings")
        settings.pack(fill="x", pady=(6, 0))

        ttk.Label(settings, text="Model").grid(row=0, column=0, sticky="w", padx=6, pady=2)
        ttk.Entry(settings, textvariable=self.var_model, width=24).grid(row=0, column=1, sticky="ew", padx=6, pady=2)

        ttk.Label(settings, text="Batch size").grid(row=1, column=0, sticky="w", padx=6, pady=2)
        ttk.Entry(settings, textvariable=self.var_batch, width=10).grid(row=1, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(settings, text="Trunc chars").grid(row=2, column=0, sticky="w", padx=6, pady=2)
        ttk.Entry(settings, textvariable=self.var_trunc, width=10).grid(row=2, column=1, sticky="w", padx=6, pady=2)

        ttk.Checkbutton(settings, text="Use cache (bundle cache/EL_cache.jsonl)", variable=self.var_use_cache).grid(row=3, column=0, columnspan=2, sticky="w", padx=6, pady=2)

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
        nb.add(tab_full, text="EL Full report")
        nb.add(tab_surv, text="EL Survivors")
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
                f" | PASS_FLAGGED: {self.counts.get('PASS_FLAGGED',0)}"
            )
        self.lbl_counts.configure(text=msg)

    def _set_controls_running(self, running: bool) -> None:
        self.btn_cancel.configure(state=("normal" if running else "disabled"))
        self.btn_run.configure(state=("disabled" if running else ("normal" if self.bundle_zip_path else "disabled")))
        self.btn_export.configure(state=("disabled" if running else ("normal" if self.full_rows else "disabled")))
        self.btn_export_err.configure(state=("disabled" if running else ("normal" if (self.bundle and self.bundle.parse.skipped) else "disabled")))
        self.btn_export_bundle.configure(state=("disabled" if running else ("normal" if self.full_rows else "disabled")))

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
                cache_member = self.bundle.root + EL_CACHE_REL
                if cache_member in zf.namelist():
                    self.cache_map = _load_cache_from_jsonl(_decode_bytes(_read_zip_bytes(zf, cache_member)))
        except Exception:
            self.cache_map = {}

        m = self.bundle.manifest
        schema = _safe_str(m.get("bundle_schema", m.get("schema", ""))).strip() or "unknown"
        created_at = _safe_str(m.get("created_at", "")).strip()
        created_by = _safe_str(m.get("created_by", "")).strip()
        stages = ((m.get("pipeline", {}) or {}).get("stages", None)) or ((m.get("pipeline_state", {}) or {}).get("stages", None)) or {}
        st_el = _safe_str(stages.get("EL", "")).strip() or "unknown"
        self.lbl_bundle_meta.configure(text=f"schema={schema} | created_at={created_at} | created_by={created_by} | EL={st_el}")

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
                notes = "missing target -> treated as MISSING (PASS_FLAGGED)"
            elif header_set and not any((t or "").lower() in header_set_l for t in c.targets):
                status = "WARNING"
                notes = f"missing column(s): {', '.join(c.targets)} -> treated as MISSING (PASS_FLAGGED)"

            op = (c.operator or "").strip().lower()
            if op != "llm":
                status = "WARNING"
                notes = (notes + " | " if notes else "") + f"operator '{op}' treated as UNCERTAIN in EL"

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
            "el_outcome", "el_failed_ids", "el_missing_ids", "el_met_ids", "el_uncertain_ids", "el_reason_summary"
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
                if r.get("el_outcome") == "OUT":
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
        win.title("EL Row details")
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

        outcome = _safe_str(row.get("el_outcome", "")).strip()
        if outcome:
            ttk.Label(top, text=f"EL outcome: {outcome}").pack(anchor="w")
            rs = _safe_str(row.get("el_reason_summary", "")).strip()
            if rs:
                ttk.Label(top, text=f"summary: {rs}").pack(anchor="w")

        box = ttk.Labelframe(win, text="Per-criterion evidence (from el_evidence_json)")
        box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        cols = ["cid", "type", "operator", "targets", "what", "threshold", "status", "decision", "confidence", "field", "quote_valid", "quote"]
        table = DataTable(box, on_sort=lambda _c: None, on_row_activate=None)
        table.pack(fill="both", expand=True, padx=6, pady=6)
        table.set_columns(cols)

        # parse evidence dict
        ev_raw = _safe_str(row.get("el_evidence_json", "{}"))
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
            messagebox.showerror("Missing OPENAI_API_KEY", "EL uses the OpenAI API. Set OPENAI_API_KEY in your environment (.env).")
            return

        # parse settings
        model = (self.var_model.get() or DEFAULT_MODEL).strip()
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
        self.lbl_status.configure(text="Running EL…")
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
                full_rows, survivors, counts, crit_impacts, row_eval_lists, cache_out = run_el_screen(
                    self.bundle.parse,
                    self.bundle.criteria,
                    model=model,
                    trunc_chars=trunc_chars,
                    batch_size=batch_size,
                    use_cache=use_cache,
                    cache_in=self.cache_map if use_cache else {},
                    cancel_event=self._cancel,  # ✅ ELView uses self._cancel
                    log_cb=lambda s: self.after(0, (lambda ss=s: self._log(ss))),
                    progress_cb=progress_cb,
                    progress_evt=progress_evt,
                )

                if self._cancel.is_set():
                    self.after(0, lambda: self._log("\n[CANCELLED]\n"))
                    self.after(0, lambda: self.lbl_status.configure(text="Cancelled."))
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
                self.after(0, lambda: self.lbl_status.configure(text="EL done."))

            except Exception as e:
                self.after(0, lambda m=str(e): messagebox.showerror("EL run failed", m))
                self.after(0, lambda: self.lbl_status.configure(text="EL failed."))
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
        if not self.full_rows:
            messagebox.showwarning("Nothing to export", "Run EL first.")
            return

        default_name = f"{_now_stamp()}_EL_reports.xlsx"
        p = filedialog.asksaveasfilename(
            title="Save EL reports",
            defaultextension=".xlsx",
            initialfile=default_name,
            filetypes=[("Excel Workbook", "*.xlsx")],
        )
        if not p:
            return

        try:
            _export_el_xlsx(p, self.full_rows, self.survivors, self.bundle.parse.header)
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
        if not self.full_rows:
            messagebox.showwarning("Nothing to export", "Run EL first.")
            return

        default_name = f"{_now_stamp()}_post_EL_bundle.zip"
        out_zip = filedialog.asksaveasfilename(
            title="Save next bundle ZIP (post-EL)",
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
        """Create a new bundle zip where data/current.csv becomes the EL survivors.

        Keeps other files from the input bundle, updates manifest pipeline stage, adds reports, carries input_errors,
        and writes cache/EL_cache.jsonl when enabled.
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

            _set_stage(manifest, "EL", "done")
            manifest["updated_at"] = datetime.utcnow().isoformat() + "Z"

            with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf_out:
                skip_exact = {
                    root + "data/current.csv",
                    root + f"{REPORTS_DIR_REL}/EL_FULL.csv",
                    root + f"{REPORTS_DIR_REL}/EL_SURVIVORS.csv",
                    root + "data/input_errors.csv",
                    root + EL_CACHE_REL,
                    root + "manifest.json",
                }

                for m in members:
                    if m.endswith("/"):
                        continue
                    if m in skip_exact:
                        continue
                    zf_out.writestr(m, _read_zip_bytes(zf_in, m))

                zf_out.writestr(root + "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

                # survivors to data/current.csv
                header = list(self.bundle.parse.header)
                if "local_id" not in header:
                    header = ["local_id"] + header

                buf = io.StringIO()
                w = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
                w.writeheader()
                for r in self.survivors:
                    w.writerow({k: r.get(k, "") for k in header})
                zf_out.writestr(root + "data/current.csv", buf.getvalue())

                # reports
                header_full = [
                    *header,
                    "el_outcome", "el_failed_ids", "el_missing_ids", "el_met_ids", "el_uncertain_ids", "el_reason_summary", "el_evidence_json",
                ]

                buf2 = io.StringIO()
                w2 = csv.DictWriter(buf2, fieldnames=header_full, extrasaction="ignore")
                w2.writeheader()
                for r in self.full_rows:
                    w2.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in header_full})
                zf_out.writestr(root + f"{REPORTS_DIR_REL}/EL_FULL.csv", buf2.getvalue())

                buf3 = io.StringIO()
                w3 = csv.DictWriter(buf3, fieldnames=header, extrasaction="ignore")
                w3.writeheader()
                for r in self.survivors:
                    w3.writerow({k: r.get(k, "") for k in header})
                zf_out.writestr(root + f"{REPORTS_DIR_REL}/EL_SURVIVORS.csv", buf3.getvalue())

                # input errors
                if self.bundle.parse.skipped:
                    buf4 = io.StringIO()
                    err_header = ["reason", "row_json"]
                    w4 = csv.DictWriter(buf4, fieldnames=err_header)
                    w4.writeheader()
                    for e in self.bundle.parse.skipped:
                        w4.writerow({"reason": _safe_str(e.get("reason", "")), "row_json": json.dumps(e.get("row", {}), ensure_ascii=False)})
                    zf_out.writestr(root + "data/input_errors.csv", buf4.getvalue())

                # cache
                if self.var_use_cache.get():
                    zf_out.writestr(root + EL_CACHE_REL, _dump_cache_to_jsonl(self.cache_map))


class StandaloneELPlugin(ttk.Frame):
    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.bundle_zip_path: Optional[str] = None
        self.bundle: Optional[BundleInfo] = None

        self.full_rows: List[Dict[str, Any]] = []
        self.survivors: List[Dict[str, str]] = []
        self.counts: Dict[str, int] = {}
        self.crit_impacts: Dict[str, Dict[str, int]] = {}
        self.row_eval_lists: List[Dict[str, List[str]]] = []
        self.cache_map: Dict[str, Dict[str, Any]] = {}

        self.cancel_event = threading.Event()
        self.worker: Optional[threading.Thread] = None

        # --- Top controls
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)

        self.btn_load = ttk.Button(top, text="Load Bundle ZIP", command=self.on_load_bundle)
        self.btn_load.pack(side="left")

        ttk.Separator(top, orient="vertical").pack(side="left", padx=6, fill="y")

        ttk.Label(top, text="Model:").pack(side="left")
        self.var_model = tk.StringVar(value=DEFAULT_MODEL)
        ttk.Entry(top, textvariable=self.var_model, width=18).pack(side="left", padx=(2, 8))

        ttk.Label(top, text="Batch:").pack(side="left")
        self.var_batch = tk.IntVar(value=DEFAULT_BATCH_SIZE)
        ttk.Spinbox(top, from_=1, to=500, textvariable=self.var_batch, width=6).pack(side="left", padx=(2, 8))

        ttk.Label(top, text="Trunc:").pack(side="left")
        self.var_trunc = tk.IntVar(value=DEFAULT_TRUNC_CHARS)
        ttk.Spinbox(top, from_=200, to=5000, increment=50, textvariable=self.var_trunc, width=7).pack(side="left", padx=(2, 8))

        self.var_use_cache = tk.BooleanVar(value=DEFAULT_USE_CACHE)
        ttk.Checkbutton(top, text="Use cache", variable=self.var_use_cache).pack(side="left", padx=(2, 8))

        self.btn_run = ttk.Button(top, text="Run EL", command=self.on_run_el, state="disabled")
        self.btn_run.pack(side="left")

        self.btn_cancel = ttk.Button(top, text="Cancel", command=self.on_cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=(6, 0))

        ttk.Separator(top, orient="vertical").pack(side="left", padx=6, fill="y")

        self.btn_export_csv = ttk.Button(top, text="Export EL_FULL.csv", command=self.on_export_csv, state="disabled")
        self.btn_export_csv.pack(side="left")
        self.btn_export_xlsx = ttk.Button(top, text="Export EL_FULL.xlsx", command=self.on_export_xlsx, state="disabled")
        self.btn_export_xlsx.pack(side="left", padx=(6, 0))
        self.btn_next_bundle = ttk.Button(top, text="Build next bundle ZIP", command=self.on_build_next_bundle, state="disabled")
        self.btn_next_bundle.pack(side="left", padx=(6, 0))

        self.lbl_key = ttk.Label(top, text="")
        self.lbl_key.pack(side="right")
        self._refresh_key_label()

        # --- Meta + progress
        meta = ttk.Frame(self)
        meta.pack(fill="x", padx=8)
        self.lbl_bundle_meta = ttk.Label(meta, text="")
        self.lbl_bundle_meta.pack(side="left")

        self.lbl_counts = ttk.Label(meta, text="")
        self.lbl_counts.pack(side="right")

        self.pbar = ttk.Progressbar(self, orient="horizontal", mode="determinate")
        self.pbar.pack(fill="x", padx=8, pady=(4, 6))

        # --- Main split: left criteria, right table/log
        main = ttk.Panedwindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=8, pady=6)

        # left panel
        left = ttk.Frame(main, width=320)
        main.add(left, weight=0)

        ttk.Label(left, text="EL Criteria (enabled)").pack(anchor="w")
        self.lst_crit = tk.Listbox(left, height=14)
        self.lst_crit.pack(fill="both", expand=False, pady=(2, 6))
        self.lst_crit.bind("<Double-Button-1>", self.on_criterion_doubleclick)

        ttk.Label(left, text="Warnings").pack(anchor="w")
        self.txt_warn = tk.Text(left, height=6, wrap="word", state="disabled")
        self.txt_warn.pack(fill="both", expand=True, pady=(2, 6))

        # right panel
        right = ttk.Frame(main)
        main.add(right, weight=1)

        # table
        self.table_columns = [
            "local_id", "title", "year",
            "el_outcome", "el_failed_ids", "el_missing_ids", "el_uncertain_ids",
        ]
        self.table = DataTable(right, self.table_columns)
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<Double-Button-1>", self.on_row_doubleclick)

        # log
        ttk.Label(right, text="Log").pack(anchor="w", pady=(6, 0))
        self.txt_log = tk.Text(right, height=8, wrap="word", state="disabled")
        self.txt_log.pack(fill="x", expand=False)

    # -------- UI helpers
    def _refresh_key_label(self):
        self.lbl_key.configure(text=("OPENAI_API_KEY ✓" if _has_openai_key() else "OPENAI_API_KEY ✗"))

    def _log(self, msg: str):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", msg)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _set_warn(self, lines: List[str]):
        self.txt_warn.configure(state="normal")
        self.txt_warn.delete("1.0", "end")
        self.txt_warn.insert("end", "\n".join(lines) if lines else "(none)")
        self.txt_warn.configure(state="disabled")

    def _refresh_counts_label(self):
        if not self.bundle:
            self.lbl_counts.configure(text="")
            return
        pr = self.bundle.parse
        msg = f"Rows: {len(pr.rows)} | Skipped: {len(pr.skipped)}"
        if self.counts:
            msg += (
                f" | OUT: {self.counts.get('OUT',0)}"
                f" | PASS_CLEAN: {self.counts.get('PASS_CLEAN',0)}"
                f" | PASS_FLAGGED: {self.counts.get('PASS_FLAGGED',0)}"
            )
        self.lbl_counts.configure(text=msg)

    def _set_controls_running(self, running: bool):
        self.btn_cancel.configure(state=("normal" if running else "disabled"))
        self.btn_run.configure(state=("disabled" if running else ("normal" if self.bundle else "disabled")))
        self.btn_load.configure(state=("disabled" if running else "normal"))
        self.btn_export_csv.configure(state=("disabled" if running else ("normal" if self.full_rows else "disabled")))
        self.btn_export_xlsx.configure(state=("disabled" if running else ("normal" if self.full_rows else "disabled")))
        self.btn_next_bundle.configure(state=("disabled" if running else ("normal" if self.full_rows else "disabled")))

    # -------- bundle load
    def on_load_bundle(self):
        p = filedialog.askopenfilename(
            title="Select ScreenA bundle ZIP",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")]
        )
        if not p:
            return
        self.bundle_zip_path = p
        self._refresh_key_label()

        try:
            self.bundle = _load_bundle(p)
        except Exception as e:
            self.bundle = None
            messagebox.showerror("Bundle load failed", str(e))
            return

        # read cache from bundle if present
        self.cache_map = {}
        try:
            with zipfile.ZipFile(p, "r") as zf:
                root = self.bundle.root
                mem = zf.namelist()
                cache_member = root + EL_CACHE_REL
                if cache_member in mem:
                    self.cache_map = _load_cache_from_jsonl(_decode_bytes(_read_zip_bytes(zf, cache_member)))
        except Exception:
            self.cache_map = {}

        # meta label
        m = self.bundle.manifest
        schema = _safe_str(m.get("bundle_schema", m.get("schema", ""))).strip() or "unknown"
        created_at = _safe_str(m.get("created_at", "")).strip()
        created_by = _safe_str(m.get("created_by", "")).strip()
        stages = ((m.get("pipeline", {}) or {}).get("stages", None)) or ((m.get("pipeline_state", {}) or {}).get("stages", None)) or {}
        st_el = _safe_str(stages.get("EL", "")).strip() or "unknown"
        self.lbl_bundle_meta.configure(text=f"schema={schema} | created_at={created_at} | created_by={created_by} | EL={st_el}")

        # criteria list
        self.lst_crit.delete(0, "end")
        crits = [c for c in self.bundle.criteria.criteria if c.enabled]
        for c in crits:
            lbl = f"{c.id}  thr={c.threshold:g}  → {c.source_text[:80]}"
            self.lst_crit.insert("end", lbl)

        self._set_warn(self.bundle.criteria.warnings)

        # reset results
        self.full_rows = []
        self.survivors = []
        self.counts = {}
        self.crit_impacts = {}
        self.row_eval_lists = []

        # set table to raw rows
        self.table.set_rows(self.bundle.parse.rows[:2000])  # show first 2000 pre-run for responsiveness
        self._refresh_counts_label()

        self.btn_run.configure(state="normal")

    # -------- run EL
    def on_run_el(self):
        if not self.bundle or self.worker:
            return

        model = self.var_model.get().strip() or DEFAULT_MODEL
        trunc_chars = int(self.var_trunc.get())
        batch_size = int(self.var_batch.get())
        use_cache = bool(self.var_use_cache.get())

        self.cancel_event.clear()
        self.pbar.configure(value=0.0, maximum=100.0)
        self._set_controls_running(True)

        def progress_cb(frac: float):
            # called from worker; route to UI thread
            self.after(0, lambda: self.pbar.configure(value=max(0.0, min(100.0, frac * 100.0))))

        def progress_evt(evt: Dict[str, Any]):
            # optional structured events for advanced UI; currently logs minimal
            kind = _safe_str(evt.get("kind",""))
            sub = _safe_str(evt.get("sub",""))
            if kind == "l_batch" and sub == "sending":
                bi = evt.get("batch_idx"); bt = evt.get("batch_total")
                ci = evt.get("crit_idx"); ct = evt.get("crit_total")
                self.after(0, lambda: self._log(f"[LLM] criterion {ci}/{ct} batch {bi}/{bt} sending...\n"))

        def work():
            try:
                full_rows, survivors, counts, crit_impacts, row_eval_lists, cache_out = run_el_screen(
                    self.bundle.parse,
                    self.bundle.criteria,
                    model=model,
                    trunc_chars=trunc_chars,
                    batch_size=batch_size,
                    use_cache=use_cache,
                    cache_in=self.cache_map if use_cache else {},
                    cancel_event=self.cancel_event,
                    log_cb=lambda s: self.after(0, lambda: self._log(s)),
                    progress_cb=progress_cb,
                    progress_evt=progress_evt,
                )
                if self.cancel_event.is_set():
                    self.after(0, lambda: self._log("\n[CANCELLED]\n"))
                    return
                self.full_rows = full_rows
                self.survivors = survivors
                self.counts = counts
                self.crit_impacts = crit_impacts
                self.row_eval_lists = row_eval_lists
                self.cache_map = cache_out

                # update table to full rows (show outcomes)
                self.after(0, lambda: self.table.set_rows(self.full_rows))
                self.after(0, self._refresh_counts_label)

                # enable exports
                self.after(0, lambda: self.btn_export_csv.configure(state="normal"))
                self.after(0, lambda: self.btn_export_xlsx.configure(state="normal"))
                self.after(0, lambda: self.btn_next_bundle.configure(state="normal"))

            except Exception as e:
                self.after(0, lambda m=str(e): messagebox.showerror("EL run failed", m))
            finally:
                self.after(0, lambda: self._set_controls_running(False))
                self.worker = None

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def on_cancel(self):
        self.cancel_event.set()
        self._log("\n[Cancel requested]\n")

    # -------- exports
    def on_export_csv(self):
        if not self.full_rows:
            return
        p = filedialog.asksaveasfilename(
            title="Save EL_FULL.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")]
        )
        if not p:
            return
        header = list(self.full_rows[0].keys())
        _write_csv(p, header, self.full_rows)
        messagebox.showinfo("Export", f"Saved:\n{p}")

    def on_export_xlsx(self):
        # Keep it standard-library only: write CSV next to requested xlsx name.
        if not self.full_rows:
            return
        p = filedialog.asksaveasfilename(
            title="Save EL_FULL.xlsx (fallback to CSV if no writer)",
            defaultextension=".xlsx",
            filetypes=[("XLSX", "*.xlsx"), ("CSV", "*.csv")]
        )
        if not p:
            return
        # If user asked CSV, do CSV.
        if p.lower().endswith(".csv"):
            header = list(self.full_rows[0].keys())
            _write_csv(p, header, self.full_rows)
            messagebox.showinfo("Export", f"Saved:\n{p}")
            return

        # Minimal XLSX writer without dependencies is non-trivial; provide a CSV next to it.
        csv_path = p[:-5] + ".csv"
        header = list(self.full_rows[0].keys())
        _write_csv(csv_path, header, self.full_rows)
        messagebox.showinfo("Export", f"No XLSX writer bundled.\nSaved CSV instead:\n{csv_path}")

    def on_build_next_bundle(self):
        if not self.bundle or not self.full_rows:
            return
        out_zip = filedialog.asksaveasfilename(
            title="Save next bundle ZIP (post-EL)",
            defaultextension=".zip",
            filetypes=[("ZIP", "*.zip")]
        )
        if not out_zip:
            return

        # Prepare output structure in-memory then zip.
        # - manifest.json updated
        # - data/current.csv replaced with survivors
        # - reports/EL_FULL.csv + reports/EL_SURVIVORS.csv
        # - input_errors.csv from skipped
        # - cache/EL_cache.jsonl if enabled
        try:
            with zipfile.ZipFile(self.bundle.zip_path, "r") as zf_in:
                members = zf_in.namelist()
                root = self.bundle.root

                # read original manifest
                manifest = dict(self.bundle.manifest)

                # update pipeline stage mark (tolerate both schemas)
                def _set_stage(m: Dict[str, Any], key: str, value: str):
                    if "pipeline" in m and isinstance(m.get("pipeline"), dict):
                        m["pipeline"].setdefault("stages", {})
                        m["pipeline"]["stages"][key] = value
                    if "pipeline_state" in m and isinstance(m.get("pipeline_state"), dict):
                        m["pipeline_state"].setdefault("stages", {})
                        m["pipeline_state"]["stages"][key] = value

                _set_stage(manifest, "EL", "done")
                manifest["updated_at"] = datetime.utcnow().isoformat() + "Z"

                # write new zip
                with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf_out:
                    # copy everything except data/current.csv and reports we replace
                    skip_prefixes = {
                        root + "data/current.csv",
                        root + f"{REPORTS_DIR_REL}/EL_FULL.csv",
                        root + f"{REPORTS_DIR_REL}/EL_SURVIVORS.csv",
                        root + "data/input_errors.csv",
                        root + EL_CACHE_REL,
                        root + "manifest.json",
                    }
                    for m in members:
                        if m in skip_prefixes:
                            continue
                        # also avoid directories
                        if m.endswith("/"):
                            continue
                        zf_out.writestr(m, _read_zip_bytes(zf_in, m))

                    # manifest
                    zf_out.writestr(root + "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

                    # data/current.csv survivors
                    # Use original header order (minus EL columns)
                    header = list(self.bundle.parse.header)
                    # guarantee local_id present
                    if "local_id" not in header:
                        header = ["local_id"] + header
                    buf = io.StringIO()
                    w = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
                    w.writeheader()
                    for r in self.survivors:
                        w.writerow({k: r.get(k, "") for k in header})
                    zf_out.writestr(root + "data/current.csv", buf.getvalue())

                    # reports
                    rep_full = root + f"{REPORTS_DIR_REL}/EL_FULL.csv"
                    rep_surv = root + f"{REPORTS_DIR_REL}/EL_SURVIVORS.csv"
                    # full
                    header_full = list(self.full_rows[0].keys())
                    buf2 = io.StringIO()
                    w2 = csv.DictWriter(buf2, fieldnames=header_full, extrasaction="ignore")
                    w2.writeheader()
                    for r in self.full_rows:
                        w2.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in header_full})
                    zf_out.writestr(rep_full, buf2.getvalue())

                    # survivors report = same schema as input current.csv
                    buf3 = io.StringIO()
                    w3 = csv.DictWriter(buf3, fieldnames=header, extrasaction="ignore")
                    w3.writeheader()
                    for r in self.survivors:
                        w3.writerow({k: r.get(k, "") for k in header})
                    zf_out.writestr(rep_surv, buf3.getvalue())

                    # input errors
                    if self.bundle.parse.skipped:
                        buf4 = io.StringIO()
                        # flatten skipped
                        err_header = ["reason", "row_json"]
                        w4 = csv.DictWriter(buf4, fieldnames=err_header)
                        w4.writeheader()
                        for e in self.bundle.parse.skipped:
                            w4.writerow({"reason": _safe_str(e.get("reason","")), "row_json": json.dumps(e.get("row", {}), ensure_ascii=False)})
                        zf_out.writestr(root + "data/input_errors.csv", buf4.getvalue())

                    # cache
                    if self.var_use_cache.get():
                        zf_out.writestr(root + EL_CACHE_REL, _dump_cache_to_jsonl(self.cache_map))

            messagebox.showinfo("Next bundle", f"Saved:\n{out_zip}")
        except Exception as e:
            messagebox.showerror("Next bundle failed", str(e))

    # -------- details
    def on_row_doubleclick(self, _evt=None):
        row = self.table.get_selected_row()
        if not row:
            return
        top = tk.Toplevel(self)
        top.title(f"Row {row.get('local_id','')}")
        top.geometry("850x600")

        txt = tk.Text(top, wrap="word")
        txt.pack(fill="both", expand=True)

        def add(title: str, content: str):
            txt.insert("end", f"\n=== {title} ===\n")
            txt.insert("end", content + "\n")

        add("local_id", _safe_str(row.get("local_id","")))
        add("title", _safe_str(row.get("title","")))
        add("abstract", _safe_str(row.get("abstract","")))
        add("keywords", _safe_str(row.get("keywords","")))
        add("EL outcome", _safe_str(row.get("el_outcome","")))
        add("EL summary", _safe_str(row.get("el_reason_summary","")))

        ev = _safe_str(row.get("el_evidence_json","{}"))
        try:
            evj = json.loads(ev)
            add("EL evidence (json)", json.dumps(evj, ensure_ascii=False, indent=2)[:15000])
        except Exception:
            add("EL evidence (raw)", ev[:15000])

        txt.configure(state="disabled")

    def on_criterion_doubleclick(self, _evt=None):
        # Filter table to rows touched by selected criterion (failed/missing/uncertain/met)
        if not self.full_rows or not self.bundle:
            return
        sel = self.lst_crit.curselection()
        if not sel:
            return
        # parse criterion id from listbox line
        line = self.lst_crit.get(sel[0])
        cid = line.split()[0].strip()

        touched: List[Dict[str, Any]] = []
        for r in self.full_rows:
            parts = ",".join([
                _safe_str(r.get("el_failed_ids","")),
                _safe_str(r.get("el_missing_ids","")),
                _safe_str(r.get("el_uncertain_ids","")),
                _safe_str(r.get("el_met_ids","")),
            ])
            if cid in {p.strip() for p in parts.split(",") if p.strip()}:
                touched.append(r)

        if touched:
            self._log(f"\n[Filter] Criterion {cid}: showing {len(touched)} rows touched.\n")
            self.table.set_rows(touched)
        else:
            self._log(f"\n[Filter] Criterion {cid}: no touched rows.\n")

