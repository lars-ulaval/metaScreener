# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT
"""Multi-arm criteria-diversity experiment driver (wave 16a).

Runs experiment ARMS — (criteria source, per-stage config) pairs — against the
776-record aggregate the reference chain uses, through the product's own
translation, loading, deterministic screening, prompt rendering and
context-budget machinery. Two modes:

DRY (default): ZERO network capability. The dry path never constructs an LLM
    client and never calls ``run_el_screen``/``run_il_screen`` — the only
    functions in the pipeline that can open a connection. On top of that
    structural property, ``_install_dry_guard`` replaces
    ``llm_client._openai_client_for`` with a raiser before any arm runs, so
    even a future regression that reached client construction would fail
    loudly instead of connecting. Per arm it reports: the harmonized table,
    validator/linter findings, stage landings vs recorded intent, the EH→IH
    deterministic funnel, records reaching EL/IL, the context-budget verdict
    per criterion per batch size, and exact live-call arithmetic.

LIVE (``--live``): built for wave 16b, NOT exercised at 16a. Follows the 15e
    preflight-assert pattern (docs/internal/harnesses/acceptance_harness_15e.py)
    — endpoint, exclusion policy, window, corpus/criteria digests, and models
    EXPLICIT per stage from the spec (never store-resolved for model/batch) —
    plus the 15d hard call-budget enforcer wrapping the client
    (docs/internal/harnesses/acceptance15d_live.py). Refuses before the first
    call on any mismatch.

Baseline correctness check: the ``arm0_baseline`` dry run must reproduce the
pinned chain exactly — 776 -> EH OUT 16 -> 760 -> IH OUT 738 -> 22, with
IC-5 met=70/failed=690 (tests/test_stage_routing.py::TestTheChainAsRouted).
A mismatch is a harness bug and aborts the whole run.

Usage:
    python tools/run_criteria_experiment.py                      # dry, all arms
    python tools/run_criteria_experiment.py --arm g4_edge_shapes # dry, one arm
    python tools/run_criteria_experiment.py --out DIR            # dry, custom out
    python tools/run_criteria_experiment.py --live --arm KEY --budget N \
        --yes-live   # wave 16b only; every preflight assert must pass
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import io
import json
import math
import sys
import threading
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_SPEC = PROJECT_ROOT / "docs" / "data" / "wave16_arms" / "experiment_spec.json"
DEFAULT_OUT = PROJECT_ROOT / "docs" / "data" / "wave16_arms" / "dryrun_v1"

STAGES = ("EH", "IH", "EL", "IL")

# Wall-clock rates measured at wave 15e (docs/data/wave15e_acceptance_runs/
# wave15e_acceptance_runs.meta.txt:37-39), qwen2.5:7b at localhost, same-machine
# assumption for any estimate derived from them: runJ 528s/60 calls (batch 5,
# the slower of the J/K pair, used as the conservative rate), runL 1020s/294
# (batch 1).
SECONDS_PER_CALL_BATCH5 = 528.0 / 60.0
SECONDS_PER_CALL_BATCH1 = 1020.0 / 294.0


# ---------------------------------------------------------------------------
# Headless scaffolding (tools/capture_el_il_goldens.py pattern)
# ---------------------------------------------------------------------------

def _setup_headless_imports() -> None:
    """Mock tkinter + metascreener.plugin_api so plugin modules import on a
    headless run. Must run before any plugins.* import."""
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
    if "metascreener.plugin_api" not in sys.modules:
        api = types.ModuleType("metascreener.plugin_api")

        class _FakePluginMeta:
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)

        class _FakeBasePlugin:
            def __init__(self, app=None, meta=None):
                self.app = app
                self.meta = meta

        api.PluginMeta = _FakePluginMeta  # type: ignore
        api.BasePlugin = _FakeBasePlugin  # type: ignore
        sys.modules["metascreener.plugin_api"] = api

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))


class _Mods:
    """Lazily-imported product modules, one namespace to thread around."""

    def __init__(self) -> None:
        _setup_headless_imports()
        self.common_parser = importlib.import_module("plugins._common.parser")
        self.runner = importlib.import_module("plugins._common.runner")
        self.llm_client = importlib.import_module("plugins._common.llm_client")
        self.run_estimate = importlib.import_module("plugins._common.run_estimate")
        self.h_parser = importlib.import_module("plugins.03_harmoniser.parser")
        self.h_inference = importlib.import_module("plugins.03_harmoniser.inference")
        self.h_exporters = importlib.import_module("plugins.03_harmoniser.exporters")
        self.h_linter = importlib.import_module("plugins.03_harmoniser.linter")
        self.el_screen = importlib.import_module("plugins.06_el.screen")
        self.il_screen = importlib.import_module("plugins.07_il.screen")
        self.el_prompt = importlib.import_module("plugins.06_el.prompt")
        self.il_prompt = importlib.import_module("plugins.07_il.prompt")


def _install_dry_guard(mods: _Mods) -> None:
    """Belt-and-braces on top of the structural guarantee: in dry mode the
    pipeline never calls client construction; if it ever did, raise."""

    def _refuse(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError(
            "dry mode: LLM client construction is forbidden; no network call "
            "can be made in this mode")

    mods.llm_client._openai_client_for = _refuse  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def calls_for(records: int, criteria: int, batch_size: int) -> int:
    """The engine's exact live-call arithmetic (run_estimate.py:100-125):
    per-criterion ceiling division summed, never mixing criteria."""
    if records <= 0 or criteria <= 0:
        return 0
    size = max(1, int(batch_size))
    return (-(-records // size)) * criteria


def wall_clock_seconds(calls: int, batch_size: int) -> float:
    rate = SECONDS_PER_CALL_BATCH5 if batch_size >= 2 else SECONDS_PER_CALL_BATCH1
    return calls * rate


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------

REQUIRED_ARM_FIELDS = ("key", "kind", "source")
ARM_KINDS = ("free_text", "harmonized_csv", "derived_rows")


def load_spec(path: Path) -> Dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec.get("spec_version") != 1:
        raise ValueError(f"unsupported spec_version: {spec.get('spec_version')!r}")
    for field in ("corpus", "corpus_sha256", "window", "trunc_chars", "arms"):
        if field not in spec:
            raise ValueError(f"spec missing required field: {field}")
    keys = set()
    for arm in spec["arms"]:
        for field in REQUIRED_ARM_FIELDS:
            if field not in arm:
                raise ValueError(f"arm missing required field {field}: {arm}")
        if arm["kind"] not in ARM_KINDS:
            raise ValueError(f"arm {arm['key']}: unknown kind {arm['kind']!r}")
        if arm["key"] in keys:
            raise ValueError(f"duplicate arm key: {arm['key']}")
        keys.add(arm["key"])
        if arm["kind"] == "derived_rows":
            for field in ("derive_from", "ids", "stage"):
                if not arm.get(field):
                    raise ValueError(
                        f"derived arm {arm['key']}: missing {field}")
            if arm["stage"] not in ("EL", "IL"):
                raise ValueError(
                    f"derived arm {arm['key']}: stage must be EL or IL")
            if "corpus_bundle" not in spec:
                raise ValueError(
                    "derived arms require a spec-level corpus_bundle")
    for arm in spec["arms"]:
        if arm["kind"] == "derived_rows":
            if not any(a["key"] == arm["derive_from"] for a in spec["arms"]
                       if a["kind"] == "free_text"):
                raise ValueError(
                    f"derived arm {arm['key']}: derive_from must name a "
                    f"free_text arm")
    return spec


def resolve_bundle_corpus(mods: _Mods, bundle_cfg: Dict[str, Any]) -> Tuple[Any, Dict[str, Any]]:
    """Locate the corpus bundle BY MANIFEST CONTENT, never by filename: scan
    the directory's zips, match the manifest's own sha256 map against the
    spec's member digests, then verify member bytes and the whole-zip digest
    before trusting anything. Returns (ParseReport, identification block)."""
    bdir = Path(bundle_cfg["dir"])
    want_members: Dict[str, str] = bundle_cfg["member_sha256"]
    want_crit_prefix = bundle_cfg.get("criteria_member_sha256_prefix", "")
    matches = []
    for zp in sorted(bdir.glob("*.zip")):
        try:
            with zipfile.ZipFile(zp) as z:
                man_names = [n for n in z.namelist()
                             if n.endswith("manifest.json") and n.count("/") <= 1]
                if not man_names:
                    continue
                manifest = json.loads(z.read(man_names[0]).decode("utf-8"))
        except Exception:
            continue
        sha_map = manifest.get("sha256") or {}
        if all(sha_map.get(m) == d for m, d in want_members.items()) and (
                not want_crit_prefix or str(sha_map.get(
                    "criteria/criteria_harmonized.csv", "")).startswith(
                        want_crit_prefix)):
            matches.append((zp, man_names[0], manifest, sha_map))
    if not matches:
        raise SystemExit(
            f"bundle identification by manifest content matched no zip in "
            f"{bdir} — refusing")
    # Manifest content under-determines the artifact: same-state re-exports
    # carry identical manifest digests in byte-different zips (measured: six
    # such siblings for the 15e input). Disambiguate inside the equivalence
    # class by the whole-zip digest — still content, never the filename.
    want_zip_sha = bundle_cfg.get("zip_sha256")
    if len(matches) > 1 and not want_zip_sha:
        raise SystemExit(
            f"bundle identification matched {len(matches)} same-state zips "
            f"and the spec pins no zip_sha256 to pick one — refusing")
    chosen = []
    for zp, man_name, manifest, sha_map in matches:
        zip_bytes = zp.read_bytes()
        got = _sha256_bytes(zip_bytes)
        if not want_zip_sha or got == want_zip_sha:
            chosen.append((zp, man_name, manifest, sha_map, zip_bytes, got))
    if len(chosen) != 1:
        raise SystemExit(
            f"bundle identification: {len(matches)} manifest-content matches, "
            f"{len(chosen)} surviving the zip-digest pin — refusing "
            f"(need exactly 1)")
    zp, man_name, manifest, sha_map, zip_bytes, got_zip_sha = chosen[0]
    root = man_name[: -len("manifest.json")]
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        member_bytes = {m: z.read(root + m) for m in want_members}
        crit_bytes = z.read(root + "criteria/criteria_harmonized.csv")
    for m, want in want_members.items():
        got = _sha256_bytes(member_bytes[m])
        if got != want:
            raise SystemExit(f"bundle member {m} digest {got} != {want}")
    crit_sha = _sha256_bytes(crit_bytes)
    if want_crit_prefix and not crit_sha.startswith(want_crit_prefix):
        raise SystemExit(
            f"bundle criteria member digest {crit_sha[:12]} lacks the "
            f"expected prefix {want_crit_prefix}")
    corpus_text = member_bytes["data/current.csv"].decode("utf-8-sig")
    parse = mods.common_parser._parse_csv_tolerant_text(corpus_text)
    expected = int(bundle_cfg.get("expected_records", 0))
    if expected and len(parse.rows) != expected:
        raise SystemExit(
            f"bundle corpus has {len(parse.rows)} records, expected {expected}")
    ident = {
        "identified_by": "manifest content (member sha256 map), then byte "
                         "verification; filename recorded as opaque key only",
        "zip_opaque_key": zp.name,
        "zip_sha256": got_zip_sha,
        "manifest_created_at": manifest.get("created_at"),
        "manifest_created_by": manifest.get("created_by"),
        "member_sha256_verified": {m: _sha256_bytes(b)
                                   for m, b in member_bytes.items()},
        "criteria_member_sha256": crit_sha,
        "records": len(parse.rows),
        "population_banner": bundle_cfg.get("population_banner", ""),
    }
    return parse, ident


def derive_rows_from_parent(mods: _Mods, spec: Dict[str, Any],
                            arm: Dict[str, Any], a_columns: List[str],
                            text_stats: Dict[str, float]) -> Tuple[List[Dict[str, Any]], str, str]:
    """Translate the parent free-text arm and keep only the named ids. The
    derived CSV's data rows must be BYTE-IDENTICAL to the parent's harmonized
    output rows — asserted line-by-line. Returns (rows, derived_csv_text,
    parent_harmonized_sha256)."""
    parent = next(a for a in spec["arms"] if a["key"] == arm["derive_from"])
    parent_text = _read_text(PROJECT_ROOT / parent["source"])
    parent_rows = translate_free_text(mods, parent_text, a_columns, text_stats)
    parent_csv = mods.h_exporters._criteria_csv_text(parent_rows)
    keep = [r for r in parent_rows if r["id"] in set(arm["ids"])]
    if len(keep) != len(arm["ids"]):
        raise SystemExit(
            f"derived arm {arm['key']}: ids {arm['ids']} not all present in "
            f"parent {arm['derive_from']}")
    derived_csv = mods.h_exporters._criteria_csv_text(keep)
    parent_lines = set(parent_csv.splitlines())
    derived_lines = derived_csv.splitlines()
    for line in derived_lines[1:]:  # skip header, compare data rows
        if line not in parent_lines:
            raise SystemExit(
                f"derived arm {arm['key']}: row not byte-identical to the "
                f"parent's harmonized output: {line[:80]!r}")
    return keep, derived_csv, _sha256_bytes(parent_csv.encode("utf-8"))


# ---------------------------------------------------------------------------
# Criteria production per arm
# ---------------------------------------------------------------------------

def translate_free_text(mods: _Mods, text: str, a_columns: List[str],
                        text_stats: Dict[str, float]) -> List[Dict[str, Any]]:
    """The GUI's free-text harmonise path, no LLM, no widgets — the same call
    sequence tests/test_harmoniser_regression.py::_build_rows reproduces."""
    h_parser, h_inf = mods.h_parser, mods.h_inference
    default_text_target = h_parser._get_best_text_targets(a_columns, text_stats)
    default_text_target, _ = h_parser._canonicalize_targets(default_text_target, a_columns)
    rows: List[Dict[str, Any]] = []
    for crit_id, crit_type, label, source_line in h_parser._parse_free_text_criteria(text):
        inferred = h_inf._infer_criterion_details(
            crit_id=crit_id, crit_type=crit_type, label=label,
            a_columns=list(a_columns), default_text_target=default_text_target,
        )
        stage = inferred["stage"]
        rows.append({
            "stage": stage, "id": crit_id, "type": crit_type, "scope": "metadata",
            "label": label, "operator": inferred["operator"],
            "target": inferred["target"], "what": inferred["what"],
            "threshold": f"{h_inf.DEFAULT_THRESHOLD:.2f}" if stage in {"EL", "IL"} else "",
            "enabled": True, "source_text": source_line,
        })
    return rows


def rows_from_harmonized_csv(mods: _Mods, csv_text: str) -> List[Dict[str, Any]]:
    """Hand-authored harmonized CSV -> normalized row dicts, via the same
    structured-row normalizer the harmoniser's table import uses
    (plugins/03_harmoniser/parser.py::_normalize_structured_row)."""
    reader = csv.DictReader(io.StringIO(csv_text))
    return [mods.h_parser._normalize_structured_row(dict(r)) for r in reader]


def validator_pass(mods: _Mods, rows: List[Dict[str, Any]],
                   a_columns: List[str]) -> Dict[str, Dict[str, List[str]]]:
    """_validate_row per row (on copies — it mutates), keyed by criterion id."""
    out: Dict[str, Dict[str, List[str]]] = {}
    for row in rows:
        errs, warns = mods.h_inference._validate_row(dict(row), a_columns)
        out[str(row.get("id", "?"))] = {"errors": errs, "warnings": warns}
    return out


def linter_pass(mods: _Mods, rows: List[Dict[str, Any]], a_columns: List[str],
                corpus_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    report = mods.h_linter.lint_criteria(rows, a_columns, corpus_rows)
    return [{
        "criterion_id": f.criterion_id, "check": f.check,
        "severity": f.severity, "message": f.message,
    } for f in report]


# ---------------------------------------------------------------------------
# Stage landings + chain
# ---------------------------------------------------------------------------

def stage_landings(mods: _Mods, csv_text: str) -> Dict[str, Any]:
    """Load the harmonized CSV per stage exactly as the product does:
    _load_criteria_from_text for EH/IH; _parse_criteria_harmonized_csv for
    EL/IL. Returns per-stage (id, operator, enabled) plus loader warnings."""
    out: Dict[str, Any] = {"stages": {}, "loader_warnings": {}}
    for stage in ("EH", "IH"):
        rep = mods.common_parser._load_criteria_from_text(csv_text, stage)
        out["stages"][stage] = [
            {"id": c.cid, "operator": c.operator, "type": c.ctype, "enabled": c.enabled}
            for c in rep.criteria]
        out["loader_warnings"][stage] = list(rep.warnings)
    for stage, screen in (("EL", mods.el_screen), ("IL", mods.il_screen)):
        rep = screen._parse_criteria_harmonized_csv(csv_text, stage_filter=stage)
        out["stages"][stage] = [
            {"id": c.id, "operator": c.operator, "type": c.ctype, "enabled": c.enabled}
            for c in rep.criteria]
        out["loader_warnings"][stage] = list(rep.warnings)
    return out


def landings_vs_intent(landings: Dict[str, Any],
                       intents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    landed_by_id: Dict[str, List[Tuple[str, str]]] = {}
    for stage in STAGES:
        for c in landings["stages"].get(stage, []):
            landed_by_id.setdefault(c["id"], []).append((stage, c["operator"]))
    diff = []
    for intent in intents:
        cid = intent["id"]
        landed = landed_by_id.get(cid, [])
        landed_stages = sorted({s for s, _ in landed})
        landed_ops = sorted({op for _, op in landed})
        match = (landed_stages == [intent["intended_stage"]]
                 and landed_ops == [intent["intended_operator"]])
        diff.append({
            "id": cid,
            "intended_stage": intent["intended_stage"],
            "intended_operator": intent["intended_operator"],
            "landed_stages": landed_stages,
            "landed_operators": landed_ops,
            "match": match,
            "rationale": intent.get("rationale", ""),
        })
    intended_ids = {i["id"] for i in intents}
    for cid, landed in landed_by_id.items():
        if cid not in intended_ids:
            diff.append({
                "id": cid, "intended_stage": None, "intended_operator": None,
                "landed_stages": sorted({s for s, _ in landed}),
                "landed_operators": sorted({op for _, op in landed}),
                "match": False, "rationale": "UNDECLARED: no recorded intent",
            })
    return diff


def run_chain(mods: _Mods, parse: Any, csv_text: str) -> Dict[str, Any]:
    """EH then IH via the shared deterministic engine, with the survivor
    re-wrap from TestTheChainAsRouted (tests/test_stage_routing.py:230-243)."""
    cp, runner = mods.common_parser, mods.runner
    ev = threading.Event()
    _f, surv_eh, c_eh, imp_eh, _r, cancelled = runner.run_screen(
        parse, cp._load_criteria_from_text(csv_text, "EH"), ev, stage="EH")
    assert not cancelled
    pr = cp.ParseReport(header=parse.header, rows=surv_eh, skipped=[])
    _f, surv_ih, c_ih, imp_ih, _r, cancelled = runner.run_screen(
        pr, cp._load_criteria_from_text(csv_text, "IH"), ev, stage="IH")
    assert not cancelled
    return {
        "input": len(parse.rows),
        "eh": {"out": c_eh["OUT"], "survivors": len(surv_eh),
               "pass_flagged": c_eh.get("PASS_FLAGGED", 0), "impacts": imp_eh},
        "ih": {"out": c_ih["OUT"], "survivors": len(surv_ih),
               "pass_flagged": c_ih.get("PASS_FLAGGED", 0), "impacts": imp_ih},
        "records_at_el": len(surv_ih),
        # Flag-only policy: LLM verdicts may flag but not exclude
        # (llm_exclusion_allowed False for EL and IL under the maintainer's
        # store), and deterministic operators at EL are not evaluated — so EL
        # removes nothing and IL sees the same records.
        "records_at_il": len(surv_ih),
        "il_input_assumption": "flag_only: EL removes no records; IL input = EL input",
        "survivor_rows_ih": surv_ih,
    }


# ---------------------------------------------------------------------------
# Prompt render + context budget + arithmetic
# ---------------------------------------------------------------------------

def _items_from_rows(header: List[str], rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Exact item construction from plugins/06_el/screen.py:581-592."""
    header_map = {h.lower(): h for h in (header or [])}

    def getv(row: Dict[str, str], key: str) -> str:
        k = header_map.get(key.lower(), key)
        v = row.get(k, "")
        return "" if v is None else str(v)

    return [{
        "a_id": getv(r, "local_id").strip(),
        "title": getv(r, "title"),
        "abstract": getv(r, "abstract"),
        "keywords": getv(r, "keywords"),
    } for r in rows]


