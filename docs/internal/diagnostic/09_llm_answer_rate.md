<!-- SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo -->
<!-- SPDX-License-Identifier: MIT -->

# 09 — Why EL answered 15 calls of 294 and IL answered 144 of 147

*Read-only diagnostic of one measured asymmetry, reproduced against the same model.
Nothing was fixed.*

**Repository state:** `diag/llm-answer-rate` off `fix/wave-13f-register` @ `31ed041`
(`git describe --tags` → `post-wave-13e-2-g31ed041`). `git status --porcelain` empty at
session start. **Date:** 2026-08-13. **Mode:** read-only. No source, test, golden,
sample, register row or user-facing document was modified. This file is the only one
added.
**Test baseline:** **1880 passed, 7 skipped** — before and after.
**Goldens:** `tests/golden` tree object `050b3575` (`git rev-parse HEAD:tests/golden`),
unchanged before and after. *No aggregate listing hash is quoted: wave 13e retracted
`9b7fe3e2` as a hand-carried number that never derived.*

**`origin` could not be reached this session.** `git fetch origin` exited 128 (no network
to `github.com/lars-ulaval/metaScreener.git`). Against the last-known refs, `main` and
`origin/main` are both `fe5c5ff` and agree; `31ed041` is 2 commits ahead of both and
unpushed. **Origin sync is asserted from stale refs, not verified.**

## Gate exception — the evidence folder is empty

The brief directs this session to read the run bundles at `%TEMP%\ms_run_20260813\`.

**The directory exists and contains zero files.** `Test-Path` → `True`;
`Get-ChildItem -Recurse -Force -File` → `0`. Its mtime is `2026-08-13 16:46:37`, minutes
before this session began. There are no EH, IH or post-EL bundles, no ScreenA report
workbook, no cache, no manifest.

Every number the brief quotes from that run is therefore **reported, not verified**, and
is marked `[reported]` at each use. What replaces the bundle is the frozen study corpus at
`docs/data/study_input/`, the three committed local runs at `docs/data/wave12_local_runs/`
— one of which is **qwen2.5:7b against this exact EL prompt** — and twelve live calls to
the same local model.

## Network disclosure — read this first

**I called the local Ollama server. Thirteen requests in total: one metadata, twelve
inference.** The brief authorises up to twelve inference calls where a call settles what
reading cannot; I used exactly twelve and made no thirteenth. I said before making them
that I would, and I am saying after that I did.

- **1 metadata**, no inference: `GET http://localhost:11434/api/tags`.
- **12 inference**, all `POST http://localhost:11434/v1/chat/completions`, all against
  `qwen2.5:7b`, all at `temperature=0.0`, all carrying a prompt rendered by the
  repository's own builders with `trunc_chars=1500` and a batch of one — the run
  configuration the brief describes.
