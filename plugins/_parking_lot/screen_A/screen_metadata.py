# -*- coding: utf-8 -*-
"""
Created on Mon Sep 22 11:07:38 2025

@author: alere
"""

# File: plugins/screen_A/screen_metadata.py
# Batch 2 — Metadata screening engine (soft scores) + CSV/XLSX loader for A
# LLM + safe-funneling extensions:
# - Header normalization & presence flags
# - Optional LLM decision fusion (conservative, extractive-only)
# - score_so_far / max_remaining / drop_by_upper_bound for safe pruning

from __future__ import annotations
from typing import Dict, Any, List, Tuple, Iterable, Optional, Set
import math
import re
import csv
import hashlib

try:
    import pandas as pd
    PANDAS_OK = True
except Exception:
    pd = None
    PANDAS_OK = False

from .criteria_schema import normalize_synonyms

# ---------------------------------------------------------------------------
# Public options / defaults
# ---------------------------------------------------------------------------

DEFAULT_PASS_THR = 0.60
DEFAULT_BORDER_THR = 0.40

# Missing/unknown handling (soft) when NO LLM provided or evidence unavailable
MISSING_SCORE_INCLUDE = 0.50   # include criterion unknown -> neutral-ish
MISSING_SCORE_EXCLUDE = 0.70   # exclude criterion unknown -> lenient

# Policy when fields are missing in the CSV
MISSING_FIELDS_POLICY_SAFE = "unknown"  # do not punish; allow later rescue
MISSING_FIELDS_POLICY_STRICT = "negative"  # treat as negative evidence (not recommended)

# ---------------------------------------------------------------------------
# Header normalization
# ---------------------------------------------------------------------------

# Map many possible input column names -> canonical keys we use internally
HEADER_MAP = {
    # a_id / ids
    "a_id": "a_id", "id": "a_id", "uid": "a_id", "local_id": "a_id",
    # title
    "title": "title", "ti": "title", "article_title": "title",
    # abstract
    "abstract": "abstract", "ab": "abstract", "summary": "abstract",
    # keywords
    "keywords": "keywords", "kw": "keywords", "mesh": "keywords",
    # year / date
    "year": "year", "pub_year": "year", "py": "year", "date": "year",
    # language
    "language": "lang", "lang": "lang", "la": "lang",
    # venue / journal / conf
    "venue": "venue", "journal": "venue", "source": "venue", "conference": "venue",
    # identifiers
    "doi": "doi", "pmid": "pmid", "pmcid": "pmcid",
    "arxiv": "arxiv",
    # type
    "type": "doc_type", "document_type": "doc_type", "pub_type": "doc_type",
}

CANON_ORDER = ["a_id", "doi", "title", "abstract", "keywords", "year", "lang", "venue", "doc_type", "pmid", "pmcid", "arxiv"]

def _normalize_row_keys(r: Dict[str, Any], idx: int) -> Dict[str, Any]:
    """Lowercase incoming keys, map to canonical, ensure a_id."""
    nr: Dict[str, Any] = {}
    for k, v in r.items():
        lk = k.lower() if isinstance(k, str) else k
        canon = HEADER_MAP.get(lk, lk)
        nr[canon] = v
    if "a_id" not in nr or (nr.get("a_id") in (None, "", "nan")):
        nr["a_id"] = nr.get("id") or (idx + 1)
    return nr

def _presence_flags(item: Dict[str, Any]) -> Dict[str, bool]:
    """Track which metadata fields are present (non-empty after str())."""
    def _has(x: Any) -> bool:
        return (str(x).strip() != "" and x is not None and str(x).lower() != "nan")
    return {
        "has_title": _has(item.get("title")),
        "has_abstract": _has(item.get("abstract")),
        "has_keywords": _has(item.get("keywords")),
        "has_year": _has(item.get("year")),
        "has_lang": _has(item.get("lang")),
        "has_venue": _has(item.get("venue")),
        "has_doc_type": _has(item.get("doc_type")),
    }

# ---------------------------------------------------------------------------
# Loader (CSV/XLSX) with normalization
# ---------------------------------------------------------------------------

def parse_A_csv_xlsx(path: str) -> List[Dict[str, Any]]:
    """Load A items from CSV/XLSX, normalize headers, ensure a_id, add presence flags hash."""
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

    normed: List[Dict[str, Any]] = []
    for i, r in enumerate(rows):
        nr = _normalize_row_keys(r, i)
        # order (optional, just to keep dicts tidy)
        nr = {k: nr.get(k) for k in CANON_ORDER if k in nr} | {k: v for k, v in nr.items() if k not in CANON_ORDER}
        # presence flags
        pres = _presence_flags(nr)
        nr["_presence"] = pres
        # small content hash (useful for caching upstream)
        to_hash = (str(nr.get("title") or "") + "\n" +
                   str(nr.get("abstract") or "") + "\n" +
                   str(nr.get("keywords") or ""))
        nr["_content_hash"] = hashlib.sha1(to_hash.encode("utf-8", errors="ignore")).hexdigest()
        normed.append(nr)
    return normed

