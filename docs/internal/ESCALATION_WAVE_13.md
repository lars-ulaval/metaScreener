<!-- SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo -->
<!-- SPDX-License-Identifier: MIT -->

# Wave-13 escalation: three questions arising from the diagnostic

**Branch:** `diag/wave-13-criteria`, HEAD `fcc5493` at session start (parents `e45ac37`,
`42a5c42`/`post-wave-12`). **Date:** 2026-08-12. **Mode:** read-only.
**Test baseline:** 1600 passed, 7 skipped — before and after.
**Nothing was fixed.** No code, test, golden, register row, sample or user-facing
document was modified. This file is the only one added.

The brief's default path was `docs/internal/ESCALATION_WAVE_13.md`; that already
matches the `SCREAMING_SNAKE` convention of every other top-level file in
`docs/internal/`, so the path is unchanged.

## Network disclosure — read this first

Q1 was designed to need no key and no server, and the designed experiments needed
neither. **One experiment nevertheless sent a single HTTP request to a live Ollama
daemon already running on this machine, and I did not intend it to.** The full account
is in §Q1.4, because the *reason* it happened is itself a finding. In summary:

- I set `OPENAI_BASE_URL` to a localhost stub and ran the real EL engine.
- **The settings store's per-stage endpoint overrode the environment variable** — by
  design, per the F-91 family — and the run went to `http://localhost:11434/v1`.
- A daemon was listening. It returned **HTTP 404, `model 'gpt-4o-mini' not found`**.
  No model was loaded, no tokens were generated, no inference ran, nothing was
  pulled, and no cost was incurred anywhere.
- **I did not start Ollama.** It was already running. The previous session's claim
  that no daemon was started remains true; this session's is that one request reached
  one that was.
- No paid vendor API was contacted at any point. No API key was used: the only
  credential in play was the literal string `placeholder-not-a-real-key`.

I then redirected the settings directory and re-ran the experiment correctly against
the stub. Reporting this rather than quietly re-running is the point.

## Evidence conventions

As in `06_llm_integration.md` and `07_criteria_parsing.md`. `path::symbol` citations;
**no line numbers**. Markers: **[measured]** = executed in this session, command and
output shown; **[read]** = derived from source without executing; **[not established]**
= followed by what would settle it. Sub-agents: **none were used this session**; every
claim below is my own, from source or from execution. No agent deaths to report.

---

## Step 0 — gate

| Check | Expected | Actual | |
| --- | --- | --- | --- |
| `git rev-parse HEAD` | — | `fcc54937fa0a3b1c96319e86bdd571cdb85d2369` | ✅ |
| `git branch --show-current` | — | `diag/wave-13-criteria` | ✅ |
| `git status --porcelain` | empty | empty | ✅ |
| `e45ac37` on branch | yes | YES | ✅ |
| `fcc5493` on branch | yes | YES | ✅ |
| `git ls-files -s tests/golden` | — | 9 entries, Appendix A | ✅ |
| Full suite | 1600 passed, 7 skipped | `1600 passed, 7 skipped in 42.93s` | ✅ |

All six checks pass; the session proceeded.

---

## Corrections to the coordinator's brief

Per the standing rule, first.

### Correction 1 — Q1's premise is sound but its worry is unfounded. openai 3.0.0 does **not** break the shipped application.

The brief asks whether "an SDK major-version jump from 1.x to 3.x may have moved more
than a transport dependency." **[measured]** it moved nothing the shipped code
touches. Every symbol, every keyword argument, every exception class and the one
response attribute the application reads are identical between 1.106.0 and 3.0.0, and
the real EL engine completes a full criterion end-to-end under 3.0.0 with every
verdict usable. §Q1. **No Critical is warranted** and I decline to propose one.

### Correction 2 — Q2's hypothesis is confirmed, and understated.

The brief hypothesised that "EC-4's 112 exclusions sit inside that 125, meaning ~90%
of the published EH stage was performed by a rule that does not match its stated
criterion." **[measured]** they do, and the share is **89.6%** — 111 of the 125 EH
exclusions rest on EC-4 *alone*.

But the brief stops at the EH stage, and the consequence does not.
**[measured]** re-running the chain with EC-1 and EC-4 rendered as their prose labels
state gives **776 → 16 → 760 → 613 → 147**, against the published
**776 → 125 → 651 → 566 → 85**. **The published final set of 85 would have been 147.
Sixty-two records — 42% of the correct final set — were excluded by a rule that
matches nothing its own label describes.** The 85 is a strict subset of the 147; no
record goes the other way.

### Correction 3 — the two defects have very different blast radii, and one of them has none.

The brief treats EC-1 and EC-4 together. They are not comparable.
**[measured]** the 2 Spanish records EC-1 fails to remove are `A380` (year 1997) and
`A525` (year 2012). Both survive EH and both are removed at IH — by `IC-3`
(`equals lang English`) and `IC-4` (`gte year 2018`) together. **EC-1's truncation
changes the published output by exactly zero records**, and it could not have changed
it: `IC-3` requires English, so every non-English record dies at IH regardless.
EC-1 is functionally redundant with IC-3 on this corpus. **The entire 62-record
divergence is EC-4's.**

### Correction 4 — Q3's hypothesis is confirmed, and the fix is free; but the glob must be narrower than last session implied.

**[measured]** adding `docs/data/*.csv binary` changes **no committed bytes**, needs
**no** `git add --renormalize`, makes the freeze test pass (12 passed, was 3 failed),
and leaves the whole suite green in the simulated clone. §Q3.

