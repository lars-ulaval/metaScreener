# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
llm_refine.py - Plugin 03 Harmoniser: optional LLM refinement of harmonised rows.

Concerns owned by this module:
  - OpenAI-compatible JSON-mode helper (_call_openai_json)
  - SDK importability (_sdk_importable) — and nothing else about
    availability. Whether this stage MAY run is
    `plugins/_common/stage_state.py::llm_readiness`, the same function
    EL and IL ask, because a third answer to that question is the defect
    F-117 closed arriving one module further down.
  - Optional refinement pass (_llm_refine) that re-evaluates already-harmonised
    rows under the row-count, identifier, and polarity guardrails specified in
    manuscript Algorithm 1; falls back to the rule-based output if any
    guardrail fires.

This is the only module in plugins/03_harmoniser/ that imports the `openai`
package, and it does so lazily (inside the call sites) so that test environments
without OpenAI credentials do not pay an import cost or fail at collection time.

Imports from .parser (vocabularies + small utilities) and .inference
(_validate_row for post-refinement structural checks). No GUI dependencies.

Extracted from `plugin.py` in Conv 4 of the v3.1.0 refactor. Behavior is
preserved verbatim; the criteria_harmonized.csv golden regression test (which
does not invoke the LLM path) confirms that the rule-based output is unchanged.
"""

import json
import os
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .parser import (
    STAGES,
    OPERATORS,
    _safe_str,
    _parse_what_cell,
)
from .inference import _validate_row


#: This stage's name in the settings store. Named rather than inlined
#: because two spellings would be two stages as far as ``resolve_stage``
#: is concerned, and one of them would silently have no configuration.
STAGE = "harmoniser"


def _call_openai_json(model: str, system: str, user: str, timeout_s: int = 600,
                      stage: str = STAGE,
                      response_format: Optional[Dict[str, Any]] = None,
                      max_tokens: Optional[int] = None,
                      ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """One OpenAI-compatible call, returning ``(parsed, meta)``.

    ``parsed`` is the JSON object the model replied with, or ``None`` when
    the reply did not parse — no longer a raise (wave 15d, F-185/F-186):
    the caller contains a bad reply per chunk, and ``meta`` carries what
    the old raise threw away. Transport errors still propagate.

    **This function had two call routes and only one of them existed**
    (F-146, wave 12). The second called ``openai.ChatCompletion``, removed
    from the SDK in version 1.0, against a project that declares
    ``openai>=1.40.0`` — so "Harmonise + LLM" could not have succeeded on
    any install for over two years. It was reached from a bare
    ``except Exception: pass`` on the route below, which meant that
    **every** failure of the real call — a refused connection, a rejected
    key, a model name with a typo, a fenced reply — was discarded and
    re-reported as::

        LLM call failed: You tried to access openai.ChatCompletion, but
        this is no longer supported in openai>=1.0.0

    a migration notice about a code path the user never invoked. The
    diagnostic's own §A1.3 says exactly this and its summary table says
    "No — dead"; the table is what was carried forward (F-148).

    Three things follow, and all three matter:

    * the removed route is **deleted**, not repaired. There is nothing to
      repair — it is an interface that no longer exists;
    * the surviving route **does not swallow its exception**. What the
      user sees is now the cause they can act on, which is a visible
      behaviour change in ``ui.py``'s message box and the point of the
      fix;
    * ``timeout_s`` is **forwarded** rather than orphaned. It was consumed
      only by the removed branch, so deleting that branch alone would have
      left this path with no timeout expression at all — the diagnostic's
      C-19, a regression hiding inside a repair.

    The default is 600 rather than the 120 the dead branch declared, and
    the wave 12 review is why (F-153). That 120 was never applied to
    anything, so making it live would have *shortened* the effective
    timeout from the SDK's own default of 600 to two minutes — and this
    stage's reason for existing on a local provider is a model doing a
    long reasoning pass on a CPU, which is precisely the run that takes
    more than two minutes. A repair that quietly tightens a limit nobody
    asked to tighten is the shape being avoided.

    Parsing goes through ``_parse_llm_json_object`` rather than a bare
    ``json.loads`` for the same reason EL and IL use
    ``_parse_llm_json_array``: local models fence their JSON, and the
    maintainer's failing run was against ``llama3.2:latest``. A bare
    ``json.loads`` on a fenced reply is the most likely thing the removed
    branch was hiding.

    F-117's property is unchanged and load-bearing: the client comes from
    ``_openai_client_for(stage)``, the one sanctioned builder, which
    decides the credential on the resolved (provider, endpoint) pair — so
    this stage cannot be handed the placeholder string while pointed at a
    billing host, and it honours the same per-stage endpoint EL and IL do.
    """
    from plugins._common.llm_client import (
        _openai_client_for,
        _parse_llm_json_object,
    )

    client = _openai_client_for(stage)
    kw: Dict[str, Any] = dict(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0,
        timeout=timeout_s,
    )
    # Wave 15d (F-185): the constrained request and the cost bound ride
    # as parameters so the chunk driver decides per call; a transport
    # error still propagates — a refused connection is not a refinement
    # rejection, and its text is the actionable cause (F-146's fix).
    if response_format is not None:
        kw["response_format"] = response_format
    if max_tokens is not None:
        kw["max_tokens"] = int(max_tokens)
    resp = client.chat.completions.create(**kw)
    txt = resp.choices[0].message.content or ""

    # Wave 15d (F-186): everything the old raise threw away, carried out
    # to the caller — finish_reason, all three token counts, the reply
    # length, the bounded head, and the parse exception's own message.
    # All were in hand at the old raise site and discarded; the 200-char
    # head ended mid-token and misled the first person to read it.
    usage = getattr(resp, "usage", None)
    meta: Dict[str, Any] = {
        "finish_reason": getattr(resp.choices[0], "finish_reason", None),
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
        "reply_chars": len(txt),
        "reply_head": txt[:200],
        "parse_error": "",
    }

    parsed = _parse_llm_json_object(txt)
    if parsed is None:
        # The unparseable-reply RuntimeError that used to live here was
        # one of the two measured worker aborts (08 §7: the maintainer's
        # own incident). It is gone by design: the caller contains the
        # failure per chunk and keeps the deterministic rows, and the
        # exact JSON error is named rather than guessed at.
        try:
            json.loads(txt)
            meta["parse_error"] = "no JSON object found in the reply"
        except Exception as e:
            meta["parse_error"] = f"{type(e).__name__}: {e}"
    return parsed, meta


def _sdk_importable() -> bool:
    """Whether the OpenAI SDK can be imported at all.

    **This is all that is left of ``_llm_available``, and the narrowing
    is the fix (F-118/D9, wave 11 session C).**

    F-117 removed one of the two key predicates from this module. What
    remained still answered three questions at once — is the SDK here, is
    a key present, may this stage run — and only the first is a question
    this module can answer. The other two are ``stage_state``'s, and this
    stage was answering them differently from EL and IL:

    * it never checked ``NOT_CONFIGURED``, so a store with a leftover key
      and **no provider chosen** lit the button, ahead of the check that
      exists precisely because the key and model tests can each be
      satisfied while the path as a whole is unconfigured;
    * it never consulted the probe, so an unreachable endpoint lit the
      button too, and the run failed one call in;
    * ``cfg.get("provider", "local")`` defaulted to a **keyless**
      provider on a missing key, which waives the key gate — the same
      shape as session A's ``defaults()``.

    The name is *removed* rather than kept as an alias, for the reason
    session A gave when it removed ``has_key=``: a caller left on the old
    name would silently keep the old meaning, and two predicates is the
    defect being closed. A ``NameError`` is the cheaper failure.

    The View now asks ``stage_state.llm_readiness`` exactly as EL and IL
    do, and combines it with this. A key without the SDK is still not
    availability, and that remains this module's to say.
    """
    try:
        import openai  # noqa: F401
        return True
    except Exception:
        try:
            from openai import OpenAI  # noqa: F401
            return True
        except Exception:
            return False


HARMONISER_CHUNK_SIZE = 4
"""Criteria per call (F-185, wave 15d). Argued from the measurement, not
the schema: four is the largest count with three consecutive
byte-identical successes in 08 §8a, while six looped for 38 rows and
eight hallucinated a ninth — so the F-107 unconstrained fallback path
sits inside the evidence too, and the strict cardinality below is a
second lock rather than the load-bearing one."""

HARMONISER_REPLY_RESERVE_PER_ROW = 240
"""Reply-reserve per refined row, deliberately generous (a refined row
is bigger than an EL verdict; the budget check uses it, and the cost
bound below is derived from it)."""

HARMONISER_MAX_TOKENS_MARGIN = 200
"""Slack on the per-call cost bound. ``max_tokens`` is a COST control,
not the correctness fix (08 §8b: the n=8 reply was already complete);
it exists to cap the n=6-shape runaway that burned 40 seconds."""


def _harmoniser_max_tokens(n_rows: int) -> int:
    return HARMONISER_REPLY_RESERVE_PER_ROW * int(n_rows) \
        + HARMONISER_MAX_TOKENS_MARGIN


def _response_format_for_rows(n: int) -> Dict[str, Any]:
    """The constrained request for a chunk of exactly ``n`` criteria rows
    (F-185), 14c's ``_response_format_for`` shape one plugin over.

    The cardinality is the point: ``minItems == maxItems == n`` makes the
    two measured failure shapes — a hallucinated extra row at n=8, a
    38-row repetition loop at n=6 — inexpressible on this path. The
    ``stage`` and ``operator`` enums are the parser's own vocabularies
    (the 15c hoist), not a new copy (F-109).
    """
    row_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "type": {"type": "string", "enum": ["include", "exclude"]},
            "stage": {"type": "string", "enum": list(STAGES)},
            "label": {"type": "string"},
            "operator": {"type": "string", "enum": list(OPERATORS)},
            "target": {"type": "string"},
            "what": {"type": "array", "items": {"type": "string"}},
            "threshold": {"type": "string"},
            "enabled": {"type": "boolean"},
        },
        "required": ["id", "stage", "type", "label", "operator", "target",
                     "what", "threshold", "enabled"],
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "criteria_rows",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "rows": {"type": "array", "items": row_schema,
                             "minItems": int(n), "maxItems": int(n)},
                },
                "required": ["rows"],
            },
        },
    }


_GENERIC_REASON = ("the model's rewrite did not pass this software's "
                   "checks")
"""The reason for a validator error the map below does not know. The
totality test drives the real validator over provoking rows and asserts
no KNOWN error reaches this; the register test asserts even this string
speaks the user's language."""

