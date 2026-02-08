# -*- coding: utf-8 -*-
"""
plugin.py — Screen A (Metadata-only) PRISMA Hub tab plugin — Foundation (v3)

Design goals (for a clean restart)
- One job: a robust UI shell around the v2 staging contract: EH → IH → EL → IL → FINAL
- Thread-safe: no Tk calls from worker threads (queue + .after polling only)
- Minimal assumptions about the other modules:
    • criteria.py: parse criteria text → rows (list[dict])
    • metadata.py: parse A file → rows (list[dict]); run one stage with prior_result
    • decisions_report.py: aggregate final rows; export decisions/audit; counts; charts
- “Future-proof” invocation: we introspect function signatures and pass only supported kwargs.

Expected v2 result shape from metadata.screen_metadata(...)
{
  "caches": {
     "EH": {"rows": [...], "survivor_ids": [...]},
     "IH": {"rows": [...], "survivor_ids": [...]},
     "EL": {"rows": [...], "survivor_ids": [...]},
     "IL": {"rows": [...], "survivor_ids": [...]},
     "FINAL": {...}  # optional; plugin can also compute final via decisions_report
  },
  "meta": {...}     # optional
}

Stage rows (cache["rows"]) should be list[dict] containing (recommended keys):
  stage, a_id, stage_outcome, passed_to_next, hard_stop,
  hard_stop_criterion_id, hard_stop_criterion_label, stage_reason_summary

Final rows (from decisions_report.aggregate_final / aggregate_decisions) recommended keys:
  a_id, title, year, venue, lang, doc_type,
  final_outcome, discarded_at_stage,
  outcome_EH/IH/EL/IL, reasons_EH/IH/EL/IL, history

Hub entry point:
  create_plugin(app=None, *args, **kwargs) -> BasePlugin
"""

from __future__ import annotations

TAB_TITLE = "Screen A - Metadata"

import inspect
import json
import os
import queue
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Hub plugin base/meta
from prisma_hub.plugin_api import BasePlugin, PluginMeta  # type: ignore


# ----------------------------
# Cancellation (engine-friendly)
# ----------------------------

class CancelToken:
    """
    Engine-friendly cancellation token.

    - Engine may check token.cancelled (bool).
    - Plugin uses token.cancel() to request cancellation.
    """
    def __init__(self) -> None:
        self._evt = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._evt.is_set()

    def cancel(self) -> None:
        self._evt.set()


# ----------------------------
# UI event types
# ----------------------------

@dataclass
class _UiEvent:
    kind: str
    payload: Dict[str, Any]


# ----------------------------
# Utilities
# ----------------------------

def _now_hms() -> str:
    return time.strftime("%H:%M:%S")

def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    try:
        return str(x)
    except Exception:
        return repr(x)

def _has_var_kwargs(fn: Callable[..., Any]) -> bool:
    try:
        sig = inspect.signature(fn)
    except Exception:
        return True
    for p in sig.parameters.values():
        if p.kind == inspect.Parameter.VAR_KEYWORD:
            return True
    return False

