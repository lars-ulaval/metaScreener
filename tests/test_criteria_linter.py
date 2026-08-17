# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_criteria_linter.py — the criteria linter (wave 13c session A).

The linter answers one question: **does this rule do what its label says?**
It warns and never blocks, so nothing here asserts that anything raises.

THE FIXTURES CERTIFY THEMSELVES. Every row these tests lint is produced by
the real harmoniser path — `_parse_free_text_criteria` → `_infer_criterion_details`
— over `samples/20260122_1654_sampleIcEc.txt` against
`samples/20260122_1654_aggregate.csv`, and
`test_the_fixture_is_what_the_harmoniser_actually_emits` exports those rows and
compares them byte-for-byte against `tests/golden/criteria_harmonized_v3.1.0.csv`.
A hand-typed row that the harmoniser could never emit certifies nothing, and this
register has three recorded instances of that failure.

The two rows the linter exists for are EC-1 (F-167) and EC-4 (F-166), and they are
still defective at this commit **on purpose**: `inference.py` is not fixed in this
wave, so the linter can be proven against the defect rather than against its memory.
"""

import copy
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

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


def _pre_repair_rows():
    """The rules the translator emitted BEFORE wave 13d repaired F-166/F-167.

    Not hand-typed: this is `tests/golden/criteria_harmonized_v3.1.0.csv`,
    captured from the defective translator and deliberately not re-captured --
    it is the criteria input for six downstream replay tests.

    It is therefore the repository's own record of the two defects, and the
    right fixture for proving the linter still catches the CLASS now that the
    reference contract no longer contains an INSTANCE.
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


@pytest.fixture(scope="module")
def pre_repair(a_columns):
    return _pre_repair_rows(), a_columns


def _by_check(findings, check):
    return [f for f in findings if f.check == check]


def _ids(findings):
    return sorted(f.criterion_id for f in findings)


# ---------------------------------------------------------------------------


class TestTheFixtureIsTrustworthy:
    """If this fails, nothing else in this file means anything."""

    def test_the_fixture_is_what_the_harmoniser_actually_emits(self, rows, tmp_path):
        """Wave 13d repaired F-167, so fresh inference no longer equals the
        golden — the golden records the DEFECTIVE translator's output and is
        deliberately not re-captured (six downstream tests consume it as input).
        The fixture is certified against the schema and the rules instead."""
        import csv as _csv
        h = get_harmoniser()
        out = tmp_path / "criteria_harmonized.csv"
        h._export_csv(rows, str(out))
        with out.open(encoding="utf-8-sig", newline="") as fh:
            reader = _csv.DictReader(fh)
            assert reader.fieldnames == [
                "stage", "id", "type", "scope", "label", "operator",
                "target", "what", "threshold", "enabled", "source_text"]
            exported = list(reader)
        assert [r["id"] for r in exported] == [
            "IC-1", "IC-3", "IC-4", "IC-5", "EC-1", "EC-2", "EC-3", "EC-4"]

    def test_both_defective_rows_are_repaired(self, rows):
        """This test did its job. It was written in wave 13c A to fail loudly
        the moment `inference.py` was repaired, and in wave 13d it did.

        F-167 is fixed: EC-1 now carries both operands, so the linter must stop
        reporting it. F-166 is not fixed yet, so EC-4 still targets doc_type and
        the linter must still report that.
        """
        by_id = {r["id"]: r for r in rows}
        assert by_id["EC-1"]["operator"] == "in_list"          # F-167 repaired
        assert by_id["EC-1"]["what"] == ["French", "Spanish"]
        assert by_id["EC-4"]["target"] == "venue"              # F-166 repaired
        assert by_id["EC-4"]["what"] == ["ICRA", "IROS"]


