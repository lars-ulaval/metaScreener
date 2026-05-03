# Changelog

All notable changes to metaScreener are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Citation File Format metadata (`CITATION.cff`)
- Pre-filled Zenodo deposit metadata (`.zenodo.json`)
- This changelog
- SPDX license headers in all source files

### Changed
- Bumped version to 3.1.0 in preparation for peer-review revision release
- Stripped UTF-8 BOMs from text files
- Translated remaining French inline comments to English
- Renamed Python package `prisma_hub/` → `metascreener/` for naming consistency
- Renamed application class `PrismaHubApp` → `MetaScreenerApp`
- Renamed PyInstaller spec files: `PRISMA Hub.spec` → `metaScreener.spec`, `PRISMA Hub (console).spec` → `metaScreener-console.spec`
- Renamed Plugin 01 folder to `plugins/01_reference_extractor/` and flagged as experimental
- Plugin 01 UI tab now labeled with explicit `(experimental)` scope warning
- Plugin 01 frame now displays an experimental scope banner

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

## [3.0.1] - 2026-04-04

Initial GitHub-tagged release. See https://github.com/lars-ulaval/metaScreener/releases/tag/v3.0.1