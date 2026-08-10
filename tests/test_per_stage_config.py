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
    """**FLIPPED by the per-stage resolver commit.**

    Was: *the store accepts a per-stage endpoint and nothing honours it*
    — a control bound to that value would be a widget that does nothing,
    F-91's own family of defect, which is why it was recorded before the
    control existed rather than after.

    Now: the resolver takes a stage, and ``stage=""`` still means the
    application level, which is the property the golden replays rest on.
    """

    def test_the_app_level_call_is_unchanged_by_a_stage_override(self, store):
        """The half that did **not** flip, and it matters: an app-level
        question must keep the app-level answer, or every existing caller
        would start following whichever stage was edited last."""
        import plugins._common.llm_client as lc
        store.update_settings(provider="openai",
                              endpoint="https://api.openai.com/v1")
        store.set_stage_override("EL", endpoint="http://localhost:11434/v1")
        assert lc.resolve_openai_base_url() == "https://api.openai.com/v1"

    def test_a_per_stage_endpoint_is_now_read_by_the_resolver(self, store):
        import plugins._common.llm_client as lc
        store.update_settings(provider="openai",
                              endpoint="https://api.openai.com/v1")
        store.set_stage_override("EL", endpoint="http://localhost:11434/v1")
        assert lc.resolve_openai_base_url("EL") == "http://localhost:11434/v1"
        assert lc.resolve_openai_base_url("IL") == "https://api.openai.com/v1"

    def test_the_resolver_takes_a_stage(self):
        import inspect
        import plugins._common.llm_client as lc
        params = inspect.signature(lc.resolve_openai_base_url).parameters
        assert "stage" in params
        assert params["stage"].default == "", (
            "the application level must remain the default, or an existing "
            "caller silently changes which endpoint it resolves"
        )


# ---------------------------------------------------------------------------
# 2. The keyless gate ignores the endpoint
# ---------------------------------------------------------------------------

class TestTheKeylessGateIgnoresTheEndpointToday:
    """**FLIPPED by the invariant commit (INV-1b).**

    Was: *the key requirement is decided on the provider string alone, so
    nothing relates the gate to the endpoint.* Session B closed **a
    keyless provider never FALLS BACK to the paid vendor** — a rule about
    the fallback. A per-stage endpoint override reaches the vendor
    **explicitly**, so that rule does not fire.

    Now: the question is asked about the resolved pair, and where the two
    halves disagree the safe side wins.
    """

    def test_the_provider_only_predicate_is_unchanged(self):
        """``key_required`` keeps its exact meaning. One predicate asking
        a larger question, not two predicates — which is F-117."""
        assert ss.key_required("local") is False
        assert ss.key_required("openai") is True

    def test_a_keyless_provider_pointed_at_the_vendor_needs_a_key(self):
        assert ss.key_required_for("local", "https://api.openai.com/v1") is True
        assert ss.key_ok(provider="local", api_key="",
                         endpoint="https://api.openai.com/v1") is False

    def test_readiness_asks_where_the_stage_points(self):
        import inspect
        assert "endpoint" in inspect.signature(ss.llm_readiness).parameters
        r = ss.llm_readiness(stage="EL", has_bundle=True, provider="local",
                             api_key="", model="m",
                             endpoint="https://api.openai.com/v1",
                             probe=D.Detection(D.READY, ("m",), "", ""))
        assert r.code == ss.NO_KEY and r.can_run is False


# ---------------------------------------------------------------------------
# 3. Discovery flattens the states session A separated
# ---------------------------------------------------------------------------

