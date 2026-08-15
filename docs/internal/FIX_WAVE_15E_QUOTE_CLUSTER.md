# Fix wave 15e — the quote cluster (F-195, F-21): the gate keys on direction of harm

*Design only, committed before implementation. The coordinator adjudicates before any
code. The invariant every decision serves: **a verdict justified by absence can never
remove a record on the strength of a substring, because no substring exists to check —
the gate defends what can be proven; what cannot be proven goes to a person.***

---

## Repository state (the step-0 gate, all verified this session)

- **Branch** `main` @ `7fd9084` (the 15d merge), clean, in sync with `origin/main`;
  tag `post-wave-15d` → `7fd9084`. **[measured]**
- **CI** on the 15b/15c/15d merges **[not established]** — the maintainer is checking in
  parallel; this design proceeds per F-165, and the wrap-up requires his recorded
  conclusion before any session-complete statement.
- **Goldens** `tests/golden` tree object `043de53a`, 10 files, **unmoved and not to be
  moved in this session** — movement is *proposed and quantified* in §4, and executed
  only if adjudicated. `git ls-files tests/golden`: `README.md`,
  `criteria_harmonized_v3.1.0.csv`, `eh_filtered_v3.1.0.csv`, `el_cache_v3.1.0.json`,
  `el_filtered_v3.1.0.csv`, `el_input_v3.1.0.csv`, `ih_filtered_v3.1.0.csv`,
  `il_cache_v3.1.0.json`, `il_filtered_v3.1.0.csv`, `il_input_v3.1.0.csv`. **[measured]**
- **Suite** 2124 passed, 7 skipped in 49.65s. **[measured]**
- **Register** 203 rows, max **F-206**, next free **F-207**, open Criticals **ZERO**
  (totals machine-verified by the suite). **[measured]**

**Network disclosure.** I made **4 declared local Ollama calls** (the §3 schema probes:
`qwen2.5:7b` via `http://localhost:11434/v1`, Ollama 0.32.9, temperature 0, tiny
synthetic prompts, default window). No vendor API, no key, no stage run, no model
pulled. Everything else in this document is offline computation over committed bytes.

**The cells this design stands on, read verbatim this session:** F-195 (row + both
churn notes), F-21 (row + the wave-14d note), F-191's fix cell (the three gate
clauses), F-206, F-201's 35/45, all at `docs/internal/diagnostic/03_findings.md`
lines 225, 47, 221, 236, 231; the gate itself at `plugins/06_el/screen.py:868` /
`plugins/07_il/screen.py:870`; the schema at `plugins/_common/llm_client.py:1074-1102`;
the prompt clause at `plugins/06_el/prompt.py:44-50` / `07_il/prompt.py:37-43`
(byte-identical builders, **[measured]** by diff).

---

## §0 — The mechanism at HEAD, verbatim

The gate, identical bytes in both engines (`plugins/06_el/screen.py:868`,
`plugins/07_il/screen.py:870`) **[read]**:

```python
usable = valid_quote and (confidence >= float(c.threshold)) and (decision in {"meet","not_meet"})
```

Polarity is **the criterion's own**, not the stage's (`06_el/screen.py:885`,
`07_il/screen.py:887`: `if c.ctype == "exclude":` …), and both files gate both arms —
`FIX_WAVE_12_FLAG_ONLY.md:152-156`: *"polarity is carried by the criterion's `type`
cell rather than by the stage … a gate on only the expected arm is a gate with a door
beside it."* A usable excluding verdict routes through `_excluded_by` to `failed`
(→ `OUT`) when exclusion is permitted, else to `suppressed` (→ `EXCLUSION_SUPPRESSED`);
an unusable one lands `uncertain` (→ `PASS_FLAGGED` at EL, `REVIEW` at IL). **[read]**

The prompt's quote demand is exactly one clause, in the `Keys per item:` enumeration
(`06_el/prompt.py:44-50`): *"quote (exact substring from that field), span
[start,end]."* On the constrained path the schema makes it structural:
`"quote": {"type": "string"}`, in the `required` list, `strict: True`, non-nullable
(`llm_client.py:1081,1085-1086,1092`). **[read]** So for a `not_meet` justified by
absence, the model **cannot** answer honestly: the fabrication is demanded twice, by
prose and by grammar. F-195's measured rate: 49 invalid quotes on 241 answered pairs
(wave 14c runE); F-21's measured floor: `quote_valid` flipping on 32/294 pairs between
identical runs.

---

## §1 — The truth table

### 1.1 One amendment to the adjudicated principle, from source