- **No paid vendor API was contacted. No API key was used** — the only credential in play
  was the literal string `local`. **No stage was run.** No model was pulled. The daemon
  was already running; I did not start it. Nothing was written inside the repository by
  the probe; its scratch lives in `$env:TEMP\ms_diag_answer_rate\` (`render.py`,
  `probe.py`, `baserate.py`, `parsecheck.py`, `outcome.py`). Only `probe.py` touches the
  network — the other four import repository symbols and execute them on fixed inputs.

## Evidence conventions

As `07_criteria_parsing.md` and `08_harmoniser_llm_failure.md`. Claims are anchored on
`path::symbol`; **line numbers are never cited.** The house markers are used unchanged:

- **[measured]** — established by running something. The command or script is named.
- **[read]** — established by reading source, a document, or a committed artefact.
- **[not established]** — I could not settle it, and why.
- **[general knowledge]** — from outside this repository, flagged so it is never mistaken
  for a measurement.

**One marker is added for this session**, because the empty bundle creates a category the
house set has no name for: **[reported]** — the coordinator's observation of the
2026-08-13 run, which cannot be verified here. It is not a weaker `[measured]`; it is
someone else's measurement.

---

## Executive summary

EL and IL are the same code. The prompt builders' **function bodies are byte-identical**
and only their docstrings and `PROMPT_VERSION` differ; the system prompt is byte-identical;
the client, parser, evidence gate and counters are one shared implementation. **Nothing in
the EL path is stopping the model.** What differs is the *criterion*, and the proportion
of the corpus that matches it.

The shared system prompt says *"Return a JSON list of objects, nothing else."* A small
model reads that as a **filter**: return the items that match. When a criterion matches
nothing — `EC-2` "spatial navigation in a virtual maze", `EC-3` "the rubber hand illusion
paradigm", against a corpus of VR training papers — the honest filter output is the empty
list `[]`. That reply parses cleanly, yields zero objects, and
`plugins/_common/llm_client.py::run_m1_llm_for_criterion`'s omission back-fill writes
`used: False` for every record, which
`plugins/_common/llm_client.py::summarize_llm_evidence` counts as **`no_answer`**. The
model was not silent. It said *"none of them"*, and the pipeline recorded *"it said
nothing."*

**[measured]** `EC-2` returned the two characters `[]` on **6 of 6** attempts across four
records, including two verbatim retries. `IC-1`, on the same records in the same session,
returned populated verdict objects on **3 of 4**.

Three of the brief's premises are wrong, one of its two named levers is measured
worthless, the other is measured to work *without* the change the brief attaches to it,
and two of the eight candidate findings I first drafted were already open register rows.
All of that is in §8 and §5.

---

## §1 The prompt builders, and what actually differs

Both symbols: `plugins/06_el/prompt.py::_build_llm_messages_for_criterion` and
`plugins/07_il/prompt.py::_build_llm_messages_for_criterion`.

**[measured]** `git diff --no-index plugins/06_el/prompt.py plugins/07_il/prompt.py`:
the **function bodies are character-for-character identical**; the module docstrings differ
in stage names and cross-references, and `PROMPT_VERSION` is `"EL_v1_jsonlist"` versus
`"IL_v1_jsonlist"`. `PROMPT_VERSION` is never referenced inside the builder — it reaches
`plugins/_common/llm_client.py::_cache_key` and never the messages **[read]**.

`07_criteria_parsing.md` §3 established that each prompt carries `json.dumps` of ONE
criterion. **That still holds for both stages [read]**: each builder constructs one
`c_pack` and emits `json.dumps({"criterion": c_pack, "items": items_pack})`.

**The rendered prompts, same record, both criteria.** Record `A612` from
`docs/data/study_input/el_input_v3.1.0.csv`, `trunc_chars=1500`, batch of one, rendered by
the repository's own builders **[measured, `render.py`]**.

*System message — identical for both, 326 characters:*

```
You are scoring research items against ONE screening criterion. For each item, answer with JSON only. Keys per item: a_id, decision ('meet'|'not_meet'|'uncertain'), confidence (0..1), field ('title'|'abstract'|'keywords'), quote (exact substring from that field), span [start,end]. Return a JSON list of objects, nothing else.
```

*User message, `EC-2` — 2052 characters (the `items` array is identical for both and is
elided for width):*

```json
{"criterion": {"id": "EC-2", "type": "exclude", "operator": "llm", "target": "keywords", "what": ["The paper’s primary focus is spatial navigation in a virtual maze (no social interaction or collaboration)."], "how": "llm", "label": "The paper’s primary focus is spatial navigation in a virtual maze (no social interaction or collaboration).", "threshold": 0.6}, "items": [{"a_id": "A612", "title": "A Critical Review of the Use of Virtual Reality in Construction Engineering Education and Training", "abstract": "Virtual Reality (VR) has been rapidly recognized and implemented in construction engineering education and training (CEET) …", "keywords": "Virtual reality; Computer science; Visualization; Task (project management); Training (meteorology); Human–computer interaction; Engineering management; Engineering; Systems engineering; Artificial intelligence; Meteorology; Physics"}]}
```

*User message, `IC-1` — 2048 characters, same record, same `items` array:*

```json
{"criterion": {"id": "IC-1", "type": "include", "operator": "llm", "target": "keywords", "what": ["The paper considers immersive virtual reality OR a virtual simulation using a head-mounted display (HMD)."], "how": "llm", "label": "The paper considers immersive virtual reality OR a virtual simulation using a head-mounted display (HMD)."}, "items": [{"a_id": "A612", …identical…}]}
```

**The entire difference between an EL call and an IL call, for the same record, is the
`criterion` object.**

**The `items` payload ignores `target`** — both builders always send `title`, `abstract`
*and* `keywords`. This is not new: `07_criteria_parsing.md` registered it as its own
candidate **D-9**, *"behaviourally inert today because the prompt packs all three fields
regardless."* It is inert for correctness and decisive for §3.3's arithmetic.

**There is only one system prompt.** `EL_v1_jsonlist` and `IL_v1_jsonlist` name two
identical strings **[measured: `system_el == system_il` → `True`]**. **The coordinator's
hypothesis (b) — a wording difference between the stages' system prompts — is refuted:
there is nothing to differ.**

## §2 The reply shape, the whitelist, and the polarity problem

Both stages expect **the same JSON**: a list of objects with
`a_id, decision, confidence, field, quote, span`.

`meet`/`not_meet` is **not** framed differently for an exclusion criterion than for an
inclusion one — the system prompt is one string and says nothing about polarity. Polarity
is applied afterwards, in the engines, correctly: `plugins/06_el/screen.py::run_el_screen`
and `plugins/07_il/screen.py::run_il_screen` branch on `c.ctype` and route the excluding
verdict through the single `_excluded_by` helper **[read]**.

**This observation is not new, and 07 gets the credit.** `07_criteria_parsing.md` §3
already recorded that the pack says `"type": "exclude"` while the prompt asks for
`decision ('meet'|'not_meet'|'uncertain')` *"without ever stating what 'meet' implies for
an exclusion criterion."* §3 also establishes two things worth carrying forward: the whole
criteria table is never sent, so the model cannot see that a sibling criterion covers the
same ground; and *"the harmonised `label` is what the model sees, not the raw prose."*

**Wave 8's case-folding fix covers both stages and both framings [read].** The
normalisation is `plugins/_common/llm_client.py::_normalize_decision`, called from the
single shared parse loop both engines enter. It folds case *and* separators
(`_DECISION_SEPARATORS`), so `"Meet"`, `"NOT MEET"` and `"not-meet"` all reduce correctly,
and returns `None` rather than silently rewriting to `uncertain`, so the rejection is
counted as `decisions_rejected`. **One implementation, no stage branch — the F-90 fix
cannot be present for one stage and absent for the other. Confirmed.**

## §3 The parser — what "answered" means, and what is kept

`summarize_llm_evidence` partitions each evidence record **[read]**:

| bucket | condition |
|---|---|
| `failed` | `"error" in ev` |
| `no_answer` | `ev.get("used") is not True` |
| `decisions_rejected` | `"decision_rejected" in ev` |
| `answered` | `used is True`, no error, a readable decision |

**`no_answer` is derived, not incremented.** The record behind it is written by the
omission back-fill inside `run_m1_llm_for_criterion` — the loop commented *"ensure every
item in THIS cur_batch has an entry"* — which writes
`{"used": False, "decision": "uncertain", "field": "abstract", …}` for any `a_id` the
parse loop did not reach. A record lands there when `_parse_llm_json_array` returned an
empty list, or returned objects none of which carried an `a_id` in `_field_texts_by_id`.

**What `_parse_llm_json_array` accepts [measured, `parsecheck.py`]:**

| input | result |
|---|---|
| `[{…}]` plain list | parsed |
| ` ```json [{…}] ``` ` fenced list | parsed |
| `{"results": [{…}]}` object wrapping a list | **parsed** — the salvage regex finds the inner list |
| `{"items": [{…}]}` | **parsed**, same accident |
| `{"a_id": …}` **bare object** | **`[]`** |
| `[{…},]` trailing comma | **`[]`** |
| `[]` | `[]` |

**This is F-122, an open register row, stated verbatim there** — *"accepts an object
wrapping a list but returns `[]` for a bare object and for a trailing-comma list"*, with
the fix cell already reading *"Promote a lone dict to a one-element list."* I re-derived
it before finding the row; the row wins, and §5 records the withdrawal. **The wrapper
tolerance is what makes lever 1 work today (§4.1), and F-122's own Impact cell calls it
working "by accident."**

**Is the raw reply retained anywhere? No.** **[read]** `txt = (resp.choices[0].message.content or "[]")`
is a local in the batch loop; it is passed to the parser and goes out of scope. No `log(...)`
call includes it. The evidence dict carries seven fixed keys — no `raw`, no
`finish_reason`, no token count, no reply length. **The cache cannot hold it either:**
`_is_cacheable_evidence` requires `ev.get("used") is True`, so a `no_answer` record is
refused a cache line.

**[measured]** `docs/data/wave12_local_runs/runC_qwen25_manifest.json` records
`{"records": 170, "answered": 137, "no_answer": 33, …}` and `runC_qwen25_EL_cache.jsonl`
contains **exactly 137 lines**.

**Precision, because my first draft overstated this.** The *fact and per-record identity*
of a no-answer **do** survive, in the exported CSV: `runC_qwen25_EL_FULL.csv` carries
`el_evidence_json` for all 170 judgments, the 33 appearing with the signature
`used: false / confidence 0.0 / span null`, and all 33 citing `field: "abstract"` — the
back-fill's hard-coded default, which is a cheap forensic marker. What is unrecoverable is
**the reply itself**: what the model actually said, its `finish_reason`, and its token
counts. Nobody can tell an empty list from a prose refusal from a truncated object from
any artefact this pipeline writes. That is **D-4**, and its nearest register neighbour is
**F-135** (*"Nothing ties a verdict to the call that produced it"*), not F-186.

## §4 The asymmetry — the hypothesis refuted, and what replaces it

> *"Something in the EL prompt or parser makes a small local model produce nothing usable,
> while the IL equivalent works."*

**Refuted.** There is no EL prompt distinct from the IL prompt (§1) and no EL parser
distinct from the IL parser (§3). One builder body, one system string, one client, one
parse loop, one gate, one set of counters.

**[measured] — twelve calls to `qwen2.5:7b`, `temperature=0.0`, `trunc_chars=1500`, batch
of one:**

| # | criterion | record | latency | raw reply | recorded as |
|---|---|---|---|---|---|
| 1 | `EC-2` | A423 | 6.66 s¹ | `[]` | **no_answer** |
| 2 | `IC-1` | A423 | 0.38 s | `[]` | **no_answer** |
| 3 | `EC-2` | A493 | 0.43 s | `[]` | **no_answer** |
| 4 | `IC-1` | A493 | 2.21 s | `[{"a_id":"A493","decision":"not_meet","confidence":0.8,"field":"keywords","quote":"Virtual reality exposure therapy","span":[21,45]}]` | **answered** |
| 5 | `EC-2` | A564 | 0.47 s | `[]` | **no_answer** |
| 6 | `IC-1` | A564 | 2.09 s | `[{"a_id":"A564","decision":"meet",…,"quote":"Virtual reality","span":[13,22]}]` | **answered** |
| 7 | `EC-2` | A572 | 0.57 s | `[]` | **no_answer** |
| 8 | `IC-1` | A572 | 2.69 s | `[{"a_id":"A572","decision":"not_meet",…,"quote":"Spherical video‐based virtual reality (SVVR)","span":[139,146]}]` | **answered** |

¹ first call of the session — cold model load, not inference time.

**The reply is never malformed.** `[]` is valid JSON and means what it says. Note call 2:
`IC-1` also returned `[]` on the one record whose keywords are about social media rather
than VR. **The behaviour is not stage-bound — it is match-bound**, which is the whole
point.

**This mechanism is consistent with all four rates the brief reports [reported +
inference]:**

| criterion | polarity | reported | as a share of that criterion's 147 calls |
|---|---|---|---|
| `IC-1` immersive VR / HMD | include | 144 of 147 | 98 % |
| `IC-5` training / vocational / workplace | include | 32 of 147 | 22 % |
| `EC-2` + `EC-3` maze / rubber-hand | exclude | 8 of 147 *between them* | 5.4 % of one criterion's calls; **2.7 % of EL's 294** |

**The brief's own EL figures do not reconcile, and I am not papering over it.** It states
EL answered **15** of 294, and separately that `EC-2` and `EC-3` answered **8** between
them. `EC-2` and `EC-3` *are* EL's two criteria, so those should be the same number. The
gap is **[not established]** — the bundle is empty. Nothing in this document turns on
which is right; both are ≤ 5 %.

**Answer rate tracks match rate, not stage. [measured]** on the frozen 85-record corpus by
deterministic keyword count (`baserate.py`): VR terms in `keywords` 43/85 = 50.6 %;
training/vocational/workplace across title+abstract+keywords 13/85 = 15.3 %; maze or
spatial-navigation terms **0/85**; rubber-hand terms **0/85**.

**The timing asymmetry is explained without invoking hardware.** The brief reports EL
≈ 0.87 s/call and IL ≈ 8 s/call with GPU activity during EL and heavy CPU during IL, and
offers VRAM pressure. In this session, one server, one model, no reload between calls,
**EL-shaped calls took 0.33–0.57 s and IL-shaped calls 2.09–2.69 s** — a 5× ratio produced
entirely by output length: `[]` is two tokens, a verdict object roughly sixty. **This does
not prove the coordinator's machine had no VRAM problem** — his 8 s is well above my
2.7 s, and F-154 quotes his own Ollama log reading `total_vram="0 B"
default_num_ctx=4096`. What it removes is the timing observation as *evidence for* a
context-window problem.

**It also explains the shape of the answers the run did get [reported + inference].** All
were `not_meet`, and 7 of 15 cited a quote absent from the text. Those are the calls where
the model scored rather than filtered; having then to supply a mandatory `quote` for a
*negative* verdict it fabricated one. Two of my eight probe calls show the same defect from
the include side: calls 4 and 8 returned `valid_quote: False`, and call 8's `span`
`[139,146]` is inconsistent with its own 43-character quote.

**The structural cause underneath is D-5.** The system prompt makes `quote` — *"exact
substring from that field"* — required for **every** verdict including `not_meet`. For an
exclusion criterion on a non-matching record there is no such substring, because the
justification is absence. **The prompt demands evidence that cannot exist**, and the
evidence gate then correctly rejects what the model invents.

---

## §5 Q2 — the four levers

### 5.1 Lever 1 — constrained JSON decoding

**What is sent today, verbatim, for both stages [read,
`plugins/_common/llm_client.py::run_m1_llm_for_criterion._call_once`]:**

```python
client.chat.completions.create(
    model=model,
    messages=msgs,
    temperature=temperature,
)
```

**Three parameters. That is the whole request.** No `response_format`, no `format: "json"`,
no `max_tokens`, no `seed`, no `stop`, no `options`. `_openai_client_for` passes no
`timeout` and no `max_retries` either, so the SDK's defaults stand (F-25). Ollama's native
`/api/chat` is never used, so `format: json` has no call site to be sent from.

`stage` reaches `_has_openai_key` and `_openai_client_for`, so it selects endpoint, key
and per-stage config — and because `model` is stage-overridable (§5.4), **`stage` can
change the model on the wire.** It changes no *body parameter* and no byte of `messages`.

**[measured] — probe calls 9–10, the two failing `EC-2` prompts re-sent with
`response_format={"type": "json_object"}`:**

- **Ollama accepted the parameter.** No 400.
- **The model produced a real verdict for both** — `{"a_id": "A423", "decision":
  "not_meet", "confidence": 0.9, "field": "keywords", "quote": "Social media", "span":
  [0, 8]}` and the equivalent for A493. The empty list is gone.
- **The pipeline still recorded `no_answer` for both**, because JSON-object mode forced a
  **bare** object and the parser drops those.

**But the parser accepts `{"results": [...]}` (§3).** So the working combination is
**`response_format` plus one sentence in the system prompt asking for a `{"results": [...]}`
wrapper — and it needs no parser change at all.** My first draft concluded the opposite;
`parsecheck.py` refutes it.

**The real costs, all of which a next wave must plan for:**

1. **The cache key does not cover it.** `_cache_key` hashes exactly
   `{prompt_version, model, endpoint, temperature, prompt}` **[read]**. Adding
   `response_format` changes what is *asked* and not the key, so entries cached by an
   unconstrained run are served to a constrained one and back — the F-01 / F-89 shape. **A
   `PROMPT_VERSION` bump is mandatory**, which moves the byte-identity goldens and trips
   `tests/test_el_regression.py`.
2. **F-107 is the standing argument against this and must be engaged, not bypassed.** Its
   Impact cell names precisely this commit: *"A 'modernise the SDK call' commit adding
   `response_format` … would silently narrow the set of servers the tool can talk to — with
   the whole suite green, because nothing asserts the shape."* The minimal request is a
   deliberate portability property that survives by luck.
3. **Failure is not graceful, and is worse than "terminal".** A rejected parameter raises
   `BadRequestError`; `_classify_llm_error` returns `bad_request` — terminal for the batch,
   since `salvageable = err_class in ("rate_limit", "oversize")`. Worse, a sub-agent
   **[measured]** a 400 whose body reads *"unsupported parameter 'response_format'; only
   max_tokens allowed"* classifying as **`("oversize", "type+message")`** — salvageable —
   because `_OVERSIZE_RE` matches `max_tokens`. Such a rejection routes into the full
   halve-then-step-down ladder, spending the same refusal repeatedly, before failing anyway.
   **An explicit unconstrained-retry fallback is required.**
4. **13 test doubles define `create(self, *, model, messages, temperature)` keyword-only**,
   so any added kwarg breaks the suite — F-107's accidental pin, doing its job.

The harmoniser failure in `08_harmoniser_llm_failure.md` was indeed a reply missing one
closing brace — **but constrained decoding would not have saved that run**: the same
document establishes the repaired reply parses to **9 rows for 8 inputs**, so it would
have failed at `_llm_refine`'s row-count check regardless, and names the real finding as
that path having *"no batching, chunking, retry, adaptive split or bound of any kind."*

### 5.2 Lever 2 — retry on no-answer

**There is no retry on a no-answer [read].** The ladder in `run_m1_llm_for_criterion` lives
entirely inside `except Exception`, fires only on a call that *raised*, and only for
`rate_limit` and `oversize`. A 200 whose reply yields no verdict takes the success path,
hits `break  # batch success`, and is never retried. The `no_answer` records are produced
*after* the parse loop and nothing inspects them.

