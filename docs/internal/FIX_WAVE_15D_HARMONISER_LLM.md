<!-- SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo -->
<!-- SPDX-License-Identifier: MIT -->

# Fix wave 15d — the harmoniser's LLM path (F-185, F-186)

*Design only, committed before implementation. The invariant every
decision serves: **Harmonise + LLM can never make the table worse than
the no-LLM parse.** Any refinement the validator rejects keeps the
deterministic row for that criterion, with a plain-language named reason
on the completion dialog — never a worker abort, never jargon, never a
lost row.*

## 1. The call shape

**Today [read]:** `plugins/03_harmoniser/llm_refine.py::_llm_refine`
builds one `user` payload carrying ALL rows plus the full criteria text
(≤8,000 chars) plus the column list, and
`::_call_openai_json` sends it in one chat call — `temperature=0`,
`timeout=600`, **no `max_tokens`, no `response_format`, no batching,
no retry** (08 §8c: zero occurrences of batch/chunk/retry/split).
Parsing is shared-module: `plugins/_common/llm_client.py::
_parse_llm_json_object`, the object-variant sibling of EL/IL's
`_parse_llm_json_array` — so this path shares the fence-stripping
parser and nothing else of EL's machinery.

**Why n≥6 breaks [documented, 08 §5, llama3.2:latest]:**

    n=2  678/203 tok   4.5 s   2 rows   parses
    n=4  900/391 tok   6.4 s   4 rows   parses (×3, byte-identical)
    n=6  1,141/3,575   40.4 s  38 rows  NO — repetition loop, stopped
                                        mid-object at 13,039 chars
    n=8  1,384/896     13.8 s  9 rows   NO — eight correct rows, a
                                        hallucinated ninth (IC-5 with
                                        type and stage flipped), no
                                        closing brace

Neither side overflows (§8b: n=8 totals 2,280 tokens,
`finish_reason: 'stop'`); the mechanism is a small model losing the
frame of one long object, with per-token probability compounding in
length (§8a). The degradation is not monotonic — six fails worse than
eight — so no safe limit above four can be stated: **four is the
largest measured-safe count, three consecutive byte-identical
successes** (§8a).

**The redesign.** `HARMONISER_CHUNK_SIZE = 4`, argued from the
measurement and NOT from the schema constraint: 14c's constrained
request killed EL's cardinality failures (F-191's replay: 31/31
omitted pairs filled), and the harmoniser's two measured failure
shapes — a hallucinated extra row, a 38-row loop — are exactly what
`minItems == maxItems == n` makes inexpressible; but whether a given
local model honours `strict` json_schema on THIS payload shape is
[not established] until the live run, and the F-107 fallback path
(server rejects `response_format`) must still be safe. Chunking at
the size measured safe **without** the constraint means both request
shapes sit inside the evidence; the schema is a second lock, not the
load-bearing one.

Per chunk of n rows:

1. **Schema-constrained call** — a new
   `_response_format_for_rows(n)` beside 14c's
   `_response_format_for(n)` in the harmoniser's module: strict
   json_schema, `rows` array `minItems == maxItems == n`, row
   properties `id, stage, type, label, operator, target, what,
   threshold, enabled` all required; `stage` and `operator` enums
   from `plugins/03_harmoniser/parser.py::STAGES`/`OPERATORS` — the
   one vocabulary home the 15c hoist established, not a new copy
   (F-109); `what` an array of strings; `threshold` a string;
   `enabled` a boolean.
2. **`_response_format_rejected` → unconstrained retry** of the same
   chunk, F-107's fallback, at the measured-safe size.
