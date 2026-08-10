# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_stage_endpoint_invariant.py — session C: the invariant, over the
cross product a per-stage endpoint opens.

The rule, in two clauses
------------------------
**INV-1** — *a keyless provider never resolves to the paid vendor.*
Session B's, closed over the class rather than the instance. It is a rule
about the **fallback**: it fires when nothing named an endpoint.

**INV-1b** — *an effective endpoint that is the paid vendor is never
keyless.* Session C's, and it exists because INV-1 does not cover the
route this session opens. With a per-stage endpoint the provider and the
endpoint move **independently**, so

    provider = "local"                       -> key_required is False
    stages["EL"]["endpoint"] = the vendor    -> reached EXPLICITLY

is a keyless stage pointed straight at a billing host, and INV-1 never
fires because nothing fell back. That is the third route to this wave's
billing defect: session A produced it with a default that presumed a
provider, session B with a blank field that presumed an endpoint, and a
per-stage override produces it with no presumption at all — the user
simply typed a URL into the stage they were working in.

Both clauses are asserted over the **cross product** of provider ×
endpoint × key, not over the two routes that happen to be known, because
patching routes is what left the hole open twice.

What is deliberately NOT overridable
------------------------------------
``provider``. ``settings.STAGE_OVERRIDABLE`` refuses it, and the reason
is invariant 2: ``llm_readiness`` checks ``NOT_CONFIGURED`` **ahead of**
the key and model checks precisely because those can each be satisfied
while the path as a whole is unconfigured. A stage-level provider would
let a stage acquire an effective provider while the application is still
``UNCHOSEN`` — a path reaching a run without passing that check.
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


S = _load("_settings_for_invariant", "plugins/_common/settings.py")

VENDOR = "https://api.openai.com/v1"
LOCAL = "http://localhost:11434/v1"
ELSEWHERE = "http://elsewhere.invalid:8080/v1"

KEYLESS_PROVIDERS = ("local", "custom")
ALL_PROVIDERS = ("local", "custom", "openai", "", "something-new")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return S


# ---------------------------------------------------------------------------
# The two constants must not drift
# ---------------------------------------------------------------------------

class TestTheVendorIsNamedOnce:
    """``stage_state`` holds the billing hosts as bare strings because
    ``settings`` imports it, not the other way round. That is an import
    constraint, not a licence for two lists."""

    def test_the_vendor_default_endpoint_is_recognised_as_billing(self):
        assert ss.is_paid_vendor(S.DEFAULT_OPENAI_ENDPOINT) is True

    def test_the_llm_client_default_is_recognised_as_billing(self):
        import plugins._common.llm_client as lc
        assert ss.is_paid_vendor(lc.DEFAULT_OPENAI_BASE_URL) is True

    def test_the_local_default_is_not(self):
        assert ss.is_paid_vendor(S.DEFAULT_LOCAL_ENDPOINT) is False


class TestTheHostIsParsedRatherThanMatched:

    @pytest.mark.parametrize("endpoint", [
        "https://api.openai.com/v1",
        "https://api.openai.com/v1/",
        "https://API.OpenAI.com/v1",
        "https://api.openai.com:443/v1",
        "api.openai.com/v1",                  # a user typing it by hand
        "https://api.openai.com",
    ])
    def test_every_spelling_of_the_vendor_is_recognised(self, endpoint):
        assert ss.is_paid_vendor(endpoint) is True, endpoint

    @pytest.mark.parametrize("endpoint", [
        "http://api.openai.com.example.invalid/v1",   # a lookalike host
        "http://localhost:11434/v1",
        "http://127.0.0.1:8080/v1",
        "https://example.invalid/api.openai.com/v1",  # the name in the path
        "", "   ", None,
    ])
    def test_nothing_else_is(self, endpoint):
        assert ss.is_paid_vendor(endpoint) is False, endpoint


# ---------------------------------------------------------------------------
# INV-1b, over the cross product
# ---------------------------------------------------------------------------

