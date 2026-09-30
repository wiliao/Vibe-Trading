"""Cross-market strategy example: vol-adjusted dual-MA with per-market parameters.

Covers the two venues this repo trades — US and Canada equity — including
dual-listed names (e.g. ``RY`` on NYSE vs ``RY.TO`` on TSX). The CompositeEngine
handles calendar alignment, market rules, and shared capital.
"""

import re

import numpy as np
import pandas as pd


# Per-market indicator parameters
MARKET_PARAMS = {
    "us_equity": {"ma_fast": 10, "ma_slow": 50, "vol_lookback": 20},
    "ca_equity": {"ma_fast": 10, "ma_slow": 50, "vol_lookback": 20},
}

_MARKET_PATTERNS = [
    # Canadian listings carry the Yahoo exchange suffix; TSXV uses .V.
    (re.compile(r"^[A-Z0-9&.\-]+\.(TO|V)$", re.I), "ca_equity"),
    # Everything else that looks like a North-American equity ticker is US.
    (re.compile(r"^[A-Z][A-Z0-9.\-]{0,6}$"), "us_equity"),
]


class SignalEngine:
    def generate(self, data_map: dict) -> dict:
        # Step 1: raw signals per market
        raw_signals = {}
        for code, df in data_map.items():
            market = self._detect_market(code)
            params = MARKET_PARAMS.get(market, MARKET_PARAMS["us_equity"])
            raw_signals[code] = self._market_signal(df, params)

        # Step 2: volatility-adjusted weights
        return self._vol_adjust(raw_signals, data_map)

    def _detect_market(self, code: str) -> str:
        for pattern, market in _MARKET_PATTERNS:
            if pattern.match(code):
                return market
        return "us_equity"

    def _market_signal(self, df: pd.DataFrame, params: dict) -> pd.Series:
        close = df["close"]
        ma_fast = close.rolling(params["ma_fast"]).mean()
        ma_slow = close.rolling(params["ma_slow"]).mean()

        sig = pd.Series(0.0, index=df.index)
        sig[ma_fast > ma_slow] = 1.0
        sig[ma_fast < ma_slow] = -1.0
        return sig

    def _vol_adjust(self, signals: dict, data_map: dict) -> dict:
        vols = {}
        for code, df in data_map.items():
            ret = df["close"].pct_change(fill_method=None).dropna()
            vols[code] = (
                ret.rolling(20).std().iloc[-1]
                if len(ret) > 20
                else ret.std()
            )

        inv_vols = {c: 1.0 / (v + 1e-10) for c, v in vols.items()}
        total_inv = sum(inv_vols.values())

        adjusted = {}
        n = len(signals)
        for code, sig in signals.items():
            weight = inv_vols[code] / total_inv * n
            adjusted[code] = (sig * weight).clip(-1.0, 1.0)
        return adjusted
