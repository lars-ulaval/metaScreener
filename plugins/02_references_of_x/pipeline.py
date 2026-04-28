# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
pipeline.py — headless CLI pipeline for "References-of-X — AI v1"

Orchestrates the end-to-end flow without the Tk UI:
1) Ingest X (from text or CSV/XLSX)
2) Resolve/enrich metadata (Crossref/OpenAlex/Semantic Scholar)
3) Fetch references for each X[i]
4) Aggregate & deduplicate → vector A
5) Export CSVs

Usage (examples)
----------------
# From pasted text in a .txt file → export A.csv
python pipeline.py --text input.txt --out A.csv

# From a CSV of X → export A.csv and also export cleaned X and per-X refs
python pipeline.py --input studies.csv --out A.csv --export-x X_clean.csv --export-refs-dir refs_by_x/

# Read text from stdin
cat citations.txt | python pipeline.py --text - --out A.csv

# Export the resolver audit/provenance CSV after metadata resolution
python pipeline.py --input studies.csv --no-refs --no-aggregate --export-meta-sources meta_sources.csv
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Dict, List, Optional

from .services import Ingestor, MetaResolver, RefFetcher, Exporter, dedup_items
from .core import BibItem, CancellationToken

# --------------------------------------------------------------------------------------
# Console logger + progress
# --------------------------------------------------------------------------------------

class ConsoleLogger:
    def __init__(self, quiet: bool = False):
        self.quiet = quiet

    def log(self, msg: str) -> None:
        if not self.quiet:
            ts = time.strftime("%H:%M:%S")
            print(f"[{ts}] {msg}", flush=True)


class ConsoleProgress:
    """
    Formats the lightweight progress payloads emitted by services.py into
    human-friendly single-line console updates. Silent if verbose=False.
    """
    def __init__(self, logger: ConsoleLogger, verbose: bool = True):
        self.logger = logger
        self.verbose = verbose

    def __call__(self, p: Dict) -> None:
        if not self.verbose:
            return
        phase = p.get("phase")
        event = p.get("event")
        if phase == "resolve":
            if event == "start":
                self.logger.log(f"Resolve ▶ {p.get('id','')}")
            elif event == "done":
                hits = p.get("hits", {})
                self.logger.log(
                    f"Resolve ✅ {p.get('id','')}  (hits: OA:{int(hits.get('oa',0))} CR:{int(hits.get('cr',0))} S2:{int(hits.get('s2',0))})"
                )
        elif phase == "fetch":
            parent = p.get("parent", "")
            if event == "start":
                self.logger.log(f"Fetch ▶ {parent}")
            elif event == "hydrated_chunk":
                self.logger.log(
                    f"Fetch ⧉ {parent}  +{p.get('count',0)} (OA)  total:{p.get('refs_found',0)}"
                )
            elif event == "fallback_added":
                self.logger.log(
                    f"Fetch ↩ {parent}  +{p.get('count',0)} ({p.get('source','?')})  total:{p.get('refs_found',0)}"
                )
            elif event == "resolved_refs_progress":
                self.logger.log(
                    f"Fetch ✓ {parent}  resolved {p.get('resolved',0)}/{p.get('total',0)} fetched refs"
                )
            elif event == "skip_no_doi":
                self.logger.log(f"Fetch ⏭ {parent} (no DOI)")
            elif event == "done":
                self.logger.log(f"Fetch ✅ {parent}  total:{p.get('refs_found',0)}")


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def _read_text_source(path_or_dash: str) -> str:
    if path_or_dash == "-":
        return sys.stdin.read()
    with open(path_or_dash, "r", encoding="utf-8") as f:
        return f.read()


def _ensure_dir(p: Optional[str]) -> None:
    if p:
        os.makedirs(p, exist_ok=True)


def _export_refs_dir(refs_by_x: Dict[str, List[BibItem]], outdir: str, logger: ConsoleLogger) -> None:
    _ensure_dir(outdir)
    exp = Exporter(logger)
    for x_id, rows in refs_by_x.items():
        if not rows:
            continue
        fname = os.path.join(outdir, f"{x_id}_refs.csv")
        exp.to_csv(fname, rows)


