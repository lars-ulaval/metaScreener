# metaScreener — Diagnostic Report: index and executive summary

> **How to read this file.** Everything above *"What the 2026-08-08 diagnostic found"* is
> **live** and is maintained by each wave. Everything below it is the **original executive
> summary as written on 2026-08-08**, preserved so the set remains readable as a record of
> what the first diagnostic found — annotated, not rewritten, wherever it has since been
> overtaken. Its three headline items are all closed. Do not act on the lower half without
> reading the annotation attached to the passage.

---

## The document set

| Document | Contents |
|---|---|
| [`00_overview.md`](00_overview.md) | Phase 1–2 — what the software is, domain glossary, project-identity audit, publication metadata, annotated tree, file inventory, and the `docs/` vs sample-folder analysis. |
| [`01_architecture.md`](01_architecture.md) | Phase 3–4 — startup trace, the custom plugin loader dissected, plugin contract compliance, stage-by-stage data flow, bundle format, two Mermaid diagrams, and the full duplication measurement + de-duplication design. |
| [`02_quality.md`](02_quality.md) | Phase 5–7 — test inventory and run results, coverage, the golden mechanism, CI assessment, error handling, evidence gating, LLM interaction, cache, determinism, kappa verification, input validation, portability, docs/packaging/hygiene. §6.3–6.5 carry wave-6 addenda. |
| [`03_findings.md`](03_findings.md) | **The register — the live document of the set.** Every finding, its status, the sweep and closure notes, top-10 actions, what is genuinely good, open questions. |
| [`04_frozen_build.md`](04_frozen_build.md) | Wave 3, Part B — the PyInstaller distributable actually built and launched, against a prediction that had stood unverified since the 3.1.0 restructure. |
| [`05_report_production.md`](05_report_production.md) | What stages 04–07 write, whether the CSVs survive hostile metadata, and what fills the on-screen table. Source of F-67..F-82. Carries a wave-6 addendum listing its twelve stale passages. |
| [`06_llm_integration.md`](06_llm_integration.md) | How the LLM is employed, and what a local-by-default or model-discovery destination would cost. Source of F-86..F-130 via its `C-n` namespace; §B9 carries the candidate table and ten open maintainer decisions. |

## Current state

**Repository:** `main`, 149 tracked files, 27,571 lines of Python. The set was begun on
2026-08-08 against `365325c`; documents 04, 05 and 06 were added by later waves, and six
fix waves (0–5) have landed since.

**The register is the single authority for counts and status.** As of wave 6b it holds
**129 rows**, F-01..F-132 with a permanent gap at F-56–F-58. **45 are closed and 84 are
open**, and every closed row now names the commit that closed it — a row's status is the
marker in its **Effort** cell (`(done)`, `(scheduled)`, `(backlog)`, `(parked)`, or nothing
for open-and-unscheduled).

| | Total | Closed | **Open** |
|---|---:|---:|---:|
| **Critical** | 4 | 3 | **1** |
| **High** | 36 | 16 | **20** |
| **Medium** | 57 | 14 | **43** |
| **Low** | 32 | 12 | **20** |
| **Total** | 129 | 45 | **84** |

Of the 84 open, 1 is scheduled (F-79, wave 4b), 5 are backlog and 2 are parked; the rest are
unscheduled. These totals are a derived snapshot and nothing checks them against the table —
that is **F-131**. Count **rows**, never the maximum ID. See
[`03_findings.md` § "How this register is counted, and which rows are closed"](03_findings.md).

**The highest-severity open finding is F-86** (from `06_llm_integration.md` C-1):
`plugins/_common/llm_client.py::run_m1_llm_for_criterion` builds its acceptance map from
the whole item list before batching, so a response naming another batch's record is
accepted and its quote validated against *that* record's real text. The evidence gate
passes, the verdict is written back to cache, and a later run replays the fabricated
exclusion with zero API calls. Reproduced at `OUT = 3/6`; fires at `batch_size = 1`. It is
the only finding in the set that can remove a record from a review on evidence belonging to
a different record.

**Test baseline:** 422 passed, 4 skipped. *(This figure is quoted here because it is the
gate every wave checks against. It is deliberately absent from the published documentation
— pinning a count in prose is F-17, and F-124 records that the pin re-drifted after F-17
was fixed.)*

---

## What this software is

