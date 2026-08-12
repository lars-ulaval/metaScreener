<!-- SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo -->
<!-- SPDX-License-Identifier: MIT -->

# The red CI: diagnosis of the failure observed at wave 12

**Session:** wave-13 diagnostic, part A. Read-only.
**HEAD at time of writing:** `42a5c42` (tag `post-wave-12`), branch `diag/wave-13-criteria`.
**Nothing in this document was fixed.** No code, test, golden, register row or sample
was modified by the session that produced it.

## Naming

The brief's default path was `docs/internal/CI_FAILURE_wave12.md`. Every other
top-level file in `docs/internal/` is `SCREAMING_SNAKE` (`FIX_WAVE_10_PROVENANCE.md`,
`FIX_WAVE_12_FLAG_ONLY.md`, …), so this file is `CI_FAILURE_WAVE_12.md`. That is the
only deviation from the brief's naming, and it is a case change.

The filename is nonetheless a misnomer, for the reason given in Correction 1: the
failure was not introduced by wave 12. The name is kept because it is the anchor the
brief chose and because wave 12 is when it was noticed.

---

## 0. Evidentiary conventions

This document separates three kinds of claim, and labels every one:

- **EXECUTED** — a command was run in this session; the command and its output are
  shown. This is the strongest class.
- **READ** — derived from repository source or from git metadata, without executing
  the behaviour in question.
- **SERVICE** — drawn from `%TEMP%\ci_wave12.txt`, a capture of the GitHub REST API.
  These are claims about the **CI service**, not about the repository. They were
  re-verified against the file in this session but not against the API.
- **UNDETERMINED** — could not be established with the evidence available. Said so
  rather than inferred.

Line numbers are deliberately absent; symbols and section headings are cited instead.

### What the service evidence does and does not contain

`%TEMP%\ci_wave12.txt` was read in full. It contains the last 20 workflow runs
(status, conclusion, head SHA, timestamp) and a **per-job, per-step listing for the
most recent run only** — run `31602134818`, head `42a5c42`, `2026-08-12T13:34:43Z`.

`%TEMP%\ci_wave12_logs\` **does not exist** on this machine. Verified:

```
$ if (Test-Path "$env:TEMP\ci_wave12_logs") { ... } else { "ABSENT: ..." }
ABSENT: C:\Users\alere\AppData\Local\Temp\ci_wave12_logs does not exist
```

**No CI log text was available to this session.** Every conclusion below therefore
rests on repository source plus local reproduction, never on a runner's log. Where
the log would have been the decisive evidence, this is stated. In the event the
reproduction (§5) turned out to be stronger evidence than a log would have been,
because it isolates causes rather than merely displaying them.

The three service facts this document relies on, all re-verified against the file:

| Fact | Value |
| --- | --- |
| Last green run | `f014e2f`, `2026-08-10T12:43:04Z`, run `31389331742` |
| First red run | `bef2c0b`, `2026-08-10T13:41:04Z`, run `31394131823` |
| Consecutive failures since | 7, ending `42a5c42` at `2026-08-12T13:34:43Z` |

And the per-cell fact, available for `42a5c42` **only**: in all 16 cells, steps 1–4
(Set up job / Checkout / Set up Python / Install package + dev dependencies)
succeeded, step 5 `Run pytest` failed, and steps 6–8 (the three audit steps) were
skipped. The matrix is 4 OS × 4 Python = 16, confirmed by READ of
`.github/workflows/test.yml::jobs.test.strategy.matrix`.

---

## 1. Step-0 gate

All six checks passed; the session proceeded.

| Check | Expected | Actual | |
| --- | --- | --- | --- |
| `git rev-parse HEAD` | `42a5c42` | `42a5c42eba394b472f67378e84a50fff1e58815f` | ✅ |
| `git describe --tags` | `post-wave-12` | `post-wave-12` | ✅ |
| `git status --porcelain` | empty | empty | ✅ |
| `git rev-list --left-right --count origin/main...HEAD` | `0 0` | `0	0` | ✅ |
| `git ls-files -s tests/golden` | re-verifiable | 9 entries, recorded in Appendix A | ✅ |
| Full suite | 1600 passed, 7 skipped | `1600 passed, 7 skipped in 42.84s` | ✅ |

**EXECUTED.** The local working tree at `42a5c42` passes the suite that CI cannot.
That contradiction is the subject of this document.

---

## 2. Corrections to the coordinator's brief

Per the ground rules, these come first.

### Correction 1 — Wave 12 did not break CI. Wave 10 did. The brief's implication is wrong, and neither of the two alternatives the brief offered is the answer.

The brief said: *"all 16 cells failed on the wave-12 push," which is true but implies
wave 12 broke CI*, and then offered a fork — *"If they are all wave-12 session
branches then wave 12 did break it, before the merge, and the brief's implication is
right for the wrong reason."*

Neither arm holds. **The seven red SHAs span three waves**, and every one of them is
on `main`.

**EXECUTED** — ancestry:

```
$ for s in bef2c0b c6b0f77 d6a0773 ec8f7c3 8b5a972 7a39eda 42a5c42; do
      git merge-base --is-ancestor $s origin/main && echo YES || echo NO; done
