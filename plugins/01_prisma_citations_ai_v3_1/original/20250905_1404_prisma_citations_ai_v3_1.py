# -*- coding: utf-8 -*-
"""
Created on Thu Sep  4 17:22:53 2025

@author: alere
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PRISMA Citations Extractor — AI v3.1
------------------------------------
Polish & UX pass:
- Numbered output lists:
  • Numeric style → "1. [13]", "2. [15]", ...
  • Author–year → "1. Smith et al., 2022", ... (sortable)
- Progress ribbon with step timings + always-on Event Log (and optional file logging)
- Cancel/Stop button (cooperative cancel; aborts between steps, ignores long in-flight calls)
- Preview tab with thumbnails of processed pages
- Sorting controls for author–year (Extraction order / Year ↑ / Year ↓ / Author A→Z)
- Copy Numbered List button

Setup
-----
pip install -r requirements_ai_v3.txt
$env:OPENAI_API_KEY="sk-..."
python prisma_citations_ai_v3_1.py
"""

import os
import re
import io
import time
import base64
import threading
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime

# UI
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# PDF & imaging
import fitz  # PyMuPDF
from PIL import Image, ImageTk

# OCR
try:
    import pytesseract
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

# OpenAI
try:
    from openai import OpenAI
    OPENAI_OK = True
except Exception:
    OpenAI = None
    OPENAI_OK = False

# Fuzzy matching
try:
    from rapidfuzz import fuzz
    FUZZY_OK = True
except Exception:
    FUZZY_OK = False

DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

# ---------------- Utilities ----------------

DASHES = {"–": "-", "—": "-", "-": "-", "‒": "-"}

def normalize_dashes(text: str) -> str:
    for k, v in DASHES.items():
        text = text.replace(k, v)
    return text

def page_to_base64_png(doc, page_index: int, dpi: int = 240) -> str:
    page = doc.load_page(page_index)
    pix = page.get_pixmap(dpi=dpi)
    b = pix.tobytes("png")
    return "data:image/png;base64," + base64.b64encode(b).decode("ascii")

# ---------------- Parse References ----------------

NUM_REF_LINE_PATS = [
    re.compile(r"^\s*\[(\d{1,3})\]\s*(.+)$"),
    re.compile(r"^\s*(\d{1,3})\.\s+(.+)$"),
    re.compile(r"^\s*(\d{1,3})\)\s+(.+)$"),
]

YEAR_PAT = re.compile(r"(19|20)\d{2}")

@dataclass
class RefEntry:
    idx: Optional[int]     # numeric index if present
    first_author: str
    year: Optional[int]
    title: str
    raw: str

# ---------------- Logging ----------------

class CancellationToken:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

class UiLogger:
    def __init__(self, text_widget: tk.Text, log_to_file_var: tk.BooleanVar, logs_dir: str, tk_root: tk.Tk):
        self.text_widget = text_widget
        self.log_to_file_var = log_to_file_var
        self.logs_dir = logs_dir
        self.root = tk_root
        self.file_handle = None
        os.makedirs(self.logs_dir, exist_ok=True)

    def _open_file_if_needed(self):
        if self.file_handle is None and self.log_to_file_var.get():
            fname = datetime.now().strftime("%Y-%m-%d_%H%M%S.log")
            self.file_handle = open(os.path.join(self.logs_dir, fname), "w", encoding="utf-8")

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        def _append():
            self.text_widget.insert(tk.END, line)
            self.text_widget.see(tk.END)
        self.root.after(0, _append)
        if self.log_to_file_var.get():
            self._open_file_if_needed()
            try:
                self.file_handle.write(line)
                self.file_handle.flush()
            except Exception:
                pass

    def close(self):
        try:
            if self.file_handle:
                self.file_handle.close()
        except Exception:
            pass
        self.file_handle = None

# ---------------- PDF helpers ----------------

def extract_pdf_texts(pdf_path: str) -> Tuple[str, List[str]]:
    doc = fitz.open(pdf_path)
    try:
        page_texts = [p.get_text("text") for p in doc]
        return "\n".join(page_texts), page_texts
    finally:
        doc.close()

def find_references_block(full_text: str) -> str:
    m = re.search(r"\bReferences\b|\bBibliography\b|\bWorks Cited\b", full_text, flags=re.IGNORECASE)
    if m:
        return full_text[m.start():]
    start = int(len(full_text) * 0.65)
    return full_text[start:]

