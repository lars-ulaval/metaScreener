
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_provider_detect.py — D4/D5: three states, three different fixes.

"Not installed", "installed but not running" and "running with no models"
are three different problems with three different remedies, and telling a
user the wrong one wastes their afternoon. So they are distinct states,
not one "unavailable" with a vague message.

Two rules the detector must never break:

* **it must not require Ollama to exist.** A machine with no Ollama at
  all is a supported configuration — that user goes to OpenAI, and
  nothing about their launch may be slower or noisier for it;
* **it must not start anything.** D5 is explicit: detect that the server
  is down, give the command, do *not* run it. metaScreener does not
  launch background processes, so detection uses ``shutil.which`` and an
  HTTP call, never ``subprocess``.

The fake server
---------------
The wave brief points at "the stdlib ``http.server`` idiom in
``tests/test_cancellation.py``". **There is no such idiom** — that file
contains no ``http.server`` usage, and neither does any other file under
``tests/``. It was established here instead. It binds ``127.0.0.1`` on
port 0, so the OS allocates a free ephemeral port and nothing leaves the
loopback interface: no external network, and no fixed port to collide
with a developer's real Ollama on 11434.

**Session C moved the body to ``tests/helpers_fake_server.py``** and left
the names below bound to it. Session C's discovery and combobox tests
need the same server, and a second copy would be a second definition of
what a real server answers — which is exactly the drift those tests exist
to prevent. Nothing about the behaviour changed.
"""
import importlib.util
import json
import sys

import pytest

from conftest import PROJECT_ROOT
from helpers_fake_server import dead_url, models_body, serve


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


# ---------------------------------------------------------------------------
# The fake server — body in tests/helpers_fake_server.py, one copy only
# ---------------------------------------------------------------------------

_serve = serve
_models_body = models_body


@pytest.fixture
def dead_endpoint():
    """A port nothing is listening on — bound, read, then released."""
    return dead_url()


INSTALLED = lambda _name: "/usr/local/bin/ollama"
ABSENT = lambda _name: None


# ---------------------------------------------------------------------------
# The four states
# ---------------------------------------------------------------------------

class TestTheStatesAreDistinguished:

    def test_a_server_with_models_is_ready(self):
        url, stop = _serve(_models_body(["qwen2.5:7b", "llama3.2"]))
        try:
            d = D.detect(url, which=ABSENT)
        finally:
            stop()
        assert d.state == D.READY
        assert d.models == ("llama3.2", "qwen2.5:7b")

    def test_a_reachable_server_is_ready_even_with_no_binary_present(self):
        """A remote Ollama, or LM Studio, or llama.cpp. If the server
        answers, whether a local binary exists is irrelevant — the binary
        only ever discriminates the *message* when nothing answers."""
        url, stop = _serve(_models_body(["m"]))
        try:
            assert D.detect(url, which=ABSENT).state == D.READY
        finally:
            stop()

    def test_a_server_with_an_empty_list_has_no_models(self):
        """D3's trigger: installed, running, nothing pulled. The remedy is
        to pull a model, which is a different action from starting a
        server or installing one."""
        url, stop = _serve(_models_body([]))
        try:
            d = D.detect(url, which=INSTALLED)
        finally:
            stop()
        assert d.state == D.NO_MODELS
        assert d.models == ()

    def test_binary_present_and_nothing_listening_is_not_running(
            self, dead_endpoint):
        d = D.detect(dead_endpoint, which=INSTALLED, timeout=0.5)
        assert d.state == D.NOT_RUNNING

    def test_no_binary_and_nothing_listening_is_not_installed(
            self, dead_endpoint):
        d = D.detect(dead_endpoint, which=ABSENT, timeout=0.5)
        assert d.state == D.NOT_INSTALLED


class TestEachStateSaysSomethingDifferentAndActionable:
    """The whole reason the states are separate."""

    def _detail(self, state, endpoint, which):
        return D.detect(endpoint, which=which, timeout=0.5).detail

    def test_the_three_failure_messages_are_all_different(self, dead_endpoint):
        not_installed = self._detail(None, dead_endpoint, ABSENT)
        not_running = self._detail(None, dead_endpoint, INSTALLED)
        url, stop = _serve(_models_body([]))
        try:
            no_models = D.detect(url, which=INSTALLED).detail
        finally:
            stop()
        assert len({not_installed, not_running, no_models}) == 3

    def test_not_running_names_the_command_and_does_not_run_it(
            self, dead_endpoint):
        """D5. metaScreener does not launch background processes."""
        d = D.detect(dead_endpoint, which=INSTALLED, timeout=0.5)
        assert "ollama serve" in d.detail

    def test_not_installed_does_not_tell_the_user_to_run_a_command(
            self, dead_endpoint):
        """Telling someone to run `ollama serve` when they have no Ollama
        is the wasted afternoon this split exists to prevent."""
        d = D.detect(dead_endpoint, which=ABSENT, timeout=0.5)
        assert "ollama serve" not in d.detail

    def test_nothing_in_detection_shells_out(self):
        """D5, asserted against the module's own AST.

        Read as structure rather than as text: a raw substring search
        matches the docstring that *explains* the rule, so the
        documentation would break the check that enforces it. Names are
        taken from imports and attribute access, the way
        ``tests/test_frozen_build_spec.py`` derives its package list.
        """
        import ast
        tree = ast.parse((PROJECT_ROOT / "plugins" / "_common"
                          / "provider_detect.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "subprocess" not in imported, "detection must not shell out"

        called = {
            node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert not ({"system", "Popen", "run", "call", "check_output"}
                    & called), f"process-spawning call in detection: {called}"


class TestItNeverRequiresOllamaAndNeverHangs:

    def test_a_machine_with_no_ollama_still_returns_promptly(
            self, dead_endpoint):
        d = D.detect(dead_endpoint, which=ABSENT, timeout=0.5)
        assert d.state == D.NOT_INSTALLED
        assert d.can_use is False

    def test_a_slow_server_is_abandoned_rather_than_waited_on(self):
        """Detection runs on a launch path. A server that accepts the
        connection and then never answers must not hold the GUI."""
        # 0.6s against a 0.25s timeout: comfortably over, without paying
        # the difference in wall-clock on every suite run.
        url, stop = _serve(_models_body(["m"]), delay=0.6)
        try:
            d = D.detect(url, which=INSTALLED, timeout=0.25)
        finally:
            stop()
        assert d.state == D.NOT_RUNNING, "a timeout is not a ready server"

    def test_detection_never_raises(self, dead_endpoint):
        """Every failure is a state, not an exception. A launch path that
        can raise is a launch path that can fail to launch."""
        for which in (ABSENT, INSTALLED):
            for endpoint in (dead_endpoint, "", "not a url", "http://"):
                assert D.detect(endpoint, which=which, timeout=0.25).state \
                    in D.STATES


class TestMalformedAnswersDegradeRatherThanCrash:

    def test_non_json_is_not_a_ready_server(self):
        url, stop = _serve(lambda p: "<html>hello</html>"
                           if p.endswith("/models") else None)
        try:
            assert D.detect(url, which=INSTALLED).state == D.NOT_RUNNING
        finally:
            stop()

    def test_a_500_is_not_a_ready_server(self):
        url, stop = _serve(_models_body(["m"]), status=500)
        try:
            assert D.detect(url, which=INSTALLED).state == D.NOT_RUNNING
        finally:
            stop()

    def test_an_unexpected_shape_yields_no_models_not_a_crash(self):
        url, stop = _serve(lambda p: json.dumps({"models": ["wrong-key"]})
                           if p.endswith("/models") else None)
        try:
            d = D.detect(url, which=INSTALLED)
        finally:
            stop()
        assert d.state == D.NO_MODELS

    def test_entries_without_an_id_are_skipped_not_fatal(self):
        url, stop = _serve(lambda p: json.dumps(
            {"data": [{"id": "good"}, {"no_id": 1}, "not-a-dict"]})
            if p.endswith("/models") else None)
        try:
            assert D.detect(url, which=INSTALLED).models == ("good",)
        finally:
            stop()


# ---------------------------------------------------------------------------
# Discovery is an aid, never a gate
# ---------------------------------------------------------------------------

class TestDiscoveryNeverBlocks:
    """The model control is an *editable* combobox precisely because
    llama.cpp ignores the model field entirely and a readonly dropdown
    would rebuild the enumeration problem this project keeps removing."""

    def test_a_failed_list_call_returns_empty_rather_than_raising(
            self, dead_endpoint):
        assert D.list_models(dead_endpoint, timeout=0.25) == ()

    def test_a_successful_list_is_sorted_and_deduplicated(self):
        url, stop = _serve(_models_body(["b", "a", "b"]))
        try:
            assert D.list_models(url) == ("a", "b")
        finally:
            stop()
