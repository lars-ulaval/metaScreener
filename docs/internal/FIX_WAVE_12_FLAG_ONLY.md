# Fix wave 12 — flag-only, three defects found by using the software,
# and what the measurement actually showed

**Session A (code).** Branch `fix/wave-12-flag-only`, off `main` at `8b5a972`.
**Session B (the measurement).** Branch `docs/wave-12-measurement`, off `main`
at `7a39eda`; see the second half of this document.

This is the last wave. It exists because the maintainer built the software and
ran it, which produced two things no amount of reading would have: a
**measurement** that decides what the LLM stages are allowed to do, and **three
defects** that 1330 green tests were fully compatible with.

---

## 1. The measurement, and what follows from it

Three bundles, produced by the maintainer against two local models — two runs
of `llama3.2:latest` and one of `qwen2.5:7b`. EL stage, 85 records, the same
corpus and the same `EL` criteria as the committed goldens, all three runs
fully attributed by wave 10's provenance block:

| Model | Exclusions | Audit |
|---|---|---|
| `gpt-4o-mini` (the golden) | **1** | audited, correct |
| `llama3.2:latest` (run A) | **40** | not individually audited; **39 kept by the audited baseline** |
| `llama3.2:latest` (run B) | **43** | not individually audited; **42 kept by the audited baseline**; same recorded configuration as run A |
| `qwen2.5:7b` | **4** | all 4 examined individually and wrong, confirmed by the author |

*This table was written from the session-B brief and said "all unjustified"
for the llama runs. **Nobody audited them** — see §B1, which caught it, and
`d5ad13e`, which corrected `docs/llm-evaluation.md` and `README.md`. That
correction did not reach this table, `docs/usage.md` or F-145's register row
until §B8's review pass swept for it; all three are repaired now. The wording
above is what the artefacts support.*

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
pairs in perfect JSON with **zero** rejected *decisions*. It did not fail to
follow the format. It asserted matches that were not there. (Not zero *field*
rejections: 1 in run A and 3 in run B, corrected in §B8 — the two counters are
separate and only `decisions_rejected` is zero.)

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

---

# Session B — publish the measurement

**Branch `docs/wave-12-measurement`**, off `main` at `7a39eda` (session A
merged and tagged `post-wave-12a`). Scope: the measurement write-up, the
context-window finding, two of session A's eight unverified claims, and the
documentation session A's code falsified.

## B1. The brief was wrong five times, and the rule caught all five

The session-B brief supplied figures and instructed that every one be treated
as a hypothesis until re-measured against the artefacts. That rule earned its
place:

| # | The brief said | The artefacts say |
|---|---|---|
| 1 | two local runs | **three** — two `llama3.2:latest`, one `qwen2.5:7b` |
| 2 | 43 exclusions | **40 and 43**, from two runs of one configuration |
| 3 | `llama3.2:3b` | **`llama3.2:latest`** — a *mutable tag* |
| 4 | "quantised at 4 bits" | **not recorded anywhere**; the provenance block has six fields and none is quantisation |
| 5 | all three runs at `trunc_chars 1500` | the **baseline** was captured at **4000**; only the local runs used 1500 |

A sixth was found without prompting and is this session's own: the write-up as
first committed described the 40 and 43 `llama3.2` exclusions as "all
unjustified". **Nobody audited them.** The brief asserted it, and the tell is
that the same brief marked the qwen four as "confirmed by the author" and did
not mark the llama sets. No audit of them exists in this repository. That had
reached the README before it was caught, which is precisely the wave 10 error
the rule exists to prevent — and it was caught by asking the question the
review pass was going to ask, one commit before the review answered.

The replacement is traceable and nearly as strong: **39 of run A's 40 and 42 of
run B's 43 excluded records were kept by the audited baseline**, the single
overlap in each case being `A499`, the one exclusion the author examined and
found correct.

## B2. The context window: settled, and it cuts both ways

`num_ctx` appears **nowhere** in the tree, so every local run inherits the
server's default — 4096 on the maintainer's machine. An OpenAI-compatible
server truncates rather than errors when a prompt exceeds its window, so this
had to be settled before anything was published: if the prompts overflowed,
every causal claim about model comprehension in this wave was confounded.

