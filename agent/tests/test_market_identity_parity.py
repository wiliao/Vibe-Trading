"""Every market the data layer routes is known to identity and symbol search (#1565).

A market is added in ``backtest.engines._market_hooks`` (pattern + currency) and
the backtest can then price it. The grounding identity layer and symbol search
keep their own suffix tables, and nothing tied them to that one: ``.L``, ``.VN``
and ``.BA`` each shipped with no canonical-symbol scan, no venue, no currency,
and search results labelled ``global``. This test makes the backtest's currency
table the list, so a new market fails here until it has a row.
"""

from __future__ import annotations

import pytest

from backtest.engines._market_hooks import _MARKET_CURRENCY, _detect_market
from src.agent.grounding.identity import _infer_currency, _infer_venue, _scan_symbols
from src.tools.symbol_search_tool import _from_yahoo_symbol

# market -> (project symbol, Yahoo's spelling of it, symbol-search label)
_SAMPLES: dict[str, tuple[str, str, str]] = {
    "us_equity": ("AAPL.US", "AAPL", "us"),
    "ca_equity": ("TD.TO", "TD.TO", "ca"),
}

# Index levels have a currency row but no listing suffix / venue: they carry no
# canonical-symbol scan of their own.
_NOT_A_LISTING_MARKET = {"index"}


def test_every_currency_market_has_a_sample() -> None:
    assert set(_SAMPLES) == set(_MARKET_CURRENCY) - _NOT_A_LISTING_MARKET


@pytest.mark.parametrize("market", sorted(_SAMPLES))
def test_identity_and_search_know_the_market(market: str) -> None:
    symbol, yahoo_symbol, label = _SAMPLES[market]

    assert _detect_market(symbol) == market
    assert _scan_symbols(f"What did {symbol} close at yesterday?") == {symbol}
    assert _infer_venue(symbol) is not None
    assert _infer_currency(symbol) == _MARKET_CURRENCY[market]
    assert _from_yahoo_symbol(yahoo_symbol, {"quoteType": "EQUITY"}) == (symbol, label)
