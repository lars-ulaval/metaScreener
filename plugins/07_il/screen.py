
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""screen.py - Plugin 07 IL: engine implementation.

After Conv 6 / Commit 6, this module owns IL's engine code:
  - Dataclasses: Criterion, ParseReport, CriteriaLoadReport, BundleInfo
  - OUTCOMES constant
  - Stage-specific helpers: _safe_str, _decode_bytes, _read_zip_bytes,
    _detect_bundle_root, _csv_read, _write_csv, _load_bundle,
    _parse_criteria_harmonized_csv. These are deliberately kept
    IL-local rather than imported from plugins/_common/ for the same
    reason as EL's screen.py: their bodies differ from _common's
    EH/IH-tuned versions, and substitution would change behaviour
    and break the captured byte-identity goldens.
  - _cache_key: stage-curried wrapper around plugins._common.llm_client._cache_key
    that bakes in IL's PROMPT_VERSION.
  - run_il_screen: the main engine entry point invoked by ILView.
  - _summarize_el_reason: outcome-summary helper used by the UI.
    (Name retained for code-history continuity even though IL outcomes
    are REVIEW-flavored rather than EL's PASS/FAIL flavored.)

plugin.py is now a thin re-export shim: it pulls everything in this
module up into the plugins.07_il.plugin namespace so existing
consumers (UI code, tests, the plugin manager) reach il.run_il_screen,
il.Criterion, il._safe_str, etc. through the unchanged paths.

Behaviour-preservation note: the byte-identity tests in
tests/test_il_regression.py::TestILGolden lock down this module's
output. Any change to the helpers above must keep the captured
goldens passing, otherwise IL's screening output has drifted.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
import time
import zipfile
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from plugins._common.llm_client import (
    _has_openai_key,
    _quote_in_text,
    _sha_text,
    _normalize_space,
    chunked,
    _parse_llm_json_array,
    run_m1_llm_for_criterion,
    _make_item_for_llm,
    _row_target_text_hash,
    _load_cache_from_jsonl,
    _dump_cache_to_jsonl,
)
from plugins._common.llm_client import _cache_key as _shared_cache_key

from .prompt import PROMPT_VERSION, _build_llm_messages_for_criterion

OUTCOMES = ("OUT", "PASS_CLEAN", "REVIEW")

# ------------------------------ dataclasses -----------------------------------

@dataclass
class Criterion:
    id: str
    stage: str                  # EH / IH / EL / IL
    ctype: str                  # include / exclude
    enabled: bool
    operator: str               # contains / regex / llm / ...
    targets: List[str]          # ["title","abstract"] etc
    what_raw: str               # raw "what" cell
    what_list: List[str]        # parsed list
    threshold: float            # for llm
    source_text: str            # human-readable criterion text (for UI)
    label: str = ""             # optional

@dataclass
class ParseReport:
    header: List[str]
    rows: List[Dict[str, str]]
    skipped: List[Dict[str, Any]]  # rows skipped due to parse issues

@dataclass
class CriteriaLoadReport:
    criteria: List[Criterion]
    warnings: List[str]

@dataclass
class BundleInfo:
    zip_path: str
    root: str
    manifest: Dict[str, Any]
    parse: ParseReport
    criteria: CriteriaLoadReport


# ------------------------------ small utils ----------------------------------

def _safe_str(x: Any) -> str:
    return "" if x is None else str(x)

def _decode_bytes(b: bytes) -> str:
    # BOM-safe decode
    return b.decode("utf-8-sig", errors="replace")

def _read_zip_bytes(zf: zipfile.ZipFile, member: str) -> bytes:
    with zf.open(member, "r") as fp:
        return fp.read()

def _detect_bundle_root(members: Sequence[str]) -> str:
    """
    Accept:
      manifest.json at root
      OR inside a single top folder, e.g. ScreenA_Bundle/manifest.json
    Return root prefix ("" or "ScreenA_Bundle/").
    """
    if "manifest.json" in members:
        return ""
    # find any */manifest.json
    for m in members:
        if m.endswith("/manifest.json"):
            return m[:-len("manifest.json")]
    # fallback: try first segment
    tops = {m.split("/", 1)[0] for m in members if "/" in m}
    for t in sorted(tops):
        if f"{t}/manifest.json" in members:
            return f"{t}/"
    return ""

def _csv_read(text: str) -> Tuple[List[str], List[Dict[str, str]]]:
    # Robust CSV reading with UTF-8 and tolerant rows
    f = io.StringIO(text)
    reader = csv.reader(f)
    rows = list(reader)
    if not rows:
        return [], []
    header = [h.strip() for h in rows[0]]
    out: List[Dict[str, str]] = []
    for i, r in enumerate(rows[1:], start=2):
        if not any((c or "").strip() for c in r):
            continue
        d: Dict[str, str] = {}
        for j, h in enumerate(header):
            d[h] = (r[j] if j < len(r) else "")
        out.append(d)
    return header, out

def _write_csv(path: str, header: List[str], rows: List[Dict[str, Any]]):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in header})