**But my own previous session's suggestion was too broad and I am correcting it.**
`07_criteria_parsing.md` and `CI_FAILURE_WAVE_12.md` §7 floated a rule that would also
cover the extension-less `SHA256SUMS` manifests. **[measured]** `docs/data/eval_summary_v1.txt`
is **LF in the index and CRLF in the working tree**, and it passes today *because*
`tools/eval_ingest.py::write_summary_text` uses `Path.write_text` (platform-native) and
so matches whatever the checkout produced. **Making `docs/data/*` binary would break
it on Windows.** The rule must stay scoped to `*.csv`.

### Correction 5 — the brief's own framing of the coordinator's error rate.

The brief says he "was wrong three times in the last round." Of the corrections I
recorded, the CI fork was the substantive one; the others were an imprecise file
location and an incomplete enumeration. This round: **Q2 and Q3 are both confirmed**,
and Q1's premise is sound while its worry is not. Recording this because a register of
corrections that only ever grows is not a calibration.

---

## Q1 — does openai 3.0.0 break the shipped application, or only the tests?

**Answer: only the tests. [measured], four independent ways.**

### Q1a — every shipped-code touch of the SDK

**[read]**, `path::symbol`. "Shipped" excludes `tests/` and `tools/`.

| Site | What it does |
| --- | --- |
| `plugins/_common/llm_client.py::_openai_client_for` | `from openai import OpenAI` (lazy), then `OpenAI(api_key=placeholder_key_for(...), base_url=cfg.endpoint)`. **The only client constructor for EL/IL and the harmoniser.** |
| `plugins/_common/llm_client.py::run_m1_llm_for_criterion` (inner `_call_once`) | `client.chat.completions.create(model=, messages=, temperature=)`; reads `resp.choices[0].message.content`. |
| `plugins/_common/llm_client.py::_openai_error_types` | `import openai` (lazy), then `getattr(openai, name, None)` over a **7-name enumeration**. |
| `plugins/_common/llm_client.py::_classify_llm_error` | Consumes that dict; falls back to `getattr(e, "status_code", None)`, then to message regexes. |
| `plugins/_common/llm_client.py::resolve_openai_base_url`, `::OPENAI_BASE_URL_ENV`, `::DEFAULT_OPENAI_BASE_URL` | Endpoint resolution (wave 9). Reads `OPENAI_BASE_URL` from the environment; passes `base_url=` explicitly. |
| `plugins/_common/llm_client.py::_stage_config`, `::_has_openai_key` | Read `OPENAI_BASE_URL` / `OPENAI_API_KEY`; no SDK use. |
| `plugins/03_harmoniser/llm_refine.py::_call_openai_json` | Second `.create()` site, through the same `_openai_client_for`. Reads `resp.choices[0].message.content`. **Now live (F-146).** |
| `plugins/03_harmoniser/llm_refine.py::_sdk_importable` | `import openai`, then `from openai import OpenAI`, for a GUI gate only. |
| `plugins/01_reference_extractor/original/prisma_citations_ai_v3_1.py` | Legacy plugin 01: module-level `from openai import OpenAI`, `OpenAI(api_key=os.environ["OPENAI_API_KEY"])`, a third `.create()`. Bypasses all wave-9/11 plumbing. |
| `plugins/02_references_of_x/core.py` | `from openai import OpenAI` behind an `OPENAI_OK` flag; optional AI fallback. |

**Not the SDK, and therefore immune to its version — an important negative result.**
**[read]** `plugins/_common/provider_detect.py` and `plugins/_common/model_pull.py` use
stdlib `urllib.request` only. Provider detection, readiness probing and model pulling
cannot be affected by an `openai` major at all.

**Enumeration check (ground rule 8).** `_openai_error_types`'s 7 names —
`RateLimitError, BadRequestError, AuthenticationError, PermissionDeniedError,
NotFoundError, APITimeoutError, APIConnectionError` — have **exactly one second copy**,
in `tests/test_error_classification.py`. (A grep also hits `FileNotFoundError` in five
files; those are the Python builtin, not this list.) The second copy lives in **the very
file that fails to collect under openai 3.0.0** — so if a class were renamed, the
shipped classifier would degrade silently *and* the test that would have caught it
would not run. That coupling is the real hazard here, and it is why Q1d mattered.

### Q1b — the API surface, 1.106.0 versus 3.0.0

**[measured]** `%TEMP%\q1_probe.py`, pure introspection, run under the local 1.x and
under a throwaway venv containing `openai==3.0.0` alone.

| Check | 1.106.0 | 3.0.0 |
| --- | --- | --- |
| `from openai import OpenAI` | OK | **OK** |
| `__init__` accepts `api_key=` / `base_url=` / `timeout=` | True / True / True | **True / True / True** |
| `__init__` reads `OPENAI_BASE_URL` / `OPENAI_API_KEY` | True / True | **True / True** |
| `client.chat.completions.create` exists | OK | **OK** |
| `create` accepts `model` / `messages` / `temperature` / `timeout` | all True | **all True** |
| all 7 exception classes present on `openai` | MISSING: none | **MISSING: none** |
| `APITimeoutError` subclasses `APIConnectionError` | True | **True** |
| `openai.ChatCompletion` still present as a raising proxy | True | **True** |

3.0.0 *adds* constructor parameters (`admin_api_key`, `workload_identity`, `provider`).
Additive only. Nothing the shipped code passes was removed or renamed.

### Q1c — the decisive call

