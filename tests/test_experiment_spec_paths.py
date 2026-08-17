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
