# FIX WAVE 16A — criteria-diversity robustness: design, harness, deterministic dry run

**Session:** wave 16a, 2026-08-15, branch `fix/wave-16a-criteria-design` off `556daa7`.
**Live-call budget: ZERO — spent ZERO.** The dry path is structurally incapable of
network calls (no LLM client is ever constructed in dry mode; a guard raises if that
invariant were ever broken — `tools/run_criteria_experiment.py::_install_dry_guard`,
pinned by `tests/test_run_criteria_experiment.py::TestDryModeIsStructurallyOffline`).
`--live` exists (built for 16b) and **was never invoked**.
**This wave ends at the STOP line at the bottom. No 16b work happened.**

Map: `docs/internal/RECON_WAVE_16.md` (adopted verbatim this session, commit 1);
everything load-bearing built on it was re-verified in-session before use.

---

## 1. Environment givens (recorded from the maintainer, 2026-08-15) + code verification

Given (do not write his store; re-assert all of this at the 16b preflight):

- `%APPDATA%\metaScreener\settings.json`: endpoint `http://localhost:11434/v1`,
  provider `local`, api_key `""`, `allow_llm_exclusion: null`, top-level model
  `llama3.2:latest`, per-stage overrides (the store's real container key is
  **`stages`**, not "stage_overrides" — `plugins/_common/settings.py:216`;
  overridable fields are only `model`/`endpoint`/`batch_size`,
  `STAGE_OVERRIDABLE`, settings.py:356): EL `{batch_size: 10, model: qwen2.5:7b}`,
  IL `{batch_size: 1}` (**no model key**), harmoniser `{model: qwen2.5:7b}`.
  **No `context_window` key anywhere.**
- `OLLAMA_CONTEXT_LENGTH` unset. ollama: `qwen2.5:7b` id 845dbda0ea48 Q4_K_M 7.6B;
  `llama3.2:latest` id a80c4f17acd5 present.

Verified in code AND by execution against a byte-equivalent store in a scratch
APPDATA (real store untouched; `load_settings()` never writes — a missing file
returns `defaults()`, settings.py:239-262):

**(a) Per-stage model resolution — IL falls back to the top-level model.**
`resolve_stage` → `effective_model` → `effective(settings, stage, "model", "")`
(settings.py:427-428, :593): the stage entry is tried first, then the top level
(settings.py:411-424). `stages.IL` has no `model`, so IL resolves
**`llama3.2:latest`**; EL and harmoniser resolve their override `qwen2.5:7b`.
Executed proof: `effective_model('IL') = 'llama3.2:latest'`,
`resolve_stage('IL').model = 'llama3.2:latest'`.
**Operational consequence for 16b:** a store-resolved IL run would use a
DIFFERENT model than EL. The harness therefore takes models **explicitly per
stage from the spec** and never store-resolves model or batch
(`run_el_screen`/`run_il_screen` accept keyword-only `model`/`batch_size` —
`plugins/06_el/screen.py:458-471`, `plugins/07_il/screen.py:460-473`).

**(b) `allow_llm_exclusion: null` → `llm_exclusion_allowed` is False for EL and IL.**
`llm_client.py:206-228` → `resolve_stage` reads the tri-state application-level
setting (settings.py:583-585); a non-bool (including None) falls to
`key_required(provider)` (stage_state.py:507-558, fall-through at :558), and
`"local"` is keyless (`_KEYLESS_PROVIDERS`, stage_state.py:425) → **False**
(flag-only). Executed: `False` / `False`.

**(c) `resolve_context_window` = 4096 for both stages.** No stored
`context_window` (defaults to None, settings.py:215); the hosted 128k default
applies only to paid-vendor endpoints (`_hosted_default_applies`,
llm_client.py:822-843; `is_paid_vendor` matches api.openai.com hosts only) —
localhost gets `CONTEXT_WINDOW_DEFAULT = 4096` (llm_client.py:749, :846-869).
Executed: `4096` / `4096`.

