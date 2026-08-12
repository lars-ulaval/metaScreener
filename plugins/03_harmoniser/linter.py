# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
linter.py — does this rule do what its label says?

The harmoniser turns a researcher's sentence into an executable rule and, today,
nothing checks the translation. F-166: *"The publication venue contains ICRA OR
IROS"* became ``equals doc_type conference``, removed 112 of 776 records, and
Validate reported zero errors and zero warnings. F-167: *"written in French or
Spanish"* became ``equals lang French``, dropping the second operand in silence.

**This module warns and never blocks.** It has no concept of failure, raises
nothing, and returns findings. The researcher may have a reason; a tool that
blocks teaches people to click past warnings, which is the failure mode that
matters most here. Every finding names the criterion and says what the rule will
actually do, in the user's terms — not a rule name and not a count. ``_validate``
already computes error strings and discards them (F-173); a linter whose findings
are also discarded would be that defect happening twice.

**Pure.** No Tk, no file IO, no global state, no network, no clock. It reads its
arguments and returns a list. Import-safe in any order.

**Do not reach this module through ``plugin.py``** — that module does
``from tkinter import ttk`` at import time, and the whole point of keeping this one
pure is lost if its only route drags in a GUI. ``tests/test_criteria_linter.py``
imports it directly, and asserts the Tk-freeness in a subprocess, because
``tests/conftest.py`` mocks ``tkinter`` before any plugin import and so cannot
observe the difference.

Design, the measurements behind each check, and the five things this cannot do:
``docs/internal/FIX_WAVE_13C_LINTER.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .parser import TARGET_ALIASES, _parse_what_cell, _safe_str

# --------------------------------------------------------------------------
# Severity. Deliberately NOT the findings register's Critical/High/Medium/Low:
# those grade work for a maintainer, these grade a sentence shown to a
# researcher mid-task, and reusing the words would invite the two to be
# conflated. Ordered most- to least-urgent; findings sort by this, so the
# sentence read first is the one that changes which papers are screened.
# --------------------------------------------------------------------------

MISTRANSLATED = "MISTRANSLATED"   # the rule demonstrably does not implement the label
INERT = "INERT"                   # the rule is well formed and will not act
NOTICE = "NOTICE"                 # worth a look; not necessarily wrong

_SEVERITY_ORDER = (MISTRANSLATED, INERT, NOTICE)


@dataclass(frozen=True)
class Finding:
    """One thing worth telling the user about one criterion."""

    criterion_id: str
    check: str
    severity: str
    message: str
    detail: str = ""

    @property
    def _rank(self) -> int:
        try:
            return _SEVERITY_ORDER.index(self.severity)
        except ValueError:          # pragma: no cover - guarded by construction
            return len(_SEVERITY_ORDER)


class LintReport(List[Finding]):
    """The findings, plus which checks actually ran.

    It *is* a list, so a caller that only wants findings can ignore the rest.
    ``skipped`` exists because a check that could not run must be visible: a
    caller must never read "no findings" as "checked and clean", which is the
    shape F-64 records one stage over.
    """

    def __init__(
        self,
        findings: Iterable[Finding] = (),
        ran: Iterable[str] = (),
        skipped: Iterable[str] = (),
    ) -> None:
        super().__init__(findings)
        self.ran: Tuple[str, ...] = tuple(ran)
        self.skipped: Tuple[str, ...] = tuple(skipped)


# --------------------------------------------------------------------------
# Row normalisation.
#
# The linter has two callers with two shapes. `ui.py::_harmonise_no_llm` builds
# in-memory dicts where `what` is a list and `enabled` is a bool; the exported
# `criteria_harmonized.csv` carries `what` joined by `_what_to_export` and
# `enabled` as 0/1. A linter specified against the file would split a list that
# is not a list. Both are accepted and normalised here, once.
# --------------------------------------------------------------------------

_TRUTHY = {"1", "true", "yes", "y", "on"}