bef2c0b on-origin/main: YES
c6b0f77 on-origin/main: YES
d6a0773 on-origin/main: YES
ec8f7c3 on-origin/main: YES
8b5a972 on-origin/main: YES
7a39eda on-origin/main: YES
42a5c42 on-origin/main: YES

$ git rev-list --count f014e2f..42a5c42
52
$ git log --merges --oneline f014e2f..42a5c42
(no output — zero merge commits in the range)
```

The red period is **52 commits, entirely linear**. The wave branches
(`fix/wave-10-provenance`, `fix/wave-11-provider-choice`, `fix/wave-12-flag-only`,
`docs/wave-12-measurement`) are fast-forward tips, so every branch commit is also a
main commit and `git branch --contains` cannot separate them.

Wave attribution, by the tag and subject each red SHA carries (**READ**):

| # | SHA | Timestamp (SERVICE) | Tag / branch tip | Wave |
| --- | --- | --- | --- | --- |
| 1 | `bef2c0b` | 2026-08-10T13:41Z | tip of `fix/wave-10-provenance` — *"docs: record wave 10…"* | **10** |
| 2 | `c6b0f77` | 2026-08-10T13:49Z | tag `post-wave-10` | **10** |
| 3 | `d6a0773` | 2026-08-10T17:29Z | tag `post-wave-11a` | 11 |
| 4 | `ec8f7c3` | 2026-08-10T18:19Z | tag `post-wave-11b` | 11 |
| 5 | `8b5a972` | 2026-08-10T21:54Z | tag `post-wave-11` | 11 |
| 6 | `7a39eda` | 2026-08-12T03:06Z | tag `post-wave-12a` | 12 |
| 7 | `42a5c42` | 2026-08-12T13:34Z | tag `post-wave-12` | 12 |

Two wave-10 SHAs, three wave-11, two wave-12.

There is a further reason the "wave-12 session branch" arm cannot be right. **READ**,
`.github/workflows/test.yml::on`:

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch: {}
```

The workflow does not trigger on a push to any branch other than `main`. A wave
session branch cannot produce a CI run at all except as a pull request targeting
main. So no red run in this window can be dismissed as "a branch push that never
reached main" — and in fact `c6b0f77`, tagged `post-wave-10`, is a main commit that
ran red on 2026-08-10, **two days before wave 12 existed**.

**The correct statement:** CI went red on `main` during wave 10, on 2026-08-10, and
waves 11 and 12 inherited a red CI without anyone noticing. Wave 12 added no new
breakage of its own; the second cause that arrived during wave 12 (§4.2) is an
external package release, not a commit.

### Correction 2 — "all 16 cells failed" is established for the last run only, and must not be projected backwards.

The brief treats the 16-cell failure as a property of the red period. The service
evidence carries per-job detail for run `31602134818` (`42a5c42`) **only**. For the
six earlier red runs the capture gives a conclusion and nothing else. A GitHub run is
`failure` if **any** cell fails, so "red" is consistent with 4 cells failing as
readily as with 16.

This matters, because §4 establishes that for the first five red runs only **4 of 16
cells** could have been failing.

### Correction 3 — hypothesis (b)'s reasoning about `core.autocrlf` is wrong, and the correction changes which platforms it predicts.

The brief said: *"Consider that GitHub's Windows runner defaults to
`core.autocrlf=true` while Linux runners do not — work out what each platform would
actually receive."*

`core.autocrlf` is not the operative setting here. `.gitattributes` in this
repository begins `* text=auto`. When an explicit `text` attribute is set, git
performs the checkout conversion governed by **`core.eol`**, whose default is
`native` — and it does so *regardless of `core.autocrlf`*. `core.autocrlf` is the
fallback for paths with no `text` attribute; it is not a master switch.

This is not a pedantic distinction. I initially ran the "Linux simulation" as a clone
with `core.autocrlf=false`, and it produced CRLF anyway:

```
$ git -c core.autocrlf=false clone … ci_probe_linuxlike
docs/data/eval_decisions_v1.csv CRLF=345 LFonly=0     # <-- still CRLF
```

That experiment was invalid and its result is not evidence of anything. Repeating it
with `core.eol=lf` gave LF, as expected. **The lesson for the fix options in §7 is
that setting `core.autocrlf` in the workflow would not have changed anything**; only
an attribute change or a `core.eol` change would.

### Correction 4 — hypothesis (b) does not predict "all platforms failing". It predicts Windows only, and that contradiction is the reason a second cause had to be found.

The brief asked whether the `.gitattributes` mechanism *"predicts the observed
pattern (all platforms failing) or contradicts it."* It **contradicts** it: it
accounts for exactly 4 of 16 cells (§4.1). Taking that contradiction seriously is
what surfaced the real all-16 cause (§4.2). Had the contradiction been smoothed over,
the diagnosis would have stopped at the wrong answer.

### Correction 5 — the "eight of nine unpinned" framing (F-15) is right, but the failure it produced is not the one the brief anticipated.

The brief said of (c): *"Install SUCCEEDED in all cells, so this is not an install
failure — but a package that installs and then misbehaves survives."* Correct, and
this is the cause. But the mechanism is not a package that *misbehaves*. It is a
package that **changed its own dependency set**, removing a transitive package the
test suite had been silently relying on. The new major version installs and works
perfectly; what broke is something that was never declared at all.

