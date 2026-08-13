<!-- SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo -->
<!-- SPDX-License-Identifier: MIT -->

# Wave 13e — the criteria preview: what exists, what it costs, what it cannot do

**Branch:** `fix/wave-13e-preview` off `main` @ `a790f9d`, working tree clean,
`origin/main` in sync (0 ahead, 0 behind). **Date:** 2026-08-12.
**Test baseline:** 1765 passed, 7 skipped (read from the run, not predicted).
**Goldens:** `tests/golden` tree object `050b3575` (`git rev-parse HEAD:tests/golden`),
and `git diff --stat main -- tests/golden` empty — all nine files byte-identical to
`main`. (This paragraph originally flagged the undocumented "golden aggregate
`9b7fe3e2`" carried by earlier wave docs. Session B swept it: 71 derivations tried,
none reproduces it, and it is now retracted everywhere it appears. The tree object
above is the reproducible replacement.)
**Mode for this commit:** read, execute, measure. **No feature code was written.**
No source, test, golden, sample, register row or user-facing document was modified;
this file is the only one added.
**Network:** none. No Ollama, no vendor API. Every LLM-path measurement below was
taken against the fake client in `tests/_engine_probe.py`, and the absence of network
traffic was asserted by an audit hook, not assumed.

## Evidence conventions

**EXECUTED** means a program was run and the output is transcribed. **READ** means
a file was inspected and nothing was run. Every load-bearing number below is
EXECUTED. Where a claim rests on reading alone it says so.

Two instruments are used repeatedly and are worth naming once:

- **the write-audit hook** — `sys.addaudithook` recording every `open` in a write
  mode plus `os.mkdir`/`os.remove`/`os.rename`. When a section says "zero file
  writes", that is this hook returning empty, not an inspection of the source.
- **the Tk block** — a `sys.meta_path` finder that raises `ImportError` on any
  `tkinter` import. This is the opposite of `tests/conftest.py`, which *mocks*
  tkinter so that anything imports; a module that survives the block genuinely
  does not need a display.

## The question this wave exists to answer

Wave 13d's repaired EC-4 removes **zero** records from the reference corpus. That is
correct — its two operands are conference venues and this corpus has none — but a
reviewer has no way to discover it. The linter cannot help: the rule is well-formed
and faithful to its prose, so every check in `plugins/03_harmoniser/linter.py` is
correctly silent. Wave 13d also moved the chain from 776 → 125 → 651 → 566 → 85 to
776 → 16 → 760 → 613 → 147 — a 73% increase in what a human must read — and that was
discovered after the fact, by measurement, not by anything the tool said.

The linter answers *"does this rule mean what you wrote?"*. Nothing answers *"what
will this rule actually do to my corpus?"*. Those are different questions and neither
subsumes the other. EC-4 is precisely the case where the linter is right to say
nothing and a preview would speak.

## a. The candidate headless entry points, EXECUTED

`07_criteria_parsing.md` §8.1 names `tests/_engine_probe.py` and `standalone.py` as
candidates and nobody had established whether either is usable. Each was executed
rather than read.

| Candidate | Executed | Needs | Writes | Usable as a preview entry point |
|---|---|---|---|---|
| `tests/_engine_probe.py::run_flag_only` | **yes**, EL and IL | `tests/` on `sys.path`; a plugin module | **nothing** (audit hook) | **No** — see below |
| `plugins/06_el/standalone.py` | no — cannot | a display | bundle + CSV | **No** — `import tkinter` at module top, no `argparse`, no `__main__` |
| `plugins/07_il/standalone.py` | no — cannot | a display | bundle + CSV | **No** — identical shape |
| `tools/measure_prompt_size.py` | **yes** (`--help`) | nothing | nothing | **No** — builds prompts, never evaluates a criterion |
| `tools/capture_el_il_goldens.py` | **yes** (`--help`) | an API key | goldens, 2 sites | **No** — makes real vendor calls and rewrites goldens |

Both `standalone.py` files are GUI applications, not headless harnesses. The §8.1
note should be corrected: they were never entry points in the sense intended.

