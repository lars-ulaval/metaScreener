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
