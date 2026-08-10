# Fix wave 9 — the endpoint enters the cache key

Branch `fix/wave-9-endpoint-key`, from `main` @ `f40af5f` (tagged
`post-wave-8`). Four commits, four findings closed: **F-92**, **F-139**,
**F-89** (High) and the **F-142** audit question.

The first wave since wave 2 to move a committed golden, run under wave 2's
discipline — with the one obligation wave 2 skipped discharged here.

---

## 0. Gate

| Check | Expected | Found |
|---|---|---|
| HEAD | wave-8 merge | `f40af5f` ✔ |
| branch | `main` | `main` ✔ |
| tag at HEAD | `post-wave-8` | `post-wave-8` ✔ |
| `git status --porcelain` | clean | clean ✔ |
| origin sync | 0/0 | `0  0` ✔ |
| suite baseline | 695 passed, 4 skipped | **695 passed, 4 skipped** ✔ |

No gap commits to classify.

### Golden manifest at `f40af5f` (SHA-256, first 32 hex)

| File | Digest | Moved this wave? |
|---|---|---|
| `criteria_harmonized_v3.1.0.csv` | `A01CCC73056A987C5459DA9C9EC373E0` | no |
| `eh_filtered_v3.1.0.csv` | `9B1EB10D85DBED2D30C1BBE8CD89D29B` | no |
| `el_cache_v3.1.0.json` | `A7009F0BCD968D58C330B56024AEA0DB` | **YES** |
| `el_filtered_v3.1.0.csv` | `604CB2F51BE7FB06D003CEC86EA69E9D` | no |
| `el_input_v3.1.0.csv` | `AF029F8D64FAD71B6B58DE338207F789` | no |
| `ih_filtered_v3.1.0.csv` | `D0B559F8251A592D886B1B367EA0D9C0` | no |
| `il_cache_v3.1.0.json` | `F29CDBAABEF7889655BFF864F15FE055` | **YES** |
| `il_filtered_v3.1.0.csv` | `088CCA9DB4220729D6BC7BCC4D356B9D` | no |
| `il_input_v3.1.0.csv` | `C4C5D7397EC6EDB172A27CCFCDEF3020` | no |

Post-wave digests and the reason for each are in §5.

---

## 1. Disagreements with the wave prompt

Stated before any code was written, as required.

**1. The register schedules F-135 for wave 9; this wave's scope excludes
it.** `03_findings.md:161` says of F-135 *"**Scheduled for wave 9**,
alongside F-88's tier 1: both write into the same records, and doing them
in separate waves would touch every evidence writer twice and move the
same goldens twice."* The legend at `:246` repeats it: *"`(scheduled)` — a
named future wave owns it: **F-79** (wave 4b), **F-135** and **F-142**
(wave 9)."* The wave-9 prompt names only F-89, F-92, F-139 and F-142.

I followed the prompt and did **not** do F-135. The prompt is the
maintainer's live instruction and the register's cell is a plan recorded
in wave 8. But the register's stated *reason* for pairing them is now
materially weaker in one direction and stronger in another, and both are
worth recording:

* *Weaker*: the fear was moving the same goldens twice. This wave has
  already moved them. A later F-135 would move them a **third** time, not
  a second.
* *Stronger*: F-135 adds a field to the evidence record and hence to the
  cache **value**. That is not a re-key — it changes values — and §B4.6 is
  explicit that a field can be added offline **only if its value for the
  archived run is known**. A call fingerprint for the archived run is
  **not** known, so F-135 over the existing goldens is in the same class
  as F-128's SDK version: it cannot be added retroactively, and doing it
  requires a genuine re-capture with a live key.

That is a harder constraint than "touch the writers twice", and it did not
change by being deferred. **The register rows for F-135 and F-88 should
say so.** Recorded in §7 as an amendment.

