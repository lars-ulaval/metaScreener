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
  Over this repository's own 85-record corpus and criteria,
  `llama3.2:3b` produced 43 exclusions and `qwen2.5:7b` produced 4, all
  unjustified — and every one of them *passed* the gate, with a
  verbatim quote and a confidence above threshold. The gate verifies
  that a quote is real; it cannot verify that a quote is relevant, and
  nothing short of another model could. Nor was it a format failure:
  llama3.2 answered 170 of 170 in perfect JSON with zero vocabulary
  rejections. It simply asserted matches that were not there. A run can
  therefore look entirely healthy by every counter this pipeline keeps
  and still be removing correct studies.

  What follows is that a local model may annotate but may not exclude,
  which is what flag-only mode enforces (F-145): on a local or custom
  provider an excluding verdict is recorded as `EXCLUSION_SUPPRESSED`
  and the record survives to human review. The gate remains useful — it
  is what makes a *malformed* verdict harmless — but it is not what
  makes a *confident and wrong* one harmless, and only the second of
  those was ever the interesting case.

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

## Reproducibility of the demonstration funnel

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
