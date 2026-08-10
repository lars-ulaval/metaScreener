
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_startup_flow.py — F-91 and F-144: launch order, and a key that
survives the frozen build.

Why this is an AST test
-----------------------
``metascreener/main.py`` builds a ``tk.Tk`` subclass and cannot be
instantiated under the conftest, which replaces tkinter with
``MagicMock``. The properties that matter here are properties of
**order** — what exists before what, and what can stop the rest from
being built — and order is visible in the syntax tree without running
anything. ``tests/test_frozen_build_spec.py`` establishes the pattern and
the reason: a fixed list is correct exactly until someone edits the file,
so derive from the source instead.

What is pinned, and why each one
--------------------------------
**Nothing may destroy the application.** The old
``_prompt_api_key_always`` returned ``False`` on an empty string or a
cancel, and ``__init__`` answered with ``self.after(0, self.destroy)``
and a bare ``return`` — three lines before the notebook existed. So
dismissing a *key* dialog cost the user stages 03, 04 and 05, which need
no model of any kind and are the majority of the funnel.

**The notebook and the plugins come first.** Not merely "no destroy":
the UI must be built before anything can go wrong, so that whatever the
provider conversation concludes, there is an application behind it.

**The key goes to the settings store, not to ``.env``** (F-144). The
distinction that row exists for is *location*, not *write*: F-139 made
the write atomic, permission-preserving and symlink-safe, and it still
reported success while writing into a directory PyInstaller deletes on
exit. A fix that improved the write again would close nothing.
"""
import ast

import pytest

from conftest import PROJECT_ROOT

MAIN = PROJECT_ROOT / "metascreener" / "main.py"


@pytest.fixture(scope="module")
def tree():
    return ast.parse(MAIN.read_text(encoding="utf-8"))


def _class(tree, name):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name} not found in main.py")


def _func(tree, cls_name, func_name):
    for node in _class(tree, cls_name).body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return node
    return None


def _calls(node):
    """Every called name or attribute, as dotted text."""
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.append(f.id)
            elif isinstance(f, ast.Attribute):
                base = f.value
                prefix = base.id if isinstance(base, ast.Name) else (
                    base.attr if isinstance(base, ast.Attribute) else "")
                out.append(f"{prefix}.{f.attr}" if prefix else f.attr)
    return out


class TestNothingDestroysTheApplication:

    def test_init_never_destroys(self, tree):
        """Mentions, not just calls. The old line was
        ``self.after(0, self.destroy)`` — ``destroy`` is passed as a
        *reference* there, so a call-only check walks straight past the
        very statement this test exists to forbid."""
        init = _func(tree, "MetaScreenerApp", "__init__")
        mentions = [n for n in ast.walk(init)
                    if isinstance(n, ast.Attribute) and n.attr == "destroy"]
        assert not mentions, (
            "__init__ can still tear the application down; a user who "
            "declines a provider must keep the deterministic stages"
        )

    def test_init_has_no_early_return(self, tree):
        """A bare ``return`` in ``__init__`` is how the old flow skipped
        building the notebook, the plugin list and both event bindings."""
        init = _func(tree, "MetaScreenerApp", "__init__")
        returns = [n for n in ast.walk(init) if isinstance(n, ast.Return)]
        assert not returns, "an early return leaves the app half-built"

    def test_the_old_prompt_is_gone(self, tree):
        assert _func(tree, "MetaScreenerApp", "_prompt_api_key_always") is None


class TestTheUIIsBuiltBeforeTheProviderConversation:

    def _index_of(self, init, predicate):
        for i, stmt in enumerate(init.body):
            if predicate(stmt):
                return i
        return None

    def test_the_notebook_exists_before_any_provider_step(self, tree):
        init = _func(tree, "MetaScreenerApp", "__init__")
        # An AST dump renders `ttk.Notebook` as nested nodes, not as the
        # dotted source text, so match the attribute name alone.
        nb = self._index_of(init, lambda s: "'Notebook'" in ast.dump(s))
        prov = self._index_of(
            init, lambda s: "provider" in ast.dump(s).lower())
        assert nb is not None, "the notebook is not created in __init__"
        if prov is not None:
            assert nb < prov, (
                "the provider step runs before the notebook exists, which "
                "is what made a dismissed dialog cost the whole GUI"
            )

    def test_plugins_load_unconditionally(self, tree):
        """Not inside an ``if``: stages 03, 04 and 05 need no model and
        must be there whatever the provider conversation concludes."""
        init = _func(tree, "MetaScreenerApp", "__init__")
        top_level = [ast.dump(s) for s in init.body]
        assert any("_load_plugins" in d for d in top_level), (
            "_load_plugins is not called at the top level of __init__, so "
            "some condition can now skip loading every plugin"
        )

    def test_the_close_protocol_is_always_bound(self, tree):
        """``_on_close`` iterates ``self._plugins`` and fires each
        plugin's cancel hooks. The old flow could return before binding
        it, leaving worker threads with nothing to stop them."""
        init = _func(tree, "MetaScreenerApp", "__init__")
        assert any("WM_DELETE_WINDOW" in ast.dump(s) for s in init.body)


class TestTheKeyGoesToTheStore:
    """F-144. The row is about *location*, not about the write."""

    def test_init_does_not_write_env(self, tree):
        init = _func(tree, "MetaScreenerApp", "__init__")
        assert "_save_env_key" not in _calls(init)

    def test_no_method_of_the_app_writes_env_any_more(self, tree):
        cls = _class(tree, "MetaScreenerApp")
        offenders = [n.name for n in cls.body
                     if isinstance(n, ast.FunctionDef)
                     and "_save_env_key" in _calls(n)]
        assert not offenders, (
            f"{offenders} still persist the key through .env, which the "
            f"frozen build unpacks into a directory PyInstaller deletes on "
            f"exit — the write succeeds and the key is gone next launch"
        )

    def test_the_store_is_what_persists_it(self, tree):
        """Positive half: something in the module must actually save."""
        src = MAIN.read_text(encoding="utf-8")
        assert "settings" in src and (
            "update_settings" in src or "save_settings" in src), (
            "nothing in main.py writes the settings store"
        )

    def test_env_is_still_read(self, tree):
        """``.env`` stays supported as an *input* for source runs — the
        decision was that the store becomes the write target, not that
        ``.env`` is dropped."""
        assert _func(tree, "MetaScreenerApp", "__init__") is not None
        src = MAIN.read_text(encoding="utf-8")
        assert "_load_env_file" in src


class TestPluginOneDeclaresItsProvider(object):
    """D8. Plugin 01 needs OpenAI whatever the screening stages are set to,
    and the tab must say so rather than failing mid-run.

    The failure it replaces is specific: a user who has chosen a local
    model reasonably expects the whole application to be free. This tab
    calls OpenAI directly and is billed, and until now the only way to
    learn that was to run it.
    """

    def test_the_banner_names_openai_and_the_cost(self):
        src = (PROJECT_ROOT / "plugins" / "01_reference_extractor"
               / "plugin.py").read_text(encoding="utf-8")
        assert "OpenAI API key" in src
        assert "billed" in src

    def test_it_says_the_screening_provider_does_not_apply(self):
        """The specific confusion: 'I chose local, so this is free too.'"""
        src = (PROJECT_ROOT / "plugins" / "01_reference_extractor"
               / "plugin.py").read_text(encoding="utf-8")
        assert "local model" in src
