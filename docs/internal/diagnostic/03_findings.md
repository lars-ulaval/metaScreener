# 03 — Findings Register

*Diagnostic report, Phase 8. Read-only analysis; nothing in this report was fixed.*

Severity: **Critical** = incorrect scientific output, data loss, or security ·
**High** = blocks maintenance or peer review · **Medium** · **Low** = cosmetic.
Effort: **XS** ≤ 30 min · **S** ≤ half a day · **M** 1–3 days · **L** > 3 days.

---

## The register

| ID | Sev | Category | Finding | Evidence | Impact | Suggested fix | Effort |
|---|---|---|---|---|---|---|---|
| **F-01** | **Critical** | correctness | **The LLM cache key omits the criterion's content.** Only the criterion *id* (`cid`) enters the key, but the prompt carries the criterion's `type`, `operator`, `target`, `what`, `label`, and `threshold`. | `plugins/_common/llm_client.py:397-414` (key = `prompt_version\|model\|cid\|a_id\|text_hash\|trunc_chars`); prompt content built at `plugins/06_el/screen.py:434-443` and serialised at `plugins/06_el/prompt.py:42-51`; lookup at `screen.py:457` | A researcher who refines the wording of `IC-1` — the most common edit during a live review — and re-runs EL/IL receives **the previous criterion's answers from cache, verbatim, with no warning**. The evidence JSON then shows quotes and decisions produced against different criterion text. UI reports a normal `cache_hits=N`. | Hash the serialised `crit_pack` into the cache key. Will invalidate `tests/golden/{el,il}_cache_v3.1.0.json` and require a re-capture — make that trade-off explicitly. | S (+ golden re-capture) |
| **F-02** | **Critical** | correctness | **Cancelling a run silently truncates the output with no marker.** `if cancel_event.is_set(): break` exits the row loop mid-corpus; the partial `full_rows`/`survivors` are returned as if complete. | `plugins/_common/runner.py:101,119`; `plugins/06_el/screen.py:430,511`; `plugins/07_il/screen.py:432,513` | A user who cancels and then exports gets a bundle that is **indistinguishable from a complete run over a smaller corpus**. Records never evaluated simply do not appear in the FULL report. In a screening tool this is a missing-data failure with scientific consequences. | Return a `cancelled: bool` alongside the results; refuse export (or stamp `manifest.pipeline.history[].cancelled = true` and label the reports) when set. | S |
| **F-03** | **Critical** | correctness | **`data/input_errors.csv` uses three incompatible schemas and is destroyed by EL/IL.** Harmoniser writes `record_number,reason,observed_len,expected_len,raw`; EH/IH write `record_index_ex_header,reason,raw_record`; EL/IL write `reason,row_json`. The only reader expects the second. | Writers: `plugins/03_harmoniser/exporters.py:160-166`, `plugins/_common/exporters.py:45`, `plugins/06_el/ui.py:1053`. Reader: `plugins/_common/parser.py:318-338`. EL skip-set that prevents carry-forward: `plugins/06_el/ui.py:1003`. **Proven:** feeding the Harmoniser's file to the reader returns `[]` | Every citation dropped at ingestion loses its provenance at the first hop (`04_eh/ui.py:460` then reports "0 rows"). At EL/IL the file is **deleted from the bundle** unless EL itself skipped rows. The audit trail for excluded-as-malformed records does not survive the pipeline. | Pick one schema, put the writer in `_common`, make EL/IL append rather than overwrite, and add a round-trip test. | S |
| **F-04** | **High** | correctness | **IL treats a criterion with an empty `type` cell as an exclusion criterion**, inverting its polarity. | `plugins/07_il/screen.py:261` — `ctype = … or "exclude"` — inside the IL stage parser; polarity applied at `07_il/screen.py:553-571` | A hand-edited or third-party `criteria_harmonized.csv` with a blank `type` on an IL row makes the LLM's `meet` verdict **exclude** the record instead of including it. Silent, and exactly backwards. | Default to `"include"` in IL (and keep `"exclude"` in EL), or better: reject a criterion with no `type` and surface a warning. | XS |
| **F-05** | **High** | correctness / documentation | **Stages 06 and 07 never verify or refresh SHA-256.** The string `sha` appears **zero** times in `06_el/ui.py`, `07_il/ui.py`, and both `standalone.py`. Both stages *do* overwrite `data/current.csv`. | `plugins/06_el/ui.py:1028` writes the file; no `sha256` map update anywhere in the module. Contrast `plugins/_common/bundle.py:208-215`. Claim: `README.md:95` | The bundle leaving EL carries a manifest digest that **no longer matches the file it names** — the manifest actively asserts something false — and nothing downstream checks. The README's "any modification … is detectable" is false for precisely the two stages that carry the LLM decisions. | Route EL/IL bundle export through a shared writer that refreshes `sha256`; add load-time verification. Soften the README claim to "corruption-detecting, not tamper-proof". | S |
| **F-06** | **High** | correctness | **`majority_vote` returns `"uncertain"`, which is not in `CANONICAL_DECISIONS = ("yes","no","unsure")`.** Combined with F-07 this silently corrupts Cohen's kappa on any tied overlap item. | `tools/eval_ingest.py:600-606` vs `:85`; consumed at `:635` | Any tie between the three raters produces a pair the confusion matrix drops but `n` still counts. **Verified not triggered in the committed data** (0 ties in 45 overlap items; reported `N` equals every matrix total). Dormant, but a re-run with a different sample or rater set would silently mis-state the validation study's headline statistic. | Change `"uncertain"` → `"unsure"` (two occurrences). | XS |
| **F-07** | **High** | correctness | **`cohen_kappa` divides by `len(pairs)` while `_confusion_matrix` silently drops out-of-vocabulary pairs.** | `tools/eval_ingest.py:512` (`n = len(pairs)`) vs `:496-498` (`if a in idx and b in idx`) | **Demonstrated:** adding 10 out-of-vocabulary pairs to a clean 50-pair set moves kappa from 0.400000 to 0.361702 with no error. Both `p_o` and `p_e` are deflated. | Raise on an unknown label, or compute `n` from the matrix total and report the drop count. | XS |
| **F-08** | **High** | correctness | **The API-key dialog blocks the documented local-provider workflow.** It requires `startswith("sk-") and len >= 20`, and it cannot be skipped. | `metascreener/api_key_dialog.py:112`; `metascreener/main.py:62,76-91`. Documentation it contradicts: `README.md:314,318,322` (`OPENAI_API_KEY=ollama`, `=llama-cpp`) | The Ollama / llama.cpp / vLLM paths — a full README section, and a likely reviewer probe since it is the project's answer to "does this require a paid API?" — **cannot be exercised through the GUI at all**. | Accept any non-empty key; downgrade the `sk-` check to a non-blocking hint. Optionally skip the prompt when a valid key is already in the environment. | XS |
| **F-09** | **High** | packaging | **The PyInstaller builds almost certainly ship without `pandas`, `openpyxl`, `langdetect`, `rapidfuzz`, `PIL`, `pytesseract`.** `hook-plugins.py` exists to collect them and is disabled by `hookspath=[]`; PyInstaller cannot discover them itself because `plugins/` is bundled as *data*. | `metaScreener.spec:25` and `metaScreener-console.spec:25` (`hookspath=[]`); `hook-plugins.py`; spec `collect_all` covers only `requests`, `urllib3`, `openai`, `fitz`; plugin imports counted in `plugins/**` | Predicted: Plugin 02 fails on `import pandas`, 04/05 on `langdetect`, 01 on `PIL`, all XLSX export on `openpyxl`. Because `main.py:137` only `print()`s and the windowed spec sets `console=False`, the user sees **silently missing tabs**. *Inferred — not confirmed by a build.* | Set `hookspath=['.']`, or add the six packages to `hiddenimports`/`collect_all`. Then build once and launch. | S (build + verify) |
| **F-10** | **High** | documentation | **`README.md` carries a UTF-8 BOM and mojibake on 46 lines**, introduced by the most recent commit on `main`. | BOM `EF BB BF` at byte 0; `â€` ×25, `Ã©` ×2 on lines 17, 21, 25, 33, 34, 52, 89-93, 101, 107, 111, 192, 194, 243-245, 299, 311, 312, 369, 411, 415. Introduced by `365325c` (49+/49− for a one-character DOI change) | This is the first screen a JORS reviewer sees: the opening sentence, the 776→73 headline, the bundle-format list, the platform table, and `QuÃ©bec` in the acknowledgements. `CHANGELOG.md:41` claims BOMs were stripped in 3.1.0, so it reads as a regression. | Re-save as UTF-8 without BOM, restore the em-dashes. Then add a mojibake+BOM step to CI — the "local pre-commit gate only" policy (`test.yml:15-18`) demonstrably failed. | XS (+ XS for the CI gate) |
| **F-11** | **High** | testing | **`plugins/02_references_of_x/` has zero test coverage** — 1,984 statements, 0%, not even an import smoke test. It is the second-largest subsystem in the repo. | Coverage: `services.py` 978 stmts 0%, `ui.py` 681 0%, `pipeline.py` 196 0%, `core.py` 129 0% | Every corpus that enters the pipeline passes through untested code. Any regression here is invisible to 16 CI cells. | Start with an import smoke test and offline unit tests for `core.py` normalisation and `services.py` parsing (the network calls can be left alone). | M |
| **F-12** | **High** | testing | **The entire LLM interaction path is 0% covered.** `run_m1_llm_for_criterion` lines 157-375 — batching, 429 handling, adaptive splitting, truncation reduction, terminal-failure back-fill — is never executed. | `plugins/_common/llm_client.py` 197 stmts, 21%, missing 157-375. The golden tests deliberately short-circuit before it (`test_el_regression.py` unsets the key) | The code that decides what happens on rate limits, truncated JSON, or a mid-run outage has never run in a test. F-01's fix and any retry tuning would be unguarded. | Unit-test it against a stub client object — no network needed; the function only calls `client.chat.completions.create`. | S |
| **F-13** | **High** | correctness | **A non-UTF-8 corpus CSV silently becomes an empty corpus in Plugin 02.** `pd.read_csv(path)` with no `encoding=` fails, is logged, and the fallback `open(path, encoding="utf-8")` fails identically. | `plugins/02_references_of_x/services.py:118,122,127,131` | A cp1252/Latin-1 CSV — routine output from Windows reference managers — yields **zero records** with nothing but two log lines. Contrast `plugins/_common/parser.py:215-221`, which tries four encodings. | Reuse `_decode_bytes`, or pass `encoding="utf-8-sig"` and fall back to cp1252. Surface a modal on zero rows. | XS |
| **F-14** | **High** | duplication | **3,251 lines of the 15,548-line `plugins/` tree (21%) are twinned copies.** `04_eh/ui.py` ↔ `05_ih/ui.py` differ in **20 structural lines out of 877** (98.9% identical); `06_el/screen.py` ↔ `07_il/screen.py` in **36 of ~632** (97.0%); `prompt.py` pair in **8, of which 7 are docstring**. | Full pair table in `01_architecture.md` §4.2 | Every bug fix, every reviewer-requested change, and every audit must be applied twice and verified twice. The two copies have already drifted in one user-visible way (`07_il/standalone.py:504` labels an IL field "EL summary"). | Staged `StageSpec`-parameterised merge, design and migration order in `01_architecture.md` §4.7. Start with `prompt.py` (zero behavioural risk, golden-protected). | L |
| **F-15** | **High** | packaging | **Eight of nine runtime dependencies are entirely unpinned**, in a project whose stated purpose is reproducibility. | `requirements.txt`, `pyproject.toml:36-46`. A fresh install on 2026-08-08 resolved to `openai 2.53.0` (constraint is `>=1.40.0` — a major boundary crossed), `pandas 3.0.5`, `numpy 2.4.6` | The tool cannot reproduce its own dependency set. A reviewer installing today, a reader installing in 2027, and CI on any given morning are testing different software. `.zenodo.json` claims the archive "satisfies the audit and reproducibility requirements expected in rigorous evidence synthesis methodology". | Keep loose ranges in `pyproject.toml`; add a fully pinned `requirements.lock` used by the Dockerfile and one dedicated CI cell; reference it from `docs/installation.md`. | S |
| **F-16** | **High** | documentation | **`docs/usage.md` names three report files that the software never produces.** | `docs/usage.md:206` `reports/eh_decisions.csv`, `:234` `reports/ih_decisions.csv`, `:269` `reports/el_decisions.csv`. Actual names: `{EH,IH,EL,IL}_FULL.csv` / `_SURVIVORS.csv` (`plugins/_common/bundle.py:160-161`). Verified: `decisions.csv` appears nowhere in plugin code | The usage guide sends a first-time user to look for three non-existent files, at the three moments they most need to find the output. | Rename to the real filenames. | XS |
| **F-17** | **High** | documentation | **The README's test counts are stale by two refactor cycles.** "104 automated tests" and "**Status: ✅ 73 passed**". Actual: **166**. | `README.md:253,271,289` vs measured `166 passed in 3.62s`. The per-file table omits `test_eval_ingest.py` (32) and `test_eval_grid_generator.py` (27) entirely and understates `test_metadata.py` as 2 (actual 5) | Understates the project's own strongest asset to a reviewer, and "73 passed" sits 264 lines below an unrelated "73 records", inviting confusion. | Update the table and the total; consider generating the count in CI. | XS |
| **F-18** | **High** | architecture | **The declared plugin lifecycle is entirely dead.** `main.py:70` sets `self._plugins = []` and nothing ever appends to it, so `_on_tab_changed` and `_on_close` iterate an empty list. | `metascreener/main.py:70,202-213`; contract at `metascreener/plugin_api.py:24-30`; dead implementations at `06_el/plugin.py:113`, `07_il/plugin.py:134`, `03_harmoniser/plugin.py:54`, `04_eh/plugin.py:60`, `02_references_of_x/plugin.py:53-88` | `on_select()` and `on_close()` are never called. Plugin 02's cooperative worker cancellation (`on_unload` → `view.on_stop()`) never runs, so **closing the app during a long resolve leaves the worker thread running**. | Append `(instance, frame)` to `self._plugins` in `_load_plugins`, or delete the hooks from the contract. Two lines either way — but pick one. | XS |
| **F-19** | **Medium** | architecture | **The custom plugin loader costs correct line numbers, `__file__`, `inspect`, and bytecode caching, for a problem stock `importlib` appears to solve.** | `metascreener/plugin_manager.py`. Measured: `run_el_screen` disk line 335 → runtime `co_firstlineno` **334** (all files with `from __future__ import annotations` are off by one); `__file__` absent; `inspect.getsource` raises `TypeError`; `__spec__.cached is None`; `plugins/__init__.py` never executes. All ten plugin modules import cleanly under stock `importlib.import_module` | Every traceback, breakpoint, and coverage line number below line 37-ish in the affected modules is wrong by one. 15,548 lines are re-compiled on every launch. Third-party plugin authors (invited at `README.md:360-370`) hit undocumented constraints. | Two steps: (1) wrap current behaviour in tests; (2) replace with `sys.path` + `importlib.import_module` and verify with one frozen build. Full reasoning and verdict in `01_architecture.md` §3.2. | M |
| **F-20** | **Medium** | correctness | **The plugin-source sanitiser can silently corrupt string literals.** `_sanitize` is line-oriented and string-blind. | `metascreener/plugin_manager.py:60-71`. Demonstrated: `S = """\nfrom __future__ import annotations\n"""` → `len(S)` becomes **1** instead of 34; a `__future__` line inside a docstring is deleted from the docstring; `from __future__ import annotations, division` loses `division` too | Latent. No current file triggers it. Will fire the first time a plugin embeds Python source in a string — a prompt template, a code generator, a fixture. The corrupted module still compiles, so nothing detects it. | Removed automatically by F-19. Until then, add a test asserting the sanitiser preserves string literals. | XS (test) |
| **F-21** | **Medium** | correctness | **The evidence gate validates that a quote *exists* but not that it is *substantive*.** A one-character quote passes. | `plugins/_common/llm_client.py:58-70` (`_quote_in_text`); gate at `plugins/06_el/screen.py:547` | `{"decision":"meet","confidence":0.95,"quote":"the"}` clears the gate and excludes a record. Relevant given `README.md:328` explicitly invites untested open-weight models. | Require a minimum normalised quote length (~20 chars), or that the quote share a token with the criterion's `what` list. | XS |
| **F-22** | **Medium** | correctness | **The quote check is not Unicode-normalised or case-folded**, so encoding variation inflates the flag rate. | `plugins/_common/llm_client.py:58-70` — exact match, then whitespace-collapsed match only | Fails *closed* (records go to human review), so it is safe — but a corpus with mixed NFC/NFD or smart punctuation flags records for reasons unrelated to the criterion, silently degrading the tool's headline reduction figure. | `unicodedata.normalize("NFKC", …)` on both sides before the second comparison. | XS |
| **F-23** | **Medium** | correctness | **`_decode_bytes` behaves differently in `_common` and in EL/IL.** | `plugins/_common/parser.py:215-221` tries `utf-8-sig, utf-8, cp1252, latin-1`; `plugins/06_el/screen.py:109-111` does `utf-8-sig` with `errors="replace"` only | The same cp1252 bundle CSV decodes correctly in EH/IH and becomes U+FFFD in EL/IL, which then breaks quote validation for those records. Also blocks the `_common` unification the CHANGELOG defers. | Unify on the four-encoding ladder, but note this changes EL/IL output bytes and requires a golden re-capture. Do it as its own commit. | S |
| **F-24** | **Medium** | correctness | **EL/IL accept malformed CSV rows that EH/IH reject.** `_csv_read` pads short rows with `""`; `_parse_csv_tolerant_text` skips them. | `plugins/06_el/screen.py:150-151` vs `plugins/_common/parser.py:302-304` | A truncated row is excluded from the corpus at stage 04 but silently screened with empty fields at stage 06 — different record sets depending on which stage happens to run. | Converge the two policies; document which one is intended. | S |
| **F-25** | **Medium** | correctness | **No `max_tokens` and no timeout on the OpenAI client.** | `plugins/_common/llm_client.py:167` (client), `:180-184` (call) | A batch whose response exceeds the model's output limit is truncated mid-JSON; `_parse_llm_json_array` returns `[]`; **the whole batch is back-filled as uncertain** with no detection and no retry, because truncation does not raise. A hung endpoint blocks a worker for the SDK default (600 s). | Set an explicit `timeout`; detect `finish_reason == "length"` and halve the batch as the 429 path already does. | S |
| **F-26** | **Medium** → **High** *(corrected during the wave 2 fix — see below)* | correctness | **Cancelling did not merely discard LLM results already paid for; it overwrote received answers with fabricated ones.** `_check_cancel()` raised a bare `RuntimeError("Cancelled")`, which unwound past `return out` — that much was in the original row. **Correction:** the post-call check at `llm_client.py:231` sits *inside* the per-batch retry `try`, so the generic `except Exception` handler at `:323` caught the cancellation, matched neither the rate-limit nor the context-length branch, and fell through to its "final failure for this batch" path — writing every item in the batch out as `decision="uncertain", confidence=0.0, valid_quote=False, error="Cancelled"`. | `plugins/_common/llm_client.py:172-176,206,231` (the raise sites) and `:323-375` (the handler that swallowed it and fabricated the replacements) | The original row understated this as wasted spend. The real impact is **evidential**: a batch whose API call had already succeeded and returned real decisions had those decisions replaced by manufactured `uncertain` verdicts, which then flow into `el_evidence_json` / the row-detail modal and into the cache if the run is later resumed — indistinguishable from a genuine model non-answer except for the `error` field, which nothing surfaces. A user pressing Cancel could therefore *change screening evidence*, not just lose it. | Raise a dedicated exception type so the retry handler re-raises rather than swallowing it, catch it at the batch loop, return the partial `out`, and drop the post-call check entirely — the answer is already paid for by then, so the thing worth skipping is the *next* batch, which the check at the top of the loop already does. | XS |
| **F-27** | **Medium** | correctness | **The manifest carries two divergent stage maps.** Plugin 03 writes `pipeline_state.stages`; EH/IH write a freshly-created `pipeline.stages`; EL/IL update whichever exists. | `plugins/03_harmoniser/exporters.py:220-223` vs `plugins/_common/bundle.py:184-198` vs `plugins/06_el/ui.py:987-995`. Reader: `plugins/04_eh/ui.py:375` reads `pipeline` | A completed pipeline ends with `pipeline_state` claiming EH/IH `not_run` while `pipeline` says `done`. The EH tab displays `EH=unknown` for a fresh Harmoniser bundle. The audit trail contradicts itself. | Pick one key; migrate the other on load. | S |
| **F-28** | **Medium** | testing | **The byte-identity goldens are captured at non-default settings**, so the default configuration path is not regression-covered. | `tools/capture_el_il_goldens.py:68-70` (`TRUNC_CHARS = 4000`, `BATCH_SIZE = 5`) vs `plugins/06_el/plugin.py:38-39` (`1500`, `50`) | `trunc_chars` participates in the cache key *and* in the quote-validation window, so truncation-boundary behaviour on the path every user actually runs is untested. | Capture a second golden at the defaults, or change the defaults to match. | S |
| **F-29** | **Medium** | testing | **The docs cross-reference tests treat internal documents as public.** `docs_dir.rglob("*.md")` requires **every** markdown file under `docs/` to be listed in `docs/index.md`. | `tests/test_metadata.py:90,167`. Reproduced: this report's own files fail the suite (1 failed, 165 passed) | Any internal note, draft, or working document under `docs/` breaks CI until advertised publicly. This is the most likely reason `docs/internal/reviewer-response-map.md` (announced at `CHANGELOG.md:35`) is absent from the repo. | Exclude `docs/internal/**` from both cross-reference tests. | XS |
| **F-30** | **Medium** | documentation | **`CHANGELOG.md:35` announces a file that does not exist** — `docs/internal/reviewer-response-map.md`. | Verified absent from the tracked tree and from all of `git log --all` | The 3.1.0 release notes claim a deliverable the repository does not contain. A reviewer checking the changelog against the repo finds a gap. | Either restore the file (after F-29) or remove the changelog entry. | XS |
| **F-31** | **Medium** | architecture | **Three of seven plugins expose `create_plugin`, which the loader does not recognise** (it looks for `make_plugin`). They load only via the untyped fallback scan over `vars(module)`. | `plugins/01_reference_extractor/plugin.py:12`, `02_references_of_x/plugin.py:29`, `03_harmoniser/plugin.py:38`; loader strategies at `metascreener/main.py:127-194` | Works today by luck — the scan happens to find the right class because no View class defines `build_tab`. Adding a `build_tab` method to `HarmoniserView` or `ReferencesOfXView` would silently break tab loading. | Rename `create_plugin` → `make_plugin` in three files. | XS |
| **F-32** | **Medium** | testing | **The CI step "Audit imports (plugins + tests)" audits plugins only.** | `.github/workflows/test.yml:55-56`; `tools/audit_imports.py plugins/ tests/` lists 36 files, none under `tests/`. The same arguments to `audit_decorators.py` list 60 files including all 14 test files | The step's name overstates its coverage. The audit itself is clean. | Fix the tool's argument walk, or rename the step. | XS |
| **F-33** | **Medium** | correctness | **Corrupt cache lines are skipped without any report.** | `plugins/_common/llm_client.py:416-430` (`try/except: continue`) | Failure ladder is correct (miss → API call → flagged), but the user is told `cache_hits=N` and never that M lines were unreadable — silent, unattributable cost and flag-rate changes. | Count skipped lines and surface them in the log line that already reports cache hits. | XS |
| **F-34** | **High** *(raised from Medium — see below)* | correctness | **A stage with zero enabled criteria reports a successful clean pass.** Every record is assigned `PASS_CLEAN` and the run summary shows all records surviving, with the fact that no screening happened confined to a warning line. | `plugins/_common/parser.py:373` and `plugins/06_el/screen.py:323` / `07_il/screen.py:325` emit the warning; `plugins/_common/runner.py:99-115` and `plugins/06_el/screen.py:386-404` then assign `PASS_CLEAN` to every row. **Measured** on a bundle built from `tests/golden/criteria_harmonized_v3.1.0.csv`: `counts: {'OUT': 0, 'PASS_CLEAN': 85, 'PASS_FLAGGED': 0}`, `survivors: 85 of 85`. | A stage that did nothing is indistinguishable from a stage that ran correctly and excluded nothing — and `PASS_CLEAN` is the *stronger* of the two survivor labels, meaning "every criterion was met", which is precisely what did not happen. **Raised to High because F-04 added a second and more likely route to it:** rejecting a criterion whose `type` cell is blank means one malformed cell can now empty a stage, where previously the stage would at least have run (with inverted polarity). A single-criterion stage — which EL is, in the demonstration corpus, after `EC-3` — goes from "wrong answer" to "no answer that looks like a right answer". See F-04. | A stage with zero enabled criteria must not report success: block the run or label the outcome distinctly (e.g. `NOT_SCREENED`), and require explicit acknowledgement before export. The warning panel alone is insufficient — the run summary actively contradicts it. Specified as a Wave 2 task. | S |
| **F-35** | **Medium** | correctness | **A plugin that fails to load produces a silently missing tab.** Failures are `print()`ed to stdout, which goes nowhere in the windowed build (`console=False`). | `metascreener/main.py:137-138,153-154,169,193-194,197`; `metaScreener.spec:47` | Compounds F-09: if the frozen build is missing `pandas`, the user sees six tabs instead of seven and no explanation. | Show a placeholder tab carrying the traceback. | S |
| **F-36** | **Medium** | hygiene | **`SCREENA` / `Screen A` is a surviving legacy identity, and it is user-visible** — env-var prefix, four tab titles, bundle root prefix, `ScreenA_Report.xlsx`, `created_by: screen_a_eh_plugin`. | Full table in `00_overview.md` §1.3 | A reviewer reads `metaScreener` in the README, launches the app, and finds four tabs called "Screen A". | Decide deliberately: rename, or document "Screen A" as the name of the screening phase. Note that renaming the bundle root and `created_by` changes the manifest and would need a compatibility shim in `_detect_bundle_root`. | M |
| **F-37** | **Medium** | documentation | **Only the `SCREENA_EL_*` environment variables are documented; the four `SCREENA_IL_*` are not.** | `README.md:300-303` vs `plugins/07_il/plugin.py:44-47` | A user tuning EL's model/batch size has no idea IL has independent settings, and will assume one setting governs both. | Add four rows to the table. | XS |
| **F-38** | **Medium** | correctness | **`services.py` fallback CSV read uses `utf-8`, not `utf-8-sig`.** | `plugins/02_references_of_x/services.py:127` | A BOM'd CSV (very common from Windows tools) yields a first column literally named `﻿title`, so every `r.get("title")` returns `""` — silent loss of the title field for the whole corpus. | `encoding="utf-8-sig"`. | XS |
| **F-39** | **Medium** | correctness | **A Semantic Scholar failure is indistinguishable from "this paper has no references".** | `plugins/02_references_of_x/services.py:1334-1335` (`except Exception: cached = {}`) | Silent under-collection of the corpus during a network blip, with no signal to the researcher. | Distinguish empty-result from error; surface errors in the UI log and the run summary. | S |
| **F-40** | **Medium** | packaging | **`hook-plugins.py` has never had any effect** — both specs set `hookspath=[]`. | `metaScreener.spec:25`, `metaScreener-console.spec:25`, `hook-plugins.py` | Dead file that looks load-bearing; the root cause of F-09. | Either wire it up (`hookspath=['.']`) or delete it and list the packages explicitly. | XS |
| **F-41** | **Low** | documentation | **`LICENSE` is not the verbatim MIT text and names no copyright holder.** It ends at `THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.`, omitting the rest of the warranty and liability clause; line 3 reads `Copyright (c) 2026` with no name. | `LICENSE:3,13` vs the SPDX headers naming Alejandro Reyes-Consuelo | Weakens the liability disclaimer and leaves the copyright holder unstated in the one file that should state it. JORS checks licensing. | Restore the full MIT text; add the holder. | XS |
| **F-42** | **Low** | hygiene | **`LICENSE` carries a UTF-8 BOM**, missed by the 3.1.0 BOM sweep (it has had one since the initial commit). | Byte-level: `EF BB BF` at offset 0 | Some licence scanners key on an exact first line. | Strip; covered by the same CI gate as F-10. | XS |
| **F-43** | **Low** | documentation | **The DOI appears only in `README.md`** — `CITATION.cff` has no `doi:` field and `.zenodo.json` no `doi` key. | `README.md:7,384`; `CITATION.cff`; `.zenodo.json` | Citation managers consuming the CFF (the machine-readable path) get no DOI. | Add `doi: 10.5281/zenodo.19360124` to `CITATION.cff` (top level and `preferred-citation`). | XS |
| **F-44** | **Low** | documentation | **Publication status drifts between two files.** README BibTeX says `note = {Submitted}`; `CITATION.cff` says `notes: "Under revision."` | `README.md:383` vs `CITATION.cff:48` | Minor, but a reviewer may notice. | Pick one. | XS |
| **F-45** | **Low** | documentation | **`.zenodo.json` spells the affiliation `Universite Laval` (ASCII) where `CITATION.cff` uses `Université Laval`.** | `.zenodo.json` creators vs `CITATION.cff:12,17,21` | Inconsistent metadata across the two deposit descriptors. | Use the accented form in both (`.zenodo.json` is UTF-8 clean). | XS |
| **F-46** | **Low** | hygiene | **`tools/audit_imports.py` is the one source file with no SPDX header**, contradicting `CHANGELOG.md:14`. | Verified: 72 of 73 tracked `.py` files comply. Added in `3456df3`, after the SPDX sweep in `5cd5197` | The changelog claim is very nearly, but not quite, accurate. | Add two lines. | XS |
| **F-47** | **Low** | hygiene | **`docker_test.sh` writes `test_output_linux.txt` into the repo root, and it is not gitignored.** | `docker_test.sh:28`; `git check-ignore` returns exit 1 for that path | Running the documented command leaves an untracked artefact that can be committed by accident. | Add to `.gitignore`. | XS |
| **F-48** | **Low** | hygiene | **`dist/` holds wheels and sdists for two versions** (3.0.1 and 3.1.0). | `dist/` listing | `twine upload dist/*` would re-attempt 3.0.1. Gitignored, so no repo impact. | Clear before release. | XS |
| **F-49** | **Low** | duplication | **`_common/widgets.py` claims to serve EL/IL but does not.** Its docstring says "shared Tk widgets for EH/IH/EL/IL"; only `04_eh/ui.py:99` and `05_ih/ui.py:99` import it. EL and IL carry a byte-identical 109-line private `DataTable` each. | `plugins/_common/widgets.py:7,38`; `plugins/06_el/ui.py:66`; `plugins/07_il/ui.py:73`. The shared version is 73 lines and 60 diff-lines away | 218 duplicated lines and a docstring that misleads the next maintainer. | Reconcile the delta; adopt the shared widget. Part of F-14. | S |
| **F-50** | **Low** | hygiene | **`07_il/standalone.py:504` labels an IL field "EL summary"** — a surviving copy-paste artefact, user-visible in the row-detail pane. | `add("EL summary", _safe_str(row.get("il_reason_summary","")))` | Cosmetic, but it is direct evidence of the F-14 twinning cost. | One-word fix. | XS |
| **F-51** | **Low** | hygiene | **Duplicated statement.** `fld_txt = (idx_map.get(a_id) or {}).get(field) or ""` appears twice in a row. | `plugins/_common/llm_client.py:273-274` | Harmless; a marker of hand-merging. | Delete one. | XS |
| **F-52** | **Low** | hygiene | **`datetime.utcnow()` in six places** — deprecated since Python 3.12. | `plugins/_common/parser.py:137`, `02_references_of_x/core.py:88`, `06_el/ui.py:997`, `06_el/standalone.py:406`, `07_il/ui.py:1240`, `07_il/standalone.py:406` | Currently harmless; CI covers 3.12/3.13 without `-W error`, so the deprecation is invisible until removal. | `datetime.now(timezone.utc)`. | XS |
| **F-53** | **Low** | correctness | **Manifest timestamps use local time and disagree with each other.** `created_at` uses `datetime.now()` (naive, local); the `history[].ran_at` two lines earlier uses `_iso_now()` (UTC + `Z`). | `plugins/_common/bundle.py:200` vs `:190` and `plugins/_common/parser.py:136-137` | Same manifest, two clocks, one unlabelled. Undermines the audit trail's timestamp evidence. Also `plugins/_common/bundle.py:204` writes the user's local ZIP filename into `derived_from.zip_name`. | Use `_iso_now()` everywhere. | XS |
| **F-54** | **Low** | hygiene | **`docs_/**` is blanket-gitignored with three re-inclusions**, so files dropped there vanish from `git status`. | `.gitignore:66-69` | A contributor adding a sample sees it silently untracked. Compounded by the one-underscore confusion with `docs/`. | Document the rule in `docs_/README.md`; consider renaming to `samples/` after acceptance (touches `pyproject.toml:75`, README ×4, `docs/index.md`, `docs/usage.md`). | S |
| **F-55** | **Low** | testing | **EH/IH do not detect duplicate `local_id`; EL/IL do.** | `plugins/06_el/screen.py:213-215` drops duplicates; `plugins/_common/parser.py:270-315` has no such check | A corpus with duplicate ids screens cleanly through stages 04–05 and silently loses rows at stage 06. | Add the check to `_parse_csv_tolerant_text`. | XS |

