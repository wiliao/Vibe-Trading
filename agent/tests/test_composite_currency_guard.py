"""Regression tests for the composite engine's single-currency requirement.

``CompositeEngine`` keeps one shared capital pool: a single cash scalar and one
equity curve. A code set spanning USD and CAD would be summed into that curve
as if the units matched, and every metric derived from it would be reported
without a warning. There is no FX translation layer, so the engine refuses the
run instead.
"""

from __future__ import annotations

import pytest

from backtest.engines._market_hooks import code_currency
from backtest.engines.composite import CompositeEngine, _reject_mixed_currency


class TestCodeCurrency:
    """Every supported market maps to the currency it settles in."""

    @pytest.mark.parametrize(
        ("code", "currency"),
        [
            ("AAPL.US", "USD"),
            ("AAPL", "USD"),
            ("TD.TO", "CAD"),
            ("PNG.V", "CAD"),
        ],
    )
    def test_settlement_currencies(self, code, currency):
        assert code_currency(code) == currency

    def test_index_is_usd_comparable(self):
        # Index levels are USD-denominated benchmark inputs so a US + index
        # basket is one currency rather than an UNKNOWN marker.
        assert code_currency("^SPX") == "USD"
        assert code_currency("^VIX") == "USD"


class TestRejectMixedCurrency:
    """The guard separates a genuinely mixed book from a merely cross-market one."""

    def test_us_and_index_are_one_currency(self):
        _reject_mixed_currency(["AAPL.US", "^SPX", "^VIX"])

    def test_a_single_market_is_allowed(self):
        _reject_mixed_currency(["AAPL.US", "MSFT.US"])

    def test_empty_and_single_code_sets_are_allowed(self):
        _reject_mixed_currency([])
        _reject_mixed_currency(["AAPL.US"])

    def test_a_us_canada_basket_is_refused(self):
        # US (USD) + Canada (CAD) is the only possible cross-currency pair
        # after the refactor; it must fail closed rather than sum USD and CAD.
        with pytest.raises(ValueError, match="one settlement currency"):
            _reject_mixed_currency(["AAPL", "TD.TO"])

    def test_the_error_names_every_currency_and_its_codes(self):
        with pytest.raises(ValueError) as excinfo:
            _reject_mixed_currency(["AAPL.US", "TD.TO"])
        message = str(excinfo.value)
        for fragment in ("USD", "CAD", "AAPL.US", "TD.TO"):
            assert fragment in message


class TestRunBacktestFailsClosed:
    """A mixed run must stop before it fetches data or reports a metric."""

    class _RecordingLoader:
        def __init__(self):
            self.fetched = False

        def fetch(self, *args, **kwargs):
            self.fetched = True
            return {}

    def test_mixed_currency_run_raises_before_fetching(self):
        codes = ["AAPL.US", "TD.TO"]
        engine = CompositeEngine({"initial_cash": 1_000_000, "codes": codes}, codes)
        loader = self._RecordingLoader()

        with pytest.raises(ValueError, match="one settlement currency"):
            engine.run_backtest(
                {"initial_cash": 1_000_000, "codes": codes},
                loader,
                signal_engine=None,
                run_dir=None,
            )
        assert loader.fetched is False

    def test_constructing_a_mixed_engine_is_still_allowed(self):
        # Rule-book routing across the two markets is a legitimate use; only the
        # shared equity curve is unsound, so construction must not raise.
        codes = ["AAPL.US", "TD.TO"]
        engine = CompositeEngine({"initial_cash": 1_000_000, "codes": codes}, codes)
        assert engine._rule_for("AAPL.US").market == "us"
        assert engine._rule_for("TD.TO").market == "ca"


class TestCompositeRunInterval:
    """The run config, not the construction config, sets the funding bar span.

    ``CompositeEngine`` re-reads ``interval`` in ``run_backtest``; the composite
    must follow that convention so a run launched with a different interval
    than the one it was constructed with uses the run's interval (#1290).
    """

    def test_run_backtest_rereads_the_interval(self) -> None:
        codes = ["AAPL.US", "^SPX"]
        engine = CompositeEngine({"initial_cash": 100_000, "interval": "1D"}, codes)
        assert engine._run_interval == "1D"
        try:
            engine.run_backtest({"codes": codes, "interval": "4H"}, None, None, None)
        except Exception:
            pass  # the pipeline needs a real loader; only the re-read matters here
        assert engine._run_interval == "4H"
