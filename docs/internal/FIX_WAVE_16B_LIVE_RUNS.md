# FIX WAVE 16B — the criteria-diversity live runs

**Session:** wave 16b, 2026-08-15, branch `fix/wave-16b-live-runs` off `6e5dcfc`.
**Spend: 340 network calls** — 325 in-ledger across eight arms, plus 15 sunk in an
aborted first attempt. Declared ceilings totalled 648; the session ceiling of 750
was respected. **Zero records were removed at EL or IL in any arm.**

Evidence: `docs/data/wave16_live_runs/` (79 files, pinned by `SHA256SUMS`),
`meta.txt` there carries the provenance, the off-ledger disclosure, the
same-machine statement and the F-168 population banner. Predictions were
registered before any call at `2ed4710` (`FIX_WAVE_16A_CRITERIA_DESIGN.md` §7).

This document records **what happened and what was measured**. The cross-arm
scientific analysis, the freeze-guard test and any register rows belong to
wave 16c and are deliberately not written here.

---

## 0. Gates and preflight (all refusing, all passed before the first call)

- **git**: `main` at `6e5dcfc`, tree clean.
- **CI**: run `31909302033` on `6e5dcfc` — completed, **success**, **16/16 jobs
  green** (4 OS × Python 3.10–3.13). Already complete; no polling needed.
- **suite**: 2235 passed, 7 skipped.
- **dry re-verify**: all eight arms' harmonized criteria digests equal their
  `dryrun_v1` manifests; budget guard green at batch 5; baseline pin reproduced
  `776 → 16 → 760 → 738 → 22` with IC-5 met 70 / failed 690.
- **global preflight** (real store, read-only): provider `local`, endpoint
  `http://localhost:11434/v1`, window **4096** both stages,
  `llm_exclusion_allowed` **False** both stages, key gate passes; spec models
  **explicit `qwen2.5:7b` for EL and IL**, batch 5, temp 0.0, trunc 1500,
  `EL_v3_nullquote`/`IL_v3_nullquote`, `use_cache: false` declared *and*
  hardcoded; s1 bundle resolved by manifest content + zip digest.
- **offline smoke of the live path** against a fake client (zero network) before
  risking a call: nine artifacts written, 15 calls counted, anomaly checks silent.

The preflight caught the thing that mattered: the store resolves **IL to
`llama3.2:latest`** (the IL stage entry has no model key and falls back to the
top level, `settings.py:411-424`). Every arm therefore passed models explicitly.

---

## 1. PHASE-1 DIAGNOSTIC — the arm0 budget stop (zero calls, preserved artifacts)

The first attempt at `arm0_baseline` was declared **15** — the exact no-re-ask
arithmetic — and needed **16**. The enforcer refused attempt 16. Artifacts:
`docs/data/wave16_live_runs/aborted_attempt1/`.

### (a) Which batch, which call, and what was requested and returned

IL ran 22 records at batch 5 → batches of `[5,5,5,5,2]`. Calls 11-14 were
batches 1-4; **call 15 was the re-ask** (`reasks_made: 1`); **batch 5/5 was
attempt 16 and was refused**. The two records in batch 5 — **A612 and A622**,
confirmed as the last two in corpus order — were never sent.

**The exact request and reply that triggered the re-ask are not recoverable from
the artifacts, and that is itself the finding.** The engine preserves a reply
only when a batch ends with residue still unanswered (F-194's tally,
`_remember_no_answer_reply`, `llm_client.py:1763-1770`); here the re-ask repaired
the omission completely, so `no_answer_replies` is `{}` and nothing was kept. The
artifacts record *that* one batch of batches 1-4 was short, never *which* batch,
*how many* verdicts came back, or *which* `a_id`s.

### (b) Was the schema sent?

