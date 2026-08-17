# Wave 17 — what the seven arms MEASURED

Written 2026-08-17, after `62a1049`. This document answers the gap the wave-17
handoff names in its §9: seven arms had run and no report anywhere said what any
of them measured. Everything reported before this was operational — call counts,
re-ask rates, gate outcomes, request shapes, wall clock, token densities. Those
establish that the instrument worked. They say nothing about the experiment.

**No arm was run to produce this document. Zero LLM calls were made.** Every
figure below is derived by script from bytes already committed under
`docs/data/wave17_arms/` and `docs/data/wave16_live_runs/`, or from the product's
own deterministic translator/loader/prompt-builder invoked in-process with the
dry guard installed (`tools/run_criteria_experiment.py::_install_dry_guard`,
which makes LLM client construction raise).

**All ten arms have now run.** `h6_no_abstract`, `h9_batch1` and `h7_loose` were run at wave 17e — 267 live calls, 3,221 s — and §10 reports them. Wave total: **472 live calls across ten arms.**

---

## The answer, in one page

**There is a control, and it is zero.** `h0` ran twice, 24 calls each. The two
executions produced byte-identical verdict tables — **0 of 96 record×criterion
pairs differ on any of six axes**. Nothing below is run-to-run variation. (§1)

**K1 — rewording the criteria moves the product a lot.** Same 32 records, same
model, temperature, batch, truncation, window, policy and cache; eight criteria
restated in synonymous English. **9 of 32 records flipped at IL, 5 of 32 at EL.**
The human review pile went 19 → 25 at IL (+31.6%) and 2 → 6 at EL (+200%). The
number of papers cleared without human attention at both stages **halved, 10 →
5**. F-221 replicates in effect and in sign — but **not** in its headline
"none went the other way": 2 of 9 flips are counter-directional here. (§2)

**K2 — an 18-character hint moves the evidence, not the verdict.** `h8` differs
from `h0` by exactly one inserted substring, `,abstract,keywords`, in the
criterion's `target`; the system prompt and every item byte are identical
(verified by rendering both prompts). Decisions barely move — 1 of 64 at EL,
2 of 32 at IL. But the model's self-reported evidence field swings **70.8 points**
(title-share 95.8% → 25.0%), and because `valid_quote` is computed against the
field the model *names*, the hint changes gate outcomes: 3 records move at EL,
2 swap at IL **while the aggregate counts stay identical**. (§3)

**K4 — the routing all landed; four registered predictions about behaviour did
not.** All 52 `landings_vs_intent` rows match. But `h2`'s IC-26 — registered
"expected to cut 0" — cut 449 of 461 and **inverted its own criterion**, leaving
the arm with nothing but the 12 Portuguese records it was written to exclude;
`h4`'s H4-6 was authored to demonstrate the absence rule and demonstrated the
presence gate instead; and two more framings cite bounds that do not apply.
`intended_target`, registered on all 70 intents, is **read by no code**. (§5)

**The largest behavioural effect in the wave is negation.** On records with
unambiguous ground truth, three of four negation-phrased criteria were answered
as though the negation were absent — EC-23 12/12 wrong, EC-28 12/12 wrong,
IC-22 10/12 wrong; only "something other than" survived. It cleared everything
at EL and flagged everything at IL. (§5.2)

**Where the LLM can be checked against a title, it is poor.** `h3`'s IC-33 found
1 of 10 explicitly paediatric populations; EC-38 found 1 of 18 explicit
reviews and flagged 4 papers that are neither. 115 of 116 records went to a
human, and the review denominator is 18, not the 16 an earlier draft used.
(§5.6, filed as F-242)

**"Zero removals" needs a second sentence.** `OUT` is 0 in all 14 stage
summaries, as reported. But **24 verdicts across six arms passed the strict
presence gate and reached `ACTION_EXCLUDE`** — validated quote, over the 20-char
floor, over threshold. What stopped them was `exclusion_policy: flag_only`, not
the gate. That number has never been reported. (§5.4.1)

**EL's excluding verdicts are 0 for 9.** Extending §7.6's `h0` finding to `h1`
and `h8` at zero call cost gives 16 excluding verdicts on 9 distinct pairs;
three independent judges call 8 unanimously wrong and the ninth merely
defensible, **none correct**. EC-2's true-positive set on the pile is empty, and
EC-3 never fired on either record it was written to catch (0 of 6). On A187 and
A275 the model offered **the same quote, at the same span, as proof of inclusion
and of exclusion** — both `quote_valid: true`. Raised F-244 to High. (§7.8)

**K5 — the pile is mostly right; what is missing from it is not.** Two substring
rules removed 391 of 423 records and let through **none** of the 152 that are
off-topic by construction. Three independent reviewers judged the surviving 32:
**10 correct, 14 boundary, 8 wrong** (5 wrong unanimously). IL sorted that pile
well — **8 of 8 wrong inclusions flagged, 0 wrong inclusions among the 12 it
cleared**, 83.3% agreement on the 18 decisive records. The pile also holds a
duplicate work under two DOIs (A223 = A229) and three records with no abstract,
two of them cleared.

But decomposing the gate shows **IC-4 alone excludes 151 of the 152 off-topic
records**, while IC-5's real effect is to kill **117 IC-4-matching papers, 116 of
them on-topic** — including Berntson's *Respiratory sinus arrhythmia: autonomic
origins*, Porges's *Cardiac vagal tone*, Thayer's neurovisceral-integration
papers and *HRV as a transdiagnostic biomarker of psychopathology*. Nothing
surfaces that to the user.

And **the only two removals the pipeline attempted on `h0` were A187 and A275 —
two of the seven records all three reviewers unanimously call correct.** EC-3
claimed each is primarily about clinical arrhythmia diagnosis, at confidence 0.9,
and quoted as proof the record's own title saying the opposite. Both quotes are
`quote_valid: true`, so the strict gate accepted both: **it verifies that a quote
exists in the record, never that it supports the verdict.** Only flag-only
stopped the removal. (§7)

**Sixteen statements in committed prose are wrong against the artefacts they
describe** — including a revised stop condition that would halt on 89% of all
verdicts, and an F-218 test that cannot be run because no log carries a
timestamp. (§6)


---

## 0. State, verified rather than trusted

| check | handoff says | measured this session |
|---|---|---|
| `git log -1` | main at `b95886b` | **`62a1049`** — the handoff's own commit, made after §1 was written |
| working tree | clean | clean |
| suite | 2348 passed / 7 skipped | **2348 passed, 7 skipped** |
| `tools/audit_imports.py plugins/ tests/` | green | **exit 0, clean** |
| `tools/audit_decorators.py plugins/ tests/` | green | **exit 0, clean** |
| `tools/check_encoding.py` | green | **exit 0, 481 paths, no BOM or mojibake** |
| register totals | 40 machine cells | `tools/derive_register_totals.py`: **"matches the rows in all 40 cells"**; highest id **F-237**, next free **F-238** |
| live artefacts | 63 files, 7 arms | **63 files, 7 arms** (9 per arm) |
| live calls in the artefacts | 230 spent | **205 recoverable** from the 7 committed manifests; the other 25 are h0's first run (24, overwritten in place) and h2's aborted first call (1). `b95886b`'s own message says "205 across all seven arms that have now run" |

The corpus digest in the spec verifies against `samples/20260816_1841_rsaAggregate.csv`
(`e8b262f1…`); the harness refuses to run otherwise and the check was re-run here.

---

## 1. The control nobody had computed — a zero noise floor

Wave 16 could say its five IL flips were not run-to-run variation because it had
measured a same-configuration noise pair at 0 of 64. Wave 17 appeared to have no
such control. **It does, and it is stronger.**

`h0_baseline` ran twice. `74bf295`'s own message records the second run: *"h0
re-run instrumented: 24 calls, 191.3 s against the first run's 191.7 s"*. The
first run's artefacts were committed at `6265d89`; the second overwrote them.

What the second run changed, and what it did not:

```
$ git rev-parse {6265d89,74bf295,b95886b,HEAD}:docs/data/wave17_arms/live_v1/h0_baseline_EL_FULL.csv
ad80e26ef6dbeb568c33cb55cc8beaf54cd2f409   (all four)
... _IL_FULL.csv
75eeeb2e7cdb1b8df128090e460ef7eda2999c5e   (all four)

$ git show --stat --format="" 74bf295 -- docs/data/wave17_arms/live_v1/
 h0_baseline_EL_report.json    |  88 ++++-
 h0_baseline_EL_summary.json   |  88 ++++-
 h0_baseline_IL_report.json    |  46 ++-
 h0_baseline_IL_summary.json   |  46 ++-
 h0_baseline_live_manifest.json| 136 +++++-
```

The summaries changed (`wall_seconds` 124.3 → 123.1 at EL, 67.4 → 68.0 at IL,
plus the new `token_samples` array). The `FULL.csv` blobs did not change at all.
`run_arm_live` writes `{key}_{stage}_FULL.csv` unconditionally, into the same
`out_dir` as the summary it did rewrite, so the second execution produced
byte-identical verdict tables.

**The wave-17 noise floor is therefore 0 differences across 32 records × 41
columns × 2 stages** — including all 96 record×criterion verdict pairs on all six
evidence axes (`decision`, `status`, `confidence`, `field`, `quote`,
`quote_valid`). Two independent executions, 48 live calls, different wall clock,
identical output at temperature 0.0.

Everything in §2 and §3 below is measured against that zero.

> One honest limit on the inference: git cannot distinguish "rewritten with
> identical bytes" from "not rewritten". The write is unconditional in the same
> function that rewrote the summary, and the summary demonstrably changed, so the
> file was written. That is the whole chain; it is not a byte-level capture of two
> separate runs sitting side by side. A freeze that wanted the stronger artefact
> would keep both runs under distinct names.

---

## 2. K1 — `h0` vs `h1`: the wave's actual result

### 2.1 The methodological premise, settled before the comparison

F-221 is stated as *"Paraphrasing IC-1 … moved 5 of 22 records at IL"*. Wave 16's
`g1_paraphrase.txt` reworded **all eight** criteria, not one. The brief was right
to ask whether the figure was attributed to one criterion or to the arm.

Settled by machine, three ways:

1. **IL runs exactly one LLM criterion, and it is IC-1** — in both waves.
   `llm_criteria: 1` in every IL summary, and the set of criterion ids appearing
   in `il_evidence_json` across every record is exactly `['IC-1']`.
2. **One prompt carries one criterion.** `plugins/06_el/prompt.py:60-68` packs a
   single `c_pack` per call; `token_samples` records one `criterion` per call.
   The other seven criteria cannot reach the model at IL by any path.
3. **Routing did not move.** The `h0` and `h1` dry manifests carry identical
   funnels — 463 → EH 423 → IH 32, with identical per-criterion impacts — and
   the deterministic rows harmonise byte-identically. Both arms screened the
   **same 32 `local_id`s** at both stages.

So F-221's attribution is **sound at IL**: rewording all eight varies exactly one
criterion's text at that stage. It is **loose at EL**, where two LLM criteria
(EC-2, EC-3) were both reworded — F-221's "the same paraphrase moved 1 of 44
pairs at EL" is a two-criterion figure, and 44 = 22 records × 2 criteria.

And the original figure reproduces exactly. Recomputed from
`docs/data/wave16_live_runs/`:

| F-221 as filed | recomputed |
|---|---|
| 5 of 22 at IL, `PASS_CLEAN` → `EXCLUSION_SUPPRESSED` | **5 of 22, same transition** |
| A317, A330, A332, A558, A612 | **exactly those five** |
| every one `meet` → `not_meet`, none the other way | **5 `meet`→`not_meet`, 0 counter-directional** |
| review pile 11 → 16 (+45%) | **11 → 16, +45.45%** |
| 1 of 44 pairs at EL | **1 of 44** (A332/EC-2) |

