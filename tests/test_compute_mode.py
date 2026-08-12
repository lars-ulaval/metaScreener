# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_compute_mode.py — wave 12, F-150: the user could not find out that
their model was running on the CPU until after the run.

What happened
-------------
The maintainer's run took hours and pegged his CPU. His own Ollama log
says why::

    msg="discovering available GPUs..."
    inference compute id=cpu library=cpu name=cpu total="63.8 GiB"
    msg="vram-based default context" total_vram="0 B"

Ollama never found his RTX 3060 and ran the model entirely on the CPU.

**metaScreener cannot fix that and must not try.** GPU detection is
Ollama's business and the user's machine is not ours to configure. What
metaScreener can do is be honest about the consequence *before* a
four-hour run rather than after, and Ollama already publishes the fact:
``/api/ps`` reports, per loaded model, how much of it sits in VRAM.

So this is a reporting change, not a control one. Nothing here gates a
run: CPU is slow, not wrong, and a user who knows it is slow and starts
it anyway is doing something reasonable.

The tri-state that matters
--------------------------
``size_vram == 0`` is CPU, ``size_vram == size`` is GPU, and anything
between is a split — a real Ollama state when a model does not fit. But
the fourth answer is the important one: **not knowing**. A server that
does not answer ``/api/ps``, a non-Ollama OpenAI-compatible server that
has no such route, and a server with no model loaded yet are all "we
cannot say", and none of them may be reported as "CPU". Telling a user
on a working GPU that they are on the CPU would send them to reinstall
drivers they did not need to touch, which is the same class of harm as
D5's three distinct detection messages.
"""
import json

import pytest

from helpers_fake_server import dead_url, serve
from plugins._common import provider_detect as pd


def _ps_body(models):
    """The ``/api/ps`` payload Ollama returns for loaded models."""
    def _body(path):
        if not path.endswith("/api/ps"):
            return None
        return json.dumps({"models": models})
    return _body


def _model(name="llama3.2:latest", size=6_000_000_000, size_vram=0):
    return {"name": name, "model": name, "size": size,
            "size_vram": size_vram}


class TestTheUrlIsTheNativeApi:
    """Ollama publishes this on its own surface, not the compatible one."""

    @pytest.mark.parametrize("endpoint,expected", [
        ("http://localhost:11434/v1", "http://localhost:11434/api/ps"),
        ("http://localhost:11434/v1/", "http://localhost:11434/api/ps"),
        ("http://localhost:11434", "http://localhost:11434/api/ps"),
        ("http://box.local:1234/v1", "http://box.local:1234/api/ps"),
    ])
    def test_the_v1_suffix_is_stripped(self, endpoint, expected):
        assert pd.compute_mode_url(endpoint) == expected

    def test_it_matches_the_pull_url_derivation(self):
        """Same derivation as ``model_pull.pull_url``, which already had
        to solve this. Two rules for one thing would drift."""
        from plugins._common import model_pull as mp
        e = "http://localhost:11434/v1"
        assert (pd.compute_mode_url(e).rsplit("/", 1)[0]
                == mp.pull_url(e).rsplit("/", 1)[0])


class TestWhatTheServerSays:

    def test_a_model_wholly_in_vram_is_gpu(self):
        url, stop = serve(_ps_body([_model(size=6_000, size_vram=6_000)]))
        try:
            got = pd.compute_mode(url)
        finally:
            stop()
        assert got.mode == pd.COMPUTE_GPU
        assert got.known is True

    def test_a_model_with_no_vram_is_cpu(self):
        """The maintainer's case, exactly: total_vram 0 B."""
        url, stop = serve(_ps_body([_model(size=6_000, size_vram=0)]))
        try:
            got = pd.compute_mode(url)
        finally:
            stop()
        assert got.mode == pd.COMPUTE_CPU
        assert got.known is True
        assert "CPU" in got.detail

    def test_a_partly_offloaded_model_is_neither(self):
        url, stop = serve(_ps_body([_model(size=6_000, size_vram=2_400)]))
        try:
            got = pd.compute_mode(url)
        finally:
            stop()
        assert got.mode == pd.COMPUTE_PARTIAL
        assert got.known is True

    def test_the_named_model_is_preferred_when_several_are_loaded(self):
        url, stop = serve(_ps_body([
            _model("other:latest", size=6_000, size_vram=6_000),
            _model("llama3.2:latest", size=6_000, size_vram=0),
        ]))
        try:
            got = pd.compute_mode(url, model="llama3.2:latest")
        finally:
            stop()
        assert got.mode == pd.COMPUTE_CPU, (
            "reporting another loaded model's placement would be a "
            "confident answer about the wrong thing"
        )


class TestNotKnowingIsItsOwnAnswer:
    """The fourth state, and the one that must never read as CPU."""

    def test_an_unreachable_server_is_unknown(self):
        got = pd.compute_mode(dead_url())
        assert got.mode == pd.COMPUTE_UNKNOWN
        assert got.known is False

    def test_a_server_without_the_route_is_unknown(self):
        """Any OpenAI-compatible server that is not Ollama: LM Studio,
        llama.cpp, vLLM, or the vendor itself."""
        url, stop = serve(lambda path: None)      # 404 to everything
        try:
            got = pd.compute_mode(url)
        finally:
            stop()
        assert got.mode == pd.COMPUTE_UNKNOWN

    def test_no_model_loaded_is_unknown_rather_than_cpu(self):
        """Ollama unloads idle models. Nothing loaded says nothing about
        where the next one will run."""
        url, stop = serve(_ps_body([]))
        try:
            got = pd.compute_mode(url)
        finally:
            stop()
        assert got.mode == pd.COMPUTE_UNKNOWN

    def test_a_shape_this_code_does_not_understand_is_unknown(self):
        url, stop = serve(lambda path: json.dumps({"unexpected": True})
                          if path.endswith("/api/ps") else None)
        try:
            got = pd.compute_mode(url)
        finally:
            stop()
        assert got.mode == pd.COMPUTE_UNKNOWN

    def test_a_missing_size_vram_field_is_unknown_not_zero(self):
        """Absent is not zero — F-68's rule. An older Ollama that does
        not publish the field must not be reported as running on the CPU."""
        url, stop = serve(_ps_body([{"name": "m", "size": 6_000}]))
        try:
            got = pd.compute_mode(url)
        finally:
            stop()
        assert got.mode == pd.COMPUTE_UNKNOWN

    def test_it_never_raises(self):
        """Reached from a pre-run path; a probe that raises would block a
        run over a reporting nicety."""
        for endpoint in ("", "not a url", "http://", dead_url()):
            assert pd.compute_mode(endpoint).mode == pd.COMPUTE_UNKNOWN


