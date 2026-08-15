
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
plugins/06_el/prompt.py - EL stage prompt construction.

Holds EL's PROMPT_VERSION constant and the prompt template used by
``run_m1_llm_for_criterion`` when EL invokes the LLM. The template is
byte-identical to IL's today (see plugins/07_il/prompt.py); the
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


PROMPT_VERSION = "EL_v3_nullquote"
"""Bumped at wave 15e (F-195/F-21): the template stops demanding a quote
for every verdict. A ``not_meet`` on an exclusion criterion is justified
by ABSENCE — no substring exists to quote — so v2's unconditional
"quote (exact substring)" clause demanded fabrication, and the gate then
spent itself rejecting output the prompt had made impossible to produce
honestly (F-195; 49 of 241 answered pairs carried an invalid quote on
the wave-14c batch-5 run). v3 asks for a quote where one can exist
('meet'), for ``null`` where one cannot, and states that an empty list
is never a valid answer — F-191's outstanding prompt-side clause.
Unlike 14c's bump, this one MOVES TEMPLATE BYTES, so the cache goldens'
re-key needs the tool's ``--migration template`` mode, which freezes the
v2 system string; tools/rekey_cache_goldens.py holds the proof and
tests/test_golden_rekey.py re-verifies it on every suite run.
"""


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
