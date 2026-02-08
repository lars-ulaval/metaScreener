# -*- coding: utf-8 -*-
"""
Created on Sat Sep  6 09:51:50 2025

@author: alere
"""

import os
import tkinter as tk
from tkinter import ttk

class ApiKeyDialog(tk.Toplevel):
    """
    Modal dialog that asks for OPENAI_API_KEY.
    If user closes or cancels, `value` stays None.
    If user clicks Save, `value` is the key string.
    If `remember_var` is true, caller can persist it (e.g., to .env).
    """
    def __init__(self, master, existing_key: str = "", remember_default: bool = True):
        super().__init__(master)
        self.title("OpenAI API Key")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()  # modal

        self.value = None
        self.remember_var = tk.BooleanVar(value=remember_default)

        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Enter your OpenAI API key:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.entry = ttk.Entry(frm, width=56, show="*")
        self.entry.grid(row=1, column=0, sticky="we", pady=(6, 0))
        self.entry.insert(0, existing_key or "")
        frm.columnconfigure(0, weight=1)

        ttk.Checkbutton(frm, text="Remember on this device (.env in project folder)", variable=self.remember_var)\
            .grid(row=2, column=0, sticky="w", pady=(10, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, sticky="e", pady=(16, 0))
        ttk.Button(btns, text="Cancel", command=self._on_cancel).pack(side="right")
        ttk.Button(btns, text="Save", command=self._on_save).pack(side="right", padx=(0, 8))

        # UX niceties
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.entry.focus()
        self.bind("<Return>", lambda e: self._on_save())
        self.bind("<Escape>", lambda e: self._on_cancel())

        self._center_on(master)

    def _center_on(self, parent):
        self.update_idletasks()
        if parent is None:
            self.geometry("+400+300")
            return
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        w = self.winfo_width()
        h = self.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self.geometry(f"+{max(0,x)}+{max(0,y)}")

    def _on_save(self):
        key = self.entry.get().strip()
        if key:
            self.value = key
            self.destroy()
        else:
            # simple inline feedback
            self.entry.configure(foreground="red")
            self.after(1200, lambda: self.entry.configure(foreground="black"))

    def _on_cancel(self):
        self.value = None
        self.destroy()