**(d) Batch sizes as the store resolves them today** (for the record; 16b does
NOT use them): EL 10, IL 1 (explicit overrides), unset stages fall to the D6
suggestion `LOCAL_BATCH_SIZE = 5` (settings.py:568-570; stage_state.py:979).
16b runs **batch 5 explicit** on both stages, from the spec.

**(e) Preflight mechanics for 16b:** assert against the real store by calling
the read-only resolvers under the inherited `APPDATA` (settings.py:127-130);
pin/pop `OPENAI_BASE_URL`/`OPENAI_API_KEY` (llm_client.py:120, :246-249 —
store beats env, :187-192). The harness's `live_preflight` asserts endpoint,
window, exclusion policy, key gate, corpus digest, criteria digest, and
explicit per-stage models before any call, with REFUSING semantics
(`tools/run_criteria_experiment.py::live_preflight`, the 15e pattern —
`docs/internal/harnesses/acceptance_harness_15e.py:81-110`).

---

## 2. The harness (recon §6c's "genuinely missing" build)

`tools/run_criteria_experiment.py` — spec-driven multi-arm driver.
Spec: `docs/data/wave16_arms/experiment_spec.json` (committed; corpus digest
pinned; per-criterion intents recorded **before** the first dry run; live
config with explicit models/batch per stage).

Per arm the dry pipeline runs the product's own machinery, never a re-implementation:
free-text arms translate via the exact call sequence
`tests/test_harmoniser_regression.py::_build_rows` reproduces
(`_parse_free_text_criteria` → `_infer_criterion_details` → `_criteria_csv_text`);
every arm is loaded per stage by the product loaders
(`_load_criteria_from_text` EH/IH; `_parse_criteria_harmonized_csv` EL/IL);
EH→IH runs via `run_screen` with the survivor re-wrap
(`tests/test_stage_routing.py:230-243`); EL/IL prompts render through the real
builders and the real `check_context_budget` per criterion at batch 5 and 1;
call arithmetic is cross-asserted against the engine's `RunPlan` on every arm.
Outputs: per-arm manifest JSONs + `cross_arm_summary.csv` under
`docs/data/wave16_arms/dryrun_v1/`.

**Built-in correctness check:** the baseline arm must reproduce the pinned
chain `776 → EH OUT 16 → 760 → IH OUT 738 → 22` with IC-5 met=70/failed=690 or
the whole run aborts (`BASELINE PIN FAILED`). It reproduced it exactly, and the
suite pins that reproduction (`TestBaselineReproduction`). Suite: **2218 → 2229
passed, 7 skipped** throughout.

**Live mode (16b, built, NOT exercised):** `--live --arm KEY --budget N
--yes-live`; 15e preflight-assert + 15d hard budget enforcer wrapping
`llm_client._openai_client_for` (`_BudgetEnforcedClient`); `use_cache=False,
cache_in={}` per F-101; models/batch explicit from the spec.

Raw bundle-read probes (`raw_probe`) feed a CSV through all four loaders with
no validator — the F-205/F-208 semantics pass, reported per stage.

---

## 3. The six arms — taxonomy, criteria, intent

Full verbatim criteria live in the committed sources; intents (stage, operator,
rationale per criterion, recorded pre-run) live in the spec. Summary:

| arm | kind | source | n | probes |
|---|---|---|---|---|
| arm0_baseline | free_text | samples/ic_ec_12.txt | 8 | anchor; pin check |
| g1_paraphrase | free_text | wave16_arms/g1_paraphrase.txt | 8 | translator robustness + decision stability under rewording (byte-distinct, same intent, same ids) |
| g2_polarity | free_text | wave16_arms/g2_polarity.txt | 6 | logically-equivalent include/exclude mirrors; 2 deterministic boundary hazards recorded pre-run |
| g3_stage_stress | free_text | wave16_arms/g3_stage_stress.txt | 8 | all-four-stage recipe + 2 trigger-word traps (F-65 class, deliberate) + negation-blindness + LANG_MAP gap + DOI branch |
| g4_edge_shapes | harmonized_csv (+ raw probe) | wave16_arms/g4_edge_shapes.csv, g4_raw_probe.csv | 8 (+4 raw) | F-204 union, F-205 both ways, F-206 both directions, F-208, in_list exactness, between bounds, thresholds 0/1 |
| g5_adversarial | harmonized_csv | wave16_arms/g5_adversarial.csv | 7 | absence phrasing (rule c), near-bound long prose, unicode/CSV hazards, thin-`what` substance-floor probe |

