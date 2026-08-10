# metaScreener — Wave 7: cache integrity, and the last open Critical

The first code wave since wave 5. Three findings, three commits, one new register row.
**F-86 was the register's only open Critical; the register now has none.**

Standing rules as before: branch `fix/wave-7-cache-integrity` off `main` (@ `83ac1aa`,
tagged `post-wave-6`), one commit per finding, suite green after every commit, no golden may
move — a SHA-256 manifest of `tests/golden/` was recorded at step 0 and re-verified at
close-out alongside `git diff main...HEAD -- tests/golden/` — and **no merge, no tag, no
push**. Coordinates are `path::symbol`, never line numbers.

Scope was held. Readiness probes, the error classifier, case-folding of the decision
whitelist, timeouts, GUI, provenance fields and endpoint work were all left alone. Two
things found along the way were recorded rather than fixed: one as a register row (F-133),
one as an observation in this document with the reason it did not become a row.

---

## Step 0 — the gate

The coordinator's ledger was right on every point.

| Check | Expected | Found |
|---|---|---|
| HEAD | `83ac1aa`, post-wave-6 | `83ac1aac82a3ce95003adb62ab5699a4db3618ae`, tag `post-wave-6` |
| Branch | `main` | `main` |
| Tree | clean | clean (`git status --porcelain` empty) |
| `origin/main..main` | 0 | 0 |
| `main..origin/main` | 0 | 0 |
| Suite | 422 passed, 4 skipped | **422 passed, 4 skipped** |

Nine files under `tests/golden/`, hashed at step 0 and re-verified at close-out. See
*Close-out*.

The three register rows were read before any code was written. **The fix cells agree with
the brief** on all three, with one divergence worth stating up front: F-104's Suggested-fix
cell already says *"Consider also making `_verify_sha256_map` report digests whose member is
absent, which closes the general case."* The brief asks for that to be established and
reported, not fixed, and made a register row if warranted. Both are right, and together they
describe a trap: closing F-104 on the one-line condition would have left the general case
recorded only inside a row marked `(done)`, where nothing would ever look for it again. It is
now **F-133**, and F-104's cell says so.

---

## Part 1 — F-86, the Critical

### What was reproduced, and how

Nothing here was taken on the diagnostic's word. `tests/test_cross_batch_substitution.py`
drives the real `plugins/_common/llm_client.py::run_m1_llm_for_criterion` through a scripted
stand-in for the OpenAI client that returns a chosen payload per call and records the a_ids
each call was actually sent, so the batching a test claims to have arranged is asserted
rather than assumed.

Both routes fired on the first attempt, exactly as described:

**Forward.** Batch 1 (`A000`–`A002`) answers its own three records honestly and appends a
fourth object naming `A004`, which is in batch 2. Batch 2 then omits `A004`.

```
A004 -> {'used': True, 'decision': 'meet', 'confidence': 0.95, 'field': 'title',
         'quote': 'Record 4 on virtual reality rehabilitation',
         'span': [0, 42], 'valid_quote': True}
```

**Backward.** Batch 1 answers `A000` `not_meet`; batch 2 answers its own records and
additionally claims `A000` meets the exclusion criterion, quoting `A000`'s real title. The
unguarded parse-loop write replaced the correct verdict outright — `assert 'meet' ==
'not_meet'`. No omission anywhere was required.

**At `batch_size = 1`: confirmed, from source and by test.** The acceptance map was built
from the whole `items` list before `chunked(items, batch_size)` was ever called, so batching
had no bearing on what the guard would admit. A single-record call for `A000` filed a
`meet` verdict against `A001` and it was accepted with `valid_quote: True`. The severity
assessment stands.

**The persistence half.** Driving the real EL engine — real prompt builder, real cache keys —
the fabricated verdict was written back under `A004`'s own legitimate key, and a second run
against a client that answers honestly reproduced the exclusion:

```
F-86 persistence: the second run reproduced the exclusion of A004 from cache alone
(0 API call(s) made). Re-running is the user's remedy and the cache defeats it.
```

### Before / after

