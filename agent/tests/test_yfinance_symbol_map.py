"""yfinance symbol translation for US class shares (#1351).

Yahoo/yfinance serve US class shares only in hyphen form (``BRK-B``);
the dot form (``BRK.B``) returns empty data, so the ``.US`` conversion
must fold internal dots to hyphens.
"""

from backtest.loaders.yfinance_loader import _to_yfinance_symbol


def test_class_shares_map_to_hyphen_form() -> None:
    assert _to_yfinance_symbol("BRK.B.US") == "BRK-B"
    assert _to_yfinance_symbol("BRK.A.US") == "BRK-A"
    assert _to_yfinance_symbol("BF.B.US") == "BF-B"


def test_plain_tickers_unchanged() -> None:
    assert _to_yfinance_symbol("AAPL.US") == "AAPL"
    assert _to_yfinance_symbol("AAPL") == "AAPL"


def test_crypto_and_suffix_forms_untouched() -> None:
    # Crypto markets were removed with the US/CA refactor, so a stablecoin pair
    # is no longer rewritten onto its USD form; Canada suffixes pass through.
    assert _to_yfinance_symbol("BTC-USDT") == "BTC-USDT"
    assert _to_yfinance_symbol("TD.TO") == "TD.TO"
