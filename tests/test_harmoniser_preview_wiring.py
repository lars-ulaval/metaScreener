# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""test_harmoniser_preview_wiring.py — the Preview button, executed not read.

`HarmoniserView` subclasses `ttk.Frame`, which `tests/conftest.py` has replaced with a
`MagicMock`. The class object is therefore a mock and attribute access on it hands back
mocks rather than methods, so nothing that merely imports the View executes a line of
it. Wave 13c session B established this the hard way: reverting `_validate` entirely
left the whole suite green. The remedy it built is reused here — lift the real `def`
out of `ui.py` by AST and run it against `ui`'s own globals, so the code under test is
the code that ships.

What this file is for, beyond coverage: the pure function's own tests asserted a dialog
`kind` of `"showinfo"` and passed, because they invented the vocabulary instead of
reading it. `ui._SHOW` is keyed `"info"`, `"warning"`, `"error"`, so `_SHOW[kind]` would
have raised `KeyError` the first time anyone pressed the button. A test that never runs
the View cannot find that.
"""

import io
from pathlib import Path

import pytest

from conftest import _import_plugin, PROJECT_ROOT


CORPUS = PROJECT_ROOT / "samples" / "20260122_1654_aggregate.csv"
PROSE = PROJECT_ROOT / "samples" / "ic_ec_12.txt"


def _ui():
    return _import_plugin("03_harmoniser", "ui")


@pytest.fixture(scope="module")
def rows_and_columns():
    """The rules the Harmoniser emits today, from the producer rather than by hand."""
    hp = _import_plugin("03_harmoniser", "parser")
    hi = _import_plugin("03_harmoniser", "inference")
    cols, stats = hp._load_a_header_and_stats(str(CORPUS))
    default_target, _ = hp._canonicalize_targets(
        hp._get_best_text_targets(cols, stats), cols)
    out = []
    for cid, ctype, label, src in hp._parse_free_text_criteria(
            io.open(PROSE, encoding="utf-8").read()):
        inf = hi._infer_criterion_details(
            crit_id=cid, crit_type=ctype, label=label,
            a_columns=list(cols), default_text_target=default_target)
        out.append({
            "stage": inf["stage"], "id": cid, "type": ctype, "scope": "metadata",
            "label": label, "operator": inf["operator"], "target": inf["target"],
            "what": inf["what"], "enabled": True, "source_text": src,
            "threshold": ("" if inf["stage"] in {"EH", "IH"} else "0.60"),
        })
    return out, list(cols)


def _method(name, ui=None):
    """The real function body out of `ui.py`, bound to nothing.

    Same mechanism as `tests/test_harmoniser_validate_wiring.py`; see that file's
    docstring for why it is necessary.

    `ui` is a parameter, and that is not decoration. `conftest._import_plugin`
    calls `spec.loader.exec_module` every time, so it returns a **fresh module
    object** on each call -- patching `ui._SHOW` on one instance and then lifting
    against another silently patches nothing, and the assertion fails with an empty
    list and no clue why. The sibling file does not trip on this only because it
    patches `ui.messagebox`, which conftest installed once in `sys.modules` and is
    therefore shared across instances. `_SHOW` is a module-level dict and is not.
    """
    import ast

    ui = ui if ui is not None else _ui()
    source = Path(ui.__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == "HarmoniserView":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == name:
                    module = ast.Module(body=[item], type_ignores=[])
                    ast.fix_missing_locations(module)
                    namespace = dict(ui.__dict__)
                    exec(compile(module, ui.__file__, "exec"), namespace)
                    return namespace[name]
    raise AssertionError("HarmoniserView.%s not found in ui.py" % name)


class _State:
    def __init__(self, rows, a_columns, a_path):
        self.rows = rows
        self.a_columns = a_columns
        self.a_path = a_path
        self.criteria_path = None
        self.criteria_kind = None
        self.a_id_col = "local_id"
        self.text_stats = {}
        self.criteria_text = ""


class _Stub:
    """Only what `_preview` touches. Anything else it reaches for is a bug."""

    def __init__(self, rows, a_columns, a_path):
        self.state = _State(rows, a_columns, a_path)
        self.logged = []
        self._worker = None

    def _log(self, msg):
        self.logged.append(msg)


def _run_preview(stub, monkeypatch):
    ui = _ui()          # ONE instance: patched below and lifted from, see _method
    shown = []
    monkeypatch.setattr(ui, "_SHOW", {
        "info": lambda t, b: shown.append(("info", t, b)),
        "error": lambda t, b: shown.append(("error", t, b)),
        "warning": lambda t, b: shown.append(("warning", t, b)),
    })
    warned = []
    monkeypatch.setattr(ui.messagebox, "showwarning",
                        lambda t, b: warned.append((t, b)), raising=False)
    monkeypatch.setattr(ui.messagebox, "showerror",
                        lambda t, b: warned.append((t, b)), raising=False)
    ok = _method("_preview", ui)(stub)
    return ok, shown, warned


class TestTheButtonExists:
    def test_the_view_has_a_preview_method(self):
        assert hasattr(_ui().HarmoniserView, "_preview") or _method("_preview")

    def test_the_button_is_created_and_wired_to_it(self):
        """Read from `_build_ui`'s source: the widget cannot be built headless."""
        import ast
        ui = _ui()
        source = Path(ui.__file__).read_text(encoding="utf-8")
        found = []
        for node in ast.walk(ast.parse(source)):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "Button"):
                kw = {k.arg: k.value for k in node.keywords}
                text = kw.get("text")
                cmd = kw.get("command")
                if (isinstance(text, ast.Constant)
                        and isinstance(text.value, str)
                        and "preview" in text.value.lower()):
                    found.append((text.value,
                                  getattr(cmd, "attr", None) if cmd else None))
        assert found, "no button whose label mentions Preview"
        assert found[0][1] == "_preview", (
            "the Preview button must call _preview, not %r" % (found[0][1],))

    def test_the_button_is_enabled_and_disabled_with_the_others(self):
        """A Preview with no criteria or no corpus would only raise a dialog."""
        source = Path(_ui().__file__).read_text(encoding="utf-8")
        body = source.split("def _refresh_buttons")[1].split("def ")[0]
        assert "btn_preview" in body, (
            "_refresh_buttons must govern the Preview button too, or it stays "
            "clickable when there is nothing to preview")