The three counters are distinct **[read]**: `calls_failed` counts `_call_once` invocations
that raised; `failed` counts *records* carrying an `error` key; `no_answer` counts records
sent and not addressed. The brief's run has `calls_failed = 0`, `failed = 0`,
`no_answer = 279` — a healthy transport carrying a useless result.

**[measured] — probe calls 11–12: both failing `EC-2` prompts re-sent verbatim at
temperature 0 returned `[]` again, byte-stable.** This is two samples and it does not
overturn wave 12's finding that temperature 0 is not reproducible locally. It has a
same-repo precedent: `08_harmoniser_llm_failure.md` records *"n=4 is stable. Three runs,
byte-identical replies, identical token counts"*, offered there against F-155. What it
establishes is that **this failure is not noise**, so a lever whose premise is "try again
and get lucky" has no purchase on it.

There is no negative caching to work around: `_is_cacheable_evidence` refuses to store a
`no_answer`, so a re-run genuinely re-asks. That is already correct.

**The brief's citation is wrong and should not propagate. F-11 is
*"`plugins/02_references_of_x/` has zero test coverage"* — Plugin 02, no LLM content at
all [read].** F-12 does concern the LLM error paths, but its headline is stale at HEAD:
`tests/test_error_classification.py`, `tests/test_run_report.py` and
`tests/test_terminal_failure_guard.py` drive several of the branches it calls uncovered. A
new row on this path should cross-reference **F-25, F-94, F-122, F-134** and explicitly
**not** F-11.

