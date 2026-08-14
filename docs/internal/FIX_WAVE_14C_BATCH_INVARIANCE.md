<!-- SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo -->
<!-- SPDX-License-Identifier: MIT -->

# Fix wave 14c — batch invariance

*Design only. This document is the design commit; no implementation accompanies it.*

**Repository state:** `fix/wave-14c-constrained-decoding` off `main` @ `24e675b`
(tag `post-wave-14b`), clean, `origin/main` in sync.
**Goldens:** `tests/golden` tree object `050b3575`, 9 files, **unmoved and not to be
moved in this session**.
**Test baseline:** **1932 passed, 7 skipped**.
**Register:** 197 rows after this wave's intake, max `F-200`, one open Critical
(`F-168`). **CI** 16/16 on `24e675b`, taken as given (F-165).

**The goal, in the maintainer's terms:** batch size is a throughput setting and must not
change which records get screened. Today it does. *"Teach the software to hear an empty
list"* is the mechanism at n=1 only; **the acceptance criterion is invariance.**

## Network disclosure

**I made 12 local Ollama calls** — `qwen2.5:7b` at `http://localhost:11434/v1`,
`temperature 0.0`, `trunc_chars 1500`, prompts rendered by
`plugins/06_el/prompt.py::_build_llm_messages_for_criterion` over the frozen
`docs/data/study_input/el_input_v3.1.0.csv`. No vendor API, no key, no stage run, no
model pulled. They exist because §2 is an empirical question about the *server*, and the
brief required it be measured rather than reasoned about.

---

## §1 The acceptance criterion, designed before the fix

### 1.1 What is compared

**Per-record `el_outcome`** — `OUT` / `PASS_CLEAN` / `PASS_FLAGGED` /
`EXCLUSION_SUPPRESSED` — not per-criterion `decision`. Outcome is what reaches the
review; a decision that flips without moving the outcome is not a screening difference,
and holding the fix to decision-identity would fail it for a change with no scientific
consequence.

**Secondary, and it carries a hard target rather than a bound:** `no_answer / records`
per arm. Today it is **94 % at batch 1 against 18 % at batch 5** — a 76-point gap.

### 1.2 What "the same" means — a bounded disagreement rate, and why not identity

**Not identity.** F-155 establishes that these runs are not deterministic at fixed
settings, so two batch-5 runs already disagree with each other. A criterion of identical
verdicts would fail on noise and tell us nothing.

**The bound is measured, not chosen.** Run **batch 5 three times** and take the maximum
pairwise per-record outcome disagreement among those repeats as the **noise floor**.
Batch invariance holds when cross-batch disagreement (1 vs 5, 5 vs 10, 1 vs 10) is **not
larger than that floor**. That converts an unfalsifiable *"about the same"* into a
comparison against a control the same session produces.

This is the design's honest weak point and it is stated rather than hidden: **the floor
is itself an estimate from three repeats**, and if the floor turns out to be large the
criterion becomes weak. If that happens the answer is more repeats, not a looser bound.

**Cache OFF for every arm.** **F-101** — verified at source this session:
`plugins/06_el/screen.py::_cache_key` renders the prompt for `[item]`, a *single-item*
list, whatever the real batch size, so the key is blind to batch size. The maintainer's
own two runs are already contaminated by it: 56 calls where the corpus needed
`ceil(277/5)`, because 17 pairs were served from the batch-1 run's cache. **A batch
comparison run with the cache on is not a comparison.**

### 1.3 What can live in the suite, and what cannot

| | where |
|---|---|
| the request carries a schema, and its cardinality equals the batch length | **suite**, doubles |
| a reply short of the batch is *detected*, not silently back-filled | **suite**, doubles |
| the re-ask covers exactly the omitted `a_id`s | **suite**, doubles |
| the fallback fires when a server rejects `response_format`, and the run records which path it took | **suite**, doubles |
| no code path maps absence to a verdict (§5.3) | **suite**, doubles |
| **whether the model omits, and whether the schema stops it** | **live — the maintainer** |
| **the invariance measurement itself** | **live — the maintainer** |

