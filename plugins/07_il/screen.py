
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
    _is_cacheable_evidence,
    llm_provenance,
    new_llm_call_stats,
    summarize_llm_evidence,
    _load_cache_from_jsonl,
    _dump_cache_to_jsonl,
    _render_prompt_for_key,
    resolve_openai_base_url,
    resolve_context_window,
    enforce_context_budget,
    llm_exclusion_allowed,
    OPENAI_BASE_URL_ENV,
)
from plugins._common.llm_client import _cache_key as _shared_cache_key
from plugins._common.bundle import (
    EXCLUSION_SUPPRESSED,
    NOT_SCREENED,
    POLICY_EXCLUSION_PERMITTED,
    POLICY_FLAG_ONLY,
    _verify_sha256_map,
)
from plugins._common.parser import _decode_bytes as _decode_bytes_common
from plugins._common.stage_state import criterion_row_lists
from plugins._common.verdict_gate import (
    ACTION_EXCLUDE,
    ACTION_MET,
    ACTION_SUPPRESS_ABSENCE,
    DECLINED_ABSENCE,
    DECLINED_ABSENCE_AND_FLAG_ONLY,
    DECLINED_FLAG_ONLY,
    verdict_action,
)

from .prompt import PROMPT_VERSION, _build_llm_messages_for_criterion

OUTCOMES = ("OUT", "PASS_CLEAN", "REVIEW", EXCLUSION_SUPPRESSED,
            NOT_SCREENED)

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
    """BOM-safe decode through the shared four-encoding ladder.

    F-73: this was a single ``utf-8-sig`` attempt with ``errors="replace"``,
    so a cp1252 bundle that EH/IH decode correctly mojibaked to U+FFFD here
    — corrupting exactly the text the evidence-quote validation compares
    against. Delegates to plugins/_common/parser._decode_bytes (utf-8-sig,
    utf-8, cp1252, latin-1), which is byte-identical to the old behaviour
    for the UTF-8 input the goldens use.
    """
    return _decode_bytes_common(b)

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

