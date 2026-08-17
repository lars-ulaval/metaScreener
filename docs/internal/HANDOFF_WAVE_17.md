# HANDOFF — out of wave 17, into the next wave

Written at the close of wave 17f for a coordinator with **no memory of wave 17**.
Everything needed to pick up cold is here or is pointed at by path.

**This supersedes the earlier version of this file**, which was written mid-wave
at 17d and described seven arms as run and the analysis as not done. Both are
finished. Where the two disagree, this one is right; §7 lists the corrections.

---

## 1. State, verified at the close

| | |
|---|---|
| `main` | **`d4b08c5`** — `chore(wave17f): pack the object store, prune merged branches…` |
| `origin/main` | `d4b08c5` — pushed, in sync |
| tag | **`post-wave-17` → `91b13c9`**, the 17e freeze commit. `main` is **one commit ahead**: 17f is housekeeping and was deliberately left outside the tag |
| working tree | clean |
| suite, Windows | **2429 passed / 7 skipped** |
| suite, Linux (WSL Ubuntu 24.04) | **2431 passed / 5 skipped** — same 2436 total, different platform skips |
| four CI steps | `pytest`, `tools/audit_imports.py plugins/ tests/`, `tools/audit_decorators.py plugins/ tests/`, `tools/check_encoding.py` — green on both |
| register | **244 rows**, next free **F-248**, 40 cells machine-derived and matching |
| **open Criticals** | **0** |

By tier: `Critical 9/9/0 open · High 72/40/32 · Medium 108/37/71 · Low 55/20/35
· Total 244/106/138`.

Shape after 17f: `.git` **5.5 MB** (was 43 MB, never packed), working tree
**33 MB** (was 402 MB — `build/` and `dist/` removed, gitignored, never in
history), **2 local branches** (was 42), the remote shows **`main` alone**,
**41 tags untouched**.

---

## 2. What wave 17 did, in five lines

1. Built a second corpus (463 RSA records from 8 seeds) and eight criteria for
   it, then ten arms each varying one thing: wording, polarity, stage routing,
   edge shapes, adversarial unicode, missing abstracts, a `target` hint, batch
   size, and a deliberately loose gate.
2. Ran all ten live against `qwen2.5:7b` at temperature 0 — **472 calls**, zero
   removals, `request_shape: json_schema` on all twenty stages.
3. Found that the anchor arm had been run **twice** with byte-identical verdict
   tables — **a noise floor of 0 differences in 96 record-criterion pairs** — which
   is what makes every comparison below attributable to its variable.
4. Read the artefacts for content, which nothing had done: three independent
   judgements of the surviving pile, registered intent against outcome per arm,
   and the two LLM stages measured **separately**.
5. Froze the evidence (113 digests, a guard test that re-derives, `crit_impacts`
   recovered) and verified it in two fresh clones on two platforms.

---

## 3. The central result

**The two LLM stages are not one thing, and the difference is architectural.**

| | **IL** (asks inclusion criteria) | **EL** (asks exclusion criteria) |
|---|---|---|
| what a wrong answer does | routes to a human queue; **cannot delete** | **requests a deletion** |
| on 47 records off-topic *by construction* (`h7_loose`) | flagged **47 of 47**; its cleared pile of 33 holds **0** off-topic, against 8.2 expected by chance | 19 records reached `EXCLUSION_SUPPRESSED`; only **6** are off-topic — **precision 31.6%** |
| on the anchor pile, judged by three reviewers | agreed on **15 of 18** decisive records | **0 correct of 9** distinct (record, criterion) pairs across three arms |

**The stage that cannot delete is the accurate one. The stage that can delete is
the inaccurate one.**

### The guard holding the wrong deletions is the switchable one

`OUT` is 0 in all twenty stage summaries. That zero has **two causes of unequal
strength**:

| guard | held | can a setting switch it off? |
|---|---|---|
| **`exclusion_policy: flag_only`** | **49 verdicts** that passed the full strict evidence gate and reached `ACTION_EXCLUDE` | **YES — it is a provider setting** |
| **gate rule (c)** — a removal justified by *absence* | **576 verdicts** | No. Unconditional, whatever the setting |

**The wrong deletions are all in the first population.** They arrive by the
*presence* path, where the model produced a quote that validated — the one path
rule (c) never touches. **A user who sets `exclusion_policy` to act gets 13
wrongly deleted on-topic papers on `h7` alone, plus A187 and A275 on the anchor
arm — two of the seven records all three reviewers unanimously call correct
inclusions — each carrying evidence that renders as valid in every artefact.**

Do not permit `allow_exclusion` for any provider while **F-238** and **F-244**
are open.

---

## 4. Three things move the result without a user intending it

Each measured on the same 32 records against the 0-of-96 noise floor. The figure
is how many papers emerge `PASS_CLEAN` at **both** LLM stages.

