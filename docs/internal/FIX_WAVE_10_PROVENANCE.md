# Fix wave 10 — provenance

Branch `fix/wave-10-provenance`, cut from `f014e2f` (`main`, tagged
`post-wave-9`). **Additive throughout: no golden moved**, verified two ways at
step 0 and again at close-out. No merge, no tag, no push.

Scope: **F-88** (High), **F-98** (High), **F-141** (High), **F-143** (Low, from
wave 9) and the documentation half of **F-96** (High). Out, explicitly: F-135,
and every GUI, discovery, settings-persistence, default-model, API-key and
harmoniser item — waves 11 and 12.

---

## 0. Gate

| Check | Result |
|---|---|
| `git rev-parse HEAD` | `f014e2f67eb67739a25bc852407b8ec1b89f9dc8` |
| Branch / tag | `main`, tagged `post-wave-9` |
| `git status --porcelain` | clean |
| Origin sync | 0 ahead, 0 behind |
| Gap commits | none |
| Golden manifest | 9 files, SHA-256 recorded (§7) |
| Suite baseline | **750 passed, 5 skipped** |

---

## 1. Three disagreements with the brief, recorded before any code was written

### 1.1 F-96's variance metric — the brief overrides the register

The register's F-96 fix cell lists **four** items, the fourth being *"switch the
variance metric from distinct spans to distinct quotes"*. The brief scopes that
out, with a reason: it touches F-63's neighbourhood and belongs with the
re-capture. The brief was followed.

**Consequence, stated so the accounting stays honest: F-96 cannot be closed this
wave.** Three of four clauses are done. The row keeps an empty Effort marker and
counts as open, under the partial-closure convention (§5.2).

### 1.2 F-141's scope has grown since the row was written

The row names **three** findings — F-86, F-87, F-104. The brief asks for **five**,
adding F-90 and F-143. The row is stale rather than wrong: it was written at wave
8, and waves 8 and 9 have since closed further output-changing defects. The brief
is a strict superset and was followed; the row is annotated with the reason.

### 1.3 F-143 — the brief does not close it, and does not claim to

F-143's fix cell asks for one of two remedies — drop the unreproducible entries,
or count and report them — and asks explicitly that the tension with F-87's
carry-through rule be *"resolved explicitly rather than by whichever is
implemented first."* Part 3 of the brief assigns F-143 a changelog paragraph and
nothing else.

A disclosure is neither remedy and resolves no tension. **F-143 therefore stays
open**, annotated with the disclosure. This was flagged before starting rather
than discovered at close-out; the brief was followed as written.

---

## 2. F-98 first — freezing the study input

`78cd401`. The brief put this first on the reasoning that wave 9 passed a
golden-touching wave without the study input frozen and the exposure was nil only
by luck. That is confirmed: `git log -- tests/golden/{el,il}_filtered_v3.1.0.csv`
is **one commit**, the original capture `4fbe8fd`. Wave 9's re-key moved the two
*cache* goldens and left the two filtered ones untouched. Had F-89's re-key
been a re-capture, the published study's input would have changed inside a wave
whose brief never mentioned it.

### 2.1 What the freeze protects, measured rather than asserted

`docs/llm-evaluation.md` §Reproducibility publishes two commands and this claim:

> Every artefact in this evaluation is regenerable from inputs already in the
> repository … re-running the ingestor on the committed grids reproduces the four
> output files byte-for-byte.

That claim was **true and unverified**. Running it at step 0 reproduced all four
`docs/data/eval_*` artefacts byte-for-byte. It has **five** inputs, and **three
were mutable goldens**:

| Input | Was | Now |
|---|---|---|
| `docs/data/grids/partition_manifest.csv` | already frozen | unchanged |
| `docs/data/grids/filled/*.xlsx` | already frozen | unchanged |
| `criteria_harmonized_v3.1.0.csv` | **`tests/golden/`** | `docs/data/study_input/` |
| `el_filtered_v3.1.0.csv` | **`tests/golden/`** | `docs/data/study_input/` |
| `il_filtered_v3.1.0.csv` | **`tests/golden/`** | `docs/data/study_input/` |