**2. F-98 says to freeze the study's input *before* any golden-touching
wave, and it is still open.** `03_findings.md:124`: *"Freeze a copy of the
two filtered CSVs under `docs/data/` as the study's immutable input, and
let the goldens move independently. **Do this before any golden-touching
wave**, since it is the cheapest of the set and unblocks the rest."* F-98
is not in this wave's scope and I did not do it.

The exposure this wave actually created is **nil**, and that is measured
rather than argued: F-98's hazard is that a golden-touching wave rewrites
`{el,il}_filtered_v3.1.0.csv`, the published study's data source. This
wave left both **byte-identical** (§5). So the wave passed through F-98's
blast radius without touching it. The advice remains correct for the next
wave that moves a decision file — which a re-capture would.

**3. The prompt's framing of the one-way door is right but incomplete, and
the gap matters.** It names two candidates: hashing an ABSENT `base_url`
as `""`, and hashing "the SDK's RESOLVED default". §B4.5 measured exactly
those two and found them disjoint. But the diagnostic never records what
the SDK's resolved value *is at runtime* — §B4.2 and C-7 both name
`str(client.base_url)` without ever printing it. **Measured here:**

```
openai 1.106.0
OPENAI_BASE_URL unset  -> str(client.base_url) == 'https://api.openai.com/v1/'
base_url='https://api.openai.com/v1' -> str(client.base_url) == 'https://api.openai.com/v1/'
```

httpx appends a trailing slash. So `str(client.base_url)` is a **third**
candidate value, disjoint from both of §B4.5's, and "hash the SDK's
resolved default" is ambiguous between two different key sets. §3 settles
it explicitly.

---

## 2. The register rows, restated

**F-89** (High, correctness/reproducibility) — the key hashes
`{prompt_version, model, temperature, prompt}`; `base_url` appears nowhere
and no repository code reads `OPENAI_BASE_URL` at all, so one model name
across two providers is one cache. F-01's failure shape on the provider
axis. Fix: hash the effective endpoint; one-way door per §B4.5; invalidates
every golden key; sequence with F-98. Size S + full golden re-key.

**F-92** (High, architecture/testing) — the local-provider capability rests
on the vendor SDK's `OPENAI_BASE_URL` fallback. `openai` pinned only
`>=1.40.0`; **not established** whether the floor has the fallback; no test
asserts the resolved endpoint. Fix: read it explicitly, pass `base_url=`,
log once per run, add to `.env.example`, one test on `str(client.base_url)`.
Size XS.

**F-139** (High, correctness/data loss) — `_save_env_key` replaces the whole
`.env` with one line when the read fails. Fix: distinguish absent from
unreadable, refuse the second, surface it; the `except` around the write
also makes a failed persist indistinguishable from a success. Size XS.

**F-142** (High, correctness/provenance) — a cache entry poisoned before
`3f37f17` is still served after it under a legitimate key. Sequencing note:
F-89 is an *incidental* remedy, so if F-89 lands first this row reduces to
the audit question. Scheduled for wave 9. Size S.

No fix cell disagrees with the prompt. The two register-level disagreements
are in §1.

---

## 3. The decision: absent is hashed as the resolved default

**Decided: the endpoint is hashed VERBATIM, and an absent
`OPENAI_BASE_URL` is hashed as the repository's resolved default
`https://api.openai.com/v1` — not as `""`, and not as
`str(client.base_url)`.**

This is a one-way door: §B4.5 measured absent-as-`""` and the resolved
default to give **disjoint** key sets, so changing one's mind later costs a
second re-key. The argument, in full.

### Why the resolved default rather than `""`

Because `""` and the default describe the **same configuration**, and
giving them different keys is a false discrimination with a real cost.

A user who leaves `OPENAI_BASE_URL` unset and a user who writes
`OPENAI_BASE_URL=https://api.openai.com/v1` into `.env` are talking to the
same server and will get the same answers. Under absent-as-`""` those two
runs occupy different cache namespaces, so a no-op edit to `.env` — adding
the line the `.env.example` this wave ships now invites them to add —
throws away every cached answer and charges a full re-run for nothing. The
resolved form collapses them, which is correct.

