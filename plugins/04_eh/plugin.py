# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""plugin.py - Plugin 04 EH (Screen A): thin shim entry point.

After Conv 5's decomposition the EH plugin is split into:
  - plugins/_common/{parser,evaluator,exporters,bundle,runner,widgets}.py
    (logic shared with IH; will also be shared with EL/IL once those
    plugins undergo their own decomposition)
  - plugins/04_eh/ui.py (the EH View — Tkinter UI code and the
    stage-curried wrappers it calls into)

This module wires the metaScreener plugin manager to EHView and
re-exports a small set of engine symbols that the EH/IH regression
and import tests reach via this plugin module's attribute namespace.
See the submodules for the substantive code.
"""

from typing import Optional
import tkinter as tk
from tkinter import ttk

from metascreener.plugin_api import BasePlugin, PluginMeta

# Re-exports for test compatibility. Tests reach these via mod.<name>
# (where mod is this module's namespace). Do not drop without updating
# the corresponding test.
from plugins._common.parser import (
    Criterion,
    ParseReport,
    CriteriaLoadReport,
    _parse_csv_tolerant_text,
)
from plugins._common.evaluator import _eval_criterion
from plugins._common.exporters import _write_csv_bytes

from .ui import (
    TAB_TITLE,
    EHView,
    _load_criteria_eh_from_text,
    run_eh_screen,
)


class Plugin(BasePlugin):
    def __init__(self, app=None, meta: Optional[PluginMeta] = None):
        if meta is None:
            meta = PluginMeta(id="screen_a_eh", title=TAB_TITLE, version="2.2.1")
        super().__init__(app, meta)
        self.view: Optional[EHView] = None

    def build_tab(self, parent: ttk.Notebook) -> tk.Frame:
        frame = ttk.Frame(parent)
        self.view = EHView(frame)
        self.view.pack(fill="both", expand=True)
        return frame

    def on_close(self):
        try:
            if self.view:
                self.view.destroy()
        except Exception:
            pass
        self.view = None