def _crit_pack(c: Any) -> Dict[str, Any]:
    """Guard-pack shape from plugins/06_el/screen.py:711-720."""
    return {
        "id": c.id, "type": c.ctype, "operator": c.operator,
        "target": ",".join(c.targets), "what": c.what_list,
        "how": "llm", "label": c.label or c.source_text,
        "threshold": c.threshold,
    }


def budget_pass(mods: _Mods, stage: str, csv_text: str, header: List[str],
                rows: List[Dict[str, str]], batch_sizes: List[int],
                window: int, trunc_chars: int) -> Dict[str, Any]:
    """check_context_budget per llm criterion per batch size, with the stage's
    real prompt builder — the engine's own pre-run guard, run standalone."""
    screen = mods.el_screen if stage == "EL" else mods.il_screen
    prompt = mods.el_prompt if stage == "EL" else mods.il_prompt
    rep = screen._parse_criteria_harmonized_csv(csv_text, stage_filter=stage)
    llm_crits = [c for c in rep.criteria if c.enabled and c.operator == "llm"]
    items = _items_from_rows(header, rows)
    out: Dict[str, Any] = {"llm_criteria": [c.id for c in llm_crits], "batches": {}}
    for b in batch_sizes:
        per_crit = {}
        for c in llm_crits:
            r = mods.llm_client.check_context_budget(
                criteria=[_crit_pack(c)], items=items, batch_size=b,
                trunc_chars=trunc_chars,
                build_messages=prompt._build_llm_messages_for_criterion,
                window=window)
            per_crit[c.id] = {
                "ok": r.ok, "worst_estimate": r.worst_estimate,
                "reserve": r.reserve, "n_batches": r.n_batches,
                "max_safe_batch": r.max_safe_batch,
                "message": r.message,
            }
        all_ok = all(v["ok"] for v in per_crit.values()) if per_crit else True
        out["batches"][str(b)] = {"ok": all_ok, "per_criterion": per_crit}
    return out


