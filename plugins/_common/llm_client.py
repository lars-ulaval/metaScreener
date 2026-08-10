
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
from collections import Counter
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


def _guarded(fn: Optional[Callable[[Any], None]]) -> Optional[Callable[[Any], None]]:
    """Wrap a caller-supplied reporting callback so its failure cannot change
    the work it reports on.

    F-134. ``progress()`` and ``log()`` are called from *inside* the per-batch
    retry ``try``, and the ``sub="batch_done"`` event in particular is emitted
    after the parse loop and the omission back-fill have both written. So an
    exception raised while *reporting* on a batch fell into the generic
    handler, matched no salvage class, and rewrote every record of that batch
    as a terminal failure — destroying answers the API call had already been
    paid for. That is F-26's shape reached through a different trigger, and
    F-26's fix does not cover it: it guards ``_Cancelled`` specifically.

    The route is not hypothetical. ``plugins/06_el/ui.py::ELView._run_clicked``
    passes a ``progress_evt`` that marshals through ``self.after``, which
    raises ``RuntimeError`` once the Tk root is gone — i.e. whenever the user
    closes the window during a run.

    Swallowing is the right disposal, and the alternatives are both worse:
    letting it propagate kills the run and discards every batch already paid
    for, and letting it reach the retry handler is the defect. A reporting
    channel that cannot report is a lost log line; it must not also be a lost
    verdict.

    ``_Cancelled`` is re-raised rather than swallowed. No reporting callback
    raises it today, but cancellation is control flow rather than a reporting
    failure, and a swallow here would make the cancel button stop working the
    moment someone wired one through a callback.
    """
    if fn is None:
        return None

    def _call(payload: Any) -> None:
        try:
            fn(payload)
        except _Cancelled:
            raise
        except Exception:
            pass

    return _call


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

def _sample_of(counts: "Counter", limit: int = 5) -> str:
    """Render the commonest few keys of a tally for a log line.

    Bounded on purpose: the values are model output, so an unbounded render
    would put arbitrary text of arbitrary length into the log pane.
    """
    head = ", ".join(f"{k!r}×{n}" for k, n in counts.most_common(limit))
    rest = len(counts) - min(limit, len(counts))
    return head + (f", and {rest} other value(s)" if rest > 0 else "")

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


# --------------------------- error classification -----------------------------

LLM_ERROR_CLASSES: Tuple[str, ...] = (
    "rate_limit", "oversize", "bad_request", "auth", "not_found",
    "transport", "unknown",
)
"""What went wrong with a call, as far as it can honestly be determined.

Only ``rate_limit`` and ``oversize`` have remedies in this module. The rest
exist so that a terminal failure is *named* rather than anonymous: today a
down server, a rejected key, a model that was never pulled and a malformed
request produce one indistinguishable record.
"""

# The oversize vocabulary of the servers this project actually targets, not
# of OpenAI's JSON error bodies. Every alternative below is something
# llama.cpp, Ollama, vLLM or the hosted API emits. F-94.
_OVERSIZE_RE = re.compile(
    r"n_ctx"
    r"|context[\s_\-]*(?:length|window|size)"
    r"|exceeds?[\s_\-]+the[\s_\-]+context"
    r"|max(?:imum)?[\s_\-]*tokens?"
    r"|token[\s_\-]*limit"
    r"|too[\s_\-]+large"
    r"|too[\s_\-]+long"
    r"|reduce[\s_\-]+the[\s_\-]+length",
    re.I,
)

# Anchored on word boundaries. The old predicate was
# ``("rate" in msg and "limit" in msg)``, which fires on any message
# containing `generate`, `moderate` or `separate` *and* the word `limit`
# anywhere else in it -- "moderate token limit exceeded" classifies as a
# rate limit today. F-94's finding cell states the substring half of this;
# the conjunction is why it needs the second word to be live.
_RATE_RE = re.compile(r"\b429\b|\btoo[\s_\-]+many[\s_\-]+requests\b"
                      r"|\brate[\s_\-]*limit", re.I)


