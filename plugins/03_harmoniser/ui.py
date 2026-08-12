# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""ui.py - Plugin 03 Harmoniser: Tkinter view (UiState + HarmoniserView).

Owns all Tkinter widget construction, event handlers, workflow methods,
and threading. Orchestrates the engine modules (parser, inference,
llm_refine, exporters, bundle) but contains no engine logic.

Extracted from plugin.py in Conv 4 of the v3.1.0 refactor; behaviour
preserved verbatim."""

import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .parser import (
    STAGES, OPERATORS, _now_iso, _safe_str, _read_text_file,
    _rtf_to_text, _is_rtf_path, _load_a_header_and_stats,
    _get_best_text_targets, _detect_id_column, _canonicalize_targets,
    _parse_what_cell, _what_to_export, _parse_free_text_criteria,
    _load_structured_criteria_table, _normalize_structured_row,
)
from .inference import DEFAULT_THRESHOLD, _infer_criterion_details, _validate_row
from .llm_refine import STAGE as LLM_STAGE, _llm_refine, _sdk_importable
from .exporters import BUNDLE_ROOT_NAME
from .bundle import export_screen_a_bundle
from .validate_report import build_validation_report

#: Dispatch for `validate_report.Dialog.kind`. A dict rather than an if/elif so
#: an unknown kind raises here instead of silently showing nothing.
_SHOW = {
    "error": messagebox.showerror,
    "info": messagebox.showinfo,
    "warning": messagebox.showwarning,
}

# Wave 11 session C. The harmoniser's LLM path gets the same provider
# treatment as EL and IL: session A's unified key predicate and session
# B's readiness gate, rather than a third answer of its own.
from plugins._common.provider_detect import (
    last_known,
    model_choices,
    refresh as pd_refresh,
)
from plugins._common.widgets import RecheckButton, Tooltip
from plugins._common.settings import (
    apply_stage_fields,
    load_settings,
    resolve_stage,
)
from plugins._common.stage_state import Readiness, llm_readiness


@dataclass
class _UiState:
    criteria_path: str = ""
    criteria_kind: str = ""  # rtf/txt/csv/xlsx/paste
    a_path: str = ""
    a_columns: List[str] = None  # type: ignore
    a_id_col: str = ""
    text_stats: Dict[str, float] = None  # type: ignore
    criteria_text: str = ""
    rows: List[Dict[str, Any]] = None  # type: ignore

    def __post_init__(self):
        if self.a_columns is None:
            self.a_columns = []
        if self.text_stats is None:
            self.text_stats = {}
        if self.rows is None:
            self.rows = []


#: What the model box shows when nothing is stored. Named rather than
#: inlined twice: the seed and the fallback must be the SAME string, or
#: the seeded value looks like an edit and gets pinned.
DEFAULT_HARMONISER_MODEL = "gpt-4o-mini"


class HarmoniserView(ttk.Frame):
    def __init__(self, master: tk.Misc):
        super().__init__(master)
        self.state = _UiState()

        self._worker: Optional[threading.Thread] = None
        self._worker_err: Optional[str] = None
        self._worker_done: bool = False

        self._build_ui()
        self.on_provider_changed()      # seeds the combobox and the label

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        top.columnconfigure(1, weight=1)

        crit_box = ttk.LabelFrame(top, text="1) Criteria (required)")
        crit_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        ttk.Button(crit_box, text="Load TXT/RTF…", command=self._load_criteria_text).grid(row=0, column=0, padx=6, pady=6, sticky="ew")
        ttk.Button(crit_box, text="Load table CSV/XLSX…", command=self._load_criteria_table).grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        ttk.Button(crit_box, text="Clear", command=self._clear_criteria).grid(row=0, column=2, padx=6, pady=6, sticky="ew")

        self.lbl_crit = ttk.Label(crit_box, text="No criteria loaded")
        self.lbl_crit.grid(row=1, column=0, columnspan=3, padx=6, pady=(0, 6), sticky="w")

        a_box = ttk.LabelFrame(top, text="2) A vector (required)")
        a_box.grid(row=0, column=1, sticky="nsew")
        a_box.columnconfigure(0, weight=1)

        row0 = ttk.Frame(a_box)
        row0.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        row0.columnconfigure(1, weight=1)

        ttk.Button(row0, text="Load A CSV…", command=self._load_a_csv).grid(row=0, column=0, sticky="w")
        self.lbl_a = ttk.Label(row0, text="No A loaded")
        self.lbl_a.grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.lbl_a_stats = ttk.Label(a_box, text="")
        self.lbl_a_stats.grid(row=1, column=0, sticky="w", padx=6, pady=(0, 6))

        body = ttk.Panedwindow(self, orient="horizontal")
        body.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))

        left = ttk.Frame(body)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        left_top = ttk.Frame(left)
        left_top.grid(row=0, column=0, sticky="ew")
        left_top.columnconfigure(3, weight=1)

        ttk.Label(left_top, text="Criteria text (editable):").grid(row=0, column=0, sticky="w")

        # D9. The "LLM refine" checkbox is DELETED, not wired. This
        # REVERSES the coordinator's wave-8 decision to wire it, and the
        # reversal is recorded in F-118's register row so it is not
        # re-litigated.
        #
        # The reasoning: the LLM/no-LLM choice is already expressed by
        # two buttons a few inches to the right — "Harmonise (no-LLM)"
        # and "Harmonise + LLM" — and `_harmonise_llm` never consulted
        # `var_llm`. Wiring it would mean deciding what it should mean
        # when it disagrees with the button pressed, and every answer to
        # that is worse than not having the control: a third control that
        # can contradict two explicit ones is a control that makes the
        # user wrong about what they asked for. F-118's row calls the
        # checkbox the worst of that finding's three halves precisely
        # because it reads as the cost-and-provider safety switch, and
        # a wired version that could be overridden by a button would
        # still read that way while still not being one.

        ttk.Label(left_top, text="Model:").grid(row=0, column=1, padx=(10, 0), sticky="e")
        # The same editable combobox EL and IL carry, for the same
        # reason: llama.cpp ignores the model field, so a readonly
        # dropdown would make a server that will not enumerate unusable.
        self.var_model = tk.StringVar(value=self._seed_model())
        self.cmb_model = ttk.Combobox(left_top, textvariable=self.var_model,
                                      width=18, values=())
        self.cmb_model.grid(row=0, column=2, sticky="w")
        self.ent_model = self.cmb_model      # kept: the old attribute name

        # F-117's third predicate, removed. This label read
        # `os.getenv("OPENAI_API_KEY")` directly, so it said "missing" to
        # a user running locally who needs no key — and disagreed with
        # the button beside it. It now shows exactly what EL and IL show,
        # from the same function.
        self.lbl_key = ttk.Label(left_top, text="")
        self.lbl_key.grid(row=0, column=3, padx=(10, 0), sticky="w")

        # F-149. Beside the indicator that says "Unreachable", because
        # that is where the user is looking when they need it.
        self.btn_recheck = RecheckButton(
            left_top, prepare=self._reprobe_job,
            on_done=self.on_provider_changed)
        self.btn_recheck.grid(row=0, column=4, padx=(10, 0), sticky="w")
        Tooltip(self.btn_recheck,
                "Ask this stage's endpoint again. The provider is checked "
                "once at startup, so a server started, restarted or woken "
                "since then is not noticed until you ask.")

        # wraplength, because D4/D5's messages are sentences, not
        # labels. Without it the review measured 46% of the text
        # clipped off the pane — the same overflow shape session B
        # shipped, in the label that carries the remedy.
        self.lbl_models = ttk.Label(left_top, text="", foreground="#555",
                                    wraplength=520, justify="left")
        self.lbl_models.grid(row=1, column=0, columnspan=5, sticky="w",
                             pady=(2, 0))

        self.var_model.trace_add(
            "write", lambda *_a: self._refresh_buttons())
        self.cmb_model.bind("<<ComboboxSelected>>",
                            lambda _e: self._model_edited())
        self.cmb_model.bind("<FocusOut>", lambda _e: self._model_edited())

        txt_frame = ttk.Frame(left)
        txt_frame.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        txt_frame.rowconfigure(0, weight=1)
        txt_frame.columnconfigure(0, weight=1)

        self.txt_criteria = tk.Text(txt_frame, height=18, wrap="word")
        ysb = ttk.Scrollbar(txt_frame, orient="vertical", command=self.txt_criteria.yview)
        self.txt_criteria.configure(yscrollcommand=ysb.set)

        self.txt_criteria.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")

        body.add(left, weight=1)

        right = ttk.Frame(body)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(3, weight=1)

        btns = ttk.Frame(right)
        btns.grid(row=0, column=0, sticky="ew")

        self.btn_harmonise = ttk.Button(btns, text="Harmonise (no-LLM)", command=self._harmonise_no_llm)
        self.btn_harmonise.grid(row=0, column=0, padx=(0, 6), pady=(0, 6), sticky="w")

        self.btn_harmonise_llm = ttk.Button(btns, text="Harmonise + LLM", command=self._harmonise_llm)
        self.btn_harmonise_llm.grid(row=0, column=1, padx=(0, 6), pady=(0, 6), sticky="w")

        self.btn_validate = ttk.Button(btns, text="Validate", command=self._validate)
        self.btn_validate.grid(row=0, column=2, padx=(0, 6), pady=(0, 6), sticky="w")

        self.btn_export = ttk.Button(btns, text="Export bundle…", command=self._export_bundle)
        self.btn_export.grid(row=0, column=3, padx=(0, 6), pady=(0, 6), sticky="w")

        self.btn_pick_target = ttk.Button(btns, text="Pick target(s)…", command=self._pick_targets)
        self.btn_pick_target.grid(row=0, column=4, padx=(0, 6), pady=(0, 6), sticky="w")

        table_frame = ttk.LabelFrame(right, text="Harmonised criteria")
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        cols = ("stage", "id", "type", "label", "operator", "target", "what", "threshold", "enabled")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="extended")
        for c in cols:
            self.tree.heading(c, text=c)
            width = 80
            if c == "label":
                width = 260
            elif c == "target":
                width = 220
            elif c == "what":
                width = 280
            elif c == "id":
                width = 90
            elif c == "enabled":
                width = 70
            self.tree.column(c, width=width, anchor="w")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self.tree.tag_configure("error", background="#ffe5e5")
        self.tree.tag_configure("warn", background="#fff6d5")
        # Wave 13c B: a row the linter has something to say about, which
        # `_validate_row` passed clean. Blue rather than a third warm shade,
        # because the existing two already sit close together and HO-13-2 is
        # open on whether they are distinguishable at all. HO-13-11 asks the
        # same question of this one. Deliberately the palest of the three: it
        # is the only tint that stops nothing.
        self.tree.tag_configure("lint", background="#e8f0fe")
        self.tree.bind("<Double-1>", self._on_double_click)

        log_frame = ttk.LabelFrame(right, text="Log")
        log_frame.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.txt_log = tk.Text(log_frame, height=10, wrap="word", state="disabled")
        logsb = ttk.Scrollbar(log_frame, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=logsb.set)

        self.txt_log.grid(row=0, column=0, sticky="nsew")
        logsb.grid(row=0, column=1, sticky="ns")

        body.add(right, weight=2)

        self._edit_widget: Optional[tk.Widget] = None

    def _log(self, msg: str) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"[{_now_iso()}] {msg}\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    STAGE = LLM_STAGE

    def _stored_config(self):
        """This stage's effective configuration.

        Guarded: ``load_settings`` raises on a settings file that exists
        and cannot be parsed, and ``main.py::resolve_plugin_entrypoint``
        swallows every exception into a ``print()``, so an unguarded read
        would make this tab silently absent.
        """
        try:
            cfg = load_settings()
        except Exception:
            cfg = {}
        return resolve_stage(cfg, self.STAGE,
                             env_endpoint=os.environ.get("OPENAI_BASE_URL", ""),
                             env_api_key=os.environ.get("OPENAI_API_KEY", ""))

    def _seed_model(self) -> str:
        return self._stored_config().model or DEFAULT_HARMONISER_MODEL

    def _model_edited(self) -> None:
        try:
            apply_stage_fields(
                self.STAGE,
                # See the EL/IL views: without the fallback this pinned
                # the hard-coded "gpt-4o-mini" as a permanent override on
                # the first focus-out, so a model chosen later in the
                # provider dialog never reached this stage again.
                fallbacks={"model": DEFAULT_HARMONISER_MODEL},
                model=self.var_model.get())
        except Exception as e:
            self._log(f"Model not saved: {e}")
        self._refresh_buttons()

    def _reprobe_job(self):
        """Build the probe to run off the GUI thread (F-149).

        Reads `cfg.endpoint` rather than a live widget, because this View
        has no endpoint box -- the same source `_readiness` uses, so the
        tab re-probes exactly the server it reports on.
        """
        cfg = self._stored_config()
        endpoint, api_key, provider = cfg.endpoint, cfg.api_key, cfg.provider
        return lambda: pd_refresh(endpoint, api_key=api_key,
                                  provider=provider)

    def _readiness(self) -> Readiness:
        """Whether this stage's LLM path may run — **the same function EL
        and IL ask**.

        The harmoniser used to decide for itself, and got three things
        different from the other two stages: it never checked
        ``NOT_CONFIGURED``, it never consulted the probe, and its
        provider default was a keyless one. A user running locally found
        that this one button still demanded a paid key, while a user with
        an unreachable server found it live.

        ``has_bundle=True`` is passed deliberately. This stage has no
        bundle — its inputs are the criteria text and the A vector — and
        ``_ensure_ready`` owns that check with messages that name those
        two things. ``NO_BUNDLE`` would tell a harmoniser user to load a
        ScreenA bundle ZIP, which is the wrong file at the wrong stage.
        """
        cfg = self._stored_config()
        return llm_readiness(stage="Harmonise",
                             has_bundle=True,
                             provider=cfg.provider,
                             api_key=cfg.api_key,
                             model=self.var_model.get(),
                             endpoint=cfg.endpoint,
                             probe=last_known(cfg.endpoint))

    def on_provider_changed(self) -> None:
        """Re-seed after the application settled or re-probed a provider."""
        seed = self._stored_config()
        if seed.model:
            self.var_model.set(seed.model)
        choices = model_choices(last_known(self._stored_config().endpoint))
        try:
            self.cmb_model.configure(values=list(choices.values))
        except Exception:
            pass
        self.lbl_models.configure(text=choices.note)
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        has_crit = bool(self.txt_criteria.get("1.0", "end").strip()) or bool(self.state.rows)
        has_a = bool(self.state.a_path) and bool(self.state.a_columns)
        can_h = has_crit and has_a and (self._worker is None)

        self.btn_harmonise.configure(state=("normal" if can_h else "disabled"))

        # F-117/F-118. Two questions, each asked of whoever can answer it:
        # whether this configuration may run is `llm_readiness`'s, shared
        # with EL and IL; whether the SDK is importable is the refine
        # module's. What used to be here was a third answer to the first.
        ready = self._readiness()
        llm_ok = ready.can_run and _sdk_importable()
        # The Readiness object reports only the PROVIDER half here, because
        # `_readiness` passes has_bundle=True -- this stage's inputs are the
        # criteria text and the A vector, and `_ensure_ready` owns that check
        # with messages that name them. So its "Ready to run" would sit beside
        # a button disabled for want of criteria, which is a label claiming
        # more than it can support. Found by executing the real widget, not by
        # reading it. When the provider is settled the label says so and stops
        # there; when it is not, the shared wording is exact and is used
        # verbatim.
        self.lbl_key.configure(
            text="Provider ready" if ready.can_run else ready.label)

        self.btn_harmonise_llm.configure(state=("normal" if (can_h and llm_ok) else "disabled"))
        self.btn_validate.configure(state=("normal" if (bool(self.state.rows) and has_a and self._worker is None) else "disabled"))
        self.btn_export.configure(state=("normal" if (bool(self.state.rows) and has_a and self._worker is None) else "disabled"))
        self.btn_pick_target.configure(state=("normal" if (bool(self.state.rows) and has_a and self._worker is None) else "disabled"))

    def _ensure_ready(self) -> bool:
        if not (self.state.a_path and self.state.a_columns):
            messagebox.showwarning("Missing A", "Please load the A vector CSV first.")
            return False
        if not (self.txt_criteria.get("1.0", "end").strip() or self.state.rows):
            messagebox.showwarning("Missing criteria", "Please load/paste criteria first.")
            return False
        return True

    def _load_criteria_text(self) -> None:
        path = filedialog.askopenfilename(
            title="Load criteria TXT/RTF",
            filetypes=[("Text/RTF", "*.txt *.rtf"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            raw = _read_text_file(path)
            if _is_rtf_path(path):
                raw = _rtf_to_text(raw)
            raw = raw.replace("\r\n", "\n").replace("\r", "\n")
            self.state.criteria_path = path
            self.state.criteria_kind = "rtf" if _is_rtf_path(path) else "txt"
            self.state.criteria_text = raw
            self.txt_criteria.delete("1.0", "end")
            self.txt_criteria.insert("1.0", raw)
            self.state.rows = []
            self._clear_table()
            self.lbl_crit.configure(text=f"Loaded: {Path(path).name}")
            self._log(f"Criteria loaded ({self.state.criteria_kind}): {path}")
        except Exception as e:
            messagebox.showerror("Load failed", str(e))
        finally:
            self._refresh_buttons()

    def _load_criteria_table(self) -> None:
        path = filedialog.askopenfilename(
            title="Load criteria table",
            filetypes=[("CSV/XLSX", "*.csv *.xlsx *.xlsm"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            raw_rows, kind = _load_structured_criteria_table(path)
            self.state.criteria_path = path
            self.state.criteria_kind = kind

            self.txt_criteria.delete("1.0", "end")
            self.txt_criteria.insert(
                "1.0",
                "\n".join([_safe_str(r) for r in raw_rows[:20]]) + ("\n…" if len(raw_rows) > 20 else ""),
            )

            self.state.criteria_text = "\n".join([_safe_str(r) for r in raw_rows])

            self.state.rows = [_normalize_structured_row(r) for r in raw_rows]
            self._render_rows()
            self.lbl_crit.configure(text=f"Loaded: {Path(path).name} ({len(self.state.rows)} rows)")
            self._log(f"Criteria table loaded ({kind}): {path}")
        except Exception as e:
            messagebox.showerror("Load failed", str(e))
        finally:
            self._refresh_buttons()

    def _clear_criteria(self) -> None:
        self.state.criteria_path = ""
        self.state.criteria_kind = ""
        self.state.criteria_text = ""
        self.txt_criteria.delete("1.0", "end")
        self.state.rows = []
        self._clear_table()
        self.lbl_crit.configure(text="No criteria loaded")
        self._log("Criteria cleared")
        self._refresh_buttons()

    def _load_a_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="Load A vector CSV",
            filetypes=[("CSV", "*.csv"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            cols, stats = _load_a_header_and_stats(path)
            self.state.a_path = path
            self.state.a_columns = cols
            self.state.text_stats = stats
            self.state.a_id_col = _detect_id_column(cols)

            self.lbl_a.configure(text=f"Loaded: {Path(path).name} ({len(cols)} cols), id={self.state.a_id_col}")

            if stats:
                s = " / ".join([f"{k}:{stats[k]*100:.0f}%" for k in stats])
                self.lbl_a_stats.configure(text=f"Text coverage (sample): {s}")
            else:
                self.lbl_a_stats.configure(text="")

            self._log(f"A loaded: {path}")

            if self.state.rows:
                self._validate(show_ok=False)

        except Exception as e:
            messagebox.showerror("Load failed", str(e))
        finally:
            self._refresh_buttons()

    def _harmonise_no_llm(self) -> None:
        if not self._ensure_ready():
            return

        # Dynamic default text target from A coverage
        default_text_target = _get_best_text_targets(self.state.a_columns, self.state.text_stats)
        default_text_target, _ = _canonicalize_targets(default_text_target, self.state.a_columns)

        # If rows already exist (structured), infer missing fields conservatively
        if self.state.rows:
            self._log("Harmonise (no-LLM): inferring missing fields in existing rows…")
            for r in self.state.rows:
                crit_type = _safe_str(r.get("type")).lower() or "include"
                seed_text = _safe_str(r.get("label")) or _safe_str(r.get("source_text")) or ""

                needs = (
                    not _safe_str(r.get("stage")).strip()
                    or not _safe_str(r.get("operator")).strip()
                    or not _safe_str(r.get("target")).strip()
                    or not isinstance(r.get("what"), list)
                    or len(r.get("what") or []) == 0
                )

                if needs:
                    inferred = _infer_criterion_details(
                        _safe_str(r.get("id")),
                        crit_type,
                        seed_text,
                        list(self.state.a_columns),
                        default_text_target,
                    )
                    if not _safe_str(r.get("stage")).strip():
                        r["stage"] = inferred["stage"]
                    if not _safe_str(r.get("operator")).strip():
                        r["operator"] = inferred["operator"]
                    if not _safe_str(r.get("target")).strip():
                        r["target"] = inferred["target"]
                    if not isinstance(r.get("what"), list) or not (r.get("what") or []):
                        r["what"] = inferred["what"]

                st = _safe_str(r.get("stage")).upper()
                if st in {"EH", "IH"}:
                    r["threshold"] = ""
                else:
                    if not _safe_str(r.get("threshold")).strip():
                        r["threshold"] = f"{DEFAULT_THRESHOLD:.2f}"

                r["target"], _ = _canonicalize_targets(_safe_str(r.get("target")), self.state.a_columns)

            self._render_rows(with_validation=True)
            self._validate(show_ok=True)
            return

        # Free-text parse path
        text = self.txt_criteria.get("1.0", "end")
        parsed = _parse_free_text_criteria(text)
        if not parsed:
            messagebox.showerror("No criteria found", "No criteria detected. Check formatting (IC/EC lines or headers).")
            return

        self._log(f"Harmonise (no-LLM): parsed {len(parsed)} criteria; inferring rules…")

        rows: List[Dict[str, Any]] = []
        for crit_id, crit_type, label, source_line in parsed:
            inferred = _infer_criterion_details(
                crit_id=crit_id,
                crit_type=crit_type,
                label=label,
                a_columns=list(self.state.a_columns),
                default_text_target=default_text_target,
            )

            stage = inferred["stage"]
            operator = inferred["operator"]
            target = inferred["target"]
            what = inferred["what"]

            threshold = ""
            if stage in {"EL", "IL"}:
                threshold = f"{DEFAULT_THRESHOLD:.2f}"

            rows.append({
                "stage": stage,
                "id": crit_id,
                "type": crit_type,
                "scope": "metadata",
                "label": label,
                "operator": operator,
                "target": target,
                "what": what,
                "threshold": threshold,
                "enabled": True,
                "source_text": source_line,
            })

        self.state.rows = rows
        self._render_rows(with_validation=True)
        self._validate(show_ok=True)

    def _harmonise_llm(self) -> None:
        if not self._ensure_ready():
            return
        # Session C: the same gate, and the same words, as EL and IL. The
        # old message was "OPENAI_API_KEY missing or OpenAI package not
        # available", which is wrong twice for a local user — they need
        # no key, and the thing that is actually missing might be a
        # running server or a chosen provider. `ready.detail` names the
        # one next thing to fix.
        self._model_edited()
        ready = self._readiness()
        if not ready.can_run:
            messagebox.showwarning("Harmonise + LLM cannot start",
                                   ready.detail)
            return
        if not _sdk_importable():
            messagebox.showwarning(
                "LLM unavailable",
                "The OpenAI client library is not installed, so no "
                "provider can be reached — including a local one.\n\n"
                "Install it with: pip install openai")
            return

        if not self.state.rows:
            self._harmonise_no_llm()
            if not self.state.rows:
                return

        model = ready.model
        full_text = self.txt_criteria.get("1.0", "end").strip() or self.state.criteria_text

        def worker():
            try:
                refined = _llm_refine(self.state.rows, full_text, self.state.a_columns, model=model, log=self._thread_log)
                self.state.rows = refined
                self._worker_err = None
            except Exception as e:
                self._worker_err = str(e)
            finally:
                self._worker_done = True

        self._start_worker(worker, "LLM harmonisation")

    def _thread_log(self, msg: str) -> None:
        self.after(0, lambda: self._log(msg))

    def _start_worker(self, target, label: str) -> None:
        if self._worker is not None:
            return
        self._worker_done = False
        self._worker_err = None

        self._log(f"Starting: {label} …")
        self._worker = threading.Thread(target=target, daemon=True)
        self._worker.start()
        self._refresh_buttons()
        self.after(100, self._poll_worker)

    def _poll_worker(self) -> None:
        if self._worker is None:
            return
        if not self._worker_done:
            self.after(150, self._poll_worker)
            return

        err = self._worker_err
        self._worker = None
        self._worker_done = False

        if err:
            self._log(f"Worker failed: {err}")
            messagebox.showerror("Operation failed", err)
        else:
            self._log("Worker finished successfully")
            self._render_rows(with_validation=True)
            self._validate(show_ok=True)

        self._refresh_buttons()

    def _validate(self, show_ok: bool = True) -> bool:
        # The decision lives in `validate_report.build_validation_report`, which
        # is pure and therefore testable; this method is the part that needs a
        # widget. Extracted unchanged in wave 13c B — see
        # `tests/test_harmoniser_validate_wiring.py` for the characterisation.
        if not self.state.rows:
            return False
        if not self.state.a_columns:
            messagebox.showwarning("Missing A", "Load A vector first.")
            return False

        report = build_validation_report(
            self.state.rows, self.state.a_columns, show_ok=show_ok
        )

        self._render_rows(with_validation=True)
        self._log(report.log_line)

        if report.dialog is not None:
            _SHOW[report.dialog.kind](report.dialog.title, report.dialog.body)

        return report.ok

    def _export_bundle(self) -> None:
        if not self.state.rows:
            messagebox.showwarning("Nothing to export", "Harmonise criteria first.")
            return
        if not self._validate(show_ok=False):
            messagebox.showerror("Export blocked", "Fix validation errors before export.")
            return
        if not (self.state.a_path and self.state.a_columns):
            messagebox.showerror("Missing A", "Load the A vector CSV before export.")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"{BUNDLE_ROOT_NAME}_{ts}.zip"

        zip_path = filedialog.asksaveasfilename(
            title="Save Screen A bundle ZIP",
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[("ZIP", "*.zip")],
        )
        if not zip_path:
            return

        criteria_source_text = self.txt_criteria.get("1.0", "end").strip()

        try:
            export_screen_a_bundle(
                rows=self.state.rows,
                a_path=self.state.a_path,
                a_columns=self.state.a_columns,
                a_id_col_guess=self.state.a_id_col,
                criteria_path=self.state.criteria_path,
                criteria_kind=self.state.criteria_kind,
                criteria_source_text=criteria_source_text,
                zip_out_path=zip_path,
            )
            self._log(f"Bundle exported: {zip_path}")
            messagebox.showinfo("Export done", f"Exported bundle ZIP:\n{zip_path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))
            self._log(f"Export failed: {e}")


    def _pick_targets(self) -> None:
        if not self.state.a_columns:
            messagebox.showwarning("Missing A", "Load A vector first.")
            return
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Pick targets", "Select one or more rows first.")
            return

        win = tk.Toplevel(self)
        win.title("Pick target columns")
        win.geometry("420x500")

        ttk.Label(win, text="Select one or more A columns (Ctrl/Shift):").pack(anchor="w", padx=10, pady=(10, 4))

        lb = tk.Listbox(win, selectmode="extended")
        lb.pack(fill="both", expand=True, padx=10, pady=6)

        for c in self.state.a_columns:
            lb.insert("end", c)

        btn_row = ttk.Frame(win)
        btn_row.pack(fill="x", padx=10, pady=10)

        def apply():
            picks = [lb.get(i) for i in lb.curselection()]
            if not picks:
                messagebox.showwarning("No selection", "Pick at least one column")
                return
            tgt = ",".join(picks)
            for it in sel:
                rid = self.tree.set(it, "id")
                r = self._find_row_by_id(rid)
                if r is not None:
                    r["target"], _ = _canonicalize_targets(tgt, self.state.a_columns)
            self._render_rows(with_validation=True)
            win.destroy()

        ttk.Button(btn_row, text="Apply", command=apply).pack(side="left")
        ttk.Button(btn_row, text="Cancel", command=win.destroy).pack(side="right")

    def _clear_table(self) -> None:
        for it in self.tree.get_children():
            self.tree.delete(it)

    def _find_row_by_id(self, rid: str) -> Optional[Dict[str, Any]]:
        rid = rid.strip()
        for r in self.state.rows:
            if _safe_str(r.get("id")).strip() == rid:
                return r
        return None

    def _render_rows(self, with_validation: bool = False) -> None:
        self._clear_table()
        if not self.state.rows:
            self._refresh_buttons()
            return

        for r in self.state.rows:
            st = _safe_str(r.get("stage")).upper()
            if st in {"EH", "IH"}:
                r["threshold"] = ""
            else:
                if not _safe_str(r.get("threshold")).strip():
                    r["threshold"] = f"{DEFAULT_THRESHOLD:.2f}"

        # One source for the tints. `build_validation_report` already decides
        # error/warn/lint per row and is tested; deciding it a second time here
        # would be two representations of one rule, which is F-69's shape.
        marks = ()
        if with_validation and self.state.a_columns:
            marks = build_validation_report(
                self.state.rows, self.state.a_columns, show_ok=False
            ).marks

        for index, r in enumerate(self.state.rows):
            vals = (
                r.get("stage", ""),
                r.get("id", ""),
                r.get("type", ""),
                _safe_str(r.get("label", ""))[:200],
                r.get("operator", ""),
                r.get("target", ""),
                _what_to_export(r.get("operator", ""), r.get("what", []) or [])[:260],
                r.get("threshold", ""),
                "1" if bool(r.get("enabled", True)) else "0",
            )

            tags = ()
            if index < len(marks) and marks[index].tag:
                tags = (marks[index].tag,)

            self.tree.insert("", "end", values=vals, tags=tags)

        self._refresh_buttons()

    def _destroy_editor(self) -> None:
        try:
            if self._edit_widget is not None:
                self._edit_widget.destroy()
        except Exception:
            pass
        finally:
            self._edit_widget = None

    def _on_double_click(self, event) -> None:
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not item or not col:
            return

        col_index = int(col.replace("#", "")) - 1
        columns = list(self.tree["columns"])
        if col_index < 0 or col_index >= len(columns):
            return

        col_name = columns[col_index]
        if col_name not in {"stage", "label", "operator", "target", "what", "threshold", "enabled"}:
            return

        if col_name == "enabled":
            rid = self.tree.set(item, "id")
            r = self._find_row_by_id(rid)
            if r is not None:
                r["enabled"] = not bool(r.get("enabled", True))
                self._render_rows(with_validation=True)
            return

        self._destroy_editor()

        bbox = self.tree.bbox(item, col)
        if not bbox:
            return
        x, y, w, h = bbox

        rid = self.tree.set(item, "id")
        row = self._find_row_by_id(rid)
        if row is None:
            return

        if col_name == "threshold":
            st = _safe_str(row.get("stage")).upper()
            if st not in {"EL", "IL"}:
                return

        value = self.tree.set(item, col_name)

        if col_name == "stage":
            cb = ttk.Combobox(self.tree, values=list(STAGES), state="readonly")
            cb.set(value or "")
            cb.place(x=x, y=y, width=w, height=h)
            cb.focus_set()

            def save(_=None):
                v = cb.get().strip().upper()
                if v in STAGES:
                    row["stage"] = v
                    if v in {"EH", "IH"}:
                        row["threshold"] = ""
                    else:
                        if not _safe_str(row.get("threshold")).strip():
                            row["threshold"] = f"{DEFAULT_THRESHOLD:.2f}"
                self._destroy_editor()
                self._render_rows(with_validation=True)

            cb.bind("<<ComboboxSelected>>", save)
            cb.bind("<Return>", save)
            cb.bind("<Escape>", lambda _=None: self._destroy_editor())

            self._edit_widget = cb
            return

        if col_name == "operator":
            cb = ttk.Combobox(self.tree, values=list(OPERATORS), state="readonly")
            cb.set(value or "")
            cb.place(x=x, y=y, width=w, height=h)
            cb.focus_set()

            def save(_=None):
                v = cb.get().strip().lower()
                if v in OPERATORS:
                    row["operator"] = v
                    if v == "llm":
                        what_list = row.get("what") or []
                        if isinstance(what_list, list):
                            if len(what_list) != 1:
                                seed = (_safe_str(row.get("label")) or _safe_str(row.get("source_text")) or "").strip()
                                row["what"] = [seed] if seed else [""]
                        else:
                            row["what"] = [str(what_list).strip()]
                self._destroy_editor()
                self._render_rows(with_validation=True)

            cb.bind("<<ComboboxSelected>>", save)
            cb.bind("<Return>", save)
            cb.bind("<Escape>", lambda _=None: self._destroy_editor())

            self._edit_widget = cb
            return

        ent = ttk.Entry(self.tree)
        ent.insert(0, value)
        ent.place(x=x, y=y, width=w, height=h)
        ent.focus_set()

        def save(_=None):
            v = ent.get().strip()
            if col_name == "label":
                row["label"] = v
            elif col_name == "target":
                canon, _unk = _canonicalize_targets(v, self.state.a_columns)
                row["target"] = canon
            elif col_name == "what":
                row["what"] = _parse_what_cell(row.get("operator", "contains"), v)
            elif col_name == "threshold":
                row["threshold"] = v
            self._destroy_editor()
            self._render_rows(with_validation=True)

        ent.bind("<Return>", save)
        ent.bind("<Escape>", lambda _=None: self._destroy_editor())
        ent.bind("<FocusOut>", save)

        self._edit_widget = ent

