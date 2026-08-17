# HANDOFF — wave 17

Written at the end of wave 17d for a session with **no memory of this one**.
Everything needed to finish the wave is here or is pointed at by path.

---

## 1. State

| stage | what it was | status |
|---|---|---|
| **17a** | land the `samples/` rename; commit the RSA corpus byte-stable; encoding hotfix | **done, on main** |
| **17b** | author the RSA criteria file and the wave-17 arms | **done, on main** |
| **17c** | derive the call budget from a dry run; preflight verification | **done, on main** |
| **17d** | the live run, ten arms | **7 of 10 arms run**, halted |
| **17e** | freeze the evidence | **not started** |

**Arms that have run:** `h0_baseline` (twice), `h1_paraphrase`, `h2_polarity`,
`h3_stage_stress`, `h4_edge_shapes`, `h5_adversarial`, `h8_pinned_target`.

**Arms that have NOT run:** `h6_no_abstract`, `h9_batch1`, `h7_loose`.

**Spend so far: 230 live calls.** h0 twice (24 + 24), h2's aborted first attempt
(1), and the six-arm sequence (181).

### Git state — read this carefully, it contains a mistake of mine

`main` is at **`b95886b`** and contains **everything**. The working tree is
clean. **Nothing has been pushed.** No tag exists for 17b, 17c or 17d
(`post-wave-17a` exists and points at `980d339`, deliberately, even though that
commit is CI-red — it records truthfully where the stage ended, including that
it ended with an undetected defect, which is the evidence for F-226. **Do not
move it.**)

**My error, stated because the reports were wrong:** the last two commits,
`74bf295` (the calibration) and `b95886b` (the six arms), were committed
**directly on `main`**. The maintainer's fast-forward merge of
`fix/wave-17d-calibrate` left HEAD on `main` and I did not branch again before
committing. My session reports said "nothing merged" both times. They were
wrong; `git reflog show main` is the record. Everything before those two came to
main by the maintainer's own fast-forward merges.

Ten stale wave-17 branches exist and can be deleted once the maintainer is
satisfied: `fix/wave-17a-encoding`, `fix/wave-17a-rename-and-rsa-corpus`,
`fix/wave-17b-arms`, `fix/wave-17b-criteria`, `fix/wave-17c-budget`,
`fix/wave-17c-dryrun`, `fix/wave-17c-preflight`, `fix/wave-17d-arms`,
`fix/wave-17d-calibrate`, `fix/wave-17d-live`.

**Suite: 2348 passed / 7 skipped.** All four CI steps green.

---

## 2. Where everything lives

| what | path |
|---|---|
| corpus (463 records, 34 cols) | `samples/20260816_1841_rsaAggregate.csv` — sha256 `e8b262f1203c8b459357e866bc376e40f3b73a2d7b68b67cac5a3f01e371435c` |
| criteria file (8 criteria) | `samples/20260816_1841_rsaSampleIcEc.txt` — sha256 `62e59ab8…` |
| the spec | `docs/data/wave17_arms/experiment_spec.json` — 10 arms |
| prose arms | `docs/data/wave17_arms/h{1,2,3}_*.txt` |
| columnar arms | `docs/data/wave17_arms/h{4,5,6,7,8}_*.csv` |
| dry-run manifests | `docs/data/wave17_arms/dryrun_v1/` (11 files) |
| **live artefacts** | `docs/data/wave17_arms/live_v1/` (63 files, 7 arms) |
| the harness | `tools/run_criteria_experiment.py` |
| register | `docs/internal/diagnostic/03_findings.md` — 234 rows, next free **F-238** |

Per arm, `live_v1/` holds `{arm}_{EL,IL}_FULL.csv`, `_report.json`,
`_summary.json`, `_log.txt`, and `{arm}_live_manifest.json`.

Both `samples/` files and everything under `docs/data/wave17_arms/` are pinned
`text eol=crlf` in `.gitattributes`. Keep disk and checkout byte-identical: if
you regenerate anything, normalise to CRLF before committing (F-230).

---

## 3. Findings filed this wave

| ID | sev | category | status |
|---|---|---|---|
| F-225 | Medium | provenance / CI | **XS (done)** |
| F-226 | Medium | process / testing | S (open) |
| F-227 | Medium | correctness / scientific integrity | M (open) |
| F-228 | **High** | provenance / scientific integrity | S (open) |
| F-229 | Medium | correctness | S (open) |
| F-230 | Medium | provenance / CI | **XS (done)** |
| F-231 | Low | measurement / validation | **XS (done)** |
| F-232 | Medium | provenance / correctness | S (open) |
| F-233 | Medium | provenance / correctness | **XS (done)** |
| F-234 | Medium | provenance / correctness | S (open) |
| F-235 | Medium | correctness | XS (open) |
| F-236 | **High** | correctness / instrument | M (open) |
| F-237 | Low | measurement / validation | **XS (done)** |

