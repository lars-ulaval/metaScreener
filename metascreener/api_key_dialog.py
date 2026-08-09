# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
Created on Sat Sep  6 09:51:50 2025

@author: alere
"""

import tkinter as tk
from tkinter import ttk


# --------------------------------------------------------------------------
# Acceptance rules (pure, no Tk - unit-tested in tests/test_api_key_validation.py)
# --------------------------------------------------------------------------

LOCAL_PROVIDER_HINT = (
    "This does not look like an OpenAI key. It will be used as entered - "
    "correct if you have set OPENAI_BASE_URL to a local or third-party "
    "endpoint (Ollama, llama.cpp, vLLM, DeepSeek)."
)


def sanitize_api_key(s):
    """Trim whitespace/newlines and one layer of surrounding quotes."""
    return (s or "").strip().strip('"').strip("'")


def looks_like_openai_key(key: str) -> bool:
    """True for a key shaped like OpenAI's own. Advisory only."""
    key = key or ""
    return key.startswith("sk-") and len(key) >= 20


def validate_api_key(key):
    """Decide whether `key` may be used, and what to tell the user.

    Returns (accepted, message). The only rejection is an empty value:
    metaScreener targets any OpenAI-compatible endpoint, and local servers
    (Ollama, llama.cpp, vLLM) require the variable to be set but ignore its
    value, so placeholders like "ollama" are legitimate. A key that does not
    look like OpenAI's is accepted with an advisory message rather than
    refused - that refusal made the entire documented local-provider
    workflow unreachable through the GUI.
    """
    key = sanitize_api_key(key)
    if not key:
        return False, "Please enter a key."
    if not looks_like_openai_key(key):
        return True, LOCAL_PROVIDER_HINT
    return True, ""


class ApiKeyDialog(tk.Toplevel):
    """
    Modal dialog that asks for OPENAI_API_KEY.
    - Paste from clipboard
    - Show/hide toggle
    - Basic format validation (starts with 'sk-', length >= 20)
    If user cancels/closes, `value` stays None.
    """
    def __init__(self, master, existing_key: str = "", remember_default: bool = True):
        super().__init__(master)
        self.title("OpenAI API Key")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()  # modal

        self.value = None
        self.remember_var = tk.BooleanVar(value=remember_default)
        self.show_var = tk.BooleanVar(value=False)
        self.msg_var = tk.StringVar(value="")

        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)

        ttk.Label(frm, text="Enter your OpenAI API key:", font=("Segoe UI", 10, "bold"))\
            .grid(row=0, column=0, sticky="w")

        row1 = ttk.Frame(frm)
        row1.grid(row=1, column=0, sticky="we", pady=(6, 0))
        row1.columnconfigure(0, weight=1)

        self.entry = ttk.Entry(row1, width=56, show="*")
        self.entry.grid(row=0, column=0, sticky="we")
        if existing_key:
            self.entry.insert(0, existing_key)

        ttk.Button(row1, text="Paste", command=self._on_paste)\
            .grid(row=0, column=1, padx=(8, 0))
        ttk.Checkbutton(row1, text="Show", variable=self.show_var, command=self._toggle_show)\
            .grid(row=0, column=2, padx=(8, 0))

        ttk.Checkbutton(frm,
                        text="Remember on this device (.env in project folder)",
                        variable=self.remember_var)\
            .grid(row=2, column=0, sticky="w", pady=(10, 0))

        ttk.Label(
            frm,
            text=("Using a local or third-party endpoint? Set OPENAI_BASE_URL and enter\n"
                  "any non-empty placeholder here (e.g. \"ollama\") - most local servers\n"
                  "require the variable to be set but ignore its value."),
            foreground="#555555",
            justify="left",
        ).grid(row=3, column=0, sticky="w", pady=(8, 0))

        # validation message: red when the key is refused, grey when advisory
        self.msg_label = tk.Label(frm, textvariable=self.msg_var, fg="red",
                                  wraplength=460, justify="left")
        self.msg_label.grid(row=4, column=0, sticky="w", pady=(6, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, sticky="e", pady=(16, 0))
        ttk.Button(btns, text="Cancel", command=self._on_cancel).pack(side="right")
        ttk.Button(btns, text="Save", command=self._on_save).pack(side="right", padx=(0, 8))

        # UX niceties
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.entry.focus()
        self.bind("<Return>", lambda e: self._on_save())
        self.bind("<Escape>", lambda e: self._on_cancel())

        self._center_on(master)

    # ---------------- helpers ----------------

    def _center_on(self, parent):
        self.update_idletasks()
        if parent is None:
            self.geometry("+400+300")
            return
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self.geometry(f"+{max(0,x)}+{max(0,y)}")

    def _toggle_show(self):
        self.entry.configure(show="" if self.show_var.get() else "*")

    def _on_paste(self):
        try:
            txt = self.clipboard_get()
        except Exception:
            txt = ""
        txt = self._sanitize(txt)
        if txt:
            self.entry.delete(0, "end")
            self.entry.insert(0, txt)
            self.msg_var.set("")  # clear any prior error

    def _sanitize(self, s: str) -> str:
        # trim spaces/newlines and surrounding quotes
        return sanitize_api_key(s)

    def _is_valid(self, key: str) -> bool:
        # Advisory only - see validate_api_key. Kept as a method because
        # it is part of this class's historical surface.
        return looks_like_openai_key(key)

    def _on_save(self):
        key = self._sanitize(self.entry.get())
        accepted, message = validate_api_key(key)
        if not accepted:
            self.msg_label.configure(fg="red")
            self.msg_var.set(message)
            return
        if message:
            # Advisory, not a refusal: show it and continue.
            self.msg_label.configure(fg="#555555")
            self.msg_var.set(message)
            self.update_idletasks()
        self.value = key
        self.destroy()

    def _on_cancel(self):
        self.value = None
        self.destroy()
