# -*- coding: utf-8 -*-
"""
criteria.py — Criteria ingestion + normalization for Screen A (metadata-only) — Contract v2

This module is intentionally "boring and strict":
- It emits *stage-explicit* criteria rows for the v2 pipeline: EH → IH → EL → IL.
- It prevents accidental v1/v2 mixing by enforcing:
    • EH/IH = heuristic operators (contains/equals/regex/…)
    • EL/IL = LLM operator only (operator == "llm")

Primary consumer:
- plugin.py: calls parse_criteria_text(text) and passes the resulting list[dict] to metadata.screen_metadata(...).

Primary engine expectations (metadata.py):
- Each criterion is a dict with (at minimum):
    stage (EH/IH/EL/IL), id, label, operator, target, what, enabled, order
  Plus optional: threshold (for llm), scope/type/weight/how (ignored by v2 engine if present)

Supported input formats for parse_criteria_text(text):
1) JSON:
   [
     {"stage":"EH","id":"EH_LANG","label":"Exclude FR","operator":"equals","field":"lang","what":"FR"},
     {"stage":"IH","id":"IH_TOPIC","label":"Topic hit","operator":"contains","field":"title,abstract","what":["autism","ASD"]},
     {"stage":"EL","id":"EL_ANIMAL","label":"Exclude animal-only","operator":"llm","field":"abstract","what":"Animal-only study.", "threshold":0.85}
   ]

2) Pipe table (with optional header):
   stage | id | label | operator | field | what | threshold | enabled
   EH    | EH_LANG | Exclude FR | equals | lang | FR |      | true
   IH    | IH_TOPIC| Topic hit  | contains | title,abstract | autism;ASD | | true
   EL    | EL_ANIMAL | Exclude animal-only | llm | abstract | Animal-only study. | 0.85 | true

3) Sectioned lines:
   [EH]
   EH_LANG | Exclude FR | equals | lang | FR
   [IH]
   IH_TOPIC | Topic hit | contains | title,abstract | autism; ASD
   [EL]
   EL_ANIMAL | Exclude animal-only | llm | abstract | Animal-only study. | 0.85

Notes:
- "field" and "target" are treated as synonyms; output always includes "target".
- "what" is normalized to list[str]. For llm/regex it is treated as a single string item unless JSON provides a list.
- If stage is missing, we try to infer from:
    • section headers [EH]/[IH]/[EL]/[IL]
    • id prefix EH_/IH_/EL_/IL_
  Otherwise we raise an error (strict).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import csv
import io
import json
import os
import re


STAGES: Tuple[str, ...] = ("EH", "IH", "EL", "IL")

# Heuristic operators supported by the v2 metadata engine
HEURISTIC_OPERATORS = {
    "contains",
    "equals",
    "regex",
    "in_list",
    "not_in",
    "gte",
    "lte",
    "between",
}

LLM_OPERATOR = "llm"

# Simple operator aliases (human-friendly → canonical)
_OPERATOR_ALIASES = {
    "==": "equals",
    "=": "equals",
    "eq": "equals",
    "match": "regex",
    "matches": "regex",
    "re": "regex",
    "in": "in_list",
    "notin": "not_in",
    "not in": "not_in",
    "gteq": "gte",
    "ge": "gte",
    "lteq": "lte",
    "le": "lte",
}

_BOOL_TRUE = {"1", "true", "t", "yes", "y", "on"}
_BOOL_FALSE = {"0", "false", "f", "no", "n", "off"}

# Heuristic stages vs LLM stages (contract-safe enforcement)
_HEURISTIC_STAGES = {"EH", "IH"}
_LLM_STAGES = {"EL", "IL"}


# -----------------------------
# Errors
# -----------------------------
@dataclass
class CriteriaParseError(Exception):
    message: str
    errors: List[str]

    def __str__(self) -> str:
        if not self.errors:
            return self.message
        joined = "\n".join(f"- {e}" for e in self.errors)
        return f"{self.message}\n{joined}"


# -----------------------------
# Public API
# -----------------------------
def parse_criteria_text(text: str, *, strict: bool = True) -> List[Dict[str, Any]]:
    """
    Parse criteria from a text blob. See module docstring for accepted formats.

    Returns:
        list[dict] normalized, contract-safe criteria rows (stage-explicit).
    """
    raw = (text or "").strip()
    if not raw:
        return []

    # 1) JSON first (most unambiguous)
    first_nonblank = _first_nonblank_line(raw)
    if first_nonblank and first_nonblank.lstrip().startswith(("{", "[")):
        try:
            obj = json.loads(raw)
            rows = _rows_from_json(obj)
            return normalize_criteria_rows(rows, strict=strict)
        except json.JSONDecodeError:
            # Fall through to text parsing (user might have pasted something JSON-like but invalid)
            pass

    # 2) Table / section formats
    rows = _rows_from_text_table_or_sections(raw)
    return normalize_criteria_rows(rows, strict=strict)


def parse_criteria_file(path: str, *, strict: bool = True, encoding: str = "utf-8") -> List[Dict[str, Any]]:
    """
    Optional helper (not required by plugin.py): load and parse criteria from a file.
    Supports: .json, .txt/.md, .csv
    """
    if not path:
        raise CriteriaParseError("Criteria file path is empty.", [])
    if not os.path.exists(path):
        raise CriteriaParseError(f"Criteria file not found: {path}", [])

    ext = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding=encoding, errors="replace") as f:
        content = f.read()

    if ext == ".json":
        return parse_criteria_text(content, strict=strict)

    if ext in {".txt", ".md"}:
        return parse_criteria_text(content, strict=strict)

    if ext == ".csv":
        rows = _rows_from_csv(content)
        return normalize_criteria_rows(rows, strict=strict)

    # default: try text
    return parse_criteria_text(content, strict=strict)


def normalize_criteria_rows(rows: List[Dict[str, Any]], *, strict: bool = True) -> List[Dict[str, Any]]:
    """
    Normalize + validate criteria rows into the schema used by metadata.py.

    Contract-safe constraints:
    - stage ∈ {EH, IH, EL, IL}
    - EH/IH: operator ∈ HEURISTIC_OPERATORS
    - EL/IL: operator == "llm"
    - id must be unique
    """
    errors: List[str] = []
    out: List[Dict[str, Any]] = []

    # Pre-pass: coerce to dicts
    cleaned: List[Dict[str, Any]] = []
    for i, r in enumerate(rows or []):
        if isinstance(r, dict):
            cleaned.append(dict(r))
        else:
            errors.append(f"Row {i+1}: not a dict (got {type(r).__name__}).")

    # Normalize each row
    seen_ids: set = set()
    auto_counters = {st: 1 for st in STAGES}

    for idx, r in enumerate(cleaned):
        row_err_prefix = f"Row {idx+1}"
        nr: Dict[str, Any] = {}

        # Stage inference: explicit stage > section stage > id prefix
        stage = _coerce_stage(r.get("stage"))
        if not stage:
            # some users use "scope" or "phase" by mistake
            stage = _coerce_stage(r.get("phase") or r.get("scope_stage") or r.get("scope"))
        if not stage:
            stage = _infer_stage_from_id(r.get("id") or r.get("criterion_id") or r.get("name"))
        if not stage:
            errors.append(f"{row_err_prefix}: missing/invalid stage (expected one of {', '.join(STAGES)}).")
            continue
        nr["stage"] = stage

        # Enabled (soft-delete)
        nr["enabled"] = _coerce_bool(r.get("enabled"), default=True)

        # Order (stable presentation + deterministic execution ordering)
        nr["order"] = _coerce_int(r.get("order"), default=(idx + 1))

        # ID
        cid = _safe_str(r.get("id") or r.get("criterion_id") or r.get("name")).strip()
        if not cid:
            cid = f"{stage}_{auto_counters[stage]:03d}"
            auto_counters[stage] += 1
        nr["id"] = cid

        if cid in seen_ids:
            errors.append(f"{row_err_prefix}: duplicate id '{cid}'. IDs must be unique.")
            continue
        seen_ids.add(cid)

        # Label/description
        label = _safe_str(r.get("label") or r.get("criterion_label") or r.get("title")).strip()
        if not label:
            label = cid
        nr["label"] = label
        desc = _safe_str(r.get("description") or r.get("criterion_description")).strip()
        if desc:
            nr["description"] = desc

        # Operator
        op_raw = _safe_str(r.get("operator") or r.get("op")).strip().lower()
        op_raw = _OPERATOR_ALIASES.get(op_raw, op_raw)
        if not op_raw:
            errors.append(f"{row_err_prefix} ({cid}): missing operator.")
            continue

        # Normalize "llm"/"LLM" and enforce stage/operator compatibility
        if op_raw == LLM_OPERATOR:
            op = LLM_OPERATOR
        else:
            op = op_raw

        # Treat some legacy "how" or "method" entries as hints only; DO NOT stage-route on them.
        # If a user put operator blank but how="llm", we keep contract safety: require explicit operator.
        if not op:
            errors.append(f"{row_err_prefix} ({cid}): operator is empty after normalization.")
            continue

        nr["operator"] = op

        # Target/field
        target_raw = r.get("target")
        if target_raw is None:
            target_raw = r.get("field")
        if target_raw is None:
            target_raw = r.get("targets")
        target = _normalize_target(_safe_str(target_raw))
        if not target:
            errors.append(f"{row_err_prefix} ({cid}): missing target/field.")
            continue
        nr["target"] = target

        # What (normalize to list[str])
        what_val = r.get("what")
        if what_val is None:
            what_val = r.get("value")
        what_list = _normalize_what(op, what_val)

        # Validate "what" presence
        if op == LLM_OPERATOR:
            if not what_list or not what_list[0].strip():
                errors.append(f"{row_err_prefix} ({cid}): llm criterion requires a non-empty 'what' sentence.")
                continue
            # House rule: keep only one sentence item for LLM criteria
            nr["what"] = [what_list[0].strip()]
        else:
            if op not in HEURISTIC_OPERATORS:
                errors.append(
                    f"{row_err_prefix} ({cid}): unsupported heuristic operator '{op}'. "
                    f"Allowed: {', '.join(sorted(HEURISTIC_OPERATORS))} or 'llm'."
                )
                continue
            if not what_list:
                errors.append(f"{row_err_prefix} ({cid}): heuristic criterion requires non-empty 'what'.")
                continue
            nr["what"] = [w for w in what_list if w.strip()]

        # Threshold (LLM only; optional for heuristics)
        if op == LLM_OPERATOR:
            nr["threshold"] = _coerce_float(r.get("threshold"), default=0.85)
        else:
            if r.get("threshold") is not None:
                # Keep it for completeness, but it won't be used by heuristic evaluation
                nr["threshold"] = _coerce_float(r.get("threshold"), default=0.0)

        # Optional extra fields (kept if provided; ignored by v2 engine unless later reused)
        for opt_key in ("type", "scope", "how", "weight"):
            if opt_key in r and r.get(opt_key) is not None:
                nr[opt_key] = r.get(opt_key)

        # Contract-safe stage/operator enforcement
        if stage in _HEURISTIC_STAGES and op == LLM_OPERATOR:
            errors.append(
                f"{row_err_prefix} ({cid}): stage {stage} is heuristic; operator must NOT be 'llm'. "
                f"Move this criterion to EL/IL or change operator."
            )
            continue

        if stage in _LLM_STAGES and op != LLM_OPERATOR:
            errors.append(
                f"{row_err_prefix} ({cid}): stage {stage} is LLM; operator must be 'llm'. "
                f"Move this criterion to EH/IH or change operator to 'llm'."
            )
            continue

        out.append(nr)

    if errors and strict:
        raise CriteriaParseError("Criteria parsing/validation failed.", errors)

    # If not strict, drop invalid rows but keep the rest
    return out


def summarize(criteria_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Small helper for UI/debug: stage distribution + enabled counts.
    """
    dist = {st: 0 for st in STAGES}
    enabled_dist = {st: 0 for st in STAGES}
    for r in criteria_rows or []:
        if not isinstance(r, dict):
            continue
        st = _coerce_stage(r.get("stage")) or ""
        if st in dist:
            dist[st] += 1
            if _coerce_bool(r.get("enabled"), True):
                enabled_dist[st] += 1
    return {"total": sum(dist.values()), "by_stage": dist, "enabled_by_stage": enabled_dist}