Also touched: **F-212 CLOSED** (`XS (done)`) — `LANG_MAP` extended so every name
branch 1 can emit reaches a code, and every code a committed corpus stores is
reachable by name; guarded by `tests/test_lang_map.py`, seen red first.
**F-217** gained two re-ask rates. **F-218** is marked **NOT REPRODUCING** — three measurements, three relationships — with an untested candidate explanation recorded in the row; see §6.

### F-227 carries a retraction — read the row, do not trust the headline

F-227 was filed **High** claiming an `llm` criterion screens the single field
its `target` cell names, and that the abstract is screened on neither corpus.
**That is false and the row says so in place.** `plugins/06_el/prompt.py:78-86`
and its IL twin pack `title`, `abstract` AND `keywords` for every item
unconditionally; `target` is only a string inside the criterion object. Verified
from a rendered prompt and corroborated live (`field=abstract` with
`quote_valid=True`, impossible had only the title been sent).

Also verified by sentinel: `_get_best_text_targets`'s value reaches the `target`
cell **only where `operator == "llm"`** — all six deterministic branches
overwrite it. So the corpus-dependent choice lands exclusively where it selects
nothing.

**What survives, and why the row is still open at Medium:** `target` is a
*filter* for deterministic operators and a *hint* for `llm` ones, and
`criteria_harmonized.csv` — which ships in the bundle — renders both
identically. A reviewer sees `target: keywords` on an `llm` row and concludes
the model saw keywords. It saw all three.

---

## 4. The calibration (F-236) — the most load-bearing result

**`CHARS_PER_TOKEN` was 4.5 and is now 3.3**, in
`plugins/_common/llm_client.py`. The full reasoning is in that constant's
docstring; the short version:

4.5 was measured once, on wave 15b's **VR** corpus, and applied to the **RSA**
corpus with nothing asking whether the new text tokenises the same way. It does
not. `h2_polarity` aborted on its first live call — 885 actual prompt tokens
against 741 estimated, 3.62 chars/token — and eight of nine arms could not run.

**Small prompts are DENSER,** which inverts the intuition: JSON scaffolding,
field names, record ids and punctuation tokenise badly and dominate a small
payload, while long prose tokenises efficiently and dominates a large one. Wave
15b's own probes show 5.03–5.23 chars/token on large payloads and 4.48–4.50 on
small ones.

3.3 is a **floor, not a mean** — a mean is what failed. It is also the *lowest*
value causing no false refusal: the largest prompt in the wave is 11,551 chars,
estimating 3,531 tokens, and 3,531 + the 400-token reserve is 3,931 inside a
4,096 window. At 3.0 the same prompt would want 4,281 and the guard would refuse
a prompt that fits.

### Validation: 197 recorded samples, 0 drift aborts

| arm | density (chars/token) | min margin |
|---|---|---|
| h5_adversarial | 4.44 – 4.96 | +36% |
| **h2_polarity** | **3.55 – 3.83** | **+11%** |
| h1_paraphrase | 4.51 – 4.74 | +39% |
| h8_pinned_target | 4.52 – 4.74 | +39% |
| h3_stage_stress | 3.92 – 5.17 | +27% |
| h4_edge_shapes | 4.41 – 5.16 | +35% |

h2's 3.55–3.83 confirms the single 3.61 observation the floor was fitted from.
Nothing anywhere fell below 3.55.

**The drift check is unchanged and still strict** — `llm_client.py:1662`,
`actual > estimate` raises. Calibration made the estimate right; it did not make
the check forgiving. `tests/test_context_guard.py` re-adjudicates the pin to 3.3
with the evidence, and now also asserts conservatism against the eight RSA
observations.

**Instrumentation added:** `token_samples` records every
`(estimate, actual, items, criterion)` tuple and the harness surfaces it into
each stage summary. Before this, the drift check fetched `usage.prompt_tokens`,
compared it once, and discarded it — so two waves of live running left exactly
one usable observation. Any future recalibration now has data.

**I6 measurement:** after calibration, **zero of ten `guard_ok_batch5` verdicts
change.** All were True before and remain True; worst est+reserve rises to
2,318–3,930, with h4 closest at 3,930 of 4,096 = 96%. The prompts did fit; only
the assurance had been missing.

---

## 5. The five stop conditions, as revised

Halt the sequence immediately and report if any arm shows:

1. **any removal or auto-act at any gate** — `OUT > 0` in a stage summary's
   `counts`. Wave 16 and all seven wave-17 arms measured zero. A removal is
   either a real behaviour change or a broken gate.