| | before | after |
|---|---|---|
| `tests/test_cross_batch_substitution.py` | **8 failed, 6 passed** | **14 passed** |
| full suite | 422 passed, 4 skipped | **436 passed, 4 skipped** |

### The fix — `3f37f17`

`plugins/_common/llm_client.py::_field_texts_by_id` builds the map from **one batch**, and is
called inside the batch loop, per attempt, because the adaptive-split path rewrites
`cur_batch`. Both the acceptance guard and the quote-validation text read from it, so neither
can reach a record the call did not send — the invariant is structural rather than
remembered. The parse-loop write is now guarded the way the back-fill always was, so the
first answer for an id wins.

Six of the fourteen tests exist only to prove the guard rejects foreign ids **and nothing
else**: ids in the current batch, answers returned out of prompt order, invented ids, blank
ids, the unused back-fill that turns a non-answer into a flag, and the end-to-end EL run.

### Two refinements the register's own text does not carry

Both narrow the finding without weakening it, and both are recorded here because a reader of
the row alone would get them wrong.

1. **The forward route needs the owning batch to *complete and omit*, not merely omit.** The
   terminal-failure arm of `run_m1_llm_for_criterion` is a *second* unconditional overwrite:
   on exhausted retries it rewrites every id in `cur_batch` with `used: False`,
   `decision: "uncertain"`, `error: …`, which fails the evidence gate. So a 429-exhausted or
   transport-failed owning batch would have destroyed the fabrication. There is also a third
   survival route no document lists: if cancellation trips before the owning batch is
   reached, `_Cancelled` unwinds to `return out` (the F-26 keep-what-was-paid-for behaviour)
   carrying the fabrication with it. The backward route remains unconditional.

2. **`items` at both call sites is `to_call`, the criterion's *uncached* subset.** "Built
   from the whole `items` list" is exactly true of the function and reads wider than the live
   population: the substitutable set was per-criterion and shrank as the cache warmed, and on
   a fully-warm replay the function is not entered at all.

A third point, on rate rather than reachability: at `batch_size = 1` the prompt contains one
`a_id`, so the model must **invent** a foreign id rather than copy a visible neighbour. The
guard is equally defective at every batch size; the trigger rate is not equal. The register's
"it fires at `batch_size = 1`" is true of the code and silent on the rate.

---

## Part 2 — F-87

### Half one — the write-back

`tests/test_negative_caching.py` runs both engines against a client that raises
`RuntimeError("Internal server error (500) from api.openai.com: upstream timeout")` — chosen
because it matches neither the rate-limit nor the oversize test, so the split and
truncation-reduction arms are skipped and the batch goes straight to the terminal back-fill
that stamps `error` on every item.

Before the fix, every one of those non-answers was cached, the SDK exception text was
serialised into the exported cache member, and **the second run made no API call at all** —
the failures were served back as verdicts. The register's characterisation is exact: the
user's remedy is to re-run, and re-running is the one action the cache defeats.

### Half two — the duplicate-`local_id` companion

Reproduced at **`OUT = 2/3` in both stages**, matching the register's measurement:

```
F-87 companion: 2 of 3 rows were excluded. Two rows share local_id A001, so a single
verdict was applied to both, and the first of them — an interview study of ward
handover — was excluded on a quote that appears nowhere in its own text.
Outcomes: ['OUT', 'OUT', 'PASS_FLAGGED']
```

One detail the fixture had to get right, recorded because getting it wrong makes the defect
vanish rather than fail loudly: both `id_to_item` and the per-batch text map are built by
assignment, so the **last** row under a duplicated id is the one whose text the quote is
validated against. Put the quote in the first duplicate and it fails validation, the verdict
degrades to uncertain, and nothing fires.

### Before / after

| | before | after |
|---|---|---|
| `tests/test_negative_caching.py` | **20 failed, 8 passed** | **28 passed** |
| full suite | 436 passed, 4 skipped | **464 passed, 4 skipped** |

### The fix — `d98d625`

