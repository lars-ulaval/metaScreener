
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
import math
import os
import re
import time
import dataclasses as _dc
from collections import Counter
from hashlib import sha256
from time import perf_counter
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from plugins._common.run_estimate import remember_call


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


OPENAI_BASE_URL_ENV = "OPENAI_BASE_URL"
"""The environment variable that selects the endpoint.

Named rather than inline because three call sites read it and one of them
is a cache-key input (F-89); a typo in any of them would silently split or
merge cache namespaces.
"""

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
"""The endpoint used when nothing selects one.

**No trailing slash, and that is load-bearing.** This string is hashed
into the cache key, and ``https://api.openai.com/v1`` and
``https://api.openai.com/v1/`` are different pre-images. The slash-less
form is the one the SDK's own constructor names, the one
``docs/installation.md`` documents, and the one §B4.5 of
``06_llm_integration.md`` measured the migration against — so it is the
form that keeps this repository's key set equal to the measured one.

Note that ``str(client.base_url)`` is **not** this string: httpx
normalises it to ``https://api.openai.com/v1/``. That normalised value is
deliberately not what reaches the key. See :func:`_cache_key`.
"""


def resolve_openai_base_url(stage: str = "") -> str:
    """The endpoint this process will talk to, decided by this repository.

    **Wave 11 session C: the decision itself moved to
    ``settings.resolve_stage``, and this function takes a stage.**

    ``stage=""`` is the application level and resolves to exactly what
    this function resolved to before per-stage overrides existed — which
    is what keeps the golden replays valid, and is asserted directly. A
    named stage additionally honours ``stages[stage]["endpoint"]``.

    The decision moved because it now has to be made about a *pair*: with
    a per-stage endpoint the provider and the endpoint can be moved
    independently, so the question "does this need a key?" stopped being
    answerable from the provider string. Keeping the endpoint decision
    next to the store is what lets one function answer both without a
    second copy of either.

    F-92. The local-provider capability used to work only because the
    vendor SDK's ``OpenAI.__init__`` falls back to
    ``os.environ.get("OPENAI_BASE_URL")``. No repository line read, wrote,
    validated, logged or recorded that variable; ``openai`` is pinned only
    ``>=1.40.0``; and no test asserted the resolved endpoint. So an SDK
    major that dropped the fallback — or a well-meant refactor adding an
    explicit ``base_url="https://api.openai.com/v1"`` — would have routed a
    "local" run to the paid API with the whole suite green. The failure is
    billable rather than merely wrong.

    Blank is treated as absent. ``metascreener/main.py::_load_env_file``
    already refuses to export an empty value, but the variable can also
    come from the shell, and "set to nothing" must not become a third
    endpoint namespace distinct from both "unset" and any real URL.

    Whitespace is stripped because it is not a routing difference; leaving
    it in would give one server two cache namespaces. Everything else is
    returned **verbatim** — see :func:`_cache_key` for why no further
    normalisation is applied.

    This is the single place the endpoint is decided. :func:`_cache_key`'s
    callers and :func:`_openai_client_for` both read it from here, so the
    key and the client cannot disagree about where a run went.

    **Wave 11 adds the settings store as the first source, and it must be
    first.** The store is what a GUI choice writes, so a stale
    ``OPENAI_BASE_URL`` in the environment winning over it would make the
    control the user just operated do nothing — a GUI-first defect of the
    same family as F-91. The order is therefore: an explicitly stored
    endpoint, then the environment variable, then the vendor default.

    An *unconfigured* install stores nothing, so this reduces exactly to
    the previous expression — which is what keeps the golden replays
    valid, since they pop ``OPENAI_BASE_URL`` and rely on reaching
    ``DEFAULT_OPENAI_BASE_URL``. Session A's review found the earlier
    version of this wave shipping ``provider="local"`` in the defaults
    while nothing read ``endpoint``, so a run the store called local went
    to the paid vendor. Reading the endpoint here is one half of that fix;
    not presuming a provider (``settings.defaults``) is the other.
    """
    return _stage_config(stage).endpoint


def llm_exclusion_allowed(stage: str = "") -> bool:
    """Whether this stage's verdicts may REMOVE a record (F-145).

    ``False`` means flag-only: the model may mark a record for human
    review, and may not take it out of the review. Off by default for the
    keyless providers — local and custom — because local models were
    measured producing 40, 43 and 4 exclusions on a corpus where the
    vendor model produced one correct one — all but one per llama3.2 run,
    and all four from qwen2.5, being records the audited run kept — every
    one of them carrying a verbatim quote above threshold. See
    ``stage_state.exclusion_allowed`` for the measurement and the rule.

    Resolved through ``_stage_config`` for the same reason
    ``resolve_openai_base_url`` is: one place decides, and a second
    derivation would be two representations of one fact. It degrades with
    the store — an unreadable settings file resolves to ``provider=""``,
    which is not a keyless provider and so is not restricted. That is the
    honest reading rather than a hole: a store in that state also fails
    ``llm_readiness`` at ``NOT_CONFIGURED``, so no run reaches this
    question, and treating an unknown provider as a local model would move
    the golden replays, which resolve exactly that provider.
    """
    return _stage_config(stage).allow_llm_exclusion


def _stage_config(stage: str = ""):
    """The resolved configuration of ``stage``, or of the application.

    Unreadable or unavailable settings must never change where a run is
    sent, so a failure here degrades to an empty store — which resolves
    to the environment and then the vendor default, exactly the
    behaviour that predates the store.
    """
    from plugins._common.settings import resolve_stage

    try:
        from plugins._common.settings import load_settings
        cfg = load_settings()
    except Exception:
        cfg = {}
    return resolve_stage(
        cfg, stage,
        env_endpoint=os.environ.get(OPENAI_BASE_URL_ENV, ""),
        env_api_key=os.environ.get("OPENAI_API_KEY", ""),
    )