class TestDiscoveryFlattensTodayException:
    """**FLIPPED by the discovery commit — and the characterisation's own
    framing was corrected in the process, which is worth recording.**

    The characterisation said this class would be *inverted*: that
    ``list_models``' flattening was the defect and would be removed. On
    working it, that reading was wrong. ``list_models`` answers *what
    names are there* for a caller whose remedy is identical in every
    failure, and its contract is correct **for that caller**. The defect
    was that the tabs had no other path, so the flattening happened where
    it mattered.

    So the fix gives the tabs a path that does not flatten —
    ``detect`` plus ``model_choices`` — and leaves the helper alone. The
    assertion that inverts is therefore *"the tab path carries the states
    through"*, not *"list_models stopped flattening"*. Changing the
    helper would have been a change made to satisfy a characterisation
    rather than a user.
    """

    def test_list_models_still_flattens_by_design(self, dead_endpoint):
        from helpers_fake_server import serve_models

        url, stop = serve_models([])
        try:
            answered_empty = D.list_models(url)
        finally:
            stop()
        never_answered = D.list_models(dead_endpoint, timeout=0.25)
        assert answered_empty == never_answered == ()

    def test_the_tab_path_carries_the_three_states_through(
            self, dead_endpoint):
        """What actually inverted: three problems, three notes."""
        from helpers_fake_server import serve_models

        url, stop = serve_models([])
        try:
            no_models = D.model_choices(
                D.detect(url, which=lambda _n: "/bin/ollama"))
        finally:
            stop()
        not_running = D.model_choices(D.detect(
            dead_endpoint, which=lambda _n: "/bin/ollama", timeout=0.25))
        not_installed = D.model_choices(D.detect(
            dead_endpoint, which=lambda _n: None, timeout=0.25))

        assert {no_models.state, not_running.state, not_installed.state} == \
            {D.NO_MODELS, D.NOT_RUNNING, D.NOT_INSTALLED}
        assert len({no_models.note, not_running.note,
                    not_installed.note}) == 3


# ---------------------------------------------------------------------------
# 4. The harmoniser decides for itself
# ---------------------------------------------------------------------------

HARMONISER_UI = PROJECT_ROOT / "plugins" / "03_harmoniser" / "ui.py"


def _harmoniser_tree():
    return ast.parse(HARMONISER_UI.read_text(encoding="utf-8"))


class TestTheHarmoniserCheckboxIsReadByNothingToday:
    """**FLIPPED by the D9 commit, which DELETES the checkbox.**

    Was: ``self.var_llm`` is bound to a ``Checkbutton`` and nothing calls
    ``.get()`` on it, so unticking the one control a cautious user would
    untick before doing anything expensive changes nothing.

    Now: it is gone. **This reverses the coordinator's wave-8 decision to
    wire it**, and the reversal is recorded in F-118's register row so it
    is not re-litigated. Wiring would have meant deciding what the flag
    means when it disagrees with the button pressed, and a third control
    that can contradict two explicit ones makes the user wrong about what
    they asked for.
    """

    def test_the_variable_is_gone_entirely(self):
        """Read as structure, not as text — the third time this session
        has needed that rule, and the reason is always the same: the
        comment that *explains* the deletion names the thing deleted, so
        a substring search matches the explanation. The repository
        already learned this for the ``subprocess`` check in
        ``test_provider_detect.py``."""
        tree = _harmoniser_tree()
        refs = [n for n in ast.walk(tree)
                if isinstance(n, ast.Attribute) and n.attr == "var_llm"]
        assert refs == []

    def test_no_checkbutton_remains_in_the_criteria_row(self):
        """Any ``Checkbutton`` here would be a new control in the place
        the deleted one occupied."""
        tree = _harmoniser_tree()
        checkbuttons = [n for n in ast.walk(tree)
                        if isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "Checkbutton"]
        assert checkbuttons == []

    def test_the_llm_choice_is_still_expressed_by_the_two_buttons(self):
        """What the checkbox was redundant *with*. If these ever went
        away, deleting the checkbox would have removed the only control."""
        src = HARMONISER_UI.read_text(encoding="utf-8")
        assert "Harmonise (no-LLM)" in src
        assert "Harmonise + LLM" in src