**[measured]** `%TEMP%\q1_call.py`: construct exactly as `_openai_client_for` does
(only `api_key` and `base_url`), then issue exactly `_call_once`'s kwargs against
`http://127.0.0.1:49999/v1`, where nothing listens. Dummy key, no network egress.

```
########## SUBJECT: openai 3.0.0 ##########      ########## CONTROL: openai 1.106.0 ##########
construction: OK -> OpenAI                       construction: OK -> OpenAI
call raised: openai.APIConnectionError           call raised: openai.APIConnectionError
             message: Connection error.                       message: Connection error.
  is APIConnectionError : True                     is APIConnectionError : True
  is TypeError          : False                    is TypeError          : False
  is AttributeError     : False                    is AttributeError     : False
  _classify_llm_error resort-1 verdict:            _classify_llm_error resort-1 verdict:
      ('transport', 'type')                            ('transport', 'type')
```

**Byte-for-byte the same outcome.** A `ConnectionError`, per the brief's own test, means
construction and call signature survived. No `TypeError`, no `AttributeError`, no
`ImportError`.

### Q1d — does the wave-8 classifier still fire? Yes, and I have it firing twice on real errors.

**[measured]** twice, under 3.0.0:

1. Against the closed port: `openai.APIConnectionError` → `('transport', 'type')`.
   Resort 1 (by type) answered; no fall-through to message sniffing.
2. Against the live Ollama daemon (§Q1.4), which returned a real HTTP 404 with a
   JSON error body, the **shipped** `run_m1_llm_for_criterion` logged, verbatim:

   ```
   [EL-LLM] batch 1/1 failed [not_found, by type]: Error code: 404 -
   {'error': {'message': "model 'gpt-4o-mini' not found", 'type': 'not_found_error', ...}}
   ```

   `[not_found, by type]` is `_classify_llm_error` returning `("not_found", "type")` —
   resort 1, from `openai.NotFoundError`, under openai 3.0.0. And the fail-safe held:
   all 5 records came back `used: False, decision: uncertain, confidence: 0.0`, i.e.
   flagged rather than excluded, with `stats: {'calls_made': 1, 'calls_failed': 1,
   'batches_failed': 1}`.

**The wave-8 defect is not reintroduced.** The classifier's type-based resort is intact
because all seven classes still exist at the same module path.

One caveat on my own probe: check `[7]` reported `APIStatusError.status_code` absent in
**both** versions. That is because I inspected the *class*, not an instance;
`_classify_llm_error` reads `getattr(e, "status_code", None)` on the instance, which is
correct. The 404 above proves the instance path works. My check was mis-aimed, not a
finding.

### Q1.4 — the end-to-end run, and the accidental Ollama contact

**[measured]** `%TEMP%\q1_e2e.py` stands up a stdlib `http.server` on `127.0.0.1:47311`
speaking the OpenAI chat-completions shape, then calls the real
`plugins/_common/llm_client.py::run_m1_llm_for_criterion` with the real
`plugins/06_el/prompt.py::_build_llm_messages_for_criterion`.

