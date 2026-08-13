<!-- SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo -->
<!-- SPDX-License-Identifier: MIT -->

# Fix wave 14b — instrumenting the answer-rate failure

*Design only. This document is commit 1; no implementation accompanies it.*

**Repository state:** `main` @ `9e48614`, clean, in sync with `origin/main`.
**Goldens:** `tests/golden` tree object `050b3575`, 9 files.
**Test baseline:** **1880 passed, 7 skipped** (Windows, measured at gate).
**Register:** 193 rows, max `F-196`, next free `F-197`, one open Critical (`F-168`).
**CI:** 16/16 green on `9e48614`, taken as given from the maintainer's REST-API check;
not verifiable from the tree (**F-165**).

Three rows, all High: **F-194** (nothing of the reply is retained), **F-193** (`no_answer`
is read by nothing), **F-192** (the acknowledgement reassures, and it gates the export).
This wave fixes no model behaviour and changes no prompt. It comes first because the
artefacts currently cannot tell an empty reply from a refusal from a truncated object,
so every later change to the LLM path would be evaluated blind.

---

## §0 What the design work corrected before any code was written

### 0.1 F-193's Evidence cell contains a claim built on a state the producer cannot create — and it is mine

F-193 asserts: *"The guard demands acknowledgement at a 100% answer rate and stays silent
at 5%."* That sentence, written in wave 14a, rests on modelling the flag-only
counterfactual for wave 12's run A as `OUT → 0` with `EXCLUSION_SUPPRESSED` left at `0`.

**That state cannot occur.** Flag-only does not delete an excluding verdict.
`plugins/06_el/screen.py::_excluded_by` appends it to `suppressed`, and the record's
outcome becomes `EXCLUSION_SUPPRESSED`; **F-153** put `suppressed` into `separated`
precisely so the gate would not fire on it. The producer-faithful counterfactual for run A
is therefore `{OUT: 0, EXCLUSION_SUPPRESSED: 40, PASS_FLAGGED: 45}`, not
`{OUT: 0, PASS_FLAGGED: 85}`.

**[measured]**, executing `plugins/_common/stage_state.py::run_outcome` on both:

| state | code | acknowledgement |
|---|---|---|
| run A, flag-only, **as wave 14a modelled it** (`SUPPRESSED: 0`) | `nothing_separated` | **YES** |
| run A, flag-only, **as the producer would build it** (`SUPPRESSED: 40`) | `exclusions_suppressed` | **none** |
| run C as recorded (19.4% `no_answer`) | `ok` — *"EL done."* | none |
| run C, flag-only counterfactual (`SUPPRESSED: 4`) | `exclusions_suppressed` | none |

**So the guard is not inverted. It is absent.** At a 100% answer rate the run is ungated;
at 19.4% unanswered it is ungated; the only gated case is the one where nothing separated
*and* the model was nearly silent, and there the prose then argues the reader out of it
(F-192, whose own measurement uses a state that **is** producible and is unaffected).

F-193's headline — *"`no_answer` is derived, written into the manifest, and read by
nothing … no gate anywhere keys on the answer rate"* — **stands, and is cleaner without
the inversion sentence.** The claim needs correcting in three places: F-193's Evidence
cell, `09_llm_answer_rate.md` §6, and the message of commit `bb428b0`. **That correction
is not made here** — it is a register edit and this commit is a design document. It is
flagged for the coordinator as **HO-1**.

This is exactly the failure Step 3 of this brief warns about — a hand-built state that was
never checked against the producer that would create it — and wave 14a committed it while
naming the risk in the same document.

### 0.2 `finish_reason` and the token counts are not available where the design must read them

F-194's fix cell says *"retain a bounded copy of the reply, plus `finish_reason` and the
token counts"*, and the brief asks which are actually available. **[measured]:**

| field | available in production | available under the suite |
|---|---|---|
| reply text | yes — `resp.choices[0].message.content`, may be `None` | **yes** |
| reply length | yes, derived from the text | **yes** |
| `finish_reason` | yes — `resp.choices[0].finish_reason` | **no** |
| token counts | yes — `resp.usage.*` | **no** |

