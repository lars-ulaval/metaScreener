# Changelog

All notable changes to metaScreener are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### You can now screen with a model on your own computer, and no API key

Before this release, metaScreener could only be used with an OpenAI key. The
documentation described a local-provider workflow, but it was unreachable
through the interface: the only ways to point the application at a local
server were to hand-edit a `.env` file or to set an environment variable, and
the launch dialog refused to let you past without entering *something* in the
API key box — its own message told you to invent a placeholder such as
`"ollama"`.

What changed:

- **The application asks which provider you want**, once, and remembers the
  answer. Dismissing that question no longer closes the application: stages 03,
  04 and 05 need no model of any kind and now stay available.
- **A local model needs no API key at any layer.** The key requirement is a
  question about the provider and the endpoint, not a box that must be
  non-empty.
- **The endpoint is a visible, editable field**, at the application level and
  per stage, and a second line tells you where the value came from — your stage
  override, your application setting, the `OPENAI_BASE_URL` variable, or a
  default.
- **The model field offers what your server reports**, and you can still type a
  name that is not listed. Some servers ignore the model field entirely, so the
  list is a suggestion and never a restriction. If your server will not list its
  models, nothing is disabled.
- **Three local-server problems are told apart**: Ollama is not installed, it is
  installed but not running, or it is running with no model pulled. Each says
  what to do about that one, and the application offers to download a
  recommended model — with its size stated before anything is downloaded, and
  cancellable.
- **The batch size defaults to 5 for a local model** instead of 50. Asking a
  small model for fifty JSON objects in one reply is where it loses track. This
  is a quality setting, not a correctness one, and changing it does not
  invalidate your cached decisions.
- **Your settings survive a launch and the packaged build.** They are stored
  beside your other application data rather than next to the program, which in
  the packaged build was a temporary directory deleted on exit — so a key you
  asked to be remembered was silently gone next time.

**What still needs an OpenAI key:** a run whose endpoint is
`api.openai.com`, which is where an unconfigured installation still points. An
endpoint that bills always requires a key, whatever the provider is set to.

**This release makes no claim about how well a local model screens.** That is a
measurement nobody has made here yet. What is claimed is narrower: the path
exists, it is reachable from the interface, and it does not require paying for
a credential you will not use.

### If you produced results with an earlier version, read this first

This release fixes defects that could have affected screening results. Most
were silent — they produced a plausible-looking answer rather than an error —
so the only way to know whether your review was affected is to check the
conditions below against what you actually did.

They are ordered by how likely they are to have changed **which records were
included or excluded**.

Where a condition matches, the remedy is the same in every case:
**re-run the affected stages on this version and compare.** There is
nothing to repair in place. These defects produced
plausible artefacts rather than broken ones, so there is no corruption
for a tool to detect and no migration to run — the only way to learn
what a corrected run gives you is to perform one. Re-running is also
sufficient: the response cache no longer serves anything an earlier
version wrote, so a re-run cannot replay a verdict that any of these
defects produced.

**1. A record could be excluded on evidence belonging to a different
record.** The two LLM stages send records to the model in batches. The
code that accepted an answer checked the record identifier it named
against every record the criterion still had to ask about, rather than
against the batch that call had actually carried, so an answer naming a
record that call never saw was
accepted anyway — and the quote was then validated against *that*
record's own text, so it passed every check. The result is a
well-formed, fully evidenced exclusion produced by a call that did not
contain the record it excluded. Nothing about it looks wrong: the quote
is genuine, the confidence is high, the evidence trail is complete. It
was also persistent, because the fabricated verdict was written to the
response cache — so re-running reproduced the same exclusion offline,
for ever, at no API cost and with the interface reporting a normal cache
hit. The trigger is a model misreporting an identifier, which is a
characteristic weak-model failure, so the rate rises on exactly the
local-model configurations the README invites. **Re-check if:** you ran
EL or IL and any record was excluded. Batch size does not exempt you:
the guard was equally defective at every size, including 1, where the
defect was reproduced both from source and by test. A larger batch — the
default is 50 — raises the rate rather than the reachability, because a
model that can see its neighbours' identifiers can copy one instead of
inventing it. Answers are now accepted only for the records the call
actually carried, and the quote is validated against that same set.
*(F-86)*

**2. An inclusion criterion could be applied backwards (IL stage).**
If a criterion's `type` cell was blank in `criteria_harmonized.csv`, the IL
stage treated it as an *exclusion*. An inclusion criterion that a record *met* —
which is the reason to keep the record — therefore dropped it instead. Silent,
and exactly backwards. **Re-check if:** you ran IL and any row of your criteria
table had an empty `type`. The stage now refuses such a criterion and names the
spreadsheet row number in its warnings panel rather than guessing. *(F-04)*

**3. Your whole corpus could have been silently emptied, or lost its titles.**
A corpus CSV saved as cp1252 or Latin-1 — the ordinary output of Windows
reference managers — failed to load, and the failure was swallowed: you got zero
records rather than an error. Separately, a CSV with a byte-order mark produced
an unreadable first column, so every record's title read as empty and was
screened as if it had none. **Re-check if:** your corpus came out of EndNote,
Zotero or Excel on Windows and a stage reported far fewer records than you
expected, or excluded records for "missing" fields you know were populated.
*(F-13, F-38)*