def arithmetic(mods: _Mods, records_el: int, records_il: int,
               n_el: int, n_il: int, batch_sizes: List[int]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"reasks_expected": 0}
    for b in batch_sizes:
        el_calls = calls_for(records_el, n_el, b)
        il_calls = calls_for(records_il, n_il, b)
        # Cross-check the local formula against the product's own RunPlan.
        assert el_calls == mods.run_estimate.RunPlan(
            records=records_el, criteria=n_el, batch_size=b).requests
        assert il_calls == mods.run_estimate.RunPlan(
            records=records_il, criteria=n_il, batch_size=b).requests
        total = el_calls + il_calls
        out[f"batch{b}"] = {
            "EL": el_calls, "IL": il_calls, "total": total,
            "wall_clock_s_est": round(wall_clock_seconds(total, b), 1),
        }
    return out


# ---------------------------------------------------------------------------
# The raw bundle-read probe (F-205/F-208 semantics, deliberate edges)
# ---------------------------------------------------------------------------

def raw_probe(mods: _Mods, csv_text: str) -> Dict[str, Any]:
    """Feed a raw CSV through all four bundle-read loaders and record what
    each one does — no validator, exactly the bundle-read semantics."""
    out: Dict[str, Any] = {}
    for stage in ("EH", "IH"):
        rep = mods.common_parser._load_criteria_from_text(csv_text, stage)
        out[stage] = {
            "loaded": [{"id": c.cid, "operator": c.operator, "enabled": c.enabled}
                       for c in rep.criteria],
            "warnings": list(rep.warnings),
        }
    for stage, screen in (("EL", mods.el_screen), ("IL", mods.il_screen)):
        rep = screen._parse_criteria_harmonized_csv(csv_text, stage_filter=stage)
        out[stage] = {
            "loaded": [{"id": c.id, "operator": c.operator, "enabled": c.enabled}
                       for c in rep.criteria],
            "warnings": list(rep.warnings),
        }
    return out


