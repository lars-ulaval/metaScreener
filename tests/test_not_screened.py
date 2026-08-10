
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_not_screened.py — F-34: a stage with zero enabled criteria reported
every record as a clean pass.

When a screening stage ended up with no enabled criteria it did not fail,
warn loudly, or stop. It assigned ``PASS_CLEAN`` to every record and
reported every record as a survivor. Measured on a bundle built from the
committed golden criteria table with the EL criteria removed::

    counts   : {'OUT': 0, 'PASS_CLEAN': 85, 'PASS_FLAGGED': 0}
    survivors: 85 of 85 records

``PASS_CLEAN`` is the *stronger* of the two survivor labels — it means
"every criterion was met" — which is precisely what did not happen. A stage
that did no work was indistinguishable from a stage that ran correctly and
excluded nothing, and it reported itself using the label that most strongly
asserts the opposite.

Raised Medium → High because F-04 opened a second and more likely route in:
a criterion whose ``type`` cell is blank is now rejected rather than run
with a guessed polarity, so one malformed cell can empty a stage. On the
demonstration corpus EL runs on a single criterion after EC-3, so blanking
one cell takes EL from a wrong answer to no answer that looks like a right
one.

The contract: a no-op stage must be visibly distinct from a stage that
screened everything and excluded nothing —
  1. a distinct outcome, not PASS_CLEAN, in its own count bucket;
  2. reaching the run summary, not only a warning box;
  3. gating the run or the export;
  4. recorded in the manifest, so a reviewer reproducing the pipeline can
     tell without re-running the GUI.
