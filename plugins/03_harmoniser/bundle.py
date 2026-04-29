# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
bundle.py - Plugin 03 Harmoniser: Screen-A bundle archive orchestration.

Concerns owned by this module:
  - export_screen_a_bundle(...): given pure-data inputs (harmonised rows,
    aggregate-CSV path, criteria source text, output ZIP path), build the
    full Screen-A bundle archive on disk.

The bundle archive layout produced is:
    ScreenA_Bundle/
        manifest.json
        data/
            current.csv
            input_errors.csv         (only if rows were dropped during cleaning)
        criteria/
            criteria_harmonized.csv
            criteria_harmonized.txt
            criteria_source.txt

Calls into .exporters for the actual file writers, manifest assembly, and
SHA-256 hashing. No GUI dependencies; no LLM dependencies. Caller (the View)
is responsible for any user-facing dialogs or error messages.

Extracted from `plugin.py` in Conv 4 of the v3.1.0 refactor; the orchestration
previously lived inline in the View's `_export_bundle` method, which is now a
thin wrapper around this function. Behavior is preserved verbatim - same temp
scratch dir, same write order, same manifest structure, same ZIP layout.
"""

import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .exporters import (
    BUNDLE_ROOT_NAME,
    _build_manifest,
    _clean_aggregate_csv,
    _export_csv,
    _export_pipe,
    _sha256_file,
)


def export_screen_a_bundle(
    *,
    rows: List[Dict[str, Any]],
    a_path: str,
    a_columns: Sequence[str],
    a_id_col_guess: str,
    criteria_path: str,
    criteria_kind: str,
    criteria_source_text: str,
    zip_out_path: str,
) -> str:
    """
    Build the Screen-A bundle archive at `zip_out_path`.

    Steps:
      1. Create a temporary scratch dir + ScreenA_Bundle/ root + data/, criteria/
         subdirectories.
      2. Write criteria/criteria_harmonized.csv (byte-identity-critical schema
         consumed by EH/IH/EL/IL downstream).
      3. Write criteria/criteria_harmonized.txt (pipe-table view).
      4. Write criteria/criteria_source.txt (raw researcher input).
      5. Clean the aggregate CSV: data/current.csv (+ optional
         data/input_errors.csv when malformed rows were dropped).
      6. Build the manifest (config + criteria summary + clean stats).
      7. Compute SHA-256 over the data files; attach hashes to manifest.
      8. Write manifest.json.
      9. Pack everything into the output ZIP.

    Returns the resolved zip_out_path on success.
    Raises any exception from the underlying steps; the caller decides how
    to surface failures to the user.
    """
    with tempfile.TemporaryDirectory(prefix="screenA_bundle_") as tmp:
        root = Path(tmp) / BUNDLE_ROOT_NAME
        data_dir = root / "data"
        crit_dir = root / "criteria"
        data_dir.mkdir(parents=True, exist_ok=True)
        crit_dir.mkdir(parents=True, exist_ok=True)

        criteria_csv = crit_dir / "criteria_harmonized.csv"
        criteria_txt = crit_dir / "criteria_harmonized.txt"
        criteria_src = crit_dir / "criteria_source.txt"

        _export_csv(rows, str(criteria_csv))
        _export_pipe(rows, str(criteria_txt))
        criteria_src.write_text(criteria_source_text + "\n", encoding="utf-8")

        current_csv = data_dir / "current.csv"
        errors_csv = data_dir / "input_errors.csv"
        clean_stats = _clean_aggregate_csv(a_path, current_csv, errors_csv)

        wrote_errors = errors_csv.exists() and errors_csv.stat().st_size > 0
        if not wrote_errors:
            try:
                errors_csv.unlink(missing_ok=True)
            except Exception:
                if errors_csv.exists():
                    errors_csv.unlink()

        manifest = _build_manifest(
            a_path=a_path,
            a_columns=list(a_columns),
            a_id_col_guess=a_id_col_guess,
            clean_stats=clean_stats,
            criteria_path=criteria_path,
            criteria_kind=criteria_kind,
            criteria_rows=rows,
            criteria_source_text=criteria_source_text,
            wrote_input_errors=wrote_errors,
        )

        hashes = {
            "data/current.csv": _sha256_file(current_csv),
            "criteria/criteria_harmonized.csv": _sha256_file(criteria_csv),
        }
        if wrote_errors:
            hashes["data/input_errors.csv"] = _sha256_file(errors_csv)
        manifest["sha256"] = hashes

        (root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        zip_out = Path(zip_out_path)
        zip_out.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in root.rglob("*"):
                if p.is_file():
                    arc = str(p.relative_to(Path(tmp)))  # includes root folder name
                    zf.write(p, arcname=arc)

    return zip_out_path

