
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""plugin.py - Plugin 07 IL (Screen A): thin shim entry point.

After Conv 6 / Commit 6, this module is a thin shim that wires the
metaScreener plugin manager to ILView. The substantive code lives in:

  - plugins/07_il/prompt.py     (PROMPT_VERSION + prompt builder)
  - plugins/07_il/screen.py     (engine + dataclasses + IL helpers)
  - plugins/07_il/ui.py         (ILView + DataTable + final-report helpers)
  - plugins/07_il/standalone.py (StandaloneILPlugin shell)
  - plugins/_common/llm_client.py (LLM-side stage-agnostic helpers)

Re-exports below let existing consumers and tests reach
il.<Name> for any of these symbols through this module's namespace
without having to know which submodule they live in.

The IL-specific final-report constants (FINAL_REPORT_NAME,
FINAL_REPORT_REL, CONTRACT_STAGE_SHEET_COLS) are kept in this module
because ui.py's final-report aggregation helpers reach them via
``from .plugin import``; moving them to screen.py would force an
ui.py edit, which we deliberately avoid in this commit to keep the
diff scoped.
"""
import os
from typing import Optional

import tkinter as tk
from tkinter import ttk

from metascreener.plugin_api import BasePlugin, PluginMeta


# ------------------------------ constants -------------------------------------

TAB_TITLE = "Screen A — IL"
PLUGIN_ID = "screen_a_il"
PLUGIN_VERSION = "2.0.0"

DEFAULT_MODEL = os.environ.get("SCREENA_IL_MODEL", "gpt-4o-mini")
DEFAULT_TRUNC_CHARS = int(os.environ.get("SCREENA_IL_TRUNC_CHARS", "1500"))
DEFAULT_BATCH_SIZE = int(os.environ.get("SCREENA_IL_BATCH_SIZE", "50"))
DEFAULT_USE_CACHE = os.environ.get("SCREENA_IL_USE_CACHE", "1").strip() not in {"0", "false", "False", "no", "NO"}

RENDER_CHUNK = 400

IL_CACHE_REL = "cache/IL_cache.jsonl"
REPORTS_DIR_REL = "reports"
FINAL_REPORT_NAME = "ScreenA_Report.xlsx"
FINAL_REPORT_REL = f"{REPORTS_DIR_REL}/{FINAL_REPORT_NAME}"

# F-69: this header is the row builder's schema — the exact key set
# _extract_contract_stage_row returns (pinned by test_final_report.py). It
# used to be a seven-name list written against a different specification;
# only two names intersected the builder's keys, so five columns could
# never be populated and every stage-sheet data cell shipped blank.
# ``decided_at`` (no producer anywhere) and ``history`` (written as "" at
# every call site) are gone rather than fabricated.
CONTRACT_STAGE_SHEET_COLS = [
    "a_id", "stage", "stage_outcome", "passed_to_next",
    "failed_criteria_ids", "missing_criteria_ids", "uncertain_criteria_ids",
    "met_criteria_ids", "matched_evidence", "stage_reason_summary",
]


# ------------------------------ re-exports ------------------------------------
# All re-exports are needed by tests and/or UI consumers. The order matters
# because of circular imports between plugin.py / ui.py / standalone.py /
# screen.py: each later submodule's `from .plugin import (...)` sees only
# names defined above its `from .X import` line.

from .prompt import PROMPT_VERSION, _build_llm_messages_for_criterion

from .screen import (
    Criterion,
    ParseReport,
    CriteriaLoadReport,
    BundleInfo,
    OUTCOMES,
    _safe_str,
    _decode_bytes,
    _read_zip_bytes,
    _detect_bundle_root,
    _csv_read,
    _write_csv,
    _load_bundle,
    _parse_criteria_harmonized_csv,
    _cache_key,
    run_il_screen,
    _summarize_el_reason,
)

from plugins._common.llm_client import (
    _has_openai_key,
    _quote_in_text,
    _sha_text,
    _normalize_space,
    chunked,
    _parse_llm_json_array,
    _make_item_for_llm,
    _row_target_text_hash,
    _load_cache_from_jsonl,
    _dump_cache_to_jsonl,
    run_m1_llm_for_criterion,
)

from .ui import (
    DataTable,
    ILView,
    _build_final_report_xlsx_bytes,
    _compute_final_outcome,
    _export_il_xlsx,
    _extract_contract_stage_row,
    _find_bundle_member,
    _load_csv_rows_from_zip,
    _load_master_rows,
    _now_stamp,
    _stage_prefix,
)
from .standalone import StandaloneILPlugin


# ------------------------------ plugin wrapper --------------------------------

class Plugin(BasePlugin):
    def __init__(self, app=None, meta: Optional[PluginMeta] = None):
        if meta is None:
            meta = PluginMeta(id=PLUGIN_ID, title=TAB_TITLE, version=PLUGIN_VERSION)
        super().__init__(app, meta)
        self.view: Optional[ILView] = None

    def build_tab(self, parent: ttk.Notebook) -> tk.Frame:
        frame = ttk.Frame(parent)
        self.view = ILView(frame)
        self.view.pack(fill="both", expand=True)
        return frame

    def on_close(self):
        try:
            if self.view:
                self.view.destroy()
        except Exception:
            pass
        self.view = None