| **F-59** | **Medium** | correctness | **Plugin 02's pause/resume hooks guard on methods the View does not define**, so they would no-op even if fired correctly. `RefXPlugin.on_hide` checks `hasattr(self.view, "request_pause")` and `on_show` checks `request_resume`; `ReferencesOfXView` defines neither. | `plugins/02_references_of_x/plugin.py:71-91` (the guards) vs `plugins/02_references_of_x/ui.py:388` `ReferencesOfXView`, whose only pause/resume-adjacent method is `on_stop` (line 942). The `_request_pause`/`_request_resume` pair lives on `_BaseModal` (line 129), `ResolveModal` (335) and `FetchModal` (360) — modal helper classes the plugin never reaches. | This is a **second, independent** reason the pause/resume feature is dead, on top of F-18: fixing the dispatch alone changes nothing, because the guard fails and both hooks fall through silently. Long resolve/fetch runs keep consuming CPU and API quota while their tab is off-screen. Note the contrast with `on_unload`, whose guard on `view.on_stop` **does** resolve — that hook works now that F-18 fires it. | Decide whether the feature is wanted. If yes, expose `request_pause`/`request_resume` on `ReferencesOfXView` delegating to the active modal's `_RunControl` (`ui.py:104`), and wire `on_hide` to tab-leave in `_on_tab_changed`. If no, delete `on_hide`/`on_show` from the plugin — they are not in the `BasePlugin` contract. | S |
| **F-60** | **Medium** | testing | **`_load_plugins` itself is untested.** The lifecycle tests exercise `resolve_plugin_entrypoint` and `notify_plugin` against fake modules; the loop that actually registers plugins is covered only by an AST assertion that the source contains a `self._plugins.append` call. | `metascreener/main.py:228-245`; tests at `tests/test_plugin_lifecycle.py` (`TestResolveReturnsTheInstance`, `TestNotifyPlugin` use fakes; `TestPluginsListIsPopulated` parses the source rather than running it) | A structural check cannot catch an ordering or alignment bug — e.g. appending after `nb.add` on one branch, or skipping the append when `frame` is falsy-but-not-None — which would silently de-align `_plugins` from the notebook's tab indices and make `_on_tab_changed` fire the wrong plugin's hook. The method cannot be exercised without a Tk root, which is why it was never covered. | Fold into the headless View smoke test proposed as action 7 in the top-ten list: build a real `Tk()`, run `_load_plugins` over the seven real plugins, assert `len(self._plugins) == nb.index("end")` and that entry *i* corresponds to tab *i*. Skip when no display is available. | S |

