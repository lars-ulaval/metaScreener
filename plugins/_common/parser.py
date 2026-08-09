# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
plugins/_common/parser.py — shared parsing & criteria-loading for EH/IH.

Owns:
  - Dataclasses produced by the parser: Criterion, ParseReport, CriteriaLoadReport.
  - Constants and normalization maps (TRUTHY, DOC_TYPE_MAP, LANG_MAP) that govern
    how raw cell values map to comparable canonical forms.
  - Pure utility functions (_safe_str, _truthy, _split_*, _norm_*, _now_stamp,
    _iso_now, _sha256_hex, _decode_bytes).
  - Robust CSV record splitter (_split_csv_records) that preserves quoted newlines.
  - Tolerant corpus parser (_parse_csv_tolerant_text) that emits a ParseReport
    with integral rows + skipped/invalid rows.
  - Bundle input_errors carry-forward (_load_input_errors_from_text).
  - Stage-parametrized criteria loader (_load_criteria_from_text) and pairwise
    contradiction detection (_detect_contradictions_simple).

The criteria loader is parametrized by a `stage` argument ("EH" or "IH") so a
single implementation serves both Plugin 04 and Plugin 05; the per-plugin
plugin.py keeps a thin _load_criteria_<stage>_from_text wrapper for backward
test compatibility.

Consumed by:
  - plugins/04_eh/plugin.py
  - plugins/05_ih/plugin.py
