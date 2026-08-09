# 05 — Report production in the four screening stages

*Read-only diagnostic of what stages 04–07 actually write, whether the CSVs
survive hostile metadata, and what fills the on-screen results table.*

**Repository state:** `main` @ `b586230`, working tree clean. HEAD is **12 commits
ahead** of the tag `post-wave-2` (`5795f7c`), 0 behind — HEAD does *not* match the
tag.
**Date:** 2026-08-08. **Mode:** read-only. No source, test, golden, register or
changelog file was modified; this document is the only file added.
**Method:** every claim below is either (a) cited to `file:line` read from source,
or (b) marked **[observed]** and produced by an offline run of the real engine
entry points over a synthetic hostile corpus. Inference is marked **[inference]**.
No Tkinter object was instantiated; `OPENAI_API_KEY` was removed from the
environment before any EL/IL call, so no network request was possible.

---

## Addendum (wave 6): what wave 4a changed, and which passages below are now stale

*Added 2026-08-09 at `895e51c`. **Nothing below this section has been rewritten.**
This document is a dated, commit-pinned snapshot whose claims are cited to source or
marked **[observed]** — an experimental record — so the wave-6 sweep annotates it and
leaves the measurements as written. Read the body as "true at `b586230`" and this
section as the delta.*

Wave 4a fixed most of what this document found, and in doing so overtook **twelve**
passages across three topics. The count matters: `06_llm_integration.md` reports "two
items encountered in passing", which is two *topics*, not two passages — and two of the
twelve contain neither phrase a reader would grep for.

**Topic 1 — `data/input_errors.csv` is now written unconditionally (F-75, `b65a86d`).**
Both bundle writers gated the file on a non-empty read; the gates are gone and the file
is always emitted, header-only when nothing was dropped — which is the argument this
document quotes from `write_input_errors_csv`'s own docstring. Now stale:

| § | Passage | Stale token |
|---|---|---|
| `A.1–A.7 Stage 04 — EH` | files-written table, `data/input_errors.csv` row | "only if the merged file has ≥1 row" |
| `Stage 05 — IH` | item **1. Files written.** | the single word "conditional" |
| `Stage 06 — EL` | files-written table, `data/input_errors.csv` row | "only if non-empty" |
| `B.4 Per-file structural verification` | paragraph **A third, minor.** | "the header-only file is never written" **[observed]** |
| `Candidate findings` | item 6 | → **F-75**, closed |

**Topic 2 — EL and IL now reject ragged rows instead of repairing them (F-72,
`58518c9`).** `plugins/06_el/screen.py::_csv_read_strict` and its IL twin divert them to
the skip list as `bad_column_count`, so they reach `data/input_errors.csv`. Now stale:

| § | Passage |
|---|---|
| `Stage 06 — EL` | item **2. Row universe.** — "ragged rows are silently padded or truncated" **[observed]** |
| `Stage 06 — EL` | item **7. Contract as implemented.** — the "repaired rather than rejected" clause only |
| `Stage 07 — IL` | item **2. Row universe.** — "Same padding-not-skipping behaviour as EL" |
| `B.6 Defect classification` | class (R), second bullet — the **first** near-miss only |
| `Candidate findings` | item 8 → **F-72** (and **F-24**), closed |
| `Open questions for the maintainer` | **Q-D** — **answered**: align EL/IL to EH/IH's reject-and-record policy |

**Two traps in topic 2, for anyone re-verifying rather than reading.** First,
`B.1 Inventory` row **R3** is *not* stale and must not be swept with the rest:
`plugins/06_el/screen.py::_csv_read` still pads, deliberately, because the criteria table
and report re-reads still go through it — only `data/current.csv` moved to the strict
sibling, for which the inventory has no row at all. R3 is now **incomplete, not wrong**.
Second, the coordinate `screen.py:148-154` cited in `Stage 06 — EL` still lands inside
that same lenient `_csv_read`, so a verifier who re-checks the line number instead of the
call path will wrongly re-confirm a stale claim.

**Topic 3 — `read_input_errors()` now raises on an unreadable file (F-68, `f813b70`),**
which this document's own candidate 2 asked for. `plugins/_common/input_errors.py`
defines `InputErrorsUnreadableError`; absent or empty still reads as empty. Every passage
asserting that the reader "never raises" or returns `[]` on failure is stale —
`Executive summary` item 2, `B.1 Inventory` row **R4**, `B.2 Static red flags`, and
`Candidate findings` item 2. This topic is named in neither the brief nor
`06_llm_integration.md`; it was found during the wave-6 sweep.

**Closure map for this document's candidate findings.** 1 → F-67 (`267007d`, with a
residual site deferred to F-79); 2 → F-68 (`f813b70`); 3 → F-69 (`150a37a`); 4 → F-70
(`da519ec`); 5 → F-71 (`2203ab0`); 6 → F-75 (`b65a86d`); 7 → F-76 (`1e1ee0a`); 8 → F-72
(`58518c9`); 9 → F-73 (`b2fa7df`); 10 → F-77, 11 → F-78, 12 → F-74 (`c928432`), 13 →
F-27's mechanism note, 14 → F-80, 15 → F-14's note, 16/17 → F-79, 18 → F-81. Of these,
**F-77, F-78, F-79, F-80 and F-81 remain open** — F-79 is wave 4b, the rest backlog.

---

## Executive summary

**The CSV writers are structurally sound where it matters most, and the display
path is clean. The two real problems are elsewhere: a quoting bug that can make
`data/input_errors.csv` unreadable, and a final workbook whose four stage sheets
are empty.**

1. **CSV structure holds under hostile content.** Six records carrying embedded
   `LF`, `CRLF`, lone `CR`, balanced and unbalanced double quotes, commas,
   semicolons, surrounding whitespace, accents, a 9 000-character abstract and an
   empty abstract were driven through EH → IH → EL → IL. In all 22 emitted CSVs,
   **every logical record occupied exactly one CSV record, every pass-through
   field round-tripped, no file contained `\r\r\n`, and every manifest digest
   matched.** The extra user column `reviewer_note` survived all four hops.
   **[observed]**

2. **One writer configuration is genuinely unsafe.** `csv.writer` /
   `csv.DictWriter` with `lineterminator="\n"` does **not** quote a field
   containing a lone `CR`. Three call sites use that configuration
   (`plugins/_common/exporters.py:84`, `plugins/_common/input_errors.py:114`,
   `plugins/06_el/ui.py:984`). Demonstrated end-to-end: a corpus record that is
   both ragged **and** contains a lone `CR` makes the Harmoniser write a
   `data/input_errors.csv` that `csv.reader` refuses to parse — and
   `read_input_errors()` swallows the exception and returns `[]`
   (`plugins/_common/input_errors.py:156-157`), so a dropped citation is recorded
   to disk and then read back as *"nothing was dropped."* **[observed]**

3. **The final deliverable workbook is largely blank.** IL's
   `reports/ScreenA_Report.xlsx` has five sheets. The four stage sheets (EH, IH,
   EL, IL) are populated from `CONTRACT_STAGE_SHEET_COLS`
   (`plugins/07_il/plugin.py:56-59`) while the row builder emits an entirely
   different key set (`plugins/07_il/ui.py:322-349`). Five of seven columns can
   never match, and the two that do were empty in the run — **every data cell on
   all four stage sheets came back `None`**. Separately, the FINAL sheet's
   metadata columns are blank for every record excluded before IL, because
   `_load_master_rows` falls back to `data/current.csv`
   (`plugins/07_il/ui.py:298-315`) and the Harmoniser never writes a `data/A.csv`.
   **[observed]**

4. **The tab tables are populated purely from memory, and correctly.** All four
   stages render `self.full_rows` / `self.survivors` straight from the engine
   return; nothing re-reads a CSV. The row-preparation expression
   (`plugins/_common/widgets.py:94`) was unit-tested headlessly against the
   hostile rows: arity always equalled the column count and every value was
   byte-identical. Two cells did carry a raw `\n` into the widget; whether
   `ttk.Treeview` renders that as one row is the one open human-observation
   question. **[observed]**

5. **Most plausible cause of a user seeing one record spill onto adjacent rows:
   class (V), the spreadsheet, not the software.** Re-parsing `EH_FULL.csv` with
   `;` as the delimiter — the Excel default under a French-Canada locale — turns
   **7 logical records into 11 physical rows**, because with a mismatched
   delimiter the leading `"` is no longer at a field boundary and the embedded
   newlines stop being protected. `EL_FULL.csv`: 5 → 9. **[observed]**

