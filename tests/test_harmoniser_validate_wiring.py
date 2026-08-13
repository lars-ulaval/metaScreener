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


def _pre_repair_rows():
    """The rules the translator emitted BEFORE wave 13d repaired F-166/F-167.

    `tests/golden/criteria_harmonized_v3.1.0.csv`, which was captured from the
    defective translator and is deliberately not re-captured -- it is the
    criteria input for six downstream replay tests. It is the repository's own
    record of the two defects, and the fixture for proving the wired path still
    surfaces them now that the live table no longer contains an instance.
    """
    import csv as _csv
    hp = _import_plugin("03_harmoniser", "parser")
    with GOLDEN.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(_csv.DictReader(fh))
    # Back to the IN-MEMORY shape the View holds: `what` a list, `enabled` a
    # bool. Reading the CSV raw would leave `what` a string, which makes
    # `_validate_row` emit "'what' was not a list; coerced" for every row and
    # drowns the findings under eight warnings.
    for r in rows:
        r["what"] = hp._parse_what_cell(r.get("operator", "contains"), r.get("what", ""))
        r["enabled"] = str(r.get("enabled", "1")).strip() not in {"0", "false", "no", ""}
    return rows


# ---------------------------------------------------------------------------


class TestTheShapeTheUiHandsTheLinter:
    """The highest-risk item in this wave, settled by execution.

    All four writers of `_UiState.rows` are checked, because `_validate` cannot
    tell which one produced what it is iterating:

      - `ui.py::HarmoniserView._harmonise_no_llm` (free text, and the
        infer-missing-fields branch over already-loaded rows)
      - `parser.py::_normalize_structured_row` (a loaded CSV/XLSX table)
      - `ui.py::HarmoniserView._on_double_click`'s `save` closures (a hand-edited
        cell) — there are three of them, one per editor widget
      - `llm_refine.py::_llm_refine` (the LLM refinement pass)
    """

    def test_the_fixture_is_what_the_harmoniser_emits(self, rows, tmp_path):
        """Wave 13d repaired F-167, so fresh inference no longer equals the
        golden. The golden records the DEFECTIVE translator's output and is
        deliberately not re-captured — six downstream tests consume it as their
        criteria input. Certified against the schema and the id set instead."""
        import csv as _csv
        h = get_harmoniser()
        out = tmp_path / "criteria_harmonized.csv"
        h._export_csv(rows, str(out))
        with out.open(encoding="utf-8-sig", newline="") as fh:
            reader = _csv.DictReader(fh)
            assert reader.fieldnames == sorted(ROW_KEYS, key=[
                "stage", "id", "type", "scope", "label", "operator",
                "target", "what", "threshold", "enabled", "source_text"].index)
            exported = list(reader)
        assert [r["id"] for r in exported] == [
            "IC-1", "IC-3", "IC-4", "IC-5", "EC-1", "EC-2", "EC-3", "EC-4"]

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
        """`_on_double_click`'s entry `save` writes `_parse_what_cell(...)`, so
        an edit cannot turn `what` into a string behind the linter's back."""
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
        assert found == [("IC-5", "inert-at-stage")], (
            "F-166 and F-167 are repaired in wave 13d; only F-65's row remains, "
            "and it is its own wave's"
        )
        # ...and the CLASS is still caught, on the pre-repair table:
        pre = _findings(lint.lint_criteria(_pre_repair_rows(), a_columns))
        assert ("EC-4", "target-mismatch") in pre        # F-166
        assert ("EC-1", "dropped-operand") in pre        # F-167

    def test_the_five_correct_rows_are_silent(self, rows, a_columns):
        lint = _linter()
        noisy = {cid for cid, _ in _findings(lint.lint_criteria(rows, a_columns))}
        assert noisy == {"IC-5"}, (
            "after wave 13d every row except F-65's is correctly translated "
            "and must produce nothing: %s" % sorted(noisy)
        )


def _report():
    return _import_plugin("03_harmoniser", "validate_report")


