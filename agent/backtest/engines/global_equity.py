"""US / Canada equity backtest engine.

Market rules:
  US:
    - T+0, long/short allowed
    - Zero commission (retail brokers)
    - Fractional shares supported (round to 0.01)
    - Low slippage (high liquidity)
  Canada (TSX / TSX Venture):
    - Same-session round trips and long/short orders supported
    - Whole shares; odd and mixed lots remain executable
    - Broker commission and slippage are config-driven
    - Official TSX/TSXV price-increment grid is applied to fills
"""

from __future__ import annotations

import math

import pandas as pd

from backtest.engines.base import BaseEngine


class GlobalEquityEngine(BaseEngine):
    """US / Canada equity engine selected by *market*.

    Config keys:
      - slippage_us: default 0.0005
      - slippage_ca: defaults to slippage_us
      - ca_commission: broker commission rate, default 0.0
    """

    def __init__(self, config: dict, market: str = "us"):
        config = {**config, "leverage": config.get("leverage", 1.0)}
        super().__init__(config)
        self.market = market

        # US defaults
        self.slippage_us: float = config.get("slippage_us", 0.0005)
        # Canada defaults. Commission varies by broker, so the model exposes a
        # rate instead of inventing an exchange-wide charge.
        self.slippage_ca: float = config.get("slippage_ca", self.slippage_us)
        self.ca_commission: float = config.get("ca_commission", 0.0)

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """Allow same-session trading in both directions for both markets."""
        return True

    def round_size(self, raw_size: float, price: float) -> float:
        """US: fractional; Canada: whole shares.

        TSX and TSXV accept odd and mixed lots through dedicated facilities,
        so forcing every order to a board lot would reject valid retail trades.
        Canada has no native fractional-share order, hence the whole-share
        floor.
        """
        if self.market == "ca":
            return float(math.floor(max(raw_size, 0.0)))
        return round(max(raw_size, 0.0), 2)

    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        """US: zero; Canada: configured broker rate."""
        if self.market == "ca":
            return size * price * self.ca_commission
        # US: zero commission (SEC fee negligible)
        return 0.0

    def apply_slippage(self, price: float, direction: int) -> float:
        """Apply market slippage and Canada's official price-increment grid."""
        if self.market == "ca":
            rate = self.slippage_ca
        else:
            rate = self.slippage_us
        slipped = price * (1 + direction * rate)
        if self.market != "ca":
            return slipped

        # TSX/TSXV standard increments: $0.005 below $0.50, otherwise $0.01.
        # Round against the trader: buys/cover orders up, sells/shorts down.
        tick = 0.005 if slipped < 0.50 else 0.01
        units = slipped / tick
        if direction > 0:
            steps = math.ceil(units - 1e-12)
        elif direction < 0:
            steps = math.floor(units + 1e-12)
        else:
            steps = round(units)
        return round(steps * tick, 3 if tick == 0.005 else 2)