def parse_numeric_references(block: str) -> Dict[int, RefEntry]:
    lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
    mapping: Dict[int, RefEntry] = {}
    current_idx: Optional[int] = None
    buf: List[str] = []

    def flush():
        nonlocal current_idx, buf
        if current_idx is None or not buf:
            return
        raw = " ".join(s.strip() for s in buf).strip()
        first_author = ""
        year = None
        title = ""
        m_year = YEAR_PAT.search(raw)
        if m_year:
            year = int(m_year.group(0))
        m_auth = re.match(r"\s*([A-Z][\w\-\']+)", raw)
        if m_auth:
            first_author = m_auth.group(1)
        if m_year:
            tail = raw[m_year.end():]
            tail = tail.replace(").", ".")
            parts = tail.split(". ")
            if parts:
                title = parts[0].strip(" .;:")
        mapping[current_idx] = RefEntry(current_idx, first_author, year, title, raw)
        current_idx, buf = None, []

    for ln in lines:
        matched = False
        for pat in NUM_REF_LINE_PATS:
            m = pat.match(ln)
            if m:
                if buf:
                    flush()
                current_idx = int(m.group(1))
                buf = [m.group(2).strip()]
                matched = True
                break
        if not matched:
            if current_idx is not None:
                buf.append(ln)
    flush()
    return mapping

AUTHLINE_START = re.compile(r"^\s*([A-Z][\w\-\']+(?:\s+[A-Z][\w\-\']+)*)\,")

def parse_author_year_references(block: str) -> List[RefEntry]:
    lines_raw = [ln.rstrip() for ln in block.splitlines()]
    if lines_raw and re.match(r"^\s*References\b", lines_raw[0], flags=re.I):
        lines_raw = lines_raw[1:]

    entries: List[RefEntry] = []
    buf: List[str] = []

    def flush_buf():
        nonlocal buf, entries
        if not buf:
            return
        raw = " ".join(s.strip() for s in buf if s.strip())
        if not raw:
            buf = []
            return
        m_auth = AUTHLINE_START.match(buf[0])
        first_author = m_auth.group(1).split()[0] if m_auth else ""
        m_year = YEAR_PAT.search(raw)
        year = int(m_year.group(0)) if m_year else None
        title = ""
        if m_year:
            tail = raw[m_year.end():]
            tail = tail.lstrip("). ,;:-")
            parts = tail.split(". ")
            if parts:
                title = parts[0].strip(" .;:")
        entries.append(RefEntry(None, first_author, year, title, raw))
        buf = []

    for ln in lines_raw:
        if AUTHLINE_START.match(ln):
            if buf:
                flush_buf()
            buf = [ln]
        else:
            if ln.strip() == "" and buf:
                flush_buf()
                buf = []
            else:
                if buf:
                    buf.append(ln)
    flush_buf()
    return entries

def detect_reference_style(full_text: str) -> str:
    block = find_references_block(full_text)
    numeric = parse_numeric_references(block)
    if len(numeric) >= 3:
        return "numeric"
    auth_entries = parse_author_year_references(block)
    if len(auth_entries) >= 5:
        return "author_year"
    return "unknown"

# ---------------- Included list extraction (AI + OCR) ----------------

KEYWORDS_BASE = [
    "selected articles", "articles selected", "studies selected", "selected and analyzed",
    "selected and analysed", "included studies", "studies included",
    "table 1", "table i", "prisma", "flow diagram",
    "eligibility", "screening", "inclusion"
]
APPENDIX_TERMS = ["appendix", "supplementary", "supplement"]

SINGLE_BRACKET_NUM = re.compile(r"\[(\d{1,3})\]")
RANGE_INSIDE = re.compile(r"\[(\d{1,3})\s*[–-]\s*(\d{1,3})\]")
RANGE_TWO_BRACKETS = re.compile(r"\[(\d{1,3})\]\s*[–-]\s*\[(\d{1,3})\]")

def harvest_bracket_numbers(text: str) -> Tuple[List[int], List[Tuple[int,int]]]:
    text = normalize_dashes(text)
    found: List[int] = []
    pairs: List[Tuple[int,int]] = []
    for m in RANGE_TWO_BRACKETS.finditer(text):
        a, b = int(m.group(1)), int(m.group(2))
        pairs.append((a,b))
        found += list(range(min(a,b), max(a,b)+1))
    for m in RANGE_INSIDE.finditer(text):
        a, b = int(m.group(1)), int(m.group(2))
        pairs.append((a,b))
        found += list(range(min(a,b), max(a,b)+1))
    for m in SINGLE_BRACKET_NUM.finditer(text):
        found.append(int(m.group(1)))
    found = sorted(set(found))
    return found, pairs

