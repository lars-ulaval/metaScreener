# 04 — The frozen build, measured

*Wave 3, Part B. The distributable had been predicted broken since the 3.1.0
restructure but never built. This is the measurement.*

Environment: Windows 11, Python 3.11, PyInstaller 6.15.0. Both specs built
from the committed tree, unmodified, before any change was made.

---

## Summary

| Prediction (register, inferred) | Measured |
|---|---|
| F-09: `pandas`, `openpyxl`, `langdetect`, `rapidfuzz`, `PIL`, `pytesseract` absent from the bundle | **Half right.** `langdetect`, `rapidfuzz`, `pytesseract` absent. `pandas`, `openpyxl`, `PIL` present — by accident, see below |
| F-09: Plugins 01/02/03/04/05 fail silently; symptom is missing tabs | **Wrong.** All seven plugin modules import and all seven tabs render — confirmed by visual observation, both builds. Every heavy dependency is behind a `try/except` feature flag or a lazy in-function import |
| F-40: `hookspath=[]` disables `hook-plugins.py`; enabling it is the fix | **Understated.** Setting `hookspath=['.']` alone changes nothing at all — the hook never fires, because nothing statically imports `plugins` |
| F-35: plugin failures `print()` to a stdout the windowed build discards | **Conditionally true.** Output survives when the exe is launched from a terminal; it is lost on the double-click path a reviewer would actually use |
| F-19: the custom plugin loader is unnecessary, stock `importlib` suffices | **Not supported by this evidence.** See the correction below |

**Verdict: the distributable is fit to ship, confirmed rather than inferred.**
After the two-line spec fix in `d8d8a96`, both the console and the windowed
executable build, launch, and render all seven tabs — the latter observed
visually, not deduced from process output (see *Tab count — verified*). All six
third-party dependencies the plugins use are bundled, three of them no longer by
accident.

Before the fix the app also started and showed all seven tabs; what was missing
was three optional dependencies, and the failure mode was silent feature
degradation rather than the predicted missing tabs. That is the one caveat on
"fit to ship": nothing here checks that a build has the dependencies it needs, so
the next mis-specified build will look exactly as healthy as this one (F-66).

---

## What was actually missing, and why the rest got in

Measured from the built `PYZ-00.pyz` and the EXE's own archive, not inferred
from a crash.

Absent from the unmodified build: **`langdetect`, `rapidfuzz`, `pytesseract`**.

Present: `pandas` (280 modules), `openpyxl` (176), `PIL` (80) — and they are
present **by accident**. The import chain is:

```
collect_all('openai')  →  openai._extras.pandas_proxy  →  pandas
                       →  pandas.io.excel._openpyxl    →  openpyxl
                       →  openpyxl.drawing.image       →  PIL
```

Nothing in the specs asks for any of the three. They arrive because the
`openai` package ships an optional-extras proxy module that names `pandas`,
and `collect_all` pulls the whole package in. Three plugins' dependencies
currently rest on an implementation detail of an unrelated library: if
`openai` ever drops `_extras.pandas_proxy`, Plugin 02's CSV/XLSX import,
Plugin 03's parser, and the EL/IL XLSX exports all lose their dependency at
once, with no spec change to explain it.

The two-line fix makes all six explicit consequences of analysing the plugin
tree, rather than leaving three of them to coincidence.

## Why the predicted symptom did not occur

The plugins do not import their heavy dependencies unguarded:

- `plugins/02_references_of_x/core.py:34-46` — `pandas` and `rapidfuzz` are
  each in a `try/except` setting `PANDAS_OK` / `FUZZY_OK`.
- `plugins/02_references_of_x/services.py:44-49` — `langdetect` likewise, with
  `_LANGDETECT_OK`.
- `plugins/01_reference_extractor/plugin.py:36` — the heavy module is imported
  *inside a method* (`from .original import prisma_citations_ai_v3_1`), so it
  is not touched at plugin-load time at all.

So the predicted crash never happens and no tab goes missing. **The real
failure mode is worse in one respect and better in another:** better, because
the app runs; worse, because the degradation is invisible. With `rapidfuzz`
absent, `FUZZY_OK` is False and fuzzy title matching silently does not happen —
a reference-matching tool quietly doing less matching, with no notice to the
user and no entry in any log. `langdetect` absent means language detection
returns `""` for everything. `pytesseract` absent means OCR is unavailable.

Note that `plugins/01_reference_extractor/original/prisma_citations_ai_v3_1.py`
imports `fitz` and `PIL` **unguarded** at lines 49-50. Both happen to be
bundled (`fitz` explicitly via `collect_all`, `PIL` by the accident above), so
that module loads — but it is loaded lazily, so any failure there would surface
only when the user clicks the feature, not at startup.

## Why `hookspath=['.']` alone does nothing

This is the part of F-40 that was wrong, and it matters because enabling
`hookspath` is the fix the register proposes.

