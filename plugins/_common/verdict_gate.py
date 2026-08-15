# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
verdict_gate.py — the evidence gate's truth table, as data (wave 15e,
F-195 / F-21).

**The table is the spec.** ``GATE_TABLE`` is the adjudicated wave-15e design
committed as an executable artifact rather than as prose the engines
re-implement by hand (F-131's family: a hand-maintained enumeration drifts;
a table the code derives from cannot). ``verdict_action`` is the only
reader; ``tests/test_verdict_gate.py`` asserts every cell and every
boundary.

The rule the table encodes — adjudicated by the coordinator for wave 15e:
**the gate keys on DIRECTION OF HARM and JUSTIFICATION TYPE, not on the
decision string.**

* A verdict that REMOVES a record, justified by PRESENCE ("the text IS
  about X"): full strict gate — a validated quote, of substance, above
  threshold. Auto-actable only where exclusion is permitted (F-145).
* A verdict that KEEPS a record: confidence only. A quote cannot be
  demanded where the justification is absence, and is not needed to leave
  a record in the review; if one is offered it is validated and recorded,
  never required.
* A verdict that REMOVES a record, justified by ABSENCE ("the text does
  not meet inclusion criterion X"): NEVER auto-acted — any provider, any
  confidence, any quote, any setting. There is no substring that can
  prove an absence, so no gate can check one; what cannot be proven goes
  to a person. Above threshold it is a policy-declined suppression
  (``EXCLUSION_SUPPRESSED`` — the model asked, we refused); below, an
  ordinary gate refusal.

Polarity is the CRITERION'S OWN (``ctype``), not the stage's — the rule
both engines have carried since wave 12 (*"polarity is carried by the
criterion's type cell, not by the stage"*), which is what makes this
table independent of F-206's unvalidated type-vs-stage invariant: a
polarity-mismatched row still lands on its correct direction-of-harm row
here. F-04's closure guarantees ``ctype`` is ``include`` or ``exclude``
at every call site; anything else is treated as ``include``, matching the
engines' historical ``else`` arm.

``allow_llm_exclusion`` (the provider-trust setting, F-145) is deliberately
NOT an input to this table: it governs whether a presence-removal that
passes the strict gate is acted on or suppressed, one layer up, in the
engines' ``_excluded_by``. Provider trust cannot manufacture provability,
so it has no cell here.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from plugins._common.llm_client import _normalize_space


# --------------------------------------------------------------------------
# The substance floor (F-21)
# --------------------------------------------------------------------------
SUBSTANCE_MIN_CHARS = 20
"""Minimum whitespace-normalised quote length for a removal-by-presence.

Calibration, measured on the frozen wave-14d evidence
(``docs/data/wave14d_invariance_runs/``, wave-15e design §4.3): of the 45
fabricated ``meet`` verdicts across the three batched runs, 35 passed the
pre-15e gate with a validated quote; at a floor of 20 that falls to 14,
because qwen2.5:7b's modal fabricated quote is the bare term
``"virtual reality"`` — exactly 15 normalised chars (nine of the eighteen
batch-10 fabrications). The elbow is between 15 and 20. Meanwhile every
genuine exclusion in a committed artefact clears 20 comfortably: the EL
golden's single audited exclusion (A499) quotes 102 normalised chars.

F-21's own caution, kept beside the number it bounds: against a model
with no honest quote, a longer minimum buys a MORE CONVINCING
fabrication. This floor is hygiene for the strict gate, not the quality
lever — F-201's fix cell (batch 1, two-model agreement, the EC-2
wording) remains that lever.
"""


# --------------------------------------------------------------------------
# The truth table
# --------------------------------------------------------------------------
RULE_REMOVES_BY_PRESENCE = "removes_by_presence"
RULE_KEEPS = "keeps"
RULE_REMOVES_BY_ABSENCE = "removes_by_absence"

#: (ctype, decision) -> rule. THE wave-15e table; see the module docstring.
#: Four cells, total over {include, exclude} x {meet, not_meet}; the
#: decisions outside the whitelist never reach a rule (``verdict_action``
#: answers UNCERTAIN first).
GATE_TABLE: Dict[Tuple[str, str], str] = {
    ("exclude", "meet"): RULE_REMOVES_BY_PRESENCE,
    ("exclude", "not_meet"): RULE_KEEPS,
    ("include", "meet"): RULE_KEEPS,
    ("include", "not_meet"): RULE_REMOVES_BY_ABSENCE,
}

#: What ``verdict_action`` can answer. The engines route: MET -> the met
#: list; EXCLUDE -> ``_excluded_by`` (FAILED or SUPPRESSED per F-145's
#: policy); SUPPRESS_ABSENCE -> suppressed unconditionally (never FAILED);
#: UNCERTAIN -> the uncertain list.
ACTION_MET = "MET"
ACTION_EXCLUDE = "EXCLUDE"
ACTION_SUPPRESS_ABSENCE = "SUPPRESS_ABSENCE"
ACTION_UNCERTAIN = "UNCERTAIN"


def substance_ok(quote: str) -> bool:
    """Whether a quote clears :data:`SUBSTANCE_MIN_CHARS` after the same
    whitespace normalisation ``_quote_in_text`` applies."""
    return len(_normalize_space(quote or "")) >= SUBSTANCE_MIN_CHARS


def verdict_action(*, ctype: str, decision: str, confidence: float,
                   threshold: float, quote: str, valid_quote: bool) -> str:
    """Apply :data:`GATE_TABLE` to one verdict; return an ``ACTION_*``.

    The decision whitelist survives in EVERY rule: ``uncertain`` — the
    model's or the back-fill's (which also writes ``confidence: 0.0``) —
    passes nothing, keeps nothing, removes nothing. That clause is one of
    the lines that keep F-191's ``[]``-to-``not_meet`` hazard dead on the
    unconstrained fallback path; see the wave-15e design §2.
    """
    if decision not in ("meet", "not_meet"):
        return ACTION_UNCERTAIN
    key = ("exclude" if ctype == "exclude" else "include", decision)
    rule = GATE_TABLE[key]
    conf_ok = float(confidence) >= float(threshold)
    if rule == RULE_KEEPS:
        # Confidence only. valid_quote/quote are recorded by the caller,
        # never consulted: a keep verdict justified by absence has no
        # substring to offer (F-195), and one justified by presence does
        # not need its quote to leave the record in the review.
        return ACTION_MET if conf_ok else ACTION_UNCERTAIN
    if rule == RULE_REMOVES_BY_PRESENCE:
        # The full strict gate: F-191's three clauses plus F-21's floor.
        if bool(valid_quote) and substance_ok(quote) and conf_ok:
            return ACTION_EXCLUDE
        return ACTION_UNCERTAIN
    # RULE_REMOVES_BY_ABSENCE. Above threshold the model has confidently
    # asked for a removal no evidence can support: policy declines, a
    # person decides. Below threshold it is an ordinary gate refusal —
    # "suppressed" and "uncertain" stay different facts (F-145's pinned
    # distinction).
    return ACTION_SUPPRESS_ABSENCE if conf_ok else ACTION_UNCERTAIN


# --------------------------------------------------------------------------
# The decliners (rule (c) / F-145), for the reason summary
# --------------------------------------------------------------------------
#: Why a suppressed verdict was not acted on. ``EXCLUSION_SUPPRESSED``
#: means "the gate accepted and policy declined" (bundle.py); since wave
#: 15e there are two decliners, and the reason summary must name the one
#: that applied — the line a human reviewer acts on must not say
#: "flag-only" about a removal no setting could have permitted.
DECLINED_FLAG_ONLY = "flag_only"
DECLINED_ABSENCE = "absence"
DECLINED_ABSENCE_AND_FLAG_ONLY = "absence_and_flag_only"
