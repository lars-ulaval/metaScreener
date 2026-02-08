# -*- coding: utf-8 -*-
"""
Created on Sat Oct 11 08:59:35 2025

@author: alere

File: plugins/screen_A/llm_harmonizer.py
Purpose: LLM-backed criteria harmonization (strict JSON in → validated Criterion[])
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
import json
import re

# Schema + validators
from .criteria_schema import (
    Criterion,
    criterion_from_dict,
    normalize_synonyms,
    ALLOWED_TYPES,
    ALLOWED_SCOPE,
    ALLOWED_OPERATORS,
)

# ---- prompt plumbing (import from prompts.py if available) ----
def _build_messages(criteria_payload: List[Dict[str, Any]], model: str) -> List[Dict[str, str]]:
    """
    Try to use prompts.py; otherwise fall back to a minimal internal prompt.
    """
    try:
        from .prompts import build_criteria_harmonize_messages  # your centralized builder
        import json as _json
        return build_criteria_harmonize_messages(criteria_payload, model=model)
    except Exception:
        system = (
            "You are a careful assistant that rewrites screening criteria into a strict JSON list. "
            "For each input criterion, output items with fields: "
            "id (string), label (string), type ('include'|'exclude'), scope ('metadata'|'fulltext'|'both'), "
            "targets (list[str]), operators (list[str] among "
            + ", ".join(sorted(ALLOWED_OPERATORS))
            + "), patterns (list[str]), weight (float 0..10), threshold (float 0..1), notes (string). "
            "Use only allowed values. If an input line implies multiple criteria, split them. "
            "Return ONLY JSON (no prose)."
        )
        user = {
            "role": "user",
            "content": json.dumps(
                {
                    "criteria": criteria_payload,
                    "hint": "Normalize synonyms, keep allowed operators/scopes only, be conservative.",
                },
                ensure_ascii=False,
            ),
        }
        return [{"role": "system", "content": system}, user]


# ---- utilities ----

def _strip_code_fences(txt: str) -> str:
    if not txt:
        return txt
    # Remove ```json ... ``` or ``` ... ```
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", txt, flags=re.S | re.I)
    return m.group(1) if m else txt

def _parse_llm_json(txt: str) -> List[Dict[str, Any]]:
    raw = _strip_code_fences(txt).strip()
    data = json.loads(raw)
    if isinstance(data, dict) and "criteria" in data:
        data = data["criteria"]
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array (or object with 'criteria').")
    return data

def _coerce_list_of_str(val: Any) -> List[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    s = str(val).strip()
    if not s:
        return []
    # accept comma/semicolon separated
    toks = re.split(r"[;,]", s)
    return [t.strip() for t in toks if t.strip()]

def _clamp(x: float, lo: float, hi: float) -> float:
    return hi if x > hi else lo if x < lo else x

def _sanitize_item(d: Dict[str, Any]) -> Dict[str, Any]:
    # Normalize strings
    typ = str(d.get("type") or "include").strip().lower()
    scope = str(d.get("scope") or "both").strip().lower()
    label = normalize_synonyms(str(d.get("label") or "").strip())

    # Targets/operators/patterns
    targets = [t.lower() for t in _coerce_list_of_str(d.get("targets"))]
    if not targets:
        targets = ["title", "abstract", "keywords"]

    ops = [o.lower() for o in _coerce_list_of_str(d.get("operators"))]
    ops = [o for o in ops if o in ALLOWED_OPERATORS]
    if not ops:
        ops = ["contains"]

    patterns = [normalize_synonyms(p) for p in _coerce_list_of_str(d.get("patterns"))]
    if not patterns and label:
        patterns = [label]

    # Numeric fields
    try:
        weight = float(d.get("weight"))
    except Exception:
        weight = 1.0
    weight = _clamp(weight, 0.0, 10.0)

    try:
        thr = float(d.get("threshold"))
    except Exception:
        thr = 0.6
    thr = _clamp(thr, 0.0, 1.0)

    out = {
        "id": str(d.get("id") or "").strip(),
        "label": label,
        "type": typ if typ in ALLOWED_TYPES else "include",
        "scope": scope if scope in ALLOWED_SCOPE else "both",
        "targets": targets,
        "operators": ops,
        "patterns": patterns,
        "weight": weight,
        "threshold": thr,
        "notes": str(d.get("notes") or "").strip(),
    }
    return out

def _criterion_payload(criteria: List[Criterion]) -> List[Dict[str, Any]]:
    # Small payload for the prompt (don’t dump everything verbose)
    pay: List[Dict[str, Any]] = []
    for c in criteria:
        pay.append(
            {
                "id": c.id,
                "label": c.label,
                "type": c.type,
                "scope": c.scope,
                "targets": c.targets,
                "operators": c.operators,
                "patterns": c.patterns,
                "weight": c.weight,
                "threshold": c.threshold,
                "notes": c.notes,
            }
        )
    return pay


# ---- main entrypoint ----

# in plugins/screen_A/llm_harmonizer.py

def reformulate_with_llm(
    criteria: List[Criterion],
    *,
    model: str = "gpt-4o-mini",
    temperature: float = 0.0,
    max_output_tokens: int = 2000,
    audit_outdir: Optional[str] = None,
    log_fn = None,   # <— NEW
) -> List[Criterion]:
    def _log(msg: str):
        try:
            if log_fn: log_fn(f"[LLM-HARMONIZER] {msg}\n")
        except Exception:
            pass

    if not criteria:
        _log("no criteria, returning empty")
        return []

    payload = _criterion_payload(criteria)
    messages = _build_messages(payload, model=model)
    _log(f"prepared messages; criteria={len(payload)}")

    llm_text = None
    last_err: Optional[Exception] = None

    # Try new client
    try:
        from openai import OpenAI
        _log("using OpenAI() client")
        _client = OpenAI()
        resp = _client.chat.completions.create(
            model=model,
            temperature=temperature,
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=max_output_tokens,
        )
        llm_text = resp.choices[0].message.content
        _log("OpenAI() call OK")
    except Exception as e:
        last_err = e
        _log(f"OpenAI() call failed: {e}")

    # Fallback to legacy client
    if llm_text is None:
        try:
            import openai
            _log("using legacy openai.ChatCompletion")
            resp = openai.ChatCompletion.create(
                model=model,
                temperature=temperature,
                messages=messages,
                max_tokens=max_output_tokens,
            )
            llm_text = resp["choices"][0]["message"]["content"]
            _log("legacy ChatCompletion call OK")
        except Exception as e2:
            if last_err is None: last_err = e2
            _log(f"legacy ChatCompletion failed: {e2}")

    if llm_text is None:
        # Bubble a clear error up to the UI (will be printed with traceback)
        raise RuntimeError(f"LLM call failed (no response). Last error: {last_err}")

    _log(f"got text length={len(llm_text)}; parsing JSON")

    # ---- parse + sanitize ----
    parsed = _parse_llm_json(llm_text)
    sanitized: List[Criterion] = []
    errors: List[str] = []

    for i, d in enumerate(parsed, 1):
        try:
            clean = _sanitize_item(d)
            # ensure id
            if not clean.get("id"):
                clean["id"] = f"C{i:02d}"
            c = criterion_from_dict(clean)
            c.validate()
            sanitized.append(c)
        except Exception as ex:
            errors.append(f"row {i}: {ex}")

    # If everything was rejected, fallback to original inputs to avoid empty result surprises
    result = sanitized if sanitized else criteria

    # ---- optional audit (best-effort) ----
    if audit_outdir:
        try:
            from .reports import save_criteria_audit  # if you add this helper later
            save_criteria_audit(
                audit_outdir,
                before=payload,
                after=[_criterion_payload([c])[0] for c in sanitized] if sanitized else payload,
                model_params={"model": model, "temperature": temperature},
                errors=errors,
            )
        except Exception:
            pass

    return result

def _self_test_llm(model: str = "gpt-4o-mini") -> str:
    # minimal request to verify we hit the API & see it on the dashboard
    try:
        from openai import OpenAI
        c = OpenAI()
        r = c.chat.completions.create(
            model=model,
            temperature=0.0,
            messages=[{"role":"system","content":"Return JSON: {\"ok\":true}"},
                      {"role":"user","content":"ok"}],
            response_format={"type":"json_object"},
            max_tokens=20,
        )
        return r.choices[0].message.content
    except Exception as e:
        try:
            import openai
            r = openai.ChatCompletion.create(
                model=model,
                temperature=0.0,
                messages=[{"role":"system","content":"Return JSON: {\"ok\":true}"},
                          {"role":"user","content":"ok"}],
                max_tokens=20,
            )
            return r["choices"][0]["message"]["content"]
        except Exception as e2:
            return f"ERROR: {e} | {e2}"
