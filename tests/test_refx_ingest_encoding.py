# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_refx_ingest_encoding.py - Corpus ingestion under non-UTF-8 encodings.

Regression cover for F-13 and F-38 in plugins/02_references_of_x/services.py.

F-13: Ingestor.from_csv_or_xlsx read CSVs with pd.read_csv(path) (no
      encoding argument) and, on failure, with open(path, encoding="utf-8").
      A cp1252 or Latin-1 file - routine output from Windows reference
      managers - failed both, was logged twice, and left rows == [], so the
      entire corpus silently became empty. plugins/_common/parser.py:215-221
      has had a four-encoding ladder for exactly this since Conv 5.

F-38: the fallback used "utf-8" rather than "utf-8-sig", so a BOM'd CSV
      produced a first column literally named "﻿title" and every
      r.get("title") returned "" - silent loss of the title column for the
      whole corpus.

A silently empty or silently title-less corpus is the worst failure mode
this pipeline has: nothing downstream can tell it apart from a genuinely
empty search result.
"""
import pytest

from conftest import get_refx_services


svc = get_refx_services()


HEADER = "title,authors,year,doi\n"
# Non-ASCII in every row, restricted to characters that all three of
# utf-8, cp1252 and latin-1 can represent, so one fixture serves them all.
ROWS = [
    '"Restorative effects of nature, a réview","Gärling, T.",2003,10.1/a\n',
    '"Virtual reality for rehabilitation","Désirée, Ö.",2020,10.1/b\n',
]


class _CapturingLogger:
    def __init__(self):
        self.lines = []

    def log(self, msg):
        self.lines.append(str(msg))


def _write(tmp_path, name, encoding, bom=False):
    path = tmp_path / name
    text = HEADER + "".join(ROWS)
    data = text.encode(encoding)
    if bom:
        data = b"\xef\xbb\xbf" + data
    path.write_bytes(data)
    return str(path)


def _ingest(path):
    logger = _CapturingLogger()
    items = svc.Ingestor(logger=logger).from_csv_or_xlsx(path)
    return items, logger


class TestEncodingLadder:

    def test_utf8_still_works(self):
        """Baseline: the path that already worked must keep working."""
        pass  # exercised by the parametrised test below

    @pytest.mark.parametrize(
        "encoding,bom",
        [
            ("utf-8", False),
            ("utf-8", True),      # F-38: BOM'd CSV
            ("cp1252", False),    # F-13: Windows reference-manager default
            ("latin-1", False),
        ],
    )
    def test_every_supported_encoding_yields_all_records(self, tmp_path, encoding, bom):
        path = _write(tmp_path, "corpus.csv", encoding, bom=bom)
        items, _logger = _ingest(path)
        assert len(items) == len(ROWS), (
            "%s%s produced %d records, expected %d"
            % (encoding, " with BOM" if bom else "", len(items), len(ROWS))
        )

    @pytest.mark.parametrize("encoding,bom", [("utf-8", True), ("cp1252", False)])
    def test_title_column_survives(self, tmp_path, encoding, bom):
        """F-38: a BOM renamed the first column, emptying every title."""
        path = _write(tmp_path, "corpus.csv", encoding, bom=bom)
        items, _logger = _ingest(path)
        assert all(it.title for it in items), [it.title for it in items]
        assert "restorative" in items[0].title.lower()

    def test_non_ascii_characters_are_preserved(self, tmp_path):
        path = _write(tmp_path, "corpus.csv", "cp1252")
        items, _logger = _ingest(path)
        assert "é" in items[0].title, items[0].title
        assert "ä" in items[0].authors, items[0].authors  # Garling

    def test_cp1252_only_characters_survive(self, tmp_path):
        """0x96 en-dash exists in cp1252 but not in latin-1.

        This is the exact byte that made docs_/samples/ex_ref_2.txt
        undecodable as UTF-8 (F-56), so it is worth pinning on its own.
        """
        path = tmp_path / "corpus.csv"
        row = '"Pages 78–91 of something","A, B",2001,10.1/c\n'
        data = HEADER.encode("cp1252") + row.encode("cp1252")
        assert b"\x96" in data, "the fixture must contain the cp1252-only byte"
        path.write_bytes(data)
        items, _logger = _ingest(str(path))
        assert len(items) == 1
        assert "–" in items[0].title, items[0].title


class TestEmptyResultIsReported:

    def test_unreadable_file_raises_rather_than_returning_nothing(self, tmp_path):
        """F-13: total failure must not look like an empty search result."""
        path = tmp_path / "corpus.csv"
        path.write_bytes(b"")
        with pytest.raises(Exception):
            _ingest(str(path))

    def test_zero_rows_is_logged_loudly(self, tmp_path):
        """A header-only CSV is legitimately empty, but must say so."""
        path = tmp_path / "corpus.csv"
        path.write_bytes(HEADER.encode("utf-8"))
        items, logger = _ingest(str(path))
        assert items == []
        assert any("no record" in ln.lower() or "0 items" in ln.lower()
                   or "empty" in ln.lower() for ln in logger.lines), logger.lines


class TestShippedSampleIsReadable:

    def test_docs_samples_reference_list_decodes(self):
        """docs_/samples/ex_ref_2.txt is the documented Plugin 02 input.

        It was cp1252 until F-56; this pins that the shipped sample can
        actually be read by the plugin it demonstrates.
        """
        from conftest import SAMPLES_DIR
        raw = (SAMPLES_DIR / "ex_ref_2.txt").read_bytes()
        raw.decode("utf-8")  # must not raise
