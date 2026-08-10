# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_review_repairs.py — the defects session C's review found by executing,
each pinned by the configuration that produced it.

Six survived refutation and are repaired here. Two of them are the same
mistake in different clothes: **a value that is right for the application
was applied to a stage that had moved.**

1. **One probe answered for every stage.** The application probed its own
   endpoint and deposited the answer in a single global; a stage with an
   endpoint override read it and reported ``Ready to run`` while its own
   server had nothing listening. That breaks the property session B built
   — *ready means reachable* — for the very feature session C added.
   Measured before the repair:

       app endpoint probed : ... -> ready
       EL readiness        : ready can_run=True 'Ready to run'
       direct probe of EL's own endpoint: not_installed

2. **An untouched tab pinned its module defaults.** ``stage_overrides_for``
   compared the field against a baseline computed *without* the stage's
   own defaults, so ``model='gpt-4o-mini'`` and ``batch_size=50`` — the
   values the widget is seeded with when the store says nothing — looked
   like deliberate edits. Opening a tab once and leaving any field pinned
   them permanently:

       stages after ONE field-exit : {"EL": {"batch_size": 50,
                                             "model": "gpt-4o-mini"}}
       ... user then chooses local ...
       EL resolves : batch=50  model='gpt-4o-mini'   <- D6 defeated
       IL resolves : batch=5   model='qwen2.5:7b'    <- never opened

   So D6 and the user's own model choice reached only the stages they had
   *not* opened, and the two stages silently diverged.

3. **The trailing-dot FQDN defeated INV-1b.** ``api.openai.com.`` is the
   same host to DNS and a different string to a comparison, so
   ``key_required_for("local", "https://api.openai.com./v1")`` was
   ``False`` — a keyless provider reaching the paid vendor, by one
   character. The fourth route to this wave's recurring defect.

4. **The batch size asked the provider name and never the endpoint**, so a
   stage whose provider said ``local`` and whose endpoint pointed at the
   vendor ran at 5. The criterion and system prompt are re-sent with every
   batch, so that is roughly ten times those tokens — a bill, not a wait.

5. **``sanitize_api_key`` was bounded at four passes** while its docstring
   claimed idempotence "by construction". Deeply nested quotes were not
   reduced to a fixed point, so the central claim was false.

6. **The harmoniser's discovery label had no ``wraplength``**, so D4/D5's
   message — the one carrying the remedy — was clipped. The overflow shape
   session B shipped, in a new label.