The probe *runs*, and cleanly — EL and IL each returned 4 and 5 rows with their
`el_*`/`il_*` columns populated, under zero file writes and zero network events. But
it is not a preview engine: `_client` is a hardcoded fake returning a fixed decision,
and `llm_exclusion_allowed` is forced to `False`. It answers "does the engine run",
not "what would my criteria do".

**Its real value is what it proved incidentally, and this is the finding of section
(a):** `run_el_screen` and `run_il_screen` accept a `ParseReport` and a
`CriteriaLoadReport` **built by hand**, with `use_cache=False, cache_in={}`. No
bundle, no zip, no manifest, no disk. The probe demonstrates the entry point rather
than being one.

## b. The deterministic path, and the measurement the size decision rests on

**The symbol is `plugins/_common/runner.py::run_screen`.**

```python
def run_screen(parse, criteria_report, cancel_event, progress_cb=None, *, stage
    ) -> Tuple[full_rows, survivors, counts, crit_impacts, row_eval_lists, cancelled]
```

The whole preview pipeline was EXECUTED end to end — prose file to per-record
verdicts — against the 776-record reference corpus
`samples/20260122_1654_aggregate.csv`:

```
harmonised 8 criteria in 1.9 ms; corpus 776 rows parsed in 117.4 ms

   IL    IC-1  llm       keywords                ['The paper considers immersive virtual reality OR …']
   IH    IC-3  equals    lang                    ['English']
   IH    IC-4  gte       year                    ['2018']
   IL    IC-5  contains  title,abstract,keywords ['training', 'vocational', 'workplace']
   EH    EC-1  in_list   lang                    ['French', 'Spanish']
   EL    EC-2  llm       keywords                ['…spatial navigation in a virtual maze…']
   EL    EC-3  llm       keywords                ['…the rubber hand illusion paradigm.']
   EH    EC-4  contains  venue                   ['ICRA', 'IROS']

EH: 776 in -> 760 survive   [15.2, 15.8, 15.2 ms]
     EC-1   {'failed': 16,  'missing': 0,   'met': 760, 'unknown': 0}
     EC-4   {'failed': 0,   'missing': 126, 'met': 650, 'unknown': 0}
IH: 760 in -> 147 survive   [10.5, 10.9, 10.8 ms]
     IC-3   {'failed': 8,   'missing': 0,   'met': 752, 'unknown': 0}
     IC-4   {'failed': 611, 'missing': 1,   'met': 148, 'unknown': 0}

FILE WRITES across the WHOLE round trip: NONE
```

**The measured wall-clock is ~26 ms for both deterministic stages** (EH 15.2 + IH
10.5, best of three each). The brief set ~200 ms as the threshold at which the size
decision would stand. It stands with an order of magnitude to spare, and it would
still stand if the corpus were ten times larger. **Nothing here would freeze the UI.**

Two honest adjustments to the brief's framing. The brief said "8 criteria × 776
records"; in fact only **four** of the eight are deterministic — the other four are
seeded to EL/IL and are filtered out by stage before `run_screen` ever sees them. And
the 26 ms excludes the one-off corpus parse of **117 ms**, which the Harmoniser must
pay because `_UiState` deliberately holds no corpus rows (CL-3): it retains
`a_path` and `a_columns` only. 117 ms on a button press is fine. It is not fine on
every keystroke, which is one of the costs in section (e).

Three further properties were measured, because a preview that corrupts the run it
previews is worse than no preview:

- **`runner.py` performs no file IO at all** — the grep for
  `open(|\.write|Path(|os\.|shutil|json\.dump|csv\.writer|mkdir` returns nothing.
- **`run_screen` does not mutate its input** — `parse.rows` unchanged after the call;
  `full_rows[0] is parse.rows[0]` is `False`, so the returned rows are copies.
- **The whole round trip writes nothing** — audit hook, transcribed above.

### The trap this path avoids for free

`_eval_criterion` evaluated directly against IC-5 gives MET=22, FAILED=754 — but
**the IL stage never runs IC-5** (F-65). A preview built on the evaluator would show
a criterion doing something it will never do, on 776 records, confidently.

