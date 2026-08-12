<!-- SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo -->
<!-- SPDX-License-Identifier: MIT -->

# 08 — Why "Harmonise + LLM" failed on eight criteria

*Read-only diagnostic of one reported failure, reproduced. Nothing was fixed.*

**Repository state:** `diag/harmoniser-llm-failure` off `main` @ `cdffa53`
(tag `post-wave-13c`), `origin/main` in sync (0 ahead, 0 behind).
**Date:** 2026-08-12. **Mode:** read-only. No source, test, golden, sample, register
row or user-facing document was modified. This file is the only one added.
**Test baseline:** 1602 → **1714 passed, 7 skipped** — before and after.
**Golden listing aggregate:** `9b7fe3e2`.

**Gate exception, reported rather than waved through.** `git status --porcelain` was
**not** empty at session start. One untracked file:

```
?? "samples/ic_ec_12 - Copie.txt"        171 bytes, mtime 2026-08-12 19:08
```

It contains IC-1 and EC-1 only. That is the maintainer's own two-criterion file from
the controlled comparison described in the brief, written three minutes after the
19:05 failure. It is evidence, it is his, and `samples/` is outside this session's
fence — **it was read and left exactly where it was.** It is still untracked at
wrap-up and that is deliberate.

## Network disclosure — read this first

**I called the local Ollama server. Eight requests in total: two metadata, six
inference.** The brief authorises up to six inference calls for §8a and I used exactly
six; no seventh was made.

- **2 metadata**, no inference: `GET /api/tags` and `POST /api/show` for
  `llama3.2:latest`.
- **6 inference**, all `POST /v1/chat/completions` against
  `http://localhost:11434`, all replaying a prompt reconstructed from repository code:
  n=8 once, n=2 once, n=6 once, n=4 three times.
- **No paid vendor API was contacted. No API key was used** — the only credential in
  play was the literal string `placeholder-not-a-real-key`. No EL or IL screening was
  run. No model was pulled. The daemon was already running; I did not start it.

## Evidence conventions

As `07_criteria_parsing.md`. Claims are anchored on `path::symbol`; **line numbers are
absent entirely**. Markers: **[measured]** = executed in this session, command and
output shown; **[read]** = derived from source without executing; **[not established]**
= followed by what would settle it. Harnesses live in `%TEMP%` (`hlf_measure.py`,
`hlf_reply.py`, `hlf_replay.py`); none was written into the repository tree.

---

## Executive summary

**The failure is not what it looks like, and it is not what the brief's revised
hypothesis says it is.** Five facts, three of which correct the framing I was given.

1. **The reply was not truncated, and nothing overflowed a context window.**
   **[measured]** replaying the reconstructed 8-criterion prompt against
   `llama3.2:latest` reproduces the failure and returns `finish_reason: 'stop'` with
   `usage: {prompt_tokens: 1384, completion_tokens: 896, total_tokens: 2280}`. The
   model finished of its own accord, having used 2,280 tokens. Nothing was cut off.

2. **The reply is complete and malformed: it is missing exactly one closing brace.**
   **[measured]** the raw reply is 3,280 characters, brace balance `{` = 10 against
   `}` = 9, and appending a single `}` makes it parse. The model closed the row array
   with `]` and never closed the outer object.

3. **It also invented a ninth row.** **[measured]** the repaired reply parses to **9**
   rows for 8 inputs — the eight correct ones plus a duplicate `IC-5` with its `type`
   flipped from `include` to `exclude` and its stage moved from `IL` to `EH`. Had the
   brace been present, the run would still have failed, at
   `_llm_refine`'s *"LLM changed row count (expected 8, got 9)"* — a different guard
   with a different message.

4. **The degradation is not monotonic, so "find the threshold" has no clean answer.**
   **[measured]** n=2 and n=4 succeed; n=6 fails *worse* than n=8. At six criteria the
   model went into a **repetition loop**, emitting **38 row objects for 6 inputs**,
   13,039 characters and 3,575 completion tokens over 40.4 seconds, cycling
   `IC-3 IC-4 IC-5 EC-1 EC-2` six times over before stopping mid-object.

