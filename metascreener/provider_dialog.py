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
from plugins._common.stage_state import exclusion_allowed


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
        # F-145 is tri-state in the store: None means "follow the
        # provider". A checkbox has two states, so the box is seeded from
        # the RESOLVED answer and `_on_exclusion_toggled` records that the
        # user has now chosen. Seeding it from the raw setting would show
        # an unconfigured local install an unticked box that means the
        # same thing as the ticked box it would show OpenAI.
        self._exclusion_touched = isinstance(
            cfg.get("allow_llm_exclusion"), bool)
        self.var_allow_exclusion = tk.BooleanVar(
            value=exclusion_allowed(
                provider=remembered or "local",
                setting=cfg.get("allow_llm_exclusion")))

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

        ttk.Label(frm, text="Endpoint").grid(row=6, column=0, sticky="w", **pad)
        self.ent_endpoint = ttk.Entry(frm, textvariable=self.var_endpoint,
                                      width=46)
        self.ent_endpoint.grid(row=6, column=1, columnspan=2, sticky="we", **pad)

        ttk.Label(frm, text="API key").grid(row=7, column=0, sticky="w", **pad)
        self.ent_key = ttk.Entry(frm, textvariable=self.var_key, width=46,
                                 show="•")
        self.ent_key.grid(row=7, column=1, columnspan=2, sticky="we", **pad)

        ttk.Label(frm, text="Model").grid(row=8, column=0, sticky="w", **pad)
        self.ent_model = ttk.Entry(frm, textvariable=self.var_model, width=46)
        self.ent_model.grid(row=8, column=1, columnspan=2, sticky="we", **pad)

        # F-145's control, and F-153 is why it exists at all: the engine
        # logged "the provider dialog can permit exclusion" while no
        # widget anywhere could write the setting. A policy the user is
        # told is theirs and cannot reach is F-91's shape — the defect
        # where no control bound the endpoint.
        #
        # Here rather than in the stage tabs because the setting is
        # application-level and provider-shaped: this is the screen where
        # the provider is chosen, so it is the screen where "and may this
        # one exclude?" belongs.
        self.chk_exclude = ttk.Checkbutton(
            frm, text="Let the model exclude records, not just flag them",
            variable=self.var_allow_exclusion,
            command=self._on_exclusion_toggled)
        self.chk_exclude.grid(row=11, column=0, columnspan=3, sticky="w", **pad)

        # **The measurement, stated where the user changes it.** A
        # checkbox offering to turn off a safety gate without saying what
        # the gate is for is a checkbox that will be turned off.
        self.lbl_exclude = ttk.Label(
            frm, wraplength=520, justify="left", foreground="#555",
            text=("Measured on this project's own 85-record corpus: "
                  "gpt-4o-mini produced 1 exclusion and it was correct; "
                  "llama3.2:latest produced 40 and 43 on two runs of the "
                  "same configuration, and qwen2.5:7b produced 4. All but "
                  "one per llama3.2 run, and all four from qwen2.5, were "
                  "records the audited run kept; the four were examined "
                  "individually and are wrong. Each carried a real quote "
                  "and a confidence above threshold. The quote check "
                  "cannot tell whether a quote is relevant, and at "
                  "temperature 0 the same model did not exclude the same "
                  "papers twice. Leave this off unless you have validated "
                  "the model on your own corpus. Whatever this setting, a "
                  "removal the model justifies by absence — answering "
                  "not_meet on an inclusion criterion — is never applied "
                  "automatically: there is no quote that can prove an "
                  "absence, so those records always go to human review."))
        self.lbl_exclude.grid(row=12, column=0, columnspan=3, sticky="w",
                              padx=10, pady=(0, 4))

        # Its own row. `lbl_status` above spans columns 0-2 of row 4, so a
        # button placed in column 2 of that row occupies the same grid
        # cell and the two overlap.
        self.btn_pull = ttk.Button(frm, text="Download a model…",
                                   command=self._offer_pull)
        self.btn_pull.grid(row=5, column=0, columnspan=3, sticky="w", **pad)
        self.btn_pull.grid_remove()

        actions = ttk.Frame(frm)
        actions.grid(row=9, column=0, columnspan=3, sticky="e", **pad)
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
        ).grid(row=10, column=0, columnspan=3, sticky="w", **pad)

    # -- behaviour ---------------------------------------------------------

    def _on_exclusion_toggled(self):
        """The user has now chosen, so the store stops deciding for them.

        Until this fires the setting stays ``None`` — *nobody has chosen*
        — and the provider answers. That distinction is the whole reason
        the setting is tri-state: a boolean written at install time is
        wrong the moment the provider changes.
        """
        self._exclusion_touched = True

    def _on_provider_changed(self):
        provider = self.var_provider.get()
        # The default follows the provider, so an untouched box has to
        # follow it too — otherwise switching from OpenAI to local leaves
        # a ticked box that no longer reflects what will happen.
        if not self._exclusion_touched:
            self.var_allow_exclusion.set(
                exclusion_allowed(provider=provider, setting=None))
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

    def _post(self, fn):
        """Marshal a worker-thread result back onto the GUI thread.

        F-147. ``self.after`` on a destroyed widget raises ``TclError``,
        and this call happens on a daemon thread, where the exception
        surfaces as a traceback on stderr and nothing else — the run
        continues, the user sees nothing, and the process exit code is
        untouched. A dialog that has been dismissed while a probe is in
        flight is ordinary, not exceptional: the probe has a 2-second
        timeout and "Not now" is one click away.
        """
        try:
            self.after(0, fn)
        except tk.TclError:
            pass                    # dismissed while the probe was in flight

    def _probe(self):
        """Detect on a worker thread; never on the GUI thread."""
        endpoint = self.var_endpoint.get().strip()
        self.lbl_status.configure(text="Checking…")

        provider = self.var_provider.get()
        api_key = self.var_key.get().strip()

        def _work():
            found = pd.detect(endpoint, api_key=api_key, provider=provider)
            self._post(lambda: self._status_arrived(found))

        threading.Thread(target=_work, daemon=True).start()

    def _status_arrived(self, found):
        """F-147. Guarded, because the widget may be gone by now.

        The maintainer's traceback, on every launch::

            File "provider_dialog.py", line 174, in <lambda>
              self.after(0, lambda: self._status_arrived(found))
            File "provider_dialog.py", line 180, in _status_arrived
              self.lbl_status.configure(text=found.detail or "Ready.")
            _tkinter.TclError: invalid command name
                ".!providerdialog.!frame.!label2"

        Detection runs on a daemon thread with a 2-second timeout and the
        dialog can be dismissed at any moment, so the callback outliving
        the widget is the normal case rather than a rare race. Guarding
        at ``_post`` alone is not enough: a dialog destroyed *between*
        the successful ``after`` and the callback firing lands here with
        an already-dead label, which is exactly the traceback above.

        The guard is on ``lbl_status`` rather than on ``self`` because a
        widget can be destroyed while its toplevel is still alive, and
        the label is what this method actually touches. That follows the
        shape of the only other ``winfo_exists`` guard in the repository,
        in ``_offer_pull`` below, which checks the outermost widget whose
        children it is about to write to.

        ``self._status`` is still recorded first: it costs nothing, it
        cannot fail, and a caller reading the dialog's result after it
        closes should see what the probe actually found.
        """
        self._status = found
        if not self.lbl_status.winfo_exists():
            return
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
            self._post(_apply)

        def _work():
            result = mp.pull(self.var_endpoint.get().strip(), model.name,
                             on_progress=_progress, cancel=self._cancel)
            self._post(lambda: self._pull_finished(win, model, result))

        threading.Thread(target=_work, daemon=True).start()

    def _pull_finished(self, win, model, result):
        """F-147, the same class as ``_status_arrived`` and found with it.

        A pull is measured in gigabytes and minutes, so the dialog being
        gone by the time it finishes is *more* likely here than on the
        probe, not less. Every statement below touches a widget: the
        status label directly, ``messagebox(parent=self)`` through its
        parent, and ``_probe`` through the label again.

        The progress window is destroyed before the guard, deliberately —
        it is a child of a dialog that may already be gone, and leaving a
        stranded progress window on screen would be a worse failure than
        the one being fixed.
        """
        from tkinter import messagebox

        try:
            win.destroy()
        except Exception:
            pass
        if not self.lbl_status.winfo_exists():
            return
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
        # Repair a blank endpoint rather than storing one. Session B's
        # review reproduced session A's billing defect through exactly
        # this hole: selecting local and clearing the endpoint box stored
        # {provider: "local", endpoint: ""}, and a blank endpoint used to
        # resolve to the paid vendor while `key_required("local")` waived
        # the key gate. `resolve_openai_base_url` now refuses that too, so
        # this is the second of two independent guards.
        endpoint = self.var_endpoint.get().strip()
        if not endpoint:
            endpoint = (DEFAULT_OPENAI_ENDPOINT if provider == "openai"
                        else DEFAULT_LOCAL_ENDPOINT)
        # **F-140's live route, which its row does not name.** The row is
        # written against ``ApiKeyDialog``, which session B made
        # unreachable — this is the dialog the application opens now, and
        # it did not sanitize quotes at all. A key pasted with the
        # surrounding quotes a copy commonly carries was stored verbatim
        # and refused by the endpoint with a 401, which surfaces as a
        # terminal batch failure and a corpus of manufactured non-answers
        # (F-93), pointing the user at everything except the quotes.
        #
        # One function, shared with the other dialog, so the two cannot
        # disagree about what a key is — which is F-117's shape applied
        # to the value rather than to the predicate.
        from metascreener.api_key_dialog import sanitize_api_key

        self.result = {
            "provider": provider,
            "endpoint": endpoint,
            "api_key": sanitize_api_key(self.var_key.get()),
            "model": self.var_model.get().strip(),
            # `None` unless the user actually operated the checkbox, so a
            # dialog opened and accepted without touching it leaves the
            # provider deciding rather than freezing today's answer.
            "allow_llm_exclusion": (bool(self.var_allow_exclusion.get())
                                    if self._exclusion_touched else None),
        }
        self.destroy()

    def _dismiss(self):
        """Write nothing. The store stays UNCONFIGURED and the LLM stages
        report why they cannot run — which is a working application, not a
        refusal to start."""
        self.result = None
        self.destroy()
