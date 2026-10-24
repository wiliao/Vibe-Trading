"""Connector-prefixed codes must reach the risk x-ray and merge across brokers."""

from __future__ import annotations

import pytest

from src.portfolio.normalization import normalize_position
from src.portfolio.service import PortfolioService


def _futu(code: str, market: str, currency: str) -> dict:
    position = normalize_position(
        "futu",
        {"code": code, "qty": 10, "market_val": 1000, "average_cost": 90,
         "market": market, "currency": currency},
    )
    position.update(priced=True, market_value_usd=1000, broker="futu")
    return position


def test_futu_prefixed_codes_are_risk_xray_symbols() -> None:
    args = PortfolioService._risk_xray_args(
        [_futu("US.AAPL", "US", "USD"), _futu("US.BRK.B", "US", "USD")]
    )
    assert sorted(args["symbols"]) == ["AAPL.US", "BRK.B.US"]


def test_futu_and_suffix_form_holdings_merge() -> None:
    longbridge = {"symbol": "AAPL.US", "currency": "USD", "market": "US", "broker": "longbridge",
                  "asset_type": "stock", "market_value_usd": 500}
    ibkr = {"symbol": "NVDA", "currency": "USD", "market": "US", "broker": "ibkr",
            "asset_type": "stock", "market_value_usd": 300}
    rows = PortfolioService._combine_holdings(
        [_futu("US.AAPL", "US", "USD"), longbridge, _futu("US.NVDA", "US", "USD"), ibkr]
    )
    by_id = {row["canonical_id"]: row for row in rows}
    assert set(by_id) == {"US:AAPL", "US:NVDA"}
    assert by_id["US:AAPL"]["duplicate_across_brokers"] is True
    assert by_id["US:AAPL"]["brokers"] == ["futu", "longbridge"]
    assert by_id["US:NVDA"]["brokers"] == ["futu", "ibkr"]


def test_suffix_form_symbols_still_route_to_the_risk_xray() -> None:
    toronto = {"symbol": "SHOP.TO", "currency": "CAD", "priced": True,
               "market_value_usd": 1000, "asset_type": "stock"}
    assert PortfolioService._risk_xray_symbol(toronto) == "SHOP.TO"
    tsx_v = {"symbol": "WD.V", "currency": "CAD", "priced": True,
             "market_value_usd": 500, "asset_type": "stock"}
    assert PortfolioService._risk_xray_symbol(tsx_v) == "WD.V"


@pytest.mark.parametrize("code,expected", [
    (" US.BRK.B ", "BRK.B.US"), ("us.aapl", "AAPL.US"),
    ("SHOP.TO", "SHOP.TO"), ("AAPL", "AAPL.US"),
])
def test_prefix_conversion_preserves_share_classes_and_venues(code, expected):
    assert PortfolioService._risk_xray_symbol(
        {"symbol": code, "currency": "USD"}
    ) == expected


def test_futu_whitespace_does_not_split_the_same_holding():
    rows = PortfolioService._combine_holdings([
        _futu(" US.AAPL ", "US", "USD"), _futu("AAPL.US", "US", "USD"),
    ])
    assert len(rows) == 1
    assert rows[0]["market_value_usd"] == 2000.0
