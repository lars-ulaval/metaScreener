# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""The wave-17 freeze guard.

Every number this file asserts is RE-DERIVED from the frozen bytes, not restated
from a document. That is the whole point: a freeze test that copies figures out
of the analysis proves the analysis was transcribed, not that it was true. Where
a figure appears in `docs/data/wave17_arms/ANALYSIS_WAVE_17_ARMS.md` or in a
register row, this file recomputes it from `*_FULL.csv` and `*_summary.json` and
fails if the two disagree.

Three layers:

1. THE BYTES. SHA256SUMS is a bijection with `git ls-files` — never with the
   filesystem, because an `rglob` will happily digest an untracked scratch file
   and call the freeze complete (F-223). Every frozen file is deterministically
   pinned, and the working tree is asserted equal to what a checkout serves
   (`git cat-file --filters`), which is the check F-230 exists because nobody
   had.

2. THE RUNS. Provenance, shape, policy and spend, against `meta.txt`'s claims.

3. THE RESULTS. The headline findings of the wave, recomputed: F-221's
   replication, F-247's batch-size effect, F-244's EL precision, F-238's
   identical-span evidence, F-246's abstract-less behaviour, and the two guard
   populations that make "zero removals" true.
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "docs" / "data" / "wave17_arms"
LIVE = FROZEN / "live_v1"
DRY = FROZEN / "dryrun_v1"
REL = "docs/data/wave17_arms"

csv.field_size_limit(10_000_000)

ARMS = ("h0_baseline", "h1_paraphrase", "h2_polarity", "h3_stage_stress",
        "h4_edge_shapes", "h5_adversarial", "h6_no_abstract", "h7_loose",
        "h8_pinned_target", "h9_batch1")
STAGES = ("EL", "IL")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                          text=True, check=True).stdout


def _tracked() -> set:
    out = subprocess.run(["git", "ls-files", "-z", "--", REL], cwd=str(ROOT),
                         capture_output=True, check=True).stdout.decode()
    return {p[len(REL) + 1:] for p in out.split("\0") if p}


def _sums() -> dict:
    text = (FROZEN / "SHA256SUMS").read_text(encoding="utf-8")
    out = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, name = line.split(" *", 1)
        out[name] = digest
    return out


@pytest.fixture(scope="module")
def summaries():
    return {(a, s): json.loads((LIVE / f"{a}_{s}_summary.json").read_text(encoding="utf-8"))
            for a in ARMS for s in STAGES}


@pytest.fixture(scope="module")
def manifests():
    return {a: json.loads((LIVE / f"{a}_live_manifest.json").read_text(encoding="utf-8"))
            for a in ARMS}