def _filter_kwargs(fn: Callable[..., Any], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Keep only kwargs accepted by fn signature (unless fn has **kwargs).
    """
    if _has_var_kwargs(fn):
        return kwargs
    try:
        sig = inspect.signature(fn)
        allowed = set(sig.parameters.keys())
        return {k: v for k, v in kwargs.items() if k in allowed}
    except Exception:
        return kwargs

def _call_flex(fn: Callable[..., Any], **kwargs: Any) -> Any:
    """
    Call fn with filtered kwargs.
    If that still raises TypeError, progressively drop optional keys (best-effort).
    """
    kw = _filter_kwargs(fn, dict(kwargs))
    try:
        return fn(**kw)
    except TypeError:
        # fallback: drop common optional keys if mismatch
        drop_order = [
            "log", "progress", "cancel_token",
            "llm_trunc_chars", "llm_batch_size",
            "random_seed", "hard_stop",
            "prior_result",
        ]
        for k in drop_order:
            if k in kw:
                kw2 = dict(kw)
                kw2.pop(k, None)
                try:
                    return fn(**kw2)
                except TypeError:
                    kw = kw2
                    continue
        raise


# ----------------------------
# Plugin
# ----------------------------

class ScreenAMetadataPlugin(BasePlugin):
    """
    PRISMA Hub Notebook tab plugin: Screen A (metadata-only) staging UI.
    """

    STAGES: Tuple[str, ...] = ("EH", "IH", "EL", "IL")

    # Default columns (we will also support dynamic columns)
    DEFAULT_STAGE_COLS: Tuple[str, ...] = (
        "stage", "a_id", "stage_outcome", "passed_to_next",
        "hard_stop", "hard_stop_criterion_id", "hard_stop_criterion_label",
        "stage_reason_summary",
    )
    DEFAULT_FINAL_COLS: Tuple[str, ...] = (
        "a_id", "title", "year", "venue", "lang", "doc_type",
        "final_outcome", "discarded_at_stage",
        "outcome_EH", "outcome_IH", "outcome_EL", "outcome_IL",
        "reasons_EH", "reasons_IH", "reasons_EL", "reasons_IL",
        "history",
    )

    def __init__(self, app=None) -> None:
        super().__init__(app, PluginMeta(
            id="screen_A_metadata",
            title=TAB_TITLE,
            version="3.0.0",
        ))

        # --- Data ---
        self.criteria_text: str = ""
        self.criteria_rows: List[Dict[str, Any]] = []
        self.A_rows: List[Dict[str, Any]] = []
        self.A_meta: Dict[str, Any] = {}

        # v2 engine results (progressively merged)
        self.meta_results: Optional[Dict[str, Any]] = None

        # UI-friendly result tables
        self.stage_rows: Dict[str, List[Dict[str, Any]]] = {s: [] for s in self.STAGES}
        self.final_rows: List[Dict[str, Any]] = []

        # gating: which stages are completed in current run lineage
        self._done: Dict[str, bool] = {s: False for s in self.STAGES}

        # --- Run control / threading ---
        self._ui_q: "queue.Queue[_UiEvent]" = queue.Queue()
        self._run_thread: Optional[threading.Thread] = None
        self._cancel_token: Optional[CancelToken] = None
        self._poll_after_id: Optional[str] = None

        # Pending state computed by worker, applied on main thread
        self._pending_meta_results: Optional[Dict[str, Any]] = None
        self._pending_stage_rows: Optional[Dict[str, List[Dict[str, Any]]]] = None
        self._pending_final_rows: Optional[List[Dict[str, Any]]] = None
        self._pending_error: Optional[str] = None

        # --- Tk handles ---
        self._frame: Optional[ttk.Frame] = None
        self._root: Optional[tk.Misc] = None

        # Setup widgets
        self.txt_criteria: Optional[tk.Text] = None
        self.lbl_criteria_summary: Optional[ttk.Label] = None
        self.lbl_a_summary: Optional[ttk.Label] = None

        # Options
        self.var_llm_model: tk.StringVar = tk.StringVar(value="")
        self.var_llm_batch: tk.IntVar = tk.IntVar(value=75)
        self.var_llm_trunc: tk.IntVar = tk.IntVar(value=1500)
        self.var_random_seed: tk.StringVar = tk.StringVar(value="")
        self.var_hard_stop: tk.BooleanVar = tk.BooleanVar(value=True)

        # Results widgets
        self.tv_stage: Dict[str, ttk.Treeview] = {}
        self.tv_final: Optional[ttk.Treeview] = None

        # Logs
        self.txt_log: Optional[tk.Text] = None

        # Modal progress
        self._modal: Optional[tk.Toplevel] = None
        self._modal_stage: Optional[ttk.Label] = None
        self._modal_msg: Optional[ttk.Label] = None
        self._modal_counts: Optional[ttk.Label] = None
        self._modal_pb: Optional[ttk.Progressbar] = None
        self._modal_cancel_btn: Optional[ttk.Button] = None
        self._progress_total: int = 0
        self._progress_done: int = 0
        self._progress_stage: str = ""
        self._progress_msg: str = ""

        # Cached A index (for title lookup in UI if needed)
        self._A_index: Dict[str, Dict[str, Any]] = {}

    # ----------------------------
    # Hub entry points
    # ----------------------------

    def build_tab(self, notebook: ttk.Notebook) -> ttk.Frame:
        root = ttk.Frame(notebook)
        self._frame = root
        try:
            self._root = root.winfo_toplevel()
        except Exception:
            self._root = notebook.winfo_toplevel()

        self._build_ui(root)
        self._log(f"[{_now_hms()}] Loaded {TAB_TITLE} plugin (v{self.meta.version}).\n")
        return root

    def on_select(self):
        # Optional hook called by hub when tab is selected
        pass

    def on_close(self):
        # Optional hook called by hub when tab is closed
        try:
            self._request_cancel()
        except Exception:
            pass
        self._stop_polling()

    # ----------------------------
    # Lazy imports (so plugin loads even if modules are mid-rebuild)
    # ----------------------------

    def _modules(self):
        """
        Returns (criteria_mod, metadata_mod, report_mod).
        Raises a friendly error if something is missing.
        """
        try:
            from . import criteria as criteria_mod  # type: ignore
        except Exception as e:
            raise RuntimeError(f"Cannot import criteria.py: {e}") from e
        try:
            from . import metadata as metadata_mod  # type: ignore
        except Exception as e:
            raise RuntimeError(f"Cannot import metadata.py: {e}") from e
        try:
            from . import decisions_report as report_mod  # type: ignore
        except Exception as e:
            raise RuntimeError(f"Cannot import decisions_report.py: {e}") from e
        return criteria_mod, metadata_mod, report_mod

    # ----------------------------
    # UI
    # ----------------------------

    def _build_ui(self, container: tk.Widget) -> None:
        nb = ttk.Notebook(container)
        nb.pack(fill=tk.BOTH, expand=True)

        tab_setup = ttk.Frame(nb, padding=10)
        tab_results = ttk.Frame(nb, padding=10)
        tab_export = ttk.Frame(nb, padding=10)

        nb.add(tab_setup, text="Setup")
        nb.add(tab_results, text="Results")
        nb.add(tab_export, text="Export & Logs")

        self._build_setup_tab(tab_setup)
        self._build_results_tab(tab_results)
        self._build_export_tab(tab_export)

    def _build_setup_tab(self, tab: ttk.Frame) -> None:
        # Layout: left (criteria), right (A + run)
        pan = ttk.Panedwindow(tab, orient=tk.HORIZONTAL)
        pan.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(pan, padding=(0, 0, 10, 0))
        right = ttk.Frame(pan)
        pan.add(left, weight=3)
        pan.add(right, weight=2)

        # --- Criteria editor ---
        lf_crit = ttk.LabelFrame(left, text="Criteria", padding=10)
        lf_crit.pack(fill=tk.BOTH, expand=True)

        btn_row = ttk.Frame(lf_crit)
        btn_row.pack(fill=tk.X, pady=(0, 8))

        ttk.Button(btn_row, text="Load…", command=self.on_load_criteria_file).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Save…", command=self.on_save_criteria_file).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btn_row, text="Parse / Validate", command=self.on_parse_criteria).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(btn_row, text="Clear", command=self.on_clear_criteria).pack(side=tk.LEFT, padx=(6, 0))

        self.lbl_criteria_summary = ttk.Label(lf_crit, text="No criteria loaded.")
        self.lbl_criteria_summary.pack(anchor="w", pady=(0, 8))

        txt = tk.Text(lf_crit, height=18, wrap="word")
        self.txt_criteria = txt
        scr = ttk.Scrollbar(lf_crit, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=scr.set)

        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scr.pack(side=tk.RIGHT, fill=tk.Y)

        # --- A loader + run ---
        lf_a = ttk.LabelFrame(right, text="Dataset A", padding=10)
        lf_a.pack(fill=tk.X)

        ttk.Button(lf_a, text="Load A (CSV/XLSX)…", command=self.on_load_A).pack(anchor="w")
        self.lbl_a_summary = ttk.Label(lf_a, text="No A loaded.")
        self.lbl_a_summary.pack(anchor="w", pady=(6, 0))

        lf_opts = ttk.LabelFrame(right, text="Run options", padding=10)
        lf_opts.pack(fill=tk.X, pady=(10, 0))

        grid = ttk.Frame(lf_opts)
        grid.pack(fill=tk.X)

        ttk.Label(grid, text="LLM model (optional)").grid(row=0, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self.var_llm_model, width=28).grid(row=0, column=1, sticky="we", padx=(8, 0))

        ttk.Label(grid, text="LLM batch").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(grid, from_=1, to=500, textvariable=self.var_llm_batch, width=8).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(6, 0))

        ttk.Label(grid, text="LLM trunc chars").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(grid, from_=200, to=20000, increment=100, textvariable=self.var_llm_trunc, width=8).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(6, 0))

        ttk.Label(grid, text="Random seed (optional)").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(grid, textvariable=self.var_random_seed, width=16).grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(6, 0))

        ttk.Checkbutton(grid, text="Hard stop", variable=self.var_hard_stop).grid(row=4, column=0, sticky="w", pady=(6, 0))

        grid.columnconfigure(1, weight=1)

        lf_run = ttk.LabelFrame(right, text="Staged run", padding=10)
        lf_run.pack(fill=tk.X, pady=(10, 0))

        row1 = ttk.Frame(lf_run)
        row1.pack(fill=tk.X)

        ttk.Button(row1, text="Run EH", command=lambda: self.on_run(stage="EH")).pack(side=tk.LEFT)
        ttk.Button(row1, text="Run IH", command=lambda: self.on_run(stage="IH")).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(row1, text="Run EL", command=lambda: self.on_run(stage="EL")).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(row1, text="Run IL", command=lambda: self.on_run(stage="IL")).pack(side=tk.LEFT, padx=(6, 0))

        row2 = ttk.Frame(lf_run)
        row2.pack(fill=tk.X, pady=(8, 0))

        ttk.Button(row2, text="Run remaining", command=self.on_run_remaining).pack(side=tk.LEFT)
        ttk.Button(row2, text="Reset results", command=self.on_reset_results).pack(side=tk.LEFT, padx=(6, 0))

        self._update_run_button_states(lf_run)

    def _build_results_tab(self, tab: ttk.Frame) -> None:
        nb = ttk.Notebook(tab)
        nb.pack(fill=tk.BOTH, expand=True)

        for s in self.STAGES:
            frame = ttk.Frame(nb, padding=8)
            nb.add(frame, text=s)
            tv = self._make_tree(frame, columns=list(self.DEFAULT_STAGE_COLS))
            self.tv_stage[s] = tv

        frame_f = ttk.Frame(nb, padding=8)
        nb.add(frame_f, text="FINAL")
        self.tv_final = self._make_tree(frame_f, columns=list(self.DEFAULT_FINAL_COLS))

    def _build_export_tab(self, tab: ttk.Frame) -> None:
        top = ttk.Frame(tab)
        top.pack(fill=tk.X)

        ttk.Button(top, text="Export decisions CSV…", command=self.on_export_decisions_csv).pack(side=tk.LEFT)
        ttk.Button(top, text="Export decisions XLSX…", command=self.on_export_decisions_xlsx).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(top, text="Export audit CSV…", command=self.on_export_audit_csv).pack(side=tk.LEFT, padx=(18, 0))
        ttk.Button(top, text="Export audit XLSX…", command=self.on_export_audit_xlsx).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(top, text="Save charts…", command=self.on_save_charts).pack(side=tk.LEFT, padx=(18, 0))
        ttk.Button(top, text="Save run JSON…", command=self.on_save_run_json).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Separator(tab).pack(fill=tk.X, pady=10)

        self.txt_log = tk.Text(tab, height=20, wrap="word")
        scr = ttk.Scrollbar(tab, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=scr.set)

        self.txt_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scr.pack(side=tk.RIGHT, fill=tk.Y)

    def _make_tree(self, parent: tk.Widget, columns: List[str]) -> ttk.Treeview:
        tv = ttk.Treeview(parent, columns=columns, show="headings", height=14)
        y = ttk.Scrollbar(parent, orient="vertical", command=tv.yview)
        x = ttk.Scrollbar(parent, orient="horizontal", command=tv.xview)
        tv.configure(yscrollcommand=y.set, xscrollcommand=x.set)

        for c in columns:
            tv.heading(c, text=c)
            tv.column(c, width=140, stretch=True, anchor="w")

        tv.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")

        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        return tv

    # ----------------------------
    # Logging
    # ----------------------------

    def _log(self, msg: str) -> None:
        """
        Thread-safe log entry: worker threads should enqueue via _emit_log,
        main thread can call _log directly.
        """
        if self.txt_log is None:
            return
        self.txt_log.insert("end", msg)
        self.txt_log.see("end")

    def _emit_log(self, msg: str) -> None:
        self._ui_q.put(_UiEvent("log", {"msg": msg}))

    # ----------------------------
    # Criteria actions
    # ----------------------------

    def on_load_criteria_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Load criteria",
            filetypes=[("Text", "*.txt *.md *.csv"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                txt = f.read()
            self.criteria_text = txt
            if self.txt_criteria is not None:
                self.txt_criteria.delete("1.0", "end")
                self.txt_criteria.insert("1.0", txt)
            self._log(f"[{_now_hms()}] Loaded criteria file: {os.path.basename(path)}\n")
        except Exception as e:
            messagebox.showerror("Load criteria", str(e))

    def on_save_criteria_file(self) -> None:
        if self.txt_criteria is not None:
            self.criteria_text = self.txt_criteria.get("1.0", "end").strip()
        if not self.criteria_text.strip():
            messagebox.showwarning("Save criteria", "No criteria text to save.")
            return
        path = filedialog.asksaveasfilename(
            title="Save criteria",
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.criteria_text)
            self._log(f"[{_now_hms()}] Saved criteria file: {os.path.basename(path)}\n")
        except Exception as e:
            messagebox.showerror("Save criteria", str(e))

    def on_clear_criteria(self) -> None:
        self.criteria_text = ""
        self.criteria_rows = []
        if self.txt_criteria is not None:
            self.txt_criteria.delete("1.0", "end")
        self._update_criteria_summary()
        self._log(f"[{_now_hms()}] Cleared criteria.\n")
        self.on_reset_results()

    def on_parse_criteria(self) -> None:
        if self.txt_criteria is not None:
            self.criteria_text = self.txt_criteria.get("1.0", "end").strip()

        if not self.criteria_text.strip():
            messagebox.showwarning("Criteria", "Paste or load criteria text first.")
            return

        try:
            criteria_mod, _, _ = self._modules()

            # Canonical v3 API: parse_criteria_text(text) -> rows
            if hasattr(criteria_mod, "parse_criteria_text"):
                rows = _call_flex(criteria_mod.parse_criteria_text, text=self.criteria_text)  # type: ignore
            # Compatibility with older naming patterns
            elif hasattr(criteria_mod, "parse_criteria_rows"):
                rows = _call_flex(criteria_mod.parse_criteria_rows, text=self.criteria_text)  # type: ignore
            elif hasattr(criteria_mod, "harmonize_from_text"):
                rows = _call_flex(criteria_mod.harmonize_from_text, text=self.criteria_text)  # type: ignore
            else:
                raise RuntimeError("criteria.py must provide parse_criteria_text(text)->rows (or a compatible function).")

            if not isinstance(rows, list):
                raise RuntimeError("criteria parser returned unexpected type (expected list of dict).")

            # shallow validation: list of dict
            for i, r in enumerate(rows):
                if not isinstance(r, dict):
                    raise RuntimeError(f"criteria row #{i} is not a dict.")

            self.criteria_rows = rows
            self._update_criteria_summary()

            self._log(f"[{_now_hms()}] Parsed criteria: {len(rows)} row(s).\n")
        except Exception as e:
            self.criteria_rows = []
            self._update_criteria_summary()
            self._log(f"[{_now_hms()}] Criteria parse error: {e}\n")
            messagebox.showerror("Criteria", str(e))

        self._update_run_button_states()

    def _update_criteria_summary(self) -> None:
        if self.lbl_criteria_summary is None:
            return
        if not self.criteria_rows:
            self.lbl_criteria_summary.configure(text="No parsed criteria rows.")
            return

        enabled = sum(1 for r in self.criteria_rows if bool(r.get("enabled", True)))
        # stage distribution (best-effort)
        dist: Dict[str, int] = {s: 0 for s in self.STAGES}
        for r in self.criteria_rows:
            if not bool(r.get("enabled", True)):
                continue
            stage = _safe_str(r.get("stage", "")).upper().strip()
            if stage in dist:
                dist[stage] += 1

        dist_str = ", ".join(f"{k}:{v}" for k, v in dist.items() if v)
        if dist_str:
            self.lbl_criteria_summary.configure(text=f"Parsed: {len(self.criteria_rows)} | enabled: {enabled} | stages: {dist_str}")
        else:
            self.lbl_criteria_summary.configure(text=f"Parsed: {len(self.criteria_rows)} | enabled: {enabled}")

    # ----------------------------
    # A actions
    # ----------------------------

    def on_load_A(self) -> None:
        path = filedialog.askopenfilename(
            title="Load A (CSV/XLSX)",
            filetypes=[("CSV", "*.csv"), ("Excel", "*.xlsx *.xls"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            _, metadata_mod, _ = self._modules()

            # Canonical v3 API: parse_A_file(path) -> (rows, meta)
            rows: Any = None
            meta: Dict[str, Any] = {}

            if hasattr(metadata_mod, "parse_A_file"):
                out = _call_flex(metadata_mod.parse_A_file, path=path)  # type: ignore
                if isinstance(out, tuple) and len(out) == 2:
                    rows, meta = out
                else:
                    rows = out
            # Compatibility
            elif hasattr(metadata_mod, "parse_A_csv_xlsx"):
                rows = _call_flex(metadata_mod.parse_A_csv_xlsx, path=path)  # type: ignore
            else:
                raise RuntimeError("metadata.py must provide parse_A_file(path) or parse_A_csv_xlsx(path).")

            if not isinstance(rows, list):
                raise RuntimeError("A parser returned unexpected type (expected list of dict).")
            for i, r in enumerate(rows[:10]):
                if not isinstance(r, dict):
                    raise RuntimeError(f"A row #{i} is not a dict.")

            self.A_rows = rows
            self.A_meta = meta or {}

            # Build index for quick lookups
            self._A_index = {}
            for r in self.A_rows:
                a_id = _safe_str(r.get("a_id") or r.get("id") or r.get("ID") or "").strip()
                if a_id:
                    self._A_index[a_id] = r

            self._update_a_summary()
            self._log(f"[{_now_hms()}] Loaded A: {len(rows)} row(s) from {os.path.basename(path)}\n")

            # New A invalidates results
            self.on_reset_results()

        except Exception as e:
            messagebox.showerror("Load A", str(e))

        self._update_run_button_states()

    def _update_a_summary(self) -> None:
        if self.lbl_a_summary is None:
            return
        if not self.A_rows:
            self.lbl_a_summary.configure(text="No A loaded.")
            return
        cols = sorted({k for r in self.A_rows[:50] for k in r.keys()})
        col_preview = ", ".join(cols[:10]) + ("…" if len(cols) > 10 else "")
        self.lbl_a_summary.configure(text=f"Loaded: {len(self.A_rows)} rows | columns: {col_preview}")

    # ----------------------------
    # Run gating + controls
    # ----------------------------

    def _update_run_button_states(self, root: Optional[tk.Widget] = None) -> None:
        # We keep it simple: run buttons are enabled based on (criteria parsed) and (A loaded),
        # and stage gating EH→IH→EL→IL.
        # Button state changes happen by re-walking children if a root is provided.
        if root is None and self._frame is not None:
            root = self._frame

        ok_inputs = bool(self.criteria_rows) and bool(self.A_rows)
        need = {
            "EH": ok_inputs,
            "IH": ok_inputs and self._done["EH"],
            "EL": ok_inputs and self._done["EH"] and self._done["IH"],
            "IL": ok_inputs and self._done["EH"] and self._done["IH"] and self._done["EL"],
        }
        # We won’t rely on widget references for buttons; instead, we keep gating in on_run() too.
        # This method is still useful for future enhancements.

    def _require_ready(self) -> None:
        if not self.criteria_rows:
            raise RuntimeError("Load and parse criteria first.")
        if not self.A_rows:
            raise RuntimeError("Load A first.")

    def _require_stage_gate(self, stage: str) -> None:
        stage = stage.upper().strip()
        if stage == "EH":
            return
        if stage == "IH" and not self._done["EH"]:
            raise RuntimeError("Run EH first.")
        if stage == "EL" and not (self._done["EH"] and self._done["IH"]):
            raise RuntimeError("Run EH and IH first.")
        if stage == "IL" and not (self._done["EH"] and self._done["IH"] and self._done["EL"]):
            raise RuntimeError("Run EH, IH and EL first.")

    # ----------------------------
    # Run actions
    # ----------------------------

    def on_reset_results(self) -> None:
        self.meta_results = None
        self.stage_rows = {s: [] for s in self.STAGES}
        self.final_rows = []
        self._done = {s: False for s in self.STAGES}

        for s, tv in self.tv_stage.items():
            self._populate_tree(tv, [], self.DEFAULT_STAGE_COLS)
        if self.tv_final is not None:
            self._populate_tree(self.tv_final, [], self.DEFAULT_FINAL_COLS)

        self._log(f"[{_now_hms()}] Reset results.\n")

    def on_run(self, stage: str) -> None:
        stage = (stage or "").upper().strip()
        if stage not in self.STAGES:
            messagebox.showerror("Run", f"Unknown stage: {stage}")
            return

        try:
            self._require_ready()
            self._require_stage_gate(stage)
        except Exception as e:
            messagebox.showwarning("Run", str(e))
            return

        # If rerunning EH, invalidate downstream lineage
        if stage == "EH":
            self.on_reset_results()

        self._start_worker(stages=[stage])

    def on_run_remaining(self) -> None:
        try:
            self._require_ready()
        except Exception as e:
            messagebox.showwarning("Run", str(e))
            return

        # Determine first missing stage
        plan: List[str] = []
        for s in self.STAGES:
            if not self._done[s]:
                plan.append(s)
        if not plan:
            messagebox.showinfo("Run", "All stages are already completed.")
            return

        # Enforce gate: if first missing is not EH, prior must be completed
        try:
            self._require_stage_gate(plan[0])
        except Exception as e:
            messagebox.showwarning("Run", str(e))
            return

        self._start_worker(stages=plan)

    def _start_worker(self, stages: List[str]) -> None:
        if self._run_thread and self._run_thread.is_alive():
            messagebox.showinfo("Run", "A run is already in progress.")
            return

        self._pending_meta_results = None
        self._pending_stage_rows = None
        self._pending_final_rows = None
        self._pending_error = None

        self._cancel_token = CancelToken()

        self._open_progress_modal()
        self._emit_log(f"[{_now_hms()}] Run start: {' → '.join(stages)}\n")

        args = {
            "stages": list(stages),
            "criteria_rows": list(self.criteria_rows),
            "A_rows": list(self.A_rows),
            "initial_meta_results": self.meta_results,
            "llm_model": (self.var_llm_model.get().strip() or None),
            "llm_batch_size": int(self.var_llm_batch.get()),
            "llm_trunc_chars": int(self.var_llm_trunc.get()),
            "random_seed": (self.var_random_seed.get().strip() or None),
            "hard_stop": bool(self.var_hard_stop.get()),
        }

        self._run_thread = threading.Thread(target=self._worker_main, kwargs=args, daemon=True)
        self._run_thread.start()
        self._start_polling()

    def _worker_main(
        self,
        stages: List[str],
        criteria_rows: List[Dict[str, Any]],
        A_rows: List[Dict[str, Any]],
        initial_meta_results: Optional[Dict[str, Any]],
        llm_model: Optional[str],
        llm_batch_size: int,
        llm_trunc_chars: int,
        random_seed: Optional[str],
        hard_stop: bool,
    ) -> None:
        """
        Worker thread: runs one or more stages sequentially, merges results,
        computes final rows, then sends a single "completed" event.
        """
        try:
            _, metadata_mod, report_mod = self._modules()

            if not hasattr(metadata_mod, "screen_metadata"):
                raise RuntimeError("metadata.py must provide screen_metadata(...).")

            screen_fn = metadata_mod.screen_metadata  # type: ignore

            meta_results = initial_meta_results if isinstance(initial_meta_results, dict) else None

            for s in stages:
                if self._cancel_token and self._cancel_token.cancelled:
                    self._emit_log(f"[{_now_hms()}] Cancel requested. Stopping.\n")
                    break

                self._ui_q.put(_UiEvent("progress", {"stage": s, "msg": "starting", "done": 0, "total": 0}))

                # Build kwargs (filtered by signature)
                kw = dict(
                    A=A_rows,
                    criteria=criteria_rows,
                    subrun=s,
                    prior_result=meta_results,
                    llm_model=llm_model,
                    llm_batch_size=llm_batch_size,
                    llm_trunc_chars=llm_trunc_chars,
                    random_seed=random_seed,
                    hard_stop=hard_stop,
                    cancel_token=self._cancel_token,
                    progress=self._emit_progress,
                    log=self._emit_log,
                )

                res = _call_flex(screen_fn, **kw)

                if not isinstance(res, dict):
                    raise RuntimeError("Engine returned unexpected type (expected dict).")

                meta_results = self._merge_meta_results(meta_results, res, subrun=s)

                # Emit stage stats for modal/log
                cache = ((meta_results.get("caches") or {}).get(s) or {}) if isinstance(meta_results, dict) else {}
                surv = cache.get("survivor_ids") or []
                rows = cache.get("rows") or []
                self._emit_log(f"[{_now_hms()}] Stage {s} done | rows={len(rows)} | survivors={len(surv)}\n")

            # Build UI rows from caches
            stage_rows = {k: [] for k in self.STAGES}
            if isinstance(meta_results, dict):
                caches = meta_results.get("caches") or {}
                for s in self.STAGES:
                    c = caches.get(s) or {}
                    r = c.get("rows") or []
                    if isinstance(r, list):
                        stage_rows[s] = r

            # Compute final rows (best-effort)
            final_rows: List[Dict[str, Any]] = []
            if isinstance(meta_results, dict):
                if hasattr(report_mod, "aggregate_final"):
                    out = _call_flex(report_mod.aggregate_final, meta_results=meta_results, A_rows=A_rows)  # type: ignore
                    if isinstance(out, list):
                        final_rows = out
                elif hasattr(report_mod, "aggregate_decisions"):
                    out = _call_flex(report_mod.aggregate_decisions, meta_results, A_rows)  # type: ignore
                    if isinstance(out, list):
                        final_rows = out

            self._pending_meta_results = meta_results
            self._pending_stage_rows = stage_rows
            self._pending_final_rows = final_rows

        except Exception as e:
            tb = traceback.format_exc()
            self._pending_error = f"{e}\n\n{tb}"

        finally:
            self._ui_q.put(_UiEvent("completed", {}))

    def _merge_meta_results(
        self,
        prev: Optional[Dict[str, Any]],
        new: Dict[str, Any],
        subrun: str
    ) -> Dict[str, Any]:
        """
        Merge v2 caches across staged calls.

        Rules:
        - Keep existing stage caches unless overridden by new.
        - When subrun is an earlier stage, invalidate downstream caches.
        """
        subrun = (subrun or "").upper().strip()
        out: Dict[str, Any] = {}
        prev = prev if isinstance(prev, dict) else None

        # copy top-level
        if prev:
            out.update(prev)
        out.update({k: v for k, v in new.items() if k != "caches"})

        prev_caches = (prev.get("caches") or {}) if prev else {}
        new_caches = new.get("caches") or {}

        merged: Dict[str, Any] = {}
        # keep everything we already have
        if isinstance(prev_caches, dict):
            merged.update(prev_caches)
        # overlay new
        if isinstance(new_caches, dict):
            merged.update(new_caches)

        # Invalidate downstream lineage when rerunning earlier stage
        if subrun == "EH":
            for k in ("IH", "EL", "IL", "FINAL"):
                merged.pop(k, None)
        elif subrun == "IH":
            for k in ("EL", "IL", "FINAL"):
                merged.pop(k, None)
        elif subrun == "EL":
            for k in ("IL", "FINAL"):
                merged.pop(k, None)

        out["caches"] = merged
        return out

    # ----------------------------
    # Progress events (worker -> UI)
    # ----------------------------

    def _emit_progress(self, evt: Dict[str, Any]) -> None:
        # Worker thread safe: queue the event
        self._ui_q.put(_UiEvent("progress", dict(evt or {})))

    # ----------------------------
    # Polling + apply results
    # ----------------------------

    def _start_polling(self) -> None:
        if self._poll_after_id is not None:
            return
        if self._root is None:
            return
        self._poll_after_id = self._root.after(80, self._poll)

    def _stop_polling(self) -> None:
        if self._root is None:
            self._poll_after_id = None
            return
        if self._poll_after_id is not None:
            try:
                self._root.after_cancel(self._poll_after_id)
            except Exception:
                pass
            self._poll_after_id = None

    def _poll(self) -> None:
        # Main thread: handle queued events
        try:
            while True:
                ev = self._ui_q.get_nowait()
                if ev.kind == "log":
                    self._log(ev.payload.get("msg", ""))
                elif ev.kind == "progress":
                    self._handle_progress(ev.payload)
                elif ev.kind == "completed":
                    self._apply_worker_completion()
                else:
                    # unknown event
                    pass
        except queue.Empty:
            pass

        # continue polling while run is alive or modal exists
        alive = bool(self._run_thread and self._run_thread.is_alive())
        modal = bool(self._modal and self._modal.winfo_exists())
        if alive or modal:
            if self._root is not None:
                self._poll_after_id = self._root.after(80, self._poll)
        else:
            self._stop_polling()

    def _handle_progress(self, evt: Dict[str, Any]) -> None:
        # Update modal progress best-effort
        stage = _safe_str(evt.get("stage") or self._progress_stage).upper().strip()
        msg = _safe_str(evt.get("msg") or evt.get("message") or "")
        done = evt.get("done")
        total = evt.get("total")

        if isinstance(done, int):
            self._progress_done = done
        if isinstance(total, int):
            self._progress_total = total
        if stage:
            self._progress_stage = stage
        if msg:
            self._progress_msg = msg

        if self._modal and self._modal.winfo_exists():
            if self._modal_stage is not None:
                self._modal_stage.configure(text=f"Stage: {self._progress_stage or '…'}")
            if self._modal_msg is not None:
                self._modal_msg.configure(text=f"{self._progress_msg}" if self._progress_msg else "")
            if self._modal_counts is not None:
                if self._progress_total > 0:
                    self._modal_counts.configure(text=f"{self._progress_done}/{self._progress_total}")
                else:
                    self._modal_counts.configure(text="working…")

            if self._modal_pb is not None:
                if self._progress_total > 0:
                    self._modal_pb.configure(mode="determinate", maximum=max(1, self._progress_total), value=min(self._progress_done, self._progress_total))
                else:
                    self._modal_pb.configure(mode="indeterminate")
                    try:
                        self._modal_pb.start(25)
                    except Exception:
                        pass

    def _apply_worker_completion(self) -> None:
        # Called on main thread after worker signals completion
        self._close_progress_modal()

        if self._pending_error:
            self._log(f"[{_now_hms()}] Run error:\n{self._pending_error}\n")
            messagebox.showerror("Run", "Run failed. See log for details.")
            self._pending_error = None
            return

        # Apply pending state
        if self._pending_meta_results is not None:
            self.meta_results = self._pending_meta_results

        if self._pending_stage_rows is not None:
            self.stage_rows = self._pending_stage_rows

        if self._pending_final_rows is not None:
            self.final_rows = self._pending_final_rows

        # Update done gates based on caches present
        caches = (self.meta_results.get("caches") or {}) if isinstance(self.meta_results, dict) else {}
        for s in self.STAGES:
            self._done[s] = bool(caches.get(s))

        # Render tables
        for s in self.STAGES:
            tv = self.tv_stage.get(s)
            if tv is not None:
                self._populate_tree(tv, self.stage_rows.get(s, []), self.DEFAULT_STAGE_COLS)

        if self.tv_final is not None:
            self._populate_tree(self.tv_final, self.final_rows, self.DEFAULT_FINAL_COLS)

        # Counts to log (best-effort)
        try:
            _, _, report_mod = self._modules()
            counts = None
            if hasattr(report_mod, "prisma_counts"):
                counts = _call_flex(report_mod.prisma_counts, final_rows=self.final_rows)  # type: ignore
            if counts:
                self._log(f"[{_now_hms()}] PRISMA counts: {counts}\n")
        except Exception:
            pass

        self._log(f"[{_now_hms()}] Run completed.\n")

        # Clear pending
        self._pending_meta_results = None
        self._pending_stage_rows = None
        self._pending_final_rows = None

    def _populate_tree(self, tv: ttk.Treeview, rows: List[Dict[str, Any]], default_cols: Tuple[str, ...]) -> None:
        # Clear
        for iid in tv.get_children():
            tv.delete(iid)

        # If rows have keys not covered by default, we keep default columns only (stable UI).
        cols = list(default_cols)

        for i, r in enumerate(rows or []):
            vals = [_safe_str(r.get(c, "")) for c in cols]
            tv.insert("", "end", iid=str(i), values=vals)

    # ----------------------------
    # Modal progress
    # ----------------------------

    def _open_progress_modal(self) -> None:
        if self._root is None:
            return
        if self._modal and self._modal.winfo_exists():
            return

        win = tk.Toplevel(self._root)
        self._modal = win
        win.title("Screening…")
        win.transient(self._root)
        win.grab_set()
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        self._modal_stage = ttk.Label(frm, text="Stage: …", font=("TkDefaultFont", 11, "bold"))
        self._modal_stage.pack(anchor="w")

        self._modal_msg = ttk.Label(frm, text="", wraplength=520)
        self._modal_msg.pack(anchor="w", pady=(6, 0))

        self._modal_counts = ttk.Label(frm, text="working…")
        self._modal_counts.pack(anchor="w", pady=(6, 0))

        self._modal_pb = ttk.Progressbar(frm, mode="indeterminate", maximum=100)
        self._modal_pb.pack(fill=tk.X, pady=(10, 0))
        try:
            self._modal_pb.start(25)
        except Exception:
            pass

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, pady=(12, 0))

        self._modal_cancel_btn = ttk.Button(btns, text="Cancel", command=self._request_cancel)
        self._modal_cancel_btn.pack(side=tk.RIGHT)

        def _on_close():
            # treat close as cancel request
            self._request_cancel()

        win.protocol("WM_DELETE_WINDOW", _on_close)

    def _close_progress_modal(self) -> None:
        if self._modal and self._modal.winfo_exists():
            try:
                self._modal.grab_release()
            except Exception:
                pass
            try:
                self._modal.destroy()
            except Exception:
                pass
        self._modal = None
        self._modal_stage = None
        self._modal_msg = None
        self._modal_counts = None
        self._modal_pb = None
        self._modal_cancel_btn = None
        self._progress_total = 0
        self._progress_done = 0
        self._progress_stage = ""
        self._progress_msg = ""

    def _request_cancel(self) -> None:
        if self._cancel_token and not self._cancel_token.cancelled:
            self._cancel_token.cancel()
            self._emit_log(f"[{_now_hms()}] Cancel requested.\n")
            if self._modal_msg is not None:
                self._modal_msg.configure(text="Cancel requested… stopping when safe.")
            if self._modal_cancel_btn is not None:
                try:
                    self._modal_cancel_btn.configure(state="disabled")
                except Exception:
                    pass

    # ----------------------------
    # Export actions
    # ----------------------------

    def _require_results(self) -> None:
        if not self.meta_results:
            raise RuntimeError("No results available. Run screening first.")

    def on_export_decisions_csv(self) -> None:
        try:
            self._require_results()
            _, _, report_mod = self._modules()
            if not hasattr(report_mod, "export_decisions_csv"):
                raise RuntimeError("decisions_report.py must provide export_decisions_csv(path, meta_results).")

            path = filedialog.asksaveasfilename(
                title="Save decisions (CSV)",
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv")]
            )
            if not path:
                return
            _call_flex(report_mod.export_decisions_csv, path=path, meta_results=self.meta_results)  # type: ignore
            self._log(f"[{_now_hms()}] Exported decisions CSV: {os.path.basename(path)}\n")
        except Exception as e:
            messagebox.showerror("Export", str(e))

    def on_export_decisions_xlsx(self) -> None:
        try:
            self._require_results()
            _, _, report_mod = self._modules()
            if not hasattr(report_mod, "export_decisions_xlsx"):
                raise RuntimeError("decisions_report.py must provide export_decisions_xlsx(path, meta_results).")

            path = filedialog.asksaveasfilename(
                title="Save decisions (XLSX)",
                defaultextension=".xlsx",
                filetypes=[("Excel", "*.xlsx")]
            )
            if not path:
                return
            _call_flex(report_mod.export_decisions_xlsx, path=path, meta_results=self.meta_results)  # type: ignore
            self._log(f"[{_now_hms()}] Exported decisions XLSX: {os.path.basename(path)}\n")
        except Exception as e:
            messagebox.showerror("Export", str(e))

    def on_export_audit_csv(self) -> None:
        try:
            self._require_results()
            _, _, report_mod = self._modules()
            if not hasattr(report_mod, "export_metadata_audit_csv"):
                raise RuntimeError("decisions_report.py must provide export_metadata_audit_csv(path, meta_results, A_rows).")

            path = filedialog.asksaveasfilename(
                title="Save audit (CSV)",
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv")]
            )
            if not path:
                return
            _call_flex(report_mod.export_metadata_audit_csv, path=path, meta_results=self.meta_results, A_rows=self.A_rows)  # type: ignore
            self._log(f"[{_now_hms()}] Exported audit CSV: {os.path.basename(path)}\n")
        except Exception as e:
            messagebox.showerror("Export", str(e))

    def on_export_audit_xlsx(self) -> None:
        try:
            self._require_results()
            _, _, report_mod = self._modules()
            if not hasattr(report_mod, "export_metadata_audit_xlsx"):
                raise RuntimeError("decisions_report.py must provide export_metadata_audit_xlsx(path, meta_results, A_rows).")

            path = filedialog.asksaveasfilename(
                title="Save audit (XLSX)",
                defaultextension=".xlsx",
                filetypes=[("Excel", "*.xlsx")]
            )
            if not path:
                return
            _call_flex(report_mod.export_metadata_audit_xlsx, path=path, meta_results=self.meta_results, A_rows=self.A_rows)  # type: ignore
            self._log(f"[{_now_hms()}] Exported audit XLSX: {os.path.basename(path)}\n")
        except Exception as e:
            messagebox.showerror("Export", str(e))

    def on_save_charts(self) -> None:
        try:
            self._require_results()
            _, _, report_mod = self._modules()
            if not hasattr(report_mod, "save_metadata_charts"):
                raise RuntimeError("decisions_report.py must provide save_metadata_charts(outdir, meta_results).")

            outdir = filedialog.askdirectory(title="Select folder for charts")
            if not outdir:
                return
            out = _call_flex(report_mod.save_metadata_charts, outdir=outdir, meta_results=self.meta_results)  # type: ignore
            self._log(f"[{_now_hms()}] Saved charts: {_safe_str(out)}\n")
        except Exception as e:
            messagebox.showerror("Charts", str(e))

    def on_save_run_json(self) -> None:
        try:
            self._require_results()
            path = filedialog.asksaveasfilename(
                title="Save run (JSON)",
                defaultextension=".json",
                filetypes=[("JSON", "*.json")]
            )
            if not path:
                return
            blob = {
                "criteria_rows": self.criteria_rows,
                "A_meta": self.A_meta,
                "meta_results": self.meta_results,
                "final_rows": self.final_rows,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(blob, f, ensure_ascii=False, indent=2)
            self._log(f"[{_now_hms()}] Saved run JSON: {os.path.basename(path)}\n")
        except Exception as e:
            messagebox.showerror("Save JSON", str(e))


# ----------------------------
# Factory (Hub import point)
# ----------------------------

def create_plugin(app=None, *args, **kwargs):
    return ScreenAMetadataPlugin(app)


# ----------------------------
# Standalone runner (optional)
# ----------------------------

def _standalone():
    root = tk.Tk()
    root.title("Screen A - Metadata-only (standalone)")
    root.geometry("1280x820")

    nb = ttk.Notebook(root)
    nb.pack(fill=tk.BOTH, expand=True)

    plugin = ScreenAMetadataPlugin()
    plugin._root = root  # for standalone convenience
    frame = plugin.build_tab(nb)
    nb.add(frame, text=plugin.meta.title)

    root.mainloop()

if __name__ == "__main__":
    _standalone()
