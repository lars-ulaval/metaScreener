# Fix wave 11 — the provider choice

Branch `fix/wave-11-provider-choice`, cut from `c6b0f77` (`main`, tagged
`post-wave-10`). **Additive: no golden moved**, verified two ways.

**The wave runs as three sessions**, proposed after step 0 and agreed before any
code was written. This document is written as the sessions land; sessions B and C
are marked pending below.

| | Session A — foundation | Session B — startup | Session C — controls |
|---|---|---|---|
| Findings | F-116, F-117, F-121, **F-144** (opened) | F-91, F-140, D8, F-144 (closes) | F-92 GUI *(see §1.1)*, F-118/D9, D6 |
| GUI diff | **none** | the popup, launch order | every stage tab |
| Status | **complete** | pending | pending |

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
| Session A close | **858** | 7 |

**Delta +64 passed, +2 skipped, all new; no test deleted, two suites translated:**

- +22 `tests/test_settings_store.py` (2 of them skipped on Windows — POSIX
  permissions and symlink privileges)
- +22 `tests/test_provider_readiness.py`
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

**Everything still requires an OpenAI key**, because nothing yet reads the store at
launch. That is session B.

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

## 10. Sessions B and C

*Pending.*
