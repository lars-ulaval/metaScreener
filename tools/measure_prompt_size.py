# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
measure_prompt_size.py — how large is an EL/IL prompt, against a context window?

Wave 12, F-154. metaScreener never sets ``num_ctx``, so every local run
inherits whatever context window the server defaults to — 4096 on the
maintainer's Ollama, per its own log line ``vram-based default context
… default_num_ctx=4096``. An OpenAI-compatible server does not error
when a prompt exceeds its window; it truncates. So the prompt the
application believes it sent and the prompt the model actually saw can
differ, silently, with no log line and no manifest note.

This tool exists so the figures published in
``docs/llm-evaluation.md`` can be re-derived rather than taken on trust.
Wave 10 published a figure supplied from memory that was wrong by a
factor that would have claimed 99.6% where the measured value was 72%;
a number nobody can re-compute is how that happens.

**Read-only.** It renders prompts through the real builder and measures
them. It calls no model, opens no network connection, and writes
nothing.

Usage::

    python tools/measure_prompt_size.py                 # goldens, batches 1/5/10/50
    python tools/measure_prompt_size.py --window 8192
    python tools/measure_prompt_size.py --batches 5

On the estimator
----------------
No tokenizer ships with this project's dependencies (``tiktoken``,
``transformers`` and ``sentencepiece`` are all absent from a default
install), so this reports a **range** rather than a number: 4.5
characters per token as the optimistic bound and 3.0 as the pessimistic
one. Those are the conventional bounds for byte-level BPE over English
prose. JSON-structured text sits toward the pessimistic end, because
field names and punctuation fragment into more tokens per character than
prose does.

**Calibrated at wave 15b against the server's own count, and the paragraph
above is corrected by the measurement.** ``usage.prompt_tokens`` for eight
prompts rendered by the real builder over the frozen 147-record corpus
measured 4.48–4.50 chars/token on batch-1/5 payloads and **4.88–5.23 on
batch-10 payloads** — this JSON-heavy payload sits at or BEYOND the
"optimistic" 4.5 bound, not toward the pessimistic end. The 3.0 bound
over-counts by ~65 % on this tokenizer; read from it, "26 of 30 batch-10
prompts overflow" (wave 14d's framing) — measured, **zero** do, worst
3,537 real tokens. Treat 4.5 as the realistic figure for qwen2-class
tokenizers and 3.0 as a genuinely-worst-case bound for unknown ones; the
run-time drift check in ``plugins/_common/llm_client.py`` is what covers
the unknown case with a measurement instead of a guess.

If a tokenizer *is* importable, it is used and the exact count is
reported instead — the range is a fallback, not a preference.

The measurement excludes the chat template's own framing tokens (role
markers, BOS), which add a small constant per message. That makes every
figure here a slight **under**-estimate, which is the safe direction for
a question about overflow.
"""
from __future__ import annotations

import argparse
import csv
import io
import statistics
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

GOLDEN = PROJECT_ROOT / "tests" / "golden"

#: Characters per token. Optimistic first.
BOUNDS = (4.5, 3.0)


def _tokenizer():
    """An exact counter if one is importable, else ``None``."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return lambda s: len(enc.encode(s)), "tiktoken/cl100k_base"
    except Exception:
        return None, None


def _read_csv(path: Path):
    return list(csv.DictReader(io.StringIO(
        path.read_text(encoding="utf-8-sig"))))