**A double cannot answer the invariance question, because the double is the thing that
decides the reply.** Everything mechanical is testable; the behavioural claim is not, and
pretending otherwise is how a wave ships a green suite and a broken run.

---

## §2 Can the schema enforce cardinality? — measured

**[measured], 12 calls.** Ollama 0.32.9 **accepts**
`response_format={"type": "json_schema", "json_schema": {…}}` — no refusal on any call.

| arm | result |
|---|---|
| batch 1, unconstrained | `[]` — **0 of 1 covered**, twice |
| batch 1, schema `minItems=maxItems=1` | a full verdict object — **1 of 1 covered, twice** |
| batch 5, unconstrained | 5 of 5 covered, twice |
| batch 5, schema `n=5` | 5 of 5 covered, twice |
| batch 10, unconstrained | 10 of 10 covered |
| batch 10, schema `n=10` | 10 of 10 covered |
| batch 3, schema `n=3` | 3 of 3 covered |
| **batch 5, `{"type": "json_object"}`** | **a bare single object — 0 of 5 covered** |

**Two conclusions, and they are not equally strong.**

**ESTABLISHED — the floor is enforced, and it kills `[]`.** `minItems=1` turned a reply
of `[]` into a verdict on the same record, twice, with nothing else changed. The
constraint was *load-bearing*: 0 objects became 1. That is the batch-1 failure mode
eliminated at its source.

**[not established] — that cardinality repairs *partial omission*.** I could not
reproduce omission on the frozen 85-record corpus: all four unconstrained multi-record
calls covered every record. So the constraint was never asked to add a missing object at
n>1, and I will not claim from n=1 that it would. **The maintainer's corpus produces the
omission; mine does not, and that difference is itself unexplained.**

**Consequence for the design, and it is the load-bearing one: detection is mandatory
regardless of what the schema does.** A design that trusts cardinality is a design that
rests on an unmeasured claim.

### 2.1 A correction to `09_llm_answer_rate.md`

09 §5.1 recommends **`{"type": "json_object"}`** plus a prompt instruction asking for a
`{"results": [...]}` wrapper, and states it needs no parser change. **Measured: that
combination does not work.** `json_object` at batch 5 returned a *bare* single object for
five records; `plugins/_common/llm_client.py::_parse_llm_json_array` drops a bare object
(**F-122**), so the run recorded 0 of 5. **The wrapper must be imposed by the schema, not
requested in prose.**

The parser half of 09's claim **survives and is re-verified**: schema output
`{"results": [{…}]}` parses through `_parse_llm_json_array`'s salvage regex unchanged. No
parser change is needed — but for `json_schema`, not for `json_object`.

---

## §3 The fix

### 3.1 Shape and cardinality

`response_format={"type": "json_schema", "json_schema": {"name": …, "strict": true,
"schema": …}}` where the schema is an object with a required `results` array,
`minItems == maxItems == len(cur_batch)`, and each item requiring `a_id`, `decision`
(enum), `confidence`, `field` (enum), `quote`, `span`.

**The cardinality is computed per call from the batch actually being sent**, including
after the adaptive-split path rewrites `cur_batch` — otherwise a halved batch would carry
a schema demanding the original count and the server would be asked for objects that
cannot exist. This is the single most likely implementation error and gets a test.

**The enums close F-90's and F-136's surfaces for free**: a `decision` outside the
vocabulary and a `field` outside `{title, abstract, keywords}` stop being expressible.
That is a side effect worth naming so a later reader does not think those rows were
fixed here — they are not; their code paths remain and still handle a non-conforming
provider.

### 3.2 Detection and the fallback for omission — arguing for one option

- **Cap batch size — rejected.** The measurement refutes it: batch 1 is the worst arm.
  F-154 bounds the *top* of the range; nothing bounds the bottom, and 07 §8.3's inference
  to "therefore 1" is retracted in `b744f42`.
