# Frequently asked questions

Answers to questions that come up frequently when installing, running,
or extending metaScreener. For deeper coverage of any topic below, the
linked references point at the relevant section of the
[installation guide](installation.md),
[usage guide](usage.md), or
[LLM-screening human validation document](llm-evaluation.md).

## Installation and environment

### Which Python versions are supported?

Python 3.10 or later. The application uses standard-library features
(structural pattern matching, parameterised generics syntax)
introduced in 3.10 and will fail to import on 3.9 or earlier. See
[Prerequisites > Python 3.10 or later](installation.md#python-310-or-later).

### Why does the GUI fail to launch on Linux?

Most often, Tkinter is not installed. On Debian/Ubuntu install with
`sudo apt-get install python3-tk`; equivalent commands for Fedora
and Arch are listed under
[Prerequisites > Tkinter](installation.md#tkinter). Verify with
`python -c "import tkinter; tkinter._test()"` — a small test window
should open.

### `pip install` fails on `pymupdf` or `pillow` on macOS

Install Xcode Command Line Tools (`xcode-select --install`) and
retry. On Apple Silicon, also confirm you are using the universal
Python installer from python.org rather than a Homebrew-only build.
See [Troubleshooting >
pip install fails on pymupdf or pillow](installation.md#pip-install-fails-on-pymupdf-or-pillow-macos).

### Do I need an OpenAI API key to run anything?

Only for the LLM-using plugins: 01 (Reference Markers), 03 (Criteria
Parser, when the optional LLM refinement pass is enabled), 06 (EL),
and 07 (IL). Plugins 02 (References-of-X), 04 (EH), and 05 (IH) are
deterministic and run without a key, as does the full test suite.

### Can I use a different LLM provider?

Yes, for any OpenAI-compatible endpoint. Set `OPENAI_BASE_URL` in
your `.env` to the alternative endpoint's base URL (Azure OpenAI, a
locally-hosted proxy, etc.). The configuration table is documented
in [Configuration > Optional environment
variables](installation.md#optional-environment-variables). Local
models that don't expose an OpenAI-compatible interface are not
currently supported out of the box but can be reached through a
proxy.

## Costs and caching

### How much will an LLM-stage run cost?

Costs scale with the number of records that reach the LLM stages, not
with corpus size — the deterministic stages run first and usually
remove most of the corpus. On the bundled demonstration corpus (776
records), only 85 reach EL and 84 reach IL, giving 254 individual
decisions in total; batched at the default of 50 per request, that is
a handful of API requests. Check the OpenAI pricing page for current
per-token rates. Subsequent runs are free because every response is
cached by content hash; see the next question.

Beware a units confusion in the project's own write-ups: a figure
like "170 EL calls" counts individual **decisions**, not HTTP
requests.

### How does the cache work?

Each LLM response is keyed by SHA-256 of the **fully rendered prompt**
together with the model identifier, the temperature and the prompt
version. Hashing the rendered prompt rather than a list of named
parameters means anything that changes what the model is shown —
criterion wording, record text, the fields targeted, the truncation
length — changes the key automatically. A second run with identical
inputs reuses the cached response without contacting the API.

The cache is stored **inside the bundle**, as
`cache/EL_cache.jsonl` and `cache/IL_cache.jsonl`, not in a directory
on disk. See
[Re-running and the LLM cache](usage.md#re-running-and-the-llm-cache).

### How do I re-decide part of the corpus without re-running everything?

Change what the model is shown, and only the affected entries miss.
Editing a criterion's wording re-decides every record for that
criterion and leaves the others cached; editing a record's text
re-decides that record. There is no way to target a single entry by
hand: the key is an opaque digest of the whole rendered prompt, so a
cache line carries no record or criterion identifier to search on.

To re-decide everything for one stage, untick **Use cache** before
running it. Note that exporting a bundle with the box unticked
currently drops the existing cache from the bundle rather than
preserving it, so copy the bundle first if you want to keep it.

### The cache keeps growing — how do I prune it?

There is no automatic pruning, and superseded entries are carried
forward into every bundle. The cache is purely a cost-and-latency
optimisation and no pipeline state lives there, so a bundle exported
with **Use cache** unticked — which omits it — is still a complete
bundle; the next run simply pays for its decisions again.

## The bundle pipeline

### What is a "bundle"?

A bundle is a ZIP archive that carries the complete pipeline state
at a given stage: the canonical record table, the harmonized
criteria, every per-stage decision report so far, the LLM response
cache, and a manifest recording SHA-256 digests of the bundle's
files, the per-stage run history, and creation timestamps. Each
plugin consumes a bundle and produces a new one with its stage's
report appended. For the two LLM stages, the history entry also
records **which engine produced that run**: the model, the resolved
endpoint, the temperature, the prompt version, the truncation limit
and the batch size. See
[Bundle format and audit trail](../README.md#bundle-format-and-audit-trail).

Two limits worth knowing. The record is per *run*, not per decision:
a bundle whose stage ran more than once carries one entry per run, and
an individual row of a report is not stamped with the engine that
decided it. And a run can serve decisions from its cache, which
outlives the run that filled it — but the cache key is itself a digest
over the model, the resolved endpoint, the temperature, the prompt
version and the rendered prompt, so a cached decision cannot be served
into a run that differs in any of them. Batch size is the one recorded
field the cache key does not cover.

### Can I resume from a saved bundle?

Yes. Save a bundle at any stage and reload it later — the plugin
list reflects which stages have already run, and you can pick up
from the next stage. This is also how a collaborator can continue
from where you left off without re-running upstream plugins.

### Can I skip a plugin?

Yes, but with caveats. The deterministic plugins (04 EH, 05 IH) are
zero-cost; skipping them just means more records reach the LLM
stages, which is more expensive but does not affect correctness.
Skipping Plugin 03 is harder because the LLM plugins need the
harmonized criteria; you can hand-author `criteria_harmonized.csv`
in the bundle's `criteria/` directory if you really want to, but
the supported workflow is to run Plugin 03 at least once.

### What does bundle integrity hashing actually catch?

It catches accidental or intentional modification of the record
table or harmonized criteria between stages. Every bundle's
manifest records SHA-256 hashes of these files at write time; the
next plugin verifies them at read time and **reports any mismatch as
a warning in the bundle-load log**. It does not refuse to load the
bundle — refusing would strand a reviewer whose only copy of the
corpus is inside it — so check the warnings panel after loading. The
intent is to surface "someone edited the CSV manually" before that
change silently propagates into downstream decisions.

Treat the digests as a corruption check rather than a tamper-proof
seal: they live in the same archive as the files they describe and
are not signed.

## LLM stages and human validation

### What is "evidence gating"?

A safeguard on the LLM stages (EL and IL). A record is excluded
(EL) or included (IL) only when the LLM's response contains both
(1) a confidence at or above the configured threshold (default
0.6) and (2) a verbatim quotation from the title, abstract, or
keywords that supports the decision. Records that fail either
condition receive `UNCERTAIN` status and are surfaced for human
review. See
[Plugin 06 EL](usage.md#plugin-06---el-exclusion-by-llm).

### Why does the LLM say `UNCERTAIN` so often?

It is doing its job. The LLM is configured to prefer flagging
uncertainty over producing a wrong confident answer. On the
demonstration corpus, the IL/IC-1 confusion matrix shows the LLM
chose `unsure` rather than commit to `yes` or `no` on 29 of the
52 IL disagreements with human raters. This is a defensible
calibration — uncertain records are routed to human review rather
than auto-decided — but worth understanding. The pattern is
analysed in
[LLM hedging on IC-1](llm-evaluation.md#llm-hedging-on-ic-1).

### What do the kappa values in the validation study tell me?

Cohen's kappa measures human-vs-LLM agreement; Fleiss' kappa
measures inter-human agreement on the overlap subset. On the
demonstration corpus, and with `gpt-4o-mini` — the one model the
study measured — the inclusion-criterion kappas land in the "fair"
Landis-Koch band (Cohen 0.28, Fleiss 0.26 on IL/IC-1).
The exclusion-criterion kappas hover near zero, but this is not a
weakness of the LLM — it is the "kappa paradox" caused by skewed
marginal distributions. Both LLM and humans agree on the exclusion
criteria at 83-87% observed rate; the kappa metric simply can't see
that agreement when one decision category dominates. Full
discussion in
[The kappa paradox on the exclusion criteria](llm-evaluation.md#the-kappa-paradox-on-the-exclusion-criteria).

These figures are a property of that model on that corpus, not of
metaScreener. If you run a different model — a local one especially —
they tell you very little about what you will get; see
[Single model](llm-evaluation.md#limitations).

### Can I run my own human validation on my own corpus?

Yes. `tools/eval_grid_generator.py` produces blind adjudication
grids from any filtered EL/IL bundle output;
`tools/eval_ingest.py` consumes the filled grids and produces the
evidence CSVs and the summary. The full pipeline is documented in
[Reproducibility](llm-evaluation.md#reproducibility).

## Reproducibility and citing

### How do I cite metaScreener?

Use the metadata in `CITATION.cff` at the repository root. The DOI
badge in the README resolves to the Zenodo deposit for the most
recently archived version. The current development branch (between
Zenodo releases) is not separately citable; cite the most recent
tagged release plus the git commit short SHA if exact provenance
matters.

### How do I reproduce a previous run?

Three things are needed: the input record set, the harmonized
criteria, and the seed (where applicable). Bundles produced by the
LLM stages also need the cache to hit zero-cost reproducibility;
without the cache the run will rebuild against live API responses
and may differ if the model has been updated between runs.

### Are the human-vs-LLM validation evidence files in the repository?

Yes. They live under `docs/data/` (the evidence CSVs and summary)
and `docs/data/grids/` (the partition manifest and the three filled
grids). Re-running `tools/eval_ingest.py` against the committed
inputs reproduces the four output files byte-for-byte; the command
line is in
[Reproducibility](llm-evaluation.md#reproducibility).

## Common errors

### `AuthenticationError: Incorrect API key`

The key in `.env` is not accepted by the endpoint. Verify it on
[platform.openai.com/api-keys](https://platform.openai.com/api-keys);
if it was generated for a different organisation, switch to the
correct one. See [Troubleshooting >
AuthenticationError](installation.md#authenticationerror-incorrect-api-key).

### `Activate.ps1 cannot be loaded because running scripts is disabled` (Windows)

PowerShell's default execution policy blocks the venv activation
script. Allow signed scripts for the current user once with
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy
RemoteSigned`. See [Troubleshooting >
Activate.ps1](installation.md#activateps1-cannot-be-loaded-because-running-scripts-is-disabled-windows).

### Tests pass but the GUI does not open

Usually a virtualenv mismatch. Confirm the venv is activated and
`which python` (or `where python` on Windows) points inside
`.venv/`. See [Troubleshooting >
GUI does not open](installation.md#tests-pass-but-the-gui-does-not-open).

### Plugin 01 produces hallucinated reference markers

Most likely the input image was not a reference list — for example,
a PRISMA flow diagram or a methodology figure. Plugin 01 is
designed for images of *numbered* or *author-year* citations and
will improvise when fed something else. See
[Plugin 01 > Common gotchas](usage.md#plugin-01---reference-markers-experimental).

## Advanced

### Can I change the LLM prompt without forking the project?

The prompts are versioned per stage under `plugins/*/prompt.py`.
Editing them locally is supported; doing so changes the prompt
version stamp, which means the cache will not match previous runs
(so a re-run will hit the live API for every record). The prompt
version is written into the bundle manifest, in the `provenance`
block of the stage's run-history entry, so an archived bundle can say
which prompt produced it.

One caveat if you edit prompts. That stamp is a hand-maintained label,
not a hash of the prompt text, so editing a prompt *without* bumping
its version leaves the manifest naming the old one. The cache is not
misled by this — its key covers the rendered prompt itself, so your
edit does invalidate it — but the manifest is only as accurate as the
label you maintain.

### Are there hooks for adding a new plugin?

Yes. The plugin loader scans `plugins/` for directories matching
`NN_name/` and expects a `plugin.py` exposing a recognised plugin
contract. The deterministic plugins (`04_eh`, `05_ih`) are good
templates for a non-LLM plugin; the LLM plugins (`06_el`, `07_il`)
show how to use the evidence-gated runner with caching. A formal
plugin-developer guide is not yet part of the docs; for now, copy
an existing plugin and adapt.

### Where do I report bugs or request features?

The repository's issue tracker on GitHub. Please include the
metaScreener version (from `pyproject.toml`), the Python version,
the operating system, and the smallest reproducible input that
exhibits the issue. For LLM-stage issues, the relevant
`*_evidence_json` from the bundle is often the most useful
attachment.
