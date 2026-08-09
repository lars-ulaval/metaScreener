
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_input_errors.py — F-03: the record of which citations were dropped as
malformed was itself being dropped.

Three writers, three schemas, one reader that understood one of them, and a
stage that deleted the file:

  - Harmoniser  record_number, reason, observed_len, expected_len, raw
  - EH / IH     record_index_ex_header, reason, raw_record
  - EL / IL     reason, row_json
  - the reader  expected the second, and returned [] for the Harmoniser's
  - EL          put data/input_errors.csv in its copy-forward skip set and
                only rewrote it when EL itself had skipped rows, so the file
                left the bundle entirely on any run where EL skipped nothing

Net effect: a citation dropped by the Harmoniser for being malformed was
invisible by the time the bundle reached EL, and gone from the bundle after
it. There is no way to audit a screening pipeline whose record of dropped
input does not survive the pipeline.

The contract here: one schema, widened rather than narrowed; one writer;
every stage appends; and a dropped record survives all four hops with its
provenance — which stage dropped it, and why — intact.
"""
import csv
import json
import io

import pytest

from plugins._common.input_errors import (
    INPUT_ERRORS_FIELDS,
    InputError,
    merge_input_errors_csv,
    read_input_errors,
    write_input_errors_csv,
)


# ---------------------------------------------------------------------------
# the canonical schema
# ---------------------------------------------------------------------------

class TestSchema:

    def test_is_the_widened_harmoniser_schema_plus_stage(self):
        """'Pick one schema — the Harmoniser's is the richest, so widen
        rather than narrow.' Plus `stage`, without which an appended file
        cannot say who dropped what."""
        assert INPUT_ERRORS_FIELDS == [
            "stage", "record_number", "reason",
            "observed_len", "expected_len", "raw",
        ]

    def test_header_is_written_even_with_no_rows(self):
        text = write_input_errors_csv([])
        assert text.splitlines()[0] == ",".join(INPUT_ERRORS_FIELDS)


# ---------------------------------------------------------------------------
# the reader must understand every schema ever written
# ---------------------------------------------------------------------------

class TestReaderAcceptsLegacySchemas:
    """Bundles written by earlier versions are still on disk. Refusing to
    read them would drop exactly the records this finding is about."""

    def test_reads_harmoniser_schema(self):
        text = (
            "record_number,reason,observed_len,expected_len,raw\n"
            "7,ragged_row,12,15,\"a,b,c\"\n"
        )
        errs = read_input_errors(text, default_stage="Harmoniser")
        assert len(errs) == 1, (
            "F-03: the only reader returned [] for the Harmoniser's schema, "
            "so every record the Harmoniser dropped vanished at the next hop."
        )
        e = errs[0]
        assert e.record_number == 7
        assert e.reason == "ragged_row"
        assert e.observed_len == 12
        assert e.expected_len == 15
        assert e.raw == "a,b,c"
        assert e.stage == "Harmoniser"

    def test_reads_eh_ih_schema(self):
        text = ("record_index_ex_header,reason,raw_record\n"
                "3,missing_local_id,junk\n")
        errs = read_input_errors(text, default_stage="EH")
        assert len(errs) == 1
        assert errs[0].record_number == 3
        assert errs[0].reason == "missing_local_id"
        assert errs[0].raw == "junk"
        assert errs[0].observed_len is None

    def test_reads_el_il_schema(self):
        text = ('reason,row_json\n'
                'missing local_id,"{""title"": ""x""}"\n')
        errs = read_input_errors(text, default_stage="EL")
        assert len(errs) == 1
        assert errs[0].reason == "missing local_id"
        assert '"title"' in errs[0].raw
        assert errs[0].stage == "EL"

    def test_reads_the_canonical_schema(self):
        original = [InputError(stage="IH", record_number=4, reason="dup",
                               raw="r", observed_len=2, expected_len=3)]
        assert read_input_errors(write_input_errors_csv(original)) == original

    def test_empty_text_reads_as_no_errors(self):
        assert read_input_errors("") == []
        assert read_input_errors("   \n  ") == []


# ---------------------------------------------------------------------------
# F-68: unreadable is not the same claim as empty
# ---------------------------------------------------------------------------

class TestUnreadableRaises:
    """F-68. The reader caught every exception and returned [], so an
    existing, non-empty audit file that could not be parsed read back as
    "no records were dropped" — the exact false negative this module
    exists to prevent. Absent or empty still means empty; unreadable now
    raises a typed error the caller must surface."""

    # structurally invalid: the pre-F-67 writer's output for a lone-CR field
    STRUCTURALLY_BROKEN = (
        "stage,record_number,reason,observed_len,expected_len,raw\n"
        "Harmoniser,3,wrong_column_count,4,3,pre\rpost | 2022 | SURPLUS\n"
    )

    def test_structurally_invalid_text_raises(self):
        from plugins._common.input_errors import InputErrorsUnreadableError
        with pytest.raises(InputErrorsUnreadableError):
            read_input_errors(self.STRUCTURALLY_BROKEN)

    def test_unknown_schema_raises(self):
        """A non-empty file with none of the four known layouts was never
        written by this project; treating it as empty hides whatever it is."""
        from plugins._common.input_errors import InputErrorsUnreadableError
        with pytest.raises(InputErrorsUnreadableError):
            read_input_errors("not,a,known,schema\n1,2,3,4\n")

    def test_the_error_is_a_value_error(self):
        """Callers that already catch broadly keep working."""
        from plugins._common.input_errors import InputErrorsUnreadableError
        assert issubclass(InputErrorsUnreadableError, ValueError)

    def test_bundle_export_over_unreadable_prior_fails_loudly(self, tmp_path):
        """The write path must refuse, not silently drop the prior rows —
        and must leave no output zip claiming success."""
        import json as _json
        import zipfile
        from plugins._common.bundle import BundleInfo, _export_next_bundle_zip
        from plugins._common.input_errors import InputErrorsUnreadableError

        zp = tmp_path / "in.zip"
        manifest = {"pipeline": {"stages": {}, "history": []}, "sha256": {}}
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("manifest.json", _json.dumps(manifest))
            zf.writestr("data/current.csv", "local_id,title\nA001,x\n")
            zf.writestr("data/input_errors.csv", self.STRUCTURALLY_BROKEN)
        bundle = BundleInfo(zip_path=str(zp), root="", manifest=manifest,
                            members=[])

        out = tmp_path / "out.zip"
        with pytest.raises(InputErrorsUnreadableError):
            _export_next_bundle_zip(
                str(out), bundle, "data/current.csv", "criteria/c.csv", None,
                ["local_id", "title"], [{"local_id": "A001", "title": "x"}],
                [{"local_id": "A001", "title": "x"}], [], {"OUT": 0},
                stage="EH",
            )
        assert not out.exists(), (
            "F-68: the export must not leave an output bundle behind after "
            "refusing — a zip that exists claims the export succeeded."
        )


# ---------------------------------------------------------------------------
# F-67: hostile content must not break the file's structure
# ---------------------------------------------------------------------------

class TestLoneCarriageReturnSurvives:
    """F-67. csv.writer with lineterminator="\\n" does not quote a field
    containing a lone CR, so a dropped record whose text carried a stray
    \\r produced an input_errors.csv that csv.reader refuses to parse —
    and read_input_errors() then reported it as empty (F-68). The audit
    file must be parseable whatever the dropped record contained."""

    HOSTILE = InputError(stage="Harmoniser", record_number=3,
                         reason="wrong_column_count",
                         raw="pre\rpost | 2022 | SURPLUS",
                         observed_len=4, expected_len=3)

    def test_lone_cr_field_is_parseable_by_csv_reader(self):
        text = write_input_errors_csv([self.HOSTILE])
        rows = list(csv.reader(io.StringIO(text)))
        assert len(rows) == 2, (
            "F-67: a lone CR in the raw field was emitted unquoted, so the "
            "file is not valid CSV and csv.reader cannot parse it."
        )

    def test_lone_cr_field_round_trips_byte_preserved(self):
        [back] = read_input_errors(write_input_errors_csv([self.HOSTILE]))
        assert back == self.HOSTILE
        assert back.raw == "pre\rpost | 2022 | SURPLUS"

    def test_merge_output_stays_parseable_with_hostile_prior(self):
        prior = write_input_errors_csv([self.HOSTILE])
        merged = merge_input_errors_csv(
            prior, [InputError("EH", 5, "missing_local_id", "clean")])
        assert [e.stage for e in read_input_errors(merged)] == ["Harmoniser", "EH"]


# ---------------------------------------------------------------------------
# appending, never overwriting
# ---------------------------------------------------------------------------

class TestAppend:

    def test_merge_keeps_prior_rows(self):
        prior = write_input_errors_csv(
            [InputError("Harmoniser", 1, "ragged_row", "a")])
        merged = merge_input_errors_csv(
            prior, [InputError("EH", 2, "missing_local_id", "b")])
        errs = read_input_errors(merged)
        assert [e.stage for e in errs] == ["Harmoniser", "EH"]

    def test_merge_onto_nothing(self):
        merged = merge_input_errors_csv(None, [InputError("EH", 1, "x", "y")])
        assert len(read_input_errors(merged)) == 1

    def test_merge_with_nothing_new_preserves_the_file(self):
        """The case that deleted the record: a stage that skipped no rows
        must still carry the file forward, not drop it."""
        prior = write_input_errors_csv(
            [InputError("Harmoniser", 1, "ragged_row", "a")])
        merged = merge_input_errors_csv(prior, [])
        assert len(read_input_errors(merged)) == 1

    def test_merge_is_not_deduplicating_distinct_stages(self):
        """The same record_number dropped at two stages is two facts."""
        prior = write_input_errors_csv([InputError("EH", 5, "bad", "raw")])
        merged = merge_input_errors_csv(prior, [InputError("EL", 5, "bad", "raw")])
        assert len(read_input_errors(merged)) == 2

    def test_exact_duplicate_rows_are_not_multiplied(self):
        """Re-exporting the same stage twice must not grow the file without
        bound — the carried-forward copy and the fresh one are one fact."""
        e = InputError("EH", 5, "bad", "raw")
        prior = write_input_errors_csv([e])
        assert len(read_input_errors(merge_input_errors_csv(prior, [e]))) == 1


# ---------------------------------------------------------------------------
# the four-hop round trip
# ---------------------------------------------------------------------------

class TestFourHopSurvival:
    """Write from each stage in pipeline order, reading back and appending at
    every hop, and assert nothing is lost and provenance stays intact."""

    HOPS = [
        ("Harmoniser", InputError("Harmoniser", 1, "ragged_row", "raw-h",
                                  observed_len=12, expected_len=15)),
        ("EH", InputError("EH", 2, "missing_local_id", "raw-eh")),
        ("IH", InputError("IH", 3, "duplicate_local_id:A003", "raw-ih")),
        ("EL", InputError("EL", 4, "missing local_id", '{"t": "x"}')),
        ("IL", InputError("IL", 5, "missing local_id", '{"t": "y"}')),
    ]

    def test_every_dropped_record_survives_every_hop(self):
        carried = None
        for _stage, err in self.HOPS:
            carried = merge_input_errors_csv(carried, [err])

        final = read_input_errors(carried)
        assert len(final) == len(self.HOPS), (
            f"F-03: {len(self.HOPS) - len(final)} dropped record(s) were lost "
            f"in transit. The audit trail of what was excluded from the "
            f"review is the one thing that must not be lossy."
        )
        assert [e.stage for e in final] == [s for s, _ in self.HOPS]
        assert [e.reason for e in final] == [e.reason for _, e in self.HOPS]
        assert [e.record_number for e in final] == [1, 2, 3, 4, 5]

    def test_the_richest_fields_survive_the_narrow_stages(self):
        """The Harmoniser's observed_len/expected_len must still be there
        after passing through stages that never had those columns."""
        carried = None
        for _stage, err in self.HOPS:
            carried = merge_input_errors_csv(carried, [err])
        h = read_input_errors(carried)[0]
        assert h.observed_len == 12 and h.expected_len == 15

    def test_a_stage_that_skips_nothing_still_forwards_the_file(self):
        carried = write_input_errors_csv(
            [InputError("Harmoniser", 1, "ragged_row", "raw")])
        for _ in range(4):
            carried = merge_input_errors_csv(carried, [])
        assert len(read_input_errors(carried)) == 1

    def test_output_is_valid_csv_with_the_canonical_header(self):
        carried = None
        for _stage, err in self.HOPS:
            carried = merge_input_errors_csv(carried, [err])
        rdr = csv.DictReader(io.StringIO(carried))
        assert rdr.fieldnames == INPUT_ERRORS_FIELDS
        assert len(list(rdr)) == len(self.HOPS)


# ---------------------------------------------------------------------------
# adapters from each stage's in-memory shape
# ---------------------------------------------------------------------------

class TestAdapters:

    def test_from_tuple_skipped(self):
        """EH/IH carry (record_index_ex_header, reason, raw_record)."""
        from plugins._common.input_errors import from_tuple_skipped
        errs = from_tuple_skipped([(3, "missing_local_id", "junk")], stage="EH")
        assert errs == [InputError("EH", 3, "missing_local_id", "junk")]

    def test_from_dict_skipped(self):
        """EL/IL carry [{"reason": ..., "row": {...}}] with no index."""
        from plugins._common.input_errors import from_dict_skipped
        errs = from_dict_skipped(
            [{"reason": "missing local_id", "row": {"title": "x"}}], stage="EL")
        assert len(errs) == 1
        assert errs[0].stage == "EL"
        assert errs[0].reason == "missing local_id"
        assert '"title"' in errs[0].raw
        assert errs[0].record_number == 1

    def test_from_dict_skipped_numbers_sequentially(self):
        from plugins._common.input_errors import from_dict_skipped
        errs = from_dict_skipped(
            [{"reason": "a", "row": {}}, {"reason": "b", "row": {}}], stage="IL")
        assert [e.record_number for e in errs] == [1, 2]


# ---------------------------------------------------------------------------
# the legacy tuple reader EH/IH still call
# ---------------------------------------------------------------------------

class TestSurvivesTheRealBundleWriter:
    """The unit tests above exercise the merge; this one drives the actual
    next-bundle writer, which is where the record was being dropped."""

    @staticmethod
    def _seed(tmp_path, errors_text):
        import zipfile
        from plugins._common.bundle import BundleInfo
        zp = tmp_path / "in.zip"
        manifest = {"pipeline": {"stages": {}, "history": []}, "sha256": {}}
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("data/current.csv", "local_id,title\nA001,x\n")
            if errors_text is not None:
                zf.writestr("data/input_errors.csv", errors_text)
        return BundleInfo(zip_path=str(zp), root="", manifest=manifest,
                          members=[])

    @staticmethod
    def _export(bundle, out, skipped, stage):
        from plugins._common.bundle import _export_next_bundle_zip
        _export_next_bundle_zip(
            str(out), bundle, "data/current.csv", "criteria/c.csv", None,
            ["local_id", "title"], [{"local_id": "A001", "title": "x"}],
            [{"local_id": "A001", "title": "x"}], skipped, {"OUT": 0},
            stage=stage,
        )

    @staticmethod
    def _errors_in(zip_path):
        import zipfile
        with zipfile.ZipFile(zip_path, "r") as zf:
            if "data/input_errors.csv" not in zf.namelist():
                return None
            return read_input_errors(zf.read("data/input_errors.csv").decode("utf-8"))

    def test_harmoniser_record_survives_the_eh_hop(self, tmp_path):
        prior = write_input_errors_csv(
            [InputError("Harmoniser", 7, "wrong_column_count", "raw-h",
                        observed_len=12, expected_len=15)])
        bundle = self._seed(tmp_path, prior)
        out = tmp_path / "out.zip"
        self._export(bundle, out, [(3, "missing_local_id", "raw-eh")], "EH")

        errs = self._errors_in(out)
        assert errs is not None and len(errs) == 2, (
            "F-03: EH's export replaced the incoming input_errors.csv with "
            "only its own rows, so the Harmoniser's dropped record was gone "
            "one hop after it was recorded."
        )
        assert [e.stage for e in errs] == ["Harmoniser", "EH"]
        assert errs[0].observed_len == 12

    def test_a_stage_that_skipped_nothing_does_not_delete_the_file(self, tmp_path):
        prior = write_input_errors_csv(
            [InputError("Harmoniser", 7, "wrong_column_count", "raw-h")])
        bundle = self._seed(tmp_path, prior)
        out = tmp_path / "out.zip"
        self._export(bundle, out, [], "EH")

        errs = self._errors_in(out)
        assert errs is not None, (
            "F-03: input_errors.csv is in the copy-forward skip set and was "
            "only rewritten when the stage had skipped rows, so a clean run "
            "deleted the record of everything dropped upstream."
        )
        assert len(errs) == 1

    def test_no_errors_anywhere_still_writes_the_header_only_file(self, tmp_path):
        """F-75. 'A file that exists and says no records were dropped is a
        different claim from no file, and only the first one is auditable'
        — the writer's own docstring. Both bundle writers gated on a
        non-empty read, so a clean corpus produced no file at all and a
        reviewer could not tell "nothing dropped" from "not recorded"."""
        bundle = self._seed(tmp_path, None)
        out = tmp_path / "out.zip"
        self._export(bundle, out, [], "EH")
        errs = self._errors_in(out)
        assert errs is not None, (
            "F-75: a clean run must write the header-only input_errors.csv, "
            "not omit the file."
        )
        assert errs == []

    def test_llm_stage_writer_also_writes_the_header_only_file(self, tmp_path):
        """The EL/IL bundle writer had the same gate (bundle.py:524)."""
        import zipfile
        from plugins._common.bundle import _write_llm_stage_bundle
        src = tmp_path / "in.zip"
        manifest = {"pipeline": {"stages": {}, "history": []}, "sha256": {}}
        with zipfile.ZipFile(src, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("data/current.csv", "local_id,title\nA001,x\n")
        out = tmp_path / "out.zip"
        with zipfile.ZipFile(src, "r") as zf_in:
            _write_llm_stage_bundle(
                str(out), zf_in, root="", manifest=manifest, stage="EL",
                reports_dir_rel="reports", cache_rel="cache/EL_cache.jsonl",
                parse_header=["local_id", "title"],
                survivors=[{"local_id": "A001", "title": "x"}],
                full_rows=[{"local_id": "A001", "title": "x"}],
                full_header=["local_id", "title"], skipped=[],
            )
        errs = self._errors_in(out)
        assert errs is not None and errs == []

    def test_two_hops_accumulate(self, tmp_path):
        bundle = self._seed(tmp_path, None)
        first = tmp_path / "eh.zip"
        self._export(bundle, first, [(3, "missing_local_id", "raw-eh")], "EH")

        from plugins._common.bundle import _load_bundle
        second = tmp_path / "ih.zip"
        self._export(_load_bundle(str(first)), second,
                     [(4, "duplicate_local_id:A004", "raw-ih")], "IH")

        errs = self._errors_in(second)
        assert [e.stage for e in errs] == ["EH", "IH"]


class TestCarriedRowsAreNotRestamped:
    """F-71. EH/IH merged the carried-forward rows into ParseReport.skipped
    and the export writer stamped the whole list with the current stage, so
    one citation dropped at the Harmoniser grew to two rows after EH and
    three after IH — with the Harmoniser's observed_len/expected_len present
    on the original and absent on every copy. Prior rows must pass through
    verbatim; only this stage's own drops get this stage's stamp.

    The seed text is written with the same canonical writer the Harmoniser's
    _clean_aggregate_csv uses, so the bytes match a real first-hop bundle.
    """

    HARM = InputError("Harmoniser", 7, "wrong_column_count", "raw-h",
                      observed_len=12, expected_len=15)

    _seed = staticmethod(TestSurvivesTheRealBundleWriter._seed)
    _export = staticmethod(TestSurvivesTheRealBundleWriter._export)
    _errors_in = staticmethod(TestSurvivesTheRealBundleWriter._errors_in)

    @classmethod
    def _carried_tuples(cls, zip_path):
        """What the pre-fix EH/IH load path fed into pr.skipped: the prior
        file re-read through _load_input_errors_from_text."""
        import zipfile
        from plugins._common.parser import _load_input_errors_from_text
        with zipfile.ZipFile(zip_path, "r") as zf:
            text = zf.read("data/input_errors.csv").decode("utf-8")
        return _load_input_errors_from_text(text)

    def test_one_harmoniser_drop_stays_one_row_across_two_hops(self, tmp_path):
        bundle = self._seed(tmp_path, write_input_errors_csv([self.HARM]))
        eh_out = tmp_path / "eh.zip"
        # the contaminated list the old UI passed: carried copies + nothing new
        self._export(bundle, eh_out, self._carried_tuples(bundle.zip_path), "EH")

        errs = self._errors_in(eh_out)
        assert [e.stage for e in errs] == ["Harmoniser"], (
            f"F-71: the carried-forward row was re-stamped as EH — one drop "
            f"became {len(errs)} rows after one hop (stages: "
            f"{[e.stage for e in errs]})."
        )

        from plugins._common.bundle import _load_bundle
        ih_out = tmp_path / "ih.zip"
        self._export(_load_bundle(str(eh_out)), ih_out,
                     self._carried_tuples(eh_out), "IH")
        errs = self._errors_in(ih_out)
        assert [e.stage for e in errs] == ["Harmoniser"]
        assert errs[0].observed_len == 12 and errs[0].expected_len == 15, (
            "F-71: the Harmoniser's ragged-row diagnostics were dropped in "
            "transit — the surviving row must keep observed_len/expected_len."
        )

    def test_own_drops_still_get_this_stages_stamp(self, tmp_path):
        bundle = self._seed(tmp_path, write_input_errors_csv([self.HARM]))
        out = tmp_path / "out.zip"
        skipped = self._carried_tuples(bundle.zip_path) + \
            [(3, "missing_local_id", "raw-eh")]
        self._export(bundle, out, skipped, "EH")
        errs = self._errors_in(out)
        assert [e.stage for e in errs] == ["Harmoniser", "EH"]
        assert errs[1].reason == "missing_local_id"

    def test_re_exporting_the_same_stage_is_idempotent(self, tmp_path):
        bundle = self._seed(tmp_path, write_input_errors_csv([self.HARM]))
        first = tmp_path / "first.zip"
        skipped = self._carried_tuples(bundle.zip_path) + \
            [(3, "missing_local_id", "raw-eh")]
        self._export(bundle, first, skipped, "EH")

        from plugins._common.bundle import _load_bundle
        again = tmp_path / "again.zip"
        self._export(_load_bundle(str(first)), again,
                     self._carried_tuples(first) +
                     [(3, "missing_local_id", "raw-eh")], "EH")
        errs = self._errors_in(again)
        assert [e.stage for e in errs] == ["Harmoniser", "EH"], (
            "F-71: re-running a stage must not grow the file."
        )


class TestExportButtonsWriteTheCanonicalSchema:
    """F-74. The EL/IL "Export input_errors.csv…" buttons still carried
    inline csv.writer blocks emitting the legacy reason,row_json layout —
    the last two writers of the schema F-03 retired, and a file that
    disagreed with the data/input_errors.csv of the same name in the
    bundle. The buttons now route through the canonical writer; this pins
    the non-widget core they invoke."""

    def test_dict_shaped_skips_export_as_the_canonical_schema(self, tmp_path):
        from plugins._common.exporters import _export_input_errors_csv_from_dicts
        p = tmp_path / "input_errors.csv"
        _export_input_errors_csv_from_dicts(
            str(p),
            [{"reason": "missing local_id", "row": {"title": "x"}},
             {"reason": "bad_column_count:4!=expected:3",
              "row": {"raw": "a | b | c | d"}}],
            stage="EL",
        )
        text = p.read_text(encoding="utf-8")
        rdr = csv.DictReader(io.StringIO(text))
        assert rdr.fieldnames == INPUT_ERRORS_FIELDS, (
            "F-74: the button must write the canonical six-column schema, "
            "not the legacy reason,row_json layout."
        )
        errs = read_input_errors(text)
        assert [e.stage for e in errs] == ["EL", "EL"]
        assert errs[0].reason == "missing local_id"
        assert '"title"' in errs[0].raw

    def test_el_and_il_views_no_longer_carry_the_legacy_writer(self):
        """The inline writers are the defect; their removal is the fix.
        Source-level check because the click handlers are Tk-bound."""
        from pathlib import Path
        for rel in ("plugins/06_el/ui.py", "plugins/07_il/ui.py"):
            src = (Path(__file__).parent.parent / rel).read_text(encoding="utf-8")
            assert 'w.writerow(["reason", "row_json"])' not in src, (
                f"F-74: {rel} still writes the legacy two-column layout."
            )
            assert "_export_input_errors_csv_from_dicts" in src


class TestLegacyTupleReader:

    def test_load_input_errors_from_text_reads_the_harmoniser_schema(self):
        """plugins/04_eh/ui.py reports 'Imported previous input_errors: N
        rows' from this. It said 0 for every Harmoniser-written file."""
        from plugins._common.parser import _load_input_errors_from_text
        text = ("record_number,reason,observed_len,expected_len,raw\n"
                "7,ragged_row,12,15,junk\n")
        out = _load_input_errors_from_text(text)
        assert out == [(7, "ragged_row", "junk")], (
            "F-03: EH's 'Imported previous input_errors: (0 rows)' was not a "
            "report that there were none — it was the reader failing to "
            "understand the file it had just found."
        )

    def test_still_reads_its_own_schema(self):
        from plugins._common.parser import _load_input_errors_from_text
        text = ("record_index_ex_header,reason,raw_record\n"
                "3,missing_local_id,junk\n")
        assert _load_input_errors_from_text(text) == [(3, "missing_local_id", "junk")]