# ---------------------------------------------------------------------------
# Dry run per arm
# ---------------------------------------------------------------------------

def run_arm_dry(mods: _Mods, spec: Dict[str, Any], arm: Dict[str, Any],
                parse: Any, a_columns: List[str],
                text_stats: Dict[str, float]) -> Dict[str, Any]:
    src = PROJECT_ROOT / arm["source"]
    src_text = _read_text(src)
    window = int(spec["window"])
    trunc = int(spec["trunc_chars"])
    batches = [int(b) for b in spec.get("batch_sizes_reported", [5, 1])]

    if arm["kind"] == "derived_rows":
        return _run_derived_arm_dry(mods, spec, arm, a_columns, text_stats,
                                    window, trunc, batches)

    if arm["kind"] == "free_text":
        rows = translate_free_text(mods, src_text, a_columns, text_stats)
        harmonized_text = mods.h_exporters._criteria_csv_text(rows)
    else:
        rows = rows_from_harmonized_csv(mods, src_text)
        harmonized_text = src_text

    validator = validator_pass(mods, rows, a_columns)
    linter = linter_pass(mods, rows, a_columns, parse.rows)
    landings = stage_landings(mods, harmonized_text)
    # Intents with intended_stage None describe raw-probe rows; their
    # expectations are checked by the raw_probe section, not the main table.
    main_intents = [i for i in arm.get("intents", [])
                    if i.get("intended_stage") is not None]
    diff = landings_vs_intent(landings, main_intents)
    chain = run_chain(mods, parse, harmonized_text)

    surv = chain.pop("survivor_rows_ih")
    budget = {
        "EL": budget_pass(mods, "EL", harmonized_text, parse.header, surv,
                          batches, window, trunc),
        "IL": budget_pass(mods, "IL", harmonized_text, parse.header, surv,
                          batches, window, trunc),
    }
    n_el = len(budget["EL"]["llm_criteria"])
    n_il = len(budget["IL"]["llm_criteria"])
    calls = arithmetic(mods, chain["records_at_el"], chain["records_at_il"],
                       n_el, n_il, batches)

    manifest: Dict[str, Any] = {
        "arm": arm["key"],
        "kind": arm["kind"],
        "source": arm["source"],
        "source_sha256": _sha256_bytes(src.read_bytes()),
        "harmonized_sha256": _sha256_bytes(harmonized_text.encode("utf-8")),
        "corpus": spec["corpus"],
        "corpus_sha256": spec["corpus_sha256"],
        "window": window,
        "trunc_chars": trunc,
        "generated_by": "tools/run_criteria_experiment.py (dry mode, zero calls)",
        "harmonized_rows": [{
            "stage": r.get("stage"), "id": r.get("id"), "type": r.get("type"),
            "operator": r.get("operator"), "target": r.get("target"),
            "what": r.get("what"), "threshold": r.get("threshold"),
            "enabled": r.get("enabled"),
        } for r in rows],
        "validator": validator,
        "linter": linter,
        "landings": landings,
        "landings_vs_intent": diff,
        "funnel": chain,
        "budget_guard": budget,
        "call_arithmetic": calls,
    }

    if arm.get("raw_probe"):
        probe_path = PROJECT_ROOT / arm["raw_probe"]
        manifest["raw_probe"] = {
            "source": arm["raw_probe"],
            "source_sha256": _sha256_bytes(probe_path.read_bytes()),
            "loaders": raw_probe(mods, _read_text(probe_path)),
        }

    pin = arm.get("pin")
    if pin:
        got = {
            "input": chain["input"], "eh_out": chain["eh"]["out"],
            "eh_surv": chain["eh"]["survivors"], "ih_out": chain["ih"]["out"],
            "ih_surv": chain["ih"]["survivors"],
        }
        want = pin["chain"]
        impacts_ok = all(
            chain["ih"]["impacts"].get(cid, {}).get(k) == v
            for cid, kv in pin.get("ih_impacts", {}).items()
            for k, v in kv.items())
        manifest["pin_check"] = {"want": want, "got": got,
                                "ok": got == want and impacts_ok}
        if not manifest["pin_check"]["ok"]:
            raise SystemExit(
                f"BASELINE PIN FAILED for {arm['key']}: want {want}, got {got}, "
                f"impacts_ok={impacts_ok}. The harness is wrong — STOPPING; do "
                f"not touch the pinned test.")
    return manifest


