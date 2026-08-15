# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_wave15e_acceptance_freeze.py — the wave-15e acceptance experiment,
frozen and re-derived (the 14c/14d freeze pattern).

``docs/data/wave15e_acceptance_runs/`` holds the three adjudicated runs
(batch 5, batch-5 repeat, batch 1) of the frozen 14d corpus under the
wave-15e prompt/schema/gate. The register's settlement notes on F-195,
F-201 and F-197 cite these figures, so this file both pins the bytes
(SHA256SUMS bijection) and RE-DERIVES every headline number from them —
a citation that cannot drift from its evidence (F-159's lesson).

The predictions these runs were measured against were registered at the
design commit (`291a60f` §6), before the implementation existed.
"""
import csv
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

FROZEN = Path(__file__).parent.parent / "docs" / "data" / "wave15e_acceptance_runs"
RUNS = ("runJ_batch5", "runK_batch5", "runL_batch1")

#: The headline figures, as cited by the register and the wave doc.
INVALID_NONNULL_NOT_MEET = {"runJ_batch5": 0, "runK_batch5": 0,
                            "runL_batch1": 0}
NOT_MEET_TOTALS = {"runJ_batch5": 284, "runK_batch5": 284, "runL_batch1": 294}
NULL_QUOTED_NOT_MEET = {"runJ_batch5": 283, "runK_batch5": 283,
                        "runL_batch1": 294}
MEET_PAIRS = {"runJ_batch5": 10, "runK_batch5": 10, "runL_batch1": 0}
OUTCOME_DIST = {
    "runJ_batch5": {"PASS_CLEAN": 133, "PASS_FLAGGED": 9,
                    "EXCLUSION_SUPPRESSED": 5},
    "runK_batch5": {"PASS_CLEAN": 133, "PASS_FLAGGED": 9,
                    "EXCLUSION_SUPPRESSED": 5},
    "runL_batch1": {"PASS_CLEAN": 147},
}
OUTCOME_CHURN = 2            # runJ <-> runK records; frozen 14d was 24
DECISION_FLIPS = 0           # runJ <-> runK pairs; frozen floor was 10/294
QUOTE_VALID_FLIPS = 0        # runJ <-> runK pairs; frozen was 32/294
SUPPRESSED_MEETS = 5         # per batch-5 run: passed rule (a), flag-only
CALLS = {"runJ_batch5": 60, "runK_batch5": 60, "runL_batch1": 294}


def _sums():
    out = {}
    for line in (FROZEN / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(None, 1)
        out[name.strip()] = digest
    return out


@pytest.fixture(scope="module")
def data():
    loaded = {}
    for run in RUNS:
        path = FROZEN / f"{run}_EL_FULL.csv"
        rows = {}
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows[r["local_id"]] = (r, json.loads(r["el_evidence_json"]))
        loaded[run] = rows
    return loaded


class TestTheBytesAreFrozen:

    def test_sha256sums_is_a_bijection_with_the_data_files(self):
        sums = _sums()
        on_disk = {p.name for p in FROZEN.glob("run*")}
        assert set(sums) == on_disk
        for name, digest in sums.items():
            assert hashlib.sha256(
                (FROZEN / name).read_bytes()).hexdigest() == digest, name

    def test_every_data_file_is_attribute_pinned(self):
        root = FROZEN.parent.parent.parent
        for p in sorted(FROZEN.glob("run*")):
            if p.suffix not in (".csv", ".json"):
                continue
            out = subprocess.run(
                ["git", "check-attr", "text", "--",
                 p.relative_to(root).as_posix()],
                cwd=str(root),
                capture_output=True, text=True, check=True).stdout
            assert out.strip().endswith("text: unset"), out

    def test_the_two_batch5_reports_are_byte_identical(self):
        """runJ's and runK's run reports (counters + provenance) came out
        byte-identical — the same-configuration repeat reproduced every
        counter. Pinned because it is the strongest single fact about the
        v3 noise floor."""
        j = (FROZEN / "runJ_batch5_report.json").read_bytes()
        k = (FROZEN / "runK_batch5_report.json").read_bytes()
        assert j == k


class TestTheRunsAreWhatTheMetaSays:

    @pytest.mark.parametrize("run", RUNS)
    def test_provenance_and_counters(self, run):
        rep = json.loads((FROZEN / f"{run}_report.json").read_text(
            encoding="utf-8"))
        prov = rep["provenance"]
        assert prov["prompt_version"] == "EL_v3_nullquote"
        assert prov["model"] == "qwen2.5:7b"
        assert prov["endpoint"] == "http://localhost:11434/v1"
        assert prov["temperature"] == 0.0
        assert prov["trunc_chars"] == 1500
        assert rep["request_shape"] == "json_schema"
        assert rep["exclusion_policy"] == "flag_only"
        assert (rep["records"], rep["answered"], rep["no_answer"]) == \
            (294, 294, 0)
        assert rep["reasks_made"] == 0
        assert rep["calls_made"] == CALLS[run]
        assert "absence_suppressed" not in rep, (
            "exclude-type criteria only: no absence-removal is expressible "
            "at EL on this corpus, and the counter is presence-by-key"
        )


class TestTheHeadlineFiguresRederive:

    @pytest.mark.parametrize("run", RUNS)
    def test_the_not_meet_quote_states(self, data, run):
        """The F-195 mechanism: invalid non-null quotes on not_meet went
        to ZERO in all three runs (frozen comparators: runE 49/241,
        runF 100/294, runG 54/278, runH 62/281), because the honest
        answer — null — became expressible."""
        nm = invalid = null = 0
        for _, ev in data[run].values():
            for e in ev.values():
                if e["decision"] != "not_meet":
                    continue
                nm += 1
                if not e["quote"]:
                    null += 1
                elif not e["quote_valid"]:
                    invalid += 1
        assert nm == NOT_MEET_TOTALS[run]
        assert invalid == INVALID_NONNULL_NOT_MEET[run]
        assert null == NULL_QUOTED_NOT_MEET[run]

    @pytest.mark.parametrize("run", RUNS)
    def test_meet_pairs_and_the_base_rate_record(self, data, run):
        """14d's instrument, reused verbatim: A349 is the corpus's one
        maze-adjacent record and answered not_meet on both criteria in
        every run, so meets elsewhere are fabrications. 10/10/0 against
        the frozen 15/12/0 — did not rise; zero intercept holds."""
        meets = [(lid, c) for lid, (_, ev) in data[run].items()
                 for c, e in ev.items() if e["decision"] == "meet"]
        assert len(meets) == MEET_PAIRS[run]
        a349 = data[run]["A349"][1]
        assert a349["EC-2"]["decision"] == "not_meet"
        assert a349["EC-3"]["decision"] == "not_meet"

    def test_the_fabricated_set_is_stable_across_the_repeat(self, data):
        """New under v3: runJ and runK fabricate the SAME 10 (lid, cid)
        pairs (the frozen batch-5 pair shared 9 of 15/12)."""
        def meets(run):
            return {(lid, c) for lid, (_, ev) in data[run].items()
                    for c, e in ev.items() if e["decision"] == "meet"}
        assert meets("runJ_batch5") == meets("runK_batch5")

    @pytest.mark.parametrize("run", RUNS)
    def test_the_outcome_distributions(self, data, run):
        got = Counter(row["el_outcome"] for row, _ in data[run].values())
        assert dict(got) == OUTCOME_DIST[run]

    def test_the_suppressed_meets_passed_the_strict_gate(self, data):
        """Per batch-5 run: 5 of the 10 fabricated meets carried valid
        quotes of substance and were suppressed by flag-only; the other 5
        failed on quote validity. The substance floor fired uniquely on
        none in these runs — recorded so nobody reads the floor as the
        thing that caught them."""
        for run in ("runJ_batch5", "runK_batch5"):
            st = Counter(e["status"] for _, ev in data[run].values()
                         for e in ev.values() if e["decision"] == "meet")
            assert st["SUPPRESSED"] == SUPPRESSED_MEETS
            assert st["UNCERTAIN"] == 10 - SUPPRESSED_MEETS

    def test_the_same_config_churn(self, data):
        """The registered prediction: 24/147 -> <= ~13 with the
        quote_valid component zero. Measured: 2/147, both pure confidence
        churn; decision flips 0/294 and quote_valid flips 0/294 — the
        quote-noise instrument went run-invariant."""
        j, k = data["runJ_batch5"], data["runK_batch5"]
        churn = [lid for lid in j
                 if j[lid][0]["el_outcome"] != k[lid][0]["el_outcome"]]
        assert len(churn) == OUTCOME_CHURN
        dec = sum(1 for lid in j for c in ("EC-2", "EC-3")
                  if j[lid][1][c]["decision"] != k[lid][1][c]["decision"])
        qv = sum(1 for lid in j for c in ("EC-2", "EC-3")
                 if j[lid][1][c]["quote_valid"] != k[lid][1][c]["quote_valid"])
        assert dec == DECISION_FLIPS
        assert qv == QUOTE_VALID_FLIPS
        for lid in churn:
            for c in ("EC-2", "EC-3"):
                ej, ek = j[lid][1][c], k[lid][1][c]
                if ej["status"] == ek["status"]:
                    continue
                assert ej["decision"] == ek["decision"]
                assert ej["quote_valid"] == ek["quote_valid"]
                # what differs is the confidence, crossing the threshold
                thr = float(ej["threshold"])
                assert (float(ej["confidence"]) >= thr) != \
                    (float(ek["confidence"]) >= thr)

    def test_the_meta_file_states_the_derived_numbers(self):
        meta = (FROZEN / "wave15e_acceptance_runs.meta.txt").read_text(
            encoding="utf-8")
        for needle in ("0/284", "0/294", "100/294 -> 0/294", "10/294",
                       "2/147", "0/294 (frozen 32/294)", "133/9/5",
                       "147/0/0", "A349", "calls_made=60", "calls_made=294",
                       "0bd1604a", "f8115e4f"):
            assert needle in meta, needle
