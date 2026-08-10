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
