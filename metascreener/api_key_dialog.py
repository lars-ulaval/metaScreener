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


#: How many strip passes before giving up. Four covers every realistic
#: paste — a key wrapped in quotes that were themselves wrapped when the
#: value was copied out of a shell history or a JSON blob. The bound
#: exists so a pathological input cannot spin here; it is not reached by
#: anything a user can plausibly type.
_SANITIZE_PASSES = 4


def sanitize_api_key(s):
    """Trim whitespace/newlines and surrounding quotes, to a fixed point.

    **F-140. This used to be one pass, and it was not idempotent**, which
    is the whole of that finding. The order was strip-whitespace, then
    strip-quotes, and it never re-stripped — so a value that had
    whitespace *inside* its quotes came out still carrying it:

        '" x "'  ->  ' x '        one pass
        ' x '    ->  'x'          two passes

    ``ApiKeyDialog._on_save`` sanitized once and handed the result to
    ``validate_api_key``, which sanitized it **again** internally. So the
    accept/reject decision was taken on ``'x'`` while ``'  x '`` is what
    reached ``os.environ`` and the endpoint — the value checked was not
    the value used, on the axis this project keeps being bitten on. A
    padded key is refused with a 401, which surfaces as a terminal batch
    failure and a full corpus of manufactured non-answers (F-93),
    pointing the user at everything except the space.

    Iterating to a fixed point makes the function idempotent by
    construction, so sanitizing twice can no longer differ from
    sanitizing once. That is the belt; ``_on_save`` sanitizing exactly
    once is the braces, and the two are independent.

    Known limit, unchanged from the one-pass version: a key whose real
    value begins and ends with a quote character cannot be entered. No
    provider issues one, and the alternative — pasting quotes and having
    them kept — is the far commoner mistake.
    """
    out = (s or "")
    for _ in range(_SANITIZE_PASSES):
        nxt = out.strip().strip('"').strip("'").strip()
        if nxt == out:
            break
        out = nxt
    return out


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
        # F-140, the second of two independent guards. The RAW entry goes
        # to `validate_api_key`, which sanitizes it internally, and the
        # stored value is `sanitize_api_key` of that same raw string — so
        # the two are the same expression over the same input and cannot
        # differ, whether or not `sanitize_api_key` is idempotent. It is,
        # now, which is the first guard; this one does not depend on it.
        raw = self.entry.get()
        accepted, message = validate_api_key(raw)
        key = self._sanitize(raw)
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