`el_input_v3.1.0.csv` is frozen too: §Results cites it as the evidence for the
record-for-record deterministic claim.

### 2.2 What breaks without it

Wave 12 re-captures the goldens against a different model.
`tools/capture_el_il_goldens.py` overwrites six files in one run with no
versioning and no cross-check against `docs/data/`. After that run, and with no
freeze:

- the two commands in §Reproducibility still execute, exit 0, and produce
  **different kappas**;
- the document goes on claiming byte-for-byte reproduction of
  `docs/data/eval_*`, which is now false;
- **no test fails**, because no test compared them;
- nothing in the changelog is triggered, because no user-facing behaviour changed.

A published analysis silently acquires a different input. That is F-98 stated as
a sequence of events rather than as a structural observation.

### 2.3 The freeze is wider than the brief specified — deliberately, not quietly

The register's fix cell and the brief both say *the two filtered CSVs*. Freezing
two of the five inputs would have left the published reproduction command still
pointing at two mutable goldens. The freeze covers **every `tests/golden/` file
the document cites**: the two filtered CSVs, the criteria table and the post-IH
record set. That rule is itself derivable, which is what makes the guard in §2.4
possible.

### 2.4 Five guards, none of them a hand-maintained list

The brief required that the protection not be a hand-maintained list, "this
project has been bitten by those five times." `tests/test_frozen_build_spec.py`
states the rule the guards follow: *"A fixed list is the same enumeration mistake
as F-01's cache key: it is correct exactly until someone adds an import, and then
it is silently wrong."*

| Guard | Derived from | Catches |
|---|---|---|
| **Coverage** | the directory listing and `SHA256SUMS`, compared **both ways** | a frozen file with no digest; a digest with no file |
| **Fidelity** | re-running the published command and comparing four outputs byte-for-byte | the input drifting, the ingestor changing, or `docs/data/eval_*` being hand-edited |
| **Independence** | a grep for any *file* under `tests/golden/` in the document | the document being pointed back at a fixture, including at paths that do not exist yet |
| **Non-interference** | every `Path` constant in the capture tool, plus its source text | a re-capture ever reaching `docs/` |
| **Bytes** | `.gitattributes` | `* text=auto` rewriting the frozen CSVs on checkout |

**Fidelity is the one that matters**, and it is what a digest cannot do: it
executes the document's own claim. A digest proves the input did not move;
fidelity proves it still *produces* the published numbers.

**The bytes guard is not theoretical.** Three of the four frozen files are
pure-LF and one (`criteria_harmonized`) is pure-CRLF. `tests/golden/** binary`
protects the originals; a copy outside that path inherits `* text=auto`, so a
fresh Windows clone would rewrite them, every digest would break, and the failure
would present as tampering rather than as checkout. This is the F-128 trap one
directory over, and it was found by writing the guard before the files.

**Two guards failed first and were tightened**, which is the reason to write them
first:

1. *Non-interference* was written as "every output path stays under
   `tests/golden/`" and immediately caught `samples/20260122_1654_aggregate.csv`
   — an **input**, not an output. The invariant that matters is not "everything
   is an output" but "nothing is under `docs/`". Rewritten to that.
2. *Independence* was written as "the document must not contain the string
   `tests/golden`" and immediately failed on the new §Study input paragraph,
   which *explains the freeze* and must be able to name what it froze away from.
   Narrowed to naming a **file** under `tests/golden/`, because naming a file is
   how a fixture becomes an input again.

---

## 3. F-88 — the provenance design, and its argument

`97886f3`, with documentation corrections in `97886f3` and `03acf06`.

### 3.1 Which artefacts carry it — one, and why not the others

The brief asked for this argued in a paragraph before implementing. The answer is
**the history entry of `manifest.pipeline.history[]`, and nothing else.**

