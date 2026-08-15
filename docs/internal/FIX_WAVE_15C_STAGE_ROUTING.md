<!-- SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo -->
<!-- SPDX-License-Identifier: MIT -->

# Fix wave 15c — stage routing (F-65) and the per-provider window (F-203)

*Design, committed before implementation. Part A of the brief: four
questions, answered from the tree, with the corpus consequence measured
rather than predicted. The coordinator adjudicates before Part B.*

## 3. The reference-corpus consequence — measured, and it is severe

*(Answered first because its number governs the adjudication.)*

**Method [measured]:** the real chain, end to end — the corpus
`samples/20260122_1654_aggregate.csv` through
`plugins/_common/parser.py::_parse_csv_tolerant_text`,
`::_load_criteria_from_text`, `plugins/_common/evaluator.py::_eval_criterion`
and `plugins/_common/runner.py::run_screen` — first under today's table
(wave 14c's `runDE_criteria_harmonized.csv`, the post-13d rules), then with
IC-5's stage cell flipped IL→IH. The method validates itself: today's chain
reproduces `776 → EH OUT 16 → 760 → IH OUT 613 → 147` exactly, the same
five numbers wave 13d measured through the same runner.

**The number: routing IC-5 to IH takes the chain to
`776 → 16 → 760 → IH OUT 752 → 8`.** Eight records reach EL. IC-5 at IH
fails 738 of the 760 records it sees, meets 22, misses none. Restricted to
today's 147 EL inputs: 8 MET, 139 FAILED.

**And the number is not what the criterion's prose promises, which is the
second finding of this measurement.** IC-5 reads *"the title, abstract, or
keywords mention …"* — a three-field disjunction. The deterministic
evaluator resolves multi-target criteria through
`plugins/_common/evaluator.py::_get_first_nonempty`, which takes **the
first non-empty target's value only**: over the 760 IH inputs that is the
title for 759 records and the abstract for 1. Routed to IH under the
current evaluator, IC-5 becomes a **title-only** keyword test. Union
semantics — any keyword in any of the three fields, what the prose says —
would keep **22** of today's 147 (70 of the 760); the evaluator as written
keeps **8**. Neither is the 147, and the two differ by nearly 3×.

This narrowing is not registered anywhere: no register row and no
diagnostic section mentions `_get_first_nonempty`'s single-field semantics
against a multi-target criterion. It is filed as **candidate F-204**
(intake at adjudication): *a multi-target deterministic criterion evaluates
only the first non-empty target, so "A, B, or C mentions X" silently means
"A mentions X" whenever A is non-empty.* IC-5 is today the only
multi-target deterministic row, but any hand-authored or re-harmonised
table can produce more.

**What moves and what does not, if the router fix lands:**

- `tests/golden/criteria_harmonized_v3.1.0.csv` — **does not move.** It
  characterises 3.1.0 as shipped and is the criteria INPUT for the EH, IH,
  EL and IL replay regressions and both eval tools
  (`tests/golden/README.md`, the 15a rule). Wave 13d's precedent is exact:
  its F-166/F-167 repairs flipped entries of
  `tests/test_harmoniser_regression.py::EXPECTED_RULES` — the live-translator
  characterisation — while the golden stayed frozen. The router fix flips
  `EXPECTED_RULES["IC-5"]` from `("IL", "contains", …)` to
  `("IH", "contains", …)` in the open, in the fix commit, with the F-65
  comment beside it replaced by the repair note. Golden tree stays
  `043de53a`.
- **No frozen dataset's meta changes.** `docs/data/**` records runs made
  under the rules of their day (F-98/F-99 freeze); the wave-14c/14d run
  data was produced with IC-5 at IL and stays byte-frozen. Their meta files
  already state the criteria table they ran under.
- **The docs that cite 147** — `README.md` (the funnel note),
  `docs/usage.md` (§Plugin 04 chain note and the cache section's
  provenance note), `docs/faq.md` (the provenance note) — say *"the same
  criteria prose harmonised today sends 147 records to EL."* That sentence
  is true of the committed translator and stays true until the router fix
  merges; the moment it merges, "harmonised today" produces IH,IC-5 and
  the true number becomes **8** (current evaluator) — so those passages
  must be updated in the same wave that changes the router, or they join
  F-203's falsified-passages list. The published demonstration's own
  figures (85, 73, the pre-13d chain) are frozen history and do not move.

**What this hands the maintainer to adjudicate, stated plainly:** the
router fix is correct as a matter of routing — a `contains` rule is
deterministic and F-65's own cell names the fix — but whether IC-5 is
usable as a **hard deterministic filter** is a screening-methodology
question, not a code question. Three options, none recommended here:

1. **Route and accept the cut** — EL sees 8 records; the three keywords
   become a hard gate, under whichever semantics (first-nonempty or union)
   is also adjudicated. The 147-citing docs change with it.
2. **Route and disable** — IC-5 moves to IH but ships `enabled=0` in
   re-harmonised tables, surfacing as a deliberate human decision in the
   criteria table rather than a silent no-op. The chain stays 147. (The
   suggestion exists because F-34 made a disabled criterion loud:
   `NOT_SCREENED` semantics guard the nothing-enabled case, and the
   criteria table shows the zero row.)
3. **Route only the class, hold IC-5** — fix the router so no FUTURE
   harmonisation mis-routes (the class F-65 names), but leave the
   committed reference tables untouched (they are wave-14c artefacts and
   frozen anyway). The reference chain changes only when someone actually
   re-harmonises, which is already a human act.

Whichever option is chosen, **the existing-bundle half (question 2) ships
regardless** — bundles carrying contains@IL exist and must stop skipping
silently.

## 1. The router

**Where assignment happens [read].** Branch 6 of
`plugins/03_harmoniser/inference.py::_infer_criterion_details` — the
keyword-in-text branch — sets `operator = "contains"` and then
`stage = "IL" if crit_type == "include" else "EL"`. It is the only branch
pairing a deterministic operator with an LLM stage: branches 1–5 all route
to IH/EH, and the default emits `llm` at IL/EL. (The module docstring
misdescribes its own routing — it claims deterministic-pattern misses
"fall back to operator='llm'" without mentioning branch 6's exception —
and is corrected with the fix.)

**The correct rule, and its existing home.** The compatibility half of the
rule already exists as importable, evaluator-pinned code:
`plugins/03_harmoniser/linter.py::executable_operators` /
`_EXECUTABLE_BY_STAGE` (`EH`/`IH` → the eight deterministic operators;
`EL`/`IL` → `{"llm"}`), pinned against the real evaluator by
`tests/test_criteria_linter.py::TestTheExecutableSetIsNotJustRetyped` and
already delegated to by `preview.py`. Per F-109's discipline the fix
**hoists this map to `plugins/03_harmoniser/parser.py`** — the package's
declared vocabulary home, imported by every relevant module, importing
nothing package-internal — with `linter.py` re-exporting so its public
API stands.

**Both producers need the rule, and the validator is the net.**
- `_infer_criterion_details` branch 6: stage becomes `IH`/`EH` by
  criterion type. One line, plus the docstring.
- `plugins/03_harmoniser/llm_refine.py::_llm_refine` rebuilds rows from
  the model's reply *including the stage*, and its system prompt actively
  invites the violation (*"If unsure, prefer operator=llm and stage
  IL/EL"*). The refiner gains an **auto-route repair** before validation
  (a deterministic operator at an LLM stage is re-staged to IH/EH by
  type, recorded in `warns`, consistent with its existing coercions), and
  the prompt states the pairing.
- `plugins/03_harmoniser/inference.py::_validate_row` gains the
  **cross-check as an error**: an operator the assigned stage cannot
  execute (either direction — `contains@IL` and `llm@EH` alike). Today it
  validates stage membership and operator membership separately and
  never reads both [read, quoted in the reader record]; `contains@IL`
  passes with zero errors and zero warnings. The 13c linter deliberately
  chose warn-never-block *for the linter* and recorded that *"F-65's own
  remedy proposes a `_validate_row` error… Both mechanisms should
  exist"* — this is that deferred half. `_validate_row` is a mutating
  validator called exactly once per row; the cross-check adds no second
  call.

**Hand-edits: possible today, silent today.** The criteria table's stage
and operator cells are editable via read-only comboboxes offering the
full vocabularies in any combination
(`plugins/03_harmoniser/ui.py::_on_double_click`); the save handlers
check membership only. A hand-made `contains@IL` is tinted pale blue by
the linter, with no text unless Validate or Preview is pressed, and
exports cleanly — the export gate reads `_validate_row` errors alone.
Under the fix the pairing becomes a row error: still editable, tinted,
named by Validate — **and no longer exportable**. This blocks nothing at
the *stages* (question 2's constraint); it blocks authoring new bundles
that would silently no-op.

**Candidate intakes surfaced by this reading** (filed at adjudication,
not fixed this wave): **F-205** — `plugins/_common/parser.py::
_load_criteria_from_text` assumes *every* row belongs to the requested
stage when the criteria CSV lacks a `stage` column, and blank-operator
defaults diverge by consumer (`equals` there, `llm` in
`plugins/06_el/screen.py::_parse_criteria_harmonized_csv`); **F-206** —
`_validate_row` never checks type-vs-stage polarity either (an `exclude`
at IH passes), a sibling gap deliberately not bundled into this fix.

## 2. The existing-bundle half — visibility, not a refusal

**What happens today [read, all four sites quoted in the reader
record].** Both engines carry two sites each. In the criterion loop
(`plugins/06_el/screen.py::run_el_screen`,
`plugins/07_il/screen.py::run_il_screen`): `elif c.operator != "llm"` →
an inert stub per record into `llm_results`
(`{"used": False, "decision": "uncertain", …}`). In the per-row status
loop: `if c.operator != "llm"` → `uncertain.append(c.id)`, evidence
`{"status":"UNCERTAIN","note":"non-llm operator in EL/IL stage"}`. The
row loop never reads the stubs — site B short-circuits first. One such
criterion makes PASS_CLEAN unreachable for the whole run (the outcome
ladder requires `not uncertain`), so every survivor is PASS_FLAGGED (EL)
/ REVIEW (IL). The note string reaches every export inside
`*_evidence_json` — and no screen: the EL/IL row-detail modal has no
`note` column, so it is parsed and dropped.

**Worse, the stubs corrupt the run's own diagnosis [read → inferred].**
`summarize_llm_evidence` counts each stub as `no_answer` (no `"error"`
key, `used is not True`), so a deterministic criterion inflates
`no_answer` by one per record; `plugins/_common/stage_state.py::run_outcome` then
misclassifies the run — sole criterion: *"NO ANSWERS"* blaming *"an
unreachable server, a misspelled model name"*; one of ≤10: *"low answer
rate… came back unreadable"* about pairs that were never sent. The
manifest's `llm` block carries the inflated numbers. The completion
message never names the criterion or the cause.

**What already speaks, needing nothing [read — one brief premise
corrected]:** the linter *already has* the check — Check 4,
`plugins/03_harmoniser/linter.py::_check_inert_at_stage`, severity INERT, F-65-tagged, firing
on both directions today (the brief's "the linter gains a check" was
already true since 13c). The preview *already lists* the criterion as
`evaluated=False` with reason *"will never run: IL evaluates only llm…
(F-65)"* and counts `None`-not-`0`. The EL/IL criteria table already
writes a WARNING note (*"operator 'contains' treated as UNCERTAIN in
IL"*). What never speaks: the run report, the manifest, the completion
message, and the row-detail modal.

**The design — four additions, zero behaviour changes to outcomes or
exports (goldens cannot move, and none of these artefacts is golden):**

1. **The run report gains a per-criterion record.** `_run_report` writes
   `not_evaluated: {cid: "deterministic operator 'contains' at IL"}` for
   every non-llm criterion; `_write_llm_stage_bundle` carries it into
   `manifest.pipeline.history[].llm` automatically (`run_outcome`
   ignores unknown keys — non-breaking).
2. **The stubs stop counting as model silence.** Site A stops writing
   stubs into `llm_results` (nothing reads them), so
   `summarize_llm_evidence`'s `no_answer` describes the model again;
   the per-criterion `uncertain` tallies in `crit_impacts` are
   untouched (they feed the criteria table). Record-level artefacts —
   outcomes, evidence JSON, uncertain_ids, reason summaries, FULL.csv —
   stay byte-identical; the EL/IL replay regressions prove it.
3. **The completion message names it, in F-173's register.**
   `run_outcome` gains the not-evaluated facts and, when they exist,
   the label and ack name the criterion and the cause (*"IC-5 was not
   evaluated: a 'contains' rule at IL, which runs llm only"*) instead
   of misdiagnosing the answer rate. Exact wording at Part B under the
   F-173 tests' discipline.
4. **The row-detail modal gains the `note` column** — exactly the EH/IH
   precedent (`_eval_criterion_detail`'s `note` rendered by
   `EHView._open_row_detail_modal`), closing the asymmetry F-65's row
   names. The rendering itself is View code the suite cannot draw
   (conftest MagicMocks tkinter) — a numbered HO at Part B, per
   precedent.

**No refusal anywhere at the stages**: an old bundle with `contains@IL`
runs exactly as before, produces the same rows and exports — it now
says what it did not do, in four places, instead of zero.

## 4. F-203: the per-provider window default

**The seam exists, unused [read]:**
`plugins/_common/llm_client.py::resolve_context_window` already accepts
`stage: str = ""` and never reads it; both engines already pass their
stage. The provider-aware default lands entirely inside that function —
zero engine changes, stored-value-wins untouched (any stored int ≥ 512
returns unconditionally; the floor's rejects fall through to the new
default logic).

**Keyed on the resolved pair, not the provider label.** The instrument
is `plugins/_common/stage_state.py::is_paid_vendor` over the endpoint on the endpoint
`_stage_config(stage)` resolves — session C's principle, and the harm
direction picks it: the drift check aborts only when reality *exceeds*
the estimate, and a server that front-truncates reports *fewer* tokens,
so a hosted-sized default aimed at a local server would be caught by
nothing at run time. The provider label alone could do exactly that (a
`openai` provider with a local endpoint override). The rule proposed:

    hosted default  iff  provider is chosen (not UNCHOSEN)
                    and  is_paid_vendor(resolved endpoint)
    else 4096 (the measured local default, unchanged)

The provider-chosen guard closes the unconfigured-install collision the
reading found: an empty store resolves provider `""` with the vendor
endpoint as fallback, and must keep resolving 4096 — `llm_readiness`
blocks such a run anyway, but `resolve_context_window` should not hand
128k to nothing-configured on its own.

**The hosted number and its basis.** `HOSTED_CONTEXT_WINDOW_DEFAULT =
128_000`. There is **no in-repo basis** [measured — swept]: the only
hosted-window sentence in the tree is README's numberless DeepSeek
comparison. The basis is external and must be cited in the constant's
docstring: OpenAI's model documentation states a 128k context window for
the gpt-4o family including the shipped default `gpt-4o-mini`
**[documented]**. Consequence stated plainly: at 128,000 the shipped
hosted batch-50 flow passes the guard (worst measured request ≈ 16,473 +
4,000 reserve ≪ 128k), un-refusing F-203's regression.
**Known limit:** `PAID_VENDOR_HOSTS` is `("api.openai.com",)` — a
DeepSeek endpoint keeps the conservative 4096 default and a loud refusal
naming the setting as remedy; widening a *money* vocabulary to fix a
*window* default is refused here (`key_required_for` consequences), and
the usage guide's hosted paragraph already tells any hosted user the
setting is the remedy.

**The refusal message when a hosted run still exceeds the default.**
The current third paragraph asserts Ollama's measured last-half-window
truncation; that is a local server's pathology and unestablished for
vendor endpoints. `check_context_budget` gains a `hosted: bool`
(threaded from the engines beside the window, keeping the guard pure):
the hosted branch keeps the arithmetic paragraphs and max_safe, drops
the truncation-mechanism paragraph in favour of the constraint stated
without an unmeasured mechanism, and replaces the closing remedy with
usage.md's hosted wording — *"there is no server of yours to restart:
the remedy is the 'context_window' setting, set to the context length
your model's documentation states"* — plus the batch-size remedy it
already names. The F-173 message tests keep their local-branch pins and
gain hosted-branch twins.

**Second copy of the number, closed:** `llm_provenance`'s
`context_window: int = CONTEXT_WINDOW_DEFAULT` keyword default becomes
**required** — both live callers pass explicitly; a future caller must
not silently stamp 4096 while the real default is pair-dependent.

**The drift check: nothing more needed** — it compares
`usage.prompt_tokens` against the estimator per call, provider-blind,
which covers the wrong-tokenizer risk for hosted exactly as for local.
Its stated blind spot (window smaller than the setting on a truncating
server) is a property of truncation, not of providers, is documented in
usage.md, and no per-provider mechanism changes it.

**What must move with the change [read]:**
`tests/test_context_guard.py::TestTheWindowSetting` (the three
fallback-`== 4096` assertions become pair-aware, with provider/endpoint
inputs controlled; stored-wins survives unchanged; new hosted and
unconfigured pins), the `CONTEXT_WINDOW_DEFAULT == 4096` constant pin
(stays — the local default is unchanged), `plugins/_common/settings.py::defaults`' key
comment, usage.md §The setting, and F-203's three falsified passages —
un-falsified by this design once the hosted flow stops being refused —
plus a **fourth** stale passage the reading found beside them:
README's `SCREENA_EL_BATCH_SIZE` row still says batch size is *"not a
correctness one"*, falsified by F-197 (appended to F-203's evidence at
intake, corrected with the other three).

## Candidate findings for intake at adjudication

- **F-204** — multi-target deterministic criteria evaluate only the
  first non-empty target (§3): the measured 8-vs-22 gap.
- **F-205** — a criteria CSV without a `stage` column loads as
  every-row-at-the-requested-stage, and blank-operator defaults diverge
  by consumer (§1).
- **F-206** — `_validate_row` never checks type-vs-stage polarity (§1).
- **F-203 evidence append** — README's batch-size row, the fourth stale
  passage (§4).

## The questions the coordinator adjudicates

1. **Question 3's number**: option 1 (route and accept 147→8), option 2
   (route and disable IC-5), or option 3 (route the class only) — and if
   IC-5 is ever to run deterministically, **which semantics** (the
   evaluator's first-nonempty 8, or fixing F-204 first for the union 22).
2. `_validate_row` cross-check as **error** (blocks new exports; the 13c
   note anticipated it) versus warning (blocks nothing, F-65's silence
   survives authoring).
3. F-203: the pair-keyed rule and the 128k hosted constant as designed,
   including DeepSeek's stated exclusion.
4. The four candidate intakes.

## Handoffs (Part B — the View strings the suite cannot draw)

`tests/conftest.py` MagicMocks tkinter before any plugin import, so no
View method executes under the suite. Everything below is pure-function
tested up to its last link; the link itself is the observation.

**HO-1 — does the EL/IL detail modal render the new `note` column?**
*Repro:* open any EL/IL FULL row's detail modal (double-click) on a
bundle whose criteria table carries a non-`llm` row at that stage — any
pre-15c bundle, including the golden-era demonstration bundle.
*Expected:* a `note` column, last, showing
`non-llm operator in EL stage` (IL twin) on the stranded criterion's
row and empty on the llm rows — exactly what the EH/IH modals have
always shown for their mirror case.
*Falsifiers:* no `note` column; the column present but empty on the
stranded row; the modal erroring on old evidence JSON.

**HO-2 — does the completion dialog carry the refiner's repairs?**
The pure half is tested
(`tests/test_stage_routing.py::TestTheDialogNamesTheRepair`); the View
threading — worker → `_poll_worker` → `_validate(repair_notes=…)` — is
Tk-mocked.
*Repro:* Harmonise (LLM) with any model; if the log gains a
`LLM refine repair:` line, the completion dialog must open with
*"N adjustment(s) were made to the model's refinement before it was
accepted:"* and the same text as a bullet.
*Falsifiers:* the repair line in the log with an "All good." dialog; the
dialog naming repairs the log does not have; repairs surviving into a
LATER Validate press (they are consumed once, by design).

**HO-3 — does the not-evaluated naming reach the status line and the
export acknowledgement?** `run_outcome`'s label and ack are pure-tested
(`tests/test_loud_skip.py::TestTheCompletionMessageNamesIt`); the Views
render them through pre-existing wiring.
*Repro:* run EL or IL on a pre-15c bundle carrying `contains` at that
stage.
*Expected:* the status line and the `[EL]`/`[IL]` log line end with
*"IC-5 was not evaluated: deterministic operator 'contains' at IL,
which runs llm only (F-65)."*, and the export confirm opens with the
same criterion named and the re-harmonise remedy, ending "Export
anyway?".
*Falsifiers:* a bare "IL done."; an export with no acknowledgement; the
old "low answer rate — came back unreadable" misdiagnosis, which this
wave removed at the source.
