# metaScreener — Fix Wave 2: the Criticals

**Do not start this until Waves 0 and 1 are committed and the suite is green at
166 passed.**

Five findings: F-01, F-02, F-03 (all Critical), F-05 (High, integrity) and F-34
(High, escalated at the pre-wave-2 checkpoint). Each is a case where **the output
looks complete or correct but isn't** — the worst failure class for a screening
tool, and the one a reviewer is most likely to probe.

This wave will change golden files. That is expected and is the reason it gets
its own session.

## Ground rules

- One finding per commit, `fix(F-nn): <what>`.
- Test-first throughout. Each fix needs a test that reproduces the defect before
  you touch the fix.
- **Stop and report before regenerating any golden.** Do not regenerate as a
  reflex when a byte-identity test fails — a failing golden might mean your fix
  is wrong. The human decides.
- No API calls. Everything here is testable against stubs and cached fixtures.
- If any fix looks like it needs more than the register's effort estimate, stop
  and report.

---

## F-01 — the cache key omits criterion content

`plugins/_common/llm_client.py:397-414`. Key is
`prompt_version | model | cid | a_id | text_hash | trunc_chars` — only the
criterion *id*. But the prompt carries `type`, `operator`, `target`, `what`,
`label`, `threshold` (`plugins/06_el/screen.py:434-443` →
`prompt.py:42-51`). Edit `IC-1`'s wording, keep the id, re-run: every record
returns the previous criterion's answer, with evidence quotes produced against
text the model never saw this run. UI reports a normal `cache_hits=N`.

**Fix it structurally, not by adding a field.** Temperature and prompt version
were each added to this key in separate earlier commits — that's the third patch
to a hand-maintained list, which tells you enumeration is the bug. Derive the key
from a hash of the **fully-rendered prompt string** plus model and temperature.
Then anything that changes what the model sees changes the key automatically and
this class of defect cannot recur.

If the rendered prompt isn't reachable at the point the key is computed, say so
and propose the smallest restructuring that makes it reachable — don't fall back
to enumerating fields without flagging it.

Tests:
- Same criterion content under a different `cid` → different key (sanity).
- **Same `cid`, edited criterion text → different key.** This is the bug.
- Identical inputs → byte-identical key across processes (no dict-ordering or
  `hash()` leakage — use a stable serialisation).
- Temperature and model changes still change the key.

Then the goldens. `tests/golden/{el,il}_cache_v3.1.0.json` are keyed by the hash
you just changed, so byte-identity will fail by construction. **Stop here and
report** with: which golden tests fail, and confirmation that the regenerated
caches contain **identical decisions under different keys**. That equivalence
check is the entire safety net — a re-capture that silently changes a decision is
exactly what the goldens exist to catch.

Note the re-capture in `CHANGELOG.md` under `[Unreleased]`.

Related, worth flagging while you're here: **F-28** — the goldens were captured at
`TRUNC_CHARS=4000, BATCH_SIZE=5` against plugin defaults of `1500, 50`
(`tools/capture_el_il_goldens.py:68-70` vs `plugins/06_el/plugin.py:38-39`). If
you're regenerating anyway, capturing at the defaults instead would close F-28 in
the same motion. Propose it; don't do it unilaterally — it may be connected to
open question Q1.

---

## F-02 — cancellation silently truncates

`plugins/_common/runner.py:101,119`; `plugins/06_el/screen.py:430,511`;
`plugins/07_il/screen.py:432,513`. `if cancel_event.is_set(): break` exits the row
loop mid-corpus and returns partial results as though complete. An exported
bundle from a cancelled run is indistinguishable from a complete run over a
smaller corpus.

Return a `cancelled: bool` alongside results. Then either refuse export or stamp
`manifest.pipeline.history[].cancelled = true` and label the reports. **Prefer
refusing export**, or at minimum make it a deliberate confirmation — a partial
bundle that merely *says* it's partial in a manifest field will be missed.

Also fix **F-26** here (`plugins/_common/llm_client.py:172-176,206,231`):
`_check_cancel()` raises and unwinds past `return out`, discarding LLM results
already paid for. Catch at the batch loop and return partial `out`. Same code
path, same commit is fine.

Test: cancel mid-corpus, assert the flag propagates to the bundle and export
behaves as designed.

---

## F-03 — `input_errors.csv` has three schemas and gets deleted

The record of which citations were dropped as malformed is itself dropped.

- Harmoniser writes `record_number,reason,observed_len,expected_len,raw`
  (`plugins/03_harmoniser/exporters.py:160-166`)
- EH/IH write `record_index_ex_header,reason,raw_record`
  (`plugins/_common/exporters.py:45`)
- EL/IL write `reason,row_json` (`plugins/06_el/ui.py:1053`)
- The only reader expects the second (`plugins/_common/parser.py:318-338`) and
  returns `[]` for the Harmoniser's version — verified in the diagnostic
- `plugins/06_el/ui.py:1003` puts the file in the copy-forward skip set, so EL
  **removes it from the bundle** unless EL itself skipped rows

Pick one schema — the Harmoniser's is the richest, so widen rather than narrow.
Put a single writer in `_common`. Make every stage **append**, never overwrite.
Add a round-trip test: write from each stage, read back, assert every dropped
record survives all four hops with its provenance intact.