`tools/measure_prompt_size.py` renders the real prompt through the real
builder. It is validated against the artefacts rather than trusted — it
produces 17 prompts per criterion × 2 criteria = **34**, exactly the
`calls_made: 34` all three bundles record.

**They did not overflow.** Worst batch-5 prompt plus reply is 2,679–4,020
tokens against 4,096, depending on the tokenizer assumption. The truncation
hypothesis is dead and the measurement stands.

**But the recommended range is already unsafe.** At batch 10 — inside
`LOCAL_BATCH_RANGE = (5, 10)`, the range D6's tooltip offers a local user —
seven of nine prompts exceed the window, and `standalone.py:108` seeds its box
from `DEFAULT_BATCH_SIZE = 50` directly, at 4–6× the window. F-154 therefore
**blocks any future increase to the local batch range** and records that the
present upper bound is unsafe. Not fixed, by instruction.

## B3. The finding the wave did not go looking for

Runs A and B are the same model on the same input, **identical in all six
fields the provenance block records**, twenty-three minutes apart. They
excluded 40 and 43 records. The 40 are a strict subset of the 43; three
records moved `PASS_FLAGGED → OUT`; 8 of 170 judgments (4.7%) changed
decision; even `fields_rejected` differs, 1 versus 3.

`temperature = 0` is widely treated as a reproducibility guarantee. It is not
one here, and this is a direct measurement rather than an inference. The
project's own code has said so in a docstring since wave 7; this attaches an
effect size to it.

Three consequences, recorded as **F-155**:

1. a bundle's provenance identifies a run's *configuration*, not its *result*
   — two bundles agreeing in every recorded field can disagree about which
   papers are in the review;
2. the replay goldens pin **recorded** answers, not **reproducible** ones.
   Asked whether `llm-evaluation.md` or `02_quality.md` implied otherwise:
   **they did not** — both already drew the distinction correctly. But both
   argued it from a docstring, so §6.5's LLM-sampling row and its Verdict now
   cite the measurement;
3. it is a **stronger argument for flag-only than accuracy is**, and the
   write-up makes it that way. Not "the model is wrong" but "the same model,
   in the same recorded configuration, excludes a different set of papers each
   time". Removal is the pipeline's one irreversible act.

What it does **not** undermine, stated because it matters: the deterministic
stages reproduced exactly across all three runs — 776 → 125 → 651 → 566 → 85,
the same records every time. The variability is confined to the LLM half.

## B4. Two claims reproduced, both real

Session A left eight unverified claims. Two were examined, with a repro
required before acting. **Both reproduced.**

**F-156 — the criterion drill-down hid suppressed records.** The filter tested
four lists and F-145 had added a fifth, `suppressed`, which by design receives
the criterion *instead of* `failed`. Measured on a four-record flag-only run:
the criteria table reported `EC-1: failed 4`, and clicking `EC-1` showed
**zero** records. Flag-only's entire value is that a human reads the record;
this lost it at the point of reading. Fixed with one predicate over a
vocabulary enumerated once — the enumeration being the fix, since the defect
is precisely a set that grew on the engine side and not the View side.

**F-157 — `compute_mode` could freeze the interface.** `urlopen`'s timeout
bounds each socket operation, not the transfer: **8.02 s against a 2.0 s
timeout** against a server that dribbles its body. `_confirm_run` calls it on
the GUI thread deliberately, so that is a frozen application at the moment the
user presses Run. The first repair did not work, and why is the instructive
part: `read(8192)` blocks until it has 8192 bytes, so it swallowed the whole
slow transfer in one call and the deadline was checked once. `read1` fixes it.
**8.02 s → 2.42 s.**

Two for two is a reason to take the remaining six seriously, not a reason to
assume them. They stay tabulated and unactioned.

## B5. Documentation, and one thing the sweep exposed