G2's mirror pairs (spec `mirror_pairs`): (EC-2↔IC-21), (EC-3↔IC-22),
(IC-1↔EC-23), (IC-4↔EC-24), (IC-4↔IC-26), (IC-1↔EC-28).

---

## 4. Dry-run results (zero calls; evidence: `docs/data/wave16_arms/dryrun_v1/`)

### 4.1 Landings vs intent — 43/43 matched

Every criterion in every arm landed at exactly its intended stage with its
intended operator, including the deliberate mislandings: **both G3 traps landed
at EH as predicted** (EC-35 pulled by `abstract`+`mentions`, whole-label operand
because `mentions` defeats the `\bmention\s` extraction regex; EC-36 pulled by
`keywords`, whole-label operand), and G3's negation probe EC-37 rendered
**inverted** as predicted (`exclude equals lang Portuguese` for "not written in
Portuguese"). The 4 raw-probe rows are checked in the probe section, not the
landings table.

### 4.2 Funnels (input 776 everywhere; flagged = kept-but-flagged)

| arm | EH out → surv (flagged) | IH out → surv (flagged) | at EL | at IL |
|---|---|---|---|---|
| arm0_baseline | 16 → 760 (115) | 738 → 22 (0) | 22 | 22 |
| g1_paraphrase | 16 → 760 (115) | 738 → 22 (0) | 22 | 22 |
| g2_polarity | 669 → 107 (1) | 0 → 107 (1) | 107 | 107 |
| g3_stage_stress | 0 → 776 (**776**) | 669 → 107 (1) | 107 | 107 |
| g4_edge_shapes | 4 → 772 (0) | 756 → 16 (0) | 16 | 16 |
| g5_adversarial | 42 → 734 (0) | 704 → 30 (0) | 30 | 30 |

IL input = EL input under flag-only (EL removes nothing; deterministic
operators at EL are not evaluated — recorded as an assumption in every
manifest).

**G1 is funnel-identical to baseline down to every per-criterion impact**
(EC-1 failed 16/met 760; EC-4 missing 126/met 650; IC-3 8/752; IC-4
611/1/148; IC-5 690/70): the paraphrase preserved routing AND deterministic
semantics byte-for-byte at the impact level. The rewording experiment at EL/IL
therefore starts from an identical population — exactly what a decision-
stability comparison wants.

**G2's boundary hazards materialized as predicted:** "before 2018" rendered
`lte 2018` and removed 669 (including the year-2018 band the original keeps —
baseline IC-4 met 148 vs G2 survivor 107; the delta of ~42 en-language 2018
records is the measured incoherence band of the (IC-4↔EC-24) pair). "after
2017" rendered `gte 2017`; on G2's post-EH population it is vacuous (all 106
met + 1 missing) because EC-24 already removed everything below 2019 — the
(IC-4↔IC-26) boundary is observable only cross-arm vs baseline.

**G3: all five EH criteria inert, exactly as intended, with one loud surprise.**
EC-31 (German) and EC-37 (Portuguese) cut 0 — `LANG_MAP` (plugins/_common/
parser.py:80-94) maps only en/fr/es variants, so the operand never meets the
corpus's ISO codes (`de`, `pt`). EC-35/EC-36 (traps) matched nothing
(whole-label operands). EC-38 ("has no DOI") rendered `equals doi ""` — and
came back **unknown on all 776 records**, flagging the entire corpus
(EH flagged = 776): `_match_field` drops falsy operands before dispatch, so
the empty-string operand branch 5 deliberately emits (inference.py:272-274) is
`equals_missing_what` → UNKNOWN for every record (evaluator.py:108-113). See
§8 candidate findings.

