# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
plugins/_common/widgets.py — shared Tk widgets for EH/IH/EL/IL plugins.

Owns:
  - DataTable: a virtualised ttk.Treeview-based row viewer with
    incremental population, column-header sorting, and a
    double-click-to-activate row callback. Used by every screen tab
    that displays the FULL/SURVIVORS row sets.

Body is byte-identical to the prior plugins/04_eh/plugin.py and
plugins/05_ih/plugin.py copies (zero diff between them).

Consumed by:
  - plugins/04_eh/plugin.py  (EHView holds two DataTable instances)
  - plugins/05_ih/plugin.py  (IHView holds two DataTable instances)

When EL and IL undergo their own decomposition, they will import the
same DataTable rather than carrying private copies.
"""
import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional, Sequence

from plugins._common.parser import _safe_str


# Number of rows the DataTable renders per Treeview-insert batch. Tuned to
# keep the UI responsive on large corpora (the deterministic stages routinely
# show 2k+ rows). Was duplicated in plugins/04_eh/plugin.py and 05_ih/plugin.py.
RENDER_CHUNK = 300


class Tooltip:
    """A hover label for one widget.

    Added in wave 11 session C because D6 asks for a *reason* beside a
    number, and there was no tooltip anywhere in this repository to reuse.

    It holds no logic: the text is decided by
    ``plugins/_common/stage_state.py`` and handed in, so the wording is
    testable without a display. This class only shows it — which is the
    same division the Views follow, and the reason the decisions in
    ``stage_state`` can be asserted at all.
    """

    #: Long enough not to fire while the pointer crosses the widget on its
    #: way somewhere else; short enough that hovering to read it works.
    DELAY_MS = 450

    def __init__(self, widget, text: str, *, wraplength: int = 380):
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self._after_id = None
        self._window = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def set_text(self, text: str) -> None:
        """Replace the wording, e.g. after the provider changed."""
        self.text = text
        if self._window is not None:
            self._hide()

    def _schedule(self, _evt=None):
        self._cancel()
        self._after_id = self.widget.after(self.DELAY_MS, self._show)

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._window is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        except Exception:
            return
        win = tk.Toplevel(self.widget)
        win.wm_overrideredirect(True)
        win.wm_geometry(f"+{x}+{y}")
        tk.Label(win, text=self.text, justify="left",
                 wraplength=self.wraplength, relief="solid", borderwidth=1,
                 background="#ffffe0", padx=6, pady=4).pack()
        self._window = win

    def _hide(self, _evt=None):
        self._cancel()
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None


class DataTable(ttk.Frame):
    """
    Treeview wrapper with:
    - column setup
    - click-to-sort (requests sort callback)
    - incremental rendering to keep UI responsive
    - double-click callback to open details
    """
    def __init__(self, parent, on_sort: Callable[[str], None], on_row_activate: Optional[Callable[[Dict[str, str]], None]] = None):
        super().__init__(parent)
        self.on_sort = on_sort
        self.on_row_activate = on_row_activate

        self.tree = ttk.Treeview(self, show="headings", selectmode="browse")
        self.vs = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.hs = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=self.vs.set, xscrollcommand=self.hs.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        self.vs.grid(row=0, column=1, sticky="ns")
        self.hs.grid(row=1, column=0, sticky="ew")

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.columns: List[str] = []
        self._render_token = 0
        self._iid_to_row: Dict[str, Dict[str, str]] = {}

        self.tree.bind("<Double-1>", self._on_double_click)

    def set_columns(self, cols: List[str]):
        self.columns = cols
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = cols
        for c in cols:
            self.tree.heading(c, text=c, command=lambda col=c: self.on_sort(col))
            self.tree.column(c, width=140, minwidth=90, stretch=False)

    def clear(self):
        self._render_token += 1
        self._iid_to_row.clear()
        self.tree.delete(*self.tree.get_children())

    def render_rows_incremental(self, rows: List[Dict[str, str]]):
        self.clear()
        token = self._render_token

        def _insert_chunk(start: int):
            if token != self._render_token:
                return
            end = min(start + RENDER_CHUNK, len(rows))
            for i in range(start, end):
                r = rows[i]
                iid = f"r{i}"
                self._iid_to_row[iid] = r
                vals = [_safe_str(r.get(c, "")) for c in self.columns]
                self.tree.insert("", "end", iid=iid, values=vals)
            if end < len(rows):
                self.after(1, lambda: _insert_chunk(end))

        self.after(0, lambda: _insert_chunk(0))

    def _on_double_click(self, _evt):
        if not self.on_row_activate:
            return
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        r = self._iid_to_row.get(iid)
        if r:
            self.on_row_activate(r)
