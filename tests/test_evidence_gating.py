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

class TestCacheKey:

    def test_deterministic(self):
        """Same inputs → same cache key."""
        k1 = _el()._cache_key(model="gpt-4o", cid="EC-1",
                               a_id="rec_001", text_hash="abc123",
                               trunc_chars=4000)
        k2 = _el()._cache_key(model="gpt-4o", cid="EC-1",
                               a_id="rec_001", text_hash="abc123",
                               trunc_chars=4000)
        assert k1 == k2

    def test_different_model_different_key(self):
        """Different model → different cache key."""
        k1 = _el()._cache_key(model="gpt-4o", cid="EC-1",
                               a_id="rec_001", text_hash="abc123",
                               trunc_chars=4000)
        k2 = _el()._cache_key(model="gpt-4o-mini", cid="EC-1",
                               a_id="rec_001", text_hash="abc123",
                               trunc_chars=4000)
        assert k1 != k2

    def test_different_criterion_different_key(self):
        k1 = _el()._cache_key(model="gpt-4o", cid="EC-1",
                               a_id="rec_001", text_hash="abc123",
                               trunc_chars=4000)
        k2 = _el()._cache_key(model="gpt-4o", cid="EC-2",
                               a_id="rec_001", text_hash="abc123",
                               trunc_chars=4000)
        assert k1 != k2

    def test_different_text_hash_different_key(self):
        k1 = _el()._cache_key(model="gpt-4o", cid="EC-1",
                               a_id="rec_001", text_hash="hash_a",
                               trunc_chars=4000)
        k2 = _el()._cache_key(model="gpt-4o", cid="EC-1",
                               a_id="rec_001", text_hash="hash_b",
                               trunc_chars=4000)
        assert k1 != k2

    def test_key_is_sha256_hex(self):
        """Cache key must be a 64-char hex digest."""
        k = _el()._cache_key(model="gpt-4o", cid="EC-1",
                              a_id="rec_001", text_hash="abc",
                              trunc_chars=4000)
        assert len(k) == 64
        assert all(c in "0123456789abcdef" for c in k)

    def test_key_includes_prompt_version(self):
        """Cache key incorporates the module-level PROMPT_VERSION."""
        # We verify indirectly: the key formula is
        # sha256(f"{PROMPT_VERSION}|{model}|{cid}|{a_id}|{text_hash}|{trunc_chars}")
        pv = _el().PROMPT_VERSION
        base = f"{pv}|gpt-4o|EC-1|rec_001|abc|4000"
        expected = sha256(base.encode("utf-8", errors="ignore")).hexdigest()
        k = _el()._cache_key(model="gpt-4o", cid="EC-1",
                              a_id="rec_001", text_hash="abc",
                              trunc_chars=4000)
        assert k == expected


# ======================================================================
# _row_target_text_hash
# ======================================================================

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
