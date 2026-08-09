# 06 — LLM integration

*Read-only diagnostic of how this repository actually drives a language model
today, and what stands between here and two future destinations: model
identification without a hand-maintained list, and local no-API-call inference as
the default path.*

**Repository state:** `main` @ `f952e69`, working tree clean, `origin/main` in
sync (0 ahead, 0 behind). HEAD matches the coordinator's ledger exactly; there
were no gap commits to classify.
**Date:** 2026-08-09. **Mode:** read-only. No source, test, golden, tool, spec,
register or changelog file was modified; this document is the only file added.
**Test baseline:** 422 passed, 4 skipped — before and after.
**Network:** none. No package was installed, no model weights downloaded, no LLM
endpoint contacted (local or remote), no server or daemon started. One zero-cost
local check was permitted and performed: `ollama` **is** on PATH at
`C:\Users\alere\AppData\Local\Programs\Ollama\ollama`, **version 0.32.6**;
`lms`, `llama-server` and `llama-cli` are not. No daemon was started and no model
pulled.

**Citation convention.** Claims are anchored on `path::symbol` — module path plus
function or class name. Line numbers appear only as a secondary aid and are
marked *as of `f952e69`*. This deviates from `05_report_production.md`'s
`file:line` style deliberately, and §A11.4 records a second, sharper reason than
"line numbers rot": `metascreener/plugin_manager.py::_sanitize` deletes the
`from __future__` line before compiling, so every runtime line number in
`plugins/_common/llm_client.py`, `plugins/06_el/screen.py` and
`plugins/07_il/screen.py` is **off by one from disk**. Line numbers in those three
files are wrong at the moment of measurement, not merely later.

**Evidence markers.** **[measured]** = produced by offline execution of real
repository code with no network. **[installed SDK source]** = read from `openai
1.106.0` in this machine's `site-packages`, i.e. third-party source, not
repository evidence. **[general knowledge]** = not derivable from this repository
or from any installed tree; stated separately and never blended with repository
evidence. **[not established]** = the evidence does not settle it, followed by
what would.

**Candidate findings** are labelled **C-1 … C-42** in §B9. They are *not* register
IDs. No `F-nn` was assigned and `03_findings.md` was not modified. §B9 is a single
deduplicated namespace: the parallel analysis that produced this document issued
roughly 167 `C-n` labels across twelve independent namespaces that all restarted
at C-1, and consolidating them was part of the work. The duplication sweep against
the existing 82 register rows is a later wave.

---

## Executive summary

**The transport is already portable; the product around it is not. Four facts
constrain every design choice that follows, and two of them contradict premises
in the brief.**

1. **The EL/IL request is the minimum viable chat completion, and that is the
   single largest asset in this analysis.**
   `plugins/_common/llm_client.py::run_m1_llm_for_criterion` (inner `_call_once`)
   sends exactly `model`, `messages`, `temperature` — nothing else. Two roles
   (`system`, `user`), both `content` values plain strings, one route
   (`POST {base_url}/chat/completions`), `Authorization: Bearer` from the SDK.
   No `response_format`, no `seed`, no `max_tokens`, no `top_p`, no `logprobs`,
   no `tools`. There is **no enumeration of supported models anywhere in the
   repository** — no `Literal`, no `Enum`, no combobox `values=`, no `argparse
   choices=`, no validation whitelist; the only constraint on a model string in
   the entire tree is `if not model:`. An integration that assumes almost nothing
   is an integration that ports. It is also *incidental*: nothing in any
   docstring, comment or test says the minimality is deliberate, so nothing
   protects it. **[measured]** across the whole tree there are exactly four
   `.create(` LLM call sites in three files.

2. **`model` is already in the cache key — so the brief's pivotal question rests
   on a false premise — and the goldens are insulated from a default-model
   change.** `plugins/_common/llm_client.py::_cache_key` hashes a four-member
   JSON object: `prompt_version`, **`model`**, `temperature`, `prompt`. Model
   identity cannot be "added"; it has been hashed by name since before the
   goldens were captured, and `tests/test_cache_key.py::TestCacheKeySanity::test_model_change_changes_key`
   pins it. Separately, `tests/golden/{el,il}_cache_v3.1.0.json` is a
   `{_invocation, cache}` envelope carrying `{"batch_size": 5, "model":
   "gpt-4o-mini", "trunc_chars": 4000}`, and
   `tests/test_el_regression.py::_el_to_csv` drives the replay with
   `model=invocation["model"]` — **not** `DEFAULT_MODEL`. **[measured]** running
   the full suite with `SCREENA_EL_MODEL=SCREENA_IL_MODEL=gemma3:12b` gives
   **422 passed, 4 skipped**, byte-identical to baseline. Changing the production
   default breaks no test, in any of 16 CI cells. *The number a reviewer replays
   is model-pinned by a fixture; the number a user obtains is model-pinned by
   nothing.* What **would** invalidate every golden key is adding the **endpoint**
   to the key: **[measured]** 0 of 170 EL and 0 of 84 IL keys survive, for either
   candidate `base_url` value, and the two candidate key sets are disjoint from
   each other as well as from the goldens.

3. **The documented local-provider capability is real, GUI-unreachable, and
   implemented entirely by a side effect of the vendor SDK's constructor.**
   `plugins/_common/llm_client.py::_openai_client_for` passes only `api_key` and
   never `base_url`. **[installed SDK source]** `openai/_client.py::OpenAI.__init__`
   falls back to `os.environ.get("OPENAI_BASE_URL")`. No repository line reads,
   writes, validates, logs or records that variable — the only two Python
   occurrences are display strings in `metascreener/api_key_dialog.py`. **No
   widget anywhere in the application is bound to an endpoint, host or port**, so
   the only routes are hand-editing `.env` or the OS environment: precisely the
   config-file editing and CLI use the GUI-first constraint forbids. Wave 1's F-08
   fix unblocked *step 2* of a two-step workflow (the placeholder key) and left
   *step 1* blocked. And **no test anywhere asserts the fallback**, so an SDK
   major that dropped it — or a refactor adding an explicit
   `base_url="https://api.openai.com/v1"` — would silently route a "local" run to
   the paid API with all 422 tests green.

4. **Every model failure routes to flag-for-review rather than to an exclusion —
   with one Critical exception this wave found, and it is worse under a weaker
   model.** The safety property is carried by a single triple-AND conjunction,
   `usable = valid_quote and (confidence >= float(c.threshold)) and (decision in
   {"meet","not_meet"})` (`plugins/06_el/screen.py::run_el_screen`, byte-identical
   at `plugins/07_il/screen.py::run_il_screen`), and `failed.append` occurs only
   inside `if usable:`. **[measured]** fifteen fabricated failure modes — malformed
   JSON, refusal, empty content, missing decision, out-of-vocabulary decision,
   bad field, bad span, transport error, timeout, no key, no model, omitted
   `a_id`, and more — give `OUT = 0` and every record a survivor, at both stages
   and at both criterion polarities (60 runs). **The exception (C-1) is real and
   I reproduced it independently:** `idx_map` is built from the whole `items`
   list before batching, while the back-fill covers only `cur_batch`, and the
   parse-loop write is unguarded — so a model that names another batch's `a_id`
   can have that verdict accepted, validated against the *other record's* real
   text, and exported as an exclusion. **[measured]** 3 of 6 records `OUT` with
   `used: true, quote_valid: true`; it fires at **`batch_size = 1` too**; a
   backward-drift variant *overwrites an already-correct verdict* with no
   omission required; and the fabricated exclusion is written into the persistent
   cache and replays on every later run with **zero API calls**.

Two further facts shape sequencing rather than design. **A finished bundle cannot
be attributed to a model:** across `plugins/` and `metascreener/` the dict key
`"model"` occurs exactly once, inside `_cache_key`'s hashed-and-discarded JSON.
Model, temperature and prompt version are used to *look up* an answer and then
thrown away — and the *entire published validation study*, every kappa in
`docs/llm-evaluation.md` and `docs/data/eval_summary_v1.txt`, is attributable to
`gpt-4o-mini` only through the `_invocation.model` field of two test fixtures,
which is the one file a model swap must overwrite. And **the LLM error path has
no test coverage at all**: `_openai_client_for`'s body never executes in the
suite, so no CI cell today — and none under replay tomorrow — would notice that
the local path is broken.

---

## Part A — descriptive: how the LLM is employed today

### A1 Call-site inventory

**Exactly three modules in the repository send a prompt to a language model.**
Established by sweeping the whole tree for `chat.completions`,
`completions.create`, `responses.create`, `OpenAI(`, `AzureOpenAI`, `embeddings`,
`images`, `moderations`, `anthropic`, `genai`, `generativeai`, `mistralai`,
`cohere`, `ollama`, `requests.post`, `httpx`, `urlopen`, `http.client`,
`/v1/chat`, `/api/generate`, `11434`, `1234/v1`, `8080/v1`.

| # | Module | Symbol issuing the request | SDK surface | Live? |
|---|---|---|---|---|
| 1 | `plugins/_common/llm_client.py` | `run_m1_llm_for_criterion` (inner `_call_once`) | `client.chat.completions.create` | **Yes — EL/IL screening** |
| 2 | `plugins/03_harmoniser/llm_refine.py` | `_call_openai_json` (branch 1) | `client.chat.completions.create` | Yes — opt-in refinement |
| 3 | `plugins/03_harmoniser/llm_refine.py` | `_call_openai_json` (branch 2) | `openai.ChatCompletion.create` | **No — dead** (§A1.3) |
| 4 | `plugins/01_reference_extractor/original/prisma_citations_ai_v3_1.py` | `ai_extract_included` | `client.chat.completions.create` + vision + forced tool call | Yes — experimental |

There are **no** embeddings, image, moderation, `responses.create`, streaming,
Assistants or Batch calls anywhere, and no non-OpenAI SDK. The three client
constructors are `plugins/_common/llm_client.py::_openai_client_for`
(`OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))`),
`prisma_citations_ai_v3_1.py::ai_extract_included`
(`OpenAI(api_key=os.environ["OPENAI_API_KEY"])` — a **subscript**, so a missing
key is a `KeyError`, not a message), and `llm_refine.py::_call_openai_json`
(`OpenAI()` — **no arguments at all**).

#### A1.1 Plugins 06 EL and 07 IL — the shared screening call site

Both stages reach the model through one function. Per-stage differences are
narrow:

| Aspect | EL (06) | IL (07) |
|---|---|---|
| Engine | `plugins/06_el/screen.py::run_el_screen` | `plugins/07_il/screen.py::run_il_screen` |
| Prompt builder passed in | `plugins/06_el/prompt.py::_build_llm_messages_for_criterion` | `plugins/07_il/prompt.py::_build_llm_messages_for_criterion` |
| `stage=` | `"EL"` → log prefix `[EL-LLM]` | `"IL"` → `[IL-LLM]` |
| `block_tag=` | `"exclude"` | **`"exclude"` also** — a mislabel at an inclusion stage (C-38) |
| Cache-key curry | `plugins/06_el/screen.py::_cache_key`, bakes `PROMPT_VERSION = "EL_v1_jsonlist"` | `plugins/07_il/screen.py::_cache_key`, bakes `"IL_v1_jsonlist"` |
| Model default | `plugins/06_el/plugin.py::DEFAULT_MODEL` = `os.environ.get("SCREENA_EL_MODEL", "gpt-4o-mini")` | `plugins/07_il/plugin.py::DEFAULT_MODEL` under `SCREENA_IL_MODEL` |
| Batch / trunc defaults | 50 / 1500 | 50 / 1500 |
| Third label | `PASS_FLAGGED` | `REVIEW` |

**What it sends:** one request per (criterion × batch of records) — a fixed
`system` string and one `user` message whose content is
`json.dumps({"criterion": c_pack, "items": items_pack}, ensure_ascii=False)`.
**What it expects:** a JSON *list* of objects with `a_id`, `decision`,
`confidence`, `field`, `quote`, `span`. **What it does otherwise:** never raises
to the caller; every `(a_id, criterion_id)` pair in the batch is guaranteed an
entry, and any pair not usably answered becomes
`{"used": False, "decision": "uncertain", "confidence": 0.0, "field": "abstract",
"quote": "", "span": None, "valid_quote": False}`. Full table in §A6.4.

Reachability: `metascreener/plugin_manager.py::discover` imports each
`plugins/<dir>/plugin.py`; `metascreener/main.py::resolve_plugin_entrypoint`
instantiates `Plugin` and calls `build_tab`; `plugins/06_el/plugin.py::Plugin.build_tab`
constructs `ELView`. The run path is `plugins/06_el/ui.py::ELView._run_clicked`,
gated by `_has_openai_key()`.

**`standalone.py` in both plugins is not exercised by any test and diverges from
the tab UI.** `plugins/06_el/standalone.py::StandaloneELPlugin` and its IL twin
each contain a *second* independent `run_*_screen` invocation. No test
instantiates either class (references in `tests/test_imports.py` are AST- or
attribute-level only), neither has a `__main__` guard, and neither passes
`temperature=` nor applies a `_has_openai_key()` run gate — only a status label.
**[not established]** whether they are unreachable from the shipped application:
that is a claim about the plugin loader and the frozen build spec, and this wave
verified only "not exercised by any test". They are also *not* free to delete —
`plugins/06_el/plugin.py`'s own comment states "The order matters because of
circular imports between plugin.py / ui.py / standalone.py / screen.py", and
`01_architecture.md` describes that chain as "executed in a deliberately fragile
order dictated by a circular dependency" (C-31).

`tools/capture_el_il_goldens.py` is a fourth, script-only entry into the same
call site, not a distinct request builder: `MODEL = "gpt-4o-mini"`,
`TRUNC_CHARS = 4000`, `BATCH_SIZE = 5`, `use_cache=True`, `cache_in={}`, no
`temperature`.

#### A1.2 Plugin 01 Reference Markers — the GPT-4o vision path

`plugins/01_reference_extractor/plugin.py` **does not itself call a model**. It is
a 61-line shim: `build_tab` does `from .original import prisma_citations_ai_v3_1
as mod; self.view = mod.PrismaAIV3View(f)`, embedding the original module's Tk
frame in-process behind a yellow "Experimental" label. **It does not shell out** —
no `subprocess`, no `runpy`.

The call is `…::ai_extract_included`. It is the one genuinely non-portable request
in the repository:

- `model` from `PrismaAIV3View.model_name`, a free-text Entry, default
  `DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")` — a **different env
  var and a different literal** from EL/IL.
- a `user` message whose content is a **list of parts**: per candidate page a
  text part plus `{"type":"image_url","image_url":{"url":"data:image/png;base64,…"}}`.
  `…::page_to_base64_png` renders at `dpi=240`, one image per candidate page,
  unbounded in count, with **no `detail` control and no `max_tokens`** — an
  untimed, uncapped call carrying inlined image bytes.
- `tools=[tool_schema]` (one function `return_included`) and
  `tool_choice={"type":"function","function":{"name":"return_included"}}` —
  **forced** — plus `temperature=0`.
- reads `chat.choices[0].message.tool_calls[0].function.arguments`. A bare
  `except Exception:` falls back to scraping `[27]`-style bracket numbers out of
  prose, so a refusal produces a **silently degraded numeric result**, not an
  error.

So plugin 01 asserts vision **and** forced function calling, statically, checks
neither, and is pointed at a user-typed model string. This is the **only** site
in the repository where a capability distinction is load-bearing (C-24).

#### A1.3 Plugin 03 Harmoniser — definitively split

**`inference.py` never calls a model. `llm_refine.py` does.** Both are wired, on
two different buttons.

`plugins/03_harmoniser/inference.py` imports only `re`, `typing` and `.parser`;
its docstring says "no GUI, no LLM dependencies", and
`::_infer_criterion_details` is a deterministic six-pattern regex cascade. The
critical distinction: the `operator = "llm"` it writes is a **label in a CSV
cell** declaring that EL/IL must evaluate the criterion later. It is not a call
and does not become one inside plugin 03.

`plugins/03_harmoniser/llm_refine.py::_call_openai_json` is a real second call
site. Branch 1 constructs `OpenAI()` with no arguments and sends `model`,
`messages`, `temperature=0`; it expects a JSON **object** with a `rows` list — a
*different* response contract from EL/IL's bare list. Branch 2 is
`openai.ChatCompletion.create(..., request_timeout=timeout_s)`, the pre-1.0
surface: **[measured]** on the installed 1.106.0, attribute access returns an
`APIRemovedInV1Proxy` and calling it raises `openai.APIRemovedInV1`. Because
branch 1 is wrapped in a bare `except Exception: pass`, **any** branch-1 failure
(missing key, wrong base URL, bad model, a fenced JSON reply) surfaces as
`RuntimeError("LLM call failed: You tried to access openai.ChatCompletion, but
this is no longer supported in openai>=1.0.0 …")` — a migration notice about the
wrong problem. `timeout_s: int = 120` is dead with the branch, so plugin 03's LLM
path has **no timeout at all** (C-19).

Wiring, quoted: `from .llm_refine import _llm_available, _llm_refine` in
`plugins/03_harmoniser/ui.py`; two buttons, `"Harmonise (no-LLM)"` and
`"Harmonise + LLM"`, built in `::HarmoniserView._build_ui`; enablement in
`::HarmoniserView._refresh_buttons` (`llm_ok = _llm_available()`); entry at
`::HarmoniserView._harmonise_llm`. **Opt-in, and only via the dedicated
button** — and note that `_llm_available()` uses bare `os.getenv` truthiness
*without* `.strip()`, diverging from `_has_openai_key` (C-33).

#### A1.4 Plugin 02 References-of-X — definitively **not** an LLM client

It never calls a language model. No `chat.completions`, no prompt, no `gpt`
identifier anywhere in `core.py`, `pipeline.py`, `services.py`, `ui.py`, or
`references_of_x_ai_v1.py` (a 20-line delegator — the "ai" in the filename is
branding). **A bibliographic REST API is not an LLM call** [general knowledge]:
these endpoints return structured metadata records from a database by DOI/title
lookup — no model, no prompt, no sampling, no token cost. It calls OpenAlex,
Crossref, Semantic Scholar, Unpaywall, doi.org and arXiv via `requests.get`, at
**twelve** call sites in `plugins/02_references_of_x/services.py`, each with an
explicit `timeout=` between 10 and 20 s. Local non-model inference: `rapidfuzz`
title matching and `langdetect`.

It nonetheless *looks* like an LLM plugin: `core.py` does `from openai import
OpenAI  # optional AI fallback`, sets `OPENAI_OK`, documents the flag in its
module docstring, and re-exports both in `__all__` — while **no consumer exists**
(C-30).

#### A1.5 Plugins 04 EH / 05 IH — confirmed LLM-free

Neither imports `openai`, constructs a client, or reads `OPENAI_API_KEY`. The
only LLM-adjacent lines are the *refusal* branch in each `ui.py`
(`if op in ("llm",): … "operator 'llm' not supported in EH -> UNKNOWN
(PASS_FLAGGED)"`), backed by `plugins/_common/evaluator.py::_eval_criterion`
returning `"UNKNOWN"` for `op in ("llm",)`.

---

### A2 Transport layer

*This section's parameter classification is the item the brief singles out as
mattering more than any other in Part A.*

**Scope correction.** The brief asserts the code sends only `model`, `messages`,
`temperature`. That is exactly right **for the EL/IL transport** and not right for
the repository as a whole: call site 4 (plugin 01) sends `tools`, `tool_choice`
and multimodal `image_url` content parts. Any portability claim phrased as
"metaScreener sends three parameters" is false at the repository level.

#### A2.1 SDK, declaration, import strategy

| Item | Finding |
|---|---|
| Client | The official `openai` Python SDK. No hand-rolled HTTP, no direct `requests`/`httpx` in the LLM path. |
| Declared | `pyproject.toml` `[project].dependencies` and `requirements.txt` both carry `openai>=1.40.0` — lower bound only, no ceiling. The two files agree exactly on all nine packages; only `openai` carries any constraint (F-15). |
| Installed here | `openai 1.106.0`. **[not established]** whether **1.40.0** — the declared floor — has the `OPENAI_BASE_URL` fallback the documented local path depends on; only 1.106.0 is inspectable without a network fetch. Settling evidence: read `openai/_client.py::OpenAI.__init__` from an installed 1.40.0 or its sdist, or the SDK changelog entry introducing the fallback. |
| Transport | `httpx`, transitively. **`httpx` is declared nowhere in the repository** — nor `anyio`, `pydantic`, `pydantic_core`, `jiter`, `distro`, `sniffio`, `certifi`, `httpcore`, `h11`. |
| Import | **Deferred into the function body** — `plugins/_common/llm_client.py::_openai_client_for` does `from openai import OpenAI` inside itself. The docstring's stated reason is **testability**, not import cost: the seam exists so the function can be monkeypatched, which is exactly how `tests/test_cancellation.py` uses it. Plugin 03 defers for a *different* stated reason (collection-time safety); plugins 01 and 02 use top-level `try/except` + an `OPENAI_OK` flag. Three idioms for one problem. |

#### A2.2 Base URL — the implicit `OPENAI_BASE_URL` path

`_openai_client_for` passes exactly one keyword: `api_key`. No `base_url`, no
`timeout`, no `max_retries`, no `http_client`, no `default_headers`, no
`organization`, no `project`. **No `.py` file anywhere reads, writes, validates,
passes or logs `OPENAI_BASE_URL`**; the only Python occurrences are two display
strings, `metascreener/api_key_dialog.py::LOCAL_PROVIDER_HINT` and the grey
advisory label in `::ApiKeyDialog.__init__`, plus one assertion about that text in
`tests/test_api_key_validation.py`.

**[installed SDK source]** `openai/_client.py::OpenAI.__init__`:

```python
if base_url is None:
    base_url = os.environ.get("OPENAI_BASE_URL")
if base_url is None:
    base_url = f"https://api.openai.com/v1"
```

So the entire local-provider capability — a full README section, and the
project's answer to "does this require a paid API?" — rests on a side effect of
the vendor SDK's constructor. `metascreener/main.py::_load_env_file` is a generic
`KEY=VALUE` reader (`if k and v and k not in os.environ`) and runs before
`_load_plugins()`, so an `OPENAI_BASE_URL=` line in `.env` *does* reach
`os.environ`; but the shipped `.env.example` is **one line**, `OPENAI_API_KEY=`,
and that line is itself a no-op because `_load_env_file` requires a non-empty
value.

`02_quality.md`'s "Client construction" row already records this mechanism and
**I agree with it entirely**, having now confirmed the SDK half against installed
source rather than assumption. Two caveats for whoever edits that document: its
line number 167 is stale (`_openai_client_for` is lines 71–78 as of `f952e69`),
and two neighbouring rows in the same table are stale post-fix — the
**Cancellation** row describes pre-F-26 behaviour, and the **§6.4 key derivation**
block describes the pre-F-01 enumerated key.

The same SDK constructor also silently absorbs `OPENAI_ORG_ID`,
`OPENAI_PROJECT_ID` and `OPENAI_WEBHOOK_SECRET` from the environment and emits
the first two as headers — so a user with those left over from other tooling
sends them to their local server. Harmless in practice; a second class of
implicit configuration the repository does not know about, and one that
`.env`'s unallowlisted loader can set (C-40).

#### A2.3 Endpoint path, auth, timeouts, concurrency

**Route.** One SDK method: `client.chat.completions.create`. **[installed SDK
source]** `openai/resources/chat/completions/completions.py` posts to the literal
`"/chat/completions"`. Repo-wide grep for `\.responses\.create` returns zero.
This matters: **[general knowledge]** `/v1/chat/completions` is the de facto
interoperability surface that Ollama, LM Studio, `llama-server` and vLLM all
implement, whereas the newer proprietary `/v1/responses` is implemented by
essentially none of them. Using `chat.completions` is the single most
portability-preserving decision in this layer — **and it appears incidental**; no
comment records the choice, so nothing protects it from a "modernise to the
Responses API" commit (C-25).

**Auth.** Not hand-rolled. **[installed SDK source]** `OpenAI.auth_headers`
returns `{"Authorization": f"Bearer {api_key}"}`, `{}` if falsy. Note the
interlock: `_openai_client_for` passes `os.environ.get(...)`, which is `None` when
unset, and the SDK **raises `OpenAIError`** on `api_key is None` — unreachable
from EL/IL because `_has_openai_key` gates first, but reachable from plugin 03,
which constructs `OpenAI()` bare.

**Timeouts.** **Not established in the repository, and this is definitive rather
than a gap in the search.** Repo-wide grep for `timeout|max_retries|with_options|
Timeout` returns two families, neither on the EL/IL path: twelve
`requests.get(..., timeout=…)` calls in plugin 02, and
`llm_refine.py::_call_openai_json`'s `timeout_s: int = 120`, forwarded only on
the dead branch. **[installed SDK source]** the defaults that therefore apply:
`DEFAULT_TIMEOUT = httpx.Timeout(timeout=600, connect=5.0)` and
`DEFAULT_MAX_RETRIES = 2`. So one `_call_once` can consume **3 × 600 s = up to
30 minutes** on a single batch while the worker thread holds and the UI shows the
stale `"sending"` progress event. This sharpens F-25's magnitude (C-20).

**Concurrency: there is none. Definitively.** Repo-wide grep for
`asyncio|concurrent\.futures|ThreadPool|ProcessPool|Executor|multiprocessing`
returns **zero hits** in any `.py` file. `threading` is used only as one
background worker per plugin plus `Event` as a cancel token — and one
`threading.Lock()` in plugin 02's non-LLM path. `plugins/_common/runner.py`
contains **no LLM code at all**; its `threading` import exists solely for the
`cancel_event: threading.Event` type hint. Criteria are serial; batches within a
criterion are serial. **Exactly one HTTP request is in flight per stage at any
instant.** Corroborating: `tests/test_cancellation.py`'s fake client counts calls
with a plain non-atomic integer and asserts exact counts, which would be flaky
under any concurrency. Consequence: a 776-record corpus at `batch_size=50` across
2 criteria is ~32 strictly serial requests, undocumented and unmeasured (C-35).

#### A2.4 Retries — two independent layers, neither aware of the other

**Layer 1, the SDK's, is invisible to this code.** **[installed SDK source]**
`DEFAULT_MAX_RETRIES = 2`; `_base_client.py::_should_retry` retries on the
`x-should-retry` header and on 408, 409, 429 and any ≥ 500, with exponential
backoff between `INITIAL_RETRY_DELAY = 0.5` and `MAX_RETRY_DELAY = 8.0`. The
repository never disables, configures or logs it. **Every "batch failed" line in
the metaScreener log therefore represents three HTTP attempts, not one**, and
every Layer-2 sleep is *additional* to up to 8 s already spent inside `create()`.

**Layer 2 is the repository's own adaptive loop**, all inside
`run_m1_llm_for_criterion`: an outer `while bi < len(batches)` and an inner
`while True` with an `attempts` counter that is **used for nothing except the
sleep duration** and is never compared against a cap.

Classification is by substring sniffing on the stringified exception:

```python
msg = str(e).lower()
is_rate = ("429" in msg) or ("too many requests" in msg) or ("rate" in msg and "limit" in msg)
is_big  = ("too large" in msg) or ("context" in msg and "length" in msg) or ("max tokens" in msg)
```

There is no reference to `openai.RateLimitError`, `openai.BadRequestError`,
`e.status_code` or `e.code` anywhere in the repository. **Both remedies — batch
halving and the truncation step-down — are gated on `(is_rate or is_big)`.**

Assessment, and one correction to an earlier reading in this wave. The 429 path
is **more robust than it first appears**: **[installed SDK source]**
`_make_status_error_from_response` composes `err_msg = err_text or f"Error code:
{response.status_code}"` on a non-JSON body, so an *empty* body still yields
`"Error code: 429"` (matching `"429"`) and a plain-text `"Too Many Requests"`
body matches the second predicate. The genuinely broken half is **oversize**:
`is_big` requires `context` ∧ `length` co-occurring, so a server saying "prompt
exceeds the context window" or "n_ctx exceeded" matches neither term-pair and
the batch-halving and truncation remedies **that exist precisely for that
condition never fire** — and small context windows are exactly the local case.
`APITimeoutError` → `"Request timed out."` and `APIConnectionError` →
`"Connection error."` match neither predicate, so **every timeout and every
connection failure is terminal on first sight** at the application layer. There
are also false positives: `"rate" in msg` matches inside `generate`, `moderate`,
`separate`, `accurate`, `iterate` (C-9).

The **batch-halving requeue** is item-preserving by construction —
`cur_batch[:new_n]` replaces `batches[bi]` and `cur_batch[new_n:]` is inserted at
`bi + 1`, so the outer loop reaches it next. Note that halving is applied to
*both* branches: on a genuine rate limit it **increases** request count, which is
the opposite of what a 429 asks for, and no `Retry-After` is read at Layer 2
(C-21). The **truncation step-down** (`new_trunc = max(600, int(cur_trunc *
0.75))`) is reached only when `len(cur_batch) == 1`.

**Is there a bound on attempts? No explicit bound — but termination is guaranteed
by construction, and the proof is tighter than a worst-case count.** Every
`continue` strictly decreases the lexicographic measure
`(len(cur_batch), cur_trunc)`: the split gate requires `len(cur_batch) > 1` and
`new_n = max(1, len//2) < len` for all `len ≥ 2`; the truncation gate requires
`cur_trunc > 600` and `max(600, int(0.75·c)) < c` for all `c > 600`. Both are
bounded below. The outer loop terminates because total items is invariant and no
batch is ever empty, so `len(batches) ≤ len(items)`. Two arithmetic corrections
to earlier readings in this wave: 50 items halve in **5** steps (50→25→12→6→3→1),
and the step-down count is **not a constant** — 4 at the default
`trunc_chars=1500`, but **7** at the goldens' 4000, and `trunc_chars` is a
user-editable field. The fragility is that the guarantee lives in two unrelated
gate conditions and no test asserts it.

**One further defect the retry structure hides.** `_check_cancel` is defined once
and invoked at **exactly one site** — the top of the *outer* batch loop, outside
the inner `try`. Nothing inside that try body (`progress`, `_call_once`,
`_parse_llm_json_array`, the back-fill loops, `time.sleep`) calls it. So
cancellation is unobserved for the **entire** inner retry loop — not only the
≤ 4 s sleeps but the HTTP call itself (up to 3 × 600 s) and the whole
split/step-down cascade. The corollary: the `except _Cancelled: raise` guard and
the elaborate F-26 rationale in `::_Cancelled`'s docstring are **unreachable in
production** — no code inside the try can raise `_Cancelled`. They fire only
under the injected test double (C-14).

#### A2.5 THE PARAMETER CLASSIFICATION

**Table 1 — what the EL/IL transport DOES send.** Verbatim:

```python
def _call_once(batch: List[Dict[str, Any]], cur_trunc: int):
    msgs = build_messages(criterion, batch, cur_trunc)
    return client.chat.completions.create(
        model=model,
        messages=msgs,
        temperature=temperature,
    )
```

Confirmed exhaustive three ways: reading the call; a repo-wide grep for
`response_format|seed|top_p|top_k|logprobs|service_tier|max_tokens|
max_completion_tokens|frequency_penalty|presence_penalty|logit_bias|stream=|
stop=|reasoning_effort|extra_body|extra_headers` finding **no hit inside
`llm_client.py` or any EL/IL module**; and the accidental contract test in
`tests/test_cancellation.py`'s fake client, whose
`create(self, *, model, messages, temperature)` is **keyword-only with no
`**kwargs`**, so any fourth parameter fails the suite.

| Parameter | Source | Class | Note |
|---|---|---|---|
| `model` | `SCREENA_{EL,IL}_MODEL` env or the Tk Entry, default `gpt-4o-mini` | **(a) universal** | Required by the request schema everywhere. Its *semantics* are not universal: `README.md` itself states that with llama.cpp the field "can be set to any value … since the server uses whichever model is currently loaded". That has a cache consequence (C-4). |
| `messages` | the per-stage prompt builder | **(a) universal** | Emits exactly `[{"role":"system","content":<str>},{"role":"user","content":<str>}]` — plain strings, no content-part arrays, no images, no `name`, no `tool_calls`. The most conservative possible shape. |
| `temperature` | keyword, default `0.0`; EL/IL Spinbox 0.0–2.0 | **(a) universal across OpenAI-*compatible* servers — but NOT universally accepted by OpenAI itself** | **[general knowledge]** OpenAI's reasoning-model family rejects `temperature` with a 400 rather than ignoring it. Repository consequence: such an error satisfies neither `is_rate` nor `is_big`, so **every batch of every criterion goes terminal and the whole corpus is written `decision: "uncertain"`** — a silent full-corpus failure presented as a completed run. The Model field is free text, so this is reachable by typing (C-9). Effect at 0.0 is **(c) unknown**: some backends map 0 to greedy decoding, some clamp, and none is obliged to ignore a server-side `top_k`/`repeat_penalty` **[general knowledge]**. |

**Roles.** Only `system` and `user`; `assistant` and `tool` never appear.
**[general knowledge]** some open-weight chat templates have no system turn and
the serving layer prepends or discards it — and a discarded system prompt here
removes the *entire* output-format instruction, leaving the model the JSON
payload and no instruction to produce anything. The downstream effect is
benign-but-invisible: `_parse_llm_json_array` returns `[]`, every item back-fills
`uncertain`, and the stage reports a clean run of flagged records.

**Response shape.** `txt = (resp.choices[0].message.content or "[]")`.
**[general knowledge]** `choices[].message.content` is the chat-completions
contract that every compatibility layer emits, so the access is portable. Three
repository-level observations: `resp.choices[0]` is **unguarded**, so
`{"choices": []}` raises `IndexError("list index out of range")`, which matches
neither predicate and sends the batch terminal carrying that text as its `error`;
`content is None` is handled, degrading to `"[]"`; and `finish_reason` is
**never read** — the F-25 truncation blind spot. **[installed SDK source]**
`_strict_response_validation` defaults `False`, which helps portability: a server
returning extra or slightly-off fields does not raise.

**Table 2 — OpenAI-specific parameters the code notably does NOT send.** *The
class assignments in this table are* **[general knowledge, not repo evidence]** —
the repository establishes only the absence.

| Not sent | Class if sent | What not sending it costs / buys |
|---|---|---|
| `response_format` / `json_schema` | **(b)** | **Buys portability, costs reliability.** The code instead salvages with `_parse_llm_json_array`'s three tiers. Given the local-provider ambition this is arguably the right trade — a hard `response_format` would 400 on some servers — but it is nowhere *stated* as a trade. |
| `seed` | **(b)** | The one parameter that would buy real run-to-run stability on a self-hosted server, and the one never sent. See §A10. |
| `max_tokens` / `max_completion_tokens` | **(a)** | The one absence that is a pure loss with no portability upside. Already F-25. Worse locally, where default output caps and context windows are far smaller than a hosted `gpt-4o-mini`'s while `batch_size` is 50. |
| `top_p` | **(a)** | Not sent, so the server's default applies — invisibly, unlogged, unrecorded. |
| `top_k`, `repeat_penalty`, `min_p`, `num_ctx`, `num_predict` | not OpenAI parameters — local-server extensions | Unreachable through this transport even when needed; there is no `extra_body` seam. |
| `logprobs` / `top_logprobs` | **(b)** | The evaluation story leans on the model's *self-reported* `confidence`, a number it writes into its JSON. Token logprobs are the calibrated alternative and are not requested. See §B6. |
| `stream` | **(a)** | No incremental feedback; the 600 s timeout is felt as a total freeze. |
| `tools` / `tool_choice` | **(b)** | Deliberately absent from EL/IL and **present in plugin 01** — the one part of metaScreener that cannot plausibly run against an arbitrary OpenAI-compatible server. |
| `service_tier`, `n`, `stop`, `frequency_penalty`, `presence_penalty`, `logit_bias`, `user`, `metadata`, `store`, `reasoning_effort` | (a)/(b) | No cost. |
| `extra_headers`, `extra_body`, `extra_query`, per-request `timeout` | SDK escape hatches | None used. There is no seam at all for provider-specific tuning. |

**OpenAI-*shaped* vs OpenAI-*specific*.** What is genuinely OpenAI-specific on the
EL/IL wire: **nothing as against other vendors** — three universal parameters,
two universal roles, one universal route, a Bearer header. What is
OpenAI-*shaped*, i.e. would break against a **native** non-OpenAI API:

| Shape assumption | Where | What breaks off-OpenAI |
|---|---|---|
| The SDK class itself | `::_openai_client_for`, hard-coded `from openai import OpenAI` | No provider abstraction exists. Supporting a native API means editing this one function — a point in the design's favour. |
| `messages` as a flat list with a `system` **role** | the two `prompt.py` builders | **[general knowledge]** Anthropic takes `system` as a top-level parameter; Gemini uses `systemInstruction` + `contents`/`parts`. The builder must be restructured, not re-routed. |
| `resp.choices[0].message.content` | the unwrap | **[general knowledge]** Anthropic returns `content: [{type:"text",…}]`; Gemini `candidates[0].content.parts[0].text`. Ollama's native `/api/chat` has **no `choices` key at all**. |
| Error text carrying `429` / `context…length` | `is_rate`/`is_big` | Already fragile *within* the compatible world; off it, meaningless. |
| Env-var **names** and user-facing strings | `_has_openai_key`; the dialog title "OpenAI API Key"; `plugins/06_el/ui.py::ELView._run_clicked`'s `"EL uses the OpenAI API."` | Cosmetic but pervasive: a user running Gemma on Ollama is told their local run "uses the OpenAI API" (C-34). |

**Net, for a reviewer asking "is this OpenAI-locked?": the requests are not; the
vocabulary and the error handling are; and plugin 01 genuinely is.**

---

### A3 Where the model name comes from

#### A3.1 Complete inventory

**(i) Sites that DEFAULT a model** — a fallback literal deciding what runs when
the user supplies nothing:

| `path::symbol` | Literal | Role | Env override |
|---|---|---|---|
| `plugins/06_el/plugin.py::DEFAULT_MODEL` | `gpt-4o-mini` | Runtime default, EL | `SCREENA_EL_MODEL` |
| `plugins/07_il/plugin.py::DEFAULT_MODEL` | `gpt-4o-mini` | Runtime default, IL | `SCREENA_IL_MODEL` |
| `plugins/01_reference_extractor/original/prisma_citations_ai_v3_1.py::DEFAULT_MODEL` | **`gpt-4o`** | Runtime default, plugin 01 vision | `OPENAI_MODEL` |
| `plugins/03_harmoniser/ui.py::HarmoniserView._build_ui` (`ent_model.insert(0, …)`) | `gpt-4o-mini` | UI prefill | **none** |
| `plugins/03_harmoniser/ui.py::HarmoniserView._harmonise_llm` (`… or "gpt-4o-mini"`) | `gpt-4o-mini` | Runtime fallback — a **second, independent** literal in the same file with nothing keeping the two in sync | **none** |
| `tools/capture_el_il_goldens.py::MODEL` | `gpt-4o-mini` | The model actually billed on a golden re-capture | none |

**Six default-bearing literals in five files.** Plugin 03 alone carries two, in
one module (C-29).

