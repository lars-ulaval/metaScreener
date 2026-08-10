# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""The provider choice — F-91, D1, D3, D4, D7.

Replaces the API-key modal, which had two defects beyond its subject: it
could only ask about OpenAI, and declining it destroyed the application.

**This dialog can never prevent the application from running.** It is
opened after the notebook and every plugin already exist, and dismissing
it writes nothing — which leaves the store ``UNCONFIGURED`` rather than
letting a provider be acquired by fiat. That is the safety property D1's
restatement turns on: ``key_required("local")`` is ``False``, so a
provider must never become effective without an explicit choice.

What it shows
-------------
Local is the **lit** option (D1) — lit, not selected-by-default-in-the-
store; those are different, and conflating them is what made a fresh
install billable in session A. OpenAI is one click away. An advanced
custom-endpoint field covers LM Studio, llama.cpp and vLLM at once,
because they speak the same wire protocol, so a URL field reaches all
three with no new code and no new provider member.

Each provider carries the detection state from
``plugins/_common/provider_detect.py``, whose three failure messages are
deliberately distinct: *not installed*, *installed but not running*, and
*running with nothing pulled* are three problems with three different
fixes (D4, D5).

Nothing here starts a server. D5 is explicit: detect, give the command,
do not run it.
"""
import threading
import tkinter as tk
from tkinter import ttk

from plugins._common import model_pull as mp
from plugins._common import provider_detect as pd
from plugins._common.settings import (
    DEFAULT_LOCAL_ENDPOINT,
    DEFAULT_OPENAI_ENDPOINT,
    UNCHOSEN,
)


class ProviderDialog(tk.Toplevel):
    """Modal provider chooser. Sets ``self.result`` to a settings dict, or
    leaves it ``None`` when dismissed."""

    def __init__(self, parent, *, settings=None, status=None):
        super().__init__(parent)
        self.title("Choose a model provider")
        self.resizable(False, False)
        self.transient(parent)
        self.result = None

        cfg = dict(settings or {})
        self._status = status

        # D7: open on the remembered choice; otherwise on local, which is
        # the lit option rather than a stored one.
        remembered = (cfg.get("provider") or "").strip()
        self.var_provider = tk.StringVar(value=remembered or "local")
        self.var_endpoint = tk.StringVar(
            value=(cfg.get("endpoint") or "").strip() or DEFAULT_LOCAL_ENDPOINT)
        self.var_key = tk.StringVar(value=(cfg.get("api_key") or "").strip())
        self.var_model = tk.StringVar(value=(cfg.get("model") or "").strip())

        self._build()
        self._on_provider_changed()
        self.after(50, self._probe)

        self.protocol("WM_DELETE_WINDOW", self._dismiss)
        self.grab_set()

    # -- construction ------------------------------------------------------

    def _build(self):
        pad = {"padx": 10, "pady": 4}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True)

        ttk.Label(
            frm,
            text="metaScreener can screen with a model on this computer, or "
                 "with a hosted provider.",
            wraplength=520, justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", **pad)

        for row, (value, label) in enumerate((
                ("local", "On this computer (Ollama) — no API key, no cost"),
                ("openai", "OpenAI — needs an API key, billed per record"),
                ("custom", "Another OpenAI-compatible server (advanced)")),
                start=1):
            ttk.Radiobutton(frm, text=label, value=value,
                            variable=self.var_provider,
                            command=self._on_provider_changed
                            ).grid(row=row, column=0, columnspan=3,
                                   sticky="w", **pad)

        self.lbl_status = ttk.Label(frm, text="Checking…", wraplength=520,
                                    justify="left", foreground="#555")
        self.lbl_status.grid(row=4, column=0, columnspan=3, sticky="w", **pad)

        ttk.Label(frm, text="Endpoint").grid(row=5, column=0, sticky="w", **pad)
        self.ent_endpoint = ttk.Entry(frm, textvariable=self.var_endpoint,
                                      width=46)
        self.ent_endpoint.grid(row=5, column=1, columnspan=2, sticky="we", **pad)

        ttk.Label(frm, text="API key").grid(row=6, column=0, sticky="w", **pad)
        self.ent_key = ttk.Entry(frm, textvariable=self.var_key, width=46,
                                 show="•")
        self.ent_key.grid(row=6, column=1, columnspan=2, sticky="we", **pad)

        ttk.Label(frm, text="Model").grid(row=7, column=0, sticky="w", **pad)
        self.ent_model = ttk.Entry(frm, textvariable=self.var_model, width=46)
        self.ent_model.grid(row=7, column=1, columnspan=2, sticky="we", **pad)

        self.btn_pull = ttk.Button(frm, text="Download a model…",
                                   command=self._offer_pull)
        self.btn_pull.grid(row=4, column=2, sticky="e", **pad)
        self.btn_pull.grid_remove()

        actions = ttk.Frame(frm)
        actions.grid(row=8, column=0, columnspan=3, sticky="e", **pad)
        ttk.Button(actions, text="Not now", command=self._dismiss
                   ).pack(side="left", padx=4)
        self.btn_ok = ttk.Button(actions, text="Use this provider",
                                 command=self._accept)
        self.btn_ok.pack(side="left", padx=4)

        ttk.Label(
            frm,
            text="You can change this later, and the deterministic stages "
                 "(03–05) work without any model.",
            wraplength=520, justify="left", foreground="#555",
        ).grid(row=9, column=0, columnspan=3, sticky="w", **pad)

    # -- behaviour ---------------------------------------------------------

    def _on_provider_changed(self):
        provider = self.var_provider.get()
        if provider == "openai":
            self.var_endpoint.set(DEFAULT_OPENAI_ENDPOINT)
            self.ent_endpoint.state(["disabled"])
            self.ent_key.state(["!disabled"])
        elif provider == "local":
            if not self.var_endpoint.get().strip() or \
                    self.var_endpoint.get() == DEFAULT_OPENAI_ENDPOINT:
                self.var_endpoint.set(DEFAULT_LOCAL_ENDPOINT)
            self.ent_endpoint.state(["!disabled"])
            self.ent_key.state(["disabled"])     # a local server needs none
        else:
            self.ent_endpoint.state(["!disabled"])
            self.ent_key.state(["!disabled"])
        self._probe()

    def _probe(self):
        """Detect on a worker thread; never on the GUI thread."""
        endpoint = self.var_endpoint.get().strip()
        self.lbl_status.configure(text="Checking…")

        def _work():
            found = pd.detect(endpoint)
            self.after(0, lambda: self._status_arrived(found))

        threading.Thread(target=_work, daemon=True).start()

    def _status_arrived(self, found):
        self._status = found
        self.lbl_status.configure(text=found.detail or "Ready.")
        # D3: a server that is running with nothing pulled is the one state
        # where metaScreener can help directly. Offered, never automatic.
        self.btn_pull.grid_remove()
        if found.state == pd.NO_MODELS and mp.recommended_models():
            self.btn_pull.grid()

    def _offer_pull(self):
        """Offer, then pull — sized before a byte moves, and cancellable.

        The ceremony is deliberate. ``_run_clicked`` elsewhere in this
        application starts a *billable* operation with no estimate and no
        confirmation; adding a multi-gigabyte download with less ceremony
        than that deserves would repeat the mistake in a form the user
        cannot undo.
        """
        from tkinter import messagebox

        models = mp.recommended_models()
        if not models:
            return
        model = models[0]
        if not messagebox.askyesno("Download a model?",
                                   mp.offer_text(model), parent=self):
            return                      # refusable

        self._cancel = threading.Event()
        win = tk.Toplevel(self)
        win.title(f"Downloading {model.name}")
        win.transient(self)
        ttk.Label(win, text=f"{model.name} — about {model.human_size}",
                  padding=10).pack(anchor="w")
        bar = ttk.Progressbar(win, length=380, mode="determinate", maximum=1000)
        bar.pack(padx=10, pady=6)
        lbl = ttk.Label(win, text="Starting…", padding=(10, 0))
        lbl.pack(anchor="w")
        ttk.Button(win, text="Cancel",
                   command=self._cancel.set).pack(pady=8)
        win.protocol("WM_DELETE_WINDOW", self._cancel.set)

        def _progress(p):
            def _apply():
                if not win.winfo_exists():
                    return
                bar["value"] = int(p.fraction * 1000)
                shown = f"{p.status} — {p.fraction * 100:.0f}%" if p.total \
                    else p.status
                lbl.configure(text=shown)
            self.after(0, _apply)

        def _work():
            result = mp.pull(self.var_endpoint.get().strip(), model.name,
                             on_progress=_progress, cancel=self._cancel)
            self.after(0, lambda: self._pull_finished(win, model, result))

        threading.Thread(target=_work, daemon=True).start()

    def _pull_finished(self, win, model, result):
        from tkinter import messagebox

        try:
            win.destroy()
        except Exception:
            pass
        if result.cancelled:
            self.lbl_status.configure(text="Download cancelled. Nothing kept.")
        elif result.ok:
            self.var_model.set(model.name)
            self._probe()
        else:
            messagebox.showwarning("Download failed", result.error,
                                   parent=self)
        self._probe()

    def _accept(self):
        provider = self.var_provider.get()
        self.result = {
            "provider": provider,
            "endpoint": self.var_endpoint.get().strip(),
            "api_key": self.var_key.get().strip(),
            "model": self.var_model.get().strip(),
        }
        self.destroy()

    def _dismiss(self):
        """Write nothing. The store stays UNCONFIGURED and the LLM stages
        report why they cannot run — which is a working application, not a
        refusal to start."""
        self.result = None
        self.destroy()
