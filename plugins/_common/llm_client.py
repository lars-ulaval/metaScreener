
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
plugins/_common/llm_client.py — Shared LLM-driving infrastructure.

This module holds the byte-identical helpers that EL (Plugin 06) and IL
(Plugin 07) used to duplicate. Each plugin's screening orchestrator
(``run_el_screen`` / ``run_il_screen``) stays in its own ``plugin.py``;
only the helper machinery is shared here.

Two of the helpers required minor signature changes to support being
shared across stages with different per-stage constants:

* ``_cache_key`` now takes ``prompt_version`` as a keyword parameter.
  EL/IL plugins each expose their own ``_cache_key`` curry that bakes
  in their stage's ``PROMPT_VERSION`` so call sites and the existing
  evidence-gating tests remain unchanged.

* ``run_m1_llm_for_criterion`` now takes ``stage`` as a keyword
  parameter. The stage label is used only for log prefixes
  (``[EL-LLM]`` / ``[IL-LLM]``) and the courtesy ``"stage"`` field on
  emitted progress events; no semantic logic depends on its value.

All other functions are byte-identical to the inlined copies that
previously lived in ``plugins/06_el/plugin.py`` and
``plugins/07_il/plugin.py``.
"""
from __future__ import annotations

import json
import os
import re
import time
from hashlib import sha256
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


# --------------------------- small utilities ----------------------------------

def _safe_str(x: Any) -> str:
    return "" if x is None else str(x)

def _sha_text(s: str) -> str:
    return sha256(s.encode("utf-8", errors="ignore")).hexdigest()

def _normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _quote_in_text(quote: str, text: str) -> bool:
    """
    Quote validity check:
      - exact substring OR
      - whitespace-normalized substring (prevents false invalid due to newlines/multiple spaces)
    """
    if not quote or not text:
        return False
    if quote in text:
        return True
    qn = _normalize_space(quote)
    tn = _normalize_space(text)
    return bool(qn) and (qn in tn)

def _has_openai_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())

def chunked(seq: Sequence[Any], n: int):
    n = max(1, int(n))
    for i in range(0, len(seq), n):
        yield seq[i:i+n]


# --------------------------- LLM utilities ------------------------------------

def _parse_llm_json_array(text: str) -> List[Dict[str, Any]]:
    """
    Robust parse of a JSON array. Accepts:
      - pure JSON list
      - fenced code block
      - extra text before/after (extract first [...] block)
    """
    t = (text or "").strip()
    # strip fenced code blocks
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()

    # direct
    try:
        val = json.loads(t)
        if isinstance(val, list):
            return [v for v in val if isinstance(v, dict)]
    except Exception:
        pass

    # extract first bracketed list
    m = re.search(r"\[\s*\{.*\}\s*\]", t, flags=re.S)
    if m:
        try:
            val = json.loads(m.group(0))
            if isinstance(val, list):
                return [v for v in val if isinstance(v, dict)]
        except Exception:
            pass
    return []

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
        "type": criterion.get("type", "exclude"),
        "operator": criterion.get("operator", "llm"),
        "target": criterion.get("target", "abstract"),
        "what": criterion.get("what", []),
        "how": criterion.get("how", "llm"),
        "label": criterion.get("label", ""),
        "threshold": criterion.get("threshold", 0.6),
    }

    def trunc(s: str) -> str:
        s = s or ""
        if trunc_chars and len(s) > trunc_chars:
            return s[:trunc_chars]
        return s

    items_pack = []
    for it in items:
        items_pack.append({
            "a_id": it.get("a_id", ""),
            "title": trunc(_safe_str(it.get("title",""))),
            "abstract": trunc(_safe_str(it.get("abstract",""))),
            "keywords": trunc(_safe_str(it.get("keywords",""))),
        })

    user = json.dumps({"criterion": c_pack, "items": items_pack}, ensure_ascii=False)
    return [{"role":"system","content":sys}, {"role":"user","content":user}]


def run_m1_llm_for_criterion(
    criterion: Dict[str, Any],
    items: List[Dict[str, Any]],
    *,
    stage: str,
    model: Optional[str],
    trunc_chars: int,
    batch_size: int,
    log: Optional[Callable[[str], None]] = None,
    progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_token: Optional[object] = None,
    crit_idx: Optional[int] = None,
    crit_total: Optional[int] = None,
    block_tag: str = "exclude",
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """
    Returns (a_id, criterion_id) -> llm_decision_dict (used/decision/confidence/field/quote/span/valid_quote).
    Implements adaptive batching on errors (429/oversize).

    The ``stage`` keyword (e.g. ``"EL"`` or ``"IL"``) is used for log prefixes
    and the courtesy ``"stage"`` field on emitted progress events. No semantic
    logic depends on its value.
    """
    log_prefix = f"[{stage}-LLM]"
    if not model:
        if log: log(f"{log_prefix} model=None; skipping.\n")
        return {}
    if not _has_openai_key():
        if log: log(f"{log_prefix} OPENAI_API_KEY not visible in environment; skipping.\n")
        return {}

    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    except Exception as e:
        if log: log(f"{log_prefix} OpenAI client import/init failed: {e}\n")
        return {}

    def _check_cancel():
        if cancel_token is not None and bool(getattr(cancel_token, "cancelled", False)):
            raise RuntimeError("Cancelled")
        if cancel_token is not None and bool(getattr(cancel_token, "is_set", lambda: False)()):
            raise RuntimeError("Cancelled")

    def _call_once(batch: List[Dict[str, Any]], cur_trunc: int):
        msgs = _build_llm_messages_for_criterion(criterion, batch, cur_trunc)
        return client.chat.completions.create(
            model=model,
            messages=msgs,
            temperature=0.0,
        )

    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    cid = criterion["id"]
    
    # Build a_id -> field texts map (used for quote validation + ignoring unknown a_id)
    idx_map: Dict[str, Dict[str, str]] = {}
    for it in items:
        a_id = _safe_str(it.get("a_id", "")).strip()
        if not a_id:
            continue
        idx_map[a_id] = {
            "title": _safe_str(it.get("title", "")),
            "abstract": _safe_str(it.get("abstract", "")),
            "keywords": _safe_str(it.get("keywords", "")),
        }

    # initial batches
    batches: List[List[Dict[str, Any]]] = [list(b) for b in chunked(items, max(1, int(batch_size)))]

    bi = 0
    while bi < len(batches):
        _check_cancel()

        cur_batch = list(batches[bi])
        cur_trunc = int(trunc_chars)
        attempts = 0

        while True:
            attempts += 1
            try:
                total_batches = len(batches)
                batch_num = bi + 1

                if progress:
                    progress({
                        "kind": "l_batch",
                        "stage": stage,
                        "block": block_tag,
                        "crit_idx": crit_idx,
                        "crit_total": crit_total,
                        "batch_idx": batch_num,
                        "batch_total": total_batches,
                        "sub": "sending",
                    })

                resp = _call_once(cur_batch, cur_trunc)
                _check_cancel()

                if progress:
                    progress({
                        "kind": "l_batch",
                        "stage": stage,
                        "block": block_tag,
                        "crit_idx": crit_idx,
                        "crit_total": crit_total,
                        "batch_idx": batch_num,
                        "batch_total": total_batches,
                        "sub": "parsing",
                    })

                txt = (resp.choices[0].message.content or "[]")
                arr = _parse_llm_json_array(txt)

                # parse response objects
                for obj in arr:
                    a_id = _safe_str(obj.get("a_id", "")).strip()
                    if not a_id or a_id not in idx_map:
                        continue

                    decision = _safe_str(obj.get("decision", "uncertain")).strip()
                    if decision not in {"meet", "not_meet", "uncertain"}:
                        decision = "uncertain"

                    try:
                        confidence = float(obj.get("confidence", 0.0))
                    except Exception:
                        confidence = 0.0
                    confidence = min(1.0, max(0.0, confidence))

                    field = _safe_str(obj.get("field", "")).strip().lower()
                    if field not in {"title", "abstract", "keywords"}:
                        field = "abstract"

                    quote = _safe_str(obj.get("quote", ""))
                    span = obj.get("span", None)
                    if not (isinstance(span, list) and len(span) == 2 and all(isinstance(x, int) for x in span)):
                        span = None

                    fld_txt = (idx_map.get(a_id) or {}).get(field) or ""
                    fld_txt = (idx_map.get(a_id) or {}).get(field) or ""
                    # Validate against the SAME truncated text that was sent to the model for this call
                    fld_txt_prompt = (fld_txt[:cur_trunc] if cur_trunc and len(fld_txt) > cur_trunc else fld_txt)
                    valid_quote = _quote_in_text(quote, fld_txt_prompt)

                    out[(a_id, cid)] = {
                        "used": True,
                        "decision": decision,
                        "confidence": confidence,
                        "field": field,
                        "quote": quote,
                        "span": span,
                        "valid_quote": valid_quote,
                    }

                # ensure every item in THIS cur_batch has an entry
                for it in cur_batch:
                    a_id = _safe_str(it.get("a_id", "")).strip()
                    if not a_id:
                        continue
                    if (a_id, cid) not in out:
                        out[(a_id, cid)] = {
                            "used": False,
                            "decision": "uncertain",
                            "confidence": 0.0,
                            "field": "abstract",
                            "quote": "",
                            "span": None,
                            "valid_quote": False,
                        }

                if progress:
                    progress({
                        "kind": "l_batch",
                        "stage": stage,
                        "block": block_tag,
                        "crit_idx": crit_idx,
                        "crit_total": crit_total,
                        "batch_idx": batch_num,
                        "batch_total": total_batches,
                        "sub": "batch_done",
                    })

                break  # batch success

            except Exception as e:
                msg = str(e).lower()
                is_rate = ("429" in msg) or ("too many requests" in msg) or ("rate" in msg and "limit" in msg)
                is_big = ("too large" in msg) or ("context" in msg and "length" in msg) or ("max tokens" in msg)

                # split WITHOUT losing items (requeue remainder right after this batch)
                if (is_rate or is_big) and len(cur_batch) > 1:
                    new_n = max(1, len(cur_batch) // 2)
                    remainder = cur_batch[new_n:]
                    cur_batch = cur_batch[:new_n]

                    # replace current batch, insert remainder as next batch
                    batches[bi] = cur_batch
                    if remainder:
                        batches.insert(bi + 1, remainder)

                    if log:
                        log(
                            f"{log_prefix} batch {bi+1}/{len(batches)} error ({e}); "
                            f"split into {len(cur_batch)} + {len(remainder)}\n"
                        )

                    time.sleep(min(4.0, 0.4 * attempts))
                    continue

                # reduce truncation if still big/rate and trunc is high
                if (is_rate or is_big) and cur_trunc > 600:
                    new_trunc = max(600, int(cur_trunc * 0.75))
                    if log:
                        log(f"{log_prefix} batch {bi+1}/{len(batches)} error ({e}); trunc {cur_trunc} -> {new_trunc}\n")
                    cur_trunc = new_trunc
                    time.sleep(min(4.0, 0.4 * attempts))
                    continue

                # final failure for this batch: mark all items in THIS cur_batch as uncertain
                if log:
                    log(f"{log_prefix} batch {bi+1}/{len(batches)} failed: {e}\n")

                for it in cur_batch:
                    a_id = _safe_str(it.get("a_id", "")).strip()
                    if not a_id:
                        continue
                    out[(a_id, cid)] = {
                        "used": False,
                        "decision": "uncertain",
                        "confidence": 0.0,
                        "field": "abstract",
                        "quote": "",
                        "span": None,
                        "valid_quote": False,
                        "error": str(e),
                    }
                break  # stop retrying this batch

        bi += 1

    return out


# --------------------------- row + cache helpers ------------------------------

def _make_item_for_llm(row: Dict[str, str]) -> Dict[str, Any]:
    return {
        "a_id": _safe_str(row.get("local_id","")).strip(),
        "title": _safe_str(row.get("title","")),
        "abstract": _safe_str(row.get("abstract","")),
        "keywords": _safe_str(row.get("keywords","")),
    }

def _row_target_text_hash(row: Dict[str, str], targets: List[str], trunc_chars: int) -> str:
    parts: List[str] = []
    for t in targets:
        v = _safe_str(row.get(t, ""))
        if trunc_chars and len(v) > trunc_chars:
            v = v[:trunc_chars]
        parts.append(v)
    return _sha_text("|".join(parts))

def _cache_key(*, prompt_version: str, model: str, cid: str, a_id: str, text_hash: str, trunc_chars: int) -> str:
    """Compose a cache key from the per-stage ``prompt_version`` and the
    invocation parameters. EL/IL plugins expose stage-curried wrappers
    that bake in their own ``PROMPT_VERSION`` so that legacy call sites
    and tests continue to work unchanged.
    """
    base = f"{prompt_version}|{model}|{cid}|{a_id}|{text_hash}|{trunc_chars}"
    return _sha_text(base)

def _load_cache_from_jsonl(text: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
            k = _safe_str(obj.get("key",""))
            v = obj.get("val", None)
            if k and isinstance(v, dict):
                out[k] = v
        except Exception:
            continue
    return out

def _dump_cache_to_jsonl(cache: Dict[str, Dict[str, Any]]) -> str:
    lines: List[str] = []
    for k, v in cache.items():
        lines.append(json.dumps({"key": k, "val": v}, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")
