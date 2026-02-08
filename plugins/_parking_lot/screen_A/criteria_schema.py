# -*- coding: utf-8 -*-
"""
Created on Sun Sep 21 19:31:22 2025

@author: alere
"""

# File: plugins/screen_A/criteria_schema.py
# Batch 1 — Criteria schema + validators

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any
import re
import json

ALLOWED_TYPES = {"include", "exclude"}
ALLOWED_SCOPE = {"metadata", "fulltext", "both"}
ALLOWED_OPERATORS = {
    "contains", "regex", "equals", "in", "not_in", "gte", "lte", "between"
}

# Minimal synonym map used by the harmonizer
DEFAULT_SYNONYMS: Dict[str, List[str]] = {
    "randomized controlled trial": ["rct", "randomised controlled trial", "randomized trial"],
    "adult": ["adults", ">=18", "≥18", "18 years or older"],
    "children": ["child", "pediatric", "paediatric", "<18"],
}


@dataclass
class Criterion:
    id: str
    label: str
    type: str  # include|exclude
    scope: str  # metadata|fulltext|both
    targets: List[str] = field(default_factory=list)
    operators: List[str] = field(default_factory=list)
    patterns: List[str] = field(default_factory=list)
    pico: Dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0
    threshold: float = 0.6
    notes: str = ""

    def validate(self) -> None:
        if self.type not in ALLOWED_TYPES:
            raise ValueError(f"Invalid type: {self.type}")
        if self.scope not in ALLOWED_SCOPE:
            raise ValueError(f"Invalid scope: {self.scope}")
        for op in self.operators:
            if op not in ALLOWED_OPERATORS:
                raise ValueError(f"Invalid operator: {op}")
        if not (0.0 <= self.weight <= 10.0):
            raise ValueError("weight must be within [0,10]")
        if not (0.0 <= self.threshold <= 1.0):
            raise ValueError("threshold must be within [0,1]")

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def criterion_from_dict(d: Dict[str, Any]) -> Criterion:
    # Fill defaults and coerce lists
    return Criterion(
        id=str(d.get("id") or ""),
        label=str(d.get("label") or ""),
        type=str(d.get("type") or "include"),
        scope=str(d.get("scope") or "both"),
        targets=list(d.get("targets") or []),
        operators=list(d.get("operators") or ["contains"]),
        patterns=[str(x) for x in (d.get("patterns") or [])],
        pico=dict(d.get("pico") or {}),
        weight=float(d.get("weight") or 1.0),
        threshold=float(d.get("threshold") or 0.6),
        notes=str(d.get("notes") or ""),
    )


def normalize_synonyms(text: str, synonyms: Dict[str, List[str]] = DEFAULT_SYNONYMS) -> str:
    s = text
    for canon, alts in synonyms.items():
        for a in alts:
            s = re.sub(rf"\b{re.escape(a)}\b", canon, s, flags=re.IGNORECASE)
    return s