3. **`max_tokens` as a cost bound, named as such** — 08 §8b: not the
   fix (n=8's reply was complete), but it caps the n=6-shape runaway
   that burned 40 seconds; sized from the reply-reserve arithmetic
   per chunk, generous.
4. **Re-ask once for residue**: rows the reply omitted, duplicated,
   or mangled structurally (id mismatch) are re-asked ONCE as their
   own smaller chunk, cardinality = residue size — EL's re-ask
   shape.
5. **Per-row fallback**: any row still unusable after the re-ask —
   and any row the validator rejects (§2) — keeps the deterministic
   input row for that criterion, with a named reason. A chunk whose
   reply never parses falls back whole, one reason per row, carrying
   F-186's diagnostics (§2). **No failure of any chunk aborts the
   worker, and no criterion can lose its row.**

**Budget check on the shape [measured, committed estimator]:** the
one-shot payload for `samples/ic_ec_12.txt` is 5,207 chars →
estimated 1,188 prompt tokens (08 measured 1,384 real at n=8 —
the estimator is conservative in range). Chunked: worst chunk
estimate 880 tokens at n=4; with a deliberately generous 240
tokens/row reply reserve, 1,840 total — far under the 4,096 local
default, and a fortiori under any hosted default.

## 2. The validator seam

**Where the worker aborts today [read]:** `_llm_refine` calls
`_validate_row` per refined row and raises
`RuntimeError(f"LLM refined row invalid ({id}): {errs}")` on ANY
error; `ui.py::_poll_worker` catches worker errors into an
**"Operation failed"** modal quoting the raw validator string. That
is the maintainer's reported live failure — *"llm requires exactly 1
sentence in what"* — a worker abort over one row of one chunk, jargon
included, whole refinement lost. (08's own documented incident was
the OTHER raise, `_call_openai_json`'s JSON-parse message; both
aborts die with this design.)

**The containment.** The 15c refiner already repairs-and-names
stage↔operator mismatches (auto-route, `repairs` list, rendered by
`validate_report.py::compose_dialog`'s adjustments section through
`build_validation_report(repair_notes=…)`). This wave generalises
that surface, and must not regress it — the 15c auto-route runs
BEFORE validation exactly as now, and
`tests/test_stage_routing.py::TestTheRefinerAutoRoute` stays green:

- a refined row that passes validation (after auto-route) is
  **accepted**;
- a refined row the validator rejects is **discarded in favour of the
  deterministic input row**, and a plain-language reason joins the
  notes: *"IC-1: kept your original — the model's rewrite is not a
  single sentence"*, never the validator string;
- the completion dialog gains a **kept-your-original section** beside
  15c's adjustments section, same channel, same pure functions, same
  F-173 tests discipline;
- the LOG gets the full F-186 record where a chunk-level failure
  occurs: `finish_reason`, prompt/completion/total token counts,
  reply length, and the parse exception's own message — all four
  were in hand at the raise site and discarded (F-186's cell); the
  dialog gets the plain sentence, the log the numbers.

**Validator-message inventory [read,
`plugins/03_harmoniser/inference.py::_validate_row`]** — errors:
`Invalid stage` · `Missing id` · `Invalid type` · `Invalid operator` ·
`operator 'x' cannot execute at stage Y: …` (15c) · `Missing target` ·
`Unknown target(s): …` · `between requires exactly 2 values` ·
`llm requires exactly 1 sentence in what` ·
`threshold must be between 0 and 1` · `threshold must be a number`;
warnings: `'what' was not a list; coerced` ·
`{op} usually expects 1 value` ·
`threshold ignored for EH/IH; will be blanked`.

Who meets them decides the rewrite:

- **On the refine path** (the messages describe the MODEL's proposal):
  every error is translated by a reason-naming map to the
  kept-your-original sentence — *"the model's rewrite is not a single
  sentence"*, *"the model pointed it at columns your file does not
  have"*, *"the model picked a stage/operator this software does not
  have"*, *"the model's confidence threshold is not a number between
  0 and 1"* — one entry per validator error, tested as a total map so
  a new validator error cannot fall through to jargon.
- **On the Validate/export path** (the messages describe the USER's
  own cell edit, where naming the field to fix is the kindness):
  they stay technical, with one rewrite —
  `llm requires exactly 1 sentence in what` becomes
  `an llm rule's 'what' must be exactly one sentence` — because it
  is the one string whose grammar reads as machinery even there.

## 3. The budget guard

Measured above: chunking alone keeps every request under a quarter of
the smallest provider default. The guard is wired regardless — 15b
named this path its consumer, and a pathological criteria file (essays
for labels) must refuse rather than truncate.
`enforce_context_budget` is called once before the first chunk, over
the REAL chunk renders (the same builder the calls use), with
`window=resolve_context_window("harmoniser")` — the stage key
`settings.py::LLM_STAGES` already carries — and `hosted` from the
resolved pair as the engines pass it. The refusal message must speak
harmoniser language: `check_context_budget` gains a `noun` parameter
(default `"record"`, the harmoniser passes `"criterion"`) so the
message reads *criteria*, not records; wording lands under the F-173
message tests.

## 4. Prompt version, cache, provenance

**The path has neither cache nor prompt version [measured]:** zero
occurrences in `llm_refine.py`. Both stay absent, argued: a refine is
a one-shot authoring action over a table the user is actively editing
— a cache keyed on the rendered prompt would either miss on every
edit (worthless) or hit across edits (stale rows, F-87's shape in
reverse), and the cost it would save is a handful of calls per
authoring session. No `PROMPT_VERSION` constant is needed where no
cache key exists.

**Provenance is the gap that stays if nothing is added [measured]:**
`exporters.py::_build_manifest` records stage counts and warnings —
nothing about refinement. The manifest's criteria section gains a
`refinement` block, written only when Harmonise + LLM ran in the
session that exported: `{model, refined: [ids], kept: {id: reason},
repaired: [ids]}` — which rows the model rewrote, which kept the
deterministic parse and why, which the 15c auto-route re-staged. No
CSV column changes, no bundle-schema change beyond the additive
manifest key, no golden movement.

## 5. Goldens and the reference table

`tests/golden` does not move: tree `043de53a`, and this wave touches
the LLM-assisted path only — `_infer_criterion_details` and the
no-LLM parse are untouched, so
`tests/test_harmoniser_regression.py` (EXPECTED_RULES and the schema
assertion) proves byte-identity of the deterministic parse before and
after. Nothing in this design renders into `criteria_harmonized.csv`
differently for a table that never met the model. If implementation
finds otherwise, STOP applies.

## 6. The acceptance test

**Suite-provable with doubles (everything except real model
behaviour):** the chunk arithmetic (8 → 4+4; 6 → 4+2; 3 → 3);
cardinality schema built per chunk and rebuilt per re-ask;
`_response_format_rejected` → unconstrained fallback at the same
size; the residue re-ask (once, only for the residue); the per-row
fallback keeping the deterministic row byte-for-byte; the total
reason-map (every validator error string → a plain sentence — a test
iterates the validator's error vocabulary and asserts no raw string
leaks); the never-worse invariant as a property test — for every
scripted failure mode (malformed chunk, wrong ids, duplicated ids,
validation rejects, total garbage, empty reply) the result carries
exactly the input ids, each row either validated-refined or
byte-identical-deterministic, and no exception escapes `_llm_refine`
for row-content reasons; the F-186 diagnostics carried to the log
record; the dialog sections rendering through the pure
`compose_dialog`; 15c's auto-route tests green throughout.

**What only the live run can show:** that qwen2.5:7b under the strict
row schema produces acceptable refinements at chunk size 4 on the
real file, and that the whole flow — `samples/ic_ec_12.txt`,
Harmonise + LLM — completes with **no worker abort**, every row
improved-or-unchanged-with-reason, and the dialog naming each
fallback in plain language: the maintainer's exact live failure,
re-run. Expected call count: 2 chunk calls, plus at most 2 re-asks,
plus one repeat of the whole flow for stability — **≤ 12 calls
budgeted, announced before and after, WAIT FOR MAINTAINER before the
first one.**

## Premise notes for the wrap-up

- `samples/ic_ec_12.txt` carries **eight** criteria (measured; F-185's
  row says the same), not the brief's "twelve criteria of realistic
  prose" — the filename's 12 is not a count. The measurement above
  covers the real eight.
- The brief's "maintainer hit it live at n=8+ (validator jargon)" is a
  SECOND incident, [reported]: 08's documented incident died at
  `_call_openai_json`'s JSON-parse raise, not the validator. Both
  abort paths exist in the tree [read], and both die under §2.
