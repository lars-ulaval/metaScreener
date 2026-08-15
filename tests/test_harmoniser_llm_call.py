# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_harmoniser_llm_call.py — wave 12, F-146: "Harmonise + LLM" has never
worked on any modern install, and the error it printed named the wrong
problem.

What the maintainer saw
-----------------------
Clicking "Harmonise + LLM" produced::

    LLM call failed: You tried to access openai.ChatCompletion, but this
    is no longer supported in openai>=1.0.0

``plugins/03_harmoniser/llm_refine.py::_call_openai_json`` was two ``try``
blocks. The first is the modern, correct call. Its except arm was a bare
``except Exception: pass``. The second called ``openai.ChatCompletion``,
removed from the SDK in version 1.0; this project declares
``openai>=1.40.0``, so it has been unreachable-as-a-success for over two
years.

**The visible error therefore proved that the modern call had already
failed, and said nothing whatever about why.** The gate, the provider
routing and the endpoint resolution all worked — the log line reads
``LLM refine: calling OpenAI model=llama3.2:latest`` — and the innermost
call swallowed the real cause and replaced it with a migration notice
about a code path the user never asked for.

Why it survived every review
----------------------------
Two reasons, and the second is a finding about the diagnostic rather than
about this module.

1.  ``llm_refine.py``'s call path has **zero execution coverage**. The
    only assertions that touch it are string and AST matches over the
    unparsed source (``tests/test_harmoniser_provider.py``,
    ``tests/test_per_stage_config.py``), which read the code without
    running it. This file is the first test that executes the function.

2.  ``docs/internal/diagnostic/06_llm_integration.md`` line 156 marks
    this call site **"No — dead (§A1.3)"** in its summary table — while
    its own §A1.3 prose, twenty lines further on, says the opposite and
    is correct: *"Because branch 1 is wrapped in a bare `except
    Exception: pass`, **any** branch-1 failure (missing key, wrong base
    URL, bad model, a fenced JSON reply) surfaces as `RuntimeError(...)`
    — a migration notice about the wrong problem."* The row was not
    unread. It was read, understood in prose, and then contradicted by
    the table — and the table is what got carried forward. See F-148.

The likely masked cause, which §A1.3 also names
------------------------------------------------
Branch 1 parsed with a bare ``json.loads``. The working engine path does
not: ``llm_client._parse_llm_json_array`` strips fenced code blocks,
because local models emit them. A ```-fenced reply from
``llama3.2:latest`` raises inside branch 1, is swallowed, and re-emerges
as the notice above. That is asserted directly below.
"""
import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from conftest import get_harmoniser

ROOT = Path(__file__).resolve().parents[1]
REFINE = ROOT / "plugins" / "03_harmoniser" / "llm_refine.py"


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


#: Interfaces the openai SDK removed at 1.0. Spelled as the trailing
#: attribute name, matched against attribute ACCESS rather than against
#: source text.
REMOVED_ATTRS = ("ChatCompletion", "Completion", "Embedding", "Moderation",
                 "api_key", "api_base", "api_type", "api_version")


def _removed_attribute_uses(path: Path):
    """Attribute accesses naming a removed 0.x interface, structurally.

    Read as structure rather than as text, which is this repository's
    stated rule for a guard and is load-bearing three times over already
    (the ``subprocess`` ban, the ``Detection(...)`` ban, the model-literal
    ban). A substring search matches the *comment that records the rule* —
    and this repair's own docstring quotes ``openai.ChatCompletion`` in
    order to explain why it is gone, which a text search would flag as the
    defect it documents.

    Only accesses rooted at the ``openai`` module count. ``client.chat.
    completions.create`` is the current interface and contains the word
    "completions"; ``resp.api_key`` on some unrelated object is not a
    vendor call. Matching the root avoids both false positives.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr not in REMOVED_ATTRS:
            continue
        root = node
        while isinstance(root, ast.Attribute):
            root = root.value
        if isinstance(root, ast.Name) and root.id == "openai":
            found.append(ast.unparse(node))
    return found


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, text):
        msg = type("M", (), {"content": text})
        self.choices = [type("C", (), {"message": msg})]


