# -*- coding: utf-8 -*-
"""
Created on Sun Sep 21 14:55:23 2025

@author: alere
"""

# File: plugins/screen_A/ui_progress.py
# Progress widgets + demo orchestrator for Batch 0

from dataclasses import dataclass
from tkinter import ttk
import tkinter as tk
import threading
import time
import math
import queue


class StageName:
    INGEST = "Ingest Criteria"
    HARMONIZE = "Harmonize"
    METADATA = "Metadata Screen"
    FULLTEXT_FETCH = "Full-Text Fetch"
    FULLTEXT_SCREEN = "Full-Text Screen"
    DECISIONS_REPORTS = "Decisions/Reports"
    ALL = [INGEST, HARMONIZE, METADATA, FULLTEXT_FETCH, FULLTEXT_SCREEN, DECISIONS_REPORTS]


@dataclass
class StageEvent:
    stage: str
    state: str  # waiting|running|done|error|cancelled
    total: int
    done: int
    errors: int
    elapsed_s: float
    rate_ipm: float  # items per minute
    message: str = ""


class ProgressBox:
    def __init__(self, parent, title: str):
        self.title = title
        self.frame = ttk.LabelFrame(parent, text=title)
        self._start_ts = None

        # Widgets
        self._bar = ttk.Progressbar(self.frame, mode="determinate", length=220)
        self._bar.grid(row=0, column=0, columnspan=2, padx=8, pady=(8,2), sticky="we")

        self._lab_proc = ttk.Label(self.frame, text="Processed: 0 / 0")
        self._lab_stat = ttk.Label(self.frame, text="Status: Idle")
        self._lab_time = ttk.Label(self.frame, text="Elapsed: 00:00:00")
        self._lab_rate = ttk.Label(self.frame, text="Rate: 0.0 items/min")
        self._lab_errs = ttk.Label(self.frame, text="Errors: 0")

        self._lab_proc.grid(row=1, column=0, sticky="w", padx=8)
        self._lab_stat.grid(row=1, column=1, sticky="e", padx=8)
        self._lab_time.grid(row=2, column=0, sticky="w", padx=8)
        self._lab_rate.grid(row=2, column=1, sticky="e", padx=8)
        self._lab_errs.grid(row=3, column=0, sticky="w", padx=8, pady=(0,8))

        for c in range(2):
            self.frame.columnconfigure(c, weight=1)

        self.reset()

    def reset(self):
        self._bar.configure(value=0, maximum=100)
        self._lab_proc.configure(text="Processed: 0 / 0")
        self._lab_stat.configure(text="Status: Idle")
        self._lab_time.configure(text="Elapsed: 00:00:00")
        self._lab_rate.configure(text="Rate: 0.0 items/min")
        self._lab_errs.configure(text="Errors: 0")
        self._start_ts = None

    def update_with_event(self, ev: StageEvent):
        if ev.state == "running" and self._start_ts is None:
            self._start_ts = time.time()
        if ev.state in ("done", "error", "cancelled") and self._start_ts is None:
            self._start_ts = time.time()

        # Progress
        total = max(ev.total, 1)
        pct = max(0, min(100, int(ev.done * 100 / total)))
        self._bar.configure(maximum=100, value=pct)
        self._lab_proc.configure(text=f"Processed: {ev.done} / {ev.total}")

        # Status
        status_txt = {
            "waiting": "Idle",
            "running": "Running",
            "done": "Done",
            "error": "Error",
            "cancelled": "Cancelled",
        }.get(ev.state, "Idle")
        self._lab_stat.configure(text=f"Status: {status_txt}")

        # Elapsed
        elapsed = int(ev.elapsed_s)
        hh, mm = divmod(elapsed, 3600)
        mm, ss = divmod(mm, 60)
        self._lab_time.configure(text=f"Elapsed: {hh:02d}:{mm:02d}:{ss:02d}")

        # Rate & errors
        self._lab_rate.configure(text=f"Rate: {ev.rate_ipm:.1f} items/min")
        self._lab_errs.configure(text=f"Errors: {ev.errors}")


class StageOrchestrator:
    """Demo-only orchestrator that simulates a realistic run across all stages.
    Later batches will reuse this skeleton and emit real events from worker threads.
    """
    def __init__(self, out_q: "queue.Queue[StageEvent]"):
        self.out_q = out_q
        self._thr = None
        self._cancel = False
        self.is_running = False

    def start_demo_run(self):
        if self.is_running:
            return
        self._cancel = False
        self._thr = threading.Thread(target=self._demo, daemon=True)
        self._thr.start()
        self.is_running = True

    def cancel(self):
        self._cancel = True

    # ---- helpers ----
    def _emit(self, stage: str, state: str, total: int, done: int, errors: int, t0: float, message: str = ""):
        elapsed = time.time() - t0
        rate = (done / elapsed * 60) if elapsed > 0 else 0.0
        self.out_q.put(StageEvent(stage, state, total, done, errors, elapsed, rate, message))

    def _phase(self, name: str, n_items: int, step_s: float = 0.15, err_every: int | None = None):
        t0 = time.time()
        self._emit(name, "running", n_items, 0, 0, t0, "start")
        errors = 0
        done = 0
        for i in range(n_items):
            if self._cancel:
                self._emit(name, "cancelled", n_items, done, errors, t0, "cancelled")
                return False
            time.sleep(step_s)
            done += 1
            if err_every and (i + 1) % err_every == 0:
                errors += 1
                self._emit(name, "running", n_items, done, errors, t0, f"warn: item {i+1} minor error")
            else:
                self._emit(name, "running", n_items, done, errors, t0, f"item {i+1} processed")
        self._emit(name, "done", n_items, done, errors, t0, "done")
        return True

    def _demo(self):
        # Simulate a small run across all stages
        plan = [
            (StageName.INGEST, 8, 0.08, None),
            (StageName.HARMONIZE, 8, 0.10, None),
            (StageName.METADATA, 30, 0.05, 11),
            (StageName.FULLTEXT_FETCH, 30, 0.06, 7),
            (StageName.FULLTEXT_SCREEN, 18, 0.07, 6),
            (StageName.DECISIONS_REPORTS, 30, 0.04, None),
        ]
        for name, total, step, err_every in plan:
            if not self._phase(name, total, step_s=step, err_every=err_every):
                self.is_running = False
                return
        self.is_running = False
