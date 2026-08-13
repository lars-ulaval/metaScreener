# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_inference_repairs.py — F-166 and F-167, and the classes behind them.

`inference.py::_infer_criterion_details` translates a researcher's sentence into an
executable rule. Two measured defects made it emit a rule that does not match the
sentence:

  F-167 — a compound criterion was truncated to its first operand. "The paper is
  written in French or Spanish" became ``equals lang ['French']``, and the two
  Spanish records the criterion names survived it.

  F-166 — a criterion was rendered against a different column from the one its label
  names. "The publication venue contains 'ICRA' OR 'IROS' (robotics conference
  proceedings)" became ``equals doc_type ['conference']`` because the word
  *conference*, appearing only inside the parenthetical gloss, reached branch 3
  before branch 4 was tried. It removed 112 of 776 records; the criterion as written
  removes none.

**Every fixture here is produced by the real translator**, not typed out: the tests
drive `_parse_free_text_criteria` → `_infer_criterion_details` over prose, which is
the path the "Harmonise (no LLM)" button takes. A hand-built row certifies nothing,
and this register has recorded that failure four times.

**These tests are about the CLASS, not the two sentences.** The probe battery below
contains criteria nobody has ever run, including the two that caught mistakes in the
first draft of each repair.
"""

import pytest

from conftest import AGGREGATE_CSV, IC_EC_FILE, _import_plugin, get_harmoniser


def _rule_for(label, crit_type="exclude", crit_id="X-1"):
    """The rule the translator emits for one sentence, via the real producer."""
    h = get_harmoniser()
    a_columns, text_stats = h._load_a_header_and_stats(str(AGGREGATE_CSV))
    default_text_target = h._get_best_text_targets(a_columns, text_stats)
    default_text_target, _ = h._canonicalize_targets(default_text_target, a_columns)
    inferred = h._infer_criterion_details(
        crit_id=crit_id, crit_type=crit_type, label=label,
        a_columns=list(a_columns), default_text_target=default_text_target,
    )
    return (inferred["stage"], inferred["operator"],
            inferred["target"], list(inferred["what"]))


def _reference_rules():
    """Every rule from `samples/ic_ec_12.txt`, keyed by id, via the real path."""
    h = get_harmoniser()
    a_columns, text_stats = h._load_a_header_and_stats(str(AGGREGATE_CSV))
    default_text_target = h._get_best_text_targets(a_columns, text_stats)
    default_text_target, _ = h._canonicalize_targets(default_text_target, a_columns)
    out = {}
    for crit_id, crit_type, label, _src in h._parse_free_text_criteria(
            IC_EC_FILE.read_text(encoding="utf-8-sig")):
        inferred = h._infer_criterion_details(
            crit_id=crit_id, crit_type=crit_type, label=label,
            a_columns=list(a_columns), default_text_target=default_text_target,
        )
        out[crit_id] = (inferred["stage"], inferred["operator"],
                        inferred["target"], list(inferred["what"]))
    return out


class TestF167ACompoundCriterionKeepsEveryOperand:
    """"French or Spanish" must express both."""

    def test_EC_1_names_both_languages(self):
        assert _reference_rules()["EC-1"] == (
            "EH", "in_list", "lang", ["French", "Spanish"])

    def test_the_operator_is_in_list_because_equals_cannot_express_two(self):
        """`_eval_criterion` reads `what_list_norm[0]` alone for `equals`, so a
        two-value `equals` is silently a one-value one — the reason the remedy
        changes the operator and not merely the operand list."""
        stage, operator, target, what = _reference_rules()["EC-1"]
        assert operator == "in_list"
        assert len(what) == 2

    def test_a_single_language_is_untouched(self):
        """The one-language case must be bit-for-bit what it was."""
        assert _reference_rules()["IC-3"] == ("IH", "equals", "lang", ["English"])
        assert _rule_for("The paper is written in English.", "include") == (
            "IH", "equals", "lang", ["English"])

    def test_a_language_outside_the_known_list_still_survives(self):
        """`Dutch` is not in the inference's language alternation.

        A repair that only scanned for known names would silently swap which
        operand survives — `German` instead of `Dutch` — rather than keeping both.
        This is why the repair unions the pattern captures with the name scan.
        """
        assert _rule_for("Written in Dutch or German.") == (
            "EH", "in_list", "lang", ["Dutch", "German"])

    def test_three_languages(self):
        assert _rule_for("The paper is written in French, Spanish or Portuguese.") == (
            "EH", "in_list", "lang", ["French", "Spanish", "Portuguese"])

    def test_the_repaired_rule_removes_the_records_the_criterion_names(self):
        """End to end through the real evaluator: the two Spanish records that
        survived F-167 no longer do."""
        cp = _import_plugin("_common", "parser")
        ev = _import_plugin("_common", "evaluator")
        _stage, operator, target, what = _reference_rules()["EC-1"]
        crit = cp.Criterion(
            stage="EH", cid="EC-1", ctype="exclude", scope="metadata",
            label="l", operator=operator, targets=[target],
            what_raw=";".join(what), what_list=what,
            threshold=0.6, enabled=True, source_text="s")
        for lang, expected in (("fr", "FAILED"), ("es", "FAILED"),
                               ("en", "MET"), ("pt", "MET")):
            row = {target: lang}
            assert ev._eval_criterion(row, set(row), crit) == expected, lang
