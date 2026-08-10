# metaScreener — Wave 8: readiness and honesty

The wave that lets the application distinguish a run that worked from a run that did not.
**Both parts.** The wave was split after the step-0 reading, with the coordinator's
agreement; the seam and the reasoning are in *§ The split* below. **Part 1** — the engine and
the exported artefact — is §§ Part 0–2 and closed at `153a7ce`. **Part 2** — the interface —
is § Part 2 of the wave onward and closed at `e188a07`.

Branch `fix/wave-8-readiness` off `main` @ `ed61b6a` (tagged `post-wave-7`). Standing rules
as before: one logical change per commit, suite green after every commit, no golden may move
— a SHA-256 manifest of `tests/golden/` was recorded at step 0 and re-verified at close-out
alongside `git diff main...HEAD -- tests/golden/` — and **no push, no merge, no tag**.

Coordinates are `path::symbol` throughout. Line numbers are wrong in this area even when
fresh: `metascreener/plugin_manager.py::_sanitize` strips the `from __future__` line before
compiling, so runtime line numbers in `llm_client.py` and both `screen.py` files are off by
one from disk (wave 6, D3).

---

## Step 0 — the gate

| Check | Expected | Found |
|---|---|---|
| `git rev-parse HEAD` | wave-7 merge | `ed61b6a3c3f2b03ffca26528faedacd765391aa1` |
| Branch / tag | `main`, `post-wave-7` | both, exactly |
| `git status --porcelain` | clean | empty |
| `origin/main` sync | 0 / 0 | `0	0` |
| Suite baseline | 476 passed, 4 skipped | **476 passed, 4 skipped** |
| Register | 130 rows, F-56–F-58 absent | 130 rows, F-01..F-133, gap intact, no duplicates |

The coordinator's ledger was right on every point. HEAD had not moved, so no gap commits
needed classifying.

**Golden manifest recorded at step 0** and re-verified unchanged at close-out:

```
a01ccc73…  criteria_harmonized_v3.1.0.csv    9b1eb10d…  eh_filtered_v3.1.0.csv
a7009f0b…  el_cache_v3.1.0.json              604cb2f5…  el_filtered_v3.1.0.csv
af029f8d…  el_input_v3.1.0.csv               d0b559f8…  ih_filtered_v3.1.0.csv
f29cdbaa…  il_cache_v3.1.0.json              088cca9d…  il_filtered_v3.1.0.csv
c4c5d739…  il_input_v3.1.0.csv
```

---

## The split

The brief asked for a judgement on whether this is one session or two, before any code. It
is two, and the seam is the one the brief itself draws: Parts 1 + 2, then Part 3.

Four measured reasons, all established in step 0:

1. **The engine work cannot move a golden.** `tests/test_el_regression.py` pops
   `OPENAI_API_KEY` *and* runs with a complete cache, so `to_call` is empty and
   `plugins/_common/llm_client.py::run_m1_llm_for_criterion` is never entered at all. F-90,
   F-94 and F-134 are unreachable from the byte-identity tests. That makes part 1 cheap and
   safe to review.
2. **The substrate work is not cheap.** `run_m1_llm_for_criterion` cannot change its return
   type — fourteen tests depend on it being a plain mapping and one asserts `out == {}` — so
   the counts had to ride on a caller-supplied mutable kwarg. The engine tuple grows across
   **fourteen unpack sites**, two of them in `tools/capture_el_il_goldens.py`, where a
   breakage would silently remove the ability to re-capture a golden.
3. **Part 3 has no direct test coverage and cannot get any as written.** `ttk.Frame` is a
   `MagicMock` under `tests/conftest.py`, so `ELView` is not instantiable and no test asserts
   on a status label anywhere in the suite. Every UI decision must first be extracted into a
   pure function to be testable at all — the wave-4a pattern, but a genuine refactor of four
   UI files plus `metascreener/main.py`, not an edit.
4. **§B1.4's eleven states are 0–10, and six of them are *discovery* states** (0, 4, 5, 6, 7,
   9) requiring an endpoint field and a `/v1/models` call — explicitly out of scope until
   waves 9–12. Part 3 can therefore build only the post-run arm plus the two pre-run states
   that need no endpoint. That is the right thing to build, and it needs arguing carefully
   rather than landing after eight other commits.

Each half makes a complete claim on its own. **Part 1: the engine stops misreading the
model, stops treating every transport failure as anonymous, stops overwriting its own
answers, and the exported bundle stops saying a failed run succeeded.** Part 2: the
interface stops saying it too. Neither half is a dead substrate — part 1's report reaches
`manifest.pipeline.history[]`, which is the artefact a reviewer reads.

---

## Part 0 — eight new rows

Both commissioned rows were swept against **all 130** existing rows before being added, not
only against the ones the brief named. Neither is covered by an existing row.

### F-134 — the terminal-failure arm overwrites received verdicts (Medium)