The reverse error does not exist: no two *different* endpoints resolve to
the same string, so nothing is merged that should be separate.

`resolve_openai_base_url` also folds blank to the default, for the same
reason: `OPENAI_BASE_URL=` and `OPENAI_BASE_URL="  "` are ways of saying
"unset", and must not become a third namespace.

### Why not `str(client.base_url)`

Because it is httpx's string, not ours. It carries a trailing slash the
SDK's own constructor literal does not, and it is the product of a vendor
normaliser that can change without notice. Hashing it would mean a vendor
formatting change silently re-keys every cache in existence — precisely the
class of dependency F-92 exists to remove. Hashing the repository's own
resolved string keeps the key set equal to the one §B4.5 measured, and
keeps the SDK out of the key entirely.

Note the pleasing consequence of doing F-92 first: once `base_url=` is
passed explicitly, the SDK never resolves anything, so "the SDK's resolved
default" stops being a value that exists in this program at all. The
one-way door is between `""` and *our* default.

### Why verbatim rather than a digest or a coarse label

Neither value in play is sensitive. §B8.1 states the tension exactly: *"an
unsalted hash of a short internal hostname is dictionary-guessable, so it
is a discriminator and not a secret; a per-bundle salt makes it a secret
and destroys the cross-bundle comparability that was the reason to record
it. Discriminator or secret — the design cannot have both."* A digest buys
privacy it cannot deliver and costs comparability. A coarse "local vs
remote" label cannot separate two local servers on different ports, which
is the comparison the maintainer expects to run.

### The cost of verbatim, stated so it is not later rediscovered as a bug

`http://host/v1` and `http://host/v1/` route identically and key
differently. So do `localhost` and `127.0.0.1`. This is
**over-discrimination**, and it is the safe direction: it costs a redundant
re-run, whereas under-discrimination costs a wrong answer, which is F-89
itself. Recorded in `_cache_key`'s docstring.

### Where the value is read — §B9 Q2, and why neither option was taken

Q2 asks whether the endpoint is read from `os.environ` at keying time or
threaded from the constructed client. **Neither.** The stage engine
resolves it **once per run** via `resolve_openai_base_url`, and threads it
into `_cache_key` as a **required** parameter.

* Not an env read inside `_cache_key`: Q2's own objection is decisive —
  it makes golden byte-identity environment-dependent, and neither
  `test_key_stable_across_processes` (it copies `os.environ` wholesale)
  nor CI can detect that. The failure mode is "16 green CI cells and a red
  suite on the machine of the person developing the feature."
* Not threaded from the client: the client is built inside
  `run_m1_llm_for_criterion`, per criterion, and its `base_url` is httpx's
  normalised object — see above.
* Required, not defaulted: a default would let a future call site omit it
  and reintroduce F-89 for that path with the suite green, which is how the
  pre-F-01 enumerated key accreted its omissions.

Key and client cannot disagree because both read the same function, and the
engine resolves once so a mid-run environment change cannot split a run's
namespace.

---

## 4. What changed, per finding

### F-92 — `3703abd`

`plugins/_common/llm_client.py::resolve_openai_base_url` is the single
place the endpoint is decided; `::DEFAULT_OPENAI_BASE_URL` and
`::OPENAI_BASE_URL_ENV` name its inputs. `::_openai_client_for` passes
`base_url=` explicitly. `plugins/06_el/screen.py::run_el_screen` and
`plugins/07_il/screen.py::run_il_screen` resolve once per run and log it.
`.env.example` gains the variable with the Ollama and llama.cpp recipes.

**Before/after:** `tests/test_endpoint_routing.py` — **10 failed, 3 passed
→ 13 passed**.

The before-state is the finding in miniature. The three that *passed*
before the fix include `test_local_endpoint_reaches_the_resolved_client`:
the behaviour was already correct, because the SDK's fallback was doing the
work. The one that *failed* is
`test_client_is_constructed_with_an_explicit_base_url`, which asserts the
keyword reached the constructor. **That asymmetry is F-92**: asserting only
`str(client.base_url)` passes in exactly the state the finding objects to,
so the decisive assertion had to be about who supplied the value.

