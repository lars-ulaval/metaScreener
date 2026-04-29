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

from .llm_refine import (
    _llm_available,
    _llm_refine,
)

from .exporters import BUNDLE_ROOT_NAME, _export_csv
from .bundle import export_screen_a_bundle
from .ui import HarmoniserView


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
