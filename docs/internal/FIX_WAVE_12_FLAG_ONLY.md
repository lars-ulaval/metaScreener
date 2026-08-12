# Fix wave 12 — flag-only, and three defects found by using the software

**Session A (code).** Branch `fix/wave-12-flag-only`, off `main` at `8b5a972`.
Session B owns the measurement write-up; nothing here is that document.

This is the last wave. It exists because the maintainer built the software and
ran it, which produced two things no amount of reading would have: a
**measurement** that decides what the LLM stages are allowed to do, and **three
defects** that 1330 green tests were fully compatible with.

---

## 1. The measurement, and what follows from it

Two bundles, produced by the maintainer against two local models. EL stage, 85
records, the same corpus and the same criteria as the committed goldens, both
runs fully attributed by wave 10's provenance block:

| Model | Exclusions | Audit |
|---|---|---|
| `gpt-4o-mini` (the golden) | **1** | correct |
| `llama3.2:3b` | **43** | all 43 unjustified |
| `qwen2.5:7b` | **4** | all 4 unjustified, confirmed by the author |

qwen's four were A286 and A301 (brain–computer interface), A310 (neuromotor
rehabilitation) and A423 (a report on teenagers and social media), all excluded
against EC-2, which asks whether the paper's primary focus is spatial navigation
in a virtual maze. None is a maze-navigation study. The likely mechanism is that
the model read EC-2's parenthetical — *"(no social interaction or
collaboration)"* — as an independent second condition.

**Every one of those exclusions passed the evidence gate**, with a verbatim quote
and a confidence above threshold.

That is the finding, and it is not a bug in the gate. `_quote_in_text` verifies
that a quote is *real*. Nothing in this pipeline can verify that a quote is
*relevant*, and nothing short of another model could. Wave 8's counters rule out
the comfortable explanation: llama3.2 answered **170 of 170** record-criterion
pairs in perfect JSON with **zero** vocabulary rejections. It did not fail to
follow the format. It asserted matches that were not there.

qwen answered 137 of 170 and left 33 unanswered, which correctly became flagged —
the fail-safe path works exactly as designed. The failure being closed here is
the one the fail-safe path cannot see, because it does not look like a failure.

### The conclusion

> A local model can read and annotate. It cannot be trusted to **remove** a paper
> from a systematic review.

And that costs almost nothing here, because of where exclusions actually come
from in this pipeline: **EH removes 125, IH removes 566, EL and IL together
remove 5.** The deterministic stages do 99.3% of the work. Forbidding LLM
exclusion means a reviewer reads 85 abstracts instead of 80 — five more — in
exchange for eliminating the false-exclusion class entirely, while keeping
everything the model is good at: the reasons, the quotes, and the ordering of
what to read first.

It is also §8 of the project's own commitment applied one level up. Every failure
path already routes to human review rather than exclusion. This says that when
the **engine** cannot be trusted, the same rule applies.

---

## 2. What a user gets now

**Running a local model (Ollama, LM Studio, llama.cpp, vLLM — `local` or
`custom`).** The LLM stages read every record, produce reasons, quotes and
confidences, and flag what they think should come out. They do not take anything
out. A record the model wanted excluded is labelled `EXCLUSION_SUPPRESSED` and
survives to human review, with the criterion named, the quote kept and the
confidence recorded. The run summary says how many. The bundle's manifest records
that the run was flag-only, so a later reader can tell this artefact from one
produced with exclusion permitted. Before the run starts, the tab now says how
many records and requests are coming, whether the server is running the model on
the GPU or the CPU, and — once it has timed a request against that server — how
long it is likely to take. If the server goes away and comes back, there is a
**Re-check** button instead of a restart.

The user can turn exclusion on. It is one setting, and the measurement above is
what they should read before doing it.

**Running OpenAI.** Nothing about screening changes. `openai` is the
configuration the published validation study measured, so exclusion is permitted
by default and the pipeline behaves exactly as it did — the nine goldens are
byte-identical, which is the proof rather than the claim. What is new is
everything that is not screening: the pre-run confirmation with a record and
request count before a billable operation, the compute-mode line where it can be
determined, the re-check button, a harmoniser "Harmonise + LLM" button that works
at all, and a provider dialog that no longer throws a traceback on every launch.

