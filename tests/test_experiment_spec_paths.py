# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_experiment_spec_paths.py — every path an experiment spec names must be a
file the REPOSITORY has (F-225).

`docs/data/wave16_arms/experiment_spec.json` is an *executable* artefact, not a
record: `tools/run_criteria_experiment.py` resolves `arms[].source` against the
project root and opens it, and `tests/test_run_criteria_experiment.py` drives
the same loader. Nothing checked that those paths still pointed at anything.

Wave 17a renamed `samples/ic_ec_12.txt`. The spec kept the old string, and the
breakage surfaced three directories away as three opaque failures in
`test_run_criteria_experiment.py` — a FileNotFoundError from a JSON file that
no traceback names. The spec is the input; the path in it is the thing that
rots when a file moves.

This is F-223's family, and it inherits F-223's rule:

1. **A referenced path must exist in the REPOSITORY, not on the disk.** Every
   lookup here goes through `git ls-files`. A spec that names a file which is
   present locally but never committed is broken for everyone else, and
   `Path.exists()` would call it fine — which is exactly how wave 16b's
   SHA256SUMS passed locally and failed on the first fresh clone.
  1b. A digest a spec records must match the bytes the repository SERVES, not
     the bytes that happen to be on this disk. `git cat-file --filters` applies
     the checkout conversion, so the comparison is the one a fresh clone on any
     platform would make (F-230). Wave 16a recorded seven of its eight
     `source_sha256` values from the LF form while `* text=auto` served them as
     CRLF on Windows; nothing read them, so it was silent for two waves.

2. **Discovery is repository-side too, and automatic.** The spec set comes from
   `git ls-files docs/data`, so a `wave17_arms/experiment_spec.json` is covered
   the day it is committed with no edit here. This deliberately does NOT copy
   `tests/test_frozen_directories.py`'s `DATA.rglob(...)` discovery: that reads
   the working tree, which is the half of F-223 this file exists to avoid. The
   hardcoded `docs/data` search root is copied, because that is where the
   evidence directories live.

What counts as a path is decided structurally rather than by a key whitelist,
so a future spec that invents a new path-bearing key is covered without anyone
remembering to add its name here. A spec string is a candidate path when it
has a `/` and no whitespace — which admits `corpus`, `source` and `raw_probe`,
and excludes the three kinds of `/`-bearing string these specs also carry:
prose (`rationale`, `comparison`, `population_banner` — all contain spaces),
the `http://` endpoint, and `corpus_bundle.dir`, an absolute path to an archive
that lives outside the repository by design.
"""
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DATA_REL = "docs/data"

#: The filename that marks an experiment spec. Basename match, any depth.
SPEC_NAME = "experiment_spec.json"


def _git(*args):
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                          text=True, check=True).stdout


def _git_is_usable():
    try:
        proc = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                              cwd=str(ROOT), capture_output=True, text=True)
    except (OSError, ValueError):
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "true"


_NEEDS_GIT = pytest.mark.skipif(
    not _git_is_usable(),
    reason="git ls-files is the authority these assertions consult; "
           "no usable git here.",
)


def _tracked():
    """Every path the repository holds, as forward-slash repo-relative."""
    return {p for p in _git("ls-files").split("\n") if p}


def _spec_paths():
    """Committed experiment specs, repo-relative."""
    if not _git_is_usable():
        return []
    listing = _git("ls-files", "--", DATA_REL).split("\n")
    return sorted(p for p in listing if p and p.rsplit("/", 1)[-1] == SPEC_NAME)


def _candidate_paths(node, where=""):
    """(json-pointer-ish location, value) for every string in `node` that is
    shaped like a repo-relative path. See the module docstring for the rule."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            out.extend(_candidate_paths(v, where + "." + k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(_candidate_paths(v, where + "[" + str(i) + "]"))
    elif isinstance(node, str):
        s = node.strip()
        if "/" in s and not any(c.isspace() for c in s):
            out.append((where.lstrip("."), s))
    return out


def _is_repo_relative(value):
    """Absolute paths and URLs are not this guard's business."""
    if "://" in value:
        return False
    if value.startswith("/") or value.startswith("\\"):
        return False
    if len(value) > 1 and value[1] == ":":     # drive letter, e.g. S:/...
        return False
    return True


SPECS = _spec_paths()


@_NEEDS_GIT
def test_there_are_specs_to_guard():
    """A guard that silently guards nothing is the failure mode this file
    exists to prevent, so the discovery itself is asserted — the same
    reasoning as `test_frozen_directories.py::test_there_are_frozen_
    directories_to_guard`."""
    assert SPECS, (
        "No %s found under %s via `git ls-files`. Either the specs moved or "
        "the discovery broke; both make this file a no-op that still passes."
        % (SPEC_NAME, DATA_REL)
    )


