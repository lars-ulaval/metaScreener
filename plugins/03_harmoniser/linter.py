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
# Check 2 — dropped-operand (F-167)
#
# Count the coordinating alternatives the label offers; compare against the
# operands the rule carries. Two refinements are load-bearing, and without
# either one the check fires on rows that are correct — which is the failure
# mode that matters most, because a noisy linter gets ignored.
#
#   (i)  Only DISCRETE operators. `gte`/`lte`/`between` express an interval, so
#        "2018 or later" is already carried by the operator (IC-4). For `llm`
#        the whole sentence IS the single operand by design; without this
#        exclusion IC-1 and EC-2 both false-positive.
#   (ii) Discount an `or` that enumerates the row's OWN targets rather than
#        values. IC-5's label is "The title, abstract, or keywords mention
#        training OR vocational OR workplace." — three `or` tokens, one of
#        which joins two field names this rule already reads.
#
# `07_criteria_parsing.md` §7.5 measured the naive form at 6 of 8 and called it
# over-inclusive; this is what makes it 2 of 8.
# --------------------------------------------------------------------------

DROPPED_OPERAND = "dropped-operand"

_DISCRETE_OPERATORS = frozenset({"equals", "contains", "not_in", "in_list"})

# "2018 or later" is one bound, not two alternatives.
_RANGE_TAIL = re.compile(
    r"\bor\s+(?:later|earlier|more|less|above|below|greater|fewer|newer|older|"
    r"after|before|higher|lower|beyond|onwards?)\b"
)


def _alternatives_offered(label: str, targets: Sequence[str]) -> int:
    """How many alternatives does this sentence offer as VALUES?"""
    text = _RANGE_TAIL.sub(" ", label.lower())
    words = _WORD.findall(text)

    own = set()
    for t in targets:
        own.add(t)
        # a label may name a target by an alias ("journal" for venue)
        for alias, canon in TARGET_ALIASES.items():
            if _safe_str(canon).strip().lower() == t:
                own.add(_safe_str(alias).strip().lower())

    count = 1
    for i, word in enumerate(words):
        if word != "or":
            continue
        prev = words[i - 1] if i else ""
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if prev in own and nxt in own:
            continue        # enumerating the fields this rule reads, not values
        count += 1
    return count


def _check_dropped_operand(row: Dict[str, Any]) -> Optional[Finding]:
    if row["operator"] not in _DISCRETE_OPERATORS:
        return None

    offered = _alternatives_offered(row["label"], row["targets"])
    carried = len(row["what"])
    if carried >= offered:
        return None

    kept = ", ".join('"%s"' % w for w in row["what"]) or "nothing"
    return Finding(
        criterion_id=row["id"],
        check=DROPPED_OPERAND,
        severity=MISTRANSLATED,
        message=(
            "%s offers %d alternatives but the rule carries only %d: %s. The "
            "rest of the sentence will not be applied to any record."
            % (row["id"] or "This criterion", offered, carried, kept)
        ),
        detail="label offers %d alternative(s); what=%r" % (offered, row["what"]),
    )


# --------------------------------------------------------------------------
# Check 4 — inert-at-stage (F-65)
#
# The linter REPORTS this and does not gate it. F-65's own remedy proposes an
# `_validate_row` error, and an error blocks export; the decision for this
# feature is warn-clearly-never-block. Both mechanisms should exist, and this
# one can say what an error string cannot: not "invalid" but "this rule will
# never be evaluated".
#
# THE SET BELOW IS A RESTATEMENT AND IT IS NOT ALLOWED TO STAY UNCHECKED.
# `plugins/_common/evaluator.py` keeps its executable operators as an inline
# tuple inside `_eval_criterion`, so there is nothing to import (F-109 counts
# seven copies of this vocabulary already). It also cannot be derived at run
# time: `_eval_criterion` returns UNKNOWN both for "operator not supported" and
# for "this value is not comparable" — measured, `gte` against a non-numeric
# field returns UNKNOWN while `gte` against `year` returns MET. So
# `tests/test_criteria_linter.py::TestTheExecutableSetIsNotJustRetyped` probes
# the real evaluator with a well-typed operand per operator and asserts this
# table equals what it actually executes. An eighth copy, made a checked copy.
# --------------------------------------------------------------------------

INERT_AT_STAGE = "inert-at-stage"

_DETERMINISTIC_OPERATORS = frozenset({
    "equals", "contains", "regex", "in_list", "not_in", "gte", "lte", "between",
})

_EXECUTABLE_BY_STAGE = {
    "EH": _DETERMINISTIC_OPERATORS,
    "IH": _DETERMINISTIC_OPERATORS,
    # EL/IL mark every non-`llm` operator UNCERTAIN *without evaluating it*.
    "EL": frozenset({"llm"}),
    "IL": frozenset({"llm"}),
}


def executable_operators(stage: str) -> Tuple[str, ...]:
    """Which operators actually execute at ``stage``. Empty for an unknown stage."""
    return tuple(sorted(_EXECUTABLE_BY_STAGE.get(_safe_str(stage).strip().upper(), ())))


def _check_inert_at_stage(row: Dict[str, Any]) -> Optional[Finding]:
    stage = row["stage"]
    if stage not in _EXECUTABLE_BY_STAGE:
        return None                     # not this check's business; _validate_row errors
    operator = row["operator"]
    if not operator or operator in _EXECUTABLE_BY_STAGE[stage]:
        return None

    runnable = ", ".join(executable_operators(stage))
    return Finding(
        criterion_id=row["id"],
        check=INERT_AT_STAGE,
        severity=INERT,
        message=(
            "%s will never be evaluated: it is a \"%s\" rule at the %s stage, "
            "which runs %s only. No record will be included or excluded by it."
            % (row["id"] or "This criterion", operator, stage, runnable)
        ),
        detail="stage=%s operator=%s executable=%s"
               % (stage, operator, list(executable_operators(stage))),
    )


