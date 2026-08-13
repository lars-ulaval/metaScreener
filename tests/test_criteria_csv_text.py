# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""test_criteria_csv_text.py — pinning the criteria CSV writer before splitting it.

`plugins/03_harmoniser/exporters.py::_export_csv` writes
`criteria/criteria_harmonized.csv`, whose SHA is recorded in the bundle manifest by
`plugins/03_harmoniser/bundle.py`. It is byte-identity-critical: a change to its
output invalidates every manifest that came before.

Wave 13e's preview needs that same CSV **as text**, because
`plugins/_common/parser.py::_load_criteria_from_text` is the only supported way to
build `Criterion` objects and it takes text. The alternative — a second writer living
in the preview — was measured byte-identical to this one *today* (1991 bytes both), and
that is exactly the trap: two hand-maintained copies of an eleven-column
byte-identity-critical schema, correct on the day they are written. F-109 is the row
about what happens next.

So `_export_csv` is split into `_criteria_csv_text(rows) -> str` plus a two-line file
write. **This file exists to prove the split moves no bytes.**

`TestTheBytesAreWhatTheyWere` characterises the writer's output and must pass
*unchanged* before and after the extraction — it is the lock, not a new assertion.
`TestTheTextFunctionIsTheSameWriter` fails before the extraction (the symbol does not
exist) and passes after.

The fixture exercises every decision the writer makes rather than restating one happy
row: `_what_to_export`'s four branches, the `enabled` coercion, the `scope` default,
absent keys, and a label containing the delimiter.
"""

import io
import os
import tempfile

import pytest

from conftest import _import_plugin


def _exporters():
    return _import_plugin("03_harmoniser", "exporters")


def _hparser():
    return _import_plugin("03_harmoniser", "parser")


def _cparser():
    return _import_plugin("_common", "parser")


# --- the fixture -------------------------------------------------------------
# Each row is here because it makes the writer take a different branch. A row that
# only repeats a decision another row already covers is not worth its line.

ROWS = [
    # `contains` with several operands -> ";"-joined by _what_to_export
    {"stage": "EH", "id": "EC-4", "type": "exclude", "scope": "metadata",
     "label": "The venue contains ICRA or IROS.", "operator": "contains",
     "target": "venue", "what": ["ICRA", "IROS"], "threshold": "",
     "enabled": True, "source_text": "EC-4 venue"},
    # `equals` with exactly one operand -> emitted bare, NOT ";"-joined
    {"stage": "IH", "id": "IC-3", "type": "include", "scope": "metadata",
     "label": "Written in English.", "operator": "equals", "target": "lang",
     "what": ["English"], "threshold": "", "enabled": True,
     "source_text": "IC-3 lang"},
    # `gte` single operand -> the same bare branch, different operator
    {"stage": "IH", "id": "IC-4", "type": "include", "scope": "metadata",
     "label": "Published in 2018 or later.", "operator": "gte", "target": "year",
     "what": ["2018"], "threshold": "", "enabled": True, "source_text": "IC-4 year"},
    # `between` with exactly two -> its own branch
    {"stage": "IH", "id": "IC-9", "type": "include", "scope": "metadata",
     "label": "Between 2018 and 2024.", "operator": "between", "target": "year",
     "what": ["2018", "2024"], "threshold": "", "enabled": True,
     "source_text": "IC-9 span"},
    # `in_list` -> falls through to the join, and F-167's shape
    {"stage": "EH", "id": "EC-1", "type": "exclude", "scope": "metadata",
     "label": "Written in French or Spanish.", "operator": "in_list",
     "target": "lang", "what": ["French", "Spanish"], "threshold": "",
     "enabled": True, "source_text": "EC-1 lang"},
    # enabled=False -> must serialise as 0, and a label carrying the CSV delimiter
    {"stage": "EH", "id": "EC-8", "type": "exclude", "scope": "metadata",
     "label": 'Excluded, "quoted", and; delimited.', "operator": "contains",
     "target": "title", "what": ["x"], "threshold": "", "enabled": False,
     "source_text": "EC-8 punctuation"},
    # an LLM row with a threshold, and NO `scope` key at all -> defaults to metadata
    {"stage": "IL", "id": "IC-1", "type": "include",
     "label": "The paper considers immersive VR.", "operator": "llm",
     "target": "keywords", "what": ["The paper considers immersive VR."],
     "threshold": "0.60", "enabled": True, "source_text": "IC-1 vr"},
    # a row missing most keys entirely -> every absent cell must be ""
    {"id": "EC-9", "operator": "contains", "what": []},
    # `regex` with MORE THAN ONE operand. This is the only shape in which
    # `_what_to_export` differs from a plain ";".join -- measured, wave 13e B's
    # mutation battery -- so without this row a writer that dropped
    # `_what_to_export` entirely would pass every assertion in this file.
    {"stage": "EH", "id": "EC-7", "type": "exclude", "scope": "metadata",
     "label": "Matches a four-digit code.", "operator": "regex", "target": "title",
     "what": [r"^\d{4}$", "SECOND-OPERAND-IS-DROPPED"], "threshold": "",
     "enabled": True, "source_text": "EC-7 regex"},
]


def _write_via_file(exporters, rows):
    """Drive the real `_export_csv` and hand back the bytes it put on disk."""
    fd, path = tempfile.mkstemp(suffix=".csv", prefix="w13e_")
    os.close(fd)
    try:
        exporters._export_csv(rows, path)
        return io.open(path, "rb").read()
    finally:
        os.remove(path)


class TestTheBytesAreWhatTheyWere:
    """The lock. These assertions must not move when the writer is split.

    They are written against the bytes on disk, because that is what the manifest
    hashes — not against an in-memory string that might differ in line endings.
    """

    def test_the_header_is_the_eleven_column_schema_in_order(self):
        raw = _write_via_file(_exporters(), ROWS)
        first = raw.split(b"\r\n")[0]
        assert first == (b"stage,id,type,scope,label,operator,target,what,"
                         b"threshold,enabled,source_text")

    def test_rows_are_crlf_terminated(self):
        """`csv.writer` defaults to \\r\\n and the manifest was computed over it."""
        raw = _write_via_file(_exporters(), ROWS)
        assert raw.endswith(b"\r\n")
        assert b"\n" not in raw.replace(b"\r\n", b"")

    def test_it_is_utf8_without_a_bom(self):
        raw = _write_via_file(_exporters(), ROWS)
        assert not raw.startswith(b"\xef\xbb\xbf")
        raw.decode("utf-8")

    @pytest.mark.parametrize("cid,expected_what", [
        ("EC-4", "ICRA;IROS"),      # contains -> joined
        ("IC-3", "English"),        # equals + one operand -> bare
        ("IC-4", "2018"),           # gte + one operand -> bare
        ("IC-9", "2018;2024"),      # between + two -> its own branch
        ("EC-1", "French;Spanish"),  # in_list -> joined
        ("EC-9", ""),               # empty list -> empty cell
        # regex keeps ONLY the first operand -- the one branch that is not a join
        ("EC-7", r"^\d{4}$"),
    ])
    def test_what_is_serialised_by_operator(self, cid, expected_what):
        """`_what_to_export`'s branches, pinned through the writer that calls it."""
        raw = _write_via_file(_exporters(), ROWS)
        row = _row_by_id(raw, cid)
        assert row["what"] == expected_what

    def test_enabled_is_1_or_0_and_never_true_or_false(self):
        raw = _write_via_file(_exporters(), ROWS)
        assert _row_by_id(raw, "EC-4")["enabled"] == "1"
        assert _row_by_id(raw, "EC-8")["enabled"] == "0"

    def test_absent_scope_defaults_to_metadata_and_other_absent_cells_are_empty(self):
        raw = _write_via_file(_exporters(), ROWS)
        ic1 = _row_by_id(raw, "IC-1")
        assert ic1["scope"] == "metadata", "the one defaulted column"
        ec9 = _row_by_id(raw, "EC-9")
        assert ec9["scope"] == "metadata"
        for col in ("stage", "type", "label", "target", "threshold", "source_text"):
            assert ec9[col] == "", "absent key %r must be empty, not 'None'" % col
        assert ec9["enabled"] == "1", "absent `enabled` defaults to True"

    def test_a_label_containing_quotes_and_delimiters_round_trips(self):
        raw = _write_via_file(_exporters(), ROWS)
        assert _row_by_id(raw, "EC-8")["label"] == 'Excluded, "quoted", and; delimited.'

    def test_the_whole_file_is_byte_stable_across_two_writes(self):
        """No timestamp, no ordering nondeterminism — the manifest depends on it."""
        e = _exporters()
        assert _write_via_file(e, ROWS) == _write_via_file(e, ROWS)


