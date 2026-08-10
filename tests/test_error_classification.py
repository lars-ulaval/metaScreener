
# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_error_classification.py — F-94: the two salvage mechanisms must fire
for the servers that need them, not only for OpenAI's own error bodies.

Both remedies in ``run_m1_llm_for_criterion`` — halving the batch and
stepping the truncation down — were gated on substring sniffs over
``str(e).lower()``:

    is_rate = ("429" in msg) or ("too many requests" in msg) \\
              or ("rate" in msg and "limit" in msg)
    is_big  = ("too large" in msg) or ("context" in msg and "length" in msg) \\
              or ("max tokens" in msg)

``is_big`` requires ``context`` **and** ``length`` to co-occur, so
``"n_ctx exceeded"`` and ``"prompt exceeds the context window"`` — what
llama.cpp and Ollama actually say — match neither term-pair. **Small context
windows are the local case**, so the two mechanisms that exist precisely for
a small context window are unavailable in the configuration that most needs
them. That is the load-bearing half.

``APITimeoutError`` and ``APIConnectionError`` stringify to the fixed
sentences ``"Request timed out."`` and ``"Connection error."``, matching
neither predicate, so every transport failure is anonymous at the
application layer.

And the false positives are live, though the register overstates their
frequency: ``is_rate`` is a *conjunction*, so ``"rate"`` matching inside
``generate`` / ``moderate`` / ``separate`` is not enough on its own — the
word ``limit`` must also appear somewhere in the message. It routinely does:
``"moderate token limit exceeded"`` classifies as a rate limit today.

The contract these tests pin:
  - classification is by exception *type* first, ``status_code`` second, and
    the message only as an explicitly labelled last resort;
  - the oversize class covers what non-OpenAI servers actually say, and the
    halving and step-down genuinely fire for it;
  - the rate-limit class does not fire on prose containing ``generate`` and
    ``limit``;
  - transport and auth failures are named rather than anonymous.