### Correction 6 — the brief's own count of unpinned dependencies.

F-15 is quoted as "eight of nine unpinned". **READ**,
`pyproject.toml::project.dependencies`: nine entries, of which `openai>=1.40.0` has a
lower bound and the other eight (`pymupdf`, `pillow`, `pytesseract`, `rapidfuzz`,
`requests`, `pandas`, `openpyxl`, `langdetect`) have none. So "eight of nine
unpinned" is accurate if "unpinned" means "no bound at all". It is worth noting that
the ninth is not pinned either — a lower bound is not a pin, and it is precisely the
absence of an *upper* bound on `openai` that caused this outage.

---

## 3. A2 — the window between green and red

`f014e2f` is a direct ancestor of `bef2c0b`, so no bisect was required.

**EXECUTED:**

```
$ git merge-base f014e2f bef2c0b
f014e2f67eb67739a25bc852407b8ec1b89f9dc8      # == f014e2f, i.e. linear
$ git log --oneline f014e2f..bef2c0b
bef2c0b docs: record wave 10, close F-98/F-141, and repair what the review found
e9c31e7 docs(F-96): name the model the validation study measured
03acf06 docs(F-88): correct the second FAQ claim the provenance block falsifies
ba68b39 docs(F-141, F-143): disclose waves 7-9 to the user who already has results
97886f3 fix(F-88): record which engine produced each run
78cd401 fix(F-98): freeze the study input so the goldens can move
```

Six commits, one hour of work (08:58 → 09:38 local, `-0400`). Every one read.

| Commit | Subject | Touched | Can it break CI? |
| --- | --- | --- | --- |
| `78cd401` | fix(F-98): freeze the study input so the goldens can move | `.gitattributes`; `docs/data/study_input/` (4 CSVs + SHA256SUMS + meta); `docs/index.md`; `docs/llm-evaluation.md`; **`tests/test_study_input_freeze.py` (new, 303 lines)** | **YES — this is it** |
| `97886f3` | fix(F-88): record which engine produced each run | `plugins/06_el/`, `plugins/07_il/`, `plugins/_common/{bundle,llm_client,stage_state}.py`; **`tests/test_provenance.py` (new, 411 lines)**; README/docs | Not on its own — see §4.2 |
| `ba68b39` | docs(F-141, F-143) | `CHANGELOG.md` only | No |
| `03acf06` | docs(F-88) | `docs/faq.md` only | No |
| `e9c31e7` | docs(F-96) | `docs/faq.md`, `docs/llm-evaluation.md` | No |
| `bef2c0b` | docs: record wave 10 | `CHANGELOG.md`, `docs/**` only | No |

**The introducing commit is `78cd401`** — *fix(F-98): freeze the study input so the
goldens can move*, authored `2026-08-10 08:58:40 -0400` = `12:58:40Z`. That lands
**after** the last green run (12:43Z) and **before** the first red run (13:41Z). The
window is closed on both sides.

Its committed time being 15 minutes after the last green run, and 43 minutes before
the first red one, is as tight a bracket as this evidence can give.

## 4. A3 — CI config and git attributes across the red period

**EXECUTED:**

```
$ git diff --stat f014e2f..42a5c42 -- .github/
(no output)
```

**`.github/` did not change at all across the red period.** The workflow that was
green on `f014e2f` is byte-identical to the one failing on `42a5c42`. Nothing about
the CI configuration is implicated, and no CI-config change can be the fix.

`.gitattributes` did change, twice. **EXECUTED**,
`git diff f014e2f..42a5c42 -- .gitattributes`: the pre-image was two rules
(`* text=auto`, `tests/golden/** binary`); the post-image adds
`docs/data/study_input/*.csv binary` (in `78cd401`) and three
`docs/data/wave12_local_runs/*.{csv,jsonl,json} binary` rules (in wave 12, for
F-159).

Both additions are correct and well-commented. **Neither covers the files that
actually broke.** That is §4.1.

---

## 5. A5 — the decisive experiment

Run first, because it is what makes the rest of this document evidence rather than
argument. A fresh clone from `origin`, a clean venv, and the workflow's own install
command. Then, to isolate causes, the full 2×2 of {working tree, fresh clone} ×
{the long-standing local environment, a freshly resolved one}.

**EXECUTED.** Clone and install exactly as `.github/workflows/test.yml` does:

```
$ git clone https://github.com/lars-ulaval/metaScreener.git ci_probe_w13
$ cd ci_probe_w13 && git log --oneline -1
42a5c42 docs: resolve every pending hash, and record two conventions
$ python -m venv .venv_ci
$ ./.venv_ci/Scripts/python.exe -m pip install --upgrade pip
$ ./.venv_ci/Scripts/python.exe -m pip install -e ".[dev]"
Successfully installed … openai-3.0.0 httpcore2-2.10.0 httpx2-2.10.0 pandas-3.0.5
  pillow-12.3.0 pytest-9.1.1 numpy-2.4.6 pydantic-2.13.4 …
```

Install **succeeded**, matching the service evidence for step 4. Then:

```
$ ./.venv_ci/Scripts/python.exe -m pytest tests/ -q
ERROR collecting tests/test_error_classification.py
tests\test_error_classification.py:…: in <module>
    import httpx
E   ModuleNotFoundError: No module named 'httpx'
ERROR collecting tests/test_run_report.py
tests\test_run_report.py:…: in <module>
    import httpx
E   ModuleNotFoundError: No module named 'httpx'
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!
2 errors in 9.79s
```

**CI reproduced.** Two collection errors; pytest exits non-zero without running a
single test; step 5 fails; steps 6–8 are skipped. That is precisely the step pattern
the service evidence reports for all 16 cells of `42a5c42`.

### The 2×2

| | local env (`openai 1.106.0`) | fresh env (`openai 3.0.0`) |
| --- | --- | --- |
| **working tree** `S:\…\prisma-hub_v3_repo` | **1600 passed, 7 skipped** | *(not run — see note)* |
| **fresh clone** `%TEMP%\ci_probe_w13` | **3 failed, 1597 passed, 7 skipped** | **2 collection errors** → with those two files ignored: **11 failed, 1503 passed** |

Each cell **EXECUTED**; commands and tails in Appendix B. The working-tree × fresh-env
cell was not run because the two isolating experiments below settle the question more
cleanly than it would, and running a foreign venv against the working tree risks
`pythonpath` ambiguity between the editable install and the tree under test.

Two further isolating runs, both **EXECUTED**, complete the separation:

```
# fresh clone, fresh env, with httpx restored — isolates everything except cause 1
$ ./.venv_ci/Scripts/python.exe -m pip install httpx
$ ./.venv_ci/Scripts/python.exe -m pytest tests/ -q --tb=no
3 failed, 1597 passed, 7 skipped, 1 warning in 60.58s
```

```
# the same three, under the local env too
$ cd %TEMP%\ci_probe_w13 && python -m pytest tests/ -q --tb=no
3 failed, 1597 passed, 7 skipped in 61.08s
```

**Reading the matrix:**

- The **3 freeze failures** appear in the fresh clone under **both** environments and
  in **neither** working-tree run. They are therefore **committed-state versus
  working-tree divergence**, independent of the dependency set. → cause 2, §4.1.
- The **2 collection errors** (and the 8 further `test_provenance` failures they
  drag down) appear only under the **fresh environment**. They are therefore purely
  **environmental**. → cause 1, §4.2.
- The two causes are **independent**. Fixing either leaves the other.

The delta the brief asked for, as test names and assertion output rather than counts,
is in §4.1 and §4.2 respectively.

---

## 4. A4 — the candidate causes, and which cells each accounts for

Two causes are real. Together they account for all 16 cells, but **at different
times**, and neither accounts for all 16 alone throughout.

### 4.1 Cause 2 (chronologically first) — CRLF/LF byte-identity. **ESTABLISHED. 4 of 16 cells. Live from 2026-08-10T12:58Z.**

This is hypothesis (b), confirmed as a real cause but by a different mechanism and
with different cell coverage than the brief proposed.

**The failing tests, with assertion output (EXECUTED, fresh clone):**

```
FAILED tests/test_study_input_freeze.py::TestTheFrozenInputReproducesThePublishedResults
       ::test_output_is_byte_identical_to_the_committed_artefact[eval_decisions_v1.csv]
FAILED …[eval_results_v1.csv]
FAILED …[eval_disagreements_v1.csv]

>       assert regenerated.read_bytes() == published.read_bytes(), (
            f"docs/data/{name} is no longer reproducible from the frozen "
            f"study input. Either the frozen input drifted, the ingestor's "
            f"behaviour changed, or docs/data/{name} was edited by hand. …"
        )
E       assert b'stage,a_id,...isjoint,no,\n' == b'stage,a_id,...joint,no,\r\n'
E         At index 63 diff: b'\n' != b'\r'
```

The left operand is the **regenerated** file (LF). The right is the **published,
checked-out** file (CRLF). Note that the test's own diagnostic message names three
possible causes — drifted input, changed ingestor, hand-edit — and the actual cause
is a fourth one it does not mention.

**Mechanism, established from source and confirmed by execution:**

1. The test compares raw bytes of files regenerated by `tools/eval_ingest.py`
   against the committed `docs/data/eval_{decisions,results,disagreements}_v1.csv`.
2. **Those three files are covered by no `binary` rule.** The `.gitattributes` rules
   are `tests/golden/**`, `docs/data/study_input/*.csv` and
   `docs/data/wave12_local_runs/*.{csv,jsonl,json}`. The published outputs live one
   directory up, in `docs/data/` itself. **EXECUTED:**

   ```
   $ git check-attr -a docs/data/eval_decisions_v1.csv …
   docs/data/eval_decisions_v1.csv: text: auto
   docs/data/eval_disagreements_v1.csv: text: auto
   docs/data/eval_results_v1.csv: text: auto
   ```

   They fall through to `* text=auto`, so git converts them on checkout.