`_openai_client_for` stays zero-argument: twelve test doubles across the
suite monkeypatch it as `lambda: client`, and a parameter would break all
twelve for no gain.

**The open question — does `openai==1.40.0` have the fallback? — CANNOT BE
SETTLED OFFLINE, and is left open.** Nothing was installed. Searched: a
filesystem walk of `C:\Users\alere` and `S:\Alejandro_`, plus a zip-magic
scan of all 2317 files in the pip cache. Every `openai` on this machine:

| Version | Fallback present |
|---|---|
| 1.104.2, 1.106.0, 1.107.0, 1.109.1 | yes |
| 2.7.1, 2.28.0, 2.53.0 | yes |

The lowest artefact anywhere is **1.104.2 — 64 minor releases above the
declared floor**. The wheels ship no changelog and the repo has no lockfile,
so nothing on disk dates the fallback's introduction. The fallback is
continuously present across 1.104.2 → 2.53.0 and survived the 1.x→2.x major
boundary, so it is not a recent addition — but that is not an answer about
1.40.0. `[not established]` stands; F-15 still owns the unpinned floor.

**This commit makes the question moot for this project**: once `base_url=`
is passed, the SDK's fallback is unreachable here whatever version resolves.

### F-139 — `37dd61c`

Reproduced at `f40af5f`, verbatim: a `.env` holding a cp1252 comment,
`OPENAI_BASE_URL`, `SCREENA_EL_MODEL` and `OPENAI_API_KEY` became
`OPENAI_API_KEY=sk-new\r\n` **alone**, and the function returned `None`.

`metascreener/main.py::_save_env_key` now: refuses to write when the read
raised, leaving the file byte-for-byte intact; writes atomically via a
sibling temporary and `os.replace`; and returns
`::EnvSaveResult(ok, message)`, which
`::MetaScreenerApp._prompt_api_key_always` surfaces in a warning dialog.

**Before/after:** `tests/test_env_persistence.py` — **8 failed, 1 passed →
9 passed**. The one that passed before did so vacuously
(`test_no_temporary_file_is_left_behind`: the old code wrote no temporary
because it overwrote the target directly).

#### What a safe write looks like here, as the prompt asks

The file is user-authored, gitignored, and holds a secret. Those three
facts pull in different directions and the design has to satisfy all of
them.

* **A lost file is the worst outcome**, because `.env` is the *only*
  persistence this application has (F-116: no settings file, no registry
  use, no config parser anywhere). What is lost is not recoverable from
  elsewhere in the program. Hence: never truncate a file we could not
  first read.
* **A partial write is a different kind of bad** — arguably worse than a
  lost file, because a half-written `.env` still loads, silently, with
  some variables missing. `Path.write_text` opens with mode `w`, which
  truncates at open, so a write interrupted by a full disk left exactly
  that. `os.replace` is atomic on Windows and POSIX, so the file is either
  wholly old or wholly new, never in between.
* **The temporary is a second copy of a secret.** It is removed when the
  rename fails, and `.gitignore` now covers `.env.tmp` so that a crash
  between write and rename cannot strand the user's API key in a file
  that `git status` would offer to commit.
* **One residue, recorded rather than silently changed:** the temporary
  inherits default permissions (`0o666 & ~umask` on POSIX), so on a
  permissive umask the secret is briefly group/world-readable. The
  pre-existing code created `.env` itself with exactly the same
  permissions, so this is not a regression, and tightening it is a
  behaviour change no finding asks for. It belongs with wave 11's `.env`
  work.