class TestTheHarmoniserHasAThirdKeyPredicateToday:
    """**FLIPPED by the harmoniser commit.**

    Was: the key indicator read ``os.getenv("OPENAI_API_KEY")`` directly
    — a third predicate after F-117 unified two — so it said *missing* to
    a user running locally who needs no key, and disagreed with the
    button beside it. And ``_llm_available`` never consulted the probe or
    the unconfigured check.

    Now: both questions go to whoever can answer them.
    ``stage_state.llm_readiness`` decides whether this stage may run, the
    same function EL and IL ask; ``_sdk_importable`` answers only whether
    the SDK is present, which is the one part this module owns.
    """

    def test_the_environment_is_read_in_one_place_and_only_as_an_input(self):
        """The property, stated precisely.

        The environment is not forbidden — it is a legitimate *input* to
        ``settings.resolve_stage``, which is the one function that
        decides. What is forbidden is a second place **deciding** from
        it, which is what the old key indicator did. So: every read lives
        inside ``_stored_config``, and hands its value straight to the
        resolver.

        Checked by AST, because the comment recording the removal names
        the call it removed and a text search matches the record rather
        than the defect.
        """
        tree = _harmoniser_tree()

        def _is_env_read(node):
            if not isinstance(node, ast.Call):
                return False
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == "getenv":
                return True
            return (isinstance(fn, ast.Attribute) and fn.attr == "get"
                    and isinstance(fn.value, ast.Attribute)
                    and fn.value.attr == "environ")

        allowed = next(n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef)
                       and n.name == "_stored_config")
        inside = {id(n) for n in ast.walk(allowed) if _is_env_read(n)}

        stray = [n.lineno for n in ast.walk(tree)
                 if _is_env_read(n) and id(n) not in inside]
        assert stray == [], (
            f"lines {stray}: a second place deciding from the environment "
            f"is the third predicate coming back"
        )

        # And the reads that are allowed must be arguments to the
        # resolver, not decisions of their own.
        for node in ast.walk(allowed):
            if not _is_env_read(node):
                continue
            holders = [c for c in ast.walk(allowed)
                       if isinstance(c, ast.Call)
                       and isinstance(c.func, ast.Name)
                       and c.func.id == "resolve_stage"
                       and any(kw.value is node for kw in c.keywords)]
            assert holders, ast.unparse(node)

    def test_the_view_asks_the_shared_readiness_function(self):
        tree = _harmoniser_tree()
        assert any(isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Name)
                   and n.func.id == "llm_readiness"
                   for n in ast.walk(tree))

    def test_the_old_availability_predicate_is_removed_not_aliased(self):
        """Removed rather than kept as an alias, for the reason session A
        gave when it removed ``has_key=``: a caller left on the old name
        would silently keep the old meaning, and two predicates is the
        defect being closed. A ``NameError`` is the cheaper failure."""
        path = PROJECT_ROOT / "plugins" / "03_harmoniser" / "llm_refine.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)}
        assert "_llm_available" not in names
        assert "_sdk_importable" in names

    def test_what_remains_answers_only_the_question_it_can(self):
        """``_sdk_importable`` must not have quietly kept a key check."""
        path = PROJECT_ROOT / "plugins" / "03_harmoniser" / "llm_refine.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_sdk_importable")
        # Strip the docstring: it *describes* the checks that were taken
        # out, so unparsing it back in would match every one of them.
        statements = [n for n in fn.body
                      if not (isinstance(n, ast.Expr)
                              and isinstance(n.value, ast.Constant)
                              and isinstance(n.value.value, str))]
        body = "\n".join(ast.unparse(n) for n in statements)
        for forbidden in ("key_ok", "load_settings", "api_key", "provider"):
            assert forbidden not in body, forbidden
        assert "openai" in body, "it must still check the thing it is for"


# ---------------------------------------------------------------------------
# 5. A lifecycle hook with no receiver
# ---------------------------------------------------------------------------