6. **Fidelity is not byte-identical: EH silently rewrites every `CRLF` and lone
   `CR` inside metadata to `LF`** (`plugins/_common/parser.py:237`, applied to the
   whole text *including quoted fields*). Corroborated by the committed goldens:
   `docs_/samples/20260122_1654_aggregate.csv` has 4 fields containing `CR`;
   `tests/golden/eh_filtered_v3.1.0.csv` has 0. EL/IL preserve `CR` but only ever
   see text EH already normalised. **[observed]**

---

## Part A — the bundle report contract, per stage

### A.0 Shared facts that apply to all four

- **`reports/{STAGE}_SURVIVORS.csv` and `data/current.csv` are the same bytes.**
  EH/IH assign one buffer to both (`plugins/_common/bundle.py:349,354`); EL/IL
  serialise the same rows twice with the same writer
  (`plugins/_common/bundle.py:519,521`). Confirmed byte-for-byte in all four
  bundles. **[observed]**
- **Everything the stage did not write is copied verbatim** from the input zip
  (`bundle.py:436-440`, `bundle.py:583-586`), so a bundle accumulates every
  earlier stage's reports. The IL bundle carried all eight prior report CSVs.
  **[observed]**
- **`created_by` / `derived_from` are EH/IH-only.** `_export_next_bundle_zip`
  stamps `created_at`, `created_by = f"screen_a_{sl}_plugin"` and
  `derived_from.zip_name` (`bundle.py:405-411`). `_write_llm_stage_bundle` stamps
  none of them; EL/IL's callers set only `updated_at`
  (`plugins/06_el/ui.py:1051`, `plugins/07_il/ui.py:1299`).
- **The two stage maps diverge.** EL/IL write both `pipeline.stages` and
  `pipeline_state.stages` (`bundle.py:551-556`). EH/IH write only
  `pipeline.stages`. Observed in the IL bundle: `pipeline.stages` =
  `{EH: done, IH: done, EL: done, IL: done}` but `pipeline_state.stages` =
  `{EH: not_run, IH: not_run, EL: done, IL: done}`. **[observed]**

### A.1–A.7 Stage 04 — EH

**1. Files written into the bundle** (`plugins/_common/bundle.py:311-447`, called
from `plugins/04_eh/ui.py:921`):

| Path in bundle | Writer | Condition |
|---|---|---|
| `manifest.json` | `json.dumps(..., indent=2)` + `"\n"`, `bundle.py:424` | always |
| `data/current.csv` | `_write_csv_bytes`, `bundle.py:349` | always |
| `reports/EH_FULL.csv` | `_write_csv_bytes`, `bundle.py:350` | always |
| `reports/EH_SURVIVORS.csv` | same bytes as `data/current.csv`, `bundle.py:354` | always |
| `data/input_errors.csv` | `merge_input_errors_csv`, `bundle.py:372-375` | only if the merged file has ≥1 row |
| *(all other members)* | copied verbatim, `bundle.py:436-440` | always |

No cache file. Manifest fields updated: `pipeline.stages["EH"]`
(`done` / `cancelled` / `not_screened`, `bundle.py:386-391`), a
`pipeline.history` entry with `counts`, `survivors_rows`, `out_rows_full`,
`cancelled`, `not_screened` (`bundle.py:392-400`), `created_at`, `created_by`,
`derived_from.zip_name`, and the `sha256` map for the four files it wrote
(`bundle.py:415-422`). **`pipeline_state.stages` is left untouched.**

GUI-only emission sites (not in the bundle): `EH_reports.xlsx` two sheets
(`plugins/_common/exporters.py:59-80`), standalone `input_errors.csv`
(`exporters.py:46-57`).

**2. Row universe.** FULL = every *integral* row of the `data/current.csv` that
arrived at EH — i.e. everything this stage saw, **not** the original corpus.
SURVIVORS = the subset whose `eh_outcome != "OUT"` (`runner.py:211-212`).
Records excluded at an earlier stage are simply **absent**; there is no
carried-forward "already out" marker anywhere in either file. Ordering is input
file order, preserved end to end (`runner.py:148`). Filtering/dedup happens in
`_parse_csv_tolerant_text` before the runner sees the rows: blank records,
`bad_column_count`, `missing_local_id` and **duplicate `local_id`** (first
occurrence wins, `parser.py:317-325`) are all diverted to `ParseReport.skipped`.
Observed: 6 in → 6 FULL → 5 SURVIVORS. **[observed]**

**3. Columns, in order.** `parse_header + ["eh_outcome", "eh_failed_ids",
"eh_missing_ids", "eh_met_ids", "eh_reason_summary"]` (`bundle.py:350-352`).

| Column | Class |
|---|---|
| every column of the incoming `data/current.csv`, in its original order | **pass-through** (CR-normalised, see 4) |
| `eh_outcome` | stage-added: `OUT` / `PASS_CLEAN` / `PASS_FLAGGED` / `NOT_SCREENED` |
| `eh_failed_ids`, `eh_missing_ids`, `eh_met_ids` | stage-added, criterion ids joined with **`;`** (`runner.py:198-204`) |
| `eh_reason_summary` | stage-added free text (`evaluator.py:339-351`) |

**Input columns dropped: none.** SURVIVORS carries `parse_header` only — zero
stage-added columns, so the survivors file is schema-identical to its input.

**4. Value fidelity of pass-through columns.** Not byte-identical.
`_split_csv_records` executes `text.replace("\r\n","\n").replace("\r","\n")` on
the **entire file text before parsing**, so the rewrite reaches inside quoted
fields (`plugins/_common/parser.py:237`). Every other transformation is absent:
`_safe_str` returns `str` unchanged (`parser.py:142-150`), no trimming, no
truncation, no re-encoding of cell values. **Header cells are `.strip()`ed**
(`parser.py:282`), so a column literally named `" year "` is renamed to `"year"`.
Output encoding is UTF-8 without BOM; line terminator **LF** (`exporters.py:84`).
Observed: all six records' `title`/`abstract`/`keywords`/`reviewer_note` matched
the CR-normalised intent exactly, and differed from the byte-identical intent
only in the three `CR`-bearing fields. **[observed]**

**5. Provenance of extra user columns.** Traced ingest → bundle → report:
`_clean_aggregate_csv` (`plugins/03_harmoniser/exporters.py:126-163`) reads with
`csv.reader`, writes the header verbatim and copies every integral row verbatim —
it validates *width* only, never column names. So arbitrary user columns land in
`data/current.csv` untouched. EH takes its whole header from that file
(`parser.py:282`) and writes `parse_header` back out. Observed: `reviewer_note`
present with correct values in `EH_FULL.csv`, `EH_SURVIVORS.csv` and
`data/current.csv`, and still present after IH, EL and IL. **[observed]**

**6. Evidence shape.** EH has **no evidence column**. Its entire audit output is
three `;`-joined id lists plus a sentence. There is no per-criterion record of
*which value* was compared or *why* it matched; that exists only in the
recomputed detail modal (`evaluator.py:170-337`), which is never written to disk.

**7. Contract as implemented.** *EH writes a FULL report over exactly the records
it was handed, in input order, with every input column passed through verbatim
except that all carriage returns have been rewritten to line feeds, plus five
`eh_`-prefixed decision columns; and a SURVIVORS report that is schema-identical
to its input and byte-identical to the `data/current.csv` it hands to the next
stage.* Internal inconsistencies: it updates only one of the manifest's two stage
maps; its `SURVIVORS`/`current.csv` duplication is real duplication of bytes
rather than a reference; and its criterion-id separator (`;`) disagrees with
EL/IL's (`,`).

### Stage 05 — IH

`plugins/05_ih/ui.py` differs from `plugins/04_eh/ui.py` by **stage literals
only** — verified by full diff: every hunk is a docstring, a widget label, a
`stage=` argument, or an `eh_`→`ih_` prefix. There is no logic difference in the
UI layer.

**1. Files written.** Identical set to EH with `IH` substituted:
`reports/IH_FULL.csv`, `reports/IH_SURVIVORS.csv`, `data/current.csv`,
`manifest.json`, conditional `data/input_errors.csv`, everything else copied.
`created_by` becomes `screen_a_ih_plugin`. Observed IH bundle also carried
`EH_FULL.csv` / `EH_SURVIVORS.csv` forward untouched. **[observed]**

**2. Row universe.** FULL = the **EH survivors**, not the corpus. Observed 5 in →
5 FULL → 4 SURVIVORS; the record EH excluded (`R6`) does not appear anywhere in
IH's reports. **[observed]** Same ordering, same dedup/skip rules (shared
`_parse_csv_tolerant_text`).

