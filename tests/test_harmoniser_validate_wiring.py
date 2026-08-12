# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_harmoniser_validate_wiring.py — the Harmoniser's Validate path (wave 13c B).

Session A built `plugins/03_harmoniser/linter.py::lint_criteria` against fixtures
and nothing called it. This module is the seam: it proves the shape the UI hands
the linter is the shape the linter reads, characterises what Validate does today,
and then pins what it does once the linter is wired in.

WHY A SHAPE PROOF AT ALL. The rows Validate iterates are `_UiState.rows`, built in
memory; the rows in `criteria_harmonized.csv` are those same rows after
`exporters.py::_export_csv` coerces `what` to a joined string and `enabled` to 0/1.
A linter specified against the file would split a list that is not a list. These
tests establish, from the producers rather than by assertion, that all three shapes
read identically.

Views are not instantiable under this conftest — `tkinter` is a MagicMock, so the
widget tree is fake and `HarmoniserView.__init__` builds nothing real. Everything
here therefore drives the pure functions the View delegates to, which is why those
functions exist.
"""

from pathlib import Path

import pytest

from conftest import (
    AGGREGATE_CSV,
    IC_EC_FILE,
    _import_plugin,
    get_harmoniser,
)

GOLDEN = Path(__file__).parent / "golden" / "criteria_harmonized_v3.1.0.csv"

#: The 11 keys `exporters.py::_export_csv` declares. Every producer of
#: `_UiState.rows` builds exactly these, and the linter reads a subset.
ROW_KEYS = frozenset({
    "stage", "id", "type", "scope", "label", "operator",
    "target", "what", "threshold", "enabled", "source_text",
})

#: The in-memory types. `what` is a LIST and `enabled` is a BOOL — the two the
#: coordinator's brief for session A got wrong, and the reason this file exists.
ROW_TYPES = {
    "stage": str, "id": str, "type": str, "scope": str, "label": str,
    "operator": str, "target": str, "what": list, "threshold": str,
    "enabled": bool, "source_text": str,
}


def _linter():
    return _import_plugin("03_harmoniser", "linter")


def _harm_parser():
    return _import_plugin("03_harmoniser", "parser")


# ---------------------------------------------------------------------------
# The fixture, derived from the producer rather than typed out.
#
# This mirrors `ui.py::HarmoniserView._harmonise_no_llm`'s free-text branch
# statement for statement. `test_the_fixture_is_what_the_harmoniser_emits`
# certifies it by export byte-identity, so a drift in the production path fails
# here rather than silently changing what every other test in this file means.
# ---------------------------------------------------------------------------

def _production_rows():
    h = get_harmoniser()
    a_columns, text_stats = h._load_a_header_and_stats(str(AGGREGATE_CSV))
    default_text_target = h._get_best_text_targets(a_columns, text_stats)
    default_text_target, _ = h._canonicalize_targets(default_text_target, a_columns)

    rows = []
    for crit_id, crit_type, label, source_line in h._parse_free_text_criteria(
            IC_EC_FILE.read_text(encoding="utf-8-sig")):
        inferred = h._infer_criterion_details(
            crit_id=crit_id, crit_type=crit_type, label=label,
            a_columns=list(a_columns), default_text_target=default_text_target,
        )
        stage = inferred["stage"]
        rows.append({
            "stage": stage, "id": crit_id, "type": crit_type, "scope": "metadata",
            "label": label, "operator": inferred["operator"],
            "target": inferred["target"], "what": inferred["what"],
            "threshold": f"{h.DEFAULT_THRESHOLD:.2f}" if stage in {"EL", "IL"} else "",
            "enabled": True, "source_text": source_line,
        })
    return rows, list(a_columns)


@pytest.fixture(scope="module")
def production():
    return _production_rows()


@pytest.fixture(scope="module")
def rows(production):
    return production[0]


@pytest.fixture(scope="module")
def a_columns(production):
    return production[1]


def _findings(report):
    return sorted((f.criterion_id, f.check) for f in report)


# ---------------------------------------------------------------------------


class TestTheShapeTheUiHandsTheLinter:
    """The highest-risk item in this wave, settled by execution.

    All four writers of `_UiState.rows` are checked, because `_validate` cannot
    tell which one produced what it is iterating:

      - `ui.py::HarmoniserView._harmonise_no_llm` (free text, and the
        infer-missing-fields branch over already-loaded rows)
      - `parser.py::_normalize_structured_row` (a loaded CSV/XLSX table)
      - `ui.py::HarmoniserView._begin_edit`'s inline `save` (a hand-edited cell)
      - `llm_refine.py::_llm_refine` (the LLM refinement pass)
    """

    def test_the_fixture_is_what_the_harmoniser_emits(self, rows, tmp_path):
        h = get_harmoniser()
        out = tmp_path / "criteria_harmonized.csv"
        h._export_csv(rows, str(out))
        assert out.read_bytes() == GOLDEN.read_bytes(), (
            "The production path changed, or this fixture drifted from it. "
            "Either way every assertion in this file is now about a table that "
            "does not exist."
        )

    def test_the_in_memory_row_has_exactly_the_exported_keys(self, rows):
        for row in rows:
            assert frozenset(row) == ROW_KEYS, sorted(frozenset(row) ^ ROW_KEYS)

    def test_what_is_a_list_and_enabled_is_a_bool_in_memory(self, rows):
        """The two the brief for session A got wrong, pinned by type."""
        for row in rows:
            for key, want in ROW_TYPES.items():
                assert isinstance(row[key], want), (
                    "%s[%s] is %s, expected %s — the linter's normaliser branches "
                    "on exactly this." % (row["id"], key, type(row[key]).__name__,
                                          want.__name__)
                )

    def test_the_exported_csv_carries_the_other_two_types(self, rows, tmp_path):
        """`_export_csv` is the ONLY place the types change."""
        import csv as _csv
        h = get_harmoniser()
        out = tmp_path / "c.csv"
        h._export_csv(rows, str(out))
        with out.open(encoding="utf-8-sig", newline="") as fh:
            exported = list(_csv.DictReader(fh))
        assert frozenset(exported[0]) == ROW_KEYS
        assert all(isinstance(r["what"], str) for r in exported)
        assert {r["enabled"] for r in exported} <= {"0", "1"}

    def test_a_structured_reload_reproduces_the_in_memory_rows_exactly(
            self, rows, tmp_path):
        """Export, load back through the real structured loader, compare.

        This is the round trip that settles whether an adapter is needed between
        the UI and the linter. It is not: `_normalize_structured_row` already
        restores `what` to a list (via `_parse_what_cell`) and `enabled` to a
        bool, so the file shape and the memory shape reconcile in the loader the
        application already ships.
        """
        h = get_harmoniser()
        hp = _harm_parser()
        out = tmp_path / "c.csv"
        h._export_csv(rows, str(out))

        loaded = hp._load_structured_criteria_table(str(out))
        raw_rows = loaded[0] if isinstance(loaded, tuple) else loaded
        restored = [hp._normalize_structured_row(r) for r in raw_rows]

        assert len(restored) == len(rows)
        for original, back in zip(rows, restored):
            assert frozenset(back) == ROW_KEYS
            for key in sorted(ROW_KEYS):
                assert back[key] == original[key], (
                    "%s[%s] did not survive the round trip: %r -> %r"
                    % (original["id"], key, original[key], back[key])
                )

    def test_a_hand_edited_what_cell_stays_a_list(self, rows):
        """`_begin_edit`'s `save` writes `_parse_what_cell(...)`, so an edit
        cannot turn `what` into a string behind the linter's back."""
        hp = _harm_parser()
        row = dict(rows[4])                      # EC-1, operator=equals
        row["what"] = hp._parse_what_cell(row["operator"], "French;Spanish")
        assert isinstance(row["what"], list)
        assert row["what"] == ["French", "Spanish"]