**Yes, on every call, and no fallback fired.** `_call_once` attaches
`response_format = _response_format_for(len(batch))` whenever `use_schema`
(`llm_client.py:1498-1500`), and that schema pins `minItems == maxItems == n`
with `strict: True` (`:1045-1058`, F-191). `request_shape` is recorded
**`json_schema`** in all fifteen live stage-reports; the F-107 fallback would
have written `"unconstrained"` permanently for the run (`:1819-1822`) and never
did. Aggregate integrity across all reports: `decisions_rejected: 0`,
`fields_rejected: 0`.

### (c) CLASSIFICATION — **[OTHER: undetermined-by-artifact]**, with
**[WRONG-IDENTITY]** as the mechanism the schema permits

- **[FALLBACK] — ruled out.** `request_shape: json_schema` everywhere.
- **[WRONG-LENGTH] — not established, and affirmatively unlikely.** Establishing
  it requires observing `len(reply) != n`, and the reply was not kept. Against
  it: cardinality was measured effective at wave 14c (31/31 previously-omitted
  pairs filled; the unconstrained controls reproduced the omission exactly,
  `_response_format_for` docstring) and across **414 constrained EL calls at wave
  15e with `reasks_made: 0` in all three runs** on this same server, model and
  decoding.
- **[WRONG-IDENTITY] — the mechanism the schema leaves open.** The per-verdict
  object declares `"a_id": {"type": "string"}` with **no enum**
  (`llm_client.py:1089`), so a reply of exactly *n* objects carrying a duplicated
  or out-of-batch `a_id` satisfies the schema perfectly. `_absorb` then
  **silently drops** any object whose `a_id` is not in the batch
  (`:1644-1646`) and **silently skips** a duplicate (`:1654-1655`) — in both
  cases with **no counter** — producing exactly the observed signature.

Because the length constraint is pinned and has a track record, while identity is
unconstrained by construction and its violations are dropped uncounted, the
observed omission is far more consistent with WRONG-IDENTITY. It cannot be proven
from what was kept, so the honest classification is **OTHER —
undetermined-by-artifact**. Per the decision rule (WRONG-IDENTITY / FALLBACK /
OTHER → proceed), the session proceeded to phase 2.

### (d) One re-ask per batch — confirmed; but **2 × base is a clean-path bound,
not the code's maximum**

**Confirmed:** the re-ask is a single `if omitted:` block issuing one
`_call_once`, not a loop (`llm_client.py:1734-1743`). On the clean path a batch
costs at most 2 calls, so an arm costs at most 2 × base.

**COORDINATOR PREMISE PARTLY WRONG** on "so the structural maximum per arm is
exactly 2 × base". The batch loop is `while True:` with **no attempts cap**
(`:1560-1561`). A *salvageable* error (`rate_limit`/`oversize` only, `:1857`)
takes one of two `continue` paths — halving the batch and inserting the remainder
as a new batch (`:1860-1878`), or stepping truncation down 1500→…→600
(`:1881-1889`) — and each retry is another counted call. The F-107 flip is a
third `continue` (`:1831`). So the true maximum is unbounded in principle; 2 ×
base holds exactly when no salvageable error occurs. None fired in these runs, so
the ceiling was never the binding constraint. The caveat is recorded in
`meta.txt`.

### (e) How the refusal propagated, and what the artifacts can and cannot say

The enforcer's `AssertionError` was caught by **the engine**, not the harness:
the generic `except Exception` at `llm_client.py:1809`. It was not a
`response_format` rejection, so it fell to `_classify_llm_error` → `unknown` →
not salvageable → terminal for that batch. Hence `calls_failed: 1`,
`batches_failed: 1`, and the log line
`[IL-LLM] batch 5/5 failed [unknown, by none]: live budget exceeded: call 16 > declared 15`.

**Distinguishable from a model-emitted uncertain: yes.** A model verdict carries
`used: true`; both the omission back-fill (`:1753-1761`) and the batch-failure
back-fill (`:1912-1920`) carry `used: false`. A612/A622 read
`{"decision": "uncertain", "confidence": 0.0, "field": "abstract", "quote": "",
"quote_valid": false, "used": false}`.

