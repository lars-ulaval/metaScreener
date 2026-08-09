# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_criteria_polarity.py - Polarity handling in the EL/IL criteria parser.

Regression cover for F-04. `_parse_criteria_harmonized_csv` defaulted a
blank `type` cell to "exclude" in BOTH stages. In EL that is the stage's
natural polarity and harmless; in IL it silently inverts the criterion, so
an LLM verdict of "meet" would EXCLUDE the record instead of including it.

A criterion whose polarity cannot be determined must not be guessed at.
These tests pin the chosen behaviour: skip the row and emit a warning that
the View surfaces in its "Notes / warnings" panel, so the criterion is
visibly absent rather than invisibly inverted.
"""
from conftest import get_el, get_il


HEADER = "stage,id,type,scope,label,operator,target,what,threshold,enabled,source_text"


def _csv(*rows):
    return "\n".join([HEADER] + list(rows)) + "\n"


def _row(stage, cid, ctype, label="some criterion"):
    return "%s,%s,%s,metadata,%s,llm,abstract,%s,0.60,1,%s" % (
        stage, cid, ctype, label, label, label
    )


class TestExplicitPolarityIsPreserved:
    """The happy path must be untouched by the F-04 fix."""

    def test_il_include_criterion_loads_as_include(self):
        rep = get_il()._parse_criteria_harmonized_csv(
            _csv(_row("IL", "IC-1", "include")), stage_filter="IL"
        )
        assert [c.id for c in rep.criteria] == ["IC-1"]
        assert rep.criteria[0].ctype == "include"

    def test_el_exclude_criterion_loads_as_exclude(self):
        rep = get_el()._parse_criteria_harmonized_csv(
            _csv(_row("EL", "EC-1", "exclude")), stage_filter="EL"
        )
        assert [c.id for c in rep.criteria] == ["EC-1"]
        assert rep.criteria[0].ctype == "exclude"

    def test_il_can_still_carry_an_exclude_criterion(self):
        """An explicit polarity is always honoured, whatever the stage."""
        rep = get_il()._parse_criteria_harmonized_csv(
            _csv(_row("IL", "EC-9", "exclude")), stage_filter="IL"
        )
        assert rep.criteria[0].ctype == "exclude"


class TestBlankPolarityIsRejected:

    def test_il_blank_type_is_not_silently_inverted(self):
        """The actual F-04 defect: blank type became "exclude" in IL."""
        rep = get_il()._parse_criteria_harmonized_csv(
            _csv(_row("IL", "IC-1", "")), stage_filter="IL"
        )
        assert [c.ctype for c in rep.criteria] != ["exclude"]

    def test_il_blank_type_row_is_skipped_with_a_warning(self):
        rep = get_il()._parse_criteria_harmonized_csv(
            _csv(_row("IL", "IC-1", "")), stage_filter="IL"
        )
        assert rep.criteria == []
        assert any("IC-1" in w for w in rep.warnings)
        assert any("type" in w.lower() for w in rep.warnings)

    def test_el_blank_type_row_is_skipped_with_a_warning(self):
        """Mirror case: EL's default happened to match its polarity, but a
        blank cell is still an unspecified criterion, not an exclusion."""
        rep = get_el()._parse_criteria_harmonized_csv(
            _csv(_row("EL", "EC-1", "")), stage_filter="EL"
        )
        assert rep.criteria == []
        assert any("EC-1" in w for w in rep.warnings)

    def test_unrecognised_type_is_also_rejected(self):
        rep = get_il()._parse_criteria_harmonized_csv(
            _csv(_row("IL", "IC-1", "maybe")), stage_filter="IL"
        )
        assert rep.criteria == []
        assert any("IC-1" in w for w in rep.warnings)

    def test_valid_rows_survive_alongside_a_rejected_one(self):
        rep = get_il()._parse_criteria_harmonized_csv(
            _csv(
                _row("IL", "IC-1", "include"),
                _row("IL", "IC-2", ""),
                _row("IL", "IC-3", "include"),
            ),
            stage_filter="IL",
        )
        assert [c.id for c in rep.criteria] == ["IC-1", "IC-3"]
        assert any("IC-2" in w for w in rep.warnings)
