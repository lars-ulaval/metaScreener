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


class TestRaggedRowsAreRejectedAtTheLLMStages:
    """F-72. EL/IL's corpus reader padded a short row with "" and truncated a
    long one to the header width, where EH/IH skip the same row as
    bad_column_count (plugins/_common/parser.py:305-307). The same
    data/current.csv therefore yielded different record sets depending on
    which stage opened it, and the repair left nothing in the audit trail.
    Both LLM stages now apply EH/IH's reject-and-record policy.

    Uses the diagnostic's fixture: a 4-cell row and a 2-cell row against a
    3-column header (05_report_production.md, probe P5).
    """

    RAGGED = ("local_id,a,b\n"
              "X1,1,2,3\n"      # surplus cell   -> must be rejected
              "X2,1\n"          # missing cell   -> must be rejected
              "X3,1,2\n")       # integral       -> must survive

    CRITERIA = ("stage,id,type,scope,label,operator,target,what,"
                "threshold,enabled,source_text\n")

    def _bundle_zip(self, tmp_path, name):
        import json
        import zipfile
        zp = tmp_path / name
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("manifest.json", json.dumps({}))
            zf.writestr("data/current.csv", self.RAGGED)
            zf.writestr("criteria/criteria_harmonized.csv", self.CRITERIA)
        return str(zp)

    def _assert_policy(self, bundle):
        assert [r["local_id"] for r in bundle.parse.rows] == ["X3"], (
            "F-72: a ragged row was silently repaired into the corpus "
            "instead of being rejected the way EH/IH reject it."
        )
        reasons = [e.get("reason", "") for e in bundle.parse.skipped]
        assert sum("bad_column_count" in r for r in reasons) == 2, (
            f"F-72: the rejected rows must reach the skip list that becomes "
            f"data/input_errors.csv (got reasons: {reasons})."
        )

    def test_el_rejects_and_records(self, tmp_path):
        from conftest import get_el
        self._assert_policy(get_el()._load_bundle(
            self._bundle_zip(tmp_path, "el.zip")))

    def test_il_rejects_and_records(self, tmp_path):
        from conftest import get_il
        self._assert_policy(get_il()._load_bundle(
            self._bundle_zip(tmp_path, "il.zip")))


class TestDecodeLadderParity:
    """F-73. EL/IL decoded with a single utf-8-sig errors="replace" attempt
    where EH/IH fall back through utf-8, cp1252, latin-1
    (plugins/_common/parser.py:217-223). A cp1252 bundle that EH read
    correctly therefore mojibaked to U+FFFD at EL — corrupting exactly the
    text the quote-validation window compares against.
    """

    CP1252 = "local_id,title\nA001,Étude à Québec\n".encode("cp1252")

    def test_el_decodes_cp1252_like_eh(self):
        from conftest import get_el
        from plugins._common.parser import _decode_bytes as eh_decode
        eh_text = eh_decode(self.CP1252)
        el_text = get_el()._decode_bytes(self.CP1252)
        assert "�" not in el_text, (
            "F-73: EL replaced every non-UTF-8 byte with U+FFFD instead of "
            "falling back through the shared encoding ladder."
        )
        assert el_text == eh_text

    def test_il_decodes_cp1252_like_eh(self):
        from conftest import get_il
        from plugins._common.parser import _decode_bytes as eh_decode
        assert get_il()._decode_bytes(self.CP1252) == eh_decode(self.CP1252)

    def test_utf8_with_bom_is_unchanged(self):
        """The goldens are UTF-8; the ladder's first attempt must behave
        exactly as the old single attempt did for them."""
        from conftest import get_el
        b = "﻿local_id,title\nA001,Étude\n".encode("utf-8")
        assert get_el()._decode_bytes(b) == "local_id,title\nA001,Étude\n"


class TestCarriageReturnCanonicalisation:
    """F-76. The EH/IH record splitter rewrites every CRLF and lone CR to
    LF across the whole file text BEFORE parsing, so the rewrite reaches
    inside quoted fields (plugins/_common/parser.py, _split_csv_records).
    This is a deliberate canonicalisation of metadata, kept by decision
    Q-A of docs/internal/FIX_WAVE_4_REPORTS.md — it is load-bearing for
    the committed goldens (the sample corpus has 4 CR-bearing fields, the
    EH golden has 0). This class pins it so it stops being an undeclared
    side effect: removing or changing it must fail here first, on purpose.
    """

    def test_crlf_inside_a_quoted_field_becomes_lf(self):
        text = 'local_id,title\nA001,"line one\r\nline two"\n'
        rep = _parse(text)
        assert rep.rows[0]["title"] == "line one\nline two"

    def test_lone_cr_inside_a_quoted_field_becomes_lf(self):
        text = 'local_id,title\nA001,"pre\rpost"\n'
        rep = _parse(text)
        assert rep.rows[0]["title"] == "pre\npost"

    def test_embedded_lf_is_preserved_verbatim(self):
        """Only the CR variants are rewritten; a quoted LF passes through."""
        text = 'local_id,title\nA001,"line one\nline two"\n'
        rep = _parse(text)
        assert rep.rows[0]["title"] == "line one\nline two"

    def test_the_record_structure_survives_the_rewrite(self):
        """One logical record with multi-line metadata stays one record."""
        text = ('local_id,title\n'
                'A001,"a\r\nb"\n'
                'A002,plain\n')
        rep = _parse(text)
        assert [r["local_id"] for r in rep.rows] == ["A001", "A002"]
        assert rep.skipped == []
