
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_startup_readiness.py — session B: "ready" means reachable, and
"unconfigured" must never run.

The safety property
-------------------
``key_required("local")`` is ``False``, so *local* waives the key gate.
That is correct once a user has chosen local, and catastrophic before —
session A's review found a fresh install being waved past the gate and
then billed against the vendor endpoint, leaving it **worse off than
before that session**: previously blocked at ``NO_KEY``, afterwards
billable.

So the rule this module pins, restated from the coordinator's correction
to D1:

    D1 describes what the POPUP SHOWS. Local is the lit option when the
    choice is presented. It says nothing about what is true before that
    choice exists. The store's default is UNCONFIGURED; local becomes
    effective only when a user chooses it or a remembered choice is
    loaded. Never by fiat.

**Any path that can reach a run without passing through an explicit
choice must resolve to unconfigured, and unconfigured must not run.**

Reachability
------------
The brief requires that the run button stay disabled until a provider is
*ready*, where ready means **reachable** rather than merely configured.
Session A's ``READINESS_CODES`` docstring anticipated exactly this and
specified the extension mechanism — new members here, new branches in
``llm_readiness``, reached by new keyword arguments, changing no state
that already exists. This module holds it to that.

A probe is a network call, so ``llm_readiness`` does not perform one: it
is *told* the result. Being told nothing is its own state — ``NOT_CHECKED``
— rather than being silently optimistic, because "we have not looked" and
"we looked and it answered" are different claims and only one of them
licenses a run.
"""
import importlib.util
import sys

import pytest

from conftest import PROJECT_ROOT

import plugins._common.stage_state as ss


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


S = _load("_settings_for_startup", "plugins/_common/settings.py")
D = _load("_detect_for_startup", "plugins/_common/provider_detect.py")


def _ready(**kw):
    base = dict(stage="EL", has_bundle=True, provider="openai",
                api_key="sk-abc", model="gpt-4o-mini",
                probe=D.Detection(D.READY, ("gpt-4o-mini",), "", ""))
    base.update(kw)
    return ss.llm_readiness(**base)


# ---------------------------------------------------------------------------
# Unconfigured must not run
# ---------------------------------------------------------------------------

class TestUnconfiguredNeverRuns:

    def test_the_shipped_provider_is_unchosen(self):
        assert S.defaults()["provider"] == S.UNCHOSEN

    def test_an_unchosen_provider_blocks(self):
        r = _ready(provider=S.UNCHOSEN, api_key="", probe=None)
        assert r.code == ss.NOT_CONFIGURED
        assert r.can_run is False

    def test_it_blocks_even_with_a_key_and_a_model_and_a_live_probe(self):
        """The failure mode is a path that *looks* complete. Nothing
        substitutes for an explicit choice."""
        r = _ready(provider=S.UNCHOSEN, api_key="sk-abc", model="m",
                   probe=D.Detection(D.READY, ("m",), "", ""))
        assert r.code == ss.NOT_CONFIGURED
        assert r.can_run is False

    def test_the_message_names_the_choice_rather_than_a_missing_key(self):
        detail = _ready(provider=S.UNCHOSEN, api_key="", probe=None).detail
        assert "key" not in detail.lower(), detail

    def test_a_bundle_is_still_asked_for_first(self):
        """Order is the order the user meets the steps in."""
        assert _ready(provider=S.UNCHOSEN, has_bundle=False).code == ss.NO_BUNDLE


# ---------------------------------------------------------------------------
# Reachable, not merely configured
# ---------------------------------------------------------------------------

class TestReadyMeansReachable:

    def test_a_fully_configured_provider_that_was_never_probed_is_not_ready(self):
        """'We have not looked' and 'we looked and it answered' are
        different claims, and only one licenses a run."""
        r = _ready(probe=None)
        assert r.code == ss.NOT_CHECKED
        assert r.can_run is False

    def test_an_unreachable_endpoint_blocks(self):
        r = _ready(provider="local", api_key="",
                   probe=D.Detection(D.NOT_RUNNING, (), "start it", ""))
        assert r.code == ss.ENDPOINT_UNREACHABLE
        assert r.can_run is False

    def test_a_server_with_nothing_pulled_blocks_distinctly(self):
        r = _ready(provider="local", api_key="",
                   probe=D.Detection(D.NO_MODELS, (), "pull one", ""))
        assert r.code == ss.NO_MODELS_PULLED
        assert r.can_run is False

    @pytest.mark.parametrize("state,detail", [
        (D.NOT_INSTALLED, "install it from somewhere"),
        (D.NOT_RUNNING, "run ollama serve"),
        (D.NO_MODELS, "pull a model"),
    ])
    def test_the_detection_message_is_carried_through_verbatim(
            self, state, detail):
        """D4/D5 require three distinct actionable messages. Readiness must
        not flatten them into one 'unavailable' — telling a user the wrong
        one wastes their afternoon."""
        r = _ready(provider="local", api_key="",
                   probe=D.Detection(state, (), detail, ""))
        assert detail in r.detail

    def test_a_reachable_local_server_with_a_model_is_ready(self):
        r = _ready(provider="local", api_key="", model="qwen2.5:7b",
                   probe=D.Detection(D.READY, ("qwen2.5:7b",), "", ""))
        assert r.code == ss.READY
        assert r.can_run is True


class TestTheExistingStatesAreUnchanged:
    """The extension contract: none of them changes a state that already
    exists."""

    def test_openai_without_a_key_still_reports_no_key(self):
        assert _ready(api_key="  ").code == ss.NO_KEY

    def test_a_missing_model_still_reports_no_model(self):
        assert _ready(model=" ").code == ss.NO_MODEL

    def test_a_missing_bundle_still_wins(self):
        assert _ready(has_bundle=False, api_key="", model="").code == ss.NO_BUNDLE

    def test_a_ready_configuration_returns_the_normalised_model(self):
        assert _ready(model="  gpt-4o-mini ").model == "gpt-4o-mini"

    def test_every_code_is_declared(self):
        """A code the popup needs but the vocabulary does not carry would
        be a finding about the extension mechanism, not a licence to bolt
        one on."""
        for code in (ss.READY, ss.NO_BUNDLE, ss.NO_KEY, ss.NO_MODEL,
                     ss.NOT_CONFIGURED, ss.NOT_CHECKED,
                     ss.ENDPOINT_UNREACHABLE, ss.NO_MODELS_PULLED):
            assert code in ss.READINESS_CODES


# ---------------------------------------------------------------------------
# The fresh install, end to end
# ---------------------------------------------------------------------------

class TestAFreshInstall:
    """No settings file, no .env, no key, no Ollama — the state the brief
    names as this session's specific risk, because session A made it worse
    rather than better."""

    @pytest.fixture
    def pristine(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        return tmp_path

    def test_nothing_is_configured(self, pristine):
        cfg = S.load_settings()
        assert cfg["provider"] == S.UNCHOSEN
        assert cfg["api_key"] == ""
        assert not S.settings_path().exists(), "reading must not create it"

    def test_the_llm_stages_are_blocked(self, pristine):
        cfg = S.load_settings()
        r = ss.llm_readiness(stage="EL", has_bundle=True,
                             provider=cfg["provider"], api_key=cfg["api_key"],
                             model=cfg["model"], probe=None)
        assert r.can_run is False
        assert r.code == ss.NOT_CONFIGURED

    def test_the_engine_gate_agrees(self, pristine):
        import plugins._common.llm_client as lc
        assert lc._has_openai_key() is False

    def test_nothing_routes_to_a_paid_endpoint_by_default(self, pristine):
        """The regression session A shipped and its review caught: a fresh
        install must not be silently 'local' and therefore keyless, while
        the call still goes to the vendor."""
        import plugins._common.llm_client as lc
        assert lc.resolve_openai_base_url() == lc.DEFAULT_OPENAI_BASE_URL

    def test_a_fresh_install_is_no_worse_off_than_before_this_wave(
            self, pristine):
        """The specific shape to watch for. Before wave 11 an unconfigured
        user was blocked at NO_KEY. They must still be blocked — by a
        clearer state, but blocked."""
        cfg = S.load_settings()
        r = ss.llm_readiness(stage="EL", has_bundle=True,
                             provider=cfg["provider"], api_key=cfg["api_key"],
                             model=cfg["model"], probe=None)
        assert r.can_run is False


class TestTheProbeCache:
    """Detection runs off the GUI thread and deposits its answer; the
    stage views read it synchronously inside Tk callbacks, where a network
    call is exactly what must not happen."""

    def setup_method(self):
        D.forget()

    def teardown_method(self):
        D.forget()

    def test_nothing_checked_yet_reads_as_none(self):
        assert D.last_known() is None

    def test_a_remembered_probe_is_returned(self):
        d = D.Detection(D.READY, ("m",), "", "")
        D.remember(d)
        assert D.last_known() is d

    def test_a_provider_change_forgets_the_previous_answer(self):
        """The previous answer describes a server the user is no longer
        pointing at. Reporting it would be a stale-cache defect."""
        D.remember(D.Detection(D.READY, ("m",), "", ""))
        D.forget()
        assert D.last_known() is None

    def test_refresh_caches_what_it_found(self, monkeypatch):
        sentinel = D.Detection(D.NOT_RUNNING, (), "start it", "")
        monkeypatch.setattr(D, "detect", lambda *a, **k: sentinel)
        assert D.refresh("http://x/v1") is sentinel
        assert D.last_known() is sentinel

    def test_an_uncached_probe_blocks_the_run_rather_than_enabling_it(self):
        """The direction that matters. If this defaulted to optimistic,
        every launch would enable Run before anything had been checked."""
        r = ss.llm_readiness(stage="EL", has_bundle=True, provider="local",
                             api_key="", model="m", probe=D.last_known())
        assert r.can_run is False
        assert r.code == ss.NOT_CHECKED
