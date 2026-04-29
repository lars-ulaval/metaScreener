# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
plugins/_common/evaluator.py — shared per-criterion evaluation for EH/IH.

Owns:
  - _get_first_nonempty: pick the first non-empty value across a list of
    target column names for a row.
  - _eval_criterion: fast four-state evaluator (MET / FAILED / MISSING /
    UNKNOWN) applied to one (row, criterion) pair. Stage-agnostic.
  - _eval_criterion_detail: detailed variant for the UI evaluation modal.
    The LLM-not-supported note is stage-parametrized so EH and IH share
    the implementation.
  - _summarize_reason: aggregate per-criterion outcomes into a single
    free-text reason. Stage-parametrized for the "All {stage} criteria
    met." happy-path message.

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

Bodies of _get_first_nonempty, _eval_criterion, _eval_criterion_detail,
and _summarize_reason are copied verbatim from plugins/04_eh/plugin.py
v3.1.0 (commit 35aadcd) with the only deltas being:
  - _eval_criterion_detail gains a `stage: str` parameter; its
    operator_llm_not_supported_in_EH literal becomes f-string.
  - _summarize_reason gains a `stage: str` parameter; its "All EH
    criteria met." literal becomes f-string.
This guarantees byte-identity through the EH and IH golden regressions.
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