Building with `hookspath=['.']` and no other change produced a bundle with the
**identical 2960 pure modules** and `plugins` still at zero. PyInstaller
searches `hookspath` for `hook-<name>.py` only for modules that are already in
the dependency graph. Nothing statically imports `plugins`: `run.py` imports
`metascreener`, and `metascreener/plugin_manager.py` loads the plugin packages
at runtime through its own `sys.meta_path` finder, reading and sanitising the
source files. The graph therefore never contains a node named `plugins`, so
`hook-plugins.py` is never looked for.

`hook-plugins.py` was not disabled. It was unreachable.

Adding `'plugins'` to `hiddenimports` puts the node in the graph; the hook then
fires and `collect_submodules("plugins")` contributes all 47 plugin submodules,
which PyInstaller analyses, picking up their imports:

| | before | after |
|---|---|---|
| pure modules | 2960 | 3054 |
| `plugins` | 0 | 47 |
| `langdetect` | 0 | 10 |
| `rapidfuzz` | 0 | 35 |
| `pytesseract` | 0 | 2 |

## F-35, measured

The windowed build (`console=False`) **did** emit its `PLUGIN LOADER:` banners
when launched from a shell with stdout redirected. So the claim that output is
discarded is not unconditionally true: the GUI-subsystem binary still writes to
an inherited handle when one exists.

It is true on the path that matters. Double-clicked from Explorer — how a
reviewer runs a distributable — there is no console attached and the output
goes nowhere. F-35's consequence stands; its mechanism needs the qualifier.

## Correction to F-19 — the loader is load-bearing

F-19 recommended replacing the custom plugin loader with stock `importlib`, on
the evidence that stock `importlib` loads all ten plugin modules in the source
tree. That measurement was taken in **dev mode**, which is not the case the
loader exists for.

In the frozen build the plugin packages ship as `--add-data`, i.e. as files
under `sys._MEIPASS/plugins`, and are not importable modules. Measured here:
`_plugins_root_frozen()` resolves correctly, the finder is installed, and all
seven plugins load — the loader does the job it was written for.

Two further observations that F-19's replacement would have to reproduce:

1. The plugin package directories (`01_reference_extractor`, …) begin with a
   digit, so they are not valid identifiers for `import` statements. They are
   reachable via `importlib.import_module` by string, but a naive replacement
   using ordinary imports would not work.
2. The finder *sanitises* the source as it loads it — it strips a BOM and drops
   `from __future__ import annotations`. Any replacement inherits that
   requirement or must first prove it is no longer needed.

After the fix, `plugins` is also in the PYZ as an analysed package. The custom
finder still wins, because it is inserted at `sys.meta_path[0]`; verified by
relaunching both builds, not assumed. **F-19's verdict should move from
"replace" to "keep, with tests".**

## What remains broken

- **Silent feature degradation has no reporting.** The `*_OK` flags are never
  surfaced. A build missing an optional dependency looks identical to a
  complete one. Logged as a new finding (F-66).
- **F-35 stands** on the double-click path: a plugin that fails at load time in
  the windowed build aborts startup with no visible reason, because
  `discover()` has no `try/except` and the traceback goes to a stdout nobody
  sees.
## Tab count — verified

**Seven tabs, both builds. Observed visually by A. Reyes-Consuelo (maintainer),
who launched each executable and counted the rendered notebook tabs:**

1. Reference Markers (experimental)
2. References-of-X — AI v1
3. Harmoniser — Criteria
4. Screen A — EH
5. Screen A — IH
6. Screen A — EL
7. Screen A — IL

Plugin 01's experimental banner renders. This is a human visual observation of
the running GUI, not an inference from process output — the distinction that
the method note below exists to preserve.

It confirms the indirect evidence gathered from inside the process, which was
correct: both `PLUGIN LOADER:` banners printed; `discover()` is unguarded, so a
failed plugin import would have aborted startup with a traceback and none
appeared; and `_load_plugins` prints `[PLUGIN] Skipping` for an unusable
entrypoint, which never appeared either. Each of those was consistent with all
seven plugins loading, and none of them could have shown how many tabs were
drawn. The two lines of evidence agree.

## Note on method: what a process cannot observe about itself

An earlier draft of this document listed, under "what remains broken", that
startup appeared to pass the modal API-key dialog without interaction in both
dev and frozen mode, reproducibly and unexplained. **That was wrong and is
retracted.** The dialog blocked correctly on every launch; a human was entering
the key by hand each time, which is invisible from inside the process and from
the captured stdout.

The general point is worth keeping, because it will recur in any GUI check run
this way. A modal that requires human input cannot be verified from inside the
process: reaching the code past it proves only that *something* satisfied it,
not that it behaved correctly, and the absence of any record of interaction is
not evidence that none occurred. Reproducibility across runs does not
distinguish the two either — a person doing the same thing each time looks
exactly like no gate at all.

Future GUI checks should state explicitly whether a human interacted with the
run, and which steps they performed. Where that is not recorded, any conclusion
that depends on a modal's behaviour should be marked unverified rather than
inferred from what the process managed to print.
