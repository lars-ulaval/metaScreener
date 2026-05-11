# metaScreener documentation

This directory contains the project's user and methodological
documentation. For the high-level project description, badges, and
quickstart pointers, see the [project README](../README.md).

## Available documents

- **[Installation guide](installation.md)** — detailed setup
  instructions for Windows, macOS, and Linux, with prerequisites,
  configuration reference, verification steps, troubleshooting,
  upgrading, and uninstalling.

- **[LLM-screening human validation](llm-evaluation.md)** —
  methodology and results of the human-vs-LLM agreement study on the
  demonstration corpus. Covers the multi-annotator design, the
  polarity-aware mapping between LLM evidence and canonical
  decisions, Cohen's and Fleiss' kappa per criterion with confusion
  matrices, an explanation of the kappa paradox observed on the
  exclusion criteria, and limitations.

- **[Usage guide](usage.md)** — walkthrough of the seven plugins
  from corpus ingestion through to the final bundle export, with
  per-plugin inputs, outputs, configuration knobs, and common
  gotchas. Uses the sample data in [`docs_/samples/`](../docs_/samples/)
  as the running example.

- **FAQ** — forthcoming. Answers to common questions about
  configuration, model selection, bundle compatibility, and known
  edge cases. Will live at `docs/faq.md` once available.

## Evidence files

The [`data/`](data/) subdirectory holds reproducibility evidence for
the human-vs-LLM agreement study:

- [`data/grids/partition_manifest.csv`](data/grids/partition_manifest.csv)
  — per-rater record assignments (overlap vs disjoint), with seed and
  metadata in
  [`partition_manifest.meta.txt`](data/grids/partition_manifest.meta.txt).
- [`data/grids/filled/`](data/grids/filled/) — the three filled
  adjudication grids, one per co-author rater.
- [`data/eval_decisions_v1.csv`](data/eval_decisions_v1.csv) —
  long-format human decisions (344 rows).
- [`data/eval_results_v1.csv`](data/eval_results_v1.csv) — human
  decisions joined with LLM evidence and per-row agreement flag.
- [`data/eval_disagreements_v1.csv`](data/eval_disagreements_v1.csv)
  — the 88-row subset where the human and the LLM disagreed, sorted
  for spot-checking.
- [`data/eval_summary_v1.txt`](data/eval_summary_v1.txt) —
  human-readable summary with kappa values and 3x3 confusion matrices.

Re-running [`tools/eval_ingest.py`](../tools/eval_ingest.py) against
the committed grids and manifest reproduces all four evidence files
byte-for-byte; the command line is documented in
[`llm-evaluation.md`](llm-evaluation.md#reproducibility).
