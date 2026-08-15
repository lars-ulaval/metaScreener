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

## Model under evaluation

Every LLM decision adjudicated below was produced by **`gpt-4o-mini`**,
in a single capture committed at `4fbe8fd` (2026-05-02), with a
4000-character field truncation limit and a batch size of 5.

That attribution needs a caveat, and it is why this section exists: the
model is not recorded by the product. It is a constant asserted by the
capture harness — `MODEL` in
[`tools/capture_el_il_goldens.py`](../tools/capture_el_il_goldens.py),
written into the `_invocation` envelope of the two cache fixtures — so
it is a statement about how the capture was configured, not a value
recovered from the run. Three further properties of that run were not
recorded at all, and are given here as inference rather than
observation:

| | Value | Basis |
|---|---|---|
| Model | `gpt-4o-mini` | asserted by the capture harness |
| Truncation limit | 4000 characters | asserted by the capture harness |
| Batch size | 5 | asserted by the capture harness |
| Prompt version | `EL_v1_jsonlist` / `IL_v1_jsonlist` | read from the source at the capture commit, where it was already a cache-key member |
| Endpoint | the OpenAI default | *inferred* — none was recorded, and the capture set none |
| Temperature | 0.0 | *inferred* — the capture set none, so the run took the code default |

The prompt-version stamp needs one qualification. It is a hand-maintained
label rather than a hash of the prompt text, and both labels are still in
use today — so the stamp establishes which prompt *version* the study
ran, but not that today's prompt text is byte-identical to the one it
ran. The prompt-building code has since been extracted to its own module
and the cache key rewritten to hash the rendered prompt rather than an
enumerated list of parameters.

The frozen study input carries the same statement in
[`study_input.meta.txt`](data/study_input/study_input.meta.txt).

None of this is true of a run made with the current version. A bundle
exported today records the model, the resolved endpoint, the
temperature, the prompt version, the truncation limit and the batch size
in its manifest, once per stage run, so a later evaluation will not have
to reconstruct its provenance from a test fixture. This study predates
that and cannot benefit from it retroactively.

