# Rescued live-run harnesses (waves 15d, 15e)

These two scripts are **verbatim rescue copies** of the ad-hoc headless harnesses
that produced the wave-15d and wave-15e live acceptance evidence. Until wave 16a
they existed only in Claude session scratchpads under
`%LOCALAPPDATA%\Temp\claude\S--Alejandro--projet-julien--prisma-hub--prisma-hub-v3-repo\`
— an uncommitted temp location that would have been unrecoverable on cleanup
(flagged in `docs/internal/RECON_WAVE_16.md` §3a and §6c). They are committed
here as **provenance records, not maintained tools**: nothing imports them, the
suite does not run them, and future experiment work should use
`tools/run_criteria_experiment.py` (wave 16a), which generalizes their patterns.

## Files and provenance

| file | produced | rescued from (session scratchpad) | sha256 at rescue |
|---|---|---|---|
| `acceptance_harness_15e.py` | the wave-15e 414-call acceptance runs J/K/L (2026-08-15), frozen in `docs/data/wave15e_acceptance_runs/` | `…\d23aa140-1f9c-4d66-a09c-0de9162022b8\scratchpad\acceptance_harness_15e.py` | `6cbbf72cba9e7b951fcee7fe49fcc047034886a20f9d01140bd4695675b1d19b` |
| `acceptance15d_live.py` | the wave-15d harmoniser LLM-refine acceptance (2026-08-14, BUDGET=12), recorded in `docs/internal/FIX_WAVE_15D_HARMONISER_LLM.md` §"acceptance run, recorded" | `…\dc7b3901-b084-4964-b068-43679d91fe72\scratchpad\acceptance15d_live.py` | `67e3a3c2aba1902e496ec18464bfb498f095242d0ca0dc80e09c845c23919c50` |

Both temp-dir originals still existed at rescue time (2026-08-15, wave 16a);
the rescue copies were made with a byte-for-byte file copy and the digests
above were computed identically on source and copy before committing.

## Why we know `acceptance_harness_15e.py` is the exact producer

Its output directory (`…\d23aa140-…\scratchpad\wave15e_runs\`) still contains
the run artifacts, and their digests are **byte-identical** to the committed
freeze (`docs/data/wave15e_acceptance_runs/SHA256SUMS`), re-verified during the
wave-16 recon and again at rescue:

```
435bd7745fb498efb3b39e1489f3ea5858a600c31402d2763fbeeb37b1a69499  runJ_batch5_EL_FULL.csv
7b7fab2c39b47bc41dd1016291a21c4d233df2d76b366ebb090e4a690a73a3a5  runL_batch1_report.json
```

(scratchpad output = committed SHA256SUMS, both files.) The wave-15e meta
(`docs/data/wave15e_acceptance_runs/wave15e_acceptance_runs.meta.txt`) describes
this harness's preflight and call accounting without naming the file; this
rescue closes that gap.

For `acceptance15d_live.py` no committed artifact exists to digest-match (the
15d record is the wave doc itself); its identification rests on
`FIX_WAVE_15D_HARMONISER_LLM.md:277-284` ("the harness was rebuilt
conftest-free …") matching the script's structure — endpoint assert before any
call, `BUDGET = 12` client wrapper, twice-run `_llm_refine`, headless
`export_screen_a_bundle`.

## Patterns worth reusing (and where they went)

- **Preflight-assert before any call** (endpoint, policy, prompt version,
  corpus/criteria digests; REFUSING on mismatch) — `acceptance_harness_15e.py`;
  generalized into `tools/run_criteria_experiment.py --live` preflight.
- **Hard call-budget enforcer wrapping the client** — `acceptance15d_live.py`;
  same destination.
- **Digest-verify bundle/corpus/criteria in memory before spending a call** —
  `acceptance_harness_15e.py`.
