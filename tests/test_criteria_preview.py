# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""test_criteria_preview.py — what each criterion will do, before a stage is run.

`plugins/03_harmoniser/preview.py::build_criteria_preview` answers one question per
criterion: how many records does this remove, out of how many, and which ones. Nothing
in the product answered it before — `04_eh/ui.py::_refresh_criteria_table` has the
columns but fills them only once `pre_run` is false.

Three properties are load-bearing and each has its own class below.

**Criteria within a stage are not sequential.** Every criterion in a stage is evaluated
against that stage's full input, so per-criterion removals overlap: on the reference
corpus six records fail both `IC-3` and `IC-4`, and 8 + 611 is 619 while the stage
removes 613. A running total per criterion is arithmetic nonsense, and
`TestTheDisplayCannotProduceAMisleadingTotal` exists to keep it out.

**`llm` criteria are not evaluated here and must say so.** Four of the eight reference
criteria are seeded to EL/IL. Omitting them would misrepresent the table; showing them
as `removes 0` would be a lie of a worse kind.

**`unknown` and `missing` are shown beside `removed`.** Wave 13e B-1 measured that a
`year` of `2018-03` is `UNKNOWN` for a `gte` comparison, so the criterion silently does
not apply to that record. On this corpus that count is zero; on a corpus using
year-month strings it would be every record, and the criterion would look like it was
working while filtering nothing. The removal count alone cannot show that.
"""

import io
import sys

import pytest

from conftest import _import_plugin, PROJECT_ROOT


CORPUS = PROJECT_ROOT / "samples" / "20260122_1654_aggregate.csv"
PROSE = PROJECT_ROOT / "samples" / "ic_ec_12.txt"


def _preview():
    return _import_plugin("03_harmoniser", "preview")


def _hparser():
    return _import_plugin("03_harmoniser", "parser")


def _inference():
    return _import_plugin("03_harmoniser", "inference")


def _cparser():
    return _import_plugin("_common", "parser")


# --- fixtures from the producer, never hand-typed ----------------------------

@pytest.fixture(scope="module")
def corpus():
    """The reference corpus, parsed exactly as a real run parses it."""
    cp = _cparser()
    text = io.open(CORPUS, encoding="utf-8-sig").read()
    parse = cp._parse_csv_tolerant_text(text)
    return parse.header, parse.rows


@pytest.fixture(scope="module")
def harmonised(corpus):
    """The rules the Harmoniser emits today from the reference prose.

    Built by driving the real free-text path -- `_parse_free_text_criteria` then
    `_infer_criterion_details` -- rather than by restating its output, so that a
    change in the translator shows up here instead of being masked.
    """
    hp, hi = _hparser(), _inference()
    header, _rows = corpus
    cols, stats = hp._load_a_header_and_stats(str(CORPUS))
    default_target, _ = hp._canonicalize_targets(
        hp._get_best_text_targets(cols, stats), cols)
    out = []
    for cid, ctype, label, src in hp._parse_free_text_criteria(
            io.open(PROSE, encoding="utf-8").read()):
        inf = hi._infer_criterion_details(
            crit_id=cid, crit_type=ctype, label=label,
            a_columns=list(cols), default_text_target=default_target)
        out.append({
            "stage": inf["stage"], "id": cid, "type": ctype, "scope": "metadata",
            "label": label, "operator": inf["operator"], "target": inf["target"],
            "what": inf["what"], "enabled": True, "source_text": src,
            "threshold": ("" if inf["stage"] in {"EH", "IH"} else "0.60"),
        })
    return out


@pytest.fixture(scope="module")
def report(harmonised, corpus):
    header, rows = corpus
    return _preview().build_criteria_preview(harmonised, header, rows)


def _stage(report, name):
    for s in report.stages:
        if s.stage == name:
            return s
    raise AssertionError("no stage %r in %r" % (name, [s.stage for s in report.stages]))


def _crit(report, cid):
    for s in report.stages:
        for c in s.criteria:
            if c.criterion_id == cid:
                return c
    raise AssertionError("no criterion %r in the report" % cid)


# --- the tests ---------------------------------------------------------------

class TestTheChainReproducesARealRun:
    """If these numbers drift from what `run_screen` does, the preview is a lie."""

    def test_the_corpus_size_is_reported(self, report):
        assert report.corpus_n == 776

    def test_the_deterministic_chain_is_776_760_147(self, report):
        """Wave 13d's measured chain, reproduced through the preview."""
        eh, ih = _stage(report, "EH"), _stage(report, "IH")
        assert (eh.in_n, eh.out_n) == (776, 760)
        assert (ih.in_n, ih.out_n) == (760, 147)
        assert report.survivors_n == 147

    def test_it_agrees_with_run_screen_criterion_by_criterion(self, report,
                                                              harmonised, corpus):
        """The preview must not compute impacts its own way."""
        import threading
        cp, he = _cparser(), _import_plugin("03_harmoniser", "exporters")
        rn = _import_plugin("_common", "runner")
        header, rows = corpus
        text = he._criteria_csv_text(harmonised)
        survivors = list(rows)
        for stage_name in ("EH", "IH"):
            crits = cp._load_criteria_from_text(text, stage_name)
            parse = cp.ParseReport(header=header, rows=survivors, skipped=[])
            _full, out, _counts, impacts, _evals, _c = rn.run_screen(
                parse, crits, threading.Event(), stage=stage_name)
            for cid, imp in impacts.items():
                c = _crit(report, cid)
                assert c.removed_n == imp["failed"], cid
                assert c.missing_n == imp["missing"], cid
                assert c.unknown_n == imp["unknown"], cid
                assert c.met_n == imp["met"], cid
            survivors = out