**4. Records could vanish between stages 05 and 06.**
The EH/IH parser accepted repeated `local_id` values but EL silently dropped
them, so a corpus with a duplicated identifier lost rows at stage 06 with
nothing recording which. Where a duplicate survived, its evidence was whichever
copy was processed last. **Re-check if:** your record counts fell between the IH
and EL stages by an amount you did not account for. Duplicates are now recorded
as `duplicate_local_id:<id>` in `data/input_errors.csv`. *(F-55)*

**5. Editing a criterion and re-running could return the old criterion's
answers.** The LLM response cache was keyed on a criterion's *id* but not its
*content*. Refining a criterion's wording while keeping its id — the most common
edit during a live review — and re-running EL or IL served every record the
**previous** wording's decision from cache, complete with evidence quotes taken
against text the model never saw on that run. The interface reported a normal
`cache_hits=N`. The same applied to record text: editing an abstract did not
invalidate a criterion that targeted only the title, even though the model is
sent all three fields. **Re-check if:** you edited criterion wording or record
text mid-review and re-ran a stage with the cache enabled. Re-running now with
the cache on is sufficient to get correct answers, because the key covers
everything the model sees. *(F-01)*

**6. Cancelling a run could produce a bundle that looked complete.**
Cancelling stopped the row loop mid-corpus and returned the records reached so
far as though they were the whole corpus. The exported bundle was
indistinguishable from a complete run over a smaller corpus — and it is the
survivor list that becomes the next stage's input, so every record never reached
was dropped from the review without trace. **Re-check if:** you cancelled a run
and then exported, or continued to the next stage. Cancelled runs can no longer
be exported. *(F-02)*

**7. Cancelling could also replace real answers with fabricated ones.**
Worse than losing work: for the batch in flight, decisions the model had already
returned were overwritten with manufactured `uncertain` verdicts carrying an
internal `error="Cancelled"` marker that nothing displayed. Those verdicts are
indistinguishable in the evidence trail from a genuine model non-answer.
**Re-check if:** you cancelled an EL or IL run and kept or resumed its results —
look for records marked uncertain around the point of cancellation. *(F-26)*

**8. A model that capitalised its answer had every decision rewritten
to "uncertain".** The vocabulary check on the model's `decision` field
was case-sensitive while the check two statements later was not, so a
model answering `Meet` rather than `meet` — or `Not_Meet`, or `not
meet` — had every one of its verdicts silently replaced with
`uncertain`, and the evidence gate then refused all of them. No record
was wrongly excluded by this: the records were flagged for human review
rather than dropped. What was lost is the screening itself, and the
audit trail actively misleads — each record carries `used: true`, a
valid quote and a high confidence beside a verdict of "uncertain", and
the run as a whole looks exactly like one in which the model was unsure
about everything, which is the signature the degenerate-output note in
[`docs/llm-evaluation.md`](docs/llm-evaluation.md) tells a reader to
interpret as a lazy model. Local models are the most exposed, having the
weakest format discipline and no `response_format` to hold them to it.
**Re-check if:** a run flagged far more records than you expected, or
flagged every record, and you were not using an OpenAI model. Decisions
are now matched with case and separator folded; a value outside the
vocabulary is rejected and counted rather than silently replaced, and a
rejected decision is never cached. *(F-90)*

**9. A network failure could become a permanent verdict.** Every entry
of a stage's result map was written into the response cache, including
the entries that record a failure rather than an answer: a transient
500, a timeout, an authentication blip or a model refusal was stored
under a key that matches on every later run. Re-running — the obvious
remedy — is precisely the action the cache defeats, because the second
run reads the stored failure back instead of calling the model. The
direction of harm is safe: a failure reads as `uncertain`, so the record
was flagged for human review rather than excluded. What it costs is
review effort, and the truthfulness of a trail in which a server error
is indistinguishable from a model that genuinely could not decide.
**Re-check if:** you screened during a provider outage or a run reported
failures, and a later re-run returned the same uncertain verdicts
without calling the model. Failures and refusals are no longer written
to the cache. This fixed the writing, not the reading: entries already
present in a bundle were deliberately left untouched, because silently
discarding a user's accumulated cache would be its own data loss. See
item 18 for what now happens to them. *(F-87)*

**10. A stage that screened nothing reported every record as cleanly passing.**
If a stage ended up with no enabled criteria — including because its only
criterion was rejected for the blank-`type` reason in item 2 — it assigned
`PASS_CLEAN` to every record and reported all of them as survivors. `PASS_CLEAN`
is the stronger of the two survivor labels: it asserts every criterion was met,
by a stage that evaluated none. **No record was wrongly excluded by this** — the
stage excluded nothing — but your report asserts those records were screened and
passed when they were never examined. **Re-check if:** any stage's report shows
every record as `PASS_CLEAN` with no exclusions. Such records are now labelled
`NOT_SCREENED`. *(F-34)*

**11. Agreement statistics could be wrong.**
In `tools/eval_ingest.py`, rater pairs whose labels were not recognised were
dropped from the confusion matrix but still counted in the denominator,
deflating Cohen's and Fleiss' kappa. On a 50-pair fixture with ten unrecognised
labels, kappa read 0.362 instead of 0.400, with no warning. A tie between raters
also emitted a non-canonical `uncertain` code that fed this path. **Re-check
if:** you reported human-vs-LLM agreement figures — recompute them. The tool now
fails loudly on an unrecognised label instead of quietly miscounting. *(F-06,
F-07)*

