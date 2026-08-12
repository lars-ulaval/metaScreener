<!-- SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo -->
<!-- SPDX-License-Identifier: MIT -->

# Wave 13c session A — the criteria linter: design, measured before it is built

**Branch:** `fix/wave-13c-linter` off `main` @ `7591fc2` (tag `post-wave-13b`), working tree
clean, `origin/main` in sync (0 ahead, 0 behind). **Date:** 2026-08-12.
**Test baseline:** 1602 passed, 7 skipped. **Golden listing aggregate:** `9b7fe3e2`.
**Mode for this commit:** design only. **No code was written.** No source, test, golden,
sample, register row or user-facing document was modified; this file is the only one added.
**Network:** none. No LLM endpoint was contacted, local or remote. No Ollama daemon was
started. No paid vendor API was called.

## Evidence conventions

As `07_criteria_parsing.md`. Claims are anchored on `path::symbol`; **line numbers are
absent entirely**, for the reason that document gives. Markers:

- **[measured]** — produced by executing real repository code in this session. The harnesses
  are `%TEMP%\w13c_produce.py`, `%TEMP%\w13c_proto.py` and `%TEMP%\w13c_probe2.py`; none was
  written into the repository tree.
- **[read]** — derived from repository source without executing the behaviour.
- **[not established]** — the evidence does not settle it, followed by what would.

**The harness is trustworthy, and that is checked rather than asserted.** **[measured]**
driving `plugins/03_harmoniser/parser.py::_parse_free_text_criteria` →
`plugins/03_harmoniser/inference.py::_infer_criterion_details` over `samples/ic_ec_12.txt`
against `samples/20260122_1654_aggregate.csv`, and writing the result through
`plugins/03_harmoniser/exporters.py::_export_csv`, reproduces
`tests/golden/criteria_harmonized_v3.1.0.csv` **byte for byte** — 1,984 bytes, equal. Every
row figure below comes from that path, not from a hand-typed table.

---

## Corrections to the coordinator's brief

Per the standing rule, first, and there are six.

### 1. Claim (a) is confirmed — but the linter's input is *not* the CSV, and the brief's framing would specify the wrong shape

The instruction says the contradiction "is machine-checkable from ONE row with nothing else
loaded", citing `label` and `source_text` sitting beside the substituted rule "in the file
every stage opens". **That is true of the file and it is not the input session B will hand
the linter.**

**[measured]** `plugins/03_harmoniser/ui.py::HarmoniserView._harmonise_no_llm` assembles an
in-memory `dict` per criterion and stores it on `_UiState.rows`. Those dicts carry exactly the
eleven keys `_export_csv` writes — `stage, id, type, scope, label, operator, target, what,
threshold, enabled, source_text` — **but not in the same types**:

| key | in memory (what `_validate_row` and session B see) | in `criteria_harmonized.csv` |
| --- | --- | --- |
| `what` | `list` — e.g. `['training', 'vocational', 'workplace']` | `str`, joined by `_what_to_export` |
| `enabled` | `bool` — `True` | `int` — `1` / `0` |
| `threshold` | `str` — `''` or `'0.60'` | same |

A linter specified against the CSV would receive `what` as a string from its only real caller
and count operands by splitting a list that is not a list. **The signature in §d accepts both
shapes and normalises on entry**, and the normaliser is the first thing that needs a test.

### 2. `_infer_criterion_details` takes five arguments, not the four the decision table implies

**[read]** the real signature is
`_infer_criterion_details(crit_id, crit_type, label, a_columns, default_text_target)`.
`07_criteria_parsing.md` §2.2's decision table describes the guards but not the arity, and
`default_text_target` is not a detail — it is computed by
`parser.py::_get_best_text_targets` and is the value F-175 is about. A fixture generator that
omits it does not reproduce the golden. Stated because the mandatory regression fixtures
depend on getting this exactly right.

### 3. The coordinator's check 2 is unsafe as worded, and I measured the false positive

The brief proposes: *"the label contains a conjunction or disjunction the rule expresses with
a single-value operator."* Implemented literally, **it fires on `IC-5`, which is correct.**

**[measured]**, naive version, over the eight golden rows:

```
target-mismatch fired on: ['EC-4']
dropped-operand fired on: ['IC-5', 'EC-1', 'EC-4']       <- IC-5 is a FALSE POSITIVE
```

`IC-5`'s label is *"The title, abstract, or keywords mention training OR vocational OR
workplace."* It contains **three** `or` tokens, of which **one enumerates targets** and two
enumerate operands. The rule carries three operands and is right.

`07_criteria_parsing.md` §7.5 already predicted exactly this — *"compound by a crude marker
sweep, 6 of 8 (over-inclusive — `IC-4`'s '2018 or later' is not compound, and `IC-5`'s three
values are correctly captured)"* — and the brief's list did not carry that warning forward.
Two refinements make it clean, and both are load-bearing rather than cosmetic (§b, check 2).

### 4. The executable-operator set cannot be derived at run time, because `UNKNOWN` is overloaded

This bears directly on whether the linter should own check 4. **[measured]**
`plugins/_common/evaluator.py` has **no module-level constant** for the executable set — its
only names are `Criterion, _eval_criterion, _eval_criterion_detail, _get_first_nonempty,
_norm_for_target, _norm_what_for_target, _safe_str, _summarize_reason` — so the 8-tuple is
inline and cannot be imported. That is F-109, and a linter that retypes it becomes the
**eighth** representation of this vocabulary.

The obvious escape is to derive it by *behaviour*: call `_eval_criterion` and treat `UNKNOWN`
as "not executable". **[measured] that does not work**, because `UNKNOWN` means two different
things:

```
gte  on lang='en'   what=['2000']  -> UNKNOWN     (operator IS executable; the value is not comparable)
gte  on year='2020' what=['2000']  -> MET
llm  on lang='en'   what=['prose'] -> UNKNOWN     (operator is NOT executable here)
```

A caller cannot tell the two apart from the return value. **With well-typed operands the probe
does resolve exactly the right set** — **[measured]** `between, contains, equals, gte, in_list,
lte, not_in, regex`, matching `07_criteria_parsing.md` §2.5 — but "well-typed" has to be
supplied per operator, which is fine in a test and impossible at run time over a user's table.

**Consequence, and it is the design answer:** the linter restates the set, and a **guard test**
probes `_eval_criterion` with per-operator well-typed fixtures and asserts the linter's table
equals what the evaluator actually executes. That converts an eighth copy into a *checked*
copy, which is what F-109's remedy asks for and the pattern `91566ed` established for
`.gitattributes` (derive rather than restate; where you must restate, assert). Recorded as
**CL-1** below, because the overload is a defect in shipped code and not merely an
inconvenience here.

### 5. Check 6 is half-undecidable, and the decidable half has no reachable instance

The brief asks for *"a threshold is unparseable **or was silently defaulted**"*.

**The second half cannot be seen from the row.** **[read]**
`ui.py::_harmonise_no_llm` writes `f"{DEFAULT_THRESHOLD:.2f}"`, i.e. the literal string
`0.60`, into every EL/IL row. A user who types `0.60` produces the identical bytes. Nothing
in the row, the table or the bundle distinguishes them. Recorded as **CL-2**.

**The first half is decidable and, through the documented workflow, unreachable.**
**[measured]** across all three committed criteria tables — the golden, the frozen study input
and the wave-12 local-run table — every threshold is `''` or `'0.60'` and none is unparseable
or out of range. `inference.py::_validate_row` already rejects a non-float threshold, so a
table exported through the GUI cannot carry one. It bites only on a hand-edited or
externally-produced table reaching `plugins/06_el/screen.py::_parse_criteria_harmonized_csv`,
which is F-176's arrival route. Kept, at the lowest severity, as a guard rather than as a
finding-in-waiting.

### 6. "Two rows are duplicates" needs narrowing to be worth having

**[measured]** zero duplicate ids across all three committed tables. F-174 records that the
defect is latent and reachable only through a hand-authored table. Kept, but the check is
**duplicate `id`**, not "duplicate rows" — two rows with the same id are the defect F-174
measured (`crit_impacts` collapses them, and the second verdict overwrites the first); two
rows that are wholly identical are a subset of that and need no separate rule.

---

## a. The row contract