def _run_derived_arm_dry(mods: _Mods, spec: Dict[str, Any], arm: Dict[str, Any],
                         a_columns: List[str], text_stats: Dict[str, float],
                         window: int, trunc: int,
                         batches: List[int]) -> Dict[str, Any]:
    """Supplement arms (wave 16a-deltas): rows derived byte-identically from a
    free-text arm's harmonized output, run at ONE LLM stage over a bundle
    corpus identified by manifest content. No deterministic chain runs — the
    bundle's data/current.csv IS the stage population, with its F-168-style
    banner carried on every artifact."""
    stage = arm["stage"]
    rows, derived_csv, parent_sha = derive_rows_from_parent(
        mods, spec, arm, a_columns, text_stats)
    bundle_parse, ident = resolve_bundle_corpus(mods, spec["corpus_bundle"])
    bundle_cols = list(bundle_parse.header)

    validator = validator_pass(mods, rows, bundle_cols)
    linter = linter_pass(mods, rows, bundle_cols, bundle_parse.rows)
    landings = stage_landings(mods, derived_csv)
    diff = landings_vs_intent(landings, [i for i in arm.get("intents", [])
                                         if i.get("intended_stage") is not None])
    n_records = len(bundle_parse.rows)
    budget = {
        "EL": budget_pass(mods, "EL", derived_csv, bundle_parse.header,
                          bundle_parse.rows, batches, window, trunc),
        "IL": budget_pass(mods, "IL", derived_csv, bundle_parse.header,
                          bundle_parse.rows, batches, window, trunc),
    }
    n_el = len(budget["EL"]["llm_criteria"])
    n_il = len(budget["IL"]["llm_criteria"])
    records_el = n_records if n_el else 0
    records_il = n_records if n_il else 0
    calls = arithmetic(mods, records_el, records_il, n_el, n_il, batches)

    return {
        "arm": arm["key"],
        "kind": arm["kind"],
        "source": arm["source"],
        "derive_from": arm["derive_from"],
        "derived_ids": arm["ids"],
        "stage": stage,
        "source_sha256": _sha256_bytes((PROJECT_ROOT / arm["source"]).read_bytes()),
        "parent_harmonized_sha256": parent_sha,
        "harmonized_sha256": _sha256_bytes(derived_csv.encode("utf-8")),
        "byte_identity": "every derived data row appears verbatim in the "
                         "parent arm's harmonized CSV (asserted)",
        "corpus_bundle": ident,
        "population_banner": ident["population_banner"],
        "window": window,
        "trunc_chars": trunc,
        "generated_by": "tools/run_criteria_experiment.py (dry mode, zero calls)",
        "harmonized_rows": [{
            "stage": r.get("stage"), "id": r.get("id"), "type": r.get("type"),
            "operator": r.get("operator"), "target": r.get("target"),
            "what": r.get("what"), "threshold": r.get("threshold"),
            "enabled": r.get("enabled"),
        } for r in rows],
        "validator": validator,
        "linter": linter,
        "landings": landings,
        "landings_vs_intent": diff,
        "funnel": {
            "input": n_records,
            "eh": {"out": "", "survivors": "", "pass_flagged": "", "impacts": {}},
            "ih": {"out": "", "survivors": "", "pass_flagged": "", "impacts": {}},
            "records_at_el": records_el,
            "records_at_il": records_il,
            "il_input_assumption": "single-stage supplement arm: the bundle "
                                   "population is the stage input directly; "
                                   "no deterministic chain runs",
        },
        "budget_guard": budget,
        "call_arithmetic": calls,
    }