def _csv_read_strict(text: str) -> Tuple[List[str], List[Dict[str, str]], List[Dict[str, Any]]]:
    """_csv_read for the corpus: a ragged row is rejected and recorded, not
    silently padded or truncated to the header width.

    F-72. EH/IH have always rejected such rows as ``bad_column_count``
    (plugins/_common/parser.py:305-307); repairing the same file here meant
    the corpus depended on which stage opened it, and the repair left no
    entry in the audit trail. ``_csv_read`` keeps its lenient behaviour for
    the criteria table and report re-reads; only data/current.csv comes
    through this strict variant.
    """
    f = io.StringIO(text)
    reader = csv.reader(f)
    rows = list(reader)
    if not rows:
        return [], [], []
    header = [h.strip() for h in rows[0]]
    expected = len(header)
    out: List[Dict[str, str]] = []
    skipped: List[Dict[str, Any]] = []
    for r in rows[1:]:
        if not any((c or "").strip() for c in r):
            continue
        if len(r) != expected:
            skipped.append({
                "reason": f"bad_column_count:{len(r)}!=expected:{expected}",
                "row": {"raw": " | ".join(_safe_str(c) for c in r)},
            })
            continue
        out.append({h: r[j] for j, h in enumerate(header)})
    return header, out, skipped


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
        # F-72: strict read — ragged rows divert to the skip list.
        header, rows, skipped = _csv_read_strict(current_txt)
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

        # F-05: verify the manifest digests against the bytes actually in
        # the zip. Nothing downstream checked before, which is how the
        # stale digests IL itself wrote went unnoticed: the manifest
        # asserted a hash for a data/current.csv that had been replaced.
        #
        # Warn rather than refuse. A digest mismatch means the file changed
        # after the manifest was written, which is worth stopping to look
        # at, but refusing to open the bundle would strand a reviewer whose
        # only copy of the corpus is inside it. The warnings ride on the
        # criteria report because that is what the View already surfaces.
        to_check = {}
        for member in members:
            if member.endswith("/") or not member.startswith(root):
                continue
            rel = member[len(root):]
            if rel == "manifest.json":
                continue
            try:
                to_check[rel] = _read_zip_bytes(zf, member)
            except Exception:
                continue
        criteria.warnings.extend(_verify_sha256_map(manifest, to_check))

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
# this stage's PROMPT_VERSION and this stage's prompt builder, so the key is
# derived from the exact bytes IL would send for this (criterion, item) pair.
#
# F-01: the key is the hash of the rendered prompt, not of a hand-maintained
# list of fields. The prompt is rendered for a batch of one because the cache
# is keyed per (a_id, criterion) while the real call batches many items; a
# one-item render is the per-item slice of what the model sees, and it is what
# makes criterion wording, record text and trunc_chars all reach the key
# without being enumerated.
#
# F-89: `endpoint` is required and is threaded in from the caller, which
# resolves it once per run. It is not defaulted and not read from the
# environment here — see plugins/_common/llm_client.py::_cache_key.
def _cache_key(*, model: str, criterion: Dict[str, Any], item: Dict[str, Any],
               trunc_chars: int, endpoint: str, temperature: float = 0.0) -> str:
    return _shared_cache_key(
        prompt_version=PROMPT_VERSION,
        model=model,
        rendered_prompt=_render_prompt_for_key(
            _build_llm_messages_for_criterion(criterion, [item], trunc_chars)
        ),
        endpoint=endpoint,
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
    bool,                       # cancelled (F-02)
    Dict[str, int],             # run report (wave 8)
]:
    """...

    The eighth element is the **run report**: what the stage learned, and
    what it failed to learn. Before it, a wholly failed run and a wholly
    uncertain run were indistinguishable to every caller — identical
    ``counts``, identical survivors, ``cancelled: False``, ``not_screened:
    False`` — so the UI could only say "IL done." for both and the manifest
    could only record the same history entry for both.

    Its record-level keys are **derived** by
    ``plugins/_common/llm_client.py::summarize_llm_evidence`` from
    ``llm_results``, the same evidence map the row loop below makes its
    decisions from, so the report cannot disagree with the output it
    describes. Its call-level keys are counted at the call, because a call
    that raised and was then salvaged leaves no record. See
    ``new_llm_call_stats`` for why the split is drawn there.

    A dict rather than more tuple positions: later waves add provenance
    (F-88, F-135) to the same history entry, and a key is cheaper to add
    than a position — and safer, since a positional append is exactly what
    silently rebinds an existing unpack.
    """
    rows = parse.rows
    crits = [c for c in criteria_report.criteria if c.enabled]
    counts = {k: 0 for k in OUTCOMES}
    crit_impacts: Dict[str, Dict[str, int]] = {c.id: {"failed":0,"missing":0,"met":0,"uncertain":0} for c in crits}

    full_rows: List[Dict[str, Any]] = []
    survivors: List[Dict[str, str]] = []
    row_eval_lists: List[Dict[str, List[str]]] = []

    cache_out: Dict[str, Dict[str, Any]] = dict(cache_in or {})
    cancelled = False

    # Wave 8. One tally threaded through every criterion's calls; the
    # record-level half of the report is derived from llm_results at the end
    # rather than accumulated here.
    call_stats: Dict[str, int] = new_llm_call_stats()

    # F-88. Filled once the endpoint is resolved, below. It stays empty on
    # the zero-criteria path, which returns before that point: a stage that
    # consulted no model must not name one — the same rule the run report
    # itself follows.
    provenance: Dict[str, Any] = {}
    # F-145. A mutable holder set at the same point as `provenance` and
    # obeying the same omission rule: a stage that consulted no model
    # records no policy, because a policy that governed no verdict is not
    # a fact about this run. The zero-criteria path returns before either
    # is filled, which is what makes that true.
    policy: Dict[str, Any] = {}

    # F-65 (wave 15c): criteria this stage cannot evaluate, {cid: reason}.
    # Filled by the criterion loop, carried into the run report and from
    # there into the manifest's history entry — the two places that used
    # to say nothing while the criterion silently did nothing.
    not_evaluated: Dict[str, str] = {}

    def _run_report(evidence: Dict[Tuple[str, str], Dict[str, Any]]) -> Dict[str, Any]:
        report: Dict[str, Any] = dict(summarize_llm_evidence(evidence))
        report.update(call_stats)
        if provenance:
            report["provenance"] = dict(provenance)
        report.update(policy)
        if not_evaluated:
            report["not_evaluated"] = dict(not_evaluated)
        return report

    if not crits:
        for r in rows:
            if cancel_event.is_set():
                cancelled = True
                break
            fr = dict(r)
            # F-34: NOT_SCREENED, not PASS_CLEAN. PASS_CLEAN is the
            # stronger of the two survivor labels — it means every
            # criterion was met — so using it for a stage that
            # evaluated none asserted the opposite of the truth.
            fr["il_outcome"] = NOT_SCREENED
            fr["il_failed_ids"] = ""
            fr["il_missing_ids"] = ""
            fr["il_met_ids"] = ""
            fr["il_uncertain_ids"] = ""
            fr["il_reason_summary"] = (
                f"{NOT_SCREENED}: IL had no enabled criteria. This record "
                f"was neither included nor excluded; it passed through "
                f"unexamined."
            )
            fr["il_evidence_json"] = "{}"
            full_rows.append(fr)
            survivors.append(dict(r))
            row_eval_lists.append(criterion_row_lists(
                failed=[], missing=[], met=[], uncertain=[],
                suppressed=[]))
        counts[NOT_SCREENED] = len(survivors)
        if progress_cb:
            progress_cb(1.0)
        return full_rows, survivors, counts, crit_impacts, row_eval_lists, cache_out, cancelled, _run_report({})

    # Build items for LLM (same base shape as legacy), but robust to header casing
    header_map: Dict[str, str] = {h.lower(): h for h in (parse.header or [])}

    def getv(row: Dict[str, str], key: str) -> str:
        k = header_map.get(key.lower(), key)
        return _safe_str(row.get(k, ""))

    items = [{
        "a_id": getv(r, "local_id").strip(),
        "title": getv(r, "title"),
        "abstract": getv(r, "abstract"),
        "keywords": getv(r, "keywords"),
    } for r in rows]

    # F-87, the duplicate-id companion. Two rows carrying the same local_id
    # go into the prompt as two different records under one a_id, so whatever
    # the model answers cannot be attributed to either of them: the maps here
    # are built by assignment, the last row under an id wins, and a quote
    # drawn from that row then validates and excludes every row sharing the
    # id — including ones whose own text does not contain it. Measured at
    # OUT = 2/3.
    #
    # Both _load_bundle and plugins/_common/parser (since F-55) already drop
    # duplicates, and both keep doing so. But they are upstream, so the
    # safety property was carried by the caller: anything constructing a
    # ParseReport directly walked straight past it. The guard belongs to the
    # gate as well, so it is here too.
    #
    # Ambiguous ids are withheld from the LLM entirely rather than asked
    # about and then discarded — the answer would be unusable and billed.
    # With no verdict to look up, the row loop's evidence gate degrades them
    # to UNCERTAIN, which flags the rows for a human instead of acting on
    # them. Nothing is dropped from the output.
    seen_ids: Set[str] = set()
    ambiguous_ids: Set[str] = set()
    for it in items:
        lid = _safe_str(it.get("a_id", "")).strip()
        if not lid:
            continue
        if lid in seen_ids:
            ambiguous_ids.add(lid)
        seen_ids.add(lid)
    if ambiguous_ids:
        if log_cb:
            log_cb(
                f"[IL] {len(ambiguous_ids)} duplicated local_id(s) "
                f"({', '.join(sorted(ambiguous_ids))}) carry more than one "
                f"record each. A verdict cannot be attributed to a single "
                f"record, so these rows are not screened by the LLM and are "
                f"reported as uncertain. Fix the duplicate ids upstream.\n"
            )
        items = [it for it in items
                 if _safe_str(it.get("a_id", "")).strip() not in ambiguous_ids]

    # a_id -> the item as the prompt builder will see it. This is what the
    # cache key is derived from (F-01), and it doubles as the "is this a_id
    # one of ours?" guard when merging LLM results back in.
    #
    # The per-criterion text hash that used to be precomputed here is gone:
    # it hashed only the criterion's *target* fields, but the prompt ships
    # title, abstract and keywords for every criterion regardless of target.
    # Editing a record's keywords under a title-targeted criterion therefore
    # changed the model's input without changing the key — the same defect as
    # F-01, one level down. The rendered prompt covers all three.
    id_to_item: Dict[str, Dict[str, Any]] = {}
    for it in items:
        lid = _safe_str(it.get("a_id", "")).strip()
        if lid:
            id_to_item[lid] = it

    # F-92. Resolved once per run, here, because two consumers must not
    # disagree about it: the log line below and — from F-89 — every cache key
    # computed in the loop. `_openai_client_for` reads the same function when
    # it builds the client, so the endpoint a key was computed for is the
    # endpoint the call actually went to.
    # Session C: resolved FOR THIS STAGE, so that a per-stage endpoint
    # override reaches the cache key and the provenance record as well as
    # the client. Two answers to "where did this run go?" is F-89's shape.
    endpoint = resolve_openai_base_url("IL")

    # F-88. Recorded here rather than at export, because this is the only
    # point at which all six facts are simultaneously true of *this run*:
    # the endpoint has just been resolved and is not available to the UI at
    # all, and the model and temperature the UI holds are live widget values
    # that may be edited between the run and the export.
    # F-154 / wave 15b: resolved once per run, beside the endpoint
    # and for the same reason (one answer per run, F-89's shape).
    context_window = resolve_context_window("IL")

    provenance.update(llm_provenance(
        model=model, endpoint=endpoint, temperature=temperature,
        prompt_version=PROMPT_VERSION, trunc_chars=trunc_chars,
        batch_size=batch_size, context_window=context_window,
    ))

    # F-145. Resolved once per run, beside the endpoint, for the same
    # reason: the row loop below must not ask this question per record and
    # get two answers if the store changes mid-run.
    allow_exclusion = llm_exclusion_allowed("IL")
    policy["exclusion_policy"] = (POLICY_EXCLUSION_PERMITTED if allow_exclusion
                                  else POLICY_FLAG_ONLY)
    if log_cb and not allow_exclusion:
        log_cb("[IL] flag-only: an LLM verdict may flag a record for review "
               "but may not exclude it. The provider dialog can permit "
               "exclusion, once the model has been validated on this "
               "corpus.\n")

    if log_cb:
        # F-119's lesson: say what the code observed. Whether the variable
        # was set is the actionable half — a user following the README's
        # Ollama recipe needs to see at a glance that their `.env` took
        # effect, and "endpoint=https://api.openai.com/v1" alone does not
        # distinguish "I chose the public API" from "my .env was not read".
        _endpoint_src = (
            f"set via {OPENAI_BASE_URL_ENV}"
            if os.environ.get(OPENAI_BASE_URL_ENV, "").strip()
            else f"{OPENAI_BASE_URL_ENV} not set; using the default"
        )
        log_cb(f"[IL] endpoint={endpoint} ({_endpoint_src})\n")

    # F-154 / wave 15b: the context-budget guard. Whole-corpus and
    # pre-run — every prompt the run would send is rendered and
    # budgeted BEFORE the first call, and a run that cannot fit
    # raises ContextBudgetExceeded to the View's existing error
    # path with zero calls spent. The logic lives once in
    # plugins/_common/llm_client.py; this stage and its standalone
    # shell both pass through here, so every path that can carry a
    # batch size reaches the guard.
    _guard_packs = [{
        "id": c.id,
        "type": c.ctype,
        "operator": c.operator,
        "target": ",".join(c.targets),
        "what": c.what_list,
        "how": "llm",
        "label": c.label or c.source_text,
        "threshold": c.threshold,
    } for c in crits if c.operator == "llm"]
    if _guard_packs and items:
        # F-203 (wave 15c): the refusal message's wording follows the
        # resolved pair — the same instrument the default window keys
        # on — so a hosted user is not told about a truncation
        # mechanism measured only on a local server.
        from plugins._common.stage_state import is_paid_vendor
        enforce_context_budget(
            criteria=_guard_packs, items=items, batch_size=batch_size,
            trunc_chars=trunc_chars,
            build_messages=_build_llm_messages_for_criterion,
            window=context_window, hosted=is_paid_vendor(endpoint))

    # Run criterion by criterion (legacy-style)
    llm_results: Dict[Tuple[str,str], Dict[str, Any]] = {}

    for ci, c in enumerate(crits, start=1):
        if cancel_event.is_set():
            cancelled = True
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
            k = _cache_key(model=model, criterion=crit_pack, item=it,
                           trunc_chars=trunc_chars, endpoint=endpoint,
                           temperature=temperature)
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
                stats=call_stats,
            )
            # merge + write to cache
            for (a_id, cid), ev in res.items():
                llm_results[(a_id, cid)] = ev
                it = id_to_item.get(a_id)
                if not it:
                    continue
                # cid is c.id here — res only ever carries this criterion —
                # so crit_pack is the pack the prompt was rendered from.
                k = _cache_key(model=model, criterion=crit_pack, item=it,
                               trunc_chars=trunc_chars, endpoint=endpoint,
                               temperature=temperature)
                # F-87: a non-answer is not a verdict. Without this gate a
                # transient 500, a timeout, an auth blip or a plain omission
                # was cached under a key that matches on every later run, so
                # the user's remedy — re-run — was the one action the cache
                # defeated. See _is_cacheable_evidence.
                if use_cache and _is_cacheable_evidence(ev):
                    cache_out[k] = dict(ev)

        elif c.operator != "llm":
            # F-65 (wave 15c): a deterministic operator here is never
            # evaluated — the row loop marks every record UNCERTAIN with
            # its note, unchanged. What changed: the inert stubs this
            # branch used to write into `llm_results` are gone. Nothing
            # ever read them for a decision (the row loop short-circuits
            # first), but `summarize_llm_evidence` counted each as
            # `no_answer` — model silence — so one such criterion made
            # `run_outcome` diagnose "low answer rate … came back
            # unreadable" about requests that were never sent, into the
            # manifest. The skip is recorded per criterion instead, where
            # the report, the manifest and the completion message can
            # say it.
            not_evaluated[c.id] = (
                f"not evaluated: deterministic operator '{c.operator}' "
                f"at IL, which runs llm only (F-65)")

        if progress_cb:
            progress_cb(ci / max(1, len(crits)) * 0.7)

    # Now compute per-row statuses
    #: Rule (c)'s named counter (wave 15e): criterion-verdicts declined by
    #: the absence rule, run-wide. Recorded into `policy` after the loop —
    #: presence-by-key like `not_evaluated`, so a run with none records
    #: nothing — and carried by `_run_report` into the manifest's history
    #: entry, where "provider not trusted" and "verdict class not
    #: provable" stay tellable apart.
    absence_suppressed = 0
    for idx, r in enumerate(rows, start=1):
        if cancel_event.is_set():
            cancelled = True
            break

        a_id = getv(r, "local_id").strip()
        failed: List[str] = []
        missing: List[str] = []
        met: List[str] = []
        uncertain: List[str] = []
        #: Criteria on which the model returned an excluding verdict that
        #: policy declined to act on. Separate from `uncertain`, which is
        #: what the gate REFUSING produces — the two are different facts
        #: about the record. Since wave 15e there are two decliners —
        #: flag-only (F-145) and the absence rule (rule (c): a removal
        #: justified by absence is never auto-acted) — and `suppressed_by`
        #: records which one applied per criterion, because the reason
        #: summary must not say "flag-only" about a removal no setting
        #: could have permitted.
        suppressed: List[str] = []
        suppressed_by: Dict[str, str] = {}
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
            # Wave 15e (F-195/F-21): the gate is the truth table in
            # plugins/_common/verdict_gate.py — keyed on DIRECTION OF HARM
            # and JUSTIFICATION TYPE, read off the criterion's own type
            # polarity, never the stage's (both of a criterion's arms are
            # live here whatever the stage; F-206's mismatch lands on its
            # correct row by construction). The table decides; this loop
            # only routes. `_excluded_by` still routes an excluding
            # verdict to `failed` (acted on) or `suppressed` (recorded,
            # not acted on) — never both, because `failed` is what drives
            # OUT and two representations of one fact is F-69's shape.
            #
            # IL's criteria are include-typed, so "the model said
            # exclude" is `decision == "not_meet"` here where it is
            # `"meet"` in EL — a removal justified by ABSENCE, which is
            # rule (c)'s row: never auto-acted.
            action = verdict_action(
                ctype=c.ctype, decision=decision, confidence=confidence,
                threshold=float(c.threshold),
                quote=_safe_str(ev.get("quote", "")),
                valid_quote=valid_quote)

            status = "UNCERTAIN"
            if action == ACTION_MET:
                status = "MET"
                met.append(c.id)
                crit_impacts[c.id]["met"] += 1
            elif action == ACTION_EXCLUDE:
                # A removal justified by PRESENCE that passed the strict
                # gate; F-145's policy decides whether it acts.
                status = _excluded_by(c.id, failed, suppressed,
                                      crit_impacts, allow_exclusion)
                if status == "SUPPRESSED":
                    suppressed_by[c.id] = DECLINED_FLAG_ONLY
            elif action == ACTION_SUPPRESS_ABSENCE:
                # A removal justified by ABSENCE: never auto-acted — any
                # provider, any confidence, any quote, any setting
                # (rule (c), wave 15e). Routed through `_excluded_by` with
                # exclusion forced off so the suppression accounting has
                # one home.
                status = _excluded_by(c.id, failed, suppressed,
                                      crit_impacts, allow_exclusion=False)
                suppressed_by[c.id] = (
                    DECLINED_ABSENCE if allow_exclusion
                    else DECLINED_ABSENCE_AND_FLAG_ONLY)
                absence_suppressed += 1
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
        elif suppressed:
            # F-145. Above PASS_CLEAN and REVIEW both, because it is the
            # more specific fact: this record was not merely unresolved,
            # the model asked for its removal and the removal was declined.
            # Below OUT because `failed` can only be non-empty when
            # exclusion is permitted, in which case no suppression happened.
            outcome = EXCLUSION_SUPPRESSED
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
        fr["il_reason_summary"] = _summarize_el_reason(
            outcome, failed, missing, uncertain, suppressed, suppressed_by)

        full_rows.append(fr)
        row_eval_lists.append(criterion_row_lists(
            failed=failed, missing=missing, met=met,
            uncertain=uncertain, suppressed=suppressed))

        if outcome != "OUT":
            survivors.append(dict(r))

        counts[outcome] = counts.get(outcome, 0) + 1

        if progress_cb and idx % 25 == 0:
            # remaining 30% of progress
            progress_cb(0.7 + (idx / max(1, len(rows))) * 0.3)

    if progress_cb:
        progress_cb(1.0)

    if absence_suppressed:
        policy["absence_suppressed"] = absence_suppressed

    return full_rows, survivors, counts, crit_impacts, row_eval_lists, cache_out, cancelled, _run_report(llm_results)

