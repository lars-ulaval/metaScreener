
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_model_pull.py — D3: the pull must be refusable, interruptible, and
honest about its size before it starts.

Why the ceremony is not polish
------------------------------
The repository's mirror-image defect is that ``_run_clicked`` starts a
**billable** operation with no cost estimate, no request count and no
confirmation, and the only cost statement in the documentation is wrong
by two to three orders of magnitude (F-125). Adding a multi-gigabyte
download with *less* ceremony than that deserves would repeat the mistake
in a form the user cannot undo — bytes already transferred over a metered
connection are not refundable.

So three properties are asserted, not assumed:

* **refusable** — the size is known and reportable *before* a byte moves;
* **interruptible** — a cancel is honoured mid-stream, promptly;
* **honest** — the figure shown up front is labelled as the estimate it
  is, and the server's own total supersedes it once known.

Why the name is not in a Python constant
----------------------------------------
It lives in ``plugins/_common/recommended_models.json``, which the
documentation points at. A model name in a constant is the enumeration
this project keeps removing: it makes a new model a code change and a
release. The tests below therefore refuse to accept a hardcoded fallback
name — a missing config offers *nothing* rather than something stale.
"""
import importlib.util
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import PROJECT_ROOT


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


MP = _load("_model_pull_under_test", "plugins/_common/model_pull.py")


# ---------------------------------------------------------------------------
# A streaming fake, in the idiom session A established
# ---------------------------------------------------------------------------

def _serve_stream(chunks, *, status=200, hang_after=None):
    """NDJSON, one object per line, flushed as it goes — the shape Ollama's
    pull endpoint actually produces."""
    class _H(BaseHTTPRequestHandler):
        def do_POST(self):
            # Drain the request body before answering. A handler that
            # never reads it can have the connection reset under it before
            # the response is delivered, which showed up here once as a
            # test that passed alone and failed in sequence. A flaky test
            # in a suite that runs on every commit is its own defect.
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            self.send_response(status)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            for i, obj in enumerate(chunks):
                try:
                    self.wfile.write((json.dumps(obj) + "\n").encode())
                    self.wfile.flush()
                except Exception:
                    return
                if hang_after is not None and i == hang_after:
                    time.sleep(5)      # a stall the caller must survive
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    t = threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.01),
                         daemon=True)
    t.start()
    host, port = srv.server_address[:2]

    def stop():
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)

    return f"http://{host}:{port}/v1", stop


# ---------------------------------------------------------------------------
# The recommendation comes from data
# ---------------------------------------------------------------------------

class TestTheRecommendationIsData:

    def test_the_shipped_config_exists_and_parses(self):
        models = MP.recommended_models()
        assert models, "nothing is offered, so D3's pull can never appear"
        assert all(m.name and m.size_bytes > 0 for m in models)

    def test_no_model_name_is_hardcoded_in_the_module(self):
        """The whole point. A name in a constant makes a new model a code
        change; read as AST so the docstring explaining the rule cannot
        break the check enforcing it."""
        import ast
        src = (PROJECT_ROOT / "plugins" / "_common"
               / "model_pull.py").read_text(encoding="utf-8")
        literals = [
            n.value for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ]
        suspects = [s for s in literals
                    if ":" in s and any(c.isdigit() for c in s)
                    and "/" not in s and " " not in s]
        assert not suspects, f"model-name-shaped literals in code: {suspects}"

    def test_a_user_copy_overrides_the_shipped_one(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path / "a"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "x"))
        d = MP.user_config_path().parent
        d.mkdir(parents=True, exist_ok=True)
        MP.user_config_path().write_text(json.dumps(
            {"recommended": [{"name": "mine:1b", "size_bytes": 1}]}),
            encoding="utf-8")
        names = [m.name for m in MP.recommended_models()]
        assert names == ["mine:1b"]

    def test_a_missing_config_offers_nothing_rather_than_something_stale(
            self, monkeypatch):
        monkeypatch.setattr(MP, "_shipped_config_path",
                            lambda: PROJECT_ROOT / "does_not_exist.json")
        monkeypatch.setattr(MP, "user_config_path",
                            lambda: PROJECT_ROOT / "also_not_there.json")
        assert MP.recommended_models() == ()

    def test_a_corrupt_config_offers_nothing_rather_than_raising(
            self, tmp_path, monkeypatch):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(MP, "user_config_path", lambda: bad)
        monkeypatch.setattr(MP, "_shipped_config_path", lambda: bad)
        assert MP.recommended_models() == ()

    def test_the_documentation_points_at_the_file(self):
        """The brief requires the name to live somewhere the documentation
        names. A config file nobody is told about is a constant with extra
        steps."""
        found = [p for p in (PROJECT_ROOT / "docs").rglob("*.md")
                 if "recommended_models.json" in p.read_text(encoding="utf-8")]
        assert found, "no published document mentions recommended_models.json"


# ---------------------------------------------------------------------------
# Honest about size before it starts
# ---------------------------------------------------------------------------

class TestSizeIsKnownBeforeAByteMoves:

    def test_the_offer_carries_a_size(self):
        m = MP.recommended_models()[0]
        assert m.size_bytes > 0
        assert m.human_size.endswith("GB") or m.human_size.endswith("MB")

    def test_the_size_is_labelled_as_an_estimate(self):
        """It comes from a config file, not from the server. Presenting an
        approximation as a fact is how a 'few thousand API calls' got into
        the documentation."""
        assert "about" in MP.offer_text(MP.recommended_models()[0]).lower()

    def test_the_offer_names_the_model_and_the_size_together(self):
        m = MP.recommended_models()[0]
        text = MP.offer_text(m)
        assert m.name in text and m.human_size in text


# ---------------------------------------------------------------------------
# Interruptible
# ---------------------------------------------------------------------------

class TestThePullIsInterruptible:

    def test_a_cancel_stops_the_stream_promptly(self):
        chunks = [{"status": "pulling", "total": 100, "completed": i}
                  for i in range(0, 100)]
        url, stop = _serve_stream(chunks)
        cancel = threading.Event()
        seen = []

        def on_progress(p):
            seen.append(p)
            if len(seen) >= 3:
                cancel.set()

        try:
            result = MP.pull(url, "any:tag", on_progress=on_progress,
                             cancel=cancel, timeout=5)
        finally:
            stop()
        assert result.cancelled is True
        assert result.ok is False
        assert len(seen) < 100, "the stream ran to completion despite a cancel"

    def test_a_cancel_before_the_first_byte_makes_no_request(self):
        cancel = threading.Event()
        cancel.set()
        result = MP.pull("http://127.0.0.1:1/v1", "any:tag",
                         on_progress=lambda p: None, cancel=cancel, timeout=1)
        assert result.cancelled is True

    def test_progress_reports_the_servers_total_not_the_estimate(self):
        chunks = [{"status": "pulling", "total": 2048, "completed": 1024}]
        url, stop = _serve_stream(chunks)
        seen = []
        try:
            MP.pull(url, "any:tag", on_progress=seen.append,
                    cancel=threading.Event(), timeout=5)
        finally:
            stop()
        assert seen and seen[-1].total == 2048
        assert seen[-1].fraction == pytest.approx(0.5)


class TestFailuresAreStatesNotCrashes:

    def test_an_unreachable_server_reports_an_error(self):
        r = MP.pull("http://127.0.0.1:1/v1", "any:tag",
                    on_progress=lambda p: None, cancel=threading.Event(),
                    timeout=1)
        assert r.ok is False and r.cancelled is False and r.error

    def test_a_non_200_reports_an_error(self):
        url, stop = _serve_stream([{"status": "nope"}], status=500)
        try:
            r = MP.pull(url, "any:tag", on_progress=lambda p: None,
                        cancel=threading.Event(), timeout=5)
        finally:
            stop()
        assert r.ok is False and r.error

    def test_a_malformed_line_is_skipped_rather_than_fatal(self):
        url, stop = _serve_stream([
            {"status": "pulling", "total": 10, "completed": 5},
            "not-a-dict",
            {"status": "success"},
        ])
        try:
            r = MP.pull(url, "any:tag", on_progress=lambda p: None,
                        cancel=threading.Event(), timeout=5)
        finally:
            stop()
        assert r.ok is True

    def test_the_pull_url_is_the_native_api_not_the_openai_surface(self):
        """Ollama's pull lives at /api/pull; the stored endpoint ends in
        /v1, which is the OpenAI-compatible surface and has no pull."""
        assert MP.pull_url("http://h:11434/v1") == "http://h:11434/api/pull"
        assert MP.pull_url("http://h:11434/v1/") == "http://h:11434/api/pull"
        assert MP.pull_url("http://h:11434") == "http://h:11434/api/pull"

    def test_nothing_in_the_module_spawns_a_process(self):
        """D5's rule extends here: metaScreener does not launch background
        processes, and a pull is not an excuse to shell out to the CLI."""
        import ast
        tree = ast.parse((PROJECT_ROOT / "plugins" / "_common"
                          / "model_pull.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "subprocess" not in imported
