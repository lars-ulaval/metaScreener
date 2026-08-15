
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
plugins/07_il/prompt.py - IL stage prompt construction.

Holds IL's PROMPT_VERSION constant and the prompt template used by
``run_m1_llm_for_criterion`` when IL invokes the LLM. The template is
byte-identical to EL's today (see plugins/06_el/prompt.py); the
duplication is deliberate so that EL and IL prompts can evolve
independently in the future without coupling them through a shared
module.

PROMPT_VERSION is incorporated into the cache key (see
``plugins._common.llm_client._cache_key``); changing its value
invalidates the LLM-response cache and the captured byte-identity
goldens, so it must only be bumped intentionally.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from plugins._common.llm_client import _safe_str


PROMPT_VERSION = "IL_v3_nullquote"
"""Bumped at wave 15e with EL's — see plugins/06_el/prompt.py; the two
stages share run_m1_llm_for_criterion, so the template and the version
move together or the unmoved stage keeps demanding evidence that cannot
exist (F-195)."""


def _build_llm_messages_for_criterion(criterion: Dict[str, Any], items: List[Dict[str, Any]], trunc_chars: int) -> List[Dict[str, str]]:
    sys = (
        "You are scoring research items against ONE screening criterion. "
        "For each item, answer with JSON only. Keys per item: "
        "a_id, decision ('meet'|'not_meet'|'uncertain'), confidence (0..1), "
        "field ('title'|'abstract'|'keywords'), "
        "quote (for 'meet': an exact substring from that field that supports the verdict; "
        "for 'not_meet' or 'uncertain': null, unless an exact substring genuinely supports the verdict), "
        "span ([start, end] of the quote, or null when quote is null). "
        "Return a JSON list of objects, one object for every item sent, "
        "including items whose decision is 'not_meet'. "
        "An empty list is never a valid answer."
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
