"""Symbol -> market classification helpers shared by runner.py and composite.py.

Hosts the regex tables (``_MARKET_PATTERNS``), ``_detect_market``,
``_detect_submarket``, the settlement-currency contract (``code_currency``)
and the ``local:`` prefix helper. Keep the tables here so every consumer reads
one classification.
"""

from __future__ import annotations

import re
from typing import List

# ── Symbol -> market classification (shared by runner.py + composite.py) ──

_MARKET_PATTERNS = [
    # US equities: tickers may carry a class-share dot (BRK.B.US, BF.B.US)
    # and a hyphen (e.g. BF-B.US).
    (re.compile(r"^[A-Z0-9&.\-]+\.US$", re.I), "us_equity"),
    # Canada equities: Toronto Stock Exchange (TD.TO) and TSX Venture
    # (PNG.V). Yahoo carries both suffixes verbatim.
    (re.compile(r"^[A-Z0-9&.\-]+\.(TO|V)$", re.I), "ca_equity"),
    # Yahoo index symbols (^SPX, ^NDX, ^VIX, ...) — served verbatim.
    # Classified as their own market (D1) so they never route through an
    # equity settlement currency.
    (re.compile(r"^\^[A-Za-z0-9.\-]+$"), "index"),
    # Bare US tickers (AAPL, MSFT, SPY, T, ...). Must stay LAST so every
    # suffixed form above wins first. ``{1,5}`` covers every standard US
    # ticker length; longer unknown codes fall through to the fail-loud
    # default in ``_detect_market``.
    (re.compile(r"^[A-Z]{1,5}$", re.I), "us_equity"),
]

# Supported settlement-currency contract per market. A composite backtest holds
# one shared capital pool, so a code set spanning both markets would add USD to
# CAD as if they were the same unit. Index levels (^SPX, ^VIX, ...) are
# USD-denominated benchmark inputs, so they are comparable with US equities.
_MARKET_CURRENCY = {
    "us_equity": "USD",
    "ca_equity": "CAD",
    "index": "USD",
}

# ── Crypto-pair recognition (classification only, never routing) ──────────
#
# Crypto is a removed market in this US/CA build: no loader chain, no engine,
# no settlement-currency row. But the symbol layers above still speak crypto —
# symbol search returns Yahoo-native pairs like BTC-USD verbatim (labelled
# "global") and the grounding identity scanner knows their spellings — so a
# pair like BTC-USD used to fall into the generic "unsupported symbol format:
# expected a US ticker …" error, i.e. it was *treated as a stock symbol* that
# happened to be malformed. Recognizing the shape here keeps classification
# honest (BTC-USD is crypto, not an equity) and lets ``_detect_market`` answer
# with a clear "crypto is not a supported market" instead.
#
# Mirrors ``src.tools.symbol_search_tool._canonical_crypto_pair`` (kept
# independent so this module stays dependency-free for subprocess entry
# points): stablecoin quotes accept any alphanumeric base — no real-world
# asset except crypto ones trades quoted in stablecoins — while a USD/BTC/ETH/
# BNB quote is gated on the whitelist of major coins below. A pair whose BOTH
# legs are fiat (GBP-USD, EUR/USD) is forex, never crypto.

_CRYPTO_STABLECOIN_QUOTES = ("FDUSD", "USDT", "USDC", "BUSD", "TUSD")
_CRYPTO_QUOTE_ASSETS = _CRYPTO_STABLECOIN_QUOTES + ("BTC", "ETH", "BNB", "USD")
# Bases that may pair with USD/BTC/ETH/BNB and still count as a crypto pair —
# majors listed on the big spot exchanges. XAU/EUR/etc are deliberately out.
_CRYPTO_QUOTE_BASES = frozenset(
    {
        "BTC", "ETH", "BNB", "SOL", "ADA", "XRP", "DOGE", "TRX", "DOT",
        "MATIC", "AVAX", "LINK", "LTC", "BCH", "ETC", "XLM", "ATOM",
        "FIL", "APT", "NEAR", "ALGO", "SAND", "MANA", "AXS", "XAUT",
        "PAXG",
    }
)
# Fiat ISO codes: a pair whose both legs are fiat is an FX pair, never crypto.
_FIAT_LEG_CODES = frozenset(
    {
        "USD", "EUR", "GBP", "JPY", "CHF", "CNY", "CNH", "HKD", "AUD", "NZD",
        "CAD", "KRW", "INR", "SGD", "SEK", "NOK", "DKK", "MXN", "BRL", "ZAR",
        "TRY", "RUB", "PLN", "THB", "MYR", "IDR", "PHP", "VND", "ILS", "AED",
        "SAR", "EGP", "CZK", "HUF", "RON", "CLP", "COP", "PEN", "TWD", "CUP",
    }
)
# BASE-QUOTE / BASE/QUOTE spelling, e.g. BTC-USD, ETH/USDT.
_CRYPTO_SEPARATED_RE = re.compile(
    r"^([A-Z0-9]{2,15})[-/]([A-Z]{3,5})$", re.I
)
# Joined alnum spelling, e.g. a base run straight into its quote (no
# separator). The stablecoin quotes come first so the longest quote wins on a
# suffix collision (…USD vs …USDT).
_CRYPTO_JOINED_RE = re.compile(
    r"^([A-Z0-9]{2,15})(?:" + "|".join(_CRYPTO_QUOTE_ASSETS) + r")$",
    re.I,
)


