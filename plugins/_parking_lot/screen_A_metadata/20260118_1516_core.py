# -*- coding: utf-8 -*-
"""
core.py — shared primitives for the metadata-only screening pipeline
-------------------------------------------------------------------
Holds ONLY small, stable things used across:
  - criteria.py
  - metadata.py
  - decisions_report.py
  - plugin.py

No network calls. No heavy libs. Pure Python.

Public surface (import from here):
  • ALLOWED_TYPES, ALLOWED_SCOPE, ALLOWED_OPERATORS
  • TARGETABLE_FIELDS
  • HEADER_MAP, CANON_ORDER, canonicalize_headers(...)
  • normalize_synonyms(text), normalize_text_for_match(text)
  • normalize_lang(x), normalize_doc_type(x), normalize_availability(x)
  • presence_flags(item)
  • coerce_list(x), coerce_bool(x), now_iso()
  • chunked(seq, n)
  • LLM_MODEL_PRESETS, BATCH_SIZE_DEFAULT, TOKENS_PER_ITEM_EST
  • PREFS_FILE, DEFAULT_PREFS, load_prefs(), save_prefs()
  • clamp_int(), clamp_float(), resolve_model_preset()
  • estimate_tokens(items, per_item_est), max_batch_for_tpm(org_tpm, model_overhead)
  • make_progress(kind, **kv), emit_progress(cb, payload), safe_log(cb, msg)
  • human_duration(secs)
  • CancelToken, ETA

All helpers are intentionally small and predictable.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Iterable, Callable, Tuple
from dataclasses import dataclass
import unicodedata
import re
import datetime
import os
import json
import tempfile
import time

# ---------------------------------------------------------------------
# Allowed value sets (UI should rely on these)
# ---------------------------------------------------------------------

ALLOWED_TYPES = {"include", "exclude"}      # IC -> include, EC -> exclude
ALLOWED_SCOPE = {"metadata"}                # for this phase we only screen metadata
ALLOWED_OPERATORS = {
    "contains", "equals", "regex", "not_in", "in_list",
    "gte", "lte", "between",
    "llm",  # ask the model (extractive, conservative)
}

# Allowed values for the 'how' column (what generated the rule)
ALLOWED_HOW = {"heuristic", "llm", "crosscheck"}

# Fields that criteria may target. This is the single source of truth for
# validating and building dropdowns/multi-selects across the app.
TARGETABLE_FIELDS: List[str] = [
    "title", "abstract", "keywords",
    "lang", "doc_type", "availability",
    "year", "venue", "doi",
]

# ---------------------------------------------------------------------
# A-items header normalization (used by metadata.py)
# ---------------------------------------------------------------------

HEADER_MAP: Dict[str, str] = {
    # identifiers
    "a_id": "a_id", "id": "a_id", "uid": "a_id", "local_id": "a_id",

    # bibliographic content
    "title": "title", "ti": "title", "article_title": "title",
    "abstract": "abstract", "ab": "abstract", "summary": "abstract",
    "keywords": "keywords", "kw": "keywords", "mesh": "keywords",

    # venue / type
    "venue": "venue", "journal": "venue", "source": "venue", "source_title": "venue",
    "conference": "venue", "conference_name": "venue", "booktitle": "venue",
    "type": "doc_type", "document_type": "doc_type", "pub_type": "doc_type",

    # language & year
    "language": "lang", "lang": "lang", "la": "lang",
    "year": "year", "date": "year", "py": "year", "pub_year": "year",
    "publication_year": "year", "published_year": "year",

    # identifiers (often present)
    "doi": "doi", "pmid": "pmid", "pmcid": "pmcid", "arxiv": "arxiv",

    # availability (optional upstream field)
    "availability": "availability",
    "status": "availability",
}

CANON_ORDER: List[str] = [
    "a_id", "doi", "title", "abstract", "keywords",
    "year", "lang", "venue", "doc_type",
    "availability",
    "pmid", "pmcid", "arxiv",
]

YEAR4_RE = re.compile(r"\b(19|20)\d{2}\b")

def canonicalize_headers(row: Dict[str, Any], idx: int) -> Dict[str, Any]:
    """
    Lowercase incoming keys, map to canonical names, keep extras as-is.
    Ensure a_id exists (fallback to row index + 1).
    Also normalize obvious categoricals and coerce a 4-digit year when mixed with dates.
    """
    mapped: Dict[str, Any] = {}
    for k, v in row.items():
        lk = k.lower() if isinstance(k, str) else k
        mapped[HEADER_MAP.get(lk, lk)] = v

    # Ensure a_id
    if "a_id" not in mapped or mapped.get("a_id") in (None, "", "nan"):
        mapped["a_id"] = (idx + 1)

    # Normalize categoricals conservatively
    if "lang" in mapped:
        nl = normalize_lang(mapped.get("lang"))
        if nl is not None:
            mapped["lang"] = nl
    if "doc_type" in mapped:
        nd = normalize_doc_type(mapped.get("doc_type"))
        if nd is not None:
            mapped["doc_type"] = nd
    if "availability" in mapped:
        na = normalize_availability(mapped.get("availability"))
        if na is not None:
            mapped["availability"] = na

    # Year extraction: accept int/clean string; else pull first 4-digit year token if present
    if "year" in mapped:
        y = mapped.get("year")
        y_val: Optional[int] = None
        try:
            # If it already looks like an int (or float like 2021.0), coerce safely
            y_val = int(str(y).strip()[:4])
        except Exception:
            if isinstance(y, str):
                m = YEAR4_RE.search(y)
                if m:
                    try:
                        y_val = int(m.group(0))
                    except Exception:
                        y_val = None
        if y_val is not None and 1800 <= y_val <= 2100:
            mapped["year"] = y_val  # store as int
        # else leave as-is (unknown or exotic)

    # Preserve canonical order first, then extras (do not drop unknown fields)
    ordered = {k: mapped.get(k) for k in CANON_ORDER if k in mapped}
    extras = {k: v for k, v in mapped.items() if k not in CANON_ORDER}
    return ordered | extras

# ---------------------------------------------------------------------
# Tiny normalization helpers (text & categorical)
# ---------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")
def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

def normalize_synonyms(text: str) -> str:
    """
    Very light, conservative synonym/alias reduction for keyword matching.
    DO NOT over-compress semantics here—keep it predictable.
    """
    if not text:
        return ""
    t = str(text)
    t = _strip_accents(t).lower()
    t = _WS_RE.sub(" ", t).strip()

    # Common domain aliases used frequently
    alias_map = [
        (r"\bvr\b", "virtual reality"),
        (r"\bivr\b", "immersive virtual reality"),
        (r"\bar\b", "augmented reality"),
        (r"\bmr\b", "mixed reality"),
        (r"\bl2\b", "second language"),
    ]
    for pat, rep in alias_map:
        t = re.sub(pat, rep, t)

    return t

def normalize_text_for_match(text: str) -> str:
    """
    Pipeline for deterministic 'contains' checks:
      lower -> strip accents -> collapse whitespace
    (leave punctuation — sometimes meaningful for phrases)
    """
    if not text:
        return ""
    t = _strip_accents(str(text)).lower()
    t = _WS_RE.sub(" ", t).strip()
    return t

def normalize_lang(x: Any) -> Optional[str]:
    """
    Map common language tokens to a short code.
    Only normalize when obvious; else return None to avoid false claims.
    """
    if x is None:
        return None
    s = normalize_text_for_match(str(x))
    if s in {"en", "eng", "english", "anglais"}:
        return "en"
    if s in {"fr", "fre", "fra", "french", "francais", "français"}:
        return "fr"
    if s in {"es", "spa", "spanish", "espanol", "español"}:
        return "es"
    if re.fullmatch(r"[a-z]{2,3}", s):
        return s
    return None

def normalize_doc_type(x: Any) -> Optional[str]:
    """
    Reduce doc types to a small, explicit set.
    """
    if x is None:
        return None
    s = normalize_text_for_match(str(x))
    mapping = {
        "article": "research-article",
        "research article": "research-article",
        "journal article": "research-article",
        "original article": "research-article",
        "review": "review",
        "systematic review": "review",
        "conference": "conference-article",
        "proceedings": "proceedings",
        "conference article": "conference-article",
        "editorial": "editorial",
        "book chapter": "book-chapter",
        "chapter": "book-chapter",
        "thesis": "thesis",
        "preprint": "preprint",
    }
    if s in mapping:
        return mapping[s]
    if "conference" in s:
        return "conference-article"
    if "proceed" in s:
        return "proceedings"
    if "review" in s:
        return "review"
    if "editorial" in s:
        return "editorial"
    if "chapter" in s:
        return "book-chapter"
    if "thesis" in s:
        return "thesis"
    if "preprint" in s:
        return "preprint"
    if "article" in s or "journal" in s:
        return "research-article"
    return None

def normalize_availability(x: Any) -> Optional[str]:
    """
    Normalize textual availability/status into a small set:
      'available' | 'unavailable' | 'paywalled' | 'broken-link'
    """
    if x is None:
        return None
    s = normalize_text_for_match(str(x))
    if any(tok in s for tok in ("unavailable", "not available", "missing", "no access")):
        return "unavailable"
    if any(tok in s for tok in ("paywall", "paywalled", "paid only")):
        return "paywalled"
    if any(tok in s for tok in ("broken", "404", "not found")):
        return "broken-link"
    if s:
        return "available"
    return None

# ---------------------------------------------------------------------
# Presence flags for A-items
# ---------------------------------------------------------------------

def _has_value(x: Any) -> bool:
    try:
        s = str(x)
    except Exception:
        return False
    s = s.strip().lower()
    return (x is not None) and (s != "") and (s != "nan")

def presence_flags(item: Dict[str, Any]) -> Dict[str, bool]:
    """
    For UI and missing-fields policy. Only presence (not validity).
    """
    return {
        "has_title": _has_value(item.get("title")),
        "has_abstract": _has_value(item.get("abstract")),
        "has_keywords": _has_value(item.get("keywords")),
        "has_year": _has_value(item.get("year")),
        "has_lang": _has_value(item.get("lang")),
        "has_venue": _has_value(item.get("venue")),
        "has_doc_type": _has_value(item.get("doc_type")),
        "has_availability": _has_value(item.get("availability")),
    }

# ---------------------------------------------------------------------
# Simple coercions + LLM criteria sanitation helpers
# ---------------------------------------------------------------------

def coerce_list(x: Any) -> List[str]:
    """
    Turn a free entry (str/list/tuple/None) into a clean list of strings.
    Comma-separated strings are split; blanks are removed.
    """
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        vals = [str(v) for v in x]
    else:
        vals = [p.strip() for p in str(x).split(",")]
    out: List[str] = []
    for v in vals:
        v = v.strip()
        if not v:
            continue
        out.append(v)
    return out

def coerce_bool(x: Any, default: bool = False) -> bool:
    if isinstance(x, bool):
        return x
    if x is None:
        return default
    s = str(x).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default

# ---- LLM criteria sanitation helpers ----

def _norm_id(x: Any, fallback: str) -> str:
    s = str(x).strip() if x is not None else ""
    return s or fallback

def _norm_type(x: Any) -> str:
    s = (str(x) if x is not None else "").strip().lower()
    return "exclude" if s == "exclude" else "include"

def _norm_scope(x: Any) -> str:
    # Only 'metadata' supported in this phase
    return "metadata"

def _norm_how(x: Any) -> str:
    s = (str(x) if x is not None else "").strip().lower()
    return s if s in ALLOWED_HOW else "heuristic"

def _norm_operator(x: Any) -> str:
    s = (str(x) if x is not None else "").strip().lower()
    # Common synonyms coming from LLMs
    syn = {
        "not contains": "regex",     # encourage regex with negative lookups if needed upstream
        "does_not_contain": "regex",
        "does not contain": "regex",
        "contain": "contains",
        "equal": "equals",
        "in": "in_list",
        "not in": "not_in",
    }
    s = syn.get(s, s)
    return s if s in ALLOWED_OPERATORS else "contains"

def _norm_target_csv(x: Any) -> str:
    """
    Normalize 'target' into a comma-separated, de-duplicated list
    restricted to TARGETABLE_FIELDS. Lowercases and trims tokens.
    """
    raw = []
    if isinstance(x, (list, tuple)):
        raw = [str(v) for v in x]
    else:
        raw = [p.strip() for p in str(x or "").split(",")]
    seen = set()
    out: List[str] = []
    for tok in raw:
        t = tok.strip().lower()
        if not t:
            continue
        if t in TARGETABLE_FIELDS and t not in seen:
            seen.add(t)
            out.append(t)
    # Safety: if empty, default to title,abstract to stay conservative
    return ",".join(out if out else ["title", "abstract"])

def _norm_label(x: Any, fallback: str) -> str:
    s = str(x).strip() if x is not None else ""
    return s or fallback

def _norm_weight(x: Any, default: float = 1.0) -> float:
    return clamp_float(x, 0.0, 10.0, default)

def _norm_threshold(x: Any, default: float = 0.60) -> float:
    return clamp_float(x, 0.0, 1.0, default)

def _norm_what_list(x: Any) -> List[str]:
    """
    Normalize 'what' to a list of non-empty strings, trimmed,
    preserving order and removing duplicates.
    """
    vals = coerce_list(x)
    out: List[str] = []
    seen = set()
    for v in vals:
        key = v.strip()
        if not key:
            continue
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out

def sanitize_criterion_row(row: Dict[str, Any], *, fallback_id: str = "C") -> Dict[str, Any]:
    """
    Strict, conservative normalizer for a single criterion row.
    - Enforces allowed values and ranges
    - Normalizes target fields to TARGETABLE_FIELDS
    - Keeps 'enabled' flag as provided (default True)
    - If operator=='llm' but 'how' is empty, sets how='llm'
    """
    rid = _norm_id(row.get("id"), fallback_id)
    typ = _norm_type(row.get("type"))
    scp = _norm_scope(row.get("scope"))
    op  = _norm_operator(row.get("operator"))
    tgt = _norm_target_csv(row.get("target"))
    wht = _norm_what_list(row.get("what"))
    how = _norm_how(row.get("how"))
    # Imply how='llm' if operator is llm and how is not already set to llm
    if op == "llm" and how != "llm":
        how = "llm"
    lbl = _norm_label(row.get("label"), f"{typ.upper()} · {op}({tgt})")
    wei = _norm_weight(row.get("weight", 1.0))
    thr = _norm_threshold(row.get("threshold", 0.60))
    en  = coerce_bool(row.get("enabled", True), True)

    return {
        "id": rid,
        "type": typ,
        "scope": scp,
        "label": lbl,
        "operator": op,
        "target": tgt,
        "what": wht,
        "how": how,
        "weight": wei,
        "threshold": thr,
        "enabled": en,
    }

def sanitize_llm_criteria(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Apply sanitize_criterion_row to each row and ensure unique IDs.
    If duplicate IDs appear, suffix with _a, _b, _c... deterministically.
    """
    out: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    for i, r in enumerate(rows or []):
        sr = sanitize_criterion_row(r, fallback_id=f"C{i+1:02d}")
        rid = str(sr.get("id") or f"C{i+1:02d}")
        n = counts.get(rid, 0)
        if n > 0:
            sr["id"] = f"{rid}_{chr(96+n+1)}"  # _a, _b, ...
        counts[rid] = n + 1
        out.append(sr)
    return out

