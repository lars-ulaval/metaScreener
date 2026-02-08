# -*- coding: utf-8 -*-
"""
Created on Sun Sep 21 14:54:02 2025

@author: alere
"""

# File: plugins/screen_A/ScreenAPlugin.py
# Batches 0→6 — Adds performance controls + parallel fetching/screening

from tkinter import ttk
import tkinter as tk
import threading
import queue
import time

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
        
        ttk.Button(btns, text="Run end-to-end", command=self._on_run_e2e).pack(side=tk.LEFT, padx=(12,0))
        ttk.Button(btns, text="Resume from last", command=self._on_resume).pack(side=tk.LEFT, padx=(6,0))
        
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
        self._tab_criteria = self._make_criteria_tab(nb)
        self._tab_meta = self._make_metadata_tab(nb)
        self._tab_ft = self._make_fulltext_tab(nb)
        self._tab_decisions = self._make_tab(nb, "Decisions")
        self._tab_reports = self._make_tab(nb, "Reports")
        self._tab_diag = self._make_diag_tab(nb)

        # Start pumping UI events
        self._schedule_pump()
        return root

    def _make_tab(self, nb, title):
        f = ttk.Frame(nb)
        nb.add(f, text=title)
        ttk.Label(f, text=f"{title} — (batch scaffold)").pack(anchor="w", padx=8, pady=8)
        return f

    # ----- Batch 2: Metadata tab (unchanged from Batch 5) -----
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

    # ----- Batch 1: Criteria tab (unchanged) -----
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

    # ----- Batch 3 & 4: Full-Text tab (now with parallel options) -----
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

    # ----- Diagnostics tab -----
    def _make_diag_tab(self, nb):
        f = ttk.Frame(nb); nb.add(f, text="Diagnostics")
        self._log_text = tk.Text(f, wrap="word"); self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(f, orient="vertical", command=self._log_text.yview); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._log_text.configure(yscrollcommand=sb.set)
        return f

    # ----- Handlers (metadata & criteria same as Batch 5) -----
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
        import time
        t0 = time.time(); total = len(A); done = 0
        self._meta_table.delete(*self._meta_table.get_children())
        self._event_q.put(StageEvent(StageName.METADATA, "running", total, done, 0, 0.0, 0.0, "start"))
        pass_thr = float(self._thr_pass.get()); border_thr = float(self._thr_border.get())
        self._meta_results = []
        for item in A:
            res = screen_metadata(item, crits, pass_thr=pass_thr, border_thr=border_thr)
            self._meta_results.append(res)
            done += 1
            title = (item.get("title") or "").strip(); title = title[:117] + "…" if len(title)>120 else title
            self._meta_table.insert("", "end", values=(item.get("a_id") or item.get("id") or done, item.get("doi") or "", title, f"{res['score']:.2f}", res['label']))
            elapsed = time.time()-t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
            self._event_q.put(StageEvent(StageName.METADATA, "running", total, done, 0, elapsed, rate, f"A item {done}"))
        elapsed = time.time()-t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
        self._event_q.put(StageEvent(StageName.METADATA, "done", total, done, 0, elapsed, rate, "done"))

    def _on_paste_criteria(self):
        try: self._criteria_input.focus_set()
        except Exception: pass

    def _on_load_csv(self):
        from tkinter import filedialog, messagebox
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
        import time
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
        import time
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
                if ev.message: self._append_log(f"[{ev.stage}] {ev.message}\n")
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

    def _on_run_e2e(self):
        from threading import Thread
        from tkinter import messagebox
        try:
            # basic guardrails
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
