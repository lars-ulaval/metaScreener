# metaScreener — Diagnostic Report: Executive Summary

**Scope:** complete static and offline-dynamic diagnostic of the repository at
`main` @ `365325c`, 121 tracked files, 22,175 lines of Python.
**Date:** 2026-08-08. **Mode:** read-only — no source file was modified.
**Audience:** the maintainer, and a coordinating Claude instance planning follow-up work.

| Document | Contents |
|---|---|
| [`00_overview.md`](00_overview.md) | Phase 1–2 — what the software is, domain glossary, project-identity audit, publication metadata, annotated tree, file inventory, `docs/` vs `docs_/`. |
| [`01_architecture.md`](01_architecture.md) | Phase 3–4 — startup trace, the custom plugin loader dissected, plugin contract compliance, stage-by-stage data flow, bundle format, two Mermaid diagrams, and the full duplication measurement + de-duplication design. |
| [`02_quality.md`](02_quality.md) | Phase 5–7 — test inventory and run results, coverage, the golden mechanism, CI assessment, error handling, evidence gating, LLM interaction, cache, determinism, kappa verification, input validation, portability, docs/packaging/hygiene. |
| [`03_findings.md`](03_findings.md) | Phase 8 — the prioritised register (55 findings), top-10 actions, what is genuinely good, 15 open questions. |

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

---

## The three things that most warrant immediate attention

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

### 3. `README.md` is corrupted, by the most recent commit on `main` (F-10, High)

`README.md` carries a UTF-8 BOM and **27 mojibake sequences across 25 lines** — every em-dash
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

**Tests and CI.** **166 passed, 0 failed, 0 skipped, 3.62 s** on a pristine `git archive
HEAD` export — fully offline, no key, no display. Both CI audit tools exit 0. Coverage is
**23% overall**, and the shape is deliberate rather than lazy: the deterministic scientific
core is well covered (`eval_grid_generator` 97%, `eval_ingest` 90%, `_common/parser` 76%,
`_common/runner` 71%, `screen.py` 62-63%) while the GUI is not (**4,447 statements across
`ui.py`/`standalone.py`, 92.8% never executed** — 7,092 source lines). Two untested surfaces
matter more than the GUI headline: `plugins/02_references_of_x/` is 1,984 statements at
**0%**, and `run_m1_llm_for_criterion` — the entire retry/batching/rate-limit path — is
**0%**. The 16-cell CI matrix is appropriate in breadth but cannot compensate for that.

**Documentation.** All markdown links resolve (139 references checked, zero broken `[…]` + `(…)`).
The prose has three real errors: `docs/usage.md:206,234,269` name `reports/{eh,ih,el}_decisions.csv`,
which the software **never produces** (real names are `*_FULL.csv` / `*_SURVIVORS.csv`);
`CHANGELOG.md:35` announces `docs/internal/reviewer-response-map.md`, which does not exist in
the tree or in any commit; and the README's test counts say "104 automated tests" and
"Status: ✅ 73 passed" against an actual 166. The README's *scientific* numbers, by contrast,
check out: 776 records verified by parsing the sample corpus, 90.6% and 98.3% arithmetically
exact and mutually consistent, the 0.6 default threshold confirmed in three code locations.

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

---

## What not to break

The `PASS_FLAGGED` discipline; the evidence gate (which survived a field-by-field
adversarial read — every malformed response degrades to "flagged", and quotes are validated
against the *exact truncated text the model was shown*, recomputed per call); the
golden-file mechanism and the `.gitattributes binary` rule that protects it; the two AST
audit tools; the blind-adjudication validation design; and the pure-Python kappa
implementations, which I re-derived independently and which are **exactly correct against
published reference values**, edge cases included. Full detail in `03_findings.md`.

---

## Two things a reader of this report should know about it

1. **Writing this report breaks the test suite.** `tests/test_metadata.py:167` requires every
   markdown file anywhere under `docs/` to be listed in `docs/index.md`, so these five files
   cause `1 failed, 165 passed` (`test_every_doc_listed_in_index`). That is finding F-29, and it is very likely why
   `docs/internal/reviewer-response-map.md` was removed from the repo after the CHANGELOG
   announced it. Excluding `docs/internal/**` from the two cross-reference tests is a
   prerequisite for keeping internal documents in-tree.

2. **Fifteen questions could not be answered from the code alone** and are listed at the end
   of `03_findings.md`. The most consequential is **Q1**: the README says the pipeline ends at
   **73** records; replaying the committed goldens gives **80**. The goldens were captured at
   non-default settings, so these may legitimately be two different runs — but as the
   repository stands, the reproducibility evidence a reviewer can actually execute disagrees
   with the headline figure, and nothing reconciles them.
