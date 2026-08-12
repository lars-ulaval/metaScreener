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
        body = vr.build_validation_report(rows, a_columns).dialog.body
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
            "Validate: 8 rows, errors=0, warnings=0, findings=4")


class TestTheLinterIsWiredInAndBlocksNothing:
    """The constraint that defines the feature: warn, never block."""

    def test_the_three_defective_rows_produce_findings_through_the_wired_path(
            self, rows, a_columns):
        """Not through `lint_criteria` directly — through what Validate builds."""
        vr = _report()
        report = vr.build_validation_report(rows, a_columns)
        found = sorted((f.criterion_id, f.check) for f in report.findings)
        assert found == [
            ("EC-1", "dropped-operand"),      # F-167
            ("EC-4", "dropped-operand"),
            ("EC-4", "target-mismatch"),      # F-166
            ("IC-5", "inert-at-stage"),       # F-65
        ]

    def test_the_five_correct_rows_produce_nothing_through_the_wired_path(
            self, rows, a_columns):
        vr = _report()
        report = vr.build_validation_report(rows, a_columns)
        noisy = {f.criterion_id for f in report.findings}
        assert noisy == {"EC-1", "EC-4", "IC-5"}
        for quiet in ("IC-1", "IC-3", "IC-4", "EC-2", "EC-3"):
            assert quiet not in noisy

    def test_findings_do_not_change_the_verdict(self, rows, a_columns):
        """`ok` is what gates export. Four findings, and it is still True."""
        vr = _report()
        report = vr.build_validation_report(rows, a_columns)
        assert len(report.findings) == 4
        assert report.ok is True

    def test_a_table_of_nothing_but_findings_still_passes(self, a_columns):
        """Every row mistranslated, and export is still permitted."""
        vr = _report()
        rows, cols = _production_rows()
        bad = [r for r in rows if r["id"] in {"EC-1", "EC-4", "IC-5"}]
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
        rows, cols = _production_rows()
        bad = [r for r in rows if r["id"] in {"EC-1", "EC-4", "IC-5"}]
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
        report = vr.build_validation_report(rows, a_columns)
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
        assert tinted == {"EC-1", "EC-4", "IC-5"}

    def test_the_five_correct_rows_are_not_tinted(self, rows, a_columns):
        vr = _report()
        report = vr.build_validation_report(rows, a_columns)
        untinted = {m.criterion_id for m in report.marks if not m.tag}
        assert untinted == {"IC-1", "IC-3", "IC-4", "EC-2", "EC-3"}

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

    def test_tag_precedence_is_declared_once(self):
        vr = _report()
        assert vr.TAG_PRECEDENCE == (vr.TAG_ERROR, vr.TAG_WARN, vr.TAG_LINT)

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
