# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_lang_map.py — a language criterion must be able to match the corpus it
runs against (F-212).

`plugins/03_harmoniser/inference.py`'s branch 1 turns "written in German" into
`equals lang German`. `plugins/_common/evaluator.py` then compares the
criterion's operand and the corpus cell after passing both through
`_norm_for_target`, which for a `lang` target is `LANG_MAP.get(x, x)`. If the
NAME is absent from the map it normalises to itself, the CODE normalises to
itself, and the two can never be equal — so the criterion silently cuts
nothing. `_validate_row` returns E=0 W=0 and every linter check stays silent,
because nothing in the pipeline compares a criterion against the corpus's
vocabulary.

Measured twice before this file existed: wave 16a's G3 arm (German, one `de`
record) and wave 17b's RSA criteria file (Portuguese, twelve `pt` records). The
second is the sharper one — the funnel's endpoint was unchanged, because a
later criterion removed the same records, so the defect was invisible in the
only number a reader checks.

**Both halves are DERIVED, never repeated here** (F-131's discipline: a
hand-maintained second copy of a vocabulary drifts from the first):

  1. The alternation is read out of `inference.py`'s source, so adding a
     seventh language there fails this file until `LANG_MAP` follows.
  2. The corpus codes are read out of the sample aggregates found through
     `git ls-files`, so committing a corpus with an unmappable language fails
     here too — and it reads the REPOSITORY rather than the disk, which is
     F-223's rule.
"""
import csv
import io
import re
import subprocess
from pathlib import Path

import pytest

from plugins._common.parser import LANG_MAP, _norm_for_target

ROOT = Path(__file__).parent.parent

#: Where branch 1's language alternation lives.
INFERENCE_SRC = ROOT / "plugins" / "03_harmoniser" / "inference.py"

#: The alternation as written today, for the "did we actually find it" guard.
#: Not the source of truth — `_alternation_names()` is — but a bare-minimum
#: floor, so a regex that silently stops matching cannot pass this file.
KNOWN_MINIMUM = {"english", "french", "spanish"}


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
    reason="the corpus half derives its file list from `git ls-files`.",
)


def _alternation_names():
    """The language names branch 1 recognises, read from its source."""
    src = INFERENCE_SRC.read_text(encoding="utf-8")
    # r"\b(english|french|spanish|german|portuguese|italian)\b"
    m = re.search(r"\\b\((english(?:\|[a-z]+)+)\)\\b", src)
    assert m, (
        "Could not find branch 1's language alternation in %s. This file "
        "derives the name list from that pattern rather than repeating it; if "
        "the pattern moved or changed shape, update the search here — do not "
        "paste a copy of the names." % INFERENCE_SRC.relative_to(ROOT)
    )
    return m.group(1).split("|")


def _corpus_lang_codes():
    """{code: (n_records, [corpora])} over every committed sample aggregate."""
    listing = [p for p in _git("ls-files", "--", "samples").split("\n") if p]
    corpora = [p for p in listing if p.endswith("aggregate.csv")
               or p.endswith("Aggregate.csv")]
    out = {}
    for rel in corpora:
        txt = (ROOT / rel).read_bytes().decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(txt)))
        if not rows or "lang" not in rows[0]:
            continue
        i = rows[0].index("lang")
        for r in rows[1:]:
            code = r[i].strip()
            if not code:
                continue
            n, where = out.get(code, (0, set()))
            out[code] = (n + 1, where | {rel})
    return out, corpora


ALTERNATION = _alternation_names()


def test_the_alternation_was_actually_found():
    """A derivation that silently returns nothing would make every assertion
    below vacuously true."""
    assert len(ALTERNATION) >= 3, ALTERNATION
    assert KNOWN_MINIMUM <= set(ALTERNATION), (
        "The alternation no longer contains %s; either the pattern changed or "
        "the derivation is matching the wrong thing." % sorted(KNOWN_MINIMUM)
    )


@pytest.mark.parametrize("name", ALTERNATION, ids=ALTERNATION)
def test_every_name_branch_one_emits_normalises_to_a_code(name):
    """THE F-212 regression. A name the translator can emit must reach a code,
    or `equals lang <name>` cuts nothing for ever and says nothing."""
    got = _norm_for_target("lang", name)
    assert got != name, (
        "`equals lang %s` normalises to itself: branch 1 in inference.py can "
        "emit %r, but LANG_MAP has no entry for it, so it can never equal a "
        "corpus cell holding an ISO code. That is F-212 exactly — the "
        "criterion cuts nothing and every validator stays silent."
        % (name, name)
    )
    assert len(got) <= 3 and got.isalpha(), (
        "%r normalised to %r, which is not an ISO-639-style code." % (name, got)
    )


@_NEEDS_GIT
def test_there_are_corpora_to_check():
    """Guard-guards-nothing: the corpus half must actually find corpora."""
    _codes, corpora = _corpus_lang_codes()
    assert corpora, (
        "No sample aggregate found via `git ls-files samples`. The corpus "
        "half of this file would pass while checking nothing."
    )


@_NEEDS_GIT
def test_every_language_a_committed_corpus_stores_is_reachable_by_name():
    """The other direction, and the one wave 17b's RSA corpus tripped: a code
    sitting in a corpus that no English name maps onto cannot be written as a
    criterion at all. `_norm_lang`'s `.get(x, x)` already normalises a code to
    itself, so this is about the NAME -> code route being present."""
    codes, _corpora = _corpus_lang_codes()
    assert codes, "No `lang` values found in any committed corpus."

    reachable = {v for k, v in LANG_MAP.items() if k != v}
    unreachable = sorted(
        (code, n, sorted(where))
        for code, (n, where) in codes.items()
        if code not in reachable
    )
    assert not unreachable, (
        "These languages are stored by a committed corpus but no name in "
        "LANG_MAP normalises onto them, so no criterion can select them: %s. "
        "Add the English name (and its 639-2 variants) to LANG_MAP."
        % [(c, n) for c, n, _ in unreachable]
    )


@_NEEDS_GIT
def test_a_name_and_its_code_normalise_onto_the_same_value():
    """The property the evaluator actually needs: whichever side the criterion
    and the corpus are written in, both land on one value."""
    codes, _ = _corpus_lang_codes()
    by_code = {}
    for k, v in LANG_MAP.items():
        if k != v:
            by_code.setdefault(v, []).append(k)
    for code in sorted(codes):
        for name in by_code.get(code, []):
            assert _norm_for_target("lang", name) == _norm_for_target("lang", code), (
                "%r and %r do not normalise onto the same value." % (name, code)
            )
