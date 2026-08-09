# Changelog

All notable changes to metaScreener are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- A stage with zero enabled criteria no longer reports every record as a clean
  pass (F-34). It assigned `PASS_CLEAN` — the stronger of the two survivor
  labels, meaning "every criterion was met" — to every record and reported
  every record as a survivor, so a stage that did no work was indistinguishable
  from one that ran correctly and excluded nothing. Records now get a distinct
  `NOT_SCREENED` outcome counted in its own bucket, the run summary and status
  line say so instead of "Done.", export requires an explicit acknowledgement,
  and `manifest.pipeline.history[]` records the no-op so a reviewer
  reproducing the pipeline can see it without re-running the GUI. The records
  still pass through to the next stage — not having screened them is no reason
  to drop them. A criterion that exists but is disabled now counts as absent
  for this purpose; disabled criteria were previously still being evaluated.
- EL and IL now refresh the manifest's SHA-256 map on export and verify it on
  load (F-05). Neither did before — the string `sha` appeared nowhere in either
  UI or either standalone shell — while both overwrite `data/current.csv` with
  the stage's survivors, so every bundle leaving EL or IL asserted a digest for
  a file it had just replaced, and nothing downstream checked. A digest that is
  present and wrong is worse than none: it turns an integrity check into false
  assurance. The four near-identical EL/IL export copies are now one shared
  writer, which is what makes the refresh unforgettable. The README claim
  softened in Wave 0 is restored, minus the tamper-resistance it never had.
- `data/input_errors.csv` — the record of which citations were dropped as
  malformed — now has one schema, one writer, and survives the pipeline
  (F-03). It previously had three schemas (one per writer), a reader that
  understood only one of them, and a copy-forward skip in EL that deleted the
  file outright on any run where EL itself skipped nothing. A citation the
  Harmoniser dropped was therefore already invisible by EL, and gone from the
  bundle afterwards. The schema is the Harmoniser's, widened rather than
  narrowed, plus a `stage` column; every stage appends instead of overwriting;
  and reading stays tolerant of all three legacy layouts so existing bundles
  still load. EH's "Imported previous input_errors: … (0 rows)" was the reader
  failing rather than a count, and now reports truthfully.
- A cancelled screening run can no longer be exported (F-02). All four stage
  engines now return a `cancelled` flag alongside their results; the stage UIs
  refuse both the XLSX and the next-bundle export while it is set, and say why.
  Previously the row loop exited mid-corpus and returned the rows it had
  reached as though they were the whole corpus, so an exported bundle from a
  cancelled run was indistinguishable from a complete run over a smaller
  one — and it is the survivor list that becomes the next stage's input. If a
  partial run is written by some other path, `manifest.pipeline.history[]` now
  carries `cancelled: true` and the stage marker reads `cancelled`.
- Cancelling an LLM stage no longer throws away answers already received and
  paid for (F-26). The cancel check raised past `return out`, discarding every
  completed batch; and because the post-call check sat inside the per-batch
  retry block, the generic error handler caught it and rewrote the whole batch
  as `uncertain` with `error="Cancelled"`, replacing real answers with
  fabricated non-answers.
- The LLM response cache key is now derived from a hash of the fully-rendered
  prompt (plus model and temperature) rather than from an enumerated list of
  invocation parameters (F-01). Previously the key carried only the criterion's
  *id*, so editing a criterion's wording while keeping its id produced a cache
  hit: every record was served the previous criterion's answer, with evidence
  quotes taken against text the model never saw on that run, while the UI
  reported a normal `cache_hits=N`. The same omission applied one level down —
  the record text hash covered only the criterion's *target* fields, although
  the prompt ships title, abstract and keywords for every criterion.

### Pending re-capture
- The EL/IL cache goldens (`tests/golden/{el,il}_cache_v3.1.0.json`) are keyed
  by the hash changed above, so `test_el_regression` and `test_il_regression`
  byte-identity currently fail by construction. Re-keying was verified to be a
  pure relabelling — 170 EL and 84 IL entries map 1:1 onto new keys with
  byte-identical decisions, no collisions and no orphans — but the re-capture
  itself is deliberately **not** committed here and awaits sign-off.

## [3.1.0] - 2026-04-29

### Added
- Citation File Format metadata (`CITATION.cff`)
- Pre-filled Zenodo deposit metadata (`.zenodo.json`)
- This changelog
- SPDX license headers in all source files
- Human-vs-LLM agreement validation infrastructure (`tools/eval_grid_generator.py`,
  `tools/eval_ingest.py`) with pure-Python Cohen's and Fleiss' kappa computation,
  exercised against textbook reference values and edge cases in
  `tests/test_eval_ingest.py`
