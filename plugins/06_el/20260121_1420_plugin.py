# -*- coding: utf-8 -*-
"""
plugin.py — Screen A (EL-only) as a PRISMA Hub tab plugin (Contract v2, EL stage)

Design goals (aligned with your EH/IH conventions)
- Single-file plugin: UI + engine + LLM interaction (no local imports except prisma_hub.plugin_api)
- Bundle-first input (Harmoniser ZIP): reads data/current.csv + criteria/criteria_harmonized.csv
- EL semantics (contract v2):
    - Per criterion status: MET / FAILED / MISSING / UNCERTAIN
    - Per row outcome:
        any FAILED           -> OUT
        else all MET         -> PASS_CLEAN
        else                 -> PASS_FLAGGED
- LLM logic (recovered + compatible with your legacy metadata.py approach):
    - System: JSON-only list; per item: a_id, decision(meet|not_meet|uncertain), confidence(0..1), field, quote, span
    - Evidence gating: decision counts only if confidence>=threshold AND quote_valid=True
    - Batching: chunk items; adaptive shrink on 429/oversize; optional truncation reduction
- Persistent cache (default ON): cache/EL_cache.jsonl stored inside output bundle.
  Key includes model + criterion_id + a_id + hash(truncated target text) + prompt_version.

Notes
- Requires prisma_hub.plugin_api.BasePlugin / PluginMeta
- Requires OPENAI_API_KEY in environment to run LLM
- Uses OpenAI Chat Completions via `from openai import OpenAI` (imported inside function)
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
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from prisma_hub.plugin_api import BasePlugin, PluginMeta


# ------------------------------ constants -------------------------------------

TAB_TITLE = "Screen A — EL (LLM Exclude)"
PLUGIN_ID = "screen_a_el"
PLUGIN_VERSION = "2.0.0"

# Defaults (safe; overridable in UI + env)
DEFAULT_MODEL = os.environ.get("SCREENA_EL_MODEL", "gpt-4o-mini")
DEFAULT_TRUNC_CHARS = int(os.environ.get("SCREENA_EL_TRUNC_CHARS", "1500"))
DEFAULT_BATCH_SIZE = int(os.environ.get("SCREENA_EL_BATCH_SIZE", "50"))
DEFAULT_USE_CACHE = os.environ.get("SCREENA_EL_USE_CACHE", "1").strip() not in {"0", "false", "False", "no", "NO"}

PROMPT_VERSION = "EL_v1_jsonlist"

EL_CACHE_REL = "cache/EL_cache.jsonl"
REPORTS_DIR_REL = "reports"

OUTCOMES = ("OUT", "PASS_CLEAN", "PASS_FLAGGED")

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

def _sha_text(s: str) -> str:
    return sha256(s.encode("utf-8", errors="ignore")).hexdigest()

def _normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _has_openai_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())

def chunked(seq: Sequence[Any], n: int):
    n = max(1, int(n))
    for i in range(0, len(seq), n):
        yield seq[i:i+n]


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
        # mark rows with empty local_id as skipped
        filtered: List[Dict[str, str]] = []
        for r in rows:
            if not (r.get("local_id") or "").strip():
                skipped.append({"reason": "missing local_id", "row": r})
                continue
            filtered.append(r)

        parse = ParseReport(header=header, rows=filtered, skipped=skipped)

        # criteria/criteria_harmonized.csv
        crit_full = root + "criteria/criteria_harmonized.csv"
        if crit_full not in members:
            raise FileNotFoundError("Bundle missing criteria/criteria_harmonized.csv")
        crit_txt = _decode_bytes(_read_zip_bytes(zf, crit_full))
        criteria = _parse_criteria_harmonized_csv(crit_txt, stage_filter="EL")

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

    for r in rows:
        stage = _safe_str(get(r, "stage")).strip().upper()
        if stage != stage_filter.upper():
            continue

        enabled_s = _safe_str(get(r, "enabled")).strip()
        enabled = enabled_s not in {"0", "false", "False", "", "no", "NO"}

        cid = _safe_str(get(r, "id", "criterion_id")).strip()
        if not cid:
            continue

        ctype = _safe_str(get(r, "type", "ctype")).strip().lower() or "exclude"
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
        warnings.append(f"No EL criteria found (stage={stage_filter}).")

    return CriteriaLoadReport(criteria=crits, warnings=warnings)


# ------------------------ LLM utilities (legacy-compatible) -------------------

def _parse_llm_json_array(text: str) -> List[Dict[str, Any]]:
    """
    Robust parse of a JSON array. Accepts:
      - pure JSON list
      - fenced code block
      - extra text before/after (extract first [...] block)
    """
    t = (text or "").strip()
    # strip fenced code blocks
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()

    # direct
    try:
        val = json.loads(t)
        if isinstance(val, list):
            return [v for v in val if isinstance(v, dict)]
    except Exception:
        pass

    # extract first bracketed list
    m = re.search(r"\[\s*\{.*\}\s*\]", t, flags=re.S)
    if m:
        try:
            val = json.loads(m.group(0))
            if isinstance(val, list):
                return [v for v in val if isinstance(v, dict)]
        except Exception:
            pass
    return []

def _build_llm_messages_for_criterion(criterion: Dict[str, Any], items: List[Dict[str, Any]], trunc_chars: int) -> List[Dict[str, str]]:
    sys = (
        "You are scoring research items against ONE screening criterion. "
        "For each item, answer with JSON only. Keys per item: "
        "a_id, decision ('meet'|'not_meet'|'uncertain'), confidence (0..1), "
        "field ('title'|'abstract'|'keywords'), quote (exact substring from that field), span [start,end]. "
        "Return a JSON list of objects, nothing else."
    )

    c_pack = {
        "id": criterion["id"],
        "type": criterion.get("type", "exclude"),
        "operator": criterion.get("operator", "llm"),
        "target": criterion.get("target", "abstract"),
        "what": criterion.get("what", []),
        "how": criterion.get("how", "llm"),
        "label": criterion.get("label", ""),
        "threshold": criterion.get("threshold", 0.6),
    }

    def trunc(s: str) -> str:
        s = s or ""
        if trunc_chars and len(s) > trunc_chars:
            return s[:trunc_chars]
        return s

    items_pack = []
    for it in items:
        items_pack.append({
            "a_id": it.get("a_id", ""),
            "title": trunc(_safe_str(it.get("title",""))),
            "abstract": trunc(_safe_str(it.get("abstract",""))),
            "keywords": trunc(_safe_str(it.get("keywords",""))),
        })

    user = json.dumps({"criterion": c_pack, "items": items_pack}, ensure_ascii=False)
    return [{"role":"system","content":sys}, {"role":"user","content":user}]

def run_m1_llm_for_criterion(
    criterion: Dict[str, Any],
    items: List[Dict[str, Any]],
    *,
    model: Optional[str],
    trunc_chars: int = DEFAULT_TRUNC_CHARS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    log: Optional[Callable[[str], None]] = None,
    progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_token: Optional[object] = None,
    crit_idx: Optional[int] = None,
    crit_total: Optional[int] = None,
    block_tag: str = "exclude",
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """
    Returns (a_id, criterion_id) -> llm_decision_dict (used/decision/confidence/field/quote/span/valid_quote).
    Implements adaptive batching on errors (429/oversize).
    """
    if not model:
        if log: log("[EL-LLM] model=None; skipping.\n")
        return {}
    if not _has_openai_key():
        if log: log("[EL-LLM] OPENAI_API_KEY not visible in environment; skipping.\n")
        return {}

    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    except Exception as e:
        if log: log(f"[EL-LLM] OpenAI client import/init failed: {e}\n")
        return {}

    def _check_cancel():
        if cancel_token is not None and bool(getattr(cancel_token, "cancelled", False)):
            raise RuntimeError("Cancelled")
        if cancel_token is not None and bool(getattr(cancel_token, "is_set", lambda: False)()):
            raise RuntimeError("Cancelled")

    def _call_once(batch: List[Dict[str, Any]], cur_trunc: int):
        msgs = _build_llm_messages_for_criterion(criterion, batch, cur_trunc)
        return client.chat.completions.create(
            model=model,
            messages=msgs,
            temperature=0.0,
        )

    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    cid = criterion["id"]

    batches = [list(b) for b in chunked(items, max(1, int(batch_size)))]
    total_batches = len(batches)

    # index text for quote validation
    idx_map: Dict[str, Dict[str, str]] = {}
    for it in items:
        a_id = _safe_str(it.get("a_id",""))
        if not a_id:
            continue
        idx_map[a_id] = {
            "title": _safe_str(it.get("title","")),
            "abstract": _safe_str(it.get("abstract","")),
            "keywords": _safe_str(it.get("keywords","")),
        }

    for bi, batch in enumerate(batches, start=1):
        _check_cancel()
        cur_batch = list(batch)
        cur_trunc = int(trunc_chars)
        attempts = 0

        while True:
            attempts += 1
            try:
                if progress:
                    progress({
                        "kind":"l_batch",
                        "stage":"EL",
                        "block":block_tag,
                        "crit_idx":crit_idx,
                        "crit_total":crit_total,
                        "batch_idx":bi,
                        "batch_total":total_batches,
                        "sub":"sending",
                    })
                resp = _call_once(cur_batch, cur_trunc)
                _check_cancel()

                if progress:
                    progress({
                        "kind":"l_batch",
                        "stage":"EL",
                        "block":block_tag,
                        "crit_idx":crit_idx,
                        "crit_total":crit_total,
                        "batch_idx":bi,
                        "batch_total":total_batches,
                        "sub":"parsing",
                    })

                txt = (resp.choices[0].message.content or "[]")
                arr = _parse_llm_json_array(txt)

                # build for every item in batch (even if missing from response)
                seen_ids = set()
                for obj in arr:
                    a_id = _safe_str(obj.get("a_id","")).strip()
                    if not a_id:
                        continue
                    if a_id not in idx_map:
                        continue

                    decision = _safe_str(obj.get("decision","uncertain")).strip()
                    if decision not in {"meet","not_meet","uncertain"}:
                        decision = "uncertain"

                    try:
                        confidence = float(obj.get("confidence", 0.0))
                    except Exception:
                        confidence = 0.0
                    confidence = min(1.0, max(0.0, confidence))

                    field = _safe_str(obj.get("field","")).strip().lower()
                    if field not in {"title","abstract","keywords"}:
                        field = "abstract"

                    quote = _safe_str(obj.get("quote",""))
                    span = obj.get("span", None)
                    if not (isinstance(span, list) and len(span) == 2 and all(isinstance(x, int) for x in span)):
                        span = None

                    fld_txt = (idx_map.get(a_id) or {}).get(field) or ""
                    valid_quote = bool(quote) and (quote in fld_txt)

                    out[(a_id, cid)] = {
                        "used": True,
                        "decision": decision,
                        "confidence": confidence,
                        "field": field,
                        "quote": quote,
                        "span": span,
                        "valid_quote": valid_quote,
                    }
                    seen_ids.add(a_id)

                # any missing response items -> mark uncertain used=False
                for it in cur_batch:
                    a_id = _safe_str(it.get("a_id","")).strip()
                    if not a_id:
                        continue
                    if (a_id, cid) not in out:
                        out[(a_id, cid)] = {
                            "used": False,
                            "decision": "uncertain",
                            "confidence": 0.0,
                            "field": "abstract",
                            "quote": "",
                            "span": None,
                            "valid_quote": False,
                        }

                if progress:
                    progress({
                        "kind":"l_batch",
                        "stage":"EL",
                        "block":block_tag,
                        "crit_idx":crit_idx,
                        "crit_total":crit_total,
                        "batch_idx":bi,
                        "batch_total":total_batches,
                        "sub":"batch_done",
                    })

                break  # batch success

            except Exception as e:
                msg = str(e).lower()
                is_rate = ("429" in msg) or ("rate" in msg and "limit" in msg) or ("too many requests" in msg)
                is_big = ("too large" in msg) or ("context" in msg and "length" in msg) or ("max tokens" in msg)

                # adaptive handling
                if (is_rate or is_big) and len(cur_batch) > 1:
                    new_n = max(1, len(cur_batch)//2)
                    if log:
                        log(f"[EL-LLM] batch {bi}/{total_batches} error ({e}); shrinking batch {len(cur_batch)} -> {new_n}\n")
                    cur_batch = cur_batch[:new_n]
                    time.sleep(min(4.0, 0.4 * attempts))
                    continue

                if (is_rate or is_big) and cur_trunc > 600:
                    new_trunc = max(600, int(cur_trunc * 0.75))
                    if log:
                        log(f"[EL-LLM] batch {bi}/{total_batches} error ({e}); trunc {cur_trunc} -> {new_trunc}\n")
                    cur_trunc = new_trunc
                    time.sleep(min(4.0, 0.4 * attempts))
                    continue

                # final failure: mark all as uncertain
                if log:
                    log(f"[EL-LLM] batch {bi}/{total_batches} failed: {e}\n")
                for it in cur_batch:
                    a_id = _safe_str(it.get("a_id","")).strip()
                    if not a_id:
                        continue
                    out[(a_id, cid)] = {
                        "used": False,
                        "decision": "uncertain",
                        "confidence": 0.0,
                        "field": "abstract",
                        "quote": "",
                        "span": None,
                        "valid_quote": False,
                        "error": str(e),
                    }
                break

    return out


# ------------------------ EL engine (self-contained) --------------------------

def _make_item_for_llm(row: Dict[str, str]) -> Dict[str, Any]:
    return {
        "a_id": _safe_str(row.get("local_id","")).strip(),
        "title": _safe_str(row.get("title","")),
        "abstract": _safe_str(row.get("abstract","")),
        "keywords": _safe_str(row.get("keywords","")),
    }

def _row_target_text_hash(row: Dict[str, str], targets: List[str], trunc_chars: int) -> str:
    parts: List[str] = []
    for t in targets:
        v = _safe_str(row.get(t, ""))
        if trunc_chars and len(v) > trunc_chars:
            v = v[:trunc_chars]
        parts.append(v)
    return _sha_text("|".join(parts))

def _cache_key(*, model: str, cid: str, a_id: str, text_hash: str, trunc_chars: int) -> str:
    base = f"{PROMPT_VERSION}|{model}|{cid}|{a_id}|{text_hash}|{trunc_chars}"
    return _sha_text(base)

def _load_cache_from_jsonl(text: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
            k = _safe_str(obj.get("key",""))
            v = obj.get("val", None)
            if k and isinstance(v, dict):
                out[k] = v
        except Exception:
            continue
    return out

def _dump_cache_to_jsonl(cache: Dict[str, Dict[str, Any]]) -> str:
    lines: List[str] = []
    for k, v in cache.items():
        lines.append(json.dumps({"key": k, "val": v}, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")

def run_el_screen(
    parse: ParseReport,
    criteria_report: CriteriaLoadReport,
    *,
    model: str,
    trunc_chars: int,
    batch_size: int,
    use_cache: bool,
    cache_in: Optional[Dict[str, Dict[str, Any]]],
    cancel_event: threading.Event,
    log_cb: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
    progress_evt: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[
    List[Dict[str, Any]],   # full_rows with EL columns
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
            fr["el_outcome"] = "PASS_CLEAN"
            fr["el_failed_ids"] = ""
            fr["el_missing_ids"] = ""
            fr["el_met_ids"] = ""
            fr["el_uncertain_ids"] = ""
            fr["el_reason_summary"] = "No active EL criteria: default PASS_CLEAN."
            fr["el_evidence_json"] = "{}"
            full_rows.append(fr)
            survivors.append(dict(r))
            row_eval_lists.append({"failed": [], "missing": [], "met": [], "uncertain": []})
        counts["PASS_CLEAN"] = len(survivors)
        if progress_cb:
            progress_cb(1.0)
        return full_rows, survivors, counts, crit_impacts, row_eval_lists, cache_out

    # Build items for LLM (same base shape as legacy)
    items = [_make_item_for_llm(r) for r in rows]
    id_to_row: Dict[str, Dict[str, str]] = {(_safe_str(r.get("local_id","")).strip()): r for r in rows}

    # Precompute per-row text hashes per criterion for caching
    per_row_hash: Dict[Tuple[str,str], str] = {}  # (a_id,cid)->text_hash
    for c in crits:
        for r in rows:
            a_id = _safe_str(r.get("local_id","")).strip()
            if not a_id:
                continue
            per_row_hash[(a_id, c.id)] = _row_target_text_hash(r, c.targets, trunc_chars)

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
            log_cb(f"\n[EL] Criterion {ci}/{len(crits)} {c.id} ({c.operator})\n")

        # Separate cached vs to-call items
        to_call: List[Dict[str, Any]] = []
        cached_pairs: List[Tuple[str,str]] = []

        for it in items:
            a_id = _safe_str(it.get("a_id","")).strip()
            if not a_id:
                continue
            th = per_row_hash.get((a_id, c.id), "")
            k = _cache_key(model=model, cid=c.id, a_id=a_id, text_hash=th, trunc_chars=trunc_chars)
            if use_cache and k in cache_out:
                # reuse cached evidence
                ev = dict(cache_out[k])
                ev.setdefault("used", True)
                llm_results[(a_id, c.id)] = ev
                cached_pairs.append((a_id, c.id))
            else:
                to_call.append(it)

        if log_cb:
            log_cb(f"[EL] cache_hits={len(cached_pairs)} | to_call={len(to_call)}\n")

        if c.operator == "llm" and to_call:
            res = run_m1_llm_for_criterion(
                crit_pack,
                to_call,
                model=model,
                trunc_chars=trunc_chars,
                batch_size=batch_size,
                log=log_cb,
                progress=progress_evt,
                cancel_token=cancel_event,
                crit_idx=ci,
                crit_total=len(crits),
                block_tag="exclude",
            )
            # merge + write to cache
            for (a_id, cid), ev in res.items():
                llm_results[(a_id, cid)] = ev
                r = id_to_row.get(a_id)
                if not r:
                    continue
                th = per_row_hash.get((a_id, cid), "")
                k = _cache_key(model=model, cid=cid, a_id=a_id, text_hash=th, trunc_chars=trunc_chars)
                if use_cache:
                    cache_out[k] = dict(ev)

        elif c.operator != "llm":
            # deterministic operator (rare in EL). Mark uncertain; real deterministic logic can be added later.
            for it in to_call:
                a_id = _safe_str(it.get("a_id","")).strip()
                llm_results[(a_id, c.id)] = {"used": False, "decision":"uncertain","confidence":0.0,"field":"abstract","quote":"","span":None,"valid_quote":False}

        if progress_cb:
            progress_cb(ci / max(1, len(crits)) * 0.7)

    # Now compute per-row statuses
    for idx, r in enumerate(rows, start=1):
        if cancel_event.is_set():
            break

        a_id = _safe_str(r.get("local_id","")).strip()
        failed: List[str] = []
        missing: List[str] = []
        met: List[str] = []
        uncertain: List[str] = []
        evidence: Dict[str, Any] = {}

        for c in crits:
            # missing if all target fields are empty
            all_empty = True
            for t in c.targets:
                if _safe_str(r.get(t, "")).strip():
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
                evidence[c.id] = {"status":"UNCERTAIN", "note":"non-llm operator in EL stage"}
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
                    # (not expected in EL) treat as include
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
            outcome = "PASS_FLAGGED"

        fr = dict(r)
        fr["el_outcome"] = outcome
        fr["el_failed_ids"] = ",".join(failed)
        fr["el_missing_ids"] = ",".join(missing)
        fr["el_met_ids"] = ",".join(met)
        fr["el_uncertain_ids"] = ",".join(uncertain)
        fr["el_evidence_json"] = json.dumps(evidence, ensure_ascii=False)
        fr["el_reason_summary"] = _summarize_el_reason(outcome, failed, missing, uncertain)

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
        return "PASS_CLEAN: all EL criteria MET."
    bits: List[str] = ["PASS_FLAGGED:"]
    if missing:
        bits.append(f"missing {', '.join(missing)}")
    if uncertain:
        bits.append(f"uncertain {', '.join(uncertain)}")
    if not missing and not uncertain:
        bits.append("no failures")
    return " ".join(bits)


# ------------------------------ UI helpers ------------------------------------

class DataTable(ttk.Frame):
    def __init__(self, parent: tk.Misc, columns: List[str]):
        super().__init__(parent)
        self.columns = columns[:]
        self.tree = ttk.Treeview(self, columns=self.columns, show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._sort_state: Dict[str, bool] = {}
        for c in self.columns:
            self.tree.heading(c, text=c, command=lambda col=c: self.sort_by(col))
            self.tree.column(c, width=120, anchor="w")

        self._rows: List[Dict[str, Any]] = []
        self._id_map: Dict[str, Dict[str, Any]] = {}

    def set_rows(self, rows: List[Dict[str, Any]]):
        self._rows = rows
        self._id_map = {}
        self.tree.delete(*self.tree.get_children())
        # incremental insert to keep UI responsive
        self._insert_chunk(0, chunk=200)

    def _insert_chunk(self, start: int, chunk: int = 200):
        end = min(len(self._rows), start + chunk)
        for i in range(start, end):
            r = self._rows[i]
            iid = f"R{i}"
            vals = [ _safe_str(r.get(c, "")) for c in self.columns ]
            self.tree.insert("", "end", iid=iid, values=vals)
            self._id_map[iid] = r
        if end < len(self._rows):
            self.after(1, lambda: self._insert_chunk(end, chunk))

    def get_selected_row(self) -> Optional[Dict[str, Any]]:
        sel = self.tree.selection()
        if not sel:
            return None
        return self._id_map.get(sel[0])

    def sort_by(self, col: str):
        asc = not self._sort_state.get(col, True)
        self._sort_state[col] = asc
        def keyfun(r: Dict[str, Any]):
            v = _safe_str(r.get(col, ""))
            # numeric if possible
            try:
                return float(v)
            except Exception:
                return v.lower()
        self._rows.sort(key=keyfun, reverse=not asc)
        self.set_rows(self._rows)


class ELView(ttk.Frame):
    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.bundle_zip_path: Optional[str] = None
        self.bundle: Optional[BundleInfo] = None

        self.full_rows: List[Dict[str, Any]] = []
        self.survivors: List[Dict[str, str]] = []
        self.counts: Dict[str, int] = {}
        self.crit_impacts: Dict[str, Dict[str, int]] = {}
        self.row_eval_lists: List[Dict[str, List[str]]] = []
        self.cache_map: Dict[str, Dict[str, Any]] = {}

        self.cancel_event = threading.Event()
        self.worker: Optional[threading.Thread] = None

        # --- Top controls
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)

        self.btn_load = ttk.Button(top, text="Load Bundle ZIP", command=self.on_load_bundle)
        self.btn_load.pack(side="left")

        ttk.Separator(top, orient="vertical").pack(side="left", padx=6, fill="y")

        ttk.Label(top, text="Model:").pack(side="left")
        self.var_model = tk.StringVar(value=DEFAULT_MODEL)
        ttk.Entry(top, textvariable=self.var_model, width=18).pack(side="left", padx=(2, 8))

        ttk.Label(top, text="Batch:").pack(side="left")
        self.var_batch = tk.IntVar(value=DEFAULT_BATCH_SIZE)
        ttk.Spinbox(top, from_=1, to=500, textvariable=self.var_batch, width=6).pack(side="left", padx=(2, 8))

        ttk.Label(top, text="Trunc:").pack(side="left")
        self.var_trunc = tk.IntVar(value=DEFAULT_TRUNC_CHARS)
        ttk.Spinbox(top, from_=200, to=5000, increment=50, textvariable=self.var_trunc, width=7).pack(side="left", padx=(2, 8))

        self.var_use_cache = tk.BooleanVar(value=DEFAULT_USE_CACHE)
        ttk.Checkbutton(top, text="Use cache", variable=self.var_use_cache).pack(side="left", padx=(2, 8))

        self.btn_run = ttk.Button(top, text="Run EL", command=self.on_run_el, state="disabled")
        self.btn_run.pack(side="left")

        self.btn_cancel = ttk.Button(top, text="Cancel", command=self.on_cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=(6, 0))

        ttk.Separator(top, orient="vertical").pack(side="left", padx=6, fill="y")

        self.btn_export_csv = ttk.Button(top, text="Export EL_FULL.csv", command=self.on_export_csv, state="disabled")
        self.btn_export_csv.pack(side="left")
        self.btn_export_xlsx = ttk.Button(top, text="Export EL_FULL.xlsx", command=self.on_export_xlsx, state="disabled")
        self.btn_export_xlsx.pack(side="left", padx=(6, 0))
        self.btn_next_bundle = ttk.Button(top, text="Build next bundle ZIP", command=self.on_build_next_bundle, state="disabled")
        self.btn_next_bundle.pack(side="left", padx=(6, 0))

        self.lbl_key = ttk.Label(top, text="")
        self.lbl_key.pack(side="right")
        self._refresh_key_label()

        # --- Meta + progress
        meta = ttk.Frame(self)
        meta.pack(fill="x", padx=8)
        self.lbl_bundle_meta = ttk.Label(meta, text="")
        self.lbl_bundle_meta.pack(side="left")

        self.lbl_counts = ttk.Label(meta, text="")
        self.lbl_counts.pack(side="right")

        self.pbar = ttk.Progressbar(self, orient="horizontal", mode="determinate")
        self.pbar.pack(fill="x", padx=8, pady=(4, 6))

        # --- Main split: left criteria, right table/log
        main = ttk.Panedwindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, padx=8, pady=6)

        # left panel
        left = ttk.Frame(main, width=320)
        main.add(left, weight=0)

        ttk.Label(left, text="EL Criteria (enabled)").pack(anchor="w")
        self.lst_crit = tk.Listbox(left, height=14)
        self.lst_crit.pack(fill="both", expand=False, pady=(2, 6))
        self.lst_crit.bind("<Double-Button-1>", self.on_criterion_doubleclick)

        ttk.Label(left, text="Warnings").pack(anchor="w")
        self.txt_warn = tk.Text(left, height=6, wrap="word", state="disabled")
        self.txt_warn.pack(fill="both", expand=True, pady=(2, 6))

        # right panel
        right = ttk.Frame(main)
        main.add(right, weight=1)

        # table
        self.table_columns = [
            "local_id", "title", "year",
            "el_outcome", "el_failed_ids", "el_missing_ids", "el_uncertain_ids",
        ]
        self.table = DataTable(right, self.table_columns)
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<Double-Button-1>", self.on_row_doubleclick)

        # log
        ttk.Label(right, text="Log").pack(anchor="w", pady=(6, 0))
        self.txt_log = tk.Text(right, height=8, wrap="word", state="disabled")
        self.txt_log.pack(fill="x", expand=False)

    # -------- UI helpers
    def _refresh_key_label(self):
        self.lbl_key.configure(text=("OPENAI_API_KEY ✓" if _has_openai_key() else "OPENAI_API_KEY ✗"))

    def _log(self, msg: str):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", msg)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _set_warn(self, lines: List[str]):
        self.txt_warn.configure(state="normal")
        self.txt_warn.delete("1.0", "end")
        self.txt_warn.insert("end", "\n".join(lines) if lines else "(none)")
        self.txt_warn.configure(state="disabled")

    def _refresh_counts_label(self):
        if not self.bundle:
            self.lbl_counts.configure(text="")
            return
        pr = self.bundle.parse
        msg = f"Rows: {len(pr.rows)} | Skipped: {len(pr.skipped)}"
        if self.counts:
            msg += (
                f" | OUT: {self.counts.get('OUT',0)}"
                f" | PASS_CLEAN: {self.counts.get('PASS_CLEAN',0)}"
                f" | PASS_FLAGGED: {self.counts.get('PASS_FLAGGED',0)}"
            )
        self.lbl_counts.configure(text=msg)

    def _set_controls_running(self, running: bool):
        self.btn_cancel.configure(state=("normal" if running else "disabled"))
        self.btn_run.configure(state=("disabled" if running else ("normal" if self.bundle else "disabled")))
        self.btn_load.configure(state=("disabled" if running else "normal"))
        self.btn_export_csv.configure(state=("disabled" if running else ("normal" if self.full_rows else "disabled")))
        self.btn_export_xlsx.configure(state=("disabled" if running else ("normal" if self.full_rows else "disabled")))
        self.btn_next_bundle.configure(state=("disabled" if running else ("normal" if self.full_rows else "disabled")))

    # -------- bundle load
    def on_load_bundle(self):
        p = filedialog.askopenfilename(
            title="Select ScreenA bundle ZIP",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")]
        )
        if not p:
            return
        self.bundle_zip_path = p
        self._refresh_key_label()

        try:
            self.bundle = _load_bundle(p)
        except Exception as e:
            self.bundle = None
            messagebox.showerror("Bundle load failed", str(e))
            return

        # read cache from bundle if present
        self.cache_map = {}
        try:
            with zipfile.ZipFile(p, "r") as zf:
                root = self.bundle.root
                mem = zf.namelist()
                cache_member = root + EL_CACHE_REL
                if cache_member in mem:
                    self.cache_map = _load_cache_from_jsonl(_decode_bytes(_read_zip_bytes(zf, cache_member)))
        except Exception:
            self.cache_map = {}

        # meta label
        m = self.bundle.manifest
        schema = _safe_str(m.get("bundle_schema", m.get("schema", ""))).strip() or "unknown"
        created_at = _safe_str(m.get("created_at", "")).strip()
        created_by = _safe_str(m.get("created_by", "")).strip()
        stages = ((m.get("pipeline", {}) or {}).get("stages", None)) or ((m.get("pipeline_state", {}) or {}).get("stages", None)) or {}
        st_el = _safe_str(stages.get("EL", "")).strip() or "unknown"
        self.lbl_bundle_meta.configure(text=f"schema={schema} | created_at={created_at} | created_by={created_by} | EL={st_el}")

        # criteria list
        self.lst_crit.delete(0, "end")
        crits = [c for c in self.bundle.criteria.criteria if c.enabled]
        for c in crits:
            lbl = f"{c.id}  thr={c.threshold:g}  → {c.source_text[:80]}"
            self.lst_crit.insert("end", lbl)

        self._set_warn(self.bundle.criteria.warnings)

        # reset results
        self.full_rows = []
        self.survivors = []
        self.counts = {}
        self.crit_impacts = {}
        self.row_eval_lists = []

        # set table to raw rows
        self.table.set_rows(self.bundle.parse.rows[:2000])  # show first 2000 pre-run for responsiveness
        self._refresh_counts_label()

        self.btn_run.configure(state="normal")

    # -------- run EL
    def on_run_el(self):
        if not self.bundle or self.worker:
            return

        model = self.var_model.get().strip() or DEFAULT_MODEL
        trunc_chars = int(self.var_trunc.get())
        batch_size = int(self.var_batch.get())
        use_cache = bool(self.var_use_cache.get())

        self.cancel_event.clear()
        self.pbar.configure(value=0.0, maximum=100.0)
        self._set_controls_running(True)

        def progress_cb(frac: float):
            # called from worker; route to UI thread
            self.after(0, lambda: self.pbar.configure(value=max(0.0, min(100.0, frac * 100.0))))

        def progress_evt(evt: Dict[str, Any]):
            # optional structured events for advanced UI; currently logs minimal
            kind = _safe_str(evt.get("kind",""))
            sub = _safe_str(evt.get("sub",""))
            if kind == "l_batch" and sub == "sending":
                bi = evt.get("batch_idx"); bt = evt.get("batch_total")
                ci = evt.get("crit_idx"); ct = evt.get("crit_total")
                self.after(0, lambda: self._log(f"[LLM] criterion {ci}/{ct} batch {bi}/{bt} sending...\n"))

        def work():
            try:
                full_rows, survivors, counts, crit_impacts, row_eval_lists, cache_out = run_el_screen(
                    self.bundle.parse,
                    self.bundle.criteria,
                    model=model,
                    trunc_chars=trunc_chars,
                    batch_size=batch_size,
                    use_cache=use_cache,
                    cache_in=self.cache_map if use_cache else {},
                    cancel_event=self.cancel_event,
                    log_cb=lambda s: self.after(0, lambda: self._log(s)),
                    progress_cb=progress_cb,
                    progress_evt=progress_evt,
                )
                if self.cancel_event.is_set():
                    self.after(0, lambda: self._log("\n[CANCELLED]\n"))
                    return
                self.full_rows = full_rows
                self.survivors = survivors
                self.counts = counts
                self.crit_impacts = crit_impacts
                self.row_eval_lists = row_eval_lists
                self.cache_map = cache_out

                # update table to full rows (show outcomes)
                self.after(0, lambda: self.table.set_rows(self.full_rows))
                self.after(0, self._refresh_counts_label)

                # enable exports
                self.after(0, lambda: self.btn_export_csv.configure(state="normal"))
                self.after(0, lambda: self.btn_export_xlsx.configure(state="normal"))
                self.after(0, lambda: self.btn_next_bundle.configure(state="normal"))

            except Exception as e:
                self.after(0, lambda: messagebox.showerror("EL run failed", str(e)))
            finally:
                self.after(0, lambda: self._set_controls_running(False))
                self.worker = None

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def on_cancel(self):
        self.cancel_event.set()
        self._log("\n[Cancel requested]\n")

    # -------- exports
    def on_export_csv(self):
        if not self.full_rows:
            return
        p = filedialog.asksaveasfilename(
            title="Save EL_FULL.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")]
        )
        if not p:
            return
        header = list(self.full_rows[0].keys())
        _write_csv(p, header, self.full_rows)
        messagebox.showinfo("Export", f"Saved:\n{p}")

    def on_export_xlsx(self):
        # Keep it standard-library only: write CSV next to requested xlsx name.
        if not self.full_rows:
            return
        p = filedialog.asksaveasfilename(
            title="Save EL_FULL.xlsx (fallback to CSV if no writer)",
            defaultextension=".xlsx",
            filetypes=[("XLSX", "*.xlsx"), ("CSV", "*.csv")]
        )
        if not p:
            return
        # If user asked CSV, do CSV.
        if p.lower().endswith(".csv"):
            header = list(self.full_rows[0].keys())
            _write_csv(p, header, self.full_rows)
            messagebox.showinfo("Export", f"Saved:\n{p}")
            return

        # Minimal XLSX writer without dependencies is non-trivial; provide a CSV next to it.
        csv_path = p[:-5] + ".csv"
        header = list(self.full_rows[0].keys())
        _write_csv(csv_path, header, self.full_rows)
        messagebox.showinfo("Export", f"No XLSX writer bundled.\nSaved CSV instead:\n{csv_path}")

    def on_build_next_bundle(self):
        if not self.bundle or not self.full_rows:
            return
        out_zip = filedialog.asksaveasfilename(
            title="Save next bundle ZIP (post-EL)",
            defaultextension=".zip",
            filetypes=[("ZIP", "*.zip")]
        )
        if not out_zip:
            return

        # Prepare output structure in-memory then zip.
        # - manifest.json updated
        # - data/current.csv replaced with survivors
        # - reports/EL_FULL.csv + reports/EL_SURVIVORS.csv
        # - input_errors.csv from skipped
        # - cache/EL_cache.jsonl if enabled
        try:
            with zipfile.ZipFile(self.bundle.zip_path, "r") as zf_in:
                members = zf_in.namelist()
                root = self.bundle.root

                # read original manifest
                manifest = dict(self.bundle.manifest)

                # update pipeline stage mark (tolerate both schemas)
                def _set_stage(m: Dict[str, Any], key: str, value: str):
                    if "pipeline" in m and isinstance(m.get("pipeline"), dict):
                        m["pipeline"].setdefault("stages", {})
                        m["pipeline"]["stages"][key] = value
                    if "pipeline_state" in m and isinstance(m.get("pipeline_state"), dict):
                        m["pipeline_state"].setdefault("stages", {})
                        m["pipeline_state"]["stages"][key] = value

                _set_stage(manifest, "EL", "done")
                manifest["updated_at"] = datetime.utcnow().isoformat() + "Z"

                # write new zip
                with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf_out:
                    # copy everything except data/current.csv and reports we replace
                    skip_prefixes = {
                        root + "data/current.csv",
                        root + f"{REPORTS_DIR_REL}/EL_FULL.csv",
                        root + f"{REPORTS_DIR_REL}/EL_SURVIVORS.csv",
                        root + "data/input_errors.csv",
                        root + EL_CACHE_REL,
                        root + "manifest.json",
                    }
                    for m in members:
                        if m in skip_prefixes:
                            continue
                        # also avoid directories
                        if m.endswith("/"):
                            continue
                        zf_out.writestr(m, _read_zip_bytes(zf_in, m))

                    # manifest
                    zf_out.writestr(root + "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

                    # data/current.csv survivors
                    # Use original header order (minus EL columns)
                    header = list(self.bundle.parse.header)
                    # guarantee local_id present
                    if "local_id" not in header:
                        header = ["local_id"] + header
                    buf = io.StringIO()
                    w = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
                    w.writeheader()
                    for r in self.survivors:
                        w.writerow({k: r.get(k, "") for k in header})
                    zf_out.writestr(root + "data/current.csv", buf.getvalue())

                    # reports
                    rep_full = root + f"{REPORTS_DIR_REL}/EL_FULL.csv"
                    rep_surv = root + f"{REPORTS_DIR_REL}/EL_SURVIVORS.csv"
                    # full
                    header_full = list(self.full_rows[0].keys())
                    buf2 = io.StringIO()
                    w2 = csv.DictWriter(buf2, fieldnames=header_full, extrasaction="ignore")
                    w2.writeheader()
                    for r in self.full_rows:
                        w2.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in header_full})
                    zf_out.writestr(rep_full, buf2.getvalue())

                    # survivors report = same schema as input current.csv
                    buf3 = io.StringIO()
                    w3 = csv.DictWriter(buf3, fieldnames=header, extrasaction="ignore")
                    w3.writeheader()
                    for r in self.survivors:
                        w3.writerow({k: r.get(k, "") for k in header})
                    zf_out.writestr(rep_surv, buf3.getvalue())

                    # input errors
                    if self.bundle.parse.skipped:
                        buf4 = io.StringIO()
                        # flatten skipped
                        err_header = ["reason", "row_json"]
                        w4 = csv.DictWriter(buf4, fieldnames=err_header)
                        w4.writeheader()
                        for e in self.bundle.parse.skipped:
                            w4.writerow({"reason": _safe_str(e.get("reason","")), "row_json": json.dumps(e.get("row", {}), ensure_ascii=False)})
                        zf_out.writestr(root + "data/input_errors.csv", buf4.getvalue())

                    # cache
                    if self.var_use_cache.get():
                        zf_out.writestr(root + EL_CACHE_REL, _dump_cache_to_jsonl(self.cache_map))

            messagebox.showinfo("Next bundle", f"Saved:\n{out_zip}")
        except Exception as e:
            messagebox.showerror("Next bundle failed", str(e))

    # -------- details
    def on_row_doubleclick(self, _evt=None):
        row = self.table.get_selected_row()
        if not row:
            return
        top = tk.Toplevel(self)
        top.title(f"Row {row.get('local_id','')}")
        top.geometry("850x600")

        txt = tk.Text(top, wrap="word")
        txt.pack(fill="both", expand=True)

        def add(title: str, content: str):
            txt.insert("end", f"\n=== {title} ===\n")
            txt.insert("end", content + "\n")

        add("local_id", _safe_str(row.get("local_id","")))
        add("title", _safe_str(row.get("title","")))
        add("abstract", _safe_str(row.get("abstract","")))
        add("keywords", _safe_str(row.get("keywords","")))
        add("EL outcome", _safe_str(row.get("el_outcome","")))
        add("EL summary", _safe_str(row.get("el_reason_summary","")))

        ev = _safe_str(row.get("el_evidence_json","{}"))
        try:
            evj = json.loads(ev)
            add("EL evidence (json)", json.dumps(evj, ensure_ascii=False, indent=2)[:15000])
        except Exception:
            add("EL evidence (raw)", ev[:15000])

        txt.configure(state="disabled")

    def on_criterion_doubleclick(self, _evt=None):
        # Filter table to rows touched by selected criterion (failed/missing/uncertain/met)
        if not self.full_rows or not self.bundle:
            return
        sel = self.lst_crit.curselection()
        if not sel:
            return
        # parse criterion id from listbox line
        line = self.lst_crit.get(sel[0])
        cid = line.split()[0].strip()

        touched: List[Dict[str, Any]] = []
        for r in self.full_rows:
            parts = ",".join([
                _safe_str(r.get("el_failed_ids","")),
                _safe_str(r.get("el_missing_ids","")),
                _safe_str(r.get("el_uncertain_ids","")),
                _safe_str(r.get("el_met_ids","")),
            ])
            if cid in {p.strip() for p in parts.split(",") if p.strip()}:
                touched.append(r)

        if touched:
            self._log(f"\n[Filter] Criterion {cid}: showing {len(touched)} rows touched.\n")
            self.table.set_rows(touched)
        else:
            self._log(f"\n[Filter] Criterion {cid}: no touched rows.\n")

# ------------------------------ plugin wrapper --------------------------------

class Plugin(BasePlugin):
    def __init__(self, app=None, meta: Optional[PluginMeta] = None):
        if meta is None:
            meta = PluginMeta(id=PLUGIN_ID, title=TAB_TITLE, version=PLUGIN_VERSION)
        super().__init__(app, meta)
        self.view: Optional[ELView] = None

    def build_tab(self, parent: ttk.Notebook) -> tk.Frame:
        frame = ttk.Frame(parent)
        self.view = ELView(frame)
        self.view.pack(fill="both", expand=True)
        return frame

    def on_close(self):
        try:
            if self.view:
                self.view.destroy()
        except Exception:
            pass
        self.view = None
