<!-- SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo -->
<!-- SPDX-License-Identifier: MIT -->

# 07 — The harmoniser and the criteria-parsing stage

*Read-only diagnostic of what plugin 03 actually does to a researcher's criteria
between the text box and the executable table, and of the three destinations the
maintainer wants to reach: a lazy-proof harmoniser, two-model agreement before an
exclusion, and batch size 1 by default for local models.*

> *Retracted 2026-08-13 (wave 14c): the third destination — batch size 1 by
> default for local models — **is falsified and must not be acted on**. See
> §8.3, where the retraction and its measurement are recorded.*

**Repository state:** `diag/wave-13-criteria` @ `42a5c42` (tag `post-wave-12`) at
session start, working tree clean, `origin/main` in sync (0 ahead, 0 behind).
**Date:** 2026-08-12. **Mode:** read-only. No source, test, golden, tool, sample,
register or changelog file was modified. This document and
`docs/internal/CI_FAILURE_WAVE_12.md` are the only files added.
**Test baseline:** 1600 passed, 7 skipped — before and after.
**Network:** one call to the public PyPI JSON index, in part A, for release dates.
No LLM endpoint was contacted, local or remote. **No Ollama call was made and no
Ollama daemon was started.** No paid vendor API was called; no OpenAI call of any
kind was made.

## Citation and evidence conventions

This document follows `06_llm_integration.md`. Claims are anchored on
`path::symbol`. **Line numbers are absent entirely** — this is a deliberate
tightening of the model document, which permitted them "as a secondary aid". The
reason is the one §A11.4 of that document already gives:
`metascreener/plugin_manager.py::_sanitize` strips the `from __future__` line before
compiling, so runtime line numbers in the plugin tree are off by one from disk. A
citation that is wrong at the moment it is written is worse than no citation.

**Evidence markers**, as in the model document, with one addition:

- **[measured]** — produced by executing real repository code in this session, with
  no network and no model. The harness is `%TEMP%\w13_empirical.py` and
  `%TEMP%\w13_execute.py`; neither was written into the repository tree.
- **[read]** — derived from repository source without executing the behaviour.
- **[general knowledge]** — not derivable from this repository.
- **[not established]** — the evidence does not settle it, followed by what would.
- **[delegated, verified]** — *new in this document.* Part of the survey was
  produced by sub-agents. Nothing they returned is stated here as fact until I
  re-derived it from source myself. Two of their claims did not survive that check
  and are recorded in §11 rather than dropped.

**Candidate findings** are labelled **D-1 … D-10** in §9. They are **not** register
IDs. No `F-nn` was assigned and `03_findings.md` was not modified.

## Structure, and where it deviates from the model

`06_llm_integration.md` splits Part A (descriptive) from Part B (diagnostic). This
document keeps that split, but numbers its sections to the wave-13 brief's own
`B1…B11` so each can be checked off against the request. The mapping:

| Brief | Here | Kind |
| --- | --- | --- |
| B1 | §1 Inventory | descriptive |
| B2 | §2 `inference.py`, and the vocabulary audit | descriptive |
| B3 | §3 The two consumption paths | descriptive |
| B4 | §4 `llm_refine.py` after wave 12 | descriptive |
| B5 | §5 The Validate button | descriptive |
| B6 | §6 Test coverage of the parse path | descriptive |
| B7 | §7 **The empirical pass** | measured |
| — | §8 T1 / T2 / T3, informed | diagnostic |
| B8 | §8.4 Sequencing | diagnostic |
| B9 | §9 Candidate findings D-1…D-10 | diagnostic |
| B10 | §10 Corrections to the brief | — |
| B11 | §11 Handoffs HO-13-1…HO-13-6 | — |

---

## Executive summary

**The harmoniser's failure mode is not that it refuses bad input. It is that it
accepts everything, silently discards the half of each criterion it cannot model,
and then certifies the result as valid.** Five facts, three of which contradict
premises in the brief.

1. **Three of the eight rows in the repository's own reference contract do not do
   what their label says, and the Validate button reports zero errors and zero
   warnings on all eight.** **[measured]** Running the real rule engine over
   `samples/ic_ec_12.txt` against `samples/20260122_1654_aggregate.csv` reproduces
   `tests/golden/criteria_harmonized_v3.1.0.csv` exactly, and
   `plugins/03_harmoniser/inference.py::_validate_row` returns `E=0 W=0` for every
   row. The three defective rows fail in three *different* ways — a dropped operand
   (`EC-1`), a rule against the wrong column with both operands dropped (`EC-4`),
   and a correct rule at a stage that cannot execute it (`IC-5`). Only the third has
   a register row (F-65).

2. **The measured cost is not marginal.** **[measured]** over the 776-record corpus,
   executing the golden through `plugins/_common/evaluator.py::_eval_criterion` and
   `plugins/_common/runner.py::run_screen`'s own `if failed: outcome = "OUT"` rule:
   `EC-4`, whose label names *"venue contains ICRA OR IROS"*, removes **112
   records** — and the corpus contains **zero** records whose `venue` matches either
   string. The researcher's criterion, executed faithfully, would remove none. The
   harmoniser's rendering of it removes 14.4% of the corpus. `EC-1`, *"written in
   French or Spanish"*, removes the 14 French records and leaves the 2 Spanish ones,
   because "Spanish" was discarded at inference time.

3. **The operator vocabulary is not one source. It is at least seven
   representations, and no executor reads the authoritative one.** **[measured]**
   `plugins/03_harmoniser/parser.py::OPERATORS` is a 9-tuple imported by exactly
   three modules, all inside plugin 03. The 8-operator executable whitelist is
   hand-typed **four times, byte-identically**
   (`plugins/_common/evaluator.py` twice, `plugins/04_eh/ui.py`,
   `plugins/05_ih/ui.py`); EL and IL carry no list at all, only a bare
   `!= "llm"` at three sites each; `plugins/_common/parser.py::_detect_contradictions_simple`
   carries a two-member subset; `plugins/03_harmoniser/llm_refine.py` carries a
   prose copy inside a live prompt string; and `docs/usage.md` carries a copy in
   which **six of seven names are not operators at all**. Meanwhile the rule engine
   can emit only 7 of the 9 — `regex` and `in_list` are unreachable from any
   inference branch.

4. **The brief's model of the second consumption path is wrong, and the correction
   makes the problem narrower but not smaller.** The prompt does not receive "the
   criteria text". `plugins/06_el/prompt.py::_build_llm_messages_for_criterion`
   sends `json.dumps` of an 8-key object describing **one** criterion, never the
   table, never the sibling criteria, and never the raw prose except through a
   fallback when `label` is empty. The bundle *does* carry the researcher's original
   prose as `criteria/criteria_source.txt` — and **[measured]** nothing reads it.

5. **A previously dead path is now live, reachable by one button, and leaves no
   trace.** `plugins/03_harmoniser/llm_refine.py::_llm_refine` can rewrite every
   cell of the researcher's table. It records no model, no endpoint, no
   `PROMPT_VERSION` — the module has none — and the exported
   `criteria_harmonized.csv` and `manifest.json` are byte-indistinguishable from the
   rule-based ones. **[measured]** its guardrail body has zero test coverage: the
   only two occurrences of `_llm_refine(` in the tree are its definition and its
   single call site.

Two facts shape sequencing rather than design. **The entire empirical base for this
tool is eight criteria in one file** — **[measured]** `samples/` contains exactly one
criteria file, `ic_ec_12.txt`; `ex_ref_2.txt` is a bibliography. Every golden, every
test and the published validation study derive from those eight lines, and they are
clean, well-formed, one-per-line prose: **the opposite of the input T1 exists to
handle.** And **the packaging precedent T1 would follow is already broken**:
**[measured]** building a wheel from `pyproject.toml` yields 65 members including all
52 plugin `.py` files and **zero `.json` files**, so
`plugins/_common/recommended_models.json` ships in the frozen build and not in a
`pip install`.

---

# Part A — descriptive

## §1 (B1) Inventory

### Plugin 03 — `plugins/03_harmoniser/`

| Path | What it is |
| --- | --- |
| `__init__.py` | Package marker, no code. |
| `plugin.py` | Tab shim: `TAB_TITLE`, `make_plugin`, `HarmoniserPlugin`. Re-exports the parser/inference internals that tests reach for. |
| `parser.py` | **Holds the closed vocabularies** `STAGES`, `OPERATORS`, `TARGET_ALIASES`. Free-text parsing (`_parse_free_text_criteria`), structured CSV/XLSX load (`_load_structured_criteria_table`, `_normalize_structured_row` and its `op_alias` map), corpus header/coverage stats (`_load_a_header_and_stats`), target selection (`_get_best_text_targets`, `_canonicalize_targets`), operand serialisation (`_parse_what_cell`, `_what_to_export`), pipe-table export. |
| `inference.py` | The rule engine: `DEFAULT_TEXT_TARGET`, `DEFAULT_THRESHOLD`, `_infer_criterion_details`, `_validate_row`. |
| `llm_refine.py` | Optional LLM refinement: `STAGE`, `_call_openai_json`, `_sdk_importable`, `_llm_refine`. |
| `exporters.py` | `BUNDLE_SCHEMA`, `_export_csv` (the 11-column byte-frozen writer), `_export_pipe`, `_sha256_file`, `_clean_aggregate_csv`, `_build_manifest`. |
| `bundle.py` | `export_screen_a_bundle` — assembles and zips `ScreenA_Bundle/`. |
| `ui.py` | `_UiState`, `DEFAULT_HARMONISER_MODEL`, `HarmoniserView` — file loading, `_harmonise_no_llm`, `_harmonise_llm`, `_validate`, `_render_rows`, `_begin_edit`, `_export_bundle`. |