class TestTheTextFunctionIsTheSameWriter:
    """`_criteria_csv_text` must be the writer, not a second one that agrees today."""

    def test_the_text_function_exists(self):
        assert hasattr(_exporters(), "_criteria_csv_text"), (
            "the preview needs the CSV as text; see FIX_WAVE_13E_PREVIEW.md B-4"
        )

    def test_it_returns_exactly_what_export_csv_writes(self):
        e = _exporters()
        on_disk = _write_via_file(e, ROWS)
        as_text = e._criteria_csv_text(ROWS)
        assert as_text.encode("utf-8") == on_disk, (
            "the extraction moved bytes; the bundle manifest hashes these"
        )

    def test_it_writes_nothing(self):
        """The whole point: the preview must reach the text without touching disk."""
        e = _exporters()
        writes = []
        import sys

        def hook(event, args):
            if event == "open" and len(args) > 1 and args[1] and any(
                    c in str(args[1]) for c in "wax+"):
                writes.append(str(args[0]))
            elif event in ("os.mkdir", "os.rename", "os.remove"):
                writes.append(event)

        sys.addaudithook(hook)
        n0 = len(writes)
        e._criteria_csv_text(ROWS)
        assert writes[n0:] == [], "_criteria_csv_text touched the filesystem: %r" % (
            writes[n0:],)

    def test_the_text_survives_the_round_trip_the_preview_depends_on(self):
        """rows -> text -> `Criterion`, which is the preview's whole input path."""
        e, cp = _exporters(), _cparser()
        text = e._criteria_csv_text(ROWS)
        eh = cp._load_criteria_from_text(text, "EH")
        by_id = {c.cid: c for c in eh.criteria}
        assert "EC-8" not in by_id, "enabled=0 rows are dropped by the loader"
        assert by_id["EC-4"].what_list == ["ICRA", "IROS"]
        assert by_id["EC-1"].what_list == ["French", "Spanish"], (
            "F-167's multi-operand shape must survive rows -> text -> Criterion"
        )
        ih = cp._load_criteria_from_text(text, "IH")
        assert {c.cid for c in ih.criteria} == {"IC-3", "IC-4", "IC-9"}


# --- helper ------------------------------------------------------------------

def _row_by_id(raw_bytes, cid):
    import csv as _csv
    rdr = _csv.DictReader(io.StringIO(raw_bytes.decode("utf-8")))
    for r in rdr:
        if r.get("id") == cid:
            return r
    raise AssertionError("no row %r in the exported CSV" % cid)
