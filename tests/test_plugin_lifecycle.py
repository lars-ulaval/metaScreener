# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_plugin_lifecycle.py - Plugin entry-point resolution and lifecycle hooks.

Regression cover for F-18. metascreener/main.py set self._plugins = [] and
never appended to it, so _on_tab_changed and _on_close iterated an empty
list and the BasePlugin lifecycle declared in metascreener/plugin_api.py
never ran. Four plugins implement on_close and Plugin 02 implements
on_unload to cancel its resolve/fetch worker; none of them was ever called,
so closing the window mid-run left the thread alive.

resolve_plugin_entrypoint now returns the instance it built (it used to be
discarded), and notify_plugin dispatches the hooks. Both are module-level
so they can be exercised without a Tk root - this module was at 0%
coverage.
"""
import importlib.util
import sys
import types

import pytest

from conftest import PROJECT_ROOT


def _load_main():
    """Import metascreener/main.py under conftest's tkinter mocks."""
    ms = sys.modules.get("metascreener")
    if ms is None:
        ms = types.ModuleType("metascreener")
        sys.modules["metascreener"] = ms
    if not hasattr(ms, "__path__"):
        ms.__path__ = [str(PROJECT_ROOT / "metascreener")]
    spec = importlib.util.spec_from_file_location(
        "metascreener.main", str(PROJECT_ROOT / "metascreener" / "main.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["metascreener.main"] = mod
    spec.loader.exec_module(mod)
    return mod


main = _load_main()

PARENT = object()  # resolve_plugin_entrypoint only passes this through


class _Frame:
    pass


def _module(**attrs):
    mod = types.ModuleType(attrs.pop("__name__", "fake_plugin"))
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


# --------------------------------------------------------------------------
# resolve_plugin_entrypoint
# --------------------------------------------------------------------------

class TestResolveReturnsTheInstance:

    def test_plugin_class_strategy_returns_instance_and_frame(self):
        frame = _Frame()

        class Plugin:
            def __init__(self, app=None, meta=None):
                self.app = app

            def build_tab(self, parent):
                return frame

        inst, got, title = main.resolve_plugin_entrypoint(
            _module(Plugin=Plugin, TAB_TITLE="Tab"), PARENT, app="APP"
        )
        assert got is frame
        assert isinstance(inst, Plugin), "the instance must not be discarded (F-18)"
        assert inst.app == "APP"
        assert title == "Tab"

    def test_make_plugin_strategy_returns_instance(self):
        frame = _Frame()

        class P:
            def build_tab(self, parent):
                return frame

        made = P()
        inst, got, _title = main.resolve_plugin_entrypoint(
            _module(make_plugin=lambda app: made, TAB_TITLE="T"), PARENT
        )
        assert got is frame
        assert inst is made

    def test_fallback_scan_returns_instance(self):
        frame = _Frame()

        class SomeView:
            def build_tab(self, parent):
                return frame

        inst, got, _title = main.resolve_plugin_entrypoint(
            _module(SomeView=SomeView, TAB_TITLE="T"), PARENT
        )
        assert got is frame
        assert isinstance(inst, SomeView)

    def test_module_level_build_tab_has_no_instance(self):
        """The one strategy with nothing to hang a lifecycle on."""
        frame = _Frame()
        mod = _module(build_tab=lambda parent, **kw: frame, TAB_TITLE="T")
        inst, got, _title = main.resolve_plugin_entrypoint(mod, PARENT)
        assert got is frame
        assert inst is None

    def test_failure_yields_no_frame(self):
        inst, frame, title = main.resolve_plugin_entrypoint(_module(), PARENT)
        assert frame is None
        assert inst is None
        assert title == "Plugin"

    def test_raising_constructor_does_not_leak_a_half_built_instance(self):
        class Plugin:
            def __init__(self, *a, **kw):
                raise RuntimeError("boom")

        inst, frame, _title = main.resolve_plugin_entrypoint(
            _module(Plugin=Plugin), PARENT
        )
        assert inst is None and frame is None


class TestTitleResolution:

    def test_module_tab_title_is_used(self):
        _i, _f, title = main.resolve_plugin_entrypoint(
            _module(TAB_TITLE="  Screen A - EH  "), PARENT
        )
        assert title == "Screen A - EH"

    def test_default_title_when_absent(self):
        assert main._title_from(_module()) == "Plugin"


# --------------------------------------------------------------------------
# notify_plugin
# --------------------------------------------------------------------------

class _Recorder:
    def __init__(self, *hooks):
        self.calls = []
        for h in hooks:
            setattr(self, h, (lambda name=h: self.calls.append(name)))


class TestNotifyPlugin:

    def test_calls_the_hook_when_present(self):
        p = _Recorder("on_close")
        assert main.notify_plugin(p, "on_close") is True
        assert p.calls == ["on_close"]

    def test_calls_every_matching_hook(self):
        """on_close is the contract; on_unload is Plugin 02's worker cancel."""
        p = _Recorder("on_close", "on_unload")
        main.notify_plugin(p, "on_close", "on_unload")
        assert p.calls == ["on_close", "on_unload"]

    def test_tolerates_a_missing_hook(self):
        p = _Recorder("on_unload")
        assert main.notify_plugin(p, "on_close", "on_unload") is True
        assert p.calls == ["on_unload"]

    def test_none_plugin_is_a_noop(self):
        assert main.notify_plugin(None, "on_close") is False

    def test_a_raising_hook_does_not_propagate(self):
        class Boom:
            def on_close(self):
                raise RuntimeError("nope")

        assert main.notify_plugin(Boom(), "on_close") is False

    def test_one_raising_hook_does_not_block_the_others(self):
        calls = []

        class Mixed:
            def on_close(self):
                raise RuntimeError("nope")

            def on_unload(self):
                calls.append("on_unload")

        main.notify_plugin(Mixed(), "on_close", "on_unload")
        assert calls == ["on_unload"], "a failing hook must not strand the worker"


# --------------------------------------------------------------------------
# The registration itself
# --------------------------------------------------------------------------

class TestPluginsListIsPopulated:
    """The F-18 defect proper, checked statically.

    _load_plugins builds each tab inside a Tk notebook, so exercising it
    directly needs a display. What can be checked headlessly is the thing
    that was actually wrong: the method never wrote to self._plugins, so
    the list _on_tab_changed and _on_close iterate was always empty. This
    test fails against the pre-fix main.py.
    """

    def _load_plugins_source(self):
        import ast

        src = (PROJECT_ROOT / "metascreener" / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_load_plugins":
                return node
        pytest.fail("_load_plugins not found in metascreener/main.py")

    def test_load_plugins_appends_to_self_plugins(self):
        import ast

        node = self._load_plugins_source()
        appends = [
            n for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "append"
            and isinstance(n.func.value, ast.Attribute)
            and n.func.value.attr == "_plugins"
        ]
        assert appends, (
            "_load_plugins never appends to self._plugins, so the list that "
            "_on_tab_changed and _on_close iterate stays empty and no plugin "
            "lifecycle hook is ever called (F-18)"
        )

    def test_close_handler_dispatches_hooks(self):
        import ast

        src = (PROJECT_ROOT / "metascreener" / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_on_close":
                body = ast.dump(node)
                assert "on_unload" in body, (
                    "_on_close must also fire on_unload: that is the hook "
                    "Plugin 02 uses to cancel its worker thread"
                )
                return
        pytest.fail("_on_close not found")


# --------------------------------------------------------------------------
# The real plugins
# --------------------------------------------------------------------------

class TestShippedPluginsExposeHooks:

    def test_plugin_02_worker_cancellation_hook_is_reachable(self):
        """The concrete leak F-18 describes: on_unload -> view.on_stop()."""
        from conftest import _import_plugin

        mod = _import_plugin("02_references_of_x")
        inst = mod.RefXPlugin(app=None, meta=None)
        assert callable(getattr(inst, "on_unload", None))
        assert main.notify_plugin(inst, "on_close", "on_unload") is True

    @pytest.mark.parametrize("subdir", ["03_harmoniser", "04_eh", "05_ih", "06_el", "07_il"])
    def test_on_close_is_reachable(self, subdir):
        from conftest import _import_plugin

        mod = _import_plugin(subdir)
        cls = getattr(mod, "Plugin", None) or getattr(mod, "HarmoniserPlugin")
        inst = cls(None, None)
        assert main.notify_plugin(inst, "on_close", "on_unload") is True
