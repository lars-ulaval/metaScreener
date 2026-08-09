# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_corpus_parser.py - Record-identity rules in the shared corpus parser.

Regression cover for F-55. plugins/_common/parser._parse_csv_tolerant_text
(used by EH and IH) skipped rows with a missing local_id but accepted
duplicates, while plugins/06_el/screen._load_bundle:213-215 (used by EL and
IL) dropped duplicates into its skipped list. A corpus carrying a repeated
local_id therefore screened cleanly through stages 04 and 05 and silently
lost rows at stage 06 - and because EL builds its per-record maps by
local_id, the surviving row's evidence would be whichever copy landed last.

Both stages now treat a duplicate identifier the same way: skip it, and
record why in the skipped list that becomes data/input_errors.csv.
"""
from conftest import get_eh


HEADER = "local_id,title,abstract,keywords,lang,year,doc_type"


def _csv(*rows):
    return "\n".join([HEADER] + list(rows)) + "\n"


def _row(local_id, title="a title"):
    return "%s,%s,an abstract,kw,English,2020,journal" % (local_id, title)


def _parse(text):
    return get_eh()._parse_csv_tolerant_text(text)


class TestDistinctIdsAreKept:

    def test_all_unique_rows_survive(self):
        rep = _parse(_csv(_row("A001"), _row("A002"), _row("A003")))
        assert [r["local_id"] for r in rep.rows] == ["A001", "A002", "A003"]
        assert rep.skipped == []

    def test_ids_differing_only_by_case_are_distinct(self):
        """local_id is an opaque identifier; do not fold case."""
        rep = _parse(_csv(_row("a001"), _row("A001")))
        assert len(rep.rows) == 2
        assert rep.skipped == []


class TestDuplicateIdsAreSkipped:

    def test_second_occurrence_is_skipped(self):
        rep = _parse(_csv(_row("A001", "first"), _row("A001", "second")))
        assert [r["local_id"] for r in rep.rows] == ["A001"]
        assert rep.rows[0]["title"] == "first", "the FIRST occurrence must win"
        assert len(rep.skipped) == 1

    def test_skip_reason_names_the_duplicate(self):
        rep = _parse(_csv(_row("A001"), _row("A001")))
        _idx, reason, _raw = rep.skipped[0]
        assert "duplicate" in reason.lower()
        assert "A001" in reason

    def test_skipped_record_index_is_the_offending_row(self):
        rep = _parse(_csv(_row("A001"), _row("A002"), _row("A001")))
        assert [r["local_id"] for r in rep.rows] == ["A001", "A002"]
        idx, _reason, _raw = rep.skipped[0]
        assert idx == 3, "1-based, excluding the header"

    def test_triplicate_skips_two(self):
        rep = _parse(_csv(_row("A001"), _row("A001"), _row("A001")))
        assert len(rep.rows) == 1
        assert len(rep.skipped) == 2

    def test_missing_and_duplicate_ids_are_both_reported(self):
        rep = _parse(_csv(_row("A001"), _row(""), _row("A001")))
        assert [r["local_id"] for r in rep.rows] == ["A001"]
        reasons = sorted(reason for _i, reason, _r in rep.skipped)
        assert len(reasons) == 2
        assert any("missing" in r.lower() for r in reasons)
        assert any("duplicate" in r.lower() for r in reasons)


class TestParityWithTheLLMStages:

    def test_el_and_eh_agree_on_a_duplicated_corpus(self):
        """The F-55 divergence itself: EL dropped duplicates, EH did not."""
        from conftest import get_el

        text = _csv(_row("A001"), _row("A001"), _row("A002"))
        eh_rep = _parse(text)
        _header, el_rows = get_el()._csv_read(text)

        seen, el_kept = set(), []
        for r in el_rows:
            lid = (r.get("local_id") or "").strip()
            if lid and lid not in seen:
                seen.add(lid)
                el_kept.append(lid)

        assert [r["local_id"] for r in eh_rep.rows] == el_kept
