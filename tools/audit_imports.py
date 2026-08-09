# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""tools/audit_imports.py - Static check for unresolved name references in Python modules.

Walks each .py file's AST. Flags any `ast.Name` reference (Load context) that
isn't accounted for by:
  - an import (`import X`, `from X import Y`, including aliases, including lazy
    imports nested inside function bodies or try/except blocks)
  - a function/class definition (top-level or nested)
  - a function parameter (positional, keyword-only, *args, **kwargs)
  - any binding target (assignment, augmented assignment, annotated
    assignment, for-loop target, with-as, except-as, walrus :=, comprehension
    binding) at any nesting depth
  - a Python builtin
  - the method-receiver names `self` and `cls`

Designed to catch the bug class that integration tests miss because the
affected code path isn't exercised by tests. Concrete example from Conv 4 of
the v3.1.0 refactor: Plugin 03's `_export_pipe()` was extracted into
`exporters.py` but the transitive `_export_to_pipe_table` import was dropped.
The 74-test suite stayed green because `_export_pipe` is invoked only via the
View's `_export_bundle` method, which Tkinter mocks block in headless runs.
Manual GUI smoke caught the bug at deploy time. A 30-second run of this audit
against `plugins/03_harmoniser/` would have caught it at staging time.

Usage:
    python tools/audit_imports.py plugins/03_harmoniser/
    python tools/audit_imports.py plugins/03_harmoniser/exporters.py

Exit code: 0 if no unresolved names found, 1 otherwise. Suitable as a
pre-commit gate alongside `pytest -q` and the mojibake one-liner.

Note: this audit is over-permissive on cross-function references (a name
defined inside function G is treated as resolvable from function F, even
though Python would raise NameError). This trade-off is intentional: zero
false positives matter more than catching cross-scope leaks, since the
bug class we're protecting against is missing imports, which manifest the
same way regardless of scope.
"""
import ast
import builtins
import sys
from pathlib import Path


def _add_target_names(target, names):
    """Add all Name ids reachable from an assignment/binding target."""
    if isinstance(target, ast.Name):
        names.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for el in target.elts:
            _add_target_names(el, names)
    elif isinstance(target, ast.Starred):
        _add_target_names(target.value, names)


def audit_file(path):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))

    known = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for n in node.names:
                known.add(n.asname or n.name)
        elif isinstance(node, ast.Import):
            for n in node.names:
                known.add(n.asname or n.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            known.add(node.name)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                posonly = getattr(args, "posonlyargs", []) or []
                for arg in list(args.args) + list(args.kwonlyargs) + list(posonly):
                    known.add(arg.arg)
                if args.vararg:
                    known.add(args.vararg.arg)
                if args.kwarg:
                    known.add(args.kwarg.arg)
        elif isinstance(node, ast.Lambda):
            args = node.args
            posonly = getattr(args, "posonlyargs", []) or []
            for arg in list(args.args) + list(args.kwonlyargs) + list(posonly):
                known.add(arg.arg)
            if args.vararg:
                known.add(args.vararg.arg)
            if args.kwarg:
                known.add(args.kwarg.arg)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                _add_target_names(t, known)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            _add_target_names(node.target, known)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            _add_target_names(node.target, known)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    _add_target_names(item.optional_vars, known)
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                known.add(node.name)
        elif isinstance(node, ast.NamedExpr):  # walrus :=
            _add_target_names(node.target, known)
        elif isinstance(node, ast.comprehension):
            _add_target_names(node.target, known)

    safe = set(dir(builtins)) | {"self", "cls"} | {
        # Module-level dunders Python provides automatically.
        "__file__", "__name__", "__doc__", "__package__",
        "__loader__", "__spec__", "__builtins__", "__cached__", "__path__",
    }
    referenced = {
        n.id for n in ast.walk(tree)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    return sorted(referenced - known - safe)


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/audit_imports.py <path>", file=sys.stderr)
        sys.exit(2)

    target = Path(sys.argv[1])
    if not target.exists():
        print(f"Path not found: {target}", file=sys.stderr)
        sys.exit(2)

    files = sorted(target.rglob("*.py")) if target.is_dir() else [target]
    files = [f for f in files if f.name != "__init__.py"]

    any_issues = False
    for f in files:
        try:
            issues = audit_file(f)
        except SyntaxError as e:
            print(f"{f}: SYNTAX ERROR: {e}")
            any_issues = True
            continue
        if issues:
            any_issues = True
            print(f"{f}:")
            for name in issues:
                print(f"  unresolved: {name}")
        else:
            print(f"{f}: clean")

    sys.exit(1 if any_issues else 0)


if __name__ == "__main__":
    main()
