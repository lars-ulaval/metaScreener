# LLM-screening human validation

This document describes how metaScreener's LLM-adjudicated screening
decisions were evaluated against human judgement on the demonstration
corpus, and reports the resulting agreement metrics.

The evaluation responds to Reviewer 1's compulsory item in the JORS
revision ("clearer evaluation of LLM decision quality, e.g. agreement
with human reviewers"). It validates the **LLM's per-criterion calls
within metaScreener**, not metaScreener as a whole; software-quality
attributes of the tool itself (reproducibility, plugin architecture,
audit trails) are evaluated separately by JORS.

## What is and is not validated

**In scope.** The three LLM-adjudicated criteria from the demonstration
corpus on HMD virtual reality:

- **IC-1** (inclusion, IL stage): *the paper considers immersive
  virtual reality OR a virtual simulation using a head-mounted display
  (HMD).*
- **EC-2** (exclusion, EL stage): *the paper's primary focus is spatial
  navigation in a virtual maze (no social interaction or
  collaboration).*
- **EC-3** (exclusion, EL stage): *the paper's primary focus is the
  rubber hand illusion paradigm.*

**Out of scope.** The five deterministic criteria in the same
demonstration (language detection, year threshold, document-type
filter, keyword presence) are filtered by regex/string-matching code
and never reach the LLM. Validating a regex against a human reader
would be a category error: the regex always agrees with itself. The
distinction between LLM-adjudicated and deterministic criteria is
captured by each criterion's `operator` field in the harmonized
criteria CSV; this evaluation includes exactly the rows where
`operator = llm` and the stage is IL or EL.

## Design

**Multi-annotator with stratified overlap.** Three raters (the paper's
authors) independently adjudicated the LLM-stage records. A fixed
15-record overlap per stage was rated by all three raters; the
remaining records were partitioned disjointly across raters with
load-balancing. The overlap subset supports inter-rater agreement
(Fleiss' kappa); the disjoint subsets extend the sample for
human-vs-LLM agreement (Cohen's kappa) without inflating cost.

**Blind adjudication.** Raters were not shown the LLM's per-record
decision. The grid generator deliberately strips the
`il_*`/`el_*` columns from the input filtered CSVs before writing the
Excel workbooks. Anchoring on a visible LLM call would invalidate the
agreement measurement: kappa would then reflect anchoring rather than
independent judgement. A unit test
(`test_decisions_sheets_do_not_expose_llm_columns`) guards this
invariant.

**Abstract-level evidence.** Raters worked from the title, abstract,
keywords, and (where present) venue and DOI of each record. This is
the same evidence the LLM sees during the IL and EL stages.
Title-and-abstract screening is the standard PRISMA level for the
deduplicated-records stage; metaScreener does not perform full-text
screening, so evaluating at this level is methodologically appropriate
both for the tool and for fair comparison with the LLM. Raters were
given the option to consult full text if they considered the abstract
genuinely insufficient, with a note flag in the workbook.

**Partition reproducibility.** The 15-record overlap and disjoint
assignments were sampled with a fixed seed
(`--seed 42` in
[`tools/eval_grid_generator.py`](../tools/eval_grid_generator.py))
using largest-remainder apportionment per stage outcome stratum, so
the overlap reflects the corpus's decision distribution rather than
concentrating on a single outcome class. The exact assignments are
recorded in
[`docs/data/grids/partition_manifest.csv`](data/grids/partition_manifest.csv)
and the run metadata in
[`partition_manifest.meta.txt`](data/grids/partition_manifest.meta.txt).

## Rater interface

To eliminate operator-translation friction, the dropdown options
presented to each rater quote the criterion text verbatim:

```text
YES - this is true: <criterion text>
NO - this is not true: <criterion text>
I cannot tell from the abstract alone.
```

A rater never has to translate from natural-language judgement
("is this paper about HMD VR?") to operator vocabulary
("include / exclude") nor reason about polarity ("does `include` mean
the paper survives this stage, or that the criterion's claim holds?"):
they just pick the sentence that matches their reading of the
abstract. The ingestor canonicalizes these long strings to short
codes (`yes` / `no` / `unsure`) via prefix matching.

## Mapping the LLM's evidence to canonical decisions

metaScreener's per-criterion `status` field in `*_evidence_json`
describes whether the record passes or fails the screening rule, not
whether the criterion's claim holds. These coincide for inclusion
criteria but invert for exclusion criteria:

| Polarity   | `status=MET`                 | `status=FAILED`              | `status=UNCERTAIN` |
|------------|------------------------------|------------------------------|--------------------|
| Inclusion  | passes inclusion -> `yes`    | fails inclusion -> `no`      | -> `unsure`        |
| Exclusion  | passes exclusion (not excluded) -> `no` | fails exclusion (excluded) -> `yes` | -> `unsure` |

The polarity-aware mapping ensures the human and the LLM are answering
the same question ("is the criterion's claim true of this paper?")
when their decisions are compared. The mapping is implemented in
[`tools/eval_ingest.py`](../tools/eval_ingest.py)'s
`status_to_canonical(status, polarity)` helper and is reproduced in
every `eval_summary_v1.txt` so the methodology is self-documenting.

## Metrics

For each (stage, criterion) pair the ingestor computes:

- **Cohen's kappa** between the human aggregate and the LLM. Overlap
  records contribute a single (majority-vote-of-raters, LLM) pair;
  disjoint records contribute (single-rater, LLM) pairs. The
  denominator is the union of these pairs.
- **Fleiss' kappa** across the three human raters on the overlap
  subset only. The matrix has one row per overlap record and one
  column per canonical decision; counts are the number of raters who
  chose each decision.
- **Percent observed agreement** alongside both kappas. Observed
  agreement is reported because, in the regime where one canonical
  category dominates the marginal distribution, kappa becomes
  uninformative (see the kappa-paradox discussion below) and percent
  agreement carries information that kappa loses.
- **3x3 confusion matrices** (rows: human aggregate; columns: LLM
  canonical) per (stage, criterion). The matrices localise the
  disagreement pattern in a way summary statistics cannot.

Both kappa implementations are pure-Python (no `scipy` dependency).
They are exercised against textbook reference values
(perfect-agreement, perfect-disagreement, chance-agreement = 0,
Landis-Koch's worked-example matrix) and edge cases (empty input,
single-class degeneracy, inconsistent rater counts) in
[`tests/test_eval_ingest.py`](../tests/test_eval_ingest.py).

## Results

Total LLM-screening decisions covered: **254** (85 EL/EC-2 + 85
EL/EC-3 + 84 IL/IC-1). Total human decisions collected: **344**
(3 raters x 15 overlap records per stage + disjoint records). Total
disagreements: **88**.

### EL / EC-2 (exclusion)

> *The paper's primary focus is spatial navigation in a virtual maze
> (no social interaction or collaboration).*

|                                 |                                                                                  |
|---------------------------------|----------------------------------------------------------------------------------|
| Cohen's kappa (human vs LLM)    | **-0.0466** (N = 85, P_observed = 0.835, P_expected = 0.843)                     |
| Fleiss' kappa (inter-human, N=15) | **-0.1331** (P_observed = 0.689, P_expected = 0.725)                           |

Confusion matrix (rows: human; cols: LLM):

|             | LLM yes | LLM no | LLM unsure |
|-------------|--------:|-------:|-----------:|
| Human yes   |       0 |      2 |          0 |
| Human no    |       1 |     71 |          2 |
| Human unsure|       0 |      9 |          0 |

### EL / EC-3 (exclusion)

> *The paper's primary focus is the rubber hand illusion paradigm.*

|                                 |                                                                                  |
|---------------------------------|----------------------------------------------------------------------------------|
| Cohen's kappa (human vs LLM)    | **0.1010** (N = 85, P_observed = 0.871, P_expected = 0.856)                      |
| Fleiss' kappa (inter-human, N=15) | **-0.0547** (P_observed = 0.867, P_expected = 0.874)                           |

Confusion matrix (rows: human; cols: LLM):

|             | LLM yes | LLM no | LLM unsure |
|-------------|--------:|-------:|-----------:|
| Human yes   |       0 |      1 |          2 |
| Human no    |       0 |     74 |          3 |
| Human unsure|       0 |      5 |          0 |

### IL / IC-1 (inclusion)

> *The paper considers immersive virtual reality OR a virtual
> simulation using a head-mounted display (HMD).*

|                                 |                                                                                  |
|---------------------------------|----------------------------------------------------------------------------------|
| Cohen's kappa (human vs LLM)    | **0.2775** (N = 84, P_observed = 0.560, P_expected = 0.390)                      |
| Fleiss' kappa (inter-human, N=15) | **0.2609** (P_observed = 0.600, P_expected = 0.459)                            |

Confusion matrix (rows: human; cols: LLM):

|             | LLM yes | LLM no | LLM unsure |
|-------------|--------:|-------:|-----------:|
| Human yes   |      37 |      1 |         13 |
| Human no    |       2 |      2 |         16 |
| Human unsure|       4 |      1 |          8 |

The raw long-format decisions are in
[`docs/data/eval_decisions_v1.csv`](data/eval_decisions_v1.csv); the
human + LLM joined view with agreement flags is in
[`eval_results_v1.csv`](data/eval_results_v1.csv); the 88-row
disagreement subset is in
[`eval_disagreements_v1.csv`](data/eval_disagreements_v1.csv).

## Interpretation

### The kappa paradox on the exclusion criteria

EC-2 and EC-3 show **high observed agreement (83-87%) coexisting with
near-zero kappa**. This is the well-documented "kappa paradox" or
"first paradox of kappa" (Feinstein and Cicchetti 1990; Cicchetti and
Feinstein 1990): when one decision category dominates the marginal
distribution, expected agreement by chance is already near ceiling,
and Cohen's formula `kappa = (P_o - P_e) / (1 - P_e)` divides a small
numerator by a small denominator. The metric becomes unstable and
ceases to track the underlying concordance.

In this corpus, ~95% of EL records are not about spatial navigation
in a maze and ~96% are not about the rubber hand illusion paradigm.
The LLM and the humans agree on this overwhelmingly. The agreement is
real but kappa cannot see it.

For these criteria, **observed agreement is the more informative
metric** and is reported alongside kappa for that reason. Reporting
kappa alone without observed agreement would be misleading in either
direction (under-reporting actual concordance, or
encouraging post-hoc claims about LLM weakness that the data does not
support).

### LLM hedging on IC-1

The IL/IC-1 confusion matrix shows fair Cohen's kappa (0.28) and
consistent Fleiss' kappa (0.26) - the latter places inter-human
agreement in Landis and Koch's (1977) "fair" band, which is itself
informative about the criterion's difficulty for human readers
working from abstracts alone.

The dominant disagreement pattern is the **LLM hedging to `unsure`**:

- 13 records where the human aggregate said `yes` and the LLM said
  `unsure`,
- 16 records where the human aggregate said `no` and the LLM said
  `unsure`.

Combined, 29 of the 52 IL disagreements are LLM-hedge cases. The
opposite direction (LLM confident where humans are unsure) is
rare: 4 records where the human aggregate said `unsure` and the LLM
said `yes`. This asymmetry suggests the LLM is conservative on
ambiguous abstracts and prefers `UNCERTAIN` to a wrong confident
call. The behaviour is methodologically defensible (it propagates
uncertainty to a human-review stage rather than auto-deciding under
uncertainty) but worth flagging when users interpret the LLM's
calibration.

## Limitations

The findings reported above are bounded by several conditions:

- **N is small.** 254 LLM-screening decisions across three criteria.
  Inter-human agreement is computed on N = 15 items per stage. With
  this sample size, individual confusion-matrix cells with low counts
  carry high relative uncertainty; reading the matrices, not just the
  scalar kappa, is essential.
- **Raters are the paper authors.** This is a known in-group bias.
  Truly independent multi-disciplinary adjudication (e.g., a panel
  of domain experts unconnected to metaScreener's development) would
  be a stronger validation design. The current exercise meets the
  reviewer's compulsory item but should not be over-interpreted as a
  population-level estimate of LLM-vs-human agreement.
- **Single corpus.** The HMD-VR demonstration is the only corpus on
  which agreement has been measured. Extending kappa across multiple
  corpora and criterion sets is future work.
- **Abstracts only.** Raters worked from the same evidence the LLM
  saw. This is methodologically appropriate for fair comparison and
  for the title-and-abstract PRISMA stage, but it does not validate
  what either humans or LLMs would conclude at the full-text stage.
- **No temperature sweep.** Decisions are taken at the LLM's default
  temperature for the bundle. Run-stability under repeated sampling
  at non-zero temperature has not been measured.
- **No subgroup analysis.** Agreement metrics are not broken down by
  record characteristics (year, venue, language); a longer corpus
  would justify such an analysis.
- **Screening quality is bounded by whether the model discriminates,
  and the pipeline cannot tell when it stops.** Agreement figures
  describe runs in which the model produced varied, per-record
  judgements. That is not guaranteed. In one archived run of the same
  776-record corpus (2026-05-07, `gpt-4o-mini`), all 170 EL calls
  returned the same decision (`not_meet`), the same confidence (0.9
  exactly), and only three distinct evidence spans, one of which
  repeated identically across an entire 85-record criterion sweep. The
  decisions were defensible for that corpus — those records genuinely
  are not about spatial navigation or the rubber-hand illusion — but a
  constant answer is not per-record reasoning, and nothing in the
  pipeline distinguishes the two. There is no check on the variance of
  a run's decisions, its confidences, or its spans.

  The evidence gate bounds the harm without removing it. A verdict
  whose quote cannot be found in the text the model was shown is
  refused (`plugins/06_el/screen.py:603`), so a degenerate run cannot
  silently exclude records; in the archived run 38 such verdicts were
  forced to `PASS_FLAGGED` and none affected an exclusion. What the
  gate cannot do is prevent the opposite failure — a uniform, confident
  pass that examines nothing and sends the whole corpus forward
  unscreened. Reviewers should treat per-run decision and confidence
  variance as something to inspect rather than assume, particularly
  when a stage excludes nothing.

  This is one observed run, on one corpus, with one model. It is
  reported because it happened, not as an estimate of how often
  degenerate output occurs; that has not been measured.

## Reproducibility

Every artefact in this evaluation is regenerable from inputs already
in the repository:

1. Empty grids and partition manifest:

   ```text
   python tools/eval_grid_generator.py \
       --el-filtered tests/golden/el_filtered_v3.1.0.csv \
       --il-filtered tests/golden/il_filtered_v3.1.0.csv \
       --criteria    tests/golden/criteria_harmonized_v3.1.0.csv \
       --raters      AReyes JKiss JVoisin \
       --output-dir  docs/data/grids \
       --overlap     15 --seed 42
   ```

2. Filled grids: the three workbooks in
   [`docs/data/grids/filled/`](data/grids/filled/) are committed as the
   raw rater inputs.

3. Evidence files: re-running the ingestor on the committed grids
   reproduces the four output files byte-for-byte:

   ```text
   python tools/eval_ingest.py \
       --manifest         docs/data/grids/partition_manifest.csv \
       --criteria         tests/golden/criteria_harmonized_v3.1.0.csv \
       --filled-grids-dir docs/data/grids/filled \
       --el-filtered      tests/golden/el_filtered_v3.1.0.csv \
       --il-filtered      tests/golden/il_filtered_v3.1.0.csv \
       --output-dir       docs/data
   ```

The ingestor performs no LLM calls; all LLM evidence is read from the
`*_evidence_json` columns already present in the bundle-stage filtered
CSVs, which were themselves captured in the published demonstration
run.

## References

- Cicchetti, D. V., and Feinstein, A. R. (1990). High agreement but
  low kappa: II. Resolving the paradoxes. *Journal of Clinical
  Epidemiology*, 43(6), 551-558.
- Feinstein, A. R., and Cicchetti, D. V. (1990). High agreement but
  low kappa: I. The problems of two paradoxes. *Journal of Clinical
  Epidemiology*, 43(6), 543-549.
- Landis, J. R., and Koch, G. G. (1977). The measurement of observer
  agreement for categorical data. *Biometrics*, 33(1), 159-174.
