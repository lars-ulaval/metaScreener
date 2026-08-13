<!-- SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo -->
<!-- SPDX-License-Identifier: MIT -->

# Wave 13d — repairing the criteria translator: read, measured, then reported

**Branch:** `fix/wave-13d-inference` off `main` @ `65561b2`, working tree clean,
`origin/main` in sync (0 ahead, 0 behind). **Date:** 2026-08-12.
**Test baseline:** 1714 passed, 7 skipped. **Golden aggregate:** `9b7fe3e2`.
**Mode for this commit:** read and measure. **No code was written.** No source, test,
golden, sample, register row or user-facing document was modified; this file is the
only one added. **Network:** none. No Ollama, no vendor API — this wave is entirely
deterministic.

## Evidence conventions

As `07_criteria_parsing.md`. `path::symbol` citations, **no line numbers**.
**[measured]** = executed this session; **[read]** = from source without executing;
**[not established]** = followed by what would settle it. Harnesses are in
`%TEMP%\w13d\`; the shadow variants of `inference.py` used for the blast-radius
measurement were written **there**, never into the repository tree.

---

## a. The branch order, and which one EC-4 hits

**[measured]** by enumerating every `# n)` comment and every `operator =` / `stage =`
assignment inside `inference.py::_infer_criterion_details`. **There are exactly six
branches** — wave 13b corrected F-65's row, which named branches 7–9 that have never
existed, and this confirms that correction independently.

| # | branch | guard, in one line | emits | stage |
| --- | --- | --- | --- | --- |
| — | seed | always | `llm` | `IL`/`EL` |
| 1 | Language | four regexes over the label; a bare language name is one of them | `equals` | `IH`/`EH` |
| 2 | Year | a year column exists **and** a year-ish shape matches | `between`/`gte`/`lte` | `IH`/`EH` |
| 3 | Document type | a doc-type column exists **and** the label contains any of `type`, `document`, `publication type`, `study type`, `article type`, **`conference`** | `equals`/`contains` | `IH`/`EH` |
| 4 | Venue/Journal | the label contains any of `venue`, `journal`, **`conference`**, `published in` | `contains` | `IH`/`EH` |
| 5 | DOI | a `doi` column exists and the label mentions one | `equals`/`not_in` | `IH`/`EH` |
| 6 | Text search | the label mentions title/abstract/keywords/mention/contains/… | `contains` | **`IL`/`EL`** |

First match wins and each branch `return`s.

**EC-4 hits branch 3 and should have hit branch 4.** Its label is *"The publication
venue contains "ICRA" OR "IROS" (robotics conference proceedings)."* Branch 3's guard
fires on the word **`conference`** — which appears **only inside the parenthetical
gloss** — and then `doc_type_map`'s own `"conference"` key matches, again from the
gloss, so the branch returns `equals` / `doc_type` / `["conference"]` and branch 4 is
never reached. Both the target column **and** the operand come from an aside describing
the venues, not from the criterion's subject.

**Note the collision that makes this delicate: `conference` is in branch 3's trigger
list AND in branch 4's.** Any repair has to decide which owns a label containing it.

## b. The minimal change for F-166 — options, and what each moves

**Option 1 — reorder: put branch 4 before branch 3.** **Rejected, and the measurement
says why.** `conference` is in both guards, so *"Exclude conference proceedings."* — a
criterion with no venue in it at all — would become `contains venue conference`. That
trades one wrong column for another and breaks a case that works today.

**Option 2 — tighten branch 3 so a parenthetical cannot decide.** Taken, in a specific
form arrived at by measurement rather than by design:

- the **guard** stays on the full label (permissive: a gloss may still let a branch
  *in*);
- the **value decision** — `doc_type_map`'s scan and the `conference`/`proceedings`
  fallback — runs on the **main clause only**, the label with `(...)` spans removed;
- **branch 4's guard** also runs on the main clause, so a gloss cannot pull a criterion
  *into* venue either.

**The first draft of this was wrong and the measurement caught it.** Stripping
parentheticals from branch 3's *guard* as well regressed *"Systematic reviews and
meta-analyses (any type)."*: its only trigger word (`type`) is in the gloss, so the
guard stopped firing and the criterion fell all the way to `llm` — even though its map
key, `systematic review`, is in the main clause and matched correctly before. Guard
permissive, value strict, is what satisfies both.

**Option 3 — score both branches and pick the stronger.** Rejected as unfalsifiable at
this size: with one reference file there is nothing to tune a score against.

