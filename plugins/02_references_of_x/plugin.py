# -*- coding: utf-8 -*-
"""
plugin.py — Hub plugin wrapper for "References-of-X — AI v1"

Responsibilities:
- Mount the Tk/ttk view (ReferencesOfXView) inside a Hub tab.
- Forward lifecycle events (unload, hide/show) to the view so it can
  stop/cancel or pause/resume long-running tasks (resolve/fetch modals).
- Keep this file thin; all UI/logic lives in ui.py / services.py.

Notes:
- The modals themselves are created/managed inside ReferencesOfXView.
- We just ensure cooperative shutdown (on_unload) and optional pause/resume
  when the tab visibility changes (on_hide/on_show), if available.
"""

TAB_TITLE = "References-of-X — AI v1"

from typing import Optional
from tkinter import ttk
from prisma_hub.plugin_api import PluginMeta, BasePlugin

from .ui import ReferencesOfXView  # type: ignore

def create_plugin(app):
    """Factory expected by the Hub."""
    return RefXPlugin(app, PluginMeta(id="refx", title="References of X"))


class RefXPlugin(BasePlugin):
    def __init__(self, app, meta: PluginMeta):
        super().__init__(app, meta)
        self._frame: Optional[ttk.Frame] = None
        self.view: Optional[ReferencesOfXView] = None

    # ------------------------------------------------------------------
    # Required: build the tab content
    # ------------------------------------------------------------------
    def build_tab(self, parent):
        frame = ttk.Frame(parent, padding=0)
        self.view = ReferencesOfXView(frame)  # your full UI (with modals)
        self.view.pack(fill="both", expand=True)
        self._frame = frame
        return frame

    # ------------------------------------------------------------------
    # Lifecycle hooks (called by the Hub when available)
    # ------------------------------------------------------------------
    def on_unload(self):
        """
        Called when the tab is being destroyed/unmounted.
        Ensure long-running jobs are cancelled and resources released.
        """
        try:
            if self.view:
                # Cooperatively cancel any running worker (resolve/fetch)
                # and let the view close any open modal if needed.
                if hasattr(self.view, "on_stop"):
                    self.view.on_stop()
        except Exception:
            pass
        finally:
            # Null references to help GC
            self.view = None
            self._frame = None

    def on_hide(self):
        """
        Optional: Tab went off-screen (e.g., user switched tabs).
        If your view offers pause/resume, pause to be nice with resources.
        """
        try:
            if self.view and hasattr(self.view, "request_pause"):
                # Non-fatal if not implemented
                self.view.request_pause()
        except Exception:
            pass

    def on_show(self):
        """
        Optional: Tab is visible again. Resume if it was paused.
        """
        try:
            if self.view and hasattr(self.view, "request_resume"):
                self.view.request_resume()
        except Exception:
            pass


