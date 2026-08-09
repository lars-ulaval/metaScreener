# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
plugins/_common/runner.py — shared filter-pipeline orchestrator for EH/IH.

Owns:
  - run_screen(parse, criteria_report, cancel_event, progress_cb, *, stage):
    the deterministic per-row filter loop. Iterates the integral rows of a
    ParseReport, applies _eval_criterion against each enabled criterion,
    accumulates per-row outcome (MET / FAILED / MISSING / UNKNOWN tallies),
    assigns a final OUT / PASS_CLEAN / PASS_FLAGGED outcome under the
    stage's policy, builds the FULL-report row with stage-prefixed columns,
    accumulates survivors (anything not OUT), and returns the five-tuple
    that EH/IH plugins surface to their View widgets.

Two genuine behavioural differences between EH and IH are inlined here
(rather than parametrised through a strategy object), because they are
small, documented, and shielded by the byte-identity goldens:

  - Outcome assignment for non-failed rows:
      EH (strict)  : PASS_CLEAN iff len(met) == len(crits) and no missing
                     and no unknown; otherwise PASS_FLAGGED.
      IH (lenient) : PASS_FLAGGED iff there is any unknown OR missing;
                     otherwise PASS_CLEAN.

  - Composition of the {stage}_missing_ids report column:
      EH : missing CIDs only.
      IH : union of missing CIDs and unknown CIDs (single column for
           "non-deterministic-or-absent").

Pulled-in dependencies:
  - plugins._common.parser   : ParseReport, CriteriaLoadReport (type hints).
  - plugins._common.evaluator: _eval_criterion, _summarize_reason.

Consumed by:
  - plugins/04_eh/plugin.py  (thin wrapper run_eh_screen)
  - plugins/05_ih/plugin.py  (thin wrapper run_ih_screen)

