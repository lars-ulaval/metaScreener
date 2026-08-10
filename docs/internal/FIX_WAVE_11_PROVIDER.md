# Fix wave 11 — the provider choice

Branch `fix/wave-11-provider-choice`, cut from `c6b0f77` (`main`, tagged
`post-wave-10`). **Additive: no golden moved**, verified two ways.

**The wave ran as three sessions**, proposed after step 0 and agreed before any
code was written. This document was written as the sessions landed. F-140 moved
from session B's column to session C's, where its per-stage neighbours were —
the row is recorded against the session that closed it.

| | Session A — foundation | Session B — startup | Session C — controls |
|---|---|---|---|
| Findings | F-116, F-117, F-121, **F-144** (opened) | F-91, F-144 (closes), D1, D3, D7, D8 | **F-118**/D9, **F-140**, D6, F-91's per-stage surface |
| GUI diff | **none** | the popup, launch order | every stage tab |
| Status | **complete** | **complete** | **complete** |

The seam differs from the brief's guess in three places, and the reasons are the
same one: everything the GUI stands on should exist and be tested before a widget
depends on it. **Discovery** moved into A (same call, same fake-server shape as
detection — only the combobox belongs in C); **F-117** moved into A (both B's popup
and C's run buttons rest on the unified predicate, and it is what the wave-8 state
model must absorb); **F-121** moved into A because it is independent, cheap, and
otherwise the thing that slips.

---

## 0. Gate

| Check | Result |
|---|---|
| HEAD | `c6b0f77`, `main`, tagged `post-wave-10` |
| Status / sync | clean, 0/0 |
| Gap commits | none |
| Golden manifest | 9 files recorded |
| Suite baseline | **794 passed, 5 skipped** |

---

## 1. Disagreements with the brief

### 1.1 F-92 has no GUI half — it is already closed

The brief scopes "F-92's GUI half". F-92's Effort cell is **`XS (done)`**, fixed in
`3703abd` in wave 9, and its subject was endpoint *routing* — reading
`OPENAI_BASE_URL` explicitly and passing `base_url=` to the client. It has no GUI
component.

The endpoint's GUI surface is **F-91**, whose own fix cell says exactly that: *"One
Entry plus a read at `plugins/_common/llm_client.py::_openai_client_for`."* F-91 is
High, open, and already in scope. Raised at step 0; **the coordinator accepted the
correction and assigned F-91 as owner.** Nothing was opened and nothing is lost.

### 1.2 The fake-server idiom the brief points at does not exist

The brief instructs: *"the stdlib `http.server` idiom in
`tests/test_cancellation.py` is the pattern."* **`tests/test_cancellation.py`
contains no `http.server` usage, and neither does any other file under `tests/`.**
The pattern was established in `tests/test_provider_detect.py` instead:
`ThreadingHTTPServer` on `127.0.0.1` port **0**, so the OS allocates a free
ephemeral port, nothing leaves loopback, and there is no fixed 11434 to collide
with a developer's real Ollama.

### 1.3 F-117 carries three items, not one