2. **any F-107 unconstrained fallback** — `request_shape != "json_schema"`.
3. **any arm reaching its per-arm ceiling.**
4. **any `quote_valid=False`** — *this replaces the retired condition below.*
5. **any `TokenEstimateDrift`.**

### The retired condition, and why

The fourth condition used to be *"any non-null quote on a `not_meet` verdict"*.
**It was wrong and it halted the sequence on permitted behaviour.** The contract
at `plugins/07_il/prompt.py:44` asks for *"null, **unless an exact substring
genuinely supports the verdict**"*, and the schema at
`llm_client.py:1143-1146` makes `quote` `anyOf [string, null]` — **nullable,
never null-required**. F-195's comment says why: a schema requiring a string
*"demands fabrication in grammar"*.

The condition came from a session report of mine that described 80-of-80 null
quotes on h0 as "the wave-15 null-quote fix holds", turning an observation into
a guarantee. Do not reinstate it. The four verdicts that tripped it are filed
as **F-237** (Low, measurement) with their n stated and their inertness proved.

The driver that enforces these lives in the scratchpad, not the repo. Its logic
is simple enough to rewrite: run each arm as a subprocess, then read the stage
summaries and `FULL.csv` evidence before starting the next.

---

## 6. Measurements to carry forward

**Re-ask rate does not track prompt size.** 8 of 197 base batches = **4.1%**
overall, against wave 16b's 1 of 324 = 0.31%.

| arm | median chars | re-asks | rate |
|---|---|---|---|
| h2 | 3,151 | 0 of 12 | 0.0% |
| h3 | 7,033 | 1 of 48 | 2.1% |
| h4 | 7,049 (max 11,551) | 0 of 56 | 0.0% |
| h0 | 9,010 | 3 of 21 | 14.3% |
| h1 | 9,024 | 3 of 21 | 14.3% |
| h8 | 9,028 | 1 of 21 | 4.8% |
| h5 | 9,329 | 0 of 18 | 0.0% |

No monotone relationship in either direction. The largest-prompt arm and
largest-median arm both had zero. h0 and h1 are paraphrases and both hit exactly
3; h8 is h0 with one hint string changed and hit 1. **It looks stochastic.** The
calibrated ceiling of 486 derived from 0.31% was withdrawn in 17c; the
**structural 926 stands**.

**F-218 is NOT REPRODUCING.** Three measurements, three relationships:

- wave 15e / F-218 as filed: IL 2.0–3.6× slower than EL
- h0: IL 8.43 s/call against EL 7.77 → **1.08×**
- h3: EL **28.00** s/call against IL 7.48 → EL nearly **4× slower than IL**

Candidate explanation for h3's EL outlier, **untested**: Ollama unloads idle
models, so an arm starting after a gap pays model-load time on its first calls.
h3 began at 08:31:25 after h8 finished — check the gaps in
`live_v1/*_log.txt` against the per-call timings. Every wall-clock figure in the
spec is currently at h0's measured rates and should be treated as provisional.

**The three `quote_valid=False` cases, as a measurement with n stated:** 3 of 68
`not_meet` verdicts on `h4_edge_shapes` IL criterion H4-7 named
`field=abstract` and quoted the **keywords** text instead; a fourth quoted the
title with `quote_valid=True`. All four are `status=SUPPRESSED`, confidence 0.9,
and `verdict_gate.py:147` does not consult the quote on the
`RULE_REMOVES_BY_ABSENCE` path, so **all are inert for the decision. Nothing was
removed.** H4-7 is the longest prompt in the wave, but **do not assert that
prompt length causes this** — the re-ask data above shows no size relationship,
so length-as-cause is a hypothesis at n=3. Evidence:
`live_v1/h4_edge_shapes_IL_FULL.csv`, records A220, A221, A223 (invalid) and
A228 (valid).

---

## 7. Remaining work

### 17d, to finish: 266 calls, ~35 min

```
h6_no_abstract   56 calls   --budget 112
h9_batch1        96 calls   --budget 192
h7_loose        114 calls   --budget 228
```

Command shape — **pass `--out` explicitly every time**:

```
python tools/run_criteria_experiment.py \
    --spec docs/data/wave17_arms/experiment_spec.json \
    --out  docs/data/wave17_arms/live_v1 \
    --live --arm h6_no_abstract --budget 112 --yes-live
```

**`h9_batch1` is the remaining drift risk.** Its prompts are 1,296–3,004 chars,
**all smaller than any density observation** (the densest measured is h2's 3.55
at ~3,150 chars). If density keeps falling below that, h9 trips the drift check,
costs one call, and yields the datum the fit is missing. That is the right trade
— let it happen rather than loosening the check.

### 17e, not started

