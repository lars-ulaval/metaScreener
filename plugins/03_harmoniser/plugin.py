# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""plugin.py - Plugin 03 Harmoniser: thin shim entry point.

After Conv 4's decomposition the harmoniser is split into focused modules:
  - parser, inference, llm_refine, exporters, bundle (logic)
  - ui (Tkinter view code)

This module wires the metaScreener plugin manager to the View and re-exports
private engine symbols for tests that reach them via the plugin module
attribute. See the individual submodules for the substantive code.
"""

TAB_TITLE = "Harmoniser — Criteria"

from typing import Optional
from tkinter import ttk

from metascreener.plugin_api import PluginMeta, BasePlugin

# Re-exports for test compatibility. Existing tests reach these via
# `mod.<name>` (where `mod` is this module's namespace). Do not drop
# without updating the corresponding test.
from .parser import (
    _parse_free_text_criteria,
    _load_a_header_and_stats,
    _get_best_text_targets,
    _canonicalize_targets,
)
from .inference import DEFAULT_THRESHOLD, _infer_criterion_details
from .exporters import _export_csv
from .ui import HarmoniserView


def make_plugin(app):
    """Factory the plugin manager looks for (metascreener/main.py:157)."""
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

    def on_provider_changed(self):
        """Relay the application's provider news to the View.

        ``main.py`` notifies this name on the *plugin*, and until session
        C nothing implemented it anywhere, so the call reached nothing.
        This stage needs it as much as EL and IL do: its LLM button is
        gated on the same readiness, so a provider change it never hears
        about leaves the button reporting the previous answer.
        """
        try:
            if self.view:
                self.view.on_provider_changed()
        except Exception as e:                      # pragma: no cover - GUI
            print(f"[PLUGIN] Harmoniser on_provider_changed failed: {e}")

    def on_close(self):
        try:
            if self.view:
                self.view.destroy()
        except Exception:
            pass
        self.view = None
