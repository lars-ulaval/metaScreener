# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
plugins/_common/bundle.py — shared bundle IO for EH/IH.

Owns:
  - BundleInfo dataclass: in-memory representation of a screening bundle
    (manifest, criteria CSV bytes, current.csv bytes, optional input
    errors, root path inside zip).

  - Bundle-zip readers (pure, no stage dependency):
      _detect_bundle_root: find the common root prefix inside the zip.
      _read_zip_bytes:     read a single member as bytes.
      _find_first_member:  resolve a logical path under the bundle root
                           against a list of candidate file names.
      _load_bundle:        open a bundle zip and emit a BundleInfo.

  - Bundle-zip writer (stage-parametrized):
      _export_next_bundle_zip: write the next-stage bundle zip with
        data/current.csv replaced by survivors, plus reports/{stage}_FULL.csv
        and reports/{stage}_SURVIVORS.csv. Manifest's pipeline + history are
        updated for the stage that just ran. Calls _export_xlsx and
        _write_csv_bytes from plugins._common.exporters.

The bundle helpers are character-identical between EH and IH; only
_export_next_bundle_zip carries six stage-specific literals (report
file names, full-report column prefix, manifest stage marker, history
entry stage, created_by tag), all parametrized over a `stage` argument.

Pulled-in from plugins._common.parser:
  - _safe_str, _decode_bytes, _sha256_hex, _iso_now.
Pulled-in from plugins._common.exporters:
  - _export_xlsx, _write_csv_bytes.

Consumed by:
  - plugins/04_eh/plugin.py  (called from EHView export actions)
  - plugins/05_ih/plugin.py  (same)
"""
import csv
import io
import json
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from plugins._common.parser import (
    _decode_bytes,
    _iso_now,
    _safe_str,
    _sha256_hex,
)
from plugins._common.exporters import (
    _export_xlsx,
    _write_csv_bytes,
)
from plugins._common.input_errors import (
    from_dict_skipped,
    from_tuple_skipped,
    merge_input_errors_csv,
    read_input_errors,
)


@dataclass
class BundleInfo:
    zip_path: str
    root: str                       # e.g. "ScreenA_Bundle/" or ""
    manifest: Dict[str, Any]
    members: List[str]


# ----------------------------
# Outcomes
# ----------------------------

NOT_SCREENED = "NOT_SCREENED"
"""Outcome for a record that passed through a stage which evaluated no
criteria at all.

F-34. A stage with zero enabled criteria used to assign ``PASS_CLEAN`` to
every record and report every record as a survivor. ``PASS_CLEAN`` is the
stronger of the two survivor labels — it means "every criterion was met" —
so a stage that did no work reported itself with the label that most
strongly asserts the opposite, and was indistinguishable from a stage that
ran correctly and excluded nothing.

The records still pass through to the next stage: not having screened them
is no reason to drop them, and emptying the corpus would be a worse failure
than the one being fixed. What changes is that they are no longer described
as having passed anything.
"""


EXCLUSION_SUPPRESSED = "EXCLUSION_SUPPRESSED"
"""Outcome for a record the model asked to remove while flag-only was on.

Wave 12, F-145. The model produced a confident, well-quoted excluding
verdict; the evidence gate **passed** it; and the configured provider is
not permitted to act on it, so the record survives and is routed to human
review instead.

**This is deliberately not ``PASS_FLAGGED`` / ``REVIEW``, and the
distinction is the point.** Those mean the gate refused the verdict — the
quote did not validate, the confidence sat below threshold, or the model
said "uncertain". This one means the gate accepted the verdict and policy
declined to act on it. "The model said exclude and we did not act on it"
and "the model could not decide" are different facts about the record, and
a reader of the report has to be able to tell them apart. Reusing a label
that asserts something other than what happened is precisely the error
``NOT_SCREENED`` above exists to correct.

