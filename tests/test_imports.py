# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_imports.py — Module import smoke tests.

Verifies that core modules and plugin modules load successfully
on Linux/macOS without an X server (headless). This is evidence
for JORS requirement #4 (UNIX-based system testing).
"""
import sys
import platform

import pytest


class TestCoreImports:
    """Verify that core framework modules import cleanly."""

    def test_import_plugin_api(self):
        # plugin_api is mocked by conftest for headless compat;
        # verify our mock exposes the right interface
        import metascreener.plugin_api as api
        assert hasattr(api, "BasePlugin")
        assert hasattr(api, "PluginMeta")

    def test_import_plugin_manager(self):
        """Load plugin_manager directly from file (avoids conftest mock)."""
        import importlib.util
        from conftest import PROJECT_ROOT
        pm_path = PROJECT_ROOT / "metascreener" / "plugin_manager.py"
        spec = importlib.util.spec_from_file_location("metascreener.plugin_manager", str(pm_path))
        pm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pm)
        assert hasattr(pm, "_sanitize")

    def test_sanitizer_strips_bom(self):
        import importlib.util
        from conftest import PROJECT_ROOT
        pm_path = PROJECT_ROOT / "metascreener" / "plugin_manager.py"
        spec = importlib.util.spec_from_file_location("_pm_test", str(pm_path))
        pm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pm)
        src = "\ufeffimport os\nprint('hello')"
        clean = pm._sanitize(src)
        assert not clean.startswith("\ufeff")
        assert "import os" in clean

    def test_sanitizer_strips_future_annotations(self):
        import importlib.util
        from conftest import PROJECT_ROOT
        pm_path = PROJECT_ROOT / "metascreener" / "plugin_manager.py"
        spec = importlib.util.spec_from_file_location("_pm_test2", str(pm_path))
        pm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pm)
        src = "from __future__ import annotations\nimport os\n"
        clean = pm._sanitize(src)
        assert "from __future__" not in clean
        assert "import os" in clean


class TestPluginImports:
    """Verify that plugin modules import successfully (headless)."""

    def test_harmoniser_loads(self):
        from conftest import get_harmoniser
        mod = get_harmoniser()
        assert hasattr(mod, "_parse_free_text_criteria")
        assert hasattr(mod, "_infer_criterion_details")

    def test_eh_loads(self):
        from conftest import get_eh
        mod = get_eh()
        assert hasattr(mod, "_eval_criterion")
        assert hasattr(mod, "Criterion")

    def test_el_loads(self):
        from conftest import get_el
        mod = get_el()
        assert hasattr(mod, "_quote_in_text")
        assert hasattr(mod, "_cache_key")
        assert hasattr(mod, "PROMPT_VERSION")


class TestSharedHelpersOrigin:
    """Regression tests for Conv 6 / Commit 1 (f3fa6bb).

    The original Commit 1 apply script left orphaned local definitions of
    ``run_m1_llm_for_criterion``, ``_build_llm_messages_for_criterion``, and
    ``_parse_llm_json_array`` inside plugins/06_el/plugin.py and
    plugins/07_il/plugin.py. Those locals shadowed the imports from
    plugins/_common/llm_client and lacked the new ``stage`` keyword
    parameter. Production calls would have TypeError'd; the byte-identity
    tests masked the bug because their fully-cached paths never invoked
    ``run_m1_llm_for_criterion``.

    These tests assert that EL/IL plugin modules expose the SHARED versions
    of the LLM helpers (origin: plugins._common.llm_client), not local
    re-definitions. They would have caught the original incomplete
    extraction.
    """

    SHARED_FN_NAMES = (
        "run_m1_llm_for_criterion",
        "_parse_llm_json_array",
        "_make_item_for_llm",
        "_row_target_text_hash",
        "_load_cache_from_jsonl",
        "_dump_cache_to_jsonl",
        "_quote_in_text",
        "_sha_text",
        "_normalize_space",
        "_has_openai_key",
        "chunked",
    )

    def _check_origin(self, mod, fn_name):
        fn = getattr(mod, fn_name, None)
        assert fn is not None, f"{mod.__name__} missing {fn_name}"
        assert fn.__module__ == "plugins._common.llm_client", (
            f"{mod.__name__}.{fn_name} resolves to {fn.__module__!r}, "
            f"expected 'plugins._common.llm_client'. A local re-definition "
            f"is shadowing the import (Conv 6 / Commit 1 bug class)."
        )

    def test_el_helpers_resolve_to_common(self):
        from conftest import get_el
        mod = get_el()
        for name in self.SHARED_FN_NAMES:
            self._check_origin(mod, name)

    def test_il_helpers_resolve_to_common(self):
        from conftest import get_il
        mod = get_il()
        for name in self.SHARED_FN_NAMES:
            self._check_origin(mod, name)

    def test_run_m1_llm_accepts_stage_kwarg_el(self):
        """Direct check: the function bound to el.run_m1_llm_for_criterion
        must accept the ``stage`` and ``build_messages`` keyword parameters
        introduced in Commit 1 and Commit 2 respectively."""
        import inspect
        from conftest import get_el
        sig = inspect.signature(get_el().run_m1_llm_for_criterion)
        assert "stage" in sig.parameters, (
            "el.run_m1_llm_for_criterion lacks the 'stage' parameter; "
            "a stale local definition is shadowing the shared import."
        )
        assert "build_messages" in sig.parameters, (
            "el.run_m1_llm_for_criterion lacks the 'build_messages' parameter "
            "(Conv 6 / Commit 2 contract). A stale local definition is "
            "shadowing the shared import, or _common/llm_client.py is out of date."
        )

    def test_run_m1_llm_accepts_stage_kwarg_il(self):
        import inspect
        from conftest import get_il
        sig = inspect.signature(get_il().run_m1_llm_for_criterion)
        assert "stage" in sig.parameters, (
            "il.run_m1_llm_for_criterion lacks the 'stage' parameter; "
            "a stale local definition is shadowing the shared import."
        )
        assert "build_messages" in sig.parameters, (
            "il.run_m1_llm_for_criterion lacks the 'build_messages' parameter "
            "(Conv 6 / Commit 2 contract). A stale local definition is "
            "shadowing the shared import, or _common/llm_client.py is out of date."
        )


class TestPerPluginPrompts:
    """Conv 6 / Commit 2 contract: PROMPT_VERSION and the prompt builder
    live in per-plugin ``prompt.py`` modules so EL and IL prompts can
    evolve independently. The plugin-level ``__module__`` of the prompt
    builder must point to the per-plugin module, not to ``_common``.

    These tests would catch a regression that accidentally moved the
    prompt builder back into ``_common/llm_client.py`` (re-coupling the
    two stages' prompts) or that forgot to wire the per-plugin re-exports
    through ``plugin.py``.
    """

    def test_el_prompt_module_origin(self):
        from conftest import get_el
        mod = get_el()
        fn = mod._build_llm_messages_for_criterion
        assert fn.__module__ == "plugins.06_el.prompt", (
            f"el._build_llm_messages_for_criterion resolves to {fn.__module__!r}, "
            f"expected 'plugins.06_el.prompt'."
        )

    def test_il_prompt_module_origin(self):
        from conftest import get_il
        mod = get_il()
        fn = mod._build_llm_messages_for_criterion
        assert fn.__module__ == "plugins.07_il.prompt", (
            f"il._build_llm_messages_for_criterion resolves to {fn.__module__!r}, "
            f"expected 'plugins.07_il.prompt'."
        )

    def test_el_prompt_version_string(self):
        from conftest import get_el
        assert get_el().PROMPT_VERSION == "EL_v1_jsonlist"

    def test_il_prompt_version_string(self):
        from conftest import get_il
        assert get_il().PROMPT_VERSION == "IL_v1_jsonlist"


class TestPerPluginUI:
    """Conv 6 / Commit 3 contract: View classes live in per-plugin
    ``ui.py`` modules, not inside ``plugin.py``. The plugin module
    re-exports them so el.ELView and il.ILView remain reachable.

    Implementation note: the test environment mocks tkinter (see the
    ``MagicMock`` usage in ``conftest.py``), which means ``ttk.Frame``
    is a MagicMock and ``class ELView(ttk.Frame)`` produces a MagicMock-
    like object, NOT a real class. So we cannot use ``__module__`` for
    introspection. Instead we inspect the source files at the AST level
    to assert which file each class is defined in.

    These tests would catch a regression that accidentally moved a View
    class back into ``plugin.py``, or that left an orphan copy of it
    there during extraction.
    """

    def _class_defs_in(self, path):
        import ast
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        return {n.name for n in ast.iter_child_nodes(tree) if isinstance(n, ast.ClassDef)}

    def test_el_view_in_ui_not_plugin(self):
        from conftest import PROJECT_ROOT
        ui_classes = self._class_defs_in(PROJECT_ROOT / "plugins" / "06_el" / "ui.py")
        plugin_classes = self._class_defs_in(PROJECT_ROOT / "plugins" / "06_el" / "plugin.py")
        standalone_classes = self._class_defs_in(PROJECT_ROOT / "plugins" / "06_el" / "standalone.py")
        assert "ELView" in ui_classes, "ELView must be defined in plugins/06_el/ui.py"
        assert "ELView" not in plugin_classes, (
            "ELView must NOT be defined in plugins/06_el/plugin.py "
            "(orphan from incomplete Commit 3 extraction)"
        )
        # Conv 6 / Commit 4: StandaloneELPlugin moved out of ui.py
        # into its own standalone.py.
        assert "StandaloneELPlugin" in standalone_classes, (
            "StandaloneELPlugin must be defined in plugins/06_el/standalone.py "
            "(Conv 6 / Commit 4)"
        )
        assert "StandaloneELPlugin" not in ui_classes, (
            "StandaloneELPlugin must NOT be in plugins/06_el/ui.py after Commit 4"
        )
        assert "StandaloneELPlugin" not in plugin_classes
        assert "DataTable" in ui_classes
        assert "DataTable" not in plugin_classes
        assert "DataTable" not in standalone_classes

    def test_il_view_in_ui_not_plugin(self):
        from conftest import PROJECT_ROOT
        ui_classes = self._class_defs_in(PROJECT_ROOT / "plugins" / "07_il" / "ui.py")
        plugin_classes = self._class_defs_in(PROJECT_ROOT / "plugins" / "07_il" / "plugin.py")
        standalone_classes = self._class_defs_in(PROJECT_ROOT / "plugins" / "07_il" / "standalone.py")
        assert "ILView" in ui_classes, "ILView must be defined in plugins/07_il/ui.py"
        assert "ILView" not in plugin_classes, (
            "ILView must NOT be defined in plugins/07_il/plugin.py "
            "(orphan from incomplete Commit 3 extraction)"
        )
        # Conv 6 / Commit 4: StandaloneILPlugin moved out of ui.py.
        assert "StandaloneILPlugin" in standalone_classes
        assert "StandaloneILPlugin" not in ui_classes
        assert "StandaloneILPlugin" not in plugin_classes
        assert "DataTable" in ui_classes
        assert "DataTable" not in plugin_classes
        assert "DataTable" not in standalone_classes

    def test_el_view_reachable_via_plugin_module(self):
        """Smoke check: the plugin module must re-export ELView so existing
        consumers (Plugin.build_tab, tests) can reach it via plugin
        namespace, even though it's now defined in ui.py."""
        from conftest import get_el
        mod = get_el()
        assert hasattr(mod, "ELView")
        assert hasattr(mod, "StandaloneELPlugin")

    def test_il_view_reachable_via_plugin_module(self):
        from conftest import get_il
        mod = get_il()
        assert hasattr(mod, "ILView")
        assert hasattr(mod, "StandaloneILPlugin")


class TestEnvironmentInfo:
    """Report environment info (not assertions — for CI logs)."""

    def test_python_version(self):
        major, minor = sys.version_info[:2]
        assert major == 3 and minor >= 10, f"Requires Python 3.10+, got {major}.{minor}"

    def test_platform_info(self, capsys):
        print(f"\nPlatform: {platform.platform()}")
        print(f"Python: {sys.version}")
        print(f"Architecture: {platform.machine()}")
        # Always passes — informational only
        assert True
