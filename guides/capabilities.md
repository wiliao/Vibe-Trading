# Data sources and capabilities

## Data sources

Market-data and backtest tools support US and Canadian equities, ETFs, and US
index series used as benchmarks. US symbols may be bare tickers or use `.US`;
Canadian symbols use `.TO` for TSX and `.V` for TSX Venture.

| Source | Coverage | Credentials |
|--------|----------|-------------|
| `yahoo`, `yfinance` | US and Canada | None |
| `stooq`, `sina`, `eastmoney` | US | None |
| `finnhub`, `alphavantage`, `tiingo`, `fmp` | US | Provider API key |
| `local` | User-provided data for supported symbols | None |
| `auto` | Selects the configured chain for the symbol's market | Depends on available sources |

Fallback order is configured per market:

- **US equity** → `yahoo` · `stooq` · `sina` · `eastmoney` · `yfinance` ·
  `tiingo` · `fmp` · `finnhub` · `alphavantage` · `local`
- **Canada equity** → `yahoo` · `yfinance` · `local`
- **US indices** → `yahoo` · `yfinance` · `local`

The `local:` prefix selects user-provided CSV, Parquet, or DuckDB data and never
falls back to a network source. Source-specific availability and credentials
are reported with the returned market-data provenance.

## Research tools

`get_market_data` retrieves normalized OHLCV bars. Stock research tools also
cover financial statements and SEC filings for US listings, company news,
options, symbol search, market screening, ETF holdings, and SEC institutional
holdings. US and Canadian prices use separate settlement currencies; backtest
metrics do not combine USD and CAD as if they were interchangeable.