Swept against F-26 (same overwrite, closed, different trigger), F-86 (closed, foreign
`a_id`s rather than the batch's own), F-87 (closed, persistence rather than the write),
F-102, F-122 and F-12. New.

**Severity: Medium, agreeing with the brief's suggestion.** The row is bounded three ways
where F-26 was not — batch-local rather than run-wide, fail-safe in direction (a received
`meet` degrades to flagged, never to excluded), and no longer persistent since `d98d625`.
F-26 was raised to High because its trigger was a deliberate press of a shipped button;
this one needs an exception inside a narrow window.

The `progress()` route is recorded in the evidence cell explicitly, as the brief asked,
because it is the trap for anyone modifying progress reporting — which is what this wave
does.

### F-135 — no call fingerprint on a verdict (Medium, scheduled for wave 9)

Swept against F-88, F-62, F-63, F-64, F-86, F-96, F-98 and F-103. New, and **explicitly not
F-88**: F-88 asks *which model* produced a decision, F-135 asks *which call*. Different
fields, different questions, and a bundle can satisfy either without the other — stamping
the model into `pipeline.history[]` says nothing about which of forty-seven requests
returned a given verdict. Cross-referenced in both directions. Marked `(scheduled)` for
wave 9 alongside F-88 tier 1, because both write into the same records and doing them
separately would touch every evidence writer twice.

### Six further rows, found while working the wave and all verified by execution

| ID | Sev | Finding |
|---|---|---|
| **F-136** | Low | The `field` whitelist falls back to `abstract` silently, and the fallback changes *which text the quote is validated against*, so a real verdict degrades to UNCERTAIN. F-90's twin. Counted this wave, deliberately not fixed. |
| **F-137** | Medium | `plugins/02_references_of_x/ui.py::ReferencesOfXView.on_resolve_metadata` and `::on_fetch_refs` carry F-112's defect verbatim — and worse, both fire while a `wait_window`-grabbed modal holds the Tk grab. |
| **F-138** | Medium | In the same two functions, `_ui_tick` is defined inside `for i, bi in enumerate(...)` and scheduled with `after(0, _ui_tick)` with no default-argument binding, so the progress modal reports an item the worker has already left behind. |
| **F-139** | High | `metascreener/main.py::_save_env_key` sets `lines = []` when the read raises and then writes unconditionally. **Reproduced:** a `.env` holding `OPENAI_BASE_URL`, `SCREENA_EL_MODEL` and `OPENAI_API_KEY` became `OPENAI_API_KEY=sk-new` alone. |
| **F-140** | Low | `ApiKeyDialog._on_save` validates `sanitize(sanitize(entry))` but stores `sanitize(entry)`, and `sanitize` is not idempotent. **Measured:** entry `'" x "'` validates as `'x'` and is stored as `' x '`. |
| **F-141** | High | **Wave 7's three closures never reached `CHANGELOG.md`**, and one of them is the register's last Critical. `[Unreleased]` mentions F-86, F-87 and F-104 nowhere, while carrying a hand-written "If you produced results with an earlier version, read this first" list whose entire purpose is this class of disclosure. |

F-139 is filed **High, not Critical**, on F-104's reasoning: the loss is of retypeable
configuration rather than scientific records. It is nonetheless the most consequential of
the six for waves 9–12, every one of which makes `.env` carry more while nothing guards it.

**F-141 was found while checking this wave's own close-out conventions, and it is the one
that should be read first.** F-86 could remove a record from a systematic review on evidence
belonging to a different record, and reproduce that removal offline for ever. A user who ran
metaScreener before `3f37f17` cannot learn this from any user-facing document: the register
and the wave briefs live under `docs/internal/`, and the changelog is the only place the
project speaks to a past user about results they have already produced. It is the exact
inverse of the bookkeeping failure the register records in § "How this register is counted",
item 3 — waves 0–2 closed in the changelog and never wrote back to the rows, and wave 6b
spent a whole pass repairing that; wave 7 wrote the rows and never wrote the changelog. The
two halves have now failed in both directions, which is why this is filed as a process row
and not as three missing bullets. Opened rather than fixed, deliberately: the wording of a
disclosure about fabricated exclusions in already-published reviews is the coordinator's
call, and this wave's brief does not scope `CHANGELOG.md`.

---

## Part 1 — the engine

### F-90 — the decision whitelist — `edd02c3`

**Before.** `decision` was compared against the inline literal set with only `.strip()`
applied, while `field` on the *next* statement got `.strip().lower()`. A model answering
`"Meet"` had every decision in the run rewritten to `"uncertain"`, and the record kept
`used: True`, a genuine quote, `valid_quote: True` and a high confidence.

**After.** `plugins/_common/llm_client.py::_normalize_decision` folds case and separator and
returns `None` outside the vocabulary, so the caller counts the rejection rather than
silently substituting the fallback. Returning the fallback in place is what made the
condition invisible.

| | |
|---|---|
| Tests | `tests/test_decision_whitelist.py`, 33 |
| Red before | **16** — 11 for the case and separator defect, 5 for the missing visibility |
| Green after | 33 |
| Regression net | the 17 that passed before are `TestTheWideningIsExact`, and they must keep passing |

**Where this departs from the register, and why.** The fix cell says "one `.lower()`". The
row's own *finding* cell names `"not meet"` among the strings a model produces, and case
folding alone does not reach it. A model that varies the case varies the separator for the
same reason — there is no `response_format` on the local path to hold it to either — so the
separator is normalised too. The widening cannot invent a verdict: only a string reducing
*exactly* to a vocabulary member is accepted, and `meets`, `does not meet`, `notmeet` and
`yes` are all still outside it. `TestTheWideningIsExact` exists to hold that line, and its
ten cases were green before the fix and are green after.

**Why rejections are logged once per criterion, not once per record.** Eight hundred
identical lines in a sub-tab that is not the focused one is precisely the reporting failure
this wave exists to fix, committed a second time. The summary names the commonest raw
values, bounded, because `"Meet"` and `"maybe"` call for opposite responses from the user
and the tally alone does not distinguish them.

**Why a rejected decision is not cached.** This extends F-87's rule, and the reason is
specific to this row rather than inherited: a cache hit never reaches the parser, so a
cached rejection would emit the new log line exactly once and never again. By the second
run the condition would be invisible again — the defect reintroduced through the cache.

### F-94 — error classification — `c267593`

**Before.** Both salvage mechanisms were gated on substring sniffs over `str(e).lower()`,
and `is_big` required `context` **and** `length` to co-occur.

**After.** `::_classify_llm_error` returns `(class, how)` over three resorts in order, and
`how` names which one answered so the log line can say:

| Resort | Signal | Why in this order |
|---|---|---|
| `type` | `openai.RateLimitError`, `BadRequestError`, `AuthenticationError`, `PermissionDeniedError`, `NotFoundError`, `APIConnectionError` (which `APITimeoutError` subclasses) | the only signal that does not depend on prose |
| `status` | `e.status_code` | an OpenAI-compatible server behind a proxy surfaces a generic `APIStatusError`; the HTTP code still means what it means |
| `message` | `_OVERSIZE_RE`, `_RATE_RE` | **last resort, and labelled as such** |

| | |
|---|---|
| Tests | `tests/test_error_classification.py`, 46 |
| Red before | **43** |
| Green after | 46 |
| Regression net | `TestUnknownErrorsStillReachTheTerminalArm` — `test_negative_caching` raises a bare `RuntimeError` and `test_cross_batch_substitution` a bare `AssertionError`, and both rely on being written off rather than propagated |

The SDK types are imported **lazily**, as `::_openai_client_for` already imports `OpenAI`.
Hoisting them to module scope would make every stage module fail to import on a machine
without the SDK — a strictly worse failure than losing type-based classification on a
machine that cannot make an API call in the first place.

A 400 is `oversize` only when its body says so. Treating every 400 as oversize would halve
the batch to one and step the truncation to its floor against a request the server will
never accept.

There is deliberately **no message-level transport sniff**. A bare string containing
"timeout" is not evidence of a transport failure — `"Internal server error (500) … upstream
timeout"` is a server error — and every real transport condition arrives as an SDK type or
an HTTP status.

#### Two refinements to the row, both measured

**The false positives are live, but rarer than the row states.** `is_rate` is a
*conjunction*: `("rate" in msg and "limit" in msg)`. So `"rate"` matching inside `generate`,
`moderate` or `separate` is not sufficient on its own — the word `limit` must also appear
somewhere in the message. Measured against the old predicate:

```
'failed to generate output'                  -> is_rate False   (the row's claim, alone)
'moderate token limit exceeded'              -> is_rate True    (the live case)
'failed to generate: request limit reached'  -> is_rate True
'the model will generate up to the limit'    -> is_rate True
```

The new pattern is boundary-anchored (`\brate[\s_-]*limit`), so `"generate limit"` no longer
matches. All four are now correctly classified.

**`transport` stays terminal — a deliberate departure from a literal reading of "terminal on
first sight".** The SDK sets `DEFAULT_MAX_RETRIES = 2`, so a transport error reaching the
application layer has *already* been attempted three times. An application-level ladder would
make it six. The ladder is F-25's, and F-25 is explicit that the application's ladder and the
SDK's must be chosen in awareness of each other. What this wave changes is that the failure
is **named** rather than anonymous — `error_class` is stamped on the record, not only logged,
because a log line lives in a sub-tab that is not the focused one while the record reaches
whoever asks why the run produced no answers.

**Recorded, not fixed, as the brief instructed:** halving is the wrong remedy for a 429,
because it increases the request count, and no `Retry-After` is read at the application
layer. The remedy mapping for `rate_limit` is unchanged; only its detection is.

### F-134 — the terminal-failure arm — `1d53122`

**Before.** The omission back-fill was guarded `if (a_id, cid) not in out`; the terminal
back-fill twelve lines below was not.

**After**, in two halves, either of which alone would leave the other route open:

1. **The guard.** `(a_id, cid) in out → continue`, matching the back-fill above it. Records
   with no verdict still get an entry, so the guard cannot turn into a leak — the row loop's
   `llm_results.get(...)` must not come back empty for a record the batch carried.
2. **Reporting is isolated from the work.** `::_guarded` wraps the two caller-supplied
   callbacks once, at the top of the function. Rebinding the two names rather than editing a
   dozen call sites means a reporting call added later is covered without anyone having to
   remember.

| | |
|---|---|
| Tests | `tests/test_terminal_failure_guard.py`, 9 |
| Red before | **7** |
| Green after | 9 |

The guard is exercised through `_quote_in_text` raising mid-parse-loop, **not** through
`progress()`, so the two halves are pinned independently.

**Why swallowing is the right disposal.** Both alternatives are worse. Propagating kills the
run and discards every batch already paid for; reaching the retry handler is the defect
itself. A reporting channel that cannot report is a lost log line; it must not also be a lost
verdict. `_Cancelled` is re-raised rather than swallowed, because cancellation is control
flow — a swallow there would make the cancel button stop working the moment someone wired
one through a callback.

**The second-order route in the row still holds, and is now doubly guarded.** Had the failure
message happened to contain a rate-limit token, the batch would split and retry instead, and
the already-written verdicts would survive *only* because of F-86's `(a_id, cid) in out`
guard in the parse loop — a correctness property resting on an unrelated fix. That is now two
guards rather than one borrowed.

---

## Part 2 — the run-level failure report — `d82470e`

### The design, and the one paragraph the brief asked for

The constraint was that the count be derivable rather than hand-maintained, this project
having been bitten four times by an enumeration that drifted from its source. **The rule
adopted is: a fact about a record is derived from the record; a fact about a call is counted
at the call.** The line falls there because it is forced rather than chosen — a batch that is
refused as oversize, halved, and then answered ends with every record carrying a good
verdict, so the failure that happened is *invisible* in the evidence map and no derivation
can see it. Everything that can be derived, is: `summarize_llm_evidence` walks the same
evidence map the row loop makes its decisions from and recomputes six counts on every call,
so the report cannot disagree with the output it describes; nothing increments them, and
`records` partitions exactly into the other four, which a test asserts on every shape. Only
three numbers are stored — `calls_made`, `calls_failed`, `batches_failed` — and they live in
a caller-supplied dict rather than in the return value, because `run_m1_llm_for_criterion`'s
return type is pinned as a plain mapping by fourteen existing tests, one of which asserts
`out == {}`.

### What the report says

| Key | Kind | Meaning |
|---|---|---|
| `records` | derived | evidence entries the decisions were made from |
| `answered` | derived | **a decision this pipeline could read** |
| `no_answer` | derived | sent, and the model said nothing about it |
| `failed` | derived | the call raised; `error` present |
| `decisions_rejected` | derived | answered outside the vocabulary (F-90) |
| `fields_rejected` | derived | `field` outside the vocabulary (F-136) — counted, not acted on |
| `calls_made` | counted | `_call_once` invocations. **Not** HTTP requests: the SDK retries twice beneath (F-25) |
| `calls_failed` | counted | invocations that raised, salvaged or not |
| `batches_failed` | counted | batches that ended in the terminal arm |

`answered` is the load-bearing one, and it is the whole wave in a single number:

```
a model answering "uncertain" everywhere   ->  answered == records
a down server                              ->  answered == 0
a model name with a typo                   ->  answered == 0
a model that was never pulled              ->  answered == 0
an empty model field                       ->  answered == 0
```

`tests/test_run_report.py::TestTheDistinctionTheWaveExistsFor` proves the first two are
identical in every *other* field — same `counts`, same survivor count, same outcomes,
`cancelled` False for both — and that the report separates them.

### The carrier

The engines return an **eighth element, a dict**. A dict rather than more tuple positions
because waves 9 and 11 add provenance (F-88, F-135) to the same history entry, and a key is
cheaper and safer to add than a position. Appended *after* `cancelled` so `cancelled` keeps
its index; the suite's one star-unpack (`*_, cancelled`) is now spelled out, because a star
form silently rebinds when a tuple grows.

Fourteen unpack sites moved in lockstep. Two of them —
`tools/capture_el_il_goldens.py`, one per stage — appear in **no test**, and breaking them
removes the ability to re-capture a golden with nothing saying so until someone needs to.
`TestEveryUnpackSiteMovesWithTheTuple` is a static AST check over `plugins/`, `tools/` and
`tests/` that names the capture tool explicitly. It was needed: the first mechanical pass
missed exactly those two sites, and no test noticed.

### The manifest

`plugins/_common/bundle.py::_write_llm_stage_bundle` gains two keyword parameters, both
defaulted so the twelve existing call sites are unaffected:

- **`llm_report`** rides on the history entry as `llm`, a **sibling of `counts`, not a member
  of it**. `counts` is the outcome histogram, a call failure is not an outcome, and it is
  asserted by exact dict equality in `tests/test_archived_bundle_manifest.py` — which is the
  right constraint for a histogram to have. Omitted entirely when the caller has none, rather
  than written as zeroes: a stage that did not measure must not claim it measured nothing.
- **`cancelled`** becomes a real parameter, and the stage marker gains `"cancelled"`, matching
  `::_export_next_bundle_zip`, which has taken both since F-02. The UIs refuse to export a
  cancelled run, so no reachable call passes `True` today; the hard-coded `False` was a false
  record waiting for a path that writes one.

**No model, provider or endpoint field.** That is wave 9 and it would conflict.

| | |
|---|---|
| Tests | `tests/test_run_report.py`, 40 |
| Red before | **29** of the 34 present when the count was taken |
| Green after | 40 |

The six tests added after the red count are the static arity checks and two manifest
assertions; the arity check was also red, since it asserts 8 against the then-current 7.

---

## Where I disagree with the brief, or with the register

**1. The brief mis-assigns F-112.** It attributes `_refresh_key_label` to F-112 and treats
the plugin-01 worker-thread `messagebox` as something "F-111 mentions" that may need a new
row. The register says otherwise: **F-111 owns both** the eleven states and
`_refresh_key_label`; **F-112 is already the row** for the worker-thread `messagebox`, at
Medium/XS, with the fix cell "Marshal the error dialog through `self.after` like its
neighbours". No new row was needed, and F-112 is already in the wave's scope list. It is
part 2 work.

**2. F-111's `path::symbol` is wrong.** Corrected in place. `MetaScreenerApp._refresh_key_label`
does not exist — `grep -rn "_refresh_key_label" metascreener/` returns nothing, and
`MetaScreenerApp` owns no key widget at all. The symbol is
`plugins/06_el/ui.py::ELView._refresh_key_label` plus three byte-identical twins.
`06_llm_integration.md` cites the correct paths; the coordinate was corrupted when the
candidate was promoted into the register.

**3. F-112's Evidence cell is wrong.** Corrected in place.
`plugins/01_reference_extractor/plugin.py` contains **zero** `messagebox` calls and zero
`self.after` calls — 61 lines holding `TAB_TITLE`, `make_plugin` and
`ReferenceExtractorEmbedded::build_tab`, plus an `import tkinter.messagebox as messagebox`
that nothing uses. That dead import is the likeliest source of the mis-citation. The defect
is at `plugins/01_reference_extractor/original/prisma_citations_ai_v3_1.py::PrismaAIV3View.on_extract`,
nested `work()`: nine marshalled `self.after(0, …)` on the success path against one bare
`messagebox.showerror` in the `except`.

**4. A refutation of F-111 was raised during recon and did not survive checking.** It is
recorded here because a wave brief must not carry a false refutation, and because the
checking produced F-140. The claim was that the `✗` branch is reachable because
`sanitize_api_key` leaves `'" "'` as a bare space, which `_has_openai_key` then strips to
nothing. `sanitize_api_key` does do that — but `validate_api_key` **re-sanitises
internally**, so the residual space strips to `""` and the save is refused. Verified by
execution against the shipped modules:

```
'" "'   -> sanitize ' '    accepted False       '"   "' -> sanitize '   '  accepted False
```

Since `sanitize` of any all-whitespace string is empty, no accepted value can be
whitespace-only, so `_has_openai_key()` cannot be False once the modal has been passed.
**F-111's "can only ever render `✓`" claim stands.** What the check *did* find is that
`_on_save` validates a different string from the one it stores, which is now **F-140**.

**5. F-90's fix cell under-serves F-90's finding cell.** The finding names `"not meet"`; the
fix says "one `.lower()`", which does not reach it. Implemented as the finding requires and
recorded in the row. See Part 1 above.

**6. F-93 cannot be closed by part 1, and is annotated as partially fixed rather than
closed.** The engine and artefact half is done; the GUI half is part 2. This is the first row
in the register to carry a partial closure, and the Effort marker stays empty deliberately —
`(done)` over a half-fixed row is the failure mode that section exists to prevent, and the
same reasoning kept F-133 out of F-104's closure in wave 7.

**7. F-118 will not be closable by part 2 either, and this is flagged now.** The brief scopes
F-118 to its first third (the `btn_run` gate). The register's F-118 has three: the gate, the
harmoniser's unread "LLM refine" checkbox, and unvalidated numerics where a negative
`trunc_chars` truncates the *tail* of every field. Part 2 can do the gate and the numerics —
both are in `_run_clicked`, which it is already rewriting — but "wire or delete" the checkbox
is a product decision in a different plugin. F-118 should stay open with an annotation.

---

## Close-out

### Goldens — verified both ways

Per-file SHA-256 of all nine files under `tests/golden/` is **identical to the step-0
manifest**, and `git diff main...HEAD -- tests/golden/` is **empty**. No equivalence proof is
needed because nothing here can reach a golden: `tests/test_el_regression.py` pops
`OPENAI_API_KEY` *and* supplies a complete cache, so `to_call` is empty and
`run_m1_llm_for_criterion` is never entered. The byte-identity tests do exercise the new
tuple arity, and pass unchanged.

Neither new evidence key reaches an exported artefact: `{el,il}_evidence_json` is built from
a fixed list of nine keys, and `error`/`decision_rejected` both make an entry uncacheable, so
neither reaches a cache file either.

### Suite

| | |
|---|---|
| Before (`ed61b6a`) | **476 passed, 4 skipped** |
| After (`d82470e`) | **604 passed, 4 skipped** |
| Delta | **+128 passed, 0 skipped** |

The delta is entirely new tests, in four new files: `test_decision_whitelist.py` 33,
`test_error_classification.py` 46, `test_terminal_failure_guard.py` 9, `test_run_report.py`
40 — 128 exactly. No existing test was deleted, and no existing test changed its assertions;
the fourteen edits to existing test files are unpack-arity changes only.

### Audit tools

| Command | Result | Exit |
|---|---|---|
| `python tools/audit_imports.py plugins` | all files `clean` | **0** |
| `python tools/audit_decorators.py plugins` | all files `clean` | **0** |
| `python tools/check_encoding.py` | 158 paths scanned, no BOM or mojibake | **0** |

The encoding scan covers 158 paths, up from 154 at step 0: the four new test files.

### Register

Regenerated **from the rows**, not edited by hand, using the derivation the register itself
prescribes (severity after the arrow where a cell carries a revision; status from the Effort
marker). Nothing checks this, which is **F-131** and is still not fixed.

| Severity | Total | Closed | **Open** | unscheduled | scheduled | backlog | parked |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Critical** | 4 | 4 | **0** | 0 | 0 | 0 | 0 |
| **High** | 38 | 20 | **18** | 18 | 0 | 0 | 0 |
| **Medium** | 62 | 15 | **47** | 43 | 2 | 2 | 0 |
| **Low** | 34 | 12 | **22** | 17 | 0 | 3 | 2 |
| **Total** | **138** | **51** | **87** | 78 | 2 | 5 | 2 |

Movement from wave 7: **+8 rows** (F-134..F-141), **+3 closed** (F-90, F-94, F-134), one
partial closure (F-93), one new `(scheduled)` row (F-135, wave 9). There are still no open
Criticals.

### Commits

| SHA | Subject |
|---|---|
| `d8bd93c` | `docs: open F-134..F-140, and correct F-111's and F-112's coordinates` |
| `edd02c3` | `fix(F-90): fold the decision vocabulary, and give a rejection a signature` |
| `c267593` | `fix(F-94): classify call failures by type and status, not by prose` |
| `1d53122` | `fix(F-134): a failure must not destroy the answers already received` |
| `d82470e` | `fix(F-93): give the engine and the bundle a run-level failure report` |

Not merged, not tagged, not pushed.

### What part 2 inherited

*Kept as written at part 1's close, so the handover can be checked against what was
actually done. All five items were delivered. Two of them were wrong in ways part 2 had to
correct, and those corrections are in § Part 2 below — the note about
`plugins/06_el/standalone.py` was right, and the note about F-119's reachable trigger was
not.*

*Kept as written at part 1's close, so the handover can be checked against what was
actually done. All five items were delivered; two of them turned out to be wrong in ways
recorded below.*
The substrate is in place and has one consumer already (the manifest). Part 2 needs:

- **F-93's GUI half** — refuse an empty model before starting (`(self.var_model.get() or
  DEFAULT_MODEL).strip()`, whose reachable trigger is a whitespace-only field; note that
  `plugins/06_el/standalone.py` has the *correct* expression, so the defect is the tab UIs'
  alone), surface the count, extend `_export_confirm_reason`. The gate condition it should
  use is derivable from what part 1 built.
- **F-111** — a pure, headless state model with two arms: readiness before a run (decidable
  from configuration) and outcome after one (decidable from `counts` + the run report).
  Six of §B1.4's eleven states need an endpoint and are wave 10's; the model must be shaped
  so they can be added as inputs rather than as a rewrite.
- **F-112 and F-137** — the same one-line fix at three sites, with the `lambda m=str(e):`
  binding, which is required rather than stylistic (PEP 3110 deletes `e` at the end of the
  `except` block).
- **F-118** — the `btn_run` gate and the numeric validation; not the harmoniser checkbox.
- **F-119** — neutralise the provider-locked strings and log `model={model!r}`.

---
---

# Part 2 — the interface

Branch continues on `fix/wave-8-readiness` from `153a7ce`. Gate: HEAD `153a7ce`, clean, 6
ahead of `main` and 0 behind, `main` 0/0 with origin, branch never pushed (so there is no
upstream to compare it against, which is correct). Goldens identical to part 1's manifest.
Suite **604 passed, 4 skipped**.

---

## Part 0 — F-142, and why it is not F-88

The brief asked first whether F-88's provenance scope already covers a cache entry poisoned
before `3f37f17`. **It does not, and the distinction is the row's whole point.** F-88 asks
*which model* produced a decision and writes into `manifest.pipeline.history[]`. This asks
*which code version* produced a **cache entry**. Even with both of F-88's tiers implemented,
a pre-fix and a post-fix entry carrying the same model, temperature and prompt version are
indistinguishable, because neither tier records the engine. F-88 is cross-referenced, not
amended.

Everything was verified rather than assumed:

| Claim | Check | Result |
|---|---|---|
| the key is unchanged across the fix | `git show 3f37f17 -- plugins/_common/llm_client.py` | **zero** occurrences of `_cache_key` |
| the cache records no code version | `::_dump_cache_to_jsonl` | writes `{"key", "val"}` per line, nothing else |
| the value records no provenance | 170 values in `tests/golden/el_cache_v3.1.0.json` | exactly seven keys: `decision`, `confidence`, `field`, `quote`, `span`, `valid_quote`, `used` |
| the `_invocation` envelope might carry it | the golden JSON | `{batch_size, model, trunc_chars}` — and it exists **only in the golden *capture* format, not in the shipped `.jsonl`**, and records no code version either. F-96's "a field inside a test fixture", a second time |

Swept against F-33, F-86, F-87, F-88, F-89, F-96, F-99, F-101, F-102, F-103, F-128, F-133 and
F-135. New. **Filed High with the case for Critical stated in the row rather than suppressed**
— the consequence is a fabricated exclusion in a systematic review, which is what made F-86
Critical, and the path is live at HEAD. Held at High because the code is correct, the affected
population is fixed and shrinking rather than growing, and a zero-cost remedy exists once
known: it is *undiscoverable*, not unavailable.

One sequencing note that changes wave 9's order, and it is the most useful thing in the row:
**F-89's fix is an incidental remedy.** Hashing the endpoint changes every key, stranding every
pre-fix entry including the poisoned ones. If F-89 lands first, F-142 reduces to the audit
question alone; the other order wastes the work.

---

## The method — extract, then fix

Part 1 established that `ELView` is not instantiable under `tests/conftest.py` and that no
test in the suite asserts on a status label. So part 2 ran in two movements, in separate
commits, and the discipline paid for itself.

### Movement one — `ed05fb3`, behaviour-preserving

`plugins/_common/stage_state.py` took the Views' decisions as transcribed expressions, and
`tests/test_stage_state.py` locked in **today's behaviour, defects included**. Five assertions
encoded defects deliberately, each carrying a `CHARACTERISATION` marker naming the finding it
was waiting for:

| Assertion, as written in `ed05fb3` | Finding | Flipped in |
|---|---|---|
| a wholly failed run `== f"{stage} done."` | F-93/F-111 | `91ed3f8` |
| failed and all-uncertain `broken == unsure` | F-111 | `91ed3f8` |
| a wholly failed run's confirm `is None` | F-93 | `a0e95b0` |
| `st.run is True` with no key | F-118 | `866c988` |
| the two `btn_run` predicates disagree | F-118 | `866c988` |

**Exactly those five changed, and no others.** The remaining assertions are identical in
`ed05fb3` and at close, so the diff of each fix commit shows precisely which user-visible
behaviour moved. Each flipped test now carries a docstring naming the commit that set it and
quoting what it used to assert, so the history survives in the file rather than only in git.

The scaffold deserves a note. `run_button_enabled_after_load` was written **solely so the
F-118 contradiction could be stated as a passing test** — two functions deciding one button
from disjoint inputs. `866c988` deletes it, and the replacement assertion is
`not hasattr(ss, "run_button_enabled_after_load")`. Asserting the *absence* of the second
predicate is a stronger guarantee than asserting the first one's behaviour.

### What the extraction covers, and what F-14 still inherits

Recorded because **F-14's migration is gated on headless View testing**, and this is the
second instalment — wave 4a's mocked-Tk row-preparation tests were the first.

**Covered.** The two Views' *decisions*, now one implementation each rather than two: status
text, button enablement, export gating, readiness, numeric validation. These were twinned
between `06_el/ui.py` and `07_il/ui.py`; they are not any more, and they are tested.

**Not covered, and an F-14 wave inherits all of it.** The rendering path — `DataTable` is
still three copies (`_common/widgets.py` plus one in each View), which is F-49. Widget
construction and layout. Event wiring. The row-detail modal. The two standalone shells, which
diverge materially and were deliberately left alone (see *Scope decisions*). And the thing
that would make the rest testable: **no View is instantiable under `tests/conftest.py`, and
nothing here changes that.** What this wave demonstrates is that the decisions can be lifted
out without touching the widgets — not that the widgets can be tested.

---

## The state model — F-111, `91ed3f8`

### The design, and the argument for it

Two arms, because the inputs arrive at two different times and answer two different questions.
Before a run the facts are configuration — bundle, key, model — and the question is *may I
start, and what do I fix first*. After a run the facts are the outcome counts and part 1's run
report, and the question is *did that work, and may I export it*. A single flat enumeration
over eleven states would have to mix the two, and **§B1.4's own table does mix them**: state
10 ("model blank") is a pre-run check, states 2–7 are probe results, and the post-run states
are absent from it entirely, because that section was written about model *discovery* rather
than about run outcomes. Splitting the arms is what lets wave 10 add its endpoint states to
the first without touching the second, and what lets the second consume a report the first
knows nothing about.

### What was buildable, and what was not

§B1.4's eleven states are numbered **0–10**, and **six of them (0, 4, 5, 6, 7, 9) are
discovery states** requiring an endpoint and a `/v1/models` call — out of scope until waves 9
and 10. What is decidable today is the pre-run arm over (bundle, key, model), plus a post-run
arm the document does not enumerate at all.

| Arm | States | Decidable today? |
|---|---|---|
| pre-run | `ready`, `no_bundle`, `no_key`, `no_model` (§B1.4 state 10) | yes |
| pre-run | endpoint unreachable, model not pulled, keyless server (§B1.4 1–7, 9) | **no — wave 10** |
| post-run | `cancelled`, `not_screened` | already existed |
| post-run | `no_answers`, `nothing_separated`, `partial_failure` | **yes, and new** |

### Extensibility, which was a constraint rather than a hope

Both functions are **keyword-only**, so a new input disturbs no existing call site. The code
sets are published constants. `tests/test_llm_readiness.py::TestTheModelIsExtensible` asserts
all of it, plus the two properties wave 9 needs: an unknown key in the report is ignored, and
a missing one defaults. Wave 10's three states are new members and new branches reached by new
arguments; none of them changes a state that already exists.

### It reads the report; it does not re-derive it

The counting substrate exists from part 1, and a second derivation would be F-69's shape —
two representations of one fact — which this project has shipped four times. The test that
proves the direction of authority does it by **disagreeing the two inputs**: `counts` saying
"a normal screening pass" and a report saying "nothing answered" classify as `no_answers`.

### One gate, two diagnoses — and a disagreement settled

Part 1's brief recorded a disagreement to resolve here. The register's F-93 fix cell says to
extend the acknowledgement gate to cover "an all-uncertain run"; the wave's thesis is that a
model answering `uncertain` and a model not answering are *different*. Both are right, and the
resolution is to separate the gate from the diagnosis:

- **The gate is one condition** — this stage separated nothing (`OUT == 0 and PASS_CLEAN == 0`).
- **The diagnosis is two**, drawn from the report: `no_answers` ("the model was never heard
  from — this is what an unreachable server, a misspelled model name, a model that was never
  pulled and a rejected key all look like") and `nothing_separated` ("the model *was* heard
  from and nothing cleared the evidence gate — this may well be genuine").

`partial_failure` is reported and **not** gated. A run with a documented hole is a real result,
and gating it would train the user to click through the dialog that matters.

### The rendering constraint, pinned rather than eyeballed

The indicator is a `ttk.Label` in a grid cell that held `"OPENAI_API_KEY ✓"` — 16 characters.
Every new label is ≤16 and a test asserts it, because that is a genuine rendering question
rather than a matter of taste. A trace on the model `StringVar` keeps the label current while
the user types; without it the indicator would go stale the moment someone typed a model name,
which would be a new dishonesty in the widget this finding exists to make honest.

**One deliberate string change to flag:** in the ready state the label now reads `Ready to
run` rather than `OPENAI_API_KEY ✓`. After this wave the widget's job is readiness, and
labelling the ready state after an environment variable is what made it a constant in the
first place. The `✗` string is kept verbatim for the case it actually described.

---

## F-93's remaining half — `a0e95b0`

**Refuse rather than substitute.** `_run_clicked` asks the same readiness the indicator and
the Run button ask, and refuses an empty or whitespace-only model. This is a deliberate
reading of "refuse an empty model before starting": a blanked field is a mistake, and quietly
screening a whole corpus against `DEFAULT_MODEL` costs real money and produces results
attributable to the wrong model. The fallback survives where it belongs — as the `StringVar`'s
initial value.

**Extend, don't reinvent.** `_export_confirm_reason` gains one keyword, `outcome_reason`. It is
a parameter rather than an import because the dependency runs the other way — `stage_state`
imports `bundle`. EH and IH are not LLM stages, pass nothing, and keep exactly the behaviour
they had across their twelve call sites. F-34's question is checked **first** and wins when
both apply: a stage with no criteria never called anything, so its report is empty and would
otherwise read as "no answers", and "you have no criteria for this stage" is the diagnosis
that tells the user what to do.

**A third export door, found while wiring the other two.** IL's `_export_final_clicked` had
**no acknowledgement gate at all** — a pre-existing asymmetry with its two siblings, and in
the worst possible place, since `ScreenA_Report.xlsx` is the terminal deliverable a reviewer
actually reads. Gating two doors and leaving the third open is not a gate, so it is gated
here.

### The partial-closure convention, in practice

F-93 was the register's first partially-closed row, and it is now closed, so the convention
can be reported rather than proposed. It cost nothing and caught something:

- the Effort marker stays **empty** until every half is done, so the totals count the row as
  open;
- the fix cell **opens** with which half was fixed and which was not, and names the commit for
  each;
- the closing annotation names **both** commits.

It caught something because F-118 needed the same treatment three commits later, and the shape
was already there. F-118 now carries a partial closure and will until wave 10.

---

## F-118 — `866c988`, two halves of three

**The gate.** `control_states` takes a `Readiness` rather than a bundle flag, which makes a
second predicate *impossible to reintroduce* — there is nowhere left to put a different one —
and `_load_bundle_inputs` stops deciding for itself. That incidentally fixes something no
finding records: IL's `btn_export_final` was absent from the load path's reset block, so it
stayed enabled after loading a new bundle while its three siblings were forced back to
disabled.

**The numerics, and a correction to the row.** The register says a negative `trunc_chars`
"truncates the **tail** of every field". Measured on the real builder, it is worse:

```
trunc=     1500  title_len= 31  abstract_len= 317  keywords_len= 13  TAIL present
trunc=        0  title_len= 31  abstract_len= 317  keywords_len= 13  TAIL present
trunc=     -100  title_len=  0  abstract_len= 217  keywords_len=  0  TAIL gone
trunc= -1000000  title_len=  0  abstract_len=   0  keywords_len=  0
```

`-100` removes the last 100 characters of the abstract **and empties the title and keywords
outright**, because any field shorter than 100 characters slices to `""`. Titles and keywords
are routinely under 100 characters, so a modest negative value blanks two of the three fields
for essentially every record. Three consequences follow, none of them in the row: `valid_quote`
collapses for want of any text to validate against; the oversize truncation step-down is
silently disabled, because its guard is `cur_trunc > 600`; and **wave 8's own run report
scores the records as `answered`**, because the model did answer — about nothing. That last one
is a real limit of part 1's substrate and is stated here rather than glossed.

**`batch_size` is not part of the defect.** `plugins/_common/llm_client.py::chunked` does
`max(1, int(n))` and its caller does it again, so 0 or negative degrades to one-item batches —
slow, never wrong. It is reported only because what was typed and what ran differed.

**Correct and report, rather than refuse.** A typo in a numeric box should not discard a
configured run, and the old code already substituted a default for non-numeric input. What
changes is that the substitution stops being silent. `0` is left alone: the builder's guard is
`if trunc_chars and …`, so falsy means "do not truncate" — a documented value, not an error.

**Deliberately not done:** clamping inside the prompt builder. The register says "validate the
numerics at entry", and a clamp in the builder would mask a caller's bug rather than surface
it. A direct caller passing a negative value remains unguarded, and that is the honest
residual.

**The checkbox.** Out of scope by decision, and F-118 stays partial. The decision — *wired, not
deleted, in wave 10* — is recorded in the row so it is not re-litigated. One fact for whoever
implements it, found while confirming the checkbox is dead: the LLM/no-LLM choice is **already
expressed by two separate buttons**, `"Harmonise (no-LLM)"` and `"Harmonise + LLM"`, and
`plugins/03_harmoniser/ui.py::_harmonise_llm` never consults `var_llm`. Wiring the checkbox
therefore means deciding what it should mean when it disagrees with the button the user
pressed. That is a design question rather than a coding one, and it is better asked before
wave 10 than during it.

---

## F-119 — `744d4e6`

The log line becomes `model={model!r}`. The two dialogs stop asserting a provider: what is
actually true, and useful, is that the client requires `OPENAI_API_KEY` to be set *even when
the endpoint ignores its value*, so a placeholder will do.

**Writing the test corrected this row's own mechanism, and the correction matters.** The
engine's guard is `if not model:`, and a whitespace-only string is **truthy** — so a whitespace
model never reaches that line at all. What reached it was `""`, because the UI had already
stripped the whitespace away. The row's "reachable trigger being a whitespace-only field"
therefore holds only by way of a strip that happens somewhere else, and the old line was wrong
twice over: it named `None` where the value was `""`. A second test pins the consequence — a
whitespace-only model passed *directly* to the engine goes to the wire, because the engine
cannot tell it from a real one — which is exactly why refusing it belongs in the UI.

**Scope note, and a gap left standing:** `metascreener/api_key_dialog.py`'s window title
(`"OpenAI API Key"`) and its heading (`"Enter your OpenAI API key:"`) are provider-locked
strings on the **first screen a user sees**. They are not covered by F-119, whose evidence cell
names the EL/IL panes and the skip line, and they are left alone. They were recorded in part
1's report and belong to whichever wave deletes that modal.

---

## F-112 and F-137 — `e188a07`

Three sites, one shape, one line each, with the `lambda m=str(e):` binding — which is
**required rather than stylistic**: PEP 3110 compiles `except Exception as e:` with an implicit
`finally: del e`, and the callback runs later on the main loop, so a bare closure would raise
`NameError` inside an `after` callback. In the windowed frozen build that is a silent traceback
with the real message lost.

**The test is static, and the reasoning is worth keeping.** Observing this at run time means
importing `plugins/01_reference_extractor/original/prisma_citations_ai_v3_1.py`, which has
unguarded top-level `import fitz` and `from PIL import Image, ImageTk` — so a behavioural test
would pass here and fail on any machine without PyMuPDF and Pillow. And `tests/conftest.py`
replaces `tkinter` with a `MagicMock`, which is thread-agnostic: real Tk raises `RuntimeError:
main thread is not in main loop`, the mock silently records the call. **A behavioural test
would need to import an unimportable module in order to assert on a mock that cannot fail.**

Reading the AST costs neither. `tests/test_worker_thread_tk_safety.py` walks every
`threading.Thread(target=…)` closure in `plugins/` and fails on any `messagebox` call not
lexically inside an `after(…)` argument — pinning the *property* rather than three instances of
it. It found exactly the three sites, stays green on the seven workers that were already
correct, and carries a vacuity guard so it cannot quietly stop matching the tree.

**Recorded, not fixed:** the same closures read `tk.Variable`s off-thread inside their
`run_pipeline(...)` argument lists — the same defect class at a different site, covered by no
row. And plugin 02's `_ui_tick` closes over its loop variable (F-138) in the same two
functions; fixing the `messagebox` line must not be confused with fixing that.

---

## Scope decisions

**The standalone shells were left alone, deliberately.** They are not twins of the tab Views
for any of this wave's purposes: they carry no status label at all, different buttons
(`btn_export_csv` / `btn_export_xlsx`), `IntVar` + `Spinbox` numerics rather than free-text
entries, and — for F-93 — they already had the *correct* model expression. Neither class is
instantiated anywhere in the repository. Applying the state model to them would mean designing
a second interface for dead code; papering over their divergence silently would be worse.
F-115 records that divergence, and this wave neither deepens nor hides it.

**Everything in the brief's OUT list stayed out:** no endpoint, `base_url`, provider or
discovery work; no manifest provenance field; no cache-key change; no timeout change; the
harmoniser checkbox untouched.

---

## Close-out — part 2

### Goldens — verified both ways

All nine SHA-256 hashes identical to the step-0 manifest recorded at the top of this document,
and `git diff main...HEAD -- tests/golden/` empty. Nothing in part 2 touches an engine path a
golden reaches: every change is in the two Views, in the new pure module, in
`_export_confirm_reason`'s new optional parameter, in one engine log line, and in two plugins
the goldens do not exercise at all.

### Suite

| | |
|---|---|
| Part 2 start (`153a7ce`) | **604 passed, 4 skipped** |
| Part 2 close (`e188a07`) | **695 passed, 4 skipped** |
| Part 2 delta | **+91 passed, 0 skipped** |
| Whole wave (`ed61b6a` → `e188a07`) | **476 → 695, +219** |

The +91 is three new test files plus additions to two existing ones:
`tests/test_stage_state.py` 36, `tests/test_llm_readiness.py` 40,
`tests/test_worker_thread_tk_safety.py` 2, and 4 added to
`tests/test_decision_whitelist.py` — 82 — plus 9 from `test_stage_state.py`'s own growth
across the fix commits. No existing test was deleted. The only existing assertions that
changed are the five characterisation assertions, each by design and each documented in the
test that replaced it.

### Audit tools

| Command | Exit |
|---|---|
| `python tools/audit_imports.py plugins` | **0** |
| `python tools/audit_decorators.py plugins` | **0** |
| `python tools/check_encoding.py` | **0** |

### Register

Regenerated from the rows. **139 rows, 56 closed, 83 open**, still no open Criticals.

| Severity | Total | Closed | **Open** | unscheduled | scheduled | backlog | parked |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Critical** | 4 | 4 | **0** | 0 | 0 | 0 | 0 |
| **High** | 39 | 21 | **18** | 17 | 1 | 0 | 0 |
| **Medium** | 62 | 18 | **44** | 40 | 2 | 2 | 0 |
| **Low** | 34 | 13 | **21** | 16 | 0 | 3 | 2 |
| **Total** | **139** | **56** | **83** | 73 | 3 | 5 | 2 |

Part 2 closed **F-93, F-111, F-112, F-119 and F-137**; opened **F-142** (scheduled, wave 9);
left **F-118** partial; and amended **F-88** — its history entry is now eight keys rather than
seven, because part 1 added `llm`, a *counting* field that changes nothing about that row —
and **F-14**, where the extraction is recorded as a down payment.

### Commits — part 2

| SHA | Subject |
|---|---|
| `18edaab` | `docs: open F-142 — a pre-3f37f17 poisoned cache entry is still undetectable` |
| `ed05fb3` | `refactor: extract the LLM stages' UI decisions into pure functions` |
| `91ed3f8` | `fix(F-111): a state model, so the interface can say which situation it is in` |
| `744d4e6` | `fix(F-119): say what the code observed, and stop naming one provider` |
| `a0e95b0` | `fix(F-93): refuse a model that is not set, and gate an export that did not work` |
| `866c988` | `fix(F-118): restore the readiness gate, and validate the numeric settings` |
| `e188a07` | `fix(F-112, F-137): marshal the worker threads' error dialogs through after()` |

Not merged, not tagged, not pushed.

### What wave 9 inherits

- **F-142 before or after F-89** — F-89's fix strands every pre-fix cache key incidentally, so
  landing it first collapses F-142 to the audit question. The other order wastes the work.
- **F-135 with F-88 tier 1** — both write into the same records; separately they touch every
  evidence writer twice and move the same goldens twice.
- **The state model is ready for an endpoint.** Wave 10 adds three pre-run states as new
  keyword arguments and new branches; `TestTheModelIsExtensible` is the contract that says so.
- **The harmoniser checkbox needs a design answer before it needs code** — see F-118 above.
- **F-139 is the highest-severity open row this wave touched but did not fix**, and every
  later wave makes `.env` carry more while nothing guards it.
