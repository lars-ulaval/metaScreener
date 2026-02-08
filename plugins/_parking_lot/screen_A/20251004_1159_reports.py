# -*- coding: utf-8 -*-
"""
Created on Mon Sep 22 12:19:43 2025

@author: alere
"""

# File: plugins/screen_A/reports.py
# Batch 5 — Exports and quick charts (CSV/XLSX + PNG)

from __future__ import annotations
from typing import Dict, Any, List, Tuple
import os
import csv
from collections import Counter, defaultdict
from datetime import datetime

try:
    import pandas as pd
    HAVE_PANDAS = True
except Exception:
    pd = None
    HAVE_PANDAS = False

try:
    import matplotlib
    matplotlib.use("Agg")  # headless
    import matplotlib.pyplot as plt
    HAVE_MPL = True
except Exception:
    plt = None
    HAVE_MPL = False

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".screenA_cache", "reports")


def ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p


def prisma_counts(records: List[Dict[str, Any]]) -> Dict[str, int]:
    total = len(records)
    by_label = Counter([r.get("label") for r in records])
    return {
        "total": total,
        "include": by_label.get("include", 0),
        "exclude": by_label.get("exclude", 0),
        "needs_review": by_label.get("needs-review", 0),
        "insufficient": by_label.get("insufficient-evidence", 0),
    }


def top_exclusion_reasons(records: List[Dict[str, Any]], top_k: int = 10) -> List[Tuple[str,int]]:
    ctr = Counter()
    for r in records:
        if r.get("label") == "exclude":
            for d in r.get("drivers") or []:
                ctr[d] += 1
    return ctr.most_common(top_k)


def export_decisions_csv(path: str, records: List[Dict[str, Any]]) -> None:
    if HAVE_PANDAS:
        df = pd.DataFrame.from_records(records)
        df.to_csv(path, index=False)
        return
    # fallback
    keys = sorted(set(k for r in records for k in r.keys()))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader(); w.writerows(records)


def export_decisions_xlsx(path: str, records: List[Dict[str, Any]]) -> None:
    if not HAVE_PANDAS:
        raise RuntimeError("pandas not available for XLSX export")
    df = pd.DataFrame.from_records(records)
    df.to_excel(path, index=False)


def save_charts(output_dir: str, records: List[Dict[str, Any]]) -> Dict[str, str]:
    """Create a couple of quick charts. Returns dict of chart name → path."""
    ensure_dir(output_dir)
    out: Dict[str, str] = {}
    if not HAVE_MPL:
        return out

    # Bar chart of exclusion reasons
    reasons = top_exclusion_reasons(records, top_k=12)
    if reasons:
        labels = [r[0] for r in reasons]
        values = [r[1] for r in reasons]
        plt.figure()
        plt.bar(range(len(values)), values)
        plt.xticks(range(len(labels)), labels, rotation=45, ha='right')
        plt.title('Top exclusion reasons')
        plt.tight_layout()
        p = os.path.join(output_dir, 'exclusion_reasons.png')
        plt.savefig(p)
        out['exclusion_reasons'] = p

    # PRISMA-style counts (stacked bar)
    counts = prisma_counts(records)
    plt.figure()
    cats = ['include','exclude','needs_review','insufficient']
    vals = [counts[c] for c in cats]
    plt.bar(range(len(vals)), vals)
    plt.xticks(range(len(cats)), cats, rotation=0)
    plt.title('Decision outcomes')
    plt.tight_layout()
    p2 = os.path.join(output_dir, 'decision_outcomes.png')
    plt.savefig(p2)
    out['decision_outcomes'] = p2

    return out


def default_report_dir() -> str:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return ensure_dir(os.path.join(CACHE_DIR, f"run_{ts}"))
