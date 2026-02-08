# -*- coding: utf-8 -*-
"""
Created on Sat Oct  4 12:28:31 2025

@author: alere

File: plugins/screen_A/llm_metadata.py

Runs criterion-wise, batched metadata screening via LLM with:
 - strict JSON schema & extractive-quote validation
 - batching & parallel workers
 - retries with backoff
 - file cache to avoid re-paying for identical inputs

Public entrypoint:
    run_llm_for_criteria(items, criteria, model, batch_size, workers, trunc_chars, progress_cb)

Returns:
    decisions: dict[tuple[a_id, criterion_id], dict[str, Any]]
        where each value has keys: llm_decision, llm_conf, llm_field, llm_quote_span
"""

from __future__ import annotations
from typing import Any, Dict, List, Tuple, Optional, Callable
import json
import math
import re
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

# Prompts
from .prompts import (
    build_metadata_criterion_batched_messages,
)

# Cache
from .llm_cache import make_key, cache_get, cache_put


# -----------------------------
# Config / Types
# -----------------------------

ChatFn = Callable[[str, List[Dict[str, Any]]], str]
PROMPT_VERSION = "v1"

_ALLOWED_FIELDS = {"title", "abstract", "keywords", "venue", "lang", "year"}

_DECISION_SET = {"meet", "not_meet", "uncertain"}


# -----------------------------
# Utilities
# -----------------------------

def _normalize_field_name(k: str) -> str:
    k = (k or "").lower().strip()
    # normalize typical aliases
    if k in {"language"}:
        return "lang"
    if k in {"journal"}:
        return "venue"
    if k in {"ti"}:
        return "title"
    if k in {"ab"}:
        return "abstract"
    if k in {"kw"}:
        return "keywords"
    if k in {"py"}:
        return "year"
    return k


def _truncate_text(s: Optional[str], limit: int) -> str:
    if not s:
        return ""
    if limit and len(s) > limit:
        return s[:limit]
    return s


def _extract_item_fields(item: Dict[str, Any], trunc_chars: int) -> Dict[str, Any]:
    # Pull only relevant metadata, normalized, truncated
    take = {
        "title": item.get("title") or item.get("ti"),
        "abstract": item.get("abstract") or item.get("ab"),
        "keywords": item.get("keywords") or item.get("kw"),
        "venue": item.get("venue") or item.get("journal"),
        "lang": item.get("language") or item.get("lang"),
        "year": item.get("year") or item.get("py"),
    }
    out: Dict[str, Any] = {}
    for k, v in take.items():
        nk = _normalize_field_name(k)
        if nk not in _ALLOWED_FIELDS:
            continue
        if nk in {"title", "abstract", "keywords", "venue"}:
            out[nk] = _truncate_text(str(v or ""), trunc_chars)
        else:
            out[nk] = str(v or "")
    # drop empties
    return {k: v for k, v in out.items() if (v is not None and v != "")}


def _hash_fields(fields: Dict[str, Any]) -> str:
    # Stable per-item fields hash for caching
    h = hashlib.sha256()
    for k in sorted(fields.keys()):
        h.update(k.encode("utf-8")); h.update(b"\x1f"); h.update(str(fields[k]).encode("utf-8")); h.update(b"\x1e")
    return h.hexdigest()


def _strip_code_fences(s: str) -> str:
    if s is None:
        return ""
    s = s.strip()
    # remove ```json ... ``` fences if present
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _find_json_array(s: str) -> Optional[str]:
    """Best-effort: find the first [...] JSON array."""
    m = re.search(r"\[\s*{", s, flags=re.S)
    if not m:
        return None
    start = m.start()
    # naive scan to matching bracket balance
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "[":
            depth += 1
        elif s[i] == "]":
            depth -= 1
            if depth == 0:
                return s[start:i+1]
    return None


# -----------------------------
# Validation helpers
# -----------------------------

