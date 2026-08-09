# metaScreener — Wave 3: Q1 closure and the frozen build

Two independent parts. Part A is documentation and one new finding. Part B is the
build experiment. Do A first — it's short, and B may fail in ways that eat the
session.

Standing rules as before: one commit per unit of work, suite green after each
(baseline 379 passed, 4 skipped), no golden may move, stop and report rather than
expanding scope.

---

# Part A — close Q1, and log what the investigation actually found

## A1. Log IC-5 as a new finding

`IC-5` is an IL-stage **inclusion** criterion using the `contains` operator. The
non-LLM branch never evaluates it, so it has never been applied to any record in
any run — it only ever blocked `PASS_CLEAN`, which is why the committed IL golden
shows `REVIEW 80, OUT 4` and zero `PASS_CLEAN`.

Verify this independently before logging. Then establish:

- Which stages evaluate which operators, and where a `contains` criterion assigned
  to EL or IL falls through. Is this specific to `contains`, or does every
  non-`llm` operator at an LLM stage silently no-op?
- Whether the Harmoniser can assign a deterministic operator to an LLM stage in
  normal use, or whether this criteria table is unusual.
- What the correct behaviour is: evaluate it deterministically within the LLM
  stage, refuse the assignment at parse time with a warning, or route it back to
  EH/IH.

Severity is yours to argue, but note the consequence in the finding: the published
demonstration ran with **seven effective criteria, not the eight its criteria table
declares**. Cross-reference F-64.

Log only. Do not fix — the fix changes screening outcomes and needs its own wave.

## A2. Write the Q1 resolution into `docs/llm-evaluation.md`

The manuscript-run artifacts are not archived and will not be recovered. Q1 is
being closed on the evidence rather than on a reproduction. Write it up honestly.

Established facts, all verified during this work — re-verify anything you want to
assert:

- **The deterministic half reproduces exactly.** Across three independent runs
  (manuscript ≤2026-04-01, goldens 2026-05-02, archived bundle 2026-05-07):
  776 records → EH excludes 125 → 651 → IH excludes 566 → 85. Identical every
  time. 98.3% of exclusions come from this half, and it is bit-reproducible.
- **The LLM half does not.** The manuscript figure requires 12 LLM exclusions
  (776 − 691 deterministic − 12 = 73). The committed goldens give 5: EL `OUT` 1,
  IL `OUT` 4, leaving 80.
- **The gap localises precisely.** It is 7 records at IL. The IL golden holds 30
  records with valid-quote `not_meet` on IC-1 at confidence 0.1–0.4, excluded from
  action only by the 0.60 threshold. Seven of those crossing 0.60 yields 11 IL
  exclusions and 73 survivors. Nothing else in the pipeline has that shape.
- **Truncation is ruled out**, on five independent grounds — nothing in either
  corpus exceeds 2927 characters so the 4000 setting truncates nothing; every LLM
  criterion targets `keywords`, which never approaches either limit; all 254
  evidence quotes came from `keywords`, none from `abstract`, none at or beyond
  character 1500; and no single threshold value reproduces 73 (0.40→78, 0.30→77,
  0.20→68).
- **The two runs were not executing the same code.** The manuscript figure entered
  the README at `985973b` (2026-04-01). The EL and IL stages were restructured on
  2026-05-02 across `f3fa6bb`, `90ff050`, `edd466d`, `9553393`, `3b4baf7`,
  `8bec55e` — including a fix for duplicate LLM helpers shadowing `_common`. The
  goldens were captured after that work.
- **Degenerate model output is possible and observed.** The 2026-05-07 archived run
  returned one decision, one confidence value, and three boilerplate spans across
  170 calls. Already documented in the Limitations section.

Write a subsection that states: which figure the manuscript reports and from when;
that the deterministic stages are exactly reproducible and the LLM stages are not;
that a replay of the archived goldens yields 80 rather than 73; where the
difference sits and why; and what has been ruled out. Report both numbers. Do not
change the README's 73, 90.6% or 98.3% — those are the manuscript's figures and
they remain the reported result.

Then add one sentence to the README pointing at this subsection, so a reader who
replays the goldens and gets 80 finds the explanation instead of a contradiction.

Commit as `docs: resolve Q1 — reproducibility of the deterministic and LLM stages`.

---

# Part B — build the distributable and find out if it works

Predicted broken since the 3.1.0 restructure, but never tested. `hook-plugins.py`
exists to collect the plugin dependencies and is disabled by `hookspath=[]` in both
specs (F-40); PyInstaller cannot discover those imports itself because `plugins/`
ships as `--add-data`, i.e. as data it does not analyse (F-09). Plugin load
failures `print()` to a stdout the windowed build discards (F-35), so the
predicted symptom is *silently missing tabs*, not an error.

Do not fix anything until the build has run once and told us what is actually
wrong. The point of this wave is measurement.

## B1. Build the console spec first, unmodified

`metaScreener-console.spec` sets `console=True`, so failures are visible. Build it
exactly as committed — no edits — and launch it. Capture the full stdout,
including the `PLUGIN LOADER:` banners from `plugin_manager.py`.

Report: does it start; how many tabs appear; which plugins fail and with what
error. If it will not build at all, report the build error and stop — that is a
finding in itself.

If you cannot launch a GUI in your environment, say so plainly and hand me a
numbered checklist: the exact command to run, what to look for, and what to copy
back. Do not simulate the result.

## B2. Diagnose against the prediction

Predicted missing from the frozen build: `pandas`, `openpyxl`, `langdetect`,
`rapidfuzz`, `PIL`, `pytesseract`. Determine which are actually absent — inspect
the build's warn file and the bundled tree rather than inferring from the crash.
Report the real list against the predicted one.

Also determine whether the custom plugin loader is doing anything necessary here.
It was written for exactly this case: `plugins/` bundled as data, not importable
by normal means. Does it work in the frozen build? Does `sys._MEIPASS` resolve as
`_plugins_root_frozen()` expects? This is the evidence F-19 has been waiting for —
the earlier finding that stock `importlib` suffices was measured in dev mode only,
which is not the case the loader exists for.

## B3. Fix the minimum, then rebuild

Smallest change that makes the console build load all seven tabs. Most likely
`hookspath=['.']`, or explicit `hiddenimports`. Prefer whichever is more
transparent to a future maintainer, and say why you chose it.

Then rebuild, relaunch, and confirm seven tabs. Commit as `fix(F-09,F-40): collect
the plugin dependencies in the frozen build`.

## B4. Then the windowed spec

Build `metaScreener.spec`, launch, count tabs. If a plugin fails here it is
invisible by construction — which is F-35. If B3 fixed everything the windowed
build should match, but verify rather than assume; `console=False` changes more
than logging.

## B5. Report, do not fix

Write your findings to `docs/internal/diagnostic/04_frozen_build.md`: what was
broken, what the fix was, what remains broken, and a verdict on whether the
distributable is currently fit to ship. Update F-09, F-35 and F-40 in the register
with the measured outcome, replacing the *inferred* labels. Add a finding for
anything new.

If the build reveals that the custom loader is load-bearing after all, say so
plainly and revise F-19's verdict — that would be a correction to the diagnostic's
recommendation, and it should be recorded as one.

---

Finish with: what you committed, the suite result, the tab count for both builds,
and a one-line answer to "could a reviewer download this and run it today?"