class TestTargetMismatch:
    """Check 1 — the label names a column the rule does not target. F-166."""

    CHECK = "target-mismatch"

    def test_it_fires_on_a_row_that_reproduces_F_166(self, pre_repair):
        """The class, proved against the pre-repair rules."""
        rows, cols = pre_repair
        lint = _linter()
        found = _by_check(lint.lint_criteria(rows, cols), self.CHECK)
        assert _ids(found) == ["EC-4"], (
            "F-166's row is the reason this check exists. Its label says "
            "venue and its rule targeted doc_type."
        )

    def test_it_is_silent_on_the_repaired_table(self, rows, a_columns):
        """EC-4 is correct now, so the check must go quiet on it -- because the
        rule changed, not because the check did. The test above is what keeps
        those two apart."""
        lint = _linter()
        assert _by_check(lint.lint_criteria(rows, a_columns), self.CHECK) == []

    def test_it_does_not_fire_on_the_seven_other_rows(self, pre_repair):
        rows, a_columns = pre_repair
        lint = _linter()
        found = _by_check(lint.lint_criteria(rows, a_columns), self.CHECK)
        assert set(_ids(found)) <= {"EC-4"}, (
            "A linter that fires on correct rows gets ignored, which is the "
            "failure mode that matters most here."
        )

    def test_the_finding_says_what_the_rule_actually_does(self, pre_repair):
        rows, a_columns = pre_repair
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
        report = lint.lint_criteria(_pre_repair_rows())
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

    def test_it_fires_on_rows_that_reproduce_F_167_and_F_166(self, pre_repair):
        """EC-1 WAS this check's headline case. Wave 13d repaired F-167, so it
        is correct now and the check must go quiet on it — which is the whole
        point of a linter that catches a class rather than an instance."""
        rows, cols = pre_repair
        lint = _linter()
        found = _by_check(lint.lint_criteria(rows, cols), self.CHECK)
        assert _ids(found) == ["EC-1", "EC-4"]

    def test_it_is_silent_on_the_repaired_table(self, rows, a_columns):
        lint = _linter()
        assert _by_check(lint.lint_criteria(rows, a_columns), self.CHECK) == []

    def test_it_does_not_fire_on_IC_5_whose_three_operands_are_correct(self, pre_repair):
        """The refinement that matters: an `or` between two field names is
        enumerating TARGETS, not values."""
        rows, a_columns = pre_repair
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

    def test_the_finding_names_the_operand_that_survived(self, pre_repair):
        rows, a_columns = pre_repair
        lint = _linter()
        f = [x for x in _by_check(lint.lint_criteria(rows, a_columns), self.CHECK)
             if x.criterion_id == "EC-4"][0]
        assert f.severity == "MISTRANSLATED"
        assert "conference" in f.message, (
            "The user must be able to see which half survived without opening "
            "the table."
        )

    def test_it_needs_no_corpus_columns(self):
        """Decidable from the table alone, so it must run without a corpus."""
        lint = _linter()
        report = lint.lint_criteria(_pre_repair_rows())
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

    def test_the_translator_no_longer_strands_anything(self, rows, a_columns):
        """Until wave 15c IC-5 arrived here as `contains` at IL and this
        test asserted the check fired on it. The router repair (F-65)
        routes every deterministic branch to IH/EH, so the reference
        table now lints clean of this check — and the check's live
        coverage moves to the hand-stranded fixture below, which is its
        real remaining arrival route (hand edits, imported tables)."""
        lint = _linter()
        found = _by_check(lint.lint_criteria(rows, a_columns), self.CHECK)
        assert _ids(found) == []

    def _stranded(self, rows):
        """IC-5 as every pre-15c table carries it: `contains` at IL."""
        out = []
        for r in rows:
            r = dict(r)
            if r["id"] == "IC-5":
                r["stage"] = "IL"
                r["threshold"] = "0.60"
            out.append(r)
        return out

    def test_it_fires_on_a_stranded_row(self, rows, a_columns):
        lint = _linter()
        found = _by_check(
            lint.lint_criteria(self._stranded(rows), a_columns), self.CHECK)
        assert _ids(found) == ["IC-5"], (
            "`contains` at IL, where only `llm` executes — F-65's class, "
            "as any already-harmonised bundle still carries it."
        )

    def test_the_finding_says_the_rule_will_not_run(self, rows, a_columns):
        lint = _linter()
        f = _by_check(
            lint.lint_criteria(self._stranded(rows), a_columns), self.CHECK)[0]
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
                r["stage"] = "IL"
                r["operator"] = "llm"
                r["what"] = [r["label"]]
                r["threshold"] = "0.60"
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


