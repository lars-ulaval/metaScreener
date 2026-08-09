
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
capture_el_il_goldens.py — Capture EL and IL byte-identity goldens.

Run ONCE with a live OPENAI_API_KEY to produce the six fixture files that
tests/test_el_regression.py and tests/test_il_regression.py replay against:

    tests/golden/el_input_v3.1.0.csv      ← post-IH survivors fed into EL
    tests/golden/el_cache_v3.1.0.json     ← LLM-response cache for EL run
    tests/golden/el_filtered_v3.1.0.csv   ← byte-identity FULL CSV from EL
    tests/golden/il_input_v3.1.0.csv      ← post-EL survivors fed into IL
    tests/golden/il_cache_v3.1.0.json     ← LLM-response cache for IL run
    tests/golden/il_filtered_v3.1.0.csv   ← byte-identity FULL CSV from IL

The cache JSON files have a small envelope:

    {
      "_invocation": {"model": "...", "trunc_chars": 4000, "batch_size": 5},
      "cache": {"<sha256>": {...}, ...}
    }

Tests read "_invocation" to drive run_*_screen with the same parameters
that produced the cache, then feed "cache" as cache_in. Subsequent runs
(in tests, in CI, in Conv 7+ refactors) hit cache for every (a_id, cid)
pair; OPENAI_API_KEY is unset so any miss short-circuits to empty
evidence, which causes the byte-identity check to fail loudly.

Usage (Windows PowerShell)::

    $env:OPENAI_API_KEY = "sk-..."
    python tools/capture_el_il_goldens.py

Usage (POSIX)::

    OPENAI_API_KEY=sk-... python tools/capture_el_il_goldens.py

Re-runs:
    Re-running this script overwrites the six fixture files. Inspect the
    diff before committing — drift in any of the goldens is a behaviour
    change that should be intentional.

Constants below (MODEL, TRUNC_CHARS, BATCH_SIZE) must match the values
used in tests/test_el_regression.py and tests/test_il_regression.py.
If you bump them here, bump them there too; the prompt-hash test will
also need re-capture (run with --print-hashes to see the new values).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

# --------------------------------------------------------------------------
# Constants (must match the corresponding test modules)
# --------------------------------------------------------------------------
MODEL = "gpt-4o-mini"
TRUNC_CHARS = 4000
BATCH_SIZE = 5

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = PROJECT_ROOT / "docs_" / "samples"
GOLDEN_DIR = PROJECT_ROOT / "tests" / "golden"

AGGREGATE_CSV = SAMPLES_DIR / "20260122_1654_aggregate.csv"
CRITERIA_CSV = GOLDEN_DIR / "criteria_harmonized_v3.1.0.csv"

EL_INPUT = GOLDEN_DIR / "el_input_v3.1.0.csv"
EL_CACHE = GOLDEN_DIR / "el_cache_v3.1.0.json"
EL_FULL = GOLDEN_DIR / "el_filtered_v3.1.0.csv"

IL_INPUT = GOLDEN_DIR / "il_input_v3.1.0.csv"
IL_CACHE = GOLDEN_DIR / "il_cache_v3.1.0.json"
IL_FULL = GOLDEN_DIR / "il_filtered_v3.1.0.csv"


# --------------------------------------------------------------------------
# Headless plugin loading (mirrors tests/conftest.py setup)
# --------------------------------------------------------------------------
def _setup_headless_imports() -> None:
    """Mock tkinter + metascreener.plugin_api so plugin modules import on
    a headless run (no X server, no plugin manager installed)."""
    import types
    tk_modules = [
        "tkinter", "tkinter.ttk", "tkinter.filedialog",
        "tkinter.messagebox", "tkinter.scrolledtext",
        "tkinter.font", "_tkinter",
    ]
    for name in tk_modules:
        if name not in sys.modules:
            sys.modules[name] = MagicMock()

    if "metascreener" not in sys.modules:
        sys.modules["metascreener"] = types.ModuleType("metascreener")
    api = types.ModuleType("metascreener.plugin_api")

    class _FakePluginMeta:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    class _FakeBasePlugin:
        def __init__(self, app=None, meta=None):
            self.app = app
            self.meta = meta

    api.PluginMeta = _FakePluginMeta            # type: ignore
    api.BasePlugin = _FakeBasePlugin            # type: ignore
    sys.modules["metascreener.plugin_api"] = api

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))


