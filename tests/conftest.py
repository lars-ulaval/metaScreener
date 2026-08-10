# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
conftest.py — shared fixtures for metaScreener pytest suite.

Mocks tkinter and metascreener.plugin_api so that plugin modules can be
imported on headless systems (CI, Docker, WSL) without an X server.
"""

import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# 1. Mock tkinter and related submodules BEFORE any plugin import
# ---------------------------------------------------------------------------
_TK_MODULES = [
    "tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox",
    "tkinter.scrolledtext", "tkinter.font", "_tkinter",
]

for mod_name in _TK_MODULES:
    if mod_name not in sys.modules:
        mock = MagicMock()
        # ttk.Notebook, ttk.Frame, etc. must return MagicMock so type() works
        sys.modules[mod_name] = mock


# Mock metascreener.plugin_api so BasePlugin / PluginMeta resolve
_plugin_api = types.ModuleType("metascreener.plugin_api")

class _FakePluginMeta:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

class _FakeBasePlugin:
    def __init__(self, app=None, meta=None):
        self.app = app
        self.meta = meta

_plugin_api.PluginMeta = _FakePluginMeta       # type: ignore
_plugin_api.BasePlugin = _FakeBasePlugin        # type: ignore

# Ensure the metascreener package exists in sys.modules
if "metascreener" not in sys.modules:
    _metascreener = types.ModuleType("metascreener")
    sys.modules["metascreener"] = _metascreener
if "metascreener.plugin_api" not in sys.modules:
    sys.modules["metascreener.plugin_api"] = _plugin_api

# ---------------------------------------------------------------------------
# 2. Add project root to sys.path so plugin imports resolve
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 3. Shared paths / data
# ---------------------------------------------------------------------------
SAMPLES_DIR = PROJECT_ROOT / "samples"
IC_EC_FILE = SAMPLES_DIR / "ic_ec_12.txt"
AGGREGATE_CSV = SAMPLES_DIR / "20260122_1654_aggregate.csv"

# Columns present in the sample aggregate CSV (used in criterion inference)
AGGREGATE_COLUMNS = [
    "local_id", "source_key", "title", "authors", "first_author", "year",
    "doi", "pmid", "pmcid", "arxiv", "venue", "volume", "issue", "pages",
    "publisher", "lang", "url", "confidence", "status", "provenance",
    "last_checked", "parents", "abstract", "keywords", "open_access",
    "doc_type", "hit_openalex", "hit_crossref", "hit_semanticscholar",
    "match_strategy",
]


# ---------------------------------------------------------------------------
# 4. Import helpers for plugins (dirs start with digits → importlib needed)
# ---------------------------------------------------------------------------
import importlib.util

def _import_plugin(subdir: str, module_name: str = "plugin"):
    """Import a plugin module from plugins/<subdir>/plugin.py."""
    plugin_path = PROJECT_ROOT / "plugins" / subdir / f"{module_name}.py"
    if not plugin_path.exists():
        raise FileNotFoundError(f"Plugin not found: {plugin_path}")
    spec = importlib.util.spec_from_file_location(
        f"plugins.{subdir}.{module_name}", str(plugin_path)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# Pre-import plugin modules (cached after first call)
_plugin_cache = {}

def get_harmoniser():
    if "harmoniser" not in _plugin_cache:
        _plugin_cache["harmoniser"] = _import_plugin("03_harmoniser")
    return _plugin_cache["harmoniser"]

def get_eh():
    if "eh" not in _plugin_cache:
        _plugin_cache["eh"] = _import_plugin("04_eh")
    return _plugin_cache["eh"]

def get_ih():
    if "ih" not in _plugin_cache:
        _plugin_cache["ih"] = _import_plugin("05_ih")
    return _plugin_cache["ih"]

def get_el():
    if "el" not in _plugin_cache:
        _plugin_cache["el"] = _import_plugin("06_el")
    return _plugin_cache["el"]

def get_il():
    if "il" not in _plugin_cache:
        _plugin_cache["il"] = _import_plugin("07_il")
    return _plugin_cache["il"]

def get_refx_services():
    """plugins/02_references_of_x/services.py (the corpus ingestion layer)."""
    if "refx_services" not in _plugin_cache:
        _plugin_cache["refx_services"] = _import_plugin(
            "02_references_of_x", "services"
        )
    return _plugin_cache["refx_services"]


# ---------------------------------------------------------------------------
# 4b. No test reads the developer's real settings
# ---------------------------------------------------------------------------
#
# Session C's review found the golden replays exposed to
# `%APPDATA%/metaScreener/settings.json`: the EL and IL engines resolve
# their endpoint per stage now, the endpoint is a cache-key input (F-89),
# and so a developer with a stage override in their own settings would
# compute different keys and fail the golden test — or, worse, pass one
# that should have failed. The exposure predates session C at the
# application level; session C widened it to stages, and the right answer
# is to close it for the whole suite rather than for the paths noticed.
#
# Set on the environment rather than through `monkeypatch`, because this
# must hold for module-level code that runs at import time. A test that
# wants its own directory still overrides it with `monkeypatch.setenv`,
# which is function-scoped and therefore wins.
import tempfile as _tempfile

_ISOLATED_SETTINGS = _tempfile.mkdtemp(prefix="metascreener-tests-")
os.environ["APPDATA"] = str(Path(_ISOLATED_SETTINGS) / "appdata")
os.environ["XDG_CONFIG_HOME"] = str(Path(_ISOLATED_SETTINGS) / "xdg")


# ---------------------------------------------------------------------------
# 5. Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ic_ec_text() -> str:
    """Raw text of the sample ic_ec_12.txt criteria file."""
    return IC_EC_FILE.read_text(encoding="utf-8-sig")


@pytest.fixture
def aggregate_columns() -> list:
    """Column names from the sample aggregate CSV."""
    return list(AGGREGATE_COLUMNS)