**3. Columns.** `parse_header + ["ih_outcome","ih_failed_ids","ih_missing_ids",
"ih_met_ids","ih_reason_summary"]`. Same classification as EH. **One real
difference from EH:** `ih_missing_ids` is the union of *missing* and *unknown*
criterion ids, not missing alone (`plugins/_common/runner.py:199-203`). So the
same column name carries a different meaning at 04 and 05, and a record with an
`UNKNOWN` criterion is indistinguishable in the CSV from one with a `MISSING`
criterion.

**4. Fidelity.** Identical to EH — same parser, same writer, same CR
normalisation, LF terminator, UTF-8 no BOM. Observed identical fidelity result.

**5. Extra user columns.** Survive; `reviewer_note` verified present and correct
in both IH reports. **[observed]**

**6. Evidence shape.** Same as EH: none. Note also the **outcome policy differs**
(`runner.py:177-194`): EH is strict (`PASS_CLEAN` iff every criterion is `MET`
with nothing missing or unknown), IH is lenient (`PASS_FLAGGED` only if something
is unknown or missing). Same column names, different semantics.

**7. Contract as implemented.** *IH writes the same report shape as EH over the
records EH let through, with the same verbatim-except-CR pass-through, but its
`ih_missing_ids` column silently merges two distinct states and its
`PASS_CLEAN` bar is lower than EH's.* The inconsistency worth naming is that
`{stage}_missing_ids` is a single column name with two different definitions
across two stages that a reviewer will read side by side in the same bundle.

### Stage 06 — EL

**1. Files written into the bundle** (`plugins/_common/bundle.py:465-592`, called
from `plugins/06_el/ui.py:1066` and from `plugins/06_el/standalone.py:468`):

| Path in bundle | Writer | Condition |
|---|---|---|
| `manifest.json` | `json.dumps(..., indent=2)`, `bundle.py:575` (no trailing newline, unlike EH/IH) | always |
| `data/current.csv` | `_dict_csv_bytes`, `bundle.py:519` | always |
| `reports/EL_FULL.csv` | `_dict_csv_bytes`, `bundle.py:520` | always |
| `reports/EL_SURVIVORS.csv` | `_dict_csv_bytes`, `bundle.py:521` | always |
| `data/input_errors.csv` | `merge_input_errors_csv`, `bundle.py:515-525` | only if non-empty |
| `cache/EL_cache.jsonl` | `_dump_cache_to_jsonl`, `bundle.py:526-527` | only when "Use cache" is ticked |
| *(all other members)* | copied verbatim, `bundle.py:583-586` | always |

Manifest fields: `pipeline.stages["EL"]` **and** `pipeline_state.stages["EL"]`
(`bundle.py:539-556`), a `pipeline.history` entry (`bundle.py:558-566`),
refreshed `sha256` for every written member, `updated_at` from the caller. No
`created_by`, no `derived_from`.

GUI-only emission sites: `EL_reports.xlsx` (`plugins/06_el/ui.py:196-269`),
`input_errors.csv` in the **legacy two-column layout**
(`plugins/06_el/ui.py:983-987`), and in the standalone shell `EL_FULL.csv` via
`_write_csv` (`plugins/06_el/screen.py:157-163`, invoked at `standalone.py:382`
and `:408,415`).

**2. Row universe.** FULL = the **IH survivors**. Observed 4 in → 4 FULL → 3
SURVIVORS. **[observed]** Records excluded at EH or IH are absent. Ordering
preserved. Dedup/skip is EL's own and differs from EH/IH: `_load_bundle`
(`plugins/06_el/screen.py:207-219`) diverts empty and duplicate `local_id` to
`parse.skipped` — but **ragged rows are silently padded or truncated** by
`_csv_read` (`screen.py:148-154`) rather than skipped. Verified: a 4-cell row
against a 3-column header yields `{'local_id':'X1','a':'1','b':'2'}` from EL,
while EH skips the same row as `bad_column_count`. **[observed]**

**3. Columns.** `header + ["el_outcome","el_failed_ids","el_missing_ids",
"el_met_ids","el_uncertain_ids","el_reason_summary","el_evidence_json"]`
(`plugins/06_el/ui.py:1057-1060`), where `header` is `parse.header` with
`local_id` force-prepended if absent (`ui.py:1053-1055`).

| Column | Class |
|---|---|
| every incoming column, original order | **pass-through**, byte-identical at this stage |
| `el_outcome` | stage-added: `OUT` / `PASS_CLEAN` / `PASS_FLAGGED` / `NOT_SCREENED` |
| `el_failed_ids`, `el_missing_ids`, `el_met_ids`, `el_uncertain_ids` | stage-added, ids joined with **`,`** (`screen.py:651-654`) — note the separator differs from EH/IH's `;` |
| `el_reason_summary` | stage-added free text (`screen.py:675-687`) |
| `el_evidence_json` | stage-added: `json.dumps` of `{criterion_id: {...}}` (`screen.py:655`) |

`el_uncertain_ids` and `el_evidence_json` have **no counterpart at EH/IH**.
Input columns dropped: none.

**4. Value fidelity.** EL's own reads are byte-preserving: `_csv_read` uses
`csv.reader` (`screen.py:139-155`) and preserves `CR`, `CRLF` and embedded `LF`
verbatim; `_dict_csv_bytes` uses the default `\r\n` terminator
(`bundle.py:458`), which **does** quote lone `CR`. Header cells are stripped
(`screen.py:146`). Observed: the three `CR` differences visible in `EL_FULL.csv`
were **inherited from EH**, not introduced by EL. **[observed]**

One divergence worth flagging: EL decodes with
`b.decode("utf-8-sig", errors="replace")` (`screen.py:111-113`), a single
attempt. EH/IH try `utf-8-sig → utf-8 → cp1252 → latin-1` in turn
(`parser.py:217-223`). A cp1252-encoded bundle that EH reads correctly is
silently turned into U+FFFD replacement characters by EL. **[inference from
source; not exercised in the run]**

**5. Extra user columns.** Survive. `reviewer_note` verified present and correct
in `EL_FULL.csv`, `EL_SURVIVORS.csv` and `data/current.csv`. **[observed]**

**6. Evidence shape.** This is where the LLM and non-LLM branches genuinely
diverge. `el_evidence_json` is an object keyed by criterion id, each value
carrying `status`, `decision`, `confidence`, `threshold`, `field`, `quote`,
`quote_valid`, `span`, `used` (`screen.py:630-640`). For a criterion whose
targets are all empty the value is `{"status":"MISSING"}` (`screen.py:587`); for
a non-`llm` operator it is `{"status":"UNCERTAIN","note":"non-llm operator in EL
stage"}` (`screen.py:593`). EH/IH write nothing comparable.

**7. Contract as implemented.** *EL writes a FULL report over the records IH let
through, pass-through columns byte-identical to what it received, plus seven
`el_`-prefixed columns of which one is a JSON evidence blob keyed by criterion.*
Internal inconsistencies: the id separator is `,` where EH/IH use `;`; ragged
rows are repaired rather than rejected, which is the opposite of EH/IH's policy
on the same file; the report CSVs use `CRLF` where EH/IH use `LF`, so a single
bundle contains reports with two different line terminators; and the GUI's
`input_errors.csv` button writes a schema the shared reader was specifically
built to replace.

### Stage 07 — IL

`plugins/07_il/screen.py` differs from `plugins/06_el/screen.py` only in stage
literals **plus two real behavioural deltas**: `OUTCOMES` replaces
`PASS_FLAGGED` with `REVIEW` (`07_il/screen.py:70`), and the non-`OUT`,
non-`PASS_CLEAN` outcome is `REVIEW` (`07_il/screen.py:649`). Verified by full
diff.

**1. Files written.** Everything EL writes, with `IL` substituted, **plus**:

| Path in bundle | Writer | Condition |
|---|---|---|
| `reports/ScreenA_Report.xlsx` | `_build_final_report_xlsx_bytes`, passed as `extra_members` (`plugins/07_il/ui.py:1331-1334`) | always |

Observed IL bundle members: the two IL reports, `data/current.csv`,
`cache/IL_cache.jsonl`, `reports/ScreenA_Report.xlsx`, plus all six earlier-stage
reports and `cache/EL_cache.jsonl` copied forward, and a `sha256` map covering
13 files. **[observed]**

**2. Row universe.** FULL = the **EL survivors**. Observed 3 in → 3 FULL → 1
SURVIVOR. **[observed]** Same padding-not-skipping behaviour as EL.

**3. Columns.** `header + ["il_outcome","il_failed_ids","il_missing_ids",
"il_met_ids","il_uncertain_ids","il_reason_summary","il_evidence_json"]`
(`plugins/07_il/ui.py:1305-1308`). Classification identical to EL. Input columns
dropped: none.