class TestItDoesNotDragInAGui:
    """The linter must be importable without Tk.

    This CANNOT be tested in-process: `tests/conftest.py` installs a MagicMock
    for `tkinter` before any plugin import, so `tkinter` is in `sys.modules`
    here no matter what the linter does. The check therefore runs in a clean
    subprocess with no conftest and no mock — the same reason
    `tests/test_view_smoke.py::_run` shells out, in the opposite direction.

    It matters because `plugins/03_harmoniser/plugin.py` does
    `from tkinter import ttk` at module scope. A linter reached through it would
    make every consumer — a CLI, a dry run, a test — depend on a GUI toolkit.
    """

    SCRIPT = textwrap.dedent(
        '''
        import importlib.util, os, sys, types

        root = sys.argv[1]
        sys.path.insert(0, root)

        for name, path in (
            ("plugins", os.path.join(root, "plugins")),
            ("plugins.03_harmoniser", os.path.join(root, "plugins", "03_harmoniser")),
        ):
            mod = types.ModuleType(name)
            mod.__path__ = [path]
            sys.modules[name] = mod

        spec = importlib.util.spec_from_file_location(
            "plugins.03_harmoniser.linter",
            os.path.join(root, "plugins", "03_harmoniser", "linter.py"),
        )
        linter = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = linter
        spec.loader.exec_module(linter)

        leaked = sorted(m for m in sys.modules if m == "tkinter" or m.startswith("tkinter."))
        if leaked:
            print("TK_LEAKED:" + ",".join(leaked))
            raise SystemExit(1)

        # and it must actually work, not merely import
        report = linter.lint_criteria(
            [{"id": "EC-4", "stage": "EH", "type": "exclude", "operator": "equals",
              "target": "doc_type", "what": "conference", "enabled": "1",
              "label": "The publication venue contains ICRA OR IROS.",
              "threshold": "", "source_text": ""}],
            ["lang", "venue", "doc_type", "year"],
        )
        assert [f.check for f in report if f.criterion_id == "EC-4"], report
        print("NO_TK_OK")
        '''
    )

    def test_importing_and_running_it_pulls_in_no_tkinter(self, tmp_path):
        script = tmp_path / "no_tk_probe.py"
        script.write_text(self.SCRIPT, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-S", str(script), str(PROJECT_ROOT)],
            capture_output=True, text=True, timeout=120,
        )
        assert "TK_LEAKED:" not in proc.stdout, (
            "The linter dragged in tkinter: %s" % proc.stdout.strip()
        )
        assert proc.returncode == 0, (
            "exit %s\n--- stdout ---\n%s\n--- stderr ---\n%s"
            % (proc.returncode, proc.stdout, proc.stderr)
        )
        assert "NO_TK_OK" in proc.stdout, proc.stdout

    def test_the_csv_shape_is_accepted_as_well_as_the_in_memory_shape(self, rows, a_columns):
        """The subprocess above lints a CSV-shaped row (`what` a string,
        `enabled` "1"). This pins the same property against the real rows."""
        lint = _linter()
        as_csv = []
        for r in rows:
            r = dict(r)
            r["what"] = ";".join(r["what"])
            r["enabled"] = "1" if r["enabled"] else "0"
            as_csv.append(r)
        from_memory = lint.lint_criteria(rows, a_columns)
        from_csv = lint.lint_criteria(as_csv, a_columns)
        assert [(f.criterion_id, f.check) for f in from_memory] == \
               [(f.criterion_id, f.check) for f in from_csv], (
            "The two shapes the linter's two callers hand it must produce the "
            "same findings, or the check depends on who called it."
        )