class TestTheLinterReadsAllThreeShapesIdentically:
    """No adapter is required, and this is what says so."""

    def test_in_memory_and_reloaded_and_raw_csv_agree(self, rows, a_columns, tmp_path):
        import csv as _csv
        h = get_harmoniser()
        hp = _harm_parser()
        lint = _linter()

        out = tmp_path / "c.csv"
        h._export_csv(rows, str(out))
        loaded = hp._load_structured_criteria_table(str(out))
        raw_rows = loaded[0] if isinstance(loaded, tuple) else loaded
        restored = [hp._normalize_structured_row(r) for r in raw_rows]
        with out.open(encoding="utf-8-sig", newline="") as fh:
            as_csv = list(_csv.DictReader(fh))

        in_memory = _findings(lint.lint_criteria(rows, a_columns))
        reloaded = _findings(lint.lint_criteria(restored, a_columns))
        raw = _findings(lint.lint_criteria(as_csv, a_columns))

        assert in_memory == reloaded == raw, (
            "The linter reads the three shapes differently, so what a user is "
            "told depends on how the table reached the screen.\n"
            "in-memory: %s\nreloaded : %s\nraw csv  : %s"
            % (in_memory, reloaded, raw)
        )

    def test_the_three_defective_rows_are_found_in_every_shape(self, rows, a_columns):
        lint = _linter()
        found = _findings(lint.lint_criteria(rows, a_columns))
        assert ("EC-4", "target-mismatch") in found     # F-166
        assert ("EC-1", "dropped-operand") in found     # F-167
        assert ("IC-5", "inert-at-stage") in found      # F-65

    def test_the_five_correct_rows_are_silent(self, rows, a_columns):
        lint = _linter()
        noisy = {cid for cid, _ in _findings(lint.lint_criteria(rows, a_columns))}
        assert noisy == {"EC-1", "EC-4", "IC-5"}, (
            "IC-1, IC-3, IC-4, EC-2 and EC-3 are correctly translated and must "
            "produce nothing: %s" % sorted(noisy)
        )