#: Validator error → what the completion dialog says (F-173's register:
#: the user's language, never the validator's). Matched by prefix on the
#: REAL strings ``_validate_row`` emits; order matters only for
#: readability. Adjudication note 2 bans the tokens "llm", "row",
#: "invalid", "requires exactly" and backticked operator names from every
#: output — tested, not assumed.
_REASON_MAP = (
    ("Invalid stage", "the model picked a screening stage this software "
                      "does not have"),
    ("Missing id", "the model dropped the criterion's identifier"),
    ("Invalid type", "the model changed whether this criterion includes "
                     "or excludes"),
    ("Invalid operator", "the model picked a comparison this software "
                         "does not have"),
    ("operator '", "the model paired the rule with a stage that cannot "
                   "run it"),
    ("Missing target", "the model dropped the column the rule reads"),
    ("Unknown target(s)", "the model pointed it at columns your file "
                          "does not have"),
    ("between requires exactly 2", "the model's range needs exactly two "
                                   "numbers"),
    ("llm requires exactly 1 sentence", "the model's rewrite is not a "
                                        "single sentence"),
    ("threshold must be between 0 and 1", "the model's confidence "
                                          "threshold is not between 0 "
                                          "and 1"),
    ("threshold must be a number", "the model's confidence threshold is "
                                   "not a number"),
)

