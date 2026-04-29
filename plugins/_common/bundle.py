# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
plugins/_common/bundle.py — shared bundle IO for EH/IH.

Owns:
  - BundleInfo dataclass: in-memory representation of a screening bundle
    (manifest, criteria CSV bytes, current.csv bytes, optional input
    errors, root path inside zip).

  - Bundle-zip readers (pure, no stage dependency):
      _detect_bundle_root: find the common root prefix inside the zip.
      _read_zip_bytes:     read a single member as bytes.
      _find_first_member:  resolve a logical path under the bundle root
                           against a list of candidate file names.
      _load_bundle:        open a bundle zip and emit a BundleInfo.

  - Bundle-zip writer (stage-parametrized):
      _export_next_bundle_zip: write the next-stage bundle zip with
        data/current.csv replaced by survivors, plus reports/{stage}_FULL.csv
        and reports/{stage}_SURVIVORS.csv. Manifest's pipeline + history are
        updated for the stage that just ran. Calls _export_xlsx and
        _write_csv_bytes from plugins._common.exporters.

The bundle helpers are character-identical between EH and IH; only
_export_next_bundle_zip carries six stage-specific literals (report
file names, full-report column prefix, manifest stage marker, history
entry stage, created_by tag), all parametrized over a `stage` argument.

Pulled-in from plugins._common.parser:
  - _safe_str, _decode_bytes, _sha256_hex, _iso_now.
Pulled-in from plugins._common.exporters:
  - _export_xlsx, _write_csv_bytes.

Consumed by:
  - plugins/04_eh/plugin.py  (called from EHView export actions)
  - plugins/05_ih/plugin.py  (same)
