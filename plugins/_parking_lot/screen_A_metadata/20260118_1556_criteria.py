# -*- coding: utf-8 -*-
"""
criteria.py — criteria ingestion & harmonization (metadata-only pipeline)
------------------------------------------------------------------------
Emits rows compatible with the target table:

  id | type | scope | label | operator | target | what | how | weight | threshold | enabled

Where:
  • type      ∈ {"include","exclude"}
  • scope     = "metadata" (for this phase)
  • operator  ∈ {"contains","equals","regex","not_in","in_list","gte","lte","between","llm"}
  • target    = one or more metadata fields, comma-separated. Each token must be allowed
                (e.g., "title", "abstract", "keywords", "lang", "doc_type", "availability",
                 "year", "venue", "doi"). Multiple allowed: "title,abstract", "title,keywords,venue", etc.
  • what      = comma-separated string in the UI (internally kept as a list[str])
  • how       ∈ {"heuristic","llm","crosscheck"}   # NOTE: "hybrid" removed
  • enabled   = soft-delete flag (bool), default True

Public API:
  - parse_criteria_rows(path: str) -> list[dict]
  - harmonize_from_text(text: str) -> list[dict]
  - harmonize_from_rows(rows: list[dict]) -> list[dict]
  - reformulate_with_llm(criteria_rows: list[dict], *, model: str = "gpt-4o-mini",
                         log: callable | None = None) -> list[dict]

Note: This module does NOT call the LLM during free-text parsing by default.
      Use reformulate_with_llm(...) explicitly if you want an LLM pass.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
import csv
import os
import re
import json

# Optional XLSX via pandas (if available)
try:
    import pandas as _pd  # type: ignore
    _PANDAS_OK = True
except Exception:
    _pd = None
    _PANDAS_OK = False

from .core import (
    ALLOWED_TYPES, ALLOWED_SCOPE, ALLOWED_OPERATORS,
    coerce_list, coerce_bool,
    normalize_text_for_match,
)

# Try to import a canonical list of targetable fields from core; fallback if absent.
try:
    from .core import TARGETABLE_FIELDS  # type: ignore
    _TARGETABLE_FIELDS: List[str] = list(TARGETABLE_FIELDS)  # maintain declared order if any
except Exception:
    _TARGETABLE_FIELDS = [
        "title", "abstract", "keywords",
        "lang", "doc_type", "availability",
        "year", "venue", "doi",
    ]

# ---------------------------------------------------------------------
# Helpers: CSV/XLSX load (loose mapping, keep user's columns if present)
# ---------------------------------------------------------------------

_CANON_COLS = (
    "id","type","scope","label","operator","target","what","how","weight","threshold","enabled"
)

def parse_criteria_rows(path: str) -> List[Dict[str, Any]]:
    """
    Load criteria rows from CSV or XLSX (if pandas available).
    Accepts either canonical headers or user variants (we keep columns as-is
    and validate/normalize later in harmonize_from_rows).
    """
    rows: List[Dict[str, Any]] = []
    ext = os.path.splitext(path)[1].lower()

    if ext in (".xlsx", ".xls") and _PANDAS_OK:
        df = _pd.read_excel(path)
        rows = df.to_dict(orient="records")
    else:
        # CSV fallback (support UTF-8 BOM)
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

    return rows

# ---------------------------------------------------------------------
# Free-text IC/EC parsing and deterministic harmonization
# ---------------------------------------------------------------------

# IC-1a, EC 2, EC-12, etc.
_ID_PAT = re.compile(r"\b([IE]C)\s*[-–—]?\s*(\d+[a-z]?)\b", re.I)

# windowing hints like "from 2015", "since 2018"
_YEAR_GTE_PAT = re.compile(r"\b(since|after|from)\s+((?:19|20)\d{2})\b", re.I)
# "before 2017", "up to 2020"
_YEAR_LTE_PAT = re.compile(r"\b(before|until|upto|up to|≤|<=)\s*((?:19|20)\d{2})\b", re.I)
# "2010-2015" with various dashes
_YEAR_BETWEEN_PAT = re.compile(r"\b((?:19|20)\d{2})\s*[-–—]\s*((?:19|20)\d{2})\b")

def harmonize_from_text(text: str) -> List[Dict[str, Any]]:
    """
    Parse pasted lines like:
        IC-1a – The paper has one of the following terms...
        EC-5  – The study is theoretical...
    Produce canonical rows with operator/target/what/how filled where possible.
    """
    if not text:
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out: List[Dict[str, Any]] = []
    auto_idx = 1

    for raw in lines:
        # Extract id (if present)
        cid = _extract_or_make_id(raw, auto_idx)
        if cid.startswith("C"):
            auto_idx += 1

        # Determine type by IC/EC (default include)
        lower = raw.strip().lower()
        ctype = "include" if lower.startswith(("ic", "ic-")) else ("exclude" if lower.startswith(("ec", "ec-")) else "include")

        # Derive a friendly label (keep the full sentence minus the id token if present)
        label = _derive_label(raw, cid)

        # Deterministic mapping first (lang, availability, doc_type, keyword families, negations, year windows)
        crit = _auto_harmonize_line(cid, ctype, label, raw)

        # Validate & normalize
        crit = _validate_row_defaults(crit)
        out.append(crit)

    # Ensure IDs are unique (friendly suffix if duplicates)
    return _ensure_unique_ids(out)

def _extract_or_make_id(raw: str, auto_idx: int) -> str:
    m = _ID_PAT.search(raw)
    if not m:
        return f"C{auto_idx:02d}"
    base = (m.group(1) + "-" + m.group(2)).upper()
    base = base.replace("–", "-").replace("—", "-").replace(" ", "")
    return base

def _derive_label(raw: str, cid: str) -> str:
    s = raw.strip()
    # Remove the id token from the beginning for readability (with or without dash)
    s_norm = re.sub(r"^\s*" + re.escape(cid).replace(r"\-", r"[-–—]?") + r"\s*", "", s, flags=re.I)
    s_norm = s_norm[0].upper() + s_norm[1:] if s_norm else s
    return f"{cid} — {s_norm}"

# ---------------------------------------------------------------------
# Row-based harmonization (from CSV/XLSX or programmatic calls)
# ---------------------------------------------------------------------

def harmonize_from_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Take raw rows (from CSV/XLSX or upstream) and ensure they conform to the
    canonical schema. Fill gaps (e.g., missing scope) and normalize entries.
    """
    out: List[Dict[str, Any]] = []
    for i, r in enumerate(rows):
        # Start with existing columns (best effort), then patch
        cid = str(r.get("id") or f"C{i+1:02d}")
        ctype = str(r.get("type") or "").strip().lower() or "include"
        label = str(r.get("label") or cid)
        operator = str(r.get("operator") or "").strip().lower()
        target = str(r.get("target") or "").strip().lower()
        what = coerce_list(r.get("what"))
        how = str(r.get("how") or "").strip().lower() or "heuristic"
        try:
            weight = float(r.get("weight")) if r.get("weight") is not None else 1.0
        except Exception:
            weight = 1.0
        try:
            threshold = float(r.get("threshold")) if r.get("threshold") is not None else 0.60
        except Exception:
            threshold = 0.60
        enabled = coerce_bool(r.get("enabled"), True)

        # If operator/target/what are missing, try deterministic mapping from label
        if not operator or not target or (not what and operator != "llm"):
            det = _auto_harmonize_line(cid, ctype, label, label)  # use label text as hint
            operator = operator or det["operator"]
            target = target or det["target"]
            what = what or det["what"]
            # Preserve explicit user choice of LLM; otherwise adopt deterministic 'how'
            if how != "llm":
                how = det["how"] or how

        crit = {
            "id": cid,
            "type": ctype,
            "scope": str(r.get("scope") or "metadata").strip().lower(),
            "label": label,
            "operator": operator,
            "target": target,
            "what": what,
            "how": how,
            "weight": weight,
            "threshold": threshold,
            "enabled": enabled,
        }
        crit = _validate_row_defaults(crit)
        out.append(crit)

    return _ensure_unique_ids(out)