5. **This path sends everything in one call and has no batching, chunking, retry,
   adaptive split or bound of any kind.** **[measured]** `llm_refine.py` contains zero
   occurrences of `batch`, `chunk`, `retry` or `split`; `plugins/_common/llm_client.py`,
   which EL and IL use, mentions `batch` 86 times. **That is the finding.** It is a
   design gap, not a tuning problem, and no `num_ctx` setting fixes it.

**The one-line answer to the brief's question.** Eight criteria did not overflow
anything; a 3-billion-parameter model was asked to emit one 2,142-character JSON object
in a single shot with no retry, and it produced a *nearly* correct one — and "nearly"
is fatal to `json.loads`.

---

## §1 The guard, and what it actually tests

The message comes from `plugins/03_harmoniser/llm_refine.py::_call_openai_json`, at the
only raise site in that function:

```python
parsed = _parse_llm_json_object(txt)
if parsed is None:
    raise RuntimeError(
        f"The model did not return a JSON object. First 200 characters "
        f"of the reply: {txt[:200]!r}"
    )
```

**[read]** `plugins/_common/llm_client.py::_parse_llm_json_object` does three things
and returns `None` only if all three fail:

1. `_strip_code_fence(text)` — removes a leading ```` ``` ```` fence and its closing
   partner. **So a fenced reply cannot cause this failure.**
2. `json.loads` on the whole stripped string; returns it if it is a `dict`.
3. `re.search(r"\{.*\}", t, flags=re.S)` — **greedy**, from the first `{` to the
   **last** `}` — then `json.loads` on that span.

Step 3 is the important one and it is more tolerant than the brief assumes. Because the
match is greedy and dot-matches-newline, **leading prose, trailing prose, and a
trailing explanation after the object are all tolerated**: the span simply starts at
the first brace and ends at the last one.

**So what can actually make a reply carrying valid JSON fail this guard?** Only a reply
in which the span from the first `{` to the last `}` is *itself* not valid JSON. Three
shapes do that:

- **a missing closing brace** — the last `}` belongs to an inner object, so the span is
  an unterminated outer object. **This is the observed failure.**
- **a truncated reply** — same effect, arrived at differently.
- **two complete objects** — the greedy span covers `{…}{…}`, which is not valid JSON.
  Not observed here.

And one shape that is *not* a cause, contrary to the natural reading: a model that
wrapped a perfectly good object in prose. That case is handled.

## §2 What the error throws away

At the moment it raises, the function holds `resp` — the full response object — and
`txt`, the full reply. The message uses **200 characters of `txt` and nothing else**.

Discarded, all of it available and all of it decisive:

| available | value in the reproduced run | what it would have told the user |
| --- | --- | --- |
| `finish_reason` | `'stop'` | the reply was **not** cut off — kills the truncation reading outright |
| `usage.prompt_tokens` | 1384 | the input is small |
| `usage.completion_tokens` | 896 | the output is small |
| `usage.total_tokens` | 2280 | nothing is near any window |
| `len(txt)` | 3280 | the 200 shown are 6% of what arrived |
| the parse failure | `Expecting ',' delimiter: line 1 column 3281` | **the exact character where it broke** |

The last row is the sharpest: `_parse_llm_json_object` catches every exception
internally and returns `None`, so the `json.JSONDecodeError` — which names the
offending column — is destroyed inside the parser and cannot be recovered by the
caller even in principle.

**Is this the wave-8 defect?** Not literally — that was eleven distinct failure states
collapsing onto one message. This is one message that cannot distinguish **truncation**
from **malformation** from **refusal** from **a repetition loop**, which is the same
*shape* one function over. And it is not hypothetical here: **the 200-character window
is what made the first reader of this incident conclude the reply had been truncated.**
It had not. A failure message that misleads the person diagnosing the failure is doing
worse than saying nothing.

## §3 Length limits

**`max_tokens` is not set.** **[read]** `_call_openai_json` passes exactly `model`,
`messages`, `temperature=0` and `timeout` to `client.chat.completions.create`. This is
the live half of **F-25**.

**`num_ctx` is set nowhere in the shipped tree.** **[measured]** grepping
`plugins/`, `metascreener/` and `tools/` for `num_ctx`, `max_tokens`, `num_predict` and
`options=` returns two hits, both inside `tools/measure_prompt_size.py`'s docstring,
which is F-154's own subject. This confirms F-154.

**`llama3.2:latest` declares no `num_ctx` either.** **[measured]** `/api/show` returns
`parameters` containing only three `stop` tokens, and `model_info` reports
`llama.context_length = 131072`. So the effective window is whatever the Ollama runtime
defaults to.

**F-154's 4096 does not hold on this machine, and that is a correction.** **[measured]**
the n=6 replay completed with `total_tokens: 4716` and `finish_reason: 'stop'`. A run
that generates past 4,096 tokens and then stops *naturally* cannot have been bounded at
4,096. **[not established]** what the effective value is — settling it needs
`OLLAMA_CONTEXT_LENGTH` from the daemon's environment or a deliberate overflow probe,
and neither was necessary once the window was ruled out as the cause.

**The 8000-character truncation did not fire.** **[measured]** `samples/ic_ec_12.txt` is
**611 characters**, so `full_criteria_text[:8000]` in `_llm_refine` is a no-op here.
HO-13-4 stands as an open question for a real corpus and is untouched by this incident.

**The arithmetic, computed before any call was made**, using F-154's own bounds
(4.5 and 3.0 characters per token; `tiktoken` is not importable in this environment, so
these are bounds and not counts):

| n | prompt chars | prompt tok (est) | expected reply chars | reply tok (est) | sum (est) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2 | 2,440 | 542–813 | 566 | 125–188 | 667–1,001 |
| 4 | 3,218 | 715–1,072 | 1,044 | 232–348 | 947–1,420 |
| 6 | 4,155 | 923–1,385 | 1,613 | 358–537 | 1,281–1,922 |
| 8 | 5,044 | 1,120–1,681 | 2,142 | 476–714 | 1,596–2,395 |

**Every row fits 4,096, pessimistically, with room to spare.** The estimate was good:
the measured n=8 prompt is 1,384 tokens against an estimated 1,120–1,681.

## §4 The reconstruction, and what it settled before any call

**[measured]** the prompt was rebuilt by driving the real
`parser.py::_parse_free_text_criteria` → `inference.py::_infer_criterion_details` over
`samples/ic_ec_12.txt` against `samples/20260122_1654_aggregate.csv`, then calling the
real `_llm_refine` with `_call_openai_json` replaced by a capturing stub — so the system
and user strings are the ones the application builds, not an approximation.

**The reconstruction is certified by the log itself.** A faithful reply to that prompt
begins:

```
{"rows": [{"id": "IC-1", "type": "include", "stage": "IL", "label": "The paper considers
immersive virtual reality OR a virtual simulation using a head-mounted display (HMD).",
"operator": "llm", "tar
```

which is **character-for-character the 200-character fragment in the maintainer's log**,
ending at `"tar` in the same place. The model was producing exactly the demanded schema.

Candidate shapes, against all the evidence:

| shape | consistent? | why |
| --- | --- | --- |
| markdown fence | **no** | `_strip_code_fence` removes it |
| leading prose | **no** | the greedy span starts at the first `{` |
| trailing prose | **no** | the greedy span ends at the last `}` |
| two objects | possible in principle | not observed; would need the model to answer twice |
| genuinely truncated reply | **not at n=8** | `finish_reason: 'stop'`, 2,280 tokens |
| **complete but missing one brace** | **yes — observed** | brace balance 10 vs 9 |

The arithmetic in §3 said the window was not the constraint; the shapes above said the
tolerant parser could only be defeated by an unbalanced object. What neither could
settle was **which** unbalanced shape, and whether the model had also corrupted the
content. That is what the replay was for.

## §5 The replay — six inference calls, and what they showed

**[measured]**, all against `llama3.2:latest`, `temperature=0`, **no `max_tokens`** —
i.e. exactly what `_call_openai_json` sends.

| n | prompt tok | completion tok | total | reply chars | elapsed | row objects | parses? |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2 | 678 | 203 | 881 | 755 | 4.5 s | 2 | **yes** |
| 4 | 900 | 391 | 1,291 | 1,400 | 6.4 s | 4 | **yes** |
| 4 (repeat) | 900 | 391 | 1,291 | 1,400 | 6.4 s | 4 | **yes** |
| 4 (repeat) | 900 | 391 | 1,291 | 1,400 | 6.3 s | 4 | **yes** |
| 6 | 1,141 | **3,575** | **4,716** | **13,039** | **40.4 s** | **38** | **no** |
| 8 | 1,384 | 896 | 2,280 | 3,280 | 13.8 s | 9 | **no** |

The n=8 row reproduces the maintainer's incident: 13.8 seconds against his 15, the same
guard, the same message.

**n=8's failure**: eight correct rows, then a hallucinated ninth — `IC-5` repeated with
`type` flipped to `exclude` and `stage` to `EH` — then `]` with no closing `}`.

**n=6's failure is different and worse**: the model emitted the six correct rows and
then looped, re-emitting `IC-3 IC-4 IC-5 EC-1 EC-2` six times over. Final tally:
`IC-1`×2, `IC-3`×6, `IC-4`×6, `IC-5`×6, `EC-1`×9, `EC-2`×9. It stopped mid-object after
13,039 characters.

**n=4 is stable.** Three runs, byte-identical replies, identical token counts. Worth
recording against **F-155**, which established that EL-stage runs are not deterministic
at `temperature=0`: on this prompt, on this machine, they were. F-155's measurement was
over a batched EL run and is not contradicted — but "temperature 0 is not
reproducible" is not universal, and this is a counter-example in the same repository.

## §6 Test coverage — F-170 confirmed, and refined

**F-170 is correct.** **[measured]** `_llm_refine` has no test coverage; the only
occurrences of `_llm_refine(` in the tree remain its definition and its single call
site in `ui.py::HarmoniserView::_harmonise_llm`.

**Which of the six paths did this failure take? None of them.** **[measured]**
`llm_refine.py` has **seven** `raise RuntimeError` sites. Six are inside `_llm_refine`
and are the six F-170 enumerates. The seventh is inside `_call_openai_json`, and it is
the one that fired. F-170's count is right about the function it names and **excludes
the raise the maintainer actually hit** — worth an annotation on that row rather than a
correction, since the row's claim is about `_llm_refine`.

Had the brace been present, the run would have reached the second of F-170's six —
*"LLM changed row count (expected 8, got 9)"* — and failed there instead. **The
guardrails are not the problem. They are working; the reply is genuinely bad.**

## §7 / §8d What a user can do today, and what they are told

**Nothing in the GUI addresses this, and nothing names the cause.**

**[read]** the Harmoniser tab offers: load criteria, load A vector, a model combobox,
*Harmonise (no LLM)*, *Harmonise + LLM*, *Validate*, *Export bundle*, and per-cell
editing of the resulting table. There is **no** control for context length, response
length, batching, retry, or criteria count. The model box changes *which* model, not
how it is called.

What the user sees is a modal titled **"Operation failed"** whose text is
*"The model did not return a JSON object. First 200 characters of the reply: '{"rows":
[{"id": "IC-1"…'"* — a fragment of well-formed JSON. **What a reasonable person
concludes from that is that the model did return JSON and the software is wrong**, which
is very nearly the opposite of the truth and is exactly where the first reading of this
incident went.

The only action that works is to **delete criteria from the text pane until it
succeeds** — which the maintainer discovered by doing it, not by being told. Nothing in
the message, the dialog title or the log pane mentions input size, criteria count,
tokens, or retrying. **A failure whose only remedy is "use fewer criteria", that never
says so, is unactionable**; and on this evidence the remedy caps out at four, which is
half of the repository's own reference file and a small fraction of a real review.

## §8a The threshold, and why the honest answer is not a number

**Largest count that succeeded: four.** Three consecutive successes, byte-identical.

**But "up to 4 works" would be a misleading thing to write in a release note**, for two
reasons the measurements force:

- **the degradation is not monotonic.** Six fails worse than eight — 40 seconds and
  13,039 characters against 13.8 seconds and 3,280. A threshold implies that below it
  you are safe and above it you are not; here the failure mode changes shape between 6
  and 8, and nothing suggests 5 or 7 behave like their neighbours.
- **the mechanism is a probability, not a limit.** No boundary was crossed at n=6 or
  n=8. A 3B model emitting long structured JSON in one shot has some per-token chance of
  losing the frame, and that chance compounds with length. Four worked three times; that
  is evidence it is *likely* to work, not that it *will*.

**[not established]** where n=5 and n=7 fall, and whether n=4 holds across models. Both
need more calls than the brief authorises, and neither changes the finding.

## §8b Input or output? Neither

**Neither side overflows, and their sum does not either.** **[measured]** at n=8, the
worst case for input: prompt 1,384 tokens, completion 896, total **2,280**. At n=6 the
total reached 4,716 and still returned `finish_reason: 'stop'`.

**This decides the remedy, and it rules out the two the brief proposes first.** A larger
`num_ctx` fixes nothing — the window was never reached at n=8. A `max_tokens` setting
fixes nothing either; it can only make replies *shorter*, and the n=8 reply was already
complete. `max_tokens` would help exactly one observed case — capping n=6's runaway
before it burned 40 seconds — and that is a cost control, not a correctness fix.

**What the evidence points at instead:** send fewer rows per call. Batch the criteria the
way EL and IL batch records, so each call asks for an object small enough that a small
model closes it — and validate and retry per batch rather than losing the whole table to
one missing character.

## §8c Does anything scale? No

**[measured]** `plugins/03_harmoniser/llm_refine.py` contains **zero** occurrences of
`batch`, `chunk`, `retry`, `split` or any adaptive behaviour. Every criterion goes in one
`user` payload, in one call, whatever the count.

The contrast is inside the same repository. `plugins/_common/llm_client.py`, which EL and
IL use, mentions `batch` **86 times** and its `run_m1_llm_for_criterion` carries batching,
per-batch failure accounting and a run report. `07_criteria_parsing.md` §4 already
recorded the harmoniser's second call site as having *"no batching, retry, adaptive
split, cache, progress events, run report, provenance, or cancellation"* — and this
incident is the first time that list has had a user-visible cost attached to it.

**So this is a design gap, not a tuning problem**, and it is the finding.

---

## Candidate findings

Proposed severities against the register's own bar: **Critical** = incorrect scientific
output, data loss, or security · **High** = blocks maintenance or peer review ·
**Medium** · **Low** = cosmetic. Max register ID is **F-181**.

### HLF-1 — the harmoniser's LLM path sends every criterion in one call, and fails on the repository's own sample

**Proposed severity: High.** **[measured]** with `llama3.2:latest` — the model the
maintainer runs and the one `06_llm_integration.md` treats as the local default — the
path succeeds at 2 and 4 criteria and fails at 6 and 8. `samples/ic_ec_12.txt` has
**eight**. The configuration that works is one no systematic review would ever have.

The mechanism is not a limit: nothing overflows (§8b). It is that a 3B model asked for
one long structured object in a single shot, with no batching, no retry, no adaptive
split and no bound (§8c), sometimes loses the frame — a missing brace at n=8, a
repetition loop at n=6 — and one lost character discards the whole table.

**Direction of harm is safe**, which is why this is High and not Critical:
`ui.py::HarmoniserView::_harmonise_llm` assigns `self.state.rows = refined` **only on
success**, so a failure leaves the rule-based table untouched. No wrong criteria reach a
screening run through this door. What is lost is the feature.

**Duplication sweep.** **[measured]** over all 178 register rows: `runaway` 0 hits,
`did not return a JSON` 0 hits. **F-146** is the closest and is `(done)` — it records
that this path *never executed* before wave 12 and fixed the dead SDK branch; this is
the successor state, discovered by being the first person to run it, and F-146's own
cell predicts it (*"a bare `json.loads` on a fenced reply is the most likely thing the
removed branch was hiding"* — the guess was right about the class and wrong about the
shape). **F-154** is about `num_ctx` and prompt truncation and this row is measured
*not* to be that. **F-158** is the harmoniser LLM path's missing audit trail, a
different defect on the same button. Novel.

**Suggested fix, argued.** Batch the criteria per call, as EL and IL already batch
records, and validate per batch so one bad reply costs one batch rather than the table.
`max_tokens` is worth setting as a cost bound — it would have capped n=6's 40-second
loop — but it is **not** the fix, because n=8's reply was already complete.

### HLF-2 — the failure message cannot distinguish its own causes, and misled the first person to read it

**Proposed severity: Medium.** The message quotes 200 characters and discards
`finish_reason`, all three token counts, the reply length, and the parse exception
naming the exact offending column (§2). Every one of those was in hand.

**The concrete cost is documented in this very document.** The 200-character window ends
mid-token at `"tar`, which reads as a truncated reply; the first reading of the incident
concluded exactly that, and it was wrong. Truncation, malformation, refusal and a
repetition loop all produce this one message.

**Duplication sweep.** **[measured]** **F-122** already records *"`finish_reason` is
never read anywhere"* — that half is **not novel** and belongs as an annotation on
F-122 rather than in a new row. **F-25** already records *"no `max_tokens`"*; the
`max_tokens` observation in §3 belongs there. What is novel is the rest: the token
counts, the reply length and the destroyed `JSONDecodeError`, and the demonstrated
misdirection. **F-64** is the same shape one stage over — a status emitted without the
information needed to interpret it. The coordinator may prefer this as an extension of
F-122 rather than its own row; on balance I would keep it separate, because F-122 is
scoped to `_parse_llm_json_array` and the robustness of `resp.choices[0]`, and this is
about what a *user* is told when a guard fires.

---

## Corrections to the brief

1. **"Length is confirmed as the variable" — half right, and the half that is wrong
   changes the remedy.** Length correlates with failure, and the controlled comparison
   is sound. But the brief's §8b asks which side overflows, and **neither does**: n=8
   uses 2,280 tokens and returns `finish_reason: 'stop'`. Framing this as a window
   problem points at `num_ctx`, which would fix nothing.

2. **The failure is not monotonic in length**, so §8a's "report the largest criteria
   count that succeeds" has no safe answer. Six fails worse than eight. The largest that
   succeeded is four; writing that down as a supported limit would overstate what three
   runs establish.

3. **The reply was not truncated.** The brief is right that the 200-character fragment is
   the *error message* truncating, and right to warn against inheriting the
   truncated-reply reading. The correct reading is a third thing: **complete and
   malformed** — one missing closing brace, plus a hallucinated ninth row that would have
   failed a different guard anyway.

4. **F-154's 4,096 does not hold on this machine.** A run completing 4,716 total tokens
   with `finish_reason: 'stop'` cannot have been bounded at 4,096. F-154's claim that
   `num_ctx` is never set is confirmed; its observed default value is not.

5. **F-170's "six `RuntimeError` paths" excludes the one that fired.** There are seven
   raise sites in the module; the seventh is in `_call_openai_json`. F-170's claim is
   accurate about `_llm_refine` and should gain an annotation, not a correction.

6. **`finish_reason` being discarded is already registered** as F-122. I nearly filed it
   as novel; the sweep caught it. Recording that here because this register has eight
   duplicates behind it and the near-miss is the interesting part.

---

## What was not done

- **Nothing was fixed.** No source, test, golden, sample, register row or changelog entry
  was modified.
- **No EL or IL screening was run**, and no bundle was exported.
- **No paid vendor API was called and no API key was used.**
- **The effective `num_ctx` on this machine is [not established]** — only that it exceeds
  4,716. Settling it needs the daemon's environment or a deliberate overflow probe, and
  neither was needed once the window was ruled out.
- **n=5 and n=7 are [not established]**, and so is whether n=4 holds on `qwen2.5:7b`,
  which is also installed. Both need calls beyond the six authorised.
- **The GUI was not observed.** §7 is read from `ui.py`, not from a running window.
- **One run per size, except n=4.** F-155 warns that these runs vary; n=4 was repeated
  three times and did not, but n=6 and n=8 are single observations and their *specific*
  failure shapes may not reproduce. That they fail is established by the maintainer's
  independent run at n=8; that n=6 loops is one observation.