### `plugins/_common/` pieces plugin 03 depends on

| Path | Role for 03 |
| --- | --- |
| `input_errors.py` | `InputError`, `write_input_errors_csv` — the malformed-row audit schema used by `exporters._clean_aggregate_csv`. |
| `llm_client.py` | `_openai_client_for`, `_parse_llm_json_object`, imported lazily inside `llm_refine._call_openai_json`. |
| `provider_detect.py` | `last_known`, `model_choices`, `refresh` — the provider probe behind the LLM button. |
| `settings.py` | `apply_stage_fields`, `load_settings`, `resolve_stage`, `LLM_STAGES`. |
| `stage_state.py` | `Readiness`, `llm_readiness` — the single gate deciding whether "Harmonise + LLM" may run. Also `LOCAL_BATCH_SIZE`, `LOCAL_BATCH_RANGE`, `recommended_batch_size` (see §8.3). |
| `widgets.py` | `RecheckButton`, `Tooltip`. |

Note that plugin 03 has its **own** `parser.py`, `bundle.py` and `exporters.py`; the
same-named modules in `_common/` belong to the EH/IH side and are not shared with
it. **[measured]** no module under `plugins/_common/`, `plugins/04_eh/`,
`plugins/05_ih/`, `plugins/06_el/` or `plugins/07_il/` imports anything from
`plugins/03_harmoniser/` — the sole textual occurrence is a comment in
`plugins/_common/input_errors.py`. **The producer of the criteria table and its
consumers share no code.**

### The downstream criteria path (the consumers)