**Why my own tests missed 1 and 2**, recorded because it is the more
useful half: ``test_stage_fields.py`` asserted *"an untouched field pins
nothing"* — and set the application level first, so the field it checked
was already backed by the store. **The fresh-install case, which is the
state every user starts in, was never exercised.** A test that covers the
configured path and calls it coverage is the same shape as session B's
fixture that asserted a state the system could not reach.
"""
import importlib.util
import sys

import pytest

from conftest import PROJECT_ROOT
from helpers_fake_server import dead_url, serve_models

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


S = _load("_settings_for_repairs", "plugins/_common/settings.py")
D = _load("_detect_for_repairs", "plugins/_common/provider_detect.py")

VENDOR = "https://api.openai.com/v1"
LOCAL = "http://localhost:11434/v1"

#: What the EL/IL tabs seed their widgets with when the store says nothing.
STAGE_FALLBACKS = {"model": "gpt-4o-mini", "batch_size": 50}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return S


@pytest.fixture(autouse=True)
def _clean_probes():
    D.forget()
    yield
    D.forget()


# ---------------------------------------------------------------------------
# 1. The probe is per endpoint
# ---------------------------------------------------------------------------

class TestOneProbeNoLongerAnswersForEveryStage:

    def test_a_stage_with_its_own_endpoint_does_not_inherit_an_answer(self):
        url, stop = serve_models(["app-model"])
        try:
            D.refresh(url, provider="custom")
        finally:
            stop()
        assert D.last_known(url) is not None
        assert D.last_known("http://elsewhere.invalid:9/v1") is None, (
            "a stage nobody probed must read 'not checked', not somebody "
            "else's answer"
        )

    def test_an_unprobed_stage_blocks_rather_than_reporting_ready(self):
        """The measured defect, as an assertion. Before the repair this
        returned ``ready`` for a stage whose endpoint was dead."""
        url, stop = serve_models(["app-model"])
        try:
            D.refresh(url, provider="custom")
        finally:
            stop()
        stage_endpoint = dead_url()
        r = ss.llm_readiness(stage="EL", has_bundle=True, provider="custom",
                             api_key="", model="m", endpoint=stage_endpoint,
                             probe=D.last_known(stage_endpoint))
        assert r.can_run is False
        assert r.code == ss.NOT_CHECKED

    def test_the_combobox_offers_this_stage_s_models_not_another_s(self):
        app, stop_a = serve_models(["app-only"])
        stage, stop_s = serve_models(["stage-only"])
        try:
            D.refresh(app, provider="custom")
            D.refresh(stage, provider="custom")
        finally:
            stop_a(); stop_s()
        assert D.model_choices(D.last_known(stage)).values == ("stage-only",)
        assert D.model_choices(D.last_known(app)).values == ("app-only",)

    def test_one_server_is_one_entry(self):
        """Trailing slashes and case are not routing differences. Two
        entries for one server would let the tab that probed and the tab
        that reads disagree about a server they both point at."""
        url, stop = serve_models(["m"])
        try:
            D.refresh(url, provider="custom")
        finally:
            stop()
        assert D.last_known(url + "/") is not None
        assert D.last_known(url.upper().replace("HTTP", "http")) is not None
        assert len(D.known_endpoints()) == 1

    def test_forget_clears_every_server(self):
        """A provider change invalidates every stage's answer, not one."""
        a, sa = serve_models(["a"]); b, sb = serve_models(["b"])
        try:
            D.refresh(a, provider="custom"); D.refresh(b, provider="custom")
        finally:
            sa(); sb()
        assert len(D.known_endpoints()) == 2
        D.forget()
        assert D.known_endpoints() == ()

    def test_the_no_argument_form_refuses_to_guess(self):
        """It answers only when exactly one server has been probed, so a
        multi-endpoint configuration cannot silently pick one."""
        a, sa = serve_models(["a"]); b, sb = serve_models(["b"])
        try:
            D.refresh(a, provider="custom")
            assert D.last_known() is not None
            D.refresh(b, provider="custom")
            assert D.last_known() is None
        finally:
            sa(); sb()

    def test_the_launch_path_probes_every_stage_endpoint(self):
        """The corollary of keying by endpoint: an unprobed stage blocks
        forever unless something probes it. Asserted on ``main.py``'s
        source, because ``MetaScreenerApp`` cannot be built here."""
        import ast
        tree = ast.parse((PROJECT_ROOT / "metascreener" / "main.py")
                         .read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_refresh_provider_status")
        body = ast.unparse(fn)
        assert "LLM_STAGES" in body
        assert "resolve_openai_base_url(stage)" in body

    def test_every_llm_stage_is_named_in_one_place(self):
        assert set(S.LLM_STAGES) == {"EL", "IL", "harmoniser"}


# ---------------------------------------------------------------------------
# 2. An untouched tab pins nothing — including on a fresh install
# ---------------------------------------------------------------------------

class TestAFreshTabPinsNothing:
    """The case the original test missed: no application setting at all,
    so the widget shows a *module* default the store has never seen."""

    def test_opening_a_tab_and_leaving_a_field_writes_no_override(
            self, store):
        seed = store.resolve_stage(store.load_settings(), "EL")
        var_model = seed.model or STAGE_FALLBACKS["model"]
        var_batch = str(seed.batch_size if seed.batch_size is not None
                        else STAGE_FALLBACKS["batch_size"])

        store.apply_stage_fields("EL", fallbacks=STAGE_FALLBACKS,
                                 model=var_model, endpoint=seed.endpoint,
                                 batch_size=var_batch)
        assert store.load_settings()["stages"] == {}

    def test_d6_still_reaches_a_stage_that_has_been_opened(self, store):
        """The harm, as an assertion. The stage the user looked at must
        not be the one that misses the local batch size."""
        seed = store.resolve_stage(store.load_settings(), "EL")
        store.apply_stage_fields(
            "EL", fallbacks=STAGE_FALLBACKS,
            model=seed.model or STAGE_FALLBACKS["model"],
            endpoint=seed.endpoint,
            batch_size=str(STAGE_FALLBACKS["batch_size"]))

        store.update_settings(provider="local", endpoint=LOCAL,
                              model="qwen2.5:7b")
        opened = store.resolve_stage(store.load_settings(), "EL")
        untouched = store.resolve_stage(store.load_settings(), "IL")
        assert opened.batch_size == ss.LOCAL_BATCH_SIZE
        assert opened.model == "qwen2.5:7b"
        assert (opened.batch_size, opened.model) == \
               (untouched.batch_size, untouched.model), (
            "the stage the user opened and the stage they did not must not "
            "silently diverge"
        )

    def test_the_environment_endpoint_is_not_pinned_either(
            self, store, monkeypatch):
        """The same defect on the endpoint: the tab seeds from a
        resolution that reads OPENAI_BASE_URL and the baseline did not.

        The provider has to be one that *needs* a key, because a keyless
        provider never reaches the environment branch at all — INV-1 sends
        it to the local default first, which is the whole point of that
        rule and is asserted elsewhere.
        """
        env = "http://from-env.invalid/v1"
        monkeypatch.setenv("OPENAI_BASE_URL", env)
        store.update_settings(provider="openai", endpoint="", api_key="sk-x")
        shown = store.resolve_stage(store.load_settings(), "EL",
                                    env_endpoint=env).endpoint
        assert shown == env, "the environment must reach the widget"
        store.apply_stage_fields("EL", fallbacks=STAGE_FALLBACKS,
                                 endpoint=shown)
        assert store.load_settings()["stages"] == {}

    def test_a_keyless_provider_never_reaches_the_environment_branch(
            self, store, monkeypatch):
        """Stated here because the test above depends on it: INV-1 sends
        a keyless provider to the local default ahead of OPENAI_BASE_URL,
        so a stale export cannot point a 'local' run anywhere else."""
        monkeypatch.setenv("OPENAI_BASE_URL", "http://from-env.invalid/v1")
        store.update_settings(provider="custom", endpoint="")
        got = store.resolve_stage(store.load_settings(), "EL",
                                  env_endpoint="http://from-env.invalid/v1")
        assert got.endpoint == S.DEFAULT_LOCAL_ENDPOINT
        assert got.endpoint_source == S.ENDPOINT_FROM_KEYLESS_DEFAULT

    def test_a_real_edit_is_still_stored(self, store):
        """The repair must not have turned the feature off."""
        store.apply_stage_fields("EL", fallbacks=STAGE_FALLBACKS,
                                 model="a-different-model",
                                 batch_size="7")
        got = store.resolve_stage(store.load_settings(), "EL")
        assert (got.model, got.batch_size) == ("a-different-model", 7)

    @pytest.mark.parametrize("rel", ["plugins/06_el/ui.py",
                                     "plugins/07_il/ui.py",
                                     "plugins/03_harmoniser/ui.py"])
    def test_every_view_passes_its_fallbacks(self, rel):
        src = PROJECT_ROOT.joinpath(*rel.split("/")).read_text(
            encoding="utf-8")
        assert "fallbacks=" in src, rel


# ---------------------------------------------------------------------------
# 3. INV-1b and the trailing dot
# ---------------------------------------------------------------------------

class TestTheFullyQualifiedFormIsTheSameHost:

    @pytest.mark.parametrize("endpoint", [
        "https://api.openai.com./v1",
        "https://API.OPENAI.COM./v1",
        "https://api.openai.com.:443/v1",
        "api.openai.com./v1",
        "https://api.openai.com../v1",
    ])
    def test_it_is_recognised_as_billing(self, endpoint):
        assert ss.is_paid_vendor(endpoint) is True, endpoint

    @pytest.mark.parametrize("endpoint", [
        "https://api.openai.com./v1", "https://API.OPENAI.COM./v1"])
    def test_a_keyless_provider_there_still_needs_a_key(self, endpoint):
        assert ss.key_required_for("local", endpoint) is True
        assert ss.key_ok(provider="local", api_key="",
                         endpoint=endpoint) is False

    def test_a_lookalike_with_a_dot_is_still_not_the_vendor(self):
        assert ss.is_paid_vendor(
            "https://api.openai.com.example.invalid./v1") is False


# ---------------------------------------------------------------------------
# 4. The batch size asks the pair
# ---------------------------------------------------------------------------

class TestTheBatchSizeAsksWhereTheStagePoints:

    def test_a_local_provider_pointed_at_the_vendor_gets_no_suggestion(self):
        assert ss.recommended_batch_size("local", VENDOR) is None
        assert ss.recommended_batch_size("local", LOCAL) == \
            ss.LOCAL_BATCH_SIZE

    def test_the_resolver_agrees(self, store):
        store.update_settings(provider="local", endpoint=LOCAL)
        store.set_stage_override("EL", endpoint=VENDOR)
        assert store.resolve_stage(store.load_settings(), "EL").batch_size \
            is None
        assert store.resolve_stage(store.load_settings(), "IL").batch_size \
            == ss.LOCAL_BATCH_SIZE

    def test_the_tooltip_follows(self):
        """A reason beside a number that is no longer the number would be
        worse than no reason."""
        local = ss.batch_size_tooltip("local", LOCAL)
        billed = ss.batch_size_tooltip("local", VENDOR)
        assert local != billed
        assert "local provider is selected" in billed

    def test_the_denial_survives_both_wordings(self):
        for endpoint in (LOCAL, VENDOR, None):
            text = ss.batch_size_tooltip("local", endpoint)
            assert "A smaller batch does not make a run safer" in text
            assert "does not invalidate your cache" in text


# ---------------------------------------------------------------------------
# 5. sanitize_api_key really is a fixed point
# ---------------------------------------------------------------------------

def _akd():
    pytest.importorskip("tkinter",
                        reason="api_key_dialog imports tkinter at import time")
    return _load("_akd_for_repairs", "metascreener/api_key_dialog.py")


class TestSanitiseReachesAFixedPoint:

    @pytest.mark.parametrize("depth", [1, 2, 4, 5, 9, 12, 40])
    def test_however_deeply_quoted(self, depth):
        m = _akd()
        raw = ('"' * depth) + " sk-abc " + ("'" * depth)
        once = m.sanitize_api_key(raw)
        assert m.sanitize_api_key(once) == once, (depth, repr(once))

    def test_the_bound_that_made_the_docstring_false_is_gone(self):
        """It was capped at four passes while claiming idempotence 'by
        construction'. Each pass strictly shortens or returns, so the
        loop terminates without a cap — the cap was the only thing
        making the claim false."""
        src = (PROJECT_ROOT / "metascreener" / "api_key_dialog.py").read_text(
            encoding="utf-8")
        assert "_SANITIZE_PASSES" not in src

    def test_a_deeply_quoted_key_still_arrives_intact(self):
        m = _akd()
        assert m.sanitize_api_key('"""  sk-real-key  """') == "sk-real-key"


# ---------------------------------------------------------------------------
# 6. The label that carries the remedy must not be clipped
# ---------------------------------------------------------------------------

class TestEveryDiscoveryLabelWraps:
    """D4/D5's messages are sentences, and the one carrying the remedy is
    the longest of them. A label without ``wraplength`` clips it — the
    overflow shape session B shipped, which is why this is asserted for
    every view rather than the one the review measured."""

    @pytest.mark.parametrize("rel", ["plugins/06_el/ui.py",
                                     "plugins/07_il/ui.py",
                                     "plugins/03_harmoniser/ui.py"])
    def test_the_models_label_sets_a_wraplength(self, rel):
        import ast
        tree = ast.parse(PROJECT_ROOT.joinpath(*rel.split("/")).read_text(
            encoding="utf-8"))
        found = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign)
                    and isinstance(node.value, ast.Call)):
                continue
            if not any(isinstance(t, ast.Attribute)
                       and t.attr in ("lbl_models", "lbl_endpoint_src")
                       for t in node.targets):
                continue
            kw = {k.arg for k in node.value.keywords}
            found.append((node.lineno, "wraplength" in kw))
        assert found, rel
        assert all(has for _line, has in found), (rel, found)

    def test_the_longest_message_is_longer_than_any_sensible_label(self):
        """Why this matters at all, measured rather than asserted by
        eye: the not-installed remedy is a paragraph."""
        longest = max(len(D.detect("http://127.0.0.1:1/v1", timeout=0.2,
                                   which=w).detail)
                      for w in (lambda _n: None, lambda _n: "/bin/ollama"))
        assert longest > 120, longest