class TestValidateAsItStandsToday:
    """CHARACTERISATION. These assert the CURRENT behaviour, defects included.

    Extracted from `ui.py::HarmoniserView::_validate` without changing it, so the
    commit that changes it has to flip these in the open rather than quietly.
    Every assertion here that is a defect says so.
    """

    def test_the_rule_level_checks_still_see_nothing(self, rows, a_columns):
        """UNCHANGED, and it is why the linter had to exist: `_validate_row`
        reports errors=0 warnings=0 on all eight rows, three of which do not do
        what their labels say (F-166, F-167, F-65)."""
        vr = _report()
        report = vr.build_validation_report(rows, a_columns)
        assert report.n_rows == 8
        assert report.n_error_rows == 0
        assert report.n_warning_rows == 0
        assert report.ok is True

    def test_it_no_longer_says_all_good(self, rows, a_columns):
        """FLIPPED. Was: kind=info, title="Validation OK",
        body="All good. Warnings: 0" — with three mistranslated rows on screen."""
        vr = _report()
        dialog = vr.build_validation_report(rows, a_columns).dialog
        assert dialog.kind == "info"
        assert dialog.title == "Criteria checked"
        assert "All good" not in dialog.body

    def test_the_dialog_now_names_every_criterion(self, rows, a_columns):
        """FLIPPED TWICE. Was: named no criterion at all. Then: a bare count,
        "4 things worth a look." Now: each finding, in the user's terms."""
        vr = _report()
        report = vr.build_validation_report(rows, a_columns)
        report = vr.build_validation_report(_pre_repair_rows(), a_columns)
        body = report.dialog.body
        assert len(report.findings) == 4
        for crit_id in ("EC-1", "EC-4", "IC-5"):
            assert crit_id in body
        # Two criteria, three findings — EC-4 trips two checks.
        assert "2 criteria may not do what their wording says:" in body
        assert "1 criterion will not run at all:" in body

    def test_the_dialog_says_what_the_rule_will_do_not_which_check_fired(
            self, rows, a_columns):
        vr = _report()
        body = vr.build_validation_report(_pre_repair_rows(), a_columns).dialog.body
        assert 'the rule reads "doc_type" instead' in body
        assert "will never be evaluated" in body
        for check_name in ("target-mismatch", "dropped-operand",
                           "inert-at-stage", "MISTRANSLATED", "INERT"):
            assert check_name not in body, (
                "%s is the engine's vocabulary, not the user's." % check_name
            )

    def test_the_dialog_says_it_does_not_block(self, rows, a_columns):
        vr = _report()
        body = vr.build_validation_report(rows, a_columns).dialog.body
        assert "these are notes, not a gate" in body

    def test_the_per_check_strings_now_reach_the_dialog(
            self, rows, a_columns):
        """FLIPPED — F-173's other half. `_validate_row`'s per-check strings
        were computed and discarded; they now reach the user, by criterion id."""
        vr = _report()
        noisy = [dict(r) for r in rows]
        noisy[1]["what"] = ["English", "French"]     # equals with >1 value
        report = vr.build_validation_report(noisy, a_columns)
        warned = [m for m in report.marks if m.warnings][0]
        assert warned.criterion_id in report.dialog.body
        assert warned.warnings[0] in report.dialog.body

    def test_all_good_is_no_longer_shown_with_warnings_outstanding(
            self, rows, a_columns):
        """FLIPPED. Was: title="Validation OK", body started "All good." with a
        warning outstanding."""
        vr = _report()
        noisy = [dict(r) for r in rows]
        noisy[1]["what"] = ["English", "French"]     # equals with >1 value -> warning
        report = vr.build_validation_report(noisy, a_columns)
        assert report.n_warning_rows >= 1
        assert report.ok is True
        assert report.dialog.title == "Criteria checked"
        assert "All good" not in report.dialog.body
        assert "1 row was adjusted or is worth a look:" in report.dialog.body

    def test_all_good_survives_only_when_there_is_genuinely_nothing(self, a_columns):
        """The one case that still says it, and it has to be earned."""
        vr = _report()
        clean = [{
            "stage": "IH", "id": "IC-9", "type": "include", "scope": "metadata",
            "label": "The paper is written in English.", "operator": "equals",
            "target": "lang", "what": ["English"], "threshold": "",
            "enabled": True, "source_text": "",
        }]
        report = vr.build_validation_report(clean, a_columns)
        assert report.findings == ()
        assert report.dialog == vr.Dialog("info", "Validation OK", "All good.")

    def test_an_error_blocks_and_now_names_the_row(self, a_columns):
        """FLIPPED. Was: "1 row(s) have errors. Fix them before export." with
        the id absent, leaving the user to find it by tint."""
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
        assert report.dialog.title == "Validation failed"
        assert "EC-9" in report.dialog.body
        assert "1 row has an error and export is blocked" in report.dialog.body
        assert "1 row cannot be exported until it is fixed:" in report.dialog.body

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

    def test_the_log_line_now_carries_the_finding_count(self, rows, a_columns):
        """FLIPPED. Was: "Validate: 8 rows, errors=0, warnings=0"."""
        vr = _report()
        report = vr.build_validation_report(rows, a_columns)
        assert report.log_line == (
            "Validate: 8 rows, errors=0, warnings=0, findings=1")


