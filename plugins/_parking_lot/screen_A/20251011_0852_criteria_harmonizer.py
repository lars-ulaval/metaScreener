# -*- coding: utf-8 -*-
"""
Created on Sun Sep 21 19:32:00 2025

@author: alere
"""

# File: plugins/screen_A/criteria_harmonizer.py
# Batch 1 — Deterministic cleaners + (optional) AI reformulation stub

from __future__ import annotations
from typing import List, Dict, Any
import csv
import re

try:
    import pandas as pd
    PANDAS_OK = True
except Exception:
    pd = None
    PANDAS_OK = False

from .criteria_schema import Criterion, criterion_from_dict, normalize_synonyms


def parse_free_text(raw: str) -> List[Dict[str, Any]]:
    """Heuristic parser: one criterion per non-empty line; infer include/exclude and scope keywords."""
    rows: List[Dict[str, Any]] = []
    i = 1
    for line in raw.splitlines():
        t = line.strip()
        if not t:
            continue
        t_norm = normalize_synonyms(t)
        ctype = "exclude" if re.search(r"\b(exclude|exclusion|not)\b", t_norm, re.I) else "include"
        scope = "both"
        if re.search(r"\bmetadata\b", t_norm, re.I):
            scope = "metadata"
        elif re.search(r"\bfull\s*text\b|texte?\s*int(é|e)gral", t_norm, re.I):
            scope = "fulltext"
        rows.append({
            "id": f"C{i:02d}",
            "label": t_norm,
            "type": ctype,
            "scope": scope,
            "targets": ["title", "abstract", "keywords"],
            "operators": ["contains"],
            "patterns": [t_norm],
            "weight": 1.0,
            "threshold": 0.6,
            "notes": "",
        })
        i += 1
    return rows


def parse_csv_or_xlsx(path: str) -> List[Dict[str, Any]]:
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
    return rows


def deterministic_clean(rows: List[Dict[str, Any]]) -> List[Criterion]:
    out: List[Criterion] = []
    for idx, r in enumerate(rows, 1):
        # normalize text fields
        label = normalize_synonyms(str(r.get("label") or r.get("Label") or r.get("criterion") or "").strip())
        ctype = (r.get("type") or r.get("Type") or "include").strip().lower()
        scope = (r.get("scope") or r.get("Scope") or "both").strip().lower()
        targets = r.get("targets") or r.get("Targets") or ["title", "abstract", "keywords"]
        if isinstance(targets, str):
            targets = [t.strip() for t in targets.split(";") if t.strip()]
        operators = r.get("operators") or r.get("Operators") or ["contains"]
        if isinstance(operators, str):
            operators = [o.strip().lower() for o in operators.split(";") if o.strip()]
        patterns = r.get("patterns") or r.get("Patterns") or ([label] if label else [])
        if isinstance(patterns, str):
            patterns = [normalize_synonyms(p.strip()) for p in patterns.split(";") if p.strip()]
        weight = float(r.get("weight") or 1.0)
        threshold = float(r.get("threshold") or 0.6)
        notes = str(r.get("notes") or "")

        c = criterion_from_dict({
            "id": r.get("id") or f"C{idx:02d}",
            "label": label,
            "type": ctype,
            "scope": scope,
            "targets": targets,
            "operators": operators,
            "patterns": patterns,
            "weight": weight,
            "threshold": threshold,
            "notes": notes,
        })
        # validate
        c.validate()
        out.append(c)
    return out


def ai_reformulate(criteria: List[Criterion]) -> List[Criterion]:
    """Placeholder for AI refinement. For Batch 1 we simply echo back (idempotent).
    Later we will integrate model calls and keep the same signature.
    """
    return criteria


# Convenience entry-points used by the UI

def harmonize_from_free_text(raw: str) -> List[Criterion]:
    rows = parse_free_text(raw)
    cleaned = deterministic_clean(rows)
    return ai_reformulate(cleaned)


def harmonize_from_rows(rows: List[Dict[str, Any]]) -> List[Criterion]:
    cleaned = deterministic_clean(rows)
    return ai_reformulate(cleaned)