def _report():
    return _import_plugin("03_harmoniser", "validate_report")


class TestValidateAsItStandsToday:
    """CHARACTERISATION. These assert the CURRENT behaviour, defects included.

    Extracted from `ui.py::HarmoniserView::_validate` without changing it, so the
    commit that changes it has to flip these in the open rather than quietly.
    Every assertion here that is a defect says so.
    """

    def test_the_reference_contract_validates_completely_clean(self, rows, a_columns):
        """THE DEFECT THIS WHOLE WAVE IS ABOUT. Three of these eight rows do not
        do what their labels say — F-166, F-167 and F-65 — and Validate reports
        nothing at all."""
        vr = _report()
        report = vr.build_validation_report(rows, a_columns)
        assert report.n_rows == 8
        assert report.n_error_rows == 0
        assert report.n_warning_rows == 0
        assert report.ok is True

    def test_it_says_all_good(self, rows, a_columns):
        vr = _report()
        dialog = vr.build_validation_report(rows, a_columns).dialog
        assert dialog.kind == "info"
        assert dialog.title == "Validation OK"
        assert dialog.body == "All good. Warnings: 0"

    def test_the_dialog_names_no_criterion(self, rows, a_columns):
        """DEFECT (F-173): counts, never identities."""
        vr = _report()
        dialog = vr.build_validation_report(rows, a_columns).dialog
        for row in rows:
            assert row["id"] not in dialog.body

    def test_the_per_check_strings_are_computed_and_never_reach_the_dialog(
            self, rows, a_columns):
        """DEFECT (F-173): `_validate_row`'s findings are built and thrown away.

        The extraction keeps them on the marks so a later commit can surface
        them; today nothing reads them.
        """
        vr = _report()
        report = vr.build_validation_report(rows, a_columns)
        assert all(isinstance(m.errors, tuple) for m in report.marks)
        assert all(isinstance(m.warnings, tuple) for m in report.marks)
        assert report.dialog.body == "All good. Warnings: 0"

    def test_all_good_is_shown_even_with_warnings_outstanding(self, rows, a_columns):
        """DEFECT (F-173): the pass message does not depend on the warning count."""
        vr = _report()
        noisy = [dict(r) for r in rows]
        noisy[1]["what"] = ["English", "French"]     # equals with >1 value -> warning
        report = vr.build_validation_report(noisy, a_columns)
        assert report.n_warning_rows >= 1
        assert report.ok is True
        assert report.dialog.title == "Validation OK"
        assert report.dialog.body.startswith("All good.")

    def test_an_error_blocks_and_still_names_nothing(self, a_columns):
        vr = _report()
        broken = [{
            "stage": "EH", "id": "EC-9", "type": "exclude", "scope": "metadata",
            "label": "x", "operator": "not_an_operator", "target": "lang",
            "what": ["x"], "threshold": "", "enabled": True, "source_text": "",
        }]
        report = vr.build_validation_report(broken, a_columns)
        assert report.n_error_rows == 1
        assert report.ok is False
        assert report.dialog.kind == "error"
        assert report.dialog.body == "1 row(s) have errors. Fix them before export."
        assert "EC-9" not in report.dialog.body

    def test_no_rows_says_nothing_at_all(self, a_columns):
        vr = _report()
        report = vr.build_validation_report([], a_columns)
        assert report.ok is False
        assert report.dialog is None

    def test_no_corpus_asks_for_the_a_vector(self, rows):
        vr = _report()
        report = vr.build_validation_report(rows, [])
        assert report.ok is False
        assert report.dialog == vr.Dialog("warning", "Missing A", "Load A vector first.")

    def test_show_ok_false_suppresses_the_dialog_but_not_the_verdict(
            self, rows, a_columns):
        """The export path. `ok` must not depend on whether a dialog was asked for."""
        vr = _report()
        loud = vr.build_validation_report(rows, a_columns, show_ok=True)
        quiet = vr.build_validation_report(rows, a_columns, show_ok=False)
        assert quiet.dialog is None
        assert loud.ok == quiet.ok is True

    def test_row_tints_are_exclusive_and_error_wins(self, a_columns):
        vr = _report()
        both = [{
            "stage": "EL", "id": "EC-9", "type": "exclude", "scope": "metadata",
            "label": "x", "operator": "equals", "target": "lang",
            "what": ["a", "b"], "threshold": "nope", "enabled": True,
            "source_text": "",
        }]
        report = vr.build_validation_report(both, a_columns)
        mark = report.marks[0]
        assert mark.errors and mark.warnings
        assert mark.tag == vr.TAG_ERROR

    def test_the_warning_count_and_the_tints_disagree(self, a_columns):
        """DEFECT, faithfully reproduced: a row with BOTH errors and warnings is
        tinted `error` but still counted into the warning total, because the
        original used two independent `if`s over one call."""
        vr = _report()
        both = [{
            "stage": "EL", "id": "EC-9", "type": "exclude", "scope": "metadata",
            "label": "x", "operator": "equals", "target": "lang",
            "what": ["a", "b"], "threshold": "nope", "enabled": True,
            "source_text": "",
        }]
        report = vr.build_validation_report(both, a_columns)
        assert report.n_error_rows == 1
        assert report.n_warning_rows == 1
        assert sum(1 for m in report.marks if m.tag == vr.TAG_WARN) == 0

    def test_the_log_line_is_unchanged(self, rows, a_columns):
        vr = _report()
        report = vr.build_validation_report(rows, a_columns)
        assert report.log_line == "Validate: 8 rows, errors=0, warnings=0"
