
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_el_regression.py — Golden-file regression for Plugin 06 (EL).

Drives the same engine functions that the EL tab's "Run EL" button calls
and writes an EL_FULL report CSV that must be byte-identical to
``tests/golden/el_filtered_v3.1.0.csv``.

The golden is the byte-level contract that pins (a) per-criterion outcome
assignment, (b) survivor selection (derivable from ``el_outcome != "OUT"``),
(c) the reason-summary text, and (d) the LLM evidence JSON. Together these
guard against silent drift across the EL module-decomposition refactor
(Conv 6) and any subsequent change.

Test inputs:
- corpus:   tests/golden/el_input_v3.1.0.csv   (post-IH survivors)
- criteria: tests/golden/criteria_harmonized_v3.1.0.csv
- cache:    tests/golden/el_cache_v3.1.0.json  (replayed verbatim)

A second test asserts that the assembled OpenAI ``messages`` payload for a
fixed (criterion, item) pair has a stable SHA-256 hash. This catches drift
in prompt construction that the cache-keyed byte-identity test cannot
see (since cache resolution short-circuits before prompt construction).

A third test asserts the module-level ``PROMPT_VERSION`` string.
``PROMPT_VERSION`` is incorporated into ``_cache_key``; bumping it
invalidates the cache golden, so this assertion serves as an explicit
guardrail. ``PROMPT_VERSION`` bumps are intentional and require
re-capturing both the cache and FULL CSV goldens via
``tools/capture_el_il_goldens.py``.

Capture / re-capture
--------------------
The six golden files (three for EL, three for IL) are produced by
``tools/capture_el_il_goldens.py``. Run that script with a live
``OPENAI_API_KEY`` exactly once when goldens are first established, then
again only when a change is intentional. See the script's docstring for
details.

Cache-miss behaviour
--------------------
This test unsets ``OPENAI_API_KEY`` before invoking ``run_el_screen``.
With no key, ``_has_openai_key()`` returns False and
``run_m1_llm_for_criterion`` short-circuits to an empty result. Every
(a_id, criterion_id) pair MUST therefore be served from the cache;
any cache miss yields empty evidence which causes the byte-identity
assertion to fail.
"""
import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

import pytest

from conftest import AGGREGATE_COLUMNS, get_el  # noqa: F401

GOLDEN_DIR = Path(__file__).parent / "golden"
EL_INPUT = GOLDEN_DIR / "el_input_v3.1.0.csv"
EL_CACHE = GOLDEN_DIR / "el_cache_v3.1.0.json"
EL_FULL = GOLDEN_DIR / "el_filtered_v3.1.0.csv"
CRITERIA_GOLDEN = GOLDEN_DIR / "criteria_harmonized_v3.1.0.csv"

# Prompt-hash assertions (captured by tools/capture_el_il_goldens.py
# --print-hashes). If this hash changes, EL prompt construction has
# drifted; re-capture goldens deliberately.
EXPECTED_PROMPT_VERSION = "EL_v1_jsonlist"
EXPECTED_PROMPT_HASH = (
    "5e82291d4b999ed55cdb3a75e9603b7ea3d4f05fed44f233870c802f43a3d010"
)

# Must match capture script and IL test
PROMPT_HASH_TRUNC_CHARS = 4000


def _load_cache_envelope(path: Path):
    """Read the cache JSON envelope produced by capture_el_il_goldens.py.

    Envelope shape::

        {"_invocation": {...}, "cache": {<sha256>: {...}, ...}}
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw["_invocation"], raw["cache"]