---

## 3. The three design questions, and how they were answered

### Where the setting lives

`plugins/_common/settings.py`, **application level only**, as a tri-state:
`None` means *nobody has chosen* and the provider answers; a genuine `True` or
`False` is an explicit user choice and wins outright. It is resolved into
`StageConfig` by `resolve_stage`, the one place any stage configuration is
decided.

Per-stage override was considered and rejected. `endpoint` *is* overridable, so a
stage genuinely can point at a different engine, which is the argument for it.
The argument against won: this is a trust decision about the engine, and wave 11's
invariant 2 deliberately made the engine's identity an application-level fact that
a stage may not vary — `provider` is refused by `STAGE_OVERRIDABLE` **and**
ignored by `resolve_stage`, so a hand-edited settings file cannot smuggle one in.
A policy whose cause cannot differ per stage should not itself differ per stage.
It also avoids three silent-failure traps on that path: `_clean_stage_entry` drops
booleans on the floor, `stage_overrides_for`'s baseline would pin the flag as a
permanent override on first tab focus, and `STAGE_OVERRIDABLE` is a closed set
asserted by test — three ways to ship a setting that looks stored and is not.

**The default is computed, never stored:** `flag_only = not key_required(provider)`.
Two reasons, and the second is not an aesthetic one.

1. It reuses F-117's single predicate rather than adding a second that answers the
   same question and drifts. The coincidence is not being exploited: a keyless
   provider *is* a local or self-hosted engine, which is exactly the population
   the measurement covers.
2. **It is empirically forced.** `tests/conftest.py` isolates `APPDATA` and
   `XDG_CONFIG_HOME` to an empty directory, so every golden replay resolves
   `provider = UNCHOSEN = ""`. The naive rule — *permit only when provider ==
   "openai"* — makes `""` flag-only, which flips 1 EL record and 4 IL records from
   `OUT` to suppressed and **moves two byte-identity goldens** on a wave whose
   brief says nothing may move. `key_required("")` is `True`, so the rule chosen
   leaves them untouched. This was checked by running the goldens, not by
   argument.

A stored boolean would also have been wrong the moment the user switched provider —
the same mistake as the shipped `provider="local"` and `batch_size=5` defaults,
both of which caused live defects and are documented in `defaults()`.

### What a suppressed exclusion produces

A new per-criterion status `SUPPRESSED` and a new record outcome
`EXCLUSION_SUPPRESSED`, produced at the **four** `status = "FAILED"` sites — two
per stage. Both arms are gated in both engines, including the ones each file
labels *"not expected"*: polarity is carried by the criterion's `type` cell rather
than by the stage, so a hand-edited or third-party criteria table reaches them,
and a gate on only the expected arm is a gate with a door beside it.

It had to be **distinguishable from an uncertain flag**, and it is by
construction rather than by convention: `PASS_FLAGGED` / `REVIEW` mean *the gate
refused the verdict* — the quote did not validate, the confidence sat below
threshold, the model said "uncertain". `EXCLUSION_SUPPRESSED` means *the gate
passed the verdict and policy declined to act on it*. Those are different facts
about the record and a reader must be able to tell them apart. Reusing a label
that asserts something other than what happened is precisely F-34's error, whose
marker sits twenty lines above the code this wave changed.

**The IL analogue needed no special case, and that is a result rather than a
convenience.** EL's criteria are exclude-typed and exclude on `meet`; IL's are
include-typed and exclude on `not_meet`. The verdict polarity is mirrored, but the
*action* is identical — `failed` → `OUT` → dropped from `survivors` → absent from
`data/current.csv`. One rule covers both. There is no soft "not included" state in
IL to invent, because a confident refusal to include already **was** an exclusion.

**No new report column.** A column would move
`tests/golden/{el,il}_filtered_v3.1.0.csv`, which are byte-identity goldens whose
re-capture this wave cancelled. What the model said is kept where it already
lives: the evidence JSON carries `status: "SUPPRESSED"` beside the decision, the
confidence and the quote, and `{stage}_reason_summary` names the criteria in prose
for the human who has to act on it.

The count comes from the outcome histogram the engine already builds. Nothing
re-scans `full_rows`, `row_eval_lists` or the exported CSV to recover it — that is
F-69's shape, which this project has shipped four times.

