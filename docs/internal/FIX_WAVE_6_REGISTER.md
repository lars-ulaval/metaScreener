# metaScreener — Wave 6: sweep the LLM-integration candidates into the register, and make the documentation tell the truth

Documentation only. No file under `metascreener/`, `plugins/`, `tests/`, `tools/`, no
`.spec`, no `pyproject.toml`, no `requirements.txt`, no `Dockerfile` and no CI workflow was
touched; nothing in this wave changes program behaviour. Where a fix I wanted to make
required code, it was recorded as a register row and left undone — F-124's test pin and
F-125's Dockerfile header are the two that bit.

Standing rules as before: branch `fix/wave-6-register` off `main` (@ `895e51c`), one logical
change per commit, suite green after every commit (baseline **422 passed, 4 skipped**), no
golden may move — a SHA-256 manifest of `tests/golden/` was recorded at step 0 and
re-verified at close-out alongside `git diff main...HEAD -- tests/golden/` — and **no push**:
the human pushes after coordinator review. `895e51c` was **not** pushed at wave start;
`origin/main` stood at `f952e69`, one commit behind.

Long-lived documents cite `path::symbol` or a section heading, never a line number. Wave 5
broke that rule twice and this wave repairs the instances it touched.

---

## Step-0 verification: what the register actually contained

Established read-only on `main` @ `895e51c` before branching. The coordinator's ledger was
right on every point:

- **82 rows**, F-01..F-85 with exactly F-56, F-57 and F-58 absent, no duplicate IDs. The
  register's own count line agreed.
- HEAD `895e51c`, tree clean, `origin/main` at `f952e69`.
- Suite **422 passed, 4 skipped**.

*Counting mechanics, since this repository has been wrong about the row count twice:* rows
begin `| **F-nn**`, with the ID bolded. A pattern matching `^| F-` returns **zero**, which is
the likeliest source of both errors. This is now written into the register itself.

**What the ledger did not say, and what turned out to matter more than the sweep.** Only
**17 of the 82 rows carry a closure annotation**, while `CHANGELOG.md` [Unreleased] records
closures for **29 more**. The `Fixed in <sha>` convention began in wave 3 and was applied
consistently only from wave 4; waves 0–2 closed their findings in the changelog and never
wrote back. So the register — the document whose entire purpose is to be the one place open
work is enumerated — understated its own progress by 29 rows, including all three Criticals.
Recorded as a closure ledger in the register rather than by editing 29 rows; see
*Disagreements*, item 3.

---

## Decisions of record

**D1. New IDs continue past the maximum, at F-86. F-56–F-58 are never backfilled.** The
wave-5 decision stands and is now written into the register so it stops costing a
verification cycle.

**D2. Register rows for wave 6 are denser than wave 4's.** F-67..F-82 had to absorb
`05_report_production.md`'s detail because that document's candidate list was terse. §B9 is
not terse — it carries the full analysis, and every new row names its `C-n`. The rows
therefore state the defect, the measured evidence, the consequence and the fix, and leave the
derivation where it already lives.

**D3. Coordinates are `path::symbol` throughout.** Wave 6 also de-lined the coordinates in
every row and passage it amended. This is not fastidiousness: `06_llm_integration.md`
§A11.4 measured that `metascreener/plugin_manager.py::_sanitize` strips the `from __future__`
line before compiling, so **runtime line numbers in `llm_client.py` and both `screen.py`
files are off by one from disk** — a line citation in this area is wrong even when it is
fresh. Three of the stale citations this wave found had rotted onto a progress callback and
two blank lines.

**D4. Annotate, never rewrite, in the point-in-time documents.** The set has an established
and unanimous house style — `02_quality.md`'s `*Addendum (wave 4a, F-76):*`,
`05_report_production.md`'s closing "corrected after the fact", the register's
`**Fixed in <sha>:**` — and in all three the superseded text survives verbatim. A wave that
edited the original sentences would have been the first departure. Applied to `02_quality.md`
and `05_report_production.md`. Not applied to the diagnostic `README.md`, for the reason in
*Part 3* below.

