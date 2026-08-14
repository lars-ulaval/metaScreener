# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
rekey_cache_goldens.py — F-89: re-key the EL/IL cache goldens offline.

A RE-KEY, NOT A RE-CAPTURE. The stored keys change; the stored values do
not. No API call is made and no decision is recomputed. Values are copied
byte for byte; only their labels change.

Why this file exists at all
---------------------------
Wave 2 did the same job for F-01 in commit ``c8d2fb3`` and **the script was
never committed** — ``git show --stat c8d2fb3`` is three files, none of
them a migration tool, so the proof survives only as prose in a commit
message. §B4.6 of ``06_llm_integration.md`` names that as the mistake to
avoid the second time:

    "If an endpoint re-key is done, the migration script (or a test that
    regenerates and re-verifies the mapping) should be **committed this
    time** — otherwise the next wave inherits the same 'the message says
    it was proved' situation."

So this is committed, and ``tests/test_golden_rekey.py`` runs its
verification on every suite run. A future wave can re-derive the mapping
rather than take it on trust.

Method
------
For every (criterion, record) pair the stage engine would enumerate over
the committed golden corpora, derive **both** keys:

* the OLD key — a four-member object ``{prompt_version, model,
  temperature, prompt}``, reimplemented below from ``c5e2100^``;
* the NEW key — the current five-member object, via the live stage curry.

Then move each committed entry from the first label to the second.

The reimplementation of the old formula is self-validating: if it were
wrong, the derived old keys would not match the committed golden keys, and
obligation 1 (170/170, 84/84, zero orphans) would fail. Matching all of
them is the evidence that the enumeration and the formula are both right.
That is wave 2's method, reused deliberately.

The endpoint the goldens are re-keyed to
----------------------------------------
``DEFAULT_OPENAI_BASE_URL`` — the public API. The captures were taken with
a live ``OPENAI_API_KEY`` against ``gpt-4o-mini``, a model only OpenAI
serves, at a time when **no repository code read ``OPENAI_BASE_URL`` at
all**, so the SDK resolved its own default.

That is an inference, not a record — F-128 is the standing finding that
the goldens' capture-time provenance was never written down, and it cannot
be added retroactively. It does not have to be taken on faith here: the
byte-identity regression tests replay the re-keyed cache at the default
endpoint and must reproduce the committed report CSVs exactly. If the
endpoint chosen here were wrong, every lookup would miss and both tests
would fail loudly. Their passing is the verification.

The five obligations
--------------------
From ``c8d2fb3``, and the standard this wave is held to. The re-key
REFUSES TO WRITE unless all five hold, for both stages:

  1. entry count preserved, mapping 1:1
  2. no collisions, no orphans
  3. values byte-identical as multisets
  4. new key set disjoint from the old
  5. ``_invocation`` preserved

Usage::

    python tools/rekey_cache_goldens.py --verify   # prove, write nothing
    python tools/rekey_cache_goldens.py            # prove, then write
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = PROJECT_ROOT / "tests" / "golden"

CRITERIA_CSV = GOLDEN_DIR / "criteria_harmonized_v3.1.0.csv"

STAGES = {
    "EL": {
        "subdir": "06_el",
        "input": GOLDEN_DIR / "el_input_v3.1.0.csv",
        "cache": GOLDEN_DIR / "el_cache_v3.1.0.json",
    },
    "IL": {
        "subdir": "07_il",
        "input": GOLDEN_DIR / "il_input_v3.1.0.csv",
        "cache": GOLDEN_DIR / "il_cache_v3.1.0.json",
    },
}