| **F-61** | **Low** *(investigated as a suspected Critical — see the note below the register)* | hygiene | **`run_screen` did not filter criteria on `enabled`.** The EH/IH runner took `criteria_report.criteria` wholesale, so any disabled criterion in the report it was handed would have been evaluated and could have excluded records. **Unreachable through the application:** the EH/IH criteria loader drops disabled rows before building the report, and EL/IL filter at run, so no disabled criterion has ever reached an evaluation loop. | Defect: `plugins/_common/runner.py:90` before `dc622fa` (`crits = criteria_report.criteria`). Why it is unreachable: `plugins/_common/parser.py:390-392` (`enabled = _truthy(...)`; `if not enabled: continue`) for EH/IH, and `plugins/06_el/screen.py:410` / `plugins/07_il/screen.py:412` (`crits = [c for c in criteria_report.criteria if c.enabled]`) for EL/IL — the latter present since before wave 0. The toggle itself is Plugin 03's criteria table (`plugins/03_harmoniser/ui.py:695-699`), which writes `enabled=0` to `criteria_harmonized.csv` (`plugins/03_harmoniser/exporters.py:87`). Verified by loading a two-row table with one row disabled: only the enabled `cid` reaches the report. | **No user-facing impact, and no released version can have produced a wrong exclusion from this.** It is a latent gap only: a caller that constructs a `CriteriaLoadReport` in code — as `tests/test_not_screened.py` does — would have got silent evaluation of disabled criteria, and the same omission meant "zero *enabled* criteria" could not be detected in EH/IH at all, which is how it surfaced. | Fixed in `dc622fa` as a prerequisite to F-34: filter on `enabled`, and key `crit_impacts` over all criteria so the criteria table keeps a zeroed row for a disabled one. Defence in depth — the parser remains the primary filter. | XS (done) |