def _openai_error_types() -> Dict[str, type]:
    """The SDK's exception classes, or ``{}`` if the SDK is not importable.

    Imported lazily, like ``_openai_client_for``'s ``from openai import
    OpenAI``. Hoisting these to module scope would make every stage module
    fail to import on a machine without the SDK, which is a strictly worse
    failure than losing type-based classification on a machine that cannot
    make an API call in the first place.
    """
    try:
        import openai  # type: ignore
    except Exception:
        return {}
    found: Dict[str, type] = {}
    for name in ("RateLimitError", "BadRequestError", "AuthenticationError",
                 "PermissionDeniedError", "NotFoundError",
                 "APITimeoutError", "APIConnectionError"):
        t = getattr(openai, name, None)
        if isinstance(t, type):
            found[name] = t
    return found


def _classify_llm_error(e: BaseException) -> Tuple[str, str]:
    """Classify a failed call as ``(class, how)``.

    F-94. Both salvage mechanisms used to be gated on substring sniffs over
    ``str(e).lower()``, and ``is_big`` required ``context`` *and* ``length``
    to co-occur. A server saying ``"n_ctx exceeded"`` or ``"prompt exceeds
    the context window"`` matched neither term-pair, **so the batch-halving
    and truncation step-down that exist precisely for a small context window
    never fired** — and small context windows are the local case, which is
    why this is correctness rather than robustness.

    Three resorts, in order, and ``how`` names which one answered so the log
    line can say. **The message sniff is the last of them and is labelled as
    such**, because prose is the only signal a server is free to change.

    ``type``
        the SDK named the condition. The only signal that does not depend on
        wording.
    ``status``
        an OpenAI-compatible server behind a proxy can surface a generic
        ``APIStatusError``; the HTTP code still means what it means.
    ``message``
        last resort. Restricted to ``oversize`` and ``rate_limit``, the two
        classes that have remedies — there is deliberately no message-level
        transport sniff, because a bare string containing "timeout" is not
        evidence of a transport failure (``"Internal server error (500) …
        upstream timeout"`` is a server error), and every real transport
        condition arrives as an SDK type or an HTTP status anyway.

    Never raises: it runs inside an ``except`` block, and a classifier that
    raised would replace the error being classified with its own.
    """
    try:
        types = _openai_error_types()
    except Exception:                                    # pragma: no cover
        types = {}

    try:
        lowered = str(e).lower()
    except Exception:
        lowered = ""
    oversize = bool(_OVERSIZE_RE.search(lowered))

    def _is(name: str) -> bool:
        t = types.get(name)
        try:
            return t is not None and isinstance(e, t)
        except Exception:                                # pragma: no cover
            return False

    # 1 — by type
    if _is("RateLimitError"):
        return "rate_limit", "type"
    if _is("BadRequestError"):
        # A 400 is oversize only when its body says so. Treating every 400
        # as oversize would halve the batch to one and step the truncation
        # to its floor against a request the server will never accept.
        return ("oversize", "type+message") if oversize else ("bad_request", "type")
    if _is("AuthenticationError") or _is("PermissionDeniedError"):
        return "auth", "type"
    if _is("NotFoundError"):
        return "not_found", "type"
    # APITimeoutError subclasses APIConnectionError in the SDK, so the
    # second test covers both; both are named for legibility.
    if _is("APITimeoutError") or _is("APIConnectionError"):
        return "transport", "type"

    # 2 — by HTTP status
    status: Optional[int] = None
    try:
        raw = getattr(e, "status_code", None)
        status = int(raw) if raw is not None else None
    except Exception:
        status = None
    if status is not None:
        if status == 429:
            return "rate_limit", "status"
        if status in (401, 403):
            return "auth", "status"
        if status == 404:
            return "not_found", "status"
        if status in (400, 413):
            return ("oversize", "status+message") if oversize else ("bad_request", "status")
        if status in (408, 502, 503, 504):
            return "transport", "status"

    # 3 — by message. LAST RESORT.
    if oversize:
        return "oversize", "message"
    if _RATE_RE.search(lowered):
        return "rate_limit", "message"
    return "unknown", "none"


# --------------------------- answer vocabularies ------------------------------

DECISION_VOCABULARY: Tuple[str, ...] = ("meet", "not_meet", "uncertain")
"""The only ``decision`` values the evidence gate can act on.

F-90, F-108. Named rather than inline so the set has one home; the prompt
still restates it in prose twenty lines away, which is F-108 and is not
fixed here.
"""

