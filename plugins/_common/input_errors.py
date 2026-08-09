# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
plugins/_common/input_errors.py — the single reader and writer for
data/input_errors.csv.

F-03. This file is the record of which citations were dropped as malformed
and why. It had three different schemas, one per writer:

    Harmoniser   record_number, reason, observed_len, expected_len, raw
    EH / IH      record_index_ex_header, reason, raw_record
    EL / IL      reason, row_json

the only reader understood the second, and EL removed the file from the
bundle on any run where EL itself had skipped nothing. So the audit trail
of what had been excluded from the review did not survive the pipeline that
excluded it.

One schema now, widened rather than narrowed — the Harmoniser's, which was
the richest, plus ``stage``. ``stage`` is new and is the point of the file
once stages append to it rather than overwrite: without it, a merged file
says five records were dropped but not by whom, which is most of the
provenance.

Reading is deliberately tolerant of all three legacy layouts. Bundles
written by earlier versions are on disk and in reviewers' hands; refusing
to read them would drop exactly the records this module exists to keep.

Consumed by:
  - plugins/_common/exporters.py  (_export_input_errors_csv and the
    dict-shaped variant behind EL/IL's export buttons — F-74)
  - plugins/_common/parser.py     (_load_input_errors_from_text)
  - plugins/_common/bundle.py     (both next-bundle writers)
  - plugins/03_harmoniser/exporters.py
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


INPUT_ERRORS_FIELDS = [
    "stage", "record_number", "reason", "observed_len", "expected_len", "raw",
]


class InputErrorsUnreadableError(ValueError):
    """An input_errors.csv exists and is non-empty but cannot be read.

    F-68. The reader used to catch every exception and return ``[]``, so an
    unreadable audit file was indistinguishable from one recording that no
    records were dropped — the exact false negative this module exists to
    prevent. Absent or empty still reads as empty; a file that exists and
    cannot be parsed raises this, and callers surface it rather than
    coercing it to "nothing was dropped".

    Subclasses ``ValueError`` so callers that already catch broadly keep
    working; the ones that must *not* swallow it catch this type first.
    """

# Legacy column names, mapped onto the canonical ones.
_RECORD_NUMBER_ALIASES = ("record_number", "record_index_ex_header")
_RAW_ALIASES = ("raw", "raw_record", "row_json")


@dataclass
class InputError:
    """One record dropped as malformed, and everything known about why.

    ``observed_len`` / ``expected_len`` are the Harmoniser's ragged-row
    diagnostics. They stay None for stages that do not compute them rather
    than being invented, so an empty cell means "not measured" and not
    "measured as zero".
    """
    stage: str
    record_number: int
    reason: str
    raw: str
    observed_len: Optional[int] = None
    expected_len: Optional[int] = None


def _as_int(value: Any) -> Optional[int]:
    text = ("" if value is None else str(value)).strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _first_present(row: Dict[str, Any], names: Sequence[str]) -> str:
    for name in names:
        if name in row and row[name] is not None:
            return str(row[name])
    return ""


def to_rows(errors: Iterable[InputError]) -> List[Dict[str, str]]:
    """Canonical CSV rows. None becomes an empty cell, not "None"."""
    out: List[Dict[str, str]] = []
    for e in errors:
        out.append({
            "stage": e.stage or "",
            "record_number": "" if e.record_number is None else str(e.record_number),
            "reason": e.reason or "",
            "observed_len": "" if e.observed_len is None else str(e.observed_len),
            "expected_len": "" if e.expected_len is None else str(e.expected_len),
            "raw": e.raw or "",
        })
    return out


def write_input_errors_csv(errors: Iterable[InputError]) -> str:
    """Serialise to the canonical schema.

    The header is written even for an empty list: a file that exists and
    says "no records were dropped" is a different claim from no file, and
    only the first one is auditable.

    F-67: the line terminator is the csv module's default ``\\r\\n``, not
    ``\\n``. With ``lineterminator="\\n"`` the writer does not quote a field
    containing a lone CR, and a dropped record whose text carried a stray
    ``\\r`` produced a file ``csv.reader`` refuses to parse — an audit trail
    destroyed by the very content it exists to record.
    """
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=INPUT_ERRORS_FIELDS)
    w.writeheader()
    for row in to_rows(errors):
        w.writerow(row)
    return buf.getvalue()


