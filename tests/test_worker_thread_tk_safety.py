
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_worker_thread_tk_safety.py — F-112 and F-137: a worker thread must not
touch Tk directly.

Both findings are the same shape at three sites: a nested ``work()``
closure whose success path marshals every update through ``self.after(0,
…)`` and whose ``except`` branch calls ``messagebox.showerror`` straight
from the worker. Tk is not thread-safe, so this can hang **the whole hub**,
not just the tab it happens in — and it fires on the error path, which is
exactly when the application most needs to stay responsive.

**Why this is a static check rather than a behavioural one.** The only way
to observe the defect at run time is to import the module that contains it,
and ``plugins/01_reference_extractor/original/prisma_citations_ai_v3_1.py``
has unguarded top-level ``import fitz`` and ``from PIL import Image,
ImageTk`` — so a test that imported it would pass here and fail on any
machine without PyMuPDF and Pillow. Worse, ``tests/conftest.py`` replaces
``tkinter`` with a ``MagicMock``, which is thread-agnostic: real Tk raises
``RuntimeError: main thread is not in main loop``, the mock silently
records the call. A behavioural test would therefore need to import an
unimportable module in order to assert on a mock that cannot fail.

Reading the AST costs neither, and it pins the *property* rather than the
three instances of it — which is what stops a fourth appearing.
"""
import ast
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT


PLUGINS = PROJECT_ROOT / "plugins"


def _worker_targets(tree: ast.AST):
    """Every function used as ``threading.Thread(target=…)`` in this module."""
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        called = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if called != "Thread":
            continue
        for kw in node.keywords:
            if kw.arg == "target":
                v = kw.value
                if isinstance(v, ast.Name):
                    names.add(v.id)
                elif isinstance(v, ast.Attribute):
                    names.add(v.attr)
    return names


def _tk_calls_outside_after(fn_node: ast.AST):
    """``messagebox.*`` and ``tk.*Var.get`` calls not wrapped in ``after(…)``.

    Only ``messagebox`` is asserted on; the variable reads are reported for
    context because they are the same defect class at a different site and
    are *not* covered by either finding.
    """
    parents = {}
    for parent in ast.walk(fn_node):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def _inside_after(node):
        cur = parents.get(node)
        while cur is not None:
            if isinstance(cur, ast.Call):
                f = cur.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                if name == "after":
                    return True
            cur = parents.get(cur)
        return False

    bad = []
    for node in ast.walk(fn_node):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if isinstance(owner, ast.Name) and owner.id == "messagebox":
            if not _inside_after(node):
                bad.append(f"messagebox.{node.func.attr} at line {node.lineno}")
    return bad


def _offending_sites():
    for path in sorted(PLUGINS.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):        # pragma: no cover
            continue
        targets = _worker_targets(tree)
        if not targets:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name in targets:
                for bad in _tk_calls_outside_after(node):
                    yield path.relative_to(PROJECT_ROOT).as_posix(), node.name, bad


class TestNoWorkerThreadTouchesTkDirectly:

    def test_the_finder_still_finds_workers(self):
        """Vacuity guard. If the tree stops matching ``threading.Thread(
        target=…)`` the check silently passes for ever."""
        found = 0
        for path in sorted(PLUGINS.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):    # pragma: no cover
                continue
            found += len(_worker_targets(tree))
        assert found >= 8, (
            f"only {found} worker targets found across plugins/; the finder "
            f"has stopped matching the code rather than the code having "
            f"changed"
        )

    def test_no_worker_calls_messagebox_off_the_main_thread(self):
        """F-112 (plugin 01) and F-137 (plugin 02, twice).

        Seven other workers in the tree already do this correctly — 06 and
        07 marshal with ``self.after(0, lambda m=str(e): …)``, and 03/04/05
        hand the message to a main-thread handler — so the property is the
        house rule and these three were the exceptions."""
        sites = list(_offending_sites())
        assert not sites, "\n".join(
            f"{p}::{fn} — {bad}" for p, fn, bad in sites)
