# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_view_smoke.py — F-14's gap, closed for the three LLM Views.

Why this file exists
--------------------
Nothing in this suite instantiates a View. ``conftest.py`` replaces
``tkinter`` with a ``MagicMock`` so plugin modules import on a headless
machine, which means ``ttk.Frame`` is a mock and ``class ELView(ttk.Frame)``
cannot be constructed. Session B wrote the consequence down as a LIMIT
after a dead Run button and three overflowing labels shipped past 906
green tests, and listed what a real smoke test would have to do.

**Session C then proved the point twice.** Both were caught by a
hand-driven real-Tk run, not by the suite:

* a per-stage endpoint made ``_readiness`` report ``Ready to run`` for a
  stage whose own server was dead;
* and, while repairing that, a plain ``NameError`` in ``_build_ui`` —
  ``seed`` referenced in a method where it is not in scope. **1321 tests
  were green with the EL and IL tabs unable to open at all.**

A ``NameError`` on a construction path is the cheapest possible defect to
catch and the suite could not see it. That is not a coverage gap, it is a
blind spot with a shape.

How it works, and why a subprocess
----------------------------------
The mock is installed at *import* time and is process-wide, so a real Tk
cannot coexist with it in this interpreter. The smoke therefore runs in a
**clean subprocess**: no conftest, no mock, the real ``tkinter``.

It skips rather than fails where there is no display — a headless CI box
is a supported place to run this suite, and a test that cannot run there
must not turn red there. It is therefore a *ratchet*, not a gate: it adds
cover on developer machines and on any CI with a display, and it never
subtracts.

What it asserts, from session B's own list
------------------------------------------
1. **Instantiate a View at all** — all three, which is where the
   ``NameError`` lived.
2. **Drive ``_readiness()`` and read the widget** — with a bundle, a
   model, a configured provider and a live probe, the Run button is
   enabled; without a probe it is not.
3. **Cover the default path**, not a constructed one: the first case is a
   fresh install, which is the state every launch starts in.
4. **Assert on the widget, not on the function.** ``llm_readiness`` was
   correct throughout both of session C's defects; what was wrong was
   what the View passed it and what it did with the answer.
