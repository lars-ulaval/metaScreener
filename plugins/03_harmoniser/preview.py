# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""preview.py - what each criterion will do to a corpus, before a stage is run.

The Harmoniser can tell you a rule is well-formed (`linter.py`) and that it says what
its prose says (`validate_report.py`). Neither can tell you what it will *do*. Wave
13d's repaired `EC-4` removes zero records from the reference corpus -- correct, and
invisible -- while `IC-4` removes 611 of 760, 80% of the corpus by one rule, and
nothing said that either. This module answers one question per criterion: **how many
records does it remove, out of how many, and which ones.**

Four properties shape the design and each is easy to get wrong.

*Criteria within a stage are not sequential.* `run_screen` evaluates every criterion in
a stage against that stage's full input, so per-criterion removals **overlap**: on the
reference corpus six records fail both `IC-3` and `IC-4`, so 8 + 611 = 619 while IH
actually removes 613. `CriterionPreview` therefore carries `stage_in_n` and no
cumulative field of any kind, and `StagePreview.removed_n` comes from the funnel rather
than from adding rows up.

*A criterion that will not run must never be reported as one that removes nothing.*
That covers `llm` rules at EL/IL (out of scope for this wave), and -- the case an
adversarial review found in the first cut -- rules whose operator does not execute at
their stage **in either direction**. An `llm` rule parked at EH is marked `UNKNOWN` for
every record without being evaluated, and the first cut rendered that as "check the
`title` column: 775 records have no value there at all", blaming the corpus for a
defect in the rule. Which operators execute where is asked of
`linter.executable_operators`, not restated here.

*Whole-stage effects need their own check.* Two include rules partitioning `year` can
each remove a modest share and between them leave one record of 776. Per-criterion
thresholds cannot see that, so `_notes` checks the funnel as well.

*`unknown` and `missing` are shown beside `removed`.* A `year` of `2018-03` is
`UNKNOWN` to a `gte` comparison, so the criterion silently does not apply to that
record and it passes unfiltered (measured, `FIX_WAVE_13E_PREVIEW.md` B-1).

**Read-only.** Nothing here writes a file, and neither does anything it calls. The
criteria text is produced by `exporters._criteria_csv_text`, the same serialiser the
bundle uses, so the preview screens the bytes a real run will load. The caller does all
IO, which is what makes `build_criteria_preview` pure and testable without a View.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from plugins._common.parser import (
    ParseReport,
    _load_criteria_from_text,
)
from plugins._common.runner import run_screen

from .exporters import _criteria_csv_text
from .linter import executable_operators as _linter_executable_operators

#: Stages a preview can run without a model, in pipeline order.
DETERMINISTIC_STAGES: Tuple[str, ...] = ("EH", "IH")
#: Stages that need a model. Listed, never evaluated -- see the module docstring.
LLM_STAGES: Tuple[str, ...] = ("EL", "IL")
KNOWN_STAGES: Tuple[str, ...] = DETERMINISTIC_STAGES + LLM_STAGES

#: A criterion removing at least this share of the records that reached its stage is
#: called out. A default, not a discovery -- it is a parameter so it can be argued with.
DEFAULT_HIGH_REMOVAL_FRACTION = 0.75

#: A *stage* removing at least this share of its input is called out separately,
#: because criteria that are individually modest can be collectively lethal. Set well
#: above the per-criterion bar: the reference corpus's IH removes 81% and is a normal,
#: intended screen, not a wipeout.
DEFAULT_STAGE_WIPEOUT_FRACTION = 0.95

#: How many ids the rendered body prints before saying how many it withheld. The model
#: always keeps every id.
DEFAULT_MAX_IDS_SHOWN = 10


def _executable_operators(stage: str) -> Tuple[str, ...]:
    """Which operators actually execute at `stage`.

    Delegated to `linter.py` rather than restated. The linter already owns this
    vocabulary, it is the module that reports F-65, and two copies of it would drift
    -- which is F-109's entire subject.
    """
    return _linter_executable_operators(stage)