**Count by severity: 3 Critical · 16 High · 23 Medium · 16 Low — 58 findings.**

**Count by category: correctness 24 (one of which is shared with documentation) · documentation 9 ·
hygiene 10 · testing 7 · packaging 3 · architecture 3 · duplication 2.**

---

### Note on F-61: a suspected Critical that did not survive checking

F-61 was opened on the hypothesis that a criterion switched off in the UI was
still being evaluated and could still exclude records — a visible control that
silently does nothing, which would have been Critical and would have meant past
users needed to re-check their exclusions.

**That hypothesis is false, and nothing in it should be carried into release
notes or user-facing documentation.** Three independent filters stand between
the toggle and an evaluation loop, and the first two predate wave 0:

1. Plugin 03's table writes `enabled=0` into `criteria_harmonized.csv`
   (`03_harmoniser/ui.py:695-699` → `exporters.py:87`).
2. The EH/IH loader skips disabled rows when building the report, so they never
   enter `CriteriaLoadReport.criteria` at all (`_common/parser.py:390-392`).
3. EL/IL filter again at run (`06_el/screen.py:410`, `07_il/screen.py:412`).

The runner's missing filter sat *behind* filter 2 and was therefore never
reached in the application. It was found only because a test constructs a
`CriteriaLoadReport` directly, bypassing the loader.