Routing through `_load_criteria_from_text(text, stage)` and then `run_screen` avoids
this without special-casing, because the loader filters by stage: IC-5 is at IL and
simply never appears in the EH or IH criteria set. **The preview must be built on the
stage-aware path, not on evaluator capability.** This is not a preference; it is the
difference between a correct preview and a confidently wrong one.

### The subtlety that would otherwise have shipped as a defect

Criteria within a stage are **not** applied sequentially. Every criterion in a stage
is evaluated against that stage's full input — EC-1 and EC-4 both see all 776 records
(760+16 = 776 and 650+126 = 776), IC-3 and IC-4 both see all 760.

So per-criterion removals **overlap**, and this was measured rather than assumed:

```
IH: in=760 out=147  stage removed=613
     IC-4   fails 611
     IC-3   fails 8
     sum of per-criterion failures = 619  -> OVERLAP = 6 removed by more than one
     IC-4 AND IC-3 both fail on: ['A376','A382','A385','A646','A770','A776']
```

**A per-criterion running total would be arithmetic nonsense.** The funnel is
per *stage*; per *criterion* the honest statement is "removes N of the M that reached
this stage", with the stage total shown separately and never as a sum. Section (d)'s
mock-up obeys this.

## c. The LLM path, and whether a preview would poison the cache

The brief's central fear was the F-104 family: a 5-record preview writing to
`{EL,IL}_cache.jsonl`, so that a subsequent real run replays preview verdicts.

**The cache write is separable from the call.** This is established three independent
ways, in increasing order of strength:

1. **The engines never write.** An AST walk of `run_el_screen` and `run_il_screen`
   for calls to `open`, `_write_csv`, `mkdir`, `dump`, `write`, `write_text`,
   `write_bytes`, `rename`, `remove` returns **`NONE`** for both. Not "only when a
   flag is set" — the bodies contain no writer call of any kind.
2. **Executed under the audit hook**, EL and IL on 5 records each:
   `FILE WRITES: NONE`, `NETWORK: NONE`. Neither mutated the caller's rows
   (`rows != snapshot` is `False`; `full[0] is parse.rows[0]` is `False`).
3. **The write happens somewhere a preview never goes.** `cache_out` is the sixth
   element of the return tuple — a value the caller may discard. The file is written
   by `plugins/06_el/ui.py::_build_next_bundle_zip`, whose own docstring says it
   *"writes cache/EL_cache.jsonl when enabled"*. That is the bundle export path.

**One thing I could not demonstrate, stated rather than papered over:** I never
produced a *populated* `cache_out`. Both runs returned `{}` — with `flag_only` the
fake's EXCLUDE is rejected (`decisions_rejected: 5`), and with exclusion permitted it
was still gated, most likely by F-87's non-answer check. So the claim does not rest
on observing a discarded cache; it rests on (1) and (3), which are stronger: the
engine has no mechanism to write a file, so there is nothing to discard.

**The cache fear is discharged. The LLM half is still not ready, for four other
reasons, each measured.**

**c-i. The engines are reachable only through `screen.py`.**
`plugins/06_el/plugin.py` and `plugins/07_il/plugin.py` both `import tkinter`.
`plugins/06_el/screen.py` and `plugins/07_il/screen.py` do not, and both **loaded
successfully under the Tk block** with `run_el_screen`/`run_il_screen` present. The
preview must import the engine modules directly. Reaching them through `plugin.py`
would make the preview require a display and would put it out of reach of the test
suite for the same reason Views are.

**c-ii. There is a second `Criterion` dataclass and it has different field names.**

| | `plugins/_common/parser.py::Criterion` | `plugins/07_il/screen.py::Criterion` |
|---|---|---|
| identity field | `cid` | `id` |
| `scope` | present | **absent** |

Feeding `_common`'s objects to the IL engine raises
`AttributeError: 'Criterion' object has no attribute 'id'` — EXECUTED, that is how
this was found. The LLM half must load criteria through the stage-local
`plugins/07_il/screen.py::_parse_criteria_harmonized_csv(csv_text, stage_filter)`,
which takes CSV text — the same text the deterministic half already produces. This is
the F-109 enumeration-rot hazard reappearing inside the preview's own construction,
and it is a live trap for whoever builds it.