def _validate_and_normalize_response(raw_text: str,
                                     criterion_id: str,
                                     items_index: Dict[str, Dict[str, Any]]) -> Dict[Tuple[Any, Any], Dict[str, Any]]:
    """
    Parse assistant raw text to JSON and validate each item element.
    Returns mapping (a_id, criterion_id) -> normalized dict.
    Unknown/invalid entries are coerced to {"llm_decision": "uncertain", "llm_conf": 0.0, "llm_field": None, "llm_quote_span": None}
    """
    out: Dict[Tuple[Any, Any], Dict[str, Any]] = {}

    text = _strip_code_fences(raw_text)
    blob = _find_json_array(text) or text

    try:
        data = json.loads(blob)
        if not isinstance(data, list):
            raise ValueError("Expected a JSON array")
    except Exception:
        # total failure: mark all as uncertain
        for a_id in items_index.keys():
            out[(a_id, criterion_id)] = {
                "llm_decision": "uncertain",
                "llm_conf": 0.0,
                "llm_field": None,
                "llm_quote_span": None,
            }
        return out

    # Build quick map a_id -> element
    for el in data:
        try:
            a_id = str(el.get("a_id"))
        except Exception:
            continue
        if a_id not in items_index:
            # ignore unknown ids
            continue

        norm = {
            "llm_decision": "uncertain",
            "llm_conf": 0.0,
            "llm_field": None,
            "llm_quote_span": None,
        }

        try:
            decisions = el.get("decisions") or []
            if not decisions:
                out[(a_id, criterion_id)] = norm
                continue
            d0 = decisions[0]  # our prompt uses one criterion
            cid = str(d0.get("criterion_id") or "")
            if cid != str(criterion_id):
                # if different, still consume but treat as uncertain
                out[(a_id, criterion_id)] = norm
                continue

            dec = str(d0.get("decision") or "").lower().strip()
            conf = float(d0.get("confidence") or 0.0)
            if dec not in _DECISION_SET or not (0.0 <= conf <= 1.0):
                out[(a_id, criterion_id)] = norm
                continue

            # justification (extractive)
            just = d0.get("justification")
            if just is None and dec == "uncertain":
                # OK: uncertain with no quote
                norm["llm_decision"] = dec
                norm["llm_conf"] = conf
                out[(a_id, criterion_id)] = norm
                continue

            field = _normalize_field_name((just or {}).get("field") or "")
            quote = (just or {}).get("quote") or ""
            span = (just or {}).get("char_span")

            # Validate extractive constraints
            fields = items_index[a_id]["fields"]
            ok = True
            if field not in _ALLOWED_FIELDS or field not in fields:
                ok = False
            else:
                txt = str(fields[field] or "")
                if not isinstance(span, list) or len(span) != 2:
                    ok = False
                else:
                    s0, s1 = int(span[0]), int(span[1])
                    if s0 < 0 or s1 < s0 or s1 > len(txt):
                        ok = False
                    else:
                        if txt[s0:s1] != quote:
                            ok = False

            if not ok:
                # invalid justification → downgrade to uncertain
                out[(a_id, criterion_id)] = norm
                continue

            norm["llm_decision"] = dec
            norm["llm_conf"] = conf
            norm["llm_field"] = field
            norm["llm_quote_span"] = [int(span[0]), int(span[1])]
            out[(a_id, criterion_id)] = norm

        except Exception:
            out[(a_id, criterion_id)] = norm

    # Fill any missing items (LLM didn’t return them) as uncertain
    for a_id in items_index.keys():
        out.setdefault((a_id, criterion_id), {
            "llm_decision": "uncertain",
            "llm_conf": 0.0,
            "llm_field": None,
            "llm_quote_span": None,
        })

    return out


# -----------------------------
# Chat caller (OpenAI default)
# -----------------------------

def _default_openai_chat(model: str, messages: List[Dict[str, Any]]) -> str:
    """
    Minimal OpenAI Chat Completions wrapper. Uses environment OPENAI_API_KEY.
    Returns assistant content (string).
    """
    try:
        from openai import OpenAI
    except Exception as e:
        raise RuntimeError("openai package not available; supply chat_fn instead") from e

    client = OpenAI()
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
    )
    return (resp.choices[0].message.content or "").strip()


def _retry_chat(chat_fn: ChatFn, model: str, messages: List[Dict[str, Any]], *, max_retries: int = 4) -> str:
    delay = 1.0
    for attempt in range(max_retries):
        try:
            return chat_fn(model, messages)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
            delay *= 2.0  # exponential backoff
    raise RuntimeError("unreachable")  # for type checker


# -----------------------------
# Batching
# -----------------------------

def _chunk_list(xs: List[Any], k: int) -> List[List[Any]]:
    if k <= 0:
        return [xs]
    return [xs[i:i+k] for i in range(0, len(xs), k)]


# -----------------------------
# Public entrypoint
# -----------------------------