**12. The record of what was dropped as malformed did not survive the pipeline.**
Citations discarded for being malformed were written to `data/input_errors.csv`
in three mutually unreadable formats, and the EL stage deleted the file outright
on any run where EL itself dropped nothing. This does not change which records
were screened, but it means **you may be unable to reconstruct your PRISMA
exclusion counts** from an exported bundle. **Re-check if:** you need to report
how many records were excluded as unparseable. That figure may be missing rather
than wrong. *(F-03)*

**13. EL/IL bundles failed their own integrity check.**
Both stages overwrite `data/current.csv` on export but never updated the
manifest's SHA-256 digests, so a bundle that had passed through EL or IL
recorded a hash that did not match the file it named, and nothing verified it.
No screening result is affected. But if you verified a bundle's digests and they
matched, that check was not meaningful, and if they did not match, that was this
defect rather than evidence of tampering. *(F-05)*

**14. The record of what was dropped could be written in a form nothing can
read.** A `csv` writer used for `data/input_errors.csv` did not quote a field
containing a lone carriage return, so a citation dropped for being malformed —
if its own text carried a stray CR — produced a file that the standard CSV
reader refuses to parse. The reader then swallowed that failure and reported an
empty list, so the bundle said no citations were dropped rather than saying it
cannot tell. No screening result is affected; the exclusion trail is. Both
halves are fixed: the writer now quotes such fields, and an existing,
unreadable audit file raises a visible error — the export refuses rather than
silently dropping the prior rows, and the stage views show a warning instead of
"0 rows". One related site remains open by design: the EH/IH *report* CSVs keep
their old line terminator until the deliverable-format wave (F-79), because
changing it moves golden bytes — that residual cannot affect
`input_errors.csv`. **Re-check if:** you need to report how many records were
excluded as unparseable from a bundle exported by an earlier version and your
corpus came from a source that mixes line endings. *(F-67, F-68)*

**15. The final workbook's four stage sheets have always been empty.**
`reports/ScreenA_Report.xlsx` carries five sheets: one per stage plus FINAL. The
four stage sheets were built with a column header and a row builder that were
written against different schemas, so every data cell has always come out blank.
The row *count* was right, which is why this was not noticed — the sheets looked
populated until a cell was inspected. The FINAL sheet's outcomes were unaffected.
Fixed: the sheet header is now the row builder's schema, pinned identical by
test, and the two columns that never had a data source (`decided_at`,
`history`) are gone rather than shipped empty. The workbook has its first test
coverage. **Re-check if:** you used the per-stage sheets of a
`ScreenA_Report.xlsx` exported by an earlier version — those cells were blank;
the per-stage `reports/*_FULL.csv` files carry the same information and were
always correct. *(F-69)*

**16. The final workbook's FINAL sheet had no metadata for excluded records.**
The FINAL sheet lists every record with its per-stage outcome, and those
outcomes are correct. But its title, abstract and keyword columns were filled
from the record table as it stands at the *end* of the pipeline, so every record
excluded at EH, IH or EL appeared with the right verdict and no way to tell
which citation it is. Fixed: the Harmoniser now writes `data/original.csv`, a
pre-screening snapshot of the corpus that survives every stage, and the FINAL
sheet fills its metadata from that. One honest caveat: a bundle created
*before* this fix has no snapshot, so a final report rebuilt from an old bundle
still falls back to the survivor set and still lacks metadata for
early-excluded records — re-ingest through the Harmoniser to get a complete
one. **Re-check if:** you used the FINAL sheet of an earlier version to write
up exclusions. *(F-70)*

**17. Running a stage with "Use cache" unticked deleted the bundle's
cache.** The export writer excluded the cache file from the copy loop
whether or not it was writing a replacement, so a single run with the
box unticked silently discarded every answer the bundle had accumulated.
No screening result is affected, and a re-run regenerates the cache at
the cost of calling the model again for the whole corpus. The audit
trail is affected: the manifest's SHA-256 map kept its entry for the
now-absent file, and the bundle's integrity check could not see the
problem, because it verifies only members that are present — so the
bundle asserted a digest for a file it no longer contained and reported
itself intact. **Re-check if:** a bundle you exported has no cache
member, or is smaller than you expected, and you ran a stage with "Use
cache" unticked. The cache file is now skipped only when a replacement
is actually being written. *(F-104)*

**18. Caches written by earlier versions are no longer consulted, and
that is deliberate.** Item 5 widened what the cache key covers; this
release widens it again to include the endpoint the answer came from, so
that a run against a local server can never be served an answer produced
by a different provider. The consequence is that every cache entry
written by an earlier version is now keyed under something this code no
longer computes, and none of them will be read. Nothing is deleted: the
old entries stay in the bundle and are carried into every bundle it
produces, so the cache file does not shrink. What you will see is a
re-run that reports `cache_hits=0` and calls the model for the whole
corpus where the previous run cost nothing — correct behaviour
presenting as a regression, which is the only reason it is on this list.
It is also the remedy for item 1: a cache entry poisoned before that
defect was fixed can no longer be served by any code path, so an old
cache does not need to be distrusted. It needs only to be re-filled.
*(F-89, F-143)*