**c-iii. F-65 makes an LLM preview actively misleading unless it is special-cased
before any call is made.** EXECUTED, IL on 5 real corpus records:

```
IL loads: [('IC-1','llm'), ('IC-5','contains')]   warnings: []
IL on 5 real records -> crit_impacts:
   IC-1 {'failed':0,'missing':0,'met':0,'uncertain':5}
   IC-5 {'failed':0,'missing':0,'met':0,'uncertain':5}
   calls_made: 1
```

Two criteria, **one call**. IC-5 is `contains` at an LLM stage, so it was never
evaluated — yet it reports `uncertain: 5`, indistinguishable in the output from
"the model could not decide". This independently reproduces F-65's row, which says
*"every other operator is marked `UNCERTAIN` without being evaluated"*. A preview
that printed those impacts verbatim would tell the user their criterion was tried and
was inconclusive, when it was never tried at all. The preview must consult the
linter's existing `inert-at-stage` verdict and say *"IC-5 will not run"* — **before**
spending a call.

**c-iv. The sample must be drawn from the right population.** A real EL/IL run reads
`data/current.csv` from the bundle: the EH/IH **survivors**, 147 of 776 on this
corpus. Sampling 5 records from the raw 776 would preview records that, four times
out of five, never reach the LLM stage at all. The sample must come from the
survivors the deterministic half just computed — which is another reason the two
halves belong in one function and not two features.

And, unavoidably: every press spends vendor tokens and real latency. Wave 13's Ollama
diagnostic measured 8 criteria failing in 15 s against 2 succeeding in 5 s. The LLM
half can never be implicit; it must be a distinct, labelled, opt-in action.

## d. What the user sees

Two shapes are proposed. The deterministic table is the deliverable; the LLM block is
shown for completeness and does not ship in this wave.

```
Criteria preview — samples/20260122_1654_aggregate.csv, 776 records
─────────────────────────────────────────────────────────────────────────────
  EH — deterministic, every record          776 in → 760 out   (16 removed)

     EC-1  in_list lang [French, Spanish]              removes    16 of 776
     EC-4  contains venue [ICRA, IROS]                 removes     0 of 776  ⚠

  IH — deterministic, every record          760 in → 147 out  (613 removed)

     IC-3  equals lang [English]                       removes     8 of 760
     IC-4  gte year [2018]                             removes   611 of 760  ⚠

     6 records are removed by both IC-3 and IC-4; the per-criterion counts
     above overlap and do not add up to 613.
─────────────────────────────────────────────────────────────────────────────
  147 of 776 records reach the LLM stages (19%).

  ⚠ EC-4 removed no records.
    If you expected it to remove some, check the venue column: 126 of 776
    records have no venue at all, and a record with no venue is kept.
    A criterion that removes nothing may still be exactly right.

  ⚠ IC-4 removed 611 of the 760 records that reached it — 80%.
    That is most of your corpus removed by one rule. Confirm the year
    cut-off is what you meant.

  ○ IC-5 (contains, title/abstract/keywords) will not run.
    The IL stage evaluates only LLM criteria, so this rule is never
    applied. See the Validate report.

     [ Show the 16 records EC-1 removes ]  [ Show all removals ]  [ Close ]
```

The two cases the brief asked about by name:

- **Removes nothing** — flagged, and given the most likely benign explanation drawn
  from the data (`missing: 126`) rather than an accusation. The wording says
  explicitly that this may be correct. This is the EC-4 case that motivated the wave.
- **Removes almost everything** — flagged at ≥ 75% of the records reaching that
  criterion. **This is not hypothetical: IC-4 removes 80% of the live corpus today,
  and nothing in the tool says so.** The preview would surface it on first use.

Both are advisory. Wave 13c B's constraint — **warn, never block** — carries over
unchanged: the preview has no veto and no OK/not-OK verdict.

"Which ones" is free: `run_screen` returns `row_eval_lists` aligned with `full_rows`,
so the removed record ids are already in hand (this is how the 6 overlapping ids above
were named). The drill-down lists them; it does not need a second pass.

The inert row is reported from the linter's existing `inert-at-stage` finding rather
than from a count, per c-iii.

## e. Where it attaches — options and their costs