@dataclass(frozen=True)
class CriterionPreview:
    """What one criterion does to the records that reached its stage.

    There is deliberately no `out_n`, no running total and no cumulative field: a
    criterion does not hand its survivors to the next criterion, and a type that
    offered such a number would invite a display to print a funnel that does not
    exist. `stage_in_n` is the denominator for every count here.

    When `evaluated` is `False` the four counts are `None` rather than `0`, so that
    "was not run" cannot be misread as "removes nothing". Three different situations
    set it: an `llm` rule at an LLM stage (this wave makes no model calls), a rule
    whose operator does not execute at its stage at all (F-65 and its mirror), and a
    rule whose id collides with another's so its results cannot be attributed.
    """

    stage: str
    criterion_id: str
    ctype: str
    operator: str
    target: str
    what: List[str]
    label: str
    stage_in_n: int
    evaluated: bool
    removed_n: Optional[int] = None
    missing_n: Optional[int] = None
    unknown_n: Optional[int] = None
    met_n: Optional[int] = None
    removed_ids: List[str] = field(default_factory=list)
    not_evaluated_reason: str = ""

    @property
    def removed_fraction(self) -> float:
        if not self.evaluated or not self.stage_in_n:
            return 0.0
        return (self.removed_n or 0) / float(self.stage_in_n)


@dataclass(frozen=True)
class StagePreview:
    """One stage's funnel, and the criteria that were applied within it.

    `removed_n` is `in_n - out_n` -- the funnel -- and never the sum of the criteria
    below it.

    `overlap_n` and `overcount_n` are **different numbers** and the distinction is not
    pedantic. `overlap_n` counts records removed by more than one criterion;
    `overcount_n` is how much the naive sum of per-criterion removals overstates the
    stage total. They are equal only when every overlapping record fails exactly two
    criteria -- true on the reference corpus, where both are 6, and false as soon as a
    record fails three, where one record gives `overlap_n=1` and `overcount_n=2`. The
    first cut carried only the record count and a docstring claiming it was both.
    """

    stage: str
    in_n: int
    out_n: int
    evaluated: bool
    criteria: List[CriterionPreview] = field(default_factory=list)
    overlap_n: int = 0
    overcount_n: int = 0
    overlap_ids: List[str] = field(default_factory=list)
    overlap_criteria: List[str] = field(default_factory=list)

    @property
    def removed_n(self) -> int:
        return self.in_n - self.out_n

    @property
    def removed_fraction(self) -> float:
        return (self.removed_n / float(self.in_n)) if self.in_n else 0.0


@dataclass(frozen=True)
class PreviewNote:
    """Something worth a reader's attention. Advisory: the preview never blocks."""

    kind: str          # zero-removal | high-removal | stage-wipeout | uncomparable
                       # | not-evaluated | duplicate-id | uncovered | loader-warning
    criterion_id: str
    text: str


@dataclass(frozen=True)
class PreviewDialog:
    #: One of the keys of `ui._SHOW` -- "info", "warning" or "error". NOT the
    #: messagebox function name: `_SHOW[kind]` is how the View dispatches, so
    #: "showinfo" here raises KeyError at the moment a user presses the button.
    kind: str
    title: str
    body: str


@dataclass(frozen=True)
class PreviewReport:
    corpus_n: int
    survivors_n: int
    stages: List[StagePreview]
    notes: List[PreviewNote]
    dialog: PreviewDialog
    log_line: str
    skipped_n: int = 0


