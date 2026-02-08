# -*- coding: utf-8 -*-
"""
plugin.py — Screen A (metadata-only) as a PRISMA Hub Notebook tab plugin (V2)

Goal of this rewrite
- Use decisions_report.py "v2" contract (stages EH/IH/EL/IL with caches + final_rows)
- Keep UI simple + robust: criteria editor, A loader, staged run buttons, modal progress, exports
- Make logging + progress thread-safe (no Tk calls from worker thread)

Expected engine function (from .metadata):
    screen_metadata(A, criteria, ..., progress=callable, cancel_token=token, subrun="EH|IH|EL|IL", prior_result=<previous run result>)

Expected report helpers (from .decisions_report):
    aggregate_decisions(meta_results_v2, A_rows, pass_thr=..., border_thr=...)
    export_decisions_csv/xlsx(path, meta_results_v2)
    export_metadata_audit_csv/xlsx(path, meta_results_v2, A_rows)
    prisma_counts(final_rows)
    save_metadata_charts(outdir, meta_results_v2)

This file is designed to replace the old plugin.py entirely; no incremental patching.
"""

from __future__ import annotations

TAB_TITLE = "Screen A - Metadata"

import os
import platform
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Hub plugin base/meta
from prisma_hub.plugin_api import BasePlugin, PluginMeta  # type: ignore

# Shared constants (dropdowns)
from .core import (
    ALLOWED_TYPES,
    ALLOWED_SCOPE,
    ALLOWED_OPERATORS,
    LLM_MODEL_PRESETS,
)

# Package-relative imports
from .criteria import (
    parse_criteria_rows,
    harmonize_from_text,
    harmonize_from_rows,
    reformulate_with_llm,
)
from .metadata import (
    parse_A_csv_xlsx,
    screen_metadata,
)
from .decisions_report import (
    aggregate_decisions,
    export_decisions_csv, export_decisions_xlsx,
    export_metadata_audit_csv, export_metadata_audit_xlsx,
    prisma_counts, save_metadata_charts,
)


# ----------------------------
# Cancellation (engine-friendly)
# ----------------------------

class _CancelToken:
    def __init__(self) -> None:
        self.cancelled = False


# ----------------------------
# UI event types
# ----------------------------

@dataclass
class _UiEvent:
    kind: str
    payload: Dict[str, Any]


# ----------------------------
# Plugin
# ----------------------------