class TestPerCriterionCountsAreStageRelative:
    """`stage_in_n`, never a running total."""

    def test_every_criterion_reports_the_records_that_reached_its_stage(self, report):
        for s in report.stages:
            for c in s.criteria:
                if c.evaluated:
                    assert c.stage_in_n == s.in_n, (
                        "%s reports %d in, but stage %s received %d"
                        % (c.criterion_id, c.stage_in_n, s.stage, s.in_n))

    def test_the_four_verdicts_account_for_every_record_in_the_stage(self, report):
        for s in report.stages:
            for c in s.criteria:
                if c.evaluated:
                    total = c.removed_n + c.missing_n + c.unknown_n + c.met_n
                    assert total == c.stage_in_n, (
                        "%s: %d+%d+%d+%d != %d" % (c.criterion_id, c.removed_n,
                                                   c.missing_n, c.unknown_n,
                                                   c.met_n, c.stage_in_n))

    def test_ic4_removes_611_of_the_760_that_reached_ih(self, report):
        c = _crit(report, "IC-4")
        assert (c.removed_n, c.stage_in_n) == (611, 760)

    def test_ec4_removes_nothing_and_has_126_records_with_no_venue(self, report):
        """Wave 13d's repair, and the case that motivated the whole feature."""
        c = _crit(report, "EC-4")
        assert (c.removed_n, c.missing_n, c.stage_in_n) == (0, 126, 776)


class TestTheDisplayCannotProduceAMisleadingTotal:
    """Six records fail both IC-3 and IC-4. 8 + 611 = 619, but IH removes 613."""

    def test_the_overlap_is_real_on_this_corpus(self, report):
        ih = _stage(report, "IH")
        naive = sum(c.removed_n for c in ih.criteria if c.evaluated)
        assert naive == 619
        assert ih.removed_n == 613
        assert ih.overlap_n == 6

    def test_the_stage_total_is_never_the_sum_of_its_criteria(self, report):
        for s in report.stages:
            naive = sum(c.removed_n for c in s.criteria if c.evaluated)
            assert s.removed_n == s.in_n - s.out_n, (
                "the stage total must come from the funnel, not from adding up rows")
            if s.overlap_n:
                assert s.removed_n != naive

    def test_a_criterion_carries_no_cumulative_field_to_misread(self, report):
        """The type must not offer a running total for a display to pick up."""
        c = _crit(report, "IC-4")
        for forbidden in ("running_total", "cumulative", "out_n", "remaining",
                          "records_left", "after_n"):
            assert not hasattr(c, forbidden), (
                "CriterionPreview.%s invites a sequential reading that is wrong"
                % forbidden)

    def test_the_rendered_body_states_the_overlap_instead_of_hiding_it(self, report):
        body = report.dialog.body
        assert "6 records" in body and "IC-3" in body and "IC-4" in body
        assert "do not add up" in body or "does not add up" in body

    def test_the_rendered_body_never_prints_the_naive_sum_as_a_total(self, report):
        """619 must not appear anywhere as if it meant something."""
        assert "619" not in report.dialog.body