**(ii) Sites that merely MENTION a model in prose:** `README.md` (plugin-01
capability column `GPT-4o vision API`; the two `SCREENA_*_MODEL` default rows —
**accurate**; `llama3.1` twice in the Ollama recipe; a DeepSeek context-window
comparison to `GPT-4o-mini`), `docs/installation.md`'s `OPENAI_MODEL` row
(**wrong**, §A13), `docs/faq.md`'s cost estimate, and four internal-diagnostic
mentions.

**(iii) Sites that RECORD which model produced an artifact:**
`tests/golden/{el,il}_cache_v3.1.0.json` → `_invocation.model` = `gpt-4o-mini`
(provenance **and load-bearing test input**), and `docs/llm-evaluation.md`'s
archived-run bullet — a historical fact that must **never** be updated.

**(iv) Inert test-fixture literals:** `tests/test_cache_key.py` (three sites,
including `gpt-4o` used only as "some other model"),
`tests/test_cancellation.py` (three), `tests/test_not_screened.py` (two). Inert
because the surrounding tests disable the cache or run with no key.

**(v) Checked and confirmed to contain NO model name:** `.env.example`,
`Dockerfile`, `docker_test.sh`, `.github/workflows/test.yml`, `CITATION.cff`,
`.zenodo.json`, both `.spec` files (only `collect_all('openai')`),
`hook-plugins.py`, `pyproject.toml`, `requirements.txt`,
`plugins/_common/bundle.py` and `plugins/03_harmoniser/bundle.py` (the substring
`model` appears **zero** times in either), all of `docs/data/`, `tests/data/`,
`tests/conftest.py`. Two false positives disclaimed: one corpus abstract is
*about* "Chat GPT", and
`tests/test_api_key_validation.py::LOCAL_PROVIDER_KEYS` is a list of **API-key
placeholders**, not model names.

**Premise correction: "cached bundles" are not a model-name location.** A shipped
bundle's `cache/EL_cache.jsonl` records no model — `::_dump_cache_to_jsonl` writes
only `{"key":…, "val":…}`. The `_invocation` envelope exists **only** in the test
fixtures; it is the *capture tool's* format, not the bundle format (§A9.4).

#### A3.2 The env-var chain, and its timing

`metascreener/main.py::_load_env_file` is invoked from `MetaScreenerApp.__init__`
**before** `self._load_plugins()`, and plugin modules are imported only inside
`plugin_manager.discover`. Since `run.py` imports only `metascreener.plugin_manager`
and `metascreener.main`, **no plugin module is imported before `.env` is loaded** —
so `SCREENA_EL_MODEL` / `SCREENA_IL_MODEL` / `OPENAI_MODEL` placed in `.env` do
take effect despite the import-time `os.environ.get` idiom. `_load_env_file` sets
only keys `not in os.environ`, so a real environment variable wins over `.env`.

Precedence, EL/IL: **GUI entry (non-blank, stripped) → `SCREENA_*_MODEL` from real
env → same from `.env` → literal `gpt-4o-mini`.** The GUI entry is re-read on
every Run click; the env layer is frozen at import.

`OPENAI_BASE_URL` and `METASCREENER_CACHE_DIR` are read by **nothing**.

#### A3.3 Is there a hand-maintained list of "supported" models? — **No. Definitively.**

There is no enumeration, no validation, and no rejection of an unrecognised model
string anywhere. What was searched:

| Search | Result |
|---|---|
| `Literal[`, `class …(Enum)`, `IntEnum`, `StrEnum`, `TypedDict`, `NewType` | **zero hits repository-wide, in any `.py` file** |
| `SUPPORTED_`, `ALLOWED_`, `VALID_`, `_MODELS`, `MODELS_`, `KNOWN_` | zero model-related hits |
| `ttk.Combobox` | **three** instances, none a model picker: plugin 01's result-sort control, and plugin 03's `values=list(STAGES)` and `values=list(OPERATORS)` |
| every model-input widget | `ttk.Entry`, free text, no validator — six of them (EL, IL, both standalones, plugin 03, plugin 01) |
| `argparse` `choices=` | **zero anywhere in the repository** |
| any conditional on `model` | **exactly one line**: `if not model:` in `run_m1_llm_for_criterion` |

**This absence is the result, and it inverts the brief's framing.** Destination
1's *stated* problem — "the model he used last may no longer be supported by
whatever enumeration the code carries" — describes a hazard this code does not
have. What is actually broken is the opposite: **nothing validates the model
string**, so a typo produces a full corpus of manufactured `uncertain`
non-answers reported as `"EL done."` (C-8). Any discovery feature must be
designed as an *aid* that preserves this permissiveness, not as a gate that
introduces the enumeration the brief fears.

#### A3.4 Change-cost — three different counts

**To USE a new model for one run — 0 files.** Type it into the stage's Model
entry, or export `SCREENA_EL_MODEL`/`SCREENA_IL_MODEL`/`OPENAI_MODEL`, or add a
line to `.env`. No enumeration to extend, no validation to satisfy.

**To make a new model the DEFAULT — 6 code sites in 5 files** (the six literals
in §A3.1(i)), **plus 6 user-facing documentation sites** that assert the current
default (`README.md` ×4 including the plugin-01 row and the DeepSeek comparison,
`docs/installation.md`, `docs/faq.md`), **plus 4 internal-doc sites**. Total for a
clean change: **16 edits.** Nothing enforces consistency; no test compares a doc
string to `DEFAULT_MODEL`.

**To RE-ESTABLISH goldens under a new model — 1 tool constant, then 6 regenerated
fixtures, then a live run.** `tools/capture_el_il_goldens.py::MODEL` is the only
string to edit; there is no CLI override (its `main()` argparse declares exactly
one option, `--print-hashes`). The `_invocation.model` field **cannot be
"updated"** — because `_cache_key` hashes the model, hand-editing it without
re-capturing makes every key miss, every criterion go `UNCERTAIN`, and the
byte-identity goldens fail. It can only be re-captured. The prompt-hash tests are
model-agnostic: they hash `_build_llm_messages_for_criterion(criterion, [item],
4000)`, which contains no model name.

#### A3.5 Does any code branch on model name or family? — **No. Nothing inspects a model string beyond truthiness.**

| Asked about | Answer |
|---|---|
| Branch on model name/family | **None.** The exhaustive conditional grep returns only `if not model:`. |
| `"gpt-4"` / `"-mini"` substring tests | **None.** No `startswith`/`endswith`/`in model` anywhere. |
| JSON mode / `response_format` | **Never sent.** Discipline is enforced *post hoc* by `_parse_llm_json_array`. |
| `max_tokens` / token budgeting | **Never sent, never computed.** |
| Tokeniser choice | **Absent.** `tiktoken` appears nowhere in code or dependencies. |
| Context-window assumptions | **No numeric assumption keyed to a model.** Handling is purely *reactive*: `is_big` → halve → step `cur_trunc` down. Model-agnostic by construction — and, per §A2.4, the trigger does not fire on a local server's phrasing. |
| Cost estimation | **Absent.** No pricing table, no accounting. The only cost statement is prose in `docs/faq.md`, wrong by 2–3 orders of magnitude (§A13). |
| Vision-vs-text routing | **No routing.** Plugin 01 is unconditionally multimodal and unconditionally tool-forcing. |

So capability assumptions live **per plugin, statically**, never per model, and
nothing in the code states or checks them.

---

### A4 Provider and model selection as the user experiences it

#### A4.1 Where a model is chosen, per stage

**There is no Combobox, OptionMenu or validated widget for model anywhere in the
application.** Every model field is a bare `ttk.Entry`.

| Stage | Widget construction | Prefill | Read-back | Validation |
|---|---|---|---|---|
| 01 | `…prisma_citations_ai_v3_1.py::PrismaAIV3View._build_ui`, label `"OpenAI model:"` | `OPENAI_MODEL` else `gpt-4o` | `::on_extract` | none |
| 03 | `plugins/03_harmoniser/ui.py::HarmoniserView._build_ui` — `ttk.Entry(...)` then `.insert(0, "gpt-4o-mini")`, **no `textvariable`** | literal; reads **no** env var | `::_harmonise_llm` | none |
| 06 EL | `plugins/06_el/ui.py::ELView._build_ui`, in Labelframe `"EL Settings"` | `SCREENA_EL_MODEL` else `gpt-4o-mini` | `::ELView._run_clicked` | none |
| 07 IL | `plugins/07_il/ui.py::ILView._build_ui`, Labelframe `"IL Settings"` | `SCREENA_IL_MODEL` else `gpt-4o-mini` | `::ILView._run_clicked` | none |

Note the fallback's shape in EL/IL: `model = (self.var_model.get() or
DEFAULT_MODEL).strip()`. An **emptied** field falls back to the default (empty
string is falsy), but a field containing **only spaces** is truthy, survives the
`or`, and strips to `""` — traced to a completed-looking run in §A4.4 (C-8).

#### A4.2 Per-stage or global? — strictly per-stage, with no reconciliation

To run a full EL+IL pipeline a user sets the model in **two** independent widgets
on two tabs. Adding harmoniser refinement makes it **three**; adding plugin 01
makes it **four**. The prefills can differ before the user touches anything: EL
reads `SCREENA_EL_MODEL`, IL reads `SCREENA_IL_MODEL`, plugin 01 reads
`OPENAI_MODEL` defaulting to a *different model*, and plugin 03 reads nothing.
**If they disagree, nothing detects it and nothing records it** — an
EL-on-`gpt-4o-mini` / IL-on-`llama3.1` pipeline is indistinguishable, in its own
audit artefact, from a uniform run (C-3, C-36).

#### A4.3 Persistence — nothing but the API key

Exhaustive search for `settings.json`, `config.json`, `prefs`, `winreg`,
`configparser`, `.ini` across `metascreener/`, `plugins/`, `tools/` returns one
irrelevant hit. The single persistence primitive is
`metascreener/main.py::_save_env_key`, which writes exactly one variable
(`ENV_KEY == "OPENAI_API_KEY"`). Model, temperature, batch size, truncation and
the cache toggle are Tk variables created fresh per view and discarded on close.

**Consequence, plainly: a user on a local model must retype the model name into
two separate fields on every launch, forever.** The only way to make a non-default
model stick is `SCREENA_EL_MODEL` + `SCREENA_IL_MODEL` — a `.env` or OS-environment
edit, i.e. the GUI-first constraint violated to escape a GUI-first defect. The
harmoniser cannot be pinned even that way (C-32).

#### A4.4 Is `base_url` reachable from the GUI today? — **No. Definitively.**

Not from any tab, not from the launch dialog, not from any menu. A
case-insensitive search for `base_?url|endpoint|provider|localhost|11434|:8080|
host|port` across `metascreener/` and `plugins/` yields, in GUI code, exactly
**two** hits — both *static advisory text* in `metascreener/api_key_dialog.py`,
and both of which **instruct the user to set an environment variable**. Neither
offers a field.

The only routes are (1) hand-editing `<repo root>/.env` — resolved as
`MetaScreenerApp.__init__`'s `self.project_root / ".env"` with
`project_root = Path(__file__).resolve().parents[1]`; gitignored, never committed —
or (2) setting the OS environment before launch. **Neither satisfies the GUI-first
constraint.** The consequence is that *the entire local-inference story is
GUI-unreachable* even after wave 1: F-08 removed the key-format barrier so the
placeholder key can be entered, but the redirect that makes the placeholder
meaningful cannot (C-6).

`.env.example` offers no help: one line, `OPENAI_API_KEY=`. A user who follows
`docs/installation.md`'s "Copy `.env.example` to `.env`" never encounters
`OPENAI_BASE_URL`, and it is absent from the README's own env-var table too.

#### A4.5 Does the GUI reveal which provider is in effect? — **No.**

A user looking at the screen cannot tell whether the next click spends money at
OpenAI or hits a server on localhost. What the labels show:

| Stage | Symbol | Text | Predicate |
|---|---|---|---|
| 06 EL | `plugins/06_el/ui.py::ELView._refresh_key_label` | `"OPENAI_API_KEY ✓"` / `"✗"` | `_has_openai_key` |
| 07 IL | `plugins/07_il/ui.py::ILView._refresh_key_label` | same | same |
| 03 | `plugins/03_harmoniser/ui.py::HarmoniserView._refresh_buttons` | `"API key: OK"` / `"missing"` | `_llm_available` (no `.strip()`) |
| 01 | — | **no key or provider indicator at all** | checked only after the button is pressed |

Three problems compound. **The label reports the wrong variable for the question
being asked** — `OPENAI_API_KEY ✓` is true whether the value is a live `sk-`
credential or the string `ollama`, while the variable that decides the cost
question is never displayed. **In the hub the ✗ branch is unreachable, so the
indicator is a constant**: `MetaScreenerApp.__init__` calls
`_prompt_api_key_always()` *before* `_load_plugins()`, that method returns `False`
(app destroyed) unless `dlg.value` is truthy, and on success unconditionally sets
`os.environ[ENV_KEY]`; nothing ever clears it. So `_has_openai_key()` is
necessarily `True` by the time any EL/IL tab exists, and the ✗ string, the
harmoniser's "missing" string and both `messagebox.showerror("Missing
OPENAI_API_KEY", …)` calls are **dead in the shipped entry point**. And **the
wording is provider-locked** (C-34).

#### A4.6 Other LLM-adjacent GUI settings

| Setting | Tabs | Widget | Default | Validation |
|---|---|---|---|---|
| Model | EL/IL/03/01 | `ttk.Entry` | see §A4.1 | none |
| Temperature | EL/IL only | `ttk.Spinbox(from_=0.0, to=2.0, increment=0.1, format="%.2f")` on a `DoubleVar` | `0.0` | range is advisory — the entry is editable, so a typed `5.0` parses and is forwarded; unparseable text silently becomes `0.0` |
| Batch size | EL/IL | `ttk.Entry` | `50` | none; `0` absorbed by `max(1, int(n))` in `::chunked` |
| Trunc chars | EL/IL | `ttk.Entry` | `1500` | none. A **negative** value reaches `prompt.py`'s `trunc`, whose guard `if trunc_chars and len(s) > trunc_chars` makes `-100` truncate the *tail* of every field |
| Use cache | EL/IL | `ttk.Checkbutton` | on | n/a |
| "LLM refine" | 03 | `ttk.Checkbutton` on `self.var_llm` | `False` | **read by nothing** — grep returns only the two construction lines (C-28) |

Not exposed anywhere, for any stage: `base_url`, timeout, `max_tokens`, retry
budget, cost estimate, prompt version, threshold.

**What an unvalidated Model field costs.** Two failure modes reach a
completed-looking run. A **whitespace-only** model becomes `""`,
`run_m1_llm_for_criterion` hits `if not model:` and returns `{}` after one log
line, every criterion lands `uncertain`, and every row is `PASS_FLAGGED` — not
`NOT_SCREENED`, which requires *zero enabled criteria*. A **misspelled or
unavailable** model produces an error matching neither `is_rate` nor `is_big`, so
the terminal branch writes every item `uncertain` with `error=str(e)`. In both
cases the status label reads `"EL done."`, both export buttons enable, and
`pipeline.history` records `cancelled: False, not_screened: False`. The only
trace is a line in the **Log** sub-tab — which is not the focused tab, since
`tab_full` is added first. Same family as F-34 on a different trigger (C-8).

---

### A5 API key handling

#### A5.1 The dialog — wave 1's change confirmed

`metascreener/api_key_dialog.py` symbols: `LOCAL_PROVIDER_HINT`,
`sanitize_api_key`, `looks_like_openai_key`, `validate_api_key`, `ApiKeyDialog`.
The acceptance logic verbatim (`::validate_api_key`):

```python
key = sanitize_api_key(key)
if not key:
    return False, "Please enter a key."
if not looks_like_openai_key(key):
    return True, LOCAL_PROVIDER_HINT
return True, ""
```

**Confirmed: the only rejection is emptiness.** The shape check survives, demoted
to advisory: `::looks_like_openai_key` returns `key.startswith("sk-") and
len(key) >= 20`. Its only callers are `validate_api_key` (to choose hint or
silence) and `::ApiKeyDialog._is_valid`, which is retained for historical surface
and **called by nothing** (C-42).

`::LOCAL_PROVIDER_HINT`, verbatim:

> "This does not look like an OpenAI key. It will be used as entered - correct if
> you have set OPENAI_BASE_URL to a local or third-party endpoint (Ollama,
> llama.cpp, vLLM, DeepSeek)."

The standing grey help label in the dialog body, verbatim:

> "Using a local or third-party endpoint? Set OPENAI_BASE_URL and enter any
> non-empty placeholder here (e.g. "ollama") - most local servers require the
> variable to be set but ignore its value."

Presentation: on rejection the message goes red and the dialog stays open; on
acceptance-with-hint the label is recoloured grey, the hint shown,
`update_idletasks()` called, and then `self.value = key; self.destroy()` — so the
hint is displayed **for one frame** and the dialog closes. The persistent copy is
the always-visible row-3 label.

**Stale documentation inside the same file:** the `ApiKeyDialog` class docstring
still asserts the removed rule — *"Basic format validation (starts with 'sk-',
length >= 20)"*. The file that was the subject of the fix tells its next reader
the opposite of what it does (C-42).

Sanitisation: `::sanitize_api_key` is `(s or "").strip().strip('"').strip("'")` —
handles `None`, whitespace, then one layer of double then single quotes.
`main.py::_load_env_file` performs an independent equivalent cleanup on read;
`::_save_env_key` writes the value **unquoted and unescaped**.

#### A5.2 Storage, scope, lifetime

- **Path:** `<repo root>/.env`, from `project_root = Path(__file__).resolve().parents[1]`.
  The checkbox label states it: "Remember on this device (.env in project
  folder)", and `remember_default=True` is passed, so it is **pre-checked**.
- **Format:** plaintext `OPENAI_API_KEY=<value>`; existing lines for that key are
  filtered and one appended; **other lines, including `OPENAI_BASE_URL`, are
  preserved**. Both read and write failures are swallowed
  (`except Exception: pass`), so a locked `.env` makes "Remember" silently do
  nothing.
- **Gitignored:** yes (`.env`, `.env.local`, … plus `secrets/*` with
  `!secrets/README.md`). Verified never committed.
- **Permissions on Windows: none applied.** `Path.write_text` inherits the
  project directory's NTFS ACLs; there is no `os.chmod`, no `icacls`, no DPAPI or
  Credential Manager use anywhere.
- **`secrets/`** contains only `README.md`, whose text tells users to put `.env`
  there — while `ENV_FILE_NAME` resolves to the **project root**. A user who
  follows that advice has their key silently ignored (C-42).
- **Shown on every launch: yes, unconditionally.** `::MetaScreenerApp._prompt_api_key_always`'s
  docstring says so; a valid key in the environment only prefills.
- **Cannot be skipped.** On Cancel / Escape / window-close, `dlg.value = None`,
  the method returns `False`, `__init__` schedules `destroy()` and returns before
  the notebook, `self._plugins` and the `WM_DELETE_WINDOW` protocol exist. **The
  process exits with no window and no message. No key ⇒ no application.**
- **Lifetime:** the `.env` value persists indefinitely. Unchecking "Remember"
  does **not** delete a previously written line — `_save_env_key` is simply not
  called. There is no "forget key" affordance.

#### A5.3 Is there a path where no key is supplied at all?

**Through `run.py` / `metascreener/main.py`: no.** The trace above is airtight —
a sanitised non-empty string is in `os.environ` before any plugin module is
imported, and nothing ever unsets it.

The engine-level handling nevertheless exists and is correct:
`::_has_openai_key` is `bool(os.environ.get("OPENAI_API_KEY","").strip())` —
`False` on empty *or* whitespace-only — and `run_m1_llm_for_criterion` then logs
one line and returns `{}`. The EL/IL UI disables Run after bundle load and shows
`messagebox.showerror("Missing OPENAI_API_KEY", …)` — both reachable only by
importing `ELView` outside `MetaScreenerApp`.

**Exact consequence for a local server that needs no key: the user must invent a
placeholder, and it is enforced, not conventional.** Three independent
enforcement points: `validate_api_key` refuses empty and cancelling exits the
app; `_has_openai_key` would no-op the path; and **[installed SDK source]** the
SDK's own `OpenAI.__init__` raises `OpenAIError` when `api_key` resolves to
`None`. It **is** documented in three places (README, the row-3 label,
`LOCAL_PROVIDER_HINT`) and pinned by
`tests/test_api_key_validation.py::TestAcceptance::test_local_provider_placeholders_are_accepted`
over `["ollama","llama-cpp","vllm","not-needed","x"]`. **This part of the
local-provider story is in good shape.** What is not is that the placeholder buys
nothing without `OPENAI_BASE_URL`, which the GUI cannot set.

#### A5.4 The wave-1 "documented local-provider workflow" — located, quoted, sized

It is a README section plus two doc rows and an FAQ entry. The load-bearing
sentence, verbatim from `README.md`:

> "Switching providers requires no code change: set the `OPENAI_BASE_URL`
> environment variable to the target endpoint and ensure `OPENAI_API_KEY` is
> non-empty (most local servers ignore the key value but require it to be set).
> The **Model** field in metaScreener's EL/IL Settings panels then selects which
> backend model to use."

and the opening claim:

> "metaScreener targets any **OpenAI-compatible API endpoint**. The default
> backend is OpenAI's hosted API, but the same Python client transparently
> supports: - **Hosted commercial APIs** — Azure OpenAI, DeepSeek… - **Locally
> hosted models** — open-weight models served via compatible inference frameworks
> such as Ollama, llama.cpp, and vLLM."

with an honest caveat already present:

> "> **Note**: open-weight model compatibility with the evidence gating protocol
> (which requires models to produce verbatim substring quotations) has not been
> formally tested."

`docs/faq.md`: *"Yes, for any OpenAI-compatible endpoint. Set `OPENAI_BASE_URL`
in your `.env` … Local models that don't expose an OpenAI-compatible interface
are not currently supported out of the box but can be reached through a proxy."*
`docs/installation.md` carries the `OPENAI_BASE_URL` row.

**How far the abstraction actually reaches:**

| Layer | Reality at `f952e69` |
|---|---|
| Redirecting EL/IL/harmoniser traffic to another OpenAI-compatible host | **Works** — via the SDK fallback. No code change needed. The README sentence is *literally* true. |
| Loading `OPENAI_BASE_URL` from `.env` | **Works** — the loader is generic and runs before plugin import. |
| Entering a placeholder key through the GUI | **Works** — wave 1's fix. |
| Choosing the local model name through the GUI | **Works** — the Entry is free text. |
| Setting the endpoint through the GUI | **Does not exist.** |
| Seeing which endpoint is in effect | **Does not exist.** |
| Recording which endpoint/model produced a decision | **Does not exist.** |
| Request-shape portability for EL/IL | **Good** — the narrowest possible surface, and the largest single reason the claim survives. |
| Request-shape portability for plugin 01 | **Poor, and undisclosed.** |
| Behavioural portability of the evidence gate | **Untested, and the README says so.** |

**Honest sizing of the head start: real but narrow.** The transport is genuinely
provider-agnostic for EL/IL, one environment variable away, and the placeholder-key
barrier is gone. What is missing is everything *between that variable and the
user* — no control, no display, no record, no persistence — plus one plugin whose
request shape is not portable at all, plus the fact that the mechanism is a
third-party default the repository neither declares nor tests. **The
documentation describes the finished feature; the code has the plumbing and none
of the fixtures.**

`CHANGELOG.md`'s F-08 entry is accurate and carefully scoped — it claims the
*section* was unreachable and that the *dialog* now passes placeholders, and does
**not** claim the section is now reachable through the GUI. `tests/test_api_key_validation.py`
pins eight properties of the three pure functions and, correctly per its own
docstring, nothing about the Tk dialog. **What nothing anywhere pins is that
`OPENAI_BASE_URL` is honoured** (C-7).

---

### A6 Request/response contract

#### A6.1 The full prompt as rendered

`plugins/06_el/prompt.py::_build_llm_messages_for_criterion` returns exactly two
messages. The **system** message is five concatenated literals; the resulting
single-line value:

```
You are scoring research items against ONE screening criterion. For each item,
answer with JSON only. Keys per item: a_id, decision ('meet'|'not_meet'|
'uncertain'), confidence (0..1), field ('title'|'abstract'|'keywords'), quote
(exact substring from that field), span [start,end]. Return a JSON list of
objects, nothing else.
```

Note what is **absent**: no statement of the criterion's polarity semantics
(whether "meet" means include or exclude — the caller decides that from
`c.ctype`), no instruction that every input `a_id` must be answered, no
instruction that `span` must index the quoted field, no example, no
refusal-handling instruction, no length guidance.

The **user** message is `json.dumps({"criterion": c_pack, "items": items_pack},
ensure_ascii=False)`. `c_pack` has 8 keys in order: `id` (no default — `KeyError`
if missing), `type` (`"exclude"`), `operator` (`"llm"`), `target` (`"abstract"`),
`what` (`[]`), `how` (`"llm"`), `label` (`""`), `threshold` (`0.6`). On the real
path `how` is always identical to `operator` — a redundant key. `items_pack` is
one object per record: `{"a_id", "title", "abstract", "keywords"}`, each text
field `s[:trunc_chars]` — a hard character slice, no token awareness, no word
boundary, **no ellipsis marker**, so the model cannot tell a truncated field from
a complete one.

**All three text fields are sent for every criterion regardless of the
criterion's `target`.** `run_el_screen`'s own comment documents this as the reason
the cache key had to move to hashing the rendered prompt.

**Are EL and IL templates byte-identical? The function bodies are; the modules are
not.** Both files are 2484 bytes and differ in exactly two places: the module
docstrings and `PROMPT_VERSION` (`"EL_v1_jsonlist"` vs `"IL_v1_jsonlist"`). From
`def _build_llm_messages_for_criterion` to the final `return` they are identical
byte for byte. The code's own account, from `plugins/_common/llm_client.py`:

> "The body is byte-identical between EL and IL today, but is duplicated
> deliberately so the two stages' prompts can evolve independently."

Consequence worth stating: because the only differentiator reaching the model is
`c_pack["type"]` and the criterion wording, **the model is given no stage identity
at all**. `PROMPT_VERSION` differs only so the two caches cannot collide — which
it does correctly (`tests/test_cache_key.py::test_el_and_il_keys_differ`).

#### A6.2 How the answer is parsed

`plugins/_common/llm_client.py::_parse_llm_json_array` has three tiers.

**Path 0 — fence stripping**, conditional on `t.startswith("```")` *after* the
outer `.strip()`. Opening regex `^```[a-zA-Z0-9]*\s*` accepts a purely
alphanumeric language tag, so ```` ```json ````/```` ```JSON ````/```` ```json5 ````
strip cleanly but ```` ```json-lines ```` leaves `-lines` behind. Closing regex
`\s*```$` uses `$` without `re.MULTILINE`, so trailing prose leaves the fence in
place. **A fence preceded by any prose at all is not stripped** (the
`startswith` test fails).

**Path 1 — direct `json.loads`**, accepting only a top-level **list**, with the
`return` *inside* the `isinstance(val, list)` branch. Easy to miss: if the text
parses as a list, path 3 is **never tried**, even when the list yields zero dicts.

**Path 3 — first bracketed block**, regex `\[\s*\{.*\}\s*\]` with `re.S`. It
requires `[`, optional whitespace, `{` — so it will not latch onto a numeric
array — and `.*` is **greedy**, matching from the first such `[` to the **last**
`}` in the whole text.

| Model output | Path | Returns |
|---|---|---|
| `[{"a_id":"1",…}]` | 1 | the list |
| fenced `[{…}]` | 0 → 1 | the list |
| `Here you go:\n[{…}]` | 1 fails → 3 | the list |
| fenced then `Hope that helps!` | 0 strips opener; 1 fails; 3 recovers | the list |
| `[]` | 1 | `[]` — **path 3 never tried** |
| `[1, 2, 3]` | 1 → filter drops all | `[]` — path 3 never tried |
| `[[{…}]]` | 1 → filter drops inner list | `[]` — path 3 never tried |
| a **bare object** `{"a_id":…,"span":[0,5]}` | 1 not a list, no exception; 3 needs `[`+`{` | `[]` |
| `{"rows":[{…},{…}]}` | 1 falls through; 3 matches | **the inner list — silently accepted** |
| two arrays in one reply | 3's greedy `.*` spans both; `json.loads` fails | `[]` |
| a refusal | 1 fails; 3 no match | `[]` |
| truncated mid-JSON | 1 fails; 3 no match | `[]` |
| trailing comma `[{…},]` | 3 matches; `json.loads` fails | `[]` |

So an object *wrapping* a list works by accident while a bare object and a
trailing-comma list both yield `[]`, indistinguishable downstream from "the model
answered nothing usable" (C-37).

#### A6.3 Required vs defaulted response fields

All from the parse loop in `run_m1_llm_for_criterion`.

| Field | Required? | Coercion / clamp / whitelist | Default |
|---|---|---|---|
| `a_id` | **Required and gating** | `_safe_str(...).strip()`, then `if not a_id or a_id not in idx_map: continue` — the object is **discarded silently**. `idx_map` keys are **every item in the `items` argument, not just the current batch** — the mechanism of C-1. An integer `12` coerces to `"12"`. | none — dropped |
| `decision` | No | `_safe_str(obj.get("decision","uncertain")).strip()`, then whitelist `{"meet","not_meet","uncertain"}`. **No case-folding.** | `"uncertain"` |
| `confidence` | No | `float(...)` in `try/except → 0.0`, then clamped to `[0.0, 1.0]`. `"0.9"` succeeds; `"high"` → 0.0; `true` → 1.0; `-3` → 0.0; `7` → 1.0. | `0.0` (never usable against a 0.6 threshold) |
| `field` | No | `.strip().lower()`, then whitelist `{"title","abstract","keywords"}` — **is** case-folded | `"abstract"` |
| `quote` | No | `_safe_str(...)` — no strip, no length cap, no minimum | `""` → `valid_quote=False` |
| `span` | No | must be a list of exactly two `int`s. Floats rejected. Note `isinstance(True, int)` is True, so `[true,false]` is accepted | `None` |
| `valid_quote` | Derived, not read | `_quote_in_text(quote, fld_txt_prompt)` against the **`cur_trunc` in force for the call that produced this answer** | `False` |
| `used` | Derived | `True` for any object surviving the `a_id` gate | `False` for back-fills |
| `error` | Derived, terminal failure only | `str(e)` | key absent |

**The `decision` whitelist is not lowercased while `field` two statements later
is.** A model answering `"Meet"`, `"MEET"`, `"Not_Meet"` or `"not meet"` has
**every decision silently rewritten to `"uncertain"`**, and the gate then refuses
it — so every record becomes `PASS_FLAGGED`/`REVIEW` with `used: True`, a *valid*
quote and a *high* confidence sitting in the evidence JSON: an internally
contradictory audit record, with no log line and no count anomaly. This matters
most for exactly the local-model scenario, where format discipline is weakest and
there is no `response_format` to lean on. Fix is one `.lower()` (C-5).

**`span` is never validated against the quote.** Nothing checks
`fld_txt[span[0]:span[1]] == quote`, or `span[1] > span[0]`, or `span[1] <=
len(fld_txt)`. It is then written into the evidence JSON and the exported cache.
**[measured]** in `tests/golden/el_cache_v3.1.0.json`, **169 of 170** entries have
`span[1]-span[0] != len(quote)` — and that is `gpt-4o-mini` at temperature 0
(C-11).

#### A6.4 Behaviour table

| Scenario | Path | Result-dict value | `used` | `error` | User told? |
|---|---|---|---|---|---|
| **Malformed JSON** | `_parse_llm_json_array` → `[]`; batch back-fill | all-uncertain | **False** | no | **No.** No log line at all; `progress` still emits `batch_done` |
| **Missing `decision`** | `.get("decision","uncertain")` | `uncertain`, other fields as returned | True | no | No |
| **`decision` outside whitelist** | silent rewrite | `uncertain`, but `confidence`/`quote`/`span` **kept as returned** | True | no | **No** |
| **Extra prose around the JSON** | path 3 recovers | normal | True | no | No — correctly |
| **Refusal** | 1 fails, 3 no match → `[]` | all-uncertain | **False** | no | **No.** Indistinguishable from genuine uncertainty |
| **Empty response / `content=None`** | `or "[]"` → `[]` | all-uncertain | **False** | no | **No** |
| **Empty `choices` array** | `IndexError` → generic except; neither predicate → terminal | all-uncertain **+** `error` | False | **yes** | **Yes**, one log line |
| **Transport error** | terminal on the **first** attempt, no retry | all-uncertain + `error` | False | yes | Yes, one log line |
| **Timeout** | `APITimeoutError` → terminal, no retry | all-uncertain + `error` | False | yes | Yes, one log line |
| **Rate limit (429)** | `is_rate` → halve, or step trunc down, sleep, retry | normal on success; all-uncertain + `error` on exhaustion | mixed | on exhaustion | Yes — each split/step logs |
| **Oversize context** | `is_big` → same ladder; **on a local server, often matches neither** | as above | as above | as above | as above |
| **Unknown / invented `a_id`** | `continue` | object **discarded** | n/a | no | **No** — no counter, no log |
| **`a_id` in the batch, absent from the reply** | back-fill `if (a_id, cid) not in out` | all-uncertain entry | **False** | no | **No** |
| **Same `a_id` twice** | second write overwrites | last object wins | True | no | No |
| **`a_id` from ANOTHER batch** | **accepted** — `idx_map` spans all items; quote validated against that record's real text | a verdict for a record this prompt never contained | **True** | no | **No.** See C-1 |
| **Cancellation mid-run** | `_check_cancel` at the top of the batch loop → `_Cancelled` → outer handler logs and `return out` | results already received are **kept** | mixed | no | Yes: "cancelled after i of n batches; keeping N result(s)" |

**Per-request timeout: none anywhere on the EL/IL path** — not on the client, not
on the request, no `with_options`. Effective behaviour is the SDK's 600 s read
timeout × up to 3 attempts (§A2.3).

---

### A7 The evidence gate

#### A7.1 Where it lives — two premise corrections

**The brief's premise is wrong in two respects.**

1. **`plugins/_common/evaluator.py` contains no evidence gate and is not on the
   EL/IL path.** Its own docstring: *"LLM evaluation is intentionally NOT
   implemented here: the deterministic (heuristics) stages EH and IH never invoke
   an LLM."* Its four symbols are `_get_first_nonempty`, `_eval_criterion`,
   `_eval_criterion_detail`, `_summarize_reason`; `valid_quote`, `confidence`,
   `threshold` and `quote` appear nowhere in the file. Its only consumers are
   `plugins/_common/runner.py` and the EH/IH plugins.
2. **There is no `OUTCOMES` constant in `plugins/_common/`.** `OUTCOMES` is
   defined twice, per stage, in the EL and IL screen modules.

The gate is a **two-part mechanism split across two modules**:

| Part | `path::symbol` | What it does |
|---|---|---|
| **Quote verification** | `plugins/_common/llm_client.py::run_m1_llm_for_criterion`, response-parsing loop | selects the field text, re-applies the same truncation the prompt used, calls `_quote_in_text`, stores the boolean as `valid_quote` |
| the predicate | `::_quote_in_text` | exact substring, else whitespace-collapsed substring |
| the normaliser | `::_normalize_space` | `re.sub(r"\s+", " ", s or "").strip()` |
| **Usability decision** | `plugins/06_el/screen.py::run_el_screen` | `usable = valid_quote and (confidence >= float(c.threshold)) and (decision in {"meet","not_meet"})` |
| | `plugins/07_il/screen.py::run_il_screen` | byte-identical line |

`_quote_in_text` has **exactly one production call site**. Everywhere else it is
re-exported or tested. `tools/eval_ingest.py` reads `quote_valid` out of the
evidence JSON but never recomputes it — it records, it does not gate.

Note for the register: `docs/llm-evaluation.md` cites the gate at
`plugins/06_el/screen.py:603`; at `f952e69` that line is
`progress_cb(ci / max(1, len(crits)) * 0.7)`. The `03_findings.md` rows for F-21
and F-62 cite `:547` and `:603` for the same thing. **All three are stale** — a
third independent instance of the rot the citation convention exists to prevent,
and this one is in a *published* document (C-38).

*(Two transcription errors corrected in wave 6b, in place, because neither was ever
true of anything: this cross-reference read **C-39**, which is the screenshot-rotation
candidate, where it means **C-38**, the false-documentation-claims cluster; and §A13.2's
table row spelled the variable `METESCREENER_CACHE_DIR`. Register coordinates for both,
since §B9's namespace has since been swept: **C-38 → F-123, F-124 and F-125**, and the
stale gate citations described here are item (j) of **F-125**, corrected in `bd2d92b`;
**C-39 → F-126**, still open. Nothing else in this document has been altered.)*

#### A7.2 What is compared, and which field's text

1. **Haystacks** are built once per invocation into `idx_map`: for each item,
   `{"title", "abstract", "keywords"}` — **always all three, for every criterion,
   regardless of that criterion's `targets`**.
2. **The field is chosen by the model, not by the criterion**:
   `field = _safe_str(obj.get("field","")).strip().lower()`, then silently
   **coerced to `"abstract"`** if not in the whitelist.
3. **Haystack** = `(idx_map.get(a_id) or {}).get(field) or ""`.
4. **Truncation re-applied** at `cur_trunc`, matching the prompt.
5. **Needle** = the model's raw `quote` string — untrimmed, unlimited, no minimum.

Two consequences, neither checked anywhere:

- **The criterion's `targets` do not constrain the field.** A `target=keywords`
  criterion can be satisfied by a quote the model attributes to `abstract`, and
  the gate will validate it there and accept it. `targets` is used only for the
  all-fields-empty → `MISSING` pre-check (C-12).
- **An unrecognised `field` is silently redirected to `abstract`**, so its quote
  is compared against text it did not come from — a guaranteed
  `valid_quote=False`, with the mis-attribution written into the exported
  evidence *as though the model had said `abstract`* (C-12).

#### A7.3 Normalisation — what IS and what is NOT normalised

`_normalize_space` is the *only* transform. There is no `unicodedata` import
anywhere under `plugins/`. Because Python's `re` `\s` is Unicode-aware, the
collapsed class is wider than it looks. **[measured]** behaviour:

| Class | Collapsed? | Consequence |
|---|---|---|
| Space, tab, CR, LF, FF, VT, runs | **Yes** | the intended fix; pinned by `tests/test_evidence_gating.py::TestQuoteInText::test_whitespace_normalized_match` |
| U+00A0 NBSP; U+202F; U+2000–U+200A; U+3000; U+2028; U+2029 | **Yes** | Safe. Includes the French thin space and the CJK full-width space. So the NBSP class an existing register row implies is broken is in fact **handled**. |
| **U+200B ZWSP, U+200C ZWNJ, U+200D ZWJ** | **No** | a faithfully-copied zero-width character on one side and not the other fails the gate |
| **U+FEFF / stray BOM** | **No** | a BOM surviving mid-field invalidates every quote spanning it |
| **U+00AD SOFT HYPHEN** | **No** | a model that normalises `re-\u00ADhabilitation` → `rehabilitation` fails |
| **Case** | **No** | pinned as intended by `::test_case_sensitive`. **[general knowledge]** re-casing is a common weaker-model behaviour |
| **Curly vs straight quotes** | **No** | **[measured]** `_normalize_space("don\u2019t") != _normalize_space("don't")` — fails on any possessive or contraction |
| **En/em dash vs hyphen** | **No** | **[measured]** `"a\u2014b" != "a-b"`. Note the contrast: `…prisma_citations_ai_v3_1.py::normalize_dashes` does exactly this normalisation for reference matching — the capability exists in the repository and is simply absent from the gate |
| **Ligatures** `ﬁ`/`ﬂ` | **No** | **[measured]** `"\ufb01n" != "fin"`. NFKC would fix this; NFC would not |
| **Accent composition** (NFD vs NFC) | **No** | **[measured]** unequal. Directly relevant to French, Spanish, Portuguese and Vietnamese corpora, and to macOS-originated files, which are canonically NFD |

**The gate fails closed**, so every one of these routes the record to
`PASS_FLAGGED`/`REVIEW` rather than to a wrong exclusion. The harm is not a false
decision; it is that the human-review queue silently inflates for reasons
unrelated to eligibility, **systematically worse for weaker and local models and
for non-English and PDF-derived corpora** (C-13).

*Refinement to the existing F-22 row rather than a duplicate finding:* the
recommended `unicodedata.normalize("NFKC", …)` is necessary and **not
sufficient**. It fixes ligatures, compatibility spaces/dashes and NFD accents; it
does **not** remove U+200B/U+200C/U+200D/U+FEFF/U+00AD (no compatibility
decomposition) and does **not** address case. A complete fix is NFKC **+**
stripping the zero-width/soft-hyphen set **+** `casefold()` **+** a dash/quote
fold.

#### A7.4 How truncation interacts with the gate

`cur_trunc = int(trunc_chars)` is set at the **top of each batch iteration**, so
it resets per batch. The prompt is rendered with that value and validation uses
the same value — the two expressions are character-for-character equivalent, so
**the quote is validated against exactly the bytes the model was shown for that
call. This is the single most important correctness property of the gate and it
holds.**

The step-down is *self-consistent* (prompt and haystack shrink together) but **not
comparable across records**: within one criterion sweep, one record may have been
judged on 1500 characters and its neighbour on 600, and **nothing in the evidence
JSON records which**. A reviewer replaying a bundle cannot reconstruct the window
a given verdict was formed in.

**Cache interaction.** `cur_trunc` never reaches the cache key: the key is
computed in the stage engine from the *configured* `trunc_chars`, and `cur_trunc`
is a local that is not returned. So an answer produced from a 600-character prompt
is stored under the hash of the 1500-character prompt, and the key's stated
contract — *"anything that changes what the model sees changes the key
automatically"* — is violated on exactly this path (C-10).

*"What if a cached entry is reused under a different `trunc_chars`?"* — the
premise needs qualifying. It **cannot** happen for a record where truncation
bites, because `trunc_chars` reaches the key *through the bytes it removes*: a
different setting renders different text and misses. It **can** happen for a
record whose three fields are all shorter than both settings — and that reuse is
**benign**: the model saw the same text either way. This is precisely why the
goldens captured at `TRUNC_CHARS=4000` remain meaningful against a default of
1500, as `docs/llm-evaluation.md` independently establishes (longest field 2927
chars; every deciding criterion targets `keywords`, longest 270). F-28's framing
of the mismatch as a *coverage* gap is accurate; the reason it is not also a
*correctness* gap is that identity.

`valid_quote` is never recomputed on a cache hit — the cached dict is copied
wholesale with only `setdefault("used", True)`. Sound, given that any change to
text or criterion changes the key.

#### A7.5 The 0.60 threshold — where, and by whom

| Site | Value | Role |
|---|---|---|
| `plugins/03_harmoniser/inference.py::DEFAULT_THRESHOLD` | `0.60` | **The authoring default.** `_validate_row` blanks it for EH/IH rows and writes `f"{DEFAULT_THRESHOLD:.2f}"` for EL/IL rows when the cell is empty; a present value must parse as a float in `[0.0, 1.0]` |
| `plugins/03_harmoniser/ui.py` (four sites) | `0.60` | re-applied when a row is created or switched to EL/IL |
| `plugins/06_el/screen.py::_parse_criteria_harmonized_csv` (and IL twin) | `0.6` | **consumer fallback** — a *different literal spelling* of the same constant |
| the two `prompt.py` builders | `0.6` | written **into the prompt** as `c_pack["threshold"]` — so the model is told the bar it must clear, and it is therefore also inside the cache key |
| `plugins/03_harmoniser/llm_refine.py` | `0.60` | prose in the refiner's system prompt |
| `plugins/_common/parser.py` | *none* | the EH/IH parser leaves `threshold=None`; EH/IH never use it |

**Who can set it: the per-criterion `threshold` column of
`criteria_harmonized.csv`, and only through plugin 03.**
`::HarmoniserView._on_double_click` admits `threshold` to the editable set, gates
it to rows whose stage is EL or IL, and opens a plain free-text Entry validated on
the next render. Editing the CSV by hand works identically.

**The EL and IL GUIs cannot set it.** Their Settings panels expose Model,
Temperature, Batch size, Trunc chars and Use cache — no threshold. Their criteria
tables display `threshold` read-only, and the double-click binding opens a detail
modal that edits nothing.

**Which wins:** the criteria-file value, always. The `0.6` literals fire only for
a blank or non-numeric cell, and in practice never, because the harmoniser
guarantees a value. **[measured]** in `tests/golden/criteria_harmonized_v3.1.0.csv`
all three `llm`-operator rows (`EC-2`, `EC-3`, `IC-1`) carry `'0.60'`.

**The comparison is `>=`, inclusive** — a model returning exactly `0.60` clears
the bar. `confidence` is read defensively twice: coerced and clamped in
`llm_client.py`, then re-floated with a `0.0` fallback in the screen module.
**[measured]** no cached confidence in either golden equals `0.60`, so flipping
`>=` to `>` would move no record and break no test (C-16).

*One finding this section surfaces that nothing else does:* **the threshold is
written into the prompt, so the model is told the bar it must exceed, and the
observed confidences cluster immediately above it.** **[measured]** 141 of 170 EL
confidences are exactly 0.9 against a threshold of 0.60; every EL value above the
bar is one of 0.7/0.75/0.8/0.85/0.9/0.95 and every value below is
0.1/0.2/0.3/0.4, with a gap straddling 0.60. Telling a model the bar and then
treating its self-reported number as an independent gate is a circularity (C-15).

#### A7.6 Every outcome the gate can produce

**Per-criterion status**, written into `evidence[c.id]["status"]`:

| Status | Condition | Evidence shape |
|---|---|---|
| `MISSING` | every one of `c.targets` blank on this row — decided **before** the gate, no LLM result consulted | `{"status":"MISSING"}` (1 key) |
| `UNCERTAIN` (non-LLM operator) | `c.operator != "llm"` | 2 keys |
| `UNCERTAIN` (gate refused) | `not usable` — `valid_quote` false, **or** `confidence < threshold`, **or** `decision == "uncertain"`, **or** no LLM entry at all | full 9-key shape |
| `MET` | `usable` **and** (`exclude` + `not_meet`) or (`include` + `meet`) | 9 keys |
| `FAILED` | `usable` **and** (`exclude` + `meet`) or (`include` + `not_meet`) | 9 keys |

There is no reachable fifth state: `usable` requires
`decision in {"meet","not_meet"}`, so both polarity branches always assign. The
three-shape inconsistency is F-64.

**Row-level outcome:**

```
if failed:                                                     → "OUT"
elif len(met) == len(crits) and not missing and not uncertain   → "PASS_CLEAN"
else                                                            → "PASS_FLAGGED" (EL) / "REVIEW" (IL)
```

plus `NOT_SCREENED` from the zero-enabled-criteria early return (F-34).
Survivorship is `outcome != "OUT"`, so `PASS_CLEAN`, `PASS_FLAGGED`/`REVIEW` and
`NOT_SCREENED` all pass forward. **Only `OUT` is an exclusion, nothing but a
`FAILED` criterion can produce one, and nothing but a fully-passed gate can
produce a `FAILED`.** That conjunction is the whole safety property; §B5 tests it
to destruction.

---

### A8 Cache

#### A8.1 The key composer, and its two per-stage curries

`plugins/_common/llm_client.py::_cache_key` is the only hashing site:

```python
def _cache_key(*, prompt_version: str, model: str, rendered_prompt: str,
               temperature: float = 0.0) -> str
```

The hashed payload is exactly a **four-key** JSON object, serialised with
`ensure_ascii=False, sort_keys=True, separators=(",", ":")` and SHA-256'd:
`{"prompt_version", "model", "temperature", "prompt"}`. Its docstring records
F-01 and states the design principle:

> "Enumeration was itself the bug — temperature and prompt version had each been
> bolted onto that list in separate earlier commits. Hashing the rendered prompt
> means anything that changes what the model sees changes the key automatically,
> so this class of defect cannot recur: criterion content, record text, field
> truncation and the prompt template are all covered without being named here."

and, on the parameter the brief asks about:

> "``temperature`` is hashed unconditionally now. It used to be appended only
> when non-zero…"

`::_render_prompt_for_key` produces `rendered_prompt` — a `json.dumps` of
`[{"role":…,"content":…}, …]` with `sort_keys=True`, deliberately avoiding builtin
`hash()` and dict ordering so the key is stable across processes (pinned by
`tests/test_cache_key.py::test_key_stable_across_processes` over three
`PYTHONHASHSEED` values).

The per-stage curries `plugins/06_el/screen.py::_cache_key` and
`plugins/07_il/screen.py::_cache_key` have a **different signature** — `model`,
`criterion`, `item`, `trunc_chars`, `temperature` — and render the prompt
themselves, for **one** item. `prompt_version` is baked in; `trunc_chars` is
present but only as an argument to the prompt builder, **never hashed by name**.
**[measured]** the two curry bodies are character-for-character identical; what
differs is only the module namespace through which `PROMPT_VERSION` and
`_build_llm_messages_for_criterion` resolve. `model=model` is verbatim
pass-through — neither curry bakes it in nor drops it.

The key is computed **twice** per (item, criterion) pair on a miss — once at the
lookup site and once at the write-back site — each time re-rendering the full
one-item prompt.

#### A8.2 What the key includes — explicit checklist

| Ingredient | In the key? | Evidence |
|---|---|---|
| **Model name** | **YES**, by name | `"model": _safe_str(model)`. Pinned by `tests/test_cache_key.py::TestCacheKeySanity::test_model_change_changes_key`. **This is the fact that makes the brief's B4 question a false premise.** |
| **Provider / `base_url` / endpoint** | **NO** — neither named nor transitive | The hashed object has exactly four keys, none a URL; `_render_prompt_for_key` serialises only `role` and `content`. And `_openai_client_for` never passes `base_url`, so **no endpoint value exists in the process to hash** — see §B4.2 |
| **Temperature** | **YES**, by name, unconditionally | `"temperature": float(temperature)`. Pinned by `::test_temperature_change_changes_key` |
| **`prompt_version`** | **YES**, by name | curried from each stage's `PROMPT_VERSION`; because the two differ, an identical criterion+item cannot collide across EL and IL |
| **Rendered prompt** | **YES** — but a **one-item render**, not the prompt actually sent | covers the system-message text, the whole `c_pack`, and the item's four fields |
| **Criterion content** (`type`, `operator`, `target`, `what`, `label`, `threshold`) | **YES**, transitively | pinned per-field by `tests/test_cache_key.py::TestEditedCriterionContentInvalidatesCache` — the F-01 regression |
| **Criterion `id` alone** | **YES**, transitively — and it was F-01's entire subject | `c_pack["id"]` is in the rendered prompt. Called out explicitly because a reader will look for it |
| **The system-message template text** | **YES**, transitively | it is message 0 of the rendered list; a template edit changes the key without `PROMPT_VERSION` moving |
| **Record text** (`title`, `abstract`, `keywords`, `a_id`) | **YES**, transitively — all three fields, regardless of the criterion's `target` | pinned by `::test_non_target_field_change_still_changes_key` |
| **`trunc_chars`** | **NOT named. Transitive, and only conditionally so.** | It reaches the key only *through the bytes it removes*. If every field is shorter than both candidate values the renders are byte-identical and the keys equal — semantically right, but not "trunc_chars is in the key" |
| **`batch_size`** | **NO. Not named, and not covered transitively.** | The curry always renders `[item]`. The hashed prompt is a **synthetic one-item render that was never sent** whenever `batch_size > 1` (§A8.3) |
| `top_p`, `seed`, `max_tokens`, `response_format`, `logprobs`, `n`, `stop`, service tier, any other decode parameter | **NO** — and none is ever sent | §A2.5 |
| SDK / `openai` package version | **NO** | and unrecoverable retroactively (C-41) |
| `OPENAI_API_KEY`, account, org | **NO** | correct — but two tenants share one keyspace |
| Stage label | only transitively, via `PROMPT_VERSION` | `stage=` is used for log prefixes only |
| Bundle identity, `local_id` ordering, run timestamp | **NO** | `a_id` is in the key only because the prompt carries it |

**Per-item or per-batch? Per-item.** One key per `(item, criterion)` pair. Because
`batch_size` is absent and the render is fixed at one item, an entry produced under
`batch_size=50` is served, indistinguishably, to a run at `batch_size=1` and vice
versa. **Batch composition — which records co-occur in one prompt — is invisible to
the key.** The design is documented in a comment above the curry; the *consequence*
is not: a model's answer for item *k* can depend on the other 49 items in the same
request **[general knowledge]**, and the repository's own Limitations section
records an archived run where an entire 85-record criterion sweep returned one
repeated evidence span, which is what contamination looks like. So the docstring's
claim that hashing the rendered prompt means "anything that changes what the model
sees changes the key automatically" is **not quite true** — and a reviewer cannot
use `batch_size` to obtain an independent second opinion (C-17).

#### A8.3 Where the cache lives, and its two shapes

`plugins/06_el/plugin.py::EL_CACHE_REL` = `"cache/EL_cache.jsonl"`;
`plugins/07_il/plugin.py::IL_CACHE_REL` = `"cache/IL_cache.jsonl"`. **The cache is
a member of the bundle zip, not a file in a user cache directory.** Read path:
`ELView._load_bundle_inputs` checks `bundle.root + EL_CACHE_REL` against
`zf.namelist()` and feeds the decoded text to `::_load_cache_from_jsonl`, the whole
block wrapped in `except Exception: self.cache_map = {}`. Write path:
`ELView._build_next_bundle_zip` passes
`cache_text=(_dump_cache_to_jsonl(self.cache_map) if self.var_use_cache.get() else None)`
into `plugins/_common/bundle.py::_write_llm_stage_bundle`.

**Production format** — one JSON object per line, exactly two keys:

```jsonl
{"key": "<sha256 hex>", "val": {"used": true, "decision": "not_meet", "confidence": 0.9, "field": "keywords", "quote": "…", "span": [0,140], "valid_quote": true}}
```

`::_load_cache_from_jsonl` silently `continue`s on any line that fails to parse or
whose `val` is not a dict (F-33).

**Test-fixture format — not JSONL.** `tests/golden/{el,il}_cache_v3.1.0.json` is a
single pretty-printed object with a two-key envelope:

```json
{"_invocation": {"batch_size": 5, "model": "gpt-4o-mini", "trunc_chars": 4000},
 "cache": {"<sha256 hex>": {"confidence":…, "decision":…, "field":…, "quote":…, "span":…, "used":…, "valid_quote":…}, …}}
```

**[measured]** EL 170 entries / 76,992 B; IL 84 entries / 30,504 B. The union of
value keys across every entry in both files is exactly those seven — **no `error`
key in either capture**.

**How does the harness convert between the shapes? It does not. There is no
conversion.** `tools/capture_el_il_goldens.py::_capture_el`/`::_capture_il` build
the envelope in Python and `json.dumps` it; the regression tests `json.loads` it
and feed `raw["cache"]` straight in. **Neither ever calls
`_dump_cache_to_jsonl`/`_load_cache_from_jsonl`.** Consequently the *shipped*
serialisation pair is exercised by **no behavioural test** — their only
appearance under `tests/` is as name strings in `tests/test_imports.py` (C-19).

`_invocation` exists purely so the replay drives `run_*_screen` with the parameters
that produced the cache. It records no `temperature` and no `prompt_version`; the
replay relies on `temperature`'s 0.0 default and on `PROMPT_VERSION` being
unchanged (separately pinned).

#### A8.4 Lifetime

| Question | Answer |
|---|---|
| Evicted? | **Never.** `cache_out = dict(cache_in or {})`, then only ever assigned into |
| Expired / TTL? | **No.** No timestamp is stored per entry |
| Size-bounded? | **No.** No count or byte cap anywhere |
| Versioned at file level? | **No.** No header, no schema field, no version line. Versioning exists only *inside each key* via `prompt_version`, which makes superseded entries unreachable but does not remove them |
| Per-bundle or global? | **Per-bundle, and per-stage within it.** No global/user-level cache path exists |
| Growth | **Monotonic.** Every superseded entry — from an earlier model, an earlier criterion wording, an earlier prompt version — is re-read and re-written into every subsequent bundle forever, and an EL cache is carried verbatim into the post-IL bundle. A reader has no way to tell live entries from dead ones, because nothing in the file records which model or prompt version produced any of them (C-18) |
| What invalidates it | any change to the model, the temperature, the criterion's `id/type/operator/target/what/label/threshold`, the record's `local_id/title/abstract/keywords`, the prompt template, `PROMPT_VERSION`, or a `trunc_chars` change that actually alters the sliced bytes — **plus** exporting with "Use cache" unticked, which *deletes* it (below) |

**Running a stage with "Use cache" unticked deletes the bundle's existing cache
file.** `::_write_llm_stage_bundle` builds `skip_exact = {root + rel for rel in
written}` and then unconditionally does `skip_exact.add(root + cache_rel)`. When
`cache_text is None`, `cache_rel` is not in `written` but **is** in `skip_exact`,
so the incoming bundle's `cache/EL_cache.jsonl` is excluded from the copy loop and
never re-written. One export with the box unticked silently discards an
accumulated cache that cost real money, with no warning and no manifest note.
Secondary effect: the manifest's `sha256` map retains its entry for the
now-absent member, and `::_verify_sha256_map` cannot detect this because it
iterates only over members that are present (C-20).

#### A8.5 How hits are accounted

**Premise correction: there is no `cache_hits` counter.** The string occurs at
exactly three places — two f-string log lines and one docstring. The number is
`len(cached_pairs)`, a local list rebuilt inside each per-criterion iteration. It
is emitted **once per criterion**, not once per run (a reader must sum the lines);
never accumulated into `counts`; routed to `log_cb` and thence to the Log tab text
widget; **never persisted** (no save action, no sidecar, no log member in the
bundle); and **absent from every report** — no CSV column, no XLSX cell, no
manifest field. **So a finished bundle contains no record of how many of its
decisions were served from cache versus paid for.**

The use-cache toggle defaults **on** (`DEFAULT_USE_CACHE` from
`SCREENA_{EL,IL}_USE_CACHE` unless in `{0,false,False,no,NO}`), is a
`ttk.Checkbutton` in EL/IL, and is read both at run time (`cache_in=self.cache_map
if use_cache else {}`) and at export time.

---

### A9 Provenance

**The answer to the question as posed: NO.** Given a finished bundle from a
completed run, a reader **cannot** determine which model, provider or endpoint
produced any EL or IL decision. The single strongest piece of evidence:
**[measured]** across the entire `plugins/` and `metascreener/` trees, the dict
key `"model"` occurs **exactly once** — in `::_cache_key`, inside the JSON that is
hashed and thrown away.

#### A9.1 What IS recorded

**Manifest, created by the Harmoniser** (`plugins/03_harmoniser/exporters.py::_build_manifest`,
packed by `plugins/03_harmoniser/bundle.py::export_screen_a_bundle`):
`bundle_schema` (`"screenA_bundle_v1"`), `created_at` (**local time, no offset**),
`created_by` (`"harmoniser"`), `inputs.{aggregate_filename, criteria_filename,
criteria_kind}`, `aggregate.{columns, id_column_guess, expected_columns,
rows_total_read, rows_valid_written, rows_invalid_skipped}`,
`criteria.{rows_total, rows_by_stage, enabled_by_stage}`,
`pipeline_state.{stages, history}`, `warnings`, `criteria_source_preview`, and an
`sha256` digest map. Notably: even though plugin 03 *has* an LLM refinement path,
`_build_manifest` takes no model parameter and records nothing about whether the
refinement ran or with which model.

**Amended by EH/IH** (`plugins/_common/bundle.py::_export_next_bundle_zip`):
`pipeline.stages[stage]`, a `pipeline.history[]` entry, `created_at`
**overwritten** with naive local time, `created_by = f"screen_a_{sl}_plugin"`,
`derived_from.zip_name`, and a refreshed `sha256`.

**Amended by EL/IL** (`::_write_llm_stage_bundle` + its two callers):
`pipeline.stages[stage]`, `pipeline_state.stages[stage]`, a `pipeline.history[]`
entry of **exactly seven keys** — `{stage, ran_at, counts, survivors_rows,
out_rows_full, cancelled, not_screened}` — `updated_at` (set by the views), and a
refreshed `sha256`. `cancelled` is **hard-coded `False`**; the views block export
on cancellation instead.

**`{el,il}_evidence_json` inner keys**, three shapes: `{status:"MISSING"}`;
`{status:"UNCERTAIN", note:"non-llm operator in EL stage"}`; and the LLM shape
`{status, decision, confidence, threshold, field, quote, quote_valid, span, used}`.
**The `error` string is not among them** — it exists only in the in-memory result
and, if caching, in the cache value (C-22).

**Cache value keys** — the artefact closest to a provenance record:
`used, decision, confidence, field, quote, span, valid_quote` (+ `error` on
terminal failure). **[measured]** confirmed as exactly that union across both
shipped fixtures.

**Report columns:** `reports/{EL,IL}_FULL.csv` = the parse header plus
`{stage}_outcome`, `_failed_ids`, `_missing_ids`, `_met_ids`, `_uncertain_ids`,
`_reason_summary`, `_evidence_json`; `_SURVIVORS.csv` and `data/current.csv` = the
parse header only; the XLSX stage sheets from
`plugins/07_il/plugin.py::CONTRACT_STAGE_SHEET_COLS`; the FINAL sheet's per-stage
outcome/reason pairs.

**Run-log / sidecar files: none exist.** The Log tab is a `tk.Text` widget; there
is no save action, no log file, and no log member in the bundle.

#### A9.2 What is NOT recorded

| Item | Recorded in any EL/IL output? |
|---|---|
| **Model name** | **NO.** `model` is a parameter of `run_*_screen` and of `run_m1_llm_for_criterion`; it is never placed in a row, in `evidence[c.id]`, in the manifest, or in any written payload. `_write_llm_stage_bundle` has no `model` parameter |
| **`base_url` / provider / endpoint** | **NO.** The value is not even available in-process to record, because `_openai_client_for` never passes it |
| **Temperature** | **NO.** Hashed into the key; written to no artefact |
| **`prompt_version`** | **NO.** Reaches only `_cache_key` and the prompt builder |
| **`trunc_chars` / `batch_size`** | **NO** in any shipped artefact. Present only in the *test fixtures*' `_invocation` |
| **Effective truncation after a step-down** | **NO.** `cur_trunc` is a local, not returned, not logged per item |
| **SDK version** | **NO.** `openai>=1.40.0` is a floor, not a record |
| **Cache hit/miss statistics** | **NO.** Log line only |
| **Which decisions came from cache vs a live call** | **NO.** `run_el_screen` merges both into one dict and `ev.setdefault("used", True)` on the cache path makes them converge |
| **Timestamp of the EL/IL run** | **YES, partially** — a *stage-level* `history[].ran_at` (UTC, second resolution) and `manifest.updated_at`. No per-decision or per-batch timestamp |
| **`created_by` / `derived_from` for EL/IL** | **NO** — this is F-82 |
| **Whether plugin 03's LLM refinement ran, and with which model** | **NO** |

#### A9.3 The asymmetry, and its consequence

| | model | provider | temperature | prompt_version | trunc_chars | batch_size |
|---|---|---|---|---|---|---|
| In the cache **KEY** | ✅ named | ❌ | ✅ named | ✅ named | ~ transitive only | ❌ |
| In the cache **VALUE** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| In `{el,il}_evidence_json` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| In any report column | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| In the manifest | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

Model, temperature and prompt version are used to *look up* an answer and then
discarded, surviving only as pre-image material inside a 64-hex digest that cannot
be inverted. **Consequence, stated plainly: a bundle cannot be attributed to a
model after the fact.** A reviewer holding a completed post-IL bundle can read
every decision, every confidence, every quote and every span, verify with
`sha256` that no file has changed — and still not answer "which model said this?",
"at what temperature?", or "was this OpenAI's `gpt-4o-mini` or a local Gemma behind
an OpenAI-compatible endpoint?" (C-3).

**The irony worth recording:** the test harness needed exactly the three
provenance fields the production artefact omits, and had to invent a private
envelope to hold them.

#### A9.4 Is the fixtures' `"model"` field a property of the harness or the product?

**Of the capture harness, unambiguously.** It is not part of any shipped artefact.

| | Production `cache/{EL,IL}_cache.jsonl` | `tests/golden/{el,il}_cache_v3.1.0.json` |
|---|---|---|
| Shape | JSONL, `{"key","val"}` per line | one pretty-printed object |
| Envelope | none | `{"_invocation", "cache"}` |
| `model`, `trunc_chars`, `batch_size` | **absent** | present, inside `_invocation` |
| Writer | `::_dump_cache_to_jsonl` | `tools/capture_el_il_goldens.py::_capture_el`/`::_capture_il` |
| Reader | `::_load_cache_from_jsonl` | `tests/test_{el,il}_regression.py::_load_cache_envelope` |

`MODEL`, `TRUNC_CHARS`, `BATCH_SIZE` are module constants of the capture tool, not
values read back from the cache — the harness **asserts** the provenance rather
than recovering it, precisely because the production format does not carry it.

#### A9.5 Relation to F-82 — confirmed, and it does not cover this

F-82 (Low, hygiene) reads: *"EL/IL bundles omit the `created_by` and
`derived_from` provenance that EH/IH stamp."* **Confirmed exactly at `f952e69`:**
`_export_next_bundle_zip` sets `created_at`, `created_by` and
`derived_from.zip_name`; `_write_llm_stage_bundle` sets none of the three, and its
two GUI callers set only `updated_at`.

**Extension — F-82's scope is narrower than the provenance gap, and the difference
matters for the destinations.** F-82 is about *which plugin* last wrote the bundle.
Fixing it as proposed would make a post-IL bundle correctly say
`created_by: screen_a_il_plugin` — and the bundle would **still** not name the
model, the endpoint, the temperature or the prompt version. Those are not fields
EH/IH have and EL/IL lack: **no stage has them, because no stage produces them**,
and EH/IH have no need of them. So the missing-provenance problem is specific to
the two LLM stages and **is not a symmetry defect at all; it is an absence.** It
should be recorded as its own finding rather than folded into F-82 (C-3, and §B8).
No contradiction with F-82 was found.

---

### A10 Determinism controls

#### A10.1 Every place temperature is set

| Layer | Site | Value |
|---|---|---|
| Wire | `::run_m1_llm_for_criterion` → `_call_once` → `create(temperature=temperature)` | pass-through |
| Function default | `::run_m1_llm_for_criterion` signature | **0.0** |
| Cache key | `::_cache_key`, hashed unconditionally | **0.0** |
| Stage orchestrator | `run_el_screen` / `run_il_screen` | **0.0** |
| Stage curry | both `screen.py::_cache_key` | **0.0** |
| **GUI (live)** | `ELView` / `ILView`: `tk.DoubleVar(value=0.0)`, `ttk.Spinbox(from_=0.0, to=2.0, increment=0.1, format="%.2f")`, read in a `try/except` → 0.0 | **user-adjustable 0.0–2.0** |
| GUI (standalone shells) | Model/Batch/Trunc/Use-cache only — **no temperature widget**, and `temperature=` is not passed | **0.0, not adjustable** |
| Golden capture | passes `model`, `trunc_chars`, `batch_size` only | **0.0** |
| Plugins 03 and 01 | hard-coded `temperature=0` | **0, not adjustable** |

**Temperature is user-adjustable in the GUI, in EL and IL only.** The Spinbox
carries a caption directly under it, in both stages, verbatim:

> `(0.0 = deterministic; non-zero invalidates cache)`

#### A10.2 Seed, `top_p`, or any other decode parameter — **none, anywhere**

`temperature` is the **only** decode control the application has and the only one
it exposes. `top_p` and everything else is whatever the server defaults to —
silently, unlogged, unrecorded. *Correction to an earlier reading in this wave:*
the identifier `seed` does appear elsewhere in the repository, in unrelated senses
— a partition seed in `tools/eval_grid_generator.py` and
`tools/eval_grid_filler_synthetic.py`, a `PYTHONHASHSEED` value in
`tests/test_cache_key.py`, and a local variable holding criterion text in
`plugins/03_harmoniser/ui.py`. **No `seed` is passed to any model call.** Note the
asymmetry this creates against the repository's own local-provider story: `seed`
is the one parameter that *would* buy meaningful run-to-run stability on a
self-hosted server **[general knowledge]**, and it is precisely the one never
sent.

#### A10.3 The code's own reproducibility claim, quoted and assessed

`::run_m1_llm_for_criterion` docstring, verbatim:

> "Note that strict determinism is not guaranteed even at 0.0 due to
> hardware-level floating-point non-determinism in model inference; the cache
> layer (keyed on temperature for non-zero values) is the primary reproducibility
> safeguard."

**The conclusion is right, one premise is incomplete, and one parenthesis is now
factually stale.**

- *"strict determinism is not guaranteed even at 0.0"* — **accurate, and
  creditably honest.** `03_findings.md` singles this passage out as a strength and
  the credit is deserved.
- *"due to hardware-level floating-point non-determinism"* — **an incomplete cause
  stated as if complete.** Float non-associativity under varying kernel/batch
  shapes is real **[general knowledge]**, but for a hosted API it is not the
  dominant mechanism: silent model rotation behind a stable alias, MoE routing
  that depends on co-batched requests, and serving-stack changes all move outputs
  further **[general knowledge]**. The repository's own FAQ implicitly knows this
  ("may differ if the model has been updated between runs"). A reader takes away
  "essentially deterministic, modulo float noise"; the honest statement is "not
  reproducible without the cache."
- *"(keyed on temperature for non-zero values)"* — **stale, and contradicted by
  its own module.** `::_cache_key`'s docstring says the opposite, deliberately.
  Two docstrings in one file describe the same key differently; the `_cache_key`
  one is correct (C-26).

#### A10.4 What the docs assume — quoted

**`README.md`, the strongest and most careful statement in the project:**

> "The deterministic 98.3% of that funnel is exactly reproducible from the
> committed goldens; the LLM stages are not, and replaying the goldens today
> yields 80 rather than 73."

**`docs/llm-evaluation.md`:**

> "**Replaying the committed goldens gives 80, not 73.** Both numbers are reported
> here rather than silently reconciled, because they come from different
> executions and only one of them is reproducible."

> "Ordinary run-to-run variation in model confidence is sufficient on its own to
> move seven records across a 0.60 threshold, and the archived run of 2026-05-07
> shows that **confidence values are not stable between runs at all**."

> "**No temperature sweep.** Decisions are taken at the LLM's default temperature
> for the bundle. Run-stability under repeated sampling at non-zero temperature
> has not been measured."

**`docs/faq.md`:**

> "Three things are needed: the input record set, the harmonized criteria, and the
> seed (where applicable). Bundles produced by the LLM stages also need the cache
> to hit zero-cost reproducibility…"

> "For reproducibility, pin to a prompt version explicitly in your bundle
> manifest."

Two documentation problems fall straight out. **Both of the FAQ sentences point at
machinery that does not exist:** no seed is sent anywhere, and the manifest carries
no prompt-version field — so "pin to a prompt version explicitly in your bundle
manifest" is unperformable. And the UI caption **"0.0 = deterministic"** is a
stronger claim than the code's own docstring will make, shown to the user at the
exact moment of choice and echoed into `docs/usage.md`'s figure caption. Its second
clause is also imprecise in two directions: temperature is hashed
unconditionally, so *any* change invalidates (0.7→0.8 too); and a non-zero
temperature *partitions* the cache rather than invalidating it — the 0.0 entries
survive untouched and become live again the moment the user returns to 0.0 (C-27).

#### A10.5 Is the story "the model is deterministic" or "the cache is the artifact"?

**Unambiguously "the cache is the artifact", and the repository is roughly
two-thirds honest about that.**

Nothing in this application constrains the model's output distribution beyond
`temperature=0.0`: no seed, no `top_p`, no pinned model snapshot, no
`response_format`, no recorded provider. Reproducibility is achieved **by not
calling the model again**. What the repository calls reproducibility is *replay*.

| | "The model is deterministic" | "The cache is the artifact" |
|---|---|---|
| What must be archived | inputs + criteria + model name | inputs + criteria + **the cache** |
| Lose the cache | recoverable | **irrecoverable — the decisions are gone** |
| Independent replication | another lab reruns and matches | another lab **cannot** match; it can only verify your cache reproduces your reported numbers |
| What a manifest must record | the model | model, temperature, prompt_version, trunc_chars, **and the cache digest** |

**The repository has already lived the consequence and written it down:** the
manuscript's 73-record result cannot be reproduced because "its bundle, its
manifest, its response cache — were not archived and will not be recovered." That
is the failure mode of a cache-as-artifact design meeting a documentation set that
never told the user the cache *was* the artifact.

Where the project is honest: `README.md`'s qualifier, all of
`docs/llm-evaluation.md`'s reproducibility section, its §Limitations, and
`::_cache_key`'s docstring. This is genuinely better than most comparable tools.
Where it is not: the UI's "0.0 = deterministic"; `docs/installation.md`'s false
claim that the model is in the manifest; the FAQ's seed and prompt-version advice;
and the floating-point attribution. Each nudges the reader toward the left column
while the code implements the right.

---

### A11 Test coverage of A1–A10