### 5.3 Lever 3 — `num_ctx`, and F-154

**F-154 is open and its substance is correct [read]:** `num_ctx` appears nowhere in the
tree, no `options` block is sent, and an OpenAI-compatible server that overruns its window
truncates rather than erroring.

**The brief's arithmetic premise is wrong.** It asks me to compare "EC-2 (keywords only)"
against "IC-5 (title,abstract,keywords)" assuming the second is much larger. **It is
smaller** — the builder ignores `target` (§1).

**[measured, `render.py`] across all 85 records of `el_input_v3.1.0.csv` at
`trunc_chars=1500`, batch of one:**

| criterion | min chars | median | max | max ≈ tokens (÷4 / ÷3.5) |
|---|---:|---:|---:|---:|
| `EC-2` (exclude, target `keywords`) | 838 | 2354 | **2699** | 675 / 771 |
| `IC-1` (include, target `keywords`) | 834 | 2350 | 2695 | 674 / 770 |
| `IC-5` (include, target `title,abstract,keywords`) | 761 | 2277 | 2622 | 656 / 749 |

The `EC-2` → `IC-1` delta is **exactly −4 characters for every record**; `EC-2` → `IC-5` is
**exactly −77**. **IC-5's prompt is 77 characters smaller than EC-2's, not larger.**

**The hard ceiling, which does not depend on this corpus [inference from the builder's
structure]:** at `trunc_chars=1500` and batch of one the user message cannot exceed three
fields × 1500 + criterion pack + scaffolding ≈ 4900 characters, plus a 326-character
system message ≈ **5230 characters ≈ 1300–1750 tokens** even at a pessimistic 3 chars per
token. **A 4096-token window cannot be reached at batch_size 1.** This bound covers the
unknown 147-record corpus too, which is why it is the argument that matters.

**So `num_ctx` is not implicated in the run the brief describes, and IC-5's rate is not a
context problem.** §4 explains all four rates with one mechanism.

**F-154 remains real and open — and my first draft got its threshold wrong.** F-154's own
row measures batch 5 at 2,170/3,256 tokens and states *"the maintainer's runs did **not**
overflow"*; **batch 10 is the first unsafe size**, and the row states it *"BLOCKS any
future increase to the local batch range, and the present upper bound of 10 is already
unsafe."* §6 must not recommend raising the batch without engaging that.

Three further points a next wave needs:

- **Ollama truncates from the front, and the criterion is at the front.**
  `json.dumps({"criterion": …, "items": …})` puts the criterion first, and Ollama preserves
  `num_keep` leading tokens and the tail — so an overflowing call can drop *the criterion
  being asked about* while keeping the records. **[general knowledge]**, and a strictly
  worse failure mode than F-154's cell describes. `num_ctx` must be set **before** any
  batch increase, not alongside it.
- **The oversize salvage ladder is dead code against Ollama.** `_OVERSIZE_RE` watches for
  `n_ctx` / `context length exceeded` — strings llama.cpp and vLLM emit and **Ollama never
  does, because it truncates and returns 200 [general knowledge]**. On the server this
  project defaults to, the module's only oversize remedy cannot fire.
- **Ollama's default `num_ctx` is 2048 in older builds and 4096 in newer ones [general
  knowledge]** — not the flat 4096 my first draft asserted. At 2048 the wave-12 batch-5
  runs would have overflowed after all. Neither value is verifiable here.

### 5.4 Lever 4 — model size and the OpenAI path

**What changes between local and OpenAI is the resolved configuration, not the request
[read].** `_stage_config` resolves one `(provider, endpoint, api_key)` triple through
`plugins/_common/settings.py::resolve_stage`; `resolve_openai_base_url` and
`_openai_client_for` both read it, so client and cache key cannot disagree (F-89, F-92).
**The precedence is four steps, and the second is load-bearing:** an explicitly configured
endpoint (stage override, then application setting) → **a keyless provider falls back to
the local default, never to the vendor** → `OPENAI_BASE_URL` → the vendor default. My first
draft omitted step 2, which is the step that keeps a "local" run local.

**`STAGE_OVERRIDABLE = ("model", "endpoint", "batch_size")` [read], enforced closed.** A
sub-agent **[measured]** `set_stage_override(provider=…)` raising
`StageOverrideRefused: provider cannot vary per stage`; `allow_llm_exclusion` is likewise
refused. **So EL and IL cannot differ in provider — they can differ in model, endpoint and
batch size.** My first draft said provider too; that was wrong.

