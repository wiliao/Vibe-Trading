# QVeris Coverage Map

This map condenses the 2026-07-07 Vibe-Trading design evidence. The measured
sample ran 20 finance-domain searches at `limit=50`; every search hit the
50-result cap. Deduplicated sample coverage was 841 tools across 63 providers.
QVeris also markets "10,000+ capabilities" across 15+ categories; cite that as
"10,000+ capabilities (per QVeris)".

## Provider Head List

Observed head providers and counts from the design sample, restricted to the
US/Canada equity surface this build covers:

| Provider | Sample count | Strong fit |
|----------|--------------|------------|
| FMP | 79 | US/global equities, fundamentals, calendars, ratios. |
| AlphaVantage | 75 | Equities, fundamentals, macro-style time series. |
| TwelveData | 62 | Market data and technical/time-series endpoints. |
| Census | 36 | Official US economic/demographic data. |
| Finnhub | 35 | Equities, news, filings, estimates, company data. |
| EODHD | 27 | End-of-day global equity data. |
| ThetaData | 25 | US options chains, implied volatility, Greeks. |
| Other observed providers | part of 63 total | FRED, US Treasury, SEC, Tiingo, Yahoo, Tradier, and additional marketplace providers. |

The sample also contained providers whose coverage sits outside this build's
US/Canada equity scope. They are out of scope here: do not route to them.

The full 63-provider raw file is not committed in this repo. Do not invent a full
provider list from memory; use the observed head list above plus live search
results from `qveris_search`.

## Category Routing

| Category | Representative tools/providers | Typical cost range | Route to QVeris when | Prefer free Vibe-Trading sources when |
|----------|--------------------------------|--------------------|----------------------|---------------------------------------|
| US/Canada equities OHLCV | FMP, AlphaVantage, TwelveData, EODHD, Yahoo | 1-24.2 credits/call | The user asks for a paid provider, broader breadth, or a source not covered by free loaders. | Routine OHLCV can use `source:"auto"` with yahoo/stooq/sina/eastmoney/yfinance/free fallbacks. |
| Fundamentals and financial statements | FMP, Finnhub, AlphaVantage, SEC | 1-24.2 credits/call | Cross-provider comparison or premium vendor ratios are needed. | US SEC facts and issuer filings are available through built-in read-only tools. |
| SEC filings and institutional data | SEC, Finnhub, FMP | 1-24.2 credits/call | Marketplace convenience or 13F/filing enrichment is needed. | Official SEC filings/companyfacts should stay on built-in SEC tools when sufficient. |
| News and sentiment | Finnhub, FMP, AlphaVantage, web-search providers | 1-24.2 credits/call | Paid sentiment/news feeds or broad provider comparison are needed. | Basic stock news and web context can use built-in `get_stock_news` / `web_search`. |
| Earnings calendar and analyst estimates | Finnhub, FMP, AlphaVantage | 1-24.2 credits/call | The user needs estimates, surprises, or vendor calendars. | Avoid paid calls if the task only needs high-level narrative or public filings. |
| ETF holdings and fund data | FMP, AlphaVantage, market-data providers | 1-24.2 credits/call | Holdings/constituents are not in free tooling or need vendor consistency. | Basic OHLCV and many fund flows can use free loaders/tools. |
| Options chains, IV, Greeks | ThetaData, Tradier, Yahoo, FMP | 1-24.2 credits/call | Greeks, implied volatility surfaces, or specialist options data are required. | Basic US options chains can start with built-in `get_options_chain`. |
| Rates and macro | AlphaVantage, TwelveData, US Treasury, FRED | 1-24.2 credits/call | Paid rate granularity or provider-specific fields are needed. | Built-in macro and Treasury sources are preferred when they cover the series. |
| Macro official data | FRED, Census, US Treasury | 1-24.2 credits/call | One key should access many official-style sources through one interface. | Built-in FRED macro is preferred when it covers the series and key is configured. |
| Corporate actions | FMP, AlphaVantage, EODHD | 1-24.2 credits/call | Dividends, splits, IPO, or vendor-adjusted history is missing in free sources. | Use free loaders for simple adjusted/unadjusted OHLCV where adequate. |
| Short interest and alternative data | Finnhub/FMP-style feeds, marketplace providers | 1-24.2 credits/call | The data class is absent from built-in tools. | Use built-in data only when it directly covers the requested metric. |

## Agent Policy

- Start with free Vibe-Trading sources for routine OHLCV and official/free tools.
- Use QVeris for paid breadth, specialist data, and provider comparison.
- Always inspect before execute.
- Rank paid candidates by `stats.success_rate`, `expected_cost`, provider fit,
  and parameter clarity.
- Tell the user when a result is single-source or when provider quality varies.
- Failed, empty, and parameter-error executions are expected not to charge; keep
  `execution_id`, `charge_outcome`, `reason_code`, `cost`, and
  `remaining_credits` in the evidence trail.