**First attempt — misdirected.** With `OPENAI_BASE_URL` set to the stub,
`resolve_openai_base_url("EL")` returned **`http://localhost:11434/v1`**. The stub
received **0** requests. The reason is by design: **[read]**
`plugins/_common/settings.py::resolve_stage`'s documented endpoint order puts *"an
explicitly configured endpoint — the stage override, then the application setting"*
first, precisely so *"anything in the environment beating it would make the control the
user just operated do nothing (F-91's family)"*. This machine's settings store has a
stored endpoint; it won. A daemon was listening and answered 404. That is the whole
incident, and Q1d above is what it bought.

**Second attempt — correct.** `plugins/_common/settings.py::settings_dir` addresses the
store through `APPDATA` on Windows, so redirecting `APPDATA` to an empty temp directory
leaves the store empty and lets the environment resolve:

```
openai: 3.0.0
resolve_openai_base_url('EL') -> http://127.0.0.1:47311/v1
_openai_client_for('EL') -> OpenAI base_url= http://127.0.0.1:47311/v1/
PROMPT_VERSION: EL_v1_jsonlist
HTTP requests the stub received: 1
  path       : /v1/chat/completions
  body keys  : ['messages', 'model', 'temperature']
verdicts returned: 5
   ('A001','EC-2') -> {'used': True, 'decision': 'meet', 'confidence': 0.91,
                       'field': 'title', 'valid_quote': True}
stats: {'calls_made': 1}
END-TO-END RESULT: PASS — the EL stage completed and every verdict was usable
```

Under the 1.106.0 control, against the working tree: **identical** — same
`body keys ['messages','model','temperature']`, same 33-character `Authorization`
header, same five usable verdicts, same `stats: {'calls_made': 1}`, same PASS.

This exercises the whole path a version bump could have broken: client construction,
endpoint resolution, the HTTP request shape, `resp.choices[0].message.content`,
`_parse_llm_json_array`, and the evidence gate.

Two incidental confirmations. The request body carries **exactly three keys**, which is
`06_llm_integration.md`'s fact 1 measured again under a new SDK major. And the
`Authorization` header **is** sent under 3.0.0 — my first run reported it absent
because 3.0.0 emits the name lower-cased and I had flattened the headers into a
case-sensitive `dict`. My error; there is no auth regression.

### Q1e — can a fresh install run an EL stage today?

**Yes. [measured]** — subject to the one caveat that this was measured against an
OpenAI-*compatible* localhost endpoint rather than `api.openai.com`, because contacting
the vendor is forbidden here and would cost money. What that leaves **[not established]**
is only vendor-side behaviour — authentication, rate limits, model availability — none
of which is a function of the SDK surface this question asks about. Everything the SDK
mediates is established.

**No Critical is warranted, and no new severity is proposed for the application.** The
defect established last session stands unchanged and unenlarged: two *test* modules
import an undeclared `httpx`. `pip install metascreener-lars-ulaval` gives a user a
working application; it gives a *contributor* a suite that cannot collect. That is a
`Medium`, in the F-15 family, and the one-line fix (declare `httpx` in the `dev`
extra) is already verified by execution.

The genuine residual risk is narrower than the brief feared and worth stating plainly:
`openai>=1.40.0` with no upper bound means **the next major could break the
application, and nothing in CI would tell you first** — because CI installs the same
unbounded range at the same moment your users do. This time the roll of the dice came
up harmless.

---

## Q2 — blast radius of EC-1 and EC-4 against published claims

### Q2a — the chain, re-run with attribution

**[measured]** `%TEMP%\q2_chain.py`: the real `plugins/_common/parser.py::_parse_csv_tolerant_text`,
`::_load_criteria_from_text` and `plugins/_common/runner.py::run_screen`, over
`samples/20260122_1654_aggregate.csv` with the **frozen** table
`docs/data/study_input/criteria_harmonized_v3.1.0.csv`.

```
parsed corpus: 776 integral rows, 0 skipped

STAGE EH — input 776 records, 2 criteria
  outcomes: {'OUT': 125, 'PASS_CLEAN': 651, 'PASS_FLAGGED': 0, 'NOT_SCREENED': 0}
    EC-1  equals   lang      ['French']       failed=14   missing=0  met=762
    EC-4  equals   doc_type  ['conference']   failed=112  missing=0  met=664
  OUT attribution by exact failing-criterion set:
    EC-4                     111
    EC-1                      13
    EC-1+EC-4                  1
    TOTAL                    125   (must equal OUT=125)

STAGE IH — input 651 records, 2 criteria
  outcomes: {'OUT': 566, 'PASS_CLEAN': 85, 'PASS_FLAGGED': 0, 'NOT_SCREENED': 0}
    IC-3  equals   lang   ['English']  failed=10   missing=0  met=641
    IC-4  gte      year   ['2018']     failed=564  missing=1   met=86
  OUT attribution by exact failing-criterion set:
    IC-4                     556
    IC-3+IC-4                  8
    IC-3                       2
    TOTAL                    566   (must equal OUT=566)
```

**Reconciliation — every published figure reproduces exactly:**

| | measured | published | |
| --- | --- | --- | --- |
| corpus rows | 776 | 776 | ✅ |
| EH excludes | 125 | 125 | ✅ |
| EH survivors | 651 | 651 | ✅ |
| IH excludes | 566 | 566 | ✅ |
| IH survivors | **85** | 85 | ✅ |

**The hypothesis is confirmed.** EC-4 fired on 112 records and is the *sole* reason 111
were removed. **112 / 125 = 89.6% of the published EH stage.** The 1 overlap record is
both French and a conference paper.

**IH is clean.** `IC-3` (`equals lang English`) and `IC-4` (`gte year 2018`) both render
their labels faithfully. Every defect in the deterministic funnel is at EH.
`IC-4`'s `missing=1` is one record with no `year`, correctly not excluded.

### Q2b — the eight rows, declared / executed / executed as labelled

**[measured]**, combining this session's chain run with `07_criteria_parsing.md` §7.

| id | prose label (abbreviated) | emitted rule | stage | executes? | matches label? |
| --- | --- | --- | --- | --- | --- |
| IC-1 | considers immersive VR **or** HMD simulation | `llm` keywords | IL | yes | yes — routed to a model, which sees the whole sentence |
| IC-3 | written in English | `equals lang English` | IH | yes | **yes** |
| IC-4 | publication year is 2018 or later | `gte year 2018` | IH | yes | **yes** |
| IC-5 | title/abstract/keywords mention training **or** vocational **or** workplace | `contains title,abstract,keywords [3 terms]` | IL | **NO** | operands correct, stage cannot run it (F-65) |
| EC-1 | written in French **or Spanish** | `equals lang French` | EH | yes | **NO — "Spanish" discarded** |
| EC-2 | primary focus is spatial navigation in a virtual maze | `llm` keywords | EL | yes | yes |
| EC-3 | primary focus is the rubber hand illusion | `llm` keywords | EL | yes | yes |
| EC-4 | **venue** contains "ICRA" **or** "IROS" (robotics conference proceedings) | `equals doc_type conference` | EH | yes | **NO — wrong column, both operands discarded** |

**Totals, mine not the coordinator's: 8 declared; 7 executed; 5 executed as labelled.**
Three rows fail, by three different mechanisms, and **[measured]** all eight validate
with zero errors and zero warnings.

### Q2c — the two Spanish records

**[measured]**

| local_id | lang | year | doc_type | title | survived EH | in final 85 |
| --- | --- | --- | --- | --- | --- | --- |
| `A380` | es | 1997 | book | *Introducción a la lingüística del texto* | **yes** (`failed=[]`) | **no** |
| `A525` | es | 2012 | book | *Education for Life and Work: Developing Transferable Knowledge and Skills in the 21st Century* | **yes** (`failed=[]`) | **no** |

Both survive EH because `equals lang French` cannot see them, and both are removed at
IH by `IC-3` and `IC-4` together — they are two of the 8 records in the `IC-3+IC-4`
group. **Neither appears in any published table or figure**: they are absent from
`docs/data/study_input/el_input_v3.1.0.csv` (the frozen 85), so they never reached EL or
IL, and the LLM-side tables are drawn from that set.

**So EC-1's blast radius on published output is zero**, and structurally could not have
been otherwise: `IC-3` requires English, which subsumes any exclusion of a non-English
language. EC-1 is redundant with IC-3 on this corpus whether truncated or not.
Recording this as a *mitigation*, prominently, because the defect is real and its
consequence here is nil, and conflating those would be its own error.

### Q2d — the blast radius that is not zero

**[measured]** `%TEMP%\q2_counterfactual.py` re-runs the chain with EC-1 and EC-4
rendered as their prose labels state. Both replacement operators already exist and are
tested in `plugins/_common/evaluator.py`:

- EC-1 → `in_list lang [French, Spanish]`
- EC-4 → `contains venue [ICRA, IROS]`

```
AS SHIPPED (the frozen study input)
  EH: in=776  OUT=125  survivors=651
      EC-1  equals   lang     ['French']              failed=14   missing=0
      EC-4  equals   doc_type ['conference']          failed=112  missing=0
  IH: in=651  OUT=566  survivors=85
  CHAIN: 776 -> EH -125 -> 651 -> IH -566 -> 85

COUNTERFACTUAL — EC-1 and EC-4 as their prose labels state
  EH: in=776  OUT=16   survivors=760
      EC-1  in_list  lang     ['French', 'Spanish']   failed=16   missing=0
      EC-4  contains venue    ['ICRA', 'IROS']        failed=0    missing=126
  IH: in=760  OUT=613  survivors=147
  CHAIN: 776 -> EH -16 -> 760 -> IH -613 -> 147

BLAST RADIUS ON THE PUBLISHED FINAL SET
  final set as shipped        : 85 records  (published 85)
  final set as labelled       : 147 records
  in labelled but NOT shipped : 62
  in shipped but NOT labelled : 0
  85 subset of 147            : True
  the 62 extra records, by doc_type: {'conference': 62}
  by lang: {'en': 62}
  year range: 2018 .. 2022
```

**The faithful EC-4 excludes nothing from this corpus** — `failed=0`, and its
`missing=126` is the 126 records with an empty `venue`, correctly not excluded. Zero
records have a venue containing `ICRA` or `IROS`.

**Sixty-two records — all English conference papers from 2018–2022 — were excluded from
the published demonstration by a rule that matches nothing its label describes.** That
is 42% of the 147 the stated criteria would have retained. The venues are exactly the
ones a VR/HMD workplace-training review would want: CHI 2019–2021, IEEE VR, ISMAR,
Augmented Human, Mensch und Computer.

**One epistemic caveat, stated because it changes what the human should conclude.** The
counterfactual measures the criterion as **stated**. EC-4's label ends with the
parenthetical *"(robotics conference proceedings)"*, and a reader could argue the
*intent* was to exclude robotics conference papers generally — in which case the
harmoniser's substitution was an over-generalisation of a real intent rather than an
invention. Either way it excludes 112 where the stated rule excludes 0, and only the
author knows which reading was meant. **HO-13-8.**

### Q2e — the published claims, quoted. Report only.

**No decision about any published claim is made here.** That is the human's, and the
brief is explicit that it is neither mine nor the coordinator's.

**`README.md`**, the abstract paragraph:

> In a demonstration use case comprising 776 candidate records, the pipeline reduced the
> corpus to 73 records requiring full human review — a 90.6% reduction — with
> deterministic pre-filtering accounting for 98.3% of exclusions.

**`docs/llm-evaluation.md`**, § *What was measured*:

> One corpus, three runs of the EL stage, all reaching that stage through identical
> deterministic screening:
>
>     776 records → EH excludes 125 → 651 → IH excludes 566 → 85
>
> That funnel reproduced **exactly** in every run, record for record

**`docs/llm-evaluation.md`**, § *The deterministic stages reproduce exactly*:

> The two heuristic stages give bit-identical results across every run we have: 776
> records → EH excludes 125 → 651 → IH excludes 566 of those → **85**. The set of 85 is
> not merely the same size but the same records […] Those 691 exclusions are 98.3% of
> the 703 total the README reports — the deterministic share the manuscript claims is
> exactly the share the goldens contain.
>
> This is the majority of the pipeline's work, and it is fully […]

**`docs/faq.md`**, § *How much will an LLM-stage run cost?*:

> On the bundled demonstration corpus (776 records), only 85 reach EL and 84 reach IL

**`docs/usage.md`**, § *Inferred assignments* — the sharpest one, because it describes
the defective row and gets it wrong:

> - IC-5 (keywords) -> `IH` / `keyword_in_text`,
> - EC-1 (French/Spanish) -> `EH` / `language`,
> - EC-4 (venue contains ICRA or IROS) -> `EH` / `venue`,

**[measured]** the committed golden says IC-5 → `IL`/`contains` and EC-4 →
`EH`/`doc_type`. The document tells a reader that EC-4 filters on **venue**. It does
not; it filters on `doc_type`, which is the entire defect. `keyword_in_text`,
`language` and `venue` are not operators in any version of the code.

**`docs/data/study_input/study_input.meta.txt`**: records `corpus_records=776` and
`frozen_from_commit=4fbe8fd…`. It makes no claim about the criteria's semantics.

**`.zenodo.json` and `CITATION.cff`**: neither cites the funnel numbers nor the
criteria. Both describe the architecture only — *"integrates deterministic rule-based
filters with large language model (LLM) inference"*. **No numeric claim in the archived
metadata is affected.**

**The observation that ties these together, and it is the finding rather than any single
quote:** every document leans on the deterministic stages as the *trustworthy* half —
"reproduced **exactly**", "bit-identical", "fully reproducible", "the majority of the
pipeline's work" — and contrasts them with the LLM stages, which are hedged carefully
(80 versus 73, non-determinism, F-155). **Reproducibility was measured; correctness was
not.** The funnel reproduces bit-identically *and* 111 of its 125 EH exclusions rest on
a rule matching nothing its label describes. A deterministic stage is reproducibly
wrong, which is worse than variably right for exactly the reason the documents give for
trusting it.

### Q2f — no paper in the tree

**[measured]** `git ls-files` matched nothing for `paper|manuscript|jors|submission|cover.?letter|response.?to|reviewer|\.tex|\.docx|\.pdf`. **There is no copy of the JORS
paper, no manuscript, no cover letter and no response-to-reviewers anywhere in the
repository.** The tracked non-code files are the ones listed in Q2e plus `Dockerfile`,
`LICENSE`, `.env.example`, `docker_test.sh` and the `docs/` tree.

So **whether the published record is affected cannot be determined from this
repository.** `README.md` references "the manuscript's reported result" and a DOI, and
`docs/llm-evaluation.md` speaks of "the manuscript figure" and "the deterministic share
the manuscript claims", so a manuscript exists outside the tree. **HO-13-7.**

### Q2g — duplication sweep against the register

**[measured]** `docs/internal/diagnostic/03_findings.md`, 160 rows, maximum ID
**F-163** (re-confirmed this session).

| Probe | Hits | Reading |
| --- | --- | --- |
| `doc_type` | **0** | nothing anywhere questions EC-4's target column |
| `over-exclud`, `false exclusion` | **0** | no row frames any stage as over-excluding |
| `651`, `566` | 1 each | inside F-159's evidence list, as reproduced figures |
| `125` | 12 | all as a reproduced count, never as a questioned one |
| `funnel` | 3 | reproducibility of the funnel, never its correctness |
| `Spanish`, `ICRA`, `compound` | 0 / 0 / 5 | the five `compound` hits are ordinary English |

**F-65 does not cover any of this.** F-65 is the stage/operator pairing defect — IC-5.
EC-1 and EC-4 execute perfectly well at their assigned stage; what is wrong is *what
they execute*. No register row addresses the correctness of a rendered criterion, and
none addresses the funnel's correctness as distinct from its reproducibility.

**Candidate findings, continuing last session's `D-` sequence. Not register rows; the
register was not edited.**

| ID | Proposed severity | Mechanism | Evidence | Duplication |
| --- | --- | --- | --- | --- |
| **D-11** | **Critical** | **The published demonstration funnel excludes 62 records — 42% of what its own stated criteria retain — because EC-4 was rendered against `doc_type` instead of `venue`, with both operands discarded.** 111 of 125 EH exclusions rest on it alone. | Q2a, Q2d. Chain reproduces 776→125→651→566→85; counterfactual gives 776→16→760→613→147; 85 ⊂ 147; the 62 are all English conference papers 2018–2022. | **Novel.** `doc_type` has zero register hits. Distinct from F-65 (pairing, not content). This is the first row to question the funnel's *correctness*. |
| **D-12** | **High** (documentation) | **Five documents present the deterministic stages as the trustworthy half on the strength of reproducibility, which is not correctness.** The hedging is all on the LLM side; the defect is all on the deterministic side. | Q2e quotes from `README.md`, `docs/llm-evaluation.md` ×2, `docs/faq.md`. | **Novel as framed.** Adjacent to F-17 (stale test counts) and F-16 (usage.md report files), neither of which is about this. |
| **D-13** | **Medium** (documentation) | **`docs/usage.md` states EC-4 targets `venue`; the committed golden says `doc_type`.** The document describes the defective row correctly-as-intended and incorrectly-as-built. | Q2e. | **Extend last session's D-6** rather than open new — same passage, same paragraph. Flagging because D-6 was scoped to the operator vocabulary and IC-5, and this is a third falsified line in it. |
| **D-14** | **Low** | **A stored per-stage endpoint silently overrides `OPENAI_BASE_URL`, and nothing tells the operator.** By design (F-91 family) and correct as a precedence rule, but undocumented in any user-facing file, and it redirected an experiment in this session to a live local daemon. | Q1.4. `resolve_stage`'s docstring states the order; `docs/usage.md` and `docs/faq.md` do not. | **Novel.** Adjacent to F-37 (env-var documentation). Possibly best folded there. |

**Recorded as a mitigation, not a finding:** EC-1's truncation changes zero published
records and structurally cannot change any, because IC-3 subsumes it (Q2c).

---

## Q3 — what would the `.gitattributes` fix actually cost?

**Answer: one line, zero committed bytes, no renormalize. The hypothesis is confirmed.**

### Q3a — what the index holds

**[measured]** `git cat-file blob HEAD:<path>` against working-tree bytes:

| file | index | working tree | identical? |
| --- | --- | --- | --- |
| `docs/data/eval_decisions_v1.csv` | CRLF=0 LF=345 | CRLF=0 LF=345 | **yes** |
| `docs/data/eval_results_v1.csv` | CRLF=0 LF=345 | CRLF=0 LF=345 | **yes** |
| `docs/data/eval_disagreements_v1.csv` | CRLF=0 LF=89 | CRLF=0 LF=89 | **yes** |
| `docs/data/eval_summary_v1.txt` | **CRLF=0 LF=62** | **CRLF=62 LF=0** | **NO** |

**The index holds LF for all four.** The three CSVs happen to match in this working tree
(which is why the suite passes here and failed in a fresh clone); the `.txt` does not,
and `git status` still reports clean because the dirty check normalises before
comparing. That is precisely how this hid for two days.

### Q3b — the simulated change

**[measured]** throwaway clone in `%TEMP%\q3_sim`, `core.autocrlf=true`. Fresh checkout
gives CRLF for all four. Then `docs/data/*.csv binary` appended, and the data
re-checked-out:

```
=== RE-CHECKOUT the CSVs under the new rule ===
  eval_decisions_v1.csv       CRLF=0  LFonly=345
  eval_results_v1.csv         CRLF=0  LFonly=345
  eval_disagreements_v1.csv   CRLF=0  LFonly=89
  eval_summary_v1.txt         CRLF=62 LFonly=0     <- untouched, correctly out of scope

=== git status --porcelain ===
 M .gitattributes                                  <- and nothing else

=== git add --renormalize . ===
M  .gitattributes
--- diff --cached --stat ---
 .gitattributes | 3 ++-
 1 file changed, 2 insertions(+), 1 deletion(-)
```

**No data file is modified. `--renormalize` alters no blob.** And the fix works:

```
$ python -m pytest tests/test_study_input_freeze.py -q
12 passed in 0.46s                    (was: 3 failed)

$ python -m pytest -q
1600 passed, 7 skipped in 43.72s
```

### Q3c — the cost, in one line

**Free.** One line in `.gitattributes`; zero files under `docs/data/` change committed
bytes; no `--renormalize`; the frozen wave-12 and study-input evidence is untouched; and
the freeze test passes in a fresh Windows clone.

Two conditions on that, both established above rather than assumed. **The glob must be
`docs/data/*.csv`, not `docs/data/*`** — `eval_summary_v1.txt` passes today only because
its writer is platform-native and matches whatever the checkout produced, so making it
binary would break it on Windows (Correction 4). And **existing Windows working trees
whose CSVs are already CRLF will not self-heal on `git pull`**; they need one
`git checkout -- docs/data/` or a `--renormalize`, which changes no blob but does rewrite
those working-tree files.

The alternative — making the test line-ending-agnostic — is **not** recommended, for the
reason last session gave: the test exists to back a published claim that a named command
reproduces the artefacts *byte-for-byte*, and weakening the comparison to
byte-for-byte-modulo-line-endings makes the test stop verifying the sentence it was
written for. The trade-off is that the attribute fix is per-repository configuration
(invisible in a tarball or a Zenodo archive, which have no `.gitattributes` semantics)
while the test change travels with the code. Since the byte-identity claim is the
scientific asset, configuration is the right place for the fix.

### Q3d — cell coverage, confirmed

**[measured]** last session, restated and unchanged:

| Cause | Cells | Live from | Status |
| --- | --- | --- | --- |
| Undeclared `httpx`, triggered by `openai` 3.0.0 | **16 of 16**, collection-fatal | 2026-08-12T01:56Z | ESTABLISHED for `42a5c42` from per-cell API data + local reproduction |
| `docs/data/*.csv` CRLF vs an LF-pinned writer | **4 of 16** (Windows only) | 2026-08-10T12:58Z | Windows arm EXECUTED; non-Windows arm READ from `lineterminator="\n"` |

**Between them they account for all 16 cells — but not simultaneously, and that
qualification is load-bearing.** For the last two red runs (`7a39eda`, `42a5c42`) cause 1
alone accounts for all 16, and masks cause 2 by failing at collection. For the first
five (`bef2c0b` … `8b5a972`) only cause 2 was live, so only 4 cells can have been
failing — and **[not established]**, because the API capture carries per-job detail for
`42a5c42` only. A GitHub run is `failure` if any cell fails, so a 4-cell failure is
fully consistent with the observed conclusions. I have not represented that as
established and do not now.

Fixing both is two independent one-line changes: `httpx` into the `dev` extra, and
`docs/data/*.csv binary`. Neither touches `tests/golden/**`.

---

## Handoffs

**HO-13-7 — Does the JORS paper describe these criteria by their prose labels, and does it report the 776/125/651/566/85 chain?**
No copy of the paper exists in the repository (Q2f). This is the one question that
settles whether the published record is affected by D-11, and only the human can answer
it. Specifically: (a) does the paper, or its supplementary material, list the exclusion
criteria as prose — in particular EC-4 as *"venue contains ICRA or IROS"*? (b) does it
report the deterministic chain, the 85, the 73, or the "98.3% of exclusions" figure?
(c) is there a data-availability statement pointing at
`docs/data/study_input/`? If (a) and (b) are both yes, the paper describes a screening
step that its own released artefacts show was not performed as described, and the
remedy is an author decision — correction, corrigendum, or an erratum note — not a code
change.

**HO-13-8 — What did EC-4 actually mean?**
The label is *"The publication venue contains "ICRA" OR "IROS" (robotics conference
proceedings)."* Two readings: **(i)** literal — exclude papers from those two venues,
which on this corpus excludes 0 records; **(ii)** the parenthetical as the real intent —
exclude robotics conference proceedings, which is narrower than "all conference papers"
but broader than two venues. The harmoniser implemented a third thing: all conference
papers, 112 records. **Question:** which did you mean when you wrote it? The answer
decides whether D-11 is "the tool silently substituted a different criterion" or "the
tool silently over-generalised a real one" — and it decides what the corrected number
is. Note that neither reading yields 112.