| what changed | what stayed identical | effect | row |
|---|---|---|---|
| **Criterion wording** — the eight criteria restated in synonymous English | model, temperature, batch, corpus, records, truncation, window, policy, cache | **10 of 32 → 5** | **F-221** |
| **`batch_size`** 5 → 1, a throughput setting | criteria digest, model, temperature, prompt version, truncation, window, policy, cache | **10 of 32 → 5**, and the two survivor sets share **2 records of 13** | **F-247** |
| **A `target` hint** — 18 characters inside the criterion object | everything else byte-for-byte, including the text sent to the model | decisions barely move (1 of 64, 2 of 32); the model's self-reported evidence field swings **70.8 points**; at IL the counts are *identical* while two records swap | **F-227** |

Rewriting the protocol and changing a performance knob have the same magnitude
of effect. One is a scientific decision; the other appears in no methods section.

---

## 5. Findings

**Filed this wave: F-225 … F-247, 23 rows.**

| ID | Sev | Status | What |
|---|---|---|---|
| F-225 | Medium | **XS (done)** | An executable spec named a renamed `samples/` path; nothing checked that paths resolve |
| F-226 | Medium | S (open) | "Green" meant pytest only — and two Windows clones are one observation twice |
| F-227 | Medium | M (open) | **Retracted and downgraded** (§7). `target` is a *hint* on `llm` rows, and it moves gate outcomes |
| F-228 | **High** | S (open) | Per-criterion impact is computed every run and persisted nowhere |
| F-229 | Medium | S (open) | No operand is checked against its target column's actual vocabulary |
| F-230 | Medium | **XS (done)** | Recorded `source_sha256` values were platform-dependent |
| F-231 | Low | **XS (done)** | Measurement: on this corpus the deterministic stages remove essentially all off-topic mass |
| F-232 | Medium | S (open) | A spec field that does not exist is accepted and silently ignored |
| F-233 | Medium | **XS (done)** | The cross-arm TOTAL assumed one batch size for every arm |
| F-234 | Medium | S (open) | A field can be accepted, computed or displayed and still be inert |
| F-235 | Medium | XS (open) | At `batch_size` 1 the residue re-ask degenerates into a verbatim retry |
| F-236 | **High** | M (open) | Estimator calibrated on one corpus, applied to another. **Mechanism retracted** (§7) |
| F-237 | Low | **XS (done)** | Measurement with n stated; re-based at 17e against the right denominator |
| F-238 | **High** | M (open) | **The evidence gate checks that a quote EXISTS, never that it SUPPORTS the verdict** |
| F-239 | **High** | S (open) | A keyword criterion silently deleted 117 on-topic papers, including the corpus's seed [1] |
| F-240 | **High** | M (open) | The free-text translator emitted the logical **complement** of its own sentence |
| F-241 | **High** | S (open) | Negation-phrased criteria are answered as though the negation were absent |
| F-242 | **High** | S (open) | Where checkable from a title: 1 of 10 paediatric populations, 1 of 18 reviews |
| F-243 | Medium | S (open) | Record identity keyed on fields not unique per work, in both directions |
| F-244 | Medium → **High** | XS (open) | **EL's excluding verdicts have no demonstrated precision** |
| F-245 | Medium | S (open) | The gate is one-sided: a KEEP never has its quote examined |
| F-246 | Medium | S (open) | Abstract-less records are screened and cleared on title/keywords; answered by `h6` |
| F-247 | **High** | M (open) | **`batch_size` changes which papers a reviewer reads** |

**Also this wave.** **F-212 CLOSED** — `LANG_MAP` extended, guarded by
`tests/test_lang_map.py`. **F-129 CLOSED** at 17f — `secrets/README.md` named the
wrong `.env` location. **F-215 measured at last** by `h9`; its documented
identity-drop mechanism did **not** fire (zero dropped verdicts) while a larger
effect did — see F-247. **F-218** marked NOT REPRODUCING, and its prescribed test
is not executable: no log carries a timestamp.

---

## 6. Conventions this wave added

- **Derive ceilings from the dry run; never declare them.** Wave 16b killed a
  healthy arm with a per-arm ceiling set at the no-re-ask arithmetic. Every
  wave-17 `--budget` is 2× the dry run's predicted count; no arm exceeded 57.1%.
- **Verify on more than one line-ending configuration** — *two Windows clones are
  one observation twice.* F-226 exists because two Windows clones agreed while CI
  went red on 12 of 16 jobs. Wave 17 verified on Windows **and** a genuine Linux
  host, asserting every digest before running anything.
- **Wait for `{arm}_live_manifest.json` before `git add`.** It is the harness's
  last write, so its presence is the completion marker. A wildcard `git add -A`
  mid-run swept half-written artefacts into an unrelated commit, and `live_v1`
  carries no digests, so nothing would have caught it.
- **Allocate IDs past the maximum; reserve nothing.** The register counts *rows*,
  never the maximum ID — it has a permanent three-ID gap at F-56/57/58. Take the
  next number above the highest in use, then run
  `python tools/derive_register_totals.py` and paste its block.
- **Inputs get fixed; outputs get preserved.** A spec is an input: a stale path in
  it is a break to repair (F-225). A run manifest is an output: it keeps the
  string the run actually consumed, even when that string is now wrong. Never
  "correct" a recorded digest — it is an output record, and the checkout form is
  what is wrong (F-230).
