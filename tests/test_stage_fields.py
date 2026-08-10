# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_stage_fields.py — session C: the tab's fields and the engine cannot
disagree about where a run goes.

The property this file exists for
---------------------------------
The engine resolves its endpoint, its model and its batch size **from the
store**. The tab holds them in Tk variables. If a value can live in a
widget without reaching the store, a run goes somewhere other than what
the tab shows — which is this wave's entire subject, arriving through the
controls added to fix it.

So ``settings::apply_stage_fields`` writes before the run starts, and the
property asserted throughout is:

    resolve_stage(load_settings(), stage) == what the fields said

The rule that makes it more than a dict copy
--------------------------------------------
**A field equal to what the stage would resolve to without an override
stores nothing.** Without it, opening a tab and pressing Run would pin a
copy of whatever the field happened to be showing — and the application
setting would then stop reaching that stage, silently. The next provider
change would leave the stage the user was *not* looking at on the old
endpoint. That is a stale-cache defect wearing a persistence feature's
clothes.

The comparison is against a resolution with the stage's entry removed,
not against the raw application key, because the two differ whenever a
default is doing the work: an unconfigured install shows the vendor
endpoint in the box while the application setting is empty.
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


S = _load("_settings_for_fields", "plugins/_common/settings.py")

VENDOR = "https://api.openai.com/v1"
LOCAL = "http://localhost:11434/v1"
ELSEWHERE = "http://elsewhere.invalid:8080/v1"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return S


def _seen_by(stage):
    """What the tab would show: the stage's resolved configuration."""
    return S.resolve_stage(S.load_settings(), stage)


# ---------------------------------------------------------------------------
# Untouched fields store nothing
# ---------------------------------------------------------------------------

class TestAnUntouchedFieldPinsNothing:

    def test_saving_what_the_field_already_showed_writes_no_override(
            self, store):
        store.update_settings(provider="local", endpoint=LOCAL, model="qwen")
        shown = _seen_by("EL")

        store.apply_stage_fields("EL", model=shown.model,
                                 endpoint=shown.endpoint,
                                 batch_size=str(shown.batch_size or ""))
        assert store.load_settings()["stages"] == {}

    def test_the_application_setting_keeps_reaching_the_stage(self, store):
        """The consequence, stated as the defect it prevents: a stage that
        pinned a copy would keep the old endpoint through a provider
        change, in the tab the user was not looking at."""
        store.update_settings(provider="local", endpoint=LOCAL)
        shown = _seen_by("EL")
        store.apply_stage_fields("EL", endpoint=shown.endpoint)

        store.update_settings(endpoint=ELSEWHERE)
        assert _seen_by("EL").endpoint == ELSEWHERE

    def test_an_unconfigured_install_does_not_pin_the_vendor_default(
            self, store):
        """The case the raw-key comparison would get wrong: the box shows
        the vendor endpoint while the application setting is empty."""
        shown = _seen_by("EL")
        assert shown.endpoint == S.DEFAULT_OPENAI_ENDPOINT
        assert shown.endpoint_source == S.ENDPOINT_FROM_VENDOR_DEFAULT

        store.apply_stage_fields("EL", endpoint=shown.endpoint)
        assert store.load_settings()["stages"] == {}


# ---------------------------------------------------------------------------
# A changed field reaches the engine
# ---------------------------------------------------------------------------

class TestAChangedFieldReachesTheEngine:

    def test_an_edited_endpoint_is_what_the_engine_resolves(self, store):
        import plugins._common.llm_client as lc
        store.update_settings(provider="custom", endpoint=LOCAL)
        store.apply_stage_fields("EL", endpoint=ELSEWHERE)
        assert lc.resolve_openai_base_url("EL") == ELSEWHERE
        assert lc.resolve_openai_base_url("IL") == LOCAL

    def test_an_edited_model_is_what_the_engine_resolves(self, store):
        store.update_settings(provider="local", endpoint=LOCAL, model="app")
        store.apply_stage_fields("IL", model="  stage-model  ")
        assert _seen_by("IL").model == "stage-model"
        assert _seen_by("EL").model == "app"

    def test_an_edited_batch_size_is_what_the_engine_resolves(self, store):
        store.update_settings(provider="local", endpoint=LOCAL, batch_size=50)
        store.apply_stage_fields("EL", batch_size="7")
        assert _seen_by("EL").batch_size == 7
        assert _seen_by("IL").batch_size == 50

    @pytest.mark.parametrize("stage", ["EL", "IL"])
    def test_what_the_fields_said_is_what_the_stage_resolves_to(
            self, store, stage):
        """The property, as one assertion, for each stage."""
        store.update_settings(provider="custom", endpoint=LOCAL,
                              model="app", batch_size=50)
        store.apply_stage_fields(stage, model="m2", endpoint=ELSEWHERE,
                                 batch_size="9")
        got = _seen_by(stage)
        assert (got.model, got.endpoint, got.batch_size) == \
            ("m2", ELSEWHERE, 9)


