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

Three properties shape the design and each is easy to get wrong.

*Criteria within a stage are not sequential.* `run_screen` evaluates every criterion in
a stage against that stage's full input, so per-criterion removals **overlap**: on the
reference corpus six records fail both `IC-3` and `IC-4`, so 8 + 611 = 619 while IH
actually removes 613. `CriterionPreview` therefore carries `stage_in_n` and no
cumulative field of any kind, and `StagePreview.removed_n` comes from the funnel rather
than from adding rows up. `StagePreview.overlap_n` makes the discrepancy explicit
instead of leaving a reader to discover it by subtraction.

*`llm` criteria are not evaluated here.* EL and IL are out of scope for wave 13e
(`FIX_WAVE_13E_PREVIEW.md` section (g) gives the four reasons). They are listed with
`evaluated=False` and every count `None` -- omitting them would misrepresent the table,
and `removes 0` would be a different and worse claim than `was not run`.

*`unknown` and `missing` are shown beside `removed`.* A `year` of `2018-03` is
`UNKNOWN` to a `gte` comparison, so the criterion silently does not apply to that
record and it passes unfiltered (measured, `FIX_WAVE_13E_PREVIEW.md` B-1). On this
corpus that count is zero; on a corpus of year-month strings it would be every record
and the removal count alone would show a criterion apparently working while filtering
nothing.

**Read-only.** Nothing here writes a file, and neither does anything it calls:
`run_screen` performs no file IO and does not mutate the rows handed to it. The
criteria text is produced by `exporters._criteria_csv_text`, which is the same
serialiser the bundle uses -- so the preview screens the bytes a real run will load,
not an approximation of them.

The caller does all IO: it reads the corpus and passes header and rows. That is what
makes `build_criteria_preview` a pure function and testable without a View.
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

# The deterministic stages, in pipeline order. EL and IL follow them but are not
# evaluated here; see the module docstring.
DETERMINISTIC_STAGES: Tuple[str, ...] = ("EH", "IH")
LLM_STAGES: Tuple[str, ...] = ("EL", "IL")

#: A criterion removing at least this share of the records that reached its stage is
#: called out. 0.75 is a default, not a discovery -- it is a parameter of
#: `build_criteria_preview` precisely so that it can be argued with.
DEFAULT_HIGH_REMOVAL_FRACTION = 0.75

#: How many removed record ids the rendered body prints per criterion before saying
#: how many it withheld. The model always keeps every id.
DEFAULT_MAX_IDS_SHOWN = 10


@dataclass(frozen=True)
class CriterionPreview:
    """What one criterion does to the records that reached its stage.

    There is deliberately no `out_n`, no running total and no cumulative field: a
    criterion does not hand its survivors to the next criterion, and a type that
    offered such a number would invite a display to print a funnel that does not
    exist. `stage_in_n` is the denominator for every count here.

    For a criterion that was not evaluated -- every `llm` row -- the four counts are
    `None` rather than `0`, so that "not run" cannot be misread as "removes nothing".
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
    below it. `overlap_n` is how many records were removed by more than one criterion,
    which is exactly the amount by which that sum overstates the truth.
    """

    stage: str
    in_n: int
    out_n: int
    evaluated: bool
    criteria: List[CriterionPreview] = field(default_factory=list)
    overlap_n: int = 0
    overlap_ids: List[str] = field(default_factory=list)

    @property
    def removed_n(self) -> int:
        return self.in_n - self.out_n


@dataclass(frozen=True)
class PreviewNote:
    """Something worth a reader's attention. Advisory: the preview never blocks."""

    kind: str          # zero-removal | high-removal | uncomparable | not-evaluated
    criterion_id: str
    text: str


@dataclass(frozen=True)
class PreviewDialog:
    kind: str          # showinfo | showwarning -- dispatched by the View's _SHOW
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