Wave 17's `h0`/`h1` therefore replicate F-221's **design** on a second corpus
(463 RSA records vs wave 16's 776 VR records; 32 survivors vs 22). It is not a
re-run of F-221's instance.

### 2.2 IL — 9 of 32 records flipped, and the flips are NOT one-directional

Population 32, one criterion (IC-1), 32 pairs. **9 pairs differ on decision and
status; 23 agree.** Every differing pair changed its decision — there are no
status-only changes at IL.

| direction | n | records |
|---|---|---|
| `meet` → `not_meet` (MET → SUPPRESSED) | **7** | A216, A275, A276, A281, A284, A285, A431 |
| `not_meet` → `meet` | **2** | A273 (SUPPRESSED → MET), A406 (UNCERTAIN → MET) |

**This is where the replication departs from F-221.** F-221's strongest sentence
is *"Every one of the five went `meet` → `not_meet`; none went the other way."*
On the second corpus, 2 of 9 go the other way. The net effect and its sign
survive; **unidirectionality does not.** Anyone citing "none went the other way"
as a property of the phenomenon should be told it is a wave-16 single-corpus
observation that the wave-17 replication contradicts.

Record-level outcomes:

| | `PASS_CLEAN` | `REVIEW` | `EXCLUSION_SUPPRESSED` | `OUT` |
|---|---|---|---|---|
| `h0_baseline` | 12 | 1 | 19 | 0 |
| `h1_paraphrase` | 7 | 0 | 25 | 0 |

**Human review pile at IL: 19 → 25, +31.6%.** (Counting `REVIEW` alongside
`EXCLUSION_SUPPRESSED` as work for a person: 20 → 25, +25.0%.)

### 2.3 EL — 5 of 32 records flipped, 4 of 5 toward removal

Population 32, two criteria (EC-2, EC-3), 64 pairs. **7 pairs differ on decision
or status; 57 agree on both.** Two of the seven changed status without changing
decision — a confidence movement across the 0.60 threshold, or a change in
whether the quote validated.

| | `PASS_CLEAN` | `PASS_FLAGGED` | `EXCLUSION_SUPPRESSED` | `OUT` |
|---|---|---|---|---|
| `h0_baseline` | 27 | 3 | 2 | 0 |
| `h1_paraphrase` | 25 | 1 | 6 | 0 |

**Human review pile at EL: 2 → 6, +200%.** `h0`'s pile is a strict subset of
`h1`'s.

Per pair (EL criteria are `exclude`, so `not_meet` → `meet` moves toward removal):

```
A014 EC-2  MET/not_meet 0.8   -> SUPPRESSED/meet 0.9     toward removal
A132 EC-3  UNCERTAIN/not_meet 0.5 -> MET/not_meet 0.8    status only
A199 EC-2  UNCERTAIN/meet 0.9 -> SUPPRESSED/meet 0.85    status only (quote gate; see §3.3)
A224 EC-2  MET/not_meet 0.8   -> SUPPRESSED/meet 0.85    toward removal
A275 EC-2  MET/not_meet 0.8   -> SUPPRESSED/meet 0.9     toward removal
A275 EC-3  SUPPRESSED/meet 0.9 -> MET/not_meet 0.8       away from removal
A292 EC-2  MET/not_meet 0.8   -> SUPPRESSED/meet 0.9     toward removal
```

Across both stages, **11 of 14 decision changes move toward removal**, 3 away.
The asymmetry points at more work for the human, not less.

**A275 is the instructive null.** Both its EL criteria flipped, in opposite
directions, and its EL outcome stayed `EXCLUSION_SUPPRESSED` in both arms. A
stage outcome can be stable while every verdict under it moved.

### 2.4 What a user would actually see

The figure that matters to someone using the product is not a per-criterion rate
but how many papers they can clear without reading. Counting records that come
out `PASS_CLEAN` at **both** LLM stages:

| arm | clean at both stages | needs a human at one or both |
|---|---|---|
| `h0_baseline` | **10** of 32 | 22 |
| `h1_paraphrase` | **5** of 32 | 27 |

**Rewording eight criteria into synonymous English halved the number of papers
the system cleared unaided, on the same 32 papers, with model, temperature,
batch size, truncation, window, endpoint, prompt version, policy and cache
setting all held fixed and a measured noise floor of zero.**

The EL and IL flip sets are disjoint — no record flipped at both stages — so
**14 distinct records of 32 (43.8%)** changed their outcome at one stage or the
other.

---

## 3. K2 — `h0` vs `h8`: F-227's only surviving claim

### 3.1 The variable, established byte-exactly

`h8_pinned_target` is `h0`'s eight criteria as a hand-authored columnar CSV with
`target` pinned to `title,abstract,keywords` on the LLM rows; `h0` is `free_text`,
whose LLM rows take `target` from `_get_best_text_targets` and land on `title`
alone. Everything else is meant to be identical. **Verified, not assumed**, by
running the product's own translator, loader and prompt builder in-process
(dry guard installed, zero calls) and diffing the rendered messages:

| | EC-2 | EC-3 | IC-1 |
|---|---|---|---|
| `c_pack` keys differing | **1** (`target`) | **1** (`target`) | **1** (`target`) |
| system message | identical | identical | identical |
| user message change hunks | **1 insert** | **1 insert** | **1 insert** |
| the hunk | `,abstract,keywords` | `,abstract,keywords` | `,abstract,keywords` |

`id`, `type`, `operator`, `what`, `how`, `label`, `threshold` and every item
payload byte are identical. **The whole experiment is 18 inserted characters.**

### 3.2 The decisions barely move — but the aggregate hides a swap

| stage | pairs | agree on decision+status | record outcome flips |
|---|---|---|---|
| EL | 64 | 61 | 3 |
| IL | 32 | 30 | 2 |

At EL the review pile doubles, 2 → 4 (`PASS_FLAGGED` 3 → 1,
`EXCLUSION_SUPPRESSED` 2 → 4), and `h0`'s pile is a strict subset of `h8`'s.

At IL **the aggregate counts are identical** — `PASS_CLEAN` 12, `REVIEW` 1,
`EXCLUSION_SUPPRESSED` 19 in both arms, and the decision and status tallies match
too. A summary-level comparison would report "no effect". **It would be wrong.**
Two records swapped in exactly offsetting directions:

```
A273  EXCLUSION_SUPPRESSED -> PASS_CLEAN     (IC-1 not_meet -> meet)
A276  PASS_CLEAN -> EXCLUSION_SUPPRESSED     (IC-1 meet -> not_meet)
```

The 19-record pile has the same size and **not the same membership**: 18 shared,
A273 only in `h0`, A276 only in `h8`. Any cross-arm claim in this wave built on
`summary.json` counts alone is unsound at IL. The handoff's own framing — *"h8's
EL suppression split is 4 against h0's 2, so something moved"* — is true at EL and
would have missed IL entirely.

### 3.3 The hint's real effect: it relocates the model's claimed evidence

This is the measurement F-227 was reaching for and nobody had taken.

`field` is genuine model self-report: `llm_client.py:1745-1756` only lowercases
and vocabulary-checks it, and `fields_rejected` is 0 in all four `report.json`
files, so nothing was clamped or defaulted.

| | `title` | `abstract` | `keywords` |
|---|---|---|---|
| `h0` (target `title`), 96 pairs | **92** | 3 | 1 |
| `h8` (target `title,abstract,keywords`), 96 pairs | 24 | **70** | 2 |

**A 70.8-point swing in title-share from an 18-character hint**, while the
evidence actually sent to the model is byte-identical in both arms —
`prompt.py:78-86` packs `title`, `abstract` and `keywords` for every item
unconditionally, whatever `target` says.

### 3.4 The mechanism, and why the surviving claim is stronger than the row says

F-227's open row says a reviewer *misreads* `target` on an `llm` row and concludes
the model saw only that field. True. But the artefacts show the hint also **changes
the gate outcome**, through a chain that is entirely in the code:

1. The prompt asks the model to name a `field` and quote from it.
2. `llm_client.py:1766` computes `valid_quote = _quote_in_text(quote, fld_txt_prompt)`
   where `fld_txt` is selected **by the field the model named**, not by `target`.
3. `verdict_gate.py`'s `RULE_REMOVES_BY_PRESENCE` requires `valid_quote` before
   an excluding verdict may be acted on or suppressed.

So the hint steers the named field, the named field selects the validation text,
and that decides whether the strict presence gate fires. Record **A199** is the
clean demonstration — same decision, same confidence, different gate:

```
h0  EC-2  decision=meet conf=0.9  field="title"
          quote="Conditioned pain modulation (CPM) refers to the diminution of ..."
          -> that text is in the ABSTRACT, not the title
          -> quote_valid=false  -> gate refuses      -> UNCERTAIN  -> PASS_FLAGGED

h8  EC-2  decision=meet conf=0.9  field="abstract"
          quote="Studying CPM in children may inform interventions to enhance ..."
          -> quote_valid=true    -> gate accepts     -> SUPPRESSED -> EXCLUSION_SUPPRESSED
```

**A null result on decisions is not a null result on outcomes.** The hint moved
1 decision of 64 at EL and 2 of 32 at IL, and it moved 3 EL records and 2 IL
records into or out of a human's queue.

---

## 4. K3 — `h0` vs `h9`: unavailable when this was written, MEASURED at §9.1

`h9_batch1` is unrun. It is h0's criteria, h0's records and h0's source digest
with `batch_size` 1 at both LLM stages, and it is **the outstanding F-215
measurement**: the identity gap F-215 documents (`_absorb` silently drops
out-of-batch `a_id`s at `llm_client.py:1645-1646` and duplicates at `:1654-1655`;
the schema pins cardinality but leaves `a_id` an unconstrained string at `:1089`)
exists only when batch > 1, because at cardinality 1 there is nothing to drop or
conflate. F-215 was argued to High at wave 16c and has never been measured.

**Run at wave 17e. See §9.1** — and the result is not the one F-215 predicted:
the identity gap this arm was built to expose produced nothing to count, while
batch size alone moved the both-stages-clean pile from 10 of 32 to 5 of 32, the
same magnitude as rewording all eight criteria. §1's zero noise floor is what
makes that attributable to batch size and nothing else.

---

## 5. K4 — the registered intents against what happened

Every arm registered per-criterion intents in `experiment_spec.json` before
running. The spec is candid that the deterministic half was *measured* during
authoring by running the real translator, loader and evaluator, so those are
confirmations rather than blind predictions. The LLM half had never been
exercised.

**All 52 `landings_vs_intent` rows across the seven run arms match on stage and
operator — 0 mismatches.** Every arm's `expected_chain` also matches its dry
manifest's funnel, number for number.

That is a narrower result than it looks, for two reasons stated here rather than
left to be found:

1. **`landings_vs_intent` checks `intended_stage` and `intended_operator` only.
   `intended_target` is registered on all 70 intents in the spec — 52 of them on
   the seven arms that ran — and is read by no code in the repository.**

   ```
   $ grep -rn "intended_target" --include=*.py .      # build/ excluded
   (no matches)
   $ grep -rn "intended_stage" --include=*.py .
   tools/run_criteria_experiment.py:427  match = (landed_stages == [intent["intended_stage"]]
   tools/run_criteria_experiment.py:428           and landed_ops == [intent["intended_operator"]])
   ```

   So **one of the three registered fields on every intent in this wave has never
   been checked by anything**, and each manifest's `match: true` attests to two
   thirds of what it appears to attest to. Checked by hand here: all 52 landed
   targets do equal their registered target — the claim is true, it was simply
   never verified by the artefact that looks like it verifies it.

   Worse for `llm` rows, the registered target is not enforceable even in
   principle: `plugins/06_el/screen.py:588-591` sends `{title, abstract,
   keywords}` for every record whatever `target` says, and the source comment at
   `:640` says so outright. On `h3` the consequence is visible — EC-38 registers
   `intended_target: title`, and 2 of its 116 verdicts (A359, A366) report
   `field=abstract` with quotes that verify as present in the abstract and absent
   from the title. Both are among the five records that criterion asked to
   exclude.
2. **A criterion can land correctly and still do the opposite of what it says.**
   Landing is about routing. Four registered predictions about *behaviour* were
   falsified, and one arm was destroyed by one of them.

### 5.1 Falsified registered predictions

**`h2` / IC-26 — the largest miss in the wave.**

Registered: *"'written in a language other than Portuguese' makes branch 1's
free-capture take `in a` and emit `in_list lang ['A','Portuguese']` — a spurious
operand the linter does not flag. **Expected to cut 0.**"*

The translation was predicted exactly. The consequence was not. `in_list` MEETS
when the value is in the list, so `lang` in `{A, Portuguese}` admits **only** the
Portuguese records:

```
funnel ih impacts IC-26:  met 12,  failed 449   (of 461 at IH)
```

**It cut 449 of 461 — and it inverted the criterion.** A rule written to exclude
Portuguese admitted nothing but Portuguese. The arm's entire LLM population is
the 12 `lang=pt` records, every one of them `parents=X002` (science education,
off-topic by construction):

```
A070 A071 A081 A084 A086 A094 A095 A098 A102 A103 A107 A109
Pedagogia da indignacao . Pedagogia da esperanca . A construcao do pensamento
e da linguagem . Conscientizacao . (Freire, Vygotsky, physics education)
```

Note the arm-level `expected_chain` for `h2` registers `ih_surv: 12` — the right
number. So the spec carries **two registered predictions that contradict each
other**: the criterion rationale says "cut 0", the chain says 449 were cut. Both
were recorded before the run. Only the chain was checked by the manifest.

**`h2` / EC-24 — partially falsified.** Registered: *"the comma-and-or tail is
taken WHOLE, so branch 6 emits **one** operand ... rather than six. Expected to
cut ~0."* Observed: **two** operands, not one —
`["emotion, dysregulation, child, adolescent, youth", "infant"]`, because the
capture split on " or ". The predicted *effect* held (2 records cut of 463); the
predicted *mechanism* was off by one operand.

**`h4` / H4-5 — the floor is in the wrong place.** Registered: *"deliberately
thin `what` (F-21 substance floor, 20-char minimum)"*, with `what` = `"Noise."`
(6 chars). But `SUBSTANCE_MIN_CHARS` and `substance_ok` in
`plugins/_common/verdict_gate.py` are applied to **the model's quote**, never to
the criterion's `what`. Nothing in the validator, linter or loader rejected it.
The criterion screened all 69 records normally: **68 MET, 1 UNCERTAIN.** The
shape was exercised; the registered rationale mis-locates the mechanism it
claims to probe.

**`h4` / H4-7 — a bound that does not apply.** Registered: *"long-prose criterion
near the 1500-char truncation bound"*. Its `what` is **1445 chars** against
`trunc_chars: 1500` — but `_build_llm_messages_for_criterion` applies `trunc()`
**only to each item's `title`/`abstract`/`keywords`**. The criterion is never
truncated, at any length. H4-7 is a long-prompt probe, which is real and useful;
it is not a truncation probe.

### 5.2 `h2` — the polarity result, which the arm still yields

The mirror-pair comparison the arm was built for **cannot be run**: `h0`'s 32
records and `h2`'s 12 share **zero** ids, so there is no record on which to
compare a criterion against its inversion. IC-26 destroyed the comparison.

What survives is better than nothing, because the 12 records give **unambiguous
ground truth**. They are Portuguese pedagogy and physics-education papers. None
reports respiratory sinus arrhythmia, vagal tone, or anything cardiac.

| criterion (as written) | truth on all 12 | model answered | correct? |
|---|---|---|---|
| EC-23 "The paper **does not** report RSA or any vagally-mediated HRV measure." | `meet` | **`not_meet` 12/12** | no |
| EC-28 "The study uses **no** index of cardiac vagal tone of any kind." | `meet` | **`not_meet` 12/12** | no |
| IC-22 "The paper's main topic is **not** clinical arrhythmia diagnosis." | `meet` | **`not_meet` 10/12** | no |
| IC-21 "...primary focus is **something other than** a numerical or computational method..." | `meet` | **`meet` 9/12** | yes |

**Three of the four negation-phrased criteria were answered as though the
negation were absent.** The one answered correctly is the one phrased "something
other than" rather than "does not" / "is not" / "no".

The consequences run in opposite directions at the two stages, and both are
wrong:

- At **EL**, EC-23 and EC-28 are `exclude`. The correct `meet` would have flagged
  all 12 for removal. The model's `not_meet` is a keep, so **all 12 passed EL
  `PASS_CLEAN`** — twelve plainly off-topic papers cleared by two criteria that
  each say, correctly, that they are off-topic.
- At **IL**, IC-22 is `include`. The correct `meet` would have kept them. The
  model's `not_meet` routes through `RULE_REMOVES_BY_ABSENCE`, so **11 of 12
  became `EXCLUSION_SUPPRESSED`** — the same twelve papers pushed into a human's
  queue by an inclusion criterion they satisfy.

One genuine wording-invariance datum sits inside this: **EC-23 and EC-28 are two
different English wordings of the same inversion, and they agreed on the decision
for 12 of 12 records.** They agreed on the *wrong* answer, and the population is
an easy one, so this is not evidence that wording does not matter — §2 measures
that on a hard population and finds the opposite. It is evidence that these two
wordings failed identically.

### 5.3 `h3` — the routing traps all fired as registered

| id | registered | observed | verdict |
|---|---|---|---|
| IC-31 | branch 2 (year), `gte` — "unexercised by h0 and the reason this arm exists" | landed IH/`gte`; met 120, failed 277, missing 1 | **HELD** |
| EC-35 | "branch 2 the other way, `lte`" | landed EH/`lte`; failed 61, missing 1 | **HELD** |
| EC-36 | branch 5 (DOI). "Expected UNKNOWN for every record, not FAILED — `equals ''` against a populated column." | `unknown 463`, met 0, failed 0; linter: `MISTRANSLATED`, "offers 1 alternatives but the rule carries only 0" | **HELD** |
| EC-34 | branch 1 with German. "post-F-212 this now maps to `de`; the corpus holds no `de`, so a **correct** 0 rather than an **inert** 0. The distinction F-229 is about." | met 463, failed 0, **unknown 0** — evaluated on every record, matched none | **HELD** |
| EC-37 | branch 3 (doc_type) | landed EH/`equals`; failed 4 | **HELD** |
| IC-32, IC-33, EC-38 | IH/`equals`, IL/`llm`, EL/`llm` | as registered | **HELD** |

EC-34 beside EC-36 is the cleanest thing in the arm: one manifest shows a rule
that ran and matched nothing (`met 463, unknown 0`) next to a rule that never ran
at all (`unknown 463, met 0`). F-229's distinction is visible in one file.

**The population is the arm's real surprise.** 64 of h3's 116 EL/IL records
(55.2%) carry `parents` X002/X012 — off-topic by construction. `h7_loose` was
designed and priced specifically to push off-topic mass into the LLM stages;
`h3` did it by accident, at 116 records instead of 189. The model behaved
sensibly on them: IC-33 ("study population consists of children or adolescents")
returned `not_meet` on 64 of 64 off-topic records, and on 50 of 52 on-topic ones.

### 5.4 `h4` — eight edge shapes reached, two framings wrong

| id | shape | observed | verdict |
|---|---|---|---|
| H4-1 | `between` bounds — "the translator can never emit this from prose" | landed IH/`between`; met 319, failed 131, missing 1 | **HELD** |
| H4-2 | `in_list` on ISO codes | failed 12 (the `pt` records); no `de` in corpus | **HELD** |
| H4-3 | `not_in` with an **empty** operand; "expected UNKNOWN for all, i.e. `PASS_FLAGGED`" | `unknown 451`; IH `pass_flagged 69` — every survivor flagged | **HELD** |
| H4-4 | `regex` on title | met 463, failed 0 — ran, matched nothing | **HELD** |
| H4-5 | thin `what` | 68 MET / 1 UNCERTAIN — screened normally | **framing FALSIFIED**, §5.1 |
| H4-6 | "absence-phrased exclusion; `RULE_REMOVES_BY_ABSENCE`, never auto-acted" | 6 SUPPRESSED, 4 UNCERTAIN, 58 MET, 1 UNCERTAIN; 0 removed — but by the **presence** gate and by policy, not by the absence rule | **FALSIFIED**, §5.4.1 |
| H4-7 | long prose "near the truncation bound" | 68 `not_meet` + 1 `meet`; 65 SUPPRESSED, 3 UNCERTAIN | **framing FALSIFIED**, §5.1 |
| H4-8 | threshold `1.00`, "the upper bound" | **69 of 69 UNCERTAIN**; highest confidence returned **0.95**; never satisfied | see below |
| H4-9 | a pile bound, not a shape | 69 survivors | **HELD** |

**H4-8 is worth setting against wave 16.** Wave 16 recorded, as candidate finding
6, *"A confidence of exactly 1.0 is reachable, so a threshold of 1.0 is not the
unsatisfiable guard it looks like."* On h4, at n=69, threshold 1.00 was **in
effect unsatisfiable** — nothing above 0.95. But 1.0 *is* reachable in this wave:
`h2`'s IC-22 returned confidence **1.0** on A107 and A109. The wave-16 statement
survives as "reachable"; h4 adds that reachability is criterion- and
population-dependent enough that a 1.00 threshold sent 69 of 69 records to
UNCERTAIN.

**F-237's own arithmetic is right; the handoff's heading around it is not.**
Recomputed: H4-7 has **68 `not_meet`** verdicts, of which 4 carry a non-empty
quote, of which **3 are `quote_valid=False`** (A220, A221, A223) and 1 is valid
(A228). All four are `status=SUPPRESSED`, confidence 0.9, and
`RULE_REMOVES_BY_ABSENCE` does not consult the quote, so all four are inert.
But the handoff §6 heading calls these *"The three `quote_valid=False` cases"* of
the wave, and they are 3 of **22**. See §6.2.


#### 5.4.1 H4-6 did not exercise the rule it was written to exercise — and the wave's "zero removals" needs a second sentence

H4-6's registered rationale reads *"absence-phrased exclusion, verdict_gate
`RULE_REMOVES_BY_ABSENCE`"*. **The gate does not key on phrasing.** `GATE_TABLE`
at `plugins/_common/verdict_gate.py:94-99` keys on `(ctype, decision)`, four
cells total:

```
("exclude", "meet")     -> RULE_REMOVES_BY_PRESENCE
("exclude", "not_meet") -> RULE_KEEPS
("include", "meet")     -> RULE_KEEPS
("include", "not_meet") -> RULE_REMOVES_BY_ABSENCE
```

H4-6's `type` cell is `exclude`. Its 10 `meet` answers therefore hit
`("exclude","meet")` = **`RULE_REMOVES_BY_PRESENCE`**, the strict quote gate.
`RULE_REMOVES_BY_ABSENCE` is reachable only from `("include","not_meet")` and was
never touched by this criterion. Machine confirmation:
`h4_edge_shapes_EL_summary.json` has `absence_suppressed_key_present: false`,
while the same arm's IL summary — where H4-7 is `include` + `not_meet` — has it
`true`.

Writing a criterion in the negative does not move it into the absence cell. Only
its `type` column does.

**And the six suppressions were not refusals. They were acceptances.** All six
came back `meet`, `quote_valid: true`, with a quote clearing the 20-char
substance floor, and confidence over threshold — the complete success path of
`RULE_REMOVES_BY_PRESENCE`, which returns `ACTION_EXCLUDE`. The product says so
itself in the reason summary a reviewer reads:

> `EXCLUSION_SUPPRESSED`: the model returned an excluding verdict on H4-6 **which
> passed the evidence gate**. Flag-only is in force for this provider, so the
> record was NOT excluded and needs human review.

Counted across the whole wave — every arm, both stages, `type` read from each
arm's own harmonized rows:

| | n |
|---|---|
| verdicts the **presence gate accepted** (`ACTION_EXCLUDE`), declined only by `exclusion_policy: flag_only` | **24** |
| verdicts refused by the absence rule (unconditional; no setting can permit them) | **283** |
| records actually removed (`OUT`) across all 14 stage summaries | **0** |

per arm, presence-gate acceptances at EL: `h1` 6, `h4` 6, `h3` 5, `h8` 4,
`h0` 2, `h5` 1, `h2` 0.

`b95886b`'s subject line — *"gate held everywhere"* — and the handoff's stop
condition 1 are both satisfied: `OUT` is 0 in all fourteen summaries. But the
zero has two different causes and only one of them is the gate. **Had
`allow_exclusion` been true, 24 records across six arms would have been removed
on this wave's evidence.** That number has never been reported, and it is the one
a maintainer deciding whether to permit exclusion for this provider needs.

### 5.5 `h5` — every adversarial shape survived the parser

| id | shape | observed | verdict |
|---|---|---|---|
| H5-1 | curly quotes, em dash, doubled quotes, accents, checkmark | survived byte-for-byte into the harmonized `what`; 28 MET, 1 SUPPRESSED | **HELD** |
| H5-2 | operand containing a comma, inside a comma-delimited target cell | `what = ["heart rate, variability", "RSA"]` — comma kept **inside** the operand, `;` split between them; met 29, failed 411 | **HELD** |
| H5-3 | semicolon as separator: two operands, not one | `what = ["Physical Review", "Physics Letters"]`; failed 23, missing 37 | **HELD** |
| H5-4 | a wholly Cyrillic criterion | parsed and ran; 27 MET, 2 UNCERTAIN | **HELD, with a caveat** |
| H5-5 | U+00A0 inside the label | present twice in the committed bytes, survived into `what`; 29/29 `not_meet`, all SUPPRESSED | **HELD** |

**H5-4's registered rationale cites a fact that was unreachable on this arm.** It
reads *"a wholly non-Latin criterion, the corpus carries 40 Cyrillic characters"*.
The corpus holds **724 Cyrillic character occurrences**, drawn from exactly **40
distinct codepoints**, confined to two records: A235 (702, in `abstract`) and
A356 (22, in `authors`). The sentence says "characters"; it is true only on the
distinct-codepoint reading it does not state.

**Neither record reached h5's 29-record EL population, and the arm's own chain is
what removed them:**

- **A235** — 702 Cyrillic characters in `abstract`, the one record that could
  have tested a Cyrillic criterion against Cyrillic text in a targeted field —
  was cut at **IH by H5-2**, because its title/abstract/keywords contain neither
  `heart rate, variability` nor `RSA`.
- **A356** — 22 Cyrillic characters, in `authors`, outside any target — was cut
  at **EH by H5-3**, its venue being *Physical Review E*.

So the arm tested that a Cyrillic *criterion* parses, renders and returns
verdicts, which it does. It did not test a Cyrillic criterion against Cyrillic
*text*, because two other criteria on the same arm deleted the only records that
could have supplied it. Every Cyrillic character in
`h5_adversarial_EL_FULL.csv` is in `el_evidence_json`; none is in a record.

**H5-4 also produced the wave's clearest fabrication, and the gate caught it.**
On A140 the model returned `decision=meet`, confidence 0.95, `field=abstract`,
`span=[113,143]`, and as its quote it returned **the criterion's own text**:
`"Анотация написана кириллицей и не относится к теме."` A quote echoed straight
out of the prompt, with a fabricated span. `quote_valid=False` →
`RULE_REMOVES_BY_PRESENCE` refused → **UNCERTAIN, nothing removed.** The same
shape appears on `h8`/A455, where EC-2's quote is that criterion's sentence
verbatim, also refused. This is F-191/F-195's strict presence gate doing exactly
the job it was built for, on live evidence, twice.

**H5-5 is semantically degenerate and its 29/29 says nothing about the model.**
The criterion reads *"The paper studies RSA with a non-breaking space before the
operand"* — it describes the test, not the paper. Uniform `not_meet` is the only
sane answer available. The parsing result is the finding; the verdict
distribution is not evidence about anything.
### 5.6 The LLM half of `h3`, which is the wave's sharpest quality signal

`h3` is the only run arm whose LLM criteria are *checkable against the record's
own title* without domain expertise. Both fail, in the same direction.

**IC-33 — "The study population consists of children or adolescents rather than
adults" (IL, `include`).**

Ten of the 116 records carry an explicit paediatric term in the **title**
(`child`, `children`, `adolescen*`, `infant`, `preschool`, `youth`, `boys`,
`girls`). IC-33 returned `meet` on **one** of them — and on exactly one record in
the entire arm.

```
A407 not_meet 0.8  The Dysregulation Profile in middle childhood and adolescence across reporters
A409 not_meet 0.8  Executive function in children with externalizing and comorbid internalizing...
A411 not_meet 0.8  The Child Behavior Checklist Dysregulation Profile in Preschool Children...
A433 not_meet 0.8  Dyadic Attunement and Physiological Synchrony During Mother-Child Interactions
A449 not_meet 0.8  Association of Resting Heart Rate and Blood Pressure in Late Adolescence...
A452 not_meet 0.8  Variability in emotional/behavioral problems in boys with oppositional defiant...
A458 meet     0.85 Normative development of the Child Behavior Checklist Dysregulation Profile...
A459 not_meet 0.6  Autonomic arousal in anxious and typically developing youth during a stressor...
A460 not_meet 0.8  On the Neuroscience of Self-Regulation in Children With Disruptive Behavior...
A415 not_meet 0.8  Neural Rhythms of Change: Long-Term Improvement after Successful Treatment in...
```

**1 of 10, at confidence 0.8.** And because `not_meet` on an `include` criterion
routes to `RULE_REMOVES_BY_ABSENCE`, the consequence is direct: **114 of 116
records became `EXCLUSION_SUPPRESSED` and 1 more `UNCERTAIN`. The arm sent 115 of
116 records to a human.**

**EC-38 — "The paper is primarily a review or meta-analysis rather than an
empirical study" (EL, `exclude`).**

**Eighteen** of the 116 titles match
`\b(review|meta-analys\w*|metaanalys\w*|systematic|overview)\b`,
case-insensitive. EC-38 flagged **one** of the eighteen (A438). *(An earlier
draft of this section said sixteen; that regex ended `meta-analys\b`, which
does not match "meta-analysis". The corrected matcher adds A284 and A285 — both
titled "…: A meta-analysis" — which makes the result worse, not better.)*

It flagged four records whose titles carry none of those terms, and all four are
X012 nonlinear-dynamics papers:

```
A302  Dissection of the radical reactions linked to fetal hemoglobin...
A359  On the merits of extrapolation-based stiff ODE solvers for...
A366  The effect of temperature on generic stable periodic structures...
A389  Experimental and numerical investigation of backscattered signal...
```

A title keyword is a proxy for ground truth, not ground truth — a paper can be a
review without saying so, and "Systematic" in a title is not proof. The proxy is
stated so the number can be argued with, and two of the eighteen are arguably
not reviews (A110 *"…Subject Overview"*, A291 *"Toward a Taxonomy…"*). It does
not matter: **at least eight of the seventeen misses say "review" or
"meta-analysis" outright**, including *"Resting respiratory sinus arrhythmia and
posttraumatic stress disorder: A meta-analysis"* (A284), *"…A Systematic Review
and Meta-Analysis"* (A285) and *"…An updated systematic review and
meta-analysis"* (A425). 1 caught against 4 flagged from outside the set is not a
margin a better proxy rescues. Filed as **F-242**.

**These two are the strongest evidence in the wave that the LLM stages are not
doing the work they appear to do**, and they are visible only because `h3`'s
criteria happen to be checkable from a title. The criteria on every other arm
require reading the abstract, or domain knowledge, or both.


---

## 6. Premises corrected

Everything in the brief and the handoff was treated as a hypothesis. Sixteen
statements in committed prose are wrong or incomplete against the artefacts they
describe. They are listed so the next session inherits corrections rather than
repeating the checks.

| # | where | what it says | what the bytes say |
|---|---|---|---|
| 1 | handoff §1 | "`main` is at **`b95886b`**" | `62a1049` — the handoff's own commit, made after §1 was written |
| 2 | handoff §5, condition 4 | "any `quote_valid=False`" | fires on **828 of 931** verdict pairs (89.0%); see §6.2 |
| 3 | handoff §6 heading | "The three `quote_valid=False` cases" | 3 of **22** in the wave; see §6.3 |
| 4 | handoff §6 / F-218 row | "check the gaps in `live_v1/*_log.txt` against the per-call timings" | all 14 logs carry **zero timestamps**; see §6.4 |
| 5 | handoff §2 | "everything under `docs/data/wave17_arms/` is pinned `text eol=crlf`" | only `*.txt`, `*.csv`, `*.json` are. `git check-attr` on a `.md` there returns `text: auto`, `eol: unspecified` |
| 6 | handoff §6 | h0 "IL 8.43 s/call against EL 7.77" | the committed artefacts give **IL 8.50, EL 7.69** (`wall_seconds / calls_made`). The handoff's figures are most likely h0's first run, whose summaries were overwritten at `74bf295` |
| 7 | F-221 | "Every one of the five went `meet` → `not_meet`; none went the other way" | holds on wave 16; **contradicted by the wave-17 replication**, 2 of 9 counter-directional (§2.2) |
| 8 | F-221 | "Paraphrasing **IC-1**" | sound at IL (one LLM criterion); loose at EL, where two were reworded (§2.1) |
| 9 | spec, `h2` IC-26 | "Expected to cut 0" | cut **449 of 461**, and inverted the criterion (§5.1) |
| 10 | spec, `h2` EC-24 | branch 6 "emits **one** operand" | emits **two** (§5.1) |
| 11 | spec, `h4` H4-6 | "`RULE_REMOVES_BY_ABSENCE`, never auto-acted" | hit `RULE_REMOVES_BY_PRESENCE`; 6 verdicts were **auto-actable** (§5.4.1) |
| 12 | spec, `h4` H4-5 / H4-7 | "F-21's 20-char substance floor" / "near the 1500-char truncation bound" | the floor is on the model's quote; `trunc_chars` never touches a criterion (§5.1) |
| 13 | spec, `h3` EC-36 | "`equals ''` against a populated column" | the empty operand is dropped **before** any comparison (`evaluator.py:108-114` → `equals_missing_what`). The predicted UNKNOWN×463 held; the mechanism did not, and the consequence is that **EC-36 cannot exclude anything on any corpus** |
| 15 | handoff §4 | "Validation: **197** recorded samples, 0 drift aborts" for the 3.3 divisor | **176.** h0's 21 samples were recorded under the old 4.5 and are the data the floor was fitted *from*; see §6.5 |
| 16 | handoff §4 | worst margin "+11%" (h2) | **h0's is +2.41%** — 35 tokens from the drift abort — and h0 is absent from the validation table |
| 14 | F-231 row | "an EL/IL error here is a judgement on a relevant paper, not a failure to spot junk" | true of `h0` (0 off-topic of 32); **false of `h3`**, where 64 of 116 (55.2%) are off-topic against a 32.8% corpus base rate — its gate *enriched* off-topic mass 1.68× |

Plus two structural ones already stated in place: `intended_target` is registered
on all 70 intents and read by no code (§5), and the wave's "zero removals" is
policy as much as gate — 24 verdicts reached `ACTION_EXCLUDE` (§5.4.1).

### 6.1 The five stop conditions, audited against the committed artefacts

| # | condition | measured |
|---|---|---|
| 1 | any removal or auto-act — `OUT > 0` | **`OUT` = 0 in all 14 stage summaries.** But see §5.4.1: 24 verdicts reached `ACTION_EXCLUDE` and were declined by policy |
| 2 | any F-107 fallback — `request_shape != "json_schema"` | **`json_schema` in all 14.** Also `decisions_rejected` 0 and `fields_rejected` 0 in all 14 reports |
| 3 | any arm reaching its per-arm ceiling | **none.** Closest are `h0` and `h1` at 24 of 42 = **57.1%** (not `h4`, which is 56 of 112 = 50.0%); every arm's `declared_budget` equals its spec `call_ceiling_arm` |
| 4 | any `quote_valid=False` | **fires on 828 of 931 pairs. Unusable as written** — §6.2 |
| 5 | any `TokenEstimateDrift` | **none.** `anomaly_stops` is `[]` in all seven live manifests |

Four of the five are clean and one cannot be used.

### 6.2 Stop condition 4, as revised, would halt on 89% of all verdicts

The handoff retired the old condition — *"any non-null quote on a `not_meet`
verdict"* — for good reasons, and replaced it with **"any `quote_valid=False`"**.
The replacement has never been exercised, because no arm has run since it was
written. It is unusable:

| | n | of 931 |
|---|---|---|
| verdict pairs across all 7 arms, both stages | 931 | |
| `quote_valid = false` | **828** | 89.0% |
| …of which the quote is **empty** | 806 | 86.6% |
| …of which the quote is **non-empty** | **22** | 2.4% |
| `quote_valid = true` | 103 | 11.1% |

`quote_valid` is `_quote_in_text(quote, field_text)`, and an empty string is not
found in anything, so **every honest null quote records `quote_valid: false`**.
The v3 prompt asks for exactly that null on `not_meet` — which is the modal
verdict. The condition as written would have halted the very first arm on its
very first batch, on the behaviour the prompt requests.

The operative condition, the one the driver must actually have implemented, is
**"any `quote_valid=False` *with a non-empty quote*"**: 22 of 931, 2.4%. That
version is meaningful and should replace the text in the handoff before any arm
runs again.

**And the retired condition was the more precise instrument, not the less.**
Counting *non-null quote on a `not_meet` verdict* across all seven arms and both
stages gives **exactly four hits**, all on `h4` IL / H4-7 — A220, A221, A223
(`quote_valid=False`) and A228 (`True`). That is 0.43% of cells, and it is
precisely the population F-237 documents.

| condition | fires on |
|---|---|
| retired: non-null quote on a `not_meet` | **4 of 931** (0.43%) |
| replacement as written: any `quote_valid=False` | **828 of 931** (88.9%) |
| the intended property: `quote_valid=False` **and** non-empty quote | **22 of 931** (2.4%) |

The retirement was justified on contract grounds — the old condition halted on
behaviour `prompt.py:44` explicitly permits, and that reasoning is sound. But the
replacement is 200× less selective than the thing it replaced, and F-237's
supporting sentence — that `quote_valid=False` *"is the property that actually
indicates the model naming a field it did not quote"* — is false for **806 of the
828** cells it matches, which carry no quote at all.

### 6.3 F-237 is right about H4-7 and the handoff's heading is wrong about the wave

F-237's own arithmetic recomputes exactly (§5.4). What does not survive is the
handoff §6 heading calling those *"The three `quote_valid=False` cases"*. The
wave contains **22** non-empty invalid quotes, across five arms and both stages:

| arm | EL | IL |
|---|---|---|
| `h4_edge_shapes` | 2 (H4-6) | **10** — 3 on H4-7, **7 on H4-8** |
| `h8_pinned_target` | 1 (EC-2) | 3 (IC-1) |
| `h0_baseline` | 1 (EC-2) | 2 (IC-1) |
| `h1_paraphrase` | 0 | 2 (IC-1) |
| `h5_adversarial` | 1 (H5-4) | 0 |

The seven on **H4-8**, on the same arm and the same stage as F-237's three, were
not counted. Nor were the twelve on four other arms. **Two** of the 22 are the
prompt-echo fabrications described in §5.5 — the model returning the criterion's
own sentence, whole, as its evidence quote (`h5`/A140/H5-4 and
`h8`/A455/EC-2). Both were refused.

A third quote overlaps its criterion without being a fabrication, and is worth
recording separately because it is F-21's substance floor firing on live
evidence: `h4`/A223/H4-6 returned `meet` at confidence 0.9 with the quote
`"vagal tone"` — **`quote_valid: true`**, a genuine substring of the record, but
10 normalised characters against `SUBSTANCE_MIN_CHARS = 20`. `substance_ok`
refused it and the verdict fell to `UNCERTAIN`. That is the only place in the
wave where the 20-char floor, rather than the validity check, is what stopped a
removal.

The inertness argument is unaffected for F-237's three (the absence path does not
consult the quote) but does **not** generalise: `h0`/A281's invalid quote sits on
an `include` + `meet` verdict, which `RULE_KEEPS` decides on confidence alone.
There the model concatenated two non-adjacent keywords —
`"Heart rate variability; Emotional regulation"` from a `keywords` cell reading
`"Vagal tone; Psychology; Vagus nerve; Emotional regulation; … Heart rate
variability; …"` — and the record was **MET**, cleared into the pile. **The strict
quote gate protects against a wrongful removal. Nothing checks the quote behind a
wrongful keep.** That asymmetry is F-195's deliberate design; it is worth stating
because the pile a user reads is made of keeps.

