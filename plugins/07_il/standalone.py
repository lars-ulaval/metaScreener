
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""standalone.py - Plugin 07 IL: standalone-app shell.

After Conv 6 / Commit 4, this module owns the StandaloneILPlugin class:
the standalone-app shell wrapper used when running IL outside the main
metaScreener application. Mirrors plugins/06_el/standalone.py.

Composes the DataTable widget that ILView uses and calls into the same
engine entry point (run_il_screen). The split from ui.py is purely
organizational; ILView is the production tab UI, StandaloneILPlugin is
the development/test driver.
"""

import csv
import io
import json
import os
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .plugin import (
    BundleInfo,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MODEL,
    DEFAULT_TRUNC_CHARS,
    DEFAULT_USE_CACHE,
    FINAL_REPORT_REL,
    IL_CACHE_REL,
    REPORTS_DIR_REL,
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
from .ui import DataTable

class StandaloneILPlugin(ttk.Frame):
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

        self.btn_run = ttk.Button(top, text="Run IL", command=self.on_run_il, state="disabled")
        self.btn_run.pack(side="left")

        self.btn_cancel = ttk.Button(top, text="Cancel", command=self.on_cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=(6, 0))

        ttk.Separator(top, orient="vertical").pack(side="left", padx=6, fill="y")

        self.btn_export_csv = ttk.Button(top, text="Export IL_FULL.csv", command=self.on_export_csv, state="disabled")
        self.btn_export_csv.pack(side="left")
        self.btn_export_xlsx = ttk.Button(top, text="Export IL_FULL.xlsx", command=self.on_export_xlsx, state="disabled")
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

        ttk.Label(left, text="IL Criteria (enabled)").pack(anchor="w")
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
            "il_outcome", "il_failed_ids", "il_missing_ids", "il_uncertain_ids",
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
                f" | REVIEW: {self.counts.get('REVIEW',0)}"
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
                cache_member = root + IL_CACHE_REL
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
        st_il = _safe_str(stages.get("IL", "")).strip() or "unknown"
        self.lbl_bundle_meta.configure(text=f"schema={schema} | created_at={created_at} | created_by={created_by} | IL={st_il}")

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

    # -------- run IL
    def on_run_il(self):
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
                full_rows, survivors, counts, crit_impacts, row_eval_lists, cache_out = run_il_screen(
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
                self.after(0, lambda m=str(e): messagebox.showerror("IL run failed", m))
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
            title="Save IL_FULL.csv",
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
            title="Save IL_FULL.xlsx (fallback to CSV if no writer)",
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
            title="Save next bundle ZIP (post-IL)",
            defaultextension=".zip",
            filetypes=[("ZIP", "*.zip")]
        )
        if not out_zip:
            return

        # Prepare output structure in-memory then zip.
        # - manifest.json updated
        # - data/current.csv replaced with survivors
        # - reports/IL_FULL.csv + reports/IL_SURVIVORS.csv
        # - input_errors.csv from skipped
        # - cache/IL_cache.jsonl if enabled
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

                _set_stage(manifest, "IL", "done")
                manifest["updated_at"] = datetime.utcnow().isoformat() + "Z"

                # write new zip
                with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf_out:
                    # copy everything except data/current.csv and reports we replace
                    skip_prefixes = {
                        root + "data/current.csv",
                        root + f"{REPORTS_DIR_REL}/IL_FULL.csv",
                        root + f"{REPORTS_DIR_REL}/IL_SURVIVORS.csv",
                    root + FINAL_REPORT_REL,
                        root + "data/input_errors.csv",
                        root + IL_CACHE_REL,
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
                    rep_full = root + f"{REPORTS_DIR_REL}/IL_FULL.csv"
                    rep_surv = root + f"{REPORTS_DIR_REL}/IL_SURVIVORS.csv"
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
                        zf_out.writestr(root + IL_CACHE_REL, _dump_cache_to_jsonl(self.cache_map))

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
        add("IL outcome", _safe_str(row.get("il_outcome","")))
        add("EL summary", _safe_str(row.get("il_reason_summary","")))

        ev = _safe_str(row.get("il_evidence_json","{}"))
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
                _safe_str(r.get("il_failed_ids","")),
                _safe_str(r.get("il_missing_ids","")),
                _safe_str(r.get("il_uncertain_ids","")),
                _safe_str(r.get("il_met_ids","")),
            ])
            if cid in {p.strip() for p in parts.split(",") if p.strip()}:
                touched.append(r)

        if touched:
            self._log(f"\n[Filter] Criterion {cid}: showing {len(touched)} rows touched.\n")
            self.table.set_rows(touched)
        else:
            self._log(f"\n[Filter] Criterion {cid}: no touched rows.\n")