# ---------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------

def now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

# ---------------------------------------------------------------------
# Progress & logging primitives (UI-safe, tiny, reusable)
# ---------------------------------------------------------------------

def make_progress(kind: str, **kv: Any) -> Dict[str, Any]:
    """
    Create a normalized progress payload. The UI code (plugin.py) can
    rely on 'kind' and 'ts' always existing.
    """
    p = {"kind": str(kind), "ts": time.time()}
    p.update(kv or {})
    return p

def emit_progress(cb: Optional[Callable[[Dict[str, Any]], None]], payload: Dict[str, Any]) -> None:
    """
    Best-effort emission. Swallows UI errors to avoid breaking the engine.
    """
    if cb is None:
        return
    try:
        if "ts" not in payload:
            payload["ts"] = time.time()
        cb(payload)
    except Exception:
        # Never propagate UI/callback errors
        pass

def safe_log(cb: Optional[Callable[[str], None]], msg: str) -> None:
    """
    Safe, newline-conservative logging. The UI can decide where/how to display it.
    """
    if cb is None:
        return
    try:
        cb(msg if msg.endswith("\n") else (msg + "\n"))
    except Exception:
        pass

def human_duration(secs: float) -> str:
    """
    Human-friendly duration. Examples: '0.2s', '3.1s', '1:04', '12:59', '1:05:03'
    """
    try:
        s = int(round(float(max(0.0, secs))))
    except Exception:
        s = 0
    if s < 10:
        return f"{secs:.1f}s"
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"