class TestLlmRowsAreVisiblyNotEvaluated:
    """Four of the eight reference criteria are `llm`. Silence would misrepresent."""

    def test_all_four_llm_criteria_are_present(self, report):
        seen = {c.criterion_id for s in report.stages for c in s.criteria
                if not c.evaluated}
        assert seen == {"IC-1", "IC-5", "EC-2", "EC-3"}

    def test_they_are_marked_not_evaluated_rather_than_zero(self, report):
        for cid in ("IC-1", "EC-2", "EC-3"):
            c = _crit(report, cid)
            assert c.evaluated is False
            assert c.removed_n is None, (
                "a count of 0 would read as 'removes nothing', which is a "
                "different claim from 'was not run'")
            assert c.not_evaluated_reason

    def test_ic5_is_a_deterministic_operator_stranded_at_an_llm_stage(self, report):
        """F-65: `contains` at IL is never evaluated by anything, ever.

        This is a different problem for the reader from "the preview makes no model
        calls", and the two reasons must not collapse into one another: IC-1 will run
        when the user screens, IC-5 will not run then either.
        """
        stranded = _crit(report, "IC-5")
        plain_llm = _crit(report, "IC-1")
        assert stranded.evaluated is False and plain_llm.evaluated is False
        assert stranded.operator == "contains"
        assert "never run" in stranded.not_evaluated_reason, (
            "F-65 is permanent, not a limitation of this preview")
        assert "F-65" in stranded.not_evaluated_reason
        assert "never run" not in plain_llm.not_evaluated_reason, (
            "IC-1 WILL run when the user screens; only the preview skips it")
        assert stranded.not_evaluated_reason != plain_llm.not_evaluated_reason

    def test_the_body_distinguishes_the_two_kinds_of_not_evaluated(self, report):
        body = report.dialog.body
        assert "never run" in body
        assert "makes no model calls" in body

    def test_the_body_says_so_in_words(self, report):
        body = report.dialog.body
        for cid in ("IC-1", "IC-5", "EC-2", "EC-3"):
            assert cid in body
        assert "not evaluated" in body.lower()

    def test_a_disabled_llm_criterion_is_not_listed(self, corpus):
        """`_load_criteria_from_text` drops disabled rows; the LLM listing must too.

        Otherwise a rule the user switched off is reported as pending evaluation.
        """
        header, rows = corpus
        crits = [
            {"stage": "IL", "id": "IC-ON", "type": "include", "scope": "metadata",
             "label": "on", "operator": "llm", "target": "keywords", "what": ["x"],
             "threshold": "0.60", "enabled": True, "source_text": "x"},
            {"stage": "IL", "id": "IC-OFF", "type": "include", "scope": "metadata",
             "label": "off", "operator": "llm", "target": "keywords", "what": ["x"],
             "threshold": "0.60", "enabled": False, "source_text": "x"},
        ]
        rep = _preview().build_criteria_preview(crits, header, rows[:20])
        listed = {c.criterion_id for s in rep.stages for c in s.criteria}
        assert listed == {"IC-ON"}
        assert "IC-OFF" not in rep.dialog.body

    def test_a_disabled_deterministic_criterion_is_not_listed_either(self, corpus):
        """The same rule on the side the loader already enforces, so the two agree."""
        header, rows = corpus
        crits = [
            {"stage": "EH", "id": "EC-ON", "type": "exclude", "scope": "metadata",
             "label": "on", "operator": "equals", "target": "lang",
             "what": ["French"], "threshold": "", "enabled": True,
             "source_text": "x"},
            {"stage": "EH", "id": "EC-OFF", "type": "exclude", "scope": "metadata",
             "label": "off", "operator": "equals", "target": "lang",
             "what": ["English"], "threshold": "", "enabled": False,
             "source_text": "x"},
        ]
        rep = _preview().build_criteria_preview(crits, header, rows)
        listed = {c.criterion_id for s in rep.stages for c in s.criteria}
        assert listed == {"EC-ON"}, "a disabled rule must not be previewed"

    def test_llm_stages_do_not_contribute_to_the_funnel(self, report):
        assert [s.stage for s in report.stages if s.evaluated] == ["EH", "IH"]
        assert report.survivors_n == _stage(report, "IH").out_n