**Distinguishable from a *sent-but-omitted* record: no.** The batch-failure entry
also carries an `error` key, but `error` is not among the nine keys the stage
writes into `{el,il}_evidence_json`, so per-record the two are byte-identical in
the FULL table. Only the run report separates them, and only in aggregate.

**`no_answer: 0` is honest.** `no_answer` is defined as "the record was sent and
the model said nothing about it" (`summarize_llm_evidence` docstring,
`:1323-1325`); A612/A622 were never sent. **The counter that names the state is
`failed`** — `failed: 2` — with `batches_failed: 1` and `calls_failed: 1`
alongside, and the partition holds: `records 22 = answered 20 + failed 2`.

### (f) Had IL ever run live under v3 + qwen + constrained decoding? **No.**

Every live local run in the repository is EL-only: wave 12 (runA/B/C), wave 14c
(runD/E), wave 14d (runF/G/H/I), wave 15e (runJ/K/L) — all
`prompt_version: EL_v3_nullquote` or earlier, all `*_EL_FULL.csv`. There is no IL
artifact in any of them. The only IL goldens (`tests/golden/il_*`) are the
hosted `gpt-4o-mini` capture from 2026-05-02, predating the v3 prompt. Wave 15e's
own meta deferred it explicitly: *"Its live IL confirmation happens in ordinary
use; the suite pins it"* (`wave15e_acceptance_runs.meta.txt:90-93`).

**Today's runs are the first live exercise of IL under v3 + qwen2.5:7b +
constrained decoding — and the re-ask appeared there, on that first exercise,
while EL's twelve prior live runs and 414 constrained calls had never produced
one.**

---

## 2. The budget correction

A declared budget is a **fault-ceiling, not a spend prediction**. The first
attempt conflated them: 15 was the exact no-re-ask arithmetic *and* the hard cap,
leaving zero headroom for the one re-ask the engine is designed to make. Phase 2
declared **2 × base** per arm (648 total) while the **prediction stayed 324 base
plus observed re-asks**. Measured: **325**. Both figures are reported separately
in `meta.txt` and in the ledger below.

---

## 3. Ledger

| # | arm | ceiling | base | spent | re-asks | wall | no_answer | removals |
|---|---|---|---|---|---|---|---|---|
| 1 | arm0_baseline | 30 | 15 | **16** | 1 (IL) | 135.5 s | 0 | 0 |
| 2 | g1_paraphrase | 30 | 15 | 15 | 0 | 129.6 s | 0 | 0 |
| 3 | g4_edge_shapes | 24 | 12 | 12 | 0 | 97.9 s | 0 | 0 |
| 4 | g5_adversarial | 60 | 30 | 30 | 0 | 312.3 s | 0 | 0 |
| 5 | g3_stage_stress | 88 | 44 | 44 | 0 | 906.1 s | 0 | 0 |
| 6 | s1a_wording_el | 120 | 60 | 60 | 0 | 549.5 s | 0 | 0 |
| 7 | s1b_polarity_il | 120 | 60 | 60 | 0 | 1100.4 s | 0 | 0 |
| 8 | g2_polarity | 176 | 88 | 88 | 0 | 1340.1 s | 0 | 0 |
| | **in-ledger total** | **648** | **324** | **325** | **1** | **4571.4 s (76.2 min)** | **0** | **0** |
| | *sunk — aborted attempt 1* | *15* | *15* | *15* | *1* | *132.0 s* | *0* | *0* |
| | **grand total (network)** | | | **340** | 2 | 78.4 min | 0 | 0 |

Every arm passed its completeness check: FULL row count equals records at stage,
report JSON parses, `calls_made` equals base + re-asks, `OUT: 0`. Aggregate over
all fifteen live stage-reports: `decisions_rejected 0`, `fields_rejected 0`,
`batches_failed 0`, `calls_failed 0`, `no_answer 0`, `no_answer_after_reask 0`,
`request_shape json_schema` with no fallback.

