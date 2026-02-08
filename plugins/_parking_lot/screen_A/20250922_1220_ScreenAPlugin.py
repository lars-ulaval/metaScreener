# -*- coding: utf-8 -*-
"""
Created on Sun Sep 21 14:54:02 2025

@author: alere
"""

# File: plugins/screen_A/ScreenAPlugin.py
# Batch 0 — Scaffold with Diagnostics tab + explicit progress boxes (demo mode)

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
    """
    Batch 0 UI goals:
      - Notebook scaffold with tabs: Criteria | Metadata Screen | Full-Text Screen | Decisions | Reports | Diagnostics
      - Progress area (2x3 grid) with explicit boxes and a quick status ribbon
      - Diagnostics log with "Log to file" checkbox (file writing will be wired in later batches)
      - Demo run simulating progress events so we can validate UX before wiring real engines
    """

    def __init__(self, app, meta: PluginMeta):
        super().__init__(app, meta)
        self._event_q: "queue.Queue[StageEvent]" = queue.Queue()
        self._orchestrator = None  # type: StageOrchestrator | None
        self._pump_id = None
        self._log_to_file_var = tk.BooleanVar(value=False)

        # important: UI root for tk.after scheduling (BasePlugin is not a widget)
        self._ui_root: ttk.Frame | None = None

        # map stage -> ProgressBox
        self._boxes = {}

    # ---------------- UI -----------------
    def build_tab(self, parent):
        root = ttk.Frame(parent, padding=12)
        self._ui_root = root  # <- use this for .after()

        # Header / Controls
        top = ttk.Frame(root)
        top.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(top, text=PLUGIN_TITLE, style="Headline.TLabel").pack(side=tk.LEFT)

        btns = ttk.Frame(top)
        btns.pack(side=tk.RIGHT)
        ttk.Button(btns, text="Start demo", command=self._on_start_demo).pack(side=tk.LEFT)
        ttk.Button(btns, text="Stop", command=self._on_stop).pack(side=tk.LEFT, padx=(6,0))
        ttk.Checkbutton(btns, text="Log to file", variable=self._log_to_file_var).pack(side=tk.LEFT, padx=(12,0))

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

        # Create boxes in fixed order
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
        self._tab_ft = self._make_tab(nb, "Full-Text Screen")
        self._tab_decisions = self._make_tab(nb, "Decisions")
        self._tab_reports = self._make_tab(nb, "Reports")
        self._tab_diag = self._make_diag_tab(nb)

        # Start pumping UI events
        self._schedule_pump()
        return root

    def _make_tab(self, nb, title):
        f = ttk.Frame(nb)
        nb.add(f, text=title)
        ttk.Label(f, text=f"{title} — (batch 0 scaffold)").pack(anchor="w", padx=8, pady=8)
        return f

    # ----- Batch 2: Metadata tab -----
    def _make_metadata_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="Metadata Screen")

        controls = ttk.Frame(f)
        controls.pack(side=tk.TOP, fill=tk.X, padx=8, pady=8)
        ttk.Button(controls, text="Load A (CSV/XLSX)", command=self._on_load_A).pack(side=tk.LEFT)
        ttk.Button(controls, text="Run metadata screening", command=self._on_run_metadata).pack(side=tk.LEFT, padx=6)

        # Thresholds
        thr = ttk.Frame(f)
        thr.pack(side=tk.TOP, fill=tk.X, padx=8)
        ttk.Label(thr, text="Pass ≥").pack(side=tk.LEFT)
        self._thr_pass = tk.DoubleVar(value=0.60)
        tk.Spinbox(thr, from_=0.0, to=1.0, increment=0.05, textvariable=self._thr_pass, width=5).pack(side=tk.LEFT)
        ttk.Label(thr, text=" | Borderline lower bound:").pack(side=tk.LEFT)
        self._thr_border = tk.DoubleVar(value=0.40)
        tk.Spinbox(thr, from_=0.0, to=1.0, increment=0.05, textvariable=self._thr_border, width=5).pack(side=tk.LEFT)

        # Results table
        cols = ("a_id","doi","title","score","label")
        tv = ttk.Treeview(f, columns=cols, show="headings", height=12)
        heads = {
            "a_id":"A id","doi":"DOI","title":"Title","score":"Score","label":"Label"
        }
        widths = {"a_id":80,"doi":160,"title":420,"score":70,"label":110}
        for c in cols:
            tv.heading(c, text=heads[c])
            tv.column(c, width=widths[c], stretch=(c=="title"))
        tv.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(6,6))
        self._meta_table = tv

        # Per-criterion details
        det = ttk.LabelFrame(f, text="Per-criterion scores (selected item)")
        det.pack(side=tk.TOP, fill=tk.BOTH, expand=False, padx=8, pady=(0,8))
        dcols = ("criterion_id","type","weight","score","matched")
        dtv = ttk.Treeview(det, columns=dcols, show="headings", height=6)
        for c in dcols:
            dtv.heading(c, text=c)
            dtv.column(c, width=120, stretch=True)
        dtv.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6, pady=6)
        self._meta_details = dtv

        self._meta_table.bind("<<TreeviewSelect>>", self._on_meta_select)
        return f

    def _on_load_A(self):
        from tkinter import filedialog, messagebox
        from .screen_metadata import parse_A_csv_xlsx
        path = filedialog.askopenfilename(
            title="Open A items (CSV/XLSX)",
            filetypes=[("CSV/XLSX","*.csv;*.xlsx;*.xls"),("All","*.*")]
        )
        if not path:
            return
        try:
            self._A_items = parse_A_csv_xlsx(path)
            self._append_log(f"Loaded {len(self._A_items)} A items from {path}")
        except Exception as e:
            messagebox.showerror("Load error", str(e))

    def _on_run_metadata(self):
        from .screen_metadata import screen_metadata
        # gather criteria from the table (already harmonized)
        crits = []
        for iid in self._criteria_table.get_children():
            vals = self._criteria_table.item(iid, "values")
            crits.append({
                "id": vals[0],
                "type": vals[1],
                "scope": vals[2],
                "label": vals[3],
                "targets": [t.strip() for t in str(vals[4]).split(",") if t.strip()],
                "operators": [o.strip() for o in str(vals[5]).split(",") if o.strip()],
                "weight": float(vals[6]),
                "threshold": float(vals[7]),
            })
        if not crits:
            self._append_log("No criteria available. Harmonize first.")
            return
        A = getattr(self, "_A_items", [])
        if not A:
            self._append_log("No A items loaded. Load CSV/XLSX first.")
            return

        # Progress start
        import time
        t0 = time.time()
        total = len(A)
        done = 0
        self._meta_table.delete(*self._meta_table.get_children())
        self._event_q.put(StageEvent(StageName.METADATA, "running", total, done, 0, 0.0, 0.0, "start"))

        pass_thr = float(self._thr_pass.get())
        border_thr = float(self._thr_border.get())

        self._meta_results = []  # store detailed results for selection view

        for item in A:
            res = screen_metadata(item, crits, pass_thr=pass_thr, border_thr=border_thr)
            self._meta_results.append(res)
            done += 1
            # Insert into table (truncate title for display)
            title = (item.get("title") or "").strip()
            if len(title) > 120:
                title = title[:117] + "…"
            self._meta_table.insert("", "end", values=(
                item.get("a_id") or item.get("id") or done,
                item.get("doi") or "",
                title,
                f"{res['score']:.2f}",
                res['label']
            ))
            elapsed = time.time()-t0
            rate = (done/elapsed*60) if elapsed>0 else 0.0
            self._event_q.put(StageEvent(StageName.METADATA, "running", total, done, 0, elapsed, rate, f"A item {done}"))

        elapsed = time.time()-t0
        rate = (done/elapsed*60) if elapsed>0 else 0.0
        self._event_q.put(StageEvent(StageName.METADATA, "done", total, done, 0, elapsed, rate, "done"))

    def _on_meta_select(self, *_):
        sel = self._meta_table.selection()
        if not sel:
            return
        idx = self._meta_table.index(sel[0])
        res = (self._meta_results[idx] if 0 <= idx < len(self._meta_results) else None)
        if not res:
            return
        self._meta_details.delete(*self._meta_details.get_children())
        for pc in res.get("per_criterion", []):
            self._meta_details.insert("", "end", values=(
                pc.get("id"), pc.get("type"), f"{pc.get('weight',1.0):.2f}", f"{pc.get('score',0.0):.2f}", pc.get("matched")
            ))
        self._append_log(f"Selected A item shows {len(res.get('per_criterion',[]))} per-criterion entries")

    def _make_diag_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="Diagnostics")
        self._log_text = tk.Text(f, wrap="word")
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(f, orient="vertical", command=self._log_text.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._log_text.configure(yscrollcommand=sb.set)
        return f

    # ----- Batch 1: Criteria tab -----
    def _make_criteria_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="Criteria")

        # Controls row
        row = ttk.Frame(f)
        row.pack(side=tk.TOP, fill=tk.X, padx=8, pady=8)
        ttk.Button(row, text="Paste criteria", command=self._on_paste_criteria).pack(side=tk.LEFT)
        ttk.Button(row, text="Load CSV/XLSX", command=self._on_load_csv).pack(side=tk.LEFT, padx=6)
        ttk.Button(row, text="Harmonize", command=self._on_harmonize).pack(side=tk.LEFT, padx=6)

        # Raw input (multiline text)
        self._criteria_input = tk.Text(f, height=6)
        self._criteria_input.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(0,8))

        # Table for harmonized criteria
        cols = ("id","type","scope","label","targets","operators","weight","threshold")
        tv = ttk.Treeview(f, columns=cols, show="headings", height=10)
        for c in cols:
            tv.heading(c, text=c)
            tv.column(c, width=120 if c!="label" else 280, stretch=True)
        tv.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(0,8))
        self._criteria_table = tv

        return f

    def _on_paste_criteria(self):
        try:
            self._criteria_input.focus_set()
        except Exception:
            pass

    def _on_load_csv(self):
        from tkinter import filedialog, messagebox
        path = filedialog.askopenfilename(
            title="Open criteria CSV/XLSX",
            filetypes=[("CSV/XLSX","*.csv;*.xlsx;*.xls"),("All","*.*")]
        )
        if not path:
            return
        try:
            rows = parse_csv_or_xlsx(path)
            self._pending_rows = rows
            self._append_log(f"Loaded {len(rows)} rows from {path}")
        except Exception as e:
            messagebox.showerror("Load error", str(e))

    def _on_harmonize(self):
        # Emit progress events to the HARMONIZE box
        import time
        t0 = time.time()
        txt = self._criteria_input.get("1.0","end").strip()
        rows = getattr(self, "_pending_rows", None)
        if txt and rows:
            # merge: text lines + file rows
            crits = harmonize_from_rows(rows) + harmonize_from_free_text(txt)
        elif rows:
            crits = harmonize_from_rows(rows)
        else:
            crits = harmonize_from_free_text(txt)
        total = len(crits)
        done = 0
        self._event_q.put(StageEvent(StageName.HARMONIZE, "running", total, done, 0, 0.0, 0.0, "start"))
        # Populate table progressively
        self._criteria_table.delete(*self._criteria_table.get_children())
        for c in crits:
            done += 1
            self._criteria_table.insert("", "end", values=(
                c.id, c.type, c.scope, c.label, ",".join(c.targets), ",".join(c.operators), c.weight, c.threshold
            ))
            elapsed = time.time()-t0
            rate = (done/elapsed*60) if elapsed>0 else 0.0
            self._event_q.put(StageEvent(StageName.HARMONIZE, "running", total, done, 0, elapsed, rate, f"added {c.id}"))
        elapsed = time.time()-t0
        rate = (done/elapsed*60) if elapsed>0 else 0.0
        self._event_q.put(StageEvent(StageName.HARMONIZE, "done", total, done, 0, elapsed, rate, "done"))

    # ------------- Demo orchestration --------------
    def _on_start_demo(self):
        if self._orchestrator and self._orchestrator.is_running:
            self._append_log("A run is already in progress. Click Stop to cancel.")
            return
        # Clear boxes & ribbon
        for name, box in self._boxes.items():
            box.reset()
            self._set_ribbon(name, "waiting")
        self._append_log("Starting demo run…")
        self._orchestrator = StageOrchestrator(self._event_q)
        self._orchestrator.start_demo_run()

    def _on_stop(self):
        if self._orchestrator:
            self._orchestrator.cancel()
            self._append_log("Cancellation requested.")

    # ------------- Event pump ----------------------
    def _schedule_pump(self):
        if self._ui_root is not None:
            self._pump_id = self._ui_root.after(80, self._pump_events)

    def _pump_events(self):
        try:
            while True:
                ev: StageEvent = self._event_q.get_nowait()
                # Update box
                box = self._boxes.get(ev.stage)
                if box:
                    box.update_with_event(ev)
                # Update ribbon
                self._set_ribbon(ev.stage, ev.state)
                # Log
                if ev.message:
                    self._append_log(f"[{ev.stage}] {ev.message}")
        except queue.Empty:
            pass
        finally:
            if self._ui_root is not None:
                self._ui_root.after(80, self._pump_events)

    def _set_ribbon(self, stage: str, state: str):
        lbl = self._ribbon_labels.get(stage)
        if not lbl:
            return
        icon = {
            "waiting": "◻",
            "running": "●",
            "done": "✅",
            "error": "⚠",
            "cancelled": "◻",
        }.get(state, "◻")
        lbl.configure(text=f"{icon} {stage}")

    def _append_log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self._log_text.insert(tk.END, f"[{ts}] {msg}")
        self._log_text.see(tk.END)


