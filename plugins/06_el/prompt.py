
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


PROMPT_VERSION = "EL_v2_jsonschema"
"""Bumped at wave 14c (F-191/F-197): the request now carries a
``response_format`` JSON schema with per-batch cardinality. The rendered
prompt is byte-identical to v1 — the constraint rides on the request
parameter — so this bump is the deliberate lever ``_cache_key`` reserves
for a semantic change that moves no byte of the template: without it,
verdicts cached from unconstrained runs would be served to constrained
runs and back, indistinguishably. The goldens were re-keyed, not
re-captured; tools/rekey_cache_goldens.py --migration prompt-version
holds the proof and tests/test_golden_rekey.py re-verifies it.
"""


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
