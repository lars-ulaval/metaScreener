from dataclasses import dataclass
from typing import Optional
import tkinter as tk
from tkinter import ttk

@dataclass
class PluginMeta:
    id: str
    title: str
    version: str = "0.1.0"

class BasePlugin:
    def __init__(self, app, meta: PluginMeta):
        self.app = app       # reference to hub app (Tk)
        self.meta = meta

    def build_tab(self, parent: ttk.Notebook) -> tk.Frame:
        """Return a Frame to mount as a tab in the hub."""
        raise NotImplementedError

    def on_select(self):
        """Called when the tab becomes active."""
        pass

    def on_close(self):
        """Called when the hub is closing."""
        pass
