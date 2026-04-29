# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
plugin.py — Harmoniser (Criteria) as a metaScreener tab plugin

Single-file, self-contained (UI + engine).

What it does
- Requires BOTH:
  1) Criteria input: free-text IC/EC (TXT/RTF) or structured criteria table (CSV/XLSX)
  2) A vector: *_aggregate.csv
- Uses the A header to:
  - populate target pickers
  - apply alias mapping (language->lang, type->doc_type, journal->venue, ...), safely (only when the alias exists)
  - validate that targets reference real columns
  - export a cleaned A ("current.csv") containing ONLY integral rows (exact header width)
- Harmonises criteria into stage-explicit rows for the split pipeline:
  EH / IH / EL / IL
- Optional LLM refinement (OpenAI) with strict guardrails.

Exports (Bundle ZIP)
- One single "Screen A Bundle" ZIP that can be used as input for any later stage plugin (EH/IH/EL/IL):
  ScreenA_Bundle/
    manifest.json
    data/
      current.csv
      input_errors.csv          (only if invalid rows were skipped)
    criteria/
      criteria_harmonized.csv
      criteria_harmonized.txt   (pipe-table)
      criteria_source.txt       (what you edited in the text box)

Notes
- This module does NOT screen articles.
- It only harmonises criteria and produces a robust bundle artifact for downstream plugins.
"""

TAB_TITLE = "Harmoniser — Criteria"

import csv
import hashlib
import json
import os
import re
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from metascreener.plugin_api import PluginMeta, BasePlugin

from .parser import (
    STAGES,
    OPERATORS,
    _now_iso,
    _norm_space,
    _safe_str,
    _read_text_file,
    _rtf_to_text,
    _is_rtf_path,
    _load_a_header_and_stats,
    _get_best_text_targets,
    _detect_id_column,
    _canonicalize_targets,
    _parse_what_cell,
    _what_to_export,
    _export_to_pipe_table,
    _parse_free_text_criteria,
    _load_structured_criteria_table,
    _normalize_structured_row,
)

from .inference import (
    DEFAULT_TEXT_TARGET,
    DEFAULT_THRESHOLD,
    _infer_criterion_details,
    _validate_row,
)

BUNDLE_SCHEMA = "screenA_bundle_v1"
BUNDLE_ROOT_NAME = "ScreenA_Bundle"


def _export_csv(rows: List[Dict[str, Any]], path: str) -> None:
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

    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
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

    errors_rows: List[Dict[str, Any]] = []

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
                        errors_rows.append({
                            "record_number": record_no,
                            "reason": "wrong_column_count",
                            "observed_len": len(row),
                            "expected_len": expected,
                            "raw": raw,
                        })
                    continue

                writer.writerow(row)
                stats["rows_valid_written"] += 1

    if out_errors_csv is not None and errors_rows:
        with out_errors_csv.open("w", encoding="utf-8", newline="") as f_err:
            w = csv.DictWriter(
                f_err,
                fieldnames=["record_number", "reason", "observed_len", "expected_len", "raw"],
            )
            w.writeheader()
            for r in errors_rows:
                w.writerow(r)

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


def _call_openai_json(model: str, system: str, user: str, timeout_s: int = 120) -> Dict[str, Any]:
    """Best-effort OpenAI call returning JSON."""
    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
        )
        txt = resp.choices[0].message.content or ""
        return json.loads(txt)
    except Exception:
        pass

    try:
        import openai  # type: ignore
        resp = openai.ChatCompletion.create(  # type: ignore[attr-defined]
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
            request_timeout=timeout_s,
        )
        txt = resp["choices"][0]["message"]["content"] or ""
        return json.loads(txt)
    except Exception as e:
        raise RuntimeError(f"LLM call failed: {e}")


def _llm_available() -> bool:
    if not os.getenv("OPENAI_API_KEY"):
        return False
    try:
        import openai  # noqa: F401
        return True
    except Exception:
        try:
            from openai import OpenAI  # noqa: F401
            return True
        except Exception:
            return False


def _llm_refine(
    rows: List[Dict[str, Any]],
    full_criteria_text: str,
    a_columns: Sequence[str],
    model: str,
    log: Optional[callable] = None,
) -> List[Dict[str, Any]]:
    """LLM-assisted refinement (guardrailed)."""
    def _log(msg: str) -> None:
        if log:
            log(msg)

    _log("LLM refine: preparing prompt…")

    compact = []
    for r in rows:
        compact.append({
            "id": r.get("id"),
            "type": r.get("type"),
            "stage": r.get("stage"),
            "label": r.get("label"),
            "operator": r.get("operator"),
            "target": r.get("target"),
            "what": r.get("what"),
            "threshold": r.get("threshold"),
            "enabled": r.get("enabled"),
            "source_text": r.get("source_text"),
        })

    system = (
        "You are a strict criteria harmoniser for PRISMA screening.\n"
        "Return ONLY valid JSON. No Markdown, no prose.\n\n"
        "SCREENING STAGES:\n"
        "EH = Exclusion Heuristic (hard metadata rule)\n"
        "IH = Inclusion Heuristic (hard metadata rule)\n"
        "EL = Exclusion LLM/semantic (soft rule, threshold required)\n"
        "IL = Inclusion LLM/semantic (soft rule, threshold required)\n\n"
        "OPERATORS:\n"
        "equals: exact match\n"
        "in_list: value is in list\n"
        "not_in: value not in list\n"
        "gte/lte/between: numeric/date comparisons\n"
        "contains/regex: text matching\n"
        "llm: semantic rule; what MUST be exactly one short declarative sentence\n\n"
        "HARD RULES:\n"
        "- Keep SAME number of rows.\n"
        "- Do NOT change ids or types.\n"
        "- target MUST be subset of allowed A columns.\n"
        "- If unsure, prefer operator=llm and stage IL/EL.\n"
        "- Threshold: blank for EH/IH; for EL/IL must be 0..1 string (default 0.60).\n\n"
        "Output schema:\n"
        "{ \"rows\": [ {\"id\":...,\"type\":...,\"stage\":...,\"label\":...,"
        "\"operator\":...,\"target\":...,\"what\":...,\"threshold\":...,\"enabled\":...}, ... ] }\n"
    )

    user_payload = {
        "task": "Refine criteria rows based on the full criteria text and allowed A columns.",
        "allowed_a_columns": list(a_columns),
        "full_criteria_text": full_criteria_text[:8000],
        "rows": compact,
    }
    user = json.dumps(user_payload, ensure_ascii=False)

    _log(f"LLM refine: calling OpenAI model={model} …")
    d = _call_openai_json(model=model, system=system, user=user)

    if not isinstance(d, dict) or "rows" not in d or not isinstance(d["rows"], list):
        raise RuntimeError("LLM response missing 'rows' list")

    got = d["rows"]
    if len(got) != len(rows):
        raise RuntimeError(f"LLM changed row count (expected {len(rows)}, got {len(got)})")

    expected = [(r.get("id"), r.get("type")) for r in rows]

    out_rows: List[Dict[str, Any]] = []
    for i, rr in enumerate(got):
        if not isinstance(rr, dict):
            raise RuntimeError("LLM produced a non-object row")
        exp_id, exp_type = expected[i]
        if _safe_str(rr.get("id")).strip() != _safe_str(exp_id).strip():
            raise RuntimeError(f"LLM changed id at index {i}")
        if _safe_str(rr.get("type")).strip().lower() != _safe_str(exp_type).strip().lower():
            raise RuntimeError(f"LLM changed type at index {i}")

        nr = {
            "stage": _safe_str(rr.get("stage")).strip().upper(),
            "id": _safe_str(rr.get("id")).strip(),
            "type": _safe_str(rr.get("type")).strip().lower(),
            "scope": "metadata",
            "label": _safe_str(rr.get("label") or rows[i].get("label")).strip(),
            "operator": _safe_str(rr.get("operator")).strip().lower(),
            "target": _safe_str(rr.get("target")).strip(),
            "what": rr.get("what"),
            "threshold": _safe_str(rr.get("threshold", "")).strip(),
            "enabled": bool(rr.get("enabled", True)),
            "source_text": rows[i].get("source_text", ""),
        }

        if not isinstance(nr["what"], list):
            nr["what"] = _parse_what_cell(nr["operator"] or "contains", nr["what"])
        nr["what"] = [str(x) for x in nr["what"] if str(x).strip()]

        errs, warns = _validate_row(nr, a_columns)
        if errs:
            raise RuntimeError(f"LLM refined row invalid ({nr.get('id')}): {', '.join(errs)}")
        for w in warns:
            _log(f"LLM refined row warning ({nr.get('id')}): {w}")

        out_rows.append(nr)

    _log("LLM refine: done.")
    return out_rows


# ============================
# UI
# ============================

@dataclass
class _UiState:
    criteria_path: str = ""
    criteria_kind: str = ""  # rtf/txt/csv/xlsx/paste
    a_path: str = ""
    a_columns: List[str] = None  # type: ignore
    a_id_col: str = ""
    text_stats: Dict[str, float] = None  # type: ignore
    criteria_text: str = ""
    rows: List[Dict[str, Any]] = None  # type: ignore

    def __post_init__(self):
        if self.a_columns is None:
            self.a_columns = []
        if self.text_stats is None:
            self.text_stats = {}
        if self.rows is None:
            self.rows = []


class HarmoniserView(ttk.Frame):
    def __init__(self, master: tk.Misc):
        super().__init__(master)
        self.state = _UiState()

        self._worker: Optional[threading.Thread] = None
        self._worker_err: Optional[str] = None
        self._worker_done: bool = False

        self._build_ui()
        self._refresh_buttons()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        top.columnconfigure(1, weight=1)

        crit_box = ttk.LabelFrame(top, text="1) Criteria (required)")
        crit_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        ttk.Button(crit_box, text="Load TXT/RTF…", command=self._load_criteria_text).grid(row=0, column=0, padx=6, pady=6, sticky="ew")
        ttk.Button(crit_box, text="Load table CSV/XLSX…", command=self._load_criteria_table).grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        ttk.Button(crit_box, text="Clear", command=self._clear_criteria).grid(row=0, column=2, padx=6, pady=6, sticky="ew")

        self.lbl_crit = ttk.Label(crit_box, text="No criteria loaded")
        self.lbl_crit.grid(row=1, column=0, columnspan=3, padx=6, pady=(0, 6), sticky="w")

        a_box = ttk.LabelFrame(top, text="2) A vector (required)")
        a_box.grid(row=0, column=1, sticky="nsew")
        a_box.columnconfigure(0, weight=1)

        row0 = ttk.Frame(a_box)
        row0.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        row0.columnconfigure(1, weight=1)

        ttk.Button(row0, text="Load A CSV…", command=self._load_a_csv).grid(row=0, column=0, sticky="w")
        self.lbl_a = ttk.Label(row0, text="No A loaded")
        self.lbl_a.grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.lbl_a_stats = ttk.Label(a_box, text="")
        self.lbl_a_stats.grid(row=1, column=0, sticky="w", padx=6, pady=(0, 6))

        body = ttk.Panedwindow(self, orient="horizontal")
        body.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))

        left = ttk.Frame(body)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        left_top = ttk.Frame(left)
        left_top.grid(row=0, column=0, sticky="ew")
        left_top.columnconfigure(3, weight=1)

        ttk.Label(left_top, text="Criteria text (editable):").grid(row=0, column=0, sticky="w")

        self.var_llm = tk.BooleanVar(value=False)
        ttk.Checkbutton(left_top, text="LLM refine", variable=self.var_llm, command=self._refresh_buttons).grid(row=0, column=1, padx=(10, 0), sticky="w")

        ttk.Label(left_top, text="Model:").grid(row=0, column=2, padx=(10, 0), sticky="e")
        self.ent_model = ttk.Entry(left_top, width=18)
        self.ent_model.insert(0, "gpt-4o-mini")
        self.ent_model.grid(row=0, column=3, sticky="w")

        self.lbl_key = ttk.Label(left_top, text="API key: " + ("OK" if os.getenv("OPENAI_API_KEY") else "missing"))
        self.lbl_key.grid(row=0, column=4, padx=(10, 0), sticky="w")

        txt_frame = ttk.Frame(left)
        txt_frame.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        txt_frame.rowconfigure(0, weight=1)
        txt_frame.columnconfigure(0, weight=1)

        self.txt_criteria = tk.Text(txt_frame, height=18, wrap="word")
        ysb = ttk.Scrollbar(txt_frame, orient="vertical", command=self.txt_criteria.yview)
        self.txt_criteria.configure(yscrollcommand=ysb.set)

        self.txt_criteria.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")

        body.add(left, weight=1)

        right = ttk.Frame(body)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(3, weight=1)

        btns = ttk.Frame(right)
        btns.grid(row=0, column=0, sticky="ew")

        self.btn_harmonise = ttk.Button(btns, text="Harmonise (no-LLM)", command=self._harmonise_no_llm)
        self.btn_harmonise.grid(row=0, column=0, padx=(0, 6), pady=(0, 6), sticky="w")

        self.btn_harmonise_llm = ttk.Button(btns, text="Harmonise + LLM", command=self._harmonise_llm)
        self.btn_harmonise_llm.grid(row=0, column=1, padx=(0, 6), pady=(0, 6), sticky="w")

        self.btn_validate = ttk.Button(btns, text="Validate", command=self._validate)
        self.btn_validate.grid(row=0, column=2, padx=(0, 6), pady=(0, 6), sticky="w")

        self.btn_export = ttk.Button(btns, text="Export bundle…", command=self._export_bundle)
        self.btn_export.grid(row=0, column=3, padx=(0, 6), pady=(0, 6), sticky="w")

        self.btn_pick_target = ttk.Button(btns, text="Pick target(s)…", command=self._pick_targets)
        self.btn_pick_target.grid(row=0, column=4, padx=(0, 6), pady=(0, 6), sticky="w")

        table_frame = ttk.LabelFrame(right, text="Harmonised criteria")
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        cols = ("stage", "id", "type", "label", "operator", "target", "what", "threshold", "enabled")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="extended")
        for c in cols:
            self.tree.heading(c, text=c)
            width = 80
            if c == "label":
                width = 260
            elif c == "target":
                width = 220
            elif c == "what":
                width = 280
            elif c == "id":
                width = 90
            elif c == "enabled":
                width = 70
            self.tree.column(c, width=width, anchor="w")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self.tree.tag_configure("error", background="#ffe5e5")
        self.tree.tag_configure("warn", background="#fff6d5")
        self.tree.bind("<Double-1>", self._on_double_click)

        log_frame = ttk.LabelFrame(right, text="Log")
        log_frame.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.txt_log = tk.Text(log_frame, height=10, wrap="word", state="disabled")
        logsb = ttk.Scrollbar(log_frame, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=logsb.set)

        self.txt_log.grid(row=0, column=0, sticky="nsew")
        logsb.grid(row=0, column=1, sticky="ns")

        body.add(right, weight=2)

        self._edit_widget: Optional[tk.Widget] = None

    def _log(self, msg: str) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"[{_now_iso()}] {msg}\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _refresh_buttons(self) -> None:
        has_crit = bool(self.txt_criteria.get("1.0", "end").strip()) or bool(self.state.rows)
        has_a = bool(self.state.a_path) and bool(self.state.a_columns)
        can_h = has_crit and has_a and (self._worker is None)

        self.btn_harmonise.configure(state=("normal" if can_h else "disabled"))

        llm_ok = _llm_available()
        self.lbl_key.configure(text="API key: " + ("OK" if llm_ok else "missing"))

        self.btn_harmonise_llm.configure(state=("normal" if (can_h and llm_ok) else "disabled"))
        self.btn_validate.configure(state=("normal" if (bool(self.state.rows) and has_a and self._worker is None) else "disabled"))
        self.btn_export.configure(state=("normal" if (bool(self.state.rows) and has_a and self._worker is None) else "disabled"))
        self.btn_pick_target.configure(state=("normal" if (bool(self.state.rows) and has_a and self._worker is None) else "disabled"))

    def _ensure_ready(self) -> bool:
        if not (self.state.a_path and self.state.a_columns):
            messagebox.showwarning("Missing A", "Please load the A vector CSV first.")
            return False
        if not (self.txt_criteria.get("1.0", "end").strip() or self.state.rows):
            messagebox.showwarning("Missing criteria", "Please load/paste criteria first.")
            return False
        return True

    def _load_criteria_text(self) -> None:
        path = filedialog.askopenfilename(
            title="Load criteria TXT/RTF",
            filetypes=[("Text/RTF", "*.txt *.rtf"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            raw = _read_text_file(path)
            if _is_rtf_path(path):
                raw = _rtf_to_text(raw)
            raw = raw.replace("\r\n", "\n").replace("\r", "\n")
            self.state.criteria_path = path
            self.state.criteria_kind = "rtf" if _is_rtf_path(path) else "txt"
            self.state.criteria_text = raw
            self.txt_criteria.delete("1.0", "end")
            self.txt_criteria.insert("1.0", raw)
            self.state.rows = []
            self._clear_table()
            self.lbl_crit.configure(text=f"Loaded: {Path(path).name}")
            self._log(f"Criteria loaded ({self.state.criteria_kind}): {path}")
        except Exception as e:
            messagebox.showerror("Load failed", str(e))
        finally:
            self._refresh_buttons()

    def _load_criteria_table(self) -> None:
        path = filedialog.askopenfilename(
            title="Load criteria table",
            filetypes=[("CSV/XLSX", "*.csv *.xlsx *.xlsm"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            raw_rows, kind = _load_structured_criteria_table(path)
            self.state.criteria_path = path
            self.state.criteria_kind = kind

            self.txt_criteria.delete("1.0", "end")
            self.txt_criteria.insert(
                "1.0",
                "\n".join([_safe_str(r) for r in raw_rows[:20]]) + ("\n…" if len(raw_rows) > 20 else ""),
            )

            self.state.criteria_text = "\n".join([_safe_str(r) for r in raw_rows])

            self.state.rows = [_normalize_structured_row(r) for r in raw_rows]
            self._render_rows()
            self.lbl_crit.configure(text=f"Loaded: {Path(path).name} ({len(self.state.rows)} rows)")
            self._log(f"Criteria table loaded ({kind}): {path}")
        except Exception as e:
            messagebox.showerror("Load failed", str(e))
        finally:
            self._refresh_buttons()

    def _clear_criteria(self) -> None:
        self.state.criteria_path = ""
        self.state.criteria_kind = ""
        self.state.criteria_text = ""
        self.txt_criteria.delete("1.0", "end")
        self.state.rows = []
        self._clear_table()
        self.lbl_crit.configure(text="No criteria loaded")
        self._log("Criteria cleared")
        self._refresh_buttons()

    def _load_a_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="Load A vector CSV",
            filetypes=[("CSV", "*.csv"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            cols, stats = _load_a_header_and_stats(path)
            self.state.a_path = path
            self.state.a_columns = cols
            self.state.text_stats = stats
            self.state.a_id_col = _detect_id_column(cols)

            self.lbl_a.configure(text=f"Loaded: {Path(path).name} ({len(cols)} cols), id={self.state.a_id_col}")

            if stats:
                s = " / ".join([f"{k}:{stats[k]*100:.0f}%" for k in stats])
                self.lbl_a_stats.configure(text=f"Text coverage (sample): {s}")
            else:
                self.lbl_a_stats.configure(text="")

            self._log(f"A loaded: {path}")

            if self.state.rows:
                self._validate(show_ok=False)

        except Exception as e:
            messagebox.showerror("Load failed", str(e))
        finally:
            self._refresh_buttons()

    def _harmonise_no_llm(self) -> None:
        if not self._ensure_ready():
            return

        # Dynamic default text target from A coverage
        default_text_target = _get_best_text_targets(self.state.a_columns, self.state.text_stats)
        default_text_target, _ = _canonicalize_targets(default_text_target, self.state.a_columns)

        # If rows already exist (structured), infer missing fields conservatively
        if self.state.rows:
            self._log("Harmonise (no-LLM): inferring missing fields in existing rows…")
            for r in self.state.rows:
                crit_type = _safe_str(r.get("type")).lower() or "include"
                seed_text = _safe_str(r.get("label")) or _safe_str(r.get("source_text")) or ""

                needs = (
                    not _safe_str(r.get("stage")).strip()
                    or not _safe_str(r.get("operator")).strip()
                    or not _safe_str(r.get("target")).strip()
                    or not isinstance(r.get("what"), list)
                    or len(r.get("what") or []) == 0
                )

                if needs:
                    inferred = _infer_criterion_details(
                        _safe_str(r.get("id")),
                        crit_type,
                        seed_text,
                        list(self.state.a_columns),
                        default_text_target,
                    )
                    if not _safe_str(r.get("stage")).strip():
                        r["stage"] = inferred["stage"]
                    if not _safe_str(r.get("operator")).strip():
                        r["operator"] = inferred["operator"]
                    if not _safe_str(r.get("target")).strip():
                        r["target"] = inferred["target"]
                    if not isinstance(r.get("what"), list) or not (r.get("what") or []):
                        r["what"] = inferred["what"]

                st = _safe_str(r.get("stage")).upper()
                if st in {"EH", "IH"}:
                    r["threshold"] = ""
                else:
                    if not _safe_str(r.get("threshold")).strip():
                        r["threshold"] = f"{DEFAULT_THRESHOLD:.2f}"

                r["target"], _ = _canonicalize_targets(_safe_str(r.get("target")), self.state.a_columns)

            self._render_rows(with_validation=True)
            self._validate(show_ok=True)
            return

        # Free-text parse path
        text = self.txt_criteria.get("1.0", "end")
        parsed = _parse_free_text_criteria(text)
        if not parsed:
            messagebox.showerror("No criteria found", "No criteria detected. Check formatting (IC/EC lines or headers).")
            return

        self._log(f"Harmonise (no-LLM): parsed {len(parsed)} criteria; inferring rules…")

        rows: List[Dict[str, Any]] = []
        for crit_id, crit_type, label, source_line in parsed:
            inferred = _infer_criterion_details(
                crit_id=crit_id,
                crit_type=crit_type,
                label=label,
                a_columns=list(self.state.a_columns),
                default_text_target=default_text_target,
            )

            stage = inferred["stage"]
            operator = inferred["operator"]
            target = inferred["target"]
            what = inferred["what"]

            threshold = ""
            if stage in {"EL", "IL"}:
                threshold = f"{DEFAULT_THRESHOLD:.2f}"

            rows.append({
                "stage": stage,
                "id": crit_id,
                "type": crit_type,
                "scope": "metadata",
                "label": label,
                "operator": operator,
                "target": target,
                "what": what,
                "threshold": threshold,
                "enabled": True,
                "source_text": source_line,
            })

        self.state.rows = rows
        self._render_rows(with_validation=True)
        self._validate(show_ok=True)

    def _harmonise_llm(self) -> None:
        if not self._ensure_ready():
            return
        if not _llm_available():
            messagebox.showwarning("LLM unavailable", "OPENAI_API_KEY missing or OpenAI package not available.")
            return

        if not self.state.rows:
            self._harmonise_no_llm()
            if not self.state.rows:
                return

        model = self.ent_model.get().strip() or "gpt-4o-mini"
        full_text = self.txt_criteria.get("1.0", "end").strip() or self.state.criteria_text

        def worker():
            try:
                refined = _llm_refine(self.state.rows, full_text, self.state.a_columns, model=model, log=self._thread_log)
                self.state.rows = refined
                self._worker_err = None
            except Exception as e:
                self._worker_err = str(e)
            finally:
                self._worker_done = True

        self._start_worker(worker, "LLM harmonisation")

    def _thread_log(self, msg: str) -> None:
        self.after(0, lambda: self._log(msg))

    def _start_worker(self, target, label: str) -> None:
        if self._worker is not None:
            return
        self._worker_done = False
        self._worker_err = None

        self._log(f"Starting: {label} …")
        self._worker = threading.Thread(target=target, daemon=True)
        self._worker.start()
        self._refresh_buttons()
        self.after(100, self._poll_worker)

    def _poll_worker(self) -> None:
        if self._worker is None:
            return
        if not self._worker_done:
            self.after(150, self._poll_worker)
            return

        err = self._worker_err
        self._worker = None
        self._worker_done = False

        if err:
            self._log(f"Worker failed: {err}")
            messagebox.showerror("Operation failed", err)
        else:
            self._log("Worker finished successfully")
            self._render_rows(with_validation=True)
            self._validate(show_ok=True)

        self._refresh_buttons()

    def _validate(self, show_ok: bool = True) -> bool:
        if not self.state.rows:
            return False
        if not self.state.a_columns:
            messagebox.showwarning("Missing A", "Load A vector first.")
            return False

        n_err = 0
        n_warn = 0

        for r in self.state.rows:
            errs, warns = _validate_row(r, self.state.a_columns)
            if errs:
                n_err += 1
            if warns:
                n_warn += 1

        self._render_rows(with_validation=True)

        self._log(f"Validate: {len(self.state.rows)} rows, errors={n_err}, warnings={n_warn}")

        if n_err > 0:
            if show_ok:
                messagebox.showerror("Validation failed", f"{n_err} row(s) have errors. Fix them before export.")
            return False

        if show_ok:
            messagebox.showinfo("Validation OK", f"All good. Warnings: {n_warn}")
        return True

    def _export_bundle(self) -> None:
        if not self.state.rows:
            messagebox.showwarning("Nothing to export", "Harmonise criteria first.")
            return
        if not self._validate(show_ok=False):
            messagebox.showerror("Export blocked", "Fix validation errors before export.")
            return
        if not (self.state.a_path and self.state.a_columns):
            messagebox.showerror("Missing A", "Load the A vector CSV before export.")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"{BUNDLE_ROOT_NAME}_{ts}.zip"

        zip_path = filedialog.asksaveasfilename(
            title="Save Screen A bundle ZIP",
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[("ZIP", "*.zip")],
        )
        if not zip_path:
            return

        criteria_source_text = self.txt_criteria.get("1.0", "end").strip()

        try:
            with tempfile.TemporaryDirectory(prefix="screenA_bundle_") as tmp:
                root = Path(tmp) / BUNDLE_ROOT_NAME
                data_dir = root / "data"
                crit_dir = root / "criteria"
                data_dir.mkdir(parents=True, exist_ok=True)
                crit_dir.mkdir(parents=True, exist_ok=True)

                criteria_csv = crit_dir / "criteria_harmonized.csv"
                criteria_txt = crit_dir / "criteria_harmonized.txt"
                criteria_src = crit_dir / "criteria_source.txt"

                _export_csv(self.state.rows, str(criteria_csv))
                _export_pipe(self.state.rows, str(criteria_txt))
                criteria_src.write_text(criteria_source_text + "\n", encoding="utf-8")

                current_csv = data_dir / "current.csv"
                errors_csv = data_dir / "input_errors.csv"
                clean_stats = _clean_aggregate_csv(self.state.a_path, current_csv, errors_csv)

                wrote_errors = errors_csv.exists() and errors_csv.stat().st_size > 0
                if not wrote_errors:
                    try:
                        errors_csv.unlink(missing_ok=True)
                    except Exception:
                        if errors_csv.exists():
                            errors_csv.unlink()

                manifest = _build_manifest(
                    a_path=self.state.a_path,
                    a_columns=self.state.a_columns,
                    a_id_col_guess=self.state.a_id_col,
                    clean_stats=clean_stats,
                    criteria_path=self.state.criteria_path,
                    criteria_kind=self.state.criteria_kind,
                    criteria_rows=self.state.rows,
                    criteria_source_text=criteria_source_text,
                    wrote_input_errors=wrote_errors,
                )

                hashes = {
                    "data/current.csv": _sha256_file(current_csv),
                    "criteria/criteria_harmonized.csv": _sha256_file(criteria_csv),
                }
                if wrote_errors:
                    hashes["data/input_errors.csv"] = _sha256_file(errors_csv)
                manifest["sha256"] = hashes

                (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

                zip_out = Path(zip_path)
                zip_out.parent.mkdir(parents=True, exist_ok=True)

                with zipfile.ZipFile(zip_out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for p in root.rglob("*"):
                        if p.is_file():
                            arc = str(p.relative_to(Path(tmp)))  # includes root folder name
                            zf.write(p, arcname=arc)

            self._log(f"Bundle exported: {zip_path}")
            messagebox.showinfo("Export done", f"Exported bundle ZIP:\n{zip_path}")

        except Exception as e:
            messagebox.showerror("Export failed", str(e))
            self._log(f"Export failed: {e}")

    def _pick_targets(self) -> None:
        if not self.state.a_columns:
            messagebox.showwarning("Missing A", "Load A vector first.")
            return
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Pick targets", "Select one or more rows first.")
            return

        win = tk.Toplevel(self)
        win.title("Pick target columns")
        win.geometry("420x500")

        ttk.Label(win, text="Select one or more A columns (Ctrl/Shift):").pack(anchor="w", padx=10, pady=(10, 4))

        lb = tk.Listbox(win, selectmode="extended")
        lb.pack(fill="both", expand=True, padx=10, pady=6)

        for c in self.state.a_columns:
            lb.insert("end", c)

        btn_row = ttk.Frame(win)
        btn_row.pack(fill="x", padx=10, pady=10)

        def apply():
            picks = [lb.get(i) for i in lb.curselection()]
            if not picks:
                messagebox.showwarning("No selection", "Pick at least one column")
                return
            tgt = ",".join(picks)
            for it in sel:
                rid = self.tree.set(it, "id")
                r = self._find_row_by_id(rid)
                if r is not None:
                    r["target"], _ = _canonicalize_targets(tgt, self.state.a_columns)
            self._render_rows(with_validation=True)
            win.destroy()

        ttk.Button(btn_row, text="Apply", command=apply).pack(side="left")
        ttk.Button(btn_row, text="Cancel", command=win.destroy).pack(side="right")

    def _clear_table(self) -> None:
        for it in self.tree.get_children():
            self.tree.delete(it)

    def _find_row_by_id(self, rid: str) -> Optional[Dict[str, Any]]:
        rid = rid.strip()
        for r in self.state.rows:
            if _safe_str(r.get("id")).strip() == rid:
                return r
        return None

    def _render_rows(self, with_validation: bool = False) -> None:
        self._clear_table()
        if not self.state.rows:
            self._refresh_buttons()
            return

        for r in self.state.rows:
            st = _safe_str(r.get("stage")).upper()
            if st in {"EH", "IH"}:
                r["threshold"] = ""
            else:
                if not _safe_str(r.get("threshold")).strip():
                    r["threshold"] = f"{DEFAULT_THRESHOLD:.2f}"

        for r in self.state.rows:
            vals = (
                r.get("stage", ""),
                r.get("id", ""),
                r.get("type", ""),
                _safe_str(r.get("label", ""))[:200],
                r.get("operator", ""),
                r.get("target", ""),
                _what_to_export(r.get("operator", ""), r.get("what", []) or [])[:260],
                r.get("threshold", ""),
                "1" if bool(r.get("enabled", True)) else "0",
            )

            tags = ()
            if with_validation and self.state.a_columns:
                errs, warns = _validate_row(r, self.state.a_columns)
                if errs:
                    tags = ("error",)
                elif warns:
                    tags = ("warn",)

            self.tree.insert("", "end", values=vals, tags=tags)

        self._refresh_buttons()

    def _destroy_editor(self) -> None:
        try:
            if self._edit_widget is not None:
                self._edit_widget.destroy()
        except Exception:
            pass
        finally:
            self._edit_widget = None

    def _on_double_click(self, event) -> None:
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not item or not col:
            return

        col_index = int(col.replace("#", "")) - 1
        columns = list(self.tree["columns"])
        if col_index < 0 or col_index >= len(columns):
            return

        col_name = columns[col_index]
        if col_name not in {"stage", "label", "operator", "target", "what", "threshold", "enabled"}:
            return

        if col_name == "enabled":
            rid = self.tree.set(item, "id")
            r = self._find_row_by_id(rid)
            if r is not None:
                r["enabled"] = not bool(r.get("enabled", True))
                self._render_rows(with_validation=True)
            return

        self._destroy_editor()

        bbox = self.tree.bbox(item, col)
        if not bbox:
            return
        x, y, w, h = bbox

        rid = self.tree.set(item, "id")
        row = self._find_row_by_id(rid)
        if row is None:
            return

        if col_name == "threshold":
            st = _safe_str(row.get("stage")).upper()
            if st not in {"EL", "IL"}:
                return

        value = self.tree.set(item, col_name)

        if col_name == "stage":
            cb = ttk.Combobox(self.tree, values=list(STAGES), state="readonly")
            cb.set(value or "")
            cb.place(x=x, y=y, width=w, height=h)
            cb.focus_set()

            def save(_=None):
                v = cb.get().strip().upper()
                if v in STAGES:
                    row["stage"] = v
                    if v in {"EH", "IH"}:
                        row["threshold"] = ""
                    else:
                        if not _safe_str(row.get("threshold")).strip():
                            row["threshold"] = f"{DEFAULT_THRESHOLD:.2f}"
                self._destroy_editor()
                self._render_rows(with_validation=True)

            cb.bind("<<ComboboxSelected>>", save)
            cb.bind("<Return>", save)
            cb.bind("<Escape>", lambda _=None: self._destroy_editor())

            self._edit_widget = cb
            return

        if col_name == "operator":
            cb = ttk.Combobox(self.tree, values=list(OPERATORS), state="readonly")
            cb.set(value or "")
            cb.place(x=x, y=y, width=w, height=h)
            cb.focus_set()

            def save(_=None):
                v = cb.get().strip().lower()
                if v in OPERATORS:
                    row["operator"] = v
                    if v == "llm":
                        what_list = row.get("what") or []
                        if isinstance(what_list, list):
                            if len(what_list) != 1:
                                seed = (_safe_str(row.get("label")) or _safe_str(row.get("source_text")) or "").strip()
                                row["what"] = [seed] if seed else [""]
                        else:
                            row["what"] = [str(what_list).strip()]
                self._destroy_editor()
                self._render_rows(with_validation=True)

            cb.bind("<<ComboboxSelected>>", save)
            cb.bind("<Return>", save)
            cb.bind("<Escape>", lambda _=None: self._destroy_editor())

            self._edit_widget = cb
            return

        ent = ttk.Entry(self.tree)
        ent.insert(0, value)
        ent.place(x=x, y=y, width=w, height=h)
        ent.focus_set()

        def save(_=None):
            v = ent.get().strip()
            if col_name == "label":
                row["label"] = v
            elif col_name == "target":
                canon, _unk = _canonicalize_targets(v, self.state.a_columns)
                row["target"] = canon
            elif col_name == "what":
                row["what"] = _parse_what_cell(row.get("operator", "contains"), v)
            elif col_name == "threshold":
                row["threshold"] = v
            self._destroy_editor()
            self._render_rows(with_validation=True)

        ent.bind("<Return>", save)
        ent.bind("<Escape>", lambda _=None: self._destroy_editor())
        ent.bind("<FocusOut>", save)

        self._edit_widget = ent


# ============================
# Hub plugin wrapper
# ============================

def create_plugin(app):
    return HarmoniserPlugin(app, PluginMeta(id="harmoniser", title="Harmoniser (Criteria)"))


class HarmoniserPlugin(BasePlugin):
    def __init__(self, app, meta: PluginMeta):
        super().__init__(app, meta)
        self.view: Optional[HarmoniserView] = None

    def build_tab(self, parent):
        frame = ttk.Frame(parent)
        self.view = HarmoniserView(frame)
        self.view.pack(fill="both", expand=True)
        return frame

    def on_close(self):
        try:
            if self.view:
                self.view.destroy()
        except Exception:
            pass
        self.view = None