**Deliberately not fixed**, and named in the docstring so wave 11 inherits
them rather than rediscovering them: the save filter matches the literal
prefix `OPENAI_API_KEY=` while `_load_env_file` splits on the first `=` and
strips, so `OPENAI_API_KEY = x` and `export OPENAI_API_KEY=x` survive the
filter and win on reload (first occurrence wins), making the newly saved
key dead on arrival; a UTF-8 BOM hides the line from the filter the same
way; the value is written unescaped, so an interior newline splits it and
truncates on reload; and `_load_env_file` still swallows the same read
failures, which is how a user reaches the destructive save in the first
place.

### F-89 — `c5e2100` (behaviour) and `b01ec25` (re-key)

`plugins/_common/llm_client.py::_cache_key` takes `endpoint` as a required
keyword and hashes a five-member object. Both stage curries
(`plugins/06_el/screen.py::_cache_key`,
`plugins/07_il/screen.py::_cache_key`) require and forward it; the four
production call sites pass the once-per-run resolved value.

**Before/after:** `tests/test_cache_key.py` — **42 failed → 42 passed**
(every test in the file fails while `endpoint` is an unknown keyword, which
is the correct before-state for a required parameter). Full suite at
`c5e2100`: **2 failed, 726 passed, 4 skipped** — see §6.

Both golden replays now pop `OPENAI_BASE_URL` the way they already popped
`OPENAI_API_KEY`. Verified: both regression files behave identically with
the variable set and unset. Without it, a developer who exports it for
their own local server misses all 170/84 entries and gets a red suite on
their machine alone — Q2's failure mode, arriving through the test harness
instead of the key function. The general remedy is an autouse fixture
clearing the LLM environment, which is **F-114** and is not this wave's.

---

## 5. The re-key: five obligations discharged

**A re-key, not a re-capture.** The stored keys change; the stored values
do not. No API call was made and no decision was recomputed.

**Method.** For every (criterion, record) pair the stage engine enumerates
over the committed golden corpora, derive **both** keys — the old
four-member one, reimplemented from `c5e2100^`, and the new five-member one
via the live stage curry — then move each committed entry from the first
label to the second. The reimplementation is self-validating: were the
formula or the enumeration wrong, the derived old keys would not match the
committed golden keys, and obligation 1 would fail.

The migration **refused to write** unless the mapping was a pure
relabelling.

| # | Obligation | EL | IL |
|---|---|---|---|
| 1 | count preserved, mapping 1:1 | **170 → 170**, 170/170 old keys matched | **84 → 84**, 84/84 matched |
| 2 | no collisions, no orphans | **0 collisions, 0 orphans** | **0, 0** |
| 3 | values byte-identical as multisets | **yes** | **yes** |
| 4 | new key set disjoint from the old | **yes** (overlap 0) | **yes** (overlap 0) |
| 5 | `_invocation` preserved | `{batch_size 5, model gpt-4o-mini, trunc_chars 4000}` | same |

All five discharge **offline**, as §B4.6 predicted. The measured survival
figure reproduces §B4.5 exactly: **0 of 170 EL and 0 of 84 IL keys
survive.**

EL derives 170 pairs for 170 entries. **IL derives 168 pairs for 84
entries**, because `IC-5` uses the `contains` operator and never reaches
the write-back site (gated `if c.operator == "llm" and to_call:`); all 84
are `IC-1`'s. Not an orphan — and it independently reproduces the
incidental figure §B4.5 recorded, which is further evidence the enumeration
matches the engine's.

### Which goldens changed, and which did not

`git diff main...HEAD -- tests/golden/` is **two files, 0 insertions, 0
deletions**:

```
 tests/golden/el_cache_v3.1.0.json | Bin 76992 -> 76992 bytes
 tests/golden/il_cache_v3.1.0.json | Bin 30504 -> 30504 bytes
```

