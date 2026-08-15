# -*- coding: utf-8 -*-
"""Wave 15e Part 3 — the acceptance experiment harness (HO-15e-1).

Conftest-free on purpose (the 15d lesson): the maintainer's REAL settings
store must resolve, and the endpoint is asserted local BEFORE any call.

Usage:
    python acceptance_harness_15e.py preflight     # zero calls
    python acceptance_harness_15e.py J             # batch 5, 60 calls
    python acceptance_harness_15e.py K             # batch 5 repeat, 60 calls
    python acceptance_harness_15e.py L             # batch 1, 294 calls
"""
import hashlib
import importlib.util
import json
import sys
import threading
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(r"S:/Alejandro_/projet julien (prisma-hub)/prisma-hub_v3_repo")
BUNDLE = Path(r"S:/Alejandro_/projet julien (prisma-hub)/_archive_bundles"
              r"/20260814_071007_post_EL_bundle.zip")
OUT = Path(__file__).parent / "wave15e_runs"
OUT.mkdir(exist_ok=True)

BUNDLE_SHA = "0bd1604aee1e7bf1fae825641a03659b49ee1942491fbb98bab0bf3c34a93c4b"
CURRENT_SHA = "f8115e4f5587b1887f2419b899fde3e8ec1e1605249ed415de94330c26b7b599"
CRITERIA_SHA_PREFIX = "5dd51aaa6e2f3c33"

ARMS = {"J": 5, "K": 5, "L": 1}
MODEL = "qwen2.5:7b"
TRUNC = 1500
EXPECTED_ENDPOINT = "http://localhost:11434/v1"


def _setup_headless_imports():
    import types
    for name in ("tkinter", "tkinter.ttk", "tkinter.filedialog",
                 "tkinter.messagebox", "tkinter.scrolledtext",
                 "tkinter.font", "_tkinter"):
        if name not in sys.modules:
            sys.modules[name] = MagicMock()
    if "metascreener" not in sys.modules:
        sys.modules["metascreener"] = types.ModuleType("metascreener")
    api = types.ModuleType("metascreener.plugin_api")

    class _M:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
    api.PluginMeta = _M
    api.BasePlugin = _M
    sys.modules["metascreener.plugin_api"] = api
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _import_el():
    p = ROOT / "plugins" / "06_el" / "plugin.py"
    spec = importlib.util.spec_from_file_location("plugins.06_el.plugin", str(p))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_corpus_and_criteria():
    raw = BUNDLE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == BUNDLE_SHA, "bundle digest mismatch — STOP"
    z = zipfile.ZipFile(BUNDLE)
    cur = z.read("ScreenA_Bundle/data/current.csv")
    assert hashlib.sha256(cur).hexdigest() == CURRENT_SHA, "current.csv digest mismatch — STOP"
    crit = z.read("ScreenA_Bundle/criteria/criteria_harmonized.csv")
    assert hashlib.sha256(crit).hexdigest().startswith(CRITERIA_SHA_PREFIX), "criteria digest mismatch — STOP"
    return cur.decode("utf-8-sig"), crit.decode("utf-8-sig")


def preflight(el):
    from plugins._common.llm_client import (
        resolve_openai_base_url, resolve_context_window,
        llm_exclusion_allowed, _has_openai_key)
    endpoint = resolve_openai_base_url("EL")
    window = resolve_context_window("EL")
    allow = llm_exclusion_allowed("EL")
    keyok = _has_openai_key("EL")
    facts = {
        "endpoint": endpoint,
        "context_window": window,
        "allow_exclusion": allow,
        "key_gate_passes": keyok,
        "prompt_version": el.PROMPT_VERSION,
    }
    print(json.dumps(facts, indent=2))
    assert endpoint == EXPECTED_ENDPOINT, (
        f"resolved endpoint {endpoint!r} is not the local server — REFUSING; "
        f"no call will be made")
    assert allow is False, "exclusion not flag-only — comparability with runG/H broken; REFUSING"
    assert keyok, "key gate refuses; the engine would silently skip every call"
    assert el.PROMPT_VERSION == "EL_v3_nullquote"
    corpus_text, criteria_text = _load_corpus_and_criteria()
    header, rows = el._csv_read(corpus_text)
    crits = el._parse_criteria_harmonized_csv(criteria_text, "EL")
    ids = [(c.id, c.ctype, c.operator, c.threshold) for c in crits.criteria if c.enabled]
    print("records:", len(rows), "criteria:", ids)
    assert len(rows) == 147
    assert ids == [("EC-2", "exclude", "llm", 0.6), ("EC-3", "exclude", "llm", 0.6)]
    print("PREFLIGHT OK — zero calls made.")


def run_arm(el, arm):
    batch = ARMS[arm]
    corpus_text, criteria_text = _load_corpus_and_criteria()
    header, rows = el._csv_read(corpus_text)
    parse = el.ParseReport(header=header, rows=rows, skipped=[])
    crits = el._parse_criteria_harmonized_csv(criteria_text, "EL")

    log_lines = []
    name0 = f"run{arm}_batch{batch}"
    live = open(OUT / f"{name0}_log_live.txt", "a", encoding="utf-8")

    def _log(line):
        log_lines.append(line)
        live.write(line)
        live.flush()

    def _prog(frac):
        live.write(f"[progress] {frac:.3f} t+{time.time() - t0:.0f}s\n")
        live.flush()

    t0 = time.time()
    (full_rows, surv, counts, impacts, evals, cache_out, cancelled,
     report) = el.run_el_screen(
        parse, crits, model=MODEL, trunc_chars=TRUNC, batch_size=batch,
        use_cache=False, cache_in={}, cancel_event=threading.Event(),
        log_cb=_log, progress_cb=_prog, progress_evt=None)
    dt = time.time() - t0
    live.close()

    from plugins._common.exporters import _write_csv_bytes
    fieldnames = list(parse.header) + [
        "el_outcome", "el_failed_ids", "el_missing_ids",
        "el_met_ids", "el_uncertain_ids",
        "el_evidence_json", "el_reason_summary",
    ]
    name = f"run{arm}_batch{batch}"
    (OUT / f"{name}_EL_FULL.csv").write_bytes(
        _write_csv_bytes(fieldnames, full_rows))
    (OUT / f"{name}_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / f"{name}_log.txt").write_text("".join(log_lines), encoding="utf-8")
    summary = {
        "arm": name, "batch_size": batch, "cancelled": cancelled,
        "wall_seconds": round(dt, 1), "counts": counts,
        "records": report.get("records"), "answered": report.get("answered"),
        "no_answer": report.get("no_answer"),
        "calls_made": report.get("calls_made"),
        "reasks_made": report.get("reasks_made"),
        "no_answer_after_reask": report.get("no_answer_after_reask"),
        "exclusion_policy": report.get("exclusion_policy"),
        "request_shape": report.get("request_shape"),
        "provenance": report.get("provenance"),
        "absence_suppressed_key_present": "absence_suppressed" in report,
    }
    (OUT / f"{name}_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    _setup_headless_imports()
    el = _import_el()
    what = sys.argv[1]
    if what == "preflight":
        preflight(el)
    else:
        preflight(el)          # re-asserted before every arm, zero extra calls
        run_arm(el, what)