def default_criteria_template_text() -> str:
    """
    Returns a paste-ready template that works with parse_criteria_text().
    (plugin.py may choose to display this as a starting point.)
    """
    return (
        "stage | id | label | operator | field | what | threshold | enabled\n"
        "EH | EH_LANG | Exclude FR language | equals | lang | FR | | true\n"
        "EH | EH_YEAR | Exclude year < 2018 | gte | year | 2018 | | true\n"
        "IH | IH_TOPIC | Topic keywords present | contains | title,abstract,keywords | autism;ASD;neurodivers | | true\n"
        "IH | IH_CONTEXT | Context keywords present | contains | title,abstract,keywords | workplace;vocational;training | | true\n"
        "EL | EL_ANIMAL | Exclude animal-only studies | llm | abstract | Animal-only study (non-human subjects). | 0.85 | true\n"
        "IL | IL_RELEV | Confirm relevance to research question | llm | title,abstract | Relevant to the target research question and population/context. | 0.85 | true\n"
    )


# -----------------------------
# Internals
# -----------------------------
def _first_nonblank_line(text: str) -> str:
    for ln in text.splitlines():
        s = ln.strip()
        if s and not s.startswith(("#", "//")):
            return s
    return ""


def _rows_from_json(obj: Any) -> List[Dict[str, Any]]:
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        # common wrappers
        for k in ("criteria", "rows", "items"):
            v = obj.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        # single row dict
        return [obj]
    return []