def build_criteria_preview(
    rows: Sequence[Dict[str, Any]],
    corpus_header: Sequence[str],
    corpus_rows: Sequence[Dict[str, str]],
    *,
    high_removal_fraction: float = DEFAULT_HIGH_REMOVAL_FRACTION,
    stage_wipeout_fraction: float = DEFAULT_STAGE_WIPEOUT_FRACTION,
    max_ids_shown: int = DEFAULT_MAX_IDS_SHOWN,
    id_column: str = "local_id",
    skipped_n: int = 0,
) -> PreviewReport:
    """Screen `corpus_rows` with `rows` and report what each criterion did.

    `rows` are the Harmoniser's in-memory criteria rows -- the same dicts
    `_export_csv` writes. `corpus_header` and `corpus_rows` are what
    `_parse_csv_tolerant_text` produced from the A vector, and `skipped_n` is how many
    records that parse rejected, so the report can say so rather than quietly
    presenting the survivors as the whole file. The caller reads the file; this
    function performs no IO.

    Nothing is written and neither `rows` nor `corpus_rows` is modified.
    """
    corpus_n = len(corpus_rows)
    header_set = {str(h) for h in corpus_header}
    criteria_text = _criteria_csv_text(list(rows))

    stages: List[StagePreview] = []
    warnings: List[str] = []
    survivors: List[Dict[str, str]] = list(corpus_rows)

    for stage_name in DETERMINISTIC_STAGES:
        load = _load_criteria_from_text(criteria_text, stage_name)
        warnings.extend(load.warnings)
        if not load.criteria:
            continue
        stage, survivors = _run_one_stage(
            stage_name, load, corpus_header, survivors, id_column)
        stages.append(stage)

    survivors_n = len(survivors)
    stages.extend(_llm_stages(rows, survivors_n))

    notes = _notes(stages, header_set, high_removal_fraction,
                   stage_wipeout_fraction)
    notes.extend(_uncovered_notes(rows))
    notes.extend(PreviewNote(kind="loader-warning", criterion_id="", text=w)
                 for w in _dedupe(warnings))

    return PreviewReport(
        corpus_n=corpus_n,
        survivors_n=survivors_n,
        stages=stages,
        notes=notes,
        skipped_n=skipped_n,
        dialog=_dialog(corpus_n, survivors_n, stages, notes, max_ids_shown,
                       skipped_n),
        log_line=_log_line(corpus_n, survivors_n, stages),
    )


def _dedupe(items: Sequence[str]) -> List[str]:
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


# --- the screening pass ------------------------------------------------------

def _run_one_stage(stage_name, load, corpus_header, in_rows, id_column):
    """One `run_screen` call, turned into a `StagePreview` plus its survivors.

    The impacts are `run_screen`'s own, not recomputed here: a preview that counted
    its own way could disagree with the run it is previewing, which is the one thing
    it must never do.

    Survivors are returned rather than stashed on the frozen dataclass. The first cut
    attached them with `object.__setattr__`, which meant every `PreviewReport` handed
    back to a caller carried several hundred corpus rows -- a CL-3 tripwire for the
    first caller that cached one.
    """
    parse = ParseReport(header=list(corpus_header), rows=list(in_rows), skipped=[])
    full, out, _counts, impacts, evals, _cancelled = run_screen(
        parse, load, threading.Event(), stage=stage_name)

    runs_here = set(_executable_operators(stage_name))
    seen: Dict[str, int] = {}
    for c in load.criteria:
        seen[c.cid] = seen.get(c.cid, 0) + 1
    duplicated = {cid for cid, n in seen.items() if n > 1}

    # Which records each criterion removed, and which records more than one removed.
    removed_by: Dict[str, List[str]] = {}
    fail_counts: Dict[str, int] = {}
    for row, ev in zip(full, evals):
        rid = str(row.get(id_column, "") or "")
        failed = ev.get("failed", []) or []
        for cid in failed:
            removed_by.setdefault(cid, []).append(rid)
        if len(failed) > 1:
            fail_counts[rid] = len(failed)

    crits: List[CriterionPreview] = []
    for c in load.criteria:
        common = dict(
            stage=stage_name, criterion_id=c.cid, ctype=c.ctype,
            operator=c.operator, target=",".join(c.targets),
            what=list(c.what_list), label=c.label, stage_in_n=len(in_rows))

        if c.operator not in runs_here:
            crits.append(CriterionPreview(
                evaluated=False, **common,
                not_evaluated_reason=(
                    "will never run: %s evaluates only %s, so a `%s` rule at this "
                    "stage is marked UNCERTAIN without being evaluated (F-65)"
                    % (stage_name, ", ".join(_executable_operators(stage_name)),
                       c.operator))))
            continue

        if c.cid in duplicated:
            crits.append(CriterionPreview(
                evaluated=False, **common,
                not_evaluated_reason=(
                    "cannot be reported on its own: another criterion has the id "
                    "`%s`, and results are keyed by id, so their counts are merged. "
                    "Give them distinct ids to see either one." % c.cid)))
            continue

        imp = impacts.get(c.cid, {})
        crits.append(CriterionPreview(
            evaluated=True, **common,
            removed_n=imp.get("failed", 0), missing_n=imp.get("missing", 0),
            unknown_n=imp.get("unknown", 0), met_n=imp.get("met", 0),
            removed_ids=list(removed_by.get(c.cid, []))))

    reportable = {c.criterion_id for c in crits if c.evaluated}
    overlap_ids = sorted(fail_counts)
    stage = StagePreview(
        stage=stage_name,
        in_n=len(in_rows),
        out_n=len(out),
        evaluated=True,
        criteria=crits,
        overlap_n=len(fail_counts),
        overcount_n=sum(n - 1 for n in fail_counts.values()),
        overlap_ids=overlap_ids,
        overlap_criteria=sorted(
            cid for cid in reportable
            if set(removed_by.get(cid, ())) & set(overlap_ids)),
    )
    return stage, out


