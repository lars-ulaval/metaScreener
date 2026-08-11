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
import threading
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


class RecheckButton(ttk.Button):
    """A button that runs one slow thing off the GUI thread, then refreshes.

    F-149. The application probed the provider once, at launch, and never
    again: a server that went away and came back left every LLM tab
    reading "Unreachable" with its Run button dead until the whole
    application was restarted. A server restarting is ordinary — Ollama
    restarts, Windows sleeps, a laptop lid closes — so there has to be a
    way to ask again.

    Written once here rather than three times in the Views, for two
    reasons. The obvious one is F-14: EL, IL and the harmoniser would
    otherwise each carry a copy. The sharper one is that the risky part
    is not the button, it is **the thread and its teardown** — the class
    F-147 had just been fixed for in ``ProviderDialog``, where a worker
    outliving its widget wrote to a destroyed label. The Views carry no
    destroyed-widget guard anywhere, and ``Plugin.on_close`` destroys a
    View without stopping its workers, so putting a third unguarded
    background thread in three tabs would have re-opened that defect in
    triplicate. Here it is guarded in one place, and
    ``tests/test_view_smoke.py`` drives it against a real Tk.

    The three callbacks are split by **which thread they run on**, which
    is the whole reason this class exists:

    ``prepare``
        GUI thread, at click. Reads whatever widget state the work needs
        and returns a zero-argument callable that closes over it. This
        step is not ceremony: EL and IL resolve their endpoint from
        ``var_endpoint.get()``, a Tk call, and reading it on the worker
        would be the very violation the worker exists to avoid.
    the callable ``prepare`` returns
        worker thread. Must touch no widget.
    ``on_done``
        GUI thread, and only if the button is still alive.

    Deliberately **not** a repeating timer. ``provider_detect.forget()``
    with no argument clears the whole probe cache, so a poll would drop
    every tab to ``NOT_CHECKED`` — label "Checking…", Run disabled — on
    a heartbeat, which is a worse interface than the one being fixed. It
    would also probe a server the user is not asking about, on a machine
    that may be metered or asleep. This asks once, when asked to.
    """

    #: Rebound while a check is in flight, so a slow or unreachable
    #: endpoint looks like work rather than like a dead button. The probe
    #: carries its own timeout, so this state always ends.
    BUSY_TEXT = "Checking…"

    def __init__(self, parent, *, prepare: Callable[[], Callable[[], None]],
                 on_done: Callable[[], None], text: str = "Re-check",
                 **kw):
        super().__init__(parent, text=text, command=self._clicked, **kw)
        self._prepare = prepare
        self._on_done = on_done
        self._idle_text = text
        self._busy = False

    def _clicked(self):
        if self._busy:
            return                  # one probe in flight is enough
        job = self._prepare()       # GUI thread: read the widgets here
        self._busy = True
        self.configure(text=self.BUSY_TEXT, state="disabled")

        def _run():
            try:
                job()
            except Exception:
                # A probe that raises is a probe that found nothing, and
                # `provider_detect` already reports "nothing" as a state
                # the labels can render. Swallowed here so the button
                # cannot be left permanently disabled by an exception on
                # a daemon thread nobody is watching.
                pass
            self._post(self._finished)

        threading.Thread(target=_run, daemon=True).start()

    def _post(self, fn):
        """F-147's guard, in the one place this class needs it."""
        try:
            if self.winfo_exists():
                self.after(0, fn)
        except tk.TclError:
            pass                    # the tab closed while the probe ran

    def _finished(self):
        self._busy = False
        if not self.winfo_exists():
            return                  # destroyed between the post and here
        self.configure(text=self._idle_text, state="normal")
        self._on_done()


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
