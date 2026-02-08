# -*- coding: utf-8 -*-
"""
Created on Mon Sep 22 18:07:18 2025

@author: alere
"""

# File: plugins/screen_A/pipeline_orchestrator.py
# Batch 7 — End-to-end orchestration with resume-friendly stages and richer diagnostics
# LLM + Safe-Funneling extensions for Metadata stage:
# - M0 Gates (rules-only) with conservative handling of missing fields
# - M1 Semantic (optional LLM fusion), conservative, extractive-only
# - Safe pruning via upper-bound math
# - Optional early escalation flag for metadata-poor items

from __future__ import annotations
from typing import Any, Dict, List, Tuple, Optional, Set
import time
import os

from .ui_progress import StageName, StageEvent

# -------------------------------
# Utilities
# -------------------------------

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


def _is_gate_criterion(c: Dict[str, Any]) -> bool:
    """
    Heuristic split: gates are objective, monotonic checks on simple fields.
    Targets that look like gates: lang, language, year, doc_type, venue (if equals/not_in).
    Operators that look like gates: equals, in/not_in, gte/lte/between (on years).
    """
    if (c.get("scope", "both") not in ("metadata", "both")):
        return False
    targets = [t.lower() for t in (c.get("targets") or [])]
    ops = [o.lower() for o in (c.get("operators") or [])]
    gate_targets = {"lang", "language", "year", "doc_type", "venue"}
    simple_ops = {"equals", "in", "not_in", "gte", "lte", "between"}
    if any(t in gate_targets for t in targets) and all(o in simple_ops for o in ops):
        return True
    return False