| Candidate | Lifetime / reader | Verdict |
|---|---|---|
| **Manifest history entry** | the bundle's whole life; anyone auditing it | **Yes.** One entry per stage run — the granularity the fact actually has |
| Evidence JSON | per decision, in the report CSVs | **No.** This is §B8.1's tier 2. It lives in the `{el,il}_filtered` goldens, so it carries the F-62/F-63/F-64 re-capture cost |
| Cache value | per decision, outlives the run | **No**, twice. It would move the cache goldens; and it is **redundant**, because since F-89 the cache *key* is a hash over the provenance itself, so a value restating it could only ever agree with its own key |
| Report column | per record, in a CSV a human reads | **No.** A per-run constant duplicated down every row, and a second representation of a fact the history entry holds — F-69's shape, which this project has shipped four times |

The cache-value line is the interesting one. Wave 9 did not merely make the
endpoint recordable; it made recording it in the cache value *pointless*. That
is a wave-9 dividend the F-88 row could not have anticipated.

### 3.2 Per-run or per-decision — and the cached-decision case

**Per run.** The brief asked what a reader should conclude about a cached
decision from an earlier run under a different model, "that is the case that
actually matters." The answer is stronger than the question implies.

Since F-89, `plugins/_common/llm_client.py::_shared_cache_key` hashes

```
{prompt_version, model, endpoint, temperature, prompt}
```

Four of those five are recorded provenance fields. The fifth, the rendered
prompt, carries `trunc_chars` transitively — through the bytes truncation
removes. Therefore:

> **A cached entry cannot be served into a run whose provenance differs in any
> recorded field except `batch_size`.** The lookup misses and the model is called
> again.

So the per-run record is not the weak claim it looks like. It is true of **every
decision in the stage's output**, cached or fresh, not merely of the calls this
run happened to make. A reader who finds `model: gpt-4o-mini` in a history entry
may conclude that every decision that stage exported was produced by
`gpt-4o-mini` at that endpoint, temperature and prompt version — because a
decision produced under anything else could not have been served.

**The residual, stated rather than buried.** `batch_size` is recorded and is
**not** a key input, because the key renders a batch of one. A cached decision
may have been produced inside a differently-sized batch than the manifest
records. This is the one provenance field a reader may not carry back to a cached
decision, and it is pinned by
`tests/test_provenance.py::test_batch_size_is_the_honest_residual` rather than
left as a comment, so it cannot stop being true silently.

Two further limits, since a per-run claim invites over-reading:

- provenance says **which engine**, not **which code**. A decision cached before
  a bug fix and replayed after it carries no marker. That is F-142's territory,
  discharged in wave 9 by the re-key rather than by a marker;
- it is per run, not per response, so it does not make F-86's substitution
  question answerable. F-135 owns that, and §4.2 of the amended
  `docs/llm-evaluation.md` says so explicitly rather than letting a reader infer
  otherwise.

### 3.3 Six fields, not four — the asymmetry

The brief flagged that *"the model answered"* and *"the model was shown
something"* are different claims and only the first is recorded, and asked that
provenance not inherit the ambiguity.

Measured: a run at `trunc_chars = -100` sends **empty** title and keywords
(`s[:trunc_chars]` is a negative slice, so any field shorter than 100 characters
becomes `""`), and its run report is **byte-identical** to a healthy run — 4
records, 4 answered, 0 failed, all nine keys equal. Both halves are asserted in
`TestProvenanceDoesNotInheritTheAnsweredAmbiguity`, including the negative one:
if the counting block ever *does* separate them, that test says to retire it
rather than repair it.

Recording `trunc_chars` is what makes `answered` interpretable. `batch_size`
completes the set the capture harness already asserts in its `_invocation`
envelope, so a manifest and a golden describe a run in the same terms.

### 3.4 Transport — a key, not a ninth tuple position

`run_el_screen`'s own docstring settles this, and names the finding:

> A dict rather than more tuple positions: later waves add provenance (F-88,
> F-135) to the same history entry, and a key is cheaper to add than a position —
> and safer, since a positional append is exactly what silently rebinds an
> existing unpack.

`stage_state.py::run_outcome` was already written for it: *"Unknown keys are
ignored and missing keys default, so … provenance fields and an older build's
absent report are both non-events."*

So provenance rides **inside the run report**, and the writer **lifts** it onto
the history entry as a sibling of `llm`. The lift is four lines and is the reason
`llm` stays a pure counting block: the register calls it *"a counting field"*,
and which engine answered is not a count.

The engine is the only layer that can supply it. The endpoint is resolved at
`plugins/06_el/screen.py:609` and never returned; the model and temperature the
UI holds are live widget values that may be edited between the run and the
export. Provenance is populated at the point the endpoint is resolved — the only
point at which all six facts are simultaneously true *of that run*.

**Net effect on the UI layer: none.** `llm_report` already flowed engine → `self`
→ writer, so no view, no standalone shell and no call site changed. Only four
type annotations widened from `Dict[str, int]` to `Dict[str, Any]`.

### 3.5 Additive, and asserted to be

- omitted, never zero-filled: a stage with no criteria consults no model and
  names none;
- old bundles load unchanged and **gain no invented provenance** — an inferred
  engine recorded as an observed one is worse than a blank (F-68/F-70 precedent,
  asserted directly);
- `counts` untouched, which two other modules assert by exact dict equality;
- no golden pins a manifest, so nothing moved.

### 3.6 Three published claims went stale, and one more was missed

The fix falsified statements in `README.md` and `docs/faq.md` that the manifest
does **not** record this. Both corrected in `97886f3`. `docs/usage.md` described
the cache key as covering model, temperature and prompt version, omitting the
resolved endpoint F-89 added — a **pre-existing** error, corrected in the same
commit because it is the same sentence's subject.

**A second FAQ passage was missed and corrected in `03acf06`.** The
"Can I change the LLM prompt without forking the project?" answer still told the
reader the manifest cannot say which prompt produced a bundle. The correction
also states a limit rather than leaving it implied: `PROMPT_VERSION` is a
hand-bumped label, not a content hash, so editing a prompt without bumping it
leaves the manifest naming the old version. The cache is not misled — its key
covers the rendered prompt — but the manifest is.

---

## 4. F-141 and F-143 — the disclosure

`ba68b39`.

### 4.1 Five entries, and a renumbering

The list is ordered by how likely each defect was to have changed which records
were included or excluded — the section's own stated contract. F-86 is the
register's only Critical and the only defect in the set that fabricates an
exclusion, so it is **item 1**, which forced a renumber to 1..18.

Done programmatically: existing item bodies moved **verbatim**, only the leading
`**N.` token rewritten, contiguity of 1..18 asserted rather than eyeballed. Three
cross-references name an item by number — one inside the list (item 7 → the
blank-`type` item) and two in `### Fixed` ("See item 12/13 above") — all three
repaired from the old→new map. Renumbering is free here because `[Unreleased]`
has never shipped.

Placement of the five: F-86 at 1; F-90 at 8 and F-87 at 9, below the two
cancellation items because both are safe-direction (records are flagged, not
dropped) and above the "no screening result is affected" group; F-104 at 17 and
F-143 at 18, which change cost and audit trail but no verdict.

### 4.2 What the entry does that a normal changelog entry does not

**It says what to do.** A new preamble paragraph: the remedy in every case is to
re-run. These defects produced plausible artefacts rather than broken ones, so
there is nothing for a tool to detect and no migration to run — and re-running is
*sufficient* precisely because F-89's re-key means the cache cannot replay a
pre-fix verdict.

**It says what cannot be determined**, in a closing paragraph.

### 4.3 The brief's figure for that paragraph was wrong