### 6.4 F-218's prescribed test does not exist, and the candidate explanation is bounded

The handoff says to check "the gaps in `live_v1/*_log.txt` against the per-call
timings". Machine check over all fourteen logs:

```
h0_baseline_EL_log.txt      14 lines   timestamp matches: 0
h0_baseline_IL_log.txt       9 lines   timestamp matches: 0
… (all 14)                              timestamp matches: 0
```

Nine to fourteen lines each, no clock of any kind, no per-call record. **The only
timing in any committed wave-17 artefact is `wall_seconds` per stage and
`wall_seconds_total` per arm.** The test named in the handoff and in the F-218
row cannot be run against the evidence they point at.

What can be derived, `wall_seconds / calls_made`:

| arm | EL s/call | IL s/call | IL / EL |
|---|---|---|---|
| h0 | 7.69 | 8.50 | 1.10× |
| h1 | 7.28 | 7.58 | 1.04× |
| h2 | 6.93 | 8.25 | 1.19× |
| **h3** | **28.00** | **7.48** | **0.27×** |
| h4 | 7.95 | 9.39 | 1.18× |
| h5 | 8.82 | 8.22 | 0.93× |
| h8 | 7.63 | 9.26 | 1.21× |

Thirteen of the fourteen stage runs sit in **6.93–9.39 s/call**. h3's EL is the
lone outlier and carries an excess of about **492 s** over 24 calls.