- Persistent archive of validation evidence under `docs/data/`: empty grids,
  partition manifest, filled grids from all three raters, joined human + LLM
  decisions, agreement summary, per-(stage, criterion) confusion matrices, and
  the 88-row disagreement subset
- Validation methodology documentation (`docs/llm-evaluation.md`) with full
  polarity-aware status-mapping table and reproducibility instructions
- Installation guide (`docs/installation.md`) covering PyPI, source, and Docker
  installation paths
- Top-level documentation landing page (`docs/index.md`) cross-linked from README
- End-to-end usage walk-through (`docs/usage.md`) with annotated per-plugin
  screenshots under `docs/images/usage/`
- Frequently asked questions document (`docs/faq.md`) with documentation
  cross-reference test coverage in `tests/test_metadata.py`

### Changed
- Bumped version to 3.1.0 for peer-review revision release
- Stripped UTF-8 BOMs from text files
- Translated remaining French inline comments to English
- Renamed Python package `prisma_hub/` → `metascreener/` for naming consistency
- Renamed application class `PrismaHubApp` → `MetaScreenerApp`
- Renamed PyInstaller spec files: `PRISMA Hub.spec` → `metaScreener.spec`, `PRISMA Hub (console).spec` → `metaScreener-console.spec`
- Renamed Plugin 01 folder to `plugins/01_reference_extractor/` and flagged as experimental
- Plugin 01 UI tab now labeled with explicit `(experimental)` scope warning
- Plugin 01 frame now displays an experimental scope banner
- Rater grid generator (`tools/eval_grid_generator.py`) writes rater workbooks
  with verbatim criterion text in dropdown options and YES/NO/uncertain natural-
  language vocabulary, and deliberately strips the LLM-evidence columns from
  input filtered CSVs so that raters are blind to the LLM's per-record decision
  (guarded by `test_decisions_sheets_do_not_expose_llm_columns`)
- LLM-status-to-canonical-decision mapping in `tools/eval_ingest.py` is now
  polarity-aware: `MET`/`FAILED` map to canonical `yes`/`no` for inclusion
  criteria and invert to `no`/`yes` for exclusion criteria, so that humans and
  LLM are compared on a single canonical "does the criterion's claim hold?"
  scale
- Manuscript figures (Figure 1 pipeline architecture, Figure 2 screening funnel)
  rebuilt to fix legend-overflow and text-clipping issues raised by Reviewer 2
- Manuscript Quality control section: demonstration-vs-validation wording
  reconciled; new "Human validation" subsection added reporting per-criterion
  Cohen's and Fleiss' kappa, observed agreement, prevalence-paradox
  interpretation, asymmetric-hedging finding, and an explicit limitations
  paragraph
- Manuscript Introduction: related-work paragraph added acknowledging an
  unrelated tool of the same name (Hong, 2025)
- Manuscript: new Figure 3 added showing the Criteria Parser desktop interface
- Manuscript Reuse potential: expanded with concrete plugin-extension examples
  and external-data-source integration points

### Fixed
- Removed hardcoded developer-machine venv path (`S:\prisma-hub\.venv\…`) from PyInstaller spec files

### Removed
- `plugins/_parking_lot/` (historical drafts folder, retained in git history)
- Timestamped backup `.py` files in `prisma_hub/` and `plugins/*/` directories

### Deferred

- Per-plugin `screen.py` files contain stage-tuned copies of helpers
  (`_safe_str`, `_decode_bytes`, `_load_bundle`, etc.) that overlap
  with `plugins/_common/` versions. Substitution would require a
  unified `_common/parser.py` + `_common/bundle.py` whose behavior
  preserves all four stages' (EH, IH, EL, IL) byte-identity goldens
  simultaneously. Deferred pending broader empirical experience
  across diverse corpora.
- Per-stage running-time estimation in the UI (Reviewer 2 optional item O4);
  requires per-model latency profiling not yet completed across supported
  providers.
- UI exposure of per-criterion confidence threshold (Reviewer 2 optional item
  O5); the threshold mechanism exists internally in the harmonized criteria
  CSV but interactive UI exposure requires confidence-calibration work not yet
  completed.
- Pipeline video walk-through (Reviewer 2 optional item O6); deferred until
  post-acceptance so that on-screen text matches the final published
  manuscript and documentation.

## [3.0.1] - 2026-04-04

Initial GitHub-tagged release. See https://github.com/lars-ulaval/metaScreener/releases/tag/v3.0.1