class TestTheLinterIsWiredInAndBlocksNothing:
    """The constraint that defines the feature: warn, never block."""

    def test_the_three_defective_rows_produce_findings_through_the_wired_path(
            self, rows, a_columns):
        """Not through `lint_criteria` directly — through what Validate builds."""
        vr = _report()
        report = vr.build_validation_report(rows, a_columns)
        found = sorted((f.criterion_id, f.check) for f in report.findings)
        assert found == [("IC-5", "inert-at-stage")], (
            "F-166 and F-167 are repaired; F-65's row is not this wave's"
        )
        pre = vr.build_validation_report(_pre_repair_rows(), a_columns)
        pre_found = sorted((f.criterion_id, f.check) for f in pre.findings)
        assert ("EC-4", "target-mismatch") in pre_found
        assert ("EC-1", "dropped-operand") in pre_found

    def test_the_five_correct_rows_produce_nothing_through_the_wired_path(
            self, rows, a_columns):
        vr = _report()
        report = vr.build_validation_report(rows, a_columns)
        noisy = {f.criterion_id for f in report.findings}
        assert noisy == {"IC-5"}
        for quiet in ("IC-1", "IC-3", "IC-4", "EC-1", "EC-2", "EC-3", "EC-4"):
            assert quiet not in noisy

    def test_findings_do_not_change_the_verdict(self, rows, a_columns):
        """`ok` is what gates export. Four findings, and it is still True."""
        vr = _report()
        report = vr.build_validation_report(_pre_repair_rows(), a_columns)
        assert len(report.findings) == 4
        assert report.ok is True

    def test_a_table_of_nothing_but_findings_still_passes(self, a_columns):
        """Every row mistranslated, and export is still permitted."""
        vr = _report()
        _rows, cols = _production_rows()
        bad = [r for r in _pre_repair_rows() if r["id"] in {"EC-1", "EC-4", "IC-5"}]
        report = vr.build_validation_report(bad, cols)
        assert len(report.findings) >= 3
        assert report.ok is True
        assert report.dialog.kind == "info"

    def test_the_dialog_is_never_a_prompt(self, rows, a_columns):
        """Nothing here may look like a blocking question."""
        vr = _report()
        report = vr.build_validation_report(rows, a_columns)
        assert report.dialog.kind in {"info", "warning", "error"}
        assert "?" not in report.dialog.body, (
            "A question mark in a validation dialog reads as a prompt."
        )
        for phrase in ("Are you sure", "Do you want", "Continue anyway",
                       "Proceed", "Cancel", "Override"):
            assert phrase not in report.dialog.body

    def test_errors_still_block_exactly_as_before(self, a_columns):
        """The linter changed nothing about the one thing that DOES gate."""
        vr = _report()
        broken = [{
            "stage": "EH", "id": "EC-9", "type": "exclude", "scope": "metadata",
            "label": "x", "operator": "not_an_operator", "target": "lang",
            "what": ["x"], "threshold": "", "enabled": True, "source_text": "",
        }]
        report = vr.build_validation_report(broken, a_columns)
        assert report.ok is False
        assert report.dialog.kind == "error"
        assert report.dialog.title == "Validation failed"


