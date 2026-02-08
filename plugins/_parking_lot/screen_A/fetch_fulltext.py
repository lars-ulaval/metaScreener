# -*- coding: utf-8 -*-
"""
Created on Mon Sep 22 11:30:12 2025

@author: alere
"""

# File: plugins/screen_A/fetch_fulltext.py
# Batch 3 — Full-text retriever with polite resolution order and caching
# Order: DOI → OpenAlex → PubMed/PMC → Unpaywall → publisher landing page (recorded, not scraped)
# Notes:
# - No HTML scraping of paywalled pages. We only follow explicit OA links (PDF/PMCID) or record landing URLs.
# - Uses an on-disk cache at ~/.screenA_cache/fulltext/ ; file names are based on a stable hash of DOI or URL.
# - UNPAYWALL requires a contact email (set env UNPAYWALL_EMAIL). If not set, that step is skipped.

from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional
import hashlib
import json
import os
import re
import time

try:
    import requests
except Exception:
    requests = None

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".screenA_cache", "fulltext")
META_SUFFIX = ".meta.json"
PDF_SUFFIX = ".pdf"
SESSION_TIMEOUT = 20


@dataclass
class FTResult:
    a_id: Any
    status: str  # found|unavailable|error
    path: Optional[str] = None
    source: Optional[str] = None  # openalex|pmc|unpaywall|landing|local
    notes: str = ""
    url: Optional[str] = None

    def to_dict(self):
        return asdict(self)


# ----------------- public API -----------------

def fetch_fulltext_for_items(items: List[Dict[str, Any]], *, progress_cb=None) -> List[Dict[str, Any]]:
    """Sequential polite fetcher. Emits progress via progress_cb(i, n, FTResult|str)."""
    ensure_cache()
    out: List[Dict[str, Any]] = []
    for idx, it in enumerate(items, 1):
        try:
            res = fetch_one(it)
        except Exception as e:
            res = FTResult(a_id=it.get("a_id") or it.get("id") or idx, status="error", notes=str(e))
        out.append(res.to_dict())
        if progress_cb:
            progress_cb(idx, len(items), res)
    return out


# ----------------- per-item logic -----------------

def fetch_one(item: Dict[str, Any]) -> FTResult:
    a_id = item.get("a_id") or item.get("id")
    doi = normalize_doi(item.get("doi") or "")
    pmcid = normalize_pmcid(item.get("pmcid") or item.get("pmc") or "")
    pdf_hint = item.get("pdf") or item.get("pdf_url") or item.get("oa_pdf")

    # Local hint (already have a file)
    if pdf_hint and os.path.isfile(str(pdf_hint)):
        return FTResult(a_id=a_id, status="found", path=str(pdf_hint), source="local", notes="provided by metadata", url=None)

    # Cache hit by DOI or pmcid
    key = doi or pmcid or (pdf_hint or "")
    meta = cache_lookup_meta(key)
    if meta and meta.get("status") == "found" and meta.get("path") and os.path.isfile(meta["path"]):
        return FTResult(a_id=a_id, **meta)

    # Try OpenAlex
    if doi:
        r = try_openalex_pdf(doi)
        if r and r.get("status") == "found":
            write_cache_meta(key, r)
            return FTResult(a_id=a_id, **r)
        if r and r.get("status") == "landing":
            # keep the landing if nothing else works
            landing_candidate = r
        else:
            landing_candidate = None
    else:
        landing_candidate = None

    # Try PMC by PMCID
    if pmcid:
        r = try_pmc_pdf(pmcid)
        if r and r.get("status") == "found":
            write_cache_meta(key, r)
            return FTResult(a_id=a_id, **r)

    # Try Unpaywall (needs email)
    if doi:
        r = try_unpaywall_pdf(doi)
        if r and r.get("status") == "found":
            write_cache_meta(key, r)
            return FTResult(a_id=a_id, **r)

    # Fallback: keep landing URL if we got one earlier
    if landing_candidate:
        write_cache_meta(key, landing_candidate)
        return FTResult(a_id=a_id, **landing_candidate)

    # Otherwise unavailable
    miss = {"status":"unavailable", "path":None, "source":None, "notes":"no OA PDF found", "url":None}
    write_cache_meta(key, miss)
    return FTResult(a_id=a_id, **miss)


