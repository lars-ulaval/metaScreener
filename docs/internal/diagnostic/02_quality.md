# 02 — Tests, Correctness, Documentation and Packaging

*Diagnostic report, Phase 5–7. Read-only analysis.*

**Repository state when this document was written:** `main` @ `365325c`, 2026-08-08 — the
same snapshot as the rest of the diagnostic set. *(This pin was added in wave 6. Its absence
was itself a defect: unlike `05_report_production.md`, this document carried no commit and no
date, so its present-tense assessments read as claims about the software now rather than as a
dated snapshot. Where a passage has since been overtaken, an `*Addendum (wave N, F-nn):*`
follows it; the original text is never rewritten. §6.3, §6.4 and §6.5 each carry one.)*

**How the test runs in this report were produced.** The system Python 3.11.0 was missing
`pandas` and `langdetect`, so I created an isolated venv outside the repo at
`…/scratchpad/dvenv` and installed `requirements.txt` + `pytest` + `pytest-cov` into it.
Nothing was installed into the system Python and nothing was installed into the repo
(no `pip install -e`, so no `.egg-info` was regenerated). Because writing this report into
`docs/internal/diagnostic/` itself perturbs two tests (see §5.2), all reported baselines
come from a pristine `git archive HEAD` export unpacked into the scratchpad.

---

## Phase 5 — Tests and CI

### 5.1 Inventory — 13 files, 166 tests

| File | Tests | Kind | What it covers |
|---|---:|---|---|
| `tests/conftest.py` | — | fixtures | Shared fixtures plus `_FakePluginMeta` / `_FakeBasePlugin` stand-ins so plugin modules import headlessly. |
| `test_eval_ingest.py` | **32** | unit + end-to-end | `TestCohenKappa` (5), `TestFleissKappa` (6), `TestNormalizeDecision` (5), `TestLlmStatusMapping` (9, polarity-aware mapping), `TestWorkbookReader` (3), `TestEndToEnd` (4). |
| `test_imports.py` | **27** | import audit + shim contract | `TestCoreImports` (4), `TestPluginImports` (3), `TestSharedHelpersOrigin` (4 — asserts EL/IL helpers really come from `_common`, guarding against the shadowing bug fixed in `90ff050`), `TestPerPluginPrompts` (4), `TestPerPluginUI` (4), `TestPerPluginScreen` (4), `TestTemperatureCacheInvalidation` (2), `TestEnvironmentInfo` (2, informational). |
| `test_eval_grid_generator.py` | **27** | unit + end-to-end | Loaders (7), dropdown options (3), stratified partition (6), multi-stage partition (2), end-to-end (9) — including the rater-blindness guard `test_decisions_sheets_do_not_expose_llm_columns`. |
| `test_evidence_gating.py` | **23** | unit | `TestQuoteInText` (10), `TestShaText` (4), `TestCacheKey` (6), `TestRowTargetTextHash` (3). The core of the scientific claim. |
| `test_criteria_parser.py` | **16** | unit | `_parse_free_text_criteria` (8) and `_infer_criterion_details` (8) for Plugin 03. |
| `test_deterministic_filters.py` | **15** | unit | `_eval_criterion` across all nine operators plus MISSING/UNKNOWN paths. |
| `test_bundle_integrity.py` | **12** | unit | ZIP structure (6), SHA-256 behaviour (4), `_common/bundle.py` public surface (2). |
| `test_metadata.py` | **5** | metadata assertion | Version consistency across `pyproject.toml`/`CITATION.cff`/`CHANGELOG.md`; README CI badge; plus `TestDocsCrossReferences` (3): README→docs/index link, every `docs/**/*.md` listed in `docs/index.md`, every internal markdown link resolves. |
| `test_el_regression.py` | **3** | golden + prompt hash | Byte-identity of `EL_FULL.csv`; SHA-256 of the assembled OpenAI `messages` payload; `PROMPT_VERSION` literal. |
| `test_il_regression.py` | **3** | golden + prompt hash | Same for IL. |
| `test_eh_regression.py` | **1** | golden | Byte-identity of `EH_FULL.csv`. |
| `test_ih_regression.py` | **1** | golden | Byte-identity of `IH_FULL.csv`. |
| `test_harmoniser_regression.py` | **1** | golden | Byte-identity of `criteria_harmonized.csv`. |
| **Total** | **166** | | |

### 5.2 Suite run — results

**Clean baseline (pristine `git archive HEAD`, venv described above, Windows 11 / Python 3.11.0):**

```
........................................................................ [ 43%]
........................................................................ [ 86%]
......................                                                   [100%]
166 passed in 3.62s
```

**166 passed, 0 failed, 0 skipped, 0 errors, 3.62 s.** The suite is fast, fully offline,
needs no display, and needs no API key.

**In the live working tree, the same command fails — because of this report.**

```
FAILED tests/test_metadata.py::TestDocsCrossReferences::test_every_doc_listed_in_index
1 failed, 165 passed in 5.28s

E  AssertionError: Docs not referenced from docs/index.md:
E      internal/diagnostic/00_overview.md
E      internal/diagnostic/01_architecture.md
E      internal/diagnostic/02_quality.md
E      internal/diagnostic/03_findings.md
```

(An earlier draft also failed `test_internal_markdown_links_resolve`, for two reasons worth
recording: a forward reference to a file not yet written, and the literal markdown
link-syntax notation used in prose, which the test's regex reads as a real link. Both were
resolved by writing the files and rephrasing the notation. Note also that
`internal/diagnostic/README.md` does **not** appear in the failure list — the test accepts a
bare-filename match, and `docs/index.md` happens to contain the string `README.md` because
it links to the project README. That is an accidental pass, not a real reference.)

`test_metadata.py:167` does `docs_dir.rglob("*.md")` (and `:90` for the link test) and requires **every** markdown file
anywhere under `docs/` to be named in `docs/index.md`. That is a defensible rule for
*published* docs and a hostile one for internal working documents: any internal note,
draft, or — as here — diagnostic report placed under `docs/` breaks CI until it is
advertised on the public documentation index.

This almost certainly explains the known-broken `CHANGELOG.md:35` reference to
`docs/internal/reviewer-response-map.md`: the changelog announces the file, the file is
absent from the repo, and this test is exactly the mechanism that would have forced its
removal. **Recommendation: exclude `docs/internal/**` from both cross-reference tests.**
Until that happens, this report's own directory has to be either exempted or advertised.

### 5.3 CI audit tools

Both run exactly as `.github/workflows/test.yml:54-58` invokes them.

```
$ python tools/audit_imports.py plugins/ tests/
plugins\01_reference_extractor\original\prisma_citations_ai_v3_1.py: clean
… 36 files, all "clean" …
EXIT=0

$ python tools/audit_decorators.py plugins/ tests/
… 46 plugin files + 14 test files, all "clean" …
EXIT=0
```

Both pass. One observation: **`audit_imports.py` silently audits nothing under `tests/`.**
Its output lists 36 files, all in `plugins/`; `audit_decorators.py` given the same
arguments lists 60 files including all 14 test files. So the CI step named
"Audit imports (plugins + tests)" is auditing plugins only. Not a defect in what it does
check — the audit is genuinely clean — but the step's name overstates its coverage.

### 5.4 Coverage

`pytest --cov=plugins --cov=metascreener --cov=tools`, clean tree:

**TOTAL: 10,753 statements, 8,329 missed, 23% covered.**

**Well covered** (the deterministic scientific core, as intended):

| Module | Stmts | Cover |
|---|---:|---:|
| `tools/eval_grid_generator.py` | 347 | **97%** |
| `tools/eval_ingest.py` | 420 | **90%** |
| `plugins/_common/parser.py` | 250 | 76% |
| `plugins/_common/runner.py` | 82 | 71% |
| `plugins/07_il/plugin.py` | 41 | 66% |
| `plugins/07_il/screen.py` | 368 | 63% |
| `plugins/06_el/screen.py` | 368 | 62% |
| `plugins/06_el/prompt.py` / `07_il/prompt.py` | 18 each | 94% |

**Untested or nearly so:**