| File | Before | After | Why |
|---|---|---|---|
| `el_cache_v3.1.0.json` | `A7009F0B…` | `8A429511…` | **changed** — every key relabelled; values untouched |
| `il_cache_v3.1.0.json` | `F29CDBAA…` | `3D1E95AF…` | **changed** — same |
| `el_filtered_v3.1.0.csv` | `604CB2F5…` | `604CB2F5…` | unchanged — records decisions; the re-key changed only labels, so the replay produces the same report |
| `il_filtered_v3.1.0.csv` | `088CCA9D…` | `088CCA9D…` | unchanged — same |
| `el_input_v3.1.0.csv` | `AF029F8D…` | `AF029F8D…` | unchanged — a corpus, not an output |
| `il_input_v3.1.0.csv` | `C4C5D739…` | `C4C5D739…` | unchanged — same |
| `criteria_harmonized_v3.1.0.csv` | `A01CCC73…` | `A01CCC73…` | unchanged — an input to every stage |
| `eh_filtered_v3.1.0.csv` | `9B1EB10D…` | `9B1EB10D…` | unchanged — upstream of EL/IL |
| `ih_filtered_v3.1.0.csv` | `D0B559F8…` | `D0B559F8…` | unchanged — upstream of EL/IL |

**Wave 2's property holds here too, and for the same reason:** the four
decision-recording goldens are byte-identical, which is the check that this
changed only labels. They are additionally identical to their values at
wave 2 and at `1b2a06b`, so they have not moved across two re-keys.

Both cache files are identical in **length** before and after (76992 and
30504) — what a relabelling of fixed-width hex keys over unchanged values
should produce, and the same figures wave 2 reported.

**`tests/golden/** binary` still holds.** `git check-attr binary` reports
`binary: set` for both cache files, and git renders the diff as `Bin`.
`tests/test_golden_rekey.py::TestGoldenSerialisationConventions` now
asserts both the attribute and the framing it protects (CRLF throughout, no
bare LF, two-space indent, no trailing newline).

### The artifact wave 2 skipped

`git show --stat c8d2fb3` is three files — `CHANGELOG.md` and the two cache
fixtures — and none of them is a script. Wave 2's proof was discharged and
thrown away; it exists only as prose in a commit message. §B4.6 names that
as the thing to do differently. Committed here:

| Artifact | Role |
|---|---|
| `tools/rekey_cache_goldens.py` | the migration. `--migrate` derived the mapping and wrote the goldens (run once, producing `b01ec25`); `--verify` re-checks the result and exits 0/1 |
| `tests/test_golden_rekey.py` | 17 tests, run on every suite run |

**How to re-run the proof:**

```
python tools/rekey_cache_goldens.py --verify      # exit 0
python -m pytest tests/test_golden_rekey.py       # 17 passed
```

**Why the standing check is over the post-conditions.** A migration is not
idempotent: once the goldens are re-keyed, re-deriving the mapping from
them finds nothing to move. A check that only worked *before* it was
applied would be exactly as unrepeatable as wave 2's. So `verify_stage`
derives both keys for every pair and requires the committed golden to
contain **all** of the new ones and **none** of the old ones — obligations
1, 2 and 4 restated over the migrated artefact, needing no git history.

Obligation 3 is the one that cannot be recomputed from the migrated file
alone, because the values it must be compared against lived in the
pre-migration file. It is pinned instead, as a SHA-256 over the sorted
multiset of serialised values, measured at `c5e2100` before a byte was
written:

```
EL 8d590115d4c24689c83a8e614e3b2fdfd7391bc4b61b2460f93d0226259dde8a
IL a084f527a8bb82c95bcd64df5aca838c7424f4c9b7306b114e8340806eba0e32
```

A re-key does not touch values, so these must survive this migration and
every later one.

### The endpoint the goldens were re-keyed to

`DEFAULT_OPENAI_BASE_URL` — the public API. The captures were taken with a
live `OPENAI_API_KEY` against `gpt-4o-mini`, a model only OpenAI serves, at
a time when no repository code read `OPENAI_BASE_URL` at all.

That is an **inference, not a record** — F-128 is the standing finding that
capture-time provenance was never written down and cannot be added
retroactively. It does not rest on faith: the byte-identity tests replay
the re-keyed cache at the default endpoint and reproduce the committed
report CSVs exactly. Had the endpoint been wrong, every lookup would miss
and both would fail. **Their passing is the verification.**

