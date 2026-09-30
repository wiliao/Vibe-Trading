"""Tests for US/CA market detection, source mapping, and code grouping.

The US/CA refactor (docs/refactor-plan.md Phase 1) reduced the data plane to
two settlement markets plus the index chain. These tests pin the surviving
surface: US/Canada/index acceptance and the fail-loud rejection of every
removed market.
"""

from __future__ import annotations

import pytest

from backtest.engines._market_hooks import _detect_market, code_currency
from backtest.runner import _group_codes_by_market
from src.market_data import detect_source


class TestDetectMarket:
    """Symbol pattern -> market type for the surviving markets."""

    @pytest.mark.parametrize(
        "code, expected",
        [
            # US equity — suffixed, dotted class shares, and bare tickers
            ("AAPL.US", "us_equity"),
            ("TSLA.US", "us_equity"),
            ("BRK.B.US", "us_equity"),
            ("BRK.A.US", "us_equity"),
            ("BF.B.US", "us_equity"),
            ("AAPL", "us_equity"),
            ("MSFT", "us_equity"),
            ("SPY", "us_equity"),
            ("T", "us_equity"),
            ("V", "us_equity"),
            # Canada equity (TSX / TSX Venture)
            ("TD.TO", "ca_equity"),
            ("BBD-B.TO", "ca_equity"),
            ("SHOP.TO", "ca_equity"),
            ("PNG.V", "ca_equity"),
            # Yahoo index symbols (decision D1)
            ("^SPX", "index"),
            ("^GSPC", "index"),
            ("^VIX", "index"),
        ],
    )
    def test_known_patterns(self, code: str, expected: str) -> None:
        assert _detect_market(code) == expected

    def test_case_insensitive(self) -> None:
        assert _detect_market("aapl.us") == "us_equity"
        assert _detect_market("aapl") == "us_equity"
        assert _detect_market("td.to") == "ca_equity"
        assert _detect_market("png.v") == "ca_equity"
        assert _detect_market("brk.b.us") == "us_equity"

    @pytest.mark.parametrize(
        "code",
        [
            # A-share
            "000001.SZ", "600519.SH", "300750.SZ", "830799.BJ",
            # HK
            "0700.HK", "9988.HK", "00005.HK",
            # India / Korea
            "RELIANCE.NS", "500325.BO", "005930.KS", "247540.KQ",
            # UK
            "VOD.L", "SHEL.L",
            # Crypto
            "BTC-USDT", "BTCUSDT", "ETH/USDT", "ETHUSDC",
            # Futures
            "IF2406.CFFEX", "ES.CME", "GC=F", "RB0",
            # Forex
            "EUR/USD", "EURUSD", "XAUUSD=X",
            # Garbage / unclassifiable
            "UNKNOWN", "random-string", "12345", "123456", "@#$",
        ],
    )
    def test_removed_markets_fail_loud(self, code: str) -> None:
        # A code that matches no US/CA/index pattern is a user error now, not
        # a silent misroute to a removed market.
        with pytest.raises(ValueError):
            _detect_market(code)


class TestCodeCurrency:
    @pytest.mark.parametrize(
        "code, expected",
        [
            ("AAPL", "USD"),
            ("AAPL.US", "USD"),
            ("TD.TO", "CAD"),
            ("PNG.V", "CAD"),
        ],
    )
    def test_settlement_currency(self, code: str, expected: str) -> None:
        assert code_currency(code) == expected

    def test_index_is_usd_comparable(self) -> None:
        assert code_currency("^SPX") == "USD"


class TestDetectSource:
    """Preferred source for the surviving markets (src.market_data)."""

    @pytest.mark.parametrize(
        "code, expected",
        [
            ("AAPL.US", "yahoo"),
            ("TD.TO", "yahoo"),
            ("PNG.V", "yahoo"),
            ("^SPX", "yahoo"),
            ("^GSPC", "yahoo"),
            ("local:AAPL", "local"),
        ],
    )
    def test_source_mapping(self, code: str, expected: str) -> None:
        assert detect_source(code) == expected

    def test_unmatched_falls_back_to_yahoo(self) -> None:
        # Bare US tickers have no _SOURCE_PATTERNS entry; they resolve to the
        # universal Yahoo source and are market-validated by _detect_market.
        assert detect_source("AAPL") == "yahoo"


class TestGroupCodes:
    def test_mixed_us_ca_index(self) -> None:
        codes = ["AAPL.US", "TD.TO", "^SPX", "MSFT"]
        groups = _group_codes_by_market(codes)
        assert groups["us_equity"] == ["AAPL.US", "MSFT"]
        assert groups["ca_equity"] == ["TD.TO"]
        assert groups["index"] == ["^SPX"]

    def test_same_market(self) -> None:
        assert _group_codes_by_market(["AAPL", "MSFT"]) == {
            "us_equity": ["AAPL", "MSFT"],
        }

    def test_empty(self) -> None:
        assert _group_codes_by_market([]) == {}