### How the manifest records it — **a disagreement with the brief**

Not inside wave 10's provenance block. A **sibling** of `llm` and `provenance` on
the history entry, lifted by the same omission rule.

The brief called provenance the natural home and invited disagreement. Here is
the disagreement. Wave 10's provenance block carries a contract, pinned by
`tests/test_provenance.py`:

> A cached entry cannot be served into a run whose provenance differs in any
> recorded field except `batch_size`.

Flag-only **cannot affect a verdict**. It acts strictly downstream of one, on what
the pipeline does with an answer the model has already given. So recording it
inside provenance forces one of two wrong things: either the contract is honoured
and toggling the policy invalidates 254 perfectly valid cached verdicts for no
scientific reason, or the contract gains a second unexplained exception and a
pinned invariant is quietly weakened. A sibling key states the fact and touches
neither. Provenance answers *how were these verdicts obtained*; this answers *what
was done with them*, and they are different questions.

Read back through `bundle.py::history_exclusion_policy`, which is **tri-state**.
Every bundle written before this wave lacks the key, and
`bool(entry.get("exclusion_policy", False))` would read those as *"this run
excluded records"* — a false positive claim about a real screening decision, on an
artefact already in users' hands. That is F-68's rule, whose statement in this
codebase is `InputError.observed_len`'s: *an empty cell means "not measured" and
not "measured as zero"*. Unrecognised values read as unrecorded rather than being
guessed at, which is F-70's half of the same rule.

### The constraint that nearly bit: not a second F-34

