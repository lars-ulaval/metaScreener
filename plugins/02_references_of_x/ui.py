# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
ui.py — Tkinter UI for "References-of-X — AI v1"

Adds two blocking floating modals:
  • ResolveModal  (for Resolve Metadata)
  • FetchModal    (for Fetch References)

Design choices (as agreed):
  - Two separate modals
  - Blocking the main UI (grab_set)
  - Floating (always on top)
  - Single-page layout
  - Show ETA & throughput and percent complete
  - Per-source hit-rates (OA/CR/S2)
  - Item-only progress (no per-field provenance)
  - Queue preview (Next N items)
  - Stop/Cancel, Pause/Resume
  - Keep modal open after cancel (wrap-up)
  - Simple error counter
  - Color-blind minimal (icons/text), mouse only

Run:
    python ui.py
"""

from __future__ import annotations

import os
import time
import threading
import traceback
from datetime import datetime
from typing import Dict, List, Optional, Callable

import tkinter as tk
from tkinter import ttk
import tkinter.messagebox as messagebox
import tkinter.filedialog as filedialog

# Core services & types
from .services import (
    Ingestor, MetaResolver, RefFetcher, Exporter, dedup_items,
    BibItem, CancellationToken, LoggerProto,
)

# --------------------------------------------------------------------------------------
# Tk Logger
# --------------------------------------------------------------------------------------

class TkUiLogger(LoggerProto):
    """Minimal logger that writes to a Tk Text widget and (optionally) a file."""
    def __init__(self, text_widget: tk.Text, log_to_file_var: tk.BooleanVar, logs_dir: str, tk_root: tk.Tk):
        self.text_widget = text_widget
        self.log_to_file_var = log_to_file_var
        self.logs_dir = logs_dir
        self.root = tk_root
        self.file_handle = None
        os.makedirs(self.logs_dir, exist_ok=True)

    def _open_file_if_needed(self):
        if self.file_handle is None and self.log_to_file_var.get():
            fname = datetime.now().strftime("%Y-%m-%d_%H%M%S.log")
            self.file_handle = open(os.path.join(self.logs_dir, fname), "w", encoding="utf-8")

    def log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"

        def _append():
            try:
                self.text_widget.insert(tk.END, line)
                self.text_widget.see(tk.END)
            except Exception:
                pass

        self.root.after(0, _append)

        if self.log_to_file_var.get():
            self._open_file_if_needed()
            try:
                self.file_handle.write(line)
                self.file_handle.flush()
            except Exception:
                pass

    def close(self) -> None:
        try:
            if self.file_handle:
                self.file_handle.close()
        except Exception:
            pass
        self.file_handle = None


# --------------------------------------------------------------------------------------
# Blocking Floating Modals (single-page)
# --------------------------------------------------------------------------------------

class _RunControl:
    """UI-level run control. Services already accept CancellationToken; we complement with 'paused'."""
    def __init__(self, cancel_token: CancellationToken):
        self.cancel_token = cancel_token
        self._paused = False
        self._lock = threading.Lock()

    def pause(self):
        with self._lock:
            self._paused = True

    def resume(self):
        with self._lock:
            self._paused = False

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def wait_if_paused(self, poll_s: float = 0.1):
        while self.paused and not self.cancel_token.cancelled:
            time.sleep(poll_s)


class _BaseModal(tk.Toplevel):
    """Shared modal skeleton with header, progress bar, telemetry row, current item, queue preview, footer."""
    def __init__(self, parent: tk.Tk, title: str, total: int, next_n: int = 8):
        super().__init__(parent)
        self.parent = parent
        self.title(title)
        # Floating + blocking
        try:
            self.attributes("-topmost", True)
        except Exception:
            pass
        self.transient(parent)
        self.grab_set()

        self.resizable(True, False)
        self.protocol("WM_DELETE_WINDOW", self._on_attempt_close)  # prevent closing while running

        self.total = max(0, int(total))
        self.next_n = max(0, int(next_n))

        # State
        self._start_ts = time.time()
        self._done = 0
        self._errors = 0
        self._throughput = 0.0
        self._eta_s = 0.0
        self._running = True    # flips to False at finish/cancel
        self._can_close = False # enable Close button only after finish/cancel

        # Build UI
        self._build_ui()

    # ---- UI layout
    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        # Header (item/total, percent, ETA, tps)
        self.lbl_header = ttk.Label(root, text="0 / 0  (0%)   ETA: —   Rate: —/s", font=("", 11, "bold"))
        self.lbl_header.pack(anchor="w", pady=(0, 8))

        # Progress
        self.pb = ttk.Progressbar(root, orient="horizontal", mode="determinate", length=420)
        self.pb.pack(fill="x")
        self.pb["maximum"] = max(self.total, 1)
        self.pb["value"] = 0

        # Telemetry row (per-source + errors)
        tele = ttk.Frame(root)
        tele.pack(fill="x", pady=(10, 6))
        self.var_hits_oa = tk.StringVar(value="OA: 0")
        self.var_hits_cr = tk.StringVar(value="CR: 0")
        self.var_hits_s2 = tk.StringVar(value="S2: 0")
        self.var_errors  = tk.StringVar(value="Errors: 0")
        # Use icons/text only (color-blind minimal)
        ttk.Label(tele, text="⟲ ").pack(side="left")
        ttk.Label(tele, textvariable=self.var_hits_oa).pack(side="left", padx=(0, 12))
        ttk.Label(tele, textvariable=self.var_hits_cr).pack(side="left", padx=(0, 12))
        ttk.Label(tele, textvariable=self.var_hits_s2).pack(side="left", padx=(0, 12))
        ttk.Label(tele, text="⚠ ").pack(side="left")
        ttk.Label(tele, textvariable=self.var_errors).pack(side="left")

        # Current item summary
        cur = ttk.LabelFrame(root, text="Current item")
        cur.pack(fill="x", pady=(6, 6))
        self.var_cur_id = tk.StringVar(value="—")
        self.var_cur_line1 = tk.StringVar(value="—")
        self.var_cur_title = tk.StringVar(value="—")

        row1 = ttk.Frame(cur); row1.pack(fill="x")
        ttk.Label(row1, text="ID: ").pack(side="left")
        ttk.Label(row1, textvariable=self.var_cur_id).pack(side="left")

        row2 = ttk.Frame(cur); row2.pack(fill="x")
        ttk.Label(row2, textvariable=self.var_cur_line1, wraplength=780, justify="left").pack(side="left")

        row3 = ttk.Frame(cur); row3.pack(fill="x")
        ttk.Label(row3, textvariable=self.var_cur_title, wraplength=780, justify="left").pack(side="left")

        # Queue preview (Next N)
        qf = ttk.LabelFrame(root, text="Next items")
        qf.pack(fill="both", pady=(6, 6))
        self.list_next = tk.Listbox(qf, height=6)
        self.list_next.pack(fill="both", expand=True)

        # Footer: Pause/Resume, Stop/Cancel, Close
        foot = ttk.Frame(root)
        foot.pack(fill="x", pady=(8, 0))
        self.btn_pause = ttk.Button(foot, text="Pause", command=self._on_pause)
        self.btn_resume = ttk.Button(foot, text="Resume", command=self._on_resume, state="disabled")
        self.btn_stop = ttk.Button(foot, text="Stop / Cancel", command=self._on_stop, style="Danger.TButton")
        self.btn_close = ttk.Button(foot, text="Close", command=self._on_close, state="disabled")
        self.btn_pause.pack(side="left")
        self.btn_resume.pack(side="left", padx=(6, 0))
        self.btn_stop.pack(side="left", padx=(12, 0))
        self.btn_close.pack(side="right")

        # Simple style for "danger"
        try:
            style = ttk.Style(self)
            style.configure("Danger.TButton")
        except Exception:
            pass

    # ---- lifecycle controls
    def _on_attempt_close(self):
        # Keep modal open while running (must Stop first)
        if self._can_close:
            self.destroy()
        else:
            # do nothing; blocking modal
            pass

    def _on_close(self):
        if self._can_close:
            self.destroy()

    def _on_pause(self):
        self._request_pause()

    def _on_resume(self):
        self._request_resume()

    def _on_stop(self):
        self._request_cancel()

    # ---- overridables (UI -> worker)
    def _request_pause(self): ...
    def _request_resume(self): ...
    def _request_cancel(self): ...

    # ---- updates from worker
    def update_progress(
        self,
        done: int,
        total: int,
        *,
        hits_oa: int,
        hits_cr: int,
        hits_s2: int,
        errors: int,
        cur_id: str,
        cur_line1: str,
        cur_title: str,
        next_labels: List[str],
        start_ts: float | None = None,
    ):
        if start_ts is not None:
            self._start_ts = start_ts

        self._done = done
        self.total = total
        self.pb["maximum"] = max(total, 1)
        self.pb["value"] = done

        # ETA & throughput
        elapsed = max(0.001, time.time() - self._start_ts)
        self._throughput = done / elapsed
        remaining = max(0, total - done)
        self._eta_s = remaining / self._throughput if self._throughput > 0 else 0.0

        pct = int(round((done / total) * 100)) if total > 0 else 0
        eta_txt = self._fmt_eta(self._eta_s)
        rate_txt = f"{self._throughput:.2f}/s" if self._throughput > 0 else "—/s"
        self.lbl_header.config(text=f"{done} / {total}  ({pct}%)   ETA: {eta_txt}   Rate: {rate_txt}")

        self.var_hits_oa.set(f"OA: {hits_oa}")
        self.var_hits_cr.set(f"CR: {hits_cr}")
        self.var_hits_s2.set(f"S2: {hits_s2}")
        self.var_errors.set(f"Errors: {errors}")

        self.var_cur_id.set(cur_id or "—")
        self.var_cur_line1.set(cur_line1 or "—")
        self.var_cur_title.set(cur_title or "—")

        self.list_next.delete(0, tk.END)
        for s in next_labels:
            self.list_next.insert(tk.END, s)

        self.update_idletasks()

    def mark_finished(self, cancelled: bool = False):
        self._running = False
        self._can_close = True
        # Disable pause/resume/stop; enable close
        self.btn_pause.config(state="disabled")
        self.btn_resume.config(state="disabled")
        self.btn_stop.config(state="disabled")
        self.btn_close.config(state="normal")
        # Keep window open (user must click Close)
        self.attributes("-topmost", True)  # keep floating

    @staticmethod
    def _fmt_eta(sec: float) -> str:
        s = int(round(sec))
        if s <= 0:
            return "—"
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}h {m}m {s}s"
        if m > 0:
            return f"{m}m {s}s"
        return f"{s}s"


class ResolveModal(_BaseModal):
    def __init__(self, parent: tk.Tk, total: int, on_pause: Callable[[], None], on_resume: Callable[[], None], on_cancel: Callable[[], None]):
        super().__init__(parent, "Resolve Metadata — Progress", total)
        self._on_pause_cb = on_pause
        self._on_resume_cb = on_resume
        self._on_cancel_cb = on_cancel

    def _request_pause(self):
        self.btn_pause.config(state="disabled")
        self.btn_resume.config(state="normal")
        self._on_pause_cb()

    def _request_resume(self):
        self.btn_resume.config(state="disabled")
        self.btn_pause.config(state="normal")
        self._on_resume_cb()

    def _request_cancel(self):
        # Freeze controls except Close; keep modal open
        self.btn_pause.config(state="disabled")
        self.btn_resume.config(state="disabled")
        self.btn_stop.config(state="disabled")
        self._on_cancel_cb()


class FetchModal(_BaseModal):
    def __init__(self, parent: tk.Tk, total: int, on_pause: Callable[[], None], on_resume: Callable[[], None], on_cancel: Callable[[], None]):
        super().__init__(parent, "Fetch References — Progress", total)
        self._on_pause_cb = on_pause
        self._on_resume_cb = on_resume
        self._on_cancel_cb = on_cancel

    def _request_pause(self):
        self.btn_pause.config(state="disabled")
        self.btn_resume.config(state="normal")
        self._on_pause_cb()

    def _request_resume(self):
        self.btn_resume.config(state="disabled")
        self.btn_pause.config(state="normal")
        self._on_resume_cb()

    def _request_cancel(self):
        self.btn_pause.config(state="disabled")
        self.btn_resume.config(state="disabled")
        self.btn_stop.config(state="disabled")
        self._on_cancel_cb()


# --------------------------------------------------------------------------------------
# Tkinter View
# --------------------------------------------------------------------------------------

class ReferencesOfXView(ttk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.root = self.winfo_toplevel()

        # State
        self.log_to_file = tk.BooleanVar(value=False)
        self.results_X: List[BibItem] = []
        self.refs_by_X: Dict[str, List[BibItem]] = {}
        self.vector_A: List[BibItem] = []
        self.cancel_token = CancellationToken()
        self.worker: Optional[threading.Thread] = None
        self.cache_dir = os.path.join(os.path.expanduser("~"), ".refx_cache")

        # Build UI
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        # Top bar
        bar = ttk.Frame(self, padding=12)
        bar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(bar, text="Import Text…", command=self.on_import_text).pack(side=tk.LEFT)
        ttk.Button(bar, text="Import CSV/XLSX…", command=self.on_import_file).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(bar, text="Resolve Metadata", command=self.on_resolve_metadata).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Button(bar, text="Fetch References", command=self.on_fetch_refs).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(bar, text="Build A", command=self.on_build_A).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(bar, text="Export…", command=self.on_export).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(bar, text="Export Meta Sources…", command=self.on_export_meta_sources).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(bar, text="Stop", command=self.on_stop).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Checkbutton(bar, text="Log to file", variable=self.log_to_file).pack(side=tk.RIGHT)

        # Progress ribbon
        ribbon = ttk.Frame(self, padding=(12, 6))
        ribbon.pack(side=tk.TOP, fill=tk.X)
        self.step_labels = {
            "Ingest": ttk.Label(ribbon, text="◻ Ingest"),
            "Normalize": ttk.Label(ribbon, text="◻ Normalize"),
            "Enrich": ttk.Label(ribbon, text="◻ Enrich"),
            "Fetch Refs": ttk.Label(ribbon, text="◻ Fetch Refs"),
            "Aggregate": ttk.Label(ribbon, text="◻ Aggregate"),
            "Export": ttk.Label(ribbon, text="◻ Export"),
        }
        for i, key in enumerate(self.step_labels.keys()):
            self.step_labels[key].grid(row=0, column=i, padx=6)

        # Tabs
        self.nb = ttk.Notebook(self)
        self.nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Tab X
        self.tab_x = ttk.Frame(self.nb)
        self.nb.add(self.tab_x, text="X (Clean List)")

        self.tree_x = self._make_table(self.tab_x, table_kind="x")
        self.tree_x.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # vertical scrollbar
        sbx = ttk.Scrollbar(self.tab_x, orient="vertical", command=self.tree_x.yview)
        sbx.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_x.configure(yscrollcommand=sbx.set)

        # horizontal scrollbar
        hbx = ttk.Scrollbar(self.tab_x, orient="horizontal", command=self.tree_x.xview)
        hbx.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree_x.configure(xscrollcommand=hbx.set)

        self.tree_x.bind("<Double-1>", self._on_cell_edit)

        # Tab References
        self.tab_refs = ttk.Frame(self.nb)
        self.nb.add(self.tab_refs, text="References (by X)")

        left = ttk.Frame(self.tab_refs)
        left.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(left, text="X items:").pack(anchor="w", padx=8, pady=(8, 0))
        self.list_x = tk.Listbox(left, height=20)
        self.list_x.pack(side=tk.TOP, fill=tk.Y, padx=8, pady=8)
        self.list_x.bind("<<ListboxSelect>>", self._on_select_x_for_refs)

        right = ttk.Frame(self.tab_refs)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree_refs = self._make_table(right, table_kind="refs")
        self.tree_refs.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # vertical scrollbar
        sbr = ttk.Scrollbar(right, orient="vertical", command=self.tree_refs.yview)
        sbr.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_refs.configure(yscrollcommand=sbr.set)

        # horizontal scrollbar
        hbr = ttk.Scrollbar(right, orient="horizontal", command=self.tree_refs.xview)
        hbr.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree_refs.configure(xscrollcommand=hbr.set)

        # Tab A
        self.tab_a = ttk.Frame(self.nb)
        self.nb.add(self.tab_a, text="A (Aggregate)")

        self.tree_a = self._make_table(self.tab_a, table_kind="a")
        self.tree_a.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # vertical scrollbar
        sba = ttk.Scrollbar(self.tab_a, orient="vertical", command=self.tree_a.yview)
        sba.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_a.configure(yscrollcommand=sba.set)

        # horizontal scrollbar
        hba = ttk.Scrollbar(self.tab_a, orient="horizontal", command=self.tree_a.xview)
        hba.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree_a.configure(xscrollcommand=hba.set)

        # Diagnostics
        self.tab_diag = ttk.Frame(self.nb)
        self.nb.add(self.tab_diag, text="Diagnostics")

        # wrap=None (no wrapping) to let horizontal scroll work
        self.log_text = tk.Text(self.tab_diag, wrap="none")
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # vertical scrollbar
        sbd = ttk.Scrollbar(self.tab_diag, orient="vertical", command=self.log_text.yview)
        sbd.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=sbd.set)

        # horizontal scrollbar
        sbdx = ttk.Scrollbar(self.tab_diag, orient="horizontal", command=self.log_text.xview)
        sbdx.pack(side=tk.BOTTOM, fill=tk.X)
        self.log_text.configure(xscrollcommand=sbdx.set)

    def _make_table(self, parent, table_kind: str = "x") -> ttk.Treeview:
        """
        table_kind: 'x' (main X with audit cols), 'refs', or 'a'
        """
        base_cols = [
            "local_id",
            "title",
            "first_author",
            "year",
            "doi",
            "pmid",
            "pmcid",
            "arxiv",
            "doc_type",
            "lang",
            "venue",
            "authors",
            "pages",
            "volume",
            "issue",
            "url",
            "open_access",
            "keywords",
            "status",
            "confidence",
            "parents",
            "abstract",
        ]

        if table_kind == "x":
            audit_cols = [
                "hit_openalex",
                "hit_crossref",
                "hit_semanticscholar",
                "match_strategy",
                "winner_source",
                "merge_summary",
                "missing_fields",
                "resolver_notes",
            ]
            cols = base_cols[:]
            insert_at = base_cols.index("keywords") + 1
            cols[insert_at:insert_at] = audit_cols
        else:
            cols = base_cols

        tree = ttk.Treeview(parent, columns=cols, show="headings", selectmode="extended")
        for c in cols:
            tree.heading(c, text=c)
            if c in ("title", "authors", "venue", "url", "abstract", "keywords", "resolver_notes", "merge_summary"):
                width = 280 if c in ("abstract", "resolver_notes", "merge_summary") else 200
            elif c in ("parents", "missing_fields"):
                width = 140
            elif c in ("doc_type", "lang", "open_access", "match_strategy", "winner_source"):
                width = 110
            elif c.startswith("hit_"):
                width = 90
            else:
                width = 100
            tree.column(c, width=width, stretch=True)

        tree.configure(xscrollcommand=lambda *args: None, yscrollcommand=lambda *args: None)
        return tree

    def set_step(self, key: str, status: str):
        lbl = self.step_labels.get(key)
        if not lbl:
            return
        if status == "running":
            lbl.config(text=f"● {key}")
        elif status == "done":
            lbl.config(text=f"✅ {key}")
        else:
            lbl.config(text=f"◻ {key}")

    def build_logger(self) -> TkUiLogger:
        return TkUiLogger(
            self.log_text,
            self.log_to_file,
            logs_dir=os.path.join(os.path.expanduser("~"), "refx_logs"),
            tk_root=self.root,
        )

    # ---------- Actions ----------
    def on_import_text(self):
        w = tk.Toplevel(self)
        w.title("Paste citations or scraper output")
        txt = tk.Text(w, width=100, height=25)
        txt.pack(fill=tk.BOTH, expand=True)
        btn = ttk.Button(w, text="Import", command=lambda: self._do_ingest_text(w, txt.get("1.0", "end-1c")))
        btn.pack(pady=6)

    def _do_ingest_text(self, win: tk.Toplevel, raw: str):
        win.destroy()
        logger = self.build_logger()
        ing = Ingestor(logger)
        self.set_step("Ingest", "running")
        self.results_X = ing.from_text(raw, source_label="pasted_text")
        self._refresh_x_table()
        self.set_step("Ingest", "done")
        logger.close()

    def on_import_file(self):
        path = filedialog.askopenfilename(
            title="Select CSV/XLSX",
            filetypes=[("CSV/XLSX", "*.csv;*.xlsx;*.xls"), ("All", "*.*")],
        )
        if not path:
            return
        logger = self.build_logger()
        ing = Ingestor(logger)
        self.set_step("Ingest", "running")
        try:
            self.results_X = ing.from_csv_or_xlsx(path)
            self._refresh_x_table()
            self.set_step("Ingest", "done")
            if not self.results_X:
                # A readable file that yields nothing looks exactly like a
                # successful import of an empty search. Say so explicitly.
                messagebox.showwarning(
                    "No records imported",
                    "The file was read successfully but produced 0 records.\n\n"
                    "Check that it has data rows below the header and a "
                    "recognisable 'title' or 'doi' column.",
                )
        except Exception as e:
            logger.log("TRACE:\n" + traceback.format_exc())
            messagebox.showerror("Import error", str(e))
            self.set_step("Ingest", "◻")
        finally:
            logger.close()

    # ------------------ RESOLVE MODAL WORKFLOW ------------------

    def on_resolve_metadata(self):
        if not self.results_X:
            messagebox.showinfo("No data", "Import X first.")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Busy", "Another task is running. Click Stop to cancel.")
            return

        logger = self.build_logger()
        resolver = MetaResolver(logger, cache_dir=os.path.join(self.cache_dir, "meta"))
        self.cancel_token = CancellationToken()
        runctl = _RunControl(self.cancel_token)

        total = len(self.results_X)
        self.set_step("Normalize", "running")
        self.set_step("Enrich", "running")

        modal = ResolveModal(
            self.root,
            total=total,
            on_pause=runctl.pause,
            on_resume=runctl.resume,
            on_cancel=self.cancel_token.cancel,
        )

        # Cumulative per-source hits & errors
        hits_oa = hits_cr = hits_s2 = 0
        errors = 0
        start_ts = time.time()

        def work():
            nonlocal hits_oa, hits_cr, hits_s2, errors, start_ts
            try:
                out: List[BibItem] = []
                N = len(self.results_X)

                for i, bi in enumerate(self.results_X, 1):
                    # Cooperative controls
                    if self.cancel_token.cancelled:
                        break
                    runctl.wait_if_paused()

                    # Assign/refresh local_id deterministically
                    bi.local_id = f"X{i:03d}"

                    # Resolve one item
                    try:
                        res = resolver.resolve_item(bi, self.cancel_token)
                    except Exception:
                        errors += 1
                        logger.log("TRACE:\n" + traceback.format_exc())
                        res = bi  # keep original when error

                    # Update counts (per-source hits)
                    try:
                        if getattr(res, "hit_openalex", None): hits_oa += 1
                        if getattr(res, "hit_crossref", None): hits_cr += 1
                        if getattr(res, "hit_semanticscholar", None): hits_s2 += 1
                    except Exception:
                        pass

                    out.append(res)

                    # UI update (item-only progress)
                    def _ui_tick():
                        # Current item summary
                        cur_id = res.local_id or f"X{i:03d}"
                        line1 = f"{res.first_author or '—'} {res.year or ''}   {res.venue or ''}"
                        title = (res.title or "—")
                        title = (title[:120].rstrip() + "…") if len(title) > 120 else title
                        # Next N labels
                        next_labels = []
                        for j in range(i+1, min(i+1+8, N+1)):
                            nb = self.results_X[j-1]
                            t = (nb.title or "—")
                            t = (t[:80].rstrip() + "…") if len(t) > 80 else t
                            next_labels.append(f"X{j:03d} — {nb.first_author or '—'} {nb.year or ''} — {t}")
                        modal.update_progress(
                            done=i,
                            total=N,
                            hits_oa=hits_oa,
                            hits_cr=hits_cr,
                            hits_s2=hits_s2,
                            errors=errors,
                            cur_id=cur_id,
                            cur_line1=line1.strip(),
                            cur_title=title,
                            next_labels=next_labels,
                            start_ts=start_ts,
                        )

                    self.root.after(0, _ui_tick)

                    # Opportunistic table refresh
                    if i % 5 == 0:
                        self.root.after(0, self._refresh_x_table)

                # Commit results
                self.results_X = out
                self.root.after(0, self._refresh_x_table)
                self.root.after(0, lambda: self.set_step("Normalize", "done"))
                self.root.after(0, lambda: self.set_step("Enrich", "done"))
            except Exception as e:
                logger.log(f"ERROR: {e}")
                logger.log("TRACE:\n" + traceback.format_exc())
                # F-137: same defect as F-112, and worse here — this worker
                # runs while a wait_window-grabbed modal holds the Tk grab,
                # so an off-thread dialog competes with a grabbed Toplevel.
                # `m=str(e)` is required: PEP 3110 deletes `e` at the end of
                # the except block and this callback runs later.
                self.root.after(0, lambda m=str(e): messagebox.showerror(
                    "Resolve error", m))
            finally:
                logger.close()
                self.root.after(0, lambda: modal.mark_finished(cancelled=self.cancel_token.cancelled))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

        # Blocking modal: keeps focus; parent is grabbed
        self.root.wait_window(modal)

    # ------------------ FETCH MODAL WORKFLOW ------------------

    def on_fetch_refs(self):
        if not self.results_X:
            messagebox.showinfo("No data", "Import/Resolve X first.")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Busy", "Another task is running. Click Stop to cancel.")
            return

        logger = self.build_logger()
        fetcher = RefFetcher(logger, cache_dir=os.path.join(self.cache_dir, "refs"))
        self.cancel_token = CancellationToken()
        runctl = _RunControl(self.cancel_token)

        total = len(self.results_X)
        self.set_step("Fetch Refs", "running")
        self.refs_by_X = {}

        modal = FetchModal(
            self.root,
            total=total,
            on_pause=runctl.pause,
            on_resume=runctl.resume,
            on_cancel=self.cancel_token.cancel,
        )

        # Cumulative per-source hits derived from child refs
        hits_oa = hits_cr = hits_s2 = 0
        errors = 0
        start_ts = time.time()

        def work():
            nonlocal hits_oa, hits_cr, hits_s2, errors, start_ts
            try:
                N = len(self.results_X)
                for i, bi in enumerate(self.results_X, 1):
                    if self.cancel_token.cancelled:
                        break
                    runctl.wait_if_paused()

                    # Fetch for one parent X
                    try:
                        refs = fetcher.fetch_for_item(bi, self.cancel_token)
                    except Exception:
                        errors += 1
                        logger.log("TRACE:\n" + traceback.format_exc())
                        refs = []

                    # Reindex child local_ids sequentially per X
                    for idx, r in enumerate(refs, 1):
                        r.local_id = f"{bi.local_id or f'X{i:03d}'}.R{idx:03d}"

                    # Update per-source hit counters from the references we just fetched
                    for r in refs:
                        try:
                            if getattr(r, "hit_openalex", None): hits_oa += 1
                            if getattr(r, "hit_crossref", None): hits_cr += 1
                            if getattr(r, "hit_semanticscholar", None): hits_s2 += 1
                        except Exception:
                            pass

                    self.refs_by_X[bi.local_id or f"X{i:03d}"] = refs

                    # UI update (item-only: per parent X)
                    def _ui_tick():
                        cur_id = bi.local_id or f"X{i:03d}"
                        line1 = f"{bi.first_author or '—'} {bi.year or ''}   {bi.venue or ''}"
                        title = (bi.title or "—")
                        title = (title[:120].rstrip() + "…") if len(title) > 120 else title
                        # Next parents
                        next_labels = []
                        for j in range(i+1, min(i+1+8, N+1)):
                            nb = self.results_X[j-1]
                            t = (nb.title or "—")
                            t = (t[:80].rstrip() + "…") if len(t) > 80 else t
                            next_labels.append(f"X{j:03d} — {nb.first_author or '—'} {nb.year or ''} — {t}")
                        modal.update_progress(
                            done=i,
                            total=N,
                            hits_oa=hits_oa,
                            hits_cr=hits_cr,
                            hits_s2=hits_s2,
                            errors=errors,
                            cur_id=cur_id,
                            cur_line1=line1.strip(),
                            cur_title=title,
                            next_labels=next_labels,
                            start_ts=start_ts,
                        )

                    self.root.after(0, _ui_tick)
                    self.root.after(0, self._refresh_refs_list)

                self.root.after(0, lambda: self.set_step("Fetch Refs", "done"))
            except Exception as e:
                logger.log(f"ERROR: {e}")
                logger.log("TRACE:\n" + traceback.format_exc())
                # F-137, the second site. See on_resolve_metadata above.
                self.root.after(0, lambda m=str(e): messagebox.showerror(
                    "Fetch error", m))
            finally:
                logger.close()
                self.root.after(0, lambda: modal.mark_finished(cancelled=self.cancel_token.cancelled))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

        # Blocking modal
        self.root.wait_window(modal)

    # ------------------ Aggregate / Export ------------------

    def on_build_A(self):
        # Aggregate all refs across X
        all_refs: List[BibItem] = []
        for _, lst in (self.refs_by_X or {}).items():
            all_refs.extend(lst)
        if not all_refs:
            messagebox.showinfo("No references", "Fetch references first.")
            return
        self.set_step("Aggregate", "running")
        A, _parents_map = dedup_items(all_refs)
        self.vector_A = A
        self._refresh_a_table()
        self.set_step("Aggregate", "done")

    def on_export(self):
        if not self.vector_A and not self.results_X:
            messagebox.showinfo("Nothing to export", "Import/build something first.")
            return
        save_path = filedialog.asksaveasfilename(
            title="Export CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All", "*.*")],
        )
        if not save_path:
            return
        logger = self.build_logger()
        exp = Exporter(logger)
        try:
            if self.vector_A:
                exp.to_csv(save_path, self.vector_A)
            else:
                exp.to_csv(save_path, self.results_X)
            self.set_step("Export", "done")
        except Exception as e:
            logger.log("TRACE:\n" + traceback.format_exc())
            messagebox.showerror("Export error", str(e))
        finally:
            logger.close()

    def on_export_meta_sources(self):
        if not self.results_X:
            messagebox.showinfo("Nothing to export", "Run Resolve Metadata first.")
            return
        save_path = filedialog.asksaveasfilename(
            title="Export Meta Sources CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All", "*.*")],
        )
        if not save_path:
            return
        logger = self.build_logger()
        exp = Exporter(logger)
        try:
            exp.to_meta_sources_csv(save_path, self.results_X)
            self.set_step("Export", "done")
        except Exception as e:
            logger.log("TRACE:\n" + traceback.format_exc())
            messagebox.showerror("Export error", str(e))
        finally:
            logger.close()

    def on_stop(self):
        if self.worker and self.worker.is_alive():
            self.cancel_token.cancel()
            self.build_logger().log("Cancellation requested.")
        else:
            messagebox.showinfo("Idle", "No running task.")

    # ---------- UI helpers ----------
    def _refresh_x_table(self):
        self._rebuild_table(self.tree_x, self.results_X)
        # refresh the X list on Refs tab
        self._refresh_refs_list()

    def _refresh_refs_list(self):
        self.list_x.delete(0, tk.END)
        for bi in self.results_X:
            count = len(self.refs_by_X.get(bi.local_id, []))
            label = f"{bi.local_id or '—'} — {bi.first_author or '—'} {bi.year or ''} — {(bi.title or '')[:50]}…  (refs: {count})"
            self.list_x.insert(tk.END, label)
        # If a selection exists, refresh the right table
        self._on_select_x_for_refs(None)

    def _refresh_a_table(self):
        self._rebuild_table(self.tree_a, self.vector_A)

    def _merge_summary(self, bi: BibItem) -> str:
        fs = getattr(bi, "field_sources", {}) or {}
        parts = []
        for fld in ("title", "year", "doi", "venue", "lang", "abstract", "keywords"):
            src = fs.get(fld)
            if src:
                parts.append(f"{fld}:{src[:2].upper()}")
        return "; ".join(parts)

    def _missing_fields(self, bi: BibItem) -> str:
        miss = []
        if not getattr(bi, "lang", ""): miss.append("lang")
        if not getattr(bi, "abstract", ""): miss.append("abstract")
        if not getattr(bi, "keywords", ""): miss.append("keywords")
        return ",".join(miss)

    def _rebuild_table(self, tree: ttk.Treeview, rows: List[BibItem]):
        tree.delete(*tree.get_children())
        cols = list(tree["columns"])

        for bi in rows:
            def value_for(col: str):
                if col == "parents":
                    return ",".join(bi.parents or [])
                if col == "confidence":
                    try:
                        return f"{bi.confidence:.2f}"
                    except Exception:
                        return ""
                if col == "abstract":
                    txt = bi.abstract or ""
                    return (txt[:240].rstrip() + "…") if len(txt) > 240 else txt
                if col == "open_access":
                    return "" if bi.open_access is None else ("True" if bi.open_access else "False")
                if col == "merge_summary":
                    return self._merge_summary(bi)
                if col == "missing_fields":
                    return self._missing_fields(bi)
                if col.startswith("hit_"):
                    val = getattr(bi, col, None)
                    if val is None:
                        return ""
                    return "hit" if val else "miss"
                if col == "resolver_notes":
                    return getattr(bi, "resolver_notes", "") or ""
                return getattr(bi, col, "") or ""

            values = [value_for(c) for c in cols]
            tree.insert("", "end", values=values)

    def _on_select_x_for_refs(self, event):
        sel = self.list_x.curselection()
        if not sel:
            self.tree_refs.delete(*self.tree_refs.get_children())
            return
        idx = sel[0]
        if idx >= len(self.results_X):
            return
        x_item = self.results_X[idx]
        refs = self.refs_by_X.get(x_item.local_id, [])
        self._rebuild_table(self.tree_refs, refs)

    # Editable cell (double-click) for X table basic fields
    def _on_cell_edit(self, event):
        tree = self.tree_x
        region = tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        row_id = tree.identify_row(event.y)
        col_id = tree.identify_column(event.x)
        if not row_id or not col_id:
            return
        col_idx = int(col_id.replace("#", "")) - 1
        cols = tree["columns"]
        field = cols[col_idx]
        if field not in ("title", "first_author", "year", "doi", "venue", "url"):
            return
        x, y, w, h = tree.bbox(row_id, col_id)
        value = tree.set(row_id, field)
        entry = tk.Entry(tree)
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, value)
        entry.focus_set()

        def on_return(e):
            new_val = entry.get()
            tree.set(row_id, field, new_val)
            entry.destroy()
            # also reflect to self.results_X
            index = tree.index(row_id)
            if 0 <= index < len(self.results_X):
                bi = self.results_X[index]
                if field == "year":
                    try:
                        bi.year = int(new_val) if new_val else None
                    except Exception:
                        bi.year = None
                else:
                    setattr(bi, field, new_val)

        entry.bind("<Return>", on_return)
        entry.bind("<Escape>", lambda e: entry.destroy())


# --------------------------------------------------------------------------------------
# Launcher
# --------------------------------------------------------------------------------------

def main():
    root = tk.Tk()
    root.title("References-of-X — AI v1")
    root.geometry("1200x840")
    root.minsize(1080, 720)
    view = ReferencesOfXView(root)
    view.pack(fill="both", expand=True)
    root.mainloop()

if __name__ == "__main__":
    main()