`plugins/_common/llm_client.py::_is_cacheable_evidence` is one predicate gating both stages'
writes. `error` is judged by **key presence**, not truthiness — it is set from `str(e)`, and
an exception raised with no message stringifies to `""`. `used` must be explicitly `True`;
the read side's `setdefault("used", True)` is for cache files written before the field
existed, and the asymmetry is deliberate. The cost of refusing to cache a doubtful entry is
one more API call; the cost of accepting one is a permanent false verdict.

The duplicate-id guard is now in both engines. Ambiguous ids are **withheld from the LLM
entirely** rather than asked about and discarded: two different records under one `a_id` make
any answer unattributable, so the call would be unusable and billed. With no verdict to look
up, the row loop's existing evidence gate degrades those rows to UNCERTAIN, which flags them
for a human instead of acting on them. No row is dropped from the output, and the duplicated
ids are named in the stage log. Both upstream dedups stay, and a test pins the loader's.

### Residual, recorded not fixed

**The gate is write-side only.** Entries arriving in `cache_in` are carried through
untouched, and the read path still serves them. So a bundle captured before `d98d625` keeps
whatever poison it already holds. This is deliberate on two grounds: silently deleting a
user's accumulated cache would be its own kind of data loss, and filtering `cache_in` would
move the goldens, which this wave may not do. A test pins the carry-through so the choice is
visible rather than incidental.

---

## Part 3 — F-104

### Reproduced

`tests/test_cache_member_preservation.py` seeds a bundle that already carries a cache member
with a correct digest, then exports with `cache_text=None` — what the UI passes when "Use
cache" is unticked. Before the fix the member was gone from the output zip, in both stages,
flat and root-prefixed. And the second half of the row reproduced with it:

```
F-104: the manifest records digests for members the bundle no longer contains:
['cache/EL_cache.jsonl']. _verify_sha256_map iterates the members that are present,
so it reports the bundle intact.
```

### Before / after

| | before | after |
|---|---|---|
| `tests/test_cache_member_preservation.py` | **6 failed, 6 passed** | **12 passed** |
| full suite | 464 passed, 4 skipped | **476 passed, 4 skipped** |

### The fix — `bb9671b`

One condition, expressed as a deletion. `skip_exact` is seeded from `written`, and `written`
contains `cache_rel` exactly when `cache_text is not None` — so the general rule, *skip only
what we are replacing*, already covers the cache member. The unconditional
`skip_exact.add(root + cache_rel)` was the only thing overriding it.

Two directions the condition must get right, both tested: `cache_text=""` is a deliberate
reset and still replaces; `cache_text=None` preserves.

*Noted, not changed:* `skip_exact.add(root + "data/input_errors.csv")` is now equally
redundant, since that member is always in `written`. It is harmless and out of scope.

### `_verify_sha256_map` — established, reported, not fixed

**It is a defect in its own right, and it is now F-133 at Medium / XS.**

The check iterates the members it is handed and looks each up in the manifest, so the
manifest's key set is never the iteration domain and an entry naming an absent file is never
examined. `_refresh_sha256_map` then carries that entry into every later manifest, because it
seeds from the incoming map and only assigns keys present in `written` — so the false claim
is permanent once made.

**Nothing compensates**, checked exhaustively: both production callers build their member map
from `zf.namelist()`; EH/IH's inline check is narrower still, testing two named rels and only
`if rel in sha_map`; `plugins/_common/bundle.py::_load_bundle` verifies nothing; the terminal
workbook reads no manifest field and turns a missing member into a silent fallback
(`plugins/07_il/ui.py::_load_master_rows`) or a header-only stage sheet; and no test covers
it.

**Medium, not High.** After `bb9671b` there is no remaining *in-code* path that drops a
member while its digest survives — F-104 owned the only one — so the live triggers are
external: a hand-edited zip, a partial extract-and-rezip, a truncated transfer, or the next
conditionally-written member. Not Low either: `README.md`'s claim that "a modification to the
record set between stages is detectable" is false for the one modification that removes
rather than alters, and two of the deletable members degrade the terminal deliverable
silently — losing `data/original.csv` re-arms F-70, and a missing `reports/{st}_FULL.csv`
yields an empty stage sheet.