3. The blobs are LF, and the local working tree also holds LF — **EXECUTED**,
   comparing `git cat-file blob HEAD:<path>` against working-tree bytes:

   ```
   eval_decisions_v1.csv       wt=4bd32c8d07527341 blob=4bd32c8d07527341 SAME  CRLF=0 LF_only=345
   eval_results_v1.csv         wt=975af0eb8fa911b8 blob=975af0eb8fa911b8 SAME  CRLF=0 LF_only=345
   eval_disagreements_v1.csv   wt=bb46bc4f527ca46e blob=bb46bc4f527ca46e SAME  CRLF=0 LF_only=89
   ```

   A *fresh checkout on Windows* does not: `core.eol` defaults to `native`, so
   `* text=auto` writes CRLF. That is the divergence, and it is why the working tree
   passes while any fresh clone on Windows fails.
4. `tools/eval_ingest.py` regenerates the three CSVs with **explicit LF on every
   platform** — **READ**, three sibling call sites in that module:

   ```python
   with path.open("w", encoding="utf-8", newline="") as fh:
       w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
   ```

   `newline=""` suppresses Python's own translation and `lineterminator="\n"`
   overrides `csv`'s default `\r\n`. So `regenerated` is LF on Windows, Linux and
   macOS alike.

**Cell coverage — 4 of 16, and the reasoning that fixes the number:**

| Platform | `published` (checkout) | `regenerated` (ingestor) | Result |
| --- | --- | --- | --- |
| windows-latest (`core.eol=native` → CRLF) | CRLF | LF | **FAIL** ×3 |
| ubuntu-22.04 / ubuntu-24.04 / macos-14 (`native` → LF) | LF | LF | pass |

The Windows arm is **EXECUTED** — the fresh clone on this Windows machine produced
exactly those three failures and nothing else. The non-Windows arm is **READ**: it
follows from `lineterminator="\n"` being platform-independent and `core.eol=native`
resolving to LF, and cannot be executed here.

A fourth artefact, `docs/data/eval_summary_v1.txt`, is compared by the same
parametrised test and **passes on every platform**. **READ**,
`tools/eval_ingest.py::write_summary_text`:

```python
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

`Path.write_text` without `newline=` applies platform-native translation, so the
regenerated summary is CRLF on Windows and LF on Linux — matching the checkout on
both. The three CSVs are LF-pinned and mismatch on Windows; the one `.txt` is
platform-native and matches everywhere. **The inconsistency between the two writer
styles inside one module is the whole defect.**

> This is also where I must flag an experiment of mine that produced a misleading
> result. An intermediate run against an LF checkout using the *Windows* ingestor
> showed `eval_summary_v1.txt` failing and the three CSVs passing — the exact
> mirror image. That hybrid (LF checkout + native-CRLF writer) corresponds to no
> real cell and is not evidence. It is recorded here only because it is the kind of
> half-simulation that would otherwise look like a finding.

**Timing.** `78cd401` was committed at 12:58Z on 2026-08-10; the last green run was
15 minutes earlier and the first red run 43 minutes later. From `bef2c0b` onward the
4 Windows cells fail. The 5 red runs of 2026-08-10 (`bef2c0b` … `8b5a972`) are
therefore **LIKELY** — not established — to have been 4-cell failures, since no
per-cell data exists for them (Correction 2).

**Latent, not currently triggering — the enumeration rot.** The `.gitattributes`
`binary` rules enumerate *file extensions*. The extension-less and `.txt` companions
in the same directories are not covered. **EXECUTED:**

```
$ git check-attr -a docs/data/study_input/SHA256SUMS \
    docs/data/wave12_local_runs/SHA256SUMS \
    docs/data/wave12_local_runs/wave12_local_runs.meta.txt \
    docs/data/study_input/study_input.meta.txt