metaScreener is a Tkinter desktop application that narrows a corpus of academic citations
down to the subset a human must read for a systematic literature review. Seven plugins, one
per notebook tab, run in order: ingest and enrich a corpus (01–02), turn prose eligibility
criteria into a machine-executable table (03), apply the deterministic criteria as
string/regex/numeric tests (04–05, EH and IH), then hand the semantic criteria to an LLM
(06–07, EL and IL). Between every stage the whole state travels as a ZIP "bundle" —
manifest, current record table, criteria table, per-stage reports, LLM caches. Its central
design commitment is that no record is silently discarded: an LLM decision is acted on only
if the model reports confidence above a threshold **and** supplies a quotation that is
literally a substring of the text it was shown; anything else is labelled `PASS_FLAGGED`
and survives for a human.

---
---

# What the 2026-08-08 diagnostic found

*Everything from here to the end of the file is the executive summary as written on
2026-08-08 against `main` @ `365325c` (121 tracked files, 22,175 lines of Python), when the
set contained four documents and the register held 55 findings. It is kept as the record of
that analysis. Its present-tense claims are claims about `365325c`, and where one has been
overtaken a bracketed **`Since 2026-08-08:`** note follows it. Nothing in the original text
has been deleted or reworded.*

## Findings by severity

| Severity | Count |
|---|---:|
| **Critical** — incorrect scientific output, data loss, security | **3** |
| **High** — blocks maintenance or peer review | **15** |
| **Medium** | **22** |
| **Low** — cosmetic | **15** |
| **Total** | **55** |

By category: correctness 23 (one shared with documentation) · documentation 9 · hygiene 9 ·
testing 6 · packaging 3 · architecture 3 · duplication 2.

> **Since 2026-08-08:** this table counts the original diagnostic's own findings only.
> Waves 3–6 added F-59..F-130 from the frozen-build, report-production and LLM-integration
> analyses. Current counts are in *Current state* above and are maintained in the register.

---

## The three things that most warrant immediate attention

> **Since 2026-08-08: all three are closed.** They are preserved below because the analysis
> behind them is the reasoning the fixes were built on, and because two of them
> (`_cache_key`, `input_errors.csv`) are still the clearest statement of *why* those
> subsystems look the way they do now. None of them is a live defect. Per-item closure notes
> follow each one.

### 1. The LLM cache is keyed on the criterion's *identifier*, not its *content* (F-01, Critical)

`_cache_key` hashes `prompt_version | model | cid | a_id | text_hash | trunc_chars`
(`plugins/_common/llm_client.py:397-414`). But the prompt sent to the model carries the
criterion's `type`, `operator`, `target`, `what`, `label`, and `threshold`
(`plugins/06_el/screen.py:434-443` → `prompt.py:42-51`). Edit the wording of `IC-1` in the
Harmoniser — the single most likely action during a live review — keep the id, re-run, and
**every record comes back from cache with the *previous* criterion's answer**. The evidence
JSON will display a quote and a decision produced against text the model never saw in this
run. The UI reports a perfectly normal `cache_hits=N`.

This is the one place where the reproducibility mechanism actively produces wrong science
rather than preventing it. The fix is to hash the serialised criterion pack into the key; it
invalidates the committed EL/IL cache goldens and needs a re-capture, which should be a
deliberate decision rather than a reason to leave it.

> **Since 2026-08-08:** fixed in wave 2. `plugins/_common/llm_client.py::_cache_key` now
> hashes the **fully rendered prompt** together with model, temperature and prompt version —
> a stronger fix than the one proposed here, because it covers anything that changes what
> the model sees rather than an enumerated list. Its docstring records the principle:
> *"Enumeration was itself the bug."* Recorded in `CHANGELOG.md` [Unreleased] → ### Fixed.
> Two residues remain open: the key still omits the **endpoint**, so one model name served
> by two providers is one namespace (**F-89**), and a mid-retry truncation step-down still
> keys on the un-reduced prompt (**F-102**).

### 2. Two silent data-loss paths in the audit trail (F-02, F-03, Critical)

**Cancellation truncates without a marker.** `if cancel_event.is_set(): break`
(`plugins/_common/runner.py:101,119`; `06_el/screen.py:430,511`; `07_il/screen.py:432,513`)
exits the per-row loop mid-corpus and returns the partial results as though complete.
Records never evaluated simply do not appear in the FULL report. An exported bundle from a
cancelled run is indistinguishable from a complete run over a smaller corpus.

