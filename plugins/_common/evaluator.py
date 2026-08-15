# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
plugins/_common/evaluator.py — shared per-criterion evaluation for EH/IH.

Owns:
  - _get_first_nonempty: pick the first non-empty value across a list of
    target column names for a row (display helper; the evaluators no
    longer decide with it — see F-204 below).
  - _nonempty_fields / _match_field: the F-204 shape — every listed
    target with a non-empty value, and the operator predicate against
    one field at a time.
  - _eval_criterion: fast four-state evaluator (MET / FAILED / MISSING /
    UNKNOWN) applied to one (row, criterion) pair. Stage-agnostic. A
    multi-target criterion matches when ANY listed field satisfies the
    predicate.
  - _eval_criterion_detail: detailed variant for the UI evaluation modal.
    The LLM-not-supported note is stage-parametrized so EH and IH share
    the implementation. Reports the field that decided.
  - _summarize_reason: aggregate per-criterion outcomes into a single
    free-text reason. Stage-parametrized for the "All {stage} criteria
    met." happy-path message.

F-204 (wave 15c): until this wave both evaluators read only the FIRST
non-empty target, so a criterion promising "title, abstract, or keywords
mention X" tested the title alone whenever a title existed — measured on
the reference corpus at 8 records kept of 147 against the 22 its prose
keeps (the title is the first non-empty field for 759 of 760 records).
Single-target criteria — every other deterministic reference row, and
every deterministic golden row — behave identically before and after;
the EH/IH golden replays prove it.

Pulled-in dependencies from plugins._common.parser:
  - dataclass `Criterion` for type hints.
  - normalisation helpers `_safe_str`, `_norm_for_target`,
    `_norm_what_for_target` so the same canonical forms are used by both
    parsing and evaluation.

Consumed by:
  - plugins/04_eh/plugin.py
  - plugins/05_ih/plugin.py

LLM evaluation is intentionally NOT implemented here: the deterministic
(heuristics) stages EH and IH never invoke an LLM. Operators set to "llm"
yield a stable UNKNOWN result with a stage-tagged note so the audit trail
shows where the LLM stage (EL/IL) takes over.