# ---------------------------------------------------------------------------
# Retraction
# ---------------------------------------------------------------------------

class TestAnOverrideCanBeRetracted:

    def test_clearing_a_text_field_drops_the_override(self, store):
        store.update_settings(provider="local", endpoint=LOCAL, model="app")
        store.apply_stage_fields("EL", model="stage")
        assert _seen_by("EL").model == "stage"
        store.apply_stage_fields("EL", model="   ")
        assert _seen_by("EL").model == "app"

    def test_clearing_the_endpoint_falls_back_rather_than_storing_blank(
            self, store):
        """F-93's shape. A whitespace-only field that survived an ``or``
        and reached the engine as ``""`` is how this project's most
        expensive silent failures start — and here it would additionally
        be the blank-endpoint route to the vendor."""
        store.update_settings(provider="local", endpoint=LOCAL)
        store.apply_stage_fields("EL", endpoint=ELSEWHERE)
        store.apply_stage_fields("EL", endpoint="  ")
        got = _seen_by("EL")
        assert got.endpoint == LOCAL
        assert ss.is_paid_vendor(got.endpoint) is False

    def test_a_non_numeric_batch_size_retracts_rather_than_storing_junk(
            self, store):
        """The field is free text. ``parse_numeric_settings`` already
        corrects-and-reports at run time (F-118); the store must not be
        the place a typo becomes durable."""
        store.update_settings(provider="local", endpoint=LOCAL, batch_size=50)
        store.apply_stage_fields("EL", batch_size="abc")
        assert "EL" not in store.load_settings()["stages"]
        assert _seen_by("EL").batch_size == 50


# ---------------------------------------------------------------------------
# The invariant survives the new write path
# ---------------------------------------------------------------------------

class TestTheInvariantSurvivesTheWritePath:

    def test_a_tab_pointed_at_the_vendor_stores_it_and_then_blocks(
            self, store):
        """The route is not forbidden — a user may legitimately point one
        stage at OpenAI and leave the other local. What must not happen
        is that it runs **keyless**."""
        import plugins._common.llm_client as lc
        store.update_settings(provider="local", endpoint=LOCAL, api_key="")
        store.apply_stage_fields("EL", endpoint=VENDOR)

        assert _seen_by("EL").endpoint == VENDOR
        assert lc._has_openai_key("EL") is False
        assert lc._has_openai_key("IL") is True

        got = _seen_by("EL")
        r = ss.llm_readiness(stage="EL", has_bundle=True,
                             provider=got.provider, api_key=got.api_key,
                             model=got.model or "m", endpoint=got.endpoint,
                             probe=None)
        assert r.can_run is False

    def test_the_same_tab_with_a_key_is_allowed(self, store):
        """The direction that must stay open, or the guard is a refusal."""
        import plugins._common.llm_client as lc
        store.update_settings(provider="local", endpoint=LOCAL,
                              api_key="sk-real")
        store.apply_stage_fields("EL", endpoint=VENDOR)
        assert lc._has_openai_key("EL") is True

    def test_a_field_cannot_smuggle_a_provider(self, store):
        with pytest.raises(S.StageOverrideRefused):
            store.apply_stage_fields("EL", provider="local")


# ---------------------------------------------------------------------------
# The Views call it, and call it before the run
# ---------------------------------------------------------------------------

class TestTheViewsUseIt:
    """``ELView``/``ILView`` cannot be instantiated under this conftest —
    ``tkinter`` is a ``MagicMock``, so ``ttk.Frame`` is a mock. This is
    the F-14 gap session B recorded. What can still be asserted is the
    *order*, from the source, which is the property that matters: the
    write must precede the readiness check, or the check answers about a
    different configuration from the one that ran."""

    @pytest.mark.parametrize("rel,stage", [
        ("plugins/06_el/ui.py", "EL"),
        ("plugins/07_il/ui.py", "IL"),
    ])
    def test_the_fields_are_persisted_before_readiness_is_consulted(
            self, rel, stage):
        import ast
        tree = ast.parse(PROJECT_ROOT.joinpath(*rel.split("/")).read_text(
            encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_run_clicked")
        body = ast.unparse(fn)
        persist = body.index("_stage_fields_edited()")
        check = body.index("ready = self._readiness()")
        assert persist < check, (
            f"{rel}: the run's readiness check would answer about a "
            f"configuration the engine will not use"
        )

    @pytest.mark.parametrize("rel", ["plugins/06_el/ui.py",
                                     "plugins/07_il/ui.py"])
    def test_the_stage_name_is_declared_once_per_view(self, rel):
        """Two spellings of the stage would be two stages as far as the
        store is concerned, and one of them would silently have no
        overrides at all."""
        import ast
        tree = ast.parse(PROJECT_ROOT.joinpath(*rel.split("/")).read_text(
            encoding="utf-8"))
        stages = [n.value.value for n in ast.walk(tree)
                  if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "STAGE"
                          for t in n.targets)
                  and isinstance(n.value, ast.Constant)]
        assert len(stages) == 1, stages
        assert stages[0] in ("EL", "IL")