def _openai_client_for(stage: str = ""):
    """Construct the OpenAI client for one stage.

    Extracted so cancellation and batching can be tested without a live
    key or network. Nothing else about the call path changed.

    F-92: ``base_url=`` is passed **explicitly**, from
    :func:`resolve_openai_base_url`. Passing it is the point — not merely
    arriving at the same answer the SDK's fallback would have produced.
    Once it is passed, the SDK's environment fallback is unreachable for
    this project, so the declared floor's behaviour stops being
    load-bearing and the unresolved question of whether ``openai==1.40.0``
    has that fallback stops mattering.

    **Wave 11 session C reverses this function's "kept zero-argument on
    purpose" decision, and records the reversal rather than quietly
    dropping it.** The reason given was that a parameter would break the
    twelve test doubles binding ``lambda: client`` *to no benefit*,
    because the endpoint was process state. Per-stage endpoints are the
    benefit: without a stage this function cannot build a client for the
    stage that is actually running, and the alternative — a module-level
    "current stage" — would be wrong the moment EL and IL run at once,
    which two tabs make ordinary. ``stage`` defaults to the application
    level, so every direct caller keeps working; the doubles were widened
    to ``lambda *a, **k: client`` in the same commit.
    """
    from openai import OpenAI  # type: ignore
    from plugins._common.settings import placeholder_key_for

    cfg = _stage_config(stage)

    # F-117. The SDK refuses to construct with an empty ``api_key`` even
    # against a server that never reads it, so a local run would die here
    # with a credential error for a credential it does not need. That
    # requirement is the application's to satisfy, not the user's — before
    # this, the NO_KEY message told every user to invent a placeholder.
    # A real key is never replaced, and ``openai`` is never given one.
    #
    # Session C: the placeholder is decided on the resolved PAIR. A stage
    # whose endpoint bills must not be handed the literal string "local"
    # as its credential just because its provider field says so.
    return OpenAI(
        api_key=placeholder_key_for(cfg.provider, cfg.api_key,
                                    endpoint=cfg.endpoint),
        base_url=cfg.endpoint,
    )


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

def _has_openai_key(stage: str = "") -> bool:
    """Whether this stage's key requirement is satisfied.

    **F-117, and a regression this wave introduced and then caught.** This
    used to be a presence check on ``OPENAI_API_KEY``. Once
    ``llm_readiness`` became provider-aware, a local run reported
    **ready** — a local server authenticates nothing — while this gate,
    one layer down, still demanded a key and returned ``{}`` for every
    criterion. The Run button would have been live, every record would
    have gone unscreened, and the status line would have read "done":
    **F-93's exact harm shape, reached by another route.** The readiness
    layer and the engine must answer the same question or the gate is
    decorative.

    The name is kept deliberately: ten test doubles across the suite bind
    this name with ``lambda: True``, and renaming it would break them all
    for no behavioural gain. What it *means* has widened twice — F-117
    made it a question about the provider, and session C makes it a
    question about the resolved **pair**, so a stage whose endpoint
    override points at the paid vendor is asked for a key however keyless
    its provider claims to be. ``stage=""`` is the application level.
    """
    from plugins._common.stage_state import key_ok

    cfg = _stage_config(stage)
    return key_ok(provider=cfg.provider, api_key=cfg.api_key,
                  endpoint=cfg.endpoint)

def _sample_of(counts: "Counter", limit: int = 5) -> str:
    """Render the commonest few keys of a tally for a log line.

    Bounded on purpose: the values are model output, so an unbounded render
    would put arbitrary text of arbitrary length into the log pane.
    """
    head = ", ".join(f"{k!r}×{n}" for k, n in counts.most_common(limit))
    rest = len(counts) - min(limit, len(counts))
    return head + (f", and {rest} other value(s)" if rest > 0 else "")

NO_ANSWER_REPLY_CAP = 500
"""Characters of a no-answer reply retained per distinct shape (F-194).

**Not 200, and the number that rules 200 out is measured rather than felt.**
``08_harmoniser_llm_failure.md`` records a 200-character window ending
mid-token at ``"tar``, which read as a truncated reply; the first reading of
that incident concluded exactly that and was wrong (F-186). 500 holds a
complete single-record verdict object, a refusal sentence, and enough of a
truncated object to see where it stopped.
"""

NO_ANSWER_REPLY_KINDS = 20
"""Distinct reply shapes stored. Beyond this, records are counted into
``no_answer_replies_dropped`` rather than allocating.

The bound is what makes the tally a fixed cost: 20 x 500 characters is
~10 KB whatever the corpus size, where one copy per record is 1,552 copies
on a 776-record corpus with two criteria.
"""

NO_ANSWER_REPLY_SAMPLE = 5
"""Shapes rendered in the log line. Matches :func:`_sample_of`'s own default."""


def _finish_reason_of(resp: Any) -> Optional[str]:
    """``finish_reason``, or ``None`` when the response does not carry one.

    **Defensive by design, not by caution.** Eleven ``_FakeResponse`` doubles
    across the suite build a choice as ``type("C", (), {"message": msg})`` and
    carry neither this field nor ``usage``; that minimal request-and-response
    shape is the portability property **F-107** asks the project to keep, and
    widening eleven doubles to read two fields would spend it. A server that
    reports no ``finish_reason`` is also a real condition, and ``None`` records
    it as one.
    """
    try:
        return getattr(resp.choices[0], "finish_reason", None)
    except Exception:
        return None


def _completion_tokens_of(resp: Any) -> Optional[int]:
    """``usage.completion_tokens``, or ``None``. See :func:`_finish_reason_of`."""
    try:
        v = getattr(getattr(resp, "usage", None), "completion_tokens", None)
        return int(v) if v is not None else None
    except Exception:
        return None