Recorded at Low rather than dropped because the code fact is real and the fix
is committed, and because the negative result is worth keeping: the next person
to notice `crits = criteria_report.criteria` should be able to find out in one
place that it was checked and found harmless.

The claim also appeared, wrongly, in the commit message of `dc622fa` and in the
first draft of the `[Unreleased]` changelog entry for F-34. The changelog was
corrected before release; the commit message stands as written and is wrong on
this point. This paragraph is the correction of record.

---

## Top 10 actions

Ordered by (impact × urgency) ÷ effort, with peer review in mind.

| # | Action | Effort | Unblocks |
|---|---|---|---|
| **1** | **Fix the README encoding (F-10) and add a BOM/mojibake CI step.** Re-save UTF-8 without BOM, restore the 25 em-dash lines, and add a three-line Python check to `test.yml` that runs identically on all four runners. | XS + XS | The first screen a JORS reviewer sees. The "local pre-commit gate only" policy has now failed once in production; CI is the only durable fix. |
| **2** | **Fix the criterion-content cache key (F-01).** Hash `crit_pack` into `_cache_key`, re-capture the EL/IL goldens, and note the re-capture in the CHANGELOG. | S + re-capture | Removes the one path where the reproducibility mechanism actively produces wrong science. This is the finding that most deserves to be closed before publication. |
| **3** | **Close the three cheap correctness holes: F-06/F-07 (kappa), F-04 (IL polarity default), F-08 (API-key dialog).** Four files, under a dozen lines total. | XS × 3 | F-06/07 protect the validation study's headline statistic on any future re-run; F-04 removes a silent polarity inversion; F-08 makes the entire documented local-LLM section actually usable — the likeliest reviewer probe of "does this need a paid API?". |
| **4** | **Make cancellation honest (F-02) and stop destroying `input_errors.csv` (F-03).** Return/record a `cancelled` flag and refuse or label a partial export; unify the three `input_errors` schemas in `_common` and make EL/IL append. | S + S | The two remaining Critical data-integrity findings. Both are "the output looks complete but isn't", which is the worst failure mode a screening tool can have. |
| **5** | **Correct the documentation claims: F-16 (three non-existent report filenames), F-17 (104/73 → 166), F-30 (missing changelog file), F-05's README wording, F-37 (`SCREENA_IL_*`).** Then fix F-29 so internal docs stop breaking CI. | XS × 5 + XS | Everything a reviewer can check by reading. Cheapest credibility per minute in the whole list. Fixing F-29 first is what lets internal working documents — including this report — live in the repo. |
| **6** | **Build the PyInstaller spec once and see what happens (F-09, F-40, F-35).** Set `hookspath=['.']` or add the six missing packages, build, launch, count the tabs. | S | The distributable is currently unverified and probably broken. It is also the only artefact a non-Python reviewer would ever run. |
| **7** | **Write a headless View smoke test** — instantiate each of the six Views against a fixture bundle, drive the run path, assert on `full_rows`. | M | This is the prerequisite for F-14. Without it, merging 1,710 lines of View code has no safety net at all (§5.4). Also lifts the 7% GUI coverage figure that a reviewer may ask about. |
| **8** | **Pin dependencies (F-15).** Add `requirements.lock` with `==` pins, wire it into the Dockerfile and one CI cell, reference it from `docs/installation.md`. | S | Makes the reproducibility claim in `.zenodo.json` true rather than aspirational. Also stabilises CI, which currently tests a moving target (`openai 2.x`, `pandas 3.x` today). |
| **9** | **Begin the de-duplication (F-14) with the two safest moves:** `prompt.py` → `_common/prompt.py`, then `screen.py` → `_common/llm_screen.py`. Both are fully golden-protected. | S then M | Removes ~660 duplicated lines and proves the `StageSpec` approach against the byte-identity tests before anything touches the untested View layer. |
| **10** | **Replace the custom plugin loader (F-19, F-20).** Tests first, then `sys.path` + `importlib`, then one frozen build to confirm. | M | Restores correct tracebacks, `__file__`, `inspect`, and bytecode caching; removes the latent source-corruption bug; and makes the extension contract in `README.md:360-370` honest. Do it after action 6, which supplies the frozen-build verification you need anyway. |