def _llm_stages(rows, survivors_n) -> List[StagePreview]:
    """EL and IL, listed and explicitly not evaluated.

    A row whose operator is not `llm` is *also* not evaluated at an LLM stage (F-65).
    Both cases are reported, with different reasons, because they are different
    problems for the reader: one is "this wave does not do LLM", the other is "this
    rule will never run anywhere".
    """
    out: List[StagePreview] = []
    for stage_name in LLM_STAGES:
        runs_here = set(_executable_operators(stage_name))
        members = [r for r in rows
                   if _stage_of(r) == stage_name and _enabled(r)]
        if not members:
            continue
        crits = []
        for r in members:
            op = str(r.get("operator", "")).strip().lower()
            if op in runs_here:
                reason = ("not evaluated: %s asks a language model, and the preview "
                          "makes no model calls" % stage_name)
            else:
                reason = ("will never run: %s evaluates only %s, so a `%s` rule at "
                          "this stage is marked UNCERTAIN without being evaluated "
                          "(F-65)" % (stage_name,
                                      ", ".join(_executable_operators(stage_name)),
                                      op))
            crits.append(CriterionPreview(
                stage=stage_name, criterion_id=str(r.get("id", "")),
                ctype=str(r.get("type", "")), operator=op,
                target=str(r.get("target", "")), what=_as_list(r.get("what")),
                label=str(r.get("label", "")), stage_in_n=survivors_n,
                evaluated=False, not_evaluated_reason=reason))
        out.append(StagePreview(stage=stage_name, in_n=survivors_n,
                                out_n=survivors_n, evaluated=False,
                                criteria=crits))
    return out


def _as_list(what) -> List[str]:
    """`list("abc")` is `['a','b','c']`, which is never what a `what` cell means."""
    if what is None:
        return []
    if isinstance(what, str):
        return [what] if what else []
    return [w for w in what if w is not None]


def _stage_of(row) -> str:
    return str(row.get("stage", "") or "").strip().upper()


def _enabled(row) -> bool:
    """Mirror the gate the exported CSV actually applies, not the one it looks like.

    `_criteria_csv_text` writes `1 if bool(r.get("enabled", True)) else 0`, and
    `bool("0")` is `True`. So the effective test is Python truthiness, **not**
    `parser._truthy`'s whitelist -- a row carrying the string `"0"` is exported
    enabled and does run. An earlier version of this helper claimed in its docstring
    to match `_truthy` and did not, which made the preview disagree with itself: the
    deterministic path (reading the exported CSV) showed such a row while the LLM
    listing (reading the raw dicts) hid it. Mirroring the writer is what keeps the
    two halves consistent; whether the writer is *right* is PV-6.
    """
    return bool(row.get("enabled", True))


# --- what is worth saying ----------------------------------------------------

