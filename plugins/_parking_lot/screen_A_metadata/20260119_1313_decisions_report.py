# -*- coding: utf-8 -*-
"""decisions_report.py — Screen A (metadata-only) reporting & exports

This file is the reporting/export layer used by the Screen A screener.

It supports two result formats:
  - Contract v2: dict returned by metadata.screen_metadata(subrun='..')
  - Legacy v1: list[dict] rows containing score/label/per_criterion

Exports:
  - Decisions (CSV/XLSX)
  - Metadata audit (CSV/XLSX)
  - Substage (EH/IH/EL/IL) CSV/XLSX
  - Quick charts (PNG) when matplotlib is available

Notes:
  - Joins are performed by a_id.
  - CSV exports always work.
  - XLSX exports require pandas+openpyxl.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union
import os
import csv
import json

# Optional XLSX via pandas
try:
    import pandas as _pd  # type: ignore
    _PANDAS_OK = True
except Exception:
    _pd = None
    _PANDAS_OK = False

# Optional charts via matplotlib
try:
    import matplotlib
    matplotlib.use("Agg")  # headless
    import matplotlib.pyplot as _plt  # type: ignore
    _MPL_OK = True
except Exception:
    _plt = None
    _MPL_OK = False


# =============================================================================
# Helpers: accept v2 dict OR v1 list
# =============================================================================

V2Result = Dict[str, Any]
V1Rows = List[Dict[str, Any]]


def _is_v2(obj: Any) -> bool:
    return isinstance(obj, dict) and "caches" in obj


def _map_A(A: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    return {str(r.get("a_id")): r for r in (A or [])}


def _safe_json_loads(s: Any) -> Any:
    if s is None:
        return None
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(str(s))
    except Exception:
        return None


def _ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)


def _get_v2_caches(meta: Any) -> Dict[str, Any]:
    if not _is_v2(meta):
        return {}
    return meta.get("caches") or {}


def _get_v2_stage_rows(meta: Any, stage: str) -> List[Dict[str, Any]]:
    caches = _get_v2_caches(meta)
    block = caches.get(stage) or {}
    rows = block.get("rows")
    return list(rows) if isinstance(rows, list) else []


def _get_v2_final_rows(meta: Any) -> List[Dict[str, Any]]:
    if not _is_v2(meta):
        return []
    # Prefer explicit return key
    if isinstance(meta.get("final_results"), list):
        return meta.get("final_results")
    caches = _get_v2_caches(meta)
    final = (caches.get("FINAL") or {}).get("rows")
    return list(final) if isinstance(final, list) else []


def _infer_title_from_A(a_id: str, mapA: Dict[str, Dict[str, Any]], fallback: str = "") -> str:
    base = mapA.get(a_id) or {}
    return str(fallback or base.get("title") or "")


def _v2_join_biblio(row: Dict[str, Any], mapA: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    a_id = str(row.get("a_id"))
    base = mapA.get(a_id) or {}
    out = dict(row)
    # common bibliographic enrich
    for k in ("lang", "doc_type", "year", "venue", "authors", "doi", "source"):
        if k not in out and k in base:
            out[k] = base.get(k)
    # always ensure title exists
    out["title"] = out.get("title") or base.get("title") or ""
    return out


# =============================================================================
# 1) Final aggregation — v2 outcomes (or legacy scores)
# =============================================================================

# Contract v2 decisions columns (FINAL tab + decisions export)
_DECISION_COLS_V2: List[str] = [
    "a_id",
    "title",
    "final_outcome",            # OUT | PASS_CLEAN | REVIEW
    "discarded_at_stage",       # EH|IH|EL|IL|""
    "outcome_EH",
    "outcome_IH",
    "outcome_EL",
    "outcome_IL",
    "history",
    "reasons_EH",
    "reasons_IH",
    "reasons_EL",
    "reasons_IL",
    # optional bibliographic enrich
    "lang", "doc_type", "year", "venue",
]


# Legacy v1 decisions columns (kept for backward compatibility)
_DECISION_COLS_V1: List[str] = [
    "a_id", "title",
    "score", "label",
    "lang", "doc_type", "year", "venue",
    "h_pass", "l_pass", "stage_h_include_mode", "stage_l_include_mode", "random_seed_used",
    "pass_thr", "border_thr",
    "hard_stop_triggered", "hard_stop_criterion_id", "hard_stop_criterion_label",
]


def aggregate_decisions(
    meta_results: Any,
    A: Optional[List[Dict[str, Any]]] = None,
    *,
    pass_thr: float = 0.60,
    border_thr: float = 0.40,
) -> List[Dict[str, Any]]:
    """Build final decision rows.

    - v2 input: returns FINAL rows in v2 shape (no score)
    - v1 input: returns legacy decision rows (score/label)

    If A is provided, the function enriches basic bibliographic fields by a_id.
    """
    mapA = _map_A(A)

    # v2
    if _is_v2(meta_results):
        final_rows = _get_v2_final_rows(meta_results)
        out: List[Dict[str, Any]] = []
        for r in final_rows:
            rr = _v2_join_biblio(r, mapA)
            # ensure mandatory keys exist
            rr.setdefault("final_outcome", "")
            rr.setdefault("discarded_at_stage", "")
            rr.setdefault("outcome_EH", "")
            rr.setdefault("outcome_IH", "")
            rr.setdefault("outcome_EL", "")
            rr.setdefault("outcome_IL", "")
            rr.setdefault("history", "")
            rr.setdefault("reasons_EH", "")
            rr.setdefault("reasons_IH", "")
            rr.setdefault("reasons_EL", "")
            rr.setdefault("reasons_IL", "")
            out.append(rr)

        # Edge-case: include A items absent from results as OUT
        if A:
            seen = {str(x.get("a_id")) for x in out}
            for a in A:
                a_id = str(a.get("a_id"))
                if a_id in seen:
                    continue
                out.append({
                    "a_id": a_id,
                    "title": str(a.get("title") or ""),
                    "final_outcome": "OUT",
                    "discarded_at_stage": "",
                    "outcome_EH": "",
                    "outcome_IH": "",
                    "outcome_EL": "",
                    "outcome_IL": "",
                    "history": "",
                    "reasons_EH": "",
                    "reasons_IH": "",
                    "reasons_EL": "",
                    "reasons_IL": "",
                    "lang": a.get("lang"),
                    "doc_type": a.get("doc_type"),
                    "year": a.get("year"),
                    "venue": a.get("venue"),
                })
        return out

    # v1 (legacy)
    rows: List[Dict[str, Any]] = list(meta_results or [])
    out_v1: List[Dict[str, Any]] = []
    for mr in rows:
        a_id = str(mr.get("a_id"))
        base = mapA.get(a_id, {})
        score = float(mr.get("score") or 0.0)
        label = mr.get("label") or _label_from_score(score, pass_thr=pass_thr, border_thr=border_thr)

        hsv = mr.get("hard_stop_violation") or {}
        hard_stop_triggered = bool(hsv)

        out_v1.append({
            "a_id": a_id,
            "title": mr.get("title") or base.get("title") or "",
            "score": score,
            "label": label,
            "lang": base.get("lang"),
            "doc_type": base.get("doc_type"),
            "year": base.get("year"),
            "venue": base.get("venue"),
            "h_pass": bool(mr.get("h_pass", True if mr.get("per_criterion") is not None else False)),
            "l_pass": bool(mr.get("l_pass", True)),
            "stage_h_include_mode": mr.get("stage_h_include_mode"),
            "stage_l_include_mode": mr.get("stage_l_include_mode"),
            "random_seed_used": mr.get("random_seed_used"),
            "pass_thr": pass_thr,
            "border_thr": border_thr,
            "hard_stop_triggered": hard_stop_triggered,
            "hard_stop_criterion_id": hsv.get("criterion_id"),
            "hard_stop_criterion_label": hsv.get("criterion_label"),
        })

    # Edge-case: include A items absent from meta_results as fail=0.0
    if A:
        seen = {r["a_id"] for r in out_v1}
        for a in A:
            a_id = str(a.get("a_id"))
            if a_id in seen:
                continue
            out_v1.append({
                "a_id": a_id,
                "title": a.get("title") or "",
                "score": 0.0,
                "label": "fail",
                "lang": a.get("lang"),
                "doc_type": a.get("doc_type"),
                "year": a.get("year"),
                "venue": a.get("venue"),
                "h_pass": False,
                "l_pass": False,
                "stage_h_include_mode": None,
                "stage_l_include_mode": None,
                "random_seed_used": None,
                "pass_thr": pass_thr,
                "border_thr": border_thr,
                "hard_stop_triggered": False,
                "hard_stop_criterion_id": None,
                "hard_stop_criterion_label": None,
            })

    return out_v1


def _label_from_score(s: float, *, pass_thr: float, border_thr: float) -> str:
    if s >= pass_thr:
        return "pass"
    if s >= border_thr:
        return "borderline"
    return "fail"

# =============================================================================
# 2) Exports — decisions (CSV/XLSX) + v2 multi-tab report
# =============================================================================

def export_decisions_csv(path: str, records: Any, A: Optional[List[Dict[str, Any]]] = None) -> str:
    """Export final decisions as CSV.

    - v2 input: exports FINAL rows in v2 decision shape.
    - v1 input: exports legacy decisions.

    Note: CSV is single-sheet by definition.
    """
    _ensure_dir(path)

    rows = aggregate_decisions(records, A)
    cols = _DECISION_COLS_V2 if (_is_v2(records)) else _DECISION_COLS_V1

    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})
    return path


def export_decisions_xlsx(path: str, records: Any, A: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
    """Export decisions as XLSX.

    - v2 input: produces the **5-tab report** (EH/IH/EL/IL/FINAL).
    - v1 input: exports a single worksheet (legacy decision table).

    Returns None if pandas is unavailable.
    """
    if not _PANDAS_OK:
        return None

    if _is_v2(records):
        return export_screenA_report_xlsx(path, records, A)

    # legacy single-sheet export
    _ensure_dir(path)
    rows = aggregate_decisions(records, A)
    df = _pd.DataFrame([{k: r.get(k, "") for k in _DECISION_COLS_V1} for r in rows])
    df = df[_DECISION_COLS_V1]
    df.to_excel(path, index=False)
    return path


# ---- v2 multi-tab report (contract) -----------------------------------------

_STAGE_COLS_V2: List[str] = [
    "a_id",
    "title",
    "stage",
    "stage_outcome",            # OUT | PASS | REVIEW
    "passed_to_next",
    "is_out",
    "is_review",
    "is_clean_pass",
    "failed_criteria_ids",
    "missing_criteria_ids",
    "uncertain_criteria_ids",
    "met_criteria_ids",
    "matched_evidence",
    "stage_reason_summary",
    "criteria_details",
    "history",
    # optional biblio
    "lang", "doc_type", "year", "venue",
]


def _stage_key_list() -> List[str]:
    return ["EH", "IH", "EL", "IL"]


def _v2_get_stage_rows(meta_results: Any, stage_key: str) -> List[Dict[str, Any]]:
    if not _is_v2(meta_results):
        return []
    caches = meta_results.get("caches") or {}
    stage = caches.get(stage_key) or {}
    return list(stage.get("rows") or [])


def _v2_normalize_stage_rows(rows: List[Dict[str, Any]], mapA: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in (rows or []):
        a_id = str(r.get("a_id"))
        rr = dict(r)
        oc = str(rr.get("stage_outcome") or "").upper()
        # Backward-compat: older drafts sometimes used PASS
        if oc == "PASS":
            oc = "PASS_CLEAN"

        rr["stage_outcome"] = oc
        rr["is_out"] = (oc == "OUT")
        # Treat PASS_FLAGGED as "review-ish" for reporting/filters
        rr["is_review"] = (oc in ("REVIEW", "PASS_FLAGGED"))
        rr["is_clean_pass"] = (oc == "PASS_CLEAN")

        # list-like to readable strings (but keep originals too if needed)
        for k in ("failed_criteria_ids", "missing_criteria_ids", "uncertain_criteria_ids", "met_criteria_ids"):
            v = rr.get(k)
            if isinstance(v, list):
                rr[k] = ",".join(str(x) for x in v)

        rr = _v2_join_biblio(rr, mapA)
        # ensure all columns exist
        for c in _STAGE_COLS_V2:
            rr.setdefault(c, "")
        out.append(rr)
    return out


def export_screenA_report_xlsx(
    path: str,
    meta_results: Dict[str, Any],
    A: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """Create the **single XLSX report** with 5 worksheets:

      - EH  (heuristic excludes)
      - IH  (heuristic includes)
      - EL  (LLM excludes)
      - IL  (LLM includes)
      - FINAL (final outcome)

    Returns None if pandas is unavailable.

    Notes:
      - If a stage is missing (because only one stage was run), its sheet is still
        created with headers only.
      - If A is provided, biblio fields (lang/doc_type/year/venue) are merged by a_id.
    """
    if not _PANDAS_OK:
        return None

    _ensure_dir(path)
    mapA = _map_A(A)

    # Build frames
    stage_frames: Dict[str, Any] = {}
    for sk in _stage_key_list():
        raw = _v2_get_stage_rows(meta_results, sk)
        norm = _v2_normalize_stage_rows(raw, mapA)
        if not norm:
            stage_frames[sk] = _pd.DataFrame([{c: "" for c in _STAGE_COLS_V2}]).iloc[0:0]
        else:
            stage_frames[sk] = _pd.DataFrame(norm, columns=_STAGE_COLS_V2)

    final_rows = aggregate_decisions(meta_results, A)
    if not final_rows:
        df_final = _pd.DataFrame([{c: "" for c in _DECISION_COLS_V2}]).iloc[0:0]
    else:
        df_final = _pd.DataFrame(final_rows, columns=_DECISION_COLS_V2)

    # Write workbook
    with _pd.ExcelWriter(path, engine="openpyxl") as writer:  # type: ignore
        # sheet names: keep short, stable
        stage_frames["EH"].to_excel(writer, sheet_name="EH", index=False)
        stage_frames["IH"].to_excel(writer, sheet_name="IH", index=False)
        stage_frames["EL"].to_excel(writer, sheet_name="EL", index=False)
        stage_frames["IL"].to_excel(writer, sheet_name="IL", index=False)
        df_final.to_excel(writer, sheet_name="FINAL", index=False)

    return path


# =============================================================================
# 3) Metadata audit (long format) — v2 & legacy
# =============================================================================

_AUDIT_COLS_V2: List[str] = [
    "a_id",
    "title",
    "stage_key",                 # EH/IH/EL/IL
    "stage",                     # human label
    "stage_outcome",
    "final_outcome",
    "discarded_at_stage",
    "criterion_id",
    "criterion_label",
    "criterion_type",
    "status",                    # MET|FAILED|MISSING|UNCERTAIN
    "evidence_kind",             # heuristic|llm
    "operator",
    "target",
    "matched",                   # JSON string (heuristic)
    "decision",
    "confidence",
    "threshold",
    "field",
    "quote",
    "quote_valid",
    # optional biblio
    "lang", "doc_type", "year", "venue",
]


def _flatten_audit_rows_v2(meta_results: Dict[str, Any], mapA: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    final_rows = _get_v2_final_rows(meta_results)
    final_map = {str(r.get("a_id")): r for r in (final_rows or [])}

    rows_out: List[Dict[str, Any]] = []
    for sk in _stage_key_list():
        stage_rows = _v2_get_stage_rows(meta_results, sk)
        for sr in stage_rows or []:
            a_id = str(sr.get("a_id"))
            title = str(sr.get("title") or "")
            stage_label = str(sr.get("stage") or "")
            stage_outcome = str(sr.get("stage_outcome") or "")

            fr = final_map.get(a_id, {})
            final_outcome = fr.get("final_outcome")
            discarded = fr.get("discarded_at_stage")

            details_raw = sr.get("criteria_details")
            details = _safe_json_loads(details_raw)
            if not isinstance(details, list):
                details = []

            for d in details:
                if not isinstance(d, dict):
                    continue
                ev = d.get("evidence") or {}
                if not isinstance(ev, dict):
                    ev = {}

                evidence_kind = ev.get("kind")
                operator = ev.get("operator")
                target = ev.get("target")

                matched = ""
                if evidence_kind == "heuristic":
                    matched = json.dumps(ev.get("matched"), ensure_ascii=False)

                decision = ev.get("decision")
                confidence = ev.get("confidence")
                threshold = ev.get("threshold")
                field = ev.get("field")
                quote = ev.get("quote")
                quote_valid = ev.get("quote_valid")

                row = {
                    "a_id": a_id,
                    "title": title,
                    "stage_key": sk,
                    "stage": stage_label,
                    "stage_outcome": stage_outcome,
                    "final_outcome": final_outcome,
                    "discarded_at_stage": discarded,
                    "criterion_id": d.get("id"),
                    "criterion_label": d.get("label"),
                    "criterion_type": d.get("type"),
                    "status": d.get("status"),
                    "evidence_kind": evidence_kind,
                    "operator": operator,
                    "target": target,
                    "matched": matched,
                    "decision": decision,
                    "confidence": confidence,
                    "threshold": threshold,
                    "field": field,
                    "quote": quote,
                    "quote_valid": quote_valid,
                }
                row = _v2_join_biblio(row, mapA)
                for c in _AUDIT_COLS_V2:
                    row.setdefault(c, "")
                rows_out.append(row)

    return rows_out


# Legacy v1 audit columns (kept)
_AUDIT_COLS_V1: List[str] = [
    "a_id", "title",
    "criterion_id", "criterion_label", "criterion_type", "operator", "target", "what", "how",
    "weight", "threshold",
    "rule_score", "fused_score",
    "llm_used", "llm_decision", "llm_confidence", "llm_field", "llm_quote", "llm_span", "llm_valid_quote",
    "item_score", "item_label",
]


def _flatten_audit_rows_v1(meta_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for it in meta_results or []:
        a_id = it.get("a_id")
        title = it.get("title")
        item_score = it.get("score")
        item_label = it.get("label")
        for pc in (it.get("per_criterion") or []):
            llm = pc.get("llm") or {}
            rows.append({
                "a_id": a_id,
                "title": title,
                "criterion_id": pc.get("id"),
                "criterion_label": pc.get("label"),
                "criterion_type": pc.get("type"),
                "operator": pc.get("operator"),
                "target": pc.get("target"),
                "what": ", ".join(pc.get("what") or []),
                "how": pc.get("how"),
                "weight": pc.get("weight"),
                "threshold": pc.get("threshold"),
                "rule_score": pc.get("rule_score"),
                "fused_score": pc.get("fused_score"),
                "llm_used": llm.get("used", False),
                "llm_decision": llm.get("decision"),
                "llm_confidence": llm.get("confidence"),
                "llm_field": llm.get("field"),
                "llm_quote": llm.get("quote"),
                "llm_span": str(llm.get("span")),
                "llm_valid_quote": llm.get("valid_quote"),
                "item_score": item_score,
                "item_label": item_label,
            })
    return rows


def export_metadata_audit_csv(path: str, meta_results: Any, A: Optional[List[Dict[str, Any]]] = None) -> str:
    _ensure_dir(path)

    if _is_v2(meta_results):
        mapA = _map_A(A)
        rows = _flatten_audit_rows_v2(meta_results, mapA)
        cols = _AUDIT_COLS_V2
    else:
        rows = _flatten_audit_rows_v1(list(meta_results or []))
        cols = _AUDIT_COLS_V1

    if not rows:
        rows = [{k: "" for k in cols}]

    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})
    return path


def export_metadata_audit_xlsx(path: str, meta_results: Any, A: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
    if not _PANDAS_OK:
        return None

    _ensure_dir(path)
    if _is_v2(meta_results):
        mapA = _map_A(A)
        rows = _flatten_audit_rows_v2(meta_results, mapA)
        df = _pd.DataFrame(rows, columns=_AUDIT_COLS_V2)
        df.to_excel(path, index=False)
        return path

    rows = _flatten_audit_rows_v1(list(meta_results or []))
    df = _pd.DataFrame(rows, columns=_AUDIT_COLS_V1)
    df.to_excel(path, index=False)
    return path


# =============================================================================
# 4) Substage exports (EH/IH/EL/IL) — wrappers for UI downloads
# =============================================================================

# Columns match the stage sheets, but reduced for lightweight CSV downloads
_EH_COLS: List[str] = [
    "a_id", "title",
    "stage_outcome",
    "failed_criteria_ids",
    "missing_criteria_ids",
    "uncertain_criteria_ids",
    "matched_evidence",
    "stage_reason_summary",
]

_IH_COLS: List[str] = [
    "a_id", "title",
    "stage_outcome",
    "failed_criteria_ids",
    "missing_criteria_ids",
    "uncertain_criteria_ids",
    "matched_evidence",
    "stage_reason_summary",
]

_EL_COLS: List[str] = [
    "a_id", "title",
    "stage_outcome",
    "failed_criteria_ids",
    "missing_criteria_ids",
    "uncertain_criteria_ids",
    "matched_evidence",
    "stage_reason_summary",
]


def _stage_drop_only(stage_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in stage_rows or []:
        if str(r.get("stage_outcome") or "").upper() == "OUT":
            out.append(r)
    return out


def export_eh_csv(path: str, dropped_rows: Any) -> str:
    """Export items dropped during EH.

    Accepts either:
      - a pre-filtered list of dropped rows
      - a full EH stage rows list (will filter OUT rows)
    """
    _ensure_dir(path)
    rows = list(dropped_rows or [])
    # If rows look like full stage rows, filter
    if rows and ("stage_outcome" in rows[0]):
        rows = _stage_drop_only(rows)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_EH_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in _EH_COLS})
    return path


def export_eh_xlsx(path: str, dropped_rows: Any) -> Optional[str]:
    if not _PANDAS_OK:
        return None
    _ensure_dir(path)
    rows = list(dropped_rows or [])
    if rows and ("stage_outcome" in rows[0]):
        rows = _stage_drop_only(rows)
    df = _pd.DataFrame(rows, columns=_EH_COLS)
    df.to_excel(path, index=False)
    return path


def export_ih_csv(
    path: str,
    survivors_ids: List[str],
    A: List[Dict[str, Any]],
    *,
    h_pass_map: Optional[Dict[str, bool]] = None,
    include_flags_map: Optional[Dict[str, List[Any]]] = None,
) -> str:
    """Legacy-compatible IH export.

    In v2, callers typically export the IH sheet via `export_screenA_report_xlsx`.
    This function remains available for the UI download button.
    """
    _ensure_dir(path)
    title_map = {str(a.get("a_id")): (a.get("title") or "") for a in (A or [])}
    hmap = {str(k): bool(v) for k, v in (h_pass_map or {}).items()}
    fmap = {str(k): (v or []) for k, v in (include_flags_map or {}).items()}

    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["a_id", "title", "h_pass", "flags_count"], extrasaction="ignore")
        w.writeheader()
        for aid in survivors_ids or []:
            w.writerow({
                "a_id": aid,
                "title": title_map.get(aid, ""),
                "h_pass": "yes" if hmap.get(aid, True) else "no",
                "flags_count": len(fmap.get(aid, [])),
            })
    return path


def export_ih_xlsx(
    path: str,
    survivors_ids: List[str],
    A: List[Dict[str, Any]],
    *,
    h_pass_map: Optional[Dict[str, bool]] = None,
    include_flags_map: Optional[Dict[str, List[Any]]] = None,
) -> Optional[str]:
    if not _PANDAS_OK:
        return None
    _ensure_dir(path)
    title_map = {str(a.get("a_id")): (a.get("title") or "") for a in (A or [])}
    hmap = {str(k): bool(v) for k, v in (h_pass_map or {}).items()}
    fmap = {str(k): (v or []) for k, v in (include_flags_map or {}).items()}

    rows = []
    for aid in survivors_ids or []:
        rows.append({
            "a_id": aid,
            "title": title_map.get(aid, ""),
            "h_pass": "yes" if hmap.get(aid, True) else "no",
            "flags_count": len(fmap.get(aid, [])),
        })
    df = _pd.DataFrame(rows, columns=["a_id", "title", "h_pass", "flags_count"])
    df.to_excel(path, index=False)
    return path


def export_el_csv(path: str, dropped_rows: Any) -> str:
    """Export items dropped during EL.

    Accepts either:
      - a pre-filtered list of dropped rows
      - a full EL stage rows list (will filter OUT rows)
    """
    _ensure_dir(path)
    rows = list(dropped_rows or [])
    if rows and ("stage_outcome" in rows[0]):
        rows = _stage_drop_only(rows)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_EL_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in _EL_COLS})
    return path


def export_el_xlsx(path: str, dropped_rows: Any) -> Optional[str]:
    if not _PANDAS_OK:
        return None
    _ensure_dir(path)
    rows = list(dropped_rows or [])
    if rows and ("stage_outcome" in rows[0]):
        rows = _stage_drop_only(rows)
    df = _pd.DataFrame(rows, columns=_EL_COLS)
    df.to_excel(path, index=False)
    return path


def export_il_csv(path: str, final_preview_rows: Any) -> str:
    """IL preview export (final table)."""
    return export_decisions_csv(path, final_preview_rows)


def export_il_xlsx(path: str, final_preview_rows: Any) -> Optional[str]:
    """IL preview export (final table)."""
    return export_decisions_xlsx(path, final_preview_rows)


# =============================================================================
# 5) PRISMA-ish counts & quick charts
# =============================================================================

def prisma_counts(final_rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """Counts by outcome.

    - v2: counts final_outcome (OUT / REVIEW / PASS_CLEAN)
    - v1: counts label (pass / borderline / fail)

    Note: plugin.py expects the key 'TOTAL' (uppercase).
    """
    if not final_rows:
        return {"PASS_CLEAN": 0, "REVIEW": 0, "OUT": 0, "TOTAL": 0}

    # v2
    if "final_outcome" in (final_rows[0] or {}):
        counts = {"PASS_CLEAN": 0, "REVIEW": 0, "OUT": 0}
        for r in final_rows:
            v = str(r.get("final_outcome") or "").upper()
            if v in counts:
                counts[v] += 1
        counts["TOTAL"] = sum(counts.values())
        return counts

    # v1 (legacy)
    counts = {"pass": 0, "borderline": 0, "fail": 0}
    for r in final_rows:
        lab = str(r.get("label") or "").lower()
        if lab in counts:
            counts[lab] += 1
    counts["TOTAL"] = sum(counts.values())
    return counts

def save_metadata_charts(outdir: str, meta_results: Any) -> Dict[str, str]:
    """Save quick charts; returns {name: filepath}. If matplotlib unavailable, returns {}.

    v2 charts:
      - final_outcome_distribution.png
      - survivors_by_stage.png

    legacy charts:
      - label_distribution.png
      - score_histogram.png
    """
    if not _MPL_OK:
        return {}

    os.makedirs(outdir or ".", exist_ok=True)
    paths: Dict[str, str] = {}

    # v2
    if _is_v2(meta_results):
        final_rows = _get_v2_final_rows(meta_results)
        finals = [str(r.get("final_outcome") or "").upper() for r in (final_rows or [])]
        cats = ["PASS_CLEAN", "REVIEW", "OUT"]
        vals = [finals.count(c) for c in cats]

        p1 = os.path.join(outdir, "final_outcome_distribution.png")
        _plt.figure(figsize=(6, 3))
        _plt.bar(cats, vals)
        _plt.title("Final outcomes")
        _plt.xlabel("Outcome")
        _plt.ylabel("Count")
        _plt.tight_layout()
        _plt.savefig(p1, dpi=150)
        _plt.close()
        paths["final_outcome_distribution"] = p1

        # Survivors after each stage (based on stage rows)
        survivor_counts = []
        labels = []
        for sk in _stage_key_list():
            sr = _v2_get_stage_rows(meta_results, sk)
            if not sr:
                continue
            labels.append(sk)
            survivor_counts.append(
                sum(1 for r in sr if str(r.get("stage_outcome") or "").upper() != "OUT")
            )

        p2 = os.path.join(outdir, "survivors_by_stage.png")
        _plt.figure(figsize=(6, 3))
        if labels:
            _plt.bar(labels, survivor_counts)
        _plt.title("Survivors by stage")
        _plt.xlabel("Stage")
        _plt.ylabel("Count")
        _plt.tight_layout()
        _plt.savefig(p2, dpi=150)
        _plt.close()
        paths["survivors_by_stage"] = p2

        return paths

    # legacy charts
    meta_rows: List[Dict[str, Any]] = list(meta_results or [])
    labels = [str(r.get("label") or "") for r in meta_rows]
    cats = ["pass", "borderline", "fail"]
    vals = [labels.count(c) for c in cats]

    p1 = os.path.join(outdir, "label_distribution.png")
    _plt.figure(figsize=(5, 3))
    _plt.bar(cats, vals)
    _plt.title("Metadata labels")
    _plt.xlabel("Label")
    _plt.ylabel("Count")
    _plt.tight_layout()
    _plt.savefig(p1, dpi=150)
    _plt.close()
    paths["label_distribution"] = p1

    scores = [float(r.get("score") or 0.0) for r in meta_rows]
    p2 = os.path.join(outdir, "score_histogram.png")
    _plt.figure(figsize=(5, 3))
    _plt.hist(scores, bins=20)
    _plt.title("Metadata scores")
    _plt.xlabel("Score")
    _plt.ylabel("Frequency")
    _plt.tight_layout()
    _plt.savefig(p2, dpi=150)
    _plt.close()
    paths["score_histogram"] = p2

    return paths