Corrected: `usage.md`'s "require an OpenAI API key in `.env`" (two waves
false); its description of the evidence gate as *the* condition for exclusion;
the per-criterion status vocabulary, which gained `SUPPRESSED`; IL's summary,
with the polarity spelled out because it is easy to reverse;
`installation.md`'s local smoke test, which will now show **zero** records
marked `OUT` and would otherwise be filed as a bug; and its provenance list,
which gains `exclusion_policy` and — more usefully — **what is not recorded**.

**F-158** was false before this wave and exposed by it. `usage.md` claimed the
harmoniser's LLM refinement "is annotated with the original and refined
assignments so the researcher can audit any changes". It is not:
`_harmonise_llm` does `self.state.rows = refined`, replacing the table
wholesale. Nobody could notice, because until F-146 the pass could not run at
all. Session A's repair turns a dormant documentation error into a live one. A
criteria table decides which papers a review considers; a pass that rewrites it
without a diff is not auditable. Documentation corrected; the code fix opens a
row, per the brief's rule.

## B6. What a maintainer picking this up in six months most needs to know

Four things, none of them currently written down anywhere else.

**1. The published measurement depended on three files that were not in this
repository — this is now closed (F-159), and the closing is §B7.** As
published, `docs/llm-evaluation.md` § *Local models on this corpus* derived
from three bundles in `_archive_bundles/`, a sibling directory of the repo
outside version control:

    20260811_174726_post_EL_bundle.zip    run A, llama3.2:latest, 40 OUT
    20260811_181009_post_EL_bundle.zip    run B, llama3.2:latest, 43 OUT
    20260811_184118_post_EL_bundle.zip    run C, qwen2.5:7b,       4 OUT

Every figure in that section traced to one machine, and nothing in the
repository said where those files were. The evidence is now frozen under
`docs/data/wave12_local_runs/` and every published figure is recomputed from
it on each suite run. **What remains worth doing:** archive the three original
zips somewhere durable anyway — their digests are recorded in
`wave12_local_runs.meta.txt`, so a resurfaced bundle can still be matched
member by member against what was kept.

**2. This codebase's characteristic defect is a vocabulary that grows on one
side only.** F-145 added an outcome; F-153 and F-156 are the two places that
outcome failed to reach. F-109 records that the per-criterion status vocabulary
has no constant at all, and F-69 records that this project has shipped the
same shape four times. So: **when you add a member to any enumerated set, grep
for every place the set is spelled out**, because there are many and almost
nothing checks them against each other. `stage_state.CRITERION_ROW_LISTS` is
the pattern to copy — name the set once, in the module both sides import.

**3. A green CI is compatible with a broken GUI, and always has been.**
`tests/conftest.py` replaces `tkinter` with a `MagicMock`, so Views and dialogs
cannot be constructed under the normal suite. `tests/test_view_smoke.py` is the
only real-Tk cover and it **skips without a display**, which most CI cells are.
Three live GUI defects shipped past a green suite in two waves. If you change a
View or a dialog, run the smoke locally; nothing else will tell you.

**4. INV-1 has now broken five times, and never once in a way a reader
noticed.** A keyless provider reaching the paid vendor has been closed by a
default, a blank field, a per-stage override, an ASCII trailing dot and — in
F-152 — a Unicode full stop. Every closure was of a *spelling*. The tests that
found the last two were written to attack the invariant rather than to confirm
it. Keep doing that, and keep
`tests/test_review_repairs.py::TestEveryFullStopDnsHonoursIsTheSameHost`'s
habit of asserting the *premise* (that IDNA really folds those code points)
rather than only the conclusion.

## B7. The evidence, committed — F-159

§B6's first item was published as the highest-value follow-up in this
document. It is closed here, and the work turned up two things the
measurement itself had missed, which is the argument for doing it rather
than filing it.

**The defect.** § *Local models on this corpus* published exclusion counts,
per-judgment distributions, quote-validity fractions and a named-record
comparison, all of it derived from three bundle zips in `_archive_bundles/` —
a sibling directory of the repository, outside version control. A reader could
not check one figure against anything committed. That is F-98's defect on a
different artefact: **a published document depending on evidence nothing
protects.** The overnight restart is the argument for why "they are on the
disk" was not an answer.

