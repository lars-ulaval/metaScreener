# 00 — Overview: Identity, Purpose, and Map of the Territory

*Diagnostic report, Phase 1–2. Generated 2026-08-08 against `main` @ `365325c`.*
*Read-only analysis. No source file was modified in producing this report.*

---

## Phase 1 — Identity and purpose

### 1.1 What this software does

**One sentence.**
metaScreener is a Tkinter desktop application that runs a seven-stage, ZIP-bundle-passing
pipeline which takes a CSV of academic citations plus a free-text list of eligibility
criteria and mechanically narrows the citation list down to the subset a human still has
to read, keeping a per-record, per-criterion evidence trail for every decision.

**One paragraph.**
A systematic literature review begins by pulling thousands of candidate papers out of
bibliographic databases and ends with a few dozen that actually get read in full. The
narrowing step ("screening") is the expensive, tedious, error-prone part, and it must be
auditable because the review's conclusions depend on it. metaScreener automates that
narrowing in seven ordered stages, each implemented as a plugin occupying one tab of a
notebook widget. Stages 01–02 ingest and enrich a citation corpus; stage 03 turns
prose criteria ("we exclude non-English papers", "we include VR training studies") into a
machine-executable CSV table; stages 04–05 apply the deterministic subset of those
criteria (language, year, document type) as plain string/regex/numeric tests, which cost
nothing and are perfectly reproducible; stages 06–07 hand the remaining semantic criteria
to an LLM over an OpenAI-compatible endpoint, one criterion at a time, in batches of
records. Between every stage, the entire accumulated state travels as a single ZIP file
containing a JSON manifest, the current citation table, the criteria table, per-stage
report CSVs, and the LLM response caches, with SHA-256 digests recorded in the manifest.
The design's central commitment is that the machine never silently discards a record: an
LLM decision is only acted on if the model reports confidence above a threshold *and*
supplies a quotation that is literally a substring of the record it was shown. Anything
that fails those checks is labelled `PASS_FLAGGED` and survives to the next stage for a
human to look at.

**One page.**

The unit of work is a *record*: one row of a citation CSV, identified by `local_id`, with
at least `title`, `abstract`, and `keywords` columns. The unit of policy is a *criterion*:
one row of `criteria_harmonized.csv`, with an `id` (`IC-1`, `EC-3`), a `type`
(`include`/`exclude`), a `stage` (`EH`/`IH`/`EL`/`IL`), an `operator`
(`equals`/`contains`/`regex`/`in_list`/`not_in`/`gte`/`lte`/`between`/`llm`), one or more
`target` columns to read, a `what` payload to compare against, and a confidence
`threshold` used only by the LLM stages.

Plugin 03 (the Harmoniser) is what produces that criteria table. It takes prose — one
criterion per line, tagged `IC-n` or `EC-n` — and pattern-matches it into six recognised
shapes (language, year, document type, venue, DOI, keyword-in-text). Anything it can
express as a deterministic test is assigned to the heuristic stages EH or IH; everything
else is assigned to the LLM stages EL or IL with `operator=llm`. An optional LLM
refinement pass may re-assign rows, but is fenced by structural guardrails (row count and
identifier set must be invariant). The Harmoniser also emits the first bundle ZIP.

Stages 04 (EH) and 05 (IH) are the deterministic filters and share a single implementation
in `plugins/_common/runner.py`. For each record they evaluate every criterion assigned to
their stage and get back one of four statuses — `MET`, `FAILED`, `MISSING` (the column
does not exist, or is empty for this record), `UNKNOWN` (the operator is `llm`, or is
unrecognised). Polarity is applied at the end: for an `include` criterion a match means
`MET`, for an `exclude` criterion a match means `FAILED`
(`plugins/_common/evaluator.py:165-168`). Any `FAILED` makes the record `OUT` — it does
not continue. Otherwise the record is `PASS_CLEAN` (everything decided and satisfied) or
`PASS_FLAGGED` (something was missing or undecidable). Both `PASS_*` outcomes survive.
The two stages differ in exactly two places, both inlined in `runner.py:146-172`: EH
requires *all* criteria to be `MET` for `PASS_CLEAN`, IH only requires the absence of
`MISSING`/`UNKNOWN`; and IH merges `unknown` into the `ih_missing_ids` report column while
EH keeps them separate.