One trap for whoever fixes it, recorded in the row: **prune at the writer, not in
`_refresh_sha256_map`.** That function's `written` is only the current stage's subset, so
pruning to it would delete every legitimate carried-forward entry. The writer knows the
output namelist; the checker's job is to report.

---

## Part 4 — the two questions

### Q1 — do the committed goldens contain cached non-answers?

**No. Zero, out of 254 entries.**

| | `el_cache_v3.1.0.json` | `il_cache_v3.1.0.json` | total |
|---|---:|---:|---:|
| entries | 170 | 84 | **254** |
| carrying an `error` key | 0 | 0 | **0** |
| `used` is `false` | 0 | 0 | **0** |
| `used` absent | 0 | 0 | **0** |

The key set is rigidly uniform — `confidence, decision, field, quote, span, used,
valid_quote` — across all 254, with no eighth key anywhere; the literal substring `error`
does not occur in either file's bytes. Every entry is `used: true`.

So **no non-answers were cached as verdicts during the capture that produced the published
validation study.** `docs/llm-evaluation.md` is not exposed on this axis. Characterisation:
decisions are `not_meet` 205 / `meet` 49 (EL is 169/1, IL 36/48); `valid_quote` is true for
245 and **false for 9** — those nine are genuine model answers whose quote failed validation,
which is the gate working, not negative caching; `field` is `keywords` for all 254.

*A format note, since the brief and the register both describe these as a cache:* they are
**not** the JSONL that `_dump_cache_to_jsonl` writes into a bundle. They are pretty-printed
JSON objects, `{"_invocation", "cache"}`, produced by `tools/capture_el_il_goldens.py`.
`_load_cache_from_jsonl` returns an empty dict if pointed at one. This is by design and the
diagnostic already documents it — but it matters for Q2, below.

### Q2 — can F-86 substitution be detected from the committed artefacts?

**Partly — and the brief's reasoning is wrong in one specific, load-bearing place.**

The brief's chain was: the quote is a valid substring of the record it was filed against, so
a substring check cannot detect it; detection needs the batch composition of the original
call; the cache key hashes a synthetic one-item prompt, so batch composition is invisible;
therefore undecidable. Links one and two hold. **Link three does not.**

**`batch_size` is committed.** Both golden envelopes carry
`_invocation: {"batch_size": 5, "model": "gpt-4o-mini", "trunc_chars": 4000}`, it is read
back by both regression tests, and `tools/capture_el_il_goldens.py` sets it. The capture ran
with `cache_in` empty, so the batches are the contiguous 5-slices of the input CSV. Batch
composition is not invisible; it is fully reconstructible. The adaptive-split arm can only
*refine* that partition — `batches[bi] = cur_batch[:n]` with the remainder inserted at
`bi + 1` — never merge it, so the 5-slice is a sound upper bound on co-batch membership.

**Cache-key inversion works exactly.** Recomputing `_cache_key` for every (record, criterion)
pair from the committed corpus and criteria resolves **254/254 keys — 170/170 EL and 84/84
IL, zero orphans, zero expected-but-absent.** EL 170 = 85 records × 2 llm criteria; IL 84 =
84 × 1 (`IC-5` is `contains` and correctly absent).

**But inversion cannot convict, and that is the brief's point surviving in a different
place.** `run_el_screen` keys the write-back from the *substituted* record's own one-item
rendered prompt, so a fabricated verdict lands on a perfectly legitimate key. Both hypotheses
predict the observed key set. The clean result is uninformative, not exculpatory. Nor does
anything else attribute a verdict to a call: the cached value has exactly seven keys, no
batch index, no call id, no timestamp, no token counts; `out[(a_id, cid)] = {…}` is a
destructive overwrite that records nothing about how many times a key was written; and
insertion order — the one channel that would catch the forward route — is destroyed at write
time, because the capture tool dumps with `sort_keys=True` over SHA-256 keys. No run log was
ever committed, and none was deleted.

