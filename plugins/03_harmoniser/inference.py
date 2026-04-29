# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
inference.py - Plugin 03 Harmoniser: rule-based criterion inference.

Concerns owned by this module:
  - Rule-based stage / operator / target / operand inference for a single
    free-text criterion label (_infer_criterion_details)
  - Per-row schema and semantics validation against the corpus columns
    (_validate_row)
  - Inference-stage default constants (DEFAULT_TEXT_TARGET,
    DEFAULT_THRESHOLD) consumed both by inference and by the View when
    assembling the final harmonised rows.

The inference engine evaluates six pattern categories in sequence
(language, year, document type, venue/journal, DOI, keyword-in-text)
and falls back to operator='llm' (EL/IL stage) when no deterministic
pattern matches. See manuscript Algorithm 1 for the full specification.

Imports only from .parser; no GUI, no LLM dependencies. Safe to reuse
standalone.

Extracted from `plugin.py` in Conv 4 of the v3.1.0 refactor. Behavior is
preserved verbatim; the `criteria_harmonized.csv` golden regression test
guards byte-identity of downstream output.
"""

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .parser import (
    STAGES,
    OPERATORS,
    _safe_str,
    _canonicalize_targets,
    _parse_what_cell,
)


# ============================
# Inference-stage defaults
# ============================

# Default operand target string when no specific column can be inferred and the
# corpus has no columns at all (effectively a no-op fallback). Set dynamically
# at the call site by `_get_best_text_targets()` in normal use.
DEFAULT_TEXT_TARGET = ""

# Default LLM-confidence threshold attached to EL/IL stage rows when no
# explicit threshold is provided. Researcher-tunable per-row in the View.
DEFAULT_THRESHOLD = 0.60


def _infer_criterion_details(
    crit_id: str,
    crit_type: str,
    label: str,
    a_columns: List[str],
    default_text_target: str = "title,abstract,keywords",
) -> Dict[str, Any]:
    """
    Rule-based inference of stage, operator, target, and what from criterion label.

    Returns dict: {stage, operator, target, what(list[str])}

    Stages:
      - EH/IH for hard metadata rules (language/year/doc_type/venue/doi, etc.)
      - EL/IL for semantic rules (operator=llm) with threshold

    Note: targets MUST exist in a_columns (case-sensitive), so we pick from available columns.
    """
    label_lower = (label or "").lower()

    # Defaults: semantic rule
    stage = "IL" if crit_type == "include" else "EL"
    operator = "llm"
    target = default_text_target or (a_columns[0] if a_columns else DEFAULT_TEXT_TARGET)
    what = [label] if label else [""]

    # Helper: pick first existing column among candidates (case-insensitive)
    def pick_col(cands: List[str]) -> Optional[str]:
        for cand in cands:
            for c in a_columns:
                if c == cand:
                    return c
            for c in a_columns:
                if c.lower() == cand.lower():
                    return c
        return None

    # 1) Language criteria
    lang_patterns = [
        r"written in\s+([a-zA-Z]+)",
        r"language is\s+([a-zA-Z]+)",
        r"in\s+([a-zA-Z]+)\s+language",
        r"\b(english|french|spanish|german|portuguese|italian)\b",
    ]
    for pattern in lang_patterns:
        m = re.search(pattern, label_lower)
        if m:
            lang = m.group(1).strip().capitalize()
            lang_target = pick_col(["language", "lang", "publication_language"])
            if lang_target:
                target = lang_target
                operator = "equals"
                what = [lang]
                stage = "IH" if crit_type == "include" else "EH"
                return {"stage": stage, "operator": operator, "target": target, "what": what}

    # 2) Year criteria
    year_target = pick_col(["year", "publication_year", "pub_year", "date_year"])
    if year_target:
        # Range: 2010-2020
        m = re.search(r"\b(19\d{2}|20\d{2})\b\s*[-–]\s*\b(19\d{2}|20\d{2})\b", label_lower)
        if m:
            target = year_target
            operator = "between"
            what = [m.group(1), m.group(2)]
            stage = "IH" if crit_type == "include" else "EH"
            return {"stage": stage, "operator": operator, "target": target, "what": what}

        # After/since/from >= YEAR
        m = re.search(r"(after|since|from|>=)\s*(19\d{2}|20\d{2})", label_lower)
        if m:
            target = year_target
            operator = "gte"
            what = [m.group(2)]
            stage = "IH" if crit_type == "include" else "EH"
            return {"stage": stage, "operator": operator, "target": target, "what": what}

        # Before/until <= YEAR
        m = re.search(r"(before|until|<=)\s*(19\d{2}|20\d{2})", label_lower)
        if m:
            target = year_target
            operator = "lte"
            what = [m.group(2)]
            stage = "IH" if crit_type == "include" else "EH"
            return {"stage": stage, "operator": operator, "target": target, "what": what}

        # Published YEAR (single)
        m = re.search(r"\b(19\d{2}|20\d{2})\b", label_lower)
        if m and any(k in label_lower for k in ["published", "publication", "year", "date"]):
            target = year_target
            operator = "gte"
            what = [m.group(1)]
            stage = "IH" if crit_type == "include" else "EH"
            return {"stage": stage, "operator": operator, "target": target, "what": what}

    # 3) Document type criteria
    doc_type_target = pick_col(["doc_type", "document_type", "publication_type", "type", "pub_type"])
    if doc_type_target and any(k in label_lower for k in ["type", "document", "publication type", "study type", "article type", "conference"]):
        doc_type_map = {
            "randomized": "randomized",
            "randomised": "randomized",
            "rct": "randomized",
            "systematic review": "systematic review",
            "meta-analysis": "meta-analysis",
            "meta analysis": "meta-analysis",
            "review": "review",
            "protocol": "protocol",
            "conference paper": "conference",
            "conference": "conference",
            "proceedings": "conference",
            "thesis": "thesis",
            "dissertation": "thesis",
            "case report": "case report",
        }

        for key, value in doc_type_map.items():
            if key in label_lower:
                target = doc_type_target
                operator = "equals"
                what = [value]
                stage = "IH" if crit_type == "include" else "EH"
                return {"stage": stage, "operator": operator, "target": target, "what": what}

        if "conference" in label_lower or "proceedings" in label_lower:
            target = doc_type_target
            operator = "contains"
            what = ["proceedings"] if "proceedings" in label_lower else ["conference"]
            stage = "IH" if crit_type == "include" else "EH"
            return {"stage": stage, "operator": operator, "target": target, "what": what}

    # 4) Venue/Journal criteria
    if any(k in label_lower for k in ["venue", "journal", "conference", "published in"]):
        venue_target = pick_col(["venue", "journal", "source", "conference"])
        if venue_target:
            target = venue_target
            operator = "contains"
            # extract after "published in" or "in"
            m = re.search(r"(published in|in)\s+(.+)$", label, re.IGNORECASE)
            what = [m.group(2).strip()] if m else [label]
            stage = "IH" if crit_type == "include" else "EH"
            return {"stage": stage, "operator": operator, "target": target, "what": what}

    # 5) DOI criteria
    if "doi" in label_lower:
        doi_target = pick_col(["doi"])
        if doi_target:
            target = doi_target
            if "no doi" in label_lower or "has no doi" in label_lower or "without doi" in label_lower:
                operator = "equals"
                what = [""]
            elif "has doi" in label_lower or "with doi" in label_lower:
                operator = "not_in"
                what = [""]  # DOI not empty
            else:
                operator = "not_in"
                what = [""]  # default to DOI present
            stage = "IH" if crit_type == "include" else "EH"
            return {"stage": stage, "operator": operator, "target": target, "what": what}

    # 6) Simple text search in title/abstract/keywords
    text_search_phrases = ["title", "abstract", "keywords", "keyword", "mention", "contains", "must include", "include term"]
    if any(phrase in label_lower for phrase in text_search_phrases):
        available_text_fields = []
        for field in ["title", "abstract", "keywords"]:
            if field in a_columns:
                available_text_fields.append(field)
        if available_text_fields:
            target = ",".join(available_text_fields)
            operator = "contains"

            # Extract quoted phrases
            quoted = re.findall(r'"([^"]+)"', label)
            if quoted:
                what = [q.strip() for q in quoted if q.strip()]
            else:
                # Try "mention X"
                m = re.search(r"\bmention\s+(.+)$", label, re.IGNORECASE)
                if m:
                    # split by OR
                    tail = m.group(1)
                    parts = re.split(r"\s+\bor\b\s+", tail, flags=re.IGNORECASE)
                    what = [p.strip(" .;:") for p in parts if p.strip(" .;:")]
                else:
                    # Try "contains X"
                    m = re.search(r"\bcontains\s+(.+)$", label, re.IGNORECASE)
                    if m:
                        tail = m.group(1)
                        parts = re.split(r"\s+\bor\b\s+", tail, flags=re.IGNORECASE)
                        what = [p.strip(" .;:") for p in parts if p.strip(" .;:")]
                    else:
                        # fallback: use label itself
                        what = [label]

            stage = "IL" if crit_type == "include" else "EL"
            return {"stage": stage, "operator": operator, "target": target, "what": what}

    return {"stage": stage, "operator": operator, "target": target, "what": what}


def _validate_row(row: Dict[str, Any], a_columns: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Return (errors, warnings)."""
    errs: List[str] = []
    warns: List[str] = []

    stage = _safe_str(row.get("stage")).strip().upper()
    if stage not in STAGES:
        errs.append("Invalid stage")

    crit_id = _safe_str(row.get("id")).strip()
    if not crit_id:
        errs.append("Missing id")

    typ = _safe_str(row.get("type")).strip().lower()
    if typ not in {"include", "exclude"}:
        errs.append("Invalid type")

    op = _safe_str(row.get("operator")).strip().lower()
    if op not in OPERATORS:
        errs.append("Invalid operator")

    target = _safe_str(row.get("target")).strip()
    if not target:
        errs.append("Missing target")

    if a_columns:
        canon, unknown = _canonicalize_targets(target, a_columns)
        row["target"] = canon
        if unknown:
            errs.append(f"Unknown target(s): {', '.join(unknown)}")

    what_list = row.get("what")
    if not isinstance(what_list, list):
        warns.append("'what' was not a list; coerced")
        row["what"] = _parse_what_cell(op or "contains", what_list)

    what_list = row.get("what") or []
    if op == "between" and len(what_list) != 2:
        errs.append("between requires exactly 2 values")
    if op in {"gte", "lte", "equals"} and len(what_list) > 1:
        warns.append(f"{op} usually expects 1 value")
    if op == "llm":
        if len(what_list) != 1:
            errs.append("llm requires exactly 1 sentence in what")

    thr = _safe_str(row.get("threshold", "")).strip()
    if stage in {"EH", "IH"}:
        if thr:
            warns.append("threshold ignored for EH/IH; will be blanked")
            row["threshold"] = ""
    else:
        if not thr:
            row["threshold"] = f"{DEFAULT_THRESHOLD:.2f}"
        else:
            try:
                v = float(thr)
                if v < 0.0 or v > 1.0:
                    errs.append("threshold must be between 0 and 1")
            except Exception:
                errs.append("threshold must be a number")

    return errs, warns