def _import_plugin(subdir: str):
    p = PROJECT_ROOT / "plugins" / subdir / "plugin.py"
    spec = importlib.util.spec_from_file_location(
        f"plugins.{subdir}.plugin", str(p)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# Pipeline staging
# --------------------------------------------------------------------------
def _run_eh_and_ih_to_get_el_input(eh, ih, parse, criteria_text: str):
    """Reproduce the EH → IH chain to obtain post-IH-survivors as EL's input."""
    # EH stage
    eh_crits = eh._load_criteria_eh_from_text(criteria_text)
    eh_full, eh_surv, _, _, _, _ = eh.run_eh_screen(
        parse, eh_crits, threading.Event(), progress_cb=None
    )
    # Build a real ParseReport from EH survivors for IH input.
    # Use eh.ParseReport (re-exported from plugins._common.parser) so the
    # shared _common/runner.py finds every attribute it expects (header,
    # rows, skipped). skipped=[] is correct: EH already filtered the
    # original parse.skipped out of eh_surv.
    ih_parse = eh.ParseReport(header=list(parse.header), rows=eh_surv, skipped=[])

    # IH stage
    ih_crits = ih._load_criteria_ih_from_text(criteria_text)
    ih_full, ih_surv, _, _, _, _ = ih.run_ih_screen(
        ih_parse, ih_crits, threading.Event(), progress_cb=None
    )
    return parse.header, ih_surv


def _write_csv_bytes(header: List[str], rows: List[Dict[str, Any]]) -> bytes:
    """LF-terminated CSV writer, identical to plugins/_common/exporters.

    Imported lazily because the capture script may be run before plugins are
    on sys.path; _setup_headless_imports() ensures the import succeeds.
    Matches the EH/IH golden convention (which writes via the same shared
    function), so all four stage goldens use the same writer.
    """
    from plugins._common.exporters import _write_csv_bytes as _shared
    return _shared(header, rows)


def _capture_el(el, el_input_header: List[str],
                el_input_rows: List[Dict[str, Any]],
                criteria_text: str) -> None:
    """Run EL and persist input fixture, cache, and FULL CSV."""
    print(f"[EL] Loading {len(el_input_rows)} post-IH survivors...")

    # Save EL input fixture
    EL_INPUT.write_bytes(_write_csv_bytes(el_input_header, el_input_rows))
    print(f"[EL]   wrote {EL_INPUT.name} ({EL_INPUT.stat().st_size} B)")

    # Build a real ParseReport using EL's own dataclass. EL's
    # run_el_screen reads parse.header and parse.rows directly (it does
    # not go through _common/runner.py), but we still use the real
    # dataclass for consistency and for forward compat once EL is
    # decomposed onto _common in Conv 6 / Commit 1+.
    parse = el.ParseReport(
        header=list(el_input_header), rows=el_input_rows, skipped=[]
    )

    el_crits = el._parse_criteria_harmonized_csv(criteria_text, "EL")
    print(f"[EL]   loaded {len(el_crits.criteria)} EL criteria")

    print("[EL] Running run_el_screen (live API calls)...")
    full_rows, _surv, counts, _impacts, _evals, cache_out, _cancelled = el.run_el_screen(
        parse, el_crits,
        model=MODEL,
        trunc_chars=TRUNC_CHARS,
        batch_size=BATCH_SIZE,
        use_cache=True,
        cache_in={},
        cancel_event=threading.Event(),
        log_cb=lambda s: print(f"  {s.rstrip()}"),
        progress_cb=None,
        progress_evt=None,
    )
    print(f"[EL]   counts: {counts}")
    print(f"[EL]   cache entries: {len(cache_out)}")

    # Save FULL CSV
    full_header = list(el_input_header) + [
        "el_outcome", "el_failed_ids", "el_missing_ids",
        "el_met_ids", "el_uncertain_ids",
        "el_evidence_json", "el_reason_summary",
    ]
    EL_FULL.write_bytes(_write_csv_bytes(full_header, full_rows))
    print(f"[EL]   wrote {EL_FULL.name} ({EL_FULL.stat().st_size} B)")

    # Save cache with envelope
    envelope = {
        "_invocation": {
            "model": MODEL,
            "trunc_chars": TRUNC_CHARS,
            "batch_size": BATCH_SIZE,
        },
        "cache": cache_out,
    }
    EL_CACHE.write_text(
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    print(f"[EL]   wrote {EL_CACHE.name} ({EL_CACHE.stat().st_size} B)")

    # Compute IL input from EL survivors
    el_survivors = [r for r in full_rows if r.get("el_outcome") != "OUT"]
    print(f"[EL] EL survivors (input for IL): {len(el_survivors)}")
    return el_survivors


def _capture_il(il, il_input_header: List[str],
                il_input_rows: List[Dict[str, Any]],
                criteria_text: str) -> None:
    """Run IL and persist input fixture, cache, and FULL CSV."""
    print(f"[IL] Loading {len(il_input_rows)} post-EL survivors...")

    # IL input is the EL survivors but with EL columns stripped — IL only
    # appends il_* columns; preserving el_* columns would conflate stages.
    # Define the IL input header as the original aggregate header (no el_*).
    base_header = [c for c in il_input_header if not c.startswith("el_")]
    base_rows = [{k: r.get(k, "") for k in base_header} for r in il_input_rows]

    IL_INPUT.write_bytes(_write_csv_bytes(base_header, base_rows))
    print(f"[IL]   wrote {IL_INPUT.name} ({IL_INPUT.stat().st_size} B)")

    # Build a real ParseReport using IL's own dataclass. Same rationale
    # as in _capture_el above.
    parse = il.ParseReport(
        header=list(base_header), rows=base_rows, skipped=[]
    )

    il_crits = il._parse_criteria_harmonized_csv(criteria_text, "IL")
    print(f"[IL]   loaded {len(il_crits.criteria)} IL criteria")

    print("[IL] Running run_il_screen (live API calls)...")
    full_rows, _surv, counts, _impacts, _evals, cache_out, _cancelled = il.run_il_screen(
        parse, il_crits,
        model=MODEL,
        trunc_chars=TRUNC_CHARS,
        batch_size=BATCH_SIZE,
        use_cache=True,
        cache_in={},
        cancel_event=threading.Event(),
        log_cb=lambda s: print(f"  {s.rstrip()}"),
        progress_cb=None,
        progress_evt=None,
    )
    print(f"[IL]   counts: {counts}")
    print(f"[IL]   cache entries: {len(cache_out)}")

    full_header = list(base_header) + [
        "il_outcome", "il_failed_ids", "il_missing_ids",
        "il_met_ids", "il_uncertain_ids",
        "il_evidence_json", "il_reason_summary",
    ]
    IL_FULL.write_bytes(_write_csv_bytes(full_header, full_rows))
    print(f"[IL]   wrote {IL_FULL.name} ({IL_FULL.stat().st_size} B)")

    envelope = {
        "_invocation": {
            "model": MODEL,
            "trunc_chars": TRUNC_CHARS,
            "batch_size": BATCH_SIZE,
        },
        "cache": cache_out,
    }
    IL_CACHE.write_text(
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    print(f"[IL]   wrote {IL_CACHE.name} ({IL_CACHE.stat().st_size} B)")


def _print_prompt_hashes(el, il) -> None:
    """Print the SHA-256 of an assembled messages list for one fixed
    (criterion, item) pair per stage. Embed these into the prompt-hash
    unit tests so prompt-construction drift is caught immediately."""
    fixed_criterion = {
        "id": "EC-2",
        "type": "exclude",
        "operator": "llm",
        "target": "title,abstract,keywords",
        "what": ["spatial navigation virtual maze"],
        "how": "llm",
        "label": "fixed-test-criterion",
        "threshold": 0.6,
    }
    fixed_item = {
        "a_id": "TEST-001",
        "title": "A study of virtual reality in cognitive rehabilitation.",
        "abstract": "We examine head-mounted display VR for stroke recovery.",
        "keywords": "virtual reality; HMD; rehabilitation",
    }

    el_msgs = el._build_llm_messages_for_criterion(
        fixed_criterion, [fixed_item], TRUNC_CHARS
    )
    el_payload = json.dumps(el_msgs, ensure_ascii=False, sort_keys=False)
    el_hash = hashlib.sha256(el_payload.encode("utf-8")).hexdigest()

    fixed_criterion_il = dict(fixed_criterion, id="IC-1", type="include")
    il_msgs = il._build_llm_messages_for_criterion(
        fixed_criterion_il, [fixed_item], TRUNC_CHARS
    )
    il_payload = json.dumps(il_msgs, ensure_ascii=False, sort_keys=False)
    il_hash = hashlib.sha256(il_payload.encode("utf-8")).hexdigest()

    print()
    print("=" * 72)
    print("Prompt-hash assertions (paste into the test files)")
    print("=" * 72)
    print(f"  el.PROMPT_VERSION       = {el.PROMPT_VERSION!r}")
    print(f"  EL prompt SHA-256       = {el_hash}")
    print(f"  il.PROMPT_VERSION       = {il.PROMPT_VERSION!r}")
    print(f"  IL prompt SHA-256       = {il_hash}")
    print("=" * 72)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--print-hashes", action="store_true",
        help="Only print prompt hashes without making API calls.",
    )
    args = ap.parse_args()

    _setup_headless_imports()
    eh = _import_plugin("04_eh")
    ih = _import_plugin("05_ih")
    el = _import_plugin("06_el")
    il = _import_plugin("07_il")

    if args.print_hashes:
        _print_prompt_hashes(el, il)
        return 0

    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is not set. Set it before running:",
              file=sys.stderr)
        print("  $env:OPENAI_API_KEY = 'sk-...'  (PowerShell)",
              file=sys.stderr)
        print("  export OPENAI_API_KEY=sk-...    (POSIX)",
              file=sys.stderr)
        return 1

    if not AGGREGATE_CSV.exists():
        print(f"ERROR: missing {AGGREGATE_CSV}", file=sys.stderr)
        return 1
    if not CRITERIA_CSV.exists():
        print(f"ERROR: missing {CRITERIA_CSV} (Conv 4 golden)", file=sys.stderr)
        return 1

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[*] Loading aggregate corpus: {AGGREGATE_CSV.name}")
    corpus_text = AGGREGATE_CSV.read_text(encoding="utf-8-sig")
    parse = eh._parse_csv_tolerant_text(corpus_text, required_id="local_id")
    print(f"[*]   {len(parse.rows)} rows, {len(parse.header)} columns")

    criteria_text = CRITERIA_CSV.read_text(encoding="utf-8-sig")

    print("[*] Reproducing EH → IH chain...")
    header_after_ih, rows_after_ih = _run_eh_and_ih_to_get_el_input(
        eh, ih, parse, criteria_text
    )
    print(f"[*]   post-IH survivors: {len(rows_after_ih)} rows")

    el_survivors = _capture_el(el, header_after_ih, rows_after_ih, criteria_text)

    # IL takes EL survivors with el_* columns stripped
    _capture_il(il, header_after_ih + [
        "el_outcome", "el_failed_ids", "el_missing_ids",
        "el_met_ids", "el_uncertain_ids",
        "el_evidence_json", "el_reason_summary",
    ], el_survivors, criteria_text)

    _print_prompt_hashes(el, il)

    print()
    print("Done. Six golden files written to tests/golden/.")
    print("Update tests/test_el_regression.py and tests/test_il_regression.py")
    print("with the prompt hashes above, then run pytest to confirm green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