class TestPressingItShowsTheRealNumbers:
    def test_it_reports_the_chain_and_both_flagged_criteria(
            self, rows_and_columns, monkeypatch):
        rows, cols = rows_and_columns
        stub = _Stub([dict(r) for r in rows], cols, str(CORPUS))
        ok, shown, _warned = _run_preview(stub, monkeypatch)

        assert ok is True
        assert len(shown) == 1
        kind, title, body = shown[0]
        assert kind in _ui()._SHOW, "the kind must be dispatchable, not invented"
        assert title == "Criteria preview"
        assert "776" in body and "760" in body and "147" in body
        assert "EC-4 removed no records" in body
        assert "IC-4 removed 611" in body

    def test_it_logs_the_chain(self, rows_and_columns, monkeypatch):
        rows, cols = rows_and_columns
        stub = _Stub([dict(r) for r in rows], cols, str(CORPUS))
        _run_preview(stub, monkeypatch)
        assert stub.logged == [
            "Preview: 776 records, EH 776->760, IH 760->147, 147 survive"]

    def test_it_names_the_llm_rows_as_not_evaluated(
            self, rows_and_columns, monkeypatch):
        rows, cols = rows_and_columns
        stub = _Stub([dict(r) for r in rows], cols, str(CORPUS))
        _ok, shown, _w = _run_preview(stub, monkeypatch)
        body = shown[0][2]
        for cid in ("IC-1", "IC-5", "EC-2", "EC-3"):
            assert cid in body
        assert "never run" in body, "F-65's row is a different case and must read so"

    def test_it_does_not_mutate_the_views_criteria_rows(
            self, rows_and_columns, monkeypatch):
        import copy
        rows, cols = rows_and_columns
        stub = _Stub([dict(r) for r in rows], cols, str(CORPUS))
        before = copy.deepcopy(stub.state.rows)
        _run_preview(stub, monkeypatch)
        assert stub.state.rows == before

    def test_it_writes_no_file(self, rows_and_columns, monkeypatch):
        import sys
        rows, cols = rows_and_columns
        stub = _Stub([dict(r) for r in rows], cols, str(CORPUS))
        writes = []

        def hook(event, args):
            if event == "open" and len(args) > 1 and args[1] and any(
                    c in str(args[1]) for c in "wax+"):
                writes.append(str(args[0]))
            elif event in ("os.mkdir", "os.rename", "os.remove"):
                writes.append(event)

        sys.addaudithook(hook)
        n0 = len(writes)
        _run_preview(stub, monkeypatch)
        assert writes[n0:] == [], "the Preview button wrote: %r" % (writes[n0:],)

    def test_it_does_not_hold_the_corpus_after_returning(
            self, rows_and_columns, monkeypatch):
        """CL-3: `_UiState` keeps a path and columns, never 776 rows."""
        rows, cols = rows_and_columns
        stub = _Stub([dict(r) for r in rows], cols, str(CORPUS))
        _run_preview(stub, monkeypatch)
        for name, value in vars(stub.state).items():
            if isinstance(value, list) and len(value) > 50:
                raise AssertionError(
                    "_UiState.%s holds %d items after a preview; CL-3 says the "
                    "View does not retain corpus rows" % (name, len(value)))


class TestItRefusesPolitelyRatherThanCrashing:
    def test_no_criteria_warns_and_returns_false(self, rows_and_columns, monkeypatch):
        _rows, cols = rows_and_columns
        stub = _Stub([], cols, str(CORPUS))
        ok, shown, warned = _run_preview(stub, monkeypatch)
        assert ok is False
        assert shown == []
        assert warned, "the user pressed a button and must be told why nothing happened"

    def test_no_corpus_warns_and_returns_false(self, rows_and_columns, monkeypatch):
        rows, cols = rows_and_columns
        stub = _Stub([dict(r) for r in rows], cols, None)
        ok, shown, warned = _run_preview(stub, monkeypatch)
        assert ok is False
        assert warned

    def test_an_unreadable_corpus_is_reported_not_raised(
            self, rows_and_columns, monkeypatch, tmp_path):
        rows, cols = rows_and_columns
        missing = tmp_path / "does_not_exist.csv"
        stub = _Stub([dict(r) for r in rows], cols, str(missing))
        ok, _shown, warned = _run_preview(stub, monkeypatch)
        assert ok is False
        assert warned, "a missing corpus file must reach the user as a dialog"


class TestItNeverBlocks:
    """Wave 13c session B's constraint, carried forward: warn, never block."""

    def test_a_flagged_preview_still_returns_true(
            self, rows_and_columns, monkeypatch):
        rows, cols = rows_and_columns
        stub = _Stub([dict(r) for r in rows], cols, str(CORPUS))
        ok, shown, _w = _run_preview(stub, monkeypatch)
        assert shown[0][0] == "warning", "EC-4 and IC-4 are both flagged"
        assert ok is True, (
            "the preview reports; it does not veto. A warning that returned False "
            "would let a caller treat it as a gate.")