def guess_candidate_pages(pdf_path: str, include_appendix: bool, logger: Optional[UiLogger]=None) -> List[int]:
    keywords = KEYWORDS_BASE + (APPENDIX_TERMS if include_appendix else [])
    doc = fitz.open(pdf_path)
    try:
        hits = []
        for i, page in enumerate(doc):
            t = page.get_text("text").lower()
            if any(kw in t for kw in keywords):
                hits.append(i)
        expanded = set(hits)
        for h in hits:
            for j in [h-1, h+1]:
                if 0 <= j < len(doc):
                    expanded.add(j)
        if not expanded:
            expanded = set(range(min(4, len(doc))))
        pages = sorted(expanded)
        if logger:
            logger.log(f"Candidate pages: {[p+1 for p in pages]}")
        return pages
    finally:
        doc.close()

def ai_extract_included(pdf_path: str, pages: Optional[List[int]], style_hint: str,
                        model: str, cancel: CancellationToken, logger: UiLogger) -> Dict[str, Any]:
    """Return dict with keys: detected_style, declared_included_n, included_numbers, included_author_year, used_pages"""
    if not OPENAI_OK:
        raise RuntimeError("OpenAI SDK not installed (pip install openai).")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set.")

    if cancel.cancelled:
        return {"detected_style": style_hint, "declared_included_n": None, "included_numbers": [], "included_author_year": [], "used_pages": []}

    doc = fitz.open(pdf_path)
    try:
        imgs = [page_to_base64_png(doc, i) for i in pages]
        page_texts = [doc.load_page(i).get_text("text") for i in pages]

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

        system = (
            "You read scientific review PDF pages (images + optional text) and extract the list of "
            "PRISMA 'Selected/Included' studies. First detect the citation style used by the paper: "
            "'numeric' (Vancouver-style numbers like [27]), 'author_year' (Author, Year), or 'superscript'. "
            "Then return ONLY structured data."
        )

        tool_schema = {
            "type": "function",
            "function": {
                "name": "return_included",
                "description": "Return included/selected list for PRISMA.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "detected_style": {"type": "string", "enum": ["numeric", "author_year", "superscript"]},
                        "declared_included_n": {"type": "integer"},
                        "included_numbers": {"type": "array", "items": {"type":"integer"}},
                        "included_author_year": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "first_author": {"type":"string"},
                                    "year": {"type":"integer"},
                                    "title_snippet": {"type":"string"}
                                },
                                "required": ["first_author", "year"]
                            }
                        }
                    },
                    "required": ["detected_style"]
                }
            }
        }

        content_parts = [{"type":"text","text":f"Style hint: {style_hint}. Find the PRISMA 'Included/Selected' list in these pages. Return structured data only; dedupe and sort ascending."}]
        for i, url in enumerate(imgs):
            if page_texts[i]:
                content_parts.append({"type":"text","text":f"Page {pages[i]+1} text:\n{page_texts[i][:4000]}"})
            content_parts.append({"type":"image_url","image_url":{"url":url}})

        logger.log(f"OpenAI request: model={model}, pages={ [p+1 for p in pages] } (images={len(imgs)})")
        t0 = time.perf_counter()
        chat = client.chat.completions.create(
            model=model,
            messages=[
                {"role":"system","content":system},
                {"role":"user","content":content_parts}
            ],
            tools=[tool_schema],
            tool_choice={"type":"function","function":{"name":"return_included"}},
            temperature=0
        )
        elapsed = time.perf_counter() - t0
        logger.log(f"OpenAI response received in {elapsed:.1f}s")

        tool_args = {}
        try:
            call = chat.choices[0].message.tool_calls[0]
            import json
            tool_args = json.loads(call.function.arguments or "{}")
        except Exception:
            raw = chat.choices[0].message.content or ""
            nums, _ = harvest_bracket_numbers(raw)
            tool_args = {"detected_style": "numeric" if nums else "author_year",
                         "included_numbers": nums,
                         "included_author_year": []}
        tool_args["used_pages"] = [i+1 for i in pages]
        return tool_args
    finally:
        doc.close()