**The route that does work runs in the exculpatory direction.** For a substituted verdict to
pass the gate, the quote `Q` filed against record `X` must be a substring of `X`'s text. For
the model to have emitted `Q` at all, `Q` must have come from a record the call actually
carried — some `Y ≠ X`. So **if `Q` occurs in no corpus record but `X`'s own, no substitution
could have produced it.** That is computable offline, in minutes, with no API key.

Measured over the 254 entries, using the committed `_quote_in_text` semantics:

| | EL | IL | total |
|---|---:|---:|---:|
| `valid_quote: false` — cannot be a substitution | 2 | 7 | **9** |
| quote unique to its own record — **substitution impossible** | 142 | 33 | **175** |
| quote also in a record in a different batch — **undecidable** | 26 | 44 | **70** |

The split is not arbitrary; it is bimodal and it lands where the mechanism predicts. Cleared
entries have a median quote length of 208 characters (EL) and 157 (IL) — long verbatim
strings, unique to one record. The undecidable ones have a median of **15**: generic
controlled-vocabulary fragments like `Computer science` that recur across a bibliographic
corpus. Because a substitution can only survive the evidence gate when its quote happens to
be corpus-ambiguous, **the undecidable set is exactly the at-risk population** — named and
enumerable, not a fog. No entry anywhere shows the positive signature (named record cannot
supply its own quote while another can); all 254 quotes are supplyable by their named record.

**The sharpest form of the answer.** The question that matters is not how many cache entries
are clean but how many *removed a record from the review*. Reconstructing the evidence gate
from the goldens yields **exactly 5 record-removing verdicts**, and they match the committed
filtered goldens exactly — EL `OUT = [A499]`, IL `OUT = [A452, A636, A642, A757]` — which
validates the whole method end to end.

| record | criterion | quote | verdict |
|---|---|---|---|
| `A499` | `EC-2` | 102 chars | **substitution impossible** |
| `A636` | `IC-1` | 152 chars | **substitution impossible** |
| `A642` | `IC-1` | 209 chars | **substitution impossible** |
| `A757` | `IC-1` | 199 chars | **substitution impossible** |
| `A452` | `IC-1` | 16 chars — `"Computer science"` | **undecidable** |

So: **four of the five exclusions in the published validation study are provably not products
of F-86. The undecidability is one record wide, and it has a name.**

**Answer.** Not "undecidable", and not "detectable" either. The artefacts support an
exculpatory-only test: it clears entries and can never convict, because nothing ties a
verdict to the call that produced it. 175 of 254 entries and 4 of the 5 exclusions are
refuted outright; the residue is structural, not effort-limited, and no additional work on
the committed artefacts will close it. The one thing that would — a per-response record of
which call answered for which id — does not exist and cannot be added retroactively.

*Also settled, because it would have made the question moot in a stronger way:* the goldens
were **live-captured**, not stubbed. The argument is artefact-internal rather than resting on
a commit message — a missing model, a missing key or a client-init failure each `return {}`,
giving an *empty* cache, and an invalid key routes to the terminal-failure branch that stamps
`error` and `used: false` on every item. 254 complete, error-free, `used: true` entries can
be produced by no other path. `tests/conftest.py` mocks only tkinter and
`metascreener.plugin_api`; neither regression test mocks the client.

---

## New register rows

**F-133** — `_verify_sha256_map` cannot see a digest whose member is absent, and
`_refresh_sha256_map` never removes one. Medium / XS. See *Part 3*.

That is the only row added. One further defect was found and deliberately **not** made a row:

*`_write_llm_stage_bundle` copies a bare `input_errors.csv` through while writing its merged
content to `data/input_errors.csv`, leaving the bundle with two conflicting records of
dropped citations.* Verified by direct execution. It is not a row because no writer in this
repository emits the bare path — `plugins/03_harmoniser/bundle.py`,
`plugins/_common/bundle.py` and both stage exporters all write `data/input_errors.csv`, and
the bare spelling appears only in *read* candidate lists, as tolerance for a foreign or
historical layout. The scenario therefore requires an externally-authored bundle, and filing
it as a defect of this writer would overstate it. Recorded here so the next person to touch
that skip set knows it was seen and judged.

---