The coordinator's table is keyed *"stage polarity × decision × justification"*. The
tree keys the gate on **the criterion's type polarity (`c.ctype`), not the stage** —
quoted above, and deliberately so since wave 12. The table below is therefore keyed
`(ctype, decision)`. This is not a cosmetic relabel; it settles the two questions the
prompt asked:

- **How is polarity known at gate time?** From `c.ctype`, read directly in the
  classification arms (`06_el/screen.py:885` / `07_il/screen.py:887`). F-04's closure
  (`f925625`/`906423a`) guarantees `ctype ∈ {include, exclude}` at these lines — a
  blank or unrecognised `type` cell is **rejected at parse**, not defaulted. **[read]**
- **Does this wave depend on F-206's unvalidated type-vs-stage invariant?** **No.**
  Keyed on `ctype`, the table gives the correct direction-of-harm answer for a
  polarity-mismatched row too (an `exclude` criterion at IL gets rule (a) on `meet`;
  an `include` at EL gets rule (c) on `not_meet` — exactly the F-206 edge cases, and
  exactly the four-arm matrix `tests/test_flag_only.py:176-184` already pins at the
  flag-only level). F-206 can land in any later wave, as the taxonomy hygiene its Low
  severity says it is. **This wave does not need it to land first.**

### 1.2 The table

Vocabulary: *removal-by-presence* = the excluding verdict asserts the text contains
something (`exclude`+`meet`); *keep* = the verdict leaves the record in
(`exclude`+`not_meet`, `include`+`meet`); *removal-by-absence* = the excluding verdict
asserts the text lacks something (`include`+`not_meet`). S = the substance minimum,
§4.3. thr = the criterion's threshold (default 0.6).

| # | ctype | decision | direction / justification | quote | substance | confidence | status if passed | auto-actable | outcome contribution |
|---|---|---|---|---|---|---|---|---|---|
| **a** | exclude | meet | REMOVES / presence | **required, valid** | **≥ S** | ≥ thr | `FAILED` or `SUPPRESSED` | **yes**, iff exclusion permitted (keyed provider or explicit user boolean); flag-only → suppressed, as today | `OUT` / `EXCLUSION_SUPPRESSED` |
| **b1** | exclude | not_meet | keeps / absence | **none** (null expected; if offered, validated + recorded, never gating) | — | ≥ thr | `MET` | n/a (keeps) | toward `PASS_CLEAN` |
| **b2** | include | meet | keeps / presence | **optional** (prompt still invites it — presence CAN be quoted; if offered, validated + recorded, never gating) | — | ≥ thr | `MET` | n/a (keeps) | toward `PASS_CLEAN` |
| **c** | include | not_meet | REMOVES / absence | irrelevant (any) | irrelevant | ≥ thr → `SUPPRESSED`; < thr → `UNCERTAIN` | `SUPPRESSED` | **NEVER** — any provider, any confidence, any quote, any setting | `EXCLUSION_SUPPRESSED` |
| **d** | any | uncertain (model-said) | unresolved | recorded if present | — | irrelevant | `UNCERTAIN` | never | `PASS_FLAGGED` / `REVIEW` |
| **e** | any | uncertain (back-filled, `used: False`, incl. terminal `error`) | non-answer | — | — | 0.0 | `UNCERTAIN` | never | `PASS_FLAGGED` / `REVIEW` |
| **f** | any | — (all target fields empty) | not evaluable | — | — | — | `MISSING` | never | `PASS_FLAGGED` / `REVIEW` (unchanged) |
| **g** | any | — (non-`llm` operator at EL/IL) | not evaluated (F-65) | — | — | — | `UNCERTAIN` + note (unchanged) | never | `PASS_FLAGGED` / `REVIEW` |
| **h** | — | — (zero enabled criteria) | stage no-op (F-34) | — | — | — | — | never | `NOT_SCREENED` (unchanged) |

Row-level outcome precedence is unchanged: `failed` → `OUT`; else `suppressed` →
`EXCLUSION_SUPPRESSED`; else all-`MET`, nothing missing/uncertain → `PASS_CLEAN`;
else `PASS_FLAGGED`/`REVIEW`. Rules (b) and (c) change only *which statuses feed the
lists*, not the precedence.

Three boundary rows made explicit, as asked:

