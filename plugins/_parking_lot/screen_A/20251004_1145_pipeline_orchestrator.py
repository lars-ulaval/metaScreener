# -*- coding: utf-8 -*-
"""
Created on Mon Sep 22 18:07:18 2025

@author: alere
"""

# File: plugins/screen_A/pipeline_orchestrator.py
# Batch 7 — End-to-end orchestration with resume-friendly stages and richer diagnostics

from __future__ import annotations
from typing import Any, Dict, List
import time

from .ui_progress import StageName, StageEvent

# Utilities to read criteria from the plugin's table (shared with handlers)
def _read_criteria(plugin) -> List[Dict[str, Any]]:
    crits: List[Dict[str, Any]] = []
    for iid in plugin._criteria_table.get_children():
        vals = plugin._criteria_table.item(iid, "values")
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
    return crits


def run_end_to_end(plugin, *, save_charts: bool = True, export_csv_path: str | None = None):
    """Drive the whole pipeline using the plugin instance state.
    This function avoids touching UI tables (fast), but emits StageEvents and stores results on the plugin:
    - plugin._meta_results
    - plugin._ft_fetch_results (added)
    - plugin._ft_screen_results
    - plugin._decisions
    - plugin._last_report_dir (if charts saved)
    """
    # 0) Preconditions
    A = getattr(plugin, "_A_items", [])
    if not A:
        raise RuntimeError("No A items loaded. Use Metadata tab to load CSV/XLSX first.")
    crits = _read_criteria(plugin)
    if not crits:
        raise RuntimeError("No criteria available. Harmonize criteria first.")

    # 1) Metadata screening
    from .screen_metadata import screen_metadata
    t0 = time.time(); total = len(A); done = 0
    plugin._event_q.put(StageEvent(StageName.METADATA, "running", total, done, 0, 0.0, 0.0, "start (Batch 7)"))
    meta_results: List[Dict[str, Any]] = []
    pass_thr = float(getattr(plugin, "_thr_pass", 0.60).get() if hasattr(plugin, "_thr_pass") else 0.60)
    border_thr = float(getattr(plugin, "_thr_border", 0.40).get() if hasattr(plugin, "_thr_border") else 0.40)
    for item in A:
        res = screen_metadata(item, crits, pass_thr=pass_thr, border_thr=border_thr)
        meta_results.append(res)
        done += 1
        elapsed = time.time() - t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
        plugin._event_q.put(StageEvent(StageName.METADATA, "running", total, done, 0, elapsed, rate, f"A item {done}"))
    plugin._meta_results = meta_results
    elapsed = time.time() - t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
    plugin._event_q.put(StageEvent(StageName.METADATA, "done", total, done, 0, elapsed, rate, "done"))

    # 2) Full-text fetch (parallel-aware)
    use_parallel = bool(getattr(plugin, "_use_parallel", False).get()) if hasattr(plugin, "_use_parallel") else False
    net_workers = int(getattr(plugin, "_net_workers", 8).get()) if hasattr(plugin, "_net_workers") else 8
    net_rate = float(getattr(plugin, "_net_rate", 4.0).get()) if hasattr(plugin, "_net_rate") else 4.0
    t0 = time.time(); total = len(A); done = 0
    plugin._event_q.put(StageEvent(StageName.FULLTEXT_FETCH, "running", total, done, 0, 0.0, 0.0, "start (Batch 7)"))

    ft_fetch_results: List[Dict[str, Any]] = []
    def cb_fetch(i, n, res):
        nonlocal done, t0
        done = i; ft_fetch_results.append(res.to_dict() if hasattr(res, 'to_dict') else (res if isinstance(res, dict) else {"status":"error","notes":str(res)}))
        elapsed = time.time() - t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
        plugin._event_q.put(StageEvent(StageName.FULLTEXT_FETCH, "running", total, done, 0, elapsed, rate, f"A item {i}"))

    if use_parallel:
        from .fetch_fulltext_parallel import fetch_fulltext_for_items_parallel, configure_network_ratelimit
        configure_network_ratelimit(tokens_per_sec=net_rate)
        fetch_fulltext_for_items_parallel(A, max_workers=net_workers, progress_cb=cb_fetch)
    else:
        from .fetch_fulltext import fetch_fulltext_for_items
        fetch_fulltext_for_items(A, progress_cb=cb_fetch)

    plugin._ft_fetch_results = ft_fetch_results
    elapsed = time.time() - t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
    plugin._event_q.put(StageEvent(StageName.FULLTEXT_FETCH, "done", total, done, 0, elapsed, rate, "done"))

    # 3) Full-text screening (parallel-aware)
    t0 = time.time(); total = len(A); done = 0
    plugin._event_q.put(StageEvent(StageName.FULLTEXT_SCREEN, "running", total, done, 0, 0.0, 0.0, "start (Batch 7)"))

    ft_min = []
    for r in ft_fetch_results:
        if isinstance(r, dict):
            ft_min.append({"a_id": r.get("a_id"), "status": r.get("status"), "path": r.get("path")})
    ft_screen_results: List[Dict[str, Any]] = []
    def cb_screen(i, n, res):
        nonlocal done, t0
        done = i; ft_screen_results.append(res)
        elapsed = time.time() - t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
        plugin._event_q.put(StageEvent(StageName.FULLTEXT_SCREEN, "running", total, done, 0, elapsed, rate, f"A item {i}"))

    cpu_workers = int(getattr(plugin, "_cpu_workers", 4).get()) if hasattr(plugin, "_cpu_workers") else 4
    if use_parallel:
        from .screen_fulltext_parallel import screen_fulltext_parallel
        screen_fulltext_parallel(A, ft_min, crits, max_workers=cpu_workers, progress_cb=cb_screen)
    else:
        from .screen_fulltext import screen_fulltext
        screen_fulltext(A, ft_min, crits, progress_cb=cb_screen)

    plugin._ft_screen_results = ft_screen_results
    elapsed = time.time() - t0; rate = (done/elapsed*60) if elapsed>0 else 0.0
    plugin._event_q.put(StageEvent(StageName.FULLTEXT_SCREEN, "done", total, done, 0, elapsed, rate, "done"))

    # 4) Decision fusion
    from .decisions import aggregate_decisions
    t0 = time.time(); total = len(A); done = total
    plugin._event_q.put(StageEvent(StageName.DECISIONS_REPORTS, "running", total, 0, 0, 0.0, 0.0, "compute decisions"))
    decisions = aggregate_decisions(A, meta_results, ft_screen_results, pass_thr=pass_thr, border_thr=border_thr)
    plugin._decisions = decisions
    elapsed = time.time() - t0
    plugin._event_q.put(StageEvent(StageName.DECISIONS_REPORTS, "running", total, done, 0, elapsed, (done/elapsed*60) if elapsed>0 else 0.0, "decisions ready"))

    # 5) Reports (optional)
    if save_charts:
        from .reports import prisma_counts, save_charts, default_report_dir, export_decisions_csv
        counts = prisma_counts(decisions)
        outdir = default_report_dir()
        plugin._last_report_dir = outdir
        save_charts(outdir, decisions)
        if export_csv_path:
            export_decisions_csv(export_csv_path, decisions)
        plugin._event_q.put(StageEvent(StageName.DECISIONS_REPORTS, "done", total, done, 0, 0.0, 0.0, f"PRISMA: {counts}"))
    else:
        plugin._event_q.put(StageEvent(StageName.DECISIONS_REPORTS, "done", total, done, 0, 0.0, 0.0, "done"))