docs/data/study_input/SHA256SUMS: text: auto
docs/data/wave12_local_runs/SHA256SUMS: text: auto
docs/data/wave12_local_runs/wave12_local_runs.meta.txt: text: auto
docs/data/study_input/study_input.meta.txt: text: auto
```

Both `SHA256SUMS` manifests — the files whose entire purpose is to pin bytes — are
themselves subject to line-ending rewriting on checkout. This is **not currently
breaking anything**: the fresh-clone run produced exactly 3 failures, so the readers
of these files tolerate CRLF (they are parsed as text, not hashed). It is recorded
because it is the same defect one directory over, and because a future test that
hashes a `SHA256SUMS` file would fail on Windows only, for reasons that would take a
session to find. Comment in `.gitattributes` claims these bytes "have to survive
checkout unaltered or both checks fail at once" — for the `.csv`/`.jsonl`/`.json`
files that is now true; for the manifests asserting it, it is not.

### 4.2 Cause 1 (chronologically second, and the one that produced the 16-cell pattern) — an undeclared `httpx`. **ESTABLISHED. 16 of 16 cells. Live from 2026-08-12T01:56Z.**

This is hypothesis (c), confirmed, with the mechanism corrected per Correction 5.

**Mechanism, established from source and by execution:**

1. Two test modules import `httpx` at module scope, unguarded. **READ:**

   ```python
   # tests/test_error_classification.py, tests/test_run_report.py
   import httpx
   import openai
   import pytest
   ```

   They use it to build the transport objects that `openai`'s exception constructors
   take: `_REQ = httpx.Request("POST", "http://localhost:11434/v1/chat/completions")`
   and `httpx.Response(code, request=_REQ, …)`.
2. **`httpx` is declared nowhere.** **EXECUTED**, `grep -rn "httpx" pyproject.toml
   setup.py setup.cfg requirements*.txt` → no output. It has always arrived as a
   transitive dependency of `openai`.
3. **The shipped application never imports it.** **EXECUTED**, grep over `plugins/`,
   `metascreener/`, `run.py`: the only hits in `plugins/_common/llm_client.py` are
   two prose comments about how httpx normalises `base_url`. So this is a
   **test-only** dependency, undeclared even as a dev extra.
4. `openai` 3.0.0 replaced `httpx` with `httpx2`. **EXECUTED:**

   ```
   $ ./.venv_ci/Scripts/python.exe -m pip show openai
   Name: openai
   Version: 3.0.0
   Requires: anyio, distro, httpx2, jiter, pydantic, sniffio, tqdm, typing-extensions
   $ ./.venv_ci/Scripts/python.exe -c "import httpx2; print(httpx2.__version__)"
   httpx2 OK 2.10.0
   $ ./.venv_ci/Scripts/python.exe -c "import httpx"
   ModuleNotFoundError: No module named 'httpx'
   ```

5. `pyproject.toml` declares `openai>=1.40.0` with no upper bound, so
   `pip install -e ".[dev]"` resolves 3.0.0, installs cleanly — hence **step 4
   succeeds in all 16 cells** — and leaves no `httpx`.
6. Collection of the two modules raises `ModuleNotFoundError`; pytest reports
   `Interrupted: 2 errors during collection` and exits non-zero **before running any
   test**. Step 5 fails; the three audit steps never run.
7. It also takes down a third module by import coupling. **EXECUTED** — the mechanism
   for the 8 `test_provenance` failures:

   ```
   tests\test_provenance.py:…: in _export
       from test_run_report import _export as export
   ```

   `tests/test_provenance.py::_export` imports from `test_run_report`, which cannot
   import. So the 8 `TestTheBundleCarriesIt` / `TestOldBundlesStillLoad` failures are
   **not an independent cause** — they are cause 1 reaching a third file. Worth
   noting because `test_provenance.py` was added by `97886f3`, inside the A2 window,
   and would otherwise look like a second wave-10 regression.

**Cell coverage — 16 of 16.** Nothing in this mechanism is platform- or
version-dependent: a missing module fails collection identically on every runner.
This is the cause that produced the pattern the service evidence records for
`42a5c42`, and it is fatal at collection, so it **masks** cause 2 entirely.

**Timing — this is what splits the red period in two.** **EXECUTED**, PyPI's public
JSON index (no vendor API, no credentials, no model calls):

```
openai  3.0.0     2026-08-12T01:55:48.678603Z
openai  2.54.0    2026-08-11
openai  2.0.0     2025-09-30T17:35:54.695224Z
httpx2  2.10.0    2026-08-09T09:11:30.882434Z
```

`openai` 3.0.0 was released **2026-08-12T01:55:48Z**. The first red run was
2026-08-10T13:41Z — **36 hours earlier**. So cause 1 was **not live** for the first
five red runs, and **was** live for the last two (`7a39eda` at 03:06Z and `42a5c42`
at 13:34Z on 2026-08-12).

For completeness, the local environment holds `openai==1.106.0` (**EXECUTED**,
`pip freeze`), which still depends on `httpx` — which is exactly why the working tree
passes.

### 4.3 Reconstructed timeline

| Time (UTC) | Event | Cells failing |
| --- | --- | --- |
| 2026-08-10 12:43 | run on `f014e2f` — **last green** | 0 |
| 2026-08-10 12:58 | **`78cd401` committed** — cause 2 becomes live | — |
| 2026-08-10 13:41 → 21:54 | 5 red runs, `bef2c0b` … `8b5a972` (waves 10, 11) | 4 (Windows) — LIKELY |
| 2026-08-12 01:56 | **`openai` 3.0.0 released** — cause 1 becomes live | — |
| 2026-08-12 03:06 | run on `7a39eda` (wave 12a) | 16 — LIKELY |
| 2026-08-12 13:34 | run on `42a5c42` (wave 12) | **16 — ESTABLISHED** |

### 4.4 The candidates that are not causes

**(a) Real-Tk tests needing a display — RULED OUT.** **READ**,
`tests/test_view_smoke.py`: it launches real Tk in a subprocess and skips rather than
fails when there is no display —

```python
_root = tk.Tk()
… print("NO_DISPLAY:" + str(e))
…
if rc == 97 or "NO_DISPLAY:" in out:
    pytest.skip("no display: the real-Tk smoke is a ratchet, not a gate")