# --------------------------------------------------------------------------
# Headless plugin loading (mirrors tools/capture_el_il_goldens.py)
# --------------------------------------------------------------------------
def _setup_headless_imports() -> None:
    import types
    for name in ("tkinter", "tkinter.ttk", "tkinter.filedialog",
                 "tkinter.messagebox", "tkinter.scrolledtext",
                 "tkinter.font", "_tkinter"):
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
# The OLD key formula, reimplemented from c5e2100^
# --------------------------------------------------------------------------
def _old_cache_key(*, prompt_version: str, model: str, rendered_prompt: str,
                   temperature: float = 0.0) -> str:
    """``plugins/_common/llm_client.py::_cache_key`` as it stood before F-89.

    Four members, no endpoint. Reproduced here rather than imported
    because the live function no longer computes it — recovering it from
    git history is what makes the mapping reproducible by anyone.

    Kept byte-identical to the original: same key names, same
    ``ensure_ascii=False, sort_keys=True, separators=(",", ":")``, same
    ``float()`` coercion of the temperature.
    """
    base = json.dumps(
        {
            "prompt_version": str(prompt_version),
            "model": str(model),
            "temperature": float(temperature),
            "prompt": rendered_prompt,
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return sha256(base.encode("utf-8", errors="ignore")).hexdigest()


# --------------------------------------------------------------------------
# The wave-14c migration: prompt_version v1 -> v2, same five-member formula
# --------------------------------------------------------------------------
#: The version strings as they stood before wave 14c bumped them for the
#: constrained request (F-191/F-197). The FORMULA did not change this time —
#: only this input to it — so the "old key" for this migration is the live
#: shared ``_cache_key`` with these strings, not a reimplementation.
V1_PROMPT_VERSIONS = {"EL": "EL_v1_jsonlist", "IL": "IL_v1_jsonlist"}


# --------------------------------------------------------------------------
# Pair enumeration — must match run_{el,il}_screen exactly
# --------------------------------------------------------------------------
def _enumerate_pairs(mod, stage: str, input_csv: Path, trunc_chars: int):
    """Yield ``(crit_pack, item)`` in the order the stage engine builds them.

    Mirrors ``run_el_screen`` / ``run_il_screen``: the header-cased item
    build, the duplicated-``local_id`` exclusion, and the per-criterion
    ``crit_pack`` assembly. Any divergence here shows up immediately as an
    old-key mismatch against the committed golden.
    """
    corpus_text = input_csv.read_text(encoding="utf-8-sig")
    criteria_text = CRITERIA_CSV.read_text(encoding="utf-8-sig")

    header, rows = mod._csv_read(corpus_text)
    criteria_report = mod._parse_criteria_harmonized_csv(criteria_text, stage)
    crits = [c for c in criteria_report.criteria if c.enabled]

    header_map = {h.lower(): h for h in (header or [])}

    def getv(row: Dict[str, str], key: str) -> str:
        k = header_map.get(key.lower(), key)
        return mod._safe_str(row.get(k, ""))

    items = [{
        "a_id": getv(r, "local_id").strip(),
        "title": getv(r, "title"),
        "abstract": getv(r, "abstract"),
        "keywords": getv(r, "keywords"),
    } for r in rows]

    # Duplicate local_ids are dropped before keying, exactly as the engine
    # does — a verdict cannot be attributed to a single record.
    seen, ambiguous = set(), set()
    for it in items:
        lid = mod._safe_str(it.get("a_id", "")).strip()
        if not lid:
            continue
        if lid in seen:
            ambiguous.add(lid)
        seen.add(lid)
    if ambiguous:
        items = [it for it in items
                 if mod._safe_str(it.get("a_id", "")).strip() not in ambiguous]

    for c in crits:
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
        for it in items:
            if not mod._safe_str(it.get("a_id", "")).strip():
                continue
            yield crit_pack, it


# --------------------------------------------------------------------------
# The re-key
# --------------------------------------------------------------------------
@dataclass
class RekeyReport:
    stage: str
    entries_before: int
    entries_after: int
    pairs_derived: int
    old_keys_matched: int
    orphans: List[str] = field(default_factory=list)
    collisions: List[str] = field(default_factory=list)
    values_multiset_equal: bool = False
    key_sets_disjoint: bool = False
    invocation_preserved: bool = False
    invocation: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return (
            self.entries_before == self.entries_after
            and self.old_keys_matched == self.entries_before
            and not self.orphans
            and not self.collisions
            and self.values_multiset_equal
            and self.key_sets_disjoint
            and self.invocation_preserved
        )

    def lines(self) -> List[str]:
        tick = lambda b: "OK  " if b else "FAIL"  # noqa: E731
        return [
            f"[{self.stage}] entries {self.entries_before} -> "
            f"{self.entries_after}, pairs derived {self.pairs_derived}",
            f"  {tick(self.old_keys_matched == self.entries_before)} "
            f"1. count preserved, mapping 1:1 "
            f"({self.old_keys_matched}/{self.entries_before} old keys matched)",
            f"  {tick(not self.orphans and not self.collisions)} "
            f"2. {len(self.collisions)} collisions, {len(self.orphans)} orphans",
            f"  {tick(self.values_multiset_equal)} "
            f"3. values byte-identical as multisets",
            f"  {tick(self.key_sets_disjoint)} "
            f"4. new key set disjoint from the old",
            f"  {tick(self.invocation_preserved)} "
            f"5. _invocation preserved: {self.invocation}",
        ]


def _serialise(envelope: Dict[str, Any]) -> bytes:
    """Reproduce the committed goldens' bytes exactly.

    ``tools/capture_el_il_goldens.py`` writes
    ``json.dumps(ensure_ascii=False, sort_keys=True, indent=2)`` through
    ``Path.write_text(encoding="utf-8")`` on Windows, which translates
    ``\\n`` to ``\\r\\n`` and appends no trailing newline. Doing the CRLF
    conversion explicitly here makes the output platform-independent
    instead of depending on where the script is run — and
    ``tests/golden/** binary`` in ``.gitattributes`` is what keeps git from
    rewriting it afterwards.
    """
    text = json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2)
    return text.replace("\n", "\r\n").encode("utf-8")


def rekey_stage(stage: str, endpoint: str) -> Tuple[RekeyReport, bytes]:
    """Derive the mapping for one stage and return its report and new bytes.

    Writes nothing. The caller decides, and only when ``report.ok``.
    """
    cfg = STAGES[stage]
    mod = _import_plugin(cfg["subdir"])

    raw = json.loads(cfg["cache"].read_text(encoding="utf-8"))
    invocation = raw["_invocation"]
    old_cache: Dict[str, Dict[str, Any]] = raw["cache"]

    model = invocation["model"]
    trunc_chars = invocation["trunc_chars"]
    temperature = 0.0  # the capture tool does not pass one; the default is 0.0

    # From the shared module rather than the stage shim: plugin.py re-exports
    # the stage's own names, and this serialiser is not one of them.
    from plugins._common.llm_client import _render_prompt_for_key

    mapping: Dict[str, str] = {}
    pairs = 0
    for crit_pack, item in _enumerate_pairs(mod, stage, cfg["input"], trunc_chars):
        pairs += 1
        rendered = _render_prompt_for_key(
            mod._build_llm_messages_for_criterion(crit_pack, [item], trunc_chars)
        )
        old = _old_cache_key(
            prompt_version=mod.PROMPT_VERSION, model=model,
            rendered_prompt=rendered, temperature=temperature,
        )
        if old not in old_cache:
            continue          # a pair with no committed entry: nothing to move
        new = mod._cache_key(
            model=model, criterion=crit_pack, item=item,
            trunc_chars=trunc_chars, endpoint=endpoint, temperature=temperature,
        )
        mapping[old] = new

    new_cache: Dict[str, Dict[str, Any]] = {}
    collisions: List[str] = []
    for old_key, value in old_cache.items():
        new_key = mapping.get(old_key)
        if new_key is None:
            continue          # orphan; counted below
        if new_key in new_cache:
            collisions.append(new_key)
        new_cache[new_key] = value

    orphans = [k for k in old_cache if k not in mapping]

    # Obligation 3: the VALUES must survive untouched. Compared as
    # multisets, not as sets, so a value duplicated in the source has to be
    # duplicated in the result too.
    def _multiset(values) -> Counter:
        return Counter(
            json.dumps(v, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"))
            for v in values
        )

    envelope = {"_invocation": invocation, "cache": new_cache}

    report = RekeyReport(
        stage=stage,
        entries_before=len(old_cache),
        entries_after=len(new_cache),
        pairs_derived=pairs,
        old_keys_matched=len(mapping),
        orphans=orphans,
        collisions=collisions,
        values_multiset_equal=_multiset(old_cache.values()) == _multiset(new_cache.values()),
        key_sets_disjoint=not (set(old_cache) & set(new_cache)),
        invocation_preserved=envelope["_invocation"] == raw["_invocation"],
        invocation=dict(invocation),
    )
    return report, _serialise(envelope)


def rekey_stage_prompt_version(stage: str, endpoint: str) -> Tuple[RekeyReport, bytes]:
    """The wave-14c migration: relabel every entry from the v1
    ``prompt_version`` to the live one. Same mechanism as
    :func:`rekey_stage` — same enumeration, same five obligations, same
    refuse-unless-all-hold — with one difference: the old key uses the SAME
    five-member formula as the new, with only ``prompt_version`` differing.

    Self-validating the same way: if the v1 derivation were wrong, the old
    keys would not match the committed golden and obligation 1 would fail.
    """
    cfg = STAGES[stage]
    mod = _import_plugin(cfg["subdir"])

    raw = json.loads(cfg["cache"].read_text(encoding="utf-8"))
    invocation = raw["_invocation"]
    old_cache: Dict[str, Dict[str, Any]] = raw["cache"]

    model = invocation["model"]
    trunc_chars = invocation["trunc_chars"]
    temperature = 0.0

    from plugins._common.llm_client import (
        _cache_key as _shared_cache_key,
        _render_prompt_for_key,
    )

    mapping: Dict[str, str] = {}
    pairs = 0
    for crit_pack, item in _enumerate_pairs(mod, stage, cfg["input"], trunc_chars):
        pairs += 1
        rendered = _render_prompt_for_key(
            mod._build_llm_messages_for_criterion(crit_pack, [item], trunc_chars)
        )
        old = _shared_cache_key(
            prompt_version=V1_PROMPT_VERSIONS[stage], model=model,
            rendered_prompt=rendered, endpoint=endpoint,
            temperature=temperature,
        )
        if old not in old_cache:
            continue
        new = mod._cache_key(
            model=model, criterion=crit_pack, item=item,
            trunc_chars=trunc_chars, endpoint=endpoint, temperature=temperature,
        )
        mapping[old] = new

    new_cache: Dict[str, Dict[str, Any]] = {}
    collisions: List[str] = []
    for old_key, value in old_cache.items():
        new_key = mapping.get(old_key)
        if new_key is None:
            continue
        if new_key in new_cache:
            collisions.append(new_key)
        new_cache[new_key] = value

    orphans = [k for k in old_cache if k not in mapping]

    def _multiset(values) -> Counter:
        return Counter(
            json.dumps(v, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"))
            for v in values
        )

    envelope = {"_invocation": invocation, "cache": new_cache}

    report = RekeyReport(
        stage=stage,
        entries_before=len(old_cache),
        entries_after=len(new_cache),
        pairs_derived=pairs,
        old_keys_matched=len(mapping),
        orphans=orphans,
        collisions=collisions,
        values_multiset_equal=_multiset(old_cache.values()) == _multiset(new_cache.values()),
        key_sets_disjoint=not (set(old_cache) & set(new_cache)),
        invocation_preserved=envelope["_invocation"] == raw["_invocation"],
        invocation=dict(invocation),
    )
    return report, _serialise(envelope)


# --------------------------------------------------------------------------
# Re-verification of an ALREADY migrated golden
# --------------------------------------------------------------------------
#
# The migration is not idempotent: once the file on disk is re-keyed, its
# keys are the new ones, so re-deriving the mapping from it would find
# nothing to move. A proof that can only be run before it is applied is
# wave 2's situation again — true once, unrepeatable afterwards.
#
# So the standing check is on the POST-conditions instead, and it needs no
# git history: derive every pair's key both ways from the committed
# corpora, and require that the new keys are exactly the committed golden's
# keys and the old keys are entirely absent from it. That is obligations
# 1, 2 and 4 restated over the migrated artefact.
#
# Obligation 3 is the one that cannot be recomputed from the migrated file
# alone, because the values it must be compared against lived in the
# pre-migration file. It is pinned instead: the SHA-256 over the sorted
# multiset of serialised values, measured on the goldens as they stood at
# c5e2100, before a byte was written. A re-key does not touch values, so
# this digest must survive the migration and every migration after it.
VALUE_MULTISET_SHA256 = {
    "EL": "8d590115d4c24689c83a8e614e3b2fdfd7391bc4b61b2460f93d0226259dde8a",
    "IL": "a084f527a8bb82c95bcd64df5aca838c7424f4c9b7306b114e8340806eba0e32",
}


@dataclass
class VerifyReport:
    stage: str
    entries: int
    new_keys_present: int
    old_keys_present: int
    pairs_derived: int
    value_multiset_sha256: str = ""
    invocation: Dict[str, Any] = field(default_factory=dict)
    #: Wave 14c: committed keys reproduced by the five-member formula with
    #: the pre-bump v1 prompt_version. Must be 0 after the v1->v2 re-key,
    #: for the same reason old_keys_present must be 0 after F-89's.
    v1_keys_present: int = 0

    @property
    def values_unchanged(self) -> bool:
        return self.value_multiset_sha256 == VALUE_MULTISET_SHA256[self.stage]

    @property
    def ok(self) -> bool:
        return (
            self.new_keys_present == self.entries
            and self.old_keys_present == 0
            and self.v1_keys_present == 0
            and self.values_unchanged
        )

    def lines(self) -> List[str]:
        tick = lambda b: "OK  " if b else "FAIL"  # noqa: E731
        return [
            f"[{self.stage}] {self.entries} committed entries, "
            f"{self.pairs_derived} pairs derived",
            f"  {tick(self.new_keys_present == self.entries)} "
            f"every committed key is reproduced by the CURRENT key function "
            f"({self.new_keys_present}/{self.entries})",
            f"  {tick(self.old_keys_present == 0)} "
            f"no committed key is reproduced by the PRE-F-89 key function "
            f"({self.old_keys_present} found; the two key sets are disjoint)",
            f"  {tick(self.v1_keys_present == 0)} "
            f"no committed key is reproduced with the v1 prompt_version "
            f"({self.v1_keys_present} found; wave 14c's re-key is complete)",
            f"  {tick(self.values_unchanged)} "
            f"values unchanged since c5e2100 "
            f"(sha256 {self.value_multiset_sha256[:16]}...)",
            f"  ---- _invocation: {self.invocation}",
        ]


def verify_stage(stage: str, endpoint: str) -> VerifyReport:
    """Check a migrated golden against the current and the pre-F-89 formulas.

    Re-runnable indefinitely, and the thing ``tests/test_golden_rekey.py``
    executes on every suite run.
    """
    cfg = STAGES[stage]
    mod = _import_plugin(cfg["subdir"])
    from plugins._common.llm_client import (
        _cache_key as _shared_cache_key,
        _render_prompt_for_key,
    )

    raw = json.loads(cfg["cache"].read_text(encoding="utf-8"))
    invocation = raw["_invocation"]
    committed: Dict[str, Dict[str, Any]] = raw["cache"]

    model = invocation["model"]
    trunc_chars = invocation["trunc_chars"]
    temperature = 0.0

    new_hits: set = set()
    old_hits: set = set()
    v1_hits: set = set()
    pairs = 0
    for crit_pack, item in _enumerate_pairs(mod, stage, cfg["input"], trunc_chars):
        pairs += 1
        rendered = _render_prompt_for_key(
            mod._build_llm_messages_for_criterion(crit_pack, [item], trunc_chars)
        )
        new = mod._cache_key(
            model=model, criterion=crit_pack, item=item,
            trunc_chars=trunc_chars, endpoint=endpoint, temperature=temperature,
        )
        if new in committed:
            new_hits.add(new)
        old = _old_cache_key(
            prompt_version=mod.PROMPT_VERSION, model=model,
            rendered_prompt=rendered, temperature=temperature,
        )
        if old in committed:
            old_hits.add(old)
        v1 = _shared_cache_key(
            prompt_version=V1_PROMPT_VERSIONS[stage], model=model,
            rendered_prompt=rendered, endpoint=endpoint,
            temperature=temperature,
        )
        if v1 in committed:
            v1_hits.add(v1)

    values = sorted(
        json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for v in committed.values()
    )
    digest = sha256("\n".join(values).encode("utf-8")).hexdigest()

    return VerifyReport(
        stage=stage,
        entries=len(committed),
        new_keys_present=len(new_hits),
        old_keys_present=len(old_hits),
        v1_keys_present=len(v1_hits),
        pairs_derived=pairs,
        value_multiset_sha256=digest,
        invocation=dict(invocation),
    )


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify", action="store_true",
                    help="re-verify the ALREADY migrated goldens; write nothing")
    ap.add_argument("--migrate", action="store_true",
                    help="derive the mapping from PRE-F-89 goldens and write "
                         "them. Run once; see the module docstring.")
    ap.add_argument("--migration", choices=("endpoint", "prompt-version"),
                    default="endpoint",
                    help="which migration --migrate performs: 'endpoint' is "
                         "F-89's (pre-F-89 four-member key -> five-member); "
                         "'prompt-version' is wave 14c's (v1 prompt_version "
                         "-> the live one, same formula).")
    args = ap.parse_args(argv)

    _setup_headless_imports()
    from plugins._common.llm_client import DEFAULT_OPENAI_BASE_URL

    if not args.migrate:
        print(f"Verifying goldens against endpoint "
              f"{DEFAULT_OPENAI_BASE_URL!r}\n")
        reports = [verify_stage(s, DEFAULT_OPENAI_BASE_URL) for s in STAGES]
        for r in reports:
            print("\n".join(r.lines()))
            print()
        ok = all(r.ok for r in reports)
        print("Goldens are keyed as this code keys them."
              if ok else "VERIFICATION FAILED.")
        return 0 if ok else 1

    migrate_fn = (rekey_stage_prompt_version
                  if args.migration == "prompt-version" else rekey_stage)
    print(f"Re-keying ({args.migration}) to endpoint "
          f"{DEFAULT_OPENAI_BASE_URL!r}\n")
    results = []
    for stage in STAGES:
        report, payload = migrate_fn(stage, DEFAULT_OPENAI_BASE_URL)
        print("\n".join(report.lines()))
        print()
        results.append((stage, report, payload))

    if not all(r.ok for _, r, _ in results):
        print("REFUSING TO WRITE: the mapping is not a pure relabelling.")
        return 1

    for stage, _report, payload in results:
        path = STAGES[stage]["cache"]
        before = path.stat().st_size
        path.write_bytes(payload)
        print(f"[{stage}] wrote {path.name} ({before} -> {len(payload)} B)")

    print("\nAll five obligations held for both stages; goldens re-keyed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