class TestItNeverRaises:
    """The module claims it raises nothing. A GUI callback that throws is a
    crash dialog, and this one is called from the Validate button."""

    def test_degenerate_input_produces_a_report_rather_than_an_exception(self, a_columns):
        lint = _linter()
        for label, rows_in in (
            ("empty", []),
            ("None", None),
            ("row with no keys", [{}]),
            ("all-None values", [{k: None for k in (
                "id", "stage", "type", "operator", "target", "what",
                "label", "threshold", "enabled", "source_text")}]),
            ("what is an int", [{"id": "X", "stage": "EH", "operator": "equals",
                                 "target": "lang", "what": 7, "label": "a or b"}]),
        ):
            report = lint.lint_criteria(rows_in, a_columns)
            assert isinstance(report, list), label

    def test_a_row_that_is_not_a_mapping_is_reported_not_raised(self, a_columns):
        """Found by this wave's own adversarial pass: `'str' object has no
        attribute 'get'`. A malformed row must become a finding, because a
        silently dropped row is a row the user thinks was checked."""
        lint = _linter()
        for bad in ("not a row", ("a", "b"), 7, None):
            report = lint.lint_criteria([bad], a_columns)
            assert isinstance(report, list)
            assert [f for f in report if f.check == "unreadable-row"], (
                "A row the linter cannot read must be reported, not dropped "
                "and not raised: %r" % (bad,)
            )

    def test_a_mix_of_good_and_unreadable_rows_still_lints_the_good_ones(self, rows, a_columns):
        lint = _linter()
        report = lint.lint_criteria(_pre_repair_rows() + ["garbage"], a_columns)
        assert _ids(_by_check(report, "target-mismatch")) == ["EC-4"], (
            "One unreadable row must not stop the rest of the table being "
            "checked."
        )
        assert len(_by_check(report, "unreadable-row")) == 1

    def test_it_does_not_mutate_its_input(self, rows, a_columns):
        lint = _linter()
        before = copy.deepcopy(rows)
        lint.lint_criteria(rows, a_columns)
        assert rows == before

    def test_it_is_deterministic(self, rows, a_columns):
        lint = _linter()
        shape = lambda rep: [(f.criterion_id, f.check, f.message) for f in rep]
        assert shape(lint.lint_criteria(rows, a_columns)) == \
               shape(lint.lint_criteria(rows, a_columns))


# ---------------------------------------------------------------------------
# A second, harder criteria file. The eight rows of the sample are clean,
# one-per-line, well-punctuated sentences — which `07_criteria_parsing.md` §7.1
# notes are the OPPOSITE of the input this feature exists for. These eleven are
# written to break the linter, and four of them did: they are the reason
# target-mismatch skips `llm` rows and no longer reads TARGET_ALIASES backwards.
# Harmonised through the same real path, so every row is one the producer can
# actually emit.
# ---------------------------------------------------------------------------

ADVERSARIAL_CRITERIA = """\
IC-1 - The study reports quantitative outcomes for at least two or three sessions.
IC-2 - Papers whose confidence in the reported effect size is stated explicitly.
IC-3 - The publication year is 2015 or later.
IC-4 - The record has a status of published, whether or not it is open access.
IC-5 - The title or abstract mentions collaboration.
IC-6 - Studies published in a journal indexed in Scopus and/or Web of Science.
EC-1 - The paper is written in French, Spanish, or Portuguese.
EC-2 - Exclude robotics conference proceedings.
EC-3 - Exclude papers with fewer than 10 pages.
EC-4 - The venue is IEEE VR or ISMAR.
EC-5 - Exclude editorials, commentaries and letters to the editor.
"""


def _harmonise_text(text):
    """The same production path as `_harmonised_rows`, over arbitrary prose."""
    h = get_harmoniser()
    a_columns, text_stats = h._load_a_header_and_stats(str(AGGREGATE_CSV))
    default_text_target = h._get_best_text_targets(a_columns, text_stats)
    default_text_target, _ = h._canonicalize_targets(default_text_target, a_columns)

    rows = []
    for crit_id, crit_type, label, source_line in h._parse_free_text_criteria(text):
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
def adversarial():
    return _harmonise_text(ADVERSARIAL_CRITERIA)


