# -*- coding: utf-8 -*-
"""
Created on Mon Sep 22 12:19:43 2025

@author: alere
"""

# File: plugins/screen_A/reports.py
# Batch 5 → 8 — Exports and quick charts (CSV/XLSX + PNG)
# Adds LLM+Funneling-friendly metadata audit exports and charts.

from __future__ import annotations
from typing import Dict, Any, List, Tuple, Iterable, Optional
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


# ---------------------------
# FS utils
# ---------------------------
def ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p


def default_report_dir() -> str:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return ensure_dir(os.path.join(CACHE_DIR, f"run_{ts}"))


# ---------------------------
# PRISMA-style counts (final decisions)
# ---------------------------
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


# ---------------------------
# Decisions export (final)
# ---------------------------
def export_decisions_csv(path: str, records: List[Dict[str, Any]]) -> None:
    if HAVE_PANDAS:
        pd.DataFrame.from_records(records).to_csv(path, index=False)
        return
    keys = sorted(set(k for r in records for k in r.keys()))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader(); w.writerows(records)


def export_decisions_xlsx(path: str, records: List[Dict[str, Any]]) -> None:
    if not HAVE_PANDAS:
        raise RuntimeError("pandas not available for XLSX export")
    pd.DataFrame.from_records(records).to_excel(path, index=False)


# ---------------------------
# Metadata audit (LLM + funnel)
# ---------------------------
def _presence_cols(pres: Optional[Dict[str, bool]]) -> Dict[str, Any]:
    pres = pres or {}
    return {
        "has_title": bool(pres.get("has_title")),
        "has_abstract": bool(pres.get("has_abstract")),
        "has_keywords": bool(pres.get("has_keywords")),
        "has_year": bool(pres.get("has_year")),
        "has_lang": bool(pres.get("has_lang")),
        "has_venue": bool(pres.get("has_venue")),
        "has_doc_type": bool(pres.get("has_doc_type")),
    }