**4. Value fidelity.** Identical mechanism to EL — byte-preserving reads,
`CRLF`-terminated `_dict_csv_bytes` writes, same single-attempt decode. Observed:
`IL_SURVIVORS.csv` matched the **byte-identical** original intent exactly,
because the one surviving record happened to carry no `CR`. **[observed]**

**5. Extra user columns.** Survive to the terminal stage. `reviewer_note` correct
in `IL_FULL.csv`, `IL_SURVIVORS.csv` and `data/current.csv`, and present in the
FINAL sheet's meta columns. **[observed]**

**6. Evidence shape.** Same JSON structure as EL under the `il_` prefix. Note
`_summarize_el_reason` is reused verbatim under its EL name
(`07_il/screen.py:677`), emitting `"REVIEW:"` as its prefix.

**7. The final workbook — its own contract, and it is broken.**
`_build_final_report_xlsx_bytes` (`plugins/07_il/ui.py:368-483`) writes five
sheets:

- **Sheets `EH` / `IH` / `EL` / `IL`.** Header is
  `CONTRACT_STAGE_SHEET_COLS = ["local_id","outcome","fail_criteria_ids",
  "missing_criteria_ids","uncertain_criteria_ids","reason","decided_at"]`
  (`plugins/07_il/plugin.py:56-59`). Rows come from
  `_extract_contract_stage_row` (`plugins/07_il/ui.py:322-349`), which returns
  keys `a_id`, `stage`, `stage_outcome`, `passed_to_next`, `failed_criteria_ids`,
  `missing_criteria_ids`, `uncertain_criteria_ids`, `met_criteria_ids`,
  `matched_evidence`, `stage_reason_summary`, `history`. Only
  `missing_criteria_ids` and `uncertain_criteria_ids` intersect the header —
  **`local_id`, `outcome`, `fail_criteria_ids`, `reason` and `decided_at` can
  never be populated**, because `ws.append([row_obj.get(c, "") ...])`
  (`ui.py:437`) silently yields `""`. Observed: on all four stage sheets every
  data cell read back as `None`, with a single exception (`IH` row 5,
  `missing_criteria_ids = "IC-2"`). Row *counts* are right; the content is not.
  **[observed]**
- **Sheet `FINAL`.** Header
  `["a_id"] + meta_cols + [outcome/reason × 4 stages, final_outcome,
  final_reason_summary, history]` (`ui.py:441-449`). Outcomes and reasons **are**
  correct — they are read from the earlier-stage `*_FULL.csv` files in the bundle
  (`ui.py:379-388`), so the union of ids covers the whole corpus. Observed: all
  six records present, `R6 → OUT at EH`, `R5 → OUT at IH`, `R1 → OUT at EL`,
  `R2`/`R3 → OUT at IL`, `R4 → REVIEW`. **[observed]**
  But `meta_cols` comes from `_load_master_rows`, which tries
  `data/A.csv`, `data/original.csv`, `data/aggregate.csv`, `data/current.csv` in
  order (`ui.py:298-315`) — and the Harmoniser only ever writes
  `data/current.csv` (`plugins/03_harmoniser/bundle.py:98`). So the "master list"
  is always the **terminal survivor set**, and every record excluded before IL
  gets blank title/abstract/keywords. Observed: `R1`, `R5`, `R6` have `None` for
  all seven metadata columns while `R2`, `R3`, `R4` are fully populated.
  **[observed]** `history` is written as `""` everywhere (`ui.py:348`,
  `ui.py:468`).

**Contract as implemented.** *IL writes the same seven-column report shape as EL
over the records EL let through, relabelling `PASS_FLAGGED` as `REVIEW`, and
additionally emits a five-sheet cross-stage workbook whose FINAL sheet is correct
for outcomes and blank for the metadata of any record excluded before IL, and
whose four per-stage sheets are structurally empty.* The workbook is the only
artefact in the pipeline that reports on the corpus as a whole, and it is the one
with the least evidence behind it.

---

## Part B — CSV structural integrity

### B.1 Inventory

**Write sites in scope.** All are the Python `csv` module — no manual string
building anywhere in stages 03–07.

| # | Site | Mechanism | Quoting | Terminator | `newline=''` | Encoding | Writes to |
|---|---|---|---|---|---|---|---|
| W1 | `plugins/_common/exporters.py:82-88` `_write_csv_bytes` | `csv.DictWriter`, `extrasaction="ignore"` | default `QUOTE_MINIMAL` | **`\n`** | n/a (`StringIO`) | UTF-8, no BOM | EH/IH `*_FULL.csv`, `*_SURVIVORS.csv`, `data/current.csv` (in zip) |
| W2 | `plugins/_common/input_errors.py:106-118` `write_input_errors_csv` | `csv.DictWriter` | default | **`\n`** | n/a (`StringIO`) | UTF-8 | `data/input_errors.csv` for Harmoniser + all four stages |
| W3 | `plugins/_common/exporters.py:46-57` `_export_input_errors_csv` | wraps W2 | — | `\n` | **yes** | UTF-8 | EH/IH "Export input_errors.csv…" button |
| W4 | `plugins/_common/bundle.py:450-462` `_dict_csv_bytes` | `csv.DictWriter`, `extrasaction="ignore"` | default | **`\r\n`** (default) | n/a (`StringIO`) | UTF-8 | EL/IL `*_FULL.csv`, `*_SURVIVORS.csv`, `data/current.csv` (in zip) |
| W5 | `plugins/06_el/screen.py:157-163` / `plugins/07_il/screen.py:159-165` `_write_csv` | `csv.DictWriter`, `extrasaction="ignore"` | default | `\r\n` | **yes** | UTF-8 | EL/IL standalone "Export {EL,IL}_FULL.csv" |
| W6 | `plugins/06_el/ui.py:983-987` | inline `csv.writer` | default | **`\n`** | **yes** | UTF-8 | EL "Export input_errors.csv…" button — **legacy `reason,row_json` schema** |
| W7 | `plugins/07_il/ui.py:1231-1235` | inline `csv.writer` | default | **`\n`** | **yes** | UTF-8 | IL "Export input_errors.csv…" button — same legacy schema |
| W8 | `plugins/03_harmoniser/exporters.py:137-162` `_clean_aggregate_csv` | `csv.writer` | default | `\r\n` | **yes** | UTF-8 | `data/current.csv` (ingest) |
| W9 | `plugins/03_harmoniser/exporters.py:73-89` `_export_csv` | `csv.DictWriter` | default | `\r\n` | **yes** | UTF-8 | `criteria/criteria_harmonized.csv` |

Non-CSV emission sites in scope, listed for completeness: `_export_xlsx`
(`exporters.py:59-80`), `_export_el_xlsx` (`06_el/ui.py:196-269`),
`_export_il_xlsx` (`07_il/ui.py:203-276`), `_build_final_report_xlsx_bytes`
(`07_il/ui.py:368-483`), `_dump_cache_to_jsonl`
(`_common/llm_client.py:528-532`).

**Read sites that re-ingest these files.**

| # | Site | Mechanism | Notes |
|---|---|---|---|
| R1 | `plugins/_common/parser.py:230-269` `_split_csv_records` | **hand-rolled quote-aware scanner** | normalises `\r\n`/`\r` → `\n` over the whole text first (`:237`); then splits on unquoted `\n`. Correct on every hostile case tested |
| R2 | `plugins/_common/parser.py:272-329` `_parse_csv_tolerant_text` | `csv.reader` per record | rejects ragged rows, blank records, missing/duplicate `local_id` |
| R3 | `plugins/06_el/screen.py:139-155` / `07_il/screen.py:141-157` `_csv_read` | `csv.reader` over whole text | pads/truncates ragged rows instead of rejecting |
| R4 | `plugins/_common/input_errors.py:121-164` `read_input_errors` | `csv.DictReader` | **never raises** — any exception yields `[]` (`:156-157`) |
| R5 | `plugins/_common/parser.py:360-437` `_load_criteria_from_text` | `csv.DictReader` | criteria table |
| R6 | `plugins/06_el/screen.py:255-350` `_parse_criteria_harmonized_csv` | via R3 | criteria table, EL/IL variant |
| R7 | `plugins/07_il/ui.py:311-315` `_load_csv_rows_from_zip` | via R3 | reads prior stages' `*_FULL.csv` for the final workbook |
| R8 | `plugins/_common/llm_client.py:512-526` `_load_cache_from_jsonl` | `.splitlines()` + `json.loads` | JSONL, **not** CSV — safe |

**Tab-table population reader: there is none.** See Part C.2.

