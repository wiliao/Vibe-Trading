---
name: data-routing
category: data-source
description: The single ROUTER for every data need. Load this skill BEFORE any backtest, data-fetch, or research task to pick the best available source/tool, honour auth (env) requirements, and avoid ban-risk providers.
---
# Data Routing (Router)

This is the one router. It maps (a) every registered backtest data **source** to its
markets / auth / skill, and (b) every research **data need** to the concrete **tool**
that serves it, its market, and the env key it requires. The supported universe is
**US and Canadian equities plus indices**; source names below are a strict subset of
`backtest.loaders.registry.VALID_SOURCES` (enforced by
`tests/test_data_routing_sources_subset.py`).

## Source Overview

Every name here is a registered OHLCV/backtest source in `VALID_SOURCES`.
"Runner-internal" sources are selected by the backtest runner, not authored as a
per-source skill.

| Source | Markets | Auth (env key) | Network | Skill |
|--------|---------|----------------|---------|-------|
| yahoo | US + Canada equities, indices | No (IP-throttled) | Needs Yahoo access | data-routing |
| yfinance | US + Canada equities, indices | No | Needs Yahoo access | yfinance |
| stooq | US equities (daily OHLCV) | No | Unrestricted | data-routing |
| sina | US equities (daily OHLCV) | No (IP-throttled) | Unrestricted | data-routing |
| eastmoney | US equities (daily OHLCV) | No (IP-throttled) | Unrestricted | data-routing |
| tiingo | US equities | Yes (`TIINGO_API_KEY`) | Unrestricted | data-routing |
| fmp | US equities | Yes (`FMP_API_KEY`) | Unrestricted | data-routing |
| finnhub | US equities | Yes (`FINNHUB_API_KEY`) | Unrestricted | data-routing |
| alphavantage | US equities | Yes (`ALPHAVANTAGE_API_KEY`) | Unrestricted | data-routing |
| local | US + Canada equities, indices (user CSV/parquet) | No | Offline | data-routing (runner-internal) |

Free with no key: `yahoo` / `yfinance` (US + Canada equities and indices),
`stooq` / `sina` / `eastmoney` (US daily OHLCV) and `local` (your own files).
Key-gated: `tiingo`, `fmp`, `finnhub`, `alphavantage` (US only). `source: "auto"`
is the cross-market selector, not a source of its own.

## Capability → Tool Routing

Pick the tool by the data need. "Market" is the universe the tool covers; "Env key"
is required only where listed (no key listed = free / no auth).

| Data need | Tool | Market | Env key |
|-----------|------|--------|---------|
| OHLCV price bars | `get_market_data` | US / Canada / index | per-source (see Source Overview) |
| Fund flow | `get_fund_flow` | US | — |
| Stock news | `get_stock_news` | US | — |
| SEC filings (EDGAR) | `get_sec_filings` | US | — |
| Financial statements | `get_financial_statements` | US | — |
| Options chain | `get_options_chain` | US | — |
| Stock profile / fundamentals | `get_stock_profile` | US / Canada | — |
| PIT-safe fundamentals panels | `get_fundamentals` | US | — |
| Institutional holdings (13F) | `get_institutional_holdings` | US | — |
| ETF look-through | `etf_holdings` | US | — |
| Market screen | `screen_market` | US | — |
| Symbol search | `search_symbol` | US / Canada / index | — |
| Technical indicators | `technical_indicators` | US / Canada / index | — |
| Broker quote snapshot | `trading_quote` | selected connector profile | Connector app / OAuth |
| Broker historical bars | `trading_history` | selected connector profile | Connector app / OAuth |
| Macro / FRED series | `get_macro_series` | Macro (US / global) | `FRED_API_KEY` |

Notes:
- `get_financial_statements` reads US statements from SEC EDGAR companyfacts
  (ticker -> CIK -> XBRL concepts). Canadian issuers file on SEDAR+, which is not
  wired to this tool, so use `local` statement data for them.
- `get_stock_news` fetches US-listed headlines from a Yahoo Finance search client;
  a failure on the upstream is returned as an error envelope, never raised, so a
  single bad symbol never aborts a batch.