class TestAVendorEndpointIsNeverKeyless:

    @pytest.mark.parametrize("provider", ALL_PROVIDERS)
    def test_the_vendor_endpoint_always_requires_a_key(self, provider):
        assert ss.key_required_for(provider, VENDOR) is True, provider

    @pytest.mark.parametrize("provider", KEYLESS_PROVIDERS)
    @pytest.mark.parametrize("endpoint", [LOCAL, ELSEWHERE, "", None])
    def test_a_keyless_provider_elsewhere_stays_keyless(
            self, provider, endpoint):
        """The direction that must **not** change: this session must not
        re-introduce the credential-for-a-free-model gate F-117 removed."""
        assert ss.key_required_for(provider, endpoint) is False

    @pytest.mark.parametrize("provider", ALL_PROVIDERS)
    @pytest.mark.parametrize("endpoint", [VENDOR, LOCAL, ELSEWHERE, "", None])
    @pytest.mark.parametrize("api_key", ["", "   ", "sk-real"])
    def test_the_gate_is_never_open_without_a_key_at_a_billing_host(
            self, provider, endpoint, api_key):
        """The whole cross product, as one property.

        Patching the two routes that were known is what left this hole
        open twice; this asserts the class."""
        open_gate = ss.key_ok(provider=provider, api_key=api_key,
                              endpoint=endpoint)
        if ss.is_paid_vendor(endpoint) and not api_key.strip():
            assert open_gate is False, (
                f"provider={provider!r} endpoint={endpoint!r} "
                f"key={api_key!r}: a billing host with no key"
            )

    def test_the_credential_handed_to_a_billing_host_is_never_a_placeholder(
            self):
        """``placeholder_key_for`` exists so a local user need not invent
        a credential. Handing the literal string 'local' to a host that
        bills is that convenience becoming the defect."""
        assert S.placeholder_key_for("local", "", endpoint=VENDOR) == ""
        assert S.placeholder_key_for("local", "", endpoint=LOCAL) \
            == S.PLACEHOLDER_KEY


# ---------------------------------------------------------------------------
# INV-1, still true, now over per-stage resolution
# ---------------------------------------------------------------------------

class TestAKeylessProviderNeverFallsBackToTheVendor:

    @pytest.mark.parametrize("provider", KEYLESS_PROVIDERS)
    @pytest.mark.parametrize("stage", ["", "EL", "IL"])
    @pytest.mark.parametrize("endpoint", ["", "   "])
    def test_a_blank_endpoint_never_becomes_the_vendor(
            self, store, provider, stage, endpoint):
        store.update_settings(provider=provider, endpoint=endpoint,
                              api_key="sk-left-over")
        cfg = store.resolve_stage(store.load_settings(), stage)
        assert cfg.endpoint != S.DEFAULT_OPENAI_ENDPOINT
        assert ss.is_paid_vendor(cfg.endpoint) is False

    @pytest.mark.parametrize("provider", KEYLESS_PROVIDERS)
    def test_a_blank_stage_override_falls_through_rather_than_to_the_vendor(
            self, store, provider):
        """An override cleared to whitespace clears the entry, so the
        stage falls back to the application setting — which for a keyless
        provider is the local default, not the vendor."""
        store.update_settings(provider=provider, endpoint="")
        store.set_stage_override("EL", endpoint="   ")
        cfg = store.resolve_stage(store.load_settings(), "EL")
        assert ss.is_paid_vendor(cfg.endpoint) is False

    def test_openai_still_resolves_to_the_vendor(self, store):
        store.update_settings(provider="openai", endpoint="")
        cfg = store.resolve_stage(store.load_settings(), "EL")
        assert cfg.endpoint == S.DEFAULT_OPENAI_ENDPOINT


# ---------------------------------------------------------------------------
# The route this session opens, end to end
# ---------------------------------------------------------------------------