Freeze the evidence. **Note carried from 17c:** because the product does not
persist per-criterion impact (F-228), the freeze must capture `crit_impacts`
**explicitly from the harness**, or the frozen evidence inherits the same hole.

---

## 8. Standing conventions

- **Detached runs with polled logs.** Never a foreground call that can hit a
  tool timeout mid-flight. Launch with `nohup … > log 2>&1 &`, then poll the log
  with an `until` loop.
- **`--out` always explicit.** Its default now derives from the spec's directory
  (`default_out_for`), but pass it anyway — a wave-16-pinned default already
  wrote wave 17's artefacts into `wave16_arms/dryrun_v1` once.
- **Per-arm `--budget` from the spec's `call_ceiling_arm`** (2× that arm's
  predicted). Not the total. Wave 16b killed a healthy arm with a per-arm ceiling
  set at the no-re-ask arithmetic.
- **Models explicit per stage.** `live_preflight` refuses unless
  `live.model.{EL,IL}` are both set. The GUI path has a stage→app-level fallback
  (`settings.py:411`, `effective()`) that the harness bypasses; keep it bypassed.
- **Cache off.** `use_cache: false`, enforced in three places. h0 and h9 differ
  only in batch size and the F-101 cache key is blind to batch size, so a live
  cache would silently collapse them.
- **Zero-tolerance drift check.** Do not add a tolerance. Recalibrate the
  estimator instead; that debate is settled in F-236.
- **The register's totals are machine-derived.** Run
  `python tools/derive_register_totals.py` after any row change and paste its
  block; `tests/test_register_totals.py` asserts it.
- **All four CI steps, not just pytest** (F-226): `pytest`,
  `tools/audit_imports.py plugins/ tests/`,
  `tools/audit_decorators.py plugins/ tests/`, `tools/check_encoding.py`. And
  verify on more than one line-ending configuration — two Windows clones agreed
  once while CI went red on 12 of 16 jobs.

---

## 9. NOT ANALYSED — the biggest gap in this handoff

**Seven arms have run and no report anywhere says what any of them MEASURED.**

Everything reported so far is operational: call counts, re-ask rates, gate
outcomes, request shapes, wall clock, token densities. Those establish that the
instrument worked. **They say nothing about the experiment's results.** The
artefacts hold the answers and nobody has read them for content.

Specifically unknown to me:

- **h0 vs h1 is F-221's replication** — does rewording a criterion change which
  records survive? Both arms ran on the same 32 records with paraphrased
  criteria. Compare the verdicts in
  `live_v1/h0_baseline_{EL,IL}_FULL.csv` against
  `live_v1/h1_paraphrase_{EL,IL}_FULL.csv`, per record per criterion. **The
  result is unknown to me.** Their operational profiles are near-identical
  (21 base calls, 3 re-asks each), which says nothing about agreement.
- **h0 vs h8 is F-227's only surviving claim** — does the `target` hint string
  move the model? Same prompts, same records, one string different in the
  criterion object. h8's summaries show a different suppression split
  (EL SUPPRESSED 4 against h0's 2), so **something moved**, and nobody has
  looked at what. `live_v1/h8_pinned_target_*` versus `h0_baseline_*`.
- **h2's polarity mirrors** — do the inverted criteria produce inverted
  verdicts? `mirror_pairs` is not declared in the wave-17 spec the way wave 16
  declared it; the pairing has to be read from
  `docs/data/wave17_arms/h2_polarity.txt`.
- **h4 and h5's edge shapes** — did the thin `what`, the absence phrasing, the
  long prose, the threshold 1.00, the Cyrillic criterion and the
  comma-in-operand behave as their `source_text` cells predicted? Each row's
  intent is registered in the spec under that arm's `intents`.
- **h3's stage routing** — its registered intents include deliberate traps
  (branch 2 both ways, the DOI branch, a German language rule now mapped
  post-F-212). Did the landings match?

The dry manifests already contain `landings_vs_intent` per arm, which is the
right starting point for the deterministic half. The LLM half has to be read out
of the `FULL.csv` evidence columns.

---

## 10. Open questions

1. **h3's EL 28 s/call outlier.** Candidate: Ollama model unloading between
   arms. Untested. Check log timestamps against per-call timing.
2. **Does density vary enough *within* the RSA corpus to make a single divisor
   unsafe?** Observed 3.55–5.18 across six arms. 3.3 held for all 197 samples,
   but h9's prompt range is unobserved.
3. **h9's small prompts** — the remaining drift risk, deliberately unmitigated.
4. **Is the `quote_valid=False` behaviour worth a finding?** 3 of 68, inert,
   n too small to attribute a cause.
5. **Ten stale wave-17 branches** to delete once the maintainer is satisfied.
