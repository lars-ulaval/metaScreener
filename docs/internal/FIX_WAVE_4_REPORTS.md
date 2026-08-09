# metaScreener — Fix Wave 4: report production

**Do not start this until the register update from `05_report_production.md` is
committed and the suite is green at 390 passed, 4 skipped.**

Sixteen findings came out of the report-production diagnostic
(`docs/internal/diagnostic/05_report_production.md`, committed as `5b8f731`):
**F-67 … F-82**. They split cleanly along one line — whether the change moves a
golden file — and that line is the wave split.

- **Wave 4a** — ten findings, **zero expected golden impact**. The audit-trail
  chain, the final workbook, and three cross-stage policy alignments. This is
  the wave that fixes things a reviewer can be harmed by.
- **Wave 4b** — one finding plus one carried site, **golden-touching, under an
  equivalence proof**. The deliverable format: line terminators, BOM, and the
  spreadsheet-delimiter problem.
- **Backlog** — **five** findings deliberately not scheduled: F-77, F-78, F-80,
  F-81, F-82. (F-77 and F-78 belong with the pre-existing F-62/F-63/F-64
  `used`-rename cluster, which shares their golden re-capture cost — that
  cluster is prior work, not a sixth wave-4 finding.)

Four questions are **pending human observation** and gate part of 4b. They are at
the end of this document.

## Ground rules

Same as waves 2 and 3.

- One finding per commit, `fix(F-nn): <what>`.
- Test-first. Each fix needs a test that reproduces the defect before the fix
  lands.
- **Stop and report before regenerating any golden.** In 4a no golden should
  move at all; if one does, that is a signal your fix changed behaviour it should
  not have, not a signal to re-capture.
- No API calls. Everything here is reachable offline — the diagnostic drove all
  four stages headlessly with a replay cache; reuse that shape.
- No GUI. Nothing in this wave requires a window except the four human
  observations, which are the human's to make.

---

# The decisions, already made

These were open questions in `05_report_production.md`. They are resolved; the
briefs below assume them.

| Question | Decision |
|---|---|
| **Q-A** — is the CRLF/CR → LF rewrite at `parser.py:237` intended? | **Keep it.** It is a deliberate canonicalisation of metadata. Document it and pin it with a test, so it stops being an undeclared side effect of the record splitter. *(F-76)* |
| **Q-B** — was `CONTRACT_STAGE_SHEET_COLS` ever the right column list? | **No — derive the header from the row builder's schema.** Drop the columns that have no data source rather than emitting them empty. *(F-69)* |
| **Q-C** — should the FINAL sheet cover the original corpus? | **Yes. The Harmoniser writes `data/original.csv`** — a pre-EH snapshot. `_load_master_rows` already looks for it. *(F-70)* |
| **Q-D** — is EL/IL's ragged-row repair deliberate? | **No — align to EH/IH's reject-and-record policy.** *(F-72, closes F-24)* |
| **Q-E** — should EH/IH re-stamp carried-forward `input_errors` rows? | **No — preserve prior rows verbatim, append only.** *(F-71)* |
| **Q-F** — are the EL/IL "Export input_errors.csv…" buttons still wanted? | **Yes, but rewired to the canonical writer.** *(F-74)* |
| *(no question raised)* | EL/IL adopt EH/IH's four-encoding decode ladder. *(F-73, closes F-23)* |
| *(no question raised)* | Always write `data/input_errors.csv`, header-only when nothing was dropped — implementing what the writer's own docstring argues for. *(F-75)* |

---

# Wave 4a — the audit trail and the final workbook

Ten findings, no golden should move. Suggested order: the `input_errors` chain
first (it is one coherent story and the fixes interlock), then the workbook, then
the three alignments.

## Group 1 — the `input_errors.csv` chain (F-67, F-68, F-74, F-75, F-71)

These five are one defect surface. Do them together, in this order.

### F-67 — the writer emits invalid CSV