class TestNotableCriteriaAreFlagged:
    """Both extremes are alarming and neither was visible anywhere."""

    def test_a_criterion_that_removes_nothing_is_notable(self, report):
        kinds = {(n.criterion_id, n.kind) for n in report.notes}
        assert ("EC-4", "zero-removal") in kinds

    def test_a_criterion_that_removes_almost_everything_is_notable(self, report):
        kinds = {(n.criterion_id, n.kind) for n in report.notes}
        assert ("IC-4", "high-removal") in kinds

    def test_the_zero_removal_note_offers_the_reason_the_data_supports(self, report):
        note = [n for n in report.notes if n.kind == "zero-removal"][0]
        assert "126" in note.text, "the missing-venue count is the explanation"
        assert "may" in note.text.lower(), (
            "a criterion that removes nothing may be correct; the note must not "
            "assert a defect")

    def test_the_high_removal_note_gives_the_share_not_just_the_count(self, report):
        note = [n for n in report.notes if n.kind == "high-removal"][0]
        assert "611" in note.text, "the count"
        assert "760" in note.text, "out of how many -- the count alone is not a share"
        assert "80%" in note.text, (
            "the computed share, not merely a percent sign somewhere in the prose")

    def test_criteria_that_are_neither_are_not_flagged(self, report):
        flagged = {n.criterion_id for n in report.notes
                   if n.kind in ("zero-removal", "high-removal")}
        assert "EC-1" not in flagged and "IC-3" not in flagged

    def test_the_threshold_is_a_parameter_not_a_magic_number(self, harmonised, corpus):
        header, rows = corpus
        p = _preview()
        low = p.build_criteria_preview(harmonised, header, rows,
                                       high_removal_fraction=0.001)
        flagged = {n.criterion_id for n in low.notes if n.kind == "high-removal"}
        assert "IC-3" in flagged, "8 of 760 clears a 0.1% bar"


class TestUncomparableValuesAreVisible:
    """B-1: a `gte` against `2018-03` is UNKNOWN, so the filter does not apply."""

    def test_unknown_and_missing_are_reported_per_criterion(self, report):
        c = _crit(report, "IC-4")
        assert c.unknown_n == 0 and c.missing_n == 1

    def test_a_corpus_of_year_months_shows_the_criterion_applying_to_nothing(self):
        p = _preview()
        rows = [{"stage": "IH", "id": "IC-4", "type": "include", "scope": "metadata",
                 "label": "Published in 2018 or later.", "operator": "gte",
                 "target": "year", "what": ["2018"], "threshold": "",
                 "enabled": True, "source_text": "x"}]
        corpus_rows = [{"local_id": "A%03d" % i, "year": "2019-04"} for i in range(20)]
        rep = p.build_criteria_preview(rows, ["local_id", "year"], corpus_rows)
        c = _crit(rep, "IC-4")
        assert (c.removed_n, c.unknown_n) == (0, 20)
        assert ("IC-4", "uncomparable") in {(n.criterion_id, n.kind)
                                            for n in rep.notes}
        assert "20" in rep.dialog.body