The brief specified: *"wave 7 established that 253 of 254 committed cache entries
can be cleared of substitution by a reverse test, but one (A452 / IC-1, quote
'Computer science') is structurally undecidable."*

**Wave 7 measured no such thing.** `FIX_WAVE_7_CACHE.md` lines 335–364 give two
different populations:

| Population | Cleared | Undecidable |
|---|---|---|
| **254 cache entries** | **175** by quote uniqueness, **+9** whose quote had already failed validation | **70** |
| **5 record-removing verdicts** | **4** | **1** — `A452` / `IC-1` / *"Computer science"* |

The one-undecidable figure belongs to the five exclusions, not to the 254
entries. `175 + 9 + 70 = 254`, checked. Publishing 253/254 would have claimed
**99.6%** clearance where the measured entry-level figure is **72%** — in a
disclosure whose whole subject is the integrity of screening output, and again in
`docs/llm-evaluation.md` under Part 4. Both populations are now stated
separately and correctly in both documents.

Verified against the source directly, not via the reader that first flagged it.

### 4.4 Framing

The 254 entries are **this project's committed caches**, behind the published
validation study — not the user's bundle. The changelog says so, and adds that
the same check can be run against a user's own bundle under the same limit.

---

## 5. F-96 — the documentation half

`e9c31e7`.

### 5.1 What was added

- **§Model under evaluation**, in the document head. `gpt-4o-mini`, captured at
  `4fbe8fd` (2026-05-02), truncation 4000, batch 5, prompt versions
  `EL_v1_jsonlist`/`IL_v1_jsonlist`. It hedges where it must: a table separates
  the facts the capture harness **asserts** from the two it leaves to
  **inference** (endpoint, temperature — the capture sets neither). §A9.4
  establishes that `_invocation.model` is a hand-asserted constant of the capture
  tool, not a value recovered from the run, and the section says so. The prompt
  version carries its own qualification: the stamp is a hand-maintained label,
  not a hash, and both labels are still in use, so it identifies the version the
  study ran but not that today's prompt text is identical to it.
- **A "Single model" limitation bullet**, naming the gap as widest for the small
  local models the README invites, whose characteristic weaknesses are precisely
  the ones these metrics do not probe.
- **The wave-7 audit, published**, with the corrected figures of §4.3 and stated
  in both directions: no entry anywhere shows the positive signature of a
  substitution, *and* the residue is structural rather than effort-limited.
- **The degenerate-output note extended** with the two modes §B6.4 marks as
  unanticipated: **JSON-shape failure**, whose zero-variance signature the note's
  own advice would misdiagnose as a lazy model, and **identifier drift**.
- Two symptoms the brief names in its diagnosis, closed in the same pass:
  §Results now says which model its figures describe, and the FAQ's kappa answer
  carries the model and a pointer to the new limitation instead of quoting
  0.28/0.26 unqualified.

### 5.2 One self-caught overstatement

The audit bullet first ended: *"The one thing that would — a per-response record
of which call answered for which record — did not exist when this study was
captured. It exists now, for runs made from this version onward."*

**That is false.** F-88 records provenance per *run*; a per-response record is
F-135, explicitly out of scope. Corrected before commit to say that it did not
exist then and does not exist now, and that per-run provenance does not close
this gap either.

### 5.3 "Four new modes" — a disagreement of counting, not of fact

The register's fix cell says *four*. §B6.4's table marks **two** as unanticipated
(JSON-shape failure, `a_id` drift) and **two** as *partially* anticipated
(exact-substring quoting failure, confidence miscalibration). The brief scopes
the work to the two unanticipated ones, which is the more precise reading of the
same table. The two partially-anticipated ones are untouched, and the
variance-metric clause is deliberately not done (§1.1).

---

## 6. The review pass

The brief did not require a full refutation pass — this wave moves no golden and
touches no user-authored file — but required Parts 3 and 4 to be reviewed
specifically for claims that over- or understate the evidence, because one is a
public statement about scientific output and the other amends a published
document. Four lenses (numbers, overstatement, understatement, document
coherence), each finding adversarially verified.

