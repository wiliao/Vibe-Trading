"""Extracted per-bar market hooks and symbol-classification helpers.

Both the original engines (CryptoEngine, ForexEngine) and CompositeEngine
call these same functions. Zero duplication — one source of truth.

Also hosts symbol -> market detection helpers shared by ``runner.py`` and
``composite.py``: ``_MARKET_PATTERNS``, ``_detect_market``,
``_is_china_futures``, ``_detect_submarket``. Keep regex tables here so the
truncated-duplicate routing bug (bare ``RB2410`` getting routed to
GlobalFutures because composite.py used a suffix-only check) cannot recur.
"""

from __future__ import annotations

import re
from typing import Dict, List

import pandas as pd

from backtest.models import Position


# ── Symbol -> market classification (shared by runner.py + composite.py) ──

# Known Chinese-futures product codes — used as a heuristic when a symbol
# lacks an exchange suffix (e.g. bare ``RB2410``, ``IF2406``). Without this
# table composite.py was misrouting such bare codes to GlobalFutures.
# Stored lowercase; ``_is_china_futures`` lowercases the extracted product
# before lookup so callers can pass any case (``RB2410`` and ``rb2410``
# both resolve correctly).
_CN_FUTURES_PRODUCTS = {
    "if", "ic", "ih", "im", "t", "tf", "ts", "tl",
    "au", "ag", "cu", "al", "zn", "pb", "ni", "sn", "ss",
    "rb", "hc", "i", "j", "jm",
    "sc", "fu", "lu", "bu", "nr",
    "c", "cs", "m", "y", "a", "p", "jd", "lh",
    "cf", "sr", "ta", "ma", "ap", "rm", "oi",
    "pp", "l", "v", "eg", "eb", "pf", "sa", "fg", "ur",
    "si", "lc",
}


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

_CHINA_EXCHANGES = {"CFFEX", "SHFE", "DCE", "ZCE", "INE", "GFEX"}

# Tushare spells the same exchanges differently (ts_code='CU1811.SHF');
# normalize to the canonical suffix before any set membership test (#1394).
_EXCHANGE_ALIASES = {"SHF": "SHFE", "CZC": "ZCE", "CFX": "CFFEX", "GFE": "GFEX"}

# Supported settlement-currency contract per market. A composite backtest holds
# one shared capital pool, so a code set spanning both markets would add USD to
# CAD as if they were the same unit.
_MARKET_CURRENCY = {
    "us_equity": "USD",
    "ca_equity": "CAD",
}


# HKEX's Stock Code Allocation Plan (updated 2026-03-12) assigns a trading
# currency by code range: 80000-89999 are "Products traded in Renminbi" (the
# RMB counters, 80700.HK beside 00700.HK), and these sub-ranges trade in USD.
# Every other .HK code trades in HKD. The venue publishes the rule, so the
# currency is known whichever source served the bars -- unlike BYMA's dollar
# lines, where a trailing D is only a habit. Checked against the currency Yahoo
# declares for 24 codes across the ranges on 2026-09-24 (6 CNY, 10 USD, 8 HKD).
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


def _is_china_futures(code: str) -> bool:
    """Check whether a futures code belongs to a Chinese exchange.

    Recognises two forms:
      1. ``<product><delivery>.<exchange>`` where exchange is one of
         CFFEX/SHFE/DCE/ZCE/INE/GFEX (e.g. ``IF2406.CFFEX``, ``rb2410.SHFE``).
      2. Bare ``<product><delivery>`` with no exchange suffix — matched
         against ``_CN_FUTURES_PRODUCTS`` (e.g. ``RB2410`` -> True).

    Args:
        code: Symbol string.

    Returns:
        True if it looks like a Chinese futures contract.
    """
    parts = strip_local_prefix(code).upper().split(".")
    if len(parts) == 2:
        # Has an exchange suffix — trust it. CN exchange = True, anything
        # else = False. Without this guard the product-code heuristic below
        # would misclassify global futures whose product letters happen to
        # collide with a CN product (e.g. ``M2412.CBOT`` — US soybean meal).
        return _EXCHANGE_ALIASES.get(parts[1], parts[1]) in _CHINA_EXCHANGES
    # Bare code (no exchange suffix): fall back to product-code heuristic.
    m = re.match(r"([A-Za-z]+)\d+", parts[0])
    if m:
        product = m.group(1).lower()
        if product in _CN_FUTURES_PRODUCTS:
            return True
    return False