Behaviour preservation is verified through the EH and IH golden-file
regressions in tests/test_*_regression.py.
"""
import threading
from typing import Callable, Dict, List, Optional, Tuple

from plugins._common.parser import ParseReport, CriteriaLoadReport
from plugins._common.evaluator import _eval_criterion, _summarize_reason


PROGRESS_EVERY_N = 200


def run_screen(
    parse: ParseReport,
    criteria_report: CriteriaLoadReport,
    cancel_event: threading.Event,
    progress_cb: Optional[Callable[[float], None]] = None,
    *,
    stage: str,
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], Dict[str, int], Dict[str, Dict[str, int]], List[Dict[str, List[str]]], bool]:
    """
    Run the deterministic per-criterion filter pipeline for one stage.

    Returns:
      full_rows: aggregate row dicts + {stage}_* columns appended
        (outcome, failed_ids, missing_ids, met_ids, reason_summary).
      survivor_rows: original aggregate row dicts (no extra columns) for
        every row whose outcome is not "OUT".
      counts: summary counts dict.
      crit_impacts: {cid: {"failed": n, "missing": n, "met": n,
        "unknown": n}}.
      row_eval_lists: list aligned with full_rows; each element is
        {"failed": [...], "missing": [...], "met": [...], "unknown": [...]}.
      cancelled: True if the row loop exited early on cancel_event, i.e.
        the results describe only part of the corpus.

    F-02: ``cancelled`` is the whole point of the sixth element. The loop
    has always been able to stop mid-corpus, but it used to return the
    rows it had reached as though they were the corpus. Nothing in
    full_rows, survivors or counts distinguishes "screened 40 records" from
    "screened 40 of 900 and gave up", and it is survivors that becomes the
    next stage's input. Callers must not export a run where this is True —
    see ``plugins._common.bundle._export_block_reason``.
    """
    sl = stage.lower()
    header_set = set(parse.header)
    rows = parse.rows
    crits = criteria_report.criteria

    counts = {
        "OUT": 0,
        "PASS_CLEAN": 0,
        "PASS_FLAGGED": 0,
        "SKIPPED_INVALID": len(parse.skipped),
        "TOTAL_INTEGRAL": len(rows),
        "TOTAL_INPUT_RECORDS_EX_HEADER": len(parse.rows) + len(parse.skipped),
    }

    crit_impacts: Dict[str, Dict[str, int]] = {
        c.cid: {"failed": 0, "missing": 0, "met": 0, "unknown": 0} for c in crits
    }

    full_rows: List[Dict[str, str]] = []
    survivors: List[Dict[str, str]] = []
    row_eval_lists: List[Dict[str, List[str]]] = []

    cancelled = False

    if not crits:
        for r in rows:
            if cancel_event.is_set():
                cancelled = True
                break
            fr = dict(r)
            fr[f"{sl}_outcome"] = "PASS_CLEAN"
            fr[f"{sl}_failed_ids"] = ""
            fr[f"{sl}_missing_ids"] = ""
            fr[f"{sl}_met_ids"] = ""
            fr[f"{sl}_reason_summary"] = f"No active {stage} criteria: default PASS_CLEAN."
            full_rows.append(fr)
            survivors.append(dict(r))
            row_eval_lists.append({"failed": [], "missing": [], "met": [], "unknown": []})
        counts["PASS_CLEAN"] = len(survivors)
        if progress_cb:
            progress_cb(1.0)
        return full_rows, survivors, counts, crit_impacts, row_eval_lists, cancelled

    n = len(rows)
    for idx, r in enumerate(rows, start=1):
        if cancel_event.is_set():
            cancelled = True
            break

        failed: List[str] = []
        missing: List[str] = []
        met: List[str] = []
        unknown: List[str] = []

        for c in crits:
            status = _eval_criterion(r, header_set, c)
            if status == "FAILED":
                failed.append(c.cid)
                crit_impacts[c.cid]["failed"] += 1
            elif status == "MISSING":
                missing.append(c.cid)
                crit_impacts[c.cid]["missing"] += 1
            elif status == "MET":
                met.append(c.cid)
                crit_impacts[c.cid]["met"] += 1
            else:
                unknown.append(c.cid)
                crit_impacts[c.cid]["unknown"] += 1

        # Stage-specific outcome assignment
        if failed:
            outcome = "OUT"
            counts["OUT"] += 1
        elif stage == "EH":
            # EH (strict): PASS_CLEAN iff every criterion is MET and there
            # is no missing or unknown; otherwise PASS_FLAGGED.
            if len(met) == len(crits) and not missing and not unknown:
                outcome = "PASS_CLEAN"
                counts["PASS_CLEAN"] += 1
            else:
                outcome = "PASS_FLAGGED"
                counts["PASS_FLAGGED"] += 1
        else:  # stage == "IH"
            # IH (lenient): PASS_FLAGGED if any unknown or missing;
            # otherwise PASS_CLEAN.
            if unknown or missing:
                outcome = "PASS_FLAGGED"
                counts["PASS_FLAGGED"] += 1
            else:
                outcome = "PASS_CLEAN"
                counts["PASS_CLEAN"] += 1

        fr = dict(r)
        fr[f"{sl}_outcome"] = outcome
        fr[f"{sl}_failed_ids"] = ";".join(failed)
        if stage == "IH":
            # IH-specific quirk: keep one column for "non-deterministic/absent"
            fr[f"{sl}_missing_ids"] = ";".join(missing + unknown)
        else:
            fr[f"{sl}_missing_ids"] = ";".join(missing)
        fr[f"{sl}_met_ids"] = ";".join(met)
        fr[f"{sl}_reason_summary"] = _summarize_reason(outcome, failed, missing, met, unknown, stage=stage)

        full_rows.append(fr)
        row_eval_lists.append({"failed": failed, "missing": missing, "met": met, "unknown": unknown})

        # Survivors are those that continue to the next stage
        if outcome != "OUT":
            survivors.append(dict(r))

        if progress_cb and (idx % PROGRESS_EVERY_N == 0 or idx == n):
            progress_cb(idx / max(1, n))

    return full_rows, survivors, counts, crit_impacts, row_eval_lists, cancelled