def _norm_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    operator = _safe_str(row.get("operator")).strip().lower()

    what = row.get("what")
    if isinstance(what, (list, tuple)):
        what_list = [_safe_str(w).strip() for w in what if _safe_str(w).strip()]
    else:
        # `_parse_what_cell` is the canonical reverse of `_what_to_export`;
        # reimplementing the split here would be a second representation of
        # one rule, which is F-109's shape.
        what_list = _parse_what_cell(operator, what)

    enabled = row.get("enabled", True)
    if isinstance(enabled, str):
        enabled_b = enabled.strip().lower() in _TRUTHY
    else:
        enabled_b = bool(enabled)

    targets = [
        t.strip().lower()
        for t in _safe_str(row.get("target")).split(",")
        if t.strip()
    ]

    label = _safe_str(row.get("label")).strip()
    if not label:
        # `_infer_criterion_details` seeds `what` from the label, and the
        # exporter falls back the same way; a row with no label but a
        # source_text is still lintable against the sentence.
        label = _safe_str(row.get("source_text")).strip()

    return {
        "id": _safe_str(row.get("id")).strip(),
        "stage": _safe_str(row.get("stage")).strip().upper(),
        "type": _safe_str(row.get("type")).strip().lower(),
        "operator": operator,
        "targets": targets,
        "what": what_list,
        "label": label,
        "threshold": _safe_str(row.get("threshold")).strip(),
        "enabled": enabled_b,
    }


# --------------------------------------------------------------------------
# The concept vocabulary, DERIVED rather than retyped.
#
# `parser.py::TARGET_ALIASES` already maps the words a researcher writes onto
# the columns the engine reads (language->lang, journal->venue, conference->venue,
# document_type->doc_type, ...). Extending it with an identity mapping for each
# corpus column gives "which column does this word name?" for free. Retyping the
# vocabulary here would make this module a further copy of it; F-109 is the row
# about exactly that, and it already counts seven.
# --------------------------------------------------------------------------

def _concept_map(a_columns: Sequence[str]) -> Dict[str, str]:
    concepts: Dict[str, str] = {}
    for col in a_columns:
        c = _safe_str(col).strip().lower()
        if c:
            concepts[c] = c
    for alias, canon in TARGET_ALIASES.items():
        a = _safe_str(alias).strip().lower()
        c = _safe_str(canon).strip().lower()
        # Only map an alias onto a column the corpus actually has, so a label
        # mentioning "journal" against a corpus with no venue column is not
        # reported as naming something.
        if a and c in concepts:
            concepts[a] = c
    return concepts


_WORD = re.compile(r"[a-z_]+")


def _concepts_named_by(label: str, concepts: Mapping[str, str]) -> List[str]:
    """Which canonical columns does this sentence name, if any?"""
    seen: List[str] = []
    for word in _WORD.findall(label.lower()):
        canon = concepts.get(word)
        if canon and canon not in seen:
            seen.append(canon)
    return seen


# --------------------------------------------------------------------------
# Check 1 — target-mismatch (F-166)
# --------------------------------------------------------------------------

TARGET_MISMATCH = "target-mismatch"


def _check_target_mismatch(row: Dict[str, Any], concepts: Mapping[str, str]) -> Optional[Finding]:
    named = _concepts_named_by(row["label"], concepts)
    if not named:
        return None
    targets = set(row["targets"])
    if not targets or targets & set(named):
        return None

    named_txt = ", ".join('"%s"' % n for n in named)
    target_txt = ", ".join('"%s"' % t for t in sorted(targets))
    return Finding(
        criterion_id=row["id"],
        check=TARGET_MISMATCH,
        severity=MISTRANSLATED,
        message=(
            "%s mentions %s, but the rule reads %s instead. It will be applied "
            "to %s values and will never look at %s."
            % (row["id"] or "This criterion", named_txt, target_txt,
               target_txt, named_txt)
        ),
        detail="label names %s; rule targets %s" % (named, sorted(targets)),
    )


# --------------------------------------------------------------------------


def lint_criteria(
    rows: Sequence[Mapping[str, Any]],
    a_columns: Sequence[str] = (),
    corpus_rows: Optional[Sequence[Mapping[str, Any]]] = None,
) -> LintReport:
    """Lint a harmonised criteria table. Warns; never blocks; raises nothing.

    ``rows`` may be the in-memory shape (``what`` a list) or the exported CSV
    shape (``what`` a joined string); both are normalised.

    ``a_columns`` is the A-vector header. Without it the checks that need to know
    what a column name looks like are skipped, and named in ``report.skipped``.
    """
    normalised = [_norm_row(r) for r in (rows or [])]

    ran: List[str] = []
    skipped: List[str] = []
    findings: List[Finding] = []

    concepts = _concept_map(a_columns or ())
    if concepts:
        ran.append(TARGET_MISMATCH)
        for row in normalised:
            f = _check_target_mismatch(row, concepts)
            if f is not None:
                findings.append(f)
    else:
        skipped.append(TARGET_MISMATCH)

    findings.sort(key=lambda f: (f._rank, f.criterion_id))
    return LintReport(findings, ran=ran, skipped=skipped)