@_NEEDS_GIT
@pytest.mark.parametrize("spec_rel", SPECS or [""], ids=SPECS or ["<none>"])
def test_every_path_a_spec_names_is_in_the_repository(spec_rel):
    """THE F-225 regression: a spec naming a file the repository does not
    have. Checked against `git ls-files`, because a working tree that still
    holds the old file — or holds a new one nobody committed — is precisely
    where this hides."""
    spec = json.loads((ROOT / spec_rel).read_text(encoding="utf-8"))
    tracked = _tracked()

    candidates = [(w, v) for w, v in _candidate_paths(spec)
                  if _is_repo_relative(v)]
    assert candidates, (
        "%s declares no repo-relative path at all. An experiment spec that "
        "names no corpus and no arm source is not one; more likely the "
        "candidate rule stopped matching." % spec_rel
    )

    missing = sorted(
        "%s -> %s" % (where, value)
        for where, value in candidates
        if value not in tracked
    )
    assert not missing, (
        "%s names paths the repository does not have: %s. A spec is an INPUT "
        "— it is executed, not merely recorded — so a path in it that no "
        "longer resolves is a break, and it surfaces far from here (F-225 "
        "surfaced as three FileNotFoundErrors in "
        "tests/test_run_criteria_experiment.py). Fix the spec. Run manifests "
        "under the same tree are OUTPUTS and keep their original strings: "
        "they record what a past run consumed."
        % (spec_rel, missing)
    )


def _served(rel):
    """The bytes a checkout of `rel` produces — index content with the file's
    eol/filter attributes applied. This is what a fresh clone gets on THIS
    platform, and it is the only form a recorded digest can honestly name."""
    proc = subprocess.run(["git", "cat-file", "--filters", ":%s" % rel],
                          cwd=str(ROOT), capture_output=True)
    if proc.returncode != 0:
        return None
    return proc.stdout


@_NEEDS_GIT
@pytest.mark.parametrize("spec_rel", SPECS or [""], ids=SPECS or ["<none>"])
def test_every_recorded_source_digest_matches_the_repository(spec_rel):
    """F-230. A spec that records `source_sha256` is making a promise about
    bytes, and a promise that only holds on the author's platform is not one.

    Compared against `git cat-file --filters`, never against the working tree:
    the disk copy can be right here and wrong in CI, which is exactly how wave
    16a's seven wrong digests survived two waves without anything noticing."""
    spec = json.loads((ROOT / spec_rel).read_text(encoding="utf-8"))
    arms = spec.get("arms") or []

    recorded = [(a.get("key"), a.get("source"), a.get("source_sha256"))
                for a in arms if a.get("source_sha256")]
    assert recorded, (
        "%s records no source_sha256 on any arm. If that is deliberate this "
        "check is vacuous and should say so; if it is not, the digests were "
        "dropped." % spec_rel
    )

    wrong = []
    for key, src, want in recorded:
        blob = _served(src)
        if blob is None:
            wrong.append("%s -> %s (not in the repository)" % (key, src))
            continue
        got = hashlib.sha256(blob).hexdigest()
        if got != want:
            wrong.append("%s -> %s: recorded %s, repository serves %s"
                         % (key, src, want[:12], got[:12]))

    assert not wrong, (
        "%s records digests that do not match the bytes the repository serves: "
        "%s. The digests are measurements and are usually RIGHT — what is "
        "normally wrong is the checkout form, so reach for a .gitattributes "
        "`eol=` rule before editing a recorded number. A recorded digest is an "
        "output record (F-225): fix how it is served, do not rewrite it."
        % (spec_rel, wrong)
    )


def _eol_attr(rel):
    """The `eol` attribute git resolves for `rel`, or None if unspecified."""
    out = subprocess.run(["git", "check-attr", "eol", "--", rel],
                         cwd=str(ROOT), capture_output=True, text=True).stdout
    # "<path>: eol: <value>"
    value = out.strip().rsplit(": ", 1)[-1] if out.strip() else ""
    return None if value in ("", "unspecified", "unset") else value


@_NEEDS_GIT
@pytest.mark.parametrize("spec_rel", SPECS or [""], ids=SPECS or ["<none>"])
def test_every_pinned_source_has_an_explicit_eol_rule(spec_rel):
    """F-230, second half — and the half that would have caught wave 17c's red CI
    on the machine that authored it.

    The digest check above compares against `git cat-file --filters`, which is
    honest but PLATFORM-LOCAL: a file left on `* text=auto` is served CRLF on
    Windows and LF everywhere else, so a CRLF-recorded digest passes on the
    author's machine and fails on every other. That is exactly what happened —
    two Windows fresh clones agreed, and CI went red on 12 of 16 jobs.

    An explicit `eol=` rule removes the platform from the question. Asserting the
    RULE rather than only the digest fails wherever it is run, including on the
    machine that wrote the record, which is the difference between catching this
    at authoring time and catching it in CI."""
    spec = json.loads((ROOT / spec_rel).read_text(encoding="utf-8"))
    pinned = sorted({a["source"] for a in (spec.get("arms") or [])
                     if a.get("source_sha256")})
    assert pinned, (
        "%s pins no source by digest, so this check is vacuous." % spec_rel
    )

    unpinned = [rel for rel in pinned if _eol_attr(rel) is None]
    assert not unpinned, (
        "These files have a recorded `source_sha256` in %s but no explicit "
        "`eol=` rule in .gitattributes, so what a checkout serves depends on "
        "the platform while the recorded digest does not: %s. Add an `eol=` "
        "rule matching the form the digest was measured in — `eol=crlf` if it "
        "was recorded on Windows, `eol=lf` if on Linux or macOS. Do NOT edit "
        "the digest: it is an output record (F-225), and the checkout form is "
        "what is wrong. This assertion is deliberately platform-independent — "
        "the digest check alone passes on the authoring machine and fails "
        "everywhere else, which is how F-230 reached CI twice."
        % (spec_rel, unpinned)
    )

