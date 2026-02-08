# -*- coding: utf-8 -*-
"""
Created on Mon Sep 22 17:53:40 2025

@author: alere
"""

# File: plugins/screen_A/screen_fulltext_parallel.py
# Batch 6 — Parallel wrapper for full-text screening (CPU/IO bound)

from __future__ import annotations
from typing import Dict, Any, List, Optional
from .screen_fulltext import screen_fulltext, extract_pages, make_chunks, decide_for_criterion
from .runtime_perf import run_parallel
import os


def _screen_one(args):
    (it, ft_map, criteria) = args
    a_id = it.get("a_id") or it.get("id")
    pdf_path = ft_map.get(a_id)
    if not pdf_path or not os.path.isfile(pdf_path):
        return {"a_id": a_id, "per_criterion": [], "notes": "full text unavailable"}
    try:
        pages = extract_pages(pdf_path)
        chunks = make_chunks(pages, max_chars=2500)
        per = []
        for c in criteria:
            if (c.get("scope","both") not in ("fulltext","both")):
                continue
            d = decide_for_criterion(a_id, c, chunks)
            per.append(d.to_dict())
        return {"a_id": a_id, "per_criterion": per, "notes": "ok"}
    except Exception as e:
        return {"a_id": a_id, "per_criterion": [], "notes": f"error: {e}"}


def screen_fulltext_parallel(items: List[Dict[str,Any]], ft_results: List[Dict[str,Any]], criteria: List[Dict[str,Any]], *, max_workers: int = 4, progress_cb=None) -> List[Dict[str,Any]]:
    ft_map = { (r.get("a_id") if isinstance(r,dict) else getattr(r,'a_id',None)): (r.get("path") if isinstance(r,dict) else getattr(r,'path',None)) for r in ft_results }
    args = [(it, ft_map, criteria) for it in items]
    results = run_parallel(args, _screen_one, max_workers=max_workers, progress_cb=progress_cb)
    return results