class CancelToken:
    """
    Shared cancel flag compatible with `.cancelled` attribute reads.
    """
    __slots__ = ("cancelled",)
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled: bool = bool(cancelled)
    def cancel(self) -> None:
        self.cancelled = True

class ETA:
    """
    Lightweight ETA estimator with exponential smoothing over per-item rate.
    Use:
        eta = ETA(total=100)
        eta.start()
        ...
        eta.update(done_so_far)
        payload = eta.snapshot()  # percent, elapsed, remaining, rate
    """
    __slots__ = ("total", "done", "start_ts", "last_ts", "smoothed_rate", "alpha")
    def __init__(self, total: int, *, smoothing: float = 0.25) -> None:
        self.total = max(0, int(total))
        self.done = 0
        self.start_ts: Optional[float] = None
        self.last_ts: Optional[float] = None
        self.smoothed_rate: Optional[float] = None  # items/sec
        self.alpha = float(min(0.95, max(0.05, smoothing)))

    def start(self) -> None:
        now = time.time()
        self.start_ts = now
        self.last_ts = now
        self.done = 0
        self.smoothed_rate = None

    def update(self, done: int) -> None:
        done = max(0, int(done))
        now = time.time()
        if self.start_ts is None:
            self.start()
        dt = max(1e-6, (now - (self.last_ts or now)))
        delta = max(0, done - self.done)
        inst_rate = float(delta) / dt if dt > 0 else 0.0
        if inst_rate > 0:
            if self.smoothed_rate is None:
                self.smoothed_rate = inst_rate
            else:
                a = self.alpha
                self.smoothed_rate = a * inst_rate + (1 - a) * self.smoothed_rate
        self.done = done
        self.last_ts = now

    def snapshot(self) -> Dict[str, Any]:
        now = time.time()
        elapsed = 0.0 if self.start_ts is None else (now - self.start_ts)
        total = max(0, self.total)
        done = max(0, min(self.done, total))
        pct = (100.0 * done / total) if total > 0 else 0.0
        rate = self.smoothed_rate or (done / elapsed if elapsed > 0 else 0.0)
        remain_items = max(0, total - done)
        remaining = (remain_items / rate) if rate > 0 else float("inf")
        return {
            "done": done,
            "total": total,
            "percent": pct,
            "elapsed_sec": elapsed,
            "remaining_sec": remaining,
            "rate_items_per_sec": rate,
            "elapsed_human": human_duration(elapsed),
            "remaining_human": ("∞" if remaining == float("inf") else human_duration(remaining)),
        }

