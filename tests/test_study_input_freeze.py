
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_study_input_freeze.py — F-98: the published study's input is frozen
under ``docs/data/study_input/`` and no longer shares an artefact with the
regression fixtures.

Why this file exists
--------------------
``tests/golden/{el,il}_filtered_v3.1.0.csv`` served two roles whose
maintenance rules are opposites:

- a **regression fixture** is *meant* to be re-captured when the guarded
  behaviour legitimately changes — that is what it is for;
- a **cited dataset** must *never* change, or the published analysis no
  longer has the input it claims.

``docs/llm-evaluation.md`` §Reproducibility publishes two commands and the
claim that re-running them "reproduces the four output files
byte-for-byte". Three of the five inputs to those commands were mutable
goldens. ``tools/capture_el_il_goldens.py`` overwrites six files in one
run with no versioning, so **any** golden-touching wave silently rewrote
the input of a published analysis — and the document would have gone on
claiming byte-for-byte reproduction while producing different kappas, with
no error and nothing to notice.

Wave 12 re-captures the goldens against a different model. This freeze is
what makes that safe.

What guards the freeze, and why none of it is a hand-maintained list
--------------------------------------------------------------------
The project has been bitten five times by lists that fall silently out of
sync with the thing they enumerate — most recently the register's own
totals (F-131) — and ``test_frozen_build_spec.py`` states the rule this
file follows: "A fixed list is the same enumeration mistake as F-01's
cache key: it is correct exactly until someone adds an import, and then it
is silently wrong."

So every check here is **derived**:

1. *Coverage* — the set of frozen files is read off the directory and the
   set of recorded digests off ``SHA256SUMS``, and the two must agree **in
   both directions**. Adding a file without a digest fails; removing a
   file while leaving its digest fails. Nothing is named in this module.
2. *Fidelity* — the strongest guard, and the reason a digest alone is not
   enough: the documented reproduction command is actually run against the
   frozen inputs and its output compared byte-for-byte with the committed
   ``docs/data/eval_*`` artefacts. This is the document's own claim, made
   executable.
3. *Independence* — ``docs/llm-evaluation.md`` must not name
   ``tests/golden/`` at all. That is the whole of F-98 as a one-line
   invariant: the published document may not depend on a mutable fixture.
   It is a grep, not a list, so it holds for paths that do not exist yet.
4. *Non-interference* — the capture tool's own output paths are read out
   of the tool and must all land under ``tests/golden/``. This is the
   check that a re-capture cannot reach the frozen copy.
5. *Bytes* — ``.gitattributes`` must keep the frozen CSVs out of
   ``* text=auto`` normalisation. Three of the four are pure-LF and one is
   pure-CRLF; without the rule a fresh clone on Windows rewrites them,
   every digest breaks, and the failure looks like tampering rather than
   like checkout. ``tests/golden/`` already carries this rule for exactly
   this reason (see ``TestGoldenSerialisationConventions``).
