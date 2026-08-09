# metaScreener — Wave 5: rename `docs_/` → `samples/` and make the sample-availability story honest

Scope is deliberately small: one rename with its full reference sweep (F-54),
one documentation correction (F-83), two findings logged and parked (F-84,
F-85). Nothing in this wave changes behaviour, goldens, or the contents of the
wheel/sdist.

Standing rules as before: branch `fix/wave-5-samples` off `main` (@ `7e44e54`),
one finding per commit, suite green after every commit (baseline **421 passed,
4 skipped**), no golden may move — a sha256 manifest of `tests/golden/` was
recorded at step 0 and is re-verified at close-out, alongside
`git diff main...HEAD -- tests/golden/` — merge `--ff-only`, tag
`post-wave-5`, and **no push**: the human pushes after coordinator review.

---

## Decisions of record (made by the human; recorded, not relitigated)

**D1. `docs_/` becomes top-level `samples/` — not `docs/samples/`.**
Top-level keeps the sample files inside `tools/check_encoding.py`'s scan scope
(its exclusion list covers `docs/data/` and `docs/internal/`; a top-level
`samples/` matches neither prefix), and outside the docs cross-reference
tests' discovery root (`PROJECT_ROOT / "docs"` + `rglob("*.md")`). Implemented
as the **flat** layout — `docs_/samples/<file>` → `samples/<file>` and
`docs_/README.md` → `samples/README.md` — per the rename the diagnostic itself
proposed (`00_overview.md` §2.4: "`docs_/samples/` → `samples/`"); a literal
one-level rename would have produced a degenerate `samples/samples/`.

**D2. F-83's remedy is honesty, not shipping.** The documentation now states
that the samples live in the repository — clone or download the source to get
them — and that pip installs do **not** include them. The samples are not
added to the wheel/sdist. The dead `[tool.setuptools.package-data]` line
(`pyproject.toml:74`, a no-op because `docs_` is not a package selected by
`packages.find`) is deleted with the rename.

**D3. The `.gitignore` `docs_` block (lines 68–72 at wave start) is deleted,
not retargeted.** Nothing writes into the tree at runtime — established in the
docs_/docs diagnostic: zero references in `metascreener/`, `run.py`,
`hook-plugins.py`; comments only in `plugins/`; `tools/` reads only — so the
blanket rule's only effect was to hide accidental manual additions from
`git status`. That is the F-54 foot-gun; deleting the rule closes F-54.

**D4. F-84 and F-85 are register-only this wave.** Logged and parked; no code
or test changes for either.

---

## Step-1 verification: what the register actually contains

Established at source on `main` @ `7e44e54`, read-only, before branching:

- `docs/internal/diagnostic/03_findings.md` holds **79 rows**: F-01..F-82
  present except exactly **F-56, F-57, F-58**, with no duplicate IDs. The
  register's own count line agrees ("— 79 findings").
- The coordinator's ledger ("79 rows; F-56–F-58 never assigned") is right
  about the row count and the absences, and wrong about "never assigned":
  all three IDs were assigned to real findings and consumed outside the
  register — commits `a6d1f0f` fix(F-56), `d6af29c` fix(F-57), `8a000ac`
  fix(F-58); CHANGELOG lines 314 (F-57), 321 (F-56), 323 (F-58); F-56 also
  cited in `tests/test_refx_ingest_encoding.py:109,145`.
- The docs_/docs diagnostic (2026-08-09) was right that F-54 is a real row
  and that F-56 is a real, fixed finding — and wrong to describe F-56 as
  "already registered". The three findings are fixed and documented in the
  CHANGELOG; they simply never received register rows. This wave does not
  backfill them: new IDs continue after the maximum, at F-83.
- Minor drift, noted and left: F-54's evidence cell cites `.gitignore:66-69`;
  at wave-5 start the block sits at lines 68–72 (later `.gitignore` edits
  shifted it).

F-54's row, verbatim, at wave-5 start:

> | **F-54** | **Low** | hygiene | **`docs_/**` is blanket-gitignored with
> three re-inclusions**, so files dropped there vanish from `git status`. |
> `.gitignore:66-69` | A contributor adding a sample sees it silently
> untracked. Compounded by the one-underscore confusion with `docs/`. |
> Document the rule in `docs_/README.md`; consider renaming to `samples/`
> after acceptance (touches `pyproject.toml:75`, README ×4, `docs/index.md`,
> `docs/usage.md`). | S |

---

## Duplication sweep of the wave-5 candidates

Swept against all 79 existing rows before any register edit.

**CF-1 → new row F-83** (documentation / packaging, Medium). The docs present
PyPI as a first-class install path and call the samples "bundled", but no
distributable contains them; `pyproject.toml:74` is a no-op, verified against
the built 3.1.0 wheel (59 entries) and sdist (90 entries). Near-misses, none
covering it: F-54 cites the package-data line only as a rename touchpoint;
F-09/F-40 are the same *class* (packaging claims vs artifact contents) for a
different artifact (the frozen build), closed; F-16/F-17/F-30/F-57 are
docs-vs-reality for different subjects; F-48 is about `dist/` staleness, not
contents. New row.

**CF-2 → new row F-84** (packaging, Low, **parked — needs proof before
fix**). The 3.1.0 sdist ships 13 `tests/test_*.py` modules with none of their
prerequisites (no `conftest.py`, no `tests/golden/`, no sample data), so
pytest in an unpacked sdist cannot collect. Mechanism unproven — suspected
stale on-disk `metascreener_lars_ulaval.egg-info/SOURCES.txt` union; under
the current `packages.find` config `tests/` should not be in the sdist at
all. Nearest row is F-48 (stale `dist/`), which is about coexisting versions,
not artifact contents. New row, parked per D4.

**CF-3 → new row F-85** (testing, Low, **parked**).
`test_every_doc_listed_in_index` accepts a bare-filename substring match
(`tests/test_metadata.py:198-202`), so a published doc whose name already
occurs anywhere in `docs/index.md` counts as "listed". Nearest rows: F-29 —
same test family, different defect (scope, fixed) — and F-32 (a check weaker
than its name), different subject. The companion trap from the wave-5 handoff
(samples under `docs/data/` would leave the encoding guard's scope) is mooted
by D1's top-level placement and is recorded inside the row rather than as its
own finding. New row, parked per D4.

---

## Plan of commits

1. `docs: wave-5 brief` — this file.
2. `docs(register): log wave-5 findings` — rows F-83..F-85, counts updated.
3. `fix(F-54): rename docs_/ to samples/` — guard test added first and
   watched failing; then `git mv` (flat layout) and the full reference
   sweep from the diagnostic's §6(i) list; `.gitignore` block deleted (D3);
   dead package-data line deleted; CHANGELOG `### Changed` bullet.
   History untouched: `CHANGELOG.md` line 320 and all `docs/internal/**`
   mentions of `docs_` stay as written.
4. `fix(F-83): state the true sample availability` — `docs/installation.md`
   (PyPI framing + smoke-test lead-in), `README.md` sample-data note,
   `docs/usage.md` lead-in; CHANGELOG `### Fixed` bullet. Claims corrected,
   paths already correct after commit 3.
5. `docs(register): close out wave 5` — "Fixed in `hash`" on F-54 and F-83,
   golden manifest re-verified, final counts recorded.
