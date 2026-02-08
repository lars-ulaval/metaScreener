# -*- coding: utf-8 -*-
"""
Core primitives for References-of-X — AI v1

This module centralizes:
- Data model: BibItem
- Regexes & small helpers: now_iso, norm_key, title_norm, strip_html, normalize_lang
- Optional dependency flags: PANDAS_OK, FUZZY_OK, REQ_OK, OPENAI_OK
- Common constants: CACHE_DIR, LOGS_DIR
- Control primitive: CancellationToken (now supports pause/resume + cancel)

Keep this UI-agnostic (no tkinter imports here).
"""

from __future__ import annotations

import os
import re
import time
import html as _html
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from threading import Event

# =====================================================================================
# Optional deps / feature flags
# =====================================================================================

try:
    import pandas as pd  # for CSV/XLSX import/export (optional)
    PANDAS_OK = True
except Exception:
    pd = None  # type: ignore
    PANDAS_OK = False

try:
    from rapidfuzz import fuzz  # for fuzzy title matching (optional)
    FUZZY_OK = True
except Exception:
    fuzz = None  # type: ignore
    FUZZY_OK = False

try:
    import requests  # for HTTP to Crossref/OpenAlex/S2 (optional)
    REQ_OK = True
except Exception:
    requests = None  # type: ignore
    REQ_OK = False

try:
    from openai import OpenAI  # optional AI fallback
    OPENAI_OK = True
except Exception:
    OpenAI = None  # type: ignore
    OPENAI_OK = False

# =====================================================================================
# Constants (paths)
# =====================================================================================

HOME = os.path.expanduser("~")
CACHE_DIR = os.path.join(HOME, ".refx_cache")
LOGS_DIR = os.path.join(HOME, "refx_logs")

# Ensure cache dir exists when modules need it (creation may also happen elsewhere)
os.makedirs(CACHE_DIR, exist_ok=True)

# =====================================================================================
# Regexes
# =====================================================================================

DOI_PAT = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
YEAR_PAT = re.compile(r"\b(19|20)\d{2}\b")
NON_ALNUM = re.compile(r"[^0-9a-z]+")
HTML_TAGS = re.compile(r"<[^>]+>")

# =====================================================================================
# Helpers
# =====================================================================================

def now_iso() -> str:
    """UTC timestamp in ISO format (Z)."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_key(s: str) -> str:
    """Lowercase + strip non-alphanum; capped at 128 chars (stable dedup key)."""
    s = (s or "").strip().lower()
    s = NON_ALNUM.sub("", s)
    return s[:128]


def title_norm(s: str) -> str:
    """Trim, collapse spaces, and drop trailing punctuation like ':' ';' '.'"""
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*[:.;]$", "", s)
    return s


def strip_html(s: str) -> str:
    """Unescape and remove HTML tags (simple JATS/markup cleaner)."""
    if not s:
        return ""
    s = _html.unescape(s)
    return HTML_TAGS.sub(" ", s).strip()


def normalize_lang(code: str) -> str:
    """Normalize language tags to 2-letter lowercase (e.g., 'en-US' -> 'en')."""
    if not code:
        return ""
    code = code.strip().lower()
    m = re.match(r"^([a-z]{2})\b", code)
    return m.group(1) if m else (code[:2] if len(code) >= 2 else code)

# Optional: progress typing aliases (handy for services/ui, still UI-agnostic)
ProgressDict = Dict[str, Any]
ProgressCallback = Optional[Callable[[ProgressDict], None]]

# =====================================================================================
# Data model
# =====================================================================================

@dataclass
class BibItem:
    local_id: str
    source_key: str
    title: str = ""
    authors: str = ""          # full author string
    first_author: str = ""
    year: Optional[int] = None
    doi: str = ""
    pmid: str = ""
    pmcid: str = ""
    arxiv: str = ""
    venue: str = ""            # journal / proceedings
    volume: str = ""
    issue: str = ""
    pages: str = ""
    publisher: str = ""
    lang: str = ""
    url: str = ""
    confidence: float = 0.0
    status: str = "pending"     # pending / resolved / ambiguous / failed
    provenance: str = ""        # e.g., "scraper_output", "pasted_text", "csv:x.csv"
    last_checked: str = ""      # ISO timestamp
    parents: List[str] = field(default_factory=list)  # which X items cite it

    # Content fields
    abstract: str = ""                      # résumé
    keywords: str = ""                      # semi-colon separated
    open_access: Optional[bool] = None      # True/False if known
    doc_type: str = ""                      # normalized: article/conference/chapter/book/thesis/report/preprint/other

    # Audit / connectivity (resolver stage)
    hit_openalex: Optional[bool] = None     # did OA return a usable payload?
    hit_crossref: Optional[bool] = None     # did CR return a usable payload?
    hit_semanticscholar: Optional[bool] = None  # did S2 return a usable payload?
    match_strategy: str = ""                # 'doi', 'title', etc.
    winner_source: str = ""                 # which source set identity fields

    # Per-field provenance & audit
    field_sources: Dict[str, str] = field(default_factory=dict)         # e.g., {"title": "openalex", "abstract": "s2"}
    filled_by_source_counts: Dict[str, int] = field(default_factory=dict)  # e.g., {"openalex": 3, "crossref": 1}
    resolver_notes: str = ""                                            # compact human-readable audit line

    def to_row(self) -> Dict[str, Any]:
        d = asdict(self)
        d["parents"] = ",".join(self.parents or [])
        return d

# =====================================================================================
# Control primitives
# =====================================================================================

class CancellationToken:
    """
    Cooperative control primitive for workers/threads.

    - .cancel()  → request hard stop ASAP (check .cancelled in loops)
    - .pause()   → request temporary pause; worker should idle until resume()
    - .resume()  → clear pause
    - .wait_if_paused() → helper for tight loops to block while paused

    This stays UI-agnostic: the UI just flips pause/cancel; services/workers
    check the flags and cooperate.
    """
    def __init__(self) -> None:
        self._cancel_ev = Event()
        self._pause_ev = Event()  # when SET → paused

    # ---- properties ----
    @property
    def cancelled(self) -> bool:
        return self._cancel_ev.is_set()

    @property
    def paused(self) -> bool:
        return self._pause_ev.is_set()

    # ---- commands ----
    def cancel(self) -> None:
        self._cancel_ev.set()

    def pause(self) -> None:
        self._pause_ev.set()

    def resume(self) -> None:
        self._pause_ev.clear()

    def toggle_pause(self) -> None:
        if self._pause_ev.is_set():
            self._pause_ev.clear()
        else:
            self._pause_ev.set()

    # ---- cooperative wait ----
    def wait_if_paused(self, poll_s: float = 0.1) -> None:
        """
        Block in small sleeps while paused; returns immediately if not paused.
        Exits early if cancelled during pause.
        """
        while self.paused and not self.cancelled:
            time.sleep(poll_s)

# =====================================================================================
# Public exports
# =====================================================================================

__all__ = [
    # flags & deps
    "PANDAS_OK", "FUZZY_OK", "REQ_OK", "OPENAI_OK", "pd", "fuzz", "requests", "OpenAI",
    # constants
    "CACHE_DIR", "LOGS_DIR",
    # regexes & helpers
    "DOI_PAT", "YEAR_PAT", "NON_ALNUM", "now_iso", "norm_key", "title_norm", "strip_html", "normalize_lang",
    # model & control
    "BibItem", "CancellationToken",
    # progress typing aliases (optional)
    "ProgressDict", "ProgressCallback",
]