`csv.writer` / `csv.DictWriter` with `lineterminator="\n"` does **not** quote a
field containing a lone CR. Demonstrated:

```
lineterminator="\n"    -> b'lone\rCR,next\n'      csv.reader RAISES _csv.Error
lineterminator="\r\n"  -> b'"lone\rCR",next\r\n'  csv.reader -> [['lone\rCR','next']]
```

Four sites: `plugins/_common/exporters.py:84`,
`plugins/_common/input_errors.py:114`, `plugins/06_el/ui.py:984`,
`plugins/07_il/ui.py:1232`.

**In 4a, fix only `input_errors.py:114`.** The `exporters.py:84` site is the
EH/IH report writer and moves golden bytes — it belongs to 4b under F-79. The two
`ui.py` sites disappear entirely under F-74, so do not patch them; delete them.

Test: build a ragged corpus row whose surplus cell carries a lone CR and nothing
else problematic, run it through the Harmoniser's `_clean_aggregate_csv`, and
assert `csv.reader` parses the resulting `data/input_errors.csv` into exactly two
records. That test fails today.

### F-68 — the reader turns unreadable into empty

`plugins/_common/input_errors.py:156-157` catches every exception and returns
`[]`. With F-67 fixed the file will be parseable, but the swallow is the reason
F-67 went unnoticed and it will hide the next one too.

Distinguish "empty" from "unparseable". The tolerance for the three legacy
layouts must stay — that is F-03's whole point and existing bundles depend on it.
What must not stay is a parse failure that looks like a clean result. Surface it
in the stage's warnings panel, where the "Imported previous input_errors: …
(N rows)" line already lives.

Test: feed it deliberately malformed text and assert the caller can tell the
difference.

### F-74 — the EL/IL export buttons still write the legacy schema

`plugins/06_el/ui.py:983-987` and `plugins/07_il/ui.py:1231-1235` write
`reason,row_json` inline. These are the last two writers of the schema F-03
retired, and `plugins/_common/input_errors.py:36` already claims (wrongly) that
both modules consume the shared writer.

Replace both with `_export_input_errors_csv` (`plugins/_common/exporters.py:46`),
which is what EH/IH's equivalent button already calls. The EL/IL `parse.skipped`
is a list of dicts, so route it through `from_dict_skipped`. This deletes two of
F-67's four sites as a side effect.

### F-75 — the header-only file is never written

Both bundle writers gate on `if read_input_errors(merged)`
(`plugins/_common/bundle.py:374`, `:524`), so a clean corpus produces no
`data/input_errors.csv` at all. `write_input_errors_csv`'s own docstring
(`input_errors.py:108-112`) argues that is the wrong choice, and it is right:
a reviewer cannot tell "nothing was dropped" from "this version did not write
the file".

Drop both gates. Always write the file.

Note the interaction with F-80: this adds a small file to every bundle. That is
the point.

### F-71 — one dropped citation inflates by one row per hop

`plugins/04_eh/ui.py:444-449` merges the carried-forward rows into
`ParseReport.skipped`, and `plugins/_common/bundle.py:373` then hands the whole
merged list to `from_tuple_skipped(skipped, stage="EH")`, which re-stamps every
prior stage's row as EH's and discards `observed_len`/`expected_len`. Because
`merge_input_errors_csv` keys on `stage`, the copies do not collapse. Measured:
1 row after the Harmoniser, 2 after EH, 3 after IH.

Fix: pass only **this stage's own** `pr.skipped` to `from_tuple_skipped`, and let
`merge_input_errors_csv` carry the prior rows through unchanged. That is what its
docstring already describes. The cleanest shape is to keep the carried rows out of
`ParseReport.skipped` entirely and track them separately, but if that ripples too
far, threading the un-merged list to the export call is acceptable — say which you
chose.

Test: drive Harmoniser → EH → IH over a corpus with one ragged row and assert the
file has exactly one data row at every hop, still carrying
`stage=Harmoniser` and its `observed_len`/`expected_len`.

## Group 2 — the final workbook (F-69, F-70)