The candidate explanation — Ollama unloading idle models, so an arm pays load
time on its first calls — would have to account for that 492 s. It is **bounded
but not falsified**: `h2_polarity`'s EL ran its entire 6-call stage in **41.6 s**,
so any per-run model load paid there was at most 41.6 s, an order of magnitude
too small. Whether h3's excess is concentrated in one call or spread across
twenty-four is **undecidable from the committed artefacts**, and will stay that
way until per-call timing is recorded. That instrumentation is the fix, and it is
the same shape as the `token_samples` fix F-236 already made for densities.

### 6.5 F-236's validation set is 176 samples, not 197 — h0's are on the old divisor

This is the wave's most load-bearing result and its validation pools two
instruments.

`74bf295` changed `CHARS_PER_TOKEN` from 4.5 to 3.3 and, in the same commit,
committed h0's re-run with the new `token_samples` instrumentation. The handoff
§4 then reports *"Validation: 197 recorded samples, 0 drift aborts"* over a table
of six arms — **h0 is not in that table, but its 21 samples are in the 197.**

`token_samples` records `(estimate, actual, items, criterion)` and **no divisor**,
so the mixture is invisible in the artefact. It is recoverable from the ratios:

| arm | n | `estimate/actual` |
|---|---|---|
| **`h0_baseline`** | **21** | **1.024 – 1.070** |
| `h2_polarity` | 12 | 1.109 – 1.207 |
| `h3_stage_stress` | 48 | 1.275 – 1.589 |
| `h4_edge_shapes` | 56 | 1.355 – 1.580 |
| `h5_adversarial` | 18 | 1.361 – 1.520 |
| `h1_paraphrase` | 21 | 1.388 – 1.452 |
| `h8_pinned_target` | 21 | 1.389 – 1.451 |