def _detect_submarket(codes: List[str]) -> str:
    """Detect US, HK, Canada, or UK from symbol suffixes.

    Args:
        codes: Instrument codes.

    Returns:
        ``"hk"`` for ``.HK``, ``"ca"`` for ``.TO``/``.V``, ``"uk"`` for
        ``.L``, else ``"us"``.
    """
    for code in codes:
        upper = code.upper()
        if upper.endswith(".HK"):
            return "hk"
        if upper.endswith((".TO", ".V")):
            return "ca"
        if upper.endswith(".L"):
            return "uk"
    return "us"

# ── Crypto: OKX tiered maintenance margin table (simplified) ──

_TIER_TABLE = [
    (100_000, 0.004),
    (500_000, 0.006),
    (1_000_000, 0.01),
    (5_000_000, 0.02),
    (10_000_000, 0.05),
    (float("inf"), 0.10),
]

FUNDING_HOURS = {0, 8, 16}


#: Spans of the calendar-period bars the runner builds from daily ones
#: (#1479). A month is the mean one, 365.25 / 12 days, so a monthly bar settles
#: 91 funding periods whether the month has 28 days or 31.
_PERIOD_SPAN_HOURS = {"1W": 168.0, "1M": 730.5}


def _interval_span_hours(interval: str) -> float | None:
    """Bar span in hours for a runner interval token, ``None`` when unknown.

    ``1M`` is a month and ``1m`` a minute; the period tokens are looked up
    whole before any suffix is read, so the two never meet.
    """
    token = str(interval).strip()
    if token in _PERIOD_SPAN_HOURS:
        return _PERIOD_SPAN_HOURS[token]
    for suffix, scale in (("m", 1 / 60), ("H", 1.0), ("D", 24.0)):
        if token.endswith(suffix) and token[: -len(suffix)].isdigit():
            return int(token[: -len(suffix)]) * scale
    return None


def _maintenance_rate(notional_usd: float) -> float:
    """Look up tiered maintenance margin rate."""
    for tier_max, rate in _TIER_TABLE:
        if notional_usd <= tier_max:
            return rate
    return _TIER_TABLE[-1][1]