**HO-13-9 — Which endpoint is stored for the EL stage on the maintainer's machine?**
Q1.4 found a stored per-stage endpoint of `http://localhost:11434/v1` overriding the
environment, and an Ollama daemon answering on it. **Question:** open the provider/LLM
settings for EL and IL and report what endpoint and model each shows. This matters for
two reasons beyond this session's accident: it tells you whether the machine that
produced the wave-12 measurements is still pointed where those runs assumed, and it is
the user-visible half of D-14.

**HO-13-10 — Would a reader of `docs/usage.md` § *Inferred assignments* notice the table is wrong?**
That passage lists EC-4 → `EH`/`venue` beside a screenshot,
`docs/images/usage/plugin03_criteria_parser.png`. **Question:** does the screenshot show
the *actual* harmonised table — i.e. does it visibly show `doc_type`/`conference` for
EC-4, contradicting the prose three lines below it? If the image already contains the
correct value, the document contradicts itself on the same screen, which changes how
urgent D-13 is.

---

## What was not done

- **Nothing was fixed.** No code, test, golden, register row, sample or user-facing
  document was modified. No register row was added: D-11…D-14 are candidates.
- **No decision was taken about any published claim.** Q2e quotes; it does not
  recommend. That call is the human's, and HO-13-7 is what it needs first.