**What else option 2 moves — [measured], not reasoned.** §d.

**Half the repair is not the column at all.** **[measured]** with branch 4 merely
*reached*, EC-4 becomes `contains venue` with `what = ["The publication venue contains
"ICRA" OR "IROS" (robotics conference proceedings)."]` — **the whole label as a single
operand**, because branch 4's own extractor is `re.search(r"(published in|in)\s+(.+)$",
…)` and that pattern does not match this sentence, so it falls back to `[label]`. So
F-166's remedy is two changes, not one: reach branch 4, **and** extract the operands.
The extractor is narrowed to the high-confidence case — **quoted strings are
operands** — because EC-4 quotes both, and anything cleverer is guessing.

## c. The minimal change for F-167, and what `in_list` needs first

**The change**: branch 1 takes `m.group(1)` from the first matching pattern and
returns. It should collect **every** language the label names, in order of appearance,
and emit `in_list` when there is more than one, `equals` when there is exactly one —
so the single-language case is bit-for-bit what it is today.

**What `in_list` needed first: to be executed at all.** The coordinator's brief is
right to flag this and right that he was twice wrong about it. **[measured]** the only
occurrences of `in_list` under `tests/` are a criterion dict in `test_final_report.py`
and two references in `test_criteria_linter.py`; `tests/test_deterministic_filters.py`
exercises `regex` and **not** `in_list`.

**[measured]**, fourteen cases through the real `plugins/_common/evaluator.py`:
**`in_list` works, and the fast and detail entry points agree on all fourteen.**

| case | verdict |
| --- | --- |
| `["French"]` vs `French` / vs `fr` | FAILED / FAILED — `_norm_what_for_target` maps both sides to `fr` |
| `["French","Spanish"]` vs `fr` / `es` / `en` | FAILED / FAILED / MET |
| case and whitespace differences | normalised away |
| empty `what`, or `[""]` | `UNKNOWN`, note `in_list_missing_what` — safe |
| empty value | `MISSING` |

**And one result that decided the design of the other repair: `in_list` is exact
membership, not substring.** `["ICRA","IROS"]` against a venue of `"Proc. ICRA 2021"`
does **not** match. So `in_list` is right for languages, where the corpus holds exact
codes, and **wrong for EC-4**, where the label says *contains*.

**[measured]** the operator that is right for EC-4 is `contains`, and it already ORs
its operands — `matched = any((w.lower() in hay) for w in what_list_norm if w)`. So
**F-166 needs no evaluator change.** By contrast `equals` reads `what_list_norm[0]`
alone, which is why it can never express a compound criterion and why F-167's remedy
has to change the operator rather than just the operand list.

## d. The blast radius, measured

**[measured]** the current `_infer_criterion_details` and three shadow variants were run
over every criteria source in the repository plus a twelve-label probe battery written
to find collateral damage. Tables saved to `%TEMP%\w13d\`.

**Sources**: `samples/ic_ec_12.txt` — **[measured]** the only criteria file in
`samples/`; `ex_ref_2.txt` is a bibliography — and the `label` cells of
`docs/data/study_input/criteria_harmonized_v3.1.0.csv`,
`tests/golden/criteria_harmonized_v3.1.0.csv` and
`docs/data/wave12_local_runs/runBC_criteria_harmonized.csv`. All four carry the same
eight labels, so the eight rows below are the whole real population.

**The eight rows of the reference contract — two move, six do not:**

| id | before | after | verdict |
| --- | --- | --- | --- |
| IC-1 | `IL llm keywords` | unchanged | — |
| IC-3 | `IH equals lang [English]` | unchanged | — |
| IC-4 | `IH gte year [2018]` | unchanged | — |
| IC-5 | `IL contains title,abstract,keywords [3]` | unchanged | still F-65, untouched |
| **EC-1** | `EH equals lang ['French']` | **`EH in_list lang ['French','Spanish']`** | **F-167 repaired** |
| EC-2 | `EL llm keywords` | unchanged | — |
| EC-3 | `EL llm keywords` | unchanged | — |
| **EC-4** | `EH equals doc_type ['conference']` | **`EH contains venue ['ICRA','IROS']`** | **F-166 repaired** |

**The probe battery — one further true positive, no regressions:**

| id | label | before | after |
| --- | --- | --- | --- |
| P-1 | *Exclude conference proceedings.* | `EH equals doc_type [conference]` | unchanged ✔ |
| P-9 | *Systematic reviews and meta-analyses (any type).* | `IH equals doc_type [systematic review]` | unchanged ✔ |
| P-10 | *Exclude editorials (a type of commentary).* | `EL llm keywords` | unchanged ✔ |
| P-8 | *Written in Dutch or German.* | `EH equals lang ['Dutch']` | **`EH in_list lang ['Dutch','German']`** ✔ |
| **P-11** | *The venue contains CHI (a conference).* | `IH equals doc_type ['conference']` | **`IH contains venue`** ✔ |

**P-11 is the point of the whole exercise**: a sentence nobody has ever run, mis-targeted
by exactly F-166's mechanism, now corrected. **The repair catches the class, not the
instance.**

**P-8 shows F-167's fix is not merely EC-4's twin**: `Dutch` is not in the known-language
alternation, so the repair has to union the pattern captures with the name scan, or it
would silently swap which operand survives.

**The corpus effect, [measured] end to end through the real
`plugins/_common/runner.py::run_screen`:**

```
AS SHIPPED           776 -> EH OUT 125 -> 651 -> IH OUT 566 -> 85
    EC-1  equals   lang     ['French']            failed=14   missing=0
    EC-4  equals   doc_type ['conference']        failed=112  missing=0