# ---------------------------------------------------------------------
# Deterministic mapping rules (the “safe” pre-pass)
# ---------------------------------------------------------------------

# Seed synonym families (editable, conservative)
_VR_TERMS = ["virtual reality", "vr", "immersive virtual reality", "ivr"]
_IMMERSION_TERMS = ["immersion", "immersive", "sense of presence", "presence"]
_FL_TERMS = ["foreign language", "second language", "l2", "language learning", "language teaching"]

def _auto_harmonize_line(cid: str, ctype: str, label: str, raw_text: str) -> Dict[str, Any]:
    """
    Convert a free-text criterion into a canonical row with best-effort deterministic mapping.
    If we cannot do it safely, we fall back to operator='llm', target='abstract', how='llm'.
    """
    txt = normalize_text_for_match(raw_text)

    # Defaults (LLM fallback)
    row = {
        "id": cid,
        "type": ctype if ctype in ALLOWED_TYPES else "include",
        "scope": "metadata",
        "label": label,
        "operator": "llm",
        "target": "abstract",
        "what": [],
        "how": "llm",
        "weight": 1.0,
        "threshold": 0.60,
        "enabled": True,
    }

    # --- Language (English yes/no) ---
    # Include: "written in English", "English only"
    if ("written in english" in txt) or (re.search(r"\benglish\b", txt) and ("not" not in txt) and ("non-" not in txt)):
        if row["type"] == "include":
            return {**row, "operator": "equals", "target": "lang", "what": ["en"], "how": "heuristic"}
    # Exclude: "not in English", "non-English"
    if ("not written in english" in txt) or ("non-english" in txt) or (("not" in txt) and ("english" in txt)):
        if row["type"] == "exclude":
            # use not_in for exclusion instead of equals=en
            return {**row, "operator": "not_in", "target": "lang", "what": ["en"], "how": "heuristic"}

    # --- Availability (not available) ---
    if "not available" in txt or "unavailable" in txt:
        if row["type"] == "exclude":
            return {**row, "operator": "equals", "target": "availability", "what": ["unavailable"], "how": "heuristic"}

    # --- Doc type (Research Article / Proceedings/Conference) ---
    if ("research article" in txt) or ("journal article" in txt) or ("original article" in txt):
        if row["type"] == "include":
            return {**row, "operator": "in_list", "target": "doc_type", "what": ["research-article", "article"], "how": "heuristic"}
    if ("proceedings" in txt) or ("conference article" in txt) or ("conference paper" in txt):
        if row["type"] == "include":
            return {**row, "operator": "in_list", "target": "doc_type", "what": ["conference-article", "proceedings"], "how": "heuristic"}

    # --- Year windows (simple) ---
    m = _YEAR_BETWEEN_PAT.search(raw_text)
    if m:
        y1, y2 = int(m.group(1)), int(m.group(2))
        lo, hi = sorted((y1, y2))
        return {**row, "operator": "between", "target": "year", "what": [str(lo), str(hi)], "how": "heuristic"}

    m = _YEAR_GTE_PAT.search(raw_text)
    if m:
        y = int(m.group(2))
        return {**row, "operator": "gte", "target": "year", "what": [str(y)], "how": "heuristic"}

    m = _YEAR_LTE_PAT.search(raw_text)
    if m:
        y = int(m.group(2))
        return {**row, "operator": "lte", "target": "year", "what": [str(y)], "how": "heuristic"}

    # --- Keyword families (VR / Immersion / Foreign Language) ---
    if ("virtual reality" in txt) or re.search(r"\bvr\b", txt):
        return {**row, "operator": "contains", "target": "title,abstract,keywords", "what": _VR_TERMS, "how": "heuristic"}
    if ("immersion" in txt) or ("immersive" in txt) or ("presence" in txt):
        return {**row, "operator": "contains", "target": "title,abstract,keywords", "what": _IMMERSION_TERMS, "how": "heuristic"}
    if ("foreign language" in txt) or ("second language" in txt) or re.search(r"\bl2\b", txt):
        return {**row, "operator": "contains", "target": "title,abstract,keywords", "what": _FL_TERMS, "how": "heuristic"}

    # --- Explicit negative semantic claims (better via LLM) ---
    if "does not consider immersive virtual reality" in txt or "does not consider virtual reality" in txt:
        return {**row, "operator": "llm", "target": "abstract", "what": ["paper lacks a focus on immersive virtual reality"], "how": "llm"}
    if "does not consider teaching" in txt and ("foreign language" in txt or "second language" in txt or "l2" in txt):
        return {**row, "operator": "llm", "target": "abstract", "what": ["paper does not address foreign language teaching/learning"], "how": "llm"}
    if "study is theoretical" in txt or "proposes a framework" in txt or "conceptual" in txt:
        return {**row, "operator": "llm", "target": "abstract", "what": ["theoretical/conceptual work without empirical study"], "how": "llm"}

    # Fallback: ask the LLM (extractive, conservative)
    return row

