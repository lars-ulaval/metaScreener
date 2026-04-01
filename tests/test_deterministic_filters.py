# -*- coding: utf-8 -*-
"""
test_deterministic_filters.py — Tests for EH/IH _eval_criterion() logic.

Verifies that:
  - EH correctly excludes records matching exclusion criteria
  - IH correctly retains only records matching inclusion criteria
  - Edge cases (missing data, unknown operators) are handled
"""
import pytest
from conftest import get_eh


_mod = None

def _e():
    global _mod
    if _mod is None:
        _mod = get_eh()
    return _mod


def _make_criterion(*, cid="EC-1", ctype="exclude", operator="equals",
                    targets=None, what_list=None, stage="EH",
                    label="test", threshold=None, enabled=True):
    """Helper to build a Criterion dataclass from the EH plugin."""
    mod = _e()
    return mod.Criterion(
        stage=stage,
        cid=cid,
        ctype=ctype,
        scope="metadata",
        label=label,
        operator=operator,
        targets=targets or ["lang"],
        what_raw=";".join(what_list) if what_list else "",
        what_list=what_list or [],
        threshold=threshold,
        enabled=enabled,
        source_text=label,
    )


# ======================================================================
# EH exclusion semantics
# ======================================================================

class TestEHExclusion:
    """Exclusion criterion: if the record matches → FAILED (= excluded)."""

    def test_language_exclusion_match(self):
        """Record lang='fr' + EC operator=equals what=['fr'] → FAILED."""
        c = _make_criterion(ctype="exclude", operator="equals",
                            targets=["lang"], what_list=["fr"])
        row = {"lang": "fr", "title": "Some title"}
        header_set = {"lang", "title"}
        status = _e()._eval_criterion(row, header_set, c)
        # For exclude criteria: matched=True → FAILED (record IS excluded)
        assert status == "FAILED"

    def test_language_exclusion_no_match(self):
        """Record lang='en' + EC operator=equals what=['fr'] → MET (survives)."""
        c = _make_criterion(ctype="exclude", operator="equals",
                            targets=["lang"], what_list=["fr"])
        row = {"lang": "en", "title": "Some title"}
        header_set = {"lang", "title"}
        status = _e()._eval_criterion(row, header_set, c)
        # For exclude criteria: matched=False → MET (record is NOT excluded)
        assert status == "MET"

    def test_venue_contains_exclusion(self):
        """Record venue has 'ICRA' + EC contains → FAILED."""
        c = _make_criterion(cid="EC-4", ctype="exclude", operator="contains",
                            targets=["venue"], what_list=["ICRA"])
        row = {"venue": "IEEE ICRA 2023", "title": "Robot study"}
        header_set = {"venue", "title"}
        status = _e()._eval_criterion(row, header_set, c)
        assert status == "FAILED"

    def test_venue_contains_no_match(self):
        """Record venue lacks 'ICRA' + EC contains → MET."""
        c = _make_criterion(cid="EC-4", ctype="exclude", operator="contains",
                            targets=["venue"], what_list=["ICRA"])
        row = {"venue": "Nature Medicine", "title": "VR study"}
        header_set = {"venue", "title"}
        status = _e()._eval_criterion(row, header_set, c)
        assert status == "MET"


# ======================================================================
# IH inclusion semantics
# ======================================================================

