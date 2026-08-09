# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_evidence_gating.py — Tests for EL/IL evidence-gating utility functions.

Tests SubstringMatch / quote validation and cache key construction
WITHOUT invoking any LLM calls.
"""
import pytest
from hashlib import sha256
from conftest import get_el


_mod = None

def _el():
    global _mod
    if _mod is None:
        _mod = get_el()
    return _mod


# ======================================================================
# _quote_in_text (SubstringMatch / quote validation)
# ======================================================================

class TestQuoteInText:

    def test_exact_substring_match(self):
        text = "Virtual reality is used for rehabilitation in stroke patients."
        quote = "used for rehabilitation"
        assert _el()._quote_in_text(quote, text) is True

    def test_exact_match_full_text(self):
        text = "Virtual reality training."
        quote = "Virtual reality training."
        assert _el()._quote_in_text(quote, text) is True

    def test_no_match(self):
        text = "This paper studies augmented reality."
        quote = "virtual reality"
        assert _el()._quote_in_text(quote, text) is False

    def test_whitespace_normalized_match(self):
        """Quotes with different whitespace (newlines, multiple spaces)."""
        text = "Virtual reality\n  is   used for\n rehabilitation."
        quote = "Virtual reality is used for rehabilitation."
        assert _el()._quote_in_text(quote, text) is True

    def test_empty_quote_returns_false(self):
        assert _el()._quote_in_text("", "some text") is False

    def test_empty_text_returns_false(self):
        assert _el()._quote_in_text("a quote", "") is False

    def test_both_empty_returns_false(self):
        assert _el()._quote_in_text("", "") is False

    def test_none_quote_returns_false(self):
        assert _el()._quote_in_text(None, "some text") is False

    def test_none_text_returns_false(self):
        assert _el()._quote_in_text("quote", None) is False

    def test_case_sensitive(self):
        """Quote matching is case-sensitive (exact or ws-normalized)."""
        text = "Virtual Reality is effective."
        quote = "virtual reality is effective."
        # Exact: 'v' != 'V' → False; ws-norm: same issue
        result = _el()._quote_in_text(quote, text)
        # The function does exact or ws-normalized substring match
        # Both are case-sensitive, so this should be False
        assert result is False


# ======================================================================
# _sha_text
# ======================================================================

class TestShaText:

    def test_deterministic(self):
        """Same input → same hash."""
        h1 = _el()._sha_text("hello world")
        h2 = _el()._sha_text("hello world")
        assert h1 == h2

    def test_different_inputs(self):
        h1 = _el()._sha_text("hello")
        h2 = _el()._sha_text("world")
        assert h1 != h2

    def test_matches_stdlib(self):
        """Verify it matches hashlib.sha256 directly."""
        text = "test string for hashing"
        expected = sha256(text.encode("utf-8", errors="ignore")).hexdigest()
        assert _el()._sha_text(text) == expected

    def test_hex_length(self):
        """SHA-256 hex digest is always 64 characters."""
        h = _el()._sha_text("anything")
        assert len(h) == 64


# ======================================================================
# _cache_key construction
# ======================================================================
#
# The TestCacheKey class that lived here was removed in the F-01 fix. Every
# test in it asserted the key built from the enumerated field list
#
#     sha256(f"{PROMPT_VERSION}|{model}|{cid}|{a_id}|{text_hash}|{trunc_chars}")
#
# including one that pinned that formula literally. That enumeration was the
# defect: the criterion contributed only its id, so editing a criterion's
# wording was a cache hit. The key is now the hash of the rendered prompt.
#
# Coverage moved to tests/test_cache_key.py, which keeps every property those
# tests checked (determinism, model, criterion id, record text, hex digest,
# per-stage separation) and adds the ones they could not express — edited
# criterion content, non-target field edits, and cross-process stability.


# ======================================================================
# _row_target_text_hash
# ======================================================================
#
# Still exported from plugins/_common/llm_client.py and still correct as a
# general helper, but no longer on the cache-key path: it hashed only a
# criterion's *target* fields, while the prompt ships title, abstract and
# keywords regardless of target. These tests pin the helper's own behaviour,
# not the cache key.

class TestRowTargetTextHash:

    def test_deterministic(self):
        row = {"title": "VR in education", "abstract": "We study VR."}
        h1 = _el()._row_target_text_hash(row, ["title", "abstract"], 0)
        h2 = _el()._row_target_text_hash(row, ["title", "abstract"], 0)
        assert h1 == h2

    def test_different_content_different_hash(self):
        row_a = {"title": "VR in education", "abstract": "A"}
        row_b = {"title": "VR in education", "abstract": "B"}
        h1 = _el()._row_target_text_hash(row_a, ["title", "abstract"], 0)
        h2 = _el()._row_target_text_hash(row_b, ["title", "abstract"], 0)
        assert h1 != h2

    def test_truncation(self):
        row = {"title": "A" * 10000}
        h_full = _el()._row_target_text_hash(row, ["title"], 0)
        h_trunc = _el()._row_target_text_hash(row, ["title"], 100)
        assert h_full != h_trunc
