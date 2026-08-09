
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_frozen_build_spec.py — F-66: keep the PyInstaller specs able to reach
every dependency the plugins import.

Why this exists
---------------
The frozen build shipped for months without ``langdetect``, ``rapidfuzz`` and
``pytesseract``, and **nothing about running it revealed that**. It started
cleanly, printed both ``PLUGIN LOADER:`` banners, and rendered all seven tabs,
because every heavy dependency in the plugin tree sits behind a ``try/except``
feature flag or a lazy in-function import. What was actually lost was silent:
``FUZZY_OK=False`` meant a reference-matching tool performed no fuzzy title
matching, and said nothing about it.

So **a green launch is not evidence that the build is correct** — that is the
whole of F-66, and it is why this check is static and not a smoke test.

The fix in ``d8d8a96`` is two lines per spec: ``hookspath=['.']`` and
``'plugins'`` in ``hiddenimports``. Both are needed, and neither is
self-evidently load-bearing to someone editing a spec later:

- ``hookspath=['.']`` alone changes nothing measurable. PyInstaller looks for
  ``hook-<name>.py`` only for modules already in the dependency graph, and
  nothing statically imports ``plugins`` — ``plugin_manager`` loads the plugin
  packages at runtime through its own ``sys.meta_path`` finder. Without the
  ``hiddenimports`` entry the hook is never even looked for.
- ``'plugins'`` in ``hiddenimports`` alone would pull in the package but not
  its submodules; ``hook-plugins.py`` is what calls ``collect_submodules``.

Delete either and the build silently loses five of the nine packages below,
while still launching and still showing seven tabs. This test is the only
thing standing between that edit and a shipped binary.

How the package list is derived
-------------------------------
From the source, with the AST, the way ``tools/audit_imports.py`` walks it —
**not** from a hardcoded list. A fixed list is the same enumeration mistake as
F-01's cache key: it is correct exactly until someone adds an import, and then
it is silently wrong. Anything a plugin imports is picked up here the moment it
is written, including ``pandas``, ``openpyxl`` and ``PIL``, which before
``d8d8a96`` were reachable *only* by accident — ``collect_all('openai')`` pulls
``openai._extras.pandas_proxy``, which names ``pandas``, which drags in
``openpyxl`` and then ``PIL``. Had ``openai`` ever dropped that proxy module,
three plugins would have lost their dependencies with no spec change to explain
it. They are covered here by derivation, not by being named.

No build is required, so this runs in every CI cell.
"""
import ast
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPECS = ["metaScreener.spec", "metaScreener-console.spec"]
HOOK_FILE = PROJECT_ROOT / "hook-plugins.py"

#: Package names that are ours, not third-party.
LOCAL_PACKAGES = {"plugins", "metascreener", "tools", "tests"}


# ---------------------------------------------------------------------------
# reading the specs
# ---------------------------------------------------------------------------

def _spec_tree(spec_name: str) -> ast.Module:
    path = PROJECT_ROOT / spec_name
    assert path.exists(), f"{spec_name} is missing"
    return ast.parse(path.read_text(encoding="utf-8"), filename=spec_name)


def _analysis_kwarg(tree: ast.Module, name: str):
    """The literal value of a keyword argument to the Analysis(...) call."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Analysis"):
            for kw in node.keywords:
                if kw.arg == name:
                    try:
                        return ast.literal_eval(kw.value)
                    except ValueError:
                        return None
    return None


def _hiddenimports_literal(tree: ast.Module) -> set:
    """Names in the module-level ``hiddenimports = [...]`` assignment.

    Only the literal list. Entries appended later from ``collect_all`` results
    are not statically knowable and are handled by ``_collect_all_targets``.
    """
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "hiddenimports":
                    try:
                        return {str(x) for x in ast.literal_eval(node.value)}
                    except ValueError:
                        return set()
    return set()


def _collect_all_targets(tree: ast.Module) -> set:
    """Package names passed to collect_all(...) / collect_submodules(...)."""
    out = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in {"collect_all", "collect_submodules",
                                     "collect_data_files"}
                and node.args):
            try:
                out.add(str(ast.literal_eval(node.args[0])))
            except ValueError:
                pass
    return out


# ---------------------------------------------------------------------------
# deriving what the plugins actually import
# ---------------------------------------------------------------------------