**Method, and what these numbers are not.** 27 `test_*.py` modules plus
`conftest.py` (the brief's "28 files" is right if `conftest.py` is counted).
Baseline 422 passed / 4 skipped; **[measured]** the 4 skips are all
`tests/test_plugin_contract.py::TestFactorySignature::test_make_plugin_is_callable_with_one_argument`
for the four `Plugin`-class plugins — **the EL and IL golden tests do run.**

`coverage` and `pytest_cov` are **not installed on this machine**, so F-12's
coverage.py figures could not be reproduced. A `sys.settrace` harness produced two
mutually inconsistent numbers (32.6% whole-suite vs 53.0% per-module-union) — an
artifact of the instrument, compounded by the −1 runtime line shift in §A11.4.
**No coverage percentage for `plugins/_common/llm_client.py` should be quoted
anywhere until it is re-measured under one instrument** (§B9 Q10). Every branch
verdict below is anchored on the `if`/`except` statement itself and does not
depend on a metric.

Two further measurements, both read-only and offline: with a key set for the whole
suite and `_openai_client_for` replaced by a counter that raises — **422 passed,
4 skipped, 0 client constructions**. With `socket.connect`, `connect_ex` and
`getaddrinfo` all raising and a key set — **422 passed, 4 skipped, 0 socket
attempts**.

#### A11.1 A1–A10 → test map

| # | Topic | Verdict | Coverage |
|---|---|---|---|
| A1 | Call sites | **Partial** | `tests/test_imports.py::TestSharedHelpersOrigin` pins that EL/IL resolve `run_m1_llm_for_criterion` to `_common` and that the `stage`/`build_messages`/`temperature` kwargs exist; `::TestPerPluginPrompts` pins the builders' origin. **No test at all** for the other two call sites |
| A2 | Transport | **None** | `::_openai_client_for`'s body **never executes in the entire suite** — proven by line trace and by the 0-construction measurement. No test mentions `base_url` or `OPENAI_BASE_URL` except one assertion about dialog *text* |
| A3 | Model naming | **Partial, and the production default is unpinned** | `::test_model_change_changes_key` covers the cache-key role. **Nothing asserts `DEFAULT_MODEL` in either stage**, nor the env overrides. Contrast `PROMPT_VERSION`, pinned twice per stage |
| A4 | GUI selection | **None** | No test instantiates `ELView`/`ILView`. `::TestPerPluginUI` asserts only where the classes are *defined* (AST-level), because `ttk.Frame` is a `MagicMock` under `conftest.py` |
| A5 | Key handling | **Partial** | 8 tests over the three pure functions. **None** for `_load_env_file`, `_save_env_key`, `_prompt_api_key_always` — the code that puts the key into `os.environ` and writes `.env`. **None** for `::_has_openai_key`, whose body never executes (C-40) |
| A6 | Request/response contract | **Partial, happy path only** | The parameter set is pinned **accidentally** by the fake client's keyword-only `create`. Nothing asserts that `temperature == 0.0` is what is sent. Response side: only the pure-JSON path runs |
| A7 | Evidence gate | **Incidental only** | `tests/test_evidence_gating.py::TestQuoteInText` covers the helper (10 tests over literal strings). **No test drives the gate itself.** It is exercised only by golden replay — see §A11.3 for what that does and does not establish |
| A8 | Cache | **Key: strong. Persistence: none.** | `tests/test_cache_key.py` is thorough — edited criterion content per field, criterion id, determinism, model, temperature, record text, non-target fields, truncation, hex shape, EL/IL separation, cross-process stability. **Zero coverage of persistence**: neither JSONL function ever executes |
| A9 | Provenance | **None — and nothing to assert** | The history entry has no model/temperature/prompt_version, so no test can assert what the artefact does not carry |
| A10 | Determinism | **Partial, and only of the deterministic layer** | cross-process key stability; temperature-in-key; byte-identity of downstream processing; prompt-construction stability. **Nothing tests model-output determinism** — nor could it without a model. No test asserts that no `seed` is sent |

#### A11.2 Reconciliation with F-12 — **partly stale in its headline, fully accurate in its substance**

F-12 reads *"The entire LLM interaction path is 0% covered … `run_m1_llm_for_criterion`
lines 157-375 … is never executed"*, evidenced at "197 stmts, 21%". It carries no
closure note. **The measurement predates wave 2**: `tests/test_cancellation.py` was
added by `9812f6d`, after the diagnostic landed at `250badd`.

| F-12 clause | Status at `f952e69` |
|---|---|
| "0% covered" / "never executed" | **Stale.** The function is executed by `tests/test_cancellation.py::TestLLMCancellationKeepsPaidResults` (3 tests) against a fake client |
| "batching" | **Stale.** Exercised: 20 items at `batch_size=5` → 4 batches; `chunked`, the batch loop and the bookkeeping all run |
| "429 handling" | **Still accurate — uncovered** |
| "adaptive splitting" | **Still accurate — uncovered** |
| "truncation reduction" | **Still accurate — uncovered** |
| "terminal-failure back-fill" | **Still accurate — uncovered** |
| "the golden tests short-circuit before it (`test_el_regression.py` unsets the key)" | **Correct in effect, wrong in mechanism** — see §A11.3 |

**The correct restatement is narrower and sharper: the happy path and the
cancellation path are covered; every error path and every response-salvage path is
not.** The fake client never raises, so no `except` clause inside the retry loop is
ever entered. Branch by branch, **uncovered**: `if not model:`;
`if not _has_openai_key():`; the `except` around client construction; the
`.cancelled`-attribute arm of `_check_cancel` (no caller in `plugins/` supplies
such an object); all three `progress` payloads; the unknown-`a_id` skip; the
`decision` whitelist rewrite; the `confidence` coercion `except`; the `field`
coercion; the malformed-`span` branch; the per-batch back-fill body; `is_rate` and
`is_big` classification; the halving requeue; the truncation step-down; **both**
backoff sleeps; the terminal mark-all-uncertain branch; and the inner
`except _Cancelled: raise` — which is not merely uncovered but **unreachable in
production** (§A2.4). **Covered:** the `.is_set()` arm, initial batching, the happy
`_call_once`, the valid parse loop, `break`, the outer `except _Cancelled`, and
`return out`.

Adjacent, same measurement: `::_openai_client_for` and `::_has_openai_key` bodies
**never execute**; `::_parse_llm_json_array` runs its happy path only (fence
stripping, the `json.loads` failure fallback, the bracket regex and the `return []`
give-up all never execute); `::_make_item_for_llm` **never executes at all** — EL/IL
build items inline, and the helper is only asserted to *exist* (C-32);
`::_load_cache_from_jsonl` and `::_dump_cache_to_jsonl` never execute.

One mechanical detail makes F-12 a hard gate rather than a soft one: the fake
client's `create(self, *, model, messages, temperature)` is keyword-only with no
`**kwargs`, so **the first added request parameter raises `TypeError` inside the
double and fails that suite.** The double must be generalised before the transport
changes.

#### A11.3 The replay-cache mechanism

**The headless harness.** `tests/test_el_regression.py::_el_to_csv` (IL twin):
`::_load_cache_envelope` reads `{"_invocation", "cache"}` and returns the halves;
corpus and criteria are read from the goldens with `encoding="utf-8-sig"`; the key
is popped and restored in a `finally`; `run_el_screen` is driven with
`model=invocation["model"]`, `trunc_chars=invocation["trunc_chars"]`,
`batch_size=invocation["batch_size"]`, `use_cache=True`, `cache_in=cache` — **all
three invocation parameters come from the fixture envelope, not from production
defaults** — and the output is serialised through the same writer as the EH/IH
goldens and compared byte for byte.

The docstring that explains it:

> "This test unsets ``OPENAI_API_KEY`` before invoking ``run_el_screen``. With no
> key, ``_has_openai_key()`` returns False and ``run_m1_llm_for_criterion``
> short-circuits to an empty result. Every (a_id, criterion_id) pair MUST
> therefore be served from the cache; any cache miss yields empty evidence which
> causes the byte-identity assertion to fail."

**Correction, measured: that docstring describes a fallback that is never
reached.** Instrumenting the exact replay path in-process:

```
EL: rows=85  enabled crits=[('EC-2','llm'), ('EC-3','llm')]
EL: log → "[EL] cache_hits=85 | to_call=0"  (twice)
EL: run_m1_llm_for_criterion invocations = 0   client constructions = 0
IL: rows=84  enabled crits=[('IC-1','llm'), ('IC-5','contains')]
IL: log → "[IL] cache_hits=84 | to_call=0"  then  "[IL] cache_hits=0 | to_call=84"
IL: run_m1_llm_for_criterion invocations = 0   client constructions = 0
```

The operative mechanism is `run_el_screen`'s guard `if c.operator == "llm" and
to_call:` — with a complete cache, `to_call == 0` and the function is **not
entered at all**, so `_has_openai_key()` is never consulted. **The unset-key step
is a correct second line of defence that has never been load-bearing.** F-12's
evidence cell and the test's own docstring both make the same misattribution.

Two facts the measurement surfaces. EL's 170 entries are exactly 85 records × 2
LLM criteria — a complete cache. IL's 84 are 84 records × **one** LLM criterion:
`IC-5` has `operator="contains"` and takes the non-llm branch, marked `UNCERTAIN`
by fiat. **So the IL byte-identity golden pins a stage where half the enabled
criteria never consult a model** (C-33).

**`tools/capture_el_il_goldens.py`.** Pins `MODEL = "gpt-4o-mini"`,
`TRUNC_CHARS = 4000`, `BATCH_SIZE = 5`, all hard-coded with **no CLI override**
(`main()`'s argparse declares only `--print-hashes`). It mirrors `conftest.py`'s
headless setup, parses the sample corpus, replays EH→IH to obtain EL's input, then
runs `run_el_screen` with `cache_in={}` — a cold cache, so every pair is a live
call — and writes six files. Its `__main__` gate requires a truthy
`OPENAI_API_KEY`; **any non-empty value passes**, so the placeholder-key convention
already satisfies it. Its docstring's claim that its three constants "must match
the values used in" the two test modules is **wrong**: those modules define no
`MODEL` and no `BATCH_SIZE` (both flow through `_invocation`); only truncation is
duplicated, as `PROMPT_HASH_TRUNC_CHARS = 4000`, and **nothing asserts it equals
`invocation["trunc_chars"]`** (C-33).

#### A11.4 Can the replay cache stand in for a live local model?

**What it can prove.** Given a fixed set of model outputs, byte-identity of
*everything downstream of the model*: cache lookup, the evidence gate,
per-criterion status, the `failed`/`missing`/`met`/`uncertain` partition, outcome
assignment, the reason prose, the 9-key evidence JSON, column order, and CSV
serialisation down to line terminators. Plus two model-independent properties:
prompt-construction stability (a SHA-256 over the assembled `messages`) and
cache-key stability including across processes.

**What it cannot prove.** Nothing whatsoever about a model's behaviour — no
accuracy, no calibration, no whether quotes are extractive, no JSON
well-formedness, no latency, no refusal behaviour. Nothing about **transport**: the
client is never constructed, so the goldens say nothing about whether
`OPENAI_BASE_URL` is honoured, whether a local `/v1/chat/completions` is
compatible, or what happens on connection failure. Nothing about the **error
paths** — replay is *structurally incapable* of covering them, because a cache hit
means no call. Nothing about **response-shape robustness** — the salvage tiers a
chattier model would exercise first never run. And nothing about the gate under
adversarial input: **[measured]** the captured caches contain **zero**
`decision == "uncertain"` entries, zero `used: false` and zero `error` keys, so the
third conjunct of `usable` is never exercised against a non-member value.

**The boundary, plainly: the replay cache is a fixture for the deterministic half
of the pipeline and a perfect one. It is not a model substitute, not a stub
*client*, and not a contract test for the LLM interface. A CI suite built only on
replay can be 100% green while the application is incapable of talking to any
endpoint at all — which is exactly the state of A2 today.**

**If the default model changed, would replay still work unchanged? Yes — and that
is the problem.** Traced input by input, the harness supplies `model` from
`invocation["model"]` (the literal `"gpt-4o-mini"`), `temperature` by omission
(0.0), `prompt_version` from the module constant, and the rendered prompt from the
goldens. **None is affected by a change to `DEFAULT_MODEL`.** **[measured]** the
full suite under `SCREENA_EL_MODEL=SCREENA_IL_MODEL=gemma3:12b` gives 422 passed /
4 skipped, identical to baseline; and grep confirms zero occurrences of
`DEFAULT_MODEL`/`SCREENA_EL_MODEL`/`SCREENA_IL_MODEL` anywhere under `tests/`. **The
failure mode is silence, not a red test.** That is the load-bearing conclusion for
Part B.

The converse asymmetry is the reassuring half: changing the **replay** model
changes every key → 0 hits → empty evidence → byte-identity fails **loudly**.
**[measured]** at `gemma3:12b`, `llama3.1`, or `T=0.1`, 0 of 170 EL and 0 of 84 IL
keys match. **The cache is model-specific by construction and cannot be silently
reused across a model swap** — so each candidate model needs its own captured
golden set, and each capture needs one live run against that model.

**A mechanical hazard that makes every line-number citation in this area
suspect.** `01_architecture.md` records, from a prior measurement, that
`metascreener/plugin_manager.py::_sanitize` *deletes* the `from __future__` line
before compiling, so every line below it shifts by one — measured, `run_el_screen`
is at disk line 335 and runtime `co_firstlineno` 334, with the same −1 shift in
`plugins/07_il/screen.py` and `plugins/_common/llm_client.py`. I verified the
mechanism at `::_sanitize`. Two consequences no prior section states: **any line
number obtained from a runtime source — a traceback, `co_firstlineno`, a
`sys.settrace` callback, a coverage report — is off by one from disk in exactly the
three files this diagnostic cites most**; and it is a second, stronger argument for
`path::symbol` than "line numbers rot", because here they are *wrong at the moment
of measurement*, depending on which import path produced them (C-28).

#### A11.5 CI

`.github/workflows/test.yml` is the only tracked workflow. Job `test`; triggers
`push`/`pull_request` on `main` plus `workflow_dispatch`; matrix
`os: [ubuntu-22.04, ubuntu-24.04, macos-14, windows-latest]` ×
`python-version: ["3.10","3.11","3.12","3.13"]` = **16 cells** (the brief is
correct); `fail-fast: false`; `timeout-minutes: 10`. Steps: checkout, setup-python,
`pip install -e ".[dev]"`, `python -m pytest tests/ -q`, then the three audit
tools. **There is no build job — PyInstaller is never run in CI.**

**Secrets / API keys: none.** No `env:` block, no `secrets.` reference anywhere in
`.github/`. **Can any test in CI make a network call?** No — and the guarantee does
not depend on the key being absent, per the two measurements in §A11's method note.
`pip install -e ".[dev]"` of course reaches PyPI; that is a network dependency of
the CI *run*, not of any test, and combined with F-15 it means each cell resolves
a different dependency set.

**Coverage is installed and never used.** `pytest-cov` is in
`[project.optional-dependencies].dev`, so every cell installs it; the pytest step
passes no `--cov`, no `--cov-report` and no `--cov-fail-under`. A regression of the
F-11/F-12 kind — a subsystem falling to 0% — is invisible to all 16 cells (C-30).

**One further hazard: `tests/conftest.py` has no network guard, and the suite's
cleanliness is incidental rather than structural.** **[measured]** flipping the
single `operator="contains"` literal in `tests/test_cancellation.py`'s
`TestELILReportCancellation` setup to `"llm"` reaches client construction — i.e. on
any developer machine with `OPENAI_API_KEY` set it would make a live, billable
call. An autouse fixture clearing `OPENAI_API_KEY`/`OPENAI_BASE_URL` and stubbing
`_openai_client_for` to raise would make the property structural (C-31).

---

### A12 Packaging and offline behaviour

#### A12.1 LLM-implicated dependencies

`pyproject.toml` and `requirements.txt` declare **the same nine packages with the
same single constraint**: `openai>=1.40.0`, and `requests`, `pandas`, `openpyxl`,
`pymupdf`, `pillow`, `pytesseract`, `rapidfuzz`, `langdetect` all **unpinned**
(F-15). `pyproject.toml` additionally carries `[dev] = ["pytest>=7.0",
"pytest-cov"]`, for which `requirements.txt` has no equivalent.

**`httpx` is declared nowhere in the repository** — nor `anyio`, `pydantic`,
`jiter`, `distro`, `sniffio`, `certifi`, `httpcore`, `h11`, `tqdm`,
`typing_extensions`. Every one is in the LLM path transitively via `openai`.
**[installed distribution metadata, third-party]** `openai 1.106.0` requires
`anyio`, `distro`, `httpx`, `jiter`, `pydantic`, `sniffio`, `tqdm`,
`typing-extensions`. Two are **compiled extensions**, not pure Python:
`pydantic_core` and `jiter` — both load-bearing, both shipped as binaries.

Note the discrepancy with the register: F-15 records that a fresh install on
2026-08-08 resolved to `openai 2.53.0`; this machine is at `1.106.0`. The
`>=1.40.0` constraint spans both, so **the committed `dist/` binaries and a fresh
`pip install` are not the same software**, and nothing records which one a given
artefact used.

#### A12.2 The two specs and `hook-plugins.py`

`metaScreener.spec` and `metaScreener-console.spec` are byte-identical apart from
`name=` and `console=`. Both set `datas = [('plugins', 'plugins')]`,
`hookspath=['.']`, `excludes=[]`, `upx=True` with `upx_exclude=[]`, a 30-name
`hiddenimports` literal beginning with `'plugins'`, `collect_data_files('certifi')`,
and `collect_all` for `requests`, `urllib3`, **`openai`** and `fitz`. Both are
**onefile** (binaries inlined in `EXE(...)`, `runtime_tmpdir=None`, no `COLLECT`).
`hook-plugins.py` is two lines: `hiddenimports = collect_submodules("plugins")`.

**LLM deps are handled by exactly two entries: `collect_all('openai')` and
`collect_data_files('certifi')`.** `httpx`, `anyio`, `pydantic`, `pydantic_core`,
`jiter`, `distro`, `sniffio`, `httpcore`, `h11` are **named nowhere**; they arrive
only because PyInstaller analyses what `collect_all('openai')` puts in the graph.

**Is `openai` actually bundled? [measured]** from the untracked wave-3 build
artefacts (`build/` is not part of HEAD, so this is corroboration, not
repository evidence): `PYZ-00.toc` carries `openai` 892 modules, `pydantic` 104,
`anyio` 35, `httpcore` 31, `httpx` 23, `h11` 11, `certifi` 2, `distro` 2,
`plugins` 47. `EXE-00.toc` carries `certifi\cacert.pem` and both compiled
extensions. `warn-metaScreener.txt` (408 lines) contains **no** missing-module
warning for any of them. So the stack is present — but **by transitive analysis,
not by any spec entry**: the same dependency-by-coincidence pattern
`04_frozen_build.md` criticised for `pandas`/`openpyxl`/`PIL`, one layer down, and
still uncorrected.

**Prior findings still hold, with one superseded.** `FIX_WAVE_3_BUILD.md`'s premise
that both specs set `hookspath=[]` is **no longer the state of the tree** — both
now carry `hookspath=['.']` **and** `'plugins'` in `hiddenimports`, pinned by
`tests/test_frozen_build_spec.py::TestSpecWiring`. `04_frozen_build.md`'s analysis
of *why both* lines are needed still holds.

**What would break if a heavy new dependency were added.**
`tests/test_frozen_build_spec.py::_routes_for` computes `hook_wired` as a condition
on the *spec* — `"." in hookspath and "plugins" in hidden and HOOK_FILE.exists()` —
**independent of the package being examined**. So any new import under `plugins/`
is declared "reachable" the instant it is written. Correct for a pure-Python
package; **wrong for one whose payload is native libraries or data files**.
`llama-cpp-python` (bundled `llama.dll`), `tokenizers`/`transformers` (Rust
extension plus data), `torch` (large DLL tree plus dynamic `torch.classes` loading)
each need `collect_dynamic_libs`/`collect_all`/a hook, and none of that is
derivable from an AST import walk. `test_every_derived_dependency_has_a_route`
would go green on a build that imports the module and fails at first use — F-66's
silent-degradation class re-created one layer down (C-24). Aggravated by
`excludes=[]` (nothing trimmed; the onefile payload is already 81,804,646 bytes),
`upx=True` with no exclusions (**[general knowledge]** UPX on large native DLLs is
a documented source of corrupted or refused binaries and slow startup), and the
onefile shape, which extracts the whole payload on **every launch**.

#### A12.3 Do EL/IL run with ZERO network when a cache is present?

**Yes — definitively, and by construction rather than by luck.** The trace:

1. `run_el_screen` builds `items`, then per criterion computes `_cache_key` for
   every item and partitions into `cached_pairs` and `to_call`. Pure hashing, no
   I/O.
2. The call site is guarded: `if c.operator == "llm" and to_call:`. **If every item
   hit the cache, `to_call` is empty and `run_m1_llm_for_criterion` is never
   entered.**
3. `_openai_client_for` is called *inside* that function, after the `model` and
   key guards — and `from openai import OpenAI` is *inside the function body*. So
   on an all-hits run **the `openai` package is never even imported**.
4. Does construction alone touch the network? **[installed SDK source]**
   `OpenAI.__init__` resolves `base_url`, then builds an `httpx.Client`; `chat` is a
   `@cached_property`. No request is issued, and **[general knowledge]**
   constructing an `httpx.Client` opens no connection.

So the ordering question resolves cleanly: **the client is constructed after the
cache lookup, and on a full-hit run it is not constructed at all.**

**Is the regression tests' demonstration airtight or incidental? Incidental.** The
safety comes from *removing the key*, so the test would not hit the network even
on a cache miss. What the byte-identity assertion *does* prove is the converse: a
miss would yield empty evidence and change the bytes, so passing implies all 170 EL
/ 84 IL keys hit. The two facts together are strong, **but no test exercises the
property a user actually depends on — cache present, key present, no network
attempted** — and there is no socket guard in `conftest.py` (C-31).

#### A12.4 What the frozen build assumes about network availability

**There is no preflight or connectivity check anywhere.** Grepping `plugins/`,
`metascreener/`, `run.py` for `socket`, `urlopen`, `connect`, `ping`, `preflight`,
`online`/`offline` returns only unrelated identifiers. The single pre-run gate is
`if not _has_openai_key():` — a test for **a string in the environment**, not for
reachability.

**Offline with no cache, the exact failure path.** `_call_once` raises;
**[general knowledge + installed SDK source]** `APIConnectionError("Connection
error.")` after 2 SDK retries against `connect=5.0` — on the order of tens of
seconds per batch, not a hang; the exact figure is **[not established]** and I
decline to multiply it out. `"connection error."` matches neither predicate → the
terminal branch logs one line per batch and writes **every item as a fabricated
non-answer** with `error=str(e)`. `usable` is False for all, so every criterion is
`UNCERTAIN`, no `failed` list, `outcome = "PASS_FLAGGED"` for the whole corpus.
`evidence[c.id]` is built from a fixed key list and **does not copy `error`**.
`cancelled` is False so the success path runs: the status label reads **`"EL
done."`** and both export buttons enable.

**Where the user learns something is wrong:** only from `log_cb` lines in the
stage's Log pane, plus indirectly from a counts label showing every record
flagged. Both are easy to read as "the model was uncertain about everything". The
graceful-degradation verdict is therefore: **it does not crash, and it does not
tell you** (C-8).

Worse, and compounding: those fabricated entries are then **merged into the
cache** — the write-back loop has no filter on `ev` — become `self.cache_map`, and
are serialised into the exported bundle. On a later **online** re-run with the
cache on they are served as hits (`ev.setdefault("used", True)` leaves the stored
`used: False` intact), the log reports a healthy `cache_hits=N`, and the API is
never called. **A transient outage becomes a permanent verdict** (C-2).

**The frozen build cannot read or write `.env`.** `MetaScreenerApp.__init__` sets
`project_root = Path(__file__).resolve().parents[1]`. **[general knowledge]**
PyInstaller gives a PYZ-frozen module a `__file__` under `sys._MEIPASS`, which for
onefile is a per-run temp directory — so `env_path` resolves to `<MEIPASS>/.env`,
never present on read and discarded at exit. If that holds, "Remember on this
device (.env in project folder)" silently does nothing in the distributable and
`OPENAI_BASE_URL` cannot be supplied to it at all except via a machine-level
environment variable. Same shape for a pip install, where `project_root` becomes
`site-packages`. **[not established]** — not observed on a running build;
`04_frozen_build.md` measured `_plugins_root_frozen()` and never touched
`project_root`. **HO-1 and HO-2 settle it** (C-6, §B10).

#### A12.5 Docker

`Dockerfile` assumes **network at build time** (`apt-get install`, `pip install -r
requirements.txt` — unpinned, so whatever PyPI serves that day) and **no network
at run time** (`CMD` runs pytest; no `OPENAI_API_KEY` is passed and none is
needed). It is the **only** consumer of `requirements.txt` — CI installs from
`pyproject.toml` — and nothing keeps the two declarations in step (C-35). Two
header claims do not match its own body: `# … on Ubuntu 24.04` and a `LABEL`
saying "Ubuntu/Debian" against `FROM python:3.12-slim-bookworm`, which is Debian
12; and header steps 3 and 4 describe things the `CMD` does not do as steps
(platform info *is* printed, incidentally, by `tests/test_imports.py` under `-s`).

---

### A13 Documentation claims

#### A13.1 The load-bearing sentences, quoted

**`README.md`** — the model and provider claims: the plugin-table entries
`GPT-4o vision API` (01) and `OpenAI-compatible endpoint, T=0.0` (06/07); the two
`SCREENA_*_MODEL` default rows (`gpt-4o-mini`); `openai (≥1.40.0) | LLM API client
| 01, 03, 06, 07`; *"An OpenAI API key (required for Plugins 01, 03, 06, 07; not
required for Plugins 02, 04, 05)"*; the whole local-provider section quoted in
§A5.4; and *"The EL and IL stages are configured independently: setting
`SCREENA_EL_MODEL` does not change the model used by IL."* On cost and caching:
*"All LLM responses are persisted in a local cache keyed by content hash, enabling
exact re-runs without additional API cost"* and, for EH/IH, *"These stages execute
without LLM inference, incur no token cost, and impose no latency."* On
reproducibility: `manifest.json — pipeline configuration (criteria file hash,
prompt version, model ID, UTC timestamp)`. On testing: *"The project includes 166
automated tests … No OpenAI API key, network access, or graphical display server
is required"* and `> **Status**: ✅ 166 passed`.

**`docs/installation.md`** — the env-var table rows for `OPENAI_BASE_URL`
(`https://api.openai.com/v1`), `OPENAI_MODEL` (`gpt-4o-mini` (per plugin)) and
`METASCREENER_CACHE_DIR` (`.cache/`); *"Each LLM-using plugin (01, 03, 06, 07) has
its own model dropdown in the GUI. Defaults can be overridden per run; the
selected model is recorded in each bundle's `manifest.json` so subsequent runs are
auditable."*; the verification line *"Expected: `162 passed, 1 xfailed`…"*; and the
cache-pruning instructions.

**`docs/usage.md`** — *"Every LLM response in metaScreener is keyed by the SHA-256
hash of (record content, prompt version, model identifier, criterion
identifier)."*; *"A first run … typically uses a few thousand API calls; subsequent
runs use zero."*; *"Bundles produced from a cached run are byte-identical (modulo
the timestamp in `manifest.json`)."*; *"Cache files live under
`.cache/<stage>.jsonl` by default; the location is configurable via
`METASCREENER_CACHE_DIR`"*; *"the temperature (0.0 = deterministic; any non-zero
value invalidates the response cache)"*; and *"73 from 776, a 90.6% reduction"*.

**`docs/faq.md`** — the provider answer; *"with `gpt-4o-mini` typically uses a few
thousand API calls"*; *"Each LLM response is keyed by SHA-256 of `(record content,
prompt version, model identifier, criterion identifier)`."*; *"Open the
corresponding `.cache/<stage>.jsonl` file, find the line whose `record_hash`
matches…"*; *"a manifest with the criteria-hash, prompt version, model identifier,
and UTC timestamp"*; *"the next plugin verifies them at read time and refuses to
proceed on mismatch"*; the seed and prompt-version reproducibility advice; and
*"Cohen 0.28, Fleiss 0.26 on IL/IC-1"*.

**`CITATION.cff` / `.zenodo.json`** — *"integrates deterministic rule-based filters
with large language model (LLM) inference"* and *"Each screening decision is
logged within a timestamped, SHA-256-verified bundle archive that satisfies the
audit and reproducibility requirements expected in rigorous evidence synthesis
methodology."* **Neither names a model, a provider, an API key, a cost, or a
numeric result.** That is the correct posture and should be preserved.

#### A13.2 Which of these a change of default model would falsify

| Claim | True at `f952e69`? | Falsified by a default-model change? |
|---|---|---|
| `SCREENA_EL_MODEL` / `SCREENA_IL_MODEL` default `gpt-4o-mini` | **Yes** | **YES — direct falsification** |
| "cache … enabling exact re-runs without additional API cost" | Yes, with a caveat: "exact" is model- **and endpoint**-conditional, and the key covers only the former | **Yes, materially.** Every key changes: an existing bundle cache produces 0 hits and a full-price re-run |
| "a second run with the same model and prompt version reuses the cached responses" | **Yes** | **Yes in effect.** The sentence stays true; a changed default silently means "not the same model", so the user's expectation does not |
| "with `gpt-4o-mini` typically uses a few thousand API calls" | **No** — wrong by 2–3 orders of magnitude (below) | falsified again |
| DeepSeek "substantially larger context windows than GPT-4o-mini" | not verifiable from the repository | weakly — the comparison baseline stops being the default |
| "replaying the goldens today yields 80 rather than 73" | **Yes** | **No** — the replay passes `model=invocation["model"]`, so 80 is fixture-insulated. **But it silently stops describing the shipped default** |
| 73 / 90.6% | **Partly** — labelled as the manuscript's result and immediately qualified | No directly; becomes doubly unreproducible |
| 98.3% deterministic share | **Yes** | **No, entirely.** Model-free |
| Plugin 01 "GPT-4o vision API" | **Yes** (a separate constant) | No — but must be scoped if a *global* local default is introduced |
| "open-weight compatibility … has not been formally tested" | **Yes** | No — and it becomes the most load-bearing sentence in the project |
| `manifest.json` records "prompt version, model ID" (README, installation, faq) | **NO** | Already false; a model change makes the omission consequential |
| Cache key = "(record content, prompt version, model identifier, criterion identifier)" (usage, faq) | **NO — this is the pre-F-01 key** | Already misstated (omits `temperature`, names a criterion *identifier* that F-01 replaced with content) |
| `OPENAI_MODEL` = `gpt-4o-mini` "(per plugin)" | **NO, twice** — read at exactly one site, defaulting to **`gpt-4o`**, and no EL/IL code reads it | already false |
| `METASCREENER_CACHE_DIR` / `.cache/<stage>.jsonl` | **NO** — the variable is read by no code; caches live inside the bundle ZIP | already false |
| "refuses to proceed on mismatch" | **NO** — `_load_bundle` **warns**, with the in-code rationale "Warn rather than refuse … refusing to open the bundle would strand a reviewer". README correctly says "warning"; the FAQ contradicts both | already false |
| `record_hash` field in the cache JSONL | **NO** — the file has `key` and `val` only, and the key is an opaque digest of the whole rendered prompt | already false |
| "166 automated tests" / "✅ 166 passed" / "162 passed, 1 xfailed" | **NO** — the measured run is 422/4; no `xfail` marker exists anywhere in `tests/`, and the test the guide names as xfailed **passes** | already false |
| "model dropdown in the GUI" / "the model selector" | **NO** — all six model inputs are unvalidated `ttk.Entry`; the repository contains no model Combobox | already false |
| "Bundles produced from a cached run are byte-identical (modulo the timestamp)" | **[not established]** — `_write_llm_stage_bundle` **appends a new history entry on every run**, so the manifest differs by more than one field, and `writestr` stamps member mtimes. Settling evidence: run the same bundle through EL twice with the cache on and diff member by member | No |

#### A13.3 The three manuscript figures — what they are figures of

| Figure | What it measures | Model | Survives a default change? |
|---|---|---|---|
| **98.3%** | the deterministic share of exclusions, 691 of 703 (EH 125 + IH 566) | **none** — a property of plugins 04 and 05 only | **Yes, entirely** |
| **73** and **90.6%** | survivors of the full funnel; 90.6% = 1 − 73/776. The manuscript figure requires 12 LLM exclusions | **[not established].** The figure entered the README on 2026-04-01 (`985973b`); `docs/llm-evaluation.md` states the run's "bundle, its manifest, its response cache — were not archived and will not be recovered". Because no manifest field records a model, they could not have supplied it even if archived. Settling evidence: the maintainer's recollection or an off-repo record (**HO-6**) | Formally yes (labelled historical); practically it degrades |
| **80** | the replay figure. **[measured]** `el_filtered` = 85 rows (`PASS_CLEAN` 77, `PASS_FLAGGED` 7, `OUT` 1); `il_filtered` = 84 (`REVIEW` 80, `OUT` 4); 776 − 691 − 1 − 4 = 80 | **`gpt-4o-mini`**, via `_invocation` — the only attribution route | Yes (fixture-pinned) — and it silently stops describing the default |

The archived-degenerate-run bullet, verbatim, confirming the brief's corpus
reference:

> "In one archived run of the same 776-record corpus (2026-05-07, `gpt-4o-mini`),
> all 170 EL calls returned the same decision (`not_meet`), the same confidence
> (0.9 exactly), and only three distinct evidence spans, one of which repeated
> identically across an entire 85-record criterion sweep."

**[measured]** 170 is exactly the entry count of `el_cache_v3.1.0.json`, and equals
85 records × 2 EL criteria. So **"170 EL calls" means 170 per-record decisions, not
170 HTTP requests** — at the goldens' `batch_size=5` that is 34 requests; at the
default 50 it is 4. The same conflation is what makes "a few thousand API calls"
read plausible: the true figure is **254 per-record decisions** (85 EC-2 + 85 EC-3
+ 84 IC-1), i.e. roughly **6 HTTP requests at the default batch size**. Both places
need disambiguating (C-38).

**The asymmetry worth stating in one line: the number a reviewer replays is
model-pinned by a fixture; the number a user obtains is model-pinned by nothing.**

---

## Part B — diagnostic: implications

*Assessment, not decision. Nothing is decided or fixed here. Where a choice is
genuinely the maintainer's, it appears in §B9 as a question with the trade-off
named on each side, not as a recommendation.*

### B1 Model discovery

#### B1.1 The two senses, and why conflating them is the trap

| | (i) **Which model IDs exist** | (ii) **What a model can do** |
|---|---|---|
| Question | "What may I put in the Model field?" | "Will this model produce the JSON contract, fit 50 records, quote verbatim?" |
| Standard mechanism | `GET /v1/models` plus native variants | none that is uniform |
| Answerable over the wire | **Yes**, where the server implements the route | **Partially at best**, and not at all on the most portable route |
| What it buys | Destination 1 almost entirely | Nothing the current code needs — because the current code asserts almost no capability |

**The most important structural fact: (i) is a cheap, additive feature; (ii) is a
research problem this codebase does not need to solve.** Any design that couples
them — "discover the models, then filter to those with JSON mode / a 32k window /
tool use" — imports the hard problem into the easy one and lands back at a
hand-maintained capability table, i.e. exactly the thing Destination 1 wants gone.

#### B1.2 Sense (i) — discovering which model IDs an endpoint offers

**Does any listing call exist in the code today? No. Definitively none, and the
search is exhaustive rather than merely negative.** `models.list`, `/v1/models`,
`api/tags`, `api/show`, `list_models`, `available_models`, `model_list` and bare
`/models` return **zero matches in any file of any type** — not `.py`, not `.md`,
not the specs, not the tests. `requests.get`/`httpx`/`urlopen`/`urllib` in `*.py`
returns 12 hits, **all** bibliographic REST calls in
`plugins/02_references_of_x/services.py`; zero in `metascreener/`, zero in
`plugins/_common/`, zero in any LLM stage. `argparse choices=` returns zero
anywhere. The only SDK resource the repository ever touches is
`chat.completions`. **So there is nothing to remove, nothing to migrate, and no
existing discovery behaviour to preserve — a listing feature would be purely
additive.**

**The SDK surface it would use. [installed SDK source]** `openai/_client.py`
exposes `OpenAI.models`; `openai/resources/models.py` defines
`def list(...) -> SyncPage[Model]` implemented as `self._get_api_list("/models",
…)`, i.e. `GET {base_url}/models` against whatever `base_url` the client carries.
Two caveats the brief's phrasing does not carry: `openai/types/model.py::Model`
has exactly **four** fields — `id`, `created`, `object`, `owned_by` — **none of
them a context length or a capability flag**; and `_strict_response_validation`
defaults `False`, so a malformed listing is **coerced rather than raised** — a
caller must *check* the result, not merely catch. And because
`_openai_client_for` omits `base_url`, **a listing call added today would already
reach a local endpoint whenever `OPENAI_BASE_URL` is set** — inheriting exactly
the undeclared dependency the chat path has.

**Mechanisms per endpoint type. Everything in this table is [general knowledge,
not repo evidence]; no endpoint was contacted. Confidence is stated per row.**

| Endpoint | Route | Returns | Reliability |
|---|---|---|---|
| OpenAI hosted | `GET /v1/models` | the four-field envelope, on the order of a hundred entries **mixing chat, dated snapshots, embeddings, audio/TTS, image and moderation models, with no type field** | authoritative for this provider |
| The compatible convention | `GET /v1/models` | same envelope | widely but **not universally** implemented. It is *convention*, not specification: a layer may omit it, stub it, or 404 it while `/v1/chat/completions` works perfectly |
| Ollama `/v1` shim | `GET /v1/models` | locally **pulled** models, `name:tag` form | high confidence the route exists. A model that *could* be pulled but has not been is **not listed**, and asking for it errors rather than pulling |
| Ollama native | `GET /api/tags`; `POST /api/show` | `tags` carries a `details` sub-object; `show` carries a `model_info` map including an architecture-prefixed context length and, in newer versions, a `capabilities` list | moderate on route and `details`; the `capabilities` array is newer and version-dependent, so treating its absence as "no capabilities" would be wrong |
| LM Studio | `GET /v1/models` and a native `GET /api/v0/models` | the native route carries a type discriminator, quantisation, max context, and load state | moderate on the native path and field names |
| llama.cpp `llama-server` | `GET /v1/models`, plus `GET /props` | conventionally a **single** entry for the loaded model; `/props` carries the effective context size | **the important fact is behavioural, not about the route:** it generates from whichever model is loaded and the request's `model` field is commonly **ignored** — and the repository's own README says so |
| vLLM | `GET /v1/models` | the served model name(s), with LoRA adapters as separate entries | moderate on the envelope; **low confidence** on version-specific extra fields, which I decline to name |
| Azure OpenAI | **not the same surface** | addresses *deployment names* on a different URL shape with a different auth header | high confidence it is a different shape. `docs/installation.md` lists Azure as an `OPENAI_BASE_URL` target; **that claim is supported by nothing in this repository and is doubtful on its own terms** |
| A gateway / proxy | whatever it implemented | a curated alias set, the upstream list, or a 404 | least uniform, and the case most likely in an institutional setting |

**Two consequences matter more than any row.** First, **the route is optional in
practice**, so a design that requires a successful listing before allowing a run
would be *less capable than the free-text Entry the tool ships today* — a
regression the GUI-first constraint cannot absorb. Second, **`/v1/models` on the
hosted OpenAI API returns a list that is mostly wrong answers**: embeddings, TTS,
image and moderation models arrive indistinguishably from chat models. Presenting
the raw list hands the user a hundred entries of which a handful are usable. The
obvious fix — filter by name pattern — **is a hand-maintained list of model-name
prefixes, i.e. Destination 1 defeated by its own implementation.**

#### B1.3 Sense (ii) — capabilities: what is and is not discoverable

**[general knowledge unless marked]**

| Capability | `/v1/models` | Ollama `/api/show` | LM Studio native | llama-server `/props` | Uniformly unavailable? |
|---|---|---|---|---|---|
| Model id | yes | yes | yes | yes (one) | — |
| Context window | **no** — **[installed SDK source]** the SDK's `Model` type has four fields and none is a length | under `model_info` | a max-context field | effective `n_ctx` | **Yes.** The one route every server implements carries no length |
| Max output tokens | no | no | no | no | **Yes** |
| JSON mode / structured output | **no** | not as a flag | no | indirectly, as a *server* property | **Yes.** There is no cross-provider "does this accept `response_format`" signal |
| Vision | no | newer versions, via `capabilities` | via a type discriminator | no | not uniformly |
| Tool calling | no | newer versions | no | no | not uniformly |
| Tokeniser identity | no | inferable from family, not stated | no | no | **Yes** |
| Quantisation / weights identity | no | `details.quantization_level`, `digest` | a quantisation field | model path | **Yes on the compatible route** — and this is the field that decides whether two runs of "the same model" are the same model |
| Whether `model` is honoured at all | **no** | n/a | n/a | **no, and it often is not** | **Yes, and consequential** |

**Blunt summary: `/v1/models` is an ID list.** Everything richer lives on a
provider-native route, differs per provider *and* per version of that provider,
and is absent for the hosted OpenAI case. Any capability model built on it is a
per-provider adapter — that is, **provider-shape code, not data**.

**What the code assumes today — and it is the asset.** Verified independently in
§A2.5 and §A3.5: zero `Literal`/`Enum`/`TypedDict` anywhere; every OpenAI decode
and capability parameter absent; exactly one condition on the model value. So for
the screening path the assumed capability set is:

> An HTTP endpoint that accepts `POST {base_url}/chat/completions` with
> `{model, messages:[{role:"system"},{role:"user"}], temperature}` and returns an
> object whose `choices[0].message.content` is a string.

**That should be recorded as an asset, not merely as an absence** — and, since it
is incidental rather than designed, as an **invariant to protect** (C-25).

**The four assumptions that DO exist are all behavioural, none checked, none
logged, none tested:**

1. **The model will obey a JSON-only instruction carried entirely in the system
   message.** There is no `response_format` and no schema; the contract is one
   sentence. On failure `_parse_llm_json_array` → `[]` → back-fill → every record
   flagged, **with no log line and no dialog**. Weakest exactly where local models
   are weakest.
2. **The `system` role survives to the model.** **[general knowledge]** some
   open-weight chat templates have no system turn; the serving layer prepends or
   discards it — silently removing the entire format instruction, then failure
   mode 1.
3. **`batch_size × trunc_chars` fits the context window.** No token count exists
   anywhere. Handling is reactive via `is_big` — **and §A2.4 established that the
   trigger does not fire on a local server's phrasing, so the two remedies that
   exist for this exact condition are unreachable there.** The defaults were sized
   against a hosted model's window.
4. **The model will quote verbatim.** Fails **closed**, so nothing is wrongly
   excluded — but the review queue inflates for reasons unrelated to eligibility,
   systematically worse for models that paraphrase or re-punctuate. The README
   already says this is untested.

Assumptions 1, 2 and 4 are all "the model behaves well" — unobservable from any
discovery route and observable only by trying. **Assumption 3 is the only one a
discovery route could inform**, and it is also the one whose remedy merely needs
its trigger fixed.

**The one place a real capability distinction is unavoidable** is plugin 01
(§A1.2), which asserts vision **and** forced function calling, checks neither, and
is pointed at a user-typed model string. **Plugin 01 must be scoped out of any
"local models by default" claim, or given its own endpoint/model setting** — a
single app-wide setting that also governed it would silently break it (C-24).

#### B1.4 What the GUI must do when discovery fails

**A hard precondition governs everything here: discovery has nothing to discover
against until the endpoint becomes a first-class, GUI-settable, repository-read
value (§A4.4). An endpoint field is a *prerequisite* of model discovery, not a
companion to it.** The persistence half is nearly free — `_load_env_file` is
already generic and `_save_env_key` already preserves unrelated lines — so what is
missing is a widget, a second write path, and a `base_url=` argument.

Today `ELView`/`ILView` show one provider-adjacent widget, and in the shipped hub
it is a constant (§A4.5). **Every state below is currently indistinguishable from
every other, and `"EL done."` is emitted for most of them.**

| # | State | How the tool learns it | What it must show | What it must still allow |
|---|---|---|---|---|
| 0 | Discovery in progress | a call is outstanding | "Checking <endpoint>…"; never a frozen window | typing a model; starting a run without waiting. **Must be off the Tk main thread** — and note plugin 01 already calls `messagebox` from a worker thread, which is the pattern *not* to copy (C-29) |
| 1 | No endpoint configured | `OPENAI_BASE_URL` unset | the effective endpoint **spelled out**: "OpenAI hosted API — api.openai.com — **this is a paid API**". This is the state most users are in and the one the GUI currently never names | everything |
| 2 | Configured, unreachable | connection refused / DNS / connect timeout | "Cannot reach <endpoint>." Distinguish from state 3 — a refused connection is not an auth problem | editing the endpoint; **and starting a run anyway**, which must then fail *loudly* |
| 3 | Reachable, auth rejected | 401/403 | "<endpoint> rejected the key." **Never "OPENAI_API_KEY ✗"** — the key is present; it was refused | re-entering the key **without restarting** (today the dialog is launch-only) |
| 4 | Reachable, no listing route | 404/405 or a non-JSON body | "Connected. This endpoint does not publish a model list." **Neutral wording — this is a normal, supported configuration** | free text, unimpeded. This state must cost the user nothing |
| 5 | Route present, body unusable | the object has no items — and **[installed SDK source]** it arrives *coerced*, not raised | as state 4, plus one log line naming what was received | free text |
| 6 | Lists zero models | `data == []` | "Connected. <endpoint> reports no models available." For a local server this usually means nothing is loaded — say so as a **hint, not a diagnosis** | free text, and Run |
| 7 | Lists models, none identifiable as chat-capable | **cannot be determined** from `/v1/models` | **the tool must not claim this state.** It cannot distinguish "no chat models" from "chat models it cannot recognise". The honest presentation is the unfiltered list with no suitability claim | the whole list, plus free text |
| 8 | User typed a model not in the list | string not in the ids | a **non-blocking** note, in exactly the register of `LOCAL_PROVIDER_HINT` and for the same reason | the run, **unconditionally**. Blocking here re-creates F-08 on the model axis |
| 9 | Endpoint ignores `model` | **not detectable** | nothing can be asserted; the endpoint field's help text should carry the caveat the README already carries | any string |
| 10 | Model blank / whitespace-only | local check | **this one should block, and does not today** (§A4.4) | nothing — refuse before starting, with a message |

**Must free text remain permitted? Yes, and it is not a concession.** Five
independent reasons, in descending strength: (1) **llama-server ignores the
`model` field** and the README says so, so a list-only control presents a required
choice the server discards, and nothing on the wire lets the UI know when to
relax; (2) **a dropdown is itself an enumeration**, maintained by whatever the
server advertises — a proxy alias, a vLLM LoRA name, a freshly loaded model, an
endpoint with no listing route all become unreachable, which is *Destination 1's
own failure re-created one layer out*; (3) filtering the hosted list to something
usable requires a name-pattern list, i.e. the hand-maintained model list the
maintainer wants gone; (4) **the GUI-first constraint cuts both ways** — remove
free text and a discovery failure leaves the user only a config file or a shell;
(5) **the precedent is in the repository and was paid for** — F-08 was a
validation rule that looked like a safety check and made the entire documented
local-provider workflow GUI-unreachable. **The same shape of answer is correct for
the model field: reject only emptiness, advise on anything unrecognised, never
refuse.** The design that satisfies both destinations is therefore an **editable
combobox**, and it would be a new pattern here — **[measured]** all three existing
`ttk.Combobox` instances in the tree are `state="readonly"`.

#### B1.5 One interaction to see before choosing

**Making the endpoint easy to change through the GUI multiplies an existing latent
defect.** The endpoint is in neither the cache key nor any artefact. Today the
hazard is dormant because switching endpoints requires editing `.env`. An endpoint
field plus a model dropdown turns a two-step file edit into two clicks — at which
point reusing one model name across two endpoints serves one endpoint's cached
answers under the other's configuration, logged as a healthy `cache_hits=N`, with
no trace in any artefact. **The sequencing implication is concrete: put the
resolved `base_url` into the cache key and into the manifest in the same change
that makes the endpoint settable, not afterwards** (C-4, and §B9 Q1–Q3).

---

### B2 Local backend integration surfaces

Ranked **by size of diff, not by preference.**

| Rank | Surface | Diff | Files touched | New deps | Frozen-build effect | What it buys |
|---|---|---|---|---|---|---|
| **1 (smallest)** | **(i) OpenAI-compatible HTTP** — Ollama `/v1`, LM Studio, `llama-server`, vLLM | **S** minimum, **M** for parity | **7 source** minimum (`llm_client.py`, both `screen.py`, both `ui.py`, `api_key_dialog.py`, `main.py`); **11** for parity across all four LLM plugins; **13** if the standalone shells are kept consistent. Plus ~3 tests, ~5 docs, `.env.example` | **None.** `openai` is already the sole client and already declared | **Zero spec change.** `collect_all('openai')` is already in both specs and §A12.2 measured the whole stack present. Build size unchanged | A keyless or placeholder-key local server reachable **from the GUI**, an endpoint the user can see and that persists, discovery via `client.models.list()`, and an endpoint-aware cache key. Also, unavoidably, DeepSeek/Azure/vLLM for free |
| **2** | **(ii) Native non-OpenAI API** — Ollama `/api/chat` | **L** | **14 source** — all of (i)'s plus a new transport module, and the change *inside* `llm_client.py` is structural (a provider seam) rather than a new parameter. Plus a second discovery implementation, ~4 tests, ~5 docs | **None.** `requests` is already declared and already `collect_all`'d | **Zero spec change** | Ollama's native `options` block (`num_ctx`, `num_predict`, `repeat_penalty`, `seed`, `format:"json"`) and `/api/tags`/`/api/pull` progress. **[general knowledge]** the `/v1` shim already accepts a documented subset including `seed` and `response_format`; which parameters a given build accepts is a fact about Ollama that this repository establishes neither way. **Marginal gain over (i) is small and uncertain while the diff is strictly larger** |
| **3 (largest)** | **(iii) In-process Python binding** — `llama-cpp-python`, `ctransformers`, `transformers`+`torch` | **XL** | **~18–20 source** — all of (ii)'s plus a model-lifetime owner, a weights manager, a download UI, a per-token cancellation path; **plus 7 build/config files**; plus a re-capture of all 6 golden fixtures; plus ~8 docs | **Heavy** (below) | **Severe, and for weights impossible** | A tool that runs with no server process and no separate install step. Nothing else — screening quality is a property of the weights, not the binding |

#### B2.1 Surface (i) — the transport already works; that is not the same as the feature existing

Today, with `OPENAI_BASE_URL` set, EL and IL already talk to a local server with
**zero code change**, and I traced all four links (§A2.2, §A3.2, §A6.1). **And a
GUI-first user cannot reach it.** Five blockers, none of them in the request path:

1. **No control.** No widget of any kind is bound to an endpoint, host or port; the
   two `OPENAI_BASE_URL` mentions in GUI code are static strings telling the user
   to go set an environment variable.
2. **No persistence.** `_save_env_key` writes one variable. Every LLM setting is
   re-initialised from constants each launch.
3. **A key is enforced.** Three independent points plus a fourth in the SDK, so a
   keyless server needs an invented placeholder — and the placeholder buys nothing
   without the endpoint the GUI cannot set. **Wave 1 unblocked step 2 and left step
   1 blocked.**
4. **No display.** The ✗ branch is unreachable in the shipped app; the one
   provider-adjacent widget carries zero bits.
5. **No record, and an unsafe cache.** A provider switch under a reused model name
   is a silent 100%-hit replay of the previous provider's answers.

**And one dependency the repository does not own:** the whole capability rests on
the SDK's env fallback, which no repository line mentions, which `openai>=1.40.0`
does not pin, and which **no test anywhere asserts**. So the correct summary is:
*the smallest surface is also the one whose current success is undeclared, unpinned
and unattributed.* Making it explicit is part of the diff, not an optional extra.

**The concrete diff, symbol by symbol.** `plugins/_common/llm_client.py`, four
symbols: `::_openai_client_for` accepts and passes `base_url=`, and must supply a
non-`None` `api_key` for the keyless case because the SDK raises on `None`;
`::_has_openai_key` — **the real blocker** — must become a *readiness* predicate
over (endpoint, key) rather than a presence check on a key string, and it has
**five consumers** plus the standalone twins, and its body **never executes in the
test suite**, so nothing pins it; `::run_m1_llm_for_criterion` gains an endpoint
keyword and needs its error classifier rewritten; `::_cache_key` gains the resolved
endpoint. Then the cache-key threading through both `screen.py` curries and their
two call sites each; three UI symbols per stage; the two `DEFAULT_MODEL` constants
plus a new endpoint default; the key dialog; `_save_env_key` and
`_prompt_api_key_always`; a discovery helper plus the two UI files; and, for
parity, `llm_refine.py::_call_openai_json` (which constructs `OpenAI()` bare and
whose `_llm_available` diverges from `_has_openai_key`) and plugin 01's
`ai_extract_included` (which subscripts `os.environ`). **Specs: no change** — and
that is measured, not inferred (§A12.2).

**The error classifier is the substantive correctness change, not a nicety.** Both
remedies are gated on `(is_rate or is_big)`, so on a server whose phrasing matches
neither, **the two mitigations that exist for a small context window are
unreachable — and small context windows are precisely the local case.** The fix is
`isinstance(e, openai.RateLimitError)` / `openai.BadRequestError` plus
`e.status_code`, keeping the substring sniff only as a labelled last resort (C-9).

#### B2.2 Surface (ii) — why it ranks larger for an uncertain gain

Everything in (i), **plus**: a new transport module and a **structural** change to
the shared one, because `_call_once` returns an SDK *response object* which line
285 destructures as `resp.choices[0].message.content` while **[general knowledge]**
Ollama's `/api/chat` has **no `choices` key at all** — the minimal seam is to make
`_call_once` return **text** and push the unwrap into a per-provider adapter, which
has the recordable consequence that `finish_reason` becomes structurally
*unavailable* rather than merely unused. Plus **a second error taxonomy** (a
`requests.HTTPError` string matches neither predicate, so without a rewrite *every*
native error goes terminal on first sight). Plus a second discovery implementation
feeding one user-facing control. Plus **provider must join model in the cache key**,
or `llama3.1` via `/v1` and via `/api/chat` collide. Plus plugins 01 and 03 either
stay OpenAI-only or need separate ports.

**No new dependency and no spec change** — `requests` is already declared and
bundled. **Net: a strictly larger diff for a benefit that is small and, on the
evidence available here, unquantified.** The honest statement is that (ii) is worth
doing only if a specific `options` parameter the `/v1` shim refuses turns out to be
load-bearing — and no such parameter has been identified, because the repository
sends three.

#### B2.3 Surface (iii) — what has no analogue in (i) or (ii)

| Concern | Why it is new work, not a port |
|---|---|
| **Model lifetime** | A client is stateless and cheap; a loaded model is a multi-gigabyte resident object. Constructing one per `run_m1_llm_for_criterion` call means reloading per criterion (pathological). Holding it means new ownership interacting with the worker thread and `MetaScreenerApp._on_close`, which today only fires plugin hooks |
| **Cancellation** | `_check_cancel` runs at exactly one site and a local 50-record batch is one long blocking generation. **[general knowledge]** `llama-cpp-python`'s `create_chat_completion` does not poll a `threading.Event`; cancelling needs `stream=True` with a per-token loop or a stopping-criteria callback. The existing design deliberately does not check between call and parse — correct for a paid API, wrong for a ten-minute local generation |
| **Response shape** | **[general knowledge]** `llama-cpp-python` returns a *dict* shaped like OpenAI's, so `resp["choices"][0]["message"]["content"]` — attribute access breaks even though the schema matches |
| **Weights management** | Nothing exists to build on: no download code anywhere, no progress-driven transfer, no resume, no checksum, no disk-space precheck |
| **Somewhere to put state** | The application knows exactly two paths, `project_root` and `env_path`. **There is no application data directory**, no `%APPDATA%`/`~/.config` use, no config parser, no registry use — and `METASCREENER_CACHE_DIR` is documented and read by no code. Weights, a model list and an endpoint all have nowhere to live, and in the frozen build `project_root` is probably inside the extraction directory (§A12.4) |
| **The launch gate becomes wrong** | `_prompt_api_key_always` destroys the app if no key is entered, and `__init__` returns before the notebook exists. Local-by-default means that modal cannot be the startup gate — a change to launch *order*, not a cosmetic edit |

**Dependency weight, unsentimentally. All figures [general knowledge, not repo
evidence].** `llama-cpp-python`: CPU wheels in the tens of MB, CUDA variants
hundreds; on Windows the plain `pip install` gets the **source sdist** (prebuilt
CPU wheels come from the project's own index via `--extra-index-url`, with coverage
lagging new Python versions), and a source build needs CMake plus MSVC C++ Build
Tools — a multi-gigabyte separate install with no wheel fallback.
`ctransformers`: smaller, effectively unmaintained — a poor bet for an artifact
expected to install years from now. `transformers`+`torch`: CPU `torch` on Windows
~200 MB+, CUDA 2–3 GB installed, plus `tokenizers` (Rust extension),
`safetensors`, `huggingface-hub`, `numpy`.

**For calibration against what this project already carries,** measured on this
machine's `site-packages`: the **entire** current LLM dependency stack — `openai`,
`httpx`, `httpcore`, `anyio`, `pydantic`, `pydantic_core`, `jiter`, `certifi` — is
**~18 MB**. `pandas` alone is 63.6 MB. A CPU `torch` would be the largest single
thing in the project by a wide margin; a CUDA `torch` larger than everything else
combined by an order of magnitude.

**Model weights [general knowledge]:** ~0.7–1 GB for a 1B at Q4; ~1.5–2 GB for a
2–3B; ~4–5 GB for a 7–8B; ~16 GB for an 8B at bf16. **`dist/` currently holds a
188,047-byte wheel and an 81,804,646-byte executable. A 2 GB download is 25× the
entire distributable.**

**What PyInstaller would then have to bundle, and why it is worse than it looks:**
native libraries via `collect_dynamic_libs` (both specs currently have
`binaries = []` seeded only from `collect_all`, and `excludes=[]` trims nothing);
**onefile amplification** — every launch extracts the whole payload, already
noticeable at 81.8 MB and a first-impression problem at 150 MB for exactly the
reviewer the frozen build exists for; **UPX on native DLLs**; and — decisively —
**the build's only safety net cannot see this class of breakage** (§A12.2).
**Weights cannot be frozen at all**, so even a perfect build ships a tool that
does nothing until a multi-gigabyte download completes. And **no CI build step
exists**: the distributable's entire evidence base is one manual measurement on
one Windows 11 / Python 3.11 / PyInstaller 6.15.0 machine, with the tab count from
one human visual observation.

#### B2.4 Which surface the code is already closest to

**(i), and the gap is not in the transport.** Genuinely already done: one SDK
method posting to the de facto interoperability route with `/responses` unused;
three request parameters and two roles with plain-string content, pinned
accidentally by a keyword-only test double; `Bearer` from the SDK, which local
layers accept and ignore; `_strict_response_validation` defaulting `False`; and
wave 1's dialog fix, pinned by test. **The five things separating "the transport
works" from "a GUI-first user can reach it" are listed in §B2.1 and none of them
is in the request path.**

---

### B3 What "local by default" costs operationally

#### B3.1 First launch with no server running

**What the user sees today, traced end to end.** Steps 1–8 are the launch flow and
the run gate (§A5.2, §A4.5). Then: client construction **succeeds** (it opens no
connection); `_call_once` raises `APIConnectionError`; **[measured mechanism]**
`"connection error."` matches neither predicate so **neither remedy fires**; the
terminal branch logs one line per batch and writes every item as a fabricated
non-answer with `error`; those entries are **merged into the cache with no filter**;
`usable` is False for all, so every criterion is `UNCERTAIN` and every row
`PASS_FLAGGED`; `evidence[c.id]` **does not copy `error`**; `cancelled` is False so
the status label reads **`"EL done."`**; both export buttons enable because
`self.full_rows` is non-empty; and `_export_block_reason` and
`_export_confirm_reason` both return nothing, so **export proceeds without a
warning**.

**So today, with the server unreachable: a full corpus of manufactured
non-answers, a green "EL done.", both export buttons live, and the only signal is
one log line per batch in a sub-tab that is not the focused one.**

**Correcting the brief on the mechanism, because the correction matters.** The
brief attributes this to `run_m1_llm_for_criterion`'s "silent `return {}`". **That
is not the path.** The silent `{}` has exactly three triggers, all *before* any
network activity: `if not model:`, `if not _has_openai_key():`, and the `except`
around client construction. A server that is simply *down* reaches none of them —
construction opens no connection — so the failure surfaces at `_call_once` and
takes the **terminal branch**, which *does* log per batch and *does* stamp `error`.
The user-visible outcome is nearly identical; **the forensic trace is not.**

**And the brief's underlying worry is right about the destination — sharper than
stated.** Under a local default with a keyless server, **whatever replaces
`_has_openai_key()` becomes the thing that decides between "one log line" and "a
per-batch error trail".** If the replacement is a presence check on an endpoint
string — the direct analogue of today's presence check on a key string — then a
typo'd endpoint gives the terminal path, while an **unset** endpoint gives the
silent `{}` path: one log line for the entire run, no `error` anywhere, a full
corpus of `PASS_FLAGGED`, and `"EL done."` Today that second case is
**unreachable in the hub**, because the modal cannot be passed without a non-empty
key and nothing ever clears it.

**Stated plainly: the launch-time API-key modal is, today, doing the work of a
readiness check, by accident. Local-by-default cannot keep it — a keyless server
requires removing it — and removing it removes the only thing currently
guaranteeing that the LLM path is not silently a no-op. A readiness probe is
therefore not an optional nicety in the local design; it is the load-bearing
substitute for a gate that is being deleted.**

Two adjacent defects local-by-default would aggravate:
`plugins/06_el/ui.py::ELView._set_controls_running` re-enables `btn_run` on
`self.bundle_zip_path` **alone**, dropping the `_has_openai_key()` condition that
`::_load_bundle_inputs` applied — so after the first run of a session the readiness
gate on the button is gone (C-34). And the stage has **no run-level failure
report**: `_write_llm_stage_bundle` hard-codes `cancelled: False` and records no
error count, so a wholly failed run and a wholly uncertain run are
indistinguishable in the bundle. The precedent for the right fix already exists —
F-34's `_export_confirm_reason` + a confirmation dialog: make the user say it out
loud.

#### B3.2 No weights present

**Surfaces (i) and (ii): the user pulls, out of band, and metaScreener should not
trigger a download.** Consequence: a model name that has not been pulled yields a
not-found error whose message **[general knowledge]** matches neither predicate, so
it goes terminal → all-`uncertain` → `PASS_FLAGGED` → `"EL done."` **This is the
single most likely user error in local mode and it produces a completed-looking
run.**

It is also the most direct argument for Destination 1's discovery — **and the
argument runs the opposite way to the usual framing**: enumeration is wanted here
not to *restrict* what the user may type but to make an unpullable name
**impossible to submit** rather than survivable. A combobox filled from
`/v1/models` (or `/api/tags`) satisfies both destinations at once: it needs no code
edit to accept a new model, and it removes the failure mode.

**Surface (iii): metaScreener becomes the downloader, and nothing exists to build
on** (§B2.3). Sizes in §B2.3. **"Must not silently start a large download" — and
note the repository has the mirror-image problem today:** `_run_clicked` starts a
*billable* operation with no cost estimate, no request count and no confirmation,
and the only cost statement anywhere is wrong by two to three orders of magnitude.
A design that added a multi-gigabyte transfer without an explicit, cancellable,
sized confirmation would be repeating that mistake in a form the user cannot undo.

#### B3.3 The `docs/installation.md` smoke test

Verbatim, the four numbered steps name only plugins **03, 02, 04 and 05**, and the
header says "LLM-free": *"To verify an end-to-end LLM-free pipeline: 1. Launch the
GUI. 2. In Plugin 03 (Criteria Parser), load `samples/ic_ec_12.txt`. Click Run…
3. In Plugin 02 (References-of-X AI), load `samples/ex_ref_2.txt`. Click Run.
4. Pipe the Plugin 02 output through Plugins 04 (EH) and 05 (IH) — these are
deterministic and require no API key."* — then, conditionally, *"If you have an
OpenAI key configured, extend the smoke test through Plugins 06 (EL) and 07
(IL)."*

**So the smoke test does not exercise EL or IL at all, and making local the default
does not in itself invalidate it.** What is **already wrong with it**, verified
against the widgets:

| Claim | Reality |
|---|---|
| "Click Run" in Plugin 03 | **There is no Run button.** `HarmoniserView._build_ui` creates "Harmonise (no-LLM)", **"Harmonise + LLM"**, "Validate", "Export bundle…", "Pick target(s)…". Naming the wrong one matters more than usual here: the adjacent button spends money |
| `samples/ic_ec_12.txt` alone | `::_refresh_buttons` gates harmonising on criteria **and** an A vector. Neither button enables from the criteria file alone, and the smoke test never mentions the A CSV |
| "Click Run" in Plugin 02 | No Run button either — "Import Text…", "Resolve Metadata", "Fetch References", "Build A", … |
| implicitly, offline | **"Resolve Metadata" and "Fetch References" make live HTTP calls.** The "LLM-free" smoke test **is not offline**; it is merely un-billed. For an offline reviewer that distinction is the entire story |
| "Pipe the Plugin 02 output through 04 and 05" | Plugin 04's input is a **bundle ZIP**, which only Plugin 03's "Export bundle…" produces. Plugin 02 emits a CSV/XLSX A-vector. **There is no pipe** |

**Can it still be a smoke test without a model? Yes — and a better one.** A
strictly LLM-free, strictly **offline** route exists today using only committed
files: plugin 03 (load criteria + `samples/20260122_1654_aggregate.csv` →
"Harmonise (no-LLM)" → "Validate" → "Export bundle…"), then plugin 04 on that ZIP,
then plugin 05. That is the deterministic 98.3% of the funnel, and it needs no key,
no server, no network and no model. **What has to change is only the wording**
(C-36). What would additionally change under a local default: the trailing sentence
becomes "if you have a local server running with model X pulled" — **and at that
point it stops being a smoke test, because its precondition is exactly the thing
most likely to be missing and its failure mode is a successful-looking run.** A
smoke test whose failure signal is `"EL done."` is not a smoke test; making the LLM
step smoke-testable requires the readiness probe and the run-level failure report
first.

#### B3.4 CI — can a 16-cell matrix run a local model? **No.**

Four independent reasons, any one fatal. Runner-capability figures are **[general
knowledge, not repo evidence]**.

1. **The 10-minute per-cell timeout is decisive.** The corpus at this stage is
   **254 per-record decisions** carried in prompts of up to 50 records, each
   expecting a JSON object per record in the reply. A 1–3B Q4 model on a 2–4 vCPU
   hosted runner produces on the order of 5–20 tokens/s. **Weight download alone
   would consume the budget.**
2. **No GPUs** on any of the four standard hosted images.
3. **RAM and vCPU** — ~2–4 vCPU and 7–16 GB. A 7–8B Q4 model fits in RAM but not
   in 10 minutes; anything larger does not fit.
4. **Disk and bandwidth × 16.** Sixteen multi-gigabyte pulls per push is not a
   test strategy.

And a fifth reason that is a property of the destination rather than the runner:
**a local model's output is not a fixture.** The filtered goldens assert exact CSV
bytes derived from exact `decision`/`confidence`/`quote`/`span` values. **No real
model in CI, on any hardware, can hold those.**

**What the strategy must be instead — and the repository already has most of it.
Keep replay as the CI contract, and re-capture the goldens once per candidate
model.** §A11.3 measured that replay is *already* a zero-key, zero-network,
zero-model contract, and it works identically for a local model provided a golden
set is captured against that model once, by hand, on a real machine. The capture
tool's key gate accepts any non-empty value, so the placeholder convention already
satisfies it.

**What replay cannot verify, and this is the load-bearing limitation: it cannot
execute the transport at all.** `_openai_client_for`'s body never runs and
`_has_openai_key`'s never runs, so **no CI cell today, and none under replay
tomorrow, would notice that the local path is broken.** Specifically unverifiable:
that a base_url is honoured; that a keyless server is reachable; that the response
unwrap matches the server's shape; that the error classifier classifies that
server's errors; that `_parse_llm_json_array`'s fallbacks cope with a chattier
model; and that the gate's verbatim-substring requirement is satisfiable by the
model at all.

**The gap closes with a fake server, not a real model**, in two tiers. **Tier 1, in
all 16 cells, seconds not minutes:** a stdlib `http.server` on `127.0.0.1` speaking
`/v1/chat/completions`, with `OPENAI_BASE_URL` pointed at it — pinning base_url
honouring, keyless auth, the response unwrap, and the whole error taxonomy (a 429
with a plain-text body, a 400 with an unfamiliar context-window phrasing, an empty
`choices` array, `content: null`, a fenced reply, a bare object, a trailing comma).
The idiom already exists in `tests/test_cancellation.py`. Tier 1 is what makes the
destination *maintainable*. **Tier 2, out of CI, one machine, human-run,
recorded:** a conformance check against a real local server, written up the way
`04_frozen_build.md` records its measurement — including who ran it and on what
hardware. Only tier 2 can say anything about model behaviour, and it cannot be
automated on hosted runners.

**One thing CI could pin today and does not:** the two `DEFAULT_MODEL` constants
are referenced by no test, so if either became a local model tomorrow all 16 cells
would stay green for a shipped default that had never been run. **For Destination 2
that is the most consequential single gap in the suite, and the cheapest to
close** (C-12).

#### B3.5 The frozen build, and the offline reviewer

Size measured: `dist/metaScreener.exe` 81,804,646 bytes; the console build
81,809,210. Onefile in both specs, so the full payload extracts on every launch.
**`.env` almost certainly does not work there** (§A12.4) — **[not established]**,
and **if it holds it is the hardest constraint on Destination 2**, because
`OPENAI_BASE_URL` could not be supplied to the distributable through `.env` at all,
only through a machine-level environment variable, which is neither GUI-first nor
something a JORS referee will do. **A GUI endpoint field must therefore persist
somewhere the frozen build can actually write** — beside `sys.executable`, or
`%APPDATA%`/`~/.config`. Neither location exists anywhere in the repository, so
this is new code, not a re-point of `env_path`.

Failure invisibility compounds it: `04_frozen_build.md` records that `discover()`
is unguarded, that the windowed build's stdout goes nowhere on the double-click
path (F-35), and that the `*_OK` feature flags are never surfaced, so a build
missing an optional dependency "looks exactly as healthy as this one" (F-66).
**Under local-by-default, a first run that fails at *readiness* rather than at
*import* would print nothing and show nothing — and the `"EL done."` path of §B3.1
is exactly how it would present.**

Docker assumes network at build time and none at run time (§A12.5), so a local
default changes nothing there **except** that the container would need either a
sidecar server or the replay cache — the latter being what it already effectively
uses.

---

### B4 Golden-file and cache impact

*The brief calls this the pivotal question. It contains a false premise, and the
question the maintainer actually needs answered has a different — and more
reassuring — answer.*

#### B4.1 The premise, tested

The brief asks: *"If model identity were added to the cache key, would every EL/IL
golden cache be invalidated?"*

**Model identity is already in the cache key. It cannot be "added".**
`::_cache_key` hashes exactly four members and `model` is the second of them
(§A8.1–A8.2). Both per-stage curries pass it through verbatim; both call sites in
each screening loop pass the run's `model`; `model` is a keyword-only parameter of
`run_el_screen`/`run_il_screen` with **no default**; and
`tests/test_cache_key.py::TestCacheKeySanity::test_model_change_changes_key` pins
it for both stages. It was also present in the **pre-F-01** formula
(`prompt_version|model|cid|a_id|text_hash|trunc_chars`), so it predates the goldens
under both key schemas.

**Answering the question as asked would have produced a reassuring "nothing is
invalidated" about the wrong subject.** The question conceals three distinct
things with three different answers, and the diagnostic value is in separating
them:

| | What it is | Does a default-model change touch it? |
|---|---|---|
| **(a)** the cache **key schema** — what is hashed | `{prompt_version, model, temperature, prompt}` | **No.** Unchanged |
| **(b)** the golden **cache contents** — whose answers are stored | `gpt-4o-mini`'s 170 + 84 answers, self-described by `_invocation` | **No.** The replay reads the model *from the fixture* |
| **(c)** the production **default** model | two `DEFAULT_MODEL` literals | **Yes — and nothing else** |

#### B4.2 Is the endpoint in the key? No — and here is the concrete consequence

`base_url` is in the key neither by name nor transitively: the hashed object has
four keys, `_render_prompt_for_key` serialises only `role` and `content`, and no
repository code reads `OPENAI_BASE_URL`. **A structural point worth recording:
the resolved endpoint is not even *obtainable* at the keying site** — `_cache_key`
is called from the stage engine, while the client is constructed inside
`run_m1_llm_for_criterion`, so `str(client.base_url)` is unavailable where the key
is computed. Threading it there is part of the diff, not a one-line addition.

**The concrete scenario.** A user runs EL against OpenAI `gpt-4o-mini`. They then
follow the README's Ollama recipe — `OPENAI_BASE_URL=http://localhost:11434/v1`,
`OPENAI_API_KEY=ollama` — and, because the README's llama.cpp section tells them
*"The **Model** field can be set to any value … since the server uses whichever
model is currently loaded"*, they leave the Model field untouched. **Result: 100%
cache hits and OpenAI's answers, reported in the log as a normal `cache_hits=N`.**
The bundle records neither the endpoint nor the model, so the substitution leaves
**no trace in any artefact**. A colleague sharing that bundle inherits it.

**This is F-01's exact failure shape displaced onto the provider axis**: the key
enumerates what determines the answer, and the endpoint determines the answer. The
docstring's own argument — "anything that changes what the model sees changes the
key automatically" — is true and **does not cover *who answers*.** Severity today:
**Medium**, because reaching it requires a `.env` edit. Under either destination:
**High**, because it becomes two clicks (C-4).

#### B4.3 Would a default-model change break the goldens? **No — proved, not inferred**

The decisive fact is *where the regression harness gets its model*, and it is
neither an explicit literal nor `DEFAULT_MODEL`:
`tests/test_el_regression.py::_el_to_csv` passes **`model=invocation["model"]`**,
read from the golden's own `_invocation` envelope by `::_load_cache_envelope`. The
IL twin is identical. **So the model and the keys it must match ship in one file
and cannot drift.**

**[measured]** the experiment, run read-only with no file edited — possible because
`DEFAULT_MODEL` is `os.environ.get("SCREENA_EL_MODEL", …)`, so the production
default is changeable with zero source edits:

| Run | Result |
|---|---|
| `python -m pytest -q` | **422 passed, 4 skipped** |
| `SCREENA_EL_MODEL=gemma3:12b SCREENA_IL_MODEL=gemma3:12b python -m pytest -q` | **422 passed, 4 skipped** — identical |

with `conftest.get_el().DEFAULT_MODEL` confirmed to print `gemma3:12b`, and grep
confirming zero occurrences of either constant or either env var anywhere under
`tests/`.

**So the goldens are insulated. They pin `gpt-4o-mini` as an experimental control,
and a default change is a documentation problem, not a golden problem.** The
corollary is the uncomfortable half: **it is also invisible**. 16 CI cells stay
green for a shipped default that has never been run (C-12).

**[measured]** the key-recomputation figures, reproduced twice independently by
replaying the committed goldens through the real engines with a key recorder
installed on the screen module (no repository file touched):

| Variant | EL keys matched | IL keys matched |
|---|---|---|
| `gpt-4o-mini`, T=0.0 (as captured) | **170 / 170** | **84 / 84** |
| `gemma3:12b` | 0 / 170 | 0 / 84 |
| `llama3.1` | 0 / 170 | 0 / 84 |
| `gpt-4o-mini`, T=0.1 | 0 / 170 | 0 / 84 |

**The converse asymmetry is the reassuring structural property: a model swap cannot
*accidentally* corrupt the goldens — every key changes, every lookup misses, the
evidence goes empty, and byte-identity fails loudly. It can only *deliberately* do
so, by re-capturing.**

One incidental measurement worth recording because it explains a number: IL
computes **168** keys across its two enabled criteria while the golden holds **84**,
because `IC-5` has `operator="contains"` and never reaches the write-back site
(gated `if c.operator == "llm" and to_call:`). All 84 hits are `IC-1`'s.

#### B4.4 What else keys off the model literal

| Site | What a default change does |
|---|---|
| `tools/capture_el_il_goldens.py::MODEL` | nothing automatically — it is a module constant with **no CLI override**. It must be edited by hand for a re-capture, and its docstring's claim that it must match values in the two test modules is **already wrong** (§A11.3) |
| the goldens' `_invocation.model` | nothing — it is read *by* the tests, so it insulates them |
| `tests/test_cache_key.py` | nothing — it uses its own literals and only asserts that *changing* the model changes the key |
| `tests/test_cancellation.py`, `tests/test_not_screened.py` | nothing — inert literals; the surrounding tests never reach the API |
| `tests/test_metadata.py`, `tests/test_manifest_digests.py`, `tests/test_frozen_build_spec.py` | nothing — **[measured]** zero occurrences of `model` in any of the three |
| `ELView`/`ILView` prefill and run-time fallback, and both standalone shells | the new literal would be used — but **[measured]** no test instantiates those views, so those sites are never executed by the suite |
| documentation | 6 public + 4 internal sites become wrong (§A3.4). `docs/llm-evaluation.md`'s archived-run model must **not** change |

**One documentation row deserves a correction rather than a ripple note.**
`docs/installation.md`'s `OPENAI_MODEL` row is **already false at `f952e69`**, on
two counts independent of any default change: it states the default as
`gpt-4o-mini` when the only consumer of that variable defaults to **`gpt-4o`**, and
it implies `OPENAI_MODEL` is the per-plugin EL/IL lever when EL/IL never read it.
"Becomes false" understates it; "already false, and a default change makes it more
so" is accurate (C-38).

#### B4.5 Would adding the endpoint invalidate the goldens? **Yes. Every entry, in both stages, unconditionally.**

**[measured]**, reproduced independently, for both candidate values:

| Candidate hashed value | EL | IL |
|---|---|---|
| `base_url = ""` (absent-as-empty) | old keys matched 170/170; new distinct 170; **collisions 0; overlap with golden 0** | old 84/84; new 84; collisions 0; **overlap 0** |
| `base_url = "https://api.openai.com/v1"` (SDK-resolved default) | same shape; **overlap 0** | same; **overlap 0** |
| the two candidate key sets against **each other** | **overlap 0** | **overlap 0** |

Mechanism: `_cache_key` serialises with `sort_keys=True` before hashing, so a
five-member object is a different pre-image from the four-member one regardless of
the value. **And note the design trap the measurement exposes: hashing an *absent*
base_url as `""` and hashing the SDK's *resolved* default give disjoint key sets, so
the choice of which to hash is a one-way door — changing one's mind later costs a
second re-key** (§B9 Q1).

#### B4.6 What an equivalence proof would have to demonstrate

The shape exists in this repository and should be reused verbatim. Wave 2's re-key
lives **only as commit `c8d2fb3`'s message** — **[measured]** `git show --stat
c8d2fb3` is three files (`CHANGELOG.md` plus the two cache fixtures at
`Bin 76992 -> 76992` and `Bin 30504 -> 30504`); **the script was never
committed.** The message states the principle and the five obligations:

> "Re-key, NOT a re-capture … No API call was made and no decision was
> recomputed."

with the checks: **EL 170 entries → 170, 1:1, 0 collisions, 0 orphans**; **IL 84 →
84**; **values byte-identical as multisets**; **new key sets disjoint from the old
ones**; **`_invocation` preserved** — plus the four decision-file digests
unchanged (`604cb2f5…`, `088cca9d…`, `af029f8d…`, `c4c5d739…`). `FIX_WAVE_2_CRITICALS.md`
set only two obligations; the commit discharged five.

**Is such a proof possible without a live model? Yes — and that is exactly why wave
2 could do it offline.** A re-key transforms **keys** while **values** are copied
byte for byte, so every obligation is a property of a mapping over committed data.
The same is true of an endpoint addition. **[measured]** all five discharge offline
for the change in §B4.5.

**Two boundary conditions to carry forward.** First, one obligation is *not*
offline-dischargeable: adding a field whose value for the archived run is **not
known** — the SDK version is the concrete case, and it can never be added
retroactively (C-41). Second, wave 2's own closing note is the right warning:
a change to the *prompt* or to *criterion content* needs "a real re-capture", not
a re-key. **A model change is a fourth trigger that the CHANGELOG entry does not
list.**

**The artifact obligation.** Wave 2's proof was discharged and then thrown away.
If an endpoint re-key is done, the migration script (or a test that regenerates
and re-verifies the mapping) should be **committed this time** — otherwise the
next wave inherits the same "the message says it was proved" situation.

#### B4.7 One further reproducibility hazard, from a file nobody had read

`.gitattributes` is three lines: `* text=auto`, a comment, and
`tests/golden/** binary`. **[measured]** `git check-attr` confirms
`tests/golden/*` is `binary` while **`samples/20260122_1654_aggregate.csv` and
`docs/data/eval_results_v1.csv` are `text: auto`**.

Three things follow that no prior document states. **The golden byte-identity story
rests on this file** — every re-key analysis and every line-terminator finding
assumes committed golden bytes are checked-out golden bytes, which is true *only*
because of that one line. **`docs/data/eval_*` is not protected**, so
`docs/llm-evaluation.md`'s claim that re-running the ingestor "reproduces the four
output files byte-for-byte" is a claim about a working tree, not about a commit.
And **`samples/*.csv` is not protected either, and it is the input to the capture
tool**: **[measured]** the corpus is stored with 2096 CRLF and 0 bare LF, and **15
of its fields contain an embedded newline** — bytes that go verbatim into the
rendered prompt, which is hashed into every cache key. **So two maintainers
re-capturing goldens from the same commit with different `core.autocrlf` obtain
different cache keys.** That hazard sits directly on the path a model swap
prescribes (C-14).

---

### B5 Safety under weaker models

#### B5.1 Half one — verified from source AND from tests

**Two premise corrections first, both load-bearing.** The brief asks how `used`,
`valid_quote` and `confidence` "combine in the evaluator". **They do not combine in
`plugins/_common/evaluator.py`, which has no evidence gate and is not on the EL/IL
path at all** (§A7.1) — the register will otherwise acquire an `evaluator.py`
coordinate for a finding that lives in `screen.py`. And **`used` is not a gate
term.** The gate is the three-way conjunction; `used` is written, and read once
~36 lines later only to be *recorded* in the evidence dict. **[measured]** across
`plugins/`, `"used"` appears nine times — three writes in `llm_client.py`, one
write per stage in the non-llm branch, one `ev.setdefault("used", True)` per stage
on the cache-hit path, and one read per stage inside the evidence dict.
**No conditional anywhere tests it.** (One consequence of that `setdefault`: a
cached entry lacking the key is exported as `used: true`.)

**The structural guard.** Within `run_el_screen` and `run_il_screen`, `failed.append`
occurs **only** inside `if usable:`, and `outcome = "OUT"` only `if failed:`. That
conjunction is the entire safety property. *Scoping correction:* `failed.append`
and an `outcome = "OUT"` assignment also occur in
`plugins/_common/runner.py::run_screen` — the deterministic EH/IH orchestrator,
which never consults an LLM result — so the guard must be stated as holding
*within the two LLM stage engines*, not as "the only sites in the tree".

**[measured]** the battery, reproduced in-process against the real engines with
`_openai_client_for` and `_has_openai_key` replaced locally, 6 synthetic records,
one `operator="llm"` criterion, `batch_size=3`, `threshold=0.6` — and, beyond what
the brief asked, at **both criterion polarities** (60 stage × polarity runs):

| # | Failure mode | Result-dict state | Outcome | Proving test | Verdict |
|---|---|---|---|---|---|
| 1 | transport failure | `used=False, uncertain, qv=False`, `error` | flag | **NONE** | `OUT=0` **[measured]** |
| 2 | timeout | same | flag | **NONE** | `OUT=0` **[measured]** |
| 3 | malformed JSON | back-fill, no `error` | flag | **NONE** | `OUT=0` **[measured]** |
| 4 | missing `decision` | `uncertain`, conf/quote kept | flag | **NONE** | `OUT=0` **[measured]** |
| 5 | missing quote | `qv=False` | flag | **NONE** | `OUT=0` **[measured]** |
| 6 | quote not a substring | `qv=False` | flag | **NONE** | `OUT=0` **[measured]** |
| 7 | confidence below threshold | `usable` False | flag | **NONE** | `OUT=0` **[measured]** |
| 8 | model refusal | back-fill | flag | **NONE** | `OUT=0` **[measured]** |
| 9 | empty response / `content=None` | back-fill | flag | **NONE** | `OUT=0` **[measured]** |
| 10 | `a_id` omitted from the reply | back-fill, `used=False` | flag | **NONE** | `OUT=0` **[measured]** |
| 11 | `a_id` **not in the batch** | see §B5.2 | **CAN EXCLUDE** | **NONE** | **C-1** |
| 12 | `decision` outside the whitelist | silently `uncertain` | flag | **NONE** | `OUT=0` **[measured]** |
| 13 | `field` outside the whitelist | coerced to `abstract`, `qv=False` | flag | **NONE** | `OUT=0` **[measured]** |
| 14 | malformed `span` | discarded to `None` — **`span` is not a gate term at all** | governed by the accompanying decision | **NONE** | **[measured]** `OUT=6/6` when accompanied by a well-formed confident `meet` on an exclude criterion. **This mode is not *safe*; it is *not a gate term*** — the exclusion is caused by the real answer beside it |
| 15 | no key / no model | `{}` → every pair absent → `uncertain` | flag | **NONE** | `OUT=0` **[measured]** |
| 16 | user cancellation | results already received kept; unreached pairs absent → `uncertain` | flag | **see below** | the property is asserted by **no** test |

**Counterexample hunt over the cases the brief names, all [measured]:** inverted
polarity — `exclude`+`meet` → FAILED and `include`+`not_meet` → FAILED are both
live in the golden criteria, and this is a **real model answer**, not a failure
mode; non-`llm` operator — `how` is derived from `operator`, never an independent
switch; **threshold 0.0 and −1.0** — the confidence conjunct becomes vacuous but
`valid_quote` and the decision whitelist each still refuse, `OUT=0`; empty criteria
set — early return to `NOT_SCREENED`, all survivors, and this one **is** asserted
(`tests/test_not_screened.py::TestELILZeroCriteria`); `block_tag` — reaches only
three progress-event payloads, no semantic effect.

**Test coverage of the safety property: 0 of 16.** This is the sentence a reader
will use to judge how much of the design guarantee is machine-checked, so it must
be exact. **[measured]** `grep "usable" tests/*.py` returns one unrelated hit;
`grep 'counts\["OUT"\]' tests/*.py` returns exactly one assertion, and it is on the
*deterministic* EH/IH path; only four test sites call the LLM stage engines at all,
and two of those use `operator="contains"` while the other two are the golden
replays. Cancellation is the only mode with any deliberate test, and those tests
assert a **different contract**: all three call `run_m1_llm_for_criterion` directly
and assert on its returned dict — `client.calls == 2`, `len(out) == 10`,
`val["decision"] != "uncertain"` — never on a stage outcome. One of them asserts
that every preserved decision is `"meet"`, which on an exclude criterion is
precisely the value that produces `OUT`; **the test pins exclusion-capable answers
and is compatible with a cancelled run excluding records.** What cancellation
genuinely has tested is three useful but different things: that the `cancelled`
flag is returned, that already-received results are not replaced by fabricated
non-answers, and that export is refused.

**One qualification in the other direction, and it is to the credit of the
goldens.** It would be wrong to say nothing exercises the gate. **[measured]** the
golden replays execute it **170 times at EL and 84 at IL**, and pin its refusals
byte-for-byte: `el_cache` holds 2 entries with `valid_quote: false` and 5 below
threshold, and `el_filtered` records those exact 7 as `UNCERTAIN` with all 7 owning
records `PASS_FLAGGED`; IL has 5 bad-quote + 30 low-confidence + 2 both = 37
`UNCERTAIN`, all 37 owning records `REVIEW`. **So the `valid_quote` and
`confidence` conjuncts are exercised and their consequence is pinned — but
incidentally.** What is missing is (a) any *named* assertion, so a failure surfaces
as "the EL FULL report changed" rather than "the gate stopped refusing", and (b)
any exercise of the **third** conjunct against a non-member, since the caches
contain zero `decision: "uncertain"`, zero `used: false` and zero `error` keys
(C-11, C-16).

#### B5.2 C-1 — the one mode that can exclude, verified independently

`idx_map` is built from the **entire `items` argument** *before batching touches
anything*, while the "ensure every item has an entry" back-fill iterates only
`cur_batch`, and the parse-loop write `out[(a_id, cid)] = {...}` is **unguarded**.

**I reproduced this myself, in-process, no files written:**

```
FORWARD drift, batch_size=3: calls=2 entries=6 -> would-EXCLUDE ['A003','A004','A005']
    each: decision=meet conf=0.99 valid_quote=True used=True
FORWARD drift, batch_size=1 (claimed mitigation): calls=6 entries=6 -> would-EXCLUDE ['A003','A004','A005']
BACKWARD drift, batch_size=3 (overwrites correct answers): calls=2 -> would-EXCLUDE ['A000','A001','A002']
```

**Four things this establishes, three of which correct an initial reading:**

1. **The verdict is accepted and validated against the *other* record's real
   text**, because `idx_map` carries every item's fields — so `valid_quote` comes
   back **True** and the gate passes. Downstream: 3 of 6 records `OUT`.
2. **`batch_size = 1` does NOT mitigate it.** `idx_map` is built from `items`
   independently of batching, so it always holds every item in the run. Lowering
   the batch reduces how many foreign `a_id`s the model *sees* per call; it can
   still name any `a_id` in the run. Any advice that the defect "cannot fire at
   `batch_size = 1`" is wrong and must not ship.
3. **There are two routes, and the *backward* one is strictly more available.**
   Forward drift (a stray id belonging to a *later* batch) sticks only if the
   owning batch omits the item, via the back-fill's `not in out`. **Backward drift
   (a stray id belonging to an *already-answered* batch) sticks unconditionally,
   because the parse-loop write has no guard — it destroys a correct verdict and
   requires no second failure.** Forward drift where the owning batch *does* answer
   is safe: the honest answer overwrites the stray.
4. **It is persistent, not transient.** The write-back caches every entry under the
   *substituted* record's own legitimate key, so **[measured]** a second run
   replaying that cache reproduces the 3 exclusions with **0 API calls**, reported
   as a normal `cache_hits=N`. Once it fires it is sticky until the cache or the
   prompt changes.

**Precision on the headline.** "Excludes a record that was never sent to the model"
is **false as written** — the batches are precomputed and all of them run, so the
record *is* sent; the model simply says nothing about it. The exact true statement
is: **the verdict that excluded the record was produced by a call whose prompt did
not contain that record, and the call that did contain it either said nothing or
was overwritten.** The single-line fix is to scope the acceptance guard to the
current batch.

**A companion route outside the enumerated sixteen, input-driven rather than
model-driven.** `run_el_screen` keys results by `a_id` alone, and `idx_map` does
too — so **two corpus rows sharing a `local_id` share one verdict**, validated
against whichever row wrote `idx_map` last. **[measured]** with three rows, two
carrying `local_id="A000"` and only the second containing the quoted text: `OUT=2`,
both A000 rows excluded with `quote_valid: true`, **including the row whose own
abstract does not contain the quote.** This is guarded only *upstream*, by
`plugins/06_el/screen.py::_load_bundle`'s duplicate-`local_id` diversion — and any
caller that builds a `ParseReport` directly, as the regression tests do, bypasses
that guard. **The safety property here is carried by the bundle loader, not by the
gate** (C-2).

#### B5.3 Half two — which modes a small local model hits more often, and what that does to the flag rate

*Capability judgements in this subsection are* **[general knowledge, not repo
evidence]**; *the repository-derived facts about what the code does with a failure
are from §A6.*

What the prompt actually demands: a **JSON-only** reply; a **list** of objects, one
per item; an **exact substring** quote from a specified field; a calibrated
**confidence** in 0..1; correct **`a_id` echoing** across a batch of up to **50**
items; and all of it instructed **only in the system message**, with no
`response_format` and no schema.

| Demand | Difficulty for a small open-weight model | What the code does with the failure |
|---|---|---|
| **Exact-substring quoting** | **Hardest, and it bites first.** Paraphrase, re-casing, smart-quote or dash substitution, ligature expansion, NFC/NFD — all common | fails **closed** → flag. §A7.3 established the gate normalises **whitespace only**, so every one of those substitutions fails |
| **A single valid JSON list** | Hard. Prose preambles, fenced blocks preceded by text, a bare object for a one-item batch, `{"results": …}` wrappers, trailing commas, truncation | `_parse_llm_json_array` → `[]` → whole-batch back-fill, **with no log line at all** — indistinguishable in the artefact from genuine all-uncertain |
| **`a_id` fidelity across 50 items** | Hard. Renumbering, invention, omission and duplication are characteristic | omission → flag; invention → silently dropped; **drift into another batch → C-1** |
| **Confidence calibration** | Hard, and *differently* hard: the characteristic small-model failure is **over-confidence**, not hedging | a model that emits 0.95 for everything makes the threshold vacuous; one that emits 0.5 makes the gate refuse everything |
| **Decision vocabulary** | Moderate — but §A6.3's missing `.lower()` means `"Meet"` silently becomes `uncertain`, so **case drift alone converts the whole stage into a no-op** | flag, with a contradictory audit record (C-5) |
| **Instruction-following at batch 50** | Hard; degrades with batch size | more of all of the above |

**The consequence, stated precisely: because non-answers route to flag/review
rather than to exclusion, a weaker model does not make the tool *unsafe* — it makes
it *useless* at a high enough failure rate, because the human must adjudicate
everything.** That is the difference between "safe" and "usable", and it is the
right frame.

**Can that be quantified from repository evidence? [not established].** What the
baseline *is*: **[measured]** at EL, 7 of 170 per-decision gate refusals (4.1%),
affecting 7 of 85 records (8.2%); at IL, 37 of 84 (44.0%) — and IL's is already
that high largely because `IC-5`'s blanket `UNCERTAIN` (F-65) pushes 80 of 84
records to `REVIEW` regardless of the model. **A model-vs-model comparison against
that IL baseline would be comparing against a distorted control, and anyone
benchmarking should know it before, not after.** What would settle the quantitative
question is a bake-off protocol holding fixed: the corpus, the harmonised criteria
(including thresholds), `trunc_chars`, `batch_size`, temperature, and the prompt
version — varying only the model, and reporting per-decision *and* per-record flag
rates plus the reason each refusal fired. **That last part is currently impossible:
§A7.6's `UNCERTAIN` carries no reason code, so the protocol needs F-64's
`uncertain_reason` first** (§B8).

**Would the retry loop fire more or less often locally?** Less, and that is the
wrong direction. **[general knowledge]** a local server's error strings differ from
OpenAI's, so `is_big` will often match nothing — and the batch-halving and
truncation step-down that exist precisely for a small context window will **never
fire**, sending the batch terminal instead (C-9). Meanwhile `_check_cancel`'s
single call site means a long local generation cannot be interrupted at all
(C-14).

**Does the existing degenerate-output note anticipate this? Partly, and by the
wrong route** — see §B6.4.

---

### B6 Scientific-validity implications

**Two premise corrections first.** There is **no "README results/validation
section"** in the sense the brief implies: README has 45 headings and none is a
results section; the three figures appear in the *Overview* and the validation
study appears only as a documentation link. **No kappa value appears anywhere in
README** — the only kappa figures outside `docs/llm-evaluation.md` and
`docs/data/` are in `docs/faq.md`. And the raters are not merely "suggested" by the
grid filenames: `docs/data/grids/partition_manifest.meta.txt` is six lines and
names them outright — `seed=42`, `raters=AReyes,JKiss,JVoisin`,
`EL_n_overlap=15`, `EL_criteria=EC-2,EC-3`, `IL_n_overlap=15`, `IL_criteria=IC-1` —
which cross-reference against `CITATION.cff::authors` to the three co-authors.
`docs/llm-evaluation.md` states this directly and lists it as a limitation
("**Raters are the paper authors.** This is a known in-group bias").

#### B6.1 What is specific to `gpt-4o-mini`

**The attribution chain, established end to end — repository evidence, not
inference:**

```
docs/data/eval_summary_v1.txt              (the published kappas)
  ← tools/eval_ingest.py                   (no LLM call; reads *_evidence_json)
  ← tests/golden/{el,il}_filtered_v3.1.0.csv :: {el,il}_evidence_json
  ← tests/golden/{el,il}_cache_v3.1.0.json  :: cache      (170 + 84 entries)
  ← tests/golden/{el,il}_cache_v3.1.0.json  :: _invocation.model == "gpt-4o-mini"
```

**[measured]** joining all **344** rows of `docs/data/eval_results_v1.csv` against
the committed filtered goldens: for every row, `llm_status`, `llm_confidence` (to
3 dp) and `llm_quote` match the corresponding evidence entry exactly — *checked
344, mismatch 0, missing 0*. **So the published agreement study is computed over
the committed goldens, and the only model attribution anywhere in that chain is the
`_invocation.model` field of two test fixtures.**

**That field is the single point of failure for the entire validity claim.** It is
not in the manifest, not in the filtered CSVs, not in the cache values, not in
`docs/data/*`, not in `eval_summary_v1.txt`, and not in `CITATION.cff` or
`.zenodo.json`. **[measured]** the only line in all of `docs/data/` matching
`model` is one record whose keyword list contains "Structural equation modeling".

**The validation study's parameters, every one named:**

| Parameter | Value | Source |
|---|---|---|
| Corpus | 776 records; the LLM stages see the 85 EH+IH survivors | `docs/llm-evaluation.md`; `el_input_v3.1.0.csv` |
| Criteria | exactly the three `operator=llm` rows: `EC-2`, `EC-3` (exclude, EL), `IC-1` (include, IL) | `criteria_harmonized_v3.1.0.csv` |
| **Target field of all three** | **`keywords`** | same file |
| Threshold | `0.60` on all three | same file |
| Temperature | **not recorded in any artefact**; the engines default `0.0` and the capture tool passes none | the capture tool; `run_el_screen` |
| `batch_size` / `trunc_chars` at capture | **5 / 4000** — neither is the production default | `_invocation` |
| **Model** | **`gpt-4o-mini`** | `_invocation.model` — the only occurrence |
| Human raters | **AReyes, JKiss, JVoisin** = the three co-authors | `partition_manifest.meta.txt`; `CITATION.cff` |
| Assignment | seed 42; 15-record overlap per stage rated by all three; disjoint remainder | `partition_manifest.csv` |
| Decisions | **254** LLM (85 + 85 + 84); **344** human; 88 disagreements | `docs/llm-evaluation.md`, corroborated by row counts |
| Model disclosed to raters | **No** — `tools/eval_grid_generator.py` never emits one |
| Model disclosed in §Results | **No** — and the only model named in the whole document belongs to a *different*, degenerate run |

**The scientifically load-bearing consequence that no document states.** All three
adjudicated criteria have `target=keywords`, and **[measured] 170/170 EL and 84/84
evidence quotes carry `field: "keywords"` — none quotes `title`, none quotes
`abstract`.** In this corpus `keywords` is a semicolon-delimited controlled-vocabulary
term list: 140 of 170 EL quotes contain `"; "`, and quote length min/median/max is
12 / 202 / 270 characters. **So the published quote-validity rate (measured:
333/344 `llm_quote_valid=true`) and the 83–87% observed agreement were earned on a
task where "produce a verbatim substring" means "echo back a machine-generated term
list". The evidence gate has never been measured against prose extraction from an
abstract, in any run in this repository.** That is the project's most
transferable-*looking* claim resting on its narrowest evidential base — and it is
precisely the claim a small local model is most likely to break (C-10).

**Claim by claim, what a default-model change falsifies:** the 98.3% figure — no
effect, model-free. 73 / 90.6% — already unreproducible, becomes doubly so.
"replaying the goldens today yields 80" — the *claim* survives (fixture-pinned) but
**silently stops describing the shipped default**. The six Cohen and Fleiss kappas,
the three confusion matrices, the FAQ's "Cohen 0.28, Fleiss 0.26", and the "83–87%
observed rate" — **all model-specific, all undeclared at every site, and all
falsified as descriptions of the running tool**. And the *behavioural*
characterisation "the LLM hedging to `unsure`" is **falsified in direction as well
as magnitude**, because over-confidence rather than hedging is the characteristic
small-model failure.

**Nothing pins the published kappas.** `tests/test_eval_ingest.py`'s end-to-end
fixture runs the ingestor against **synthetically modified** filtered CSVs into
`tmp_path` and asserts only structural properties plus a loose
`agree_count / len(rows) > 0.7`. **It never reads `docs/data/eval_summary_v1.txt`.**
Combined with the unpinned `DEFAULT_MODEL`: a model swap, plus a re-capture, plus a
re-run of the ingestor, would **rewrite every published figure with the full suite
green** (C-12).

#### B6.2 Are the goldens model-specific artifacts?

Both senses the brief distinguishes are real and the file-level split is clean — but
**two of the files carry a third role the brief does not name, and it is the role
that matters most.**

**Sense (a) — model-specific as DATA.** `el_cache_v3.1.0.json` (170 entries) and
`il_cache_v3.1.0.json` (84) are **recordings of an inference run**: one specific
model's literal answers. Nothing in them is derivable from the repository; they can
only be re-obtained by paying for another run against the same model.

**Sense (b) — model-specific only transitively.** `el_filtered_v3.1.0.csv` (85
rows) and `il_filtered_v3.1.0.csv` (84) are deterministic functions of input +
criteria + cache. **Model-independent:** both `*_input` goldens, both
`*h_filtered` goldens, and `criteria_harmonized_v3.1.0.csv` (produced by the
*rule-based* harmonise path). **So of nine golden files, two are model-specific
data, two are model-specific derivatives, and five are model-independent.**

**The third role.** The two filtered CSVs are simultaneously **(1)** the byte-identity
regression control and **(2)** the primary data source of the published validation
study — `docs/llm-evaluation.md` passes exactly those two paths to
`tools/eval_ingest.py` and says so, and §B6.1 verified role 2 numerically. That
dual role deserves stating plainly:

> **The repository has one artefact pair serving as both its software-regression
> fixture and its scientific dataset. Those two roles have opposite maintenance
> pressures. A regression fixture is *meant* to be re-captured whenever the thing
> it guards legitimately changes. A published dataset must never change after the
> figures derived from it are cited. A single re-capture — the exact operation
> `tools/capture_el_il_goldens.py` exists to perform, and the one a model swap
> requires — silently invalidates every kappa in `docs/llm-evaluation.md`, every
> number in `docs/data/eval_summary_v1.txt`, and the FAQ's "Cohen 0.28, Fleiss
> 0.26", with no test failing and no changelog obligation triggered.** (C-13)

**What a default change does to what the goldens PROVE:**

| | Before | After a default change, no re-capture |
|---|---|---|
| What they **prove** | downstream determinism, given a fixed answer set | **unchanged — all of it.** The proof is conditional on the answer set and never mentions the model |
| What they **describe** | what a user running the shipped default experiences | **nothing.** They describe `gpt-4o-mini` |
| What the tests **detect** | any drift in the deterministic layer | the same — **and not the default change** |
| What the published figures **describe** | `gpt-4o-mini`, undeclared | `gpt-4o-mini`, still undeclared, now presented beside a different default |

#### B6.3 What would have to be SAID

**The scientific-integrity point, without hedging: performance figures obtained
with one model do not transfer to another. A tool that ships model B as its default
while displaying agreement figures measured with model A is making an empirical
claim it has not tested.** In this repository that claim would be made in nine
files, and in six of them the figures currently carry **no model qualifier at
all** — so the claim is *already* being made implicitly, and a default change merely
makes it false rather than merely undeclared.

**The structural blocker, first — three of the edits cannot be made in prose.**
`docs/data/eval_summary_v1.txt` is **generated** by `tools/eval_ingest.py`, whose
inputs (the partition manifest, the criteria CSV, the filled grids, the two filtered
CSVs) **contain no model field**. Either the ingestor gains a `--model` argument — a
hand-asserted string, i.e. the same weakness `_invocation` already is — or the
filtered CSVs gain per-decision model provenance, which is the change §A9 identifies.
Same dependency for an `llm_model` column in `eval_results_v1.csv` and
`eval_disagreements_v1.csv`. And the §Reproducibility command block promises
byte-for-byte regeneration, so the promise and the edit must land together.
**Consequence for sequencing: the documentation edits are downstream of the
provenance fix. Doing them first produces a hand-typed model string in a generated
file — which is exactly what `_invocation` already is, and exactly what made this
problem invisible.**

**The edits, by file.** `docs/llm-evaluation.md` — **9**: a new "Model under
evaluation" block in the head (there is presently no such statement anywhere in the
document); the "254 decisions" line; a model row on each of the three metrics
tables; the "the LLM is conservative" passage (the generic definite article is the
error — it reads as a property of LLM screening); **a new "Single model" limitation
beside the existing "Single corpus"**; the "no temperature sweep" bullet, which
should state the actual value since "the bundle's default" is not a thing that
exists; the stale gate citation; and the 73/80 discussion. `README.md` — **5**: split
the model-free 98.3% from the model-conditional 73/90.6 rather than reporting them
in one breath; qualify "yields 80"; the two `SCREENA_*_MODEL` rows; and **promote
the open-weight caveat out of the "Using local LLM providers" section** — if local
is the default, a caveat living in an optional-configuration section is in the wrong
place, and it is the single most accurate sentence about this in the repository.
`docs/faq.md` — 3. `docs/usage.md` — 3 (including the figure caption and the
unqualified 73/90.6%). `docs/index.md` — 1. `docs/installation.md` — 1 (already
false). `docs/data/*` — 3 generated files, blocked as above. `CITATION.cff` /
`.zenodo.json` — **no edit needed**: both are model-agnostic, which is the correct
posture and should be preserved. `CHANGELOG.md` — one obligation: the `[3.1.0]`
entry warns that a prompt or criterion change "needs a real re-capture", and **a
model change is a fourth trigger it does not list**.

**The minimum a reader needs in order not to be misled** is three sentences: a
head-of-document statement that all agreement figures were measured with
`gpt-4o-mini` at temperature 0.0 on this corpus from the goldens captured on
2026-05-02 and **do not transfer**; a "Single model" limitation bullet; and,
wherever the shipped default differs, a note naming both models and stating that
the figures have not been re-measured.

#### B6.4 Does the degenerate-output note cover the new cases?

The note is **good** — unusually candid, it names the mechanism, it bounds its own
generality ("This is one observed run, on one corpus, with one model. It is
reported because it happened, not as an estimate of how often degenerate output
occurs"), and it should be **preserved and extended, not rewritten.** But its frame
is **one failure mode: collapse of output variance in a model that is otherwise
contract-compliant.** The archived run produced parseable JSON, valid decision
tokens, matching `a_id`s and mostly-findable quotes — it simply produced the *same*
ones.

| New failure mode | Anticipated? | Assessment |
|---|---|---|
| **Exact-substring quoting failure** | **Partially, and by the wrong route** — the note gives a rate (38/170) but as a *symptom of degeneracy*, not as a model-capability limit, and it never states which field the quotes came from | **Needs extension, and needs the field fact from §B6.1.** A reader is given no way to see that the published rate does not cover prose extraction |
| **JSON-shape failure** | **No. Not addressed at all** | **The most consequential omission.** A parse failure produces zero variance *too*, so it presents with the same signature as the degeneracy the note describes — **and the note's own advice ("treat per-run decision and confidence variance as something to inspect") actively misfires: a reviewer would diagnose a lazy model rather than a broken response contract.** There is no log line (C-11) |
| **Confidence miscalibration** | **Partially — and the note's own evidence understates it** | **[measured]** on the *committed* goldens the kappas rest on: EL 141/170 at exactly 0.9; pooled across `eval_results_v1.csv`, **213/344 = 62% at exactly 0.900**, with only **10 distinct confidence values in the entire study**, everything above the bar in {0.7,0.75,0.8,0.85,0.9,0.95} and everything below in {0.1,0.2,0.3,0.4}, **with a gap straddling 0.60**. This is not a calibrated posterior; it is a coarse verbal scale. **So the 0.60 threshold is doing far less work than a reader would assume**, and a model with a different verbal-confidence habit changes the exclusion count by a mechanism the note does not name. No calibration curve exists anywhere |
| **`a_id` drift** | **No. Not addressed** | Silent on both sides: an unrecognised id is dropped with no counter and no log; a missing one is back-filled with no log; a duplicate overwrites — **and C-1 makes a stray id from another batch *exclusion-capable*** |

**One further extension the note needs, from its own data.** **[measured] the
committed goldens are themselves a weaker instance of the pathology the note
reports as an anomaly of a *different* run:**

| | Archived run (per the note) | **Committed goldens (`gpt-4o-mini`)** |
|---|---|---|
| EL decisions | 170/170 `not_meet` | **169/170 `not_meet`, 1 `meet`** |
| EL confidence | 170/170 at 0.9 | **141/170 at exactly 0.9** |
| EL distinct spans | 3 | **27 of 170** — top span `[0,140]` appears **52 times** |
| EL distinct quotes | not stated | **100 of 170** |
| Quotes rejected by the gate | 38 of 170 | **2 of 170** |
| Field quoted | not stated | **170/170 `keywords`** |

The note's framing — "Agreement figures describe runs in which the model produced
varied, per-record judgements" — is true of the goldens only *by comparison with a
fully collapsed run*. On EC-2/EC-3 the golden run is 99.4% one decision at a modal
confidence. The kappa-paradox discussion correctly attributes the skewed *marginals*
to the corpus; **it does not observe that the model's output is nearly as
concentrated, nor that the two would look identical from the outside.** That is not
a retraction of the kappa analysis — it strengthens the case for reporting observed
agreement — but it is a fact the document has and does not surface (C-11).

Also: **the note's variance metric is computed over a fabricated field.** It offers
"only three distinct evidence spans" as its degeneracy evidence, but **[measured]**
169/170 EL and 77/84 IL entries have `span[1]-span[0] != len(quote)`. **Span
diversity is a proxy for nothing.** Switch the metric to distinct quotes, or fix
`span` first (C-11, C-16).

#### B6.5 Archival artifacts — is there a mismatch risk?

| Artifact | Pins a model? | Pins a figure? | Risk from a default change |
|---|---|---|---|
| `CITATION.cff` | No | No | **None.** Model-agnostic abstract |
| `.zenodo.json` | No | No | **None from a model change.** Its audit claim is already overstated given §A9, but that is independent |
| README BibTeX | No | No | none |
| **Git tag `v3.1.0`** | **Yes, indirectly** | **Yes** | see below |

**The archival snapshot does pin `gpt-4o-mini`, and the pin is inside a test
fixture.** **[measured]** `git show v3.1.0:tests/golden/el_cache_v3.1.0.json` carries
`_invocation = {'batch_size': 5, 'model': 'gpt-4o-mini', 'trunc_chars': 4000}` and
170 entries; the tag also contains `docs/llm-evaluation.md`, all four
`docs/data/eval_*` files, the three filled rater grids and the partition manifest.
**So the DOI-referenced release *is* the record tying the published kappas to
`gpt-4o-mini` — via a fixture envelope, nowhere else.**

**[measured]** `git diff --stat v3.1.0 HEAD` over the relevant paths shows only:
`docs/llm-evaluation.md` +106 lines (the reproducibility subsection), and the two
cache files re-keyed at **identical byte size** with `_invocation` unchanged. **All
four filtered/input goldens and all four `docs/data/eval_*` files are byte-identical
to the published record. The evidence base has not drifted from what was
archived** — which is good, and worth saying.

**The mismatch a default change would create is not with the citation metadata; it
is with the tagged snapshot's own internal consistency.** A future release whose
`DEFAULT_MODEL` is a local model, shipping the same `llm-evaluation.md` and
`eval_summary_v1.txt` byte for byte, would present figures that the *previous*
archived version's fixture attributes to `gpt-4o-mini` while the new version runs
something else — with no field in either release stating so. **And one further
exposure specific to the DOI: the only route that lets anyone recover the model at
all runs through the one file a model swap must overwrite.** If it is overwritten,
the kappas join the 73-figure as unattributable, and `docs/llm-evaluation.md`
already documents what that costs. **That is the strongest argument for making the
model a first-class manifest field *before* any model work begins** (C-3, and §B9
Q5).

---

### B7 Enumerated-list audit

#### B7.1 F-69's shape, and the two other times the project was bitten

The brief says the project has been bitten three times. **Accurate, and the three
are F-69, F-01 and F-06.** All three share one structure — **two hand-written
descriptions of a single thing, no test comparing them, and a failure mode that
preserves the appearance of correctness** — and two of the three shipped in
published artefacts.

**F-69, the most expensive.** The list was
`plugins/07_il/plugin.py::CONTRACT_STAGE_SHEET_COLS`, a hand-written column header
for the four stage sheets of the final Excel deliverable. It and the row builder
were written against different specifications and **intersected in 2 of 7 names**;
the writer is `[row_obj.get(c, "") for c in CONTRACT_STAGE_SHEET_COLS]`, so the five
non-intersecting columns silently resolved to `""`. **The four stage sheets had
never contained data** — row *counts* were correct, so the sheets looked populated
until a cell was inspected, and there was no golden and no test for the workbook.
The fix, from `FIX_WAVE_4_REPORTS.md` decision Q-B, verbatim: *"**No — derive the
header from the row builder's schema.** Drop the columns that have no data source
rather than emitting them empty."* The constant still exists — annotated as *being*
the row builder's key set and **pinned identical by test**.

**F-01.** The cache key **was an enumerated list of invocation parameters**, of
which only the criterion's *id* was named. Its own docstring now says it: *"Enumeration
was itself the bug."* Editing a criterion's wording while keeping its id was a
cache **hit**. Fixed by hashing the **rendered prompt** — i.e. by replacing the
enumeration with the artefact it was trying to describe. **This is the strongest
derive-from-one-source precedent in the repository.**

**F-06.** `tools/eval_ingest.py::CANONICAL_DECISIONS = ("yes","no","unsure")` versus
a hand-written `"uncertain"` returned elsewhere in the same file — two vocabularies
for one concept, ~500 lines apart. Any three-rater tie produced a pair the confusion
matrix dropped while `n` still counted it, **silently corrupting the validation
study's headline kappa**. Verified dormant in the committed data (0 ties in 45
overlap items) — **the bug shipped and was only not triggered by luck.**

#### B7.2 The audit

**[measured]** **zero `Literal[`, zero `Enum`/`IntEnum`/`StrEnum`, zero
`TypedDict`, zero `NewType` anywhere in the repository.** Every enumeration below
is a bare tuple, set, list, dict, prose sentence, `if/elif` cascade, or Markdown
table. **That is the structural precondition for all three drifts: nothing in the
type system can hold two descriptions of one vocabulary together, so only a test
can — and mostly no test does.**

**Group 1 — model identity (11 items).** The six default literals of §A3.1 plus
five documentation assertions. **Derivable?** A default's *value* cannot be derived
— someone must choose it — but its *count* can: collapse six literals in five files
to one app-level setting with a documented per-stage override, keeping plugin 01's
divergence and *stating* why. The five documentation assertions are all mechanically
pinnable against the constants, and none is pinned today.

**Group 2 — endpoints and env-var names (6 items).** `ENV_KEY`; the eight
`SCREENA_{EL,IL}_{MODEL,TRUNC_CHARS,BATCH_SIZE,USE_CACHE}` names written as 4 + 4
with four duplicated default expressions; the one-line `.env.example`; the README
and installation tables. **Derivable?** The eight env names **yes** — a two-line
helper parameterised by stage would produce all eight and make the EL/IL pair
provably symmetric (F-14's twinning in miniature). `.env.example` is **incomplete by
omission**, which is worse than un-derivable. And there is **no endpoint
enumeration in code at all**, because there is no endpoint handling.

**Group 3 — provider shapes and products (10 items).** `LOCAL_PROVIDER_HINT`'s four
product names; the dialog's grey label repeating the claim in different words;
`looks_like_openai_key` (a **one-member provider-shape enumeration disguised as a
predicate**, correctly demoted by F-08); `LOCAL_PROVIDER_KEYS` (the **only
executable artefact** naming the claimed provider set); README's four `###` product
sections plus its "Azure OpenAI, DeepSeek, and others" bullet; the FAQ's fifth
prose statement; the `is_rate`/`is_big` substring lists; and plugin 02's dead
`OPENAI_OK`. **Derivable?** The *structure* is: one shape statement plus a table of
example base URLs. The error lists are the sharpest structural win — see §B7.3(c).

**Group 4 — the model-output vocabulary (15 items), where B1(ii) and B7 meet.**
These lists **are** the capability the code demands of a model, and every one is
currently duplicated in prose *inside the prompt*. `decision`'s enforcing whitelist
in `llm_client.py`; the same three values spelled out **in prose in both
`prompt.py` files**; a 2-member subset restated at four more sites per stage;
`field`'s enforcing whitelist; the same three names in `idx_map`, in
`_make_item_for_llm`, in both prompt builders' prose *and* their `items_pack` keys,
in both screen modules' item construction, and five more times across plugin 03;
**the per-criterion status vocabulary `MET`/`FAILED`/`UNCERTAIN`/`MISSING`, for
which [measured] there is no constant anywhere**; the eval tools'
`_STATUS_MAP_INCLUDE`/`_STATUS_MAP_EXCLUDE` (duplicated between two tools, **both
copies omitting `MISSING`**, absorbed by `table.get(s, "unsure")` so a `MISSING`
criterion is silently rated "unsure"); and `("yes","no","unsure")` under **two
different names in three files** — F-06's exact terrain, structurally unrepaired
(C-26, C-27).

**Group 5 — criterion-operator capability (6 items).** `parser.py::OPERATORS` (9
members) restated as an `if/elif` cascade in `evaluator.py::_eval_criterion`, again
in `::_eval_criterion_detail` ~130 lines below, and **again in prose in
`llm_refine.py`'s system prompt sent to a model** — currently in sync 9 for 9, with
nothing enforcing it. Plus plugin 01's `tool_schema` enum. **Contrast
`plugins/03_harmoniser/ui.py`, which correctly derives its Combobox from
`OPERATORS` — the good pattern exists in the same subsystem** (C-27).

**Group 6 — adjacent, for exhaustiveness (9 items).** The two per-stage `OUTCOMES`
tuples; `STAGES` + its Combobox (**second good precedent**);
`CONTRACT_STAGE_SHEET_COLS` (**F-69 itself, now pinned — the pattern every row above
should be measured against**); `INPUT_ERRORS_FIELDS` and its alias lists (F-03's
deliberate terrain); `TARGET_ALIASES` (genuinely human knowledge); the corpus
normalisation maps; the eval tools' stage-keyed maps duplicated across three files;
`PROMPT_VERSION` + its test-side copy (**deliberate pinning — the correct use of
duplication**); and test/tool scaffolding.

#### B7.3 Where derive-from-one-source is NOT possible — four exceptions, burden discharged

*Everything not listed here should be treated as derivable until proven otherwise.*

**(a) A default's *value* cannot be derived; its *count* can.** Someone must choose
what the tool does when the user has expressed no preference, and no source of
truth for that exists inside the repository. What is **not** justified is that this
single decision is written as **six literals across five files**, one of which
carries two independent copies in one module. Once discovery exists, even the
surviving literal becomes a last-resort fallback rather than a policy: *"the model
used last, if the endpoint still lists it, else the first listed, else this
literal."*

**(b) Records of history must never be derived from current configuration.** Four
items: the capture tool's `MODEL`, the goldens' `_invocation.model`, the
archived-run model in `docs/llm-evaluation.md`, and README's "yields 80". **Deriving
any of these from `DEFAULT_MODEL` would destroy the one property that makes the
replay meaningful** — §B4.3 established that the harness reads the model from the
envelope *precisely so* that changing the default cannot silently repoint it. The
correct treatment is the **opposite** of derivation: make them more explicitly
historical, and add the missing guard that a *documented* default matching a *code*
default is what should be pinned by test.

**(c) Error classification is derivable for conforming servers and irreducibly
heuristic beyond them.** For an OpenAI-shaped endpoint the two substring lists are
fully replaceable by `isinstance(e, openai.RateLimitError)` /
`openai.BadRequestError` plus `e.status_code` — structured, testable, no phrase
list. **But [installed SDK source]** the status code enters `str(e)` only when the
error body parses as JSON, and `APITimeoutError`/`APIConnectionError` stringify to
fixed English sentences — so a non-conforming server's plain-text error genuinely
carries no structure and a substring fallback must survive. **The correct shape is
therefore structured first, substrings as a labelled last resort, with the residual
list documented as a heuristic** — not the current arrangement, where the heuristic
is the *only* mechanism and is presented as if it were classification. **This is
the highest-value item in the whole audit for Destination 2**, because it decides
whether a local server's context-window error triggers the remedy that exists for
it (C-9).

**(d) PyInstaller needs literal hints, and the derived guard already exists.**
Dynamically-imported and data-carrying packages cannot be found by static analysis,
so the spec literals cannot be eliminated. **But
`tests/test_frozen_build_spec.py::_third_party_imports_under_plugins` already
derives the *requirement* side by AST-walking every import under `plugins/`, and
reads the spec's literals back out of the AST to compare. That is precisely the
F-69 remedy applied prospectively, and it is already in this repository.** It should
be cited as the house pattern whenever a list must stay hand-maintained: **keep the
literal, add the derived test that fails when the literal drifts.** Its known blind
spot — a package whose payload is native libraries or data, and a transitive
dependency not imported under `plugins/` — is a real limit on the pattern, not an
argument against it (§A12.2).

**Not an exception, and worth saying explicitly: the prompt text.** The sentences
enumerating `decision`, `field` and the operator vocabulary *look* like prose and
therefore feel un-derivable. They are not. **Each is a second description of a
constant that exists twenty lines away in the enforcing code** — F-69's shape with
the model as the consumer instead of Excel, and the same silent failure mode: the
model answers in a vocabulary the parser rejects, every record becomes `uncertain`,
and the run reports success. Generating the sentence from the constant costs one
f-string and removes four hand-maintained copies. *One cost note:* any change to the
prompt text moves the golden cache keys and the `EXPECTED_PROMPT_HASH` constants,
so a **byte-identical** regeneration of the current sentence must be verified before
commit (C-26).

#### B7.4 Models versus provider shapes — the category the documentation gets wrong

The maintainer's distinction is the right one and the repository blurs it.

| Category | What it is | Legitimately hand-maintained? |
|---|---|---|
| **A list of MODELS** | which `model` strings are acceptable | **No — this is what Destination 1 removes. And the good news is that no such list exists in the code today.** There is no enumeration to delete: only defaults to consolidate and documentation to correct |
| **A list of PROVIDER SHAPES** | which *wire protocols* the code can speak. A genuinely small closed set, because each member is a distinct request builder and response reader — **it is code, not data** | **Yes, legitimately.** Today the set has exactly **one** member. Candidate second members (Ollama-native, Anthropic Messages, Gemini `generateContent`) each need their own builder, so each is a code addition and correctly enumerated |
| **A list of PRODUCTS** | Ollama, llama.cpp, vLLM, LM Studio, DeepSeek, Azure | **This is the miscategorised one.** Five hand-maintained places present four or five *products* as if each were an integration. **Four of them are one shape plus a different example base URL.** Azure is the genuine exception — a different URL shape and auth header — and it is the one the documentation asserts most confidently and supports least |

Three consequences to weigh. **The product lists are the ones that will rot, and
they are cheap to make un-rottable**: restructure the README section as one shape
statement plus a table of `{product, example OPENAI_BASE_URL, example placeholder
key}`, and let the dialog hint name the *shape* with products as parenthetical
examples from one source — then adding LM Studio costs a table row, not four prose
edits. **LM Studio is already missing from every one of those lists**, while
`ollama` 0.32.6 is on the maintainer's PATH and LM Studio is not, so the omission
happens to be harmless — but it is direct evidence that a hand-maintained product
list drifts against a moving ecosystem, **which is the same argument the maintainer
makes about models.** And **the shape list must not be allowed to grow silently
into a capability list**: "Ollama-native" is a legitimate second shape only if it
buys something the compatible shape cannot, and on the evidence of §B1.3 the honest
case is `/api/show`'s context length and `capabilities` array — one adapter, one
advisory display, **labelled as an optional enrichment the tool works without.** It
must not become the seed of a per-provider capability matrix (C-28).

---

### B8 Backlog interaction

*Register read in full at `f952e69`: 432 lines, F-01…F-85 with F-56/F-57/F-58 never
assigned = **82 rows**, matching the brief's count.*

**Three register-hygiene corrections first, because they change how the list should
be read.** (i) **The register does not mark most of waves 1–3 as closed, and a
planner reading it alone will over-scope.** Some rows carry explicit *Fixed in
`<sha>`* annotations; many do not, although `CHANGELOG.md` records fixes. Three
verified directly rather than trusted: **F-01 is fixed** (the key now hashes the
rendered prompt); **F-05 is fixed and its row is now actively false** ("the string
`sha` appears zero times in `06_el/ui.py`" — `_write_llm_stage_bundle` calls
`_refresh_sha256_map` before serialising, and this matters here because F-82's fix
lands in that same function); **F-51 is fixed** (the duplicated statement appears
once). (ii) **F-12's headline is stale; its substance is not** (§A11.2).
(iii) **All ten findings the brief names are open.**

| Finding (severity · category) | Verdict | Where the interaction lives |
|---|---|---|
| **F-12** · High · testing | **PREREQUISITE** | Both destinations rewrite the two functions it names, and one of them — `::_openai_client_for` — has **never executed in the suite**. The goldens *structurally* cannot cover the replacement: a fully-cached replay never enters `run_m1_llm_for_criterion` at all. **And one mechanical detail makes it a hard gate rather than a soft one:** the fake client's `create` is keyword-only with no `**kwargs`, so the first added request parameter fails that suite. The double must be generalised *before* the transport changes. Restate the headline first (§A11.2) |
| **F-15** · High · packaging | **PREREQUISITE for Destination 2 — conditionally, and the condition is inside the LLM work** | Making local inference the **default** means the default path's behaviour is decided by an SDK fallback in a package pinned only `>=1.40.0`, across a 1.x→2.x boundary, with **no test able to see it**. The condition: if the work makes `_openai_client_for` read the endpoint and pass `base_url=` explicitly, the dependency on undeclared SDK behaviour disappears and F-15 reverts to general hygiene for this path. **The second route is the more durable and lives inside the wave.** Separately, any local backend arriving as a Python dependency joins the same unpinned list — a second, unconditional reason |
| **F-36** · Medium · hygiene | **CHEAPER IF DONE IN THE SAME WAVE** — shared touch point: the `SCREENA_*` constant blocks and the env-var tables any new setting must extend | Every LLM-adjacent setting lives under that prefix. Both destinations must add names here — and whoever does either extends `SCREENA_`, **minting the legacy identity into a new documented surface**, or opens a third namespace (noting `METASCREENER_*` already exists on paper and not in source). Deciding F-36 afterwards means renaming twice. Second coupling: **F-82's stated fix stamps `created_by`, which `_export_next_bundle_zip` writes as `f"screen_a_{sl}_plugin"` — so doing F-82 as written propagates `screen_a_el_plugin`/`screen_a_il_plugin` into two more manifests**, precisely the string F-36 says needs a deliberate decision |
| **F-62** · Medium · hygiene | **CHEAPER IF DONE IN THE SAME WAVE** — one `evidence[c.id]` dict, one re-capture | `used=true, valid_quote=false` — the combination F-62 says cost one full investigation cycle, performed by the tool's own author — **moves from an anomaly to the common case under a paraphrasing model.** And F-62's migration recipe (accept both names on read for one release, write only the new one, regenerate by scripted field-rename with a byte-diff review) **is the mechanism the tier-2 provenance fields and F-64's reason code both need** in order to keep old bundles loadable. Doing F-62 first inside the group establishes it once |
| **F-63** · Medium · correctness | **CHEAPER IF DONE IN THE SAME WAVE — and its *category* changes** | Currently framed as "cosmetic-adjacent with bounded harm", and that framing survives one model and **does not survive several**. **[measured]** 169/170 golden spans are inconsistent with their quote — and that is a comparatively strong model at temperature 0. With several models, spans become the field a reader would naturally reach for to *compare* evidence quality, and every such comparison would be measuring noise the code never checked. F-63's own fix is strictly better under the destination: **compute the span from the validated quote, because a computed span is model-independent and therefore comparable, whereas a reported one is a second thing the model can get wrong** |
| **F-64** · Medium · correctness | **CHEAPER IF DONE IN THE SAME WAVE — and it is the most load-bearing of the three** | Not because it is the largest defect today but because the destinations make it **structural**. Every upstream salvage path — an out-of-vocabulary `decision`, an unrecognised `field`, a malformed `span`, an unparseable batch, a terminally failed batch whose `error` the evidence dict then drops — lands in the same `status: "UNCERTAIN"` with **no indication of which path was taken.** Destination 2 multiplies those paths at once. So the question a maintainer *must* answer to compare two models — "did this model refuse, paraphrase, mislabel the field, hesitate, or never get asked?" — is exactly the question the current shape cannot answer, and §B5.3 identified it as the blocker on any bake-off protocol. F-64's proposed reason vocabulary is the right instrument and is **two members short** for the destination: it needs `call_failed` and `no_response`. Adding them while the vocabulary is being designed is free; afterwards is another re-capture |
| **F-65** · High · correctness | **UNAFFECTED mechanically — with a scheduling hazard that argues for a *different* wave** | Verified: neither half of the mechanism is touched by either destination. **The hazard is attribution, not code.** F-65 is the **only other open finding that moves the demonstration funnel** (its own measurement: 80 → 13 survivors). A model change also moves it. Landing both in one period makes the two effects **inseparable in the record**, at a moment when the project already carries an unreconciled 73-vs-80 discrepancy it could not diagnose *for exactly this reason*. Related and smaller: F-65 is why `PASS_CLEAN` is structurally unreachable at IL today, so anyone benchmarking a candidate model against IL outcome distributions is comparing against a distorted baseline (§B5.3). One genuine tension to record rather than resolve: F-65's proposed net is a new hand-maintained *capability* enumeration, introduced at the moment Destination 1 argues enumerations rot — apparent rather than real (the operator vocabulary is internal, closed and small; the model space is external and churning), but a maintainer doing both will feel it |
| **F-77** · Medium · hygiene | **CHEAPER IF DONE IN THE SAME WAVE** — the same forty lines, and the re-capture the destination forces anyway | Two edited lines per stage, nine lines from the `evidence[c.id]` dict F-62/63/64 rewrite. The row's own note says it "needs its own re-capture" — **a model change makes that re-capture a necessary consequence rather than an extra cost** |
| **F-78** · Medium · correctness | **UNAFFECTED** | The defect is entirely inside `plugins/_common/runner.py`'s row assembly — the deterministic EH/IH path, which never calls a model. **And the apparent saving does not apply:** the file it moves is `ih_filtered_v3.1.0.csv`, and the EH/IH goldens are **model-independent** — that is the whole content of the project's own claim that the deterministic 98.3% reproduces exactly. A model change re-captures the EL/IL fixtures and leaves the IH one alone, so **F-78 must pay for its own re-capture whenever it lands and should not be bundled in on the assumption that it shares one** |
| **F-82** · Low · hygiene | **PREREQUISITE — and the row as written is not the prerequisite** | See below |

#### B8.1 F-82 at length

**F-82 records a *symmetry* defect (Low, hygiene, XS). The destinations create an
*absence* defect (correctness/provenance) that F-82's proposed fix does not touch.
The right move is to graduate F-82 into the larger row and keep its XS fix as a
rider — not to fix F-82 and consider the area closed.** §A9.5 verified all three
of its claims and established why: those are not fields EH/IH have and EL/IL lack;
**no stage has them, because no stage produces them.**

**Why the omission is survivable today and stops being so.** In practice there is
one model, one provider and one temperature, so "which model produced this bundle?"
is answerable *by reading the source at the commit that produced it*. A weak
answer, but an answer. **Destination 1 removes it deliberately** (no enumeration,
any non-empty string accepted, entered per stage, persisted nowhere);
**Destination 2 removes it again on a second axis.** At that point the artefact is
the only possible witness and it is silent — and `.zenodo.json`'s audit claim
becomes false in the specific way a methods reviewer would probe. **The brief's
argument holds: a bundle that cannot be attributed to a model is not untidy, it is
unusable as evidence.** Two concrete failures follow that cannot occur today: the
cross-provider cache collision of §B4.2, and **intra-bundle heterogeneity** — the
cache travels *inside* the bundle and is never evicted, so one `EL_FULL.csv` can
carry rows decided under model A and rows decided under model B, **at which point a
run-level provenance block would be confidently wrong about most of the rows, which
is worse than silence.**

**The minimum provenance set, in two tiers** — because one tier cannot be honest on
its own. **Tier 1** = an `llm_invocation` block inside the `history[]` entry
`_write_llm_stage_bundle` already appends: additive, **covered by no golden**, so it
costs no re-capture. **Tier 2** = per-decision, inside the cache *value* and
surfaced in the evidence JSON: the golden-touching change that must ride with
F-62/63/64.

| Field | Verdict | Justification |
|---|---|---|
| `model` | **Include, tiers 1 and 2. Mandatory** | the one field the destinations make unrecoverable; already a parameter at the write site; already in the key. Tier 2 as well, because of intra-bundle heterogeneity |
| endpoint | **Include, tier 1, in reduced form; a discriminator in tier 2** | a model name is **not an identifier**: the same tag served by two runtimes at two quantisations is two engines under one string, and llama.cpp ignores the field entirely. It is also the field whose absence from the key permits the collision — **so whatever form is chosen must go into the key as well as the manifest, or the manifest asserts one endpoint while the cache silently mixes two** |
| `temperature` | **Include, tier 1** | free at the write site, already in the key, user-adjustable, and the published reproducibility story is stated *as* "T=0.0" in the README plugin table. A bundle that does not record it cannot support the claim made about it |
| `prompt_version` | **Include, tiers 1 and 2** | the FAQ already instructs the reader to pin it "in your bundle manifest" — unperformable today. Free at the write site, and it is the deliberate cache-invalidation lever, so a reader needs it to know whether a replay means anything |
| timestamp | **Exclude — do not add a second one; fix the one that exists** | `history[].ran_at` is already UTC. A second timestamp inside the block **re-creates F-53 inside one dict.** What should ride along is F-53's actual fix, because a provenance block sitting next to a mislabelled clock invites arithmetic across two unlabelled time bases |
| `trunc_chars`, `batch_size` | **Include, tier 1** | both change what the model saw, and one has **no other trace anywhere**: `batch_size` is absent from the key entirely. `trunc_chars` is the quote-validation window, and the adaptive step-down means the *effective* window can differ record to record with no record of it. The capture tool's `_invocation` already records exactly these two plus `model` — **precedent inside the repository** |
| `openai` SDK version | **Include only while the endpoint is resolved by the SDK's own env fallback** | it is provenance for a behaviour the repository does not own. If `base_url` is passed explicitly, this field's justification disappears with the dependency. Note it **cannot be added retroactively** for the existing goldens (C-41) |
| API key, org id, project id | **Exclude, unconditionally** | secret or identifying, and contributes nothing to attributing a decision. Note the SDK absorbs org/project from the environment and emits them as headers; a provenance block must not be where those surface |
| cache hit/miss counts | **Include if cheap — but label them run statistics, not provenance** | a real gap (§A8.5), but it answers "was this run live?" not "which model said this?", and merging the two blurs both |

**The privacy angle on `base_url`.** Facts first: nothing in the repository reads the
variable, so there is **no existing value and no existing precedent** for how to
record it — though there *is* one precedent for leaking a local string into a shared
manifest, `derived_from.zip_name`, which is F-53's second clause and is already
flagged inside F-82's own row.

| Option | Assessment |
|---|---|
| **Verbatim** | Maximally useful and genuinely risky. `http://localhost:11434/v1` is harmless; `https://llm.internal.<employer>:8443/v1` names an internal host in a file the project tells users to deposit. A URL can also carry a path segment that is effectively a credential — a gateway route, a tenant id, a deployment alias. Recording it verbatim by default puts a class of value the project has never inspected into a published artefact |
| **Hashed** | Preserves the property that matters for the cache defect — two runs against different endpoints become distinguishable, and "same endpoint" is checkable across bundles — and leaks nothing. But it answers the *equality* question, not the *attribution* question, and attribution is the one the destinations create: a reviewer asking "was this local or paid?" gets 64 hex characters and no answer |
| **Coarse label** | Answers the attribution question in the form a reviewer needs, and is the only option that does. A defensible three-way split: `openai-hosted`, `local` (host resolves to loopback), `third-party`. It leaks only that a non-public endpoint was used, which the bundle already implies by not being one of the other two |

**Two costs to price before choosing.** The classifier has to be right — a hostname
that merely *contains* `localhost` is not loopback, and erring permissively
publishes the very thing the reduction was for. And, more important: **an unsalted
hash of a short internal hostname is dictionary-guessable, so it is a discriminator
and not a secret; a per-bundle salt makes it a secret and destroys the cross-bundle
comparability that was the reason to record it. Discriminator or secret — the design
cannot have both**, and the choice should be made deliberately rather than emerging
from whichever `sha256` call gets written first (§B9 Q3).

One GUI consequence to record alongside: because there is no endpoint widget,
whatever is recorded is read from `os.environ` and describes **what the process
had**, not what the user believes they configured. That is the honest thing to
record, and worth saying so in the field's documentation.

#### B8.2 Twelve further interacting findings the brief did not name

**The brief's list is incomplete.** Twelve further rows interact specifically; I
found no thirteenth worth reporting.

| Finding | Verdict | Interaction |
|---|---|---|
| **F-21** (Medium) "the gate validates that a quote *exists* but not that it is *substantive*. A one-character quote passes." | **PREREQUISITE** | The row already anticipates the destination ("Relevant given `README.md` explicitly invites untested open-weight models") and the destination **promotes** it: `{"decision":"meet","confidence":0.95,"quote":"the"}` clears the gate and **excludes** a record — and short generic quotes are what a weaker model emits when it cannot locate evidence. XS, and far cheaper before there are two models whose flag rates must be compared |
| **F-22** (Medium) "the quote check is not Unicode-normalised or case-folded" | **PREREQUISITE** | Same one-line site. §A7.3 enumerated the failing classes precisely. A model that re-cases or re-punctuates fails the gate for reasons unrelated to eligibility, which inflates the review queue **differentially by model** and corrupts any comparison before it starts. Note NFKC is necessary and not sufficient |
| **F-25** (Medium) "no `max_tokens` and no timeout" | **PREREQUISITE for Destination 2** | Local servers carry far smaller default output caps and context windows while `batch_size` is 50 — sized for the hosted model. `finish_reason` is never read, so a response truncated mid-JSON parses to `[]` and back-fills the batch with no detection. And the effective limit is 600 s × up to 3 attempts, **worst on exactly the CPU-bound workload the destination makes default** |
| **F-14** (High) "3,251 lines of the `plugins/` tree are twinned copies" | **HARDER — the destination is doubled by it** | Every edit either destination requires — model/endpoint plumbing, the evidence dict, the cache write-back, the provenance stamp, the separator — must be made twice and verified twice. **The drift is not hypothetical:** §A1.1 found the standalone shells omitting `temperature` and lacking the key gate, on this exact axis. F-14's first two steps are the cheapest way to halve the wave — **and they are golden-protected *today*, which stops being true once the goldens are mid-re-capture** |
| **F-34** (High) "a stage with zero enabled criteria reports a successful clean pass" | **CHEAPER IF DONE IN THE SAME WAVE** | F-34 already built the vocabulary and the export-gate affordance for "this stage did not actually screen". **The destination creates a second route to the identical outcome** — a wrong model tag, a whitespace-only model, an unreachable endpoint — which today yields all-`PASS_FLAGGED`, `"EL done."` and enabled exports. Extending F-34's own machinery is small while that code is open and awkward afterwards |
| **F-66** (Medium) "optional-dependency degradation is silent and unreportable" | **CHEAPER IF DONE IN THE SAME WAVE, and it is the precedent the destination needs** | The house habit is a `*_OK` flag nobody surfaces, and Destination 2 will produce more of them. **F-66's fix is the same widget the destination independently needs:** a startup line naming what is unavailable, and a visible per-plugin marker — compare `_refresh_key_label`, structurally incapable of rendering anything but ✓ |
| **F-33** (Medium) "corrupt cache lines are skipped without any report" | **CHEAPER IF DONE IN THE SAME WAVE** | Once cache values carry provenance, old caches must keep loading and "entry from before the field existed" must be distinguishable from "unreadable line". **The counter F-33 asks for is the same log line that would report "N entries produced by a different model or endpoint" — one place, one loop** |
| **F-28** (Medium) "the goldens are captured at non-default settings" | **CHEAPER IF DONE IN THE SAME WAVE** | Every candidate model needs its own capture run. **Capturing at the plugin defaults costs nothing extra at that moment**, and a multi-model world wants the constants parameterised — which is F-28's edit. Correct its docstring coupling claim while there (§A11.3) |
| **F-53** (Low) "manifest timestamps use local time and disagree with each other" | **PREREQUISITE for F-82's fix** | One line, and it is the precondition for a provenance block that does not contradict its neighbour. `derived_from.zip_name` is also the existing precedent for the leak the `base_url` discussion is about |
| **F-27** (Medium) "the manifest carries two divergent stage maps" | **CHEAPER IF DONE IN THE SAME WAVE** | Same function, same hundred lines. Anyone opening `_write_llm_stage_bundle` to add `llm_invocation` is already there |
| **F-79** (Medium) deliverable-format cluster | **CHEAPER IF DONE IN THE SAME WAVE — one shared tool** | Its plan *is* the interaction: "proving equivalence by parsing old and new goldens with the `csv` module and asserting field-for-field equality rather than byte equality". **A model change cannot preserve golden bytes, so it needs exactly that harness.** Whichever lands second gets it free — and F-79 carries an unresolved human observation, so it is the one that can wait, which argues for the model work building the harness |
| **F-09 / F-40** (packaging, both closed) | **PREREQUISITE — conditionally, only if a backend with a native payload is chosen** | Their fix is real but **does not cover the new case**: §A12.2 established that the whole `httpx`/`pydantic_core`/`jiter` layer is present only as a transitive analysis product — dependency-by-coincidence one layer below the layer F-09 criticised — and that the spec test's hook route is a condition on the *spec*, independent of the package examined. **A backend shipping native libraries needs work whose omission no current test can detect** |

Also relevant but not distinct interactions: **F-01 is closed and is the direct
precedent** for the endpoint-omission problem — its docstring's argument is true and
does not cover *who answers*. **F-37 is closed** and folds into F-36's touch point.
**Findings checked and judged genuinely unaffected:** F-02–F-08, F-10, F-11, F-13,
F-16–F-20, F-23, F-24, F-26, F-29–F-32, F-35, F-38, F-39, F-41–F-52, F-54, F-55,
F-59–F-61, F-67–F-76, F-80, F-81, F-83–F-85.

#### B8.3 Dependency ordering

*Not a recommendation to proceed. An ordering with reasons, on the assumption the
work is done.*

**Before — because the LLM work cannot be done safely or cheaply without them.**
**1.** F-12 narrowed to the error and salvage paths: nothing else here can be
changed with a net, the goldens structurally cannot cover it, and the test double
must be generalised anyway. **2.** F-21, F-22 and F-25 — the three guards on the
gate and the call. Each is the failure mode a weaker model exercises first, each is
XS–S, and each is cheaper to fix **while there is still exactly one model to
regression-test against**; fixing them afterwards means every measurement taken in
between is uninterpretable. **3.** F-53 — one line, and the precondition for a
coherent provenance block. **4.** F-14's first two steps — optional, but they halve
every edit in the "with" group and are golden-protected *today* in a way they will
not be later.

**With — one commit family, one `evidence[c.id]` dict, one EL/IL re-capture.**
**5.** F-64 (defining the shape, and gaining `call_failed` and `no_response` while
the vocabulary is open), then F-63 (a computed, model-independent span), then F-62
(the rename, whose dual-read recipe is the migration mechanism for all of it), then
F-82 tier 2, then F-77. **6.** F-82 tier 1 — the `llm_invocation` block plus the
endpoint discriminator in the key, landing with **the same endpoint-reduction
decision** the key uses, or the manifest and the cache disagree. **7.** F-28 —
capture at the plugin defaults and parameterise the tool constant; the capture run
is happening regardless, so doing it right is free at that moment. **8.** F-33,
F-27, F-34's vocabulary extension, F-66's surfacing widget — all inside functions
the work above already has open. **9.** F-15, *if* the work does not make
`_openai_client_for` pass `base_url` explicitly. **10.** F-36, as a **decision
rather than a rename**, because new env-var names and two new `created_by` strings
are about to be minted and deferring means the decision gets made by default.

**After. 11.** F-79 — it wants the same equivalence harness and carries an
unresolved human observation, so it is the item that can absorb the wait and
inherit the tool. **12.** F-65 — **deliberately in a different wave, with a
re-capture between**, because it is the only other open finding that moves the
funnel and concurrent effects would be inseparable in the record. **13.** F-09's
class, conditionally, only after a backend is chosen. **14.** Everything else,
neither blocked by this work nor blocking it — and **F-78 in particular should not
be bundled in** on the assumption that it shares the re-capture.

---

### B9 Candidate findings

**One deduplicated namespace.** The parallel analysis behind this document issued
roughly 167 `C-n` labels across twelve namespaces that all restarted at C-1;
consolidating them was part of the work. Severity is my assessment. **No `F-nn` was
assigned; `03_findings.md` was not touched.** The duplication sweep against the
existing 82 rows is a later wave, and several of these are plainly the LLM-facing
face of an existing row — noted inline where so, and they should be **merged, not
added**.

#### Critical

| ID | Category | Finding | Fix |
|---|---|---|---|
| **C-1** | correctness / data loss | **Cross-batch answer substitution can export a fabricated exclusion.** `plugins/_common/llm_client.py::run_m1_llm_for_criterion` builds `idx_map` from the **whole `items` list before batching**, so the acceptance guard `if not a_id or a_id not in idx_map: continue` admits an `a_id` belonging to any other batch; the quote is then validated against **that record's real text**, so `valid_quote` returns True and the gate passes. **Reproduced independently: `OUT = 3/6` with `used: true, quote_valid: true`.** Three aggravations. It **fires at `batch_size = 1`** — `idx_map` is built independently of batching, so any advice that a small batch mitigates it is wrong. There are **two routes, and the backward one is unconditional**: the parse-loop write `out[(a_id, cid)] = {...}` is **unguarded**, so a later batch naming an earlier batch's id **destroys an already-correct verdict** with no omission required (measured, `OUT = 3/6`). And it is **persistent**: the write-back caches the fabricated verdict under the substituted record's own legitimate key, so a later run replays the exclusion with **0 API calls**, logged as a normal `cache_hits=N`. Precise headline: the verdict that excluded the record was produced by a call whose prompt **did not contain that record**. Aggravated by every destination — `a_id` drift on a 50-item batch is a characteristic small-model failure | Scope the acceptance guard to `cur_batch`, and guard the parse-loop write the way the back-fill is guarded. Then add the test the property has never had |

#### High

| ID | Category | Finding | Fix |
|---|---|---|---|
| **C-2** | correctness / integrity | **API failures, refusals and empty responses are written into the persistent cache as verdicts and served forever.** The write-back loop merges **every** entry of `res` with no filter on `ev.get("used")` or `ev.get("error")`, so a transient 500, a timeout, an auth blip or a refusal is negatively cached under a key that matches on every later run; `ev.setdefault("used", True)` does not repair it. The `error` string — including SDK exception text — is serialised into the exported bundle. **A network blip becomes a permanent verdict.** Companion route: duplicate `local_id` collapses two rows onto one verdict and can exclude a record whose own text lacks the quote (measured, `OUT = 2/3`), guarded only *upstream* by `_load_bundle`'s dedup, which any direct `ParseReport` caller bypasses — **the safety property there is carried by the loader, not the gate** | Refuse to cache any `ev` carrying `error`, or any with `used=False`. Move the duplicate-id guard into the engine |
| **C-3** | provenance / scientific integrity | **No artefact records which model, provider, temperature or prompt version produced a decision.** Across `plugins/` + `metascreener/` the dict key `"model"` occurs **exactly once**, inside `_cache_key`'s hashed-and-discarded JSON. Not the manifest, not the seven-key history entry, not the cache value, not the evidence JSON, not any report column. **A bundle cannot be attributed to a model after the fact.** Falsifies four documentation claims and makes the FAQ's "pin to a prompt version explicitly in your bundle manifest" unperformable. **Graduates F-82 rather than duplicating it** (§B8.1): F-82 is a symmetry defect; this is an absence, and F-82's proposed fix does not touch it | Two tiers per §B8.1. Tier 1 is additive and **covered by no golden**, so it costs no re-capture |
| **C-4** | correctness / reproducibility | **The cache key omits the endpoint, so two providers share one namespace.** `_cache_key` hashes `{prompt_version, model, temperature, prompt}`; `base_url` appears nowhere, and no repository code reads `OPENAI_BASE_URL`. The README's own llama.cpp instructions **actively recommend the collision-triggering configuration**. Scenario in §B4.2: 100% cache hits and the previous provider's answers, logged as healthy. **F-01's exact failure shape displaced onto the provider axis** — the docstring's argument covers what is asked, not *who answers*. Structural note: the resolved endpoint is **not obtainable at the keying site**. Medium today (a `.env` edit); **High under either destination** (two clicks) | Hash the effective endpoint — which requires the code to learn `OPENAI_BASE_URL`, which it should do anyway for C-6. Decide the reduced form **once** (§B9 Q1/Q3) |
| **C-5** | correctness | **The `decision` whitelist is not case-folded, while `field` two statements later is.** A model answering `"Meet"`, `"MEET"`, `"Not_Meet"` or `"not meet"` has **every decision silently rewritten to `"uncertain"`**; the gate then refuses all of them, so every record is flagged with `used: True`, a *valid* quote and a *high* confidence in the evidence JSON — an internally contradictory audit record, with no log line and no count anomaly. **The run looks like one in which the model was unsure about everything.** Acute for local models, where format discipline is weakest and there is no `response_format` to lean on | One `.lower()`; and count and log whitelist rejections |
| **C-6** | GUI-first | **`base_url` has no GUI surface whatsoever, so the documented local-provider workflow is unreachable through the GUI.** The only two `OPENAI_BASE_URL` mentions in GUI code are static advisory strings *telling the user to set an environment variable*; no widget anywhere is bound to an endpoint, host or port. The only routes are hand-editing `.env` or the OS environment. **Wave 1 removed the second barrier (the placeholder key) and left the first standing.** Discovery has nothing to discover against until this is fixed, so it is a **prerequisite of Destination 1, not a companion to it** | One Entry plus a read at `_openai_client_for`. Persistence is nearly free: `_load_env_file` is already generic and `_save_env_key` already preserves unrelated lines |
| **C-7** | architecture / test coverage | **The whole local-provider capability rests on an undeclared, unpinned, untested third-party default.** No repository line reads `OPENAI_BASE_URL`; it works only because **[installed SDK source]** `OpenAI.__init__` falls back to it. `openai` is pinned only `>=1.40.0`, and **[not established]** whether the declared floor even has the fallback. **No test anywhere asserts it.** An SDK major that dropped it — or a well-meant refactor adding an explicit `base_url="https://api.openai.com/v1"` — would silently route a "local" run to the paid API **with all 422 tests green** | Read it explicitly and pass `base_url=`; log it once per run; add it to `.env.example`; one test asserting `str(client.base_url)` |
| **C-8** | correctness | **An unvalidated model field, an unreachable endpoint, or an offline machine all turn a misconfiguration into a completed-looking run.** `(self.var_model.get() or DEFAULT_MODEL).strip()` puts `.strip()` **outside** the `or`, so whitespace survives the fallback and strips to `""`; and a misspelled model or a down server produces an error matching neither retry predicate. All paths end with every criterion `UNCERTAIN`, every record flagged, status label **`"EL done."`**, both exports enabled, and `pipeline.history` recording `cancelled: False, not_screened: False`. The only trace is a line in an **unfocused** sub-tab. **Same family as F-34 on three new triggers — and under local-by-default this becomes the *dominant* failure mode** | Refuse an empty model before starting; surface a terminal-failure count; extend F-34's own `_export_confirm_reason` machinery to cover it; add the readiness probe of §B3.1 |
| **C-9** | correctness | **Error classification sniffs substrings that only OpenAI's own JSON error bodies reliably contain, and both remedies are gated on it.** `is_big` requires `context` ∧ `length` co-occurring, so a server saying "prompt exceeds the context window" or "n_ctx exceeded" matches neither term-pair — **and the batch-halving and truncation step-down that exist precisely for a small context window never fire.** `APITimeoutError`/`APIConnectionError` stringify to fixed sentences matching neither, so **every timeout and every connection failure is terminal on first sight** at the application layer. False positives are live: `"rate"` matches inside `generate`, `moderate`, `separate`. **Small context windows are exactly the local case.** *Scope note:* the 429 half is **more robust than it first appears** — an empty body still yields `"Error code: 429"` — so the finding is about oversize and transport, not rate limiting | `isinstance(e, openai.RateLimitError)`/`BadRequestError` plus `e.status_code`, keeping the substring sniff as a **labelled** last resort. Also: halving is the wrong remedy for a 429 (it increases request count) and no `Retry-After` is read at the application layer |
| **C-10** | scientific integrity | **The published quote-validity and observed-agreement rates were earned on a task the documentation never characterises.** All three `operator=llm` criteria have `target=keywords`, and **[measured] 170/170 EL and 84/84 IL quotes carry `field: "keywords"`** — 140/170 containing `"; "`, median length 202 chars, over semicolon-delimited controlled-vocabulary term lists. **So "produces a verbatim substring quotation" has been measured only as "echoes back a term list", never as prose extraction from an abstract.** The project's most transferable-*looking* claim on its narrowest evidential base — and the one a small local model is most likely to break | Say so in `docs/llm-evaluation.md`, in the same paragraph as the rate |
| **C-11** | scientific integrity | **The validation study is attributable to a model only through the `_invocation.model` field of two test fixtures, and `§Limitations` bounds everything except the model.** The chain is verified and 344/344 field-for-field; §Results names no model, `docs/data/*` has no model column, the FAQ quotes the kappas without one, and **the only model named in the document belongs to a different, degenerate run** — inviting a reader to attribute the kappas to it. There is a "**Single corpus**" limitation and **no "Single model"** one. Compounding: the degenerate-output note does not anticipate **JSON-shape failure** (whose zero-variance signature its own diagnostic advice would misdiagnose as a lazy model) or **`a_id` drift**; **[measured]** the committed goldens are themselves near the low-variance regime it warns about (169/170 one decision, 62% of pooled confidences at exactly 0.900, 10 distinct values in the whole study); and its variance metric — distinct spans — is computed over a **fabricated** field | A "Model under evaluation" block in §head; a "Single model" bullet; extend the note with the four new modes; switch the variance metric to distinct quotes |
| **C-12** | testing | **Nothing pins the production default model or the published kappas, so a model swap plus a re-capture rewrites every figure with 16 CI cells green.** Neither `DEFAULT_MODEL` is referenced by any test — **[measured]** the full suite passes unchanged under `SCREENA_EL_MODEL=SCREENA_IL_MODEL=gemma3:12b` — and `tests/test_eval_ingest.py` runs the ingestor against **synthetically modified** CSVs into `tmp_path`, asserting only structure plus `agree_count/len > 0.7`, **never reading `eval_summary_v1.txt`**. Contrast `PROMPT_VERSION`, pinned twice per stage precisely because it invalidates the cache. **The failure mode is silence, not a red test** | Pin the documented default against the code default; assert the published summary against the committed data |
| **C-13** | architecture / integrity | **One artefact pair serves as both the regression fixture and the scientific dataset, and the two roles have opposite maintenance rules.** `tests/golden/{el,il}_filtered_v3.1.0.csv` are the byte-identity control **and** the sole data source of the published study. A fixture is meant to be re-captured when the guarded behaviour legitimately changes; a cited dataset must never change. The capture tool overwrites six files in one run with **no versioning of the previous set and no cross-check against `docs/data/`** | Freeze a copy of the two filtered CSVs under `docs/data/` as the study's immutable input, and let the goldens move independently |
| **C-14** | reproducibility | **`.gitattributes` protects only `tests/golden/**`, so a golden re-capture is checkout-dependent.** **[measured]** `samples/20260122_1654_aggregate.csv` and `docs/data/eval_results_v1.csv` are `text: auto`; the corpus is stored with 2096 CRLF and 0 bare LF, and **15 of its fields contain an embedded newline** — bytes that reach the rendered prompt, which is hashed into every cache key. **So two maintainers re-capturing from the same commit with different `core.autocrlf` obtain different keys**, and `docs/llm-evaluation.md`'s byte-for-byte regeneration claim is about a working tree, not a commit. Sits directly on the path a model swap prescribes | Add `samples/** binary` and `docs/data/** binary`; record `core.autocrlf` in the capture tool's `_invocation` |
| **C-15** | scientific validity | **The prompt tells the model the confidence threshold it must clear, and the observed confidences cluster immediately above it.** `c_pack["threshold"]` is serialised into the user message; the gate then applies `confidence >= float(c.threshold)`. **[measured]** 141/170 EL confidences are exactly 0.9 against 0.60; every value above the bar is in {0.7…0.95} and every value below in {0.1…0.4}, **with a gap straddling 0.60**. Telling a model the bar and then treating its self-reported number as an independent gate is a circularity — and no section of the documentation names it | Remove `threshold` from `c_pack` and re-capture, **or** state in `docs/llm-evaluation.md` that the confidence gate is not independent of the prompt |
| **C-16** | testing | **The LLM error and salvage paths have no coverage, and the transport layer has none at all.** `::_openai_client_for`'s body **never executes** across 422 tests even with a key set (measured: 0 constructions); `::_has_openai_key`'s body never executes; every branch of the retry loop that fires when a model or endpoint misbehaves is uncovered, as is every `_parse_llm_json_array` fallback and every response-normalisation coercion. **This is F-12's substance, still true — its "0% / never executed" headline is now stale and should be narrowed rather than closed**, and its evidence cell's *mechanism* is also wrong (§A11.3). The gate itself has no named assertion; the threshold comparison is untested and **[measured]** no cached confidence equals 0.60, so flipping `>=` to `>` would break no test | Narrow F-12; generalise the test double (its keyword-only `create` fails on the first added parameter); add the fake-server tier of §B3.4 |

#### Medium

| ID | Category | Finding | Fix |
|---|---|---|---|
| **C-17** | correctness | **The cache key hashes a synthetic one-item prompt, so `batch_size` is invisible to it.** Entries produced at `batch_size=50` are served indistinguishably to a run at `batch_size=1` and vice versa, and any cross-item contamination within a batch is cached as a per-item verdict — so **a reviewer cannot use `batch_size` to obtain an independent second opinion.** The design is documented in a comment; the *consequence* is not, and it is the one place the key's stated invariant does not hold | Document the consequence beside the existing comment; consider a batch-composition discriminator if the invariant is to be literal |
| **C-18** | correctness | **A mid-retry truncation step-down caches under the wrong key, and the cache grows monotonically with no way to tell live entries from dead.** `cur_trunc` is reduced (1500→1125→843→632→600) but never returned, so an answer formed on a 600-char window is stored under the hash of the 1500-char prompt — **a residual leak of exactly the class F-01 closed**, surviving *because* the key is rendered from a reconstruction rather than from the bytes sent. Separately: nothing prunes entries whose key can no longer be produced, and every superseded entry is copied forward into every distributed artefact forever | Return the effective truncation and key on it (or record it); prune on `prompt_version` change and log what was dropped |
| **C-19** | testing | **The shipped on-disk cache format has no round-trip test — the goldens bypass it entirely.** The capture tool writes with `json.dumps` and the tests read with `json.loads`, so `::_dump_cache_to_jsonl` and `::_load_cache_from_jsonl` — **the only code that ever touches the format a user's bundle actually carries** — never execute. The byte-identity suite would stay green through a change that breaks the real cache file. Compounded by F-33's silent `except Exception: continue` | One round-trip test over the production pair |
| **C-20** | correctness | **Running a stage with "Use cache" unticked *deletes* the bundle's existing cache.** `_write_llm_stage_bundle` adds `cache_rel` to `skip_exact` unconditionally, so when `cache_text is None` the incoming member is excluded from the copy loop and never re-written. **One export with the box unticked silently discards an accumulated cache that cost real money**, with no warning and no manifest note; the `sha256` map keeps its entry for the now-absent member, and `_verify_sha256_map` cannot detect it because it iterates only present members | Only skip `cache_rel` when it is actually being written |
| **C-21** | robustness | **No timeout is set anywhere on the EL/IL path, so one batch can consume up to 30 minutes.** **[installed SDK source]** `DEFAULT_TIMEOUT = 600 s` **and** `DEFAULT_MAX_RETRIES = 2`, and the repository configures neither — so one `_call_once` can spend 3 × 600 s while the worker thread holds and the UI shows a stale progress event. Also: **every logged "batch failed" line under-reports the request count threefold**, which matters for anyone reasoning about cost or a rate limit. Offered as a **sharpening of F-25's magnitude**, not a new defect | An explicit per-request `timeout=` and a `max_retries=` chosen in awareness of the application ladder |
| **C-22** | correctness | **The `error` string never reaches the audit trail, and `span` is never validated against the quote.** `evidence[c.id]` is built from a fixed nine-key list that omits `error`, so a record whose criterion was never evaluated because the call failed is **visually identical** in the export to one the model genuinely could not judge. And `span` is accepted as any two ints with no check that it locates the quote: **[measured]** 169/170 EL and 77/84 IL golden entries are inconsistent — and the value is exported into the evidence JSON and the cache. **F-63's category changes under multiple models** (§B8): spans become the field a reader would use to *compare* evidence quality, and every such comparison would measure noise | Add `error` (or a `status: "ERROR"`); compute the span from `fld_txt.find(quote)` after validation, or drop the field |
| **C-23** | correctness | **The evidence gate normalises whitespace only.** Case, NFC/NFD accents, curly vs straight quotes, en/em dash vs hyphen, `ﬁ`/`ﬂ` ligatures, U+200B/200C/200D, U+FEFF and U+00AD all fail — each verified by measurement. It fails **closed**, so the harm is not a false decision but a review queue that inflates for reasons unrelated to eligibility, **systematically worse for weaker and local models and for non-English and PDF-derived corpora.** *This is a refinement to F-22, not a duplicate:* NFKC is **necessary and not sufficient** — it does not remove the zero-width/soft-hyphen set and does not address case; and `_normalize_space` already handles the NBSP class correctly, which F-22 implies it does not. Note `normalize_dashes` exists in plugin 01 — **the capability is in the repository and simply absent from the gate** | NFKC **+** strip the zero-width/soft-hyphen set **+** `casefold()` **+** a dash/quote fold |
| **C-24** | correctness / packaging | **Capability assumptions are asserted statically per plugin, checked nowhere, and the frozen-build test cannot see the class of breakage a local backend would introduce.** Plugin 01 unconditionally sends vision content parts **and** forced `tool_choice` against a free-text model string defaulting to `gpt-4o` via a *different* env var — the only site where a capability distinction is load-bearing, and the README's "no code change" is not scoped away from it. Separately, `tests/test_frozen_build_spec.py::_routes_for`'s hook route is a condition on the **spec**, independent of the package examined, so any new import under `plugins/` is "reachable" the instant it is written — **and a dependency whose payload is DLLs or data files passes while its binaries are absent.** F-66's failure shape one layer down | Scope the README claim to EL/IL/03 explicitly, or give plugin 01 its own endpoint/model setting; add a spec test that can see a missing DLL rather than a missing module |
| **C-25** | architecture | **The repository's most valuable portability property is undocumented and therefore unprotected.** The EL/IL request is the minimum viable chat completion, with zero `Literal`/`Enum` types anywhere and exactly one condition on the model string — and **nothing in any docstring, comment or test says the minimality is deliberate.** The parameter set is pinned only *accidentally*, by a test double that happens to be keyword-only. The route choice (`chat.completions` over `/responses`) is likewise correct and unrecorded, so nothing protects it from a "modernise" commit | One paragraph in `run_m1_llm_for_criterion`'s docstring plus one explicit test converts an accident into an invariant |
| **C-26** | hygiene / correctness | **The screening prompt hand-restates two vocabularies the parser enforces twenty lines away, in four places, with no test comparing them.** Both `prompt.py` files spell out the `decision` and `field` value sets in prose while `llm_client.py` enforces them as inline literals and both `screen.py` files restate a 2-member subset at four more sites each. **F-69's exact shape with the model as the consumer**, and the same silent failure: the model answers in a vocabulary the parser rejects, every record becomes `uncertain`, and the run reports success | One constant each; generate the prompt sentence from it. **Cost note:** any prompt-text change moves the golden keys and the `EXPECTED_PROMPT_HASH` constants, so a byte-identical regeneration must be verified before commit |
| **C-27** | correctness | **The criterion-operator vocabulary exists in four hand-maintained copies, one of them a prompt sent to a model; and there is no constant at all for the per-criterion status vocabulary.** `parser.py::OPERATORS` is duplicated as an `if/elif` cascade twice in `evaluator.py` and again in prose in `llm_refine.py`'s system prompt — in sync 9 for 9, with nothing enforcing it. **[measured]** no `STATUSES` symbol exists anywhere, and that absence is *why* the eval tools' status maps could omit `MISSING` undetected (silently rating it "unsure") and why F-64's two incompatible shapes went unnoticed. Contrast `ui.py:748`, which correctly derives its Combobox from `OPERATORS` — **the good pattern is in the same subsystem** | One constant per vocabulary; a dispatch dict keyed by `OPERATORS`, which also makes F-65's "declared but not executable at this stage" a checkable property |
| **C-28** | documentation / categorisation | **Five hand-maintained places enumerate *products* where the code has one *shape*, and LM Studio is missing from all five.** Four of the five products are one wire protocol with different example base URLs; Azure is genuinely a different shape and is the one asserted most confidently with **no supporting code**. The four-section README structure implies four integrations where there is one code path | One shape statement plus a table of `{product, example base URL, example placeholder}`, so adding a product costs a table row |
| **C-29** | correctness / GUI | **The GUI cannot distinguish eleven endpoint/model states and reports the same thing for all of them.** `"EL done."` is emitted for a whitespace-only model, an unreachable endpoint, a rejected key, an unavailable model name and a genuinely all-uncertain run alike; and `_refresh_key_label` **can only ever render `✓`** in the shipped hub, so the one provider-adjacent widget carries zero bits. Discovery is worthless without a state model behind it. Adjacent: plugin 01 calls `messagebox.showerror` **from a worker thread** while every success-path update in the same function is correctly marshalled through `self.after` — Tk is not thread-safe, and this can hang the whole hub, not just that tab | Display the effective endpoint; implement the state table of §B1.4; marshal plugin 01's error dialog |
| **C-30** | testing / hygiene | **CI installs `pytest-cov` and never uses it; the suite's network-cleanliness is incidental rather than structural; and one non-LLM plugin is dressed as an LLM plugin.** 16 cells run `pytest -q` with no `--cov` and no floor, so a subsystem falling to 0% is invisible — both F-11 and F-12 were found by hand. `conftest.py` has **no network guard**: **[measured]** flipping one `operator="contains"` literal to `"llm"` reaches client construction, i.e. on any developer machine with a key set it would make a live billable call. And plugin 02 imports `OpenAI`, sets `OPENAI_OK`, documents it as a feature flag and re-exports both — **guarding no call site at all** | One cell with `--cov-fail-under`; an autouse fixture clearing the env vars and stubbing `_openai_client_for`; delete the dead import and flag |
| **C-31** | architecture | **The standalone shells diverge from the tab UI on the LLM path and are not free to delete.** Neither passes `temperature=` (so they always run at 0.0 while the tab honours the spinbox) and neither applies a `_has_openai_key()` run gate. **[not established]** that they are unreachable from the shipped application — only that no test exercises them. And they are **not** a simple deletion: `plugins/06_el/plugin.py`'s own comment states the re-export order "matters because of circular imports between plugin.py / ui.py / standalone.py / screen.py", and `01_architecture.md` calls that chain "a deliberately fragile order dictated by a circular dependency" | Break the cycle first (F-14's `_common/llm_screen.py` step), *then* wire the shells up or delete them |
| **C-32** | GUI-first | **No LLM setting persists between launches except the API key, and the model must be set in up to four unreconciled widgets.** No settings file, registry use or config parser exists anywhere; `_save_env_key` writes one variable. **A local-model user retypes the model name into two fields every launch, forever** — and the only persistence lever is itself a `.env` edit, so the GUI-first constraint is violated to escape a GUI-first defect. The harmoniser cannot be pinned even that way. Three different prefill sources plus one hardcoded literal mean **accidental mixed-model pipelines are the default, not an edge case**, and nothing detects or records the disagreement | One app-level setting with per-stage override, persisted where the frozen build can write (§B3.5) |
| **C-33** | testing / consistency | **Two divergent key predicates, and the IL golden is weaker than the EL one.** `_has_openai_key` strips; `_llm_available` uses bare `os.getenv` truthiness — so with a whitespace-only OS-level key **the harmoniser offers to spend money while EL and IL refuse.** Separately, **[measured]** the IL byte-identity golden exercises **one** LLM criterion, not two: `IC-5` is `operator="contains"` and is marked `UNCERTAIN` by fiat, pushing 80 of 84 records to `REVIEW`. Nothing is wrong with the code; the fixture is simply weaker than EL's and the docstring does not say so. And the capture tool's docstring misstates its coupling to the tests, with nothing asserting `PROMPT_HASH_TRUNC_CHARS == invocation["trunc_chars"]` | One predicate; document the IL fixture's scope; one assertion |
| **C-34** | correctness / documentation | **Small user-facing untruths clustered around the LLM path.** `_set_controls_running` re-enables `btn_run` on `self.bundle_zip_path` **alone**, dropping the key condition `_load_bundle_inputs` applied — so after the first run of a session the readiness gate on the button is gone. Provider-locked strings tell a user running Gemma on Ollama that "EL uses the OpenAI API". The `"model=None; skipping."` log line reports that literal **regardless of the actual value**, and its reachable trigger is a whitespace-only field. Numeric settings accept out-of-range values silently, and a **negative** `trunc_chars` reaches the prompt builder's guard `if trunc_chars and len(s) > trunc_chars`, truncating the **tail** of every field with no log line. And `plugins/03_harmoniser/ui.py`'s **"LLM refine" checkbox is read by nothing** — a control that reads as the cost/provider safety switch, which a user can untick and still spend money | Restore the gate; neutralise the strings; `model={model!r}`; validate the numerics; wire or delete the checkbox |
| **C-35** | packaging / hygiene | **The dependency and build story has three unowned seams.** `httpx`, `anyio`, `pydantic`, `pydantic_core` and `jiter` are named in **neither spec** and arrive only as transitive analysis products of `collect_all('openai')` — dependency-by-coincidence one layer below the layer F-09 criticised, and invisible to the spec test because they are not imported under `plugins/`. `requirements.txt` is exercised **only** by Docker while CI installs from `pyproject.toml`, with nothing keeping them in step. And `datas = [('plugins', 'plugins')]` ships the build machine's `__pycache__` as dead weight, since the loader reads and sanitises `.py` source | Name the transitive stack explicitly, or add a test that can see it; run one CI cell from `requirements.txt`; exclude `__pycache__` |
| **C-36** | documentation | **The `docs/installation.md` smoke test cannot be followed and is not offline.** It says "Click Run" for two plugins that **have no Run button** (naming the wrong one matters here: the adjacent button spends money); it omits the A-CSV that both harmonise buttons require; it says "pipe the Plugin 02 output through Plugins 04 and 05" when plugin 04's input is a **bundle ZIP** only plugin 03 produces; and its "LLM-free" route calls five external bibliographic APIs, so it is **un-billed, not offline** — which for an offline reviewer is the entire story. A strictly offline route exists today using only committed files (§B3.3) | Correct the button names, insert the A-CSV step, replace "pipe" with the bundle hand-off, and mark plugin 02 as network-dependent |
| **C-37** | robustness | **`_parse_llm_json_array` accepts an object *wrapping* a list but returns `[]` for a bare object and for a trailing-comma list, and `resp.choices[0]` is unguarded.** So models that habitually wrap in `{"results": …}` work by accident while a model emitting a single object for a single-item batch silently produces all-uncertain output — indistinguishable downstream from a non-answer. A server returning `{"choices": []}` raises `IndexError`, whose text matches neither predicate, so the batch goes terminal carrying a Python idiom as its `error`. `finish_reason` is never read | Promote a lone dict to `[dict]`; guard `choices`; read `finish_reason` |

#### Low

| ID | Category | Finding | Fix |
|---|---|---|---|
| **C-38** | documentation | **A cluster of LLM-area claims that are already false at `f952e69`, independent of any future change.** `METASCREENER_CACHE_DIR` and `.cache/<stage>.jsonl` **do not exist** (six passages instruct the reader to configure, inspect, prune or share them); `python -m metascreener` fails (no `__main__.py` in the tree or the built wheel); the `OPENAI_MODEL` row is wrong in **every column**; four places claim the manifest records the model and prompt version; the FAQ says integrity mismatch "refuses to proceed" when the code **warns**, contradicting both the code and the README; `usage.md` and `faq.md` still document the **pre-F-01** cache key; `record_hash` is not a field of the cache JSONL; "a few thousand API calls" overstates the demonstration run by **two to three orders of magnitude** (the true figure is 254 decisions ≈ 6 requests at the default batch size, and the confusion is seeded by "170 EL calls" meaning *decisions*); the test counts (166 / "✅ 166 passed" / "162 passed, 1 xfailed") are all wrong and **no `xfail` marker exists anywhere**; installation.md contains no Docker section the changelog claims; three docs cite the evidence gate at a line that now holds a progress callback; and the Dockerfile header misdescribes its own base image | Each is mechanically pinnable against the corresponding constant, and `tests/test_metadata.py` already pins other doc facts — **the pattern exists** |
| **C-39** | documentation | **All three `docs/usage.md` figures show a different plugin from the one their caption describes**, in a clean cyclic rotation: `plugin03_criteria_parser.png` shows the **`Screen A — EL`** tab, `plugin05_ih.png` shows the **Harmoniser** tab, `plugin06_el.png` shows the **`Screen A — IH`** tab. Each caption matches its **filename**, not its content. Two consequences: the caption describing "the model selector, the temperature… the batch size, the truncation length… and the cache toggle" is an accurate description of a panel the reader is **not being shown**; and the repository's only screenshot of an LLM-stage settings panel is filed under a criteria-parser name. These are three of the four images in the repository and the project's only visual evidence of the GUI-first claim. *Favourable side effect:* the EL Settings screenshot **does exist**, which is why three of the brief's four proposed human observations could be settled from source (§B10) | Rename or re-shoot; correct the captions |
| **C-40** | robustness | **`.env` is an unallowlisted configuration channel, and the one gate that decides whether the LLM path runs is untested.** `_load_env_file` sets **arbitrary** `KEY=VALUE` pairs into `os.environ` — which is the *enabling* mechanism for `OPENAI_BASE_URL` and also means a project-root `.env` can set `PATH`, `SSL_CERT_FILE`, `HTTP_PROXY`, `OPENAI_ORG_ID` or `OPENAI_PROJECT_ID`, the last two of which **[installed SDK source]** the SDK silently promotes into request headers. Not a remote attack surface (the file is user-authored and gitignored) but an undeclared channel the destinations are about to make load-bearing. And `::_has_openai_key`'s body **never executes in the suite** — the gate is asserted only in prose in a docstring | Read the endpoint explicitly by name rather than relying on the generic loader; log which keys `.env` supplied; one unit test for the predicate |
| **C-41** | process | **The `openai` version at golden-capture time is unrecorded and unrecoverable.** §B4.6 establishes that a field can be added to the goldens offline only if its value for the archived run is **known** — and no artefact records the SDK version, so this one **can never be added retroactively**. It is a hard constraint on one of the migration options, not a hypothetical | Record `openai.__version__` in the capture tool's `_invocation` from the next capture forward, and mark the existing goldens' SDK version explicitly **unknown** rather than absent |
| **C-42** | hygiene | **Small dead or self-contradicting artefacts in the LLM path.** `::ApiKeyDialog._is_valid` is called by nothing and the class docstring **still documents the rule F-08 removed**, in the very file that was the subject of the fix. `secrets/README.md` tells users to put `.env` in `secrets/` while `ENV_FILE_NAME` resolves to the project root — so a user following that advice has their key silently ignored. `::_make_item_for_llm` is **dead** yet asserted to exist by a test whose purpose is to prove EL/IL share helpers — so it proves a re-export chain no code traverses while the item-construction logic is twinned inline. Two `_safe_str` implementations coexist in `_common/` with different failure behaviour and **the LLM path uses the unguarded one**. Two docstrings in `llm_client.py` describe the same cache key incompatibly. IL passes `block_tag="exclude"` at an inclusion stage | Delete or wire each; one `_safe_str`; correct the stale docstrings |

#### Open decisions the maintainer will have to make

*Questions, with the trade-off named on each side. Not recommendations.*

**Q1 — Does the resolved endpoint enter the cache key?**
*For:* it is the only thing that makes an entry attributable to an engine; without
it one model name shared across two providers is one namespace, and the README
recommends the maximally ambiguous configuration. §B4.5–B4.6 show the migration is
provably safe offline.
*Against:* it invalidates **every** golden key unconditionally, so the deferred
re-key becomes mandatory and its artifact must be built — and wave 2's script was
never committed, so there is nothing to reuse.

**Q2 — If it does, is it read from `os.environ` at keying time or threaded from the constructed client?**
*For env-read:* trivial — the client does not exist where `_cache_key` is called.
*Against:* it makes golden byte-identity **environment-dependent**, and
`conftest.py` has no environment isolation while
`tests/test_cache_key.py::test_key_stable_across_processes` copies `os.environ`
wholesale, so **it cannot detect the instability.** The failure mode is 16 green CI
cells and a red suite on the machine of the person developing the feature.
*For client-threaded:* authoritative and environment-independent. *Against:* it
stops being an additive change.

**Q3 — Verbatim, hashed, or a coarse label?**
The three are not exclusive, and the unresolved tension is stated in §B8.1: **an
unsalted hash of a short internal hostname is a discriminator, not a secret; a
per-bundle salt makes it a secret and destroys the cross-bundle comparability that
was the reason to record it.** Note also that §B4.5 measured absent-as-`""` and the
SDK-resolved default to give **disjoint** key sets, so this choice is a **one-way
door**: changing one's mind later costs a second re-key.

**Q4 — Does the Model field stay free text?**
*For:* llama.cpp ignores the field entirely and the README says so — a condition no
discovery route can detect; a server-supplied dropdown is **still an enumeration**
and re-creates Destination 1's failure one layer out; filtering the hosted list
requires a name-pattern list, i.e. the hand-maintained list being removed; and F-08
is this project's own precedent for a validation rule that looked like a safety
check and made a documented workflow GUI-unreachable.
*Against:* a whitespace-only or misspelled model produces a full corpus of flagged
records, a `"EL done."` label and enabled exports — **the most likely local-mode
user error yields a completed-looking run.** An editable combobox is the obvious
compromise and is a **new pattern here**: all three existing `ttk.Combobox`
instances are `state="readonly"`.

**Q5 — Does local-by-default ship before or after provenance is recorded?**
*Before:* the endpoint/model work is what makes provenance *necessary*, so shipping
the default first is the faster route to a usable tool.
*After:* the manifest records no model, and the only artefact tying the published
kappas to `gpt-4o-mini` is a field inside a fixture that a model swap must
overwrite. Shipping the default first means the space of possible producing engines
grows from a vendor catalogue to every quantisation of every open-weight model,
with nothing in any artefact narrowing it.

**Q6 — Is the published accuracy figure re-measured under the new default, or qualified in prose?**
*Re-measure:* one live run per candidate model, a fresh capture (the tool's `MODEL`
is a source constant with no CLI override), and it rewrites every kappa. C-12
established that **no test pins those figures, so this can happen silently** —
which is an argument for doing it deliberately and loudly, not for avoiding it.
*Qualify in prose:* three sentences at three places (§B6.3), costing nothing and
remaining honest. But it leaves the tool shipping a default whose agreement with
human reviewers has never been measured, in a manuscript under revision — and C-13
means the fixture and the dataset must then diverge.

**Q7 — Does the `evidence[c.id]` dict change once or twice?**
*Once:* fold F-64's reason code, F-63's computed span, F-62's rename, F-77's
separator and C-3's tier-2 provenance into one commit family and one re-capture.
*Twice:* a single large evidence-shape change is a large diff review against a
fixture set that is **also a published dataset** — and §B8.3's ordering puts F-12's
test work first, so batching means the biggest change lands with the least coverage
history behind it.

**Q8 — Is F-65 fixed in the same period as the model work?**
*Same period:* both touch the same criterion-routing neighbourhood and both need a
re-capture.
*Different periods:* F-65 is the only other open finding that **moves the
demonstration funnel**, and a model change also moves it — concurrent, the two
effects are inseparable in the record, **which is exactly the failure the project
already lived once with 73-vs-80.**

**Q9 — Is `batch_size` re-documented as a correctness parameter?**
*For:* C-1 makes batch composition safety-relevant, and a weaker model should
arguably be run at a smaller batch for correctness reasons — nothing tells the user.
*Against:* **the honest version of this argument is weaker than it looks**, because
C-1 fires at `batch_size = 1` too; the real mitigation is the guard, not the
setting. Re-framing a throughput knob as a safety knob without the guard would be
false reassurance.

**Q10 — Does the diagnostic quote a coverage percentage for `llm_client.py` at all?**
*For:* F-12's cell needs a figure to be restated against.
*Against:* three mutually incompatible numbers exist (21%, 32.6%, 53.0%), the
instrument may be reading line numbers shifted by one (§A11.4), and `coverage.py` is
already installed by CI and never invoked — so a re-measurement under one instrument
costs one CI step and removes the ambiguity permanently. **This document quotes
none of the three.**

---

### B10 Human-observation questions

#### B10.0 Questions that CAN be settled from source — deliberately not listed as HOs

The brief names four candidate observations. **Three are settleable from source at
`f952e69`, and one of those is additionally corroborated by a committed
screenshot.** Listing them would waste the maintainer's time, so they are answered
here.

**"Is the EL/IL Model field a free-text Entry or a Combobox in the running app?" —
Settled. A free-text `ttk.Entry` with no validation.** Both `_build_ui` methods
construct `ttk.Entry(settings, textvariable=self.var_model, width=24)`, and
repository-wide `ttk.Combobox` occurs three times, none of them a model picker.
**Corroborated visually, and this is where C-39 pays off:** the EL Settings panel
*is* photographed in the repository — under the wrong filename,
`docs/images/usage/plugin03_criteria_parser.png` — and it shows `Model` rendered as
a flat full-width text box **with no dropdown arrow**, directly above `Temperature
0.0` rendered **with** spinner arrows. The visual contrast between the two widgets
in one panel is itself the evidence. So `docs/installation.md`'s "model dropdown" is
false in the running app as well as in source.

**"What does the EL/IL Settings panel actually show?" — Settled, and there is a
screenshot.** From that same image, the `EL Settings` labelframe shows, top to
bottom: `Model` = `gpt-4o-mini`; `Temperature` = `0.0` (spinner); the caption
`(0.0 = deterministic; non-zero invalidates cache)`; `Batch size` = `50`;
`Trunc chars` = `1500`; and a **checked** `Use cache (bundle cache/EL_cache.jsonl)`.
Above it, `EL Criteria (read-only)` lists EC-2 and EC-3 at `operator = llm`,
`targets = keywords`. Top-right shows `OPENAI_API_KEY ✓` in green. This matches
`_build_ui` exactly — **including no base-URL field and no threshold field.** It
also settles two things source alone left open: the batch size actually used for
that run was **50**, not the goldens' 5; and the notebook tab in focus is **`EL Full
report`**, with `Log` third and unselected — **so the log lines that are a failed
run's only signal are not on screen.**

**"Does the key dialog appear on every launch in practice?" — Settled.**
`MetaScreenerApp.__init__` calls `_prompt_api_key_always()` unconditionally before
`_load_plugins()`; the method's docstring says so; nothing gates it; and there is no
path through `run.py` that reaches the notebook without it.

**Also settled, so also not listed:** that cancelling exits with no window and no
message; that no LLM setting except the key persists between launches; and that
`base_url` has no GUI surface.

#### B10.1 Pending observations

*Format follows `FIX_WAVE_4_REPORTS.md`. **HO-3, HO-4 and HO-5 gate any decision
about Destination 2** — they are the only route to evidence about whether a local
model can drive the EL/IL contract at all. **HO-1 and HO-2 gate the GUI-first claim
for the distributable.** The maintainer has `ollama` 0.32.6 on PATH; `lms`,
`llama-server` and `llama-cli` are absent, so HO-3 through HO-5 assume Ollama and
nothing else.*

**HO-1 — what does the frozen build do on first run with no key?**
*Repro:* move or rename `<repo>/.env` (it exists, untracked and gitignored — do not
delete it); ensure `OPENAI_API_KEY` is unset in both the user and machine
environment; **double-click** `dist/metaScreener.exe`; press **Cancel**. Repeat,
launching `dist/metaScreener (console).exe` from a PowerShell prompt instead. Then
enter `ollama` as the key with **Remember on this device** left checked, quit, and
relaunch.
*Report:* does a dialog appear at all under the double-click path, and how long
after the click? On Cancel, does the process exit silently, flash a window, or leave
anything in the taskbar — **could a first-time user distinguish "cancelled" from
"crashed"?** What text, if any, reaches the terminal under the console build. And
did a `.env` appear anywhere you can find, and does the next launch prefill?
*Why source cannot settle it:* `env_path` derives from
`Path(__file__).resolve().parents[1]`, and under a one-file PyInstaller build the
value of `__file__` for a PYZ-embedded module is a property of the bootloader, not
of this repository. `04_frozen_build.md` measured `_plugins_root_frozen()` and never
touched `project_root`. Whether the *dialog* draws at all before `_load_plugins()`
under the windowed build is likewise unobserved.

**HO-2 — can the distributable reach a local endpoint at all?**
*Repro:* place a `.env` **beside `dist/metaScreener.exe`** containing
`OPENAI_BASE_URL=http://localhost:11434/v1` and `OPENAI_API_KEY=ollama`; launch by
double-click. Repeat with both set as **user environment variables** instead, with
no `.env` anywhere.
*Report:* in each case, whether the key field prefills with `ollama`, and — with
Ollama running (HO-3) — whether a short EL run reaches the local server or
`api.openai.com`. **The cheapest way to tell them apart: stop Ollama and see
whether the failure text in the EL Log sub-tab names a connection refusal to
`localhost` or an authentication error from OpenAI.**
*Why source cannot settle it:* same `__file__` question as HO-1, plus the fact that
nothing in the repository reads `OPENAI_BASE_URL`, so the behaviour is entirely a
property of the installed SDK at run time. **This is the single most decisive
observation for Destination 2** — if the answer is "neither route works", a GUI
endpoint field must persist somewhere new before anything else can be built.

**HO-3 — does an Ollama-served model satisfy the JSON contract at all?**
*Repro:* `ollama pull` one small instruct model; start the server; set
`OPENAI_BASE_URL=http://localhost:11434/v1` and `OPENAI_API_KEY=ollama`; open the EL
bundle used for the goldens; set **Batch size to 5** and Trunc chars to 4000 to
match the capture; run EL over the 85 records.
*Report:* the `[EL-LLM]` and `[EL]` lines from the Log sub-tab **verbatim**,
including every `cache_hits=… | to_call=…` line and every `batch … failed:` line
with its exception text. Then the counts label, and — from the exported bundle —
the distribution of `el_outcome` and, from `el_evidence_json`, how many decisions
have `quote_valid: true`.
*Why source cannot settle it:* no test, golden, or document in the repository
exercises a non-OpenAI model, and `README.md` says so explicitly. **The exception
text is as valuable as the outcome**, because §A2.4 predicts that Ollama's error
phrasing matches neither retry predicate — this observation tests that prediction.

**HO-4 — what is the flag rate, and why did each refusal fire?**
*Repro:* from HO-3's exported bundle, count records by outcome, and for every
`UNCERTAIN` criterion in `el_evidence_json` record whether `quote_valid` is false,
whether `confidence < 0.60`, or whether `decision` is `uncertain`.
*Report:* the three counts separately, plus the set of distinct `decision` strings
and the set of distinct `confidence` values seen.
*Why source cannot settle it:* this is the measurement §B5.3 returns as **not
established**, and it is the number that decides whether a local default is *usable*
as against merely *safe*. The baseline to compare against is EL 7/170 per-decision
(4.1%) and 7/85 per-record (8.2%). **Note the instrument limitation up front:** the
three causes are currently distinguishable only by hand-reading the evidence JSON,
because `UNCERTAIN` carries no reason code — which is why F-64 is a prerequisite for
any repeatable version of this measurement.

**HO-5 — does the `decision` case bug fire in practice, and does `a_id` drift?**
*Repro:* in the same HO-3 log and bundle, look for the signature of C-5 — a
criterion whose evidence shows `decision: "uncertain"` **together with**
`quote_valid: true` and a confidence at or above 0.60. Separately, compare the set
of `local_id` values in the input against the `a_id` values appearing in
`el_evidence_json`.
*Report:* whether that contradictory combination appears at all, and how often; and
whether any `a_id` appears that is not a `local_id`, or any `local_id` receives an
evidence entry whose quote does not occur in its own text.
*Why source cannot settle it:* whether a given model re-cases its decision tokens or
drifts identifiers across a batch is a property of that model. **The second half is
the field test for C-1**, which is otherwise established only by a fabricated
client.

**HO-6 — which model produced the manuscript's 73?**
*Repro:* none in the repository. Check off-repo records — lab notes, an old shell
history, a billing statement for the period before 2026-04-01, or recollection.
*Report:* the model id, and the date if recoverable.
*Why source cannot settle it:* `docs/llm-evaluation.md` states the run's "bundle,
its manifest, its response cache — were not archived and will not be recovered",
and §A9 establishes that **no manifest field records a model, so they could not have
supplied it even if archived.** If the answer is unrecoverable, that should be
*stated* in the document rather than left as a gap — it is the concrete cost of C-3
and the strongest single argument for fixing it.

**HO-7 — was the model disclosed to the human raters?**
*Repro:* recollection, plus any instructions circulated to AReyes / JKiss / JVoisin
alongside the grids.
*Report:* whether raters knew which model produced the verdicts they were
adjudicating, and whether they saw the LLM's decision before recording their own.
*Why source cannot settle it:* `tools/eval_grid_generator.py` never emits a model
name, so the *artefact* does not disclose it — but that does not establish what the
raters were told. It bears on the in-group-bias limitation the document already
declares.

**HO-8 — does the ingestor actually reproduce `docs/data/` byte-for-byte?**
*Repro:* run the command block in `docs/llm-evaluation.md` §Reproducibility exactly
as written, into a scratch directory, and diff the four outputs against the
committed `docs/data/eval_*` files.
*Report:* whether each of the four is byte-identical, **and** — before diffing —
the value of `git config core.autocrlf` on the machine, plus a second diff with line
endings normalised.
*Why source cannot settle it:* I am forbidden from running it, and **[measured]** it
would be ambiguous anyway: C-14 established that `docs/data/**` is `text=auto`, so a
raw byte diff can fail for line-ending reasons that have nothing to do with the
data. **Recording `core.autocrlf` and diffing both ways is what makes the answer
interpretable**; without it the maintainer would have two candidate causes and no
way to separate them.

---

## Corrections to the brief and to prior diagnostics

The brief asked to be told where it is wrong about the repository. Nine items, the
first two material to the design.

1. **"If model identity were added to the cache key" — false premise, and it is the
   wave's most important correction.** `model` has been hashed **by name** since
   before the goldens were captured, and was present in the pre-F-01 formula too.
   Answering the question as asked would have produced a reassuring "nothing is
   invalidated" about the wrong subject. The question conceals three distinct things
   with three different answers (§B4.1), and the one that *would* invalidate every
   golden key is adding the **endpoint** (§B4.5).
2. **The implied risk that a default-model change breaks the goldens — it does
   not.** The goldens are **self-describing**: `tests/golden/{el,il}_cache_v3.1.0.json`
   carry a `{_invocation, cache}` envelope and the regression harness passes
   `model=invocation["model"]`. **[measured]** the full suite is unchanged under a
   different default. The uncomfortable corollary is that the change is therefore
   also *invisible* (C-12).
3. **"the evaluator" is not where the evidence gate lives.**
   `plugins/_common/evaluator.py` is the deterministic EH/IH evaluator and its own
   docstring says LLM evaluation is intentionally not implemented there; there is
   also no `OUTCOMES` constant in `plugins/_common/`. **A second instance of the
   same premise recurs in the brief's B5 question**, which asks how `used`,
   `valid_quote` and `confidence` "combine in the evaluator" — they do not combine,
   and **`used` is not a gate term at all.** Both corrections must be carried
   forward together or the register will acquire an `evaluator.py` coordinate for a
   finding that lives in `screen.py`.
4. **"the `cache_hits` counter" — there is no counter.** It is a per-criterion
   f-string, computed as `len(cached_pairs)`, never summed, never persisted, absent
   from every report and from the manifest (§A8.5).
5. **"how the harness converts between the two cache shapes" — there is no
   conversion.** The capture tool and the regression tests bypass the production
   serialisation pair entirely, which is why that pair has no behavioural test
   (C-19).
6. **"cached bundles" are not a model-name location.** A shipped
   `cache/EL_cache.jsonl` records no model; the `_invocation` envelope exists only
   in the test fixtures and is a property of the capture harness, not of the product
   (§A9.4).
7. **"the silent `return {}`" is not the not-running-server path.** That has exactly
   three triggers, all *before* any network activity; a server that is merely down
   takes the **terminal** branch, which does log per batch and does stamp `error`.
   The user-visible outcome is nearly identical; the forensic trace is not — and the
   brief's underlying worry is right about the *destination* in a sharper form
   (§B3.1).
8. **"the maintainer's model may no longer be supported by whatever enumeration the
   code carries" — the code carries no such enumeration.** No `Literal`, no `Enum`,
   no combobox values, no `argparse choices`, no whitelist; the only constraint is
   `if not model:`. Destination 1's *stated* problem is already solved on the
   model-name axis. **What is actually broken is the opposite** — nothing validates
   the string, so a typo produces a completed-looking run (C-8). Any discovery
   feature must be an *aid* that preserves this permissiveness, not a gate that
   introduces the enumeration the brief fears.
9. **"plugin 01 uses GPT-4o vision" — correct, with a distinction the phrasing
   elides:** it defaults to **`gpt-4o`** under **`OPENAI_MODEL`**, a different
   literal and a different environment variable from EL/IL's. And **"F-12 at 0%
   coverage" is partly stale** in its headline while fully accurate in its substance,
   with its evidence cell's *mechanism* also wrong (§A11.2–A11.3).

**Brief assertions checked and confirmed correct:** the 16-cell CI matrix; the 0.60
threshold (with the nuance that it is spelled `0.60` in the harmoniser and `0.6` in
the two consumers, and is also injected into the prompt — C-15); 82 register rows;
422 passed / 4 skipped; "post-F-01 the key hashes the fully rendered prompt"; and
"accepts any non-empty key since wave 1" (with the scope caveat that the fix
unblocked step 2 of a two-step workflow — C-6).

**Corrections to prior diagnostics in this set**, offered for consistency rather
than as findings. `02_quality.md`: the "Client construction" row is **right and I
agree with it**, but its line number is stale, and two neighbouring rows are
post-fix stale — the **Cancellation** row describes pre-F-26 behaviour and the
**§6.4 key derivation** block describes the pre-F-01 key. `05_report_production.md`:
two items encountered in passing are stale — it lists `data/input_errors.csv` as
written "only if non-empty" (F-75 made it unconditional) and says EL's ragged rows
are "silently padded or truncated" (F-72 routed them to `parse.skipped`).
`01_architecture.md` is the **most under-used document in the set**: it was cited
once in the whole analysis, for a diagram label, and it contains the measured −1
runtime line-shift warning that bears directly on every line-number citation in this
area (C-28) as well as the import-cycle note that makes C-31 more than a deletion.

---

## What was not done

- **No network activity of any kind.** No package installed, no weights downloaded,
  no LLM endpoint contacted local or remote, no server or daemon started. The single
  permitted local check was `ollama --version`.
- **No live model was run**, so every statement about model *behaviour* is either
  **[general knowledge]**, explicitly labelled, or returned as **not established**
  with the settling measurement named. §B10 exists because of this boundary, not in
  spite of it.
- **No file was modified.** The measurements in this document that required
  executing repository code were done in-process with local monkeypatching and
  fabricated clients, writing nothing; and the one experiment that needed a changed
  production default used the existing `SCREENA_*_MODEL` environment variables
  rather than an edit.
- **No coverage figure is quoted** for `plugins/_common/llm_client.py`. Three
  mutually incompatible numbers exist and the instrument may be reading shifted line
  numbers; §B9 Q10 sets out the choice.
- **No `F-nn` was assigned and `03_findings.md` was not touched.** §B9 is a single
  deduplicated `C-n` namespace; the sweep against the existing 82 rows is a later
  wave, and the rows that are plainly the LLM-facing face of an existing finding are
  marked inline so they are **merged, not added**.
- **`docs/internal/diagnostic/README.md` was not updated**, although it carries an
  index table that now omits documents 04, 05 and 06 and still describes the
  repository at `365325c` with 55 findings. The brief permits exactly one new file,
  so this is left for the coordinator rather than done silently.
- **Two questions in Part A are returned unresolved rather than guessed:** whether
  the declared `openai>=1.40.0` floor has the `OPENAI_BASE_URL` fallback the
  documented local path depends on (only 1.106.0 is inspectable without a network
  fetch), and whether a cached-run bundle is byte-identical modulo one timestamp
  (the manifest gains a history entry on every run, so more than one field differs).
  Both name the evidence that would settle them.

**Note for whoever adds this file to the tree.** It will not break the suite.
`tests/test_metadata.py::DOCS_INTERNAL_DIRS` is `("internal",)` and both
cross-reference tests skip anything under `docs/internal/` — F-29's fix, already in
the tree — so no index action is needed for this file or any future one there. The
suite is green with all six diagnostic documents present, and was re-run with this
one added.