| Path | Role |
| --- | --- |
| `plugins/_common/parser.py` | `_load_criteria_from_text(text, stage)`, `Criterion`, `ParseReport`, `CriteriaLoadReport`, `_split_targets`, `_norm_for_target`, `_detect_contradictions_simple`. |
| `plugins/_common/evaluator.py` | **The EH/IH executor**: `_eval_criterion`, `_eval_criterion_detail`. |
| `plugins/_common/runner.py` | `run_screen(..., stage=)` — the per-row loop and outcome assignment. |
| `plugins/04_eh/{plugin,ui}.py` | EH: `run_eh_screen` → `run_screen(stage="EH")`; `EHView._refresh_criteria_table`. |
| `plugins/05_ih/{plugin,ui}.py` | IH: the same executor at `stage="IH"`. |
| `plugins/06_el/screen.py` | **The EL executor**: `_parse_criteria_harmonized_csv`, `run_el_screen`, `_excluded_by`, `_cache_key`, `_load_bundle`. |
| `plugins/06_el/prompt.py` | `PROMPT_VERSION`, `_build_llm_messages_for_criterion`. |
| `plugins/07_il/{screen,prompt}.py` | The IL twin (F-14's deliberate duplication). |
| `plugins/06_el/ui.py`, `plugins/07_il/ui.py` | Criteria tables, the `operator != "llm"` warning row. |
| `plugins/06_el/standalone.py`, `plugins/07_il/standalone.py` | Separate Tk shells — **not** headless; see §8.1. |
| `plugins/_common/bundle.py` | `NOT_SCREENED`, `EXCLUSION_SUPPRESSED`, bundle export/verification. |

### Data files on this path

| Path | Loaded by |
| --- | --- |
| `samples/ic_ec_12.txt` | The **only** criteria file in `samples/`. `tests/conftest.py::IC_EC_FILE`. |
| `samples/20260122_1654_aggregate.csv` | The A-vector corpus, 776 records, 34 columns. |
| `plugins/_common/recommended_models.json` | `plugins/_common/model_pull.py::recommended_models` via `CONFIG_NAME`. |
| `tests/golden/criteria_harmonized_v3.1.0.csv` | The plugin-03 byte-identity golden. |
| `docs/data/study_input/criteria_harmonized_v3.1.0.csv` | The frozen study input (F-98). |
| `docs/data/wave12_local_runs/runBC_criteria_harmonized.csv` | The wave-12 local-run table (F-159). |

---

## §2 (B2) `inference.py` — what it actually does

### 2.1 The operator vocabulary, and where it is defined

**[measured]** `plugins/03_harmoniser/parser.py::OPERATORS` is the only declared
vocabulary:

```python
STAGES = ("EH", "IH", "EL", "IL")
OPERATORS = (
    "contains", "equals", "regex", "in_list", "not_in",
    "gte", "lte", "between", "llm",
)
```

**[measured]** the set `plugins/03_harmoniser/inference.py::_infer_criterion_details`
can actually emit, extracted by matching every `operator = "…"` assignment in the
module, is **seven**: `between`, `contains`, `equals`, `gte`, `llm`, `lte`,
`not_in`. **`regex` and `in_list` are emitted by no branch.** They can enter a table
only through the `ttk.Combobox` in `plugins/03_harmoniser/ui.py::HarmoniserView._begin_edit`,
through `plugins/03_harmoniser/parser.py::_normalize_structured_row`'s `op_alias`
map (`match`/`re` → `regex`, `in` → `in_list`) when a pre-built table is loaded, or
through an LLM-refine pass.

### 2.2 The decision table

Derived from source; branch order is load-bearing and first match wins.

| # | Branch | Guard | Emits | Target | Stage set |
| --- | --- | --- | --- | --- | --- |
| — | seed | always | `llm` | `default_text_target` | `IL` if include else `EL` |
| 1 | language | `pick_col(language, lang, publication_language)` | `equals` | that column | `IH`/`EH` |
| 2 | year, range | `pick_col(year, publication_year, …)` + `2010-2020` shape | `between` | that column | `IH`/`EH` |
| 2 | year, `after\|since\|from\|>=` | ditto | `gte` | ditto | `IH`/`EH` |
| 2 | year, `before\|until\|<=` | ditto | `lte` | ditto | `IH`/`EH` |
| 2 | bare year + published/date | ditto | `gte` | ditto | `IH`/`EH` |
| 3 | doc type, `doc_type_map` hit | `pick_col(doc_type, document_type, publication_type, type, pub_type)` | `equals` | that column | `IH`/`EH` |
| 3 | doc type, conference/proceedings tail | ditto | `contains` | ditto | `IH`/`EH` |
| 4 | venue/journal | `pick_col(venue, journal, source, conference)` | `contains` | that column | `IH`/`EH` |
| 5 | DOI | `pick_col(doi)` | `equals` / `not_in` | `doi` | `IH`/`EH` |
| 6 | **text search** | label contains any of `title, abstract, keywords, keyword, mention, contains, must include, include term` | **`contains`** | `",".join(present text fields)` | **`IL`/`EL`** |

**Branch 6 is the anomaly and it is the shape of F-65.** It is the only deterministic
branch that routes to an LLM stage, and its trigger list is broad enough that a
label merely *mentioning* the word "keywords" lands there. `_validate_row` then
passes the row clean, because it checks `stage in STAGES` and `op in OPERATORS` as
two independent tests and never cross-checks them.

**Stage assignment has no table.** It is `crit_type` (from `IC-`/`EC-` prefix) × "did
a deterministic branch fire", with branch 6 as the exception. A criterion whose
column is absent from the corpus does not fall to a *worse* deterministic rule — the
guard fails, the branch does not fire, and it falls through to `llm` at `EL`/`IL`,
which is the safe direction.

### 2.3 What happens when the corpus lacks the target field

Three different answers, none of them an error. **[read]**

- **EH/IH** — `plugins/_common/evaluator.py::_eval_criterion` returns `"MISSING"` for
  an absent target, an absent column, or an empty value.
  `plugins/_common/runner.py::run_screen` counts it into `missing`; the record is not
  `OUT` and survives as `PASS_FLAGGED`. Surfaced in `{stage}_missing_ids`. Note the
  header comparison is **case-sensitive**, so a target `Title` against a header
  `title` is `MISSING`.
- **EL/IL** — `plugins/06_el/screen.py::run_el_screen` lowercases targets at load and
  resolves through a case-insensitive header map, defaulting to `["abstract"]` when
  the cell is blank; all-empty gives `evidence[c.id] = {"status": "MISSING"}` and
  `PASS_FLAGGED`.
- **The model never sees a non-text target anyway.**
  `plugins/06_el/prompt.py::_build_llm_messages_for_criterion` packs only
  `a_id/title/abstract/keywords`, and
  `plugins/_common/llm_client.py::FIELD_VOCABULARY` is `("title","abstract","keywords")`.
  An EL/IL criterion whose `target` cell says `venue` is evaluated against
  title/abstract/keywords regardless.

### 2.4 Confidence and thresholds

`plugins/03_harmoniser/inference.py::DEFAULT_THRESHOLD = 0.60` is the single declared
source, applied by `_validate_row` (blank it for EH/IH with a warning; default it for
EL/IL silently; otherwise require a float in `[0,1]`).

It is consumed only at EL/IL, through
`usable = valid_quote and (confidence >= float(c.threshold)) and (decision in {"meet","not_meet"})`.
**[read]** `plugins/_common/parser.py::_load_criteria_from_text` parses
`Criterion.threshold` for EH/IH and nothing ever reads it — dead by design on that
path. And the 0.6 default is restated outside `DEFAULT_THRESHOLD` at least twice
more: `plugins/06_el/screen.py::_parse_criteria_harmonized_csv` does
`thr = float(thr_s) if thr_s else 0.6`, which also silently swallows an unparseable
value back to `0.6`, and `plugins/06_el/prompt.py` defaults `c_pack["threshold"]` to
`0.6`. (D-10.)

### 2.5 The vocabulary audit — emit versus execute

Per the standing instruction that hand-maintained enumerations in this codebase rot,
I looked for second copies of every list. There are at least seven representations.
**[measured]**

| # | `path::symbol` | Form | Contents |
| --- | --- | --- | --- |
| E1 | `plugins/03_harmoniser/parser.py::OPERATORS` | module tuple | the 9 — **authoritative, and no executor imports it** |
| E1a | `plugins/03_harmoniser/inference.py::_infer_criterion_details` | inline literals | the 7 emittable |
| E1b | `plugins/03_harmoniser/parser.py::_normalize_structured_row` | `op_alias` dict | input aliases → `equals`, `in_list`, `not_in`, `regex` |
| X1 | `plugins/_common/evaluator.py::_eval_criterion` | inline 8-tuple | `equals, contains, regex, in_list, not_in, gte, lte, between` |
| X2 | `plugins/_common/evaluator.py::_eval_criterion_detail` | **the same tuple, retyped in the same file** | identical |
| X3 | `plugins/04_eh/ui.py::EHView._refresh_criteria_table` | inline 8-tuple | identical |
| X4 | `plugins/05_ih/ui.py::IHView._refresh_criteria_table` | inline 8-tuple | identical |
| X5/X6 | `plugins/06_el/screen.py::run_el_screen`, `plugins/07_il/screen.py::run_il_screen` | bare `!= "llm"`, 3 sites each | `{llm}` |
| N1 | `plugins/_common/parser.py::_detect_contradictions_simple` | inline 2-tuple | `("equals", "in_list")` |
| D1 | `plugins/03_harmoniser/llm_refine.py::_llm_refine` | prose inside a live system prompt | all 9, correct |
| D2 | `docs/internal/diagnostic/00_overview.md` | prose | all 9, correct |
| D3 | **`docs/usage.md`, plugin-03 section** | prose | `language, year, doc_type, venue, doi, keyword_in_text, llm` — **six of seven are not operators** |

X1–X4 are four byte-identical hand-typed copies of the same 8-tuple, verified by a
single exact-string grep matching all four and nothing else.

**Set differences.** Let `EMIT` = the 9.

- **EH/IH cannot execute** `EMIT − X1 = {llm}`. This direction *is* surfaced —
  `_eval_criterion` returns `UNKNOWN` and `_eval_criterion_detail` attaches a
  stage-tagged note.
- **EL/IL cannot execute** `EMIT − {llm}` = **8 of the 9 operators**. Each is marked
  `UNCERTAIN` with `note: "non-llm operator in EL stage"` **without being
  evaluated**, and the note is the only trace — `el_uncertain_ids` cannot distinguish
  "the gate refused a verdict" from "this row was never run".
- **Union across all four stages is empty**: every operator is executable
  *somewhere*. **The defect is entirely one of stage/operator pairing, not of
  missing implementations.**
- **`regex` and `in_list` are unreachable from the rule engine.** Both are fully
  implemented in `_eval_criterion` and `in_list` is one of only two operators
  `_detect_contradictions_simple` inspects — so the contradiction detector is tuned
  for an operator the inference cannot produce, and ignores five it can.

`docs/usage.md` also states *"IC-5 (keywords) -> `IH` / `keyword_in_text`"*.
**[measured]** the committed golden says `IL` / `contains`. Both halves are wrong,
and `keyword_in_text` appears in no `.py` file in the tree. (D-7.)

---

## §3 (B3) The two consumption paths

**The brief's claim is half right, and the wrong half matters.** Criteria are indeed
consumed twice, from the same artefact — `criteria/criteria_harmonized.csv`,
extracted by `plugins/06_el/screen.py::_load_bundle`. But the second path does not
receive "criteria as text".

**Prompt builders:** `plugins/06_el/prompt.py::_build_llm_messages_for_criterion` and
`plugins/07_il/prompt.py::_build_llm_messages_for_criterion`. **Two copies, not one
builder** — the function bodies are byte-identical and only the docstring and
`PROMPT_VERSION` differ, a duplication both docstrings declare deliberate. Neither is
dispatched by stage; each is passed as a callable into
`plugins/_common/llm_client.py::run_m1_llm_for_criterion`, which appends nothing.

**What is actually rendered.** Not an f-string of prose. An 8-key JSON object:

```python
c_pack = {
    "id": criterion["id"],
    "type": criterion.get("type", "exclude"),
    "operator": criterion.get("operator", "llm"),
    "target": criterion.get("target", "abstract"),
    "what": criterion.get("what", []),
    "how": criterion.get("how", "llm"),
    "label": criterion.get("label", ""),
    "threshold": criterion.get("threshold", 0.6),
}
…
user = json.dumps({"criterion": c_pack, "items": items_pack}, ensure_ascii=False)
```

fed from `plugins/06_el/screen.py::run_el_screen`'s per-criterion pack, in which
`"label": c.label or c.source_text`.

So, precisely: **the harmonised `label` is what the model sees**, not the raw prose —
except through that `or` fallback when the label cell is empty. **The whole table is
never sent**: the loop is one `crit_pack` per criterion, so the model cannot see that
a sibling criterion already covers language, and cannot notice a duplicate.

**A real rendered example, EC-2, from `docs/data/study_input/`.** **[measured]** the
row in `docs/data/study_input/criteria_harmonized_v3.1.0.csv` is

```
EL,EC-2,exclude,metadata,The paper's primary focus is spatial navigation in a virtual
maze (no social interaction or collaboration).,llm,keywords,<same sentence>,0.60,1,<source>
```

which renders as the `criterion` half of the user message:

```json
{"criterion": {"id": "EC-2", "type": "exclude", "operator": "llm",
  "target": "keywords", "what": ["The paper's primary focus is spatial navigation in a
  virtual maze (no social interaction or collaboration)."], "how": "llm",
  "label": "The paper's primary focus is spatial navigation in a virtual maze (no
  social interaction or collaboration).", "threshold": "0.60"},
 "items": [{"a_id": "...", "title": "...", "abstract": "...", "keywords": "..."}, ...]}
```

Two things to notice. **`target` is `keywords` alone** — see §7.2. And the object
says `"type": "exclude"` while the system prompt asks for
`decision ('meet'|'not_meet'|'uncertain')` **without ever stating what "meet" implies
for an exclusion criterion**; the caller applies the polarity afterwards from
`c.ctype`. `06_llm_integration.md` §A6.1 already records this.

**So: is the brief's "an ambiguous criterion poisons both" true?** **Yes, but by a
narrower route than stated.** What poisons both is the *harmonised* `label` and
`what`, because path (i) executes them and path (ii) ships them. The researcher's
original sentence is not what is poisoned — it is what is *lost*. **[measured]**
`plugins/03_harmoniser/bundle.py::export_screen_a_bundle` writes it to
`criteria/criteria_source.txt`, and grepping the plugin tree for `criteria_source`
finds a writer, a 220-character manifest preview, and **no readers at all**. The
truncation of EC-1 to "French" is invisible at both consumption points, because both
read the truncated cell and neither reads the sentence beside it.

---

## §4 (B4) `llm_refine.py` after wave 12

**Reachable from the GUI: yes, by exactly one control, and there is no setting.**
`plugins/03_harmoniser/ui.py::HarmoniserView._build_ui` binds a button labelled
"Harmonise + LLM" to `_harmonise_llm`, which gates on `_ensure_ready`,
`_readiness`, `_sdk_importable` and then spawns a worker calling `_llm_refine`. The
former checkbox was **deleted, not wired**, reversing a wave-8 decision under F-118
(D9), and the deletion is guarded by AST tests in
`tests/test_per_stage_config.py::TestTheHarmoniserCheckboxIsReadByNothingToday`.
**Consequence: the button is the only consent surface** — a user cannot pre-disable
this path, and unlike EL/IL there is no pre-run cost confirmation on it.

**Does it fire for local providers? Yes — that is now its designed case.**
`plugins/_common/stage_state.py::_KEYLESS_PROVIDERS = ("local", "custom")`, so
`llm_readiness` returns `can_run` for a keyless local provider, pinned by execution
in `tests/test_harmoniser_provider.py::TestALocalUserIsNotAskedForAPaidKey`. The
600-second timeout exists for exactly this case.

**Second call site, same plumbing — and this is the part relevant to F-160.** It is a
distinct `.create()` invocation with its own system prompt and its own response
schema (`{"rows": [...]}` rather than EL/IL's bare list), and with **no** batching,
retry, adaptive split, cache, progress events, run report, provenance, or
cancellation. But the client is built by the shared
`plugins/_common/llm_client.py::_openai_client_for(stage)` with
`STAGE = "harmoniser"`, so per-stage endpoint resolution applies and is pinned by
`tests/test_harmoniser_provider.py::TestTheInvariantReachesThisStageToo`.

On the specific worry — a vendor key reaching a keyless endpoint —
`plugins/_common/settings.py::placeholder_key_for` returns a stored real key
**unconditionally when non-empty**, with the stated rationale that a local server
which does authenticate must keep working. So a stored `sk-…` *is* transmitted to a
local endpoint. **[read]** this is by design and applies identically to EL/IL; it is
**not** a harmoniser-specific defect, and the harmoniser is not a second, unguarded
credential path. Recording that explicitly because the brief flagged it as a
possibility.

**On failure: a modal, then a silent revert.** `_llm_refine` raises on six
guardrails (missing `rows`, changed row count, non-object row, changed `id`, changed
`type`, a row failing `_validate_row`), and since F-146 `_call_openai_json` no longer
swallows the real error. `ui.py::HarmoniserView._harmonise_llm`'s worker assigns
`self.state.rows = refined` **only on success**, so any failure leaves the
rule-based rows in place, and `_poll_worker` shows
`messagebox.showerror("Operation failed", err)`. All-or-nothing: one bad row aborts
the whole refinement.

**Can the user tell which path produced the table? No.** **[measured]** the row dicts
gain no field; `plugins/03_harmoniser/exporters.py::_export_csv` writes a fixed
11-column schema byte-frozen by `tests/test_harmoniser_regression.py`; and
`_build_manifest` records `"created_by": "harmoniser"` and criteria counts, with **no
model, endpoint, temperature or prompt version** — contrast
`plugins/06_el/screen.py::run_el_screen`, which calls `llm_provenance(...)`. There is
no `PROMPT_VERSION` in `llm_refine.py` at all, so its prompt can change with nothing
recorded. The only trace is un-persisted GUI log text. (D-4.)

**Wave 12's fix, confirmed from git.** `e460a64` — *"fix(F-146): delete the SDK
interface that no longer exists, and stop hiding the real error"*. The removed body
was two `try` blocks: a modern call whose `except` arm was a bare
`except Exception: pass`, followed by `openai.ChatCompletion.create(...)` — removed at
SDK 1.0 — whose failure produced the only message the user ever saw. The fix deletes
the dead branch, removes the swallowing `except`, forwards `timeout=timeout_s` to the
live call (which previously had **no** timeout, since `timeout_s` was consumed only
by the dead branch as `request_timeout=`), and parses through the new
`plugins/_common/llm_client.py::_parse_llm_json_object`. A follow-up, `bbf423a`
(F-152/F-153), then raised the default from the dead branch's declared 120s to 600s,
because F-146 had inadvertently *shortened* the effective timeout on exactly the
CPU-bound local configuration the stage exists for.

**Tests and goldens: the call is covered, the decision is not.**
`tests/test_harmoniser_llm_call.py` executes `_call_openai_json` thoroughly,
including a repo-wide AST ban on removed SDK attributes and a negative control.
**[measured]** but `_llm_refine` itself — the ~110-line guardrail body that decides
whether a model may rewrite a researcher's criteria — has **zero coverage**: the only
two occurrences of `_llm_refine(` in the tree are its definition and its single call
site, and not one of the six `RuntimeError` paths is exercised. No golden covers it;
`tests/test_harmoniser_regression.py` drives the rule-based path only, as its own
docstring concedes. (D-5.)

---

## §5 (B5) The Validate button

**`plugins/03_harmoniser/ui.py::HarmoniserView._validate`**, delegating per row to
`plugins/03_harmoniser/inference.py::_validate_row`.

### What it checks — complete

Two preconditions: no rows → `return False` **silently**; no A-vector →
`messagebox.showwarning("Missing A", "Load A vector first.")`.

Then, per row: (1) `stage in STAGES`; (2) `id` non-empty; (3) `type` in
`{include, exclude}`; (4) `operator in OPERATORS`; (5) `target` non-empty; (6) every
target resolves against the corpus columns via `_canonicalize_targets` — *and
rewrites the cell*; (7) `what` is a list — *and coerces it*, with a warning;
(8) `between` requires exactly 2 values; (9) `gte`/`lte`/`equals` with more than one
value → **warning only**; (10) `llm` requires exactly 1 value; (11) EH/IH threshold
non-empty → warning *and blanks it*; (12) EL/IL blank threshold → **silently set to
`0.60`**; (13) EL/IL threshold parses as float; (14) in `[0, 1]`.

Two structural notes. **The error strings are computed and discarded** — `_validate`
counts rows, not findings, and never displays `errs`/`warns`; the only per-row signal
is a Treeview tint. And **"Validate" is not read-only**: checks 6, 7, 11 and 12
mutate the row, and `_render_rows(with_validation=True)` runs `_validate_row` a
second time, so one click applies the mutations twice.

### What it does NOT check

- **Compound criteria — not checked at all.** No cross-condition inspection of
  `label`, `source_text` or `what`. And the compound case is *already truncated
  upstream*, so there is nothing left in the row to detect: EC-1 arrives as
  `equals lang French`, a perfectly well-formed single-value `equals`. Check 9 makes
  even a genuine multi-value `equals` a warning only, and `_eval_criterion` then uses
  `what_list_norm[0]` alone.
- **Vagueness — not checked.** No length bound, no readability test, no blocklist.
  For `operator="llm"` the only check is **arity**, not content, and since
  `_infer_criterion_details` sets `what = [label] if label else [""]`, an empty
  sentence has length 1 and validates clean.
- **References to absent fields — half checked.** The `target` cell is checked
  (check 6). Whether the criterion's *prose* names a concept the corpus cannot
  express is not — EC-4's label names `venue` while its rule tests `doc_type`, and
  both columns exist, so nothing fires. Nor is the `what` operand checked against
  corpus *content*: nothing verifies that `equals lang "French"` will ever match.
- **Duplicates — not checked, anywhere in the pipeline.** `_validate_row` sees one
  row; `_validate` never compares rows; there is no id-uniqueness test.
  `plugins/06_el/screen.py::run_el_screen` then builds
  `crit_impacts = {c.id: {...} for c in crits}` — a dict comprehension, so duplicate
  ids **collapse**, and `llm_results[(a_id, c.id)]` means the second criterion's
  verdict overwrites the first's for every record. Contrast the *record* id path,
  which is guarded twice. (D-9.)
- **Non-executable operators — not checked, and the rule engine produces them.**
  `_validate_row` validates stage and operator independently. This is the gap F-65's
  remedy already names; it is **not** a new finding (§9).

Beyond the brief's list: `regex` is never compiled, so a malformed pattern validates
clean and yields `UNKNOWN` at run time; `gte`/`lte`/`between` operands are never
checked as numeric; six of nine operators accept an empty `what` and then return
`UNKNOWN` for every record; `enabled`, `scope` and `source_text` are unvalidated.

### What the user sees → **HO-13-1**

**[read]**, verbatim:

- pass: `messagebox.showinfo("Validation OK", f"All good. Warnings: {n_warn}")`
- fail: `messagebox.showerror("Validation failed", f"{n_err} row(s) have errors. Fix them before export.")`

Note the pass message says **"All good"** even when `n_warn > 0`, and never lists the
warnings. Which rows and which of the fourteen checks failed is never stated.
Whether that reads to a user as success is a question for a human eye — **HO-13-1**.

---

## §6 (B6) Test coverage of the parse path

| File | Tests | What it asserts |
| --- | --- | --- |
| `tests/test_criteria_parser.py` | 16 | `_parse_free_text_criteria` (count, ids, types, labels, `source_text`, empty/None input) and `_infer_criterion_details` branch behaviour, including `test_missing_columns_falls_to_llm`. |
| `tests/test_harmoniser_regression.py` | 1 | Byte-identity of the whole harmonise path against `tests/golden/criteria_harmonized_v3.1.0.csv`. |
| `tests/test_criteria_polarity.py` | 10 | F-04, the EL/IL blank-`type` skip. |
| `tests/test_deterministic_filters.py` | 15 | `_eval_criterion` per operator, including `regex`. |

**Does any test feed real prose and assert on the resulting table? One does, and it
is the wrong shape of assertion.** `tests/test_harmoniser_regression.py` reads
`samples/ic_ec_12.txt` and asserts the output is byte-identical to the golden. That
pins the current output — including all three defects in §7 — rather than validating
it. `tests/test_criteria_parser.py` feeds the same prose but asserts on the *parse*
(ids, types, labels), not on the emitted stage/operator/target triple.

**Would any existing test catch a non-executable operator being emitted? No.**
**[measured]** the only occurrences of `OPERATORS` anywhere under `tests/` are two
comments in `tests/test_harmoniser_provider.py`, whose actual assertion counts
`state="readonly"` occurrences — it locks the *widget state*, not the *contents*.
Nothing asserts a relationship between the emittable set and either executable set,
and nothing asserts that a given row's operator is executable at its assigned stage.
The golden encodes such a row and the suite is green.

**[measured]** `plugins/03_harmoniser/inference.py::_validate_row` and
`HarmoniserView::_validate` have **no direct test coverage at all** — grepping
`tests/` for either name returns nothing. The golden was therefore captured, and is
asserted byte-identical, having never passed through the validator whose approval the
GUI requires before export.

---

## §7 (B7) The empirical pass

Harnesses: `%TEMP%\w13_empirical.py`, `%TEMP%\w13_execute.py`. Nothing written into
the repository tree.

### 7.1 Scope, and a finding in the scope itself

**[measured]** `samples/` contains exactly one criteria file — `ic_ec_12.txt`, eight
criteria. `ex_ref_2.txt` is a bibliography; `20260122_1654_aggregate.csv` is the
corpus. So "every criteria file in `samples/`" is one file, and the frozen study
input contains the harmonised *output* of that same file.

That is itself worth stating: **the entire empirical base for this tool is eight
lines of clean, one-per-line, well-punctuated prose** — precisely the input a
lazy-proof harmoniser would *not* need to handle.

### 7.2 The corpus, and target selection

**[measured]** `samples/20260122_1654_aggregate.csv`: **776 records, 34 columns**.
Text-field coverage over the first 200 rows: `keywords` 1.000, `title` 0.995,
`abstract` 0.775.

`plugins/03_harmoniser/parser.py::_get_best_text_targets` returns **`'keywords'`** —
because the top field's coverage exceeds 0.8, it collapses to that field **alone**.
So every `llm` criterion in the golden carries `target = keywords`, and `title` and
`abstract` are dropped from the recorded target of criteria whose own labels are
about the paper's *content*. It does not change behaviour today, because the EL/IL
prompt packs all three fields regardless — but the recorded target is then a
statement about the run that is not true of the run, and it would matter the moment
the target cell were honoured. (D-8.)

### 7.3 The table the rule engine produces

**[measured]** running `_parse_free_text_criteria` → `_infer_criterion_details` over
`ic_ec_12.txt` against that corpus reproduces
`tests/golden/criteria_harmonized_v3.1.0.csv` **exactly**, which is what makes the
harness trustworthy. Classified:

| stage | id | operator | target | what | executable? | validate |
| --- | --- | --- | --- | --- | --- | --- |
| IL | IC-1 | `llm` | keywords | (the sentence) | yes | E=0 W=0 |
| IH | IC-3 | `equals` | lang | English | yes | E=0 W=0 |
| IH | IC-4 | `gte` | year | 2018 | yes | E=0 W=0 |
| IL | **IC-5** | **`contains`** | title,abstract,keywords | training;vocational;workplace | **NO** | E=0 W=0 |
| EH | **EC-1** | `equals` | lang | **French** *(Spanish dropped)* | yes | E=0 W=0 |
| EL | EC-2 | `llm` | keywords | (the sentence) | yes | E=0 W=0 |
| EL | EC-3 | `llm` | keywords | (the sentence) | yes | E=0 W=0 |
| EH | **EC-4** | `equals` | **doc_type** | **conference** *(venue/ICRA/IROS dropped)* | yes | E=0 W=0 |

**Every row validates with zero errors and zero warnings.** The same classification
over `docs/data/study_input/criteria_harmonized_v3.1.0.csv` gives an identical table.

### 7.4 What the defective rows actually do — measured on 776 records

Executed through `plugins/_common/parser.py::_load_criteria_from_text` and
`plugins/_common/evaluator.py::_eval_criterion`. Polarity per
`plugins/_common/runner.py::run_screen`: `if failed: outcome = "OUT"`, so `FAILED`
is removal.

```
EXECUTING stage EH  (2 criteria loaded)  warnings=none
  EC-1  op=equals  target=lang      what=['French']      -> {'MET': 762, 'FAILED': 14}
  EC-4  op=equals  target=doc_type  what=['conference']  -> {'MET': 664, 'FAILED': 112}

EXECUTING stage IH  (2 criteria loaded)  warnings=none
  IC-3  op=equals  target=lang      what=['English']     -> {'MET': 752, 'FAILED': 24}
  IC-4  op=gte     target=year      what=['2018']        -> {'FAILED': 625, 'MET': 150, 'MISSING': 1}
```

Corpus contents: `lang` = `en` 752, `fr` 14, `pt` 2, `es` 2, others 1 each;
`doc_type` = `article` 560, `conference` 112, `book` 49, `chapter` 42, …;
`venue` = 379 distinct values.

**EC-1 — *"The paper is written in French or Spanish."*** The emitted rule removes
the 14 French records. Note the language mapping *works* — `French` normalises to
`fr` — so this is not a matching failure. It is a truncation: the corpus holds **2
Spanish records**, and they survive. The criterion names 16 records and can remove at
most 14.

**EC-4 — *"The publication venue contains "ICRA" OR "IROS" (robotics conference
proceedings)."*** **[measured]** the corpus contains **0** records whose `venue`
contains `ICRA` and **0** containing `IROS`. The criterion as the researcher wrote it
removes **nothing**. The rule the harmoniser emitted removes **112 records — 14.4% of
the corpus.** Branch 3 matched on the word "conference" inside the parenthetical
before branch 4 (venue) was ever reached, so the target, the operand and the operator
are all substitutions, and no test, validator or report says so.

**IC-5 — the F-65 case.** `contains` at `IL`, so `run_il_screen` never evaluates it.
**[measured]** on the full corpus the keyword rule matches 70 of 776 records, so as a
strict inclusion filter it would fail 706; as shipped it fails none. (The register's
F-65 row measures the same defect on the IL stage's own 84-record input, where it
gives 80 survivors → 13.)

**IC-4** additionally shows `MISSING: 1` — one record has no year and silently
survives a criterion it cannot be tested against. That is the designed safe
direction, and it is visible in `{stage}_missing_ids`.

### 7.5 The answer to the question B7 asks

**How often does this tool today produce a table that silently does not do what it
says it does?**

**Three of eight rows — 37.5% — in the repository's own reference contract**, by
three different mechanisms, all validating clean:

| Row | Mechanism | Measured consequence |
| --- | --- | --- |
| EC-1 | operand dropped from a compound criterion | 2 of 16 named records survive |
| EC-4 | wrong column, both operands dropped | 112 records removed that the label does not name; 0 that it does |
| IC-5 | correct rule at a stage that cannot execute it (F-65) | 0 of 70 matching records acted on |

Counting only rows whose *executability* is broken gives 1 of 8 (12.5%) — that is
F-65's number. **The remaining two are not F-65 and have no register row.** By the
brief's other classifiers, on the same eight rows: compound by a crude
marker sweep, 6 of 8 (over-inclusive — `IC-4`'s "2018 or later" is not compound, and
`IC-5`'s three values are correctly captured); genuinely mis-handled compounds, **2**;
vague labels, 3 of 8, all three routed to `llm`, which is the correct destination for
them; targets absent from the corpus, **0 of 8**; duplicate rows, **0 of 8**.

### 7.6 One thing that looked like a finding and is not

The wave-12 local-run table `docs/data/wave12_local_runs/runBC_criteria_harmonized.csv`
differs from the frozen study input in exactly one row — IC-5, `contains` → `llm` —
so the two published measurements ran on different criteria. **This is already
disclosed**, prominently, in `docs/data/wave12_local_runs/wave12_local_runs.meta.txt`
and in `docs/llm-evaluation.md`, which also states the counterfactual (*"Evaluating it
as a strict inclusion criterion would give 13 survivors, not 73"*) and cross-refers
F-65. Recorded here only because it looks like an undisclosed discrepancy until you
check, and a future reader may reach for it as one.

---

# Part B — diagnostic

## §8 The three destinations

Treated as one cluster, as instructed. Nothing below was built.

### 8.1 T1 — a lazy-proof harmoniser

**What §7 says about the target.** The problem is not that dense prose fails to
parse. It is that **everything parses, and the losses are silent**. A linter that
only rejected malformed input would have passed all eight golden rows. The property
worth engineering is *"tell the user what their criterion was reduced to"*, not
*"reject bad criteria"*.

**Splitting compound criteria.** §7.4 gives the two concrete cases and their measured
cost. Note the asymmetry: EC-1's fix is mechanical (emit `in_list ['French','Spanish']`
— an operator that already exists, is fully implemented, is tested, and that the
inference engine **cannot currently emit**, §2.5). EC-4's is not: it requires
noticing that branch 3 matched a parenthetical gloss rather than the criterion's
subject, which is a semantic judgement.

**A deterministic linter — where it would attach.**
`plugins/03_harmoniser/inference.py::_validate_row` is already a pure function
`(row, a_columns) -> (errors, warnings)` with no I/O, no Tk and no global state. It is
the natural attachment point and it is directly testable today. Three properties it
could check with no new machinery, in increasing difficulty: (a) operator
executability at the assigned stage — this is F-65's own proposed remedy; (b) operand
count versus the number of coordinating conjunctions in the label — catches EC-1;
(c) whether the target column is the one the label names — catches EC-4. **[measured]**
it has no test file today, so any work here starts by writing one.

**Few-shot examples shipped as data — the packaging precedent is broken.**
`plugins/_common/model_pull.py::recommended_models` reads `CONFIG_NAME =
"recommended_models.json"` from `settings_dir()` first (user override) then from
`Path(__file__).resolve().parent` (shipped copy), and returns `()` on *any* failure,
deliberately: *"Offering nothing is correct."*

**[measured]** the frozen build includes it — `metaScreener.spec` has
`datas = [('plugins', 'plugins')]`, copying the whole tree. **A `pip install` does
not.** Building a wheel from `pyproject.toml` in this session:

```
wheel: metascreener_lars_ulaval-3.1.0-py3-none-any.whl
JSON files in wheel: NONE
recommended_models.json present: False
total members: 65      (all 52 plugins/**.py present)
```

The cause is `pyproject.toml::[tool.setuptools.package-data]`:
`"plugins" = ["**/*.py", "**/*.txt", "**/*.csv"]` — **`.json` is not in the list.**
And because `recommended_models()` degrades silently by design, a pip-installed
metaScreener offers no models and says nothing. The docstring's reasoning is sound
for a file absent *by choice*; it also masks a file absent *by packaging bug*.
**Shipping few-shot examples as JSON under `plugins/` would inherit this exact
defect.** (D-6.)

**A five-record dry run — does a headless entry point exist?** **[measured]** No, not
in the shipped tree.

- `plugins/06_el/standalone.py` and `plugins/07_il/standalone.py` are **not**
  headless: no `argparse`, no `__main__`, no `def main`; they build `tk.Toplevel`
  windows. They are alternate GUI shells. (This corrects the brief's implicit framing
  — see §10.)
- `tests/_engine_probe.py` is the closest thing to the seam wanted. Its docstring
  states its purpose exactly: *"drive the real EL/IL engines from a clean
  interpreter"*, written for F-161 because the drill-down call sites need a real
  class in a subprocess with real tkinter. It supplies a `_FakeResponse`/`_client`
  pair so the engine runs end-to-end with no network. It lives under `tests/`, is
  underscore-prefixed to avoid collection, and is used by exactly one caller,
  `tests/test_view_smoke.py`.
- The only argparse CLIs that drive real engine code are in `tools/` — notably
  `tools/capture_el_il_goldens.py` and `tools/measure_prompt_size.py`, the latter of
  which already renders real prompts through
  `plugins/06_el/prompt.py::_build_llm_messages_for_criterion` over a chosen corpus.

**So the seam exists three times over and is not exposed.** A dry run returning
per-criterion hit counts over N records without writing a bundle is closest to
`tools/measure_prompt_size.py`'s shape, and for the *deterministic* criteria it needs
no model at all — `_eval_criterion` over N rows is exactly what §7.4 executed here,
in a few lines. **That is the cheapest useful version of T1 and it requires no LLM
call**: for EH/IH criteria it is exact, and for EL/IL criteria it can report only
"this row will be sent to the model" — which, note, is precisely the information that
would have made IC-5's deadness visible.

### 8.2 T2 — two-model agreement before an exclusion

**Where a second call would attach.** `plugins/_common/llm_client.py::run_m1_llm_for_criterion`
takes `build_messages` as a parameter and returns per-`a_id` verdicts; both
`run_el_screen` and `run_il_screen` call it once per criterion. A second engine call
attaches there, and the verdict-combining logic attaches at the single conjunction
`usable = valid_quote and (confidence >= float(c.threshold)) and (decision in {"meet","not_meet"})`,
which is the one place a verdict becomes an action.

**Does the wave-9 cache key accommodate two models?** **Yes, cleanly, and this is the
good news.** `06_llm_integration.md` §2 establishes that
`plugins/_common/llm_client.py::_cache_key` hashes a four-member object including
**`model`** by name, pinned by
`tests/test_cache_key.py::TestCacheKeySanity::test_model_change_changes_key`. Two
models therefore produce disjoint key sets automatically and **cannot collide**. The
same section establishes the converse hazard: adding the **endpoint** to the key
invalidates every golden key (0 of 170 EL and 0 of 84 IL survive). So T2 is safe with
respect to the cache and the goldens as long as it varies `model` and not the key
*shape*. **[not established]** whether the provenance-hash side carries the same
property; establishing it means reading `plugins/_common/llm_client.py::llm_provenance`
against a two-model run, which this session did not do.

**Does the report schema have room for a second verdict?** **[not established], and
the evidence points to no.** The provenance block records six fields and, per F-155,
*the criteria table is not one of them* — a block already known to under-describe its
run. The per-record evidence shape is a flat dict (`status`, `decision`,
`confidence`, `field`, `quote`, `span`, `valid_quote`, `threshold`, `note`) with no
list dimension. A second verdict needs either a schema change or a parallel block,
and either is a golden-file event.

**Interaction with flag-only.** This is the sharpest question in T2 and it is
partly already answered. Wave 12 established that exclusion is suppressed by default
and that `EXCLUSION_SUPPRESSED` means *the gate would have excluded and policy did
not*, while `PASS_FLAGGED`/`REVIEW` mean *the gate did not reach the bar*. Those are
distinct facts and the vocabulary already separates them by construction.
**Disagreement between two models is a third thing: the gate reached the bar twice
and disagreed.** Mapping it onto `EXCLUSION_SUPPRESSED` would be wrong — that value
asserts the gate *passed*. Mapping it onto `REVIEW` is closer but loses the reason.
**Recommendation, offered as a design opinion rather than a finding:** disagreement
should produce `REVIEW`, because the user-facing action is identical (a human looks
at it) and `REVIEW` already carries "the machine did not settle this". The
*disagreement itself* belongs in the evidence block as a new note value, not as a new
outcome. Adding a fifth outcome would touch every counting map, every report column
and every golden — and `tests/test_archived_bundle_manifest.py` and
`tests/test_not_screened.py` already contain `test_a_no_op_stage_agrees_across_both_maps`,
which exists precisely because those maps have diverged before.

**And the sequencing point that may make T2 moot: with flag-only on by default, a
second model changes no record's fate.** It changes a suppressed exclusion into a
suppressed, disputed exclusion. The value is in the audit trail, not the screening —
which is a good reason to build it, and a decisive reason not to build it first.

### 8.3 T3 — batch size 1 by default for local models

**Every site where a batch default is set.** The brief asked me to assume the
enumeration has rotted until checked. It has, in both directions.

| `path::symbol` | Value | Note |
| --- | --- | --- |
| `plugins/06_el/plugin.py::DEFAULT_BATCH_SIZE` | `int(os.environ.get("SCREENA_EL_BATCH_SIZE", "50"))` | **50** |
| `plugins/07_il/plugin.py::DEFAULT_BATCH_SIZE` | `int(os.environ.get("SCREENA_IL_BATCH_SIZE", "50"))` | **50** — a second, independent copy |
| `plugins/_common/stage_state.py::LOCAL_BATCH_SIZE` | `5` | **the brief did not name this one** |
| `plugins/_common/stage_state.py::LOCAL_BATCH_RANGE` | `(5, 10)` | what D6's tooltip offers |
| `plugins/_common/stage_state.py::recommended_batch_size` | function | consumed by `plugins/_common/settings.py` |
| `plugins/02_references_of_x/services.py` | `batch_size = 20` | unrelated to LLM screening; enrichment batching |

`plugins/06_el/standalone.py` and `plugins/07_il/standalone.py` **import**
`DEFAULT_BATCH_SIZE`; they do not define it (§10, correction 3). But they do seed
their spinbox from it directly — `self.var_batch = tk.IntVar(value=DEFAULT_BATCH_SIZE)` —
**bypassing `recommended_batch_size` entirely**, which is F-154's observation and is
the single most important fact for T3: the standalone shells offer a local user
**50** where the recommendation logic would offer 5.

**The experiment that would justify the change is largely already run, and it argues
for T3 more strongly than the brief does.** F-154 (High, in the register) establishes
by arithmetic over real rendered prompts that `num_ctx` is never set, that Ollama's
observed default is 4,096, and that worst-case prompt tokens are: **batch 1
600/901** (optimistic/pessimistic), batch 5 2,170/3,256, batch 10 3,957/5,936, batch
50 16,473/24,710. So batch 10 already overflows pessimistically, batch 50 exceeds the
window by 4–6×, and **F-154's row explicitly states that it blocks any increase to
the local batch range and that the present upper bound of 10 is already unsafe.**

**T3 is therefore not a new hypothesis needing a new experiment. It is the action
F-154 already implies.** What is *not* established is the quality claim — that batch
1 gives *better verdicts*, not merely *unsuffocated* ones. Specified, not run:

- **Records:** the 85-record frozen EL input in `docs/data/study_input/el_input_v3.1.0.csv`,
  which is byte-identical across the wave-12 runs, so it is already the established
  comparison base.
- **Criteria:** EC-2 and EC-3 only — the two EL rows, byte-identical across all three
  wave-12 runs.
- **Model:** `llama3.2` at a **pinned digest, not `:latest`** — F-154 records that
  `:latest` is mutable and therefore a weak provenance value, and an experiment
  pinned to a mutable tag cannot be replicated.
- **Arms:** batch ∈ {1, 5, 10}, three repeats each at `temperature=0`, because F-155
  established these runs are **not** deterministic even at fixed settings; a single
  run per arm cannot distinguish a batch effect from run-to-run variance.
- **Comparison metric:** per-record agreement with the human consensus in
  `docs/data/eval_decisions_v1.csv`, plus the two quantities that would show
  truncation directly — the count of records omitted from a reply (`no_answer`) and
  the count failing the evidence gate (`valid_quote is False`).
- **Falsification:** if batch 1 does not reduce `no_answer` and does not improve
  agreement beyond the run-to-run spread measured by the three repeats, the change is
  justified *only* by the context-window argument and should be argued on that basis
  alone rather than on quality.

*Retracted 2026-08-13 (wave 14c):* **this recommendation is falsified, and by the
falsification clause immediately above it. Batch 1 does not reduce `no_answer`; it
multiplies it.** The controlled comparison the clause asks for has now been run by the
maintainer — same corpus, same criteria, same model, same temperature, same
`trunc_chars`, **only batch size differing** — on the 147-record post-13d chain, 294
record-criterion pairs:

| | batch 1 | batch 5 |
| --- | ---: | ---: |
| answered | **17 / 294** | **241 / 294** |
| `no_answer` | 277 (94 %) | 53 (18 %) |
| replies that were `[]` | 273 | 2 |
| `OUT` / `PASS_CLEAN` / `PASS_FLAGGED` | 0 / 0 / 147 | 0 / 61 / 75 |

**A user who followed this section would get a run in which the LLM stage screened
nothing and reported success.** That is not a throughput cost, it is the whole stage
failing silently, and it is why this note is a retraction rather than a caveat.

**The mechanism is F-191 and it is specific to n=1.** At a batch of one, the honest
reply to a non-matching record *is* an empty list, and `_parse_llm_json_array` reads
`[]` as *"the model said nothing"*. 273 of the 277 batch-1 failures are the literal two
characters `[]`. At batch 5 that signature nearly vanishes (2 of 53); the residual is
partial omission, which is **F-25 / F-122**'s territory and a different defect. So the
two batch sizes do not fail more or less — **they fail differently**, and the smaller
one fails catastrophically.

**What survives of this section.** The enumeration of batch-default sites is unaffected
and was independently useful. **F-154**'s context-window arithmetic is unaffected: batch
10 still overflows pessimistically and batch 50 still exceeds the window several times
over, so *"do not raise the local batch range"* stands. What does not survive is the
inference from that arithmetic to *"therefore lower it to 1"* — the window argument
bounds the top of the range and says nothing about the bottom, and this section treated
the two as one conclusion. **[not established]:** where between 1 and 5 the failure
sets in, and whether 5 is optimal or merely better than 1.

**Also falsified, and it is a shipped user-facing string rather than a document.**
`plugins/_common/stage_state.py::batch_size_tooltip` renders *"This is a QUALITY
setting, not a correctness one"* beside the batch box in both provider variants. On
this measurement it is a correctness setting: the same corpus screened at 1 and at 5
yields different verdicts for the same records. That is **code**, outside a
documentation wave's scope, and it is filed rather than edited here.

*Updated 2026-08-14 (wave 14d):* **the comparison above describes the UNCONSTRAINED
request, and must not be read as “prefer batch 5”.** Wave 14c changed the request
(`EL_v2_jsonschema`, cardinality-bearing), and the four-run measurement on the new
request (`docs/data/wave14d_invariance_runs/`, cache off) inverts the practical
ordering: **batch 1 now answers 294/294 and fabricates zero exclusion verdicts**,
while batch 5 fabricates 15 and 12 on two identical runs (~5 %) and batch 10
fabricates 18 (6.1 %) — a rate that grows with batch size, on largely arbitrary
records (**F-201**). So this section's *“the smaller one fails catastrophically”* is
true of the request this repository no longer sends; on the request it does send,
batch 1 is the measured-clean configuration at 5× the calls of batch 5, and the
tooltip's correction filed above was itself corrected at wave 14d to state that
trade. [not established]: where between 1 and 5 the fabrication sets in, and whether
the rate is model-specific.
- **Estimated wall-clock:** **[not established]**, and I decline to guess. F-159's
  archived manifests record real durations for CPU-only local runs at a known batch
  size; that number, scaled by the call count (85 records at batch 1 is 85 calls per
  criterion versus 17 at batch 5), is the arithmetic — but running it needs an Ollama
  call, and this session made none. The call-count ratio is the reliable part: **batch
  1 is 5× the calls of batch 5 and 10× the calls of batch 10**, and on CPU inference
  wall-clock is dominated by prompt processing, so the increase is real but sublinear.

### 8.4 (B8) Sequencing

**T1 is prerequisite to both others, and one T1 finding could make T2 unnecessary.**

1. **T1 first, and specifically the linter half.** T2 spends two model calls per
   record to decide whether an exclusion is trustworthy. §7.4 shows the shipped
   reference table removes 112 records for a reason no model would ever be consulted
   about — EC-4 is an `EH` row, adjudicated by `_eval_criterion`, never by an LLM.
   **Two-model agreement cannot detect a criterion that was mistranslated before
   either model saw it.** Buying agreement on the LLM stages while the deterministic
   stages silently substitute a different column is paying for precision in the wrong
   place.
2. **T3 second, and it is nearly free.** It touches two constants and a tooltip
   range, it is already argued by F-154, and it is a precondition for T2 being
   *measurable*: a two-model comparison run at batch 10 on a 4,096-token window is
   comparing two truncated prompts.
3. **T2 last, and possibly never in its exclusion-blocking form.** With flag-only
   on by default, disagreement changes no record's fate (§8.2).

**What finding would make each unnecessary?**

- **T1** — nothing found here. It is the load-bearing one. The measured 37.5% defect
  rate on the repository's own reference contract is the argument.
- **T2** — if flag-only remains the default, T2's screening value is zero and its
  audit value is better served by recording the criteria table in the provenance
  block (F-155's existing gap) than by a second model. That is a cheaper answer to
  the same worry.
- **T3** — if `num_ctx` were set explicitly, as F-154's remedy proposes, the
  context-window argument for batch 1 evaporates and the question reduces to the
  quality experiment, which is **[not established]**.

---

## §9 (B9) Candidate findings

**These are not register rows.** `docs/internal/diagnostic/03_findings.md` was not
modified. **[measured]** the true current maximum finding ID is **F-163**, over 160
rows — the coordinator's belief is **correct**, now verified by scanning every
`F-nnn` token in `docs/` and the top-level markdown.

Each row below carries a duplication check against the existing register.

| ID | Sev | Mechanism (one line) | Evidence | Duplication check |
| --- | --- | --- | --- | --- |
| **D-1** | **High** | **A compound criterion is silently truncated to its first operand, and the discarded half is unrecoverable from the bundle.** `inference.py::_infer_criterion_details` branch 1 returns on the first regex group. | §7.4: EC-1 *"French or Spanish"* → `equals lang French`; measured 14 of 16 named records removed, 2 survive. `in_list` would express it and the rule engine cannot emit it (§2.5). | **Novel.** "Spanish" and "compound criterion" appear nowhere in the register; the five `compound` hits are ordinary English ("compounded by"). Distinct from F-65, which is about stage/operator pairing. |
| **D-2** | **High** | **A criterion can be rendered against a different column than the one its label names, dropping every operand, with no signal.** Branch 3 matches a parenthetical gloss before branch 4 is reached. | §7.4: EC-4 *"venue contains ICRA OR IROS"* → `equals doc_type conference`; **measured 112 of 776 records removed; 0 records match the label's actual condition.** | **Novel.** `ICRA` appears nowhere in the register. |
| **D-3** | **Medium** | **The harmoniser's LLM path records no provenance**: no model, endpoint, temperature or `PROMPT_VERSION` (the module has none), so an LLM-rewritten table is byte-indistinguishable from a rule-based one in both the CSV and the manifest. | §4. Contrast `plugins/06_el/screen.py::run_el_screen`'s `llm_provenance(...)`. | **Adjacent to F-155/F-88**, which concern the EL/IL provenance block's *contents*. Those rows do not cover plugin 03, which has no block at all. Recommend attaching to the F-155 family rather than opening standalone. |
| **D-4** | **Medium** | **`_llm_refine` has zero test coverage** — the ~110-line guardrail body that decides whether a model may rewrite a researcher's criteria; none of its six `RuntimeError` paths is exercised. | §4, §6. Only two occurrences of `_llm_refine(` in the tree. | **Novel as stated.** F-146's fix added heavy coverage of `_call_openai_json`; the caller was not covered by it. |
| **D-5** | **Medium** | **A wheel built from `pyproject.toml` contains no `.json`**, so `plugins/_common/recommended_models.json` is absent from any pip install, and `recommended_models()` degrades silently to offering nothing. | §8.1, **[measured]** by building the wheel: 65 members, all 52 plugin `.py` files, zero JSON. `package-data` globs `**/*.py`, `**/*.txt`, `**/*.csv`. | **Novel.** `recommended_models` appears nowhere in the register. Note F-37 concerns `SCREENA_EL_*` env-var documentation, not packaging. |
| **D-6** | **Medium** | **`docs/usage.md` documents an operator vocabulary that does not exist** — `language, year, doc_type, venue, doi, keyword_in_text, llm`, of which six are not operators (five are target column names, one exists nowhere in the tree) — and states *"IC-5 (keywords) -> `IH` / `keyword_in_text`"* where the committed golden says `IL` / `contains`. | §2.5. **[measured]** `keyword_in_text` has zero occurrences in any `.py`. | **Novel.** F-16 concerns `docs/usage.md` naming three report files the software never produces — a different claim about the same file. Worth checking whether the maintainer prefers to extend F-16. |
| **D-7** | **Medium** | **The Validate dialog reports counts, not identities**, and the per-check error strings are computed and discarded; "Validation OK — All good" is shown even with warnings outstanding. | §5, verbatim message strings. | **Novel.** `_validate_row` appears once in the register, inside F-65's remedy, concerning the *cross-check* it lacks rather than its reporting. |
| **D-8** | **Low** | **Duplicate criterion ids are unchecked at every stage**, and `run_el_screen`'s `crit_impacts` dict comprehension collapses them while `llm_results[(a_id, c.id)]` lets the second verdict overwrite the first. | §5. Contrast the record-id path, guarded twice (F-87). | **Novel.** |
| **D-9** | **Low** | **`_get_best_text_targets` collapses to a single field above 0.8 coverage**, so `llm` criteria about a paper's content record `target = keywords` alone. Behaviourally inert today because the prompt packs all three fields regardless. | §7.2, **[measured]** coverage `keywords` 1.000, `title` 0.995, `abstract` 0.775 → `'keywords'`. | **Novel.** Low because it is currently a provenance inaccuracy, not a behaviour change. |
| **D-10** | **Low** | **The 0.60 threshold default is restated in at least three places** beyond `DEFAULT_THRESHOLD`, and `_parse_criteria_harmonized_csv` silently swallows an unparseable threshold back to `0.6`. | §2.4. | **Novel as a consolidated row**; the silent-swallow half may belong with the F-63 evidence-gate family. |

**Explicitly NOT opened as a finding:** the absence of a stage × operator cross-check
in `_validate_row`. **F-65 already covers it**, both in its evidence (*"`_validate_row`
on that row returns no error and no warning … checks stage and operator separately and
never cross-checks them"*) and in its proposed remedy (*"Add `_validate_row`
cross-validation … as the net"*). Opening a second row would be the duplication this
register has been careful to avoid.

---

## §10 (B10) Corrections to the coordinator's brief

1. **"Criteria … shipped as text into every EL/IL prompt" — materially wrong.**
   §3. The prompt receives `json.dumps` of an 8-key object describing **one**
   criterion. Never the whole table, never the sibling criteria, and never the raw
   prose except through the `label or source_text` fallback. The brief's conclusion —
   that an ambiguous criterion poisons both paths — survives, but by a narrower
   route: what poisons both is the *harmonised cell*, and the raw prose is not
   poisoned but **discarded**. `criteria/criteria_source.txt` is written into every
   bundle and read by nothing.

2. **"`standalone.py`'s `DEFAULT_BATCH_SIZE = 50`" — wrong location.**
   `plugins/06_el/standalone.py` and `plugins/07_il/standalone.py` **import** the
   constant. It is *defined* in `plugins/06_el/plugin.py` and
   `plugins/07_il/plugin.py` — **two** independent copies, each reading a different
   environment variable. The substantive point the brief was reaching for is
   nonetheless real and sharper: the standalone shells seed their spinbox from
   `DEFAULT_BATCH_SIZE` directly, bypassing `recommended_batch_size`.

3. **The batch enumeration has rotted, and the brief's own list is incomplete.**
   `LOCAL_BATCH_RANGE` exists as the brief said. `plugins/_common/stage_state.py::LOCAL_BATCH_SIZE = 5`
   also exists and the brief did not name it, as do
   `stage_state::recommended_batch_size` and an unrelated `batch_size = 20` in
   `plugins/02_references_of_x/services.py`. §8.3.

4. **T3 is not an open question needing a fresh experiment.** F-154 is already a High
   register row that measures the token arithmetic, states that the recommended range
   already exceeds a 4,096-token window at its upper bound, and **explicitly blocks
   any increase**. T3's direction is what that row already implies. The genuinely
   open part is the *quality* claim, and §8.3 specifies that experiment.

5. **F-160's shape, as applied to the harmoniser, is not a second credential path.**
   `llm_refine` builds its client through the shared
   `plugins/_common/llm_client.py::_openai_client_for` with `STAGE = "harmoniser"`, so
   per-stage endpoint resolution and the keyless-provider logic both apply. A stored
   real key *is* still sent to a local endpoint, but that is
   `settings.py::placeholder_key_for`'s documented behaviour and is shared with EL/IL.
   It is a second **call site** — with no batching, cache, retry, provenance,
   progress or cancellation — not a second **credential** path.

6. **"The 43 tests there recompute published figures from bytes"** (part A, on
   `tests/golden/`). The byte-recomputation tests that broke CI are in
   `tests/test_study_input_freeze.py` against `docs/data/`, not against
   `tests/golden/`, whose files are already covered by a `binary` attribute and were
   never at risk. Recorded in `CI_FAILURE_WAVE_12.md` §4.1; repeated here because the
   two documents share the assumption.

7. **The maximum finding ID is F-163 — the coordinator's belief is correct**, now
   verified rather than assumed. §9.

8. **Sub-agent claims that did not survive verification**, recorded per the ground
   rule that a sub-agent's correction is a claim, not a fact:
   - One agent reported that `plugins/_common/evaluator.py` and the two `ui.py`
     files retype an 8-operator tuple. My first grep appeared to refute this,
     matching only `("llm",)` guards. **The agent was right and my grep was wrong** —
     the whitelist is written `op not in (...)`, which my pattern missed. Verified
     with an exact-string search matching all four copies and nothing else.
   - The same agent's inventory attributed `plugins/06_el/screen.py`'s criterion
     objects and `plugins/_common/parser.py::Criterion` to one type. They are two
     different types with different field names (`id` versus `cid`), which is
     consistent with F-14's recorded duplication but was not stated.
   - Neither agent died on a session limit; both returned complete reports.

---

## §11 (B11) Handoffs

Each needs a human eye on a running GUI. Exact repro, then the one question.

**HO-13-1 — Does "Validation OK" read as success when there are warnings?**
Launch the app, open the Harmoniser tab, load `samples/20260122_1654_aggregate.csv` as
the A vector and `samples/ic_ec_12.txt` as criteria, click **Harmonise (no LLM)**,
then click **Validate**. *Expected from source: a dialog titled "Validation OK" reading
"All good. Warnings: 0".* **Question:** now edit any EL/IL row's threshold cell to
`abc` and re-Validate. The dialog should become "Validation failed — 1 row(s) have
errors." **Can you tell from the screen which row and which check?**

**HO-13-2 — Are the row tints legible and attributable?**
Same setup. `_render_rows` tags error rows `#ffe5e5` and warning rows `#fff6d5`.
**Question:** with one error row and one warning row present, are the two tints
distinguishable from each other and from an untinted row, at default theme and on the
maintainer's monitor? Does the tint survive row selection (selection highlight may
override the tag background in `ttk.Treeview`)?

**HO-13-3 — Is an LLM-rewritten criteria table distinguishable from a rule-based one?**
With a local provider configured and reachable, load the same two files, click
**Harmonise + LLM**, wait for "Worker finished successfully", then **Export bundle**.
Open the resulting `ScreenA_Bundle/manifest.json` and `criteria/criteria_harmonized.csv`.
*Expected from source: nothing in either file records that a model was involved.*
**Question:** is there anything at all on screen, after the run, that a user could
screenshot as evidence of which path produced the table? (This is D-3's user-facing
half.)

**HO-13-4 — Is the 8,000-character truncation of the criteria text visible?**
`_harmonise_llm` passes `full_criteria_text[:8000]` with no marker. Paste a criteria
document longer than 8,000 characters into the left pane and run **Harmonise + LLM**.
**Question:** does anything — the log pane, a dialog, the row count — indicate that
the model saw only the first 8,000 characters? This matters directly for T1, whose
target user arrives with a long unformatted document.

**HO-13-5 — Does the operator dropdown communicate a closed vocabulary?**
Double-click an `operator` cell to open the `ttk.Combobox`
(`_begin_edit`, `state="readonly"`). **Question:** are all nine values visible without
scrolling, and is it evident that `regex` and `in_list` are selectable here but can
never be produced by Harmonise? Relatedly, does selecting `contains` on an `IL` row
produce any warning? *Expected from source: none — this is the F-65 path, reachable
by hand as well as by inference.*

**HO-13-6 — What does a local user actually see offered, from a pip install?**
Install metaScreener from a built wheel (not `-e`) into a clean environment, launch
it, and open the provider dialog with a local provider that has **no models pulled**.
*Expected from source: `recommended_models()` returns `()` and the dialog offers
nothing, silently.* **Question:** what does the dialog show in that state — an empty
list, a disabled control, or no section at all? This is D-5's user-visible
consequence, and whether it reads as "nothing to offer" or as a broken screen
determines the severity.

---

## What was not done

- **Nothing was fixed.** No source, test, golden, sample, register row or changelog
  entry was modified, in either part of this session.
- **No model was called**, local or remote. Every measurement above is either static
  analysis or deterministic execution of `_parse_free_text_criteria`,
  `_infer_criterion_details`, `_validate_row`, `_load_criteria_from_text` and
  `_eval_criterion`. No Ollama daemon was started.
- **T3's wall-clock estimate is [not established]** — it needs a local inference run,
  which needs an Ollama call. §8.3 gives the call-count arithmetic instead and says
  plainly which part is missing.
- **T2's report-schema question is [not established]** beyond the observation that the
  evidence dict has no list dimension. Settling it means reading
  `llm_provenance` and the bundle writers against a hypothetical two-model run.
- **The GUI was not observed.** Six handoffs in §11, none guessed at.
- **The empirical pass covers eight criteria**, because that is every criterion in
  `samples/`. The 37.5% figure in §7.5 is three defective rows out of eight, from one
  input file, against one corpus. It is a strong signal about *this* reference
  contract, which is the one the goldens and the published study rest on. It is **not**
  a rate that generalises to arbitrary user prose, and §7.1 notes that the eight lines
  are far cleaner than the input T1 targets — which, if anything, means the rate on
  real input is a lower bound.