# ---------------------------------------------------------------------
# Numeric & model sanity helpers
# ---------------------------------------------------------------------

def clamp_int(x: Any, lo: int, hi: int, default: int) -> int:
    """Coerce to int and clamp within [lo, hi]; fall back to default."""
    try:
        v = int(x)
    except Exception:
        return int(default)
    return max(lo, min(hi, v))

def clamp_float(x: Any, lo: float, hi: float, default: float) -> float:
    """Coerce to float and clamp within [lo, hi]; fall back to default."""
    try:
        v = float(x)
    except Exception:
        return float(default)
    return max(lo, min(hi, v))

# Models known to work with OpenAI chat.completions in this project
LLM_MODEL_PRESETS: List[str] = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1-mini",
    "gpt-4.1",
]

# --- LLM batching/safety defaults ---
BATCH_SIZE_DEFAULT = 75
# rough, conservative token-per-item estimate after truncation (title+abstract+keywords)
# we stay deliberately high to stay under TPM even with JSON/system tokens overhead
TOKENS_PER_ITEM_EST = 280

def estimate_tokens(n_items: int, per_item_est: int = TOKENS_PER_ITEM_EST, overhead: int = 1200) -> int:
    """
    Crude upper-bound token estimate for a single LLM call.
    Adds a small JSON/system overhead to the batch.
    """
    n = max(0, int(n_items))
    return n * max(1, int(per_item_est)) + max(0, int(overhead))

