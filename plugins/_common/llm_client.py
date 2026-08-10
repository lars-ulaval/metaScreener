
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

* ``_cache_key`` takes ``prompt_version`` as a keyword parameter.
  EL/IL plugins each expose their own ``_cache_key`` curry that bakes
  in their stage's ``PROMPT_VERSION``.

  It also takes the fully-rendered prompt rather than a list of
  invocation parameters (F-01) — see its docstring. The stage curries
  render the prompt for a single item via their own prompt builder, so
  the key covers criterion content and record text without naming
  either.

* ``run_m1_llm_for_criterion`` now takes ``stage`` as a keyword
  parameter. The stage label is used only for log prefixes
  (``[EL-LLM]`` / ``[IL-LLM]``) and the courtesy ``"stage"`` field on
  emitted progress events; no semantic logic depends on its value.

* ``run_m1_llm_for_criterion`` also takes a ``build_messages``
  callable parameter (added in Conv 6 / Commit 2). Each plugin passes
  its own per-stage prompt builder from ``plugins/<stage>/prompt.py``
  so EL and IL prompts can evolve independently.

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

class _Cancelled(Exception):
    """Raised inside ``run_m1_llm_for_criterion`` when the caller's cancel
    token trips.

    F-26. This used to be a bare ``RuntimeError("Cancelled")``, which had
    two consequences. It unwound past ``return out``, throwing away every
    LLM result already paid for in earlier batches; and because the
    post-call check sits inside the per-batch retry ``try``, the generic
    ``except Exception`` handler caught it and wrote the whole batch out as
    ``uncertain`` with ``error="Cancelled"`` — replacing answers that had
    been received with fabricated non-answers.

    A dedicated type lets the retry handler re-raise it untouched and the
    batch loop catch it and return what it has.
    """


def _openai_client_for():
    """Construct the OpenAI client.

    Extracted so cancellation and batching can be tested without a live
    key or network. Nothing else about the call path changed.
    """
    from openai import OpenAI  # type: ignore
    return OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


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

# _build_llm_messages_for_criterion moved to per-plugin prompt.py modules
# (plugins/06_el/prompt.py, plugins/07_il/prompt.py) in Conv 6 / Commit 2.
# The body is byte-identical between EL and IL today, but is duplicated
# deliberately so the two stages' prompts can evolve independently.
# run_m1_llm_for_criterion below now takes the per-stage builder as a
# `build_messages` keyword argument; each plugin passes its own.


