---
name: cross-market-strategy
description: Write signal_engine.py for portfolios spanning US and Canadian equity listings, including dual-listed issuers and index/sector mixes.
category: strategy
---

## When to Use

When the user requests a backtest with codes from **different listings** — e.g. `["AAPL", "SHOP.TO"]`, `["RY", "RY.TO"]`, or `["SPY", "XIC.TO"]`.

The `CompositeEngine` handles calendar alignment, shared capital, and market rules automatically. The strategy only needs to output per-symbol signals.

## Key Concepts

### 1. Market Classification in generate()

Group symbols by market type and apply market-specific indicator parameters:

```python
def generate(self, data_map):
    groups = {}
    for code, df in data_map.items():
        market = self._detect_market(code)
        groups.setdefault(market, {})[code] = df

    signals = {}
    for market, market_data in groups.items():
        params = MARKET_PARAMS[market]
        for code, df in market_data.items():
            signals[code] = self._market_signal(df, params)
    return signals
```

### 2. Per-Market Parameter Tables

The US and Canadian listings of the same issuer trade the same business but differ in liquidity, currency and (for the TSXV) volatility. Using the same parameters everywhere produces poor results.

| Parameter | US Equity | Canada (TSX) | Canada (TSXV) |
|-----------|-----------|--------------|----------------|
| MA fast | 10 | 10 | 10 |
| MA slow | 50 | 50 | 50 |
| RSI period | 14 | 14 | 14 |
| Vol lookback | 20 | 20 | 20 |
| Typical daily vol | 1-2% | 1-2% | 2-5% |

### 3. Volatility-Adjusted Weights (Critical)

A TSXV name can run 3-5% daily vol against ~1.2% for a large-cap US name. Without vol-adjustment, the small-cap sleeve eats the entire risk budget.

```python
def _vol_adjust(self, signals, data_map):
    vols = {}
    for code, df in data_map.items():
        ret = df["close"].pct_change(fill_method=None).dropna()
        vols[code] = ret.rolling(20).std().iloc[-1] if len(ret) > 20 else ret.std()

    inv_vols = {c: 1.0 / (v + 1e-10) for c, v in vols.items()}
    total_inv = sum(inv_vols.values())

    adjusted = {}
    for code, sig in signals.items():
        weight = inv_vols[code] / total_inv * len(signals)
        adjusted[code] = (sig * weight).clip(-1.0, 1.0)
    return adjusted
```

**Currency note:** a Canadian listing's price series is in CAD and a US listing's is in USD. Either trade each sleeve in its own currency and report the CAD/USD basis, or convert with a **retrieved** CAD/USD rate and state the rate and its timestamp. Never mix the two silently.

### 4. Cross-Listing Signal Patterns

1. **Relative-value convergence**: for a dual-listed issuer (e.g. `RY` vs `RY.TO`), trade the spread between the two lines when it moves outside its own 60-day range
2. **Risk-on/Risk-off**: VIX term structure + DXY + the 10Y yield as a regime overlay to reduce equity exposure
3. **Hedging**: long US large-cap beta against short Canadian commodity-beta (or the reverse) as a macro hedge
4. **Correlation regime**: when rolling correlation > 0.6, reduce to single-market exposure; when < 0.2, maximize diversification

### 5. What the Engine Handles (Don't Worry About)

- **Trading calendar alignment**: signals are shifted on each symbol's own calendar, then ffill'd to unified dates — the US and Canadian sessions differ on holidays
- **Market rules**: settlement conventions, currency, and per-symbol commission models
- **Capital allocation**: shared pool, strategy just sets target weights via signals
- **Commission/slippage**: dispatched to the correct sub-engine per symbol

**Scope note:** Canada is covered for market data and backtesting only — there is no live Canadian broker path in this build.

## config.json for a Cross-Listing Backtest

```json
{
  "source": "auto",
  "codes": ["AAPL", "SHOP.TO"],
  "start_date": "2024-01-01",
  "end_date": "2025-03-31",
  "interval": "1D",
  "initial_cash": 1000000,
  "engine": "daily"
}
```

- `source` **must** be `"auto"` for a multi-listing backtest (routes each symbol to its loader)
- `extra_fields` should be `null` unless every symbol supports fundamentals
- `leverage` defaults to 1.0 (CompositeEngine inherits from config)

## Market Detection Heuristics

| Pattern | Market |
|---------|--------|
| `AAPL`, `MSFT`, `SPY` | US equity |
| `SHOP.TO`, `RY.TO`, `TD.TO` | Canada equity (TSX) |
| `PNG.V`, `CJT.V` | Canada equity (TSXV) |
| `^GSPC`, `^GSPTSE` | Index |

## Supporting Files

- [example_signal_engine.py](example_signal_engine.py) — complete US/Canada cross-listing strategy example
