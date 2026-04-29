#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
tools/audit_decorators.py - Heuristic guard against accidental @dataclass omission.

Scans Python files in given directories or files. For every top-level class
definition, flags classes that look like they should be dataclasses but lack
a dataclass-style decorator.

A class is "dataclass-shaped" if:
  - It has class-level type-annotated attributes (e.g. `name: str`, possibly
    with a default value).
  - It does NOT define its own __init__.
  - It either has no bases, or its only base is `object`.

This catches the regression that surfaced in Conv 5 / Commit 4 (e84b796):
plugins/_common/bundle.py:BundleInfo lost its @dataclass decorator during
the extraction (the regex anchored at `class BundleInfo:` and missed the
`@dataclass` line above). The audit_imports.py tool didn't flag it because
the missing decorator did not produce any unresolved name reference - the
class was syntactically valid Python, every name resolved, the failure
only manifested at instantiation time during the GUI smoke test for
Commit 7.

ClassVar and InitVar annotations are excluded from the field count, so
classes that only declare class-level constants (and have no instance
fields) are not flagged.

Usage:
    python tools/audit_decorators.py plugins/_common/
    python tools/audit_decorators.py plugins/
    python tools/audit_decorators.py plugins/_common/bundle.py

Exit code 0 if all classes audit clean, 1 if any findings, 2 on usage error.
"""
import ast
import sys
from pathlib import Path
from typing import List, Tuple


DATACLASS_DECORATOR_NAMES = {
    "dataclass",   # @dataclass, @dataclasses.dataclass, @dc.dataclass
    "define",      # @attrs.define
    "frozen",      # @attrs.frozen
    "attrs",       # @attr.attrs (legacy)
    "s",           # @attr.s (legacy)
}


def _decorator_name(node):
    """Extract a decorator's identifier (handles @x, @x.y, @x(...), @x.y(...))."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return ""


def _is_dataclass_like_decorator(node):
    return _decorator_name(node) in DATACLASS_DECORATOR_NAMES


def _is_classvar_or_initvar(annotation):
    """Return True for ClassVar[T] / typing.ClassVar[T] / dataclasses.InitVar[T]."""
    if isinstance(annotation, ast.Subscript):
        inner = annotation.value
        if isinstance(inner, ast.Name) and inner.id in {"ClassVar", "InitVar"}:
            return True
        if isinstance(inner, ast.Attribute) and inner.attr in {"ClassVar", "InitVar"}:
            return True
    return False


def _has_dataclass_shape(cls):
    """True if class has the structural shape of a dataclass (annotated fields,
    no __init__, no real inheritance)."""
    for stmt in cls.body:
        if isinstance(stmt, ast.FunctionDef) and stmt.name == "__init__":
            return False
        if isinstance(stmt, ast.AsyncFunctionDef) and stmt.name == "__init__":
            return False

    has_instance_field = False
    for stmt in cls.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            if not _is_classvar_or_initvar(stmt.annotation):
                has_instance_field = True
                break
    if not has_instance_field:
        return False

    bases = cls.bases
    if not bases:
        return True
    if len(bases) == 1 and isinstance(bases[0], ast.Name) and bases[0].id == "object":
        return True
    return False


def _has_dataclass_decorator(cls):
    return any(_is_dataclass_like_decorator(d) for d in cls.decorator_list)


def audit_file(path):
    """Return [(class_name, line_no), ...] for dataclass-shaped classes missing a decorator."""
    try:
        source = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as e:
        return [(f"DECODE ERROR: {e}", 0)]
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [(f"SYNTAX ERROR: {e}", e.lineno or 0)]
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if _has_dataclass_shape(node) and not _has_dataclass_decorator(node):
                findings.append((node.name, node.lineno))
    return findings


def main(argv):
    if len(argv) < 2:
        print("Usage: python tools/audit_decorators.py <path> [<path>...]", file=sys.stderr)
        return 2

    any_findings = False
    for pathstr in argv[1:]:
        root = Path(pathstr)
        if not root.exists():
            print(f"{pathstr}: does not exist")
            any_findings = True
            continue

        files = [root] if root.is_file() else sorted(root.rglob("*.py"))
        files = [f for f in files if "__pycache__" not in f.parts]

        for f in files:
            findings = audit_file(f)
            if findings:
                for name, lineno in findings:
                    print(f"{f}:{lineno}: dataclass-shaped class {name!r} is missing @dataclass")
                any_findings = True
            else:
                print(f"{f}: clean")

    return 1 if any_findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
