# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2026 Alejandro Reyes-Consuelo
# SPDX-License-Identifier: MIT

"""
test_run_estimate.py — wave 12, F-151: a long, sometimes billable run
started with no record count, no request count, no estimate and no
confirmation.

The gap was already named in the repository before it was fixed.
``provider_dialog.py::_offer_pull``'s docstring says the ceremony around
a model download is deliberate *because* ``_run_clicked`` starts a
billable operation with less, and ``tests/test_model_pull.py``'s module
docstring says the same. The pattern to copy was in the tree; only this
side of it was missing.

The line this file defends
--------------------------
**Counts are certain and are stated. Duration is not, and is only ever
reported from a rate actually observed.** A plausible-looking
seconds-per-request constant would have been easy and is exactly how
F-125 came to describe a cost wrong by two to three orders of magnitude.
Silence about time is worse than a measurement and better than a guess.
"""
import pytest

from plugins._common import run_estimate as re_


@pytest.fixture(autouse=True)
def _clean():
    re_.forget_rates()
    yield
    re_.forget_rates()


class TestTheArithmeticIsExact:

    @pytest.mark.parametrize("records,criteria,batch,requests", [
        (85, 2, 5, 34),          # 17 batches per criterion, twice
        (85, 2, 50, 4),          # 2 batches per criterion, twice
        (100, 1, 10, 10),
        (1, 1, 50, 1),           # a partial batch is still a request
        (0, 3, 5, 0),
        (10, 0, 5, 0),
    ])
    def test_requests_are_per_criterion_ceilings(self, records, criteria,
                                                 batch, requests):
        plan = re_.RunPlan(records=records, criteria=criteria,
                           batch_size=batch)
        assert plan.requests == requests

    def test_a_batch_size_of_zero_does_not_divide_by_zero(self):
        assert re_.RunPlan(records=10, criteria=1, batch_size=0).requests == 10

    def test_pairs_are_what_the_model_is_asked(self):
        assert re_.RunPlan(records=85, criteria=2, batch_size=5).pairs == 170


class TestTheRateIsObservedOrAbsent:

    def test_nothing_measured_means_no_rate(self):
        assert re_.observed_rate("http://x/v1", "m") is None

    def test_a_rate_is_the_mean_not_the_last_call(self):
        """One slow call -- a cold load, a retry after a rate limit --
        should move the estimate, not become it."""
        for s in (1.0, 1.0, 10.0):
            re_.remember_call("http://x/v1", "m", s)
        assert re_.observed_rate("http://x/v1", "m") == pytest.approx(4.0)

    def test_rates_are_kept_per_endpoint_and_model(self):
        re_.remember_call("http://a/v1", "m1", 2.0)
        re_.remember_call("http://b/v1", "m1", 8.0)
        re_.remember_call("http://a/v1", "m2", 4.0)
        assert re_.observed_rate("http://a/v1", "m1") == pytest.approx(2.0)
        assert re_.observed_rate("http://b/v1", "m1") == pytest.approx(8.0)
        assert re_.observed_rate("http://a/v1", "m2") == pytest.approx(4.0)

    def test_the_endpoint_key_ignores_a_trailing_slash_and_case(self):
        re_.remember_call("http://Localhost:11434/v1/", "m", 3.0)
        assert re_.observed_rate("http://localhost:11434/v1", "m") \
            == pytest.approx(3.0)

    @pytest.mark.parametrize("bad", [None, "nope", float("nan"), -1.0])
    def test_a_bad_measurement_cannot_break_a_run(self, bad):
        """Called from the engine's innermost call site, so it must not
        be able to fail a run over a reporting nicety."""
        re_.remember_call("http://x/v1", "m", bad)
        rate = re_.observed_rate("http://x/v1", "m")
        assert rate is None or rate == rate      # never raises; no NaN out


class TestTheWording:

    def _plan(self):
        return re_.RunPlan(records=85, criteria=2, batch_size=5)

    def test_the_counts_are_all_present(self):
        text = re_.confirm_text(self._plan(), stage="EL", model="llama3.2")
        for fragment in ("85", "170", "34", "llama3.2", "EL"):
            assert fragment in text, (fragment, text)

    def test_no_duration_is_claimed_without_a_measurement(self):
        text = re_.confirm_text(self._plan(), stage="EL", model="m")
        assert "no basis for a time estimate" in text
        for word in ("minutes", "hours"):
            assert word not in text, (word, text)

    def test_a_measured_rate_produces_a_duration(self):
        text = re_.confirm_text(self._plan(), stage="EL", model="m", rate=30.0)
        # 34 requests x 30s = 17 minutes
        assert "17 minutes" in text, text

    def test_the_compute_sentence_is_carried_verbatim(self):
        """The wording belongs to provider_detect, which observed it."""
        sentence = "This server is running the model on the CPU — no GPU."
        text = re_.confirm_text(self._plan(), stage="EL", model="m",
                                compute_detail=sentence)
        assert sentence in text

    def test_flag_only_is_stated_because_it_changes_the_meaning(self):
        text = re_.confirm_text(self._plan(), stage="EL", model="m",
                                flag_only=True)
        assert "will not exclude" in text

    def test_it_asks_rather_than_announces(self):
        text = re_.confirm_text(self._plan(), stage="EL", model="m")
        assert text.rstrip().endswith("?")

    def test_it_promises_nothing_it_cannot_keep(self):
        """The false-reassurance rule ``batch_size_tooltip`` is held to.

        An estimate that called itself accurate, or a run that was
        described as safe, would be the kind of claim this project
        removes rather than adds.
        """
        for rate in (None, 12.0):
            text = re_.confirm_text(self._plan(), stage="EL", model="m",
                                    rate=rate).lower()
            for word in ("accurate", "guarantee", "exactly", "safe",
                         "precise"):
                assert word not in text, (word, rate)


class TestHumanDuration:

    @pytest.mark.parametrize("seconds,expected", [
        (5, "5 seconds"),
        (89, "89 seconds"),
        (600, "about 10 minutes"),
        (5400, "about 1.5 hours"),
        (36000, "about 10 hours"),
        (0, "0 seconds"),
        (-5, "0 seconds"),
    ])
    def test_it_reads_without_conversion(self, seconds, expected):
        assert re_.human_duration(seconds) == expected