**Deterministic-stage MISSING semantics, measured precisely:** a MISSING
target keeps the record and flags it (it does not drop): G3's IH kept 107 =
106 met + 1 missing (A078, blank year), G2's EH kept 107 the same way.

### 4.3 Validator and linter, layer by layer

`_validate_row` (layer 1): **zero errors, zero warnings in all six arms** —
including the F-206 rows E1 (`exclude`@IH) and E2 (`include`@EL), which passed
clean exactly as F-206 records, and the bound thresholds E6 (0) / E7 (1),
accepted at the bounds.

Linter (layer 2): two findings, both instructive:
- **g1/IC-5 `dropped-operand` MISTRANSLATED — a false positive.** The
  paraphrase "Either the title, the abstract, or the keywords mention …" adds
  a field-name "or" the discounter did not fully absorb; the translation is
  measurably lossless (IC-5 impacts identical to baseline: met 70/failed 690).
- **g3/EC-38 `dropped-operand`** on the `equals doi ""` rendering — the linter
  is the only layer that murmurs about the empty operand; nothing calls it
  unevaluable (see §8).

Bundle-read loaders (layers 3-4), raw stage-less probe (g4_raw_probe.csv),
measured:

| loader | result |
|---|---|
| EH `_load_criteria_from_text` | loads R1, R2, R3 (assume-all); **R2's blank operator → `equals`**; **R4 (blank `enabled`) silently absent** (F-208) |
| IH same | identical — the same table silently duplicated at both deterministic stages (F-205) |
| EL `_parse_criteria_harmonized_csv` | **zero criteria**, warning `No EL criteria found (stage=EL).` (F-205 drop-all half) |
| IL twin | zero, `No IL criteria found (stage=IL).` |

### 4.4 Context-budget guard (window 4096, trunc 1500; per criterion; est+reserve vs 4096)