"""
import json
import threading
import types

import httpx
import openai
import pytest

import plugins._common.llm_client as lc


CID = "EC-1"
_REQ = httpx.Request("POST", "http://localhost:11434/v1/chat/completions")


def _status_error(cls, code, message="boom"):
    return cls(message, response=httpx.Response(code, request=_REQ), body=None)


# ---------------------------------------------------------------------------
# The classifier itself
# ---------------------------------------------------------------------------

class TestClassificationByType:
    """First resort. An SDK that names the condition in the type system is
    the only signal that does not depend on prose."""

    @pytest.mark.parametrize("cls,code,expected", [
        (openai.RateLimitError, 429, "rate_limit"),
        (openai.BadRequestError, 400, "bad_request"),
        (openai.AuthenticationError, 401, "auth"),
        (openai.PermissionDeniedError, 403, "auth"),
        (openai.NotFoundError, 404, "not_found"),
    ])
    def test_status_exceptions(self, cls, code, expected):
        klass, how = lc._classify_llm_error(_status_error(cls, code))
        assert klass == expected
        assert how == "type"

    def test_a_timeout_is_transport_not_unknown(self):
        klass, how = lc._classify_llm_error(openai.APITimeoutError(request=_REQ))
        assert klass == "transport", (
            "F-94: APITimeoutError stringifies to 'Request timed out.', which "
            "matches neither substring predicate, so a timeout was "
            "indistinguishable from any other terminal failure."
        )
        assert how == "type"

    def test_a_connection_failure_is_transport(self):
        e = openai.APIConnectionError(message="Connection error.", request=_REQ)
        assert lc._classify_llm_error(e)[0] == "transport"

    def test_an_oversize_bad_request_is_oversize_not_merely_bad_request(self):
        """A 400 is only oversize when its body says so. The type alone
        cannot tell an oversize prompt from a malformed one, and treating
        every 400 as oversize would halve the batch forever on a request the
        server will never accept."""
        e = _status_error(openai.BadRequestError, 400,
                          "This model's maximum context length is 4096 tokens")
        assert lc._classify_llm_error(e)[0] == "oversize"


class TestClassificationByStatusCode:
    """Second resort: an OpenAI-compatible server behind a proxy can raise a
    generic ``APIStatusError`` rather than the specific subclass."""

    @pytest.mark.parametrize("code,expected", [
        (429, "rate_limit"), (401, "auth"), (403, "auth"), (404, "not_found"),
    ])
    def test_status_code_is_read_when_the_type_is_generic(self, code, expected):
        class _Odd(Exception):
            status_code = code
        klass, how = lc._classify_llm_error(_Odd("nothing useful here"))
        assert klass == expected
        assert how == "status"


class TestTheOversizeClassCoversWhatLocalServersSay:
    """The load-bearing half. Every string below is one a non-OpenAI server
    emits, and none of them matched the old ``context`` AND ``length``
    term-pair."""

    @pytest.mark.parametrize("msg", [
        "n_ctx exceeded",
        "prompt exceeds the context window",
        "the prompt is too long for this model",
        "input length exceeds the maximum context size",
        "requested 5000 tokens, but the maximum context length is 4096",
        "Request too large for gpt-4o-mini",
        "max tokens exceeded",
        "please reduce the length of the messages",
        "context window exceeded",
        "token limit exceeded for this model's context",
    ])
    def test_local_server_phrasings_classify_as_oversize(self, msg):
        klass, how = lc._classify_llm_error(RuntimeError(msg))
        assert klass == "oversize", (
            f"F-94: {msg!r} matched neither term-pair, so the batch-halving "
            f"and truncation step-down that exist precisely for a small "
            f"context window never fired. Small context windows are the "
            f"local case."
        )
        assert how == "message", "no type and no status: this is the last resort"


class TestTheRateLimitClassDoesNotFireOnProse:

    @pytest.mark.parametrize("msg", [
        "moderate token limit exceeded",
        "failed to generate: request limit reached",
        "separate rate policy limit",
        "the model will generate up to the limit",
    ])
    def test_generate_moderate_separate_are_not_rate_limits(self, msg):
        """Each of these classifies as a rate limit today: ``is_rate`` is a
        conjunction, so ``rate`` inside ``generate``/``moderate``/``separate``
        plus a stray ``limit`` anywhere in the message is enough."""
        assert lc._classify_llm_error(RuntimeError(msg))[0] != "rate_limit"

    @pytest.mark.parametrize("msg", [
        "Error code: 429",
        "Rate limit reached for gpt-4o-mini",
        "429 Too Many Requests",
        "rate-limit exceeded",
    ])
    def test_real_rate_limit_phrasings_still_classify(self, msg):
        assert lc._classify_llm_error(RuntimeError(msg))[0] == "rate_limit"


class TestUnknownIsAnHonestAnswer:

    @pytest.mark.parametrize("msg", [
        "Internal server error (500) from api.openai.com: upstream timeout",
        "something went wrong",
        "",
    ])
    def test_an_unrecognised_error_is_not_guessed_at(self, msg):
        assert lc._classify_llm_error(RuntimeError(msg))[0] == "unknown"

    def test_the_classifier_never_raises(self):
        """It runs inside an ``except`` block. A classifier that raises
        would replace the real error with its own."""
        class _Hostile(Exception):
            def __str__(self):
                raise ValueError("no")

            @property
            def status_code(self):
                raise ValueError("no")

        assert lc._classify_llm_error(_Hostile())[0] == "unknown"


# ---------------------------------------------------------------------------
# Behaviour — the remedies must actually fire
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        msg = type("M", (), {"content": json.dumps(payload)})
        self.choices = [type("C", (), {"message": msg})]


class _OversizeUntilSmallEnough:
    """Refuses any batch larger than ``limit`` with a local server's oversize
    wording, and answers anything at or below it. Records every batch size
    it was asked for."""

    def __init__(self, limit, message="n_ctx exceeded"):
        self.limit = limit
        self.message = message
        self.sizes = []
        outer = self

        class _Completions:
            def create(self, *, model, messages, temperature):
                items = json.loads(messages[1]["content"])["items"]
                outer.sizes.append(len(items))
                if len(items) > outer.limit:
                    raise RuntimeError(outer.message)
                return _FakeResponse([
                    {"a_id": it["a_id"], "decision": "meet", "confidence": 0.9,
                     "field": "title", "quote": it["title"], "span": [0, 1]}
                    for it in items
                ])

        self.chat = type("Chat", (), {"completions": _Completions()})()


class _AlwaysRaises:
    def __init__(self, exc):
        self.exc = exc
        self.calls = 0
        outer = self

        class _Completions:
            def create(self, *, model, messages, temperature):
                outer.calls += 1
                raise outer.exc

        self.chat = type("Chat", (), {"completions": _Completions()})()


def _build_messages(criterion, items, trunc_chars):
    return [
        {"role": "system", "content": "score the items"},
        {"role": "user", "content": json.dumps(
            {"criterion": criterion, "items": items}, ensure_ascii=False)},
    ]


@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setattr(lc, "_has_openai_key", lambda: True)
    # The back-off between salvage attempts is real code but is not what
    # these tests are about, and paying it would roughly double the whole
    # suite's wall-clock. Replace the module's own reference rather than
    # `time.sleep` itself, so nothing outside llm_client is affected.
    monkeypatch.setattr(lc, "time", types.SimpleNamespace(sleep=lambda *_a: None))
    return lc


def _run(monkeypatch, client, n_items=8, batch_size=8, trunc_chars=1500,
         log=None):
    monkeypatch.setattr(lc, "_openai_client_for", lambda: client)
    criterion = {"id": CID, "type": "exclude", "operator": "llm",
                 "target": "title", "what": ["x"], "how": "llm",
                 "label": "x", "threshold": 0.6}
    items = [{"a_id": f"A{i:03d}", "title": f"Title {i}", "abstract": "",
              "keywords": ""} for i in range(n_items)]
    return lc.run_m1_llm_for_criterion(
        criterion, items, stage="EL", build_messages=_build_messages,
        model="gemma3", trunc_chars=trunc_chars, batch_size=batch_size,
        log=log, cancel_token=threading.Event(),
    )


class TestHalvingFiresForALocalOversizeMessage:

    def test_the_batch_is_split_until_it_fits(self, llm, monkeypatch):
        client = _OversizeUntilSmallEnough(limit=2)
        out = _run(monkeypatch, client, n_items=8, batch_size=8)
        assert client.sizes[0] == 8
        assert min(client.sizes) <= 2, (
            f"F-94: sizes tried were {client.sizes}. 'n_ctx exceeded' matched "
            f"neither term-pair, so the batch was never halved and the whole "
            f"batch was written off as uncertain on the first refusal."
        )
        assert all(v["decision"] == "meet" for v in out.values()), (
            "every record must end up with the answer the server was willing "
            "to give at a smaller batch size"
        )
        assert not any("error" in v for v in out.values())

    @pytest.mark.parametrize("message", [
        "n_ctx exceeded",
        "prompt exceeds the context window",
        "requested 9000 tokens, but the maximum context length is 4096",
    ])
    def test_it_holds_for_each_local_phrasing(self, llm, monkeypatch, message):
        client = _OversizeUntilSmallEnough(limit=2, message=message)
        _run(monkeypatch, client, n_items=8, batch_size=8)
        assert min(client.sizes) <= 2


class TestTruncationStepDownFiresForALocalOversizeMessage:

    def test_a_single_record_batch_steps_the_truncation_down(self, llm,
                                                             monkeypatch):
        """With one record there is nothing left to halve, so the other
        remedy must take over. It never could, for the same reason."""
        seen = []

        class _NeedsSmallerTrunc:
            def __init__(self):
                outer = self

                class _Completions:
                    def create(self, *, model, messages, temperature):
                        body = json.loads(messages[1]["content"])
                        n = len(body["items"][0]["title"])
                        seen.append(n)
                        if n > 700:
                            raise RuntimeError("n_ctx exceeded")
                        return _FakeResponse([
                            {"a_id": body["items"][0]["a_id"],
                             "decision": "meet", "confidence": 0.9,
                             "field": "title",
                             "quote": body["items"][0]["title"][:10],
                             "span": [0, 1]}
                        ])

                self.chat = type("Chat", (), {"completions": _Completions()})()

        def _trunc_messages(criterion, items, trunc_chars):
            cut = [{**it, "title": it["title"][:trunc_chars]} for it in items]
            return _build_messages(criterion, cut, trunc_chars)

        monkeypatch.setattr(lc, "_openai_client_for", lambda: _NeedsSmallerTrunc())
        out = lc.run_m1_llm_for_criterion(
            {"id": CID, "type": "exclude", "operator": "llm", "target": "title",
             "what": ["x"], "how": "llm", "label": "x", "threshold": 0.6},
            [{"a_id": "A000", "title": "T" * 4000, "abstract": "",
              "keywords": ""}],
            stage="EL", build_messages=_trunc_messages, model="gemma3",
            trunc_chars=1200, batch_size=1,
        )
        assert len(seen) > 1, (
            f"F-94: only one attempt was made ({seen}); the truncation "
            f"step-down never fired."
        )
        assert seen[-1] <= 700
        assert out[("A000", CID)]["decision"] == "meet"


class TestTerminalFailuresAreNamedRatherThanAnonymous:

    def test_the_class_is_recorded_on_the_record(self, llm, monkeypatch):
        client = _AlwaysRaises(openai.APIConnectionError(
            message="Connection error.", request=_REQ))
        out = _run(monkeypatch, client, n_items=2, batch_size=2)
        ev = out[("A000", CID)]
        assert ev["error_class"] == "transport", (
            "a down server, a rejected key and a malformed request all "
            "produced the same anonymous terminal record"
        )
        assert "error" in ev

    def test_a_rejected_key_is_named(self, llm, monkeypatch):
        client = _AlwaysRaises(_status_error(openai.AuthenticationError, 401))
        out = _run(monkeypatch, client, n_items=2, batch_size=2)
        assert out[("A000", CID)]["error_class"] == "auth"

    def test_a_model_that_does_not_exist_is_named(self, llm, monkeypatch):
        """The 404 an Ollama server returns for a model that was never
        pulled — one of the three states F-111 says matter most."""
        client = _AlwaysRaises(_status_error(openai.NotFoundError, 404))
        out = _run(monkeypatch, client, n_items=2, batch_size=2)
        assert out[("A000", CID)]["error_class"] == "not_found"

    def test_the_class_appears_in_the_log(self, llm, monkeypatch):
        lines = []
        client = _AlwaysRaises(_status_error(openai.AuthenticationError, 401))
        _run(monkeypatch, client, n_items=2, batch_size=2, log=lines.append)
        assert "auth" in "".join(lines)

    def test_a_transport_failure_does_not_retry_at_this_layer(self, llm,
                                                             monkeypatch):
        """Deliberate, and a departure from a literal reading of F-94's
        'terminal on first sight'. The SDK defaults to ``max_retries=2``, so
        a transport error reaching this layer has already been attempted
        three times; retrying again here would make it six. The retry ladder
        is F-25's, and F-25 is explicit that the two must be chosen together.
        What changes here is that the failure is named, not that it is
        retried."""
        client = _AlwaysRaises(openai.APITimeoutError(request=_REQ))
        _run(monkeypatch, client, n_items=4, batch_size=2)
        assert client.calls == 2, "one attempt per batch, two batches"


class TestUnknownErrorsStillReachTheTerminalArm:
    """The regression net for the rewrite. Nothing may start escaping the
    generic handler: ``tests/test_negative_caching.py`` raises a bare
    ``RuntimeError`` and ``tests/test_cross_batch_substitution.py`` raises a
    bare ``AssertionError``, and both rely on being written off rather than
    propagated."""

    def test_a_plain_runtime_error_is_still_written_off(self, llm, monkeypatch):
        client = _AlwaysRaises(RuntimeError("Internal server error (500)"))
        out = _run(monkeypatch, client, n_items=2, batch_size=2)
        assert out[("A000", CID)]["error_class"] == "unknown"
        assert out[("A000", CID)]["used"] is False

    def test_an_assertion_error_does_not_escape(self, llm, monkeypatch):
        client = _AlwaysRaises(AssertionError("unscripted call"))
        out = _run(monkeypatch, client, n_items=2, batch_size=2)
        assert len(out) == 2