---

## What is genuinely good here

This is a better-instrumented project than its size and its one-maintainer history would
predict. The following should be treated as load-bearing and **not** disturbed by any
refactor:

- **The `PASS_FLAGGED` discipline is real and consistently applied.** Almost every failure
  path inside the screening engines — unparseable JSON, missing column, empty field,
  unrecognised operator, API outage, low confidence, unverifiable quote — routes to *human
  review*, never to exclusion. `llm_client.py:290-303` and `:357-370` explicitly back-fill an
  uncertain entry for every item in a batch that produced no response, so a failed API call
  cannot make a record disappear. That is the correct instinct for a screening tool and it is
  applied uniformly.

- **The evidence gate holds up under adversarial reading.** I traced every field of the LLM
  response looking for a way past it: invented `a_id`, out-of-enum decision, non-numeric or
  out-of-range confidence, bogus field name, malformed span, non-JSON response, prose-wrapped
  response. Every one degrades to "flagged", not to "acted on". The one hole (F-21, trivial
  quotes) is narrow and closable in one line. Crucially, the quote is validated against **the
  exact truncated text the model was shown**, recomputed per call because adaptive retry can
  change the truncation mid-batch (`llm_client.py:273-277`) — that is a subtle thing to get
  right and it is right.

- **The golden-file mechanism is the best thing in the repository.** Five byte-identity
  goldens covering all four screening stages plus the criteria table, replayed offline
  through a cached-response envelope so an LLM-dependent stage becomes deterministically
  testable with zero network and zero cost — and engineered so that a *cache miss* flips the
  outcome column and fails loudly rather than silently passing. The `.gitattributes`
  `binary` rule protecting them from CRLF rewriting is load-bearing and correct (the goldens
  genuinely mix LF and CRLF). This machinery is what makes the Phase 4 de-duplication
  tractable at all.

