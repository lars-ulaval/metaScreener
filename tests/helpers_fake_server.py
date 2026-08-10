# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
helpers_fake_server.py — the one fake OpenAI-compatible server.

Extracted from ``tests/test_provider_detect.py``, where session A
established it, so that session C's discovery and combobox tests drive
**the same** server rather than a second one that can drift from it. Two
fake servers is two definitions of what a real server answers, and the
whole point of these tests is that the fixture agrees with the producer.

The rules session A set, kept verbatim:

* it binds ``127.0.0.1`` on port **0**, so the OS allocates a free
  ephemeral port — nothing leaves the loopback interface, and there is no
  fixed 11434 to collide with a developer's real Ollama;
* ``serve_forever(poll_interval=0.01)``, because the default is 0.5s and
  ``shutdown()`` waits for it — half a second of dead time per test in a
  suite that runs on every commit, with the loop doing nothing else;
* the URL ends in ``/v1``, so it is shaped exactly like the endpoints the
  application stores.

``serve_authenticated`` is session C's addition, and it exists for one
reason: session B's worst defect was a fixture asserting a state the real
detector could not produce for the vendor — ``probe.state == "ready"``
for ``provider="openai"``, when the only supplier of that probe was an
**unauthenticated** GET that api.openai.com answers with a 401. A server
that behaves the way the vendor behaves is what makes that pair
checkable, so a test can no longer assert it by construction.
"""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def serve(handler_body, *, status=200, content_type="application/json",
          delay=0.0, require_bearer=False):
    """Run a one-route server on an ephemeral loopback port.

    Returns ``(base_url, stop)``. ``base_url`` ends in ``/v1``.

    ``require_bearer`` makes the server answer **401** to a request that
    carries no ``Authorization: Bearer …`` header, which is what the paid
    vendor does and what session B's probe could not survive.
    """
    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            if delay:
                import time
                time.sleep(delay)
            if require_bearer:
                auth = self.headers.get("Authorization", "")
                if not auth.startswith("Bearer ") or not auth[7:].strip():
                    self.send_response(401)
                    self.end_headers()
                    return
            body = handler_body(self.path)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            raw = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass                      # keep pytest output clean

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


def models_body(ids):
    """The ``/v1/models`` payload an OpenAI-compatible server returns."""
    def _body(path):
        if not path.endswith("/models"):
            return None
        return json.dumps({"data": [{"id": i} for i in ids]})
    return _body


def serve_models(ids, **kw):
    """Shorthand: a server that lists exactly ``ids``."""
    return serve(models_body(ids), **kw)


def serve_authenticated(ids, **kw):
    """A server that behaves like the paid vendor: 401 without a key."""
    return serve(models_body(ids), require_bearer=True, **kw)


def dead_url():
    """A URL on a port nothing is listening on — bound, read, released."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/v1"
