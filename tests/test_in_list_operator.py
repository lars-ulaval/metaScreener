# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_in_list_operator.py — characterising `in_list` before anything emits it.

`plugins/03_harmoniser/parser.py::OPERATORS` declares nine operators. Two of them,
`regex` and `in_list`, are emitted by no inference branch — `07_criteria_parsing.md`
§2.5 — so `in_list` has been implemented, shipped and never executed. Wave 13b
measured that `tests/test_deterministic_filters.py` exercises `regex` and **not**
`in_list`; the coordinator stated twice that it was tested and was wrong both times.

Wave 13d's repair of **F-167** makes `in_list` reachable: a compound language
criterion stops being truncated to its first operand and becomes
`in_list lang [French, Spanish]`. **An operator nobody has run may not do what its
name suggests**, so this file establishes what it does before the inference emits it.

The result, recorded here rather than in a commit message that scrolls away:
**it works, and the two evaluator entry points agree.** No fix was needed. What these
tests buy is that the next person to change `_norm_for_target`, `_norm_what_for_target`
or the `in_list` branch finds out here rather than in a screening run.

One property below decided the shape of the *other* repair in this wave and is worth
reading even if the rest is skimmed:
`test_it_is_exact_membership_not_substring`. `in_list` is set membership, so it is
right for languages — the corpus holds exact codes — and **wrong for F-166's EC-4**,
whose label says *contains*.
"""

import pytest

from conftest import _import_plugin


def _parser():
    return _import_plugin("_common", "parser")


def _evaluator():
    return _import_plugin("_common", "evaluator")


def _criterion(operator, target, what, ctype="exclude", stage="EH"):
    """A `Criterion` exactly as `_load_criteria_from_text` would build one."""
    cp = _parser()
    return cp.Criterion(
        stage=stage, cid="X-1", ctype=ctype, scope="metadata", label="probe",
        operator=operator, targets=[target],
        what_raw=";".join(what), what_list=list(what),
        threshold=0.6, enabled=True, source_text="probe",
    )


def _verdicts(operator, target, what, value):
    """Both entry points, so a divergence between them cannot hide.

    `_eval_criterion` is the fast path `run_screen` uses for the outcome;
    `_eval_criterion_detail` is what the drill-down modal shows. They normalise
    through the same helpers and must agree.
    """
    ev = _evaluator()
    row = {target: value}
    crit = _criterion(operator, target, what)
    fast = ev._eval_criterion(row, set(row), crit)
    detail = ev._eval_criterion_detail(row, set(row), crit, "EH")
    return fast, detail.get("status"), detail.get("note", "")


class TestInListDoesWhatItsNameSuggests:
    """The cases a language criterion actually meets."""

    def test_one_value_matching_the_raw_form(self):
        assert _verdicts("in_list", "lang", ["French"], "French")[0] == "FAILED"

    def test_one_value_matching_the_corpus_code(self):
        """`French` and `fr` are the same language to both sides.

        `parser.py::_norm_for_target` maps a `lang` value through `LANG_MAP`, and
        `_norm_what_for_target` is the same function — so the operand and the record
        meet in one canonical form. This is why F-167's remedy can name languages
        the way a researcher writes them.
        """
        assert _verdicts("in_list", "lang", ["French"], "fr")[0] == "FAILED"

    @pytest.mark.parametrize("value,expected", [
        ("fr", "FAILED"),      # first operand
        ("es", "FAILED"),      # second operand — the one F-167 drops today
        ("en", "MET"),
        ("pt", "MET"),
    ])
    def test_every_operand_is_considered(self, value, expected):
        """The whole point of the operator, and of F-167's remedy.

        `FAILED` on an exclusion criterion means the record is removed.
        """
        assert _verdicts("in_list", "lang", ["French", "Spanish"], value)[0] == expected

    def test_case_and_surrounding_whitespace_do_not_matter(self):
        assert _verdicts("in_list", "lang", ["FRENCH"], "fr")[0] == "FAILED"
        assert _verdicts("in_list", "lang", ["  French  "], "fr")[0] == "FAILED"

    def test_it_is_exact_membership_not_substring(self):
        """**This decided F-166's operator choice and is not incidental.**

        `in_list` asks whether the record's value IS one of the operands, not
        whether it CONTAINS one. A venue of "Proc. ICRA 2021" is not the string
        "ICRA", so `in_list` does not match it — which is why EC-4, whose label
        says *contains*, is repaired with `contains` and not with `in_list`.
        """
        assert _verdicts("in_list", "venue", ["ICRA", "IROS"], "ICRA")[0] == "FAILED"
        assert _verdicts("in_list", "venue", ["ICRA", "IROS"],
                         "Proc. ICRA 2021")[0] == "MET"
        # and the operator that IS right for that sentence
        assert _verdicts("contains", "venue", ["ICRA", "IROS"],
                         "Proc. ICRA 2021")[0] == "FAILED"
        assert _verdicts("contains", "venue", ["ICRA", "IROS"],
                         "IEEE IROS 2020")[0] == "FAILED"
        assert _verdicts("contains", "venue", ["ICRA", "IROS"],
                         "CHI 2019")[0] == "MET"


class TestInListDegradesSafely:
    """The shapes a hand-edited or externally-produced table can carry."""

    def test_no_operands_is_unknown_and_says_why(self):
        fast, status, note = _verdicts("in_list", "lang", [], "fr")
        assert fast == "UNKNOWN"
        assert status == "UNKNOWN"
        assert note == "in_list_missing_what", (
            "the note is the only trace a consumer gets; F-64 is the row about "
            "an UNCERTAIN with no reason attached"
        )

    def test_operands_that_are_all_empty_are_the_same_as_none(self):
        assert _verdicts("in_list", "lang", [""], "fr")[0] == "UNKNOWN"

    def test_an_empty_record_value_is_missing_not_a_mismatch(self):
        """`MISSING` keeps the record; a mismatch would remove it. The safe
        direction, and the same one `_eval_criterion` takes for every operator."""
        fast, status, note = _verdicts("in_list", "lang", ["French"], "")
        assert fast == "MISSING"
        assert status == "MISSING"

    def test_a_value_containing_the_export_separator_is_not_split(self):
        """`_what_to_export` joins operands with `;`. A record whose value
        contains one must not be silently treated as two."""
        assert _verdicts("in_list", "venue", ["A;B"], "A;B")[0] == "FAILED"


class TestTheTwoEntryPointsAgree:
    """`_eval_criterion` decides the outcome; `_eval_criterion_detail` explains it.

    They normalise through the same helpers but are written twice — X1 and X2 in
    `07_criteria_parsing.md` §2.5's vocabulary audit, and F-109's subject. If they
    ever disagree, a record is excluded for a reason the drill-down denies.
    """

    CASES = [
        ("lang", ["French"], "French"),
        ("lang", ["French"], "fr"),
        ("lang", ["French", "Spanish"], "es"),
        ("lang", ["French", "Spanish"], "en"),
        ("lang", ["FRENCH"], "fr"),
        ("lang", [], "fr"),
        ("lang", [""], "fr"),
        ("lang", ["French"], ""),
        ("venue", ["ICRA", "IROS"], "ICRA"),
        ("venue", ["ICRA", "IROS"], "Proc. ICRA 2021"),
        ("venue", ["A;B"], "A;B"),
        ("doc_type", ["conference"], "conference"),
    ]

    @pytest.mark.parametrize("target,what,value", CASES)
    def test_fast_and_detail_return_the_same_status(self, target, what, value):
        fast, status, _note = _verdicts("in_list", target, what, value)
        assert fast == status, (
            "the outcome path and the explanation path disagree about "
            "in_list %r on %r=%r" % (what, target, value)
        )