Stages 06 (EL) and 07 (IL) are the LLM filters. For each criterion in turn, the surviving
records are packed into batches (default 50) and sent as a single JSON object — criterion
spec plus a list of `{a_id, title, abstract, keywords}` items, each field truncated to
1500 characters — with a system prompt demanding a JSON array back, one object per item,
each carrying `decision` (`meet`/`not_meet`/`uncertain`), `confidence` (0–1), `field`,
`quote`, and `span`. The response is parsed defensively (fenced blocks stripped, first
`[...]` block extracted as a fallback). Then comes the gate
(`plugins/06_el/screen.py:547`): the decision counts only if the quote validates as a
substring of the exact truncated field text that was sent, *and* confidence meets the
criterion's threshold (default 0.6), *and* the decision is not `uncertain`. Failing any of
those, the record is marked uncertain for that criterion and ends up `PASS_FLAGGED` (EL)
or `REVIEW` (IL). Every accepted or rejected response is written to a JSONL cache keyed by
a SHA-256 of prompt version, model, criterion id, record id, a hash of the record's
truncated target text, and the truncation length, so re-running the same corpus with the
same settings costs nothing and returns the same answers.

The output of the last stage is a bundle whose `reports/IL_FULL.csv` carries every record
with its per-criterion evidence JSON, and whose `reports/IL_SURVIVORS.csv` is the set that
a human must now read. A cross-stage `reports/ScreenA_Report.xlsx` aggregates all four
screening stages into one workbook.

Two supporting toolchains sit outside the GUI. `tools/eval_grid_generator.py` produces
blind adjudication workbooks so human raters can independently judge a sample of records
without seeing the LLM's answer, and `tools/eval_ingest.py` joins the filled grids back
against the LLM decisions and computes Cohen's and Fleiss' kappa in pure Python. The
committed outputs of that study live in `docs/data/`.

### 1.2 Domain glossary

