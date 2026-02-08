# -*- coding: utf-8 -*-
"""
Created on Mon Sep 22 11:52:04 2025

@author: alere
"""

# File: plugins/screen_A/screen_fulltext.py
# Batch 4 — Full-text screening (single-judge placeholder) with evidence spans
#
# Responsibilities
# - Read PDFs (PyMuPDF if available, else pdfminer.six)
# - Chunk text conservatively (page-aware)
# - For each fulltext/both criterion, retrieve relevant chunks by keyword heuristics
# - Decide include/not_meet/uncertain per criterion (heuristic for now; LLM pluggable)
# - Emit evidence snippets (page + text excerpt)
# - Provide screen_fulltext(...) entry point with progress callback

from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Tuple, Optional, Callable
import os
import re

# Optional backends
try:
    import fitz  # PyMuPDF
    HAVE_FITZ = True
except Exception:
    fitz = None
    HAVE_FITZ = False

try:
    from pdfminer.high_level import extract_text as pdfminer_extract_text
    HAVE_PDFMINER = True
except Exception:
    pdfminer_extract_text = None
    HAVE_PDFMINER = False

from .criteria_schema import normalize_synonyms


# ---------------- Extraction -----------------

def extract_pages(path: str) -> List[Tuple[int, str]]:
    """Return list of (page_index_1based, text)."""
    if HAVE_FITZ:
        doc = fitz.open(path)
        pages = []
        for i in range(doc.page_count):
            txt = doc.load_page(i).get_text("text") or ""
            pages.append((i+1, txt))
        doc.close()
        return pages
    if HAVE_PDFMINER:
        # pdfminer returns whole-text; we synthesize a single page
        txt = pdfminer_extract_text(path) or ""
        return [(1, txt)]
    raise RuntimeError("No PDF backend available (PyMuPDF or pdfminer.six)")


def make_chunks(pages: List[Tuple[int,str]], max_chars: int = 2500) -> List[Dict[str,Any]]:
    chunks: List[Dict[str,Any]] = []
    buf = []
    cur_len = 0
    start_page = None
    for pno, txt in pages:
        t = (txt or "").strip()
        if not t:
            continue
        lines = t.splitlines()
        page_text = "\n".join(lines)
        if start_page is None:
            start_page = pno
        if cur_len + len(page_text) > max_chars and buf:
            chunk_text = "\n".join(buf)
            chunks.append({"pages": (start_page, pno-1), "text": chunk_text})
            buf = [page_text]
            cur_len = len(page_text)
            start_page = pno
        else:
            buf.append(page_text)
            cur_len += len(page_text)
    if buf:
        chunk_text = "\n".join(buf)
        end_page = pages[-1][0]
        chunks.append({"pages": (start_page, end_page), "text": chunk_text})
    return chunks


# --------------- Retrieval -------------------

def score_chunk_for_patterns(text: str, patterns: List[str]) -> float:
    if not text:
        return 0.0
    t = normalize_synonyms(text.lower())
    sc = 0
    for p in patterns:
        try:
            pnorm = normalize_synonyms(str(p).lower())
            if pnorm in t:
                sc += 1
            else:
                # light regex attempt
                if re.search(pnorm, t, flags=re.I):
                    sc += 1
        except re.error:
            continue
    return float(sc)