# ---------------------------------------------------------------------------
# 7. A malformed stages entry must not delete a tab
# ---------------------------------------------------------------------------

class TestAMalformedStageEntryDegradesRatherThanDeletingAStage:
    """§10.2's defect one level deeper. ``load_settings`` validated the
    stages container and its entries but not the values inside an entry,
    so a non-string endpoint escaped into ``resolve_stage`` and out
    through ``.strip()`` — inside ``_build_ui``, where
    ``main.py::resolve_plugin_entrypoint`` swallows every exception into
    a ``print()``. The tab was silently absent."""

    @pytest.mark.parametrize("bad", [
        {"endpoint": ["http://x/v1"]},
        {"endpoint": 11434},
        {"model": {"name": "m"}},
        {"model": None},
        {"batch_size": "not a number"},
        {"batch_size": True},
        {"endpoint": None, "model": 5, "batch_size": []},
    ])
    def test_it_falls_back_to_the_application_setting(self, store, bad):
        import json
        store.settings_path().parent.mkdir(parents=True, exist_ok=True)
        store.settings_path().write_text(json.dumps({
            "schema": 1, "provider": "local", "endpoint": LOCAL,
            "api_key": "", "model": "app-model", "stages": {"EL": bad},
        }), encoding="utf-8")
        got = store.resolve_stage(store.load_settings(), "EL")
        assert got.endpoint == LOCAL
        assert got.model == "app-model"
        assert isinstance(got.batch_size, (int, type(None)))

    def test_a_wrong_type_is_dropped_rather_than_coerced(self, store):
        """``str(["http://…"])`` would invent a plausible-looking endpoint
        out of a file the user got wrong, and an endpoint is where money
        goes."""
        import json
        store.settings_path().parent.mkdir(parents=True, exist_ok=True)
        store.settings_path().write_text(json.dumps({
            "schema": 1, "provider": "openai", "endpoint": VENDOR,
            "stages": {"EL": {"endpoint": ["http://sneaky/v1"]}},
        }), encoding="utf-8")
        assert store.load_settings()["stages"]["EL"] == {}

    def test_a_good_entry_beside_a_bad_value_survives(self, store):
        import json
        store.settings_path().parent.mkdir(parents=True, exist_ok=True)
        store.settings_path().write_text(json.dumps({
            "schema": 1, "provider": "local", "endpoint": LOCAL,
            "stages": {"EL": {"model": "keep-me", "batch_size": []}},
        }), encoding="utf-8")
        assert store.resolve_stage(store.load_settings(), "EL").model             == "keep-me"


