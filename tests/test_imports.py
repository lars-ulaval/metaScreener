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
        import prisma_hub.plugin_api as api
        assert hasattr(api, "BasePlugin")
        assert hasattr(api, "PluginMeta")

    def test_import_plugin_manager(self):
        """Load plugin_manager directly from file (avoids conftest mock)."""
        import importlib.util
        from conftest import PROJECT_ROOT
        pm_path = PROJECT_ROOT / "prisma_hub" / "plugin_manager.py"
        spec = importlib.util.spec_from_file_location("prisma_hub.plugin_manager", str(pm_path))
        pm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pm)
        assert hasattr(pm, "_sanitize")

    def test_sanitizer_strips_bom(self):
        import importlib.util
        from conftest import PROJECT_ROOT
        pm_path = PROJECT_ROOT / "prisma_hub" / "plugin_manager.py"
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
        pm_path = PROJECT_ROOT / "prisma_hub" / "plugin_manager.py"
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