def top_k_chunks(chunks: List[Dict[str,Any]], patterns: List[str], k: int = 3) -> List[Dict[str,Any]]:
    scored = [ (score_chunk_for_patterns(ch["text"], patterns), i, ch) for i,ch in enumerate(chunks) ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [ch for s,_,ch in scored[:k] if s > 0]


# --------------- Decisions -------------------

@dataclass
class FTDecision:
    a_id: Any
    criterion_id: str
    decision: str  # meet | not_meet | uncertain
    confidence: float
    evidence: List[Dict[str,Any]]  # {page, text}

    def to_dict(self):
        return asdict(self)


LLMDecider = Callable[[str, Dict[str,Any], List[Dict[str,Any]]], Tuple[str, float]]
# Signature: (criterion_label, criterion_struct, evidence_chunks) -> (decision, confidence)


def heuristic_decider(criterion_label: str, c: Dict[str,Any], evid_chunks: List[Dict[str,Any]]) -> Tuple[str,float]:
    """Simple rule: if any chunk matched (we only pass chunks with >0 score),
    then include-criterion => meet, exclude-criterion => not_meet; otherwise uncertain.
    Confidence scales with #chunks.
    """
    has_hits = len(evid_chunks) > 0
    ctype = (c.get("type") or "include").lower()
    if has_hits:
        return ("meet" if ctype == "include" else "not_meet", min(0.9, 0.5 + 0.2*len(evid_chunks)))
    return ("uncertain", 0.4)


def decide_for_criterion(a_id: Any, c: Dict[str,Any], chunks: List[Dict[str,Any]], decider: Optional[LLMDecider] = None) -> FTDecision:
    scope = (c.get("scope") or "both").lower()
    if scope not in ("fulltext","both"):
        return FTDecision(a_id=a_id, criterion_id=c.get("id",""), decision="uncertain", confidence=0.0, evidence=[])
    patterns = c.get("patterns") or [c.get("label") or ""]
    evid_chunks = top_k_chunks(chunks, patterns, k=3)
    # Build evidence spans: first ~240 chars of each chunk
    evidence: List[Dict[str,Any]] = []
    for ch in evid_chunks:
        p0,p1 = ch["pages"]
        snippet = ch["text"]
        if len(snippet) > 240:
            snippet = snippet[:237] + "…"
        evidence.append({"page": f"{p0}-{p1}", "text": snippet})
    dec = (decider or heuristic_decider)(c.get("label",""), c, evid_chunks)
    return FTDecision(a_id=a_id, criterion_id=c.get("id",""), decision=dec[0], confidence=dec[1], evidence=evidence)


def screen_fulltext(items: List[Dict[str,Any]], ft_results: List[Dict[str,Any]], criteria: List[Dict[str,Any]], *,
                    progress_cb=None, decider: Optional[LLMDecider] = None) -> List[Dict[str,Any]]:
    """Full-text screening entry point.
    - items: A items (need a_id and maybe titles for logs)
    - ft_results: output from fetch_fulltext_for_items (we look up path by a_id)
    - criteria: harmonized criteria
    Returns list of {a_id, per_criterion:[FTDecision...]}
    """
    path_by_id = { (r.get("a_id") if isinstance(r,dict) else getattr(r,'a_id',None)): (r.get("path") if isinstance(r,dict) else getattr(r,'path',None)) for r in ft_results }
    out: List[Dict[str,Any]] = []
    total = len(items)
    for i, it in enumerate(items, 1):
        a_id = it.get("a_id") or it.get("id") or i
        pdf_path = path_by_id.get(a_id)
        if not pdf_path or not os.path.isfile(pdf_path):
            # no full text
            res = {"a_id": a_id, "per_criterion": [], "notes": "full text unavailable"}
            out.append(res)
            if progress_cb:
                progress_cb(i, total, res)
            continue
        try:
            pages = extract_pages(pdf_path)
            chunks = make_chunks(pages, max_chars=2500)
            per: List[Dict[str,Any]] = []
            for c in criteria:
                if (c.get("scope","both") not in ("fulltext","both")):
                    continue
                d = decide_for_criterion(a_id, c, chunks, decider=decider)
                per.append(d.to_dict())
            res = {"a_id": a_id, "per_criterion": per, "notes": "ok"}
        except Exception as e:
            res = {"a_id": a_id, "per_criterion": [], "notes": f"error: {e}"}
        out.append(res)
        if progress_cb:
            progress_cb(i, total, res)
    return out