- **The two AST audit tools are an unusual and genuinely good idea.** `tools/audit_imports.py`
  exists because a real bug — a transitive import dropped during the Plugin 03 extraction —
  survived a green test suite and was only caught by manual GUI smoke. Rather than shrug, the
  author wrote a static checker for that exact bug class, documented the incident in the
  tool's docstring, and wired it into CI. Both audits pass clean today.

- **The validation study is done properly.** Blind adjudication grids with the LLM's columns
  deliberately stripped, and a test (`test_decisions_sheets_do_not_expose_llm_columns`) that
  enforces the blindness. Polarity-aware mapping so humans and LLM are compared on one
  canonical scale. Pure-Python Cohen's and Fleiss' kappa — **which I verified independently
  against textbook reference values and they are exactly correct**, including the edge cases
  (empty input, perfect agreement, single category / zero marginals → NaN rather than a
  division by zero, unequal rater counts → `ValueError`). The full evidence chain is
  committed under `docs/data/`, and the reported kappas include *negative* values that the
  documentation then explains as the prevalence paradox rather than hiding.

- **The refactoring history is disciplined.** Twenty-odd commits titled
  `refactor(plugin-NN): extract X`, each small, each preceded by the golden capture that
  protects it (`4977cf0` and `4fbe8fd` land *before* the extractions they guard). Two
  follow-up commits (`90ff050`, `d277a33`) fix defects the author found in their own earlier
  extractions. `_common/` for EH/IH is a complete and successful de-duplication — the residual
  difference is 12 lines of `plugin.py` plus 20 lines of strings.