| Term | Meaning | Where implemented |
|---|---|---|
| **PRISMA** | *Preferred Reporting Items for Systematic Reviews and Meta-Analyses* — the reporting standard that governs how a systematic review documents its search-and-screening funnel. metaScreener does not implement PRISMA; it produces the audit trail a PRISMA flow diagram needs. Survives only as the legacy repo/folder name. | No code. Named in `README.md:51-55`, `plugins/01_reference_extractor/plugin.py:22-30`. |
| **Systematic review** | A literature review with a pre-registered, reproducible search-and-selection protocol, as opposed to a narrative review. The reason auditability matters here. | Domain context only. |
| **Screening** | Deciding, per candidate record, whether it is eligible, usually first from title/abstract and later from full text. metaScreener automates title/abstract screening. | Stages 04–07. |
| **EH** — Exclusion by Heuristic | Stage 04. Deterministic evaluation of exclusion criteria; a match removes the record. Strict `PASS_CLEAN` policy. | `plugins/04_eh/`, engine in `plugins/_common/runner.py` with `stage="EH"`. |
| **IH** — Inclusion by Heuristic | Stage 05. Deterministic evaluation of inclusion criteria; failing one removes the record. Lenient `PASS_CLEAN` policy. | `plugins/05_ih/`, same shared engine with `stage="IH"`. |
| **EL** — Exclusion by LLM | Stage 06. LLM adjudication of exclusion criteria that could not be reduced to a deterministic test. | `plugins/06_el/screen.py:335` `run_el_screen`. |
| **IL** — Inclusion by LLM | Stage 07. LLM adjudication of inclusion criteria. Terminal stage; also emits the cross-stage final report. | `plugins/07_il/screen.py:337` `run_il_screen`. |
| **Bundle** | A ZIP archive carrying the complete pipeline state between stages: `manifest.json`, `data/current.csv`, `criteria/criteria_harmonized.csv`, `reports/*`, `cache/*`. Plugins have no other channel of communication — no database, no shared memory. | Written by `plugins/03_harmoniser/bundle.py` (first bundle) and `plugins/_common/bundle.py:136` `_export_next_bundle_zip` (EH/IH); EL/IL write their own in `standalone.py`/`ui.py`. Read by `plugins/_common/bundle.py:114` and the stage-local `_load_bundle` in `06_el/screen.py:170` / `07_il/screen.py:172`. |
| **Criteria harmonisation** | Turning prose eligibility criteria into the structured `criteria_harmonized.csv` table, including deciding which stage each criterion belongs to. | `plugins/03_harmoniser/parser.py` (text → rows), `inference.py` (operator/target/stage inference), `llm_refine.py` (optional LLM re-assignment under guardrails). |
| **Evidence gating** | The rule that an LLM decision is only acted on when it is backed by a confidence score at or above the criterion's threshold *and* a verbatim quotation that validates as a substring of the text the model was shown. | Gate: `plugins/06_el/screen.py:547` and `plugins/07_il/screen.py:549`. Quote check: `plugins/_common/llm_client.py:58` `_quote_in_text`, applied at `llm_client.py:277`. Tests: `tests/test_evidence_gating.py`. |
| **`PASS_FLAGGED`** | Outcome for a record that was not excluded but whose evaluation was incomplete — a missing column, an empty field, an `llm` operator in a heuristic stage, or an LLM answer that failed the gate. It survives to the next stage and lands in the human review queue. IL uses the label `REVIEW` for the same concept. | `plugins/_common/runner.py:153,159`; `plugins/06_el/screen.py:591`; `plugins/07_il/screen.py:593` (as `REVIEW`). Outcome vocabulary: `OUTCOMES` in `06_el/screen.py:66` and `07_il/screen.py:68`. |
| **Golden file** | A committed, byte-exact expected output. The regression tests re-run a stage over a committed input and assert the produced CSV bytes equal the committed golden bytes, so any behaviour drift shows up as a diff. | `tests/golden/*.csv`, `tests/golden/*.json`; regenerated by `tools/capture_el_il_goldens.py`; protected from CRLF rewriting by the `binary` rule in `.gitattributes:4`. |
| **Adjudication grid** | An Excel workbook handed to a human rater containing a sample of records and, per record, a dropdown per criterion (YES / NO / uncertain). Deliberately stripped of the LLM's columns so the rater is blind. | `tools/eval_grid_generator.py`; blindness enforced by `test_decisions_sheets_do_not_expose_llm_columns` in `tests/test_eval_grid_generator.py`. Filled examples: `docs/data/grids/filled/*.xlsx`. |
| **Cohen's kappa** | Chance-corrected agreement between exactly two raters. Used for human-vs-LLM per-criterion agreement. | `tools/eval_ingest.py` (pure Python, no scipy). Validated in `tests/test_eval_ingest.py`. |
| **Fleiss' kappa** | Chance-corrected agreement among three or more raters. Used for the three-co-author overlap sample. | `tools/eval_ingest.py`, same test file. |
| **Polarity** | Whether a criterion is `include` or `exclude`. Determines how a `meet`/`not_meet` verdict maps to `MET`/`FAILED`. Also the axis along which the four screening stages are twinned (E vs I). | `plugins/_common/evaluator.py:165-168`; `plugins/06_el/screen.py:551-569`. |
| **`a_id` / `local_id`** | The record identifier. `local_id` is the CSV column; `a_id` is the same value inside LLM request/response JSON. | `plugins/_common/llm_client.py:380-386`. |
| **Bundle root** | Bundles may be zipped with or without a top-level folder; the readers sniff for `manifest.json` at the root or one level down and carry the prefix around. | `plugins/_common/bundle.py:76`, `plugins/06_el/screen.py:117`. |

### 1.3 Project identity audit

The project has carried at least **five** distinct names. Current state of each in the
tracked tree:

| Name | Where it still lives | Occurrences | Status |
|---|---|---|---|
| `prisma-hub_v3_repo` | Working-directory folder name only — not referenced by any tracked file. | 0 in repo | Cosmetic; local only. |
| `prisma_hub` / `PrismaHubApp` / `PRISMA Hub` | `CHANGELOG.md:42,43,44,72,76` only, as historical record of the 3.1.0 rename. | 5 lines, 1 file | **Correct.** A changelog *should* name what it renamed. No stale code references survive. |
| `PRISMA` (as product branding) | `README.md:51-55,194`, `docs_/README.md`, `plugins/01_reference_extractor/plugin.py:22-30` — all now *negative* references warning that PRISMA flow diagrams are **not** valid Plugin 01 input. | — | Intentional; leave alone. |
| **`SCREENA` / `Screen A` / `ScreenA`** | Live in code: env-var prefix `SCREENA_EL_*` / `SCREENA_IL_*`; tab titles `"Screen A — EL"`, `"Screen A — IH"`; plugin ids `screen_a_el`; bundle names `ScreenA_Bundle_*.zip`; bundle root prefix `ScreenA_Bundle/`; final report `ScreenA_Report.xlsx`; manifest `created_by: screen_a_eh_plugin`. | 12 code lines for `SCREENA_`; ~40 for `Screen A`/`ScreenA` | **Surviving legacy identity, user-visible.** See finding N-01. |
| `metascreener` / `metaScreener` / `metascreener-lars-ulaval` | Package, product, PyPI distribution. | — | Current. |

`SCREENA` is the one that matters. It is not confined to comments: it is the environment
variable prefix a user must set to configure the LLM stages, the label on four of the seven
GUI tabs, and the filename of the final deliverable workbook. A reviewer reading the README
sees `metaScreener`, launches the app, and finds four tabs called "Screen A". Exhaustive
list:

| File:line | Occurrence |
|---|---|
| `plugins/06_el/plugin.py:33` | `TAB_TITLE = "Screen A — EL"` |
| `plugins/06_el/plugin.py:34` | `PLUGIN_ID = "screen_a_el"` |
| `plugins/06_el/plugin.py:37-40` | `SCREENA_EL_MODEL`, `SCREENA_EL_TRUNC_CHARS`, `SCREENA_EL_BATCH_SIZE`, `SCREENA_EL_USE_CACHE` |
| `plugins/07_il/plugin.py:40,41` | `TAB_TITLE = "Screen A — IL"`, `PLUGIN_ID = "screen_a_il"` |
| `plugins/07_il/plugin.py:44-47` | `SCREENA_IL_MODEL`, `SCREENA_IL_TRUNC_CHARS`, `SCREENA_IL_BATCH_SIZE`, `SCREENA_IL_USE_CACHE` |
| `plugins/07_il/plugin.py:53` | `FINAL_REPORT_NAME = "ScreenA_Report.xlsx"` |
| `plugins/04_eh/ui.py` | `TAB_TITLE = "Screen A — EH"`; export default `ScreenA_Bundle_EH_{stamp}.zip` |
| `plugins/05_ih/ui.py` | `TAB_TITLE = "Screen A — IH"`; export default `ScreenA_Bundle_IH_{stamp}.zip` |
| `plugins/_common/bundle.py:67,84` | bundle-root prefixes `"ScreenA_Bundle/"`, `"screenA_bundle/"`, `"ScreenA/"` |
| `plugins/_common/bundle.py:201` | `m["created_by"] = f"screen_a_{sl}_plugin"` |
| `README.md:300-303` | Documents `SCREENA_EL_*` — and **only** the EL half; the four `SCREENA_IL_*` variables are undocumented. |

### 1.4 Publication status

| Source | Version | Date | Notes |
|---|---|---|---|
| `pyproject.toml:7` | `3.1.0` | — | |
| `CITATION.cff:24-25` | `3.1.0` | `2026-04-29` | |
| `CHANGELOG.md:10` | `[3.1.0]` | `2026-04-29` | Previous release `3.0.1` (2026-04-04). |
| `metascreener/__init__.py` | *(no `__version__`)* | — | The package exposes no version attribute. |
| `.zenodo.json` | *(no version field)* | — | |
| `dist/` (untracked) | `3.0.1` **and** `3.1.0` wheels + sdists | — | Stale build output for two versions side by side. |
| PyPI | claimed via badge `README.md:11` | — | Not verified — no network calls were made per the brief's ground rule 5. |

Versions are **consistent** across the three sources that state one. Other metadata facts:

- **Licence.** MIT. `LICENSE` (15 lines, and note: **carries a UTF-8 BOM**), declared in
  `pyproject.toml:8`, `CITATION.cff:26`, `.zenodo.json`.
  `LICENSE` line 3 reads `Copyright (c) 2026` with **no copyright holder named** — the
  SPDX headers in the source files say `Alejandro Reyes-Consuelo`, so the licence file is
  strictly less informative than the headers. Also, the standard MIT warranty clause has
  been truncated: the file ends at `THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF
  ANY KIND.` and omits the remainder ("...EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED
  TO... IN NO EVENT SHALL THE AUTHORS... BE LIABLE..."). It is therefore **not** the
  verbatim MIT text, despite being labelled MIT everywhere.
- **DOI.** `10.5281/zenodo.19360124`, in the `README.md:7` badge and the BibTeX block at
  `README.md:384`. Commit `365325c` switched this from `...125` to `...124` ("concept DOI
  for stability"). The DOI appears **nowhere else** — `CITATION.cff` has no `doi:` field
  and `.zenodo.json` has no `doi` key, so citation managers consuming the CFF will not see
  it.
- **CITATION.cff** is well-formed CFF 1.2.0 with ORCIDs for all three authors and a
  `preferred-citation` block pointing at *Journal of Open Research Software*,
  `notes: "Under revision."`
- **.zenodo.json** is pre-filled and consistent with CITATION.cff, except that it spells
  the affiliation `Universite Laval` (ASCII) where CITATION.cff uses `Université Laval`.
- **Peer review.** The CHANGELOG describes 3.1.0 as the "peer-review revision release" and
  enumerates reviewer-driven changes (Reviewer 2 optional items O4/O5/O6 explicitly
  deferred, Figures 1–3 rebuilt, manuscript sections revised). README's BibTeX says
  `note = {Submitted}` while CITATION.cff says `Under revision.` — **minor drift between
  two publication-status statements.**

---

## Phase 2 — Map of the territory

### 2.1 Annotated directory tree

```
prisma-hub_v3_repo/
├── run.py                      Entry point. Imports plugin_manager for its import-time
│                               side effect, then constructs MetaScreenerApp. 14 lines.
├── metascreener/               The application shell — everything that is not a plugin.
│   ├── __init__.py             Empty but for SPDX header. No __version__.
│   ├── main.py                 MetaScreenerApp(tk.Tk): .env prefill, mandatory API-key
│   │                           prompt, ttk.Notebook, plugin discovery + tab mounting.
│   ├── plugin_api.py           The plugin contract: PluginMeta dataclass, BasePlugin ABC.
│   ├── plugin_manager.py       Custom MetaPathFinder that intercepts all `plugins.*`
│   │                           imports and exec()s sanitised source. See 01_architecture.
│   └── api_key_dialog.py       Modal OpenAI-key prompt shown on every launch.
├── plugins/                    Seven pipeline stages + shared library. Imported only
│   │                           through the meta-path finder above.
│   ├── __init__.py             Package marker (6 lines).
│   ├── _common/                Code factored out of the twinned stages.
│   │   ├── parser.py           CSV record splitter, tolerant corpus parser, criteria
│   │   │                       loader, normalisation maps, hashing, encoding fallback.
│   │   ├── evaluator.py        Per-(row, criterion) deterministic evaluation for EH/IH.
│   │   ├── runner.py           The EH/IH screening loop. Stage-parameterised.
│   │   ├── bundle.py           Bundle ZIP read + next-bundle write for EH/IH.
│   │   ├── exporters.py        CSV byte-writer (byte-identity-locked) and XLSX writer.
│   │   ├── llm_client.py       Stage-agnostic LLM machinery for EL/IL: batching, adaptive
│   │   │                       split on 429/oversize, JSON extraction, quote validation,
│   │   │                       cache key derivation, JSONL cache serialisation.
│   │   └── widgets.py          Shared Tk widgets (110 lines).
│   ├── 01_reference_extractor/ Stage 01, experimental. Extracts reference markers from
│   │   │                       PDF/PNG images via GPT-4o vision.
│   │   ├── plugin.py           Thin embedder + experimental-scope banner.
│   │   └── original/
│   │       └── prisma_citations_ai_v3_1.py   1,009-line standalone tool, LIVE (imported
│   │                                          by plugin.py:35). See §4.7.
│   ├── 02_references_of_x/     Stage 02. Resolves/enriches references against OpenAlex,
│   │                           Crossref, Semantic Scholar. core/pipeline/services/ui split.
│   ├── 03_harmoniser/          Stage 03. Prose criteria → criteria_harmonized.csv + first
│   │                           bundle. parser/inference/llm_refine/exporters/bundle/ui.
│   ├── 04_eh/                  Stage 04 EH. plugin.py is a re-export shim; ui.py holds the
│   │                           View plus six stage-curried one-line wrappers.
│   ├── 05_ih/                  Stage 05 IH. Structural twin of 04_eh (98.9% identical).
│   ├── 06_el/                  Stage 06 EL. prompt/screen/ui/standalone + shim plugin.py.
│   └── 07_il/                  Stage 07 IL. Twin of 06_el plus the terminal-stage final
│                               report aggregation (~330 extra lines in ui.py).
├── tests/                      13 files, offline, no API key or display needed.
│   ├── conftest.py             Fixtures + the plugins.* import shim used by tests.
│   ├── data/                   Two small CSV fixtures for the EL/IL evaluators.
│   └── golden/                 Byte-identity expected outputs, marked `binary` in
│                               .gitattributes so CRLF conversion cannot corrupt them.
├── tools/                      Offline CLI utilities, not part of the GUI.
│   ├── audit_imports.py        AST audit: every name resolves to import/def/param/builtin.
│   ├── audit_decorators.py     AST audit of decorator usage.
│   ├── capture_el_il_goldens.py Regenerates the EL/IL goldens from fixtures.
│   ├── eval_grid_generator.py  Builds blind human adjudication workbooks.
│   ├── eval_grid_filler_synthetic.py  Fills grids synthetically for testing the ingest.
│   └── eval_ingest.py          Joins filled grids to LLM decisions; Cohen's/Fleiss' kappa.
├── docs/                       PUBLISHED documentation + reproducibility evidence.
│   ├── index.md, installation.md, usage.md, faq.md, llm-evaluation.md
│   ├── images/usage/           Three annotated screenshots (plugins 03, 05, 06).
│   └── data/                   The human-validation study's committed evidence: partition
│                               manifest, three filled grids, joined decisions, summary.
├── docs_/                      SAMPLE INPUTS only. See §2.4.
├── secrets/                    Gitignored except its README. Explanatory placeholder.
├── .github/workflows/test.yml  16-cell CI matrix: 4 OS × 4 Python versions.
├── metaScreener.spec           PyInstaller one-file spec (windowed).
├── metaScreener-console.spec   Same, console subsystem. Byte-identical but for the name
│                               and `console=True`.
├── hook-plugins.py             PyInstaller hook: collect_submodules("plugins"). 4 lines.
├── Dockerfile / docker_test.sh Headless Linux test evidence for the JORS editor.
├── pyproject.toml              setuptools packaging, entry points, pytest config.
├── requirements.txt            Nine dependencies, all but `openai` unpinned.
├── CHANGELOG.md, CITATION.cff, .zenodo.json, LICENSE, README.md
└── .env.example                One line: `OPENAI_API_KEY=`
```

### 2.2 Every tracked file over 200 lines

Source and tooling first, then data/fixtures.

| Path | Lines | Purpose |
|---|---:|---|
| `plugins/02_references_of_x/services.py` | 1513 | Federated bibliographic lookup: OpenAlex/Crossref/Semantic Scholar clients, fuzzy title matching, throttling, record merge. |
| `plugins/07_il/ui.py` | 1314 | ILView tab + DataTable + the terminal-stage cross-bundle final-report aggregation (7 helpers absent from EL). |
| `plugins/02_references_of_x/ui.py` | 1076 | ReferencesOfXView: input panes, resolve/fetch modals, worker threads, result grid. |
| `plugins/06_el/ui.py` | 1066 | ELView tab + DataTable + XLSX export. Twin of `07_il/ui.py` minus the final report. |
| `plugins/01_reference_extractor/original/prisma_citations_ai_v3_1.py` | 1009 | Self-contained GPT-4o-vision reference-marker extractor with its own Tk view. Live. |
| `tools/eval_ingest.py` | 939 | Grid ingestion, polarity-aware status mapping, Cohen's + Fleiss' kappa, confusion matrices, four output artefacts. |
| `tools/eval_grid_generator.py` | 885 | Rater-workbook generator: partitioning, dropdown validation, LLM-column stripping. |
| `plugins/05_ih/ui.py` | 877 | IHView. 98.9% identical to `04_eh/ui.py` after stage-word normalisation. |
| `plugins/04_eh/ui.py` | 877 | EHView. |
| `plugins/03_harmoniser/ui.py` | 799 | HarmoniserView: criteria text pane, inferred-table grid, LLM-refine controls, bundle export. |
| `plugins/07_il/screen.py` | 633 | IL engine. 97.0% identical to EL's. |
| `plugins/06_el/screen.py` | 631 | EL engine: bundle load, criteria parse, cache lookup, LLM dispatch, evidence gate, outcome assignment. |
| `tests/test_eval_ingest.py` | 554 | Kappa validation against textbook values + edge cases. |
| `plugins/07_il/standalone.py` | 542 | StandaloneILPlugin dev/QA shell. |
| `plugins/06_el/standalone.py` | 541 | StandaloneELPlugin. 93.5% identical to IL's. |
| `plugins/03_harmoniser/parser.py` | 528 | Free-text criteria parsing, target canonicalisation, corpus header stats. |
| `tests/test_imports.py` | 467 | Import audit, plugin-shim regression, cache-key invariants. |
| `plugins/_common/parser.py` | 452 | Shared parsing/normalisation for EH/IH. |
| `plugins/_common/llm_client.py` | 436 | Shared LLM machinery for EL/IL. |
| `tools/capture_el_il_goldens.py` | 421 | Golden regeneration harness. |
| `README.md` | 415 | Project front page. |
| `tests/test_eval_grid_generator.py` | 403 | Grid-generator behaviour incl. rater-blindness guard. |
| `docs/usage.md` | 360 | Seven-plugin walkthrough. |
| `docs/installation.md` | 359 | Per-platform install, config, troubleshooting. |
| `plugins/02_references_of_x/pipeline.py` | 352 | Stage-02 orchestration over `services.py`. |
| `plugins/_common/evaluator.py` | 351 | `_eval_criterion` + detailed variant + reason summariser. |
| `docs/llm-evaluation.md` | 339 | Validation-study methodology and results. |
| `plugins/03_harmoniser/inference.py` | 318 | Six-category pattern inference → operator/target/stage. |
| `tools/eval_grid_filler_synthetic.py` | 264 | Synthetic grid filler for testing the ingest path. |
| `docs/faq.md` | 263 | FAQ. |
| `plugins/02_references_of_x/core.py` | 247 | Stage-02 data structures/normalisation. |
| `plugins/_common/bundle.py` | 240 | Bundle IO for EH/IH. |
| `plugins/03_harmoniser/exporters.py` | 231 | criteria_harmonized.csv writer + XLSX. |
| `metascreener/plugin_manager.py` | 225 | The meta-path finder. |
| `tests/test_bundle_integrity.py` | 216 | Bundle structure/manifest/hash tests. |
| `metascreener/main.py` | 213 | App shell. |
| `tests/test_el_regression.py` | 209 | EL golden regression. |
| `tests/test_deterministic_filters.py` | 205 | `_eval_criterion` across all operators. |

Tracked **data/fixture** files over 200 lines (not source):

| Path | Lines | Nature |
|---|---:|---|
| `tests/golden/eh_filtered_v3.1.0.csv` | 2096 | Golden — EH stage output. |
| `tests/golden/ih_filtered_v3.1.0.csv` | 2096 | Golden — IH stage output. |
| `docs_/samples/20260122_1654_aggregate.csv` | 2096 | Sample corpus (776 records; the extra lines are quoted embedded newlines). |
| `tests/golden/el_cache_v3.1.0.json` | 2048 | Golden — EL LLM response cache. |
| `tests/golden/il_cache_v3.1.0.json` | 1016 | Golden — IL LLM response cache. |
| `docs/data/eval_results_v1.csv` | 345 | Human+LLM joined decisions. |
| `docs/data/eval_decisions_v1.csv` | 345 | Long-format human decisions. |
| `docs/data/grids/partition_manifest.csv` | 230 | Rater assignment manifest. |
| `docs/data/grids/filled/*.xlsx` | 226–241 | Three filled adjudication grids (binary; line counts are byte-artefacts). |
| `docs/images/usage/*.png` | 86–323 | Screenshots (binary). |

**Totals.** 121 tracked files. Tracked Python is **22,175 lines**
(`git ls-files '*.py' | xargs wc -l`), split as: `plugins/` 15,548 · `tests/` 3,192 ·
`tools/` 2,818 · `metascreener/` + `run.py` 613 · `hook-plugins.py` 4.

### 2.3 Tracked source vs. tracked data vs. local artefacts

| Category | What | Verdict |
|---|---|---|
| **Tracked source** | `run.py`, `metascreener/**`, `plugins/**/*.py`, `tools/*.py`, `tests/*.py`, spec files, `hook-plugins.py`, `Dockerfile`, `docker_test.sh`, CI workflow. | Correct. |
| **Tracked data/fixtures** | `tests/golden/**` (9 files), `tests/data/*.csv` (2), `docs/data/**` (9), `docs/images/**` (3), `docs_/samples/**` (3). | Correct and deliberate — the `docs/data/` set is the paper's reproducibility evidence, and the goldens are the regression contract. |
| **Local artefacts, correctly gitignored** | `dist/` (4 files), `metascreener_lars_ulaval.egg-info/` (6 files), `.pytest_cache/`, 10 × `__pycache__/`, `.env`. | All matched by `.gitignore`. `git status` is clean. |

Nothing is tracked that should not be. Three things are *present in the working tree* that
warrant a note:

1. **`dist/` holds two versions simultaneously** — `metascreener_lars_ulaval-3.0.1{.tar.gz,-py3-none-any.whl}`
   and the same pair for `3.1.0`. Harmless (ignored), but a `twine upload dist/*` would
   attempt to re-upload 3.0.1. Worth clearing before any release.
2. **`.env` exists in the working tree** (181 bytes, ignored). Confirmed ignored by
   `.gitignore` line 40 and absent from `git ls-files`. It has never been committed —
   verified against the full history (`git log --all -- .env` returns nothing).
3. **10 `__pycache__` trees and an `.egg-info`** are stale build residue. Note that
   `__pycache__` under `plugins/` is *particularly* misleading: because of the custom
   loader (see 01_architecture §3.2), Python never writes or reads bytecode for
   `plugins.*` modules, so anything in `plugins/**/__pycache__` was produced by some
   *other* import path (e.g. `pytest` collecting them directly) and is not what the app
   executes.

### 2.4 `docs/` vs `docs_/` — what the split actually is

They are not two documentation directories. The trailing underscore is doing real work,
and it is a genuine trap.

| | `docs/` | `docs_/` |
|---|---|---|
| Purpose | The project's **published documentation and evidence archive** — index, installation, usage, FAQ, validation methodology, screenshots, and the committed human-validation data. | A **sample-input directory**. Three example files a user feeds *into* the pipeline. |
| Tracked files | 17 | 4 (`README.md` + 3 samples) |
| `.gitignore` treatment | Not mentioned; fully tracked. | **Explicitly blanket-ignored** at `.gitignore:57-60`: `docs_/**` with re-inclusions for `!docs_/README.md`, `!docs_/samples/`, `!docs_/samples/**`. |
| Referenced from | `README.md:31-36`, `docs/index.md` | `README.md:192-193,211-217,349-350`, `pyproject.toml:75` (`package-data`), `docs/index.md`, `docs/usage.md` |
| Age | Created 2026-04 during the documentation push. | Present since the initial commit (2026-02-08). |

So the split **is intentional but badly named.** `docs_/` predates `docs/`; it was the
original catch-all "stuff that isn't code" folder, was later reduced to samples-only by the
blanket ignore rule, and then `docs/` was created alongside it for the real documentation.
The working tree currently contains exactly the four tracked files in `docs_/` — nothing
else is hiding there — but the blanket ignore means a contributor can drop files into
`docs_/` and see them silently not appear in `git status`, which is a foot-gun.

The obvious rename (`docs_/samples/` → `samples/` or `docs/samples/`) would touch
`pyproject.toml:75`, `README.md` (4 places), `docs/index.md`, `docs/usage.md`, and
`.gitignore`. It is low-risk but not zero-risk, and it changes paths that the published
manuscript may quote. Flagged as a Medium finding, not recommended before acceptance.

---

*Continues in [`01_architecture.md`](01_architecture.md).*
