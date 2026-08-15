# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
_engine_probe.py — drive the real EL/IL engines from a clean interpreter.

Why this is a module and not a fixture
--------------------------------------
``tests/test_view_smoke.py`` runs in a **subprocess with the real tkinter**,
because ``conftest.py`` replaces ``tkinter`` with a ``MagicMock`` at import
time and the two cannot coexist in one process. That subprocess gets no
conftest and no pytest fixtures, so anything it needs has to be importable
on its own. This is that.

It exists for F-161. The drill-down call sites — ``_refresh_reports_view``
in both Views and ``on_criterion_doubleclick`` in both standalone shells —
were never executed by any test, and the fix for F-156 was verified only by
applying the *predicate* the way a drill-down would. To execute the real
sites you need a real class, which needs a real ``ttk.Frame``, which needs
the subprocess. And the state those sites read must come from the engine
rather than from a literal — that is the whole lesson of wave 11 session
B's ``probe=SimpleNamespace(state="ready")``, and repeating it here in the
test written to close a vocabulary defect would be absurd.

The leading underscore keeps pytest from collecting it.
"""
import inspect
import json
import threading


class _FakeResponse:
    def __init__(self, payload):
        msg = type("M", (), {"content": json.dumps(payload)})
        self.choices = [type("C", (), {"message": msg})]


def _client(decision, confidence=0.9):
    """Every record answered, the quote lifted verbatim from the title.

    The quote is the title, so the evidence gate *passes*: these are
    confident, well-quoted verdicts, which is the case flag-only exists
    for. A malformed answer is already fail-safe and proves nothing here.
    """
    class _Completions:
        def create(self, *, model, messages, temperature, response_format=None):
            items = json.loads(messages[1]["content"])["items"]
            return _FakeResponse([
                {"a_id": it["a_id"], "decision": decision,
                 "confidence": confidence, "field": "title",
                 "quote": it["title"], "span": [0, 1]}
                for it in items
            ])

    return type("C", (), {"chat": type("Chat", (), {
        "completions": _Completions()})()})()


def run_flag_only(plugin_module, stage, ctype, decision, cid="EC-1", rows=4):
    """Run one stage end to end under flag-only and hand back what it made.

    Returns ``(full_rows, row_eval_lists, cid)``.

    ``llm_exclusion_allowed`` is forced on the *engine* module rather than
    on ``llm_client``: ``screen.py`` does ``from ... import
    llm_exclusion_allowed``, so it holds its own binding and patching the
    source module would be silently ignored — the caller would then be
    testing the default and not knowing it.
    """
    from plugins._common import llm_client as lc

    run = (plugin_module.run_el_screen if stage == "EL"
           else plugin_module.run_il_screen)
    engine = inspect.getmodule(run)

    saved = (lc._has_openai_key, lc._openai_client_for,
             engine.llm_exclusion_allowed)
    lc._has_openai_key = lambda *_a, **_k: True
    lc._openai_client_for = lambda *_a, **_k: _client(decision)
    engine.llm_exclusion_allowed = lambda *_a, **_k: False
    try:
        crit = plugin_module.Criterion(
            id=cid, stage=stage, ctype=ctype, enabled=True, operator="llm",
            targets=["title"], what_raw="x", what_list=["x"], threshold=0.6,
            source_text="x", label="x",
        )
        parse = plugin_module.ParseReport(
            header=["local_id", "title", "abstract", "keywords"],
            # Wave 15e: the title is the quote the fake model offers, and
            # the strict gate now demands SUBSTANCE_MIN_CHARS of it — a
            # 7-char "Title N" would be gate-refused and the EL arm would
            # stop producing the suppressed record this probe exists to
            # show (F-161's own defect shape).
            rows=[{"local_id": "A%03d" % i,
                   "title": "Title %d carries enough verbatim substance "
                            "for the strict gate" % i,
                   "abstract": "a", "keywords": "k"} for i in range(rows)],
            skipped=[])
        report = plugin_module.CriteriaLoadReport(criteria=[crit], warnings=[])
        full, _surv, _counts, _imp, evals, _c, _cx, _rep = run(
            parse, report, model="gemma3", trunc_chars=1500, batch_size=4,
            use_cache=False, cache_in={}, cancel_event=threading.Event())
    finally:
        (lc._has_openai_key, lc._openai_client_for,
         engine.llm_exclusion_allowed) = saved

    return full, evals, cid