# ---------------------------------------------------------------------
# Validation / defaults
# ---------------------------------------------------------------------

# Operator↔target coarse compatibility (fail → fallback to LLM)
_OP_TARGET_OK = {
    "contains": {"title","abstract","keywords","venue","doi"},
    "regex":    {"title","abstract","keywords","venue","doi"},
    "equals":   {"lang","doc_type","availability","venue","title","doi","year"},
    "not_in":   {"doc_type","availability","venue","lang"},
    "in_list":  {"doc_type","availability","venue","lang"},
    "gte":      {"year"},
    "lte":      {"year"},
    "between":  {"year"},
    "llm":      {"title","abstract","keywords","venue","lang","doc_type","availability","year","doi"},
}

def _normalize_target_multi(tgt_raw: str) -> str:
    """
    Accept a comma-separated target string. Normalize tokens (trim/lower), dedupe,
    and keep only allowed tokens from _TARGETABLE_FIELDS. Preserve user order.
    Return a comma-joined string. If result ends up empty, return 'abstract'.
    """
    if not tgt_raw:
        return "abstract"
    toks = [t.strip().lower() for t in str(tgt_raw).split(",") if t.strip()]
    seen = set()
    allowed = set(_TARGETABLE_FIELDS)
    out: List[str] = []
    for t in toks:
        if t in allowed and t not in seen:
            out.append(t)
            seen.add(t)
    # Special convenience: preserve historical "title,abstract,keywords" exactly if equivalent
    if set(out) == {"title", "abstract", "keywords"} and len(out) == 3:
        return "title,abstract,keywords"
    return ",".join(out) if out else "abstract"

