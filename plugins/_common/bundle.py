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
from plugins._common.input_errors import (
    from_tuple_skipped,
    merge_input_errors_csv,
    read_input_errors,
)


@dataclass
class BundleInfo:
    zip_path: str
    root: str                       # e.g. "ScreenA_Bundle/" or ""
    manifest: Dict[str, Any]
    members: List[str]


# ----------------------------
# Export gate
# ----------------------------

CANCELLED_EXPORT_REASON = (
    "This run was cancelled before it reached the end of the corpus, so the "
    "results cover only part of it.\n\n"
    "Exporting them would produce a bundle that is indistinguishable from a "
    "complete run over a smaller corpus: the survivors written to "
    "data/current.csv become the next stage's input, and the records never "
    "reached would be silently dropped from the review.\n\n"
    "Run the stage again to completion before exporting."
)


def _export_block_reason(*, has_rows: bool, cancelled: bool) -> Optional[str]:
    """Return why export must be refused, or None if it may proceed.

    F-02. One rule in one place, called by all four stage UIs, because the
    decision is the same for all of them and a per-stage copy is a per-stage
    opportunity to forget it.

    Cancellation is checked first on purpose: a cancelled run that produced
    no rows at all would otherwise be reported as "run the stage first",
    which is both wrong and reassuring.
    """
    if cancelled:
        return CANCELLED_EXPORT_REASON
    if not has_rows:
        return "Run the stage first — there are no results to export."
    return None


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
    cancelled: bool = False,
) -> None:
    """
    Create a new bundle zip where data/current.csv becomes the {stage} survivors.
    Keeps other files from the input bundle, updates manifest pipeline + sha256 (warn-only downstream).
    Adds reports/{stage}_FULL.csv and reports/{stage}_SURVIVORS.csv.

    ``cancelled`` is stamped onto the history entry (F-02). The UIs refuse to
    call this at all for a cancelled run — refusing export is the primary
    defence, since a manifest field that merely *says* the bundle is partial
    is easy to miss. The stamp is here so that any path which does write one
    anyway leaves a record a downstream reader can find.
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

    # F-03: append to whatever the incoming bundle already recorded, and
    # carry the file forward even when this stage dropped nothing. The old
    # code wrote only this stage's rows and only `if skipped`, in a layout
    # the reader could not parse — three separate ways to lose the record of
    # an excluded citation.
    prior_errors_text = ""
    try:
        with zipfile.ZipFile(src_zip, "r") as zf_prior:
            for rel in ("data/input_errors.csv", "input_errors.csv"):
                if root + rel in zf_prior.namelist():
                    prior_errors_text = _decode_bytes(zf_prior.read(root + rel))
                    break
    except Exception:
        prior_errors_text = ""

    input_errors_bytes = None
    merged_errors = merge_input_errors_csv(
        prior_errors_text, from_tuple_skipped(skipped, stage=stage))
    if read_input_errors(merged_errors):
        input_errors_bytes = merged_errors.encode("utf-8")

    # Update manifest
    m = dict(bundle.manifest)
    pipeline = dict(m.get("pipeline", {}) or {})
    stages = dict(pipeline.get("stages", {}) or {})
    history = list(pipeline.get("history", []) or [])

    stages[stage] = "cancelled" if cancelled else "done"
    history.append({
        "stage": stage,
        "ran_at": _iso_now(),
        "counts": counts,
        "survivors_rows": len(survivors),
        "out_rows_full": len(full_rows),
        "cancelled": bool(cancelled),
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
