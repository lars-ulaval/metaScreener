
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""plugin.py - Plugin 06 EL (Screen A): thin shim entry point.

After Conv 6 / Commit 5, this module is a thin shim that wires the
metaScreener plugin manager to ELView. The substantive code lives in:

  - plugins/06_el/prompt.py     (PROMPT_VERSION + prompt builder)
  - plugins/06_el/screen.py     (engine + dataclasses + EL helpers)
  - plugins/06_el/ui.py         (ELView + DataTable + UI helpers)
  - plugins/06_el/standalone.py (StandaloneELPlugin shell)
  - plugins/_common/llm_client.py (LLM-side stage-agnostic helpers)

Re-exports below let existing consumers and tests reach
el.<Name> for any of these symbols through this module's namespace
without having to know which submodule they live in.
"""
import os
from typing import Optional

import tkinter as tk
from tkinter import ttk

from metascreener.plugin_api import BasePlugin, PluginMeta


# ------------------------------ constants -------------------------------------

TAB_TITLE = "Screen A — EL"
PLUGIN_ID = "screen_a_el"
PLUGIN_VERSION = "2.0.0"

DEFAULT_MODEL = os.environ.get("SCREENA_EL_MODEL", "gpt-4o-mini")
DEFAULT_TRUNC_CHARS = int(os.environ.get("SCREENA_EL_TRUNC_CHARS", "1500"))
DEFAULT_BATCH_SIZE = int(os.environ.get("SCREENA_EL_BATCH_SIZE", "50"))
DEFAULT_USE_CACHE = os.environ.get("SCREENA_EL_USE_CACHE", "1").strip() not in {"0", "false", "False", "no", "NO"}

RENDER_CHUNK = 400

EL_CACHE_REL = "cache/EL_cache.jsonl"
REPORTS_DIR_REL = "reports"


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
    run_el_screen,
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
    ELView,
    _export_el_xlsx,
    _now_stamp,
)
from .standalone import StandaloneELPlugin


# ------------------------------ plugin wrapper --------------------------------

class Plugin(BasePlugin):
    def __init__(self, app=None, meta: Optional[PluginMeta] = None):
        if meta is None:
            meta = PluginMeta(id=PLUGIN_ID, title=TAB_TITLE, version=PLUGIN_VERSION)
        super().__init__(app, meta)
        self.view: Optional[ELView] = None

    def build_tab(self, parent: ttk.Notebook) -> tk.Frame:
        frame = ttk.Frame(parent)
        self.view = ELView(frame)
        self.view.pack(fill="both", expand=True)
        return frame

    def on_close(self):
        try:
            if self.view:
                self.view.destroy()
        except Exception:
            pass
        self.view = None