# ---------------------------------------------------------------------------
# Public API: metadata screening with optional LLM fusion
# ---------------------------------------------------------------------------

def screen_metadata(
    item: Dict[str, Any],
    criteria: List[Dict[str, Any]],
    *,
    pass_thr: float = DEFAULT_PASS_THR,
    border_thr: float = DEFAULT_BORDER_THR,
    # LLM fusion (optional): {(a_id, criterion_id): {"decision","conf","field","quote","span"}}
    llm_decisions: Optional[Dict[Tuple[Any, Any], Dict[str, Any]]] = None,
    # Which criteria are considered "judged" so far (for score_so_far / max_remaining)
    judged_criteria_ids: Optional[Set[Any]] = None,
    # Missing field policy at metadata stage
    missing_fields_policy: str = MISSING_FIELDS_POLICY_SAFE,
    # Treat unknown/missing evidence as these soft scores when no LLM (legacy behavior)
    missing_score_include: float = MISSING_SCORE_INCLUDE,
    missing_score_exclude: float = MISSING_SCORE_EXCLUDE,
) -> Dict[str, Any]:
    """
    Compute a soft metadata score using include/exclude criteria, optionally fusing LLM decisions.
    Returns:
      {
        "score": float,
        "label": "pass|borderline|fail",
        "per_criterion": [
            {
              "id","type","weight",
              "rule_score","matched",
              "llm_decision","llm_conf","llm_field","llm_quote_span","llm_used",
              "fused_score"
            },...
        ],
        "presence": {...},
        "wsum": float,
        "score_so_far": float,          # weighted over judged_criteria_ids (if provided)
        "max_remaining": float,         # safe upper bound given unjudged criteria
        "drop_by_upper_bound": bool     # whether score_so_far + max_remaining < pass_thr
      }
    """
    a_id = item.get("a_id")
    pres = item.get("_presence") or _presence_flags(item)

    # collect only metadata-relevant criteria
    meta_criteria = [c for c in criteria if (c.get("scope", "both") in ("metadata", "both"))]

    per: List[Dict[str, Any]] = []
    wsum_all = 0.0
    ssum_all = 0.0

    # also accumulate judged vs remaining for upper-bound math
    judged_ids: Set[Any] = set(judged_criteria_ids) if judged_criteria_ids else {c.get("id") for c in meta_criteria}
    wsum_judged = 0.0
    ssum_judged = 0.0
    wsum_remaining = 0.0

    for c in meta_criteria:
        cid = c.get("id")
        ctype = (c.get("type") or "include").lower()
        w = float(c.get("weight", 1.0))

        rule_score, matched = _criterion_score_metadata(
            item, c,
            missing_fields_policy=missing_fields_policy,
            missing_score_include=missing_score_include,
            missing_score_exclude=missing_score_exclude
        )

        # LLM fusion (if provided)
        lkey = (a_id, cid)
        llm = (llm_decisions or {}).get(lkey)
        fused_score, llm_used, llm_fields = _fuse_rule_with_llm(ctype, rule_score, llm, item)

        per.append({
            "id": cid,
            "type": ctype,
            "weight": w,
            "rule_score": rule_score,
            "matched": matched,
            "llm_decision": (llm or {}).get("decision"),
            "llm_conf": float((llm or {}).get("conf", 0.0)) if llm else None,
            "llm_field": (llm or {}).get("field"),
            "llm_quote_span": (llm or {}).get("span"),
            "llm_used": llm_used,
            "fused_score": fused_score,
        })

        # overall aggregates (use fused score)
        wsum_all += w
        ssum_all += w * fused_score

        # judged vs remaining
        if cid in judged_ids:
            wsum_judged += w
            ssum_judged += w * fused_score
        else:
            wsum_remaining += w  # max remaining assumes future score=1 for include, 1 for exclude (optimistic upper bound)

    overall = (ssum_all / wsum_all) if wsum_all > 0 else 0.0
    label = _label_from_score(overall, pass_thr, border_thr)

    # score_so_far (only judged subset), max_remaining = (remaining weight / total weight)
    score_so_far = (ssum_judged / wsum_all) if wsum_all > 0 else 0.0
    max_remaining = (wsum_remaining / wsum_all) if wsum_all > 0 else 0.0
    drop_by_upper_bound = (score_so_far + max_remaining) < pass_thr if wsum_all > 0 else False

    return {
        "score": overall,
        "label": label,
        "per_criterion": per,
        "presence": pres,
        "wsum": wsum_all,
        "score_so_far": score_so_far,
        "max_remaining": max_remaining,
        "drop_by_upper_bound": bool(drop_by_upper_bound),
    }

# ---------------------------------------------------------------------------
# Labeling
# ---------------------------------------------------------------------------

def _label_from_score(score: float, pass_thr: float, border_thr: float) -> str:
    if score >= pass_thr:
        return "pass"
    if score >= border_thr:
        return "borderline"
    return "fail"

# ---------------------------------------------------------------------------
# Rule scoring (legacy deterministic operators)
# ---------------------------------------------------------------------------

