# -*- coding: utf-8 -*-
"""
Created on Mon Sep 22 11:07:38 2025

@author: alere
"""

# File: plugins/screen_A/screen_metadata.py
# Batch 2 — Metadata screening engine (soft scores) + CSV/XLSX loader for A

from __future__ import annotations
from typing import Dict, Any, List, Tuple
import math
import re
import csv

try:
    import pandas as pd
    PANDAS_OK = True
except Exception:
    pd = None
    PANDAS_OK = False

from .criteria_schema import normalize_synonyms

# --- Public helpers ---------------------------------------------------------

def parse_A_csv_xlsx(path: str) -> List[Dict[str, Any]]:
    """Load A items from CSV/XLSX with loose headers. Expected useful fields:
    a_id | id | doi | title | abstract | year | venue | keywords | mesh
    """
    rows: List[Dict[str, Any]] = []
    if PANDAS_OK and path.lower().endswith((".xlsx", ".xls", ".csv")):
        try:
            df = pd.read_excel(path) if path.lower().endswith((".xlsx", ".xls")) else pd.read_csv(path)
            rows = df.to_dict(orient="records")
        except Exception:
            rows = []
    if not rows and path.lower().endswith(".csv"):
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    # normalize keys (lowercase) but keep original values
    normed = []
    for i, r in enumerate(rows, 1):
        nr = { (k.lower() if isinstance(k,str) else k): v for k,v in r.items() }
        # ensure a_id
        if "a_id" not in nr:
            nr["a_id"] = nr.get("id", i)
        normed.append(nr)
    return normed


# --- Scoring model ----------------------------------------------------------

DEFAULT_PASS_THR = 0.60
DEFAULT_BORDER_THR = 0.40

# Missing/unknown handling (soft)
MISSING_SCORE_INCLUDE = 0.50   # include criterion unknown -> neutral-ish
MISSING_SCORE_EXCLUDE = 0.70   # exclude criterion unknown -> lenient


def screen_metadata(item: Dict[str, Any], criteria: List[Dict[str, Any]], *,
                    pass_thr: float = DEFAULT_PASS_THR,
                    border_thr: float = DEFAULT_BORDER_THR) -> Dict[str, Any]:
    """Compute a soft score on metadata using include/exclude criteria.
    criteria: list of dicts with keys id,type,scope,targets,operators,patterns,weight,threshold
    Returns: {score, label, per_criterion:[{id,type,weight,score,matched}]}
    """
    # collect only metadata-relevant criteria
    meta_criteria = [c for c in criteria if (c.get("scope","both") in ("metadata","both"))]
    per: List[Dict[str, Any]] = []
    wsum = 0.0
    ssum = 0.0

    for c in meta_criteria:
        w = float(c.get("weight", 1.0))
        rule_score, matched = _criterion_score_metadata(item, c)
        per.append({
            "id": c.get("id"),
            "type": c.get("type"),
            "weight": w,
            "score": rule_score,
            "matched": matched,
        })
        wsum += w
        ssum += w * rule_score

    overall = (ssum/wsum) if wsum > 0 else 0.0
    label = _label_from_score(overall, pass_thr, border_thr)
    return {"score": overall, "label": label, "per_criterion": per}


def _label_from_score(score: float, pass_thr: float, border_thr: float) -> str:
    if score >= pass_thr:
        return "pass"
    if score >= border_thr:
        return "borderline"
    return "fail"


# --- Rule scoring -----------------------------------------------------------

def _get_text_fields(item: Dict[str,Any]) -> Dict[str,str]:
    return {
        "title": str(item.get("title") or item.get("ti") or ""),
        "abstract": str(item.get("abstract") or item.get("ab") or ""),
        "keywords": str(item.get("keywords") or item.get("kw") or ""),
        "mesh": str(item.get("mesh") or ""),
        "venue": str(item.get("venue") or item.get("journal") or ""),
        "language": str(item.get("language") or item.get("lang") or ""),
        "year": str(item.get("year") or item.get("py") or ""),
    }


def _criterion_score_metadata(item: Dict[str,Any], c: Dict[str,Any]) -> Tuple[float, str]:
    ctype = (c.get("type") or "include").lower()
    targets = c.get("targets") or ["title","abstract","keywords"]
    ops = c.get("operators") or ["contains"]
    patterns = c.get("patterns") or [c.get("label") or ""]

    fields = _get_text_fields(item)

    # pre-normalize all text
    fields_norm = {k: normalize_synonyms(v.lower()) for k,v in fields.items()}
    pats_norm = [normalize_synonyms(str(p).lower()) for p in patterns]

    matched_any = False
    known_any = False

    for tgt in targets:
        val = fields_norm.get(tgt)
        if val is None or val == "":
            continue
        known_any = True
        for op in ops:
            if _match(op, val, pats_norm):
                matched_any = True
                break
        if matched_any:
            break

    if ctype == "include":
        if matched_any:
            return 1.0, "match"
        if not known_any:
            return MISSING_SCORE_INCLUDE, "unknown"
        return 0.0, "no-match"
    else:  # exclude
        if matched_any:
            return 0.0, "match-exclude"
        if not known_any:
            return MISSING_SCORE_EXCLUDE, "unknown"
        return 1.0, "no-match"


def _match(op: str, text: str, patterns: List[str]) -> bool:
    op = op.lower()
    if op == "contains":
        return any(p in text for p in patterns)
    if op == "equals":
        return any(text.strip() == p.strip() for p in patterns)
    if op == "in":
        # same as contains from the perspective of text ∋ pattern
        return any(p in text for p in patterns)
    if op == "not_in":
        return all(p not in text for p in patterns)
    if op == "regex":
        try:
            return any(re.search(p, text, flags=re.I) for p in patterns)
        except re.error:
            return False
    if op == "gte" or op == "lte" or op == "between":
        # attempt numeric compare on year or numeric tokens
        try:
            nums = [int(s) for s in re.findall(r"\d{4}", text)]
            val = nums[0] if nums else None
            if val is None:
                return False
            if op == "gte":
                return any(int(p) <= val for p in patterns if str(p).isdigit())
            if op == "lte":
                return any(int(p) >= val for p in patterns if str(p).isdigit())
            if op == "between" and len(patterns) >= 2 and str(patterns[0]).isdigit() and str(patterns[1]).isdigit():
                lo, hi = int(patterns[0]), int(patterns[1])
                return lo <= val <= hi
        except Exception:
            return False
    # default fallback
    return False