# --- convenience helpers for resume ---

def needs_metadata(plugin) -> bool:
    return not hasattr(plugin, "_meta_results") or not plugin._meta_results

def needs_ft_fetch(plugin) -> bool:
    return not hasattr(plugin, "_ft_fetch_results") or not plugin._ft_fetch_results

def needs_ft_screen(plugin) -> bool:
    return not hasattr(plugin, "_ft_screen_results") or not plugin._ft_screen_results

def needs_decisions(plugin) -> bool:
    return not hasattr(plugin, "_decisions") or not plugin._decisions


def resume_from_last(plugin):
    """Run only the missing tail of the pipeline."""
    A = getattr(plugin, "_A_items", [])
    if not A:
        raise RuntimeError("No A items loaded.")
    crits = _read_criteria(plugin)
    if not crits:
        raise RuntimeError("No criteria available.")
    if needs_metadata(plugin):
        run_end_to_end(plugin, save_charts=False)
        return
    if needs_ft_fetch(plugin):
        # run from fetch onward
        plugin._meta_results = getattr(plugin, "_meta_results", [])
        run_end_to_end(plugin, save_charts=False)
        return
    if needs_ft_screen(plugin):
        plugin._meta_results = getattr(plugin, "_meta_results", [])
        plugin._ft_fetch_results = getattr(plugin, "_ft_fetch_results", [])
        run_end_to_end(plugin, save_charts=False)
        return
    if needs_decisions(plugin):
        plugin._meta_results = getattr(plugin, "_meta_results", [])
        plugin._ft_fetch_results = getattr(plugin, "_ft_fetch_results", [])
        plugin._ft_screen_results = getattr(plugin, "_ft_screen_results", [])
        run_end_to_end(plugin, save_charts=False)
        return
