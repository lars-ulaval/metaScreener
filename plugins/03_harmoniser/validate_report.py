# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
validate_report.py — what the Validate button decides, as a pure function.

`ui.py::HarmoniserView::_validate` used to hold this inline: it looped the rows,
counted how many had errors and how many had warnings, threw the per-check strings
away, and picked a dialog from the two counts. None of that needs a widget, and
while it lived inside a View it could not be tested — `tests/conftest.py` replaces
`tkinter` with a MagicMock, so a View builds nothing real.

Extracted here **unchanged**, so the behaviour can be pinned before it is altered.
`tests/test_harmoniser_validate_wiring.py` characterises it as it stands, defects
included, and those assertions are what a later commit has to flip in the open.

**Pure.** No Tk, no file IO, no global state, no network, no clock. It reads its
arguments and returns a report; the View does the talking.

The defects it currently reproduces, all F-173:

  - it reports COUNTS and never identities, so "1 row(s) have errors" leaves the
    user to find the row by tint and the check by guesswork;
  - `_validate_row`'s per-check strings are computed here and discarded;
  - "Validation OK — All good" is shown even with warnings outstanding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from .inference import _validate_row

#: Treeview tags `ui.py::HarmoniserView::_render_rows` already binds to colours:
#: `error` -> #ffe5e5, `warn` -> #fff6d5.
TAG_ERROR = "error"
TAG_WARN = "warn"
TAG_NONE = ""


@dataclass(frozen=True)
class Dialog:
    """What the View should put on screen. `kind` maps to a messagebox call."""

    kind: str        # "error" | "info" | "warning"
    title: str
    body: str


@dataclass(frozen=True)
class RowMark:
    """How one row should be tinted, and why."""

    criterion_id: str
    tag: str
    errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationReport:
    """The whole decision. `ok` is what `_validate` returns, and it gates export."""

    ok: bool
    n_rows: int
    n_error_rows: int
    n_warning_rows: int
    marks: Tuple[RowMark, ...]
    dialog: Optional[Dialog]
    log_line: str


def build_validation_report(
    rows: Sequence[Mapping[str, Any]],
    a_columns: Sequence[str],
    *,
    show_ok: bool = True,
) -> ValidationReport:
    """Decide what Validate should say and how the rows should be tinted.

    ``show_ok=False`` is the export path: the same decision, with no dialog. It
    does **not** change ``ok``, so export gating is unaffected by whether a
    dialog was requested.
    """
    if not rows:
        # `_validate` returns False here without saying anything at all. Kept.
        return ValidationReport(
            ok=False, n_rows=0, n_error_rows=0, n_warning_rows=0,
            marks=(), dialog=None, log_line="",
        )

    if not a_columns:
        return ValidationReport(
            ok=False, n_rows=len(rows), n_error_rows=0, n_warning_rows=0,
            marks=(),
            dialog=Dialog("warning", "Missing A", "Load A vector first."),
            log_line="",
        )

    marks: List[RowMark] = []
    n_err = 0
    n_warn = 0
    for row in rows:
        # ONE call per row. `_validate_row` is not a pure predicate — checks 6,
        # 7, 11 and 12 rewrite the row they inspect — so calling it a second
        # time to recount would apply those rewrites twice. The original had
        # exactly one call here, and this keeps it.
        errs, warns = _validate_row(row, a_columns)

        # Two INDEPENDENT ifs, as the original: a row with both errors and
        # warnings increments both counters. The tint below is exclusive. So the
        # counts and the tints disagree for such a row — reproduced rather than
        # tidied, because tidying it here would be a behaviour change hidden
        # inside an extraction.
        if errs:
            n_err += 1
        if warns:
            n_warn += 1

        if errs:
            tag = TAG_ERROR
        elif warns:
            tag = TAG_WARN
        else:
            tag = TAG_NONE

        marks.append(RowMark(
            criterion_id=str(row.get("id", "") or ""),
            tag=tag,
            errors=tuple(errs or ()),
            warnings=tuple(warns or ()),
        ))

    log_line = "Validate: %d rows, errors=%d, warnings=%d" % (len(rows), n_err, n_warn)

    dialog: Optional[Dialog] = None
    if n_err > 0:
        if show_ok:
            dialog = Dialog(
                "error", "Validation failed",
                "%d row(s) have errors. Fix them before export." % n_err,
            )
        return ValidationReport(
            ok=False, n_rows=len(rows), n_error_rows=n_err, n_warning_rows=n_warn,
            marks=tuple(marks), dialog=dialog, log_line=log_line,
        )

    if show_ok:
        # F-173: "All good" regardless of `n_warn`.
        dialog = Dialog("info", "Validation OK", "All good. Warnings: %d" % n_warn)

    return ValidationReport(
        ok=True, n_rows=len(rows), n_error_rows=n_err, n_warning_rows=n_warn,
        marks=tuple(marks), dialog=dialog, log_line=log_line,
    )