h0 sits in a band no other arm touches. The clinching arithmetic is h0 against
h1 — same corpus, same records, prompts within ~14 characters of each other:

```
h0 EL sample 1: {estimate: 2031, actual: 1902}
h1 EL sample 1: {estimate: 2759, actual: 1900}
estimate ratio 2759 / 2031 = 1.3584      4.5 / 3.3 = 1.3636
```

Two prompts **2 tokens apart in reality, 728 tokens apart in estimate**. h0's 21
samples were recorded under the **old** divisor 4.5; the other 176 under 3.3.
That also explains why `74bf295`'s own fit line reads *"wave17 RSA h0 n=21
density 4.52 .. 4.74"* — those are the observations the 3.3 floor was fitted
*from*, not observations that validate it.

Three consequences:

1. **The 3.3 divisor is validated by 176 samples, not 197.** The claim is still
   comfortably supported — the six post-calibration arms range 1.109–1.589, all
   conservative — but the stated n is wrong and the table and the total disagree
   with each other.
2. **h0's worst margin is +2.41%** (`estimate 1490, actual 1455` at EL), against
   the handoff's stated minimum of "+11%" for h2. h0 came within **35 tokens** of
   the zero-tolerance drift abort. Under the old divisor, which is exactly the
   near-miss that motivated the recalibration — but the handoff's validation
   table omits the arm entirely, so the closest approach in the wave is not in
   the record.
3. **Any future recalibration that pools all 197 samples fits a mixed
   instrument.** `token_samples` should record the divisor in force, the same way
   the summaries record `prompt_version` and `context_window`.

---

## 7. K5 — the product question: are they the right 32?

`h0_baseline` is the product run as a user would run it. Its deterministic chain
took 463 records to 423 at EH and to 32 at IH. Those 32 are the pile a person
reads. This section asks whether they are the right ones.

### 7.1 What the deterministic gate accomplished

The corpus carries **152 records** whose `parents` begins `X002` (science
education) or `X012` (nonlinear dynamics) — off-topic by construction, 32.8% of
the corpus. **Zero of them reached EL on `h0`.** Confirmed by set intersection,
and the same holds for `h1` and `h8`.

Across the seven arms the figure is entirely a property of the gate, not of the
corpus:

| arm | records at EL | off-topic reaching EL |
|---|---|---|
| `h0_baseline`, `h1_paraphrase`, `h8_pinned_target` | 32 | **0** (0.0%) |
| `h4_edge_shapes` | 69 | 1 (1.4%) |
| `h5_adversarial` | 29 | 4 (13.8%) |
| `h3_stage_stress` | 116 | 64 (55.2%) |
| `h2_polarity` | 12 | **12 (100%)** |

`h0`'s IC-4 (`respiratory sinus arrhythmia` OR `vagal` OR `heart rate
variability`) ANDed with IC-5 (`emotion` OR `dysregulation` OR `child` OR
`adolescent` OR `youth` OR `infant`) over title+abstract+keywords is doing all of
the topical work, and doing it perfectly on this corpus. **Two substring rules
removed 391 of 423 records and let through not one of the 152 known-off-topic
ones.** That is the strongest thing in the wave, and no LLM was involved in it.

### 7.2 What the pile actually contains

Three independent reviewers judged all 32 with different lenses — a
systematic-review methodologist applying the criteria literally, a
psychophysiologist judging on substance, and an adversarial auditor hunting
keyword false positives. Majority call per record:

| | n |
|---|---|
| CORRECT_INCLUSION | **10** |
| BOUNDARY | **14** |
| WRONG_INCLUSION | **8** |

**Unanimous CORRECT (7):** A187 *Heart Rate Variability as an Index of Regulated
Emotional Responding* · A219 *Sympathetic and parasympathetic responses to social
stress across adolescence* · A265 *Resting HRV predicts self-reported
difficulties in emotion regulation* · A275 *How heart rate variability affects
emotion regulation brain networks* · A276 *HRV indices as bio-markers of top-down
self-regulatory mechanisms* · A281 *Cardiac vagal control as a marker of emotion
regulation* · A431 *Facial EMG and heart rate responses to emotion-inducing film
clips in boys with disruptive behavior disorders*.

**Unanimous WRONG (5):** A014 *Influence of Olanzapine on QT Variability … in
Patients With Schizophrenia* (antipsychotic cardiac safety) · A053 *Effect of age
on long-term heart rate variability* (ageing methodology) · A222 *Autonomic
Nervous System Function in Infants and Adolescents: Impact of Autonomic Tests on
HRV* (normative test battery) · A227 *…adolescent chronic fatigue syndrome*
(clinical autonomic dysfunction) · A416 *A prospective study of heart rate and
externalising behaviours* (resting heart rate, not HRV, not a regulation index).

**Majority WRONG, one dissent (3):** A132 *Interactions Between Respiration and
Circulation* (a 1986 physiology handbook chapter — the origin of RSA as a
phenomenon, not a study of it as a regulation index) · A199 *Conditioned Pain
Modulation in Children and Adolescents* (admitted on `child`, about nociception)
· A220 *Heart rate and QT variability in children with anxiety disorders*
(cardiac electrophysiology).

**Every one of the eight is admitted by a true keyword match — the gate is not
malfunctioning, it is doing exactly what it says.** The operands that let each
one through:

| record | admitted by IC-4 | admitted by IC-5 |
|---|---|---|
| A014 | `vagal`, `heart rate variability` | `dysregulation` |
| A053 | `heart rate variability` | `child` |
| A132 | `respiratory sinus arrhythmia`, `vagal` | `infant` |
| A199 | `heart rate variability` | `child`, `adolescent` |
| A220 | `vagal`, `heart rate variability` | `child` |
| A222 | `heart rate variability` | `child`, `adolescent`, `infant` |
| A227 | `heart rate variability` | `dysregulation`, `adolescent` |
| A416 | `heart rate variability` | `child`, `adolescent` |

A053 is the pattern in miniature. Its IC-5 hit is the word *children* inside
*"24-h Holter ECG in 33 healthy human subjects (11 children and 22 adults)"* — a
sentence about sample composition in a paper on how HRV changes with age.
Substring matching cannot tell that apart from a study of children.

IC-4 ∧ IC-5 cannot distinguish a paper that *measures* HRV from one that *uses*
it as an index of emotion regulation. IC-1 is the criterion carrying that
distinction, and IC-1 is the LLM one — which is why §7.4 matters.

### 7.3 Two defects in the pile that no criterion could have caught

**A223 and A229 are the same paper.** Same title (*Personality profiles and heart
rate variability (vagal tone) in children with recurrent abdominal pain*), same
year, same venue (*Acta Paediatrica*), abstracts **98.95%** identical — under two
different DOIs, `10.1111/j.1651-2227.2001.tb02425.x` and
`10.1080/080352501750258685`, and two different `source_key`s. Deduplication
keyed on either cannot see it. **The pile of 32 is 31 distinct works,** and a
reviewer notices in seconds.

**It is not the only collision, and the corpus fails in both directions.** Ten
title-collision groups exist in the 463 records. Four are certain duplicates; the
other six are generic titles (*"Heart rate variability"*, *"Diagnostic and
statistical manual of mental disorders"*) that may legitimately name distinct
documents, and are not asserted either way. The four split by mechanism:

| pair | title | `source_key` | DOI | reached a stage? |
|---|---|---|---|---|
| A223 / A229 | identical | **differs** | differs | **yes — h0, h1, h4, h8** |
| A172 / A173 | identical | **identical** | differs by `//` | no |
| A174 / A175 | identical | **identical** | differs by `//` | no |
| A176 / A177 | identical | **identical** | differs by `//` | no |

The three `10.1037//` pairs differ only by a doubled slash, which `source_key`
normalisation strips — so `source_key` catches them and the DOI does not, the
exact inverse of A223/A229. **Only A223/A229 reached an LLM stage, and both
members reached, together, on four arms.** So `h0`/`h1`/`h8`'s 32 records are
**31 works** and `h4`'s 69 are **68**; `h2`, `h3` and `h5` are unaffected. Every
rate in this document over those four arms is therefore computed on a
denominator that counts one work twice. Filed as **F-243**.

It also yields a free determinism datum. The two landed in **different batches**
(A223 in batch 3, A229 in batch 4) and received the **same decision, confidence
and status** at both stages — but **different evidence**: A223's IL quote is from
the abstract and `quote_valid: false`; A229's is from the title and
`quote_valid: true`. Near-identical content gives a stable verdict and an
unstable self-report.

**Three of the 32 have no abstract at all** — A276, A281, A406 (119 of the 463
corpus records have none). They were screened anyway, on title and keywords, and
two of them were cleared:

```
A276  meet 0.85  field=title     quote_valid=true   -> MET  -> PASS_CLEAN
A281  meet 0.95  field=keywords  quote_valid=FALSE  -> MET  -> PASS_CLEAN
A406  not_meet 0.55                                 -> UNCERTAIN -> REVIEW
```

