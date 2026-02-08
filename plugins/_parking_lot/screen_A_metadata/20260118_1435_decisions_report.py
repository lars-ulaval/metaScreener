# -*- coding: utf-8 -*-
"""
decisions_report.py — final fusion, exports & quick charts (metadata-only pipeline)
----------------------------------------------------------------------------------

Public API (existing, unchanged):
  aggregate_decisions(meta_results, A: list[dict] | None = None, *, pass_thr=0.60, border_thr=0.40) -> list[dict]
  export_decisions_csv(path, records) -> str
  export_decisions_xlsx(path, records) -> str | None
  export_metadata_audit_csv(path, meta_results) -> str
  export_metadata_audit_xlsx(path, meta_results) -> str | None
  prisma_counts(records) -> dict
  save_metadata_charts(outdir, meta_results) -> dict[str, str]

Substage exports (for per-tab downloads):
  export_eh_csv(path, dropped_rows) -> str
  export_eh_xlsx(path, dropped_rows) -> str | None
  export_ih_csv(path, survivors_ids, A, *, h_pass_map=None, include_flags_map=None) -> str
  export_ih_xlsx(path, survivors_ids, A, *, h_pass_map=None, include_flags_map=None) -> str | None
  export_el_csv(path, dropped_rows) -> str
  export_el_xlsx(path, dropped_rows) -> str | None
  # (Optional convenience) IL = same shape as final decisions:
  export_il_csv(path, final_preview_rows) -> str
  export_il_xlsx(path, final_preview_rows) -> str | None

Notes:
- All joins are done by a_id (never by index).
- CSV exports are always available (stdlib `csv`).
- XLSX exports require pandas+openpyxl; otherwise the function returns None.
- Chart saving requires matplotlib; otherwise it returns {}.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
import os
import csv

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


# ======================================================================================
# 1) Final aggregation — metadata-only
# ======================================================================================

def aggregate_decisions(
    meta_results: List[Dict[str, Any]],
    A: Optional[List[Dict[str, Any]]] = None,
    *,
    pass_thr: float = 0.60,
    border_thr: float = 0.40,
) -> List[Dict[str, Any]]:
    """
    Build final rows from metadata results (and optionally enrich from A).
    If A is provided, we add lang/doc_type/year/venue from A by a_id.

    Echoes thresholds and stage flags for traceability.
    """
    map_A = {str(r.get("a_id")): r for r in (A or [])}

    out: List[Dict[str, Any]] = []
    for mr in meta_results:
        a_id = str(mr.get("a_id"))
        base = map_A.get(a_id, {})
        score = float(mr.get("score") or 0.0)
        label = mr.get("label") or _label_from_score(score, pass_thr=pass_thr, border_thr=border_thr)

        hsv = mr.get("hard_stop_violation") or {}
        hard_stop_triggered = bool(hsv)
        hard_stop_criterion_id = hsv.get("criterion_id")
        hard_stop_criterion_label = hsv.get("criterion_label")

        h_pass = bool(mr.get("h_pass", True if mr.get("per_criterion") is not None else False))
        l_pass = bool(mr.get("l_pass", True))
        seed_used = mr.get("random_seed_used")

        out.append({
            "a_id": a_id,
            "title": mr.get("title") or base.get("title") or "",
            "score": score,
            "label": label,
            "lang": base.get("lang"),
            "doc_type": base.get("doc_type"),
            "year": base.get("year"),
            "venue": base.get("venue"),
            # stage visibility
            "h_pass": h_pass,
            "l_pass": l_pass,
            "stage_h_include_mode": mr.get("stage_h_include_mode"),
            "stage_l_include_mode": mr.get("stage_l_include_mode"),
            "random_seed_used": seed_used,
            # thresholds echoed for reproducibility
            "pass_thr": pass_thr,
            "border_thr": border_thr,
            # hard-stop visibility
            "hard_stop_triggered": hard_stop_triggered,
            "hard_stop_criterion_id": hard_stop_criterion_id,
            "hard_stop_criterion_label": hard_stop_criterion_label,
        })

    # Edge-case: include A items absent from meta_results as fail=0.0
    if A:
        seen = {r["a_id"] for r in out}
        for a in A:
            a_id = str(a.get("a_id"))
            if a_id in seen:
                continue
            out.append({
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

    return out


def _label_from_score(s: float, *, pass_thr: float, border_thr: float) -> str:
    if s >= pass_thr:
        return "pass"
    if s >= border_thr:
        return "borderline"
    return "fail"


# ======================================================================================
# 2) Exports — decisions & metadata audit
# ======================================================================================

_DECISION_COLS = [
    "a_id", "title",
    "score", "label",
    "lang", "doc_type", "year", "venue",
    # stage info
    "h_pass", "l_pass", "stage_h_include_mode", "stage_l_include_mode", "random_seed_used",
    # thresholds
    "pass_thr", "border_thr",
    # hard-stop visibility
    "hard_stop_triggered", "hard_stop_criterion_id", "hard_stop_criterion_label",
]

def export_decisions_csv(path: str, records: List[Dict[str, Any]]) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_DECISION_COLS, extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow({k: r.get(k, "") for k in _DECISION_COLS})
    return path


def export_decisions_xlsx(path: str, records: List[Dict[str, Any]]) -> Optional[str]:
    if not _PANDAS_OK:
        return None
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df = _pd.DataFrame([{k: r.get(k, "") for k in _DECISION_COLS} for r in records])
    df = df[_DECISION_COLS]  # enforce order
    df.to_excel(path, index=False)
    return path


# ---- Metadata audit (long format) ----
# One row per a_id × criterion, including rule_score, llm evidence & fused_score.

_AUDIT_COLS = [
    "a_id", "title",
    "criterion_id", "criterion_label", "criterion_type", "operator", "target", "what", "how",
    "weight", "threshold",
    "rule_score", "fused_score",
    "llm_used", "llm_decision", "llm_confidence", "llm_field", "llm_quote", "llm_span", "llm_valid_quote",
    "item_score", "item_label",
]

def _flatten_audit_rows(meta_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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


def export_metadata_audit_csv(path: str, meta_results: List[Dict[str, Any]]) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rows = _flatten_audit_rows(meta_results)
    if not rows:
        # ensure header
        rows = [{k: "" for k in _AUDIT_COLS}]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_AUDIT_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in _AUDIT_COLS})
    return path


def export_metadata_audit_xlsx(path: str, meta_results: List[Dict[str, Any]]) -> Optional[str]:
    if not _PANDAS_OK:
        return None
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rows = _flatten_audit_rows(meta_results)
    df = _pd.DataFrame(rows, columns=_AUDIT_COLS)
    df.to_excel(path, index=False)
    return path


# ======================================================================================
# 2.5) Substage exports (for E/H, I/H, E/L, and IL preview)
# ======================================================================================

# Columns match the plugin table layouts
_EH_COLS = [
    "a_id","title",
    "criterion_id","criterion_label","operator","target","threshold","rule_score"
]

_IH_COLS = [
    "a_id","title","h_pass","flags_count"
]

_EL_COLS = [
    "a_id","title",
    "criterion_id","criterion_label","operator","target","threshold","rule_score",
    "decision","confidence","decision_field","decision_quote","decision_span","decision_valid_quote",
    "fused_score"
]

def export_eh_csv(path: str, dropped_rows: List[Dict[str, Any]]) -> str:
    """
    Export items dropped during E/H (heuristic excludes).
    Each row in dropped_rows is expected to contain:
      a_id, title, criterion_id, criterion_label, operator, target, threshold, rule_score
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_EH_COLS, extrasaction="ignore")
        w.writeheader()
        for r in dropped_rows or []:
            w.writerow({k: r.get(k, "") for k in _EH_COLS})
    return path