def ocr_harvest_pages(pdf_path: str, pages_1based: List[int], cancel: CancellationToken, logger: UiLogger) -> List[int]:
    if not OCR_AVAILABLE or not pages_1based:
        return []
    logger.log("OCR augmentation: starting")
    doc = fitz.open(pdf_path)
    try:
        text = ""
        for p in pages_1based:
            if cancel.cancelled:
                logger.log("OCR augmentation: cancelled")
                return []
            i = p - 1
            pix = doc.load_page(i).get_pixmap(dpi=240)
            try:
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                cfg = r'--psm 6 -c tessedit_char_whitelist=0123456789[],-–'
                text += "\n" + pytesseract.image_to_string(img, config=cfg)
                logger.log(f"OCR page {p} done")
            except Exception as e:
                logger.log(f"OCR page {p} error: {e}")
        nums, _ = harvest_bracket_numbers(text)
        logger.log(f"OCR augmentation: harvested {len(nums)} numbers")
        return nums
    finally:
        doc.close()

# ---------------- Mapping ----------------

def map_numeric(included_nums: List[int], ref_map: Dict[int, RefEntry]) -> List[Tuple[int, str, float]]:
    out = []
    for n in sorted(set(included_nums)):
        entry = ref_map.get(n)
        if entry:
            out.append((n, entry.raw, 1.0))
        else:
            out.append((n, "(Not found in References section)", 0.0))
    return out

def normalize_name(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z]+", "", s)
    return s

def build_author_year_index(entries: List[RefEntry]) -> Dict[Tuple[str,int], List[int]]:
    idx: Dict[Tuple[str,int], List[int]] = {}
    for i, e in enumerate(entries):
        if not e.first_author or not e.year:
            continue
        key = (normalize_name(e.first_author), int(e.year))
        idx.setdefault(key, []).append(i)
    return idx

def fuzzy_match_author_year(items: List[Dict[str,Any]], entries: List[RefEntry]) -> List[Tuple[str,int,str,float]]:
    # returns (first_author, year, raw_citation, confidence)
    index = build_author_year_index(entries)
    out = []
    for it in items:
        fa = normalize_name(it.get("first_author",""))
        yr = it.get("year", None)
        title_snip = (it.get("title_snippet","") or "").strip()
        best_raw = "(No match)"
        conf = 0.0
        if fa and isinstance(yr, int):
            candidates = index.get((fa, yr), [])
            if candidates:
                if len(candidates) == 1:
                    best_raw = entries[candidates[0]].raw
                    conf = 0.95
                else:
                    if FUZZY_OK and title_snip:
                        scores = []
                        for j in candidates:
                            ref_title = entries[j].title or entries[j].raw
                            score = fuzz.token_set_ratio(title_snip, ref_title)
                            scores.append((score, j))
                        scores.sort(reverse=True)
                        best_raw = entries[scores[0][1]].raw
                        conf = scores[0][0] / 100.0
                    else:
                        best_raw = entries[candidates[0]].raw
                        conf = 0.75
        out.append((it.get("first_author",""), yr if isinstance(yr,int) else None, best_raw, conf))
    return out

# ---------------- Pipeline ----------------