def _rows(arm: str, stage: str) -> list:
    with open(LIVE / f"{arm}_{stage}_FULL.csv", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _ev(row: dict, stage: str) -> dict:
    return json.loads(row[f"{stage.lower()}_evidence_json"] or "{}")


def _outcome(row: dict, stage: str) -> str:
    return row[f"{stage.lower()}_outcome"]


def _ctypes(arm: str) -> dict:
    man = json.loads((DRY / f"{arm}_manifest.json").read_text(encoding="utf-8"))
    return {r["id"]: r["type"] for r in man["harmonized_rows"]}


def _offtopic(row: dict) -> bool:
    p = row.get("parents") or ""
    return p.startswith("X002") or p.startswith("X012")


def _clean_both(arm: str) -> set:
    el = {r["local_id"]: _outcome(r, "EL") for r in _rows(arm, "EL")}
    il = {r["local_id"]: _outcome(r, "IL") for r in _rows(arm, "IL")}
    return {k for k in el if el[k] == "PASS_CLEAN" and il[k] == "PASS_CLEAN"}


# --------------------------------------------------------------------------
# 1. the bytes
# --------------------------------------------------------------------------

class TestTheBytesAreFrozen:

    def test_sha256sums_is_a_bijection_with_git_ls_files(self):
        """Against git, never against the filesystem. F-223."""
        sums = _sums()
        tracked = _tracked() - {"SHA256SUMS"}
        assert set(sums) == tracked, (
            f"only in SHA256SUMS: {sorted(set(sums) - tracked)}; "
            f"tracked but unlisted: {sorted(tracked - set(sums))}")
        assert len(sums) == 113, len(sums)

    def test_every_recorded_digest_verifies(self):
        for name, digest in _sums().items():
            got = hashlib.sha256((FROZEN / name).read_bytes()).hexdigest()
            assert got == digest, f"{name}: recorded {digest}, bytes hash {got}"

    def test_every_frozen_file_is_deterministically_pinned(self):
        """Including the extensionless SHA256SUMS.

        Two pins are acceptable and the difference is deliberate. `binary` is
        wave 16d's rule for a frozen directory and is used for `dryrun_v1/**`
        and `live_v1/**`. The nine top-level authored files keep
        `text eol=crlf`, because `experiment_spec.json` records each arm's
        `source_sha256` against the CRLF checkout and F-230's guard compares
        with `git cat-file --filters`; flipping them to binary would break
        both. What is NOT acceptable is `text=auto`, which is what every file
        under the two subdirectories had before this freeze and which makes the
        bytes — and therefore every digest above — platform-dependent.
        """
        for rel in sorted(_tracked()):
            out = _git("check-attr", "text", "eol", "binary", "--", f"{REL}/{rel}")
            pinned = ("binary: set" in out) or ("eol: crlf" in out)
            assert pinned, f"{rel} is not deterministically pinned:\n{out}"

    def test_the_working_tree_is_what_a_checkout_serves(self):
        """F-230's actual lesson: a digest is a promise about the bytes a
        clone produces, not about the bytes that happen to be on this disk."""
        for rel in sorted(_tracked()):
            served = subprocess.run(["git", "cat-file", "--filters", f":{REL}/{rel}"],
                                    cwd=str(ROOT), capture_output=True, check=True).stdout
            assert served == (FROZEN / rel).read_bytes(), rel

    def test_all_ten_arms_have_all_nine_artefacts(self):
        for arm in ARMS:
            for suffix in ("EL_FULL.csv", "EL_log.txt", "EL_report.json",
                           "EL_summary.json", "IL_FULL.csv", "IL_log.txt",
                           "IL_report.json", "IL_summary.json",
                           "live_manifest.json"):
                assert (LIVE / f"{arm}_{suffix}").is_file(), f"{arm}_{suffix}"


# --------------------------------------------------------------------------
# 2. the runs are what meta.txt says
# --------------------------------------------------------------------------

class TestTheRunsAreWhatTheMetaSays:

    @pytest.mark.parametrize("arm", ARMS)
    @pytest.mark.parametrize("stage", STAGES)
    def test_provenance(self, arm, stage, summaries):
        p = summaries[(arm, stage)]["provenance"]
        assert p["model"] == "qwen2.5:7b"
        assert p["endpoint"] == "http://localhost:11434/v1"
        assert p["temperature"] == 0.0
        assert p["trunc_chars"] == 1500
        assert p["context_window"] == 4096
        assert p["prompt_version"] == f"{stage}_v3_nullquote"

    @pytest.mark.parametrize("arm", ARMS)
    @pytest.mark.parametrize("stage", STAGES)
    def test_batch_size_is_five_except_h9(self, arm, stage, summaries):
        want = 1 if arm == "h9_batch1" else 5
        assert summaries[(arm, stage)]["provenance"]["batch_size"] == want

    def test_nothing_was_removed_anywhere(self, summaries):
        outs = {k: v["counts"]["OUT"] for k, v in summaries.items()}
        assert set(outs.values()) == {0}, {k: v for k, v in outs.items() if v}
        assert len(outs) == 20

    def test_no_unconstrained_fallback_anywhere(self, summaries):
        shapes = {v["request_shape"] for v in summaries.values()}
        assert shapes == {"json_schema"}, shapes

    def test_flag_only_everywhere(self, summaries):
        assert {v["exclusion_policy"] for v in summaries.values()} == {"flag_only"}

    def test_no_arm_approached_its_ceiling(self, manifests):
        worst = max(m["calls_made_total"] / m["declared_budget"] for m in manifests.values())
        assert worst < 0.60, worst
        for arm, m in manifests.items():
            assert m["calls_made_total"] < m["declared_budget"], arm
            assert m["anomaly_stops"] == [], (arm, m["anomaly_stops"])

    def test_total_spend(self, manifests):
        assert sum(m["calls_made_total"] for m in manifests.values()) == 472

    def test_corpus_digest_is_pinned_and_agreed(self, manifests):
        spec = json.loads((FROZEN / "experiment_spec.json").read_text(encoding="utf-8"))
        want = spec["corpus_sha256"]
        assert want == ("e8b262f1203c8b459357e866bc376e40"
                        "f3b73a2d7b68b67cac5a3f01e371435c")
        for arm, m in manifests.items():
            assert m["preflight"]["corpus"]["sha256"] == want, arm
            assert m["preflight"]["corpus"]["records"] == 463, arm

    def test_cache_was_off_on_every_arm(self, manifests):
        for arm, m in manifests.items():
            assert m["preflight"]["cache"]["use_cache"] is False, arm


# --------------------------------------------------------------------------
# 3. crit_impacts is a derivation and must still derive (F-228)
# --------------------------------------------------------------------------

class TestCritImpactsIsRecoverable:

    def test_the_capture_matches_a_fresh_derivation(self):
        """The engine computes this table on every run and persists it
        nowhere; the freeze captures a reconstruction, so the reconstruction
        must keep reproducing or the capture is an orphan."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "extract_crit_impacts", ROOT / "tools" / "extract_crit_impacts.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fresh = mod.build()
        committed = json.loads((LIVE / "crit_impacts.json").read_text(encoding="utf-8"))
        assert fresh == committed

    def test_it_covers_every_arm_and_both_halves(self):
        d = json.loads((LIVE / "crit_impacts.json").read_text(encoding="utf-8"))
        assert set(d["arms"]) == set(ARMS)
        for arm, e in d["arms"].items():
            assert set(e["llm_stages"]) == {"EL", "IL"}, arm
            assert set(e["deterministic_stages"]) == {"EH", "IH"}, arm

    def test_the_buckets_partition_the_records(self):
        d = json.loads((LIVE / "crit_impacts.json").read_text(encoding="utf-8"))
        for arm, e in d["arms"].items():
            for stage, s in e["llm_stages"].items():
                for cid, b in s["impacts"].items():
                    assert sum(b.values()) == s["records"], (arm, stage, cid)

    def test_nothing_was_acted_on_which_is_why_out_is_zero(self):
        """`failed` counts asserted removals, acted or not — screen.py's own
        choice. The split is what tells you no removal was executed."""
        d = json.loads((LIVE / "crit_impacts.json").read_text(encoding="utf-8"))
        acted = sum(v["acted_FAILED"]
                    for e in d["arms"].values()
                    for s in e["llm_stages"].values()
                    for v in s["failed_split"].values())
        assert acted == 0


# --------------------------------------------------------------------------
# 4. the results, re-derived
# --------------------------------------------------------------------------

class TestTheGuardsThatMadeZeroRemovalsTrue:
    """F-238. Two decliners, two strengths, and the counts are not the same."""

    def test_the_two_populations(self):
        presence = absence = 0
        for arm in ARMS:
            ct = _ctypes(arm)
            for stage in STAGES:
                for row in _rows(arm, stage):
                    for cid, v in _ev(row, stage).items():
                        if v["status"] != "SUPPRESSED":
                            continue
                        if ct.get(cid) == "exclude" and v["decision"] == "meet":
                            presence += 1
                        elif ct.get(cid) == "include" and v["decision"] == "not_meet":
                            absence += 1
        # held by exclusion_policy=flag_only, which a provider setting can turn off
        assert presence == 49
        # held by gate rule (c), which no setting can turn off
        assert absence == 576


class TestF221ReplicationAtIL:
    """Wording sensitivity: magnitude replicates, direction does not."""

    def test_nine_of_thirty_two_flip_and_two_go_the_other_way(self):
        a = {r["local_id"]: _ev(r, "IL")["IC-1"] for r in _rows("h0_baseline", "IL")}
        b = {r["local_id"]: _ev(r, "IL")["IC-1"] for r in _rows("h1_paraphrase", "IL")}
        assert set(a) == set(b) and len(a) == 32
        moves = Counter(f'{a[k]["decision"]}->{b[k]["decision"]}'
                        for k in a if a[k]["decision"] != b[k]["decision"])
        assert moves == {"meet->not_meet": 7, "not_meet->meet": 2}

    def test_the_review_pile_grew(self):
        def pile(arm, stage):
            return sum(1 for r in _rows(arm, stage)
                       if _outcome(r, stage) == "EXCLUSION_SUPPRESSED")
        assert (pile("h0_baseline", "IL"), pile("h1_paraphrase", "IL")) == (19, 25)
        assert (pile("h0_baseline", "EL"), pile("h1_paraphrase", "EL")) == (2, 6)


class TestF247BatchSize:
    """The only difference is batch_size, and the result moves as much as a
    full rewrite of the criteria."""

    def test_everything_except_batch_size_is_identical(self, summaries, manifests):
        for stage in STAGES:
            p0 = dict(summaries[("h0_baseline", stage)]["provenance"])
            p9 = dict(summaries[("h9_batch1", stage)]["provenance"])
            assert p0.pop("batch_size") == 5 and p9.pop("batch_size") == 1
            assert p0 == p9
        assert (manifests["h0_baseline"]["preflight"]["criteria_sha256"]
                == manifests["h9_batch1"]["preflight"]["criteria_sha256"])

    def test_the_unaided_clearance_pile_halves(self):
        h0, h9 = _clean_both("h0_baseline"), _clean_both("h9_batch1")
        assert (len(h0), len(h9)) == (10, 5)
        assert h0 & h9 == {"A265", "A281"}

    def test_the_same_magnitude_as_rewording(self):
        assert len(_clean_both("h1_paraphrase")) == 5


class TestF244ELPrecision:

    def test_sixteen_excluding_verdicts_on_nine_distinct_pairs(self):
        verdicts, pairs = 0, set()
        for arm in ("h0_baseline", "h1_paraphrase", "h8_pinned_target"):
            for row in _rows(arm, "EL"):
                for cid, v in _ev(row, "EL").items():
                    if v["decision"] == "meet":
                        verdicts += 1
                        pairs.add((row["local_id"], cid))
        assert verdicts == 16
        assert len(pairs) == 9

    def test_ec3_never_fired_on_the_two_records_it_was_written_for(self):
        for arm in ("h0_baseline", "h1_paraphrase", "h8_pinned_target"):
            by = {r["local_id"]: _ev(r, "EL") for r in _rows(arm, "EL")}
            for rid in ("A014", "A220"):
                assert by[rid]["EC-3"]["decision"] == "not_meet", (arm, rid)

    def test_h7_el_auto_actable_precision(self):
        supp = [r for r in _rows("h7_loose", "EL")
                if _outcome(r, "EL") == "EXCLUSION_SUPPRESSED"]
        assert len(supp) == 19
        assert sum(1 for r in supp if _offtopic(r)) == 6

    def test_h7_il_flagged_every_off_topic_record(self):
        rows = _rows("h7_loose", "IL")
        off = [r for r in rows if _offtopic(r)]
        assert len(off) == 47
        assert all(_outcome(r, "IL") != "PASS_CLEAN" for r in off)
        cleared = [r for r in rows if _outcome(r, "IL") == "PASS_CLEAN"]
        assert len(cleared) == 33
        assert sum(1 for r in cleared if _offtopic(r)) == 0


class TestF238TheSameQuoteBothWays:
    """The clearest statement that validity checks presence, not support."""

    @pytest.mark.parametrize("arm,rid", [("h0_baseline", "A187"),
                                         ("h0_baseline", "A275"),
                                         ("h8_pinned_target", "A275")])
    def test_one_quote_proves_a_claim_and_its_contrary(self, arm, rid):
        el = {r["local_id"]: _ev(r, "EL") for r in _rows(arm, "EL")}[rid]["EC-3"]
        il = {r["local_id"]: _ev(r, "IL") for r in _rows(arm, "IL")}[rid]["IC-1"]
        assert el["decision"] == "meet" and il["decision"] == "meet"
        assert el["quote"].strip() == il["quote"].strip() != ""
        assert el["quote_valid"] is True and il["quote_valid"] is True

    def test_only_a187_also_shares_the_declared_span(self):
        """The quote is byte-identical on all three pairs; the SPAN is shared
        on `h0`/A187 only. An early draft of the analysis said "at the same
        span" of all three and this test is why it does not any more: on A275
        the same 68-character string is declared at `[0, 39]` by EC-3 and
        `[0, 35]` by IC-1, in the same run."""
        def spans(arm, rid):
            el = {r["local_id"]: _ev(r, "EL") for r in _rows(arm, "EL")}[rid]["EC-3"]
            il = {r["local_id"]: _ev(r, "IL") for r in _rows(arm, "IL")}[rid]["IC-1"]
            return el["span"], il["span"]
        assert spans("h0_baseline", "A187") == ([0, 36], [0, 36])
        assert spans("h0_baseline", "A275") == ([0, 39], [0, 35])
        assert spans("h8_pinned_target", "A275") == ([0, 39], [0, 35])

    def test_not_one_span_in_the_wave_matches_its_quote(self):
        """`span` is documented as "[start, end] of the quote". Across all ten
        arms not a single one is: the width never equals the quoted string's
        length, including the [0, 36] that A187's two contradictory verdicts
        agree on for a 68-character quote. The field is decorative, and the
        gate never consults it — only `_quote_in_text` decides."""
        seen = matched = 0
        for arm in ARMS:
            for stage in STAGES:
                for row in _rows(arm, stage):
                    for v in _ev(row, stage).values():
                        q, sp = (v.get("quote") or ""), v.get("span")
                        if not q.strip() or not isinstance(sp, list):
                            continue
                        seen += 1
                        matched += (sp[1] - sp[0] == len(q))
        assert seen == 212
        assert matched == 0


class TestF246AbstractlessRecords:

    def test_absence_is_read_as_evidence_of_absence(self):
        rows = _rows("h6_no_abstract", "IL")
        empty = [r for r in rows if not (r["abstract"] or "").strip()]
        assert len(empty) == 32
        assert Counter(_outcome(r, "IL") for r in empty) == {
            "EXCLUSION_SUPPRESSED": 30, "PASS_CLEAN": 1, "REVIEW": 1}

    def test_the_model_names_a_field_that_does_not_exist(self):
        n = 0
        for stage, crit in (("EL", "H6-2"), ("IL", "H6-3")):
            for r in _rows("h6_no_abstract", stage):
                if (r["abstract"] or "").strip():
                    continue
                if _ev(r, stage)[crit]["field"] == "abstract":
                    n += 1
        assert n == 56


class TestF239SilentRecallLoss:
    """One criterion does the topical work; the other removes the target
    literature, including the corpus's own seed paper."""

    IC4 = ("respiratory sinus arrhythmia", "vagal", "heart rate variability")
    IC5 = ("emotion", "dysregulation", "child", "adolescent", "youth", "infant")

    def _corpus(self):
        path = ROOT / "samples" / "20260816_1841_rsaAggregate.csv"
        with open(path, newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))

    def _blob(self, r):
        return (r["title"] + " " + r["abstract"] + " " + r["keywords"]).lower()

    def test_ic4_alone_excludes_almost_all_the_off_topic_records(self):
        rows = self._corpus()
        off = [r for r in rows if _offtopic(r)]
        assert len(off) == 152
        assert sum(1 for r in off if not any(o in self._blob(r) for o in self.IC4)) == 151

    def test_ic5_removes_on_topic_records_that_ic4_kept(self):
        rows = self._corpus()
        eh = [r for r in rows if r["lang"] != "pt"
              and not any(v.lower() in (r["venue"] or "").lower()
                          for v in ("Physical Review", "Physics Letters",
                                    "Bifurcation and Chaos"))]
        killed = [r for r in eh
                  if any(o in self._blob(r) for o in self.IC4)
                  and not any(o in self._blob(r) for o in self.IC5)]
        assert len(killed) == 117
        assert sum(1 for r in killed if not _offtopic(r)) == 116

    def test_the_seed_paper_is_among_them(self):
        """Seed [1] of samples/20260122_1654_rsaSampleReferences.txt."""
        a044 = {r["local_id"]: r for r in self._corpus()}["A044"]
        assert a044["first_author"] == "Gary G. Berntson"
        assert a044["title"].startswith("Respiratory sinus arrhythmia: Autonomic origins")
        assert any(o in self._blob(a044) for o in self.IC4)
        assert not any(o in self._blob(a044) for o in self.IC5)