def _post_resolve_summary(rows: List[BibItem], logger: ConsoleLogger) -> None:
    """Aggregate and print a compact audit after metadata resolution."""
    n = len(rows)
    if n == 0:
        logger.log("No items to summarize after resolve.")
        return

    def count(pred) -> int:
        return sum(1 for r in rows if pred(r))

    hit_oa = count(lambda r: bool(getattr(r, "hit_openalex", False)))
    hit_cr = count(lambda r: bool(getattr(r, "hit_crossref", False)))
    hit_s2 = count(lambda r: bool(getattr(r, "hit_semanticscholar", False)))

    miss_lang = count(lambda r: not (getattr(r, "lang", "") or ""))
    miss_abs  = count(lambda r: not (getattr(r, "abstract", "") or ""))
    miss_kw   = count(lambda r: not (getattr(r, "keywords", "") or ""))

    # winner_source counts
    win_counts: Dict[str, int] = {}
    for r in rows:
        w = (getattr(r, "winner_source", "") or "").strip().lower() or "-"
        win_counts[w] = win_counts.get(w, 0) + 1

    # field-level contribution totals
    contrib_totals = {"openalex": 0, "crossref": 0, "semanticscholar": 0}
    for r in rows:
        c = getattr(r, "filled_by_source_counts", {}) or {}
        for k in contrib_totals.keys():
            contrib_totals[k] += int(c.get(k, 0))

    # print summary
    logger.log("── Resolver summary ───────────────────────────────────────────")
    logger.log(f"Items: {n}")
    logger.log(f"Connectivity hits → OpenAlex:{hit_oa}/{n}  Crossref:{hit_cr}/{n}  S2:{hit_s2}/{n}")
    logger.log(f"Still missing → lang:{miss_lang}  abstract:{miss_abs}  keywords:{miss_kw}")
    logger.log("Winner source counts:")
    for src, cnt in sorted(win_counts.items(), key=lambda t: (-t[1], t[0])):
        logger.log(f"  {src}: {cnt}")
    logger.log("Field contributions filled (total fields set by each source):")
    logger.log(f"  OpenAlex: {contrib_totals['openalex']}  Crossref: {contrib_totals['crossref']}  S2: {contrib_totals['semanticscholar']}")
    logger.log("───────────────────────────────────────────────────────────────")


# --------------------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------------------

