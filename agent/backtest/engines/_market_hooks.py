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


# HKEX's Stock Code Allocation Plan (updated 2026-03-12) assigns a trading
# currency by code range: 80000-89999 are "Products traded in Renminbi" (the
# RMB counters, 80700.HK beside 00700.HK), and these sub-ranges trade in USD.
# Every other .HK code trades in HKD.
#
# NOTE: Hong Kong is no longer a settlement market in this build. This table is
# retained only because the grounding ledger's ``identity._infer_currency``
# still reads it; it is removed with that call site in the prompts/identity
# phase.
_HK_COUNTER_CURRENCY_RANGES: tuple[tuple[int, int, str], ...] = (
    (80000, 89999, "CNY"),
    (9000, 9199, "USD"),  # ETFs
    (9200, 9399, "USD"),  # leveraged and inverse products
    (9400, 9499, "USD"),  # ETFs
    (9500, 9599, "USD"),  # leveraged and inverse products
    (9700, 9799, "USD"),  # leveraged and inverse products
    (9800, 9849, "USD"),  # ETFs
    (10900, 10999, "USD"),  # derivative warrants
    (41500, 41599, "USD"),  # ETFs
)
_HK_CODE = re.compile(r"^(\d{3,5})\.HK$", re.I)


def hk_counter_currency(code: str) -> str | None:
    """Return the currency HKEX's code allocation assigns to a ``.HK`` code.

    Args:
        code: Ticker / symbol string, optionally ``local:``-prefixed.

    Returns:
        ``"CNY"``, ``"USD"`` or ``"HKD"`` for a Hong Kong code, ``None`` for
        anything else.
    """
    match = _HK_CODE.match(strip_local_prefix(code).strip())
    if match is None:
        return None
    number = int(match.group(1))
    return next(
        (cur for low, high, cur in _HK_COUNTER_CURRENCY_RANGES if low <= number <= high),
        "HKD",
    )


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
        ValueError: The symbol matches no supported US/CA/index pattern.
    """
    symbol = strip_local_prefix(code)
    for pattern, market in _MARKET_PATTERNS:
        if pattern.match(symbol):
            return market
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
