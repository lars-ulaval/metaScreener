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
    """Every rule from the sample criteria file, keyed by id, via the real path."""
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


class TestF166TheRuleReadsTheColumnTheLabelNames:
    """A parenthetical gloss must not decide which column a criterion is about."""

    def test_EC_4_targets_venue_and_carries_both_operands(self):
        """The wave's headline fixture. Both halves matter: reaching branch 4
        gets the column right and leaves the operand as the entire sentence."""
        assert _reference_rules()["EC-4"] == (
            "EH", "contains", "venue", ["ICRA", "IROS"])

    def test_the_gloss_did_not_decide_the_target(self):
        """The word *conference* appears only inside "(robotics conference
        proceedings)". It must not pull the rule onto `doc_type`."""
        _stage, _operator, target, _what = _reference_rules()["EC-4"]
        assert target == "venue"
        assert target != "doc_type"

    def test_the_operator_is_contains_not_in_list(self):
        """Venues are strings like "Proc. ICRA 2021"; the label says *contains*.

        `in_list` is exact membership — `tests/test_in_list_operator.py`
        establishes that — so it would produce a rule that matches nothing and
        looks right in the table. `contains` ORs its operands.
        """
        assert _reference_rules()["EC-4"][1] == "contains"

    def test_a_genuine_document_type_criterion_still_reaches_branch_3(self):
        """The repair must not send doc-type criteria to venue. `conference` is
        in BOTH guards, which is why reordering the branches was rejected."""
        assert _rule_for("Exclude conference proceedings.") == (
            "EH", "equals", "doc_type", ["conference"])
        assert _rule_for("Exclude papers of document type thesis.") == (
            "EH", "equals", "doc_type", ["thesis"])

    def test_a_doc_type_criterion_whose_only_trigger_is_in_the_gloss(self):
        """The case that broke the first draft of this repair.

        "Systematic reviews and meta-analyses (any type)." has its only branch-3
        trigger word — *type* — inside the gloss, but its map key —
        *systematic review* — in the main clause. Stripping parentheticals from
        the GUARD as well as the value scan sent it all the way to `llm`.
        Guard permissive, value strict.
        """
        assert _rule_for("Systematic reviews and meta-analyses (any type).",
                         "include") == ("IH", "equals", "doc_type",
                                        ["systematic review"])

    def test_the_class_is_caught_on_a_sentence_nobody_has_run(self):
        """F-166's mechanism on different prose. This is the point of repairing
        the class rather than the instance."""
        assert _rule_for("The venue contains CHI (a conference).", "include") == (
            "IH", "contains", "venue", ["CHI"]) or _rule_for(
            "The venue contains CHI (a conference).", "include")[:3] == (
            "IH", "contains", "venue")

    def test_the_repaired_rule_excludes_what_the_label_describes(self):
        """End to end through the real evaluator."""
        cp = _import_plugin("_common", "parser")
        ev = _import_plugin("_common", "evaluator")
        _stage, operator, target, what = _reference_rules()["EC-4"]
        crit = cp.Criterion(
            stage="EH", cid="EC-4", ctype="exclude", scope="metadata",
            label="l", operator=operator, targets=[target],
            what_raw=";".join(what), what_list=what,
            threshold=0.6, enabled=True, source_text="s")
        for venue, expected in (("Proc. ICRA 2021", "FAILED"),
                                ("IEEE IROS 2020", "FAILED"),
                                ("CHI 2019", "MET"),
                                ("ACM TOCHI", "MET")):
            row = {target: venue}
            assert ev._eval_criterion(row, set(row), crit) == expected, venue


class TestTheSixCorrectRowsNeverMoved:
    """Every row of the reference contract that was already right."""

    UNCHANGED = {
        "IC-1": ("IL", "llm", "keywords"),
        "IC-3": ("IH", "equals", "lang"),
        "IC-4": ("IH", "gte", "year"),
        # IC-5 left this table at wave 15c: F-65's repair routes it to
        # IH, its own wave, exactly as its row warned. Pinned below.
        "EC-2": ("EL", "llm", "keywords"),
        "EC-3": ("EL", "llm", "keywords"),
    }

    @pytest.mark.parametrize("crit_id", sorted(UNCHANGED))
    def test_row_is_untouched_by_either_repair(self, crit_id):
        stage, operator, target = self.UNCHANGED[crit_id]
        assert _reference_rules()[crit_id][:3] == (stage, operator, target)

    def test_IC_5_is_F_65s_row_repaired(self):
        """Was pinned at `("IL", "contains")` — deliberately unmoved by
        waves 13b–13d because F-65's cell warned the repair changes
        screening outcomes. Wave 15c is that repair, adjudicated with
        its measured corpus effect (147 → 22 under the F-204 union
        evaluator; see tests/test_stage_routing.py)."""
        assert _reference_rules()["IC-5"][:2] == ("IH", "contains")

    def test_a_gloss_cannot_pull_a_criterion_INTO_venue_either(self):
        """The other direction of the same rule, and the mutation battery found
        it untested.

        "Exclude editorials (published in a conference)." is a document-type
        criterion whose gloss mentions a venue. Branch 3 correctly declines it —
        *editorial* is not in `doc_type_map` — and branch 4 must decline it too,
        or the gloss decides the column a second way round. It falls to `llm`,
        which is the safe direction: a criterion nobody can translate goes to a
        model rather than to a wrong rule.
        """
        for label in ("Exclude editorials (published in a conference).",
                      "Exclude opinion pieces (journal commentary).",
                      "Exclude short papers (conference format)."):
            stage, operator, target, _what = _rule_for(label)
            assert (stage, operator) == ("EL", "llm"), (
                "%r was routed to %s %s on %s -- a gloss decided the column"
                % (label, stage, operator, target)
            )
