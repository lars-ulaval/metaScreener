# -*- coding: utf-8 -*-
"""
Created on Mon Sep 22 17:53:30 2025

@author: alere
"""

# File: plugins/screen_A/fetch_fulltext_parallel.py
# Batch 6 — Parallel wrappers around the full-text fetcher

from __future__ import annotations
from typing import Dict, Any, List, Optional
from .fetch_fulltext import FTResult, fetch_one, ensure_cache
from .runtime_perf import run_parallel, TokenBucket

# Optional shared bucket: e.g., 4 requests/sec total
_net_bucket: Optional[TokenBucket] = None


def configure_network_ratelimit(tokens_per_sec: float = 4.0):
    global _net_bucket
    _net_bucket = TokenBucket(tokens_per_sec)


def _fetch_one_rate_limited(item: Dict[str, Any]) -> FTResult:
    global _net_bucket
    if _net_bucket is not None:
        _net_bucket.wait(1)
    try:
        return fetch_one(item)
    except Exception as e:
        return FTResult(a_id=item.get("a_id") or item.get("id"), status="error", notes=str(e))


def fetch_fulltext_for_items_parallel(items: List[Dict[str, Any]], *, max_workers: int = 8, progress_cb=None) -> List[Dict[str, Any]]:
    ensure_cache()
    results = run_parallel(items, _fetch_one_rate_limited, max_workers=max_workers, progress_cb=progress_cb)
    out: List[Dict[str, Any]] = []
    for r in results:
        if isinstance(r, FTResult):
            out.append(r.to_dict())
        else:
            out.append(FTResult(a_id=None, status="error", notes=str(r)).to_dict())
    return out