def _remember_no_answer_reply(stats: Optional[Dict[str, Any]], raw_reply: Any,
                              resp: Any, n_records: int) -> None:
    """Record what came back for records the parse loop did not reach (F-194).

    Called only from the omission back-fill, where ``resp`` exists. The
    terminal-failure back-fill has no reply to keep -- the call raised -- and
    already records ``error`` and ``error_class``; nothing here touches it.

    **A tally, not a copy per record.** 279 unanswered records in the run that
    raised F-194 carried *one* distinct reply, ``[]``; storing it 279 times
    answers nothing that the shape and a count do not. ``count`` is therefore
    the number of **records left unanswered by a reply of this shape**, which
    is the same quantity ``no_answer`` counts, so the two can be read against
    each other.

    **A reply with no content at all is counted apart.** ``txt = (content or
    "[]")`` in the caller makes a ``None`` content indistinguishable from a
    literal empty list downstream, and they are different situations -- a
    server that returned nothing, and a model that returned "none of them".
    Keeping them apart here is the whole point of the row.

    Nothing is written to the cache: ``_is_cacheable_evidence`` is untouched
    and a no-answer stays uncacheable, which is **F-87** and is correct.
    Reversing it is a separate argued decision, not a side effect of this one.
    """
    if stats is None or n_records <= 0:
        return

    # Recorded before the kinds cap can return early: the largest reply a
    # no-answer call produced is the number that separates "returned two
    # tokens" from "returned eight hundred and was cut off", and it must not
    # depend on whether that reply's shape happened to fit the tally.
    ct = _completion_tokens_of(resp)
    if ct is not None:
        prev = stats.get("no_answer_max_completion_tokens")
        if prev is None or ct > prev:
            stats["no_answer_max_completion_tokens"] = ct

    if raw_reply is None:
        stats["no_answer_replies_absent"] = int(
            stats.get("no_answer_replies_absent", 0) or 0) + n_records
        return

    text = _safe_str(raw_reply)
    over = len(text) > NO_ANSWER_REPLY_CAP
    key = text[:NO_ANSWER_REPLY_CAP]
    tally = stats.setdefault("no_answer_replies", {})

    entry = tally.get(key)
    if entry is None:
        if len(tally) >= NO_ANSWER_REPLY_KINDS:
            stats["no_answer_replies_dropped"] = int(
                stats.get("no_answer_replies_dropped", 0) or 0) + n_records
            return
        entry = tally[key] = {"count": 0, "truncated": False, "finish_reason": []}

    entry["count"] += n_records
    # Two distinct long replies sharing a prefix collapse onto one key. That
    # is acceptable -- they are the same shape -- but only because this flag
    # tells the reader the key is a prefix and not the reply's end. F-186 is
    # what happens when it does not.
    if over:
        entry["truncated"] = True

    fr = _finish_reason_of(resp)
    if fr not in entry["finish_reason"]:
        entry["finish_reason"].append(fr)
        entry["finish_reason"].sort(key=lambda v: (v is not None, _safe_str(v)))


def _no_answer_reply_sample(stats: Optional[Dict[str, Any]],
                            limit: int = NO_ANSWER_REPLY_SAMPLE) -> str:
    """Render the commonest no-answer replies for a log line, via _sample_of."""
    tally = (stats or {}).get("no_answer_replies") or {}
    c: "Counter" = Counter({k: int(v.get("count", 0) or 0)
                            for k, v in tally.items()})
    absent = int((stats or {}).get("no_answer_replies_absent", 0) or 0)
    if absent:
        c["<no content>"] = absent
    return _sample_of(c, limit) if c else "none recorded"


def chunked(seq: Sequence[Any], n: int):
    n = max(1, int(n))
    for i in range(0, len(seq), n):
        yield seq[i:i+n]


# --------------------------- LLM utilities ------------------------------------

def _strip_code_fence(text: str) -> str:
    """Remove a Markdown code fence, if the reply is wrapped in one.

    Local models emit fenced JSON routinely, and this is the one place
    that knowledge is written down. Extracted from
    ``_parse_llm_json_array`` in wave 12 so that
    ``_parse_llm_json_object`` shares it rather than restating it: two
    fence-stripping rules that could drift is F-69's shape, and the
    harmoniser having no fence handling *at all* is the defect F-146
    closes.
    """
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    return t


def _parse_llm_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Robust parse of a JSON **object**. ``None`` when there is none.

    The object-shaped sibling of ``_parse_llm_json_array``: the harmoniser
    asks for ``{"rows": [...]}`` where EL and IL ask for a bare list, so
    the two response contracts need two parsers but only one set of
    tolerances.

    Returns ``None`` rather than ``{}`` on failure, so that the caller can
    tell "the model sent no object" from "the model sent an empty one" and
    raise an error naming the real problem. Returning a falsy dict here is
    how the defect this was written for stayed invisible.
    """
    t = _strip_code_fence(text)

    try:
        val = json.loads(t)
        if isinstance(val, dict):
            return val
    except Exception:
        pass

    # Extract the first balanced-looking object, for a model that wrapped
    # its answer in prose.
    m = re.search(r"\{.*\}", t, flags=re.S)
    if m:
        try:
            val = json.loads(m.group(0))
            if isinstance(val, dict):
                return val
        except Exception:
            pass
    return None


def _parse_llm_json_array(text: str) -> List[Dict[str, Any]]:
    """
    Robust parse of a JSON array. Accepts:
      - pure JSON list
      - fenced code block
      - extra text before/after (extract first [...] block)
    """
    t = _strip_code_fence(text)

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


# --------------------------- context budget (F-154) ---------------------------

CONTEXT_WINDOW_DEFAULT = 4096
"""The token window assumed when the user has not said otherwise.

The wave-15b probes measured this server's serving window at exactly 4,096
(a 3,537-token prompt passed untouched; a 7,254-token prompt was truncated),
and measured what overflow costs: **the excess is not trimmed — the server
keeps the LAST ~half-window of tokens and drops the front**, system message
and criterion included, then answers confidently about the remainder. That
is why the guard below refuses rather than warns. User-settable as the
application-level ``context_window`` key in the settings store
(``update_settings(context_window=8192)``); values below 512 are treated as
typos and ignored.
"""

HOSTED_CONTEXT_WINDOW_DEFAULT = 128_000
"""The default window when the resolved pair points at a paid vendor
endpoint (F-203, wave 15c).

Basis is EXTERNAL, and deliberately cited rather than measured here:
OpenAI's model documentation states a 128,000-token context window for
the gpt-4o family, including the shipped default ``gpt-4o-mini``
(platform.openai.com/docs/models, read 2026-08). No in-repo probe
establishes it — the wave-15c sweep confirmed the repository carries no
hosted-window measurement — and the drift check covers the estimator
against any tokenizer at run time either way. Applies only when the
provider is CHOSEN and ``stage_state.is_paid_vendor`` says the resolved
endpoint bills (see ``resolve_context_window``); a DeepSeek or other
non-listed hosted endpoint conservatively keeps the local default and a
loud refusal naming the setting, because widening the PAID_VENDOR_HOSTS
money vocabulary to fix a window default would change who is asked for
a key."""

CHARS_PER_TOKEN = 4.5
"""The estimator's divisor, with its calibration on the record (wave 15b,
probe 1 — the server's own ``usage.prompt_tokens`` for prompts rendered by
the real builder over the frozen 147-record corpus):

    chars   measured tokens   chars/token
     2,699        600            4.50      (batch-1 payload)
    10,033      2,240            4.48      (batch-5 payload)
     8,146      1,621            5.03      (batch-10 payloads...)
    12,627      2,518            5.02
    14,307      2,930            4.88
    15,288      2,942            5.20
    16,754      3,204            5.23
    17,515      3,537            4.95