**The figures below therefore describe one model.** They are not a
property of metaScreener and should not be read as one — see *Single
model* under [Limitations](#limitations).

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

**Study input.** The screening output this study adjudicates is frozen
under [`docs/data/study_input/`](data/study_input/): the two filtered
CSVs that carry the LLM's per-record decisions and evidence quotes, the
harmonised criteria table, and the post-IH record set. Every command in
§Reproducibility reads from there.

These four files began as copies of the byte-identity regression
fixtures under `tests/golden/`, and are deliberately no longer the same
artefact. A regression fixture is *meant* to be re-captured when the
behaviour it guards legitimately changes; a cited dataset must never
change. While one pair of files served both roles, every change to the
screening engine silently rewrote the input of this analysis — and this
document would have gone on claiming byte-for-byte reproduction while
producing different numbers. The frozen copies are pinned by
[`SHA256SUMS`](data/study_input/SHA256SUMS), described in
[`study_input.meta.txt`](data/study_input/study_input.meta.txt), and
checked on every test run, which also re-runs the §Reproducibility
command against them and compares its output with the committed
`docs/data/eval_*` files byte-for-byte. The fixtures under
`tests/golden/` are now free to move without touching this study.

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

Every figure in this section describes `gpt-4o-mini` on the HMD-VR
demonstration corpus; see [Model under
evaluation](#model-under-evaluation).

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
said `yes`. This asymmetry suggests **this model** is conservative on
ambiguous abstracts and prefers `UNCERTAIN` to a wrong confident
call. The behaviour is methodologically defensible (it propagates
uncertainty to a human-review stage rather than auto-deciding under
uncertainty) but worth flagging when users interpret the LLM's
calibration.

This is the conclusion in the document that transfers least well, and
it is worth being explicit about why. It is a claim about `gpt-4o-mini`,
not about LLM screening: hedging is the characteristic failure of a
large, well-aligned model, and **over-confidence** rather than hedging is
the characteristic failure of a small one. A reader running a local
quantised model should expect this asymmetry to weaken, vanish, or
invert — and the inverse is the harmful direction, because a confident
wrong call is acted on where a hedge is routed to a human.

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
- **Single model.** Every decision was produced by one model,
  `gpt-4o-mini`, in one capture — see [Model under
  evaluation](#model-under-evaluation). The agreement figures are a
  property of that model on this corpus, not a property of
  metaScreener. A different model may agree with human raters more or
  less, and may fail in ways this corpus cannot show; the gap is widest
  for the smaller local models the tool supports and the README
  invites, whose characteristic weaknesses — format discipline,
  identifier fidelity, confidence calibration — are precisely the ones
  these metrics do not probe. Nothing here transfers automatically to
  whatever model the tool ships as its default. If that default
  changes, these figures continue to describe `gpt-4o-mini` and not the
  model that ships.
- **Abstracts only.** Raters worked from the same evidence the LLM
  saw. This is methodologically appropriate for fair comparison and
  for the title-and-abstract PRISMA stage, but it does not validate
  what either humans or LLMs would conclude at the full-text stage.
- **No temperature sweep.** Decisions were taken at temperature 0.0 —
  the code default at the capture commit, which the capture harness did
  not override (see [Model under
  evaluation](#model-under-evaluation)). No bundle records or defaults a
  temperature. Run-stability under repeated sampling at non-zero
  temperature has not been measured.
- **No subgroup analysis.** Agreement metrics are not broken down by
  record characteristics (year, venue, language); a longer corpus
  would justify such an analysis.
- **Screening quality is bounded by whether the model discriminates,
  and the pipeline cannot tell when it stops.** Agreement figures
  describe runs in which the model produced varied, per-record
  judgements. That is a weaker guarantee than it sounds, and this
  study's own run is the place to see why. Its IL half is genuinely
  varied — 48 `meet` against 36 `not_meet`. Its EL half is not: 169 of
  170 decisions are `not_meet`, and 141 of them carry confidence 0.900
  exactly. The kappa-paradox discussion above attributes the skewed
  marginals to the corpus, and that is right; what it does not say is
  that the model's output is nearly as concentrated as the corpus, and
  that from outside the artefact the two are indistinguishable. This
  strengthens the case for reading observed agreement alongside kappa
  rather than retracting either — but the figures reported above should
  not be read as describing a run of highly differentiated judgements,
  because on EL they do not.

  Full collapse is a different matter, and it does happen. In one
  archived run of the same 776-record corpus (2026-05-07,
  `gpt-4o-mini` — the same model as this study, a different run), all
  170 EL calls
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
  refused (`plugins/06_el/screen.py`, `run_el_screen`); in the archived
  run 38 such verdicts were forced to `PASS_FLAGGED` and none affected
  an exclusion.

  **This passage previously continued "so a degenerate run cannot
  silently exclude records", and wave 12 measured that claim false.**
  Over this repository's own 85-record corpus and criteria, local models
  produced 40, 43 and 4 exclusions across three runs where the audited
  baseline produced 1 — and every one of them *passed* the gate, with a
  verbatim quote and a confidence above threshold. The gate verifies that a quote
  is real; it cannot verify that a quote is relevant, and nothing short
  of another model could. Nor was it a format failure: `llama3.2`
  answered 170 of 170 in well-formed JSON with zero *decision*-vocabulary
  rejections. It asserted matches that were not there. A run can
  therefore look almost entirely healthy by this pipeline's counters —
  the two runs did reject 1 and 3 *field* values — and still be removing
  correct studies. The measurement, its
  distributions and its limits are reported in full under *Local models
  on this corpus: a direct measurement* below, and are not restated
  here.

  What follows is that a local model may annotate but may not exclude,
  which is what flag-only mode enforces (F-145): on a local or custom
  provider an excluding verdict is recorded as `EXCLUSION_SUPPRESSED`
  and the record survives to human review. The gate remains useful — it
  is what makes a *malformed* verdict harmless — but it is not what
  makes a *confident and wrong* one harmless, and only the second of
  those was ever the interesting case.

  The same measurement produced a second finding that bears on this
  bullet directly, and on the paragraph above it. Two runs of the same
  model, identical in every field the provenance block records, excluded
  **40** and **43** records — so a run's decision set is not stable even
  at `temperature 0.0`. The variance this bullet asks reviewers to
  inspect is therefore not only a property of the corpus and the model;
  part of it is run-to-run noise, and inspecting a single run cannot
  separate the two.

  The other failure the gate cannot prevent is unchanged: a uniform,
  confident pass that examines nothing and sends the whole corpus
  forward unscreened. Reviewers should treat per-run decision and
  confidence variance as something to inspect rather than assume,
  particularly when a stage excludes nothing.

  Two further failure modes are **not** instances of this one, and
  watching for this one will not catch them. A **JSON-shape failure** —
  a response that does not parse, or that omits the expected fields —
  also produces zero variance, so it presents with the same outward
  signature as a model that has stopped discriminating while having an
  unrelated cause and an unrelated remedy. The advice in the preceding
  paragraph misfires on it specifically: a reviewer inspecting decision
  and confidence variance would diagnose a lazy model rather than a
  broken response contract. **Identifier drift** — a model that
  misreports which record it is answering about — is invisible on both
  sides, an unrecognised identifier being dropped and a missing one
  back-filled, in each case with no counter and no log line; it is also
  the trigger condition for the substitution defect described in the
  next bullet. Neither mode occurred in the archived 2026-05-07 run
  described above, and the frequency of neither has been measured. No
  such claim is made for the study run: the next bullet reports 70
  entries on which drift of the substituting kind cannot be decided
  either way. Both modes are more likely on smaller models than on the
  one this study used.

  This is one observed run, on one corpus, with one model. It is
  reported because it happened, not as an estimate of how often
  degenerate output occurs; that has not been measured.
- **A defect in the screening code could, in principle, have fabricated
  an exclusion — and this study's own evidence has been audited for
  it.** Until it was fixed, the LLM stages could accept an answer
  naming a record the call had not carried, and would then validate the
  quote against *that* record's own text, so the result passed every
  check (item 1 of the release notes in
  [`CHANGELOG.md`](../CHANGELOG.md)). An exclusion fabricated this way
  is well-formed and fully evidenced, and cannot be found by
  inspection.

  The 254 cache entries behind this study were therefore checked
  directly. The check runs in one direction only: if the quote filed
  against a record occurs nowhere in the corpus except that record's
  own text, no substitution could have produced it. It clears **175**
  entries outright and leaves **70 undecidable** — short, generic
  keyword fragments such as "Computer science" that recur across a
  bibliographic corpus, which is exactly the population in which a
  substitution could have survived the evidence gate at all.

  The remaining **9** are the entries whose quote failed validation, and
  they need stating carefully, because the direction is not the obvious
  one. A failed quote is not in itself proof that no substitution
  occurred — a borrowed quote checked against a record that cannot
  supply it is precisely what a caught substitution looks like. So the
  nine were examined individually rather than assumed:

  - **six** quote a string that appears nowhere in the corpus, in any
    field of any record, even ignoring case — the model invented the
    text rather than borrowing it;
  - **two** are record `A345`, on `EC-2` and on `IC-1`, quoting
    "Augmented reality". That string is supplied by `A345`'s **own
    title** — *"Brain–Computer Interface Integrated With Augmented
    Reality for Human–Robot Interaction"* — and differs from it only in
    the case of one letter. The parsimonious reading is a model quoting
    its own record's title, lower-casing a word and labelling the field
    `keywords`; not a borrowed quote;
  - **one** is record `A247`, whose quote its own record does contain
    exactly, so its gate failure concerns where the validator looked
    rather than whether the text exists.

  **None of the nine exhibits the positive signature of a
  substitution** — a record that cannot supply its own quote while
  another can. And what follows from all nine collectively is narrower
  and firmer than any claim about substitution: **they failed the
  evidence gate, so whatever produced them, none of them removed a
  record.**

  Narrowed to what changes the funnel: this study contains five
  verdicts that actually removed a record. **Four are provably not
  products of the defect. One — record `A452` on `IC-1`, quoting
  "Computer science" — is undecidable.**

  Both halves of that should be read carefully. The undecidable entries
  are not evidence that anything went wrong: every quote that *passed*
  the evidence gate can be supplied by the record it is filed against,
  which is what passing the gate means, and none of them exhibits the
  positive signature. Nor are they evidence that nothing did. The
  residue is structural rather than a
  matter of effort — nothing in the artefacts ties a verdict to the
  call that produced it, so no further analysis of the committed files
  can resolve it, and the one thing that would, a per-response record
  of which call answered for which record, did not exist when this
  study was captured and does not exist now. The provenance a bundle
  records from this version onward is per *run* — which engine
  produced a stage's decisions — not per response, so it does not
  close this gap either.

## Local models on this corpus: a direct measurement

*Added 2026-08-11 (wave 12). This section reports a measurement taken
after the validation study above and describes a different question. It
does not revise any figure, kappa or matrix reported earlier; those
concern `gpt-4o-mini` against human raters, and nothing here touches
them.*

The question is narrower and more practical than the study's: **what
happens when the same pipeline is pointed at a model running on the
user's own machine?** metaScreener has supported an OpenAI-compatible
local endpoint since v3.2, and until now nothing had been measured about
what a local model does with these criteria.

### What was measured

One corpus, three runs of the EL stage, all reaching that stage through
identical deterministic screening:

    776 records → EH excludes 125 → 651 → IH excludes 566 → 85

That funnel reproduced **exactly** in every run, record for record — see
*Reproducibility of the demonstration funnel* below, which reports the
same identity for the archived study runs, and whose provenance note
(wave 15a, F-168) applies to this funnel equally: it is the shipped
pre-13d chain, reproducible and not what the criteria prose describes.

| | model | prompt | exclusions | notes |
|---|---|---|---|---|
| baseline | `gpt-4o-mini` | `EL_v1_jsonlist` | **1** | the committed golden capture; audited by the author, correct |
| run A | `llama3.2:latest` | `EL_v1_jsonlist` | **40** | 39 of them kept by the audited baseline |
| run B | `llama3.2:latest` | `EL_v1_jsonlist` | **43** | 42 of them kept by the audited baseline |
| run C | `qwen2.5:7b` | `EL_v1_jsonlist` | **4** | all four kept by the baseline; all four individually confirmed wrong by the author |

**On "wrong", and what was actually checked.** The four `qwen2.5`
exclusions were examined individually by the author and are wrong. The
40 and 43 `llama3.2` exclusions were **not** individually audited, and
no audit of them exists in this repository; describing them as
"unjustified" would be repeating an assertion as a finding, which is the
error this section exists to avoid. What the artefacts *do* support is
stated instead, and it is nearly as strong: **39 of run A's 40 and 42 of
run B's 43 excluded records were kept by the audited baseline.** The
single overlap in each case is `A499` — the one exclusion the author
examined and found correct. A stage that removes half the corpus where an
audited run removed one record is not making the same distinction,
whatever the verdict on each individual paper.

Runs A, B and C were taken at `temperature 0.0`, `trunc_chars 1500`,
`batch_size 5`, against `http://localhost:11434/v1`, and each is fully
attributed by the provenance block wave 10 added. **The baseline was
captured at `trunc_chars 4000`** (`tools/capture_el_il_goldens.py`), and
that difference is treated as a limitation below rather than glossed.

Every figure in this section was re-derived from the run artefacts
themselves rather than transcribed from a report; where a figure and an
artefact disagreed, the artefact was taken as correct.

**Where this evidence is, and how to check a figure.** The artefacts are
committed under **`docs/data/wave12_local_runs/`** — for each run, the
bundle manifest (carrying its six-field provenance block and its LLM
counters), the 85 EL records with their per-criterion evidence, and the
raw per-judgment model answers. Every number in this section is
recomputed from those bytes on each test run by
`tests/test_wave12_measurement_freeze.py`, which fails if the prose and
the artefacts disagree; the artefacts are the source of truth and this
text has to match them. Integrity is held twice over — by
`docs/data/wave12_local_runs/SHA256SUMS`, and by the `sha256` block
inside each run's own manifest, which also records digests for the
bundle members that were *not* committed, so an original bundle can
still be matched member by member. `wave12_local_runs.meta.txt` explains
what was omitted and why.

Two of the inputs were already in the repository and are asserted rather
than duplicated: the 85 records the EL stage screened are byte-identical
in all three runs and to `docs/data/study_input/el_input_v3.1.0.csv`, and
run A's criteria table is byte-identical to
`docs/data/study_input/criteria_harmonized_v3.1.0.csv`. Runs B and C ran
against a criteria table differing in one row — **IC-5, an `IL`
criterion, which the EL stage does not read**; `EC-2` and `EC-3` are
identical across all three runs, field by field, and the test asserts it.
That difference is called out here rather than buried because it is a
concrete instance of the point *The same model, the same input, a
different answer* makes below: the provenance block records six fields,
the criteria table is not one of them, and something did differ between
runs A and B that no artefact of either run would have reported.

### The distributions behind the counts

Per run, over the 170 record–criterion judgments (85 records × EC-2,
EC-3):

| | `meet` | `not_meet` | `uncertain` | quote valid | answered |
|---|---|---|---|---|---|
| run A `llama3.2:latest` | 82 | 36 | 52 | 81/170 (47.6%) | 170/170 |
| run B `llama3.2:latest` | 81 | 35 | 54 | 80/170 (47.1%) | 170/170 |
| run C `qwen2.5:7b` | 8 | 129 | 33 | 117/170 (68.8%) | 137/170 |

`meet` is the excluding verdict here: EC-2 and EC-3 are exclusion
criteria, so a record "meets" them by being the kind of study the review
excludes.

**Two cautions about run C's row, because its denominators do not mean
what runs A and B's mean.** The 33 judgments `qwen2.5` did not answer are
back-filled by the pipeline as `uncertain` with `valid_quote: false`, and
they are absent from the committed cache entirely (137 lines, not 170).
So (1) its `uncertain` column merges *the model said uncertain* with *the
model said nothing* — two states the engine keeps apart everywhere else;
and (2) `117/170` divides a numerator counted over 137 answered
judgments by 170. Among judgments the model actually answered the rate is
**117/137 = 85.4%**, which is the figure comparable to runs A and B's
47.6% and 47.1% — those two answered 170/170, so their denominators are
real. Run C's 68.8% is reported as-is for consistency with the manifest
counters and should not be read as a better quote-validity rate.

Two features are worth naming. The `llama3.2` runs produced **zero**
records with a clean pass — every one of the 85 was either excluded or
flagged — where the baseline produced 77 clean passes out of 85. And
`qwen2.5` left 33 judgments unanswered, which the pipeline correctly
routed to human review; that is the fail-safe path working exactly as
designed, and it is not the failure this section is about.

### The four `qwen2.5` exclusions

Named individually because the pattern matters more than the count. All
four were excluded against **EC-2**, which asks whether the paper's
primary focus is spatial navigation in a virtual maze:

| record | subject | confidence | quoted field | quote valid |
|---|---|---|---|---|
| A286 | brain–computer interfaces for augmented reality | 0.7 | abstract | yes |
| A301 | review of EEG-based BCI paradigms | 0.9 | abstract | yes |
| A310 | TRAVEE multimodal neuromotor rehabilitation | 0.9 | abstract | yes |
| A423 | *Teens, Social Media & Technology 2018* | **1.0** | title | yes |

None is a maze-navigation study. A423 is the clearest case and the one
to look at closely: a Pew Research Center report on adolescent social
media use, excluded from a virtual-reality navigation review at
**confidence 1.0**, with the quote supplied being the report's own title.

The gate was satisfied. The title is verbatim, present in the field the
model named, and every check the software performs returned true.

### The central finding

**Every false exclusion in every run passed the evidence gate.**

That gate is metaScreener's principal defence on the LLM path: a verdict
is acted on only when the model supplies a confidence at or above
threshold *and* a quotation that can be found, character for character,
in the text the model was shown. It is a good defence and it is doing its
job. But its job is narrower than it looks:

> A verbatim-quote gate defends against **fabrication**. It is silent
> about **irrelevance**.

Verifying that a span is present in the source is a string operation.
Verifying that the span *supports the verdict* is an inference, and
nothing short of a second model could perform it. A423 makes the gap
concrete: quoting a paper's title proves the paper exists and says
nothing whatever about whether its primary focus is a virtual maze.

This generalises beyond metaScreener, and is the part of this section
most likely to be useful to someone building a different tool.
Quote-grounding, citation-checking and span-extraction gates are common
answers to LLM unreliability, and they all share this boundary: they
convert *unverifiable assertions* into *verifiable citations*, which
eliminates one failure mode entirely and leaves a second untouched. A
system that treats a passing quote check as evidence that a verdict is
sound has mistaken the first for the second.

The failure is **not** a formatting failure, which is worth stating
because that is the comfortable explanation. Wave 8's counters record
`llama3.2` answering **170 of 170** judgments in well-formed JSON with
**zero** rejected *decisions*, zero failed calls and zero failed
batches. The model was not confused about what to emit. It asserted
matches that were not there.

*Not quite zero, and the exception is worth naming rather than
smoothing over.* The pipeline keeps two rejection counters, and only one
of them is zero. `decisions_rejected` is 0 in both runs; `fields_rejected`
is **1 in run A and 3 in run B** — values outside `{title, abstract,
keywords}`, silently replaced with `abstract`. An earlier draft of this
section said "zero vocabulary rejections", which the run-A/run-B
comparison below then contradicted with its own `1 vs 3`. The claim that
survives is the one that matters for the argument: the model emitted
well-formed JSON and a legal verdict on every one of the 170 judgments,
so the wrong exclusions are not a parsing failure.

### The same model, the same input, a different answer

**This is the more generalisable result of the two**, and it was not
what the runs were taken to find.

Runs A and B are the same model on the same input. Every field the
provenance block records is identical:

| field | run A | run B |
|---|---|---|
| `model` | `llama3.2:latest` | `llama3.2:latest` |
| `endpoint` | `http://localhost:11434/v1` | `http://localhost:11434/v1` |
| `temperature` | `0.0` | `0.0` |
| `prompt_version` | `EL_v1_jsonlist` | `EL_v1_jsonlist` |
| `trunc_chars` | `1500` | `1500` |
| `batch_size` | `5` | `5` |

Of everything either run records about itself, they differ only in when
they ran — 21:47 and 22:10 UTC on the same machine, twenty-three minutes
apart. (They also ran against criteria tables differing in one `IL` row,
which the EL stage does not read and which neither run's provenance
block would have told you about; see *Where this evidence is* above. The
85 records screened and both `EL` criteria are byte-identical.)

They excluded **40** and **43** records respectively:

- the 40 are a **strict subset** of the 43; nothing excluded in A was
  kept in B;
- three records — **A312, A322, A570** — moved from `PASS_FLAGGED` to
  `OUT`;
- **8 of 170 judgments (4.7%) changed decision** between the runs;
- even the internal counters differ: `fields_rejected` was 1 in A and 3
  in B.

**The decision field is the least of it.** Counting only the verdicts
understates how much moved between the two runs, and the understatement
is large. Comparing every judgment on the evidence the model actually
supplied — decision, confidence, cited field, quoted span, and the
resulting gate status — **37 of 170 judgments (21.8%) differ in at least
one of them**: confidence on 23, the quotation on 22, the field cited on
13. Roughly one judgment in five is not the same judgment twice, against
the one in twenty-one you get by looking only at the verdict.

**A570 is why that distinction is not pedantry.** Of the three records
that moved from flagged to excluded, it is the one whose *decisions did
not change at all*: `meet` on EC-2 in both runs, at confidence 1.0 and
0.95. What changed is that in run A the model cited the abstract and
supplied **no quotation**, so the evidence gate had nothing to verify and
the record was flagged for a human; in run B it cited the keywords and
supplied `"Virtual reality"`, which is present verbatim, so the gate
passed and the record was removed from the review. Same model, same
input, same verdict, same confidence to within 0.05 — and the difference
between *a human reads this* and *this is gone* was which words the model
chose to quote.

This sharpens what the gate is and is not. It is the mechanism that
converts a verdict into an action, so **whatever varies in the quotation
varies in the outcome**, entirely independently of whether the model
changed its mind. A reader comparing two runs on their verdicts alone
would find A570 identical in both and have no way to explain why one run
excluded it.

**Practitioners routinely treat `temperature = 0` as a reproducibility
guarantee. On this server and this hardware, it is not one.** Greedy
decoding is deterministic given identical logits, but the logits are not
identical across runs: batching, kernel selection, memory layout and
floating-point reduction order all vary, and a near-tie between two
tokens resolves differently. metaScreener's own code has said as much
since wave 7 — `llm_client.py`'s docstring records that "strict
determinism is not guaranteed even at 0.0 due to hardware-level
floating-point non-determinism in model inference" — but that was a
statement of principle. This is a measurement of it, at fixed settings,
with the size of the effect attached.

**What this does not undermine.** The deterministic half of the pipeline
reproduced exactly across all three runs and across the archived study
runs: 776 → 125 → 651 → 566 → 85, the same records every time. The
variability is confined entirely to the LLM stages. That is consistent
with what this document's *Reproducibility of the demonstration funnel*
section has said since wave 6 — the deterministic share reproduces, the
LLM share does not — and it is the first measurement of the LLM share's
variability under *fixed* settings rather than across executions that
also differed in configuration.

**What this means for the replay goldens.** The committed EL/IL caches
pin **recorded** answers, not **reproducible** ones. Replaying a golden
proves that the pipeline turns a given set of model answers into a given
set of outputs, byte for byte — which is a real and useful guarantee,
and is what those tests are for. It does **not** prove that a fresh run
against the same model would produce those answers again. No claim to
the contrary is made anywhere in this repository, and both
`docs/llm-evaluation.md` and `docs/internal/diagnostic/02_quality.md`
§6.5 already draw the distinction correctly; this measurement supplies
the evidence they were reasoning about in the abstract.

**What this means for flag-only.** It is a stronger argument than
accuracy, and it does not depend on adjudicating a single verdict:

> The same model, on the same input, in the same recorded configuration,
> excludes a different set of papers each time it is run.

A component that behaves that way should not be permitted to remove a
paper from a systematic review, whatever its accuracy. Removal is the
one irreversible act in the pipeline — a flagged record is read by a
human, an excluded record is gone — and irreversible acts should not be
delegated to a process that will not repeat itself.

### What is not established

This section reports what was observed. It does not support the
following, and several of these are the questions a reader will most want
answered:

- **The hosted baseline is n = 1.** One correct exclusion is a thin basis
  for comparison, and nothing here demonstrates that `gpt-4o-mini` is
  *generally* more accurate on this task. It demonstrates that on this
  corpus it excluded one record and was right, while the local models
  excluded 40–43 and 4, of which the four examined individually were
  wrong, and 39 of run A's 40, 42 of run B's 43 and all four of run C's
  were records this baseline kept.
- **The comparison is not like-for-like.** The baseline was captured at
  `trunc_chars = 4000` and the local runs at `1500`. Measured on this
  corpus: no abstract exceeds 4000 characters, so the baseline saw every
  abstract in full, while **28 of 85 (33%)** were truncated for the local
  runs, losing a median of 364 characters each. Titles and keywords are
  unaffected. This does not explain a confident wrong exclusion — a model
  shown less text has less evidence, not more — but the runs are not a
  controlled comparison and should not be described as one.
- **Quantisation is not recorded.** The provenance block has six fields
  and none of them is quantisation, so these runs **cannot be fully
  specified from their own artefacts**. Ollama serves quantised weights
  by default, so the local runs are near-certainly not the models at full
  precision, but which quantisation was used is not recoverable from the
  bundles. That is a gap in the provenance block, not a detail omitted
  from this write-up.
- **`llama3.2:latest` is a mutable tag.** It names whatever weights that
  tag pointed at on 2026-08-11. It may point elsewhere later, which makes
  it a weak value for a field whose purpose is identifying what produced
  a result (F-154).
- **The context window was measured and is not a factor.** metaScreener
  never sets `num_ctx`, so these runs inherited the server's default of
  4096 tokens, and an OpenAI-compatible server truncates rather than
  errors when a prompt exceeds its window. That raised the possibility
  that the models were answering about records they had been only partly
  shown. **It did not happen.** Rendering the real prompt for this corpus
  at `batch_size 5` gives a worst case of 2,170–3,256 tokens depending on
  the tokenizer assumption, and a worst observed reply of **327–491**, for
  a worst total of **2,497–3,747** against 4,096. The prompts fit, with
  more headroom than first published. The explanation below is therefore
  not confounded by truncation. (`tools/measure_prompt_size.py` re-derives
  the *prompt* half and says so on every run; the *reply* half is measured
  from the run evidence, which since F-159 is committed under
  `docs/data/wave12_local_runs/` — the worst reply is 1,471 characters,
  run A, EC-3, the seventh batch of five. An earlier draft published
  509–764 for the reply and 2,679–4,020 for the total; those were not
  re-derivable from anything and are overstatements, corrected here from
  the frozen artefacts. At `batch_size 10` the same corpus *does*
  overflow, which is F-154's open half.)
- **EC-2's own wording has not been tested.** Its parenthetical — *"(no
  social interaction or collaboration)"* — is plausibly readable as an
  independent second condition rather than as a gloss on the primary
  clause, and all four `qwen2.5` exclusions are consistent with a model
  that read it that way: BCI, rehabilitation and social-media papers are
  all things one might exclude under a standalone "no social interaction"
  test. **This is a candidate explanation and nothing here demonstrates
  it.** The criteria in this corpus were written for human readers and
  have never been tested for machine-readability. Whether criterion
  phrasing accounts for a material share of local-model error is an open
  question and a good one.
- **No claim about local models in general.** Two models, one corpus, one
  criteria set, one stage, one machine. `llama3.2` and `qwen2.5` at these
  sizes are small models; nothing here speaks to larger local models,
  other quantisations, other prompting strategies, or other review
  domains.

### Why flag-only is the default

metaScreener therefore ships **flag-only** for local and custom
providers: an LLM verdict may flag a record for human review, and may not
remove it. Exclusion remains permitted by default for OpenAI, the
configuration the validation study above measured, and the setting is
user-changeable for any provider from the provider dialog, where this
measurement is restated.

*Updated at wave 15e:* the rule above gained a second, provider-independent
companion. A removal justified by **absence** — `not_meet` on an inclusion
criterion, IL's own removing verdict — is **never** applied automatically,
for any provider, at any confidence, whatever the exclusion setting: no
quotation can prove an absence, so the evidence gate has nothing it could
check for that verdict class. Permitting exclusion in the provider dialog
reaches presence-justified removals only. In practice IL flags and ranks;
it does not remove.

**The argument does not depend on resolving anything in the previous
section.** Suppose the criterion wording is at fault; suppose
quantisation is; suppose it is model size. The observation stands
regardless: *a default configuration, reachable by following this
project's own documentation, removed roughly half the corpus at a stage
where an audited run removed one record, passed every check the software
performs while doing it, and removed a different half on each run.* Whatever the cause, that is not a component that
should be permitted to delete studies from a review unattended.

The cost is small on this pipeline, and it is worth stating precisely
rather than reassuringly — which means not mixing two runs inside one
sentence, as an earlier draft of this paragraph did.

**In the committed goldens**, the funnel removes 692 records: EH 125 and
IH 566 deterministically, EL 1 by LLM verdict, and IL none — since wave
15e an absence-justified removal is never auto-acted, so IL's four
confident `not_meet` verdicts route to review as `EXCLUSION_SUPPRESSED`
instead of removing. (They did remove, until 15e: the goldens carried
them as `OUT`, and moved with the rule — before 15e this paragraph read
"696 removed, EL 1 and IL 4 by LLM verdict, 99.3%".) Flag-only changes
the reviewer's workload from 84 records to 85 — **one more abstract** —
and the deterministic share is 691/692 = **99.9%**.

**In the manuscript run**, the funnel removes 703, of which the
deterministic stages account for the same 691 and the LLM stages for
**12**; there the cost would be twelve more abstracts and the
deterministic share is 691/703 = **98.3%**. Both ratios are published in
this repository and they are not the same measurement: 99.9% is the
goldens under today's rules, 98.3% is the manuscript run under the rules
it was produced with. An earlier draft set the scale with 703 and
supplied the numerator from the goldens, leaving a reader unable to
reconcile the two figures — kept named here because mixing the two
denominators is exactly how such numbers go wrong.

Either way the trade is the same in kind: a handful of abstracts, in
exchange for removing the false-exclusion class entirely while keeping
everything the model is good at — the reasons, the quotes, and the
ordering of what to read first.

A user who has validated a local model on their own corpus can turn
exclusion on. The default is chosen for the user who has not.

## Reproducibility of the demonstration funnel

> **Provenance note (2026-08-14, wave 15a — register row F-168).** The funnel
> behind these figures was produced under harmonisation rules retired at wave
> 13d: EC-4 was rendered against `doc_type` where its prose names the venue,
> and EC-1 as `equals French` where its prose names French *or Spanish*. The
> figures reproduce exactly and are kept as the record of the shipped
> demonstration; a table harmonised from the same criteria prose today yields
> `776 → 16 → 760 → 613 → 147` before the LLM stages, and the 85 records here
> are a measured strict subset of those 147. The full note is at
> `docs/data/study_input/study_input.meta.txt`; the current-rules evidence is
> committed under `docs/data/wave14c_batch_runs/` and
> `docs/data/wave14d_invariance_runs/`.

The README reports that the demonstration corpus of 776 records reduced
to **73** requiring full human review (a 90.6% reduction, with
deterministic pre-filtering accounting for 98.3% of exclusions). That
figure entered the README on 2026-04-01 (`985973b`) and is the
manuscript's reported result.

**Replaying the committed goldens gives 80, not 73.** Both numbers are
reported here rather than silently reconciled, because they come from
different executions and only one of them is reproducible.

### The deterministic stages reproduce exactly

The two heuristic stages give bit-identical results across every run we
have: 776 records → EH excludes 125 → 651 → IH excludes 566 of those →
**85**. The set of 85 is not merely the same size but the same records:
the intersection of the EH and IH survivor sets is identical, record for
record, to
[`el_input_v3.1.0.csv`](data/study_input/el_input_v3.1.0.csv). Those 691 exclusions are
98.3% of the 703 total the README reports — the deterministic share the
manuscript claims is exactly the share the goldens contain.

This is the majority of the pipeline's work, and it is fully
reproducible from the repository with no API access.

### The LLM stages do not

The manuscript figure requires 12 LLM exclusions (776 − 691 − 12 = 73).
The committed goldens give 5: EL `OUT` 1, IL `OUT` 4, leaving **80**.

The gap is 7 records, and it localises to the IL stage. The IL golden
holds 30 records carrying a valid-quote `not_meet` on `IC-1` at
confidence 0.1–0.4, kept from acting only by the 0.60 threshold. Seven of
those crossing 0.60 yields 11 IL exclusions and 73 survivors. No other
mechanism in the pipeline has that shape.

### What has been ruled out

- **Truncation.** The goldens were captured at `TRUNC_CHARS=4000` against
  a plugin default of 1500, which was the leading hypothesis. It does not
  survive: nothing in either corpus exceeds 2927 characters, so the 4000
  setting truncates nothing at all; every LLM criterion targets
  `keywords`, whose longest value is 270 characters and which neither
  setting reaches; and all 254 evidence quotes were drawn from
  `keywords`, none from `abstract`, none at or beyond character 1500. The
  only field either setting can change is one the deciding criteria never
  quote.
- **A different threshold.** No single value reproduces 73 (0.40 → 78,
  0.30 → 77, 0.20 → 68).
- **A different criteria set.** The criteria table is byte-identical
  across the runs compared.
- **The unevaluated `IC-5` criterion.** `IC-5` is a deterministic
  criterion assigned to an LLM stage and is therefore never applied (see
  the register, F-65). Evaluating it as a strict inclusion criterion
  would give 13 survivors, not 73.

### What remains

The manuscript run's artefacts — its bundle, its manifest, its response
cache — were not archived and will not be recovered. Q1 is therefore
closed on the evidence rather than on a reproduction.

The most likely explanation is that the two runs were not executing the
same code. The EL and IL stages were restructured on 2026-05-02 across
six commits (`f3fa6bb`, `90ff050`, `edd466d`, `9553393`, `3b4baf7`,
`8bec55e`), one of which — `90ff050` — removed duplicate LLM helpers that
had been shadowing the shared module. The goldens were captured after
that work, on the same day (`4fbe8fd`); the manuscript figure predates
all of it by a month. Ordinary run-to-run variation in model confidence
is sufficient on its own to move seven records across a 0.60 threshold,
and the archived run of 2026-05-07 shows that confidence values are not
stable between runs at all (see Limitations).

We therefore report 73 as the manuscript's result and 80 as the figure a
reader will obtain by replaying the committed goldens today. The
deterministic 98.3% of the funnel is reproducible; the LLM remainder is
not, and should not be quoted as though it were.

## Reproducibility

Every artefact in this evaluation is regenerable from inputs already
in the repository:

1. Empty grids and partition manifest:

   ```text
   python tools/eval_grid_generator.py \
       --el-filtered docs/data/study_input/el_filtered_v3.1.0.csv \
       --il-filtered docs/data/study_input/il_filtered_v3.1.0.csv \
       --criteria    docs/data/study_input/criteria_harmonized_v3.1.0.csv \
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
       --criteria         docs/data/study_input/criteria_harmonized_v3.1.0.csv \
       --filled-grids-dir docs/data/grids/filled \
       --el-filtered      docs/data/study_input/el_filtered_v3.1.0.csv \
       --il-filtered      docs/data/study_input/il_filtered_v3.1.0.csv \
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