- **Honesty in the documentation where it counts.** `llm_client.py:150-155` states plainly
  that temperature 0.0 does not guarantee determinism and that the cache is the real
  reproducibility mechanism. The CHANGELOG's **Deferred** section names the exact obstacle to
  further de-duplication and the exact reviewer items that were not addressed, rather than
  quietly omitting them. Plugin 01 is labelled experimental in the README, in `docs_/README.md`,
  in the tab title, in a banner widget, and in its docstring — five places, with an explicit
  warning that PRISMA flow diagrams are not valid input.

- **Zero bare `except:` clauses in 22,175 lines.** The 183 broad handlers are a problem, but
  every one of them names `Exception`.

- **The headline funnel numbers check out.** 776 records confirmed by parsing the sample
  corpus; 90.6% and 98.3% are arithmetically exact and mutually consistent; the 0.6 default
  threshold is verified in three code locations plus the committed criteria golden. (The final
  count is the one open item — see Q1.)

- **`git status` is clean, no secret has ever been committed** (`git log --all -- .env`
  returns nothing), all seven `.gitignore` sections are thoughtful, and the CI matrix covers
  four operating systems and four Python versions with `fail-fast: false`.

---

## Open questions for the human

**Q1 — The 73-vs-80 discrepancy (highest priority).** `README.md:25` reports the funnel
ending at **73** records. Replaying the committed goldens gives **80** (`il_filtered`: 84 in,
4 `OUT`, 80 `REVIEW`). The 90.6% and 98.3% figures are consistent with 73, not 80. The
goldens were captured at `TRUNC_CHARS=4000, BATCH_SIZE=5`, which are not the application
defaults — so the golden run and the manuscript's demonstration run may legitimately be
different executions. **Which run do the manuscript figures describe, and is that run's
output archived anywhere?** If they are different runs, the repository should say so; if they
are the same run, one of the two numbers is wrong.

**Q2 — Has a PyInstaller build ever been produced and launched from this tree?** F-09 predicts
that `pandas`, `openpyxl`, `langdetect`, `rapidfuzz`, `PIL`, and `pytesseract` are absent from
the frozen bundle, which would make Plugins 01/02/03/04/05 fail silently. I could not test
this. If a working `.exe` exists, my analysis of the spec is missing something and I would
want to know what.

**Q3 — Is the custom plugin loader solving a problem I cannot see?** I demonstrated that stock
`importlib` loads all ten plugin modules in the source tree, and that `_ensure_metascreener_on_sys_path`
already puts `sys._MEIPASS` on `sys.path` for the frozen case. **Was the loader written in
response to a specific PyInstaller failure?** If so, what was the error? That would change the
F-19 verdict from "replace" to "keep, with tests".

**Q4 — Is "Screen A" a deliberate concept or a legacy name?** It appears in tab titles, env
vars, the bundle root prefix, and the final report filename. If it names a *phase* (title/
abstract screening, as opposed to a hypothetical "Screen B" full-text phase), it should be
documented as such. If it is just the old product name, F-36 applies. This affects the bundle
root string, so it is not a cosmetic decision.

**Q5 — What is the intended relationship between EH/IH `PASS_FLAGGED` and IL's `REVIEW`?**
They are the same concept under two labels (`06_el/screen.py:66` vs `07_il/screen.py:68`).
Is the distinction meaningful to a user, or is it an artefact of the twinning?

**Q6 — Should `docs/internal/` exist at all?** F-29 means it currently breaks CI. If internal
documents are wanted in-repo (this report, the reviewer-response map), the tests need an
exclusion; if not, they should live elsewhere and `CHANGELOG.md:35` should be corrected.

**Q7 — What was `docs/internal/reviewer-response-map.md` and where is it now?** The CHANGELOG
announces it as a 3.1.0 deliverable. It is in neither the tree nor any commit.

**Q8 — Is Plugin 02's zero test coverage a deliberate scoping decision?** It is the second-
largest subsystem and every corpus passes through it. Was it treated as out of scope because
it makes network calls, or did it simply never get tests?

**Q9 — How much does the pipeline get run against non-UTF-8 corpora in practice?** Several
findings (F-13, F-23, F-38) concern encoding fallbacks that fail either silently or closed. If
real-world inputs are always UTF-8 exports, these drop in priority; if researchers routinely
paste from Endnote/Zotero on Windows, F-13 in particular becomes urgent.

**Q10 — Is the criteria file expected to change between runs of the same review?** This
determines how severe F-01 really is. If the workflow is "harmonise once, then run stages
04→07 in one sitting", the stale-cache window is small. If criteria get refined after seeing
EL output — which is the realistic research workflow — F-01 fires on the most common path.

**Q11 — Are the EL and IL prompts intended to diverge?** Commit `edd466d` deliberately split
one shared prompt builder into two byte-identical copies "so EL and IL prompts can evolve
independently". Is there a concrete plan for that divergence? If not, F-14's first migration
step is free; if yes, the `StageSpec` design should carry a per-stage prompt hook instead.

**Q12 — Who is the copyright holder?** `LICENSE:3` says `Copyright (c) 2026` with no name;
the SPDX headers say Alejandro Reyes-Consuelo; the affiliations point at Université Laval.
Universities often assert institutional copyright. Worth resolving before deposit.

**Q13 — Was commit `365325c` made through a PowerShell script or an editor?** Identifying the
exact tool would let you fix the local workflow, not just the file. The signature is a
read-as-cp1252 / write-as-UTF-8-with-BOM round trip, which is the PowerShell 5.1 default for
`Set-Content`/`Out-File`.

**Q14 — Does the GUI block export after a cancelled run?** I could not verify F-02's full
severity without running the app. If `EHView`'s export buttons are disabled after a cancel,
the finding drops from Critical to Medium. The engine-level truncation is real either way.

**Q15 — Is there an upper bound on corpus size anyone has tested?** `run_screen` holds the
entire corpus in memory as list-of-dicts and the LLM stages build several parallel dicts
keyed by `(a_id, cid)`. 776 records is comfortable; 50,000 may not be. No finding is raised
because no limit is documented or claimed — but reviewers of screening tools often ask.

---

*See [`README.md`](README.md) for the executive summary.*