def _notes(stages, header_set, high_removal_fraction,
           stage_wipeout_fraction) -> List[PreviewNote]:
    notes: List[PreviewNote] = []
    for s in stages:
        for c in s.criteria:
            if not c.evaluated:
                kind = ("duplicate-id" if "distinct ids" in c.not_evaluated_reason
                        else "not-evaluated")
                notes.append(PreviewNote(
                    kind=kind, criterion_id=c.criterion_id,
                    text="%s %s" % (c.criterion_id, c.not_evaluated_reason)))
                continue

            if c.removed_n == 0:
                notes.append(PreviewNote(
                    kind="zero-removal", criterion_id=c.criterion_id,
                    text=_zero_removal_text(c, header_set)))
            elif c.removed_fraction >= high_removal_fraction:
                notes.append(PreviewNote(
                    kind="high-removal", criterion_id=c.criterion_id,
                    text="%s removed %d of the %d records that reached it (%.0f%%). "
                         "That is most of your corpus removed by one rule -- confirm "
                         "it is what you meant."
                         % (c.criterion_id, c.removed_n, c.stage_in_n,
                            100.0 * c.removed_fraction)))

            if c.unknown_n:
                notes.append(PreviewNote(
                    kind="uncomparable", criterion_id=c.criterion_id,
                    text="%s could not be compared against %d of %d records -- their "
                         "`%s` value is present but not in a form this operator can "
                         "read, so the rule does not apply to them and they pass "
                         "unfiltered."
                         % (c.criterion_id, c.unknown_n, c.stage_in_n, c.target)))

        # The whole-stage check. Criteria that are individually modest can be
        # collectively lethal, and no per-criterion threshold can see that.
        if s.evaluated and s.in_n and s.removed_fraction >= stage_wipeout_fraction:
            notes.append(PreviewNote(
                kind="stage-wipeout", criterion_id=s.stage,
                text="%s removed %d of the %d records that reached it and left %d. "
                     "Taken together these criteria remove almost everything -- check "
                     "that they are not contradicting one another."
                     % (s.stage, s.removed_n, s.in_n, s.out_n)))
    return notes


def _uncovered_notes(rows) -> List[PreviewNote]:
    """Criteria no stage will ever see, because their `stage` cell is not a stage.

    `parser.py::_normalize_structured_row` writes `stage=""` for anything it does not
    recognise, so an imported table with a typo lands here. The row stays visible in
    the Harmonised-criteria table, and without this the preview would report on the
    others and close with a total that reads as complete.
    """
    lost = [str(r.get("id", "") or "?") for r in rows
            if _enabled(r) and _stage_of(r) not in KNOWN_STAGES]
    if not lost:
        return []
    return [PreviewNote(
        kind="uncovered", criterion_id=", ".join(lost),
        text="%d criterion/criteria are not at any known stage and were not "
             "previewed at all: %s. Their `stage` cell is blank or unrecognised, so "
             "no stage will run them. Set it to one of %s."
             % (len(lost), ", ".join(lost), ", ".join(KNOWN_STAGES)))]


def _zero_removal_text(c, header_set) -> str:
    """Report the fact and offer the reason the data supports -- never a verdict.

    A criterion that removes nothing may be exactly right: wave 13d's repaired EC-4
    is correct and removes zero, because this corpus contains no conference venues.

    `_eval_criterion` returns `MISSING` for three different causes and the first cut
    rendered all three as "records have no value there at all" -- including the case
    where the column is not in the corpus, which sent the reader to look at a column
    that does not exist.
    """
    head = "%s removed no records." % c.criterion_id
    targets = [t for t in (c.target or "").split(",") if t.strip()]

    if not targets:
        return (head + " It has no target column, so it was treated as MISSING for "
                       "every record and removed nothing. Give it a target.")

    absent = [t for t in targets if t not in header_set]
    if absent:
        return (head + " Its target %s not in this corpus -- the A vector does not "
                       "have %s -- so it was treated as MISSING for every record. "
                       "Point it at a column that exists."
                % (("columns are" if len(absent) > 1 else "column is"),
                   ", ".join("`%s`" % a for a in absent)))

    if c.missing_n:
        return (head + " If you expected it to remove some, check the `%s` column: "
                       "%d of %d records have no value there at all, and a record "
                       "with no value is kept. A criterion that removes nothing may "
                       "still be exactly right."
                % (c.target, c.missing_n, c.stage_in_n))

    return (head + " Every one of the %d records that reached it was kept. A "
                   "criterion that removes nothing may still be exactly right."
            % c.stage_in_n)