def _is_crypto_pair(symbol: str) -> bool:
    """Return whether *symbol* is spelled as a crypto pair.

    Recognizes the dashed/slash form (``BTC-USD``, ``ETH/USDT``) and the
    joined form (a base run straight into its quote, no separator). The quote
    leg must be a stablecoin (any base accepted) or one of USD/BTC/ETH/BNB
    paired with a whitelisted major coin; both legs fiat is forex, not crypto.

    Args:
        symbol: Bare symbol without any ``local:`` routing prefix.

    Returns:
        ``True`` when the spelling is a crypto pair.
    """
    upper = symbol.strip().upper()
    if not upper:
        return False
    matched = _CRYPTO_SEPARATED_RE.fullmatch(upper)
    if matched:
        base, quote = matched.group(1), matched.group(2)
    else:
        matched = _CRYPTO_JOINED_RE.fullmatch(upper)
        if not matched:
            return False
        # The joined regex only anchors the tail; recover the split so the
        # fiat-leg and whitelist gates see the real base/quote legs.
        for quote in _CRYPTO_QUOTE_ASSETS:
            if upper.endswith(quote) and len(upper) > len(quote) + 1:
                base, quote = upper[: -len(quote)], quote
                break
        else:
            return False
    if quote in _FIAT_LEG_CODES and base in _FIAT_LEG_CODES:
        # Both legs fiat is an FX pair (GBP-USD, EUR-USD), never crypto.
        return False
    if quote in _CRYPTO_STABLECOIN_QUOTES:
        return True
    return quote in ("USD", "BTC", "ETH", "BNB") and base in _CRYPTO_QUOTE_BASES


def strip_local_prefix(code: str) -> str:
    """Return the instrument symbol behind a ``local:`` routing prefix.

    ``local:AAPL.US`` asks for the user's own ``AAPL.US`` dataset. The prefix
    chooses the loader; it is not part of the instrument, so market rules,
    price caliber and result keys must all see ``AAPL.US``.

    Args:
        code: Ticker / symbol string, optionally prefixed with ``local:``.

    Returns:
        The symbol without the prefix, or ``code`` unchanged.
    """
    return code.split(":", 1)[1] if code[:6].lower() == "local:" else code


def _detect_market(code: str) -> str:
    """Infer market type from symbol format.

    Args:
        code: Ticker / symbol string.

    Returns:
        One of ``"us_equity"``, ``"ca_equity"`` or ``"index"``. Bare 1-5
        letter alphabetic tickers resolve to ``us_equity``; ``.US``,
        ``.TO``/``.V`` and ``^``-prefixed index symbols resolve to their
        markets. Any format that matches no pattern is a user error in a
        US/CA-only build and raises ``ValueError`` (fail loud) rather than
        silently misrouting to a removed market.

    Raises:
        ValueError: The symbol names crypto, a removed market with no data
            source here, or matches no supported US/CA/index pattern at all.
    """
    symbol = strip_local_prefix(code)
    for pattern, market in _MARKET_PATTERNS:
        if pattern.match(symbol):
            return market
    if _is_crypto_pair(symbol):
        # A crypto pair is NOT a malformed stock ticker: say so instead of
        # telling the caller to use a US/CA ticker format. Crypto has no
        # loader chain or engine in this build, so it stays fail-loud.
        raise ValueError(
            f"Crypto symbol {code!r} is not a supported market: this build "
            "routes US tickers (bare or .US), Canadian tickers (.TO/.V), and "
            "^-prefixed indexes only."
        )
    raise ValueError(
        f"Unsupported symbol format {code!r}: expected a US ticker "
        f"(bare or .US), a Canadian ticker (.TO/.V), or a ^-prefixed index."
    )


def code_currency(code: str) -> str:
    """Return the supported settlement-currency contract for a symbol.

    Args:
        code: Ticker / symbol string.

    Returns:
        A currency code such as ``"USD"`` or ``"CAD"``. A symbol whose currency
        cannot be established returns a ``"UNKNOWN:<market>"`` marker rather
        than a guess, so a homogeneous set still compares equal while a mixed
        one cannot pass a same-currency check by accident.
    """
    code = strip_local_prefix(code)
    market = _detect_market(code)
    if market in _MARKET_CURRENCY:
        return _MARKET_CURRENCY[market]
    return f"UNKNOWN:{market}"


def _detect_submarket(codes: List[str]) -> str:
    """Detect Canada vs US from symbol suffixes.

    Args:
        codes: Instrument codes.

    Returns:
        ``"ca"`` for ``.TO``/``.V``, else ``"us"``.
    """
    for code in codes:
        if code.upper().endswith((".TO", ".V")):
            return "ca"
    return "us"