`run_outcome`'s fourth branch fires on `separated == 0`, where `separated =
counts["OUT"] + counts["PASS_CLEAN"]`. Suppressing exclusions drives `OUT` to
zero. Without a branch of its own, a **correctly configured, fully successful,
deliberate** run would have reported *"nothing separated — every record flagged"*
**and raised an export acknowledgement gate** — asking the user to acknowledge a
working safety feature as damage.

That is F-34 with the sign flipped: a label asserting the opposite of what
happened. `OUTCOME_EXCLUSIONS_SUPPRESSED` sits above that branch with
`ack_reason=None`, and cancellation, no-criteria and no-answers still beat it,
because a dead server also suppresses nothing and must still report as a dead
server.

---

## 4. The three defects from the field

All three were found by the maintainer in twenty minutes of use, against 1330
green tests.

### F-149 — readiness never re-checked

The application probed the provider once, at launch, and never again. His Ollama
server stopped, the tab read "Unreachable" with the buttons dead, he restarted the
server, and the tab still read "Unreachable" until he relaunched metaScreener.
Confirmed in source rather than assumed: `_refresh_provider_status` has exactly two
call sites, both one-shot; `main.py` contains two `self.after(` calls and neither
repeats; there is no timer, no polling loop and no re-check control anywhere. Once
the launch probe's thread finishes, `provider_detect._PROBES` is frozen for the
session.

A shared `widgets.py::RecheckButton`, beside the readiness indicator in all three
LLM tabs — where the user is looking when it says "Unreachable". It re-probes
**only this stage's endpoint**, not through `main.py::_refresh_provider_status`,
which opens with `pd.forget()` and would drop every other tab to `NOT_CHECKED`
because this one asked a question. **Not a repeating timer**, for that reason plus
two others: a poll would flicker every tab on a heartbeat, and would probe a
server the user is not asking about on a machine that may be metered or asleep.

Written once rather than three times, and the reason is not F-14 but F-147: the
risky part is the thread and its teardown, the Views carry no destroyed-widget
guard anywhere, and `Plugin.on_close` destroys a View without stopping its
workers. Three unguarded background threads in three tabs would have re-opened, in
triplicate, the defect fixed one commit earlier.

A second route closed with it, which was not reported: `_effective_endpoint`
prefers the live widget value, so typing a new endpoint sent a tab to
`NOT_CHECKED` with nothing able to ever resolve it. `provider_detect.py` already
carried a comment admitting this.

### F-147 — the provider dialog wrote to a destroyed widget

Every launch. Reproduced here in a real-Tk subprocess with the identical widget
path before it was fixed:

```
_tkinter.TclError: invalid command name ".!providerdialog.!frame.!label2"
```

Two guards, and both are needed. `_post` wraps `self.after` and swallows the
`TclError` a dismissed dialog raises — that call runs on a daemon thread, where
the exception is a traceback on stderr and nothing else. And `_status_arrived`
returns early on `not self.lbl_status.winfo_exists()`, because a dialog destroyed
*between* a successful `after` and the callback firing lands in the callback with
a dead label, which is exactly the reported traceback. The guard tests the label
rather than the toplevel: a widget can be destroyed while its toplevel lives, and
the label is what the method writes to.

`_pull_finished` and the download progress callback carried the same defect and
were fixed with it — found by reading the neighbourhood, and a multi-gigabyte pull
makes the dialog *more* likely to be gone on completion, not less.

**Should the smoke test cover dialogs? Yes, and now it does.** Three reasons this
could not be seen before: `conftest` replaces `tkinter` with a `MagicMock`, under
which `configure` on a destroyed widget returns a mock instead of raising;
session C's `test_view_smoke.py` covered the three Views and no dialog at all; and —
the part that matters most — an exception inside an `after` callback goes to Tk's
`report_callback_exception`, which prints and returns, **leaving the process exit
code at 0**. A test that merely ran the callback would have passed green while the
defect fired in front of it. The recorder installed on
`report_callback_exception` is what makes these tests assert anything.

### F-146 — the harmoniser's LLM path, and why the visible error was the wrong one

This is worse than the brief describes, and the difference is the fix.

`_call_openai_json` was two `try` blocks. The first is the modern, correct call
added by wave 11's F-117 fix; its except arm was a bare `except Exception: pass`.
The second called `openai.ChatCompletion`, removed at SDK 1.0, against a project
declaring `openai>=1.40.0`.

So the error the maintainer saw —

```
LLM call failed: You tried to access openai.ChatCompletion, but this is no
longer supported in openai>=1.0.0
```

— **proves the modern call had already failed, and says nothing about why.** Every
real cause (refused connection, rejected key, mistyped model, a fenced reply) was
discarded and replaced by a migration notice about a code path he never invoked,
sending him to look at his SDK version instead of at his server.

`hasattr(openai, "ChatCompletion")` is `True` on the installed 1.106.0 — the SDK
ships an `APIRemovedInV1Proxy` that exists only to raise — so no runtime
capability check would have caught this. A source-level ban is what works, and it
must read structure: this repair's own docstring quotes `openai.ChatCompletion` to
explain why it is gone, which a text search flags as the defect it documents.

Three parts, not one:

* the removed branch is **deleted**, not repaired;
* the surviving call **no longer swallows its exception**, so the message box shows
  the actionable cause — a deliberate, user-visible behaviour change;
* `timeout_s` is **forwarded** rather than orphaned. It was consumed only by the
  removed branch, so deleting that branch alone would have left plugin 03's LLM
  path with no timeout expression at all — the diagnostic's C-19, a regression
  hiding inside a repair.

Parsing now goes through `_parse_llm_json_object`, which shares `_strip_code_fence`
with `_parse_llm_json_array` rather than restating it. The harmoniser parsed with a
bare `json.loads` while the engine path has stripped Markdown fences since wave 6,
and local models fence their JSON routinely — the failing run was against
`llama3.2:latest`, so this is the most likely thing the dead branch was hiding.

**Why it survived**, as asked. The call path had **zero execution coverage**: every
assertion touching it was a string or AST match over the unparsed source, which
reads code without running it. `tests/test_harmoniser_llm_call.py` is the first
test that executes the function. The second reason is F-148, below, and is a
finding about the diagnostic rather than about this module.

---

## 5. Part 3 — plugin 01, and the general question

**Plugin 01's vision path is not stale.** `ai_extract_included`
(`plugins/01_reference_extractor/original/prisma_citations_ai_v3_1.py:329`) uses a
**current** interface throughout: the `OpenAI(...)` constructor,
`client.chat.completions.create` with `tools=` / `tool_choice=` rather than the
removed `functions=` / `function_call=`, and the v1.x response shape
`message.tool_calls[0].function.arguments`. It is **live**, verified rather than
assumed: `plugin.py:36` imports it and `plugin_manager.discover` loads every
plugin unconditionally.

Its client is built with `api_key` and **no `base_url`**, so it never consults the
settings store and always reaches the vendor. That is F-92's shape but it is
**declared, not accidental**: `plugin.py` carries a banner stating that this tab
calls OpenAI directly and is billed even when the screening stages are set to a
local model, and `tests/test_startup_flow.py` asserts that banner's wording. Left
alone deliberately — changing it would silently alter a documented promise.

**Is there any other code calling an SDK interface that no longer exists? No.**
All four `.create(` sites were checked; three use the current interface and the
fourth is the one deleted here. The answer is now a test rather than a claim:
`TestNoRemovedSdkInterfaceSurvivesAnywhere` sweeps every tracked `.py` for the
eight interfaces removed at SDK 1.0, over the **AST**, and the finder is itself
tested against the pre-fix body so a silently broken guard cannot read as a clean
tree.

### F-148 — two findings about the diagnostic

Answering that question surfaced two errors in the document that produced the
four-site count, and both are recorded.

1. **Its summary table contradicts its own prose.**
   `06_llm_integration.md:156` marks the `openai.ChatCompletion` branch
   **"No — dead (§A1.3)"**. §A1.3, twenty lines later, says the opposite and is
   right — and even names the fenced JSON reply that is the most likely cause of
   the maintainer's failure. The brief supposed nobody read the call. Someone did,
   in prose, and the table then contradicted them; the table is what was carried
   forward. That is the measured cost of a wrong label: it is why nobody re-read a
   call broken on every install for two years, while the diagnostic flagged its
   *neighbourhood* repeatedly — dead branches, a divergent predicate, a `timeout_s`
   forwarded only on a path that never runs. Every one of those observations is
   consistent with the branch being **live**. None was reconciled against the label.

2. **The inventory is incomplete, and the incompleteness is about method.** Its
   heading claims exactly three modules send a prompt to a language model. That is
   true of *chat completions* and false of *routes to a model server*. Two live
   routes reach one over raw `urllib`, with no SDK and no `.create(` in them:
   `model_pull.py::pull` (POST to Ollama's native `/api/pull`, from the dialog's
   download button) and `provider_detect.py::_fetch_models` (GET `{endpoint}/models`
   carrying the API key as a Bearer token, on the launch path for the app endpoint
   and every per-stage override). Neither is affected by the 0.x removal — but "the
   diagnostic counted exactly four `.create(` call sites" is a true statement about
   a grep and a false one about the question anyone actually asks it.

Both are corrected in place: row 3 struck through and annotated, rows 5 and 6
added, and a correction note naming both errors.

---

## 6. Part 4 — compute mode

The maintainer's run took hours and pegged his CPU. His own Ollama log says why:

```
msg="discovering available GPUs..."
inference compute id=cpu library=cpu name=cpu total="63.8 GiB"
msg="vram-based default context" total_vram="0 B"
```

Ollama never found his RTX 3060. **metaScreener cannot fix that and does not
try** — GPU detection is Ollama's business and the user's machine is not ours to
configure. Reporting a consequence is not the same as configuring a machine.

**F-150.** `provider_detect::compute_mode` reads Ollama's `/api/ps` and returns
`gpu` / `cpu` / `partial` / **`unknown`**. The fourth is the load-bearing member: a
server that is not Ollama has no such route, and Ollama unloads idle models, so
"cannot say" is the ordinary answer and must never be rendered as "CPU". Telling a
user with a working GPU that they are on the CPU would send them to reinstall
drivers they never needed to touch — D5's harm shape. An **absent** `size_vram` on
an older build reads as unknown rather than as zero (F-68 again). It never raises,
because it is reached from a pre-run path and a reporting nicety must not block a
run. **The run is not gated on it: CPU is slow, not wrong.**

**F-151.** `_run_clicked` began a long, and on OpenAI billable, operation with no
record count, no request count, no estimate and no confirmation. The gap was
already written down twice in this repository — `provider_dialog::_offer_pull`'s
docstring and `test_model_pull.py`'s module docstring both say the download
ceremony is deliberate *because* `_run_clicked` starts a billable operation with
less. This is the other half of that sentence.

The design line is **counts and duration are kept apart**. Records, criteria,
record-criterion pairs and requests-at-this-batch-size are arithmetic over loaded
data and are stated flatly. A duration is not, so it appears **only** from a rate
measured against this endpoint and model in this session; with nothing measured
the text says there is no basis for one. That refusal is not fastidiousness — a
plausible seconds-per-request constant is exactly how F-125 came to describe a
cost wrong by two to three orders of magnitude.

`llm_client` times every call in a `finally`, so a server that takes thirty
seconds to refuse also counts: that is the run a user most needs warned about. The
rate is a session mean rather than the last call, so one cold model load moves the
estimate instead of becoming it, and it is held in memory only, because a rate
measured against a since-restarted server that has now found its GPU is worse than
no rate at all.

The dialog sits **after** the readiness check — no point confirming a run that
cannot start — and **before** any control enters its running state, so declining
leaves the tab exactly as it was. It carries the compute mode and, when in force,
flag-only, because that changes what the run *means* rather than what it costs.

---

## 7. The review pass, and what it cost

Run by **executing**, as instructed. Seven lenses, each required to paste a
command it actually ran and the output it actually saw, and to discard anything
it could not make fail. The two mandatory lenses both paid.

**Lens 1 — produce an exclusion under flag-only, by any route.** It could not.
Every attack is recorded in the transcript: the full (ctype × decision ×
confidence × threshold) cross product including confidences above 1.0 and
thresholds of 0, cached excluding verdicts served through `use_cache=True`, a
criterion typed neither include nor exclude, duplicate and empty `local_id`s,
the zero-criteria path, the standalone shells, and every downstream consumer
that might re-derive a removal from `el_failed_ids`. `tests/test_flag_only.py`
pins the cross product so the answer stays answered.

**Lens 2 — reach the paid vendor with a keyless provider. It succeeded**, and
that is **F-152**: `api.openai.com．` — a fullwidth full stop — read as *not*
the vendor, so a keyless provider passed the gate, while IDNA folds U+FF0E,
U+3002 and U+FF61 to `.` and the request resolves to the vendor's real server.
INV-1 broken a fifth time, by one character, in the guard written to close the
fourth. The same function raised `ValueError` on `http://[::1` from inside a Tk
callback rather than answering.

That is the fifth instance of one defect class, and the **third** found by
executing rather than reading. The lesson is not about hostnames. It is that
this particular invariant has never once been broken in a way a reader would
notice, and every closure of it has been a closure of a *spelling* rather than
of the class — including this one, which is why the new test asserts the IDNA
folding itself rather than trusting a list of code points to stay complete.

**The review also found five defects this wave had just introduced** (F-153),
and one missing deliverable. Three are worth restating because they are the same
shape: a new value or a new caller reaching a surface written before it existed.

* `run_outcome`'s new branch cancelled F-93's export acknowledgement whenever
  *any* record was suppressed, so one suppression among nineteen unresolved
  records bought silence for the whole run — and did so most readily for the
  weak local models flag-only exists for. Repaired in `separated`, on the
  principle that **the two policies must judge run quality identically**.
* `_run_summary_counts_text` never learned `EXCLUSION_SUPPRESSED`, so the line a
  user reads as the result printed `OUT: 0 | PASS_CLEAN: 0 | PASS_FLAGGED: 19`
  for a corpus of 20. F-34's requirement 2, reproduced for the value F-145 added —
  the exact error this wave spent three paragraphs planning to avoid, committed
  one function away from where it was being avoided.
* The Re-check button reached `on_provider_changed`, which ends in
  `_set_controls_running(False)`. Harmless for its previous callers, which only
  fire at launch; reachable **during a run**, where it disabled Cancel and
  re-armed Export over rows the worker was still writing.

**The missing deliverable.** The brief asked for the setting to be
user-changeable *with the measurement stated where the user changes it*. It
shipped with no writer at all: the README called it user-changeable and the
engine's own log line told the user to change it "in the provider settings",
while no widget anywhere could write it — F-91's shape, the defect where the
documentation described an endpoint no control bound. `ProviderDialog` now
carries the checkbox and the measurement beside it, tri-state preserved, driven
end to end by five smoke tests.

### What the review could not finish

**Twenty of the thirty-two verification agents died on a session limit**, so of
25 candidate findings only a handful were adversarially verified. Everything
acted on above was verified — either by an independent refutation agent
(the `run_outcome` finding, which came back confirmed with a corrected severity
and two corrections to the reporter's reasoning) or by me re-running the repro
in the real repository (F-152's two claims, the counts line, the mid-run control
reset).

The rest are **reported but unverified**, and are recorded here rather than
silently dropped, because an unverified finding is not a refuted one:

| Claim | Area |
|---|---|
| `RunPlan.requests` ignores adaptive batch splitting, so the estimate is low on the runs that split | `run_estimate.py` |
| `compute_mode`'s timeout does not bound total blocking time on a slow body; it runs on the GUI thread | `provider_detect.py`, `_confirm_run` |
| The observed rate is keyed by (endpoint, model) but not batch size, so a rate measured at one size mispredicts another | `run_estimate.py` |
| The criterion drill-down filters on outcome, and may hide exactly the suppressed records | `06_el/ui.py`, `07_il/ui.py` |
| `_fetch_models` forwards the API key across a cross-host HTTP redirect *(pre-existing, not this wave)* | `provider_detect.py` |
| The AST-based SDK ban can be fooled by an alias import or `getattr` | `test_harmoniser_llm_call.py` |
| `test_worker_thread_tk_safety.py` scans `plugins/` only, so it cannot see `metascreener/` | test coverage |
| `RecheckButton._post` catches `TclError` but not the `RuntimeError` a shutdown mid-flight can raise | `widgets.py` |

None is a correctness defect in screening output on the evidence available. Each
needs the same treatment the confirmed ones got — a repro, executed — before it
is either fixed or refuted, and none should be actioned on the strength of an
unverified report.

## 8. Verification

| Check | Result |
|---|---|
| Suite before | 1330 passed, 7 skipped |
| Suite after | **1534 passed, 7 skipped** |
| Goldens, both ways | **9/9 SHA-256 identical**; `git diff main..HEAD -- tests/golden/` empty |
| `rekey_cache_goldens.py --verify` | clean — EL 170/170, IL 84/84, values unchanged since `c5e2100`, key sets disjoint from the pre-F-89 function |
| `tools/check_encoding.py` | 200 paths, no BOM, no mojibake |
| `tools/audit_imports.py plugins` | clean, every file |
| `tools/audit_decorators.py plugins metascreener` | clean, every file |
| Golden re-capture | **cancelled**, as instructed — and not needed: nothing moved |

The goldens not moving is the load-bearing verification for this wave, not a
formality. The application level resolves `provider = ""`, which `key_required`
calls keyed, so exclusion stays permitted on every replay and each of the nine
fixtures keeps its meaning.

## 9. Commits

| Hash | Subject |
|---|---|
| `ef5b0e3` | `feat(F-145)`: an LLM verdict may flag a record, and may not remove it |
| `e460a64` | `fix(F-146)`: delete the SDK interface that no longer exists, and stop hiding the real error |
| `0868379` | `fix(F-147)`: guard the dialog's worker callbacks, and let the smoke test see dialogs |
| `be711d0` | `feat(F-149)`: let the user ask the provider again, without relaunching |
| `a6ba567` | `docs(F-148)`: correct the call-site inventory that contradicted its own prose |
| `be2fadc` | `feat(F-150, F-151)`: report the compute mode, and say what a run costs before starting it |
| `bbf423a` | `fix(F-152, F-153)`: close INV-1's fifth route, and repair what this wave's review found |

## 10. Register

Nine rows opened and closed: **F-145** (Critical, correctness), **F-146** (High,
correctness), **F-147** (Medium, correctness), **F-148** (Medium,
process/documentation), **F-149** (Medium, correctness), **F-150** (Medium,
reporting), **F-151** (Medium, correctness/reporting), **F-152** (Critical,
correctness/cost), **F-153** (High, correctness).

Two of the nine — F-152 and F-153 — exist because the review executed instead of
reading, and F-153 is entirely this wave's own damage. That ratio is the argument
for the instruction that produced it.

Out of scope, untouched, as instructed: the golden re-capture (cancelled), F-135,
and every documentation change except the two claims a code fix falsified —
`README.md`'s evidence-gating paragraph and `docs/llm-evaluation.md`'s
*"a degenerate run cannot silently exclude records"*, which the measurement in §1
disproves directly.