**On `flag_only` — the brief states it backwards.** The brief says *"flag_only defaults ON
for OpenAI (meaning exclusions act)"*; `flag_only` ON means exclusions **do not** act.
What the code does **[read]**: `llm_exclusion_allowed` returns
`_stage_config(stage).allow_llm_exclusion`, and
`plugins/_common/stage_state.py::exclusion_allowed` restricts exactly the keyless
providers, `_KEYLESS_PROVIDERS = ("local", "custom")`.

- **local / custom → exclusion NOT allowed → flag-only → a would-be exclusion becomes
  `EXCLUSION_SUPPRESSED`, not `OUT`.**
- **openai (keyed) → exclusion allowed → records go `OUT`.**

**A correction to my own first draft:** flag-only forces `OUT ≡ 0`, and it is precisely
what *produces* `EXCLUSION_SUPPRESSED`. So the brief's run having **0 `EXCLUSION_SUPPRESSED`
follows from the answer rate, not from the policy.** That distinction matters because §6's
branch walk turns on it.

The docstring gives the measured reason for the default: local models produced 40, 43 and
4 exclusions where the vendor model produced one correct one. **[read, with a caveat the
register carries]** only qwen2.5's **4** were individually audited and all four were wrong;
llama3.2's 40 and 43 were not individually audited. **The default is right.**

**Switching is harder than "open the provider dialog".** `metascreener/provider_dialog.py`
has exactly one construction site,
`metascreener/main.py::MainApp._show_provider_dialog`, reached only from
`::_offer_provider_choice` at launch when the provider is unset or the probe fails. **A
user whose local Ollama is running and healthy has no in-app route to it** — a sub-agent's
**[inference by exhaustion]**, which it flagged as such. Today the switch requires stopping
Ollama or hand-editing `%APPDATA%\metaScreener\settings.json`. Two further gaps: there is
**no format check on the key a user enters** on the reachable path
(`metascreener/api_key_dialog.py::validate_api_key` is dead for it), and
`provider_dialog.py` puts no `trace` on `var_key`, so **the key is validated for the first
time on the first billable call of an actual run.**

---

## §6 Q3 — what the user was actually told

**The brief's premise is wrong for this run, and the truth is more interesting.**

> *"A run where the model answered 15 of 294 calls reported as success: 'EL done',
> everything flagged, both exports enabled."*

The classifier is `plugins/_common/stage_state.py::run_outcome` — **seven ordered branches,
not the five wave 8 shipped**: wave 12 / F-145 added `exclusions_suppressed`, and F-153
rewrote the `separated` expression. Walked against the reported counts — `total_rows = 147`,
`OUT = 0`, `PASS_CLEAN = 0`, `EXCLUSION_SUPPRESSED = 0`; `records = 294`, `answered = 15`,
`failed = 0`, `decisions_rejected = 0`, `calls_failed = 0` **[read + reported]**, and
**[measured]** — `outcome.py` executes `run_outcome` on exactly these inputs:

| # | branch | condition | fires? |
|---|---|---|---|
| 1 | `cancelled` | `cancelled` | no |
| 2 | `not_screened` | `not_screened` | no — EL had two enabled criteria |
| 3 | `no_answers` | `records and answered == 0` | **no — 15 ≠ 0** |
| 4 | `nothing_separated` | `total_rows and separated == 0`, `separated = OUT + PASS_CLEAN + suppressed` | **YES — 0 + 0 + 0 = 0** |
| 5 | `exclusions_suppressed` | `suppressed` | not reached |
| 6 | `partial_failure` | `failed or rejected` | not reached |
| 7 | `ok` | — | not reached |

**A guard did fire.** The status line read *"EL: nothing separated — every record flagged
(model answered 15 of 294)."*, and because that branch sets an `ack_reason`, both export
paths in `plugins/06_el/ui.py::ELView` put up
`messagebox.askyesno("Check this before exporting", …)`.

**The brief was right that both exports were enabled, and I over-corrected in my first
draft.** Enablement is `plugins/_common/stage_state.py::control_states`, which returns
`export=(not running) and has_rows` and `export_bundle=(not running) and has_rows` **[read]**
— no outcome, no report field, no answer rate touches either. The buttons are live; the gate
is a modal on click. Only *"silently"* is refuted.

**Now read what the modal says at a 5 % answer rate [read]:**

> *"The model **was heard from** — 15 of 294 record-criterion pairs carry a decision — so
> this is **a screening result rather than a misconfiguration**, and **it may well be
> genuine**: a corpus the model is unsure about produces exactly this."*

**The dialog prints the correct number and then tells the user to disregard it.** At 15/294
the reassurance is false. The two branches are separated by `answered == 0` — a cliff with
no gradient. At `answered = 0` the user is told *"this is what an unreachable server, a
misspelled model name, a model that was never pulled and a rejected key all look like."* At
`answered = 1` that text is unreachable. **No threshold on the answer *rate* exists anywhere
in the codebase.** That is **D-2**.

**And the gate is one record wide. [measured, `outcome.py`]** — the same report, varying one
count:

| counts | code | label | export asks? |
|---|---|---|---|
| `PASS_CLEAN: 0` (as reported) | `nothing_separated` | *EL: nothing separated — every record flagged (model answered 15 of 294).* | **yes** |
| `PASS_CLEAN: 1` | `ok` | *EL done.* | **no** |
| `OUT: 1` | `ok` | *EL done.* | **no** |
| `EXCLUSION_SUPPRESSED: 1` | `exclusions_suppressed` | *EL done, flag-only — 1 record(s) carry a model exclusion that was not acted on.* | **no** |

**One record out of 147 flips a 5 %-answer run from a gated warning to a clean "done."**
With 15 answered pairs, `PASS_CLEAN ≤ 7`; whether it was ≥ 1 for the brief's run is
**[not established]**.

**The silent `"EL done."` is not hypothetical — it is in this repository's own frozen
artefacts. [measured]**, `docs/data/wave12_local_runs/runC_qwen25_manifest.json`:

```
llm_report: {"records": 170, "answered": 137, "no_answer": 33, "failed": 0,
             "decisions_rejected": 0, "fields_rejected": 0,
             "calls_made": 34, "calls_failed": 0, "batches_failed": 0}
counts:     {"OUT": 4, "PASS_CLEAN": 38, "PASS_FLAGGED": 43, "NOT_SCREENED": 0}
provenance: {"model": "qwen2.5:7b", "endpoint": "http://localhost:11434/v1",
             "temperature": 0.0, "prompt_version": "EL_v1_jsonlist",
             "trunc_chars": 1500, "batch_size": 5}
```

`separated = 4 + 38 + 0 = 42 ≠ 0` → branch 4 skipped; `failed = 0`, `rejected = 0` →
branch 6 skipped; **[measured, `outcome.py`] `code=ok`, `label="EL done."`,
`ack_reason=None` — exports ungated.** A
run with **19.4 % of record-criterion pairs unanswered reported as a clean success**, and
it was captured, committed and frozen as a measurement artefact.

