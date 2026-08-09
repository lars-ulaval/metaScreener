# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_plugin_contract.py - Every plugin must be loadable by a named entry point.

Regression cover for F-31. metascreener/main.py:127-194 resolves a plugin
through four strategies in order:

  1. a module-level build_tab(nb, ...)
  2. a class named exactly `Plugin`
  3. a factory named exactly `make_plugin`
  4. fallback: the first class in vars(module) that has a build_tab attribute

Plugins 01, 02, and 03 exported `create_plugin`, which is not any of the
first three, so all three loaded only through strategy 4 - an untyped scan
over module attributes in definition order. It worked by luck: it happens
to reach the right class because neither ReferencesOfXView nor
HarmoniserView defines a build_tab attribute. Give either View one, or
reorder the imports at the top of a plugin.py, and tab loading breaks
silently (main.py only print()s the failure, and the windowed PyInstaller
build has nowhere for stdout to go).

These tests pin every plugin to a named entry point.
"""
import inspect

import pytest

from conftest import _import_plugin


PLUGIN_DIRS = [
    "01_reference_extractor",
    "02_references_of_x",
    "03_harmoniser",
    "04_eh",
    "05_ih",
    "06_el",
    "07_il",
]

# The names main.py looks for, in the order it tries them.
NAMED_ENTRY_POINTS = ("build_tab", "Plugin", "make_plugin")


@pytest.fixture(scope="module", params=PLUGIN_DIRS)
def plugin_module(request):
    return request.param, _import_plugin(request.param)


class TestNamedEntryPoint:

    def test_exposes_a_named_entry_point(self, plugin_module):
        name, mod = plugin_module
        found = [ep for ep in NAMED_ENTRY_POINTS if hasattr(mod, ep)]
        assert found, (
            "%s exposes none of %s, so metascreener/main.py can only load it "
            "through the untyped fallback scan (F-31)" % (name, list(NAMED_ENTRY_POINTS))
        )

    def test_does_not_use_the_legacy_factory_name(self, plugin_module):
        name, mod = plugin_module
        assert not hasattr(mod, "create_plugin"), (
            "%s exports create_plugin, which the loader does not recognise; "
            "the factory it looks for is make_plugin" % name
        )

    def test_declares_a_tab_title(self, plugin_module):
        name, mod = plugin_module
        title = getattr(mod, "TAB_TITLE", None)
        assert isinstance(title, str) and title.strip(), (
            "%s has no usable TAB_TITLE; its tab would be labelled 'Plugin'" % name
        )


class TestFactorySignature:

    def test_make_plugin_is_callable_with_one_argument(self, plugin_module):
        """main.py:158-165 tries make_plugin(app, meta), then (app), then ()."""
        name, mod = plugin_module
        factory = getattr(mod, "make_plugin", None)
        if factory is None:
            pytest.skip("%s uses the Plugin class entry point" % name)
        sig = inspect.signature(factory)
        accepted = [
            n for n, p in sig.parameters.items()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        assert len(accepted) <= 2, (
            "%s.make_plugin takes %d positional parameters; main.py never "
            "passes more than two" % (name, len(accepted))
        )