The brief describes only the predicate split. The row also covers the IL golden
being weaker than EL's, and the missing `PROMPT_HASH_TRUNC_CHARS ==
_invocation["trunc_chars"]` assertion, and says one commit closes all three. Both
extras were taken; it took two commits, split by kind — one code defect, two
fixture observations.

### 1.4 Wave 9 assigned this wave four `.env` defects the brief does not mention

`_save_env_key`'s docstring names them: the read-modify-write needs a cross-process
lock (*"which is wave 11's"*); the filter matches a literal prefix while the loader
splits-and-strips, so `OPENAI_API_KEY = x` and `export OPENAI_API_KEY=x` survive it
and win on reload; a BOM hides the line the same way; and the value is written
unescaped, so an interior newline splits it.

**Three of the four are retired rather than fixed**, which is the better outcome:
once the store is the write target, no parsing of `.env` remains on the write path.
That was the coordinator's decision, taken at step 0 — the API key moves to the
store, and `.env` stays readable as a source-run input but is never written. The
fourth, the lock, is **deliberately not implemented** — see §2.4.

---

## 2. F-116 — settings that survive a launch (`4a50a1f`)

### 2.1 The frozen-build answer, and why it became its own row

The brief asked whether `.env` works in the frozen build rather than assuming. It
does not, in either direction, **and the write fails silently**:

* the spec is **onefile** — `EXE(pyz, a.scripts, a.binaries, a.datas, …)` with no
  `COLLECT` — so the bundle unpacks at runtime into a temporary directory named by
  `sys._MEIPASS`;
* `metascreener/main.py:324` computes `project_root =
  Path(__file__).resolve().parents[1]`, which under onefile **is** that temporary
  directory. `main.py` is not frozen-aware; `plugin_manager.py:40,46` reads
  `sys._MEIPASS` precisely because it must, so the omission is specific to this
  path;
* `.env` is not among the spec's `datas`, so the read finds nothing and returns
  silently — no prefill, ever;
* the write **succeeds**, into the directory PyInstaller deletes on exit.
  `_save_env_key` reports `ok=True`, no warning is shown, and the key is gone next
  launch.

That is **F-139's own failure mode — a persist indistinguishable from one that
worked — reintroduced by packaging**, and invisible to F-139's fix, which verifies
that *the write succeeded*, not that *the location survives*.

**Filed as F-144, High**, at the coordinator's instruction, because the mechanism
generalises: any future code writing anywhere inherits the same blind spot, and
nothing in the repository currently distinguishes a durable path from a temporary
one. `04_frozen_build.md` does not mention `.env` at all.

### 2.2 Where the store lives, and why not `metascreener/`

`plugins/_common/settings.py`. Both the application and the plugins must read it,
and `plugins` is a real package on `sys.path` in the app, in the frozen build (the
spec carries `'plugins'` in `hiddenimports` with a `collect_submodules` hook) and
under the test conftest — whereas `metascreener` is replaced by a **stub module** in
`tests/conftest.py:52-54`, so `metascreener.settings` would not be importable from
a test. It imports no tkinter for the same reason.

### 2.3 The write rules, re-implemented rather than inherited

F-139's three properties — symlinks followed, unique temporary, atomic
`os.replace` — are re-implemented here rather than assumed to generalise, because
this is a second writer of a user-authored file with the same shape and **wave 9's
review caught its first attempt reintroducing its own defect class via symlinks**.
The symlink rule is asserted directly.

One rule is stricter: the file may hold an API key, so it is created `0o600` and an
existing file's mode is preserved rather than widened. One is inherited unchanged:
*absent is not unreadable* — a missing file is the shipped configuration; a file
that exists and cannot be parsed raises and is **never overwritten**, asserted.

Whitespace never wins anywhere: an empty or whitespace-only stage override
**clears** the override rather than storing one that resolves to nothing. That is
F-93's shape.

### 2.4 The limit that is not fixed, and why

The read-modify-write is **not atomic across processes**. `_save_env_key`'s
docstring assigns that lock to this wave. It is not implemented, deliberately: a
lock that is wrong is worse than none, and the realistic trigger is narrower than
the one that motivated it — the settings dialog is modal, where `.env` prompting
happened on every launch and two windows at once was ordinary. Recorded in the
module docstring and in the row rather than silently omitted.

---

## 3. F-117 — one predicate, and it asks about the provider (`8162904`, `d8f754b`)

Two predicates over one environment variable: `llm_client._has_openai_key` stripped;
the harmoniser's `_llm_available` used bare `os.getenv` truthiness. With a
whitespace-only key the harmoniser offered to spend money while EL and IL refused.

**Making both strip would have left the deeper defect.** Under D1 a local server
authenticates nothing, so a *presence* check forces the local user to invent a
placeholder credential to pass a gate that exists for a provider they are not
using — which is precisely what the old `NO_KEY` message told them to do, in as
many words. Asking someone to type a fake credential to reach a free local model is
a GUI-first defect wearing a security gate's clothes.

So `key_required(provider)` / `key_ok(provider, api_key)`. An **unknown** provider
is treated as needing a key: refusing costs a click, while guessing that an
unfamiliar endpoint is unauthenticated could leak one or spend money.

`llm_readiness`'s `has_key: bool` is **replaced** by `provider` + `api_key`, and
removed rather than aliased — a caller left on `has_key=` would silently keep the
presence check, and two predicates is the defect being closed, so a `TypeError` is
the cheaper failure. The SDK's non-empty-`api_key` requirement became the
application's problem via `settings::placeholder_key_for`, which never substitutes
for `openai`, where it would turn *you forgot your key* into a vendor 401.

Both existing state suites were **translated, not relaxed**: every `has_key=True`
became `provider="openai"` with a real key and every `has_key=False` the same
provider with none, so they keep pinning exactly what they pinned before.

---

## 4. The wave-8 state model extended cleanly

The brief asked whether it absorbs the new states, and said that if it does not,
that is a finding about wave 8's design. **It does, by the mechanism its author
wrote down.** `READINESS_CODES`' docstring:

> Once an endpoint is a first-class GUI value, three more states become decidable —
> endpoint unreachable, endpoint reachable but the model was never pulled, and a
> keyless server that must not be blocked for want of a key. Each is a new member
> here and a new branch in `llm_readiness`, reached by new keyword arguments; none
> of them changes a state that already exists.

Three of the five states this wave needs are named there. The two that are not —
"Ollama not installed" and "installed but not running" — are the *same decision* as
"endpoint unreachable" (`can_run=False`) differing only in message; because D4/D5
require those messages to be distinct and actionable, they are distinct **detection**
states (§5) whose message the readiness layer will carry, rather than new readiness
codes that decide nothing new. **No finding against wave 8.**

*(Cosmetic: that docstring says "Wave 10 extends this set" for what is now wave 11
— the same wave-number slip as `run_outcome`'s "wave 9's provenance fields".)*

---

## 5. Detection and discovery (`77227f4`)

### 5.1 What detection can establish

Four states, from one HTTP GET plus one `shutil.which`:

| State | Established by | Remedy it names |
|---|---|---|
| `READY` | endpoint answered, ≥1 model | — |
| `NO_MODELS` | endpoint answered, 0 models | pull one (D3) |
| `NOT_RUNNING` | nothing answered, binary present | `ollama serve` |
| `NOT_INSTALLED` | nothing answered, no binary | install, or use OpenAI |

The three failure messages are asserted **mutually distinct**, and two specific
confusions are asserted directly: `NOT_RUNNING` names `ollama serve`, and
`NOT_INSTALLED` must **not** — telling someone to start a server they have not
installed is the wasted afternoon the split exists to prevent.

**The binary check is deliberately secondary.** If the server answers, a local
binary is irrelevant: the endpoint may be a remote Ollama, LM Studio, llama.cpp or
vLLM, which all speak the same wire protocol. `which` only ever discriminates the
*message* when nothing answered. Asserted.

### 5.2 What detection cannot establish

- **Whether a model is any good at screening.** Out of scope by instruction; that
  is wave 12 and needs a live measurement. Nothing in this session's code or
  documentation asserts local screening *quality* — only that the path exists.
- **Whether a reachable endpoint is the one the user meant.** `http://host/v1` and
  `http://host/v1/` route identically and key differently (F-89's recorded
  over-discrimination); detection inherits that and cannot see it.
- **Why a server is not answering.** A firewall, a wrong port and a stopped daemon
  are one state, `NOT_RUNNING`, when the binary is present.
- **Whether a listed model will actually load.** `list_models` reports what the
  server advertises, which for Ollama is what is pulled, not what fits in memory.

### 5.3 Two rules the module never breaks

**It does not require Ollama to exist** — every failure is a *state*, not an
exception, asserted over the cross product of both `which` outcomes and four
malformed endpoints, because a launch path that can raise is a launch path that can
fail to launch. **It does not start anything** (D5): `shutil.which` plus one GET,
with the absence of `subprocess` asserted against the module's **AST** rather than
its text — a raw substring search matches the docstring that *explains* the rule, so
the documentation would have broken the check enforcing it.

### 5.4 One request, not two

An availability probe followed by a list call doubled the latency on a launch path
and could observe different states either side of a server starting. `_fetch_models`
is tri-state instead: `None` means *did not answer usably*, a tuple means it
answered and may be empty — the distinction `NO_MODELS` and `NOT_RUNNING` rest on.

Two performance corrections found while writing the tests: `serve_forever`'s
`poll_interval` defaults to 0.5s and `shutdown()` waits for it, half a second of
dead time per test; and the double request above. Together 9.7s → 5.0s for the file.

---

## 6. The startup flow, as it stands before session B