"""
import json
import threading
import zipfile

import pytest

from conftest import get_el, get_il

from plugins._common.bundle import (
    BundleInfo,
    NOT_SCREENED,
    _export_confirm_reason,
    _export_next_bundle_zip,
    _run_summary_counts_text,
)
from plugins._common.parser import CriteriaLoadReport, Criterion, ParseReport
from plugins._common.runner import run_screen


def _rows(n):
    return [{"local_id": f"A{i:03d}", "title": f"Title {i}",
             "abstract": f"Abstract {i}", "keywords": "k"} for i in range(n)]


def _parse(n):
    return ParseReport(header=["local_id", "title", "abstract", "keywords"],
                       rows=_rows(n), skipped=[])


def _eh_crit(enabled=True):
    return Criterion(
        stage="EH", cid="EC-1", ctype="exclude", scope="", label="EC-1",
        operator="contains", targets=["title"], what_raw="Title",
        what_list=["Title"], threshold=None, enabled=enabled, source_text="x",
    )


# ---------------------------------------------------------------------------
# 1. a distinct outcome, in its own bucket
# ---------------------------------------------------------------------------

class TestEHIHZeroCriteria:

    @pytest.mark.parametrize("stage", ["EH", "IH"])
    def test_outcome_is_not_pass_clean(self, stage):
        full, _surv, counts, _imp, _ev, _c = run_screen(
            _parse(85), CriteriaLoadReport(criteria=[], warnings=[]),
            threading.Event(), None, stage=stage)

        sl = stage.lower()
        outcomes = {r[f"{sl}_outcome"] for r in full}
        assert outcomes == {NOT_SCREENED}, (
            f"F-34: a {stage} stage with no criteria labelled every record "
            f"{outcomes}. PASS_CLEAN is the stronger of the two survivor "
            f"labels — it asserts every criterion was met, which is exactly "
            f"what did not happen."
        )

    @pytest.mark.parametrize("stage", ["EH", "IH"])
    def test_counted_in_its_own_bucket(self, stage):
        _full, _surv, counts, _imp, _ev, _c = run_screen(
            _parse(85), CriteriaLoadReport(criteria=[], warnings=[]),
            threading.Event(), None, stage=stage)

        assert counts[NOT_SCREENED] == 85
        assert counts["PASS_CLEAN"] == 0, (
            "F-34: NOT_SCREENED must not be folded into either survivor "
            "category. The counts label is what the user reads after a run."
        )
        assert counts.get("PASS_FLAGGED", 0) == 0
        assert counts["OUT"] == 0

    @pytest.mark.parametrize("stage", ["EH", "IH"])
    def test_records_still_flow_to_the_next_stage(self, stage):
        """Not screening them is not a reason to drop them — emptying the
        corpus would be a worse failure than the one being fixed. They pass
        through, they are just no longer described as having passed."""
        _full, surv, _counts, _imp, _ev, _c = run_screen(
            _parse(85), CriteriaLoadReport(criteria=[], warnings=[]),
            threading.Event(), None, stage=stage)
        assert len(surv) == 85

    @pytest.mark.parametrize("stage", ["EH", "IH"])
    def test_reason_summary_says_the_stage_did_nothing(self, stage):
        full, *_ = run_screen(
            _parse(3), CriteriaLoadReport(criteria=[], warnings=[]),
            threading.Event(), None, stage=stage)
        reason = full[0][f"{stage.lower()}_reason_summary"]
        assert NOT_SCREENED in reason
        assert "PASS_CLEAN" not in reason

    @pytest.mark.parametrize("stage", ["EH", "IH"])
    def test_all_criteria_disabled_is_the_same_case(self, stage):
        """A stage whose criteria all exist but are switched off has screened
        nothing just the same."""
        report = CriteriaLoadReport(criteria=[_eh_crit(enabled=False)],
                                    warnings=[])
        full, _surv, counts, _imp, _ev, _c = run_screen(
            _parse(10), report, threading.Event(), None, stage=stage)
        assert counts[NOT_SCREENED] == 10
        assert {r[f"{stage.lower()}_outcome"] for r in full} == {NOT_SCREENED}

    @pytest.mark.parametrize("stage", ["EH", "IH"])
    def test_a_normal_run_is_unaffected(self, stage):
        _full, _surv, counts, _imp, _ev, _c = run_screen(
            _parse(10), CriteriaLoadReport(criteria=[_eh_crit()], warnings=[]),
            threading.Event(), None, stage=stage)
        assert counts[NOT_SCREENED] == 0


class TestELILZeroCriteria:

    @staticmethod
    def _run(mod, stage, crits):
        parse = mod.ParseReport(
            header=["local_id", "title", "abstract", "keywords"],
            rows=_rows(85), skipped=[])
        report = mod.CriteriaLoadReport(criteria=crits, warnings=[])
        run = mod.run_el_screen if stage == "EL" else mod.run_il_screen
        return run(parse, report, model="gpt-4o-mini", trunc_chars=1500,
                   batch_size=5, use_cache=False, cache_in={},
                   cancel_event=threading.Event())

    @pytest.mark.parametrize("getter,stage", [(get_el, "EL"), (get_il, "IL")],
                             ids=["el", "il"])
    def test_the_measured_defect(self, getter, stage):
        """The exact shape recorded in the finding: 85 records, no criteria,
        counts {'OUT': 0, 'PASS_CLEAN': 85, ...}, survivors 85 of 85."""
        mod = getter()
        (full, surv, counts, _imp, _ev, _cache, _c,
         _report) = self._run(mod, stage, [])
        sl = stage.lower()

        assert counts["PASS_CLEAN"] == 0, (
            f"F-34: {stage} with zero criteria still reports "
            f"PASS_CLEAN: {counts['PASS_CLEAN']} — 'every criterion was met' "
            f"for a stage that evaluated none."
        )
        assert counts[NOT_SCREENED] == 85
        assert {r[f"{sl}_outcome"] for r in full} == {NOT_SCREENED}
        assert len(surv) == 85  # they still pass through

    @pytest.mark.parametrize("getter,stage", [(get_el, "EL"), (get_il, "IL")],
                             ids=["el", "il"])
    def test_not_screened_is_in_the_outcomes_tuple(self, getter, stage):
        mod = getter()
        assert NOT_SCREENED in mod.OUTCOMES

    @pytest.mark.parametrize("getter,stage", [(get_el, "EL"), (get_il, "IL")],
                             ids=["el", "il"])
    def test_the_other_survivor_label_is_untouched(self, getter, stage):
        """IL uses REVIEW where EL uses PASS_FLAGGED; adding a literal must
        not disturb either."""
        mod = getter()
        expected = "PASS_FLAGGED" if stage == "EL" else "REVIEW"
        assert expected in mod.OUTCOMES


# ---------------------------------------------------------------------------
# 2. it has to reach the run summary
# ---------------------------------------------------------------------------

class TestRunSummary:
    """The counts label and the survivors tab are what the user reads after a
    run. A warning in a read-only box in the left pane loses to them."""

    def test_summary_leads_with_not_screened(self):
        text = _run_summary_counts_text(
            {"OUT": 0, "PASS_CLEAN": 0, "PASS_FLAGGED": 0, NOT_SCREENED: 85},
            stage="EL", total_rows=85)
        assert NOT_SCREENED in text
        assert "85" in text
        assert "no enabled criteria" in text.lower()
        assert "nothing was screened" in text.lower()

    def test_summary_does_not_claim_survivors_for_a_no_op_stage(self):
        text = _run_summary_counts_text(
            {"OUT": 0, "PASS_CLEAN": 0, "PASS_FLAGGED": 0, NOT_SCREENED: 85},
            stage="EL", total_rows=85)
        assert "survivors: 85 of 85" not in text.lower()

    def test_a_normal_run_reads_normally(self):
        text = _run_summary_counts_text(
            {"OUT": 5, "PASS_CLEAN": 70, "PASS_FLAGGED": 10, NOT_SCREENED: 0},
            stage="EL", total_rows=85)
        assert NOT_SCREENED not in text
        assert "70" in text and "5" in text


# ---------------------------------------------------------------------------
# 3. gating
# ---------------------------------------------------------------------------

class TestExportGate:

    def test_a_no_op_stage_needs_explicit_acknowledgement(self):
        reason = _export_confirm_reason(not_screened=True, stage="EL")
        assert reason is not None
        assert "EL" in reason
        assert "no" in reason.lower() and "criteri" in reason.lower()

    def test_a_normal_run_needs_no_acknowledgement(self):
        assert _export_confirm_reason(not_screened=False, stage="EL") is None


# ---------------------------------------------------------------------------
# 4. it has to be in the manifest
# ---------------------------------------------------------------------------

def _seed(tmp_path):
    zp = tmp_path / "in.zip"
    manifest = {"pipeline": {"stages": {}, "history": []}, "sha256": {}}
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("data/current.csv", "local_id,title\nA001,x\n")
    return BundleInfo(zip_path=str(zp), root="", manifest=manifest, members=[])


def _history(zip_path):
    with zipfile.ZipFile(zip_path, "r") as zf:
        return json.loads(zf.read("manifest.json"))["pipeline"]


class TestManifestRecordsIt:

    def test_no_op_stage_is_recorded(self, tmp_path):
        out = tmp_path / "out.zip"
        _export_next_bundle_zip(
            str(out), _seed(tmp_path), "data/current.csv", "criteria/c.csv",
            None, ["local_id", "title"], [{"local_id": "A001", "title": "x"}],
            [{"local_id": "A001", "title": "x"}], [],
            {"OUT": 0, NOT_SCREENED: 1}, stage="EH", not_screened=True)

        pipeline = _history(out)
        assert pipeline["history"][-1]["not_screened"] is True, (
            "F-34: a downstream reader of the bundle — including a reviewer "
            "reproducing the pipeline — must be able to tell that a stage was "
            "a no-op without re-running the GUI."
        )
        assert pipeline["stages"]["EH"] != "done"

    def test_a_normal_stage_is_marked_done(self, tmp_path):
        out = tmp_path / "out.zip"
        _export_next_bundle_zip(
            str(out), _seed(tmp_path), "data/current.csv", "criteria/c.csv",
            None, ["local_id", "title"], [{"local_id": "A001", "title": "x"}],
            [{"local_id": "A001", "title": "x"}], [], {"OUT": 0}, stage="EH")

        pipeline = _history(out)
        assert pipeline["history"][-1]["not_screened"] is False
        assert pipeline["stages"]["EH"] == "done"


class TestELILManifestRecordsIt:
    """EL/IL wrote no pipeline.history entry at all before — only a
    stages[STAGE] = "done" marker, which for a stage that evaluated no
    criteria is the manifest repeating the run summary's false claim."""

    @staticmethod
    def _export(tmp_path, mod, stage, not_screened):
        from plugins._common.bundle import _write_llm_stage_bundle
        zp = tmp_path / f"{stage}_in.zip"
        manifest = {"pipeline": {"stages": {}, "history": []}, "sha256": {}}
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("data/current.csv",
                        "local_id,title,abstract,keywords\nA001,T,A,K\n")
            zf.writestr("criteria/criteria_harmonized.csv",
                        "stage,id,type,scope,label,operator,target,what,threshold,enabled,source_text\n")
        bundle = mod._load_bundle(str(zp))
        out = tmp_path / f"{stage}_out.zip"
        counts = ({NOT_SCREENED: 1, "OUT": 0, "PASS_CLEAN": 0} if not_screened
                  else {"OUT": 0, "PASS_CLEAN": 1, NOT_SCREENED: 0})
        with zipfile.ZipFile(bundle.zip_path, "r") as zf_in:
            _write_llm_stage_bundle(
                str(out), zf_in, root=bundle.root, manifest=dict(bundle.manifest),
                stage=stage, reports_dir_rel="reports",
                cache_rel=f"cache/{stage}_cache.jsonl",
                parse_header=["local_id", "title"],
                survivors=[{"local_id": "A001", "title": "T"}],
                full_rows=[{"local_id": "A001", "title": "T"}],
                full_header=["local_id", "title"], skipped=[],
                counts=counts, not_screened=not_screened)
        with zipfile.ZipFile(out, "r") as zf:
            return json.loads(zf.read("manifest.json"))["pipeline"]

    @pytest.mark.parametrize("getter,stage", [(get_el, "EL"), (get_il, "IL")],
                             ids=["el", "il"])
    def test_no_op_stage_is_recorded(self, tmp_path, getter, stage):
        pipeline = self._export(tmp_path, getter(), stage, True)
        assert pipeline["history"][-1]["not_screened"] is True
        assert pipeline["history"][-1]["counts"][NOT_SCREENED] == 1
        assert pipeline["stages"][stage] == "not_screened"

    @pytest.mark.parametrize("getter,stage", [(get_el, "EL"), (get_il, "IL")],
                             ids=["el", "il"])
    def test_a_normal_stage_is_marked_done(self, tmp_path, getter, stage):
        pipeline = self._export(tmp_path, getter(), stage, False)
        assert pipeline["history"][-1]["not_screened"] is False
        assert pipeline["stages"][stage] == "done"