What the model said is not discarded: the per-criterion evidence entry
keeps ``status: "SUPPRESSED"`` alongside the decision, the confidence and
the quote, and ``{stage}_reason_summary`` names the criteria in prose. The
fact is carried there rather than in a new report column because a new
column moves ``tests/golden/{el,il}_filtered_v3.1.0.csv``.
"""


#: How a run's exclusion policy is spelled in the manifest. Two words
#: rather than a boolean, because ``"flag_only": false`` reads as a denial
#: of something and ``"exclusion_policy": "exclusion_permitted"`` reads as
#: a statement of what was done.
POLICY_FLAG_ONLY = "flag_only"
POLICY_EXCLUSION_PERMITTED = "exclusion_permitted"

_EXCLUSION_POLICIES = (POLICY_FLAG_ONLY, POLICY_EXCLUSION_PERMITTED)


def history_exclusion_policy(entry: Mapping[str, Any]) -> Optional[bool]:
    """Was this history entry's run flag-only? ``None`` if unrecorded.

    Tri-state on purpose, and the third state is the one that matters.
    Every bundle written before wave 12 lacks the key entirely, and
    ``bool(entry.get("exclusion_policy", False))`` would read those as
    "exclusion was permitted" — putting a positive claim about a real
    screening decision into a reviewer's hands on the strength of a key
    that was never written.

    That is F-68's rule, whose statement in this codebase is
    ``InputError.observed_len``'s: values "stay None for stages that do
    not compute them rather than being invented, so an empty cell means
    'not measured' and not 'measured as zero'." It is also
    ``llm_readiness``'s ``NOT_CHECKED``: being told nothing is its own
    state rather than silent optimism.

    Recognised values only. A stray ``null``, a bare boolean from a
    hand-edited manifest, or a spelling this build does not know reads as
    unrecorded rather than being guessed at — F-70's half of the same
    rule, where an old artefact keeps a documented degraded behaviour
    instead of having a value inferred for it.

    This lives here, beside the writer, rather than in ``stage_state``:
    that module imports this one and the dependency runs one way only. A
    user-facing *label* for this fact belongs there, next to ``Outcome``.
    """
    value = entry.get("exclusion_policy")
    if value == POLICY_FLAG_ONLY:
        return True
    if value == POLICY_EXCLUSION_PERMITTED:
        return False
    return None


# ----------------------------
# Run summary
# ----------------------------

def _run_summary_counts_text(counts: Dict[str, int], *, stage: str,
                             total_rows: int) -> str:
    """The counts line the stage shows after a run.

    F-34, requirement 2. The warning that a stage has no criteria already
    existed and already reached the GUI, but it is an eight-line read-only
    text box in the left pane, while this line and the survivors table are
    what the user actually reads. When two parts of one screen disagree, the
    part that looks like a result wins — so the no-op has to be said here,
    not only in the warning box.
    """
    n = int(counts.get(NOT_SCREENED, 0) or 0)
    if n:
        return (f"{NOT_SCREENED}: {n} of {total_rows} records — {stage} had no "
                f"enabled criteria, so nothing was screened. These records "
                f"were neither included nor excluded; they passed through "
                f"unexamined.")
    parts = [f"OUT: {counts.get('OUT', 0)}",
             f"PASS_CLEAN: {counts.get('PASS_CLEAN', 0)}"]
    if "PASS_FLAGGED" in counts:
        parts.append(f"PASS_FLAGGED: {counts.get('PASS_FLAGGED', 0)}")
    if "REVIEW" in counts:
        parts.append(f"REVIEW: {counts.get('REVIEW', 0)}")
    return " | ".join(parts)


# ----------------------------
# Export gate
# ----------------------------

CANCELLED_EXPORT_REASON = (
    "This run was cancelled before it reached the end of the corpus, so the "
    "results cover only part of it.\n\n"
    "Exporting them would produce a bundle that is indistinguishable from a "
    "complete run over a smaller corpus: the survivors written to "
    "data/current.csv become the next stage's input, and the records never "
    "reached would be silently dropped from the review.\n\n"
    "Run the stage again to completion before exporting."
)


def _export_block_reason(*, has_rows: bool, cancelled: bool) -> Optional[str]:
    """Return why export must be refused, or None if it may proceed.

    F-02. One rule in one place, called by all four stage UIs, because the
    decision is the same for all of them and a per-stage copy is a per-stage
    opportunity to forget it.

    Cancellation is checked first on purpose: a cancelled run that produced
    no rows at all would otherwise be reported as "run the stage first",
    which is both wrong and reassuring.
    """
    if cancelled:
        return CANCELLED_EXPORT_REASON
    if not has_rows:
        return "Run the stage first — there are no results to export."
    return None


def _export_confirm_reason(*, not_screened: bool, stage: str,
                           outcome_reason: Optional[str] = None) -> Optional[str]:
    """Return the question the user must answer yes to before exporting, or
    None if export may proceed without asking.

    F-34, requirement 3: "allow it and require an explicit acknowledgement
    before the bundle can be exported". This is deliberately a confirmation
    rather than a hard block — passing a stage through with no criteria is a
    legitimate thing to want, and refusing outright would leave no way to do
    it. What is not legitimate is doing it without noticing, which is what a
    read-only warning box permitted.

    **F-93 extends the same machinery rather than building a second one.**
    F-34's gate keys solely on the NOT_SCREENED count, so a stage that
    screened *everything* and learned *nothing* — an unreachable server, a
    misspelled model, a model never pulled, an empty model field — produced
    zero of those and exported with no warning at all. ``outcome_reason``
    is that stage's own diagnosis, rendered by
    ``plugins/_common/stage_state.py::run_outcome`` from the run report the
    engine now returns.

    It is a parameter rather than an import because the dependency runs the
    other way: ``stage_state`` imports this module. EH and IH are not LLM
    stages, have no report to give, and pass nothing — so their twelve call
    sites keep exactly the behaviour they had.

    The F-34 question is checked **first** and wins when both apply. A stage
    with no criteria never called anything, so its report is empty and would
    otherwise read as "no answers"; "you have no criteria for this stage" is
    the diagnosis that tells the user what to do.
    """
    if not not_screened:
        return outcome_reason or None
    return (
        f"{stage} had no enabled criteria, so no record was screened at this "
        f"stage.\n\n"
        f"Every record passed through unexamined. They are recorded as "
        f"{NOT_SCREENED} rather than as having passed, and the bundle's "
        f"manifest will say the stage was a no-op.\n\n"
        f"This usually means the criteria table has no rows for {stage}, or "
        f"that a criterion was rejected — a blank or unrecognised 'type' cell "
        f"is enough to reject one, and rejecting the only one empties the "
        f"stage.\n\n"
        f"Export anyway?"
    )


# ----------------------------
# Manifest digests
# ----------------------------

def _refresh_sha256_map(manifest: Dict[str, Any],
                        written: Dict[str, bytes]) -> Dict[str, Any]:
    """Return a copy of ``manifest`` whose ``sha256`` map is correct for
    every member in ``written`` (keys are bundle-relative, without root).

    F-05. Every stage that replaces a file in the bundle must call this, or
    the manifest goes on asserting the digest of the file it replaced. EL and
    IL never did — the string ``sha`` appeared zero times in either UI — while
    both overwrite data/current.csv with their survivors on export.

    A digest that is present and wrong is worse than no digest: it turns an
    integrity check into false assurance, and a reviewer who later sees a
    mismatch cannot tell tampering from this bug. Entries for files the stage
    did not touch are left exactly as they were.
    """
    out = dict(manifest)
    sha_map = dict(out.get("sha256", {}) or {})
    for rel, body in written.items():
        sha_map[rel] = _sha256_hex(body)
    out["sha256"] = sha_map
    return out


def _verify_sha256_map(manifest: Dict[str, Any],
                       members: Dict[str, bytes]) -> List[str]:
    """Check recorded digests against actual bytes; return one message per
    mismatch, empty if everything agrees.

    F-05, the other half: nothing downstream checked, which is why the stale
    digests EL wrote went unnoticed for as long as they did. A member with no
    recorded digest is not a mismatch — the manifest simply makes no claim
    about it — and a missing or malformed sha256 map is not an error either,
    because refusing to load a bundle over a bad audit field would be a worse
    failure than reporting it.
    """
    problems: List[str] = []
    sha_map = manifest.get("sha256", {})
    if not isinstance(sha_map, dict):
        return problems
    for rel, body in members.items():
        expected = _safe_str(sha_map.get(rel, "")).strip()
        if not expected:
            continue
        actual = _sha256_hex(body)
        if expected != actual:
            problems.append(
                f"[bundle] sha256 mismatch for {rel}: manifest records "
                f"{expected[:12]}…, file is {actual[:12]}…. The file has "
                f"changed since the manifest was written."
            )
    return problems


# ----------------------------
# Bundle IO
# ----------------------------

def _detect_bundle_root(members: Sequence[str]) -> str:
    """
    Determine bundle root prefix. Supports:
      - manifest.json at zip root
      - <folder>/manifest.json
    """
    if "manifest.json" in members:
        return ""
    for pref in ("ScreenA_Bundle/", "screenA_bundle/", "bundle/", "ScreenA/"):
        if pref + "manifest.json" in members:
            return pref
    for m in members:
        if m.endswith("/manifest.json"):
            return m[:-len("manifest.json")]
    return ""


def _read_zip_bytes(zf: zipfile.ZipFile, name: str) -> bytes:
    try:
        return zf.read(name)
    except KeyError:
        raise FileNotFoundError(f"Missing required file in bundle: {name}")


def _find_first_member(zf: zipfile.ZipFile, root: str, rel_candidates: Sequence[str]) -> Tuple[str, str]:
    """
    Returns (member_name_in_zip, rel_path_used)
      - member_name_in_zip includes root prefix
      - rel_path_used is the relative path without root
    """
    nameset = set(zf.namelist())
    for rel in rel_candidates:
        full = root + rel
        if full in nameset:
            return full, rel
    raise FileNotFoundError(f"None of these files were found in bundle: {', '.join(rel_candidates)}")


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

        if not isinstance(manifest, dict):
            raise ValueError("manifest.json must be a JSON object.")

        return BundleInfo(zip_path=zip_path, root=root, manifest=manifest, members=members)

def _export_next_bundle_zip(
    out_zip_path: str,
    bundle: BundleInfo,
    data_rel: str,
    criteria_rel: str,
    input_errors_rel: Optional[str],
    parse_header: List[str],
    full_rows: List[Dict[str, str]],
    survivors: List[Dict[str, str]],
    skipped: List[Tuple[int, str, str]],
    counts: Dict[str, int],
    *,
    stage: str,
    cancelled: bool = False,
    not_screened: bool = False,
) -> None:
    """
    Create a new bundle zip where data/current.csv becomes the {stage} survivors.
    Keeps other files from the input bundle, updates manifest pipeline + sha256 (warn-only downstream).
    Adds reports/{stage}_FULL.csv and reports/{stage}_SURVIVORS.csv.

    ``cancelled`` is stamped onto the history entry (F-02). The UIs refuse to
    call this at all for a cancelled run — refusing export is the primary
    defence, since a manifest field that merely *says* the bundle is partial
    is easy to miss. The stamp is here so that any path which does write one
    anyway leaves a record a downstream reader can find.
    """
    sl = stage.lower()
    root = bundle.root
    src_zip = bundle.zip_path

    manifest_rel = "manifest.json"
    rep_full_rel = f"reports/{stage}_FULL.csv"
    rep_surv_rel = f"reports/{stage}_SURVIVORS.csv"

    # Always write survivors to the canonical location (data/current.csv) for downstream stages
    out_data_rel = "data/current.csv"

    current_bytes = _write_csv_bytes(parse_header, survivors)
    rep_full_bytes = _write_csv_bytes(
        parse_header + [f"{sl}_outcome", f"{sl}_failed_ids", f"{sl}_missing_ids", f"{sl}_met_ids", f"{sl}_reason_summary"],
        full_rows
    )
    rep_surv_bytes = current_bytes

    # F-03: append to whatever the incoming bundle already recorded, and
    # carry the file forward even when this stage dropped nothing. The old
    # code wrote only this stage's rows and only `if skipped`, in a layout
    # the reader could not parse — three separate ways to lose the record of
    # an excluded citation.
    prior_errors_text = ""
    try:
        with zipfile.ZipFile(src_zip, "r") as zf_prior:
            for rel in ("data/input_errors.csv", "input_errors.csv"):
                if root + rel in zf_prior.namelist():
                    prior_errors_text = _decode_bytes(zf_prior.read(root + rel))
                    break
    except Exception:
        prior_errors_text = ""

    # F-71: prior rows pass through verbatim; only this stage's own drops get
    # this stage's stamp. The EH/IH views historically merged the
    # carried-forward rows into the skipped list they pass here, and stamping
    # those with the current stage made one dropped citation grow by one row
    # per hop — with the Harmoniser's observed_len/expected_len present on the
    # original and absent on every copy. Anything identical to a prior row on
    # (record_number, reason, raw) is a carried copy and is subtracted before
    # stamping; a genuine new drop cannot collide, because the indices are
    # into a current.csv that no longer contains the previously dropped rows.
    prior_keys = {(e.record_number, e.reason, e.raw)
                  for e in read_input_errors(prior_errors_text)}
    own_drops = [e for e in from_tuple_skipped(skipped, stage=stage)
                 if (e.record_number, e.reason, e.raw) not in prior_keys]

    # F-75: always written, header-only when nothing was dropped. A file
    # that exists and says "no records were dropped" is a different claim
    # from no file, and only the first one is auditable.
    input_errors_bytes = merge_input_errors_csv(
        prior_errors_text, own_drops).encode("utf-8")

    # Update manifest
    m = dict(bundle.manifest)
    pipeline = dict(m.get("pipeline", {}) or {})
    stages = dict(pipeline.get("stages", {}) or {})
    history = list(pipeline.get("history", []) or [])

    # F-34: "not_screened" is a distinct state from "done". A reviewer
    # reproducing the pipeline must be able to tell that a stage evaluated no
    # criteria without re-running the GUI, and "done" would not tell them.
    if cancelled:
        stages[stage] = "cancelled"
    elif not_screened:
        stages[stage] = "not_screened"
    else:
        stages[stage] = "done"
    history.append({
        "stage": stage,
        "ran_at": _iso_now(),
        "counts": counts,
        "survivors_rows": len(survivors),
        "out_rows_full": len(full_rows),
        "cancelled": bool(cancelled),
        "not_screened": bool(not_screened),
    })
    pipeline["stages"] = stages
    pipeline["history"] = history
    m["pipeline"] = pipeline

    m["created_at"] = datetime.now().replace(microsecond=0).isoformat()
    m["created_by"] = f"screen_a_{sl}_plugin"
    m.setdefault("derived_from", {})
    try:
        m["derived_from"]["zip_name"] = Path(src_zip).name
    except Exception:
        pass

    # Refresh sha256 map (only for files we overwrite/add), through the
    # shared helper so EH/IH and EL/IL share one implementation (F-05).
    written = {
        out_data_rel: current_bytes,
        rep_full_rel: rep_full_bytes,
        rep_surv_rel: rep_surv_bytes,
        "data/input_errors.csv": input_errors_bytes,
    }
    m = _refresh_sha256_map(m, written)

    manifest_bytes = (json.dumps(m, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    # Copy everything except entries we overwrite
    overwrite_set = {
        root + manifest_rel,
        root + out_data_rel,
        root + rep_full_rel,
        root + rep_surv_rel,
        root + "data/input_errors.csv",
    }

    with zipfile.ZipFile(src_zip, "r") as zin, zipfile.ZipFile(out_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            if name in overwrite_set:
                continue
            data = zin.read(name)
            zout.writestr(name, data)

        zout.writestr(root + manifest_rel, manifest_bytes)
        zout.writestr(root + out_data_rel, current_bytes)
        zout.writestr(root + rep_full_rel, rep_full_bytes)
        zout.writestr(root + rep_surv_rel, rep_surv_bytes)
        zout.writestr(root + "data/input_errors.csv", input_errors_bytes)


def _dict_csv_bytes(fieldnames: Sequence[str],
                    rows: Sequence[Dict[str, Any]]) -> bytes:
    """DictWriter to bytes, with None rendered as an empty cell.

    Matches what EL/IL's four inlined copies produced, so the bytes of an
    exported bundle do not move.
    """
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(fieldnames), extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fieldnames})
    return buf.getvalue().encode("utf-8")


def _write_llm_stage_bundle(
    out_zip_path: str,
    zf_in: zipfile.ZipFile,
    *,
    root: str,
    manifest: Dict[str, Any],
    stage: str,
    reports_dir_rel: str,
    cache_rel: str,
    parse_header: Sequence[str],
    survivors: Sequence[Dict[str, Any]],
    full_rows: Sequence[Dict[str, Any]],
    full_header: Sequence[str],
    skipped: Sequence[Dict[str, Any]],
    counts: Optional[Dict[str, int]] = None,
    cache_text: Optional[str] = None,
    extra_members: Optional[Dict[str, bytes]] = None,
    not_screened: bool = False,
    cancelled: bool = False,
    llm_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, bytes]:
    """Write the next-stage bundle for an LLM stage (EL or IL).

    F-05. EL and IL each had two near-identical copies of this — one in
    ui.py, one in standalone.py — and none of the four refreshed the
    manifest's sha256 map. The string ``sha`` appeared zero times in any of
    them, while all four overwrite data/current.csv with the stage's
    survivors, so every bundle leaving EL or IL asserted a digest for a file
    it had just replaced.

    They are one function now, and the digests are refreshed through
    ``_refresh_sha256_map`` — the same helper ``_export_next_bundle_zip``
    uses for EH/IH, so there is one implementation of "the manifest must
    describe what is actually in the zip" rather than five.

    Kept separate from ``_export_next_bundle_zip`` rather than merged into
    it: the LLM stages carry two extra report columns (uncertain_ids,
    evidence_json), write a response cache, and in IL's case a cross-stage
    workbook. Folding them together would have changed EL/IL's report schema
    to EH/IH's, which is a behaviour change the goldens would rightly catch.

    Returns the member map it wrote, keyed by bundle-relative path.
    """
    members = zf_in.namelist()

    # F-03: append to the incoming bundle's record of dropped citations and
    # carry it forward even when this stage skipped nothing.
    prior_errors = ""
    for rel in ("data/input_errors.csv", "input_errors.csv"):
        if root + rel in members:
            prior_errors = _decode_bytes(_read_zip_bytes(zf_in, root + rel))
            break
    merged_errors = merge_input_errors_csv(
        prior_errors, from_dict_skipped(skipped, stage=stage))

    written: Dict[str, bytes] = {
        "data/current.csv": _dict_csv_bytes(parse_header, survivors),
        f"{reports_dir_rel}/{stage}_FULL.csv": _dict_csv_bytes(full_header, full_rows),
        f"{reports_dir_rel}/{stage}_SURVIVORS.csv": _dict_csv_bytes(parse_header, survivors),
    }
    written.update(extra_members or {})
    # F-75: always written, header-only when nothing was dropped — the
    # auditable claim "no records were dropped" needs a file to live in.
    written["data/input_errors.csv"] = merged_errors.encode("utf-8")
    if cache_text is not None:
        written[cache_rel] = cache_text.encode("utf-8")

    # F-34, requirement 4: record the run in pipeline.history, marking a
    # no-op as such. EL/IL wrote no history entry at all before — only a
    # stages[STAGE] = "done" marker — so a reviewer reproducing the pipeline
    # from the bundle had nothing to read. "done" for a stage that evaluated
    # no criteria is the manifest repeating the same false claim the run
    # summary used to make.
    manifest = dict(manifest)
    pipeline = dict(manifest.get("pipeline", {}) or {})
    stages = dict(pipeline.get("stages", {}) or {})
    history = list(pipeline.get("history", []) or [])
    # Wave 8. `cancelled` used to be hard-coded False in the history entry
    # below, and the stage marker knew only "done" and "not_screened" — so a
    # truncated corpus written through this path claimed to be a completed
    # stage. ``_export_next_bundle_zip`` has taken a real `cancelled` since
    # F-02 and marks the stage `cancelled`; this is the same rule for the LLM
    # stages, and the ordering matches: cancellation dominates, because a run
    # that stopped early tells you nothing about what it would have screened.
    if cancelled:
        marker = "cancelled"
    elif not_screened:
        marker = "not_screened"
    else:
        marker = "done"
    stages[stage] = marker

    # A bundle carries two stage maps, `pipeline.stages` and
    # `pipeline_state.stages` (F-27). The EL/IL views set both to "done"
    # before calling this, via their own _set_stage; if this function then
    # corrected only `pipeline.stages`, a zero-criteria run would leave the
    # two maps disagreeing — "not_screened" in one, "done" in the other.
    # That was a regression introduced with F-34 and is fixed here: whatever
    # marker this stage lands on is written to every stage map the manifest
    # actually has. It does not resolve F-27 itself — nothing reconciles maps
    # this function did not write — but it stops this path adding to it.
    if isinstance(manifest.get("pipeline_state"), dict):
        pipeline_state = dict(manifest["pipeline_state"])
        ps_stages = dict(pipeline_state.get("stages", {}) or {})
        ps_stages[stage] = marker
        pipeline_state["stages"] = ps_stages
        manifest["pipeline_state"] = pipeline_state

    entry: Dict[str, Any] = {
        "stage": stage,
        "ran_at": _iso_now(),
        "counts": dict(counts or {}),
        "survivors_rows": len(survivors),
        "out_rows_full": len(full_rows),
        "cancelled": bool(cancelled),
        "not_screened": bool(not_screened),
    }
    # Wave 8, the run-level failure report. Without it, a wholly failed run
    # and a wholly uncertain run are identical in every field this entry
    # records: same counts, same survivor count, not_screened False,
    # cancelled False. `counts` cannot carry it — that is the *outcome*
    # histogram, and a call-failure is not an outcome; it is also asserted by
    # exact dict equality in tests/test_archived_bundle_manifest.py, which is
    # the right constraint for a histogram to have.
    #
    # Omitted entirely when the caller has none, rather than written as
    # zeroes: a stage that did not measure must not claim it measured
    # nothing. EH/IH go through a different writer and never supply one.
    if llm_report:
        report = dict(llm_report)
        # F-88. Provenance travels *inside* the run report — the engine is
        # the only layer that knows the resolved endpoint, and
        # `run_el_screen`'s docstring rules out a ninth tuple position
        # ("a positional append is exactly what silently rebinds an
        # existing unpack"). It is lifted back out here so the manifest
        # reads correctly: `llm` is the counting block — how many records
        # were answered, failed or rejected — and which engine answered is
        # not a count. A reader looking for the model should not have to
        # find it inside a block named after failure counting.
        #
        # Same omission rule as `llm` itself: absent when the stage
        # consulted no model, never zero-filled or inferred.
        provenance = report.pop("provenance", None)
        # F-145, and the same lift for the same reason. A bundle produced
        # under flag-only and one produced with exclusion permitted are
        # different artefacts, and a later reader must be able to tell
        # which is which without re-running the GUI.
        #
        # A **sibling** of `provenance`, not a seventh field inside it —
        # this is a deliberate disagreement with the brief. Wave 10's
        # contract is that a cached entry cannot be served into a run whose
        # provenance differs in any recorded field except `batch_size`.
        # This policy cannot affect a verdict: it acts strictly downstream
        # of one, on what the pipeline DOES with an answer the model has
        # already given. Recording it inside provenance would therefore
        # force one of two wrong things — invalidating 254 perfectly valid
        # cached verdicts every time the policy is toggled, or adding a
        # second unexplained exception to a contract a test pins. As a
        # sibling it states the fact and touches neither.
        policy = report.pop("exclusion_policy", None)
        entry["llm"] = report
        if isinstance(provenance, dict) and provenance:
            entry["provenance"] = dict(provenance)
        if policy in _EXCLUSION_POLICIES:
            entry["exclusion_policy"] = policy
    history.append(entry)
    pipeline["stages"] = stages
    pipeline["history"] = history
    manifest["pipeline"] = pipeline

    # Digests must be computed before the manifest is serialised. The old
    # code wrote manifest.json first and the payloads afterwards, which is
    # what made forgetting the refresh so easy.
    manifest = _refresh_sha256_map(manifest, written)
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

    # A member is skipped by the copy loop only when this export is writing a
    # replacement for it — which is precisely what being in `written` means.
    #
    # F-104: `cache_rel` used to be added here unconditionally, but it only
    # enters `written` when `cache_text is not None`, i.e. when the user
    # ticked "Use cache". Untick the box and the incoming cache member was
    # excluded from the copy loop with nothing written in its place, so one
    # export silently deleted an accumulated cache that cost real money. The
    # manifest kept its digest for the vanished member — `_refresh_sha256_map`
    # only touches members it wrote — and `_verify_sha256_map` iterates the
    # members that are present, so it could not see the absence and reported
    # the bundle intact.
    skip_exact = {root + rel for rel in written}
    skip_exact.add(root + "manifest.json")
    skip_exact.add(root + "data/input_errors.csv")

    with zipfile.ZipFile(out_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf_out:
        for name in members:
            if name.endswith("/") or name in skip_exact:
                continue
            zf_out.writestr(name, _read_zip_bytes(zf_in, name))

        zf_out.writestr(root + "manifest.json", manifest_bytes)
        for rel, body in written.items():
            zf_out.writestr(root + rel, body)

    return written