# ---------------------------------------------------------------------------
# 8. No test reads the developer's real settings
# ---------------------------------------------------------------------------

class TestTheSuiteCannotSeeTheRealSettingsDirectory:
    """The golden replays resolve their endpoint per stage now, and the
    endpoint is a cache-key input (F-89) — so a stage override in the
    developer's own settings would change the keys the goldens are
    compared against. The exposure predates session C at the application
    level; session C widened it, and the fix closes it for the suite."""

    def test_the_settings_path_is_not_the_developers(self):
        import tempfile
        p = str(S.settings_dir()).lower()
        assert "metascreener-tests-" in p, p
        assert p.startswith(tempfile.gettempdir().lower())

    def test_a_test_can_still_take_its_own_directory(self, store, tmp_path):
        """The suite-wide default must not stop a test isolating further."""
        assert str(tmp_path).lower() in str(S.settings_dir()).lower()


# ---------------------------------------------------------------------------
# 9. Found by my own smoke run, not by the reviewers
# ---------------------------------------------------------------------------

class TestTheHarmoniserLabelDoesNotOverclaim:
    """Its readiness call passes ``has_bundle=True`` deliberately — this
    stage's inputs are the criteria text and the A vector, and
    ``_ensure_ready`` owns that check. So the Readiness reports only the
    PROVIDER half, and rendering its label verbatim put "Ready to run"
    beside a button disabled for want of criteria. The wording it
    replaced, "API key: OK", reported the same half without claiming
    readiness to run."""

    def test_the_view_does_not_render_ready_to_run_verbatim(self):
        import ast
        tree = ast.parse((PROJECT_ROOT / "plugins" / "03_harmoniser" /
                          "ui.py").read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_refresh_buttons")
        body = ast.unparse(fn)
        assert "Provider ready" in body
        assert "ready.can_run" in body

    def test_the_blocked_wordings_are_still_the_shared_ones(self):
        """Only the satisfied case is reworded. When something IS wrong
        the shared message is exact and must be used verbatim."""
        r = ss.llm_readiness(stage="Harmonise", has_bundle=True,
                             provider="", api_key="", model="m",
                             endpoint=LOCAL, probe=None)
        assert r.can_run is False
        assert r.label == "No provider"