A281's "quote" is `"Heart rate variability; Emotional regulation"` — two real
terms from a `keywords` cell that reads *"Vagal tone; Psychology; Vagus nerve;
Emotional regulation; … Heart rate variability; …"*, concatenated out of order
and presented as a substring. It is invalid, and it did not matter: `include` +
`meet` is `RULE_KEEPS`, which consults confidence alone. **The strict quote gate
guards removals; nothing guards a keep.** This is precisely what `h6_no_abstract`
was designed to probe, and three records of `h0` already show its shape.

### 7.4 Did the LLM stages add value? On the pile it was given, yes

Cross-tabulating the model's IL verdict against the reviewers' majority call.
Read `EXCLUSION_SUPPRESSED` here as **"the model asked for this one out"** — at
IL every such verdict arrives by `RULE_REMOVES_BY_ABSENCE`, which declines the
removal unconditionally whatever the provider setting, so it is a flag for a
human and never a deletion:

| | model kept | model asked to remove | model undecided |
|---|---|---|---|
| **CORRECT_INCLUSION** (10) | **7** | 3 | 0 |
| BOUNDARY (14) | 5 | 8 | 1 |
| **WRONG_INCLUSION** (8) | **0** | **8** | 0 |

On the 18 records where the reviewers reach a decisive majority, the model agrees
on **15**, i.e. **83.3%**. More usefully for a person:

- **It asked to remove every single record the reviewers call a wrong inclusion —
  8 of 8, no false negatives.** All five unanimous-WRONG records are among them.
- **Nothing wrong slipped into the pile it cleared.** The 12 records it marked
  `PASS_CLEAN` are 7 correct inclusions and 5 boundary cases. A reviewer who
  read only the 20 flagged records would have auto-accepted no paper that any
  reviewer calls wrong.
- Its errors are the conservative kind: **3 correct inclusions were flagged**
  (A218, A219, A459) — pushed into a queue a human reads, not removed. A219 is
  the sharpest miss; its abstract opens *"Many transformations that occur in
  adolescence are related to emotion and emotion regulation"*, and IC-1 came back
  `not_meet` at confidence 0.8.

So the honest answer to *"does it do something"* is **yes, on this arm**: the
deterministic gate removed all 152 known-off-topic records and the LLM stage
separated the pile it was given with 83% agreement against three human reviewers
and no dangerous errors in the permissive direction.


### 7.5 The other half of the question: what the gate threw away

"Are they the right 32" has a second half the brief did not ask for and the
artefacts answer anyway. Decomposing the gate over the whole corpus:

| | n |
|---|---|
| records matching IC-4 (`RSA` ∨ `vagal` ∨ `heart rate variability`) | 149 of 463 |
| records matching IC-5 (`emotion` ∨ `dysregulation` ∨ `child` ∨ `adolescent` ∨ `youth` ∨ `infant`) | 112 of 463 |
| off-topic records failing IC-4 | **151 of 152** |
| off-topic records failing IC-5 | 150 of 152 |
| off-topic records passing IC-4 alone | **1** (A382, permutation entropy of cardiac signals) |

**IC-4 alone does the off-topic exclusion.** It admits 149 records containing
exactly one off-topic paper. The conjunction with IC-5 adds essentially nothing
on that side — both off-topic records carrying IC-5 vocabulary fail IC-4 anyway.
So §7.1's "two substring rules" is really *one* substring rule, and it works
because RSA/vagal/HRV is rare vocabulary that science-education and
nonlinear-dynamics papers do not use.

**IC-5's actual function is to cut on-topic material, and it cuts hard.** Of the
423 EH survivors, **117 pass IC-4 and are killed by IC-5 — and 116 of those 117
come from on-topic parents.** IC-5 removes 149 → 32 almost entirely at the
expense of relevant papers.

What it removed includes much of the field's canon:

```
A044  Respiratory sinus arrhythmia: Autonomic origins, physiological mechanisms…
A025  Cardiac vagal tone: A physiological index of stress
A209  Claude Bernard and the heart–brain connection (neurovisceral integration)
A016  Respiratory Sinus Arrhythmia and Cardiovascular Responses to Stress
A017  Cardiac Vagal Tone in Generalised Anxiety Disorder
A042  A meta-analysis of heart rate variability and neuroimaging studies
A057  Vagal influence during worry and cognitive challenge
A190  Heart rate variability and its relation to prefrontal cognitive function
A240  Heart rate variability as a transdiagnostic biomarker of psychopathology
A266  Heart rate variability and cognitive processing
A290  Autonomic dysfunction in PTSD indexed by heart rate variability
A444  Understanding heterogeneity in conduct disorder: psychophysiology review
```

Every one passes IC-4 and fails IC-5, because none happens to contain the literal
strings `emotion`, `dysregulation`, `child`, `adolescent`, `youth` or `infant`.
**Each was checked individually by evaluating both criteria over the record's own
title, abstract and keywords, and the author names are read from the corpus's
`first_author` column. These are removal measurements and canon judgements —
none of them except A044 is claimed to be a seed.**

**A044 is not merely canonical — it is entry [1] of the corpus's own seed
bibliography.** `samples/README.md` names
`samples/20260122_1654_rsaSampleReferences.txt` as *"the RSA seed
bibliography"*, and its first entry reads:

```
[1] Berntson GG, Cacioppo JT, Quigley KS. Respiratory sinus arrhythmia:
    autonomic origins, physiological mechanisms, and psychophysiological
    implications. Psychophysiology. 1993;30(2):183-196.
```

A044's record: `first_author` **Gary G. Berntson**, `year` **1993**, `venue`
**Psychophysiology**, title exactly that. It has a 1,051-character abstract
containing none of IC-5's six words. **The corpus was built outward from this
paper, and the criteria deleted it at IH.**

**A full seed-to-record mapping is not attempted, and the reason is worth
recording.** The corpus carries no seed identifier, so the mapping has to come
from titles — and title matching is unsafe here: **A117**, *"Respiratory Sinus
Arrhythmia"* (Hayano 1996, *Circulation*), is a substring of **five different
seed references**, and two different fuzzy-matching passes produced two
contradictory seed tallies before this was noticed. Only two identifications are
made, both by hand and both agreeing on first author, year, venue and exact
title: **seed [1] = A044** (cut by IC-5) and **seed [6] = A187**, Appelhans and
Luecken 2006, *"Heart rate variability as an index of regulated emotional
responding"* — which reached EL/IL and is one of the two records the pipeline
then tried to remove (§7.6).

And the symmetric failure exists too: **A208, *"A model of neurovisceral
integration in emotion regulation and dysregulation"*, is invisible to IC-4** —
its abstract is empty and no keyword carries a vagal token — so a paper whose
title states the review's exact construct never reaches any stage.

The pile is therefore right in the sense that little junk got in, and wrong in
the sense that a great deal of the target literature never arrived. **A reviewer
reading these 32 would not know that 117 IC-4-matching papers were removed by a
six-word substring list.** Nothing in the product surfaces that; the funnel
reports `IC-5 failed 311` and no more.

### 7.6 The removals the pipeline attempted were its two best papers

§5.4.1 counted 24 gate-accepted removals across the wave. On `h0` there are
exactly **two**, and both are `EC-3` — *"The paper's primary focus is clinical
arrhythmia diagnosis rather than psychological function"*:

```
A187  EC-3  meet 0.9  quote_valid=TRUE  -> SUPPRESSED
      title: "Heart Rate Variability as an Index of Regulated Emotional Responding"
      quote: "Heart Rate Variability as an Index of Regulated Emotional Responding"

A275  EC-3  meet 0.9  quote_valid=TRUE  -> SUPPRESSED
      title: "How heart rate variability affects emotion regulation brain networks"
      quote: "How heart rate variability affects emotion regulation brain networks"
```

**A187 and A275 are two of the seven records all three reviewers unanimously call
CORRECT_INCLUSION, and A187 is entry [6] of the corpus's own seed bibliography**
(Appelhans and Luecken 2006; see §7.5). The model asserted that each is primarily
about clinical arrhythmia diagnosis, at confidence 0.9, and offered as proof a
verbatim quote of a title that says the opposite.

Both quotes are `quote_valid: true` — they *are* exact substrings of the record.
So the strict presence gate accepted both and returned `ACTION_EXCLUDE`. **The
only thing that stopped the removal was `exclusion_policy: flag_only`.**

This is the sharpest limit on F-195's gate found anywhere in the wave, and it is
structural, not a tuning problem: **the gate verifies that a quote exists in the
record. It cannot verify that the quote supports the verdict.** A title quoted
verbatim is always valid, always clears the 20-char floor, and can be attached to
any claim at all.

Meanwhile EC-3 returned `not_meet` on **A014** (olanzapine, QT variability,
schizophrenia) and **A220** (heart rate and QT variability in anxious children) —
the only two records in the pile where an arrhythmia-focus exclusion would have
been correct. All four of EL's `meet` decisions in this arm are wrong; the two
that were refused (A199, A455) were refused on quote validity, not on merit.

**That sits directly against §7.4's positive result, and the contrast is the
point.** The same model, run, records and settings produced a stage that got all
four of its committed decisions wrong (EL) and a stage that flagged 8 of 8 wrong
inclusions (IL). **No single statement about "the LLM stage" survives both**, and
any framing that says errors get caught at the LLM stage flattens exactly this.
Filed as **F-244** at Medium, with n=4 stated and no generalisation drawn.

**With `allow_exclusion` enabled, this run removes A187 and A275 and the human
never sees them.** Precisely two records, not three: A219 — the third correct
inclusion the pipeline wanted out — was suppressed at IL by
`RULE_REMOVES_BY_ABSENCE`, which `verdict_gate.py` declines *"unconditionally,
whatever the setting"*. The absence rule is what protects it, and the absence
rule is the one no provider dialog can switch off.

### 7.7 The evidence behind the pile is thin

Counting quotes across `h0`'s 96 verdict cells:

| stage | empty quote | non-empty, valid | non-empty, invalid |
|---|---|---|---|
| EL (64 cells) | **61** | 2 | 1 |
| IL (32 cells) | 20 | 10 | 2 |

All 20 of IC-1's `not_meet` verdicts — the ones that put 19 records into the
review pile — are **unquoted assertions of absence**, which the v3 prompt
permits and the absence rule does not examine. Their confidences are
`{0.55: 1, 0.6: 1, 0.7: 1, 0.8: 16, 0.9: 1}`: **16 of 19 sit at a flat 0.8**, so
the confidence field carries almost no triage information on the exclusion
branch. A reviewer sorting the pile by model confidence would be sorting noise.

### 7.8 EL's excluding verdicts across all three arms: 0 correct of 9

§7.6 reported EL's four `meet` decisions on `h0` and noted that the same
comparison on `h1` and `h8` was available for free. It was taken. `h1` and `h8`
ran the **same 32 records** through the **same two EL criteria** — `h1`
paraphrases them, `h8` changes only a `target` hint — so the three arms together
give **16 arm-level excluding verdicts on 9 distinct (record, criterion)
pairs**, EC-2 ten and EC-3 six.

**Precision: zero.** Three independent judges — a word-by-word literalist, a
psychophysiologist, and an adversarial steelman explicitly instructed to build
the strongest case *for* each exclusion — graded all nine pairs:

| judgement | pairs |
|---|---|
| WRONG, unanimous | **8** |
| DEFENSIBLE (steelman only; the other two called it wrong) | **1** — A052/EC-3, cardiology-adjacent |
| CORRECT | **0** |

So **15 or 16 of the 16 arm-level verdicts are wrong and none is right.**

**EC-2's true-positive set on this pile is empty.** Its second clause — *"with no
human participants"* — is a factual test the abstracts settle, and 26 of the 32
records state a participant count outright (A199 n=133, A224 n=48, A455 n=151,
A014 n=15+controls, …). All **ten** EC-2 `meet` verdicts are false positives by
construction. Six of the ten come from `h1_paraphrase` alone: the paraphrase
added four exclusions no other arm produced.

**Recall: 0 of 6.** A014 (olanzapine, QT variability, schizophrenia) and A220
(heart rate and QT variability in children with anxiety disorders) are the two
records for which an arrhythmia-focus exclusion is arguable. **EC-3 returned
`not_meet` on both, on all three arms** — six opportunities, zero hits, verified
directly from the three `_EL_FULL.csv` files. A014's only excluding verdict came
from EC-2, the wrong criterion.

**And the errors are inverted, not merely wrong.** EC-3's three `meet` records
are A187, A275 and A052; the first two are in the seven-record unanimous
CORRECT_INCLUSION set. The evidence they carry is the finding:

```
h0 / A187   IC-1 (INCLUDE) meet 0.95  quote "Heart Rate Variability as an Index
                                             of Regulated Emotional Responding"  span [0,36]
            EC-3 (EXCLUDE) meet 0.90  quote  ...the same string...              span [0,36]

h0 / A275   IC-1 meet 0.85  quote "How heart rate variability affects emotion
                                   regulation brain networks"
            EC-3 meet 0.90  quote  ...the same string...
```