### B.2 Static red flags

- **No manual comma-joins, no `.split(',')` over a CSV body, no `.splitlines()`
  over a CSV body, no regex row parsing** anywhere in stages 03–07. The one
  `.splitlines()` (`llm_client.py:514`) is over JSONL. The `.split(",")` calls
  (`_common/parser.py:164`, `06_el/standalone.py:541`, `07_il/standalone.py:541`)
  operate on single already-parsed *cells*, not on file text.
- **Every disk write that opens a file passes `newline=''`.** Verified by grep
  across `plugins/`: W3, W5, W6, W7, W8, W9 all do. There is therefore **no
  `\r\r\n` risk from text-mode translation**, and none was found in any emitted
  file. **[observed]**
- **Red flag: `lineterminator="\n"` at W1, W2, W3, W6, W7.** See B.4/B.6 — this
  is the one genuine writer defect.
- **Red flag: `read_input_errors` swallows every exception**
  (`input_errors.py:156-157`). Combined with the above, a structurally invalid
  audit file reads back as "no records were dropped" rather than as an error.
- **Red flag (mild): R1 is a hand-rolled CSV scanner** where `csv.reader` would
  do. It behaved correctly on all hostile inputs tested, but it is the only
  non-stdlib parser in the chain and it is the site of the CR normalisation.
- **Inconsistency: two line terminators in one bundle.** EH/IH reports are `LF`,
  EL/IL reports are `CRLF`, the criteria table is `CRLF`. Confirmed on the IL
  bundle. **[observed]**

### B.3 The empirical run

**Everything below was executed from a scratch directory outside the repository,
which has been removed. Nothing in the repository was written to except this
document.**

*Synthetic corpus* — 8 columns
`local_id,title,abstract,keywords,year,lang,doc_type,reviewer_note`, where
`reviewer_note` is the non-standard extra user column required by A.5. Six
records:

| id | hostile content carried |
|---|---|
| `R1` | embedded **`LF`** in `title`; semicolons in `keywords`; comma **and** semicolon in `reviewer_note` |
| `R2` | embedded **`CRLF`** in `title`; **lone `CR`** in `abstract`; commas in `keywords`; `CRLF` in `reviewer_note` |
| `R3` | **balanced** double quotes in `title`; **unbalanced** double quote in `abstract`; unbalanced quote in `reviewer_note` |
| `R4` | leading/trailing whitespace in `title`; accented + non-ASCII (`É`, `ç`, `à`, `—`) in `title`/`keywords`; **very long abstract** (~9 000 chars) |
| `R5` | **empty abstract**; commas in `title` |
| `R6` | `year=1990`, `"RETRACTED"` in title — the EH exclusion bait |

*Criteria* (six rows, two per deterministic stage, one per LLM stage), written
through the real Harmoniser criteria writer:
EH `EC-1` exclude `lte year 1999`, EH `EC-2` exclude `contains title "retracted"`,
IH `IC-1` include `in_list lang en;fr`, IH `IC-2` include
`contains abstract "cognition"`, EL `EC-L1` exclude `llm`, IL `IC-L1` include
`llm`.

*Commands invoked* (no GUI, no Tkinter object, no network):

1. **Ingest / bundle build** — the real function, not a re-implementation:
   `plugins.03_harmoniser.bundle.export_screen_a_bundle(rows=…, a_path=corpus,
   a_columns=…, a_id_col_guess="local_id", …)`.
2. **EH** — the non-widget half of `EHView._load_bundle_inputs` +
   `_run_clicked` + `_export_bundle_clicked`, i.e.
   `plugins._common.bundle._load_bundle` →
   `parser._decode_bytes` → `parser._parse_csv_tolerant_text(text,
   required_id="local_id")` → `parser._load_input_errors_from_text` merged into
   `ParseReport.skipped` → `parser._load_criteria_from_text(text, stage="EH")` →
   `runner.run_screen(..., stage="EH")` →
   `bundle._export_next_bundle_zip(..., stage="EH")`.
3. **IH** — identical with `stage="IH"`, over the EH output bundle.
4. **EL** — `plugins.06_el.screen._load_bundle` →
   `screen.run_el_screen(..., use_cache=True, cache_in=<replay cache>)` →
   `bundle._write_llm_stage_bundle(..., stage="EL")`, over the IH output bundle.
5. **IL** — identical with `run_il_screen` / `stage="IL"`, plus
   `plugins.07_il.ui._build_final_report_xlsx_bytes` passed as `extra_members`,
   over the EL output bundle.

**On the LLM stages.** The suite has no mock LLM *client*, but it does have a
mock LLM *mechanism*, and it is the one `tests/test_el_regression.py` uses: with
`OPENAI_API_KEY` unset, `_has_openai_key()` is False and
`run_m1_llm_for_criterion` returns nothing, so **every verdict must come from the
cache**. I built a replay cache keyed exactly as `screen._cache_key` keys it
(rendered-prompt hash), with fabricated verdicts including a deliberately hostile
evidence quote (`evidence "x", y; z\nsecond line`). Both EL and IL therefore ran a
full stage headlessly with zero API calls. This is the same harness shape as
`tests/test_el_regression.py::_el_to_csv`.

*Result:* `EH 6→5`, `IH 5→4`, `EL 4→3`, `IL 3→1`. FULL and SURVIVORS are
non-trivial at every stage. Counts: EH `{OUT:1, PASS_CLEAN:5}`, IH
`{OUT:1, PASS_CLEAN:4}`, EL `{OUT:1, PASS_CLEAN:3}`, IL
`{OUT:2, PASS_CLEAN:1, REVIEW:0}`. **[observed]**

### B.4 Per-file structural verification

For each of the 22 CSVs written across the five bundles:

| Check | Result |
|---|---|
| bytes contain `\r\r\n` | **no**, every file |
| logical record count (`csv.reader`) matches the expected record set, ids and order | **yes**, every file |
| each input record occupies exactly **one** logical CSV record | **yes**, every file |
| field-for-field equality on read-back against intended values | **yes**, modulo the documented CR→LF normalisation applied at EH |
| extra user column `reviewer_note` present and correct | **yes**, all four stages |
| next stage re-read the file without corrupting any field | **yes** — IH read EH's output, EL read IH's, IL read EL's, and the fidelity comparison held at each hop |
| manifest `sha256` matches the bytes actually in the zip | **matches**, every written member, every bundle |

**Logical vs naive record counts** (a line-based reader would see phantom rows):

| Bundle | File | logical | naive non-empty lines |
|---|---|---:|---:|
| harmoniser | `data/current.csv` | 7 | 10 |
| EH | `reports/EH_FULL.csv` | 7 | 11 |
| EH | `reports/EH_SURVIVORS.csv` = `data/current.csv` | 6 | 10 |
| IH | `reports/IH_FULL.csv` | 6 | 10 |
| IH | `reports/IH_SURVIVORS.csv` = `data/current.csv` | 5 | 9 |
| EL | `reports/EL_FULL.csv` | 5 | 9 |
| EL | `reports/EL_SURVIVORS.csv` = `data/current.csv` | 4 | 7 |
| IL | `reports/IL_FULL.csv` | 4 | 7 |
| IL | `reports/IL_SURVIVORS.csv` = `data/current.csv` | 2 | 2 |

The gap is exactly the number of embedded newlines and is **correct behaviour** —
it is what a quoted multi-line field looks like on disk. It is listed here
because it is the number any line-based external tool will get wrong.

**The one structural failure found.** `csv.writer` / `csv.DictWriter` configured
with `lineterminator="\n"` does not quote a field containing a lone `CR`:

```
lineterminator="\n"    -> b'lone\rCR,next\n'        csv.reader RAISES _csv.Error
lineterminator="\r\n"  -> b'"lone\rCR",next\r\n'    csv.reader -> [['lone\rCR','next']]
```

Reproduced end-to-end through the real ingest path: a corpus record that is both
ragged **and** contains a lone `CR` produces

```
stage,record_number,reason,observed_len,expected_len,raw
Harmoniser,3,wrong_column_count,4,3,G2 | pre<CR>post | 2022 | SURPLUS
```

`csv.reader` raises on that file; `read_input_errors()` catches the exception and
returns `[]`. **[observed]** The reports themselves are not reachable this way
because EH strips every `CR` before writing — but that is an accident of ordering,
not a guard, and it disappears the moment a bundle is opened directly at EL.