| Module | Stmts | Cover | Note |
|---|---:|---:|---|
| `plugins/02_references_of_x/services.py` | 978 | **0%** | |
| `plugins/02_references_of_x/ui.py` | 681 | **0%** | |
| `plugins/02_references_of_x/pipeline.py` | 196 | **0%** | |
| `plugins/02_references_of_x/core.py` | 129 | **0%** | |
| `plugins/01_.../prisma_citations_ai_v3_1.py` | 723 | **0%** | |
| `metascreener/main.py` | 168 | **0%** | |
| `metascreener/api_key_dialog.py` | 78 | **0%** | |
| `metascreener/plugin_api.py` | 19 | **0%** | |
| `plugins/07_il/ui.py` | 811 | 7% | |
| `plugins/06_el/ui.py` | 675 | 7% | |
| `plugins/03_harmoniser/ui.py` | 556 | 8% | |
| `plugins/06_el/standalone.py` / `07_il/standalone.py` | 332 each | 8% | |
| `plugins/04_eh/ui.py` / `05_ih/ui.py` | 530 each | 10% | |
| `plugins/_common/widgets.py` | 60 | 18% | |
| `plugins/_common/llm_client.py` | 197 | 21% | `run_m1_llm_for_criterion` (lines 157-375) is entirely unexecuted. |
| `plugins/_common/bundle.py` | 112 | 35% | `_export_next_bundle_zip` (155-240) entirely unexecuted. |
| `plugins/03_harmoniser/llm_refine.py` | 73 | 11% | |

**The GUI-layer figure, quantified.** The six `ui.py` files plus the two `standalone.py`
files total **4,447 statements, of which 4,128 (92.8%) are never executed by the suite**.
In source-line terms that is **7,092 lines** (`ui.py`: 6,009 across six files;
`standalone.py`: 1,083) — larger than the ~5,000 the brief estimated, because `07_il/ui.py`
alone is 1,314 lines.

**Two more untested surfaces that matter more than the GUI headline suggests:**

1. **`plugins/02_references_of_x/` is 1,984 statements at 0%.** It is the second-largest
   subsystem in the repo and has no test of any kind — not even an import smoke test.
2. **`_common/llm_client.run_m1_llm_for_criterion` — the entire LLM interaction path,
   including all retry, batch-splitting, and truncation-reduction logic — is 0% covered.**
   `test_evidence_gating.py` covers the *helpers* (`_quote_in_text`, `_cache_key`,
   `_sha_text`) and the golden tests replay a *cache*, deliberately short-circuiting before
   the network call. So the code that decides what happens when the API returns 429, or
   returns truncated JSON, or dies mid-run, has never been executed in a test.

**Relevance to the Phase 4 de-duplication.** The proposed refactor moves ~3,050 lines. Of
those, roughly 1,340 (the `screen.py` and `prompt.py` moves) are protected by byte-identity
goldens and can be done with high confidence. The other ~1,710 (the two View merges, the
Standalone merge, the DataTable consolidation) sit in the 7% -covered region. **A View-layer
merge attempted today would have essentially no automated safety net.** Writing a headless
Tk smoke test — instantiate each View against a fixture bundle, click Run, assert the
resulting `full_rows` — before touching the Views is the single highest-leverage
preparatory step.

### 5.5 The golden-file mechanism

**What byte-identity actually guarantees.** Five goldens lock the exact bytes of a produced
CSV:

| Golden | Locked artefact | Test |
|---|---|---|
| `criteria_harmonized_v3.1.0.csv` | Plugin 03's criteria table | `test_harmoniser_regression.py` |
| `eh_filtered_v3.1.0.csv` (776 rows) | `EH_FULL` report | `test_eh_regression.py` |
| `ih_filtered_v3.1.0.csv` (776 rows) | `IH_FULL` report | `test_ih_regression.py` |
| `el_filtered_v3.1.0.csv` (85 rows) | `EL_FULL` report | `test_el_regression.py` |
| `il_filtered_v3.1.0.csv` (84 rows) | `IL_FULL` report | `test_il_regression.py` |

Plus two *inputs* (`el_input`, `il_input`) and two *replay caches* (`el_cache`,
`il_cache`). Byte-identity therefore pins: per-criterion outcome assignment, survivor
selection (derivable from `outcome != "OUT"`), reason-summary wording, the full evidence
JSON, column order, CSV quoting, and line terminators. Any behaviour drift anywhere in the
engine surfaces as a diff.

**The offline replay trick, and why it is sound.** `test_el_regression.py` unsets
`OPENAI_API_KEY` before invoking `run_el_screen`, then supplies `el_cache_v3.1.0.json` as
`cache_in`. With no key, `_has_openai_key()` returns False and `run_m1_llm_for_criterion`
returns `{}` immediately (`llm_client.py:161-163`). Every `(a_id, criterion_id)` pair must
therefore resolve from cache; a miss yields empty evidence, which flips the row's outcome
to `PASS_FLAGGED` and breaks byte-identity loudly. This is a genuinely good design — it
makes an LLM-dependent stage deterministically testable with zero network and zero cost.

**Regeneration.** `tools/capture_el_il_goldens.py`, run once with a live key, overwrites all
six EL/IL fixtures. Its docstring instructs the operator to inspect the diff before
committing. The cache JSON carries an `_invocation` envelope so the tests replay with the
same parameters that produced it.

**Caveat worth recording: the goldens are captured at non-default settings.**
`capture_el_il_goldens.py:68-70` sets `MODEL = "gpt-4o-mini"`, `TRUNC_CHARS = 4000`,
`BATCH_SIZE = 5`. The application defaults are `TRUNC_CHARS = 1500` and `BATCH_SIZE = 50`
(`06_el/plugin.py:38-39`). Since `trunc_chars` participates in both the cache key and the
quote-validation window, the regression suite locks a configuration **no user runs by
default**. The truncation-boundary behaviour on the default path is untested.