def _client(reply=None, raises=None, record=None):
    """A fake OpenAI client whose ``create`` records its kwargs.

    ``**kwargs`` rather than a keyword-only signature, deliberately: F-107
    records that a test double pinned to an exact request shape breaks on
    the first added parameter, which makes it a hidden pin on the caller.
    This one has to tolerate ``timeout=`` being added, which is the point.
    """
    class _Completions:
        def create(self, **kwargs):
            if record is not None:
                record.update(kwargs)
            if raises is not None:
                raise raises
            return _FakeResponse(reply)

    return type("C", (), {"chat": type("Chat", (), {
        "completions": _Completions()})()})()


def _load_refine():
    """The module under test, imported the way the application imports it.

    Loading the file standalone would fail on its relative imports, so it
    is reached through the package: ``get_harmoniser()`` pulls in
    ``plugin.py``, which reaches ``ui.py``, which imports this module.
    """
    get_harmoniser()
    return sys.modules["plugins.03_harmoniser.llm_refine"]


@pytest.fixture
def stub_client(monkeypatch):
    """Install a fake client and return the kwargs recorder.

    ``_call_openai_json`` does ``from plugins._common.llm_client import
    _openai_client_for`` inside its own body, so the lookup happens at
    call time and patching the source module is both sufficient and the
    honest place for it: that function is the one sanctioned client
    builder, and this test must not be able to reach a network.
    """
    from plugins._common import llm_client as lc

    def _install(**kw):
        seen = {}
        monkeypatch.setattr(
            lc, "_openai_client_for",
            lambda *_a, **_k: _client(record=seen, **kw))
        return seen

    return _install


# ---------------------------------------------------------------------------
# 1. the removed interface is gone
# ---------------------------------------------------------------------------

