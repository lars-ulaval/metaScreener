# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_frozen_directories.py — one guard over EVERY frozen evidence directory,
generalised from the wave-16d failure.

Wave 16b froze eight arms of live runs, wrote a SHA256SUMS from the working
tree, and committed. `.gitignore`'s `*.log` silently excluded one artefact at
`git add` time: `git add -A <dir>` skips ignored files without a word, so the
commit looked complete. The SHA256SUMS listed the file and the wave's own
freeze test compared against `Path.rglob` — **both read the same working tree,
so both agreed with each other and neither agreed with the repository.** The
first fresh clone (CI) had no such file on disk and the bijection failed there
and only there.

The lesson this file encodes:

1. **A frozen directory is bijective with the REPOSITORY, not the disk.**
   Everything here reads `git ls-files` and `git cat-file`, never the working
   tree, so a file that is present locally but never committed cannot hide.
2. **A recorded digest is a promise about bytes, so those bytes must be
   attribute-protected** — including prose and including SHA256SUMS itself,
   which has no extension and slipped through every glob-shaped rule in all
   six frozen directories at once.
3. **The digest must hold for the committed blob AND for a fresh checkout.**
   Those differ exactly when an attribute is missing, which is how wave 16b's
   README broke on Windows while passing on Linux.

Adding a new frozen directory requires no edit here: drop a SHA256SUMS beside
the evidence and this file starts guarding it.
"""
import hashlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DATA = ROOT / "docs" / "data"

#: Files a frozen directory may track WITHOUT listing in its SHA256SUMS.
#: The older waves deliberately keep their `*.meta.txt` outside the sums —
#: it is the prose that describes the frozen bytes, and it is revised when a
#: later wave annotates the dataset. Wave 16b chose to pin its meta.txt
#: instead; both are legitimate, so this only says an unlisted file must be
#: one of these, never an evidence blob.
UNLISTED_ALLOWED_SUFFIXES = (".meta.txt",)


def _git(*args):
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                          text=True, check=True).stdout


def _frozen_dirs():
    return sorted(p.parent for p in DATA.rglob("SHA256SUMS"))


def _listed(sums_path):
    """{relative name -> digest} as recorded, parsed line-ending-robustly."""
    out = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, name = line.split(None, 1)
        out[name.strip().lstrip("*")] = digest
    return out


def _tracked(d):
    """Repo-relative paths git actually holds for this directory."""
    rel = d.relative_to(ROOT).as_posix()
    listing = _git("ls-files", "--", rel).split("\n")
    return {p for p in listing if p}


FROZEN_DIRS = _frozen_dirs()
IDS = [d.relative_to(ROOT).as_posix() for d in FROZEN_DIRS]


def test_there_are_frozen_directories_to_guard():
    """A guard that silently guards nothing is the failure mode this file
    exists to prevent, so the discovery itself is asserted."""
    assert len(FROZEN_DIRS) >= 6, IDS


@pytest.mark.parametrize("d", FROZEN_DIRS, ids=IDS)
class TestAFrozenDirectoryIsBijectiveWithTheRepository:

    def test_every_listed_file_is_committed(self, d):
        """THE wave-16d regression: a digest recorded for a file the
        repository does not have. Checked against `git ls-files`, because
        the working tree is precisely where the missing file was hiding."""
        rel_dir = d.relative_to(ROOT).as_posix()
        listed = {f"{rel_dir}/{n}" for n in _listed(d / "SHA256SUMS")}
        missing = sorted(listed - _tracked(d))
        assert not missing, (
            f"{rel_dir}: listed in SHA256SUMS but not committed: {missing}. "
            f"A `git add` that hit an ignore rule is the usual cause; "
            f"`git check-ignore -v <path>` names it.")

    def test_no_evidence_file_is_committed_unlisted(self, d):
        """The other direction, scoped: prose may sit outside the sums, an
        evidence blob may not."""
        rel_dir = d.relative_to(ROOT).as_posix()
        listed = {f"{rel_dir}/{n}" for n in _listed(d / "SHA256SUMS")}
        sums = f"{rel_dir}/SHA256SUMS"
        unlisted = sorted(p for p in _tracked(d) if p not in listed and p != sums)
        offenders = [p for p in unlisted
                     if not p.endswith(UNLISTED_ALLOWED_SUFFIXES)]
        assert not offenders, (
            f"{rel_dir}: committed but unpinned: {offenders}")

    def test_committed_bytes_match_the_recorded_digests(self, d):
        """Verified against the blob git stores, not the file on disk: the
        repository is the authority a fresh clone will receive."""
        rel_dir = d.relative_to(ROOT).as_posix()
        for name, digest in _listed(d / "SHA256SUMS").items():
            spec = f"HEAD:{rel_dir}/{name}"
            proc = subprocess.run(["git", "show", spec], cwd=str(ROOT),
                                  capture_output=True, check=False)
            assert proc.returncode == 0, (
                f"{rel_dir}/{name}: listed in SHA256SUMS but not present at "
                f"HEAD. If you have just staged it, commit it — a digest "
                f"recorded for a file no commit carries is the wave-16d "
                f"regression this file guards.")
            assert hashlib.sha256(proc.stdout).hexdigest() == digest, (
                f"{rel_dir}/{name}: committed bytes do not match the "
                f"recorded digest")

    def test_a_fresh_checkout_reproduces_the_recorded_digests(self, d):
        """The working tree must agree too. It diverges from the blob
        exactly when a file is not attribute-protected — wave 16b's README
        matched on Linux and not on Windows for that reason — so this is the
        platform-sensitive half of the guarantee."""
        for name, digest in _listed(d / "SHA256SUMS").items():
            p = d / name
            assert p.is_file(), f"{p} listed but absent from the working tree"
            assert hashlib.sha256(p.read_bytes()).hexdigest() == digest, (
                f"{p}: working-tree bytes differ from the recorded digest — "
                f"a checkout rewrote them, which means the file is not "
                f"binary-pinned in .gitattributes")

    def test_everything_pinned_is_also_protected(self, d):
        """A recorded digest implies protected bytes, with no exception for
        prose and none for SHA256SUMS itself (no extension, so every
        glob-shaped rule missed it in all six directories at once)."""
        rel_dir = d.relative_to(ROOT).as_posix()
        names = list(_listed(d / "SHA256SUMS")) + ["SHA256SUMS"]
        paths = [f"{rel_dir}/{n}" for n in names]
        out = _git("check-attr", "text", "binary", "--", *paths)
        attrs = {}
        for line in out.strip().split("\n"):
            if not line:
                continue
            path, attr, val = line.rsplit(": ", 2)
            attrs.setdefault(path, {})[attr] = val
        unprotected = sorted(p for p in paths
                             if attrs.get(p, {}).get("binary") != "set")
        assert not unprotected, (
            f"{rel_dir}: pinned by a digest but not binary in "
            f".gitattributes: {unprotected}")