4.5 is near-exact on small payloads and ~10 % conservative on large ones —
conservative in the only safe direction for a refusing guard. The one hole a
constant cannot close, a tokenizer denser than the estimate on an untested
provider, is closed at run time by the drift check in
``run_m1_llm_for_criterion``: the first real call's ``usage.prompt_tokens``
is compared against this estimator and the run aborts if reality exceeds it.
"""

FRAMING_TOKENS = 30
"""Chat-template framing allowance per request (role markers, specials)."""

REPLY_RESERVE_PER_VERDICT = 80
"""Per-verdict completion reserve. Wave-12's worst measured reply was
327–491 tokens for five verdicts (65–98 each); 80 sits inside that band."""


def estimate_prompt_tokens(chars: int) -> int:
    """Conservative token estimate for a rendered prompt of ``chars``."""
    return int(math.ceil(chars / CHARS_PER_TOKEN)) + FRAMING_TOKENS


def _load_settings_or_empty() -> Dict[str, Any]:
    from plugins._common.settings import load_settings
    return load_settings()


def _hosted_default_applies(stage: str) -> bool:
    """F-203: whether the hosted default governs ``stage``'s fallback.

    Keyed on the RESOLVED PAIR via ``is_paid_vendor``, never the provider
    label — the drift check aborts only when reality *exceeds* the
    estimate, and a truncating local server reports *fewer* tokens, so a
    hosted-sized default aimed at a local endpoint would be caught by
    nothing at run time. The provider-chosen guard keeps an unconfigured
    install (provider ``""``, vendor endpoint as resolution fallback) at
    the conservative local default; ``llm_readiness`` blocks such a run
    anyway, but this function must not hand 128k to nothing-configured
    on its own. Errors resolve to False: the local default is the safe
    side.
    """
    try:
        cfg = _stage_config(stage)
    except Exception:
        return False
    if not (getattr(cfg, "provider", "") or "").strip():
        return False
    from plugins._common.stage_state import is_paid_vendor
    return bool(is_paid_vendor(getattr(cfg, "endpoint", "")))


def resolve_context_window(stage: str = "") -> int:
    """The context window this run budgets against.

    Application-level, like the endpoint, because the window is a property
    of the server. A stored ``context_window`` >= 512 wins unconditionally;
    the DEFAULT is per-provider since wave 15c (F-203): 4,096 — the
    measured local serving default — unless the stage resolves to a paid
    vendor endpoint, which gets :data:`HOSTED_CONTEXT_WINDOW_DEFAULT`.
    Degrades to the local default on an unreadable store, per the same
    rule ``_stage_config`` follows. Detection via provider metadata is
    deliberately NOT attempted here — F-107: a provider-specific call in
    the run path narrows portability, and the drift check already detects
    a lying window universally.
    """
    try:
        cfg = _load_settings_or_empty()
    except Exception:
        return CONTEXT_WINDOW_DEFAULT
    v = cfg.get("context_window")
    if isinstance(v, bool) or not isinstance(v, int) or v < 512:
        return (HOSTED_CONTEXT_WINDOW_DEFAULT
                if _hosted_default_applies(stage) else
                CONTEXT_WINDOW_DEFAULT)
    return int(v)


class ContextBudgetExceeded(RuntimeError):
    """Raised by the engines BEFORE the first call when a run cannot fit.

    Reaches the user through the Views' existing run-failed error path; the
    message is composed here (testably) and follows F-173's register: name
    the thing, give the numbers, tell no conclusion.
    """


class TokenEstimateDrift(RuntimeError):
    """Raised after the FIRST real call of a run when the server reports
    more prompt tokens than the estimator predicted — the estimator is
    optimistic for this model's tokenizer, so the pre-run size check the
    run was admitted under cannot be trusted. One call has been spent."""


@_dc.dataclass(frozen=True)
class ContextBudgetReport:
    ok: bool
    window: int
    batch_size: int
    reserve: int                 # of the worst call
    worst_estimate: int          # prompt tokens, worst call
    worst_criterion: str
    worst_batch_index: int       # 0-based within its criterion
    n_batches: int               # per criterion
    max_safe_batch: int          # largest batch size that fits; 0 = none
    message: str                 # the refusal text (empty when ok)


def _worst_call(criteria, items, batch_size, trunc_chars, build_messages):
    worst = (-1, "", -1, 0)      # (est+reserve, cid, batch_idx, est)
    n_batches = 0
    for pack in criteria:
        for bi, batch in enumerate(chunked(items, max(1, int(batch_size)))):
            n_batches = bi + 1
            chars = sum(len(m.get("content", ""))
                        for m in build_messages(pack, list(batch), trunc_chars))
            est = estimate_prompt_tokens(chars)
            tot = est + REPLY_RESERVE_PER_VERDICT * len(batch)
            if tot > worst[0]:
                worst = (tot, pack.get("id", "?"), bi, est)
    return worst, n_batches


def check_context_budget(*, criteria, items, batch_size, trunc_chars,
                         build_messages, window,
                         hosted: bool = False,
                         noun: str = "record") -> ContextBudgetReport:
    """Render every prompt the run would send and budget it against
    ``window``. Whole-corpus and pre-run on purpose: rendering is cheap and
    exact (the wave-15b reconstruction proved byte-fidelity), and the user
    should learn at zero cost, not forty calls in.

    The refusal threshold is ``estimate + reserve > window`` — landing
    exactly on the window passes.

    ``hosted`` (F-203, wave 15c) selects the refusal message's wording
    only, never its arithmetic. The local message describes the measured
    Ollama overflow (last half-window kept, front dropped); a hosted
    endpoint's overflow behaviour is not established here, so that
    branch states the constraint and the setting remedy without
    asserting an unmeasured mechanism. The engines pass
    ``is_paid_vendor(endpoint)`` — the resolved pair, the same
    instrument the default window keys on.
    """
    window = int(window)
    (worst_tot, worst_cid, worst_bi, worst_est), n_batches = _worst_call(
        criteria, items, batch_size, trunc_chars, build_messages)
    reserve = worst_tot - worst_est
    if worst_tot <= window:
        return ContextBudgetReport(
            ok=True, window=window, batch_size=int(batch_size),
            reserve=reserve, worst_estimate=worst_est,
            worst_criterion=worst_cid, worst_batch_index=worst_bi,
            n_batches=n_batches, max_safe_batch=int(batch_size), message="")

    # derive the largest batch size that fits every request of THIS corpus
    max_safe = 0
    for n in range(int(batch_size) - 1, 0, -1):
        (tot_n, _c, _b, _e), _nb = _worst_call(
            criteria, items, n, trunc_chars, build_messages)
        if tot_n <= window:
            max_safe = n
            break

    if hosted:
        mechanism = (
            f"The {window}-token figure is this application's "
            f"'context_window' setting, not a measurement of the endpoint: "
            f"hosted models generally serve far larger windows than the "
            f"setting assumes. There is no server of yours to restart — if "
            f"your model's documentation states a larger context length, "
            f"set 'context_window' to it.\n\n")
        closing = (f"\n\nThe setting must not exceed the context length "
                   f"the endpoint actually serves.")
        no_fit_tail = (f"A lower truncation limit or a larger "
                       f"'context_window' setting would change that.")
    else:
        mechanism = (
            f"An overflowing request is not trimmed to fit: the server "
            f"keeps roughly the last {window // 2} tokens — half the "
            f"window, however long the request was — and drops everything "
            f"before them, instructions and criterion included, then "
            f"answers about the remainder.\n\n")
        closing = (f"\n\nThe window is the application-level "
                   f"'context_window' setting; the server's own window "
                   f"must be at least as large.")
        no_fit_tail = (f"A lower truncation limit or a larger server "
                       f"window would change that.")

    # ``noun`` (wave 15d): the harmoniser budgets CRITERIA per call, not
    # records per batch, and its refusal must say so. The default keeps
    # the EL/IL message byte-identical; the criterion-id clause is
    # dropped on the non-record path because the "criterion" there is a
    # synthetic pack covering the whole table.
    if noun == "record":
        numbers = (
            f"Criterion {worst_cid}, batch {worst_bi + 1} of {n_batches} "
            f"at batch size {int(batch_size)}, measures an estimated "
            f"{worst_est} prompt tokens plus a {reserve}-token reply "
            f"reserve — {worst_tot} in total against the {window}-token "
            f"window.\n\n")
    else:
        numbers = (
            f"Call {worst_bi + 1} of {n_batches} at {int(batch_size)} "
            f"{noun}s per call measures an estimated {worst_est} prompt "
            f"tokens plus a {reserve}-token reply reserve — {worst_tot} "
            f"in total against the {window}-token window.\n\n")

    msg = (
        f"This run was not started: the largest request it would send does "
        f"not fit the configured {window}-token context window.\n\n"
        + numbers
        + mechanism
        + (f"At this window, the largest batch size that fits every request "
           f"for this corpus is {max_safe}."
           if max_safe else
           f"No batch size fits this corpus at this window — a single "
           f"{noun}'s request already exceeds it. " + no_fit_tail)
        + closing
    )
    return ContextBudgetReport(
        ok=False, window=window, batch_size=int(batch_size), reserve=reserve,
        worst_estimate=worst_est, worst_criterion=worst_cid,
        worst_batch_index=worst_bi, n_batches=n_batches,
        max_safe_batch=max_safe, message=msg)


def enforce_context_budget(**kw) -> ContextBudgetReport:
    """:func:`check_context_budget`, raising :class:`ContextBudgetExceeded`
    on refusal. One call per engine run, before the criterion loop."""
    rep = check_context_budget(**kw)
    if not rep.ok:
        raise ContextBudgetExceeded(rep.message)
    return rep


# --------------------------- answer vocabularies ------------------------------

DECISION_VOCABULARY: Tuple[str, ...] = ("meet", "not_meet", "uncertain")
"""The only ``decision`` values the evidence gate can act on.

