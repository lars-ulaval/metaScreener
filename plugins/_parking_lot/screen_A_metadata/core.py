# -*- coding: utf-8 -*-
"""
core.py — shared primitives for Screen A (metadata-only) screener (Contract v2)

Design constraints
- Pure Python, no network calls, no heavy dependencies.
- Stable “single source of truth” constants and small helpers that multiple modules can share.
- Must remain compatible with criteria.py imports:
    ALLOWED_TYPES, ALLOWED_SCOPE, ALLOWED_OPERATORS,
    coerce_list, coerce_bool, normalize_text_for_match,
    (optionally) TARGETABLE_FIELDS

Contract v2 vocabulary
- Stages: EH -> IH -> EL -> IL
- Criterion statuses: MET | FAILED | MISSING | UNCERTAIN
- Stage outcomes: OUT | PASS_CLEAN | PASS_FLAGGED | REVIEW

This module does NOT implement screening logic. It only provides:
- Constants/enums
- Deterministic normalization
- Safe coercions
- Optional canonicalization helpers (useful for ingest and reporting)
- Optional progress/log helpers (UI-safe)

Keep this file small and boring: it should almost never change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import re
import time
import unicodedata


# =============================================================================
# Contract v2 constants (single source of truth)
# =============================================================================

STAGES: Tuple[str, ...] = ("EH", "IH", "EL", "IL")
FINAL_STAGE: str = "FINAL"

CRITERION_STATUSES: Tuple[str, ...] = ("MET", "FAILED", "MISSING", "UNCERTAIN")
STAGE_OUTCOMES: Tuple[str, ...] = ("OUT", "PASS_CLEAN", "PASS_FLAGGED", "REVIEW")

STAGE_PRETTY: Dict[str, str] = {"EH": "E/H", "IH": "I/H", "EL": "E/L", "IL": "I/L", "FINAL": "FINAL"}
PREV_STAGE: Dict[str, Optional[str]] = {"EH": None, "IH": "EH", "EL": "IH", "IL": "EL"}

# Polarity is derived from stage by contract:
#   EH/EL => exclude, IH/IL => include
STAGE_POLARITY: Dict[str, str] = {"EH": "exclude", "IH": "include", "EL": "exclude", "IL": "include"}


# =============================================================================
# Criteria schema: allowed sets (criteria.py relies on these)
# =============================================================================

ALLOWED_TYPES = {"include", "exclude"}     # IC -> include, EC -> exclude
ALLOWED_SCOPE = {"metadata"}              # Screen A is metadata-only
ALLOWED_OPERATORS = {
    # Text matching
    "contains",
    "equals",
    "regex",
    "any_of",
    "all_of",
    # Categorical / list membership
    "in_list",
    "not_in",
    "in",
    "not_in_list",
    # Numeric
    "gte",
    "lte",
    "between",
    "range",
    # LLM
    "llm",
}

ALLOWED_HOW = {"heuristic", "llm", "crosscheck"}  # informational; engine should route by operator=='llm'


# =============================================================================
# Targetable metadata fields (dropdown single source of truth)
# =============================================================================

TARGETABLE_FIELDS: List[str] = [
    "title",
    "abstract",
    "keywords",
    "authors",
    "year",
    "venue",
    "journal",
    "doi",
    "lang",
    "doc_type",
    "availability",
    # convenience synthetic fields some engines support:
    "any_text",
]


# =============================================================================
# Tiny safe helpers
# =============================================================================

_WS_RE = re.compile(r"\s+")
_CANON_KEY_RE = re.compile(r"[^a-z0-9_]+")


def safe_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    try:
        return str(x)
    except Exception:
        return ""


def is_blank(x: Any) -> bool:
    s = safe_str(x).strip()
    return s == "" or s.lower() in {"nan", "none", "null"}


def normalize_space(s: str) -> str:
    return _WS_RE.sub(" ", (s or "")).strip()


def strip_accents(s: str) -> str:
    """
    Deterministic accent stripping for match-normalization.
    """
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_text_for_match(text: Any) -> str:
    """
    Deterministic normalization for matching:
    - stringify
    - lowercase
    - strip accents
    - collapse whitespace

    Keep punctuation (phrases may rely on it).
    """
    if text is None:
        return ""
    t = strip_accents(safe_str(text)).lower()
    return normalize_space(t)


def canonical_key(k: Any) -> str:
    """
    Canonicalize arbitrary column keys into a stable internal key:
    - lower
    - whitespace -> underscore
    - remove non [a-z0-9_]
    """
    s = safe_str(k).replace("\ufeff", "").strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = _CANON_KEY_RE.sub("_", s).strip("_")
    return s


def coerce_list(x: Any, *, split: bool = True) -> List[str]:
    """
    Turn list/tuple/str/None into a clean list[str].
    For strings:
      - if split=True, split on common separators: comma, semicolon, pipe, newline
      - else, return [string] (trimmed) if non-empty
    """
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        out: List[str] = []
        for it in x:
            s = safe_str(it).strip()
            if s:
                out.append(s)
        return out

    s = safe_str(x).strip()
    if not s:
        return []
    if not split:
        return [s]

    parts = re.split(r"[,\n;|]+", s)
    return [p.strip() for p in parts if p.strip()]


def coerce_bool(x: Any, default: bool = False) -> bool:
    if isinstance(x, bool):
        return x
    if x is None:
        return default
    s = safe_str(x).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def clamp_int(x: Any, lo: int, hi: int, default: int) -> int:
    try:
        v = int(x)
    except Exception:
        return int(default)
    return max(int(lo), min(int(hi), v))


def clamp_float(x: Any, lo: float, hi: float, default: float) -> float:
    try:
        v = float(x)
    except Exception:
        return float(default)
    return max(float(lo), min(float(hi), v))


# =============================================================================
# Optional: lightweight progress + logging helpers (safe in any caller)
# =============================================================================

def make_progress(kind: str, **kv: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"kind": safe_str(kind), "ts": time.time()}
    payload.update(kv or {})
    return payload


def emit_progress(cb: Optional[Callable[[Dict[str, Any]], None]], payload: Dict[str, Any]) -> None:
    if cb is None:
        return
    try:
        if "ts" not in payload:
            payload["ts"] = time.time()
        cb(payload)
    except Exception:
        # never break engines on UI callback errors
        pass


def safe_log(cb: Optional[Callable[[str], None]], msg: str) -> None:
    if cb is None:
        return
    try:
        cb(msg if msg.endswith("\n") else (msg + "\n"))
    except Exception:
        pass


# =============================================================================
# Optional: canonicalization helpers (useful across ingest/reporting)
# =============================================================================

HEADER_SYNONYMS: Dict[str, str] = {
    # ids
    "id": "a_id",
    "uid": "a_id",
    "record_id": "a_id",
    "recordid": "a_id",
    "local_id": "a_id",

    # core text
    "ti": "title",
    "article_title": "title",
    "document_title": "title",
    "paper_title": "title",

    "ab": "abstract",
    "summary": "abstract",
    "resume": "abstract",
    "résumé": "abstract",

    "kw": "keywords",
    "key_words": "keywords",
    "author_keywords": "keywords",
    "mesh": "keywords",

    # venue / type
    "journal": "venue",
    "source": "venue",
    "source_title": "venue",
    "publication": "venue",
    "conference": "venue",
    "booktitle": "venue",

    "document_type": "doc_type",
    "doctype": "doc_type",
    "type": "doc_type",

    # year/lang
    "py": "year",
    "pub_year": "year",
    "publication_year": "year",
    "language": "lang",
    "langue": "lang",
}


def canonicalize_headers(row: Dict[str, Any], *, idx: int = 0, id_prefix: str = "A", id_width: int = 6) -> Dict[str, Any]:
    """
    Best-effort canonicalization of an input row (dict):
    - canonicalize keys
    - map synonyms
    - ensure 'a_id' exists (A000001 style by default)
    - keep all other columns (canonized keys) as extras
    """
    out: Dict[str, Any] = {}

    for k, v in (row or {}).items():
        ck = canonical_key(k)
        ck = HEADER_SYNONYMS.get(ck, ck)
        out[ck] = v

    a_id = safe_str(out.get("a_id")).strip()
    if not a_id:
        out["a_id"] = f"{id_prefix}{idx+1:0{id_width}d}"

    return out


# =============================================================================
# Optional: small structured helpers
# =============================================================================

@dataclass(frozen=True)
class CancelToken:
    """
    Minimal cancel token compatible with `token.cancelled` checks.
    (Plugin may use its own token class; both are compatible at the interface level.)
    """
    cancelled: bool = False

    def cancel(self) -> "CancelToken":
        return CancelToken(True)


def stage_pretty(stage: str) -> str:
    return STAGE_PRETTY.get(stage, stage)


def stage_polarity(stage: str) -> str:
    return STAGE_POLARITY.get(stage, "include")
