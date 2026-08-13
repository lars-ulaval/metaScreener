# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_harmoniser_regression.py — Golden-file regression for Plugin 03.

Drives the same engine functions that the Harmoniser tab's "Harmonise (no-LLM)"
button calls and writes a `criteria_harmonized.csv` that must be byte-identical
to `tests/golden/criteria_harmonized_v3.1.0.csv`.

The golden file is the contract that the EH/IH/EL/IL plugins downstream consume.
This test guards the schema and inference output against silent drift across
the Plugin 03 module-decomposition refactor (Conv 4) and any subsequent change.

Rebuilding the golden file (only when output changes are deliberate)
-------------------------------------------------------------------
From the project root:

    python -c "from tests.test_harmoniser_regression import _harmonise_to_csv, GOLDEN; \\
               import sys; sys.path.insert(0, 'tests'); import conftest; \\
               GOLDEN.parent.mkdir(parents=True, exist_ok=True); \\
               _harmonise_to_csv(GOLDEN); \\
               print('Captured', GOLDEN, GOLDEN.stat().st_size, 'bytes')"

Then visually inspect the new `tests/golden/criteria_harmonized_v3.1.0.csv` to
confirm the change is intended before committing.
"""
import tempfile
from pathlib import Path

from conftest import (
    AGGREGATE_CSV,
    IC_EC_FILE,
    get_harmoniser,
)

GOLDEN = Path(__file__).parent / "golden" / "criteria_harmonized_v3.1.0.csv"


def _harmonise_to_csv(out_path: Path) -> None:
    """Reproduce the GUI's free-text harmonise path, no LLM, no widgets."""
    h = get_harmoniser()

    a_columns, text_stats = h._load_a_header_and_stats(str(AGGREGATE_CSV))

    default_text_target = h._get_best_text_targets(a_columns, text_stats)
    default_text_target, _ = h._canonicalize_targets(default_text_target, a_columns)

    text = IC_EC_FILE.read_text(encoding="utf-8-sig")
    parsed = h._parse_free_text_criteria(text)
    assert parsed, "Sample IC/EC file produced no parsed criteria"

    rows = []
    for crit_id, crit_type, label, source_line in parsed:
        inferred = h._infer_criterion_details(
            crit_id=crit_id,
            crit_type=crit_type,
            label=label,
            a_columns=list(a_columns),
            default_text_target=default_text_target,
        )

        stage = inferred["stage"]
        threshold = ""
        if stage in {"EL", "IL"}:
            threshold = f"{h.DEFAULT_THRESHOLD:.2f}"

        rows.append({
            "stage": stage,
            "id": crit_id,
            "type": crit_type,
            "scope": "metadata",
            "label": label,
            "operator": inferred["operator"],
            "target": inferred["target"],
            "what": inferred["what"],
            "threshold": threshold,
            "enabled": True,
            "source_text": source_line,
        })

    h._export_csv(rows, str(out_path))


def _build_rows():
    """The row-building half of `_harmonise_to_csv`, shared so the per-rule
    assertions and the schema assertion drive one production path."""
    h = get_harmoniser()
    a_columns, text_stats = h._load_a_header_and_stats(str(AGGREGATE_CSV))
    default_text_target = h._get_best_text_targets(a_columns, text_stats)
    default_text_target, _ = h._canonicalize_targets(default_text_target, a_columns)
    text = IC_EC_FILE.read_text(encoding="utf-8-sig")
    rows = []
    for crit_id, crit_type, label, source_line in h._parse_free_text_criteria(text):
        inferred = h._infer_criterion_details(
            crit_id=crit_id, crit_type=crit_type, label=label,
            a_columns=list(a_columns), default_text_target=default_text_target,
        )
        stage = inferred["stage"]
        rows.append({
            "stage": stage, "id": crit_id, "type": crit_type, "scope": "metadata",
            "label": label, "operator": inferred["operator"],
            "target": inferred["target"], "what": inferred["what"],
            "threshold": f"{h.DEFAULT_THRESHOLD:.2f}" if stage in {"EL", "IL"} else "",
            "enabled": True, "source_text": source_line,
        })
    return rows


#: The rule the harmoniser emits for each criterion of `samples/ic_ec_12.txt`,
#: as (stage, operator, target, what). CHARACTERISATION: this records what the
#: translator does TODAY, defects included, so wave 13d's repairs of F-166 and
#: F-167 have to flip these entries in the open rather than silently.
EXPECTED_RULES = {
    "IC-1": ("IL", "llm", "keywords", 1),
    "IC-3": ("IH", "equals", "lang", ["English"]),
    "IC-4": ("IH", "gte", "year", ["2018"]),
    # F-65: `contains` at an LLM stage, never evaluated. Not this wave's.
    "IC-5": ("IL", "contains", "title,abstract,keywords",
             ["training", "vocational", "workplace"]),
    # F-167: "written in French or Spanish" -> one operand. DEFECT.
    "EC-1": ("EH", "equals", "lang", ["French"]),
    "EC-2": ("EL", "llm", "keywords", 1),
    "EC-3": ("EL", "llm", "keywords", 1),
    # F-166: the label names `venue`; the rule reads `doc_type` and both
    # operands are discarded. DEFECT.
    "EC-4": ("EH", "equals", "doc_type", ["conference"]),
}


class TestTheRuleEmittedForEachCriterion:
    """Row by row, so a repair shows exactly which rows it moved.

    This sits beside the byte-identity assertion below rather than replacing it
    yet. `tests/golden/criteria_harmonized_v3.1.0.csv` is NOT just this module's
    fixture: it is the criteria INPUT for the EH, IH, EL and IL replay
    regressions and for the eval-grid and eval-ingest tools, so it must not move.
    """

    def test_every_criterion_emits_the_expected_rule(self):
        rows = _build_rows()
        assert [r["id"] for r in rows] == list(EXPECTED_RULES), "criteria set changed"
        for row in rows:
            stage, operator, target, what = EXPECTED_RULES[row["id"]]
            got = (row["stage"], row["operator"], row["target"])
            assert got == (stage, operator, target), (
                "%s emits %s, expected %s" % (row["id"], got, (stage, operator, target))
            )
            if isinstance(what, int):
                assert len(row["what"]) == what, row["id"]
            else:
                assert row["what"] == what, (
                    "%s operands are %r, expected %r" % (row["id"], row["what"], what)
                )

    def test_the_schema_is_unchanged(self):
        """The other thing byte-identity guarded: the 11-column contract the
        downstream plugins consume."""
        import csv as _csv
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "criteria_harmonized.csv"
            _harmonise_to_csv(out)
            with out.open(encoding="utf-8-sig", newline="") as fh:
                reader = _csv.DictReader(fh)
                assert reader.fieldnames == [
                    "stage", "id", "type", "scope", "label", "operator",
                    "target", "what", "threshold", "enabled", "source_text",
                ]
                assert len(list(reader)) == 8


class TestHarmoniserGolden:
    """Byte-identity regression for criteria_harmonized.csv."""

    def test_byte_identical_to_golden(self):
        assert GOLDEN.exists(), f"Golden file missing: {GOLDEN}"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "criteria_harmonized.csv"
            _harmonise_to_csv(out)
            actual = out.read_bytes()
        expected = GOLDEN.read_bytes()
        assert actual == expected, (
            f"criteria_harmonized.csv changed.\n"
            f"  expected {len(expected)} bytes, got {len(actual)} bytes.\n"
            f"  Schema or inference output drifted; this breaks downstream EH/IH/EL/IL.\n"
            f"  If the change is intentional, rebuild the golden file deliberately."
        )