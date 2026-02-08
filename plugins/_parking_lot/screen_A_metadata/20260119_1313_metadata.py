# -*- coding: utf-8 -*-
"""screen_A_metadata.metadata (v2)

Screen A — metadata-only screener (Contract v2 / 2026-01-18)

This module implements the frozen decision contract:
  Pipeline stages: EH -> IH -> EL -> IL
  Criterion statuses: MET | FAILED | MISSING | UNCERTAIN
    - UNCERTAIN is only produced by LLM criteria.
  Stage decision rule (uniform):
    - if any criterion is FAILED        -> OUT
    - else if all criteria are MET      -> PASS_CLEAN
    - else                              -> PASS_FLAGGED (or REVIEW if stage == IL)
    - if stage has no criteria          -> PASS_CLEAN

Include vs Exclude semantics are standardized so the rule “any FAILED -> OUT” is valid:
  - Include criterion:  condition true  -> MET ; condition false -> FAILED ; missing field -> MISSING
  - Exclude criterion:  condition true  -> FAILED (exclusion hit) ; condition false -> MET ; missing field -> MISSING

Heuristic criteria are evaluated with deterministic operators (contains/regex/equals/in_list/not_in/gte/lte/between).
LLM criteria are evaluated conservatively: status becomes MET/FAILED only if
  confidence >= threshold AND quote_valid == True AND decision in {meet, not_meet};
otherwise UNCERTAIN (or MISSING if the target field is empty).

Public API (used by plugin layer):
  - parse_A_csv_xlsx(path) -> List[Dict]
  - screen_metadata(A, criteria, ..., subrun=...) -> Dict with caches

Notes:
  - Many legacy parameters are accepted for backward compatibility but are not used by the contract.
  - Progress/cancellation hooks are preserved (kinds: h_criterion_start/done, l_criterion_start/done, l_batch,...)

"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Callable, Literal, Union
import csv
import os
import re
import math
import time
import json
import hashlib

# Optional XLSX via pandas
try:
    import pandas as _pd  # type: ignore
    _PANDAS_OK = True
except Exception:
    _pd = None
    _PANDAS_OK = False

from .core import (
    canonicalize_headers,
    presence_flags,
    normalize_text_for_match,
    normalize_lang,
    normalize_doc_type,
    normalize_availability,
    chunked,
    BATCH_SIZE_DEFAULT,
    TOKENS_PER_ITEM_EST,
)


# -----------------------------------------------------------------------------
# Progress + cancellation
# -----------------------------------------------------------------------------

class _Cancelled(RuntimeError):
    pass


def _emit(progress: Optional[Callable[[Dict[str, Any]], None]], payload: Dict[str, Any]) -> None:
    if not progress:
        return
    try:
        if "ts" not in payload:
            payload["ts"] = time.time()
        progress(payload)
    except Exception:
        # never let UI callback errors break the engine
        pass


def _check_cancel(cancel_token: Optional[object]) -> None:
    if cancel_token is None:
        return
    try:
        if getattr(cancel_token, "cancelled", False):
            raise _Cancelled("cancelled")
    except AttributeError:
        return


# -----------------------------------------------------------------------------
# A ingest
# -----------------------------------------------------------------------------


def parse_A_csv_xlsx(path: str) -> List[Dict[str, Any]]:
    """Load A-items from CSV/XLSX, normalize headers, compute presence flags,
    and normalize common categorical fields (lang, doc_type, availability)."""

    ext = os.path.splitext(path)[1].lower()

    if ext in (".xlsx", ".xls") and _PANDAS_OK:
        df = _pd.read_excel(path)  # type: ignore
        rows: List[Dict[str, Any]] = df.to_dict(orient="records")  # type: ignore
    else:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))

    out: List[Dict[str, Any]] = []
    for i, r in enumerate(rows):
        row = canonicalize_headers(r, idx=i)

        if row.get("lang") is not None:
            row["lang"] = normalize_lang(row.get("lang")) or row.get("lang")
        if row.get("doc_type") is not None:
            row["doc_type"] = normalize_doc_type(row.get("doc_type")) or row.get("doc_type")
        if row.get("availability") is not None:
            row["availability"] = normalize_availability(row.get("availability")) or row.get("availability")

        row.update(presence_flags(row))
        out.append(row)

    return out


# -----------------------------------------------------------------------------
# Contract vocabulary
# -----------------------------------------------------------------------------

Status = Literal["MET", "FAILED", "MISSING", "UNCERTAIN"]
Stage = Literal["EH", "IH", "EL", "IL"]
Outcome = Literal["OUT", "PASS_CLEAN", "PASS_FLAGGED", "REVIEW"]


def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _crit_stage(c: Dict[str, Any]) -> Literal["H", "L"]:
    how = (c.get("how") or "heuristic").strip().lower()
    op = (c.get("operator") or "").strip().lower()
    return "L" if (how == "llm" or op == "llm") else "H"


def _crit_type(c: Dict[str, Any]) -> Literal["include", "exclude"]:
    t = (c.get("type") or "include").strip().lower()
    return "exclude" if t == "exclude" else "include"


def _targets(c: Dict[str, Any]) -> List[str]:
    raw = (c.get("target") or "").strip()
    if not raw:
        # contract examples default to abstract/title depending on criterion;
        # keep predictable default.
        return ["abstract"]
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts or ["abstract"]


def _stage_outcome(stage: Stage, statuses: List[Status]) -> Outcome:
    if not statuses:
        return "PASS_CLEAN"
    if any(s == "FAILED" for s in statuses):
        return "OUT"
    if all(s == "MET" for s in statuses):
        return "PASS_CLEAN"
    # no FAILED, but at least one MISSING or UNCERTAIN
    if stage == "IL":
        return "REVIEW"
    return "PASS_FLAGGED"


def _stage_name(stage: Stage) -> str:
    return stage


# -----------------------------------------------------------------------------
# Heuristic evaluation
# -----------------------------------------------------------------------------


def _get_field_text(item: Dict[str, Any], field: str) -> str:
    v = item.get(field)
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return str(v)


def _heuristic_condition(item: Dict[str, Any], crit: Dict[str, Any]) -> Tuple[Optional[bool], Dict[str, Any]]:
    """Return (condition_true|False|None_if_missing, evidence_dict).

    condition refers to the raw predicate (e.g., "contains keyword", "year>=2018").
    Mapping to MET/FAILED depends on include/exclude semantics (see _status_from_condition).
    """

    operator = (crit.get("operator") or "").strip().lower()
    tgs = _targets(crit)
    what_list = [normalize_text_for_match(w) for w in _as_list(crit.get("what")) if str(w).strip()]

    # fetch and normalize target texts (for matching)
    raw_texts = {t: _get_field_text(item, t) for t in tgs}
    norm_texts = {t: normalize_text_for_match(raw_texts[t]) for t in tgs}

    has_any = any(bool(norm_texts[t]) for t in tgs)
    has_all = all(bool(norm_texts[t]) for t in tgs)

    evidence: Dict[str, Any] = {
        "kind": "heuristic",
        "operator": operator,
        "target": ",".join(tgs),
    }

    # MISSING if the criterion has no usable field content
    if not has_any:
        evidence["missing_targets"] = tgs
        return None, evidence

    # contains
    if operator == "contains":
        matched: List[Dict[str, Any]] = []
        for t in tgs:
            txt = norm_texts[t]
            if not txt:
                continue
            hits = [w for w in what_list if w and (w in txt)]
            if hits:
                matched.append({"field": t, "hits": hits})
        evidence["matched"] = matched
        return (len(matched) > 0), evidence

    # regex
    if operator == "regex":
        pat = what_list[0] if what_list else ""
        evidence["pattern"] = pat
        try:
            rx = re.compile(pat, flags=re.I)
        except Exception as e:
            evidence["regex_error"] = str(e)
            # treat as missing/unevaluable → None (so stage becomes PASS_FLAGGED instead of OUT)
            return None, evidence

        for t in tgs:
            txt_raw = raw_texts[t]
            if not txt_raw:
                continue
            m = rx.search(txt_raw)
            if m:
                evidence["match"] = {"field": t, "span": [m.start(), m.end()], "text": m.group(0)[:160]}
                return True, evidence
        return False, evidence

    # equals / in_list
    if operator in {"equals", "in_list"}:
        vals = set(what_list)
        evidence["values"] = list(vals)
        for t in tgs:
            v = normalize_text_for_match(raw_texts[t])
            if not v:
                continue
            if v in vals:
                evidence["match"] = {"field": t, "value": v}
                return True, evidence
        return False, evidence

    # not_in
    if operator == "not_in":
        if not has_all:
            evidence["missing_targets"] = [t for t in tgs if not norm_texts[t]]
            return None, evidence
        vals = set(what_list)
        evidence["values"] = list(vals)
        # condition_true means "all field values are not in vals"
        for t in tgs:
            v = normalize_text_for_match(raw_texts[t])
            if v in vals:
                evidence["violations"] = [{"field": t, "value": v}]
                return False, evidence
        return True, evidence

    # numeric year range
    if operator in {"gte", "lte", "between"}:
        # prefer explicit year field even if target says otherwise
        field = "year" if "year" in tgs else tgs[0]
        raw = _get_field_text(item, field).strip()
        if not raw:
            evidence["missing_targets"] = [field]
            return None, evidence
        try:
            y = int(float(raw))
        except Exception:
            evidence["parse_error"] = f"cannot parse int: {raw[:32]}"
            return None, evidence

        evidence["year"] = y
        try:
            if operator == "gte":
                lo = int(float(what_list[0]))
                evidence["gte"] = lo
                return (y >= lo), evidence
            if operator == "lte":
                hi = int(float(what_list[0]))
                evidence["lte"] = hi
                return (y <= hi), evidence
            lo = int(float(what_list[0])); hi = int(float(what_list[1]))
            evidence["between"] = [lo, hi]
            return (lo <= y <= hi), evidence
        except Exception as e:
            evidence["range_error"] = str(e)
            return None, evidence

    # llm operator is evaluated elsewhere
    if operator == "llm":
        return None, {"kind": "heuristic", "operator": "llm", "target": ",".join(tgs)}

    # unknown operator → unevaluable
    evidence["unknown_operator"] = operator
    return None, evidence


def _status_from_condition(crit_type: Literal["include", "exclude"], cond: Optional[bool]) -> Status:
    if cond is None:
        return "MISSING"
    if crit_type == "include":
        return "MET" if cond else "FAILED"
    # exclude criterion: cond True means exclusion satisfied → FAILED
    return "FAILED" if cond else "MET"


# -----------------------------------------------------------------------------
# LLM evaluation (extractive + conservative)
# -----------------------------------------------------------------------------


def _llm_available() -> bool:
    try:
        from openai import OpenAI  # type: ignore
        return bool(os.environ.get("OPENAI_API_KEY"))
    except Exception:
        return False


def _truncate(s: str, n: int) -> str:
    if not s:
        return ""
    s = str(s)
    return (s[: n - 1] + "…") if (n and len(s) > n) else s


def _fingerprint_for_llm(item: Dict[str, Any], crit: Dict[str, Any], trunc: int) -> str:
    tgs = _targets(crit)
    buf: List[str] = []
    for t in tgs:
        txt = _get_field_text(item, t)
        if trunc and len(txt) > trunc:
            txt = txt[:trunc]
        buf.append(f"{t}::{txt}")
    payload = "||".join(buf)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _build_llm_messages_for_criterion(
    criterion: Dict[str, Any],
    items: List[Dict[str, Any]],
    trunc_chars: int,
) -> List[Dict[str, str]]:
    """Messages for one criterion over many items.

    IMPORTANT: contract requires extractive evidence:
      - field (title|abstract|keywords)
      - quote (exact substring)
      - span [start,end]
    """

    sys = (
        "You are evaluating research items against ONE screening criterion. "
        "Return JSON only. For each item output an object with keys: "
        "a_id, decision ('meet'|'not_meet'|'uncertain'), confidence (0..1), "
        "field ('title'|'abstract'|'keywords'), quote (exact substring from that field), span [start,end]. "
        "Return a JSON array of objects, nothing else."
    )

    c_pack = {
        "id": str(criterion.get("id") or ""),
        "type": _crit_type(criterion),
        "operator": (criterion.get("operator") or "llm"),
        "target": ",".join(_targets(criterion)),
        "what": _as_list(criterion.get("what")),
        "label": criterion.get("label") or "",
        "threshold": float(criterion.get("threshold") or 0.0),
    }

    payload = []
    for it in items:
        payload.append({
            "a_id": str(it.get("a_id")),
            "title": _truncate(_get_field_text(it, "title"), trunc_chars),
            "abstract": _truncate(_get_field_text(it, "abstract"), trunc_chars),
            "keywords": _truncate(_get_field_text(it, "keywords"), trunc_chars),
        })

    user_obj = {"criterion": c_pack, "items": payload}

    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": json.dumps(user_obj, ensure_ascii=False)},
    ]


def _parse_llm_json_array(txt: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads(txt)
        if isinstance(data, dict) and "results" in data:
            data = data["results"]
        if isinstance(data, list):
            return data
    except Exception:
        pass

    # fallback: attempt to extract array
    m = re.search(r"\[[\s\S]*\]", txt)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except Exception:
        return []


def run_m1_llm_for_criterion(
    criterion: Dict[str, Any],
    items: List[Dict[str, Any]],
    *,
    model: Optional[str],
    trunc_chars: int = 1500,
    batch_size: int = BATCH_SIZE_DEFAULT,
    log: Optional[Callable[[str], None]] = None,
    progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_token: Optional[object] = None,
    crit_idx: Optional[int] = None,
    crit_total: Optional[int] = None,
    block_tag: str = "include",
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Return (a_id, criterion_id) -> llm_decision.

    llm_decision keys:
      used, decision, confidence, field, quote, span, quote_valid
    """

    cid = str(criterion.get("id") or "")
    if not items:
        _emit(progress, {
            "kind": "l_criterion_start", "stage": "L", "block": block_tag,
            "crit_idx": crit_idx, "crit_total": crit_total,
            "crit_id": cid, "label": criterion.get("label"),
            "batches_total": 0,
        })
        _emit(progress, {"kind": "l_criterion_done", "stage": "L", "block": block_tag, "crit_idx": crit_idx})
        return {}

    if not model:
        if log:
            log(f"[M1-LLM] criterion {cid}: model=None; skipping LLM.\n")
        _emit(progress, {
            "kind": "l_criterion_start", "stage": "L", "block": block_tag,
            "crit_idx": crit_idx, "crit_total": crit_total,
            "crit_id": cid, "label": criterion.get("label"),
            "batches_total": 0,
        })
        _emit(progress, {"kind": "l_criterion_done", "stage": "L", "block": block_tag, "crit_idx": crit_idx})
        return {}

    if not _llm_available():
        if log:
            log(f"[M1-LLM] criterion {cid}: OPENAI_API_KEY not available; skipping LLM.\n")
        _emit(progress, {
            "kind": "l_criterion_start", "stage": "L", "block": block_tag,
            "crit_idx": crit_idx, "crit_total": crit_total,
            "crit_id": cid, "label": criterion.get("label"),
            "batches_total": 0,
        })
        _emit(progress, {"kind": "l_criterion_done", "stage": "L", "block": block_tag, "crit_idx": crit_idx})
        return {}

    from openai import OpenAI  # type: ignore

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    def _estimate_tokens(n_items: int) -> int:
        overhead = 2500
        return overhead + n_items * TOKENS_PER_ITEM_EST

    def _call_once(batch_items: List[Dict[str, Any]], cur_trunc: int):
        msgs = _build_llm_messages_for_criterion(criterion, batch_items, cur_trunc)
        return client.chat.completions.create(
            model=model,
            messages=msgs,
            temperature=0.0,
        )

    out: Dict[Tuple[str, str], Dict[str, Any]] = {}

    batches = [list(b) for b in chunked(items, max(1, int(batch_size)))]
    total_batches = len(batches)

    _emit(progress, {
        "kind": "l_criterion_start", "stage": "L", "block": block_tag,
        "crit_idx": crit_idx, "crit_total": crit_total,
        "crit_id": cid, "label": criterion.get("label"),
        "batches_total": total_batches,
    })

    for bi, raw_batch in enumerate(batches, start=1):
        _check_cancel(cancel_token)

        cur_batch = list(raw_batch)
        cur_trunc = int(trunc_chars)

        # Preflight shrink if we overestimate huge context
        while _estimate_tokens(len(cur_batch)) > 160_000 and len(cur_batch) > 1:
            new_len = math.ceil(len(cur_batch) / 2)
            _emit(progress, {
                "kind": "l_batch_retry", "stage": "L", "block": block_tag,
                "crit_idx": crit_idx, "batch_idx": bi,
                "note": f"preflight → shrinking batch {len(cur_batch)}→{new_len}",
            })
            cur_batch = cur_batch[:new_len]

        _emit(progress, {
            "kind": "l_batch", "stage": "L", "block": block_tag,
            "crit_idx": crit_idx, "batch_idx": bi, "batch_total": total_batches,
            "sub": "preparing",
        })

        attempts = 0
        while True:
            attempts += 1
            _check_cancel(cancel_token)
            _emit(progress, {
                "kind": "l_batch", "stage": "L", "block": block_tag,
                "crit_idx": crit_idx, "batch_idx": bi, "batch_total": total_batches,
                "sub": "sending",
            })

            try:
                _emit(progress, {
                    "kind": "l_batch", "stage": "L", "block": block_tag,
                    "crit_idx": crit_idx, "batch_idx": bi, "batch_total": total_batches,
                    "sub": "waiting",
                })
                resp = _call_once(cur_batch, cur_trunc)

                _check_cancel(cancel_token)
                _emit(progress, {
                    "kind": "l_batch", "stage": "L", "block": block_tag,
                    "crit_idx": crit_idx, "batch_idx": bi, "batch_total": total_batches,
                    "sub": "parsing",
                })

                txt = resp.choices[0].message.content or "[]"
                arr = _parse_llm_json_array(txt)

                idx_map = {str(it.get("a_id")): it for it in cur_batch}

                for obj in arr:
                    a_id = str(obj.get("a_id"))
                    decision = (obj.get("decision") or "uncertain").strip().lower()
                    try:
                        confidence = float(obj.get("confidence") or 0.0)
                    except Exception:
                        confidence = 0.0
                    field = (obj.get("field") or "").strip().lower() or None
                    quote = obj.get("quote") or None
                    span = obj.get("span") or None

                    quote_valid = False
                    if field in {"title", "abstract", "keywords"} and quote:
                        fld_txt = _get_field_text(idx_map.get(a_id, {}), field)
                        quote_valid = bool(quote in fld_txt)

                    out[(a_id, cid)] = {
                        "used": True,
                        "decision": decision,
                        "confidence": confidence,
                        "field": field,
                        "quote": quote,
                        "span": span if isinstance(span, list) and len(span) == 2 else None,
                        "quote_valid": bool(quote_valid),
                    }

                _emit(progress, {
                    "kind": "l_batch", "stage": "L", "block": block_tag,
                    "crit_idx": crit_idx, "batch_idx": bi, "batch_total": total_batches,
                    "sub": "batch_done",
                })
                break

            except Exception as e:
                msg = str(e)
                hit_429 = (
                    "rate_limit" in msg.lower() or "too many" in msg.lower() or
                    "request too large" in msg.lower() or "429" in msg
                )

                if not hit_429 or len(cur_batch) == 1:
                    if log:
                        log(f"[M1-LLM] ERROR {cid} batch {bi} (attempt {attempts}): {e}\n")
                    _emit(progress, {
                        "kind": "l_batch_retry", "stage": "L", "block": block_tag,
                        "crit_idx": crit_idx, "batch_idx": bi,
                        "note": f"error: {msg[:160]}",
                    })
                    break

                # shrink or truncate to recover
                if len(cur_batch) > 2:
                    new_len = max(1, len(cur_batch) // 2)
                    _emit(progress, {
                        "kind": "l_batch_retry", "stage": "L", "block": block_tag,
                        "crit_idx": crit_idx, "batch_idx": bi,
                        "note": f"429 → shrinking batch {len(cur_batch)}→{new_len}",
                    })
                    cur_batch = cur_batch[:new_len]
                else:
                    new_trunc = max(600, int(cur_trunc * 0.75))
                    if new_trunc != cur_trunc:
                        _emit(progress, {
                            "kind": "l_batch_retry", "stage": "L", "block": block_tag,
                            "crit_idx": crit_idx, "batch_idx": bi,
                            "note": f"429 → reducing trunc {cur_trunc}→{new_trunc}",
                        })
                        cur_trunc = new_trunc
                    else:
                        _emit(progress, {
                            "kind": "l_batch_retry", "stage": "L", "block": block_tag,
                            "crit_idx": crit_idx, "batch_idx": bi,
                            "note": "429 persists → short backoff 1.0s",
                        })
                        time.sleep(1.0)
                time.sleep(0.5)

    _emit(progress, {
        "kind": "l_criterion_done", "stage": "L", "block": block_tag,
        "crit_idx": crit_idx,
    })

    return out


def _llm_status_for_item(
    item: Dict[str, Any],
    crit: Dict[str, Any],
    llm_dec: Optional[Dict[str, Any]],
) -> Tuple[Status, Dict[str, Any]]:
    """Map LLM result to MET/FAILED/UNCERTAIN/MISSING according to the contract."""

    tgs = _targets(crit)
    raw_texts = {t: _get_field_text(item, t) for t in tgs}
    has_any = any(bool(raw_texts[t].strip()) for t in tgs)

    evidence: Dict[str, Any] = {
        "kind": "llm",
        "target": ",".join(tgs),
        "threshold": float(crit.get("threshold") or 0.0),
    }

    if not has_any:
        evidence["missing_targets"] = tgs
        return "MISSING", evidence

    if not llm_dec or not llm_dec.get("used"):
        evidence["note"] = "no_llm_result"
        return "UNCERTAIN", evidence

    decision = (llm_dec.get("decision") or "uncertain").strip().lower()
    try:
        confidence = float(llm_dec.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0

    quote_valid = bool(llm_dec.get("quote_valid"))
    thr = float(crit.get("threshold") or 0.0)

    evidence.update({
        "decision": decision,
        "confidence": confidence,
        "field": llm_dec.get("field"),
        "quote": llm_dec.get("quote"),
        "span": llm_dec.get("span"),
        "quote_valid": quote_valid,
    })

    if (confidence >= thr) and quote_valid and decision in {"meet", "not_meet"}:
        # status mapping per contract (section 9.2 + include/exclude semantics section 6)
        ctype = _crit_type(crit)
        if ctype == "include":
            return ("MET" if decision == "meet" else "FAILED"), evidence
        # exclude
        return ("FAILED" if decision == "meet" else "MET"), evidence

    return "UNCERTAIN", evidence


# -----------------------------------------------------------------------------
# Stage runner
# -----------------------------------------------------------------------------


def _stage_criteria(criteria: List[Dict[str, Any]], stage: Stage) -> List[Dict[str, Any]]:
    active = [c for c in criteria if c.get("enabled", True)]
    if stage == "EH":
        return [c for c in active if _crit_stage(c) == "H" and _crit_type(c) == "exclude"]
    if stage == "IH":
        return [c for c in active if _crit_stage(c) == "H" and _crit_type(c) == "include"]
    if stage == "EL":
        return [c for c in active if _crit_stage(c) == "L" and _crit_type(c) == "exclude"]
    # IL
    return [c for c in active if _crit_stage(c) == "L" and _crit_type(c) == "include"]


def _stage_progress_kind(stage: Stage) -> Literal["H", "L"]:
    return "H" if stage in ("EH", "IH") else "L"


def _run_stage(
    stage: Stage,
    items: List[Dict[str, Any]],
    criteria: List[Dict[str, Any]],
    *,
    llm_model: Optional[str] = None,
    llm_trunc_chars: int = 1500,
    llm_batch_size: int = BATCH_SIZE_DEFAULT,
    llm_cache: Optional[Dict[Tuple[str, str, str], Dict[str, Any]]] = None,
    log: Optional[Callable[[str], None]] = None,
    progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_token: Optional[object] = None,
) -> Dict[str, Any]:
    """Evaluate one contract stage over provided items."""

    _check_cancel(cancel_token)

    stage_crit = _stage_criteria(criteria, stage)
    kind = _stage_progress_kind(stage)

    # Per-item accumulation
    per_item: Dict[str, Dict[str, Any]] = {}
    for it in items:
        a_id = str(it.get("a_id"))
        per_item[a_id] = {
            "a_id": a_id,
            "title": _get_field_text(it, "title"),
            "criteria_details": [],  # list of {id,label,type,status,evidence}
        }

    # Evaluate criteria sequentially (full traceability)
    for ci, c in enumerate(stage_crit, start=1):
        _check_cancel(cancel_token)

        cid = str(c.get("id") or "")
        ctype = _crit_type(c)
        operator = (c.get("operator") or "").strip().lower()

        if kind == "H":
            _emit(progress, {
                "kind": "h_criterion_start",
                "stage": "H",
                "block": "exclude" if stage == "EH" else "include",
                "crit_idx": ci,
                "crit_total": len(stage_crit),
                "crit_id": cid,
                "operator": c.get("operator"),
                "target": c.get("target"),
                "label": c.get("label"),
            })

        if kind == "L":
            # Batch LLM calls for this criterion, for items that have any target text.
            tgs = _targets(c)

            # ensure cache dict
            if llm_cache is None:
                llm_cache = {}

            # queue for LLM
            queue: List[Dict[str, Any]] = []
            fps: Dict[str, str] = {}
            for it in items:
                a_id = str(it.get("a_id"))
                fp = _fingerprint_for_llm(it, c, llm_trunc_chars)
                fps[a_id] = fp
                has_any = any(bool(_get_field_text(it, t).strip()) for t in tgs)
                if not has_any:
                    continue
                key = (cid, a_id, fp)
                if key not in llm_cache:
                    queue.append(it)

            # LLM call only for operator/how=llm criteria
            if operator == "llm" or _crit_stage(c) == "L":
                # If model missing, we still emit progress start/done with 0 batches for UI consistency
                m = run_m1_llm_for_criterion(
                    c,
                    queue,
                    model=llm_model,
                    trunc_chars=llm_trunc_chars,
                    batch_size=llm_batch_size,
                    log=log,
                    progress=progress,
                    cancel_token=cancel_token,
                    crit_idx=ci,
                    crit_total=len(stage_crit),
                    block_tag=("exclude" if stage == "EL" else "include"),
                )
                for it in queue:
                    a_id = str(it.get("a_id"))
                    dec = m.get((a_id, cid))
                    if dec:
                        llm_cache[(cid, a_id, fps[a_id])] = dec
            else:
                # non-llm operator in an L stage (rare): no LLM needed
                _emit(progress, {
                    "kind": "l_criterion_start", "stage": "L",
                    "block": ("exclude" if stage == "EL" else "include"),
                    "crit_idx": ci, "crit_total": len(stage_crit),
                    "crit_id": cid, "label": c.get("label"),
                    "batches_total": 0,
                })
                _emit(progress, {
                    "kind": "l_criterion_done", "stage": "L",
                    "block": ("exclude" if stage == "EL" else "include"),
                    "crit_idx": ci,
                })

        # Apply evaluation result per item
        for it in items:
            _check_cancel(cancel_token)
            a_id = str(it.get("a_id"))

            if kind == "H":
                cond, ev = _heuristic_condition(it, c)
                status: Status = _status_from_condition(ctype, cond)
                detail = {
                    "id": cid,
                    "label": c.get("label") or "",
                    "type": ctype,
                    "stage": stage,
                    "status": status,
                    "evidence": ev,
                }
            else:
                # kind == "L"
                if operator == "llm" or _crit_stage(c) == "L":
                    fp = _fingerprint_for_llm(it, c, llm_trunc_chars)
                    dec = (llm_cache or {}).get((cid, a_id, fp))
                    status, ev = _llm_status_for_item(it, c, dec)
                    detail = {
                        "id": cid,
                        "label": c.get("label") or "",
                        "type": ctype,
                        "stage": stage,
                        "status": status,
                        "evidence": ev,
                    }
                else:
                    # deterministic operator evaluated in an L stage (no LLM)
                    cond, ev = _heuristic_condition(it, c)
                    status = _status_from_condition(ctype, cond)
                    detail = {
                        "id": cid,
                        "label": c.get("label") or "",
                        "type": ctype,
                        "stage": stage,
                        "status": status,
                        "evidence": ev,
                    }

            per_item[a_id]["criteria_details"].append(detail)

        if kind == "H":
            _emit(progress, {
                "kind": "h_criterion_done",
                "stage": "H",
                "block": "exclude" if stage == "EH" else "include",
                "crit_idx": ci,
            })

    # Build stage rows + survivors
    rows: List[Dict[str, Any]] = []
    survivors: List[Dict[str, Any]] = []
    survivors_ids: List[str] = []
    outcome_map: Dict[str, Outcome] = {}

    # for stable row order
    item_by_id = {str(it.get("a_id")): it for it in items}

    for it in items:
        a_id = str(it.get("a_id"))
        details = per_item[a_id]["criteria_details"]
        statuses = [d["status"] for d in details]
        outcome = _stage_outcome(stage, statuses)
        outcome_map[a_id] = outcome

        failed = [d["id"] for d in details if d["status"] == "FAILED"]
        missing = [d["id"] for d in details if d["status"] == "MISSING"]
        uncertain = [d["id"] for d in details if d["status"] == "UNCERTAIN"]
        met = [d["id"] for d in details if d["status"] == "MET"]

        # matched evidence (compact)
        matched_keywords: Dict[str, List[str]] = {}
        llm_summaries: List[Dict[str, Any]] = []
        for d in details:
            ev = d.get("evidence") or {}
            if ev.get("kind") == "heuristic" and (ev.get("operator") == "contains"):
                for m in ev.get("matched") or []:
                    f = m.get("field")
                    hits = m.get("hits") or []
                    if f and hits:
                        matched_keywords.setdefault(str(f), [])
                        for h in hits:
                            if h not in matched_keywords[str(f)]:
                                matched_keywords[str(f)].append(h)
            if ev.get("kind") == "llm":
                llm_summaries.append({
                    "criterion_id": d.get("id"),
                    "decision": ev.get("decision"),
                    "confidence": ev.get("confidence"),
                    "threshold": ev.get("threshold"),
                    "field": ev.get("field"),
                    "quote": ev.get("quote"),
                    "quote_valid": ev.get("quote_valid"),
                })

        matched_evidence = {
            "matched_keywords": matched_keywords,
            "llm": llm_summaries,
        }

        # stage_reason_summary (readable)
        parts: List[str] = []
        if failed:
            parts.append(f"FAILED={','.join(failed)}")
        if missing:
            parts.append(f"MISSING={','.join(missing)}")
        if uncertain:
            parts.append(f"UNCERTAIN={','.join(uncertain)}")
        if met:
            parts.append(f"MET={','.join(met)}")
        reason_summary = " | ".join(parts) if parts else "no_criteria"

        row = {
            "a_id": a_id,
            "title": per_item[a_id].get("title") or "",
            "stage": _stage_name(stage),
            "stage_outcome": outcome,
            "passed_to_next": bool(outcome != "OUT"),
            "failed_criteria_ids": failed,
            "missing_criteria_ids": missing,
            "uncertain_criteria_ids": uncertain,
            "met_criteria_ids": met,
            "matched_evidence": json.dumps(matched_evidence, ensure_ascii=False),
            "stage_reason_summary": reason_summary,
            "criteria_details": json.dumps(details, ensure_ascii=False),
            # history is filled by caller (needs previous stages)
            "history": "",
        }

        rows.append(row)

        if outcome != "OUT":
            survivors.append(it)
            survivors_ids.append(a_id)

    return {
        "stage": stage,
        "rows": rows,
        "survivors": survivors,
        "survivor_ids": survivors_ids,
        "outcome_map": outcome_map,
        "llm_cache": llm_cache or {},
    }


# -----------------------------------------------------------------------------
# Main entry: contract pipeline (subrun only)
# -----------------------------------------------------------------------------

def screen_metadata(
    A: List[Dict[str, Any]],
    criteria: List[Dict[str, Any]],
    *,
    # Backward-compatible aliases expected by plugin.py
    A_rows: Optional[List[Dict[str, Any]]] = None,
    criteria_rows: Optional[List[Dict[str, Any]]] = None,
    # Legacy parameters kept for compatibility (mostly unused in v2)
    pass_thr: float = 0.60,
    border_thr: float = 0.40,
    missing_policy: str = "unknown",
    llm_model: Optional[str] = None,
    llm_trunc_chars: int = 1500,
    llm_batch_size: int = BATCH_SIZE_DEFAULT,
    stage_h_include_mode: str = "all",
    stage_l_include_mode: str = "all",
    randomize_within_blocks: bool = False,
    random_seed: Optional[Union[str, int]] = None,
    log: Optional[Callable[[str], None]] = None,
    hard_stop: bool = False,
    progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_token: Optional[object] = None,
    subrun: Optional[Literal["EH", "IH", "EL", "IL"]] = None,
    return_stage_caches: bool = True,
    reuse_from_stage: Optional[Literal["EL", "EH", "IH"]] = None,
    initial_a_ids: Optional[List[str]] = None,
    prior_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

    """Run Screen A metadata-only screening for a single stage (subrun) following Contract v2.

    Returns:
      {
        "mode": <subrun>,
        "caches": {
           "EH": {...}, "IH": {...}, "EL": {...}, "IL": {...}, "FINAL": {...}, "meta": {...}
        },
        "final_results": [...]   # only for IL (FINAL rows)
      }

    Reuse shortcuts (optional):
    Progressive merge (Option B):
      - Pass prior_result=<previous call result dict OR its ["caches"] dict>.
      - The function will run ONLY the requested subrun stage and will:
          * take its input working set from the prior stage survivor_ids
          * merge prior stage caches into the returned caches
          * (for IL) build FINAL using merged outcomes/reasons from EH+IH+EL+IL

    Legacy reuse shortcuts (optional / backward compatibility):
      - subrun="IH", reuse_from_stage="EH", initial_a_ids=[...] will skip EH.
      - subrun="EL", reuse_from_stage="IH", initial_a_ids=[...] will skip EH+IH.
      - subrun="IL", reuse_from_stage="EL", initial_a_ids=[...] will skip EH+IH+EL.
    """

    _check_cancel(cancel_token)

    # Backward-compatible aliases expected by plugin.py
    if A_rows is not None:
        A = A_rows
    if criteria_rows is not None:
        criteria = criteria_rows

    mode = (subrun or "").upper()

    if mode not in {"EH", "IH", "EL", "IL"}:
        raise ValueError("Contract v2 requires subrun one of: 'EH', 'IH', 'EL', 'IL'.")

    # meta + progressive merge support
    prior_caches: Optional[Dict[str, Any]] = None
    if prior_result and isinstance(prior_result, dict):
        # accept either the full result {"mode":..,"caches":..} OR the caches dict itself
        if isinstance(prior_result.get("caches"), dict):
            prior_caches = prior_result.get("caches")  # type: ignore
        else:
            prior_caches = prior_result

    criteria_canon = sorted(criteria, key=lambda c: str((c or {}).get("id") or ""))
    criteria_fingerprint = hashlib.sha256(
        json.dumps(criteria_canon, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]

    a_ids = sorted(str(it.get("a_id")) for it in A)
    a_fingerprint = hashlib.sha256(("|".join(a_ids)).encode("utf-8")).hexdigest()[:16]

    engine_fingerprint = hashlib.sha256(
        json.dumps(
            {"llm_model": llm_model, "llm_trunc_chars": llm_trunc_chars, "llm_batch_size": llm_batch_size},
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()[:16]

    prior_meta = (prior_caches or {}).get("meta", {}) if isinstance((prior_caches or {}).get("meta", {}), dict) else {}

    prior_fp = prior_meta.get("criteria_fingerprint")
    if prior_fp and prior_fp != criteria_fingerprint:
        raise ValueError("Criteria changed since the previous stage run; reset staged flow and rerun from EH.")

    prior_a_fp = prior_meta.get("a_fingerprint")
    if prior_a_fp and prior_a_fp != a_fingerprint:
        raise ValueError("A-items changed since the previous stage run; reset staged flow and rerun from EH.")

    prior_eng_fp = prior_meta.get("engine_fingerprint")
    if prior_eng_fp and prior_eng_fp != engine_fingerprint:
        raise ValueError("LLM settings changed since the previous stage run; reset staged flow and rerun from EH.")

    caches: Dict[str, Any] = {
        "EH": (prior_caches.get("EH") or {}) if prior_caches else {},
        "IH": (prior_caches.get("IH") or {}) if prior_caches else {},
        "EL": (prior_caches.get("EL") or {}) if prior_caches else {},
        "IL": (prior_caches.get("IL") or {}) if prior_caches else {},
        "FINAL": (prior_caches.get("FINAL") or {}) if prior_caches else {},
        "meta": {
            "contract": "v2",
            "criteria_fingerprint": criteria_fingerprint,
            "a_fingerprint": a_fingerprint,
            "engine_fingerprint": engine_fingerprint,
            "merged_from_prior": bool(prior_caches),
            "pass_thr_legacy": pass_thr,
            "border_thr_legacy": border_thr,
            "missing_policy_legacy": missing_policy,
            "stage_h_include_mode_legacy": stage_h_include_mode,
            "stage_l_include_mode_legacy": stage_l_include_mode,
            "hard_stop_legacy": hard_stop,
            "randomize_within_blocks_legacy": randomize_within_blocks,
            "random_seed_legacy": random_seed,
            "llm_model": llm_model,
            "llm_trunc_chars": llm_trunc_chars,
            "llm_batch_size": llm_batch_size,
            "reused_from": reuse_from_stage,
        },
    }

    # Input selection (when reusing survivors from a previous run)
    def _select_by_ids(items: List[Dict[str, Any]], ids: Optional[List[str]]) -> List[Dict[str, Any]]:
        if not ids:
            return list(items)
        wanted = {str(x) for x in ids}
        return [it for it in items if str(it.get("a_id")) in wanted]

    # Shared LLM cache across stages within one call (when running multiple stages)
    llm_cache: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    # Helpers to build history strings (seed from prior stages if provided)
    history_map: Dict[str, List[str]] = {str(it.get("a_id")): [] for it in A}
    if prior_caches:
        for _st in ("EH", "IH", "EL", "IL"):
            for r in ((prior_caches.get(_st) or {}).get("rows", []) or []):
                a_id = str(r.get("a_id"))
                hist = (r.get("history") or "").strip()
                if hist:
                    history_map[a_id] = [p.strip() for p in hist.split("->") if p.strip()]

    def _apply_history(stage: Stage, stage_rows: List[Dict[str, Any]]):
        for r in stage_rows:
            a_id = str(r.get("a_id"))
            frag = f"{stage}:{r.get('stage_outcome')}"
            # compact reason hints (failed/missing/uncertain counts)
            f = r.get("failed_criteria_ids") or []
            m = r.get("missing_criteria_ids") or []
            u = r.get("uncertain_criteria_ids") or []
            if f or m or u:
                frag += f"(F={len(f)},M={len(m)},U={len(u)})"
            prev = [p for p in history_map.get(a_id, []) if not p.strip().startswith(f"{stage}:")]
            prev.append(frag)
            history_map[a_id] = prev
            r["history"] = " -> ".join(history_map[a_id])

    # Stage execution plan (strict progressive / contract-safe):
    # - EH can run standalone (start a chain)
    # - IH/EL/IL require prior_result (previous stage caches)
    if (not prior_caches) and mode != "EH":
        raise ValueError(
            f"Progressive flow requires prior_result; run EH first, then run {mode} with prior_result=<previous result>."
        )

    stages_to_run: List[Stage] = [mode]

    # Determine starting working set (strict progressive)
    working = list(A)

    if mode != "EH":
        prev_stage = {"IH": "EH", "EL": "IH", "IL": "EL"}[mode]

        # For IL, we also require that EH/IH/EL have rows (needed for FINAL reasons)
        if mode == "IL":
            for req in ("EH", "IH", "EL"):
                if not isinstance((prior_caches.get(req) or {}).get("survivor_ids"), list):
                    raise ValueError(f"Progressive flow requires stage {req} completed before running IL.")
                if not isinstance((prior_caches.get(req) or {}).get("rows"), list):
                    raise ValueError(
                        f"Progressive flow requires stage {req} rows available before running IL (needed for FINAL report)."
                    )

        prev_ids = (prior_caches.get(prev_stage) or {}).get("survivor_ids") if prior_caches else None
        if not isinstance(prev_ids, list):
            raise ValueError(f"Progressive flow requires stage {prev_stage} completed before running {mode}.")

        working = _select_by_ids(A, prev_ids)  # type: ignore

    stage_outputs: Dict[Stage, Dict[str, Any]] = {}

    # Run planned stages
    for st in stages_to_run:
        _check_cancel(cancel_token)
        out = _run_stage(
            st,
            working,
            criteria,
            llm_model=llm_model,
            llm_trunc_chars=llm_trunc_chars,
            llm_batch_size=llm_batch_size,
            llm_cache=llm_cache,
            log=log,
            progress=progress,
            cancel_token=cancel_token,
        )
        llm_cache = out.get("llm_cache") or llm_cache
        stage_outputs[st] = out

        _apply_history(st, out["rows"])

        # Save to caches in both contract-friendly and legacy-friendly keys
        caches[st] = {
            "rows": out["rows"],
            "survivor_ids": out["survivor_ids"],
            "outcome_map": out["outcome_map"],
            # legacy-ish conveniences
            "survivors_after_%s_ids" % st: out["survivor_ids"],
            "dropped_records": [r for r in out["rows"] if r.get("stage_outcome") == "OUT"],
            "criteria_counts": {"count": len(_stage_criteria(criteria, st))},
        }

        working = out["survivors"]

        # Stop early if this call's subrun is reached
        if st == mode:
            break

    # No legacy reuse shortcuts in strict progressive flow (Option B).

    # Build FINAL rows only in IL
    final_results: List[Dict[str, Any]] = []
    if mode == "IL":
        def _outcome_map(stage: str) -> Dict[str, Any]:
            m = (caches.get(stage) or {}).get("outcome_map")
            if isinstance(m, dict) and m:
                return m
            rows = (caches.get(stage) or {}).get("rows", []) or []
            out: Dict[str, Any] = {}
            for r in rows:
                out[str(r.get("a_id"))] = r.get("stage_outcome")
            return out

        oEH = _outcome_map("EH")
        oIH = _outcome_map("IH")
        oEL = _outcome_map("EL")
        oIL = _outcome_map("IL")

        # stage rows maps for reasons (from merged caches)
        rows_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for st in ("EH", "IH", "EL", "IL"):
            for r in ((caches.get(st) or {}).get("rows", []) or []):
                rows_map[(st, str(r.get("a_id")))] = r

        for it in A:
            a_id = str(it.get("a_id"))
            out_eh = oEH.get(a_id, "")
            out_ih = oIH.get(a_id, "")
            out_el = oEL.get(a_id, "")
            out_il = oIL.get(a_id, "")

            discarded_at = ""
            for st, ov in [("EH", out_eh), ("IH", out_ih), ("EL", out_el), ("IL", out_il)]:
                if ov == "OUT":
                    discarded_at = st
                    break

            final_outcome = "OUT" if discarded_at else (out_il or "")
            if final_outcome == "PASS_FLAGGED":
                final_outcome = "REVIEW"  # should not happen but keep safe

            final_results.append({
                "a_id": a_id,
                "title": _get_field_text(it, "title"),
                "outcome_EH": out_eh,
                "outcome_IH": out_ih,
                "outcome_EL": out_el,
                "outcome_IL": out_il,
                "discarded_at_stage": discarded_at,
                "final_outcome": final_outcome,
                "history": " -> ".join(history_map.get(a_id, [])),
                "reasons_EH": rows_map.get(("EH", a_id), {}).get("stage_reason_summary", ""),
                "reasons_IH": rows_map.get(("IH", a_id), {}).get("stage_reason_summary", ""),
                "reasons_EL": rows_map.get(("EL", a_id), {}).get("stage_reason_summary", ""),
                "reasons_IL": rows_map.get(("IL", a_id), {}).get("stage_reason_summary", ""),
            })

        caches["FINAL"] = {"rows": final_results}

    result: Dict[str, Any] = {
        "mode": mode,
        "caches": caches,
    }
    if mode == "IL":
        result["final_results"] = final_results

    return result
