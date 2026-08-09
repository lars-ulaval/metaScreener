# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_ih_regression.py — Golden-file regression for Plugin 05 (IH).

Drives the same engine functions that the IH tab's "Run IH" button calls and
writes an IH_FULL report CSV that must be byte-identical to
`tests/golden/ih_filtered_v3.1.0.csv`.

The golden is the byte-level contract that pins (a) per-criterion outcome
assignment, (b) survivor selection (derivable from `ih_outcome != "OUT"`),
and (c) the reason-summary text — including the IH-specific quirk that
`ih_missing_ids` carries the union of MISSING and UNKNOWN per row. Together
these guard against silent drift across the IH module-decomposition refactor
(Conv 5) and any subsequent change.

Inputs:
- corpus:   samples/20260122_1654_aggregate.csv
- criteria: tests/golden/criteria_harmonized_v3.1.0.csv  (the harmoniser golden)

Note: IH is exercised against the original aggregate corpus, not against
post-EH survivors. This decouples the IH golden from any EH golden change,
keeping the two regressions independent.

Rebuilding the golden file (only when output changes are deliberate)
-------------------------------------------------------------------
From the project root:

    python -c "import sys; sys.path.insert(0, 'tests'); import conftest; \
               from test_ih_regression import _ih_to_csv, GOLDEN; \
               GOLDEN.parent.mkdir(parents=True, exist_ok=True); \
               _ih_to_csv(GOLDEN); \
               print('Captured', GOLDEN, GOLDEN.stat().st_size, 'bytes')"

Then visually inspect the new golden to confirm the change is intended before
committing.
"""
import tempfile
import threading
from pathlib import Path

from conftest import AGGREGATE_CSV, get_ih

GOLDEN = Path(__file__).parent / "golden" / "ih_filtered_v3.1.0.csv"
CRITERIA_GOLDEN = Path(__file__).parent / "golden" / "criteria_harmonized_v3.1.0.csv"


def _ih_to_csv(out_path: Path) -> None:
    """Reproduce the GUI's IH run path (no widgets, no LLM, deterministic)."""
    h = get_ih()

    corpus_text = Path(AGGREGATE_CSV).read_text(encoding="utf-8-sig")
    criteria_text = CRITERIA_GOLDEN.read_text(encoding="utf-8-sig")

    parse = h._parse_csv_tolerant_text(corpus_text, required_id="local_id")
    crits = h._load_criteria_ih_from_text(criteria_text)

    full_rows, _surv, _counts, _impacts, _row_evals, _cancelled = h.run_ih_screen(
        parse, crits, threading.Event(), progress_cb=None
    )

    fieldnames = list(parse.header) + [
        "ih_outcome", "ih_failed_ids", "ih_missing_ids",
        "ih_met_ids", "ih_reason_summary",
    ]
    out_path.write_bytes(h._write_csv_bytes(fieldnames, full_rows))


class TestIHGolden:
    """Byte-identity regression for the IH_FULL report CSV."""

    def test_byte_identical_to_golden(self):
        assert GOLDEN.exists(), f"Golden file missing: {GOLDEN}"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ih_full.csv"
            _ih_to_csv(out)
            actual = out.read_bytes()
        expected = GOLDEN.read_bytes()
        assert actual == expected, (
            f"IH_FULL report CSV changed.\n"
            f"  expected {len(expected)} bytes, got {len(actual)} bytes.\n"
            f"  Per-criterion eval, outcome assignment, or reason summary drifted.\n"
            f"  If the change is intentional, rebuild the golden file deliberately."
        )