- **Uncertain** (d/e): the decision-whitelist clause `decision in {"meet","not_meet"}`
  survives in **every** rule. An `uncertain` — the model's or the back-fill's — is never
  `MET`, never `SUPPRESSED` (that distinction is pinned:
  `test_flag_only.py:285-311`, *"the gate rejecting a quote and the policy declining to
  act are different facts"*), never actable. Rule (b) does **not** convert high-confidence
  non-answers into keeps: back-fill writes `confidence: 0.0` (`llm_client.py:1734-1742`),
  and the whitelist stops the decision string regardless.
- **Rule (c)'s split at thr**: an absence-removal *above* threshold is policy-declined
  (`SUPPRESSED` — the model asked; we refused); *below* threshold it is gate-refused
  (`UNCERTAIN` — the model didn't convincingly ask). This preserves the suppressed ≠
  uncertain distinction the vocabulary insists on.
- **Flag-only** interacts only with rule (a): rules (b) remove nothing, and rule (c)
  produces the identical outcome under both provider modes — which is the point.

### 1.3 Rule (c)'s home in the outcome vocabulary

`EXCLUSION_SUPPRESSED`'s own contract (`plugins/_common/bundle.py:100-123`) **[read]**:
*"the gate accepted the verdict and policy declined to act on it"*, deliberately
distinct from `PASS_FLAGGED`/`REVIEW` (*"the gate refused the verdict"*). Rule (c) has
exactly that structure — a second **decliner** beside flag-only, not a second meaning.
**Proposed: reuse `EXCLUSION_SUPPRESSED`, with three honesty edits**, rather than mint
a new outcome class:

1. The docstring's first line — *"while flag-only was on"* — generalises to the two
   decliners: provider policy (flag-only, F-145) and justification policy
   (absence-removal, this wave).
2. `_summarize_el_reason`'s suppressed branch (`06_el/screen.py:998-1005`) currently
   hard-codes *"Flag-only is in force for this provider"* — **false under rule (c) with
   a keyed provider**. The reason text must name *which* policy declined:
   flag-only, the absence rule, or both (a keyless absence-removal is declined twice).
   This line is what the human reviewer acts on; it is the load-bearing honesty.
3. The run report gains a named counter for the absence-declined subset (the
   `stage_state` run-outcome vocabulary and the llm counters both carry an explicit
   extension contract — *"a new member, no existing state changed meaning"*,
   `stage_state.py:61-65`), so the counts line can distinguish *"provider not trusted"*
   from *"verdict class not provable"* without a new record-level outcome.

The alternative — a new outcome string (`ABSENCE_REVIEW` or similar) — was considered
and is **recommended against**: every consumer of `OUTCOMES`
(deterministic filters, export gating F-93/F-153, run-summary counts, both Views, the
drill-down vocabulary F-156/F-161, the manifests) would learn a member for a
distinction the reason summary and a counter carry, and the F-153 equivalence tests
would need a third arm. The coordinator may overrule; the consumer list above is the
cost either way.

**Stated plainly, the consequence of rule (c):** IL's criteria are include-typed, so
IL's excluding verdict is *always* absence-justified — **under rule (c), IL auto-
exclusion is retired for every provider and every setting.** The only LLM verdicts
that can remove a record anywhere in the pipeline are presence-justified
`exclude`+`meet` under rule (a). This collides with one recorded contract:
`stage_state.exclusion_allowed`'s *"``setting`` is the user's explicit choice and wins
outright"* (`stage_state.py:525-526`). The resolution this design proposes:
`allow_llm_exclusion` answers a **provider-trust** question and continues to govern
rule (a) exactly as today; rule (c) is an **epistemic** rule about a verdict class —
like the gate itself, it is not a setting, and provider trust cannot manufacture
provability. The a-fortiori argument from the tree: `test_flag_only.py`'s own
rationale records 40/43/4 wrong local-model exclusions **with verbatim quotes above
threshold** — even presence-removals with evidence were 87/87 wrong from local models;
an absence-removal has, by construction, *no* evidence to check, from any model.
IL's log line (`07_il/screen.py:675-678`, *"The provider dialog can permit exclusion,
once the model has been validated"*) and any usage/FAQ copy promising IL exclusion
must be swept in the implementation wave; the promise it half-keeps now belongs to
rule (a) only.

One semantic shift, stated so nobody discovers it later: **`PASS_CLEAN` weakens** from
"every criterion met with a validated quote" to "every criterion met at threshold
confidence; quotes validated where offered". A CLEAN record can now carry a keep
verdict whose quote is absent or invalid (recorded, visible in the modal). The report
never promised more than the gate enforced, but the gate enforced more until now.

### 1.4 The prompt rewrite (the clause this wave exists to change)

The single system-string clause becomes an instruction conditional on the verdict —
wording proposed, adjudication welcome:

> *"quote: for meet, an exact substring from that field that supports the verdict; for
> not_meet or uncertain, null unless an exact substring genuinely supports the verdict.
> span: [start,end] of the quote, or null when quote is null. An empty list is never a
> valid answer: return one object for every item sent."*

The last sentence is F-191's own outstanding prompt-side ask (*"state that an empty
list is never a valid answer"*) — it rides at zero marginal cost; whether it closes
F-191's row is the coordinator's scope call (§7). EL and IL builders stay
byte-identical twins; both `PROMPT_VERSION`s bump (§4.4).

---

## §2 — The IL hazard, re-proven under the new rules

F-191's fix cell records the hazard and its containment at HEAD: a naive
`[]`-to-`not_meet` patch at IL *"asserts 'no record meets this inclusion criterion'
and asks for the whole corpus to be removed on the strength of a two-token reply"*,
held off by **three gate clauses** — `usable = valid_quote and (confidence >=
threshold) and decision in {meet, not_meet}` — plus flag-only. F-195's pressure to
relax the quote clause is what the cell warns *"would supply"* the missing pass.
Rule (b)/(c) now removes that clause for `not_meet`. The hazard must therefore be
re-proven, and it is — **the defence does not thin, it changes kind**:

1. **`[]` is inexpressible on the constrained path** (wave 14c): `minItems ==
   maxItems == n` on the required `results` array, rebuilt per call from the batch
   actually sent (`llm_client.py:1096-1097, 1474-1481`); measured live filling 31/31
   previously-omitted pairs. An empty reply cannot parse out of a conforming response.
2. **On the F-107 fallback path `[]` is expressible again** — and parses to *nothing*,
   which the back-fill records as `used: False, decision: "uncertain", confidence:
   0.0` (`llm_client.py:1726-1742`) after one re-ask of exactly the omitted subset.
   The **decision-whitelist clause survives in every rule of the new table**: an
   `uncertain` passes no rule, keeps nothing, removes nothing.
   `test_constrained_request.py`'s absence-never-a-verdict invariant (lines 264-292)
   pins precisely this and stays green untouched.
3. **Rule (c) makes the classification itself non-actable**: `include`+`not_meet` no
   longer *has* a code path to `failed`/`OUT` — not at any confidence, any quote, any
   provider, any setting. Where today's gate asks "is this removal well-evidenced?",
   the new table answers "this removal class is never auto-acted". A verdict that
   somehow arrived confident and well-formed lands `SUPPRESSED`, i.e. **the record
   survives to a human**. That is categorically stronger than the quote clause it
   replaces, *for exactly the verdict class where the quote clause was checking
   evidence that cannot exist.*
4. **Flag-only remains the provider backstop** for rule (a), unchanged (F-145).
5. **Silence stays visible**: `reasks_made` / `no_answer_after_reask` counters and the
   F-194 no-answer reply capture are untouched.

**What a regression would require** — all of the following at once: reverting rule
(c)'s classification (re-introducing a `failed` route for absence-removals); AND a
patch that maps absence to a `meet`/`not_meet` decision string with a synthetic
confidence ≥ thr (the exact patch F-191's cell forbids — the back-fill's `uncertain`
fails the whitelist otherwise); AND either the constrained path off (server rejecting
`response_format`) or a server ignoring array cardinality; AND exclusion permitted
(keyed provider or explicit boolean). Each is an independent, separately-tested line;
the implementation adds one more pin: extend `test_flag_only.py`'s four-arm matrix
with the new invariant *`allow=True` + `include`+`not_meet` → not `OUT`* (today that
arm asserts `OUT`, lines 335-344 — an intended break, §4.5).

---

## §3 — Schema feasibility, measured live

Four declared calls, `qwen2.5:7b`, Ollama 0.32.9, OpenAI-compat endpoint, temperature
0, tiny synthetic single-record prompts, default window. Full probe script preserved
in the session scratchpad; results **[measured]**:

| probe | schema | instruction | result |
|---|---|---|---|
| P1 | `quote: anyOf [string, null]`, required, strict | not_meet on a non-matching text; "quote MUST be null" | **accepted; emitted genuine JSON `null`** |
| P2 | + `if decision==meet then quote:string minLength 1, else quote:null` | natural meet case | accepted; conforming string quote |
| P3 | same conditional | **adversarial: "set decision meet AND quote null"** | **accepted; emitted `meet` + `null` — the conditional was NOT enforced** |
| P4 | current shape (quote required string) | not_meet on a non-matching text | model **fabricated** a quote, wrapped in added quotation marks that would fail `_quote_in_text` — F-195's mechanism live at probe scale |

P3 is the decisive row: `if/then` is **accepted-but-ignored** — worse than rejected,
because it looks like enforcement until the day it isn't. P1 shows nullability via
`anyOf` is honoured end-to-end.

**The measurement selects the permissive architecture**: schema nullable always
(`quote: anyOf [string, null]`; `span: anyOf [[int,int], null]` — span must go
nullable with it, or a null quote still forces a fabricated span), **gate strict
post-hoc** (the §1 table), **prompt text instructing when to quote** (§1.4). The
`required` list keeps all six keys — required-and-nullable is expressible and was
honoured. Conditional requirement is rejected as a load-bearing mechanism.

Parser consequences, from source: `_safe_str(None)` → `""` (`llm_client.py:301-302`),
so a null quote lands as `quote: ""`, `valid_quote: False`, span already coerced to
`None` unless a 2-int list (`1671-1673`) — **no parser change is needed**, and the
evidence keeps its fixed nine keys. The "offered-and-failed vs nothing-offered"
distinction stays expressible as empty-vs-non-empty `quote`. On the F-107 fallback
path (no schema at all) the prompt instruction alone carries the null convention;
the gate no longer keys on quotes for keeps regardless of path, so the fallback loses
nothing this wave adds.

---

## §4 — The blast radius, quantified exactly

### 4.1 What the replays do (established from source)

`tests/test_el_regression.py` / `test_il_regression.py` drive the real engines with
the golden input + criteria, `cache_in` = the golden cache envelope, key and base-URL
popped so every pair MUST be a cache hit, then assert the produced FULL CSV
**byte-identical** to `{el,il}_filtered_v3.1.0.csv`. The replays resolve provider
UNCHOSEN (conftest isolates the settings store), which is **exclusion-permitted** —
pinned deliberately at `test_flag_only.py:205-216` *because reading UNCHOSEN as
flag-only "would move tests/golden/el_filtered and il_filtered"*. So the goldens
contain real `OUT` rows, and the gate change replays against them offline,
deterministically, with no network. **[read, verified]**

### 4.2 The filtered goldens under the new table — computed offline from committed bytes

Recomputed this session from `{el,il}_filtered_v3.1.0.csv`'s own evidence JSON joined
with `criteria_harmonized_v3.1.0.csv` (script preserved in scratchpad; every number
**[measured]**):

**EL (85 records; criteria EC-2, EC-3, both exclude-type, thr 0.6):**

- Evidence census at HEAD: 162 `not_meet` valid+confident (`MET`), 5 `not_meet`
  under-confident (`UNCERTAIN`, stay), **2 `not_meet` confident with invalid quotes**
  (`UNCERTAIN` today), 1 `meet` valid+confident (`FAILED` — the audited A499
  exclusion).
- Under rule (b1) the 2 invalid-quote keeps become `MET`: **A328** and **A345** flip
  `PASS_FLAGGED → PASS_CLEAN`. Distribution **77/7/1 → 79/5/1**.
- The single `OUT` (A499, EC-2, quote 102 normalised chars, valid) **passes rule (a)
  at every substance minimum in the 0–30 sweep** — the EL exclusion does not move,
  so `il_input` (84 = 85 − 1) does not move either.
- **N = 2 records flip; el_filtered moves** (outcomes, met/uncertain id-lists, two
  evidence statuses, two reason summaries).

**IL (84 records; IC-1 include-type llm, IC-5 `contains` → F-65 `UNCERTAIN` on all 84):**

- Evidence census at HEAD: 43 `meet` valid+confident (`MET`), **5 `meet` confident
  with invalid quotes** (`UNCERTAIN` today), 30 `not_meet` under-confident
  (`UNCERTAIN`), **4 `not_meet` valid+confident (`FAILED` → the golden's 4 `OUT`)**,
  2 `not_meet` under-confident+invalid.
- Rule (b2) rescues the 5 keeps: **A247, A345, A545, A615, A622** — evidence status,
  `il_met_ids`/`il_uncertain_ids` move; outcomes stay `REVIEW` (IC-5's F-65
  `UNCERTAIN` pins every IL record below `PASS_CLEAN` on this corpus).
- Rule (c) reclassifies the 4 removals-by-absence: **A452, A636, A642, A757** flip
  `OUT → EXCLUSION_SUPPRESSED`. **The IL survivor set changes: 80 → 84.**
  Distribution **80 REVIEW / 4 OUT → 80 REVIEW / 4 EXCLUSION_SUPPRESSED**.
- **N = 4 records flip outcome + 5 evidence-only; il_filtered moves.** IL is the last
  stage; nothing cascades further.

**Both decision goldens move. The history, corrected from `git log --follow`
[measured]:** the two *cache* goldens have moved **three times** — wave 2 `c8d2fb3`,
wave 9 `b01ec25`, wave 14c `0becf95`, every one an argued re-key with values proven
byte-identical — and the four *decision* files (`{el,il}_filtered`, `{el,il}_input`)
have **never moved**: one commit each, `4fbe8fd`, the original capture; their
byte-identity was the proof-check of all three re-keys. What this wave proposes is
therefore not the third argued golden move but **the first argued move of the
decision-recording goldens in the project's history**. The numbers above are the
whole of it; the maintainer decides with them in front of him. Nothing moves in this
session.

### 4.3 The substance minimum (F-21's floor), measured against the evidence

Swept at 0/10/15/20/30 normalised chars over every committed presence-removal:

- The golden's one real exclusion (A499, 102 chars): survives every value ≤ 102.
- The 45 fabricated meets (14d, three batched runs): gate-passing fabrications
  **35 → 31 → 31 → 14 → 14** at smin 0/10/15/20/30. The elbow between 15 and 20 is
  real: qwen's modal fabricated quote is `"virtual reality"` — exactly 15 normalised
  chars (nine of runI's eighteen). **A 20-char floor kills 21 of the 35 gate-passing
  fabrications on frozen evidence** while touching no genuine exclusion in any
  committed artefact.
- **Proposed: S = 20**, with F-21's own caution quoted beside the constant: against a
  model with no honest quote, a substance floor buys *a more convincing fabrication*;
  the floor is hygiene for rule (a), and F-201's fix cell — not this constant — stays
  the quality lever (§5).

### 4.4 PROMPT_VERSION and the cache goldens

- **The bump is confirmed and doubly forced**: the template bytes change (§1.4), so
  the rendered prompt in every key changes; and the semantics change even where a
  server rejects the schema. `EL_v2_jsonschema → EL_v3_nullquote`,
  `IL_v2_jsonschema → IL_v3_nullquote` (names for adjudication). User caches in the
  wild: old entries go inert, exactly as at 14c — no eviction, no misservice.
- **Premise corrected: the committed re-key tool does NOT cover this migration as it
  stands.** `tools/rekey_cache_goldens.py --migration prompt-version` assumes *"the
  old key uses the SAME five-member formula … with only `prompt_version` differing"*
  (tool lines 397-404) — true at 14c, where the template moved no byte. This wave
  moves template bytes, so old keys hash prompts the new builder will never render.
  The tool needs a **third migration mode** that freezes the v2 system string and
  renders old keys with it — the exact pattern `_old_cache_key` already uses to
  reimplement the pre-F-89 formula from git history. Values stay verbatim; the five
  obligations hold; `VALUE_MULTISET_SHA256` survives, as its own comment demands.
- **The standing objection, argued rather than stepped around**: wave 2's changelog
  records *"any future change to the prompt template … needs a real re-capture."* The
  answer with numbers: the cached values are the answers gpt-4o-mini actually gave to
  the v2 prompt — a re-key keeps the replay's claim honest as *"the gate, over
  recorded evidence"*, which is precisely what a gate-change wave needs pinned; the
  filtered goldens then move by exactly §4.2's computed flips, regenerated offline by
  the replay itself, no API call. The alternative the wave-2 rule names — a live
  re-capture via `tools/capture_el_il_goldens.py` — needs a funded key, ~51 batch-5
  calls (170 EL + 84 IL pairs), and moves the goldens by an *unbounded* amount (new
  model behaviour under the new prompt, including its nulls). Both options are on the
  table with their numbers; **the maintainer chooses**. The design recommends the
  re-key + offline regeneration, with the live half pinned by §6's acceptance run.
- Also sanctioned-and-expected: both `EXPECTED_PROMPT_HASH` constants re-captured via
  `--print-hashes`, both `EXPECTED_PROMPT_VERSION` constants updated.

### 4.5 The test break matrix (what the suite says when this lands)

From the committed tests, verified: **breaks and must be updated deliberately** —
`test_el_regression`/`test_il_regression` byte-identity (goldens move, §4.2) and
prompt-hash + prompt-version constants (§4.4); `test_golden_rekey`
(`test_every_committed_key_is_reproduced`, `--verify` clean, capture-endpoint pin)
until the third migration mode lands and runs; `test_flag_only`'s
`allow=True → all four arms OUT` (lines 335-344) — the two absence arms now assert
`SUPPRESSED`, the intended §2 invariant; `test_constrained_request`'s schema-shape
pins where they assert `quote`/`span` non-nullable. **Stays green untouched**:
`test_evidence_gating` (`_quote_in_text` unchanged), `test_wave14d_invariance_freeze`
and both other freeze suites (committed bytes), the whitelist suite, the re-ask
protocol suite, `test_no_v1_prompt_version_key_survives` (v1 strings unchanged in the
committed cache).

**STOP.** Step-1 ends at this line: no code, no golden byte, no schema change in this
session. The numbers above are the adjudication input.

---

## §5 — What this wave does not fix, in so many words

- **F-201 is untouched.** Fabricated presence-removals pass rule (a)'s strict gate
  *with valid quotes* — 35 of 45 did, and rule (a) is deliberately unchanged in kind.
  The substance floor cuts the frozen-evidence fabrications 35 → 14 at S=20 (§4.3),
  and that number must be read with F-21's own caution: it filters today's lazy
  fabrications, it does not stop tomorrow's better ones. **F-201's own fix cell —
  batch 1 as the accuracy setting, two-model agreement, the EC-2 wording — remains
  the quality lever.**
- **The decision-noise floor remains.** Recomputing both frozen batch-5 runs under
  the new table (offline, this session, **[measured]**): same-configuration churn
  **24/147 → 13/147**. The eliminated 11 are the quote_valid-driven flips; the
  surviving 13 are genuine decision and confidence churn (8 meet↔not_meet pairs,
  4 threshold-crossing confidence swings, 1 not_meet↔uncertain) — F-197's open
  decision half, owned by F-201.
- Untouched besides: F-22 (the gate's Unicode/case blindness — and note the rescued
  IL keeps A247/A345/A545/A615/A622 look exactly like its casualties), F-100
  (confidence semantics), F-28 (goldens captured at non-default settings).
- **The claim this wave CAN make, measurably**: the junk-quote manufacture on
  `not_meet` ends — the prompt stops demanding it (§1.4), the schema stops requiring
  it (§3), and the gate stops reading it (§1.2 b1) — and the CLEAN/FLAGGED churn
  collapses from 24/147 toward the 13/147 decision-noise floor, with the
  quote_valid-driven component identically zero.

---

## §6 — The acceptance experiment (designed now, run after implementation)

**HO-1 — the re-screen.** *Corpus*: the archived 147-record post-IH bundle in the
maintainer's `_archive_bundles/` (repo sibling, outside version control — the freeze
metas record the digests: e.g. `bundle_runG_sha256=0bd1604a…` in
`wave14d_invariance_runs.meta.txt`; the maintainer locates the zip by digest).
*Comparability caveat, stated*: this bundle predates the 15c/15d routing fixes (the
current chain from the same inputs is 776→16→760→738→22, per the F-168 banner on both
freeze metas) — it is a **regression corpus chosen for identity with the frozen 14d
baselines**, not a representation of the current pipeline's own chain; EL's criteria
set on it (EC-2, EC-3, both llm) is what runs at HEAD, unchanged.

*Configuration*: `qwen2.5:7b`, `http://localhost:11434/v1`, temperature 0,
`trunc_chars` 1500, **batch 5**, cache off, flag-only default — byte-for-byte runG/H's
recorded provenance except `prompt_version`. **60 calls.**
**WAIT FOR MAINTAINER before the first call**; budget announced before and after.

*Measures and predictions* (comparators all **[measured]** from the frozen artefacts
this session):

| measure | frozen comparator | prediction under 15e | falsifier |
|---|---|---|---|
| invalid non-null quotes on answered `not_meet` | runE **49/241** (47 nm + 2 m); runG **54/278**, runH **62/281**, runF **100/294**, runI **44/276** | collapses toward zero — the honest answer (`null`) becomes expressible; residual = models that quote anyway | fraction not materially below the comparator band |
| fabricated meets | runG **15**, runH **12** /294 | unchanged-ish; **must not rise** (the prompt change touches only the not_meet clause) | a rise above the 15/12 band |
| CLEAN/FLAG/SUPPRESSED | runG 86/48/13, runH 86/52/9 | CLEAN rises sharply (frozen-evidence recomputation: ~128-132/~6/~9-13) — direction is the claim, not the exact counts (decisions resample live) | flags NOT dominated by decision-noise; quote-driven flags persisting |
| repeat churn (**if the maintainer grants a second run, +60 calls**) | **24/147** | **≤ ~13/147**, with the quote_valid-driven component zero | churn not materially below 24 |

**The batch-1 arm, priced as asked (+294 calls):** F-195's row records its causal
claim as **[inferred]** and names the settling experiment in its own evidence cell —
*"make `quote` optional or `null` for `not_meet`, re-run the same corpus and model,
and measure the change in the `valid_quote is False` fraction."* Batch 1 is the clean
instrument for it: zero fabricated meets in 294 frozen judgments, so **every** invalid
quote at batch 1 is pure F-195 pressure — comparator runF **100/294**, prediction
near-zero, and the row's [inferred] becomes [measured] either way the result falls.
Worth its price if the maintainer wants F-195 closed *as a measured cause* rather than
as a removed pressure; the wave's fix does not depend on it. **The maintainer
chooses: 60 / 120 / 414 total calls.**

**HO-2 — the frozen-baseline guard**: after any golden decision, `python -m pytest
tests/test_wave14d_invariance_freeze.py tests/test_wave14c_batch_freeze.py -q` must
stay green untouched — the frozen evidence is history, not a fixture, and this wave
must not restate it.

---

## §7 — Candidates for intake at adjudication

- **F-207 candidate** (hygiene, XS, F-50's class): `plugins/07_il/screen.py:896` — the
  comment `# (not expected in IL) treat as include` sits on the include arm that
  IL's own comment eleven lines up (881-883) correctly calls *"IL's own arm"* — a
  surviving `s/EL/IL/` twin artefact that inverts the truth at the exact lines this
  wave edits. (Sibling of the same class, for the same commit or a note: IL's
  reason-summary helper is named `_summarize_el_reason`.)
- **F-191 scope call**: §1.4's last sentence lands F-191's outstanding prompt-side
  ask verbatim. Whether 15e's implementation closes F-191's row (its structural halves
  landed at 14c/`8da350f`) or leaves it to its own pass is the coordinator's call.
- **Documentation sweep rider** (implementation-wave task): IL's flag-only log line
  and any usage/FAQ passage promising provider-dialog exclusion at IL (§1.3's
  consequence).

## §8 — Premises corrected (standing instruction; cumulative 20 → 25)

1. *"49/241 not_meet verdicts carried invalid quotes at batch 5"* → **49 of 241
   answered pairs** carried invalid quotes on the wave-**14c** runE artefact (not
   14d), and the split is **47 `not_meet` + 2 `meet`** **[measured]** from
   `docs/data/wave14c_batch_runs/`.
2. *"24/147 records flip CLEAN/FLAGGED between identical runs"* → 24/147 flip
   `el_outcome`; **16 are CLEAN↔FLAGGED, 8 involve `EXCLUSION_SUPPRESSED`**
   (9 C→F, 7 F→C, 4 S→C, 2 C→S, 2 S→F) **[measured]**.
3. *"that is the third argued golden move in the project's history"* → the **cache**
   goldens have already moved three times (waves 2, 9, 14c — argued re-keys, values
   byte-identical throughout); the **decision** goldens have moved **zero** times
   (single capture commit `4fbe8fd`). This proposal is the **first** decision-golden
   move — a stronger claim on the maintainer's attention than the premise implied,
   not a weaker one. **[measured]** via `git log --follow`.
4. *"the two cache goldens re-key as in 14c"* → the committed migration covers a
   version-string relabel over an **unchanged** template only; 15e changes template
   bytes, so a third migration mode (frozen v2 renderer, `_old_cache_key`'s pattern)
   is required before "as in 14c" is true. **[read]** from the tool.
5. The adjudicated principle's key — *"stage polarity"* — → the gate keys on
   **criterion-type polarity** (`c.ctype`), per `FIX_WAVE_12` and the code at both
   `screen.py` sites; keyed as the principle literally states it would re-import
   F-206's unvalidated stage↔type invariant as a dependency. Keyed on `ctype` (this
   design), the wave has **no dependency on F-206**, and the F-206 edge cases get the
   correct direction-of-harm row by construction. **[read]**

*(Premises that held under verification, for the record: HEAD/tag/tree/suite/register
state, exactly as gated; F-191's three clauses, verbatim; F-201's 35/45, re-derived;
the two-move-together constraint, quoted in all three cells it lives in.)*

---

**STOP — awaiting adjudication.** No implementation accompanies this document. The
implementation prompt follows the numbers.