def summarize(manifests: List[Dict[str, Any]], ceiling: Optional[int]) -> List[Dict[str, Any]]:
    rows = []
    for m in manifests:
        b5 = m["call_arithmetic"].get("batch5", {})
        b1 = m["call_arithmetic"].get("batch1", {})
        guard5 = m["budget_guard"]
        worst5 = 0
        for stage in ("EL", "IL"):
            for v in guard5[stage]["batches"].get("5", {}).get("per_criterion", {}).values():
                worst5 = max(worst5, v["worst_estimate"] + v["reserve"])
        rows.append({
            "arm": m["arm"],
            "kind": m["kind"],
            "criteria": len(m["harmonized_rows"]),
            "validator_errors": sum(len(v["errors"]) for v in m["validator"].values()),
            "linter_findings": len(m["linter"]),
            "landings_match": sum(1 for d in m["landings_vs_intent"] if d["match"]),
            "landings_total": len(m["landings_vs_intent"]),
            "eh_out": m["funnel"]["eh"]["out"],
            "ih_out": m["funnel"]["ih"]["out"],
            "records_at_el": m["funnel"]["records_at_el"],
            "el_llm_criteria": len(m["budget_guard"]["EL"]["llm_criteria"]),
            "il_llm_criteria": len(m["budget_guard"]["IL"]["llm_criteria"]),
            "guard_ok_batch5": all(
                guard5[s]["batches"].get("5", {}).get("ok", True) for s in ("EL", "IL")),
            "guard_worst_est_plus_reserve_batch5": worst5,
            "calls_batch5": b5.get("total", 0),
            "calls_batch1": b1.get("total", 0),
            "wall_clock_min_batch5": round(b5.get("wall_clock_s_est", 0.0) / 60.0, 1),
        })
    total5 = sum(r["calls_batch5"] for r in rows)
    total1 = sum(r["calls_batch1"] for r in rows)
    rows.append({
        "arm": "TOTAL", "kind": "", "criteria": "", "validator_errors": "",
        "linter_findings": "", "landings_match": "", "landings_total": "",
        "eh_out": "", "ih_out": "", "records_at_el": "",
        "el_llm_criteria": "", "il_llm_criteria": "",
        "guard_ok_batch5": "",
        "guard_worst_est_plus_reserve_batch5": "",
        "calls_batch5": total5, "calls_batch1": total1,
        "wall_clock_min_batch5": round(
            sum(float(r["wall_clock_min_batch5"] or 0) for r in rows[:-1]
                if isinstance(r["wall_clock_min_batch5"], float)), 1)
        if rows else 0,
    })
    if ceiling is not None and total5 > ceiling:
        print(f"WARNING: batch-5 cross-arm total {total5} EXCEEDS the "
              f"{ceiling}-call ceiling — do not tighten unilaterally; "
              f"propose a reduction to the maintainer.")
    return rows


# ---------------------------------------------------------------------------
# Live mode (wave 16b) — built at 16a, NOT exercised. The preflight refuses
# before the first call on any mismatch; the budget enforcer is a hard stop.
# ---------------------------------------------------------------------------

DRY_MANIFEST_DIR = PROJECT_ROOT / "docs" / "data" / "wave16_arms" / "dryrun_v1"


def live_preflight(mods: _Mods, spec: Dict[str, Any], arm: Dict[str, Any],
                   parse: Any, harmonized_text: str,
                   dry_manifest_dir: Path = DRY_MANIFEST_DIR) -> Dict[str, Any]:
    """15e pattern: assert everything, spend nothing. Models and batch sizes
    come EXPLICITLY from the arm's live config — never store-resolved. Every
    assertion here REFUSES the run rather than spending a call on a
    configuration nobody declared."""
    lc = mods.llm_client
    live = arm.get("live") or spec.get("live_defaults")
    if not live:
        raise SystemExit("live: no live config for this arm and no live_defaults")
    for stage in ("EL", "IL"):
        if not live.get("model", {}).get(stage):
            raise SystemExit(f"live: model for {stage} must be explicit in the spec")
        if not live.get("batch_size", {}).get(stage):
            raise SystemExit(f"live: batch_size for {stage} must be explicit in the spec")
    if live.get("use_cache") is not False:
        raise SystemExit("live: spec must declare use_cache false (F-101) — REFUSING")
    facts: Dict[str, Any] = {}
    for stage in ("EL", "IL"):
        endpoint = lc.resolve_openai_base_url(stage)
        window = lc.resolve_context_window(stage)
        allow = lc.llm_exclusion_allowed(stage)
        keyok = lc._has_openai_key(stage)
        facts[stage] = {"endpoint": endpoint, "window": window,
                        "allow_exclusion": allow, "key_gate_passes": keyok,
                        "model_explicit": live["model"][stage],
                        "batch_size_explicit": live["batch_size"][stage]}
        expected_endpoint = spec.get("expected_endpoint", "http://localhost:11434/v1")
        assert endpoint == expected_endpoint, (
            f"resolved {stage} endpoint {endpoint!r} != expected "
            f"{expected_endpoint!r} — REFUSING; no call will be made")
        assert allow is False, (
            f"{stage} exclusion not flag-only — REFUSING")
        assert keyok, f"{stage} key gate refuses; engine would skip every call"
        assert window == int(spec["window"]), (
            f"{stage} window {window} != spec window {spec['window']} — REFUSING")
    # Corpus: the aggregate for chained arms, the bundle for derived arms.
    if arm["kind"] == "derived_rows":
        _p, ident = resolve_bundle_corpus(mods, spec["corpus_bundle"])
        assert ident["records"] == len(parse.rows), (
            f"bundle population {ident['records']} != parse rows "
            f"{len(parse.rows)} — REFUSING")
        facts["corpus"] = {"kind": "bundle", "zip_sha256": ident["zip_sha256"],
                           "members": ident["member_sha256_verified"],
                           "records": ident["records"],
                           "population_banner": ident["population_banner"]}
    else:
        corpus_bytes = (PROJECT_ROOT / spec["corpus"]).read_bytes()
        got = _sha256_bytes(corpus_bytes)
        assert got == spec["corpus_sha256"], (
            f"corpus digest {got} != {spec['corpus_sha256']} — REFUSING")
        facts["corpus"] = {"kind": "aggregate", "sha256": got,
                           "records": len(parse.rows)}
    # The criteria this arm will actually screen with must be the criteria the
    # dry run measured, byte for byte.
    crit_sha = _sha256_bytes(harmonized_text.encode("utf-8"))
    dry_path = dry_manifest_dir / f"{arm['key']}_manifest.json"
    dry = json.loads(dry_path.read_text(encoding="utf-8"))
    assert crit_sha == dry["harmonized_sha256"], (
        f"criteria digest {crit_sha[:12]} != dry manifest "
        f"{dry['harmonized_sha256'][:12]} — REFUSING")
    facts["criteria_sha256"] = crit_sha
    facts["dry_manifest_sha256"] = dry["harmonized_sha256"]
    facts["prompt_versions"] = {"EL": mods.el_prompt.PROMPT_VERSION,
                                "IL": mods.il_prompt.PROMPT_VERSION}
    for stage, want in (("EL", "EL_v3_nullquote"), ("IL", "IL_v3_nullquote")):
        got = facts["prompt_versions"][stage]
        assert got == want, f"{stage} prompt version {got!r} != {want!r} — REFUSING"
    facts["cache"] = {"use_cache": False, "cache_in": "{}"}
    print(json.dumps(facts, indent=2))
    print("LIVE PREFLIGHT OK — zero calls made so far.")
    return facts


