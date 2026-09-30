"""Pin the volume-unit declarations of the surviving equity loaders.

After the US/CA refactor the surviving loaders declare single-share volume for
US equities (the one empirically verified case); every other surviving market
stays undeclared rather than guessed.
"""

from __future__ import annotations

import pytest

from backtest.loaders.eastmoney_loader import DataLoader as EastmoneyLoader
from backtest.loaders.local_loader import DataLoader as LocalLoader
from backtest.loaders.stooq_loader import DataLoader as StooqLoader
from backtest.loaders.yahoo_loader import DataLoader as YahooLoader
from backtest.loaders.yfinance_loader import DataLoader as YfinanceLoader


@pytest.mark.parametrize(
    ("loader_cls", "market", "expected"),
    [
        (YahooLoader, "us_equity", "shares"),
        (YfinanceLoader, "us_equity", "shares"),
        (StooqLoader, "us_equity", "shares"),
    ],
)
def test_loader_volume_unit_declaration(loader_cls, market, expected):
    assert getattr(loader_cls, "volume_units", {})[market] == expected


def test_undeclared_markets_surface_as_missing_not_wrong():
    """Markets without evidence stay undeclared (null), never guessed."""
    assert "ca_equity" not in YahooLoader.volume_units
    assert "us_equity" not in EastmoneyLoader.volume_units
    assert getattr(LocalLoader, "volume_units", {}) == {}