No provenance field was added to `_invocation` — out of scope for this
wave, and F-128 is the row that owns it.

---

## 6. Part 4 — the F-142 audit question, verified

> After this wave, can a pre-F-89 cache entry still be served?

**No.** Traced, then demonstrated.

**The trace.** The read is a single expression — `if use_cache and k in
cache_out` at `plugins/06_el/screen.py:654` and
`plugins/07_il/screen.py:656` — with `k` freshly computed by the stage
curry. There is no second lookup, no `.get(…, fallback)`, no prefix match,
no iteration over `cache_out.keys()`, no normalisation, and no
migration-on-load: `plugins/_common/llm_client.py::_load_cache_from_jsonl`
does not touch keys. `::_row_target_text_hash`, the hash the pre-F-01 key
used, is still imported by both stages but is never called by either engine
— a dead import, not an alternate path. So an entry is served only under
exact string equality with a key the current function computed, and the
current function hashes a five-member object where the old one hashed four.

**The demonstration.** A single entry was placed in `cache_in` under the
**old** four-member key for a real pair of the golden corpus (`A009`,
`EC-2`), carrying a verdict no honest run would produce, and `run_el_screen`
was run with no API key:

```
old (pre-F-89) key: 998f5cb3ea79f26a4dbf7b2cd6c7b00da53a969168ef09ac6a5b52cd4492668e
new (post-F-89) key: 9fbbfc81730eb2f93d63231e754358fe0abbc108a2642f8590ec65161a10df57
keys equal? False

[EL] cache_hits=0 | to_call=85
[EL] cache_hits=0 | to_call=85

1. WAS IT SERVED?   'FABRICATED-BY-F-86' in the record's evidence: False
   evidence for A009/EC-2: {'status': 'UNCERTAIN', …, 'used': False}
2. REPORTED AS A HIT?  every cache_hits line is 0: True
3. DOES IT SURVIVE?    old key still in cache_out: True (value unchanged)
```

The fabricated verdict does not reach the record. The run reports zero hits
rather than a healthy `cache_hits=N`. **The wave-8 argument was correct and
the wave 9/11 swap rests on a true premise.**

### What remains of F-142

Not (a) nothing. Mostly (b), plus one genuinely new and much smaller
finding, and one part that was never F-142's to begin with.

**F-142 as filed is closed by incidental remedy.** Its subject is "a cache
entry poisoned before `3f37f17`". That population is now unreachable —
structurally, not by policy — and unreachable is a stronger guarantee than
the version-marker-plus-warning its fix cell proposed, because it needs no
user action and cannot be misconfigured. The remedy it asked for was a way
to *distrust* such entries; they can no longer be trusted by anything.

**(b) The documentation note is owed.** Users hold bundles whose caches are
now inert. Nothing warns them, and the observable symptom is a re-run that
costs a full corpus of API calls where the previous run cost nothing. That
is correct behaviour presenting as a regression, which is exactly the kind
of thing a CHANGELOG entry exists for. **Not written here** — the prompt
says report the residue, not implement it.

**(c) One new finding, small.** A pre-F-89 entry is *inert but immortal*.
`cache_out` starts as `dict(cache_in)`, unreachable entries are never
dropped, and `::_dump_cache_to_jsonl` writes every one of them back — so
each bundle carries a permanently growing stratum of entries that can never
be served, that nothing can identify, and that no user action can remove.
For a golden-sized corpus that is 170 dead entries beside 170 live ones
after one re-key. This is hygiene, not correctness — nothing wrong is ever
*served* — and it is a consequence of `_is_cacheable_evidence`'s deliberate
"entries arriving in `cache_in` are carried through untouched". Proposed as
a new **Low** row, F-143, in §7.