Not a pick. The costs are what the human is choosing between; my recommendation is at
the end of the section and is separable from the options.

**Option 1 — a "Preview" button beside Validate** in `plugins/03_harmoniser/ui.py`,
next to `self.btn_validate`.
- *Cost:* the corpus must be re-read on each press — 117 ms measured — because
  `_UiState` holds `a_path` but no rows (CL-3). Acceptable on an explicit press;
  the alternative is caching rows in the View, which reopens CL-3.
- *Cost:* a second modal in a UI that already shows a Validate dialog.
- *Benefit:* it is exactly the moment the user has criteria and a corpus and has not
  yet exported, and it mirrors `_validate` — pure function, thin widget wrapper.

**Option 2 — fold it into the existing Validate dialog.**
- *Cost:* `_validate(show_ok=False)` is called on **every** `_load_a_csv` and on every
  harmonise, so the corpus would be screened on each — 117 + 26 ms every time.
- *Cost:* it changes what the dialog means. Validate today answers *well-formedness*;
  effect is a different question, and merging them makes neither answer clear.
- *Cost:* the Validate path is explicitly outside this wave's fence.
- **Not recommended on any of the three counts.**

**Option 3 — a separate preview window** opened from the Harmoniser, deterministic
table filled on open, with a distinct `[ Run LLM sample — 5 records, makes real API
calls ]` button.
- *Cost:* the most new UI code, and a new window to maintain.
- *Benefit:* the only shape in which the LLM half can be opt-in per press, which
  c-iv establishes it must be.

*Recommendation, separable from the above:* Option 1 now for the deterministic half,
shaped so it grows into Option 3's window when the LLM half lands. Option 1's dialog
and Option 3's window consume the same report object, so the choice can be deferred
without rework.

### The extracted pure function

```python
def build_criteria_preview(
    rows: List[Dict[str, Any]],           # the Harmoniser's in-memory criteria rows
    corpus_header: List[str],
    corpus_rows: List[Dict[str, str]],    # the WHOLE corpus; the caller does the IO
    *,
    high_removal_fraction: float = 0.75,
    lint: Optional["LintReport"] = None,  # for the inert-at-stage verdicts (c-iii)
    llm_sample: Optional["LlmSampleResult"] = None,   # None = deterministic only
) -> PreviewReport
```

`PreviewReport` carries `corpus_n`, `stages: List[StagePreview]` in pipeline order,
`steps: List[CriterionPreview]`, `survivors_n`, `notes: List[PreviewNote]` (the
zero-removal, high-removal and inert callouts), plus `dialog` and `log_line` **in the
same shape `build_validation_report` already returns**, so the existing
`_SHOW[report.dialog.kind]` dispatch works unchanged.

`CriterionPreview` carries `stage, criterion_id, operator, target, what, stage_in_n,
removed_n, missing_n, unknown_n, removed_ids, will_not_run, reason`. Note
`stage_in_n` and not a running total — that is the overlap finding in (b) encoded in
the type, so the display cannot get it wrong.

It is testable because the caller performs every side effect: reading the corpus,
and making any LLM call. The function is a pure fold over `run_screen`'s outputs.
Every module it needs — `_common/parser.py`, `evaluator.py`, `runner.py`,
`03_harmoniser/parser.py`, `inference.py`, `exporters.py`, and both `screen.py` —
**imports successfully under the Tk block**, so its tests need no View, no
`conftest` mock, and none of wave 13c B's AST-lifting.

### The one refactor this design requires, flagged as a fence question

`plugins/03_harmoniser/exporters.py::_export_csv(rows, path)` writes an 11-column CSV
directly to a path and has **no text-producing variant**. The preview needs that text
in memory.

The preview must screen *the same bytes the bundle will carry*, or it is previewing
something other than what will run. Restating the 11-column schema inside the preview
is exactly the F-109 rot this repository has spent three waves fighting — the
measurement script for this report had to restate it, and that restatement is a
defect I am not proposing to ship.