F-90, F-108. Named rather than inline so the set has one home; the prompt
still restates it in prose twenty lines away, which is F-108 and is not
fixed here.
"""

FIELD_VOCABULARY: Tuple[str, ...] = ("title", "abstract", "keywords")

_DECISION_SEPARATORS = re.compile(r"[\s_\-]+")


def _response_format_for(n: int) -> Dict[str, Any]:
    """The ``response_format`` for a batch of exactly ``n`` records (F-191,
    F-197).

    **The cardinality is the point.** Shape alone kills the batch-1 failure
    — ``[]`` stops being expressible — but only ``minItems == maxItems == n``
    reaches the batch-5 failure, a reply that answers one record of five and
    omits the rest. Both were measured (FIX_WAVE_14C_BATCH_INVARIANCE.md §2
    and the replay: 31/31 previously-omitted pairs filled, with the
    unconstrained controls reproducing the omission exactly).

    Built per call from the batch actually being sent, because the adaptive
    split rewrites ``cur_batch``: a halved batch carrying the original
    count's schema would ask the server for objects that cannot exist.

    The enums are the parser's own vocabularies rather than a third hand
    copy — F-108/F-109's shape, not repeated. A decision outside
    :data:`DECISION_VOCABULARY` and a field outside
    :data:`FIELD_VOCABULARY` stop being expressible on this path; the
    normalisation and rejection code stays, because the unconstrained
    fallback still needs it.

    The **messages are untouched** on purpose: the constraint rides on the
    request parameter, so the rendered prompt — which the cache key hashes —
    is byte-identical under both shapes. What changes the key is
    ``PROMPT_VERSION``, bumped with this wave, which is the deliberate,
    greppable lever ``_cache_key``'s docstring reserves for a semantic
    change that does not move a byte of the template.
    """
    verdict = {
        "type": "object",
        "properties": {
            "a_id": {"type": "string"},
            "decision": {"type": "string", "enum": list(DECISION_VOCABULARY)},
            "confidence": {"type": "number"},
            "field": {"type": "string", "enum": list(FIELD_VOCABULARY)},
            "quote": {"type": "string"},
            "span": {"type": "array", "items": {"type": "integer"},
                     "minItems": 2, "maxItems": 2},
        },
        "required": ["a_id", "decision", "confidence", "field", "quote",
                     "span"],
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "verdicts",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "results": {"type": "array", "items": verdict,
                                "minItems": int(n), "maxItems": int(n)},
                },
                "required": ["results"],
            },
        },
    }


def _response_format_rejected(e: BaseException) -> bool:
    """Whether this exception is a server refusing ``response_format`` itself.

    **Checked before ``_classify_llm_error``, and that ordering is measured,
    not stylistic** (wave 14b): a real rejection body reads *"unsupported
    parameter 'response_format'; only max_tokens allowed"*, and
    ``max_tokens`` matches ``_OVERSIZE_RE`` — so the classifier calls it
    ``oversize``, salvageable, and the ladder would halve the batch and step
    down the truncation against a refusal no batch size can cure.

    Deliberately narrow: the parameter's name must appear in the message.
    A schema-*validation* failure, a genuine oversize, or any other 400
    falls through to the classifier unchanged — this predicate exists for
    exactly one condition, the F-107 provider that does not speak
    structured output at all.
    """
    try:
        msg = str(e).lower()
    except Exception:
        return False
    if "response_format" not in msg:
        return False
    types_ = _openai_error_types()
    t = types_.get("BadRequestError")
    if t is not None and isinstance(e, t):
        return True
    status = getattr(e, "status_code", None)
    try:
        return status is not None and int(status) == 400
    except Exception:
        return False


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
    return {"calls_made": 0, "calls_failed": 0, "batches_failed": 0,
            # F-194. What came back for the records the parse loop did not
            # reach. A no-answer is refused a cache line (F-87) and carries
            # seven fixed keys in the evidence record, so before this the
            # reply was unrecoverable from every artefact the run wrote.
            # Bounded in both dimensions -- see NO_ANSWER_REPLY_CAP and
            # NO_ANSWER_REPLY_KINDS -- because the value is model output of
            # arbitrary length and the corpus can be large.
            "no_answer_replies": {},
            "no_answer_replies_absent": 0,
            "no_answer_replies_dropped": 0,
            "no_answer_max_completion_tokens": None,
            # F-197 / F-107. Which request shape this run actually used:
            # "json_schema" until a server rejects the parameter, then
            # "unconstrained" for the rest of the run. Reaches the manifest
            # through _run_report's report.update(call_stats), so a bundle
            # records which path produced its verdicts — without this, two
            # runs of the same version against different servers are
            # indistinguishable in the artefact (F-88's argument, applied
            # to the one thing wave 14c changes).
            "request_shape": "json_schema",
            # F-197. Batches whose first reply omitted records, and the
            # records still unanswered after their one re-ask. The second
            # is the residue design §3.2 refuses to back-fill silently.
            "reasks_made": 0,
            "no_answer_after_reask": 0,
            # F-154 / wave 15b. Whether the first-call drift check has run
            # for this run. Run-scoped through this dict, like request_shape.
            "drift_checked": False}


def _bump(stats: Optional[Dict[str, int]], key: str) -> None:
    if stats is not None:
        stats[key] = int(stats.get(key, 0)) + 1


def llm_provenance(*, model: str, endpoint: str, temperature: float,
                   prompt_version: str, trunc_chars: int,
                   batch_size: int,
                   # Required since wave 15c (F-203): the keyword default
                   # was the number's second copy, and a caller omitting
                   # it would stamp 4096 whatever the provider-aware
                   # default resolved. Both engines pass explicitly.
                   context_window: int) -> Dict[str, Any]:
    """Which engine produced this run's decisions (F-88).

    Shared by both stages so the two cannot drift into recording different
    field sets — the same reason the four near-identical EL/IL export
    copies became one writer under F-05.

    **These are observations, not settings.** Every value is what the run
    actually used, threaded from the engine rather than re-read from a
    widget or the environment at export time: the model the user typed may
    have been edited between the run and the export, and the endpoint is
    resolved once per run precisely so that two consumers cannot disagree
    about it (F-92).

    Why these six. The first four are §B8.1's tier 1 — the minimum needed
    to say which engine answered. ``trunc_chars`` is here because of the
    asymmetry wave 8 surfaced: **"the model answered" and "the model was
    shown something" are different claims**, and the run report records
    only the first. A negative ``trunc_chars`` makes the builder's
    ``s[:trunc_chars]`` a negative slice, so fields are *emptied* rather
    than truncated, and the resulting run report is byte-identical to a
    healthy one — four records, four answered, none failed. Recording what
    the model was shown is what keeps ``answered`` interpretable.
    ``batch_size`` completes the set the capture harness already records
    in its ``_invocation`` envelope, so a manifest and a golden describe a
    run in the same terms.

    Not a call fingerprint (F-135): this is per *run*, it is written only
    into the manifest, and it does not touch a cache value.
    """
    return {
        "model": _safe_str(model),
        "endpoint": _safe_str(endpoint),
        "temperature": float(temperature),
        "prompt_version": _safe_str(prompt_version),
        "trunc_chars": int(trunc_chars),
        "batch_size": int(batch_size),
        # F-154, wave 15b: a run that may have been budgeted against a
        # window is not fully specified without the window. Recorded from
        # resolve_context_window at run start, like the endpoint.
        "context_window": int(context_window),
    }


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

    The ``stage`` keyword (e.g. ``"EL"`` or ``"IL"``) names the log prefix and
    the courtesy ``"stage"`` field on emitted progress events — **and, from
    wave 11 session C, decides which configuration this run uses.** It is
    passed to ``_has_openai_key`` and ``_openai_client_for`` so a per-stage
    endpoint or model override is honoured by the gate and by the client
    alike. That it was already threaded here is why no new parameter was
    needed; what changed is that it stopped being decorative.

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
    if not _has_openai_key(stage):
        if log: log(f"{log_prefix} OPENAI_API_KEY not visible in environment; skipping.\n")
        return {}

    try:
        client = _openai_client_for(stage)
    except Exception as e:
        if log: log(f"{log_prefix} OpenAI client import/init failed: {e}\n")
        return {}

    def _check_cancel():
        if cancel_token is not None and bool(getattr(cancel_token, "cancelled", False)):
            raise _Cancelled()
        if cancel_token is not None and bool(getattr(cancel_token, "is_set", lambda: False)()):
            raise _Cancelled()

    # F-151. Where a *measured* rate comes from, so the pre-run
    # confirmation can offer a duration instead of a guess. Resolved once
    # here rather than per call: it is a settings read, and the endpoint
    # cannot change mid-run.
    _rate_endpoint = resolve_openai_base_url(stage)

    # F-197. Sticky per RUN, not per criterion: the stats dict is the one
    # object that accumulates across every criterion of a stage, so a server
    # that rejected `response_format` once is not re-probed by the next
    # criterion. With no stats dict there is no channel and the default
    # stands per call.
    use_schema = stats is None or \
        stats.get("request_shape", "json_schema") != "unconstrained"

    # F-154 / wave 15b: the drift check needs the estimate of the call the
    # response answers; a mutable cell rather than a return-shape change,
    # because fourteen tests pin _call_once's callers on the response alone.
    _last_estimate = {"v": 0}
    _drift_done = {"v": False}

    def _call_once(batch: List[Dict[str, Any]], cur_trunc: int):
        msgs = build_messages(criterion, batch, cur_trunc)
        _last_estimate["v"] = estimate_prompt_tokens(
            sum(len(m.get("content", "")) for m in msgs))
        # Counted here rather than at the call site so that every attempt is
        # counted once, including the ones a later salvage makes invisible in
        # the evidence map. See new_llm_call_stats.
        _bump(stats, "calls_made")
        # F-191: the schema is rebuilt per call from the batch actually
        # being sent — the adaptive split rewrites cur_batch, and a halved
        # batch under the original count's schema would demand objects that
        # cannot exist.
        kwargs: Dict[str, Any] = {}
        if use_schema:
            kwargs["response_format"] = _response_format_for(len(batch))
        # `perf_counter` is imported by name at module scope, deliberately:
        # several tests replace this module's `time` with a stub carrying
        # only `sleep`, and routing the clock through that name would break
        # them for a reason that has nothing to do with what they assert.
        _t0 = perf_counter()
        try:
            return client.chat.completions.create(
                model=model,
                messages=msgs,
                temperature=temperature,
                **kwargs,
            )
        finally:
            # In `finally`, so a failed call still contributes its
            # duration: a server that takes 30 seconds to refuse is
            # exactly the one a user most needs warned about.
            remember_call(_rate_endpoint, model, perf_counter() - _t0)

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

    # F-194. Per criterion, for the log line; the durable tally lives in
    # `stats` and accumulates across the stage. One accumulation point each,
    # for two different questions -- this one is "what did THIS criterion
    # cost", which a run-cumulative figure cannot answer.
    crit_no_answers = 0

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

                    # F-154 / wave 15b: the drift check, usage's first
                    # consumer (F-122's family). Once per RUN via the shared
                    # stats dict; with no stats dict the scope degrades to
                    # once per criterion, which only re-checks. A provider
                    # that reports no usage is a real condition, not an
                    # error (all thirteen legacy doubles are that provider).
                    if not _drift_done["v"] and not (
                            stats or {}).get("drift_checked", False):
                        _drift_done["v"] = True
                        if stats is not None:
                            stats["drift_checked"] = True
                        _pt = getattr(getattr(resp, "usage", None),
                                      "prompt_tokens", None)
                        if _pt is not None and int(_pt) > _last_estimate["v"]:
                            raise TokenEstimateDrift(
                                f"Run stopped after its first call: the "
                                f"server reports {int(_pt)} prompt tokens "
                                f"for a request estimated at "
                                f"{_last_estimate['v']}. The token "
                                f"estimator is optimistic for this model's "
                                f"tokenizer, so the pre-run size check "
                                f"cannot be trusted here. One call was "
                                f"spent; nothing was screened.")

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

                    # F-194: the raw value is kept alongside the parsed one.
                    # `or "[]"` is what the parser needs; it is also what makes
                    # "the server sent no content" and "the model sent an empty
                    # list" the same string, so the tally reads the raw value.
                    raw_reply = resp.choices[0].message.content
                    txt = (raw_reply or "[]")
                    arr = _parse_llm_json_array(txt)

                    # F-86: scoped to `cur_batch`, and recomputed per attempt
                    # because the adaptive-split path rewrites cur_batch. Both
                    # the acceptance guard and the quote-validation text below
                    # read from here, so neither can reach a record this call
                    # did not send.
                    batch_texts = _field_texts_by_id(cur_batch)

                    # parse response objects. A closure rather than an
                    # inline loop since wave 14c, because two replies can
                    # feed one batch now: the first call's, and — when it
                    # omitted records — the re-ask's. One acceptance path
                    # for both, or F-90/F-136/F-86 would each have a twin
                    # that could drift.
                    def _absorb(arr, batch_texts):
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

                    _absorb(arr, batch_texts)

                    # F-197, design §3.2: a reply short of the batch gets ONE
                    # re-ask of exactly the omitted subset. Not a retry —
                    # F-191 measured verbatim retries worthless at
                    # temperature 0 — but a different item list, hence a
                    # different rendered prompt, hence a different request;
                    # the replay measured it filling 31/31 omitted pairs.
                    # Shape-independent on purpose: on the F-107 fallback
                    # path the constrained guarantee is gone and `[]` is
                    # expressible again, so detection is the only line left.
                    # A raising re-ask falls into the batch's own except arm,
                    # where the F-134 guard keeps every verdict already
                    # absorbed.
                    omitted = [it for it in cur_batch
                               if _safe_str(it.get("a_id", "")).strip()
                               and (_safe_str(it.get("a_id", "")).strip(),
                                    cid) not in out]
                    if omitted:
                        _bump(stats, "reasks_made")
                        resp = _call_once(omitted, cur_trunc)
                        raw_reply = resp.choices[0].message.content
                        _absorb(_parse_llm_json_array(raw_reply or "[]"),
                                _field_texts_by_id(omitted))

                    # ensure every item in THIS cur_batch has an entry
                    _unanswered = 0
                    for it in cur_batch:
                        a_id = _safe_str(it.get("a_id", "")).strip()
                        if not a_id:
                            continue
                        if (a_id, cid) not in out:
                            _unanswered += 1
                            out[(a_id, cid)] = {
                                "used": False,
                                "decision": "uncertain",
                                "confidence": 0.0,
                                "field": "abstract",
                                "quote": "",
                                "span": None,
                                "valid_quote": False,
                            }

                    # F-194. After the back-fill, so `_unanswered` is final,
                    # and inside the try, so `resp` is in scope. A batch the
                    # model answered fully records nothing. Since the F-197
                    # re-ask, `raw_reply`/`resp` are the LAST reply's — the
                    # one that left the residue unanswered — which is the
                    # reply a diagnostician needs; the first reply's
                    # omissions were repaired and left no residue behind.
                    _remember_no_answer_reply(stats, raw_reply, resp, _unanswered)
                    crit_no_answers += _unanswered
                    if _unanswered:
                        # F-197's residue counter. `_unanswered > 0` implies
                        # `omitted` was non-empty, so a re-ask DID run and
                        # still left these: a stronger fact than a plain
                        # no_answer, named so the run report can say it.
                        if stats is not None:
                            stats["no_answer_after_reask"] = int(
                                stats.get("no_answer_after_reask", 0) or 0
                            ) + _unanswered

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

                except TokenEstimateDrift:
                    # Wave 15b: same rule as _Cancelled — this is an abort,
                    # not a batch failure, and the generic handler would
                    # rewrite it into per-record error entries.
                    raise

                except Exception as e:
                    # F-107's answer, checked BEFORE the classifier and for a
                    # measured reason (wave 14b): a real rejection body reads
                    # "unsupported parameter 'response_format'; only
                    # max_tokens allowed", and `max_tokens` matches
                    # _OVERSIZE_RE — so _classify_llm_error calls it
                    # `oversize`, salvageable, and the ladder would halve the
                    # batch and step the truncation down against a refusal no
                    # batch size can cure. One flip per run, then the minimal
                    # request F-107 protects, exactly as before this wave.
                    if use_schema and _response_format_rejected(e):
                        use_schema = False
                        if stats is not None:
                            stats["request_shape"] = "unconstrained"
                        _bump(stats, "calls_failed")
                        if log:
                            log(f"{log_prefix} this server rejects "
                                f"response_format; continuing this run with "
                                f"the unconstrained request. Constrained "
                                f"decoding is what prevents empty and "
                                f"partial replies (F-191, F-197), so watch "
                                f"the no-verdict counts.\n")
                        continue
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
    # F-194. One line per criterion, like F-90's above and for the same
    # reason: a per-record line on an 800-record corpus is 800 identical
    # lines in a sub-tab nobody is looking at.
    if log and crit_no_answers:
        log(f"{log_prefix} {cid}: {crit_no_answers} record(s) received no "
            f"verdict. What came back, so far this run: "
            f"{_no_answer_reply_sample(stats)}. These records are recorded as "
            f"unanswered, not as uncertain answers.\n")
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
               endpoint: str, temperature: float = 0.0) -> str:
    """Compose a cache key from everything that determines the model's
    answer: the fully-rendered prompt, the model, the endpoint, and the
    temperature.

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

    ``endpoint`` — F-89
    -------------------
    The argument above covers everything the model is **asked**. It does
    not cover **who answers**, and the endpoint decides that. A model name
    served by OpenAI and the same name served by Ollama were one cache
    namespace; the README's own local-provider section instructs the
    ``.env`` edit that triggers the collision *and* tells the user to leave
    the Model field alone, which is the maximally ambiguous configuration.
    The result was 100% cache hits and the previous provider's answers,
    logged as a normal ``cache_hits=N``, with no trace in any artefact.

    **Required, not defaulted.** A default would let a future call site
    omit it and quietly reintroduce F-89 for that path with the suite
    green — which is precisely how the pre-F-01 enumerated key accreted
    its omissions.

    **A parameter, not an environment read.** Resolution belongs to the
    stage engine, which does it once per run
    (``run_el_screen`` / ``run_il_screen``) from
    :func:`resolve_openai_base_url` — the same function
    :func:`_openai_client_for` uses, so the key and the client cannot
    disagree about where a run went. Reading ``os.environ`` here instead
    would make golden byte-identity environment-dependent, and neither
    ``test_key_stable_across_processes`` (which copies ``os.environ``
    wholesale) nor CI could detect that; it would fail only on the machine
    of whoever was developing the feature.

    **Hashed verbatim** — not digested, not reduced to a coarse label.
    Neither value in play is sensitive; an unsalted digest of a short
    internal hostname is dictionary-guessable, so it is a discriminator
    rather than a secret and buys privacy it cannot deliver, while a
    per-bundle salt would destroy the cross-machine comparability that is
    the reason to record it at all. A coarse "local vs remote" label
    cannot separate two local servers on different ports, which is exactly
    the comparison this is for.

    **Absent is hashed as the resolved default, not as ``""``.** §B4.5 of
    ``06_llm_integration.md`` measured those two candidates to give
    *disjoint* key sets, so this is a one-way door and is decided here
    deliberately. Hashing the resolved value means an unset
    ``OPENAI_BASE_URL`` and an explicit
    ``OPENAI_BASE_URL=https://api.openai.com/v1`` — the same endpoint,
    reached two ways — share one namespace, which is correct. Hashing the
    raw variable with absent as ``""`` would split one provider into two
    namespaces and charge the user a full re-run for a no-op edit.

    The value hashed is this repository's own resolved string, **not**
    ``str(client.base_url)``. httpx normalises the latter to
    ``https://api.openai.com/v1/`` with a trailing slash, and the two are
    different pre-images. Keeping the SDK's normalisation out of the key
    keeps the key set equal to the one §B4.5 measured, and keeps a vendor
    formatting change from silently re-keying every cache in the world.

    The cost of verbatim, stated so it is not rediscovered as a bug:
    ``…/v1`` and ``…/v1/`` route identically but key differently, as do
    ``localhost`` and ``127.0.0.1``. That is over-discrimination, and it is
    the safe direction — it costs a redundant re-run, where
    under-discrimination costs a wrong answer, which is F-89 itself.
    """
    base = json.dumps(
        {
            "prompt_version": _safe_str(prompt_version),
            "model": _safe_str(model),
            "endpoint": _safe_str(endpoint),
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