def _field_texts_by_id(batch: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """Map ``a_id`` -> that record's field texts, for the records in ONE batch.

    F-86. This map used to be built once from the whole ``items`` list,
    before batching, and served two purposes at once: deciding whether a
    returned ``a_id`` was acceptable, and supplying the text to validate its
    quote against.

    Built over the whole corpus, the first use answers the wrong question —
    "is this one of the records in the run?" rather than "is this one of the
    records in the prompt this response is answering?" — and the second use
    then hands back the *named* record's real text, so the quote validates,
    ``valid_quote`` comes back True, and the evidence gate accepts a verdict
    produced by a call whose prompt did not contain that record. Nothing is
    malformed at any point: the response parses and the quote is genuine.

    Building it per batch makes the invariant structural rather than
    remembered — there is no text in here for a record that was not sent, so
    a foreign ``a_id`` cannot be accepted and cannot be validated. It also
    means the defect does not depend on ``batch_size``: the old map was
    built independently of batching, so single-record calls were no safer.
    """
    texts: Dict[str, Dict[str, str]] = {}
    for it in batch:
        a_id = _safe_str(it.get("a_id", "")).strip()
        if not a_id:
            continue
        texts[a_id] = {
            "title": _safe_str(it.get("title", "")),
            "abstract": _safe_str(it.get("abstract", "")),
            "keywords": _safe_str(it.get("keywords", "")),
        }
    return texts


def run_m1_llm_for_criterion(
    criterion: Dict[str, Any],
    items: List[Dict[str, Any]],
    *,
    stage: str,
    build_messages: Callable[[Dict[str, Any], List[Dict[str, Any]], int], List[Dict[str, str]]],
    model: Optional[str],
    trunc_chars: int,
    batch_size: int,
    log: Optional[Callable[[str], None]] = None,
    progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_token: Optional[object] = None,
    crit_idx: Optional[int] = None,
    crit_total: Optional[int] = None,
    block_tag: str = "exclude",
    temperature: float = 0.0,
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """
    Returns (a_id, criterion_id) -> llm_decision_dict (used/decision/confidence/field/quote/span/valid_quote).
    Implements adaptive batching on errors (429/oversize).

    The ``stage`` keyword (e.g. ``"EL"`` or ``"IL"``) is used for log prefixes
    and the courtesy ``"stage"`` field on emitted progress events. No semantic
    logic depends on its value.

    The ``temperature`` keyword controls the OpenAI sampling temperature
    forwarded to ``client.chat.completions.create``. Default ``0.0`` is
    appropriate for screening tasks where we want deterministic outputs;
    callers may raise it for tasks where some response variability is
    desired. Note that strict determinism is not guaranteed even at 0.0
    due to hardware-level floating-point non-determinism in model
    inference; the cache layer (keyed on temperature for non-zero
    values) is the primary reproducibility safeguard.
    """
    log_prefix = f"[{stage}-LLM]"
    if not model:
        if log: log(f"{log_prefix} model=None; skipping.\n")
        return {}
    if not _has_openai_key():
        if log: log(f"{log_prefix} OPENAI_API_KEY not visible in environment; skipping.\n")
        return {}

    try:
        client = _openai_client_for()
    except Exception as e:
        if log: log(f"{log_prefix} OpenAI client import/init failed: {e}\n")
        return {}

    def _check_cancel():
        if cancel_token is not None and bool(getattr(cancel_token, "cancelled", False)):
            raise _Cancelled()
        if cancel_token is not None and bool(getattr(cancel_token, "is_set", lambda: False)()):
            raise _Cancelled()

    def _call_once(batch: List[Dict[str, Any]], cur_trunc: int):
        msgs = build_messages(criterion, batch, cur_trunc)
        return client.chat.completions.create(
            model=model,
            messages=msgs,
            temperature=temperature,
        )

    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    cid = criterion["id"]

    # F-86: the a_id -> field-texts map is built per batch, inside the loop,
    # from the records that call actually carried. It used to be built here,
    # from the whole `items` list, which is what let a response name a record
    # from another batch and have the quote validate against that record's
    # own text. See _field_texts_by_id.

    # initial batches
    batches: List[List[Dict[str, Any]]] = [list(b) for b in chunked(items, max(1, int(batch_size)))]

    bi = 0
    # F-26: cancellation unwinds to here, not past `return out`. Whatever
    # earlier batches already returned is kept and handed back, because it
    # was paid for. The caller learns the run stopped early from its own
    # cancel_event (F-02), not from losing results.
    try:
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

                    # F-26: no cancel check between the call and the parse. The
                    # answer is already paid for; the cheap thing to skip is the
                    # NEXT batch, not this response. Cancellation is honoured at
                    # the top of the batch loop instead.

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

                    # F-86: scoped to `cur_batch`, and recomputed per attempt
                    # because the adaptive-split path rewrites cur_batch. Both
                    # the acceptance guard and the quote-validation text below
                    # read from here, so neither can reach a record this call
                    # did not send.
                    batch_texts = _field_texts_by_id(cur_batch)

                    # parse response objects
                    for obj in arr:
                        a_id = _safe_str(obj.get("a_id", "")).strip()
                        if not a_id or a_id not in batch_texts:
                            continue

                        # F-86: guarded the way the back-fill below has always
                        # been guarded. An id already carrying a verdict keeps
                        # it: a second object for the same id — whether from a
                        # model contradicting itself inside one response, or
                        # from a later batch naming an earlier batch's record —
                        # must not silently destroy an answer already received.
                        if (a_id, cid) in out:
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

                        fld_txt = (batch_texts.get(a_id) or {}).get(field) or ""
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

                except _Cancelled:
                    # F-26: must not fall into the generic handler below,
                    # which would mark every item in this batch "uncertain"
                    # with error="Cancelled" — fabricating non-answers out of
                    # a user action. Let it reach the batch loop.
                    raise

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

    except _Cancelled:
        if log:
            log(f"{log_prefix} cancelled after {bi} of {len(batches)} "
                f"batches; keeping {len(out)} result(s) already received.\n")

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

def _render_prompt_for_key(messages: Sequence[Dict[str, str]]) -> str:
    """Serialise a rendered chat-completion message list stably.

    Stability matters twice over: the same inputs must hash the same way
    in a different process (so no builtin ``hash()`` and no reliance on
    dict insertion order — ``sort_keys=True``), and the serialisation
    must be lossless enough that two prompts differing anywhere produce
    different strings.
    """
    return json.dumps(
        [
            {
                "role": _safe_str(m.get("role", "")),
                "content": _safe_str(m.get("content", "")),
            }
            for m in (messages or [])
        ],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def _cache_key(*, prompt_version: str, model: str, rendered_prompt: str,
               temperature: float = 0.0) -> str:
    """Compose a cache key from everything that determines the model's
    answer: the fully-rendered prompt, the model, and the temperature.

    F-01. This used to hash an enumerated list of invocation parameters —
    ``prompt_version|model|cid|a_id|text_hash|trunc_chars`` — of which the
    only part of the criterion was its *id*. The rendered prompt also
    carries ``type``, ``operator``, ``target``, ``what``, ``label`` and
    ``threshold``, so editing a criterion's wording while keeping its id
    was a cache *hit*: every record was served the previous criterion's
    answer, with evidence quotes taken against text the model never saw
    on that run, and the UI reported a normal ``cache_hits=N``.

    Enumeration was itself the bug — temperature and prompt version had
    each been bolted onto that list in separate earlier commits. Hashing
    the rendered prompt means anything that changes what the model sees
    changes the key automatically, so this class of defect cannot recur:
    criterion content, record text, field truncation and the prompt
    template are all covered without being named here.

    ``prompt_version`` is still hashed alongside. It is redundant with
    the template text in ``rendered_prompt`` for any change that alters
    the wording, but it remains the deliberate, greppable lever for
    invalidating the cache on a semantic change that happens not to move
    a byte of the template.

    ``temperature`` is hashed unconditionally now. It used to be appended
    only when non-zero, to spare a cache captured before it was part of
    the key; that cache is superseded by this change anyway. 0.0 is still
    the default, so an omitted temperature and an explicit 0.0 agree.
    """
    base = json.dumps(
        {
            "prompt_version": _safe_str(prompt_version),
            "model": _safe_str(model),
            "temperature": float(temperature),
            "prompt": rendered_prompt,
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
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