### F-69 — the four stage sheets have never contained data

`CONTRACT_STAGE_SHEET_COLS` (`plugins/07_il/plugin.py:56-59`) and the keys
returned by `_extract_contract_stage_row` (`plugins/07_il/ui.py:322-349`)
intersect in **2 of 7** names. `ws.append([row_obj.get(c, "") for c in …])`
(`ui.py:437`) silently yields `""` for the other five, so every data cell on all
four stage sheets comes out blank while the row count stays correct.

Per **Q-B**: derive the header from the row builder. Concretely, the row builder
emits `a_id, stage, stage_outcome, passed_to_next, failed_criteria_ids,
missing_criteria_ids, uncertain_criteria_ids, met_criteria_ids,
matched_evidence, stage_reason_summary, history`. Two of those have no data
source and should go rather than ship empty: `history` is written as `""` at
`ui.py:348` and never populated, and `decided_at` (from the old header) has no
producer anywhere. Do not invent a source for either.

**Add a golden for this workbook.** Its absence is why the defect survived. An
`openpyxl` read-back asserting sheet names, header rows and a handful of cells is
enough, and it is what makes F-70 checkable too.

### F-70 — FINAL has no metadata for records excluded before IL

`_load_master_rows` (`plugins/07_il/ui.py:298-315`) tries `data/A.csv`,
`data/original.csv`, `data/aggregate.csv`, then `data/current.csv`. Nothing in
the pipeline writes the first three, so the "master list" is always the terminal
survivor set — and the FINAL sheet lists every excluded record with the right
verdict and no title.

Per **Q-C**: the Harmoniser writes `data/original.csv`. It is a copy of what
`_clean_aggregate_csv` already produces at `plugins/03_harmoniser/bundle.py:98`,
so this is a second `write` and a manifest entry, not new logic. Add it to the
`sha256` map. No stage overwrites it, so it survives to IL untouched.

Two consequences to handle deliberately:

- **Old bundles have no `data/original.csv`.** The fallback chain must keep
  working, and the FINAL sheet must not claim completeness it does not have. Emit
  a warning into the criteria/notes panel when the fallback fires.
- Bundle size grows by one corpus-sized CSV. Accepted.

Test: build a bundle, run all four stages, assert every record in the FINAL sheet
has a non-empty title — including the ones excluded at EH.

## Group 3 — cross-stage alignments (F-72, F-73, F-76)

### F-72 — EL/IL repair ragged rows that EH/IH reject

`plugins/06_el/screen.py:148-154` pads or truncates to the header width;
`plugins/_common/parser.py:305-307` skips the row as `bad_column_count`. A 4-cell
row against a 3-column header yields a record at EL and a skip at EH. Per **Q-D**,
align EL/IL to reject-and-record. This closes **F-24**, which recorded the
divergence without the audit-trail half.

The repaired-row case does not arise in the goldens (they are well-formed), so no
golden should move. Confirm that rather than assume it.

### F-73 — EL/IL's decoder is weaker than EH/IH's

`plugins/06_el/screen.py:113` does one `utf-8-sig` attempt with
`errors="replace"`; `plugins/_common/parser.py:217-223` falls back through
`utf-8`, `cp1252`, `latin-1`. Share the ladder. This closes **F-23**.

The goldens are UTF-8, so the ladder's first attempt succeeds and the bytes should
not move. **Verify that explicitly before committing** — F-23's register row
predicted a golden re-capture, and the diagnostic's reading says otherwise. If a
golden does move, stop and report; do not re-capture.

### F-76 — the CR normalisation is undocumented

`plugins/_common/parser.py:237` rewrites every CRLF and lone CR to LF across the
whole file text, *including inside quoted fields*, before parsing. Per **Q-A**,
keep it. Document it in the function's docstring and in `docs/usage.md`'s
description of what the reports contain, and add a test that asserts it — a
corpus field containing `\r\n` must come out of `EH_FULL.csv` as `\n`.

