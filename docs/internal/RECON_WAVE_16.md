# RECON — wave-16 candidate: criteria-diversity robustness experiment

**Session:** read-only recon, 2026-08-15, at HEAD `556daa71bb3b9f3eb11e4ebc558d8e9e96cf8090` (main, clean tree).
**Location note:** the task asked for `docs/reports/wave-16-recon.md`; that directory does not exist, and the repo's established reports location is `docs/internal/` (every wave report lives there: `FIX_WAVE_*.md`, `ESCALATION_WAVE_13.md`, `CI_FAILURE_WAVE_12.md`), so this report is `docs/internal/RECON_WAVE_16.md`, matching the `*_WAVE_N` naming. It is deliberately **untracked** — no branch, no commit.
**Method note:** produced by a 13-agent read-only recon (8 section agents; the five numeric/legality-heavy sections re-verified by adversarial verifier agents that re-read every citation and re-ran every count), with the load-bearing claims of the remaining three sections independently reproduced by the coordinator session. Zero product LLM calls were made; zero network calls; no file in the repo was modified.

Standing rule applied throughout: every coordinator claim was checked against the repo; corrections are flagged inline as **COORDINATOR PREMISE WRONG** and consolidated in **PREMISES CORRECTED** near the end.

---

## §1 CRITERIA INVENTORY

### 1.1 The shipped sample criteria (free-text form)

`samples/ic_ec_12.txt` is the **only criteria file in `samples/`** (`docs/internal/diagnostic/07_criteria_parsing.md:615-616`, `tests/conftest.py:71`). Despite the "_12" in the name it carries **eight** criteria — 4 inclusion + 4 exclusion, with IC-2 absent (the numbering gap is verbatim in the file); `docs/internal/FIX_WAVE_15D_HARMONISER_LLM.md:239-241` records the eight-count as measured ("the filename's 12 is not a count"). Verbatim:

| line | id | polarity | verbatim text |
|---|---|---|---|
| samples/ic_ec_12.txt:1 | IC-1 | include | `IC-1 – The paper considers immersive virtual reality OR a virtual simulation using a head-mounted display (HMD).` |
| samples/ic_ec_12.txt:2 | IC-3 | include | `IC-3 – The paper is written in English.` |
| samples/ic_ec_12.txt:3 | IC-4 | include | `IC-4 – The publication year is 2018 or later.` |
| samples/ic_ec_12.txt:4 | IC-5 | include | `IC-5 – The title, abstract, or keywords mention training OR vocational OR workplace.` |
| samples/ic_ec_12.txt:6 | EC-1 | exclude | `EC-1 – The paper is written in French or Spanish.` |
| samples/ic_ec_12.txt:7 | EC-2 | exclude | `EC-2 – The paper’s primary focus is spatial navigation in a virtual maze (no social interaction or collaboration).` |
| samples/ic_ec_12.txt:8 | EC-3 | exclude | `EC-3 – The paper’s primary focus is the rubber hand illusion paradigm.` |
| samples/ic_ec_12.txt:9 | EC-4 | exclude | `EC-4 – The publication venue contains “ICRA” OR “IROS” (robotics conference proceedings).` |

Polarity comes from the `IC`/`EC` prefix at parse time: `plugins/03_harmoniser/parser.py:408-415` (`crit_type = "include" if prefix == "IC" else "exclude"`, line 414). The free-text parser also accepts "Inclusion/Exclusion criteria" headers + bullets, `ic:`/`ec:` prefixes, and plain lines under a mode header (`plugins/03_harmoniser/parser.py:355-451`). README: "Sample inclusion/exclusion criteria (4 IC + 4 EC) for a VR/HMD workplace training review" (`README.md:238`); `docs/usage.md:23-24` says "eight free-text criteria (four inclusion, four exclusion)".

### 1.2 The harmonized frozen sets — TWO frozen tables plus one live pin, and they differ

**(a) `docs/data/study_input/criteria_harmonized_v3.1.0.csv`** — the v3.1.0/published-study freeze (PRE-13d rules; carries known defects F-166/F-167). Byte-identical to `tests/golden/criteria_harmonized_v3.1.0.csv` (both sha256 `a01ccc73056a987c5459da9c9ec373e08d44803ba9b67c2d48b3bf818e11f73d`, re-run). Header: `stage,id,type,scope,label,operator,target,what,threshold,enabled,source_text`. All rows `scope=metadata`, `enabled=1`:

| line | id | stage | type | operator | target(s) | what | threshold |
|---|---|---|---|---|---|---|---|
| :2 | IC-1 | IL | include | llm | keywords | the full IC-1 sentence | 0.60 |
| :3 | IC-3 | IH | include | equals | lang | `English` | (blank) |
| :4 | IC-4 | IH | include | gte | year | `2018` | (blank) |
| :5 | IC-5 | **IL** | include | **contains** | `title,abstract,keywords` | `training;vocational;workplace` | 0.60 |
| :6 | EC-1 | EH | exclude | equals | lang | **`French` only** (F-167 truncation — prose says French OR Spanish) | (blank) |
| :7 | EC-2 | EL | exclude | llm | keywords | the full EC-2 sentence | 0.60 |
| :8 | EC-3 | EL | exclude | llm | keywords | the full EC-3 sentence | 0.60 |
| :9 | EC-4 | EH | exclude | **equals doc_type `conference`** (F-166 substitution — prose names ICRA/IROS venues) | | | (blank) |

`docs/data/study_input/study_input.meta.txt:1-16` states the flaw explicitly: pre-13d rules, chain `776 -> 125 -> 651 -> 566 -> 85` (:9), "REPRODUCIBLE, AND NOT THE SCREENING THE CRITERIA PROSE DESCRIBES" (:10). IC-5 here is `contains` at IL — the F-65 pairing that EL/IL never evaluate (see 1.5).

**(b) `docs/data/wave14c_batch_runs/runDE_criteria_harmonized.csv`** — the current-rules frozen chain input (POST-13d, PRE-15c; drives the 147-record chain `776 -> 16 -> 760 -> 613 -> 147`, `study_input.meta.txt:12`; criteria digest `5dd51aaa…`, `study_input.meta.txt:27`). Same header; differs from (a) only in:

| line | id | stage | operator | target | what |
|---|---|---|---|---|---|
| :6 | EC-1 | EH | **in_list** | lang | **`French;Spanish`** (F-167 repaired) |
| :9 | EC-4 | EH | **contains** | **venue** | **`ICRA;IROS`** (F-166 repaired) |
| :5 | IC-5 | still IL / contains | | `title,abstract,keywords` | `training;vocational;workplace` |

**(c) What the translator emits TODAY (post-15c, HEAD)** — not a committed CSV, pinned by tests: `tests/test_harmoniser_regression.py:121-137` (`EXPECTED_RULES`) is identical to (b) except `"IC-5": ("IH", "contains", "title,abstract,keywords", ["training","vocational","workplace"])` (:129-130). Maintainer adjudication in the F-65 register row (`docs/internal/diagnostic/03_findings.md:92`): *"IC-5 stays as written — it is a keyword-mention test, and the software executes what is written"*; fixed in `52d3491`/`8bffb53`. The resulting deterministic funnel is pinned live by `TestTheChainAsRouted` (`tests/test_stage_routing.py:208-243`): `776 → EH OUT 16 → 760 → IH OUT 738 → 22` (docstring :209-213; asserts :228, :235, :241), with `imp["IC-5"]["met"] == 70` (:242) and `failed == 690` (:243) under the F-204 union evaluator. Frozen tables (a) and (b) deliberately do not move (freeze policy, `docs/internal/FIX_WAVE_15C_STAGE_ROUTING.md:50-66`).

### 1.3 Row schema

The harmonized CSV schema is owned by the harmoniser's exporter, **not** by `plugins/_common/parser.py`: `plugins/03_harmoniser/exporters.py:74-86` — `cols = ["stage","id","type","scope","label","operator","target","what","threshold","enabled","source_text"]`, "byte-identity-critical" (:69-72); `enabled` serialises `1`/`0` (:108).

Vocabularies (`plugins/03_harmoniser/parser.py`): `STAGES = ("EH","IH","EL","IL")` (:41); `OPERATORS = ("contains","equals","regex","in_list","not_in","gte","lte","between","llm")` (:42-52); `DETERMINISTIC_OPERATORS = frozenset(OPERATORS) - {"llm"}` (:56); `EXECUTABLE_BY_STAGE = {"EH": det, "IH": det, "EL": {"llm"}, "IL": {"llm"}}` (:65-72; comment :58-64 — "Hoisted here from `linter.py` at wave 15c … (F-109's discipline); `linter.py` re-exports it"). Evaluator side: `DETERMINISTIC_OPERATORS` tuple with "`llm` is deliberately absent" — `plugins/_common/evaluator.py:88-92`.

### 1.4 `_validate_row` legality rules — in `plugins/03_harmoniser/inference.py:331-407` (NOT `plugins/_common/parser.py`)