Provenance: the bodies were copied verbatim from plugins/04_eh/plugin.py
v3.1.0 (commit 35aadcd) at extraction, with stage parametrization the
only delta, and byte-identity was the guarantee then. Wave 15c's F-204
fix restructured both evaluators around _match_field/_nonempty_fields;
the guarantee since is behavioural, held by the EH and IH golden replay
regressions (all of whose deterministic rows are single-target, the
class the fix leaves untouched).
"""
import re
from typing import Dict, List, Optional, Sequence, Tuple

from plugins._common.parser import (
    Criterion,
    _norm_for_target,
    _norm_what_for_target,
    _safe_str,
)


def _get_first_nonempty(row: Dict[str, str], targets: Sequence[str]) -> Tuple[str, str]:
    if not targets:
        return "", ""
    for t in targets:
        if t in row:
            v = _safe_str(row.get(t, ""))
            if v.strip():
                return t, v
    t0 = targets[0]
    return t0, _safe_str(row.get(t0, "")) if t0 in row else ""

def _as_float(x: str) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


#: The operators _match_field can decide. `llm` is deliberately absent:
#: the deterministic stages never invoke a model (module docstring).
DETERMINISTIC_OPERATORS = (
    "equals", "contains", "regex", "in_list", "not_in", "gte", "lte",
    "between")


def _match_field(op: str, target: str, raw_val: str, val: str,
                 what_list: List[str]) -> Tuple[Optional[bool], str]:
    """The operator predicate against ONE field's value.

    Returns (matched, note): ``True``/``False`` when this field decides,
    ``None`` when it cannot (the per-field face of UNKNOWN — bad pattern,
    non-numeric value, empty operand list). The note is the detail
    modal's per-op string; the fast evaluator ignores it.

    The ``what`` operands are normalised per target, because
    normalisation is a property of the column (lang, doc_type) and a
    multi-target criterion may span columns that normalise differently.
    """
    what_list_norm = [_norm_what_for_target(target, w) for w in what_list
                      if _norm_what_for_target(target, w)]

    if op == "equals":
        if not what_list_norm:
            return None, "equals_missing_what"
        return (val.lower() == what_list_norm[0].lower()), "equals"

    if op == "contains":
        if not what_list_norm:
            return None, "contains_missing_what"
        hay = val.lower()
        return any((w.lower() in hay) for w in what_list_norm if w), "contains"

    if op == "regex":
        if not what_list:
            return None, "regex_missing_pattern"
        pat = what_list[0]
        try:
            return bool(re.search(pat, raw_val, flags=re.IGNORECASE)), \
                f"regex:{pat}"
        except Exception:
            return None, f"bad_regex:{pat}"

    if op == "in_list":
        if not what_list_norm:
            return None, "in_list_missing_what"
        wset = {w.lower() for w in what_list_norm if w}
        return (val.lower() in wset), "in_list"

    if op == "not_in":
        if not what_list_norm:
            return None, "not_in_missing_what"
        wset = {w.lower() for w in what_list_norm if w}
        return (val.lower() not in wset), "not_in"

    if op == "gte":
        if not what_list:
            return None, "gte_missing_what"
        a = _as_float(val)
        b = _as_float(what_list[0])
        if a is None or b is None:
            return None, "gte_non_numeric"
        return (a >= b), f"gte:{b}"

    if op == "lte":
        if not what_list:
            return None, "lte_missing_what"
        a = _as_float(val)
        b = _as_float(what_list[0])
        if a is None or b is None:
            return None, "lte_non_numeric"
        return (a <= b), f"lte:{b}"

    if op == "between":
        if len(what_list) < 2:
            return None, "between_requires_two_values"
        a = _as_float(val)
        lo = _as_float(what_list[0])
        hi = _as_float(what_list[1])
        if a is None or lo is None or hi is None:
            return None, "between_non_numeric"
        if lo > hi:
            lo, hi = hi, lo
        return (lo <= a <= hi), f"between:{lo}..{hi}"

    return None, f"unknown_operator:{op}"


def _nonempty_fields(row: Dict[str, str], header_set: set,
                     targets: Sequence[str]) -> List[Tuple[str, str, str]]:
    """Every listed target present in the header whose normalised value
    is non-empty, as (target, raw, norm) — in the criterion's own order.

    F-204: the evaluator used to read only the FIRST of these, so a
    criterion promising "title, abstract, or keywords mention X" tested
    the title alone whenever a title existed — measured at 8 kept of
    147 against the 22 its prose keeps. Every field is read now.
    """
    out = []
    for t in targets:
        if t not in header_set:
            continue
        raw = _safe_str(row.get(t, ""))
        norm = _norm_for_target(t, raw)
        if norm:
            out.append((t, raw, norm))
    return out


def _eval_criterion(row: Dict[str, str], header_set: set, c: Criterion) -> str:
    """
    Fast status only: returns one of {"MET","FAILED","MISSING","UNKNOWN"}.

    A multi-target criterion matches when ANY listed field satisfies the
    predicate (F-204). A field that cannot be evaluated (non-numeric,
    bad pattern) yields UNKNOWN only when no other field matches — a
    match is a match, whatever a sibling field's condition.
    """
    if not c.targets:
        return "MISSING"

    if not any(t in header_set for t in c.targets):
        return "MISSING"

    fields = _nonempty_fields(row, header_set, c.targets)
    if not fields:
        return "MISSING"

    op = (c.operator or "").strip().lower()
    if op in ("llm",):
        return "UNKNOWN"
    if op not in DETERMINISTIC_OPERATORS:
        return "UNKNOWN"

    what_list = c.what_list[:] if c.what_list else ([_safe_str(c.what_raw)] if c.what_raw else [])

    matched = False
    any_undecidable = False
    for t, raw_val, val in fields:
        m, _note = _match_field(op, t, raw_val, val, what_list)
        if m is True:
            matched = True
            break
        if m is None:
            any_undecidable = True

    if not matched and any_undecidable:
        return "UNKNOWN"

    if c.ctype == "include":
        return "MET" if matched else "FAILED"
    else:
        return "FAILED" if matched else "MET"

def _eval_criterion_detail(row: Dict[str, str], header_set: set, c: Criterion, stage: str) -> Dict[str, str]:
    """
    Slower, for UI detail modal.
    Returns dict with keys:
      status, note, target_used, raw_value, norm_value, operator, type, targets, what
    """
    out = {
        "cid": c.cid,
        "type": c.ctype,
        "operator": c.operator,
        "targets": ",".join(c.targets),
        "what": c.what_raw,
        "status": "",
        "note": "",
        "target_used": "",
        "raw_value": "",
        "norm_value": "",
    }

    if not c.targets:
        out["status"] = "MISSING"
        out["note"] = "missing_target"
        return out

    if not any(t in header_set for t in c.targets):
        out["status"] = "MISSING"
        out["note"] = "missing_column"
        return out

    fields = _nonempty_fields(row, header_set, c.targets)
    if not fields:
        target_used, raw_val = _get_first_nonempty(row, c.targets)
        out["target_used"] = target_used
        out["raw_value"] = raw_val
        out["norm_value"] = ""
        out["status"] = "MISSING"
        out["note"] = "empty_value"
        return out

    # Until a field decides, report the first non-empty one — the value
    # the pre-F-204 evaluator would have shown.
    out["target_used"], out["raw_value"], out["norm_value"] = fields[0]

    op = (c.operator or "").strip().lower()

    if op in ("llm",):
        out["status"] = "UNKNOWN"
        out["note"] = f"operator_llm_not_supported_in_{stage}"
        return out
    if op not in DETERMINISTIC_OPERATORS:
        out["status"] = "UNKNOWN"
        out["note"] = f"unknown_operator:{op}"
        return out

    what_list = c.what_list[:] if c.what_list else ([_safe_str(c.what_raw)] if c.what_raw else [])

    # F-204: every listed field is read; the row reports the field that
    # DECIDED — the first matching one, else the first field, else (all
    # undecidable) the first undecidable one with its reason.
    matched = False
    note = ""
    first_undecidable: Optional[Tuple[str, str, str, str]] = None
    for t, raw_val, val in fields:
        m, n = _match_field(op, t, raw_val, val, what_list)
        if m is True:
            matched = True
            out["target_used"], out["raw_value"], out["norm_value"] = \
                t, raw_val, val
            note = n
            break
        if m is None and first_undecidable is None:
            first_undecidable = (t, raw_val, val, n)
        if m is False and not note:
            note = n

    if not matched and first_undecidable is not None:
        t, raw_val, val, n = first_undecidable
        out["target_used"], out["raw_value"], out["norm_value"] = \
            t, raw_val, val
        out["status"] = "UNKNOWN"
        out["note"] = n
        return out

    out["note"] = note
    if c.ctype == "include":
        out["status"] = "MET" if matched else "FAILED"
    else:
        out["status"] = "FAILED" if matched else "MET"

    return out

def _summarize_reason(outcome: str, failed: List[str], missing: List[str], met: List[str], unknown: List[str], stage: str) -> str:
    if outcome == "PASS_CLEAN":
        return f"All {stage} criteria met."
    parts = []
    if failed:
        parts.append(f"Failed: {', '.join(failed[:6])}" + (" ..." if len(failed) > 6 else ""))
    if missing:
        parts.append(f"Missing: {', '.join(missing[:6])}" + (" ..." if len(missing) > 6 else ""))
    if unknown:
        parts.append(f"Unknown: {', '.join(unknown[:6])}" + (" ..." if len(unknown) > 6 else ""))
    if not parts:
        parts.append("Uncertain (no definitive failures).")
    return " | ".join(parts)