- **No paid vendor API was called and no API key was used.** No OpenAI network call was
  made. One unintended request reached a local Ollama daemon and was refused with a 404
  before any inference; the full account is in the network disclosure and §Q1.4.
- **No Ollama run was started**, and none is needed for anything above. For
  completeness: the T3 wall-clock figure from `07_criteria_parsing.md` §8.3 remains
  **[not established]** and still needs one, which would settle only how much slower
  batch 1 is — not whether it is safer, which F-154 already establishes.
- **Vendor-side behaviour under openai 3.0.0 is [not established]** (Q1e): the
  end-to-end run used an OpenAI-compatible localhost endpoint. Everything the SDK
  surface mediates is established; authentication and rate-limit behaviour against
  `api.openai.com` is not, and testing it would cost money.
- **The counterfactual measures the criterion as stated, not as intended.** HO-13-8 is
  the difference, and until it is answered the "correct" final count is 147 under the
  literal reading and unknown under the other.
- **No sub-agents were used.** Every claim here is mine, from source or execution.
- **The GUI was not observed.** Four handoffs, HO-13-7 … HO-13-10.

## Appendix A — golden listing, for wrap-up re-verification

```
100644 0328bfd9bd5ccc8569ceb22db8bf4e6f4891d0ee 0	tests/golden/criteria_harmonized_v3.1.0.csv
100644 a325c349ba6646707e88f5bff95d0f6952ae2ed6 0	tests/golden/eh_filtered_v3.1.0.csv
100644 e8287eb10ebea1e1cb8f150056aca80c686c4372 0	tests/golden/el_cache_v3.1.0.json
100644 75dd27279c019ef7a3d3b69f3ffa3998b7f4c61f 0	tests/golden/el_filtered_v3.1.0.csv
100644 b0198c6373303137913b4d1356f0a7632623b425 0	tests/golden/el_input_v3.1.0.csv
100644 2cb4cb8314aebdecdade62d15883ec544216895d 0	tests/golden/ih_filtered_v3.1.0.csv
100644 2d0976853c23f0bc4bed2e305da93dad81dc7a97 0	tests/golden/il_cache_v3.1.0.json
100644 96b3028ba005d07cbee55896dcf1b0ae282b0593 0	tests/golden/il_filtered_v3.1.0.csv
100644 85e7edb40ec3364f7fbb653ddaed12b5dd4085df 0	tests/golden/il_input_v3.1.0.csv
```

