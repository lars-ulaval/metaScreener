<!-- SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo -->
<!-- SPDX-License-Identifier: MIT -->

# Fix wave 15b — the context-budget guard

*Design notes for the adjudicated ten decisions. Three points needed
reinterpretation; each is argued here before the code exists.*

**Measured facts this design rests on** (Step 1/1b, twelve declared probe calls):
the serving window is **4,096**; overflow does not trim the excess — it keeps the
**last ~2,048 tokens** and drops the front, instructions and criterion included;
no per-request `num_ctx` vehicle works on `/v1` (both `extra_body` forms
effect-tested: silently dropped); real tokenizer density is 4.48–4.50 chars/token
on batch-1/5 payloads and 4.88–5.23 on batch-10; the longest batch-10 prompt is
3,537 real tokens, so **no frozen run ever overflowed at the prompt level**; the
model's architectural ceiling is 32,768 (Q4_K_M quantization, no Modelfile
override).

## R1 — how a refusal surfaces (reinterpretation of decision 1)

The adjudication fixes *that* the run refuses pre-run; it does not fix the
mechanism. Three candidates, two rejected:

- **`NOT_SCREENED` rows — rejected.** Those rows mean *"passed through
  unexamined"* and trip F-34's export gate with the text *"had no enabled
  criteria"* — a wrong diagnosis shown at the wrong moment. A refusal produces
  no rows at all.
- **`cancelled` — rejected.** The label says *"Cancelled — partial run"*; nothing
  was run and nobody cancelled.
- **A dedicated exception, `ContextBudgetExceeded`, raised by the engines before
  the criterion loop — chosen.** The Views already wrap the engine call in
  `except Exception → messagebox.showerror("EL run failed", …)`, so the F-173
  message reaches the user through wiring that exists, zero calls are spent, no
  export enables (`full_rows` stays empty), and the message is composed in
  `plugins/_common/llm_client.py` where the suite can read it. The View is not
  edited; its rendering of the message gets a numbered HO per HO-2's precedent.

The guard's *logic* lands once, in `plugins/_common/llm_client.py`
(`estimate_prompt_tokens`, `check_context_budget`, `enforce_context_budget`);
each engine calls it once pre-loop. Both standalone shells call the same engines
**[verified]**, so every path that carries `DEFAULT_BATCH_SIZE = 50` is covered.

## R2 — detection via `/api/show` is deliberately not built (decision 4's option)

Argued against F-107 rather than assumed: a provider-specific metadata call in
the run path narrows the set of servers the tool can talk to, for a value the
user can set in one line — and the **drift check is already the universal
detector**: it compares the estimator against the server's own
`usage.prompt_tokens` on the first real call of every run, for every provider,
including ones never tested. The setting is mandatory; detection would be a
second, weaker copy of what the drift check does structurally.

## R3 — the provenance block gains `context_window` (F-154's own closure bar)

F-154's fix cell: *"record the window in the provenance block, because a run
that may have been truncated is not fully specified without it."* The
adjudicated decisions do not name this, but the row's closure requires it, and
it is additive: `llm_provenance()` gains the field, both engines pass
`resolve_context_window(stage)`, and `tests/test_provenance.py`'s exact-set pin
is widened with the reason in its docstring. No golden carries a provenance
block, so nothing moves.

## The window setting

