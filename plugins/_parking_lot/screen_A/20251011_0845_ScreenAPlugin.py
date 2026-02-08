# -*- coding: utf-8 -*-
"""
Consolidated ScreenAPlugin.py — Batches 0→7
Adds (LLM + Safe Funneling for Metadata):
 - Metadata LLM & Funneling panel with toggles/inputs
 - Sub-stage counters: gate-unknown, escalated, dropped-by-upper-bound
"""

from tkinter import ttk
import tkinter as tk
import queue
import time
import re
import math

from prisma_hub.plugin_api import PluginMeta, BasePlugin

# Local import (same folder)
from .ui_progress import ProgressBox, StageName, StageEvent, StageOrchestrator
# Batch 1
from .criteria_harmonizer import (
    harmonize_from_free_text,
    harmonize_from_rows,
    parse_csv_or_xlsx,
)

PLUGIN_ID = "screen_a"
PLUGIN_TITLE = "Screen A (auto inclusion/exclusion)"


def create_plugin(app):
    return ScreenAPlugin(app, PluginMeta(id=PLUGIN_ID, title=PLUGIN_TITLE))


class ScreenAPlugin(BasePlugin):
    def __init__(self, app, meta: PluginMeta):
        super().__init__(app, meta)
        self._event_q: "queue.Queue[StageEvent]" = queue.Queue()
        self._orchestrator = None  # type: StageOrchestrator | None
        self._pump_id = None
        self._log_to_file_var = tk.BooleanVar(value=False)

        # Performance settings (Batch 6)
        self._use_parallel = tk.BooleanVar(value=True)
        self._net_workers = tk.IntVar(value=8)
        self._cpu_workers = tk.IntVar(value=4)
        self._net_rate = tk.DoubleVar(value=4.0)  # tokens/sec

        # NEW: Metadata LLM & Funneling options
        self._use_llm_metadata = tk.BooleanVar(value=False)
        self._llm_model = tk.StringVar(value="gpt-4o-mini")
        self._llm_batch_size = tk.IntVar(value=12)     # items per batch (criterion-batched)
        self._llm_workers = tk.IntVar(value=8)         # max parallel LLM calls
        self._llm_trunc_chars = tk.IntVar(value=1500)  # abstract truncation (chars)
        self._safe_funneling = tk.BooleanVar(value=True)
        self._missing_fields_policy = tk.StringVar(value="unknown")  # "unknown" or "negative"
        self._early_escalate_sparse = tk.BooleanVar(value=False)

        # Sub-stage counters (auto-updated during metadata run)
        self._meta_gate_unknown = tk.StringVar(value="0")
        self._meta_escalated = tk.StringVar(value="0")
        self._meta_pruned_ub = tk.StringVar(value="0")

        self._ui_root: ttk.Frame | None = None
        self._boxes = {}

    # ---------------- UI -----------------
    def build_tab(self, parent):
        root = ttk.Frame(parent, padding=12)
        self._ui_root = root

        # Header / Controls
        top = ttk.Frame(root)
        top.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(top, text=PLUGIN_TITLE, style="Headline.TLabel").pack(side=tk.LEFT)

        btns = ttk.Frame(top); btns.pack(side=tk.RIGHT)
        ttk.Button(btns, text="Start demo", command=self._on_start_demo).pack(side=tk.LEFT)
        ttk.Button(btns, text="Stop", command=self._on_stop).pack(side=tk.LEFT, padx=(6,0))
        ttk.Checkbutton(btns, text="Log to file", variable=self._log_to_file_var).pack(side=tk.LEFT, padx=(12,0))
        ttk.Button(btns, text="Run end-to-end", command=self._on_run_e2e).pack(side=tk.LEFT, padx=(12,0))
        ttk.Button(btns, text="Resume from last", command=self._on_resume).pack(side=tk.LEFT, padx=(6,0))

        # Performance ribbon (Batch 6)
        perf = ttk.LabelFrame(root, text="Performance")
        perf.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(6,8))
        ttk.Checkbutton(perf, text="Use parallelism", variable=self._use_parallel).pack(side=tk.LEFT, padx=(0,12))
        ttk.Label(perf, text="Network workers").pack(side=tk.LEFT)
        tk.Spinbox(perf, from_=1, to=64, textvariable=self._net_workers, width=4).pack(side=tk.LEFT, padx=4)
        ttk.Label(perf, text="CPU workers").pack(side=tk.LEFT)
        tk.Spinbox(perf, from_=1, to=32, textvariable=self._cpu_workers, width=4).pack(side=tk.LEFT, padx=4)
        ttk.Label(perf, text="Net rate (t/s)").pack(side=tk.LEFT)
        tk.Spinbox(perf, from_=0, to=50, increment=0.5, textvariable=self._net_rate, width=5).pack(side=tk.LEFT, padx=4)

        # NEW: Metadata LLM & Funneling panel
        llm = ttk.LabelFrame(root, text="Metadata LLM & Funneling")
        llm.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(0,8))

        row1 = ttk.Frame(llm); row1.pack(side=tk.TOP, fill=tk.X, pady=2)
        ttk.Checkbutton(row1, text="Enable LLM for metadata", variable=self._use_llm_metadata).pack(side=tk.LEFT, padx=(0,12))
        ttk.Label(row1, text="Model").pack(side=tk.LEFT)
        ttk.Combobox(row1, textvariable=self._llm_model, width=18, values=[
            "gpt-4o-mini","gpt-4o","gpt-4.1-mini","gpt-4.1","o3-mini"
        ]).pack(side=tk.LEFT, padx=4)
        ttk.Label(row1, text="Batch size").pack(side=tk.LEFT)
        tk.Spinbox(row1, from_=4, to=32, textvariable=self._llm_batch_size, width=4).pack(side=tk.LEFT, padx=4)
        ttk.Label(row1, text="Max parallel calls").pack(side=tk.LEFT)
        tk.Spinbox(row1, from_=1, to=32, textvariable=self._llm_workers, width=4).pack(side=tk.LEFT, padx=4)

        row2 = ttk.Frame(llm); row2.pack(side=tk.TOP, fill=tk.X, pady=2)
        ttk.Label(row2, text="Abstract truncation (chars)").pack(side=tk.LEFT)
        tk.Spinbox(row2, from_=400, to=4000, increment=100, textvariable=self._llm_trunc_chars, width=6).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(row2, text="Safe funneling (upper-bound)", variable=self._safe_funneling).pack(side=tk.LEFT, padx=(12,12))
        ttk.Label(row2, text="Missing fields policy").pack(side=tk.LEFT)
        ttk.Combobox(row2, textvariable=self._missing_fields_policy, width=10, values=["unknown","negative"], state="readonly").pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(row2, text="Early escalate sparse items to full-text", variable=self._early_escalate_sparse).pack(side=tk.LEFT, padx=(12,0))

        # NEW: Sub-stage counters (read-only)
        stat = ttk.LabelFrame(root, text="Metadata sub-stage counters")
        stat.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(0,8))
        ttk.Label(stat, text="Gate unknown").pack(side=tk.LEFT, padx=(0,6))
        ttk.Label(stat, textvariable=self._meta_gate_unknown, width=6, relief=tk.SUNKEN, anchor="e").pack(side=tk.LEFT)
        ttk.Label(stat, text="  Escalated").pack(side=tk.LEFT, padx=(12,6))
        ttk.Label(stat, textvariable=self._meta_escalated, width=6, relief=tk.SUNKEN, anchor="e").pack(side=tk.LEFT)
        ttk.Label(stat, text="  Pruned by UB").pack(side=tk.LEFT, padx=(12,6))
        ttk.Label(stat, textvariable=self._meta_pruned_ub, width=6, relief=tk.SUNKEN, anchor="e").pack(side=tk.LEFT)

        # Status ribbon (compact overview)
        ribbon = ttk.Frame(root, padding=(0,8))
        ribbon.pack(side=tk.TOP, fill=tk.X)
        self._ribbon_labels = {}
        for key in StageName.ALL:
            lbl = ttk.Label(ribbon, text=f"◻ {key}")
            lbl.pack(side=tk.LEFT, padx=6)
            self._ribbon_labels[key] = lbl

        # Progress area (2x3 grid)
        grid = ttk.Frame(root)
        grid.pack(side=tk.TOP, fill=tk.X, pady=(6,8))
        order = [
            StageName.INGEST,
            StageName.HARMONIZE,
            StageName.METADATA,
            StageName.FULLTEXT_FETCH,
            StageName.FULLTEXT_SCREEN,
            StageName.DECISIONS_REPORTS,
        ]
        for i, name in enumerate(order):
            box = ProgressBox(grid, title=name)
            r, c = divmod(i, 3)
            box.frame.grid(row=r, column=c, padx=6, pady=6, sticky="nsew")
            grid.columnconfigure(c, weight=1)
            self._boxes[name] = box
        grid.rowconfigure(0, weight=0)
        grid.rowconfigure(1, weight=0)

        # Notebook
        nb = ttk.Notebook(root)
        nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._tab_criteria  = self._make_criteria_tab(nb)
        self._tab_meta      = self._make_metadata_tab(nb)
        self._tab_ft        = self._make_fulltext_tab(nb)
        self._tab_decisions = self._make_decisions_tab(nb)
        self._tab_reports   = self._make_reports_tab(nb)
        self._tab_diag      = self._make_diag_tab(nb)

        # Start pumping UI events
        self._schedule_pump()
        return root

    # ----- Generic scaffold fallback (not used for the real tabs) -----
    def _make_tab(self, nb, title):
        f = ttk.Frame(nb)
        nb.add(f, text=title)
        ttk.Label(f, text=f"{title} — (batch scaffold)").pack(anchor="w", padx=8, pady=8)
        return f

    # ----- Batch 2: Metadata tab -----
    def _make_metadata_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="Metadata Screen")
        controls = ttk.Frame(f); controls.pack(side=tk.TOP, fill=tk.X, padx=8, pady=8)
        ttk.Button(controls, text="Load A (CSV/XLSX)", command=self._on_load_A).pack(side=tk.LEFT)
        ttk.Button(controls, text="Run metadata screening", command=self._on_run_metadata).pack(side=tk.LEFT, padx=6)
        thr = ttk.Frame(f); thr.pack(side=tk.TOP, fill=tk.X, padx=8)
        ttk.Label(thr, text="Pass ≥").pack(side=tk.LEFT)
        self._thr_pass = tk.DoubleVar(value=0.60)
        tk.Spinbox(thr, from_=0.0, to=1.0, increment=0.05, textvariable=self._thr_pass, width=5).pack(side=tk.LEFT)
        ttk.Label(thr, text=" | Borderline lower bound:").pack(side=tk.LEFT)
        self._thr_border = tk.DoubleVar(value=0.40)
        tk.Spinbox(thr, from_=0.0, to=1.0, increment=0.05, textvariable=self._thr_border, width=5).pack(side=tk.LEFT)
        cols = ("a_id","doi","title","score","label")
        tv = ttk.Treeview(f, columns=cols, show="headings", height=12)
        heads = {"a_id":"A id","doi":"DOI","title":"Title","score":"Score","label":"Label"}
        widths = {"a_id":80,"doi":160,"title":420,"score":70,"label":110}
        for c in cols:
            tv.heading(c, text=heads[c]); tv.column(c, width=widths[c], stretch=(c=="title"))
        tv.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(6,6))
        self._meta_table = tv
        det = ttk.LabelFrame(f, text="Per-criterion scores (selected item)")
        det.pack(side=tk.TOP, fill=tk.BOTH, expand=False, padx=8, pady=(0,8))
        dcols = ("criterion_id","type","weight","score","matched")
        dtv = ttk.Treeview(det, columns=dcols, show="headings", height=6)
        for c in dcols:
            dtv.heading(c, text=c); dtv.column(c, width=120, stretch=True)
        dtv.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6, pady=6)
        self._meta_details = dtv
        self._meta_table.bind("<<TreeviewSelect>>", self._on_meta_select)
        return f

    # ----- Batch 1: Criteria tab -----
    def _make_criteria_tab(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Criteria")
        row = ttk.Frame(f); row.pack(side=tk.TOP, fill=tk.X, padx=8, pady=8)
        ttk.Button(row, text="Paste criteria", command=self._on_paste_criteria).pack(side=tk.LEFT)
        ttk.Button(row, text="Load CSV/XLSX", command=self._on_load_csv).pack(side=tk.LEFT, padx=6)
        ttk.Button(row, text="Harmonize", command=self._on_harmonize).pack(side=tk.LEFT, padx=6)
        self._criteria_input = tk.Text(f, height=6); self._criteria_input.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(0,8))
        cols = ("id","type","scope","label","targets","operators","weight","threshold")
        tv = ttk.Treeview(f, columns=cols, show="headings", height=10)
        for c in cols:
            tv.heading(c, text=c); tv.column(c, width=120 if c!="label" else 280, stretch=True)
        tv.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(0,8))
        self._criteria_table = tv
        return f

    # ----- Batch 3 & 4: Full-Text tab (with parallel options) -----
    def _make_fulltext_tab(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Full-Text Screen")
        controls = ttk.Frame(f); controls.pack(side=tk.TOP, fill=tk.X, padx=8, pady=8)
        ttk.Button(controls, text="Fetch full text for A", command=self._on_fetch_fulltext).pack(side=tk.LEFT)
        ttk.Button(controls, text="Run full-text screening", command=self._on_run_fulltext_screen).pack(side=tk.LEFT, padx=6)

        cols = ("a_id","doi","status","source","notes","path")
        tv = ttk.Treeview(f, columns=cols, show="headings", height=12)
        widths = {"a_id":80,"doi":160,"status":90,"source":100,"notes":260,"path":260}
        for c in cols:
            tv.heading(c, text=c); tv.column(c, width=widths[c], stretch=(c in ("notes","path")))
        tv.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(6,6))
        self._ft_table = tv

        det = ttk.LabelFrame(f, text="Full-text per-criterion (selected A)")
        det.pack(side=tk.TOP, fill=tk.BOTH, expand=False, padx=8, pady=(0,8))
        dcols = ("a_id","criterion_id","decision","confidence","evidence")
        dtv = ttk.Treeview(det, columns=dcols, show="headings", height=6)
        for c in dcols:
            dtv.heading(c, text=c); dtv.column(c, width=140, stretch=True)
        dtv.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6, pady=6)
        self._ft_details = dtv
        self._ft_table.bind("<<TreeviewSelect>>", self._on_ft_select)
        return f

    # ----- Decisions tab (Batch 5 UI restored) -----
    def _make_decisions_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="Decisions")
        controls = ttk.Frame(f); controls.pack(side=tk.TOP, fill=tk.X, padx=8, pady=8)
        ttk.Button(controls, text="Compute decisions", command=self._on_compute_decisions).pack(side=tk.LEFT)

        cols = ("a_id","title","meta_score","ft_avail","label","confidence")
        tv = ttk.Treeview(f, columns=cols, show="headings", height=12)
        heads  = {"a_id":"A id","title":"Title","meta_score":"Meta","ft_avail":"FT?","label":"Label","confidence":"Conf"}
        widths = {"a_id":80,"title":520,"meta_score":80,"ft_avail":60,"label":110,"confidence":80}
        for c in cols:
            tv.heading(c, text=heads[c]); tv.column(c, width=widths[c], stretch=(c=="title"))
        tv.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(6,6))
        self._dec_table = tv

        det = ttk.LabelFrame(f, text="Drivers & notes (selected)")
        det.pack(side=tk.TOP, fill=tk.BOTH, expand=False, padx=8, pady=(0,8))
        self._drivers = tk.Text(det, height=5, wrap="word"); self._drivers.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
        sb = ttk.Scrollbar(det, orient="vertical", command=self._drivers.yview); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._drivers.configure(yscrollcommand=sb.set)

        self._dec_table.bind("<<TreeviewSelect>>", self._on_dec_select)
        return f

    # ----- Reports tab (Batch 5 UI restored) -----
    def _make_reports_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="Reports")
        controls = ttk.Frame(f); controls.pack(side=tk.TOP, fill=tk.X, padx=8, pady=8)
        ttk.Button(controls, text="Export CSV",  command=self._on_export_csv).pack(side=tk.LEFT)
        ttk.Button(controls, text="Export XLSX", command=self._on_export_xlsx).pack(side=tk.LEFT, padx=6)
        ttk.Button(controls, text="Save charts", command=self._on_save_charts).pack(side=tk.LEFT, padx=6)

        self._report_text = tk.Text(f, height=10, wrap="word")
        self._report_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(0,8))
        return f

    # ----- Diagnostics tab -----
    def _make_diag_tab(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Diagnostics")
        self._log_text = tk.Text(f, wrap="word"); self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(f, orient="vertical", command=self._log_text.yview); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._log_text.configure(yscrollcommand=sb.set)
        return f

    # ----- Handlers: Criteria & Metadata -----
    def _on_load_A(self):
        from tkinter import filedialog, messagebox
        from .screen_metadata import parse_A_csv_xlsx
        path = filedialog.askopenfilename(title="Open A items (CSV/XLSX)", filetypes=[("CSV/XLSX","*.csv;*.xlsx;*.xls"),("All","*.*")])
        if not path: return
        try:
            self._A_items = parse_A_csv_xlsx(path)
            self._append_log(f"Loaded {len(self._A_items)} A items from {path}\n")
        except Exception as e:
            messagebox.showerror("Load error", str(e))

    def _on_run_metadata(self):
        """Legacy: local rules-only screening (quick preview). E2E uses LLM/funneling if enabled."""
        from .screen_metadata import screen_metadata
        crits = []
        for iid in self._criteria_table.get_children():
            vals = self._criteria_table.item(iid, "values")
            crits.append({
                "id": vals[0], "type": vals[1], "scope": vals[2], "label": vals[3],
                "targets": [t.strip() for t in str(vals[4]).split(",") if t.strip()],
                "operators": [o.strip() for o in str(vals[5]).split(",") if o.strip()],
                "weight": float(vals[6]), "threshold": float(vals[7]),
            })
        if not crits:
            self._append_log("No criteria available. Harmonize first.\n"); return
        A = getattr(self, "_A_items", [])
        if not A:
            self._append_log("No A items loaded. Load CSV/XLSX first.\n"); return
        t0 = time.time(); total = len(A); done = 0
        self._meta_table.delete(*self._meta_table.get_children())
        self._event_q.put(StageEvent(StageName.METADATA, "running", total, done, 0, 0.0, 0.0, "rules-only preview"))
        pass_thr = float(self._thr_pass.get()); border_thr = float(self._thr_border.get())
        self._meta_results = []
        for item in A:
            res = screen_metadata(item, crits, pass_thr=pass_thr, border_thr=border_thr)
            self._meta_results.append(res)
            done += 1
            raw_title = item.get("title") or item.get("ti") or ""
            # treat pandas NaN/float-as-NaN as empty
            try:
                if isinstance(raw_title, float) and math.isnan(raw_title):
                    raw_title = ""
            except Exception:
                pass
            title = str(raw_title).strip()
            title = title[:117] + "…" if len(title) > 120 else title
            self._meta_table.insert("", "end", values=(item.get("a_id") or item.get("id") or done, item.get("doi") or "", title, f"{res['score']:.2f}", res['label']))
            elapsed = time.time()-t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
            self._event_q.put(StageEvent(StageName.METADATA, "running", total, done, 0, elapsed, rate, f"A item {done}"))
        elapsed = time.time()-t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
        self._event_q.put(StageEvent(StageName.METADATA, "done", total, done, 0, elapsed, rate, "preview done"))

    def _on_paste_criteria(self):
        try: self._criteria_input.focus_set()
        except Exception: pass

    def _on_load_csv(self):
        from tkinter import filedialog, messagebox
        rows = []
        path = filedialog.askopenfilename(title="Open criteria CSV/XLSX", filetypes=[("CSV/XLSX","*.csv;*.xlsx;*.xls"),("All","*.*")])
        if not path: return
        try:
            rows = parse_csv_or_xlsx(path)
            self._pending_rows = rows
            self._append_log(f"Loaded {len(rows)} rows from {path}\n")
        except Exception as e:
            messagebox.showerror("Load error", str(e))

    def _on_harmonize(self):
        import time
        t0 = time.time(); txt = self._criteria_input.get("1.0","end").strip(); rows = getattr(self, "_pending_rows", None)
        if txt and rows: crits = harmonize_from_rows(rows) + harmonize_from_free_text(txt)
        elif rows: crits = harmonize_from_rows(rows)
        else: crits = harmonize_from_free_text(txt)
        total = len(crits); done = 0
        self._event_q.put(StageEvent(StageName.HARMONIZE, "running", total, done, 0, 0.0, 0.0, "start"))
        self._criteria_table.delete(*self._criteria_table.get_children())
        for c in crits:
            done += 1
            self._criteria_table.insert("", "end", values=(c.id, c.type, c.scope, c.label, ",".join(c.targets), ",".join(c.operators), c.weight, c.threshold))
            elapsed = time.time()-t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
            self._event_q.put(StageEvent(StageName.HARMONIZE, "running", total, done, 0, elapsed, rate, f"added {c.id}"))
        elapsed = time.time()-t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
        self._event_q.put(StageEvent(StageName.HARMONIZE, "done", total, done, 0, elapsed, rate, "done"))

    # ----- Batch 3 & 6: Fetch full text (parallel-aware) -----
    def _on_fetch_fulltext(self):
        A = getattr(self, "_A_items", [])
        if not A:
            self._append_log("No A items loaded. Load A in Metadata tab first.\n"); return
        use_parallel = bool(self._use_parallel.get()); net_workers = int(self._net_workers.get()); net_rate = float(self._net_rate.get())
        t0 = time.time(); total = len(A); done = 0
        self._ft_table.delete(*self._ft_table.get_children())
        self._event_q.put(StageEvent(StageName.FULLTEXT_FETCH, "running", total, done, 0, 0.0, 0.0, "start"))

        def on_progress(i, n, res):
            nonlocal done, t0
            done = i
            def _get(obj, k, default=""):
                return getattr(obj, k, default) if hasattr(obj, k) else (obj.get(k, default) if isinstance(obj, dict) else default)
            a_id = _get(res, 'a_id'); status = _get(res, 'status'); source = _get(res, 'source'); notes = _get(res, 'notes'); path = _get(res, 'path')
            doi = A[i-1].get('doi') if 0 <= i-1 < len(A) else ''
            self._ft_table.insert("", "end", values=(a_id, doi, status, source, notes, path))
            elapsed = time.time()-t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
            self._event_q.put(StageEvent(StageName.FULLTEXT_FETCH, "running", total, done, 0, elapsed, rate, f"A item {i}"))

        if use_parallel:
            from .fetch_fulltext_parallel import fetch_fulltext_for_items_parallel, configure_network_ratelimit
            configure_network_ratelimit(tokens_per_sec=net_rate)
            fetch_fulltext_for_items_parallel(A, max_workers=net_workers, progress_cb=on_progress)
        else:
            from .fetch_fulltext import fetch_fulltext_for_items
            fetch_fulltext_for_items(A, progress_cb=on_progress)

        elapsed = time.time()-t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
        self._event_q.put(StageEvent(StageName.FULLTEXT_FETCH, "done", total, done, 0, elapsed, rate, "done"))

    # ----- Batch 4 & 6: Full-text screening (parallel-aware) -----
    def _on_run_fulltext_screen(self):
        crits = []
        for iid in self._criteria_table.get_children():
            vals = self._criteria_table.item(iid, "values")
            crits.append({
                "id": vals[0], "type": vals[1], "scope": vals[2], "label": vals[3],
                "targets": [t.strip() for t in str(vals[4]).split(",") if t.strip()],
                "operators": [o.strip() for o in str(vals[5]).split(",") if o.strip()],
                "weight": float(vals[6]), "threshold": float(vals[7]),
            })
        if not crits:
            self._append_log("No criteria available. Harmonize first.\n"); return
        A = getattr(self, "_A_items", [])
        if not A:
            self._append_log("No A items loaded. Load CSV/XLSX first.\n"); return
        ft = []
        for iid in self._ft_table.get_children():
            a_id, doi, status, source, notes, path = self._ft_table.item(iid, "values")
            ft.append({"a_id": a_id, "status": status, "path": path})

        use_parallel = bool(self._use_parallel.get()); cpu_workers = int(self._cpu_workers.get())
        t0 = time.time(); total = len(A); done = 0
        self._event_q.put(StageEvent(StageName.FULLTEXT_SCREEN, "running", total, done, 0, 0.0, 0.0, "start"))
        self._ft_screen_results = []

        def on_progress(i, n, res):
            nonlocal done, t0
            done = i; self._ft_screen_results.append(res)
            elapsed = time.time()-t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
            self._event_q.put(StageEvent(StageName.FULLTEXT_SCREEN, "running", total, done, 0, elapsed, rate, f"A item {i}"))

        if use_parallel:
            from .screen_fulltext_parallel import screen_fulltext_parallel
            screen_fulltext_parallel(A, ft, crits, max_workers=cpu_workers, progress_cb=on_progress)
        else:
            from .screen_fulltext import screen_fulltext
            screen_fulltext(A, ft, crits, progress_cb=on_progress)

        elapsed = time.time()-t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
        self._event_q.put(StageEvent(StageName.FULLTEXT_SCREEN, "done", total, done, 0, elapsed, rate, "done"))

    # ----- Decisions & Reports handlers -----
    def _on_compute_decisions(self):
        from .decisions import aggregate_decisions
        A = getattr(self, "_A_items", [])
        if not A:
            self._append_log("No A items loaded.\n"); return
        meta = getattr(self, "_meta_results", [])
        ft   = getattr(self, "_ft_screen_results", [])
        pass_thr   = float(getattr(self, "_thr_pass",   tk.DoubleVar(value=0.6)).get())
        border_thr = float(getattr(self, "_thr_border", tk.DoubleVar(value=0.4)).get())

        total = len(A); done = 0; t0 = time.time()
        self._event_q.put(StageEvent(StageName.DECISIONS_REPORTS, "running", total, done, 0, 0.0, 0.0, "start"))

        recs = aggregate_decisions(A, meta, ft, pass_thr=pass_thr, border_thr=border_thr)
        self._decisions = recs
        self._dec_table.delete(*self._dec_table.get_children())
        for r in recs:
            done += 1
            title = r["title"][:120] + ("…" if len(r["title"])>120 else "")
            self._dec_table.insert("", "end", values=(r["a_id"], title, f"{r['meta_score']:.2f}",
                                                      "yes" if r["ft_available"] else "no",
                                                      r["label"], f"{r['confidence']:.2f}"))
            elapsed = time.time()-t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
            self._event_q.put(StageEvent(StageName.DECISIONS_REPORTS, "running", total, done, 0, elapsed, rate, f"A item {done}"))
        elapsed = time.time()-t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
        self._event_q.put(StageEvent(StageName.DECISIONS_REPORTS, "done", total, done, 0, elapsed, rate, "done"))

    def _on_dec_select(self, *_):
        sel = self._dec_table.selection()
        if not sel or not hasattr(self, "_decisions"):
            return
        idx = self._dec_table.index(sel[0])
        if idx >= len(self._decisions):
            return
        r = self._decisions[idx]
        self._drivers.delete("1.0", tk.END)
        self._drivers.insert(tk.END, f"Drivers: {', '.join(r.get('drivers') or [])}\nNotes: {r.get('notes') or ''}")

    def _on_export_csv(self):
        from tkinter import filedialog, messagebox
        from .reports import export_decisions_csv
        if not hasattr(self, "_decisions"):
            self._append_log("Compute decisions first.\n"); return
        path = filedialog.asksaveasfilename(title="Save CSV", defaultextension=".csv", filetypes=[("CSV","*.csv")])
        if not path: return
        try:
            export_decisions_csv(path, self._decisions)
            self._append_log(f"CSV exported to {path}\n")
        except Exception as e:
            messagebox.showerror("Export error", str(e))

    def _on_export_xlsx(self):
        from tkinter import filedialog, messagebox
        from .reports import export_decisions_xlsx
        if not hasattr(self, "_decisions"):
            self._append_log("Compute decisions first.\n"); return
        path = filedialog.asksaveasfilename(title="Save XLSX", defaultextension=".xlsx", filetypes=[("Excel","*.xlsx")])
        if not path: return
        try:
            export_decisions_xlsx(path, self._decisions)
            self._append_log(f"XLSX exported to {path}\n")
        except Exception as e:
            messagebox.showerror("Export error", str(e))

    def _on_save_charts(self):
        from .reports import prisma_counts, save_charts, default_report_dir
        if not hasattr(self, "_decisions"):
            self._append_log("Compute decisions first.\n"); return
        counts = prisma_counts(self._decisions)
        self._report_text.delete("1.0", tk.END)
        self._report_text.insert(tk.END, f"PRISMA counts -> total: {counts['total']}, include: {counts['include']}, exclude: {counts['exclude']}, needs-review: {counts['needs_review']}, insufficient: {counts['insufficient']}\n")
        outdir = default_report_dir()
        chart_paths = save_charts(outdir, self._decisions)
        for name, p in chart_paths.items():
            self._report_text.insert(tk.END, f"Saved {name}: {p}\n")
        if not chart_paths:
            self._report_text.insert(tk.END, "Matplotlib not available; charts skipped.\n")

    # ----- Diagnostics / selections -----
    def _make_diag_tab(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Diagnostics")
        self._log_text = tk.Text(f, wrap="word"); self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(f, orient="vertical", command=self._log_text.yview); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._log_text.configure(yscrollcommand=sb.set)
        return f

    def _on_meta_select(self, *_):
        sel = self._meta_table.selection()
        if not sel:
            return
        idx = self._meta_table.index(sel[0])
        res = (self._meta_results[idx] if 0 <= idx < len(getattr(self, "_meta_results", [])) else None)
        if not res:
            return
        self._meta_details.delete(*self._meta_details.get_children())
        # Render rule or fused score depending on what we have
        for pc in res.get("per_criterion", []):
            score = pc.get("fused_score", pc.get("score", 0.0))
            self._meta_details.insert("", "end", values=(pc.get("id"), pc.get("type"), f"{pc.get('weight',1.0):.2f}", f"{float(score):.2f}", pc.get("matched")))
        self._append_log(f"Selected A item shows {len(res.get('per_criterion',[]))} per-criterion entries\n")

    def _on_ft_select(self, *_):
        sel = self._ft_table.selection()
        if not sel:
            return
        a_id = self._ft_table.item(sel[0], "values")[0]
        # find full-text screen result for this a_id
        res = None
        for r in getattr(self, "_ft_screen_results", []) or []:
            ra = r.get("a_id") if isinstance(r, dict) else getattr(r, "a_id", None)
            if str(ra) == str(a_id):
                res = r; break
        self._ft_details.delete(*self._ft_details.get_children())
        if not res:
            return
        for d in res.get("per_criterion", []):
            evid = d.get("evidence") or []
            ev_txt = "; ".join([f"p{e.get('page')}: {e.get('text')}" for e in evid])
            self._ft_details.insert("", "end", values=(res.get("a_id"), d.get("criterion_id"), d.get("decision"), f"{float(d.get('confidence') or 0):.2f}", ev_txt))

    # ----- E2E / Resume (Batch 7) -----
    def _on_run_e2e(self):
        from threading import Thread
        from tkinter import messagebox
        try:
            if not hasattr(self, "_A_items") or not self._A_items:
                messagebox.showwarning("Missing input", "Load A items first (Metadata tab).")
                return
            from .pipeline_orchestrator import run_end_to_end
            def runner():
                try:
                    run_end_to_end(self, save_charts=True)
                except Exception as e:
                    self._append_log(f"E2E error: {e}\n")
            Thread(target=runner, daemon=True).start()
        except Exception as e:
            self._append_log(f"Cannot start E2E: {e}\n")

    def _on_resume(self):
        from threading import Thread
        from tkinter import messagebox
        try:
            if not hasattr(self, "_A_items") or not self._A_items:
                messagebox.showwarning("Missing input", "Load A items first (Metadata tab).")
                return
            from .pipeline_orchestrator import resume_from_last
            def runner():
                try:
                    resume_from_last(self)
                except Exception as e:
                    self._append_log(f"Resume error: {e}\n")
            Thread(target=runner, daemon=True).start()
        except Exception as e:
            self._append_log(f"Cannot start Resume: {e}\n")

    # ----- Boilerplate (demo, pump, logs) -----
    def _on_start_demo(self):
        if hasattr(self, "_orchestrator") and self._orchestrator and self._orchestrator.is_running:
            self._append_log("A run is already in progress. Click Stop to cancel.\n"); return
        for name, box in self._boxes.items():
            box.reset(); self._set_ribbon(name, "waiting")
        self._append_log("Starting demo run…\n")
        self._orchestrator = StageOrchestrator(self._event_q)
        self._orchestrator.start_demo_run()

    def _on_stop(self):
        if self._orchestrator:
            self._orchestrator.cancel(); self._append_log("Cancellation requested.\n")

    def _schedule_pump(self):
        if self._ui_root is not None:
            self._pump_id = self._ui_root.after(80, self._pump_events)

    def _pump_events(self):
        try:
            while True:
                ev: StageEvent = self._event_q.get_nowait()
                box = self._boxes.get(ev.stage)
                if box: box.update_with_event(ev)
                self._set_ribbon(ev.stage, ev.state)
                if ev.message:
                    self._append_log(f"[{ev.stage}] {ev.message}\n")
                    # Parse metadata sub-stage summaries to update counters
                    if ev.stage == StageName.METADATA:
                        # Example: "M0 done: gate_fail=12, gate_unknown=34, survivors=954"
                        m0 = re.search(r"gate_unknown=(\d+)", ev.message or "")
                        if m0:
                            self._meta_gate_unknown.set(m0.group(1))
                        # Example: "M1 done: pruned_by_upper_bound=77, escalated=15"
                        m1a = re.search(r"pruned_by_upper_bound=(\d+)", ev.message or "")
                        if m1a:
                            self._meta_pruned_ub.set(m1a.group(1))
                        m1b = re.search(r"escalated=(\d+)", ev.message or "")
                        if m1b:
                            self._meta_escalated.set(m1b.group(1))
        except queue.Empty:
            pass
        finally:
            if self._ui_root is not None:
                self._ui_root.after(80, self._pump_events)

    def _set_ribbon(self, stage: str, state: str):
        lbl = self._ribbon_labels.get(stage)
        if not lbl: return
        icon = {"waiting":"◻","running":"●","done":"✅","error":"⚠","cancelled":"◻"}.get(state, "◻")
        lbl.configure(text=f"{icon} {stage}")

    def _append_log(self, msg: str):
        ts = time.strftime("%H:%M:%S"); self._log_text.insert(tk.END, f"[{ts}] {msg}"); self._log_text.see(tk.END)