**Eleven files** define a response double as
`self.choices = [type("C", (), {"message": msg})]` — `tests/_engine_probe.py`,
`test_cancellation.py`, `test_cross_batch_substitution.py`, `test_decision_whitelist.py`,
`test_error_classification.py`, `test_flag_only.py`, `test_harmoniser_llm_call.py`,
`test_negative_caching.py`, `test_provenance.py`, `test_run_report.py`,
`test_terminal_failure_guard.py`. None carries `finish_reason`; none carries `usage`.
**[measured]:** neither string occurs anywhere under `plugins/` or `tests/` today.

This is **F-107**'s accidental pin doing its job. The design reads both through `getattr`
with a `None` default and records their absence as a value, so **no double is widened and
no test changes for this reason.** Widening eleven doubles to buy two fields would be the
larger change and would weaken the pin F-107 asks the project to keep.

### 0.3 F-194's first-choice home would move a golden

F-194's fix cell offers two homes: *"the evidence record or a per-run diagnostic member of
the bundle."* **The first moves a golden. [measured]:**
`plugins/06_el/screen.py::run_el_screen` builds `evidence[c.id]` from **exactly nine keys**
— `status, decision, confidence, threshold, field, quote, quote_valid, span, used` — and
serialises it to the `el_evidence_json` column, which `tests/golden/el_filtered_v3.1.0.csv`
carries. A tenth key moves that golden and its IL twin.

The design therefore uses neither home. See §1.3.

### 0.4 The brief's "wave-13c dialog" does not resolve

The brief names *"the wave-13c dialog"* as the house register for user-facing prose.
**[measured]:** `docs/internal/FIX_WAVE_13C_LINTER.md` contains **zero** occurrences of
`askyesno`, `messagebox` or `showinfo`; wave 13c is the criteria linter and has no dialog.
The dialog wave is **13e** (`build_criteria_preview` and its `kind`).

The register this design actually follows is the one already in the code being edited:
`run_outcome`'s own `no_answers` acknowledgement, and `plugins/_common/bundle.py::_export_confirm_reason`'s
F-34 text. Both do the same four things and none of them is "tell the user what to
conclude": **name the number, state the consequence for the artefact, list the conditions
that produce it, point at where to look, then ask the question.** §3.2 follows that shape
literally.

---

## §1 F-194 — retain a bounded copy of the reply on a no-answer

### 1.1 Where the reply exists and where it is lost

`plugins/_common/llm_client.py::run_m1_llm_for_criterion` binds
`txt = (resp.choices[0].message.content or "[]")`, parses it with `::_parse_llm_json_array`,
and — for any `a_id` the parse loop did not reach — writes the omission back-fill record,
the loop commented *"ensure every item in THIS cur_batch has an entry"*. `txt` and `resp`
are **in scope at that back-fill**, which is what makes this fix cheap.

They are not in scope at the *terminal-failure* back-fill in `except Exception`: there was
no response. That path already records `error` and `error_class` and is not this row's
business.

The record is then refused a cache line by `::_is_cacheable_evidence`, which requires
`used is True` — **F-87**, deliberately, to stop negative caching.

### 1.2 What is retained

**Not per-record copies.** 279 unanswered records in the reported run carried *one*
distinct reply, `[]`. Storing 279 copies of it answers nothing that one copy and a count
do not, and on a 776-record corpus with two criteria the worst case is 1,552 copies.

**A tally of distinct replies, per criterion** — the idiom this module already uses for
`rejected_decisions` and `rejected_fields`, rendered by `::_sample_of`. The key is the
pair `(finish_reason, truncated reply text)`; the value is a count.

Recorded alongside it: the **maximum `completion_tokens` seen on a no-answer call**, which
is the number that separates *"returned two tokens"* from *"returned eight hundred and was
cut off"*. `finish_reason` and `usage` are read via `getattr(..., None)` (§0.2) and their
absence is recorded as the literal `None`, which is itself diagnostic — a server that
reports neither is a different situation from one that reports `stop`.