**CRLF protection.** `.gitattributes:4` sets `tests/golden/** binary`, which disables
`core.autocrlf` rewriting for those paths. This is load-bearing, and it is doing real work:
`criteria_harmonized_v3.1.0.csv` is **CRLF-terminated** (Python's `csv.writer` default) while
`eh_filtered`/`el_filtered` are **LF-only** (`_common/exporters._write_csv_bytes` sets
`lineterminator="\n"` explicitly). Without the `binary` attribute, a Windows checkout would
rewrite the LF goldens to CRLF and every byte-identity test would fail on clone. Verified by
byte inspection of the archived files.

*(Side note: the same LF/CRLF split exists inside a produced bundle — EH/IH reports are LF,
EL/IL reports and the criteria CSV are CRLF, because `06_el/screen.py:155` `_write_csv` and
the EL/IL bundle writers use `csv` defaults. Harmless for consumers, untidy for a project
that advertises byte-level reproducibility.)*

### 5.6 CI matrix assessment

`.github/workflows/test.yml`: `{ubuntu-22.04, ubuntu-24.04, macos-14, windows-latest} ×
{3.10, 3.11, 3.12, 3.13}` = **16 cells**, `fail-fast: false`, 10-minute timeout, running
`pip install -e ".[dev]"`, then pytest, then the two audits.

**Appropriateness: broadly yes, with three gaps.**

*What it catches well.* The four-OS spread is exactly right for this codebase, because the
two things most likely to break cross-platform are line endings in the goldens and
filesystem-path handling — and both are exercised on every cell. The 3.10 floor matches
`requires-python`. Two Ubuntu LTS versions is generous but cheap.

*Gap 1 — the matrix cannot catch what has no test.* Sixteen cells running a suite that never
touches `plugins/02_references_of_x/` (1,984 statements) or any View means sixteen
identical green ticks that say nothing about those 8,000+ lines. Breadth is substituting
for depth.

*Gap 2 — no encoding/mojibake gate, by explicit choice.* The workflow's header comment says
so: *"No mojibake sweep in this workflow: that's a Windows-PowerShell pattern … Mojibake
protection lives in the local pre-commit gates only."* That local gate demonstrably did not
hold — see §7.2, where the most recent commit reintroduced both a BOM and 27 mojibake
sequences into `README.md`. A three-line Python step would run identically on all four
runners.

*Gap 3 — no dependency pinning, so the matrix tests a moving target.* See §7.5. My fresh
install of the unpinned `requirements.txt` today resolved to `pandas 3.0.5`, `numpy 2.4.6`,
and `openai 2.53.0` — all major versions ahead of what the project was presumably developed
against. CI installs the same moving target on every run, so a green tick today and a green
tick in six months are not the same claim.

*Platform-specific behaviour the matrix would **not** catch:*

- **Tkinter is never instantiated.** No cell creates a `Tk()` root. All GUI code is
  import-checked only, so platform-specific widget behaviour (macOS menu handling, Windows
  DPI scaling, Linux missing `python3-tk`) is invisible to CI. `Dockerfile` installs
  `python3-tk` for importability; the CI runners get whatever `actions/setup-python` ships.
- **The PyInstaller specs are never built.** No cell runs `pyinstaller`. See §7.6.
- **Non-UTF-8 input handling** (§6.8) is never exercised on any platform.
- **`datetime.utcnow()`** is deprecated from Python 3.12 and used in six places. The 3.12
  and 3.13 cells will surface `DeprecationWarning` only if warnings are made errors, which
  they are not. This is a scheduled future break the matrix is currently blind to.

---

## Phase 6 — Correctness and robustness

### 6.1 Error handling

Repo-wide AST sweep of every `except` clause that is bare or catches `Exception`:

**183 broad handlers. Zero bare `except:`. 37 have a `pass`-only body. 114 emit no
`raise`, log, print, user-visible message, or collection into a warnings/skipped list.**

That "zero bare `except:`" is worth stating plainly — it is better hygiene than most
codebases of this size. The problem is the volume of `except Exception: pass`.

Distribution:

| File | Broad handlers |
|---|---:|
| `plugins/02_references_of_x/services.py` | 25 |
| `plugins/07_il/ui.py` | 17 |
| `plugins/02_references_of_x/ui.py` | 16 |
| `plugins/06_el/ui.py` | 12 |
| `plugins/04_eh/ui.py` / `05_ih/ui.py` | 11 each |
| `plugins/01_.../prisma_citations_ai_v3_1.py` | 10 |
| `metascreener/main.py` | 9 |
| `plugins/_common/parser.py` | 7 |
| `plugins/_common/llm_client.py` | 6 |
| `plugins/03_harmoniser/ui.py` | 6 |
| others | ≤5 each |

**Handlers that can silently drop or void a record — ranked by consequence:**

| Path | Line | Behaviour | Consequence |
|---|---|---|---|
| `plugins/02_references_of_x/services.py` | 122 + 131 | `pd.read_csv(path)` (no `encoding=`) fails → logged → fall back to `open(path, encoding="utf-8")` → fails again on the same file → logged → `rows` stays `[]` | **The entire corpus silently becomes empty.** A cp1252/Latin-1 CSV — routine from Windows-based reference managers — produces zero records with nothing but two log lines. Contrast `_common/parser._decode_bytes:215`, which tries four encodings. |
| `plugins/02_references_of_x/services.py` | 1334 | Semantic Scholar request fails → `cached = {}` | A network error is indistinguishable from "this paper has no references". Silent under-collection of the corpus. |
| `plugins/02_references_of_x/services.py` | 951 | `except Exception: continue` inside the abstract-scraping loop | Abstract left empty; downstream EL/IL then mark the record `MISSING` for every abstract-targeted criterion → `PASS_FLAGGED`. Fails safe, but the cause is invisible. |
| `plugins/_common/parser.py` | 336 | `_load_input_errors_from_text` returns `[]` on any exception | Combined with the schema fracture in `01_architecture.md` §3.4, upstream dropped-record provenance is lost with no signal. |
| `plugins/_common/runner.py` | 101, 119 | `if cancel_event.is_set(): break` | Not an exception handler, but the same class of defect: a cancelled EH/IH run leaves `full_rows`/`survivors` **silently truncated** with no marker in the output. If the user then exports, the bundle looks like a complete run over a smaller corpus. Same pattern at `06_el/screen.py:430,511` and the IL twin. |
| `metascreener/main.py` | 29-30, 44-45 | `.env` read/write failures swallowed | User checks "Remember", the write fails (read-only dir, permissions), no feedback. |
| `metascreener/main.py` | 137, 153, 169, 193 | Plugin build failures `print()`ed to stdout | In a windowed PyInstaller build (`console=False`) stdout goes nowhere. **A plugin that fails to load produces a silently missing tab.** |

**The `PASS_FLAGGED` design mitigates most of this well.** Inside the screening engines,
essentially every failure path routes to "uncertain" and therefore to human review, not to
exclusion. `llm_client.py:290-303` explicitly back-fills an `used: False, uncertain` entry
for every item in a batch that produced no response, and `llm_client.py:357-370` does the
same after a terminal batch failure. That is the right instinct, consistently applied. The
risk concentrates in Plugin 02 (before the safety net exists) and in cancellation handling.

### 6.2 Evidence gating

**Implementation.** Two independent conditions, combined at `plugins/06_el/screen.py:547`
(and `07_il/screen.py:549`):

```python
usable = valid_quote and (confidence >= float(c.threshold)) and (decision in {"meet","not_meet"})
```

`valid_quote` is computed earlier, at the point of response parsing
(`_common/llm_client.py:273-277`):

```python
fld_txt = (idx_map.get(a_id) or {}).get(field) or ""
fld_txt_prompt = (fld_txt[:cur_trunc] if cur_trunc and len(fld_txt) > cur_trunc else fld_txt)
valid_quote = _quote_in_text(quote, fld_txt_prompt)
```

and `_quote_in_text` (`llm_client.py:58-70`) is:

```python
if quote in text: return True
qn = _normalize_space(quote); tn = _normalize_space(text)
return bool(qn) and (qn in tn)
```

**How the substring check is performed.** Exact substring first; on failure, both sides are
whitespace-collapsed (`re.sub(r"\s+", " ", s).strip()`) and retried. It is **not**
case-folded, **not** Unicode-normalised (no NFC/NFKC), and does no punctuation folding.

**Assessment.**

*Correct and important:* validation is against **the truncated text actually sent to the
model** for that specific call, not the full field. Because the adaptive-retry logic can
lower `cur_trunc` mid-batch (`llm_client.py:345-351`), this matters — validating against
the full field would let a model "quote" text it was never shown. The code gets this right.

*Whitespace variation:* handled. Newlines, tabs, and runs of spaces between the quote and
the source all pass.

*Unicode variation: fails closed.* A model that returns `"café"` in NFD when the source has
NFC, or normalises `—` to `-`, or straightens a curly apostrophe, produces
`valid_quote = False` → the record is flagged for a human. **This is the safe direction**,
but it is also a silent quality tax: on a corpus with mixed-encoding abstracts, the flagged
rate rises for reasons unrelated to the criterion. Two lines
(`unicodedata.normalize("NFKC", …)` on both sides before the second comparison) would remove
that noise without weakening the gate.

*Case: fails closed.* Same analysis.

**Can a malformed or adversarial response get past the gate?** I traced every field:

| Attack | Outcome |
|---|---|
| Unknown/invented `a_id` | Dropped — `llm_client.py:251` `if not a_id or a_id not in idx_map: continue`. Note the item is then back-filled as uncertain by lines 290-303, so it cannot vanish. |
| `decision` outside the enum | Coerced to `"uncertain"` (line 255-256) → fails the gate. |
| `confidence` non-numeric, negative, or > 1 | `float()` in try/except → 0.0 on failure; then `min(1.0, max(0.0, …))` (259-262). Cannot exceed 1.0. |
| `field` outside `{title, abstract, keywords}` | Coerced to `"abstract"` (264-266) — so the quote is then validated against the abstract. A model naming a bogus field gets its quote checked against the wrong text, which almost always fails → flagged. Safe. |
| Fabricated quote | Caught by the substring check. **This is the load-bearing defence and it holds.** |
| Quote that is a trivially-present substring (`"the"`, `" "`, `"a"`) | **Passes.** There is no minimum-length or minimum-informativeness requirement on the quote. A model that returns `decision:"meet", confidence:0.95, quote:"the"` clears the gate. This is the one real hole. |
| Empty quote | Rejected — `_quote_in_text` returns False on empty (line 64-65). |
| `span` malformed | Zeroed to `None` (269-271); `span` is never used in the gate, only recorded. |
| Response not JSON at all | `_parse_llm_json_array` returns `[]` → all items back-filled uncertain → flagged. |
| Response wrapped in prose or a fenced block | Handled: fence stripping (92-94) and first-`[…]`-block extraction (105-112). |
| Extra/unknown keys | Ignored. |

**Verdict.** The gate is well constructed and the adversarial surface is narrower than one
would expect. The single substantive weakness is that quote *presence* is checked but quote
*substance* is not — a one-character quote validates. A minimum length (say, 20 normalised
characters, or a requirement that the quote contain at least one token from the criterion's
`what` list) would close it. Note this is not hypothetical for local open-weight models,
which the README explicitly invites (`README.md:307-328`) while noting that "open-weight
model compatibility with the evidence gating protocol … has not been formally tested".

### 6.3 LLM interaction

All in `plugins/_common/llm_client.py:123-375`.

| Aspect | Implementation | Assessment |
|---|---|---|
| **Client construction** | `OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))`, line 167 | **`base_url` is never passed.** The client picks up `OPENAI_BASE_URL` from the environment via the SDK's own default, which is how the documented local-provider path works — but it is implicit and undocumented in the code. |
| **Timeout** | Not set | Falls back to the SDK default (600 s at the time of writing). A hung endpoint blocks a worker thread for ten minutes with no UI feedback beyond the last progress event. |
| **Retries** | Not set at the client level | The SDK's own `max_retries` (default 2) applies to transport errors, *invisibly to this code's logging*. |
| **`max_tokens`** | Not set | A large batch can exceed the model's output limit; the response is truncated mid-JSON, `_parse_llm_json_array` returns `[]`, and **the whole batch is back-filled as uncertain**. No detection, no retry with a smaller batch — because the truncation does not raise. This is the most likely silent-quality failure in normal operation. |
| **Rate limiting** | Reactive only. On an error whose text matches `429` / "too many requests" / "rate…limit", the batch is halved and the remainder requeued immediately after it (lines 325-339), with `time.sleep(min(4.0, 0.4 * attempts))`. | No proactive throttle, no jitter, no `Retry-After` parsing. Halving is a reasonable heuristic. **The retry loop is unbounded**: `while True` with no attempt cap. Termination is guaranteed only because the split path requires `len(cur_batch) > 1` and the truncation path requires `cur_trunc > 600` — once a batch is a single item at trunc 600, the next error falls through to the terminal handler. Correct, but by construction rather than by an explicit bound. |
| **Truncation of long records** | `trunc_chars` (default 1500) applied per field, in the prompt builder (`prompt.py:53-57`) and again for hash and quote validation | Consistent. Adaptive reduction to a floor of 600 on error (line 345-346). |
| **Malformed JSON** | Three-tier parse: direct, fence-stripped, first-`[…]`-block regex (lines 83-113) | Robust. Failure degrades to `[]`, i.e. to flagged. |
| **API unreachable mid-run** | Each batch fails terminally, all its items marked uncertain with an `"error"` key (357-370), loop continues to the next batch | **Progress is preserved.** The run completes; every unreachable record is flagged rather than lost. Good. |
| **Missing API key** | Detected up front (161-163), returns `{}` immediately | This is what makes the offline golden replay work. |
| **Cancellation** | `_check_cancel()` (172-176) raises `RuntimeError("Cancelled")`, which propagates out of `run_m1_llm_for_criterion` | **Partial LLM results collected so far in `out` are discarded** — the exception unwinds past the `return out`. The caller in `screen.py` never gets them, so the cache is not updated with responses already paid for. Cancelling a long run wastes every API call made since the last criterion boundary. |

**Is partial progress preserved?** Two different answers. For *API failures*: yes, fully.
For *user cancellation*: no — see the row above, plus `screen.py:430,511` which truncate
`full_rows` without marking the output as partial.

*Addendum (wave 6): three items in §6.3 have been overtaken, and one coordinate has rotted.*

- **The `Cancellation` row is pre-F-26 and is now false.** It describes
  `_check_cancel()` raising a bare `RuntimeError("Cancelled")` that unwinds past `return out`,
  discarding paid-for results. At HEAD there is a dedicated
  `plugins/_common/llm_client.py::_Cancelled` whose docstring names F-26; the per-batch retry
  block guards it with an explicit `except _Cancelled: raise` *ahead of* the generic handler;
  and the batch loop catches it, logs how many batches completed, and falls through to
  `return out`. **Partial results are retained.** F-26's own register row records the worse
  half the original assessment missed — the generic handler was not merely discarding the
  results but rewriting the in-flight batch as fabricated `uncertain` verdicts.
- **The "Is partial progress preserved?" paragraph is stale in both halves.** The cancellation
  half is above; and the `screen.py` truncation it cites is closed by F-02 —
  `plugins/06_el/screen.py::run_el_screen` now returns a `cancelled` flag and the stage UIs
  refuse to export while it is set.
- **The `Client construction` row is right and its coordinate is wrong.** `base_url` is
  still never passed and the SDK's own `OPENAI_BASE_URL` fallback is still what makes the
  documented local path work — confirmed in wave 6 against installed SDK source. Only the
  line number is stale: the factory is `plugins/_common/llm_client.py::_openai_client_for`.
  The assessment stands unaltered, and is now carried as F-89, F-91, F-92 and F-127. The
  section preamble ("All in `plugins/_common/llm_client.py:123-375`") is stale for the same
  reason and additionally excludes the client factory, which sits outside that range.

*(The `Timeout` row is not listed here because it hedges correctly — "600 s at the time of
writing". Wave 6 sharpens rather than corrects it: the SDK also defaults `max_retries=2`, so
the true bound is 3 × 600 s. See F-25.)*

### 6.4 The response cache

**Key derivation** (`llm_client.py:397-414`):

```
sha256(f"{prompt_version}|{model}|{cid}|{a_id}|{text_hash}|{trunc_chars}"
       + (f"|temp={temperature}" if temperature != 0.0 else ""))
```

where `text_hash = sha256` of the record's target-field texts, each truncated to
`trunc_chars`, joined by `|` (`llm_client.py:388-395`; EL/IL use the local equivalent
`row_text_hash` at `screen.py:395-402`).

**Invalidation coverage:**

| Parameter changes | Cache invalidated? | Correct? |
|---|---|---|
| Prompt template / `PROMPT_VERSION` | ✅ (operator must bump it manually) | Yes, and `test_el_regression`/`test_il_regression` assert the literal so a bump is deliberate. |
| Model id | ✅ | Yes |
| Record text | ✅ via `text_hash` | Yes |
| `trunc_chars` | ✅ | Yes |
| Temperature, 0.0 → non-zero | ✅ | Yes — added in `8e7d521` / `dce0352`, tested by `TestTemperatureCacheInvalidation`. |
| Temperature between two non-zero values | ✅ | Yes |
| Confidence threshold | ➖ not in key | **Correct by design** — the threshold is applied at scoring time (`screen.py:547`), not baked into the cached evidence. |
| `batch_size` | ➖ not in key | Correct — batching does not change per-item semantics. |
| **Criterion wording** (`what`, `label`, `source_text`, `type`, `operator`, `target`) | ❌ **not in key** | **No — this is a defect.** |

**The criterion-content gap.** Only the criterion *identifier* `cid` enters the key. But the
prompt carries the criterion's full content: `screen.py:434-443` builds `crit_pack` from
`c.ctype`, `c.operator`, `c.targets`, `c.what_list`, `c.label`/`c.source_text`, and
`c.threshold`, and `prompt.py:42-51` serialises all of it into the user message.

Consequence: a researcher who refines the wording of `IC-1` in the Harmoniser — the single
most likely edit during a real review — and re-runs EL/IL **gets the previous criterion's
LLM answers back from cache, verbatim, with no warning.** The evidence JSON will show a
quote and a decision that were produced against different criterion text. This is a
reproducibility *and* a correctness failure, and it is invisible: the UI reports
`cache_hits=N` and everything looks normal.

The fix is small and backward-compatible in spirit but not in bytes: hash the serialised
`crit_pack` into the key. It **will** invalidate the committed EL/IL cache goldens and
require a re-capture, which is presumably why it has not been done. That trade-off should be
made explicitly rather than by omission.

*Addendum (wave 6, F-01): everything above in §6.4 from the key-derivation block to this
paragraph describes the pre-F-01 cache and has been superseded. It was done.*

The key is now `plugins/_common/llm_client.py::_cache_key`, taking
`(prompt_version, model, rendered_prompt, temperature)` and hashing a sorted-key JSON object
of exactly those four fields. Four differences from the block above: the enumerated
`cid`, `a_id`, `text_hash` and `trunc_chars` are **gone from the key entirely**, replaced by
the whole rendered prompt — so criterion wording, record text, targets and truncation reach
the key without being named; `temperature` is now hashed unconditionally, so the
`if temperature != 0.0` suffix trick is gone; the payload is canonical JSON rather than a
pipe-joined f-string; and the stage wrappers `plugins/06_el/screen.py::_cache_key` and its IL
twin render a one-item prompt and delegate. The function's own docstring states the
principle: *"Enumeration was itself the bug."*

Three consequences for the text above, so no part of this section is left self-contradicting:
the **Invalidation coverage** table's last row (*Criterion wording … ❌ not in key … No —
this is a defect*) is now ✅ and correct; the **criterion-content gap** paragraph and its
consequence no longer describe the software; and "which is presumably why it has not been
done" is answered — it was done, and the predicted re-capture is recorded in
`CHANGELOG.md` [Unreleased]. Two rows of that same table need a wave-6 footnote rather than a
reversal: `batch_size` is "not in key" and the assessment "batching does not change per-item
semantics" is **no longer safe** (F-101, and F-86 is the reason); and the *threshold* row's
"correct by design" now has a rival consideration, since the threshold is also injected into
the prompt (F-100). The `screen.py:547` coordinate it cites for the scoring-time application
is stale — the gate is the `usable = …` line in `plugins/06_el/screen.py::run_el_screen`.