---

## The sweep

**Method.** All 42 candidates of the single deduplicated `C-n` namespace in
`06_llm_integration.md` § "B9 Candidate findings" against **all 82 rows**, not only against
the nine relationships the brief named. Each candidate was classified NEW / MERGE / SPLIT /
RETIRE, and each of the nine asserted relationships was verified against the register text
and against source rather than accepted. Two of the nine did not survive.

**Outcome: 38 candidates → 45 rows (F-86..F-130); 4 merged; 0 retired.** Six candidates
covered more than one defect and were split.

### The full table

| C-n | Sev | Outcome | Justification |
|---|---|---|---|
| C-1 | Crit | **F-86** NEW | Nothing in the register covers cross-batch answer substitution. The only row that can produce a fabricated exclusion. |
| C-2 | High | **F-87** NEW | Adjacent to F-33 (same artefact, opposite direction: F-33 is unreported corruption on read, C-2 is deliberate persistence of failures on write). |
| C-3 | High | **F-88** NEW | Graduates F-82 — verified, see *Merges*. |
| C-4 | High | **F-89** NEW | F-01's shape on the provider axis; F-01 is closed and its fix does not reach the endpoint. |
| C-5 | High | **F-90** NEW | No row covers response-vocabulary case handling. |
| C-6 | High | **F-91** NEW | The residual of F-08, not a duplicate: F-08 removed the key rule and left the endpoint barrier standing. |
| C-7 | High | **F-92** NEW | Adjacent to F-15 (unpinned floor) but distinct: the defect is reliance on an undeclared third-party default. |
| C-8 | High | **F-93** NEW | Same family as F-34 on three new triggers; F-34's shipped `_export_confirm_reason` keys solely on `NOT_SCREENED`, so none of them reach it. |
| C-9 | High | **F-94** NEW | No row covers error classification. |
| C-10 | High | **F-95** NEW | No row covers what task the published rates were measured on. |
| C-11 | High | **F-96** NEW | No row covers the study's model attribution. |
| C-12 | High | **F-97** NEW | No row pins the default model or the published figures. |
| C-13 | High | **F-98** NEW | Adjacent to F-28: F-28 is about the settings the goldens were captured at, C-13 about the two incompatible roles they serve. |
| C-14 | High | **F-99** NEW | The other half of the `.gitattributes` rule this report elsewhere calls load-bearing. |
| C-15 | High | **F-100** NEW | No row covers threshold injection into the prompt. |
| C-16 | High | **merged → F-12** | F-12's substance; its headline is stale and its mechanism wrong. |
| C-17 | Med | **F-101** NEW | The one place the post-F-01 key invariant does not hold. |
| C-18 | Med | **F-102** NEW | A residue of the class F-01 closed; F-01 is closed, so a new row. |
| C-19 | Med | **F-103** NEW | Adjacent to F-33, which is about the loader's silence, not the format's untestedness. |
| C-20 | Med→**High** | **F-104** NEW | Nothing in the register covers it. Severity raised — see *Severity*. |
| C-21 | Med | **merged → F-25** | Magnitude sharpening plus one telemetry defect the same fix closes. |
| C-22 | Med | **merged → F-63 + F-64** | The only candidate splitting across two existing rows. |
| C-23 | Med | **merged → F-22** | Refinement. Its criticism of F-22 is withdrawn — see *Disagreements*. |
| C-24 | Med | **F-105 + F-106** SPLIT | Two independent defects with two disjoint fixes, which C-24's own fix column already lists separately. Only the spec-test half is F-66's shape. |
| C-25 | Med | **F-107** NEW | No row covers the request's deliberate minimality. |
| C-26 | Med | **F-108** NEW | F-69's shape with the model as consumer; F-69 is closed and its fix does not reach a prompt. |
| C-27 | Med | **F-109** NEW | Root-cause row for F-64 and an enabler for F-65's proposed net; neither covers it. |
| C-28 | Med | **F-110** NEW | No row covers the product-versus-shape confusion. |
| C-29 | Med | **F-111 + F-112** SPLIT | A state-model gap and a Tk-thread-safety defect share a candidate but nothing else — different subsystem, different fix, different failure. |
| C-30 | Med | **F-113 + F-114** SPLIT | Coverage never enforced, and the suite having no network guard, are separate risks; the third item (plugin 02's dead `OPENAI_OK`) is pure hygiene and went to F-130. F-32 is the same class as F-113 on a different step, not a duplicate. |
| C-31 | Med | **F-115** NEW | Same files as F-81, different defect. |
| C-32 | Med | **F-116** NEW | No row covers settings persistence. |
| C-33 | Med | **F-117** NEW | Three small consistency gaps in one subsystem that one commit closes; adjacent to F-28 and F-65. |
| C-34 | Med | **F-118 + F-119** SPLIT | Its correctness half (a lost run gate, a checkbox read by nothing, a negative truncation that inverts which end of a field the model sees) is not the same finding as its string half. |
| C-35 | Med | **F-120** NEW | One layer below F-09/F-40 and invisible to the test that ought to see it. |
| C-36 | Med | **F-121** NEW | Same class as F-16 (closed) on a different document, and F-83 fixed the sample-availability half only. |
| C-37 | Med | **F-122** NEW | Adjacent to F-25; together with F-87 and F-94 they describe one under-defended response path. |
| C-38 | Low | **F-123 + F-124 + F-125** SPLIT | See *The two clusters*. |
| C-39 | Low | **F-126** NEW | Nothing in the register covers the figures. |
| C-40 | Low | **F-127** NEW | Nothing covers `.env` as a channel. |
| C-41 | Low | **F-128** NEW | Adjacent to F-15; the fact that it can never be added retroactively is the finding. |
| C-42 | Low | **F-129 + F-130** SPLIT | See *The two clusters*. |

---

## The merges, and the reasoning

**C-16 → F-12 — narrowed, not closed.** F-12's substance holds and its headline does not.
`tests/test_cancellation.py::TestLLMCancellationKeepsPaidResults` drives
`run_m1_llm_for_criterion` directly against a fake client, so batching, the batch loop, a
successful call, the parse loop and `return out` all execute. What has never run is every
branch that fires when a model or endpoint misbehaves, and the transport layer entirely.

Its evidence cell also stated the wrong **mechanism**, and the brief's framing of that error
is itself wrong in a way worth recording. The brief asks whether the golden test "unsets the
key, or does something else (a replay cache / monkeypatched client)". It **does** unset the
key — `tests/test_el_regression.py::_el_to_csv` pops `OPENAI_API_KEY` — and there is no
monkeypatched client anywhere in that module. The defective clause is the *causal* one, "the
golden tests deliberately short-circuit **before it**". Measured with the key deliberately
left set: zero client constructions, zero key checks, `cache_hits=85 | to_call=0`. The
operative gate is `if c.operator == "llm" and to_call:` — with a complete cache the function
is never entered and `_has_openai_key()` is never consulted. The unset key is a second line
of defence that has never been load-bearing. **Whoever restates F-12 must not write "the test
does not unset the key", because it does.**

No coverage percentage is quoted. Three mutually incompatible figures are in circulation
(21%, 32.6%, 53.0%) and the instrument may be reading the shifted line numbers of D3; §B9
Q10 leaves the choice open and F-113 proposes settling it with the `pytest-cov` CI already
installs and never invokes.

**C-21 → F-25 — a magnitude sharpening that is not only a magnitude sharpening.** The SDK
figures are confirmed from installed source: `DEFAULT_TIMEOUT = httpx.Timeout(timeout=600,
connect=5.0)` and `DEFAULT_MAX_RETRIES = 2`, so one call can spend 3 × 600 s. But C-21 also
carries a genuinely separate telemetry defect — every logged "batch failed" line
under-reports the request count threefold — and it silently drops F-25's `max_tokens` /
`finish_reason` half. **A merge that replaced F-25's text would have deleted a live defect.**
Both halves are preserved and the telemetry item folded in, because setting `max_retries`
explicitly fixes the log line as a side effect.

**C-22 → F-63 and F-64.** The span half is a straight duplicate of F-63 carrying new
evidence: 169/170 EL and 77/84 IL golden spans do not locate their quote, so the defect is
in the shipped fixtures rather than in one archived run — which, given F-98, means it is in
the published dataset. The `error` half extends F-64, whose proposed `uncertain_reason`
vocabulary has no member for "the call failed"; without one, the reason field would be
complete in form and incomplete in fact.

**C-23 → F-22.** NFKC is necessary and not sufficient, verified in Python: it leaves
U+200B/200C/200D, U+FEFF and U+00AD unchanged and does not fold case. The refinement lands.
Its accompanying criticism of F-22 does not — see *Disagreements*.

**C-3 graduates F-82 — verified, and the brief is right.** F-82's three fields are
`created_at` (naive local time), `created_by` (a plugin tag) and `derived_from.zip_name` (a
source-ZIP basename). Stamping all three into `_write_llm_stage_bundle` changes a post-IL
manifest from `screen_a_ih_plugin` to `screen_a_il_plugin` and nothing else. Corroborated
independently: that writer's `history.append({...})` writes seven keys and takes no `model`
parameter at all — the writer is never even *told* the model. F-82 gained an explicit scope
boundary so its closure cannot be read as closing F-88.

---

## The two clusters

The rule applied, in both directions: **split when the items have different owners, different
fix mechanisms, or different consequence classes; keep one row with an enumerated evidence
cell when one commit closes them all.**

**C-38 → three rows.** A single row hiding thirteen distinct false claims is exactly the
shape this project has already been bitten by — F-69 was two hand-maintained schemas
disagreeing inside one artefact, and nobody noticed for a release. But thirteen rows for
thirteen one-line documentation fixes is register noise that would have moved the Low count by
half. Three of the thirteen are not documentation slips at all:

- **F-123** — the four manifest-provenance claims. These have an *owner*: they are the
  documentation face of F-88, and they are the reason that absence went unnoticed, since four
  documents assert the provenance exists. They also carry the highest reviewer stakes in the
  cluster, because auditability is the property a peer reviewer will test.
- **F-124** — the test counts. Not a wrong sentence but a **recurrence of a closed finding**:
  F-17 was fixed by refreshing the number, and the refresh re-armed the trap. "The class
  re-armed itself after its own fix" is a different fact from "this sentence is wrong", and it
  is the fact that dictates the remedy (remove, do not refresh).
- **F-125** — the remaining ten, as one row with an enumerated evidence cell. They share one
  cause: documentation written against an intended design and never re-read against the code.
  One commit family closes them all.

**C-42 → two rows.** `secrets/README.md` is not a dead artefact; it is an **instruction that
fails**, and it fails where failure looks like something else — the user places their key
where the repository told them to, the application asks for a key anyway, and nothing says
why. Split as **F-129**. The other six are genuinely "delete or wire each", one commit,
one row (**F-130**), with plugin 02's dead `OPENAI_OK` flag from C-30 folded in.

---

## Severity

§B9's severities are the diagnostic author's assessment. Four were changed, against the
register's own definitions (*Critical* = incorrect scientific output, data loss, or security;
*High* = blocks maintenance or peer review) and its own calibration precedents — F-34 raised
Medium → High because a second route to it appeared, F-26 raised because the real impact was
evidential rather than economic, F-09 lowered because measurement contradicted the prediction.

