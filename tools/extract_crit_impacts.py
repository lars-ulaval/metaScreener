# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""tools/extract_crit_impacts.py - recover the per-criterion impact table the
product computes on every run and never persists (F-228).

WHY THIS EXISTS. `plugins/06_el/screen.py` builds ``crit_impacts`` — a
``{criterion_id: {failed, missing, met, uncertain}}`` table answering "what is
this criterion doing to my corpus?" — returns it from ``run_el_screen``, and
nothing writes it to disk. The stage summaries, the reports and the FULL tables
all omit it. A freeze that captures only the shipped artefacts therefore
inherits F-228's hole, which is what wave 17c flagged and this tool closes.

WHAT IT DOES NOT DO. It does not re-run anything and it makes no LLM call. The
table is *reconstructed* from evidence the artefacts already carry, so it is a
derivation and not a second measurement.

THE MAPPING, and why it is exact rather than approximate. ``crit_impacts`` is
incremented in exactly four places in the engine, and each one also writes the
criterion's ``status`` into ``{el,il}_evidence_json``:

    screen.py:876   missing.append(c.id)   -> impacts[...]["missing"] += 1   status MISSING
    screen.py:882   uncertain.append(...)  -> impacts[...]["uncertain"] += 1 status UNCERTAIN
    screen.py:913   met.append(c.id)       -> impacts[...]["met"] += 1       status MET
    screen.py:935   uncertain.append(...)  -> impacts[...]["uncertain"] += 1 status UNCERTAIN
    screen.py:1016  _excluded_by, acted    -> impacts[...]["failed"] += 1    status FAILED
    screen.py:1025  _excluded_by, declined -> impacts[...]["failed"] += 1    status SUPPRESSED

Note the last two. ``_excluded_by`` counts a SUPPRESSED verdict under
``failed`` **deliberately** — its own comment says the table answers what the
criterion asserted, not where the record ended up. This tool reproduces that
semantic rather than "fixing" it, and additionally reports the split, which the
engine's table cannot express.

WHY NOT THE ID COLUMNS. ``{el,il}_{met,failed,missing,uncertain}_ids`` look like
the same information and are not: ``_excluded_by`` appends a declined removal to
a separate ``suppressed`` list which is **exported in no column at all**, so a
SUPPRESSED criterion id appears in none of the four. The evidence JSON is the
only artefact carrying it, which is why the derivation reads that.

THE DETERMINISTIC STAGES are already persisted — ``dryrun_v1/{arm}_manifest.json``
carries ``funnel.eh.impacts`` and ``funnel.ih.impacts`` in the same shape — so
those are copied through rather than derived, and labelled with their source.

Usage:
    python tools/extract_crit_impacts.py            # write the JSON
    python tools/extract_crit_impacts.py --print    # stdout, write nothing
    python tools/extract_crit_impacts.py --check    # recompute and compare; exit 1 on drift

`tests/test_wave17_freeze.py` runs ``--check`` semantics in-process, so a drifted
capture is a red suite.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
ARMS_DIR = ROOT / "docs" / "data" / "wave17_arms"
LIVE = ARMS_DIR / "live_v1"
DRY = ARMS_DIR / "dryrun_v1"
OUT = LIVE / "crit_impacts.json"

csv.field_size_limit(10_000_000)

#: status in `{el,il}_evidence_json` -> bucket in the engine's crit_impacts.
#: FAILED and SUPPRESSED both land on `failed`; see the module docstring.
STATUS_TO_BUCKET = {
    "MET": "met",
    "MISSING": "missing",
    "UNCERTAIN": "uncertain",
    "FAILED": "failed",
    "SUPPRESSED": "failed",
}

BUCKETS = ("failed", "missing", "met", "uncertain")


def _arms() -> list:
    """Arm keys that have live artefacts, in spec order."""
    spec = json.loads((ARMS_DIR / "experiment_spec.json").read_text(encoding="utf-8"))
    return [a["key"] for a in spec["arms"]
            if (LIVE / f"{a['key']}_EL_summary.json").exists()]