def _third_party_imports_under_plugins() -> dict:
    """{top_level_package: {source files that import it}} for everything under
    plugins/ that is neither stdlib nor ours.

    Relative imports (``from . import x``) are skipped: they resolve inside the
    plugin tree and need no help from the spec.
    """
    found: dict = {}
    for path in sorted((PROJECT_ROOT / "plugins").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover - a broken plugin is another test's problem
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.setdefault(alias.name.split(".")[0], set()).add(rel)
            elif isinstance(node, ast.ImportFrom):
                if node.level:          # relative import
                    continue
                if node.module:
                    found.setdefault(node.module.split(".")[0], set()).add(rel)
    return {
        pkg: files for pkg, files in found.items()
        if pkg not in sys.stdlib_module_names
        and pkg not in LOCAL_PACKAGES
        and not pkg.startswith("_")
    }


def _routes_for(pkg: str, tree: ast.Module) -> list:
    """Every way the frozen build could reach ``pkg``, as human-readable
    strings. Empty means unreachable."""
    routes = []
    hookspath = _analysis_kwarg(tree, "hookspath") or []
    hidden = _hiddenimports_literal(tree)
    collected = _collect_all_targets(tree)

    hook_wired = ("." in hookspath and "plugins" in hidden
                  and HOOK_FILE.exists())
    if hook_wired:
        # hook-plugins.py runs collect_submodules("plugins"), so PyInstaller
        # analyses the plugin tree and picks up whatever it imports.
        routes.append("hook-plugins.py (collect_submodules('plugins'))")
    if pkg in hidden:
        routes.append("explicit hiddenimports")
    if pkg in collected:
        routes.append(f"collect_all('{pkg}')")
    return routes


# ---------------------------------------------------------------------------
# the two lines the fix consists of
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("spec", SPECS)
class TestSpecWiring:

    def test_hookspath_includes_the_project_root(self, spec):
        hookspath = _analysis_kwarg(_spec_tree(spec), "hookspath")
        assert hookspath is not None, f"{spec}: Analysis(...) has no hookspath"
        assert "." in hookspath, (
            f"{spec}: hookspath={hookspath!r} does not include '.', so "
            f"hook-plugins.py cannot be found. The build will still succeed "
            f"and still show seven tabs, while silently dropping every "
            f"dependency only the plugins import."
        )

    def test_hiddenimports_declares_the_plugins_package(self, spec):
        hidden = _hiddenimports_literal(_spec_tree(spec))
        assert "plugins" in hidden, (
            f"{spec}: 'plugins' is not in hiddenimports. Without it the "
            f"package is never in PyInstaller's graph, so hook-plugins.py is "
            f"never looked for and hookspath has no effect at all — measured: "
            f"identical 2960-module bundle with and without hookspath=['.']."
        )


class TestHookFile:

    def test_hook_exists(self):
        assert HOOK_FILE.exists(), (
            "hook-plugins.py is gone. Both specs point hookspath at the "
            "project root expecting to find it."
        )

    def test_hook_collects_the_plugin_submodules(self):
        tree = ast.parse(HOOK_FILE.read_text(encoding="utf-8"))
        assert "plugins" in _collect_all_targets(tree), (
            "hook-plugins.py no longer calls collect_submodules('plugins'). "
            "Declaring 'plugins' in hiddenimports pulls in the package but "
            "not its submodules; this call is what reaches them."
        )


# ---------------------------------------------------------------------------
# the check that survives someone adding a dependency
# ---------------------------------------------------------------------------

class TestEveryPluginDependencyIsReachable:

    def test_the_deriver_still_finds_imports(self):
        """Guard against this whole file passing vacuously. If the AST walk
        silently stops finding anything, every assertion below becomes true
        by having nothing to check."""
        deps = _third_party_imports_under_plugins()
        assert len(deps) >= 5, (
            f"only {len(deps)} third-party imports derived from plugins/ "
            f"({sorted(deps)}). The deriver is probably broken, which would "
            f"make the reachability test below pass by doing nothing."
        )

    @pytest.mark.parametrize("spec", SPECS)
    def test_every_derived_dependency_has_a_route(self, spec):
        tree = _spec_tree(spec)
        deps = _third_party_imports_under_plugins()
        unreachable = {}
        for pkg, files in sorted(deps.items()):
            if not _routes_for(pkg, tree):
                unreachable[pkg] = sorted(files)[:2]
        assert not unreachable, (
            f"{spec}: these packages are imported under plugins/ but the "
            f"frozen build has no way to reach them: {unreachable}. Add them "
            f"to hiddenimports/collect_all, or restore the hook wiring. A "
            f"build missing them still launches and still shows seven tabs "
            f"(F-66), so nothing else will catch this."
        )

    @pytest.mark.parametrize("spec", SPECS)
    def test_the_three_formerly_accidental_packages_are_reachable(self, spec):
        """``pandas``, ``openpyxl`` and ``PIL`` used to arrive only as a side
        effect of ``collect_all('openai')`` → ``openai._extras.pandas_proxy``.

        They are named here — unusually, given this file derives everything
        else — because that is the one dependency route no change to *this*
        repository controls. If ``openai`` drops the proxy module, the route
        disappears with no diff and no warning. After ``d8d8a96`` all three are
        also reachable through the plugin tree, which is what this asserts:
        that they no longer depend on the accident.
        """
        tree = _spec_tree(spec)
        deps = _third_party_imports_under_plugins()
        for pkg in ("pandas", "openpyxl", "PIL"):
            assert pkg in deps, (
                f"{pkg} is no longer imported anywhere under plugins/. If that "
                f"is deliberate, drop it from this test; if not, an import was "
                f"lost."
            )
            routes = _routes_for(pkg, tree)
            assert routes, f"{spec}: {pkg} is unreachable by the frozen build."
            assert any("hook-plugins.py" in r for r in routes), (
                f"{spec}: {pkg} is reachable only via {routes}. Before "
                f"d8d8a96 it arrived solely through collect_all('openai') "
                f"pulling openai._extras.pandas_proxy — a route this project "
                f"does not control. It must be reachable through the plugin "
                f"tree as well."
            )