**What cannot be determined.** For item 1 there is a test that can
clear a verdict but none that can convict one. If the quote filed
against a record occurs nowhere in the corpus except that record's own
text, then no substitution could have produced it — a check that runs
offline, over a bundle, with no API key. The converse does not follow,
because nothing in the artefacts ties a verdict to the call that
produced it: a stored answer carries no batch, no call identifier and no
timestamp, and its key is computed from the record the answer was filed
*against*, so a fabricated verdict and a genuine one are written to
indistinguishable places. Applied to the 254 cache entries this project
ships with its published validation study, the check clears **175**
outright and leaves **70 undecidable** — short, generic keyword
fragments such as "Computer science" that recur across a bibliographic
corpus, which is precisely the population in which a substitution could
have survived the evidence gate at all. The remaining **9** failed that
gate, so whatever produced them they cannot have removed a record —
and, examined individually, none of them shows the signature of a
substitution either: six quote text that appears nowhere in the corpus
at all, two quote their own record's title bar one letter's case, and
one quotes text its own record does contain.
Narrowed to the five verdicts that actually removed a record from that
study, four are provably not products of this defect and one — record
`A452` on criterion `IC-1` — is undecidable, and will remain so. The
same check can be run against your own bundle, and the same limit
applies to it.

Not on this list, deliberately: no released version applied a criterion that had
been switched off in the criteria table. That was investigated during this wave
and ruled out — the disabled flag is honoured at load, before any stage
evaluates anything.

### Fixed
- An LLM answer is accepted only for a record the call actually carried
  (F-86). The acceptance guard checked the returned `a_id` against a map
  built from the whole item list before batching, so an answer naming a
  record in a *different* batch was admitted, and the quote was then
  validated against that record's own text — producing a well-formed,
  fully evidenced exclusion from a call whose prompt did not contain the
  record it excluded. See item 1 above; this is the one defect in the set
  that can remove a record from a systematic review on evidence belonging
  to another record. The acceptance map is now built per batch, inside
  the loop and per attempt, and supplies both the guard and the
  quote-validation text, so neither can reach a record the call did not
  send; the parse-loop write is guarded the way the back-fill already
  was, and the first answer for an id wins. Both routes were reproduced
  before the fix, including the persistence half — a second run replayed
  the fabricated exclusion from cache at zero API calls.
- Failures and refusals are no longer written to the response cache
  (F-87). The write-back merged every entry of the result map with no
  filter on `used` or `error`, so a transient 500, a timeout, an auth
  blip or a refusal was stored as a verdict and served on every later
  run — making re-running, the user's natural remedy, precisely the
  action that could not clear it. One shared predicate now gates both
  stages' writes. Write-side only: entries already in a bundle are
  carried through untouched, because silently discarding an accumulated
  cache would be its own data loss (see item 18 above for what now
  happens to them).
- The model's `decision` value is matched with case and separator folded
  (F-90). The whitelist was case-sensitive while the `field` check two
  statements later was not, so a model answering `Meet` rather than
  `meet` had every verdict rewritten to `uncertain` and refused by the
  evidence gate — an internally contradictory record carrying `used:
  true`, a valid quote and a high confidence beside a non-answer, with
  no log line and no count anomaly to mark it. The widening cannot
  invent a verdict: only a string reducing exactly to a vocabulary
  member is accepted. Rejections are now stamped on the record and
  summarised per criterion, and a rejected decision is never cached —
  without which a cached rejection would emit its warning once and never
  again.
- Running a stage with "Use cache" unticked no longer deletes the
  bundle's cache (F-104). The writer added the cache member to its skip
  set unconditionally, so when no cache text was supplied the incoming
  member was excluded from the copy loop and never re-written. The
  general rule — skip only what is being replaced — now covers it. The
  digest map's inability to notice an absent member it still asserts a
  hash for is a separate, general defect and is tracked as its own row
  rather than closed here.
- The manifest records which engine produced each LLM run (F-88). Across
  the codebase the key `"model"` occurred exactly once, inside the
  hashed-and-discarded JSON of the cache key: not the manifest, not the
  history entry, not the cache value, not any report column. A finished
  bundle could not be attributed to a model, a provider or an endpoint
  after the fact, which made the FAQ's advice to pin a prompt version in
  the bundle manifest unperformable. Each LLM stage's
  `manifest.pipeline.history[]` entry now carries a `provenance` block:
  model, resolved endpoint, temperature, prompt version, truncation
  limit and batch size. Recorded per run, from inside the engine — the
  only layer that knows the resolved endpoint — and omitted rather than
  zero-filled when a stage consulted no model. Truncation is in the set
  deliberately: "the model answered" and "the model was shown something"
  are different claims, and a negative truncation limit empties the
  fields it should shorten while leaving the run report identical to a
  healthy one. Old bundles load unchanged and gain no invented
  provenance.
- The documentation no longer implies that pip installs include the sample
  data (F-83). The samples were described as "bundled" while no
  distributable contains them: the `[tool.setuptools.package-data]` entry
  for the old sample folder was a no-op — package-data applies only to
  packages selected by `packages.find`, which names `metascreener*` and
  `plugins*` — verified against the built 3.1.0 wheel and sdist, which
  contain no sample paths. Per the wave-5 decision the samples stay
  repository-only: the installation guide, README and usage guide now say
  they ship with a source clone or download and are absent from a PyPI
  install, and the dead package-data line is gone (removed with the F-54
  rename).
