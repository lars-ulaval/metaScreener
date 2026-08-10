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
from typing import Any, Dict, List, Optional, Sequence

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


def _call_openai_json(model: str, system: str, user: str, timeout_s: int = 120,
                      stage: str = STAGE) -> Dict[str, Any]:
    """Best-effort OpenAI call returning JSON."""
    try:
        # F-117, review of this session. This was a bare ``OpenAI()`` —
        # no api_key, no base_url. Once ``_llm_available`` admitted a
        # keyless local provider, the predicate said yes for exactly the
        # configuration this constructor cannot build for: the button
        # went live and the call then failed into the ``except`` below,
        # which falls through to the removed 0.x API and reports a
        # meaningless error. It also meant this stage ignored the
        # endpoint EL and IL honour, so a "local" run refined criteria
        # against the vendor. One client builder for all three stages.
        #
        # Session C passes the stage, so this call honours the same
        # per-stage resolution EL and IL do — and, more importantly, the
        # same invariant: `_openai_client_for` decides the credential on
        # the resolved (provider, endpoint) pair, so this stage cannot be
        # handed the placeholder string while pointed at a billing host.
        from plugins._common.llm_client import _openai_client_for
        client = _openai_client_for(stage)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
        )
        txt = resp.choices[0].message.content or ""
        return json.loads(txt)
    except Exception:
        pass

    try:
        import openai  # type: ignore
        resp = openai.ChatCompletion.create(  # type: ignore[attr-defined]
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
            request_timeout=timeout_s,
        )
        txt = resp["choices"][0]["message"]["content"] or ""
        return json.loads(txt)
    except Exception as e:
        raise RuntimeError(f"LLM call failed: {e}")


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


def _llm_refine(
    rows: List[Dict[str, Any]],
    full_criteria_text: str,
    a_columns: Sequence[str],
    model: str,
    log: Optional[callable] = None,
) -> List[Dict[str, Any]]:
    """LLM-assisted refinement (guardrailed)."""
    def _log(msg: str) -> None:
        if log:
            log(msg)

    _log("LLM refine: preparing prompt…")

    compact = []
    for r in rows:
        compact.append({
            "id": r.get("id"),
            "type": r.get("type"),
            "stage": r.get("stage"),
            "label": r.get("label"),
            "operator": r.get("operator"),
            "target": r.get("target"),
            "what": r.get("what"),
            "threshold": r.get("threshold"),
            "enabled": r.get("enabled"),
            "source_text": r.get("source_text"),
        })

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
        "- If unsure, prefer operator=llm and stage IL/EL.\n"
        "- Threshold: blank for EH/IH; for EL/IL must be 0..1 string (default 0.60).\n\n"
        "Output schema:\n"
        "{ \"rows\": [ {\"id\":...,\"type\":...,\"stage\":...,\"label\":...,"
        "\"operator\":...,\"target\":...,\"what\":...,\"threshold\":...,\"enabled\":...}, ... ] }\n"
    )

    user_payload = {
        "task": "Refine criteria rows based on the full criteria text and allowed A columns.",
        "allowed_a_columns": list(a_columns),
        "full_criteria_text": full_criteria_text[:8000],
        "rows": compact,
    }
    user = json.dumps(user_payload, ensure_ascii=False)

    _log(f"LLM refine: calling OpenAI model={model} …")
    d = _call_openai_json(model=model, system=system, user=user)

    if not isinstance(d, dict) or "rows" not in d or not isinstance(d["rows"], list):
        raise RuntimeError("LLM response missing 'rows' list")

    got = d["rows"]
    if len(got) != len(rows):
        raise RuntimeError(f"LLM changed row count (expected {len(rows)}, got {len(got)})")

    expected = [(r.get("id"), r.get("type")) for r in rows]

    out_rows: List[Dict[str, Any]] = []
    for i, rr in enumerate(got):
        if not isinstance(rr, dict):
            raise RuntimeError("LLM produced a non-object row")
        exp_id, exp_type = expected[i]
        if _safe_str(rr.get("id")).strip() != _safe_str(exp_id).strip():
            raise RuntimeError(f"LLM changed id at index {i}")
        if _safe_str(rr.get("type")).strip().lower() != _safe_str(exp_type).strip().lower():
            raise RuntimeError(f"LLM changed type at index {i}")

        nr = {
            "stage": _safe_str(rr.get("stage")).strip().upper(),
            "id": _safe_str(rr.get("id")).strip(),
            "type": _safe_str(rr.get("type")).strip().lower(),
            "scope": "metadata",
            "label": _safe_str(rr.get("label") or rows[i].get("label")).strip(),
            "operator": _safe_str(rr.get("operator")).strip().lower(),
            "target": _safe_str(rr.get("target")).strip(),
            "what": rr.get("what"),
            "threshold": _safe_str(rr.get("threshold", "")).strip(),
            "enabled": bool(rr.get("enabled", True)),
            "source_text": rows[i].get("source_text", ""),
        }

        if not isinstance(nr["what"], list):
            nr["what"] = _parse_what_cell(nr["operator"] or "contains", nr["what"])
        nr["what"] = [str(x) for x in nr["what"] if str(x).strip()]

        errs, warns = _validate_row(nr, a_columns)
        if errs:
            raise RuntimeError(f"LLM refined row invalid ({nr.get('id')}): {', '.join(errs)}")
        for w in warns:
            _log(f"LLM refined row warning ({nr.get('id')}): {w}")

        out_rows.append(nr)

    _log("LLM refine: done.")
    return out_rows