**The byte-identical quote, at the same span, offered as proof that the paper
reports HRV as an index of emotion regulation and as proof that its primary
focus is clinical arrhythmia diagnosis rather than psychological function.** Both
carry `quote_valid: true`, because the string exists, and the gate accepted both
— which is §7.6's point at its sharpest: a substring check cannot distinguish
evidence from its own negation. The same pattern recurs on `h8`/A275, and on
`h8`/A187 EC-3 quotes the abstract sentence *"HRV analysis is emerging as an
objective measure of regulated emotional responding"* as proof of an arrhythmia
focus.

**What this does and does not license.** It raised **F-244** from Medium to High.
It does not license "EL is unreliable" as a general claim: 16 verdicts fall on 8
records and 2 criteria, and the three arms are not three independent samples —
they share a corpus, a record set, and (for `h0`/`h8`) byte-identical criterion
text. **The defensible unit is the 9 distinct pairs, and the defensible claim is
that on this pile EL's excluding verdicts were correct 0 times out of 9 while its
recall on the intended targets was 0 of 2.** Set against IL's 15 of 18 on the
same records in the same runs, the conclusion is not about "the LLM stage" — it
is that the two stages must be reported separately.

### 7.9 The caveats that must travel with all of this

1. **It is one arm on one corpus.** `h3` shows the same model, on criteria
   checkable from a title, getting **1 of 10** paediatric-population calls right
   and **1 of 18** review/meta-analysis calls right (§5.6). The 83% is not a
   property of the product.
2. **Wording moves it more than the signal is wide.** `h1` is the same eight
   criteria in synonymous English, and it cut the auto-accept pile from **10 of
   32 to 5 of 32** (§2.4). A result that survives one paraphrase at 83% and
   halves under another is not yet a stable instrument.
3. **The reviewers were three model instances with different prompts, not three
   people.** They agreed unanimously on 12 of 32 and by majority on all 32, and
   the pattern they found is corroborated by facts no reviewer supplied — the
   duplicate, the empty abstracts, the zero off-topic. But this is a
   cross-checked reading of the pile, not an adjudicated human gold standard, and
   the 83% figure should be quoted with that attached.

---

## 8. Candidate findings — list only

Following wave 16c's convention: observed, then adjudicated by the maintainer.
**Adjudication is complete for all 24.**

| outcome | candidates | rows |
|---|---|---|
| **filed as their own row** | #1, #2, #3, #5, #6, #7, #11, #12, #17 | `F-238` … `F-246` |
| **folded into an existing row** | #8 → F-238 · #10, #20 → F-237 · #19 → F-236 · #22 → F-246 · #23 → F-221 | — |
| **deliberately not filed** | #4, #9, #13, #14, #15, #16, #18, #21, #24 | recorded in §8.1 |

The register reads **243 rows**, next free **F-247**, 40 machine cells verifying.

**F-244 was raised Medium → High** once its own recommended next step was taken:
extending the EL analysis to `h1` and `h8` cost zero calls and took it from n=4
to **16 arm-level verdicts on 9 distinct pairs, 0 of them correct**, with EC-3
never firing on either of the two records it was written to catch (0 of 6). See
§7.8.

### 8.1 The nine that were deliberately not filed, and why

Nine candidates were adjudicated as **not warranting a register row**. They are
instances of a filed row, measurement gaps with no defect behind them, or
observations with no remedy to propose — and nine more rows would dilute a
register that exists to decide what to work on. They are recorded here so the
decision is visible and re-openable rather than forgotten.

| # | observation | why it is not a row |
|---|---|---|
| **#4** | 16 of 19 IL `not_meet` confidences sit at a flat 0.8, so confidence carries no triage information on the exclusion branch | an observation with no remedy: the field is the model's, and nothing in the product claims it is a ranking signal. Becomes a row the moment anything sorts a review pile by it |
| **#9** | `intended_target` is registered on all 70 spec intents and read by no code | a defect in this wave's own experiment spec, not in the product. All 52 landed targets were checked by hand and matched (§5) |
| **#13** | an absence-*phrased* criterion does not reach `RULE_REMOVES_BY_ABSENCE`; only its `type` cell decides | criterion-authoring hazard, and the mechanism is already stated in F-241's fix cell. No code is wrong |
| **#14** | a "has no X" criterion drops its empty operand and can never exclude on any corpus | an instance of **F-240**'s class — the translator emitting a rule that cannot do what its sentence says. Carried in that row rather than duplicated |
| **#15** | identical aggregate counts hid a two-record swap (`h0` vs `h8` at IL) | a method warning about reading `summary.json` alone, already stated in §3.2 and in F-227's evidence. Nothing to fix in the product |
| **#16** | the `target` hint changes gate outcomes, not just the reviewer's reading | strengthens **F-227**, which is open and already carries it; a second row would split one finding |
| **#18** | no per-call timing exists in any artefact, so F-218's prescribed test cannot be run | a measurement gap, folded into F-236's fix cell as the `token_samples` precedent. F-218 already records that it is not reproducing |
| **#21** | `EXCLUSION_SUPPRESSED` is two different outcomes and reports pool them | stated in F-221's fix cell and in F-238's evidence; it is a reporting convention, not a defect |
| **#24** | the `h0` replicate is a real control and survives only because git kept the first commit | a note for the 17e freeze, not a finding. Recorded in §1 |

Ordered by what they would change, not by discovery order.