- The `data/input_errors.csv` writer now quotes a field containing a lone
  carriage return (F-67). With the old line-terminator setting the csv module
  left such a field unquoted, so a dropped citation whose text carried a stray
  CR produced an audit file the standard CSV reader refuses to parse — an
  audit trail destroyed by the very content it exists to record. The EH/IH
  report CSVs keep their old terminator until the deliverable-format wave
  (F-79, golden-touching); the two legacy button writers are gone under F-74.
- An unreadable `input_errors.csv` now raises instead of reading as empty
  (F-68). The reader caught every exception and returned an empty list, so an
  existing audit file that could not be parsed reported "no records were
  dropped" — the false negative that let F-67 go unnoticed. Absent or empty
  still means empty; unreadable raises a typed error, the bundle export
  refuses loudly before writing any output, and the stage views surface a
  warning instead of "0 rows".
- One dropped citation is one row of `data/input_errors.csv`, at every hop
  (F-71). EH and IH merged the carried-forward rows into their own skip list
  and the export writer stamped everything with the current stage, so a single
  record dropped at the Harmoniser grew to two rows after EH and three after
  IH — with the ragged-row diagnostics present on the original and absent on
  every copy. Prior rows now pass through verbatim, only this stage's own
  drops get its stamp, re-running a stage is idempotent, and the run counts
  no longer inflate `SKIPPED_INVALID` with other stages' history.
- Every exported bundle now contains `data/input_errors.csv`, header-only when
  nothing was dropped (F-75). Both bundle writers gated the file on being
  non-empty, so a clean corpus produced no file at all and a reviewer could
  not tell "nothing was dropped" from "not recorded". A file that exists and
  says no records were dropped is a different claim from no file, and only
  the first one is auditable. Bundle-shape change: one new member in every
  exported bundle.
- EL and IL reject ragged corpus rows the way EH and IH always have (F-72).
  Their reader padded a short row and truncated a long one to the header
  width, so the same `data/current.csv` yielded different record sets
  depending on which stage opened it, and the silent repair left nothing in
  the audit trail. Ragged rows now divert to the skip list as
  `bad_column_count` and reach `input_errors.csv`.
- EL and IL decode bundle text through the shared four-encoding ladder
  (F-73). They used a single UTF-8 attempt that replaced every undecodable
  byte, so a cp1252 corpus that screened normally at stages 04–05 had its
  titles and abstracts silently mojibaked at stage 06 — corrupting exactly
  the text the evidence-quote validation compares against.
- The EL/IL "Export input_errors.csv…" buttons write the canonical six-column
  schema (F-74). They carried inline writers emitting the legacy
  `reason,row_json` layout — the last two writers of the schema retired by
  the F-03 fix — so the exported file disagreed with the
  `data/input_errors.csv` of the same name inside the bundle.
- The four stage sheets of `reports/ScreenA_Report.xlsx` carry data (F-69).
  See item 15 above; the header and the row builder now share one schema,
  pinned by the workbook's first tests.
- The FINAL sheet of `reports/ScreenA_Report.xlsx` covers the whole corpus
  (F-70). See item 16 above; the Harmoniser writes `data/original.csv`, a
  pre-screening snapshot digested in the manifest, which no later stage
  touches. Bundle-shape change: one new member in every Harmoniser bundle.
- The CR-to-LF canonicalisation of metadata at the deterministic stages is
  now documented and pinned (F-76). Not a behaviour change: the EH/IH parser
  has always rewritten Windows and bare-CR line breaks inside quoted fields
  to LF, and the committed goldens depend on it — but nothing said so. It is
  now stated in `docs/usage.md`, in the parser, and held by tests.
- A stage with zero enabled criteria no longer reports every record as a clean
  pass (F-34). It assigned `PASS_CLEAN` — the stronger of the two survivor
  labels, meaning "every criterion was met" — to every record and reported
  every record as a survivor, so a stage that did no work was indistinguishable
  from one that ran correctly and excluded nothing. Records now get a distinct
  `NOT_SCREENED` outcome counted in its own bucket, the run summary and status
  line say so instead of "Done.", export requires an explicit acknowledgement,
  and `manifest.pipeline.history[]` records the no-op so a reviewer
  reproducing the pipeline can see it without re-running the GUI. The records
  still pass through to the next stage — not having screened them is no reason
  to drop them.
- EL and IL now refresh the manifest's SHA-256 map on export and verify it on
  load (F-05). Neither did before — the string `sha` appeared nowhere in either
  UI or either standalone shell — while both overwrite `data/current.csv` with
  the stage's survivors, so every bundle leaving EL or IL asserted a digest for
  a file it had just replaced, and nothing downstream checked. A digest that is
  present and wrong is worse than none: it turns an integrity check into false
  assurance. The four near-identical EL/IL export copies are now one shared
  writer, which is what makes the refresh unforgettable. The README claim
  softened in Wave 0 is restored, minus the tamper-resistance it never had.
