# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
services.py — headless services for References-of-X — AI v1

This module provides the non-UI logic:
- Ingestor: load X from text / CSV / XLSX
- MetaResolver: enrich X items via Crossref / OpenAlex / Semantic Scholar
- RefFetcher: fetch per-X reference lists
- dedup_items: aggregate & deduplicate into vector A
- Exporter: CSV export (and can be extended)

It depends on `core.py` for:
  BibItem, CancellationToken, helpers, and optional-dep flags.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Callable

from .core import (  # package context
    # flags & deps
    PANDAS_OK, FUZZY_OK, REQ_OK, pd, fuzz, requests,
    # helpers & regexes
    DOI_PAT, YEAR_PAT, now_iso, norm_key, title_norm, strip_html,
    # model
    BibItem, CancellationToken,
)

# Shared with the EH/IH corpus parser so Plugin 02 and the screening stages
# agree on which encodings a researcher's CSV may arrive in.
from plugins._common.parser import _decode_bytes

# Optional heuristic language detector (silent if missing)
try:
    from langdetect import detect as _ld_detect  # type: ignore
    _LANGDETECT_OK = True
except Exception:
    _ld_detect = None
    _LANGDETECT_OK = False

# -------------------------------------------------------------------------------------
# Logging abstraction (minimal)
# -------------------------------------------------------------------------------------

class LoggerProto:
    """Duck-typed logger interface (only .log(str) is used)."""
    def log(self, msg: str) -> None:  # pragma: no cover
        print(msg)

class NullLogger(LoggerProto):
    def log(self, msg: str) -> None:
        pass

def _maybe_emit(progress: Optional[Callable[[Dict[str, Any]], None]], payload: Dict[str, Any]) -> None:
    """Safely emit a progress event dict if a callback was provided."""
    if not progress:
        return
    try:
        progress(payload)
    except Exception:
        # Never break the worker on UI callback issues
        pass

def _wait_if_paused(cancel: CancellationToken, poll_s: float = 0.1) -> None:
    """
    Cooperative pause: if the CancellationToken exposes a .paused flag,
    idle until it clears or until cancelled.
    (UI sets this; safe no-op if attribute is absent.)
    """
    while getattr(cancel, "paused", False) and not cancel.cancelled:
        time.sleep(poll_s)

# =====================================================================================
# Ingestion: from text / CSV / XLSX / scraper output
# =====================================================================================

class Ingestor:
    def __init__(self, logger: LoggerProto | None = None):
        self.logger = logger or NullLogger()

    def from_text(self, raw: str, source_label: str) -> List[BibItem]:
        items: List[BibItem] = []
        lines = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
        for i, ln in enumerate(lines, 1):
            doi = self._find_doi(ln)
            ya = self._find_year_and_first_author(ln)
            title = self._guess_title(ln)
            local_id = f"X{str(i).zfill(3)}"
            src_key = norm_key(ln)[:64]
            bi = BibItem(
                local_id=local_id,
                source_key=src_key,
                title=title,
                authors="",
                first_author=ya.get("first_author", ""),
                year=ya.get("year"),
                doi=doi or "",
                provenance=source_label,
                last_checked=now_iso(),
            )
            items.append(bi)
        self.logger.log(f"Ingested {len(items)} items from text")
        return items

    def _read_csv_text(self, path: str) -> str:
        """Read a CSV as text, tolerating the encodings researchers actually have.

        Uses the same ladder as plugins/_common/parser._decode_bytes:
        utf-8-sig, utf-8, cp1252, latin-1. Before this, the CSV path used
        pd.read_csv(path) with no encoding and then open(path,
        encoding="utf-8") as a fallback, so a cp1252 file - the ordinary
        output of Windows reference managers - failed both and left the
        corpus silently empty (F-13), and a BOM'd file lost its first
        column to a mangled header name (F-38).
        """
        raw = open(path, "rb").read()
        if not raw.strip():
            raise RuntimeError(f"{os.path.basename(path)} is empty.")
        return _decode_bytes(raw)

    def from_csv_or_xlsx(self, path: str) -> List[BibItem]:
        items: List[BibItem] = []
        ext = os.path.splitext(path)[1].lower()
        rows: List[Dict[str, Any]] = []
        csv_text: Optional[str] = None

        if ext == ".csv":
            # Decode once, up front, so pandas and the fallback reader agree
            # on the encoding and a decode failure is reported as itself.
            csv_text = self._read_csv_text(path)

        if PANDAS_OK and ext in (".xlsx", ".xls", ".csv"):
            try:
                if ext == ".csv":
                    df = pd.read_csv(io.StringIO(csv_text))
                else:
                    df = pd.read_excel(path)
                rows = df.to_dict(orient="records")
            except Exception as e:
                self.logger.log(f"Pandas failed to read file: {e}; falling back if possible")

        if not rows:
            if ext == ".csv":
                try:
                    rows = list(csv.DictReader(io.StringIO(csv_text)))
                except Exception as e:
                    self.logger.log(f"csv read error: {e}")
                    raise RuntimeError(
                        f"Could not parse {os.path.basename(path)} as CSV: {e}"
                    ) from e
            else:
                raise RuntimeError("Install pandas/openpyxl to read Excel files, or provide CSV.")

        for i, r in enumerate(rows, 1):
            title = r.get("title") or r.get("Title") or r.get("name") or ""
            doi = r.get("doi") or r.get("DOI") or self._find_doi(" ".join(map(str, r.values()))) or ""
            auth = r.get("authors") or r.get("Authors") or r.get("author") or ""
            ya = r.get("year") or r.get("Year")

            try:
                year = int(ya) if ya not in (None, "") else None
            except Exception:
                year = None

            first_author = (auth.split(";")[0] if ";" in auth else auth.split(",")[0]).strip() if auth else ""
            local_id = f"X{str(i).zfill(3)}"
            src_key = norm_key(title or doi or json.dumps(r))

            items.append(
                BibItem(
                    local_id=local_id,
                    source_key=src_key,
                    title=title_norm(title),
                    authors=auth,
                    first_author=first_author,
                    year=year,
                    doi=doi,
                    provenance=f"file:{os.path.basename(path)}",
                    last_checked=now_iso(),
                )
            )

        if not items:
            # A readable file that yields nothing is legitimate (header-only
            # export) but must never be mistaken for a successful ingest.
            self.logger.log(
                f"WARNING: no records ingested from {os.path.basename(path)} - "
                f"the file parsed but produced 0 items. Check that it has data "
                f"rows below the header and a recognisable title/doi column."
            )
        else:
            self.logger.log(f"Ingested {len(items)} items from file")
        return items

    def _find_doi(self, s: str) -> Optional[str]:
        m = DOI_PAT.search(s or "")
        return m.group(0) if m else None

    def _find_year_and_first_author(self, s: str) -> Dict[str, Any]:
        out = {"year": None, "first_author": ""}
        m = YEAR_PAT.search(s or "")
        if m:
            try:
                out["year"] = int(m.group(0))
            except Exception:
                out["year"] = None
        m2 = re.match(r"\s*([A-Z][A-Za-z\-']+)", s or "")
        if m2:
            out["first_author"] = m2.group(1)
        return out

    def _guess_title(self, s: str) -> str:
        q = re.findall(r"\“([^\”]+)\”|\"([^\"]+)\"|'([^']+)'", s or "")
        for tup in q:
            cand = next((t for t in tup if t), None)
            if cand:
                return title_norm(cand)
        return title_norm(s or "")