def read_input_errors(text: str, *, default_stage: str = "") -> List[InputError]:
    """Parse any input_errors.csv this project has ever written.

    ``default_stage`` fills in the stage for the three legacy layouts,
    which have no such column. Callers pass the stage that produced the
    file they are reading; an unknown provenance is better recorded as
    empty than guessed.

    Absent or empty text reads as ``[]``. Text that exists but cannot be
    parsed — structurally invalid CSV, or a header matching none of the
    four layouts this project has ever written — raises
    :class:`InputErrorsUnreadableError` (F-68). It used to return ``[]``
    for those too, which made a destroyed audit trail read as a clean one.
    """
    if not (text or "").strip():
        return []
    try:
        rdr = csv.DictReader(io.StringIO(text))
        fields = set(rdr.fieldnames or [])
        rows = list(rdr)  # force csv errors here, not lazily mid-loop
    except csv.Error as e:
        raise InputErrorsUnreadableError(
            f"input_errors.csv exists but is not parseable as CSV ({e}). "
            f"The record of dropped citations is unreadable, which is not "
            f"the same as there being none — refusing to treat it as empty."
        )
    if "reason" not in fields:
        raise InputErrorsUnreadableError(
            f"input_errors.csv has a header matching none of the layouts "
            f"this project has written (columns: {sorted(fields)}). It "
            f"cannot be read as the record of dropped citations, which is "
            f"not the same as there being none."
        )
    out: List[InputError] = []
    for row in rows:
        if row is None:
            continue
        reason = _first_present(row, ("reason",)).strip()
        if not reason:
            continue
        out.append(InputError(
            stage=(_first_present(row, ("stage",)).strip() or default_stage),
            record_number=_as_int(_first_present(row, _RECORD_NUMBER_ALIASES)) or 0,
            reason=reason,
            raw=_first_present(row, _RAW_ALIASES),
            observed_len=_as_int(_first_present(row, ("observed_len",))),
            expected_len=_as_int(_first_present(row, ("expected_len",))),
        ))

    # EL/IL's layout carried no index at all, so every row read back as 0.
    # Number them in file order rather than leave the whole column at zero.
    if out and all(e.record_number == 0 for e in out):
        for i, e in enumerate(out, start=1):
            e.record_number = i
    return out


def _key(e: InputError) -> Tuple:
    return (e.stage, e.record_number, e.reason, e.raw,
            e.observed_len, e.expected_len)


def merge_input_errors_csv(prior_text: Optional[str],
                           new_errors: Iterable[InputError],
                           *, prior_stage: str = "") -> str:
    """Append ``new_errors`` to whatever ``prior_text`` already recorded.

    Append, never overwrite — that is the whole fix. Each stage adds what
    it dropped and passes the accumulated file on, so the bundle that
    arrives at IL still names the record the Harmoniser threw away.

    Exact duplicates collapse, so re-exporting a stage does not grow the
    file without bound. Two entries differing only in ``stage`` are two
    distinct facts (the same record was dropped twice, at two hops) and
    both are kept.
    """
    merged: List[InputError] = list(
        read_input_errors(prior_text or "", default_stage=prior_stage))
    seen = {_key(e) for e in merged}
    for e in new_errors:
        k = _key(e)
        if k in seen:
            continue
        seen.add(k)
        merged.append(e)
    return write_input_errors_csv(merged)


# ----------------------------
# Adapters from each stage's in-memory shape
# ----------------------------

def from_tuple_skipped(skipped: Sequence[Tuple[int, str, str]],
                       *, stage: str) -> List[InputError]:
    """EH/IH ParseReport.skipped: (record_index_ex_header, reason, raw)."""
    out: List[InputError] = []
    for item in skipped or []:
        try:
            rec_i, reason, raw = item
        except (TypeError, ValueError):
            continue
        out.append(InputError(
            stage=stage,
            record_number=_as_int(rec_i) or 0,
            reason=("" if reason is None else str(reason)),
            raw=("" if raw is None else str(raw)),
        ))
    return out


def from_dict_skipped(skipped: Sequence[Dict[str, Any]],
                      *, stage: str) -> List[InputError]:
    """EL/IL ParseReport.skipped: [{"reason": ..., "row": {...}}].

    These carry no record index — the stage never recorded one — so they
    are numbered in the order they were dropped. That is weaker provenance
    than the Harmoniser's record_number but it is what exists, and an
    honest sequence number beats a column of zeroes.
    """
    out: List[InputError] = []
    for i, item in enumerate(skipped or [], start=1):
        if not isinstance(item, dict):
            continue
        row = item.get("row", {})
        try:
            raw = json.dumps(row, ensure_ascii=False)
        except Exception:
            raw = str(row)
        out.append(InputError(
            stage=stage,
            record_number=i,
            reason=("" if item.get("reason") is None else str(item.get("reason"))),
            raw=raw,
        ))
    return out
