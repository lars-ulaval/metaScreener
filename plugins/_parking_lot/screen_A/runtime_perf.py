# -*- coding: utf-8 -*-
"""
Created on Mon Sep 22 17:53:14 2025

@author: alere
"""

# File: plugins/screen_A/runtime_perf.py
# Batch 6 — Executors, rate limiting & helpers for parallel runs

from __future__ import annotations
from typing import Callable, Iterable, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time


class TokenBucket:
    """Simple token bucket to rate-limit network calls (tokens per second)."""
    def __init__(self, rate: float, capacity: Optional[int] = None):
        self.rate = float(rate)
        self.capacity = int(capacity or max(1, int(rate * 2)))
        self.tokens = self.capacity
        self.lock = threading.Lock()
        self.last = time.monotonic()

    def wait(self, cost: int = 1):
        if self.rate <= 0:
            return
        while True:
            with self.lock:
                now = time.monotonic()
                delta = now - self.last
                self.last = now
                self.tokens = min(self.capacity, self.tokens + delta * self.rate)
                if self.tokens >= cost:
                    self.tokens -= cost
                    return
            time.sleep(max(0.001, cost / self.rate / 2))


def run_parallel(
    work_items: Iterable[Any],
    fn: Callable[[Any], Any],
    *,
    max_workers: int = 8,
    progress_cb: Optional[Callable[[int, int, Any], None]] = None,
) -> List[Any]:
    """Submit work_items to a thread pool and return results in original order.
    Emits progress via progress_cb(i, n, result).
    """
    items = list(work_items)
    n = len(items)
    if n == 0:
        return []
    results: List[Any] = [None] * n
    i_lock = threading.Lock()
    done_ctr = 0

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(fn, item): idx for idx, item in enumerate(items)}
        for fut in as_completed(futs):
            idx = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = e
            results[idx] = res
            with i_lock:
                done_ctr += 1
                if progress_cb:
                    progress_cb(done_ctr, n, res)
    return results