class MetadataTabPlugin(BasePlugin):
    """Implements the hub's plugin contract."""

    # Criteria editor columns (include id now)
    CRIT_COLS: Tuple[str, ...] = (
        "enabled", "id", "type", "scope", "label", "operator", "target", "what", "how", "weight", "threshold"
    )

    # Stage tab columns (v2 contract)
    STAGE_COLS: Tuple[str, ...] = (
        "stage", "a_id", "stage_outcome", "passed_to_next", "hard_stop",
        "hard_stop_criterion_id", "hard_stop_criterion_label",
        "stage_reason_summary",
    )

    # Final tab columns (aggregated decision rows produced by aggregate_decisions(v2))
    FINAL_COLS: Tuple[str, ...] = (
        "a_id", "title", "lang", "doc_type", "year", "venue",
        "final_outcome", "discarded_at_stage",
        "outcome_EH", "outcome_IH", "outcome_EL", "outcome_IL",
        "reasons_EH", "reasons_IH", "reasons_EL", "reasons_IL",
        "history",
    )

    def __init__(self, app=None) -> None:
        super().__init__(app, PluginMeta(
            id="screen_A_metadata",
            title="Screen A - Metadata",
            version="2.0.0",
        ))

        # Data state
        self.criteria_rows: List[Dict[str, Any]] = []
        self.A: List[Dict[str, Any]] = []

        # Engine + report state (v2)
        self.meta_results_v2: Optional[Dict[str, Any]] = None   # this is what exporters expect
        self.final_rows: List[Dict[str, Any]] = []             # display-only aggregated decisions
        self.stage_rows: Dict[str, List[Dict[str, Any]]] = {k: [] for k in ("EH", "IH", "EL", "IL")}

        # A index for title lookup
        self._A_index: Dict[str, Dict[str, Any]] = {}

        # Tk vars
        self.var_pass: Optional[tk.DoubleVar] = None
        self.var_border: Optional[tk.DoubleVar] = None
        self.var_missing: Optional[tk.StringVar] = None
        self.var_model: Optional[tk.StringVar] = None
        self.var_hardstop: Optional[tk.BooleanVar] = None
        self.var_A_info: Optional[tk.StringVar] = None

        # Two-stage controls
        self.var_h_mode: Optional[tk.StringVar] = None
        self.var_l_mode: Optional[tk.StringVar] = None
        self.var_randomize: Optional[tk.BooleanVar] = None
        self.var_seed: Optional[tk.StringVar] = None
        self.var_llm_batch: Optional[tk.IntVar] = None
        self.var_llm_trunc: Optional[tk.IntVar] = None

        # UI handles
        self._frame: Optional[ttk.Frame] = None
        self._root: Optional[tk.Misc] = None

        self.tv_crit: Optional[ttk.Treeview] = None
        self.tv_eh: Optional[ttk.Treeview] = None
        self.tv_ih: Optional[ttk.Treeview] = None
        self.tv_el: Optional[ttk.Treeview] = None
        self.tv_il: Optional[ttk.Treeview] = None
        self.tv_final: Optional[ttk.Treeview] = None

        self.txt_log: Optional[tk.Text] = None
        self.lbl_counts: Optional[ttk.Label] = None

        # Context menu (criteria)
        self._menu: Optional[tk.Menu] = None

        # Inline cell editor for criteria
        self._editor: Optional[tk.Widget] = None
        self._editor_info: Optional[Tuple[str, str]] = None  # (iid, colname)

        # Gating flags
        self._gate_eh_done = False
        self._gate_ih_done = False
        self._gate_el_done = False

        # Run / thread / modal
        self._subrun_mode: Optional[str] = None
        self._run_thread: Optional[threading.Thread] = None
        self._ui_q: Optional[queue.Queue] = None
        self._cancel_token: Optional[_CancelToken] = None

        self._modal: Optional[tk.Toplevel] = None
        self._modal_widgets: Dict[str, Any] = {}
        self._run_started_ts: float = 0.0
        self._run_finished: bool = False
        self._run_error: Optional[str] = None

        # ETA
        self._eta_samples = 0
        self._ema_rate: Optional[float] = None
        self._ema_alpha = 0.30
        self._units_done = 0
        self._units_total = 0
        self._h_total = 0
        self._h_done = 0
        self._l_total = 0
        self._l_done = 0

        # Survivor caches (for reuse_from_stage shortcuts)
        self._eh_survivor_ids: List[str] = []
        self._ih_survivor_ids: List[str] = []
        self._el_survivor_ids: List[str] = []

        # Final decisions exist only after I/L has run successfully
        self._has_final: bool = False

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
        return root

    def on_select(self):
        pass

    def on_close(self):
        pass

    # ----------------------------
    # UI: build
    # ----------------------------

    def _build_ui(self, container: tk.Widget) -> None:
        pan = ttk.Panedwindow(container, orient=tk.HORIZONTAL)
        pan.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(pan)
        right = ttk.Frame(pan)
        pan.add(left, weight=1)
        pan.add(right, weight=3)

        # ---------------- Left: controls ----------------
        lf = ttk.LabelFrame(left, text="Controls")
        lf.pack(side=tk.TOP, fill=tk.X, padx=8, pady=8)

        r = 0
        ttk.Button(lf, text="Load Criteria (Text)", command=self.on_load_criteria_text)\
            .grid(row=r, column=0, sticky="we", padx=4, pady=3)
        ttk.Button(lf, text="Load Criteria (CSV/XLSX)", command=self.on_load_criteria_file)\
            .grid(row=r, column=1, sticky="we", padx=4, pady=3)
        r += 1
        ttk.Button(lf, text="Harmonize (deterministic)", command=self.on_harmonize)\
            .grid(row=r, column=0, sticky="we", padx=4, pady=3)
        ttk.Button(lf, text="Reformulate (LLM) - selection or enabled", command=self.on_harmonize_llm)\
            .grid(row=r, column=1, sticky="we", padx=4, pady=3)
        r += 1
        ttk.Button(lf, text="Load A (CSV/XLSX)", command=self.on_load_A)\
            .grid(row=r, column=0, sticky="we", padx=4, pady=(10, 3))

        self.var_A_info = tk.StringVar(value="No A file loaded")
        ttk.Label(lf, textvariable=self.var_A_info, anchor="w")\
            .grid(row=r + 1, column=0, columnspan=2, sticky="w", padx=4, pady=(0, 6))
        r += 2

        for c in range(2):
            lf.columnconfigure(c, weight=1)

        # ---------------- Options ----------------
        opt = ttk.LabelFrame(left, text="Screening Options")
        opt.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)

        Spinbox = getattr(ttk, "Spinbox", tk.Spinbox)  # type: ignore

        ttk.Label(opt, text="Pass threshold").grid(row=0, column=0, sticky="w", padx=4)
        self.var_pass = tk.DoubleVar(value=0.60)
        Spinbox(opt, from_=0.0, to=1.0, increment=0.05, textvariable=self.var_pass, width=6)\
            .grid(row=0, column=1, sticky="w")

        ttk.Label(opt, text="Border threshold").grid(row=0, column=2, sticky="w", padx=(12, 4))
        self.var_border = tk.DoubleVar(value=0.40)
        Spinbox(opt, from_=0.0, to=1.0, increment=0.05, textvariable=self.var_border, width=6)\
            .grid(row=0, column=3, sticky="w")

        ttk.Label(opt, text="Missing policy").grid(row=1, column=0, sticky="w", padx=4, pady=(6, 0))
        self.var_missing = tk.StringVar(value="unknown")
        ttk.Combobox(opt, textvariable=self.var_missing, values=["unknown", "negative"], width=10, state="readonly")\
            .grid(row=1, column=1, sticky="w", pady=(6, 0))

        ttk.Label(opt, text="LLM model (optional)").grid(row=1, column=2, sticky="w", padx=(12, 4), pady=(6, 0))
        self.var_model = tk.StringVar(value="")
        cmb_model = ttk.Combobox(opt, textvariable=self.var_model, values=list(LLM_MODEL_PRESETS), width=20, state="normal")
        cmb_model.grid(row=1, column=3, sticky="w", pady=(6, 0))
        cmb_model.set("")

        self.var_hardstop = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="Hard-stop per criterion", variable=self.var_hardstop)\
            .grid(row=2, column=0, columnspan=4, sticky="w", padx=4, pady=(6, 0))

        for c in range(4):
            opt.columnconfigure(c, weight=1)

        # ---------------- Two-stage controls ----------------
        stg = ttk.LabelFrame(left, text="Two-Stage Controls")
        stg.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        ttk.Label(stg, text="Stage H include mode").grid(row=0, column=0, sticky="w", padx=4)
        self.var_h_mode = tk.StringVar(value="all")
        ttk.Combobox(stg, textvariable=self.var_h_mode, values=["all", "any"], width=8, state="readonly")\
            .grid(row=0, column=1, sticky="w")

        ttk.Label(stg, text="Stage L include mode").grid(row=0, column=2, sticky="w", padx=(12, 4))
        self.var_l_mode = tk.StringVar(value="all")
        ttk.Combobox(stg, textvariable=self.var_l_mode, values=["all", "any"], width=8, state="readonly")\
            .grid(row=0, column=3, sticky="w")

        self.var_randomize = tk.BooleanVar(value=True)
        ttk.Checkbutton(stg, text="Randomize order within excludes/includes", variable=self.var_randomize)\
            .grid(row=1, column=0, columnspan=4, sticky="w", padx=4, pady=(6, 0))

        ttk.Label(stg, text="Seed (optional)").grid(row=2, column=0, sticky="w", padx=4, pady=(6, 0))
        self.var_seed = tk.StringVar(value="")
        ttk.Entry(stg, textvariable=self.var_seed, width=18).grid(row=2, column=1, sticky="w", pady=(6, 0))

        ttk.Label(stg, text="LLM batch size").grid(row=2, column=2, sticky="w", padx=(12, 4), pady=(6, 0))
        self.var_llm_batch = tk.IntVar(value=75)
        Spinbox(stg, from_=1, to=500, increment=1, textvariable=self.var_llm_batch, width=8)\
            .grid(row=2, column=3, sticky="w", pady=(6, 0))

        ttk.Label(stg, text="Max chars per field").grid(row=3, column=0, sticky="w", padx=4, pady=(6, 0))
        self.var_llm_trunc = tk.IntVar(value=1500)
        Spinbox(stg, from_=200, to=8000, increment=50, textvariable=self.var_llm_trunc, width=8)\
            .grid(row=3, column=1, sticky="w", pady=(6, 0))

        for c in range(4):
            stg.columnconfigure(c, weight=1)

        # ---------------- Run (gated) ----------------
        gate = ttk.LabelFrame(left, text="Run (staged)")
        gate.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        self.btn_eh = ttk.Button(gate, text="Run E/H (Exclude - Heuristic)", command=lambda: self.on_run_substage("EH"))
        self.btn_ih = ttk.Button(gate, text="Run I/H (Include - Heuristic)", command=lambda: self.on_run_substage("IH"))
        self.btn_el = ttk.Button(gate, text="Run E/L (Exclude - LLM)", command=lambda: self.on_run_substage("EL"))
        self.btn_il = ttk.Button(gate, text="Run I/L (Include - LLM - Final)", command=lambda: self.on_run_substage("IL"))
        self.btn_reset = ttk.Button(gate, text="Reset staged flow", command=self._reset_gated_flow)

        self.btn_eh.grid(row=0, column=0, sticky="we", padx=4, pady=4)
        self.btn_ih.grid(row=0, column=1, sticky="we", padx=4, pady=4)
        self.btn_el.grid(row=1, column=0, sticky="we", padx=4, pady=4)
        self.btn_il.grid(row=1, column=1, sticky="we", padx=4, pady=4)
        self.btn_reset.grid(row=2, column=0, columnspan=2, sticky="we", padx=4, pady=(8, 4))

        for c in range(2):
            gate.columnconfigure(c, weight=1)

        # ---------------- Export ----------------
        exp = ttk.LabelFrame(left, text="Export")
        exp.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)

        ttk.Button(exp, text="Export Decisions (CSV)", command=self.on_export_decisions_csv)\
            .grid(row=0, column=0, sticky="we", padx=4, pady=3)
        ttk.Button(exp, text="Export Decisions (XLSX)", command=self.on_export_decisions_xlsx)\
            .grid(row=0, column=1, sticky="we", padx=4, pady=3)
        ttk.Button(exp, text="Export Audit (CSV)", command=self.on_export_audit_csv)\
            .grid(row=1, column=0, sticky="we", padx=4, pady=3)
        ttk.Button(exp, text="Export Audit (XLSX)", command=self.on_export_audit_xlsx)\
            .grid(row=1, column=1, sticky="we", padx=4, pady=3)
        ttk.Button(exp, text="Save Charts (PNG)", command=self.on_save_charts)\
            .grid(row=2, column=0, columnspan=2, sticky="we", padx=4, pady=(6, 3))

        for c in range(2):
            exp.columnconfigure(c, weight=1)

        # ---------------- Right: Notebook tabs ----------------
        nb = ttk.Notebook(right)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Criteria tab
        crit_tab = ttk.Frame(nb)
        nb.add(crit_tab, text="Criteria")
        self.tv_crit = ttk.Treeview(crit_tab, columns=self.CRIT_COLS, show="headings", selectmode="extended")
        ys = ttk.Scrollbar(crit_tab, orient="vertical", command=self.tv_crit.yview)
        xs = ttk.Scrollbar(crit_tab, orient="horizontal", command=self.tv_crit.xview)
        self.tv_crit.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)

        # Styles for disabled rows (best-effort)
        try:
            self.tv_crit.tag_configure("disabled", foreground="#888888")
        except Exception:
            pass

        for c in self.CRIT_COLS:
            w = 110
            if c == "enabled":
                w = 70
            elif c == "id":
                w = 80
            elif c == "label":
                w = 260
            elif c == "what":
                w = 220
            elif c == "target":
                w = 160
            self.tv_crit.heading(c, text=c)
            self.tv_crit.column(c, width=w, anchor="w", stretch=False)

        crit_tab.rowconfigure(0, weight=1)
        crit_tab.columnconfigure(0, weight=1)
        self.tv_crit.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")

        self._bind_tree_mousewheel(self.tv_crit)

        # Inline editing & context menu & shortcuts
        self.tv_crit.bind("<Double-1>", self._on_crit_cell_dblclick)
        self.tv_crit.bind("<Button-1>", self._on_crit_click_prevent_stray_editor)
        self.tv_crit.bind("<Button-3>", self._on_right_click)

        # Context menu
        self._menu = tk.Menu(self.tv_crit, tearoff=0)
        self._menu.add_command(label="Enable", command=self.enable_selected)
        self._menu.add_command(label="Disable", command=self.disable_selected)
        self._menu.add_command(label="Toggle", command=self.toggle_enable_selected)
        self._menu.add_separator()
        self._menu.add_command(label="Duplicate", command=self.duplicate_selected)
        self._menu.add_separator()
        self._menu.add_command(label="Delete permanently...", command=self.delete_selected)

        # Stage tabs
        self.tv_eh = self._add_stage_tab(nb, "E/H", "EH")
        self.tv_ih = self._add_stage_tab(nb, "I/H", "IH")
        self.tv_el = self._add_stage_tab(nb, "E/L", "EL")
        self.tv_il = self._add_stage_tab(nb, "I/L", "IL")

        # Final tab
        final_tab = ttk.Frame(nb)
        nb.add(final_tab, text="Final")
        topbar = ttk.Frame(final_tab)
        topbar.pack(fill=tk.X, pady=(0, 6))

        self.lbl_counts = ttk.Label(topbar, text="Counts: -")
        self.lbl_counts.pack(side=tk.LEFT)

        self.tv_final = ttk.Treeview(final_tab, columns=self.FINAL_COLS, show="headings")
        ys_f = ttk.Scrollbar(final_tab, orient="vertical", command=self.tv_final.yview)
        xs_f = ttk.Scrollbar(final_tab, orient="horizontal", command=self.tv_final.xview)
        self.tv_final.configure(yscrollcommand=ys_f.set, xscrollcommand=xs_f.set)

        for c in self.FINAL_COLS:
            w = 140
            if c == "a_id":
                w = 80
            elif c == "title":
                w = 460
            elif c in {"lang", "doc_type", "year"}:
                w = 90
            elif c == "venue":
                w = 180
            elif c in {"final_outcome", "discarded_at_stage"}:
                w = 150
            elif c.startswith("outcome_"):
                w = 110
            elif c.startswith("reasons_"):
                w = 280
            elif c == "history":
                w = 260

            self.tv_final.heading(c, text=c)
            self.tv_final.column(c, width=w, anchor="w", stretch=False)

        final_tab.rowconfigure(1, weight=1)
        final_tab.columnconfigure(0, weight=1)
        self.tv_final.pack(fill=tk.BOTH, expand=True)
        ys_f.pack(side=tk.RIGHT, fill=tk.Y)
        xs_f.pack(side=tk.BOTTOM, fill=tk.X)

        self._bind_tree_mousewheel(self.tv_final)

        # Log box
        logf = ttk.LabelFrame(right, text="Log")
        logf.pack(side=tk.BOTTOM, fill=tk.BOTH, padx=8, pady=(0, 8))
        self.txt_log = tk.Text(logf, height=8)
        self.txt_log.pack(fill=tk.BOTH, expand=True)

        # Keyboard shortcuts (criteria)
        is_mac = platform.system() == "Darwin"
        mod = "Command" if is_mac else "Control"
        self.tv_crit.bind("<Delete>", lambda e: self.disable_selected())
        self.tv_crit.bind("<Shift-Delete>", lambda e: self.delete_selected())
        self.tv_crit.bind(f"<{mod}-d>", lambda e: self.duplicate_selected())
        self.tv_crit.bind(f"<{mod}-e>", lambda e: self.toggle_enable_selected())

        # Initialize gating + tables
        self._reset_gated_flow(log_line=False)
        self._update_stage_buttons()

    def _add_stage_tab(self, nb: ttk.Notebook, label: str, stage_key: str) -> ttk.Treeview:
        tab = ttk.Frame(nb)
        nb.add(tab, text=label)
        tv = ttk.Treeview(tab, columns=self.STAGE_COLS, show="headings")
        ys = ttk.Scrollbar(tab, orient="vertical", command=tv.yview)
        xs = ttk.Scrollbar(tab, orient="horizontal", command=tv.xview)
        tv.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)

        # Tags
        try:
            tv.tag_configure("out", foreground="#8B0000")
            tv.tag_configure("in", foreground="#006400")
        except Exception:
            pass

        for c in self.STAGE_COLS:
            w = 140
            if c == "stage":
                w = 70
            elif c == "a_id":
                w = 80
            elif c in {"stage_outcome", "passed_to_next"}:
                w = 120
            elif c == "hard_stop":
                w = 90
            elif c in {"hard_stop_criterion_id"}:
                w = 160
            elif c in {"hard_stop_criterion_label"}:
                w = 260
            elif c == "stage_reason_summary":
                w = 520
            tv.heading(c, text=c)
            tv.column(c, width=w, anchor="w", stretch=False)

        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)
        tv.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")

        self._bind_tree_mousewheel(tv)
        return tv

    # ----------------------------
    # UI utilities
    # ----------------------------

    def _parent_toplevel(self) -> tk.Misc:
        try:
            if self._frame:
                return self._frame.winfo_toplevel()
        except Exception:
            pass
        if self._root:
            return self._root
        if self.tv_crit:
            return self.tv_crit.winfo_toplevel()
        raise RuntimeError("No parent toplevel available")

    def _bind_tree_mousewheel(self, tv: ttk.Treeview) -> None:
        def _on_mousewheel(event):
            if event.num == 4:
                tv.yview_scroll(-1, "units")
            elif event.num == 5:
                tv.yview_scroll(1, "units")
            else:
                delta = int(-1 * (event.delta / 120))
                tv.yview_scroll(delta, "units")
            return "break"

        def _on_shift_wheel(event):
            if event.num in (4, 5):
                tv.xview_scroll(-1 if event.num == 4 else 1, "units")
            else:
                delta = int(-1 * (event.delta / 120))
                tv.xview_scroll(delta, "units")
            return "break"

        tv.bind("<MouseWheel>", _on_mousewheel, add="+")
        tv.bind("<Shift-MouseWheel>", _on_shift_wheel, add="+")
        tv.bind("<Button-4>", _on_mousewheel, add="+")
        tv.bind("<Button-5>", _on_mousewheel, add="+")
        tv.bind("<Shift-Button-4>", _on_shift_wheel, add="+")
        tv.bind("<Shift-Button-5>", _on_shift_wheel, add="+")

    def _safe_str(self, v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, (list, tuple)):
            return "; ".join(self._safe_str(x) for x in v if x is not None and str(x).strip())
        return str(v)

    # ----------------------------
    # Thread-safe logging
    # ----------------------------

    def log(self, msg: str) -> None:
        """
        Thread-safe: if called from worker thread, push to UI queue.
        """
        if self._ui_q is not None and threading.current_thread() is not threading.main_thread():
            self._ui_q.put(_UiEvent("log", {"msg": msg}))
            return
        self._append_log(msg)

    def _append_log(self, msg: str) -> None:
        if self.txt_log is None:
            return
        self.txt_log.insert(tk.END, msg)
        self.txt_log.see(tk.END)

    # ----------------------------
    # Criteria: load / harmonize / reformulate
    # ----------------------------

    def on_load_criteria_text(self) -> None:
        win = tk.Toplevel(self._parent_toplevel())
        win.title("Paste Criteria (IC/EC lines)")
        txt = tk.Text(win, width=90, height=18)
        txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        def accept():
            raw = txt.get("1.0", tk.END)
            rows = harmonize_from_text(raw)
            for r in rows:
                r.setdefault("enabled", True)
            self.criteria_rows = rows
            self._refresh_criteria_table()
            self.log(f"[CRITERIA] Parsed {len(rows)} row(s) from text.\n")
            self._reset_gated_flow()
            win.destroy()

        ttk.Button(win, text="Use these", command=accept).pack(pady=8)

    def on_load_criteria_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open Criteria CSV/XLSX",
            filetypes=[("CSV", "*.csv"), ("Excel", "*.xlsx *.xls"), ("All", "*.*")]
        )
        if not path:
            return
        rows = parse_criteria_rows(path)
        rows = harmonize_from_rows(rows)
        for r in rows:
            r.setdefault("enabled", True)
        self.criteria_rows = rows
        self._refresh_criteria_table()
        self.log(f"[CRITERIA] Loaded {len(rows)} row(s) from {os.path.basename(path)}.\n")
        self._reset_gated_flow()

    def _preserve_enabled_and_replace(self, new_rows: List[Dict[str, Any]]) -> None:
        prev = {str(r.get("id")): bool(r.get("enabled", True))
                for r in self.criteria_rows if r.get("id") is not None}
        out: List[Dict[str, Any]] = []
        for r in new_rows:
            rid = str(r.get("id"))
            r2 = dict(r)
            r2["enabled"] = prev.get(rid, bool(r.get("enabled", True)) if "enabled" in r else True)
            out.append(r2)
        self.criteria_rows = out

    def on_harmonize(self) -> None:
        if not self.criteria_rows:
            messagebox.showwarning("Harmonize", "Load/paste criteria first.")
            return
        rows = harmonize_from_rows(self.criteria_rows)
        self._preserve_enabled_and_replace(rows)
        self._refresh_criteria_table()
        self.log("[CRITERIA] Harmonized deterministically.\n")
        self._reset_gated_flow()

    def _selected_criteria_indices(self) -> List[int]:
        if not self.tv_crit:
            return []
        sel = list(self.tv_crit.selection())
        try:
            return sorted({int(i) for i in sel})
        except Exception:
            return []

    def _merge_llm_reformulated_rows(self, llm_rows: List[Dict[str, Any]]) -> None:
        by_id = {str(r.get("id")): dict(r) for r in (llm_rows or []) if r.get("id")}
        if not by_id:
            return
        out: List[Dict[str, Any]] = []
        for r in self.criteria_rows:
            rid = str(r.get("id") or "")
            if rid and rid in by_id:
                nr = by_id[rid]
                nr["enabled"] = r.get("enabled", True)
                out.append(nr)
            else:
                out.append(r)
        self.criteria_rows = out

    def on_harmonize_llm(self) -> None:
        if not self.criteria_rows:
            messagebox.showwarning("LLM Reformulate", "Load/paste criteria first.")
            return

        idxs = self._selected_criteria_indices()
        if idxs:
            target_rows = [self.criteria_rows[i] for i in idxs if 0 <= i < len(self.criteria_rows)]
            scope_msg = f"{len(target_rows)} selected row(s)"
        else:
            enabled_rows = [r for r in self.criteria_rows if bool(r.get("enabled", True))]
            target_rows = enabled_rows if enabled_rows else list(self.criteria_rows)
            scope_msg = f"{len(target_rows)} row(s) ({'enabled' if enabled_rows else 'all'})"

        if not target_rows:
            messagebox.showwarning("LLM Reformulate", "No criteria to reformulate.")
            return

        model = (self.var_model.get().strip() if self.var_model else "") or "gpt-4o-mini"
        self.log(f"[CRITERIA] LLM reformulation on {scope_msg} using model={model}...\n")

        try:
            llm_rows = reformulate_with_llm(target_rows, model=model, log=self.log)
        except Exception as e:
            messagebox.showerror("LLM Reformulate", str(e))
            return

        self._merge_llm_reformulated_rows(llm_rows)
        self._refresh_criteria_table()
        self.log(f"[CRITERIA] Reformulated via LLM ({model}): updated {len(llm_rows)} row(s).\n")
        self._reset_gated_flow()

    # ----------------------------
    # A loader
    # ----------------------------

    def on_load_A(self) -> None:
        path = filedialog.askopenfilename(
            title="Open A CSV/XLSX",
            filetypes=[("CSV", "*.csv"), ("Excel", "*.xlsx *.xls"), ("All", "*.*")]
        )
        if not path:
            return

        self.A = parse_A_csv_xlsx(path)
        basename = os.path.basename(path)
        count = len(self.A)

        if self.var_A_info is not None:
            self.var_A_info.set(f"{basename} - {count} item(s)")

        self._A_index = {str(d.get("a_id")): d for d in self.A if isinstance(d, dict) and d.get("a_id") is not None}
        self.log(f"[A] Loaded {count} items from {basename}.\n")

        self._reset_gated_flow()

    # ----------------------------
    # Criteria table rendering + editing
    # ----------------------------

    def _row_enabled_disp(self, row: Dict[str, Any]) -> str:
        return "on" if row.get("enabled", True) else "off"

    def _refresh_criteria_table(self) -> None:
        if not self.tv_crit:
            return
        self.tv_crit.delete(*self.tv_crit.get_children())
        for idx, r in enumerate(self.criteria_rows):
            iid = str(idx)
            tags = ("disabled",) if not r.get("enabled", True) else ()
            self.tv_crit.insert("", tk.END, iid=iid, values=(
                self._row_enabled_disp(r),
                r.get("id"),
                r.get("type"),
                r.get("scope"),
                r.get("label"),
                r.get("operator"),
                r.get("target"),
                ", ".join(r.get("what") or []),
                r.get("how"),
                r.get("weight"),
                r.get("threshold"),
            ), tags=tags)

    def _on_crit_click_prevent_stray_editor(self, _evt) -> None:
        if self._editor:
            self._close_editor(commit=True)

    def _on_right_click(self, event) -> None:
        if not self._menu or not self.tv_crit:
            return
        row_id = self.tv_crit.identify_row(event.y)
        if row_id:
            current = set(self.tv_crit.selection())
            if row_id not in current:
                self.tv_crit.selection_set(row_id)
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    def _close_editor(self, commit: bool = True) -> None:
        if not self._editor or not self._editor_info:
            return
        iid, colname = self._editor_info
        try:
            if commit:
                self._commit_editor_value(iid, colname)
        finally:
            try:
                self._editor.destroy()
            except Exception:
                pass
            self._editor = None
            self._editor_info = None

    def _commit_editor_value(self, iid: str, colname: str) -> None:
        if not self.tv_crit:
            return
        idx = int(iid)
        if idx < 0 or idx >= len(self.criteria_rows):
            return
        row = self.criteria_rows[idx]

        def set_and_refresh(val: Any):
            # normalize types
            if colname in ("weight", "threshold"):
                try:
                    val = float(val)
                except Exception:
                    pass
            if colname == "what":
                row[colname] = [p.strip() for p in str(val).split(",") if p.strip()]
            elif colname == "enabled":
                row[colname] = bool(val)
            else:
                row[colname] = val

            # update row in UI
            disp = list(self.tv_crit.item(iid, "values"))
            col_index = self.CRIT_COLS.index(colname)
            if colname == "what":
                disp[col_index] = ", ".join(row.get("what") or [])
            elif colname == "enabled":
                disp[col_index] = self._row_enabled_disp(row)
            else:
                disp[col_index] = "" if val is None else str(val)

            tags = ("disabled",) if not row.get("enabled", True) else ()
            self.tv_crit.item(iid, values=tuple(disp), tags=tags)
            self._reset_gated_flow(log_line=False)

        w = self._editor
        if isinstance(w, ttk.Combobox):
            if colname == "enabled":
                set_and_refresh(w.get().strip().lower() in ("on", "true", "1", "yes"))
            else:
                set_and_refresh(w.get().strip())
        elif isinstance(w, (tk.Entry, ttk.Entry)):
            set_and_refresh(w.get())
        elif isinstance(w, (tk.Spinbox, getattr(ttk, "Spinbox", tk.Spinbox))):  # type: ignore
            set_and_refresh(w.get())

    def _on_crit_cell_dblclick(self, event) -> None:
        if not self.tv_crit:
            return
        self._close_editor(commit=True)

        region = self.tv_crit.identify("region", event.x, event.y)
        if region != "cell":
            return
        row_id = self.tv_crit.identify_row(event.y)
        col_id = self.tv_crit.identify_column(event.x)
        if not row_id or not col_id:
            return

        col_index = int(col_id.replace("#", "")) - 1
        if col_index < 0 or col_index >= len(self.CRIT_COLS):
            return
        colname = self.CRIT_COLS[col_index]

        # Toggle enabled directly
        if colname == "enabled":
            idx = int(row_id)
            cur = bool(self.criteria_rows[idx].get("enabled", True))
            self.criteria_rows[idx]["enabled"] = (not cur)
            self._refresh_criteria_table()
            self._reset_gated_flow(log_line=False)
            return

        # Open target selector (checkboxes)
        if colname == "target":
            self._open_target_selector(row_id)
            return

        bbox = self.tv_crit.bbox(row_id, col_id)
        if not bbox:
            return
        x, y, width, height = bbox
        current_val = self.tv_crit.set(row_id, colname)

        editor: Optional[tk.Widget] = None
        Spinbox = getattr(ttk, "Spinbox", tk.Spinbox)  # type: ignore

        if colname == "id":
            editor = ttk.Entry(self.tv_crit)
            editor.insert(0, current_val or "")

        elif colname == "type":
            editor = ttk.Combobox(self.tv_crit, values=sorted(ALLOWED_TYPES), state="readonly")
            editor.set(current_val or "include")

        elif colname == "scope":
            # metadata-only plugin: scope is fixed (but keep visible)
            editor = ttk.Combobox(self.tv_crit, values=sorted(ALLOWED_SCOPE), state="readonly")
            editor.set("metadata")

        elif colname == "label":
            editor = ttk.Entry(self.tv_crit)
            editor.insert(0, current_val or "")

        elif colname == "operator":
            editor = ttk.Combobox(self.tv_crit, values=sorted(ALLOWED_OPERATORS), state="readonly")
            fallback = current_val if current_val in ALLOWED_OPERATORS else "contains"
            editor.set(fallback)

        elif colname == "what":
            editor = ttk.Entry(self.tv_crit)
            editor.insert(0, current_val or "")

        elif colname == "how":
            editor = ttk.Combobox(self.tv_crit, values=["heuristic", "llm"], state="readonly")
            fallback = current_val if current_val in {"heuristic", "llm"} else "heuristic"
            editor.set(fallback)
            editor.bind("<<ComboboxSelected>>", lambda e: self._close_editor(commit=True))

        elif colname == "weight":
            editor = Spinbox(self.tv_crit, from_=0.0, to=10.0, increment=0.5, width=6)
            try:
                editor.delete(0, tk.END)
                editor.insert(0, float(current_val))
            except Exception:
                editor.delete(0, tk.END)
                editor.insert(0, "1.0")

        elif colname == "threshold":
            editor = Spinbox(self.tv_crit, from_=0.0, to=1.0, increment=0.05, width=6)
            try:
                editor.delete(0, tk.END)
                editor.insert(0, float(current_val))
            except Exception:
                editor.delete(0, tk.END)
                editor.insert(0, "0.60")

        else:
            return

        if editor is not None:
            editor.place(in_=self.tv_crit, x=x, y=y, width=width, height=height)
            editor.focus_set()
            editor.bind("<Return>", lambda e: self._close_editor(commit=True))
            editor.bind("<Escape>", lambda e: self._close_editor(commit=False))
            editor.bind("<FocusOut>", lambda e: self._close_editor(commit=True))
            self._editor = editor
            self._editor_info = (row_id, colname)

    def _discover_target_fields(self) -> List[str]:
        fallback = ["title", "abstract", "keywords", "lang", "doc_type", "availability", "year", "venue"]
        if not self.A:
            return fallback
        keys: set[str] = set()
        for r in self.A[:25]:
            if isinstance(r, dict):
                keys |= {k for k in r.keys() if isinstance(k, str)}
        ordered = [f for f in fallback if f in keys]
        extras = sorted([k for k in keys if k not in ordered])
        return ordered + extras

    def _open_target_selector(self, row_id: str) -> None:
        idx = int(row_id)
        if idx < 0 or idx >= len(self.criteria_rows):
            return

        choices = self._discover_target_fields()
        current = self.criteria_rows[idx].get("target") or ""
        current_set = {t.strip() for t in str(current).split(",") if t.strip()}

        win = tk.Toplevel(self._parent_toplevel())
        win.title("Select target fields")
        win.transient(self._parent_toplevel())
        win.grab_set()

        frm = ttk.Frame(win)
        frm.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        vars_map: Dict[str, tk.BooleanVar] = {}
        for i, fld in enumerate(choices):
            var = tk.BooleanVar(value=(fld in current_set))
            ttk.Checkbutton(frm, text=fld, variable=var)\
                .grid(row=i // 3, column=i % 3, sticky="w", padx=6, pady=4)
            vars_map[fld] = var

        btns = ttk.Frame(win)
        btns.pack(fill=tk.X, padx=10, pady=(6, 10))

        def accept():
            selected = [k for k, v in vars_map.items() if v.get()]
            selected_str = ",".join(selected)
            self.criteria_rows[idx]["target"] = selected_str if selected else ""
            if self.tv_crit:
                vals = list(self.tv_crit.item(row_id, "values"))
                col_index = self.CRIT_COLS.index("target")
                vals[col_index] = selected_str
                self.tv_crit.item(row_id, values=tuple(vals))
            self._reset_gated_flow(log_line=False)
            win.destroy()

        ttk.Button(btns, text="OK", command=accept).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side=tk.RIGHT, padx=(0, 8))

    # ----------------------------
    # Criteria: enable/disable/duplicate/delete
    # ----------------------------

    def _selected_indices(self) -> List[int]:
        if not self.tv_crit:
            return []
        ids = list(self.tv_crit.selection())
        try:
            return sorted(set(int(i) for i in ids))
        except Exception:
            return []

    def enable_selected(self) -> None:
        idxs = self._selected_indices()
        if not idxs:
            return
        for i in idxs:
            if 0 <= i < len(self.criteria_rows):
                self.criteria_rows[i]["enabled"] = True
        self._refresh_criteria_table()
        self.log(f"[CRITERIA] Enabled {len(idxs)} row(s).\n")
        self._reset_gated_flow(log_line=False)

    def disable_selected(self) -> None:
        idxs = self._selected_indices()
        if not idxs:
            return
        for i in idxs:
            if 0 <= i < len(self.criteria_rows):
                self.criteria_rows[i]["enabled"] = False
        self._refresh_criteria_table()
        self.log(f"[CRITERIA] Disabled {len(idxs)} row(s).\n")
        self._reset_gated_flow(log_line=False)

    def toggle_enable_selected(self) -> None:
        idxs = self._selected_indices()
        if not idxs:
            return
        for i in idxs:
            if 0 <= i < len(self.criteria_rows):
                cur = bool(self.criteria_rows[i].get("enabled", True))
                self.criteria_rows[i]["enabled"] = not cur
        self._refresh_criteria_table()
        self.log(f"[CRITERIA] Toggled {len(idxs)} row(s).\n")
        self._reset_gated_flow(log_line=False)

    def _generate_new_id(self, base: str) -> str:
        base = (base or "C").strip()
        used = {str(r.get("id")) for r in self.criteria_rows if r.get("id")}
        # try suffix letters first
        for i in range(1, 27):
            cand = f"{base}{chr(96 + i)}"
            if cand not in used:
                return cand
        # fallback numeric
        n = 1
        while f"{base}_{n}" in used:
            n += 1
        return f"{base}_{n}"

    def duplicate_selected(self) -> None:
        idxs = self._selected_indices()
        if not idxs:
            return
        new_rows: List[Tuple[int, Dict[str, Any]]] = []
        for i in idxs:
            if 0 <= i < len(self.criteria_rows):
                src = dict(self.criteria_rows[i])
                base_id = str(src.get("id") or f"C{i+1:02d}")
                src["id"] = self._generate_new_id(base_id)
                src["label"] = f"{(src.get('label') or '').strip()} (copy)".strip()
                src["enabled"] = True
                new_rows.append((i, src))
        offset = 0
        for i, row in new_rows:
            self.criteria_rows.insert(i + 1 + offset, row)
            offset += 1
        self._refresh_criteria_table()
        self.log(f"[CRITERIA] Duplicated {len(new_rows)} row(s).\n")
        self._reset_gated_flow()

    def delete_selected(self) -> None:
        idxs = self._selected_indices()
        if not idxs:
            return
        if not messagebox.askyesno("Delete permanently",
                                   f"Delete {len(idxs)} selected row(s) permanently? This cannot be undone."):
            return
        for i in sorted(idxs, reverse=True):
            if 0 <= i < len(self.criteria_rows):
                del self.criteria_rows[i]
        self._refresh_criteria_table()
        self.log(f"[CRITERIA] Deleted {len(idxs)} row(s).\n")
        self._reset_gated_flow()

    # ----------------------------
    # Run: params + gating + worker
    # ----------------------------

    def _collect_run_params(self) -> Tuple[float, float, str, Optional[str], int, int, str, str, bool, Optional[str], bool, Dict[str, Any]]:
        if not self.criteria_rows:
            raise RuntimeError("Please load/harmonize criteria first.")
        if not self.A:
            raise RuntimeError("Please load A (CSV/XLSX) first.")

        pass_thr = float(self.var_pass.get()) if self.var_pass else 0.60
        border_thr = float(self.var_border.get()) if self.var_border else 0.40
        missing_policy = (self.var_missing.get().strip() if self.var_missing else "unknown")

        model = (self.var_model.get().strip() if self.var_model else "") or None
        needs_llm = any(
            r.get("enabled", True) and (
                str(r.get("how", "")).strip().lower() == "llm" or
                str(r.get("operator", "")).strip().lower() == "llm"
            )
            for r in self.criteria_rows
        )
        if needs_llm and not model:
            model = "gpt-4o-mini"
            self.log("[RUN] No LLM model selected; using default: gpt-4o-mini\n")

        hard_stop = bool(self.var_hardstop.get()) if self.var_hardstop else True

        h_mode = (self.var_h_mode.get().strip() if self.var_h_mode else "all")
        l_mode = (self.var_l_mode.get().strip() if self.var_l_mode else "all")
        randomize = bool(self.var_randomize.get()) if self.var_randomize else True
        seed = (self.var_seed.get().strip() if self.var_seed else "") or None

        llm_batch = int(self.var_llm_batch.get()) if self.var_llm_batch else 75
        llm_trunc = int(self.var_llm_trunc.get()) if self.var_llm_trunc else 1500

        run_params = {"model": model or "(none)", "llm_batch": llm_batch, "llm_trunc": llm_trunc}
        return (
            pass_thr, border_thr, missing_policy, model, llm_trunc, llm_batch,
            h_mode, l_mode, randomize, seed, hard_stop, run_params
        )

    def on_run_substage(self, mode: str) -> None:
        mode = (mode or "").upper().strip()
        self._subrun_mode = mode

        try:
            args = self._collect_run_params()
        except RuntimeError as e:
            messagebox.showwarning("Run", str(e))
            return

        # gating: keep the same UX contract as before
        if mode == "IH" and not self._gate_eh_done:
            messagebox.showinfo("Gated", "Run E/H first.")
            return
        if mode == "EL" and not (self._gate_eh_done and self._gate_ih_done):
            messagebox.showinfo("Gated", "Run E/H and I/H first.")
            return
        if mode == "IL" and not (self._gate_eh_done and self._gate_ih_done and self._gate_el_done):
            messagebox.showinfo("Gated", "Run E/H, I/H and E/L first.")
            return

        self._start_run_worker(args, subrun=mode)

    def _start_run_worker(self, args_tuple: Tuple, subrun: str) -> None:
        (pass_thr, border_thr, missing_policy, model, llm_trunc, llm_batch,
         h_mode, l_mode, randomize, seed, hard_stop, run_params) = args_tuple

        # Reset run state
        self._run_finished = False
        self._run_error = None

        self._ui_q = queue.Queue()
        self._cancel_token = _CancelToken()

        # ETA reset
        self._eta_samples = 0
        self._ema_rate = None
        self._units_done = 0
        self._units_total = 0
        self._h_total = 0
        self._h_done = 0
        self._l_total = 0
        self._l_done = 0

        # Modal + disable controls
        self._open_progress_modal(run_params, subrun=subrun)
        self._set_controls_state(enabled=False)

        worker_args = (
            pass_thr, border_thr, missing_policy, model, llm_trunc, llm_batch,
            h_mode, l_mode, randomize, seed, hard_stop, subrun
        )
        self._run_thread = threading.Thread(target=self._worker_run, args=worker_args, daemon=True)
        self._run_thread.start()
        self._run_started_ts = time.time()

        # In staged flow, EL/IL do not execute H inside this call; prior H results are used as input filters.
        if subrun in ("EL", "IL"):
            self._emit_progress({"kind": "h_stage_skipped", "stage": "H", "reason": "staged_flow_prior_results"})

        self._poll_modal_updates()

    def _emit_progress(self, evt: Dict[str, Any]) -> None:
        if self._ui_q is not None:
            self._ui_q.put(_UiEvent("progress", evt))

    def _call_engine_flex(self, **kwargs) -> Any:
        """
        Call screen_metadata with contract-safe compatibility:
        - First call with all kwargs
        - If TypeError: drop ONLY non-contract convenience keys (never prior_result / subrun)
        """
        try:
            return screen_metadata(**kwargs)  # type: ignore[arg-type]
        except TypeError:
            pass

        # fallback sequence (strict contract):
        # - NEVER drop prior_result (progressive merge must remain enforced)
        # - NEVER drop subrun (no full-pipeline mode in this plugin contract)
        opt_keys = ["reuse_from_stage", "initial_a_ids", "cancel_token"]
        for k in opt_keys:
            if k in kwargs:
                kwargs2 = dict(kwargs)
                kwargs2.pop(k, None)
                try:
                    return screen_metadata(**kwargs2)  # type: ignore[arg-type]
                except TypeError:
                    kwargs = kwargs2
                    continue

        raise

    def _worker_run(self,
                    pass_thr: float, border_thr: float, missing_policy: str,
                    model: Optional[str], llm_trunc: int, llm_batch: int,
                    h_mode: str, l_mode: str, randomize: bool, seed: Optional[str],
                    hard_stop: bool, subrun: str) -> None:
        try:
            # Snapshot current staged state so Cancel/Error keeps previous results intact
            _prev_meta_results_v2 = self.meta_results_v2
            _prev_final_rows = list(self.final_rows)
            _prev_stage_rows = {k: list(v) for k, v in self.stage_rows.items()}
            _prev_eh_surv = list(self._eh_survivor_ids)
            _prev_ih_surv = list(self._ih_survivor_ids)
            _prev_el_surv = list(self._el_survivor_ids)
            _prev_gate_eh = self._gate_eh_done
            _prev_gate_ih = self._gate_ih_done
            _prev_gate_el = self._gate_el_done
            _prev_has_final = bool(self._has_final)

            # Progressive staged flow (Option B):
            # - Each subrun runs only that stage.
            # - It must reuse prior results via prior_result (merged caches).
            prior_result = self.meta_results_v2 if subrun in ("IH", "EL", "IL") else None


            # Backward-compatible reuse hints (only used if engine ignores prior_result)
            reuse_from_stage = None
            initial_ids = None

            if subrun == "IH":
                if not prior_result:
                    raise RuntimeError("Staged flow requires E/H to be run before I/H.")
                if self._eh_survivor_ids:
                    reuse_from_stage = "EH"
                    initial_ids = list(self._eh_survivor_ids)
                self.log(f"[I/H] Using prior E/H results ({len(self._eh_survivor_ids)} survivor(s)).\n")

            elif subrun == "EL":
                if not prior_result:
                    raise RuntimeError("Staged flow requires I/H to be run before E/L.")
                if self._ih_survivor_ids:
                    reuse_from_stage = "IH"
                    initial_ids = list(self._ih_survivor_ids)
                self.log(f"[E/L] Using prior I/H results ({len(self._ih_survivor_ids)} survivor(s)).\n")

            elif subrun == "IL":
                if not prior_result:
                    raise RuntimeError("Staged flow requires E/L to be run before I/L.")
                if not self._el_survivor_ids:
                    raise RuntimeError("Staged flow requires E/L to be run before I/L.")
                reuse_from_stage = "EL"
                initial_ids = list(self._el_survivor_ids)
                self.log(f"[I/L] Using prior E/L results ({len(self._el_survivor_ids)} survivor(s)).\n")

            kwargs = dict(
                A=self.A,
                criteria=self.criteria_rows,
                prior_result=prior_result,
                pass_thr=pass_thr,
                border_thr=border_thr,
                missing_policy=missing_policy,
                llm_model=model,
                llm_trunc_chars=llm_trunc,
                llm_batch_size=llm_batch,
                stage_h_include_mode=h_mode,
                stage_l_include_mode=l_mode,
                randomize_within_blocks=randomize,
                random_seed=seed,
                log=self.log,
                hard_stop=hard_stop,
                progress=self._emit_progress,
                cancel_token=self._cancel_token,
                subrun=subrun,
                reuse_from_stage=reuse_from_stage,
                initial_a_ids=initial_ids,
            )

            # The engine in your codebase expects positional (A, criteria) in older plugin,
            # but we call with keyword args to allow flexible signatures.
            # If your engine is positional-only, wrap it accordingly in metadata.py.
            res = self._call_engine_flex(**kwargs)

            # Handle cancellation
            if self._cancel_token and self._cancel_token.cancelled:
                # Discard this run; keep previous staged results intact
                self.meta_results_v2 = _prev_meta_results_v2
                self.final_rows = _prev_final_rows
                self.stage_rows = _prev_stage_rows
                self._eh_survivor_ids = _prev_eh_surv
                self._ih_survivor_ids = _prev_ih_surv
                self._el_survivor_ids = _prev_el_surv
                self._gate_eh_done = _prev_gate_eh
                self._gate_ih_done = _prev_gate_ih
                self._gate_el_done = _prev_gate_el
                self._has_final = _prev_has_final
                self._run_error = None
                return

            if not isinstance(res, dict):
                raise RuntimeError("Engine returned unexpected result type (expected dict).")

            # Merge caches across staged calls so earlier stage rows don't disappear.
            prev = self.meta_results_v2 if isinstance(self.meta_results_v2, dict) else {}
            prev_caches = (prev.get("caches") or {}) if isinstance(prev, dict) else {}
            new_caches = res.get("caches") or {}

            def _merge_cache(prev_cache: Any, new_cache: Any) -> Any:
                if not isinstance(prev_cache, dict):
                    return new_cache
                if not isinstance(new_cache, dict):
                    return prev_cache
                merged = dict(prev_cache)
                for k, v in new_cache.items():
                    # If new rows are empty placeholders, keep previously computed rows.
                    if (
                        k == "rows"
                        and isinstance(v, list) and len(v) == 0
                        and isinstance(prev_cache.get("rows"), list) and len(prev_cache.get("rows")) > 0
                    ):
                        continue
                    merged[k] = v
                return merged

            merged_caches: Dict[str, Any] = {}
            for sk in ("EH", "IH", "EL", "IL", "FINAL", "meta"):
                merged_caches[sk] = _merge_cache(prev_caches.get(sk), new_caches.get(sk))

            # Keep any extra cache keys that might appear later
            for k, v in new_caches.items():
                if k not in merged_caches:
                    merged_caches[k] = v

            # Invalidate downstream stages if an earlier stage is rerun (staged flow coherence)
            if subrun == "EH":
                for k in ("IH", "EL", "IL", "FINAL"):
                    merged_caches.pop(k, None)
                self.stage_rows["IH"] = []
                self.stage_rows["EL"] = []
                self.stage_rows["IL"] = []
                self._ih_survivor_ids = []
                self._el_survivor_ids = []
                self._has_final = False

            elif subrun == "IH":
                for k in ("EL", "IL", "FINAL"):
                    merged_caches.pop(k, None)
                self.stage_rows["EL"] = []
                self.stage_rows["IL"] = []
                self._el_survivor_ids = []
                self._has_final = False

            elif subrun == "EL":
                for k in ("IL", "FINAL"):
                    merged_caches.pop(k, None)
                self.stage_rows["IL"] = []
                self._has_final = False

            # FINAL exists only after I/L has run successfully
            if subrun != "IL":
                merged_caches.pop("FINAL", None)
                res["final_results"] = []
                self._has_final = False
            else:
                self._has_final = True

            res["caches"] = merged_caches
            self.meta_results_v2 = res

            # Stage rows for UI
            caches = merged_caches
            for sk in ("EH", "IH", "EL", "IL"):
                cache = caches.get(sk) or {}
                rows = cache.get("rows") or []
                if isinstance(rows, list):
                    # Always overwrite the stage we just ran; keep others unless they contain real rows.
                    if sk == subrun or rows:
                        self.stage_rows[sk] = rows

            # Survivor caches (update only when the stage actually ran)
            try:
                if subrun == "EH":
                    self._eh_survivor_ids = [str(x) for x in ((caches.get("EH") or {}).get("survivor_ids") or [])]
                elif subrun == "IH":
                    self._ih_survivor_ids = [str(x) for x in ((caches.get("IH") or {}).get("survivor_ids") or [])]
                elif subrun == "EL":
                    self._el_survivor_ids = [str(x) for x in ((caches.get("EL") or {}).get("survivor_ids") or [])]
            except Exception:
                pass

            # Final aggregated decisions (only meaningful after I/L)
            if self._has_final:
                self.final_rows = aggregate_decisions(self.meta_results_v2, self.A, pass_thr=pass_thr, border_thr=border_thr) or []
            else:
                self.final_rows = []

            # Update gating flags from successful result (and reset downstream gates when rerunning earlier stages)
            if subrun == "EH":
                self._gate_eh_done = True
                self._gate_ih_done = False
                self._gate_el_done = False
            elif subrun == "IH":
                self._gate_eh_done = True
                self._gate_ih_done = True
                self._gate_el_done = False
            elif subrun == "EL":
                self._gate_eh_done = True
                self._gate_ih_done = True
                self._gate_el_done = True
            elif subrun == "IL":
                self._gate_eh_done = True
                self._gate_ih_done = True
                self._gate_el_done = True

        except Exception as e:
            self._run_error = str(e)
            # Keep previous staged results intact on error
            self.meta_results_v2 = _prev_meta_results_v2
            self.final_rows = _prev_final_rows
            self.stage_rows = _prev_stage_rows
            self._eh_survivor_ids = _prev_eh_surv
            self._ih_survivor_ids = _prev_ih_surv
            self._el_survivor_ids = _prev_el_surv
            self._gate_eh_done = _prev_gate_eh
            self._gate_ih_done = _prev_gate_ih
            self._gate_el_done = _prev_gate_el
            self._has_final = _prev_has_final

        finally:
            self._run_finished = True

    # ----------------------------
    # Modal: progress + ETA
    # ----------------------------

    def _open_progress_modal(self, run_params: Dict[str, Any], subrun: str) -> None:
        parent = self._parent_toplevel()
        win = tk.Toplevel(parent)
        self._modal = win

        win.title(f"Screening - {subrun}")
        win.transient(parent)
        win.grab_set()
        win.attributes("-topmost", True)

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text=f"Screening: {subrun}", font=("TkDefaultFont", 12, "bold"))\
            .pack(anchor="w", pady=(0, 8))

        # H block
        h_blk = ttk.Frame(frm)
        h_blk.pack(fill="x", pady=(4, 6))
        ttk.Label(h_blk, text="Stage H (heuristics)").pack(anchor="w")
        h_label = ttk.Label(h_blk, text="0/0 (waiting)")
        h_label.pack(anchor="w")
        h_prog = ttk.Progressbar(h_blk, mode="indeterminate", maximum=100)
        h_prog.pack(fill="x", padx=(0, 4), pady=(4, 0))
        h_prog.start(30)

        # L block
        l_blk = ttk.Frame(frm)
        l_blk.pack(fill="x", pady=(6, 6))
        ttk.Label(l_blk, text="Stage L (LLM)").pack(anchor="w")
        l_label = ttk.Label(l_blk, text="0/0 batches (waiting)")
        l_label.pack(anchor="w")
        l_prog = ttk.Progressbar(l_blk, mode="indeterminate", maximum=100)
        l_prog.pack(fill="x", padx=(0, 4), pady=(4, 0))
        l_prog.start(50)

        step = ttk.Label(frm, text="Step: -", foreground="#444444")
        step.pack(anchor="w", pady=(6, 0))

        sub = ttk.Label(frm, text="Status: running...", foreground="#555555")
        sub.pack(anchor="w", pady=(2, 0))

        elapsed = ttk.Label(frm, text="Elapsed: 00:00:00   ETA: -", foreground="#666666")
        elapsed.pack(anchor="w", pady=(2, 0))

        params = ttk.Label(
            frm,
            text=f"Model: {run_params['model']}  |  batch={run_params['llm_batch']}  |  trunc={run_params['llm_trunc']}",
            foreground="#666666",
        )
        params.pack(anchor="w", pady=(2, 0))

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(10, 0))

        cancel_btn = ttk.Button(btns, text="Cancel", command=self._on_cancel_click)
        ok_btn = ttk.Button(btns, text="OK", command=self._on_modal_ok)
        ok_btn.configure(state="disabled")

        cancel_btn.pack(side="right")
        ok_btn.pack(side="right", padx=(0, 8))

        self._modal_widgets = {
            "h_label": h_label, "h_prog": h_prog,
            "l_label": l_label, "l_prog": l_prog,
            "step": step,
            "sub": sub,
            "elapsed": elapsed,
            "ok_btn": ok_btn,
            "cancel_btn": cancel_btn,
        }

        win.geometry("620x350+120+120")

        def _on_close():
            if not self._run_finished:
                return
            self._on_modal_ok()

        win.protocol("WM_DELETE_WINDOW", _on_close)

    def _on_cancel_click(self) -> None:
        if self._modal_widgets:
            btn = self._modal_widgets.get("cancel_btn")
            sub = self._modal_widgets.get("sub")
            if btn:
                btn.configure(text="Cancelling...", state="disabled")
            if sub:
                sub.configure(text="Status: cancelling (will discard results)...")
            step = self._modal_widgets.get("step")
            if step:
                try:
                    step.configure(text="Step: - (cancelling)")
                except Exception:
                    pass
        if self._cancel_token:
            self._cancel_token.cancelled = True

    def _on_modal_ok(self) -> None:
        if self._modal:
            try:
                self._modal.grab_release()
            except Exception:
                pass
            try:
                self._modal.destroy()
            except Exception:
                pass
            self._modal = None
            self._modal_widgets = {}

        self._set_controls_state(enabled=True)
        self._update_stage_buttons()

    def _set_controls_state(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        container = self._frame or self._root
        if not container:
            return
        try:
            for w in container.winfo_children():
                self._toggle_state_recursive(w, state)
        except Exception:
            pass

    def _toggle_state_recursive(self, widget: tk.Widget, state: str) -> None:
        # Keep the modal buttons interactive
        if self._modal and str(widget) == str(self._modal):
            return
        if isinstance(widget, (ttk.Entry, ttk.Combobox, ttk.Button, ttk.Checkbutton, getattr(ttk, "Spinbox", tk.Spinbox))):  # type: ignore
            try:
                widget.configure(state=state)
            except Exception:
                pass
        try:
            for ch in widget.winfo_children():
                self._toggle_state_recursive(ch, state)
        except Exception:
            pass

    def _poll_modal_updates(self) -> None:
        if not self._modal:
            return

        # Drain UI queue events
        if self._ui_q is not None:
            try:
                while True:
                    ev: _UiEvent = self._ui_q.get_nowait()
                    if ev.kind == "log":
                        self._append_log(ev.payload.get("msg", ""))
                    elif ev.kind == "progress":
                        self._handle_progress_event(ev.payload)
            except queue.Empty:
                pass

        # Update elapsed/ETA even if no events
        self._update_eta(self._units_done, self._units_total)

        if self._run_finished:
            # Stop spinners if still indeterminate
            try:
                hpb: ttk.Progressbar = self._modal_widgets.get("h_prog")  # type: ignore
                lpb: ttk.Progressbar = self._modal_widgets.get("l_prog")  # type: ignore
                if hpb and str(hpb.cget("mode")) == "indeterminate":
                    hpb.stop()
                if lpb and str(lpb.cget("mode")) == "indeterminate":
                    lpb.stop()
            except Exception:
                pass

            sub: ttk.Label = self._modal_widgets.get("sub")  # type: ignore
            ok_btn: ttk.Button = self._modal_widgets.get("ok_btn")  # type: ignore
            cancel_btn: ttk.Button = self._modal_widgets.get("cancel_btn")  # type: ignore

            # Error?
            if self._run_error:
                if sub:
                    sub.configure(text=f"Status: error - {self._run_error}")
                if cancel_btn:
                    cancel_btn.configure(state="disabled")
                if ok_btn:
                    ok_btn.configure(state="normal")
                return

            # Cancelled?
            if self._cancel_token and self._cancel_token.cancelled:
                if sub:
                    sub.configure(text="Status: cancelled - no changes saved")
                if cancel_btn:
                    cancel_btn.configure(state="disabled")
                if ok_btn:
                    ok_btn.configure(state="normal")
                return

            # Success: refresh tabs + counts
            self._render_stage_tabs()
            self._render_final_tab()

            if sub:
                sub.configure(text="Status: finished")
            if cancel_btn:
                cancel_btn.configure(state="disabled")
            if ok_btn:
                ok_btn.configure(state="normal")
            return

        # keep polling
        if self._modal:
            self._modal.after(120, self._poll_modal_updates)

    def _set_progressbar_determinate(self, pb: ttk.Progressbar, maximum: int) -> None:
        try:
            if str(pb.cget("mode")) != "determinate":
                pb.stop()
                pb.configure(mode="determinate")
            pb.configure(maximum=max(1, int(maximum)))
        except Exception:
            pass

    def _handle_progress_event(self, evt: Dict[str, Any]) -> None:
        if not self._modal_widgets:
            return

        kind = evt.get("kind")
        h_label: ttk.Label = self._modal_widgets["h_label"]  # type: ignore
        h_prog: ttk.Progressbar = self._modal_widgets["h_prog"]  # type: ignore
        l_label: ttk.Label = self._modal_widgets["l_label"]  # type: ignore
        l_prog: ttk.Progressbar = self._modal_widgets["l_prog"]  # type: ignore
        step: ttk.Label = self._modal_widgets["step"]  # type: ignore

        # Stage H (per criterion)
        if kind == "h_criterion_start":
            self._h_total = max(self._h_total, int(evt.get("crit_total") or 0))
            self._set_progressbar_determinate(h_prog, maximum=max(1, self._h_total))
            cur_idx = int(evt.get("crit_idx") or 1)
            h_prog["value"] = max(0, cur_idx - 1)

            label = evt.get("label") or evt.get("crit_id") or ""
            operator = evt.get("operator") or ""
            target = evt.get("target") or ""
            h_label.configure(text=f"Criterion {cur_idx}/{self._h_total} - {label} | {operator} ({target})")
            step.configure(text=f"Step: H - {evt.get('crit_id') or cur_idx} (start)")

            self._units_total = self._h_total + max(self._l_total, 0)
            self._update_eta(self._h_done + self._l_done, self._units_total)

        elif kind == "h_criterion_done":
            cur_idx = int(evt.get("crit_idx") or 1)
            self._h_done = max(self._h_done, cur_idx)
            self._set_progressbar_determinate(h_prog, maximum=max(1, self._h_total))
            h_prog["value"] = self._h_done
            step.configure(text=f"Step: H - {evt.get('crit_id') or cur_idx} (done)")
            self._update_eta(self._h_done + self._l_done, self._h_total + self._l_total)

        elif kind == "h_stage_skipped":
            self._h_total = 0
            self._h_done = 0
            self._set_progressbar_determinate(h_prog, maximum=1)
            h_prog["value"] = 1
            try:
                h_prog.stop()
            except Exception:
                pass
            h_label.configure(text="H: skipped (reused from previous stages)")
            step.configure(text="Step: H - skipped (reused)")
            self._update_eta(self._h_done + self._l_done, self._h_total + self._l_total)

        # Stage L (per batch)
        elif kind == "l_criterion_start":
            batches_total = int(evt.get("batches_total") or 0)
            self._l_total += batches_total
            self._set_progressbar_determinate(l_prog, maximum=max(1, self._l_total))
            l_label.configure(text=f"Criterion {evt.get('crit_idx')}/{evt.get('crit_total')} - 0/{batches_total} batches...")
            step.configure(text=f"Step: L - {evt.get('crit_id') or evt.get('crit_idx')} (batching)")
            self._update_eta(self._h_done + self._l_done, self._h_total + self._l_total)

        elif kind == "l_batch":
            substate = (evt.get("sub") or "")
            bi = int(evt.get("batch_idx") or 0)
            bt = int(evt.get("batch_total") or 0)

            l_label.configure(text=f"Batch {bi}/{bt} - {substate}  (total {self._l_done}/{self._l_total})")
            step.configure(text=f"Step: L - batch {bi}/{bt} ({substate})")

            if substate == "batch_done":
                self._l_done += 1
                self._set_progressbar_determinate(l_prog, maximum=max(1, self._l_total))
                l_prog["value"] = self._l_done
                step.configure(text=f"Step: L - batch {bi}/{bt} (done)")
                self._update_eta(self._h_done + self._l_done, self._h_total + self._l_total)

        elif kind == "l_batch_retry":
            note = evt.get("note") or ""
            sub_lbl: ttk.Label = self._modal_widgets.get("sub")  # type: ignore
            if sub_lbl:
                sub_lbl.configure(text=f"Status: {note}")

    def _update_eta(self, done: int, total: int) -> None:
        self._units_done = max(int(done or 0), 0)
        self._units_total = max(int(total or 0), 0)

        now = time.time()
        elapsed = max(1e-6, now - self._run_started_ts)

        def fmt_hms(s: float) -> str:
            s = int(max(0, s))
            h = s // 3600
            m = (s % 3600) // 60
            sec = s % 60
            return f"{h:02d}:{m:02d}:{sec:02d}"

        if self._modal_widgets:
            elapsed_lbl: ttk.Label = self._modal_widgets.get("elapsed")  # type: ignore
            elapsed_lbl.configure(text=f"Elapsed: {fmt_hms(elapsed)}   ETA: -")

        if self._units_total <= 0:
            return

        inst_rate = self._units_done / elapsed
        if inst_rate <= 0:
            return

        if self._ema_rate is None:
            self._ema_rate = inst_rate
        else:
            self._ema_rate = self._ema_alpha * inst_rate + (1 - self._ema_alpha) * self._ema_rate
        self._eta_samples += 1

        if self._modal_widgets and self._eta_samples >= 3 and self._ema_rate and self._ema_rate > 0:
            remaining = max(0.0, self._units_total - self._units_done)
            eta_seconds = remaining / self._ema_rate
            elapsed_lbl: ttk.Label = self._modal_widgets.get("elapsed")  # type: ignore
            if elapsed_lbl:
                elapsed_lbl.configure(text=f"Elapsed: {fmt_hms(elapsed)}   ETA: ~{fmt_hms(eta_seconds)}")

    # ----------------------------
    # Render results
    # ----------------------------

    def _render_stage_tabs(self) -> None:
        # Stage EH/IH/EL/IL tabs
        mapping = {
            "EH": self.tv_eh,
            "IH": self.tv_ih,
            "EL": self.tv_el,
            "IL": self.tv_il,
        }
        for sk, tv in mapping.items():
            if not tv:
                continue
            tv.delete(*tv.get_children())
            rows = self.stage_rows.get(sk) or []
            for r in rows:
                stage_out = str(r.get("stage_outcome") or "")
                tag = "out" if stage_out.upper() == "OUT" else "in"
                tv.insert("", tk.END, values=(
                    sk,
                    r.get("a_id"),
                    r.get("stage_outcome"),
                    r.get("passed_to_next"),
                    r.get("hard_stop"),
                    r.get("hard_stop_criterion_id"),
                    r.get("hard_stop_criterion_label"),
                    self._safe_str(
                        r.get("stage_reason_summary") or r.get("reasons_summary") or r.get("reasons") or r.get("why") or ""
                    ),
                ), tags=(tag,))

    def _render_final_tab(self) -> None:
        if not self.tv_final:
            return
        self.tv_final.delete(*self.tv_final.get_children())

        if not getattr(self, "_has_final", False):
            if self.lbl_counts:
                self.lbl_counts.configure(text="Counts: (run I/L to compute final decisions)")
            self._update_stage_buttons()
            return

        for r in self.final_rows or []:
            self.tv_final.insert("", tk.END, values=tuple(r.get(c) for c in self.FINAL_COLS))

        # counts label
        try:
            counts = prisma_counts(self.final_rows or [])
            if self.lbl_counts:
                self.lbl_counts.configure(
                    text=f"Counts: PASS_CLEAN={counts.get('PASS_CLEAN', 0)} | REVIEW={counts.get('REVIEW', 0)} | OUT={counts.get('OUT', 0)} | TOTAL={counts.get('TOTAL', 0)}"
                )
            self.log(
                f"[RUN] Done. PASS_CLEAN={counts.get('PASS_CLEAN', 0)}, REVIEW={counts.get('REVIEW', 0)}, OUT={counts.get('OUT', 0)}, TOTAL={counts.get('TOTAL', 0)}\n"
            )
        except Exception:
            pass

        self._update_stage_buttons()

    # ----------------------------
    # Gating helpers
    # ----------------------------

    def _reset_gated_flow(self, log_line: bool = True) -> None:
        self.meta_results_v2 = None
        self.final_rows = []
        self.stage_rows = {k: [] for k in ("EH", "IH", "EL", "IL")}
        self._eh_survivor_ids = []
        self._ih_survivor_ids = []
        self._el_survivor_ids = []
        self._has_final = False

        self._gate_eh_done = False
        self._gate_ih_done = False
        self._gate_el_done = False

        # Clear tabs
        for tv in (self.tv_eh, self.tv_ih, self.tv_el, self.tv_il, self.tv_final):
            if tv:
                tv.delete(*tv.get_children())

        if self.lbl_counts:
            self.lbl_counts.configure(text="Counts: -")

        self._update_stage_buttons()
        if log_line:
            self.log("[RUN] Staged flow reset.\n")

    def _update_stage_buttons(self) -> None:
        # Buttons may not exist yet in early init
        btn_eh = getattr(self, "btn_eh", None)
        btn_ih = getattr(self, "btn_ih", None)
        btn_el = getattr(self, "btn_el", None)
        btn_il = getattr(self, "btn_il", None)

        # Enable logic also depends on having inputs loaded
        base_ok = bool(self.criteria_rows) and bool(self.A)

        if btn_eh:
            btn_eh.configure(state="normal" if base_ok else "disabled")
        if btn_ih:
            btn_ih.configure(state="normal" if (base_ok and self._gate_eh_done) else "disabled")
        if btn_el:
            btn_el.configure(state="normal" if (base_ok and self._gate_eh_done and self._gate_ih_done) else "disabled")
        if btn_il:
            btn_il.configure(state="normal" if (base_ok and self._gate_eh_done and self._gate_ih_done and self._gate_el_done) else "disabled")

    # ----------------------------
    # Export
    # ----------------------------

    def on_export_decisions_csv(self) -> None:
        if not self.meta_results_v2 or not getattr(self, "_has_final", False):
            messagebox.showwarning("Export", "No final decisions to export. Run I/L first.")
            return

        path = filedialog.asksaveasfilename(
            title="Save Decisions CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")]
        )
        if not path:
            return
        export_decisions_csv(path, self.meta_results_v2)
        self.log(f"[EXPORT] Decisions -> {os.path.basename(path)}\n")

    def on_export_decisions_xlsx(self) -> None:
        if not self.meta_results_v2 or not getattr(self, "_has_final", False):
            messagebox.showwarning("Export", "No final decisions to export. Run I/L first.")
            return

        path = filedialog.asksaveasfilename(
            title="Save Decisions XLSX",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")]
        )
        if not path:
            return
        try:
            export_decisions_xlsx(path, self.meta_results_v2)
            self.log(f"[EXPORT] Decisions -> {os.path.basename(path)}\n")
        except Exception as e:
            messagebox.showerror("XLSX Export", str(e))

    def on_export_audit_csv(self) -> None:
        if not self.meta_results_v2:
            messagebox.showwarning("Export", "No audit to export. Run screening first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save Metadata Audit CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")]
        )
        if not path:
            return
        export_metadata_audit_csv(path, self.meta_results_v2, self.A)
        self.log(f"[EXPORT] Audit -> {os.path.basename(path)}\n")

    def on_export_audit_xlsx(self) -> None:
        if not self.meta_results_v2:
            messagebox.showwarning("Export", "No audit to export. Run screening first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save Metadata Audit XLSX",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")]
        )
        if not path:
            return
        try:
            export_metadata_audit_xlsx(path, self.meta_results_v2, self.A)
            self.log(f"[EXPORT] Audit -> {os.path.basename(path)}\n")
        except Exception as e:
            messagebox.showerror("XLSX Export", str(e))

    def on_save_charts(self) -> None:
        if not self.meta_results_v2:
            messagebox.showwarning("Charts", "No results. Run screening first.")
            return
        outdir = filedialog.askdirectory(title="Select output folder for charts")
        if not outdir:
            return
        paths = save_metadata_charts(outdir, self.meta_results_v2)
        if not paths:
            messagebox.showinfo("Charts", "matplotlib not available (or no charts produced).")
            return
        self.log("[CHARTS] Saved:\n  - " + "\n  - ".join(f"{k}: {v}" for k, v in paths.items()) + "\n")


# ----------------------------
# Factory (Hub import point)
# ----------------------------

def create_plugin(app=None, *args, **kwargs):
    return MetadataTabPlugin(app)


# ----------------------------
# Standalone runner (optional)
# ----------------------------

def _standalone():
    root = tk.Tk()
    root.title("Screen A - Metadata-only (standalone)")
    root.geometry("1260x760")
    nb = ttk.Notebook(root)
    nb.pack(fill=tk.BOTH, expand=True)

    plugin = MetadataTabPlugin()
    plugin._root = root  # type: ignore[attr-defined]
    frame = plugin.build_tab(nb)
    nb.add(frame, text=plugin.meta.title)

    root.mainloop()


if __name__ == "__main__":
    _standalone()