# Small utilities (_sha_text, _normalize_space, _quote_in_text, _has_openai_key,
# chunked) moved to plugins/_common/llm_client.py in Conv 6 / Commit 1; the
# names remain reachable via the import block at the top of this file.


# -------------------------- bundle parsing ------------------------------------

def _load_bundle(zip_path: str) -> BundleInfo:
    if not zip_path.lower().endswith(".zip"):
        raise ValueError("Bundle must be a .zip file.")
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()
        root = _detect_bundle_root(members)

        manifest_full = root + "manifest.json"
        if manifest_full not in members:
            raise FileNotFoundError("Bundle missing manifest.json")

        manifest_bytes = _read_zip_bytes(zf, manifest_full)
        try:
            manifest = json.loads(_decode_bytes(manifest_bytes))
        except Exception as e:
            raise ValueError(f"manifest.json is not valid JSON: {e}")

        # data/current.csv
        current_full = root + "data/current.csv"
        if current_full not in members:
            raise FileNotFoundError("Bundle missing data/current.csv")
        current_txt = _decode_bytes(_read_zip_bytes(zf, current_full))
        header, rows = _csv_read(current_txt)

        skipped: List[Dict[str, Any]] = []
        # Minimal sanity: require local_id
        if "local_id" not in header:
            # Try common fallbacks
            for cand in ("id", "ID", "LocalID", "localId"):
                if cand in header:
                    # rename in-memory
                    for r in rows:
                        r["local_id"] = r.get(cand, "")
                    header.append("local_id")
                    break
        # mark rows with empty or duplicate local_id as skipped
        filtered: List[Dict[str, str]] = []
        seen_ids: set = set()
        for r in rows:
            lid = (r.get("local_id") or "").strip()
            if not lid:
                skipped.append({"reason": "missing local_id", "row": r})
                continue
            if lid in seen_ids:
                skipped.append({"reason": "duplicate local_id", "row": r})
                continue
            seen_ids.add(lid)
            filtered.append(r)

        parse = ParseReport(header=header, rows=filtered, skipped=skipped)

        # criteria/criteria_harmonized.csv
        crit_full = root + "criteria/criteria_harmonized.csv"
        if crit_full not in members:
            raise FileNotFoundError("Bundle missing criteria/criteria_harmonized.csv")
        crit_txt = _decode_bytes(_read_zip_bytes(zf, crit_full))
        criteria = _parse_criteria_harmonized_csv(crit_txt, stage_filter="IL")

        return BundleInfo(zip_path=zip_path, root=root, manifest=manifest, parse=parse, criteria=criteria)

