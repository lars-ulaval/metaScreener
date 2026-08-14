
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_golden_rekey.py — F-89: the golden re-key's proof, re-run on every
suite run.

Why this file exists
--------------------
Wave 2 re-keyed the same two fixtures for F-01 and **threw the proof
away**: ``git show --stat c8d2fb3`` is three files, none of them a
migration script, so the five obligations survive only as prose in a
commit message. §B4.6 of ``06_llm_integration.md`` names that as the thing
to do differently:

    "the migration script (or a test that regenerates and re-verifies the
    mapping) should be **committed this time** — otherwise the next wave
    inherits the same 'the message says it was proved' situation."

``tools/rekey_cache_goldens.py`` is the script. This is the standing
re-verification, so a future wave can *re-run* the proof rather than read
that it was made.

What is checked, and why it is the post-conditions
--------------------------------------------------
A migration is not idempotent: once the goldens are re-keyed, re-deriving
the mapping from them finds nothing to move, so a check that only worked
before the migration would be exactly as unrepeatable as wave 2's.

The standing check is therefore over the migrated artefact, and needs no
git history. For every (criterion, record) pair the stage engine would
enumerate, both keys are derived — the current five-member one and the
pre-F-89 four-member one — and the committed golden must contain **all**
of the first and **none** of the second. That restates obligations 1, 2
and 4 over the result.

Obligation 3 cannot be recomputed from the migrated file alone, since the
values it must match lived in the pre-migration file. It is pinned as a
digest measured at ``c5e2100``, before a byte was written; a re-key does
not touch values, so it must survive this migration and every later one.

Obligation 5 is asserted directly.
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT

GOLDEN_DIR = PROJECT_ROOT / "tests" / "golden"

pytestmark = pytest.mark.skipif(
    not all((GOLDEN_DIR / n).exists() for n in (
        "el_cache_v3.1.0.json", "il_cache_v3.1.0.json",
        "el_input_v3.1.0.csv", "il_input_v3.1.0.csv",
        "criteria_harmonized_v3.1.0.csv",
    )),
    reason="EL/IL goldens not yet captured. Run tools/capture_el_il_goldens.py.",
)