class TestIHInclusion:
    """Inclusion criterion: if the record matches → MET (retained)."""

    def test_year_gte_inclusion_pass(self):
        """Record year=2020 + IC operator=gte what=['2018'] → MET."""
        c = _make_criterion(cid="IC-4", ctype="include", operator="gte",
                            targets=["year"], what_list=["2018"], stage="IH")
        row = {"year": "2020", "title": "Modern VR"}
        header_set = {"year", "title"}
        status = _e()._eval_criterion(row, header_set, c)
        assert status == "MET"

    def test_year_gte_inclusion_fail(self):
        """Record year=2015 + IC operator=gte what=['2018'] → FAILED."""
        c = _make_criterion(cid="IC-4", ctype="include", operator="gte",
                            targets=["year"], what_list=["2018"], stage="IH")
        row = {"year": "2015", "title": "Old VR"}
        header_set = {"year", "title"}
        status = _e()._eval_criterion(row, header_set, c)
        assert status == "FAILED"

    def test_year_boundary(self):
        """Record year=2018 exactly → MET (gte is inclusive)."""
        c = _make_criterion(cid="IC-4", ctype="include", operator="gte",
                            targets=["year"], what_list=["2018"], stage="IH")
        row = {"year": "2018", "title": "Boundary VR"}
        header_set = {"year", "title"}
        status = _e()._eval_criterion(row, header_set, c)
        assert status == "MET"

    def test_language_inclusion_english(self):
        """Record lang='en' + IC equals ['English'] → MET."""
        c = _make_criterion(cid="IC-3", ctype="include", operator="equals",
                            targets=["lang"], what_list=["English"], stage="IH")
        row = {"lang": "en", "title": "A study"}
        header_set = {"lang", "title"}
        status = _e()._eval_criterion(row, header_set, c)
        # _norm_lang('en') → 'en', _norm_lang('English') → 'en'
        # equals → case-insensitive match after normalization
        assert status == "MET"


# ======================================================================
# Edge cases
# ======================================================================

class TestEdgeCases:

    def test_missing_target_column(self):
        """If the target column is not in header_set → MISSING."""
        c = _make_criterion(targets=["language"], what_list=["en"])
        row = {"title": "No lang column"}
        header_set = {"title"}
        status = _e()._eval_criterion(row, header_set, c)
        assert status == "MISSING"

    def test_empty_value(self):
        """If the target column is present but empty → MISSING."""
        c = _make_criterion(targets=["lang"], what_list=["en"])
        row = {"lang": "", "title": "Empty lang"}
        header_set = {"lang", "title"}
        status = _e()._eval_criterion(row, header_set, c)
        assert status == "MISSING"

    def test_llm_operator_returns_unknown(self):
        """LLM-type criteria cannot be evaluated by EH → UNKNOWN."""
        c = _make_criterion(operator="llm", targets=["abstract"],
                            what_list=["Some semantic criterion"])
        row = {"abstract": "This is about VR", "title": "VR study"}
        header_set = {"abstract", "title"}
        status = _e()._eval_criterion(row, header_set, c)
        assert status == "UNKNOWN"

    def test_between_operator(self):
        """Year between 2018 and 2023 → MET for year=2020."""
        c = _make_criterion(cid="IC-range", ctype="include", operator="between",
                            targets=["year"], what_list=["2018", "2023"], stage="IH")
        row = {"year": "2020"}
        header_set = {"year"}
        status = _e()._eval_criterion(row, header_set, c)
        assert status == "MET"

    def test_between_operator_out_of_range(self):
        """Year between 2018 and 2023 → FAILED for year=2025."""
        c = _make_criterion(cid="IC-range", ctype="include", operator="between",
                            targets=["year"], what_list=["2018", "2023"], stage="IH")
        row = {"year": "2025"}
        header_set = {"year"}
        status = _e()._eval_criterion(row, header_set, c)
        assert status == "FAILED"

    def test_regex_operator(self):
        """Regex match on venue."""
        c = _make_criterion(cid="EC-regex", ctype="exclude", operator="regex",
                            targets=["venue"], what_list=[r"ICRA|IROS"])
        row = {"venue": "IEEE ICRA 2023"}
        header_set = {"venue"}
        status = _e()._eval_criterion(row, header_set, c)
        assert status == "FAILED"

    def test_contains_case_insensitive(self):
        """Contains operator is case-insensitive."""
        c = _make_criterion(ctype="exclude", operator="contains",
                            targets=["title"], what_list=["virtual reality"])
        row = {"title": "A Study on Virtual Reality in Education"}
        header_set = {"title"}
        status = _e()._eval_criterion(row, header_set, c)
        assert status == "FAILED"