1. **The strict evidence gate cannot tell whether a quote *supports* the verdict.**
   On `h0`, EC-3 returned `meet` at confidence 0.9 on A187 (*"Heart Rate
   Variability as an Index of Regulated Emotional Responding"*) and A275 (*"How
   heart rate variability affects emotion regulation brain networks"*),
   asserting each is primarily about clinical arrhythmia diagnosis, and offered
   as evidence a **verbatim quote of the record's own title** — text that says
   the opposite. Both are `quote_valid: true`, both cleared the 20-char floor,
   both returned `ACTION_EXCLUDE`. `flag_only` is the only thing that stopped
   the removal. A title quoted verbatim is always a valid substring, so this is
   structural, not tuning. These are two of the seven records all three
   reviewers unanimously call correct inclusions. (§7.6)

2. **A short keyword list can delete the target literature without saying so.**
   `h0`'s IC-5 removes **117 records that match IC-4, 116 of them on-topic**,
   including *Respiratory sinus arrhythmia: autonomic origins* (A044),
   *Cardiac vagal tone: a physiological index of stress* (A025), Thayer's
   neurovisceral-integration papers (A209, A190), and *HRV as a transdiagnostic
   biomarker of psychopathology* (A240) — none of which happens to contain the
   literal strings `emotion`, `dysregulation`, `child`, `adolescent`, `youth` or
   `infant`. The funnel reports `IC-5 failed 311` and nothing else. Meanwhile
   IC-4 alone already excludes **151 of the 152** off-topic records, so the
   conjunction buys almost no precision for that recall cost. (§7.5)

3. **EL got every decision wrong on the anchor arm.** All four `meet` verdicts
   across EC-2 and EC-3 on `h0` are wrong (A187, A275, A199, A455), and EC-3
   returned `not_meet` on A014 and A220 — the only two records where an
   arrhythmia-focus exclusion would have been right. Two were stopped by quote
   validity and two by flag-only; none by being correct. (§7.6)

4. **Confidence carries no triage information on the exclusion branch.** All 20
   of IC-1's `not_meet` verdicts on `h0` are unquoted, and their confidences are
   `{0.55:1, 0.6:1, 0.7:1, 0.8:16, 0.9:1}` — 16 of 19 at a flat 0.8. A reviewer
   sorting the review pile by model confidence is sorting noise. (§7.7)

5. **The free-text translator can silently invert a criterion.** `h2`'s IC-26,
   *"The paper was written in a language other than Portuguese"*, harmonises to
   `in_list lang ["A","Portuguese"]` — which admits **only** Portuguese. It cut
   449 of 461 records and delivered the exact complement of its meaning. The
   validator returned clean and the linter returned `[]`. A user gets no signal
   of any kind. (§5.1)

6. **Negation-phrased LLM criteria are answered as though un-negated.** On a
   population with unambiguous ground truth, EC-23 (12/12), EC-28 (12/12) and
   IC-22 (10/12) all returned the inverse of the correct answer; only the
   "something other than" phrasing survived. The failure is silent and its
   direction depends on the criterion's `type` — it cleared everything at EL and
   flagged everything at IL. (§5.2)

7. **The LLM stages' substantive accuracy is poor where it can be checked.**
   `h3`'s IC-33 identified 1 of 10 records whose title explicitly names a
   paediatric population; EC-38 identified 1 of 18 whose title explicitly says
   review/meta-analysis, while flagging 4 that say neither. Consequence: 115 of
   116 records routed to human review. (§5.6)

8. **The wave's "zero removals" is policy as much as gate.** 24 verdicts across
   six arms reached `ACTION_EXCLUDE` — passed the strict presence gate,
   validated quote, 20-char floor, over threshold — and were stopped only by
   `exclusion_policy: flag_only`. `OUT` is 0 in all 14 summaries and that has
   been reported; the 24 never has. It is the number a maintainer needs before
   permitting exclusion for this provider. (§5.4.1)

9. **`intended_target` is registered on all 70 intents and read by no code.**
   `landings_vs_intent`'s `match: true` attests to stage and operator only. For
   `llm` rows the registered target is not enforceable even in principle, because
   the prompt ships title+abstract+keywords regardless. (§5)

10. **Stop condition 4 as revised would halt on 89% of all verdicts.** "Any
   `quote_valid=False`" fires on 828 of 931 pairs, 806 of them the honest null
   quote the v3 prompt asks for. The operative form is "…with a non-empty
   quote": 22 of 931. This has never been exercised and would halt the first
   batch of the next arm. (§6.2)

11. **A wrongful keep is unguarded.** `RULE_KEEPS` decides on confidence alone, so
   an `include` + `meet` verdict enters the clean pile whatever its quote.
   `h0`/A281 did exactly that on a fabricated (non-contiguous) keyword quote,
   with no abstract in the record. F-195's asymmetry is deliberate; the product
   consequence — the pile a user trusts is made entirely of unguarded keeps —
   has not been stated. (§7.3)

12. **Duplicate works reach the pile under distinct DOIs.** A223 and A229 are one
   paper (same title, year, venue; abstracts 98.95% identical) under
   `10.1111/j.1651-2227.2001.tb02425.x` and `10.1080/080352501750258685`. The
   32-record pile is 31 distinct works. (§7.3)

13. **An absence-*phrased* criterion does not reach the absence rule.**
   `GATE_TABLE` keys on `(type, decision)`; phrasing is irrelevant. `h4`'s H4-6
   was authored to demonstrate `RULE_REMOVES_BY_ABSENCE` and demonstrated
   `RULE_REMOVES_BY_PRESENCE` instead. This is a criterion-authoring hazard, not
   a code defect. (§5.4.1)

14. **A "has no X" criterion can never exclude on any corpus.** `h3`'s EC-36
    harmonises to `equals doi` with **zero** operands; `evaluator.py:108-114`
    drops falsy operands before the predicate and returns `equals_missing_what` →
    UNKNOWN. On a corpus where records genuinely lack a DOI they return MISSING —
    still never FAILED. (§6, row 13)

15. **Identical aggregate counts can hide a changed pile.** `h0` and `h8` have
    byte-identical IL count vectors and swap two records (A273 ↔ A276). Any
    cross-arm claim built on `summary.json` alone is unsound. (§3.2)

16. **The `target` hint changes gate outcomes, not just the reviewer's reading.**
    18 inserted characters relocated 71% of the model's self-reported evidence
    field, and through `valid_quote` — computed against the field the model
    *names* — moved records into and out of the review pile at both stages. This
    is stronger than F-227's open row states. (§3.3, §3.4)

17. **Empty-abstract records are screened and cleared on title/keywords alone.**
    3 of `h0`'s 32; 119 of the corpus's 463. Two were cleared, one on an invalid
    quote. (§7.3)

18. **No per-call timing exists in any artefact**, so F-218's prescribed test
    cannot be run and h3's 492 s excess cannot be attributed. The fix has the
    same shape as F-236's `token_samples`. (§6.4)

19. **F-236's validation set is 176 samples, not 197.** h0's 21 `token_samples`
    were recorded under the old divisor 4.5 — they are the observations 3.3 was
    fitted from, not observations that validate it. `token_samples` records no
    divisor, so the mixture is invisible in the artefact and any future
    recalibration that pools all 197 fits a mixed instrument. h0's worst margin,
    **+2.41%**, is the closest approach to the drift abort in the wave and does
    not appear in the handoff's validation table. (§6.5)

20. **The retired stop condition was 200× more selective than its replacement.**
    Non-null quote on a `not_meet` fires **4 times in 931 cells**; "any
    `quote_valid=False`" fires **828**. The retirement's contract reasoning is
    sound; the replacement is not. (§6.2)

21. **`EXCLUSION_SUPPRESSED` is two different outcomes and the reports pool
    them.** Classifying every suppressed record by the decliner its own
    `reason_summary` names gives **zero mixed cells**: all 24 EL suppression
    verdicts are `flag_only` (policy-contingent, they would be removals if
    `allow_exclusion` were set) and all 283 IL suppression verdicts — on 282
    records, one `h2` record being suppressed by two criteria — are `absence`
    (no setting can permit them).
    A "review pile" figure that adds the two is adding a number a setting can
    change to one it cannot. (§5.4.1, §6.1)

22. **The model names `abstract` as its evidence field on records that have no
    abstract** — 25 cells across the run arms, 18 of them carrying a decisive
    status. (§9)

23. **F-221's unidirectionality does not replicate.** Recorded against the row,
    which is otherwise reproduced exactly. (§2.2)

24. **The h0 replicate is a real control and was nearly lost.** Two executions,
    byte-identical verdict tables, 0 of 96 pairs differing. It survives only
    because git kept the first commit; the freeze should keep both runs under
    distinct names rather than overwriting in place. (§1)

---

## 9. The last three arms

Run at wave 17e after §7.8's analysis, detached, `--out` explicit, models
explicit per stage, cache off. **267 calls, 3,221 s, zero removals.**

| arm | calls / budget | wall | EL counts | IL counts | stop conditions |
|---|---|---|---|---|---|
| `h6_no_abstract` | 56 / 112 | 493 s | 135 clean · 1 flagged · 3 suppressed | 19 clean · 5 review · 115 suppressed | **all clear** |
| `h9_batch1` | 96 / 192 | 821 s | 32 clean · 0 · 0 | 5 clean · 0 · 27 suppressed | **all clear** |
| `h7_loose` | 115 / 228 | 1,908 s | 155 clean · 15 flagged · 19 suppressed | 33 clean · 5 review · 151 suppressed | **condition 4 tripped** (§10.4) |

`OUT` is 0 on all six stages, `request_shape` is `json_schema` on all six, no arm
passed 51% of its ceiling, and no `TokenEstimateDrift` fired anywhere.

### 9.1 `h9` — batch size moves the result as much as rewriting every criterion

`h9` is `h0`'s criteria and `h0`'s 32 records at `batch_size: 1`. Everything else
is byte-identical — same `criteria_sha256` (`e4640ac4…`), model, endpoint,
temperature 0.0, `prompt_version`, `trunc_chars`, `context_window`.

| | h0 (batch 5) | h9 (batch 1) |
|---|---|---|
| EL outcomes | 27 clean · 3 flagged · 2 suppressed | **32 clean · 0 · 0** |
| IL outcomes | 12 clean · 1 review · 19 suppressed | **5 clean · 0 · 27 suppressed** |
| criterion pairs differing | — | **5 of 64 (EL), 11 of 32 (IL)** |
| **cleared at BOTH stages** | **10 of 32** | **5 of 32** |

**A performance setting moved the unaided-clearance pile by exactly as much as
rewording all eight criteria did** (`h1`, §2.4: also 10 → 5). And the two sets of
survivors barely overlap — `h0` clears
{A216, A223, A229, A265, A276, A281, A284, A285, A292, A431}, `h9` clears
{A187, A265, A273, A281, A406}: **two records in common out of thirteen.**

At EL every one of the five flips runs toward `PASS_CLEAN`, and **that includes
A187 and A275** — the two records §7.6 shows the pipeline trying to auto-remove.
Whether the product attempts to delete the corpus's seed [6] paper depends on the
batch size.

**What this does NOT show is F-215's mechanism.** F-215 is about `_absorb`
silently dropping verdicts whose `a_id` is out-of-batch or duplicated. Nothing
was dropped on either arm: `answered` 64/64 and 32/32, `no_answer` 0, `failed` 0,
`decisions_rejected` 0, `fields_rejected` 0. **The bookkeeping was clean and the
judgements differed anyway** — the model answers differently when it sees five
records at once than when it sees one. F-215's fix is still worth doing and would
not have caught this. Recorded in F-215's row.

### 9.2 `h9` — and the density gradient F-236 was fitted on is not there

`h9` was named as the wave's remaining drift risk: its prompts are the smallest
anywhere, and F-236's reasoning is that **small prompts are denser**.

**Measured: 64 EL samples, actual prompt tokens 327–699, implied density
4.11–4.97, median 4.57.** That is the band of the *large*-prompt arms (h1
4.51–4.74, h8 4.52–4.74) and far above h2's 3.55, the single densest point the
3.3 floor was fitted from. Worst margin **+24.67%**. **Zero drift aborts.**

So the predicted gradient does not exist at the small end, and **h2's 3.55 is not
a size effect** — h9's prompts are smaller and markedly less dense. The
calibration is unaffected and still safe; the mechanism it was chosen on is
wrong, and whatever makes h2 dense remains unidentified. Recorded in F-236.

### 9.3 `h6` — absence of evidence is read as evidence of absence

32 of h6's 139 records have no abstract at all, and both its LLM criteria ask
about abstract content.

- **The registered intent is falsified in the half it was written about.** H6-3's
  rationale says absence *"should route to UNCERTAIN, never to a removal"*. The
  second half held — nothing was removed. **The first did not: 30 of the 32 went
  to `EXCLUSION_SUPPRESSED`, 1 to `REVIEW`, and 1 was cleared.** Abstract-less
  records were suppressed *more* often than records with an abstract — **93.8%
  against 79.4%**.
- **56 of the 64 cells on abstract-less records report `field=abstract`** (29 of
  32 at EL, 27 of 32 at IL), every one of the IL cells with an empty quote.
- **Confidence does not know.** EL mean 0.803 empty against 0.814 present; IL
  0.819 against 0.820. The model gives no signal that its evidence is missing.

Recorded in F-246, which was filed as an open question one commit earlier
specifically so this would land in it.

### 9.4 `h7` — the discrimination result at n=47, and why condition 4 fired

h7 admits 189 records, **47 off-topic by construction** (`parents` X002/X012).
This is the only population in the wave where a correct verdict is knowable
rather than judged.

**IL (`include`, H7-7) — the answer to "does it do something": yes.**

- **47 of 47 off-topic records flagged. 100%.** None reached `PASS_CLEAN`.
- Its cleared pile of **33 contains zero off-topic records**, against **8.2
  expected by chance**.
- End to end, **23 records cleared both stages and not one is off-topic**.

**EL (`exclude`, H7-5/H7-6) — the answer on the other side: no.**

- **19 records reached `EXCLUSION_SUPPRESSED`** — they passed the presence gate
  and are auto-actable. **Only 6 of the 19 are off-topic. 13 are on-topic records
  EL asked to delete. Precision 31.6%.**
- H7-5 was authored as *"the criterion that should reject the X012 computational
  mass"*. It returned `not_meet` on **32 of the 47** it was written for, while
  returning `meet` on 9 on-topic records.

**So the stage that cannot delete is 100% precise on what it clears, and the
stage that can delete is 31.6% precise on what it would remove.** That is §7.8's
finding at n=47 with ground truth by construction instead of 9 judged pairs, and
it is why F-244 is High.

**Condition 4 fired, correctly, and h7 is the last arm so nothing was left
unrun.** Ten excluding verdicts reached the presence gate carrying a non-null
quote that does not validate, and **all ten were refused to `UNCERTAIN`** — among
them three more prompt-echo fabrications (A090, A104, A379) quoting the
criterion's own sentence back as evidence. The gate did exactly its job against
quotes that do not exist in the record. It remains blind to the case §7.6
documents, where the quote does exist and does not support the verdict.

> **On the stop condition itself.** As written — *any `quote_valid=False`* — it
> fires on 828 of 931 cells and would have halted h6 immediately. Narrowed to the
> acting path (an `exclude` criterion answered `meet`, i.e. a verdict that
> reached `RULE_REMOVES_BY_PRESENCE`) it fires on 3 of the wave's first 931 cells
> and on 10 of h7's — a real tripwire rather than base-rate noise. h6 and h9
> cleared it; h7 did not, on its last arm, after completing.


---

## 10. What the analysis predicted for the three arms, and what they did

*Written before they ran, kept unedited as the record of a prediction, with the
outcome appended. §9 is the measurement.*

**Scorecard.** `h9` — **held and then some**: the noise floor made it a clean
batch-size experiment, and it produced a larger effect than F-215 anticipated
(§9.1), while the density risk it was named for did not materialise (§9.2).
`h6` — **the re-aim was right**: the keep side was where the action was, and
the registered "route to UNCERTAIN" expectation was falsified 30 times of 32
(§9.3). `h7` — **right about the question, wrong about which stage would
answer it**: the prediction was that h7 would test discrimination, and it did,
but the split fell between IL (100% on 47) and EL (31.6% on 19) rather than
being a property of "the LLM stage" (§9.4).

### 10.1 The original pre-run notes

The brief's premise — that analysing the free half first might change what the
last three arms should measure — holds for all three.

**`h9_batch1` — strengthened, run it as designed.** It is still the only
measurement of F-215, and it is now a *better* experiment than when it was
written: §1 establishes that this stack is bit-reproducible at batch 5 across two
full executions, 0 of 96 pairs differing. So any h0-vs-h9 difference is
attributable to batch size and nothing else, with a measured control rather than
an assumption. The drift risk on its 1,296–3,004-char prompts is unchanged and
should still be allowed to happen.

**`h6_no_abstract` — re-aim it, and it already has a 122-instance baseline.**
Its registered intent is that absence of an abstract *"should route to UNCERTAIN,
never to a removal"*. The run arms have already produced **122 record-stage
instances of an abstract-less record at an LLM stage** — 48 distinct records,
across six of the seven arms (h3 54, h4 40, h2 10, h0/h1/h8 6 each). Nobody has
counted them. Their outcomes:

```
EL:  PASS_CLEAN 55   EXCLUSION_SUPPRESSED 3   PASS_FLAGGED 3
IL:  EXCLUSION_SUPPRESSED 51   PASS_CLEAN 5   REVIEW 5
```

Two things follow. **Removals are not the failure mode** — 51 IL suppressions
already happened on abstract-less records, and none of them was a removal because
the absence rule declines unconditionally. And there is a failure mode the intent
does not anticipate at all:

```
self-reported evidence field on those 181 cells:  title 140, keywords 16, abstract 25
cells naming field='abstract' on a record whose abstract is the empty string:  25
   ...of which carry a decisive status (MET or SUPPRESSED):                    18
```

**Twenty-five times the model named `abstract` as its evidence field on a record
that has no abstract, and eighteen of those decided the record.** Nothing catches
it: `RULE_KEEPS` does not consult evidence, and `RULE_REMOVES_BY_ABSENCE` does
not either. h6 should be aimed at the keep side and at field-attribution honesty,
with these 122 instances as its control.

**`h7_loose` — its question has been half-answered, badly, and it is now the most
valuable unrun arm.** `h7` exists to push off-topic mass into the LLM stages.
**Confirmed from the artefacts rather than from the spec's prose:** replaying
h7's deterministic chain in-process (dry guard installed, zero calls) gives 463
to EH 423 to IH **189 survivors, of which 47 carry `parents` X002 or X012 =
24.9%** — X002 17, X012 30 — matching its `expected_chain` and the manifest
funnel number for number. For comparison the same replay gives `h6` 139
survivors with **1** off-topic, and `h9` h0's 32 with **0**. **`h3` already did it, at 116 records and 55.2%
off-topic** — and taking the union over all seven run arms, **211 of the 463
records (45.6%) have already reached an LLM stage, 79 of them off-topic**,
against h7's projected 47.
And the answer is not the one h7 was set up to look for. IC-33 returned
`not_meet` on 64 of 64 off-topic records — but also on 50 of 52 on-topic ones. It
did not *reject the junk*; it rejected almost everything. So "does the LLM reject
off-topic material" is answered trivially yes and tells us nothing, while the
question that matters — **can it discriminate** — is what `h3`'s numbers make
answerable and `h7` would answer at higher power. If `h7` runs, its analysis
should be a discrimination measure (off-topic rejected vs on-topic retained),
not a rejection count. Its 228-call budget buys that; it does not buy anything
if the reported outcome is "the LLM rejected the off-topic records".

**That is what makes it the most valuable of the three unrun arms.** §7.4's
strongest positive result — the IL stage flagged **8 of 8** records the reviewers
call wrong inclusions and let none into the pile it cleared — rests on **n=8**,
on one arm, on a population containing no off-topic material at all. h7 admits
**47 deliberately off-topic records** into the LLM stages, which tests that same
discrimination at nearly six times the n and against material whose ground truth
is known by construction rather than by reviewer judgement. Neither `h6` (1
off-topic) nor `h9` (0) can do that.

**And one question the wave has not been designed to answer at all.** §5.2's
negation result is the largest behavioural effect measured in this wave, and it
rests on 36 verdicts over 12 Portuguese records that reached EL only through a
translation defect. It has never been tested on an on-topic population where the
answer is non-trivial. Nothing in `h6`, `h9` or `h7` touches it.