---

## 4. The free noise pair (aborted attempt 1 vs the arm0 rerun)

Same configuration, cache off, temperature 0, on the pairs both runs answered —
44 at EL, 20 at IL, 64 total:

| axis | measured | runJ↔runK floor |
|---|---|---|
| decision flips | **0/64** | 0/294 |
| quote_valid flips | **0/64** | 0/294 |
| confidence churn | **0/64** | 2/147 records, confidence-only |
| record-outcome churn | **0** | 2/147 |

At or inside the floor on every axis. **Every cross-arm difference in these runs
is signal, not same-configuration noise.**

---

## 5. Prediction scorecard (§7 of the design, registered pre-run)

| # | prediction | measured | verdict |
|---|---|---|---|
| 1 | counts 15/15/12/30/44/60/60/88 = 324; re-asks 0; no_answer 0 | 16/15/12/30/44/60/60/88 = **325**; **re-asks 1**; no_answer 0 | **FAILED** on re-asks (and arm0's count); PASS on the other seven arms and on no_answer |
| 2 | schema violations 0 | `decisions_rejected 0`, `fields_rejected 0`, `json_schema` on every call, no fallback | **PASS** |
| 3 | fabricated meets ≈0 on A5 / E6 | A5 **0 meets**, E6 **0 meets** | **PASS** (batch-1 clause not exercised: no batch-1 arm) |
| 4 | not_meet quotes null throughout | **1348/1360 (99.1%)** null-quoted; 12 non-null, all `quote_valid: true` real substrings | **PARTIAL** — frozen comparator was 283/284 (99.6%) |
| 5 | absence routing: zero auto-acts; removals 0 | `OUT: 0` in all 16 stage-runs; every absence verdict → `EXCLUSION_SUPPRESSED` | **PASS** |
| 6 | G4/E7 (threshold 1.0): zero MET | 3 meets, **1 MET** (one verdict reached confidence ≥ 1.0), 15 UNCERTAIN | **FAILED**, narrowly |
| 7 | G5/A5 (thin `what`): 0 suppressions | 30 not_meet, all MET, **0 suppressions** | **PASS** |
| 8 | G5/A3 near-bound: runs without refusal or drift | ran clean; no `ContextBudgetExceeded`, no `TokenEstimateDrift` | **PASS** |
| 9 | G5/A4 unicode: no attributable parse failures | 30/30 answered | **PASS** |
| 10 | F-205/206/208 raw-probe behaviour repeats | loader semantics are call-free and unchanged; re-verified in the dry gate this session | **PASS** |
| 11 | repeat noise ≤ the 15e floor | 0/64, 0/64, 0/64 | **PASS** |
| 12 | wall clock ≈ 48 min | **76.2 min** in-ledger | **FAILED** — the 8.8 s/call EL rate does not transfer to IL (g3 IL 32 s/call; s1b 18.3 s/call) |
| 13 | s1a fabricated meets stay ~10/294, majority on runJ's ten | **17/294**; overlap **8 of runJ's 10** | **PARTIAL** — overlap direction PASS (8 > 5), band FAILED (+70%) |
| 14 | s1b modal outcome `meet` | **263 not_meet vs 31 meet** — modal is not_meet | **FAILED** |
| 15 | flips yardstick = runJ↔runK floor | applied throughout | **PASS** |

### s1a vs frozen runJ — identity map, wording is the only difference

294 comparable pairs. **Decision agreement 283/294 (96.3%)**, 11 flips;
quote_valid flips 9/294. runJ: 284 not_meet / 10 meet. s1a: 277 / 17.

runJ's ten meet pairs and their fate under the paraphrase:

| runJ pair | in s1a? |
|---|---|
| A247/EC-2, A307/EC-2, A310/EC-2, A373/EC-2, A452/EC-2, A473/EC-2, A499/EC-2, A583/EC-2 | **retained (8)** |
| A323/EC-3, A607/EC-2 | **lost (2)** |

Nine pairs are new to s1a (A317, A320, A327, A330, A345, A348, A467, A618,
A642 — all EC-2). So the core of the fabricated set survived rewording while the
margin grew by 70%.

### s1b vs frozen runJ — inversion map (template + stage + polarity, confounded)

294 mapped pairs, none missing, no uncertains: **coherent 33/294 (11.2%)**,
**incoherent 261/294 (88.8%)**. The confound is the one stated in the design:
template, stage and polarity move together. s1a bounds the wording component of
that gap at ~4%.

---

## 6. Candidate findings OBSERVED (list only — 16c adjudicates)

1. **A repaired re-ask leaves no diagnosable trace.** `reasks_made` increments;
   the triggering reply is discarded unless residue remains (`:1763-1770`). The
   operator cannot tell whether the model returned too few verdicts or the wrong
   identities.
2. **Identity violations are dropped uncounted.** `_absorb` silently skips
   out-of-batch `a_id`s (`:1645-1646`) and duplicates (`:1654-1655`); no counter
   exists for either, so WRONG-LENGTH and WRONG-IDENTITY are indistinguishable
   downstream. The schema pins cardinality but leaves `a_id` an unconstrained
   string (`:1089`).
3. **A never-sent record is indistinguishable from a sent-but-unanswered one in
   the FULL table.** Both are `used: false` uncertains; the `error` key that
   separates them does not reach `{el,il}_evidence_json`.
4. **IL had never been exercised live under v3 + qwen + constrained decoding**
   before this wave, and the first exercise produced the first re-ask ever seen
   on this stack.
5. **The 8.8 s/call planning rate is EL-shaped.** IL ran 2–3.6× slower per call
   on the same machine and model; any future budget or schedule built on the 15e
   rate will under-estimate IL by a wide margin.
6. **A confidence of exactly 1.0 is reachable**, so a threshold of 1.0 is not the
   unsatisfiable guard it looks like (G4/E7: 1 MET).
7. **Polarity framing barely moves this model's answer** (s1b: 88.8% incoherent
   against the inversion map, on a population where the same records under the
   exclude framing answered not_meet). Scientific interpretation is 16c's.