All arms pass at batch 5 AND batch 1. Representative worst cells
(worst_estimate + reserve, batch 5): baseline EC-2 2206+400; G2 EC-23
2316+400; G4 E2 2151+400; **G5 A3 3565+400 = 3965/4096 — headroom 131
tokens, and `max_safe_batch` = exactly 5**: the long-prose criterion (3,279
prose chars, label=what duplication like the shipped rows) makes batch 5 the
largest batch that fits G5's own EL population. Batch 6 would refuse. At batch
1 A3 measures 2106+80. The coordinator's "~3,200-char bound" was verified with
the real renderer as instructed: it is corpus-relative (the recon's §7d bound
was for the 147-record freeze corpus's worst batch); on this arm's population,
3,279 chars sits 131 tokens under the ceiling at batch 5.

### 4.5 Call arithmetic and the 750 ceiling (16b: batch 5 primary, zero re-asks expected)

calls = Σ per llm-criterion ceil(records/batch), cross-asserted against
`RunPlan.requests` on every arm.

| arm | at EL | EL crit | IL crit | calls b5 | calls b1 | wall b5 (est) |
|---|---|---|---|---|---|---|
| arm0_baseline | 22 | 2 | 1 | 15 | 66 | 2.2 min |
| g1_paraphrase | 22 | 2 | 1 | 15 | 66 | 2.2 min |
| g2_polarity | 107 | 2 | 2 | 88 | 428 | 12.9 min |
| g3_stage_stress | 107 | 1 | 1 | 44 | 214 | 6.5 min |
| g4_edge_shapes | 16 | 2 | 1 | 12 | 48 | 1.8 min |
| g5_adversarial | 30 | 4 | 1 | 30 | 150 | 4.4 min |
| **TOTAL** | | | | **204** | 972 | **≈ 30 min** |

**204 batch-5 calls against the 750-call ceiling — 27% of it. No tightening
needed.** Wall clock at the wave-15e measured rates (runJ 528 s / 60 calls =
8.8 s/call batch-5, the slower of the J/K pair; runL 3.47 s/call batch-1;
`wave15e_acceptance_runs.meta.txt:37-39`), **same-machine assumption**: the
15e hardware is unrecorded in artifacts (CPU-only is recorded only for the 14c
capture machine, `wave14c_batch_runs.meta.txt:108-110`) — the maintainer
confirmed the environment above but rates transfer only if 16b runs on the
same machine. A batch-1 replication of everything (972 calls) would NOT fit
the ceiling; a batch-1 arm for the two anchor arms alone (66+66=132) would.

---

## 5. Metric definitions for 16b

**Pairwise decision agreement on shared survivors.** For arms X, Y and stage
s ∈ {EL, IL}: S = records reaching s in both arms (by `local_id`; the FULL
tables carry per-pair evidence JSON). For each mapped criterion pair (c_X,
c_Y) — identity map for G1 (same ids), the spec's `mirror_pairs` for G2 —
agreement is the fraction of S where the mapped decisions agree (identity for
G1; **inversion** for G2 mirrors: meet ↔ not_meet). Report per pair: n(S),
agree%, disagreements listed with both verdicts + confidences + quote states.

**The yardstick** is the wave-15e same-configuration noise floor, measured on
294 pairs: **pair decision flips 0/294, quote_valid flips 0/294, record-outcome
churn 2/147, both flips pure confidence movement**
(`wave15e_acceptance_runs.meta.txt:76-83`; `FIX_WAVE_15E_QUOTE_CLUSTER.md:765`).
Any G1 paraphrase disagreement above ~0/294-order is signal, not noise; the
coordinator's shorthand "the 294/294 v3 noise floor" is more precisely runL's
294/294 not_meet consistency plus the runJ↔runK flip floor above — both cited,
the flip floor is the yardstick.

**G2 coherence mapping under the gate** (defined NOW, per instruction; gate =
`plugins/_common/verdict_gate.py`, `GATE_TABLE` :93-98, actions :116-147):

For a shared record r and mirrored pair (orig, mirror):

| pair | coherent iff | gate reading of the coherent case |
|---|---|---|
| EC-2 (excl@EL) ↔ IC-21 (incl@IL) | dec(EC-2)=meet ⇔ dec(IC-21)=not_meet | both roads lead to review: (exclude, meet) → EXCLUDE suppressed to flag by policy (decliner `flag_only`); (include, not_meet) → SUPPRESS_ABSENCE (decliner `absence`, never auto-acts) |
| EC-3 ↔ IC-22 | same | same |
| IC-1 (incl@IL) ↔ EC-23 (excl@EL) | dec(IC-1)=meet ⇔ dec(EC-23)=not_meet | both keep clean: (include, meet) → MET; (exclude, not_meet) → MET |
| IC-1 ↔ EC-28 | same | also report EC-23↔EC-28 within-arm agreement (two phrasings of "no VR") |
| IC-4 ↔ EC-24 (deterministic) | complement up to the measured 2018 band | incoherence = exactly the year-2018 records + the A078 missing-handling asymmetry; already measured dry (§4.2), no calls needed |
| IC-4 ↔ IC-26 (deterministic) | boundary band year=2017, observable only cross-arm vs baseline | dry-measurable at 16b analysis time from FULL tables |

`uncertain` on either side of an LLM pair is scored as its own category
(neither coherent nor incoherent), reported as a rate — the whitelist keeps it
out of every gate rule (verdict_gate.py:126-127).

**Gate-outcome reporting plan.** Exclusion is off (verified §1b) and EL/IL
remove nothing, so decisions alone under-report. For every pair, 16b records
BOTH: (i) the decision (meet/not_meet/uncertain, confidence, quote validity),
and (ii) the gate ACTION `verdict_action(...)` with its decliner — so
"**would-be-auto-actable**" = count of ACTION_EXCLUDE (suppressed by policy,
decliner `flag_only`) is reported per criterion, separately from flags, and
absence-routed removals (ACTION_SUPPRESS_ABSENCE, decliner `absence`) are
verified to be review-routed with **zero auto-acts** (rule c). The engines'
counts (CLEAN/FLAGGED/SUPPRESSED + `not_evaluated`) come from the run reports
as at 15e.

---

## 6. 16b runplan (NOT executed at 16a)

- **Order:** arm0_baseline (15) → g1_paraphrase (15) → g4_edge_shapes (12) →
  g5_adversarial (30) → g3_stage_stress (44) → g2_polarity (88). Anchors and
  cheap arms first; the expensive mirror arm last, after the harness has six
  clean smaller runs behind it.
- **Batch 5 primary** on both stages, models **explicit `qwen2.5:7b` for EL
  AND IL** (never store-resolved — §1a), temperature 0.0, trunc 1500,
  window asserted 4096.
- **Cache OFF in every arm** (`use_cache=False, cache_in={}`) per F-101's own
  register instruction; byte-identical criteria across arms (baseline ids vs
  G1 ids share nothing byte-identical; still, cache off removes the question).
- **Per-arm declared budgets** = the dry-run counts above (204 total), each
  enforced by the hard budget wrapper; re-asks expected 0 — any re-ask spends
  inside the same declared budget and is reported in the run report.
- **Preflight per arm** (REFUSING): endpoint == `http://localhost:11434/v1`;
  window == 4096; `llm_exclusion_allowed` False both stages; key gate passes;
  corpus sha256 `b36c3cbb…be914`; the arm's harmonized-criteria sha256 equals
  the dry-run manifest's `harmonized_sha256`; prompt versions
  `EL_v3_nullquote`/`IL_v3_nullquote`.
- **WAIT FOR MAINTAINER before any call.** 16b starts only on his explicit
  go, arm by arm if he prefers; the maintainer will upload this document and
  `docs/data/wave16_arms/dryrun_v1/cross_arm_summary.csv` to the coordinator
  for adjudication first.

---

## 7. PREDICTIONS SKELETON (every number derivable today, filled today)

Registered before any live call, in the 15e discipline (predictions first,
then the run tests the design):

1. **Call counts:** exactly 15/15/12/30/44/88 per arm in the §6 order, 204
   total; `calls_made` per run report must equal the arm's declared budget
   with `reasks_made = 0` and `no_answer = 0` (constrained decoding,
   `minItems == maxItems`, llm_client.py:1045-1058; 15e precedent: zero
   re-asks across 414 calls).
2. **Schema violations: 0** (request_shape json_schema throughout).
3. **Batch-1 arms, if any are run: fabricated meets 0** (the v3 zero intercept,
   runL 0/294); at batch 5, fabricated meets on this corpus's maze instrument
   do not apply (different populations), but any meet on G5/A5 ("Maze.") and
   G4/E6 (robot teleoperation) is predicted ≈ 0 by content: the G5 EL
   population (30 head-mounted/HMD records) contains at most 1 maze-adjacent
   record; teleoperation in G4's 16-survivor population ≈ 0.
4. **not_meet quotes: null throughout** (EL_v3_nullquote; 15e: 294/294 null).
5. **Absence routing: zero auto-acts.** Every (include, not_meet, conf ≥ thr)
   verdict — expected the modal outcome for G2's IC-21/IC-22 and G4's E2 on
   most records — routes ACTION_SUPPRESS_ABSENCE, decliner `absence`; every
   (exclude, meet) that passes the strict gate routes ACTION_EXCLUDE and is
   suppressed by `flag_only`. Removed records at EL/IL: **0** in every arm.
6. **G4/E7 (threshold 1.0):** conf_ok requires confidence ≥ 1.0; qwen2.5:7b's
   observed confidence vocabulary in the frozen runs clusters at 0.4-0.9 —
   predicted: **zero MET via E7**; all E7 meet/not_meet verdicts land
   UNCERTAIN unless the model emits exactly 1.0. G4/E6 (threshold 0):
   conf_ok always; outcomes decided purely by decision + quote gate.
7. **G5/A5 (thin what):** any meet must still carry a valid quote of ≥ 20
   normalised chars (`SUBSTANCE_MIN_CHARS`, verdict_gate.py:61-79) — a bare
   "maze"-style quote (≤ 15 chars, the calibrated modal fabrication) fails the
   floor → UNCERTAIN, not SUPPRESSED. Predicted: 0 suppressions via A5.
8. **G5/A3 (near-bound):** guard passes at batch 5 (3965/4096) — predicted to
   run without refusal and without server-side truncation (window measured
   4096, prompt under it); `TokenEstimateDrift` silent.
9. **G5/A4 (unicode):** renders and rounds-trip through csv→json→prompt without
   parse failures (dry-verified through the renderer); predicted zero
   `bad_reply_shape` attributable to the criterion text.
10. **F-205/F-206/F-208 arm expectations, exact:** raw probe repeats §4.3's
    table verbatim (loader semantics are call-free — identical at 16b). E1
    removes exactly 1 record at IH (the `de` record, dry-measured). E2 and the
    F-206 pair evaluate by ctype with correct verdicts; the per-stage report
    surfaces mislabel only. R4 stays silently absent at EH/IH (F-208).
11. **Repeat-noise, if any arm is run twice:** ≤ the 15e floor — decision
    flips 0, quote_valid flips 0, outcome churn ≤ 2/147-order, confidence-only.
12. **Wall clock:** ≈ 30 min total at the 15e batch-5 rate (§4.5,
    same-machine assumption stated there).

---

## 8. New findings from the dry run — candidates for the register (NOT filed;
adjudication belongs to the maintainer/coordinator per the wave discipline)