class TestTheVocabularyIsClosed:

    def test_every_mode_is_declared(self):
        assert set(pd.COMPUTE_MODES) == {
            pd.COMPUTE_GPU, pd.COMPUTE_CPU, pd.COMPUTE_PARTIAL,
            pd.COMPUTE_UNKNOWN}

    def test_every_mode_has_a_sentence(self):
        seen = set()
        for models in ([_model(size=9, size_vram=9)],
                       [_model(size=9, size_vram=0)],
                       [_model(size=9, size_vram=4)],
                       []):
            url, stop = serve(_ps_body(models))
            try:
                got = pd.compute_mode(url)
            finally:
                stop()
            seen.add(got.mode)
            assert got.detail.strip(), got.mode
        assert seen == set(pd.COMPUTE_MODES)

    def test_it_does_not_tell_the_user_to_reconfigure_their_machine(self):
        """GPU detection is Ollama's business and the user's machine is
        not ours to configure. The sentence may state the consequence; it
        may not issue instructions about drivers or hardware."""
        url, stop = serve(_ps_body([_model(size=9, size_vram=0)]))
        try:
            detail = pd.compute_mode(url).detail.lower()
        finally:
            stop()
        for word in ("driver", "cuda", "reinstall", "nvidia", "install"):
            assert word not in detail, (word, detail)


class TestItCannotBlockTheInterfaceIndefinitely:
    """F-157, found by reproducing a session A claim.

    ``urlopen(..., timeout=t)`` bounds each socket operation, not the
    total. A server that sends its headers promptly and then dribbles the
    body never trips the timeout — every individual read arrives inside
    it — while the whole call takes as long as the server likes.

    That matters here specifically because ``_confirm_run``
    (``plugins/06_el/ui.py``) calls ``compute_mode`` **on the GUI
    thread**, deliberately: the whole point is that the answer arrives
    before the user decides. So an unbounded read is a frozen application
    at the moment the user presses Run. Measured before the fix, against
    a server dribbling a 4 KB body in 20 chunks::

        timeout=2.0s  ->  elapsed 8.02s   *** NOT BOUNDED ***

    The bound below is generous — three times the timeout — because this
    is a wall-clock assertion on a loaded CI box and the defect it guards
    is a factor-of-four overrun, not a 10% one.
    """

    @staticmethod
    def _dribbler(chunk_sleep=0.3, chunks=20):
        """Headers at once, body in slow pieces. Returns (url, stop)."""
        import threading
        import time as _t
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        # Padding FIRST, so a bounded read is cut mid-object. With the
        # JSON first a truncated read would still parse, which tests the
        # bound but not what the bound does to the answer.
        payload = (" " * 4000
                   + json.dumps({"models": [_model(size=10, size_vram=10)]})
                   ).encode()

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                step = max(1, len(payload) // chunks)
                for i in range(0, len(payload), step):
                    try:
                        self.wfile.write(payload[i:i + step])
                        self.wfile.flush()
                    except Exception:
                        return
                    _t.sleep(chunk_sleep)

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        t = threading.Thread(
            target=lambda: srv.serve_forever(poll_interval=0.01), daemon=True)
        t.start()
        host, port = srv.server_address[:2]

        def stop():
            srv.shutdown()
            srv.server_close()

        return f"http://{host}:{port}/v1", stop

    def test_a_dribbling_server_does_not_hold_the_gui(self):
        import time as _t

        url, stop = self._dribbler()
        try:
            t0 = _t.perf_counter()
            got = pd.compute_mode(url, timeout=1.0)
            elapsed = _t.perf_counter() - t0
        finally:
            stop()

        assert elapsed < 3.0, (
            f"compute_mode blocked for {elapsed:.2f}s against a 1.0s "
            f"timeout; _confirm_run calls this on the GUI thread"
        )
        # Giving up is reported as not knowing, never as CPU.
        assert got.mode == pd.COMPUTE_UNKNOWN

    def test_a_silent_server_is_still_bounded(self):
        """The case urlopen's own timeout already handled; kept so the
        repair cannot regress it."""
        import time as _t

        url, stop = serve(lambda path: None)
        try:
            t0 = _t.perf_counter()
            pd.compute_mode(url, timeout=1.0)
            elapsed = _t.perf_counter() - t0
        finally:
            stop()
        assert elapsed < 3.0, elapsed

    def test_a_prompt_server_is_unaffected(self):
        """The bound must not cost anything in the normal case."""
        import time as _t

        url, stop = serve(_ps_body([_model(size=10, size_vram=10)]))
        try:
            t0 = _t.perf_counter()
            got = pd.compute_mode(url)
            elapsed = _t.perf_counter() - t0
        finally:
            stop()
        assert got.mode == pd.COMPUTE_GPU
        assert elapsed < 1.0, elapsed