def _normalize_what_for_operator(op: str, what: List[Any]) -> List[str]:
    """Coerce 'what' to a safe list of strings compatible with operator semantics."""
    if op in {"contains","regex","equals","not_in","in_list"}:
        return [str(x).strip() for x in what if str(x).strip()]
    if op in {"gte","lte"}:
        vals = [str(x).strip() for x in what if str(x).strip()]
        if not vals:
            return []
        try:
            y = int(vals[0])
        except Exception:
            m = re.search(r"(19|20)\d{2}", vals[0])
            if not m:
                return []
            y = int(m.group(0))
        return [str(y)]
    if op == "between":
        vals = [str(x).strip() for x in what if str(x).strip()]
        nums: List[int] = []
        for v in vals[:2]:
            try:
                nums.append(int(v))
            except Exception:
                m = re.search(r"(19|20)\d{2}", v)
                if m:
                    nums.append(int(m.group(0)))
        if len(nums) == 2:
            lo, hi = sorted(nums)
            return [str(lo), str(hi)]
        return []
    # LLM or unknown: keep list of strings (may be empty)
    return [str(x).strip() for x in what if str(x).strip()]

def _validate_row_defaults(row: Dict[str, Any]) -> Dict[str, Any]:
    # Clamp type
    t = (row.get("type") or "").strip().lower()
    row["type"] = t if t in ALLOWED_TYPES else "include"

    # Scope is always metadata in this phase (even if the user wrote something else)
    row["scope"] = "metadata" if "metadata" in ALLOWED_SCOPE else (next(iter(ALLOWED_SCOPE)))

    # Operator
    op = (row.get("operator") or "").strip().lower()
    row["operator"] = op if op in ALLOWED_OPERATORS else "llm"

    # Target — supports arbitrary multi-targets
    tgt_raw = (row.get("target") or "").strip().lower()
    tgt_norm = _normalize_target_multi(tgt_raw)
    # Check coarse compatibility; if incompatible, fallback to LLM over abstract
    if row["operator"] in _OP_TARGET_OK and not set(tgt_norm.split(",")).issubset(_OP_TARGET_OK[row["operator"]]):
        row["operator"] = "llm"
        tgt_norm = "abstract"
        row["how"] = "llm"
    row["target"] = tgt_norm

    # What → list[str] normalized for operator
    what_list = coerce_list(row.get("what"))
    row["what"] = _normalize_what_for_operator(row["operator"], what_list)

    # How — "hybrid" removed; map anything unknown to "heuristic" unless operator is 'llm'
    how = (row.get("how") or "").strip().lower()
    if row["operator"] == "llm":
        row["how"] = "llm"
    else:
        row["how"] = how if how in {"heuristic","llm","crosscheck"} else "heuristic"

    # Weight & threshold
    try:
        w = float(row.get("weight")) if row.get("weight") is not None else 1.0
    except Exception:
        w = 1.0
    row["weight"] = max(0.0, min(10.0, float(f"{w:.2f}")))
    try:
        th = float(row.get("threshold")) if row.get("threshold") is not None else 0.60
    except Exception:
        th = 0.60
    row["threshold"] = max(0.0, min(1.0, float(f"{th:.2f}")))

    # Enabled (soft delete flag)
    row["enabled"] = coerce_bool(row.get("enabled"), True)

    # Label & id (make sure present)
    row["id"] = str(row.get("id") or "C01")
    row["label"] = str(row.get("label") or row["id"])

    return row