1. **`equals` with a deliberately empty operand is structurally unevaluable,
   and branch 5 emits exactly that.** The "no DOI" inference
   (inference.py:272-274) produces `equals doi ""`; `_match_field` filters
   falsy operands and answers `equals_missing_what` → UNKNOWN
   (evaluator.py:108-113) — so the criterion can never decide any record, and
   at EH it **flagged all 776** (G3 dry run). An author following the recipe
   gets a criterion that looks routed and is inert while repainting the whole
   corpus PASS_FLAGGED. Candidate row (correctness / validation, likely
   Medium); cross-ref F-109's operator-integrity ledger and F-166's class.
2. **Linter `dropped-operand` false positive on field-name enumerations**
   ("Either the title, the abstract, or the keywords mention …") — fires
   although the translation is measurably lossless (G1 IC-5 impacts identical
   to baseline). Candidate Low (linter hygiene); the discounter at
   linter.py:353-361 misses the "Either…or" form.
3. **For the record (not new rows):** MISSING at deterministic stages
   keeps-and-flags (never drops) — worth a doc sentence somewhere
   user-facing; and the A6 intent rationale predicted "expected cut 49" where
   the measured cut is 42 (`chapter` = 42; 49 is `book`) — an authoring slip
   in the spec's prose, disclosed here rather than edited after the fact; the
   intended stage/operator matched.