FIELD_VOCABULARY: Tuple[str, ...] = ("title", "abstract", "keywords")

_DECISION_SEPARATORS = re.compile(r"[\s_\-]+")


def _normalize_decision(raw: Any) -> Optional[str]:
    """Map a model's ``decision`` onto :data:`DECISION_VOCABULARY`, or return
    ``None`` when it falls outside it.

    F-90. This comparison used to be ``decision not in {...}`` against a
    ``.strip()``-ed string, while ``field`` on the *next* statement got
    ``.strip().lower()``. A model answering ``"Meet"`` therefore had every
    decision in the run rewritten to ``"uncertain"`` — and the record kept
    ``used: True``, a genuine quote and a high confidence, so nothing about
    it looked wrong except the verdict.

    **This goes further than the register's fix cell, which says "one
    `.lower()`", and the departure is deliberate.** F-90's own *finding*
    cell names ``"not meet"`` among the strings a model produces, and case
    folding alone does not reach it. A model that varies the case varies the
    separator for the same reason — there is no ``response_format`` on the
    local path to hold it to either — so the separator is normalised too.

    The normalisation cannot invent a verdict. Only a string that reduces
    exactly to a vocabulary member is accepted, and no semantically
    different answer does: ``meets``, ``does not meet``, ``notmeet`` and
    ``yes`` are all still outside it. That is what
    ``TestTheWideningIsExact`` exists to hold.

    ``None`` is the rejection signal rather than a silent fallback to
    ``"uncertain"``, so the caller can count and report it. Returning the
    fallback here is what made the condition invisible.
    """
    s = _DECISION_SEPARATORS.sub("_", _safe_str(raw).strip().lower())
    return s if s in set(DECISION_VOCABULARY) else None


def new_llm_call_stats() -> Dict[str, int]:
    """A fresh tally of the call-level facts that leave no record behind.

    The counterpart to :func:`summarize_llm_evidence`, and the reason the
    two exist separately. A batch that is refused as oversize, halved, and
    then answered ends with every record carrying a good verdict — the
    failure is *invisible* in the evidence map, so "how many calls raised"
    cannot be derived from the records and has to be counted where it
    happens. Everything that *can* be derived, is.

    ``calls_made``
        invocations of ``_call_once``. **Not** the number of HTTP requests:
        the SDK defaults to ``max_retries=2`` beneath this layer, so the
        wire count can be up to three times this (F-25).
    ``calls_failed``
        invocations that raised, whether or not the batch was later
        salvaged.
    ``batches_failed``
        batches that ended in the terminal arm with no verdict.

    Passed in by the caller and mutated, rather than returned:
    ``run_m1_llm_for_criterion``'s return type is pinned as a plain mapping
    by fourteen existing tests — one of which asserts ``out == {}`` — and a
    tuple return would break all of them for a secondary channel. It also
    lets one dict accumulate across every criterion of a stage.
    """
    return {"calls_made": 0, "calls_failed": 0, "batches_failed": 0}


def _bump(stats: Optional[Dict[str, int]], key: str) -> None:
    if stats is not None:
        stats[key] = int(stats.get(key, 0)) + 1