- `data/input_errors.csv` — the record of which citations were dropped as
  malformed — now has one schema, one writer, and survives the pipeline
  (F-03). It previously had three schemas (one per writer), a reader that
  understood only one of them, and a copy-forward skip in EL that deleted the
  file outright on any run where EL itself skipped nothing. A citation the
  Harmoniser dropped was therefore already invisible by EL, and gone from the
  bundle afterwards. The schema is the Harmoniser's, widened rather than
  narrowed, plus a `stage` column; every stage appends instead of overwriting;
  and reading stays tolerant of all three legacy layouts so existing bundles
  still load. EH's "Imported previous input_errors: … (0 rows)" was the reader
  failing rather than a count, and now reports truthfully.
- A cancelled screening run can no longer be exported (F-02). All four stage
  engines now return a `cancelled` flag alongside their results; the stage UIs
  refuse both the XLSX and the next-bundle export while it is set, and say why.
  Previously the row loop exited mid-corpus and returned the rows it had
  reached as though they were the whole corpus, so an exported bundle from a
  cancelled run was indistinguishable from a complete run over a smaller
  one — and it is the survivor list that becomes the next stage's input. If a
  partial run is written by some other path, `manifest.pipeline.history[]` now
  carries `cancelled: true` and the stage marker reads `cancelled`.
- Cancelling an LLM stage no longer throws away answers already received and
  paid for (F-26). The cancel check raised past `return out`, discarding every
  completed batch; and because the post-call check sat inside the per-batch
  retry block, the generic error handler caught it and rewrote the whole batch
  as `uncertain` with `error="Cancelled"`, replacing real answers with
  fabricated non-answers.
- The LLM response cache key is now derived from a hash of the fully-rendered
  prompt (plus model and temperature) rather than from an enumerated list of
  invocation parameters (F-01). Previously the key carried only the criterion's
  *id*, so editing a criterion's wording while keeping its id produced a cache
  hit: every record was served the previous criterion's answer, with evidence
  quotes taken against text the model never saw on that run, while the UI
  reported a normal `cache_hits=N`. The same omission applied one level down —
  the record text hash covered only the criterion's *target* fields, although
  the prompt ships title, abstract and keywords for every criterion.
- The cache key now also covers the **resolved endpoint** the answer came
  from (F-89). Without it a single bundle pooled answers from every
  provider it had been run against: switch `OPENAI_BASE_URL` from a local
  server to the vendor and the run was served the local model's verdicts
  at `cache_hits=N`, with nothing recording that the two came from
  different engines. An unset variable hashes as the resolved default
  rather than as an empty string, so adding the line `.env.example`
  invites you to add does not throw away a warm cache. The deliberate
  cost is over-discrimination: `http://host/v1` and `http://host/v1/`
  route identically and key differently, which costs a redundant re-run
  — the safe direction, since under-discrimination is the defect itself.
  Every cache entry written before this change is now unreachable; see
  item 18 above.
- A criterion whose `type` cell is blank or unrecognised is now rejected with a
  warning naming its spreadsheet row, in both EL and IL, instead of being
  defaulted to `exclude` (F-04). The default was harmless in EL, which is an
  exclusion stage, and inverted the decision in IL. Rejecting rather than
  defaulting to the stage's own polarity is the safer failure direction: a
  missing criterion is visible in the criteria panel, an inverted one is not.
- Corpus CSVs are read through the shared encoding ladder (utf-8-sig, utf-8,
  cp1252, latin-1) rather than with no encoding argument and a utf-8 fallback
  (F-13, F-38). A cp1252 file previously failed both attempts, and both failures
  were logged and swallowed, leaving an empty corpus; a BOM'd file produced a
  `﻿title` column so every title read as empty.
- The EH/IH corpus parser now skips repeated `local_id` values instead of
  accepting them, matching what EL already did, and records them as
  `duplicate_local_id:<id>` (F-55).
- `tools/eval_ingest.py` raises on an unrecognised rater label instead of
  dropping the pair from the confusion matrix while still counting it in the
  denominator, and `majority_vote` no longer returns the non-canonical
  `uncertain` on a tie (F-06, F-07).
- The API-key dialog accepts any non-empty key instead of requiring the OpenAI
  `sk-` prefix and a 20-character minimum (F-08). The old rule made the README's
  entire "Using local LLM providers" section unreachable: Ollama and llama.cpp
  users are told to set `OPENAI_API_KEY` to a placeholder those servers ignore,
  and both placeholders were refused with no way past the dialog. A key that
  does not look like OpenAI's now gets a grey advisory rather than a refusal.
- Plugin instances are registered with the main window, so the lifecycle hooks
  declared in the plugin API actually fire (F-18). They had all been dead: most
  visibly, closing the window during a Plugin 02 resolve or fetch run left the
  worker thread running, because the hook that cancels it was never called.
- Plugins 01, 02 and 03 expose `make_plugin`, matching the other four and the
  documented contract, instead of the legacy `create_plugin` (F-31).
- The IL standalone row-detail pane is labelled "IL summary" rather than "EL
  summary" (F-50).
- Removed a duplicated assignment in the LLM quote-validation path (F-51).
  Idempotent, so no behaviour change; the byte-identity goldens confirm it.

### Documentation
- Corrected claims in the README and `docs/usage.md` that the code did not
  support (F-16, F-17, F-30, F-37, F-57), including the SHA-256 integrity claim
  (F-05), which is now restored in full because all four stages verify.
