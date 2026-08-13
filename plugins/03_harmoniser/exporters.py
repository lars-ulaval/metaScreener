# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
exporters.py - Plugin 03 Harmoniser: bundle-output writers and helpers.

Concerns owned by this module:
  - criteria_harmonized.csv writer (_export_csv) - the byte-identity-critical
    schema consumed by EH/IH/EL/IL downstream
  - criteria_harmonized.txt pipe-table writer (_export_pipe)
  - SHA-256 file digest helper (_sha256_file) used in bundle integrity stamping
  - Aggregate-CSV cleaner (_clean_aggregate_csv) - validates corpus rows against
    the canonical column set and writes data/current.csv plus an optional
    data/input_errors.csv when malformed rows are dropped
  - Bundle manifest assembler (_build_manifest) - the JSON descriptor
    capturing schema version, configuration, criteria summary, and stats
  - Bundle schema constants (BUNDLE_SCHEMA, BUNDLE_ROOT_NAME) consumed by
    _build_manifest and by the View's `_export_bundle` orchestration

Imports from .parser (vocabularies + utilities). No GUI, no LLM dependencies.
Safe to reuse standalone for non-Tkinter pipelines that need a Screen-A bundle.

Extracted from `plugin.py` in Conv 4 of the v3.1.0 refactor. Behavior is
preserved verbatim; the criteria_harmonized.csv golden regression test guards
the byte-identity contract.
"""

import csv
import io
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from plugins._common.input_errors import (
    InputError,
    write_input_errors_csv,
)

from .parser import (
    STAGES,
    _now_iso,
    _norm_space,
    _safe_str,
    _what_to_export,
    _export_to_pipe_table,
)


# ============================
# Bundle schema constants
# ============================

BUNDLE_SCHEMA = "screenA_bundle_v1"
BUNDLE_ROOT_NAME = "ScreenA_Bundle"


def _criteria_csv_text(rows: List[Dict[str, Any]]) -> str:
    """Serialise harmonised criteria rows to `criteria_harmonized.csv` text.

    Extracted from `_export_csv` in wave 13e session B so that a consumer needing
    the CSV *without* writing a file gets the same bytes rather than a second
    hand-maintained copy of this schema. The preview
    (`plugins/03_harmoniser/preview.py`) is the first such consumer: it must screen
    the bytes the bundle will carry, and `_load_criteria_from_text` only accepts
    text.

    This is byte-identity-critical -- `plugins/03_harmoniser/bundle.py` records this
    file's SHA in the manifest -- so the extraction is pinned by
    `tests/test_criteria_csv_text.py`, whose lock class asserts the same bytes
    before and after.
    """
    cols = [
        "stage",
        "id",
        "type",
        "scope",
        "label",
        "operator",
        "target",
        "what",
        "threshold",
        "enabled",
        "source_text",
    ]

    # csv emits its own CRLF terminator and StringIO does not translate on write,
    # so this buffer already holds the exact bytes `_export_csv` puts on disk --
    # which opens with `newline=""` for the same reason. `newline=""` here is
    # explicit rather than load-bearing: wave 13e B measured the three StringIO
    # newline settings to be byte-identical for csv output, so no test can
    # distinguish them and none pretends to.
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow({
            "stage": r.get("stage", ""),
            "id": r.get("id", ""),
            "type": r.get("type", ""),
            "scope": r.get("scope", "metadata"),
            "label": r.get("label", ""),
            "operator": r.get("operator", ""),
            "target": r.get("target", ""),
            "what": _what_to_export(r.get("operator", ""), r.get("what", []) or []),
            "threshold": r.get("threshold", ""),
            "enabled": 1 if bool(r.get("enabled", True)) else 0,
            "source_text": r.get("source_text", ""),
        })
    return buf.getvalue()


def _export_csv(rows: List[Dict[str, Any]], path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(_criteria_csv_text(rows))


def _export_pipe(rows: List[Dict[str, Any]], path: str) -> None:
    Path(path).write_text(_export_to_pipe_table(rows), encoding="utf-8")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _clean_aggregate_csv(
    in_csv: str,
    out_current_csv: Path,
    out_errors_csv: Optional[Path],
    max_raw_len: int = 800,
) -> Dict[str, Any]:
    """Write a cleaned CSV that retains ONLY integral rows matching header width."""
    stats: Dict[str, Any] = {
        "rows_total_read": 0,
        "rows_valid_written": 0,
        "rows_invalid_skipped": 0,
        "expected_columns": 0,
        "header": [],
    }

    in_path = Path(in_csv)
    out_current_csv.parent.mkdir(parents=True, exist_ok=True)
    if out_errors_csv is not None:
        out_errors_csv.parent.mkdir(parents=True, exist_ok=True)

    errors_rows: List[InputError] = []

    with open(in_path, "r", encoding="utf-8-sig", newline="") as f_in:
        reader = csv.reader(f_in)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("A vector CSV is empty")

        expected = len(header)
        stats["expected_columns"] = expected
        stats["header"] = header

        with out_current_csv.open("w", encoding="utf-8", newline="") as f_out:
            writer = csv.writer(f_out)
            writer.writerow(header)

            record_no = 1  # 1 is header record
            for row in reader:
                record_no += 1
                stats["rows_total_read"] += 1

                if len(row) != expected:
                    stats["rows_invalid_skipped"] += 1
                    if out_errors_csv is not None:
                        raw = " | ".join([_safe_str(x) for x in row])
                        if len(raw) > max_raw_len:
                            raw = raw[:max_raw_len] + "…"
                        errors_rows.append(InputError(
                            stage="Harmoniser",
                            record_number=record_no,
                            reason="wrong_column_count",
                            raw=raw,
                            observed_len=len(row),
                            expected_len=expected,
                        ))
                    continue

                writer.writerow(row)
                stats["rows_valid_written"] += 1

    if out_errors_csv is not None and errors_rows:
        # F-03: the canonical schema, through the single shared writer. This
        # is the head of the chain — every later stage appends to what is
        # written here rather than replacing it with its own layout.
        with out_errors_csv.open("w", encoding="utf-8", newline="") as f_err:
            f_err.write(write_input_errors_csv(errors_rows))

    return stats


def _build_manifest(
    *,
    a_path: str,
    a_columns: Sequence[str],
    a_id_col_guess: str,
    clean_stats: Dict[str, Any],
    criteria_path: str,
    criteria_kind: str,
    criteria_rows: List[Dict[str, Any]],
    criteria_source_text: str,
    wrote_input_errors: bool,
) -> Dict[str, Any]:
    stage_counts = {st: 0 for st in STAGES}
    enabled_counts = {st: 0 for st in STAGES}
    for r in criteria_rows:
        st = _safe_str(r.get("stage")).upper()
        if st in stage_counts:
            stage_counts[st] += 1
            if bool(r.get("enabled", True)):
                enabled_counts[st] += 1

    warnings: List[str] = []
    if wrote_input_errors and clean_stats.get("rows_invalid_skipped", 0) > 0:
        warnings.append("Aggregate had invalid rows; they were skipped into data/input_errors.csv")
    for st in STAGES:
        if stage_counts.get(st, 0) == 0:
            warnings.append(f"No {st} criteria present in criteria_harmonized.csv (stage may be skipped downstream)")

    manifest: Dict[str, Any] = {
        "bundle_schema": BUNDLE_SCHEMA,
        "created_at": _now_iso(),
        "created_by": "harmoniser",
        "inputs": {
            "aggregate_filename": Path(a_path).name if a_path else "",
            "criteria_filename": Path(criteria_path).name if criteria_path else "",
            "criteria_kind": criteria_kind or "",
        },
        "aggregate": {
            "columns": list(a_columns),
            "id_column_guess": a_id_col_guess or "",
            "expected_columns": int(clean_stats.get("expected_columns", 0) or 0),
            "rows_total_read": int(clean_stats.get("rows_total_read", 0) or 0),
            "rows_valid_written": int(clean_stats.get("rows_valid_written", 0) or 0),
            "rows_invalid_skipped": int(clean_stats.get("rows_invalid_skipped", 0) or 0),
        },
        "criteria": {
            "rows_total": len(criteria_rows),
            "rows_by_stage": stage_counts,
            "enabled_by_stage": enabled_counts,
        },
        "pipeline_state": {
            "stages": {st: "not_run" for st in STAGES},
            "history": [],
        },
        "warnings": warnings,
        "criteria_source_preview": _norm_space(criteria_source_text)[:220],
    }

    return manifest