class TestTheValidatePathSurvivesALinterThatThrows:
    """`lint_criteria` promises it raises nothing. "It promised" is not a reason
    to let the Validate button die, so the failure is induced and tested."""

    @staticmethod
    def _exploding(*_a, **_kw):
        raise RuntimeError("induced linter failure")

    def test_validate_still_completes(self, rows, a_columns):
        vr = _report()
        report = vr.build_validation_report(rows, a_columns, lint=self._exploding)
        assert report.n_rows == 8
        assert report.ok is True
        assert report.findings == ()

    def test_it_says_the_check_could_not_run(self, rows, a_columns):
        vr = _report()
        report = vr.build_validation_report(rows, a_columns, lint=self._exploding)
        assert report.lint_error == "RuntimeError: induced linter failure"
        assert "could not run" in report.dialog.body
        assert "RuntimeError: induced linter failure" in report.dialog.body
        assert "The rules themselves were still checked." in report.dialog.body
        assert "these are notes, not a gate" in report.dialog.body

    def test_it_does_not_silently_claim_all_good(self, rows, a_columns):
        """The failure mode that would matter: a broken checker reading as a
        clean bill of health."""
        vr = _report()
        report = vr.build_validation_report(rows, a_columns, lint=self._exploding)
        assert "All good" not in report.dialog.body

    def test_a_failed_linter_does_not_block_export(self, rows, a_columns):
        vr = _report()
        report = vr.build_validation_report(rows, a_columns, lint=self._exploding)
        assert report.ok is True

    def test_the_log_line_records_the_failure(self, rows, a_columns):
        vr = _report()
        report = vr.build_validation_report(rows, a_columns, lint=self._exploding)
        assert "criteria check failed" in report.log_line


class TestTheDialogUnderVolume:
    """The stress case. A messagebox does not scroll, so a long list does not
    become a long dialog — it becomes one whose OK button is off the screen."""

    @staticmethod
    def _many(n_copies):
        _rows, cols = _production_rows()
        bad = [r for r in _pre_repair_rows() if r["id"] in {"EC-1", "EC-4", "IC-5"}]
        out = []
        for i in range(n_copies):
            for r in bad:
                copy = dict(r)
                copy["id"] = "%s-%02d" % (r["id"], i)
                out.append(copy)
        return out, cols

    def test_the_list_is_capped(self):
        vr = _report()
        rows, cols = self._many(12)
        report = vr.build_validation_report(rows, cols)
        assert len(report.findings) == 48
        bullets = [l for l in report.dialog.body.splitlines()
                   if l.strip().startswith("•")]
        assert len(bullets) <= vr.MAX_LISTED

    def test_every_group_that_has_a_heading_has_at_least_one_item(self):
        """The first draft spent the whole budget on the most urgent group and
        left the next one a heading with nothing under it."""
        vr = _report()
        rows, cols = self._many(12)
        lines = vr.build_validation_report(rows, cols).dialog.body.splitlines()
        for i, line in enumerate(lines):
            if not line.endswith(":"):
                continue
            following = [l for l in lines[i + 1:i + 3] if l.strip()]
            assert following and following[0].strip().startswith("•"), (
                "heading %r has no item under it" % line
            )

    def test_the_overflow_is_counted_and_pointed_somewhere(self):
        vr = _report()
        rows, cols = self._many(12)
        body = vr.build_validation_report(rows, cols).dialog.body
        assert "and 29 more of these" in body
        assert "and 11 more of these" in body
        assert "in the log below the table" in body

    def test_the_headings_count_criteria_not_findings(self, rows, a_columns):
        """EC-4 trips two checks. The heading said "3 criteria" for two."""
        vr = _report()
        report = vr.build_validation_report(_pre_repair_rows(), a_columns)
        mistranslated = [f for f in report.findings
                         if f.severity == "MISTRANSLATED"]
        assert len(mistranslated) == 3
        assert len({f.criterion_id for f in mistranslated}) == 2
        assert "2 criteria may not do what their wording says:" in report.dialog.body

    def test_a_wall_of_findings_still_does_not_block(self):
        vr = _report()
        rows, cols = self._many(12)
        report = vr.build_validation_report(rows, cols)
        assert report.ok is True

    def test_the_body_stays_a_readable_size(self):
        vr = _report()
        rows, cols = self._many(40)
        body = vr.build_validation_report(rows, cols).dialog.body
        assert body.count("\n") + 1 < 25, "the dialog has become a wall"