"""
import os
import subprocess
import sys
import tempfile
import textwrap

import pytest

from conftest import PROJECT_ROOT


def _run(body: str):
    """Execute ``body`` in a clean interpreter with the real tkinter.

    Returns ``(returncode, stdout, stderr)``. The child gets its own
    settings directory, so it can neither read nor write the developer's.
    """
    script = textwrap.dedent(f'''
        import os, sys, tempfile, importlib, importlib.util
        d = tempfile.mkdtemp(prefix="view-smoke-")
        os.environ["APPDATA"] = os.path.join(d, "appdata")
        os.environ["XDG_CONFIG_HOME"] = os.path.join(d, "xdg")
        for _v in ("OPENAI_BASE_URL", "OPENAI_API_KEY"):
            os.environ.pop(_v, None)
        sys.path.insert(0, {str(PROJECT_ROOT)!r})
        sys.path.insert(0, {str(PROJECT_ROOT / "tests")!r})

        import tkinter as tk
        try:
            _root = tk.Tk()
        except Exception as e:
            print("NO_DISPLAY:" + str(e))
            raise SystemExit(97)
        _root.withdraw()

        # The plugin directories start with digits, and ui.py imports names
        # that plugin.py defines above its own `from .ui import ...`, so
        # plugin.py must be imported first.
        for _pkg, _sub in (("plugins.06_el", "06_el"),
                           ("plugins.07_il", "07_il"),
                           ("plugins.03_harmoniser", "03_harmoniser")):
            _spec = importlib.util.spec_from_file_location(
                _pkg, os.path.join({str(PROJECT_ROOT)!r}, "plugins", _sub,
                                   "__init__.py"),
                submodule_search_locations=[
                    os.path.join({str(PROJECT_ROOT)!r}, "plugins", _sub)])
            _m = importlib.util.module_from_spec(_spec)
            sys.modules[_pkg] = _m
            try:
                _spec.loader.exec_module(_m)
            except Exception:
                pass

        ELView = importlib.import_module("plugins.06_el.plugin").ELView
        ILView = importlib.import_module("plugins.07_il.plugin").ILView
        HarmoniserView = importlib.import_module(
            "plugins.03_harmoniser.plugin").HarmoniserView

        def frame():
            return tk.Frame(_root)

{textwrap.indent(textwrap.dedent(body), " " * 8)}

        print("SMOKE_OK")
    ''')
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(script)
        path = fh.name
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run([sys.executable, path], capture_output=True,
                           text=True, timeout=180, env=env,
                           cwd=str(PROJECT_ROOT))
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return p.returncode, p.stdout, p.stderr


def _smoke(body: str):
    rc, out, err = _run(body)
    if rc == 97 or "NO_DISPLAY:" in out:
        pytest.skip("no display: the real-Tk smoke is a ratchet, not a gate")
    assert rc == 0, f"exit {rc}\n--- stdout ---\n{out}\n--- stderr ---\n{err}"
    assert "SMOKE_OK" in out, out
    return out


class TestTheViewsCanBeBuiltAtAll:
    """The cheapest defect there is, and the suite could not see it."""

    def test_all_three_construct(self):
        out = _smoke('''
            for name, cls in (("ELView", ELView), ("ILView", ILView),
                              ("HarmoniserView", HarmoniserView)):
                cls(frame())
                print("built " + name)
        ''')
        for name in ("ELView", "ILView", "HarmoniserView"):
            assert "built " + name in out

    def test_a_second_construction_is_clean(self):
        """Two tabs of the same stage, and a rebuild after a provider
        change, both happen; module-level state must not make the second
        one different from the first."""
        _smoke('''
            ELView(frame()); ELView(frame())
            ILView(frame()); HarmoniserView(frame())
        ''')


class TestTheRunButtonAgreesWithReadiness:
    """Session B's list, items 2 to 4: drive the real widget, on the
    default path, and assert on the button rather than the function."""

    def test_a_fresh_install_offers_no_run(self):
        out = _smoke('''
            v = ELView(frame())
            print("label=" + repr(v.lbl_key.cget("text")))
            print("run=" + str(v.btn_run.cget("state")))
            assert str(v.btn_run.cget("state")) == "disabled"
        ''')
        assert "run=disabled" in out

    def test_a_configured_and_probed_stage_enables_run(self):
        """The assertion session B said no test in the suite could
        express: *with a bundle, a model and a configured provider, the
        Run button is enabled*."""
        out = _smoke('''
            from plugins._common import settings as S, provider_detect as pd
            S.update_settings(provider="local",
                              endpoint="http://localhost:11434/v1",
                              api_key="", model="qwen2.5:7b")
            pd.remember(pd.Detection(pd.READY, ("qwen2.5:7b",), "1 model.",
                                     "http://localhost:11434/v1"))
            v = ELView(frame())
            v.bundle_zip_path = "/tmp/not-really-a-bundle.zip"
            v._refresh_readiness_label(); v._set_controls_running(False)
            print("label=" + repr(v.lbl_key.cget("text")))
            print("run=" + str(v.btn_run.cget("state")))
            assert str(v.btn_run.cget("state")) == "normal"
            assert v.cmb_model.cget("values") == ("qwen2.5:7b",)
        ''')
        assert "run=normal" in out

    def test_an_unprobed_stage_endpoint_does_not_enable_run(self):
        """Session C's own defect, at the widget. The application probes
        its endpoint; EL points elsewhere; EL must not inherit the
        answer."""
        out = _smoke('''
            from helpers_fake_server import serve_models, dead_url
            from plugins._common import settings as S, provider_detect as pd
            app, stop = serve_models(["app-only"])
            try:
                S.update_settings(provider="custom", endpoint=app,
                                  model="m")
                S.set_stage_override("EL", endpoint=dead_url())
                pd.forget(); pd.refresh(app, provider="custom")
                v = ELView(frame())
                v.bundle_zip_path = "/tmp/b.zip"
                v._refresh_discovery(); v._refresh_readiness_label()
                v._set_controls_running(False)
                print("combobox=" + repr(v.cmb_model.cget("values")))
                print("run=" + str(v.btn_run.cget("state")))
                assert str(v.btn_run.cget("state")) == "disabled"
                assert "app-only" not in str(v.cmb_model.cget("values"))
            finally:
                stop()
        ''')
        assert "run=disabled" in out


class TestTheTabDoesNotPinWhatTheUserDidNotChoose:
    """Session C's other defect, at the widget rather than at the pure
    function — because the pure function was given the wrong baseline,
    and only the View knows what its own fields were seeded with."""

    def test_opening_a_tab_and_leaving_a_field_stores_nothing(self):
        out = _smoke('''
            import json
            from plugins._common import settings as S
            v = ELView(frame())
            v._stage_fields_edited()
            stages = S.load_settings()["stages"]
            print("stages=" + json.dumps(stages))
            assert stages == {}, stages
        ''')
        assert 'stages={}' in out

    def test_the_stage_the_user_opened_still_gets_the_local_batch_size(self):
        out = _smoke('''
            from plugins._common import settings as S
            from plugins._common.stage_state import LOCAL_BATCH_SIZE
            v = ELView(frame()); v._stage_fields_edited()
            S.update_settings(provider="local",
                              endpoint="http://localhost:11434/v1",
                              model="qwen2.5:7b")
            el = S.resolve_stage(S.load_settings(), "EL")
            il = S.resolve_stage(S.load_settings(), "IL")
            print("el=%s/%s il=%s/%s" % (el.batch_size, el.model,
                                         il.batch_size, il.model))
            assert el.batch_size == LOCAL_BATCH_SIZE
            assert (el.batch_size, el.model) == (il.batch_size, il.model)
        ''')
        assert "el=5/qwen2.5:7b il=5/qwen2.5:7b" in out


class TestTheLabelsFitAndTheControlsStayUsable:

    def test_the_model_control_is_editable_in_every_state(self):
        """"Discovery is an aid, never a gate", at the widget: after a
        failed list call the combobox must still accept typing."""
        out = _smoke('''
            from helpers_fake_server import dead_url
            from plugins._common import settings as S, provider_detect as pd
            S.update_settings(provider="local", endpoint=dead_url())
            pd.forget()
            pd.refresh(S.load_settings()["endpoint"], provider="local")
            v = ELView(frame()); v._refresh_discovery()
            state = str(v.cmb_model.cget("state"))
            print("combobox_state=" + state)
            assert state != "readonly" and state != "disabled"
            v.var_model.set("typed-by-hand")
            assert v.var_model.get() == "typed-by-hand"
        ''')
        assert "combobox_state=normal" in out

    def test_the_readiness_label_never_exceeds_the_widget(self):
        """The 16-character constraint, measured on the rendered label
        rather than on the pure function that produces it."""
        out = _smoke('''
            from plugins._common import settings as S, provider_detect as pd
            seen = []
            for cfg, probe in (
                ({}, None),
                ({"provider": "openai", "api_key": ""}, None),
                ({"provider": "local",
                  "endpoint": "http://localhost:11434/v1"}, None),
            ):
                if cfg: S.update_settings(**cfg)
                pd.forget()
                if probe: pd.remember(probe)
                v = ELView(frame()); v._refresh_readiness_label()
                text = v.lbl_key.cget("text")
                seen.append(text)
                assert len(text) <= 16, (text, len(text))
            print("labels=" + repr(seen))
        ''')
        assert "labels=" in out


class TestTheProviderDialogSurvivesItsOwnTeardown:
    """F-147. The smoke covered Views; this defect was in a dialog.

    The maintainer's traceback, every launch::

        File "metascreener/provider_dialog.py", line 174, in <lambda>
          self.after(0, lambda: self._status_arrived(found))
        File "metascreener/provider_dialog.py", line 180, in _status_arrived
          self.lbl_status.configure(text=found.detail or "Ready.")
        _tkinter.TclError: invalid command name ".!providerdialog.!frame.!label2"

    The detection thread completes after the dialog is destroyed and
    writes to a widget that no longer exists. This is the class the
    review passes have been hunting — a background thread touching Tk
    after teardown — and no existing test could see it: the normal suite
    replaces ``tkinter`` with a ``MagicMock``, under which
    ``configure`` on a destroyed widget is a no-op that returns a mock.
    Only a real Tk can fail here, so the answer to "should the smoke
    cover dialogs?" is yes, and this is it.

    **Tk swallows the failure**, which is why this needs care: an
    exception raised inside an ``after`` callback goes to
    ``report_callback_exception``, which prints a traceback and returns.
    The process still exits 0. A test that merely ran the callback would
    pass green while the defect fired in front of it, so the recorder
    below is not decoration — without it this test asserts nothing.
    """

    #: Both orderings, because they fail in different places. The first
    #: is the maintainer's: the callback is queued while the dialog is
    #: alive and runs after it is gone. The second is the race one step
    #: earlier: the dialog is already destroyed when the worker calls
    #: ``after`` at all, which raises in the worker thread.
    _PREAMBLE = '''
        import types, threading as real_threading
        import tkinter as tk
        import metascreener.provider_dialog as PD
        from plugins._common import provider_detect as pd

        errors = []
        _root.report_callback_exception = (
            lambda exc, val, tb: errors.append(f"{exc.__name__}: {val}"))

        class _Det:
            state = pd.NOT_RUNNING
            detail = "stubbed - no server was contacted"
            models = ()
            endpoint = "http://127.0.0.1:9/v1"
            can_use = False

        # No network. PD.pd is the shared module object, so this also
        # covers the `_offer_pull` path if it is ever reached.
        PD.pd.detect = lambda *a, **k: _Det()

        # Capture worker targets instead of running them, so the test
        # decides when the "thread" finishes relative to teardown.
        targets = []
        class _FakeThread:
            def __init__(self, target=None, daemon=None, **kw):
                targets.append(target)
            def start(self):
                pass

        # Event must survive: _offer_pull does threading.Event().
        PD.threading = types.SimpleNamespace(
            Thread=_FakeThread, Event=real_threading.Event)

        # grab_set raises on a window that is not yet viewable on some
        # machines, which would fail this test for an unrelated reason.
        tk.Misc.grab_set = lambda self: None

        def new_dialog():
            targets.clear()
            return PD.ProviderDialog(
                _root, settings={"provider": "local",
                                 "endpoint": "http://127.0.0.1:9/v1"})
    '''

    def test_a_probe_that_lands_after_destroy_does_not_raise(self):
        out = _smoke(self._PREAMBLE + '''
        dlg = new_dialog()
        assert targets, "constructing the dialog should start a detection worker"

        work = targets[-1]
        work()              # the worker finishes and queues its callback
        dlg.destroy()       # the user closes the dialog
        _root.update()      # Tk runs the queued callback on a dead widget

        print("errors=" + repr(errors))
        assert errors == [], errors
        ''')
        assert "errors=[]" in out

    def test_a_worker_returning_after_destroy_does_not_raise(self):
        out = _smoke(self._PREAMBLE + '''
        dlg = new_dialog()
        work = targets[-1]
        dlg.destroy()       # gone before the worker even calls after()
        work()              # must not raise in the worker thread
        _root.update()

        print("errors=" + repr(errors))
        assert errors == [], errors
        ''')
        assert "errors=[]" in out

    def test_the_dialog_still_reports_a_status_while_it_is_alive(self):
        """The guard must not be a mute button.

        A fix that swallowed everything would pass both tests above and
        leave the dialog permanently reading "Checking…".
        """
        out = _smoke(self._PREAMBLE + '''
        dlg = new_dialog()
        work = targets[-1]
        work()
        _root.update()
        text = dlg.lbl_status.cget("text")
        print("status=" + repr(text))
        assert "stubbed" in text, text
        assert errors == [], errors
        dlg.destroy()
        ''')
        assert "no server was contacted" in out


class TestTheProviderCanBeReCheckedWithoutRelaunching:
    """F-149. The probe ran once at launch and never again.

    The maintainer's Ollama server stopped; every LLM tab read
    "Unreachable" with its Run button dead; he restarted the server and
    the tabs still read "Unreachable" until he restarted the whole
    application. ``_refresh_provider_status`` has exactly two call sites,
    both one-shot, and ``metascreener/main.py`` contains no repeating
    ``after``, no polling loop and no re-check control of any kind.
    """

    _PREAMBLE = '''
        import types, threading as real_threading
        import tkinter as tk
        from plugins._common import provider_detect as pd
        from plugins._common import widgets as W
        from plugins._common import settings as S

        errors = []
        _root.report_callback_exception = (
            lambda exc, val, tb: errors.append(f"{exc.__name__}: {val}"))

        ENDPOINT = "http://127.0.0.1:9/v1"
        S.update_settings(provider="local", endpoint=ENDPOINT)

        # The server's answer, swapped between calls by the test.
        answers = {"state": pd.NOT_RUNNING}
        calls = []

        class _Det:
            def __init__(self, state):
                self.state = state
                self.models = ("m1",) if state == pd.READY else ()
                self.detail = "stub-" + state
                self.endpoint = ENDPOINT
                self.can_use = state == pd.READY

        def _fake_detect(endpoint, **kw):
            calls.append(endpoint)
            return _Det(answers["state"])

        pd.detect = _fake_detect

        # Run the "thread" inline so the test controls ordering. start()
        # is what RecheckButton calls; running the target there keeps the
        # button's own state machine honest.
        class _FakeThread:
            def __init__(self, target=None, daemon=None, **kw):
                self._target = target
            def start(self):
                self._target()
        W.threading = types.SimpleNamespace(
            Thread=_FakeThread, Event=real_threading.Event)
    '''

    def test_a_server_that_comes_back_is_noticed(self):
        """The maintainer's sequence, end to end, in the tab he was in.

        The server is down at launch, the launch probe records that, the
        server comes back, and the tab must be able to notice without the
        application being restarted.

        ``bundle_zip_path`` is set because ``llm_readiness`` checks ``has_bundle``
        ahead of everything else, so an unloaded tab reports "No bundle
        loaded" whatever the provider is doing. He had a bundle loaded;
        what was dead was the provider.
        """
        out = _smoke(self._PREAMBLE + '''
        S.update_settings(model="m1")

        # Launch: the server is not running, and the probe says so.
        answers["state"] = pd.NOT_RUNNING
        pd.forget()
        pd.refresh(ENDPOINT, api_key="", provider="local")

        v = ELView(frame())
        v.bundle_zip_path = "pretend.zip"
        v._refresh_readiness_label()
        before = v.lbl_key.cget("text")
        print("before=" + repr(before))
        assert not v._readiness().can_run, before

        # The user starts the server again. Before F-149 this state was
        # unreachable without relaunching the application.
        answers["state"] = pd.READY
        v.btn_recheck.invoke()
        _root.update()

        after = v.lbl_key.cget("text")
        print("after=" + repr(after))
        print("probes=" + repr(calls))
        assert v._readiness().can_run, after
        assert ENDPOINT in calls, calls
        assert errors == [], errors
        ''')
        assert "before='Unreachable'" in out
        assert "after='Ready to run'" in out

    def test_it_probes_only_this_tab_s_endpoint(self):
        """It must not call ``forget()``.

        The application-wide refresh drops the whole probe cache before
        re-probing, so reusing it here would send every other tab to
        NOT_CHECKED -- "Checking...", Run disabled -- because this one
        asked a question.
        """
        out = _smoke(self._PREAMBLE + '''
        pd.forget()
        pd.remember(_Det(pd.READY), "http://other.invalid/v1")

        v = ELView(frame())
        v.btn_recheck.invoke()
        _root.update()

        other = pd.last_known("http://other.invalid/v1")
        print("other_survived=" + repr(other is not None))
        assert other is not None, "another tab's probe was discarded"
        assert errors == [], errors
        ''')
        assert "other_survived=True" in out

    def test_all_three_tabs_have_one_and_it_works(self):
        """Clicked, not merely present.

        Each View resolves its endpoint differently -- EL and IL from a
        live widget, the harmoniser from the store -- so each has its own
        ``_reprobe_job``. A missing or misnamed helper on any of them is
        an AttributeError that only appears when the button is pressed,
        which is exactly the class of defect this file exists for.
        """
        out = _smoke(self._PREAMBLE + '''
        for name, V in (("EL", ELView), ("IL", ILView),
                        ("harmoniser", HarmoniserView)):
            calls.clear()
            v = V(frame())
            assert hasattr(v, "btn_recheck"), name
            v.btn_recheck.invoke()
            _root.update()
            print(name + "_text=" + repr(v.btn_recheck.cget("text")))
            print(name + "_probed=" + repr(len(calls)))
            assert len(calls) == 1, (name, calls)
            assert str(v.btn_recheck.cget("state")) != "disabled", name
        assert errors == [], errors
        ''')
        assert out.count("_text='Re-check'") == 3
        assert out.count("_probed=1") == 3

    def test_the_button_survives_the_tab_closing_under_it(self):
        """F-147's class, which this button could have re-opened.

        ``Plugin.on_close`` destroys a View without stopping its workers,
        and the Views carry no destroyed-widget guard of their own. A
        probe still in flight when the tab goes away must not write to a
        dead widget.
        """
        out = _smoke(self._PREAMBLE + '''
        # A thread that does NOT run inline, so the test can destroy the
        # View between the click and the worker finishing.
        held = []
        class _HeldThread:
            def __init__(self, target=None, daemon=None, **kw):
                held.append(target)
            def start(self):
                pass
        W.threading = types.SimpleNamespace(
            Thread=_HeldThread, Event=real_threading.Event)

        pd.forget()
        v = ELView(frame())
        v.btn_recheck.invoke()
        assert held, "the click should have started a worker"

        v.destroy()          # the tab closes while the probe is in flight
        held[-1]()           # the worker returns to a destroyed widget
        _root.update()

        print("errors=" + repr(errors))
        assert errors == [], errors
        ''')
        assert "errors=[]" in out


class TestARunIsDescribedBeforeItStarts:
    """F-151. ``_run_clicked`` began a long, sometimes billable operation
    with no record count, no request count, no estimate and no
    confirmation. The maintainer's run took hours."""

    _PREAMBLE = '''
        import tkinter.messagebox as MB
        from plugins._common import provider_detect as pd
        from plugins._common import run_estimate as RE
        from plugins._common import settings as S
        # The package name has a leading digit, so it cannot be
        # imported with a statement; the class knows its own module.
        ELUI = sys.modules[ELView.__module__]

        asked = {}
        def _fake_ask(title, text, **kw):
            asked["title"] = title
            asked["text"] = text
            return asked.get("answer", False)
        ELUI.messagebox.askyesno = _fake_ask
        ELUI.messagebox.showerror = lambda *a, **k: None

        # No network from the compute probe.
        pd.compute_mode = lambda endpoint, **kw: pd.ComputeMode(
            pd.COMPUTE_CPU, "This server is running the model on the CPU.")
        ELUI.compute_mode = pd.compute_mode
    '''

    def test_it_states_the_counts_and_can_be_declined(self):
        out = _smoke(self._PREAMBLE + '''
        RE.forget_rates()
        v = ELView(frame())

        class _C:
            enabled = True; operator = "llm"
        class _Crits:
            criteria = [_C(), _C()]
        class _Parse:
            rows = [{}] * 85
        class _B:
            criteria = _Crits(); parse = _Parse()
        v.bundle = _B()

        asked["answer"] = False
        started = v._confirm_run("llama3.2", 5)
        print("returned=" + repr(started))
        print("text=" + repr(asked["text"]))
        assert started is False, "declining must stop the run"
        for fragment in ("85", "170", "34", "llama3.2"):
            assert fragment in asked["text"], fragment
        assert "CPU" in asked["text"], "the compute mode must reach the user"
        assert "no basis for a time estimate" in asked["text"]
        ''')
        assert "returned=False" in out

    def test_a_measured_rate_becomes_a_duration(self):
        out = _smoke(self._PREAMBLE + '''
        RE.forget_rates()
        v = ELView(frame())

        class _C:
            enabled = True; operator = "llm"
        class _Crits:
            criteria = [_C(), _C()]
        class _Parse:
            rows = [{}] * 85
        class _B:
            criteria = _Crits(); parse = _Parse()
        v.bundle = _B()

        for _ in range(3):
            RE.remember_call(v._effective_endpoint(), "llama3.2", 30.0)

        asked["answer"] = True
        assert v._confirm_run("llama3.2", 5) is True
        print("text=" + repr(asked["text"]))
        assert "17 minutes" in asked["text"], asked["text"]
        ''')
        assert "17 minutes" in out


