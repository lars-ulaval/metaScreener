# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_per_stage_config.py — session C, movement one: **characterisation.**

Nothing here is a fix. Every assertion in this file records what the code
does *today*, at each seam session C is about to move, so that the fix
commits flip a visible assertion rather than quietly changing behaviour
nobody had written down. The classes named ``…Today`` are the ones
expected to invert; each says which commit inverts it.

The seams, and why each is a seam
---------------------------------
1. **The endpoint is app-level only.** ``settings.set_stage_override``
   will happily store ``stages["EL"]["endpoint"]`` — session A built the
   override mechanism generically — but ``resolve_openai_base_url`` takes
   no stage and reads only the app-level key. So the store *accepts* a
   per-stage endpoint that nothing honours.

2. **The key gate is decided on the provider string alone.**
   ``key_required("local")`` is ``False`` whatever the endpoint is. That
   is safe while the endpoint is app-level and guarded, and it stops
   being safe the moment a stage can point somewhere else — which is
   what this session adds. See ``TestTheKeylessGateIgnoresTheEndpointToday``.

3. **Discovery flattens.** ``list_models`` returns ``()`` for *did not
   answer*, for *timed out* and for *answered with nothing pulled* alike,
   which are the three states session A went to some trouble to keep
   apart.

4. **The harmoniser decides for itself.** It carries an unread checkbox
   (F-118's remaining half) and its own ``os.getenv`` key indicator —
   a third key predicate, after F-117 unified two.

5. **A lifecycle hook with no receiver.** ``main.py`` notifies
   ``on_provider_changed`` and no plugin implements it.

6. **F-140.** ``sanitize_api_key`` is not idempotent, so the dialog
   validates one string and stores another.
"""
import ast
import importlib.util
import json
import socket
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


S = _load("_settings_for_stage_cfg", "plugins/_common/settings.py")
D = _load("_detect_for_stage_cfg", "plugins/_common/provider_detect.py")


@pytest.fixture
def store(tmp_path, monkeypatch):
    """An empty settings directory, and no ambient endpoint.

    Both variables are set because ``settings_dir`` branches on
    ``os.name`` and the suite runs on all three platforms.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return S


@pytest.fixture
def dead_endpoint():
    """A port nothing is listening on — bound, read, then released."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/v1"


# ---------------------------------------------------------------------------
# 1. The per-stage override mechanism exists and the endpoint does not use it
# ---------------------------------------------------------------------------

class TestTheOverrideMechanismAlreadyWorks:
    """Session A built ``set_stage_override``/``effective`` generically,
    over any key. That half needs no change and is pinned so the session
    can be sure it is building on it rather than round it."""

    def test_a_stage_override_is_stored_and_resolved(self, store):
        store.update_settings(model="app-level")
        store.set_stage_override("EL", model="stage-level")
        cfg = store.load_settings()
        assert store.effective_model(cfg, "EL") == "stage-level"
        assert store.effective_model(cfg, "IL") == "app-level"

    def test_an_override_of_any_key_is_stored(self, store):
        """Not model-specific: ``**extra`` takes anything."""
        store.set_stage_override("EL", endpoint="http://elsewhere:8080/v1")
        cfg = store.load_settings()
        assert cfg["stages"]["EL"]["endpoint"] == "http://elsewhere:8080/v1"

    def test_a_blank_override_clears_rather_than_storing_nothing(self, store):
        """F-93's shape, already closed. Whitespace never wins."""
        store.set_stage_override("EL", model="m")
        store.set_stage_override("EL", model="   ")
        assert "EL" not in store.load_settings()["stages"]


class TestTheEndpointIsAppLevelOnlyToday:
    """**Characterisation. Inverted by the per-stage endpoint commit.**

    The store accepts a per-stage endpoint and nothing honours it, so a
    control bound to it would be a widget that does nothing — F-91's own
    family of defect, which is why this is recorded before the control
    exists rather than after.
    """

    def test_a_per_stage_endpoint_is_not_read_by_the_resolver(self, store):
        import plugins._common.llm_client as lc
        store.update_settings(provider="openai",
                              endpoint="https://api.openai.com/v1")
        store.set_stage_override("EL", endpoint="http://localhost:11434/v1")
        assert lc.resolve_openai_base_url() == "https://api.openai.com/v1", (
            "characterisation: today the resolver is app-level only"
        )

    def test_the_resolver_takes_no_stage_today(self):
        import inspect
        import plugins._common.llm_client as lc
        params = inspect.signature(lc.resolve_openai_base_url).parameters
        assert "stage" not in params, (
            "characterisation: the endpoint is decided without reference "
            "to which stage is asking"
        )


# ---------------------------------------------------------------------------
# 2. The keyless gate ignores the endpoint
# ---------------------------------------------------------------------------

class TestTheKeylessGateIgnoresTheEndpointToday:
    """**Characterisation. Inverted by the invariant commit (INV-1b).**

    Session B closed *a keyless provider never FALLS BACK to the paid
    vendor*. That is a rule about the fallback. A per-stage endpoint
    override reaches the vendor **explicitly**, so the rule does not fire
    — which is this session's version of the defect this wave has now
    produced twice.
    """

    def test_the_key_requirement_is_decided_on_the_provider_string_alone(self):
        assert ss.key_required("local") is False
        assert ss.key_ok(provider="local", api_key="") is True

    def test_nothing_today_relates_the_gate_to_the_endpoint(self):
        """No predicate in the vocabulary takes an endpoint."""
        import inspect
        for fn in (ss.key_required, ss.key_ok):
            assert "endpoint" not in inspect.signature(fn).parameters

    def test_readiness_does_not_ask_where_the_stage_points(self):
        import inspect
        assert "endpoint" not in inspect.signature(
            ss.llm_readiness).parameters, (
            "characterisation: readiness cannot see a vendor endpoint "
            "under a keyless provider"
        )


# ---------------------------------------------------------------------------
# 3. Discovery flattens the states session A separated
# ---------------------------------------------------------------------------

class TestDiscoveryFlattensTodayException:
    """**Characterisation. Inverted by the discovery commit.**

    ``list_models`` collapses *did not answer* and *answered with nothing*
    into one empty tuple. D4/D5 exist because those two call for opposite
    actions from the user.
    """

    def test_an_unreachable_endpoint_and_an_empty_server_are_indistinguishable(
            self, dead_endpoint):
        from helpers_fake_server import serve_models

        url, stop = serve_models([])
        try:
            answered_empty = D.list_models(url)
        finally:
            stop()
        never_answered = D.list_models(dead_endpoint, timeout=0.25)
        assert answered_empty == never_answered == (), (
            "characterisation: discovery cannot tell 'pull a model' from "
            "'start a server'"
        )

    def test_the_detector_itself_can_already_tell_them_apart(
            self, dead_endpoint):
        """The information exists; only ``list_models`` throws it away.
        That is what makes this a flattening rather than a gap."""
        from helpers_fake_server import serve_models

        url, stop = serve_models([])
        try:
            assert D.detect(url, which=lambda _n: "/bin/ollama").state \
                == D.NO_MODELS
        finally:
            stop()
        assert D.detect(dead_endpoint, which=lambda _n: "/bin/ollama",
                        timeout=0.25).state == D.NOT_RUNNING


# ---------------------------------------------------------------------------
# 4. The harmoniser decides for itself
# ---------------------------------------------------------------------------

HARMONISER_UI = PROJECT_ROOT / "plugins" / "03_harmoniser" / "ui.py"


def _harmoniser_tree():
    return ast.parse(HARMONISER_UI.read_text(encoding="utf-8"))


class TestTheHarmoniserCheckboxIsReadByNothingToday:
    """**Characterisation. Inverted by the D9 commit, which DELETES it.**

    F-118's remaining half, and the row calls it the worst of the three:
    it reads as the cost-and-provider safety switch — the one control a
    cautious user would untick before doing anything expensive — and
    unticking it changes nothing.
    """

    def test_var_llm_is_assigned(self):
        src = HARMONISER_UI.read_text(encoding="utf-8")
        assert "self.var_llm" in src

    def test_nothing_ever_reads_var_llm(self):
        """Read as structure, not as text: an attribute *load* of
        ``var_llm`` is what a read is. The assignment and the
        ``variable=`` keyword are both stores or references, not reads of
        its value."""
        tree = _harmoniser_tree()
        loads = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr == "var_llm"
            and isinstance(n.ctx, ast.Load)
        ]
        # The only Load is the one handed to `variable=`, which passes the
        # object rather than reading the flag.
        gets = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get"
            and isinstance(n.func.value, ast.Attribute)
            and n.func.value.attr == "var_llm"
        ]
        assert loads, "characterisation: the variable exists"
        assert gets == [], (
            "characterisation: F-118 — nothing calls self.var_llm.get(), so "
            "the checkbox cannot affect anything"
        )

    def test_the_llm_choice_is_already_expressed_by_two_buttons(self):
        src = HARMONISER_UI.read_text(encoding="utf-8")
        assert "Harmonise (no-LLM)" in src
        assert "Harmonise + LLM" in src