**`input_errors.csv` — the record of which citations were dropped as malformed — is written
with three mutually incompatible schemas and then deleted.** The Harmoniser writes
`record_number,reason,observed_len,expected_len,raw`; EH/IH write
`record_index_ex_header,reason,raw_record`; EL/IL write `reason,row_json`. The only reader
(`plugins/_common/parser.py:318-338`) expects the second. I verified directly that feeding
it the Harmoniser's file returns `[]` — so every citation dropped at ingestion loses its
provenance at the first pipeline hop, and `04_eh/ui.py:460` then cheerfully reports
"Imported previous input_errors: … (0 rows)". At EL, the file is in the copy-forward skip
set (`06_el/ui.py:1003`) and is only rewritten if EL itself skipped rows — so it is
**removed from the bundle entirely**.

For a tool whose value proposition is the audit trail, a dropped citation whose record of
being dropped is also dropped is the most consequential defect in the repository.

> **Since 2026-08-08:** both fixed in wave 2. A cancelled run now returns a `cancelled` flag
> and cannot be exported; `data/input_errors.csv` has one schema, one writer, and every
> stage appends rather than overwrites, with reading still tolerant of all three legacy
> layouts. Wave 4a then found and closed five further defects in the same file's chain
> (F-67, F-68, F-71, F-74, F-75) — including a quoting bug that could make the audit file
> unreadable by its own reader, which is the same failure mode arriving through a different
> door. The analysis above is the reason that chain was audited at all.

### 3. `README.md` is corrupted, by the most recent commit on `main` (F-10, High)

`README.md` carries a UTF-8 BOM and **mojibake on 46 lines** — every em-dash
rendered as `â€"`, and `Québec` as `QuÃ©bec`. Affected lines include the opening sentence of
the Overview (17), the 776→73 headline (25), the bundle-format list (89-93), the platform
table (243-245), and the acknowledgements (411).

I traced it to commit **`365325c`, "docs: switch README DOI badge to concept DOI for
stability"** — the current `HEAD`. Its intent was to change one character in a DOI; its diff
is 49 insertions and 49 deletions. Every prior commit back to April has a clean, BOM-free
README. The signature is a read-as-cp1252 / write-as-UTF-8-with-BOM round trip, which is the
PowerShell 5.1 default for `Set-Content`/`Out-File`.

This matters disproportionately because it is the first screen a JORS reviewer sees, and
because `CHANGELOG.md:41` lists "Stripped UTF-8 BOMs from text files" as a 3.1.0
achievement — so it reads as a regression. The CI workflow explicitly declines to check for
this (`test.yml:15-18`, "Mojibake protection lives in the local pre-commit gates only"); that
local gate has now demonstrably failed once. A three-line Python step would run identically
on all four runners.

> **Since 2026-08-08:** fixed. The README is BOM-free and mojibake-free, the LICENSE BOM was
> stripped with it, and the CI guard this section argued for exists — `tools/check_encoding.py`,
> run on every cell. The prediction that a local-only gate was insufficient was correct.

---

## Everything else, in one paragraph each

**Duplication (F-14).** Confirmed and slightly worse than the brief estimated.
`04_eh/ui.py` vs `05_ih/ui.py`: **20 structurally differing lines out of 877** (98.9%
identical) — and *none* of them is logic; the two genuine EH/IH behavioural differences
already live correctly in `_common/runner.py`. `06_el/screen.py` vs `07_il/screen.py`: **36
of ~632** (97.0%). `prompt.py` pair: **8 lines, 7 of them docstring** — the only functional
difference is one string constant. Total measured twinning: **3,251 lines, 21% of the
`plugins/` tree.** `01_architecture.md` §4.7 gives a `StageSpec`-parameterised design, a
six-step migration order, and an honest statement of what the goldens do and do not protect.

> **Since 2026-08-08:** still open, and still the largest structural item in the register.

**The custom plugin loader (F-19, F-20).** `metascreener/plugin_manager.py` installs a
`MetaPathFinder` that intercepts every `plugins.*` import, strips `from __future__ import
annotations` lines, and `exec()`s the result. Measured costs: **runtime line numbers are off
by one** in every affected module (`run_el_screen` is at disk line 335, runtime
`co_firstlineno` 334); `__file__` is never set; `inspect.getsource` raises; there is no
bytecode caching (15,548 lines recompiled every launch); `plugins/__init__.py` never
executes. And the sanitiser silently corrupts string literals — demonstrated: a `__future__`
line inside a triple-quoted string makes `len(S)` return 1 instead of 34. Meanwhile **all
ten plugin modules import cleanly under stock `importlib.import_module`**, and the module
already puts `sys._MEIPASS` on `sys.path` for the frozen case. Verdict: replace, in two
steps.