# ---------------------------------------------------------------------------
# the F-04 route in, end to end
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("getter,stage", [(get_el, "EL"), (get_il, "IL")],
                         ids=["el", "il"])
def test_one_blank_type_cell_cannot_silently_empty_a_stage(getter, stage):
    """F-04 rejects a criterion whose polarity is not stated. That is right,
    but it means one malformed cell can empty a stage — which is why F-34 was
    escalated. Blanking the type cell of the only criterion must produce a
    visible no-op, not a clean pass."""
    mod = getter()
    cid = "EC-1" if stage == "EL" else "IC-1"
    csv_text = (
        "stage,id,type,scope,label,operator,target,what,threshold,enabled,source_text\n"
        f"{stage},{cid},,metadata,L,contains,title,Title,0.6,1,src\n"
    )
    report = mod._parse_criteria_harmonized_csv(csv_text, stage_filter=stage)
    assert [c for c in report.criteria if c.enabled] == [], (
        "precondition: F-04 should have rejected the blank-polarity row"
    )

    parse = mod.ParseReport(
        header=["local_id", "title", "abstract", "keywords"],
        rows=_rows(85), skipped=[])
    run = mod.run_el_screen if stage == "EL" else mod.run_il_screen
    (_full, _surv, counts, _imp, _ev, _cache, _c, _report) = run(
        parse, report, model="gpt-4o-mini", trunc_chars=1500, batch_size=5,
        use_cache=False, cache_in={}, cancel_event=threading.Event())

    assert counts[NOT_SCREENED] == 85
    assert counts["PASS_CLEAN"] == 0, (
        "F-34 + F-04: one blank type cell took the stage from a wrong answer "
        "to no answer that looks like a right one."
    )
