# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_model_discovery.py — session C: what the model control shows, and
**where its fixtures come from**.

The trap this file is written against
-------------------------------------
Session B's most serious defect was not a missing test. It was a test
that certified a state the system cannot produce: a helper hand-built
``probe = SimpleNamespace(state="ready")`` for ``provider="openai"``,
which the real detector could not emit for the vendor, so 926 tests were
green while the OpenAI provider could not run at all.

    **A test fixture that constructs a state by hand must be checkable
    against the producer that would create it in production.**

A combobox tested against a fabricated model list is that same trap in a
new place. So this file **fabricates nothing.** Every ``Detection`` it
asserts on is produced by running the real ``detect()`` against the real
fake server — ``PRODUCED``, below — and three guards keep it that way:

1. ``test_every_state_is_produced_rather_than_constructed`` — the table
   must cover ``provider_detect.STATES`` exactly. A state the detector
   cannot reach cannot be tested here, and a state it *can* reach cannot
   be forgotten.
2. ``test_this_file_constructs_no_detection`` — an AST check over this
   file's own source forbidding ``Detection(…)`` and
   ``SimpleNamespace(…)``. Read as structure rather than as text,
   because the prose above names both and a substring search would match
   the paragraph explaining the rule. Same idiom as
   ``test_provider_detect.py``'s ``subprocess`` check.
3. ``TestTheProviderAndTheStateArePairedByTheProducer`` — the guard that
   would actually have caught session B. Its defect was not a state
   outside ``STATES``: ``"ready"`` is in ``STATES``. It was the
   **(provider, state) pair** — ready-for-openai — so the check has to be
   over the pair, against a server that behaves the way the vendor
   behaves (401 without a Bearer token).

Discovery is an aid, never a gate
---------------------------------
Asserted in both directions: every branch offers a usable control, and
no branch returns anything a caller could read as a refusal.
"""
import ast
import importlib.util
import sys

import pytest

from conftest import PROJECT_ROOT
from helpers_fake_server import (
    dead_url, serve_authenticated, serve_models, serve,
)


def _load():
    name = "_provider_detect_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, str(PROJECT_ROOT / "plugins" / "_common" / "provider_detect.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


D = _load()

INSTALLED = lambda _name: "/usr/local/bin/ollama"      # noqa: E731
ABSENT = lambda _name: None                            # noqa: E731

OFFERED = ("llama3.2", "qwen2.5:7b")


# ---------------------------------------------------------------------------
# The table, built by execution
# ---------------------------------------------------------------------------

def _produce_every_state():
    """Run the real detector against real servers, once, for each state.

    Session-scoped rather than per-test because each entry costs a
    server start and a socket round trip, and the point is *provenance*,
    not repetition.
    """
    out = {}

    url, stop = serve_models(OFFERED)
    try:
        out[D.READY] = D.detect(url, which=ABSENT)
    finally:
        stop()

    url, stop = serve_models([])
    try:
        out[D.NO_MODELS] = D.detect(url, which=INSTALLED)
    finally:
        stop()

    dead = dead_url()
    out[D.NOT_RUNNING] = D.detect(dead, which=INSTALLED, timeout=0.25)
    out[D.NOT_INSTALLED] = D.detect(dead, which=ABSENT, timeout=0.25)
    return out


PRODUCED = _produce_every_state()


class TestTheFixturesCameFromTheProducer:
    """The first thing this session built, because without it the rest of
    the file is session B's defect with new nouns."""

    def test_every_state_is_produced_rather_than_constructed(self):
        assert set(PRODUCED) == set(D.STATES), (
            f"states the detector declares but no server here produced: "
            f"{set(D.STATES) - set(PRODUCED)}"
        )

    def test_each_entry_reports_the_state_it_is_filed_under(self):
        """The table is keyed by the state the detector *returned*, not
        by the state the author expected."""
        for state, detection in PRODUCED.items():
            assert detection.state == state

    def test_the_ready_entry_carries_the_names_the_server_listed(self):
        """The model list under test is the server's own answer, sorted
        and deduplicated by the real code path — not a literal."""
        assert PRODUCED[D.READY].models == tuple(sorted(OFFERED))

    def test_this_file_constructs_no_detection(self):
        """Read as structure, not as text: the docstring above names
        both constructors in order to forbid them, so a substring search
        would match the rule rather than a violation."""
        tree = ast.parse(
            (PROJECT_ROOT / "tests" / "test_model_discovery.py")
            .read_text(encoding="utf-8"))
        built = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (node.func.attr if isinstance(node.func, ast.Attribute)
                    else getattr(node.func, "id", ""))
            if name in ("Detection", "SimpleNamespace"):
                built.append(name)
        assert built == [], (
            f"hand-built {built} — every state asserted on here must come "
            f"from the real detector, or this file certifies fiction"
        )

    def test_not_checked_is_not_a_detection_state(self):
        """``last_known()`` returning ``None`` is the *absence* of a
        detection. Filing it among the four would make "we have not
        looked" indistinguishable from something the server said."""
        assert D.NOT_CHECKED not in D.STATES


