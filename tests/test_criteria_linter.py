# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_criteria_linter.py — the criteria linter (wave 13c session A).

The linter answers one question: **does this rule do what its label says?**
It warns and never blocks, so nothing here asserts that anything raises.

THE FIXTURES CERTIFY THEMSELVES. Every row these tests lint is produced by
the real harmoniser path — `_parse_free_text_criteria` → `_infer_criterion_details`
— over `samples/ic_ec_12.txt` against `samples/20260122_1654_aggregate.csv`, and
`test_the_fixture_is_what_the_harmoniser_actually_emits` exports those rows and
compares them byte-for-byte against `tests/golden/criteria_harmonized_v3.1.0.csv`.
A hand-typed row that the harmoniser could never emit certifies nothing, and this
register has three recorded instances of that failure.

The two rows the linter exists for are EC-1 (F-167) and EC-4 (F-166), and they are
still defective at this commit **on purpose**: `inference.py` is not fixed in this
wave, so the linter can be proven against the defect rather than against its memory.
"""

import importlib
from pathlib import Path

import pytest

from conftest import (
    AGGREGATE_CSV,
    IC_EC_FILE,
    _import_plugin,
    get_harmoniser,
)

GOLDEN = Path(__file__).parent / "golden" / "criteria_harmonized_v3.1.0.csv"


def _linter():
    """Import the linter directly, NOT through plugin.py.

    plugin.py does `from tkinter import ttk` at module scope; reaching the
    linter through it would make every caller drag in a GUI dependency.
    """
    return _import_plugin("03_harmoniser", "linter")


# ---------------------------------------------------------------------------
# The fixture: the real production path, returning rows rather than a file.
# Mirrors tests/test_harmoniser_regression.py::_harmonise_to_csv exactly.
# ---------------------------------------------------------------------------

def _harmonised_rows():
    h = get_harmoniser()

    a_columns, text_stats = h._load_a_header_and_stats(str(AGGREGATE_CSV))
    default_text_target = h._get_best_text_targets(a_columns, text_stats)
    default_text_target, _ = h._canonicalize_targets(default_text_target, a_columns)

    parsed = h._parse_free_text_criteria(IC_EC_FILE.read_text(encoding="utf-8-sig"))
    assert parsed, "Sample IC/EC file produced no parsed criteria"

    rows = []
    for crit_id, crit_type, label, source_line in parsed:
        inferred = h._infer_criterion_details(
            crit_id=crit_id,
            crit_type=crit_type,
            label=label,
            a_columns=list(a_columns),
            default_text_target=default_text_target,
        )
        stage = inferred["stage"]
        rows.append({
            "stage": stage,
            "id": crit_id,
            "type": crit_type,
            "scope": "metadata",
            "label": label,
            "operator": inferred["operator"],
            "target": inferred["target"],
            "what": inferred["what"],
            "threshold": f"{h.DEFAULT_THRESHOLD:.2f}" if stage in {"EL", "IL"} else "",
            "enabled": True,
            "source_text": source_line,
        })
    return rows, list(a_columns)


@pytest.fixture(scope="module")
def harmonised():
    return _harmonised_rows()


@pytest.fixture(scope="module")
def rows(harmonised):
    return harmonised[0]


@pytest.fixture(scope="module")
def a_columns(harmonised):
    return harmonised[1]


def _by_check(findings, check):
    return [f for f in findings if f.check == check]


def _ids(findings):
    return sorted(f.criterion_id for f in findings)


# ---------------------------------------------------------------------------


class TestTheFixtureIsTrustworthy:
    """If this fails, nothing else in this file means anything."""

    def test_the_fixture_is_what_the_harmoniser_actually_emits(self, rows, tmp_path):
        h = get_harmoniser()
        out = tmp_path / "criteria_harmonized.csv"
        h._export_csv(rows, str(out))
        assert out.read_bytes() == GOLDEN.read_bytes(), (
            "The linter's fixture is no longer what the harmoniser emits. Either "
            "the production path changed or this fixture drifted from it; in "
            "either case every assertion below is now about a table that does "
            "not exist."
        )

    def test_the_two_defective_rows_are_still_defective(self, rows):
        """F-166 and F-167 are NOT fixed in this wave, deliberately."""
        by_id = {r["id"]: r for r in rows}
        assert by_id["EC-4"]["target"] == "doc_type", (
            "EC-4 no longer targets doc_type. If inference.py was fixed, the "
            "F-166 regression fixture below is no longer testing anything."
        )
        assert by_id["EC-1"]["what"] == ["French"], (
            "EC-1 no longer drops its second operand. If inference.py was fixed, "
            "the F-167 regression fixture below is no longer testing anything."
        )


class TestTargetMismatch:
    """Check 1 — the label names a column the rule does not target. F-166."""

    CHECK = "target-mismatch"

    def test_it_fires_on_EC_4(self, rows, a_columns):
        lint = _linter()
        found = _by_check(lint.lint_criteria(rows, a_columns), self.CHECK)
        assert _ids(found) == ["EC-4"], (
            "F-166's row is the reason this check exists. Its label says "
            "'venue' and its rule targets doc_type."
        )

    def test_it_does_not_fire_on_the_seven_other_rows(self, rows, a_columns):
        lint = _linter()
        found = _by_check(lint.lint_criteria(rows, a_columns), self.CHECK)
        assert set(_ids(found)) <= {"EC-4"}, (
            "A linter that fires on correct rows gets ignored, which is the "
            "failure mode that matters most here."
        )

    def test_the_finding_says_what_the_rule_actually_does(self, rows, a_columns):
        lint = _linter()
        f = _by_check(lint.lint_criteria(rows, a_columns), self.CHECK)[0]
        assert f.criterion_id == "EC-4"
        assert f.severity == "MISTRANSLATED"
        assert "venue" in f.message and "doc_type" in f.message, (
            "The message must name both the column the user asked for and the "
            "column the rule reads, in the user's terms."
        )

    def test_it_is_skipped_without_corpus_columns(self, rows):
        """No columns means the check cannot run — and must say so, not stay silent."""
        lint = _linter()
        report = lint.lint_criteria(rows)
        assert _by_check(report, self.CHECK) == []
        assert self.CHECK in report.skipped, (
            "A skipped check must be visible, or a caller reads 'no findings' "
            "as 'checked and clean'. That is F-64's shape."
        )


class TestDroppedOperand:
    """Check 2 — the label offers more alternatives than the rule carries. F-167.

    The naive form of this check — "the label contains a conjunction" — fires on
    IC-5, which is correct, and `07_criteria_parsing.md` §7.5 predicted exactly
    that over-inclusion. Two refinements make it clean and both are pinned below,
    because a linter that fires on correct rows gets ignored.
    """

    CHECK = "dropped-operand"

    def test_it_fires_on_EC_1_and_EC_4(self, rows, a_columns):
        lint = _linter()
        found = _by_check(lint.lint_criteria(rows, a_columns), self.CHECK)
        assert _ids(found) == ["EC-1", "EC-4"], (
            "EC-1 is F-167 itself — 'French or Spanish' became one operand. "
            "EC-4 drops both of its operands and so trips this check too."
        )

    def test_it_does_not_fire_on_IC_5_whose_three_operands_are_correct(self, rows, a_columns):
        """The refinement that matters: an `or` between two field names is
        enumerating TARGETS, not values."""
        lint = _linter()
        found = _by_check(lint.lint_criteria(rows, a_columns), self.CHECK)
        assert "IC-5" not in _ids(found), (
            "IC-5's label is 'The title, abstract, or keywords mention training "
            "OR vocational OR workplace.' — three `or` tokens, of which one "
            "enumerates target fields and two enumerate operands. The rule "
            "carries all three operands and is correct."
        )

    def test_it_does_not_fire_on_IC_4_whose_or_forms_a_range(self, rows, a_columns):
        """`gte`/`lte`/`between` express an interval, so 'or later' is already
        carried by the operator."""
        lint = _linter()
        found = _by_check(lint.lint_criteria(rows, a_columns), self.CHECK)
        assert "IC-4" not in _ids(found), (
            "IC-4 is 'The publication year is 2018 or later.' rendered as "
            "`gte year 2018`. The alternative is the operator."
        )

    def test_it_does_not_fire_on_the_llm_rows(self, rows, a_columns):
        """For `llm` the whole sentence is the single operand by design.

        Without this exclusion IC-1 and EC-2 both false-positive: each has two
        alternatives in its label and one operand.
        """
        lint = _linter()
        found = _by_check(lint.lint_criteria(rows, a_columns), self.CHECK)
        assert not ({"IC-1", "EC-2", "EC-3"} & set(_ids(found)))

    def test_the_finding_names_the_operand_that_survived(self, rows, a_columns):
        lint = _linter()
        f = [x for x in _by_check(lint.lint_criteria(rows, a_columns), self.CHECK)
             if x.criterion_id == "EC-1"][0]
        assert f.severity == "MISTRANSLATED"
        assert "French" in f.message, (
            "The user must be able to see which half survived without opening "
            "the table."
        )

    def test_it_needs_no_corpus_columns(self, rows):
        """Decidable from the table alone, so it must run without a corpus."""
        lint = _linter()
        report = lint.lint_criteria(rows)
        assert self.CHECK in report.ran
        assert _ids(_by_check(report, self.CHECK)) == ["EC-1", "EC-4"]


class TestInertAtStage:
    """Check 4 — the operator cannot execute at the assigned stage. F-65.

    The linter REPORTS this; it does not gate it. F-65's own remedy proposes an
    `_validate_row` error, and an error blocks export — the human's decision for
    this feature is warn-clearly-never-block, so both mechanisms should exist and
    they are not the same mechanism.
    """

    CHECK = "inert-at-stage"

    def test_it_fires_on_IC_5(self, rows, a_columns):
        lint = _linter()
        found = _by_check(lint.lint_criteria(rows, a_columns), self.CHECK)
        assert _ids(found) == ["IC-5"], (
            "IC-5 is `contains` at IL, where only `llm` executes. It has never "
            "been applied to any record in any run (F-65)."
        )

    def test_the_finding_says_the_rule_will_not_run(self, rows, a_columns):
        lint = _linter()
        f = _by_check(lint.lint_criteria(rows, a_columns), self.CHECK)[0]
        assert f.severity == "INERT"
        assert "IL" in f.message and "contains" in f.message

    def test_it_does_not_fire_on_the_same_row_rendered_as_llm(self, rows, a_columns):
        """The wave-12 local-run table renders IC-5 as `llm` at IL, which is
        executable. The check must discriminate, not always fire."""
        lint = _linter()
        as_llm = []
        for r in rows:
            r = dict(r)
            if r["id"] == "IC-5":
                r["operator"] = "llm"
                r["what"] = [r["label"]]
            as_llm.append(r)
        found = _by_check(lint.lint_criteria(as_llm, a_columns), self.CHECK)
        assert _ids(found) == []

    def test_the_mirror_case_fires_too(self, rows, a_columns):
        """`llm` at EH/IH is the other direction of the same defect."""
        lint = _linter()
        mutated = []
        for r in rows:
            r = dict(r)
            if r["id"] == "IC-3":       # equals lang English, at IH
                r["operator"] = "llm"
            mutated.append(r)
        found = _by_check(lint.lint_criteria(mutated, a_columns), self.CHECK)
        assert "IC-3" in _ids(found)


class TestTheQuietChecks:
    """Checks 3, 5 and 6 — NOTICE severity, and none has a live instance.

    All three are guards rather than findings-in-waiting: measured across the
    golden, the frozen study input and the wave-12 local-run table, none fires.
    They are tested by mutating a real harmoniser row rather than by inventing
    one, so the shape under test is a shape the producer can actually make.
    """

    def test_unresolved_target_is_silent_on_a_clean_table(self, rows, a_columns):
        lint = _linter()
        assert _by_check(lint.lint_criteria(rows, a_columns), "unresolved-target") == []

    def test_unresolved_target_fires_when_the_corpus_lacks_the_column(self, rows):
        """The same rows against a corpus that has no `lang` column."""
        lint = _linter()
        without_lang = [c for c in _harmonised_rows()[1] if c != "lang"]
        found = _by_check(lint.lint_criteria(rows, without_lang), "unresolved-target")
        assert set(_ids(found)) == {"EC-1", "IC-3"}, (
            "EC-1 and IC-3 both target `lang`. Against a corpus without it "
            "they are MISSING for every record and silently survive."
        )
        assert found[0].severity == "NOTICE"

    def test_duplicate_id_is_silent_on_a_clean_table(self, rows, a_columns):
        lint = _linter()
        assert _by_check(lint.lint_criteria(rows, a_columns), "duplicate-id") == []

    def test_duplicate_id_fires_when_a_row_is_repeated(self, rows, a_columns):
        """F-174: `crit_impacts` is a dict comprehension, so ids collapse."""
        lint = _linter()
        clash = dict(rows[1])
        clash["id"] = rows[0]["id"]
        found = _by_check(lint.lint_criteria(list(rows) + [clash], a_columns),
                          "duplicate-id")
        assert _ids(found) == [rows[0]["id"]]
        assert "twice" in found[0].message or "more than once" in found[0].message

    def test_threshold_is_silent_on_a_clean_table(self, rows, a_columns):
        lint = _linter()
        assert _by_check(lint.lint_criteria(rows, a_columns), "threshold") == []

    def test_threshold_fires_on_an_unparseable_value(self, rows, a_columns):
        lint = _linter()
        mutated = []
        for r in rows:
            r = dict(r)
            if r["id"] == "EC-2":       # an EL row, so it has a threshold
                r["threshold"] = "abc"
            mutated.append(r)
        found = _by_check(lint.lint_criteria(mutated, a_columns), "threshold")
        assert _ids(found) == ["EC-2"]

    def test_threshold_fires_when_out_of_range(self, rows, a_columns):
        lint = _linter()
        mutated = []
        for r in rows:
            r = dict(r)
            if r["id"] == "EC-2":
                r["threshold"] = "1.4"
            mutated.append(r)
        found = _by_check(lint.lint_criteria(mutated, a_columns), "threshold")
        assert _ids(found) == ["EC-2"]

    def test_a_defaulted_threshold_is_indistinguishable_and_is_not_reported(self, rows, a_columns):
        """CL-2, pinned as a known gap rather than left as a surprise.

        `ui.py::_harmonise_no_llm` writes f"{DEFAULT_THRESHOLD:.2f}" — the
        literal 0.60 — and a user who types 0.60 produces identical bytes. The
        linter therefore cannot report "this gate was never chosen", and must
        not pretend to.
        """
        lint = _linter()
        el_rows = [r for r in rows if r["stage"] in {"EL", "IL"}]
        assert el_rows and all(r["threshold"] == "0.60" for r in el_rows)
        assert _by_check(lint.lint_criteria(rows, a_columns), "threshold") == []


class TestTheExecutableSetIsNotJustRetyped:
    """The linter's executable-operator table, checked against the real executor.

    `plugins/_common/evaluator.py` has no module-level constant for this set —
    the 8-tuple is inline inside `_eval_criterion`, so it cannot be imported, and
    a linter that retypes it is the eighth representation of one vocabulary
    (F-109). This test turns an eighth copy into a *checked* copy.

    It cannot be done by probing alone at run time: `_eval_criterion` returns
    `UNKNOWN` both for "operator not supported" and for "operand not comparable"
    (raised as CL-1 in `docs/internal/FIX_WAVE_13C_LINTER.md`), so the probe
    needs a well-typed operand per operator, which is what this test supplies.
    """

    # One row of corpus, and an operand that is well typed for each operator.
    ROW = {"lang": "en", "year": "2020"}
    WELL_TYPED = {
        "contains": ("lang", ["e"]),
        "equals": ("lang", ["en"]),
        "regex": ("lang", ["e.*"]),
        "in_list": ("lang", ["en", "fr"]),
        "not_in": ("lang", ["fr"]),
        "gte": ("year", ["2000"]),
        "lte": ("year", ["2030"]),
        "between": ("year", ["2000", "2030"]),
        "llm": ("lang", ["some prose"]),
    }

    def test_the_linter_agrees_with_the_evaluator_about_EH_and_IH(self):
        common_parser = _import_plugin("_common", "parser")
        evaluator = _import_plugin("_common", "evaluator")
        lint = _linter()

        header = set(self.ROW)
        derived = set()
        for op, (target, what) in self.WELL_TYPED.items():
            crit = common_parser.Criterion(
                stage="EH", cid="X", ctype="include", scope="metadata",
                label="probe", operator=op, targets=[target],
                what_raw=";".join(what), what_list=what,
                threshold=0.6, enabled=True, source_text="probe",
            )
            if evaluator._eval_criterion(self.ROW, header, crit) != "UNKNOWN":
                derived.add(op)

        assert derived == set(lint.executable_operators("EH")), (
            "The linter's idea of what EH/IH can execute has drifted from what "
            "`_eval_criterion` actually executes. Update the linter, not this "
            "test — the evaluator is the authority."
        )
        assert derived == set(lint.executable_operators("IH"))

    def test_the_linter_agrees_that_EL_and_IL_run_llm_only(self):
        """EL/IL mark every non-`llm` operator UNCERTAIN without evaluating it."""
        lint = _linter()
        assert set(lint.executable_operators("EL")) == {"llm"}
        assert set(lint.executable_operators("IL")) == {"llm"}

    def test_every_declared_operator_is_accounted_for(self):
        """No operator may be silently absent from every stage's table.

        `OPERATORS` is reached through `parser` directly rather than through
        `plugin.py`, which does not re-export it — consistent with
        `07_criteria_parsing.md` §2.5's finding that the authoritative
        vocabulary is imported by no executor.
        """
        harmoniser_parser = _import_plugin("03_harmoniser", "parser")
        lint = _linter()
        covered = set()
        for stage in ("EH", "IH", "EL", "IL"):
            covered |= set(lint.executable_operators(stage))
        assert covered == set(harmoniser_parser.OPERATORS), (
            "Every operator in parser.py::OPERATORS must be executable "
            "somewhere, or the linter cannot tell 'inert here' from "
            "'unimplemented everywhere'."
        )