## Where I disagree with the brief

1. **Q2's premise that batch composition is invisible is false**, and it was the load-bearing
   link. `_invocation.batch_size = 5` is committed in both golden envelopes. The conclusion
   partly survives, for a different reason — no artefact attributes a verdict to a call — but
   the undecidability is far narrower than "probably not": one record out of five exclusions.
   Full working in *Part 4*.

2. **F-87's duplicate-id guard is upstream in two places, not one.** The brief says "guarded
   only UPSTREAM, by `_load_bundle`'s dedup". `plugins/_common/parser.py` has deduped since
   F-55 as well; the register row says both. The conclusion is unaffected — both are upstream
   of the engine — but "belt and braces" was already two straps before this wave, and is
   three now.

3. **F-104's fix cell does not quite say what the brief says it says.** The brief treats
   `_verify_sha256_map`'s blindness as a discovery to be assessed; the register had already
   floated it inside F-104's own Suggested-fix cell as a "consider also". Neither is wrong,
   and the combination is the actual hazard — see *Step 0*.

4. **The register's F-86 row overstates the forward route** by stating the omission
   requirement only by contrast with the backward route, and understates the preconditions:
   the owning batch must complete *and* omit. Recorded in *Part 1* and written into the
   closed row.

5. **My own error, corrected.** The `fix(F-104)` commit message initially named the new row
   **F-131**. F-131 and F-132 already exist (added in wave 6b) — the register's maximum ID is
   132 while its row count is 129, exactly the trap its own counting section warns about. The
   correct id is **F-133**. The commit message was amended before any push; the commit is
   `bb9671b`.

Everything else in the brief was accurate, including the step-0 ledger, the 422/4 baseline,
both `OUT` measurements, and the claim that F-86 fires at `batch_size = 1`.

---

## Close-out

**Commits** — three, one per finding, suite green after each.

| Commit | Subject |
|---|---|
| `3f37f17` | `fix(F-86): scope LLM answer acceptance to the batch that was sent` |
| `d98d625` | `fix(F-87): refuse to cache non-answers, and guard duplicate ids in the engine` |
| `bb9671b` | `fix(F-104): keep the incoming cache when the export does not write one` |

**Suite** — 422 passed, 4 skipped → **476 passed, 4 skipped**. Delta **+54**, all new:

| File | Tests | Red before its fix |
|---|---:|---:|
| `tests/test_cross_batch_substitution.py` | 14 | 8 |
| `tests/test_negative_caching.py` | 28 | 20 |
| `tests/test_cache_member_preservation.py` | 12 | 6 |
| | **54** | **34** |

No existing test was modified, deleted or skipped.

**Goldens** — the nine SHA-256 hashes recorded at step 0 are byte-identical at close-out, and
`git diff main...fix/wave-7-cache-integrity -- tests/golden/` is empty. Nothing in this wave
came close to needing an equivalence proof: all three fixes are on paths the golden replay
does not take, because the replay is cache-complete and never enters
`run_m1_llm_for_criterion`.

**Audits** — all three exit `0`.

| Tool | Result |
|---|---|
| `tools/audit_imports.py plugins` | 37 files, all `clean` |
| `tools/audit_decorators.py plugins` | 47 files, all `clean` |
| `tools/check_encoding.py` | 153 paths scanned, no BOM or mojibake |

**Register** — F-86, F-87 and F-104 annotated closed in-row (`(done)` on effort, `Fixed in
<hash>` in the fix cell); F-133 added. Totals regenerated from the rows by the register's own
stated method, which was first validated by reproducing the committed pre-wave snapshot
exactly (129 rows / 45 closed, and the category line to the row).

| Severity | Total | Closed | Open | before |
|---|---:|---:|---:|---|
| **Critical** | 4 | 4 | **0** | 1 open |
| **High** | 36 | 18 | **18** | 20 open |
| **Medium** | 58 | 14 | **44** | 43 open |
| **Low** | 32 | 12 | **20** | 20 open |
| **Total** | **130** | **48** | **82** | 129 / 45 / 84 |

Not merged, not tagged, not pushed.
