"""Composite cross-market backtest engine.

Manages a shared capital pool across multiple market engines.
Sub-engines are used as stateless "rule books" for market-specific
calculations (commission, slippage, lot rounding, etc.).
All state (capital, positions, trades) lives in CompositeEngine.
"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd

from backtest.engines.base import BaseEngine
from backtest.engines._market_hooks import _detect_market, code_currency


def _build_rule_engines(config: dict, codes: List[str]) -> Dict[str, BaseEngine]:
    """Instantiate one sub-engine per market type detected in codes."""
    markets = {_detect_market(c) for c in codes}
    engines: Dict[str, BaseEngine] = {}

    for market in markets:
        if market in ("us_equity", "index"):
            from backtest.engines.global_equity import GlobalEquityEngine
            engines[market] = GlobalEquityEngine(config, market="us")
        elif market == "ca_equity":
            from backtest.engines.global_equity import GlobalEquityEngine
            engines[market] = GlobalEquityEngine(config, market="ca")
        else:
            raise ValueError(
                f"Unsupported market for composite rules: {market!r}. "
                "Composite backtests support US, Canada, and index symbols."
            )

    return engines


def _reject_mixed_currency(codes: List[str]) -> None:
    """Refuse a code set whose members do not settle in one currency.

    The shared capital pool holds a single scalar of cash and sums position
    values into a single equity curve. With codes from two currency zones that
    curve adds CNY to USD to KRW as if the units matched, and every metric
    derived from it — return, Sharpe, drawdown — is meaningless. There is no FX
    translation layer yet, so this fails closed rather than reporting a number
    that looks fine.

    Args:
        codes: Instrument codes for the backtest.

    Raises:
        ValueError: If the codes span more than one settlement currency.
    """
    by_currency: Dict[str, List[str]] = {}
    for code in codes:
        by_currency.setdefault(code_currency(code), []).append(code)
    if len(by_currency) <= 1:
        return
    breakdown = "; ".join(
        f"{currency}: {', '.join(sorted(members))}"
        for currency, members in sorted(by_currency.items())
    )
    raise ValueError(
        "composite backtest requires one settlement currency across all codes, "
        f"but got {len(by_currency)} — {breakdown}. The shared capital pool has "
        "no FX translation, so a mixed-currency equity curve would sum "
        "different units. Split the run by currency, or convert the inputs "
        "to one currency before loading."
    )


class CompositeEngine(BaseEngine):
    """Cross-market engine with shared capital pool.

    Sub-engines are stateless rule providers. All positions, capital,
    and trades live here (inherited from BaseEngine).

    Args:
        config: Backtest configuration dict.
        codes: List of instrument codes spanning multiple markets.
    """

    def __init__(self, config: dict, codes: List[str]):
        super().__init__(config)

        # Build symbol -> market mapping
        self._symbol_market: Dict[str, str] = {c: _detect_market(c) for c in codes}

        # Build sub-engines (one per market type)
        self._rule_engines = _build_rule_engines(config, codes)

        self._run_interval = str(config.get("interval", "1D"))

    def run_backtest(self, config: dict, *args, **kwargs):
        """Run the pipeline, refusing a code set that spans currencies.

        The check lives here rather than in ``__init__`` because the damage is
        in the shared equity curve, not in constructing the rule-book engines.

        Args:
            config: Backtest configuration dict.
            *args: Forwarded to :meth:`BaseEngine.run_backtest`.
            **kwargs: Forwarded to :meth:`BaseEngine.run_backtest`.

        Returns:
            The metrics dictionary from :meth:`BaseEngine.run_backtest`.

        Raises:
            ValueError: If the codes span more than one settlement currency.
        """
        _reject_mixed_currency(config.get("codes") or list(self._symbol_market))
        # The run config, not the construction config, is authoritative for the
        # bar span.
        self._run_interval = str(config.get("interval", "1D"))
        return super().run_backtest(config, *args, **kwargs)

    def _rule_for(self, symbol: str) -> BaseEngine:
        """Get the sub-engine that provides rules for this symbol."""
        market = self._symbol_market.get(symbol)
        engine = self._rule_engines.get(market) if market is not None else None
        if engine is None:
            raise ValueError(
                f"No sub-engine for symbol {symbol!r} (market {market!r})"
            )
        return engine

    # ── Stateless method dispatch ──

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """Delegate the market-rule check to the symbol's sub-engine."""
        return self._rule_for(symbol).can_execute(symbol, direction, bar)

    def round_size(self, raw_size: float, price: float) -> float:
        """Delegate to active symbol's sub-engine."""
        sub = self._rule_for(self._active_symbol)
        # A shared sub-engine instance keeps whatever symbol last synced it,
        # so refresh ``_active_symbol`` on every dispatch.
        sub._active_symbol = self._active_symbol
        return sub.round_size(raw_size, price)

    def calc_commission(
        self, size: float, price: float, direction: int, is_open: bool,
    ) -> float:
        """Delegate to active symbol's sub-engine."""
        sub = self._rule_for(self._active_symbol)
        sub._active_symbol = self._active_symbol
        return sub.calc_commission(size, price, direction, is_open)

    def apply_slippage(self, price: float, direction: int) -> float:
        """Delegate to active symbol's sub-engine."""
        sub = self._rule_for(self._active_symbol)
        sub._active_symbol = self._active_symbol
        return sub.apply_slippage(price, direction)

    # ── PnL / margin dispatch (route by symbol, not _active_symbol) ──

    def _calc_pnl(
        self, symbol: str, direction: int, size: float,
        entry_price: float, exit_price: float,
    ) -> float:
        return self._rule_for(symbol)._calc_pnl(
            symbol, direction, size, entry_price, exit_price,
        )

    def _calc_margin(
        self, symbol: str, size: float, price: float, leverage: float,
    ) -> float:
        return self._rule_for(symbol)._calc_margin(symbol, size, price, leverage)

    def _calc_raw_size(
        self, symbol: str, target_notional: float, price: float,
    ) -> float:
        return self._rule_for(symbol)._calc_raw_size(symbol, target_notional, price)

    def _leverage_for_symbol(self, symbol: str) -> float:
        return self._rule_for(symbol)._leverage_for_symbol(symbol)