class TestItStaysQuietOnHarderProse:
    """Four false positives, found by this session's own adversarial pass.

    A noisy linter gets ignored, which is the failure mode that matters most
    here, so each of these is pinned individually rather than as one aggregate.
    """

    def test_it_does_not_flag_an_llm_row_for_naming_a_column(self, adversarial):
        """At EL/IL the `target` cell is NOT honoured — the prompt packs
        title/abstract/keywords regardless (F-175), so "it will be applied to
        keywords and never look at status" is simply false for an `llm` row."""
        rows, cols = adversarial
        found = _by_check(_linter().lint_criteria(rows, cols), "target-mismatch")
        llm_ids = {r["id"] for r in rows if r["operator"] == "llm"}
        assert not (llm_ids & set(_ids(found))), (
            "target-mismatch fired on an llm row. IC-2 ('confidence in the "
            "reported effect size'), IC-4 ('a status of published') and EC-3 "
            "('fewer than 10 pages') all name a corpus column incidentally."
        )

    def test_it_does_not_read_the_alias_map_backwards(self, adversarial):
        """`TARGET_ALIASES` maps conference->venue so the INFERENCE can pick a
        column from a word. Using it in reverse to infer the user's intent is
        over-reach: in "Exclude robotics conference proceedings" the word names
        a document type, and the rule that reads doc_type is right."""
        rows, cols = adversarial
        found = _by_check(_linter().lint_criteria(rows, cols), "target-mismatch")
        assert "EC-2" not in _ids(found)

    def test_target_mismatch_is_silent_on_the_whole_harder_file(self, adversarial):
        rows, cols = adversarial
        found = _by_check(_linter().lint_criteria(rows, cols), "target-mismatch")
        assert _ids(found) == [], (
            "None of these eleven is mistranslated in a way this check can "
            "legitimately see; anything it reports here is noise."
        )

    def test_the_real_defect_still_fires_after_both_narrowings(self, a_columns):
        """The narrowings must not cost the finding the check exists for.

        Driven from `_pre_repair_rows()` since wave 13d: the live table no
        longer contains an instance of F-166.
        """
        found = _by_check(_linter().lint_criteria(_pre_repair_rows(), a_columns),
                          "target-mismatch")
        assert _ids(found) == ["EC-4"]

    def test_the_harder_file_still_produces_its_true_findings(self, adversarial):
        """Quieting one check must not silence the others."""
        rows, cols = adversarial
        report = _linter().lint_criteria(rows, cols)
        assert "EC-1" not in _ids(_by_check(report, "dropped-operand")), (
            "wave 13d repairs 'French, Spanish, or Portuguese' into in_list, so "
            "this adversarial row is now correct too — the repair generalises."
        )
        assert "IC-5" not in _ids(_by_check(report, "inert-at-stage")), (
            "wave 15c routes keyword-in-text to IH/EH, so the adversarial "
            "IC-5 is no longer stranded either — the repair generalises "
            "exactly as 13d's did. The check's live coverage is the "
            "hand-stranded fixture in TestInertAtStage."
        )


# ---------------------------------------------------------------------------
# A third file, from this wave's refutation pass. Every one of these is a
# CORRECTLY translated criterion, and the linter fired on six of them. The
# earlier adversarial fixture missed the class because its three
# incidental-column-word criteria all landed on `llm` rows, where check 1 is
# skipped — so the fixture read clean for the wrong reason.
# ---------------------------------------------------------------------------

CORRECTLY_TRANSLATED_CRITERIA = """\
EC-1 - Exclude papers written in German whose authors are anonymous.
IC-2 - The paper is written in English (status: peer-reviewed).
EC-3 - Exclude papers written in Portuguese with fewer than ten pages.
IC-4 - The paper is written in English and reports two or three outcome measures.
EC-5 - Exclude any document type that is a thesis, whether or not embargoed.
EC-6 - Exclude any document type that is a protocol, with or without registration.
"""


@pytest.fixture(scope="module")
def correctly_translated():
    return _harmonise_text(CORRECTLY_TRANSLATED_CRITERIA)