**Eleven distinct defects raised; ten fixed, one deferred with a reason.** All
were in Parts 3 and 4 — none in the code.

*A note on reading the verdicts: several refutations returned "the quoted
sentence is not in the file". That is an artefact of fixing confirmed findings
while the verifiers were still running, not a clearance. Every finding below was
re-verified against the source, or against the data, by hand before being acted
on.*

### 6.1 The one that mattered most — and it was mine

> `| Prompt version | *not applicable* | no such field existed at the capture commit |`

**False, and asserted with a claim of having verified it.** `PROMPT_VERSION`
*did* exist at `4fbe8fd` — `"EL_v1_jsonlist"` at `plugins/06_el/plugin.py:67`
and `"IL_v1_jsonlist"` at `plugins/07_il/plugin.py:66` — and was already the
first member of the cache key every one of the 254 committed entries was written
under.

The error came from checking `git show 4fbe8fd:plugins/06_el/prompt.py`, **a
path that did not exist at that commit**: the prompt modules were extracted later
in `edd466d`, and the constant then lived in `plugin.py`. The command printed
nothing, and nothing was read as absence. **An absent file and an absent constant
are not the same observation, and `git show` does not distinguish them unless you
ask.** Re-checking with `git cat-file -e` returns *"exists on disk, but not in
4fbe8fd"* immediately.

Corrected in `docs/llm-evaluation.md`, `docs/data/study_input/study_input.meta.txt`
and the F-96 register annotation. The prompt version is now recorded as the
observed fact it is, with its own qualification: the stamp is hand-maintained and
both labels are still in use, so it identifies the version the study ran but not
that today's prompt text is identical to it.

### 6.2 Three defects in the disclosure, all understating the exposure

1. **The re-check condition exempted users the defect could reach.** Item 1 read
   *"you ran EL or IL with a batch size greater than 1 — the default"*. Wave 7
   confirmed the opposite **from source and by test**: the acceptance map was
   built from the whole item list *before* `chunked(items, batch_size)` was
   called, so batching had no bearing on what the guard admitted, and a
   single-record call filed a verdict against a different record and had it
   accepted with `valid_quote: True`. Batch size changes the *rate*, not the
   reachability. A user who set batch size to 1 — a natural choice on a small
   corpus or a weak model — would have read that condition and concluded they
   were safe. Rewritten to exempt no one, and to say why a larger batch raises
   the rate (a visible neighbour's identifier can be copied rather than
   invented). The default is **50**, now stated.
2. **"against the whole corpus" overstated the substitutable population.** At
   both call sites `items` is `to_call`, the criterion's *uncached* subset, which
   shrank as the cache warmed. Rewritten to "every record the criterion still had
   to ask about". The wave-7 brief flags this exact widening as something a
   reader of the shorter description gets wrong — so the changelog had reproduced
   the error the internal record exists to prevent.
3. **The temperature limitation contradicted the new provenance block.** The
   pre-existing bullet said decisions are taken at *"the LLM's default temperature
   for the bundle"* — machinery that does not exist; no bundle records or defaults
   a temperature. My §Model under evaluation table gave a different account of the
   same fact. Reconciled to the true one: 0.0, the code default, which the capture
   did not override.

### 6.3 The claim that was backwards in both public documents

Both Part 3 and Part 4 said the nine `valid_quote: false` entries **"could not
have been substitutions because their quote had already failed validation."**

That is the wrong way round, and I inherited it from `FIX_WAVE_7_CACHE.md:339`,
whose table row reads *"`valid_quote: false` — cannot be a substitution"*. A
failed quote is not evidence that no substitution occurred; **it is what a
substitution looks like once the gate catches it.** Under F-86 the answer is
filed against a record the call did not carry and the quote is then checked
against *that* record's text, so a borrowed quote fails.

Measured directly on the frozen study input rather than argued:

| | count |
|---|---:|
| entries with `valid_quote: false` | **9** (2 EL, 7 IL) |
| — whose own record cannot supply the quote | **8** |
| — of those, quote supplied by no corpus record at all (fabricated outright) | **7** |
| — of those, quote supplied by **11 other records** and not its own — `A345`, on both `EC-2` and `IC-1`, quoting *"Augmented reality"* | **1** |

So the wave-7 brief's companion claim — *"all 254 quotes are supplyable by their
named record"* — is **also false**; it holds for the 245 that passed the gate,
which is what passing the gate means. And `A345` is the one entry in the study
matching the **positive** signature the brief says nothing exhibits.

Both documents now say what the bucket actually supports, which is narrower and
firmer: **those nine failed the evidence gate, so whatever produced them, none of
them removed a record.** The doc adds the `A345` finding explicitly, because
omitting the one near-positive result from a disclosure about integrity would be
the exact failure the disclosure exists to avoid — and because the honest reading
is that the gate worked.

**This is a defect in `FIX_WAVE_7_CACHE.md`, not only in this wave's prose.** It
is recorded here rather than corrected there: that brief is the historical record
of wave 7, and the register row for F-86 is where a correction belongs if one is
wanted.

### 6.4 Two model-scoping gaps the amendment created or sharpened

- **"the run reported above"** in the new failure-mode paragraph had two possible
  antecedents — the archived degenerate run and the study run — and was only
  supportable for the first. Read as the study run it contradicted the very next
  bullet, which reports 70 undecidable entries. Now names the archived run, and
  says explicitly that no such claim is made for the study run.
- **The one behavioural conclusion was left generic.** §Interpretation still said
  *"the LLM is conservative on ambiguous abstracts"* while the numbers had been
  scoped to one model in three places. §B6.1 calls this claim *"falsified in
  direction as well as magnitude"* under a model change, because over-confidence,
  not hedging, is the characteristic small-model failure — and it is the harmful
  direction, since a confident wrong call is acted on where a hedge is routed to
  a human. Now scoped to the model, with that inversion stated.

### 6.5 One finding fixed against its own refutation, and one deferred

**Fixed anyway:** the framing sentence *"Agreement figures describe runs in which
the model produced varied, per-record judgements"* was refuted as out of scope —
it is pre-existing text on `main` that this branch neither wrote nor exposed. The
scope point is correct and the sentence is still wrong: measured on the frozen
input, the study's **EL half is 169 of 170 one decision, 141 of 170 at confidence
0.900**. Pinning the study to `gpt-4o-mini` — the same model as the degenerate
archived run described two sentences later — is what makes leaving it untenable,
and F-96's own description cell names this concentration as part of the finding.
Qualified with measured decisions and confidences only; **the span-based variance
metric is untouched**, since switching it is the clause §1.1 scopes out.

**Deferred:** *"all 170 EL calls"* means 170 per-record decisions, not 170
requests — roughly 34 at that run's batch size. Real, and named in the register
as the seed of a two-to-three-orders-of-magnitude overstatement elsewhere in the
docs. **F-125 item (h) owns it and is open**, with the fix cell "Correct each
passage"; correcting one passage here would discharge part of another row without
annotating it. Left alone, recorded here.

---

## 7. Close-out

### 7.1 Goldens — the headline is that there is none

| Check | Result |
|---|---|
| Per-file SHA-256 of all 9 files vs the step-0 manifest | **9/9 identical, 0 mismatches** |
| `git diff main...HEAD -- tests/golden/` | **empty** |

Nothing moved. The two checks are independent and agree.

### 7.2 Suite

| | Passed | Skipped |
|---|---:|---:|
| Step 0 (`f014e2f`) | 750 | 5 |
| Close-out | **794** | 5 |

**Delta +44, all new, no test changed or removed:**