`metascreener/main.py::MetaScreenerApp.__init__`, in order: Tk root (318); title and
geometry (319–321); `project_root` from `__file__` (324); `env_path` (325);
`_load_env_file` (328); then

```python
331    if not self._prompt_api_key_always():
332        self.after(0, self.destroy)
333        return
```

**The notebook is created at 336, plugins load at 340, bindings at 342–343** — all
after the return. So the brief's claim is confirmed: `__init__` returns three lines
before `self.nb` exists.

Three consequences the replacement must not inherit:

- `self.nb`, `self._plugins`, the `<<NotebookTabChanged>>` binding and
  `WM_DELETE_WINDOW` are **never assigned**. `_on_close` iterates `self._plugins`
  and would raise `AttributeError`, unreachable only because the protocol it hangs
  off was never bound;
- **no plugins load at all**, so cancelling a *key* dialog costs the user stages
  03/04/05, which need no model of any kind. That is the substantive defect, larger
  than "the app exits";
- `_prompt_api_key_always` returns `False` on `not dlg.value` (351), so an empty
  string and a cancel are one path. There is no "continue without a key" branch
  anywhere.

*After* is session B.

---

## 7. Human observations

**None from this session.** Everything decided here was decidable from source or
from a headless test; the rendering questions belong to sessions B and C. The
register's older deferred HOs were not chased.

---

## 8. New rows

**One: F-144** (High, packaging / correctness) — §2.1. No other rows opened.

---

## 9. Session A close-out

### 9.1 Goldens

| Check | Result |
|---|---|
| Per-file SHA-256 vs the step-0 manifest | **9/9 identical** |
| `git diff main...HEAD -- tests/golden/` | **empty** |

### 9.2 Suite

| | Passed | Skipped |
|---|---:|---:|
| Step 0 | 794 | 5 |
| Session A close | **869** | 7 |

**Delta +75 passed, +2 skipped, all new; no test deleted, two suites translated:**

- +22 `tests/test_settings_store.py` (2 of them skipped on Windows — POSIX
  permissions and symlink privileges)
- +33 `tests/test_provider_readiness.py` (22 for the predicate, 11 more pinning
  the five regressions of §10)
- +18 `tests/test_provider_detect.py`
- +4 across `tests/test_{el,il}_regression.py`
- `tests/test_llm_readiness.py` and `tests/test_stage_state.py` translated to the
  new `llm_readiness` signature — same count, same assertions

### 9.3 Tools

`audit_imports`, `audit_decorators`, `check_encoding` (180 paths) and
`rekey_cache_goldens --verify` all clean.

### 9.4 What a user can now do that they could not before

**Nothing yet, at the GUI.** Session A is foundation: it changes no widget and no
launch behaviour. What it changes is what the next two sessions can rest on — a
settings store that survives a launch *and* the frozen build, one readiness
predicate that understands providers, and detection that tells three failures apart.
The one user-visible change is documentation: `docs/installation.md`'s smoke test
can now be followed.

**Everything still requires an OpenAI key.** Not, as an earlier draft of this
section claimed, "because nothing yet reads the store at launch" — that was false
the moment the readiness call sites began reading it, and the review pass caught
it (§10.1). It is true because the shipped provider is `UNCHOSEN` until something
writes a real choice, which is session B's job.

### 9.5 Bookkeeping slip, recorded

**F-144's register row rode in `77227f4` (detection) rather than standing alone.**
The ground rule is one commit per finding; a register row is bookkeeping rather than
a fix, and normally travels with the wrap-up. Harmless and traceable — the row is
filed correctly and the commit message does not claim otherwise — but it is a miss,
and the tip was not rewritten to hide it.

### 9.6 Commits

| Hash | Subject |
|---|---|
| `4a50a1f` | `fix(F-116): LLM settings that survive a launch` |
| `8162904` | `fix(F-117): one key predicate, and it asks about the provider` |
| `77227f4` | `feat(D4, D5): detect a local provider without starting anything` |
| `d8f754b` | `test(F-117): close the row's other two items` |
| `3acc167` | `docs(F-121): a smoke test that can actually be followed` |

### 9.7 Register

**141 rows, 65 closed, 76 open** (from 140 / 62 / 78). Closed this session: F-116,
F-117, F-121 — all Medium. Opened: F-144 (High). Totals regenerated by derivation
from the Effort markers, with the script first checked to reproduce the published
wave-10 figures unchanged.

---

## 10. The review pass

Refute-first, three lenses — the settings writer, the predicate change, detection.
**19 findings raised; four real and fixed in `7317675`; one further regression I
caught myself before the reviewers reported (`a17d3b8`).** Five real defects in a
session of five commits, all of them introduced by this session, which is the
pattern waves 9 and 10 both showed and the reason the pass is mandatory.

### 10.1 An unconfigured install was silently "local", and still billed

The worst of the wave so far, and worse than the one I caught.

`defaults()` shipped `provider="local"`, reasoning that D1 preselects local. **D1
preselects it *in the popup*; it is not the effective configuration before the
popup exists.** Because `key_required("local")` is `False`, a fresh install waived
the key gate at every layer — while nothing read `settings["endpoint"]`, so the
request still went to `resolve_openai_base_url()`. Verified by execution, not
argument:

```
store provider    : local
store endpoint    : http://localhost:11434/v1
resolved endpoint : https://api.openai.com/v1
credential sent   : 'local'
engine gate open  : True
```

So a run the store called *local* went to the paid vendor with the literal string
`"local"` as the credential — or, since the launch modal cannot be dismissed
without a key, **with the user's real key, billing their account for a run
labelled local.** Before this session that user was correctly blocked at `NO_KEY`.

Fixed in two halves: the provider is `UNCHOSEN` until something writes a choice,
and `resolve_openai_base_url()` now actually reads the stored endpoint — store
first, ahead of the environment, because a stale `OPENAI_BASE_URL` beating a GUI
choice would make the control the user just operated do nothing, which is F-91's
family of defect. An unconfigured install reduces to exactly the previous
expression, which is what keeps the golden replays valid.

**This also falsified §9.4 of this brief**, which asserted the opposite. Corrected
rather than quietly amended: a wrap-up that misdescribes the code is the same
class of failure as the code.

### 10.2 A corrupt settings file deleted both screening tabs