- **C-20 → F-104, Medium → High.** The register's bar for High is met twice: an export
  silently destroys an accumulated bundle member that cost real money, **and**
  `_verify_sha256_map` structurally cannot detect it, because it iterates only members that
  are present — so the bundle asserts a digest for a file it no longer contains and reports
  itself intact. That is F-05's failure mode arriving through a different door. Held below
  Critical only because the loss is of a derived artefact a paid re-run regenerates, not of
  scientific records.
- **C-38's provenance items → F-123, Low → Medium.** A documentation claim that the manifest
  records the model, in a tool whose stated value is auditability, is not cosmetic.
- **C-38's count items → F-124, Low → Medium.** It defeats the documented
  installation-verification step — a user cannot distinguish a good install from a bad one —
  and the class has demonstrably recurred after being fixed.
- **C-34's string half → F-119, Medium → Low.** Nothing in it changes an output or a
  decision. The correctness half went to F-118, where the Medium belongs.

**C-4 was left at High** although its own row hedges "Medium today (a `.env` edit); High
under either destination". The hedge is defeated by the README: the `.env` edit in question is
the literal instruction its "Using local LLM providers" section gives, so the trigger is a
documented workflow, not an exotic act. Recorded rather than silently kept.

All other severities stand as filed. **C-15 was considered for Critical** — telling the model
the threshold and then treating its self-reported confidence as an independent gate is a
circularity that bears on published figures — and left at High, because it degrades the
*interpretation* of a result rather than producing a wrong one. **C-2 was considered for
Critical** and left at High because it fails closed: a cached failure is an `uncertain`,
which flags rather than excludes.