class _BudgetEnforcedClient:
    """15d pattern: hard call budget around the real client."""

    def __init__(self, real: Any, counter: Dict[str, int], budget: int) -> None:
        outer = real

        class _Completions:
            def create(self, **kw: Any) -> Any:
                counter["n"] += 1
                assert counter["n"] <= budget, (
                    f"live budget exceeded: call {counter['n']} > declared {budget}")
                return outer.chat.completions.create(**kw)

        self.chat = type("Chat", (), {"completions": _Completions()})()


class AnomalyStop(RuntimeError):
    """A named wave-16b anomaly stop. Artifacts are written before this is
    raised; the run pauses and waits for the maintainer."""


def _check_anomalies(stage: str, counts: Dict[str, int], report: Dict[str, Any],
                     declared: int, spent: int) -> List[str]:
    """The wave-16b anomaly stops, evaluated on one stage's outcome."""
    stops: List[str] = []
    out = int(counts.get("OUT", 0) or 0)
    if out > 0:
        stops.append(
            f"ANOMALY[record-removed-at-{stage}]: counts OUT={out}; every arm "
            f"predicted 0 removals under flag-only — gate/policy regression")
    if spent > declared:
        stops.append(
            f"ANOMALY[budget-exceeded-at-{stage}]: calls_made={spent} > "
            f"declared={declared}; the enforcer should have made this impossible")
    # Rule (c): an absence-justified removal is never auto-acted — it routes
    # through `_excluded_by(..., allow_exclusion=False)` into the SUPPRESSED
    # bucket (plugins/06_el/screen.py:921-932). So absence verdicts must show
    # up as EXCLUSION_SUPPRESSED records and never as removals. (There is no
    # "absence_removed" key in the report — the counter the engine keeps is
    # `absence_suppressed`, presence-by-key, and its absence means zero.)
    absence_verdicts = int(report.get("absence_suppressed", 0) or 0)
    supp = int(counts.get("EXCLUSION_SUPPRESSED", 0) or 0)
    if absence_verdicts and supp == 0:
        stops.append(
            f"ANOMALY[absence-acted-at-{stage}]: {absence_verdicts} absence-justified "
            f"verdict(s) recorded but no record landed in EXCLUSION_SUPPRESSED — "
            f"they were acted on or lost rather than review-routed")
    return stops