class TestNothingReceivesTheProviderChangedHookToday:
    """**FLIPPED by the widget commit.**

    Was: ``main.py`` calls ``notify_plugin(plugin, "on_provider_changed")``
    after every probe lands, ``notify_plugin`` returns quietly when
    nothing implements the name, and no plugin did — so the call was a
    silent no-op and the tabs kept reporting the previous answer until
    something else happened to refresh them.

    Now: the hook is received on the **plugin**, which is what ``main.py``
    notifies, and relayed to the View. The distinction matters — a method
    on the View alone would have left the call reaching nothing, which is
    how the gap arose in the first place.
    """

    def test_the_app_notifies_the_hook(self):
        src = (PROJECT_ROOT / "metascreener" / "main.py").read_text(
            encoding="utf-8")
        assert '"on_provider_changed"' in src

    @pytest.mark.parametrize("plugin_dir", ["06_el", "07_il"])
    def test_the_plugin_wrapper_receives_it(self, plugin_dir):
        """On ``plugin.py``, because ``self._plugins`` holds the wrapper
        and ``notify_plugin`` uses ``getattr`` on that object."""
        tree = ast.parse((PROJECT_ROOT / "plugins" / plugin_dir /
                          "plugin.py").read_text(encoding="utf-8"))
        assert any(isinstance(n, ast.FunctionDef)
                   and n.name == "on_provider_changed"
                   for n in ast.walk(tree)), plugin_dir

    @pytest.mark.parametrize("plugin_dir", ["06_el", "07_il"])
    def test_the_view_implements_what_the_wrapper_relays_to(self, plugin_dir):
        tree = ast.parse((PROJECT_ROOT / "plugins" / plugin_dir /
                          "ui.py").read_text(encoding="utf-8"))
        assert any(isinstance(n, ast.FunctionDef)
                   and n.name == "on_provider_changed"
                   for n in ast.walk(tree)), plugin_dir

    def test_notify_plugin_actually_reaches_it(self):
        """``notify_plugin`` swallows everything and reports only a
        boolean, so *that it ran* is the only observable. Driven against
        the real function rather than a copy of it.

        ``main.py`` uses a relative import and ``conftest`` replaces the
        ``metascreener`` package with a bare stub, so the package needs a
        ``__path__`` for the duration — restored afterwards, because a
        stub mutated for one test is a fixture leaking into the rest of
        the suite.
        """
        import importlib.util as _iu

        pkg = sys.modules["metascreener"]
        had_path = hasattr(pkg, "__path__")
        pkg.__path__ = [str(PROJECT_ROOT / "metascreener")]
        try:
            spec = _iu.spec_from_file_location(
                "metascreener.main",
                str(PROJECT_ROOT / "metascreener" / "main.py"))
            main = _iu.module_from_spec(spec)
            sys.modules["metascreener.main"] = main
            spec.loader.exec_module(main)
        finally:
            if not had_path:
                del pkg.__path__

        seen = []

        class _Wrapper:
            def on_provider_changed(self):
                seen.append(True)

        assert main.notify_plugin(_Wrapper(), "on_provider_changed") is True
        assert seen == [True]

        class _Silent:
            pass

        assert main.notify_plugin(_Silent(), "on_provider_changed") is False, (
            "the False return is what made the gap invisible; it is the "
            "signal, so it must keep meaning 'nothing received this'"
        )


# ---------------------------------------------------------------------------
# 6. F-140 — validated one string, stored another
# ---------------------------------------------------------------------------

def _akd():
    pytest.importorskip("tkinter",
                        reason="api_key_dialog imports tkinter at import time")
    return _load("_akd_for_stage_cfg", "metascreener/api_key_dialog.py")


class TestTheKeyDialogValidatesOneStringAndStoresAnotherToday:
    """**FLIPPED by the F-140 commit.**

    Was: ``sanitize_api_key`` stripped whitespace *before* quotes and
    never re-stripped, so ``'" x "'`` became ``' x '``; ``_on_save``
    sanitized once, ``validate_api_key`` sanitized again internally, and
    the decision was taken on ``'x'`` while ``' x '`` reached the
    endpoint. Measured: ``once == ' x '``, ``twice == 'x'``.

    Now: two independent guards. The function iterates to a fixed point,
    so sanitizing twice cannot differ from sanitizing once; and
    ``_on_save`` hands the **raw** entry to the validator and stores
    ``sanitize(raw)``, so the two are the same expression over the same
    input whether or not the function is idempotent.
    """

    CORPUS = ['" x "', "  'ollama'  ", '"sk-abc"', "\t sk-abc \n",
              "'\" nested \"'", "ollama", "", "   ", None]

    @pytest.mark.parametrize("raw", CORPUS)
    def test_sanitize_is_idempotent(self, raw):
        m = _akd()
        once = m.sanitize_api_key(raw)
        assert m.sanitize_api_key(once) == once, repr(once)

    def test_the_specific_value_the_row_measured(self):
        m = _akd()
        assert m.sanitize_api_key('" x "') == "x"

    @pytest.mark.parametrize("raw", CORPUS)
    def test_the_validated_string_and_the_stored_string_are_the_same(
            self, raw):
        """``_on_save``'s two expressions, evaluated. ``validate_api_key``
        sanitizes internally; the stored value is ``sanitize(raw)``. Same
        function, same input."""
        m = _akd()
        validated = m.sanitize_api_key(raw)
        accepted, _msg = m.validate_api_key(raw)
        stored = m.sanitize_api_key(raw)
        assert stored == validated
        assert accepted is bool(validated)

    def test_the_save_handler_passes_the_raw_entry_to_the_validator(self):
        """The second guard, asserted by AST: pre-sanitizing before the
        validator is what made the two differ, and it must not come back
        if the first guard is ever relaxed."""
        tree = ast.parse((PROJECT_ROOT / "metascreener" /
                          "api_key_dialog.py").read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_on_save")
        calls = [n for n in ast.walk(fn)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)
                 and n.func.id == "validate_api_key"]
        assert len(calls) == 1
        arg = calls[0].args[0]
        assert isinstance(arg, ast.Name) and arg.id == "raw", ast.unparse(arg)


