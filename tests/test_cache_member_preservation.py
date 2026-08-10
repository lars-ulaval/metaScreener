
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_cache_member_preservation.py — F-104: exporting with "Use cache"
unticked must not delete the bundle's existing cache.

``_write_llm_stage_bundle`` copies the incoming bundle forward member by
member, skipping the ones it is about to write itself. It added the cache
member to that skip set *unconditionally* — but it only writes a cache
member when ``cache_text`` is not None, which is exactly when the user
ticked "Use cache". Untick the box and the incoming cache is excluded from
the copy loop and nothing is written in its place, so the accumulated cache
is gone. Silently: no warning, no manifest note, and the run that discarded
it looks like every other successful export.

The audit trail comes off worse than the bill. ``_refresh_sha256_map`` only
updates entries for members it wrote, so the manifest keeps its digest for
the member that is no longer there, and ``_verify_sha256_map`` iterates the
members that *are* present, so it cannot see the absence. The bundle then
asserts a digest for a file it does not contain and reports itself intact —
F-05's failure mode arriving through a different door. That second half is
not fixed here; it is a general defect of the digest map rather than of this
writer, and is recorded as its own register row.

The fix is one condition: skip the cache member only when it is actually
being written.
"""
import json
import zipfile
from hashlib import sha256

import pytest

from plugins._common.bundle import _verify_sha256_map, _write_llm_stage_bundle


STAGES = [("EL", "cache/EL_cache.jsonl"), ("IL", "cache/IL_cache.jsonl")]
STAGE_IDS = ["el", "il"]

EXISTING_CACHE = (
    '{"key": "aaa", "val": {"used": true, "decision": "not_meet"}}\n'
    '{"key": "bbb", "val": {"used": true, "decision": "meet"}}\n'
).encode("utf-8")

HEADER = ["local_id", "title", "abstract", "keywords"]
ROWS = [{"local_id": "A001", "title": "T", "abstract": "A", "keywords": "K"}]


def _sha(b: bytes) -> str:
    return sha256(b).hexdigest()


def _seed(tmp_path, cache_rel, *, root="", name="in.zip"):
    """An incoming bundle that already carries an accumulated cache, with a
    manifest that records its digest correctly."""
    zp = tmp_path / name
    current = b"local_id,title,abstract,keywords\nA001,T,A,K\n"
    manifest = {
        "pipeline": {"stages": {}, "history": []},
        "sha256": {
            "data/current.csv": _sha(current),
            cache_rel: _sha(EXISTING_CACHE),
        },
    }
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr(root + "manifest.json", json.dumps(manifest))
        zf.writestr(root + "data/current.csv", current)
        zf.writestr(root + "criteria/criteria_harmonized.csv", b"stage,id\n")
        zf.writestr(root + cache_rel, EXISTING_CACHE)
    return zp, manifest


def _export(zp, out_zip, *, stage, cache_rel, manifest, root="",
            cache_text=None):
    with zipfile.ZipFile(zp, "r") as zf_in:
        return _write_llm_stage_bundle(
            str(out_zip), zf_in,
            root=root,
            manifest=dict(manifest),
            stage=stage,
            reports_dir_rel="reports",
            cache_rel=cache_rel,
            parse_header=HEADER,
            survivors=ROWS,
            full_rows=[dict(ROWS[0], **{f"{stage.lower()}_outcome": "PASS_CLEAN"})],
            full_header=HEADER + [f"{stage.lower()}_outcome"],
            skipped=[],
            cache_text=cache_text,
        )


def _members(zip_path):
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert len(names) == len(set(names)), f"duplicate members: {names}"
        return {n: zf.read(n) for n in names}


# ---------------------------------------------------------------------------
# the finding
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stage,cache_rel", STAGES, ids=STAGE_IDS)
class TestCacheSurvivesAnExportThatDoesNotWriteOne:

    def test_the_incoming_cache_is_carried_forward_untouched(
            self, tmp_path, stage, cache_rel):
        zp, manifest = _seed(tmp_path, cache_rel)
        out = tmp_path / "out.zip"
        _export(zp, out, stage=stage, cache_rel=cache_rel, manifest=manifest,
                cache_text=None)

        members = _members(out)
        assert cache_rel in members, (
            f"F-104: {stage} exported with no cache text and the incoming "
            f"{cache_rel} was dropped from the bundle. An accumulated cache "
            f"that cost real money is gone, with no warning and no manifest "
            f"note. Members: {sorted(members)}"
        )
        assert members[cache_rel] == EXISTING_CACHE, (
            "the cache member survived but its bytes changed"
        )

    def test_the_manifest_does_not_assert_a_digest_for_an_absent_member(
            self, tmp_path, stage, cache_rel):
        """The reason this is High rather than an annoyance: the sha256 map
        keeps its entry either way, so dropping the member leaves the bundle
        asserting a digest for a file it does not contain."""
        zp, manifest = _seed(tmp_path, cache_rel)
        out = tmp_path / "out.zip"
        _export(zp, out, stage=stage, cache_rel=cache_rel, manifest=manifest,
                cache_text=None)

        members = _members(out)
        recorded = json.loads(members["manifest.json"])["sha256"]
        claimed_but_absent = [rel for rel in recorded if rel not in members]
        assert claimed_but_absent == [], (
            f"F-104: the manifest records digests for members the bundle no "
            f"longer contains: {claimed_but_absent}. _verify_sha256_map "
            f"iterates the members that are present, so it reports the "
            f"bundle intact."
        )
        assert _verify_sha256_map({"sha256": recorded}, members) == []

    def test_a_supplied_cache_still_replaces_the_old_one(
            self, tmp_path, stage, cache_rel):
        """The other half of the condition: when the box *is* ticked the new
        cache must replace the old one, not sit beside it."""
        zp, manifest = _seed(tmp_path, cache_rel)
        out = tmp_path / "out.zip"
        new_text = '{"key": "ccc", "val": {"used": true, "decision": "meet"}}\n'
        _export(zp, out, stage=stage, cache_rel=cache_rel, manifest=manifest,
                cache_text=new_text)

        members = _members(out)          # asserts no duplicate members
        assert members[cache_rel] == new_text.encode("utf-8")
        recorded = json.loads(members["manifest.json"])["sha256"]
        assert recorded[cache_rel] == _sha(new_text.encode("utf-8"))
        assert _verify_sha256_map({"sha256": recorded}, members) == []

    def test_an_empty_cache_text_is_still_a_cache_the_user_asked_to_write(
            self, tmp_path, stage, cache_rel):
        """"" is not None. A run that produced no cache entries but was told
        to write the cache should write an empty one, replacing what was
        there — that is a deliberate reset, unlike the unticked box."""
        zp, manifest = _seed(tmp_path, cache_rel)
        out = tmp_path / "out.zip"
        _export(zp, out, stage=stage, cache_rel=cache_rel, manifest=manifest,
                cache_text="")

        members = _members(out)
        assert members[cache_rel] == b""
        recorded = json.loads(members["manifest.json"])["sha256"]
        assert recorded[cache_rel] == _sha(b"")

    def test_it_holds_under_a_bundle_root_prefix(self, tmp_path, stage,
                                                 cache_rel):
        """Bundles arrive both flat and inside a single top folder; the skip
        set is built with the root prefix, so both need covering."""
        root = "ScreenA_Bundle/"
        zp, manifest = _seed(tmp_path, cache_rel, root=root)
        out = tmp_path / "out.zip"
        _export(zp, out, stage=stage, cache_rel=cache_rel, manifest=manifest,
                root=root, cache_text=None)

        members = _members(out)
        assert root + cache_rel in members
        assert members[root + cache_rel] == EXISTING_CACHE

    def test_a_bundle_with_no_incoming_cache_is_unaffected(
            self, tmp_path, stage, cache_rel):
        """Nothing to preserve, nothing to write: the member must simply be
        absent rather than appearing empty."""
        zp = tmp_path / "bare.zip"
        current = b"local_id,title,abstract,keywords\nA001,T,A,K\n"
        manifest = {"pipeline": {"stages": {}, "history": []}, "sha256": {}}
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("data/current.csv", current)
            zf.writestr("criteria/criteria_harmonized.csv", b"stage,id\n")

        out = tmp_path / "out.zip"
        _export(zp, out, stage=stage, cache_rel=cache_rel, manifest=manifest,
                cache_text=None)

        members = _members(out)
        assert cache_rel not in members
        recorded = json.loads(members["manifest.json"])["sha256"]
        assert cache_rel not in recorded