def run_arm_live(mods: _Mods, spec: Dict[str, Any], arm: Dict[str, Any],
                 parse: Any, harmonized_text: str, budget: int,
                 out_dir: Path) -> Dict[str, Any]:
    """Run one arm live, writing 15e-shaped artifacts per stage. Artifacts are
    written BEFORE any anomaly is raised, so a stop never loses evidence."""
    import time
    live = arm.get("live") or spec["live_defaults"]
    facts = live_preflight(mods, spec, arm, parse, harmonized_text)
    lc = mods.llm_client
    counter = {"n": 0}
    real_builder = lc._openai_client_for
    lc._openai_client_for = (  # type: ignore[assignment]
        lambda *a, **k: _BudgetEnforcedClient(real_builder(*a, **k), counter, budget))
    out_dir.mkdir(parents=True, exist_ok=True)
    key = arm["key"]
    arm_t0 = time.time()
    stages_done: List[Dict[str, Any]] = []
    stops: List[str] = []
    try:
        if arm["kind"] == "derived_rows":
            rows_in = parse.rows      # the bundle population IS the stage input
            stage_plan = [arm["stage"]]
        else:
            chain = run_chain(mods, parse, harmonized_text)
            rows_in = chain.pop("survivor_rows_ih")
            stage_plan = ["EL", "IL"]
        header = list(parse.header)
        for stage in stage_plan:
            screen = mods.el_screen if stage == "EL" else mods.il_screen
            crits = screen._parse_criteria_harmonized_csv(
                harmonized_text, stage_filter=stage)
            n_llm = len([c for c in crits.criteria if c.enabled and c.operator == "llm"])
            stage_parse = screen.ParseReport(header=header, rows=rows_in, skipped=[])
            log_lines: List[str] = []

            def _log(s: str, _st=stage) -> None:
                line = f"[{_st}] {s}"
                log_lines.append(line + "\n")
                print(line, flush=True)

            before = counter["n"]
            t0 = time.time()
            run_fn = screen.run_el_screen if stage == "EL" else screen.run_il_screen
            (full_rows, survivors, counts, impacts, _evals, _cache_out,
             cancelled, report) = run_fn(
                stage_parse, crits,
                model=live["model"][stage], trunc_chars=int(spec["trunc_chars"]),
                batch_size=int(live["batch_size"][stage]),
                temperature=float(live.get("temperature", 0.0)),
                use_cache=False, cache_in={},          # cache OFF per F-101
                cancel_event=threading.Event(),
                log_cb=_log)
            dt = time.time() - t0
            spent_stage = counter["n"] - before

            # ---- artifacts first, always (15e shapes) ----
            pfx = stage.lower()
            fieldnames = header + [
                f"{pfx}_outcome", f"{pfx}_failed_ids", f"{pfx}_missing_ids",
                f"{pfx}_met_ids", f"{pfx}_uncertain_ids",
                f"{pfx}_evidence_json", f"{pfx}_reason_summary",
            ]
            from plugins._common.exporters import _write_csv_bytes
            (out_dir / f"{key}_{stage}_FULL.csv").write_bytes(
                _write_csv_bytes(fieldnames, full_rows))
            (out_dir / f"{key}_{stage}_report.json").write_text(
                json.dumps(report, indent=2, sort_keys=True, default=str),
                encoding="utf-8", newline="\n")
            (out_dir / f"{key}_{stage}_log.txt").write_text(
                "".join(log_lines), encoding="utf-8", newline="\n")
            summary = {
                "arm": f"{key}_{stage}",
                "arm_key": key,
                "stage": stage,
                "batch_size": int(live["batch_size"][stage]),
                "cancelled": cancelled,
                "wall_seconds": round(dt, 1),
                "counts": counts,
                "records": report.get("records"),
                "answered": report.get("answered"),
                "no_answer": report.get("no_answer"),
                "calls_made": report.get("calls_made"),
                "calls_counted_by_enforcer": spent_stage,
                "reasks_made": report.get("reasks_made"),
                "no_answer_after_reask": report.get("no_answer_after_reask"),
                "exclusion_policy": report.get("exclusion_policy"),
                "request_shape": report.get("request_shape"),
                "provenance": report.get("provenance"),
                "absence_suppressed_key_present": "absence_suppressed" in report,
                "llm_criteria": n_llm,
                "records_in": len(rows_in),
                "full_rows": len(full_rows),
                "survivors": len(survivors),
            }
            (out_dir / f"{key}_{stage}_summary.json").write_text(
                json.dumps(summary, indent=2, default=str),
                encoding="utf-8", newline="\n")
            stages_done.append(summary)

            if cancelled:
                stops.append(f"ANOMALY[cancelled-at-{stage}]: engine reported cancelled")
            stops.extend(_check_anomalies(stage, counts, report, budget,
                                          counter["n"]))
            # The product's own chain: this stage's survivors feed the next.
            rows_in = survivors
        arm_manifest = {
            "arm": key,
            "declared_budget": budget,
            "calls_made_total": counter["n"],
            "wall_seconds_total": round(time.time() - arm_t0, 1),
            "preflight": facts,
            "stages": stages_done,
            "anomaly_stops": stops,
            "generated_by": "tools/run_criteria_experiment.py --live",
        }
        (out_dir / f"{key}_live_manifest.json").write_text(
            json.dumps(arm_manifest, indent=2, default=str),
            encoding="utf-8", newline="\n")
        print(f"live arm {key}: calls_made={counter['n']} (declared {budget}) "
              f"wall={arm_manifest['wall_seconds_total']}s")
        if stops:
            for s in stops:
                print(s, flush=True)
            raise AnomalyStop("; ".join(stops))
        return arm_manifest
    finally:
        lc._openai_client_for = real_builder  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--arm", help="run a single arm by key")
    ap.add_argument("--live", action="store_true",
                    help="wave 16b live mode; requires --arm, --budget, --yes-live")
    ap.add_argument("--budget", type=int,
                    help="declared hard call budget for the live arm")
    ap.add_argument("--yes-live", action="store_true",
                    help="explicit confirmation that live calls are intended")
    args = ap.parse_args(argv)

    spec = load_spec(args.spec)
    mods = _Mods()

    corpus_path = PROJECT_ROOT / spec["corpus"]
    corpus_bytes = corpus_path.read_bytes()
    got_digest = _sha256_bytes(corpus_bytes)
    if got_digest != spec["corpus_sha256"]:
        raise SystemExit(f"corpus digest mismatch: {got_digest} != "
                         f"{spec['corpus_sha256']} — refusing to run")
    corpus_text = corpus_bytes.decode("utf-8-sig")
    parse = mods.common_parser._parse_csv_tolerant_text(corpus_text)
    a_columns, text_stats = mods.h_parser._load_a_header_and_stats(str(corpus_path))

    arms = spec["arms"]
    if args.arm:
        arms = [a for a in arms if a["key"] == args.arm]
        if not arms:
            raise SystemExit(f"no arm with key {args.arm!r}")

    if args.live:
        if not (args.arm and args.budget and args.yes_live):
            raise SystemExit("--live requires --arm, --budget and --yes-live")
        arm = arms[0]
        src_text = _read_text(PROJECT_ROOT / arm["source"])
        if arm["kind"] == "derived_rows":
            _rows, harmonized_text, _psha = derive_rows_from_parent(
                mods, spec, arm, a_columns, text_stats)
            parse, _ident = resolve_bundle_corpus(mods, spec["corpus_bundle"])
        elif arm["kind"] == "free_text":
            rows = translate_free_text(mods, src_text, a_columns, text_stats)
            harmonized_text = mods.h_exporters._criteria_csv_text(rows)
        else:
            harmonized_text = src_text
        try:
            run_arm_live(mods, spec, arm, parse, harmonized_text, args.budget,
                         args.out)
        except AnomalyStop as e:
            print(f"WAVE16B-ANOMALY-STOP: {e}", flush=True)
            return 3
        except Exception as e:  # guard refusals, drift, transport
            print(f"WAVE16B-RUN-ERROR: {type(e).__name__}: {e}", flush=True)
            raise
        return 0

    # ---- dry mode: structurally no-network, plus the explicit guard ----
    _install_dry_guard(mods)
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    manifests = []
    for arm in arms:
        print(f"[dry] arm {arm['key']} ...")
        m = run_arm_dry(mods, spec, arm, parse, a_columns, text_stats)
        manifests.append(m)
        (out_dir / f"{arm['key']}_manifest.json").write_text(
            json.dumps(m, indent=2, default=str), encoding="utf-8", newline="\n")
    rows = summarize(manifests, spec.get("call_ceiling_total"))
    summary_path = out_dir / "cross_arm_summary.csv"
    with open(summary_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[dry] wrote {len(manifests)} manifests + {summary_path}")
    for r in rows:
        print("  ", {k: r[k] for k in ("arm", "calls_batch5", "calls_batch1",
                                       "records_at_el", "guard_ok_batch5")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