def export_eh_xlsx(path: str, dropped_rows: List[Dict[str, Any]]) -> Optional[str]:
    if not _PANDAS_OK:
        return None
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df = _pd.DataFrame([{k: r.get(k, "") for k in _EH_COLS} for r in (dropped_rows or [])])
    df = df[_EH_COLS]
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
    """
    Export items that survived I/H (heuristic includes).
    - survivors_ids: list of a_id strings
    - A: original A vector (to pull titles)
    - h_pass_map: optional {a_id: bool} from engine
    - include_flags_map: optional {a_id: list-of-flags} to count flags per item
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    title_map = {str(a.get("a_id")): (a.get("title") or "") for a in (A or [])}
    hmap = {str(k): bool(v) for k, v in (h_pass_map or {}).items()}
    fmap = {str(k): (v or []) for k, v in (include_flags_map or {}).items()}

    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_IH_COLS, extrasaction="ignore")
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
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
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
    df = _pd.DataFrame(rows, columns=_IH_COLS)
    df.to_excel(path, index=False)
    return path


def export_el_csv(path: str, dropped_rows: List[Dict[str, Any]]) -> str:
    """
    Export items dropped during E/L (LLM excludes).
    Each row in dropped_rows is expected to contain:
      a_id, title, criterion_id, criterion_label, operator, target, threshold, rule_score,
      llm_decision (dict-like or None), fused_score
    The exporter will expand llm_decision into 'decision' and 'confidence'.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_EL_COLS, extrasaction="ignore")
        w.writeheader()
        for r in dropped_rows or []:
            llm = r.get("llm_decision") or {}
            w.writerow({
                "a_id": r.get("a_id", ""),
                "title": r.get("title", ""),
                "criterion_id": r.get("criterion_id", ""),
                "criterion_label": r.get("criterion_label", ""),
                "operator": r.get("operator", ""),
                "target": r.get("target", ""),
                "threshold": r.get("threshold", ""),
                "rule_score": r.get("rule_score", ""),
                "decision": llm.get("decision", ""),
                "confidence": llm.get("confidence", ""),
                "decision_field": llm.get("field", ""),
                "decision_quote": llm.get("quote", ""),
                "decision_span": str(llm.get("span", "")),
                "decision_valid_quote": llm.get("valid_quote", ""),
                "fused_score": r.get("fused_score", ""),
            })
    return path


