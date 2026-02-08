# -*- coding: utf-8 -*-
"""
metadata.py — A-items ingest + Two-Stage Screening (Stage H heuristic → Stage L LLM)

Adds:
- progress: Optional[Callable[[dict], None]]  # structured UI events
- cancel_token: Optional[object]              # expects attribute `.cancelled: bool`

Event kinds (examples):
  H:
    {"kind":"h_criterion_start","stage":"H","block":"include","crit_idx":1,"crit_total":3,"crit_id":"IC-2",
     "operator":"contains","target":"title,abstract","label":"...", "ts":...}
    {"kind":"h_criterion_done","stage":"H","block":"include","crit_idx":1,"ts":...}

  L:
    {"kind":"l_criterion_start","stage":"L","block":"include","crit_idx":1,"crit_total":2,"crit_id":"LC-1",
     "label":"...","batches_total":16,"ts":...}
    {"kind":"l_batch","stage":"L","block":"include","crit_idx":1,"batch_idx":2,"batch_total":16,"sub":"preparing","ts":...}
    ... sub ∈ {"preparing","sending","waiting","parsing","batch_done"}
    {"kind":"l_batch_retry","stage":"L","block":"include","crit_idx":1,"batch_idx":2,"note":"429 → shrinking batch 120→60","ts":...}
    {"kind":"l_criterion_done","stage":"L","block":"include","crit_idx":1,"ts":...}
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple, Callable, Literal, Union
import csv
import os
import re
import math
import time
import hashlib
import random

# Optional XLSX via pandas
try:
    import pandas as _pd  # type: ignore
    _PANDAS_OK = True
except Exception:
    _pd = None
    _PANDAS_OK = False

from .core import (
    canonicalize_headers, presence_flags,
    normalize_text_for_match,
    normalize_lang, normalize_doc_type, normalize_availability,
    chunked, BATCH_SIZE_DEFAULT, TOKENS_PER_ITEM_EST,
)

# ----------------------- small utilities for progress/cancel ------------------

class _Cancelled(RuntimeError):
    pass

def _emit(progress: Optional[Callable[[Dict[str, Any]], None]], payload: Dict[str, Any]):
    if progress:
        try:
            if "ts" not in payload:
                payload["ts"] = time.time()
            progress(payload)
        except Exception:
            # swallow UI callback errors to avoid breaking engine
            pass

def _check_cancel(cancel_token: Optional[object]):
    if cancel_token is not None:
        try:
            if getattr(cancel_token, "cancelled", False):
                raise _Cancelled("cancelled")
        except AttributeError:
            pass

# -----------------------------------------------------------------------------
# A ingest
# -----------------------------------------------------------------------------

def parse_A_csv_xlsx(path: str) -> List[Dict[str, Any]]:
    """Load A items from CSV/XLSX, normalize headers, and compute presence flags.
       Also normalize common categorical fields (lang, doc_type, availability)."""
    ext = os.path.splitext(path)[1].lower()
    rows: List[Dict[str, Any]]

    if ext in (".xlsx", ".xls") and _PANDAS_OK:
        df = _pd.read_excel(path)
        rows = df.to_dict(orient="records")
    else:
        with open(path, "r", encoding="utf-8", newline="") as f:
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
# Helpers
# -----------------------------------------------------------------------------

def _seeded_shuffle(seq: List[Any], seed: Optional[str|int]) -> List[Any]:
    if seed is None:
        return list(seq)
    rnd = random.Random(str(seed))
    out = list(seq)
    rnd.shuffle(out)
    return out

def _stage_of(c: Dict[str, Any]) -> str:
    """Stage H: how != 'llm' and operator != 'llm' ; Stage L: otherwise."""
    how = (c.get("how") or "heuristic").strip().lower()
    op  = (c.get("operator") or "").strip().lower()
    return "L" if (how == "llm" or op == "llm") else "H"

def _block_of(c: Dict[str, Any]) -> str:
    ctype = (c.get("type") or "include").strip().lower()
    return "exclude" if ctype == "exclude" else "include"

def _include_mode_ok(mode: str, include_passes: List[bool]) -> bool:
    mode = (mode or "all").strip().lower()
    if not include_passes:  # no include criteria in this stage
        return True
    if mode == "all":
        return all(include_passes)
    return any(include_passes)  # "any"

def _fingerprint_for_llm(item: Dict[str, Any], c: Dict[str, Any], trunc: int) -> str:
    targets = (c.get("target") or "abstract").lower().split(",")
    targets = [t.strip() for t in targets if t.strip()]
    if not targets:
        targets = ["abstract"]
    buf = []
    for t in targets:
        txt = item.get(t) or ""
        if not isinstance(txt, str):
            txt = str(txt)
        if trunc and len(txt) > trunc:
            txt = txt[:trunc]
        buf.append(f"{t}::" + txt)
    payload = "||".join(buf)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

# -----------------------------------------------------------------------------
# M0 — deterministic rules (with general multi-target support)
# -----------------------------------------------------------------------------

def _m0_rule_score(item: Dict[str, Any], crit: Dict[str, Any], *, missing_policy: str = "unknown") -> Tuple[float, str]:
    """Return (score_toward_inclusion, matched_reason); score ∈ {0, 0.5, 1}."""
    ctype = (crit.get("type") or "include").strip().lower()
    operator = (crit.get("operator") or "").strip().lower()
    target_raw = (crit.get("target") or "").strip().lower()
    what_list = crit.get("what") or []
    what_list = [normalize_text_for_match(w) for w in what_list]

    targets = [t.strip() for t in target_raw.split(",") if t.strip()]
    if not targets:
        targets = ["abstract"]

    def get_field_text(tgt: str) -> str:
        return normalize_text_for_match(item.get(tgt))

    field_texts = {t: get_field_text(t) for t in targets}
    has_any_field = any(bool(v) for v in field_texts.values())
    has_all_fields = all(bool(v) for v in field_texts.values())

    match: Optional[bool] = None

    if operator == "contains":
        if has_any_field:
            m = False
            for txt in field_texts.values():
                if not txt:
                    continue
                for w in what_list:
                    if w and w in txt:
                        m = True
                        break
                if m:
                    break
            match = m
        else:
            match = None

    elif operator == "regex":
        if has_any_field and what_list:
            try:
                rx = re.compile(what_list[0], flags=re.I)
            except Exception:
                rx = None
            if rx:
                match = any((txt and rx.search(txt) is not None) for txt in field_texts.values())
            else:
                match = None
        else:
            match = None

    elif operator in {"equals", "in_list"}:
        if not has_any_field:
            match = None
        else:
            vals = set(what_list)
            match = any((txt in vals) for txt in field_texts.values() if txt)

    elif operator == "not_in":
        if not has_any_field or not has_all_fields:
            match = None
        else:
            vals = set(what_list)
            match = all((txt not in vals) for txt in field_texts.values() if txt)

    elif operator in {"gte", "lte", "between"}:
        if "year" not in targets:
            match = None
        else:
            try:
                y = int(item.get("year"))
            except Exception:
                y = None
            if y is None:
                match = None
            else:
                try:
                    if operator == "gte":
                        match = (y >= int(what_list[0]))
                    elif operator == "lte":
                        match = (y <= int(what_list[0]))
                    elif operator == "between":
                        lo = int(what_list[0]); hi = int(what_list[1])
                        match = (lo <= y <= hi)
                except Exception:
                    match = None

    elif operator == "llm":
        match = None

    else:
        match = None

    # Convert (match, ctype) to "toward inclusion" score
    if match is True:
        score = 1.0 if ctype == "include" else 0.0
        reason = "rule:match"
    elif match is False:
        score = 0.0 if ctype == "include" else 1.0
        reason = "rule:miss"
    else:
        if missing_policy == "negative" and ctype == "include":
            score = 0.0
        else:
            score = 0.5
        reason = "rule:unknown"

    return float(score), reason

# -----------------------------------------------------------------------------
# M1 — LLM fusion (extractive, conservative)
# -----------------------------------------------------------------------------

def _llm_available() -> bool:
    try:
        import os
        from openai import OpenAI  # type: ignore
        return bool(os.environ.get("OPENAI_API_KEY"))
    except Exception:
        return False

def _truncate(s: str, n: int) -> str:
    if not s:
        return ""
    s = str(s)
    return (s[:n-1] + "…") if len(s) > n else s

def _build_llm_messages_for_criterion(criterion: Dict[str, Any], items: List[Dict[str, Any]], trunc_chars: int) -> List[Dict[str, str]]:
    sys = (
        "You are scoring research items against ONE screening criterion. "
        "For each item, answer with JSON only. Keys per item: "
        "a_id, decision ('meet'|'not_meet'|'uncertain'), confidence (0..1), "
        "field ('title'|'abstract'|'keywords'), quote (exact substring from that field), span [start,end]. "
        "Return a JSON list of objects, nothing else."
    )

    c_pack = {
        "id": criterion["id"],
        "type": criterion["type"],
        "operator": criterion["operator"],
        "target": criterion["target"],
        "what": criterion.get("what", []),
        "how": criterion.get("how", "llm"),
        "label": criterion.get("label", ""),
    }

    payload = []
    for it in items:
        payload.append({
            "a_id": it.get("a_id"),
            "title": _truncate(it.get("title") or "", trunc_chars),
            "abstract": _truncate(it.get("abstract") or "", trunc_chars),
            "keywords": _truncate(it.get("keywords") or "", trunc_chars),
        })

    import json
    user = {"criterion": c_pack, "items": payload}

    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]

def _parse_llm_json_array(txt: str) -> List[Dict[str, Any]]:
    import json
    try:
        data = json.loads(txt)
        if isinstance(data, dict) and "results" in data:
            data = data["results"]
        if isinstance(data, list):
            return data
    except Exception:
        pass
    m = re.search(r"\[[\s\S]*\]", txt)
    if m:
        try:
            import json
            return json.loads(m.group(0))
        except Exception:
            return []
    return []

def run_m1_llm_for_criterion(
    criterion: Dict[str, Any],
    items: List[Dict[str, Any]],
    *,
    model: Optional[str],
    trunc_chars: int = 1500,
    batch_size: int = BATCH_SIZE_DEFAULT,
    log: callable | None = None,
    progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_token: Optional[object] = None,
    crit_idx: Optional[int] = None,
    crit_total: Optional[int] = None,
    block_tag: str = "include",
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Returns (a_id, criterion_id) -> llm_decision_dict; emits progress per batch & respects cancellation."""
    if not model:
        if log: log("[M1-LLM] model=None; skipping M1 for this criterion.\n")
        return {}
    if not _llm_available():
        if log: log("[M1-LLM] OPENAI_API_KEY not visible in environment; skipping M1.\n")
        return {}

    try:
        import os
        from openai import OpenAI  # type: ignore
        api_key = os.environ.get("OPENAI_API_KEY")
        client = OpenAI(api_key=api_key)

        def _estimate_tokens(n_items: int) -> int:
            overhead = 2500
            return overhead + n_items * TOKENS_PER_ITEM_EST

        def _call_once(batch, cur_trunc):
            msgs = _build_llm_messages_for_criterion(criterion, batch, cur_trunc)
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
            "crit_id": criterion["id"], "label": criterion.get("label"),
            "batches_total": total_batches,
        })

        for bi, raw_batch in enumerate(batches, start=1):
            _check_cancel(cancel_token)
            cur_batch = list(raw_batch)
            cur_trunc = int(trunc_chars)

            while _estimate_tokens(len(cur_batch)) > 160_000 and len(cur_batch) > 1:
                new_len = math.ceil(len(cur_batch)/2)
                _emit(progress, {
                    "kind":"l_batch_retry","stage":"L","block":block_tag,
                    "crit_idx":crit_idx,"batch_idx":bi,
                    "note":f"preflight → shrinking batch {len(cur_batch)}→{new_len}"
                })
                cur_batch = cur_batch[:new_len]

            _emit(progress, {"kind":"l_batch","stage":"L","block":block_tag,
                             "crit_idx":crit_idx,"batch_idx":bi,"batch_total":total_batches,"sub":"preparing"})
            _check_cancel(cancel_token)

            attempts = 0
            while True:
                attempts += 1
                _emit(progress, {"kind":"l_batch","stage":"L","block":block_tag,
                                 "crit_idx":crit_idx,"batch_idx":bi,"batch_total":total_batches,"sub":"sending"})
                try:
                    _emit(progress, {"kind":"l_batch","stage":"L","block":block_tag,
                                     "crit_idx":crit_idx,"batch_idx":bi,"batch_total":total_batches,"sub":"waiting"})
                    resp = _call_once(cur_batch, cur_trunc)

                    _check_cancel(cancel_token)

                    _emit(progress, {"kind":"l_batch","stage":"L","block":block_tag,
                                     "crit_idx":crit_idx,"batch_idx":bi,"batch_total":total_batches,"sub":"parsing"})
                    txt = resp.choices[0].message.content or "[]"
                    arr = _parse_llm_json_array(txt)

                    idx_map = {str(it.get("a_id")): it for it in cur_batch}
                    for obj in arr:
                        a_id = str(obj.get("a_id"))
                        decision = (obj.get("decision") or "").strip().lower() or "uncertain"
                        try:
                            confidence = float(obj.get("confidence") or 0.0)
                        except Exception:
                            confidence = 0.0
                        field = (obj.get("field") or "").strip().lower() or None
                        quote = obj.get("quote") or None
                        span = obj.get("span") or None

                        valid_quote = False
                        if field in {"title","abstract","keywords"} and quote:
                            fld_txt = (idx_map.get(a_id) or {}).get(field) or ""
                            valid_quote = (quote in fld_txt)

                        out[(a_id, criterion["id"])] = {
                            "used": True,
                            "decision": decision,
                            "confidence": confidence,
                            "field": field,
                            "quote": quote,
                            "span": span if isinstance(span, list) and len(span) == 2 else None,
                            "valid_quote": bool(valid_quote),
                        }

                    _emit(progress, {"kind":"l_batch","stage":"L","block":block_tag,
                                     "crit_idx":crit_idx,"batch_idx":bi,"batch_total":total_batches,"sub":"batch_done"})
                    break

                except Exception as e:
                    msg = str(e)
                    hit_429 = ("rate_limit" in msg.lower() or "too many" in msg.lower()
                               or "request too large" in msg.lower() or "429" in msg)
                    if not hit_429 or len(cur_batch) == 1:
                        if log: log(f"[M1-LLM] ERROR on {criterion['id']} batch {bi} (attempt {attempts}): {e}\n")
                        _emit(progress, {"kind":"l_batch_retry","stage":"L","block":block_tag,
                                         "crit_idx":crit_idx,"batch_idx":bi,"note":f"error: {msg[:160]}"})
                        break
                    if len(cur_batch) > 2:
                        new_len = max(1, len(cur_batch)//2)
                        if log: log(f"[M1-LLM] {criterion['id']}: 429 → shrinking batch {len(cur_batch)}→{new_len}\n")
                        _emit(progress, {"kind":"l_batch_retry","stage":"L","block":block_tag,
                                         "crit_idx":crit_idx,"batch_idx":bi,"note":f"429 → shrinking batch {len(cur_batch)}→{new_len}"})
                        cur_batch = cur_batch[:new_len]
                    else:
                        new_trunc = max(600, int(cur_trunc * 0.75))
                        if new_trunc == cur_trunc:
                            if log: log(f"[M1-LLM] {criterion['id']}: 429 persists → short backoff 1.0s\n")
                            _emit(progress, {"kind":"l_batch_retry","stage":"L","block":block_tag,
                                             "crit_idx":crit_idx,"batch_idx":bi,"note":"429 persists → short backoff 1.0s"})
                            time.sleep(1.0)
                        else:
                            if log: log(f"[M1-LLM] {criterion['id']}: 429 → reducing trunc {cur_trunc}→{new_trunc}\n")
                            _emit(progress, {"kind":"l_batch_retry","stage":"L","block":block_tag,
                                             "crit_idx":crit_idx,"batch_idx":bi,"note":f"429 → reducing trunc {cur_trunc}→{new_trunc}"})
                            cur_trunc = new_trunc
                    time.sleep(0.5)
                    _check_cancel(cancel_token)

        _emit(progress, {"kind":"l_criterion_done","stage":"L","block":block_tag,
                         "crit_idx":crit_idx})
        return out

    except _Cancelled:
        raise
    except Exception as e:
        if log: log(f"[M1-LLM] ERROR on {criterion['id']}: {e}\n")
        _emit(progress, {"kind":"l_batch_retry","stage":"L","block":block_tag,
                         "crit_idx":crit_idx,"batch_idx":0,"note":f"fatal: {str(e)[:160]}"})
        return {}

# -----------------------------------------------------------------------------
# Fusion logic
# -----------------------------------------------------------------------------

def _fuse_rule_and_llm(ctype: str, rule_score: float, llm_dec: Optional[Dict[str, Any]]) -> float:
    """Conservative fusion."""
    if not llm_dec or not llm_dec.get("used"):
        return float(rule_score)
    if not llm_dec.get("valid_quote"):
        return float(rule_score)

    decision = llm_dec.get("decision")
    if ctype == "include":
        if decision == "meet":
            return 1.0 if rule_score < 1.0 else rule_score
        if decision == "not_meet":
            return 0.0 if rule_score > 0.0 else rule_score
        return float(rule_score)
    else:
        # exclude
        if decision == "meet":
            return 0.0
        if decision == "not_meet":
            return 1.0
        return float(rule_score)

def _label_from_score(s: float, *, pass_thr: float, border_thr: float) -> str:
    if s >= pass_thr:
        return "pass"
    if s >= border_thr:
        return "borderline"
    return "fail"

# -----------------------------------------------------------------------------
# Main entry: Two-Stage pipeline (H → L) with hard-stop and seeded ordering
# -----------------------------------------------------------------------------

def screen_metadata(
    A: List[Dict[str, Any]],
    criteria: List[Dict[str, Any]],
    *,
    pass_thr: float = 0.60,
    border_thr: float = 0.40,
    missing_policy: str = "unknown",   # "unknown" (neutral) | "negative"
    llm_model: Optional[str] = None,
    llm_trunc_chars: int = 1500,
    llm_batch_size: int = BATCH_SIZE_DEFAULT,
    stage_h_include_mode: str = "all",
    stage_l_include_mode: str = "all",
    randomize_within_blocks: bool = True,
    random_seed: Optional[str|int] = None,
    log: callable | None = None,
    hard_stop: bool = True,
    # NEW: structured progress & cancel
    progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_token: Optional[object] = None,
    # NEW: sub-staged execution
    subrun: Optional[Literal["EH","IH","EL","IL"]] = None,
    return_stage_caches: bool = True,
    # NEW: reuse fast-paths: IL←EL, IH←EH, EL←IH
    reuse_from_stage: Optional[Literal["EL","EH","IH"]] = None,
    initial_a_ids: Optional[List[str]] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Two-stage screening with progress events and cancellation support.

    Modes:
      - subrun == "EH": stop after Heuristic EXCLUDES; return {"mode":"EH","caches":{...}}.
      - subrun == "IH": stop after Heuristic INCLUDES; return {"mode":"IH","caches":{...}}.
      - subrun == "EL": stop after LLM EXCLUDES;        return {"mode":"EL","caches":{...}}.
      - subrun == "IL": stop after LLM INCLUDES (pre-final); return {"mode":"IL","caches":{...},"final_results":[...]}.

    Notes:
      - When subrun is provided, return_stage_caches=True is assumed; callers use caches to fill per-stage tabs.
      - The "FULL" or None path preserves the legacy return type (final List[Dict]).
    """
    _check_cancel(cancel_token)

    # Enforce sub-staged execution only (no FULL pipeline fallback)
    _mode = (subrun or "").upper()
    if _mode in ("", "FULL", "NONE"):
        raise ValueError("Full pipeline (H→L) mode has been removed. Use subrun one of: 'EH', 'IH', 'EL', 'IL'.")

    # 0) Normalize / filter active criteria
    active = [c for c in criteria if c.get("enabled", True)]

    # 1) Partition criteria into Stage H vs Stage L, and Exclude vs Include
    H_EXC, H_INC, L_EXC, L_INC = [], [], [], []
    for c in active:
        stage = _stage_of(c)  # 'H' or 'L'
        block = _block_of(c)  # 'exclude' or 'include'
        if stage == "H":
            (H_EXC if block == "exclude" else H_INC).append(c)
        else:
            (L_EXC if block == "exclude" else L_INC).append(c)

    # 2) Order inside each stage: Excludes then Includes; optional seeded shuffle
    seed_used = str(random_seed) if random_seed is not None else f"ts:{int(time.time())}"
    if randomize_within_blocks:
        H_EXC = _seeded_shuffle(H_EXC, seed_used + "|H|EXC")
        H_INC = _seeded_shuffle(H_INC, seed_used + "|H|INC")
        L_EXC = _seeded_shuffle(L_EXC, seed_used + "|L|EXC")
        L_INC = _seeded_shuffle(L_INC, seed_used + "|L|INC")

    # 3) Diagnostics
    if log:
        log(f"[STAGES] H/EXC={len(H_EXC)} H/INC={len(H_INC)}  L/EXC={len(L_EXC)} L/INC={len(L_INC)}\n")
        log(f"[ORDER] seed={seed_used}\n")
        if H_EXC: log("  H/EXC: " + " | ".join(c["id"] for c in H_EXC) + "\n")
        if H_INC: log("  H/INC: " + " | ".join(c["id"] for c in H_INC) + "\n")
        if L_EXC: log("  L/EXC: " + " | ".join(c["id"] for c in L_EXC) + "\n")
        if L_INC: log("  L/INC: " + " | ".join(c["id"] for c in L_INC) + "\n")
        
    # Stage caches (for per-substage tabs)
    stage_caches: Dict[str, Any] = {
        "EH": {},
        "IH": {},
        "EL": {},
        "IL": {},
        "meta": {
            "seed_used": None,
            "stage_h_include_mode": stage_h_include_mode,
            "stage_l_include_mode": stage_l_include_mode,
            "llm_model": llm_model or "gpt-4o-mini",
            "llm_trunc_chars": llm_trunc_chars,
            "llm_batch_size": llm_batch_size,
            "pass_thr": pass_thr,
            "border_thr": border_thr,
            "reused_from": None,  # NEW
        }
    }

    stage_caches["meta"]["seed_used"] = seed_used

    # NEW: detect reuse paths
    reuse_IL_from_EL: bool = (
        ((subrun or "").upper() == "IL")
        and ((reuse_from_stage or "") == "EL")
        and bool(initial_a_ids)
    )
    reuse_IH_from_EH: bool = (
        ((subrun or "").upper() == "IH")
        and ((reuse_from_stage or "") == "EH")
        and bool(initial_a_ids)
    )
    reuse_EL_from_IH: bool = (
        ((subrun or "").upper() == "EL")
        and ((reuse_from_stage or "") == "IH")
        and bool(initial_a_ids)
    )

    if reuse_IL_from_EL:
        stage_caches["meta"]["reused_from"] = "EL"
        if log:
            log(f"[I/L] Reusing E/L survivors: {len(initial_a_ids or [])} item(s); skipping H and L/EXC\n")
        _emit(progress, {"kind":"reuse_start","stage":"L","from":"EL","count":len(initial_a_ids or []), "ts":time.time()})

    if reuse_IH_from_EH:
        stage_caches["meta"]["reused_from"] = "EH"
        if log:
            log(f"[I/H] Reusing E/H survivors: {len(initial_a_ids or [])} item(s); skipping H/EXC\n")
        _emit(progress, {"kind":"reuse_start","stage":"H","from":"EH","count":len(initial_a_ids or []), "ts":time.time()})

    if reuse_EL_from_IH:
        stage_caches["meta"]["reused_from"] = "IH"
        if log:
            log(f"[E/L] Reusing I/H survivors: {len(initial_a_ids or [])} item(s); skipping Stage H\n")
        _emit(progress, {"kind":"reuse_start","stage":"L","from":"IH","count":len(initial_a_ids or []), "ts":time.time()})

    # Dropped-at-EXCLUDE logs for the E/H and E/L tabs
    _eh_dropped: List[Dict[str, Any]] = []
    _el_dropped: List[Dict[str, Any]] = []
    
    # NEW: fast lookup sets so drops can't be resurrected later
    _eh_dropped_ids: set[str] = set()
    _el_dropped_ids: set[str] = set()

    # 4) Prepare per-item audit structure
    results_stub: Dict[str, Dict[str, Any]] = {}
    for item in A:
        a_id = str(item.get("a_id"))
        results_stub[a_id] = {
            "a_id": a_id,
            "title": item.get("title") or "",
            "per_criterion": [],
            "hard_stop_violation": None,
            "h_pass": True,
            "l_pass": True,
            "stage_h_include_mode": "all" if (stage_h_include_mode or "all").lower()=="all" else "any",
            "stage_l_include_mode": "all" if (stage_l_include_mode or "all").lower()=="all" else "any",
            "random_seed_used": seed_used,
        }

    # ---------- Stage H ----------
    def run_block(items: List[Dict[str, Any]], block_criteria: List[Dict[str, Any]], stage_tag: str, block_tag: str) -> Tuple[List[Dict[str, Any]], Dict[str, List[bool]]]:
        """Run one block (EXC or INC) of Stage H over a working item set.
           Returns survivors and per-item list of include flags."""
        survivors = list(items)
        passes: Dict[str, List[bool]] = {}  # item -> list[bool] for include criteria
        order_index = 0
        crit_total = len(block_criteria)

        for i, c in enumerate(block_criteria, start=1):
            _check_cancel(cancel_token)
            order_index += 1
            cid = c["id"]
            ctype = (c.get("type") or "include").strip().lower()
            thr = float(c.get("threshold") or 0.60)
            w = float(c.get("weight") or 1.0)

            if stage_tag == "H":
                _emit(progress, {
                    "kind": "h_criterion_start", "stage": "H", "block": block_tag,
                    "crit_idx": i, "crit_total": crit_total,
                    "crit_id": cid,
                    "operator": c.get("operator"),
                    "target": c.get("target"),
                    "label": c.get("label")
                })

            new_survivors = []
            for it in survivors:
                a_id = str(it.get("a_id"))
                rscore, _reason = _m0_rule_score(it, c, missing_policy=missing_policy)

                entry = {
                    "id": cid,
                    "label": c.get("label"),
                    "type": ctype,
                    "weight": w,
                    "threshold": thr,
                    "operator": c.get("operator"),
                    "target": c.get("target"),
                    "what": c.get("what"),
                    "how": (c.get("how") or "heuristic"),
                    "rule_score": float(rscore),
                    "llm": {"used": False},
                    "fused_score": float(rscore),
                    "stage": stage_tag,
                    "block": block_tag,
                    "order_index": order_index,
                }
                results_stub[a_id]["per_criterion"].append(entry)

                # Hard-stop applies only to INCLUDE block
                if block_tag == "include" and hard_stop and float(rscore) < thr:
                    if results_stub[a_id]["hard_stop_violation"] is None:
                        results_stub[a_id]["hard_stop_violation"] = {
                            "criterion_id": cid,
                            "criterion_label": c.get("label"),
                            "fused": float(rscore),
                            "threshold": thr,
                            "stage": stage_tag,
                            "block": block_tag,
                        }
                    # drop (do not append)
                    continue

                if block_tag == "exclude":
                    # EXCLUDE behavior: drop ONLY when the rule MATCHES the exclusion
                    # (_m0_rule_score returns reason: "rule:match" | "rule:miss" | "rule:unknown")
                    if _reason == "rule:match":
                        entry["dropped_here"] = True
                        _eh_dropped.append({
                            "a_id": a_id,
                            "title": results_stub[a_id]["title"],
                            "criterion_id": cid,
                            "criterion_label": c.get("label"),
                            "operator": c.get("operator"),
                            "target": c.get("target"),
                            "threshold": thr,
                            "rule_score": float(rscore),
                            "stage": stage_tag,
                            "block": block_tag,
                            "order_index": order_index,
                        })
                        _eh_dropped_ids.add(a_id)
                        results_stub[a_id]["h_pass"] = False
                        continue
                    else:
                        # keep non-matches and unknowns for later blocks
                        new_survivors.append(it)
                else:
                    # INCLUDE behavior: record flag and keep item for later criteria
                    passes.setdefault(a_id, []).append(float(rscore) >= thr)
                    new_survivors.append(it)
            survivors = new_survivors

            if stage_tag == "H":
                _emit(progress, {
                    "kind": "h_criterion_done", "stage": "H", "block": block_tag,
                    "crit_idx": i
                })

        return survivors, passes

    # ---------- Stage H (with reuse fast-paths) ----------
    if reuse_IH_from_EH:
        # Start from provided EH survivors; skip H/EXC
        initial_id_set = {str(x) for x in (initial_a_ids or [])}
        working_items = [it for it in A if str(it.get("a_id")) in initial_id_set]
        EH_survivors_ids = [str(it.get("a_id")) for it in working_items]
        if log: log(f"[H] (reused) Skipped EXCLUDES; using {len(working_items)} EH survivors for H/INC\n")

        # Run ONLY H/INC
        working_items, h_include_flags = run_block(working_items, H_INC, "H", "include")

        # Determine H_PASS per item (only over the reused set)
        h_pass_map: Dict[str, bool] = {}
        for it in A:
            a_id = str(it.get("a_id"))
            if a_id not in initial_id_set:
                h_pass_map[a_id] = False
                continue
            if results_stub[a_id]["hard_stop_violation"] and results_stub[a_id]["hard_stop_violation"]["stage"] == "H":
                h_pass_map[a_id] = False
                continue
            flags = h_include_flags.get(a_id, [])
            h_pass_map[a_id] = _include_mode_ok(stage_h_include_mode, flags)

        H_survivors = [it for it in working_items if h_pass_map.get(str(it.get("a_id")), False)]

        for it in A:
            a_id = str(it.get("a_id"))
            results_stub[a_id]["h_pass"] = bool(h_pass_map.get(a_id, False))

        if log: log(f"[H] After INCLUDES (mode={stage_h_include_mode}): {len(H_survivors)} survivors proceed to L\n")

        # Populate caches for tabs (EH is synthetic here; we only know the survivor IDs)
        stage_caches["EH"] = {
            "survivors_after_EH_ids": EH_survivors_ids,
            "dropped_records": _eh_dropped,
            "criteria_counts": {"H_EXC": len(H_EXC)},
        }
        stage_caches["IH"] = {
            "survivors_after_IH_ids": [str(it.get("a_id")) for it in H_survivors],
            "h_pass_map": h_pass_map,
            "include_flags_map": {k: list(v) for k, v in (h_include_flags or {}).items()},
            "criteria_counts": {"H_EXC": len(H_EXC), "H_INC": len(H_INC)},
        }

        if (subrun or "").upper() == "IH":
            return {"mode": "IH", "caches": stage_caches} if return_stage_caches else {"mode":"IH"}

    elif not reuse_IL_from_EL:
        working_items = list(A)
        working_items, _ = run_block(working_items, H_EXC, "H", "exclude")
        EH_survivors_ids = [str(it.get("a_id")) for it in working_items]
        if log: log(f"[H] After EXCLUDES: {len(working_items)} survivors\n")

        if (subrun or "").upper() == "EH":
            stage_caches["EH"] = {
                "survivors_after_EH_ids": [str(it.get("a_id")) for it in working_items],
                "dropped_records": _eh_dropped,
                "criteria_counts": {"H_EXC": len(H_EXC)},
            }
            return {"mode": "EH", "caches": stage_caches} if return_stage_caches else {"mode":"EH"}

        working_items, h_include_flags = run_block(working_items, H_INC, "H", "include")

        # Determine H_PASS per item
        h_pass_map: Dict[str, bool] = {}
        for it in A:
            a_id = str(it.get("a_id"))
            if results_stub[a_id]["hard_stop_violation"] and results_stub[a_id]["hard_stop_violation"]["stage"] == "H":
                h_pass_map[a_id] = False
                continue
            flags = h_include_flags.get(a_id, [])
            h_pass_map[a_id] = _include_mode_ok(stage_h_include_mode, flags)

        H_survivors = [it for it in working_items if h_pass_map.get(str(it.get("a_id")), True)]
        for aid in _eh_dropped_ids:
            h_pass_map[aid] = False
        for it in A:
            a_id = str(it.get("a_id"))
            results_stub[a_id]["h_pass"] = bool(h_pass_map.get(a_id, True))

        if log: log(f"[H] After INCLUDES (mode={stage_h_include_mode}): {len(H_survivors)} survivors proceed to L\n")
        stage_caches["IH"] = {
            "survivors_after_IH_ids": [str(it.get("a_id")) for it in H_survivors],
            "h_pass_map": h_pass_map,
            "include_flags_map": {k: list(v) for k, v in (h_include_flags or {}).items()},
            "criteria_counts": {"H_EXC": len(H_EXC), "H_INC": len(H_INC)},
        }
        if (subrun or "").upper() == "IH":
            stage_caches["EH"] = {
                "survivors_after_EH_ids": EH_survivors_ids,
                "dropped_records": _eh_dropped,
                "criteria_counts": {"H_EXC": len(H_EXC)},
            }
            return {"mode": "IH", "caches": stage_caches} if return_stage_caches else {"mode":"IH"}

    else:
        # Synthetic H pass for IL←EL reuse: mark only provided IDs as H survivors
        initial_id_set = {str(x) for x in (initial_a_ids or [])}
        EH_survivors_ids = list(initial_id_set)
        H_survivors = [it for it in A if str(it.get("a_id")) in initial_id_set]

        for it in A:
            a_id = str(it.get("a_id"))
            results_stub[a_id]["h_pass"] = (a_id in initial_id_set)

        stage_caches["EH"] = {
            "survivors_after_EH_ids": EH_survivors_ids,
            "dropped_records": _eh_dropped,
            "criteria_counts": {"H_EXC": len(H_EXC)},
        }
        stage_caches["IH"] = {
            "survivors_after_IH_ids": EH_survivors_ids,
            "h_pass_map": {aid: True for aid in EH_survivors_ids},
            "include_flags_map": {},
            "criteria_counts": {"H_EXC": len(H_EXC), "H_INC": len(H_INC)},
        }
    _check_cancel(cancel_token)

    # ---------- Stage L ----------
    # Keep the survivor IDs right AFTER L/EXC so the E/L tab never shows post-include data.
    _el_survivors_ids_snapshot: List[str] = []
    
    if not (L_EXC or L_INC):
        if log: log("[L] No LLM criteria. Skipping Stage L.\n")
        final_results: List[Dict[str, Any]] = []
        for it in A:
            a_id = str(it.get("a_id"))
            h_pass = results_stub[a_id]["h_pass"]
            l_pass = True
            results_stub[a_id]["l_pass"] = l_pass
            per_c = results_stub[a_id]["per_criterion"]
            sum_w = sum(float(e.get("weight", 1.0)) for e in per_c)
            sum_s = sum(float(e.get("fused_score", e.get("rule_score", 0.5))) * float(e.get("weight", 1.0)) for e in per_c)
            agg = (sum_s / sum_w) if sum_w > 0 else 0.0
            label = "pass" if (h_pass and l_pass) else "fail"
            if label == "pass":
                label = "pass" if _label_from_score(agg, pass_thr=pass_thr, border_thr=border_thr) in {"pass","borderline"} else "fail"
            final_results.append({
                "a_id": a_id,
                "title": results_stub[a_id]["title"],
                "score": float(agg),
                "label": label if h_pass else "fail",
                "per_criterion": per_c,
                "hard_stop_violation": results_stub[a_id]["hard_stop_violation"],
                "h_pass": h_pass,
                "l_pass": l_pass,
                "stage_h_include_mode": results_stub[a_id]["stage_h_include_mode"],
                "stage_l_include_mode": results_stub[a_id]["stage_l_include_mode"],
                "random_seed_used": results_stub[a_id]["random_seed_used"],
            })
        return final_results

    llm_cache: Dict[Tuple[str, str, str], Dict[str, Any]] = {}  # (cid, a_id, fp) -> llm_decision

    def run_block_L(items: List[Dict[str, Any]], block_criteria: List[Dict[str, Any]], block_tag: str) -> Tuple[List[Dict[str, Any]], Dict[str, List[bool]]]:
        survivors = list(items)
        passes: Dict[str, List[bool]] = {}
        order_index = 0
        crit_total = len(block_criteria)

        for ci, c in enumerate(block_criteria, start=1):
            _check_cancel(cancel_token)
            order_index += 1
            cid = c["id"]
            ctype = (c.get("type") or "include").strip().lower()
            thr = float(c.get("threshold") or 0.60)
            w = float(c.get("weight") or 1.0)

            # Build LLM queue (respect cache)
            queue_items: List[Dict[str, Any]] = []
            fps: Dict[str, str] = {}
            for it in survivors:
                a_id = str(it.get("a_id"))
                fp = _fingerprint_for_llm(it, c, llm_trunc_chars)
                fps[a_id] = fp
                key = (cid, a_id, fp)
                if key not in llm_cache:
                    queue_items.append(it)

            if queue_items:
                llm_model_local = llm_model or "gpt-4o-mini"
                if not llm_model and log:
                    log("[M1-LLM] No model provided; using default: gpt-4o-mini\n")

                if log: log(f"[L/LLM] {cid}: queued {len(queue_items)} item(s); batching by {llm_batch_size}\n")

                m = run_m1_llm_for_criterion(
                    c, queue_items,
                    model=llm_model_local,
                    trunc_chars=llm_trunc_chars,
                    batch_size=llm_batch_size,
                    log=log,
                    progress=progress,
                    cancel_token=cancel_token,
                    crit_idx=ci, crit_total=crit_total,
                    block_tag=block_tag,
                )
                for it in queue_items:
                    a_id = str(it.get("a_id"))
                    dec = m.get((a_id, cid))
                    if dec:
                        llm_cache[(cid, a_id, fps[a_id])] = dec
            else:
                _emit(progress, {
                    "kind":"l_criterion_start","stage":"L","block":block_tag,
                    "crit_idx":ci,"crit_total":crit_total,"crit_id":cid,"label":c.get("label"),
                    "batches_total":0
                })
                _emit(progress, {"kind":"l_criterion_done","stage":"L","block":block_tag,"crit_idx":ci})

            _check_cancel(cancel_token)

            # Apply decisions
            new_survivors = []
            for it in survivors:
                a_id = str(it.get("a_id"))
                rscore, rule_reason = _m0_rule_score(it, c, missing_policy=missing_policy)
                dec = llm_cache.get((cid, a_id, fps[a_id]), None)

                fused = _fuse_rule_and_llm(ctype, float(rscore), dec)
                entry = {
                    "id": cid,
                    "label": c.get("label"),
                    "type": ctype,
                    "weight": w,
                    "threshold": thr,
                    "operator": c.get("operator"),
                    "target": c.get("target"),
                    "what": c.get("what"),
                    "how": (c.get("how") or "llm"),
                    "rule_score": float(rscore),
                    "llm": dec or {"used": False},
                    "fused_score": float(fused),
                    "stage": "L",
                    "block": block_tag,
                    "order_index": order_index,
                }
                results_stub[a_id]["per_criterion"].append(entry)

                # B — hard-stop applies ONLY to INCLUDE block in Stage L
                if block_tag == "include" and hard_stop and float(fused) < thr:
                    if results_stub[a_id]["hard_stop_violation"] is None:
                        results_stub[a_id]["hard_stop_violation"] = {
                            "criterion_id": cid,
                            "criterion_label": c.get("label"),
                            "fused": float(fused),
                            "threshold": thr,
                            "stage": "L",
                            "block": block_tag,
                        }
                    continue  # drop

                if block_tag == "exclude":
                    # Decide "meets exclusion?" explicitly (NOT by fused toward-inclusion score).
                    meets_exclusion = False
                
                    # 1) Deterministic operators: drop ONLY on exact rule match.
                    if (c.get("operator") or "").strip().lower() != "llm":
                        meets_exclusion = (rule_reason == "rule:match")
                
                    # 2) LLM operator: require model to assert the exclusion WITH extractive evidence,
                    #    and confidence must meet the criterion threshold.
                    if (c.get("operator") or "").strip().lower() == "llm" and dec and dec.get("used"):
                        if dec.get("valid_quote") and (dec.get("decision") == "meet"):
                            try:
                                meets_exclusion = float(dec.get("confidence") or 0.0) >= float(thr)
                            except Exception:
                                # Be conservative if malformed confidence
                                meets_exclusion = True
                
                    if meets_exclusion:
                        entry["dropped_here"] = True
                        _el_dropped.append({
                            "a_id": a_id,
                            "title": results_stub[a_id]["title"],
                            "criterion_id": cid,
                            "criterion_label": c.get("label"),
                            "operator": c.get("operator"),
                            "target": c.get("target"),
                            "threshold": thr,
                            "rule_score": float(rscore),
                            "llm_decision": (dec or {}),
                            "fused_score": float(fused),
                            "stage": "L",
                            "block": block_tag,
                            "order_index": order_index,
                        })
                        _el_dropped_ids.add(a_id)
                        results_stub[a_id]["l_pass"] = False
                        continue
                    else:
                        new_survivors.append(it)

                else:
                    # INCLUDE in L: record pass flag and keep item for later criteria
                    passes.setdefault(a_id, []).append(float(fused) >= thr)
                    new_survivors.append(it)

            survivors = new_survivors

        return survivors, passes

    # ---------- Stage L ----------
    if reuse_EL_from_IH:
        # Start Stage L on provided I/H survivors; skip Stage H entirely
        initial_id_set = {str(x) for x in (initial_a_ids or [])}
        working_items = [it for it in A if str(it.get("a_id")) in initial_id_set]
        if log: log(f"[L] (reused) Starting L/EXC with {len(working_items)} IH survivors (skipped Stage H)\n")

        # Run ONLY L/EXC (E/L subrun)
        working_items, _ = run_block_L(working_items, L_EXC, "exclude")
        if log: log(f"[L] After EXCLUDES: {len(working_items)} survivors\n")

        # Populate caches and return immediately (E/L preview)
        stage_caches["EH"] = stage_caches.get("EH") or {
            "survivors_after_EH_ids": list(initial_id_set),  # best-effort synthetic EH cache
            "dropped_records": _eh_dropped,
            "criteria_counts": {"H_EXC": len(H_EXC)},
        }
        stage_caches["IH"] = stage_caches.get("IH") or {
            "survivors_after_IH_ids": list(initial_id_set),
            "h_pass_map": {aid: True for aid in initial_id_set},  # synthetic map
            "include_flags_map": {},
            "criteria_counts": {"H_EXC": len(H_EXC), "H_INC": len(H_INC)},
        }
        _el_survivors_ids_snapshot = [str(it.get("a_id")) for it in working_items]
        stage_caches["EL"] = {
            "survivors_after_EL_ids": list(_el_survivors_ids_snapshot),
            "dropped_records": _el_dropped,
            "criteria_counts": {"L_EXC": len(L_EXC)},
        }
        return {"mode": "EL", "caches": stage_caches} if return_stage_caches else {"mode":"EL"}

    elif not reuse_IL_from_EL:
        working_items = list(H_survivors)
        working_items, _ = run_block_L(working_items, L_EXC, "exclude")
        _el_survivors_ids_snapshot = [str(it.get("a_id")) for it in working_items]
        if log: log(f"[L] After EXCLUDES: {len(working_items)} survivors\n")
        if (subrun or "").upper() == "EL":
            stage_caches["EH"] = stage_caches.get("EH") or {
                "survivors_after_EH_ids": EH_survivors_ids,
                "dropped_records": _eh_dropped,
                "criteria_counts": {"H_EXC": len(H_EXC)},
            }
            stage_caches["IH"] = stage_caches.get("IH") or {
                "survivors_after_IH_ids": [str(it.get("a_id")) for it in H_survivors],
                "h_pass_map": {},
                "include_flags_map": {},
                "criteria_counts": {"H_EXC": len(H_EXC), "H_INC": len(H_INC)},
            }
            stage_caches["EL"] = {
                "survivors_after_EL_ids": [str(it.get("a_id")) for it in working_items],
                "dropped_records": _el_dropped,
                "criteria_counts": {"L_EXC": len(L_EXC)},
            }
            return {"mode": "EL", "caches": stage_caches} if return_stage_caches else {"mode":"EL"}
    else:
        # IL←EL reuse path: start Stage L directly at INCLUDE, with EL survivors = provided IDs
        working_items = [it for it in A if str(it.get("a_id")) in (initial_a_ids or [])]
        stage_caches["EL"] = {
            "survivors_after_EL_ids": [str(it.get("a_id")) for it in working_items],
            "dropped_records": _el_dropped,
            "criteria_counts": {"L_EXC": len(L_EXC)},
        }
        if log: log(f"[L] (reused) After EXCLUDES: {len(working_items)} survivors (skipped L/EXC)\n")
    _check_cancel(cancel_token)
    working_items, l_include_flags = run_block_L(working_items, L_INC, "include")
    _check_cancel(cancel_token)
    if log:
        # Harmonize with H logs and make I/L runs show a clear summary line
        log(f"[L] After INCLUDES (mode={stage_l_include_mode}): {len(working_items)} survivors\n")

    # Determine L_PASS per item (only those that reached L)
    l_pass_map: Dict[str, bool] = {}
    for it in A:
        a_id = str(it.get("a_id"))
    
        # Force-fail anything dropped at E/L (no resurrection later).
        if a_id in _el_dropped_ids:
            l_pass_map[a_id] = False
            continue
    
        if not results_stub[a_id]["h_pass"]:
            l_pass_map[a_id] = False
            continue
        if results_stub[a_id]["hard_stop_violation"] and results_stub[a_id]["hard_stop_violation"]["stage"] == "L":
            l_pass_map[a_id] = False
            continue
    
        flags = l_include_flags.get(a_id, [])
        l_pass_map[a_id] = _include_mode_ok(stage_l_include_mode, flags)
    for it in A:
        a_id = str(it.get("a_id"))
        results_stub[a_id]["l_pass"] = bool(l_pass_map.get(a_id, True))

    # Stage-L cache for I/L tab (pre-final aggregation)
    stage_caches["EL"] = stage_caches.get("EL") or {
        # Use the snapshot taken right after L/EXC (or an empty list if no L/EXC ran)
        "survivors_after_EL_ids": list(_el_survivors_ids_snapshot),
        "dropped_records": _el_dropped,
        "criteria_counts": {"L_EXC": len(L_EXC)},
    }
    
    stage_caches["IL"] = {
        "l_pass_map": l_pass_map,
        "include_flags_map": {k: list(v) for k, v in (l_include_flags or {}).items()},
        "criteria_counts": {"L_EXC": len(L_EXC), "L_INC": len(L_INC)},
    }

    if (subrun or "").upper() == "IL":
        # Build final results now (same as FULL) to allow the Final tab to render
        final_results_preview: List[Dict[str, Any]] = []
        for it in A:
            a_id = str(it.get("a_id"))
            per_c = results_stub[a_id]["per_criterion"]
            sum_w = sum(float(e.get("weight", 1.0)) for e in per_c)
            sum_s = sum(float(e.get("fused_score", e.get("rule_score", 0.5))) * float(e.get("weight", 1.0)) for e in per_c)
            agg = (sum_s / sum_w) if sum_w > 0 else 0.0

            h_pass = results_stub[a_id]["h_pass"]
            l_pass = results_stub[a_id]["l_pass"]
            stage_gate_label = "pass" if (h_pass and l_pass) else "fail"

            label = stage_gate_label
            if stage_gate_label == "pass":
                lbl = _label_from_score(agg, pass_thr=pass_thr, border_thr=border_thr)
                label = "pass" if lbl in {"pass", "borderline"} else "fail"

            final_results_preview.append({
                "a_id": a_id,
                "title": results_stub[a_id]["title"],
                "score": float(agg),
                "label": label if (h_pass and l_pass) else "fail",
                "per_criterion": per_c,
                "hard_stop_violation": results_stub[a_id]["hard_stop_violation"],
                "h_pass": h_pass,
                "l_pass": l_pass,
                "stage_h_include_mode": results_stub[a_id]["stage_h_include_mode"],
                "stage_l_include_mode": results_stub[a_id]["stage_l_include_mode"],
                "random_seed_used": results_stub[a_id]["random_seed_used"],
            })

        return {"mode": "IL", "caches": stage_caches, "final_results": final_results_preview}

    # Final aggregation
    # No full-pipeline aggregation here.
    # Callers must use subrun="IL" to receive {"final_results": [...]} along with caches.
    raise ValueError("Full pipeline (H→L) aggregation has been removed. Use subrun='IL' to obtain final_results.")