def _ensure_unique_ids(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []
    for r in rows:
        base = str(r.get("id") or "C")
        if base not in seen:
            seen[base] = 0
            out.append(r)
            continue
        seen[base] += 1
        r2 = dict(r)
        r2["id"] = f"{base}_{seen[base]}"
        if (r2.get("label") or "") == base:
            r2["label"] = r2["id"]
        out.append(r2)
    return out

# ---------------------------------------------------------------------
# Few-shot for the reformulator (your “green” target)
# ---------------------------------------------------------------------

_FEWSHOT_EXAMPLE_IN: List[Dict[str, Any]] = [
    {"id":"IC-3","type":"include","scope":"metadata","label":"IC-3 — The paper is a Proceedings / Conference Article."},
    {"id":"EC-3","type":"exclude","scope":"metadata","label":"EC-3 — The paper is a research article."},
    {"id":"IC-4","type":"include","scope":"metadata","label":"IC-4 — The paper is written in English."},
    {"id":"EC-4","type":"exclude","scope":"metadata","label":"EC-4 — The article’s primary focus is the rubber hand illusion paradigm."},
    {"id":"EC-5","type":"exclude","scope":"metadata","label":"EC-5 — The article’s primary focus is spatialized audio."},
    {"id":"IC-6","type":"include","scope":"metadata","label":"IC-6 — The paper considers Immersive Virtual Reality."},
]

_FEWSHOT_EXAMPLE_OUT: List[Dict[str, Any]] = [
    {"id":"IC-3","type":"include","scope":"metadata","label":"IC-3 — The paper is a Proceedings / Conference Article.","operator":"in_list","target":"doc_type","what":["conference-article","proceedings"],"how":"heuristic","weight":1.0,"threshold":0.6},
    {"id":"EC-3","type":"exclude","scope":"metadata","label":"EC-3 — The paper is a research article.","operator":"in_list","target":"doc_type","what":["research-article"],"how":"heuristic","weight":1.0,"threshold":0.6},
    {"id":"IC-4","type":"include","scope":"metadata","label":"IC-4 — The paper is written in English.","operator":"equals","target":"lang","what":["en"],"how":"heuristic","weight":1.0,"threshold":0.6},
    {"id":"EC-4","type":"exclude","scope":"metadata","label":"EC-4 — The article’s primary focus is the rubber hand illusion paradigm.","operator":"llm","target":"abstract","what":["The article’s primary focus is the rubber hand illusion paradigm."],"how":"llm","weight":1.0,"threshold":0.6},
    {"id":"EC-5","type":"exclude","scope":"metadata","label":"EC-5 — The article’s primary focus is spatialized audio.","operator":"llm","target":"abstract","what":["The article’s primary focus is spatialized audio."],"how":"llm","weight":1.0,"threshold":0.6},
    {"id":"IC-6","type":"include","scope":"metadata","label":"IC-6 — The paper considers Immersive Virtual Reality.","operator":"llm","target":"abstract","what":["The paper considers Immersive Virtual Reality."],"how":"llm","weight":1.0,"threshold":0.6},
]

# Allowed operator/target pairs to re-check LLM output
_ALLOWED_PAIRS = {
    ("contains","title"),("contains","abstract"),("contains","keywords"),("contains","venue"),("contains","doi"),
    ("regex","title"),("regex","abstract"),("regex","keywords"),("regex","venue"),("regex","doi"),
    ("equals","lang"),("equals","doc_type"),("equals","availability"),("equals","venue"),("equals","title"),("equals","doi"),("equals","year"),
    ("not_in","doc_type"),("not_in","availability"),("not_in","venue"),("not_in","lang"),
    ("in_list","doc_type"),("in_list","availability"),("in_list","venue"),("in_list","lang"),
    ("gte","year"),("lte","year"),("between","year"),
    ("llm","title"),("llm","abstract"),("llm","keywords"),("llm","venue"),("llm","lang"),("llm","doc_type"),("llm","availability"),("llm","year"),("llm","doi")
}

def _targets_ok(op: str, tgt: str) -> bool:
    if not tgt:
        return False
    for t in tgt.split(","):
        if (op, t.strip().lower()) not in _ALLOWED_PAIRS:
            return False
    return True

# ---------------------------------------------------------------------
# Optional: LLM reformulation (now with strict few-shot + guards)
# ---------------------------------------------------------------------

def reformulate_with_llm(criteria_rows: List[Dict[str, Any]], *, model: str = "gpt-4o-mini", log: Optional[callable] = None) -> List[Dict[str, Any]]:
    """
    Re-harmonize rows with a strict few-shot that enforces:
      • language → equals/lang/en (or not_in/en for excludes)
      • doc_type claims → in_list/doc_type/[...]
      • semantic focus/considers → llm over abstract with a single declarative sentence in 'what'
      • preserve id/type/label/weight/threshold/enabled; same count and same IDs

    If no API key or any error: returns input unchanged.
    """
    # Preserve enabled flags & order
    enabled_by_id = {str(r.get("id")): coerce_bool(r.get("enabled"), True) for r in criteria_rows}
    ordered_ids = [str(r.get("id")) for r in criteria_rows]

    try:
        from openai import OpenAI  # type: ignore
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            if log: log("[HARMONIZER-LLM] OPENAI_API_KEY missing; skipping.\n")
            return criteria_rows
        client = OpenAI(api_key=api_key)

        # Build user payload (minimal — id/type/label + any user operator/target/what to give hints)
        task_in = []
        for r in criteria_rows:
            task_in.append({
                "id": r.get("id"),
                "type": r.get("type"),
                "scope": "metadata",
                "label": r.get("label"),
                "operator": (r.get("operator") or ""),
                "target": (r.get("target") or ""),
                "what": r.get("what") if isinstance(r.get("what"), list) else coerce_list(r.get("what")),
                "how": (r.get("how") or ""),
                "weight": r.get("weight", 1.0),
                "threshold": r.get("threshold", 0.60),
            })

        # Messages: strict rules + few-shot example (your “green” expectations)
        system_rules = (
            "You are a strict harmonizer for screening criteria.\n"
            "- Always preserve: id, type, label, weight, threshold. Scope is 'metadata'. Do not add or delete rows.\n"
            "- Allowed operators: contains, equals, regex, not_in, in_list, gte, lte, between, llm.\n"
            "- Allowed targets: title, abstract, keywords, lang, doc_type, availability, year, venue, doi.\n"
            "- Categorical claims:\n"
            "  • Language: map to operator=equals target=lang what=['en'] for includes; for excludes use operator=not_in target=lang what=['en'].\n"
            "  • Doc type phrases: map to operator=in_list target=doc_type with canonical values (e.g., research-article, article, conference-article, proceedings).\n"
            "- Semantic topical claims (e.g., 'primary focus is ...', 'considers ...'): map to operator=llm target=abstract how='llm' and put ONE short declarative sentence into 'what'[0]. Do not output keyword lists in 'what' for llm.\n"
            "- Do not output 'hybrid' in 'how'; use 'heuristic' unless operator is 'llm'.\n"
            "- Output JSON only with key 'rows' (list of rows). Each row must have the same id as input."
        )

        example_in = {"example_in": _FEWSHOT_EXAMPLE_IN}
        example_out = {"rows": _FEWSHOT_EXAMPLE_OUT}
        task_wrap = {"task_in": task_in}

        messages = [
            {"role": "system", "content": system_rules},
            {"role": "assistant", "content": json.dumps(example_out, ensure_ascii=False)},   # gold OUT first
            {"role": "user", "content": json.dumps(example_in, ensure_ascii=False)},         # the example IN (paired with above)
            {"role": "user", "content": json.dumps(task_wrap, ensure_ascii=False)},          # real task IN
            {"role": "system", "content": "Return JSON only with a top-level key 'rows'. Temperature=0."}
        ]

        if log: log(f"[HARMONIZER-LLM] sending {len(criteria_rows)} rows to model={model}\n")
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        txt = resp.choices[0].message.content or "{}"
        data = json.loads(txt)
        rows = data.get("rows", data if isinstance(data, list) else [])

        # Post-validate: same count & IDs; allowed operator/target; enforce house rules
        by_id_in = {str(r["id"]): r for r in rows if "id" in r}
        if (len(by_id_in) != len(criteria_rows)) or any(_id not in by_id_in for _id in ordered_ids):
            if log: log("[HARMONIZER-LLM] ID/count mismatch → keeping originals.\n")
            return criteria_rows

        out: List[Dict[str, Any]] = []
        for _id in ordered_ids:
            r = dict(by_id_in[_id])

            # Force invariants
            r["id"] = _id
            # Preserve original label/type/weights/threshold (LLM may not change them)
            orig = next(x for x in criteria_rows if str(x.get("id")) == _id)
            r["type"] = (orig.get("type") or r.get("type") or "include")
            r["label"] = orig.get("label") or r.get("label") or _id
            r["scope"] = "metadata"
            r["weight"] = orig.get("weight", r.get("weight", 1.0))
            r["threshold"] = orig.get("threshold", r.get("threshold", 0.60))
            r["enabled"] = enabled_by_id.get(_id, True)

            # Sanity for operator/target
            op = (r.get("operator") or "").strip().lower()
            tgt = (r.get("target") or "").strip().lower() or "abstract"
            if not op or op not in ALLOWED_OPERATORS or not _targets_ok(op, tgt):
                # fallback to llm over abstract
                r["operator"] = "llm"
                r["target"] = "abstract"
                r["how"] = "llm"
            else:
                r["operator"] = op
                r["target"] = _normalize_target_multi(tgt)

            # House rule: if operator is 'llm' → how must be 'llm'; else heuristic unless 'crosscheck'
            if r["operator"] == "llm":
                r["how"] = "llm"
                # For llm, 'what' must be a single short sentence (not keyword list)
                w = r.get("what")
                if isinstance(w, list) and w:
                    w0 = str(w[0]).strip()
                    r["what"] = [w0] if w0 else []
                else:
                    r["what"] = []
            else:
                how = (r.get("how") or "").strip().lower()
                r["how"] = how if how in {"heuristic","crosscheck"} else "heuristic"

            # Normalize 'what' by operator semantics
            r["what"] = _normalize_what_for_operator(r["operator"], coerce_list(r.get("what")))

            # Final schema clamp
            r = _validate_row_defaults(r)
            out.append(r)

        if log: log(f"[HARMONIZER-LLM] received {len(out)} rows.\n")
        return out or criteria_rows

    except Exception as e:
        if log: log(f"[HARMONIZER-LLM] ERROR: {e}\n")
        return criteria_rows