The proposal is to extract `_criteria_csv_text(rows) -> str` and reduce `_export_csv`
to writing its result. **But `criteria/criteria_harmonized.csv` is byte-identity-
critical and SHA-pinned in the bundle manifest** (`03_harmoniser/bundle.py`), so this
must land as its own commit with a byte-identity assertion against the existing
golden, and it is arguably outside this wave's fence: the fence names the Validate
path, not the export path, but nothing about "byte-identity-critical" invites a
casual edit. **This is a decision for the human, not a side effect for me to take.**

## f. What the preview cannot do

1. **It cannot tell you a criterion is wrong.** It reports what a rule does; whether
   that is what you wanted is yours. EC-4 removing zero is *correct* after wave 13d.
2. **It cannot project LLM behaviour from 5 records to 776.** The sample is labelled a
   sample and is never rendered as a percentage or extrapolated.
3. **It cannot predict a real run's LLM verdicts even for those 5 records.** The
   preview runs `use_cache=False`; a real run with the cache enabled may replay an
   earlier verdict instead of calling.
4. **It cannot see records the corpus parser skipped** — though on this corpus
   `skipped = 0`, measured.
5. **It cannot guarantee preview and run agree unless it shares the serialiser.**
   Without the `_criteria_csv_text` extraction the two can drift silently, which is
   the whole argument for the refactor above.
6. **It cannot account for the exclusion policy differing between preview and run.**
   The engine's own provenance distinguishes `flag_only` from `exclusion_permitted`
   and the outcomes differ; the preview must render whichever the run will use, and
   say which.
7. **It cannot replace the linter, and the linter cannot replace it.** The linter asks
   *"does this rule mean what you wrote?"*; the preview asks *"what does this rule
   do?"*. EC-4 is silent to the first and loud to the second; a mistranslated rule is
   the reverse.

## g. GO / NO-GO

**Deterministic half — GO.**
Every piece exists and the whole chain was EXECUTED end to end this session: prose →
8 rules (1.9 ms) → criteria CSV text → stage-filtered load → `run_screen` per stage →
per-criterion impacts and per-record verdicts, over the whole 776-record corpus, in
**~26 ms**, with **zero file writes** and no mutation of the caller's data. It
reproduces wave 13d's chain exactly (776 → 760 → 147) and it surfaces both motivating
cases on first use: EC-4 removing nothing, and IC-4 removing 80% of the corpus — the
second of which nobody had named before this session. One prerequisite: the
`_criteria_csv_text` extraction, or an argued decision to restate the schema.

**LLM half — NO-GO for this wave, and not for the reason the brief anticipated.**
The cache fear is discharged: the write is separable, structurally, and the engines
have no mechanism to write a file at all. The blockers are four others, each measured
above — the engines are reachable only via `screen.py` (c-i); a second `Criterion`
dataclass with different field names must be used (c-ii); F-65 makes the output
actively misleading unless inert criteria are caught before any call is made (c-iii);
and the sample must be drawn from the 147 survivors rather than the 776 records
(c-iv) — plus the standing cost in tokens and latency of every press.

Shipping the deterministic half alone is the right outcome, and it is the outcome the
brief already anticipated as fine.

## Candidate findings

Raised, not registered — no register row was modified in this commit.

### PV-1 — `IC-4` removes 80% of the reference corpus and nothing says so

`gte year 2018` fails **611 of the 760** records reaching IH. The published funnel
records the aggregate but no artefact attributes it, and no tool surfaces it before a
run. This is not a defect in the rule — the cut-off may be exactly intended — but it
is the single largest reduction in the pipeline and it is invisible until after the
fact. It is the strongest available argument that the preview is worth building, and
it should be checked against the study's intent independently of this wave.
Cross-ref F-168, F-98.

### PV-2 — `07_criteria_parsing.md` §8.1 names two headless entry points that are GUI applications

`plugins/06_el/standalone.py` and `plugins/07_il/standalone.py` both `import tkinter`
at module top with no `argparse` and no `__main__` guard. §8.1 lists them as
candidate headless entry points. Whoever reads that section next will lose the time
this session lost. A one-line correction to §8.1, naming
`plugins/06_el/screen.py::run_el_screen` as the actual headless surface, would
discharge it. Cross-ref F-161.

### PV-3 — two `Criterion` dataclasses with different identity field names