> **Since 2026-08-08: the verdict was formally revised to "keep, with tests."** The
> measurement behind "stock `importlib` suffices" was taken in dev mode, which is not the
> case the loader exists for: in the frozen build the plugin packages ship as `--add-data`
> and are not importable modules, and measured there (`04_frozen_build.md`) the custom
> finder resolves correctly and all seven plugins load. A replacement would also have to
> handle two things the current loader does — package directories beginning with a digit are
> not valid `import`-statement identifiers, and the finder sanitises the source as it loads.
> Step (1), wrapping current behaviour in tests, stands and is now the whole of the work.
> The measured −1 runtime line shift is real and is the reason later documents cite
> `path::symbol` rather than `file:line`. See F-19.

**Tests and CI.** **166 passed, 0 failed, 0 skipped, 3.62 s** on a pristine `git archive
HEAD` export — fully offline, no key, no display. Both CI audit tools exit 0. Coverage is
**23% overall**, and the shape is deliberate rather than lazy: the deterministic scientific
core is well covered (`eval_grid_generator` 97%, `eval_ingest` 90%, `_common/parser` 76%,
`_common/runner` 71%, `screen.py` 62-63%) while the GUI is not (**4,447 statements across
`ui.py`/`standalone.py`, 92.8% never executed** — 7,092 source lines). Two untested surfaces
matter more than the GUI headline: `plugins/02_references_of_x/` is 1,984 statements at
**0%**, and `run_m1_llm_for_criterion` — the entire retry/batching/rate-limit path — is
**0%**. The 16-cell CI matrix is appropriate in breadth but cannot compensate for that.

> **Since 2026-08-08:** the suite is 422 passed, 4 skipped. **Every percentage in this
> paragraph was measured against a 166-test suite and none has been re-measured — treat them
> all as stale rather than as current figures.** Both named 0% surfaces are now exercised:
> `plugins/02_references_of_x/` by `tests/test_refx_ingest_encoding.py` and the plugin
> contract and lifecycle suites, and `run_m1_llm_for_criterion` by
> `tests/test_cancellation.py`. F-12 was **narrowed** rather than closed on that basis: the
> happy path runs, and it is the error and salvage branches — and the transport layer
> entirely — that remain uncovered. No coverage percentage is quoted anywhere in the set
> now, because three mutually incompatible figures are in circulation and the instrument may
> be reading the shifted line numbers described above; **F-113** proposes settling it with
> the `pytest-cov` that CI already installs and never invokes.

**Documentation.** All markdown links resolve (139 references checked, zero broken `[…]` + `(…)`).
The prose has three real errors: `docs/usage.md:206,234,269` name `reports/{eh,ih,el}_decisions.csv`,
which the software **never produces** (real names are `*_FULL.csv` / `*_SURVIVORS.csv`);
`CHANGELOG.md:35` announces `docs/internal/reviewer-response-map.md`, which does not exist in
the tree or in any commit; and the README's test counts say "104 automated tests" and
"Status: ✅ 73 passed" against an actual 166. The README's *scientific* numbers, by contrast,
check out: 776 records verified by parsing the sample corpus, 90.6% and 98.3% arithmetically
exact and mutually consistent, the 0.6 default threshold confirmed in three code locations.

> **Since 2026-08-08:** all three were fixed in `94c2c1e` (F-16, F-17, F-30) — **and the
> third fix re-armed its own trap.** Refreshing the count to the then-current 166 left a
> number in prose that has drifted again; wave 6 removed the counts rather than refreshing
> them a second time, and logged the recurrence as **F-124**. Wave 6 also found that the LLM
> subsystem's user documentation describes a different program in ten further respects
> (**F-125**) and that four passages claim the manifest records the model and prompt version
> when it records neither (**F-123**, owned by **F-88**).

**Packaging.** `requirements.txt`, `pyproject.toml`, `Dockerfile`, and CI agree on the
dependency set — but **eight of nine dependencies are entirely unpinned**, and the ninth's
`>=1.40.0` now admits `openai 2.x`. A fresh install today resolves to `openai 2.53.0`,
`pandas 3.0.5`, `numpy 2.4.6`. For a project whose Zenodo description claims to satisfy
"the audit and reproducibility requirements expected in rigorous evidence synthesis
methodology", the software cannot reproduce its own dependency set. Separately,
`hook-plugins.py` has **never had any effect** (both specs set `hookspath=[]`), and because
`plugins/` is bundled as *data* that PyInstaller does not analyse, `pandas`, `openpyxl`,
`langdetect`, `rapidfuzz`, `PIL`, and `pytesseract` appear to be missing from the frozen
build entirely — which would silently remove five of seven tabs. That prediction needs one
build to confirm.