**Reduced, not dumped: 4.16 MB → 0.78 MB.** Committing the three zips as-is
would have triplicated 3.8 MB of byte-identical deterministic output and
re-committed a corpus the repository already ships. Hash-only would have
failed the requirement that matters — a digest of a file you do not have lets
you confirm you have the same file, not check a figure. So the set was reduced
to what no committed file already carried, and **every omission is asserted
rather than assumed**:

| Omitted | Why it is safe |
|---|---|
| `EH_FULL`, `EH_SURVIVORS`, `IH_FULL`, `IH_SURVIVORS` | byte-identical across all three bundles — that identity **is** the "deterministic stages reproduce exactly" claim, and a digest proves it as well as a copy |
| `IH_SURVIVORS` again | byte-identical to the already-frozen `docs/data/study_input/el_input_v3.1.0.csv`, so **EL's input was in the repository all along** |
| `data/original.csv` | byte-identical to `samples/20260122_1654_aggregate.csv` |
| run A's criteria table | byte-identical to `docs/data/study_input/criteria_harmonized_v3.1.0.csv` |
| `current.csv`, `EL_SURVIVORS` | EL_FULL's non-OUT rows, minus the seven `el_*` columns |

What is committed: three manifests, three `EL_FULL.csv`, three
`EL_cache.jsonl`, the criteria variant B and C used. **The caches are
committed rather than dropped as derivable because they are the only source of
`valid_quote`** — `EL_FULL.csv`'s evidence JSON does not carry that field, and
the document's `81/170`, `80/170` and `117/170` cannot be checked without them.
That was found by trying to derive them and failing, not by inspection.

**The artefacts self-authenticate.** Every committed file is matched against
the digest recorded for it inside its own run's `manifest.json` — which is
itself committed, and which also carries digests for the members left out. So
the reduction loses nothing recoverable: a resurfaced bundle can be matched
member by member. The three zips' own digests are in the meta sidecar.

`tests/test_wave12_measurement_freeze.py`, 43 tests, and — following
`test_study_input_freeze.py` — **not one of them a hand-maintained list**:
coverage read off the directory and `SHA256SUMS` in both directions;
self-authentication mapped by basename; the anchoring equalities above; and
*fidelity*, which is the one that matters — **every published figure is
recomputed from the frozen bytes and the document is required to state it.**
The artefacts are the source of truth; the prose has to agree with them. Edit
a number in the document and it fails.

### What the freeze exposed

**1. `4.7%` understates the run-to-run variation by 4.6×.** It counts only the
verdict. Comparing every judgment on the evidence the model actually supplied —
decision, confidence, cited field, quoted span, gate status — **37 of 170
(21.8%) differ in at least one**: confidence on 23, the quotation on 22, the
cited field on 13. Roughly one judgment in five is not the same judgment twice.

**2. `A570` moved from flagged to excluded with both decisions unchanged.** Of
the three records that moved between runs A and B, it is the one no verdict
comparison can explain: `meet` on EC-2 in both runs, confidence 1.0 and 0.95.
In run A the model cited the abstract and supplied **no quotation**, so the
evidence gate had nothing to verify and a human got the record; in run B it
cited the keywords and supplied `"Virtual reality"`, present verbatim, so the
gate passed and the record left the review. **Whatever varies in the quotation
varies in the outcome, independently of whether the model changed its mind.**
This sharpens the section's central finding rather than contradicting it: the
gate is the mechanism that converts a verdict into an action, and it is the
half that was varying.

**3. A difference between runs A and B that no artefact records.** They ran
against criteria tables differing in `IC-5` — an `IL` row the EL stage does not
read. `EC-2` and `EC-3` are byte-identical across all three runs, asserted
field by field, so the comparison stands. It is recorded prominently anyway,
because it is F-155's own point made concrete: the provenance block records six
fields, the criteria table is not one of them, and **something did differ
between runs A and B that neither run's artefacts would have told you.**

### The trap that was avoided

`.gitattributes` exempts the directory from `* text=auto`. The `EL_FULL.csv`
files carry CRLF row terminators with bare LFs inside quoted abstracts — the
exact mixed content that gets normalised — so without the rule a fresh clone
rewrites them and **every digest in the directory breaks at once**, looking
like tampering rather than like checkout. F-128's trap, one directory over, and
`test_study_input_freeze.py`'s comment is what flagged it in advance.
Verified after staging: the index blobs are byte-identical to the working tree
for all twelve files.