class TestThePerStageRouteEndToEnd:
    """Executed against the real store and the real resolver, because a
    defect about what a configuration *does* is not settled by reading."""

    def test_a_local_stage_pointed_at_the_vendor_cannot_run(self, store):
        import plugins._common.llm_client as lc
        store.update_settings(provider="local", endpoint=LOCAL, api_key="",
                              model="qwen2.5:7b")
        store.set_stage_override("EL", endpoint=VENDOR)

        assert lc.resolve_openai_base_url("EL") == VENDOR
        assert lc.resolve_openai_base_url("IL") == LOCAL

        # The engine gate, which is what actually stops the call.
        assert lc._has_openai_key("EL") is False
        assert lc._has_openai_key("IL") is True

        cfg = store.resolve_stage(store.load_settings(), "EL")
        r = ss.llm_readiness(stage="EL", has_bundle=True,
                             provider=cfg.provider, api_key=cfg.api_key,
                             model=cfg.model, endpoint=cfg.endpoint,
                             probe=None)
        assert r.can_run is False

    def test_the_credential_that_would_have_been_sent(self, store,
                                                      monkeypatch):
        """The measurement session A's and session B's reviews both
        turned on: what string would actually reach the wire."""
        store.update_settings(provider="local", endpoint=LOCAL, api_key="")
        store.set_stage_override("EL", endpoint=VENDOR)
        cfg = store.resolve_stage(store.load_settings(), "EL")
        sent = S.placeholder_key_for(cfg.provider, cfg.api_key,
                                     endpoint=cfg.endpoint)
        assert sent == "", (
            f"a keyless stage pointed at the vendor would have sent "
            f"{sent!r} as its credential"
        )

    def test_the_client_is_built_against_the_stage_endpoint(self, store,
                                                            monkeypatch):
        import openai
        import plugins._common.llm_client as lc

        seen = {}

        class _Recorder:
            def __init__(self, **kwargs):
                seen.update(kwargs)

        monkeypatch.setattr(openai, "OpenAI", _Recorder)
        store.update_settings(provider="local", endpoint=LOCAL, api_key="")
        store.set_stage_override("EL", endpoint=ELSEWHERE)

        lc._openai_client_for("EL")
        assert seen["base_url"] == ELSEWHERE
        seen.clear()
        lc._openai_client_for("IL")
        assert seen["base_url"] == LOCAL


# ---------------------------------------------------------------------------
# Invariant 2 — nothing may acquire a provider per stage
# ---------------------------------------------------------------------------

class TestAStageCannotChooseItsOwnProvider:

    def test_the_overridable_set_is_closed(self):
        assert set(S.STAGE_OVERRIDABLE) == {"model", "endpoint", "batch_size"}
        assert "provider" not in S.STAGE_OVERRIDABLE
        assert "api_key" not in S.STAGE_OVERRIDABLE

    @pytest.mark.parametrize("key", ["provider", "api_key", "schema"])
    def test_an_override_of_anything_else_is_refused(self, store, key):
        with pytest.raises(S.StageOverrideRefused):
            store.set_stage_override("EL", **{key: "local"})

    def test_a_hand_edited_stage_provider_is_ignored_rather_than_honoured(
            self, store):
        """A settings file is user-editable, so refusing at the setter is
        not enough — the resolver must not read one either."""
        import json
        store.settings_path().parent.mkdir(parents=True, exist_ok=True)
        store.settings_path().write_text(json.dumps({
            "schema": 1, "provider": "", "endpoint": "", "api_key": "",
            "model": "", "stages": {"EL": {"provider": "local",
                                           "model": "m"}},
        }), encoding="utf-8")
        cfg = store.resolve_stage(store.load_settings(), "EL")
        assert cfg.provider == "", (
            "a stage that could name its own provider would escape the "
            "NOT_CONFIGURED check that sits ahead of the key and model ones"
        )
        r = ss.llm_readiness(stage="EL", has_bundle=True,
                             provider=cfg.provider, api_key=cfg.api_key,
                             model=cfg.model, endpoint=cfg.endpoint,
                             probe=None)
        assert r.code == ss.NOT_CONFIGURED


# ---------------------------------------------------------------------------
# NOT_CONFIGURED keeps its place at the front
# ---------------------------------------------------------------------------

