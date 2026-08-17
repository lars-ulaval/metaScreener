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
  gotchas. Uses the sample data in [`samples/`](../samples/)
  as the running example.

- **[FAQ](faq.md)** — answers to common questions about
  configuration, costs and caching, the bundle pipeline, LLM
  stages and human validation, reproducibility, and known edge
  cases.

## Evidence files

The [`data/`](data/) subdirectory holds reproducibility evidence for
the human-vs-LLM agreement study:

- [`data/study_input/`](data/study_input/) — the study's frozen input:
  the screening output being adjudicated, the criteria table, and the
  post-IH record set. Pinned by
  [`SHA256SUMS`](data/study_input/SHA256SUMS) and never re-captured, so
  the regression fixtures under `tests/golden/` can move without
  rewriting the input of a published analysis.
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
- [`data/wave17_arms/ANALYSIS_WAVE_17_ARMS.md`](data/wave17_arms/ANALYSIS_WAVE_17_ARMS.md)
  — what the seven wave-17 criteria-experiment arms measured: the
  paraphrase-sensitivity replication, the `target`-hint comparison,
  registered intent against outcome per arm, and a record-by-record
  judgement of the pile the baseline arm produces. Derived entirely from
  the committed artefacts under
  [`data/wave17_arms/`](data/wave17_arms/); no run was made to produce it.

Re-running [`tools/eval_ingest.py`](../tools/eval_ingest.py) against
the committed grids and manifest reproduces all four evidence files
byte-for-byte; the command line is documented in
[`llm-evaluation.md`](llm-evaluation.md#reproducibility).
