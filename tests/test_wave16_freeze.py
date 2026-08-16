# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_wave16_freeze.py — the wave-16b criteria-diversity live runs, frozen
and re-derived (the 14c/14d/15e freeze pattern).

``docs/data/wave16_live_runs/`` holds eight arms screened live against the
local ``qwen2.5:7b`` at batch 5, cache off, plus the preserved artefacts of
one aborted attempt. The wave-16b/16c documents and the register rows filed
at wave 16c cite these figures, so this file both pins the bytes
(SHA256SUMS bijection) and RE-DERIVES every headline number from them —
a citation that cannot drift from its evidence (F-159's lesson).

Nothing here is asserted from memory: every constant below is a *claim*,
and each test recomputes the quantity from the committed artefacts before
comparing. Perturb any cited byte and the arithmetic, not just a digest,
goes red.

The predictions these runs were measured against were registered at the
wave-16a design commit (`2ed4710` §7), before any call was made.
"""
import csv
import hashlib
import json
import math
import subprocess
from collections import Counter
from pathlib import Path

import pytest

FROZEN = Path(__file__).parent.parent / "docs" / "data" / "wave16_live_runs"
FROZEN_15E = Path(__file__).parent.parent / "docs" / "data" / "wave15e_acceptance_runs"
ABORTED = FROZEN / "aborted_attempt1"

#: (arm, stages) in run order, with the declared fault-ceiling and the
#: no-re-ask base. The ceiling is 2 x base by construction (wave 16b: a
#: declared budget is a fault-ceiling, not a spend prediction).
ARMS = (
    ("arm0_baseline", ("EL", "IL"), 30, 15),
    ("g1_paraphrase", ("EL", "IL"), 30, 15),
    ("g4_edge_shapes", ("EL", "IL"), 24, 12),
    ("g5_adversarial", ("EL", "IL"), 60, 30),
    ("g3_stage_stress", ("EL", "IL"), 88, 44),
    ("s1a_wording_el", ("EL",), 120, 60),
    ("s1b_polarity_il", ("IL",), 120, 60),
    ("g2_polarity", ("EL", "IL"), 176, 88),
)
BATCH_SIZE = 5
TOTAL_BASE = 324
TOTAL_SPENT = 325          # base + the single arm0 IL re-ask
TOTAL_CEILING = 648
SUNK_CALLS = 15            # the aborted first attempt, off-ledger
REASKS_TOTAL = 1

#: s1a (g1's paraphrased EC-2/EC-3 rows) against the frozen wave-15e runJ,
#: identity map: same corpus, same template, same settings — wording is the
#: only difference.
S1A_PAIRS = 294
S1A_AGREEMENT = 283
S1A_DECISION_FLIPS = 11
S1A_QUOTE_VALID_FLIPS = 9
RUNJ_MEETS = 10
S1A_MEETS = 17
S1A_RUNJ_OVERLAP = (
    ("A247", "EC-2"), ("A307", "EC-2"), ("A310", "EC-2"), ("A373", "EC-2"),
    ("A452", "EC-2"), ("A473", "EC-2"), ("A499", "EC-2"), ("A583", "EC-2"),
)

#: The F-195 quote invariant across every live pair of the wave.
NOT_MEET_TOTAL = 1360
NOT_MEET_NULL_QUOTED = 1348
NOT_MEET_EXCEPTIONS = 12

#: The free noise pair: the aborted attempt vs the arm0 rerun, same
#: configuration, on the pairs both runs answered.
NOISE_PAIRS = 64           # 44 EL + 20 IL
NOISE_EL_PAIRS = 44
NOISE_IL_PAIRS = 20

#: IL wording sensitivity: arm0's IC-1 vs g1's paraphrase of it.
IL_RECORDS = 22
IL_OUTCOME_CHANGES = 5
IL_REVIEW_BEFORE = 11
IL_REVIEW_AFTER = 16
EL_PAIRS_ARM0_G1 = 44
EL_DECISION_FLIPS_ARM0_G1 = 1


# ---------------------------------------------------------------------------
# loading helpers — every one reads the committed bytes
# ---------------------------------------------------------------------------

def _sums(root=FROZEN):
    out = {}
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(None, 1)
        out[name.strip().lstrip("*")] = digest
    return out


def _load_full(path, stage):
    """(evidence by (local_id, cid), outcome by local_id) from a FULL table."""
    pfx = stage.lower()
    ev, outcome = {}, {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cell = r.get(f"{pfx}_evidence_json") or ""
            for cid, e in (json.loads(cell) if cell else {}).items():
                ev[(r["local_id"], cid)] = e
            outcome[r["local_id"]] = r[f"{pfx}_outcome"]
    return ev, outcome


@pytest.fixture(scope="module")
def summaries():
    out = {}
    for arm, stages, _c, _b in ARMS:
        for st in stages:
            out[(arm, st)] = json.loads(
                (FROZEN / f"{arm}_{st}_summary.json").read_text(encoding="utf-8"))
    return out


@pytest.fixture(scope="module")
def manifests():
    return {arm: json.loads(
        (FROZEN / f"{arm}_live_manifest.json").read_text(encoding="utf-8"))
        for arm, _s, _c, _b in ARMS}


class TestTheBytesAreFrozen:

    def test_sha256sums_is_a_bijection_with_the_artefacts(self):
        sums = _sums()
        on_disk = {
            p.relative_to(FROZEN).as_posix()
            for p in FROZEN.rglob("*")
            if p.is_file() and p.name != "SHA256SUMS"
        }
        assert set(sums) == on_disk, (
            f"only in SHA256SUMS: {sorted(set(sums) - on_disk)}; "
            f"only on disk: {sorted(on_disk - set(sums))}")
        for name, digest in sums.items():
            assert hashlib.sha256(
                (FROZEN / name).read_bytes()).hexdigest() == digest, name

    def test_every_evidence_file_is_attribute_pinned(self):
        """Line-ending rewrites would break the digests above and look like
        tampering. Checked with `git check-attr`, never by eye.

        Wave 16d made this stricter, and the reason is worth keeping: wave
        16b exempted the README and SHA256SUMS here on the grounds that they
        are prose and mechanism rather than evidence — while listing both in
        SHA256SUMS. A recorded digest is a promise about bytes, so the
        exemption was incoherent, and the next Windows checkout rewrote the
        README and broke its digest. **Everything in a frozen directory is
        binary-pinned now, without exception.**"""
        root = FROZEN.parent.parent.parent
        paths = [p for p in sorted(FROZEN.rglob("*")) if p.is_file()]
        assert paths
        for p in paths:
            rel = p.relative_to(root).as_posix()
            out = subprocess.run(
                ["git", "check-attr", "text", "binary", "--", rel],
                cwd=str(root), capture_output=True, text=True,
                check=True).stdout
            assert out.count("text: unset") == 1, out
            assert "binary: set" in out, out

    def test_the_aborted_attempt_is_preserved_not_deleted(self):
        assert (ABORTED / "README.md").is_file()
        for stage in ("EL", "IL"):
            assert (ABORTED / f"arm0_baseline_{stage}_FULL.csv").is_file()
        sums = _sums()
        assert any(n.startswith("aborted_attempt1/") for n in sums)


class TestTheRunsAreWhatTheMetaSays:

    @pytest.mark.parametrize("arm,stage", [(a, s) for a, ss, _c, _b in ARMS
                                           for s in ss])
    def test_provenance_and_shape(self, arm, stage, summaries):
        s = summaries[(arm, stage)]
        prov = s["provenance"]
        assert prov["model"] == "qwen2.5:7b"
        assert prov["endpoint"] == "http://localhost:11434/v1"
        assert prov["temperature"] == 0.0
        assert prov["trunc_chars"] == 1500
        assert prov["batch_size"] == BATCH_SIZE
        assert prov["context_window"] == 4096
        assert prov["prompt_version"] == f"{stage}_v3_nullquote"
        assert s["request_shape"] == "json_schema", (
            "no F-107 unconstrained fallback fired in this wave")
        assert s["exclusion_policy"] == "flag_only"
        assert s["no_answer"] == 0
        assert s["answered"] == s["records"]

    @pytest.mark.parametrize("arm,stage", [(a, s) for a, ss, _c, _b in ARMS
                                           for s in ss])
    def test_no_record_was_removed(self, arm, stage, summaries):
        """The wave's Critical-shaped invariant: under flag-only plus rule
        (c), EL and IL may flag and suppress but never remove."""
        assert summaries[(arm, stage)]["counts"]["OUT"] == 0

    def test_every_stage_row_is_covered(self, summaries):
        assert len(summaries) == 14


class TestTheCallArithmeticReconciles:

    @pytest.mark.parametrize("arm,stages,ceiling,base", ARMS)
    def test_base_calls_are_the_ceiling_formula(self, arm, stages, ceiling,
                                                base, summaries):
        derived = 0
        for st in stages:
            s = summaries[(arm, st)]
            per_stage = math.ceil(s["records_in"] / BATCH_SIZE) * s["llm_criteria"]
            assert s["base_calls_no_reask"] == per_stage
            derived += per_stage
        assert derived == base
        assert ceiling == 2 * base, (
            "the declared budget is a fault-ceiling at 2 x base, which is the "
            "clean-path maximum: one re-ask per batch (llm_client.py:1734-1743)")

    @pytest.mark.parametrize("arm,stages,ceiling,base", ARMS)
    def test_spend_reconciles_with_reasks(self, arm, stages, ceiling, base,
                                          summaries, manifests):
        spent = manifests[arm]["calls_made_total"]
        reasks = sum(summaries[(arm, st)]["reasks_made"] for st in stages)
        assert spent == base + reasks, (
            f"{arm}: spent {spent} != base {base} + re-asks {reasks}")
        assert spent <= ceiling
        assert not manifests[arm]["anomaly_stops"]

    def test_the_ledger_totals_reconcile(self, summaries, manifests):
        base = sum(b for _a, _s, _c, b in ARMS)
        ceiling = sum(c for _a, _s, c, _b in ARMS)
        spent = sum(m["calls_made_total"] for m in manifests.values())
        reasks = sum(s["reasks_made"] for s in summaries.values())
        assert (base, ceiling, spent, reasks) == (
            TOTAL_BASE, TOTAL_CEILING, TOTAL_SPENT, REASKS_TOTAL)
        assert spent == base + reasks
        # The ledger CSV must agree with the artefacts it summarises.
        rows = {r["arm"]: r for r in csv.DictReader(
            open(FROZEN / "ledger.csv", encoding="utf-8"))}
        assert int(rows["TOTAL (in-ledger)"]["actual_spent"]) == spent
        assert int(rows["GRAND TOTAL (network calls)"]["actual_spent"]) == \
            spent + SUNK_CALLS

    def test_the_single_reask_is_arm0_il(self, summaries):
        with_reasks = {k: s["reasks_made"] for k, s in summaries.items()
                       if s["reasks_made"]}
        assert with_reasks == {("arm0_baseline", "IL"): 1}


class TestTheQuoteInvariantRederives:

    @pytest.fixture(scope="class")
    def not_meet(self):
        null_q, exceptions = 0, []
        for arm, stages, _c, _b in ARMS:
            for st in stages:
                ev, _o = _load_full(FROZEN / f"{arm}_{st}_FULL.csv", st)
                for (lid, cid), e in ev.items():
                    if e.get("decision") != "not_meet":
                        continue
                    if e.get("quote") in (None, ""):
                        null_q += 1
                    else:
                        exceptions.append((arm, st, lid, cid, e))
        return null_q, exceptions

    def test_null_quoted_not_meet_counts(self, not_meet):
        null_q, exceptions = not_meet
        assert null_q == NOT_MEET_NULL_QUOTED
        assert len(exceptions) == NOT_MEET_EXCEPTIONS
        assert null_q + len(exceptions) == NOT_MEET_TOTAL

    def test_every_exception_carries_a_real_substring(self, not_meet):
        """F-195's fabrication mechanism stayed shut: the twelve non-null
        quotes are genuine substrings, not manufactured evidence."""
        _n, exceptions = not_meet
        assert all(e["quote_valid"] is True for *_h, e in exceptions)

    def test_the_exceptions_cluster_by_content(self, not_meet):
        """They are not scattered: one content-poor record and one criterion
        carry five each — the F-201 content-clustering signature."""
        _n, exceptions = not_meet
        by_record = Counter(lid for _a, _s, lid, _c, _e in exceptions)
        by_criterion = Counter(cid for _a, _s, _l, cid, _e in exceptions)
        assert by_record.most_common(1)[0] == ("A078", 5)
        assert by_criterion.most_common(1)[0] == ("EC-28", 5)


class TestS1AAgainstTheFrozenRunJ:
    """Wording is the only difference: same 147 records, same
    EL_v3_nullquote template, same model/batch/temperature/truncation."""

    @pytest.fixture(scope="class")
    def pair(self):
        runj, _o1 = _load_full(FROZEN_15E / "runJ_batch5_EL_FULL.csv", "EL")
        s1a, _o2 = _load_full(FROZEN / "s1a_wording_el_EL_FULL.csv", "EL")
        return runj, s1a

    def test_decision_agreement(self, pair):
        runj, s1a = pair
        common = sorted(set(runj) & set(s1a))
        assert len(common) == S1A_PAIRS
        agree = [k for k in common
                 if runj[k]["decision"] == s1a[k]["decision"]]
        assert len(agree) == S1A_AGREEMENT
        assert len(common) - len(agree) == S1A_DECISION_FLIPS

    def test_quote_valid_flips(self, pair):
        runj, s1a = pair
        common = sorted(set(runj) & set(s1a))
        flips = [k for k in common
                 if bool(runj[k]["quote_valid"]) != bool(s1a[k]["quote_valid"])]
        assert len(flips) == S1A_QUOTE_VALID_FLIPS

    def test_meets_and_the_surviving_overlap(self, pair):
        runj, s1a = pair
        runj_meets = {k for k, v in runj.items() if v["decision"] == "meet"}
        s1a_meets = {k for k, v in s1a.items() if v["decision"] == "meet"}
        assert len(runj_meets) == RUNJ_MEETS
        assert len(s1a_meets) == S1A_MEETS
        assert tuple(sorted(runj_meets & s1a_meets)) == S1A_RUNJ_OVERLAP
        assert len(runj_meets - s1a_meets) == RUNJ_MEETS - len(S1A_RUNJ_OVERLAP)


class TestTheFreeNoisePair:
    """The aborted attempt and the rerun are the same configuration, cache
    off, temperature 0. Their agreement is what makes every cross-arm
    difference in this wave signal rather than noise."""

    @pytest.fixture(scope="class")
    def both(self):
        out = {}
        for stage in ("EL", "IL"):
            a, _ao = _load_full(ABORTED / f"arm0_baseline_{stage}_FULL.csv", stage)
            b, _bo = _load_full(FROZEN / f"arm0_baseline_{stage}_FULL.csv", stage)
            answered = [k for k in (set(a) & set(b))
                        if a[k].get("used") and b[k].get("used")]
            out[stage] = (a, b, sorted(answered))
        return out

    def test_the_comparable_population(self, both):
        assert len(both["EL"][2]) == NOISE_EL_PAIRS
        assert len(both["IL"][2]) == NOISE_IL_PAIRS
        assert sum(len(v[2]) for v in both.values()) == NOISE_PAIRS

    @pytest.mark.parametrize("axis", ["decision", "quote_valid", "confidence",
                                      "status"])
    def test_zero_movement_on_every_axis(self, both, axis):
        moved = []
        for stage, (a, b, keys) in both.items():
            for k in keys:
                if a[k].get(axis) != b[k].get(axis):
                    moved.append((stage, k, a[k].get(axis), b[k].get(axis)))
        assert moved == [], f"{axis} moved: {moved}"


class TestILWordingSensitivity:
    """The wave's most consequential measurement: paraphrasing one inclusion
    criterion, with corpus, model, settings and intent unchanged, moved five
    records out of the clean pile and into the review pile."""

    @pytest.fixture(scope="class")
    def il(self):
        a_ev, a_out = _load_full(FROZEN / "arm0_baseline_IL_FULL.csv", "IL")
        g_ev, g_out = _load_full(FROZEN / "g1_paraphrase_IL_FULL.csv", "IL")
        return a_ev, a_out, g_ev, g_out

    def test_five_records_changed_outcome_all_one_way(self, il):
        a_ev, a_out, g_ev, g_out = il
        common = sorted(set(a_out) & set(g_out))
        assert len(common) == IL_RECORDS
        changed = [i for i in common if a_out[i] != g_out[i]]
        assert len(changed) == IL_OUTCOME_CHANGES
        # every change is the same direction, and it is the harmful one
        for i in changed:
            assert a_out[i] == "PASS_CLEAN"
            assert g_out[i] == "EXCLUSION_SUPPRESSED"
            assert a_ev[(i, "IC-1")]["decision"] == "meet"
            assert g_ev[(i, "IC-1")]["decision"] == "not_meet"

    def test_the_review_pile_grew(self, il):
        _ae, a_out, _ge, g_out = il
        before = Counter(a_out.values())["EXCLUSION_SUPPRESSED"]
        after = Counter(g_out.values())["EXCLUSION_SUPPRESSED"]
        assert (before, after) == (IL_REVIEW_BEFORE, IL_REVIEW_AFTER)
        assert after > before

    def test_the_same_paraphrase_barely_moved_el(self):
        """The asymmetry is the point: the deterministic half and the EL
        half were nearly untouched by the same rewording."""
        a_ev, _a = _load_full(FROZEN / "arm0_baseline_EL_FULL.csv", "EL")
        g_ev, _g = _load_full(FROZEN / "g1_paraphrase_EL_FULL.csv", "EL")
        common = sorted(set(a_ev) & set(g_ev))
        assert len(common) == EL_PAIRS_ARM0_G1
        flips = [k for k in common
                 if a_ev[k]["decision"] != g_ev[k]["decision"]]
        assert len(flips) == EL_DECISION_FLIPS_ARM0_G1
