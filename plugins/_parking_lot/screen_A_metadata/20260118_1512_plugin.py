# -*- coding: utf-8 -*-
"""
plugin.py â€” metadata-only Screen A as a Notebook tab plugin
(With modal, threaded run, progress wiring, real cancel, and ETA)
"""

TAB_TITLE = "Screen A — Metadata"

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Any, Dict, List, Optional, Tuple, Callable
import os
import platform
import threading
import queue
import time

# Hub plugin base/meta
from prisma_hub.plugin_api import BasePlugin, PluginMeta  # type: ignore

# Shared constants (for dropdowns)
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


# ---------- small helper for true cancellation ----------
class _CancelToken:
    def __init__(self):
        self.cancelled = False


class MetadataTabPlugin(BasePlugin):
    """Implements the hub's plugin contract."""

    CRIT_COLS: Tuple[str, ...] = ("enabled", "type","scope","label","operator","target","what","how","weight","threshold")

    # Engine (Final) columns: left-anchored, stable order
    ENGINE_COLS: Tuple[str, ...] = (
        "a_id","title","score","label",
        "lang","doc_type","year","venue",
        "h_pass","l_pass","random_seed_used",
        "pass_thr","border_thr",
        "hard_stop_triggered","hard_stop_criterion_id","hard_stop_criterion_label"
    )

    # Dynamic: after loading A, we compute BIBLIO_COLS (ALL A fields minus any duplicates in ENGINE_COLS)
    BIBLIO_COLS: Tuple[str, ...] = tuple()   # filled after A is loaded
    ALL_COLS:    Tuple[str, ...] = ENGINE_COLS  # = ENGINE_COLS + BIBLIO_COLS (after A)

    # Substage tables adopt the exact same column model as Final (uniform UX)
    EH_COLS: Tuple[str, ...] = ALL_COLS
    IH_COLS: Tuple[str, ...] = ALL_COLS
    EL_COLS: Tuple[str, ...] = ALL_COLS
    RES_COLS: Tuple[str, ...] = ALL_COLS

    def __init__(self, app=None):
        super().__init__(app, PluginMeta(
            id="screen_A_metadata",
            title="Screen A â€” Metadata",
            version="1.0.0",   # unified modal header/step line; clean-foundation runner
        ))

        # State
        self.criteria_rows: List[Dict[str, Any]] = []
        self.A: List[Dict[str, Any]] = []
        self.meta_results: List[Dict[str, Any]] = []
        self.final_rows: List[Dict[str, Any]] = []

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
        # Substage rendering mode (Option B): show all items on E/H, I/H, E/L
        self.var_allview: Optional[tk.BooleanVar] = None

        # UI handles
        self.tv_crit: Optional[ttk.Treeview] = None
        self.txt_log: Optional[tk.Text] = None

        # Global column manager (applies to EH/IH/EL/RES)
        self.visible_cols: Optional[List[str]] = None  # None => show ALL_COLS
        self._column_presets: Dict[str, List[str]] = {}  # optional future use

        # Sorting state per-Treeview: {tv: [("col", asc_bool), ("col2", asc_bool)]}
        self._sort_state: Dict[ttk.Treeview, List[Tuple[str, bool]]] = {}

        # Tooltip for abstract-on-hover
        self._tooltip: Optional[tk.Toplevel] = None
        self._tooltip_label: Optional[tk.Label] = None
        self._tooltip_active_tv: Optional[ttk.Treeview] = None

        # Fast A lookup by a_id
        self._A_index: Dict[str, Dict[str, Any]] = {}

        # Active cell editor overlay
        self._editor: Optional[tk.Widget] = None
        self._editor_info: Optional[Tuple[str, str]] = None

        # Substage Treeviews
        self.tv_eh: Optional[ttk.Treeview] = None
        self.tv_ih: Optional[ttk.Treeview] = None
        self.tv_el: Optional[ttk.Treeview] = None
        self.tv_res: Optional[ttk.Treeview] = None  # final I/L

        # Stage caches (from engine)
        self.stage_caches: Dict[str, Any] = {}
        # cache of E/L survivors to reuse in I/L (skip replaying E/L)
        self._el_survivor_ids: List[str] = []

        # Gating flags
        self._gate_eh_done = False
        self._gate_ih_done = False
        self._gate_el_done = False

        # Context menu
        self._menu: Optional[tk.Menu] = None

        # --- Run state (modal/thread) ---
        # Keep a handle to our tab frame and (optionally) a root
        self._frame: Optional[ttk.Frame] = None
        self._root: Optional[tk.Misc] = None  # may be injected by host/standalone
        
        # Run state (modal/thread) ---
        self._subrun_mode: Optional[str] = None  # EH | IH | EL | IL (for headers/log prefixes)
        self._run_thread: Optional[threading.Thread] = None
        self._progress_q: Optional[queue.Queue] = None
        self._modal: Optional[tk.Toplevel] = None
        self._modal_widgets: Dict[str, Any] = {}
        self._run_started_ts: float = 0.0
        self._run_finished: bool = False
        self._results_buffer: Optional[List[Dict[str, Any]]] = None
        self._aggregated_buffer: Optional[List[Dict[str, Any]]] = None

        # Cancel token shared with engine
        self._cancel_token: Optional[_CancelToken] = None

        # ETA (EMA) state
        self._eta_samples = 0
        self._ema_rate = None  # items-per-second equivalent â€œunitâ€
        self._ema_alpha = 0.3
        self._progress_units_done = 0
        self._progress_units_total = 0

        # Stage progress book-keeping
        self._h_total = 0
        self._h_done = 0
        self._l_batches_total = 0
        self._l_batches_done = 0

    # ------------- Hub entry points -------------

    def build_tab(self, notebook: ttk.Notebook) -> ttk.Frame:
        root = ttk.Frame(notebook)
        self._frame = root
        # store a safe parent (works in hub and standalone)
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
    
    # ------------- UI actions -------------
    def on_load_criteria_text(self):
        win = tk.Toplevel()
        win.title("Paste Criteria (IC/EC lines)")
        txt = tk.Text(win, width=80, height=18)
        txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
    
        def accept():
            raw = txt.get("1.0", tk.END)
            rows = harmonize_from_text(raw)
            for r in rows:
                if "enabled" not in r:
                    r["enabled"] = True
            self.criteria_rows = rows
            self._refresh_criteria_table()
            self.log(f"[CRITERIA] Parsed {len(rows)} row(s) from text.\n")
            win.destroy()
    
        ttk.Button(win, text="Use these", command=accept).pack(pady=8)
    
    def _preserve_enabled_and_replace(self, new_rows: List[Dict[str, Any]]):
        prev = {str(r.get("id")): bool(r.get("enabled", True))
                for r in self.criteria_rows if r.get("id") is not None}
        out: List[Dict[str, Any]] = []
        for r in new_rows:
            rid = str(r.get("id"))
            r2 = dict(r)
            r2["enabled"] = prev.get(rid, bool(r.get("enabled", True)) if "enabled" in r else True)
            out.append(r2)
        self.criteria_rows = out
    
    def _selected_criteria_indices(self) -> List[int]:
        """Return sorted indices of selected rows in the Criteria table."""
        if not self.tv_crit:
            return []
        sel = list(self.tv_crit.selection())
        try:
            return sorted({int(i) for i in sel})
        except Exception:
            return []
    
    def _merge_llm_reformulated_rows(self, llm_rows: List[Dict[str, Any]]):
        """
        Merge LLM-returned rows into self.criteria_rows by 'id', preserving the
        existing 'enabled' flag for each row. Unmentioned rows remain unchanged.
        """
        by_id = {str(r.get("id")): dict(r) for r in (llm_rows or []) if r.get("id")}
        if not by_id:
            return
        out: List[Dict[str, Any]] = []
        for r in self.criteria_rows:
            rid = str(r.get("id") or "")
            if rid and rid in by_id:
                nr = by_id[rid]
                nr["enabled"] = r.get("enabled", True)  # preserve enabled
                out.append(nr)
            else:
                out.append(r)
        self.criteria_rows = out

    def on_load_criteria_file(self):
        path = filedialog.askopenfilename(
            title="Open Criteria CSV/XLSX",
            filetypes=[("CSV","*.csv"),("Excel","*.xlsx *.xls"),("All","*.*")]
        )
        if not path:
            return
        rows = parse_criteria_rows(path)
        rows = harmonize_from_rows(rows)
        for r in rows:
            if "enabled" not in r:
                r["enabled"] = True
        self.criteria_rows = rows
        self._refresh_criteria_table()
        self.log(f"[CRITERIA] Loaded {len(rows)} row(s) from {os.path.basename(path)}.\n")
        self._reset_gated_flow()
    
    def on_harmonize(self):
        if not self.criteria_rows:
            messagebox.showwarning("Harmonize", "Load/paste criteria first.")
            return
        rows = harmonize_from_rows(self.criteria_rows)
        self._preserve_enabled_and_replace(rows)
        self._refresh_criteria_table()
        self.log("[CRITERIA] Harmonized deterministically.\n")
        # Criteria changed â†’ reset staged flow
        self._reset_gated_flow()
    
    def on_harmonize_llm(self):
        if not self.criteria_rows:
            messagebox.showwarning("LLM Reformulate", "Load/paste criteria first.")
            return
    
        # Pick rows: if some are selected in the Criteria table â†’ only those.
        # Otherwise, reformulate all *enabled* rows. If none enabled, fall back to all.
        idxs = self._selected_criteria_indices() if hasattr(self, "_selected_criteria_indices") else []
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
        self.log(f"[CRITERIA] LLM reformulation on {scope_msg} using model={model}â€¦\n")
    
        try:
            llm_rows = reformulate_with_llm(target_rows, model=model, log=self.log)
        except Exception as e:
            messagebox.showerror("LLM Reformulate", str(e))
            return
    
        # Merge LLM-updated rows back in place, preserving each row's 'enabled' flag
        self._merge_llm_reformulated_rows(llm_rows)
        self._refresh_criteria_table()
        self.log(f"[CRITERIA] Reformulated via LLM ({model}): updated {len(llm_rows)} row(s).\n")
    
        # Criteria changed â†’ reset staged flow
        self._reset_gated_flow()
    
    def on_load_A(self):
        path = filedialog.askopenfilename(
            title="Open A CSV/XLSX",
            filetypes=[("CSV","*.csv"),("Excel","*.xlsx *.xls"),("All","*.*")]
        )
        if not path:
            return
        self.A = parse_A_csv_xlsx(path)
        basename = os.path.basename(path)
        count = len(self.A)
        if self.var_A_info is not None:
            self.var_A_info.set(f"{basename} â€” {count} item(s)")
        self.log(f"[A] Loaded {count} items from {basename}.\n")

        # Build A index for fast lookup
        self._A_index = {str(d.get("a_id")): d for d in self.A if isinstance(d, dict) and d.get("a_id") is not None}

        # Recompute biblio column list and rebuild all result tables (EH/IH/EL/RES)
        self._compute_all_columns()
        self._rebuild_table_columns()

        # Reset staged flow on data change
        self._reset_gated_flow()

    # ------------- UI construction -------------

    def _build_ui(self, container: tk.Widget):
        pan = ttk.Panedwindow(container, orient=tk.HORIZONTAL)
        pan.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(pan); right = ttk.Frame(pan)
        pan.add(left, weight=1); pan.add(right, weight=2)

        # LEFT: Controls
        lf = ttk.LabelFrame(left, text="Controls")
        lf.pack(side=tk.TOP, fill=tk.X, padx=8, pady=8)

        row = 0
        ttk.Button(lf, text="Load Criteria (Text)", command=self.on_load_criteria_text).grid(row=row, column=0, sticky="we", padx=4, pady=3)
        ttk.Button(lf, text="Load Criteria (CSV/XLSX)", command=self.on_load_criteria_file).grid(row=row, column=1, sticky="we", padx=4, pady=3)
        row += 1
        ttk.Button(lf, text="Harmonize (deterministic)", command=self.on_harmonize).grid(row=row, column=0, sticky="we", padx=4, pady=3)
        ttk.Button(lf, text="Reformulate (LLM) â€” selâ†’only, else enabled", command=self.on_harmonize_llm).grid(row=row, column=1, sticky="we", padx=4, pady=3)
        row += 1
        ttk.Button(lf, text="Load A (CSV/XLSX)", command=self.on_load_A).grid(row=row, column=0, sticky="we", padx=4, pady=8)
        self.var_A_info = tk.StringVar(value="No A file loaded")
        ttk.Label(lf, textvariable=self.var_A_info, anchor="w", justify="left").grid(row=row+1, column=0, columnspan=2, sticky="w", padx=4, pady=(0,6))
        row += 2

        # Screening options
        opt = ttk.LabelFrame(left, text="Screening Options")
        opt.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)

        try:
            Spinbox = ttk.Spinbox  # type: ignore[attr-defined]
        except Exception:
            Spinbox = tk.Spinbox  # type: ignore

        ttk.Label(opt, text="Pass threshold").grid(row=0, column=0, sticky="w", padx=4)
        self.var_pass = tk.DoubleVar(value=0.60)
        sp_pass = Spinbox(opt, from_=0.0, to=1.0, increment=0.05, textvariable=self.var_pass, width=6)
        sp_pass.grid(row=0, column=1, sticky="w")

        ttk.Label(opt, text="Border threshold").grid(row=0, column=2, sticky="w", padx=(12,4))
        self.var_border = tk.DoubleVar(value=0.40)
        sp_border = Spinbox(opt, from_=0.0, to=1.0, increment=0.05, textvariable=self.var_border, width=6)
        sp_border.grid(row=0, column=3, sticky="w")

        ttk.Label(opt, text="Missing policy").grid(row=1, column=0, sticky="w", padx=4, pady=(6,0))
        self.var_missing = tk.StringVar(value="unknown")
        ttk.Combobox(opt, textvariable=self.var_missing, values=["unknown","negative"], width=10, state="readonly").grid(row=1, column=1, sticky="w", pady=(6,0))

        ttk.Label(opt, text="LLM model (optional)").grid(row=1, column=2, sticky="w", padx=(12,4), pady=(6,0))
        self.var_model = tk.StringVar(value="")
        cmb_model = ttk.Combobox(opt, textvariable=self.var_model, values=list(LLM_MODEL_PRESETS), width=20, state="normal")
        cmb_model.grid(row=1, column=3, sticky="w", pady=(6,0))
        cmb_model.set("")

        self.var_hardstop = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="Hard-stop per criterion", variable=self.var_hardstop).grid(row=2, column=0, columnspan=4, sticky="w", padx=4, pady=(6,0))

        # --- Two-stage controls ---
        stg = ttk.LabelFrame(left, text="Two-Stage Controls")
        stg.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        ttk.Label(stg, text="Stage H include mode").grid(row=0, column=0, sticky="w", padx=4)
        self.var_h_mode = tk.StringVar(value="all")
        ttk.Combobox(stg, textvariable=self.var_h_mode, values=["all","any"], width=8, state="readonly").grid(row=0, column=1, sticky="w")

        ttk.Label(stg, text="Stage L include mode").grid(row=0, column=2, sticky="w", padx=(12,4))
        self.var_l_mode = tk.StringVar(value="all")
        ttk.Combobox(stg, textvariable=self.var_l_mode, values=["all","any"], width=8, state="readonly").grid(row=0, column=3, sticky="w")

        self.var_randomize = tk.BooleanVar(value=True)
        ttk.Checkbutton(stg, text="Randomize order within excludes/includes", variable=self.var_randomize).grid(row=1, column=0, columnspan=4, sticky="w", padx=4, pady=(6,0))

        ttk.Label(stg, text="Seed (optional)").grid(row=2, column=0, sticky="w", padx=4, pady=(6,0))
        self.var_seed = tk.StringVar(value="")
        ttk.Entry(stg, textvariable=self.var_seed, width=18).grid(row=2, column=1, sticky="w", pady=(6,0))

        try:
            Spinbox = ttk.Spinbox  # type: ignore[attr-defined]
        except Exception:
            Spinbox = tk.Spinbox  # type: ignore

        ttk.Label(stg, text="LLM batch size").grid(row=2, column=2, sticky="w", padx=(12,4), pady=(6,0))
        self.var_llm_batch = tk.IntVar(value=75)
        Spinbox(stg, from_=1, to=500, increment=1, textvariable=self.var_llm_batch, width=8).grid(row=2, column=3, sticky="w", pady=(6,0))

        ttk.Label(stg, text="Max chars per field").grid(row=3, column=0, sticky="w", padx=4, pady=(6,0))
        self.var_llm_trunc = tk.IntVar(value=1500)
        Spinbox(stg, from_=200, to=8000, increment=50, textvariable=self.var_llm_trunc, width=8).grid(row=3, column=1, sticky="w", pady=(6,0))

        for c in range(4):
            stg.columnconfigure(c, weight=1)

        for c in range(4):
            opt.columnconfigure(c, weight=1)

        # --- Sub-stages (gated) ---
        gate = ttk.LabelFrame(left, text="Sub-stages (gated)")
        gate.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        self.btn_eh = ttk.Button(gate, text="Run E/H (Exclude Â· Heuristic)", command=lambda: self.on_run_substage("EH"))
        self.btn_eh.grid(row=0, column=0, sticky="we", padx=4, pady=4)

        self.btn_ih = ttk.Button(gate, text="Run I/H (Include Â· Heuristic)", command=lambda: self.on_run_substage("IH"))
        self.btn_ih.grid(row=0, column=1, sticky="we", padx=4, pady=4)

        self.btn_el = ttk.Button(gate, text="Run E/L (Exclude Â· LLM)", command=lambda: self.on_run_substage("EL"))
        self.btn_el.grid(row=1, column=0, sticky="we", padx=4, pady=4)

        self.btn_il = ttk.Button(gate, text="Run I/L (Include Â· LLM Â· Final)", command=lambda: self.on_run_substage("IL"))
        self.btn_il.grid(row=1, column=1, sticky="we", padx=4, pady=4)

        self.btn_reset = ttk.Button(gate, text="Reset staged flow", command=self._reset_gated_flow)
        self.btn_reset.grid(row=2, column=0, columnspan=2, sticky="we", padx=4, pady=(8,4))

        # New: Option B toggle â€” make every sub-stage tab show ALL items
        self.var_allview = tk.BooleanVar(value=True)
        def _on_allview_toggle():
            self._refresh_all_subtabs()
            try:
                self.log(f"[UI] Substage All-Items view = {'ON' if self.var_allview.get() else 'OFF'}\n")
            except Exception:
                pass
        ttk.Checkbutton(
            gate,
            text="Show all items in substage tabs",
            variable=self.var_allview,
            command=_on_allview_toggle
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=4, pady=(4,2))
        for c in range(2):
            gate.columnconfigure(c, weight=1)

        # initialize gating
        self._update_stage_buttons()
        # Ensure current All-Items toggle is applied to tabs
        self._refresh_all_subtabs()

        # Export
        exp = ttk.LabelFrame(left, text="Export")
        exp.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)
        ttk.Button(exp, text="Export Decisions (CSV)", command=self.on_export_decisions_csv).grid(row=0, column=0, sticky="we", padx=4, pady=3)
        ttk.Button(exp, text="Export Decisions (XLSX)", command=self.on_export_decisions_xlsx).grid(row=0, column=1, sticky="we", padx=4, pady=3)
        ttk.Button(exp, text="Export Audit (CSV)", command=self.on_export_audit_csv).grid(row=1, column=0, sticky="we", padx=4, pady=3)
        ttk.Button(exp, text="Export Audit (XLSX)", command=self.on_export_audit_xlsx).grid(row=1, column=1, sticky="we", padx=4, pady=3)
        ttk.Button(exp, text="Save Charts (PNG)", command=self.on_save_charts).grid(row=2, column=0, columnspan=2, sticky="we", padx=4, pady=(6,3))

        # Columns (global)
        colf = ttk.LabelFrame(left, text="Columns & Sorting")
        colf.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)
        ttk.Button(colf, text="Columnsâ€¦", command=self._open_column_manager).grid(row=0, column=0, sticky="w", padx=4, pady=3)
        ttk.Label(colf, text="Tip: Click header to sort (Shift+click adds a secondary key)").grid(row=0, column=1, sticky="w", padx=4, pady=3)
        colf.columnconfigure(1, weight=1)

        # RIGHT: Tabs
        notebook = ttk.Notebook(right)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Criteria tab
        crit_tab = ttk.Frame(notebook)
        notebook.add(crit_tab, text="Criteria")
        self.tv_crit = ttk.Treeview(crit_tab, columns=self.CRIT_COLS, show="headings", selectmode="extended")
        ys_crit = ttk.Scrollbar(crit_tab, orient="vertical", command=self.tv_crit.yview)
        xs_crit = ttk.Scrollbar(crit_tab, orient="horizontal", command=self.tv_crit.xview)
        self.tv_crit.configure(yscrollcommand=ys_crit.set, xscrollcommand=xs_crit.set)
        try:
            self.tv_crit.tag_configure("disabled", foreground="#888888")
        except Exception:
            pass
        for c in self.CRIT_COLS:
            if c == "label":
                w = 260
            elif c in {"what"}:
                w = 200
            elif c == "enabled":
                w = 70
            else:
                w = 110
            self.tv_crit.heading(c, text=c)
            self.tv_crit.column(c, width=w, anchor="w", stretch=False)
        crit_tab.rowconfigure(0, weight=1)
        crit_tab.columnconfigure(0, weight=1)
        self.tv_crit.grid(row=0, column=0, sticky="nsew")
        ys_crit.grid(row=0, column=1, sticky="ns")
        xs_crit.grid(row=1, column=0, sticky="ew")
        self._bind_tree_mousewheel(self.tv_crit)

        # Inline editing & context menu & shortcuts
        self.tv_crit.bind("<Double-1>", self._on_crit_cell_dblclick)
        self.tv_crit.bind("<Button-1>", self._on_crit_click_prevent_stray_editor)
        self.tv_crit.bind("<Button-3>", self._on_right_click)
        self.tv_crit.bind("<Control-Button-1>", lambda e: None)

        # E/H tab (dropped by heuristic excludes)
        eh_tab = ttk.Frame(notebook)
        notebook.add(eh_tab, text="E/H")
        self.tv_eh = ttk.Treeview(eh_tab, columns=self.EH_COLS, show="headings")
        ys_eh = ttk.Scrollbar(eh_tab, orient="vertical", command=self.tv_eh.yview)
        xs_eh = ttk.Scrollbar(eh_tab, orient="horizontal", command=self.tv_eh.xview)
        self.tv_eh.configure(yscrollcommand=ys_eh.set, xscrollcommand=xs_eh.set)
        for c in self.EH_COLS:
            if c == "title":
                w = 420
            elif c in {"hard_stop_criterion_label"}:
                w = 260
            elif c in {"a_id","lang","doc_type","year"}:
                w = 90
            elif c in {"venue"}:
                w = 180
            elif c in {"score","pass_thr","border_thr"}:
                w = 90
            elif c in {"hard_stop_triggered"}:
                w = 130
            elif c in {"h_pass","l_pass"}:
                w = 80
            elif c in {"random_seed_used"}:
                w = 160
            else:
                w = 150
            self.tv_eh.heading(c, text=c)
            self.tv_eh.column(c, width=w, anchor="w", stretch=False)
        eh_tab.rowconfigure(0, weight=1); eh_tab.columnconfigure(0, weight=1)
        self.tv_eh.grid(row=0, column=0, sticky="nsew"); ys_eh.grid(row=0, column=1, sticky="ns"); xs_eh.grid(row=1, column=0, sticky="ew")
        self._bind_tree_mousewheel(self.tv_eh)
        self._bind_sorting(self.tv_eh)
        self._ensure_tooltip_bindings(self.tv_eh)

        # I/H tab (survivors & flags)
        ih_tab = ttk.Frame(notebook)
        notebook.add(ih_tab, text="I/H")
        self.tv_ih = ttk.Treeview(ih_tab, columns=self.IH_COLS, show="headings")
        ys_ih = ttk.Scrollbar(ih_tab, orient="vertical", command=self.tv_ih.yview)
        xs_ih = ttk.Scrollbar(ih_tab, orient="horizontal", command=self.tv_ih.xview)
        self.tv_ih.configure(yscrollcommand=ys_ih.set, xscrollcommand=xs_ih.set)
        for c in self.IH_COLS:
            if c == "title":
                w = 420
            elif c in {"hard_stop_criterion_label"}:
                w = 260
            elif c in {"a_id","lang","doc_type","year"}:
                w = 90
            elif c in {"venue"}:
                w = 180
            elif c in {"score","pass_thr","border_thr"}:
                w = 90
            elif c in {"hard_stop_triggered"}:
                w = 130
            elif c in {"h_pass","l_pass"}:
                w = 80
            elif c in {"random_seed_used"}:
                w = 160
            else:
                w = 150
            self.tv_ih.heading(c, text=c)
            self.tv_ih.column(c, width=w, anchor="w", stretch=False)
        ih_tab.rowconfigure(0, weight=1); ih_tab.columnconfigure(0, weight=1)
        self.tv_ih.grid(row=0, column=0, sticky="nsew"); ys_ih.grid(row=0, column=1, sticky="ns"); xs_ih.grid(row=1, column=0, sticky="ew")
        self._bind_tree_mousewheel(self.tv_ih)

        # E/L tab (dropped by LLM excludes)
        el_tab = ttk.Frame(notebook)
        notebook.add(el_tab, text="E/L")
        self.tv_el = ttk.Treeview(el_tab, columns=self.EL_COLS, show="headings")
        ys_el = ttk.Scrollbar(el_tab, orient="vertical", command=self.tv_el.yview)
        xs_el = ttk.Scrollbar(el_tab, orient="horizontal", command=self.tv_el.xview)
        self.tv_el.configure(yscrollcommand=ys_el.set, xscrollcommand=xs_el.set)
        for c in self.EL_COLS:
            if c == "title":
                w = 420
            elif c in {"hard_stop_criterion_label"}:
                w = 260
            elif c in {"a_id","lang","doc_type","year"}:
                w = 90
            elif c in {"venue"}:
                w = 180
            elif c in {"score","pass_thr","border_thr"}:
                w = 90
            elif c in {"hard_stop_triggered"}:
                w = 130
            elif c in {"h_pass","l_pass"}:
                w = 80
            elif c in {"random_seed_used"}:
                w = 160
            else:
                w = 150
            self.tv_el.heading(c, text=c)
            self.tv_el.column(c, width=w, anchor="w", stretch=False)
        el_tab.rowconfigure(0, weight=1); el_tab.columnconfigure(0, weight=1)
        self.tv_el.grid(row=0, column=0, sticky="nsew"); ys_el.grid(row=0, column=1, sticky="ns"); xs_el.grid(row=1, column=0, sticky="ew")
        self._bind_tree_mousewheel(self.tv_el)

        # Final tab (I/L)
        res_tab = ttk.Frame(notebook)
        notebook.add(res_tab, text="I/L (Final)")
        self.tv_res = ttk.Treeview(res_tab, columns=self.RES_COLS, show="headings")
        ys_res = ttk.Scrollbar(res_tab, orient="vertical", command=self.tv_res.yview)
        xs_res = ttk.Scrollbar(res_tab, orient="horizontal", command=self.tv_res.xview)
        self.tv_res.configure(yscrollcommand=ys_res.set, xscrollcommand=xs_res.set)
        for c in self.RES_COLS:
            if c == "title":
                w = 420
            elif c in {"hard_stop_criterion_label"}:
                w = 260
            elif c in {"a_id","lang","doc_type","year"}:
                w = 90
            elif c in {"venue"}:
                w = 180
            elif c in {"score","pass_thr","border_thr"}:
                w = 90
            elif c in {"hard_stop_triggered"}:
                w = 130
            elif c in {"h_pass","l_pass"}:
                w = 80
            elif c in {"random_seed_used"}:
                w = 160
            else:
                w = 150
            self.tv_res.heading(c, text=c)
            self.tv_res.column(c, width=w, anchor="w", stretch=False)
        res_tab.rowconfigure(0, weight=1)
        res_tab.columnconfigure(0, weight=1)
        self.tv_res.grid(row=0, column=0, sticky="nsew")
        ys_res.grid(row=0, column=1, sticky="ns")
        xs_res.grid(row=1, column=0, sticky="ew")
        self._bind_tree_mousewheel(self.tv_res)

        # Log box
        logf = ttk.LabelFrame(right, text="Log")
        logf.pack(side=tk.BOTTOM, fill=tk.BOTH, padx=8, pady=(0,8))
        self.txt_log = tk.Text(logf, height=8)
        self.txt_log.pack(fill=tk.BOTH, expand=True)

        # Keyboard shortcuts
        is_mac = platform.system() == "Darwin"
        mod = "Command" if is_mac else "Control"
        self.tv_crit.bind("<Delete>", lambda e: self.disable_selected())
        self.tv_crit.bind("<Shift-Delete>", lambda e: self.delete_selected())
        self.tv_crit.bind(f"<{mod}-d>", lambda e: self.duplicate_selected())
        self.tv_crit.bind(f"<{mod}-e>", lambda e: self.toggle_enable_selected())

        # Context menu
        self._menu = tk.Menu(self.tv_crit, tearoff=0)
        self._menu.add_command(label="Enable", command=self.enable_selected)
        self._menu.add_command(label="Disable", command=self.disable_selected)
        self._menu.add_separator()
        self._menu.add_command(label="Duplicate", command=self.duplicate_selected)
        self._menu.add_separator()
        self._menu.add_command(label="Delete permanentlyâ€¦", command=self.delete_selected)

    # ------------- helpers -------------
    
    def _parent_toplevel(self) -> tk.Misc:
        # Prefer the real toplevel of our frame; fall back to injected _root; finally any widget's toplevel.
        try:
            if self._frame:
                return self._frame.winfo_toplevel()
        except Exception:
            pass
        if self._root:
            return self._root
        # last resort: use the criteria tree if present
        if self.tv_crit:
            return self.tv_crit.winfo_toplevel()
        raise RuntimeError("No parent toplevel available")
    

    def log(self, msg: str):
        if self.txt_log is not None:
            self.txt_log.insert(tk.END, msg)
            self.txt_log.see(tk.END)

    def _row_enabled_disp(self, row: Dict[str, Any]) -> str:
        return "on" if row.get("enabled", True) else "off"

    def _refresh_criteria_table(self):
        if not self.tv_crit: return
        self.tv_crit.delete(*self.tv_crit.get_children())
        for idx, r in enumerate(self.criteria_rows):
            iid = str(idx)
            tags = ()
            if not r.get("enabled", True):
                tags = ("disabled",)
            self.tv_crit.insert("", tk.END, iid=iid, values=(
                self._row_enabled_disp(r),
                r.get("type"), r.get("scope"), r.get("label"),
                r.get("operator"), r.get("target"), ", ".join(r.get("what") or []),
                r.get("how"), r.get("weight"), r.get("threshold"),
            ), tags=tags)

    def _refresh_results_table(self):
        if not self.tv_res: return
        self.tv_res.delete(*self.tv_res.get_children())
        for r in self.final_rows or []:
            self.tv_res.insert("", tk.END, values=self._row_to_all_values(r))

    def _close_editor(self, commit: bool = True):
        if not self._editor or not self._editor_info:
            return
        iid, colname = self._editor_info
        try:
            if commit:
                self._commit_editor_value(iid, colname)
        finally:
            self._editor.destroy()
            self._editor = None
            self._editor_info = None

    def _commit_editor_value(self, iid: str, colname: str):
        idx = int(iid)
        if idx < 0 or idx >= len(self.criteria_rows):
            return
        row = self.criteria_rows[idx]

        def set_and_refresh(val):
            if colname in ("weight", "threshold"):
                try:
                    val = float(val)
                except Exception:
                    pass
            if colname == "what":
                row[colname] = [p.strip() for p in str(val).split(",") if p.strip()]
            else:
                row[colname] = val
            disp = list(self.tv_crit.item(iid, "values"))
            col_index = self.CRIT_COLS.index(colname)
            if colname == "what":
                disp[col_index] = ", ".join(row["what"])
            elif colname == "enabled":
                disp[col_index] = self._row_enabled_disp(row)
            else:
                disp[col_index] = str(val)
            tags = ()
            if not row.get("enabled", True):
                tags = ("disabled",)
            self.tv_crit.item(iid, values=tuple(disp), tags=tags)

        w = self._editor
        if isinstance(w, (ttk.Combobox,)):
            set_and_refresh(w.get().strip())
        elif isinstance(w, (tk.Entry, ttk.Entry)):
            set_and_refresh(w.get())
        elif isinstance(w, (tk.Spinbox, ttk.Spinbox)):  # type: ignore[attr-defined]
            set_and_refresh(w.get())

    def _on_crit_click_prevent_stray_editor(self, _evt):
        if self._editor:
            self._close_editor(commit=True)

    def _on_right_click(self, event):
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

    def _on_crit_cell_dblclick(self, event):
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

        # Toggle enabled directly on double click
        if colname == "enabled":
            idx = int(row_id)
            cur = bool(self.criteria_rows[idx].get("enabled", True))
            self.criteria_rows[idx]["enabled"] = (not cur)
            self._refresh_criteria_table()
            return

        bbox = self.tv_crit.bbox(row_id, col_id)
        if not bbox:
            return
        x, y, width, height = bbox

        editor = None
        current_val = self.tv_crit.set(row_id, colname)

        if colname == "type":
            editor = ttk.Combobox(self.tv_crit, values=sorted(ALLOWED_TYPES), state="readonly")
            editor.set(current_val or "include")

        elif colname == "scope":
            editor = ttk.Combobox(self.tv_crit, values=sorted(ALLOWED_SCOPE), state="disabled")
            editor.set("metadata")

        elif colname == "label":
            editor = ttk.Entry(self.tv_crit); editor.insert(0, current_val or "")

        elif colname == "operator":
            editor = ttk.Combobox(self.tv_crit, values=sorted(ALLOWED_OPERATORS), state="readonly")
            fallback = current_val if current_val in ALLOWED_OPERATORS else "contains"
            editor.set(fallback)

        elif colname == "target":
            self._open_target_selector(row_id); return

        elif colname == "what":
            editor = ttk.Entry(self.tv_crit); editor.insert(0, current_val or "")

        elif colname == "how":
            editor = ttk.Combobox(self.tv_crit, values=["heuristic","llm"], state="readonly")
            fallback = current_val if current_val in {"heuristic","llm"} else "heuristic"
            editor.set(fallback)
            editor.bind("<<ComboboxSelected>>", lambda e: self._close_editor(commit=True))

        elif colname == "weight":
            try:
                Spinbox = ttk.Spinbox  # type: ignore[attr-defined]
            except Exception:
                Spinbox = tk.Spinbox  # type: ignore
            editor = Spinbox(self.tv_crit, from_=0.0, to=10.0, increment=0.5, width=6)
            try:
                editor.delete(0, tk.END); editor.insert(0, float(current_val))
            except Exception:
                editor.delete(0, tk.END); editor.insert(0, "1.0")

        elif colname == "threshold":
            try:
                Spinbox = ttk.Spinbox  # type: ignore[attr-defined]
            except Exception:
                Spinbox = tk.Spinbox  # type: ignore
            editor = Spinbox(self.tv_crit, from_=0.0, to=1.0, increment=0.05, width=6)
            try:
                editor.delete(0, tk.END); editor.insert(0, float(current_val))
            except Exception:
                editor.delete(0, tk.END); editor.insert(0, "0.60")

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

    def _open_target_selector(self, row_id: str):
        idx = int(row_id)
        if idx < 0 or idx >= len(self.criteria_rows):
            return

        choices = self._discover_target_fields()
        current = self.criteria_rows[idx].get("target") or ""
        current_set = {t.strip().lower() for t in current.split(",") if t.strip()}

        win = tk.Toplevel()
        win.title("Select target fields")
        win.transient(self.tv_crit.winfo_toplevel())
        win.grab_set()

        frm = ttk.Frame(win); frm.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        vars_map: Dict[str, tk.BooleanVar] = {}
        for i, fld in enumerate(choices):
            var = tk.BooleanVar(value=(fld in current_set))
            cb = ttk.Checkbutton(frm, text=fld, variable=var)
            cb.grid(row=i // 3, column=i % 3, sticky="w", padx=6, pady=4)
            vars_map[fld] = var

        btns = ttk.Frame(win); btns.pack(fill=tk.X, padx=10, pady=(6,10))
        def accept():
            selected = [k for k, v in vars_map.items() if v.get()]
            selected_str = ",".join(selected)
            self.criteria_rows[idx]["target"] = selected_str if selected else ""
            vals = list(self.tv_crit.item(row_id, "values"))
            col_index = self.CRIT_COLS.index("target")
            vals[col_index] = selected_str
            self.tv_crit.item(row_id, values=tuple(vals))
            win.destroy()

        ttk.Button(btns, text="OK", command=accept).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side=tk.RIGHT, padx=(0,8))

    def _discover_target_fields(self) -> List[str]:
        fallback = ["title","abstract","keywords","lang","doc_type","availability","year","venue"]
        if not self.A:
            return fallback
        keys: set = set()
        for r in self.A[:10]:
            if isinstance(r, dict):
                keys |= set(k for k in r.keys() if isinstance(k, str))
        ordered: List[str] = [f for f in fallback if f in keys]
        extras = sorted([k for k in keys if k not in ordered])
        return ordered + extras

    # --------- Soft delete / hard delete / duplicate ----------

    def _selected_indices(self) -> List[int]:
        if not self.tv_crit:
            return []
        ids = list(self.tv_crit.selection())
        try:
            return sorted(set(int(i) for i in ids))
        except Exception:
            return []

    def enable_selected(self):
        idxs = self._selected_indices()
        if not idxs: return
        ids = []
        for i in idxs:
            if 0 <= i < len(self.criteria_rows):
                self.criteria_rows[i]["enabled"] = True
                ids.append(self.criteria_rows[i].get("id") or f"C{i+1:02d}")
        self._refresh_criteria_table()
        self.log(f"[CRITERIA] Enabled {len(idxs)} row(s): {', '.join(ids)}\n")

    def disable_selected(self):
        idxs = self._selected_indices()
        if not idxs: return
        ids = []
        for i in idxs:
            if 0 <= i < len(self.criteria_rows):
                self.criteria_rows[i]["enabled"] = False
                ids.append(self.criteria_rows[i].get("id") or f"C{i+1:02d}")
        self._refresh_criteria_table()
        self.log(f"[CRITERIA] Disabled {len(idxs)} row(s): {', '.join(ids)}\n")

    def toggle_enable_selected(self):
        idxs = self._selected_indices()
        if not idxs: return
        ids = []
        for i in idxs:
            if 0 <= i < len(self.criteria_rows):
                cur = bool(self.criteria_rows[i].get("enabled", True))
                self.criteria_rows[i]["enabled"] = not cur
                ids.append(self.criteria_rows[i].get("id") or f"C{i+1:02d}")
        self._refresh_criteria_table()
        self.log(f"[CRITERIA] Toggled {len(idxs)} row(s): {', '.join(ids)}\n")

    def _generate_new_id(self, base: str) -> str:
        base = (base or "C").strip()
        used = {str(r.get("id")) for r in self.criteria_rows if r.get("id")}
        for i in range(1, 27):
            cand = f"{base}{chr(96+i)}"
            if cand not in used:
                return cand
        n = 1
        while f"{base}_{n}" in used:
            n += 1
        return f"{base}_{n}"

    def duplicate_selected(self):
        idxs = self._selected_indices()
        if not idxs: return
        new_rows = []
        for i in idxs:
            if 0 <= i < len(self.criteria_rows):
                src = dict(self.criteria_rows[i])
                src["id"] = self._generate_new_id(str(src.get("id") or f"C{i+1:02d}"))
                src["label"] = f"{src.get('label','').strip()} (copy)".strip()
                src["enabled"] = True
                new_rows.append((i, src))
        offset = 0
        for i, row in new_rows:
            self.criteria_rows.insert(i + 1 + offset, row)
            offset += 1
        self._refresh_criteria_table()
        self.log(f"[CRITERIA] Duplicated {len(new_rows)} row(s).\n")

    def delete_selected(self):
        idxs = self._selected_indices()
        if not idxs: return
        if not messagebox.askyesno("Delete permanently",
                                   f"Delete {len(idxs)} selected row(s) permanently? This cannot be undone."):
            return
        for i in sorted(idxs, reverse=True):
            if 0 <= i < len(self.criteria_rows):
                del self.criteria_rows[i]
        self._refresh_criteria_table()
        self.log(f"[CRITERIA] Deleted {len(idxs)} row(s).\n")

    # ----------------- New: Threaded run + modal (full + substage) -----------------

    def _collect_run_params(self) -> Tuple[float,float,str,Optional[str],int,int,str,str,bool,Optional[str],bool,Dict[str,Any]]:
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

        # Stage controls
        h_mode = (self.var_h_mode.get().strip() if self.var_h_mode else "all")
        l_mode = (self.var_l_mode.get().strip() if self.var_l_mode else "all")
        randomize = bool(self.var_randomize.get()) if self.var_randomize else True
        seed = (self.var_seed.get().strip() if self.var_seed else "") or None

        # LLM batching params
        llm_batch = int(self.var_llm_batch.get()) if self.var_llm_batch else 75
        llm_trunc = int(self.var_llm_trunc.get()) if self.var_llm_trunc else 1500

        run_params = {"model": model or "(none)", "llm_batch": llm_batch, "llm_trunc": llm_trunc}
        return (pass_thr, border_thr, missing_policy, model, llm_trunc, llm_batch,
                h_mode, l_mode, randomize, seed, hard_stop, run_params)

    def on_run_substage(self, mode: str):
        self._subrun_mode = (mode or "").upper()
        try:
            args = self._collect_run_params()
        except RuntimeError as e:
            messagebox.showwarning("Run", str(e)); return
        # gating check
        if mode == "IH" and not self._gate_eh_done:
            messagebox.showinfo("Gated", "Run E/H first."); return
        if mode == "EL" and not (self._gate_eh_done and self._gate_ih_done):
            messagebox.showinfo("Gated", "Run E/H and I/H first."); return
        # IL requires EH + IH only. If EL wasn't run, IL will execute full Stage L.
        if mode == "IL" and not (self._gate_eh_done and self._gate_ih_done):
            messagebox.showinfo(
                "Gated",
                "Run E/H and I/H first. (E/L optional; if not run, I/L will execute full Stage L.)"
            )
            return
        self._start_run_worker(args, subrun=mode)

    def _start_run_worker(self, args_tuple: Tuple, subrun: Optional[str]):
        (pass_thr, border_thr, missing_policy, model, llm_trunc, llm_batch,
         h_mode, l_mode, randomize, seed, hard_stop, run_params) = args_tuple

        # Reset run state
        self._run_finished = False
        self._results_buffer = None
        self._aggregated_buffer = None
        self._progress_q = queue.Queue()
        self._cancel_token = _CancelToken()
        # Reset ETA + stage counters
        self._eta_samples = 0; self._ema_rate = None
        self._progress_units_done = 0; self._progress_units_total = 0
        self._h_total = 0; self._h_done = 0
        self._l_batches_total = 0; self._l_batches_done = 0

        # Modal + disable controls
        self._open_progress_modal(run_params)
        self._set_controls_state(enabled=False)

        worker_args = (
            pass_thr, border_thr, missing_policy, model, llm_trunc, llm_batch,
            h_mode, l_mode, randomize, seed, hard_stop, subrun
        )
        self._run_thread = threading.Thread(target=self._worker_run_screening, args=worker_args, daemon=True)
        self._run_thread.start()
        self._run_started_ts = time.time()
        
        # If I/L, make Stage H look intentional (reused) in the UI.
        if (self._subrun_mode or "").upper() == "IL":
            self._emit_progress({
                "kind": "h_stage_skipped",
                "stage": "H",
                "reason": "reused_from_previous"
            })
        
        self._poll_modal_updates()

    def _emit_progress(self, evt: Dict[str, Any]):
        """Called by engine (from worker thread). Push into thread-safe queue."""
        if self._progress_q is not None:
            self._progress_q.put(evt)

    def _worker_run_screening(self,
                              pass_thr, border_thr, missing_policy, model, llm_trunc, llm_batch,
                              h_mode, l_mode, randomize, seed, hard_stop, subrun):
        try:
            # Decide if we should reuse E/L survivors when running I/L
            reuse_from_stage = None
            initial_ids = None
            if (subrun or "").upper() == "IL":
                if self._gate_el_done and getattr(self, "_el_survivor_ids", None):
                    reuse_from_stage = "EL"
                    initial_ids = list(self._el_survivor_ids)
                    self.log(f"[I/L] Reusing {len(initial_ids)} survivor(s) from E/L; skipping L/EXC.\n")
                else:
                    self.log("[I/L] No E/L survivors cached; running full L (E/L â†’ I/L).\n")
            elif (subrun or "").upper() == "EL":
                # Fresh EL run should clear old cache first
                self._el_survivor_ids = []

            res = screen_metadata(
                self.A, self.criteria_rows,
                pass_thr=pass_thr, border_thr=border_thr,
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
                subrun=subrun or None,
                reuse_from_stage=reuse_from_stage,   # <<< key: reuse EL
                initial_a_ids=initial_ids,           # <<< key: the EL survivor list
            )

            if self._cancel_token and self._cancel_token.cancelled:
                self._results_buffer = None
                self._aggregated_buffer = None
            else:
                # Sub-runs always return a dict
                mode = (res.get("mode") or "").upper()
                caches = res.get("caches") or {}
                self.stage_caches = caches

                # update gate flags
                if mode == "EH":
                    self._gate_eh_done = True
                elif mode == "IH":
                    self._gate_eh_done = True; self._gate_ih_done = True
                elif mode == "EL":
                    self._gate_eh_done = True; self._gate_ih_done = True; self._gate_el_done = True
                elif mode == "IL":
                    self._gate_eh_done = True; self._gate_ih_done = True; self._gate_el_done = True

                # populate substage tabs
                # E/H tab
                eh = caches.get("EH") or {}
                self._eh_dropped_rows = eh.get("dropped_records") or []
                # I/H tab
                ih = caches.get("IH") or {}
                self._ih_survivor_ids = ih.get("survivors_after_IH_ids") or []
                self._ih_h_pass_map = ih.get("h_pass_map") or {}
                # E/L tab
                el = caches.get("EL") or {}
                self._el_dropped_rows = el.get("dropped_records") or []
                self._el_survivor_ids = el.get("survivors_after_EL_ids") or el.get("survivors_after_L_ids") or []

                # If IL, final_results preview is provided
                if mode == "IL":
                    self._results_buffer = res.get("final_results") or []
                    self.meta_results = self._results_buffer
                    self._aggregated_buffer = aggregate_decisions(
                        self._results_buffer, self.A,
                        pass_thr=pass_thr, border_thr=border_thr
                    )
                else:
                    self._results_buffer = None
                    self._aggregated_buffer = None
                    
        except Exception as e:
            self._results_buffer = [{"__error__": str(e)}]
            self._aggregated_buffer = None
        finally:
            self._run_finished = True

    # ----------------- Modal (strict) -----------------

    def _open_progress_modal(self, run_params: Dict[str, Any]):
        parent = self._parent_toplevel()
        win = tk.Toplevel(parent)
    
        self._modal = win
        subrun = (self._subrun_mode or "â€”").upper()
        win.title(f"Screening Â· {subrun}")
        win.transient(parent)
        win.grab_set()
        win.attributes("-topmost", True)
    
        frm = ttk.Frame(win, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)
    
        # Header (unified)
        ttk.Label(
            frm,
            text=f"Screening: {subrun}",
            font=("TkDefaultFont", 12, "bold")
        ).pack(anchor="w", pady=(0,8))
    
        # Stage H (always visible, even if no-op for this sub-run)
        h_blk = ttk.Frame(frm); h_blk.pack(fill="x", pady=(4,6))
        ttk.Label(h_blk, text="Stage H (heuristics)").pack(anchor="w")
        h_label = ttk.Label(h_blk, text="0/0 (waiting or skipped)")
        h_label.pack(anchor="w")
        h_prog = ttk.Progressbar(h_blk, mode="indeterminate", maximum=100)
        h_prog.pack(fill="x", padx=(0,4), pady=(4,0))
        h_prog.start(30)
    
        # Stage L (always visible, even if no-op for this sub-run)
        l_blk = ttk.Frame(frm); l_blk.pack(fill="x", pady=(6,6))
        ttk.Label(l_blk, text="Stage L (LLM)").pack(anchor="w")
        l_label = ttk.Label(l_blk, text="0/0 batches (waiting or skipped)")
        l_label.pack(anchor="w")
        l_prog = ttk.Progressbar(l_blk, mode="indeterminate", maximum=100)
        l_prog.pack(fill="x", padx=(0,4), pady=(4,0))
        l_prog.start(50)
    
        # Dedicated "current step" line (homogenized across all sub-runs)
        step = ttk.Label(frm, text="Step: â€”", foreground="#444444")
        step.pack(anchor="w", pady=(6,0))
    
        # Status + ETA + Params
        sub = ttk.Label(frm, text="Status: runningâ€¦", foreground="#555555"); sub.pack(anchor="w", pady=(2,0))
        elapsed = ttk.Label(frm, text="Elapsed: 00:00:00   ETA: â€”", foreground="#666666"); elapsed.pack(anchor="w", pady=(2,0))
        params = ttk.Label(frm, text=f"Model + params: {run_params['model']} Â· batch={run_params['llm_batch']} Â· trunc={run_params['llm_trunc']}", foreground="#666666")
        params.pack(anchor="w", pady=(2,0))
    
        # Buttons
        btns = ttk.Frame(frm); btns.pack(fill="x", pady=(10,0))
        cancel_btn = ttk.Button(btns, text="Cancel", command=self._on_cancel_click); cancel_btn.pack(side="right")
        ok_btn = ttk.Button(btns, text="OK", command=self._on_modal_ok); ok_btn.pack(side="right", padx=(0,8))
        ok_btn.configure(state="disabled")
            
        self._modal_widgets = {
            "h_label": h_label, "h_prog": h_prog,
            "l_label": l_label, "l_prog": l_prog,
            "step": step,
            "sub": sub, "elapsed": elapsed,
            "ok_btn": ok_btn, "cancel_btn": cancel_btn,
        }
        
        # If this is I/L, make Stage H look completed immediately (reused)
        if (self._subrun_mode or "").upper() == "IL":
            try:
                h_prog.stop()
            except Exception:
                pass
            self._set_progressbar_determinate(h_prog, maximum=1)
            h_prog["value"] = 1
            h_label.configure(text="H: skipped (reused from E/H + I/H)")
            try:
                self._modal_widgets["step"].configure(text="Step: H Â· skipped (reused)")  # type: ignore
            except Exception:
                pass
    
        win.geometry("580x330+120+120")
    
        def _on_close():
            if not self._run_finished:
                return
            self._on_modal_ok()
        win.protocol("WM_DELETE_WINDOW", _on_close)

    def _on_cancel_click(self):
        if self._modal_widgets:
            btn = self._modal_widgets.get("cancel_btn")
            sub = self._modal_widgets.get("sub")
            if btn:
                btn.configure(text="Cancellingâ€¦", state="disabled")
            if sub:
                sub.configure(text="Status: cancelling (will discard results)â€¦")
        if self._cancel_token:
            self._cancel_token.cancelled = True
        # also clarify the current-step line when cancelling
        if self._modal_widgets and "step" in self._modal_widgets:
            try:
                self._modal_widgets["step"].configure(text="Step: â€” (cancelling)")  # type: ignore
            except Exception:
                pass

    def _on_modal_ok(self):
        if self._modal:
            try:
                self._modal.grab_release()
            except Exception:
                pass
            self._modal.destroy()
            self._modal = None
            self._modal_widgets = {}
        self._set_controls_state(enabled=True)
        self._update_stage_buttons()

    # -------- progress â†’ UI & ETA --------

    def _handle_progress_event(self, evt: Dict[str, Any]):
        if not self._modal_widgets:
            return

        kind = evt.get("kind")
        h_label: ttk.Label = self._modal_widgets["h_label"]  # type: ignore
        h_prog: ttk.Progressbar = self._modal_widgets["h_prog"]  # type: ignore
        l_label: ttk.Label = self._modal_widgets["l_label"]  # type: ignore
        l_prog: ttk.Progressbar = self._modal_widgets["l_prog"]  # type: ignore

        # Stage H (granularity: by criterion only)
        if kind == "h_criterion_start":
            self._h_total = max(self._h_total, int(evt.get("crit_total") or 0))
            self._set_progressbar_determinate(h_prog, maximum=max(1, self._h_total))
            cur_idx = int(evt.get("crit_idx") or 1)
            # show current-1 completed
            h_prog["value"] = max(0, cur_idx - 1)
            label = evt.get("label") or evt.get("crit_id") or ""
            operator = evt.get("operator") or ""
            target = evt.get("target") or ""
            h_label.configure(text=f"Criterion {cur_idx}/{self._h_total} â€” {label} Â· {operator} ({target})")
            # unified step line
            if "step" in self._modal_widgets:
                self._modal_widgets["step"].configure(  # type: ignore
                    text=f"Step: H/{'INC' if (evt.get('block')=='include') else 'EXC'} Â· {evt.get('crit_id') or cur_idx} â€” starting"
                )            # update ETA: treat each H criterion as one unit
            self._progress_units_total = self._h_total + max(self._l_batches_total, 0)
            self._update_eta(self._h_done + self._l_batches_done, self._progress_units_total)

        elif kind == "h_criterion_done":
            cur_idx = int(evt.get("crit_idx") or 1)
            self._h_done = max(self._h_done, cur_idx)
            self._set_progressbar_determinate(h_prog, maximum=max(1, self._h_total))
            h_prog["value"] = self._h_done
            self._update_eta(self._h_done + self._l_batches_done, self._h_total + self._l_batches_total)
        
        elif kind == "h_stage_skipped":
            # Render H as completed/greyed because itâ€™s reused
            self._h_total = 0
            self._h_done = 0
            self._set_progressbar_determinate(h_prog, maximum=1)
            h_prog["value"] = 1
            try:
                h_prog.stop()
            except Exception:
                pass
            h_label.configure(text="H: skipped (reused from E/H + I/H)")
            if "step" in self._modal_widgets:
                self._modal_widgets["step"].configure(text="Step: H Â· skipped (reused)")

            # still update ETA with whatever we have so far
            self._update_eta(self._h_done + self._l_batches_done, self._h_total + self._l_batches_total)

        # Stage L (by batches + sub-statuses)
        elif kind == "l_criterion_start":
            batches_total = int(evt.get("batches_total") or 0)
            self._l_batches_total += batches_total
            self._set_progressbar_determinate(l_prog, maximum=max(1, self._l_batches_total))
            l_label.configure(text=f"Criterion {evt.get('crit_idx')}/{evt.get('crit_total')} â€” 0/{batches_total} batchesâ€¦")
            # unified step line
            if "step" in self._modal_widgets:
                self._modal_widgets["step"].configure(  # type: ignore
                    text=f"Step: L/{'INC' if (evt.get('block')=='include') else 'EXC'} Â· {evt.get('crit_id') or evt.get('crit_idx')} â€” batching ({batches_total})"
                )
            self._update_eta(self._h_done + self._l_batches_done, self._h_total + self._l_batches_total)

        elif kind == "l_batch":
            substate = (evt.get("sub") or "")
            bi = int(evt.get("batch_idx") or 0)
            bt = int(evt.get("batch_total") or 0)
            # Per-criterion label, plus global batch tally
            l_label.configure(text=f"Batch {bi}/{bt} â€” {substate}â€¦   (total {self._l_batches_done}/{self._l_batches_total})")
            # unified step line
            if "step" in self._modal_widgets:
                self._modal_widgets["step"].configure(  # type: ignore
                    text=f"Step: L Â· batch {bi}/{bt} â€” {substate}"
                )
            # ETA updates only when substate == 'batch_done'

        elif kind == "l_batch_retry":
            note = evt.get("note") or ""
            # show retry note in status; keep step line focused on where we are
            if "sub" in self._modal_widgets:
                self._modal_widgets["sub"].configure(text=f"Status: {note}")  # type: ignore

        elif kind == "l_criterion_done":
            # nothing special here; batches update the bar
            pass

        if kind == "l_batch" and evt.get("sub") == "batch_done":
            # One more batch finished
            self._l_batches_done += 1
            self._set_progressbar_determinate(l_prog, maximum=max(1, self._l_batches_total))
            l_prog["value"] = self._l_batches_done
            # reflect completion in the step line
            if "step" in self._modal_widgets:
                bi = int(evt.get("batch_idx") or 0)
                bt = int(evt.get("batch_total") or 0)
                self._modal_widgets["step"].configure(  # type: ignore
                    text=f"Step: L Â· batch {bi}/{bt} â€” done"
                )
            self._update_eta(self._h_done + self._l_batches_done, self._h_total + self._l_batches_total)

    def _set_progressbar_determinate(self, pb: ttk.Progressbar, *, maximum: int):
        try:
            if str(pb.cget("mode")) != "determinate":
                pb.stop()
                pb.configure(mode="determinate")
            if maximum != int(pb.cget("maximum")):
                pb.configure(maximum=max(1, int(maximum)))
        except Exception:
            pass

    def _update_eta(self, done: int, total: int):
        """Lightweight EMA ETA. Always show Elapsed; show ETA once we have totals + samples."""
        self._progress_units_done = max(done, 0)
        self._progress_units_total = max(total, 0)
    
        now = time.time()
        elapsed = max(1e-6, now - self._run_started_ts)
    
        # Render Elapsed immediately, even if we can't compute ETA yet
        if self._modal_widgets:
            elapsed_lbl: ttk.Label = self._modal_widgets["elapsed"]  # type: ignore
            def fmt_hms(s: float) -> str:
                s = int(max(0, s))
                h = s // 3600; m = (s % 3600) // 60; sec = s % 60
                return f"{h:02d}:{m:02d}:{sec:02d}"
            elapsed_str = fmt_hms(elapsed)
            # Tentative placeholder for ETA; we may overwrite below if we can compute it
            elapsed_lbl.configure(text=f"Elapsed: {elapsed_str}   ETA: â€”")
    
        # Without a total, we can't compute ETA yet (but Elapsed is already shown)
        if total <= 0:
            return
    
        inst_rate = self._progress_units_done / elapsed  # units/sec
        if inst_rate <= 0:
            return
        if self._ema_rate is None:
            self._ema_rate = inst_rate
        else:
            self._ema_rate = self._ema_alpha * inst_rate + (1 - self._ema_alpha) * self._ema_rate
        self._eta_samples += 1
    
        # If enough samples, overwrite the ETA part
        if self._modal_widgets and self._eta_samples >= 3 and self._ema_rate and self._ema_rate > 0:
            remaining = max(0.0, self._progress_units_total - self._progress_units_done)
            eta_seconds = remaining / self._ema_rate
            def fmt_hms(s: float) -> str:
                s = int(max(0, s))
                h = s // 3600; m = (s % 3600) // 60; sec = s % 60
                return f"{h:02d}:{m:02d}:{sec:02d}"
            elapsed_lbl: ttk.Label = self._modal_widgets["elapsed"]  # type: ignore
            elapsed_lbl.configure(text=f"Elapsed: {fmt_hms(elapsed)}   ETA: ~{fmt_hms(eta_seconds)}")

    def _poll_modal_updates(self):
        """UI thread polling: drain engine progress, update ETA, finish handling."""
        if not self._modal:
            return

        # Drain engine events
        if self._progress_q is not None:
            try:
                while True:
                    evt = self._progress_q.get_nowait()
                    self._handle_progress_event(evt)
            except queue.Empty:
                pass

        # Update elapsed even if no events
        if self._modal_widgets:
            self._update_eta(self._progress_units_done, self._progress_units_total)

        # Finish?
        if self._run_finished:
            # stop spinners if still indeterminate
            try:
                if str(self._modal_widgets["h_prog"].cget("mode")) == "indeterminate":  # type: ignore
                    self._modal_widgets["h_prog"].stop()  # type: ignore
                if str(self._modal_widgets["l_prog"].cget("mode")) == "indeterminate":  # type: ignore
                    self._modal_widgets["l_prog"].stop()  # type: ignore
            except Exception:
                pass

            ok_btn: ttk.Button = self._modal_widgets.get("ok_btn")  # type: ignore
            cancel_btn: ttk.Button = self._modal_widgets.get("cancel_btn")  # type: ignore
            sub: ttk.Label = self._modal_widgets.get("sub")  # type: ignore

            # Error?
            if isinstance(self._results_buffer, list) and self._results_buffer and "__error__" in self._results_buffer[0]:
                err = self._results_buffer[0]["__error__"]
                if sub: sub.configure(text=f"Status: error â€” {err}")
                if cancel_btn: cancel_btn.configure(state="disabled")
                if ok_btn: ok_btn.configure(state="normal")
                return

            # Cancelled?
            if self._cancel_token and self._cancel_token.cancelled:
                if sub: sub.configure(text="Status: cancelled â€” no changes saved")
                if cancel_btn: cancel_btn.configure(state="disabled")
                if ok_btn: ok_btn.configure(state="normal")
                return

            # Success: either substage caches, or final aggregated
            # 1) If we have substage caches, refresh those tabs
            if isinstance(self._results_buffer, type(None)) and self.stage_caches:
                # E/H
                self._refresh_eh_tab(getattr(self, "_eh_dropped_rows", []))
                # I/H
                self._refresh_ih_tab(getattr(self, "_ih_survivor_ids", []),
                                     getattr(self, "_ih_h_pass_map", {}))
                # E/L
                self._refresh_el_tab(
                    getattr(self, "_el_dropped_rows", []),
                    getattr(self, "_el_survivor_ids", []),
                )                # update gating + buttons
                self._update_stage_buttons()

            # 2) If we have final aggregation, refresh final tab
            if self._aggregated_buffer is not None:
                self.final_rows = self._aggregated_buffer
                counts = prisma_counts(self.final_rows)
                self._refresh_results_table()
                self.log(f"[RUN] Done. pass={counts.get('pass',0)}, borderline={counts.get('borderline',0)}, fail={counts.get('fail',0)}, total={counts.get('total',0)}\n")
                # Populate substage tabs from final rows (derived views)
                self._refresh_eh_tab(getattr(self, "_eh_dropped_rows", []))
                self._refresh_ih_tab(getattr(self, "_ih_survivor_ids", []), getattr(self, "_ih_h_pass_map", {}))
                self._refresh_el_tab(getattr(self, "_el_dropped_rows", []), [])
            if sub: sub.configure(text="Status: finished")
            if cancel_btn: cancel_btn.configure(state="disabled")
            if ok_btn: ok_btn.configure(state="normal")
            return

        # keep polling
        if self._modal:
            self._modal.after(120, self._poll_modal_updates)

    def _set_controls_state(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        container = self._frame or self._root
        if not container:
            return
        try:
            for w in container.winfo_children():
                # Skip modal subtree if present (keep OK/Cancel interactive)
                if self._modal and w == self._modal:
                    continue
                self._toggle_state_recursive(w, state)
        except Exception:
            pass
        self._update_stage_buttons()

    def _toggle_state_recursive(self, widget: tk.Widget, state: str):
        if isinstance(widget, (ttk.Entry, ttk.Combobox, ttk.Button, ttk.Checkbutton, ttk.Spinbox)):
            try:
                widget.configure(state=state)
            except Exception:
                pass
        try:
            for ch in widget.winfo_children():
                self._toggle_state_recursive(ch, state)
        except Exception:
            pass

    # --- exports

    def on_export_decisions_csv(self):
        if not self.final_rows:
            messagebox.showwarning("Export", "No results to export. Run screening first.")
            return
        path = filedialog.asksaveasfilename(title="Save Decisions CSV", defaultextension=".csv",
                                            filetypes=[("CSV","*.csv")])
        if not path: return
        export_decisions_csv(path, self.final_rows)
        self.log(f"[EXPORT] Decisions â†’ {os.path.basename(path)}\n")

    def on_export_decisions_xlsx(self):
        if not self.final_rows:
            messagebox.showwarning("Export", "No results to export. Run screening first.")
            return
        path = filedialog.asksaveasfilename(title="Save Decisions XLSX", defaultextension=".xlsx",
                                            filetypes=[("Excel","*.xlsx")])
        if not path: return
        try:
            export_decisions_xlsx(path, self.final_rows)
            self.log(f"[EXPORT] Decisions â†’ {os.path.basename(path)}\n")
        except Exception as e:
            messagebox.showerror("XLSX Export", str(e))

    def on_export_audit_csv(self):
        if not self.meta_results:
            messagebox.showwarning("Export", "No audit to export. Run screening first.")
            return
        path = filedialog.asksaveasfilename(title="Save Metadata Audit CSV", defaultextension=".csv",
                                            filetypes=[("CSV","*.csv")])
        if not path: return
        export_metadata_audit_csv(path, self.meta_results)
        self.log(f"[EXPORT] Audit â†’ {os.path.basename(path)}\n")

    def on_export_audit_xlsx(self):
        if not self.meta_results:
            messagebox.showwarning("Export", "No audit to export. Run screening first.")
            return
        path = filedialog.asksaveasfilename(title="Save Metadata Audit XLSX", defaultextension=".xlsx",
                                            filetypes=[("Excel","*.xlsx")])
        if not path: return
        try:
            export_metadata_audit_xlsx(path, self.meta_results)
            self.log(f"[EXPORT] Audit â†’ {os.path.basename(path)}\n")
        except Exception as e:
            messagebox.showerror("XLSX Export", str(e))

    def on_save_charts(self):
        if not self.meta_results:
            messagebox.showwarning("Charts", "No results. Run screening first.")
            return
        outdir = filedialog.askdirectory(title="Select output folder for charts")
        if not outdir: return
        paths = save_metadata_charts(outdir, self.meta_results)
        if not paths:
            messagebox.showinfo("Charts", "matplotlib not available; no charts saved.")
            return
        self.log("[CHARTS] Saved:\n  - " + "\n  - ".join(f"{k}: {v}" for k, v in paths.items()) + "\n")

    def _bind_tree_mousewheel(self, tv: ttk.Treeview):
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

    # ---------- Column discovery & rebuild ----------

    def _discover_biblio_columns(self) -> List[str]:
        """All keys seen in A minus the ENGINE_COLS; stable order: common fields first, then extras."""
        if not self.A:
            return []
        keys: List[str] = []
        seen = set()
        for r in self.A[:500]:
            if not isinstance(r, dict): continue
            for k, v in r.items():
                if not isinstance(k, str): continue
                lk = k.strip()
                if not lk or lk in self.ENGINE_COLS: continue
                if lk not in seen:
                    seen.add(lk); keys.append(lk)
        # Reorder to surface usual suspects near the engine block
        preferred = ["authors","abstract","keywords","publisher","issue","volume","pages","doi","url","availability"]
        ordered = [c for c in preferred if c in keys]
        extras  = [c for c in keys if c not in ordered]
        return ordered + extras

    def _compute_all_columns(self):
        """Refresh BIBLIO_COLS/ALL_COLS and propagate to COLS tuples used by tabs."""
        bcols = tuple(self._discover_biblio_columns())
        self.BIBLIO_COLS = bcols  # type: ignore[attr-defined]
        self.ALL_COLS = self.ENGINE_COLS + self.BIBLIO_COLS  # type: ignore[attr-defined]
        self.EH_COLS = self.ALL_COLS  # type: ignore[attr-defined]
        self.IH_COLS = self.ALL_COLS  # type: ignore[attr-defined]
        self.EL_COLS = self.ALL_COLS  # type: ignore[attr-defined]
        self.RES_COLS = self.ALL_COLS  # type: ignore[attr-defined]

        # Initialize visible columns (first time) -> show all
        if self.visible_cols is None:
            self.visible_cols = list(self.ALL_COLS)

    def _rebuild_table_columns(self):
        """Reconfigure the four result tables to use ALL_COLS & visible_cols with widths and headings."""
        for tv, cols in [
            (self.tv_eh, getattr(self, "EH_COLS", self.ENGINE_COLS)),
            (self.tv_ih, getattr(self, "IH_COLS", self.ENGINE_COLS)),
            (self.tv_el, getattr(self, "EL_COLS", self.ENGINE_COLS)),
            (self.tv_res, getattr(self, "RES_COLS", self.ENGINE_COLS)),
        ]:
            if not tv: continue
            tv.delete(*tv.get_children())
            tv["columns"] = cols
            for c in cols:
                # sensible widths
                if c == "title": w = 420
                elif c in {"abstract"}: w = 260
                elif c in {"hard_stop_criterion_label"}: w = 260
                elif c in {"a_id","lang","doc_type","year"}: w = 90
                elif c in {"venue","publisher"}: w = 180
                elif c in {"score","pass_thr","border_thr"}: w = 90
                elif c in {"hard_stop_triggered"}: w = 130
                elif c in {"h_pass","l_pass"}: w = 80
                elif c in {"random_seed_used"}: w = 160
                else: w = 140
                tv.heading(c, text=c, command=lambda col=c, _tv=tv: self._sort_by_column(_tv, col))
                tv.column(c, width=w, anchor="w", stretch=False)
            # Apply column visibility (hide columns by width=0 & stretch False)
            self._apply_visible_columns(tv)
            self._bind_sorting(tv)
            self._ensure_tooltip_bindings(tv)

    # ---------- Sorting ----------

    def _bind_sorting(self, tv: ttk.Treeview):
        if tv not in self._sort_state:
            self._sort_state[tv] = []
        # Nothing else to do here; per-heading command is wired in _rebuild_table_columns

    def _sort_by_column(self, tv: ttk.Treeview, col: str):
        # Toggle asc/desc; Shift => add as secondary key
        import sys
        state = self._sort_state.setdefault(tv, [])
        shift = False
        try:
            shift = (tv.tk.call('tk::GetModifierState', 'Shift') == '1')  # best-effort; may vary by platform
        except Exception:
            pass
        existing = [c for c, _ in state]
        if not shift:
            # Replace primary with toggled direction
            cur_dir = None
            for c, asc in state:
                if c == col:
                    cur_dir = asc
                    break
            new_dir = (not cur_dir) if cur_dir is not None else True
            self._sort_state[tv] = [(col, new_dir)]
        else:
            # Add/replace secondary
            new_dir = True
            if col in existing:
                # toggle secondary
                self._sort_state[tv] = [(c, a) for (c, a) in state if c != col] + [(col, not dict(state).get(col, False))]
            else:
                self._sort_state[tv] = state + [(col, new_dir)]

        # Extract all rows â†’ Python
        items = []
        for iid in tv.get_children(""):
            rowvals = {c: tv.set(iid, c) for c in tv["columns"]}
            items.append((iid, rowvals))

        # Normalizer: numbers sort numerically; everything else case-insensitive
        def _norm(v):
            if v in (None, ""):
                return ""  # empty first
            try:
                return float(v)
            except Exception:
                return str(v).lower()

        # Comparator that respects (column, asc_bool) chains
        from functools import cmp_to_key
        def _compare(a, b):
            a_vals, b_vals = a[1], b[1]
            for col, asc in self._sort_state.get(tv, []):
                av = _norm(a_vals.get(col))
                bv = _norm(b_vals.get(col))
                if av < bv:
                    return -1 if asc else 1
                if av > bv:
                    return 1 if asc else -1
            return 0

        items.sort(key=cmp_to_key(_compare))

        # Reinsert in the new order
        for iid, _ in items:
            tv.move(iid, "", "end")

    # ---------- Column visibility ----------

    def _apply_visible_columns(self, tv: ttk.Treeview):
        if not self.visible_cols:
            # show all
            for c in tv["columns"]:
                try:
                    tv.column(c, width=tv.column(c, option="width"), stretch=False)  # keep width
                except Exception:
                    pass
            return
        vis = set(self.visible_cols)
        for c in tv["columns"]:
            if c in vis:
                # leave as is
                continue
            # hide visually by collapsing width
            tv.column(c, width=0, stretch=False)

    def _open_column_manager(self):
        cols = list(getattr(self, "ALL_COLS", self.ENGINE_COLS))
        win = tk.Toplevel(self._parent_toplevel())
        win.title("Select columns (applies to all tabs)")
        win.transient(self._parent_toplevel()); win.grab_set()

        frm = ttk.Frame(win); frm.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        vars_map: Dict[str, tk.BooleanVar] = {}
        current = set(self.visible_cols or cols)

        for i, c in enumerate(cols):
            var = tk.BooleanVar(value=(c in current))
            ttk.Checkbutton(frm, text=c, variable=var).grid(row=i//3, column=i%3, sticky="w", padx=6, pady=4)
            vars_map[c] = var

        btns = ttk.Frame(win); btns.pack(fill=tk.X, padx=10, pady=(8,10))
        def accept():
            sel = [k for k, v in vars_map.items() if v.get()]
            if not sel:
                sel = cols[:]  # never allow empty: fallback to all
            self.visible_cols = sel
            self._rebuild_table_columns()
            # re-fill data currently known
            self._refresh_all_subtabs()
            self._refresh_results_table()
            win.destroy()
        ttk.Button(btns, text="OK", command=accept).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side=tk.RIGHT, padx=(0,8))

    # ---------- Tooltip (abstract on hover) ----------

    def _ensure_tooltip_bindings(self, tv: ttk.Treeview):
        tv.bind("<Motion>", lambda e, _tv=tv: self._on_tv_motion(_tv, e), add="+")
        tv.bind("<Leave>", lambda e: self._hide_tooltip(), add="+")
        tv.bind("<Button-1>", lambda e: self._hide_tooltip(), add="+")
        tv.bind("<MouseWheel>", lambda e: self._hide_tooltip(), add="+")

    def _on_tv_motion(self, tv: ttk.Treeview, event):
        # Show tooltip if hovering abstract cell
        region = tv.identify("region", event.x, event.y)
        if region != "cell":
            self._hide_tooltip(); return
        row_id = tv.identify_row(event.y)
        col_id = tv.identify_column(event.x)
        if not row_id or not col_id:
            self._hide_tooltip(); return
        col_index = int(col_id.replace("#","")) - 1
        try:
            colname = tv["columns"][col_index]
        except Exception:
            self._hide_tooltip(); return
        if colname != "abstract":
            self._hide_tooltip(); return
        text = tv.set(row_id, "abstract") or ""
        if not text:
            self._hide_tooltip(); return
        self._show_tooltip(tv, event.x_root+12, event.y_root+10, text)

    def _show_tooltip(self, tv: ttk.Treeview, x: int, y: int, text: str):
        try:
            if not self._tooltip:
                self._tooltip = tk.Toplevel(self._parent_toplevel())
                self._tooltip.wm_overrideredirect(True)
                self._tooltip.attributes("-topmost", True)
                self._tooltip_label = tk.Label(self._tooltip, text="", justify="left", wraplength=480,
                                               background="#FFFFE0", relief="solid", borderwidth=1)
                self._tooltip_label.pack(padx=6, pady=4)
            self._tooltip_label.configure(text=text[:4000])  # safety
            self._tooltip.geometry(f"+{x}+{y}")
            self._tooltip.deiconify()
            self._tooltip_active_tv = tv
        except Exception:
            pass

    def _hide_tooltip(self):
        if self._tooltip:
            try:
                self._tooltip.withdraw()
            except Exception:
                pass
        self._tooltip_active_tv = None

    # ---------- Row value assembly (ENGINE + BIBLIO) ----------

    def _get_a_index_map(self) -> Dict[str, Dict[str, Any]]:
        if self._A_index:
            return self._A_index
        self._A_index = {str(d.get("a_id")): d for d in self.A if isinstance(d, dict) and d.get("a_id") is not None}
        return self._A_index

    def _row_to_all_values(self, r: Dict[str, Any]) -> Tuple[Any, ...]:
        """Return a tuple for ALL_COLS by merging engine fields from r and biblio fields from A-index."""
        # Engine part first
        engine_tuple = self._row_tuple_final(r)
        # Biblio part from A-index (fallback to r if present there)
        out: List[Any] = list(engine_tuple)
        a_map = self._get_a_index_map()
        aid = str(r.get("a_id"))
        src = a_map.get(aid, r)

        for c in self.BIBLIO_COLS:  # type: ignore[attr-defined]
            if c in self.ENGINE_COLS:
                continue
            out.append(src.get(c))
        return tuple(out)

    # --------- Gated flow helpers + refreshers ----------
    
    def _reset_gated_flow(self):
        self.stage_caches = {}
        self._el_survivor_ids = []
        self._gate_eh_done = False
        self._gate_ih_done = False
        self._gate_el_done = False
        self._refresh_eh_tab([])
        self._refresh_ih_tab([], {})
        self._refresh_el_tab([])
        self.final_rows = []
        self._refresh_results_table()
        self._update_stage_buttons()
        self.log("[RUN] Staged flow reset.\n")
    
    def _update_stage_buttons(self):
        # EH always enabled (when controls enabled)
        if hasattr(self, "btn_eh") and self.btn_eh:
            self.btn_eh.configure(state="normal")
        # IH requires EH
        if hasattr(self, "btn_ih") and self.btn_ih:
            self.btn_ih.configure(state="normal" if self._gate_eh_done else "disabled")
        # EL requires EH + IH
        if hasattr(self, "btn_el") and self.btn_el:
            self.btn_el.configure(state="normal" if (self._gate_eh_done and self._gate_ih_done) else "disabled")
        # IL requires EH + IH only (EL optional)
        if hasattr(self, "btn_il") and self.btn_il:
            self.btn_il.configure(state="normal" if (self._gate_eh_done and self._gate_ih_done) else "disabled")
    
    def _refresh_all_subtabs(self):
        """Re-render E/H, I/H, E/L with current 'all-items' toggle."""
        # When final rows exist, theyâ€™re the best source of truth
        if getattr(self, "final_rows", None):
            self._refresh_eh_tab(getattr(self, "_eh_dropped_rows", []))
            self._refresh_ih_tab(getattr(self, "_ih_survivor_ids", []), getattr(self, "_ih_h_pass_map", {}))
            self._refresh_el_tab(getattr(self, "_el_dropped_rows", []), getattr(self, "_el_survivor_ids", []))
            return
        # Otherwise use stage caches (preview mode)
        self._refresh_eh_tab(getattr(self, "_eh_dropped_rows", []))
        self._refresh_ih_tab(getattr(self, "_ih_survivor_ids", []), getattr(self, "_ih_h_pass_map", {}))
        self._refresh_el_tab(getattr(self, "_el_dropped_rows", []), getattr(self, "_el_survivor_ids", []))

    def _row_tuple_final(self, r: Dict[str, Any]) -> tuple:
        # helper to render one row in RES_COLS order
        score = f"{float(r.get('score', 0.0)):.3f}"
        pass_thr = r.get("pass_thr"); border_thr = r.get("border_thr")
        if pass_thr is None and self.var_pass is not None:
            pass_thr = float(self.var_pass.get())
        if border_thr is None and self.var_border is not None:
            border_thr = float(self.var_border.get())
        pass_thr_s = "" if pass_thr is None else f"{float(pass_thr):.2f}"
        border_thr_s = "" if border_thr is None else f"{float(border_thr):.2f}"
        return (
            r.get("a_id"),
            r.get("title"),
            score,
            r.get("label"),
            r.get("lang"),
            r.get("doc_type"),
            r.get("year"),
            r.get("venue"),
            "yes" if r.get("h_pass") else "no",
            "yes" if r.get("l_pass") else "no",
            r.get("random_seed_used"),
            pass_thr_s,
            border_thr_s,
            "yes" if r.get("hard_stop_triggered") else "no",
            r.get("hard_stop_criterion_id"),
            r.get("hard_stop_criterion_label"),
        )

    def _refresh_eh_tab(self, dropped_rows: List[Dict[str, Any]]):
        if not self.tv_eh: return
        self.tv_eh.delete(*self.tv_eh.get_children())

        allview = bool(self.var_allview.get()) if self.var_allview else False

        # If we have final rows, prefer them
        if getattr(self, "final_rows", None):
            rows = list(self.final_rows)
            if allview:
                # Sort: H-fails first, then the rest
                rows.sort(key=lambda r: (0 if not r.get("h_pass") else 1, str(r.get("a_id"))))
                for r in rows:
                    self.tv_eh.insert("", tk.END, values=self._row_to_all_values(r))
            else:
                for r in (fr for fr in rows if not fr.get("h_pass")):
                    self.tv_eh.insert("", tk.END, values=self._row_to_all_values(r))
            return

        # Preview mode (no final rows): build from caches
        title_map = {str(it.get("a_id")): (it.get("title") or "") for it in self.A}
        dropped_ids = {str(dr.get("a_id")) for dr in (dropped_rows or [])}
        survivors = []
        try:
            survivors = (self.stage_caches.get("EH") or {}).get("survivors_after_EH_ids") or []
        except Exception:
            survivors = []
        survivor_ids = {str(x) for x in survivors}

        def make_row(aid: str) -> tuple:
            h_pass = (False if aid in dropped_ids else (True if aid in survivor_ids else None))
            minimal = {
                "a_id": aid,
                "title": title_map.get(aid, ""),
                "score": 0.0,
                "label": "fail" if h_pass is False else "borderline",
                "lang": None, "doc_type": None, "year": None, "venue": None,
                "h_pass": h_pass, "l_pass": None,
                "random_seed_used": None,
                "pass_thr": self.var_pass.get() if self.var_pass else None,
                "border_thr": self.var_border.get() if self.var_border else None,
                "hard_stop_triggered": False,
                "hard_stop_criterion_id": None,
                "hard_stop_criterion_label": None,
            }
            return self._row_to_all_values(minimal)

        if allview:
            # Show ALL A-items, with H status inferred
            for it in self.A:
                aid = str(it.get("a_id"))
                self.tv_eh.insert("", tk.END, values=make_row(aid))
        else:
            # Affected only
            if dropped_ids:
                for aid in dropped_ids:
                    self.tv_eh.insert("", tk.END, values=make_row(aid))
            else:
                for aid in survivor_ids:
                    self.tv_eh.insert("", tk.END, values=make_row(aid))

    def _refresh_ih_tab(self, survivors_ids: List[str], h_pass_map: Dict[str, bool]):
        if not self.tv_ih: return
        self.tv_ih.delete(*self.tv_ih.get_children())

        allview = bool(self.var_allview.get()) if self.var_allview else False

        if getattr(self, "final_rows", None):
            rows = list(self.final_rows)
            if allview:
                # Sort: H-survivors first
                rows.sort(key=lambda r: (0 if r.get("h_pass") else 1, str(r.get("a_id"))))
                for r in rows:
                    self.tv_ih.insert("", tk.END, values=self._row_to_all_values(r))
            else:
                for r in (fr for fr in rows if fr.get("h_pass")):
                    self.tv_ih.insert("", tk.END, values=self._row_to_all_values(r))
            return

        # Preview mode
        if not survivors_ids:
            try:
                survivors_ids = (self.stage_caches.get("IH") or {}).get("survivors_after_IH_ids") or []
                h_pass_map = (self.stage_caches.get("IH") or {}).get("h_pass_map") or {}
            except Exception:
                survivors_ids = []
                h_pass_map = {}
        title_map = {str(it.get("a_id")): (it.get("title") or "") for it in self.A}
        survivor_ids = {str(x) for x in survivors_ids}

        def make_row(aid: str) -> tuple:
            h_pass = (True if aid in survivor_ids else h_pass_map.get(aid))
            if h_pass is None:
                h_pass = True if aid in survivor_ids else None
            minimal = {
                "a_id": aid,
                "title": title_map.get(aid, ""),
                "score": 0.0,
                "label": "borderline" if h_pass else "fail",
                "lang": None, "doc_type": None, "year": None, "venue": None,
                "h_pass": bool(h_pass) if h_pass is not None else None,
                "l_pass": None,
                "random_seed_used": None,
                "pass_thr": self.var_pass.get() if self.var_pass else None,
                "border_thr": self.var_border.get() if self.var_border else None,
                "hard_stop_triggered": False,
                "hard_stop_criterion_id": None,
                "hard_stop_criterion_label": None,
            }
            return self._row_to_all_values(minimal)

        if allview:
            for it in self.A:
                aid = str(it.get("a_id"))
                self.tv_ih.insert("", tk.END, values=make_row(aid))
        else:
            for aid in survivor_ids:
                self.tv_ih.insert("", tk.END, values=make_row(aid))

    def _refresh_el_tab(self, dropped_rows: List[Dict[str, Any]], survivors_ids: Optional[List[str]] = None):
        if not self.tv_el: return
        self.tv_el.delete(*self.tv_el.get_children())

        allview = bool(self.var_allview.get()) if self.var_allview else False

        if getattr(self, "final_rows", None):
            rows = list(self.final_rows)
            if allview:
                # Sort: (H-pass & L-fail) first
                rows.sort(key=lambda r: (0 if (r.get("h_pass") and not r.get("l_pass")) else 1, str(r.get("a_id"))))
                for r in rows:
                    self.tv_el.insert("", tk.END, values=self._row_to_all_values(r))
            else:
                for r in (fr for fr in rows if fr.get("h_pass") and not fr.get("l_pass")):
                    self.tv_el.insert("", tk.END, values=self._row_to_all_values(r))
            return

        # Preview mode
        title_map = {str(it.get("a_id")): (it.get("title") or "") for it in self.A}
        dropped_ids = {str(dr.get("a_id")) for dr in (dropped_rows or [])}
        if not survivors_ids:
            try:
                survivors_ids = (self.stage_caches.get("EL") or {}).get("survivors_after_EL_ids") \
                                or (self.stage_caches.get("EL") or {}).get("survivors_after_L_ids") \
                                or []
            except Exception:
                survivors_ids = []
        survivor_ids = {str(x) for x in (survivors_ids or [])}

        def make_row(aid: str) -> tuple:
            if aid in dropped_ids:
                h_pass = True
                l_pass = False
            elif aid in survivor_ids:
                h_pass = True
                l_pass = True
            else:
                h_pass = None
                l_pass = None
            minimal = {
                "a_id": aid,
                "title": title_map.get(aid, ""),
                "score": 0.0,
                "label": "fail" if (h_pass and l_pass is False) else "borderline",
                "lang": None, "doc_type": None, "year": None, "venue": None,
                "h_pass": h_pass, "l_pass": l_pass,
                "random_seed_used": None,
                "pass_thr": self.var_pass.get() if self.var_pass else None,
                "border_thr": self.var_border.get() if self.var_border else None,
                "hard_stop_triggered": False,
                "hard_stop_criterion_id": None,
                "hard_stop_criterion_label": None,
            }
            return self._row_to_all_values(minimal)

        if allview:
            for it in self.A:
                aid = str(it.get("a_id"))
                self.tv_el.insert("", tk.END, values=make_row(aid))
        else:
            if dropped_ids:
                for aid in dropped_ids:
                    self.tv_el.insert("", tk.END, values=make_row(aid))
            else:
                for aid in survivor_ids:
                    self.tv_el.insert("", tk.END, values=make_row(aid))

# ===== factory the hub imports =====

def create_plugin(app=None, *args, **kwargs):
    return MetadataTabPlugin(app)

# ===== standalone runner (optional) =====

def _standalone():
    root = tk.Tk()
    root.title("Screen A â€” Metadata-only (standalone)")
    root.geometry("1180x720")
    nb = ttk.Notebook(root)
    nb.pack(fill=tk.BOTH, expand=True)
    plugin = MetadataTabPlugin()
    plugin._root = root  # type: ignore[attr-defined]
    frame = plugin.build_tab(nb)
    nb.add(frame, text=plugin.meta.title)
    root.mainloop()

if __name__ == "__main__":
    _standalone()


