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

    def test_all_three_tabs_have_one(self):
        out = _smoke('''
        for name, V in (("EL", ELView), ("IL", ILView),
                        ("harmoniser", HarmoniserView)):
            v = V(frame())
            assert hasattr(v, "btn_recheck"), name
            print(name + "_text=" + repr(v.btn_recheck.cget("text")))
        ''')
        assert out.count("_text='Re-check'") == 3

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
