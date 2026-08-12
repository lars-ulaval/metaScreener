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

from dataclasses import dataclass, field
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple

from .inference import _validate_row
from .linter import Finding, lint_criteria

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
    """The whole decision. `ok` is what `_validate` returns, and it gates export.

    ``findings`` are the linter's. **They are deliberately absent from every
    computation of ``ok``** — a translation warning must never stop a researcher
    harmonising, editing, exporting or running a stage. The one thing that gates
    export is ``_validate_row``'s errors, exactly as before.
    """

    ok: bool
    n_rows: int
    n_error_rows: int
    n_warning_rows: int
    marks: Tuple[RowMark, ...]
    dialog: Optional[Dialog]
    log_line: str
    findings: Tuple[Finding, ...] = ()
    #: Non-empty when the linter itself raised. The Validate path completes and
    #: says so rather than dying; `lint_criteria` promises it raises nothing,
    #: and this is what happens when that promise is wrong.
    lint_error: str = ""


def build_validation_report(
    rows: Sequence[Mapping[str, Any]],
    a_columns: Sequence[str],
    *,
    show_ok: bool = True,
    lint: Optional[Callable[..., Any]] = None,
) -> ValidationReport:
    """Decide what Validate should say and how the rows should be tinted.

    ``show_ok=False`` is the export path: the same decision, with no dialog. It
    does **not** change ``ok``, so export gating is unaffected by whether a
    dialog was requested.

    ``lint`` is injectable so a test can induce a failing linter; production
    passes nothing and gets `linter.py::lint_criteria`.
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

    # THE LINTER, wired here rather than in the View.
    #
    # Session A proposed "one call after `_validate`'s loop". The loop is now in
    # this function, so that is where the call goes — and it matters that it is
    # here and not in `_validate`: a call in the View could not be tested, which
    # is the reason this module exists at all.
    #
    # Defensive despite `lint_criteria` promising it raises nothing. It is
    # called from a GUI callback, an uncaught exception there is a crash dialog,
    # and "it promised" is not a reason to let the Validate button die.
    findings: Tuple[Finding, ...] = ()
    lint_error = ""
    try:
        findings = tuple((lint or lint_criteria)(rows, a_columns))
    except Exception as exc:                      # noqa: BLE001 - deliberate
        lint_error = "%s: %s" % (type(exc).__name__, exc)

    log_line = "Validate: %d rows, errors=%d, warnings=%d, findings=%d" % (
        len(rows), n_err, n_warn, len(findings))
    if lint_error:
        log_line += " (criteria check failed: %s)" % lint_error

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
            findings=findings, lint_error=lint_error,
        )

    if show_ok:
        dialog = _compose_pass_dialog(n_warn, findings, lint_error)

    # `ok` is computed from `n_err` alone. Findings do not appear in it, and a
    # linter that failed outright does not appear in it either.
    return ValidationReport(
        ok=True, n_rows=len(rows), n_error_rows=n_err, n_warning_rows=n_warn,
        marks=tuple(marks), dialog=dialog, log_line=log_line,
        findings=findings, lint_error=lint_error,
    )


def _compose_pass_dialog(
    n_warn: int,
    findings: Sequence[Finding],
    lint_error: str,
) -> Dialog:
    """The dialog shown when nothing blocks. Never an error, never a prompt."""
    if lint_error:
        return Dialog(
            "info", "Criteria checked",
            "The rules are valid, but the check that compares each rule against "
            "its own wording could not run:\n\n%s\n\nNothing is blocked."
            % lint_error,
        )

    if not findings and not n_warn:
        return Dialog("info", "Validation OK", "All good.")

    parts = []
    if findings:
        parts.append("%d thing%s worth a look."
                     % (len(findings), "" if len(findings) == 1 else "s"))
    if n_warn:
        parts.append("Warnings: %d" % n_warn)
    return Dialog("info", "Criteria checked", " ".join(parts))