`load_settings` raises on an unparseable file, and the EL/IL readiness call runs
inside `_build_ui` — where `main.py::resolve_plugin_entrypoint` swallows every
exception into a `print()`. A JSON typo therefore removed the EL and IL tabs with
no message at all, and in the windowed onefile build stdout goes nowhere. Readiness
now degrades to unconfigured, which blocks the run for a stated reason rather than
deleting the stage.

### 10.3 The container was validated and its entries were not

`load_settings` checked that `stages` was a dict and not that its entries were, so
a structurally wrong file passed the documented gate and crashed later with an
unrelated exception type instead of `SettingsUnreadableError`. A non-string
`provider` raised `AttributeError` inside `key_required` on the same construction
path as §10.2.

### 10.4 The harmoniser's client ignored everything this wave built

`_call_openai_json` still constructed a bare `OpenAI()` — no key, no base URL. Once
`_llm_available` admitted a keyless local provider, the predicate said yes for
exactly the configuration that constructor cannot build for: the button went live
and the call failed into an `except` that falls through to the removed 0.x API. It
also meant the harmoniser ignored the endpoint EL and IL honour. One client builder
now serves all three.

### 10.5 The regression I caught before the pass reported (`a17d3b8`)

Making `llm_readiness` provider-aware without moving the engine's own gate left the
two disagreeing: readiness said ready for a local provider with no key, and
`run_m1_llm_for_criterion` returned `{}` for every criterion. Run button live, every
record unscreened, status line "done" — **F-93's harm shape by another route.**
Pinned by an invariant over three providers × three key states rather than by
testing each side separately.

### 10.6 What the pass got wrong

Fifteen of the nineteen did not survive. They are not enumerated here; the pattern
worth recording is that the three lenses each over-reported on hypotheticals about
`urlopen` behaviour and socket reuse that the code already handles or that no
supported configuration reaches. The four that landed were all found by *running*
the code rather than reading it — which is the lesson: for a defect about what a
configuration actually does, execution beats inspection.

---

## 11. Session B - the startup flow

### 11.1 The startup flow, before and after

**Before** - `MetaScreenerApp.__init__`, in order: Tk root; title and
geometry; `project_root` from `__file__`; `.env` path; `_load_env_file`;
then

```python
331    if not self._prompt_api_key_always():
332        self.after(0, self.destroy)
333        return
```

with the notebook at 336, plugins at 340 and both bindings at 342-343 -
**all after the return.** `_prompt_api_key_always` returned `False` on
`not dlg.value`, so an empty string and a cancel were one path, and there
was no continue-without-a-key branch anywhere.

So dismissing a *key* dialog destroyed the whole application, including
stages 03, 04 and 05, which need no model of any kind and are the
majority of the funnel. It also left `self.nb`, `self._plugins` and both
bindings unassigned - `_on_close` iterates `self._plugins` and would have
raised, unreachable only because the protocol it hangs off was never
bound.

**After** - the notebook, the plugins and both bindings are built
**unconditionally**, and the provider conversation is deferred to the
event loop with `self.after(0, self._offer_provider_choice)`. It is now
something that happens *to* a working application rather than a gate in
front of one. Dismissing it writes nothing, so the store stays
`UNCONFIGURED` and the LLM stages report `NOT_CONFIGURED` - a stated
reason, not a missing window.

Pinned by AST rather than by instantiation, because the properties are
properties of **order** and `MetaScreenerApp` cannot be built under the
conftest. One gap in that test found while writing it:
`self.after(0, self.destroy)` passes `destroy` as a *reference*, so a
call-only check walked straight past the statement the test exists to
forbid; it now matches attribute mentions.

### 11.2 F-144 - the location, not the write

Closed. The key persists to the settings store. The distinction the row
exists for is *where*, not *how*: F-139 made the `.env` write atomic,
permission-preserving and symlink-safe, and it still reported `ok=True`
while writing into `sys._MEIPASS`, which PyInstaller deletes on exit. A
fix that improved the write again would have closed nothing.

`_save_env_key` is no longer reached. It is **kept**, because it carries
F-139's regression tests, with a docstring warning that every check it
performs passes even when the target directory is doomed.

### 11.3 D1, as corrected

The coordinator's restatement is now code. `NOT_CONFIGURED` is checked
**first**, ahead of the key and model checks - precisely because those can
be satisfied and make an unconfigured path look complete. The store ships
`UNCHOSEN`; local becomes effective only when chosen or remembered.

### 11.4 Ready means reachable

Four new members, added on the extension contract's own terms.
`llm_readiness` performs no probe - it runs inside Tk callbacks - it is
*told*. Being told nothing is `NOT_CHECKED` rather than silent optimism,
and the direction is asserted: an uncached probe **blocks**.

Detection's three messages are carried through verbatim rather than
flattened into one "unavailable", because not-installed, stopped, and
reachable-but-empty are three problems with three fixes.

### 11.5 D3 - why the ceremony is not polish

`_run_clicked` starts a **billable** operation with no estimate, no
request count and no confirmation, and the only cost statement in the
documentation is wrong by two to three orders of magnitude (F-125).
Adding a multi-gigabyte download with less ceremony than that deserves
would repeat the mistake in a form the user cannot undo.