class TestTheExclusionPolicyHasAControl:
    """F-153. F-145 shipped a policy the README calls user-changeable and
    the engine's own log line told the user to change "in the provider
    settings" — while **no widget anywhere could write it**.

    That is F-91's shape exactly: the defect where the documentation
    described an endpoint the user could configure and no control bound
    it. A setting reachable only by hand-editing JSON in ``%APPDATA%`` is
    not user-changeable in a GUI-first application.
    """

    _PREAMBLE = '''
        import types, threading as real_threading
        import tkinter as tk
        import metascreener.provider_dialog as PD
        from plugins._common import provider_detect as pd
        from plugins._common import settings as S

        class _Det:
            state = pd.NOT_RUNNING; models = (); detail = "stub"
            endpoint = ""; can_use = False
        PD.pd.detect = lambda *a, **k: _Det()
        class _FakeThread:
            def __init__(self, target=None, daemon=None, **kw): pass
            def start(self): pass
        PD.threading = types.SimpleNamespace(
            Thread=_FakeThread, Event=real_threading.Event)
        tk.Misc.grab_set = lambda self: None
    '''

    def test_an_untouched_box_follows_the_provider(self):
        """Tri-state preserved: opening and accepting without touching the
        box must leave the provider deciding, not freeze today's answer."""
        out = _smoke(self._PREAMBLE + '''
        for provider, expected_ticked in (("local", False), ("custom", False),
                                          ("openai", True)):
            d = PD.ProviderDialog(_root, settings={"provider": provider})
            ticked = bool(d.var_allow_exclusion.get())
            d._accept()
            print(provider + "_ticked=" + repr(ticked))
            print(provider + "_stored=" + repr(d.result["allow_llm_exclusion"]))
            assert ticked is expected_ticked, provider
            assert d.result["allow_llm_exclusion"] is None, (
                "an untouched checkbox must store None, not a boolean")
        ''')
        assert "local_ticked=False" in out
        assert "openai_ticked=True" in out
        assert out.count("_stored=None") == 3

    def test_switching_provider_moves_an_untouched_box(self):
        out = _smoke(self._PREAMBLE + '''
        d = PD.ProviderDialog(_root, settings={"provider": "openai"})
        assert d.var_allow_exclusion.get() is True
        d.var_provider.set("local")
        d._on_provider_changed()
        print("after_switch=" + repr(bool(d.var_allow_exclusion.get())))
        assert d.var_allow_exclusion.get() is False
        d.destroy()
        ''')
        assert "after_switch=False" in out

    def test_ticking_it_reaches_the_engine(self):
        """End to end: the box, the store, and what the engine will do."""
        out = _smoke(self._PREAMBLE + '''
        from plugins._common.llm_client import llm_exclusion_allowed

        d = PD.ProviderDialog(_root, settings={"provider": "local"})
        d.var_allow_exclusion.set(True)
        d._on_exclusion_toggled()
        d._accept()
        print("stored=" + repr(d.result["allow_llm_exclusion"]))
        assert d.result["allow_llm_exclusion"] is True

        S.update_settings(**d.result)
        print("engine_allows=" + repr(llm_exclusion_allowed("EL")))
        assert llm_exclusion_allowed("EL") is True, (
            "the user permitted exclusion and the engine did not hear it")
        ''')
        assert "engine_allows=True" in out

    def test_unticking_it_forbids_exclusion_on_openai(self):
        """Both directions. A user who does not trust their configuration
        must be able to turn exclusion off for a paid provider too."""
        out = _smoke(self._PREAMBLE + '''
        from plugins._common.llm_client import llm_exclusion_allowed

        d = PD.ProviderDialog(_root, settings={"provider": "openai"})
        d.var_allow_exclusion.set(False)
        d._on_exclusion_toggled()
        d.var_key.set("sk-test-key")
        d._accept()
        S.update_settings(**d.result)
        print("engine_allows=" + repr(llm_exclusion_allowed("EL")))
        assert llm_exclusion_allowed("EL") is False
        ''')
        assert "engine_allows=False" in out

    def test_the_measurement_is_stated_beside_the_control(self):
        """A checkbox offering to turn off a safety gate without saying
        what the gate is for is a checkbox that gets turned off."""
        out = _smoke(self._PREAMBLE + '''
        d = PD.ProviderDialog(_root, settings={"provider": "local"})
        text = d.lbl_exclude.cget("text")
        print("len=" + str(len(text)))
        for fragment in ("40", "43", "gpt-4o-mini", "llama3.2:latest",
                         "the audited run kept", "quote", "temperature 0"):
            assert fragment in text, fragment
        # The label must not re-assert the claim d5ad13e retracted: nobody
        # audited the 40 and 43, so the dialog may not tell a user they were
        # all unjustified. It says what the artefacts support instead.
        assert "unjustified" not in text
        d.destroy()
        ''')
        assert "len=" in out