- **Hard error — rejected.** It destroys a run for a condition that is recoverable, and
  it is worse for the user than today.
- **Re-ask the omitted records — recommended, once, then name the shortfall.** After
  parsing, compare covered `a_id`s against the batch's. If short, re-ask **exactly the
  omitted subset**; if still short, record the residue in a named counter rather than
  back-filling silently.

**The obvious objection, answered:** F-191 records retry as *measured worthless* against
`[]` at temperature 0 — byte-identical replies. **That measurement does not transfer.** It
was an *unconstrained* request re-sent verbatim; a re-ask of the omitted subset is a
different item list, hence a different rendered prompt, hence a different request — and
under §3.1 the `[]` case cannot arise at all. The measurement stands and is about
something else.

**The residue counter is the point of the fallback, not the re-ask.** A record the model
declines twice must end up in a state the run report names, because a silent back-fill is
exactly the defect wave 14b existed to end.

### 3.3 The provider fallback — answering F-107, not bypassing it

**F-107** is that the minimal request is the portability property that makes the
local-provider story work, and that it survives by luck. The design keeps it reachable:
attempt with the schema; on a rejection of the parameter, retry **once** without it and
proceed exactly as today.

**The predicate must not be `_classify_llm_error`, and wave 14b measured why.** A 400
whose body reads *"unsupported parameter 'response_format'; only max_tokens allowed"*
classifies as **`("oversize", "type+message")`** — *salvageable* — so it would enter the
halve-then-step-down ladder and spend the same refusal repeatedly before failing. The
fallback needs a dedicated check ahead of the salvage ladder.

**The run must say which path it took.** A `request_shape` field
(`"json_schema"` / `"unconstrained"`) on `llm_provenance`, so a bundle records whether its
verdicts came from a constrained request. Without it, two runs of the same version
against different servers are indistinguishable in the artefact — which is F-88's
argument, applied to the one thing this wave changes.

---

## §4 The costs, verified rather than assumed

### 4.1 `PROMPT_VERSION` bumps. Mandatory.

**[read]** `plugins/_common/llm_client.py::_cache_key` hashes exactly
`{prompt_version, model, endpoint, temperature, prompt}`. **`response_format` is not in
it.** So without a bump, entries cached by an unconstrained run are served to a
constrained one and back — the F-01 / F-89 shape, and the very contamination §1.2 rules
out of the measurement. **`EL_v1_jsonlist` → a new value, and IL's with it.**

`batch_size` is also not hashed. **That is deliberate and already registered as F-101**,
whose evidence cell this wave updated. Making it literal is F-101's decision and a second
full re-key; it is **not** in this wave's scope. What is in scope is saying that the
invariance measurement runs with the cache off.

### 4.2 The goldens move — quantified, and STOPPING HERE

A `PROMPT_VERSION` bump changes every cache key.

| golden | changes? | how much |
|---|---|---|
| `tests/golden/el_cache_v3.1.0.json` | **yes** | **170** entries under `cache`, every key rewritten; `_invocation` unchanged |
| `tests/golden/il_cache_v3.1.0.json` | **yes** | its `cache` map, same treatment |
| the other **7** files | **no** | byte-identical if the values are copied verbatim |

**Re-keyed, not re-captured.** `tools/rekey_cache_goldens.py` exists and wave 9 did
exactly this; the CHANGELOG records the precedent and the check that proves it — the four
files that record decisions must come out byte-identical, which is what shows the re-key
changed only labels. No API call, no decision recomputed.

**I have moved nothing, and this session will not. This is the maintainer's argued
decision.**

### 4.3 The test doubles — exact inventory

**13 keyword-only `create()` definitions**, across 11 files, each of which fails on the
first added keyword:

`tests/_engine_probe.py` (1) · `test_cancellation.py` (1) · `test_cross_batch_substitution.py` (1)
· `test_decision_whitelist.py` (**2**) · `test_error_classification.py` (**3**) ·
`test_flag_only.py` (1) · `test_negative_caching.py` (1) · `test_provenance.py` (1) ·
`test_run_report.py` (1) · `test_terminal_failure_guard.py` (1)

`tests/test_harmoniser_llm_call.py` uses `def create(self, **kwargs)` and needs **no**
change. Widen the 13 to accept and record `response_format`, which also makes them able
to *assert* the schema — turning F-107's accidental pin into a deliberate one, which is
what that row asks for.

---

## §5 The three questions the brief puts

### 5.1 F-195's quote requirement — **do not touch it this wave. Agreed.**

The coordinator's position is right and the register already says why. **F-191**'s fix
cell records the cross-constraint: the quote clause is one of three that stop a naive
`[]`→`not_meet` patch from asking for a whole corpus at IL, and **F-195** carries the
same note. Relaxing a backstop in the wave that changes the thing it backstops destroys
attribution if anything regresses — and this wave changes the request itself. **F-21 and
F-195 stay scheduled together, in a later wave.**

### 5.2 EL and IL both change — **verified, and non-negotiable**

**[measured]** `git diff --no-index plugins/06_el/prompt.py plugins/07_il/prompt.py` is
5 lines: the module docstring and `PROMPT_VERSION`. The function bodies are identical.
Both `prompt.py` modules and both `screen.py::_cache_key` wrappers move together, and
both `PROMPT_VERSION` constants bump.

**A fix on one stage only is the worse outcome**, because the two share
`run_m1_llm_for_criterion`: they would send different request shapes through one code
path, and the stage that did not move would keep the defect while the suite went green on
the stage that did.

### 5.3 The IL hazard cannot be expressed — by construction, and it gets a test

**F-191** records it: at IL, `not_meet` on an include-typed criterion is the *excluding*
verdict, so a fix that made `[]` mean "all `not_meet`" would ask for the whole corpus.

**This design never synthesises a verdict.** `[]` stops being expressible at the source
(§3.1); omission is detected and re-asked (§3.2); a record the model never addressed ends
in a named residue, not a decision. **There is no code path from absence to a verdict**,
and that is an invariant a test can state directly: no reply that omits a record may
produce an evidence entry for it with `used: True`.

---

## §6 The evidence, and what I need

**It should be committed, and `docs/data/wave12_local_runs/` is the right precedent —
including its shape.** That directory carries, per run, the **manifest**, the **FULL
CSV** and the **cache JSONL**, plus a `SHA256SUMS` and a `.meta.txt` naming the
provenance. **F-159** is the row that exists because a published measurement's evidence
sat outside version control, and **F-197 is now the register's justification for this
entire wave with its evidence on one disk.**

Recommended: `docs/data/wave14c_batch_runs/`, manifests **plus** FULL CSVs **plus**
caches. The manifests alone would not do: the per-record outcome table is what any later
batch-invariance claim is checked against, and the caches are what show the 17-pair
contamination.

**I do not have the files and have not assumed otherwise. Please give me the paths to the
four bundle ZIPs**, and note that committing corpus-derived CSVs interacts with **F-200**
(the manifest now carries third-party bibliographic text) — the same caveat question, one
directory over.

## §7 Open, and not settled here

- **Whether the model over-called `meet` on `EC-2` at batch 5** — 13 records, 11 becoming
  `EXCLUSION_SUPPRESSED`. **[not established].** The frozen 85-record corpus gives a
  maze/spatial-navigation keyword base rate of **zero**, which is suggestive and is *not
  the same corpus*; the 147-record post-13d chain is not in this repository. **No row was
  forced.** It needs the bundles.
- **Why the frozen corpus does not reproduce partial omission** at batch 5 or 10 when the
  maintainer's does. Corpus length, criterion text, or run-to-run variance — [not
  established], and it bounds how much §2's negative result can be leaned on.
- **Where between 1 and 5 the failure sets in**, and whether 5 is optimal or merely better
  than 1.