class TestTheProviderAndTheStateArePairedByTheProducer:
    """Session B's actual defect, generalised.

    ``"ready"`` was in ``STATES`` all along. What no producer could make
    was ``ready`` **for ``provider="openai"``**, because the only supplier
    of that probe was an unauthenticated GET and the vendor answers 401.
    So the check is over the pair, against a server that behaves the way
    the vendor behaves.
    """

    def test_ready_for_openai_is_reachable_when_a_key_is_supplied(self):
        url, stop = serve_authenticated(OFFERED)
        try:
            d = D.detect(url, which=ABSENT, api_key="sk-a-real-key",
                         provider="openai")
        finally:
            stop()
        assert d.state == D.READY, (
            "the pair session B's fixture asserted and no producer could "
            "make; if this fails, that defect is back"
        )
        assert d.models == tuple(sorted(OFFERED))

    def test_ready_for_openai_is_unreachable_without_one(self):
        """The other half of the pair: the server must actually be
        discriminating, or the test above proves nothing."""
        url, stop = serve_authenticated(OFFERED)
        try:
            d = D.detect(url, which=ABSENT, api_key="", provider="openai")
        finally:
            stop()
        assert d.state != D.READY

    def test_an_authenticated_failure_never_sends_an_openai_user_to_ollama(
            self):
        url, stop = serve_authenticated(OFFERED)
        try:
            d = D.detect(url, which=INSTALLED, api_key="",
                         provider="openai")
        finally:
            stop()
        assert "ollama" not in d.detail.lower()


# ---------------------------------------------------------------------------
# What the control shows, in each of the states a real server produces
# ---------------------------------------------------------------------------

class TestWhatTheControlShows:

    def test_a_ready_server_offers_its_own_list(self):
        c = D.model_choices(PRODUCED[D.READY])
        assert c.values == tuple(sorted(OFFERED))
        assert c.state == D.READY

    def test_a_ready_server_still_says_you_may_type_something_else(self):
        """llama.cpp ignores the model field entirely. A list presented
        as the set of valid answers would rebuild the enumeration problem
        this project exists to remove."""
        note = D.model_choices(PRODUCED[D.READY]).note.lower()
        assert "type" in note

    @pytest.mark.parametrize(
        "state", [D.NO_MODELS, D.NOT_RUNNING, D.NOT_INSTALLED])
    def test_a_failure_offers_no_names_and_says_why(self, state):
        c = D.model_choices(PRODUCED[state])
        assert c.values == ()
        assert c.note.strip()
        assert c.state == state

    def test_nothing_checked_yet_says_so_rather_than_showing_an_empty_list(
            self):
        c = D.model_choices(None)
        assert c.values == ()
        assert c.state == D.NOT_CHECKED
        assert c.note != D.model_choices(PRODUCED[D.NO_MODELS]).note, (
            "'we have not looked' and 'the server has nothing pulled' are "
            "different claims and only one of them is about the server"
        )

    def test_the_three_failure_notes_stay_distinct(self):
        """The flattening D4/D5 exist to prevent, checked at the second
        place it could happen. Detection keeps them apart; discovery must
        not put them back together."""
        notes = {D.model_choices(PRODUCED[s]).note
                 for s in (D.NO_MODELS, D.NOT_RUNNING, D.NOT_INSTALLED)}
        assert len(notes) == 3, notes

    def test_the_detection_message_is_carried_through_verbatim(self):
        for state in (D.NO_MODELS, D.NOT_RUNNING, D.NOT_INSTALLED):
            assert PRODUCED[state].detail in D.model_choices(
                PRODUCED[state]).note

    def test_not_running_and_not_installed_still_say_different_things(self):
        """The specific confusion the split exists for: telling someone
        to start a server they never installed."""
        running = D.model_choices(PRODUCED[D.NOT_RUNNING]).note
        installed = D.model_choices(PRODUCED[D.NOT_INSTALLED]).note
        assert "ollama serve" in running
        assert "ollama serve" not in installed