---

## 7. Premises corrected (this session): 2

1. **"the structural maximum per arm is exactly 2 × base"** — true only on the
   clean path. One re-ask per batch is confirmed (`:1734-1743`), but the batch
   loop has no attempts cap (`:1560`) and salvageable errors add retries
   (`:1860-1889`), so 2 × base is a clean-path bound, not the code's maximum.
   None fired here.
2. **"Does `no_answer=0` honestly describe a state where 2 records were never
   called?"** — it does. `no_answer` means *sent and unanswered*; the state is
   named by **`failed: 2`**, with `batches_failed: 1` and `calls_failed: 1`, and
   the report's partition adds up. The gap is not in the counters but in the
   per-record artifact, where a never-sent record is indistinguishable from an
   omitted one (finding 3 above).

A third correction was to my own verification, not to the brief: `SHA256SUMS` has
no extension and my first `.gitattributes` globs missed it. `git check-attr`
caught it; the repo-wide convention is that every freeze directory leaves
`SHA256SUMS` at `text=auto` and the freeze tests parse it line-ending-robustly
(`test_wave15e_acceptance_freeze.py:55-57`), so the convention was kept and the
expectation corrected. All 79 artifacts were then verified by `git check-attr`.

---

## STOP

Wave 16b ends here. 340 network calls spent against 648 declared and the 750
session ceiling; zero removals; artifacts frozen and committed. The freeze-guard
test, the cross-arm analysis and any register rows are wave 16c's. No merge, no
tag.