class TestTheReachableDialogSanitisesTheSameWay:
    """**FLIPPED.** ``ProviderDialog._accept`` stored
    ``var_key.get().strip()`` — whitespace only, no quotes — so a key
    pasted with the quotes a copy commonly carries was stored verbatim
    and refused with a 401. It now shares the other dialog's function, so
    the two cannot disagree about what a key is.
    """

    def test_the_provider_dialog_uses_the_shared_sanitiser(self):
        """Narrowed to ``_accept``, which is what *stores*. ``_probe``
        also reads the key and strips it, and that is correct — a probe
        sends it as a bearer token and never persists it, so a blanket
        ban would forbid the legitimate use alongside the defect."""
        tree = ast.parse(
            (PROJECT_ROOT / "metascreener" / "provider_dialog.py")
            .read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_accept")
        body = ast.unparse(fn)
        assert "sanitize_api_key(self.var_key.get())" in body
        assert "self.var_key.get().strip()" not in body

    def test_a_quoted_key_would_now_be_stored_unquoted(self):
        """What the user pastes, and what the endpoint would receive."""
        m = _akd()
        assert m.sanitize_api_key('"sk-a-real-key"') == "sk-a-real-key"
        assert '"sk-a-real-key"'.strip() == '"sk-a-real-key"', (
            "the old expression kept the quotes, which is the defect"
        )


class TestTheReachableDialogDoesNotSanitiseAtAllToday:
    """**Characterisation, and the half that did not flip.**

    F-140's row is written against ``ApiKeyDialog``, which session B made
    unreachable. That fact is recorded here so the fix is not mistaken
    for a live-path repair on its own — the live path is
    ``ProviderDialog``, fixed in ``TestTheReachableDialogSanitisesTheSameWay``
    above.
    """

    def test_the_old_dialog_class_is_no_longer_constructed(self):
        """Stated so the F-140 fix is not mistaken for a live-path repair
        on its own.

        By AST: ``provider_dialog.py`` now *names* ``ApiKeyDialog`` in the
        comment explaining that the row is written against it, so a text
        search matches the explanation. What matters is that nothing
        constructs it."""
        constructed = []
        for path in (PROJECT_ROOT / "metascreener").glob("*.py"):
            if path.name == "api_key_dialog.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(
                        node.func, ast.Name) and \
                        node.func.id == "ApiKeyDialog":
                    constructed.append(f"{path.name}:{node.lineno}")
        assert constructed == [], (
            f"unexpectedly still constructed at {constructed}"
        )

    def test_the_shared_sanitiser_is_what_both_dialogs_import(self):
        """The one thing the two dialogs must agree on. Two definitions
        of what a key is would be F-117's shape applied to the value
        instead of the predicate."""
        tree = ast.parse(
            (PROJECT_ROOT / "metascreener" / "provider_dialog.py")
            .read_text(encoding="utf-8"))
        imports = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom)
            and n.module == "metascreener.api_key_dialog"
            and any(a.name == "sanitize_api_key" for a in n.names)
        ]
        assert imports, "the provider dialog defines its own sanitiser"