- `screen_market` screens the **US** universe only; Canada has no screener here.
- `technical_indicators` and `get_market_data` read through the same loader layer,
  so their fallback behaviour and `_provenance` stamps are identical.

## Decision Tree

### Backtest scenario (writing config.json)

Use `source: "auto"` — the runner routes by symbol pattern and falls back across
same-market sources automatically. Only set a concrete source when the user asks.

### Analysis / research scenario

1. Identify the data need, then read the Capability table for the tool + env key.
2. If the need is plain OHLCV, call `get_market_data` and let source fallback run.
3. Set any required env key before calling a key-gated tool; if it is missing,
   report the missing key rather than failing silently.

### Source priority (for OHLCV by market)

These chains are exactly `backtest.loaders.registry.FALLBACK_CHAINS`; the first
available source wins.

- **US equities (`us_equity`)**: yahoo > stooq > sina > eastmoney > yfinance >
  tiingo > fmp > finnhub > alphavantage > local.
- **Canada equities (`ca_equity`, TSX `.TO` / TSXV `.V`)**: yahoo > yfinance > local.
- **Indices (`index`, Yahoo `^` symbols)**: yahoo > yfinance > local.

`yahoo` / `yfinance` are free and lead both equity markets and indices. `stooq`,
`sina` and `eastmoney` are free US EOD fallbacks. `tiingo`, `fmp`, `finnhub` and
`alphavantage` are US-only key-gated REST sources and trail the free ones. `local`
is last everywhere and, like an explicit `fmp`, never silently degrades to a
network source — an unavailable `local` is a Data Bridge config problem the user
must see.

## Symbol Format Reference

| Market | Format | Examples |
|--------|--------|----------|
| US equity | `TICKER` or `TICKER.US` | AAPL, AAPL.US, MSFT.US |
| Canada equity (TSX / TSXV) | `TICKER.TO` / `TICKER.V` | TD.TO, BBD-B.TO, PNG.V |
| Index | `^SYMBOL` | ^GSPC, ^GSPTSE, ^NDX, ^VIX |

US tickers may be written bare (`AAPL`) or suffixed with the project's `.US`
convention; Canada always carries Yahoo's canonical `.TO` (TSX) or `.V` (TSXV)
suffix; indices keep Yahoo's leading `^`.

## Ban-Risk & Fallback Notes

- **Eastmoney rate-limits by IP and must be throttled.** Every Eastmoney-backed
  loader routes through the shared per-host throttle; do not hammer it. On a
  throttle/timeout, fall back to the next US source in the chain (stooq / sina /
  yahoo).
- **Sina / Yahoo also throttle by IP** — same per-host wrapper, same fallback rule.
- **Key-gated sources need their env key** (`TIINGO_API_KEY`, `FMP_API_KEY`,
  `FINNHUB_API_KEY`, `ALPHAVANTAGE_API_KEY`, `FRED_API_KEY`). If the key is absent
  the tool/loader is unavailable — route to a free same-market source instead of
  erroring out.
- A single failing symbol or transient HTTP error is reported inside the envelope;
  it never aborts the surrounding batch.

## Data Verification Discipline

When a number will drive a conclusion (valuation, screening, report), do not trust a
single source. Cross-check it:

- **Verify material figures across ≥2 independent sources** before citing them.
  Prioritize original disclosures (company annual/quarterly reports, exchange filings)
  over third-party aggregators.
- **Flag any deviation >1%** between sources as a ⚠️ caliber mismatch — usually a
  definition difference (GAAP vs Non-GAAP, consolidated vs parent-only, currency,
  TTM vs annual). Do not silently pick one; state both and which you adopt.
- **Use the `financial_rigor` tool's `cross_validate` command** to do this exactly:
  pass `{source: value, ...}` and it returns the median consensus + per-source
  deviation + an `all_consistent` flag at a configurable tolerance (default 2%).
- **Mark unverified numbers** as "single-source" or "estimate" — never present an
  uncorroborated figure as established fact.

This discipline is what separates analysis from aggregation.