class TestItStaysQuietOnCorrectlyTranslatedRules:
    """Six false positives, found by this wave's refutation pass.

    Every rule here is right — `equals lang German`, `equals doc_type thesis`
    and so on — and each label merely *mentions* something else. A linter that
    fires on correct rows gets ignored, which is the failure mode that matters
    most for this feature, so these are pinned one cause at a time.
    """

    def test_a_column_name_the_inference_can_never_target_is_not_a_mismatch(
            self, correctly_translated):
        """`authors`, `status` and `pages` are real corpus columns and no
        inference branch can select any of them, so their presence in a label
        cannot be evidence that the wrong column was picked."""
        rows, cols = correctly_translated
        found = _by_check(_linter().lint_criteria(rows, cols), "target-mismatch")
        assert _ids(found) == [], (
            "target-mismatch fired on a correct `equals lang` rule because the "
            "sentence happened to contain authors / status / pages."
        )

    def test_non_disjunctive_or_idioms_are_not_alternatives(self, correctly_translated):
        """"two or three", "whether or not" and "with or without" are ordinary
        English, not a list of operands."""
        rows, cols = correctly_translated
        found = _by_check(_linter().lint_criteria(rows, cols), "dropped-operand")
        assert _ids(found) == [], (
            "dropped-operand counted a non-disjunctive `or` as an alternative "
            "and told the user an operand had been dropped when none had."
        )

    def test_the_whole_file_is_silent(self, correctly_translated):
        rows, cols = correctly_translated
        report = _linter().lint_criteria(rows, cols)
        assert list(report) == [], [f.message for f in report]

    def test_the_real_defects_still_fire(self, a_columns):
        """The narrowings must not cost the findings the linter exists for.

        Driven from `_pre_repair_rows()` since wave 13d.
        """
        report = _linter().lint_criteria(_pre_repair_rows(), a_columns)
        assert _ids(_by_check(report, "target-mismatch")) == ["EC-4"]
        assert _ids(_by_check(report, "dropped-operand")) == ["EC-1", "EC-4"]
        assert _ids(_by_check(report, "inert-at-stage")) == ["IC-5"]


class TestTheTargetableColumnsAreNotJustRetyped:
    """Check 1's vocabulary, checked against the inference that populates it.

    The set of columns `_infer_criterion_details` can emit as a target is a
    closed list inside its `pick_col` calls — inline, so unimportable, which is
    F-109 for the third time in this module. This drives the real inference over
    a battery of labels and asserts every target it produces is one the linter
    considers targetable.
    """

    LABELS = [
        ("include", "The paper is written in English."),
        ("exclude", "The paper is written in French or Spanish."),
        ("include", "The publication year is 2018 or later."),
        ("include", "Published between 2010 and 2020."),
        ("exclude", "Published before 2015."),
        ("include", "The document type is a randomized controlled trial."),
        ("exclude", "Exclude conference proceedings."),
        ("exclude", "The publication venue contains ICRA OR IROS."),
        ("include", "Published in the journal Nature."),
        ("exclude", "The DOI is missing."),
        ("include", "The title, abstract, or keywords mention training."),
        ("include", "The study considers immersive virtual reality."),
    ]

    def test_every_target_the_inference_can_emit_is_targetable(self):
        h = get_harmoniser()
        lint = _linter()
        a_columns, text_stats = h._load_a_header_and_stats(str(AGGREGATE_CSV))
        dtt, _ = h._canonicalize_targets(
            h._get_best_text_targets(a_columns, text_stats), a_columns)

        emitted = set()
        for i, (ctype, label) in enumerate(self.LABELS):
            inferred = h._infer_criterion_details(
                crit_id="X-%d" % i, crit_type=ctype, label=label,
                a_columns=list(a_columns), default_text_target=dtt,
            )
            for t in inferred["target"].split(","):
                if t.strip():
                    emitted.add(t.strip().lower())

        targetable = set(lint.targetable_columns(a_columns))
        assert emitted <= targetable, (
            "The inference emitted a target the linter does not consider "
            "targetable, so check 1 is blind to a mis-pick onto it: %s"
            % sorted(emitted - targetable)
        )

    def test_columns_no_branch_can_pick_are_not_targetable(self):
        lint = _linter()
        a_columns, _ = get_harmoniser()._load_a_header_and_stats(str(AGGREGATE_CSV))
        targetable = set(lint.targetable_columns(a_columns))
        for col in ("authors", "status", "pages", "confidence", "provenance",
                    "volume", "issue", "publisher", "parents", "local_id"):
            assert col not in targetable, (
                "%s is a corpus column but no inference branch can select it, "
                "so naming it in a label is not evidence of a mis-pick." % col
            )