AFTER THE REPAIR     776 -> EH OUT  16 -> 760 -> IH OUT 613 -> 147
    EC-1  in_list  lang     ['French','Spanish']  failed=16   missing=0
    EC-4  contains venue    ['ICRA','IROS']       failed=0    missing=126
```

**This reproduces `ESCALATION_WAVE_13.md` §Q2d's counterfactual exactly** — 776 → 16 →
760 → 613 → 147 — which is independent confirmation that the repair produces the rules
that document predicted, arrived at by changing the translator rather than by hand-editing
a table.

EC-4 now removes **0** records, against 112 before, and its `missing=126` is the 126
records with an empty `venue`, correctly not excluded. EC-1 now removes **16**, against
14 — the two Spanish records it always named.

## e. What this wave will not fix, and why

1. **F-168 — the published demonstration.** It cannot be closed by this change and must
   not appear to be. `docs/data/study_input/` is frozen under F-98 and pinned by
   `SHA256SUMS`; the artefacts keep the old rules **by design**, and the funnel they
   record is still `776 → 125 → 651 → 566 → 85`. Nothing under `docs/data/` will be
   touched. F-168's row will say so explicitly.
2. **F-65 — `IC-5` is `contains` at `IL`.** Its own row, its own wave, and its cell
   warns its fix moves screening outcomes. `IC-5` is measured unchanged by both repairs.
3. **Branch 4's operand extraction in the unquoted case.** **[measured]** *"The
   publication venue is IEEE VR or ISMAR."* still yields the whole label as one operand.
   The quoted-string extractor does not reach it, and splitting unquoted prose on `or`
   is the guessing this wave is trying to remove. Recorded as a candidate finding rather
   than fixed.
4. **`equals` reading `what_list_norm[0]` alone.** A real defect in the evaluator, and
   F-167's remedy routes around it by emitting `in_list` instead of a multi-value
   `equals`. Out of this wave's fence and recorded.
5. **The goldens.** `tests/golden/criteria_harmonized_v3.1.0.csv` records the *old*
   EC-1 and EC-4 rules. §f.

## f. The golden — the one thing that has to be decided, not discovered

**[measured]** `tests/test_harmoniser_regression.py` asserts the harmonise path is
**byte-identical** to `tests/golden/criteria_harmonized_v3.1.0.csv`, and that golden
contains `EC-1 equals lang French` and `EC-4 equals doc_type conference` — the two
defects. **A correct repair therefore breaks that test by construction.**

The brief says a golden change is "an argued decision, not a side effect", and says to
stop and report if a repair would change one. **So, reported here, before any code:**

- The golden is the **output of the defective translator**. It is not evidence of
  anything except what the translator used to do, and `07_criteria_parsing.md` §6 already
  records that it "pins the current output — including all three defects — rather than
  validating it".
- It is **not** one of the F-98-frozen study artefacts. Those live under
  `docs/data/study_input/` with their own `SHA256SUMS`, and they are untouchable. The
  `tests/golden/` copy is a regression fixture.
- **The proposal is therefore not to move the golden**, but to make the regression test
  assert the *repaired* rules explicitly and keep the golden file as the record of what
  the pre-repair translator emitted — renaming nothing and moving no bytes.

**[not established]** whether the maintainer would rather re-capture the golden. That is
his call, and the fence says a golden must not move without it; the next commit will
take the no-move option and say so, and it is one line to reverse.

---

## Corrections to the brief

1. **"F-167's remedy is `in_list`" is right; "F-166's" is not, and the brief does not
   say which operator F-166 needs.** `in_list` is **exact membership** — **[measured]**
   `["ICRA","IROS"]` does not match a venue of `"Proc. ICRA 2021"`. EC-4's label says
   *contains*. The operator it needs is `contains`, which already ORs its operands.
   Using `in_list` for both would have produced a rule that removes nothing **for the
   wrong reason**, and it would have looked correct in the table.

2. **`in_list` is untested, exactly as the brief says — and it works.** Fourteen cases,
   both evaluator entry points, agreeing. The brief was right to demand execution before
   emission; the result is that no `in_list` fix is needed, only tests.

3. **F-166 is not one change but two.** Reaching branch 4 gets the column right and
   leaves the operand as the entire sentence. The brief's own mandatory fixture —
   "expressing both ICRA and IROS" — is not satisfied by the branch fix alone.

4. **The obvious form of the branch fix regresses a working case.** Stripping
   parentheticals from branch 3's *guard* as well as its value scan sends *"Systematic
   reviews and meta-analyses (any type)"* to `llm`. Guard permissive, value strict.

5. **A reorder is not just "not local" — it is wrong.** `conference` sits in both
   guards, so putting venue first breaks *"Exclude conference proceedings."*

---

## Candidate findings

Committed here rather than relayed (F-179). Max register ID is **F-181**.

### WD-1 — branch 4 takes the whole sentence as its operand when nothing is quoted

**Proposed severity: Medium.** **[measured]** *"The publication venue is IEEE VR or
ISMAR."* yields `contains venue ["The publication venue is IEEE VR or ISMAR."]` — a rule
that can only match a venue field containing the entire criterion, i.e. never. The
extractor is `re.search(r"(published in|in)\s+(.+)$", …)` with `[label]` as the fallback,
and the fallback is reached whenever the sentence does not contain a bare `in`.

This wave fixes the **quoted** case only, which is what EC-4 needs and what can be done
without guessing. The unquoted case is left, deliberately, because splitting prose on
`or` is the class of guess that produced F-166.

**Duplication sweep.** **[measured]** over all 178 register rows: `branch 4` 0 hits,
`published in` 0 hits. **F-166** is about the wrong *column*; this is the right column
with a useless *operand*. **F-167** is about a dropped operand in branch 1. Adjacent,
distinct, and it produces a rule that silently matches nothing — the same *direction* as
EC-4-as-labelled, which excluded 0 of 776. Novel.

### WD-2 — `equals` evaluates only its first operand, so a multi-value `equals` is silently a single-value one

**Proposed severity: Medium.** **[read] and [measured]**
`plugins/_common/evaluator.py::_eval_criterion` does `matched = (val.lower() ==
what_list_norm[0].lower())` for `equals`. **[measured]** `equals venue ["ICRA","IROS"]`
against `"IEEE IROS 2020"` returns MET, i.e. does not match, silently ignoring the
second operand.

`inference.py::_validate_row` check 9 makes a multi-value `equals` a **warning only**, so
such a row exports clean, and this is the mechanism that made F-167 invisible downstream
as well as upstream.

**Duplication sweep.** **[measured]** `what_list_norm` 0 hits across the register.
**F-167** is about the inference emitting one operand; this is the evaluator ignoring
extras when it is handed several — the same defect from the other end, reachable from a
hand-edited or externally-produced table, which is F-176's and F-174's recorded arrival
route. Novel. Out of this wave's fence: `plugins/_common/` is not
`inference.py`.

---

## What was not done in this commit

- **No code was written**, per the brief's instruction to read and report first.
- **The shadow variants are in `%TEMP%\w13d\`**, not in the tree, and exist only to make
  §d a measurement rather than a prediction.
- **Nothing under `docs/data/` was read for modification** and nothing was written there.
- **[not established]** whether the maintainer prefers the golden re-captured (§f).
- **[not established]** how the repair behaves on criteria prose this repository does not
  contain. The probe battery is twelve labels I wrote; §7.1 of the diagnostic makes the
  standing point that eight clean sentences are not a sample of real input, and twelve
  more of mine are not either.