- Restored the verbatim MIT licence text and named the copyright holder (F-41).
- Added the DOI to `CITATION.cff` (F-43), aligned the publication status
  (F-44), and used the accented affiliation in `.zenodo.json` (F-45).
- Repaired README mojibake, stripped the LICENSE BOM, re-encoded
  `docs_/samples/ex_ref_2.txt` from cp1252 to UTF-8, and added a CI guard
  against both (F-10, F-42, F-56).
- Added the missing SPDX header to `tools/audit_imports.py` (F-46) and the
  required `--criteria` flag to `eval_ingest`'s usage example (F-58).
- Added the internal diagnostic report under `docs/internal/`, exempt from the
  documentation cross-reference tests (F-29).

### Changed
- The sample-data folder `docs_/` is now top-level `samples/` (F-54). The old
  name was one underscore away from `docs/` — which holds the actual
  documentation — and carried a blanket `.gitignore` rule whose only effect
  was to make files dropped beside the samples invisible to `git status`:
  nothing writes into the tree at runtime, so the rule protected nothing,
  and it is deleted with the rename. Layout change only —
  `docs_/samples/<file>` is now `samples/<file>`, `docs_/README.md` is
  `samples/README.md`; no file content changed. The no-op
  `[tool.setuptools.package-data]` entry for the old folder is gone
  (distributables never contained the samples — see F-83). A regression
  test keeps the old path out of the published documentation.
- The EL/IL cache goldens (`tests/golden/{el,il}_cache_v3.1.0.json`) were
  **re-keyed, not re-captured**, to follow the cache-key change above. The
  stored keys are now hashes of the rendered prompt; the stored values —
  decisions, confidences, evidence quotes and spans — were copied verbatim
  from the previous goldens. No API call was made and no decision was
  recomputed. 170 EL and 84 IL entries mapped 1:1 onto new keys with no
  collisions and no orphans, and the four files that record decisions
  (`{el,il}_filtered_v3.1.0.csv`, `{el,il}_input_v3.1.0.csv`) are
  byte-identical to their previous versions, which is the check that the
  re-key changed only labels. Any future change to the prompt template or to
  criterion content will invalidate these caches, since the key now covers
  both; that needs a real re-capture via `tools/capture_el_il_goldens.py`.
- The input of the published validation study is frozen under
  [`docs/data/study_input/`](docs/data/study_input/), separately from the
  byte-identity regression fixtures it was copied from (F-98). One pair of
  files had been serving both roles, and the two have opposite maintenance
  rules: a fixture is *meant* to be re-captured when the behaviour it
  guards legitimately changes, while a cited dataset must never change. So
  every change to the screening engine silently rewrote the input of a
  published analysis, and `docs/llm-evaluation.md` would have gone on
  claiming byte-for-byte reproduction while producing different numbers.
  The document now reads from the frozen copies, which are pinned by
  digest and re-verified on every test run — as is the reproduction claim
  itself, by re-running the published command and comparing its output
  with the committed results. No number in the study changes; the fixtures
  under `tests/golden/` are now free to move without touching it.
- **A run in which the model answered too little now asks before you export
  it.** For every record-criterion pair it sends, metaScreener already recorded
  whether the model came back with something it could read — but that number
  went into the bundle's manifest and nothing looked at it. A run in which the
  model declined most of what it was shown could therefore finish, report
  *"EL done."*, and export with no question asked; one of this project's own
  measurement runs did exactly that, with 33 of 170 pairs unanswered. If more
  than 10% of the pairs come back unreadable, the stage now says so on its
  status line and asks you to confirm before either export — the same
  acknowledgement a stage with no criteria has always required. **Nothing is
  blocked and no button is disabled**: you can still export, and the dialog
  tells you how much came back unreadable, what that usually means, and where
  to read a sample of what the model actually sent. A run whose answer rate is
  healthy is unaffected, and a run in which the model was never heard from at
  all keeps its own, more specific message.
- **Batch size no longer changes which records get screened.** A controlled
  comparison — same corpus, same criteria, same model, only the batch size
  differing — showed a local model answering 17 of 294 record-criterion pairs
  at batch size 1 against 241 of 294 at batch size 5, because at a batch of
  one a correct “none of these match” reply is an empty list, which the
  pipeline could not read as an answer. Requests to the model now carry a
  JSON schema that requires exactly one verdict per record sent, so an empty
  or partial reply stops being something the model can produce; a record
  still left out is asked for again once, on its own, and anything
  unanswered after that is counted and reported rather than silently marked
  unresolved. **If your server does not support structured output**, the run
  falls back to the previous request shape after one attempt, says so in the
  log, and records which shape it used in the bundle's manifest. The
  batch-size tooltip no longer calls the setting “a quality setting, not a
  correctness one” — the comparison above is the measurement that retired
  that sentence — and it now warns that cached decisions are reused across
  batch sizes, so re-running at a different batch size is not an independent
  second opinion. The evidence behind the comparison is committed under
  `docs/data/wave14c_batch_runs/`, and the cached-answer fixtures were
  re-keyed (values untouched, proven by the committed migration tool) to
  keep old unconstrained answers from being served to constrained runs.
