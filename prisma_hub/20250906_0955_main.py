import tkinter as tk
from tkinter import ttk
from .plugin_manager import discover

class PrismaHubApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PRISMA Hub")
        self.geometry("1200x820")
        self.minsize(1020, 720)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self._plugins = []
        self._load_plugins()

        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_plugins(self):
        for plugin in discover(self):
            frame = plugin.build_tab(self.nb)
            self.nb.add(frame, text=plugin.meta.title)
            self._plugins.append((plugin, frame))

    def _on_tab_changed(self, _evt):
        idx = self.nb.index("current")
        if 0 <= idx < len(self._plugins):
            self._plugins[idx][0].on_select()

    def _on_close(self):
        for plugin, _frame in self._plugins:
            try:
                plugin.on_close()
            except Exception:
                pass
        self.destroy()