def _get_text_fields(item: Dict[str, Any]) -> Dict[str, str]:
    return {
        "title": str(item.get("title") or ""),
        "abstract": str(item.get("abstract") or ""),
        "keywords": str(item.get("keywords") or ""),
        "venue": str(item.get("venue") or ""),
        "lang": str(item.get("lang") or ""),
        "year": str(item.get("year") or ""),
        "doc_type": str(item.get("doc_type") or ""),
    }

def _criterion_score_metadata(
    item: Dict[str, Any],
    c: Dict[str, Any],
    *,
    missing_fields_policy: str = MISSING_FIELDS_POLICY_SAFE,
    missing_score_include: float = MISSING_SCORE_INCLUDE,
    missing_score_exclude: float = MISSING_SCORE_EXCLUDE,
) -> Tuple[float, str]:
    """Return (rule_score, matched_label) WITHOUT any LLM info."""
    ctype = (c.get("type") or "include").lower()
    targets: List[str] = c.get("targets") or ["title", "abstract", "keywords"]
    ops: List[str] = c.get("operators") or ["contains"]
    patterns: List[str] = c.get("patterns") or [c.get("label") or ""]

    fields = _get_text_fields(item)
    # pre-normalize all text
    fields_norm = {k: normalize_synonyms(v.lower()) for k, v in fields.items()}
    pats_norm = [normalize_synonyms(str(p).lower()) for p in patterns]

    matched_any = False
    known_any = False

    for tgt in targets:
        val = fields_norm.get(tgt)
        if val is None or val.strip() == "":
            continue
        known_any = True
        for op in ops:
            if _match(op, val, pats_norm):
                matched_any = True
                break
        if matched_any:
            break

    # Missing-fields policy
    if not known_any:
        if missing_fields_policy == MISSING_FIELDS_POLICY_STRICT:
            # strict: treat missing fields as hard negative for include, hard positive for exclude
            if ctype == "include":
                return 0.0, "unknown-strict"
            else:
                return 1.0, "unknown-strict"
        # safe/unknown (default): soft neutral/lenient scores
        if ctype == "include":
            return missing_score_include, "unknown"
        else:
            return missing_score_exclude, "unknown"

    if ctype == "include":
        if matched_any:
            return 1.0, "match"
        return 0.0, "no-match"
    else:  # exclude
        if matched_any:
            return 0.0, "match-exclude"
        return 1.0, "no-match"

def _match(op: str, text: str, patterns: List[str]) -> bool:
    op = op.lower()
    if op in ("contains", "in"):
        return any(p in text for p in patterns)
    if op == "equals":
        return any(text.strip() == p.strip() for p in patterns)
    if op == "not_in":
        return all(p not in text for p in patterns)
    if op == "regex":
        try:
            return any(re.search(p, text, flags=re.I) for p in patterns)
        except re.error:
            return False
    if op in ("gte", "lte", "between"):
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

# ---------------------------------------------------------------------------
# LLM fusion (conservative, extractive-only)
# ---------------------------------------------------------------------------

def _fuse_rule_with_llm(
    ctype: str,
    rule_score: float,
    llm: Optional[Dict[str, Any]],
    item: Dict[str, Any],
) -> Tuple[float, bool, Dict[str, Any]]:
    """
    Return (fused_score, llm_used, fields_dict).
    Conservative rules:
      - Only use LLM if it provides an exact substring quote from a field we provided.
      - If decision is 'uncertain' or evidence invalid -> ignore LLM, keep rule_score.
      - include: fused = max(rule_score, conf if decision=='meet' else 0)
      - exclude: fused = min(rule_score, (1 - conf) if decision=='meet'(exclude-hit) else 1)
    """
    if not llm:
        return rule_score, False, {}

    decision = str(llm.get("decision") or "").lower()
    conf = float(llm.get("conf", 0.0) or 0.0)
    field = str(llm.get("field") or "")
    quote = str(llm.get("quote") or "")
    span = llm.get("span")

    # Validate extractive evidence: field exists and quote is an exact substring
    fields_text = _get_text_fields(item)
    field_text = fields_text.get(field, "")
    if decision not in ("meet", "not_meet", "uncertain"):
        return rule_score, False, {}
    if decision == "uncertain":
        return rule_score, False, {}
    if not field_text or not quote or quote not in field_text:
        # Evidence not extractive -> ignore LLM
        return rule_score, False, {}

    # Fuse conservatively by criterion polarity
    if ctype == "include":
        if decision == "meet":
            fused = max(rule_score, max(0.0, min(1.0, conf)))
        else:  # not_meet
            fused = max(0.0, min(1.0, 0.0))
    else:  # exclude type
        if decision == "meet":  # exclusion condition met
            fused = min(rule_score, max(0.0, min(1.0, 1.0 - conf)))
        else:  # not_meet -> prefer rule_score but cap at 1
            fused = min(1.0, max(0.0, rule_score))

    return fused, True, {"field": field, "quote": quote, "span": span}