def _excluded_by(cid: str, failed: List[str], suppressed: List[str],
                 crit_impacts: Dict[str, Dict[str, int]],
                 allow_exclusion: bool) -> str:
    """Route an excluding verdict, and return its status.

    F-145. One place decides, so no two callers can disagree, and the
    criterion lands in exactly one list — `failed` drives the OUT branch,
    so a suppressed verdict appearing there too would be two
    representations of one fact (F-69's shape). Two callers since wave
    15e: a presence-removal that passed the strict gate arrives with the
    run's real `allow_exclusion`, and an absence-removal (rule (c))
    arrives with it forced ``False``, because that class is never
    auto-acted whatever the policy.

    The twin of this function is `plugins/06_el/screen.py::_excluded_by`.
    These two modules are the deliberate near-duplicates F-14 tracks and
    the byte-identity goldens lock; de-duplicating the engines is that
    row's L-effort migration and is not attempted here.
    """
    if allow_exclusion:
        failed.append(cid)
        crit_impacts[cid]["failed"] += 1
        return "FAILED"
    suppressed.append(cid)
    # Counted under `failed` in the criterion-impact table on purpose: that
    # table answers "what is this criterion doing to my corpus?", and the
    # answer is that it is the criterion the model wants to exclude on.
    # Where the record ended up is the record's fact, carried by the
    # outcome; what the criterion asserted is the criterion's, and
    # suppressing the action does not change what was asserted.
    crit_impacts[cid]["failed"] += 1
    return "SUPPRESSED"