"""
import hashlib
import importlib.util
import re
import shutil
import sys
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT

FROZEN_DIR = PROJECT_ROOT / "docs" / "data" / "study_input"
SUMS_PATH = FROZEN_DIR / "SHA256SUMS"
DATA_DIR = PROJECT_ROOT / "docs" / "data"
EVAL_DOC = PROJECT_ROOT / "docs" / "llm-evaluation.md"

# Sidecars describe the freeze; they are not part of what is frozen.
_SIDECARS = {"SHA256SUMS", "study_input.meta.txt"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen_files():
    """Every frozen artefact, derived from the directory itself."""
    return sorted(
        p for p in FROZEN_DIR.iterdir()
        if p.is_file() and p.name not in _SIDECARS
    )


def _recorded_digests():
    """Parse ``SHA256SUMS`` (the ``sha256sum`` format: digest, two spaces,
    name) into ``{name: digest}``."""
    out = {}
    for line in SUMS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, name = line.partition("  ")
        out[name.strip()] = digest.strip().lower()
    return out


class TestTheFreezeIsCoveredWithoutAList:
    """Coverage, derived in both directions."""

    def test_the_frozen_directory_exists_and_is_not_empty(self):
        assert FROZEN_DIR.is_dir(), (
            f"{FROZEN_DIR} is missing — the published study has no frozen "
            f"input and docs/llm-evaluation.md is citing mutable fixtures."
        )
        assert _frozen_files()

    def test_every_frozen_file_has_a_recorded_digest(self):
        on_disk = {p.name for p in _frozen_files()}
        recorded = set(_recorded_digests())
        assert on_disk <= recorded, (
            "Frozen files with no digest in SHA256SUMS: "
            f"{sorted(on_disk - recorded)}. A file added to the freeze "
            "without a digest is unprotected."
        )

    def test_every_recorded_digest_names_a_frozen_file(self):
        on_disk = {p.name for p in _frozen_files()}
        recorded = set(_recorded_digests())
        assert recorded <= on_disk, (
            "SHA256SUMS names files that are not present: "
            f"{sorted(recorded - on_disk)}."
        )

    def test_the_frozen_bytes_are_unchanged(self):
        drifted = [
            f"{name}: recorded {digest[:12]}…, found {_sha256(FROZEN_DIR / name)[:12]}…"
            for name, digest in sorted(_recorded_digests().items())
            if (FROZEN_DIR / name).exists()
            and _sha256(FROZEN_DIR / name) != digest
        ]
        assert not drifted, (
            "The published study's input has changed:\n  "
            + "\n  ".join(drifted)
            + "\n\nThis input is cited by docs/llm-evaluation.md and by the "
              "manuscript. It is not a fixture and must not be re-captured. "
              "If a golden legitimately moved, move the golden — the whole "
              "point of F-98 is that the two are now independent."
        )


class TestThePublishedStudyDoesNotDependOnAFixture:
    """Independence — F-98 as a one-line invariant."""

    # A *file* under tests/golden/, not the directory. The document is
    # expected to discuss the fixtures in prose — §Study input explains
    # why the two sets exist and that they are allowed to diverge, which
    # is the freeze's rationale and must stay readable. What it may not
    # do is name a file there, because naming one is how a fixture
    # becomes an input again.
    _FIXTURE_FILE_RE = re.compile(r"tests[/\\]golden[/\\][\w.\-]+\.\w+")

    def test_the_document_cites_no_mutable_fixture(self):
        offenders = [
            f"line {n}: {m.group(0)}"
            for n, line in enumerate(
                EVAL_DOC.read_text(encoding="utf-8").splitlines(), 1
            )
            for m in self._FIXTURE_FILE_RE.finditer(line)
        ]
        assert not offenders, (
            "docs/llm-evaluation.md names a file under tests/golden/:\n  "
            + "\n  ".join(offenders)
            + "\n\nThe goldens are regression fixtures and are re-captured "
              "when guarded behaviour changes. A published study may not "
              "take its input from one — that is F-98. Cite the frozen "
              "copy under docs/data/study_input/ instead."
        )


class TestARecaptureCannotReachTheFrozenCopy:
    """Non-interference, derived from the capture tool rather than asserted
    about it."""

    def _capture_tool(self):
        name = "tools_capture_el_il_goldens"
        if name in sys.modules:
            return sys.modules[name]
        spec = importlib.util.spec_from_file_location(
            name, str(PROJECT_ROOT / "tools" / "capture_el_il_goldens.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_no_path_constant_points_into_docs(self):
        """Derived over every module-level ``Path`` the tool holds, rather
        than over an enumerated output list — the tool reads from
        ``samples/`` as well as writing to ``tests/golden/``, and the
        invariant that matters is not "everything is an output" but
        "nothing is under ``docs/``".
        """
        mod = self._capture_tool()
        paths = [v for v in vars(mod).values() if isinstance(v, Path)]
        assert paths, "No Path constants found on the capture tool."
        docs = (PROJECT_ROOT / "docs").resolve()
        escapees = [
            str(p) for p in paths
            if docs == p.resolve() or docs in p.resolve().parents
        ]
        assert not escapees, (
            "tools/capture_el_il_goldens.py names a path under docs/: "
            f"{escapees}. A re-capture must not be able to reach the frozen "
            "study input."
        )

    def test_the_source_names_no_path_under_docs_data(self):
        """The constants above cover what the tool declares; this covers a
        path assembled inline. Together they are the whole surface by
        which a re-capture could reach ``docs/data/``.
        """
        src = (PROJECT_ROOT / "tools" / "capture_el_il_goldens.py").read_text(
            encoding="utf-8"
        )
        hits = [
            line.strip() for line in src.splitlines()
            if re.search(r"docs[/\\]data", line)
        ]
        assert not hits, (
            "tools/capture_el_il_goldens.py mentions docs/data:\n  "
            + "\n  ".join(hits)
        )


class TestTheFrozenBytesSurviveCheckout:
    """Bytes — the F-128-shaped trap, one directory over."""

    def test_gitattributes_exempts_the_frozen_input(self):
        text = (PROJECT_ROOT / ".gitattributes").read_text(encoding="utf-8")
        assert "docs/data/study_input/" in text, (
            "The frozen CSVs are not exempt from `* text=auto`. Three are "
            "pure-LF and one is pure-CRLF; without a rule here a fresh "
            "clone rewrites them and every digest above breaks."
        )


class TestTheFrozenInputReproducesThePublishedResults:
    """Fidelity — the document's own claim, made executable.

    This is what a digest cannot do. A digest proves the input did not
    move; this proves the input still *produces* the published numbers,
    which is the claim §Reproducibility actually makes.
    """

    OUTPUTS = (
        "eval_decisions_v1.csv",
        "eval_results_v1.csv",
        "eval_disagreements_v1.csv",
        "eval_summary_v1.txt",
    )

    @pytest.fixture(scope="class")
    def reproduced(self, tmp_path_factory):
        spec = importlib.util.spec_from_file_location(
            "tools_eval_ingest_freeze",
            str(PROJECT_ROOT / "tools" / "eval_ingest.py"),
        )
        ein = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = ein
        spec.loader.exec_module(ein)

        out = tmp_path_factory.mktemp("frozen_repro")
        rc = ein.main([
            "--manifest",         str(DATA_DIR / "grids" / "partition_manifest.csv"),
            "--criteria",         str(FROZEN_DIR / "criteria_harmonized_v3.1.0.csv"),
            "--filled-grids-dir", str(DATA_DIR / "grids" / "filled"),
            "--el-filtered",      str(FROZEN_DIR / "el_filtered_v3.1.0.csv"),
            "--il-filtered",      str(FROZEN_DIR / "il_filtered_v3.1.0.csv"),
            "--output-dir",       str(out),
        ])
        assert rc == 0, "The documented reproduction command failed."
        return out

    @pytest.mark.parametrize("name", OUTPUTS)
    def test_output_is_byte_identical_to_the_committed_artefact(
        self, reproduced, name
    ):
        published = DATA_DIR / name
        regenerated = reproduced / name
        assert regenerated.exists(), f"{name} was not produced."
        assert regenerated.read_bytes() == published.read_bytes(), (
            f"docs/data/{name} is no longer reproducible from the frozen "
            f"study input. Either the frozen input drifted, the ingestor's "
            f"behaviour changed, or docs/data/{name} was edited by hand. "
            f"§Reproducibility of docs/llm-evaluation.md claims this "
            f"command reproduces it byte-for-byte."
        )