## B8. The review pass

**It did not run when it was supposed to, and nothing recorded that.**

Session B ended on 2026-08-11 with `ff23b40`. A review pass was scoped and
was never recorded as having run: there is no review section, no findings it
produced, and no statement that it produced none. The only trace anywhere in
the repository is `d5ad13e`'s message — *"found by asking the question the
review pass was told to ask, before the review answered"* — and §B1 repeating
it. That sentence describes a review that had not yet answered, and the
document then went to press as though it had. **An unrecorded review is worse
than an absent one**, because a reader cannot tell the two apart, and session
A set the precedent of reporting what its agents did and did not do rather
than counting unverified as refuted.

So it was run on **2026-08-12**, over the six session-B commits, as five
independent dimensions with every finding then handed to an adversarial
verifier instructed to refute it by execution and to default to *refuted*
when it could not.

| | |
|---|---|
| Raised | 24 |
| **Confirmed** | **21** |
| Refuted | 3 |

The three refuted are recorded because refuting them cost as much as
confirming the others: a claim that the stage sheet has no cell able to name
a suppressed criterion (it does — `el_evidence_json` and `el_reason_summary`
both carry it); a claim that `CRITERION_ROW_LISTS` omits the deterministic
engine's own lists (it does not, and the omission is a decision written at
the point the vocabulary was extended); and a claim that
`measure_prompt_size.py`'s under-estimate runs in the unsafe direction, which
direct measurement with the real tokenizer falsified.

### What the 21 were, and what happened to each

**Nine were false claims in documentation, and are fixed here** — session B's
scope is documentation, so these are Part 4 work the sweep missed:

1. **`d5ad13e`'s retraction reached two files and stopped.** It corrected
   `README.md` and `docs/llm-evaluation.md`; **nine other sites went on
   publishing "all unjustified"** — including `docs/usage.md`, F-145's own
   register row, this document's §1 table (contradicting §B1 eleven hundred
   lines below it), and, worst, **the shipped label in
   `metascreener/provider_dialog.py`**, which told every user about to change
   a safety setting that all 83 exclusions were unjustified when nobody had
   audited them. A smoke test asserted the word was present. All nine are
   corrected and the smoke test now asserts the word is **absent**.
2. **"zero vocabulary rejections" was false**, and this document and
   `llm-evaluation.md` each contradicted it with their own `fields_rejected`
   1 vs 3 a few dozen lines later. The pipeline keeps two rejection counters
   and only `decisions_rejected` is zero. Corrected in four places; the claim
   the argument actually needs — well-formed JSON and a legal verdict on all
   170 — survives intact.
3. **The reply figure `509–764` was not re-derivable from anything**, which
   is precisely the failure `tools/measure_prompt_size.py` was written to
   prevent. Now that F-159 has committed the evidence it *is* derivable, and
   it was an overstatement: the worst reply is **1,471 characters = 327–491
   tokens**, so the worst total is **2,497–3,747** against 4,096, not
   2,679–4,020. The verdict is unchanged and the margin is wider.
4. **The flag-only cost paragraph mixed two runs inside one sentence** —
   the manuscript run's 703 as denominator, the goldens' 5 as numerator,
   giving 691 + 5 = 696 ≠ 703. Both ratios circulate in this repository
   (99.3% goldens, 98.3% manuscript) and that paragraph was what made them
   indistinguishable. Now stated as two separate measurements.
5. **Run C's `117/170` and its `uncertain` column mean something different
   from the rows above them**: 33 unanswered judgments are back-filled as
   uncertain with an invalid quote and are absent from the cache entirely.
   Among answered judgments the rate is **117/137 = 85.4%**. Both cautions
   are now printed under the table.
6. **`usage.md`'s per-criterion status list omitted `MISSING`** — the
   rewrite in `0d7de0a` added the member the vocabulary had just gained and
   carried a pre-existing gap forward. Five statuses, not four. The gloss on
   `UNCERTAIN` was also wrong for non-LLM criteria.