class TestTheCriterionDrillDownsRunAtAll:
    """F-161(c). Four drill-down sites were fixed and none was executed.

    Traced with ``sys.settrace`` over a full run of ``test_flag_only.py``:
    ``_refresh_reports_view`` never called, ``on_criterion_doubleclick``
    never called. Re-inlining the old four-name predicate in **both** Views
    left that file green at 117 passed. The tests applied the predicate the
    way a drill-down would; nothing drove a drill-down.

    They could not, in-process: ``conftest`` makes ``ttk.Frame`` a
    ``MagicMock``, so ``class StandaloneELPlugin(ttk.Frame)`` is not a class
    and cannot be instantiated. Real Tk is the only place these methods
    exist as methods, which is why this lives here.

    The rows and lists below come from a **real engine run** via
    ``tests/_engine_probe.py``. A hand-written ``row_eval_lists`` would be
    wave 11 session B's defect committed inside the test written to close a
    vocabulary defect.
    """

    _SETUP = """
        import importlib
        import _engine_probe as EP
    """

    @pytest.mark.parametrize("stage,pkg,cls,ctype,decision", [
        ("EL", "plugins.06_el", "StandaloneELPlugin", "exclude", "meet"),
        ("IL", "plugins.07_il", "StandaloneILPlugin", "include", "not_meet"),
    ])
    def test_the_standalone_drilldown_shows_suppressed_records(
            self, stage, pkg, cls, ctype, decision):
        """The two sites F-156's repair did not reach.

        Measured before this fix, driving the real engine and applying the
        standalone predicate verbatim: ``criterion_touched`` gave 4 of 4 and
        the standalone gave **0 of 4**. It filtered the exported ``*_ids``
        columns, and F-145 added no ``*_suppressed_ids`` column, so those
        columns could not answer the question at all.
        """
        out = _smoke(self._SETUP + """
        plugin = importlib.import_module("%s.plugin")
        full, evals, cid = EP.run_flag_only(plugin, "%s", "%s", "%s")
        print("records=" + str(len(full)))

        standalone = importlib.import_module("%s.standalone")
        view = standalone.%s(frame())
        view.full_rows = full
        view.row_eval_lists = evals
        view.bundle = object()

        shown = []
        view.table.set_rows = lambda rows: shown.append(list(rows))
        view.lst_crit.curselection = lambda: (0,)
        view.lst_crit.get = lambda _i: cid + "  (llm)"

        view.on_criterion_doubleclick()

        print("shown=" + str(len(shown[-1]) if shown else 0))
        assert shown, "the drill-down never reached the table"
        assert len(shown[-1]) == len(full) == 4
        view.destroy()
        """ % (pkg, stage, ctype, decision, pkg, cls))
        assert "records=4" in out
        assert "shown=4" in out, out

    @pytest.mark.parametrize("stage,pkg,cls,ctype,decision", [
        ("EL", "plugins.06_el", "ELView", "exclude", "meet"),
        ("IL", "plugins.07_il", "ILView", "include", "not_meet"),
    ])
    def test_the_view_drilldown_shows_suppressed_records(
            self, stage, pkg, cls, ctype, decision):
        """The four sites F-156 *did* fix, now actually executed.

        This is the one that was green for the wrong reason: the fix was
        real and the test that certified it never ran the code.
        """
        out = _smoke(self._SETUP + """
        plugin = importlib.import_module("%s.plugin")
        full, evals, cid = EP.run_flag_only(plugin, "%s", "%s", "%s")

        import types
        view = plugin.%s(frame())
        view.full_rows = full
        view.row_eval_lists = evals
        view.survivors = [dict(r) for r in full]
        view.active_criterion_id = cid
        # Scaffolding, not the state under test: the method reads the
        # bundle only for its column names, and returns early without one.
        # What must come from the engine is row_eval_lists, and it does.
        view.bundle = types.SimpleNamespace(parse=types.SimpleNamespace(
            header=["local_id", "title", "abstract", "keywords"]))

        shown = {}
        for name in ("full_table", "surv_table"):
            tbl = getattr(view, name)
            tbl.render_rows_incremental = (
                lambda n: lambda rows: shown.__setitem__(n, list(rows)))(name)

        view._refresh_reports_view()
        print("full_shown=" + str(len(shown.get("full_table", []))))
        assert len(shown.get("full_table", [])) == 4, shown
        view.destroy()
        """ % (pkg, stage, ctype, decision, cls))
        assert "full_shown=4" in out, out


