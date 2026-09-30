"""yfinance loader enforces its market's quote-currency contract.

The TSX is one static CAD pool but lists a few lines in a second currency
(``DLR-U.TO`` quotes in USD beside ``DLR.TO`` in CAD). The suffix names the
venue, never the currency, so the loader reads Yahoo's declared currency and
rejects a line that cannot safely enter the pool. (The removed markets' LSE
pence and BYMA peso pools — and their GBp÷100 normalization — were deleted with
the US/CA refactor.)
"""
from __future__ import annotations

import pandas as pd
import pytest

import backtest.loaders.yfinance_loader as yfl


def _download_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [10.0, 10.5],
            "High": [11.0, 11.5],
            "Low": [9.0, 10.0],
            "Close": [10.5, 11.0],
            "Volume": [100, 200],
        },
        index=pd.DatetimeIndex(["2025-01-02", "2025-01-03"], name="Date"),
    )


def test_fetch_leaves_us_prices_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIBE_TRADING_DATA_CACHE", raising=False)

    def fake_download(tickers, start_date, end_date, interval):
        assert tickers == ["AAPL"]
        return _download_frame()

    monkeypatch.setattr(yfl, "_download_history", fake_download)

    result = yfl.DataLoader().fetch(["AAPL.US"], "2025-01-01", "2025-01-03")

    # A US listing needs no declared-currency probe: its pool is USD by suffix.
    assert result["AAPL.US"]["close"].iloc[0] == pytest.approx(10.5)


@pytest.mark.parametrize(
    ("symbol", "declared", "admitted"),
    [
        ("DLR.TO", "CAD", True),
        ("DLR.TO", "USD", False),
        ("DLR.TO", None, False),
        ("DLR-U.TO", "USD", False),
    ],
)
def test_fetch_admits_a_tsx_line_only_in_cad(
    monkeypatch: pytest.MonkeyPatch, symbol: str, declared: str | None, admitted: bool
) -> None:
    """The TSX's second-currency lines must not enter the static CAD pool."""
    monkeypatch.delenv("VIBE_TRADING_DATA_CACHE", raising=False)
    asked: list[str] = []

    def declared_currency(requested: str) -> str | None:
        asked.append(requested)
        return declared

    monkeypatch.setattr(yfl, "_download_history", lambda *args: _download_frame())
    monkeypatch.setattr(yfl, "_declared_currency", declared_currency)

    result = yfl.DataLoader().fetch([symbol], "2025-01-01", "2025-01-03")

    assert asked == [symbol]
    assert (symbol in result) is admitted
    if admitted:
        assert result[symbol].attrs["quote_currency"] == declared


def test_fetch_declared_currency_failure_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_offline(_symbol: str):
        raise RuntimeError("offline")

    monkeypatch.setattr(yfl.yf, "Ticker", raise_offline)

    assert yfl._declared_currency("DLR.TO") is None
