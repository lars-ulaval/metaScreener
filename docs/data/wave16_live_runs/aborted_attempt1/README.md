# arm0_baseline — ABORTED FIRST ATTEMPT (wave 16b, 2026-08-15)

These are the artifacts of the **first** live attempt at `arm0_baseline`, which
stopped on a named anomaly before the arm completed. **Nothing here is deleted
and nothing here is evidence for the experiment** — the completed rerun lives
one directory up. This attempt is kept because its 15 calls were really spent
and because the diagnostic in `docs/internal/FIX_WAVE_16B_LIVE_RUNS.md` §1
reads from these bytes.

## Why it stopped

The arm was declared **15 calls** — the no-re-ask ceiling arithmetic
(EL `ceil(22/5)×2 = 10`, IL `ceil(22/5)×1 = 5`). The IL stage needed a
**16th** call: one of IL's first four batches came back missing at least one
requested `a_id`, so the engine issued its single permitted re-ask
(`plugins/_common/llm_client.py:1734-1743`, F-197) — and that re-ask consumed
the call IL's fifth and last batch needed.

The budget enforcer refused attempt 16. It increments then asserts **before**
delegating to the real client, so **no 16th network call was made**: 15 calls
were spent, exactly the declaration. The refusal surfaced inside the engine's
own generic batch handler (`llm_client.py:1809`), was classified `unknown`,
was not salvageable, and ended batch 5 as a failed batch.

The declared budget was computed with the no-re-ask formula while the rules
required re-asks to fit inside it. That is the coordinator's stated error, not
a harness defect: the enforcer behaved exactly as designed.

## What the 15 calls bought (still valid as measurement)

- **EL — complete and clean.** 10 calls, 44/44 pairs answered, `reasks_made: 0`,
  `OUT: 0`, PASS_CLEAN 21 / PASS_FLAGGED 1.
- **IL — complete except two records.** 6 attempts (5 batches + 1 re-ask, the
  6th refused), 20/22 answered, `OUT: 0`, 10 absence-suppressed verdicts all
  correctly review-routed (`EXCLUSION_SUPPRESSED: 10`), `REVIEW: 2`.
- **A612 and A622 were never sent** — they were batch 5. They carry
  `used: false`, `decision: uncertain`, `confidence: 0.0` and are counted
  `failed: 2` (not `no_answer`, which stays 0 and is correct: `no_answer`
  means "sent and the model said nothing").

## Files

| file | what |
|---|---|
| `arm0_baseline_{EL,IL}_FULL.csv` | the stage tables as produced |
| `arm0_baseline_{EL,IL}_report.json` | the engine's run reports verbatim |
| `arm0_baseline_{EL,IL}_summary.json` | 15e-shaped summaries |
| `arm0_baseline_{EL,IL}_log.txt` | stage logs (IL's carries the refusal line) |
| `arm0_baseline_live_manifest.json` | preflight facts, per-stage accounting, the anomaly stop |
| `arm0_baseline_console.log` | the detached run's console output, including the live preflight block |

The 20 records this attempt and the rerun both answered are used, once, as a
free same-configuration noise pair (§ the wave document). That comparison reads
these bytes; it never alters either run.