def run_llm_for_criteria(
    items: List[Dict[str, Any]],
    criteria: List[Dict[str, Any]],
    *,
    model: str = "gpt-4o-mini",
    batch_size: int = 12,
    workers: int = 8,
    trunc_chars: int = 1500,
    prompt_version: str = PROMPT_VERSION,
    chat_fn: Optional[ChatFn] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Dict[Tuple[Any, Any], Dict[str, Any]]:
    """
    Criterion-wise batching over a population of items.
    - For each criterion, we:
        * build an items_index {a_id -> {"fields", "fields_hash"}}
        * check per-item cache; only call LLM for cache-misses
        * call in batches; validate/normalize response; write cache & merge
    Returns decisions for ALL (a_id, criterion_id) pairs encountered (cached + fresh).
    """
    if chat_fn is None:
        chat_fn = _default_openai_chat

    # Ensure a_id is present for all items
    enriched_items: List[Dict[str, Any]] = []
    for i, it in enumerate(items, 1):
        a_id = it.get("a_id") or it.get("id") or i
        it = dict(it)
        it["a_id"] = a_id
        enriched_items.append(it)

    results: Dict[Tuple[Any, Any], Dict[str, Any]] = {}
    total_batches = 0
    done_batches = 0

    # First, count how many batches we expect (cache unaware estimate)
    for c in criteria:
        # rough estimate: ceil(N / batch_size)
        total_batches += max(1, math.ceil(len(enriched_items) / max(1, batch_size)))

    if progress_cb:
        progress_cb(done_batches, total_batches)

    for c in criteria:
        cid = c.get("id")
        cscope = (c.get("scope") or "both").lower()
        if cscope not in ("metadata", "both"):
            continue  # skip non-metadata criteria

        # Build per-item fields and cache keys
        items_index: Dict[str, Dict[str, Any]] = {}
        pending: List[Dict[str, Any]] = []
        for it in enriched_items:
            a_id = str(it["a_id"])
            fields = _extract_item_fields(it, trunc_chars=trunc_chars)
            fields_hash = _hash_fields(fields)
            cache_key = make_key(model, prompt_version, str(cid), a_id, fields_hash)

            items_index[a_id] = {"fields": fields, "fields_hash": fields_hash, "cache_key": cache_key}

            cached = cache_get(cache_key)
            if cached is not None:
                # Already normalized payload
                results[(a_id, cid)] = dict(cached)
            else:
                # Build minimal item payload for prompt
                payload = {"a_id": a_id, **fields}
                pending.append(payload)

        if not pending:
            # all cached for this criterion
            continue

        # Execute in parallel batches (per criterion)
        batches = _chunk_list(pending, batch_size)

        def _task(batch_items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], str]:
            # messages for this batch
            criterion_json = json.dumps({
                "id": cid,
                "type": c.get("type"),
                "scope": c.get("scope"),
                "label": c.get("label"),
                "targets": c.get("targets"),
                "operators": c.get("operators"),
                "weight": c.get("weight"),
                "threshold": c.get("threshold"),
            }, ensure_ascii=False)
            items_json = json.dumps(batch_items, ensure_ascii=False)

            messages = build_metadata_criterion_batched_messages(criterion_json, items_json, prompt_version)
            raw = _retry_chat(chat_fn, model, messages)
            return batch_items, raw

        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futs = [ex.submit(_task, b) for b in batches]
            for fut in as_completed(futs):
                try:
                    batch_items, raw_text = fut.result()
                except Exception as e:
                    # Mark this entire batch uncertain if call failed
                    for it in batch_items:
                        a_id = str(it["a_id"])
                        results[(a_id, cid)] = {
                            "llm_decision": "uncertain",
                            "llm_conf": 0.0,
                            "llm_field": None,
                            "llm_quote_span": None,
                        }
                    done_batches += 1
                    if progress_cb:
                        progress_cb(done_batches, total_batches)
                    continue

                # Validate/normalize
                # Make a per-batch index with exact same fields for justification verification
                per_batch_index = {str(it["a_id"]): {"fields": {k: v for k, v in it.items() if k != "a_id"}} for it in batch_items}
                normalized = _validate_and_normalize_response(raw_text, str(cid), per_batch_index)

                # Merge + cache
                for (a_id, _cid), payload in normalized.items():
                    results[(a_id, cid)] = payload
                    # Save in cache using the pre-built key from global items_index if possible
                    meta = items_index.get(a_id)
                    if meta:
                        cache_put(meta["cache_key"], payload)

                done_batches += 1
                if progress_cb:
                    progress_cb(done_batches, total_batches)

    return results