def export_el_xlsx(path: str, dropped_rows: List[Dict[str, Any]]) -> Optional[str]:
    if not _PANDAS_OK:
        return None
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rows = []
    for r in dropped_rows or []:
        llm = r.get("llm_decision") or {}
        rows.append({
            "a_id": r.get("a_id", ""),
            "title": r.get("title", ""),
            "criterion_id": r.get("criterion_id", ""),
            "criterion_label": r.get("criterion_label", ""),
            "operator": r.get("operator", ""),
            "target": r.get("target", ""),
            "threshold": r.get("threshold", ""),
            "rule_score": r.get("rule_score", ""),
            "decision": llm.get("decision", ""),
            "confidence": llm.get("confidence", ""),
            "decision_field": llm.get("field", ""),
            "decision_quote": llm.get("quote", ""),
            "decision_span": str(llm.get("span", "")),
            "decision_valid_quote": llm.get("valid_quote", ""),
            "fused_score": r.get("fused_score", ""),
        })
    df = _pd.DataFrame(rows, columns=_EL_COLS)
    df.to_excel(path, index=False)
    return path


# ---- Optional convenience: IL preview export uses the "decisions" shape ----

def export_il_csv(path: str, final_preview_rows: List[Dict[str, Any]]) -> str:
    """
    IL (Final preview) export — same columns as export_decisions_csv.
    """
    return export_decisions_csv(path, final_preview_rows)


def export_il_xlsx(path: str, final_preview_rows: List[Dict[str, Any]]) -> Optional[str]:
    """
    IL (Final preview) export — same columns as export_decisions_xlsx.
    """
    return export_decisions_xlsx(path, final_preview_rows)


# ======================================================================================
# 3) PRISMA-ish counts & quick charts
# ======================================================================================

def prisma_counts(final_rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"pass": 0, "borderline": 0, "fail": 0}
    for r in final_rows or []:
        lab = (r.get("label") or "").lower()
        if lab in counts:
            counts[lab] += 1
    counts["total"] = sum(counts.values())
    return counts


def save_metadata_charts(outdir: str, meta_results: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Saves:
      - label_distribution.png
      - score_histogram.png
    Returns {name: path}. If matplotlib unavailable, returns {}.
    """
    if not _MPL_OK:
        return {}

    os.makedirs(outdir or ".", exist_ok=True)
    paths: Dict[str, str] = {}

    # Label distribution
    labels = [str(r.get("label") or "") for r in (meta_results or [])]
    cats = ["pass", "borderline", "fail"]
    vals = [labels.count(c) for c in cats]

    p1 = os.path.join(outdir, "label_distribution.png")
    _plt.figure(figsize=(5, 3))
    _plt.bar(cats, vals)              # do not set colors (project rule)
    _plt.title("Metadata labels")
    _plt.xlabel("Label")
    _plt.ylabel("Count")
    _plt.tight_layout()
    _plt.savefig(p1, dpi=150)
    _plt.close()
    paths["label_distribution"] = p1

    # Score histogram
    scores = [float(r.get("score") or 0.0) for r in (meta_results or [])]
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