class TestComputeModeDoesNotFreezeTheApplication:
    """F-162. F-157 bounded the body and left the headers.

    ``urlopen`` returns only after the status line and **every header** have
    been read, and ``_read_bounded`` runs inside the ``with`` block — so a
    server that dribbles header bytes, each arriving inside the
    per-operation socket timeout, was bounded by nothing. Measured at
    ``timeout=1.0``: 8 padding bytes held the call 4.28 s, 40 held it
    12.29 s, 120 held it 32.33 s. Linear in header size, independent of the
    timeout, every one returning a confident answer.

    ``ELView._confirm_run`` calls this **on the GUI thread**, deliberately —
    the pre-run confirmation must have the answer before the user decides.
    So the measurement that matters is not elapsed seconds in a unit test;
    it is whether Tk kept processing events. That is what this asserts, and
    it is why it lives in the real-Tk file rather than in
    ``test_compute_mode.py``, whose server uses ``end_headers()`` and emits
    every header in a single write — which is exactly why the wave's own
    regression test could not see this.
    """

    def test_a_header_dribbling_server_does_not_stop_the_mainloop(self):
        out = _smoke(r"""
        import socket, threading, time
        from plugins._common import provider_detect as pd

        # Answers the status line at once, then dribbles one header line at
        # a time, every gap comfortably inside the socket timeout so
        # urlopen's own timeout can never fire.
        GAP = 0.30
        PAD = 60

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        CRLF = bytes([13, 10])

        def serve():
            try:
                conn, _ = srv.accept()
                conn.recv(65535)
                conn.sendall(b'HTTP/1.1 200 OK' + CRLF)
                for i in range(PAD):
                    conn.sendall(('X-Pad-%d: y' % i).encode() + CRLF)
                    time.sleep(GAP)
                body = b'{"models": []}'
                conn.sendall(
                    ('Content-Length: %d' % len(body)).encode()
                    + CRLF + CRLF)
                conn.sendall(body)
                conn.close()
            except Exception:
                pass
        threading.Thread(target=serve, daemon=True).start()

        TIMEOUT = 2.0
        ticks = []
        gaps = []

        def tick():
            now = time.monotonic()
            if ticks:
                gaps.append(now - ticks[-1])
            ticks.append(now)
            _root.after(100, tick)

        result = {}

        def call():
            t0 = time.monotonic()
            result["mode"] = pd.compute_mode(
                "http://127.0.0.1:%d/v1" % port, timeout=TIMEOUT)
            result["elapsed"] = time.monotonic() - t0
            _root.after(300, _root.quit)

        _root.after(100, tick)
        _root.after(200, call)
        _root.mainloop()

        worst = max(gaps) if gaps else 0.0
        print("elapsed=%.2f" % result["elapsed"])
        print("worst_gap=%.2f" % worst)
        print("ticks=%d" % len(ticks))
        print("mode=" + result["mode"].mode)

        # The unbounded header phase would have been PAD * GAP = 18s.
        assert result["elapsed"] < TIMEOUT * 2.5, result["elapsed"]
        # And the GUI must have kept running: the call blocks its thread for
        # at most the budget, so no gap between 100ms ticks may approach the
        # 18s the server was willing to take.
        assert worst < TIMEOUT * 2.5, worst
        assert len(ticks) > 3, ticks
        # "We could not say" is the honest answer and a first-class state --
        # never COMPUTE_CPU.
        assert result["mode"].mode == pd.COMPUTE_UNKNOWN, result["mode"]
        """)
        assert "mode=unknown" in out, out
