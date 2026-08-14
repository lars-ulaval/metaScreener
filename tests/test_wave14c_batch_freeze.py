# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_wave14c_batch_freeze.py — F-197's evidence is committed, and the figures
the retraction publishes are re-derived from it on every suite run.

The batch comparison behind register row F-197 and the § 8.3 retraction in
``docs/internal/diagnostic/07_criteria_parsing.md`` was captured as five
bundle zips in ``_archive_bundles/`` — a sibling directory outside version
control, which is the exact state **F-159** exists to forbid and closed for
wave 12 one wave earlier. ``docs/data/wave14c_batch_runs/`` is the reduction;
this file is its guard, in ``test_wave12_measurement_freeze.py``'s shape and
for its reasons:

1. *Coverage* — the frozen set is read off the directory and the digest set
   off ``SHA256SUMS``, and the two must agree in both directions. No
   hand-maintained list (F-131's rule).
2. *Self-authentication* — every committed artefact is matched against the
   digest its **own run's manifest** records for it, by basename.
3. *Anchoring* — the criteria table both runs read is byte-identical across
   the two manifests, and the omitted ``data/original.csv`` is anchored to
   the committed sample corpus by digest.
4. *Fidelity* — the headline figures are recomputed from the artefacts and
   the retraction's table is required to state them. The artefacts are the
   source of truth; the prose has to agree with them.
5. *Bytes* — ``.gitattributes`` must keep these files out of ``* text=auto``,
   asserted through ``git check-attr`` rather than by reading the file and
   matching patterns by eye (the F-99 lesson).
"""
import csv
import hashlib
import io
import json
import subprocess
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT

FROZEN = PROJECT_ROOT / "docs" / "data" / "wave14c_batch_runs"

RUNS = {
    "runD_batch1": {"batch_size": 1, "answered": 17, "no_answer": 277,
                    "calls_made": 294},
    "runE_batch5": {"batch_size": 5, "answered": 241, "no_answer": 53,
                    "calls_made": 56},
}


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _manifest(run: str) -> dict:
    return json.loads((FROZEN / f"{run}_manifest.json").read_bytes()
                      .decode("utf-8"))


def _el_history(m: dict) -> dict:
    hist = (m.get("pipeline", {}) or {}).get("history", []) or []
    entries = [h for h in hist if h.get("stage") == "EL"]
    assert len(entries) == 1, "expected exactly one EL history entry"
    return entries[0]


def _sha_block(m: dict) -> dict:
    for key in ("sha256", "digests", "files"):
        blk = m.get(key)
        if isinstance(blk, dict) and blk:
            return blk
    # nested search: the block may sit under another key; find the dict whose
    # keys look like member paths and whose values are 64-hex strings
    def walk(o):
        if isinstance(o, dict):
            vals = list(o.values())
            if vals and all(isinstance(v, str) and len(v) == 64 for v in vals):
                if any("/" in k or k.endswith(".csv") for k in o):
                    yield o
            for v in vals:
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
    found = list(walk(m))
    assert found, "no sha256 member block found in manifest"
    merged = {}
    for d in found:
        merged.update(d)
    return merged


class TestTheFreezeIsCoveredWithoutAList:

    def test_every_frozen_file_has_a_digest_and_every_digest_a_file(self):
        listed = {}
        for ln in (FROZEN / "SHA256SUMS").read_bytes().decode("ascii").splitlines():
            if ln.strip():
                h, name = ln.split(None, 1)
                listed[name.lstrip("*").strip()] = h
        on_disk = {p.name for p in FROZEN.iterdir()
                   if p.name not in ("SHA256SUMS", "wave14c_batch_runs.meta.txt")}
        assert set(listed) == on_disk, (
            "SHA256SUMS and the directory disagree: "
            f"only-listed={set(listed) - on_disk} only-on-disk={on_disk - set(listed)}"
        )
        for name, h in listed.items():
            assert _sha256(FROZEN / name) == h, f"digest mismatch: {name}"


class TestTheArtefactsAuthenticateThemselves:

    @pytest.mark.parametrize("run", sorted(RUNS))
    def test_committed_members_match_their_own_manifests_digests(self, run):
        blk = _sha_block(_manifest(run))
        by_base = {Path(k).name: v for k, v in blk.items()}
        pairs = [(f"{run}_EL_FULL.csv", "EL_FULL.csv"),
                 (f"{run}_EL_cache.jsonl", "EL_cache.jsonl")]
        for committed, member in pairs:
            assert member in by_base, f"{run}: manifest records no {member}"
            assert _sha256(FROZEN / committed) == by_base[member], (
                f"{committed} does not match the digest {run}'s own manifest "
                f"records for {member}"
            )

    @pytest.mark.parametrize("run", sorted(RUNS))
    def test_the_counters_in_the_manifest_are_the_advertised_ones(self, run):
        entry = _el_history(_manifest(run))
        rep = entry.get("llm", {})
        want = RUNS[run]
        assert rep.get("answered") == want["answered"]
        assert rep.get("no_answer") == want["no_answer"]
        assert rep.get("calls_made") == want["calls_made"]
        # `provenance` is a sibling of `llm` in the history entry, not a
        # child of it — established by reading the manifest, not assumed.
        prov = entry.get("provenance", {})
        assert prov.get("batch_size") == want["batch_size"]
        assert prov.get("model") == "qwen2.5:7b"
        assert prov.get("temperature") == 0.0
        assert prov.get("trunc_chars") == 1500

    def test_only_batch_size_differs_between_the_two_provenance_blocks(self):
        """The controlled-comparison claim itself, asserted rather than
        narrated: every provenance field except batch_size is identical."""
        pd = _el_history(_manifest("runD_batch1")).get("provenance", {})
        pe = _el_history(_manifest("runE_batch5")).get("provenance", {})
        assert set(pd) == set(pe)
        diff = {k for k in pd if pd[k] != pe[k]}
        assert diff == {"batch_size"}, f"unexpected differing fields: {diff}"


class TestTheOmittedMembersAreAccountedFor:

    def test_the_criteria_table_is_the_one_both_manifests_record(self):
        got = _sha256(FROZEN / "runDE_criteria_harmonized.csv")
        for run in sorted(RUNS):
            blk = {Path(k).name: v for k, v in _sha_block(_manifest(run)).items()}
            assert blk.get("criteria_harmonized.csv") == got, (
                f"{run}'s manifest records a different criteria table"
            )

    def test_the_original_corpus_is_anchored_to_the_committed_sample(self):
        sample = PROJECT_ROOT / "samples" / "20260122_1654_aggregate.csv"
        got = _sha256(sample)
        for run in sorted(RUNS):
            blk = {Path(k).name: v for k, v in _sha_block(_manifest(run)).items()}
            if "original.csv" in blk:
                assert blk["original.csv"] == got, (
                    f"{run}: data/original.csv digest does not match the "
                    f"committed sample corpus"
                )

    def test_runD_cache_is_contained_in_runE_cache(self):
        """F-101's field measurement, held structurally: the 17 pairs runD
        answered were served to runE from cache, so every runD key must
        appear verbatim in runE's cache. If this ever fails the two runs
        were not the session the meta file describes."""
        def keys(name):
            out = set()
            for ln in (FROZEN / name).read_bytes().decode("utf-8").splitlines():
                if ln.strip():
                    out.add(json.loads(ln)["key"])
            return out
        kd = keys("runD_batch1_EL_cache.jsonl")
        ke = keys("runE_batch5_EL_cache.jsonl")
        assert len(kd) == 17 and len(ke) == 241
        assert kd <= ke


class TestTheRetractionAgreesWithTheArtefacts:

    def _figures(self):
        out = {}
        for run in sorted(RUNS):
            rep = _el_history(_manifest(run)).get("llm", {})
            counts = _el_history(_manifest(run)).get("counts", {})
            out[run] = (rep["answered"], rep["no_answer"], counts)
        return out

    def test_the_headline_figures_recompute_from_the_full_reports(self):
        """The manifests' counters must agree with a fresh derivation from
        el_evidence_json — the counters are not taken on faith."""
        for run in sorted(RUNS):
            text = (FROZEN / f"{run}_EL_FULL.csv").read_bytes().decode("utf-8-sig")
            answered = no_answer = 0
            for row in csv.DictReader(io.StringIO(text)):
                for _cid, ev in json.loads(row["el_evidence_json"]).items():
                    if ev.get("used"):
                        answered += 1
                    else:
                        no_answer += 1
            assert answered == RUNS[run]["answered"], run
            assert no_answer == RUNS[run]["no_answer"], run

    def test_the_retraction_table_states_the_recomputed_numbers(self):
        doc = (PROJECT_ROOT / "docs" / "internal" / "diagnostic"
               / "07_criteria_parsing.md").read_text(encoding="utf-8")
        # rfind, deliberately: the retraction appears twice — a pointer in
        # the summary line at the top and the full note in § 8.3 — and only
        # the § 8.3 note carries the table.
        idx = doc.rfind("Retracted 2026-08-13 (wave 14c)")
        assert idx != -1, "the § 8.3 retraction note is gone"
        note = doc[idx:idx + 4000]
        for needle in ("17 / 294", "241 / 294", "277 (94", "53 (18",
                       "0 / 0 / 147", "0 / 61 / 75"):
            assert needle in note, f"retraction table no longer states {needle!r}"


class TestTheFrozenBytesSurviveCheckout:

    @pytest.mark.parametrize("name", [
        "runD_batch1_EL_FULL.csv", "runD_batch1_EL_cache.jsonl",
        "runD_batch1_manifest.json", "runE_batch5_EL_FULL.csv",
        "runE_batch5_EL_cache.jsonl", "runE_batch5_manifest.json",
        "runDE_criteria_harmonized.csv",
    ])
    def test_gitattributes_shields_every_data_file(self, name):
        """Through ``git check-attr``, not by reading .gitattributes and
        matching globs by eye — misreading a pattern is how F-99 shipped.
        ``binary`` is a macro; the effect that matters is ``text: unset``."""
        rel = f"docs/data/wave14c_batch_runs/{name}"
        proc = subprocess.run(
            ["git", "check-attr", "-a", "--", rel],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        if proc.returncode != 0:
            pytest.skip("git check-attr unavailable: %s" % proc.stderr.strip())
        attrs = {}
        for ln in proc.stdout.splitlines():
            parts = ln.split(": ", 2)
            if len(parts) == 3:
                attrs[parts[1]] = parts[2]
        assert attrs.get("text") == "unset", (
            f"{rel} is not shielded from `* text=auto` "
            f"(text={attrs.get('text')!r}) — a fresh checkout rewrites its "
            f"line endings and every digest above breaks (F-99)"
        )