def _rekey_tool():
    """Import ``tools/rekey_cache_goldens.py``.

    ``tools/`` is not a package, so it is loaded by path — the same way
    the tool loads the plugin modules it inspects.
    """
    name = "tools_rekey_cache_goldens"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, str(PROJECT_ROOT / "tools" / "rekey_cache_goldens.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def reports():
    tool = _rekey_tool()
    tool._setup_headless_imports()
    from plugins._common.llm_client import DEFAULT_OPENAI_BASE_URL

    return {
        stage: tool.verify_stage(stage, DEFAULT_OPENAI_BASE_URL)
        for stage in ("EL", "IL")
    }


EXPECTED_ENTRIES = {"EL": 170, "IL": 84}

# IL derives twice as many pairs as it has entries because IC-5 uses the
# `contains` operator and never reaches the LLM write-back site, which is
# gated `if c.operator == "llm" and to_call:`. All 84 entries are IC-1's.
# Not an orphan — recorded here so the asymmetry is not read as one.
EXPECTED_PAIRS = {"EL": 170, "IL": 168}


@pytest.mark.parametrize("stage", ["EL", "IL"])
class TestTheRekeyHolds:

    def test_entry_count_is_unchanged(self, reports, stage):
        """Obligation 1, first half. A re-key relabels; it does not add or
        drop entries."""
        assert reports[stage].entries == EXPECTED_ENTRIES[stage]

    def test_pair_enumeration_is_faithful(self, reports, stage):
        """The enumeration must match what the stage engine walks.

        If it drifted, the key derivations below would be over the wrong
        pairs and their agreement with the golden would be meaningless.
        """
        assert reports[stage].pairs_derived == EXPECTED_PAIRS[stage]

    def test_every_committed_key_is_reproduced(self, reports, stage):
        """Obligations 1 and 2 over the migrated artefact: the mapping was
        onto, with no orphan left behind under an unreachable label.

        A key in the golden that the current function cannot reproduce is
        an entry that will never be served — a silent, permanent cache
        miss that costs real API calls and that no test would otherwise
        catch.
        """
        r = reports[stage]
        assert r.new_keys_present == r.entries, (
            f"{r.entries - r.new_keys_present} of {r.entries} committed "
            f"{stage} cache entries are keyed under something this code no "
            f"longer computes."
        )

    def test_no_pre_f89_key_survives(self, reports, stage):
        """Obligation 4, and the load-bearing half of F-142.

        The pre-F-89 key set and the post-F-89 key set must be disjoint. A
        four-member pre-image and a five-member one cannot collide short of
        a SHA-256 accident, but this asserts it over the real corpus rather
        than arguing it.
        """
        assert reports[stage].old_keys_present == 0

    def test_no_v1_prompt_version_key_survives(self, reports, stage):
        """Wave 14c's obligation 4, over ITS migration: the constrained
        request bumped ``PROMPT_VERSION`` (F-191/F-197) and the goldens
        were re-keyed with ``--migration prompt-version``. A committed key
        still derivable with the v1 version string would be an entry the
        pre-bump code could hit — exactly the unconstrained/constrained
        cache mixing the bump exists to prevent."""
        assert reports[stage].v1_keys_present == 0

    def test_values_are_untouched(self, reports, stage):
        """Obligation 3. This is what makes it a re-key and not a
        re-capture: no API call was made and no decision was recomputed.
        The pinned digest predates BOTH migrations — F-89's endpoint
        re-key and wave 14c's prompt-version re-key — and must survive
        every later one, which is the standing proof that each was a pure
        relabelling."""
        r = reports[stage]
        assert r.values_unchanged, (
            f"{stage} cache VALUES changed. A re-key relabels; if a value "
            f"moved, this was a re-capture and the decision CSVs are no "
            f"longer derived from the artefact they claim to be."
        )

    def test_invocation_is_preserved(self, reports, stage):
        """Obligation 5."""
        assert reports[stage].invocation == {
            "batch_size": 5, "model": "gpt-4o-mini", "trunc_chars": 4000,
        }


class TestTheMigrationArtifactIsUsable:
    """The point of committing the tool is that it can be re-run."""

    def test_the_tool_verifies_clean(self):
        tool = _rekey_tool()
        assert tool.main(["--verify"]) == 0

    def test_the_pinned_value_digests_cover_both_stages(self):
        tool = _rekey_tool()
        assert set(tool.VALUE_MULTISET_SHA256) == {"EL", "IL"}
        for digest in tool.VALUE_MULTISET_SHA256.values():
            assert len(digest) == 64


class TestTheCaptureToolPinsTheEndpoint:
    """F-89 made the endpoint a cache-key input, which made the capture tool
    environment-dependent while the tests that replay its output are not.

    Found in review of this wave: the two regression replays were pinned and
    the capture tool was not. A maintainer re-capturing on the machine where
    they had been testing Ollama would key the goldens to
    ``http://localhost:11434/v1``; the tests key with the default, miss every
    entry, and fail byte-identity with nothing in the committed file to
    explain why — ``_invocation`` records only model, truncation and batch
    size (F-128).
    """

    def _tool(self):
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

    def test_an_exported_override_is_ignored(self, monkeypatch):
        from plugins._common.llm_client import DEFAULT_OPENAI_BASE_URL

        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
        assert self._tool()._pin_endpoint() == DEFAULT_OPENAI_BASE_URL
        assert os.environ["OPENAI_BASE_URL"] == DEFAULT_OPENAI_BASE_URL

    def test_an_unset_variable_is_pinned_too(self, monkeypatch):
        """Pinned rather than left absent, so the capture cannot depend on
        the shell even when the shell happens to be right."""
        from plugins._common.llm_client import DEFAULT_OPENAI_BASE_URL

        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        assert self._tool()._pin_endpoint() == DEFAULT_OPENAI_BASE_URL
        assert os.environ["OPENAI_BASE_URL"] == DEFAULT_OPENAI_BASE_URL

    def test_the_pinned_endpoint_is_the_one_the_goldens_are_keyed_at(self):
        """The tool and this wave's migration must agree, or a re-capture
        would silently invalidate the fixtures it just produced."""
        from plugins._common.llm_client import DEFAULT_OPENAI_BASE_URL

        reports = {
            stage: _rekey_tool().verify_stage(stage, DEFAULT_OPENAI_BASE_URL)
            for stage in ("EL", "IL")
        }
        assert all(r.ok for r in reports.values())


class TestGoldenSerialisationConventions:
    """``tests/golden/** binary`` in ``.gitattributes`` is load-bearing, and
    these are the bytes it protects.

    The cache goldens are CRLF with a two-space indent and **no** trailing
    newline, because ``tools/capture_el_il_goldens.py`` writes
    ``json.dumps(..., indent=2)`` through ``Path.write_text`` on Windows.
    Without the binary attribute, ``* text=auto`` would normalise them on
    commit and checkout and every byte-identity test would fail on a fresh
    clone.
    """

    @pytest.mark.parametrize("name", ["el_cache_v3.1.0.json",
                                      "il_cache_v3.1.0.json"])
    def test_line_endings_and_framing_survived_the_rekey(self, name):
        raw = (GOLDEN_DIR / name).read_bytes()
        assert b"\r\n" in raw
        # No bare LF anywhere: every LF must be preceded by a CR.
        assert raw.count(b"\n") == raw.count(b"\r\n")
        assert not raw.endswith(b"\n")
        assert raw.startswith(b'{\r\n  "_invocation": {\r\n')

    def test_gitattributes_still_marks_the_goldens_binary(self):
        text = (PROJECT_ROOT / ".gitattributes").read_text(encoding="utf-8")
        assert "tests/golden/** binary" in text
