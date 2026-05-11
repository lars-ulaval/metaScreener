# Changelog

All notable changes to metaScreener are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- Internal reviewer-response mapping matrix
  (`docs/internal/reviewer-response-map.md`) as a versioned reference for the
  JORS response letter

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