def _el_to_csv(out_path: Path) -> None:
    """Reproduce the GUI's EL run path, replaying cached LLM responses."""
    el = get_el()

    # Load fixtures
    corpus_text = EL_INPUT.read_text(encoding="utf-8-sig")
    criteria_text = CRITERIA_GOLDEN.read_text(encoding="utf-8-sig")
    invocation, cache = _load_cache_envelope(EL_CACHE)

    # EL plugin.py has its own inline _csv_read returning (header, rows).
    # _parse_csv_tolerant_text only exists in plugins/_common/parser.py
    # (re-exported from EH/IH but not from EL/IL until Conv 6 / Commit 1+
    # decomposes them onto _common). Construct ParseReport manually.
    csv_header, csv_rows = el._csv_read(corpus_text)
    parse = el.ParseReport(header=csv_header, rows=csv_rows, skipped=[])
    crits = el._parse_criteria_harmonized_csv(criteria_text, "EL")

    # Defensive: tests must NEVER hit the live API
    saved_key = os.environ.pop("OPENAI_API_KEY", None)
    try:
        (full_rows, _surv, _counts, _impacts, _evals, _cache_out,
         _cancelled, _report) = el.run_el_screen(
            parse, crits,
            model=invocation["model"],
            trunc_chars=invocation["trunc_chars"],
            batch_size=invocation["batch_size"],
            use_cache=True,
            cache_in=cache,
            cancel_event=threading.Event(),
            log_cb=None,
            progress_cb=None,
            progress_evt=None,
        )
    finally:
        if saved_key is not None:
            os.environ["OPENAI_API_KEY"] = saved_key

    fieldnames = list(parse.header) + [
        "el_outcome", "el_failed_ids", "el_missing_ids",
        "el_met_ids", "el_uncertain_ids",
        "el_evidence_json", "el_reason_summary",
    ]
    # _write_csv_bytes lives in plugins/_common/exporters.py and is
    # re-exported by EH/IH. EL/IL don't expose it until Conv 6 / Commit 1+;
    # import directly from the shared module so all four stage goldens use
    # the same writer (LF line terminators, like EH/IH goldens).
    from plugins._common.exporters import _write_csv_bytes
    out_path.write_bytes(_write_csv_bytes(fieldnames, full_rows))


@pytest.mark.skipif(
    not (EL_FULL.exists() and EL_CACHE.exists() and EL_INPUT.exists()),
    reason="EL goldens not yet captured. Run tools/capture_el_il_goldens.py.",
)
class TestELGolden:
    """Byte-identity regression for the EL_FULL report CSV."""

    def test_byte_identical_to_golden(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "el_full.csv"
            _el_to_csv(out)
            actual = out.read_bytes()
        expected = EL_FULL.read_bytes()
        assert actual == expected, (
            f"EL_FULL report CSV changed.\n"
            f"  expected {len(expected)} bytes, got {len(actual)} bytes.\n"
            f"  Per-criterion eval, outcome assignment, reason summary, or\n"
            f"  evidence JSON drifted. If the change is intentional, rebuild\n"
            f"  via tools/capture_el_il_goldens.py."
        )


class TestELPromptStability:
    """Prompt-construction stability assertions.

    These tests do NOT require any golden file to be present; they exercise
    the in-memory prompt builder against a fixed synthetic input.
    """

    def test_prompt_version_string(self):
        el = get_el()
        assert el.PROMPT_VERSION == EXPECTED_PROMPT_VERSION, (
            f"PROMPT_VERSION drifted: expected {EXPECTED_PROMPT_VERSION!r}, "
            f"got {el.PROMPT_VERSION!r}. Bumping PROMPT_VERSION invalidates "
            f"the cache golden; re-capture via tools/capture_el_il_goldens.py."
        )

    def test_assembled_messages_hash_stable(self):
        el = get_el()
        criterion = {
            "id": "EC-2",
            "type": "exclude",
            "operator": "llm",
            "target": "title,abstract,keywords",
            "what": ["spatial navigation virtual maze"],
            "how": "llm",
            "label": "fixed-test-criterion",
            "threshold": 0.6,
        }
        item = {
            "a_id": "TEST-001",
            "title": "A study of virtual reality in cognitive rehabilitation.",
            "abstract": "We examine head-mounted display VR for stroke recovery.",
            "keywords": "virtual reality; HMD; rehabilitation",
        }
        msgs = el._build_llm_messages_for_criterion(
            criterion, [item], PROMPT_HASH_TRUNC_CHARS
        )
        payload = json.dumps(msgs, ensure_ascii=False, sort_keys=False)
        actual = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        assert actual == EXPECTED_PROMPT_HASH, (
            f"EL prompt construction drifted.\n"
            f"  expected SHA-256 = {EXPECTED_PROMPT_HASH}\n"
            f"  got SHA-256      = {actual}\n"
            f"  Re-capture via 'python tools/capture_el_il_goldens.py "
            f"--print-hashes' if intentional."
        )