class TestTheRemovedInterfaceIsGone:

    def test_chat_completion_is_not_referenced(self):
        assert _removed_attribute_uses(REFINE) == [], (
            "openai.ChatCompletion was removed in openai>=1.0.0 and this "
            "project declares >=1.40.0"
        )

    def test_the_function_has_one_call_route(self):
        """Two routes are what let the dead one mask the live one."""
        fn = next(n for n in ast.walk(_tree(REFINE))
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_call_openai_json")
        creates = [n for n in ast.walk(fn)
                   if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "create"]
        assert len(creates) == 1, (
            f"expected exactly one .create( call, found {len(creates)}"
        )

    def test_the_sanctioned_client_builder_is_still_used(self):
        """F-117's property, which must survive this repair."""
        fn = next(n for n in ast.walk(_tree(REFINE))
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_call_openai_json")
        assert "_openai_client_for(stage)" in ast.unparse(fn)


# ---------------------------------------------------------------------------
# 2. the call works, including against a local model's output
# ---------------------------------------------------------------------------

class TestTheCallWorks:

    def test_a_plain_json_object_is_returned(self, stub_client):
        # Wave 15d flipped the contract in the open: (parsed, meta), so
        # the chunk driver can contain a bad reply instead of aborting.
        stub_client(reply=json.dumps({"rows": [{"id": "1"}]}))
        got, meta = _load_refine()._call_openai_json(
            model="m", system="s", user="u")
        assert got == {"rows": [{"id": "1"}]}
        assert meta["parse_error"] == ""

    @pytest.mark.parametrize("wrapper", [
        "```json\n{body}\n```",
        "```\n{body}\n```",
        "Here you go:\n```json\n{body}\n```\nHope that helps!",
    ])
    def test_a_fenced_reply_parses(self, stub_client, wrapper):
        """The mechanism the dead branch was hiding.

        A local model that wraps its JSON in a Markdown fence used to
        raise inside branch 1, be swallowed, and surface as a notice about
        openai.ChatCompletion. The engine path has stripped fences since
        wave 6; this path did not. The maintainer's failing run was
        against ``llama3.2:latest``.
        """
        body = json.dumps({"rows": [{"id": "EC-1"}]})
        stub_client(reply=wrapper.format(body=body))
        got, _meta = _load_refine()._call_openai_json(
            model="m", system="s", user="u")
        assert got == {"rows": [{"id": "EC-1"}]}

    def test_the_timeout_reaches_the_call(self, stub_client):
        """``timeout_s`` was consumed only by the dead branch.

        Deleting that branch without threading it into the live one would
        have left plugin 03's LLM path with no timeout expression at all,
        which is the diagnostic's C-19 — a silent regression hiding inside
        a repair.
        """
        seen = stub_client(reply=json.dumps({"rows": []}))
        _load_refine()._call_openai_json(
            model="m", system="s", user="u", timeout_s=7)
        assert seen.get("timeout") == 7

    def test_the_stage_reaches_the_client_builder(self, monkeypatch):
        """F-117's property, executed rather than string-matched."""
        from plugins._common import llm_client as lc
        seen = {}

        def _builder(stage=""):
            seen["stage"] = stage
            return _client(reply=json.dumps({"rows": []}))

        monkeypatch.setattr(lc, "_openai_client_for", _builder)
        mod = _load_refine()
        mod._call_openai_json(model="m", system="s", user="u")
        assert seen["stage"] == mod.STAGE == "harmoniser"


# ---------------------------------------------------------------------------
# 3. a failure names the real cause
# ---------------------------------------------------------------------------

class TestTheErrorIsTheRealOne:

    def test_a_transport_failure_is_not_reported_as_a_migration_notice(
            self, stub_client):
        stub_client(raises=RuntimeError("Connection refused"))

        with pytest.raises(Exception) as ei:
            _load_refine()._call_openai_json(model="m", system="s", user="u")

        text = str(ei.value)
        assert "Connection refused" in text, (
            "the cause the user can act on must survive to the message box"
        )
        assert "ChatCompletion" not in text
        assert "openai>=1.0.0" not in text

    def test_an_unparseable_reply_says_so_without_raising(self, stub_client):
        """FLIPPED at wave 15d: the raise that lived here was one of the
        two measured worker aborts (08 §7 — the maintainer's own
        incident). The reply's unusability is now DATA — (None, meta)
        with the parse error named — and the chunk driver contains it
        per chunk instead of losing the whole table."""
        stub_client(reply="I am not JSON at all.")
        got, meta = _load_refine()._call_openai_json(
            model="m", system="s", user="u")
        assert got is None
        assert meta["parse_error"]
        assert meta["reply_chars"] == len("I am not JSON at all.")
        assert "ChatCompletion" not in meta["parse_error"]

    def test_a_client_construction_failure_survives(self, monkeypatch):
        """The gate is upstream, but a misconfigured store can still fail
        here, and it used to fail as a migration notice too."""
        from plugins._common import llm_client as lc

        def _boom(*_a, **_k):
            raise RuntimeError("no api key configured")

        monkeypatch.setattr(lc, "_openai_client_for", _boom)

        with pytest.raises(Exception) as ei:
            _load_refine()._call_openai_json(model="m", system="s", user="u")
        assert "no api key configured" in str(ei.value)
        assert "ChatCompletion" not in str(ei.value)


# ---------------------------------------------------------------------------
# 4. no other module reaches a removed interface
# ---------------------------------------------------------------------------

class TestNoRemovedSdkInterfaceSurvivesAnywhere:
    """The general question, asserted so it stays answered.

    ``openai`` ships shims for its 0.x names that exist only to raise, so
    ``hasattr(openai, "ChatCompletion")`` is True on 1.106.0 and no
    runtime check would catch this. A source-level ban is what works.
    """

    def test_no_python_source_uses_a_removed_interface(self):
        offenders = []
        for path in sorted(ROOT.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith(("build/", "dist/", ".pytest_cache/")) \
                    or "__pycache__" in rel:
                continue
            for use in _removed_attribute_uses(path):
                offenders.append(f"{rel}: {use}")
        assert offenders == [], offenders

    def test_the_check_would_have_caught_the_defect(self):
        """A guard nobody has seen fail is a guard nobody has tested.

        The pre-fix body, verbatim, must be flagged — otherwise this
        file's central assertion could be passing because the finder is
        broken rather than because the tree is clean.
        """
        import tempfile

        before = (
            "import openai\n"
            "resp = openai.ChatCompletion.create(model=m, messages=x)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "before.py"
            p.write_text(before, encoding="utf-8")
            assert _removed_attribute_uses(p) == ["openai.ChatCompletion"]

    def test_the_current_interface_is_not_flagged(self):
        """The live call must not read as the dead one."""
        import tempfile

        after = (
            "client = _openai_client_for(stage)\n"
            "resp = client.chat.completions.create(model=m, timeout=t)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "after.py"
            p.write_text(after, encoding="utf-8")
            assert _removed_attribute_uses(p) == []