def summarize_llm_evidence(
        evidence: Optional[Dict[Tuple[str, str], Dict[str, Any]]]
) -> Dict[str, int]:
    """Derive the record-level counts of a run from the records themselves.

    This project has been bitten four times by a count maintained alongside
    the thing it counts — most recently by the register's own severity
    totals (F-131) — so the rule adopted in wave 8 is: **a fact about a
    record is derived from the record; only a fact about a *call*, which
    leaves no record behind, is stored in a counter.** Everything here is
    the first kind. Nothing increments these; they are recomputed from the
    evidence map the decisions were actually made from, so they cannot
    disagree with it.

    ``records`` partitions exactly into ``failed`` + ``no_answer`` +
    ``decisions_rejected`` + ``answered``:

    ``failed``
        the call for this record raised and never produced an answer
        (``error`` present, by key rather than truthiness — see
        :func:`_is_cacheable_evidence`).
    ``no_answer``
        the record was sent and the model said nothing about it — the
        omission back-fill.
    ``decisions_rejected``
        the model answered and the answer was outside
        :data:`DECISION_VOCABULARY` (F-90).
    ``answered``
        a decision this pipeline could read. **This is the number that
        distinguishes a run that worked from a run that did not**, and it is
        the whole point of the wave: a model that answers ``"uncertain"``
        everywhere gives ``answered == records``, while a down server, a
        typo'd model and an empty model field all give ``answered == 0``.
        Today those five states are one message.

    ``fields_rejected`` is orthogonal to the partition — a record can carry
    a readable decision and an unreadable ``field`` — and is counted rather
    than acted on. That is F-136.
    """
    out = {"records": 0, "answered": 0, "no_answer": 0, "failed": 0,
           "decisions_rejected": 0, "fields_rejected": 0}
    for ev in (evidence or {}).values():
        if not isinstance(ev, dict):
            continue
        out["records"] += 1
        if "field_rejected" in ev:
            out["fields_rejected"] += 1
        if "error" in ev:
            out["failed"] += 1
        elif ev.get("used") is not True:
            out["no_answer"] += 1
        elif "decision_rejected" in ev:
            out["decisions_rejected"] += 1
        else:
            out["answered"] += 1
    return out


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
    stats: Optional[Dict[str, int]] = None,
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
    # F-134: every `log(...)` and `progress(...)` below goes through the
    # guard from here on. Rebinding the two names rather than editing a
    # dozen call sites keeps the property in one place — a new reporting
    # call added later is covered without anyone having to remember.
    log = _guarded(log)
    progress = _guarded(progress)

    log_prefix = f"[{stage}-LLM]"
    if not model:
        # F-119: this line said `model=None` whatever the value actually was,
        # and its reachable trigger was a whitespace-only field — so a user
        # who trusted it went looking for a null where there was a space.
        # `!r` is what makes None, "" and "  " distinguishable at a glance.
        if log: log(f"{log_prefix} no model set (model={model!r}); "
                    f"skipping this criterion.\n")
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
        # Counted here rather than at the call site so that every attempt is
        # counted once, including the ones a later salvage makes invisible in
        # the evidence map. See new_llm_call_stats.
        _bump(stats, "calls_made")
        return client.chat.completions.create(
            model=model,
            messages=msgs,
            temperature=temperature,
        )

    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    cid = criterion["id"]

    # F-90. Accumulated across every batch of this criterion and reported
    # once at the end rather than per record: a rejection is a property of
    # the *model's format discipline*, so on an 800-record corpus a per-record
    # line would produce 800 identical lines in a sub-tab that is not the
    # focused one — which is the reporting failure this wave exists to fix,
    # committed a second time. The raw strings are kept, not just the tally,
    # because "Meet" and "maybe" call for opposite responses from the user.
    rejected_decisions: Counter = Counter()
    rejected_fields: Counter = Counter()

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

                        # F-90: fold case and separator, and keep the raw
                        # string when the answer falls outside the
                        # vocabulary. Rewriting it to "uncertain" and saying
                        # nothing is what made a model with poor format
                        # discipline indistinguishable from a model that was
                        # unsure about everything.
                        decision_raw = _safe_str(obj.get("decision", "uncertain"))
                        decision = _normalize_decision(decision_raw)
                        decision_rejected = decision is None
                        if decision_rejected:
                            decision = "uncertain"
                            rejected_decisions[decision_raw.strip()] += 1

                        try:
                            confidence = float(obj.get("confidence", 0.0))
                        except Exception:
                            confidence = 0.0
                        confidence = min(1.0, max(0.0, confidence))

                        field_raw = _safe_str(obj.get("field", ""))
                        field = field_raw.strip().lower()
                        # F-136: the fallback is recorded but NOT widened.
                        # `field` selects which text the quote is validated
                        # against, so accepting more values here would change
                        # the meaning of `valid_quote` — a behaviour change no
                        # finding asks for. Counted so the row can be settled
                        # on measurement rather than argument.
                        field_rejected = field not in set(FIELD_VOCABULARY)
                        if field_rejected:
                            field = "abstract"
                            rejected_fields[field_raw.strip()] += 1

                        quote = _safe_str(obj.get("quote", ""))
                        span = obj.get("span", None)
                        if not (isinstance(span, list) and len(span) == 2 and all(isinstance(x, int) for x in span)):
                            span = None

                        fld_txt = (batch_texts.get(a_id) or {}).get(field) or ""
                        # Validate against the SAME truncated text that was sent to the model for this call
                        fld_txt_prompt = (fld_txt[:cur_trunc] if cur_trunc and len(fld_txt) > cur_trunc else fld_txt)
                        valid_quote = _quote_in_text(quote, fld_txt_prompt)

                        ev: Dict[str, Any] = {
                            "used": True,
                            "decision": decision,
                            "confidence": confidence,
                            "field": field,
                            "quote": quote,
                            "span": span,
                            "valid_quote": valid_quote,
                        }
                        # Recorded by key presence, like `error`, so the
                        # marker survives an empty raw string. These are the
                        # only fields `summarize_llm_evidence` reads that the
                        # record did not already carry, and neither reaches
                        # `{el,il}_evidence_json`: the stage builds that from
                        # a fixed list of nine keys.
                        if decision_rejected:
                            ev["decision_rejected"] = decision_raw
                        if field_rejected:
                            ev["field_rejected"] = field_raw
                        out[(a_id, cid)] = ev

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
                    # F-94. This used to be two substring sniffs over
                    # str(e).lower(), and `is_big` required `context` AND
                    # `length` to co-occur — so "n_ctx exceeded" and "prompt
                    # exceeds the context window" fired neither remedy, and
                    # the two mechanisms that exist for a small context
                    # window were unavailable in the configuration that most
                    # needs them. Type first, HTTP status second, message
                    # only as a labelled last resort.
                    err_class, err_how = _classify_llm_error(e)
                    _bump(stats, "calls_failed")

                    # Only these two have a remedy here. `bad_request`,
                    # `auth`, `not_found` and `transport` are terminal for
                    # this batch by design: halving a malformed request, a
                    # rejected key or a missing model just spends the same
                    # failure twice.
                    #
                    # `transport` is terminal *deliberately*, and it is a
                    # departure from a literal reading of F-94's "terminal on
                    # first sight". The SDK defaults to max_retries=2, so a
                    # transport error reaching this layer has already been
                    # attempted three times (F-25); a ladder here would make
                    # it six, and F-25 is explicit that the application's
                    # ladder and the SDK's must be chosen together. What
                    # changes is that the failure is now named.
                    salvageable = err_class in ("rate_limit", "oversize")

                    # split WITHOUT losing items (requeue remainder right after this batch)
                    if salvageable and len(cur_batch) > 1:
                        new_n = max(1, len(cur_batch) // 2)
                        remainder = cur_batch[new_n:]
                        cur_batch = cur_batch[:new_n]

                        # replace current batch, insert remainder as next batch
                        batches[bi] = cur_batch
                        if remainder:
                            batches.insert(bi + 1, remainder)

                        if log:
                            log(
                                f"{log_prefix} batch {bi+1}/{len(batches)} "
                                f"{err_class} (by {err_how}): {e}; "
                                f"split into {len(cur_batch)} + {len(remainder)}\n"
                            )

                        time.sleep(min(4.0, 0.4 * attempts))
                        continue

                    # reduce truncation if still oversize/rate-limited and trunc is high
                    if salvageable and cur_trunc > 600:
                        new_trunc = max(600, int(cur_trunc * 0.75))
                        if log:
                            log(f"{log_prefix} batch {bi+1}/{len(batches)} "
                                f"{err_class} (by {err_how}): {e}; "
                                f"trunc {cur_trunc} -> {new_trunc}\n")
                        cur_trunc = new_trunc
                        time.sleep(min(4.0, 0.4 * attempts))
                        continue

                    # final failure for this batch: mark all items in THIS cur_batch as uncertain
                    _bump(stats, "batches_failed")
                    if log:
                        log(f"{log_prefix} batch {bi+1}/{len(batches)} failed "
                            f"[{err_class}, by {err_how}]: {e}\n")

                    for it in cur_batch:
                        a_id = _safe_str(it.get("a_id", "")).strip()
                        if not a_id:
                            continue
                        # F-134: guarded the way the omission back-fill twelve
                        # lines above has always been guarded. Anything that
                        # raises after the parse loop has begun writing used to
                        # rewrite verdicts this batch had already received —
                        # a received `meet` replaced by a fabricated
                        # `uncertain`. The records with no verdict still get an
                        # entry below, so nothing is left unaccounted for; what
                        # changes is that an answer is never destroyed by the
                        # failure that followed it.
                        if (a_id, cid) in out:
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
                            # F-94: the class rides on the record, not only in
                            # the log. A log line lives in a sub-tab that is
                            # not the focused one; the record reaches whoever
                            # asks why the run produced no answers. It cannot
                            # reach a cache file — `error` already makes the
                            # entry uncacheable (F-87).
                            "error_class": err_class,
                        }
                    break  # stop retrying this batch

            bi += 1

    except _Cancelled:
        if log:
            log(f"{log_prefix} cancelled after {bi} of {len(batches)} "
                f"batches; keeping {len(out)} result(s) already received.\n")

    # F-90: one summary line per criterion, emitted whether or not the run
    # was cancelled — a rejection already observed is worth reporting.
    if log and rejected_decisions:
        log(f"{log_prefix} {cid}: {sum(rejected_decisions.values())} "
            f"decision value(s) outside "
            f"{{{', '.join(DECISION_VOCABULARY)}}} were rejected and "
            f"recorded as uncertain: {_sample_of(rejected_decisions)}. "
            f"These records carry a quote and a confidence but no usable "
            f"verdict; the model is answering in a vocabulary this stage "
            f"does not read.\n")
    if log and rejected_fields:
        log(f"{log_prefix} {cid}: {sum(rejected_fields.values())} "
            f"field value(s) outside {{{', '.join(FIELD_VOCABULARY)}}} were "
            f"replaced with 'abstract': {_sample_of(rejected_fields)}. The "
            f"quote was validated against the abstract rather than the "
            f"field the model named (F-136).\n")

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