`plugins/_common/parser.py::Criterion` uses `cid` and carries `scope`;
`plugins/06_el/screen.py::Criterion` and `plugins/07_il/screen.py::Criterion` use `id`
and do not. Passing one where the other is expected fails at attribute access, at
runtime, on a field that every criterion has. This is the F-109 enumeration-rot
pattern in dataclass form, and it is a trap for any future code that spans the
deterministic and LLM halves — which the preview, by design, does. Cross-ref F-109.

### PV-4 — `_export_csv` has no text variant, so the preview cannot screen the bytes the bundle will carry

`plugins/03_harmoniser/exporters.py::_export_csv(rows, path)` couples serialisation to
writing. Any consumer needing the text must restate the byte-identity-critical
11-column schema. See section (e) for the proposed extraction and why it is a fence
question rather than a side effect.

## What was not done in this commit

No feature code. No test. No register row. No golden, sample or user-facing document.
No network call of any kind. `docs/data/` and `tests/golden/**` were not touched, and
`inference.py`, `linter.py`, the Validate path, `llm_refine.py` and every screening
plugin's behaviour are as `a790f9d` left them.

Per the brief, this session **stops here**. Building begins in session B, if the human
accepts the GO.

---

# Wave 13e session B — building the deterministic preview

**Branch:** `fix/wave-13e-b-preview` off `main` @ `3e2d635`, working tree clean,
`origin/main` in sync (0 ahead, 0 behind). **Date:** 2026-08-12.
**Gate:** 1765 passed, 7 skipped — read from the run. Golden baseline taken with
`git ls-files -s tests/golden` and kept for re-verification at wrap-up; the
undocumented aggregate hash was retired rather than reused — see B-3.

## B-1. IC-4's 611 removals are real — the hypothesis is refuted, twice

The brief raised a reasonable suspicion: `IC-4` is `gte year 2018` and removes 611 of
the 760 records reaching IH, and CL-1 already records that `UNKNOWN` conflates
"unsupported operator" with "uncomparable value". If a meaningful share of those 611
had a missing or unparseable year, the preview would be displaying correct arithmetic
about a wrong evaluation.

**It is not happening, and it cannot happen.** Both halves EXECUTED.

**Empirically**, across the 760 records reaching IH:

```
=== year-value classes across the 760 records reaching IH ===
  PARSEABLE     759   verdicts: {'failed': 611, 'met': 148}
  EMPTY           1   verdicts: {'missing': 1}

  any failed record with an EMPTY year?       0
  any failed record with UNPARSEABLE year?    0
  max failing year: 2017  (must be < 2018)
```

Every one of the 611 has a parseable year and every one is genuinely below 2018 — the
maximum is 2017. The distribution is an ordinary literature tail: 5 records in 1962,
rising through 38 in 2014, 48 in 2015, 48 in 2016, 34 in 2017. The single record with
an empty year is `MISSING`, and `MISSING` keeps the record. **The corpus really is
80% pre-2018.**

**Structurally**, the feared mechanism cannot occur for `gte` at all. Injecting the
shapes this corpus happens not to contain:

```
  year='2020'     a clear pass       -> MET      note='gte:2018.0'      KEPT
  year='2017'     a clear fail       -> FAILED   note='gte:2018.0'      REMOVED
  year=''         empty              -> MISSING  note='empty_value'     KEPT
  year='n.d.'     unparseable text   -> UNKNOWN  note='gte_non_numeric' KEPT
  year='2018-03'  a year-month       -> UNKNOWN  note='gte_non_numeric' KEPT
  year='in press' prose              -> UNKNOWN  note='gte_non_numeric' KEPT
  year='  2019  ' padded             -> MET      note='gte:2018.0'      KEPT
  year='2018.0'   a float            -> MET      note='gte:2018.0'      KEPT
```

`_eval_criterion`'s `gte` branch returns `UNKNOWN` when `_as_float` yields `None`, and
`run_screen` **keeps** `UNKNOWN` and `MISSING` records. An uncomparable year therefore
fails safe: it can never remove a record. **No candidate finding is warranted, and
`IC-4` should be displayed exactly as it measures.**