- stage ∈ STAGES else "Invalid stage" — inference.py:336-338
- id required else "Missing id" — :340-342
- type ∈ {include, exclude} else "Invalid type" — :344-346
- operator ∈ OPERATORS else "Invalid operator" — :348-350
- **stage↔operator cross-check (ERROR, wave 15c/F-65)**: operator ∉ `EXECUTABLE_BY_STAGE[stage]` → `"operator '<op>' cannot execute at stage <stage>: <stage> runs … only"` — :360-365 (rationale :352-359: `contains@IL` used to pass "with zero errors and zero warnings, from every producer")
- target required else "Missing target" — :367-369
- targets canonicalised against corpus columns (`_canonicalize_targets`), unknown → "Unknown target(s): …"; mutating (`row["target"] = canon`, :373) — :371-375
- `what` coerced to list (warning) — :377-380
- `between` requires exactly 2 values (error) — :383-384
- `gte/lte/equals` with >1 value → **warning only** — :385-386 (why F-167's truncation validated clean)
- `llm` requires exactly 1 sentence in `what` (error) — :387-389
- threshold: EH/IH — warned + **blanked** (:391-395); EL/IL — blank defaults 0.60 (`DEFAULT_THRESHOLD`, :61; :396-398); non-numeric or outside [0,1] → error (:399-405)
- **no type-vs-stage polarity check** (candidate F-206; `FIX_WAVE_15C_STAGE_ROUTING.md:166-168, 331`)

It is a mutating validator called once per row (15C doc :145-147); **the export gate reads its errors alone** — a cross-check error blocks export of new bundles (15C doc :153-159; `plugins/03_harmoniser/validate_report.py:82-88`). `def _validate_row` exists nowhere else in the repo (grep re-run). Downstream *tolerant* loaders apply weaker rules — see §8 layers 3 and 4.

### 1.5 What routes a criterion to EH/IH vs EL/IL — precisely

Routing happens at **two distinct moments**; the coordinator's "keyword-in-text rule" is only one branch of the first.

**(A) Authoring time — the stage cell, filled by inference only where blank.** For free text, every criterion goes through `plugins/03_harmoniser/inference.py::_infer_criterion_details` (`ui.py:610-616`). For structured CSV/XLSX import, an author-stated `stage` cell **wins**: inference fills only blank cells (`plugins/03_harmoniser/ui.py:561-584`; a stage cell not in STAGES is blanked first, `parser.py:502-504`).

`_infer_criterion_details` (inference.py:64-328): **default** `stage = "IL" if include else "EL"`, `operator = "llm"`, `what = [label]` (:107-111, :328). Six deterministic branches are tried in sequence, each routing to IH (include) / EH (exclude) — the include/exclude half of the stage letter always comes from IC/EC polarity, never from the pattern:

1. **Language** — "written in X" / "language is X" / known language names; all matches unioned (F-167 fix, :125-148); requires a lang-ish corpus column (:151); `equals` (1 lang) or `in_list` (>1) (:160-163).
2. **Year** — needs a year-ish column (:166); range → `between` (:169-175); after/since/`>=` → `gte` (:178-184); before/until → `lte` (:187-193); bare year + publication word → `gte` (:196-202).
3. **Doc type** — doc-type-ish column AND type/document/conference word in the label (:205-206); value from `doc_type_map` on `label_main` (parentheticals stripped — F-166 "guard permissive, value strict", :84-105, :224-232); conference/proceedings fallback → `contains` (:234-239).
4. **Venue/Journal** — venue word + venue-ish column (:242-243); `contains`; quoted strings are the operands (:253-258), else the tail after "published in" (:260-263).
5. **DOI** — "doi" in label + doi column; `equals ""` / `not_in ""` (:267-282).
6. **Keyword-in-text** — trigger words `["title","abstract","keywords","keyword","mention","contains","must include","include term"]` anywhere in the label (:285-286) + a text column (:287-291); `contains` over available text fields; operands from quotes / "mention X or Y" / whole label (:295-316). **Since wave 15c this routes to IH/EH** (:318-326 — the F-65 fix; it used to route to IL/EL where it was never evaluated).

A criterion lands at **EL/IL only by falling through all six branches** (or by explicit stage cell / the LLM refiner, whose auto-route repair re-stages any deterministic-operator@LLM-stage row to IH/EH — 15C doc :130-136). `_validate_row`'s cross-check is the net over every producer.

**(B) Execution time — the `stage` column literal is the ONLY router; the operator decides whether the row executes.**
- 04 EH / 05 IH: `_load_criteria_from_text(text, stage)` keeps a row iff its `stage` cell equals the requested stage, case-insensitive (`plugins/_common/parser.py:395-399`; wrappers e.g. `plugins/04_eh/ui.py:112-114`). **No `stage` column at all → every row is assumed to belong to the requested stage** (parser.py:389, 396-397; docstring :377-380 — F-205).
- 06 EL / 07 IL: `_parse_criteria_harmonized_csv(text, stage_filter)` keeps a row iff `stage` equals the filter (`plugins/06_el/screen.py:342-344`; IL twin `plugins/07_il/screen.py`); disabled rows filtered at :505.
- Operator gate: EH/IH execute only deterministic operators; `llm` → UNKNOWN (`plugins/_common/evaluator.py:217-221`, note `operator_llm_not_supported_in_<stage>` :288-291). EL/IL execute only `llm` (`plugins/06_el/screen.py:720, :779`); other operators recorded loudly as `not_evaluated` "deterministic operator '<op>' at EL, which runs llm only (F-65)" (:816-831; IL :831) with record status UNCERTAIN (:880-884).
- Loader divergence worth knowing: at EH/IH a *present-but-blank* `enabled` cell **disables** the row (`_truthy`, parser.py:157-158, TRUTHY set :46, applied :401); at EL/IL blank = enabled (screen.py:346-347). Not found registered in `docs/internal/` (grep re-run); only the operator-default divergence is in F-205.

**Recipe — landing a criterion deliberately in each stage (free-text form):**
- **05 IH**: `IC-n –` line matching any branch 1–6 (e.g. "written in English" → `IH equals lang English`).
- **04 EH**: same pattern classes on an `EC-n –` line (e.g. "written in French or Spanish" → `EH in_list lang French;Spanish`).
- **07 IL**: `IC-n –` line matching NO branch — no language/year/doctype/venue/DOI pattern and **none of branch 6's trigger words** (`title, abstract, keywords, keyword, mention, contains, must include, include term`).
- **06 EL**: same fall-through on an `EC-n –` line.
- Caveat both ways: merely *mentioning* a trigger word sends a semantic criterion to the deterministic stage (F-65 row, 03_findings.md:92: "any criterion label merely mentioning those words lands there"); a parenthetical gloss can still let a branch in (F-166 comment, inference.py:93-96).

**Via hand-authored harmonized CSV (stage cell wins):** write the 11-column row with explicit `stage`; the stage↔operator pairing must be legal or export blocks — EH/IH take the 8 deterministic operators (threshold blanked), EL/IL take `llm` only, exactly one `what` sentence, threshold in [0,1] defaulting 0.60. Polarity (`type`) is free relative to the stage letter (F-206), and it is the `type` cell, not the stage letter, that the evaluator and verdict gate read (`evaluator.py:238-241`; `06_el/screen.py:893-898`: polarity is "read off the criterion's own type polarity, never the stage's").

**§1 premises:** samples-ship-criteria CONFIRMED (with precision: the chain consumes harmonised derivatives; 14d manifests record `"criteria_filename": "ic_ec_12.txt"`, `docs/data/wave14d_invariance_runs/runF_batch1_manifest.json:7`). "Routing is a keyword-in-text rule" — WRONG (correction above). "F-109 is vocabulary hoisting" — WRONG: F-109 (`03_findings.md:139`, Medium, open at HEAD) is about the criterion-operator vocabulary existing in **at least seven hand-maintained copies** with no enforcement, no STATUSES constant, plus two integrity facts (`regex` unreachable; `_detect_contradictions_simple` inspects only `("equals","in_list")`). The *hoisting* was wave 15c applying F-109's remedy discipline when it hoisted `linter.py::_EXECUTABLE_BY_STAGE` to `plugins/03_harmoniser/parser.py::EXECUTABLE_BY_STAGE` (`FIX_WAVE_15C_STAGE_ROUTING.md:115-125`; parser.py:58-64). "_validate_row in plugins/_common/parser.py" — WRONG (it is in `plugins/03_harmoniser/inference.py:331`).

---

## §2 THE AGGREGATE

### (a) In-repo artifacts

**`samples/20260122_1654_aggregate.csv` — THE "aggregated vector."** 776 data records, 34 columns (`wc -l` gives 2096 physical lines — quoted abstracts embed newlines; parsed row count is authoritative). SHA256 `b36c3cbbe88f47c6e885ee95d0d7f3e2812a73fd38348d74cee2ff392b9be914`. Header mirrored as `AGGREGATE_COLUMNS` (`tests/conftest.py:75-79`); bound as `AGGREGATE_CSV` (`tests/conftest.py:72`) and consumed by the harmoniser/EH/IH/linter/routing tests (`tests/test_eh_regression.py:49`, `test_ih_regression.py:55`, `test_stage_routing.py:226`, `test_criteria_linter.py:62`, `test_harmoniser_regression.py:51`, `test_inference_repairs.py:42`, `test_harmoniser_validate_wiring.py:75`). Every one of the 32 archived bundle manifests records `inputs.aggregate_filename = "20260122_1654_aggregate.csv"` and `aggregate.rows_valid_written = 776`.

**`docs/data/study_input/` (frozen study input, F-98):**

| file | data rows | cols | SHA256(12) |
|---|---|---|---|
| criteria_harmonized_v3.1.0.csv | 8 | 11 | a01ccc73056a |
| el_input_v3.1.0.csv | 85 | 34 | af029f8d64fa |
| el_filtered_v3.1.0.csv | 85 | 41 | 604cb2f51be7 |
| il_filtered_v3.1.0.csv | 84 | 41 | 088cca9db422 |

(digests recomputed AND matching `docs/data/study_input/SHA256SUMS:1-4`). `study_input.meta.txt:52`: `corpus_records=776`; frozen from `tests/golden/` at `4fbe8fd` (:50), captured 2026-05-02 (:51), model `gpt-4o-mini` (:59). **F-168 banner** (:9-12): this is the pre-13d chain `776 -> 125 -> 651 -> 566 -> 85`; current rules over the same prose give `776 -> 16 -> 760 -> 613 -> 147` (:12); the 85 are a strict subset of the 147, zero the other way, 62 records absent (:13-16). Lineage tie: el_input digest `af029f8d64fa` equals `sha256["reports/IH_SURVIVORS.csv"]` in all seven 85-chain post-IH/EL/IL bundles — the frozen study input IS the IH-survivor file of the archived 2026-05-02 chain.

**Test fixtures:** `tests/golden/` — criteria=8, eh/ih FULL=776 each, el_input=85, el_filtered=85, il_input=84, il_filtered=84 (mutable regression fixtures, deliberately divergent from study_input; `tests/test_study_input_freeze.py:14-32`, guards :43-63). `tests/data/`: 30-row EL/IL eval fixtures. Wave dirs: `runD_batch1_EL_FULL.csv` (14c) = 147 rows; `runJ_batch5_EL_FULL.csv` (15e) = 147 rows; `wave14c_batch_runs.meta.txt:20-21` `corpus_records=776`, `el_input_records=147` (same at `wave14d_invariance_runs.meta.txt:16-17`).

### (b) External bundles — `S:\Alejandro_\projet julien (prisma-hub)\_archive_bundles`, identified BY MANIFEST CONTENT ONLY

37 dir entries = 33 zips + 3 xlsx + 1 Office lock file. **32 zips carry `ScreenA_Bundle/manifest.json`; 1 does not** (`metaScreener_JORS_LaTeX_REVISED.zip` — a LaTeX manuscript, not a bundle). All 32: `bundle_schema=screenA_bundle_v1`, aggregate filename + 776 as above. **No manifest records a producer app version** (union of top-level keys: `aggregate, bundle_schema, created_at, created_by, criteria, criteria_source_preview, derived_from, inputs, pipeline, pipeline_state, sha256, warnings, updated_at`; regex scan for any version field → none; `tests/test_archived_bundle_manifest.py:11` attributes "v3.1.0" to the 2026-05-07 bundle from outside knowledge). Chain notation: per-stage `OUT n → survivors` from `pipeline.history[*].counts.OUT` / `survivors_rows` (manifest-recorded, not derived). cur/crit = sha256(12) of `data/current.csv` / `criteria/criteria_harmonized.csv`.

| zip (opaque key) | created_by | created / updated | chain (manifest) | cur | crit |
|---|---|---|---|---|---|
| ScreenA_Bundle_20260429_141230.zip | harmoniser | 04-29 | none run | ef9521110f35 | a01ccc73056a |
| ScreenA_Bundle_20260429_142842.zip | harmoniser | 04-29 | none run | ef9521110f35 | 3a360807655c |
| ScreenA_Bundle_20260502_182652.zip | harmoniser | 05-02 | none run | ef9521110f35 | a01ccc73056a |
| ScreenA_Bundle_20260507_092855.zip | harmoniser | 05-07 | none run | ef9521110f35 | a01ccc73056a |
| ScreenA_Bundle_20260811_180658.zip | harmoniser | 08-11 | none run | b36c3cbbe88f | 3d6d4e388948 |
| ScreenA_Bundle_20260813_154726.zip | harmoniser | 08-13 | none run | b36c3cbbe88f | 0072ec957ed8 |
| ScreenA_Bundle_20260813_214020.zip | harmoniser | 08-13 | none run | b36c3cbbe88f | **5dd51aaa6e2f** |
| ScreenA_Bundle_EH_20260502_182731.zip | screen_a_eh_plugin | 05-02 | EH:125→651 | 530bf2dfdf1c | a01ccc73056a |
| ScreenA_Bundle_EH_20260507_092916.zip | screen_a_eh_plugin | 05-07 | EH:125→651 | 530bf2dfdf1c | a01ccc73056a |
| ScreenA_Bundle_EH_20260811_174423.zip | screen_a_eh_plugin | 08-11 | EH:125→651 | 530bf2dfdf1c | a01ccc73056a |
| ScreenA_Bundle_EH_20260811_180718.zip | screen_a_eh_plugin | 08-11 | EH:125→651 | 530bf2dfdf1c | 3d6d4e388948 |
| ScreenA_Bundle_EH_20260813_154743.zip | screen_a_eh_plugin | 08-13 | **EH:16→760** | 3bcd313eb608 | 0072ec957ed8 |
| ScreenA_Bundle_EH_20260813_214049.zip | screen_a_eh_plugin | 08-13 | **EH:16→760** | 3bcd313eb608 | 5dd51aaa6e2f |
| ScreenA_Bundle_IH_20260502_182746.zip | screen_a_ih_plugin | 05-02 | EH:125→651 · IH:566→85 | af029f8d64fa | a01ccc73056a |
| ScreenA_Bundle_IH_20260507_092931.zip | screen_a_ih_plugin | 05-07 | EH:125→651 · IH:566→85 | af029f8d64fa | a01ccc73056a |
| ScreenA_Bundle_IH_20260811_174434.zip | screen_a_ih_plugin | 08-11 | EH:125→651 · IH:566→85 | af029f8d64fa | a01ccc73056a |
| ScreenA_Bundle_IH_20260811_180735.zip | screen_a_ih_plugin | 08-11 | EH:125→651 · IH:566→85 | af029f8d64fa | 3d6d4e388948 |
| ScreenA_Bundle_IH_20260813_154751.zip | screen_a_ih_plugin | 08-13 | **EH:16→760 · IH:613→147** | 5bba4a36f715 | 0072ec957ed8 |
| ScreenA_Bundle_IH_20260813_214057.zip | screen_a_ih_plugin | 08-13 | **EH:16→760 · IH:613→147** | 5bba4a36f715 | 5dd51aaa6e2f |
| 20260502_212749_post_EL_bundle.zip | screen_a_ih_plugin | 05-02 / 05-03 | 125→651 · 566→85 (**no EL history**) | af029f8d64fa | a01ccc73056a |
| 20260502_213057_post_IL_bundle.zip | screen_a_ih_plugin | 05-02 / 05-03 | 125→651 · 566→85 (**no EL/IL history**; F-27 dual maps) | af029f8d64fa | a01ccc73056a |
| 20260507_093720_post_EL_bundle.zip | screen_a_ih_plugin | 05-07 | 125→651 · 566→85 (no EL history) | af029f8d64fa | a01ccc73056a |
| 20260811_174726_post_EL_bundle.zip | screen_a_ih_plugin | 08-11 | 125→651 · 566→85 · EL:40→45 | 42ee98f606dd | a01ccc73056a |
| 20260811_181009_post_EL_bundle.zip | screen_a_ih_plugin | 08-11 | 125→651 · 566→85 · EL:43→42 | ab85fff310d2 | 3d6d4e388948 |
| 20260811_184118_post_EL_bundle.zip | screen_a_ih_plugin | 08-11 | 125→651 · 566→85 · EL:4→81 | d2e6e11eef06 | 3d6d4e388948 |
| 20260813_155206_post_EL_bundle.zip | screen_a_ih_plugin | 08-13 | **16→760 · 613→147 · EL:0→147** | f8115e4f5587 | 0072ec957ed8 |
| 20260813_214712_post_EL_bundle.zip | screen_a_ih_plugin | 08-13/14 | **16→760 · 613→147 · EL:0→147** | f8115e4f5587 | 5dd51aaa6e2f |
| 20260813_220334_post_EL_bundle.zip | screen_a_ih_plugin | 08-13/14 | same | f8115e4f5587 | 5dd51aaa6e2f |
| 20260814_003200_post_EL_bundle.zip | screen_a_ih_plugin | 08-13/14 | same | f8115e4f5587 | 5dd51aaa6e2f |
| **20260814_071007_post_EL_bundle.zip** | screen_a_ih_plugin | 08-13/14 | same — **the 15e acceptance input** (whole-zip sha `0bd1604a…`, = `bundle_runG_sha256` in the 14d meta; `wave15e_acceptance_runs.meta.txt:15-17`) | f8115e4f5587 | 5dd51aaa6e2f |
| 20260814_072708_post_EL_bundle.zip | screen_a_ih_plugin | 08-13/14 | same | f8115e4f5587 | 5dd51aaa6e2f |
| 20260814_075140_post_EL_bundle.zip | screen_a_ih_plugin | 08-13/14 | same | f8115e4f5587 | 5dd51aaa6e2f |
| metaScreener_JORS_LaTeX_REVISED.zip | — | — | **NO MANIFEST** (LaTeX paper) | — | — |

Flags: the 2026-05 post-EL/IL bundles carry F-27's contradicting stage maps (`pipeline_state.stages` vs `pipeline.stages`) and no EL/IL history entries; `tests/test_archived_bundle_manifest.py:11-25` pins exactly these defects (stale current.csv digest F-05 now caught :86-99; four undigested members documented-not-caught :112-126 but no longer producible :128-164; F-27 still open :204-243; missing EL history now written :171-197). Neither that test nor `test_bundle_integrity.py` reads the external zips at run time (synthetic reproduction; grep confirms). Aggregate byte-drift: pre-08 bundles carry `data/current.csv` = `ef9521110f35` vs repo `b36c3cbbe88f` — same header, same 776 ids in order, exactly 11 rows differing **only** in CRLF→LF inside quoted fields. The 2026-08-11 trio shows three different live-LLM EL results on the same 85 survivors (OUT 40/43/4); all 2026-08-13/14 post-EL bundles show `EL OUT 0 → 147` (flag_only policy, `wave14c_batch_runs.meta.txt:40`).

### (c) What the pinned chain consumes, and the reconciliation

`TestTheChainAsRouted` loads **`samples/20260122_1654_aggregate.csv`** (`tests/conftest.py:72`; `test_stage_routing.py:226`, asserts 776 at :228) and re-harmonises criteria live (`thr._harmonise_to_csv`, :222-224) — it consumes **no archived bundle** and no frozen criteria file. Asserts EH `(OUT, survivors) == (16, 760)` (:235), IH `(738, 22)` (:241). The verbatim chain `776 → 16 → 760 → 738 → 22` appears in exactly: the test docstring, `README.md:35`, `docs/usage.md:266`, and the three F-168 banners (14c meta :114, 14d meta :115, 15e meta :26). (`FIX_WAVE_15C_STAGE_ROUTING.md` does NOT state it verbatim — its :25 is the pre-F-204 measurement `… IH OUT 752 → 8`; the union outcome is a projection at :38, :340.)

**Three chains coexist, all from the same 776-record aggregate:**
1. **Frozen pre-13d study chain** `776 → 125 → 651 → 566 → 85` — study_input + all bundles through 2026-08-11.
2. **Wave-14c current-rules chain (IC-5 at IL, unevaluated)** `776 → 16 → 760 → 613 → 147` — the 2026-08-13/14 bundles and the 147-row EL_FULL files (14c/14d/15e).
3. **Wave-15c chain (IC-5 at IH, F-204 union)** `776 → 16 → 760 → 738 → 22` — pinned only as counts in `TestTheChainAsRouted`; **the 22-survivor set is not persisted anywhere as bytes** (no bundle, no CSV; containment of 22 in 147/85 is UNKNOWN without executing the chain).

**Maintainer's pointer table:**

| artifact | where | records | role in chain | digest(12) |
|---|---|---|---|---|
| The aggregated vector | samples/20260122_1654_aggregate.csv | 776 | chain input, consumed directly by the pinned chain | b36c3cbbe88f |
| Same corpus, older byte-form | data/current.csv inside pre-08 bundles | 776 | identical ids/order; 11 rows differ in newline encoding only | ef9521110f35 |
| Frozen study EL input (pre-13d) | docs/data/study_input/el_input_v3.1.0.csv | 85 | end of chain 1; = IH_SURVIVORS of the 2026-05-02 archived chain | af029f8d64fa |
| Frozen study criteria (pre-13d) | docs/data/study_input/criteria_harmonized_v3.1.0.csv | 8 | chain-1 criteria | a01ccc73056a |
| Current-rules criteria (14c+) | docs/data/wave14c_batch_runs/runDE_criteria_harmonized.csv; also inside the 2026-08-13 21:40 bundles | 8 | drives chain 2 | 5dd51aaa6e2f |
| 147-record EL input | wave14c/14d/15e run dirs (`*_EL_FULL.csv`); data/current.csv of the 08-13/14 bundles | 147 | end of chain 2's deterministic half; the 14d/15e EL corpus | f8115e4f5587 (current.csv) |
| 15e acceptance input bundle | _archive_bundles/20260814_071007_post_EL_bundle.zip | 147 | the exact 15e (bundle, criteria) pair | 0bd1604a (whole zip) |
| Wave-15c chain | tests/test_stage_routing.py:208-243 | 776→760→22 | current pinned chain — counts only, no persisted survivor bytes | n/a |

**§2 premises:** chain numbers CONFIRMED. **"147-record corpus under docs/data/" — PARTIALLY WRONG**: `docs/data/study_input/` holds the 85/84-record pre-13d files; the 147-record artifacts live under the wave run dirs, and 147 is itself a *regression* corpus — current rules give 22 at EL. "Chain consumes an archived bundle" — RESOLVED as in-repo file (samples CSV). Repo-map correction: 33 zips but only 32 bundles.

---

## §3 HARNESS

### (a) Entry points the 15d/15e live runs used

**15e (runs J/K/L, 2026-08-15): a scratchpad Python harness calling `run_el_screen` directly — NOT in the repo.** The wave doc describes the run (`FIX_WAVE_15E_QUOTE_CLUSTER.md:695-706`) and discloses the mechanics ("aborted after ~4 minutes to escape a 10-minute harness-timeout ceiling and relaunched detached", :739-742) but carries no literal command line. The harness survives in a session scratchpad outside the repo:

`C:\Users\alere\AppData\Local\Temp\claude\S--Alejandro--projet-julien--prisma-hub--prisma-hub-v3-repo\d23aa140-1f9c-4d66-a09c-0de9162022b8\scratchpad\acceptance_harness_15e.py`

with invocations in its docstring (:7-11): `python acceptance_harness_15e.py preflight | J | K | L`. **Proof it is the exact producer** (re-run this session): its output dir's `runJ_batch5_EL_FULL.csv` and `runL_batch1_report.json` sha256 (`435bd774…`, `7b7fab2c…`) are byte-identical to `docs/data/wave15e_acceptance_runs/SHA256SUMS`. Mechanics: mocks tkinter + `metascreener.plugin_api` before importing (:39-58, same recipe as `tools/capture_el_il_goldens.py:91-123`); imports `plugins/06_el/plugin.py` by path (:61-67); reads the archived bundle zip **in-memory** with digest verification of bundle/corpus/criteria before any call (:72-77, criteria prefix `5dd51aaa6e2f3c33`); `preflight` asserts endpoint `http://localhost:11434/v1`, `llm_exclusion_allowed("EL") is False`, `PROMPT_VERSION == "EL_v3_nullquote"`, 147 records, exactly `[("EC-2","exclude","llm",0.6), ("EC-3","exclude","llm",0.6)]` (:85-109) — the meta's "REFUSING semantics" preflight (`wave15e_acceptance_runs.meta.txt:96-99`); then the product's own entry point verbatim:

```python
(full_rows, surv, counts, impacts, evals, cache_out, cancelled, report) = el.run_el_screen(
    parse, crits, model=MODEL, trunc_chars=TRUNC, batch_size=batch,
    use_cache=False, cache_in={}, cancel_event=threading.Event(),
    log_cb=_log, progress_cb=_prog, progress_evt=None)      # acceptance_harness_15e.py:134-138
```

Outputs written by the harness itself: `*_EL_FULL.csv` via `plugins._common.exporters._write_csv_bytes`, `*_report.json` = the engine's run report verbatim, `*_summary.json` composed (:142-168; committed `runJ_batch5_summary.json:2-31` matches).

**15d (harmoniser LLM refine acceptance, 2026-08-14): a different scratchpad harness, also headless.** `FIX_WAVE_15D_HARMONISER_LLM.md:277-284`: first attempt imported the test conftest (isolated store → 401 at the vendor default); "the harness was rebuilt conftest-free so the maintainer's real store resolved `http://localhost:11434/v1`, asserted before any call." Recovered at `…\dc7b3901-b084-4964-b068-43679d91fe72\scratchpad\acceptance15d_live.py`: loads harmoniser modules by path with a package shim (:13-35), asserts a local endpoint (:40-45), wraps `lc._openai_client_for` with a call-counting `BUDGET = 12` enforcer (:47-65), runs deterministic parse + `lr._llm_refine` twice (:96-101), and headlessly builds a real bundle via `bundle_mod.export_screen_a_bundle(...)` (:137-143). No committed artifact exists to digest-match; the confirmation rests on the doc + recovered script.

**Earlier waves:** `docs/data/wave12_local_runs/` and `wave14c_batch_runs/` contain no scripts — only frozen artifacts reduced from **bundle zips the app exported** (`wave12_local_runs.meta.txt:131-134`; `wave14c_batch_runs.meta.txt:93-101` — the five-bundle "full evening chain"), i.e. app-driven runs. The one **committed** headless driver is `tools/capture_el_il_goldens.py` (docstring invocation :33-40) — it drives all four stages (`run_screen` :144/:156, `run_el_screen` :197-209, `run_il_screen` :268-280) but is pinned by design to the default OpenAI endpoint (`_pin_endpoint`, :355-390) and `MODEL = "gpt-4o-mini"` (:68): a golden-capture tool, not a general (bundle, criteria) runner. `tests/_engine_probe.py` is a third headless pattern ("drive the real EL/IL engines from a clean interpreter", :7).

### (b) Criteria: a swappable input artifact, at two levels

**Level 1 — bundle member.** EL/IL read `criteria/criteria_harmonized.csv` from the zip (`plugins/06_el/screen.py:290-295`; `plugins/07_il/screen.py:292-297`). EH/IH's loader searches `["criteria/criteria_harmonized.csv", "criteria/harmonized.csv", "criteria/criteria.csv", "criteria.csv"]` (`plugins/04_eh/ui.py:402`; `plugins/05_ih/ui.py:402`) → `_load_criteria_from_text(text, stage)` (`plugins/_common/parser.py:371`). Swapping the set = supplying a bundle with a different criteria member.

**Level 2 — plain function parameter.** All four engines take criteria as a `CriteriaLoadReport` argument decoupled from any bundle: `run_el_screen(parse, criteria_report, *, model, trunc_chars, batch_size, …)` (`plugins/06_el/screen.py:458-471`); `run_il_screen` identical (`plugins/07_il/screen.py:460-473`); `run_eh_screen`/`run_ih_screen` → `plugins/_common/runner.py::run_screen(..., stage=…)` (`plugins/04_eh/ui.py:131-141`; runner is pure/headless, :56-217). The report is built from **CSV text from anywhere** (15e harness: straight from zip bytes; goldens tool: from a repo file). Criteria are NOT GUI state and NOT stage_state (`stage_state.py` holds readiness/policy/control state only).

**What is NOT a parameter** (resolved inside the engine per run from the settings store / env): endpoint (`resolve_openai_base_url`, screen.py:658; llm_client.py:145-154), context window (`resolve_context_window`, screen.py:667; llm_client.py:846-869), exclusion policy (`llm_exclusion_allowed`, screen.py:678-680; llm_client.py:206-228). The store is `%APPDATA%\metaScreener\settings.json` (`plugins/_common/settings.py:94-95, 121-139`); endpoint can come from `OPENAI_BASE_URL` (logged; screen.py:696-701). A headless harness inherits whatever store/env the process sees — the 15d 401 and 15e preflight exist precisely because of this.

### (c) GUI-only vs scriptable

**Scriptable (proven by actual headless runs):** EH/IH screening (`run_screen`), EL/IL screening (`run_el_screen`/`run_il_screen`), bundle loading with digest verification (`_load_bundle`, `06_el/screen.py:240-320`, no Tk), initial bundle creation (`export_screen_a_bundle`, `plugins/03_harmoniser/bundle.py:52-63`, driven headlessly by 15d), harmonisation deterministic + LLM-refined, post-stage bundle writing (`_export_next_bundle_zip` / `_write_llm_stage_bundle`, `plugins/_common/bundle.py:423, 589`), and settings-store writes (`update_settings`, `set_stage_override`, `apply_stage_fields` — plain functions).

**GUI-only in practice at HEAD:** the app entry point (`run.py:8-10` is exactly `MetaScreenerApp().mainloop()`; no CLI anywhere — even the EL/IL "standalone" shells are ttk.Frames with filedialogs, `plugins/06_el/standalone.py:70-71, 225-228`); the provider-choice/consent dialogs (scriptably replaceable by writing the store); and visual confirmation surfaces (15e left "three strings need eyes" undischarged because the run was headless — `FIX_WAVE_15E_QUOTE_CLUSTER.md:712-717, 799-803`).

**§3 premises:** "15d/15e were headless script runs" — CONFIRMED (byte-identity for 15e; doc + recovered script for 15d). **WRONG:** the harness scripts are findable in the repo — they exist only in session scratchpads under `%LOCALAPPDATA%\Temp\claude\…` and are unrecoverable from the repository if those dirs are cleaned. **WRONG:** "plugins/04_eh, 05_ih have screen.py" — only 06/07 do; 04/05 are `plugin.py` + `ui.py` over the shared `_common/runner.py` engine.

---

## §4 CALL ARITHMETIC + WALL CLOCK

### (a) The 294, and what the corpus actually is

**294 = record-criterion pairs at EL: 147 records × 2 LLM criteria (EC-2, EC-3).** The repo states the arithmetic verbatim: "calls_made is the exact no-cache arithmetic (147×2=294 at batch 1; ceil(147/5)×2=60; ceil(147/10)×2=30)" (`wave14d_invariance_runs.meta.txt:48-50`). Exactly two rows of the current-rules criteria table are `llm`@EL (EC-2, EC-3); IC-1 is `llm`@IL; IC-5 is `contains`@IL (unevaluated); the rest are deterministic (runDE_criteria_harmonized.csv rows). Corpus counts verified by CSV parse: every `*_EL_FULL.csv` in 14c/14d/15e = **147** data rows; `study_input/el_input_v3.1.0.csv` = **85**; `docs/data/eval_decisions_v1.csv` = **344** rows — the *human*-rater file (230 EL + 114 IL decisions, 3 raters), NOT the source of 294. Two corpora coexist: the 85-record frozen study corpus (human validation ran on it, N=85 per EL criterion, `eval_summary_v1.txt:20,32`) and the 147-record post-13d corpus (14c/14d/15e). **Caveat carried on the 147 itself:** it is a regression corpus; current post-15c rules give `776 → 16 → 760 → 738 → 22`, so a current-rules EL run would screen 22 records = 44 pairs, not 294 (`wave15e_acceptance_runs.meta.txt:24-28`).

**Canonical in-code formula** (`plugins/_common/run_estimate.py:100-125`):

```
pairs    = records × criteria                       (:108-111)
requests = ceil(records / batch_size) × criteria    (:113-125)
# "The engine batches records within a criterion and never mixes
#  criteria in one call" (:117-119)
```

### (b) General EL/IL live-call formula

The stage loops criterion by criterion (`plugins/06_el/screen.py:733-736`; `plugins/07_il/screen.py:781-798`); per criterion, items split cache-hit vs `to_call` (:756-777), then one HTTP call per (criterion, batch) — `chunked(items, max(1, batch_size))` at `llm_client.py:1545`. A call never mixes criteria.

```
calls = Σ_over_LLM_criteria ceil((records_at_stage − cache_hits_c) / batch_size)
      + reasks_made            (ONE re-ask per batch whose reply omitted records,
                                carrying only the omitted subset — llm_client.py:1722-1743;
                                residue counter no_answer_after_reask :1777-1780;
                                still-unanswered back-filled uncertain :1745-1761, never re-called)
      + error retries           (calls_made counts every attempt — :1491-1493;
                                adaptive halving on 429/oversize only — :1415, :1857;
                                response_format rejection flips to unconstrained and continues — :1819-1831)
```

Constrained decoding keeps re-asks rare: the JSON schema pins `minItems == maxItems == n` per call (:1045-1058, F-191/F-197). Batch-size source: module default 50 (`plugins/06_el/plugin.py:39`, `07_il/plugin.py:46`, envs `SCREENA_{EL,IL}_BATCH_SIZE`); settings rule D6 asks the provider — `recommended_batch_size` returns `LOCAL_BATCH_SIZE = 5` for keyless/local pairs (`plugins/_common/settings.py:564-570`; `stage_state.py:979, :986-1010`); the frozen runs used explicit 1/5/10 (per-run report provenance, e.g. `runJ_batch5_report.json:18`).

**The 414, decomposed** (`wave15e_acceptance_runs.meta.txt:37-42`): runJ batch 5 → ceil(147/5)×2 = **60**; runK repeat → **60**; runL batch 1 → 147×2 = **294**; total **414**, `reasks_made=0` in all three, cache OFF (`cache_hits=0 | to_call=147` per criterion, meta :35; log format `06_el/screen.py:777`), declared before the first request and spent as declared (meta :42-43). One off-ledger disclosure: an aborted first runJ attempt burned an estimated 12–25 calls, no artifact (meta :43-47). Historical cross-check: 14d runs F/G/H/I = 294/60/60/30 calls at batch 1/5/5/10 (`wave14d_invariance_runs.meta.txt:29-32`); 14c runE made 56 not 60 — 17 pairs served from runD's cache (F-101 in the field, `wave14c_batch_runs.meta.txt:31-32, 42-47`).

### (c) Latency on the local qwen2.5:7b setup

The only wall-clock totals in the repo are the three 15e meta lines (`wave15e_acceptance_runs.meta.txt:37-39`; grep for `wall=` across docs/data hits only these): runJ 60 calls / 528 s; runK 60 / 484 s; runL 294 / 1020 s. Model `qwen2.5:7b`, endpoint `http://localhost:11434/v1`, temp 0.0, `context_window=4096`, `trunc_chars=1500` (meta :32-34).

| run | s/call | s/pair | **min per 100 calls** |
|---|---|---|---|
| runJ (batch 5) | 528/60 = 8.80 | 1.80 | **14.7** |
| runK (batch 5) | 484/60 = 8.07 | 1.65 | **13.4** |
| runL (batch 1) | 1020/294 = 3.47 | 3.47 | **5.8** |
| all 414 | 2032/414 = 4.91 | 2.30 | **8.2** |

Batch-5 calls ≈ 8–9 s each; batch-1 ≈ 3.5 s each, but a batch-1 run costs ~2× the wall clock per pair (1020 s vs ~500 s for the same 294 pairs). The repo's own planning constant is coarser: "~10-15 s/call" (meta :46). In-app estimation uses only a per-session measured rate (`remember_call`/`observed_rate`, `llm_client.py:1505-1517`, `run_estimate.py:82-92, 162-167`); the module refuses a hard-coded constant, citing F-125 (`run_estimate.py:25-32`). The wave-12/14c/14d metas record no wall-clock durations.

**Hardware attribution:** CPU-only (`total_vram="0 B"`, F-154) is recorded **only for the 14c capture machine** (`wave14c_batch_runs.meta.txt:108-110`); the 14d/15e artifacts record no hardware at all. Same-machine is plausible (same endpoint, model, window) but not asserted by any artifact.

**§4 premises:** 294 decisions CONFIRMED (= EL pairs, not cross-stage, not the eval CSV); 147 corpus CONFIRMED for 14c/14d/15e (with the 85-vs-147 and regression-corpus corrections); "CPU-only qwen2.5:7b" **PARTIALLY CONFIRMED** (CPU-only is an artifact-recorded fact only for 14c); 414 calls CONFIRMED.

---

## §5 CACHE + RUN INDEPENDENCE

### (a) The cache key, exactly

`plugins/_common/llm_client.py:2006-2108`, `_cache_key(*, prompt_version, model, rendered_prompt, endpoint, temperature=0.0)`: SHA-256 over a stable JSON of exactly five fields — `prompt_version` (e.g. `"EL_v3_nullquote"`, `plugins/06_el/prompt.py:30`), `model`, `endpoint` (**required, not defaulted** — F-89, :2050-2053; hashed verbatim, :2066-2073), `temperature` (hashed unconditionally, 0.0 ≡ omitted, :2034-2037), and `rendered_prompt` — a **one-item render** of the stage's real prompt builder for the (criterion, record) pair (`plugins/06_el/screen.py:446-448`; serialiser `_render_prompt_for_key`, llm_client.py:1994-2003). The call-site comment states the design: "The prompt is rendered for a batch of one because the cache is keyed per (a_id, criterion) while the real call batches many items" (`06_el/screen.py:432-436`). Because the user message embeds the full criterion pack — `id, type, operator, target, what, how, label, threshold` (`prompt.py:61-70`) — plus the record fields truncated at `trunc_chars`, "criterion content, record text, field truncation and the prompt template are all covered without being named" (:2023-2026). Pinned by `tests/test_cache_key.py` (criterion-content edits with constant id change the key :109-134; endpoint verbatim/required :137-230; model :251-253; temperature :255-262; record text :264-268; truncation :285-290; EL≠IL via PROMPT_VERSION :299-302; PYTHONHASHSEED stability :324-353). Golden re-key: `tools/rekey_cache_goldens.py` ("A RE-KEY, NOT A RE-CAPTURE", :9-11) + `tests/test_golden_rekey.py`.

### (b) Six criteria sets over the same records — contamination?

**Criteria text enters the key via the prompt, so differently-worded sets cannot collide.** Any content-byte difference in a criterion → disjoint keys. Residual behaviours to design around:

1. **A criterion byte-identical across two sets IS a cache hit across sets** (the key sees only the single criterion, never the surrounding group). Not wrong answers — but the runs are then **not independent measurements** (exactly F-101's field observation: 14c runE, 56 calls instead of 60).
2. **Batch composition never reaches the key** (one-item render): an entry produced inside a batch-50 call — where F-86/F-197/F-201-class batch effects may have shaped it — is served indistinguishably to any later run. This is F-101's core.
3. **F-102 (open, Medium)**: a mid-retry truncation step-down caches the answer under the un-stepped prompt's key (`03_findings.md:132`).

### (c) Cleanest isolation

- The key already covers criteria text — nothing needed for sets that differ in wording.
- **There is no on-disk cache directory.** The cache is a **bundle-zip member**: `cache/EL_cache.jsonl` (`plugins/06_el/plugin.py:44`), `cache/IL_cache.jsonl` (`plugins/07_il/plugin.py:51`) — loaded into memory from the opened bundle (`06_el/ui.py:864-872`), threaded `cache_in`→`cache_out` (`screen.py:513, 798-814`), written into the next exported bundle (`ui.py:1546-1557`). Provider/model/endpoint isolation happens inside the key, not in directory layout. The harmoniser LLM path has no response cache at all.
- **Disable:** the "Use cache" checkbox / env defaults `SCREENA_EL_USE_CACHE` / `SCREENA_IL_USE_CACHE` (`plugins/06_el/plugin.py:40`, `07_il/plugin.py:47`); unticked ⇒ `cache_in={}`, no reads/writes; since F-104's fix an unticked export preserves the incoming cache member (`bundle.py:768-772`). Note the 15e harness simply passed `use_cache=False, cache_in={}`. Any non-zero temperature also re-keys everything (`06_el/ui.py:508`).
- **The register's own instruction for exactly this experiment:** "Any batch-invariance measurement must run with the cache off" (F-101 cell, `03_findings.md:131`).

### (d) F-101 status and bite

F-101 (`03_findings.md:131`, Medium, **open since wave 6**, :330): "The cache key hashes a synthetic one-item prompt, so `batch_size` is invisible to it. Entries produced at `batch_size=50` are served indistinguishably to a run at `batch_size=1`, and vice versa." Field measurement at 14c (the 56-call runE). F-197 makes it worse: batch size is now known to change the verdict, and the wave-9 F-89 re-key landed WITHOUT a batch discriminator, so adding one is now a second full re-key. **Where it bites this design:** if arm A runs batch 1 and arm B batch 5 over the same records with cache on, B's lookups hit A's entries pair-by-pair (`06_el/screen.py:764-774` lookup; :798-814 write-back) — B partially replays A instead of measuring batch-5 behaviour, biased toward A's regime, and the cross-arm hit count is invisible (only a normal `cache_hits=N` is logged, :776-777). **Remedy: run every arm cache-off.**

**§5 premises:** F-101 subject/openness CONFIRMED (scoped wider than the numeral: blind to whole batch *composition*). **WRONG:** cache key "in llm_client.py or evaluator.py" — `evaluator.py` contains no cache code (grep: no matches). **WRONG (implicit):** an application cache directory exists — it does not; the cache is a per-stage bundle member.

---

## §6 PRIOR ART

### (a) Existing multi-scenario machinery — none for criteria sets

**No multi-criteria-set or multi-scenario harness exists anywhere in the repo.** The only "multi-X" machinery is multi-**rater** (eval grids) and multi-**batch-size** (14d/15e run dirs — produced by hand-driven runs, then frozen). Tool inventory (`tools/` holds exactly: `audit_decorators, audit_imports, capture_el_il_goldens, check_encoding, derive_register_totals, eval_grid_filler_synthetic, eval_grid_generator, eval_ingest, measure_prompt_size, rekey_cache_goldens`):

- `eval_grid_generator.py` — multi-RATER XLSX adjudication grids from one stage-filtered CSV + one criteria CSV (:6-45; CLI :773-795). Reusable generic pieces: `load_llm_criteria` (:148-173), seeded outcome-stratified `stratify_and_partition` (:189-259), `partition_all_stages` (:266-290). One produced instance: `docs/data/grids/` (seed=42, 3 raters, EL=EC-2,EC-3, IL=IC-1; manifest carries an F-168 banner — rated records are the PRE-13d 85/84 chain).
- `eval_ingest.py` — ingests filled grids, joins human vs LLM decisions polarity-aware, writes the four `eval_*_v1` artifacts (:6-58). Pure-python metrics kernel reusable as-is: `_confusion_matrix` :489-512, `cohen_kappa` :515-545, `fleiss_kappa` :548-605, `majority_vote` :612-626, `status_to_canonical` :124-143.
- `eval_grid_filler_synthetic.py` — test-only deterministic grid filler (:8-11), importable (:25-27).
- `capture_el_il_goldens.py` — the ONLY committed script that runs the full EH→IH→EL→IL chain headless (chain plumbing `_run_eh_and_ih_to_get_el_input` :140-159; EL→IL `el_*`-column strip :252-254, :445-450) — but endpoint-pinned (F-89) and single-hardcoded criteria set (:77).
- `measure_prompt_size.py` — renders real EL/IL prompts over the golden corpus vs a window; "calls no model, opens no network connection, writes nothing" (:7-27). The right pre-flight for each new criteria group.
- `derive_register_totals.py` — findings-register tooling; irrelevant here.

### (b) How `TestTheChainAsRouted` drives the funnel — and what it does NOT do

Call chain: (1) criteria via the real translator, no golden file — `thr._harmonise_to_csv(out)` (`test_stage_routing.py:224`, helper in `test_harmoniser_regression.py:47-89` reproducing the GUI's free-text path with no LLM and no widgets); (2) corpus via `_parse_csv_tolerant_text` on the samples aggregate (:226-228); (3) EH via `run_screen(parse, _load_criteria_from_text(crit_text, "EH"), ev, stage="EH")` (:231-235); (4) IH on the survivors re-wrapped as a `ParseReport` (:237-243). **It stubs nothing** beyond the suite-wide conftest mocks of tkinter/plugin_api (`tests/conftest.py:24-57`) — it makes zero LLM calls **because it runs only EH and IH and stops at the 22 post-IH survivors**. `helpers_fake_server.py` is a `/v1/models` discovery fixture (cannot serve completions); `_engine_probe.py` is a separate seam that patches `_has_openai_key`/`_openai_client_for` with a deterministic fake client and calls `run_el_screen`/`run_il_screen` end-to-end (:34-58, :78-82, :102-105; used by `test_view_smoke.py:837`). A third EL/IL-without-GUI mechanism is **cache replay**: `test_el_regression.py::_el_to_csv` (:94-151) runs the real engine with env popped (:112-119) so every pair must be served from the committed golden cache.

### (c) Verdict for a 6-set × 4-stage experiment

**Reuse, not rebuild:** the four stage engines (`run_screen`; `run_el_screen`/`run_il_screen` with the exact signature demonstrated at `capture_el_il_goldens.py:200-209/:268-280`); the chain plumbing (`_run_eh_and_ih_to_get_el_input` + the `el_*` strip + the ParseReport survivor-rewrap); criteria production (`_harmonise_to_csv` for free-text groups; `_load_criteria_from_text` / `_parse_criteria_harmonized_csv` for hand-authored CSVs); headless scaffolding (`_setup_headless_imports` + `_import_plugin`); 15e's preflight-and-digest discipline; `measure_prompt_size.py` as per-group pre-flight; and, if human agreement enters the design, the partitioner + kappa kernel from the eval tools.

**Genuinely missing (must be built):** (1) the loop itself — nothing iterates over more than one criteria set; (2) a set-keyed output layout + cross-set aggregator (all existing writers hardcode single-instance filenames); (3) EL/IL responses for new sets — every new criteria text voids the golden cache by construction, so per set: live local model (14d/15e pattern), live capture, or a generalized `_engine_probe`-style fake client (its current `run_flag_only` hardcodes one synthetic scenario, :84-100); (4) a run-manifest emitter for experiment provenance (the SHA256SUMS + meta.txt + freeze-test discipline exists per wave but is hand-assembled, not a tool).

**§6 premise:** **WRONG:** "TestTheChainAsRouted drives the four-stage funnel" — it drives EH+IH only ("The deterministic funnel", docstring :209); EL/IL are never invoked. The repo's only full four-stage driver is `capture_el_il_goldens.py` (live API).

---

## §7 BUDGET GUARD + PROMPT LENGTH

### (a) Where criteria text enters the rendered EL/IL prompts

EL and IL each own a byte-identical builder `_build_llm_messages_for_criterion(criterion, items, trunc_chars)` (`plugins/06_el/prompt.py:47-88`; `plugins/07_il/prompt.py:37-78`). Exactly two messages: a fixed system string (measured 609 chars) and one user message = `json.dumps({"criterion": c_pack, "items": items_pack})` (:87). Criteria text enters via `c_pack`'s `label` and `what` (:61-70), filled from the harmonised table (`label = c.label or c.source_text`, `what = c.what_list` — `06_el/screen.py:711-720, 742-751`). **One criterion per prompt: criteria COUNT multiplies calls, never lengthens a prompt** (engine loop `screen.py:736-796`; guard's worst-call scan mirrors it, `llm_client.py:902-914`). `items_pack` carries `a_id, title, abstract, keywords` for every batched record, each independently truncated at `trunc_chars` (default 1500, `06_el/plugin.py:38`) — all three text fields ship regardless of the criterion's target (`tools/measure_prompt_size.py:124-127`). EH/IH build no prompt at all.

### (b) Per-provider window config at HEAD

- `CONTEXT_WINDOW_DEFAULT = 4096` (`llm_client.py:749`), measured at wave 15b ("a 3,537-token prompt passed untouched; a 7,254-token prompt was truncated"; server keeps the LAST ~half-window on overflow — :750-761; `FIX_WAVE_15B_CONTEXT_GUARD.md:9-17`).
- `HOSTED_CONTEXT_WINDOW_DEFAULT = 128_000` (:763-779), applied only when the stage's resolved endpoint is a paid vendor (`_hosted_default_applies`, :822-843).
- `resolve_context_window(stage)` (:846-869): stored `context_window >= 512` wins unconditionally; else 4096 unless paid-vendor → 128 000; ships `None` (`settings.py:204-215`).
- `provider_detect.py` and `recommended_models.json` carry NO window config (greps: no matches).
- **The guard REFUSES pre-run**: each engine calls `enforce_context_budget(...)` once, before the criterion loop, with every prompt of the run rendered (`06_el/screen.py:703-731`; `07_il/screen.py:705-733`); it raises `ContextBudgetExceeded` when `estimate + reserve > window` ("landing exactly on the window passes", :926-927, :942); the refusal message names the worst criterion/batch and the derived `max_safe_batch` (:988-1013) — **reported, not applied**; no truncation, no auto-split; zero calls spent (`FIX_WAVE_15B_CONTEXT_GUARD.md:30-36, 119-131`). Backstop at the first real call: `TokenEstimateDrift` (:881-885).

### (c) chars/token calibration

`CHARS_PER_TOKEN = 4.5` (`llm_client.py:781`), provenance in the constant's docstring (:782-802): wave-15b probe 1, the server's own `usage.prompt_tokens` over the frozen 147-record corpus, 8-point table (2,699 chars/600 tok = 4.50 … 17,515/3,537 = 4.95); "4.5 is near-exact on small payloads and ~10 % conservative on large ones — conservative in the only safe direction for a refusing guard" (:796-797). Estimator: `tokens = ceil(chars/4.5) + 30` framing (:804-814); reply reserve `REPLY_RESERVE_PER_VERDICT = 80` × batch (:807-809, :911). Pinned by `tests/test_context_guard.py:118-130` (constants + estimator ≥ reality on all 8 probes). `measure_prompt_size.py:44-55` records the calibration ("Treat 4.5 as the realistic figure for qwen2-class tokenizers").

### (d) How long a criteria group's criterion can get before refusal at batch 5, window 4096

Step 1 — refusal iff `ceil(chars/4.5) + 30 + 80×5 > 4096` → total rendered prompt ≤ **16,497 chars** (16,498 refuses; boundary pinned `test_context_guard.py:153-160`).

Step 2 — measured with the real EL builder over the committed 147-record 14d corpus + committed criteria (EC-2/EC-3), trunc 1500 (re-run, engine-faithful float threshold): system 609 + JSON envelope 26 + fixed criterion-pack fields 127 = **762 chars fixed overhead**; batch-5 items block over 147 records: n=30 batches, min 2,072 / median 6,768 / **max 9,334** chars; worst full prompt 10,316 chars ≈ 2,323 est tokens + 400 reserve = 2,723 — comfortably under 4,096 (consistent with the 15B doc's batch-10 worked example that refuses at 4,723 with `max_safe_batch = 8`, `FIX_WAVE_15B_CONTEXT_GUARD.md:144-154`).

Step 3 — the criteria-text budget (serialized `label`+`what` JSON chars): 16,497 − 762 − 9,334 (worst batch) = **≈ 6,400 chars serialized**. The harmonised rows ship the same prose in both `label` and `what`, so each prose char costs ≈2 serialized chars: **≈ 3,200 chars of criterion prose** before the batch-5 refusal fires on this corpus — roughly **30× EC-2's 107-char prose**, the largest committed criterion. (Median-batch headroom: ≈ 8,967 serialized / ≈ 4,480 prose.)

**Corpus dependence:** on a saturated corpus (every record filling title+abstract+keywords to 1500), a batch-5 items block alone is ≈ 22,835 chars → ≈ 5,674 tokens with reserve — **batch 5 does not fit 4,096 at any criteria length**; the guard refuses and reports a smaller `max_safe_batch`. The ≈3,200-prose-char figure is a property of this freeze corpus's actual field lengths; the guard re-derives the real bound per corpus by rendering (:917-924).

**§7 premises:** window 4096 CONFIRMED (a default; stored override ≥512 wins; paid vendor → 128k; one 15B sentinel records the maintainer restarting Ollama with `OLLAMA_CONTEXT_LENGTH=8192`, `FIX_WAVE_15B_CONTEXT_GUARD.md:89-107` — but the repo ships `context_window: None`, so an unconfigured install budgets 4,096). Batch 5 CONFIRMED as the local/keyless D6 default (module default is 50). Refusal-not-truncation CONFIRMED (the two truncations that do exist are the configured per-field `trunc_chars` cap and the *server's* silent half-window keep — the failure the guard prevents). **WRONG (implicit):** that a criteria *group's combined* length is what the guard budgets — every EL/IL prompt carries exactly ONE criterion; group size multiplies calls only. (Criteria-grouped budgeting exists only on the harmoniser path — "the harmoniser budgets CRITERIA per call, not records per batch", `llm_client.py:983-984`.)

---

## §8 AUTHORING CONSTRAINTS + OPEN EDGES

### (a) Full legality table

There is **no single validator** — four independent layers with different vocabularies, defaults, and consequences. Only Layer 1's errors block anything (export); the bundle-read loaders run no `_validate_row` at all (F-205 cell: "no `_validate_row` runs anywhere on the bundle-read path").

**Layer 1 — Harmoniser `_validate_row` (authoring time; errors block export)** — full rule list in §1.4 above; the load-bearing rows for authoring:

| rule | rejected / accepted | cite |
|---|---|---|
| stage ∈ `EH,IH,EL,IL` | else ERROR | inference.py:336-338 |
| type ∈ `include,exclude` | else ERROR | :344-346 |
| operator ∈ 9-word vocabulary | else ERROR | :348-350 |
| **stage↔operator**: EH/IH = the 8 deterministic ops; EL/IL = `llm` only | ERROR both directions (`contains@IL` and `llm@EH` both blocked) | :360-365; map parser.py:65-72; pinned tests/test_stage_routing.py:111-133 |
| target required + must resolve to corpus columns (aliases: language→lang, journal/source/conference→venue, type/…→doc_type, link/website→url) | else ERROR; mutating canonicalisation | :367-375; `TARGET_ALIASES` parser.py:212-225; `_canonicalize_targets` :228-274 |
| multi-target = comma list, each part canonicalised | legal everywhere | parser.py:237; runtime split `_common/parser.py:161-168` |
| `between` exactly 2 values | ERROR | :383-384 |
| `gte/lte/equals` >1 value | **warning only** (13d decision — exports clean) | :385-386; FIX_WAVE_13D_INFERENCE.md:307 |
| `llm` exactly 1 sentence | ERROR | :387-389 |
| threshold: EH/IH blanked w/ warning; EL/IL blank→0.60, non-numeric or ∉[0,1] ERROR | | :391-405 |
| `enabled` | **not validated at all** | absence in :331-407 |
| type↔stage polarity | **not validated** (= F-206) | absence; 15C doc :166-168 |
| duplicate ids | not checked by the validator (linter NOTICE only) | 07_criteria_parsing.md:547-548 |

**Layer 2 — linter (warn-only, never blocks; `plugins/03_harmoniser/linter.py`, design FIX_WAVE_13C_LINTER.md):** `target-mismatch` (F-166; skipped for `llm` rows — F-175, :260-265) | `dropped-operand` (F-167; discrete operators only, :315; range-idiom discounts :330-361) | `inert-at-stage` (F-65 warn-twin, :415-435) | `unresolved-target` NOTICE (:459-475) | `duplicate-id` NOTICE ("only the last one will be kept", :478-500) | `threshold` NOTICE (:503-536) | `unreadable-row` NOTICE (:456, 559-576).

**Layer 3 — EH/IH bundle-read loader (`plugins/_common/parser.py:371-448`, tolerant):** stage-filter match, or **no stage column → every row belongs to the requested stage** (F-205; :389, :395-399); `enabled` truthy-set — **present-but-blank cell DISABLES** (:401-403, :46, :157-158); blank id → `<STAGE>_ROW_<n>` (:405); blank/unknown type → include w/ warning (:406, :423-425); **blank operator → `equals`** (:409); bad threshold → warned, ignored (:415-421); missing target → warned, criterion treated MISSING/PASS_FLAGGED (:427-428); include/exclude contradiction warnings only for `equals`/`in_list` (:451-478, F-109-annotated gap).

**Layer 4 — EL/IL bundle-read loader (`plugins/06_el/screen.py:322-417`; twin `07_il/screen.py:324`):** stage-filter exact; **no stage column → `""` never matches → ZERO criteria load** ("No EL criteria found (stage=EL)", :414-415); blank = enabled (diverges from Layer 3; :346-347); blank id → row skipped silently (:349-351); blank/invalid type → row **SKIPPED with warning**, never guessed (F-04; :353-369; `tests/test_criteria_polarity.py:9-17, 52-57`); **blank operator → `llm`** (:370 — the other half of F-205); blank targets → `["abstract"]` (:372); bad threshold → 0.6 silently (:386-390).

**Cross-cutting:** multi-target deterministic evaluation is union over all listed targets since F-204's fix (`evaluator.py:202-205, :225-236`; `tests/test_multi_target_criteria.py:49-62`; F-204 row "S (done)"); `in_list` is exact set membership, not substring (`tests/test_in_list_operator.py:27-29`); direction-of-harm is keyed on `ctype`, never the stage (`evaluator.py:238-241`; `GATE_TABLE` keyed `(ctype, decision)`, `verdict_gate.py:93-98`); the harmoniser structured-import normalizer is a third `enabled` semantics (false only for `{"0","false","no","off"}`) with operator aliases (`parser.py:499-536`).

### (b) F-205 — exact current state

Register row **verbatim** (`docs/internal/diagnostic/03_findings.md:235`, Medium, correctness/validation):

> **A criteria CSV without a `stage` column loads as every-row-at-the-requested-stage, and a blank operator defaults differently per consumer.** `plugins/_common/parser.py::_load_criteria_from_text` assumes every row belongs to the stage that asked when the input lacks a `stage` column entirely, so one hand-authored table of `contains` rows can silently become both an EH and an IH criteria set; and a blank operator becomes `equals` there while `plugins/06_el/screen.py::_parse_criteria_harmonized_csv` makes it `llm` — two silent defaults for one absent value, diverging by stage family. | Surfaced by wave 15c's router reading …; no `_validate_row` runs anywhere on the bundle-read path … | … the F-65 class one layer down, guarded at authoring time since wave 15c but unguarded on the read path. | Validate on read, or refuse a stage-less table with a stated reason; unify the blank-operator default across consumers … Cross-ref F-65, F-174, F-176. | S

**Status: OPEN at HEAD** (no "Fixed in" cell; filed at 15c adjudication, "filed at adjudication, not fixed this wave", `FIX_WAVE_15C_STAGE_ROUTING.md:161-166, 328-330`). **Zero code sites**: repo-wide grep for `F-205` hits exactly three doc lines (`FIX_WAVE_15C_STAGE_ROUTING.md:162, :328`; `03_findings.md:235`) and nothing in `plugins/`. **Actual behavior splits by stage family, and the register states only half:** EH/IH assume-all (every enabled row loads at the requesting stage — run the same file through plugins 04 and 05 and each takes all rows); **EL/IL drop-all** (missing column → `""` → zero criteria, one aggregate warning). Blank-operator half: `equals` (parser.py:409) vs `llm` (screen.py:370). **To exercise:** hand-author a stage-less (and/or operator-blank) `criteria_harmonized.csv` and feed it through the bundle-read path — never through the harmoniser GUI, whose exporter always writes the stage column and whose validator gate would run. **To avoid:** always write explicit `stage` and `operator` per row.

### (c) F-206 — exact current state

Register row **verbatim** (`03_findings.md:236`, Low, hygiene/validation):

> **`_validate_row` never checks type-vs-stage polarity: an `exclude` criterion at IH passes clean.** The wave-15c cross-check closed operator-vs-stage; type-vs-stage (include→I\*, exclude→E\*) still has no validator anywhere in the harmoniser. | … The evaluator honours `ctype` directly, so a polarity-mismatched row still evaluates correctly BY ITS TYPE — the stage taxonomy is silently violable but no verdict is wrong … | The stage names stop meaning what they say … | Extend the wave-15c cross-check … with the polarity half, as a warning first … *(Wave 15e note: the new gate table is keyed on `ctype`, never the stage, precisely so it does not depend on this row landing …)* | XS

**Status: OPEN at HEAD**, explicitly deferred by 15e ("F-206 can land in any later wave, as the taxonomy hygiene its Low severity says it is", `FIX_WAVE_15E_QUOTE_CLUSTER.md:90-91`). **Code sites (independence notes, not fixes):** `verdict_gate.py:36-43`; `06_el/screen.py:893-904`; `07_il/screen.py:895-904` — each stating a mismatched row lands on its correct direction-of-harm rule by construction. **Traced behavior:** no layer rejects a polarity-mismatched row, and every layer decides correctly by `type` — an `exclude@IH` row FAILS matching records exactly as an exclude should, just at an "inclusion" stage; explicit polarity is honoured at EL/IL whatever the stage (`tests/test_criteria_polarity.py:52-57`; four-arm matrix at `tests/test_flag_only.py:176-189`). Consequence: verdicts correct; per-stage report surfaces mislabel. **To exercise:** `type=exclude, stage=IH` (deterministic op) or `type=exclude, stage=IL` / `type=include, stage=EL` (op `llm`) — all validate clean and run. **To avoid:** follow the convention include→IH/IL, exclude→EH/EL; nothing enforces it.

**§8 premises:** F-205/F-206 subjects CONFIRMED (F-205 is two-part — the operator-default divergence is the second half; and the EL/IL absent-column behavior is drop-all, which the register does not state); both OPEN CONFIRMED. **WRONG:** `_validate_row` in `plugins/_common/parser.py` (see §1). **WRONG:** "code sites referencing F-205: 06_el/screen.py, 07_il/screen.py, verdict_gate.py" — those three reference **F-206 only**; F-205 has zero code sites.

---

## OPEN QUESTIONS FOR THE MAINTAINER (facts only he has)

1. **Hardware for the 14d/15e timing baselines.** CPU-only (`total_vram="0 B"`) is artifact-recorded only for the 14c capture machine; the 15e wall-clock numbers (8–9 s/call at batch 5) carry no hardware record. Were runs J/K/L on the same CPU-only machine, and is that the machine wave 16 would use?
2. **Current standing server window.** The 15B doc records one sentinel of Ollama restarted with `OLLAMA_CONTEXT_LENGTH=8192`; the repo ships `context_window: None` (→ 4096 budget). What is the window on the machine that would run wave 16, and is a stored `context_window` override set in his `settings.json`? (All §7 arithmetic assumes 4096.)
3. **Which corpus is "the same aggregate bundle" for wave 16?** Three chains coexist (85 / 147 / 22). Running new criteria groups through 04–07 from the 776-record aggregate under *current* rules will produce whatever funnel the new groups define — but if any comparison to the frozen 14c/14d/15e EL baselines is wanted, that comparability exists only on the 147 regression corpus (bundle `20260814_071007_post_EL_bundle.zip`). Which comparability matters?
4. **Should the 22-survivor set be persisted?** The current pinned chain's EL input exists nowhere as bytes — only as counts in the test. A wave-16 baseline run would materialize it for the first time; worth freezing?
5. **His local settings store.** A headless harness inherits `%APPDATA%\metaScreener\settings.json` (per-stage endpoint/model/batch overrides, if any). What does his store currently resolve per stage? (The 15e preflight-assert pattern covers this, but the expected values must come from him.)
6. **The scratchpad harnesses.** `acceptance_harness_15e.py` and `acceptance15d_live.py` exist only in temp-directory session scratchpads and are unrecoverable if cleaned. Should wave 16 commit a generalized descendant into `tools/` (the report's §6 verdict suggests yes)?
7. **Authoring route for the 5 new groups.** Free text through the translator (exercises inference branches 1–6 + F-109-adjacent breadth — the six-branch trigger vocabulary then *shapes* which stage each criterion lands in) vs hand-authored harmonized CSVs (exact stage control, exercises `_validate_row` and, if desired, the F-205/F-206 edges deliberately)? Both are supported; the choice decides which subsystem the experiment actually probes.
8. **Model identity details.** The 14d meta's "Not recorded" block: quantisation, exact model tag, `num_ctx` at serve time. If wave 16 wants comparable numbers, he must confirm the `qwen2.5:7b` tag/quant currently pulled.

## PREMISES CORRECTED: 13

Wrong outright (11):
1. **"_validate_row … in plugins/_common/parser.py"** — it lives in `plugins/03_harmoniser/inference.py:331-407`; `_common/parser.py` has only tolerant warn-and-coerce loaders. (Likewise the 11-column schema is owned by `plugins/03_harmoniser/exporters.py:74-86`.)
2. **"Routing … the keyword-in-text rule"** — keyword-in-text is branch 6 of six authoring-time inference branches, all now routing to the heuristic stages; inference fills only blank cells; at execution time routing is the `stage` column literal, nothing else.
3. **"F-109 vocabulary hoisting"** — F-109's subject is the operator vocabulary's integrity (≥7 hand-maintained copies, no STATUSES constant, unreachable `regex`, mistuned contradiction check; open at HEAD). The hoisting was wave 15c *applying F-109's discipline* to `EXECUTABLE_BY_STAGE`.
4. **"The frozen 147-record corpus under docs/data/"** — `docs/data/study_input/` is the 85/84-record pre-13d corpus; the 147-record artifacts live under the wave14c/14d/15e run dirs, and 147 is a regression corpus (current rules → 22 at EL).
5. **15d/15e harness entry points findable in the repo** — neither is committed; both recovered from session scratchpads, 15e proven the exact producer by byte-identical SHA256s against the committed SHA256SUMS.
6. **"plugins/04_eh … 07_il screen.py"** — only 06/07 have `screen.py`; 04/05 are `plugin.py`+`ui.py` over the shared `plugins/_common/runner.py` engine.
7. **"How TestTheChainAsRouted drives the four-stage funnel"** — it drives EH+IH only, stops at 22, stubs nothing, makes zero LLM calls.
8. **Cache key "in llm_client.py or evaluator.py"** — `llm_client.py:2006` only; `evaluator.py` contains no cache code.
9. **An on-disk cache directory (per-provider/per-model)** — none exists; the cache is a per-stage JSONL member inside each bundle zip; isolation lives inside the key.
10. **"How long a criteria GROUP can get before the guard fires"** (group-length framing) — every EL/IL prompt carries exactly one criterion; group size multiplies calls, never prompt length; the §7(d) bound is per criterion (≈3,200 prose chars at batch 5 / window 4096 on the freeze corpus).
11. **"Code sites referencing F-205: 06_el/screen.py, 07_il/screen.py, verdict_gate.py"** — those reference F-206 only; F-205 has zero code sites (three doc lines total).

Partially wrong (2):
12. **"CPU-only qwen2.5:7b setup"** — model/endpoint/temp confirmed for 14c/14d/15e; CPU-only is artifact-recorded only for the 14c machine; 14d/15e artifacts record no hardware.
13. **`_archive_bundles` as a bundles directory** — 33 zips, but one (`metaScreener_JORS_LaTeX_REVISED.zip`) has no manifest and is a LaTeX manuscript; 32 are bundles.

Confirmed as stated (for the record): the pinned chain 776 → −16 → 760 → −738 → 22; 294 decisions = 147×2 EL pairs; 414 = 60+60+294 with zero re-asks; samples ship the IC/EC criteria the chain's derivatives consume; local window 4096; batch 5 as the local/keyless default; refusal-guard (not truncation) semantics; F-101 open and batch-blind; F-205 = stage-column-absent semantics (plus its operator-default half); F-206 = type-vs-stage polarity unvalidated; both open at HEAD; 15d/15e runs headless.

## SESSION COMPLETE

This recon session is **complete**. **Zero live LLM calls were made** (declared budget 0, spent 0 — no network access of any kind; every measurement was offline rendering/hashing/counting). **Git state untouched**: no branch, no commit, no edit to any existing file; the only filesystem change is this untracked report. Final verification (run at close):

```
$ git status --porcelain
?? docs/internal/RECON_WAVE_16.md

$ git rev-parse HEAD
556daa71bb3b9f3eb11e4ebc558d8e9e96cf8090
```