def _parse_criteria_harmonized_csv(csv_text: str, stage_filter: str) -> CriteriaLoadReport:
    header, rows = _csv_read(csv_text)
    # columns we expect (tolerate variations)
    def get(d: Dict[str,str], *keys: str) -> str:
        for k in keys:
            if k in d:
                return d.get(k, "")
        # case-insensitive
        kl = {kk.lower(): kk for kk in d.keys()}
        for k in keys:
            if k.lower() in kl:
                return d.get(kl[k.lower()], "")
        return ""

    crits: List[Criterion] = []
    warnings: List[str] = []

    # row_no is the 1-based line number in criteria_harmonized.csv,
    # counting the header, so it matches what a spreadsheet shows.
    for row_no, r in enumerate(rows, start=2):
        stage = _safe_str(get(r, "stage")).strip().upper()
        if stage != stage_filter.upper():
            continue

        enabled_s = _safe_str(get(r, "enabled")).strip().lower()
        enabled = enabled_s not in {"0", "false", "no"}

        cid = _safe_str(get(r, "id", "criterion_id")).strip()
        if not cid:
            continue

        # Polarity must be stated, not guessed. This used to default to
        # "exclude" in both stages, which silently INVERTED an IL criterion
        # whose type cell was blank: an LLM verdict of "meet" then excluded
        # the record instead of including it. Skip the row and warn instead,
        # so a criterion we cannot interpret is visibly absent from the
        # criteria panel rather than invisibly reversed.
        ctype = _safe_str(get(r, "type", "ctype")).strip().lower()
        if ctype not in ("include", "exclude"):
            warnings.append(
                "[criteria] row %d (%s): type is %s, expected 'include' or "
                "'exclude' -> criterion SKIPPED. Its polarity cannot be "
                "determined, and guessing it could invert the screening "
                "decision. Fix the type cell in criteria_harmonized.csv "
                "and re-load the bundle."
                % (row_no, cid, repr(ctype) if ctype else "empty")
            )
            continue
        operator = _safe_str(get(r, "operator")).strip().lower() or "llm"
        target_raw = _safe_str(get(r, "target", "targets")).strip()
        targets = [t.strip().lower() for t in re.split(r"[,+;]", target_raw) if t.strip()] or ["abstract"]

        what_raw = _safe_str(get(r, "what")).strip()
        # "what" might be JSON list, or newline-separated
        what_list: List[str] = []
        if what_raw:
            try:
                val = json.loads(what_raw)
                if isinstance(val, list):
                    what_list = [str(x) for x in val]
                else:
                    what_list = [str(val)]
            except Exception:
                what_list = [w.strip() for w in re.split(r"[\n;|]+", what_raw) if w.strip()]
        thr_s = _safe_str(get(r, "threshold", "thr")).strip()
        try:
            thr = float(thr_s) if thr_s else 0.6
        except Exception:
            thr = 0.6

        label = _safe_str(get(r, "label")).strip()
        source_text = _safe_str(get(r, "source_text", "text", "criterion_text")).strip()
        if not source_text:
            # synthesize from what/label
            source_text = label or (what_list[0] if what_list else "")

        crits.append(
            Criterion(
                id=cid,
                stage=stage,
                ctype=ctype,
                enabled=enabled,
                operator=operator,
                targets=targets,
                what_raw=what_raw,
                what_list=what_list,
                threshold=thr,
                source_text=source_text,
                label=label,
            )
        )

    if not crits:
        warnings.append(f"No IL criteria found (stage={stage_filter}).")

    return CriteriaLoadReport(criteria=crits, warnings=warnings)


# LLM utilities (_parse_llm_json_array, _build_llm_messages_for_criterion,
# run_m1_llm_for_criterion) moved to plugins/_common/llm_client.py in
# Conv 6 / Commit 1 (extraction completed by hotfix to f3fa6bb).
# The names remain reachable via the import block at the top of this file.

# ------------------------ IL engine (self-contained) --------------------------

