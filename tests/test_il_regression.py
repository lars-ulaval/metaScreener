
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_il_regression.py — Golden-file regression for Plugin 07 (IL).

Drives the same engine functions that the IL tab's "Run IL" button calls
and writes an IL_FULL report CSV that must be byte-identical to
``tests/golden/il_filtered_v3.1.0.csv``.

The golden is the byte-level contract that pins (a) per-criterion outcome
assignment, (b) review-corpus selection (derivable from
``il_outcome != "OUT"``), (c) the reason-summary text, and (d) the LLM
evidence JSON. Together these guard against silent drift across the IL
module-decomposition refactor (Conv 6) and any subsequent change.

See ``tests/test_el_regression.py`` for the full design rationale; this
test mirrors that one with IL-specific paths and a separate prompt hash.

Test inputs:
- corpus:   tests/golden/il_input_v3.1.0.csv   (post-EL survivors)
- criteria: tests/golden/criteria_harmonized_v3.1.0.csv
- cache:    tests/golden/il_cache_v3.1.0.json  (replayed verbatim)

Capture / re-capture: ``tools/capture_el_il_goldens.py``.
"""
import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

import pytest

from conftest import get_il

GOLDEN_DIR = Path(__file__).parent / "golden"
IL_INPUT = GOLDEN_DIR / "il_input_v3.1.0.csv"
IL_CACHE = GOLDEN_DIR / "il_cache_v3.1.0.json"
IL_FULL = GOLDEN_DIR / "il_filtered_v3.1.0.csv"
CRITERIA_GOLDEN = GOLDEN_DIR / "criteria_harmonized_v3.1.0.csv"

# Prompt-hash assertions (captured by tools/capture_el_il_goldens.py
# --print-hashes). If this hash changes, IL prompt construction has
# drifted; re-capture goldens deliberately.
EXPECTED_PROMPT_VERSION = "IL_v1_jsonlist"
EXPECTED_PROMPT_HASH = (
    "c336d5eb9da23652181541e9888b863296b99b3a45144a523184f253c0024f32"
)

PROMPT_HASH_TRUNC_CHARS = 4000


def _load_cache_envelope(path: Path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw["_invocation"], raw["cache"]


def _il_to_csv(out_path: Path) -> None:
    """Reproduce the GUI's IL run path, replaying cached LLM responses."""
    il = get_il()

    corpus_text = IL_INPUT.read_text(encoding="utf-8-sig")
    criteria_text = CRITERIA_GOLDEN.read_text(encoding="utf-8-sig")
    invocation, cache = _load_cache_envelope(IL_CACHE)

    # IL plugin.py has its own inline _csv_read; see test_el_regression.py
    # for the rationale.
    csv_header, csv_rows = il._csv_read(corpus_text)
    parse = il.ParseReport(header=csv_header, rows=csv_rows, skipped=[])
    crits = il._parse_criteria_harmonized_csv(criteria_text, "IL")

    saved_key = os.environ.pop("OPENAI_API_KEY", None)
    try:
        full_rows, _surv, _counts, _impacts, _evals, _cache_out = il.run_il_screen(
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
        "il_outcome", "il_failed_ids", "il_missing_ids",
        "il_met_ids", "il_uncertain_ids",
        "il_evidence_json", "il_reason_summary",
    ]
    # See test_el_regression.py for the rationale.
    from plugins._common.exporters import _write_csv_bytes
    out_path.write_bytes(_write_csv_bytes(fieldnames, full_rows))


@pytest.mark.skipif(
    not (IL_FULL.exists() and IL_CACHE.exists() and IL_INPUT.exists()),
    reason="IL goldens not yet captured. Run tools/capture_el_il_goldens.py.",
)
class TestILGolden:
    """Byte-identity regression for the IL_FULL report CSV."""

    def test_byte_identical_to_golden(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "il_full.csv"
            _il_to_csv(out)
            actual = out.read_bytes()
        expected = IL_FULL.read_bytes()
        assert actual == expected, (
            f"IL_FULL report CSV changed.\n"
            f"  expected {len(expected)} bytes, got {len(actual)} bytes.\n"
            f"  Per-criterion eval, outcome assignment, reason summary, or\n"
            f"  evidence JSON drifted. If the change is intentional, rebuild\n"
            f"  via tools/capture_el_il_goldens.py."
        )


class TestILPromptStability:
    """Prompt-construction stability assertions (no golden required)."""

    def test_prompt_version_string(self):
        il = get_il()
        assert il.PROMPT_VERSION == EXPECTED_PROMPT_VERSION, (
            f"PROMPT_VERSION drifted: expected {EXPECTED_PROMPT_VERSION!r}, "
            f"got {il.PROMPT_VERSION!r}. Bumping PROMPT_VERSION invalidates "
            f"the cache golden; re-capture via tools/capture_el_il_goldens.py."
        )

    def test_assembled_messages_hash_stable(self):
        il = get_il()
        criterion = {
            "id": "IC-1",
            "type": "include",
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
        msgs = il._build_llm_messages_for_criterion(
            criterion, [item], PROMPT_HASH_TRUNC_CHARS
        )
        payload = json.dumps(msgs, ensure_ascii=False, sort_keys=False)
        actual = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        assert actual == EXPECTED_PROMPT_HASH, (
            f"IL prompt construction drifted.\n"
            f"  expected SHA-256 = {EXPECTED_PROMPT_HASH}\n"
            f"  got SHA-256      = {actual}\n"
            f"  Re-capture via 'python tools/capture_el_il_goldens.py "
            f"--print-hashes' if intentional."
        )