class TestTheRemovedRecordsCanBeCheckedByHand:
    """`row_eval_lists` already carries these, so the model keeps them all.

    Truncation is a display decision and lives in the rendered body, not in the
    model -- a caller that wants to export every removed id should not have to
    re-run the screen to get them.
    """

    def test_every_removed_id_is_kept_for_a_small_removal(self, report):
        c = _crit(report, "EC-1")
        assert len(c.removed_ids) == 16
        assert "A380" in c.removed_ids and "A525" in c.removed_ids, (
            "the two Spanish records F-167's repair added")

    def test_every_removed_id_is_kept_for_a_large_removal_too(self, report):
        c = _crit(report, "IC-4")
        assert c.removed_n == 611
        assert len(c.removed_ids) == 611
        assert len(set(c.removed_ids)) == 611, "no duplicates"

    def test_the_body_caps_the_list_and_says_how_many_it_did_not_show(self, report):
        body = report.dialog.body
        assert "and 601 more" in body, (
            "611 removed, 10 shown -- the body must say what it withheld")

    def test_the_cap_is_a_parameter(self, harmonised, corpus):
        header, rows = corpus
        rep = _preview().build_criteria_preview(harmonised, header, rows,
                                                max_ids_shown=3)
        assert "and 608 more" in rep.dialog.body

    def test_a_zero_removal_criterion_lists_nothing(self, report):
        assert _crit(report, "EC-4").removed_ids == []

    def test_the_ids_are_the_records_run_screen_actually_removed(self, report):
        """Spot-checkable by hand, which is the point of listing them."""
        c = _crit(report, "IC-3")
        assert len(c.removed_ids) == 8
        both = set(c.removed_ids) & set(_crit(report, "IC-4").removed_ids)
        assert both == {"A376", "A382", "A385", "A646", "A770", "A776"}, (
            "the six records the overlap warning is about")


class TestItIsReadOnly:
    """No bundle, no cache, no file, no mutation the caller can observe."""

    def test_it_writes_no_file(self, harmonised, corpus):
        header, rows = corpus
        writes = []

        def hook(event, args):
            if event == "open" and len(args) > 1 and args[1] and any(
                    c in str(args[1]) for c in "wax+"):
                writes.append(str(args[0]))
            elif event in ("os.mkdir", "os.rename", "os.remove", "shutil.copyfile"):
                writes.append(event)

        sys.addaudithook(hook)
        n0 = len(writes)
        _preview().build_criteria_preview(harmonised, header, rows)
        assert writes[n0:] == [], "the preview touched the filesystem: %r" % (
            writes[n0:],)

    def test_it_does_not_mutate_the_criteria_rows(self, harmonised, corpus):
        import copy
        header, rows = corpus
        before = copy.deepcopy(harmonised)
        _preview().build_criteria_preview(harmonised, header, rows)
        assert harmonised == before

    def test_it_does_not_mutate_the_corpus_rows(self, harmonised, corpus):
        import copy
        header, rows = corpus
        before = copy.deepcopy(rows[:50])
        _preview().build_criteria_preview(harmonised, header, rows)
        assert rows[:50] == before

    def test_it_is_importable_without_tkinter(self):
        """The pure function must be reachable from a headless test."""
        mod = _preview()
        assert not any(n.startswith("tkinter") for n in dir(mod))


class TestTheLogLineAndDialogShape:
    """`_validate`'s contract, so the existing `_SHOW` dispatch works unchanged."""

    def test_the_dialog_kind_is_one_the_view_can_dispatch(self, report):
        assert report.dialog.kind in ("showinfo", "showwarning", "showerror")

    def test_the_log_line_names_the_chain(self, report):
        assert report.log_line == (
            "Preview: 776 records, EH 776->760, IH 760->147, 147 survive")

    def test_an_empty_criteria_table_is_handled_rather_than_crashing(self, corpus):
        header, rows = corpus
        rep = _preview().build_criteria_preview([], header, rows)
        assert rep.corpus_n == 776
        assert rep.survivors_n == 776
        assert rep.stages == []

    def test_an_empty_corpus_is_handled(self, harmonised):
        rep = _preview().build_criteria_preview(harmonised, ["local_id"], [])
        assert rep.corpus_n == 0
        assert rep.survivors_n == 0
