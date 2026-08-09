# Fix Wave 2 — Criticals

Working brief for the third fix wave. Finding IDs (F-nn) refer to
[`docs/internal/diagnostic/03_findings.md`](docs/internal/diagnostic/03_findings.md);
read the relevant register row before starting each task.

> **Note on this file.** It did not exist when the first task below was written
> (2026-08-08, at the pre-wave-2 checkpoint); it was created to hold that task.
> If a Wave 2 brief already exists elsewhere, merge this entry into it and delete
> this file.

## Ground rules

Same as waves 0 and 1: one commit per finding, `fix(F-nn): <what>`; run
`python -m pytest tests/ -q` after every commit; no golden file may change
without an explicit, separately-justified re-capture.

---

## Task 1 — A stage with zero enabled criteria must not report success (F-34)

**Severity: High** (raised from Medium at the pre-wave-2 checkpoint — see the
register row for why).

### The defect

When a screening stage ends up with no enabled criteria, it does not fail, warn
loudly, or stop. It assigns **`PASS_CLEAN`** to every record and reports every
record as a survivor. Measured on a bundle built from
`tests/golden/criteria_harmonized_v3.1.0.csv` with the EL criteria removed:

```
counts   : {'OUT': 0, 'PASS_CLEAN': 85, 'PASS_FLAGGED': 0}
survivors: 85 of 85 records
```

`PASS_CLEAN` is the *stronger* of the two survivor labels — it means "every
criterion was met" — which is precisely what did not happen. A stage that did no
work is therefore indistinguishable from a stage that ran correctly and excluded
nothing, and reports itself using the label that most strongly asserts the
opposite.

Code paths:

| Stage | Zero-criteria branch |
|---|---|
| EH, IH | `plugins/_common/runner.py:99-115` |
| EL | `plugins/06_el/screen.py:386-404` |
| IL | `plugins/07_il/screen.py:388-406` |

The warning itself is emitted at `plugins/_common/parser.py:373`
("Criteria header not found.") and `plugins/06_el/screen.py:323` /
`plugins/07_il/screen.py:325` ("No EL/IL criteria found (stage=…)").

### Why it was raised to High

F-04 (fixed in wave 1, commits `f925625` and `906423a`) added a **second and more
likely route** into this state. A criterion whose `type` cell is blank or
unrecognised is now rejected rather than run with a guessed polarity. That is the
right call in isolation — guessing could invert a screening decision — but it
means **one malformed cell can empty a stage**.

The demonstration corpus makes this concrete: after `EC-3`, the EL stage runs on
a single criterion. Blank one cell and EL has none. The stage goes from producing
a *wrong* answer to producing *no* answer that looks like a right one. The second
failure is harder to notice than the first.

### Required behaviour

A stage with zero enabled criteria must be visibly distinct from a stage that
screened everything and excluded nothing. At minimum:

1. **Do not use `PASS_CLEAN`.** Introduce a distinct outcome — `NOT_SCREENED` is
   the suggested literal — and count it in its own bucket. It must not be folded
   into either survivor category.
2. **The run summary must say so.** The counts label and the survivors tab are
   what the user reads after a run; they currently assert success. Whatever
   label is chosen has to reach both.
3. **Gate the run or the export.** Either refuse to start (modal: the stage has
   no criteria, here is why, here is what to fix) or allow it and require an
   explicit acknowledgement before the bundle can be exported.
4. **Record it in the manifest.** A downstream reader of the bundle — including
   a reviewer reproducing the pipeline — must be able to tell that a stage was a
   no-op without re-running the GUI. Add it to
   `manifest.pipeline.history[]` alongside the existing counts.

### Why the warning panel is not enough

The warning already exists and already reaches the GUI: `_load_bundle` puts it in
`CriteriaLoadReport.warnings`, and the View copies it into the "Notes / warnings"
box (`plugins/06_el/ui.py:541-543`, `plugins/07_il/ui.py:759-761`). It is not
sufficient, for three reasons:

- It is an 8-line read-only `tk.Text` in the left pane
  (`plugins/06_el/ui.py:386-391`, `plugins/07_il/ui.py:603-608`). It gates
  nothing and blocks nothing.
- **The run summary actively contradicts it.** The user sees `PASS_CLEAN: 85` and
  `survivors: 85 of 85` in the counts label and the results tables. When two
  parts of the same screen disagree, the one that looks like a result wins.
- It does not survive into the bundle. Export the run, hand the ZIP to a
  collaborator, and nothing in `manifest.json` or the report CSVs records that
  the stage did nothing.

### Notes for the implementer

- Check the four stages together. EH/IH share `runner.py`; EL/IL have twinned
  copies (F-14), so the same change lands in two near-identical places.
- `OUTCOMES` is a per-stage tuple (`plugins/06_el/screen.py:66`,
  `plugins/07_il/screen.py:68`, and the EH/IH equivalents) — a new literal has to
  be added there too, and IL already uses `REVIEW` where EL uses `PASS_FLAGGED`.
- **Goldens should not move.** No committed golden exercises a zero-criteria
  stage, so the new branch is unreachable from them. Confirm that rather than
  assume it: if a golden changes, the new literal has leaked into the normal
  path.
- Related but out of scope here: F-04 (the route in), and the general problem
  that a bundle's manifest carries two divergent stage maps (F-27).

**Effort: S.**