7. **`usage.md` claimed a stored provider choice overrides `OPENAI_API_KEY`.**
   It overrides `OPENAI_BASE_URL`; the key is still handed to the SDK
   whatever endpoint is resolved. Corrected, and opened as **F-160**.
8. **"All but one local exclusion per run"** is right for runs A and B and
   wrong for run C, where all four were baseline-kept.
9. **§1's lead-in still said "two bundles"** over a table of three, which
   §B1 records as one of the five brief errors this session caught.

**Four are code defects and stay open, per the brief's own rule** that a fix
requiring code opens a row rather than being attempted in a documentation
session:

- **F-160** (High) — the vendor key reaches a keyless provider's endpoint.
  INV-1's mirror image.
- **F-161** (Medium) — **F-156 closed too early.** Six drill-downs exist, not
  four; the two standalone ones still show 0 of 4 suppressed records. The
  guard test compares two copies of the same literal and never reads the
  engine, so a sixth list was simulated engine-side and the suite stayed
  green at 117 passed while the drill-down went 4/4 → 0/4. And none of the
  five new tests executes `_refresh_reports_view` at all.
- **F-162** (High) — **F-157 closed too early.** The fix bounds the body and
  the header phase is still unbounded, because `_read_bounded` runs inside
  the `with urlopen(...)` block. Measured through a real Tk mainloop:
  **20.75 s frozen, no events processed.** Both stages, not one. The wave's
  own regression test cannot see it because `end_headers()` emits the
  headers in a single write.
- **F-163** (Medium) — `measure_prompt_size.py` selects criteria on stage
  alone where the engine also requires `enabled` and `operator == "llm"`.
  EL is unaffected, which is why the `calls_made: 34` cross-check passed;
  IL reports double.

### What this cost, and what it says

Two of the four open rows say a wave-12 row closed too early. That is the
same ratio session A reported — F-153 was entirely its own wave's damage —
and it is the argument for the instruction that produces it: **the review
executes rather than reads.** F-162 in particular was found by scripting a
server that dribbles header bytes, which no amount of reading the diff would
have suggested, and it sits on the code path F-157's own row calls "the most
visible failure this wave could have shipped".

The nine documentation defects share one cause and it is this project's
named one: **a correction that grows on one side only.** `d5ad13e` retracted
a claim in two files and left it standing in nine, exactly as F-145 added an
outcome that failed to reach two places. §B6.2 tells a maintainer to grep
every spelling of an enumerated set when they add a member. The same rule
applies to retractions, and this session did not follow it until the review
made it grep.

## B9. Verification

| Check | Result |
|---|---|
| Suite at `main` (session A close) | 1534 passed, 7 skipped |
| Suite at `ff23b40` (session B, first close) | 1545 passed, 7 skipped |
| **Suite now** | **1588 passed, 7 skipped** |
| — the difference | +43, exactly `tests/test_wave12_measurement_freeze.py` |
| GUI smoke, run explicitly | **23 passed** — a display was available, so the `provider_dialog` label change is actually covered rather than skipped |
| Goldens, both ways | **9/9 SHA-256 identical to `main`**; `git diff main..HEAD -- tests/golden/` and the reverse both empty |
| `rekey_cache_goldens.py --verify` | clean — EL 170/170, IL 84/84, values unchanged since `c5e2100`, key sets disjoint from the pre-F-89 function |
| `tools/check_encoding.py` | 218 paths, no BOM, no mojibake |
| `tools/audit_imports.py plugins` | clean, 42 files |
| `tools/audit_decorators.py plugins metascreener` | clean, 58 files |
| Frozen evidence, index vs working tree | **byte-identical for all 12 files** — the `.gitattributes` rule holds |
| Frozen evidence, self-authentication | every artefact matches the digest inside its own run's manifest |

**The goldens not moving is again the load-bearing check.** This session
committed evidence *derived from* runs that used a different criteria table
and a different model, and none of it touches the replay path. Nine
byte-identical fixtures is the proof.