"""
import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any, Dict, List, Optional, Sequence, Tuple

from plugins._common.input_errors import read_input_errors


# ----------------------------
# Constants
# ----------------------------

TRUTHY = {"1", "true", "yes", "y", "on", "enabled"}


# ----------------------------
# Normalization maps
# ----------------------------

DOC_TYPE_MAP = {
    # journal-like
    "journal": "journal",
    "journal article": "journal",
    "article": "journal",
    "research article": "journal",
    "original article": "journal",
    "journal-article": "journal",
    "peer reviewed article": "journal",
    # conference/proceedings-like
    "conference": "conference",
    "conference paper": "conference",
    "conference article": "conference",
    "proceedings": "conference",
    "proceedings article": "conference",
    "inproceedings": "conference",
    "conference proceedings": "conference",
    # misc common
    "preprint": "preprint",
    "arxiv": "preprint",
    "thesis": "thesis",
    "dissertation": "thesis",
    "book chapter": "book_chapter",
    "chapter": "book_chapter",
    "report": "report",
}

LANG_MAP = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "en-us": "en",
    "en-gb": "en",
    "fr": "fr",
    "fra": "fr",
    "fre": "fr",
    "french": "fr",
    "fr-ca": "fr",
    "es": "es",
    "spa": "es",
    "spanish": "es",
}


# ----------------------------
# Data structures
# ----------------------------

@dataclass
class Criterion:
    stage: str
    cid: str
    ctype: str           # include / exclude
    scope: str
    label: str
    operator: str
    targets: List[str]   # parsed list of targets
    what_raw: str
    what_list: List[str]
    threshold: Optional[float]
    enabled: bool
    source_text: str


@dataclass
class ParseReport:
    header: List[str]
    rows: List[Dict[str, str]]           # integral rows only
    skipped: List[Tuple[int, str, str]]  # (record_index_1based_ex_header, reason, raw_record_text)


@dataclass
class CriteriaLoadReport:
    criteria: List[Criterion]
    warnings: List[str]


# ----------------------------
# Utilities
# ----------------------------

def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _iso_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    try:
        return str(x)
    except Exception:
        return ""


def _norm_basic(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _truthy(x: Any) -> bool:
    return _safe_str(x).strip().lower() in TRUTHY


def _split_targets(target_cell: str) -> List[str]:
    t = _safe_str(target_cell)
    out: List[str] = []
    for p in t.split(","):
        p = p.strip().strip('"').strip("'")
        if p:
            out.append(p)
    return out


def _split_what_list(what_cell: str) -> List[str]:
    w = _safe_str(what_cell).replace("\n", ";").replace("\r", ";")
    out: List[str] = []
    for p in w.split(";"):
        p = p.strip().strip('"').strip("'")
        if p:
            out.append(p)
    return out


def _norm_doc_type(v: str) -> str:
    x = _norm_basic(v).lower()
    x = x.replace("_", " ").replace("-", " ")
    x = re.sub(r"\s+", " ", x).strip()
    return DOC_TYPE_MAP.get(x, x)


def _norm_lang(v: str) -> str:
    x = _norm_basic(v).lower()
    x = x.replace("_", "-")
    x = re.sub(r"\s+", "", x)
    return LANG_MAP.get(x, x)


def _norm_for_target(target: str, value: str) -> str:
    t = (target or "").strip().lower()
    v = _safe_str(value)
    if not v.strip():
        return ""
    if t == "doc_type":
        return _norm_doc_type(v)
    if t == "lang":
        return _norm_lang(v)
    return _norm_basic(v)


def _norm_what_for_target(target: str, what: str) -> str:
    return _norm_for_target(target, what)


def _sha256_hex(data: bytes) -> str:
    h = sha256()
    h.update(data)
    return h.hexdigest()


def _decode_bytes(b: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return b.decode(enc)
        except Exception:
            continue
    return b.decode("utf-8", errors="ignore")


# ----------------------------
# Robust CSV parsing (record splitter)
# ----------------------------

def _split_csv_records(text: str) -> List[str]:
    """
    Split CSV into record strings by scanning newlines not inside quotes.
    Preserves embedded newlines inside quoted fields.

    F-76: the CR rewrite below applies to the WHOLE text, before parsing,
    so it reaches inside quoted fields — a metadata value containing
    ``\\r\\n`` or a lone ``\\r`` comes out of the EH/IH reports with ``\\n``
    instead. This is a deliberate canonicalisation of metadata (decision
    Q-A, docs/internal/FIX_WAVE_4_REPORTS.md), documented in
    docs/usage.md, load-bearing for the committed goldens (the sample
    corpus carries 4 CR-bearing fields; the EH golden carries 0), and
    pinned by tests/test_corpus_parser.py
    ::TestCarriageReturnCanonicalisation. Embedded LF is preserved
    verbatim; only the CR variants are rewritten.
    """
    if not text:
        return []
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    recs: List[str] = []
    buf: List[str] = []
    in_quote = False
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]
        if ch == '"':
            if in_quote and (i + 1) < n and text[i + 1] == '"':
                buf.append('"')
                buf.append('"')
                i += 2
                continue
            in_quote = not in_quote
            buf.append(ch)
            i += 1
            continue

        if ch == "\n" and not in_quote:
            recs.append("".join(buf))
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    if buf:
        recs.append("".join(buf))
    return recs


def _parse_csv_tolerant_text(text: str, required_id: str = "local_id") -> ParseReport:
    records = _split_csv_records(text)
    if not records:
        raise ValueError("CSV is empty.")

    try:
        header = next(csv.reader(io.StringIO(records[0] + "\n")))
    except Exception as e:
        raise ValueError(f"Failed to parse CSV header: {e}")

    header = [h.strip() for h in header]
    if not header or all(not h for h in header):
        raise ValueError("CSV header is empty.")

    expected_n = len(header)
    rows: List[Dict[str, str]] = []
    skipped: List[Tuple[int, str, str]] = []
    seen_ids: set = set()

    for rec_idx, rec in enumerate(records[1:], start=1):  # 1-based, excluding header
        raw = rec
        if not raw.strip():
            skipped.append((rec_idx, "empty_record", raw))
            continue
        try:
            parsed = next(csv.reader(io.StringIO(raw + "\n")))
        except csv.Error as e:
            skipped.append((rec_idx, f"csv_error:{e}", raw))
            continue
        except Exception as e:
            skipped.append((rec_idx, f"parse_error:{e}", raw))
            continue

        if len(parsed) != expected_n:
            skipped.append((rec_idx, f"bad_column_count:{len(parsed)}!=expected:{expected_n}", raw))
            continue

        d = {header[i]: _safe_str(parsed[i]) for i in range(expected_n)}

        lid = _safe_str(d.get(required_id, "")).strip()
        if not lid:
            skipped.append((rec_idx, "missing_local_id", raw))
            continue

        # A repeated identifier is not a usable record: every downstream
        # stage keys its per-record maps on local_id, so the copies would
        # overwrite one another's evidence. EL/IL already dropped duplicates
        # (plugins/06_el/screen.py:213-215); EH/IH silently kept them, so a
        # corpus could lose rows between stage 05 and stage 06 with nothing
        # in the audit trail to say which (F-55). First occurrence wins.
        if lid in seen_ids:
            skipped.append((rec_idx, f"duplicate_local_id:{lid}", raw))
            continue
        seen_ids.add(lid)

        rows.append(d)

    return ParseReport(header=header, rows=rows, skipped=skipped)


def _load_input_errors_from_text(text: str) -> List[Tuple[int, str, str]]:
    """
    Parse a prior input_errors.csv (if present in bundle) and return skipped
    tuples in EH/IH's (record_index_ex_header, reason, raw_record) shape.

    F-03: this used to read only its own columns, so it returned [] for a
    file written by the Harmoniser (record_number/observed_len/expected_len/
    raw) or by EL/IL (reason/row_json). EH's status line reported that as
    "Imported previous input_errors: … (0 rows)", which reads as "there were
    none" rather than "I could not read them", and the records the
    Harmoniser had dropped stopped being carried forward at the first hop.

    Parsing now goes through the single tolerant reader in
    plugins._common.input_errors, which understands all three legacy
    layouts and the canonical one. The tuple shape is preserved because
    EH/IH merge the result straight into ParseReport.skipped.
    """
    return [
        (e.record_number, e.reason, e.raw)
        for e in read_input_errors(text)
        if e.record_number > 0 and e.reason
    ]


# ----------------------------
# Criteria loading + contradiction warnings
# ----------------------------

def _load_criteria_from_text(text: str, stage: str) -> CriteriaLoadReport:
    """
    Load harmonised-criteria CSV text and return only the rows for the
    requested stage. `stage` is "EH" or "IH" (case-insensitively matched
    against the input's `stage` column; normalized to upper-case here).

    Behaviour preserved verbatim from the per-plugin loaders that this
    function replaces: when the input lacks a `stage` column, every row
    is assumed to belong to the requested stage; otherwise only rows whose
    `stage` cell matches (case-insensitively) are retained. Default cid
    fallback uses the requested stage as prefix (e.g. "EH_ROW_3").
    """
    stage = (stage or "").strip().upper()
    warnings: List[str] = []
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return CriteriaLoadReport(criteria=[], warnings=["Criteria header not found."])

    has_stage = any((h or "").strip().lower() == "stage" for h in (reader.fieldnames or []))

    crits: List[Criterion] = []
    row_i = 0
    for row in reader:
        row_i += 1
        row_stage = _safe_str(row.get("stage", "")).strip()
        if not has_stage:
            row_stage = stage
        if row_stage.strip().upper() != stage:
            continue

        enabled = _truthy(row.get("enabled", "1"))
        if not enabled:
            continue

        cid = _safe_str(row.get("id", "")).strip() or f"{stage}_ROW_{row_i}"
        ctype = (_safe_str(row.get("type", "")).strip().lower() or "include")
        scope = _safe_str(row.get("scope", "")).strip()
        label = _safe_str(row.get("label", "")).strip()
        operator = (_safe_str(row.get("operator", "")).strip().lower() or "equals")
        targets = _split_targets(_safe_str(row.get("target", "")).strip())
        what_raw = _safe_str(row.get("what", "")).strip()
        what_list = _split_what_list(what_raw)
        source_text = _safe_str(row.get("source_text", "")).strip()

        thr = None
        thr_cell = _safe_str(row.get("threshold", "")).strip()
        if thr_cell:
            try:
                thr = float(thr_cell)
            except Exception:
                warnings.append(f"[criteria] Row {row_i} ({cid}): invalid threshold '{thr_cell}' -> ignored.")

        if ctype not in ("include", "exclude"):
            warnings.append(f"[criteria] {cid}: unknown type '{ctype}' -> treating as include.")
            ctype = "include"

        if not targets:
            warnings.append(f"[criteria] {cid}: missing target -> criterion will be treated as MISSING (PASS_FLAGGED).")

        crits.append(
            Criterion(
                stage=stage,
                cid=cid,
                ctype=ctype,
                scope=scope,
                label=label,
                operator=operator,
                targets=targets,
                what_raw=what_raw,
                what_list=what_list,
                threshold=thr,
                enabled=True,
                source_text=source_text,
            )
        )

    warnings.extend(_detect_contradictions_simple(crits))
    return CriteriaLoadReport(criteria=crits, warnings=warnings)


def _detect_contradictions_simple(crits: Sequence[Criterion]) -> List[str]:
    warns: List[str] = []
    bucket: Dict[str, Dict[str, set]] = {}

    for c in crits:
        if not c.targets or len(c.targets) != 1:
            continue
        tgt = c.targets[0].strip()
        op = (c.operator or "").strip().lower()
        if op not in ("equals", "in_list"):
            continue
        vals = c.what_list[:] if c.what_list else ([_safe_str(c.what_raw)] if c.what_raw else [])
        vals_norm = {_norm_what_for_target(tgt, v) for v in vals if _norm_what_for_target(tgt, v)}
        if not vals_norm:
            continue
        bucket.setdefault(tgt, {"include": set(), "exclude": set()})
        bucket[tgt][c.ctype].update(vals_norm)

    for tgt, d in bucket.items():
        inc = d.get("include", set())
        exc = d.get("exclude", set())
        overlap = sorted(inc.intersection(exc))
        if overlap:
            warns.append(
                f"[criteria] Possible contradiction on target '{tgt}': values appear in BOTH include and exclude: {', '.join(overlap[:10])}"
                + (" ..." if len(overlap) > 10 else "")
            )
    return warns