- **The batch-size trade is now measured on the fixed request, and the
  tooltip states it in numbers.** With the schema-constrained request, every
  batch size answers every record — and a four-run comparison showed larger
  batches inventing exclusion verdicts the records do not support, at a rate
  that grows with the batch: none in 294 judgments at batch size 1, about 5%
  at batch size 5, 6.1% at batch size 10, on records that vary run to run.
  Under the default flag-only policy those show up as suppressed exclusions
  for your review rather than acting on anything. Batch size 1 was the
  measured-clean setting at five times the requests of batch 5; the tooltip
  beside the box now gives you these numbers and leaves the choice with you.

## [3.1.0] - 2026-04-29

### Added
- Citation File Format metadata (`CITATION.cff`)
- Pre-filled Zenodo deposit metadata (`.zenodo.json`)
- This changelog
- SPDX license headers in all source files
- Human-vs-LLM agreement validation infrastructure (`tools/eval_grid_generator.py`,
  `tools/eval_ingest.py`) with pure-Python Cohen's and Fleiss' kappa computation,
  exercised against textbook reference values and edge cases in
  `tests/test_eval_ingest.py`
- Persistent archive of validation evidence under `docs/data/`: empty grids,
  partition manifest, filled grids from all three raters, joined human + LLM
  decisions, agreement summary, per-(stage, criterion) confusion matrices, and
  the 88-row disagreement subset
- Validation methodology documentation (`docs/llm-evaluation.md`) with full
  polarity-aware status-mapping table and reproducibility instructions
- Installation guide (`docs/installation.md`) covering the PyPI and source
  installation paths
- Top-level documentation landing page (`docs/index.md`) cross-linked from README
- End-to-end usage walk-through (`docs/usage.md`) with annotated per-plugin
  screenshots under `docs/images/usage/`
- Frequently asked questions document (`docs/faq.md`) with documentation
  cross-reference test coverage in `tests/test_metadata.py`

### Changed
- Bumped version to 3.1.0 for peer-review revision release
- Stripped UTF-8 BOMs from text files
- Translated remaining French inline comments to English
- Renamed Python package `prisma_hub/` → `metascreener/` for naming consistency
- Renamed application class `PrismaHubApp` → `MetaScreenerApp`
- Renamed PyInstaller spec files: `PRISMA Hub.spec` → `metaScreener.spec`, `PRISMA Hub (console).spec` → `metaScreener-console.spec`
- Renamed Plugin 01 folder to `plugins/01_reference_extractor/` and flagged as experimental
- Plugin 01 UI tab now labeled with explicit `(experimental)` scope warning
- Plugin 01 frame now displays an experimental scope banner
- Rater grid generator (`tools/eval_grid_generator.py`) writes rater workbooks
  with verbatim criterion text in dropdown options and YES/NO/uncertain natural-
  language vocabulary, and deliberately strips the LLM-evidence columns from
  input filtered CSVs so that raters are blind to the LLM's per-record decision
  (guarded by `test_decisions_sheets_do_not_expose_llm_columns`)
- LLM-status-to-canonical-decision mapping in `tools/eval_ingest.py` is now
  polarity-aware: `MET`/`FAILED` map to canonical `yes`/`no` for inclusion
  criteria and invert to `no`/`yes` for exclusion criteria, so that humans and
  LLM are compared on a single canonical "does the criterion's claim hold?"
  scale
- Manuscript figures (Figure 1 pipeline architecture, Figure 2 screening funnel)
  rebuilt to fix legend-overflow and text-clipping issues raised by Reviewer 2
- Manuscript Quality control section: demonstration-vs-validation wording
  reconciled; new "Human validation" subsection added reporting per-criterion
  Cohen's and Fleiss' kappa, observed agreement, prevalence-paradox
  interpretation, asymmetric-hedging finding, and an explicit limitations
  paragraph
- Manuscript Introduction: related-work paragraph added acknowledging an
  unrelated tool of the same name (Hong, 2025)
- Manuscript: new Figure 3 added showing the Criteria Parser desktop interface
- Manuscript Reuse potential: expanded with concrete plugin-extension examples
  and external-data-source integration points

### Fixed
- Removed hardcoded developer-machine venv path (`S:\prisma-hub\.venv\…`) from PyInstaller spec files

### Removed
- `plugins/_parking_lot/` (historical drafts folder, retained in git history)
- Timestamped backup `.py` files in `prisma_hub/` and `plugins/*/` directories

### Deferred

- Per-plugin `screen.py` files contain stage-tuned copies of helpers
  (`_safe_str`, `_decode_bytes`, `_load_bundle`, etc.) that overlap
  with `plugins/_common/` versions. Substitution would require a
  unified `_common/parser.py` + `_common/bundle.py` whose behavior
  preserves all four stages' (EH, IH, EL, IL) byte-identity goldens
  simultaneously. Deferred pending broader empirical experience
  across diverse corpora.
- Per-stage running-time estimation in the UI (Reviewer 2 optional item O4);
  requires per-model latency profiling not yet completed across supported
  providers.
- UI exposure of per-criterion confidence threshold (Reviewer 2 optional item
  O5); the threshold mechanism exists internally in the harmonized criteria
  CSV but interactive UI exposure requires confidence-calibration work not yet
  completed.
- Pipeline video walk-through (Reviewer 2 optional item O6); deferred until
  post-acceptance so that on-screen text matches the final published
  manuscript and documentation.

## [3.0.1] - 2026-04-04

Initial GitHub-tagged release. See https://github.com/lars-ulaval/metaScreener/releases/tag/v3.0.1