The evidence it is already load-bearing: `docs_/samples/20260122_1654_aggregate.csv`
has 4 fields containing CR, `tests/golden/eh_filtered_v3.1.0.csv` has 0.

## Closing 4a — reconcile the changelog

The register update that preceded this wave added items **11–13** to the
`[Unreleased]` "read this first" list (commit `fa74f69`). Each currently ends
"**Not yet fixed** — scheduled for the next wave," and the section intro says
"The last three entries are defects this release *records* rather than fixes."
The last commit of 4a must make that section internally consistent again:

- **Item 11 (F-67, F-68)** — rewrite as fixed *for the `input_errors` chain*:
  the writer now quotes a lone CR (`input_errors.py` site) and the reader
  distinguishes unparseable from empty. State explicitly that one F-67 site
  remains open — the EH/IH report writer at `_common/exporters.py:84` — and
  that it is deferred to 4b because fixing it moves golden bytes. That residual
  does not affect `input_errors.csv`, which is what item 11 is about.
- **Item 12 (F-69)** — rewrite as fixed: the stage sheets now carry data, header
  derived from the row builder, workbook golden added. Nothing remains.
- **Item 13 (F-70)** — rewrite as fixed, with the one honest caveat: bundles
  created *before* this fix have no `data/original.csv`, so a final report
  rebuilt from an old bundle still falls back to the survivor set and still
  lacks metadata for early-excluded records. New bundles are complete.
- Remove or rewrite the intro sentence "The last three entries are defects this
  release records rather than fixes…" — after 4a it is false as written. If the
  F-67 residual is judged worth a sentence there, fold it into item 11 instead.
- Keep all F-references. Add the fixed entries to the `### Fixed` section in the
  established style, as the other waves did — the "read this first" items say
  what a past user must re-check; `### Fixed` says what changed.

Commit as part of the wave's final `docs`/changelog commit, not as a separate
afterthought — a reader of `[Unreleased]` should never see the fixes and the
"not yet fixed" markers in the same checkout.

---

# Wave 4b — the deliverable format

**One finding, F-79, plus F-67's `plugins/_common/exporters.py:84` site.
Golden-touching. Its own session.**

Three facts, all measured:

1. One bundle carries reports with **two line terminators** — EH/IH LF
   (`_common/exporters.py:84`), EL/IL CRLF (`_common/bundle.py:458`), criteria
   table CRLF.
2. **No writer emits a BOM.**
3. Re-parsing `EH_FULL.csv` with `;` as the delimiter — the Excel default under a
   French-Canada locale — turns **7 logical records into 11 physical rows**
   (`EL_FULL.csv`: 5 into 9). With a mismatched delimiter the leading `"` is no
   longer at a field boundary, so quoting is not recognised and every embedded
   newline terminates a record. This is the most plausible explanation for a user
   reporting that one record's metadata overflowed onto adjacent rows.

**The decision:**

- **Unify terminators to CRLF** and **add a UTF-8 BOM** to the emitted report
  CSVs. This subsumes F-67's `exporters.py:84` site — CRLF quotes a lone CR
  correctly.
- **Prove equivalence rather than byte-identity.** The goldens will move by
  construction. The safety net is a test that parses the old and new goldens with
  the `csv` module and asserts **field-for-field equality**, not byte equality.
  A re-capture that silently changes a *field* is the thing to catch; a
  re-capture that changes only terminators and prepends three bytes is the thing
  being asked for. Write that test before you touch the writer.
- **Do not change the delimiter.** A comma-delimited CSV is correct and portable;
  the reader is what is misconfigured. Document the caveat in `docs/usage.md`
  instead, with the one-line instruction for opening a comma-delimited CSV in a
  `;`-locale Excel.
- **Make the repaired workbook the Excel-facing deliverable.** Once F-69 and F-70
  land, `reports/ScreenA_Report.xlsx` carries everything a reviewer needs, in a
  format with no delimiter question at all. Point the documentation there and
  demote the CSVs to the machine-readable path.

