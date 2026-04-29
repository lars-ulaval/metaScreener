# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_bundle_integrity.py — Tests for bundle ZIP structure and SHA-256 integrity.

Verifies:
  - A minimal bundle ZIP can be created with required structure
  - SHA-256 hash computation is correct and deterministic
  - manifest.json structure conforms to expected schema
"""
import csv
import io
import json
import tempfile
import zipfile
from hashlib import sha256
from pathlib import Path

import pytest


# ======================================================================
# Bundle creation helpers
# ======================================================================

def _make_minimal_bundle(tmp_path: Path) -> Path:
    """Create a minimal ScreenA_Bundle ZIP with required contents."""
    zip_path = tmp_path / "test_bundle.zip"

    manifest = {
        "bundle_schema": "screenA_bundle_v1",
        "created_at": "2026-03-15T12:00:00Z",
        "created_by": "harmoniser",
        "inputs": {
            "aggregate_filename": "aggregate.csv",
            "criteria_filename": "ic_ec_12.txt",
            "criteria_kind": "free_text",
        },
        "aggregate": {
            "columns": ["local_id", "title", "abstract", "year", "lang", "venue"],
            "id_column_guess": "local_id",
            "rows_total_read": 3,
            "rows_valid_written": 3,
            "rows_invalid_skipped": 0,
        },
        "criteria": {
            "rows_total": 4,
            "rows_by_stage": {"EH": 1, "IH": 1, "EL": 1, "IL": 1},
            "enabled_by_stage": {"EH": 1, "IH": 1, "EL": 1, "IL": 1},
        },
        "pipeline_state": {
            "stages": {"EH": "not_run", "IH": "not_run", "EL": "not_run", "IL": "not_run"},
            "history": [],
        },
        "warnings": [],
    }

    # Build current.csv content
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(["local_id", "title", "abstract", "year", "lang", "venue"])
    writer.writerow(["rec_001", "VR Rehab Study", "We study VR.", "2021", "en", "Nature"])
    writer.writerow(["rec_002", "AR Navigation", "AR for wayfinding.", "2019", "en", "IEEE VR"])
    writer.writerow(["rec_003", "Étude française", "Résumé en français.", "2022", "fr", "Revue"])
    csv_text = csv_buf.getvalue()

    # Build criteria_harmonized.csv
    crit_buf = io.StringIO()
    cw = csv.writer(crit_buf)
    cw.writerow(["id", "type", "stage", "scope", "label", "operator", "target", "what", "threshold", "enabled", "source_text"])
    cw.writerow(["EC-1", "exclude", "EH", "metadata", "Non-English", "equals", "lang", "fr", "", "True", "Non-English papers"])
    cw.writerow(["IC-3", "include", "IH", "metadata", "Year >= 2018", "gte", "year", "2018", "", "True", "Year 2018+"])
    cw.writerow(["EC-2", "exclude", "EL", "metadata", "Maze navigation", "llm", "abstract", "spatial navigation maze", "0.6", "True", "Maze focus"])
    cw.writerow(["IC-1", "include", "IL", "metadata", "HMD VR", "llm", "abstract", "head-mounted display VR", "0.6", "True", "HMD VR"])
    crit_text = crit_buf.getvalue()

    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ScreenA_Bundle/manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("ScreenA_Bundle/data/current.csv", csv_text)
        zf.writestr("ScreenA_Bundle/criteria/criteria_harmonized.csv", crit_text)

    return zip_path


# ======================================================================
# Tests
# ======================================================================

class TestBundleZIPStructure:

    def test_bundle_has_required_files(self, tmp_path):
        """Bundle must contain manifest.json, data/current.csv."""
        zip_path = _make_minimal_bundle(tmp_path)
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            names = zf.namelist()
            assert "ScreenA_Bundle/manifest.json" in names
            assert "ScreenA_Bundle/data/current.csv" in names
            assert "ScreenA_Bundle/criteria/criteria_harmonized.csv" in names

    def test_manifest_is_valid_json(self, tmp_path):
        zip_path = _make_minimal_bundle(tmp_path)
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            manifest_bytes = zf.read("ScreenA_Bundle/manifest.json")
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            assert isinstance(manifest, dict)

    def test_manifest_has_required_keys(self, tmp_path):
        zip_path = _make_minimal_bundle(tmp_path)
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            manifest = json.loads(zf.read("ScreenA_Bundle/manifest.json"))
            required_keys = {"bundle_schema", "created_at", "created_by",
                             "inputs", "aggregate", "criteria", "pipeline_state"}
            assert required_keys.issubset(manifest.keys())

    def test_manifest_bundle_schema(self, tmp_path):
        zip_path = _make_minimal_bundle(tmp_path)
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            manifest = json.loads(zf.read("ScreenA_Bundle/manifest.json"))
            assert manifest["bundle_schema"] == "screenA_bundle_v1"

    def test_manifest_pipeline_stages(self, tmp_path):
        zip_path = _make_minimal_bundle(tmp_path)
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            manifest = json.loads(zf.read("ScreenA_Bundle/manifest.json"))
            stages = manifest["pipeline_state"]["stages"]
            for s in ("EH", "IH", "EL", "IL"):
                assert s in stages

    def test_current_csv_roundtrip(self, tmp_path):
        """CSV inside the bundle can be read back correctly."""
        zip_path = _make_minimal_bundle(tmp_path)
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            csv_text = zf.read("ScreenA_Bundle/data/current.csv").decode("utf-8")
            reader = csv.DictReader(io.StringIO(csv_text))
            rows = list(reader)
            assert len(rows) == 3
            assert rows[0]["local_id"] == "rec_001"
            assert rows[2]["lang"] == "fr"


class TestSHA256Integrity:

    def test_hash_deterministic(self):
        data = b"metaScreener bundle content"
        h1 = sha256(data).hexdigest()
        h2 = sha256(data).hexdigest()
        assert h1 == h2

    def test_hash_changes_on_modification(self):
        data_a = b"original content"
        data_b = b"modified content"
        assert sha256(data_a).hexdigest() != sha256(data_b).hexdigest()

    def test_bundle_zip_hash_deterministic(self, tmp_path):
        """Reading the same ZIP twice → same hash."""
        zip_path = _make_minimal_bundle(tmp_path)
        content = zip_path.read_bytes()
        h1 = sha256(content).hexdigest()
        h2 = sha256(content).hexdigest()
        assert h1 == h2
        assert len(h1) == 64

    def test_bundle_modification_detected(self, tmp_path):
        """Altering bundle content changes the hash."""
        zip_path = _make_minimal_bundle(tmp_path)
        h_original = sha256(zip_path.read_bytes()).hexdigest()

        # Create a second bundle with different data
        zip_path2 = tmp_path / "test_bundle_mod.zip"
        with zipfile.ZipFile(str(zip_path), "r") as zf_in:
            with zipfile.ZipFile(str(zip_path2), "w") as zf_out:
                for item in zf_in.namelist():
                    data = zf_in.read(item)
                    if item.endswith("current.csv"):
                        data = data.replace(b"rec_001", b"rec_999")
                    zf_out.writestr(item, data)

        h_modified = sha256(zip_path2.read_bytes()).hexdigest()
        assert h_original != h_modified

class TestBundleLoader:
    """Regression tests for plugins/_common/bundle.py public surface.

    Guards against @dataclass-decorator omission during refactor extraction.
    The original such regression: Conv 5 / Commit 4 (e84b796) extracted
    BundleInfo from plugins/04_eh/plugin.py into _common/bundle.py but the
    extraction regex started one line below the @dataclass decorator,
    silently dropping it. Test_bundle_integrity.py only inspected raw zip
    structure and SHA-256 — it never instantiated BundleInfo or called
    _load_bundle, so the bug surfaced only via GUI smoke during Commit 7.
    These two tests close that gap.
    """

    def test_bundle_info_accepts_keyword_arguments(self):
        """BundleInfo must be a real dataclass (kwargs constructor)."""
        from plugins._common.bundle import BundleInfo
        b = BundleInfo(zip_path="/x", root="r/", manifest={}, members=[])
        assert b.zip_path == "/x"
        assert b.root == "r/"
        assert b.manifest == {}
        assert b.members == []

    def test_load_bundle_returns_populated_bundle_info(self, tmp_path):
        """_load_bundle on a real ZIP returns a populated BundleInfo instance."""
        from plugins._common.bundle import _load_bundle, BundleInfo
        zip_path = _make_minimal_bundle(tmp_path)
        bundle = _load_bundle(str(zip_path))
        assert isinstance(bundle, BundleInfo)
        assert bundle.zip_path == str(zip_path)
        assert bundle.root == "ScreenA_Bundle/"
        assert isinstance(bundle.manifest, dict)
        assert "ScreenA_Bundle/manifest.json" in bundle.members