**[read]** `plugins/03_harmoniser/exporters.py::_export_csv` declares eleven columns, and
`ui.py::_harmonise_no_llm` builds the in-memory dict from the same eleven keys. What a linter
can compare, and against what:

| column | what it holds | usable by the linter as |
| --- | --- | --- |
| `label` | **the researcher's sentence, verbatim** | the *intent* — the only statement of what the user asked for |
| `source_text` | the same sentence with its `IC-n -` prefix | a fallback when `label` is empty |
| `operator` | one of `parser.py::OPERATORS` | half of the *rule* |
| `target` | comma-joined corpus column names | the other half — the column the rule reads |
| `what` | the operands (`list` in memory, joined `str` in the CSV) | the values the rule compares |
| `stage` | `EH` / `IH` / `EL` / `IL` | which executor will (or will not) run it |
| `threshold` | `''` for EH/IH, `'0.60'` for EL/IL | the confidence gate, EL/IL only |
| `id`, `type`, `scope`, `enabled` | bookkeeping | id-uniqueness; `enabled` gates whether a finding matters |

**The claim is confirmed.** **[measured]** in the committed golden, `EC-4`'s row is:

```
label      : The publication venue contains “ICRA” OR “IROS” (robotics conference proceedings).
source_text: EC-4 - The publication venue contains “ICRA” OR “IROS” (robotics conference proceedings).
operator   : equals      target: doc_type      what: ['conference']
```

The word **`venue`** and the value **`doc_type`** are in the same row, four columns apart. The
contradiction is decidable from that row with nothing else loaded except the knowledge that
`venue` is a column name — and that knowledge is itself in the row set's own corpus header,
or in `parser.py::TARGET_ALIASES`. **The design below stands.**

`EC-1` is the same shape one column over:

```
label      : The paper is written in French or Spanish.
operator   : equals      target: lang           what: ['French']
```

---

## b. The check list

Seven checks proposed; **six built**. Check 7 was dropped during construction for a reason the
design did not foresee, recorded in full below rather than quietly deleted. Each row states
what it detects, the measured defect behind it, its false-positive risk, and what it needs.