**The sharpest statement of the defect is the pair of runs beside it. [measured,
`outcome.py`]** Runs A and B (`llama3.2:latest`, same batch 5) answered **170 of 170** — a
perfect answer rate — with `PASS_CLEAN: 0` and `OUT: 40` / `43`. They classify `ok` **only
because exclusions acted**. Re-run `run_outcome` with the same report under the shipped
local default — flag-only, so `OUT ≡ 0` — and it returns:

```
code=nothing_separated   ack=YES
label: EL: nothing separated — every record flagged (model answered 170 of 170).
```

***The gate demands an acknowledgement at a 100 % answer rate and stays silent at 5 %.***
Its label even prints the number that contradicts it. It is not measuring what its name
says, and `separated` — an outcome histogram — is doing duty for a question about answers.

**`no_answer` is computed, written to the manifest, and read by nothing. [measured]**
`grep -r no_answer` over the tree excluding tests: it appears in `summarize_llm_evidence`,
the wave-8 design document, two committed manifests and `07_criteria_parsing.md`.
**`run_outcome` never reads it** — it reads `records`, `answered`, `failed`,
`decisions_rejected`, `calls_failed` and the outcome histogram. That is **D-3**. It reaches
the user only obliquely: the criteria table's `n_uncertain` would read ≈ 279 across the two
criteria, merging never-answered with below-threshold and invalid-quote, and
`ELView::_open_row_detail_modal`'s column list omits `used` — the one field that separates
*"the model said uncertain"* from *"the model said nothing."*

**No test anywhere classifies a partially-answered run. [measured]** Every `llm_report`
fixture in `tests/test_llm_readiness.py` and `tests/test_stage_state.py` sets
`"no_answer": 0` — `WORKED`, `ALL_UNCERTAIN` and `WHOLLY_FAILED` alike. `no_answer > 0`
appears only in `tests/test_run_report.py`, which exercises `summarize_llm_evidence` in
isolation and never feeds `run_outcome`.

**Was this inside wave 8's intent? Unresolved, and I have moved off my first answer.**
`FIX_WAVE_8_READINESS.md` defines `no_answer` as *"sent, and the model said nothing about
it"*, which reads as intent. But the same document says, of F-118, *"wave 8's own run
report scores the records as `answered`, because the model did answer — about nothing. That
last one is a real limit of part 1's substrate"*, and its design block enumerates only
`answered == records` and `answered == 0`. **The design is explicitly binary.** A reader can
defend either reading from the same document; the defect stands on its own either way.

---

## §7 Candidate findings

**These are candidates, not register rows. No `F-nn` was assigned and
`docs/internal/diagnostic/03_findings.md` was not modified** — intake is the register
owner's, per F-179. `D-n` numbering is local to this document.

**Register:** `docs/internal/diagnostic/03_findings.md`, row format
`| ID | Sev | Category | Finding | Evidence | Impact | Suggested fix | Effort |`.
**[measured] true current maximum: F-190** — the coordinator's belief is **correct** this
time. The register holds **187 rows** with a permanent gap at F-56–F-58; its own rule is
*count rows, never the maximum ID*. Next free id: **F-191**.

**Severity bar, restated because D-1 is Critical:** Critical is reserved for incorrect
scientific output, data loss, or security.

### Two candidates withdrawn — they were already open rows

