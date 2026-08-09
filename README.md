# metaScreener

**A plugin-based desktop application for human-in-the-loop systematic literature screening.**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19360124.svg)](https://doi.org/10.5281/zenodo.19360124)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows%2010%2B-blue.svg)](#platform-compatibility)
[![Platform: macOS/Linux](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-lightgrey.svg)](#platform-compatibility)
[![CI](https://github.com/lars-ulaval/metaScreener/actions/workflows/test.yml/badge.svg)](https://github.com/lars-ulaval/metaScreener/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/metascreener-lars-ulaval.svg)](https://pypi.org/project/metascreener-lars-ulaval/)

---

## Overview

metaScreener is an open-source, cross-platform desktop application that automates citation screening for systematic literature reviews. It combines deterministic heuristic-based filters with large language model (LLM) inference in a sequential, auditable pipeline — all through a graphical interface that requires no programming expertise.

The software is designed around three principles:

- **GUI-first**: every function is accessible through a graphical interface built on Python/Tkinter — no command-line interaction, no scripts, no API knowledge required.
- **Bundle pipeline**: each plugin stage consumes a ZIP archive produced by the preceding stage and emits a new archive containing the full accumulated state, ensuring that every intermediate decision is preserved and portable.
- **Human-in-the-loop**: no record is silently excluded. Records for which automated decisions cannot be grounded in sufficient evidence are routed to an explicit human review queue.

In a demonstration use case comprising 776 candidate records, the pipeline reduced the corpus to 73 records requiring full human review — a 90.6% reduction — with deterministic pre-filtering accounting for 98.3% of exclusions.

---

## Documentation

Full project documentation lives in [`docs/`](docs/index.md):

- [Installation guide](docs/installation.md) — detailed setup, configuration reference, verification, troubleshooting, upgrading.
- [LLM-screening human validation](docs/llm-evaluation.md) — methodology, agreement metrics, and limitations from the demonstration-corpus validation study.

See the [documentation index](docs/index.md) for the full table of contents.

---

## Pipeline architecture

metaScreener organises its screening workflow into seven plugins across four functional groups:

### Corpus ingestion

| # | Plugin | Description | Method |
|---|--------|-------------|--------|
| 01 | **Reference Markers** (experimental) | Extracts visually-present reference markers (e.g., `[1]`, `[Smith 2022]`) from images supplied as PDF or PNG | GPT-4o vision API |
| 02 | **References-of-X AI** | Resolves and enriches bibliographic references via federated queries | OpenAlex, Crossref, Semantic Scholar |

> **⚠ Plugin 01 is experimental.** It is designed for images containing visible
> reference markers (e.g., numbered or author–year citation lists rendered as
> image text). Standard PRISMA flow diagrams typically do not contain such
> markers, and feeding one as input may produce hallucinated output. Plugin 01
> output should always be verified by the researcher before downstream use.

### Criteria structuring

| # | Plugin | Description | Method |
|---|--------|-------------|--------|
| 03 | **Criteria Parser** | Converts free-text inclusion/exclusion criteria into a structured, machine-executable criteria table (`criteria_harmonized.csv`) | Rule-based inference + optional LLM refinement |

The Criteria Parser accepts plain-text criteria (e.g., `ic_ec_12.txt`) and automatically assigns each criterion to the appropriate pipeline stage (EH/IH for deterministic rules, EL/IL for semantic rules) based on six pattern categories: language, year, document type, venue, DOI, and keyword-in-text. An optional LLM refinement pass adjusts the assignments under structural guardrails (row-count and identifier invariance). **The harmonized output should always be reviewed by the researcher before proceeding.**

### Deterministic heuristic-based filtering

| # | Plugin | Description | Method |
|---|--------|-------------|--------|
| 04 | **EH** (Exclusion by Heuristic) | Removes records matching any exclusion criterion at title/abstract level | Keyword / regex matching |
| 05 | **IH** (Inclusion by Heuristic) | Retains only records matching at least one inclusion criterion | Keyword / regex matching |

These stages execute without LLM inference, incur no token cost, and impose no latency. They are designed to handle the bulk of exclusions before records reach the LLM stages.

### LLM-assisted filtering

| # | Plugin | Description | Method |
|---|--------|-------------|--------|
| 06 | **EL** (Exclusion by LLM) | Applies LLM-based eligibility adjudication against exclusion criteria over full record text | OpenAI-compatible endpoint, T=0.0 |
| 07 | **IL** (Inclusion by LLM) | Applies LLM-based eligibility adjudication against inclusion criteria over full record text | OpenAI-compatible endpoint, T=0.0 |

Both LLM stages implement **evidence gating**: a screening decision is accepted only when the model provides (1) a confidence score meeting or exceeding a configurable threshold (default 0.6) and (2) a verbatim quotation verifiable as a substring of the source record. Records failing either condition receive a `PASS_FLAGGED` outcome and are routed to the human review queue. All LLM responses are persisted in a local cache keyed by content hash, enabling exact re-runs without additional API cost.

---

## Bundle format and audit trail

Each plugin produces a **bundle ZIP archive** containing:

- `manifest.json` — pipeline configuration (criteria file hash, prompt version, model ID, UTC timestamp)
- `data/current.csv` — the canonical citation table at the current stage
- `criteria/criteria_harmonized.csv` — the machine-executable criteria specification
- `reports/` — per-stage decision reports with full evidence trails
- `cache/` — JSONL caches of LLM responses (one file per stage)

Bundles are integrity-verified using **SHA-256 hashes** at ingestion and export. Any modification to the record set or configuration between stages is detectable.

---

## Installation

### Option A — Install from PyPI

```bash
pip install metascreener-lars-ulaval
```

### Option B — Install from source

#### Prerequisites

- **Python 3.10 or later** (with Tkinter — included by default on Windows and macOS; on Linux, install `python3-tk`)
- **An OpenAI API key** (required for Plugins 01, 03, 06, 07; not required for Plugins 02, 04, 05)

### Windows

```powershell
# Clone the repository
git clone https://github.com/lars-ulaval/metaScreener.git
cd metaScreener

# Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Configure your API key
copy .env.example .env
# Edit .env and add your OpenAI API key

# Run
python run.py
```

### macOS

```bash
# Clone the repository
git clone https://github.com/lars-ulaval/metaScreener.git
cd metaScreener

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure your API key
cp .env.example .env
# Edit .env and add your OpenAI API key

# Run
python run.py
```

### Linux (Ubuntu/Debian)

```bash
# Ensure Tkinter is available
sudo apt-get install python3-tk

# Clone the repository
git clone https://github.com/lars-ulaval/metaScreener.git
cd metaScreener

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure your API key
cp .env.example .env
# Edit .env and add your OpenAI API key

# Run
python run.py
```

> **Note on Tesseract**: Plugin 01 (Reference Markers, experimental) can optionally use Tesseract OCR for fallback text extraction. If needed, install Tesseract separately for your platform and ensure `tesseract` is on your PATH.

---

## Quick start

1. **Launch** the application with `python run.py`. You will be prompted for your OpenAI API key.

2. **Prepare your inputs**:
   - A **criteria file** in plain text (see `docs_/samples/ic_ec_12.txt` for format — one criterion per line with `IC-N` / `EC-N` identifiers)
   - A **citation corpus** as an aggregate CSV (see `docs_/samples/20260122_1654_aggregate.csv` for the expected schema)
   - Or, for the experimental Plugin 01, an image (PDF or PNG) containing **visible reference markers** (numbered or author–year citation lists). *Note: standard PRISMA flow diagrams typically do not contain reference markers.*

3. **Run the pipeline** sequentially through the tabs:
   - **Tab 1 (Reference Markers, experimental)**: supply an image (PDF or PNG) containing visible reference markers; extract them. *Skip this tab if you already have an aggregate CSV.*
   - **Tab 2 (References-of-X AI)**: resolve and enrich extracted references
   - **Tab 3 (Criteria Parser)**: load criteria + aggregate CSV, review the harmonized output, export a bundle ZIP
   - **Tab 4 (EH)**: load the bundle, run exclusion by heuristic
   - **Tab 5 (IH)**: load the EH output bundle, run inclusion by heuristic
   - **Tab 6 (EL)**: load the IH output bundle, run LLM exclusion
   - **Tab 7 (IL)**: load the EL output bundle, run LLM inclusion

4. **Review results**: the final bundle ZIP contains `reports/IL_FULL.csv` with every record and its per-criterion decision evidence, and `reports/IL_SURVIVORS.csv` with the final included set.

---

## Sample data

The `docs_/samples/` directory contains minimal sample inputs for testing:

| File | Description |
|------|-------------|
| `ic_ec_12.txt` | Sample inclusion/exclusion criteria (4 IC + 4 EC) for a VR/HMD workplace training review |
| `20260122_1654_aggregate.csv` | Sample aggregate citation corpus (776 records) with structured metadata fields |
| `ex_ref_2.txt` | Sample free-text reference list for Plugin 02 |

---

## Dependencies

| Package | Role | Stage(s) |
|---------|------|----------|
| `openai` (≥1.40.0) | LLM API client | 01, 03, 06, 07 |
| `pymupdf` | PDF parsing and image extraction | 01 |
| `pillow` | Image processing | 01 |
| `pytesseract` | OCR fallback (optional) | 01 |
| `rapidfuzz` | Fuzzy title matching for reference resolution | 02 |
| `requests` | HTTP client for bibliographic API queries | 02 |
| `pandas` | CSV/XLSX data handling | 02, 03 |
| `openpyxl` | Excel file support | 03 |
| `langdetect` | Language detection | 04, 05 |

All dependencies are listed in `requirements.txt`.

---

## Platform compatibility

| Platform | Status | Notes |
|----------|--------|-------|
| Windows 10+ | ✅ Verified by CI | `windows-latest` (Windows Server 2022 runner), Python 3.10–3.13 |
| macOS 14+ (Apple Silicon) | ✅ Verified by CI | `macos-14` runner, Python 3.10–3.13 |
| Linux (Ubuntu 22.04 / 24.04) | ✅ Verified by CI | `ubuntu-22.04` and `ubuntu-24.04` LTS runners, Python 3.10–3.13 |

The application is pure Python with no compiled extensions and runs on any platform supporting Python 3.10+ and Tkinter. Cross-platform compatibility is continuously verified by the GitHub Actions matrix on every push; see the [live CI status](https://github.com/lars-ulaval/metaScreener/actions/workflows/test.yml) for current run results.

---

## Testing

The project includes 104 automated tests covering the deterministic components of the pipeline as well as quote-based evidence gating, plugin imports, bundle integrity, repo metadata consistency, and per-stage regression goldens. No OpenAI API key, network access, or graphical display server is required.

```bash
pip install pytest
python -m pytest tests/ -v
```

The test suite covers seven areas:

| Module | Tests | Coverage |
|--------|-------|----------|
| `test_criteria_parser.py` | 16 | Free-text criteria parsing, operator/stage inference |
| `test_deterministic_filters.py` | 15 | EH/IH `_eval_criterion` for all operator types |
| `test_evidence_gating.py` | 23 | Quote validation, SHA-256 hashing, cache key construction |
| `test_bundle_integrity.py` | 12 | Bundle ZIP structure, manifest schema, hash verification |
| `test_imports.py` | 27 | Module imports, plugin shim regression, cache-key invariants |
| `test_metadata.py` | 2 | Repo metadata consistency (version match, README CI badge) |
| Per-stage regression suites | 9 | Byte-identity goldens for the EH, IH, EL, IL, and Harmoniser plugins (one file per stage) |
| **Total** | **104** | |

### Refactoring safety: static import audit

In addition to the runtime tests, refactoring commits should pass a static `ast`-based audit
that catches missing imports the test suite can't see (e.g., a private engine function
called only via Tkinter View workflow methods, which headless test runs mock out):

```bash
python tools/audit_imports.py plugins/03_harmoniser/
```

Exit code 0 means every name reference in every module resolves to an import, definition,
parameter, local binding, or builtin. Exit code 1 lists the offenders. Designed to run
alongside `pytest -q` as a pre-commit gate when extracting code into new modules.

Tested on Windows 10 and Ubuntu 24.04 (headless, via WSL/Docker).

> **Status**: ✅ 73 passed

---

## Configuration

### Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes (for LLM stages) | — | Your OpenAI API key |
| `SCREENA_EL_MODEL` | No | `gpt-4o-mini` | Model identifier for the EL stage |
| `SCREENA_EL_TRUNC_CHARS` | No | `1500` | Maximum characters per field sent to the LLM |
| `SCREENA_EL_BATCH_SIZE` | No | `50` | Number of records per LLM API call |
| `SCREENA_EL_USE_CACHE` | No | `1` | Enable (`1`) or disable (`0`) the persistent decision cache |

Copy `.env.example` to `.env` and set your API key. The application will prompt for confirmation on each launch.

## Using local LLM providers

metaScreener targets any **OpenAI-compatible API endpoint**. The default backend is OpenAI's hosted API, but the same Python client transparently supports:

- **Hosted commercial APIs** — Azure OpenAI, DeepSeek, and others that mirror OpenAI's chat completions schema.
- **Locally hosted models** — open-weight models served via compatible inference frameworks such as Ollama, llama.cpp, and vLLM.

Switching providers requires no code change: set the `OPENAI_BASE_URL` environment variable to the target endpoint and ensure `OPENAI_API_KEY` is non-empty (most local servers ignore the key value but require it to be set). The **Model** field in metaScreener's EL/IL Settings panels then selects which backend model to use. Three commonly used local-model paths are described below.

### Ollama

[Ollama](https://ollama.com/) exposes an OpenAI-compatible chat completions endpoint at `http://localhost:11434/v1`. After installing Ollama and pulling a model (e.g., `ollama pull llama3.1`), set `OPENAI_BASE_URL=http://localhost:11434/v1` and `OPENAI_API_KEY=ollama` (or any non-empty placeholder). In the EL/IL Settings panels, set **Model** to the local model name (e.g., `llama3.1`).

### llama.cpp

[llama.cpp](https://github.com/ggerganov/llama.cpp)'s `llama-server` binary exposes an OpenAI-compatible endpoint at `http://localhost:8080/v1` by default. Start the server with `./llama-server --model your-model.gguf` and set `OPENAI_BASE_URL=http://localhost:8080/v1` with `OPENAI_API_KEY=llama-cpp` (or any non-empty placeholder). The **Model** field can be set to any value when running llama.cpp directly, since the server uses whichever model is currently loaded.

### vLLM and DeepSeek

For higher-throughput self-hosted inference, [vLLM](https://github.com/vllm-project/vllm) exposes an OpenAI-compatible API tuned for batched GPU workloads; consult the vLLM documentation for the deployment-specific `OPENAI_BASE_URL`. As a hosted alternative, [DeepSeek](https://platform.deepseek.com/) provides an OpenAI-compatible endpoint at `https://api.deepseek.com/v1` with substantially larger context windows than GPT-4o-mini, useful when working with very long records. Use your DeepSeek API key as `OPENAI_API_KEY` for the hosted route.

> **Note**: open-weight model compatibility with the evidence gating protocol (which requires models to produce verbatim substring quotations) has not been formally tested. If you test with a local model, we welcome your feedback via the issue tracker.

---

## Project structure

```
metaScreener/
├── run.py                       # Application entry point
├── metascreener/
│   ├── main.py                  # Main window and tab orchestration
│   ├── plugin_api.py            # BasePlugin / PluginMeta contract
│   └── plugin_manager.py        # Dynamic plugin discovery and loading
├── plugins/
│   ├── 01_reference_extractor/        # Plugin 01: Reference Markers (experimental)
│   ├── 02_references_of_x/            # Plugin 02: References-of-X AI
│   ├── 03_harmoniser/                 # Plugin 03: Criteria Parser
│   ├── 04_eh/                         # Plugin 04: EH (Exclusion by Heuristic)
│   ├── 05_ih/                         # Plugin 05: IH (Inclusion by Heuristic)
│   ├── 06_el/                         # Plugin 06: EL (Exclusion by LLM)
│   └── 07_il/                         # Plugin 07: IL (Inclusion by LLM)
├── docs_/
│   └── samples/                 # Sample input files
├── requirements.txt
├── .env.example
└── LICENSE                      # MIT License
```

---

## Extending metaScreener

metaScreener's plugin architecture is designed for extensibility. To create a new plugin:

1. Create a new directory under `plugins/` (e.g., `plugins/08_my_plugin/`)
2. Add a `plugin.py` file that either:
   - Defines a `build_tab(parent)` function returning a `tk.Frame`, or
   - Defines a class inheriting from `BasePlugin` with a `build_tab(self, parent)` method
3. Set `TAB_TITLE = "My Plugin"` at the module level
4. The plugin manager will automatically discover and load it on the next launch

Plugins communicate exclusively through bundle ZIP files — there is no shared state or database. Each plugin reads a bundle, processes it, and emits a new bundle.

---

## Citation

If you use metaScreener in your research, please cite:

```bibtex
@article{reyesconsuelo2026metascreener,
  author    = {Reyes-Consuelo, Alejandro and Kiss, Jocelyne and Voisin, Julien},
  title     = {metaScreener: A Plugin-Based Desktop Application for Human-in-the-Loop Systematic Literature Screening},
  journal   = {Journal of Open Research Software},
  year      = {2026},
  note      = {Submitted},
  doi       = {10.5281/zenodo.19360124}
}
```

---

## Contributing

Contributions are welcome. To contribute:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-improvement`)
3. Commit your changes
4. Push to the branch and open a pull request

Please ensure your code follows the existing style. For bug reports and feature requests, use the [issue tracker](https://github.com/lars-ulaval/metaScreener/issues).

---

## License

metaScreener is released under the [MIT License](LICENSE).

---

## Acknowledgements

This work is supported by the Center of Interdisciplinary Research in Rehabilitation and Social Integration ([CIRRIS](https://cirris.ulaval.ca/)), Laval University, Québec, Canada, and the International Observatory on the Societal Impacts of AI and Digital Technologies ([OBVIA](https://www.obvia.ca/)).

---

**Developed by [LARS — Laboratoire d'automatisation des recherches situées](https://github.com/lars-ulaval), Laval University**