**Gate:** the BOM and terminator changes are worth making on general Windows
grounds regardless, but the *sizing* of this work depends on what Excel actually
does. **HO-2 and HO-3 below should be answered before 4b starts.** If Excel turns
out to handle the current files correctly, 4b shrinks to F-67's remaining site
plus a documentation note, and the golden re-capture may not be worth its cost.

---

# Backlog — deliberately not scheduled

| Finding | Why not now |
|---|---|
| **F-77** — `;` vs `,` criterion-id separator | Moves the bytes of all four filtered goldens. Belongs with the F-62/F-63/F-64 evidence-shape re-capture, which carries the same cost and touches the same files. |
| **F-78** — `{stage}_missing_ids` means two different things | Changes the *content* of `ih_filtered_v3.1.0.csv`, not just its bytes. Needs a deliberate re-capture with a diff review, and a decision about whether IH gains an `ih_uncertain_ids` column. |
| **F-80** — `{STAGE}_SURVIVORS.csv` duplicates `data/current.csv` | Observation, not a defect. Both names are wanted. Revisit only if bundle size becomes a constraint. |
| **F-81** — standalone export header from `full_rows[0].keys()` | Development driver, not the production tab. |
| **F-82** — EL/IL omit `created_by` / `derived_from` | Small, but it interacts with F-53 (local-time `created_at`, local path in `derived_from.zip_name`). Do the three together. |

---

# Pending human observations

Four questions from `05_report_production.md` that no amount of code reading
settles. **HO-2 and HO-3 gate wave 4b.** HO-1 and HO-4 are diagnostic — they
determine whether there is a display defect at all, and the diagnostic found no
supported mechanism for one.

### HO-1 — does a multi-line metadata field draw as one row in the tab?

Launch metaScreener → Harmoniser tab → build a bundle from any corpus containing
a record whose `title` or `abstract` has an embedded newline
(`docs_/samples/20260122_1654_aggregate.csv` has 15 such fields) → *Screen A —
EH* tab → **Load ScreenA bundle ZIP…** → **Run EH** → *EH Full report* tab →
find the affected record.

**Report:** does it occupy one `Treeview` row or more? Is the newline drawn as a
space, a box glyph, or does the cell truncate at it?

*Why it cannot be answered otherwise:* the row-preparation expression
(`plugins/_common/widgets.py:94`) was unit-tested headlessly against hostile
metadata and produced exactly one row with one value per column, every time. Only
Tk's rendering of that value is unknown.

### HO-2 — what does Excel under a French-Canada locale do to `EH_FULL.csv`?

Take the EH bundle from HO-1, extract `ScreenA_Bundle/reports/EH_FULL.csv`, and
double-click it in Excel with the system list separator set to `;`.

**Report:** the number of rows Excel shows versus the 777 records the file
contains, and whether the records with multi-line metadata spill across rows.

*Why it cannot be answered otherwise:* the Python `csv` module gave 11 rows for a
7-record file under the same delimiter mismatch, but Python's parser is only a
proxy for Excel's. **This is the observation that sizes wave 4b.**

### HO-3 — do accents survive Excel's double-click path?

Same file, same repro. The file is UTF-8 **without** a BOM.

**Report:** whether `Québec`-class strings render correctly or as mojibake.

*Why it matters:* it is the direct test of the BOM half of F-79.

### HO-4 — which surface was the user actually looking at?

The symptom "one record's metadata overflowed onto adjacent rows" was reproduced
in a spreadsheet proxy (HO-2's mechanism) and **not** reproduced in the tab-table
data path.

**Report:** was the report a spreadsheet observation or an in-app observation?
That single answer decides whether F-79 is the whole story or whether there is a
display defect the diagnostic could not reach.

---

Finish with: what you committed, the suite result, confirmation that no golden
moved in 4a, confirmation that changelog items 11–13 no longer read "not yet
fixed" (see *Closing 4a*), and — if 4b ran — the equivalence-proof output
showing that old and new goldens agree field-for-field.