- **+12** `tests/test_study_input_freeze.py` (F-98) — 4 coverage/integrity, 1
  independence, 2 non-interference, 1 gitattributes, 4 fidelity (one per
  reproduced artefact)
- **+32** `tests/test_provenance.py` (F-88) — 10 engine (5 × EL/IL), 6 bundle, 2
  legacy tolerance, 4 asymmetry, 10 cache-key partition

Skips unchanged at 5.

### 7.3 Tools

| Command | Result |
|---|---|
| `python tools/audit_imports.py plugins/ tests/` | exit 0, all clean |
| `python tools/audit_decorators.py plugins/ tests/` | exit 0, all clean |
| `python tools/check_encoding.py` | exit 0 — 176 paths, no BOM or mojibake |
| `python tools/rekey_cache_goldens.py --verify` | exit 0 — *"Goldens are keyed as this code keys them"* |

`check_encoding` now covers the frozen study input, which `tests/golden/` is
exempt from; it passes.

### 7.4 Register

Totals regenerated by derivation from the Effort markers, not counted by hand
(F-131's lesson). The script reproduces the **published wave-9 totals exactly**
before the annotations, which is what makes it trustworthy after them.

| Severity | Total | Closed | Open | unscheduled | scheduled | backlog | parked |
|---|---:|---:|---:|---:|---:|---:|---:|
| Critical | 4 | 4 | 0 | 0 | 0 | 0 | 0 |
| High | 39 | **27** | **12** | 12 | 0 | 0 | 0 |
| Medium | 62 | 18 | 44 | 40 | **2** | 2 | 0 |
| Low | 35 | 13 | 22 | 17 | 0 | 3 | 2 |
| **Total** | **140** | **62** | **78** | 69 | 2 | 5 | 2 |

Was 60 closed / 80 open. **Two Highs closed: F-98, F-141.**

**No new rows.** The first wave since 6b to open none — recorded because the
brief's standing instruction is to open a row rather than widen a wave, so a zero
is a claim that nothing was found, not that nothing was looked for. Two things
*were* found and are recorded against existing rows rather than as new ones: the
`FIX_WAVE_7_CACHE.md` inversion (§6.3, belongs to F-86's row) and the F-125
passage in §6.5.

**F-88 was worked in full and not closed.** Tier 1 is delivered; the row keeps an
empty marker under the partial-closure convention, because the *finding* is that
no artefact records which engine produced a **decision**, and tier 1 makes a
**run** attributable. Its fix cell argues tier 2 belongs with F-62/F-63/F-64 and
that remains true — but "another row will do it" is not "this row is done", and
the convention exists because that distinction has cost a verification cycle
before. **This is a change from what §1 of this brief anticipated**: F-88 was
initially marked `(done)` and reverted on reading the convention.

**F-96 part-closed** (three of four clauses; §1.1), **F-143 disclosed but not
fixed** (§1.3), **F-135 re-marked `(scheduled)` for wave 12** — its marker had
been removed at wave 9 because the wave it then named had passed; it is restored
against one that has not.

### 7.5 Commits

| Hash | Subject |
|---|---|
| `78cd401` | `fix(F-98): freeze the study input so the goldens can move` |
| `97886f3` | `fix(F-88): record which engine produced each run` |
| `ba68b39` | `docs(F-141, F-143): disclose waves 7-9 to the user who already has results` |
| `03acf06` | `docs(F-88): correct the second FAQ claim the provenance block falsifies` |
| `e9c31e7` | `docs(F-96): name the model the validation study measured` |

Suite green after each. One commit per finding, with `03acf06` the exception: a
follow-up to `97886f3` for a claim missed in it, kept separate rather than
amended so the miss stays visible.

### 7.6 Two commit messages contain the corrected-but-wrong figure's history

`ba68b39` and `e9c31e7` both record the brief's `253 of 254` figure and its
correction, which is intended. Neither records the §6.3 inversion or the §6.1
prompt-version error, because both were found after those commits. History is not
rewritten; this brief and the register annotations carry them.