Recorded rather than deleted, because the near-miss is the point (F-190's precedent).

- **WITHDRAWN — "the parser rejects a bare JSON object".** This is **F-122**, open, Medium,
  verbatim, *including* the fix cell *"Promote a lone dict to a one-element list."* I
  re-derived it independently and measured it live; that adds evidence to F-122 and does
  not add a row. **What is new and belongs on F-122 as an addendum:** the wrapper tolerance
  it calls working "by accident" is the property that makes lever 1 shippable without a
  parser change (§5.1), which converts F-122 from robustness to *leverage*.
- **WITHDRAWN — "a non-`llm` operator in EL/IL is written as `used: False`".** This is
  **F-65**, open, **High**, which cites the same `if c.operator != "llm"` arm in both
  screens. **F-62** separately enumerates that site as a `used=False` writer.

### The candidates that survive the sweep

| ID | Sev | Category | Finding | Impact | Duplication check |
|---|---|---|---|---|---|
| **D-1** | **Critical** | correctness | **A model answering "none of these match" with an empty JSON list is recorded as having said nothing.** The shared system prompt's *"Return a JSON list of objects, nothing else"* is read by a small model as a filter, not a scorer. `[]` parses cleanly, yields no objects, and the omission back-fill writes `used: False` for every record in the batch, counted as `no_answer`. **[measured]** `EC-2` returned `[]` on 6/6 attempts; `IC-1` on the same records returned verdicts on 3/4. | A correct negative verdict for a whole batch is destroyed and replaced with "unresolved". On an exclusion criterion with a low base rate — the normal case — this is *every* record, and the run then reports as a screening result. | **New as to cause.** F-25's Impact cell already describes the same silent back-fill reached from a *different* upstream (mid-JSON truncation); F-122 covers the lone-object route. Neither names the empty list, and neither has a live measurement. Must cross-ref F-25 and F-122. |
| **D-2** | **High** | correctness / UX | **`run_outcome`'s `nothing_separated` acknowledgement asserts "The model was heard from … a screening result rather than a misconfiguration … it may well be genuine" at any answer rate above zero.** The alarming `no_answers` text requires `answered == 0` exactly. No threshold on answer *rate* exists anywhere. **[measured]** the gate is one record wide: `PASS_CLEAN: 1` flips a 5 %-answer run to `"EL done."`, ungated. | At 15/294 the dialog states the correct number and then tells the user to disregard it. A user who is not the author closes it and exports. | **New.** F-34, F-93, F-111 and F-153 establish "a degenerate run reporting success" as a defect class this project fixes; F-153 concerns the gate's *placement*. None concerns its *prose* or the missing rate threshold. |
| **D-3** | **High** | correctness | **`no_answer` is derived, written to the manifest, and read by nothing.** `run_outcome` consults `records`, `answered`, `failed`, `decisions_rejected`, `calls_failed` and the outcome histogram — never `no_answer`. No UI surface shows it; `_open_row_detail_modal` omits `used`. **[measured]** no test feeds `run_outcome` a report with `no_answer > 0`. | Demonstrated on committed artefacts: wave-12 `runC` had `no_answer: 33` of 170 and classifies `"EL done."`, ungated — while runs A and B, at a **100 %** answer rate, would hit the gate under the shipped flag-only default. | **New.** Sibling of D-2 and separable: D-2 is what the text says, D-3 is that the number is not consulted at all. |
| **D-4** | **High** | provenance | **On a no-answer, EL and IL retain nothing of the reply** — not the text, not `finish_reason`, not token counts, not the length. `txt` is a local that goes out of scope; the evidence dict has seven fixed keys; `_is_cacheable_evidence` refuses the record a cache line. **[measured]** `runC_qwen25_EL_cache.jsonl` has exactly 137 lines against `records: 170`. | An empty list, a prose refusal and a truncated object are indistinguishable in every artefact. The *fact* of a no-answer does survive in the exported `el_evidence_json` (`used: false / confidence 0.0 / span null`, all citing `field: "abstract"`) — **the reply does not**, so the dominant failure mode of local screening cannot be diagnosed after the fact. | **New.** Nearest is **F-135** (*"Nothing ties a verdict to the call that produced it"*) — same substrate, different missing field. F-122's unread `finish_reason` clause overlaps and should be cross-referenced. **Not F-186**, which is the harmoniser's *message* discarding diagnostics it held. |
| **D-5** | **Medium** | correctness | **The prompt makes `quote` — "exact substring from that field" — mandatory for every verdict including `not_meet`.** For an exclusion criterion on a non-matching record the justification is *absence*, so no such substring exists and the model must fabricate one or decline. | Explains why 7 of the 15 answers the run did obtain cited quotes absent from the text and were correctly rejected by the evidence gate **[reported]**, and why 2 of my 8 probe calls returned `valid_quote: False` **[measured]**. The gate is working correctly on output the prompt made impossible to produce honestly. | **New.** Must engage **F-21**, which argues the gate is too *weak* — the opposite direction — and cross-ref F-136, F-145, F-62, F-64. |
| **D-6** | **Low** | documentation | **F-154's row and `FIX_WAVE_12_FLAG_ONLY.md` §B2 carry token figures the repository has already corrected.** They say "509/764" and "2,679 … 4,020"; `docs/llm-evaluation.md` § "What is not established" corrects the worst reply to **327–491** tokens and the worst total to **2,497–3,747**. **[measured]** independently re-derived by a sub-agent. | A stale figure in an open High row is what the next wave sizes its work against. Exactly the class F-190 exists to record. | **New.** Same shape as F-190 and F-181; should cite both. |
| **D-7** | **Low** | efficiency | **The criterion pack carries the same sentence twice**, as `what` and as `label`, because the screens set `"label": c.label or c.source_text` and the harmonised CSV fills both identically. At batch of one this is a measurable fraction of the prompt. | Wasted context and a second copy of the instruction to reconcile. Cosmetic beside D-1. | **New.** `07_criteria_parsing.md` §3's *"the harmonised `label` is what the model sees"* is the substrate; no row covers the duplication. |

**Sweep caveat, stated because it bounds the above.** The duplication sweep covered
`03_findings.md` and the diagnostic set; it did **not** exhaustively read every
`docs/internal/FIX_WAVE_*.md` candidate section. F-179 and F-190 are precisely about
candidates lost at that boundary, so the clearances for D-2, D-3, D-5, D-6 and D-7 are
**provisional**. Two of my eight original candidates were already open rows; the base rate
for this kind of error in this document is 25 %.

---

## §8 The levers, ordered by expected value per unit of work

The brief asks for this ordering and says the next wave will be built from it. **The
measurements reorder it substantially, and the highest-value item is not one of the four.**

**1. Instrument the failure. [not a lever — do it first]**
Retain a bounded copy of the reply on a no-answer (D-4), read `no_answer` in `run_outcome`,
and replace the `answered == 0` cliff with a rate threshold (D-2, D-3). This fixes no model
behaviour and is nevertheless first: **without it, every lever below is evaluated blind.**
This session only escaped that because a live server happened to be running, and the wave-12
artefacts happened to be committed. A wave that ships any prompt or decoding change without
this cannot tell whether it worked. Lowest risk of the set — it adds no request parameter,
moves no golden, and needs no `PROMPT_VERSION` bump.

**2. Lever 1 — constrained JSON decoding, with a `{"results": [...]}` wrapper in the
prompt. [highest EV among the four]**
**[measured]** to produce correct verdicts from the exact prompts that were returning `[]`,
and — because `_parse_llm_json_array` already accepts an object wrapping a list — **to need
no parser change.** It also eliminates the missing-brace class behind
`08_harmoniser_llm_failure.md`. Real costs, none of them optional: a mandatory
`PROMPT_VERSION` bump (the cache key does not cover `response_format`), the goldens moving,
**F-107's portability argument answered rather than bypassed**, an explicit
unconstrained-retry fallback (a rejection can misclassify as `oversize` and burn the whole
ladder), and 13 keyword-only test doubles to widen.

**3. `batch_size` — and the prior recommendation it inverts. [an experiment, not a fix]**
**This is the item the next wave should confront first intellectually, whatever it builds.**
`07_criteria_parsing.md` §8.3 is *"T3 — batch size 1 by default for local models"*, and
states *"T3 is therefore not a new hypothesis needing a new experiment. It is the action
F-154 already implies."* Its falsification clause reads: *"if batch 1 does not reduce
`no_answer` … the change is justified only by the context-window argument."* **The reported
run is batch 1 at 279/294 unanswered (95 %); wave-12's committed batch-5 run is 33/170
(19 %) [reported + measured].** The falsification condition appears to have been met in the
field, on the same model. §8.3 already specifies the arms (batch ∈ {1, 5, 10}, three
repeats, metric `no_answer` plus `valid_quote is False`, a pinned digest rather than
`:latest`) — **so this is running an experiment the repository already designed, not
designing one.**
Two brakes: F-154 states the present upper bound of 10 is **already unsafe** and blocks any
increase to the local batch range, so `num_ctx` must be set *before* raising the batch; and
`08_harmoniser_llm_failure.md` records that its n=6 run *"emitted the six correct rows and
then looped … stopped mid-object after 13,039 characters"*, which is direct evidence
against the assumption that a bigger batch simply makes a list the natural reply shape. The
comparison above also crosses two variables — batch size *and* criteria file — so it is
suggestive, not controlled.

**4. Lever 4 — the OpenAI path. [high EV, low technical work, real cost and policy
consequence]**
`gpt-4o-mini` would very likely not do this. It also flips `allow_llm_exclusion` to true,
so exclusions begin *acting* on a corpus where qwen2.5's four audited exclusions were all
four wrong. **This is the "make the symptom go away" option and it moves the project off
the local-first posture waves 11–12 built.** It is also not one click: there is no in-app
route to the provider dialog for a user whose Ollama is healthy, and the key is
format-unchecked and first validated on the first billable call. Worth documenting as an
escape hatch, not adopting as the fix.

**5. Lever 3 — `num_ctx`. [low EV for this defect; real for F-154]**
**[measured]** not implicated at batch 1 — the ceiling is ~1750 tokens against a 2048–4096
default. It becomes decisive at batch 10, and it must be set **before** item 3 raises any
batch, because an overflow truncates from the front and the criterion is at the front.
Closing F-154 is the natural companion to item 3, not a substitute for it.

**6. Lever 2 — retry on no-answer. [lowest EV. Do not build.]**
**[measured]** worthless against this failure: two verbatim retries at temperature 0
returned byte-identical `[]`. It would double the cost of exactly the configuration that is
already failing, and do so most for the local users flag-only exists to protect. The thin
error-path coverage the brief attributes to F-11/F-12 is a real concern, misattributed
(F-11 is Plugin 02) and separate from this.

---

## §9 Sub-agent deaths and unreliable claims

Reported as the brief requires. No agent died; several were wrong.

- **The register-sweep agent guessed the run outcome and got it wrong.** It concluded
  `run_outcome` falls through to `OUTCOME_OK` for the reported counts, omitting the
  `nothing_separated` branch from the walk it presented as a conclusion, then appended it as
  an exception and noted *"I did not run this."* **Every `run_outcome` result in §6 is my
  own [measured] via `outcome.py`, not any agent's** — the disagreement is why. A reader who
  took only that agent's §5(a) would take away the wrong answer.
- **The lever-1 agent was overruled by its verifier on four points**, including a
  wrong test-double count and two false grep-exhaustiveness claims. Its most consequential
  error was demoting to hypothetical the counter-example its verifier then executed — that a
  400 rejecting `response_format` can classify as `oversize` and route into the salvage
  ladder. §5.1 uses the verifier's version.
- **The lever-2 agent's central lead is a different mechanism from the one measured.** It
  inferred the lone-object parse failure; the probe found the empty list. It also
  self-corrected a transcription error while quoting the register, and flagged its own
  F-12-is-stale claim as unquantified.
- **The lever-4 agent's headline is inference by exhaustion**, self-labelled: it found no
  in-app route to the provider dialog and searched for one. §5.4 carries that label.
- **The lever-3 agent's forward-reaching claims are its own knowledge**, self-labelled: the
  2048-vs-4096 default, front-truncation, `num_keep`, and the dead oversize ladder. §5.3
  marks them `[general knowledge]`. Its `%TEMP%` and corpus-mismatch results are
  `[measured]` and solid.
- **The agents disagreed among themselves on the `prompt.py` diff size** (2, 3, 4 or 6
  docstring lines; 9 bytes) and none reconciled hunks against lines against bytes. §1 states
  only what I measured: the function bodies are identical.

---

## Corrections to the brief

Recorded as this project's convention requires, because the coordinator asks to be
overturned in writing.

1. **"Something specific to the EL path is stopping it."** Refuted. The builders' function
   bodies are byte-identical, the system prompt is byte-identical, and the client, parser
   and counters are one shared implementation. §1–§3.
2. **"IC-5's prompts plausibly exceed a 4096 default … the leading explanation for BOTH
   IC-5's 32/147 and the CPU behaviour."** Refuted by measurement. The builder ignores
   `target`, so IC-5's prompt is **77 characters smaller** than EC-2's, and the hard ceiling
   at batch 1 is ~1750 tokens. IC-5's rate is its base rate. §5.3, §4.
3. **"A run where the model answered 15 of 294 reported as success: 'EL done' … both exports
   enabled."** Half refuted. `nothing_separated` fires and gates both exports behind a
   modal; the defect is that its text *reassures*. **The brief is right that both exports
   were enabled** — enablement keys on `has_rows` alone. The silent `"EL done."` is real for
   a different count shape and is demonstrated on wave-12 `runC`. §6.
4. **"flag_only defaults ON for OpenAI (meaning exclusions act)."** Stated backwards.
   Exclusion is *disallowed* for the keyless providers (local, custom) and *allowed* for
   keyed ones; flag-only is what produces `EXCLUSION_SUPPRESSED`. §5.4.
5. **"F-11/F-12 record this path as thin."** F-11 is *"`plugins/02_references_of_x/` has
   zero test coverage"* — no LLM content at all. F-12 is on-topic but stale at HEAD. A new
   row should cite F-25, F-94, F-122, F-134 and **not** F-11. §5.2.
6. **"Lever 1 … note the harmoniser's failure was a reply missing ONE closing brace — the
   shape constrained decoding eliminates."** The brace is confirmed; the inference is not.
   The repaired reply parses to **9 rows for 8 inputs** and would have failed anyway. §5.1.
7. **Lever 1 is not what the brief thinks, in the useful direction.** Constrained decoding
   produces a correct verdict that the parser drops *only if the reply is a bare object*;
   asking for a `{"results": [...]}` wrapper makes it work with **no parser change**. §5.1.
8. **Lever 2 has no purchase here.** The failing reply is byte-stable across verbatim
   retries at temperature 0. §5.2.
9. **"Report the true current maximum; the coordinator believes F-190."** **Correct.**
   F-190 is the maximum; next free is F-191. §7.
10. **The brief's own EL figures do not reconcile** — 15 answered of 294 versus 8 between
    `EC-2` and `EC-3`, which are EL's only two criteria. §4.
11. **An unstated premise worth surfacing: this is not a new experiment.**
    `07_criteria_parsing.md` §8.3 already proposed batch size 1 for local models as *"the
    action F-154 already implies"*, and the reported run appears to satisfy its own
    falsification clause. §8 item 3.

---

## What was not done

- **The 2026-08-13 run was not verified in any respect. [not established]** The bundle
  folder is empty. The 294 calls, the 15 answered, the 279 `no_answer`, the four
  per-criterion rates, the 15 `not_meet` verdicts, the 7 rejected quotes and the 147
  `PASS_FLAGGED` are all `[reported]`. §4's mechanism *predicts* them and is measured
  independently; it does not verify them.
- **The brief's EL figures were not reconciled. [not established]** 15 answered of 294, and
  8 answered between `EC-2` and `EC-3`, cannot both be right for a stage whose two criteria
  are `EC-2` and `EC-3`.
- **That run's corpus is not in this repository. [measured]** 294 = 147 × 2, but the frozen
  corpora hold **85** (`el_input_v3.1.0.csv`) and **84** (`il_filtered_v3.1.0.csv`) records.
  §4's base-rate figures are therefore measured on a *different* corpus and are
  corroborative, not confirmatory. §5.3's ceiling argument is corpus-independent and does
  cover the unknown corpus.
- **Whether that run used one model for both stages. [not established]** `model` is
  stage-overridable; the settings store for that run is not in evidence. (Provider is
  *not* overridable, so at least that was shared.)
- **The hardware half. [not established]** §4 explains the timing ratio by output length
  without needing VRAM pressure; it does not exclude it, and the coordinator's 8 s/call is
  well above the 2.7 s measured here. Neither of us can settle it from this repository.
- **Whether `[]` is qwen2.5-specific. [not established]** Wave 12's llama3.2 runs recorded
  `no_answer: 0` at batch 5. Model and batch size are not separated by any evidence I have.
- **`batch_size` was not probed.** All twelve calls were batch of one, matching the brief.
  The twelve-call budget was spent before this became the leading question, and I did not
  exceed it.
- **The prompt fix was not tested.** Whether "return one object per `a_id`, never an empty
  list" alone suffices — without `response_format` — is the cheapest untested hypothesis in
  the document.
- **No coverage instrument was run**, so the claim that F-12's headline is stale is an
  observation for the register owner, not a quantified finding.
- **`README.md` § "The document set" was not updated.** It lists 00–06 only; **07 and 08 are
  already missing from it**, and 09 will be too. Left alone deliberately — this session
  modified no existing file — and flagged here so it is not rediscovered as new.
- **Sub-agent verification was partial.** Six source investigations were run with an
  adversarial verifier each; at the time their output was consolidated only one verifier
  had reported, so five investigations informed this document unverified. Their specific
  unreliabilities are named in §9.

---