class TestRowTints:
    """The dialog says "every affected row is tinted", so the tints are not
    optional decoration — they are the sentence being true.

    The tag DECISION is here, in the pure function, and `_render_rows` reads it
    rather than deciding a second time. Whether the colours are legible on a
    real screen is HO-13-2's question for the existing two and HO-13-11's for
    the new one; neither can be settled from a test.
    """

    def test_the_three_flagged_rows_are_tinted_lint(self, rows, a_columns):
        vr = _report()
        report = vr.build_validation_report(rows, a_columns)
        tinted = {m.criterion_id for m in report.marks if m.tag == vr.TAG_LINT}
        assert tinted == {"IC-5"}

    def test_the_five_correct_rows_are_not_tinted(self, rows, a_columns):
        vr = _report()
        report = vr.build_validation_report(rows, a_columns)
        untinted = {m.criterion_id for m in report.marks if not m.tag}
        assert untinted == {"IC-1", "IC-3", "IC-4", "EC-1", "EC-2", "EC-3", "EC-4"}

    def test_every_finding_has_a_tinted_row(self, rows, a_columns):
        """The dialog's promise, asserted."""
        vr = _report()
        report = vr.build_validation_report(rows, a_columns)
        tinted = {m.criterion_id for m in report.marks if m.tag}
        for finding in report.findings:
            assert finding.criterion_id in tinted, (
                "%s is reported in the dialog and its row is not tinted, so "
                '"every affected row is tinted" is false.' % finding.criterion_id
            )

    def test_an_error_row_is_not_recoloured_into_something_milder(self, a_columns):
        """`error` is the only tint that stops anything; a linter finding on the
        same row must not overwrite it."""
        vr = _report()
        broken = [{
            "stage": "EH", "id": "EC-4", "type": "exclude", "scope": "metadata",
            "label": "The publication venue contains ICRA OR IROS.",
            "operator": "not_an_operator", "target": "doc_type",
            "what": ["conference"], "threshold": "", "enabled": True,
            "source_text": "",
        }]
        report = vr.build_validation_report(broken, a_columns)
        assert report.findings, "the linter should still have something to say"
        assert report.marks[0].tag == vr.TAG_ERROR

    def test_every_tag_this_module_emits_has_a_colour_bound_to_it(self):
        """Load-bearing, where the old TAG_PRECEDENCE assertion was a tautology
        restating a constant nothing read. A tag renamed on one side and not the
        other stops painting silently."""
        import ast

        vr = _report()
        ui = _import_plugin("03_harmoniser", "ui")
        source = Path(ui.__file__).read_text(encoding="utf-8")
        bound = set()
        for node in ast.walk(ast.parse(source)):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "tag_configure"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)):
                bound.add(node.args[0].value)
        assert set(vr.ALL_TAGS) <= bound, (
            "tags with no colour bound in ui.py: %s"
            % sorted(set(vr.ALL_TAGS) - bound)
        )

    def test_a_failed_linter_leaves_the_existing_tints_alone(self, rows, a_columns):
        vr = _report()

        def exploding(*_a, **_kw):
            raise RuntimeError("induced")

        report = vr.build_validation_report(rows, a_columns, lint=exploding)
        assert all(m.tag == "" for m in report.marks)


class TestALinterThatMisbehavesRatherThanThrows:
    """Found by this session's own adversarial probe, after the wiring commit.

    `lint_criteria` returns `Finding`s. The defensive wrapper was written for a
    linter that RAISES and did not cover one that returns something unusable —
    and the consumption of the result happens outside the `try`, so it escaped.
    """

    def test_a_result_that_is_not_findings_does_not_raise(self, rows, a_columns):
        vr = _report()
        for name, bad in (
            ("None", lambda *a, **k: None),
            ("a string", lambda *a, **k: "oops"),
            ("strings", lambda *a, **k: ["a", "b"]),
            ("ints", lambda *a, **k: [1, 2]),
            ("dicts", lambda *a, **k: [{"criterion_id": "EC-1"}]),
        ):
            report = vr.build_validation_report(rows, a_columns, lint=bad)
            assert report.ok is True, name
            assert report.findings == (), name
            assert report.lint_error, (
                "%s must be reported as a failed check, not swallowed" % name
            )
            assert "could not run" in report.dialog.body, name

    def test_a_finding_with_an_unknown_severity_is_still_shown(self, rows, a_columns):
        """The worst failure available here: a finding exists, is counted, and
        the user is told "All good." because no heading matched its severity."""
        vr = _report()
        linter = _linter()

        def odd(*_a, **_kw):
            return [linter.Finding("EC-1", "x", "SOMETHING_NEW", "EC-1 is odd.", "")]

        report = vr.build_validation_report(rows, a_columns, lint=odd)
        assert len(report.findings) == 1
        assert "All good" not in report.dialog.body
        assert "EC-1 is odd." in report.dialog.body

    def test_a_finding_with_no_message_does_not_render_as_none(self, rows, a_columns):
        vr = _report()
        linter = _linter()

        def blank(*_a, **_kw):
            return [linter.Finding("EC-1", "x", "INERT", None, "")]

        report = vr.build_validation_report(rows, a_columns, lint=blank)
        assert "None" not in report.dialog.body

    def test_keyboard_interrupt_is_not_swallowed(self, rows, a_columns):
        """A user pressing Ctrl-C must not be reported as a linter defect."""
        vr = _report()

        def interrupted(*_a, **_kw):
            raise KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            vr.build_validation_report(rows, a_columns, lint=interrupted)