"""
import csv
import io
import json
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from plugins._common.parser import (
    _decode_bytes,
    _iso_now,
    _safe_str,
    _sha256_hex,
)
from plugins._common.exporters import (
    _export_xlsx,
    _write_csv_bytes,
)


class BundleInfo:
    zip_path: str
    root: str                       # e.g. "ScreenA_Bundle/" or ""
    manifest: Dict[str, Any]
    members: List[str]


# ----------------------------
# Bundle IO
# ----------------------------

def _detect_bundle_root(members: Sequence[str]) -> str:
    """
    Determine bundle root prefix. Supports:
      - manifest.json at zip root
      - <folder>/manifest.json
    """
    if "manifest.json" in members:
        return ""
    for pref in ("ScreenA_Bundle/", "screenA_bundle/", "bundle/", "ScreenA/"):
        if pref + "manifest.json" in members:
            return pref
    for m in members:
        if m.endswith("/manifest.json"):
            return m[:-len("manifest.json")]
    return ""


def _read_zip_bytes(zf: zipfile.ZipFile, name: str) -> bytes:
    try:
        return zf.read(name)
    except KeyError:
        raise FileNotFoundError(f"Missing required file in bundle: {name}")


def _find_first_member(zf: zipfile.ZipFile, root: str, rel_candidates: Sequence[str]) -> Tuple[str, str]:
    """
    Returns (member_name_in_zip, rel_path_used)
      - member_name_in_zip includes root prefix
      - rel_path_used is the relative path without root
    """
    nameset = set(zf.namelist())
    for rel in rel_candidates:
        full = root + rel
        if full in nameset:
            return full, rel
    raise FileNotFoundError(f"None of these files were found in bundle: {', '.join(rel_candidates)}")


def _load_bundle(zip_path: str) -> BundleInfo:
    if not zip_path.lower().endswith(".zip"):
        raise ValueError("Bundle must be a .zip file.")
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()
        root = _detect_bundle_root(members)

        manifest_full = root + "manifest.json"
        if manifest_full not in members:
            raise FileNotFoundError("Bundle missing manifest.json")

        manifest_bytes = _read_zip_bytes(zf, manifest_full)
        try:
            manifest = json.loads(_decode_bytes(manifest_bytes))
        except Exception as e:
            raise ValueError(f"manifest.json is not valid JSON: {e}")

        if not isinstance(manifest, dict):
            raise ValueError("manifest.json must be a JSON object.")

        return BundleInfo(zip_path=zip_path, root=root, manifest=manifest, members=members)

def _export_next_bundle_zip(
    out_zip_path: str,
    bundle: BundleInfo,
    data_rel: str,
    criteria_rel: str,
    input_errors_rel: Optional[str],
    parse_header: List[str],
    full_rows: List[Dict[str, str]],
    survivors: List[Dict[str, str]],
    skipped: List[Tuple[int, str, str]],
    counts: Dict[str, int],
    *,
    stage: str,
) -> None:
    """
    Create a new bundle zip where data/current.csv becomes the {stage} survivors.
    Keeps other files from the input bundle, updates manifest pipeline + sha256 (warn-only downstream).
    Adds reports/{stage}_FULL.csv and reports/{stage}_SURVIVORS.csv.
    """
    sl = stage.lower()
    root = bundle.root
    src_zip = bundle.zip_path

    manifest_rel = "manifest.json"
    rep_full_rel = f"reports/{stage}_FULL.csv"
    rep_surv_rel = f"reports/{stage}_SURVIVORS.csv"

    # Always write survivors to the canonical location (data/current.csv) for downstream stages
    out_data_rel = "data/current.csv"

    current_bytes = _write_csv_bytes(parse_header, survivors)
    rep_full_bytes = _write_csv_bytes(
        parse_header + [f"{sl}_outcome", f"{sl}_failed_ids", f"{sl}_missing_ids", f"{sl}_met_ids", f"{sl}_reason_summary"],
        full_rows
    )
    rep_surv_bytes = current_bytes

    input_errors_bytes = None
    if skipped:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["record_index_ex_header", "reason", "raw_record"])
        for rec_i, reason, raw in skipped:
            w.writerow([rec_i, reason, raw])
        input_errors_bytes = buf.getvalue().encode("utf-8")

    # Update manifest
    m = dict(bundle.manifest)
    pipeline = dict(m.get("pipeline", {}) or {})
    stages = dict(pipeline.get("stages", {}) or {})
    history = list(pipeline.get("history", []) or [])

    stages[stage] = "done"
    history.append({
        "stage": stage,
        "ran_at": _iso_now(),
        "counts": counts,
        "survivors_rows": len(survivors),
        "out_rows_full": len(full_rows),
    })
    pipeline["stages"] = stages
    pipeline["history"] = history
    m["pipeline"] = pipeline

    m["created_at"] = datetime.now().replace(microsecond=0).isoformat()
    m["created_by"] = f"screen_a_{sl}_plugin"
    m.setdefault("derived_from", {})
    try:
        m["derived_from"]["zip_name"] = Path(src_zip).name
    except Exception:
        pass

    # Refresh sha256 map (only for files we overwrite/add)
    sha_map = dict(m.get("sha256", {}) or {})
    sha_map[out_data_rel] = _sha256_hex(current_bytes)
    sha_map[rep_full_rel] = _sha256_hex(rep_full_bytes)
    sha_map[rep_surv_rel] = _sha256_hex(rep_surv_bytes)
    if input_errors_bytes is not None:
        sha_map["data/input_errors.csv"] = _sha256_hex(input_errors_bytes)
    m["sha256"] = sha_map

    manifest_bytes = (json.dumps(m, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    # Copy everything except entries we overwrite
    overwrite_set = {
        root + manifest_rel,
        root + out_data_rel,
        root + rep_full_rel,
        root + rep_surv_rel,
        root + "data/input_errors.csv",
    }

    with zipfile.ZipFile(src_zip, "r") as zin, zipfile.ZipFile(out_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            if name in overwrite_set:
                continue
            data = zin.read(name)
            zout.writestr(name, data)

        zout.writestr(root + manifest_rel, manifest_bytes)
        zout.writestr(root + out_data_rel, current_bytes)
        zout.writestr(root + rep_full_rel, rep_full_bytes)
        zout.writestr(root + rep_surv_rel, rep_surv_bytes)
        if input_errors_bytes is not None:
            zout.writestr(root + "data/input_errors.csv", input_errors_bytes)