| # | check | detects | measured defect it catches | needs | FP risk |
| --- | --- | --- | --- | --- | --- |
| 1 | **target-mismatch** | the label names a corpus concept, and the rule targets a different one | **F-166** — `EC-4`, *"venue"* → `doc_type`, 112 of 776 records removed | table + column vocabulary | **low, measured 0/8** |
| 2 | **dropped-operand** | the label offers more alternatives than the rule carries operands | **F-167** — `EC-1`, *"French or Spanish"* → one operand; and **F-166** again | table only | **low after two refinements; naive version 1/8** |
| 3 | **unresolved-target** | the rule targets a column the corpus does not have | none live | table + corpus header | very low |
| 4 | **inert-at-stage** | the operator cannot execute at the assigned stage | **F-65** — `IC-5`, `contains` at `IL`, 0 of 70 matching records acted on | table only | none — it is a set membership |
| 5 | **duplicate-id** | two rows share an `id` | none live (**F-174**, latent) | table only | none |
| 6 | **threshold** | unparseable or out of `[0,1]` | none live (**F-176**'s arrival route) | table only | none |
| 7 | ~~**matches-nothing**~~ | the rule selects zero records, or every record | none live | table + **corpus rows** | **NOT BUILT — see below** |

### Check 1 — target-mismatch (F-166's class)

Take the label's words, map each through a **concept vocabulary**, and compare the resulting
canonical columns against the row's `target`. Fire when the label names at least one concept
and **none** of them is the target.

**The vocabulary is derived, not retyped.** It is
`parser.py::TARGET_ALIASES` (which already maps `language→lang`, `journal→venue`,
`conference→venue`, `document_type→doc_type`, …) extended with an identity mapping for each
corpus column. Retyping it here would be a ninth representation of the same vocabulary; F-109
is explicit about the cost.

**[measured]** over the eight golden rows: fires on **`EC-4` only**.

```
label names ['venue']; rule targets ['doc_type']
```

Zero false positives. Note the alias map earns its place here: `EC-4`'s label contains both
`venue` (identity) and `conference` (`TARGET_ALIASES` → `venue`), and both point away from
`doc_type`.

**False-positive risk, stated rather than dismissed.** The corpus carries 34 columns and some
are ordinary English — `status`, `confidence`, `provenance`, `pages`, `parents`, `url`. A
label reading *"papers whose status is preprint"* would fire against a rule targeting
something else, correctly; a label using one of those words incidentally would fire wrongly.
**[measured]** none of the eight fires wrongly, but eight clean, one-per-line sentences are
not a fair sample of the input this feature exists for (§7.1 of the diagnostic makes exactly
that point). If the corpus-column half proves noisy in session B, the fallback is to restrict
the vocabulary to `TARGET_ALIASES` plus the five columns the inference branches actually
`pick_col` for, and to say so.

### Check 2 — dropped-operand (F-167's class)

Count the coordinating alternatives in the label; compare against `len(what)`. Fire when
operands are fewer.

**Two refinements, both required, both measured:**

1. **Only discrete operators.** Apply to `equals`, `contains`, `not_in`, `in_list` — operators
   where each operand is a separate alternative. **Exclude `gte`, `lte`, `between`**, which
   express an interval, so *"2018 or later"* is already carried by the operator; and **exclude
   `llm`**, where the whole sentence is the single operand by design. Without the `llm`
   exclusion, `IC-1` and `EC-2` both false-positive — **[measured]**, each has two
   alternatives and one operand.
2. **Discount target-enumerating conjunctions.** An `or` whose neighbouring words are both
   concept names is enumerating *fields*, not *values*. This is what rescues `IC-5`.

**[measured]** after both refinements:

```
IC-1   llm       alts=2 ops=1   -        (excluded: llm)
IC-3   equals    alts=1 ops=1   -
IC-4   gte       alts=1 ops=1   -        (excluded: range operator; "or later" also discounted)
IC-5   contains  alts=3 ops=3   -        (the target-enumerating "or" discounted)
EC-1   equals    alts=2 ops=1   FIRE
EC-2   llm       alts=2 ops=1   -        (excluded: llm)
EC-3   llm       alts=1 ops=1   -
EC-4   equals    alts=2 ops=1   FIRE
```

Fires on **`EC-1` and `EC-4`**, which is exactly the target set. Zero false positives.

### Check 4 — inert-at-stage (F-65's class): the linter reports, F-65's remedy gates

The brief asks whether the linter should own this or defer. **It should own the reporting and
must not own the gate**, for three reasons:

1. **F-65's proposed remedy is an `_validate_row` *error*, and an error blocks export.** The
   human's decision for this feature is warn-clearly-never-block. Those are different
   mechanisms with different consequences and both should exist.
2. **The linter can say what F-65's error cannot.** An error string says "invalid"; the linter
   says *"`IC-5` will never be evaluated: `contains` does not execute at `IL`. 70 of 776
   records match its terms and none will be acted on."* That is the whole point of the
   feature.
3. **F-65's fix is a later wave, and the linter must work while the defect is present.** This
   session's mandatory fixtures depend on `IC-5` still being `contains` at `IL`.

**[measured]** the check fires on `IC-5` in the golden **and** in the frozen study input, and
**does not** fire on `docs/data/wave12_local_runs/runBC_criteria_harmonized.csv`, where that
row is `llm`. That difference is real, disclosed, and F-159's subject — a useful proof that
the check discriminates rather than always firing.

### Check 7 — matches-nothing — PROPOSED, THEN NOT BUILT. The correction is below.

`07_criteria_parsing.md` §5 records that Validate never checks *"that `equals lang 'French'`
will ever match"*. A rule that selects **zero** records, or **all** of them, is almost always
a mistranslation or a typo. It is the only check that would have caught `EC-4`
**as the researcher wrote it** — `contains venue [ICRA, IROS]` matches 0 of 776.

**I proposed it as "optional, because it needs the corpus". That was too weak, and building it
disclosed why.** **[measured]** the harmoniser **never holds the corpus rows**.
`plugins/03_harmoniser/ui.py::_UiState` carries `criteria_path`, `criteria_kind`, `a_path`,
`a_columns`, `a_id_col`, `text_stats`, `criteria_text` and `rows` — the last being the
*criteria* rows, not the corpus. And `parser.py::_load_a_header_and_stats` returns
`(cols, stats)` only: it reads the header, then loops records solely to count non-empty text
fields, `break`s at `sample_n = 200`, and retains none of them.

So check 7's input is not *optional* at the only call site — **it is absent**. Supplying it
means session B adding a full read of the A-vector CSV (1.3 MB here, unbounded in general)
into a Validate click that is currently instant. That is new file IO in the wiring session,
which this brief's own fence calls the signal to stop and report.

**Decision: not built in session A.** Three reasons, in order of weight:

1. Its input does not exist at the caller, and creating it is a scope change session B has not
   been given.
2. **[measured]** it has no live instance — every emitted rule on all three committed tables
   matches something, so nothing is going uncaught today.
3. The seam costs nothing to leave open: `lint_criteria(rows, a_columns, corpus_rows=None)`
   already accepts the parameter and reports the check in `report.skipped`, so a later wave
   adds the check and its caller together without an API change.

**What this costs, stated rather than buried:** the class *"the rule is well-formed, correctly
targeted, and matches nothing"* is **not covered by this wave**, and it is the class that would
catch a mistranslation whose label happens not to name a column — the gap §e item 1 already
names. Raised as **CL-3**.

### Dropped from the coordinator's list

Nothing was dropped outright. "Two rows are duplicates" was narrowed to **duplicate `id`**
(correction 6), and "was silently defaulted" was removed from check 6 as undecidable
(correction 5, **CL-2**).

---

## c. Severity shape

Three levels. They are deliberately **not** the register's `Critical/High/Medium/Low`: those
grade work for a maintainer, these grade a sentence shown to a researcher mid-task, and reusing
the words would invite the two to be conflated.

| level | means | the checks that emit it |
| --- | --- | --- |
| **`MISTRANSLATED`** | the rule demonstrably does not implement the label | 1, 2 |
| **`INERT`** | the rule is well-formed and will not act | 4, 7 |
| **`NOTICE`** | worth a look; not necessarily wrong | 3, 5, 6 |

Ordering is `MISTRANSLATED` > `INERT` > `NOTICE`, and findings sort by it so the sentence a
user reads first is the one that changes which papers are screened.

**How it maps to what the user is shown is session B's, and only the ordering is fixed here.**
The one property this session asserts: **every finding carries the criterion id and a sentence
in the user's terms saying what the rule will actually do**, not a rule name. `_validate`'s
current failure — **[measured]** it computes `errs`/`warns` and displays neither, which is
F-173 — is the shape to avoid, and a linter whose findings are also discarded would be F-173
happening twice.

**Nothing here blocks.** No level is fatal, the linter has no concept of failure, and it
returns findings rather than raising. A blocking tool teaches people to click past warnings.

---

## d. Where it lives, and its signature

**Module:** `plugins/03_harmoniser/linter.py`. **Tests:** `tests/test_criteria_linter.py`.

```python
@dataclass(frozen=True)
class Finding:
    criterion_id: str      # "EC-4"
    check: str             # "target-mismatch"
    severity: str          # "MISTRANSLATED" | "INERT" | "NOTICE"
    message: str           # one sentence, user's terms, names what the rule will do
    detail: str            # the machine-checkable specifics

def lint_criteria(
    rows,                  # Sequence[Mapping] — in-memory OR CSV shape; normalised on entry
    a_columns=(),          # Sequence[str] — corpus header; enables checks 1 and 3
    corpus_rows=None,      # Optional[Sequence[Mapping]] — enables check 7
) -> List[Finding]
```

**Pure by construction:** no Tk, no file IO, no global state, no network, no clock. It reads
its arguments and returns a list. It is import-safe in any order.

**Tk-freeness is a measured property, not an intention.** **[measured]**
`plugins/03_harmoniser/parser.py` imports only `csv, json, re, datetime, pathlib, typing`;
`inference.py` imports `re, typing` and `.parser`; loading both leaves `tkinter` absent from
`sys.modules`. The linter's only non-stdlib import will be `.parser`, so the property holds by
the same measurement.

**The trap, and how the test avoids it.** `plugins/03_harmoniser/plugin.py` does
`from tkinter import ttk` at module scope, so anything reached *through* `plugin.py` drags in
Tk — and `tests/conftest.py` mocks `tkinter` before any plugin import, so a test running under
conftest **cannot** observe the difference. The Tk-freeness test therefore runs the import in a
**subprocess with no mock**, which is the pattern `tests/test_view_smoke.py::_run` already
establishes in this suite for the opposite purpose.

**How session B calls it.** `HarmoniserView._validate` already loops the rows calling
`_validate_row(row, a_columns)`. Session B adds one call after that loop —
`lint_criteria(self.state.rows, self.state.a_columns)` — and renders the findings. **No change
to `_validate_row`, no change to `inference.py`, and no change to what blocks export.** The
linter is additive: remove the call and the current behaviour returns exactly.

**Why plugin 03 and not `plugins/_common/`.** The linter audits the *producer*, and
`07_criteria_parsing.md` §1 records that the producer and its consumers share no code today.
Putting it in `_common/` would create the first such dependency for no gain, and it needs
`parser.py::TARGET_ALIASES`, which lives in plugin 03.

---

## e. What this design cannot do

Stated plainly, because a linter that silently misses a class is worse than one with a
declared gap.

1. **It cannot catch F-166's class when the label does not name a column.** `EC-4` is catchable
   *only* because its label literally contains the word *"venue"*. A criterion reading
   *"Exclude robotics conference proceedings"*, mistranslated to `equals doc_type conference`,
   produces **no finding** — and **HO-13-8** records that this may be what `EC-4` actually
   meant. **The linter catches the instance; it does not catch the intent.**
2. **It cannot check whether an operand is the *right* operand.** `equals lang French` for a
   criterion about German is well-formed, single-valued, correctly targeted, and wrong. Nothing
   here sees it.
3. **It cannot tell a silently-defaulted threshold from a chosen one** (**CL-2**).
4. **It cannot see anything the label does not say.** The label is the harmonised cell; where
   `label` is empty the row falls back to `source_text`, and where both are thin the checks
   have nothing to compare. **[read]** `_infer_criterion_details` sets `what = [label] if label
   else [""]`, so an empty criterion validates clean today and will lint clean too.
5. **It cannot detect the LLM-refine path having rewritten the table** — F-158's subject.
   Nothing in the row records which engine produced it.
6. **Checks 1 and 7 are only as good as the corpus they are given.** With no `a_columns`,
   checks 1 and 3 are skipped silently; with no `corpus_rows`, check 7 is. **Skipping must be
   visible** — the return value will carry which checks ran, so a caller cannot mistake "no
   findings" for "checked and clean". That is F-64's shape and this design does not repeat it.

**The honest summary of coverage against the measured defects.** Of the three defective rows in
the repository's own reference contract (§7.5): `EC-1` caught by check 2, `EC-4` caught by
checks 1 **and** 2, `IC-5` caught by check 4. **Three of three.** That is a real result and it
is also a small sample — eight clean, one-per-line sentences, which §7.1 notes are the opposite
of the input this feature exists for.

---

## Candidate findings raised by this session

**Committed here rather than carried in chat, per F-179.** Neither is a register row; both are
for the coordinator to sweep.

### CL-1 — `_eval_criterion` returns `UNKNOWN` for two different conditions, and a caller cannot tell them apart

**Proposed severity: Medium.** `plugins/_common/evaluator.py::_eval_criterion` returns the
string `UNKNOWN` both when the operator is **not supported at all** and when the operator is
supported but the **value cannot be compared**. **[measured]**:

```
gte  target=lang  value='en'    what=['2000']  -> UNKNOWN     operator IS executable
gte  target=year  value='2020'  what=['2000']  -> MET
llm  target=lang  value='en'    what=['prose'] -> UNKNOWN     operator is NOT executable
```

**Consequence.** Executability cannot be established by probing, so every consumer that needs
to know which operators execute must **restate** the set — which is precisely F-109, and this
linter would have become the eighth copy had the guard test not been designed around it.
Downstream, `plugins/_common/runner.py::run_screen` counts both conditions into the same
bucket, so a run report cannot distinguish *"this criterion cannot run here"* from *"this
record's value was unusable"*.

**Duplication check.** Adjacent to **F-64** (*"reports `UNCERTAIN` without recording why"*),
which is the EL/IL twin of this shape one stage over, and to **F-65**, which is about the
stage/operator pairing rather than about the report. **[measured]** `_eval_criterion` appears
in F-65's evidence cell and in F-109's; neither states the overload. Novel as stated;
the coordinator may prefer to extend F-64.

**Suggested fix.** Return a distinct sentinel for an unsupported operator — `_eval_criterion`
already has `_eval_criterion_detail` beside it, which attaches a stage-tagged note, so the
information exists and is discarded by the terser entry point.

### CL-2 — a defaulted confidence threshold is byte-identical to a chosen one

**Proposed severity: Low.** **[read]** `ui.py::_harmonise_no_llm` writes
`f"{DEFAULT_THRESHOLD:.2f}"` — the literal `0.60` — into every EL/IL row that lacks a
threshold, and `_validate_row` does the same silently for a blank EL/IL cell. A user who types
`0.60` produces identical bytes. **No artefact anywhere records which happened**, so neither a
linter, nor a reviewer, nor the bundle can report *"this gate was never chosen"*.

**Duplication check.** **F-176** covers the *restatement* of the constant and the silent
swallow of an unparseable value; it does not cover the indistinguishability of a default from a
choice. **F-88** is the general provenance shape and is scoped to model/endpoint/prompt.
Novel as stated, and plausibly better recorded as an annotation on F-176 than as a row — the
coordinator's call.

**Pinned as a gap rather than left as a surprise.**
`tests/test_criteria_linter.py::TestTheQuietChecks::test_a_defaulted_threshold_is_indistinguishable_and_is_not_reported`
asserts that all four EL/IL rows carry exactly `0.60` and that the linter reports **nothing**
about them. When a later wave records which happened, that test is where the gap closes, and
it fails loudly at the moment it does.

### CL-3 — the harmoniser cannot check a rule against the corpus, because it never holds the corpus

**Proposed severity: Low.** **[measured]** `ui.py::_UiState` retains `a_path` and `a_columns`
but no records, and `parser.py::_load_a_header_and_stats` reads the header, samples 200 rows
to compute text-field coverage, and discards every row. Nothing in plugin 03 can answer *"how
many records would this rule actually match?"* without re-reading the file.

**Consequence.** Three of the things the Validate button is criticised for not checking are
corpus-dependent and therefore unreachable from where it stands: whether an operand will ever
match (`07_criteria_parsing.md` §5), whether a rule removes an implausible share of the corpus
(F-166's 112 of 776 would have been visible as a number), and check 7 above. It also means
**F-175**'s target-collapse decision is taken from a 200-row sample of a 776-record corpus and
cannot be revisited later in the same session without another read.

**Duplication check.** **[measured]** no register row mentions `_UiState`, and F-173's subject
is what `_validate` does with findings it already has rather than what it cannot compute.
Adjacent to **F-175** (which records the 200-row sample as a *provenance* inaccuracy, not as a
capability limit) and to **F-166**'s remedy. Novel as stated; small, and it is a design
constraint more than a defect — the coordinator may prefer it as an annotation on F-175.

**Suggested fix.** None proposed. Retaining 776 records in `_UiState` to serve a linter is not
obviously right, and `tools/measure_prompt_size.py` already establishes the alternative shape —
a headless entry point that reads the corpus once, which `07_criteria_parsing.md` §8.1 argues
is the cheapest useful version of T1 anyway.

---

## What was not done

- **No code was written.** This commit is design only, per the brief's instruction to report
  before writing anything.
- **`inference.py` was not touched**, deliberately: F-166 and F-167 must still be present for
  the mandatory regression fixtures to mean anything.
- **No UI wiring**, no `_validate` change, no `plugin.py` change. Session B owns those.
- **Check 7's severity is [not established]** beyond "lowest" — whether "matches nothing"
  should read as `INERT` or as `NOTICE` depends on seeing it fire on real input, and it fires
  on nothing this repository contains.
- **The false-positive rate of check 1 on realistic prose is [not established].** It is 0 on
  eight clean sentences. Settling it needs criteria files this repository does not have, which
  is the same limit §7.1 records for every claim about this stage.
