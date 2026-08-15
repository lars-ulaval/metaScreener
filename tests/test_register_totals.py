# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""The register's Totals block must equal a derivation from its rows (F-131).

The block is a hand-regenerated snapshot, and the hand has been measured
wrong three times — most recently a mis-correction at `bb428b0` that
"repaired" a divergence the committed block did not have and thereby
created one, carried through ten regenerations. Every check before this
one compared a hand derivation against the previous hand derivation;
this one derives from the rows, so a drifted block is a red suite.

The derivation rules are the register's own ("How this register is
counted"): count rows not IDs, split cells on unescaped pipes, take the
last bolded severity (post-arrow), and read status from the Effort-cell
marker alone. The tool also hard-errors on a row that does not split
into exactly eight cells — the F-153 shape, where an unescaped pipe
pushed a closed row's marker out of its column.
"""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "_derive_register_totals", str(REPO / "tools" /
                                   "derive_register_totals.py"))
drt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drt)


def _text():
    return (REPO / "docs" / "internal" / "diagnostic" /
            "03_findings.md").read_text(encoding="utf-8")


class TestTheTotalsBlock:
    def test_the_committed_block_equals_the_derived_one(self):
        """All 40 cells. A mismatch prints the exact cells and the block
        to paste, via the tool's own comparator."""
        diffs = drt.compare(_text())
        assert diffs == [], (
            "the committed Totals block diverges from the rows: %s — run "
            "python tools/derive_register_totals.py for the block to paste"
            % ", ".join("%s/%s committed=%d derived=%d" % d for d in diffs))

    def test_every_row_parses_into_eight_cells(self):
        """derive() hard-errors on the F-153 shape; reaching a block at
        all certifies every row split clean."""
        block = drt.derive(_text())
        assert block["Total"][0] >= 200, "the register cannot shrink"

    def test_the_derivation_is_not_vacuous(self):
        """The comparator must actually see a seeded defect: flip one
        closed High row's count by faking a (done) removal in text, and
        the diff must name the exact cells."""
        text = _text()
        # Find one closed High row and un-close it in the parsed text.
        target = None
        for line in text.splitlines():
            if not drt._ROW_RE.match(line):
                continue
            cells = drt._CELL_SPLIT.split(line)[1:-1]
            if drt._BOLD_SEV.findall(cells[1])[-1] == "High" \
                    and "(done)" in cells[-1]:
                target = line
                break
        assert target is not None
        mutated = text.replace(target,
                               target[::-1].replace(")enod(", "", 1)[::-1],
                               1)
        diffs = drt.compare(mutated)
        cells_hit = {(sev, col) for sev, col, _, _ in diffs}
        assert ("High", "Closed") in cells_hit
        assert ("High", "Open") in cells_hit
        assert ("Total", "Closed") in cells_hit

    def test_a_ninth_pipe_is_an_error_not_a_guess(self):
        """The F-153 shape: an unescaped pipe inside a cell must raise,
        never skew the count."""
        text = _text()
        first_row = next(l for l in text.splitlines()
                         if drt._ROW_RE.match(l))
        broken = first_row[:-1] + "| extra |"
        try:
            drt.derive(text.replace(first_row, broken, 1))
        except drt.RegisterParseError as e:
            assert "eight-column" in str(e)
        else:
            raise AssertionError("a nine-cell row must not parse")
