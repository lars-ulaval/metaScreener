# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_api_key_validation.py - API-key acceptance rules for the launch dialog.

Regression cover for F-08. The dialog required a key matching
`startswith("sk-") and len(key) >= 20` and could not be skipped
(metascreener/main.py prompts on every launch and refuses to build the
notebook without an accepted value). That made the entire documented
local-provider workflow unreachable through the GUI: README instructs
Ollama users to set OPENAI_API_KEY=ollama, llama.cpp users to set
llama-cpp, and notes that most local servers ignore the value but require
it to be non-empty.

Only the pure acceptance rules are exercised here; driving the Tk widget
itself needs a display and is out of scope for the headless suite.
"""
import importlib.util

import pytest

from conftest import PROJECT_ROOT

pytest.importorskip("tkinter", reason="api_key_dialog imports tkinter at module level")


def _dialog_module():
    path = PROJECT_ROOT / "metascreener" / "api_key_dialog.py"
    spec = importlib.util.spec_from_file_location("_akd_test", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


akd = _dialog_module()


# Values the README tells users to enter for a local, non-OpenAI backend.
LOCAL_PROVIDER_KEYS = ["ollama", "llama-cpp", "vllm", "not-needed", "x"]


class TestAcceptance:

    def test_local_provider_placeholders_are_accepted(self):
        """The F-08 defect: these were all rejected."""
        for key in LOCAL_PROVIDER_KEYS:
            accepted, _msg = akd.validate_api_key(key)
            assert accepted, "%r must be accepted (README:314-322)" % key

    def test_openai_style_key_is_accepted(self):
        accepted, msg = akd.validate_api_key("sk-" + "a" * 40)
        assert accepted
        assert msg == ""

    def test_empty_and_whitespace_are_rejected(self):
        for key in ("", "   ", "\t", "\n", None):
            accepted, msg = akd.validate_api_key(key)
            assert not accepted
            assert msg

    def test_rejection_message_is_about_emptiness_only(self):
        _accepted, msg = akd.validate_api_key("")
        assert "sk-" not in msg


class TestHint:

    def test_non_openai_key_is_accepted_but_hinted(self):
        for key in LOCAL_PROVIDER_KEYS:
            accepted, msg = akd.validate_api_key(key)
            assert accepted
            assert msg, "a non-OpenAI-looking key should carry a hint, not silence"

    def test_hint_is_advisory_not_an_error(self):
        """The hint must not read as a rejection - the key IS being used."""
        _accepted, msg = akd.validate_api_key("ollama")
        assert "OPENAI_BASE_URL" in msg or "local" in msg.lower()

    def test_looks_like_openai_key(self):
        assert akd.looks_like_openai_key("sk-" + "a" * 40) is True
        assert akd.looks_like_openai_key("sk-short") is False
        assert akd.looks_like_openai_key("ollama") is False
        assert akd.looks_like_openai_key("") is False


class TestSanitize:

    def test_strips_whitespace_and_surrounding_quotes(self):
        assert akd.sanitize_api_key('  "sk-abc"  ') == "sk-abc"
        assert akd.sanitize_api_key("'ollama'") == "ollama"
        assert akd.sanitize_api_key(None) == ""