So: **refusable** (size stated before a byte moves, offer declinable),
**interruptible** (cancel checked between chunks *and* before the request
is made, so a cancel that arrives first costs nothing), **honest** (the
figure says "about", because it comes from a config file, and the
server's own total supersedes it).

**The model name is not in a Python constant.** It lives in
`plugins/_common/recommended_models.json`, which `docs/installation.md`
now points at, with a user override in the settings directory. Asserted
by AST - no model-name-shaped literal in the module - and a missing config
offers **nothing** rather than falling back to something stale, which is
the only answer consistent with the rule.

Reading that file in the frozen build is safe: reading from
`sys._MEIPASS` works and the spec bundles `plugins/` as data. It is
*writing* there that loses data silently. That asymmetry is worth stating
because it is the whole of F-144.

### 11.6 The _readiness near-miss, recorded as a LIMIT

Extending readiness without plumbing the probe would have left
`_readiness()` passing `None`, so **every stage would have reported
NOT_CHECKED and the Run button would have been dead for every user**.

It was caught by reasoning, immediately, and shipped in the same commit.
**That is not a repeatable safety net and must not be recorded as one.**
906 tests were green at that moment. This is **F-14's gap doing real
damage**: the goldens protect the pipeline, the suite protects the engine,
and *nothing protects the View*.

What a headless View smoke test would have needed to catch it - recorded
so the eventual F-14 wave inherits the requirement rather than
rediscovering it:

1. **Instantiate a View at all.** The conftest replaces tkinter with
   `MagicMock`, so `ttk.Frame` is a mock and `ELView` cannot be
   constructed. A real headless Tk (Xvfb, or `tk.Tk()` on a CI image with
   a display) would be needed, or a widget layer thin enough to fake
   faithfully.
2. **Drive `_readiness()` and read `ControlStates.run`.** The assertion is
   one line - *with a bundle, a model and a configured provider, the Run
   button is enabled* - and no test in the suite can express it today.
3. **Cover the default path**, not a constructed one. The defect appeared
   with `probe=None`, which is the state every launch starts in, so a
   fixture that pre-seeds a probe would have passed while the application
   was broken.
4. **Assert on the widget, not on the function.** `llm_readiness` was
   correct throughout; the defect was in what the View passed it. A test
   of the pure function - which is what this wave added - cannot see it.

The same gap covers the label overflow in 11.7, which shipped past a test
whose explicit subject is that label's width.

### 11.7 Two defects found by execution, before the reviewers reported

*Three of the four new labels overflowed the widget.* 18, 18 and 20
characters against a 16-character constraint that
`test_the_label_fits_the_widget` calls "the one property here that is
genuinely about rendering, so it is pinned rather than eyeballed". It
passed because it loops over the three configuration cases that existed
when it was written. Both halves fixed: the labels are shorter, and the
test now iterates every state **and asserts that it did**
(`seen == set(READINESS_CODES)`), so the next state added fails there
until its label is measured.

*A grid-cell collision in the provider dialog.* `lbl_status` spans columns
0-2 of row 4 and the pull button was placed in column 2 of the same row -
the same cell. Re-laid onto its own row.

*Verified rather than assumed:* the probe cache is a module global, and
`main.py`'s `from plugins._common import provider_detect` and `ELView`'s
`from plugins._common.provider_detect import last_known` resolve to the
same module object. Had they not, the app would have deposited a probe the
views never saw - the dead Run button again, by a different route.

### 11.8 Human observations

Three, and only three. The dialog cannot be rendered here, so this is what
genuinely cannot be settled from source. They are not padded.

**HO-11B-1 - does the provider dialog appear before the main window is
drawn?** `__init__` ends with `self.after(0, self._offer_provider_choice)`
and the dialog calls `grab_set()`. On a slow first paint the modal may
appear over an empty or unpainted root, which would look like the old
behaviour it replaces.
*Repro:* launch from a cold start on a machine with no `settings.json`.
Watch the first 500 ms.
*Report:* whether the main window is visibly painted before the dialog
appears, and whether the dialog is centred on it or on the screen.

**HO-11B-2 - is the disabled API-key field visibly disabled?**
`_on_provider_changed` calls `ent_key.state(["disabled"])` when *local* is
selected, because a local server needs no key. Whether ttk renders that as
convincingly greyed depends on the active theme, and a field that looks
editable but ignores typing is worse than one that is absent.
*Repro:* open the dialog, select *On this computer*, try to type in
**API key**.
*Report:* whether it is obviously inert, and whether the same holds for
**Endpoint** when *OpenAI* is selected.

**HO-11B-3 - does the pull progress window behave when the download is
long?** The bar is `determinate` over 1000 steps driven from the server's
`completed`/`total`. Ollama emits several phases (manifest, then layers),
each with its own totals, so the fraction can reset to near zero
mid-download.
*Repro:* choose a local provider with no models pulled, accept the offer,
watch a full multi-gigabyte pull.
*Report:* whether the bar visibly restarts, and whether the status text is
intelligible while it does.

### 11.9 The review pass, and whether the instruction change helped

**It helped, decisively.** The coordinator changed one instruction after
session A: *execute, do not reason*, with every finding required to carry
the command run and the output observed.

| | Session A | Session B |
|---|---|---|
| Raised | 19 | 14 |
| Survived | 4 | **2 high, both reproduced** |
| Ratio | 21% | 14% |

The ratio alone understates it. Session A's four survivors were found by
running code *despite* an instruction that permitted reasoning; session
B's two were found by running code *because* the instruction required it,
and both arrived with a paste-able repro and real output. The noise that
remained was still hypothetical, but there was less of it and it was
easier to discard — a finding with no `how_you_ran_it` is refutable on its
face.

**Recommendation for session C: keep the instruction.** The cost is that
reviewers spend their budget executing rather than enumerating, which
lowers the raw count. That is the trade one wants.

#### 11.9.1 The OpenAI provider could never run

`llm_readiness` demands `probe.state == "ready"` for *every* provider, and
the only supplier of that probe was an **unauthenticated** GET of
`<endpoint>/models`. api.openai.com answers 401, `urlopen` raises,
`_fetch_models` returns `None`, `detect` falls through to the Ollama
binary check, and anything not-ready maps to `ENDPOINT_UNREACHABLE`.

Measured: a fresh install choosing OpenAI with a valid key gets
`can_run=False` and the message *"No local model server was detected …
Install it from https://ollama.com/download, or switch to OpenAI"* —
while already on OpenAI.

**Worse than the state it replaced.** Before this session that user could
run. This is the fresh-install regression shape the coordinator named,
arriving on the provider nobody was watching.

Fixed in two halves: the probe authenticates when a key is available, so
*reachable* becomes a question the vendor can answer; and the Ollama
discrimination is skipped for a non-local provider, because sending an
OpenAI user to fix their Ollama installation is exactly the wasted
afternoon D4/D5 exist to prevent, produced by the code written to
prevent it.

**Why the suite was green, which is the part worth keeping.** This wave's
own helper hand-built `probe=SimpleNamespace(state="ready")` for
`provider="openai"` — *a probe the real detector cannot produce for the
vendor*. **A test that asserts a state the system cannot reach is worse
than no test: it certifies the path it hides.** That is a new failure
mode for this project's records, and it is not the same as insufficient
coverage — the coverage existed and pointed at fiction.

#### 11.9.2 Session A's billing defect, reachable again by a new route

`_accept` stored the endpoint verbatim, and the endpoint box is enabled
for *local*. Selecting local and clearing it stored
`{provider: "local", endpoint: ""}`; `key_required("local")` is `False`
so the gate opened; and a blank endpoint fell through to
`DEFAULT_OPENAI_BASE_URL`. Measured: key gate open, endpoint
`https://api.openai.com/v1`, credential `sk-a-real-key` — a billable run
the store labels local. The harmoniser's `_llm_available` is key-only and
never consults the probe, so that stage would have made the call.

The same shape arrives with **no user error at all** from any settings
file that names a provider and omits an endpoint.

Closed by an **invariant** rather than by patching the route: *a keyless
provider never resolves to the paid vendor*. Falling back to the local
default is wrong-but-harmless; falling back to the vendor is
wrong-and-billable. The dialog also repairs a blank endpoint at accept,
so there are two independent guards.

**This is the second time this wave has produced this defect, by two
different routes.** Session A: a default that presumed a provider.
Session B: a blank field that presumed an endpoint. Both times the
mechanism was the same — `key_required` waives the gate for a keyless
provider while something else still points at the vendor — and both times
it was found by executing rather than reading. The invariant now closes
the class, not the instance.

---

## 12. Session C — the per-stage controls

### 12.1 Gate

| Check | Result |
|---|---|
| HEAD | `ec8f7c3`, `fix/wave-11-provider-choice` = `main` = `origin/main`, tagged `post-wave-11b` |
| Status / sync | clean, 0/0, no gap commits |
| Golden manifest | 9 files recorded; `rekey_cache_goldens --verify` clean, EL 170/170, IL 84/84 |
| Suite baseline | **936 passed, 7 skipped** |

### 12.2 F-118's remaining half, stated before it was worked

The row has carried three halves and two were closed in `866c988`: the Run-button gate
(`_set_controls_running` re-enabled Run on the bundle path alone, and since it runs in the
`finally` of every run the load path's gate died after the first run of a session) and the
numerics (a negative `trunc_chars` reached the prompt builder as a *negative slice* and
emptied title and keywords outright). **The remaining half is the harmoniser's "LLM refine"
checkbox — `var_llm` bound and read by nothing.**

### 12.3 The routes this session opens, and how the invariants hold

Five new ways to specify a provider, an endpoint or a model independently and per stage.
Four are covered by what sessions A and B built. **One is not, and it was stated before any
code was written.**

| # | Route | INV-1 (a keyless provider never resolves to the paid vendor) |
|---|---|---|
| R1 | per-stage **model** override | untouched — a model is neither an endpoint nor a gate |
| R2 | app-level **endpoint** edited from a stage tab | the value session B already guards |
| R3 | **discovery** called from a tab | a read-only GET that decides no gate (§12.6) |
| R4 | **D6** batch size keyed on the provider | reads the provider, writes nothing routable |
| R5 | **per-stage endpoint override** | **not covered** |

**R5.** Session B's invariant lives in `resolve_openai_base_url`, which was app-level only,
and it is a rule about the **fallback** — it fires when nothing named an endpoint. A
per-stage override moves the endpoint *independently* of the provider and reaches the vendor
**explicitly**:

```
provider = "local"                      -> key_required is False, gate waived
stages["EL"]["endpoint"] = the vendor   -> reached explicitly, nothing fell back
```

Nothing fell back, so the invariant never fires, and `placeholder_key_for` supplies the
literal string `"local"` as the credential — or the user's real key if one is stored. **That
is this wave's billing defect for the third time**: session A produced it with a default that
presumed a provider, session B with a blank field that presumed an endpoint, and a per-stage
override produces it with no presumption at all — a user typing a URL into the tab they were
working in.

**INV-1b — an effective endpoint that is the paid vendor is never keyless.** The key question
is asked about the resolved **pair**, `stage_state::key_required_for(provider, endpoint)`, and
where the two halves disagree the safe side wins. `key_required` is unchanged and still
answers when no endpoint is known, so this is one predicate asking a larger question rather
than the two predicates F-117 closed. Asserted over the cross product of provider × endpoint ×
key rather than over the two routes that happen to be known, because patching routes is what
left this hole open twice.

The host is **parsed, not matched**: a substring check calls
`http://api.openai.com.example.invalid/v1` the vendor, which is wrong in the direction that
costs money, and would miss `api.openai.com/v1` typed without a scheme, which is wrong in the
direction that spends it.

**Invariant 2 holds by a scope limit, and the limit is a disagreement with the brief.**
`settings.STAGE_OVERRIDABLE` is `model`, `endpoint`, `batch_size` — **not `provider`**.
`llm_readiness` checks `NOT_CONFIGURED` ahead of the key and model checks precisely because
those can each be satisfied while the path as a whole is unconfigured; a stage-level provider
would let a stage acquire one while the application is still `UNCHOSEN`, which is a path
reaching a run without passing that check. `set_stage_override` raises, **and** the resolver
ignores a hand-edited one — a settings file is user-editable, so refusing at the setter alone
would be a gate with a door beside it. Nothing is lost: a stage that must reach a different
server says so with an endpoint override, which is what `custom` means and why one URL field
covers LM Studio, llama.cpp and vLLM at once.

### 12.4 Where the decision lives now

`settings::resolve_stage(cfg, stage)` returns the whole effective configuration as one frozen
record, and `resolve_openai_base_url` delegates to it. **`stage=""` is the application level
and resolves to exactly what it resolved to before per-stage anything existed** — asserted
directly, over four stage names, and it is what keeps the golden replays valid.

`_openai_client_for` and `_has_openai_key` take a stage. This **reverses**
`_openai_client_for`'s "kept zero-argument on purpose", and the reversal is recorded in its
docstring rather than dropped. The stated reason was that a parameter would break twelve
doubles *to no benefit*; per-stage endpoints are the benefit. The alternative — a module-level
"current stage" — is wrong the moment EL and IL run at once, which two tabs make ordinary. The
doubles were widened to `lambda *_a, **_k:` in the same commit.

`run_m1_llm_for_criterion` needed **no new parameter**: `stage` was already threaded through
it, documented as decorative — *"No semantic logic depends on its value."* It stopped being
decorative.

### 12.5 The combobox fixtures, and how they are checked against the producer

Session B's most serious defect was a test that certified a state the system cannot produce —
`probe=SimpleNamespace(state="ready")` for `provider="openai"`, which the real detector could
not emit, so 926 tests were green while the OpenAI provider could not run at all. A combobox
tested against a fabricated model list is that trap in a new place, and **there was no check
against it, so building one was the first thing this session did.**

`tests/test_model_discovery.py` **fabricates nothing.** Every `Detection` it asserts on is
produced by running the real `detect()` against the fake server session A established, into a
`PRODUCED` table. Three guards hold it there:

1. **the table must cover `provider_detect.STATES` exactly** — a state the detector cannot
   reach cannot be tested here, and one it *can* reach cannot be forgotten;
2. **an AST check over the file's own source** forbidding `Detection(…)` and
   `SimpleNamespace(…)` anywhere in it. Read as structure rather than as text, because the
   docstring names both constructors in order to forbid them and a substring search would
   match the rule rather than a violation — the idiom `test_provider_detect.py` already uses
   for `subprocess`;
3. **the pair check**, which is the one that would actually have caught session B. Its defect
   was *not* a state outside `STATES` — `"ready"` is in `STATES`. It was the **(provider,
   state) pair**. So the check is over the pair, against `serve_authenticated`: a server that
   answers 401 without a `Bearer` token, i.e. one that behaves the way the vendor behaves.
   Both directions are asserted, or the discriminating server proves nothing.

The fake server moved to `tests/helpers_fake_server.py` with its body unchanged. Two fake
servers would be two definitions of what a real server answers, which is the drift these tests
exist to prevent.

### 12.6 Discovery: what the control shows, in each of the three cases

`provider_detect::model_choices(detection)` maps a detection to `values` + `note` + `state`.
**Every branch returns a usable control**, and the brief's three cases resolve as:

| Case | Suggestions | Note |
|---|---|---|
| the call **fails** (refused, non-200, non-JSON, unexpected shape) | none | detection's own — *install Ollama from …*, or *start it with `ollama serve`*, whichever applies |
| the call **times out** | none | identical **by construction** — `_fetch_models` returns `None` for a timeout exactly as for a refusal, and the remedy is the same |
| the call **returns nothing** | none | a **third** message — *the server is running but has no models pulled yet*. Pulling a model and starting a server are different actions |
| *(before any of them)* `None` | none | *Checking what this server offers…* — said rather than shown as an empty list, because "we have not looked" is not something the server said |

The three failure notes are asserted **mutually distinct** and carried through **verbatim**,
which is the requirement session A met for the readiness messages, checked at the second place
the flattening could happen. Also asserted: readiness does not take `model_choices` as an
input, nothing returned could be read as a refusal, and **neither View may configure the model
control's state** — by AST, in any branch, for any reason — nor may either Combobox declare
one.

**A characterisation whose framing was wrong, corrected rather than obeyed.** The
characterisation commit said `list_models`' flattening would be inverted. Working it showed
that reading was wrong: `list_models` answers *what names are there* for a caller whose remedy
is identical in every failure, and its contract is correct **for that caller**. The defect was
that the tabs had no other path. So the tabs got one and the helper was left alone — changing
it would have been a change made to satisfy a characterisation rather than a user.

### 12.7 The combobox is editable, and the brief's claim about that is wrong

The brief says *"All three existing `ttk.Combobox` instances are `state="readonly"`, so this is
a new pattern here."* **Two of the three are.** `plugins/03_harmoniser/ui.py:723,748` are the
cell editors over `STAGES` and `OPERATORS` — **closed** vocabularies, where readonly is
right, and a test now pins that this session did not make *those* editable in passing. The
third, `plugins/01_reference_extractor/original/prisma_citations_ai_v3_1.py:755`, is live via
that plugin's `plugin.py:36` and declares no `state` at all, i.e. it is already editable. So
this is a new pattern for a **settings** surface, not a new pattern outright. Raised as a
correction; the design is unchanged by it.

### 12.8 The widget and the engine cannot disagree

The engine resolves from the store; the tab holds Tk variables. A value living only in a
widget would send a run somewhere other than what the tab shows — this wave's subject,
arriving through the controls added to fix it. So `settings::apply_stage_fields` writes on
field-exit **and before the run starts, ahead of the readiness check**, so the check answers
about the configuration that will actually run. Asserted by AST in both Views.

`stage_overrides_for` carries the rule that makes this more than a dict copy: **a field equal
to what the stage would resolve to *without* an override stores nothing.** Without it, opening
a tab and pressing Run pins a copy of whatever the box was showing; the application setting
silently stops reaching that stage; and the next provider change leaves the tab the user was
*not* looking at on the old endpoint. The comparison is against a resolution with the stage's
entry removed, not against the raw application key, because the two differ whenever a default
is doing the work — an unconfigured install shows the vendor endpoint in the box while the
setting is empty.

A second label names the endpoint's **source** (stage override / application setting / keyless
default / `OPENAI_BASE_URL` / vendor default). F-119's lesson: the URL alone does not
distinguish *I chose the public API* from *my configuration was not read*.

### 12.9 A hook that reached nothing

`main.py:443` has notified `on_provider_changed` since session B and **no plugin implemented
it**, so `notify_plugin` returned `False` into the void and the tabs kept reporting the
previous answer until something else happened to refresh them. Received on the **plugin
wrapper** — the object `main.py` notifies — and relayed to the View. A method on the View
alone would have left the call reaching nothing, which is how the gap arose in the first
place. `notify_plugin`'s `False` return is now itself asserted, because that return value is
the only signal the gap ever produced.

### 12.10 D6 — the number, and what may not be said beside it

`recommended_batch_size` returns **5** for a keyless provider and `None` — no suggestion, the
stage's own default answers — for everything else.

**Why the bottom of the 5–10 range.** The two costs of a smaller batch are more requests and
more wall-clock, and against a local server both are free: no per-request charge, and the
machine is the user's own. The benefit is a shorter list for the model to track. When one side
of a trade-off costs nothing, taking the safer end of the stated range is not a judgement
call. *(It is also the value the goldens were captured at, which is a coincidence rather than a
reason — they are replayed with an explicit batch size and nothing here reaches them.)*

The question is asked about the **provider**, not the endpoint, unlike `key_required_for`, and
the asymmetry is deliberate: getting the key gate wrong spends money, so it takes the cautious
reading of an ambiguous pair; getting the batch size wrong costs a slower run. A `custom`
endpoint may be a large hosted model or llama.cpp on a laptop, and 5 works for both.

**The wording is tested because what it must not say is the load-bearing part.** It lives in
`stage_state` — pure, no tkinter — and the `Tooltip` widget holds no logic, which is the
division that makes a sentence assertable at all. Three properties:

* **it is a quality setting, not a correctness one**, said outright. F-86 was the correctness
  defect here; it is **closed**, in the engine, since wave 7, and it fired at `batch_size = 1`
  as readily as at 50 because the acceptance guard admitted any known `a_id` whatever batch it
  came from. The tooltip names all three facts. A list of false-reassurance phrases —
  *safer*, *prevents*, *more accurate*, *guarantee* — is asserted absent, with the one
  sanctioned use, the **denial**, required verbatim and removed before the list is applied;
* **F-101**: the cache key hashes a synthetic one-item prompt, so batch size is invisible to
  it and changing this does not invalidate a cache. Said beside the box the user is about to
  change, because *"will this throw away my cached decisions?"* is the reasonable fear that
  otherwise stops them;
* **nothing about how well a local model screens.** That needs a live measurement and is wave
  12's. The claim made is narrow: a shorter list is easier to keep track of.

### 12.11 D9 — the checkbox is deleted, and that reverses a decision

F-118's fix cell said *"The checkbox is DECIDED and must not be re-litigated: it will be
WIRED, not deleted."* Session C **deletes** it, on the coordinator's instruction, and the
reversal plus its reasoning are recorded in the row so it is not re-litigated a third time.

The reasoning is the fact the earlier decision itself recorded for whoever would implement it:
the LLM/no-LLM choice is *already* expressed by two buttons a few inches away, and
`_harmonise_llm` never consulted `var_llm`. Wiring it means deciding what the flag should mean
when it disagrees with the button pressed, and **every answer to that is worse than not having
the control** — a third control that can contradict two explicit ones makes the user wrong
about what they asked for. The row calls the checkbox the worst of the three halves *because
it reads as the cost-and-provider safety switch*, and a wired version overridable by a button
would still read that way while still not being one.

### 12.12 The harmoniser stops deciding for itself

*"A user running locally must not find that one button still demands a paid key."* Four ways
it did:

* `_llm_available` never checked `NOT_CONFIGURED`, so a store with a leftover key and **no
  provider chosen** lit the button — ahead of the check that exists because the key and model
  tests can each be satisfied while the path as a whole is unconfigured;
* it never consulted the probe, so an unreachable endpoint lit it too and the run failed one
  call in;
* `cfg.get("provider", "local")` defaulted to a **keyless** provider when the key was missing,
  waiving the gate — session A's `defaults()` defect one module along;
* the key indicator read `os.getenv("OPENAI_API_KEY")` **directly** — the third predicate after
  F-117 unified two — so it said *missing* to exactly the user who needs no key, and disagreed
  with the button next to it.

All four are one defect: a third answer to a question `llm_readiness` already answers. The
View now calls it with the same arguments EL and IL pass, and the label and the button read
the same `Readiness` object, so they **cannot** disagree. `_llm_available` is **removed rather
than aliased** — session A's argument when it removed `has_key=` — and what remains,
`_sdk_importable`, answers only whether the SDK can be imported, which readiness cannot know.

`has_bundle=True` is passed deliberately: this stage has no bundle, its inputs are the criteria
text and the A vector, `_ensure_ready` owns that check, and `NO_BUNDLE` would tell a harmoniser
user to load a ScreenA bundle ZIP — the wrong file at the wrong stage.

### 12.13 F-140, and the correction that matters more than the fix

Two independent guards rather than one: `sanitize_api_key` iterates to a **fixed point**, so
sanitizing twice cannot differ from sanitizing once; and `_on_save` hands the **raw** entry to
`validate_api_key` and stores `sanitize_api_key` of that same raw string, so the two are one
expression over one input whether or not the function is idempotent.

**The row understates it.** F-140 is written against `ApiKeyDialog`, which session B made
**unreachable** — so that fix is prophylactic on its own. The dialog the application actually
opens, `ProviderDialog._accept`, stored `var_key.get().strip()`: whitespace only, **no quote
handling at all**. Measured:

```
entry '"sk-a-real-key"'  ->  old ProviderDialog stored '"sk-a-real-key"'
                         ->  now                       'sk-a-real-key'
```

The same harm by a simpler route, on the only live path. Both dialogs share one function now;
two definitions of what a key is would be F-117's shape applied to the value rather than to the
predicate. `_probe` still strips rather than sanitizes, deliberately — it sends the key as a
bearer token and never persists it.

### 12.14 A regression this session introduced and caught before it shipped

`231f0fc` made the store's batch size live. **Session A had shipped
`defaults()["batch_size"] = 5` and nothing read it**, so that value immediately became the
seed for every stage — including one running against OpenAI — in place of the module default
of 50. Ten times the requests, silently, on the provider that bills per call. Measured before
the change shipped rather than argued:

```
defaults()['batch_size'] = 5
fresh install  -> resolve_stage('EL').batch_size = 5
openai chosen  -> resolve_stage('EL').batch_size = 5     <- was 50
```

`defaults()` now says `None` — *nobody has chosen* — and the provider suggests. This is the
same shape as session A's `provider="local"`: **a value asserted by a module that cannot see
the inputs the decision depends on.**

It was caught by reasoning while wiring D6, and **that is not a repeatable safety net and must
not be recorded as one.** 1163 tests were green at that moment. It is F-14's gap again — the
goldens protect the pipeline, the suite protects the engine, and nothing protects the View —
and it is the second wave running in which the thing that caught a live defect was one person
thinking about it rather than anything in the repository.

### 12.15 The AST lesson, learned three times in one session

Three tests failed against **their own explanatory comments**: the comment recording a
deletion names the thing deleted, so a substring search matches the record rather than the
defect. The repository already learned this once, for the `subprocess` check in
`test_provider_detect.py`, and its docstring says so. All three now read structure rather than
text.

One of them produced a better test than the blunt version would have. *"The harmoniser must
not read the environment"* is false as stated — `os.environ` is a legitimate **input** to
`resolve_stage`. What is forbidden is a second place **deciding** from it, which is what the
old key indicator did. The test now says exactly that: every read lives inside
`_stored_config`, and each one is an argument to the resolver. A guard that fires on the thing
it is meant to permit gets deleted rather than obeyed, and the same correction was needed for
the model-control guard, which first flagged `configure(values=…)` — the line that *fills* the
dropdown.
