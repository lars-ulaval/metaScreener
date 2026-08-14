# tests/golden — what these fixtures are, and what they deliberately contain

These nine files characterise **metaScreener 3.1.0 as it shipped, defects
included**. That is their job: the byte-identity regression tests replay
them to prove the current code still reproduces the shipped behaviour
wherever it has not been deliberately changed, and the re-key proof
(`tests/test_golden_rekey.py`) shows the two cache files' *values* have
never moved through either approved migration.

Because they characterise the release rather than the ideal,
`criteria_harmonized_v3.1.0.csv` carries the **pre-13d harmonisation
defects recorded as F-168**: `EC-4 equals doc_type conference` where the
prose names the venue, and `EC-1 equals lang French` where the prose names
French or Spanish. The fixture chain reproduces the shipped funnel
`776 -> 125 -> 651 -> 566 -> 85`, which register row **F-168** establishes
is reproducible and *not the screening the criteria prose describes*; the
current-rules chain (`776 -> 16 -> 760 -> 613 -> 147`) and its evidence
live under `docs/data/wave14c_batch_runs/` and
`docs/data/wave14d_invariance_runs/`.

**Do not "fix" these fixtures.** Correcting a golden is a re-capture — an
argued, maintainer-approved event that moves every digest and must land
with its own proof, as the two approved golden-tree changes so far did
(the wave-14c cache re-key; and this README's own addition, which was an
argued golden-tree change at wave 15a — if you are here because a tree
hash comparison flagged `tests/golden`, this file is the explanation).

The directory is covered by `tests/golden/** binary` in `.gitattributes`,
this file included: its bytes are LF and are not rewritten at checkout.
