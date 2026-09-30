---
name: minute-analysis
description: Minute-level data analysis and backtesting. Retrieves minute candlesticks through yfinance / the Yahoo Finance chart API for US and Canadian equities, and can be used both for analysis and as input to the backtest engine.
category: strategy
---
# Minute-Level Data Analysis and Backtesting

## Purpose

Retrieve minute-level candlestick data through the market-data loaders and calculate intraday indicators (VWAP, TWAP, volume distribution, and more).
Supports minute-level backtesting: set `"interval": "5m"` in `config.json` and use the `backtest` tool to run intraday strategies.

## Backtest Configuration

For minute-level backtests, simply add the `interval` field in `config.json`:

```json
{
  "source": "yfinance",
  "codes": ["AAPL"],
  "start_date": "2026-03-01",
  "end_date": "2026-03-15",
  "interval": "5m",
  "initial_cash": 1000000,
  "commission": 0.0005
}
```

- The annualization factor is inferred automatically from `source + interval` (`yfinance 5m = 252 x 78 = 19656` bars per year on a US session)
- Minute-level datasets are large. Recommended time limits: no more than 7 days for `1m`, no more than 30 days for `5m`, and no more than 1 year for `1h`

## Supported Data Sources and Intervals

| Data Source | Supported Intervals | Notes |
|--------|---------|------|
| yfinance / Yahoo Finance | 1m/2m/5m/15m/30m/1h | US and Canadian equities. Intraday history is limited by the API: roughly 7 days per request for `1m`, ~60 days for `5m`-`30m`, longer for `1h`. Verify against the live API before promising a window |
| local | any interval present in the file | Offline CSVs you already hold |
| stooq | daily and above | Daily fallback only; no intraday |

## Yahoo Finance Minute Candlestick API

```python
import requests
import pandas as pd

resp = requests.get(
    "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
    params={"range": "5d", "interval": "1m"},
    headers={"User-Agent": "Mozilla/5.0"},
)
result = resp.json()["chart"]["result"][0]
quote = result["indicators"]["quote"][0]
df = pd.DataFrame(
    {
        "open": quote["open"],
        "high": quote["high"],
        "low": quote["low"],
        "close": quote["close"],
        "vol": quote["volume"],
    },
    index=pd.to_datetime(result["timestamp"], unit="s"),
)
df.index.name = "ts"
df = df.dropna(subset=["open", "high", "low", "close"])
```

## Indicator Calculation Templates

### VWAP (Volume-Weighted Average Price)

```python
typical_price = (df["high"] + df["low"] + df["close"]) / 3
df["vwap"] = (typical_price * df["vol"]).cumsum() / df["vol"].cumsum()
```

### TWAP (Time-Weighted Average Price)

```python
df["twap"] = df["close"].expanding().mean()
```

### Volume Distribution

```python
df["vol_pct"] = df["vol"] / df["vol"].sum() * 100
hourly_vol = df.set_index("ts").resample("1h")["vol"].sum()
```

## Parameters

| Parameter | Description |
|------|------|
| symbol | US / Canada ticker, such as `"AAPL"` or `"SHOP.TO"` |
| interval | Candlestick interval: `1m/2m/5m/15m/30m/1h` |
| limit / range | Number of records or lookback window to retrieve |

## Common Pitfalls

- Intraday history is capped by the vendor. A `1m` request cannot reach back years; state the window you actually retrieved
- The time range for minute-level backtests should not be too long, otherwise both data retrieval and backtesting will become slow or time out
- Regular-session bars only: Yahoo returns the 9:30-16:00 ET session for US names, so pre/post-market flow is not in the series unless you explicitly request it
- Timestamps are Unix timestamps in seconds and should be converted with `unit="s"`
- Transaction costs for minute strategies should be set lower (for example 0.05% instead of 0.1%) because intraday trading is frequent — but the spread and impact assumptions from the execution model must still hold
- Data for a Canada-only listing can be thinner and have gaps; drop the empty bars rather than forward-filling them

## Dependencies

```bash
pip install pandas numpy requests
```