class TestTheHarmoniserHasAThirdKeyPredicateToday:
    """**Characterisation. Inverted by the harmoniser commit.**

    F-117 unified two predicates over one environment variable. This is
    the third, and it is in a *label*, so it reports a different answer
    from the button beside it.
    """

    def test_the_view_reads_the_environment_variable_directly(self):
        src = HARMONISER_UI.read_text(encoding="utf-8")
        assert 'os.getenv("OPENAI_API_KEY")' in src, (
            "characterisation: the key indicator is a bare getenv, so it "
            "says 'missing' for a local provider that needs no key"
        )

    def test_the_button_gate_never_consults_the_probe(self):
        """``_llm_available`` is key-only: it cannot report unreachable,
        and it does not check that a provider was chosen at all.

        Read from the file rather than through an import, because
        ``llm_refine`` uses relative imports and the plugin directories
        start with digits, so ``spec_from_file_location`` cannot give it
        a parent package.
        """
        path = PROJECT_ROOT / "plugins" / "03_harmoniser" / "llm_refine.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_llm_available")
        src = ast.unparse(fn)
        assert "probe" not in src
        assert "llm_readiness" not in src
        assert "NOT_CONFIGURED" not in src and "not_configured" not in src


# ---------------------------------------------------------------------------
# 5. A lifecycle hook with no receiver
# ---------------------------------------------------------------------------

