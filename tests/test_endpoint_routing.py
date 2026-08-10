
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_endpoint_routing.py — F-92: the endpoint the run talks to must be
chosen by this repository, not by a side effect of the vendor SDK.

The defect this pins
--------------------
The whole local-provider capability — a README section, and the project's
answer to "does this require a paid API?" — worked only because
``openai/_client.py::OpenAI.__init__`` falls back to
``os.environ.get("OPENAI_BASE_URL")`` when no ``base_url=`` is passed. No
repository line read, wrote, validated, logged or recorded that variable,
``openai`` is pinned only ``>=1.40.0``, and **no test asserted the
resolved endpoint**.

Two changes would therefore have routed a "local" run to the paid API
with the entire suite green: an SDK major that dropped the fallback, and
a well-meant refactor adding an explicit
``base_url="https://api.openai.com/v1"``.

``test_client_is_constructed_with_an_explicit_base_url`` is the one that
closes the hole. Asserting only ``str(client.base_url)`` would still pass
if the SDK resolved the value on our behalf — which is the very state
F-92 objects to — so the decisive assertion is that **this repository
passed the keyword**, not that the answer happened to come out right.

No network
----------
``OpenAI(...)`` resolves and normalises its ``base_url`` in ``__init__``
and issues no request, so every assertion here is offline. A dummy
``OPENAI_API_KEY`` is set because the constructor raises without one.
"""
import os

import pytest

from plugins._common import llm_client as lc


ENV_VAR = "OPENAI_BASE_URL"


@pytest.fixture(autouse=True)
def _isolated_llm_env(monkeypatch):
    """Neither the developer's shell nor a project ``.env`` may decide the
    outcome of these tests.

    Scoped to this module deliberately: a suite-wide autouse guard is
    F-114 and is not this wave's to write.
    """
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")


# ---------------------------------------------------------------------------
# resolve_openai_base_url — the repository's own resolution
# ---------------------------------------------------------------------------

class TestResolution:
    """``resolve_openai_base_url`` is the single place the endpoint is
    decided, and both the client and the cache key read it from here."""

    def test_absent_resolves_to_the_named_default(self, monkeypatch):
        monkeypatch.delenv(ENV_VAR, raising=False)
        assert lc.resolve_openai_base_url() == lc.DEFAULT_OPENAI_BASE_URL

    @pytest.mark.parametrize("blank", ["", "   ", "\t", "\n"])
    def test_blank_resolves_to_the_named_default(self, monkeypatch, blank):
        """An empty or whitespace-only setting is an unset one.

        ``metascreener/main.py::_load_env_file`` already refuses to export
        a blank value, but the variable can also arrive from the shell,
        and "set to nothing" must not become a third endpoint namespace
        distinct from both "unset" and any real URL.
        """
        monkeypatch.setenv(ENV_VAR, blank)
        assert lc.resolve_openai_base_url() == lc.DEFAULT_OPENAI_BASE_URL

    def test_set_resolves_verbatim(self, monkeypatch):
        monkeypatch.setenv(ENV_VAR, "http://localhost:11434/v1")
        assert lc.resolve_openai_base_url() == "http://localhost:11434/v1"

    def test_surrounding_whitespace_is_stripped(self, monkeypatch):
        """Stripping is part of resolution, not of the key.

        Whitespace is not a routing difference, and leaving it in would
        make ``"…/v1"`` and ``" …/v1"`` two cache namespaces for one
        server.
        """
        monkeypatch.setenv(ENV_VAR, "  http://localhost:8080/v1  ")
        assert lc.resolve_openai_base_url() == "http://localhost:8080/v1"

    def test_default_is_the_slashless_literal(self):
        """Pinned because it is a cache-key input (F-89).

        ``str(client.base_url)`` is ``https://api.openai.com/v1/`` — httpx
        appends the trailing slash — and that normalised form is *not*
        what is hashed. Hashing it instead would be a different key set,
        i.e. a second re-key. See ``_cache_key``'s docstring.
        """
        assert lc.DEFAULT_OPENAI_BASE_URL == "https://api.openai.com/v1"


# ---------------------------------------------------------------------------
# The client actually goes where it was told
# ---------------------------------------------------------------------------

class TestClientRouting:

    def test_client_is_constructed_with_an_explicit_base_url(self, monkeypatch):
        """**This is F-92.**

        The endpoint must arrive at the SDK as a keyword this repository
        passed. If ``base_url`` is absent from the constructor call, the
        value is being supplied by the SDK's environment fallback — which
        is an undeclared, unpinned, untested third-party default, and the
        thing this finding exists to remove.
        """
        monkeypatch.setenv(ENV_VAR, "http://localhost:11434/v1")

        seen = {}

        import openai

        class _Recorder:
            def __init__(self, **kwargs):
                seen.update(kwargs)

        monkeypatch.setattr(openai, "OpenAI", _Recorder)
        lc._openai_client_for()

        assert "base_url" in seen, (
            "F-92: _openai_client_for did not pass base_url=. The endpoint "
            "is then whatever the installed SDK's constructor decides, so "
            "an SDK major that dropped the OPENAI_BASE_URL fallback would "
            "route this 'local' run to the paid API with the suite green."
        )
        assert seen["base_url"] == "http://localhost:11434/v1"

    def test_local_endpoint_reaches_the_resolved_client(self, monkeypatch):
        monkeypatch.setenv(ENV_VAR, "http://localhost:11434/v1")
        client = lc._openai_client_for()
        assert str(client.base_url) == "http://localhost:11434/v1/"

    def test_unset_endpoint_reaches_the_public_api(self, monkeypatch):
        monkeypatch.delenv(ENV_VAR, raising=False)
        client = lc._openai_client_for()
        assert str(client.base_url) == "https://api.openai.com/v1/"

    def test_explicit_default_and_unset_agree(self, monkeypatch):
        """Setting the public endpoint by hand and leaving it unset are the
        same configuration, and must resolve to the same string.

        They therefore share one cache namespace (F-89). The alternative —
        hashing the raw variable with absent as ``""`` — would split one
        provider into two namespaces and charge the user a full re-run for
        a no-op edit to ``.env``.
        """
        monkeypatch.delenv(ENV_VAR, raising=False)
        unset = lc.resolve_openai_base_url()
        monkeypatch.setenv(ENV_VAR, lc.DEFAULT_OPENAI_BASE_URL)
        explicit = lc.resolve_openai_base_url()
        assert unset == explicit

    def test_the_sdk_fallback_is_no_longer_on_the_path(self, monkeypatch):
        """The repository's value wins even when the SDK would have chosen
        differently — proving the fallback is dead code for this project
        rather than merely agreed with.

        Constructed by hand rather than through ``_openai_client_for`` so
        the assertion is about the SDK's precedence, which is what the
        pinned floor's behaviour would change.
        """
        import openai

        monkeypatch.setenv(ENV_VAR, "http://from-the-environment:1/v1")
        client = openai.OpenAI(
            api_key="sk-test-not-a-real-key",
            base_url="http://passed-explicitly:2/v1",
        )
        assert str(client.base_url) == "http://passed-explicitly:2/v1/"
