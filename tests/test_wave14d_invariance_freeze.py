# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_wave14d_invariance_freeze.py — the batch-invariance measurement's
evidence is committed, and its headline figures are re-derived from the
bytes on every suite run.

A sibling of ``test_wave12_measurement_freeze.py`` and
``test_wave14c_batch_freeze.py`` rather than an extension of either,
deliberately: one guard per frozen dataset is the established shape, and
this dataset's fidelity target differs — the wave-14c guard holds its
artefacts against the § 8.3 retraction table, while this one re-derives the
fabrication, agreement and churn numbers and holds them against the
directory's own meta file, which is what the register row and the tooltip
cite.

The five-part structure is the house one: coverage without a list,
self-authentication against each run's own manifest, anchoring of shared
members to already-committed bytes, fidelity by recomputation, and
checkout-survival through ``git check-attr`` (the F-99 lesson: never read
``.gitattributes`` and match globs by eye).
"""
import csv
import hashlib
import io
import json
import re
import subprocess
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT

FROZEN = PROJECT_ROOT / "docs" / "data" / "wave14d_invariance_runs"
RUNS = ("runF_batch1", "runG_batch5a", "runH_batch5b", "runI_batch10")

#: The headline figures, as the meta file and register row F-201 state them.
#: Everything here is RE-DERIVED from the artefacts below; these constants
#: exist so a drifted artefact and a drifted claim fail against each other.
MEET_PAIRS = {"runF_batch1": 0, "runG_batch5a": 15, "runH_batch5b": 12,
              "runI_batch10": 18}
AGREEMENT_VS_F = {"runG_batch5a": 278, "runH_batch5b": 281, "runI_batch10": 276}
NOISE_FLOOR = 284            # runG <-> runH, same configuration
QUOTE_VALID_FLIPS = 32       # runG <-> runH
OUTCOME_CHURN = 24           # records changing el_outcome, runG <-> runH
BATCHES = {"runF_batch1": 1, "runG_batch5a": 5, "runH_batch5b": 5,
           "runI_batch10": 10}
CALLS = {"runF_batch1": 294, "runG_batch5a": 60, "runH_batch5b": 60,
         "runI_batch10": 30}


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _manifest(run: str) -> dict:
    return json.loads((FROZEN / f"{run}_manifest.json").read_bytes()
                      .decode("utf-8"))


def _el(run: str) -> dict:
    hist = [h for h in _manifest(run)["pipeline"]["history"]
            if h.get("stage") == "EL"]
    assert len(hist) == 1
    return hist[0]


def _sha_block(m: dict) -> dict:
    def walk(o):
        if isinstance(o, dict):
            vals = list(o.values())
            if vals and all(isinstance(v, str) and len(v) == 64 for v in vals):
                if any("/" in k or str(k).endswith(".csv") for k in o):
                    yield o
            for v in vals:
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
    merged = {}
    for d in walk(m):
        merged.update(d)
    assert merged, "no sha256 member block found"
    return merged


def _decisions(run: str):
    text = (FROZEN / f"{run}_EL_FULL.csv").read_bytes().decode("utf-8-sig")
    dec, qv, outcome = {}, {}, {}
    for r in csv.DictReader(io.StringIO(text)):
        lid = r["local_id"]
        outcome[lid] = r["el_outcome"]
        for cid, ev in json.loads(r["el_evidence_json"]).items():
            dec[(lid, cid)] = ev.get("decision")
            qv[(lid, cid)] = bool(ev.get("quote_valid", False))
    return dec, qv, outcome


@pytest.fixture(scope="module")
def data():
    return {run: _decisions(run) for run in RUNS}


class TestTheFreezeIsCoveredWithoutAList:

    def test_every_frozen_file_has_a_digest_and_every_digest_a_file(self):
        listed = {}
        for ln in (FROZEN / "SHA256SUMS").read_bytes().decode("ascii").splitlines():
            if ln.strip():
                h, name = ln.split(None, 1)
                listed[name.lstrip("*").strip()] = h
        on_disk = {p.name for p in FROZEN.iterdir()
                   if p.name not in ("SHA256SUMS",
                                     "wave14d_invariance_runs.meta.txt")}
        assert set(listed) == on_disk
        for name, h in listed.items():
            assert _sha256(FROZEN / name) == h, name


class TestTheArtefactsAuthenticateThemselves:

    @pytest.mark.parametrize("run", RUNS)
    def test_the_full_report_matches_its_own_manifests_digest(self, run):
        by_base = {Path(k).name: v for k, v in _sha_block(_manifest(run)).items()}
        assert by_base.get("EL_FULL.csv") == _sha256(FROZEN / f"{run}_EL_FULL.csv")

    @pytest.mark.parametrize("run", RUNS)
    def test_the_run_is_a_post_14c_constrained_cache_off_run(self, run):
        e = _el(run)
        rep, prov = e["llm"], e["provenance"]
        assert prov["prompt_version"] == "EL_v2_jsonschema"
        assert rep["request_shape"] == "json_schema"
        assert prov["batch_size"] == BATCHES[run]
        assert (rep["records"], rep["answered"], rep["no_answer"]) == (294, 294, 0)
        assert rep["reasks_made"] == 0 and rep["no_answer_after_reask"] == 0
        # cache off, shown by arithmetic: the exact no-cache call count.
        assert rep["calls_made"] == CALLS[run]
        # and by absence: the manifest's member block records no cache file.
        assert not any("cache" in k.lower()
                       for k in _sha_block(_manifest(run)))

    def test_the_two_batch5_runs_are_same_configuration_repeats(self):
        pg, ph = _el("runG_batch5a")["provenance"], _el("runH_batch5b")["provenance"]
        assert pg == ph, "runG and runH must differ in NOTHING the block records"

    def test_only_batch_size_varies_across_the_four(self):
        provs = {run: dict(_el(run)["provenance"]) for run in RUNS}
        for p in provs.values():
            p.pop("batch_size")
        assert len({json.dumps(p, sort_keys=True) for p in provs.values()}) == 1


class TestTheSharedMembersAreAnchored:

    def test_the_criteria_table_is_the_wave14c_committed_one(self):
        anchor = _sha256(PROJECT_ROOT / "docs" / "data" / "wave14c_batch_runs"
                         / "runDE_criteria_harmonized.csv")
        for run in RUNS:
            by_base = {Path(k).name: v
                       for k, v in _sha_block(_manifest(run)).items()}
            assert by_base.get("criteria_harmonized.csv") == anchor, run

    def test_the_el_input_is_one_corpus_across_all_four(self):
        meta = (FROZEN / "wave14d_invariance_runs.meta.txt").read_text(
            encoding="utf-8")
        pinned = re.search(r"ih_input_sha256=([0-9a-f]{64})", meta).group(1)
        for run in RUNS:
            by_base = {Path(k).name: v
                       for k, v in _sha_block(_manifest(run)).items()}
            assert by_base.get("current.csv") == pinned, run


class TestTheMetaAgreesWithTheArtefacts:
    """Fidelity by recomputation: the numbers the register row and the
    tooltip cite are re-derived from the bytes, then required to appear in
    the meta file. Edit a number there and this fails; let an artefact
    drift and the self-authentication above fails first."""

    def test_meet_pairs_and_their_direction(self, data):
        f_dec = data["runF_batch1"][0]
        for run in RUNS:
            meet = {p for p, d in data[run][0].items() if d == "meet"}
            assert len(meet) == MEET_PAIRS[run], run
            for p in meet:
                assert f_dec[p] == "not_meet", (
                    "every fabricated meet sits on a pair batch 1 answered "
                    "not_meet — the disagreement is directional"
                )

    def test_no_flow_ever_runs_toward_not_meet(self, data):
        f_dec = data["runF_batch1"][0]
        for run in ("runG_batch5a", "runH_batch5b", "runI_batch10"):
            for p, d in data[run][0].items():
                if f_dec[p] != d:
                    assert f_dec[p] == "not_meet", (run, p, f_dec[p], d)

    def test_pairwise_agreement_and_the_noise_floor(self, data):
        def agree(a, b):
            return sum(1 for p in data[a][0] if data[a][0][p] == data[b][0][p])
        for run, want in AGREEMENT_VS_F.items():
            assert agree("runF_batch1", run) == want, run
        assert agree("runG_batch5a", "runH_batch5b") == NOISE_FLOOR

    def test_the_fabrication_targets_are_config_dependent(self, data):
        m = {run: {p for p, d in data[run][0].items() if d == "meet"}
             for run in RUNS}
        assert len(m["runG_batch5a"] & m["runH_batch5b"]) == 9
        assert len(m["runI_batch10"] &
                   (m["runG_batch5a"] | m["runH_batch5b"])) == 2

    def test_the_corpus_base_rate_is_one_record_and_it_was_not_met(self, data):
        text = (FROZEN / "runF_batch1_EL_FULL.csv").read_bytes().decode("utf-8-sig")
        hits = [r["local_id"] for r in csv.DictReader(io.StringIO(text))
                if re.search(r"maze|spatial navigation|rubber hand",
                             " ".join((r.get(f) or "") for f in
                                      ("title", "abstract", "keywords")),
                             re.I)]
        assert hits == ["A349"]
        for run in RUNS:
            for cid in ("EC-2", "EC-3"):
                assert data[run][0][("A349", cid)] == "not_meet", (run, cid)

    def test_same_config_churn(self, data):
        g, h = data["runG_batch5a"], data["runH_batch5b"]
        assert sum(1 for p in g[1] if g[1][p] != h[1][p]) == QUOTE_VALID_FLIPS
        assert sum(1 for lid in g[2] if g[2][lid] != h[2][lid]) == OUTCOME_CHURN

    def test_the_meta_file_states_the_derived_numbers(self):
        meta = (FROZEN / "wave14d_invariance_runs.meta.txt").read_text(
            encoding="utf-8")
        for needle in ("0/294 (0%)", "15/294 (5.1%)", "12/294 (4.1%)",
                       "18/294 (6.1%)", "284/294 (96.6%)", "32/294", "24/147",
                       "278/294", "281/294", "276/294", "A349"):
            assert needle in meta, needle


class TestTheFrozenBytesSurviveCheckout:

    @pytest.mark.parametrize("name", sorted(
        p.name for p in FROZEN.glob("*") if p.suffix in (".csv", ".json")))
    def test_gitattributes_shields_every_data_file(self, name):
        rel = f"docs/data/wave14d_invariance_runs/{name}"
        proc = subprocess.run(["git", "check-attr", "-a", "--", rel],
                              capture_output=True, text=True,
                              cwd=str(PROJECT_ROOT))
        if proc.returncode != 0:
            pytest.skip("git check-attr unavailable")
        attrs = {}
        for ln in proc.stdout.splitlines():
            parts = ln.split(": ", 2)
            if len(parts) == 3:
                attrs[parts[1]] = parts[2]
        assert attrs.get("text") == "unset", rel