def run_pipeline(pdf_path: str, model: str, pages_override: Optional[str], include_appendix: bool,
                 cancel: CancellationToken, logger: UiLogger) -> Dict[str, Any]:
    t0 = time.perf_counter()
    logger.log("Step: Parse references")
    full_text, _ = extract_pdf_texts(pdf_path)
    style = detect_reference_style(full_text)

    ref_block = find_references_block(full_text)
    numeric_map: Dict[int, RefEntry] = {}
    author_entries: List[RefEntry] = []
    if style == "numeric":
        numeric_map = parse_numeric_references(ref_block)
        logger.log(f"Parsed numeric refs: {len(numeric_map)} entries (max=[{max(numeric_map.keys()) if numeric_map else 0}])")
    else:
        author_entries = parse_author_year_references(ref_block)
        logger.log(f"Parsed author–year refs: {len(author_entries)} entries")

    if cancel.cancelled:
        return {}

    logger.log("Step: Find candidate pages")
    doc = fitz.open(pdf_path)
    try:
        if pages_override:
            pages = []
            for part in pages_override.split(","):
                part = part.strip()
                if "-" in part:
                    a,b = part.split("-",1)
                    if a.isdigit() and b.isdigit():
                        a,b = int(a), int(b)
                        if a<=b:
                            pages += list(range(a,b+1))
                        else:
                            pages += list(range(b,a+1))
                elif part.isdigit():
                    pages.append(int(part))
            pages = [p-1 for p in pages if 1<=p<=len(doc)]
            if not pages:
                pages = guess_candidate_pages(pdf_path, include_appendix, logger)
        else:
            pages = guess_candidate_pages(pdf_path, include_appendix, logger)
    finally:
        doc.close()

    if cancel.cancelled:
        return {}

    logger.log("Step: AI analysis")
    ai = ai_extract_included(pdf_path, pages, style_hint=style, model=model, cancel=cancel, logger=logger)

    if cancel.cancelled:
        return {}

    included_numbers: List[int] = []
    included_author_year: List[Dict[str,Any]] = []
    detected_style = ai.get("detected_style", style)
    declared_n = ai.get("declared_included_n", None)
    used_pages = ai.get("used_pages", [p+1 for p in pages])

    if detected_style == "numeric" or style == "numeric":
        included_numbers = sorted(set(int(n) for n in ai.get("included_numbers", []) if isinstance(n, int)))
        logger.log(f"AI returned {len(included_numbers)} numeric indices")
        logger.log("Step: OCR augmentation")
        ocr_nums = ocr_harvest_pages(pdf_path, used_pages, cancel, logger)
        included_numbers = sorted(set(included_numbers + [n for n in ocr_nums if n>0]))
        if numeric_map:
            included_numbers = [n for n in included_numbers if n <= max(numeric_map.keys())]
        logger.log(f"After OCR merge: {len(included_numbers)} unique indices")
    else:
        included_author_year = ai.get("included_author_year", [])
        for it in included_author_year:
            if "first_author" in it and isinstance(it["first_author"], str):
                it["first_author"] = it["first_author"].strip()
        logger.log(f"AI returned {len(included_author_year)} author–year items")

    if cancel.cancelled:
        return {}

    logger.log("Step: Mapping")
    mapped_rows: List[str] = []
    low_conf: List[str] = []
    if detected_style == "numeric" or (style=="numeric" and included_numbers):
        rows = map_numeric(included_numbers, numeric_map)
        for n, raw, conf in rows:
            mapped_rows.append(f"[{n}] {raw}")
            if conf < 0.9:
                low_conf.append(f"[{n}] (no match)")
        extracted_count = len(included_numbers)
    else:
        matches = fuzzy_match_author_year(included_author_year, author_entries)
        for fa, yr, raw, conf in matches:
            label = f"{fa}, {yr}" if yr is not None else f"{fa} (?)"
            mapped_rows.append(f"{label} — {raw}")
            if conf < 0.8:
                low_conf.append(f"{label} — low confidence ({conf:.2f})")
        extracted_count = len(matches)

    elapsed = time.perf_counter() - t0
    logger.log(f"Done in {elapsed:.1f}s")

    return {
        "style": detected_style,
        "ref_style_guess": style,
        "used_pages": used_pages,
        "declared_n": declared_n,
        "numeric_map": numeric_map,
        "author_entries": author_entries,
        "included_numbers": included_numbers,
        "included_author_year": included_author_year,
        "mapped_rows": mapped_rows,
        "low_conf": low_conf
    }

# ---------------- Formatting helpers ----------------

def format_pages_list(pages_1based: List[int]) -> str:
    if not pages_1based:
        return "[]"
    pages = sorted(pages_1based)
    ranges = []
    start = pages[0]
    prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        if start == prev:
            ranges.append(f"{start}")
        else:
            ranges.append(f"{start}–{prev}")
        start = prev = p
    if start == prev:
        ranges.append(f"{start}")
    else:
        ranges.append(f"{start}–{prev}")
    return ", ".join(ranges)

def format_numbered_list(output: Dict[str,Any], sort_mode: str) -> str:
    style = output.get("style", "unknown")
    lines = []
    if style == "numeric":
        nums = output.get("included_numbers", [])
        for i, n in enumerate(nums, 1):
            lines.append(f"{i}. [{n}]")
    else:
        items = output.get("included_author_year", [])
        # determine ordering
        def key_extraction_order(idx_item):
            i, it = idx_item
            return i
        def key_year_asc(idx_item):
            _, it = idx_item
            return (it.get("year", 9999), (it.get("first_author") or ""))
        def key_year_desc(idx_item):
            _, it = idx_item
            return (-int(it.get("year", 0) or 0), (it.get("first_author") or ""))
        def key_author(idx_item):
            _, it = idx_item
            return (it.get("first_author") or "").lower()
        indexed = list(enumerate(items))
        if sort_mode == "Year ↑":
            indexed.sort(key=key_year_asc)
        elif sort_mode == "Year ↓":
            indexed.sort(key=key_year_desc)
        elif sort_mode == "Author A→Z":
            indexed.sort(key=key_author)
        else:
            indexed.sort(key=key_extraction_order)
        for i, (_, it) in enumerate(indexed, 1):
            fa = it.get("first_author", "?")
            yr = it.get("year", "?")
            lines.append(f"{i}. {fa} et al., {yr}")
    return "\n".join(lines)