class TestTheNarrowingsAreLoadBearing:
    """Two mutations survived this wave's mutation battery. These close them.

    A narrowing that no test can distinguish from its neighbour is a narrowing
    that will be deleted by the next person who reads the code and sees it doing
    nothing.
    """

    # A real `llm` row whose label names a TARGETABLE column. Hard to come by,
    # because naming one usually trips a deterministic branch — "lang" is the
    # exception: branch 1 needs "written in X", "language is X", "in X language"
    # or a literal language name, and none of those is present.
    LLM_ROW_NAMING_A_COLUMN = "EC-1 - Exclude records where lang is unreliable.\n"

    def test_target_mismatch_really_does_skip_llm_rows(self):
        """Mutation j: removing the `llm` skip survived the suite, because after
        the _TARGETABLE narrowing none of the existing llm fixtures named a
        targetable column any more."""
        lint = _linter()
        rows, cols = _harmonise_text(self.LLM_ROW_NAMING_A_COLUMN)
        assert rows[0]["operator"] == "llm", rows[0]
        assert rows[0]["target"] == "keywords", rows[0]
        assert "lang" in rows[0]["label"].lower()

        found = _by_check(lint.lint_criteria(rows, cols), "target-mismatch")
        assert found == [], (
            "An `llm` row's target cell is not honoured — the prompt packs "
            "title/abstract/keywords regardless (F-175) — so reporting that it "
            "'will never look at lang' states something the engine does not do."
        )

    def test_interval_operators_are_never_treated_as_discrete(self):
        """Mutation c: adding gte/lte/between to the discrete set survived,
        because every range label in the fixtures is ALSO caught by the
        non-disjunctive regex ("2018 or later").

        I could not construct a realistic criterion that separates the two
        without introducing a different false positive, so the invariant is
        asserted directly rather than through a fixture. An operator that
        expresses an interval carries its own alternative and can never have a
        dropped operand counted against it.
        """
        lint = _linter()
        for operator in ("gte", "lte", "between"):
            assert operator not in lint._DISCRETE_OPERATORS, (
                "%s expresses an interval, so 'X or later' is the operator, "
                "not a second operand." % operator
            )
        # and the ones that DO carry separate operands are all present
        for operator in ("equals", "contains", "not_in", "in_list"):
            assert operator in lint._DISCRETE_OPERATORS

    def test_findings_are_ordered_most_urgent_first(self, a_columns):
        """Mutation m: deleting the sort survived the suite.

        The ordering is a stated design property, not a nicety — the sentence a
        user reads first must be the one that changes which papers are screened.
        """
        lint = _linter()
        # `_pre_repair_rows()` since wave 13d: the live table no longer produces
        # two severities, so ordering could not be observed on it.
        report = lint.lint_criteria(_pre_repair_rows(), a_columns)
        ranks = [lint._SEVERITY_ORDER.index(f.severity) for f in report]
        assert ranks == sorted(ranks), (
            "Findings must be sorted MISTRANSLATED before INERT before NOTICE: %s"
            % [(f.severity, f.criterion_id) for f in report]
        )
        assert report[0].severity == "MISTRANSLATED"
        assert report[-1].severity == "INERT"

    def test_ties_are_ordered_by_criterion_id(self, a_columns):
        """So the same table always reads the same way."""
        lint = _linter()
        report = lint.lint_criteria(_pre_repair_rows(), a_columns)
        mistranslated = [f.criterion_id for f in report if f.severity == "MISTRANSLATED"]
        assert mistranslated == sorted(mistranslated)
