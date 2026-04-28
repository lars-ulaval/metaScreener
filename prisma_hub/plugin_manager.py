# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
plugin_manager.py — hardened plugin loader for dev & PyInstaller one-file.

- Treats 'plugins/' as a data directory (bundled with --add-data "plugins;plugins").
- Installs a MetaPathFinder AT IMPORT TIME that intercepts ANY import under
  'plugins.<name>' (packages and modules), reads the file from disk, sanitizes
  BOM and any 'from __future__ import annotations', and executes it.
- Supports:
    plugins.<name>                 (package, with or without __init__.py)
    plugins.<name>.plugin          (module)
    plugins.<name>.<any_module>    (module)
    plugins.<name>.<subpkg>        (package if folder has __init__.py)
"""
import sys
import importlib
import importlib.abc
import importlib.util
from types import ModuleType
from pathlib import Path
from typing import Optional

BANNER_IMPORT   = "PLUGIN LOADER: early meta-path sanitizer INSTALLED"
BANNER_DISCOVER = "PLUGIN LOADER: meta-path sanitizer ACTIVE"

# ---------- paths & environment ----------

def _project_root_dev() -> Path:
    # This file is at <project_root>/prisma_hub/plugin_manager.py, so parents[1] is project_root.
    return Path(__file__).resolve().parents[1]

def _plugins_root_dev() -> Path:
    return _project_root_dev() / "plugins"

def _plugins_root_frozen() -> Optional[Path]:
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return None
    return Path(base) / "plugins"

def _ensure_prisma_hub_on_sys_path():
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and meipass not in sys.path:
        sys.path.insert(0, meipass)
    dev_root = _project_root_dev()
    s = str(dev_root)
    if s not in sys.path:
        sys.path.insert(0, s)
    try:
        import prisma_hub  # noqa: F401
    except Exception:
        pass

# ---------- sanitizer helpers ----------

def _sanitize(src: str) -> str:
    # Strip BOM
    if src and src[:1] == "\ufeff":
        src = src[1:]
    # Drop any 'from __future__ import annotations' line (wherever it is)
    out = []
    for ln in src.splitlines(keepends=True):
        s = ln.strip()
        if s.startswith("from __future__ import") and "annotations" in s:
            continue
        out.append(ln)
    return "".join(out)

def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return p.read_bytes().decode("utf-8", errors="ignore")

# ---------- meta-path finder/loader ----------

class _PluginsFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """
    Intercepts ANY import beginning with 'plugins.' or the top-level 'plugins' package.
    Resolves to files under <root>/<name>/... and sanitizes before execution.
    """
    def __init__(self, root: Path):
        self.root = root

    def _spec_for_package(self, fullname: str, pkg_dir: Path):
        spec = importlib.util.spec_from_loader(fullname, self, origin=str(pkg_dir))
        spec.submodule_search_locations = [str(pkg_dir)]
        return spec

    def _spec_for_module(self, fullname: str, pyfile: Path):
        return importlib.util.spec_from_loader(fullname, self, origin=str(pyfile))

    def find_spec(self, fullname, path=None, target=None):
        parts = fullname.split(".")
        # Top-level 'plugins' package
        if fullname == "plugins":
            if self.root.exists():
                return self._spec_for_package(fullname, self.root)
            return None

        # Anything under plugins.*
        if parts[0] != "plugins" or len(parts) < 2:
            return None

        # plugins.<name> (package)
        name = parts[1]
        base_dir = self.root / name
        if len(parts) == 2:
            # Treat as package if folder exists (even without __init__.py)
            if base_dir.is_dir():
                # If there's an __init__.py, use that; else synthesize empty package
                init_py = base_dir / "__init__.py"
                if init_py.exists():
                    # PATCH: mark as package when __init__.py exists
                    spec = self._spec_for_module(fullname, init_py)
                    spec.submodule_search_locations = [str(base_dir)]
                    return spec
                return self._spec_for_package(fullname, base_dir)
            return None

        # plugins.<name>.<rest>
        remainder = parts[2:]
        cur = base_dir
        for i, part in enumerate(remainder):
            candidate_pkg = cur / part
            candidate_mod = cur / (part + ".py")
            is_last = (i == len(remainder) - 1)

            if candidate_pkg.is_dir():
                if is_last:
                    init_py = candidate_pkg / "__init__.py"
                    if init_py.exists():
                        # PATCH: mark as package when __init__.py exists
                        spec = self._spec_for_module(fullname, init_py)
                        spec.submodule_search_locations = [str(candidate_pkg)]
                        return spec
                    # Package without __init__.py
                    return self._spec_for_package(fullname, candidate_pkg)
                else:
                    cur = candidate_pkg
                    continue

            if candidate_mod.exists() and is_last:
                return self._spec_for_module(fullname, candidate_mod)

            # No match
            return None

        return None

    # Loader API
    def create_module(self, spec):
        return None  # default module creation

    def exec_module(self, module):
        origin = getattr(module.__spec__, "origin", "")
        p = Path(origin)
        # Package without __init__.py: synthesize an empty package module
        if p.is_dir():
            module.__path__ = [str(p)]
            module.__file__ = str(p / "__init__.py")
            return

        # Normal .py file: read, sanitize, exec
        import __future__
        
        src = _read_text(p)
        src = _sanitize(src)
        
        # Compile with postponed evaluation of annotations (PEP 563 behavior)
        flags = __future__.annotations.compiler_flag
        code = compile(src, str(p), "exec", dont_inherit=True, flags=flags)
        
        # Ensure correct package context for relative imports
        spec = getattr(module, "__spec__", None)
        if spec and getattr(spec, "name", None):
            fullname = spec.name
            module.__package__ = fullname.rpartition(".")[0] or fullname
        
        exec(code, module.__dict__)

def _install_finder(root: Path):
    # Put a 'plugins' package in sys.modules (namespace or real) so imports always resolve
    if "plugins" not in sys.modules:
        pkg = ModuleType("plugins")
        pkg.__path__ = [str(root)]
        sys.modules["plugins"] = pkg
    # Insert our finder at the front once
    if not any(isinstance(f, _PluginsFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _PluginsFinder(root))
        print(BANNER_IMPORT, flush=True)

# ---------- public API ----------

def discover(app):
    """Import every 'plugins.<name>.plugin' via the sanitizer and return the modules."""
    print(BANNER_DISCOVER, flush=True)
    _ensure_prisma_hub_on_sys_path()
    root = _plugins_root_frozen() or _plugins_root_dev()
    if not root or not root.exists():
        raise ModuleNotFoundError(f"Plugins folder not found: {root}")
    _install_finder(root)

    loaded = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "plugin.py").exists():
            continue
        fullname = f"plugins.{entry.name}.plugin"
        mod = sys.modules.get(fullname)
        if mod is None:
            mod = importlib.import_module(fullname)  # goes through our finder
        loaded.append(mod)
    return loaded

# Install at import time (so early imports are intercepted)
_ensure_prisma_hub_on_sys_path()
_root = _plugins_root_frozen() or _plugins_root_dev()
if _root and _root.exists():
    _install_finder(_root)