---

## Part 3 — the diagnostic README

**Approach: split by function, rather than choosing between rewriting and annotating.**

The set contains two kinds of document. `03_findings.md` is a live register, amended in place
by every wave. `00`–`02` and `04`–`06` are point-in-time analyses that are never rewritten.
The README was written as a point-in-time executive summary of `365325c` but *functions* as
the set's index — and an index must be live or it is simply wrong, while an analysis must not
be rewritten or the record is lost. Neither pure remedy satisfies both constraints the brief
imposes: a dated banner on a page whose every sentence is present indicative and whose top
section is three closed Criticals still misdirects; a rewrite destroys the record.

So the two functions were separated. Above the fold, everything that was **index** — the
document table, the metrics, the counts — is now live and correct, gaining rows for 04, 05
and 06, the register's real figures, a pointer to the closure ledger and the count-rows rule,
and the current highest-severity open finding (F-86), which a reader stopping at the executive
summary previously could not learn. Below it, under a heading that frames the rest as *what
the 2026-08-08 diagnostic found*, the original text stands **verbatim** — the heading converts
its present tense into reported speech — with a bracketed `Since 2026-08-08:` note at each
point a reader would otherwise be misled.

**Drift corrected beyond the four items the brief named:** stale file and Python-line counts
(121/22,175 → 149/27,571); an index row still describing the pre-wave-5 sample folder; the
166-test figure and every coverage percentage measured against it; the frozen-build
prediction, which was measured and wrong in its specifics; the "three documentation errors",
all fixed and one since recurred; the F-29 item, fixed by the first commit after the report
landed; and the Q1 item, resolved in wave 3 along with Q2 and Q3. **Every coverage percentage
is marked stale rather than re-measured** — a false-precision coverage table is worse than
none, and F-113 is the right way to settle it.