`context_window`, an **application-level** key in the settings store (the
endpoint's home, as the adjudication suggested), read by
`llm_client.resolve_context_window(stage)` with default
`CONTEXT_WINDOW_DEFAULT = 4096` and a floor of 512 on the stored value
(anything below is treated as absent — a window of 3 is a typo, not a policy).
`update_settings(context_window=8192)` stores it; no code edit needed to change
it, per decision 4. Not stage-overridable: the window is a property of the
server, and stages share the server unless an endpoint override says otherwise —
the endpoint override case can gain a per-stage window if it is ever needed.

## The estimator

`tokens = ceil(chars / 4.5) + 30` framing, plus `80 × batch` reply reserve —
divisor and reserve per decision 2, near-exact on small payloads and ~10 %
conservative on large ones **in the safe direction for a refusing guard**. The
probe calibration table ships in the constant's docstring. The drift check
aborts the run if the first real call's `usage.prompt_tokens` exceeds the
estimate — the estimator being optimistic for an untested tokenizer is exactly
the one hole the constant cannot close itself.

## Out of scope, named

The harmoniser's one-shot call (a wave-15d consumer of the same helpers);
raising the window server-side (WAIT FOR MAINTAINER: the
`OLLAMA_CONTEXT_LENGTH=8192` restart and its sentinel confirmation, then the
`docs/usage.md` procedure with the 32,768 ceiling and the CPU/RAM trade stated
without a recommendation).

## Handoffs

**HO-1 — does the refusal message actually render in the Views?**

The one link in the refusal chain no test executes. `tests/conftest.py`
replaces `tkinter` and `tkinter.messagebox` with `MagicMock` before any plugin
import, so no `ELView`/`ILView` method — including the worker's
`except Exception` handler — ever runs under the suite (wave 14b's HO-2
established this for the Views generally). Everything up to the dialog *is*
suite-executed: the engines raise `ContextBudgetExceeded` with zero client
calls (`tests/test_context_guard.py::TestTheEnginesRefuse`, both stages), and
the handler that would catch it is read wiring:
`plugins/06_el/ui.py::ELView` wraps the worker in
`except Exception → messagebox.showerror("EL run failed", str(e))` and sets
the status label to `EL failed.`; `plugins/07_il/ui.py` mirrors with
`"IL run failed"`; both standalone shells carry the same handlers. Whether
tkinter renders a five-paragraph `str(e)` legibly in that dialog is the
residue.

*Repro:* open the reference EL bundle (the wave-14d corpus, 147 records,
EC-2/EC-3), leave the window setting untouched (no `context_window` key
stored — the 4096 default applies), set **Batch size to 10** and Trunc chars
to 1500, press Run. No server is needed and no request is sent — the refusal
fires before the first call.

*Expected, verbatim* (regenerated from the committed guard over the frozen
corpus — the same numbers the CHANGELOG's live check produced):

> This run was not started: the largest request it would send does not fit
> the configured 4096-token context window.
>
> Criterion EC-2, batch 3 of 15 at batch size 10, measures an estimated 3923
> prompt tokens plus a 800-token reply reserve — 4723 in total against the
> 4096-token window.
>
> An overflowing request is not trimmed to fit: the server keeps only the
> last half of it and drops the rest, instructions and criterion included,
> then answers about the remainder.
>
> At this window, the largest batch size that fits every request for this
> corpus is 8.
>
> The window is the application-level 'context_window' setting; the server's
> own window must be at least as large.

*Report:* whether a dialog titled **"EL run failed"** appears at all; whether
all five paragraphs are visible and wrapped rather than clipped to one line;
whether the status label reads **"EL failed."**; whether the run controls
return to idle (the `finally` re-enables them); and whether the counts area
stays empty — a refusal produces no rows, so Export must stay disabled. Then
batch size 8, same bundle: the run must start normally.

*Falsifiers:* a dialog titled anything else (the exception took a different
path); a truncated or single-line message (tkinter's default `showerror`
mishandles the length — the message would need re-shaping, not the guard);
any `[EL-LLM]` line in the Log sub-tab before the dialog (a request was sent
— the guard did not fire pre-run, contradicting
`TestTheEnginesRefuse::test_an_oversized_run_never_reaches_the_client`);
Export enabled after the refusal.

*Logs:* the Log sub-tab content, verbatim, whatever it holds — expected
empty of `[EL-LLM]` lines for the refused run.

*Scope note:* the drift-abort dialog (`TokenEstimateDrift`) rides the
identical wiring — same `except Exception`, same title — but cannot be
provoked on demand against the measured server: the estimator is
conservative for qwen2's tokenizer on every measured payload, and the check
aborts only when reality *exceeds* the estimate. Its rendering is attested by
this HO's answer to the extent the wiring is shared, and by nothing else.