What §6.4 records below this addendum — the two stages' symmetry, the corrupt-cache failure
ladder, and the absence of a size bound, eviction or schema version — is **unaffected and
still true**. The corrupt-cache observation is F-33; the missing round-trip test for the
on-disk format it describes is F-103.

**Consistency across the two stages:** the mechanism is identical. `06_el/screen.py:321-328`
and `07_il/screen.py:323-330` are byte-identical stage-curried wrappers over the same shared
`_cache_key`, differing only in the `PROMPT_VERSION` they bake in. The temperature handling
is complete and consistent in both. No asymmetry found.

**Corrupt cache file.** `_load_cache_from_jsonl` (`llm_client.py:416-430`) parses line by
line inside a `try/except: continue`. A truncated or corrupted line is skipped; a corrupted
*value* that is still valid JSON but not a dict is skipped (`isinstance(v, dict)` guard).
**Corruption therefore degrades to a cache miss, which degrades to a live API call, which
degrades to flagged if there is no key.** That is the right failure ladder. What is missing
is any *report*: the user is told `cache_hits=N` but never that M lines were unreadable.

There is no cache size bound, no eviction, and no schema version inside the JSONL — the
`_invocation` envelope exists only in the golden capture format, not in the bundle's
`cache/*.jsonl`.