---

## 9. Premises corrected (this session): 2

1. **"stage overrides" as the store's container** — the real key is `stages`
   (settings.py:216), with only model/endpoint/batch_size overridable
   (settings.py:356). The maintainer's semantics were otherwise exactly right,
   including IL's missing model key.
2. **"the 294/294 v3 noise floor as the yardstick"** — the 15e noise floor is
   the runJ↔runK same-config comparison: **0/294 decision flips, 0/294
   quote_valid flips, 2/147 confidence-only churn**
   (`wave15e_acceptance_runs.meta.txt:76-83`); "294/294" is runL's all-not_meet
   consistency figure. §5 uses the flip floor as the yardstick and cites both.

Everything else checked out: F-208 as the next free ID and 204→205 rows
(derived tool + suite), the F-208 evidence lines
(parser.py:401-403/:46/:157-158 vs 06_el/screen.py:346-347, re-verified with a
two-sided micro-test before filing), both scratchpad harness paths alive, the
2218/7 suite baseline, the 20-char substance floor, the recon's routing recipe
(43/43 landings), and the coordinator's self-flagged "~3,200-char" figure
verified corpus-relative with the real renderer (§4.4).

---

## STOP

Wave 16a ends here. **Zero live calls were made; `--live` was never invoked;
the cache was never touched; the maintainer's settings store was never
written.** No 16b work — no arm has run live, no budget has been spent, and
nothing in this repository authorizes a call until the maintainer says go
after coordinator adjudication of this document and the cross-arm summary.
