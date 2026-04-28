# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_criteria_parser.py — Tests for _parse_free_text_criteria() and
_infer_criterion_details() from the Harmoniser plugin (Plugin 03).

Uses the sample ic_ec_12.txt shipped in docs_/samples/.
"""
import pytest
from conftest import get_harmoniser

# Lazy-import: module loaded after conftest mocks tkinter
_mod = None

def _h():
    global _mod
    if _mod is None:
        _mod = get_harmoniser()
    return _mod


# ======================================================================
# _parse_free_text_criteria
# ======================================================================

class TestParseFreeTextCriteria:

    def test_returns_eight_criteria(self, ic_ec_text):
        """ic_ec_12.txt contains 4 IC + 4 EC = 8 criteria."""
        result = _h()._parse_free_text_criteria(ic_ec_text)
        assert len(result) == 8

    def test_correct_ids(self, ic_ec_text):
        result = _h()._parse_free_text_criteria(ic_ec_text)
        ids = [r[0] for r in result]
        assert "IC-1" in ids
        assert "IC-3" in ids
        assert "IC-4" in ids
        assert "IC-5" in ids
        assert "EC-1" in ids
        assert "EC-2" in ids
        assert "EC-3" in ids
        assert "EC-4" in ids

    def test_correct_types(self, ic_ec_text):
        result = _h()._parse_free_text_criteria(ic_ec_text)
        type_map = {r[0]: r[1] for r in result}
        for k in ("IC-1", "IC-3", "IC-4", "IC-5"):
            assert type_map[k] == "include", f"{k} should be 'include'"
        for k in ("EC-1", "EC-2", "EC-3", "EC-4"):
            assert type_map[k] == "exclude", f"{k} should be 'exclude'"

    def test_labels_are_nonempty(self, ic_ec_text):
        result = _h()._parse_free_text_criteria(ic_ec_text)
        for cid, ctype, label, source in result:
            assert len(label.strip()) > 0, f"Label for {cid} is empty"

    def test_source_text_preserved(self, ic_ec_text):
        """The 4th tuple element should contain the original line."""
        result = _h()._parse_free_text_criteria(ic_ec_text)
        for cid, ctype, label, source in result:
            assert len(source.strip()) > 0

    def test_empty_input(self):
        result = _h()._parse_free_text_criteria("")
        assert result == []

    def test_none_input(self):
        result = _h()._parse_free_text_criteria(None)
        assert result == []

    def test_header_mode_parsing(self):
        text = """
Inclusion criteria:
1. English language
2. Published 2020 or later

Exclusion criteria:
1. Conference proceedings
"""
        result = _h()._parse_free_text_criteria(text)
        assert len(result) == 3
        types = [r[1] for r in result]
        assert types.count("include") == 2
        assert types.count("exclude") == 1


# ======================================================================
# _infer_criterion_details
# ======================================================================

class TestInferCriterionDetails:

    def test_language_inclusion_maps_to_ih(self, aggregate_columns):
        """'written in English' → IH, operator=equals, target=lang."""
        r = _h()._infer_criterion_details("IC-3", "include",
                          "The paper is written in English.",
                          aggregate_columns)
        assert r["stage"] == "IH"
        assert r["operator"] == "equals"
        assert r["target"] == "lang"
        assert r["what"] == ["English"]

    def test_language_exclusion_maps_to_eh(self, aggregate_columns):
        """'written in French or Spanish' → EH, operator=equals."""
        r = _h()._infer_criterion_details("EC-1", "exclude",
                          "The paper is written in French or Spanish.",
                          aggregate_columns)
        assert r["stage"] == "EH"
        assert r["operator"] == "equals"
        assert r["target"] == "lang"

    def test_year_gte_maps_to_ih(self, aggregate_columns):
        """'publication year is 2018 or later' → IH, operator=gte."""
        r = _h()._infer_criterion_details("IC-4", "include",
                          "The publication year is 2018 or later",
                          aggregate_columns)
        assert r["stage"] == "IH"
        assert r["operator"] == "gte"
        assert r["target"] == "year"
        assert "2018" in r["what"]

    def test_venue_contains_maps_to_eh(self, aggregate_columns):
        """'venue contains "ICRA"' → EH, operator=contains."""
        r = _h()._infer_criterion_details("EC-4", "exclude",
                          'The publication venue contains "ICRA" OR "IROS".',
                          aggregate_columns)
        assert r["stage"] == "EH"
        assert r["operator"] == "contains"
        assert r["target"] == "venue"

    def test_semantic_criterion_maps_to_el(self, aggregate_columns):
        """A criterion with no deterministic pattern → EL, operator=llm."""
        r = _h()._infer_criterion_details("EC-2", "exclude",
                          "The paper's primary focus is spatial navigation in a virtual maze",
                          aggregate_columns)
        assert r["stage"] == "EL"
        assert r["operator"] == "llm"

    def test_semantic_inclusion_maps_to_il(self, aggregate_columns):
        """Semantic inclusion criterion → IL, operator=llm."""
        r = _h()._infer_criterion_details("IC-1", "include",
                          "The paper considers immersive virtual reality OR a virtual simulation using a head-mounted display (HMD).",
                          aggregate_columns)
        assert r["stage"] == "IL"
        assert r["operator"] == "llm"

    def test_text_search_with_mention_keyword(self, aggregate_columns):
        """'title, abstract, or keywords mention training OR vocational' → contains."""
        r = _h()._infer_criterion_details("IC-5", "include",
                          "The title, abstract, or keywords mention training OR vocational OR workplace.",
                          aggregate_columns)
        # Should detect "title"/"abstract"/"keywords" pattern
        assert r["operator"] == "contains"
        assert "training" in [w.lower() for w in r["what"]] or len(r["what"]) > 0

    def test_missing_columns_falls_to_llm(self):
        """If a_columns lacks 'lang', language criterion → LLM fallback."""
        cols_no_lang = ["title", "abstract", "year"]
        r = _h()._infer_criterion_details("EC-1", "exclude",
                          "The paper is written in French.",
                          cols_no_lang)
        # Without 'lang' column, can't map to EH
        assert r["operator"] == "llm"
        assert r["stage"] == "EL"