class TestWhatTheRefutationPassFound:
    """Four behavioural defects, all reproduced before being accepted."""

    def test_a_non_mapping_row_does_not_crash_the_validate_path(self, rows, a_columns):
        """`linter.py::UNREADABLE_ROW` exists so a malformed row becomes a
        finding rather than a crash — but `build_validation_report` looped
        `_validate_row` over every row FIRST, and that does `row.get(...)`. The
        guard was downstream of the thing it was guarding."""
        vr = _report()
        report = vr.build_validation_report(list(rows) + ["garbage"], a_columns)
        assert report.n_rows == 9
        assert report.ok is True
        assert any(f.check == "unreadable-row" for f in report.findings)

    def test_findings_in_the_error_dialog_say_they_are_not_what_blocks(
            self, rows, a_columns):
        """One malformed row put every criteria finding inside a red
        "Validation failed / export is blocked" box with no statement anywhere
        that the findings block nothing."""
        vr = _report()
        broken = _pre_repair_rows() + [{
            "stage": "EH", "id": "EC-9", "type": "exclude", "scope": "metadata",
            "label": "x", "operator": "not_an_operator", "target": "lang",
            "what": "x", "threshold": "", "enabled": "1", "source_text": "",
        }]
        report = vr.build_validation_report(broken, a_columns)
        assert report.dialog.kind == "error"
        assert "EC-4" in report.dialog.body, "findings are listed here"
        assert "EC-9" in report.dialog.body, "and so is the row that blocks"
        assert "do not block" in report.dialog.body, (
            "the dialog must say which half is the gate and which is a note"
        )

    def test_blank_criterion_ids_are_not_collapsed_into_one(self, rows, a_columns):
        """Three different mistranslated rules, all with blank ids, were
        announced as "1 criterion may not do what its wording says"."""
        vr = _report()
        blank = []
        for src in rows:
            if src["id"] in ("EC-1", "EC-4"):
                copy = dict(src)
                copy["id"] = ""
                blank.append(copy)
        report = vr.build_validation_report(blank, a_columns)
        assert "1 criterion may not do what its wording says:" not in \
            report.dialog.body, (
            "two rules, both blank-id, must not be announced as one criterion"
        )

    def test_the_cap_is_on_the_dialog_not_on_each_section(self, rows, a_columns):
        """MAX_LISTED was applied per section — bad rows, warned rows, and each
        severity group — so five sections could each spend eight."""
        vr = _report()
        mixed = []
        for i in range(3):
            r = dict(rows[0]); r.update(id="ERR-%d" % i, operator="not_an_operator")
            mixed.append(r)
        for i in range(3):
            r = dict(rows[1]); r.update(id="WARN-%d" % i, what=["English", "French"])
            mixed.append(r)
        ec4 = [r for r in rows if r["id"] == "EC-4"][0]
        for i in range(9):
            r = dict(ec4); r["id"] = "F-%d" % i
            mixed.append(r)
        body = vr.build_validation_report(mixed, a_columns).dialog.body
        bullets = [l for l in body.splitlines() if l.strip().startswith("•")]
        assert len(bullets) <= vr.MAX_LISTED, (
            "%d bullets across the whole dialog" % len(bullets)
        )
        # Same wall threshold the findings-only volume test uses, applied to the
        # worst case this module can produce: five sections, all populated.
        assert body.count("\n") + 1 < 25, "the dialog has become a wall"