def _flatten_meta_item(item_res: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """
    Flatten one metadata result (from screen_metadata) into 1..N rows,
    one per criterion, carrying per-criterion and per-item fields.
    """
    a_id = item_res.get("a_id")
    base = {
        "a_id": a_id,
        "meta_label": item_res.get("label"),
        "meta_score": float(item_res.get("score") or 0.0),
        "score_so_far": float(item_res.get("score_so_far") or 0.0),
        "max_remaining": float(item_res.get("max_remaining") or 0.0),
        "drop_by_upper_bound": bool(item_res.get("drop_by_upper_bound", False)),
        **_presence_cols(item_res.get("presence")),
    }
    for pc in item_res.get("per_criterion", []) or []:
        row = dict(base)
        row.update({
            "criterion_id": pc.get("id"),
            "criterion_type": pc.get("type"),
            "weight": float(pc.get("weight") or 1.0),
            # legacy vs fused
            "rule_score": float(pc.get("rule_score", pc.get("score", 0.0)) or 0.0),
            "fused_score": float(pc.get("fused_score", pc.get("score", 0.0)) or 0.0),
            "matched": pc.get("matched"),
            # LLM evidence (may be None)
            "llm_decision": pc.get("llm_decision"),
            "llm_conf": (None if pc.get("llm_conf") is None else float(pc.get("llm_conf"))),
            "llm_field": pc.get("llm_field"),
            # span may be [s,e] or None
            "llm_quote_span": pc.get("llm_quote_span"),
        })
        yield row


def export_metadata_audit_csv(path: str, meta_results: List[Dict[str, Any]]) -> None:
    """
    Export a long CSV with one row per (a_id, criterion), including:
      presence flags, rule vs fused scores, LLM evidence, and UB math.
    """
    rows: List[Dict[str, Any]] = []
    for r in meta_results or []:
        rows.extend(list(_flatten_meta_item(r)))

    if HAVE_PANDAS:
        df = pd.DataFrame.from_records(rows)
        df.to_csv(path, index=False)
        return

    keys = sorted(set(k for r in rows for k in r.keys()))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader(); w.writerows(rows)


def export_metadata_audit_xlsx(path: str, meta_results: List[Dict[str, Any]]) -> None:
    if not HAVE_PANDAS:
        raise RuntimeError("pandas not available for XLSX export")
    rows: List[Dict[str, Any]] = []
    for r in meta_results or []:
        rows.extend(list(_flatten_meta_item(r)))
    pd.DataFrame.from_records(rows).to_excel(path, index=False)


def metadata_funnel_summary(meta_results: List[Dict[str, Any]], escalated_ids: Optional[Iterable[Any]] = None) -> Dict[str, Any]:
    """
    Quick tallies useful for UI/logs:
      - counts by meta_label
      - how many items were drop_by_upper_bound
      - how many had unknown gates (approx via 'matched' flag)
      - how many were escalated (optional set from orchestrator)
    """
    by_label = Counter([r.get("label") for r in meta_results or []])
    pruned = sum(1 for r in meta_results or [] if r.get("drop_by_upper_bound"))
    # Approximate "gate unknown": count criterion entries whose matched startswith 'unknown'
    gate_unknown = 0
    for r in meta_results or []:
        if any((pc.get("matched", "") or "").startswith("unknown") for pc in r.get("per_criterion", []) or []):
            gate_unknown += 1
    escalated = len(set(escalated_ids or []))
    return {
        "total_items": len(meta_results or []),
        "labels": dict(by_label),
        "pruned_by_upper_bound": pruned,
        "gate_unknown_items": gate_unknown,
        "escalated_items": escalated,
    }


# ---------------------------
# Charts
# ---------------------------
def save_charts(output_dir: str, records: List[Dict[str, Any]]) -> Dict[str, str]:
    """Create a couple of quick charts for final decisions. Returns dict of name → path."""
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


def save_metadata_charts(output_dir: str, meta_results: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Quick visuals for the metadata stage:
      - Distribution of metadata labels (pass/borderline/fail)
      - Histogram of fused metadata scores
    """
    ensure_dir(output_dir)
    out: Dict[str, str] = {}
    if not HAVE_MPL:
        return out

    # Distribution of metadata labels
    by_label = Counter([r.get("label") for r in (meta_results or [])])
    if by_label:
        labs = list(by_label.keys())
        vals = [by_label[k] for k in labs]
        plt.figure()
        plt.bar(range(len(vals)), vals)
        plt.xticks(range(len(labs)), labs)
        plt.title("Metadata labels")
        plt.tight_layout()
        p = os.path.join(output_dir, "metadata_labels.png")
        plt.savefig(p)
        out["metadata_labels"] = p

    # Histogram of metadata scores
    scores = [float(r.get("score") or 0.0) for r in (meta_results or [])]
    if scores:
        plt.figure()
        plt.hist(scores, bins=20)
        plt.title("Metadata scores (fused)")
        plt.tight_layout()
        p2 = os.path.join(output_dir, "metadata_scores_hist.png")
        plt.savefig(p2)
        out["metadata_scores_hist"] = p2

    return out

# ---------------------------
# Criteria harmonization audit (NEW)
# ---------------------------
import json
import re

_CRIT_FIELDS = ("id","label","type","scope","targets","operators","patterns","weight","threshold","notes")

def _crit_to_dict(obj: Any) -> Dict[str, Any]:
    """Coerce Criterion or plain dict into a serializable dict with known fields."""
    if isinstance(obj, dict):
        d = obj
    else:
        # dataclass or simple object with attributes
        d = {k: getattr(obj, k, None) for k in _CRIT_FIELDS}
    # Normalize lists & scalars for consistency
    out: Dict[str, Any] = {}
    for k in _CRIT_FIELDS:
        v = d.get(k, None)
        if k in ("targets","operators","patterns"):
            if v is None:
                v = []
            elif isinstance(v, str):
                # accept comma/semicolon separated strings
                v = [t.strip() for t in re.split(r"[;,]", v) if t.strip()]
            else:
                v = [str(t).strip() for t in list(v)]
        elif k in ("weight","threshold"):
            try:
                v = float(v)
            except Exception:
                v = 0.0 if k == "threshold" else 1.0
        else:
            v = "" if v is None else str(v)
        out[k] = v
    return out

def _diff_crit(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return a list of field-level diffs for one criterion."""
    diffs: List[Dict[str, Any]] = []
    for k in _CRIT_FIELDS:
        if before.get(k) != after.get(k):
            b = before.get(k)
            a = after.get(k)
            # Render lists as comma-joined strings in CSV for readability
            if isinstance(b, list): b = ", ".join(map(str, b))
            if isinstance(a, list): a = ", ".join(map(str, a))
            diffs.append({"id": after.get("id") or before.get("id"), "field": k, "before": b, "after": a})
    return diffs

def save_criteria_audit(
    outdir: str,
    before: List[Any],
    after: List[Any],
    model_params: Dict[str, Any] | None = None,
    errors: List[str] | None = None,
) -> str:
    """
    Save a compact audit of criteria harmonization.
    - Writes JSON with before/after arrays and field-level diffs.
    - Also writes a CSV of diffs for quick viewing.
    Returns the directory used.
    """
    ensure_dir(outdir)

    # Coerce all to plain dicts
    before_d = [_crit_to_dict(x) for x in (before or [])]
    after_d  = [_crit_to_dict(x) for x in (after  or [])]

    # Index by id for diffing; if id missing, assign a temporary key
    def _keyed(arr: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        keyed: Dict[str, Dict[str, Any]] = {}
        for i, c in enumerate(arr, 1):
            cid = c.get("id") or f"UNK{i:02d}"
            keyed[str(cid)] = c
        return keyed

    bmap = _keyed(before_d)
    amap = _keyed(after_d)

    # Union of ids
    ids = sorted(set(bmap.keys()) | set(amap.keys()), key=lambda x: (x[:1], x))
    all_diffs: List[Dict[str, Any]] = []
    for cid in ids:
        b = bmap.get(cid, {**_crit_to_dict({}), "id": cid})
        a = amap.get(cid, {**_crit_to_dict({}), "id": cid})
        all_diffs.extend(_diff_crit(b, a))

    # JSON payload
    audit_json = {
        "model": model_params or {},
        "counts": {"before": len(before_d), "after": len(after_d), "diff_rows": len(all_diffs)},
        "errors": list(errors or []),
        "before": before_d,
        "after": after_d,
        "diffs": all_diffs,
    }

    # Write files
    json_path = os.path.join(outdir, "criteria_audit.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(audit_json, f, ensure_ascii=False, indent=2)

    csv_path = os.path.join(outdir, "criteria_diffs.csv")
    if HAVE_PANDAS:
        pd.DataFrame.from_records(all_diffs).to_csv(csv_path, index=False)
    else:
        keys = ["id","field","before","after"]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader(); w.writerows(all_diffs)

    return outdir