"What not to break" gained the one caveat wave 6 forces. Its claim that the evidence gate
survived an adversarial read is true *for malformed responses*; F-86 defeats it with a
well-formed one, naming another record, whose quote is genuine and validates. That is not a
hole the original read was looking for.

---

## Part 4 — what was corrected, and what was deferred

**Nothing was deferred, because there is nothing to defer to.**

The brief asks that anything a planned wave will make true be left alone, and flags the four
manifest model/prompt-version claims as the case to judge, on the premise that "a planned wave
adds exactly that". **There is no such wave.** The Tier 1 / Tier 2 provenance design lives in
§B8.1 of an explicitly read-only diagnostic and carries no `F-nn`; §B8.3 opens "Not a
recommendation to proceed. An ordering with reasons, on the assumption the work is done";
Part B opens "Assessment, not decision"; and the gating question is unresolved and listed
under open decisions (§B9 Q5 — does local-by-default ship before or after provenance is
recorded?). Deferring would have left a false provenance claim standing with no scheduled
repair, in the four documents a reviewer assessing reproducibility reads first. **Corrected
now**, with the register recording that they should be restored when F-88 lands.

The audit of what *is* scheduled: **F-79 (wave 4b) is the only written, unrun wave**, it is
gated on human observations HO-2/HO-3, and it owns two `docs/usage.md` edits — the
`;`-locale delimiter caveat and repointing readers at the XLSX workbook. Neither appears in
C-38. F-67's residual site is correctly deferred into F-79 and is the model deferral in this
tree. F-77, F-78, F-80, F-81 and F-82 are backlog; F-84 and F-85 parked; F-65 has a declared
"own wave" with no brief. Nothing else is scheduled.

