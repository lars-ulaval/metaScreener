# -*- coding: utf-8 -*-
"""
Created on Mon Sep 22 12:19:27 2025

@author: alere
"""

# File: plugins/screen_A/decisions.py
# Batch 5 — Fusion of metadata & full‑text judgments into final decisions

from __future__ import annotations
from typing import Dict, Any, List, Tuple
import math

DEFAULT_INCLUDE_CONF = 0.65
DEFAULT_EXCLUDE_CONF = 0.70


def _map_by_aid(items: List[Dict[str, Any]], key_fn):
    out = {}
    for it in items:
        a_id = key_fn(it)
        if a_id is not None:
            out[a_id] = it
    return out


def aggregate_decisions(
    A: List[Dict[str, Any]],
    meta_results: List[Dict[str, Any]],
    ft_results: List[Dict[str, Any]],
    *,
    pass_thr: float = 0.60,
    border_thr: float = 0.40,
) -> List[Dict[str, Any]]:
    """
    Returns list of records per A item:
    {a_id, title, meta_score, ft_available, label, confidence, drivers, notes}
    Labels: include | exclude | needs-review | insufficient-evidence
    """
    # Build maps keyed by a_id
    a_map = _map_by_aid(A, lambda x: x.get("a_id") or x.get("id"))
    meta_map = {}
    for i, it in enumerate(A):
        a_id = it.get("a_id") or it.get("id") or (i+1)
        if i < len(meta_results):
            meta_map[a_id] = meta_results[i]
    ft_map = _map_by_aid(ft_results, lambda x: x.get("a_id") if isinstance(x, dict) else getattr(x, "a_id", None))

    out: List[Dict[str, Any]] = []
    for i, it in enumerate(A):
        a_id = it.get("a_id") or it.get("id") or (i+1)
        raw_title = it.get("title") or it.get("ti") or ""
        try:
            if isinstance(raw_title, float) and math.isnan(raw_title):
                raw_title = ""
        except Exception:
            pass
        title = str(raw_title).strip()
        meta = meta_map.get(a_id, {})
        meta_score = float(meta.get("score") or 0.0)
        meta_label = str(meta.get("label") or "fail")

        ft = ft_map.get(a_id)
        ft_avail = False
        exclude_hits: List[Tuple[str,float]] = []  # (criterion_id, conf)
        include_hits: List[Tuple[str,float]] = []
        if ft and isinstance(ft, dict):
            pcs = ft.get("per_criterion") or []
            for d in pcs:
                c_id = d.get("criterion_id")
                conf = float(d.get("confidence") or 0.0)
                # screen_fulltext heuristic: include→meet, exclude→not_meet
                decision = (d.get("decision") or "").lower()
                # if any evidence exists, ft was actually run on a PDF
                if d.get("evidence"):
                    ft_avail = True
                # We don't have the criterion type here; use naming convention fallback if present in id
                # Better: expect metadata to carry that info earlier; for Batch 5 we infer from decision semantics
                if decision == "not_meet":
                    exclude_hits.append((c_id, conf))
                elif decision == "meet":
                    include_hits.append((c_id, conf))
        # Determine label
        label = "needs-review"
        confidence = 0.5
        drivers: List[str] = []
        notes = []

        # Strong exclusion: any high‑conf exclude hit
        excl_high = [c for c in exclude_hits if c[1] >= DEFAULT_EXCLUDE_CONF]
        if excl_high:
            label = "exclude"
            confidence = max(c for _, c in excl_high)
            drivers = [cid for cid,_ in sorted(excl_high, key=lambda x: -x[1])]
        else:
            # Potential include
            if meta_label == "pass" and (include_hits or meta_score >= pass_thr):
                label = "include"
                confidence = max(meta_score, max((c for _, c in include_hits), default=0.6))
                drivers = [cid for cid,_ in sorted(include_hits, key=lambda x: -x[1])] or ["metadata-pass"]
            elif meta_label == "borderline" and include_hits:
                label = "include"
                confidence = max(0.6, max(c for _, c in include_hits))
                drivers = [cid for cid,_ in sorted(include_hits, key=lambda x: -x[1])]
            else:
                # No decisive FT evidence
                if not ft_avail:
                    label = "insufficient-evidence" if meta_label == "pass" else "needs-review"
                    notes.append("full text unavailable")
                else:
                    label = "needs-review"

        out.append({
            "a_id": a_id,
            "title": title,
            "meta_score": round(meta_score, 4),
            "meta_label": meta_label,
            "ft_available": bool(ft_avail),
            "label": label,
            "confidence": round(float(confidence), 4),
            "drivers": drivers,
            "notes": "; ".join(notes),
        })
    return out