def _rows_from_csv(content: str) -> List[Dict[str, Any]]:
    buf = io.StringIO(content)
    reader = csv.DictReader(buf)
    rows: List[Dict[str, Any]] = []
    for r in reader:
        if not isinstance(r, dict):
            continue
        # DictReader returns OrderedDict[str,str], keep raw then normalize later
        rows.append(dict(r))
    return rows


def _rows_from_text_table_or_sections(text: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    current_stage: Optional[str] = None

    # Detect header table (first meaningful non-section line with "stage" etc.)
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    meaningful = [ln for ln in lines if ln.strip() and not ln.strip().startswith(("#", "//"))]
    if not meaningful:
        return []

    # If first meaningful line looks like a table header, use it.
    header_cols = None
    header_sep = None

    first = meaningful[0].strip()
    if first.startswith("[") and first.endswith("]"):
        # sectioned format; header not assumed
        pass
    else:
        header_sep = _pick_separator(first)
        if header_sep:
            cols = [c.strip().lower() for c in first.split(header_sep)]
            if any(c in {"stage", "id", "operator", "field", "target", "what"} for c in cols):
                header_cols = cols

    # Parse
    start_idx = 1 if header_cols else 0
    for ln in meaningful[start_idx:]:
        s = ln.strip()
        if not s or s.startswith(("#", "//")):
            continue

        # Section header [EH]/[IH]/[EL]/[IL]
        if s.startswith("[") and s.endswith("]") and len(s) <= 8:
            maybe = s[1:-1].strip().upper()
            if maybe in STAGES:
                current_stage = maybe
                continue

        sep = _pick_separator(s) or header_sep
        if not sep:
            # As a last resort, allow comma-separated *only* if it has enough commas
            if s.count(",") >= 4:
                sep = ","
            else:
                # skip unparseable line
                rows.append({"_parse_error_line": s})
                continue

        parts = [p.strip() for p in s.split(sep)]
        parts = [p for p in parts if p != "" or sep == ","]  # keep empty tokens for CSV-ish

        if header_cols:
            # Map by header
            d: Dict[str, Any] = {}
            for i, col in enumerate(header_cols):
                if i >= len(parts):
                    continue
                d[col] = parts[i]
            # Apply section stage if missing
            if current_stage and not d.get("stage"):
                d["stage"] = current_stage
            rows.append(d)
        else:
            # No header: interpret by position
            d = _map_parts_no_header(parts, current_stage=current_stage)
            rows.append(d)

    return rows


def _map_parts_no_header(parts: List[str], *, current_stage: Optional[str]) -> Dict[str, Any]:
    # With current_stage: id | label | operator | field | what | threshold? | enabled?
    # Without current_stage: stage | id | label | operator | field | what | threshold? | enabled?
    d: Dict[str, Any] = {}
    p = parts

    if current_stage:
        d["stage"] = current_stage
        if len(p) >= 1:
            d["id"] = p[0]
        if len(p) >= 2:
            d["label"] = p[1]
        if len(p) >= 3:
            d["operator"] = p[2]
        if len(p) >= 4:
            d["field"] = p[3]
        if len(p) >= 5:
            d["what"] = p[4]
        if len(p) >= 6:
            d["threshold"] = p[5]
        if len(p) >= 7:
            d["enabled"] = p[6]
        return d

    # No section stage
    if len(p) >= 1:
        d["stage"] = p[0]
    if len(p) >= 2:
        d["id"] = p[1]
    if len(p) >= 3:
        d["label"] = p[2]
    if len(p) >= 4:
        d["operator"] = p[3]
    if len(p) >= 5:
        d["field"] = p[4]
    if len(p) >= 6:
        d["what"] = p[5]
    if len(p) >= 7:
        d["threshold"] = p[6]
    if len(p) >= 8:
        d["enabled"] = p[7]
    return d


def _pick_separator(line: str) -> Optional[str]:
    # Prefer pipe and tab for human tables
    if "|" in line:
        return "|"
    if "\t" in line:
        return "\t"
    # Semicolon-separated tables (rare; conflicts with what lists)
    # Only treat as separator if it looks like a table (many semicolons)
    if line.count(";") >= 4:
        return ";"
    return None


def _infer_stage_from_id(val: Any) -> str:
    s = _safe_str(val).strip().upper()
    for st in STAGES:
        if s.startswith(st + "_") or s == st:
            return st
    return ""


def _coerce_stage(val: Any) -> str:
    s = _safe_str(val).strip().upper()
    if not s:
        return ""
    # Allow "E/H" "I/H" etc
    s = s.replace("/", "").replace("-", "").replace("_", "")
    # Map EH/IH/EL/IL from condensed
    if s in {"EH", "IH", "EL", "IL"}:
        return s
    return ""


def _normalize_target(val: str) -> str:
    # metadata.py expects comma-separated list of field tokens; keep order, trim blanks
    s = (val or "").strip()
    if not s:
        return ""
    # Allow "title;abstract" or "title / abstract"
    s = s.replace(";", ",")
    s = s.replace("/", ",")
    toks = [t.strip().lower() for t in s.split(",")]
    toks = [t for t in toks if t]
    return ",".join(toks)


def _normalize_what(op: str, what_val: Any) -> List[str]:
    # If list already, use it
    if isinstance(what_val, list):
        out = [_safe_str(x).strip() for x in what_val if _safe_str(x).strip()]
        return out

    s = _safe_str(what_val).strip()
    if not s:
        return []

    # For regex + llm, treat as single string item (unless JSON already provided list)
    if op in {LLM_OPERATOR, "regex"}:
        return [s]

    # For numeric operators, keep token(s) but allow comma/semicolon separators
    if op in {"gte", "lte", "between"}:
        # between can be "2018..2024" or "2018,2024"
        s2 = s.replace("..", ",").replace(";", ",")
        toks = [t.strip() for t in s2.split(",") if t.strip()]
        return toks

    # Default: split by ';' or ',' (common keyword lists)
    s2 = s.replace(";", ",")
    toks = [t.strip() for t in s2.split(",") if t.strip()]
    return toks


def _coerce_bool(val: Any, default: bool = True) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    s = _safe_str(val).strip().lower()
    if not s:
        return default
    if s in _BOOL_TRUE:
        return True
    if s in _BOOL_FALSE:
        return False
    return default


def _coerce_int(val: Any, default: int = 0) -> int:
    try:
        if val is None or _safe_str(val).strip() == "":
            return int(default)
        return int(float(_safe_str(val).strip()))
    except Exception:
        return int(default)


def _coerce_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or _safe_str(val).strip() == "":
            return float(default)
        return float(_safe_str(val).strip())
    except Exception:
        return float(default)


def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    try:
        return str(x)
    except Exception:
        return repr(x)


# -----------------------------
# CLI smoke test (optional)
# -----------------------------
if __name__ == "__main__":
    demo = default_criteria_template_text()
    try:
        parsed = parse_criteria_text(demo, strict=True)
        print("OK:", summarize(parsed))
        print(json.dumps(parsed[:2], indent=2, ensure_ascii=False))
    except CriteriaParseError as e:
        print(str(e))