**Corrected:** the four provenance claims (F-123); all four hard-coded test counts (F-124);
and ten of the eleven items of F-125 — seven cache passages across three files, the broken
`python -m metascreener` launch route, the `OPENAI_MODEL` table row, the FAQ's
"refuses to proceed", the pre-F-01 cache-key descriptions, `record_hash`, the API-call
magnitude, the CHANGELOG's phantom Docker path, and four stale gate citations.

**Left undone, and why:** the **Dockerfile header** claims an Ubuntu 24.04 base for
`FROM python:3.12-slim-bookworm` (Debian 12). The wave's own ground rules forbid touching the
Dockerfile, and `README.md` § "Testing" repeats the Ubuntu claim, so the two must move
together. Recorded inside F-125 as a named exclusion rather than silently skipped. Likewise
**pinning any of this with tests is code** — C-38's fix column proposes exactly that, and
`tests/test_metadata.py` already pins six documentation facts, so the pattern is a drop-in —
recorded as the fix in F-124, not performed.

The mandated item was done as mandated: `docs/installation.md`'s "162 passed, 1 xfailed" was
**removed, not refreshed**, because refreshing is what re-armed F-17's trap the first time.
Confirmed alongside it that **no `xfail` marker exists anywhere in the tree**, and that the
test the guide names as xfailed exists and passes.

---

## Where I disagree with the brief

The brief asked to be told where it is wrong. Nine items; the first three are material.

1. **"A planned wave adds exactly that."** It does not. See Part 4. This is the most
   consequential correction, because following the instruction would have preserved a false
   claim about provenance in four documents.

2. **"C-23 … F-22 implies `_normalize_space` mishandles the NBSP class when it does not.
   Correct that too."** There is nothing to correct. F-22's row reads, in full: *"The quote
   check is not Unicode-normalised or case-folded"*, evidence *"exact match, then
   whitespace-collapsed match only"*, impact naming *"mixed NFC/NFD or smart punctuation"*.
   It never mentions NBSP, whitespace classes or spaces. The code fact behind C-23's clause
   is true and is recorded in F-22's refinement; **the attribution is withdrawn**, in the
   register's sweep note. C-23's other claim — NFKC necessary and not sufficient — is
   confirmed by measurement and stands.

3. **"All three are closed … quote the closing evidence from the register."** There is no
   closing evidence in the register for any of F-01, F-02, F-03 or F-10. They are closed in
   the code and in `CHANGELOG.md`, and their rows were never annotated. This turned out to be
   a 29-row problem, not a 4-row one, and it defeats the wave's own stated purpose more
   thoroughly than anything the sweep found. Recorded as a closure ledger under the register.
   Annotating 29 rows individually was **deliberately not attempted here** — doing it while
   also sweeping 42 candidates into the same file would have made both changes unreviewable.
   It is the obvious next wave.

4. **"F-01..F-05 are a precedented instance of the same class."** Partly. The shared class is
   *closure recorded outside the register*, not *existence recorded outside it* — F-01..F-05
   have rows, F-56..F-58 do not, and a stale row is repairable by annotation where an absent
   row is a renumbering decision. Stated explicitly in the register so the precedent cannot be
   cited as licence to backfill. F-01..F-05 are also not distinctive: 29 rows share the
   property, and F-05 sits in two changelog subsections, so it is not a clean example.