# Stage-curried wrapper around plugins._common.llm_client._cache_key. Bakes in
# this stage's PROMPT_VERSION so call sites and the existing evidence-gating
# tests continue to work unchanged. The shared function takes prompt_version
# as a keyword parameter; this wrapper passes IL's value transparently.
def _cache_key(*, model: str, cid: str, a_id: str, text_hash: str,
               trunc_chars: int, temperature: float = 0.0) -> str:
    return _shared_cache_key(
        prompt_version=PROMPT_VERSION,
        model=model, cid=cid, a_id=a_id,
        text_hash=text_hash, trunc_chars=trunc_chars,
        temperature=temperature,
    )

# _make_item_for_llm, _row_target_text_hash, _load_cache_from_jsonl,
# _dump_cache_to_jsonl moved to plugins/_common/llm_client.py in Conv 6 /
# Commit 1; the names remain reachable via the import block at the top
# of this file.

def run_il_screen(
    parse: ParseReport,
    criteria_report: CriteriaLoadReport,
    *,
    model: str,
    trunc_chars: int,
    batch_size: int,
    temperature: float = 0.0,
    use_cache: bool,
    cache_in: Optional[Dict[str, Dict[str, Any]]],
    cancel_event: threading.Event,
    log_cb: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
    progress_evt: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[
    List[Dict[str, Any]],   # full_rows with IL columns
    List[Dict[str, str]],   # survivors (original schema)
    Dict[str, int],         # counts
    Dict[str, Dict[str, int]],  # crit_impacts
    List[Dict[str, List[str]]], # row_eval_lists (aligned with full_rows)
    Dict[str, Dict[str, Any]],  # cache_out
]:
    rows = parse.rows
    crits = [c for c in criteria_report.criteria if c.enabled]
    counts = {k: 0 for k in OUTCOMES}
    crit_impacts: Dict[str, Dict[str, int]] = {c.id: {"failed":0,"missing":0,"met":0,"uncertain":0} for c in crits}

    full_rows: List[Dict[str, Any]] = []
    survivors: List[Dict[str, str]] = []
    row_eval_lists: List[Dict[str, List[str]]] = []

    cache_out: Dict[str, Dict[str, Any]] = dict(cache_in or {})

    if not crits:
        for r in rows:
            if cancel_event.is_set():
                break
            fr = dict(r)
            fr["il_outcome"] = "PASS_CLEAN"
            fr["il_failed_ids"] = ""
            fr["il_missing_ids"] = ""
            fr["il_met_ids"] = ""
            fr["il_uncertain_ids"] = ""
            fr["il_reason_summary"] = "No active IL criteria: default PASS_CLEAN."
            fr["il_evidence_json"] = "{}"
            full_rows.append(fr)
            survivors.append(dict(r))
            row_eval_lists.append({"failed": [], "missing": [], "met": [], "uncertain": []})
        counts["PASS_CLEAN"] = len(survivors)
        if progress_cb:
            progress_cb(1.0)
        return full_rows, survivors, counts, crit_impacts, row_eval_lists, cache_out

    # Build items for LLM (same base shape as legacy), but robust to header casing
    header_map: Dict[str, str] = {h.lower(): h for h in (parse.header or [])}

    def getv(row: Dict[str, str], key: str) -> str:
        k = header_map.get(key.lower(), key)
        return _safe_str(row.get(k, ""))

    def row_text_hash(row: Dict[str, str], targets: List[str]) -> str:
        parts: List[str] = []
        for t in targets:
            v = getv(row, t)
            if trunc_chars and len(v) > trunc_chars:
                v = v[:trunc_chars]
            parts.append(v)
        return _sha_text("|".join(parts))

    items = [{
        "a_id": getv(r, "local_id").strip(),
        "title": getv(r, "title"),
        "abstract": getv(r, "abstract"),
        "keywords": getv(r, "keywords"),
    } for r in rows]

    id_to_row: Dict[str, Dict[str, str]] = {}
    for r in rows:
        lid = getv(r, "local_id").strip()
        if lid:
            id_to_row[lid] = r

    # Precompute per-row text hashes per criterion for caching
    per_row_hash: Dict[Tuple[str,str], str] = {}  # (a_id,cid)->text_hash
    for c in crits:
        for r in rows:
            a_id = getv(r, "local_id").strip()
            if not a_id:
                continue
            per_row_hash[(a_id, c.id)] = row_text_hash(r, c.targets)

    # Run criterion by criterion (legacy-style)
    llm_results: Dict[Tuple[str,str], Dict[str, Any]] = {}

    for ci, c in enumerate(crits, start=1):
        if cancel_event.is_set():
            break

        # build criterion pack
        crit_pack = {
            "id": c.id,
            "type": c.ctype,
            "operator": c.operator,
            "target": ",".join(c.targets),
            "what": c.what_list,
            "how": "llm" if c.operator == "llm" else c.operator,
            "label": c.label or c.source_text,
            "threshold": c.threshold,
        }

        if log_cb:
            log_cb(f"\n[IL] Criterion {ci}/{len(crits)} {c.id} ({c.operator})\n")

        # Separate cached vs to-call items
        to_call: List[Dict[str, Any]] = []
        cached_pairs: List[Tuple[str,str]] = []

        for it in items:
            a_id = _safe_str(it.get("a_id","")).strip()
            if not a_id:
                continue
            th = per_row_hash.get((a_id, c.id), "")
            k = _cache_key(model=model, cid=c.id, a_id=a_id, text_hash=th,
                           trunc_chars=trunc_chars, temperature=temperature)
            if use_cache and k in cache_out:
                # reuse cached evidence
                ev = dict(cache_out[k])
                ev.setdefault("used", True)
                llm_results[(a_id, c.id)] = ev
                cached_pairs.append((a_id, c.id))
            else:
                to_call.append(it)

        if log_cb:
            log_cb(f"[IL] cache_hits={len(cached_pairs)} | to_call={len(to_call)}\n")

        if c.operator == "llm" and to_call:
            res = run_m1_llm_for_criterion(
                crit_pack,
                to_call,
                stage="IL",
                build_messages=_build_llm_messages_for_criterion,
                model=model,
                trunc_chars=trunc_chars,
                batch_size=batch_size,
                log=log_cb,
                progress=progress_evt,
                cancel_token=cancel_event,
                crit_idx=ci,
                crit_total=len(crits),
                block_tag="exclude",
                temperature=temperature,
            )
            # merge + write to cache
            for (a_id, cid), ev in res.items():
                llm_results[(a_id, cid)] = ev
                r = id_to_row.get(a_id)
                if not r:
                    continue
                th = per_row_hash.get((a_id, cid), "")
                k = _cache_key(model=model, cid=cid, a_id=a_id, text_hash=th,
                               trunc_chars=trunc_chars, temperature=temperature)
                if use_cache:
                    cache_out[k] = dict(ev)

        elif c.operator != "llm":
            # deterministic operator (rare in IL). Mark uncertain; real deterministic logic can be added later.
            for it in to_call:
                a_id = _safe_str(it.get("a_id","")).strip()
                llm_results[(a_id, c.id)] = {"used": False, "decision":"uncertain","confidence":0.0,"field":"abstract","quote":"","span":None,"valid_quote":False}

        if progress_cb:
            progress_cb(ci / max(1, len(crits)) * 0.7)

    # Now compute per-row statuses
    for idx, r in enumerate(rows, start=1):
        if cancel_event.is_set():
            break

        a_id = getv(r, "local_id").strip()
        failed: List[str] = []
        missing: List[str] = []
        met: List[str] = []
        uncertain: List[str] = []
        evidence: Dict[str, Any] = {}

        for c in crits:
            # missing if all target fields are empty
            all_empty = True
            for t in c.targets:
                if getv(r, t).strip():
                    all_empty = False
                    break
            if all_empty:
                missing.append(c.id)
                crit_impacts[c.id]["missing"] += 1
                evidence[c.id] = {"status":"MISSING"}
                continue

            if c.operator != "llm":
                uncertain.append(c.id)
                crit_impacts[c.id]["uncertain"] += 1
                evidence[c.id] = {"status":"UNCERTAIN", "note":"non-llm operator in IL stage"}
                continue

            ev = llm_results.get((a_id, c.id), None) or {}
            decision = _safe_str(ev.get("decision","uncertain")).strip()
            try:
                confidence = float(ev.get("confidence", 0.0))
            except Exception:
                confidence = 0.0
            valid_quote = bool(ev.get("valid_quote", False))
            usable = valid_quote and (confidence >= float(c.threshold)) and (decision in {"meet","not_meet"})

            status = "UNCERTAIN"
            if usable:
                if c.ctype == "exclude":
                    if decision == "meet":
                        status = "FAILED"
                        failed.append(c.id)
                        crit_impacts[c.id]["failed"] += 1
                    elif decision == "not_meet":
                        status = "MET"
                        met.append(c.id)
                        crit_impacts[c.id]["met"] += 1
                else:
                    # (not expected in IL) treat as include
                    if decision == "meet":
                        status = "MET"
                        met.append(c.id)
                        crit_impacts[c.id]["met"] += 1
                    elif decision == "not_meet":
                        status = "FAILED"
                        failed.append(c.id)
                        crit_impacts[c.id]["failed"] += 1
            else:
                uncertain.append(c.id)
                crit_impacts[c.id]["uncertain"] += 1

            evidence[c.id] = {
                "status": status,
                "decision": decision,
                "confidence": confidence,
                "threshold": c.threshold,
                "field": _safe_str(ev.get("field","")),
                "quote": _safe_str(ev.get("quote","")),
                "quote_valid": bool(valid_quote),
                "span": ev.get("span", None),
                "used": bool(ev.get("used", False)),
            }

        if failed:
            outcome = "OUT"
        elif (len(met) == len(crits)) and not missing and not uncertain:
            outcome = "PASS_CLEAN"
        else:
            outcome = "REVIEW"

        fr = dict(r)
        fr["il_outcome"] = outcome
        fr["il_failed_ids"] = ",".join(failed)
        fr["il_missing_ids"] = ",".join(missing)
        fr["il_met_ids"] = ",".join(met)
        fr["il_uncertain_ids"] = ",".join(uncertain)
        fr["il_evidence_json"] = json.dumps(evidence, ensure_ascii=False)
        fr["il_reason_summary"] = _summarize_el_reason(outcome, failed, missing, uncertain)

        full_rows.append(fr)
        row_eval_lists.append({"failed": failed, "missing": missing, "met": met, "uncertain": uncertain})

        if outcome != "OUT":
            survivors.append(dict(r))

        counts[outcome] = counts.get(outcome, 0) + 1

        if progress_cb and idx % 25 == 0:
            # remaining 30% of progress
            progress_cb(0.7 + (idx / max(1, len(rows))) * 0.3)

    if progress_cb:
        progress_cb(1.0)

    return full_rows, survivors, counts, crit_impacts, row_eval_lists, cache_out

def _summarize_el_reason(outcome: str, failed: List[str], missing: List[str], uncertain: List[str]) -> str:
    if outcome == "OUT":
        return f"OUT: failed {', '.join(failed)}"
    if outcome == "PASS_CLEAN":
        return "PASS_CLEAN: all IL criteria MET."
    bits: List[str] = ["REVIEW:"]
    if missing:
        bits.append(f"missing {', '.join(missing)}")
    if uncertain:
        bits.append(f"uncertain {', '.join(uncertain)}")
    if not missing and not uncertain:
        bits.append("no failures")
    return " ".join(bits)
