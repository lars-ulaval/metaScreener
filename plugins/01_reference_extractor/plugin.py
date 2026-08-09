# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

TAB_TITLE = "Reference Markers (experimental)"

import tkinter as tk
from tkinter import ttk
import tkinter.messagebox as messagebox
from metascreener.plugin_api import PluginMeta, BasePlugin


def make_plugin(app):
    """Factory the plugin manager looks for (metascreener/main.py:157)."""
    meta = PluginMeta(
        id="reference_extractor_v3_1",
        title="Reference Markers v3.1 (experimental)",
    )
    return ReferenceExtractorEmbedded(app, meta)


class ReferenceExtractorEmbedded(BasePlugin):
    def build_tab(self, parent):
        """Build the experimental reference-marker extractor tab.

        Scope: this plugin extracts visually-present reference markers
        (numbered citations like "[1]" or author-year citations like
        "[Smith 2022]") from images supplied as PDFs or PNGs. It does
        NOT parse standard PRISMA flow diagrams, which typically do not
        contain reference markers; feeding one as input may produce
        hallucinated output. All results require human verification
        before downstream use.
        """
        f = ttk.Frame(parent)
        try:
            # The inner module must expose a Frame class named PrismaAIV3View.
            from .original import prisma_citations_ai_v3_1 as mod
            self.view = mod.PrismaAIV3View(f)   # master=hub frame

            # Experimental scope warning, packed before the embedded view
            # so it appears at the top of the tab.
            warning = tk.Label(
                f,
                text=(
                    "\u26A0 Experimental: extracts visually-present reference "
                    "markers from images.\n"
                    "Does not parse standard PRISMA flow diagrams. "
                    "Verify all output."
                ),
                background="#FFF3CD",
                foreground="#856404",
                font=("TkDefaultFont", 9, "bold"),
                padx=8, pady=6,
                anchor="w", justify="left",
            )
            warning.pack(side="top", fill="x")
            self.view.pack(fill="both", expand=True)
        except Exception as e:
            msg = f"Could not integrate tool: {e}"
            ttk.Label(f, text=msg).pack(padx=12, pady=12, anchor="w")
        return f