## Appendix B — reproduction

Scratch paths only; nothing was written inside the repository tree.

```bash
# Q1b — API surface, both versions
python -m venv "$TEMP/q1_venv30" && "$TEMP/q1_venv30/Scripts/python" -m pip install "openai==3.0.0"
python "$TEMP/q1_probe.py"                       # control, local 1.106.0
"$TEMP/q1_venv30/Scripts/python" "$TEMP/q1_probe.py"

# Q1c — the decisive call, closed port
"$TEMP/q1_venv30/Scripts/python" "$TEMP/q1_call.py"

# Q1.4 — end-to-end against a localhost stub. APPDATA MUST be redirected, or a
# stored per-stage endpoint wins and the run goes wherever that points.
APPDATA="$TEMP/q1_appdata" "$TEMP/ci_probe_w13/.venv_ci/Scripts/python" "$TEMP/q1_e2e.py" "$TEMP/ci_probe_w13"

# Q2 — the chain, and the counterfactual
python "$TEMP/q2_chain.py"
python "$TEMP/q2_counterfactual.py"

# Q3 — simulate the attribute change
git clone <repo> "$TEMP/q3_sim" && cd "$TEMP/q3_sim"
git config core.autocrlf true
printf '\ndocs/data/*.csv binary\n' >> .gitattributes
rm -f docs/data/eval_*.csv && git checkout -- docs/data/
git status --porcelain          # only .gitattributes
git add --renormalize . && git diff --cached --stat   # only .gitattributes
python -m pytest tests/test_study_input_freeze.py -q  # 12 passed
```