def build_criteria_preview(
    rows: Sequence[Dict[str, Any]],
    corpus_header: Sequence[str],
    corpus_rows: Sequence[Dict[str, str]],
    *,
    high_removal_fraction: float = DEFAULT_HIGH_REMOVAL_FRACTION,
    max_ids_shown: int = DEFAULT_MAX_IDS_SHOWN,
    id_column: str = "local_id",
) -> PreviewReport:
    """Screen `corpus_rows` with `rows` and report what each criterion did.

    `rows` are the Harmoniser's in-memory criteria rows -- the same dicts
    `_export_csv` writes. `corpus_header` and `corpus_rows` are what
    `_parse_csv_tolerant_text` produced from the A vector; the caller reads the file
    so that this function performs no IO.

    Nothing is written and neither `rows` nor `corpus_rows` is modified.
    """
    corpus_n = len(corpus_rows)
    criteria_text = _criteria_csv_text(list(rows))

    stages: List[StagePreview] = []
    survivors: List[Dict[str, str]] = list(corpus_rows)

    for stage_name in DETERMINISTIC_STAGES:
        load = _load_criteria_from_text(criteria_text, stage_name)
        if not load.criteria:
            continue
        stages.append(
            _run_one_stage(stage_name, load, corpus_header, survivors, id_column)
        )
        survivors = stages[-1]._out_rows  # type: ignore[attr-defined]

    survivors_n = len(survivors)
    stages.extend(_llm_stages(rows, survivors_n))

    notes = _notes(stages, high_removal_fraction)
    return PreviewReport(
        corpus_n=corpus_n,
        survivors_n=survivors_n,
        stages=stages,
        notes=notes,
        dialog=_dialog(corpus_n, survivors_n, stages, notes, max_ids_shown),
        log_line=_log_line(corpus_n, survivors_n, stages),
    )


# --- the screening pass ------------------------------------------------------

def _run_one_stage(stage_name, load, corpus_header, in_rows, id_column) -> StagePreview:
    """One `run_screen` call, turned into a `StagePreview`.

    The impacts are `run_screen`'s own, not recomputed here: a preview that counted
    its own way could disagree with the run it is previewing, which is the one thing
    it must never do.
    """
    parse = ParseReport(header=list(corpus_header), rows=list(in_rows), skipped=[])
    full, out, _counts, impacts, evals, _cancelled = run_screen(
        parse, load, threading.Event(), stage=stage_name
    )

    # Which records each criterion removed, and which records more than one removed.
    removed_by: Dict[str, List[str]] = {}
    fail_count: Dict[str, int] = {}
    for row, ev in zip(full, evals):
        rid = str(row.get(id_column, "") or "")
        failed = ev.get("failed", []) or []
        for cid in failed:
            removed_by.setdefault(cid, []).append(rid)
        if len(failed) > 1:
            fail_count[rid] = len(failed)

    crits = [
        CriterionPreview(
            stage=stage_name,
            criterion_id=c.cid,
            ctype=c.ctype,
            operator=c.operator,
            target=",".join(c.targets),
            what=list(c.what_list),
            label=c.label,
            stage_in_n=len(in_rows),
            evaluated=True,
            removed_n=impacts.get(c.cid, {}).get("failed", 0),
            missing_n=impacts.get(c.cid, {}).get("missing", 0),
            unknown_n=impacts.get(c.cid, {}).get("unknown", 0),
            met_n=impacts.get(c.cid, {}).get("met", 0),
            removed_ids=list(removed_by.get(c.cid, [])),
        )
        for c in load.criteria
    ]

    stage = StagePreview(
        stage=stage_name,
        in_n=len(in_rows),
        out_n=len(out),
        evaluated=True,
        criteria=crits,
        overlap_n=len(fail_count),
        overlap_ids=sorted(fail_count),
    )
    # The survivors feed the next stage. Carried on the instance rather than in the
    # public type: the report is about counts, and a caller that wants rows should
    # run the screen itself.
    object.__setattr__(stage, "_out_rows", out)
    return stage