**The general mechanism was never F-142's alone.** "The cache value records
nothing about the code that produced it" is real and untouched: this wave
stranded one generation of entries incidentally, and provides no mechanism,
so a future defect that changes behaviour without changing the key would be
exactly as invisible as F-86 was. But that is **F-135** (*which call*) and
**F-88** (*which model*), both open. Keeping F-142 open as a third statement
of it would be the register disagreeing with itself — which is F-131's
lesson.

---

## 7. Register amendments

Applied to `docs/internal/diagnostic/03_findings.md`.

| Row | Change |
|---|---|
| **F-89** | Closed. Fix cell records the decision (verbatim; absent-as-resolved-default; the `str(client.base_url)` third candidate), the two commits, and the five obligations with figures. |
| **F-92** | Closed. Fix cell records that the 1.40.0 question cannot be settled offline, what was searched, and that the fix makes it moot. |
| **F-139** | Closed. Fix cell records the reproduction, the three rules, and the four defects deliberately left for wave 11. |
| **F-142** | Closed by incidental remedy, with the trace and the demonstration recorded, and the residue split: doc note owed, F-143 filed, general mechanism referred to F-135/F-88. |
| **F-135** | Amended, not closed: adds the §B4.6 constraint that a call fingerprint over the *existing* goldens is not offline-dischargeable, because its value for the archived run is unknown — the same class as F-128. Requires a live re-capture. |
| **F-88** | Amended likewise for its tier that writes into archived records. |
| **F-114** | Amended: the hazard is now live rather than latent — the endpoint is a cache-key input read from the environment, and the two golden replays pin it locally. The autouse fixture is the general remedy. |
| **F-128** | Amended: this wave re-keyed without adding provenance, so the row is unchanged in substance but now has a concrete instance — §5 records that the capture endpoint had to be *inferred*. |
| **F-101** | Amended: it noted that making the key's invariant literal "belongs with F-89 if done at all". F-89 has now landed without it, so the batch-composition discriminator would be a *second* re-key. |
| **F-143** | **New (Low, hygiene):** unreachable cache entries accumulate in bundles unboundedly and unidentifiably. See §6(c). |

---

## 8. Verification

| Check | Result |
|---|---|
| Suite at `f40af5f` (baseline) | 695 passed, 4 skipped |
| Suite at `3703abd` (F-92) | 708 passed, 4 skipped |
| Suite at `37dd61c` (F-139) | 717 passed, 4 skipped |
| Suite at `c5e2100` (F-89 code) | **2 failed**, 726 passed, 4 skipped |
| Suite at `b01ec25` (re-key) | **745 passed, 4 skipped, 0 failed** |
| `python tools/audit_imports.py plugins` | all `clean`, exit **0** |
| `python tools/audit_decorators.py plugins` | all `clean`, exit **0** |
| `python tools/check_encoding.py` | 167 paths, no BOM or mojibake, exit **0** |
| `python tools/rekey_cache_goldens.py --verify` | exit **0** |

**+50 tests, net.** 695 → 745.

### The two failures at `c5e2100`, and why they were correct

`tests/test_el_regression.py::TestELGolden::test_byte_identical_to_golden`
and its IL twin. At that commit every committed golden key is a miss, so
the replay produces empty evidence and the report CSV differs. This is not
a defect and it is not avoidable while keeping the two commits separate:
the behaviour change invalidates the fixtures, and the re-key repairs them.

Wave 2 did exactly this and said so — `34fa37a` reported *"278 passed, 4
skipped, 2 failed (the two goldens above)"* and `c8d2fb3` restored green.
The split is deliberate, and the wave prompt asks for it: the proof and the
behaviour change are reviewable independently.

---

## 9. Commits

| Hash | Subject |
|---|---|
| `3703abd` | `fix(F-92): read the endpoint by name, and pass it to the client` |
| `37dd61c` | `fix(F-139): do not replace .env with one line when the read fails` |
| `c5e2100` | `fix(F-89): put the resolved endpoint in the cache key` |
| `b01ec25` | `test(F-89): re-key the EL/IL cache goldens, and commit the proof` |

Not merged, not tagged, not pushed.
