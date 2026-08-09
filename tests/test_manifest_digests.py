
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_manifest_digests.py — F-05: EL and IL never refreshed the SHA-256 map,
so the bundles they wrote asserted digests for files they had replaced.

The string ``sha`` appeared zero times in 06_el/ui.py, 07_il/ui.py and both
standalone.py — yet all four overwrite ``data/current.csv`` with the stage's
survivors on export. The manifest leaving EL therefore named a digest for a
file whose contents EL had just changed, and nothing downstream checked, so
the manifest asserted something false and no one found out.

That is worse than having no digest at all. A digest that is present and
wrong converts an integrity check into a source of false assurance: a
reviewer who verifies the bundle and sees a matching manifest has learned
nothing, and one who sees a mismatch cannot tell tampering from this bug.

Two halves, both tested here:
  - export refreshes the digest of every member it writes;
  - load verifies the digests and surfaces a mismatch instead of ignoring it.
"""
import json
import zipfile
from hashlib import sha256
from pathlib import Path

import pytest

from conftest import get_el, get_il

from plugins._common.bundle import (
    BundleInfo,
    _export_next_bundle_zip,
    _refresh_sha256_map,
    _verify_sha256_map,
    _write_llm_stage_bundle,
)


def _sha(b: bytes) -> str:
    return sha256(b).hexdigest()


# ---------------------------------------------------------------------------
# the shared helpers
# ---------------------------------------------------------------------------

class TestRefreshHelper:

    def test_updates_written_members_and_leaves_others_alone(self):
        manifest = {"sha256": {"data/current.csv": "stale",
                               "criteria/c.csv": "untouched"}}
        out = _refresh_sha256_map(manifest, {"data/current.csv": b"new bytes"})
        assert out["sha256"]["data/current.csv"] == _sha(b"new bytes")
        assert out["sha256"]["criteria/c.csv"] == "untouched"

    def test_adds_members_that_had_no_entry(self):
        out = _refresh_sha256_map({}, {"reports/EL_FULL.csv": b"x"})
        assert out["sha256"]["reports/EL_FULL.csv"] == _sha(b"x")

    def test_does_not_mutate_the_input(self):
        manifest = {"sha256": {"a": "1"}}
        _refresh_sha256_map(manifest, {"a": b"z"})
        assert manifest["sha256"]["a"] == "1"


class TestVerifyHelper:

    def test_silent_when_everything_matches(self):
        m = {"sha256": {"data/current.csv": _sha(b"body")}}
        assert _verify_sha256_map(m, {"data/current.csv": b"body"}) == []

    def test_reports_a_mismatch(self):
        m = {"sha256": {"data/current.csv": _sha(b"body")}}
        problems = _verify_sha256_map(m, {"data/current.csv": b"tampered"})
        assert len(problems) == 1
        assert "data/current.csv" in problems[0]
        assert "sha256" in problems[0].lower()

    def test_members_with_no_recorded_digest_are_not_a_mismatch(self):
        assert _verify_sha256_map({"sha256": {}}, {"a": b"x"}) == []

    def test_missing_or_malformed_map_does_not_raise(self):
        assert _verify_sha256_map({}, {"a": b"x"}) == []
        assert _verify_sha256_map({"sha256": "not a dict"}, {"a": b"x"}) == []


# ---------------------------------------------------------------------------
# EH/IH keep working through the same helper
# ---------------------------------------------------------------------------

def _seed(tmp_path, extra=None):
    zp = tmp_path / "in.zip"
    manifest = {"pipeline": {"stages": {}, "history": []},
                "sha256": {"data/current.csv": "deliberately-stale",
                           "criteria/c.csv": _sha(b"crit")}}
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("data/current.csv", "local_id,title\nA001,old\n")
        zf.writestr("criteria/c.csv", "crit")
        for name, body in (extra or {}).items():
            zf.writestr(name, body)
    return BundleInfo(zip_path=str(zp), root="", manifest=manifest, members=[])


def _members(zip_path):
    with zipfile.ZipFile(zip_path, "r") as zf:
        return {n: zf.read(n) for n in zf.namelist()}


class TestEHIHExportDigests:

    def test_every_written_member_matches_its_digest(self, tmp_path):
        out = tmp_path / "out.zip"
        _export_next_bundle_zip(
            str(out), _seed(tmp_path), "data/current.csv", "criteria/c.csv",
            None, ["local_id", "title"], [{"local_id": "A001", "title": "x"}],
            [{"local_id": "A001", "title": "x"}], [], {"OUT": 0}, stage="EH")

        members = _members(out)
        recorded = json.loads(members["manifest.json"])["sha256"]
        assert _verify_sha256_map({"sha256": recorded}, members) == []
        assert recorded["data/current.csv"] != "deliberately-stale"


# ---------------------------------------------------------------------------
# EL/IL — the finding
# ---------------------------------------------------------------------------

def _el_il_bundle(mod, tmp_path, stage):
    """A bundle the EL/IL loader will accept, with a deliberately stale
    digest for data/current.csv."""
    zp = tmp_path / f"{stage}_in.zip"
    body = b"local_id,title,abstract,keywords\nA001,T,A,K\nA002,T2,A2,K2\n"
    crit = b"stage,id,type,scope,label,operator,target,what,threshold,enabled,source_text\n"
    manifest = {"pipeline": {"stages": {}, "history": []},
                "sha256": {"data/current.csv": "deliberately-stale"}}
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("data/current.csv", body)
        zf.writestr("criteria/criteria_harmonized.csv", crit)
    return zp


def _build_next(mod, zp, out_zip, stage):
    """Drive the shared LLM-stage writer with the arguments the EL/IL views
    pass it.

    ELView/ILView cannot be instantiated here — ttk.Frame is a MagicMock
    under conftest — but the export logic no longer lives in the view. Both
    views and both standalone shells delegate to this one function, which is
    the code under test.
    """
    sl = stage.lower()
    bundle = mod._load_bundle(str(zp))
    header = list(bundle.parse.header)
    if "local_id" not in header:
        header = ["local_id"] + header
    header_full = [
        *header,
        f"{sl}_outcome", f"{sl}_failed_ids", f"{sl}_missing_ids",
        f"{sl}_met_ids", f"{sl}_uncertain_ids", f"{sl}_reason_summary",
        f"{sl}_evidence_json",
    ]
    with zipfile.ZipFile(bundle.zip_path, "r") as zf_in:
        _write_llm_stage_bundle(
            str(out_zip), zf_in,
            root=bundle.root,
            manifest=dict(bundle.manifest),
            stage=stage,
            reports_dir_rel="reports",
            cache_rel=f"cache/{stage}_cache.jsonl",
            parse_header=header,
            survivors=[dict(r) for r in bundle.parse.rows],
            full_rows=[dict(r, **{f"{sl}_outcome": "PASS_CLEAN"})
                       for r in bundle.parse.rows],
            full_header=header_full,
            skipped=bundle.parse.skipped,
            cache_text=None,
        )
    return bundle


@pytest.mark.parametrize("stage", ["EL", "IL"])
def test_el_il_export_refreshes_every_digest(tmp_path, stage):
    mod = get_el() if stage == "EL" else get_il()
    zp = _el_il_bundle(mod, tmp_path, stage)
    out = tmp_path / f"{stage}_out.zip"
    _build_next(mod, zp, out, stage)

    members = _members(out)
    recorded = json.loads(members["manifest.json"])["sha256"]

    assert recorded.get("data/current.csv") != "deliberately-stale", (
        f"F-05: {stage} overwrote data/current.csv with its survivors and "
        f"left the manifest asserting the digest of the file it replaced. "
        f"The manifest actively asserts something false."
    )
    problems = _verify_sha256_map({"sha256": recorded}, members)
    assert problems == [], f"F-05: {stage} bundle fails its own digests: {problems}"


@pytest.mark.parametrize("stage", ["EL", "IL"])
def test_el_il_records_digests_for_the_reports_it_writes(tmp_path, stage):
    mod = get_el() if stage == "EL" else get_il()
    zp = _el_il_bundle(mod, tmp_path, stage)
    out = tmp_path / f"{stage}_out.zip"
    _build_next(mod, zp, out, stage)

    recorded = json.loads(_members(out)["manifest.json"])["sha256"]
    assert f"reports/{stage}_FULL.csv" in recorded
    assert f"reports/{stage}_SURVIVORS.csv" in recorded


# ---------------------------------------------------------------------------
# load-time verification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stage", ["EL", "IL"])
def test_tampered_current_csv_is_surfaced_at_load(tmp_path, stage):
    """Round trip: export, tamper with data/current.csv, load the result and
    assert the next stage says so rather than screening the altered corpus in
    silence."""
    mod = get_el() if stage == "EL" else get_il()
    zp = _el_il_bundle(mod, tmp_path, stage)
    out = tmp_path / f"{stage}_out.zip"
    _build_next(mod, zp, out, stage)

    # A clean reload must be quiet about digests.
    clean = mod._load_bundle(str(out))
    assert not [w for w in clean.criteria.warnings if "sha256" in w.lower()]

    tampered = tmp_path / f"{stage}_tampered.zip"
    members = _members(out)
    members["data/current.csv"] = b"local_id,title,abstract,keywords\nA999,X,Y,Z\n"
    with zipfile.ZipFile(tampered, "w") as zf:
        for name, body in members.items():
            zf.writestr(name, body)

    loaded = mod._load_bundle(str(tampered))
    warns = [w for w in loaded.criteria.warnings if "sha256" in w.lower()]
    assert warns, (
        f"F-05: {stage} loaded a bundle whose data/current.csv no longer "
        f"matches the digest its own manifest records, and said nothing. "
        f"Nothing downstream checked, which is why the stale digests EL "
        f"wrote went unnoticed."
    )
    assert "data/current.csv" in warns[0]
