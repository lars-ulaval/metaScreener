
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_provider_readiness.py — F-117: one key predicate, and it is a
readiness check rather than a presence check.

The defect
----------
Two predicates over the same environment variable, disagreeing:

* ``plugins/_common/llm_client.py::_has_openai_key`` — ``bool(os.environ
  .get("OPENAI_API_KEY", "").strip())``, which **strips**;
* ``plugins/03_harmoniser/llm_refine.py::_llm_available`` — ``if not
  os.getenv("OPENAI_API_KEY")``, bare truthiness, which does not.

So with a whitespace-only key the harmoniser offers to spend money while
EL and IL refuse. One subsystem, one variable, two answers.

Why the fix is not "make both strip"
------------------------------------
D1 preselects a local provider, and a local server does not authenticate.
Under a presence check the local user must invent a placeholder key to
get past a gate that exists for a provider they are not using — which is
what the old ``NO_KEY`` message told them to do, in as many words:

    "a placeholder such as \\"local\\" is enough for a server that does not
    check it."

Asking a user to type a fake credential to reach a free local model is a
GUI-first defect wearing a security gate's clothes. So the predicate
becomes a question about the **provider**: does this configuration need a
key, and does it have one?

The SDK still requires *something* non-empty in the ``api_key`` slot. That
is now the application's problem, not the user's — see
``placeholder_key_for``.
"""
import importlib.util
import sys

import pytest

from conftest import PROJECT_ROOT


def _load(name, relpath):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, str(PROJECT_ROOT.joinpath(*relpath.split("/")))
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


import plugins._common.stage_state as ss

S = _load("_settings_for_readiness", "plugins/_common/settings.py")


# ---------------------------------------------------------------------------
# One predicate
# ---------------------------------------------------------------------------

class TestKeyRequirementFollowsTheProvider:

    def test_openai_requires_a_key(self):
        assert ss.key_required("openai") is True

    @pytest.mark.parametrize("provider", ["local", "custom"])
    def test_a_local_or_custom_server_does_not(self, provider):
        """The whole of D1's ergonomics. A user who picks the preselected
        local provider must not be asked for a credential."""
        assert ss.key_required(provider) is False

    def test_an_unknown_provider_is_treated_as_needing_one(self):
        """The safe direction: refusing to run costs a click, and guessing
        that an unknown endpoint is unauthenticated could leak a key or
        spend money."""
        assert ss.key_required("something-new") is True


class TestTheTwoPredicatesNowAgree:
    """The regression this row exists to prevent, asserted directly over
    both call sites' inputs rather than over one of them."""

    @pytest.mark.parametrize("key", ["", "   ", "\t\n"])
    def test_a_blank_or_whitespace_key_is_no_key_for_openai(self, key):
        assert ss.key_ok(provider="openai", api_key=key) is False

    @pytest.mark.parametrize("key", ["   ", ""])
    def test_the_same_blank_key_does_not_block_a_local_run(self, key):
        """Previously the harmoniser said yes and EL/IL said no. Now both
        say yes, and for the right reason: no key is needed."""
        assert ss.key_ok(provider="local", api_key=key) is True

    def test_a_real_key_satisfies_openai(self):
        assert ss.key_ok(provider="openai", api_key="sk-abc") is True

    def test_surrounding_whitespace_is_ignored_not_counted(self):
        assert ss.key_ok(provider="openai", api_key="  sk-abc  ") is True


class TestThePlaceholderIsTheApplicationsProblem:
    """The SDK requires a non-empty ``api_key`` even against a server that
    ignores it. The user should never be the one to satisfy that."""

    def test_a_local_provider_gets_a_placeholder(self):
        assert S.placeholder_key_for("local", "") .strip() != ""

    def test_a_real_key_is_never_replaced(self):
        assert S.placeholder_key_for("local", "sk-real") == "sk-real"

    def test_openai_is_not_given_a_placeholder(self):
        """Silently substituting one would turn 'you forgot your key' into
        a 401 from the vendor — a worse error, further from the cause."""
        assert S.placeholder_key_for("openai", "") == ""


# ---------------------------------------------------------------------------
# The readiness model absorbs the provider
# ---------------------------------------------------------------------------

class TestReadinessTakesTheProvider:

    def _ready(self, **kw):
        base = dict(stage="EL", has_bundle=True, provider="openai",
                    api_key="sk-abc", model="gpt-4o-mini")
        base.update(kw)
        return ss.llm_readiness(**base)

    def test_a_complete_openai_configuration_is_ready(self):
        r = self._ready()
        assert r.code == ss.READY and r.can_run is True

    def test_a_local_configuration_with_no_key_is_ready(self):
        """The state that could not be expressed before."""
        r = self._ready(provider="local", api_key="")
        assert r.code == ss.READY, r.detail
        assert r.can_run is True

    def test_openai_without_a_key_is_not_ready(self):
        r = self._ready(api_key="   ")
        assert r.code == ss.NO_KEY and r.can_run is False

    def test_the_no_key_message_no_longer_tells_a_local_user_to_invent_one(self):
        """The old text instructed every user to type a placeholder. It is
        now only reachable for a provider that genuinely authenticates, so
        it must name that provider rather than describe a workaround."""
        detail = self._ready(api_key="").detail.lower()
        assert "placeholder" not in detail

    def test_bundle_still_comes_first(self):
        """Order is the order the user meets the steps in — a user with
        nothing set up is told to load a bundle, not to find a key."""
        assert self._ready(has_bundle=False, api_key="").code == ss.NO_BUNDLE

    def test_a_missing_model_still_blocks(self):
        assert self._ready(model="  ").code == ss.NO_MODEL

    def test_readiness_returns_the_normalised_model(self):
        assert self._ready(model="  qwen2.5:7b  ").model == "qwen2.5:7b"


class TestTheOldSignatureIsGone:
    """A caller left on ``has_key=`` would silently keep the presence
    check. Better a TypeError than two predicates again."""

    def test_has_key_is_no_longer_accepted(self):
        with pytest.raises(TypeError):
            ss.llm_readiness(stage="EL", has_bundle=True, has_key=True,
                             model="m")
