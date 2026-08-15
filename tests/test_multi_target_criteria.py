# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""test_multi_target_criteria.py — multi-target deterministic criteria (F-204).

CHARACTERISATION, wave 15c: these tests lock what the evaluator does TODAY
with a criterion listing several targets — `_get_first_nonempty` picks the
first non-empty target's value and every other listed field is ignored, so
"the title, abstract, or keywords mention X" is evaluated as "the title
mentions X" whenever a title exists. Measured on the reference corpus: the
title is the field read for 759 of the 760 IH inputs, and IC-5 keeps 8 of
147 records where the union its prose promises keeps 22.

The F-204 fix flips the class below IN THE OPEN to union-over-all-listed-
targets — the wave-13d EXPECTED_RULES precedent. The single-target class
must survive the fix byte-identically; the golden EH/IH replays prove the
same corpus-level fact.
"""
from conftest import get_eh


_mod = None


def _e():
    global _mod
    if _mod is None:
        _mod = get_eh()
    return _mod


def _crit(*, cid="IC-X", ctype="include", operator="contains",
          targets=None, what_list=None, stage="IH"):
    mod = _e()
    return mod.Criterion(
        stage=stage, cid=cid, ctype=ctype, scope="metadata", label="test",
        operator=operator, targets=targets or ["title"],
        what_raw=";".join(what_list or []), what_list=what_list or [],
        threshold=None, enabled=True, source_text="test",
    )


THREE = ["title", "abstract", "keywords"]
KWS = ["training", "vocational", "workplace"]


class TestUnionOverListedTargets:
    """F-204, FIXED: every listed target is read; the criterion matches
    when any of them satisfies the predicate — the OR its prose states.
    (This class characterised the first-non-empty defect until the fix
    flipped it in the open, the EXPECTED_RULES precedent.)"""

    def test_a_keyword_in_the_abstract_counts_behind_a_title(self):
        """The abstract says 'training'; the title is non-empty and does
        not; the criterion is MET — every listed field is read now."""
        c = _crit(targets=THREE, what_list=KWS)
        row = {"title": "A study of surgeons",
               "abstract": "We ran a training simulation.",
               "keywords": ""}
        assert _e()._eval_criterion(row, set(THREE), c) == "MET"

    def test_a_keyword_in_keywords_counts_behind_both(self):
        c = _crit(targets=THREE, what_list=KWS)
        row = {"title": "A study of surgeons",
               "abstract": "We ran a simulation.",
               "keywords": "vocational education"}
        assert _e()._eval_criterion(row, set(THREE), c) == "MET"

    def test_no_field_matching_fails_an_include(self):
        c = _crit(targets=THREE, what_list=KWS)
        row = {"title": "A study of surgeons",
               "abstract": "We ran a simulation.",
               "keywords": "surgery"}
        assert _e()._eval_criterion(row, set(THREE), c) == "FAILED"

    def test_an_empty_title_still_reaches_the_abstract(self):
        c = _crit(targets=THREE, what_list=KWS)
        row = {"title": "", "abstract": "A workplace intervention.",
               "keywords": ""}
        assert _e()._eval_criterion(row, set(THREE), c) == "MET"

    def test_the_detail_modal_names_the_field_that_decided(self):
        from plugins._common.evaluator import _eval_criterion_detail
        c = _crit(targets=THREE, what_list=KWS)
        row = {"title": "A study of surgeons",
               "abstract": "We ran a training simulation.",
               "keywords": ""}
        d = _eval_criterion_detail(row, set(THREE), c, "IH")
        assert d["status"] == "MET"
        assert d["target_used"] == "abstract"

    def test_exclude_direction_matches_on_any_field_too(self):
        c = _crit(cid="EC-X", ctype="exclude", stage="EH",
                  targets=THREE, what_list=KWS)
        row = {"title": "A study of surgeons",
               "abstract": "We ran a training simulation.",
               "keywords": ""}
        assert _e()._eval_criterion(row, set(THREE), c) == "FAILED"

    def test_one_unevaluable_field_yields_unknown_only_if_none_match(self):
        """gte across two fields: a non-numeric year in one field cannot
        decide the criterion when the other field matches; when nothing
        matches, the un-evaluable field makes the answer UNKNOWN rather
        than a confident FAILED."""
        c = _crit(cid="IC-Y", operator="gte",
                  targets=["year", "year_alt"], what_list=["2018"])
        met = {"year": "n/a", "year_alt": "2020"}
        unk = {"year": "n/a", "year_alt": "2001-ish"}
        assert _e()._eval_criterion(met, {"year", "year_alt"}, c) == "MET"
        assert _e()._eval_criterion(unk, {"year", "year_alt"}, c) == "UNKNOWN"


class TestSingleTargetInvariants:
    """The class the fix must NOT touch: one listed target behaves the
    same before and after — these stay green across the flip."""

    def test_single_target_contains_match(self):
        c = _crit(cid="EC-4", ctype="exclude", operator="contains",
                  stage="EH", targets=["venue"], what_list=["ICRA", "IROS"])
        row = {"venue": "IEEE ICRA 2023", "title": "x"}
        assert _e()._eval_criterion(row, {"venue", "title"}, c) == "FAILED"

    def test_single_target_contains_no_match(self):
        c = _crit(cid="EC-4", ctype="exclude", operator="contains",
                  stage="EH", targets=["venue"], what_list=["ICRA", "IROS"])
        row = {"venue": "CHI 2023", "title": "x"}
        assert _e()._eval_criterion(row, {"venue", "title"}, c) == "MET"

    def test_single_target_empty_value_is_missing(self):
        c = _crit(cid="EC-4", ctype="exclude", operator="contains",
                  stage="EH", targets=["venue"], what_list=["ICRA"])
        row = {"venue": "", "title": "x"}
        assert _e()._eval_criterion(row, {"venue", "title"}, c) == "MISSING"

    def test_all_targets_empty_is_missing_multi_too(self):
        c = _crit(targets=THREE, what_list=KWS)
        row = {"title": "", "abstract": "", "keywords": ""}
        assert _e()._eval_criterion(row, set(THREE), c) == "MISSING"

    def test_no_listed_target_in_header_is_missing(self):
        c = _crit(targets=THREE, what_list=KWS)
        row = {"venue": "CHI"}
        assert _e()._eval_criterion(row, {"venue"}, c) == "MISSING"


class TestBlastRadiusOnTheReferenceTable:
    """The F-204 fix moves exactly one reference criterion. Both frozen
    harmonised tables carry IC-5 as their ONLY multi-target deterministic
    row, so the union change cannot move any other reference number —
    including every golden replay, whose deterministic rows are all
    single-target."""

    def _rows(self, path):
        import csv, io
        from pathlib import Path
        text = (Path(__file__).parent.parent / path).read_bytes() \
            .decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))

    def test_the_wave14c_table(self):
        for r in self._rows("docs/data/wave14c_batch_runs/"
                            "runDE_criteria_harmonized.csv"):
            if r["operator"].strip().lower() == "llm":
                continue
            n = len([t for t in r["target"].split(",") if t.strip()])
            assert n == 1 or r["id"] == "IC-5", (r["id"], r["target"])

    def test_the_golden_table(self):
        for r in self._rows("tests/golden/criteria_harmonized_v3.1.0.csv"):
            if r["operator"].strip().lower() == "llm":
                continue
            n = len([t for t in r["target"].split(",") if t.strip()])
            assert n == 1 or r["id"] == "IC-5", (r["id"], r["target"])