def _split_gates_scores(crits: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    gates, scores = [], []
    for c in crits:
        (gates if _is_gate_criterion(c) else scores).append(c)
    return gates, scores


def _get_plugin_toggle(plugin, attr: str, default):
    """Safely read tk variables or plain attributes; fallback to default."""
    if hasattr(plugin, attr):
        v = getattr(plugin, attr)
        try:
            # tk variable
            return v.get()
        except Exception:
            return v
    return default


# -------------------------------
# Orchestration
# -------------------------------

def run_end_to_end(plugin, *, save_charts: bool = True, export_csv_path: str | None = None):
    """Drive the whole pipeline using the plugin instance state.
    Stores results on the plugin:
      - _meta_results       : list per A item (after fusion/pruning flags)
      - _meta_survivors     : list of A items surviving metadata (if safe-funneling ON)
      - _ft_fetch_results   : list
      - _ft_screen_results  : list
      - _decisions          : list
      - _last_report_dir    : str (final decisions)
      - _last_report_dir_meta : str (metadata audit/report)
      - _escalated_to_ft    : set of a_id flagged for early escalation (metadata-poor)
    """
    # 0) Preconditions
    A: List[Dict[str, Any]] = getattr(plugin, "_A_items", [])
    if not A:
        raise RuntimeError("No A items loaded. Use Metadata tab to load CSV/XLSX first.")
    crits = _read_criteria(plugin)
    if not crits:
        raise RuntimeError("No criteria available. Harmonize criteria first.")

    # Thresholds
    pass_thr = float(_get_plugin_toggle(plugin, "_thr_pass", 0.60))
    border_thr = float(_get_plugin_toggle(plugin, "_thr_border", 0.40))

    # Metadata options (all optional; sensible defaults)
    use_llm_for_metadata = bool(_get_plugin_toggle(plugin, "_use_llm_metadata", False))
    safe_funneling_on = bool(_get_plugin_toggle(plugin, "_safe_funneling", True))
    missing_fields_policy = str(_get_plugin_toggle(plugin, "_missing_fields_policy", "unknown"))  # "unknown" or "negative"
    early_escalate_sparse = bool(_get_plugin_toggle(plugin, "_early_escalate_sparse", False))

    # LLM runtime knobs (only used if use_llm_for_metadata is True)
    llm_model = str(_get_plugin_toggle(plugin, "_llm_model", "gpt-4o-mini"))
    llm_batch_size = int(_get_plugin_toggle(plugin, "_llm_batch_size", 12))
    llm_workers = int(_get_plugin_toggle(plugin, "_llm_workers", 8))
    llm_trunc_chars = int(_get_plugin_toggle(plugin, "_llm_trunc_chars", 1500))

    # 1) METADATA — M0 Gates (rules only)
    from .screen_metadata import screen_metadata
    t0 = time.time()
    total = len(A)
    done = 0
    plugin._event_q.put(StageEvent(StageName.METADATA, "running", total, done, 0, 0.0, 0.0, "M0: Gates (rules)"))

    gates, scores = _split_gates_scores(crits)
    # If no gates were recognized, treat all as scores
    if not gates:
        scores = crits[:]

    meta_results: List[Dict[str, Any]] = []
    survivors: List[Dict[str, Any]] = []
    gate_fail_count = 0
    gate_unknown_count = 0
    escalated_ids: Set[Any] = set()

    # In M0, we evaluate only the gate criteria; judged_criteria_ids = gate ids
    judged_gate_ids = {c.get("id") for c in gates} if gates else set()

    for item in A:
        res = screen_metadata(
            item, gates if gates else scores,
            pass_thr=pass_thr, border_thr=border_thr,
            llm_decisions=None,  # rules only
            judged_criteria_ids=judged_gate_ids,
            missing_fields_policy="unknown" if missing_fields_policy != "negative" else "negative",
        )
        # Decide M0 outcome
        presence = res.get("presence", {})
        unknown_on_gates = any(pc.get("matched", "").startswith("unknown") for pc in res.get("per_criterion", []))
        hard_fail = (res["label"] == "fail") and (not unknown_on_gates)

        if hard_fail:
            gate_fail_count += 1
        else:
            # Early escalation flag if metadata-poor (no abstract and no keywords)
            if early_escalate_sparse:
                if not presence.get("has_abstract", False) and not presence.get("has_keywords", False):
                    escalated_ids.add(item.get("a_id"))
            survivors.append(item)

        if unknown_on_gates:
            gate_unknown_count += 1

        meta_results.append({
            "__stage": "M0",
            "a_id": item.get("a_id"),
            **res
        })

        done += 1
        elapsed = time.time() - t0
        rate = (done / elapsed * 60) if elapsed > 0 else 0.0
        plugin._event_q.put(StageEvent(
            StageName.METADATA, "running", total, done, 0, elapsed, rate,
            f"M0: processed {done}/{total}"
        ))

    plugin._event_q.put(StageEvent(
        StageName.METADATA, "running", total, done, 0, time.time() - t0, 0.0,
        f"M0 done: gate_fail={gate_fail_count}, gate_unknown={gate_unknown_count}, survivors={len(survivors)}"
    ))

    # 2) METADATA — M1 Semantic (optional LLM fusion)
    # Prepare LLM decisions dict: {(a_id, criterion_id) -> {...}}
    llm_decisions: Dict[Tuple[Any, Any], Dict[str, Any]] = {}

    if use_llm_for_metadata and scores:
        plugin._event_q.put(StageEvent(
            StageName.METADATA, "running", len(survivors), 0, 0, 0.0, 0.0,
            "M1: Semantic (LLM batching)"
        ))

        # Try to import the planned llm_metadata helper; if absent, we gracefully skip LLM.
        llm_available = False
        try:
            from .llm_metadata import run_llm_for_criteria  # to be added later
            llm_available = True
        except Exception:
            llm_available = False

        if llm_available and survivors:
            llm_decisions = run_llm_for_criteria(
                items=survivors,
                criteria=scores,
                model=llm_model,
                batch_size=llm_batch_size,
                workers=llm_workers,
                trunc_chars=llm_trunc_chars,
                progress_cb=lambda done_batches, total_batches: plugin._event_q.put(
                    StageEvent(StageName.METADATA, "running", total_batches, done_batches, 0, 0.0, 0.0,
                               f"M1: LLM batches {done_batches}/{total_batches}")
                )
            )
        else:
            plugin._event_q.put(StageEvent(
                StageName.METADATA, "running", len(survivors), 0, 0.0, 0.0, 0.0,
                "M1: LLM helper not available, skipping fusion"
            ))

    # 3) METADATA — Fusion over ALL criteria, compute bounds, safe pruning
    plugin._event_q.put(StageEvent(
        StageName.METADATA, "running", len(survivors), 0, 0, 0.0, 0.0,
        "M1: Scoring + Bounds"
    ))

    final_meta_results: List[Dict[str, Any]] = []
    pruned_count = 0
    survivors_after_m1: List[Dict[str, Any]] = []

    # In M1, "judged" = all metadata criteria (so bounds reflect only unjudged if you later add M2)
    judged_all_meta_ids = {c.get("id") for c in (gates + scores)}

    for idx, item in enumerate(survivors, 1):
        res = screen_metadata(
            item, (gates + scores),
            pass_thr=pass_thr, border_thr=border_thr,
            llm_decisions=llm_decisions if use_llm_for_metadata else None,
            judged_criteria_ids=judged_all_meta_ids,
            missing_fields_policy="unknown" if missing_fields_policy != "negative" else "negative",
        )
        drop_by_ub = bool(res.get("drop_by_upper_bound", False))
        if safe_funneling_on and drop_by_ub:
            pruned_count += 1
        else:
            survivors_after_m1.append(item)

        final_meta_results.append({
            "__stage": "M1",
            "a_id": item.get("a_id"),
            **res
        })

        if idx % 10 == 0 or idx == len(survivors):
            plugin._event_q.put(StageEvent(
                StageName.METADATA, "running", len(survivors), idx, 0, 0.0, 0.0,
                f"M1: scored {idx}/{len(survivors)}"
            ))

    plugin._meta_results = final_meta_results
    plugin._escalated_to_ft = escalated_ids

    # --- NEW: metadata audit exports & summary ---
    try:
        from .reports import (
            default_report_dir,
            metadata_funnel_summary,
            export_metadata_audit_csv,
            save_metadata_charts,
        )
        outdir_meta = default_report_dir()
        plugin._last_report_dir_meta = outdir_meta

        # Save long-form audit CSV (one row per a_id×criterion)
        audit_csv_path = os.path.join(outdir_meta, "metadata_audit.csv")
        export_metadata_audit_csv(audit_csv_path, final_meta_results)

        # Quick charts for metadata stage
        save_metadata_charts(outdir_meta, final_meta_results)

        # Funnel summary for logs / UI counters
        summary = metadata_funnel_summary(final_meta_results, escalated_ids)
        plugin._event_q.put(StageEvent(
            StageName.METADATA, "running", len(survivors), len(survivors), 0, 0.0, 0.0,
            f"M1 summary: labels={summary.get('labels')}, pruned_by_UB={summary.get('pruned_by_upper_bound')}, "
            f"gate_unknown_items={summary.get('gate_unknown_items')}, escalated={summary.get('escalated_items')}, "
            f"audit_csv={audit_csv_path}"
        ))
    except Exception as _e:
        # Non-fatal; continue without audit exports
        pass

    plugin._event_q.put(StageEvent(
        StageName.METADATA, "done", len(A), len(A), 0, time.time() - t0, 0.0,
        f"M1 done: pruned_by_upper_bound={pruned_count}, escalated={len(escalated_ids)}"
    ))

    # Choose population for downstream stages
    A_downstream = survivors_after_m1 if (safe_funneling_on and survivors_after_m1) else A
    plugin._meta_survivors = A_downstream

    # 4) Full-text fetch (parallel-aware)
    use_parallel = bool(_get_plugin_toggle(plugin, "_use_parallel", False))
    net_workers = int(_get_plugin_toggle(plugin, "_net_workers", 8))
    net_rate = float(_get_plugin_toggle(plugin, "_net_rate", 4.0))

    t0 = time.time()
    total = len(A_downstream)
    done = 0
    plugin._event_q.put(StageEvent(StageName.FULLTEXT_FETCH, "running", total, done, 0, 0.0, 0.0, "start (Batch 7)"))

    ft_fetch_results: List[Dict[str, Any]] = []

    def cb_fetch(i, n, res):
        nonlocal done, t0
        done = i
        ft_fetch_results.append(res.to_dict() if hasattr(res, "to_dict") else (res if isinstance(res, dict) else {"status": "error", "notes": str(res)}))
        elapsed = time.time() - t0
        rate = (done / elapsed * 60) if elapsed > 0 else 0.0
        plugin._event_q.put(StageEvent(StageName.FULLTEXT_FETCH, "running", total, done, 0, elapsed, rate, f"A item {i}"))

    if use_parallel:
        from .fetch_fulltext_parallel import fetch_fulltext_for_items_parallel, configure_network_ratelimit
        configure_network_ratelimit(tokens_per_sec=net_rate)
        fetch_fulltext_for_items_parallel(A_downstream, max_workers=net_workers, progress_cb=cb_fetch)
    else:
        from .fetch_fulltext import fetch_fulltext_for_items
        fetch_fulltext_for_items(A_downstream, progress_cb=cb_fetch)

    plugin._ft_fetch_results = ft_fetch_results
    elapsed = time.time() - t0
    rate = (done / elapsed * 60) if elapsed > 0 else 0.0
    plugin._event_q.put(StageEvent(StageName.FULLTEXT_FETCH, "done", total, done, 0, elapsed, rate, "done"))

    # 5) Full-text screening (parallel-aware)
    t0 = time.time()
    total = len(A_downstream)
    done = 0
    plugin._event_q.put(StageEvent(StageName.FULLTEXT_SCREEN, "running", total, done, 0, 0.0, 0.0, "start (Batch 7)"))

    ft_min = []
    for r in ft_fetch_results:
        if isinstance(r, dict):
            ft_min.append({"a_id": r.get("a_id"), "status": r.get("status"), "path": r.get("path")})

    ft_screen_results: List[Dict[str, Any]] = []

    def cb_screen(i, n, res):
        nonlocal done, t0
        done = i
        ft_screen_results.append(res)
        elapsed = time.time() - t0
        rate = (done / elapsed * 60) if elapsed > 0 else 0.0
        plugin._event_q.put(StageEvent(StageName.FULLTEXT_SCREEN, "running", total, done, 0, elapsed, rate, f"A item {i}"))

    cpu_workers = int(_get_plugin_toggle(plugin, "_cpu_workers", 4))
    if use_parallel:
        from .screen_fulltext_parallel import screen_fulltext_parallel
        screen_fulltext_parallel(A_downstream, ft_min, crits, max_workers=cpu_workers, progress_cb=cb_screen)
    else:
        from .screen_fulltext import screen_fulltext
        screen_fulltext(A_downstream, ft_min, crits, progress_cb=cb_screen)

    plugin._ft_screen_results = ft_screen_results
    elapsed = time.time() - t0
    rate = (done / elapsed * 60) if elapsed > 0 else 0.0
    plugin._event_q.put(StageEvent(StageName.FULLTEXT_SCREEN, "done", total, done, 0, elapsed, rate, "done"))

    # 6) Decision fusion
    from .decisions import aggregate_decisions
    t0 = time.time()
    total = len(A_downstream)
    done = total
    plugin._event_q.put(StageEvent(StageName.DECISIONS_REPORTS, "running", total, 0, 0, 0.0, 0.0, "compute decisions"))

    decisions = aggregate_decisions(A_downstream, plugin._meta_results, ft_screen_results, pass_thr=pass_thr, border_thr=border_thr)
    plugin._decisions = decisions

    elapsed = time.time() - t0
    plugin._event_q.put(StageEvent(
        StageName.DECISIONS_REPORTS, "running", total, done, 0, elapsed, (done / elapsed * 60) if elapsed > 0 else 0.0,
        "decisions ready"
    ))

    # 7) Reports (optional)
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
