# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_harmoniser_regression.py — Golden-file regression for Plugin 03.

Drives the same engine functions that the Harmoniser tab's "Harmonise (no-LLM)"
button calls, and asserts the rule emitted for each criterion of
`samples/ic_ec_12.txt` — row by row, so a change shows WHICH rule moved.

Until wave 13d this asserted byte-identity against
`tests/golden/criteria_harmonized_v3.1.0.csv`. Repairing F-166 and F-167 breaks
that by construction, because the golden records what the DEFECTIVE translator
emitted. The golden file is deliberately NOT regenerated: it is the criteria
input for six downstream tests whose expected outputs were captured from those
rules. See `TestTheGoldenIsStillTheDownstreamInput` for the whole argument, and
the schema assertion in `TestTheRuleEmittedForEachCriterion` for the other half
of what byte-identity used to guard.

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
    # F-167 REPAIRED in wave 13d: both languages the label names.
    "EC-1": ("EH", "in_list", "lang", ["French", "Spanish"]),
    "EC-2": ("EL", "llm", "keywords", 1),
    "EC-3": ("EL", "llm", "keywords", 1),
    # F-166 REPAIRED in wave 13d: the column the label names, both operands.
    "EC-4": ("EH", "contains", "venue", ["ICRA", "IROS"]),
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


class TestTheGoldenIsStillTheDownstreamInput:
    """The golden keeps its other job, and the divergence from fresh inference
    is deliberate and asserted rather than left to be discovered.

    THIS CLASS REPLACED A BYTE-IDENTITY ASSERTION. Until wave 13d this module
    asserted that fresh inference reproduced
    `tests/golden/criteria_harmonized_v3.1.0.csv` byte for byte. Repairing F-166
    and F-167 breaks that by construction: the golden records the rules the
    DEFECTIVE translator emitted.

    The golden file is nonetheless NOT regenerated, and the reason is stronger
    than "the fence says so". It is the criteria INPUT consumed by
    `test_eh_regression`, `test_ih_regression`, `test_el_regression`,
    `test_il_regression`, `test_eval_grid_generator` and `test_eval_ingest`,
    whose own expected outputs were captured FROM these rules. Regenerating it
    would move six downstream goldens with it. Those six load the FILE rather
    than fresh inference, so they are untouched by the repair and stay green.

    Separately: this file is not one of the F-98-frozen study artefacts. Those
    live under `docs/data/study_input/` with their own `SHA256SUMS` and are not
    this wave's to touch either — see F-168, which exists because a code repair
    cannot correct them.
    """

    def test_the_golden_still_exists_and_still_parses(self):
        import csv as _csv
        assert GOLDEN.exists(), f"Golden file missing: {GOLDEN}"
        with GOLDEN.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(_csv.DictReader(fh))
        assert len(rows) == 8

    def test_the_golden_records_the_pre_repair_rules(self):
        """Asserted, so nobody later reads the divergence as drift."""
        import csv as _csv
        with GOLDEN.open(encoding="utf-8-sig", newline="") as fh:
            by_id = {r["id"]: r for r in _csv.DictReader(fh)}
        assert (by_id["EC-1"]["operator"], by_id["EC-1"]["target"],
                by_id["EC-1"]["what"]) == ("equals", "lang", "French")
        assert (by_id["EC-4"]["operator"], by_id["EC-4"]["target"],
                by_id["EC-4"]["what"]) == ("equals", "doc_type", "conference")

    def test_fresh_inference_now_deliberately_differs_from_it(self):
        """The divergence itself, pinned. If a later wave re-captures the golden
        this test is where that decision announces itself."""
        import csv as _csv
        with GOLDEN.open(encoding="utf-8-sig", newline="") as fh:
            by_id = {r["id"]: r for r in _csv.DictReader(fh)}
        fresh = {r["id"]: r for r in _build_rows()}
        # F-167: `equals` -> `in_list`, and a second operand.
        assert fresh["EC-1"]["operator"] != by_id["EC-1"]["operator"]
        assert len(fresh["EC-1"]["what"]) == 2
        # F-166: `doc_type` -> `venue`, and the operands the label names.
        assert fresh["EC-4"]["target"] != by_id["EC-4"]["target"]
        assert fresh["EC-4"]["what"] == ["ICRA", "IROS"]