5. **`05_report_production.md` "lists … and says …" — two items.** Two *topics*; **twelve
   passages**, and two of them contain neither phrase a reader would grep for (Stage 05 IH's
   bare word "conditional", and open question Q-D). A **third** stale topic is named nowhere
   in the brief or in §B9: `read_input_errors()` no longer returns `[]` on an unreadable file
   (F-68), which makes four further passages stale including the executive summary. Two traps
   are recorded in the annotation so a later verifier does not introduce a *new* error: §B.1's
   R3 row is still true of `_csv_read`, which is deliberately still lenient, and the
   coordinate `screen.py:148-154` still lands inside that lenient function.

6. **"the §6.4 key-derivation block."** The staleness is not confined to the code fence. The
   Invalidation-coverage table's criterion-wording row, the whole "criterion-content gap"
   paragraph, the sentence "which is presumably why it has not been done", and §6.5's
   "Cache stale-on-criterion-edit" row and Verdict all inherit it. Annotating only the fence
   would have left a self-contradicting section. `02_quality.md` was also given the
   commit-and-date pin it never had — the absence of which is *why* its assessments read as
   live claims at all.

7. **"C-24 … F-66's failure shape one layer down."** Only its second half is. C-24 covers two
   independent defects with two disjoint fixes — which its own fix column already lists
   separately — and was split rather than merged.

8. **"C-21 … a sharpening of F-25's magnitude, not a new defect."** Almost. It also carries a
   separate telemetry defect, and a merge written as the brief describes would have deleted
   F-25's `max_tokens` / `finish_reason` half.

9. **Two overstatements inside C-38** that would have been trivially refutable if copied into
   the register. The `OPENAI_MODEL` row is **not** "wrong in every column" — the Variable
   column is correct, since the variable is genuinely read at
   `plugins/01_reference_extractor/original/prisma_citations_ai_v3_1.py::DEFAULT_MODEL` and
   `.env` reaches it; it is wrong in Default and Purpose. And "three docs cite the evidence
   gate at a line that now holds a progress callback" is imprecise: **four** citations across
   three documents, at **two** coordinates, only one of which holds a callback — the other two
   are blank lines.

**Two typos in `06_llm_integration.md` itself, left as written but recorded here so they do
not propagate:** §A13.2 spells the variable `METESCREENER_CACHE_DIR` (METE-, not META-), and
§A7.1's citation-rot note cross-references **C-39** where it means **C-38**. The document is a
dated record and was not edited, consistent with D4.

---

## Plan of commits

1. `docs(register): sweep the LLM-integration candidates into the register` — rows
   F-86..F-130, counts updated.
2. `docs(register): amend F-12, F-22, F-25, F-63, F-64 with the merged candidates` — the four
   merges plus F-82's scope boundary.
3. `docs(register): record the wave-6 sweep, the C-n map, and two counting rules` — the sweep
   note, the cross-reference table, the closure ledger, the counting rule.
4. `docs(diagnostic): annotate the stale passages in 02_quality.md` — Part 2, items A–C, plus
   the missing commit pin.
5. `docs(diagnostic): annotate the stale passages in 05_report_production.md` — Part 2, items
   D–E, twelve passages plus the third topic.
6. `docs(diagnostic): bring the diagnostic README up to date` — Part 3.
7. `docs(F-124): remove the hard-coded test counts` — Part 4, mandated item.
8. `docs(F-123): stop claiming the manifest records the model and prompt version` — Part 4.
9. `docs(F-125): correct the false LLM-area claims in the user documentation` — Part 4.
10. `docs: wave-6 brief` — this file.

---

## On finishing

Report to the coordinator: every commit hash and subject; the final HEAD; the new register
row count and maximum ID; the `C-n` → `F-nn` table in full; the golden-hash re-verification
and the independent `git diff main...HEAD -- tests/golden/`; the before/after suite counts;
the three tool exit codes; confirmation that the branch diff touches only `.md` files; and
every point of disagreement above. Do not merge, tag or push.
