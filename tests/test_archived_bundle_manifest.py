
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_archived_bundle_manifest.py — the manifest shape of a real post-EL
bundle archived 2026-05-07, held against the post-wave-2 code.

That bundle was produced by v3.1.0, before F-05 and F-34 landed. Its
manifest has four defects:

  1. ``sha256["data/current.csv"]`` records the digest of the file EL was
     *given* (the IH survivors) rather than the file EL *wrote* — the stale
     digest F-05 describes.
  2. Four members carry no digest at all: the response cache, both EL
     reports, and the two criteria .txt files.
  3. ``pipeline.stages`` and ``pipeline_state.stages`` contradict each
     other (F-27, still open).
  4. EL appended no ``pipeline.history`` entry.

These tests pin which of the four the current code catches, which it
prevents, and — as honestly as the ones it catches — which it still does
not. A regression fixture is only worth having if it records the gaps too.
"""
import json
import zipfile
from hashlib import sha256

import pytest

from plugins._common.bundle import (
    _verify_sha256_map,
    _write_llm_stage_bundle,
)


CURRENT_CSV = b"local_id,title,abstract,keywords\nA001,T,A,K\nA002,T2,A2,K2\n"
EL_FULL = b"local_id,el_outcome\nA001,PASS_CLEAN\n"
EL_SURV = CURRENT_CSV
CACHE = b'{"key": "k", "val": {}}\n'
CRIT_TXT = b"IC-1 - something\n"

#: Every member of the archived bundle, and the digest its manifest records
#: for that member — None where the manifest records none.
ARCHIVED = {
    "data/current.csv": (CURRENT_CSV, "STALE"),          # wrong digest
    "criteria/criteria_harmonized.csv": (CRIT_TXT, "OK"),  # correct digest
    "reports/EL_FULL.csv": (EL_FULL, None),
    "reports/EL_SURVIVORS.csv": (EL_SURV, None),
    "cache/EL_cache.jsonl": (CACHE, None),
    "criteria/criteria_harmonized.txt": (CRIT_TXT, None),
    "criteria/ic_ec_12.txt": (CRIT_TXT, None),
}

UNDIGESTED = [rel for rel, (_b, d) in ARCHIVED.items() if d is None]


def _archived_manifest():
    """The manifest as archived: one stale digest, four members undigested,
    two contradicting stage maps, and an empty history."""
    sha_map = {}
    for rel, (body, kind) in ARCHIVED.items():
        if kind == "OK":
            sha_map[rel] = sha256(body).hexdigest()
        elif kind == "STALE":
            # the digest of EL's INPUT (the IH survivors), not of what EL wrote
            sha_map[rel] = sha256(b"the IH survivors EL was given").hexdigest()
    return {
        "bundle_schema": "screenA_bundle_v1",
        "sha256": sha_map,
        "pipeline": {"stages": {"EH": "done", "IH": "done"}, "history": []},
        "pipeline_state": {"stages": {"EH": "done", "IH": "done", "EL": "done"}},
    }


def _members():
    return {rel: body for rel, (body, _k) in ARCHIVED.items()}


# ---------------------------------------------------------------------------
# 1. the stale digest — caught
# ---------------------------------------------------------------------------

class TestStaleDigestIsDetected:

    def test_the_mismatch_is_reported(self):
        problems = _verify_sha256_map(_archived_manifest(), _members())
        assert len(problems) == 1
        assert "data/current.csv" in problems[0]

    def test_the_message_names_both_digests(self):
        """A reviewer has to be able to tell this from tampering, so the
        message has to show what was expected against what is there."""
        problem = _verify_sha256_map(_archived_manifest(), _members())[0]
        expected = sha256(b"the IH survivors EL was given").hexdigest()
        assert expected[:12] in problem
        assert sha256(CURRENT_CSV).hexdigest()[:12] in problem

    def test_the_correctly_digested_member_is_not_flagged(self):
        problems = _verify_sha256_map(_archived_manifest(), _members())
        assert not any("criteria_harmonized.csv" in p for p in problems)


# ---------------------------------------------------------------------------
# 2. the missing digests — NOT caught on load, but no longer producible
# ---------------------------------------------------------------------------

class TestMissingDigests:

    def test_load_time_verification_does_not_flag_them(self):
        """Documenting a real gap rather than asserting a fix that is not
        there. ``_verify_sha256_map`` skips members the manifest makes no
        claim about, by design — it cannot tell "this stage forgot to record
        a digest" from "this member is not covered by the scheme". So four
        undigested members in the archived bundle pass verification in
        silence."""
        problems = _verify_sha256_map(_archived_manifest(), _members())
        for rel in UNDIGESTED:
            assert not any(rel in p for p in problems), (
                f"{rel} carries no digest and is not reported as a problem. "
                f"If this ever starts failing, load-time verification has "
                f"gained a completeness check and this test should become "
                f"the assertion that it works."
            )

    def test_the_export_path_can_no_longer_omit_them(self, tmp_path):
        """The half F-05 does fix: every member the stage writes gets a
        digest, so a bundle of this shape cannot be produced again."""
        src = tmp_path / "in.zip"
        manifest = _archived_manifest()
        with zipfile.ZipFile(src, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            for rel, body in _members().items():
                zf.writestr(rel, body)

        out = tmp_path / "out.zip"
        with zipfile.ZipFile(src, "r") as zf_in:
            written = _write_llm_stage_bundle(
                str(out), zf_in, root="", manifest=manifest, stage="EL",
                reports_dir_rel="reports", cache_rel="cache/EL_cache.jsonl",
                parse_header=["local_id", "title", "abstract", "keywords"],
                survivors=[{"local_id": "A001", "title": "T",
                            "abstract": "A", "keywords": "K"}],
                full_rows=[{"local_id": "A001", "el_outcome": "PASS_CLEAN"}],
                full_header=["local_id", "el_outcome"],
                skipped=[], counts={"OUT": 0, "PASS_CLEAN": 1},
                cache_text='{"key": "k", "val": {}}\n',
            )

        with zipfile.ZipFile(out, "r") as zf:
            new_manifest = json.loads(zf.read("manifest.json"))
            members = {n: zf.read(n) for n in zf.namelist()}

        for rel in ("data/current.csv", "reports/EL_FULL.csv",
                    "reports/EL_SURVIVORS.csv", "cache/EL_cache.jsonl"):
            assert rel in written
            assert rel in new_manifest["sha256"], (
                f"F-05: {rel} was written by the stage but carries no digest."
            )

        # and the bundle now passes its own verification end to end
        assert _verify_sha256_map(new_manifest, members) == []


# ---------------------------------------------------------------------------
# 3. the missing history entry — now written
# ---------------------------------------------------------------------------

class TestHistoryEntry:

    def test_el_now_appends_one(self, tmp_path):
        src = tmp_path / "in.zip"
        manifest = _archived_manifest()
        assert manifest["pipeline"]["history"] == []  # as archived
        with zipfile.ZipFile(src, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            for rel, body in _members().items():
                zf.writestr(rel, body)

        out = tmp_path / "out.zip"
        with zipfile.ZipFile(src, "r") as zf_in:
            _write_llm_stage_bundle(
                str(out), zf_in, root="", manifest=manifest, stage="EL",
                reports_dir_rel="reports", cache_rel="cache/EL_cache.jsonl",
                parse_header=["local_id"], survivors=[{"local_id": "A001"}],
                full_rows=[{"local_id": "A001"}], full_header=["local_id"],
                skipped=[], counts={"OUT": 0, "PASS_CLEAN": 1},
            )

        with zipfile.ZipFile(out, "r") as zf:
            history = json.loads(zf.read("manifest.json"))["pipeline"]["history"]
        assert len(history) == 1
        assert history[0]["stage"] == "EL"
        assert history[0]["counts"] == {"OUT": 0, "PASS_CLEAN": 1}
        assert history[0]["not_screened"] is False


# ---------------------------------------------------------------------------
# 4. the two contradicting stage maps — F-27, still open
# ---------------------------------------------------------------------------

class TestDivergentStageMaps:

    def test_the_archived_contradiction_is_not_reconciled(self, tmp_path):
        """F-27 was out of scope for wave 2 and remains so. The archived
        bundle says EL is done in ``pipeline_state.stages`` and does not
        mention EL in ``pipeline.stages`` at all; nothing in the current
        code reconciles the two maps or reports the disagreement."""
        manifest = _archived_manifest()
        assert manifest["pipeline_state"]["stages"].get("EL") == "done"
        assert "EL" not in manifest["pipeline"]["stages"]

        src = tmp_path / "in.zip"
        with zipfile.ZipFile(src, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            for rel, body in _members().items():
                zf.writestr(rel, body)
        out = tmp_path / "out.zip"
        with zipfile.ZipFile(src, "r") as zf_in:
            _write_llm_stage_bundle(
                str(out), zf_in, root="", manifest=manifest, stage="EL",
                reports_dir_rel="reports", cache_rel="cache/EL_cache.jsonl",
                parse_header=["local_id"], survivors=[{"local_id": "A001"}],
                full_rows=[{"local_id": "A001"}], full_header=["local_id"],
                skipped=[], counts={"OUT": 0},
                not_screened=True,
            )
        with zipfile.ZipFile(out, "r") as zf:
            m = json.loads(zf.read("manifest.json"))

        # The shared writer maintains pipeline.stages only. pipeline_state is
        # left exactly as it was found, so a no-op stage is recorded as
        # "not_screened" in one map and "done" in the other — the same class
        # of divergence F-27 describes, reachable through the new code.
        assert m["pipeline"]["stages"]["EL"] == "not_screened"
        assert m["pipeline_state"]["stages"]["EL"] == "done"