def _eval_criterion(row: Dict[str, str], header_set: set, c: Criterion) -> str:
    """
    Fast status only: returns one of {"MET","FAILED","MISSING","UNKNOWN"}.
    """
    if not c.targets:
        return "MISSING"

    if not any(t in header_set for t in c.targets):
        return "MISSING"

    target_used, raw_val = _get_first_nonempty(row, c.targets)
    val = _norm_for_target(target_used, raw_val)
    if not val:
        return "MISSING"

    op = (c.operator or "").strip().lower()

    what_list = c.what_list[:] if c.what_list else ([_safe_str(c.what_raw)] if c.what_raw else [])
    what_list_norm = [_norm_what_for_target(target_used, w) for w in what_list if _norm_what_for_target(target_used, w)]

    if op in ("llm",):
        return "UNKNOWN"
    if op not in ("equals", "contains", "regex", "in_list", "not_in", "gte", "lte", "between"):
        return "UNKNOWN"

    def _as_float(x: str) -> Optional[float]:
        try:
            return float(x)
        except Exception:
            return None

    matched: Optional[bool] = None

    if op == "equals":
        if not what_list_norm:
            return "UNKNOWN"
        matched = (val.lower() == what_list_norm[0].lower())

    elif op == "contains":
        if not what_list_norm:
            return "UNKNOWN"
        hay = val.lower()
        matched = any((w.lower() in hay) for w in what_list_norm if w)

    elif op == "regex":
        if not what_list:
            return "UNKNOWN"
        pat = what_list[0]
        try:
            matched = bool(re.search(pat, raw_val, flags=re.IGNORECASE))
        except Exception:
            return "UNKNOWN"

    elif op == "in_list":
        if not what_list_norm:
            return "UNKNOWN"
        wset = {w.lower() for w in what_list_norm if w}
        matched = (val.lower() in wset)

    elif op == "not_in":
        if not what_list_norm:
            return "UNKNOWN"
        wset = {w.lower() for w in what_list_norm if w}
        matched = (val.lower() not in wset)

    elif op == "gte":
        if not what_list:
            return "UNKNOWN"
        a = _as_float(val)
        b = _as_float(what_list[0])
        if a is None or b is None:
            return "UNKNOWN"
        matched = (a >= b)

    elif op == "lte":
        if not what_list:
            return "UNKNOWN"
        a = _as_float(val)
        b = _as_float(what_list[0])
        if a is None or b is None:
            return "UNKNOWN"
        matched = (a <= b)

    elif op == "between":
        if len(what_list) < 2:
            return "UNKNOWN"
        a = _as_float(val)
        lo = _as_float(what_list[0])
        hi = _as_float(what_list[1])
        if a is None or lo is None or hi is None:
            return "UNKNOWN"
        if lo > hi:
            lo, hi = hi, lo
        matched = (lo <= a <= hi)

    if matched is None:
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

    target_used, raw_val = _get_first_nonempty(row, c.targets)
    out["target_used"] = target_used
    out["raw_value"] = raw_val

    norm_val = _norm_for_target(target_used, raw_val)
    out["norm_value"] = norm_val

    if not norm_val:
        out["status"] = "MISSING"
        out["note"] = "empty_value"
        return out

    op = (c.operator or "").strip().lower()

    what_list = c.what_list[:] if c.what_list else ([_safe_str(c.what_raw)] if c.what_raw else [])
    what_list_norm = [_norm_what_for_target(target_used, w) for w in what_list if _norm_what_for_target(target_used, w)]

    if op in ("llm",):
        out["status"] = "UNKNOWN"
        out["note"] = f"operator_llm_not_supported_in_{stage}"
        return out
    if op not in ("equals", "contains", "regex", "in_list", "not_in", "gte", "lte", "between"):
        out["status"] = "UNKNOWN"
        out["note"] = f"unknown_operator:{op}"
        return out

    def _as_float(x: str) -> Optional[float]:
        try:
            return float(x)
        except Exception:
            return None

    matched: Optional[bool] = None

    if op == "equals":
        if not what_list_norm:
            out["status"] = "UNKNOWN"
            out["note"] = "equals_missing_what"
            return out
        matched = (norm_val.lower() == what_list_norm[0].lower())
        out["note"] = "equals"

    elif op == "contains":
        if not what_list_norm:
            out["status"] = "UNKNOWN"
            out["note"] = "contains_missing_what"
            return out
        hay = norm_val.lower()
        matched = any((w.lower() in hay) for w in what_list_norm if w)
        out["note"] = "contains"

    elif op == "regex":
        if not what_list:
            out["status"] = "UNKNOWN"
            out["note"] = "regex_missing_pattern"
            return out
        pat = what_list[0]
        try:
            matched = bool(re.search(pat, raw_val, flags=re.IGNORECASE))
            out["note"] = f"regex:{pat}"
        except Exception:
            out["status"] = "UNKNOWN"
            out["note"] = f"bad_regex:{pat}"
            return out

    elif op == "in_list":
        if not what_list_norm:
            out["status"] = "UNKNOWN"
            out["note"] = "in_list_missing_what"
            return out
        wset = {w.lower() for w in what_list_norm if w}
        matched = (norm_val.lower() in wset)
        out["note"] = "in_list"

    elif op == "not_in":
        if not what_list_norm:
            out["status"] = "UNKNOWN"
            out["note"] = "not_in_missing_what"
            return out
        wset = {w.lower() for w in what_list_norm if w}
        matched = (norm_val.lower() not in wset)
        out["note"] = "not_in"

    elif op == "gte":
        if not what_list:
            out["status"] = "UNKNOWN"
            out["note"] = "gte_missing_what"
            return out
        a = _as_float(norm_val)
        b = _as_float(what_list[0])
        if a is None or b is None:
            out["status"] = "UNKNOWN"
            out["note"] = "gte_non_numeric"
            return out
        matched = (a >= b)
        out["note"] = f"gte:{b}"

    elif op == "lte":
        if not what_list:
            out["status"] = "UNKNOWN"
            out["note"] = "lte_missing_what"
            return out
        a = _as_float(norm_val)
        b = _as_float(what_list[0])
        if a is None or b is None:
            out["status"] = "UNKNOWN"
            out["note"] = "lte_non_numeric"
            return out
        matched = (a <= b)
        out["note"] = f"lte:{b}"

    elif op == "between":
        if len(what_list) < 2:
            out["status"] = "UNKNOWN"
            out["note"] = "between_requires_two_values"
            return out
        a = _as_float(norm_val)
        lo = _as_float(what_list[0])
        hi = _as_float(what_list[1])
        if a is None or lo is None or hi is None:
            out["status"] = "UNKNOWN"
            out["note"] = "between_non_numeric"
            return out
        if lo > hi:
            lo, hi = hi, lo
        matched = (lo <= a <= hi)
        out["note"] = f"between:{lo}..{hi}"

    if matched is None:
        out["status"] = "UNKNOWN"
        out["note"] = "no_match_result"
        return out

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