# --- rendering ---------------------------------------------------------------

def _log_line(corpus_n, survivors_n, stages) -> str:
    hops = ", ".join("%s %d->%d" % (s.stage, s.in_n, s.out_n)
                     for s in stages if s.evaluated)
    if not hops:
        return "Preview: %d records, no deterministic criteria, %d survive" % (
            corpus_n, survivors_n)
    return "Preview: %d records, %s, %d survive" % (corpus_n, hops, survivors_n)


def _dialog(corpus_n, survivors_n, stages, notes, max_ids_shown,
            skipped_n) -> PreviewDialog:
    lines: List[str] = ["%d records in the corpus." % corpus_n]
    if skipped_n:
        lines.append("(%d further record%s skipped by the parser and will not be "
                     "screened.)" % (skipped_n, " was" if skipped_n == 1 else "s were"))
    lines.append("")

    for s in stages:
        if not s.evaluated:
            lines.append("%s - not evaluated by this preview" % s.stage)
            for c in s.criteria:
                lines.append("     %-6s %-9s %-24s %s"
                             % (c.criterion_id, c.operator, c.target,
                                c.not_evaluated_reason))
            lines.append("")
            continue

        lines.append("%s - %d in, %d out (%d removed)"
                     % (s.stage, s.in_n, s.out_n, s.removed_n))
        for c in s.criteria:
            if not c.evaluated:
                lines.append("     %-6s %-9s %-24s %s"
                             % (c.criterion_id, c.operator, c.target,
                                c.not_evaluated_reason))
                continue
            lines.append("     %-6s %-9s %-24s removes %d of %d"
                         % (c.criterion_id, c.operator, c.target,
                            c.removed_n, c.stage_in_n))
            extra = []
            if c.missing_n:
                extra.append("%d record%s no %s" % (
                    c.missing_n, (" has" if c.missing_n == 1 else "s have"),
                    c.target or "target"))
            if c.unknown_n:
                extra.append("%d record%s not be compared" % (
                    c.unknown_n, (" could" if c.unknown_n == 1 else "s could")))
            if extra:
                lines.append("            (%s)" % "; ".join(extra))
            if c.removed_ids:
                shown = c.removed_ids[:max_ids_shown]
                tail = ("" if len(c.removed_ids) <= len(shown)
                        else ", and %d more" % (len(c.removed_ids) - len(shown)))
                lines.append("            removes: %s%s" % (", ".join(shown), tail))

        if s.overlap_n:
            ids = ", ".join(s.overlap_ids[:max_ids_shown])
            more = ("" if len(s.overlap_ids) <= max_ids_shown
                    else ", and %d more" % (len(s.overlap_ids) - max_ids_shown))
            lines.append("")
            lines.append("     %d record%s removed by more than one of %s (%s%s), "
                         "so the counts above overlap and do not add up to %d."
                         % (s.overlap_n, (" is" if s.overlap_n == 1 else "s are"),
                            " and ".join(s.overlap_criteria), ids, more,
                            s.removed_n))
        lines.append("")

    lines.append("%d of %d records survive the deterministic stages."
                 % (survivors_n, corpus_n))

    flagged = [n for n in notes if n.kind in (
        "zero-removal", "high-removal", "stage-wipeout", "uncomparable",
        "duplicate-id", "uncovered", "loader-warning")]
    if flagged:
        lines.append("")
        for n in flagged:
            lines.append("  ! %s" % n.text)

    not_run = [n for n in notes if n.kind == "not-evaluated"]
    if not_run:
        lines.append("")
        for n in not_run:
            lines.append("  o %s" % n.text)

    return PreviewDialog(
        kind=("warning" if flagged else "info"),
        title="Criteria preview",
        body="\n".join(lines),
    )