def calc_crypto_funding_fee(
    symbol: str,
    bar: pd.Series,
    timestamp: pd.Timestamp,
    positions: Dict[str, Position],
    funding_rate: float,
    applied_set: set,
    daily_done_set: set,
    bar_span_hours: float | None = None,
) -> float:
    """Calculate crypto funding fee for one symbol.

    Args:
        symbol: Instrument code.
        bar: Current bar data.
        timestamp: Bar timestamp.
        positions: Shared positions dict.
        funding_rate: Fallback fixed rate per settlement, used when the bar
            carries no historical ``funding_rate`` column.
        applied_set: (symbol, date, hour) dedup set — mutated.
        daily_done_set: (symbol, date) dedup set — mutated.
        bar_span_hours: Bar span in hours when known. At 8h or wider the
            settlement count comes from the span (``max(1, span // 8)`` per
            bar), because a daily bar can never land on the 8h/16h slots:
            without this a daily-bar run charges a third of the documented
            funding model (#1290). Narrower bars keep the slot logic below
            unchanged.

    Returns:
        Fee amount (positive = longs pay, negative = longs receive).
    """
    if not hasattr(timestamp, "date"):
        return 0.0

    current_date = timestamp.date()
    hour = timestamp.hour if hasattr(timestamp, "hour") else 0

    settlements = 1
    if bar_span_hours is not None and bar_span_hours >= 8:
        settlements = max(1, int(bar_span_hours // 8))
        key = (symbol, current_date, hour)
        if key in applied_set:
            return 0.0
        applied_set.add(key)
    elif hour in FUNDING_HOURS:
        key = (symbol, current_date, hour)
        if key in applied_set:
            return 0.0
        applied_set.add(key)
    else:
        day_key = (symbol, current_date)
        if day_key in daily_done_set:
            return 0.0
        daily_done_set.add(day_key)

    pos = positions.get(symbol)
    if pos is None:
        return 0.0

    mark_price = float(bar.get("close", pos.entry_price))
    notional = pos.size * mark_price
    # Prefer the bar's historical funding rate when the loader supplied one
    # (USD-M perpetual data via BASE-USDT-PERP); fall back to the fixed
    # config rate otherwise so spot-proxy runs keep their behaviour.
    hist = bar.get("funding_rate")
    if hist is not None and pd.notna(hist):
        funding_rate = float(hist)
    return notional * funding_rate * pos.direction * settlements


def _liquidation_mark(bar: pd.Series, pos: Position) -> float:
    """Adverse price the liquidation check and the fill both use.

    Bar high for a short, low for a long -- mirroring the strict path's
    "adverse" convention (perpetual_risk._mark_price) -- falling back to the
    close, then the entry price, for bars without high/low. Detection and
    execution share the same mark so a wick trigger never fills at a better
    price than the venue that liquidated it.
    """
    mark_price = bar.get("high" if pos.direction < 0 else "low")
    if mark_price is None or pd.isna(mark_price):
        mark_price = bar.get("close")
    if mark_price is None or pd.isna(mark_price):
        mark_price = pos.entry_price
    return float(mark_price)


def check_crypto_liquidation(
    symbol: str,
    bar: pd.Series,
    positions: Dict[str, Position],
) -> bool:
    """Check if a crypto position should be liquidated.

    Fires when equity in the position (margin + unrealized) falls at or below
    the maintenance margin, marked at the adverse extremum so an intra-bar
    wick counts. A 1x long is exempt because its bankruptcy price is zero; a
    1x short is not -- margin is the full notional and a 2x adverse move
    zeroes it. Does NOT execute the liquidation -- the caller handles that.
    """
    pos = positions.get(symbol)
    if pos is None or (pos.leverage <= 1.0 and pos.direction > 0):
        return False

    mark_price = _liquidation_mark(bar, pos)
    margin = pos.size * pos.entry_price / pos.leverage
    unrealized = pos.direction * pos.size * (mark_price - pos.entry_price)

    notional = pos.size * mark_price
    maint_rate = _maintenance_rate(notional)
    maint_margin = notional * maint_rate

    return (margin + unrealized) <= maint_margin


# ── Forex: swap tables ──

_SWAP_LONG: dict[str, float] = {
    "EUR/USD": -6.5, "GBP/USD": -3.0, "USD/JPY": 8.0, "USD/CHF": 4.0,
    "AUD/USD": -2.0, "USD/CAD": 2.0, "NZD/USD": -1.5,
}
_SWAP_SHORT: dict[str, float] = {
    "EUR/USD": 3.5, "GBP/USD": -1.0, "USD/JPY": -12.0, "USD/CHF": -8.0,
    "AUD/USD": -1.0, "USD/CAD": -5.0, "NZD/USD": -2.0,
}


def _normalize_symbol(symbol: str) -> str:
    """Normalize forex symbol to 'XXX/YYY' format."""
    s = symbol.replace(".FX", "").replace(".", "").strip()
    if "/" in s:
        return s.upper()
    if len(s) == 6:
        return f"{s[:3]}/{s[3:]}".upper()
    return s.upper()


def calc_forex_swap(
    symbol: str,
    timestamp: pd.Timestamp,
    positions: Dict[str, Position],
    lot_size: float,
    last_swap_dates: dict,
) -> float:
    """Calculate forex swap for one symbol.

    Args:
        symbol: Forex pair.
        timestamp: Bar timestamp.
        positions: Shared positions dict.
        lot_size: Standard lot size (e.g. 100_000).
        last_swap_dates: Per-symbol date tracking dict -- mutated.

    Returns:
        Swap amount (positive = credit, negative = debit).
    """
    if not hasattr(timestamp, "date"):
        return 0.0

    current_date = timestamp.date()
    if last_swap_dates.get(symbol) == current_date:
        return 0.0
    last_swap_dates[symbol] = current_date

    pos = positions.get(symbol)
    if pos is None:
        return 0.0

    pair = _normalize_symbol(symbol)
    lots = pos.size / lot_size

    if pos.direction == 1:
        swap_per_lot = _SWAP_LONG.get(pair, -1.0)
    else:
        swap_per_lot = _SWAP_SHORT.get(pair, -1.0)

    # Wednesday = triple swap (covers Sat+Sun)
    multiplier = 3.0 if timestamp.weekday() == 2 else 1.0
    return lots * swap_per_lot * multiplier