# =====================================================================================
# Metadata resolution via public APIs (Crossref / OpenAlex / S2)
# =====================================================================================

class MetaResolver:
    def __init__(self, logger: LoggerProto | None = None, cache_dir: str | None = None):
        self.logger = logger or NullLogger()
        self.cache_dir = cache_dir or os.path.join(os.path.expanduser("~"), ".refx_cache", "meta")
        os.makedirs(self.cache_dir, exist_ok=True)

    # ---- cache helpers ----
    def _cache_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"{key}.json")

    def _load_cache(self, key: str) -> Optional[Dict[str, Any]]:
        p = self._cache_path(key)
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def _save_cache(self, key: str, payload: Dict[str, Any]) -> None:
        try:
            with open(self._cache_path(key), "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except Exception:
            pass

    # ---- Crossref ----
    def _crossref_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        if not (REQ_OK and requests):
            return None
        key = f"cr_doi_{norm_key(doi)}"
        cached = self._load_cache(key)
        if cached:
            return cached
        url = f"https://api.crossref.org/works/{requests.utils.quote(doi)}"
        try:
            r = requests.get(url, timeout=12)
            if r.status_code == 200:
                data = r.json()
                self._save_cache(key, data)
                return data
        except Exception:
            return None
        return None

    def _crossref_biblio(self, title: str) -> Optional[Dict[str, Any]]:
        if not (REQ_OK and requests):
            return None
        url = "https://api.crossref.org/works"
        params = {"query.bibliographic": title or "", "rows": 5}
        try:
            r = requests.get(url, params=params, timeout=12)
            if r.status_code == 200:
                return r.json()
        except Exception:
            return None
        return None

    # ---- OpenAlex ----
    def _openalex_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        if not (REQ_OK and requests):
            return None
        key = f"oa_doi_{norm_key(doi)}"
        cached = self._load_cache(key)
        if cached:
            return cached
        url = "https://api.openalex.org/works/https://doi.org/" + doi
        try:
            r = requests.get(url, timeout=12)
            if r.status_code == 200:
                data = r.json()
                self._save_cache(key, data)
                return data
        except Exception:
            return None
        return None

    def _openalex_works(self, title: str) -> Optional[Dict[str, Any]]:
        if not (REQ_OK and requests):
            return None
        key = f"oa_q_{norm_key(title)[:64]}"
        cached = self._load_cache(key)
        if cached:
            return cached
        url = "https://api.openalex.org/works"
        params = {"search": title or "", "per_page": 5}
        try:
            r = requests.get(url, params=params, timeout=12)
            if r.status_code == 200:
                data = r.json()
                self._save_cache(key, data)
                return data
        except Exception:
            return None
        return None

    # ---- Semantic Scholar ----
    def _s2_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        if not (REQ_OK and requests):
            return None
        key = f"s2_q_{norm_key(title)[:64]}"
        cached = self._load_cache(key)
        if cached:
            return cached
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            "query": title or "",
            "limit": 5,
            "fields": "title,year,authors,externalIds,venue,publicationVenue,publicationTypes,abstract,isOpenAccess",
        }
        try:
            r = requests.get(url, params=params, timeout=12)
            if r.status_code == 200:
                data = r.json()
                self._save_cache(key, data)
                return data
        except Exception:
            return None
        return None

    def _s2_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """Minimal S2 metadata by DOI (used mainly to recover abstracts when CR/OA miss)."""
        if not (REQ_OK and requests):
            return None
        key = f"s2_doi_{norm_key(doi)}"
        cached = self._load_cache(key)
        if cached:
            return cached
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
        fields = "title,year,authors,externalIds,venue,publicationVenue,publicationTypes,abstract,isOpenAccess"
        try:
            r = requests.get(url, params={"fields": fields}, timeout=12)
            if r.status_code == 200:
                data = r.json()
                self._save_cache(key, data)
                return data
        except Exception:
            return None
        return None

    # ---- small helpers to track provenance (field-level) ----
    def _ensure_audit_dicts(self, bi: BibItem) -> None:
        if not hasattr(bi, "field_sources") or not isinstance(getattr(bi, "field_sources"), dict):
            setattr(bi, "field_sources", {})  # field -> 'openalex'/'crossref'/'semanticscholar'/'heuristic'
        if not hasattr(bi, "filled_by_source_counts") or not isinstance(getattr(bi, "filled_by_source_counts"), dict):
            setattr(bi, "filled_by_source_counts", {
                "openalex": 0, "crossref": 0, "semanticscholar": 0, "heuristic": 0, "unpaywall": 0
            })
        if not hasattr(bi, "resolver_notes"):
            setattr(bi, "resolver_notes", "")

    def _set_if_empty(self, bi: BibItem, field: str, value: Any, source: str) -> None:
        """Set bi.<field> if empty; record provenance and increment per-source counter."""
        if value in (None, "", []):
            return
        cur = getattr(bi, field, None)
        is_empty = (cur in (None, "", []))
        if is_empty:
            setattr(bi, field, value)
            fs = getattr(bi, "field_sources")
            fs[field] = source
            cnt = getattr(bi, "filled_by_source_counts")
            cnt[source] = cnt.get(source, 0) + 1

    # ---- Orchestration ----
    def resolve_item(
        self,
        bi: BibItem,
        cancel: CancellationToken,
        progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> BibItem:
        if cancel.cancelled:
            return bi
        _wait_if_paused(cancel)
        bi.last_checked = now_iso()
        self._ensure_audit_dicts(bi)
        _maybe_emit(progress, {"phase": "resolve", "event": "start", "id": bi.local_id or "", "ts": now_iso()})

        # initialize audit flags for this run
        if bi.hit_openalex is None: bi.hit_openalex = False
        if bi.hit_crossref is None: bi.hit_crossref = False
        if bi.hit_semanticscholar is None: bi.hit_semanticscholar = False
        bi.match_strategy = "doi" if bool(bi.doi) else "title"

        # Helper to record "winner" when key identity fields change
        def _record_winner(source_name: str, before_doi: str, before_title: str) -> None:
            if not bi.winner_source:
                if (not before_doi) and bi.doi:
                    bi.winner_source = source_name
                elif (not before_title) and bi.title:
                    bi.winner_source = source_name

        # Primary phase: pick identity & main metadata
        if bi.doi:
            self.logger.log(f"Resolve via DOI (Crossref/OpenAlex): {bi.local_id} {bi.doi}")

            before_doi, before_title = bi.doi, bi.title
            _wait_if_paused(cancel)
            payload = self._crossref_by_doi(bi.doi)
            if payload:
                bi.hit_crossref = True
                self._fill_from_crossref(bi, payload)
                _record_winner("crossref", before_doi, before_title)

            # Also try OA even if CR returned (to enable later gap filling)
            before_doi, before_title = bi.doi, bi.title
            oa = self._openalex_by_doi(bi.doi)
            if oa:
                bi.hit_openalex = True
                self._fill_from_openalex(bi, oa)
                _record_winner("openalex", before_doi, before_title)

        else:
            if bi.title:
                self.logger.log(f"Resolve via title: {bi.local_id} — {bi.title[:80]}")
                # OpenAlex search
                before_doi, before_title = bi.doi, bi.title
                _wait_if_paused(cancel)
                oa_payload = self._openalex_works(bi.title)
                chosen = self._pick_best_openalex(oa_payload, bi) if oa_payload else None
                if chosen:
                    bi.hit_openalex = True
                    self._fill_from_openalex(bi, chosen)
                    _record_winner("openalex", before_doi, before_title)

                # Crossref biblio (only if DOI still empty)
                if not bi.doi:
                    before_doi, before_title = bi.doi, bi.title
                    cr_payload = self._crossref_biblio(bi.title)
                    chosen2 = self._pick_best_crossref(cr_payload, bi) if cr_payload else None
                    if chosen2:
                        bi.hit_crossref = True
                        self._fill_from_crossref(bi, {"message": chosen2})
                        _record_winner("crossref", before_doi, before_title)

                # S2 (only if DOI still empty)
                if not bi.doi:
                    before_doi, before_title = bi.doi, bi.title
                    s2_payload = self._s2_by_title(bi.title)
                    chosen3 = self._pick_best_s2(s2_payload, bi) if s2_payload else None
                    if chosen3:
                        bi.hit_semanticscholar = True
                        self._fill_from_s2(bi, chosen3)
                        _record_winner("semanticscholar", before_doi, before_title)

        # Gap-fill phase: only fill missing content fields; never overwrite
        self._gap_fill_missing(bi)

        # Status/confidence + audit note
        if bi.doi or bi.title:
            bi.status = "resolved"
            bi.confidence = bi.confidence or 0.8
        else:
            bi.status = "ambiguous"
            bi.confidence = bi.confidence or 0.3

        bi.resolver_notes = self._make_resolver_note(bi)
        self.logger.log(bi.resolver_notes)
        _maybe_emit(progress, {
            "phase": "resolve",
            "event": "done",
            "id": bi.local_id or "",
            "hits": {
                "oa": bool(getattr(bi, "hit_openalex", False)),
                "cr": bool(getattr(bi, "hit_crossref", False)),
                "s2": bool(getattr(bi, "hit_semanticscholar", False)),
            },
            "ts": now_iso(),
        })
        return bi

    def _gap_fill_missing(self, bi: BibItem) -> None:
        """Try to fill lang / abstract / keywords from any source that can provide them.
        Never overwrite non-empty fields.
        """
        need_lang = not bool(getattr(bi, "lang", "") or "")
        need_abs = not bool(getattr(bi, "abstract", "") or "")
        need_kw  = not bool(getattr(bi, "keywords", "") or "")
        if not (need_lang or need_abs or need_kw):
            return

        title_for_search = (bi.title or "").strip()
        doi = (bi.doi or "").strip()

        # 1) OpenAlex (by DOI if we have it; else by title)
        if need_abs or need_kw:
            oa_payload = None
            if doi:
                oa_payload = self._openalex_by_doi(doi)
            elif title_for_search:
                oa_payload = self._openalex_works(title_for_search)

            chosen = None
            if oa_payload:
                # normalize: could be the work itself or a search results payload
                if "id" in oa_payload and oa_payload.get("display_name"):
                    chosen = oa_payload
                elif "results" in oa_payload:
                    chosen = self._pick_best_openalex(oa_payload, bi)
            if chosen:
                bi.hit_openalex = True
                self._fill_from_openalex(bi, chosen)

        # 2) Crossref (bibliographic by title if no DOI, else by DOI)
        if need_lang or need_abs or need_kw:
            cr_payload = None
            msg_or_item = None
            if doi:
                cr_payload = self._crossref_by_doi(doi)
                msg_or_item = cr_payload
            elif title_for_search:
                cr_payload = self._crossref_biblio(title_for_search)
                msg_or_item = {"message": self._pick_best_crossref(cr_payload, bi) or {}}

            if msg_or_item:
                bi.hit_crossref = True
                self._fill_from_crossref(bi, msg_or_item)

        # 3) Semantic Scholar — **by DOI first** for abstract, then by title as fallback
        # 3) Semantic Scholar — **by DOI first** for abstract, then by title as fallback
        if need_abs or need_kw:
            if doi:
                s2_doi = self._s2_by_doi(doi)
                if s2_doi and (s2_doi.get("abstract") or (s2_doi.get("venue") or s2_doi.get("publicationVenue"))):
                    bi.hit_semanticscholar = True
                    self._fill_from_s2(bi, s2_doi)
        
            if (need_abs and not bi.abstract) and title_for_search:
                s2_payload = self._s2_by_title(title_for_search)
                chosen3 = self._pick_best_s2(s2_payload, bi) if s2_payload else None
                if chosen3:
                    bi.hit_semanticscholar = True
                    self._fill_from_s2(bi, chosen3)
        
            # 3b) Unpaywall (last resort for abstract): try multiple landing pages
            if need_abs and not bi.abstract and doi:
                # email = os.environ.get("UNPAYWALL_EMAIL", "you@example.com")
                email = os.environ.get("UNPAYWALL_EMAIL", "ale.reyes.consuelo.ar@gmail.com")
                urls: List[str] = []
            
                # Unpaywall: best + all oa_locations
                upw = self._unpaywall_by_doi(doi, email)
                if upw:
                    best = (upw or {}).get("best_oa_location") or {}
                    if best:
                        urls += [best.get("url_for_landing_page") or "", best.get("url") or ""]
                    for loc in (upw.get("oa_locations") or []):
                        urls += [loc.get("url_for_landing_page") or "", loc.get("url") or ""]
            
                # Crossref: publisher landing page
                cr = self._crossref_by_doi(doi)
                if cr and isinstance(cr.get("message"), dict):
                    urls.append(cr["message"].get("URL") or "")
            
                # OpenAlex: host venue page
                oa = self._openalex_by_doi(doi)
                if oa and isinstance(oa.get("host_venue"), dict):
                    urls.append(oa["host_venue"].get("url") or "")
            
                # Try in order; take the first good snippet
                urls = [u for u in urls if u]
                snippet = self._best_oa_text_snippet(urls)
                if snippet:
                    self._set_if_empty(bi, "abstract", snippet, "unpaywall")

        # 4) Heuristic language fallback (only if still missing)
        if not bi.lang:
            text_for_lang = " ".join([bi.title or "", bi.abstract or ""]).strip()
            lang2 = self._heuristic_lang(text_for_lang) if text_for_lang else ""
            if lang2:
                self._set_if_empty(bi, "lang", lang2, "heuristic")

    def _make_resolver_note(self, bi: BibItem) -> str:
        hits = []
        if bi.hit_openalex: hits.append("OA")
        if bi.hit_crossref: hits.append("CR")
        if bi.hit_semanticscholar: hits.append("S2")
        fs: Dict[str, str] = getattr(bi, "field_sources", {})
        filled_pairs = []
        for fld in ("title", "year", "doi", "venue", "lang", "abstract", "keywords"):
            src = fs.get(fld)
            if src:
                filled_pairs.append(f"{fld}:{src[:2].upper()}")
        missing = []
        if not getattr(bi, "lang", ""): missing.append("lang")
        if not getattr(bi, "abstract", ""): missing.append("abstract")
        if not getattr(bi, "keywords", ""): missing.append("keywords")
        hit_str = ",".join(hits) if hits else "none"
        filled_str = "; ".join(filled_pairs) if filled_pairs else "-"
        missing_str = ",".join(missing) if missing else "-"
        win = bi.winner_source or "-"
        return f"{bi.local_id} resolved | hits:{hit_str} | winner:{win} | filled:{filled_str} | missing:{missing_str}"

    # ---- Fillers (now provenance-aware via _set_if_empty) ----
    def _fill_from_crossref(self, bi: BibItem, payload: Dict[str, Any]) -> None:
        self._ensure_audit_dicts(bi)
        msg = payload.get("message", {})
        src = "crossref"

        self._set_if_empty(bi, "doi", (msg.get("DOI") or ""), src)
        self._set_if_empty(bi, "title", (" ".join(msg.get("title", [])).strip()), src)
        self._set_if_empty(bi, "venue", ((msg.get("container-title") or [""])[0]), src)
        self._set_if_empty(bi, "volume", (msg.get("volume") or ""), src)
        self._set_if_empty(bi, "issue", (msg.get("issue") or ""), src)
        self._set_if_empty(bi, "pages", (msg.get("page") or ""), src)
        self._set_if_empty(bi, "publisher", (msg.get("publisher") or ""), src)
        year = self._year_from_crossref(msg)
        self._set_if_empty(bi, "year", year, src)
        self._set_if_empty(bi, "url", (msg.get("URL") or ""), src)

        # language with normalization to 2-letter (en, fr, …)
        cr_lang_raw = (msg.get("language") or "")
        if cr_lang_raw and not getattr(bi, "lang", ""):
            self._set_if_empty(bi, "lang", self._normalize_lang(cr_lang_raw), src)

        # Crossref type -> doc_type
        if not bi.doc_type:
            cr_type = (msg.get("type") or "").strip().lower()
            bi.doc_type = self._normalize_doc_type(cr_type, source=src)

        # authors
        auths = msg.get("author", [])
        if auths and (not bi.authors):
            names = [self._name(a) for a in auths]
            self._set_if_empty(bi, "authors", "; ".join(names), src)
            self._set_if_empty(bi, "first_author", (names[0] if names else ""), src)

        # abstract / keywords
        abs_txt = strip_html(msg.get("abstract") or "")
        self._set_if_empty(bi, "abstract", abs_txt, src)

        if isinstance(msg.get("subject"), list):
            kw = "; ".join((msg.get("subject") or [])[:12])
            self._set_if_empty(bi, "keywords", kw, src)

        bi.confidence = max(bi.confidence, 0.9)

    def _fill_from_openalex(self, bi: BibItem, data: Dict[str, Any]) -> None:
        self._ensure_audit_dicts(bi)
        src = "openalex"

        # uniformize "w"
        if "id" in data and data.get("display_name"):
            w = data
        elif "results" in data and data["results"]:
            w = data["results"][0]
        else:
            return

        self._set_if_empty(bi, "title", (w.get("display_name") or ""), src)
        self._set_if_empty(bi, "year", w.get("publication_year"), src)

        # IDs (doi/pmid/pmcid/arxiv)
        ids = (w.get("ids") or {})
        doi = (ids.get("doi") or ids.get("openalex") or "")
        if doi:
            doi = doi.replace("https://doi.org/", "")
        self._set_if_empty(bi, "doi", doi, src)
        if not bi.pmid and ids.get("pmid"):
            bi.pmid = str(ids.get("pmid"))
        if not bi.pmcid and ids.get("pmcid"):
            bi.pmcid = str(ids.get("pmcid"))
        if not bi.arxiv and ids.get("arxiv"):
            arx = str(ids.get("arxiv"))
            bi.arxiv = arx.replace("https://arxiv.org/abs/", "").replace("arXiv:", "")

        # venue/url
        host = (w.get("host_venue") or {})
        self._set_if_empty(bi, "venue", host.get("display_name", ""), src)
        self._set_if_empty(bi, "url", host.get("url", ""), src)

        # authors
        auths = (w.get("authorships") or [])
        if auths and not bi.authors:
            names = [a.get("author", {}).get("display_name", "") for a in auths]
            self._set_if_empty(bi, "authors", "; ".join([n for n in names if n]), src)
            self._set_if_empty(bi, "first_author", (names[0] if names else ""), src)

        # abstract
        abs_idx = w.get("abstract_inverted_index")
        if abs_idx and (not bi.abstract):
            bi.abstract = self._reconstruct_openalex_abstract(abs_idx)
            fs = getattr(bi, "field_sources")
            fs["abstract"] = src
            cnt = getattr(bi, "filled_by_source_counts")
            cnt[src] = cnt.get(src, 0) + 1

        # keywords (concepts)
        concepts = w.get("concepts") or []
        if (not bi.keywords) and concepts:
            names = [c.get("display_name", "") for c in concepts if c.get("display_name")]
            self._set_if_empty(bi, "keywords", "; ".join(names[:12]), src)

        # open access
        if bi.open_access is None:
            oa = (w.get("open_access") or {}).get("is_oa")
            if isinstance(oa, bool):
                bi.open_access = oa

        # doc_type from OpenAlex
        if not bi.doc_type:
            oa_type = (w.get("type") or "").strip().lower()
            bi.doc_type = self._normalize_doc_type(oa_type, source=src)

        bi.confidence = max(bi.confidence, 0.9)

    def _fill_from_s2(self, bi: BibItem, data: Dict[str, Any]) -> None:
        self._ensure_audit_dicts(bi)
        src = "semanticscholar"

        self._set_if_empty(bi, "title", data.get("title", ""), src)
        self._set_if_empty(bi, "year", data.get("year"), src)

        # IDs from externalIds
        ext = data.get("externalIds", {}) or {}
        self._set_if_empty(bi, "doi", (ext.get("DOI") or ""), src)
        if not bi.pmid and ext.get("PMID"):
            bi.pmid = str(ext.get("PMID"))
        if not bi.pmcid and ext.get("PMCID"):
            bi.pmcid = str(ext.get("PMCID"))
        if not bi.arxiv and (ext.get("ArXiv") or ext.get("ARXIV")):
            bi.arxiv = str(ext.get("ArXiv") or ext.get("ARXIV")).replace("arXiv:", "")

        # venue
        venue = data.get("venue") or (data.get("publicationVenue") or {}).get("name") or ""
        self._set_if_empty(bi, "venue", venue, src)

        # authors
        auths = data.get("authors", [])
        if auths and not bi.authors:
            names = [a.get("name", "") for a in auths]
            self._set_if_empty(bi, "authors", "; ".join([n for n in names if n]), src)
            self._set_if_empty(bi, "first_author", (names[0] if names else ""), src)

        # abstract / open access
        self._set_if_empty(bi, "abstract", (data.get("abstract") or ""), src)
        if bi.open_access is None and "isOpenAccess" in data:
            bi.open_access = bool(data.get("isOpenAccess"))

        # doc_type from publicationTypes
        if not bi.doc_type:
            pt = data.get("publicationTypes") or []
            s2_type = (pt[0] if pt else "").strip().lower()
            bi.doc_type = self._normalize_doc_type(s2_type, source=src)

        bi.confidence = max(bi.confidence, 0.8)

    # ---- pickers ----
    def _pick_best_openalex(self, payload: Dict[str, Any], bi: BibItem) -> Optional[Dict[str, Any]]:
        if not payload:
            return None
        res = payload.get("results") or []
        if not res:
            return None
        if FUZZY_OK and fuzz and bi.title:
            scored = []
            for w in res:
                t = w.get("display_name") or ""
                scored.append((fuzz.token_set_ratio(bi.title, t), w))
            scored.sort(reverse=True, key=lambda t: t[0])
            return scored[0][1] if scored else (res[0] if res else None)
        return res[0]

    def _pick_best_crossref(self, payload: Dict[str, Any], bi: BibItem) -> Optional[Dict[str, Any]]:
        if not payload:
            return None
        items = (payload.get("message") or {}).get("items") or []
        if not items:
            return None
        if FUZZY_OK and fuzz and bi.title:
            scored = []
            for it in items:
                t = " ".join(it.get("title", [])).strip()
                scored.append((fuzz.token_set_ratio(bi.title, t), it))
            scored.sort(reverse=True, key=lambda t: t[0])
            return scored[0][1] if scored else (items[0] if items else None)
        return items[0]

    def _pick_best_s2(self, payload: Dict[str, Any], bi: BibItem) -> Optional[Dict[str, Any]]:
        if not payload:
            return None
        data = payload.get("data") or []
        if not data:
            return None
        if FUZZY_OK and fuzz and bi.title:
            scored = []
            for it in data:
                t = it.get("title", "")
                scored.append((fuzz.token_set_ratio(bi.title, t), it))
            scored.sort(reverse=True, key=lambda t: t[0])
            return scored[0][1] if scored else (data[0] if data else None)
        return data[0]

    # ---- misc ----
    def _year_from_crossref(self, msg: Dict[str, Any]) -> Optional[int]:
        for key in ("published-print", "published-online", "created"):
            part = msg.get(key)
            if not isinstance(part, dict):
                continue
            dp = part.get("date-parts")
            if isinstance(dp, list) and dp and isinstance(dp[0], list) and dp[0]:
                try:
                    return int(dp[0][0])
                except Exception:
                    pass
        return None

    def _name(self, a: Dict[str, Any]) -> str:
        g = (a or {}).get("given", "").strip()
        f = (a or {}).get("family", "").strip()
        if g and f:
            return f"{f}, {g}"
        return f or g or ""

    def _reconstruct_openalex_abstract(self, inverted_idx: Dict[str, List[int]]) -> str:
        if not isinstance(inverted_idx, dict):
            return ""
        pairs = []
        for tok, poss in inverted_idx.items():
            for p in poss:
                pairs.append((p, tok))
        if not pairs:
            return ""
        pairs.sort(key=lambda t: t[0])
        tokens = [t[1] for t in pairs]
        return re.sub(r"\s+", " ", " ".join(tokens)).strip()

    # Normalize doc_type values from different sources to a compact set
    def _normalize_doc_type(self, raw: str, source: str) -> str:
        s = (raw or "").strip().lower()
        if not s:
            return ""
        # Common mappings across CR/OA/S2
        mapping = {
            # generic
            "journal-article": "article",
            "article": "article",
            "review": "article",
            "letter": "article",
            "editorial": "article",
            # conference
            "proceedings-article": "conference",
            "conference": "conference",
            "conference-paper": "conference",
            "conferenceproceedings": "conference",
            # books/chapters
            "book-chapter": "chapter",
            "chapter": "chapter",
            "book": "book",
            "monograph": "book",
            # theses/reports/preprints
            "dissertation": "thesis",
            "thesis": "thesis",
            "report": "report",
            "posted-content": "preprint",
            "preprint": "preprint",
            # fallbacks
            "reference-entry": "other",
            "other": "other",
        }
        # S2 can return capitalized tokens like "BookChapter", "JournalArticle"
        s2_map = {
            "bookchapter": "chapter",
            "journalarticle": "article",
            "conference": "conference",
            "book": "book",
            "thesis": "thesis",
            "preprint": "preprint",
            "report": "report",
        }
        # unify token (remove non-alnum)
        token = re.sub(r"[^a-z]", "", s)
        if source == "semanticscholar":
            return s2_map.get(token, mapping.get(s, "other"))
        return mapping.get(s, s2_map.get(token, "other"))

    # ---- language helpers ----
    def _normalize_lang(self, code: str) -> str:
        """Return 2-letter lowercase language if possible (e.g., 'en-US' -> 'en')."""
        if not code:
            return ""
        code = code.strip().lower()
        # handle typical tags like 'en-us', 'fr-ca'
        m = re.match(r"([a-z]{2})\b", code)
        return m.group(1) if m else (code[:2] if len(code) >= 2 else code)

    def _heuristic_lang(self, text: str) -> str:
        """Very light fallback using langdetect if available; else empty string."""
        if not text:
            return ""
        if not _LANGDETECT_OK or not _ld_detect:
            return ""
        try:
            lg = _ld_detect(text)
            return self._normalize_lang(lg or "")
        except Exception:
            return ""
        
        # ---- Unpaywall ----
    def _unpaywall_by_doi(self, doi: str, email: str) -> Optional[Dict[str, Any]]:
        """Fetch Unpaywall record. Requires a valid email; cached."""
        if not (REQ_OK and requests):
            return None
        if not email or "@" not in email:
            return None
        key = f"upw_{norm_key(doi)}"
        cached = self._load_cache(key)
        if cached:
            return cached
        url = f"https://api.unpaywall.org/v2/{requests.utils.quote(doi)}"
        try:
            r = requests.get(url, params={"email": email}, timeout=12)
            if r.status_code == 200:
                data = r.json()
                self._save_cache(key, data)
                return data
        except Exception:
            return None
        return None

    def _best_oa_text_snippet(self, urls: List[str]) -> str:
        """
        Try multiple landing-page URLs (Unpaywall + Crossref + OpenAlex).
        Heuristics:
          - prefer meta descriptions/DC/OG
          - else first <p>
          - quality check via _snippet_quality_ok
        """
        if not (REQ_OK and requests) or not urls:
            return ""
        seen = set()
        for u in urls:
            u = (u or "").strip()
            if not u or u in seen:
                continue
            seen.add(u)
            try:
                r = requests.get(u, timeout=10, headers={"User-Agent": "refx/1.0"})
                if r.status_code != 200 or not r.text:
                    continue
                html = r.text[:300_000]
                # meta first
                meta_candidates = self._html_meta_extract_all(html)
                for cand in meta_candidates:
                    cand = (cand or "").strip()
                    if self._snippet_quality_ok(cand):
                        return cand
                # fallback: first <p>
                p = re.search(r"<p[^>]*>(.*?)</p>", html, flags=re.IGNORECASE | re.DOTALL)
                if p:
                    cand = strip_html(p.group(1)).strip()
                    if self._snippet_quality_ok(cand):
                        return cand
            except Exception:
                continue
        return ""

    def _snippet_quality_ok(self, txt: str) -> bool:
        """
        Guardrails to avoid boilerplate/teasers:
          - length between 240 and 4000 chars (relaxed lower bound vs. marketing blurbs)
          - at least 2 sentence boundaries
          - reject common boilerplate/cookie banners/TOC blurbs
          - reject 'references only' / citation lists
        """
        if not txt:
            return False
        # Basic sanitation
        t = re.sub(r"\s+", " ", txt).strip()
        if len(t) < 240 or len(t) > 4000:
            return False
        # Sentence count
        sent_cnt = len(re.findall(r"[.!?]\s", t))
        if sent_cnt < 2:
            return False
        # Boilerplate/banlist
        low = t.lower()
        ban = (
            "cookie", "accept all cookies", "we use cookies",
            "supplementary material", "use of this website",
            "table of contents", "copyright ©", "all rights reserved",
            "sign in", "purchase access", "add to cart", "metrics",
            "licensee", "springer nature", "wiley online library",
            "permissions", "references", "cited by"
        )
        if any(b in low for b in ban):
            return False
        # Heuristic: avoid paragraphs that look like mostly references/citations
        if re.search(r"\(\d{4}\)|\[\d+\](\s*,\s*\[\d+\])+", t):
            return False
        return True
    
    
    def _html_meta_extract_all(self, html: str) -> List[str]:
        """
        Return multiple meta-description-like candidates, longest first
        (strip HTML/entities). We’ll quality-check them upstream.
        """
        if not html:
            return []
        html = html[:300_000]
        # Collect a set to avoid duplicates
        out: List[str] = []
        pats = [
            r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']',
            r'<meta\s+property=["\']og:description["\']\s+content=["\'](.*?)["\']',
            r'<meta\s+name=["\']dc\.description["\']\s+content=["\'](.*?)["\']',
            r'<meta\s+name=["\']dcterms\.abstract["\']\s+content=["\'](.*?)["\']',
            r'<meta\s+name=["\']citation_abstract["\']\s+content=["\'](.*?)["\']',
            r'<meta\s+property=["\']article:description["\']\s+content=["\'](.*?)["\']',
            r'<meta\s+name=["\']twitter:description["\']\s+content=["\'](.*?)["\']',
            r'<meta\s+name=["\']prism:teaser["\']\s+content=["\'](.*?)["\']',
        ]
        for pat in pats:
            for m in re.finditer(pat, html, flags=re.IGNORECASE | re.DOTALL):
                txt = strip_html(m.group(1) or "").strip()
                if txt:
                    out.append(txt[:2000])
        # de-dup while preserving order; sort by length desc (longer often better)
        seen = set()
        uniq = []
        for t in out:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        uniq.sort(key=len, reverse=True)
        return uniq

    def _html_meta_extract(self, html: str) -> str:
        cands = self._html_meta_extract_all(html)
        return cands[0] if cands else ""

# =====================================================================================
# Reference fetching per X item
# =====================================================================================

class RefFetcher:
    def __init__(self, logger: LoggerProto | None = None, cache_dir: str | None = None):
        self.logger = logger or NullLogger()
        self.cache_dir = cache_dir or os.path.join(os.path.expanduser("~"), ".refx_cache", "refs")
        os.makedirs(self.cache_dir, exist_ok=True)

        # 🔧 Native full-resolution for fetched refs
        # Use a dedicated meta cache folder to share with X-resolution
        meta_cache = os.path.join(os.path.expanduser("~"), ".refx_cache", "meta")
        self.resolver = MetaResolver(logger=self.logger, cache_dir=meta_cache)

    # cache
    def _cache_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"{key}.json")

    def _load_cache(self, key: str) -> Optional[Dict[str, Any]]:
        p = self._cache_path(key)
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def _save_cache(self, key: str, payload: Dict[str, Any]) -> None:
        try:
            with open(self._cache_path(key), "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except Exception:
            pass

    def fetch_for_item(
        self,
        x_item: BibItem,
        cancel: CancellationToken,
        progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> List[BibItem]:
        if cancel.cancelled:
            return []
        _wait_if_paused(cancel)
        refs: List[BibItem] = []
        if not x_item.doi:
            _maybe_emit(progress, {"phase": "fetch", "event": "skip_no_doi", "parent": x_item.local_id or "", "ts": now_iso()})
            return refs
        _maybe_emit(progress, {"phase": "fetch", "event": "start", "parent": x_item.local_id or "", "ts": now_iso(), "refs_found": 0})

        # 1) OpenAlex (preferred)
        self.logger.log(f"Fetch references via OpenAlex for {x_item.local_id} (DOI:{x_item.doi})")
        oa = self._oa_work_by_doi(x_item.doi)
        if oa and oa.get("referenced_works"):
            works = oa["referenced_works"][:]
            batch_size = 20
            for i in range(0, len(works), batch_size):
                if cancel.cancelled:
                    break
                _wait_if_paused(cancel)
                chunk = works[i : i + batch_size]
                hydrated = self._oa_hydrate_chunk(chunk, x_item)
                refs += hydrated
                _maybe_emit(progress, {
                    "phase": "fetch",
                    "event": "hydrated_chunk",
                    "parent": x_item.local_id or "",
                    "count": len(hydrated),
                    "refs_found": len(refs),
                    "source": "openalex",
                    "ts": now_iso(),
                })

        # 2) Crossref fallback (only if OA empty)
        if not refs and not cancel.cancelled:
            self.logger.log(f"Fallback: Crossref reference list for {x_item.local_id}")
            cr = self._cr_by_doi(x_item.doi)
            if cr:
                added = self._cr_extract_refs(cr, x_item)
                refs += added
                _maybe_emit(progress, {
                    "phase": "fetch",
                    "event": "fallback_added",
                    "parent": x_item.local_id or "",
                    "count": len(added),
                    "refs_found": len(refs),
                    "source": "crossref",
                    "ts": now_iso(),
                })

        # 3) Semantic Scholar fallback (only if still empty)
        if not refs and not cancel.cancelled:
            self.logger.log(f"Fallback: Semantic Scholar references for {x_item.local_id}")
            added = self._s2_refs_by_doi(x_item.doi, x_item)
            refs += added
            _maybe_emit(progress, {
                "phase": "fetch",
                "event": "fallback_added",
                "parent": x_item.local_id or "",
                "count": len(added),
                "refs_found": len(refs),
                "source": "semanticscholar",
                "ts": now_iso(),
            })

        # ✅ Native enrichment: resolve metadata for fetched refs (same as X)
        if refs and not cancel.cancelled:
            total = len(refs)
            self.logger.log(f"Resolve metadata for {total} fetched ref(s) of {x_item.local_id} …")
            for i, r in enumerate(refs, 1):
                if cancel.cancelled:
                    break
                _wait_if_paused(cancel)
                # propagate cancel/pause, progress is optional
                self.resolver.resolve_item(r, cancel, progress=None)
                if (i % 20 == 0) or (i == total):
                    self.logger.log(f"Resolved {i}/{total} ref(s) for {x_item.local_id}")
                    _maybe_emit(progress, {
                        "phase": "fetch",
                        "event": "resolved_refs_progress",
                        "parent": x_item.local_id or "",
                        "resolved": i,
                        "total": total,
                        "ts": now_iso(),
                    })
        
        # Final signal
        _maybe_emit(progress, {
            "phase": "fetch",
            "event": "done",
            "parent": x_item.local_id or "",
            "refs_found": len(refs),
            "ts": now_iso(),
        })
        return refs


    # ---- OpenAlex helpers ----
    def _oa_work_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        if not (REQ_OK and requests):
            return None
        key = f"oa_work_{norm_key(doi)}"
        cached = self._load_cache(key)
        if cached:
            return cached
        url = "https://api.openalex.org/works/https://doi.org/" + doi
        try:
            r = requests.get(url, timeout=15)
            self.logger.log(f"OpenAlex work status={r.status_code}")
            if r.status_code == 200:
                data = r.json()
                self._save_cache(key, data)
                return data
        except Exception:
            return None
        return None

    def _oa_hydrate_chunk(self, refs_ids: List[str], parent: BibItem) -> List[BibItem]:
        out: List[BibItem] = []
        if not (REQ_OK and requests) or not refs_ids:
            return out
        url = "https://api.openalex.org/works"
        params = {"filter": f"openalex:{'|'.join(refs_ids)}", "per_page": len(refs_ids)}
        try:
            r = requests.get(url, params=params, timeout=20)
            self.logger.log(f"OpenAlex hydrate {len(refs_ids)} ids → status={r.status_code}")
            if r.status_code == 200:
                data = r.json()
                for w in data.get("results", []):
                    out.append(self._oa_to_bib(w, parent))
        except Exception:
            pass
        return out

    def _oa_to_bib(self, w: Dict[str, Any], parent: BibItem) -> BibItem:
        # local tiny helper for OA abstract
        def _reconstruct(abs_idx: Dict[str, List[int]]) -> str:
            if not isinstance(abs_idx, dict):
                return ""
            pairs = []
            for tok, poss in abs_idx.items():
                for p in poss:
                    pairs.append((p, tok))
            if not pairs:
                return ""
            pairs.sort(key=lambda t: t[0])
            return " ".join([t[1] for t in pairs])

        lid = f"{parent.local_id}.R000"  # temp; reindexed by caller
        ids = w.get("ids") or {}
        doi = (ids.get("doi") or "").replace("https://doi.org/", "")
        title = w.get("display_name") or ""
        venue = (w.get("host_venue") or {}).get("display_name", "")
        year = w.get("publication_year")
        authorships = w.get("authorships") or []
        names = [a.get("author", {}).get("display_name", "") for a in authorships]
        first_auth = names[0] if names else ""
        abs_idx = w.get("abstract_inverted_index") or {}
        abstract = _reconstruct(abs_idx) if abs_idx else ""
        concepts = w.get("concepts") or []
        keywords = "; ".join([c.get("display_name", "") for c in concepts if c.get("display_name")][:12]) if concepts else ""
        oa_flag = (w.get("open_access") or {}).get("is_oa")
        open_access = bool(oa_flag) if isinstance(oa_flag, bool) else None

        return BibItem(
            local_id=lid,
            source_key=norm_key(doi or title),
            title=title_norm(title),
            authors="; ".join(names),
            first_author=first_auth,
            year=year,
            doi=doi,
            venue=venue,
            url=(w.get("host_venue") or {}).get("url", ""),
            abstract=abstract,
            keywords=keywords,
            open_access=open_access,
            confidence=0.8,
            status="resolved",
            provenance="openalex",
            last_checked=now_iso(),
            parents=[parent.local_id],
        )

    # ---- Crossref helpers ----
    def _cr_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        if not (REQ_OK and requests):
            return None
        key = f"cr_work_{norm_key(doi)}"
        cached = self._load_cache(key)
        if cached:
            return cached
        url = f"https://api.crossref.org/works/{requests.utils.quote(doi)}"
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                data = r.json()
                self._save_cache(key, data)
                return data
        except Exception:
            return None
        return None

    def _cr_extract_refs(self, payload: Dict[str, Any], parent: BibItem) -> List[BibItem]:
        out: List[BibItem] = []
        msg = payload.get("message", {})
        arr = msg.get("reference") or []
        for idx, it in enumerate(arr, 1):
            title = title_norm(
                it.get("article-title")
                or it.get("series-title")
                or it.get("volume-title")
                or it.get("unstructured")
                or ""
            )
            doi = (it.get("DOI") or it.get("doi") or "").strip()
            year = None
            ytxt = it.get("year") or it.get("issued") or ""
            m = YEAR_PAT.search(str(ytxt))
            if m:
                try:
                    year = int(m.group(0))
                except Exception:
                    year = None
            auth = it.get("author") or ""
            first_auth = auth.split(",")[0].strip() if auth else ""
            lid = f"{parent.local_id}.R{str(idx).zfill(3)}"
            out.append(
                BibItem(
                    local_id=lid,
                    source_key=norm_key(doi or title),
                    title=title,
                    authors=auth,
                    first_author=first_auth,
                    year=year,
                    doi=doi,
                    venue=it.get("journal-title") or "",
                    pages=it.get("first-page") or "",
                    confidence=0.6 if not doi else 0.8,
                    status="resolved" if (title or doi) else "ambiguous",
                    provenance="crossref",
                    last_checked=now_iso(),
                    parents=[parent.local_id],
                )
            )
        return out

    # ---- Semantic Scholar helpers ----
    def _s2_refs_by_doi(self, doi: str, parent: BibItem) -> List[BibItem]:
        if not (REQ_OK and requests):
            return []
        key = f"s2_refs_{norm_key(doi)}"
        cached = self._load_cache(key)
        if cached is None:
            url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
            fields = "references.title,references.year,references.authors.name,references.externalIds,references.venue,references.abstract"
            try:
                r = requests.get(url, params={"fields": fields}, timeout=20)
                if r.status_code == 200:
                    cached = r.json()
                    self._save_cache(key, cached)
                else:
                    cached = {}
            except Exception:
                cached = {}
        return self._s2_payload_to_bibs(cached, parent)

    def _s2_payload_to_bibs(self, payload: Dict[str, Any], parent: BibItem) -> List[BibItem]:
        out: List[BibItem] = []
        refs = (payload or {}).get("references") or []
        for i, it in enumerate(refs, 1):
            ext = it.get("externalIds") or {}
            doi = (ext.get("DOI") or "").strip()
            names = [a.get("name", "") for a in (it.get("authors") or []) if a.get("name")]
            first = names[0] if names else ""
            out.append(
                BibItem(
                    local_id=f"{parent.local_id}.R{i:03d}",
                    source_key=norm_key(doi or (it.get("title") or "")),
                    title=title_norm(it.get("title") or ""),
                    authors="; ".join(names),
                    first_author=first,
                    year=it.get("year"),
                    doi=doi,
                    venue=it.get("venue") or "",
                    abstract=(it.get("abstract") or ""),
                    confidence=0.7 if doi else 0.5,
                    status="resolved" if (doi or it.get("title")) else "ambiguous",
                    provenance="semanticscholar",
                    last_checked=now_iso(),
                    parents=[parent.local_id],
                )
            )
        return out

# =====================================================================================
# Aggregation / dedup → vector A
# =====================================================================================

def dedup_items(items: List[BibItem]) -> Tuple[List[BibItem], Dict[str, List[str]]]:
    """Return (A_items, parents_map) where parents_map maps A.local_id → list of X parents."""
    by_doi: Dict[str, BibItem] = {}
    pool: List[BibItem] = []
    parents_map: Dict[str, List[str]] = {}

    # First pass: DOI-based
    for it in items:
        if it.doi:
            k = it.doi.lower()
            if k not in by_doi:
                by_doi[k] = it
                pool.append(it)
            else:
                base = by_doi[k]
                base.parents = sorted(list(set((base.parents or []) + (it.parents or []))))
        else:
            pool.append(it)

    # Second pass: title+first_author+year fuzzy
    result: List[BibItem] = []
    used = [False] * len(pool)
    for i, it in enumerate(pool):
        if used[i]:
            continue
        used[i] = True
        group_parents = list(it.parents or [])
        for j in range(i + 1, len(pool)):
            if used[j]:
                continue
            jt = pool[j]
            if _maybe_same_work(it, jt):
                used[j] = True
                group_parents += (jt.parents or [])
                # prefer richer metadata
                if (not it.abstract) and jt.abstract:
                    it.abstract = jt.abstract
                if (not it.keywords) and jt.keywords:
                    it.keywords = jt.keywords
                if it.open_access is None and jt.open_access is not None:
                    it.open_access = jt.open_access
                if (not it.venue) and jt.venue:
                    it.venue = jt.venue
                if (not it.url) and jt.url:
                    it.url = jt.url
        it.parents = sorted(list(set(group_parents)))
        result.append(it)

    # Assign A IDs and parents map
    for idx, it in enumerate(result, 1):
        it.local_id = f"A{str(idx).zfill(3)}"
        parents_map[it.local_id] = list(it.parents or [])

    return result, parents_map


def _maybe_same_work(a: BibItem, b: BibItem) -> bool:
    if a.doi and b.doi:
        return a.doi.lower() == b.doi.lower()
    if a.year and b.year and abs(a.year - b.year) > 1:
        return False
    if a.first_author and b.first_author and norm_key(a.first_author) != norm_key(b.first_author):
        return False
    ta = norm_key(a.title)
    tb = norm_key(b.title)
    if not ta or not tb:
        return False
    if FUZZY_OK and fuzz:
        return fuzz.token_set_ratio(a.title, b.title) >= 90
    return ta == tb

# =====================================================================================
# Export helpers
# =====================================================================================

class Exporter:
    def __init__(self, logger: LoggerProto | None = None):
        self.logger = logger or NullLogger()

    def to_csv(self, path: str, rows: List[BibItem]) -> None:
        if PANDAS_OK and pd is not None:
            df = pd.DataFrame([r.to_row() for r in rows])
            df.to_csv(path, index=False)
        else:
            with open(path, "w", encoding="utf-8", newline="") as f:
                # Compute a stable header from BibItem fields
                header = list(BibItem(local_id="", source_key="").to_row().keys())
                w = csv.DictWriter(f, fieldnames=header)
                w.writeheader()
                for r in rows:
                    w.writerow(r.to_row())
        self.logger.log(f"Saved CSV → {path}")

    def to_meta_sources_csv(self, path: str, rows: List[BibItem]) -> None:
        """
        Export a compact audit of metadata connectivity & provenance for each X item.
        Columns: local_id, doi, title, hit_openalex, hit_crossref, hit_semanticscholar,
                 match_strategy, winner_source, confidence, status
        Plus: filled_from (title/lang/abstract), missing_fields, resolver_notes
        """
        def row(b: BibItem) -> Dict[str, Any]:
            fs: Dict[str, str] = getattr(b, "field_sources", {}) or {}
            missing = []
            if not getattr(b, "lang", ""): missing.append("lang")
            if not getattr(b, "abstract", ""): missing.append("abstract")
            if not getattr(b, "keywords", ""): missing.append("keywords")
            return {
                "local_id": b.local_id,
                "doi": b.doi,
                "title": b.title,
                "hit_openalex": b.hit_openalex,
                "hit_crossref": b.hit_crossref,
                "hit_semanticscholar": b.hit_semanticscholar,
                "match_strategy": b.match_strategy,
                "winner_source": b.winner_source,
                "filled_title_from": fs.get("title", ""),
                "filled_lang_from": fs.get("lang", ""),
                "filled_abstract_from": fs.get("abstract", ""),
                "filled_keywords_from": fs.get("keywords", ""),
                "missing_fields": ",".join(missing) if missing else "",
                "confidence": b.confidence,
                "status": b.status,
                "resolver_notes": getattr(b, "resolver_notes", ""),
            }

        if PANDAS_OK and pd is not None:
            df = pd.DataFrame([row(r) for r in rows])
            df.to_csv(path, index=False)
        else:
            with open(path, "w", encoding="utf-8", newline="") as f:
                header = [
                    "local_id", "doi", "title",
                    "hit_openalex", "hit_crossref", "hit_semanticscholar",
                    "match_strategy", "winner_source",
                    "filled_title_from", "filled_lang_from", "filled_abstract_from", "filled_keywords_from",
                    "missing_fields",
                    "confidence", "status",
                    "resolver_notes",
                ]
                w = csv.DictWriter(f, fieldnames=header)
                w.writeheader()
                for r in rows:
                    w.writerow(row(r))
        self.logger.log(f"Saved meta-sources CSV → {path}")