class TestDiscoveryIsAnAidNeverAGate:
    """The property the brief states twice, asserted in both directions."""

    @pytest.mark.parametrize("state", list(D.STATES))
    def test_no_state_produces_anything_that_reads_as_a_refusal(self, state):
        c = D.model_choices(PRODUCED[state])
        assert not hasattr(c, "enabled")
        assert not hasattr(c, "disabled")
        assert isinstance(c.values, tuple)

    def test_a_failed_discovery_does_not_change_whether_the_run_may_start(
            self):
        """Readiness is decided by ``llm_readiness`` from the probe, and
        ``model_choices`` is not one of its inputs. A discovery failure
        that also disabled the control would block a user whose server
        simply will not enumerate."""
        import inspect
        import plugins._common.stage_state as ss
        assert "model_choices" not in inspect.signature(
            ss.llm_readiness).parameters
        src = inspect.getsource(ss.llm_readiness)
        assert "model_choices" not in src

    @pytest.mark.parametrize("rel", ["plugins/06_el/ui.py",
                                     "plugins/07_il/ui.py"])
    def test_the_model_control_is_never_switched_off_by_the_views(self, rel):
        """Asserted against the Views' source: **nothing may set the
        model control's state**, in any branch, for any reason. A control
        the user can still type into is the whole of "never a gate", and
        the branch that would disable it is exactly the one a discovery
        failure would reach.

        The check is narrow on purpose. An earlier version flagged every
        call on a model-named widget and caught ``configure(values=…)`` —
        the line that *fills* the dropdown, which is the feature. A guard
        that fires on the thing it is meant to permit gets deleted, not
        obeyed, so it names ``state`` specifically: a ``.state([…])``
        call, or a ``state=`` keyword to ``configure``/``config``.
        """
        path = PROJECT_ROOT.joinpath(*rel.split("/"))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not isinstance(fn, ast.Attribute):
                continue
            target = fn.value
            if not (isinstance(target, ast.Attribute)
                    and "model" in target.attr.lower()):
                continue
            if fn.attr == "state":
                offenders.append(f"{rel}:{node.lineno} .state()")
            elif fn.attr in ("configure", "config") and any(
                    kw.arg == "state" for kw in node.keywords):
                offenders.append(f"{rel}:{node.lineno} configure(state=)")
        assert offenders == [], offenders

    @pytest.mark.parametrize("rel", ["plugins/06_el/ui.py",
                                     "plugins/07_il/ui.py"])
    def test_the_model_control_is_a_combobox_and_is_not_readonly(self, rel):
        """The one property that is genuinely about the widget rather
        than about the data, so it is pinned rather than eyeballed. A
        ``state="readonly"`` combobox cannot be typed into, which would
        make discovery a gate by construction."""
        src = PROJECT_ROOT.joinpath(*rel.split("/")).read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        combos = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "Combobox"]
        assert combos, f"{rel} has no model combobox"
        for node in combos:
            for kw in node.keywords:
                assert kw.arg != "state", (
                    f"{rel}:{node.lineno} the model combobox declares a "
                    f"state; readonly would rebuild the enumeration problem"
                )


class TestListModelsKeepsItsOwnContract:
    """The flattening the characterisation commit recorded is real, and
    it is confined to ``list_models``, whose documented job is to answer
    *what names are there* for a caller whose remedy is the same in every
    failure. The fix was therefore to give the tabs a path that does not
    flatten — ``detect`` plus ``model_choices`` — rather than to change a
    helper whose contract is correct for its own caller.
    """

    def test_it_still_returns_a_bare_tuple(self):
        url, stop = serve_models(["b", "a", "b"])
        try:
            assert D.list_models(url) == ("a", "b")
        finally:
            stop()

    def test_it_still_never_raises(self):
        assert D.list_models(dead_url(), timeout=0.25) == ()

    def test_the_tab_path_does_not_use_it(self):
        """If a View ever calls ``list_models``, the three states are
        flattened again at the place the flattening matters."""
        for rel in ("plugins/06_el/ui.py", "plugins/07_il/ui.py",
                    "plugins/03_harmoniser/ui.py"):
            src = PROJECT_ROOT.joinpath(*rel.split("/")).read_text(
                encoding="utf-8")
            assert "list_models" not in src, rel


class TestMalformedAnswersReachTheControlAsStatesNotCrashes:
    """Discovery runs on a path a user is waiting on. Every degenerate
    server must produce a usable control rather than an exception."""

    @pytest.mark.parametrize("body,kw", [
        (lambda p: "<html>not json</html>", {}),
        (lambda p: '{"data": "not a list"}', {}),
        (lambda p: '{"models": ["wrong-key"]}', {}),
        (lambda p: '{"data": [{"no_id": 1}, "not-a-dict"]}', {}),
    ])
    def test_a_degenerate_server_still_yields_a_usable_control(self, body, kw):
        url, stop = serve(body, **kw)
        try:
            d = D.detect(url, which=INSTALLED, timeout=0.5)
        finally:
            stop()
        c = D.model_choices(d)
        assert c.state in D.STATES
        assert isinstance(c.values, tuple)
        assert c.note.strip()

    def test_a_slow_server_is_abandoned_and_the_control_still_works(self):
        url, stop = serve_models(OFFERED, delay=0.6)
        try:
            d = D.detect(url, which=INSTALLED, timeout=0.25)
        finally:
            stop()
        c = D.model_choices(d)
        assert c.values == ()
        assert c.note.strip()
        assert c.state == D.NOT_RUNNING