class TestNothingReceivesTheProviderChangedHookToday:
    """**Characterisation. Inverted by the discovery commit.**

    ``main.py`` calls ``notify_plugin(plugin, "on_provider_changed")``
    after every probe lands. ``notify_plugin`` never raises and returns
    ``False`` when nothing implements the name, so the call is a silent
    no-op: the stage tabs never learn that the provider changed, and
    their Run button and readiness label keep reporting the previous
    answer until something else happens to refresh them.
    """

    def test_the_app_notifies_the_hook(self):
        src = (PROJECT_ROOT / "metascreener" / "main.py").read_text(
            encoding="utf-8")
        assert '"on_provider_changed"' in src

    @pytest.mark.parametrize("plugin_dir", ["03_harmoniser", "06_el", "07_il"])
    def test_no_plugin_implements_it(self, plugin_dir):
        found = []
        for name in ("plugin.py", "ui.py"):
            path = PROJECT_ROOT / "plugins" / plugin_dir / name
            if not path.exists():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found += [n.name for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef)
                      and n.name == "on_provider_changed"]
        assert found == [], (
            f"characterisation: {plugin_dir} does not receive the hook"
        )


# ---------------------------------------------------------------------------
# 6. F-140 — validated one string, stored another
# ---------------------------------------------------------------------------

def _akd():
    pytest.importorskip("tkinter",
                        reason="api_key_dialog imports tkinter at import time")
    return _load("_akd_for_stage_cfg", "metascreener/api_key_dialog.py")


class TestTheKeyDialogValidatesOneStringAndStoresAnotherToday:
    """**Characterisation. Inverted by the F-140 commit.**

    ``_on_save`` sanitizes the entry once and hands the result to
    ``validate_api_key``, which sanitizes it *again*. ``sanitize_api_key``
    strips whitespace **before** quotes and never re-strips, so it is not
    idempotent and the two strings differ.
    """

    def test_sanitize_is_not_idempotent(self):
        m = _akd()
        once = m.sanitize_api_key('" x "')
        twice = m.sanitize_api_key(once)
        assert once == " x ", repr(once)
        assert twice == "x", repr(twice)
        assert once != twice, (
            "characterisation: F-140 — the decision is taken on the second "
            "form and the first is what gets stored"
        )

    def test_the_validated_string_and_the_stored_string_differ(self):
        """The row, executed rather than argued. ``_on_save`` computes
        ``key = sanitize(entry)``, validates ``sanitize(key)`` inside
        ``validate_api_key``, and assigns ``self.value = key``."""
        m = _akd()
        entry = '" x "'
        stored = m.sanitize_api_key(entry)              # what _on_save keeps
        validated = m.sanitize_api_key(stored)          # what it decided on
        accepted, _msg = m.validate_api_key(stored)
        assert accepted is True
        assert stored != validated
        assert stored == " x " and validated == "x"


class TestTheReachableDialogDoesNotSanitiseAtAllToday:
    """**Characterisation.** F-140's row names ``ApiKeyDialog``, which
    session B made unreachable — the launch modal is ``ProviderDialog``
    now. The reachable dialog does not sanitize quotes at all, so a key
    pasted with the surrounding quotes a copy commonly carries is stored
    verbatim and refused by the endpoint with a 401.
    """

    def test_the_provider_dialog_only_strips_whitespace(self):
        src = (PROJECT_ROOT / "metascreener" / "provider_dialog.py").read_text(
            encoding="utf-8")
        assert 'self.var_key.get().strip()' in src
        assert "sanitize_api_key" not in src, (
            "characterisation: the quote-stripping the other dialog does is "
            "absent from the one the application actually opens"
        )

    def test_the_old_dialog_is_no_longer_reached(self):
        """Stated so the F-140 fix is not mistaken for a live-path repair
        on its own."""
        callers = []
        for path in (PROJECT_ROOT / "metascreener").glob("*.py"):
            if path.name == "api_key_dialog.py":
                continue
            if "ApiKeyDialog" in path.read_text(encoding="utf-8"):
                callers.append(path.name)
        assert callers == [], f"unexpectedly still reached from {callers}"