### 1.3 Where it goes — the call-stats side channel

**Not the evidence record** (§0.3, moves a golden). **Not the cache** — F-87's rule is
correct and reversing it is a separate argued decision, not an implementation detail;
nothing in this design touches `::_is_cacheable_evidence`. **Not a new bundle member** —
that changes the manifest's `sha256` map and buys nothing the existing channel does not.

It goes into the dict returned by `::new_llm_call_stats`, whose docstring already states
the rule this fits exactly: *"a fact about a record is derived from the record; only a fact
about a **call**, which leaves no record behind, is stored in a counter."* A reply is a
property of the call. The dict is passed in and mutated, accumulates across every criterion
of a stage, and reaches the manifest through
`plugins/06_el/screen.py::run_el_screen::_run_report`, which does `report.update(call_stats)`.

**[measured]** that this is additive-safe: no test asserts an exact key set on the stats
dict or the run report — every one indexes named keys — and `run_outcome`'s docstring
states that *"unknown keys are ignored and missing keys default"*, which is how wave 9's
provenance fields were added to the same dict.

### 1.4 The bound, and the number

Two dimensions, both bounded, because either alone is a liability.

**Per-reply character cap: 500.** Defended against the alternative that has already failed
in this repository: **F-186** records that the harmoniser's 200-character window *"ends
mid-token at `"tar`, which reads as a truncated reply; the first reading of the incident
concluded exactly that and was wrong."* **200 is measurably too small — it produced a wrong
diagnosis on a real incident.** 500 holds a complete single-record verdict object (~150
characters as measured in wave 13's probe), a typical refusal sentence, and enough of a
truncated object to see where it stopped. Truncation is marked in the stored value so a
reader never mistakes the cap for the reply's end — the mistake F-186 is about.

**Distinct replies kept: 20, of which 5 are rendered.** 5 matches `::_sample_of`'s existing
default. 20 is the storage cap: beyond it, further distinct replies increment an `other`
counter rather than allocating. Worst case is 20 × 500 = **10 KB per run**, which is
bounded independently of corpus size — the property a per-record copy does not have.

### 1.5 What a user's bundle now carries that it did not

**Up to 10 KB of model output, in the manifest's run report.** The replies are the model's
words, not the corpus's — but a model that echoes its input can put record text into a
reply, so a bundle may now carry fragments of titles, abstracts or keywords that were
previously present only in the corpus members of the same bundle. **It is the same bundle**:
no field leaves the artefact that was not already in it, and no new file is created. It is
not sent anywhere; nothing in this design makes a network call.

Stated plainly because the alternative is discovering it later: this is the first time
model output text is written into the manifest.

### 1.6 What it must not break

- **F-87.** `::_is_cacheable_evidence` is untouched. A no-answer stays uncacheable.
- **The eleven response doubles.** Defensive reads only (§0.2).
- **F-135's distinction.** This records *what was said*, not *which call said it*. F-135
  remains open and untouched.
- **The evidence record's nine keys**, hence both filtered goldens.
- **Log volume.** The per-criterion summary line is emitted once per criterion, like
  F-90's, not once per record — the reporting failure wave 8 exists to avoid.

---

## §2 F-193 — make `run_outcome` read `no_answer`

### 2.1 The seven branches, established from source

`plugins/_common/stage_state.py::run_outcome`, in order: **1** `cancelled` · **2**
`not_screened` · **3** `no_answers` (`records and answered == 0`) · **4**
`nothing_separated` (`total_rows and separated == 0`) · **5** `exclusions_suppressed`
(`suppressed`) · **6** `partial_failure` (`failed or rejected`) · **7** `ok`.

Its docstring states the ordering principle: *"each step is the more specific cause winning
over the more general one."*

### 2.2 Where the new branch goes, and why not elsewhere

**A new branch `low_answer_rate` at position 4**, after `no_answers` and before
`nothing_separated`.

**Why not below `nothing_separated`:** branch 4 fires whenever `separated == 0`, which is
the shape of the reported 15/294 run. A rate branch beneath it would be unreachable in
exactly the case that motivates it.

**Why not below `exclusions_suppressed`:** §0.1's measurement. Wave 12's run C under
flag-only reaches `exclusions_suppressed` and exports **ungated** at 19.4% unanswered. A
rate branch beneath that one would not fire there either — and run C is the only degenerate
run this repository has actually captured.

**Why not merged into `no_answers`:** `answered == 0` has a distinct diagnosis — a dead
server, a typo'd model, an unpulled model, a rejected key — and at a 5% answer rate every
one of those is *false*: the server is up and the model is replying. Same shape, different
remedy, so the same argument branch 3 already makes against `nothing_separated` applies
between these two.

**Why above `nothing_separated` is the *more specific* cause**, in the docstring's terms: a
near-silent model also separates nothing, and the two call for opposite responses — which
is the reason branch 3 is already ordered above branch 4, quoted in its own comment.

### 2.3 The predicate — on `no_answer`, not on `answered`

`no_answer / records >= threshold`, guarded on `records > 0`.

**Not `answered / records < threshold`.** The counters partition `records` into
`answered + no_answer + failed + decisions_rejected`, and the other two already have owners:
`failed` belongs to `no_answers` and `partial_failure`, `decisions_rejected` to
`partial_failure` (F-90). Keying on `answered` would make this branch steal a
partially-**failed** run from `partial_failure` — the distinction F-193's own Evidence cell
draws about `dict(WORKED, answered=60, failed=25)`. Keying on `no_answer` keeps the branch
orthogonal to both, and is what the row's title asks for.

### 2.4 The threshold: 10%

The only calibration this repository has is its three committed local runs:
`llama3.2` **0/170** twice, `qwen2.5` **33/170** (19.4%). The reported 2026-08-13 run is
279/294 (94.9%) and is `[reported]`, not measured.

There is no measured population between 0% and 19.4%, so any threshold in that open
interval separates every degenerate run measured from every healthy run measured. **10%**
sits between the two clusters with roughly 2× margin below run C and unbounded margin above
runs A and B. It is a **choice between two clusters, not a measurement**, and the constant
is named and greppable so a later wave can move it on evidence rather than by search.

What it does to the two anchors the brief names:
- **the 15/294 run (94.9% unanswered):** fires. It currently reaches `nothing_separated`
  and reads as reassuring; it will now reach `low_answer_rate`.
- **wave 12's runs A and B at 100% answered:** `no_answer` is 0, so it **cannot** fire.
  Under flag-only they reach `exclusions_suppressed`, ungated, which is correct and
  unchanged. *(This corrects the brief's premise that they "hit the gate under the shipped
  flag-only default" — §0.1.)*
- **wave 12's run C (19.4%):** fires, where today it exports silently as *"EL done."*

**No floor on `records` is proposed.** A four-record corpus with one unanswered record is
25% and worth stopping on; a floor would create a silent zone precisely where a user is
most likely to be testing their configuration.

### 2.5 The fixture surface, inventoried before designing

**[measured]** — 29 `run_outcome` call sites. Report arguments: `WORKED` (2), `ALL_UNCERTAIN`
(3), `WHOLLY_FAILED` (9), inline `dict(WORKED, …)` (5), `{}` (2), plus `test_flag_only.py`'s
six. Count fixtures: `FLAGGED_ONLY = {"OUT": 0, "PASS_CLEAN": 0, "PASS_FLAGGED": 85}` —
`separated == 0`, so ten call sites currently land on `nothing_separated` — and
`NORMAL = {"OUT": 3, "PASS_CLEAN": 40, "PASS_FLAGGED": 42}`.

**Every one of them carries `no_answer: 0`**, including `ALL_UNCERTAIN = dict(WORKED)` and
all five inline variants, which override `answered`, `failed`, `decisions_rejected`,
`calls_made` or the wave-9 provenance keys and never `no_answer`.

**Consequence, and it is the design's main safety property: no existing assertion changes.**
A branch that fires only at `no_answer / records >= 0.10` cannot fire on a fixture whose
`no_answer` is 0, so all 29 call sites fall through exactly as they do today. This will be
demonstrated, not asserted — the implementation commit reports the before/after counts.

### 2.6 What it must not break

- The ten `FLAGGED_ONLY` call sites must still reach `nothing_separated`.
- `WHOLLY_FAILED` must still reach `no_answers`, not the new branch — it has
  `no_answer: 0` and `answered: 0`, so branch 3 wins on order.
- `partial_failure`'s deliberate non-gating (its own comment: gating a real result trains
  the user to click through the dialog that matters).
- `tests/test_llm_readiness.py::TestTheModelIsExtensible`, which asserts that adding an
  input disturbs no existing state.

---

## §3 F-192 — the prose, and the export gate

F-192's row fixes the boundary: **F-193 owns the guard's logic; F-192 owns the prose and
the export gate.** This design respects it — §2 adds no user-facing string beyond the
branch's identity, and this section adds no predicate.

### 3.1 What F-193's branch does to F-192's existing text, for free

Once `low_answer_rate` sits above `nothing_separated`, the latter is only reachable when the
answer rate is healthy. At that point its existing sentence — *"the model was heard from …
this is a screening result rather than a misconfiguration, and it may well be genuine"* —
**is true**. The branch does not merely add a case; it repairs the truth of the case below
it.

That is most of F-192, obtained structurally rather than by an inline conditional, which is
the cleaner reading of the row's *"condition the text on the answer rate"* and keeps the
predicate on F-193's side of the boundary.

### 3.2 The new branch's acknowledgement

Following the register established in §0.4 — name the number, state the consequence, list
the conditions, point at where to look, ask:

> `{stage}` obtained a usable answer for **{answered} of {records}** record-criterion
> pairs. **{no_answer}** were sent and came back with nothing this stage could read —
> **{pct}%** of the run.
>
> Those records are flagged rather than screened, and an exported bundle will record that
> outcome as though the stage had run normally.
>
> A model that is answering addresses every record in the batch it was given. This is what
> a reply in a shape the parser does not accept, a batch size the model cannot hold, and a
> criterion the model will not engage with all look like. The Log tab carries a sample of
> what came back.
>
> Export anyway?

The last pointer is only honest **because F-194 lands in the same wave** — without the reply
sample there is nothing at the end of it. That is the dependency between the two rows and
the reason F-194 is implemented first.

Nothing in it tells the user what to conclude. The word *genuine* does not appear.

### 3.3 `nothing_separated`'s own text

One addition, so the reassurance is auditable rather than asserted: name the unanswered
count alongside the answered one. The reader can then see the basis for *"may well be
genuine"* rather than taking it. No other change; the sentence is now true (§3.1).

### 3.4 The export gate — a user-visible behaviour change, said out loud

**Yes, export gating changes.** The new branch carries an `ack_reason`, so
`plugins/_common/bundle.py::_export_confirm_reason` returns it and both export paths in
`plugins/06_el/ui.py::ELView` and `plugins/07_il/ui.py::ILView` put up
`messagebox.askyesno("Check this before exporting", …)`.

**Concretely: a run shaped like wave 12's run C — which today exports silently as
"EL done." — will stop and ask.** That is the point of the wave, and it is the kind of
change that must be in a release note rather than discovered.

Buttons are **not** disabled. `plugins/_common/stage_state.py::control_states` keeps
`export=(not running) and has_rows`; this design does not touch enablement, so the gate
stays a modal on click, exactly as F-34 and F-93 built it.

### 3.5 What it must not break

- The `no_answers` text stays the more specific diagnosis for `answered == 0`.
- No string exceeds the ≤16-character pin `tests/test_llm_readiness.py` places on
  *readiness* labels — that pin is on the readiness arm, not on outcome labels, and this
  design adds nothing to the readiness arm.
- `_export_confirm_reason`'s F-34-first ordering: a stage with no criteria still gets the
  "no enabled criteria" text, not this one.

---

## §4 The three questions the brief asks before code

### 4.1 Which existing tests change, and why

| Test | Changes? | Why |
|---|---|---|
| the 29 `run_outcome` call sites | **no** | every fixture carries `no_answer: 0` (§2.5) |
| the 11 `_FakeResponse` doubles | **no** | `finish_reason`/`usage` read via `getattr` (§0.2) |
| `tests/test_run_report.py` | **added to** | new assertions on the reply tally; existing ones index named keys and are additive-safe |
| `tests/test_llm_readiness.py`, `tests/test_stage_state.py` | **added to** | the fixture F-193's row says the suite lacks — an `llm_report` with `no_answer > 0` fed to `run_outcome` |
| `tests/test_el_regression.py`, `tests/test_il_regression.py` | **no** | §4.2 |

**No test changes to accommodate a defect.** The two files gaining assertions gain them for
behaviour that is new; nothing existing is relaxed. If implementation forces an existing
assertion to change, that is a design error and comes back here rather than being absorbed.

### 4.2 Does any golden move? **No.**

- `run_outcome` is called only from `plugins/06_el/ui.py::ELView` and
  `plugins/07_il/ui.py::ILView`. **[measured]:** it appears nowhere in
  `tests/test_el_regression.py`, `tests/test_il_regression.py` or `tests/conftest.py`, so it
  is not on the replay path at all.
- The reply tally goes to the call-stats dict, not to the nine-key evidence record, so
  `el_evidence_json` and `il_evidence_json` are byte-unchanged (§0.3).
- `::_is_cacheable_evidence` is untouched, so `el_cache_v3.1.0.json` and
  `il_cache_v3.1.0.json` are unchanged.
- No bundle member is added, so no manifest digest map changes.

`git diff main...HEAD -- tests/golden/` must be empty at wrap-up, and the wrap-up checks it.
**If implementation moves a golden, this design was wrong and the session stops and reports
rather than re-capturing.**

### 4.3 Does `PROMPT_VERSION` bump? **No.**

Nothing here touches `plugins/06_el/prompt.py` or `plugins/07_il/prompt.py`. The cache key
(`plugins/_common/llm_client.py::_cache_key`) hashes the *rendered prompt*, the model, the
endpoint and the temperature — none of which this wave changes — so no cache is invalidated
and no key moves. The wave adds a side-channel observation of what came back; it does not
change anything that is sent.

---

## §5 Order of implementation

1. **F-194 first.** F-192's acknowledgement points at a reply sample; without F-194 that
   pointer is a lie.
2. **F-193 second.** The branch, its threshold constant, and the fixture the suite lacks.
3. **F-192 third.** The prose for the new branch and the count added to
   `nothing_separated`.

Each is one commit, test-first with the failure watched and reported. The UI-adjacent work
in §3 is prose returned by a pure function (`run_outcome`) that the suite already drives
directly, so the extract-then-fix shape the brief asks for is already satisfied by the
existing separation — `run_outcome` **is** the extracted pure function, which is what wave 8
built it for. No new extraction is proposed, and §3 of the refutation pass will demonstrate
that the suite executes the changed code rather than asserting it.

## Handoffs

**HO-1 — F-193's Evidence cell, `09_llm_answer_rate.md` §6 and commit `bb428b0`'s message
each assert an inversion built on an unproducible state (§0.1).** The correct statement is
that no gate keys on the answer rate at all — the headline of the row, unchanged. Repro:
run `run_outcome` with `counts={"OUT": 0, "PASS_CLEAN": 0, EXCLUSION_SUPPRESSED: 40,
"PASS_FLAGGED": 45}` and run A's report; observe `exclusions_suppressed` with
`ack_reason=None`, not `nothing_separated`. **This is a register edit and is outside this
commit's scope; it needs the coordinator's decision on whether it lands in this wave or its
own.**