class TestTheViewItself:
    """The refutation pass's sharpest finding: NOTHING in the suite executed a
    single line of `HarmoniserView`. Reverting `_validate` to its pre-session
    body — linter never called, "All good. Warnings: 0" back — left all 1698
    tests green, i.e. the wiring commit could be undone in its entirety and the
    suite would not notice.

    The View cannot be instantiated (conftest makes `tkinter` a MagicMock, so
    `ttk.Frame.__init__` builds nothing real), but its METHODS are ordinary
    functions. They are called here against a stub `self` carrying only the
    attributes they touch, which is enough to execute the real bodies.
    """

    class _Tree:
        def __init__(self):
            self.rows = []

        def insert(self, _parent, _where, values=(), tags=()):
            self.rows.append((values, tags))

        def delete(self, *_a, **_kw):
            self.rows = []

        def get_children(self, *_a, **_kw):
            return []

        def tag_configure(self, *_a, **_kw):
            pass

    class _Stub:
        """Only what `_validate` and `_render_rows` actually touch."""

        def __init__(self, rows, a_columns, tree):
            from types import SimpleNamespace
            self.state = SimpleNamespace(rows=rows, a_columns=a_columns)
            self.tree = tree
            self.logged = []

        def _log(self, line):
            self.logged.append(line)

        def _clear_table(self):
            self.tree.delete()

        def _refresh_buttons(self):
            pass

        def _render_rows(self, with_validation=False, marks=None):
            """`_validate` calls this. Bound to the REAL body by the caller, so
            what is exercised is the shipped render, including whether
            `_validate` hands its own marks down or lets a second evaluation
            happen."""
            return self._render_impl(
                self, with_validation=with_validation, marks=marks)

    @staticmethod
    def _method(name):
        """The real function body out of `ui.py`, bound to nothing.

        `HarmoniserView` subclasses `ttk.Frame`, which conftest has replaced
        with a `MagicMock`, so the class object is a mock and attribute access
        on it returns mocks rather than the methods. The source is still real:
        this lifts the named `def` out of the class by AST and compiles it
        against `ui`'s own globals, so the code that runs is exactly the code
        that ships.
        """
        import ast
        import textwrap

        ui = _import_plugin("03_harmoniser", "ui")
        source = Path(ui.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "HarmoniserView":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == name:
                        module = ast.Module(body=[item], type_ignores=[])
                        ast.fix_missing_locations(module)
                        namespace = dict(ui.__dict__)
                        exec(compile(module, ui.__file__, "exec"), namespace)
                        return namespace[name]
        raise AssertionError("HarmoniserView.%s not found in ui.py" % name)

    def _run_validate(self, rows, a_columns, monkeypatch):
        ui = _import_plugin("03_harmoniser", "ui")
        shown = []
        for kind in ("showinfo", "showerror", "showwarning"):
            monkeypatch.setattr(
                ui.messagebox, kind,
                lambda title, body, _k=kind: shown.append((_k, title, body)),
                raising=False,
            )
        monkeypatch.setattr(ui, "_SHOW", {
            "info": lambda t, b: shown.append(("showinfo", t, b)),
            "error": lambda t, b: shown.append(("showerror", t, b)),
            "warning": lambda t, b: shown.append(("showwarning", t, b)),
        })
        stub = self._Stub(rows, a_columns, self._Tree())
        stub._render_impl = self._method("_render_rows")
        ok = self._method("_validate")(stub)
        return ok, shown, stub

    def test_the_validate_button_really_calls_the_linter(
            self, rows, a_columns, monkeypatch):
        """Reverting `_validate` to its pre-session body must fail HERE."""
        ok, shown, stub = self._run_validate(
            [dict(r) for r in rows], a_columns, monkeypatch)
        assert ok is True
        assert len(shown) == 1
        kind, title, body = shown[0]
        assert kind == "showinfo"
        assert title == "Criteria checked"
        assert "IC-5" in body, "F-65's row is the one finding that survives 13d"
        assert "EC-4" not in body, "F-166 repaired"
        assert "EC-1" not in body, "F-167 repaired"
        assert "All good" not in body

    def test_the_validate_button_logs_the_finding_count(
            self, rows, a_columns, monkeypatch):
        _ok, _shown, stub = self._run_validate(
            [dict(r) for r in rows], a_columns, monkeypatch)
        assert stub.logged == ["Validate: 8 rows, errors=0, warnings=0, findings=1"]

    def test_the_validate_button_uses_the_right_messagebox(
            self, a_columns, monkeypatch):
        """`_SHOW` maps kind to a messagebox call; sending an info dialog to
        `showerror` would turn every note into an alarm."""
        broken = [{
            "stage": "EH", "id": "EC-9", "type": "exclude", "scope": "metadata",
            "label": "x", "operator": "not_an_operator", "target": "lang",
            "what": ["x"], "threshold": "", "enabled": True, "source_text": "",
        }]
        ok, shown, _stub = self._run_validate(broken, a_columns, monkeypatch)
        assert ok is False
        assert shown[0][0] == "showerror"
        assert shown[0][1] == "Validation failed"

    def test_render_rows_paints_the_lint_tint(self, rows, a_columns):
        stub = self._Stub([dict(r) for r in rows], a_columns, self._Tree())
        self._method("_render_rows")(stub, with_validation=True)
        painted = {vals[1]: (tags[0] if tags else "")
                   for vals, tags in stub.tree.rows}
        assert painted["IC-5"] == "lint", "F-65's row, still flagged"
        assert painted["IC-3"] == ""
        assert painted["EC-1"] == "", "F-167 repaired in wave 13d"
        assert painted["EC-4"] == "", "F-166 repaired in wave 13d"

    def test_render_rows_paints_nothing_without_validation(self, rows, a_columns):
        stub = self._Stub([dict(r) for r in rows], a_columns, self._Tree())
        self._method("_render_rows")(stub, with_validation=False)
        assert all(tags == () for _vals, tags in stub.tree.rows)

    def test_the_dialog_and_the_tints_agree(self, a_columns, monkeypatch):
        """The two-pass defect: `_validate` built one report for the dialog and
        `_render_rows` built a second for the tints. `_validate_row` REWRITES
        the row it inspects, so the second pass saw a repaired table — a row
        named in the dialog as "adjusted or worth a look" was then tinted
        nothing at all."""
        adjusted = [{
            "stage": "EH", "id": "EC-9", "type": "exclude", "scope": "metadata",
            "label": "The paper is written in French.", "operator": "equals",
            "target": "lang", "what": ["French"], "threshold": "0.60",
            "enabled": True, "source_text": "",
        }]
        _ok, shown, stub = self._run_validate(adjusted, a_columns, monkeypatch)
        body = shown[0][2]
        painted = {vals[1]: (tags[0] if tags else "")
                   for vals, tags in stub.tree.rows}
        if "EC-9" in body:
            assert painted["EC-9"], (
                "the dialog names EC-9 and the table gives the user nothing to "
                "look at: dialog=%r tints=%r" % (body, painted)
            )

    def test_the_notice_heading_is_the_users_terms_too(self, rows):
        """The NOTICE heading was rendered by no test, so it could be rewritten
        into the engine's vocabulary and the suite would not notice. NOTICE is
        reachable in production the moment the corpus lacks a column a criterion
        targets, and it lands beside the other two headings."""
        vr = _report()
        without_lang = [c for c in _production_rows()[1] if c != "lang"]
        report = vr.build_validation_report(rows, without_lang)
        assert any(f.severity == "NOTICE" for f in report.findings)
        body = report.dialog.body
        assert "thing worth checking:" in body or "things worth checking:" in body
        for engine_word in ("NOTICE", "MISTRANSLATED", "INERT", "severity",
                            "unresolved-target", "target-mismatch"):
            assert engine_word not in body, (
                "%s is the engine's vocabulary, not the user's" % engine_word
            )

    def test_every_heading_the_module_can_emit_is_the_users_terms(self):
        """A property rather than a blacklist: no heading may contain a check
        name, a severity constant, or an underscore."""
        vr = _report()
        lint = _linter()
        constants = (lint.MISTRANSLATED, lint.INERT, lint.NOTICE)
        for singular, plural in vr._HEADINGS.values():
            for text in (singular, plural % 3):
                assert "_" not in text, text
                for constant in constants:
                    assert constant not in text, text