_STRUCTURAL_REASON = ("the model did not return a usable answer for "
                      "this criterion")


def _plain_reason(errs: Sequence[str]) -> str:
    """One plain sentence for a rejected refinement, from the first
    mappable validator error."""
    for err in errs:
        for prefix, plain in _REASON_MAP:
            if str(err).startswith(prefix):
                return plain
    return _GENERIC_REASON


@dataclass
class RefineOutcome:
    """What one Harmonise + LLM pass did, per criterion — THE single
    source (adjudication note 3): the completion dialog's kept/adjusted
    sections and the exported manifest's ``refinement`` block both render
    from this object, never from two derivations.
    """

    model: str
    refined: List[str] = dc_field(default_factory=list)
    kept: Dict[str, str] = dc_field(default_factory=dict)
    repaired: List[str] = dc_field(default_factory=list)
    repairs: List[str] = dc_field(default_factory=list)
    diagnostics: List[str] = dc_field(default_factory=list)

    def manifest_block(self) -> Dict[str, Any]:
        # ``kept`` is deliberately the SAME dict object the dialog
        # renders, not a copy — one source, two surfaces.
        return {"model": self.model, "refined": list(self.refined),
                "kept": self.kept, "repaired": list(self.repaired)}


def _llm_refine(
    rows: List[Dict[str, Any]],
    full_criteria_text: str,
    a_columns: Sequence[str],
    model: str,
    log: Optional[callable] = None,
) -> Tuple[List[Dict[str, Any]], "RefineOutcome"]:
    """LLM-assisted refinement, chunked and contained (F-185, wave 15d).

    THE INVARIANT: this function can never make the table worse than the
    deterministic parse it was handed. Criteria go to the model in chunks
    of :data:`HARMONISER_CHUNK_SIZE`, each call schema-constrained with
    cardinality = chunk size (F-107 fallback: unconstrained at the same
    measured-safe size); rows the reply omits, duplicates or mis-labels
    are re-asked ONCE as their own chunk; whatever is still unusable —
    and every row the validator rejects — keeps the input row for that
    criterion, with a plain-language reason in ``outcome.kept``. No
    failure of any reply aborts the worker and no criterion can lose its
    row. Transport errors still propagate: a refused connection is not a
    refinement rejection.

    Returns ``(rows, outcome)`` — rows in input order, each either the
    validated refinement or the byte-identical input row;
    :class:`RefineOutcome` is the one object the dialog and the manifest
    both render from. The 15c auto-route (stage↔operator repairs, named)
    is preserved per row and its notes ride ``outcome.repairs``.
    """
    def _log(msg: str) -> None:
        if log:
            log(msg)

    _log("LLM refine: preparing prompt…")

    system = (
        "You are a strict criteria harmoniser for PRISMA screening.\n"
        "Return ONLY valid JSON. No Markdown, no prose.\n\n"
        "SCREENING STAGES:\n"
        "EH = Exclusion Heuristic (hard metadata rule)\n"
        "IH = Inclusion Heuristic (hard metadata rule)\n"
        "EL = Exclusion LLM/semantic (soft rule, threshold required)\n"
        "IL = Inclusion LLM/semantic (soft rule, threshold required)\n\n"
        "OPERATORS:\n"
        "equals: exact match\n"
        "in_list: value is in list\n"
        "not_in: value not in list\n"
        "gte/lte/between: numeric/date comparisons\n"
        "contains/regex: text matching\n"
        "llm: semantic rule; what MUST be exactly one short declarative sentence\n\n"
        "HARD RULES:\n"
        "- Keep SAME number of rows.\n"
        "- Do NOT change ids or types.\n"
        "- target MUST be subset of allowed A columns.\n"
        "- Stage and operator MUST pair: EH/IH run the deterministic "
        "operators only; EL/IL run llm only. A deterministic operator "
        "at EL/IL is never evaluated.\n"
        "- If unsure, prefer operator=llm and stage IL/EL.\n"
        "- Threshold: blank for EH/IH; for EL/IL must be 0..1 string (default 0.60).\n\n"
        "Output schema:\n"
        "{ \"rows\": [ {\"id\":...,\"type\":...,\"stage\":...,\"label\":...,"
        "\"operator\":...,\"target\":...,\"what\":...,\"threshold\":...,\"enabled\":...}, ... ] }\n"
    )

    def _payload(chunk_rows: Sequence[Dict[str, Any]]) -> str:
        compact = [{
            "id": r.get("id"), "type": r.get("type"),
            "stage": r.get("stage"), "label": r.get("label"),
            "operator": r.get("operator"), "target": r.get("target"),
            "what": r.get("what"), "threshold": r.get("threshold"),
            "enabled": r.get("enabled"),
            "source_text": r.get("source_text"),
        } for r in chunk_rows]
        return json.dumps({
            "task": "Refine criteria rows based on the full criteria text and allowed A columns.",
            "allowed_a_columns": list(a_columns),
            "full_criteria_text": full_criteria_text[:8000],
            "rows": compact,
        }, ensure_ascii=False)

    # -- the budget guard, before the first call (15b named this path
    # its consumer). Over the REAL chunk renders, speaking criteria.
    from plugins._common.llm_client import (
        enforce_context_budget,
        resolve_context_window,
        resolve_openai_base_url,
        _response_format_rejected,
    )
    from plugins._common.stage_state import is_paid_vendor

    if rows:
        endpoint = resolve_openai_base_url(STAGE)
        enforce_context_budget(
            criteria=[{"id": "criteria"}],
            items=list(rows),
            batch_size=HARMONISER_CHUNK_SIZE,
            trunc_chars=0,
            build_messages=lambda _pack, batch, _trunc: [
                {"role": "system", "content": system},
                {"role": "user", "content": _payload(batch)},
            ],
            window=resolve_context_window(STAGE),
            hosted=is_paid_vendor(endpoint),
            noun="criterion",
        )

    in_by_id: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for r in rows:
        rid = _safe_str(r.get("id")).strip()
        in_by_id[rid] = r
        order.append(rid)

    outcome = RefineOutcome(model=model)
    proposals: Dict[str, Dict[str, Any]] = {}
    structurally_failed: Dict[str, str] = {}

    def _call_chunk(chunk_rows, label):
        """One constrained call (F-107 fallback inside); returns the
        proposals it can attribute, and the residue ids it cannot."""
        n = len(chunk_rows)
        expected = {_safe_str(r.get("id")).strip() for r in chunk_rows}
        _log(f"LLM refine: {label} — {n} criteria …")
        try:
            parsed, meta = _call_openai_json(
                model=model, system=system, user=_payload(chunk_rows),
                response_format=_response_format_for_rows(n),
                max_tokens=_harmoniser_max_tokens(n))
        except Exception as e:
            if not _response_format_rejected(e):
                raise
            _log("LLM refine: server rejected the constrained request; "
                 "retrying unconstrained (F-107)")
            parsed, meta = _call_openai_json(
                model=model, system=system, user=_payload(chunk_rows),
                max_tokens=_harmoniser_max_tokens(n))

        got = parsed.get("rows") if isinstance(parsed, dict) else None
        if not isinstance(got, list):
            _record_chunk_failure(label, meta)
            return {}, set(expected)

        counts: Dict[str, int] = {}
        for rr in got:
            if isinstance(rr, dict):
                rid = _safe_str(rr.get("id")).strip()
                counts[rid] = counts.get(rid, 0) + 1

        found: Dict[str, Dict[str, Any]] = {}
        for rr in got:
            if not isinstance(rr, dict):
                continue
            rid = _safe_str(rr.get("id")).strip()
            if rid not in expected:
                # Adjudication note 1: a valid-looking row for an id this
                # chunk never asked about is NEVER absorbed.
                outcome.diagnostics.append(
                    f"{label}: discarded a reply row for '{rid}', which "
                    f"is not in this chunk")
                continue
            if counts.get(rid, 0) > 1:
                continue        # two proposals for one criterion is none
            found[rid] = rr
        residue = expected - set(found)
        return found, residue

    def _record_chunk_failure(label, meta):
        pe = meta.get("parse_error") or \
            "reply was JSON but carried no rows list"
        outcome.diagnostics.append(
            f"{label}: unusable reply — finish_reason="
            f"{meta.get('finish_reason')}, prompt_tokens="
            f"{meta.get('prompt_tokens')}, completion_tokens="
            f"{meta.get('completion_tokens')}, total_tokens="
            f"{meta.get('total_tokens')}, reply_chars="
            f"{meta.get('reply_chars')}, parse_error={pe}")

    # -- pass 1: the chunks
    residues: List[str] = []
    chunks = [rows[i:i + HARMONISER_CHUNK_SIZE]
              for i in range(0, len(rows), HARMONISER_CHUNK_SIZE)]
    for ci, chunk in enumerate(chunks, start=1):
        found, residue = _call_chunk(
            chunk, f"chunk {ci} of {len(chunks)}")
        proposals.update(found)
        residues.extend(sorted(residue))

    # -- pass 2: ONE re-ask over the structural residue, chunked
    if residues:
        _log(f"LLM refine: re-asking once for {len(residues)} "
             f"criteria the replies dropped or mangled")
        reask_rows = [in_by_id[rid] for rid in residues]
        for i in range(0, len(reask_rows), HARMONISER_CHUNK_SIZE):
            part = reask_rows[i:i + HARMONISER_CHUNK_SIZE]
            found, residue = _call_chunk(part, "re-ask")
            proposals.update(found)
            for rid in sorted(residue):
                structurally_failed[rid] = _STRUCTURAL_REASON

    # -- pass 3: per-row acceptance — the 15c pipeline, contained
    out_rows: List[Dict[str, Any]] = []
    for rid in order:
        original = in_by_id[rid]
        rr = proposals.get(rid)
        if rr is None:
            out_rows.append(original)
            outcome.kept[rid] = structurally_failed.get(
                rid, _STRUCTURAL_REASON)
            continue

        nr = {
            "stage": _safe_str(rr.get("stage")).strip().upper(),
            "id": rid,
            "type": _safe_str(rr.get("type")).strip().lower(),
            "scope": "metadata",
            "label": _safe_str(rr.get("label") or original.get("label")).strip(),
            "operator": _safe_str(rr.get("operator")).strip().lower(),
            "target": _safe_str(rr.get("target")).strip(),
            "what": rr.get("what"),
            "threshold": _safe_str(rr.get("threshold", "")).strip(),
            "enabled": bool(rr.get("enabled", True)),
            "source_text": original.get("source_text", ""),
        }
        if nr["type"] != _safe_str(original.get("type")).strip().lower():
            out_rows.append(original)
            outcome.kept[rid] = ("the model changed whether this "
                                 "criterion includes or excludes")
            continue

        if not isinstance(nr["what"], list):
            nr["what"] = _parse_what_cell(nr["operator"] or "contains", nr["what"])
        nr["what"] = [str(x) for x in nr["what"] if str(x).strip()]

        # F-65 (wave 15c), preserved verbatim in behaviour: the model is
        # nudged toward stage IL/EL, and a reply that keeps a
        # deterministic operator while obeying the nudge is repaired by
        # the router's rule and NAMED — the repair reaches the
        # completion dialog, not only the log.
        op0 = nr["operator"]
        stage0 = nr["stage"]
        if stage0 in ("EL", "IL") and op0 in OPERATORS and op0 != "llm":
            nr["stage"] = "IH" if nr["type"] == "include" else "EH"
            nr["threshold"] = ""
            note = (f"{rid}: the model put deterministic operator "
                    f"'{op0}' at {stage0}, which runs llm only; "
                    f"re-staged to {nr['stage']}")
            outcome.repairs.append(note)
            outcome.repaired.append(rid)
            _log(f"LLM refine repair: {note}")
        elif stage0 in ("EH", "IH") and op0 == "llm":
            nr["stage"] = "IL" if nr["type"] == "include" else "EL"
            note = (f"{rid}: the model put operator 'llm' at "
                    f"{stage0}, which never asks a model; re-staged to "
                    f"{nr['stage']}")
            outcome.repairs.append(note)
            outcome.repaired.append(rid)
            _log(f"LLM refine repair: {note}")

        errs, warns = _validate_row(nr, a_columns)
        if errs:
            # THE INVARIANT, at its point: a rejected refinement keeps
            # the deterministic row, with the reason in the user's
            # language — never a raise, never the validator's string on
            # the dialog. The raw strings go to the log for the record.
            out_rows.append(original)
            outcome.kept[rid] = _plain_reason(errs)
            outcome.repaired = [x for x in outcome.repaired if x != rid]
            outcome.repairs = [x for x in outcome.repairs
                               if not x.startswith(f"{rid}:")]
            _log(f"LLM refine: kept {rid} — validator said: "
                 f"{'; '.join(errs)}")
            continue
        for w in warns:
            _log(f"LLM refined row warning ({rid}): {w}")
        out_rows.append(nr)
        outcome.refined.append(rid)

    for line in outcome.diagnostics:
        _log("LLM refine: " + line)
    _log("LLM refine: done — %d refined, %d kept, %d repaired."
         % (len(outcome.refined), len(outcome.kept),
            len(outcome.repaired)))
    return out_rows, outcome