Check whether `plugins/04_eh/ui.py:460` ("Imported previous input_errors: … (0
rows)") starts reporting truthfully once this lands.

---

## F-05 — EL/IL never refresh SHA-256

The string `sha` appears **zero** times in `06_el/ui.py`, `07_il/ui.py`, and both
`standalone.py` — yet both stages overwrite `data/current.csv`
(`plugins/06_el/ui.py:1028`). So the bundle leaving EL carries a manifest digest
that no longer matches the file it names. The manifest actively asserts something
false, and nothing downstream checks.

Route EL/IL export through the shared writer in `plugins/_common/bundle.py:208-215`
that already refreshes `sha256`. Add load-time verification so a mismatch is
surfaced rather than ignored.

Test: export from EL, verify manifest digests match file contents; tamper with
`current.csv` and assert the next stage refuses or warns.

The README wording was already softened in Wave 0 — check whether the original
claim can now be restored honestly.

---

## F-34 — a stage with zero enabled criteria reports success

`plugins/_common/runner.py:99-115` (EH/IH); `plugins/06_el/screen.py:386-404`;
`plugins/07_il/screen.py:388-406`. When a stage ends up with no enabled criteria
it does not fail, warn loudly, or stop. It assigns **`PASS_CLEAN`** to every
record and reports every record as a survivor. Measured on a bundle built from
`tests/golden/criteria_harmonized_v3.1.0.csv` with the EL criteria removed:
counts `{'OUT': 0, 'PASS_CLEAN': 85, 'PASS_FLAGGED': 0}`, survivors 85 of 85.

`PASS_CLEAN` is the *stronger* of the two survivor labels — it means "every
criterion was met", which is precisely what did not happen. A stage that did no
work is indistinguishable from one that ran correctly and excluded nothing, and
reports itself using the label that most strongly asserts the opposite.

Raised Medium → High because **F-04 (fixed in wave 1, `f925625` and `906423a`)
opened a second and more likely route in.** A criterion whose `type` cell is
blank or unrecognised is now rejected rather than run with a guessed polarity —
correct in isolation, since guessing could invert a decision, but it means one
malformed cell can empty a stage. On the demonstration corpus EL runs on a single
criterion after `EC-3`, so blanking one cell takes EL from a *wrong* answer to
*no* answer that looks like a right one. The second failure is harder to notice.

A no-op stage must be visibly distinct from one that screened everything and
excluded nothing. Four requirements, all of them:

1. **Do not use `PASS_CLEAN`.** Add a distinct outcome — `NOT_SCREENED`
   suggested — counted in its own bucket, folded into neither survivor category.
2. **The run summary must say so.** The counts label and survivors tab are what
   the user reads after a run and they currently assert success. The label has to
   reach both.
3. **Gate the run or the export.** Either refuse to start (modal: no criteria,
   why, what to fix) or require explicit acknowledgement before export.
4. **Record it in the manifest**, in `manifest.pipeline.history[]` alongside the
   existing counts, so a reviewer reproducing the pipeline can tell a stage was a
   no-op without re-running the GUI.

The existing warning is **not** sufficient, and don't be tempted to treat it as
such. It is emitted at `plugins/_common/parser.py:373` and
`plugins/06_el/screen.py:323` / `plugins/07_il/screen.py:325`, and does reach the
GUI via `CriteriaLoadReport.warnings` (`plugins/06_el/ui.py:541-543`,
`plugins/07_il/ui.py:759-761`). But it is an 8-line read-only `tk.Text` in the
left pane (`plugins/06_el/ui.py:386-391`, `plugins/07_il/ui.py:603-608`) that
gates nothing; **the run summary actively contradicts it** — when two parts of
one screen disagree, the part that looks like a result wins; and it does not
survive into the exported bundle at all.

Notes:
- Fix all four stages together. EH/IH share `runner.py`; EL/IL are twinned copies
  (F-14), so the same change lands in two near-identical places.
- `OUTCOMES` is per-stage (`plugins/06_el/screen.py:66` →
  `("OUT", "PASS_CLEAN", "PASS_FLAGGED")`; `plugins/07_il/screen.py:68` →
  `("OUT", "PASS_CLEAN", "REVIEW")`, plus the EH/IH equivalents). The new literal
  has to be added to each — note IL uses `REVIEW` where EL uses `PASS_FLAGGED`.
- **Goldens should not move.** No committed golden exercises a zero-criteria
  stage, so the new branch is unreachable from them. Confirm that rather than
  assume it — if a golden changes, the new literal has leaked into the normal
  path.

Test: build a bundle with a stage's criteria removed, assert the outcome is
`NOT_SCREENED` rather than `PASS_CLEAN`, that it is not counted as a survivor,
that it reaches the manifest, and that export is gated.

Related, out of scope here: F-04 (the route in) and F-27 (a bundle's manifest
carries two divergent stage maps).

**Effort: S.**

---

## On finishing

Report: commits, suite result, the golden equivalence evidence for F-01, and
anything that turned out differently from the register's description. Then stop —
Wave 3 (the PyInstaller build experiment) is a separate session.