**A second `input_errors.csv` defect, unrelated to quoting.** EH/IH merge the
carried-forward entries into `ParseReport.skipped` (`04_eh/ui.py:444-449`) and
then hand that whole merged list to `from_tuple_skipped(skipped, stage="EH")`
(`bundle.py:373`), which **re-stamps prior stages' entries with the current
stage** and drops their `observed_len`/`expected_len`. Because
`merge_input_errors_csv` keys on `stage`, the copies do not collapse. One
malformed record produced 1 row after the Harmoniser, 2 after EH, 3 after IH.
**[observed]** EL/IL do not inflate it further, because their `_load_bundle`
never merges the prior file into `parse.skipped`.

**A third, minor.** `write_input_errors_csv` argues in its own docstring that a
header-only file is a meaningful claim ("a file that exists and says no records
were dropped is a different claim from no file") — but both bundle writers gate
on `if read_input_errors(merged)` (`bundle.py:374`, `bundle.py:524`), so the
header-only file is never written. Observed: no `data/input_errors.csv` in any of
the four stage bundles from the clean corpus. **[observed]**

### B.5 Have the goldens ever exercised this content class?

**Partly — by accident, and the accident is informative.**

| Golden | logical records | fields with embedded `LF` | fields with `CR` | fields with `"` |
|---|---:|---:|---:|---:|
| `docs_/samples/20260122_1654_aggregate.csv` (input) | 777 | 15 | **4** | 56 |
| `tests/golden/eh_filtered_v3.1.0.csv` | 777 | 15 | **0** | 56 |
| `tests/golden/ih_filtered_v3.1.0.csv` | 777 | 15 | **0** | 56 |
| `tests/golden/el_input_v3.1.0.csv` | 86 | 1 | 0 | 5 |
| `tests/golden/el_filtered_v3.1.0.csv` | 86 | 1 | 0 | 90 |
| `tests/golden/il_filtered_v3.1.0.csv` | 85 | 1 | 0 | 89 |
| `tests/golden/criteria_harmonized_v3.1.0.csv` | 9 | 0 | 0 | 0 |
| `tests/data/{el,il}_eval_fixture.csv` | 31 | 0 | 0 | 0 |

So embedded newlines and quotes **are** present in the byte-identity goldens, and
the byte-identity assertion does pin them. But nothing *names* that content class
as a test subject, and the `4 → 0` collapse in the `CR` column is the CR
normalisation of `parser.py:237` sitting in a committed golden, undocumented and
unasserted. No golden contains a lone `CR`, an unbalanced quote, or a
semicolon-heavy field, and no test exists for the `input_errors.csv` writer under
hostile content.

### B.6 Defect classification

**(W) — writer emits structurally invalid CSV.**
- **W-1.** `lineterminator="\n"` leaves a lone `CR` unquoted, producing a file
  `csv.reader` refuses. Sites: `_common/exporters.py:84`,
  `_common/input_errors.py:114`, `06_el/ui.py:984`, `07_il/ui.py:1232`.
  Demonstrated end-to-end on `data/input_errors.csv`; latent on the EH/IH
  reports only because EH normalises `CR` away first. **[observed]**

**(R) — writer valid, an internal reader mis-parses.**
- **None found.** Every internal reader in the chain used the `csv` module or the
  quote-aware scanner, and every hostile field round-tripped. The hand-rolled
  `_split_csv_records` handled balanced quotes, escaped quotes, unbalanced quotes
  written by a conforming writer, and embedded newlines correctly.
- Two *near*-misses worth recording because they are policy divergences, not
  parse failures: EL/IL silently repair ragged rows that EH/IH reject
  (`06_el/screen.py:148-154` vs `parser.py:305-307`), and EL/IL's single-attempt
  `errors="replace"` decode (`06_el/screen.py:113`) will mojibake a cp1252 bundle
  that EH/IH decode correctly (`parser.py:217-223`).

**(D) — writers and readers valid, the tab-table population builds wrong
row/column structure.**
- **None found.** The row-preparation expression was executed headlessly against
  the hostile FULL report: arity equalled the column count for every row, and
  every value was byte-identical to the CSV cell. See C.4.
- One residual, unresolvable without a window: two cells (`R1.title`,
  `R2.title/abstract/reviewer_note`) carried a raw `\n` into
  `Treeview.insert(values=…)`. See the open questions.

**(V) — all internal paths valid, the file displays broken in an external
viewer.** **This is the class that explains the reported symptom.**
- **V-1 — delimiter mismatch fragments records.** Re-parsing the emitted reports
  with `;` as the delimiter — the Excel default under a French-Canada locale —
  gives:

  | file | comma-parse | semicolon-parse |
  |---|---|---|
  | `EH_FULL.csv` | 7 records × 13 columns | **11 records** × 5 columns |
  | `EL_FULL.csv` | 5 records × 15 columns | **9 records** × 5 columns |

  The mechanism: with `;` as the delimiter, the `"` that opens a quoted field is
  no longer at a field boundary, so quoting is not recognised, so every embedded
  newline terminates a record. The extra rows are exactly the records with
  multi-line metadata. **[observed — with Python's `csv` module as the proxy for
  Excel, see the open questions]**
- **V-2 — no BOM.** Every emitted CSV is UTF-8 **without** a BOM
  (`exporters.py:88`, `bundle.py:462`). Excel's double-click path on Windows
  historically applies the ANSI codepage to a BOM-less CSV, which mojibakes
  accented metadata. Not measured here. **[inference]**
- **V-3 — mixed line terminators in one bundle.** EH/IH reports `LF`, EL/IL
  reports `CRLF`. Some Windows tooling treats a bare-`LF` CSV as a single line.
  **[observed for the terminators; the viewer consequence is inference]**

**Which class explains "one record's metadata overflowed onto adjacent rows"?**

**In a spreadsheet: (V), almost certainly V-1.** It reproduces the symptom
exactly, on the actual bytes this software emits, for exactly the records with
multi-line metadata, under exactly the locale named in the brief. Nothing about
the file is wrong; the reader is being told the wrong delimiter.

**In the tab's table: no supported mechanism was found.** (D) was tested and came
back clean; (R) came back clean; (W) is not reachable on the report path. If the
user saw it *in the tab*, the only remaining candidate is Tk's own rendering of a
newline inside a `Treeview` cell, which cannot be settled without looking at a
window.

**(W-1) is a real defect regardless of the reported symptom** — it silently
destroys the audit trail rather than the display, which is worse.

---

## Part C — the in-tab results table

### C.1 Where the table is built, and what it is

Every stage uses a `ttk.Treeview` wrapped in a class named `DataTable`. There are
**three separate copies** of that class:

| Stage | Class | Treeview created at | full / survivors tables instantiated at |
|---|---|---|---|
| **EH** | `plugins/_common/widgets.py:38-110` | `widgets.py:51` | `plugins/04_eh/ui.py:298`, `:301` |
| **IH** | same shared class | `widgets.py:51` | `plugins/05_ih/ui.py:298`, `:301` |
| **EL** | **private copy** `plugins/06_el/ui.py:82-189` | `06_el/ui.py:116` | `06_el/ui.py:421`, `:424` |
| **IL** | **private copy** `plugins/07_il/ui.py:89-196` | `07_il/ui.py:123` | `07_il/ui.py:638`, `:641` |

The EL/IL copies add a legacy positional-columns constructor
(`06_el/ui.py:102-112`), `set_rows` / `get_selected_row`
(`06_el/ui.py:170-182`), and a different render chunk size (`RENDER_CHUNK` 400 at
`06_el/plugin.py:42` vs 300 at `widgets.py:35`). Each stage also builds two more
`DataTable`s: the criteria panel (`04_eh/ui.py:269`, `05_ih/ui.py:269`,
`06_el/ui.py:370`, `07_il/ui.py:587`) and the per-row detail modal
(`04_eh/ui.py:819`, `05_ih/ui.py:819`, `06_el/ui.py:773`, `07_il/ui.py:991`).

### C.2 Data source — in-memory, all four stages, no re-read

| Stage | Populated from | Set at | Re-reads a CSV? |
|---|---|---|---|
| **EH** | `self.full_rows` / `self.survivors`, the engine's return value | `04_eh/ui.py:690-691` (in `_finish_run`), consumed at `:750,760,781,784` | **No** |
| **IH** | same | `05_ih/ui.py:690-691`, consumed at `:750,760,781,784` | **No** |
| **EL** | same | `06_el/ui.py:892-893` (in the worker), consumed at `:686,696,717,720` | **No** |
| **IL** | same | `07_il/ui.py:1110-1111`, consumed at `:904,914,935,938` | **No** |

There is no disk or ZIP read anywhere in `_refresh_reports_view` at any of the
four stages. The table is a view of the same dict objects the CSV writer will
later serialise, so **the display cannot drift from the report**, and equally,
**a display defect cannot be a re-parse defect**.

### C.3 Displayed columns vs the FULL report CSV

| Stage | Displayed full-report columns | vs the CSV |
|---|---|---|
| **EH** | `header + eh_outcome, eh_failed_ids, eh_missing_ids, eh_met_ids, eh_reason_summary` (`04_eh/ui.py:747`) | **identical** to `bundle.py:350-352` |
| **IH** | same with `ih_` (`05_ih/ui.py:747`) | **identical** |
| **EL** | `header + el_outcome, el_failed_ids, el_missing_ids, el_met_ids, el_uncertain_ids, el_reason_summary` (`06_el/ui.py:681-683`) | **subset** — `el_evidence_json` is in the CSV (`06_el/ui.py:1059`) but not on screen |
| **IL** | same with `il_` (`07_il/ui.py:899-900`) | **subset** — `il_evidence_json` omitted |

Survivors tables display `list(header)` at all four stages
(`04_eh/ui.py:748`, `06_el/ui.py:684`) — identical to the SURVIVORS CSV header.
No renaming anywhere.

**Per-cell formatting: none.** The only transformation is
`_safe_str(r.get(c, ""))` (`widgets.py:94`, `06_el/ui.py:162`,
`07_il/ui.py:169`), which returns a `str` unchanged. **No truncation, no newline
substitution, no escaping** is applied before the value reaches the widget. The
one truncation in the whole display path is cosmetic and lives in the detail
modal's title label: `title[:250]` (`04_eh/ui.py:806`, `06_el/ui.py:760`).

EL/IL's row-detail modal compensates for the omitted evidence column by parsing
`{stage}_evidence_json` and rendering one row per criterion
(`06_el/ui.py:778-811`). EH/IH's modal instead **recomputes** the per-criterion
evaluation from scratch via `_eval_criterion_detail` (`04_eh/ui.py:828`) —
i.e. what the modal shows at EH/IH is not read from the report at all.

### C.4 Row integrity from source — tested headlessly

The row-preparation logic **is** separable from widget instantiation: it is the
single expression `vals = [_safe_str(r.get(c, "")) for c in self.columns]`
(`widgets.py:94`). I extracted that expression verbatim and ran it, with no Tk
object created, over the real `EH_FULL.csv` produced by the hostile run, using
the exact column list `EHView._refresh_reports_view` builds (`04_eh/ui.py:747`).

Result over 6 rows × 13 columns: **0 arity defects, 0 value alterations.** Every
row produced exactly 13 values; every value was byte-identical to the CSV cell.
A field containing an embedded newline, an unbalanced quote, a comma, a semicolon
or a 9 000-character body produces **one** widget row with **one** value per
column. **[observed]**

Two rows carried a raw `\n` into the widget: `R1` (`title`) and `R2` (`title`,
`abstract`, `reviewer_note`). What `ttk.Treeview` *draws* for such a value is not
determinable from source and is listed as a human-observation request.

The same expression is used identically by both EL/IL copies
(`06_el/ui.py:162`, `07_il/ui.py:169`), so the conclusion transfers. Note that
the EL/IL private copies differ from the shared one only in the legacy
constructor and the two extra helpers — the render path is character-identical.

### C.5 The GUI export path as a distinct emission site

| Stage | Action | Writer | Same code as the bundle writer? |
|---|---|---|---|
| EH / IH | "Export XLSX…" | `_export_xlsx` (`_common/exporters.py:59-80`) | **No** — different code, but it derives its columns from the same `aggregate_header + 5` rule, so the schema agrees |
| EH / IH | "Export input_errors.csv…" | `_export_input_errors_csv` → `write_input_errors_csv` (`exporters.py:46-57`) | **Yes** — same canonical writer the bundle uses |
| EL | "Export XLSX…" | `_export_el_xlsx` (`06_el/ui.py:196-269`) | **No — a duplicate that has drifted.** It force-prepends `local_id`, and appends "extras" discovered from `full_rows[0].keys()` only (`:244`), so the column set depends on the first row |
| IL | "Export XLSX…" | `_export_il_xlsx` (`07_il/ui.py:203-276`) | **No** — same duplicate, `il_` prefixes |
| **EL** | **"Export input_errors.csv…"** | **inline `csv.writer`, `06_el/ui.py:983-987`** | **No — a duplicate that never migrated.** Writes the legacy 2-column `reason,row_json` schema |
| **IL** | **"Export input_errors.csv…"** | **inline `csv.writer`, `07_il/ui.py:1231-1235`** | **No** — same legacy schema |
| EL / IL standalone | "Export {EL,IL}_FULL.csv" | `_write_csv` (`06_el/screen.py:157-163`) | **No** — header is `full_rows[0].keys()` (`standalone.py:381`), so column order is dict-insertion order rather than the declared report schema |
| IL | "Export ScreenA_Report.xlsx…" | `_build_final_report_xlsx_bytes` (`07_il/ui.py:368-483`) | **Yes** — the same bytes also go into the bundle (`07_il/ui.py:1331-1334`) |

**Quoting / newline / encoding comparison for the two `input_errors.csv`
writers, which share a filename:**

| | schema | quoting | terminator | `newline=''` | encoding |
|---|---|---|---|---|---|
| EH/IH button + all four bundle writers | `stage,record_number,reason,observed_len,expected_len,raw` | `QUOTE_MINIMAL` | `\n` | yes | UTF-8 |
| EL/IL button | `reason,row_json` | `QUOTE_MINIMAL` | `\n` | yes | UTF-8 |

The module docstring of `plugins/_common/input_errors.py:36` lists
`plugins/06_el/ui.py, plugins/07_il/ui.py` as consumers of the shared writer.
They are consumers of `read_input_errors` and `merge_input_errors_csv`, but their
export buttons are not — those two call sites still emit the legacy layout the
module was written to retire.

### C.6 What was not done

No GUI was launched. No Tkinter object was instantiated (`tests/conftest.py`
replaces the `tkinter` modules with `MagicMock` before any plugin import). No
claim is made anywhere in this document about what any window displays.

---

## Candidate findings

Described precisely, without F-numbers. `03_findings.md` was not edited.

1. **`lineterminator="\n"` writers leave a lone `CR` unquoted, producing a CSV
   that `csv.reader` refuses to parse.** `plugins/_common/exporters.py:84`,
   `plugins/_common/input_errors.py:114`, `plugins/06_el/ui.py:984`,
   `plugins/07_il/ui.py:1232`. Demonstrated end-to-end through the real ingest
   path on `data/input_errors.csv`. Latent on the EH/IH reports only because
   `parser.py:237` happens to strip `CR` first. **Class (W).**

2. **`read_input_errors` turns a structurally invalid audit file into "nothing
   was dropped."** `plugins/_common/input_errors.py:156-157` catches every
   exception and returns `[]`. Combined with (1), a dropped citation is written
   to disk and then read back as absent — the exact failure mode the module
   exists to prevent. **Class (W), consequence.**

3. **The final workbook's four stage sheets are structurally empty.**
   `CONTRACT_STAGE_SHEET_COLS` (`plugins/07_il/plugin.py:56-59`) and the key set
   returned by `_extract_contract_stage_row` (`plugins/07_il/ui.py:322-349`)
   intersect in 2 names of 7 — `local_id`, `outcome`, `fail_criteria_ids`,
   `reason` and `decided_at` can never be populated. Observed: every data cell on
   the EH/IH/EL/IL sheets read back `None`, bar one. Row counts are correct, so
   the sheet looks populated until a cell is inspected.

4. **The final workbook's FINAL sheet has no metadata for any record excluded
   before IL.** `_load_master_rows` (`plugins/07_il/ui.py:298-315`) falls back to
   `data/current.csv` because the Harmoniser never writes `data/A.csv`
   (`plugins/03_harmoniser/bundle.py:98`), so the "master list" is the terminal
   survivor set. Observed: 3 of 6 records had blank title/abstract/keywords on the
   sheet that is supposed to be the whole-corpus deliverable.

5. **`input_errors.csv` inflates by one row per EH/IH hop, and loses the
   Harmoniser's ragged-row diagnostics.** EH/IH merge the carried-forward entries
   into `ParseReport.skipped` (`04_eh/ui.py:444-449`) and then re-stamp the whole
   merged list with the current stage (`bundle.py:373` →
   `input_errors.py:202-217`), dropping `observed_len`/`expected_len`. Observed:
   one malformed record → 1 row, then 2, then 3.

6. **The header-only `input_errors.csv` the writer's own docstring argues for is
   never written.** `write_input_errors_csv` (`input_errors.py:108-112`) makes
   the case explicitly; both bundle writers gate on
   `if read_input_errors(merged)` (`bundle.py:374`, `bundle.py:524`) and so never
   emit it.

7. **EH silently rewrites every `CRLF` and lone `CR` inside metadata to `LF`.**
   `plugins/_common/parser.py:237` applies the replacement to the whole file text
   *before* parsing, so it reaches inside quoted fields. Visible in the committed
   goldens: the input corpus has 4 `CR`-bearing fields, the EH golden has 0.
   Undocumented and unasserted.

8. **EL/IL silently repair ragged rows that EH/IH reject.**
   `plugins/06_el/screen.py:148-154` pads or truncates to the header width;
   `plugins/_common/parser.py:305-307` skips the row with
   `bad_column_count`. The same `data/current.csv` therefore yields different
   record sets depending on which stage opens it, and EL/IL's repair leaves no
   entry in the audit trail.

9. **EL/IL's decoder is strictly weaker than EH/IH's.**
   `plugins/06_el/screen.py:113` does one `utf-8-sig` attempt with
   `errors="replace"`; `plugins/_common/parser.py:217-223` falls back through
   `utf-8`, `cp1252`, `latin-1`. A cp1252 bundle EH reads correctly becomes
   U+FFFD replacement characters at EL. **[inference from source]**

10. **Two criterion-id separators across one bundle.** EH/IH join with `;`
    (`runner.py:198-204`); EL/IL join with `,` (`06_el/screen.py:651-654`). A
    consumer reading `{stage}_failed_ids` uniformly across the four reports will
    be wrong for two of them.

11. **`{stage}_missing_ids` means two different things at 04 and 05.** IH writes
    the union of *missing* and *unknown*; EH writes *missing* only
    (`plugins/_common/runner.py:199-203`). Same column name, same bundle,
    different definition.

12. **EL/IL's "Export input_errors.csv…" buttons still write the legacy
    `reason,row_json` layout.** `plugins/06_el/ui.py:983-987`,
    `plugins/07_il/ui.py:1231-1235`. The bundle path for the same filename writes
    the canonical six-column schema, so the GUI button and the bundle disagree.

13. **EH/IH never update `pipeline_state.stages`.**
    `plugins/_common/bundle.py:401-403` writes only `pipeline.stages`, while
    `_write_llm_stage_bundle` writes both (`bundle.py:551-556`). Observed on the
    IL bundle: `pipeline.stages` says EH and IH are `done`, `pipeline_state`
    still says `not_run`.

14. **`reports/{STAGE}_SURVIVORS.csv` and `data/current.csv` are byte-identical
    duplicates**, at every stage (`bundle.py:349,354`; `bundle.py:519,521`). Not
    a defect in itself; worth naming because it doubles the bundle's largest
    payload and because a reader who diffs them will find nothing.

15. **Three `DataTable` classes.** `plugins/_common/widgets.py:38`,
    `plugins/06_el/ui.py:82`, `plugins/07_il/ui.py:89`. The render path is
    character-identical; only the legacy constructor, two helpers and
    `RENDER_CHUNK` differ. EL/IL were left out of the shared-widget migration
    (`widgets.py:22-23` says so explicitly).

16. **EL/IL's report CSVs use `CRLF` while EH/IH's use `LF`**, so one bundle
    carries reports with two line terminators (`bundle.py:458` vs
    `exporters.py:84`). Observed in every bundle from EL onward.

17. **The emitted CSVs have no BOM and use `,`**, which under a French-Canada
    Excel locale fragments multi-line records across rows — 7 logical records
    became 11 physical rows in the delimiter-mismatch proxy. **Class (V).** Not a
    code defect; a deliverable-format decision that has a measurable failure mode
    for the target audience.

18. **The EL/IL standalone CSV export takes its header from
    `full_rows[0].keys()`** (`plugins/06_el/standalone.py:381,407,414`), so
    column order follows dict insertion rather than the declared report schema,
    and an empty result set raises `IndexError` before the export gate is
    reached — though the gate at `standalone.py:363` does block that case first.

---

## Open questions for the maintainer

**Human-observation requests** (cannot be settled without a window; no GUI was
launched for this diagnostic):

- **HO-1 — does a multi-line metadata field draw as one row in the tab?**
  Repro: launch metaScreener → Harmoniser tab → build a bundle from any corpus
  containing a record whose `title` or `abstract` has an embedded newline
  (`docs_/samples/20260122_1654_aggregate.csv` has 15 such fields) → Screen A —
  EH tab → *Load ScreenA bundle ZIP…* → *Run EH* → *EH Full report* tab → find
  the affected record. **Report:** does it occupy one `Treeview` row or more? Is
  the newline drawn as a space, a box glyph, or does the cell truncate at it? A
  headless test proved the *data* handed to the widget is one row with one value
  per column; only the rendering is unknown.
- **HO-2 — what does Excel under a French-Canada locale actually do to
  `reports/EH_FULL.csv`?** Repro: take the EH bundle from HO-1, extract
  `ScreenA_Bundle/reports/EH_FULL.csv`, double-click it in Excel with the system
  list separator set to `;`. **Report:** the number of rows Excel shows versus
  the 777 records the file contains, and whether the records with multi-line
  metadata spill across rows. The Python `csv` module gave 11 rows for a 7-record
  file under the same delimiter mismatch, but Python's parser is only a proxy for
  Excel's.
- **HO-3 — do accents survive Excel's double-click path?** Same file, same
  repro. The file is UTF-8 without a BOM. **Report:** whether `Québec`-class
  strings render correctly or as mojibake.
- **HO-4 — which of HO-1/HO-2 matches what was actually reported?** The symptom
  "one record's metadata overflowed onto adjacent rows" was reproduced in a
  spreadsheet proxy and *not* reproduced in the tab-table data path. Knowing
  which surface the user was looking at would settle the classification.

**Questions the code cannot answer:**

- **Q-A — is the `CRLF`/`CR` → `LF` normalisation at `parser.py:237` intended?**
  It is load-bearing for the committed goldens (the `4 → 0` `CR` collapse is
  baked into `eh_filtered_v3.1.0.csv`), so it cannot be changed without a golden
  re-capture. Is it a deliberate canonicalisation of metadata, or a side effect
  of a record splitter that only needed to normalise for *splitting*?
- **Q-B — was `CONTRACT_STAGE_SHEET_COLS` ever the right column list?** The name
  says "contract v2" and `_extract_contract_stage_row`'s docstring describes
  "contract v2 standardized columns" — but the two disagree completely. Is the
  header stale, the row builder stale, or were they written against two different
  specification documents? There is no `ScreenA_Report.xlsx` golden or test, so
  nothing has ever compared them.
- **Q-C — should the FINAL sheet cover the original corpus?** Fixing
  `_load_master_rows` requires the bundle to carry the pre-EH record table.
  Nothing currently writes one. Is preserving `data/A.csv` (or a snapshot at
  Harmoniser time) an acceptable bundle-size cost?
- **Q-D — is EL/IL's ragged-row repair deliberate?** It is the opposite of
  EH/IH's policy on the same file, and it produces no audit entry. If a bundle is
  ever opened directly at EL — which the code permits — a malformed record is
  silently corrected into the corpus rather than diverted.
  *(**Answered, wave 4a — do not re-decide.** No: align EL/IL to EH/IH's
  reject-and-record policy. Fixed in `58518c9` via F-72, which closed F-24 in the
  same change; `plugins/06_el/screen.py::_csv_read_strict` and its IL twin divert
  ragged rows to the skip list as `bad_column_count`. The lenient
  `::_csv_read` is retained on purpose for the criteria table and report
  re-reads. Stamped in wave 6.)*
- **Q-E — should EH/IH re-stamp carried-forward `input_errors` rows with their
  own stage?** The current behaviour makes one drop look like N drops. The
  alternative — carrying the prior rows through untouched and appending only what
  this stage dropped — is what `merge_input_errors_csv`'s docstring appears to
  describe, but not what the callers do.
- **Q-F — are the EL/IL "Export input_errors.csv…" buttons still wanted at all?**
  If they are, they should call `_export_input_errors_csv`; if they are not,
  removing them removes the last two writers of the legacy schema.

**Note for whoever adds this file to the tree — corrected after the fact:**
this document predicted it would fail `test_every_doc_listed_in_index`. It does
not. `tests/test_metadata.py:85` defines `DOCS_INTERNAL_DIRS = ("internal",)`
and both cross-reference tests skip anything under `docs/internal/`, which is
F-29's fix and it is already in the tree. The suite is green with all five
diagnostic documents present: **390 passed, 4 skipped**. No index action is
needed for this file or any future one under `docs/internal/`.