```

`tests/conftest.py` additionally stubs `tkinter` with a `MagicMock` so plugin modules
import headless. The workflow installs neither `python3-tk` nor `xvfb` (**READ**,
`.github/workflows/test.yml`) — and does not need to. Consistent with the 7 skips
observed locally and with the suite passing. As the brief noted, it could not have
explained the Windows cell in any case; that contradiction did not arise, because the
hypothesis fails on its own terms first.

**(d) Platform / path / encoding assumptions — RULED OUT for the window's new
tests.** **EXECUTED**: `grep -rnE "S:\\\\|/mnt/s|C:\\\\Users" tests/ --include=*.py`
→ no output, so no absolute-path fixtures anywhere in `tests/`. And every `open()` in
`tests/test_study_input_freeze.py` and `tests/test_provenance.py` passes an explicit
`encoding=` — the filtered grep for un-encoded `open(` in those two files returns
nothing. The one platform assumption that *does* exist is the line-ending one, and it
is cause 2 rather than a separate item.

**(e) Anything the log archive shows — UNDETERMINED.** `%TEMP%\ci_wave12_logs\` does
not exist (§0). No claim in this document rests on log text, and no candidate cause
was accepted or rejected on the strength of an inference about what a log would have
said. If the archive is later retrieved, the two predictions to check are: for
`42a5c42`, `ModuleNotFoundError: No module named 'httpx'` in every cell including
Windows; for `8b5a972` or earlier, three `test_study_input_freeze` byte-identity
failures in the Windows cells only and a clean pytest run in the twelve others.

### 4.5 Completeness

Together the two causes account for all 16 cells of `42a5c42`, and after both are
neutralised the fresh clone is clean but for the platform-specific three. Stated
plainly, so that nothing is smoothed over:

- **Cause 1 alone accounts for all 16 cells of the last two runs.** ESTABLISHED for
  `42a5c42` from per-cell service data plus local reproduction.
- **Cause 2 alone accounts for 4 of 16, on Windows only.** It cannot explain a
  16-cell failure and is not offered as doing so.
- **For the first five red runs I have no per-cell data at all.** The claim that they
  were 4-cell Windows failures is LIKELY — it follows from cause 2 being live and
  cause 1 not being live — but it is not established, and I have not represented it
  as established.
- **No third cause was found**, and the search for one was bounded by being unable to
  execute on Linux or macOS. The residual risk is a non-Windows-only failure that
  this Windows machine cannot see. The 1503-passing figure under `openai` 3.0.0 with
  the two uncollectable modules ignored is the best available evidence that no such
  cause is large.

---

## 6. A6 — process: nobody was watching

**Three wave wrap-ups (10, 11, 12) and two review passes completed while CI was red.**
The question the brief asks is whether anything in the process would have caught it.

**Nothing does. EXECUTED**, grep across `docs/internal/`, `tools/` and the top-level
markdown for `ci status|check ci|actions tab|is CI green|workflow run`: exactly one
hit, and it is not a check —

`README.md`, § on cross-platform support:

> Cross-platform compatibility is continuously verified by the GitHub Actions matrix
> on every push; see the [live CI status](…/actions/workflows/test.yml) for current
> run results.

That sentence is the only place CI status appears anywhere in the repository's prose,
and it points a **reader** at a page that has been red for two days while asserting
that compatibility is "continuously verified". It is a claim about the project that
the project's own CI currently falsifies.

**READ**, the eleven `docs/internal/FIX_WAVE_*.md` wrap-ups: none contains a CI check
in its gate or checklist. The only mentions of CI in `FIX_WAVE_12_FLAG_ONLY.md` are
about CI's *limits*:

> **3. A green CI is compatible with a broken GUI, and always has been.**

That paragraph reasons carefully about what a green CI fails to prove, while CI was
in fact red — and the wrap-up that contains it did not check. The wave-12 wrap-up
also cannot have been informed by CI, because the run for `7a39eda` had already
failed when it was written.

**This is a finding in its own right**, and arguably the most consequential one here:
both causes are individually trivial to fix, and the reason they persisted for seven
runs across three waves is that the session-complete statement gates on the local
suite and nothing else. A local suite on one platform, in one long-lived virtual
environment, is precisely blind to both of this outage's causes — one is
Windows-checkout-specific, the other is fresh-install-specific.

---

## 7. Fix options

**Nothing was fixed.** These are options with their risks, for a later wave. They are
in two independent groups, because the causes are independent; a complete repair
needs one from each.

### For cause 1 (the 16-cell, collection-fatal one)

**Option 1a — declare `httpx` as a dev dependency.** Add `httpx` to
`pyproject.toml::project.optional-dependencies.dev`.

- **VERIFIED BY EXECUTION.** With `openai` 3.0.0 installed and `httpx` restored, all
  three affected modules pass: `118 passed in 2.63s`. The full suite then reduces to
  cause 2 alone: `3 failed, 1597 passed, 7 skipped`.
- Touches `tests/golden/**`: **no**. Touches `.gitattributes`: **no**.
- **Risk: low.** It declares a dependency the tests already have, and honestly:
  `httpx` is a test-only need — the shipped code does not import it (§4.2 step 3).
  Note the mild oddity it institutionalises: the tests construct `httpx` objects and
  hand them to an `openai` 3.x that itself speaks `httpx2`. That works today
  (executed), but it is a coupling to `openai`'s internals that could break again at
  any major bump without any declared dependency changing.

**Option 1b — bound `openai`.** Change `openai>=1.40.0` to
`openai>=1.40.0,<3` (or `,<4` once the 3.x path is exercised).

- Touches `tests/golden/**`: **no**. Touches `.gitattributes`: **no**.
- **Risk: medium, and mostly about what it hides.** It restores green without
  admitting the undeclared dependency, so the same latent defect fires again at the
  next `openai` major. It also pins users to an older SDK for no application reason —
  the fresh-clone run shows `plugins/_common/llm_client.py` working fine under 3.0.0
  (1503 tests passed with only the two uncollectable modules excluded), so there is
  no evidence the application needs `openai < 3`.
- **1a and 1b are not alternatives.** 1a is the correct fix; 1b is the correct
  *policy* for a project whose F-15 register row already says eight of nine
  dependencies are unbounded. Doing both, and extending upper bounds to the other
  eight, is the option that actually closes F-15.

### For cause 2 (the 4-cell Windows one)

**Option 2a — extend the `binary` rule to cover `docs/data/*.csv`.**

- **TOUCHES `.gitattributes` — flagged as the brief requires.** Does **not** touch
  `tests/golden/**`.
- This is the mechanically correct fix: the blobs are LF, the test wants LF, and the
  only thing producing CRLF is a checkout conversion nobody wants on these files.
- **Risk: medium, with a migration trap.** Attribute changes apply on *checkout*, so
  existing clones keep their current bytes until `git add --renormalize .` or a hard
  re-checkout. On a Windows working tree that currently holds CRLF for these files, a
  bare `git pull` will not fix them and the test will keep failing locally with no
  visible cause. Whoever does this should verify with `git check-attr -a` afterwards,
  and should decide whether to write `docs/data/*.csv` (this directory only) or
  `docs/data/**/*.csv` (which would then subsume the existing `study_input` rule and
  invite the enumeration to rot differently). Given §4.1's latent finding, the
  version worth considering is one that covers the extension-less `SHA256SUMS`
  manifests too.

**Option 2b — normalise line endings inside the test rather than in git.** Compare
`published.read_bytes().replace(b"\r\n", b"\n")` against the regenerated bytes.

- Touches `tests/golden/**`: **no**. Touches `.gitattributes`: **no**.
- **Risk: high, and it is a scientific risk rather than a technical one.** The test
  exists to back a published claim in `docs/llm-evaluation.md` that a named command
  reproduces the artefacts **byte-for-byte**. Weakening the comparison to
  byte-for-byte-modulo-line-endings makes the test no longer verify the sentence it
  was written to defend. If this route is taken, the published claim must change in
  the same commit. I would not recommend it.

**Option 2c — make `tools/eval_ingest.py` consistent with itself.** Give
`write_summary_text` the same explicit-LF treatment as the three CSV writers
(`path.open("w", encoding="utf-8", newline="\n")`).

- Touches `tests/golden/**`: **no**. Touches `.gitattributes`: **no**.
- **This does not fix cause 2** — it fixes the *inconsistency* that made cause 2 hard
  to see, and it converts `eval_summary_v1.txt` from accidentally-passing-everywhere
  to failing on Windows alongside the CSVs. It is worth doing **together with 2a**,
  after which all four artefacts are LF-pinned on both sides and the module has one
  newline policy instead of two. On its own it makes things worse, and that is
  exactly why it is listed.

### For the process gap (§6)

Not a code fix and not costed here, but the cheapest candidate is that the
session-complete statement cannot be written without a recorded CI conclusion for the
HEAD being wrapped up. Worth noting that this outage is also an argument for one CI
cell that installs into a **clean** environment and one that tests a **fresh clone** —
the two conditions the local gate structurally cannot reproduce. The existing matrix
already does both; the gap is that nobody read its answer.

---

## Appendix A — golden listing, for wrap-up re-verification

`git ls-files -s tests/golden` at `42a5c42`:

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

## Appendix B — reproduction recipe

Scratch paths only; nothing was written inside the repository tree.

```bash
# 1. CI equivalent — reproduces the 16-cell failure
git clone https://github.com/lars-ulaval/metaScreener.git "$TEMP/ci_probe_w13"
cd "$TEMP/ci_probe_w13"
python -m venv .venv_ci
./.venv_ci/Scripts/python.exe -m pip install --upgrade pip
./.venv_ci/Scripts/python.exe -m pip install -e ".[dev]"
./.venv_ci/Scripts/python.exe -m pytest tests/ -q
#   => 2 errors during collection (ModuleNotFoundError: No module named 'httpx')

# 2. Isolate cause 2 by neutralising cause 1
./.venv_ci/Scripts/python.exe -m pip install httpx
./.venv_ci/Scripts/python.exe -m pytest tests/ -q --tb=no
#   => 3 failed, 1597 passed, 7 skipped

# 3. Confirm cause 2 is committed-state, not environmental
cd "$TEMP/ci_probe_w13" && python -m pytest tests/ -q --tb=no   # local env
#   => 3 failed, 1597 passed, 7 skipped   (same three)

# 4. Control: the working tree, local env
cd "S:/Alejandro_/projet julien (prisma-hub)/prisma-hub_v3_repo"
python -m pytest -q
#   => 1600 passed, 7 skipped
```

A caution for whoever repeats step 3 on a non-Windows machine: it will pass. Cause 2
is visible only where `core.eol` resolves to CRLF.