def max_batch_for_tpm(org_tpm_limit: int, per_item_est: int = TOKENS_PER_ITEM_EST, model_overhead: int = 1200) -> int:
    """
    Given an org TPM ceiling, return a conservative max items per batch that
    would keep a single request comfortably under that limit.
    (This is a helper for logs/diagnostics; plugin enforces user-chosen batch.)
    """
    lim = max(1000, int(org_tpm_limit))
    # keep 20% headroom
    usable = int(lim * 0.8)
    # solve: items * per_item_est + overhead <= usable
    if per_item_est <= 0:
        return 1
    cap = max(1, (usable - max(0, int(model_overhead))) // per_item_est)
    return cap

def resolve_model_preset(name: Optional[str]) -> Optional[str]:
    """
    Return a valid preset name or None if blank/unknown.
    Keeps user input 'as-is' only when it matches our known presets.
    """
    if not name:
        return None
    s = str(name).strip()
    return s if s in LLM_MODEL_PRESETS else None

# ---------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------

def chunked(seq: Iterable[Any], n: int):
    """Yield successive n-sized chunks from seq (n coerced to >=1)."""
    n = max(1, int(n))
    buf: List[Any] = []
    for x in seq:
        buf.append(x)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf

# ---------------------------------------------------------------------
# (Optional) small data holders — not required, but handy if you want types
# ---------------------------------------------------------------------

@dataclass
class CanonicalCriterion:
    """
    Optional structured representation for one criterion row
    (what your harmonizer emits for the table).
    """
    id: str
    type: str                 # include | exclude
    scope: str                # metadata
    label: str                # human-readable
    operator: str             # contains | equals | regex | not_in | in_list | gte | lte | between | llm
    target: str               # one or more of TARGETABLE_FIELDS, comma-separated
    what: List[str]           # normalized values / phrases
    how: str                  # heuristic | llm | crosscheck   (no 'hybrid')
    weight: float = 1.0
    threshold: float = 0.60
    enabled: bool = True      # soft delete / toggle visibility

    def to_row(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "scope": self.scope,
            "label": self.label,
            "operator": self.operator,
            "target": self.target,
            "what": ", ".join(self.what),
            "how": self.how,
            "weight": self.weight,
            "threshold": self.threshold,
            "enabled": self.enabled,
        }

# ---------------------------------------------------------------------
# User prefs (persistence) — tiny JSON file in the user's home dir
# ---------------------------------------------------------------------

PREFS_FILE = os.path.join(os.path.expanduser("~"), ".screen_a_metadata_prefs.json")

DEFAULT_PREFS: Dict[str, Any] = {
    # empty string means “no model selected”; plugin can auto-pick if needed
    "llm_model": "",
    "llm_batch": BATCH_SIZE_DEFAULT,
    "llm_trunc": 1500,
}

def _merge_and_sanitize_prefs(raw: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(DEFAULT_PREFS)
    if isinstance(raw, dict):
        # model: keep only known preset, else blank
        model = resolve_model_preset(raw.get("llm_model"))
        out["llm_model"] = model or ""
        # numeric clamps
        out["llm_batch"] = clamp_int(raw.get("llm_batch", out["llm_batch"]), 1, 500, out["llm_batch"])
        out["llm_trunc"] = clamp_int(raw.get("llm_trunc", out["llm_trunc"]), 200, 8000, out["llm_trunc"])
    return out

def load_prefs() -> Dict[str, Any]:
    """
    Read JSON prefs from PREFS_FILE; on any error, return DEFAULT_PREFS.
    The returned dict is always sanitized and complete.
    """
    try:
        with open(PREFS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _merge_and_sanitize_prefs(data if isinstance(data, dict) else {})
    except Exception:
        return dict(DEFAULT_PREFS)

def save_prefs(prefs: Dict[str, Any]) -> None:
    """
    Safely persist prefs to PREFS_FILE (write temp then replace).
    Ignores errors silently (keeps UI resilient).
    """
    try:
        data = _merge_and_sanitize_prefs(prefs or {})
        os.makedirs(os.path.dirname(PREFS_FILE), exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".screen_a_metadata_prefs.", suffix=".json",
                                   dir=os.path.dirname(PREFS_FILE) or None)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            try:
                os.replace(tmp, PREFS_FILE)
            except Exception:
                # fallback to copy-then-remove if replace not available
                with open(PREFS_FILE, "w", encoding="utf-8") as out:
                    json.dump(data, out, ensure_ascii=False, indent=2)
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        except Exception:
            try:
                os.remove(tmp)
            except Exception:
                pass
    except Exception:
        # swallow; persistence is non-critical
        pass