- **A frozen directory is `binary`, without exception**, including the
  extensionless `SHA256SUMS`; its bijection is asserted against `git ls-files`,
  never the filesystem (F-223); and its digests are of the **committed** bytes.

---

## 7. Premises corrected, so they are not re-inherited

- **F-227 retracted and downgraded.** Filed High claiming an `llm` criterion
  screens only the field its `target` names. False — `prompt.py:78-86` packs
  `title`, `abstract` **and** `keywords` unconditionally. What survives: `target`
  is a *filter* for deterministic operators and a *hint* for `llm` ones, rendered
  identically, and the hint moves gate outcomes.
- **F-236's mechanism retracted; the floor is empirical.** The row argued *small
  prompts are denser* and named `h9` as the exposed arm. `h9` ran with the
  smallest prompts in the wave (327–699 tokens) at density **4.11–4.97** — the
  large-prompt band. **No size gradient exists, and h2's 3.55 is unexplained.**
  `CHARS_PER_TOKEN = 3.3` now stands on 272 post-calibration RSA samples plus
  wave 15b's 8, every ratio ≥ 1.109, zero drift aborts: **it is the value that
  has never under-estimated, not one a tokeniser model predicts.**
- **F-221's unidirectionality does not replicate.** *"None went the other way"* is
  a wave-16 single-corpus observation; wave 17 found 2 of 9 counter-directional.
  The corrected claim is **instability**, not a bias toward exclusion.
- **The `span` field is decorative.** Of the 212 evidence cells carrying both a
  quote and a span, **zero** have a span whose width equals the quote's length.
  Nothing consults it.
- **The stop condition "any `quote_valid=False`" was broken**: it fires on 828 of
  931 cells, because an honest null quote records `false`. The operative form is
  `quote_valid == False AND quote IS NOT null` (22 of 931); narrowed to the
  *acting path* — an `exclude` criterion answered `meet` — it fires on 3.

---

## 8. The open backlog

**What I would put first, and why.**

1. **F-238 + F-244 as one decision.** They compound: the evidence check cannot
   catch a wrong exclusion, and the exclusions are measured wrong. The cheapest
   correct action is not code — it is to **keep `allow_exclusion` off for every
   provider and say so in the user-facing docs.** That costs nothing and removes
   the only path to an irreversible wrong outcome.
2. **F-228** — persist `crit_impacts`. The tool already computes it; wave 17 had
   to reconstruct it (`tools/extract_crit_impacts.py`) to freeze it at all. One
   write closes it, and it is the precondition for F-239's fix.
3. **F-239** — surface sole-cause removals. One pass over data the chain already
   holds, no LLM, and it would have told the user that one criterion removed 117
   on-topic papers before a single call was spent.
4. **F-247 with F-101.** `batch_size` must be recorded where a reviewer reads it,
   and F-101 — the cache key is blind to batch size — must be fixed *before* any
   cache is enabled with a variable batch size. Together they turn a
   reproducibility problem into a contamination one.
5. **F-240 / F-241** — value-domain validation for enumerated columns, and a
   linter warning on negated criteria. The translator and the model mishandle
   negation independently, by different mechanisms, with no overlap in defences.

**Cheap and unblocked:** F-235 (XS), F-232, F-234.

**Reported at 17f, not acted on:** `docs/data/wave16_arms/` has no `SHA256SUMS`.
Adding one is safe and cheap, with two conditions — the digests must come from
the blob rather than this working tree (**38 of 514 tracked files diverge**, 16
of them there), and it forces that directory from `eol=lf` to `binary`.

### 8.1 What wave 17 makes newly urgent

**PyPI users are on 3.1.0.** This wave documented **23 further findings against
that release**, and two of them — **F-238** and **F-244** — mean that **a user
who changes one setting gets wrong deletions carrying valid-looking evidence**:
`quote_valid: true`, a quote clearing the substance floor, a confidence above
threshold, and nothing in the bundle marking it unsupported.

Nothing in 3.1.0 warns about this, and the README's provider-choice section
describes unreleased behaviour that would make the setting easier to reach.

Stated, not scheduled — **the maintainer schedules.**

---

## 9. Where everything is

| what | path |
|---|---|
| the wave's result, for a cold reader | `docs/data/wave17_arms/ANALYSIS_WAVE_17_ARMS.md` **§11** |
| frozen evidence, 113 digests | `docs/data/wave17_arms/` + `SHA256SUMS` + `meta.txt` |
| its guard, re-deriving every number | `tests/test_wave17_freeze.py`, 76 tests |
| per-criterion impact, all ten arms | `docs/data/wave17_arms/live_v1/crit_impacts.json`, rebuilt by `tools/extract_crit_impacts.py --check` |
| the register | `docs/internal/diagnostic/03_findings.md` — 244 rows, next free **F-248** |
| the harness | `tools/run_criteria_experiment.py` |
| corpus and criteria | `samples/20260816_1841_rsaAggregate.csv` · `samples/20260816_1841_rsaSampleIcEc.txt` |

**The criteria in `samples/` are a realistic example, not a recommended
instrument** — F-239 measures one of them removing 117 on-topic papers,
including the paper the corpus was built around. `samples/README.md` says so.
