# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_harmoniser_provider.py — F-118/D9: the harmoniser's LLM path stops
deciding for itself.

The user-visible complaint
--------------------------
A user running locally must not find that **one** button still demands a
paid key. Before this session the harmoniser answered three questions
with one predicate of its own, and got all three different from EL and
IL:

* it never checked ``NOT_CONFIGURED``, so a store holding a leftover key
  and **no provider chosen** lit the button — ahead of the check that
  exists precisely because the key and model tests can each be satisfied
  while the path as a whole is unconfigured;
* it never consulted the probe, so an unreachable endpoint lit the button
  too, and the run failed one call in;
* ``cfg.get("provider", "local")`` defaulted to a **keyless** provider
  when the key was missing, which waives the key gate — session A's
  ``defaults()`` defect, one module along;
* and the key *indicator* beside the button read the environment
  variable directly, so it said "missing" to exactly the user who needs
  no key, disagreeing with the button next to it.

All four are one defect: a third answer to a question ``llm_readiness``
already answers. What remains in ``llm_refine`` is
``_sdk_importable`` — whether the SDK can be imported, which is the one
part that module can answer and which readiness cannot.

D9, and the reversal it records
-------------------------------
The "LLM refine" checkbox is **deleted, not wired.** That reverses the
coordinator's wave-8 decision, recorded in F-118's row. The LLM/no-LLM
choice is already expressed by two buttons — "Harmonise (no-LLM)" and
"Harmonise + LLM" — and ``_harmonise_llm`` never consulted the flag.
Wiring it would mean deciding what it means when it disagrees with the
button pressed, and every answer to that is worse than not having it: a
third control that can contradict two explicit ones makes the user wrong
about what they asked for.
"""
import ast
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


S = _load("_settings_for_harmoniser", "plugins/_common/settings.py")

UI = PROJECT_ROOT / "plugins" / "03_harmoniser" / "ui.py"
REFINE = PROJECT_ROOT / "plugins" / "03_harmoniser" / "llm_refine.py"

VENDOR = "https://api.openai.com/v1"
LOCAL = "http://localhost:11434/v1"

#: The stage name the View and the refine module must agree on. Two
#: spellings would be two stages as far as the store is concerned, and
#: one of them would silently have no configuration at all.
STAGE = "harmoniser"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return S


def _readiness(cfg, model="gpt-4o-mini", probe=None):
    """What the View's ``_readiness`` computes, from the same inputs.

    The View cannot be instantiated under this conftest — ``tkinter`` is
    a ``MagicMock``, so ``ttk.Frame`` is a mock — which is the F-14 gap
    session B recorded. This calls the same function with the same
    arguments; the *wiring* is asserted separately, by AST.
    """
    return ss.llm_readiness(stage="Harmonise", has_bundle=True,
                            provider=cfg.provider, api_key=cfg.api_key,
                            model=model, endpoint=cfg.endpoint, probe=probe)


class _Probe:
    """A detection stand-in. Only ``state`` and ``detail`` are read, and
    both values used here are ones the real detector produces — see
    ``tests/test_model_discovery.py``, which builds them by execution."""

    def __init__(self, state, detail=""):
        self.state = state
        self.detail = detail


# ---------------------------------------------------------------------------
# The complaint
# ---------------------------------------------------------------------------

class TestALocalUserIsNotAskedForAPaidKey:

    def test_a_local_provider_with_no_key_can_run_the_llm_path(self, store):
        store.update_settings(provider="local", endpoint=LOCAL, api_key="")
        r = _readiness(store.resolve_stage(store.load_settings(), STAGE),
                       probe=_Probe("ready"))
        assert r.can_run is True, r.detail

    def test_the_indicator_says_the_same_thing_the_button_does(self, store):
        """The old label read the environment and the old button read a
        different predicate, so they could disagree. One function now
        supplies both, so they cannot."""
        store.update_settings(provider="local", endpoint=LOCAL, api_key="")
        r = _readiness(store.resolve_stage(store.load_settings(), STAGE),
                       probe=_Probe("ready"))
        assert r.label == "Ready to run"
        assert r.can_run is True

    def test_the_message_never_tells_a_local_user_to_find_a_key(self, store):
        store.update_settings(provider="local", endpoint=LOCAL, api_key="")
        r = _readiness(store.resolve_stage(store.load_settings(), STAGE),
                       probe=_Probe("not_running", "start it"))
        assert r.can_run is False
        assert "API key" not in r.detail
        assert "start it" in r.detail


class TestTheThreeChecksItUsedToSkip:

    def test_an_unconfigured_store_with_a_leftover_key_does_not_run(
            self, store):
        """The worst of the four. ``key_ok`` was satisfied by a key left
        over from a previous configuration, and nothing asked whether a
        provider had been chosen."""
        store.update_settings(provider="", api_key="sk-left-over")
        r = _readiness(store.resolve_stage(store.load_settings(), STAGE),
                       probe=_Probe("ready"))
        assert r.code == ss.NOT_CONFIGURED
        assert r.can_run is False

    def test_an_unreachable_endpoint_does_not_run(self, store):
        store.update_settings(provider="local", endpoint=LOCAL)
        r = _readiness(store.resolve_stage(store.load_settings(), STAGE),
                       probe=_Probe("not_running", "start it"))
        assert r.code == ss.ENDPOINT_UNREACHABLE
        assert r.can_run is False

    def test_an_unprobed_provider_does_not_run(self, store):
        store.update_settings(provider="local", endpoint=LOCAL)
        r = _readiness(store.resolve_stage(store.load_settings(), STAGE),
                       probe=None)
        assert r.code == ss.NOT_CHECKED
        assert r.can_run is False

    def test_a_missing_provider_is_not_defaulted_to_a_keyless_one(
            self, store):
        """``cfg.get("provider", "local")`` waived the key gate whenever
        the key was absent — session A's ``defaults()`` defect one module
        along."""
        cfg = store.resolve_stage(store.load_settings(), STAGE)
        assert cfg.provider == ""
        assert ss.key_required(cfg.provider) is True


class TestTheInvariantReachesThisStageToo:
    """The harmoniser is the stage whose client used to ignore everything
    the wave built (session A's review, §10.4). It must now land on the
    same side of the line as EL and IL, by every route."""

    def test_a_keyless_provider_pointed_at_the_vendor_is_blocked(self, store):
        store.update_settings(provider="local", endpoint=LOCAL, api_key="")
        store.set_stage_override(STAGE, endpoint=VENDOR)
        cfg = store.resolve_stage(store.load_settings(), STAGE)
        assert cfg.endpoint == VENDOR
        r = _readiness(cfg, probe=_Probe("ready"))
        assert r.code == ss.NO_KEY
        assert r.can_run is False

    def test_the_client_would_not_be_handed_a_placeholder_credential(
            self, store):
        store.update_settings(provider="local", endpoint=LOCAL, api_key="")
        store.set_stage_override(STAGE, endpoint=VENDOR)
        cfg = store.resolve_stage(store.load_settings(), STAGE)
        assert S.placeholder_key_for(cfg.provider, cfg.api_key,
                                     endpoint=cfg.endpoint) == ""

    def test_the_client_is_built_for_this_stage(self, store, monkeypatch):
        """Executed rather than read: the refine module's call must reach
        the stage's own endpoint, not the application's."""
        import openai
        import plugins._common.llm_client as lc

        seen = {}

        class _Recorder:
            def __init__(self, **kwargs):
                seen.update(kwargs)

        monkeypatch.setattr(openai, "OpenAI", _Recorder)
        store.update_settings(provider="custom", endpoint=LOCAL)
        store.set_stage_override(STAGE, endpoint="http://elsewhere:9/v1")

        lc._openai_client_for(STAGE)
        assert seen["base_url"] == "http://elsewhere:9/v1"


# ---------------------------------------------------------------------------
# The wiring, by AST — the View cannot be instantiated here
# ---------------------------------------------------------------------------

def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


class TestTheViewIsWiredToTheSharedGate:

    def test_the_llm_button_handler_consults_readiness(self):
        fn = next(n for n in ast.walk(_tree(UI))
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_harmonise_llm")
        body = ast.unparse(fn)
        assert "self._readiness()" in body
        assert "can_run" in body

    def test_the_old_message_is_gone(self):
        """"OPENAI_API_KEY missing or OpenAI package not available" is
        wrong twice for a local user: they need no key, and what is
        actually missing might be a running server or a chosen
        provider."""
        fn = next(n for n in ast.walk(_tree(UI))
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_harmonise_llm")
        strings = [n.value for n in ast.walk(fn)
                   if isinstance(n, ast.Constant)
                   and isinstance(n.value, str)]
        assert not any("OPENAI_API_KEY missing" in s for s in strings)

    def test_the_refused_message_is_the_shared_one(self):
        fn = next(n for n in ast.walk(_tree(UI))
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_harmonise_llm")
        assert "ready.detail" in ast.unparse(fn)

    def test_the_button_state_uses_readiness_and_the_sdk_check(self):
        fn = next(n for n in ast.walk(_tree(UI))
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_refresh_buttons")
        body = ast.unparse(fn)
        assert "self._readiness()" in body
        assert "_sdk_importable()" in body

    def test_the_indicator_shows_the_readiness_label(self):
        fn = next(n for n in ast.walk(_tree(UI))
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_refresh_buttons")
        assert "ready.label" in ast.unparse(fn)

    def test_the_stage_name_agrees_between_the_view_and_the_engine(self):
        """Two spellings would be two stages, and one of them would have
        no configuration at all — silently."""
        refine = _tree(REFINE)
        declared = [n.value.value for n in ast.walk(refine)
                    if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "STAGE"
                            for t in n.targets)
                    and isinstance(n.value, ast.Constant)]
        assert declared == [STAGE], declared

        ui_src = UI.read_text(encoding="utf-8")
        assert "STAGE as LLM_STAGE" in ui_src
        assert "STAGE = LLM_STAGE" in ui_src, (
            "the View must take the name from the engine module rather "
            "than restate it"
        )

    def test_the_refine_call_passes_the_stage(self):
        fn = next(n for n in ast.walk(_tree(REFINE))
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_call_openai_json")
        body = ast.unparse(fn)
        assert "_openai_client_for(stage)" in body


class TestTheViewReceivesProviderNews:

    def test_the_plugin_wrapper_implements_the_hook(self):
        tree = _tree(PROJECT_ROOT / "plugins" / "03_harmoniser" / "plugin.py")
        assert any(isinstance(n, ast.FunctionDef)
                   and n.name == "on_provider_changed"
                   for n in ast.walk(tree))

    def test_the_view_implements_it(self):
        assert any(isinstance(n, ast.FunctionDef)
                   and n.name == "on_provider_changed"
                   for n in ast.walk(_tree(UI)))

    def test_the_model_control_is_an_editable_combobox(self):
        combos = [n for n in ast.walk(_tree(UI))
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "Combobox"]
        # Two of the three pre-existing comboboxes in this file are the
        # cell editors over STAGES and OPERATORS, which are CLOSED
        # vocabularies where readonly is right. The model one must not be.
        model_combos = [n for n in combos
                        if any(kw.arg == "textvariable" for kw in n.keywords)]
        assert model_combos, "the model control is not a combobox"
        for node in model_combos:
            assert not any(kw.arg == "state" for kw in node.keywords), (
                f"line {node.lineno}: the model combobox declares a state"
            )

    def test_the_closed_vocabulary_editors_are_still_readonly(self):
        """The other direction. STAGES and OPERATORS are closed sets, and
        a free-text cell editor over them would let a typo through into
        a criterion — so this session must not have made *those*
        editable in passing."""
        src = UI.read_text(encoding="utf-8")
        assert src.count('state="readonly"') == 2