> **Since 2026-08-08: the build was done, and the prediction was wrong in its specifics.**
> `04_frozen_build.md` records the measurement: three of the six predicted packages were
> missing, not six — `pandas`, `openpyxl` and `PIL` were present by accident, pulled in
> transitively by `collect_all('openai')` — and **no tab was lost**, because every heavy
> dependency sits behind a feature flag or a lazy import. F-09 was downgraded High → Medium
> on that evidence, and the real cost was found to be silent feature degradation instead
> (F-66). The `hookspath=[]` diagnosis was correct but incomplete: setting `hookspath=['.']`
> alone changes nothing, because nothing statically imports `plugins`, so the hook is never
> looked for (F-40). Both are fixed in `d8d8a96`. **The dependency-pinning half of this
> paragraph stands unchanged and remains open (F-15)**, and wave 6 added the seam beneath it:
> the whole HTTP stack arrives only as a transitive analysis product and is named in neither
> spec (**F-120**).

---

## What not to break

The `PASS_FLAGGED` discipline; the evidence gate (which survived a field-by-field
adversarial read — every malformed response degrades to "flagged", and quotes are validated
against the *exact truncated text the model was shown*, recomputed per call); the
golden-file mechanism and the `.gitattributes binary` rule that protects it; the two AST
audit tools; the blind-adjudication validation design; and the pure-Python kappa
implementations, which I re-derived independently and which are **exactly correct against
published reference values**, edge cases included. Full detail in `03_findings.md`.

> **Since 2026-08-08: two of these need a caveat, and one needs an extension.** The evidence
> gate's adversarial read holds for *malformed* responses — but F-86 defeats it with a
> *well-formed* response naming another record, whose quote is genuine and validates. That
> is not a hole the read was looking for. And the `.gitattributes binary` rule is correct and
> load-bearing precisely as described, but it covers only `tests/golden/**`; the corpus the
> goldens are re-captured *from* is not covered, which makes a re-capture depend on the
> maintainer's `core.autocrlf` (F-99). The kappa verification and the blind-adjudication
> design stand entirely.

---

## Two things a reader of this report should know about it

1. **Writing this report breaks the test suite.** `tests/test_metadata.py:167` requires every
   markdown file anywhere under `docs/` to be listed in `docs/index.md`, so these five files
   cause `1 failed, 165 passed` (`test_every_doc_listed_in_index`). That is finding F-29, and it is very likely why
   `docs/internal/reviewer-response-map.md` was removed from the repo after the CHANGELOG
   announced it. Excluding `docs/internal/**` from the two cross-reference tests is a
   prerequisite for keeping internal documents in-tree.

   > **Since 2026-08-08: no longer true, and the diagnosis was right.** F-29 was the first
   > fix committed after this report landed. `tests/test_metadata.py` now defines
   > `DOCS_INTERNAL_DIRS` and exempts `docs/internal/**` from both cross-reference tests, so
   > no index action is needed for any document in this directory. The suite is green with
   > all eight of them present. *(Eight, not five — 04, 05, 06 and this file were added
   > later.)*

2. **Fifteen questions could not be answered from the code alone** and are listed at the end
   of `03_findings.md`. The most consequential is **Q1**: the README says the pipeline ends at
   **73** records; replaying the committed goldens gives **80**. The goldens were captured at
   non-default settings, so these may legitimately be two different runs — but as the
   repository stands, the reproducibility evidence a reviewer can actually execute disagrees
   with the headline figure, and nothing reconciles them.

   > **Since 2026-08-08:** **Q1 was resolved in wave 3** (`a794cc9`, written up in
   > `docs/llm-evaluation.md`), and Q2 (has a build ever been produced?) and Q3 (is the
   > loader solving a problem I cannot see?) were both answered by the frozen-build
   > measurement — Q3 in the affirmative, which is what revised F-19. The remaining twelve
   > stand, and `06_llm_integration.md` §B9 adds ten further maintainer decisions and §B10
   > four pending human observations. The list at the end of `03_findings.md` has not been
   > re-ordered, so Q1–Q3 still appear there as open; read them with this note.