def _llm_stages(rows, survivors_n) -> List[StagePreview]:
    """EL and IL, listed and explicitly not evaluated.

    A row whose operator is not `llm` is *also* not evaluated at an LLM stage -- EL
    and IL run `llm` and nothing else, marking every other operator `UNCERTAIN`
    without evaluating it (F-65). Both cases are reported here, with different
    reasons, because they are different problems for the reader: one is "this wave
    does not do LLM", the other is "this rule will never run anywhere".
    """
    out: List[StagePreview] = []
    for stage_name in LLM_STAGES:
        members = [
            r for r in rows
            if str(r.get("stage", "")).strip().upper() == stage_name
            and _enabled(r)
        ]
        if not members:
            continue
        crits = []
        for r in members:
            op = str(r.get("operator", "")).strip().lower()
            if op == "llm":
                reason = (
                    "not evaluated: %s asks a language model, and the preview makes "
                    "no model calls" % stage_name
                )
            else:
                reason = (
                    "will never run: %s evaluates only `llm` criteria, so a `%s` rule "
                    "at this stage is marked UNCERTAIN without being evaluated (F-65)"
                    % (stage_name, op)
                )
            crits.append(CriterionPreview(
                stage=stage_name,
                criterion_id=str(r.get("id", "")),
                ctype=str(r.get("type", "")),
                operator=op,
                target=str(r.get("target", "")),
                what=list(r.get("what", []) or []),
                label=str(r.get("label", "")),
                stage_in_n=survivors_n,
                evaluated=False,
                not_evaluated_reason=reason,
            ))
        out.append(StagePreview(
            stage=stage_name, in_n=survivors_n, out_n=survivors_n,
            evaluated=False, criteria=crits,
        ))
    return out


def _enabled(row) -> bool:
    """Match `_load_criteria_from_text`'s `_truthy` gate, so the two agree."""
    v = row.get("enabled", True)
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() not in {"0", "false", "no", "", "none"}


# --- what is worth saying ----------------------------------------------------

def _notes(stages, high_removal_fraction) -> List[PreviewNote]:
    notes: List[PreviewNote] = []
    for s in stages:
        for c in s.criteria:
            if not c.evaluated:
                notes.append(PreviewNote(
                    kind="not-evaluated", criterion_id=c.criterion_id,
                    text="%s %s" % (c.criterion_id, c.not_evaluated_reason)))
                continue

            if c.removed_n == 0:
                notes.append(PreviewNote(
                    kind="zero-removal", criterion_id=c.criterion_id,
                    text=_zero_removal_text(c)))
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
    return notes


def _zero_removal_text(c) -> str:
    """Report the fact and offer the reason the data supports -- never a verdict.

    A criterion that removes nothing may be exactly right: wave 13d's repaired EC-4
    is correct and removes zero, because this corpus contains no conference venues.
    """
    head = "%s removed no records." % c.criterion_id
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


def _dialog(corpus_n, survivors_n, stages, notes, max_ids_shown) -> PreviewDialog:
    lines: List[str] = ["%d records in the corpus." % corpus_n, ""]

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
            lines.append("     %-6s %-9s %-24s removes %d of %d"
                         % (c.criterion_id, c.operator, c.target,
                            c.removed_n, c.stage_in_n))
            extra = []
            if c.missing_n:
                extra.append("%d record%s no %s" % (
                    c.missing_n, (" has" if c.missing_n == 1 else "s have"), c.target))
            if c.unknown_n:
                extra.append("%d record%s not be compared" % (
                    c.unknown_n, (" could" if c.unknown_n == 1 else "s could")))
            if extra:
                lines.append("            (%s)" % "; ".join(extra))
            if c.removed_ids:
                shown = c.removed_ids[:max_ids_shown]
                tail = ""
                if len(c.removed_ids) > len(shown):
                    tail = ", and %d more" % (len(c.removed_ids) - len(shown))
                lines.append("            removes: %s%s" % (", ".join(shown), tail))

        if s.overlap_n:
            ids = ", ".join(s.overlap_ids[:max_ids_shown])
            more = ("" if len(s.overlap_ids) <= max_ids_shown
                    else ", and %d more" % (len(s.overlap_ids) - max_ids_shown))
            involved = sorted({c.criterion_id for c in s.criteria
                               if c.evaluated and c.removed_n})
            lines.append("")
            lines.append("     %d records are removed by more than one of %s (%s%s), "
                         "so the counts above overlap and do not add up to %d."
                         % (s.overlap_n, " and ".join(involved), ids, more,
                            s.removed_n))
        lines.append("")

    lines.append("%d of %d records survive the deterministic stages."
                 % (survivors_n, corpus_n))

    flagged = [n for n in notes if n.kind in ("zero-removal", "high-removal",
                                              "uncomparable")]
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
        kind=("showwarning" if flagged else "showinfo"),
        title="Criteria preview",
        body="\n".join(lines),
    )
