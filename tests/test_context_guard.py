# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_context_guard.py — wave 15b: no run starts that the window cannot hold.

The measured facts this guard encodes (FIX_WAVE_15B_CONTEXT_GUARD.md, twelve
declared probe calls): the serving window is 4,096 tokens; overflow does not
trim the excess — Ollama keeps the LAST ~2,048 tokens and drops the front,
system message and criterion included, then answers confidently about the
remainder; no per-request ``num_ctx`` vehicle works on ``/v1``. There is
nothing to warn about, only something to prevent — hence a guard that
REFUSES, pre-run, whole-corpus, before the first call is spent.

The estimator is deliberately conservative in the refusing direction:
divisor 4.5 chars/token (measured 4.48–5.23 — near-exact on small payloads,
~10 % conservative on large), +30 framing, +80 × batch reply reserve. The
one hole a constant cannot close — a tokenizer denser than the estimate on
some untested provider — is closed by the drift check: the first real call's
``usage.prompt_tokens`` is compared against its own estimate, and a run
whose reality exceeds the estimate aborts with one call spent. ``usage`` was
previously unread anywhere (F-122's family); the drift check is its first
consumer.
"""
import inspect
import json
import threading

import pytest

from conftest import get_el, get_il

from plugins._common import llm_client as lc

CID = "EC-1"


# ---------------------------------------------------------------------------
# fakes — the house pattern
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload, prompt_tokens=None):
        msg = type("M", (), {"content": json.dumps(payload)})
        self.choices = [type("C", (), {"message": msg})]
        if prompt_tokens is not None:
            self.usage = type("U", (), {"prompt_tokens": prompt_tokens})


class _Recorder:
    """Counts calls; answers everything; optionally reports prompt_tokens."""

    def __init__(self, prompt_tokens=None):
        self.calls = 0
        outer = self

        class _Completions:
            def create(self, *, model, messages, temperature,
                       response_format=None):
                outer.calls += 1
                items = json.loads(messages[1]["content"])["items"]
                return _FakeResponse([
                    {"a_id": it["a_id"], "decision": "not_meet",
                     "confidence": 0.9, "field": "title",
                     "quote": it["title"], "span": [0, 1]}
                    for it in items
                ], prompt_tokens=outer.prompt_tokens_for(messages))

        self.chat = type("Chat", (), {"completions": _Completions()})()
        self._pt = prompt_tokens

    def prompt_tokens_for(self, messages):
        return self._pt


def _build_messages(criterion, items, trunc_chars):
    """Mirrors the real builder's truncation: each field is cut to
    ``trunc_chars`` before rendering. The guard budgets whatever the builder
    it is handed renders — so the double must truncate as the real one does,
    or the trunc-honouring test would be asserting against a builder no
    engine uses."""
    def _t(s):
        s = s or ""
        return s[:trunc_chars] if trunc_chars and len(s) > trunc_chars else s
    packed = [{"a_id": it["a_id"], "title": _t(it["title"]),
               "abstract": _t(it["abstract"]), "keywords": _t(it["keywords"])}
              for it in items]
    return [
        {"role": "system", "content": "score the items"},
        {"role": "user", "content": json.dumps(
            {"criterion": criterion, "items": packed}, ensure_ascii=False)},
    ]


def _crit_pack():
    return {"id": CID, "type": "exclude", "operator": "llm", "target": "title",
            "what": ["x"], "how": "llm", "label": "x", "threshold": 0.6}


def _items(n, chars=40):
    return [{"a_id": f"A{i:03d}", "title": "T" * chars, "abstract": "",
             "keywords": ""} for i in range(n)]


# ---------------------------------------------------------------------------
# 1. the estimator
# ---------------------------------------------------------------------------

class TestTheEstimator:

    def test_the_formula_is_ceil_chars_over_divisor_plus_framing(self):
        """Written against the divisor rather than against 4.5, so a future
        recalibration changes one constant and not this test (wave 17d)."""
        d = lc.CHARS_PER_TOKEN
        assert lc.estimate_prompt_tokens(int(d * 1000)) == 1000 + lc.FRAMING_TOKENS
        assert lc.estimate_prompt_tokens(int(d * 1000) + 1) == 1001 + lc.FRAMING_TOKENS
        assert lc.estimate_prompt_tokens(0) == lc.FRAMING_TOKENS

    def test_the_constants_are_the_adjudicated_ones(self):
        """RE-ADJUDICATED at wave 17d, 4.5 -> 3.3 (F-236).

        4.5 was measured on wave 15b's VR corpus and applied to the RSA corpus
        with nothing asking whether the new text tokenises the same way. It does
        not: `h2_polarity` aborted on its first live call at 3.62 chars/token,
        885 actual against 741 estimated, and eight of nine arms could not run.

        3.3 is a FLOOR fitted over 30 observations across two corpora — wave 15b
        VR 4.48-5.23 (n=8), wave 17d RSA h0 4.52-4.74 (n=21), wave 17d RSA h2
        3.61 (n=1) — and not a mean, because a mean is what failed. It is also
        the lowest value that causes no FALSE refusal on wave 17's prompts: the
        largest is 11,551 chars, estimating 3,531 tokens, and 3,531 + the
        400-token reserve is 3,931 inside a 4,096 window.

        The check this feeds is unchanged and still strict: actual > estimate
        still raises TokenEstimateDrift."""
        assert lc.CHARS_PER_TOKEN == 3.3
        assert lc.REPLY_RESERVE_PER_VERDICT == 80
        assert lc.CONTEXT_WINDOW_DEFAULT == 4096

    def test_the_estimate_is_conservative_against_the_rsa_observations(self):
        """The wave-17d live samples, the other corpus. Same property as the
        wave-15b probe test below: a refusing guard must never estimate BELOW
        reality on a payload it has actually seen."""
        RSA = [(9004, 1902), (9621, 2085), (6570, 1455), (8163, 1771),
               (4036, 867), (9954, 2137), (6674, 1475), (3199, 885)]
        for chars, measured in RSA:
            assert lc.estimate_prompt_tokens(chars) >= measured, (chars, measured)

    def test_the_estimate_is_conservative_against_every_probe_point(self):
        """The eight measured (chars, prompt_tokens) points from the wave-15b
        probes. A refusing guard must never estimate BELOW reality on the
        payloads it was calibrated on."""
        PROBE = [(8146, 1621), (12627, 2518), (14307, 2930), (15288, 2942),
                 (16754, 3204), (17515, 3537), (10033, 2240), (2699, 600)]
        for chars, measured in PROBE:
            assert lc.estimate_prompt_tokens(chars) >= measured, (chars, measured)


# ---------------------------------------------------------------------------
# 2. the budget check
# ---------------------------------------------------------------------------

class TestTheBudgetCheck:

    def _report(self, *, n_items=10, batch=10, chars=40, window=4096):
        return lc.check_context_budget(
            criteria=[_crit_pack()], items=_items(n_items, chars),
            batch_size=batch, trunc_chars=1500,
            build_messages=_build_messages, window=window)

    def test_a_small_corpus_fits(self):
        rep = self._report()
        assert rep.ok is True

    def test_an_oversized_batch_refuses(self):
        rep = self._report(n_items=10, batch=10, chars=3000)
        assert rep.ok is False

    def test_the_boundary_is_exclusive(self):
        """Refusal is estimate + reserve > window; landing exactly ON the
        window passes. Pin by construction: find a chars value whose worst
        estimate+reserve equals the window, then one char more refuses."""
        rep = self._report(chars=1500, window=10 ** 9)
        worst = rep.worst_estimate + rep.reserve
        assert self._report(chars=1500, window=worst).ok is True
        assert self._report(chars=1500, window=worst - 1).ok is False

    def test_the_refusal_names_what_f173_requires(self):
        """The message names the offending criterion and batch, the measured
        number against the window, and the derived maximum safe batch size
        for THIS corpus at THIS window — and tells no conclusion."""
        rep = self._report(n_items=10, batch=10, chars=3000)
        msg = rep.message
        assert CID in msg
        assert str(rep.worst_estimate + rep.reserve) in msg
        assert "4096" in msg
        assert str(rep.max_safe_batch) in msg
        assert "recommend" not in msg.lower()
        # The measured loss: the server keeps the last ~half-WINDOW of
        # tokens, not half the request — the message must state the real
        # quantity (2048 here), because "half of it" understates the loss
        # for any request well over the window.
        assert "2048" in msg
        assert "half of it" not in msg

    def test_the_derived_max_batch_actually_fits(self):
        rep = self._report(n_items=10, batch=10, chars=3000)
        assert rep.ok is False and rep.max_safe_batch >= 1
        again = self._report(n_items=10, batch=rep.max_safe_batch, chars=3000)
        assert again.ok is True, (
            "the number the refusal hands the user must itself pass"
        )

    def test_every_criterion_and_every_batch_is_rendered(self):
        """Whole-corpus, pre-run: the worst call may be the LAST batch, and
        it must be found there. The tail record carries all three fields at
        the truncation cap, so its one-record batch out-costs the full
        ten-record batch even after the ten-record batch's larger reply
        reserve; the window sits between the two costs so only the tail
        refuses — proving the sweep reached it."""
        items = _items(11, chars=40)
        items[-1]["title"] = "T" * 1500
        items[-1]["abstract"] = "A" * 1500
        items[-1]["keywords"] = "K" * 1500
        rep_all = lc.check_context_budget(
            criteria=[_crit_pack()], items=items, batch_size=10,
            trunc_chars=1500, build_messages=_build_messages, window=10 ** 9)
        tail_cost = rep_all.worst_estimate + rep_all.reserve
        assert rep_all.worst_batch_index == 1, "the tail must be the worst"
        rep = lc.check_context_budget(
            criteria=[_crit_pack()], items=items, batch_size=10,
            trunc_chars=1500, build_messages=_build_messages,
            window=tail_cost - 1)
        assert rep.ok is False
        assert rep.worst_batch_index == 1, "the tail batch, not the first"

    def test_the_second_criterion_is_budgeted_too(self):
        """Found by the mutation battery: `criteria[:1]` survived. The worst
        call must be findable in the SECOND criterion — here the second
        pack's `what` list is enormous while the first is tiny, so only a
        sweep that renders both refuses."""
        big = dict(_crit_pack(), id="EC-9",
                   what=["w" * 200] * 100, label="x" * 5000)
        rep = lc.check_context_budget(
            criteria=[_crit_pack(), big], items=_items(4), batch_size=4,
            trunc_chars=1500, build_messages=_build_messages, window=4096)
        assert rep.ok is False
        assert rep.worst_criterion == "EC-9", (
            "the offender is the second criterion; a guard that budgets "
            "only the first admits this run"
        )

    def test_the_derived_max_is_tight_not_just_safe(self):
        """Found by the mutation battery: returning batch_size-1 without
        re-verifying survived, because the first fixture's honest answer
        happened to BE batch_size-1. Here the honest answer is far lower:
        each record fills the truncation cap on all three fields, so only
        tiny batches fit — and the derived number must both pass and be the
        LARGEST that passes."""
        items = [{"a_id": f"A{i:03d}", "title": "T" * 1500,
                  "abstract": "A" * 1500, "keywords": "K" * 1500}
                 for i in range(10)]
        rep = lc.check_context_budget(
            criteria=[_crit_pack()], items=items, batch_size=10,
            trunc_chars=1500, build_messages=_build_messages, window=4096)
        assert rep.ok is False
        assert 1 <= rep.max_safe_batch < 9, (
            "batch_size-1 must not fit here, or the test proves nothing"
        )
        fits = lc.check_context_budget(
            criteria=[_crit_pack()], items=items,
            batch_size=rep.max_safe_batch, trunc_chars=1500,
            build_messages=_build_messages, window=4096)
        assert fits.ok is True
        too_big = lc.check_context_budget(
            criteria=[_crit_pack()], items=items,
            batch_size=rep.max_safe_batch + 1, trunc_chars=1500,
            build_messages=_build_messages, window=4096)
        assert too_big.ok is False, "tight means the next size up refuses"

    def test_trunc_chars_is_honoured(self):
        """The builder truncates each field to trunc_chars; the guard must
        budget what will be SENT, not the raw corpus."""
        items = _items(1, chars=500000)
        rep = lc.check_context_budget(
            criteria=[_crit_pack()], items=items, batch_size=1,
            trunc_chars=1500, build_messages=_build_messages, window=4096)
        assert rep.ok is True, "500k raw chars truncate to 1500 sent"

    def test_enforce_raises_the_dedicated_exception(self):
        with pytest.raises(lc.ContextBudgetExceeded) as e:
            lc.enforce_context_budget(
                criteria=[_crit_pack()], items=_items(10, 3000),
                batch_size=10, trunc_chars=1500,
                build_messages=_build_messages, window=4096)
        assert CID in str(e.value)


# ---------------------------------------------------------------------------
# 3. the engines refuse before the first call — both stages, one guard
# ---------------------------------------------------------------------------

class TestTheEnginesRefuse:

    def _drive(self, monkeypatch, get_mod, stage, *, rows, chars, batch,
               window=4096, client=None):
        mod = get_mod()
        engine = inspect.getmodule(mod.run_el_screen if stage == "EL"
                                   else mod.run_il_screen)
        client = client or _Recorder()
        monkeypatch.setattr(lc, "_has_openai_key", lambda *_a, **_k: True)
        monkeypatch.setattr(lc, "_openai_client_for", lambda *_a, **_k: client)
        monkeypatch.setattr(lc, "resolve_context_window",
                            lambda *_a, **_k: window)
        crit = mod.Criterion(
            id=CID, stage=stage, ctype="exclude", enabled=True, operator="llm",
            targets=["title"], what_raw="x", what_list=["x"], threshold=0.6,
            source_text="x", label="x")
        parse = mod.ParseReport(
            header=["local_id", "title", "abstract", "keywords"],
            rows=[{"local_id": f"A{i:03d}", "title": "T" * chars,
                   "abstract": "", "keywords": ""} for i in range(rows)],
            skipped=[])
        report = mod.CriteriaLoadReport(criteria=[crit], warnings=[])
        run = mod.run_el_screen if stage == "EL" else mod.run_il_screen
        return client, lambda: run(
            parse, report, model="gemma3", trunc_chars=1500, batch_size=batch,
            use_cache=False, cache_in={}, cancel_event=threading.Event())

    @pytest.mark.parametrize("get_mod,stage", [(get_el, "EL"), (get_il, "IL")])
    def test_an_oversized_run_never_reaches_the_client(self, monkeypatch,
                                                       get_mod, stage):
        client, run = self._drive(monkeypatch, get_mod, stage,
                                  rows=20, chars=1500, batch=20)
        with pytest.raises(lc.ContextBudgetExceeded):
            run()
        assert client.calls == 0, (
            "pre-run means before the FIRST call — the user learns at zero "
            "cost, not 40 calls in"
        )

    @pytest.mark.parametrize("get_mod,stage", [(get_el, "EL"), (get_il, "IL")])
    def test_a_fitting_run_proceeds_untouched(self, monkeypatch, get_mod, stage):
        client, run = self._drive(monkeypatch, get_mod, stage,
                                  rows=4, chars=40, batch=4)
        run()
        assert client.calls == 1


# ---------------------------------------------------------------------------
# 4. the drift check — usage's first consumer
# ---------------------------------------------------------------------------

class TestTheDriftCheck:

    def _run_m1(self, monkeypatch, client, *, stats=None, n=4, batch=2):
        monkeypatch.setattr(lc, "_has_openai_key", lambda *_a, **_k: True)
        monkeypatch.setattr(lc, "_openai_client_for", lambda *_a, **_k: client)
        return lc.run_m1_llm_for_criterion(
            _crit_pack(), _items(n), stage="EL",
            build_messages=_build_messages, model="gemma3",
            trunc_chars=1500, batch_size=batch, stats=stats,
            cancel_token=threading.Event())

    def test_reality_exceeding_the_estimate_aborts_after_one_call(
            self, monkeypatch):
        client = _Recorder(prompt_tokens=10 ** 6)
        with pytest.raises(lc.TokenEstimateDrift):
            self._run_m1(monkeypatch, client)
        assert client.calls == 1, "abort means abort — one call spent"

    def test_reality_below_the_estimate_proceeds(self, monkeypatch):
        client = _Recorder(prompt_tokens=5)
        out = self._run_m1(monkeypatch, client)
        assert client.calls == 2
        assert all(ev["used"] for ev in out.values())

    def test_a_response_without_usage_skips_the_check(self, monkeypatch):
        """All thirteen legacy doubles carry no usage block; a provider that
        reports none is a real condition, not an error (F-107)."""
        client = _Recorder(prompt_tokens=None)
        out = self._run_m1(monkeypatch, client)
        assert client.calls == 2 and len(out) == 4

    def test_the_check_runs_once_per_run_not_per_criterion(self, monkeypatch):
        """The stats dict is the run-scoped object; a second criterion in the
        same run must not re-check (and so must not re-spend the comparison
        against a call that could legitimately be smaller)."""
        stats = lc.new_llm_call_stats()
        client = _Recorder(prompt_tokens=5)
        self._run_m1(monkeypatch, client, stats=stats)
        assert stats["drift_checked"] is True
        # second criterion, same stats: a huge prompt_tokens now must NOT abort
        client2 = _Recorder(prompt_tokens=10 ** 6)
        out = self._run_m1(monkeypatch, client2, stats=stats)
        assert client2.calls == 2 and len(out) == 4


# ---------------------------------------------------------------------------
# 5. the window setting
# ---------------------------------------------------------------------------

class TestTheWindowSetting:

    def test_default_is_4096(self, monkeypatch):
        monkeypatch.setattr(lc, "_load_settings_or_empty", lambda: {})
        assert lc.resolve_context_window() == 4096

    def test_a_stored_value_wins(self, monkeypatch):
        monkeypatch.setattr(lc, "_load_settings_or_empty",
                            lambda: {"context_window": 8192})
        assert lc.resolve_context_window() == 8192

    def test_the_floor_rejects_typos(self, monkeypatch):
        """A window of 3 is a typo, not a policy; below 512 is treated as
        absent rather than obeyed into refusing every possible run."""
        monkeypatch.setattr(lc, "_load_settings_or_empty",
                            lambda: {"context_window": 3})
        assert lc.resolve_context_window() == 4096

    def test_a_bool_is_not_an_int_here(self, monkeypatch):
        monkeypatch.setattr(lc, "_load_settings_or_empty",
                            lambda: {"context_window": True})
        assert lc.resolve_context_window() == 4096

    def test_unreadable_settings_degrade_to_the_default(self, monkeypatch):
        def _boom():
            raise RuntimeError("no settings")
        monkeypatch.setattr(lc, "_load_settings_or_empty", _boom)
        assert lc.resolve_context_window() == 4096


# ---------------------------------------------------------------------------
# 6. the per-provider default (F-203, wave 15c)
# ---------------------------------------------------------------------------

class TestThePerProviderDefault:
    """The default is keyed on the RESOLVED PAIR via `is_paid_vendor`,
    never the provider label — the drift check aborts only when reality
    exceeds the estimate, so a hosted-sized window aimed at a truncating
    local server would be caught by nothing at run time. The label-only
    error is exactly that mistake."""

    @staticmethod
    def _resolve(monkeypatch, stored, provider, endpoint):
        from types import SimpleNamespace
        monkeypatch.setattr(lc, "_load_settings_or_empty", lambda: stored)
        monkeypatch.setattr(
            lc, "_stage_config",
            lambda _s: SimpleNamespace(provider=provider, endpoint=endpoint))
        return lc.resolve_context_window("EL")

    VENDOR = "https://api.openai.com/v1"
    LOCAL = "http://localhost:11434/v1"

    def test_a_hosted_pair_gets_the_hosted_default(self, monkeypatch):
        assert self._resolve(monkeypatch, {}, "openai", self.VENDOR) \
            == lc.HOSTED_CONTEXT_WINDOW_DEFAULT

    def test_a_local_provider_keeps_the_measured_default(self, monkeypatch):
        assert self._resolve(monkeypatch, {}, "local", self.LOCAL) == 4096

    def test_the_pair_decides_custom_at_the_vendor_is_hosted(self, monkeypatch):
        assert self._resolve(monkeypatch, {}, "custom", self.VENDOR) \
            == lc.HOSTED_CONTEXT_WINDOW_DEFAULT

    def test_the_pair_decides_openai_label_at_a_local_endpoint_is_not(
            self, monkeypatch):
        """The harm direction: a 128k default against a truncating local
        server is silent front-truncation nothing can catch."""
        assert self._resolve(monkeypatch, {}, "openai", self.LOCAL) == 4096

    def test_an_unconfigured_install_stays_at_4096(self, monkeypatch):
        """Provider UNCHOSEN resolves the vendor endpoint as a fallback;
        nothing-configured must not be handed a hosted window by it."""
        assert self._resolve(monkeypatch, {}, "", self.VENDOR) == 4096

    def test_a_stored_value_beats_the_hosted_default_too(self, monkeypatch):
        assert self._resolve(monkeypatch, {"context_window": 8192},
                             "openai", self.VENDOR) == 8192

    def test_deepseek_stays_conservatively_local(self, monkeypatch):
        """PAID_VENDOR_HOSTS does not name api.deepseek.com, and widening
        a MONEY vocabulary to fix a WINDOW default is refused — the
        conservative direction is a loud refusal naming the setting."""
        assert self._resolve(monkeypatch, {}, "custom",
                             "https://api.deepseek.com/v1") == 4096

    def test_a_failing_stage_config_degrades_to_4096(self, monkeypatch):
        def _boom(_s):
            raise RuntimeError("no store")
        monkeypatch.setattr(lc, "_load_settings_or_empty", lambda: {})
        monkeypatch.setattr(lc, "_stage_config", _boom)
        assert lc.resolve_context_window("EL") == 4096

    def test_the_constant_and_the_unrefused_flow(self):
        """128,000 per OpenAI's documented gpt-4o-family window (cited at
        the constant). The shipped hosted flow F-203 records as refused —
        batch 50, worst measured prompt 16,473 tokens optimistic, 4,000
        reply reserve — fits it with an order of magnitude to spare."""
        assert lc.HOSTED_CONTEXT_WINDOW_DEFAULT == 128_000
        assert 16_473 + 50 * lc.REPLY_RESERVE_PER_VERDICT \
            < lc.HOSTED_CONTEXT_WINDOW_DEFAULT
        assert lc.CONTEXT_WINDOW_DEFAULT == 4096, "the local default is unmoved"

    def test_llm_provenance_requires_the_window_now(self):
        """The keyword default was the number's second copy: a future
        caller omitting it would stamp 4096 whatever the provider-aware
        default resolved. Required now; both engines pass it explicitly."""
        with pytest.raises(TypeError):
            lc.llm_provenance(model="m", endpoint="e", temperature=0.0,
                              prompt_version="v", trunc_chars=1500,
                              batch_size=5)


class TestTheHostedRefusalMessage:
    """The local message's mechanism paragraph is Ollama-measured; a
    hosted endpoint's overflow behaviour is not established here, so the
    hosted branch states the constraint and the setting remedy without
    asserting an unmeasured mechanism."""

    def _report(self, hosted):
        items = _items(10, chars=3000)
        return lc.check_context_budget(
            criteria=[_crit_pack()], items=items, batch_size=10,
            trunc_chars=1500, build_messages=_build_messages, window=4096,
            hosted=hosted)

    def test_the_hosted_branch_drops_the_truncation_mechanism(self):
        msg = self._report(hosted=True).message
        assert "keeps roughly the last" not in msg
        assert "2048" not in msg
        assert "no server of yours to restart" in msg
        assert "context_window" in msg
        assert "recommend" not in msg.lower()

    def test_the_hosted_branch_keeps_the_numbers_and_the_max_safe(self):
        rep = self._report(hosted=True)
        assert str(rep.worst_estimate + rep.reserve) in rep.message
        assert "4096" in rep.message
        assert str(rep.max_safe_batch) in rep.message

    def test_the_local_branch_is_unchanged(self):
        msg = self._report(hosted=False).message
        assert "keeps roughly the last 2048 tokens" in msg
        assert "no server of yours to restart" not in msg
