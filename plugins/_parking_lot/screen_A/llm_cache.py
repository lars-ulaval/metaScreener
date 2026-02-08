# -*- coding: utf-8 -*-
"""
Created on Sat Oct  4 12:28:08 2025

@author: alere

File: plugins/screen_A/llm_cache.py
Simple file-based cache for metadata LLM calls.

Key = sha256(model, prompt_version, criterion_id, a_id, fields_hash)
Value = JSON blob (normalized decision dict for that (a_id, criterion_id))
"""

from __future__ import annotations
from typing import Any, Optional
import os
import json
import hashlib
import tempfile

CACHE_ROOT = os.path.join(os.path.expanduser("~"), ".screenA_cache", "llm")


def ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p


def _safe_filename(key: str) -> str:
    # key is already a hex digest; keep short fanout directories for performance
    ensure_dir(CACHE_ROOT)
    shard = key[:2]
    d = ensure_dir(os.path.join(CACHE_ROOT, shard))
    return os.path.join(d, f"{key}.json")


def make_key(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        if p is None:
            p = ""
        # normalize to str and encode
        h.update(str(p).encode("utf-8"))
        h.update(b"\x1e")  # record separator
    return h.hexdigest()


def cache_get(key: str) -> Optional[dict[str, Any]]:
    path = _safe_filename(key)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def cache_put(key: str, payload: dict[str, Any]) -> None:
    path = _safe_filename(key)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix="llm_cache_", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        # best-effort; ignore cache write failures
        try:
            os.remove(tmp_path)
        except Exception:
            pass