class TestNotConfiguredStillComesFirst:
    """Session B's second invariant. Per-stage overrides must not create
    a path that reaches a run without passing this check."""

    @pytest.mark.parametrize("endpoint", [VENDOR, LOCAL, ELSEWHERE])
    @pytest.mark.parametrize("api_key", ["", "sk-real"])
    @pytest.mark.parametrize("model", ["", "qwen2.5:7b"])
    def test_no_combination_of_overrides_makes_an_unchosen_provider_run(
            self, endpoint, api_key, model):
        r = ss.llm_readiness(stage="EL", has_bundle=True, provider="",
                             api_key=api_key, model=model, endpoint=endpoint,
                             probe=None)
        assert r.can_run is False
        assert r.code == ss.NOT_CONFIGURED, (
            f"endpoint={endpoint!r} key={api_key!r} model={model!r} reached "
            f"{r.code} instead of the unconfigured check"
        )

    def test_the_order_is_asserted_rather_than_assumed(self):
        """NOT_CONFIGURED must beat NO_KEY even when the endpoint bills,
        because the first thing to fix is still the choice."""
        r = ss.llm_readiness(stage="EL", has_bundle=True, provider="",
                             api_key="", model="m", endpoint=VENDOR,
                             probe=None)
        assert r.code == ss.NOT_CONFIGURED


# ---------------------------------------------------------------------------
# The application level is byte-identical to what it was
# ---------------------------------------------------------------------------

class TestTheApplicationLevelIsUnchanged:
    """What keeps the golden replays valid. An unconfigured install must
    reduce to exactly the expression that predates per-stage anything."""

    def test_an_unconfigured_install_resolves_to_the_vendor_default(
            self, store):
        import plugins._common.llm_client as lc
        assert lc.resolve_openai_base_url() == lc.DEFAULT_OPENAI_BASE_URL
        assert lc.resolve_openai_base_url("EL") == lc.DEFAULT_OPENAI_BASE_URL

    def test_the_environment_still_wins_over_nothing(self, store,
                                                     monkeypatch):
        import plugins._common.llm_client as lc
        monkeypatch.setenv("OPENAI_BASE_URL", ELSEWHERE)
        assert lc.resolve_openai_base_url() == ELSEWHERE
        assert lc.resolve_openai_base_url("EL") == ELSEWHERE

    def test_a_stored_endpoint_still_wins_over_the_environment(
            self, store, monkeypatch):
        """F-91's family: a stale variable beating the control the user
        just operated would make that control do nothing."""
        import plugins._common.llm_client as lc
        monkeypatch.setenv("OPENAI_BASE_URL", "http://stale.invalid/v1")
        store.update_settings(provider="custom", endpoint=ELSEWHERE)
        assert lc.resolve_openai_base_url() == ELSEWHERE
        assert lc.resolve_openai_base_url("EL") == ELSEWHERE

    @pytest.mark.parametrize("stage", ["", "EL", "IL", "unknown-stage"])
    def test_every_stage_agrees_when_no_override_exists(self, store, stage):
        """The property the goldens rest on, stated as one assertion."""
        import plugins._common.llm_client as lc
        store.update_settings(provider="openai", endpoint="", api_key="sk-x")
        assert lc.resolve_openai_base_url(stage) == \
            lc.resolve_openai_base_url()


class TestTheResolvedSourceIsReported:
    """F-119's lesson: say which source won. 'endpoint=…openai.com/v1'
    alone does not distinguish *I chose the public API* from *my
    configuration was not read*."""

    def test_each_source_is_named(self, store, monkeypatch):
        cfg = store.load_settings()
        assert store.resolve_stage(cfg).endpoint_source == \
            S.ENDPOINT_FROM_VENDOR_DEFAULT

        assert store.resolve_stage(cfg, env_endpoint=ELSEWHERE) \
            .endpoint_source == S.ENDPOINT_FROM_ENVIRONMENT

        store.update_settings(provider="local", endpoint="")
        assert store.resolve_stage(store.load_settings()).endpoint_source == \
            S.ENDPOINT_FROM_KEYLESS_DEFAULT

        store.update_settings(endpoint=ELSEWHERE)
        assert store.resolve_stage(store.load_settings()).endpoint_source == \
            S.ENDPOINT_FROM_APP

        store.set_stage_override("EL", endpoint=LOCAL)
        assert store.resolve_stage(store.load_settings(), "EL") \
            .endpoint_source == S.ENDPOINT_FROM_STAGE