One thing the injection did surface, which is a reason to build the preview rather
than a defect in the engine: `year='2018-03'` — an entirely ordinary bibliographic
form — is `UNKNOWN`, so the year filter silently **does not apply** to such a record
and it passes unfiltered. On this corpus that count is zero. On a corpus that used
year-month strings it would be 100%, and the criterion would appear to work while
filtering nothing. **The preview must therefore show `unknown` and `missing`
alongside `removed`, not just the removal count** — those two columns are what would
reveal a whole-corpus format mismatch. This is now a design requirement.

## B-2. The display the preview wants already exists, and is switched off before a run

Found while establishing where B-1's numbers would be shown. `04_eh/ui.py` and
`05_ih/ui.py` both contain:

```python
def _refresh_criteria_table(self, pre_run: bool):
    cols = ["id", "type", "targets", "operator", "what", "status", "notes"]
    if not pre_run:
        cols += ["n_failed", "n_missing", "n_met", "n_unknown"]
```

The per-criterion counts the preview exists to show are **already implemented, already
populated from `crit_impacts`, and already rendered** — but only once `self.full_rows`
is non-empty, i.e. only after a run. Before a run the same table shows `status` and
`notes`, which answer the *linter's* question (is this rule well-formed?) and not the
preview's (what will it do?).

So the honest framing of this feature is not "build a display". It is: **the pre-run
state of an existing table is empty by construction, and the data needed to fill it
costs 26 ms.** That materially affects the attachment decision in session A's
section (e), and it is raised as HO-13E-1 rather than decided here.

## B-3. Retiring the golden aggregate

`9b7fe3e2` has appeared in every step-0 gate since wave 13c and is now in committed
diagnostic appendices. Nobody established how it was derived. This is the
coordinator's own recorded failure mode — a supplied figure treated as fact, and a
hand-maintained number that rots (F-109's pattern, applied to a gate rather than a
vocabulary).

**Provenance, EXECUTED.** `git log -S"9b7fe3e2" --reverse` gives four commits:
`770c8f3` (wave 13c A, where it first appears), `65561b2`, `d5b6d6f`, `3e2d635`.
There is **no wave 13a report in the tree containing it** — the belief that it came
from one is itself unverified. It was introduced by a design document and copied
forward three times.

**Derivation attempt, EXECUTED — 71 methods, none reproduces it.** Concatenated file
contents; concatenated per-file digests; `name + digest` and `digest + name` listings
across three separators; incremental hashing of names with raw digests; basenames and
posix paths; `git ls-files`, `ls-files -s`, `ls-files --stage`, `ls-tree -r`,
`ls-tree`, `--name-only`, `git hash-object`, `git rev-parse HEAD:tests/golden`, each
raw, stripped and CRLF-converted; `sha256sum`/`md5sum` listing styles in three
formats; byte sizes; total size; and every individual golden's own digest — each over
sha256, sha1, md5, sha512, blake2b and crc32.

```
methods tried: 71
MATCHES: NONE — '9b7fe3e2' is not reproducible by any of these
```

**And the goldens have not moved since it was written**, so this is not a case of a
once-correct figure going stale: `git diff --stat 770c8f3 HEAD -- tests/golden/` is
empty, and the `tests/golden` tree object is `050b3575…` at `770c8f3`, `65561b2`,
`d5b6d6f`, `3e2d635` and `main` — **one distinct value across all five**. A derivable
figure would still derive. This one never did.

**What replaces it.** Two checks, both single commands, both reproducible by anyone:

| | command | what it answers |
|---|---|---|
| identity | `git rev-parse HEAD:tests/golden` → `050b3575…` | *which bytes are the goldens* |
| movement | `git diff main...HEAD -- tests/golden/` | *did this branch move them* |

The tree object is git's own content hash of the directory. It is strictly better than
what it replaces: one stable token, derivable in one command, and it changes if and
only if a golden changes.

**Swept, not spot-fixed.** All four instances were replaced with a retraction naming
the real value: `FIX_WAVE_13C_LINTER.md`, `FIX_WAVE_13D_INFERENCE.md`,
`diagnostic/08_harmoniser_llm_failure.md`, and this document's own session A header.
`git grep 9b7fe3e2` returns only the retraction notices themselves.