def run_pipeline(
    input_path: Optional[str],
    text_path: Optional[str],
    out_csv: Optional[str],
    export_x: Optional[str],
    export_refs_dir: Optional[str],
    cache_dir: str,
    do_resolve: bool,
    do_refs: bool,
    do_aggregate: bool,
    limit: Optional[int],
    quiet: bool,
    export_meta_sources: Optional[str],   # NEW
    progress_verbose: bool = True,        # NEW: control progress chatter
) -> int:
    logger = ConsoleLogger(quiet=quiet)
    progress = ConsoleProgress(logger, verbose=(progress_verbose and not quiet))

    # 1) Ingest X
    logger.log("Step 1/5 — Ingest X")
    ing = Ingestor(logger)
    if input_path and text_path:
        logger.log("ERROR: Use either --input or --text, not both.")
        return 2
    if not input_path and not text_path:
        logger.log("ERROR: Provide --input CSV/XLSX or --text TXT/- (stdin).")
        return 2

    if text_path:
        src = _read_text_source(text_path)
        results_X = ing.from_text(src, source_label="pasted_text" if text_path != "-" else "stdin")
    else:
        results_X = ing.from_csv_or_xlsx(input_path)

    if limit and limit > 0:
        results_X = results_X[:limit]
        logger.log(f"Limiting to first {limit} X items")

    # Optional: export cleaned X
    if export_x:
        Exporter(logger).to_csv(export_x, results_X)

    # 2) Resolve/enrich metadata
    if do_resolve:
        logger.log("Step 2/5 — Resolve & enrich metadata")
        resolver = MetaResolver(logger=logger, cache_dir=os.path.join(cache_dir, "meta"))
        cancel = CancellationToken()
        enriched: List[BibItem] = []
        for i, bi in enumerate(results_X, 1):
            if cancel.cancelled:
                break
            bi.local_id = f"X{i:03d}"  # stable indexing
            enriched.append(resolver.resolve_item(bi, cancel, progress=progress))
            if i % 10 == 0:
                logger.log(f"Resolved {i}/{len(results_X)}")
        results_X = enriched

        # Optional audit/provenance export right after resolve
        if export_meta_sources:
            logger.log("Exporting metadata sources audit CSV…")
            Exporter(logger).to_meta_sources_csv(export_meta_sources, results_X)

        # Summary after resolve
        _post_resolve_summary(results_X, logger)
    else:
        logger.log("Step 2/5 — Resolve skipped")

    # 3) Fetch references per X
    refs_by_x: Dict[str, List[BibItem]] = {}
    if do_refs:
        logger.log("Step 3/5 — Fetch references (OpenAlex → Crossref → S2)")
        fetcher = RefFetcher(logger=logger, cache_dir=os.path.join(cache_dir, "refs"))
        cancel = CancellationToken()
        for bi in results_X:
            if cancel.cancelled:
                break
            rows = fetcher.fetch_for_item(bi, cancel, progress=progress)
            # Reindex child local_ids sequentially per X
            for idx, r in enumerate(rows, 1):
                r.local_id = f"{bi.local_id}.R{idx:03d}"
            refs_by_x[bi.local_id] = rows
            logger.log(f"{bi.local_id}: {len(rows)} reference(s)")
        # Optional export of per-X refs
        if export_refs_dir:
            _export_refs_dir(refs_by_x, export_refs_dir, logger)
    else:
        logger.log("Step 3/5 — Fetch references skipped")

    # 4) Aggregate & deduplicate → A
    vector_A: List[BibItem] = []
    if do_aggregate:
        logger.log("Step 4/5 — Aggregate & deduplicate → vector A")
        # Flatten
        all_refs: List[BibItem] = []
        for rows in refs_by_x.values():
            all_refs.extend(rows)
        if not all_refs:
            logger.log("No references to aggregate (A will be empty).")
        else:
            vector_A, _parents = dedup_items(all_refs)
            logger.log(f"Vector A size: {len(vector_A)}")
    else:
        logger.log("Step 4/5 — Aggregate skipped")

    # 5) Export
    logger.log("Step 5/5 — Export")
    if out_csv:
        rows_to_save = vector_A if vector_A else (results_X if results_X else [])
        if not rows_to_save:
            logger.log("Nothing to export.")
        else:
            Exporter(logger).to_csv(out_csv, rows_to_save)
    else:
        logger.log("No --out provided; skipping A export.")

    logger.log("Done.")
    return 0


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Headless pipeline for References-of-X — AI v1")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="Path to CSV/XLSX of X (columns like title, authors, year, doi)")
    src.add_argument("--text", help="Path to TXT with pasted citations, or '-' to read from stdin")

    p.add_argument("--out", dest="out_csv", help="Path to export CSV (A by default, else X if A empty)")
    p.add_argument("--export-x", help="Optional: export cleaned/normalized X to this CSV path")
    p.add_argument("--export-refs-dir", help="Optional: export per-X references as CSV files into this directory")
    p.add_argument("--export-meta-sources", help="Optional: export resolver audit/provenance CSV right after Step 2")

    p.add_argument("--cache-dir", default=os.path.join(os.path.expanduser("~"), ".refx_cache"),
                   help="Cache directory (default: ~/.refx_cache)")

    # Toggles
    p.add_argument("--no-resolve", action="store_true", help="Skip metadata resolution")
    p.add_argument("--no-refs", action="store_true", help="Skip fetching references")
    p.add_argument("--no-aggregate", action="store_true", help="Skip aggregation/dedup (A)")

    p.add_argument("--limit", type=int, help="Optional: only process first N X items")
    p.add_argument("--quiet", action="store_true", help="Less verbose logging")
    p.add_argument("--no-progress", action="store_true", help="Disable fine-grained progress lines")  # NEW

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_argparser().parse_args(argv)

    try:
        code = run_pipeline(
            input_path=args.input,
            text_path=args.text,
            out_csv=args.out_csv,
            export_x=args.export_x,
            export_refs_dir=args.export_refs_dir,
            cache_dir=args.cache_dir,
            do_resolve=not args.no_resolve,
            do_refs=not args.no_refs,
            do_aggregate=not args.no_aggregate,
            limit=args.limit,
            quiet=args.quiet,
            export_meta_sources=args.export_meta_sources,
            progress_verbose=not args.no_progress,  # NEW
        )
        return code
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