# --------------------------------------------------------------------------
# Checks 3, 5 and 6 — the quiet ones.
#
# None has a live instance: measured across the golden, the frozen study input
# and the wave-12 local-run table, none fires. They are guards, at NOTICE, and
# each bites on a table that did not come from this GUI — which is F-176's and
# F-174's recorded arrival route, a hand-edited or externally-produced table
# reaching `_parse_criteria_harmonized_csv`.
# --------------------------------------------------------------------------

UNRESOLVED_TARGET = "unresolved-target"
DUPLICATE_ID = "duplicate-id"
THRESHOLD = "threshold"

#: Not a check over a criterion but over the *table*: a row this module cannot
#: read. Found by this wave's own adversarial pass, which made `lint_criteria`
#: raise `AttributeError: 'str' object has no attribute 'get'` against a
#: docstring promising it raises nothing.
UNREADABLE_ROW = "unreadable-row"


def _check_unresolved_target(row: Dict[str, Any], columns: Sequence[str]) -> Optional[Finding]:
    known = {_safe_str(c).strip().lower() for c in columns}
    missing = [t for t in row["targets"] if t not in known]
    if not missing:
        return None
    missing_txt = ", ".join('"%s"' % m for m in missing)
    return Finding(
        criterion_id=row["id"],
        check=UNRESOLVED_TARGET,
        severity=NOTICE,
        message=(
            "%s reads %s, which this corpus does not have. Every record will "
            "come back unknown for it, and none will be included or excluded "
            "by it." % (row["id"] or "This criterion", missing_txt)
        ),
        detail="missing targets %r" % (missing,),
    )


def _check_duplicate_ids(normalised: Sequence[Dict[str, Any]]) -> List[Finding]:
    counts: Dict[str, int] = {}
    for row in normalised:
        cid = row["id"]
        if cid:
            counts[cid] = counts.get(cid, 0) + 1

    out: List[Finding] = []
    for cid, n in counts.items():
        if n < 2:
            continue
        out.append(Finding(
            criterion_id=cid,
            check=DUPLICATE_ID,
            severity=NOTICE,
            message=(
                "%s appears more than once (%d times). The LLM stages key their "
                "results by criterion id, so only the last one will be kept and "
                "the others will silently do nothing." % (cid, n)
            ),
            detail="%d rows share id %r" % (n, cid),
        ))
    return out


def _check_threshold(row: Dict[str, Any]) -> Optional[Finding]:
    raw = row["threshold"]
    if not raw:
        return None                     # blank is correct for EH/IH
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return Finding(
            criterion_id=row["id"],
            check=THRESHOLD,
            severity=NOTICE,
            message=(
                "%s has a confidence threshold of \"%s\", which is not a number. "
                "It will be read as 0.60 without saying so."
                % (row["id"] or "This criterion", raw)
            ),
            detail="threshold=%r unparseable" % (raw,),
        )
    if not (0.0 <= value <= 1.0):
        return Finding(
            criterion_id=row["id"],
            check=THRESHOLD,
            severity=NOTICE,
            message=(
                "%s has a confidence threshold of %s, which is outside 0–1. A "
                "threshold above 1 can never be met and one below 0 is always met."
                % (row["id"] or "This criterion", raw)
            ),
            detail="threshold=%r out of [0,1]" % (raw,),
        )
    # A threshold that WAS silently defaulted is byte-identical to one the user
    # chose (CL-2), so there is nothing here to report and this check does not
    # pretend otherwise.
    return None


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
    ran: List[str] = []
    skipped: List[str] = []
    findings: List[Finding] = []

    # A row this function cannot read must become a FINDING, not an exception
    # and not a silent drop. It is called from a GUI callback, where raising is
    # a crash dialog; and a dropped row is a row the user believes was checked.
    normalised: List[Dict[str, Any]] = []
    for index, row in enumerate(rows or []):
        if not isinstance(row, Mapping):
            findings.append(Finding(
                criterion_id="",
                check=UNREADABLE_ROW,
                severity=NOTICE,
                message=(
                    "Row %d could not be read as a criterion, so nothing in it "
                    "has been checked." % (index + 1)
                ),
                detail="row %d is %s, not a mapping" % (index + 1, type(row).__name__),
            ))
            continue
        normalised.append(_norm_row(row))

    concepts = _concept_map(a_columns or ())
    if concepts:
        ran.append(TARGET_MISMATCH)
        for row in normalised:
            f = _check_target_mismatch(row, concepts)
            if f is not None:
                findings.append(f)

        ran.append(UNRESOLVED_TARGET)
        for row in normalised:
            f = _check_unresolved_target(row, a_columns)
            if f is not None:
                findings.append(f)
    else:
        skipped.append(TARGET_MISMATCH)
        skipped.append(UNRESOLVED_TARGET)

    # Decidable from the table alone — no corpus needed, so these always run.
    ran.append(DROPPED_OPERAND)
    for row in normalised:
        f = _check_dropped_operand(row)
        if f is not None:
            findings.append(f)

    ran.append(INERT_AT_STAGE)
    for row in normalised:
        f = _check_inert_at_stage(row)
        if f is not None:
            findings.append(f)

    ran.append(THRESHOLD)
    for row in normalised:
        f = _check_threshold(row)
        if f is not None:
            findings.append(f)

    ran.append(DUPLICATE_ID)
    findings.extend(_check_duplicate_ids(normalised))

    findings.sort(key=lambda f: (f._rank, f.criterion_id))
    return LintReport(findings, ran=ran, skipped=skipped)