def _chunked(seq, n):
    n = max(1, int(n))
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _load_builder(stage: str):
    """The real prompt builder for the stage, imported by path.

    The plugin packages begin with digits, so they cannot be imported
    with a statement.
    """
    import importlib.util

    rel = "plugins/06_el/prompt.py" if stage == "EL" else "plugins/07_il/prompt.py"
    spec = importlib.util.spec_from_file_location(f"_prompt_{stage}",
                                                  PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod._build_llm_messages_for_criterion, mod.PROMPT_VERSION


def render(build, criterion_row, records, trunc_chars):
    """One prompt, exactly as ``run_el_screen`` would build it.

    The item pack is the one at ``plugins/06_el/screen.py::run_el_screen``
    — note that it carries title, abstract **and** keywords for every
    record whatever the criterion's target is, which is why the target
    does not reduce the size.
    """
    crit = {
        "id": criterion_row["id"],
        "type": criterion_row.get("type", "exclude"),
        "operator": criterion_row.get("operator", "llm"),
        "target": criterion_row.get("target", "abstract"),
        "what": [w for w in (criterion_row.get("what") or "").split("|") if w],
        "how": "llm",
        "label": criterion_row.get("label", ""),
        "threshold": criterion_row.get("threshold", 0.6),
    }
    items = [{
        "a_id": (r.get("local_id") or "").strip(),
        "title": r.get("title") or "",
        "abstract": r.get("abstract") or "",
        "keywords": r.get("keywords") or "",
    } for r in records]
    return "\n".join(m["content"] for m in build(crit, items, trunc_chars))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--stage", default="EL", choices=("EL", "IL"))
    ap.add_argument("--window", type=int, default=4096,
                    help="context window to compare against (default 4096, "
                         "Ollama's vram-based default with no GPU)")
    ap.add_argument("--trunc-chars", type=int, default=1500,
                    help="the provenance value from the runs under study")
    ap.add_argument("--batches", type=int, nargs="*",
                    default=[1, 5, 10, 50])
    args = ap.parse_args(argv)

    corpus_path = GOLDEN / ("el_input_v3.1.0.csv" if args.stage == "EL"
                            else "il_input_v3.1.0.csv")
    if not corpus_path.exists():
        print(f"missing {corpus_path}", file=sys.stderr)
        return 2

    corpus = _read_csv(corpus_path)
    crits = [c for c in _read_csv(GOLDEN / "criteria_harmonized_v3.1.0.csv")
             if (c.get("stage") or "").strip().upper() == args.stage]
    build, version = _load_builder(args.stage)
    exact, exact_name = _tokenizer()

    print(f"stage            : {args.stage} ({version})")
    print(f"corpus           : {corpus_path.name}, {len(corpus)} records")
    print(f"criteria         : {[c['id'] for c in crits]}")
    print(f"trunc_chars      : {args.trunc_chars}")
    print(f"context window   : {args.window}")
    how = exact_name or (f"character estimate, bounds "
                         f"{BOUNDS[0]}/{BOUNDS[1]} chars per token")
    print(f"token counting   : {how}")
    print()

    worst_overall = 0
    for crit in crits:
        print(f"--- {crit['id']} " + "-" * 56)
        for bs in args.batches:
            sizes = [len(render(build, crit, list(b), args.trunc_chars))
                     for b in _chunked(corpus, bs)]
            if not sizes:
                continue
            print(f"  batch_size={bs:<3} {len(sizes):>3} prompt(s)  "
                  f"chars med {int(statistics.median(sizes)):>7,}  "
                  f"max {max(sizes):>7,}")
            if exact:
                toks = [exact(render(build, crit, list(b), args.trunc_chars))
                        for b in _chunked(corpus, bs)]
                over = sum(1 for t in toks if t > args.window)
                worst_overall = max(worst_overall, max(toks))
                print(f"{'':>16}tokens med {int(statistics.median(toks)):>7,}  "
                      f"max {max(toks):>7,}   over window: {over}/{len(toks)}")
            else:
                for label, div in zip(("optimistic", "pessimistic"), BOUNDS):
                    toks = [s / div for s in sizes]
                    over = sum(1 for t in toks if t > args.window)
                    worst_overall = max(worst_overall, int(max(toks)))
                    print(f"{'':>16}{label:<12} med {int(statistics.median(toks)):>7,}  "
                          f"max {int(max(toks)):>7,}   over window: {over}/{len(toks)}")
        print()

    print(f"worst prompt seen: {worst_overall:,} tokens against a "
          f"{args.window:,}-token window")
    print("NOTE: a reply must also fit. Reply sizes are measured from the "
          "bundles' evidence JSON, not from this tool.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