# ---------------- Tkinter App ----------------

class PrismaAIV3App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PRISMA Citations Extractor — AI v3.1")
        self.geometry("1200x820")
        self.minsize(1020, 720)

        # State
        self.pdf_path = tk.StringVar(value="")
        self.model_name = tk.StringVar(value=DEFAULT_MODEL)
        self.pages_override = tk.StringVar(value="")
        self.include_appendix = tk.BooleanVar(value=True)
        self.log_to_file = tk.BooleanVar(value=False)
        self.sort_mode = tk.StringVar(value="Extraction order")

        self.results_output: Optional[Dict[str,Any]] = None
        self.cancel_token = CancellationToken()
        self.worker: Optional[threading.Thread] = None

        # Build UI
        self._build_ui()

    # ---------- UI Builders ----------
    def _build_ui(self):
        # Top controls
        top = ttk.Frame(self, padding=12)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="PDF file:").grid(row=0, column=0, sticky="w", padx=(0,6))
        ent = ttk.Entry(top, textvariable=self.pdf_path, width=80)
        ent.grid(row=0, column=1, sticky="we", padx=(0,6))
        top.columnconfigure(1, weight=1)
        ttk.Button(top, text="Browse…", command=self.on_browse).grid(row=0, column=2, sticky="w")

        ttk.Label(top, text="OpenAI model:").grid(row=1, column=0, sticky="w", pady=(8,0))
        ttk.Entry(top, textvariable=self.model_name, width=24).grid(row=1, column=1, sticky="w", pady=(8,0))

        ttk.Label(top, text="Pages override (e.g., 2 or 2,4-5):").grid(row=1, column=2, sticky="e", padx=(16,6), pady=(8,0))
        ttk.Entry(top, textvariable=self.pages_override, width=18).grid(row=1, column=3, sticky="w", pady=(8,0))

        ttk.Checkbutton(top, text="Appendix hunt", variable=self.include_appendix).grid(row=1, column=4, sticky="w", padx=(16,0))
        ttk.Checkbutton(top, text="Log to file", variable=self.log_to_file).grid(row=1, column=5, sticky="w", padx=(12,0))

        # Buttons
        btns = ttk.Frame(self, padding=(12,0))
        btns.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(btns, text="Extract (AI)", command=self.on_extract).pack(side=tk.LEFT)
        ttk.Button(btns, text="Stop", command=self.on_stop).pack(side=tk.LEFT, padx=(8,0))
        ttk.Button(btns, text="Save Results…", command=self.on_save).pack(side=tk.LEFT, padx=(8,0))
        ttk.Button(btns, text="Copy Numbered List", command=self.on_copy_numbered).pack(side=tk.LEFT, padx=(8,0))

        # Progress ribbon
        ribbon = ttk.Frame(self, padding=(12,6))
        ribbon.pack(side=tk.TOP, fill=tk.X)
        self.step_labels = {
            "Parse references": ttk.Label(ribbon, text="◻ Parse references"),
            "Find pages": ttk.Label(ribbon, text="◻ Find pages"),
            "AI analysis": ttk.Label(ribbon, text="◻ AI analysis"),
            "OCR augmentation": ttk.Label(ribbon, text="◻ OCR augmentation"),
            "Mapping": ttk.Label(ribbon, text="◻ Mapping"),
            "Formatting": ttk.Label(ribbon, text="◻ Formatting"),
        }
        for i, key in enumerate(self.step_labels.keys()):
            self.step_labels[key].grid(row=0, column=i, padx=6)

        # Tabs
        self.nb = ttk.Notebook(self)
        self.nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Results tab
        self.tab_results = ttk.Frame(self.nb)
        self.nb.add(self.tab_results, text="Results")
        res_top = ttk.Frame(self.tab_results, padding=8)
        res_top.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(res_top, text="Sort (author–year):").pack(side=tk.LEFT)
        self.sort_combo = ttk.Combobox(res_top, textvariable=self.sort_mode, width=18,
                                       values=["Extraction order", "Year ↑", "Year ↓", "Author A→Z"])
        self.sort_combo.pack(side=tk.LEFT, padx=(6,0))
        self.sort_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_results_view())

        self.results_text = tk.Text(self.tab_results, wrap="word")
        self.results_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb1 = ttk.Scrollbar(self.tab_results, orient="vertical", command=self.results_text.yview)
        sb1.pack(side=tk.RIGHT, fill=tk.Y)
        self.results_text.configure(yscrollcommand=sb1.set)

        # Diagnostics tab (Event Log)
        self.tab_diag = ttk.Frame(self.nb)
        self.nb.add(self.tab_diag, text="Diagnostics")
        self.log_text = tk.Text(self.tab_diag, wrap="word")
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2 = ttk.Scrollbar(self.tab_diag, orient="vertical", command=self.log_text.yview)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=sb2.set)

        # Preview tab
        self.tab_preview = ttk.Frame(self.nb)
        self.nb.add(self.tab_preview, text="Preview")
        self.preview_canvas = tk.Canvas(self.tab_preview)
        self.preview_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.preview_scroll = ttk.Scrollbar(self.tab_preview, orient="vertical", command=self.preview_canvas.yview)
        self.preview_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.preview_canvas.configure(yscrollcommand=self.preview_scroll.set)
        self.preview_inner = ttk.Frame(self.preview_canvas)
        self.preview_canvas.create_window((0,0), window=self.preview_inner, anchor="nw")
        self.preview_inner.bind("<Configure>", lambda e: self.preview_canvas.configure(scrollregion=self.preview_canvas.bbox("all")))
        self.preview_imgs: List[ImageTk.PhotoImage] = []

    # ---------- Helpers ----------
    def set_step(self, key: str, status: str):
        # status: waiting, running, done
        label = self.step_labels.get(key)
        if not label:
            return
        if status == "running":
            label.config(text=f"● {key}")
        elif status == "done":
            label.config(text=f"✅ {key}")
        else:
            label.config(text=f"◻ {key}")

    def on_browse(self):
        path = filedialog.askopenfilename(title="Select a PDF", filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if path:
            self.pdf_path.set(path)

    def build_logger(self) -> UiLogger:
        return UiLogger(self.log_text, self.log_to_file, logs_dir=os.path.join(os.path.expanduser("~"), "prisma_logs"), tk_root=self)

    def on_extract(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Busy", "An extraction is already running. Click Stop to cancel it.")
            return
        path = self.pdf_path.get().strip()
        if not path:
            messagebox.showwarning("No file", "Please choose a PDF first.")
            return
        if not os.path.isfile(path):
            messagebox.showerror("Not found", f"File not found:\n{path}")
            return
        if not OPENAI_OK:
            messagebox.showerror("Missing package", "Install the OpenAI SDK:\n  pip install openai")
            return
        if not os.environ.get("OPENAI_API_KEY"):
            messagebox.showerror("Missing API key", "Set OPENAI_API_KEY in your environment.")
            return

        # reset UI
        self.results_text.delete("1.0", tk.END)
        self.log_text.delete("1.0", tk.END)
        for k in self.step_labels.keys():
            self.set_step(k, "waiting")
        self.set_step("Parse references", "running")
        self.cancel_token = CancellationToken()

        logger = self.build_logger()

        def work():
            try:
                # Parse refs (flag in pipeline logs too)
                # We mark step transitions around pipeline’s phases
                out: Dict[str,Any] = {}
                t0 = time.perf_counter()
                # The pipeline itself logs
                out = run_pipeline(
                    pdf_path=path,
                    model=self.model_name.get().strip() or DEFAULT_MODEL,
                    pages_override=self.pages_override.get().strip() or None,
                    include_appendix=self.include_appendix.get(),
                    cancel=self.cancel_token,
                    logger=logger
                )

                if not out:
                    logger.log("Cancelled.")
                    return

                # Mark steps (best-effort based on logs)
                self.after(0, lambda: self.set_step("Parse references", "done"))
                self.after(0, lambda: self.set_step("Find pages", "done"))
                self.after(0, lambda: self.set_step("AI analysis", "done"))
                if OCR_AVAILABLE:
                    self.after(0, lambda: self.set_step("OCR augmentation", "done"))
                self.after(0, lambda: self.set_step("Mapping", "done"))
                self.after(0, lambda: self.set_step("Formatting", "running"))

                self.results_output = out
                self.after(0, self.refresh_results_view)
                self.after(0, self.render_preview_images)
                self.after(0, lambda: self.set_step("Formatting", "done"))
            except Exception as e:
                logger.log(f"ERROR: {e}")
                messagebox.showerror("Extraction error", str(e))
            finally:
                logger.close()

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def on_stop(self):
        if self.worker and self.worker.is_alive():
            self.cancel_token.cancel()
            self.build_logger().log("Cancellation requested (will stop between steps or ignore in-flight call).")
        else:
            messagebox.showinfo("Idle", "No extraction is running.")

    def refresh_results_view(self):
        out = self.results_output or {}
        style = out.get("style", "unknown")
        pages_fmt = format_pages_list(out.get("used_pages", []))

        header = []
        header.append(f"Detected style: {style} (guess: {out.get('ref_style_guess','?')})")
        header.append(f"Pages processed: {pages_fmt}")
        if out.get("declared_n") is not None:
            extracted_n = len(out.get("included_numbers", [])) if style == "numeric" else len(out.get("included_author_year", []))
            header.append(f"Included count: extracted {extracted_n} (declared {out['declared_n']})")
            if extracted_n != out['declared_n']:
                header.append("⚠ Count mismatch — consider adjusting Pages override or Appendix hunt.")
        header.append("")

        # Numbered list (primary)
        numbered = format_numbered_list(out, self.sort_mode.get())

        # Mapped citations (expandable later; plain text for now)
        mapped_lines = ["Mapped citations (expanded):"]
        for row in out.get("mapped_rows", []):
            mapped_lines.append(f"- {row}")

        # Low confidence bucket
        low = out.get("low_conf", [])
        low_lines = []
        if low:
            low_lines.append("\nLow-confidence items:")
            for r in low:
                low_lines.append(f"- {r}")

        text = "\n".join(header + ["Included (numbered):", numbered, "", *mapped_lines, *low_lines])
        self.results_text.delete("1.0", tk.END)
        self.results_text.insert("1.0", text)

    def render_preview_images(self):
        # Clear previous
        for w in list(self.preview_inner.children.values()):
            w.destroy()
        self.preview_imgs.clear()
        out = self.results_output or {}
        pages = out.get("used_pages", [])
        path = self.pdf_path.get().strip()
        if not path or not pages:
            return
        try:
            doc = fitz.open(path)
            row = 0
            for p in pages:
                i = p - 1
                pix = doc.load_page(i).get_pixmap(dpi=160)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                # constrain width
                max_w = 800
                if img.width > max_w:
                    scale = max_w / img.width
                    img = img.resize((int(img.width*scale), int(img.height*scale)))
                tkimg = ImageTk.PhotoImage(img)
                self.preview_imgs.append(tkimg)
                lbl = ttk.Label(self.preview_inner, image=tkimg, text=f"Page {p}", compound="top")
                lbl.grid(row=row, column=0, pady=8, padx=8, sticky="w")
                row += 1
            doc.close()
        except Exception as e:
            # silently ignore preview failures
            pass

    def on_save(self):
        out = self.results_output
        if not out:
            messagebox.showwarning("Nothing to save", "Run Extract first.")
            return
        save_path = filedialog.asksaveasfilename(title="Save results", defaultextension=".txt",
                                                 filetypes=[("Text", "*.txt"), ("CSV", "*.csv"), ("All files", "*.*")])
        if not save_path:
            return
        try:
            if save_path.lower().endswith(".csv"):
                import csv
                with open(save_path, "w", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["Detected style", out.get("style", "")])
                    w.writerow(["Pages processed", format_pages_list(out.get("used_pages", []))])
                    w.writerow([])
                    w.writerow(["Included (numbered)"])
                    for line in format_numbered_list(out, self.sort_mode.get()).splitlines():
                        w.writerow([line])
                    w.writerow([])
                    w.writerow(["Mapped citations"]) 
                    for row in out.get("mapped_rows", []):
                        w.writerow([row])
                    if out.get("low_conf"):
                        w.writerow([])
                        w.writerow(["Low-confidence items"]) 
                        for r in out.get("low_conf", []):
                            w.writerow([r])
            else:
                # plain text
                text = self.results_text.get("1.0", "end-1c")
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(text)
            messagebox.showinfo("Saved", f"Results saved to:\n{save_path}")
        except Exception as e:
            messagebox.showerror("Save error", str(e))

    def on_copy_numbered(self):
        out = self.results_output
        if not out:
            return
        txt = format_numbered_list(out, self.sort_mode.get())
        self.clipboard_clear()
        self.clipboard_append(txt)
        self.update()  # keep clipboard
        messagebox.showinfo("Copied", "Numbered list copied to clipboard.")


def main():
    app = PrismaAIV3App()
    app.mainloop()

if __name__ == "__main__":
    main()