# ----------------- providers -----------------

def try_openalex_pdf(doi: str) -> Optional[Dict[str, Any]]:
    if not requests:
        return None
    url = f"https://api.openalex.org/works/doi:{doi.lower()}"
    try:
        r = requests.get(url, timeout=SESSION_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        oa = (data or {}).get("open_access") or {}
        pdf_url = oa.get("oa_url_for_pdf") or oa.get("oa_url")
        if pdf_url and pdf_url.lower().endswith(".pdf"):
            path = download_to_cache(pdf_url)
            if path:
                return {"status":"found", "path":path, "source":"openalex", "notes":"oa_url_for_pdf", "url":pdf_url}
        # record landing
        host = (data or {}).get("host_venue") or {}
        landing = host.get("url")
        if landing:
            return {"status":"landing", "path":None, "source":"openalex", "notes":"landing only", "url":landing}
    except Exception:
        return None
    return None


def try_pmc_pdf(pmcid: str) -> Optional[Dict[str, Any]]:
    pmcid = normalize_pmcid(pmcid)
    if not pmcid:
        return None
    # Direct PDF pattern: https://www.ncbi.nlm.nih.gov/pmc/articles/PMCID/pdf/
    url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
    path = download_to_cache(url)
    if path:
        return {"status":"found", "path":path, "source":"pmc", "notes":"pmc pdf", "url":url}
    return None


def try_unpaywall_pdf(doi: str) -> Optional[Dict[str, Any]]:
    if not requests:
        return None
    email = os.environ.get("UNPAYWALL_EMAIL")
    if not email:
        return None
    url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
    try:
        r = requests.get(url, timeout=SESSION_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        best = (data or {}).get("best_oa_location") or {}
        pdf = best.get("url_for_pdf") or best.get("url")
        if pdf and pdf.lower().endswith(".pdf"):
            path = download_to_cache(pdf)
            if path:
                return {"status":"found", "path":path, "source":"unpaywall", "notes":"best_oa_location", "url":pdf}
    except Exception:
        return None
    return None


# ----------------- cache & download -----------------

def ensure_cache():
    os.makedirs(CACHE_DIR, exist_ok=True)


def cache_key(s: str) -> str:
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()[:20]
    return h


def cache_lookup_meta(key: str) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    fp = os.path.join(CACHE_DIR, cache_key(key) + META_SUFFIX)
    if os.path.isfile(fp):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def write_cache_meta(key: str, meta: Dict[str, Any]) -> None:
    if not key:
        return
    fp = os.path.join(CACHE_DIR, cache_key(key) + META_SUFFIX)
    try:
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def download_to_cache(url: str) -> Optional[str]:
    if not requests:
        return None
    try:
        r = requests.get(url, timeout=SESSION_TIMEOUT, stream=True)
        if r.status_code != 200 or "pdf" not in (r.headers.get("content-type") or "").lower():
            return None
        key = cache_key(url)
        fp = os.path.join(CACHE_DIR, key + PDF_SUFFIX)
        with open(fp, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
        # write a companion meta if absent
        if not os.path.isfile(os.path.join(CACHE_DIR, key + META_SUFFIX)):
            write_cache_meta(url, {"status":"found", "path":fp, "source":"download", "notes":"direct", "url":url})
        return fp
    except Exception:
        return None


# ----------------- utils -----------------

def normalize_doi(doi: str) -> str:
    if not doi:
        return ""
    d = doi.strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    return d


def normalize_pmcid(pmcid: str) -> str:
    if not pmcid:
        return ""
    s = pmcid.strip().upper()
    if not s.startswith("PMC"):
        s = "PMC" + s
    return s