### 6.5 Determinism and reproducibility

The project claims exact re-runs (`README.md:81`: *"enabling exact re-runs without
additional API cost"*). Audit:

| Source of nondeterminism | Present? | Detail |
|---|---|---|
| **LLM sampling** | Yes, unavoidable | `temperature=0.0` default (`llm_client.py:138`), and the docstring at lines 150-155 is admirably honest: *"strict determinism is not guaranteed even at 0.0 due to hardware-level floating-point non-determinism in model inference; the cache layer … is the primary reproducibility safeguard."* Correct framing. |
| **Cache stale-on-criterion-edit** | Yes — §6.4 | The one place where the cache actively *breaks* reproducibility rather than guaranteeing it. |
| **Iteration order** | No | Every set is used for membership only. `_detect_contradictions_simple:446` sorts before emitting. `_dump_cache_to_jsonl` iterates a dict in insertion order, which is deterministic given a deterministic build order. `discover()` uses `sorted(root.iterdir())`. Criteria and rows preserve file order throughout. |
| **Floating point** | Negligible | The only comparison is `confidence >= float(c.threshold)`. Both sides come from decimal literals with exact `float()` round-trips (`"0.60"` → the same double as `0.6`). No accumulation, no summation. |
| **Timestamps in outputs** | **Yes, in the manifest** | `_common/bundle.py:200` `m["created_at"] = datetime.now()…` — *local* time, no timezone marker, and inconsistent with `_iso_now()` (UTC + `Z`) used two lines earlier in the same function for `history[].ran_at`. Also `06_el/ui.py:997` `updated_at`. The **report CSVs contain no timestamps**, which is why byte-identity testing is possible at all. |
| **Paths in outputs** | **Yes** | `_common/bundle.py:204` writes `m["derived_from"]["zip_name"] = Path(src_zip).name` — a user's local filename lands in the published manifest. Also `manifest.inputs.aggregate_filename` / `criteria_filename` from Plugin 03. Basenames only, not full paths, so no directory leakage. |
| **ZIP container bytes** | Yes | `zipfile` stores per-entry mtimes; two bundles built from identical content have different bytes. Only the *contents* are reproducible. |
| **Default export filenames** | Yes, by design | `_now_stamp()` in `ScreenA_Bundle_EH_{stamp}.zip` etc. |

*Addendum (wave 4a, F-76):* the EH/IH parser canonicalises `CRLF` and lone `CR`
inside quoted metadata to `LF` (`_common/parser.py`, `_split_csv_records`) — so
pass-through fields are CR-normalised rather than byte-identical to the ingested
corpus. Kept by decision Q-A, documented in `docs/usage.md`, and pinned by
`tests/test_corpus_parser.py::TestCarriageReturnCanonicalisation`.

**Verdict.** The reproducibility claim is **substantially true for the artefacts that carry
the science** — the report CSVs are byte-reproducible, and the golden tests prove it on
every CI run across 16 platform cells. It is **not** true for the manifest or the ZIP
container, and it has one real hole (criterion-edit cache staleness). The README's phrasing
("exact re-runs") is defensible; a reviewer who diffed two bundle ZIPs and found them
different would be looking at timestamps, not at drift, and the documentation does not say
so anywhere.

*Addendum (wave 6, F-01): the "one real hole" is closed, and two larger ones were found.*

The **Cache stale-on-criterion-edit** row of the table above, and the Verdict's "it has one
real hole (criterion-edit cache staleness)", both inherit §6.4's pre-F-01 description. That
hole is closed; the key now covers everything the model is shown. The Verdict's substantive
claim — that reproducibility is substantially true for the artefacts carrying the science,
and untrue for the manifest and the ZIP container — stands.

Two reproducibility defects found after this section was written are **not** covered by it,
and both sit on the same axis it audits. The key covers everything the model is *asked* and
records nothing about *who answers*: the endpoint is absent from the key, so one model name
served by two providers is one cache namespace (**F-89**), and no artefact anywhere records
which model, provider, temperature or prompt version produced a decision (**F-88**).
Separately, `.gitattributes` protects only `tests/golden/**`, so the corpus a re-capture
reads is `text: auto` and two maintainers at the same commit with different `core.autocrlf`
obtain different cache keys (**F-99**) — which makes the byte-for-byte regeneration claim a
statement about a working tree rather than about a commit.

### 6.6 Kappa computation — independently verified

I re-derived both statistics by hand and against published reference values.

**Cohen's kappa** (`tools/eval_ingest.py:502-532`): `p_o = Σ cm[i][i] / n`;
`p_e = Σ (row_i/n)(col_i/n)`; `κ = (p_o − p_e)/(1 − p_e)`. **Textbook-correct.**

```
Wikipedia 2×2 example (20/15 agree, 5/10 disagree):
  impl : n=50  p_o=0.7  p_e=0.5  kappa=0.4
  hand : n=50  p_o=0.700000  p_e=0.500000  kappa=0.400000     ✓
```

**Fleiss' kappa** (`lines 535-592`): `P_i = Σ n_ik(n_ik−1) / (n(n−1))` — algebraically
identical to the textbook `(Σ n_ik² − n)/(n(n−1))`; `P̄ = mean(P_i)`; `p_j` = category
proportions over all ratings; `P_e = Σ p_j²`; `κ = (P̄ − P_e)/(1 − P_e)`. **Textbook-correct.**

```
Fleiss (1971) 10 subjects × 14 raters × 5 categories:
  impl      : P_bar=0.378022  P_e=0.212755  kappa=0.209931
  published : P_bar=0.378     P_e=0.213     kappa=0.210        ✓
```

**Edge cases — all correct:**

| Case | Result | Correct? |
|---|---|---|
| Empty input (Cohen and Fleiss) | all NaN | ✓ |
| Perfect agreement, ≥2 categories used | κ = 1.0 | ✓ |
| **Single category / zero marginals** | `p_e == 1.0` → κ = NaN | ✓ κ is genuinely undefined here; returning NaN rather than dividing by zero is the right call |
| Total disagreement, 2 categories | κ = −1.0 | ✓ |
| Fleiss, unequal rater counts per item | `ValueError` | ✓ |
| Fleiss, fewer than 2 raters | `ValueError` | ✓ |

**One real defect found — latent, not currently triggered.**

`_confusion_matrix` (line 496-498) skips any pair whose labels are outside
`CANONICAL_DECISIONS = ("yes", "no", "unsure")`, while `cohen_kappa` divides by
`n = len(pairs)` including the skipped ones. Demonstrated:

```
clean     : n=50  p_o=0.700000  p_e=0.500000  kappa=0.400000
+10 OOV   : n=60  p_o=0.583333  p_e=0.347222  kappa=0.361702
            (n grew to 60; the matrix still totals 50)
```

**And there is a live route to it.** `majority_vote` (`eval_ingest.py:599-607`) returns the
string **`"uncertain"`** on a tie or an empty list — but the canonical vocabulary is
`("yes", "no", "unsure")`. `"uncertain"` ∉ `CANONICAL_DECISIONS`. Every tied overlap item
therefore produces a pair the confusion matrix drops but `n` counts, silently deflating both
`p_o` and `p_e` and yielding a wrong kappa.

**Are the published numbers affected? No — verified.** I parsed
`docs/data/eval_summary_v1.txt` and compared each reported `N` against the total of its
reported 3×3 confusion matrix, and independently recomputed ties from
`docs/data/eval_decisions_v1.csv`:

```
stage/criterion                    N matrixSum     gap    kappa
EL/EC-2                           85        85       0  -0.0466
EL/EC-3                           85        85       0   0.1010
IL/IC-1                           84        84       0   0.2775
TOTAL pairs counted in n but missing from the confusion matrices: 0

overlap items: 45   tied items (-> majority_vote returns 'uncertain'): 0
human_decision vocabulary: {'no': 228, 'yes': 78, 'unsure': 38}  (344 rows, matches docs/index.md)
```

So the validation study's published kappas are correct. The bug is dormant because no
overlap item happened to tie. **Any re-run with different raters, a different sample, or a
larger overlap set could silently corrupt the headline statistic of the validation study.**
Fix: change `"uncertain"` → `"unsure"` at `eval_ingest.py:602` and `:606`, and make
`cohen_kappa` either raise or count only matrix-resident pairs. Two lines plus a guard.

### 6.7 Input validation

| Input | Behaviour | Assessment |
|---|---|---|
| **Malformed CSV (wrong column count)** | Plugin 03 `_clean_aggregate_csv:139` drops the row into `input_errors.csv`; `_common/parser._parse_csv_tolerant_text:302` skips with `bad_column_count:N!=expected:M`; **EL/IL `_csv_read:151` pads short rows with `""` and keeps them** | Three different policies for the same condition. EL/IL are the permissive outlier — a truncated row survives into LLM screening with silently empty fields. |
| **Embedded newlines in quoted fields** | `_split_csv_records:228-267` hand-rolls a quote-aware splitter | Correct, and necessary: the 776-record sample corpus is 2,096 physical lines. |
| **Wrong encoding** | `_common/parser._decode_bytes:215` tries `utf-8-sig, utf-8, cp1252, latin-1`; **EL/IL `screen.py:109` do `utf-8-sig` with `errors="replace"` only** | The `latin-1` terminal fallback never raises, so *any* byte sequence decodes to *something* — mojibake enters silently with no warning. In EL/IL, non-UTF-8 becomes U+FFFD, which then breaks quote validation for those records → flagged. Fails safe but silently. |
| **Empty criteria file** | `_load_criteria_from_text:360-361` returns a warning "Criteria header not found."; `runner.py:99-115` then assigns **`PASS_CLEAN` to every record** with reason "No active EH criteria: default PASS_CLEAN." | Defensible (nothing to exclude on) and it is surfaced in the reason column — but a stage silently passing 100% of records deserves a modal warning, not a log line. |
| **Missing columns** | `_eval_criterion:74-75` returns `MISSING` if no target column exists → `PASS_FLAGGED` | Correct fail-safe. |
| **Missing `local_id`** | `parser.py:308-311` skips to `input_errors`; `06_el/screen.py:196-217` tries fallbacks (`id`, `ID`, `LocalID`, `localId`) then skips, and also drops **duplicate** `local_id` | EL/IL are stricter here than EH/IH, which do not check for duplicates at all. A corpus with duplicate ids screens fine through EH/IH and loses rows at EL. |
| **Tampered bundle** | `04_eh/ui.py:406-417` warn-only SHA-256 check; **EL/IL do not check at all** | See `01_architecture.md` §3.4. |
| **Bundle missing a required member** | `_load_bundle` raises `FileNotFoundError` with a clear message for `manifest.json`, `data/current.csv`, `criteria/criteria_harmonized.csv` | Good. |
| **`manifest.json` not JSON / not an object** | `ValueError` with the parse error attached | Good. |
| **Non-`.zip` path** | `ValueError("Bundle must be a .zip file.")` — an extension check, not a magic-number check | A renamed file raises `zipfile.BadZipFile` instead, which is uncaught in some paths. Minor. |
| **API key format** | `api_key_dialog.py:112`: `key.startswith("sk-") and len(key) >= 20` | **Contradicts the documented local-provider workflow.** `README.md:318,322` instructs users to set `OPENAI_API_KEY=ollama` or `llama-cpp`; the dialog rejects both, and `main.py:76-91` shows the dialog on **every** launch and refuses to continue without a value it accepts. As written, the Ollama/llama.cpp/vLLM paths documented across `README.md:307-328` cannot be used through the GUI. |

### 6.8 Portability

**Paths.** Clean. No hardcoded drive letters or backslash literals outside regexes and
docstrings (verified by sweep). `pathlib` and `os.path.join` used throughout. ZIP member
names are built by string concatenation with forward slashes, which is the ZIP spec's
requirement — correct on all platforms. The hardcoded developer venv path was removed from
the spec files in 3.1.0 (`CHANGELOG.md:72`) and does not recur.

**Encoding.** Every `open()` in `plugins/`, `metascreener/`, and `tools/` passes an explicit
`encoding=` except genuinely binary calls (`fitz.open`, `Image.open`) — good discipline.
The gaps are behavioural rather than syntactic:

- `services.py:118` `pd.read_csv(path)` with no `encoding` (§6.1).
- `services.py:127` fallback `open(path, "r", encoding="utf-8")` — not `utf-8-sig`, so a
  BOM'd CSV yields a first column named `﻿title` and every `r.get("title")` returns
  `""`. Silent field loss on a very common Windows input.
- The `latin-1` terminal fallback in `_decode_bytes` guarantees no exception and therefore
  guarantees silent mojibake on non-UTF-8 input.

**Line endings.** Two conventions coexist (§5.5). Both are platform-independent (Python's
`csv` writes `\r\n` by default regardless of OS, and `_write_csv_bytes` forces `\n`), so
outputs do **not** vary by platform — but the mix is untidy for a byte-reproducibility
claim.

**Deprecations.** `datetime.utcnow()` at `_common/parser.py:137`,
`02_references_of_x/core.py:88`, `06_el/ui.py:997`, `06_el/standalone.py:406`,
`07_il/ui.py:1240`, `07_il/standalone.py:406`. Deprecated since Python 3.12. Currently
harmless; a scheduled break.

---

## Phase 7 — Documentation, packaging, hygiene

### 7.1 Reference integrity

I checked **139 file references** across `README.md`, `CHANGELOG.md`, `CITATION.cff`, and
all five `docs/*.md` — every markdown `[…]` + `(…)` link plus every backticked path-like token.

**All markdown links resolve. Zero broken `[…]` + `(…)` links.** That is a good result and worth
protecting; `test_metadata.py::test_internal_markdown_links_resolve` is what keeps it true.

Genuinely broken *prose* references (excluding backticked tokens that legitimately name
bundle-internal paths like `manifest.json` or `data/current.csv`):

| Location | Reference | Problem |
|---|---|---|
| `CHANGELOG.md:35` | `docs/internal/reviewer-response-map.md` | **File does not exist.** Announced under "Added" in the 3.1.0 release notes. Almost certainly deleted because `test_every_doc_listed_in_index` (§5.2) would fail on it. |
| `docs/usage.md:206` | `reports/eh_decisions.csv` | **Never produced.** The real names are `reports/EH_FULL.csv` and `reports/EH_SURVIVORS.csv`. |
| `docs/usage.md:234` | `reports/ih_decisions.csv` | Same — real names `IH_FULL.csv` / `IH_SURVIVORS.csv`. |
| `docs/usage.md:269` | `reports/el_decisions.csv` | Same — real names `EL_FULL.csv` / `EL_SURVIVORS.csv`. |

Verified: the string `decisions.csv` appears nowhere in the plugin code; the only
`write_decisions_csv` is in `tools/eval_ingest.py` and produces `eval_decisions_v1.csv`, an
unrelated validation-study artefact. So the usage guide instructs a first-time user to look
for three files that do not exist, in the three places they most need to look.

### 7.2 Encoding audit

**BOM sweep — every tracked file, byte-level:**

| File | BOM |
|---|---|
| `README.md` | **UTF-8 BOM (`EF BB BF`)** |
| `LICENSE` | **UTF-8 BOM** |
| all 121 other tracked files | none |

**Mojibake sweep — `â€`, `Ã©`, `Â `, and related Latin-1-decoded-UTF-8 signatures across
every tracked text file:**

| File | Sequences | Lines affected |
|---|---:|---|
| `README.md` | **27** (25 × `â€`, 2 × `Ã©`) | 17, 21, 25, 33, 34, 52, 89, 90, 91, 92, 93, 101, 107, 111, 192, 194, 243, 244, 245, 299, 311, 312, 369, 411, 415 |
| everything else | **0** | — |

> **Correction (fix wave 0).** The signature list used for this sweep was too
> narrow. A structural re-scan — any of `Â`/`Ã`/`â`/`ð` followed by another
> non-ASCII character — finds **46 affected lines, not 25**: the original list
> missed the corrupted ASCII-art project tree (lines 336-353), the `⚠` warning
> glyph (51), `≥` (225), and `✅` (289). Content equivalence was then proved:
> the ASCII skeleton of `365325c^` plus the intended DOI edit is byte-identical to
> the ASCII skeleton of the corrupted `HEAD`, so the corruption touched only
> non-ASCII characters and the repair is exact. `tools/check_encoding.py` now
> encodes the structural rule.

The damage is confined to `README.md` but sits on the first screen: line 17 is the opening
sentence of the Overview, line 25 is the 776→73 headline, lines 89-93 are the bundle-format
list, lines 243-245 are the platform-compatibility table, and line 411 turns `Québec` into
`QuÃ©bec` in the acknowledgements.

**How it got reintroduced — identified.** I replayed every commit that touched `README.md`
and measured the BOM and the `â€` count at each:

```
commit    BOM       mojibake  date        subject
365325c   efbbbf    25        2026-05-11  docs: switch README DOI badge to concept DOI for stability
5801fb0   (none)     0        2026-05-10  docs: add docs/installation.md and docs/index.md
957cc63   (none)     0        2026-05-03  docs(readme): reconcile platform table + Testing section
81d4e0c   (none)     0        2026-05-03  docs: add local-model providers section to README
…
63ef1a1   —          —        2026-04-28  style: strip UTF-8 BOMs and translate inline comments
9597abf   efbbbf     0        2026-02-08  Initial commit
```

**Commit `365325c` — the single most recent commit on `main` — is the culprit**, and it is
unambiguous. Its stated purpose was to change one character in a DOI (`…19360125` →
`…19360124`). Its actual diff is **49 insertions / 49 deletions**: one line for the DOI, one
line adding the BOM, and 47 lines that changed only because every `—` became `â€"`.

The signature is exactly a read-as-cp1252 / write-as-UTF-8-with-BOM round trip. On Windows
PowerShell 5.1 that is the default behaviour of `Get-Content … | … | Set-Content` and of
`Out-File`, both of which write UTF-8 **with** BOM and read using the ANSI code page unless
told otherwise. `git show 365325c` displays the corruption plainly in the diff, so it was
committed without the diff being read.

Note the irony: `CHANGELOG.md:41` lists "Stripped UTF-8 BOMs from text files" as a 3.1.0
change (commit `63ef1a1`, 2026-04-28), and `.github/workflows/test.yml:15-18` explicitly
documents that mojibake protection was left to "local pre-commit gates only". The local gate
did not fire, and CI cannot.

`LICENSE`'s BOM predates all of this — it has carried one since the initial commit and was
missed by the 3.1.0 sweep.

### 7.3 README claims vs. the code and data

| Claim | Location | Verdict |
|---|---|---|
| Corpus of **776** candidate records | `README.md:25`, `:216` | ✅ Verified — `docs_/samples/20260122_1654_aggregate.csv` parses to exactly 776 records. |
| **90.6%** reduction | `README.md:25` | ✅ Arithmetically exact: (776 − 73)/776 = 90.593%. |
| **98.3%** of exclusions from deterministic pre-filtering | `README.md:25` | ✅ Consistent: EL's input is 85 records, so EH+IH removed 691 of 703 total exclusions = 98.29%. |
| Reduced **to 73** records | `README.md:25` | ⚠️ **Cannot be reproduced from the committed goldens.** The golden chain gives: EL in 85 → 1 `OUT` → 84 survivors; IL in 84 → 4 `OUT`, 80 `REVIEW` → **80 survivors**. Not 73. See below. |
| Default confidence threshold **0.6** | `README.md:81` | ✅ Verified in three places: `06_el/screen.py:278,280` (`thr = float(thr_s) if thr_s else 0.6`), `07_il/screen.py:280,282`, `prompt.py:50` (`criterion.get("threshold", 0.6)`), and the committed `tests/golden/criteria_harmonized_v3.1.0.csv` carries `0.60`. |
| **104** automated tests | `README.md:253,271` | ❌ Actual: **166**. The per-file table (lines 264-271) is accurate for the six files it lists but omits `test_eval_ingest.py` (32) and `test_eval_grid_generator.py` (27) entirely, and understates `test_metadata.py` as 2 (actual 5). 104 + 59 + 3 = 166. |
| "**Status: ✅ 73 passed**" | `README.md:289` | ❌ Actual: 166. This number is stale by two full refactor cycles — 73 was the count at commit `46c4174`. Note the unfortunate coincidence that "73" also appears as the funnel's final record count 264 lines earlier. |
| `SCREENA_EL_*` environment variables | `README.md:300-303` | ⚠️ Accurate but incomplete — the four `SCREENA_IL_*` equivalents (`07_il/plugin.py:44-47`) are undocumented. |
| Local-provider setup via `OPENAI_BASE_URL` + placeholder key | `README.md:307-328` | ❌ **Blocked by the code.** `api_key_dialog.py:112` requires `sk-` + length ≥ 20, and `main.py:62` makes the dialog unskippable. See §6.7. |
| "Bundles are integrity-verified … at ingestion and export" | `README.md:95` | ❌ True for stages 04–05 (warn-only), **false for 06–07**, which neither verify nor refresh SHA-256. See `01_architecture.md` §3.4. |
| Platform table: "Verified by CI", Python 3.10–3.13, four runners | `README.md:243-245` | ✅ Matches `.github/workflows/test.yml:37-38` exactly. |
| "Tested on Windows 10 and Ubuntu 24.04 (headless, via WSL/Docker)" | `README.md:287` | ⚠️ Sits directly below a paragraph claiming CI verification on four platforms; the two statements coexist awkwardly but neither is false. |

**On the 73-vs-80 discrepancy.** I am *not* asserting the README is wrong. The goldens were
captured at `TRUNC_CHARS = 4000, BATCH_SIZE = 5` (§5.5), which are not the defaults, and
`tools/capture_el_il_goldens.py` was run once against a live API — so the golden run and the
demonstration run reported in the manuscript may legitimately be different executions with
different settings. But as the repository stands, **the reproducibility evidence a reviewer
can actually run produces 80, and the README says 73**, with no note reconciling them. That
gap needs a one-sentence answer from the maintainer before submission. → Open Question Q1.

### 7.4 Dependency consistency

| Source | Contents |
|---|---|
| `requirements.txt` | 9 packages: `openai>=1.40.0`, `pymupdf`, `pillow`, `pytesseract`, `rapidfuzz`, `requests`, `pandas`, `openpyxl`, `langdetect` |
| `pyproject.toml:36-46` | **Identical 9 packages, identical constraints** |
| `pyproject.toml` `[dev]` | `pytest>=7.0`, `pytest-cov` |
| `Dockerfile:31` | `pip install -r requirements.txt pytest pytest-cov` — consistent |
| `.github/workflows/test.yml:48` | `pip install -e ".[dev]"` — consistent |

**Consistency: good.** No drift between the four sources.

**Pinning: the weak point, and it is a real one for this project specifically.**
Eight of nine runtime dependencies carry **no version constraint at all**. The ninth,
`openai>=1.40.0`, has a lower bound and no upper bound.

What that means in practice — this is what a fresh `pip install -r requirements.txt`
resolved to on 2026-08-08:

```
openai    2.53.0     ← the constraint says >=1.40.0; a MAJOR version boundary was crossed
pandas    3.0.5      ← pandas 3.x
numpy     2.4.6      ← numpy 2.x
openpyxl  3.1.5      pillow 12.3.0      pymupdf 1.28.2      rapidfuzz 3.14.5
```

For an ordinary application this is untidy. For a tool whose stated purpose is
*"satisfy[ing] the audit and reproducibility requirements expected in rigorous evidence
synthesis methodology"* (`.zenodo.json`), it is a contradiction: **the software cannot
reproduce its own dependency set.** A reviewer installing today, a reader installing in
2027, and the CI matrix on any given morning are all testing different software. The
byte-identity goldens — the project's strongest reproducibility asset — are guarded by a
suite running against an unpinned stack; if `openai` 3.x changes the response object shape,
the goldens will not catch it, because the golden tests deliberately bypass the API.

The remedy is standard and cheap: keep the loose ranges in `pyproject.toml` (correct for a
library), and add a `requirements.lock` (or `constraints.txt`) with fully pinned `==`
versions plus hashes, referenced from `docs/installation.md` and used by the Dockerfile and
by a dedicated "reproducible install" CI cell. Half a day.

### 7.5 PyInstaller specs and `hook-plugins.py`

Both specs are structurally current — `datas = [('plugins', 'plugins')]` matches the present
layout, `run.py` is the correct entry script, and the 3.1.0 rename left no stale paths. They
differ only in `name` and `console=True/False` (verified: those are the sole differences).

**Two problems, both structural:**

1. **`hook-plugins.py` is dead.** It exists to run `collect_submodules("plugins")` and feed
   the result into `hiddenimports`. Both specs set `hookspath=[]`
   (`metaScreener.spec:25`, `metaScreener-console.spec:25`), so PyInstaller never discovers
   the hook file. It has had no effect on any build.

2. **The third-party dependencies of the plugins are very likely not collected.** The
   `hiddenimports` list in both specs contains standard-library modules plus
   `metascreener.plugin_api`, and `collect_all()` is called for exactly four packages:
   `requests`, `urllib3`, `openai`, `fitz`. But the plugin sources import:

   ```
   openai (2×)   rapidfuzz (2×)   requests   pytesseract   pandas   fitz   langdetect   PIL
   ```
   plus `openpyxl` (lazily, at `_common/exporters.py:51`).

   `pandas`, `openpyxl`, `langdetect`, `rapidfuzz`, `PIL`, and `pytesseract` appear in
   neither `hiddenimports` nor any `collect_all`. And PyInstaller's static analyser cannot
   find them for itself, because `plugins/` is bundled as **data**, not as source it
   analyses — which is the whole premise of the custom loader. `hook-plugins.py` was
   evidently written to solve exactly this, and it is disabled.

   **Predicted consequence (inferred — I did not build):** in a frozen one-file build,
   Plugin 02 fails on `import pandas`, Plugins 04/05 fail on `from langdetect import …`,
   Plugin 01 fails on `from PIL import …`, and any XLSX export fails on `openpyxl`. Because
   `main.py:137` merely `print()`s the failure and `console=False` discards stdout, the user
   sees **tabs silently missing** with no error.

   This needs one build to confirm or refute. → Open Question Q2.

### 7.6 Docker

`Dockerfile` builds `python:3.12-slim-bookworm`, installs `python3-tk` and `tesseract-ocr`,
installs `requirements.txt` + pytest, copies the project, and runs the suite. `docker_test.sh`
wraps build + run and tees to `test_output_linux.txt`.

**Does it still work given a Tkinter GUI app? Yes — because it never starts the GUI.** The
CMD is `pytest tests/ -v --tb=short -s`, and the suite is headless by construction
(`test_imports.py` mocks the Tk surface via `conftest.py`'s `_FakeBasePlugin`). `python3-tk`
is installed for *importability*, not for display; there is no `DISPLAY`, no Xvfb, and none
is needed. I did not run Docker (not available in this environment) but the mechanism is
sound and mirrors what I ran directly in the venv.

Two notes: the image pins Python 3.12 while CI covers 3.10–3.13, so Docker is a spot check
rather than a matrix; and `docker_test.sh` writes `test_output_linux.txt` into the repo root,
which is **not** in `.gitignore` (only `*.log` is) — running the documented command leaves an
untracked artefact that could be committed by accident.

### 7.7 SPDX headers

`CHANGELOG.md:14` claims "SPDX license headers in all source files". I checked all 73
tracked `.py` files for both `SPDX-FileCopyrightText` and `SPDX-License-Identifier`.

**72 of 73 comply. One file is missing both:**

| File | Missing |
|---|---|
| `tools/audit_imports.py` | `SPDX-FileCopyrightText` **and** `SPDX-License-Identifier` |

The cause is visible in the history: the SPDX sweep was commit `5cd5197`
("chore: add SPDX license headers to all source files"), and `tools/audit_imports.py` was
added afterwards in `3456df3`. Its sibling `tools/audit_decorators.py` (added later still,
in `a6c2190`) *does* carry the header, so this is a one-file oversight rather than a pattern.
The CHANGELOG claim is therefore very nearly, but not quite, accurate.

The two PyInstaller `.spec` files (which are Python) carry only the `# -*- coding -*-`
line, no SPDX header — arguably out of scope for "source files", but inconsistent with
`hook-plugins.py`, which does carry one.

*(Also verified while here: the two spec files differ in exactly two lines — `name=` and
`console=True/False`. Nothing else has drifted between them.)*

### 7.8 Hygiene summary

| Item | State |
|---|---|
| `git status` | Clean (before this report). |
| `.env` in history | **Never committed** — verified with `git log --all -- .env`. |
| Secrets in tracked files | None found. `.env.example` is a single empty key. |
| `dist/` | Holds wheels + sdists for **both** 3.0.1 and 3.1.0. Gitignored, but a `twine upload dist/*` would re-attempt 3.0.1. |
| `__pycache__` | 10 directories, gitignored. Those under `plugins/` are pytest artefacts and are never used by the app (§3.2). |
| `.pytest_cache`, `*.egg-info` | Present, gitignored. |
| `test_output_linux.txt` | Produced by `docker_test.sh`, **not gitignored**. |
| `docs_/**` blanket ignore | Files dropped into `docs_/` vanish from `git status` (see `00_overview.md` §2.4). |

---

*Continues in [`03_findings.md`](03_findings.md).*