**One check this session added that did not exist before:** the published
figures are no longer verified by reading. `tests/test_wave12_measurement_freeze.py`
recomputes each of them from the frozen bytes and requires the document to
state the result, so `docs/llm-evaluation.md` cannot drift from its evidence
without a red suite.

## B10. Commits

| Hash | Subject |
|---|---|
| `ec81d58` | `docs(F-154)`: num_ctx is never set, and the recommended batch range already exceeds it |
| `e6cb53c` | `docs(F-155)`: publish the local-model measurement, and the non-determinism inside it |
| `f879670` | `fix(F-156, F-157)`: both reproduced claims were real |
| `0d7de0a` | `docs(F-158)`: correct what session A's code falsified, and one thing it exposed |
| `d5ad13e` | `docs`: say what was audited, not what was asserted |
| `ff23b40` | `docs`: record wave 12 session B, and what a maintainer needs in six months |
| `6e0bf7b` | `fix(F-159)`: commit the evidence the published measurement rests on |
| `118873e` | `fix`: repair what the review pass found, and open what it could not |

The last two are this close-out. `6e0bf7b` is §B7, `118873e` is §B8.

**A convention note, because it will confuse someone otherwise.** Rows
F-152 through F-163 say **"Fixed in `PENDING`"**. That is the wave's own
convention — the hash is written back when the wave merges, as `c5e2100` and
`b01ec25` were for wave 9 — and it is deliberately *not* resolved here, so
that all twelve rows resolve together rather than three of them carrying
hashes and nine carrying a placeholder. Whoever merges this branch resolves
them.

## B11. Register

**Five rows opened, one closed.**

| Row | Severity | State |
|---|---|---|
| **F-159** | High | **closed** — the published measurement's evidence, committed and re-derived on every suite run |
| **F-160** | High | open — a vendor key in the environment reaches a keyless provider's endpoint |
| **F-161** | Medium | open — F-156's closure overclaimed: six drill-downs, not four; the guard test never reads the engine |
| **F-162** | High | open — F-157's closure overclaimed: the header phase is still unbounded, 20.75 s of frozen GUI measured |
| **F-163** | Medium | open — `measure_prompt_size.py` selects criteria the engine would not call |

**F-155 was extended, not merely cross-referenced:** the freeze produced a
figure the original measurement did not have (**37 of 170, 21.8%**, against
the published 4.7%) and an instance the original could not explain (**A570**,
which moved from flagged to excluded with both decisions unchanged). **F-145
was corrected** where it repeated the retracted "all unjustified".

**Totals regenerated**, and the previous snapshot was stale: it read
`141 / 69 / 72`, computed at wave 10 close and carried unchanged through
wave 11 and wave 12 session A while nineteen rows were added. That is F-131
happening in the one place F-131 is about. The register now runs **F-01..F-163
with the permanent F-56/F-57/F-58 gap — 160 rows, 81 closed, 79 open.**

**Out of scope and untouched, as instructed:** the golden re-capture
(cancelled in session A), F-135, and the four code fixes opened above. No
merge, no tag, no push.

## B12. Session B is complete

Everything session B was asked for is done and verified:

- **F-154** opened — `num_ctx` is never set and the recommended local batch
  range already exceeds the window; `tools/measure_prompt_size.py` committed.
- **Part 2**, the measurement, published in `docs/llm-evaluation.md`
  § *Local models on this corpus: a direct measurement*, self-corrected once
  in `d5ad13e` and corrected again by the review in `118873e`.
- **Part 3**, two of session A's eight unverified claims reproduced by
  execution and fixed — F-156 and F-157. **Both closures were later found to
  be partial** (F-161, F-162); the reproductions themselves stand.
- **Part 4**, the documentation sweep — F-158 opened, `usage.md` and
  `installation.md` corrected, with nine further false claims found and fixed
  by the review pass.
- **The review pass**, run and recorded in §B8 rather than left as an absence.
- **The evidence**, committed in §B7 — the follow-up §B6 called the
  highest-value one in this document.

**The six remaining unverified claims from session A stay tabulated and
unactioned**, as §B4 says. Four new rows are open. Nothing here is merged,
tagged or pushed; the branch is `docs/wave-12-measurement` and it is ready
for the maintainer to take.