def _is_cacheable_evidence(ev: Any) -> bool:
    """True when an evidence dict records an answer the model actually gave.

    F-87. EL's and IL's write-back merged *every* entry of the result map
    into the persistent cache with no filter at all, so a transient 500, a
    timeout, an auth blip, an oversize failure, a cancelled batch or a plain
    omission was stored under a key that matches on every later run. The read
    side's ``ev.setdefault("used", True)`` then served it back as though it
    were an answer. The direction of harm is safe — ``uncertain`` flags
    rather than excludes — but the remedy for a network blip is to re-run,
    and re-running is exactly what a negative cache entry defeats. The raw
    SDK exception text rode along into the exported bundle as well.

    Two rules, both on the write side only:

    ``error`` is judged by *presence*, not truthiness. It is set from
    ``str(e)``, and an exception raised with no message stringifies to the
    empty string; the key is the marker of a terminal failure, whatever it
    holds.

    ``used`` must be explicitly true. The read side defaults a missing
    ``used`` to True, for cache files written before the field existed, and
    that asymmetry is deliberate: an entry that does not record a model
    answer is not evidence of one, and the cost of refusing to cache it is
    one more API call rather than a permanent false verdict.

    ``decision_rejected`` extends the same rule in wave 8 (F-90). An answer
    the parser could not read is not a verdict either, and caching it is
    worse here than for the other two: the entry is served on every later
    run at zero cost, and a cache hit never reaches the parser, so the log
    line F-90 exists to produce would be emitted exactly once and never
    again. The condition would go back to being invisible by the second
    run — which is the defect, reintroduced through the cache. ``used``
    stays True on such a record, because the model *did* answer; what it
    did not do is answer in a vocabulary this stage reads.

    ``field_rejected`` is deliberately **not** a reason to refuse. The
    record still carries a decision the gate can act on; only the quote's
    validation target was substituted. That is F-136, and it is counted
    rather than acted on.

    This governs what a run *writes*. Entries arriving in ``cache_in`` are
    carried through untouched — a bundle captured before this fix keeps
    whatever it has, because silently deleting a user's accumulated cache
    would be its own kind of data loss (and would move the goldens).
    """
    if not isinstance(ev, dict):
        return False
    if "error" in ev:
        return False
    if "decision_rejected" in ev:
        return False
    return ev.get("used") is True


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