def derive_stage(arm: str, stage: str) -> Dict[str, Any]:
    """Rebuild one stage's crit_impacts from its FULL.csv evidence."""
    pre = stage.lower()
    path = LIVE / f"{arm}_{stage}_FULL.csv"
    impacts: Dict[str, Dict[str, int]] = {}
    # the split the engine's own table cannot express, recorded beside it
    split: Dict[str, Dict[str, int]] = {}
    n_records = 0
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            n_records += 1
            ev = json.loads(row[f"{pre}_evidence_json"] or "{}")
            for cid, v in ev.items():
                st = str(v.get("status", "")).upper()
                bucket = STATUS_TO_BUCKET.get(st)
                if bucket is None:
                    raise ValueError(
                        f"{arm}/{stage}/{row['local_id']}/{cid}: unmapped status "
                        f"{st!r} — the engine's status vocabulary changed and this "
                        f"derivation must be re-read against screen.py before use")
                impacts.setdefault(cid, {b: 0 for b in BUCKETS})[bucket] += 1
                s = split.setdefault(cid, {"acted_FAILED": 0, "declined_SUPPRESSED": 0})
                if st == "FAILED":
                    s["acted_FAILED"] += 1
                elif st == "SUPPRESSED":
                    s["declined_SUPPRESSED"] += 1
    # Every criterion must account for every record exactly once.
    for cid, b in impacts.items():
        total = sum(b.values())
        if total != n_records:
            raise ValueError(
                f"{arm}/{stage}/{cid}: buckets sum to {total} over {n_records} "
                f"records — the derivation is not a partition and must not be frozen")
    return {"records": n_records, "impacts": impacts, "failed_split": split}


def build() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "generated_by": "tools/extract_crit_impacts.py",
        "what": ("Per-criterion impact tables. The EL/IL halves are DERIVED from the "
                 "committed evidence because the product never persists them (F-228); "
                 "the EH/IH halves are COPIED from the dry manifests, which do. No run "
                 "was made and no LLM call was issued to produce this file."),
        "mapping": {k: v for k, v in STATUS_TO_BUCKET.items()},
        "note_on_failed": ("`failed` counts acted removals AND declined ones, which is "
                           "what plugins/06_el/screen.py::_excluded_by does on purpose. "
                           "`failed_split` records the split, which the engine's own "
                           "table cannot express."),
        "arms": {},
    }
    for arm in _arms():
        entry: Dict[str, Any] = {"llm_stages": {}, "deterministic_stages": {}}
        for stage in ("EL", "IL"):
            entry["llm_stages"][stage] = derive_stage(arm, stage)
        man = json.loads((DRY / f"{arm}_manifest.json").read_text(encoding="utf-8"))
        for stage in ("eh", "ih"):
            entry["deterministic_stages"][stage.upper()] = {
                "source": f"dryrun_v1/{arm}_manifest.json :: funnel.{stage}.impacts",
                "impacts": man["funnel"][stage]["impacts"],
            }
        out["arms"][arm] = entry
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--print", dest="to_stdout", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="compare the committed capture against a fresh derivation")
    args = ap.parse_args(argv)

    derived = build()
    text = json.dumps(derived, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    if args.to_stdout:
        sys.stdout.write(text)
        return 0
    if args.check:
        if not OUT.exists():
            print(f"MISSING: {OUT.relative_to(ROOT)} has not been captured")
            return 1
        committed = OUT.read_text(encoding="utf-8")
        if committed.replace("\r\n", "\n") != text:
            print(f"DRIFT: {OUT.relative_to(ROOT)} does not match a fresh derivation")
            return 1
        print(f"{OUT.relative_to(ROOT)} matches a fresh derivation "
              f"({len(derived['arms'])} arms)")
        return 0

    # LF, matching every other file in the frozen directory. That directory is
    # pinned `binary` in .gitattributes, so what is written here is exactly what
    # every checkout serves, on every platform.
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(derived['arms'])} arms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