def _summarize_el_reason(outcome: str, failed: List[str], missing: List[str],
                         uncertain: List[str],
                         suppressed: Optional[List[str]] = None,
                         suppressed_by: Optional[Dict[str, str]] = None) -> str:
    if outcome == "OUT":
        return f"OUT: failed {', '.join(failed)}"
    if outcome == "PASS_CLEAN":
        return "PASS_CLEAN: all IL criteria MET."
    if outcome == EXCLUSION_SUPPRESSED:
        # Spelled out rather than left to the reader, because this is the
        # line a human reviewer reads when deciding what to do with the
        # record, and "the model wanted this out" is the actionable half.
        # Since wave 15e it must also name WHICH policy declined —
        # flag-only (F-145) or the absence rule (rule (c)) — because
        # "flag-only is in force" is false about a removal no setting
        # could have permitted.
        by = suppressed_by or {}
        sup = list(suppressed or [])
        absence = [c for c in sup
                   if str(by.get(c, "")).startswith(DECLINED_ABSENCE)]
        presence = [c for c in sup if c not in set(absence)]
        if not absence:
            return (f"{EXCLUSION_SUPPRESSED}: the model returned an excluding "
                    f"verdict on {', '.join(sup)} which passed the "
                    f"evidence gate. Flag-only is in force for this provider, so "
                    f"the record was NOT excluded and needs human review.")
        absence_clause = (
            f"the model answered not_meet on {', '.join(absence)} — a "
            f"removal justified by absence, which is never auto-acted, "
            f"whatever the provider")
        if any(by.get(c) == DECLINED_ABSENCE_AND_FLAG_ONLY for c in absence):
            absence_clause += (" (flag-only is in force for this provider "
                               "besides)")
        if not presence:
            return (f"{EXCLUSION_SUPPRESSED}: {absence_clause}. The record "
                    f"was NOT excluded and needs human review.")
        return (f"{EXCLUSION_SUPPRESSED}: the model returned an excluding "
                f"verdict on {', '.join(presence)} which passed the evidence "
                f"gate and flag-only is in force for this provider; and "
                f"{absence_clause}. The record was NOT excluded and needs "
                f"human review.")
    bits: List[str] = ["REVIEW:"]
    if missing:
        bits.append(f"missing {', '.join(missing)}")
    if uncertain:
        bits.append(f"uncertain {', '.join(uncertain)}")
    if not missing and not uncertain:
        bits.append("no failures")
    return " ".join(bits)
