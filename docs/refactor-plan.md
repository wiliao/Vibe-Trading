# Refactor Plan — Slim `vibe-trading-us-ca` to US + Canada Equity

**Status:** proposal, not started
**Owner:** _(fill in)_
**Base:** `wiliao/Vibe-Trading` @ `vibe-trading-us-ca` (upstream `HKUDS/Vibe-Trading`, fork of 2026-09-28)
**Scope:** remove every market, loader, engine, broker, tool, and prompt surface that is not US or Canada equity.

> **Note on this file's location.** `docs/` is gitignored (`.gitignore:123-127`, "Internal docs (plans, specs)"). This plan is therefore a local working document. Add it to the repo with `git add -f docs/refactor-plan.md` if it should be shared.

---

## 1. Goal and non-goals

### Goal

Make the repository support exactly two settlement markets — **US equity** (`us_equity`, USD) and **Canada equity** (`ca_equity`, CAD, TSX `.TO` / TSX Venture `.V`) — and delete the rest. "Slim" means:

- fewer data loaders shipped and imported,
- fewer backtest engines and market rule modules,
- fewer broker connectors and live-trading branches,
- fewer agent tools, skills, prompts, and UI strings that name other markets,
- a test suite that covers the supported surface instead of 15 markets.

### Non-goals

- Changing the agent architecture, LLM layer, session store, or the swarm/governance stack.
- Dropping non-English **UI** locales (9 frontend, 5 desktop). That is an i18n decision with a much larger diff; Section 9 lists it as a separate, optional workstream.
- Rewriting `CHANGELOG.md` history. It is a record of what shipped; it stays as-is.
- Adding new capability. Everything below is removal or rewiring.

### Definition of "US + Canada equity" for this plan

| In scope | Out of scope |
|---|---|
| US listings: bare tickers, `AAPL.US`, `BRK.B.US` | China A-share `600519.SH`, HK `0700.HK`, India `RELIANCE.NS`, Korea `005930.KS`, Vietnam `VIC.VN`, Argentina `.BA`, UK `.L` |
| Canada listings: `TD.TO`, `SHOP.TO`, `PNG.V` | Crypto pairs (`BTC-USDT`, `BTCUSDT`, `BTC-USD`, `BTCIRT`) |
| Equity instruments and ETFs | Futures (`ES.CME`, `RB2410.SHFE`), forex (`EUR/USD`, `XAUUSD=X`), CFFEX/global futures |
| US index/breadth data used as benchmark input (`^SPX`, `^GSPC`, `^VIX`) — **decision D1** | `macro` / `fund` markets served by `akshare`/`tushare` |
| US fundamentals (SEC EDGAR, FMP, AlphaVantage, Tiingo, Finnhub) | `qveris` premium aggregator |

---

## 2. Current state

### 2.1 Size

| Area | Measure |
|---|---|
| `agent/src/**/*.py` | 945 files, ~201,300 lines |
| `agent/backtest/**/*.py` | 85 files |
| `agent/tests/**/test_*.py` | 711 files |
| Bundled skills | 90 × `SKILL.md` |
| Factor zoo modules | 467 (`alpha101` 102, `gtja191` 192, `qlib158` 155, `academic` 13, `fundamental` 5) |
| Data loaders registered | 28 sources (`VALID_SOURCES`, `agent/backtest/loaders/registry.py:36-63`) |
| Markets declared | 15 keys (`FALLBACK_CHAINS`, `agent/backtest/loaders/registry.py:178-241`) |
| Broker connectors | 18 packages under `agent/src/trading/connectors/` |
| IM channels | 16 adapters under `agent/src/channels/` |
| Frontend | 184 files under `frontend/src/`, 9 locale JSON files |

### 2.2 Where "a market" is declared

There is no market enum. A market exists only as a row in six independent tables, which must be changed together:

| # | Table | Path | Count |
|---|---|---|---|
| 1 | `FALLBACK_CHAINS` — market → ordered sources | `agent/backtest/loaders/registry.py:178-241` | 15 |
| 2 | `_MARKET_CURRENCY` — market → currency | `agent/backtest/engines/_market_hooks.py:163-181` | 10 |
| 3 | `_MARKET_PATTERNS` — symbol regex → market | `agent/backtest/engines/_market_hooks.py:51-160` | ~30 regexes |
| 4 | `_SOURCE_PATTERNS` — symbol regex → preferred source | `agent/src/market_data.py:21-63` | ~20 regexes |
| 5 | `MARKET_BENCHMARKS` — market → benchmark ticker | `agent/backtest/benchmark.py:22-31` | 7 |
| 6 | `MARKET_DATA_ORDER_*` — env-configurable order | `agent/src/config/env_schema.py:255-269` | 15 |

Plus two duplicate symbol classifiers that already drift: `infer_market()` in `agent/backtest/correlation.py:20-70` and the suffix maps in `agent/src/tools/symbol_search_tool.py:138-166`, `agent/src/agent/grounding/identity.py:241-330`, `agent/src/portfolio/service.py:49`, and `frontend/src/lib/positions.ts:39-62`.

### 2.3 Where a market is *enforced*

| Layer | Path | What it does |
|---|---|---|
| Engine selection | `agent/backtest/runner.py:1513-1608` | codes → engine class |
| Cross-market routing | `agent/backtest/engines/composite.py:27-83` | market → rule sub-engine |
| Loader resolution | `agent/backtest/loaders/registry.py:561` `resolve_loader()` | market → first available source |
| Factor universes | `agent/src/factors/base.py:44-52` (`Market` enum), per-alpha `"universe"` metadata | which alphas a panel can run |
| Live gate asset classes | `agent/src/live/mandate/model.py:34-42`, `agent/src/live/enforcement.py:58-66` | which instruments a mandate permits |
| Live market hours | `agent/src/live/runtime/triggers.py:96-110` (`MARKET_SPECS`) | when market-triggered actions may fire |
| Connector registry | `agent/src/trading/profiles.py:28-46`, `agent/src/live/registry.py:26-70` | which brokers exist |

### 2.4 Known gaps in the current Canada support

These are pre-existing holes that the refactor must close, not create:

1. **No `CA_EQUITY` asset class.** `AssetClass` (`agent/src/live/mandate/model.py:34-42`) has `US_EQUITY, US_ETF, HK_EQUITY, CN_EQUITY, IN_EQUITY, CRYPTO, FOREX` — no Canada.
2. **No Canada row in `_ASSET_CLASS_MARKET`** (`agent/src/live/enforcement.py:58-66`).
3. **No `ca_equity` entry in `MARKET_SPECS`** (`agent/src/live/runtime/triggers.py:96-110`) — only `us_equity` and `crypto`. A Canada market-triggered rule cannot be evaluated for trading hours.
4. **No Canada-capable broker connector.** IBKR is the only built-in connector that can reach Canadian venues; Alpaca, Robinhood, Tiger, Longbridge, and Futu are US/HK/CN.
5. **`agent/src/trading/onboarding.py:52-204`** has no `_BUILTIN` entry for `ibkr`, `robinhood`, `zerodha`, or `scalable`; those fall through to generic handling.

Canada today is **market-data + backtest only**. The plan must state explicitly whether that stays true (decision **D3**).

---

## 3. Target state

After the refactor:

- **Markets:** `us_equity`, `ca_equity` (the two settlement markets), plus the region-neutral `index` chain for `^SPX`/`^GSPC`/`^VIX` benchmark inputs (decision **D1**). Everything else gone.
- **Loaders registered:** `yahoo`, `yfinance`, `stooq`, `sina`, `eastmoney` (US only), `local`, plus the key-gated US REST sources `finnhub`, `alphavantage`, `tiingo`, `fmp`. Optional: `akshare`/`longbridge` US-only branches (decision **D2**).
- **Engines:** `GlobalEquityEngine` (parameterised `market="us" | "ca"`) and `CompositeEngine` reduced to a US/CA router — the `index` key (D1) folds into `GlobalEquityEngine(market="us")`. Ordering/execution rule modules for other markets deleted.
- **Brokers:** `alpaca`, `ibkr`, `robinhood`, `tiger`, `longbridge`, `futu` (reconfigured to US), `etoro` (decision **D4**). India/Korea/EU/crypto connectors deleted.
- **Tools:** SEC/options/fundamentals/market-data/search/backtest/trading kept; the 11 A-share + Taiwan tools deleted.
- **Universe:** `gtja191` deleted (A-share only); `alpha101` / `qlib158` / `academic` / `fundamental` universe lists trimmed to `equity_us` where they can run on a US panel.
- **Frontend:** market enumerations reduced to `us_equity` / `ca_equity` / `other`; A-share welcome examples and Correlation defaults replaced with US/CA ones.
- **A scope gate in CI** that fails if a removed market string returns.

---

## 4. Strategy decision: delete vs. gate

**Decision D0 — recommended: hybrid, leaning delete.**

| Option | Diff size | Upstream sync | Runtime surface |
|---|---|---|---|
| A. Hard delete | Largest | Broken; every upstream merge conflicts in the touched tables | Smallest |
| B. Capability gate (keep code, disable via config) | Small | Clean | Unchanged — all code still imported, all deps still installed |
| **C. Hybrid (recommended)** | Large | Painful but bounded to the six tables in §2.2 | Small |

Option C means: **hard-delete** region-only modules (loaders, engines, connectors, tools, skills — files that nothing US/CA imports), but **keep** the shared dispatch tables (`FALLBACK_CHAINS`, `_MARKET_PATTERNS`, `_SOURCE_PATTERNS`, `MARKET_BENCHMARKS`, `AssetClass`) as tables with only the US/CA rows, so the shape of the code is unchanged and future upstream merges conflict in a small, reviewable region.

The rest of this plan assumes Option C. If Option A is chosen, Phases 1-3 additionally delete the table rows and the classifier branches rather than trimming them.

> **Upstream-sync impact must be acknowledged.** This fork tracks `HKUDS/Vibe-Trading`. Upstream merges ~150 PRs per release cycle and those PRs routinely touch loaders, engines, connectors, the README news log, and the six tables above. Deleting files makes `git merge upstream/main` produce large conflicts. Recommended mitigation: keep this refactor on its own long-lived branch, and re-run the deletion phases (which are mostly mechanical) after each upstream sync rather than trying to merge deletions forward. Record the deletion set as a script (Phase 1, step 3) so it is replayable.

---

## 5. Workstreams

Ten phases. Each is independently reviewable and leaves the tree green.

### Phase 0 — Baseline, branch, and guardrails

**Why first:** the refactor touches ~700 test files; without a recorded baseline, "did I break US/CA?" is unanswerable.

1. Create branch `refactor/us-ca-only` off `vibe-trading-us-ca`.
2. Record the US/CA-relevant baseline before any deletion:
   ```
   pnpm --version  # not used here; this is a Python repo
   PYTHONPATH=agent python -m pytest agent/tests -q --timeout=600 2>&1 | tail -40
   ```
   Save the pass/fail/skip summary and the list of currently-failing tests to `docs/baseline-tests.txt`. _Do not_ treat a red baseline as a blocker; the repo currently ships 711 test files and locale/loader tests are environment-sensitive.
3. Write the **scope gate** (Phase 10, item 1) as a *failing* xfail first, so it starts green only when the work is done.
4. Freeze the file inventory: `git ls-files > docs/inventory-before.txt`.

**Exit criteria:** baseline recorded; branch created; nothing else changed.

---

### Phase 1 — Data plane core: markets, symbols, chains

**Files:** `agent/backtest/loaders/registry.py`, `agent/backtest/engines/_market_hooks.py`, `agent/src/market_data.py`, `agent/backtest/correlation.py`, `agent/src/config/env_schema.py`.

1. **Trim `FALLBACK_CHAINS`** (`registry.py:178-241`) to:
   ```python
   "us_equity": ["yahoo", "stooq", "sina", "eastmoney", "yfinance", "tiingo", "fmp", "finnhub", "alphavantage", "local"],
   "ca_equity": ["yahoo", "yfinance", "local"],
   "index": ["yahoo", "yfinance", "local"],   # kept per decision D1 (^SPX/^VIX benchmark input)
   ```
   Keep `local` in both — it is the user's own CSV path and is currency-agnostic. Remove `a_share`, `hk_equity`, `india_equity`, `kr_equity`, `ar_equity`, `uk_equity`, `vietnam_equity`, `crypto`, `futures`, `fund`, `macro`, and `forex`. `index` is retained per decision **D1** — it is US-native benchmark input, not a settlement market.
2. **Trim `VALID_SOURCES`** (`registry.py:36-63`) and `_loader_modules` (`:78-130`) to the surviving set. The test `test_valid_sources_covers_all_registered_loaders` enforces that these two stay in sync.
3. **Extract the deletion set into a replayable script** — `agent/scripts/us_ca_prune.py` (or `scripts/us-ca-prune.sh`) listing every path this plan deletes with a one-line reason. This is what makes re-running the refactor after an upstream sync cheap.
4. **Trim `_MARKET_CURRENCY`** (`_market_hooks.py:163-179`) to `us_equity: USD`, `ca_equity: CAD`. Remove `hk_counter_currency` (`:209`), `_HK_COUNTER_CURRENCY_RANGES` (`:195`), `_FUTURES_EXCHANGE_CURRENCY` (`:185`), and the now-orphaned `_HK_CODE` (`:206`) once their callers are gone.
5. **Trim `_MARKET_PATTERNS`** (`_market_hooks.py:51-160`) to keep only:
   - `^[A-Z0-9&.\-]+\.US$` → `us_equity`
   - `^[A-Z0-9&.\-]+\.(TO|V)$` → `ca_equity`
   - the bare-ticker rule `^[A-Z]{1,5}$` → `us_equity` (must stay last)
   - Remove `_CN_FUTURES_PRODUCTS` (`:31`), `_is_china_futures`, and the now-orphaned `_CHINA_EXCHANGES` (`:152`) / `_EXCHANGE_ALIASES` (`:156`).
6. **Change the fallback default** from `"a_share"` (`_market_hooks.py:298`) to an explicit rejection. A code that matches no pattern in a US/CA-only build is a user error, not an A-share; failing loud is the correct behaviour and matches the repo's "misconfiguration fails loud" convention.
7. **Same for `detect_source()`** (`agent/src/market_data.py:67-73`): default `"tushare"` → raise or return `"yahoo"`. Trim `_SOURCE_PATTERNS` (`:21-63`) to `.US` → `yahoo`, `.TO`/`.V` → `yahoo`, `local:`, `^index`. Delete the `nobitex`/`wallex`/`okx`/`ccxt`/`mt5`/`pykrx` rows.
8. **Keep** `_CA_SUFFIX_RE` / `_ca_venue_sibling` (`agent/src/market_data.py:130-146`, used at `:431-483`) — this is the `.TO`↔`.V` venue-alias fallback and is the one piece of Canada-specific routing that must survive intact.
9. **Fix or delete `infer_market()`** (`agent/backtest/correlation.py:20-70`). It is a second, hand-rolled classifier that has already drifted from `_detect_market`. Preferred: make it call `_detect_market` so there is one source of truth. Fallback: trim its suffix table to `.US`/`.TO`/`.V`.
10. **Trim `DataConfig`** (`env_schema.py:255-269`) to `market_data_order_us_equity`, `market_data_order_ca_equity`, and `market_data_order_index` (kept per **D1**). Remove `tushare_token`, `gildata_token`, `qveris_api_key`, `tickerall_api_key`, `longbridge_*` once their loaders go. Keep `fmp_api_key`, `tiingo`, `finnhub`, `alphavantage`, and `fred_api_key` (macro tool, region-neutral).
11. **Update `agent/tests/conftest.py:87-98`**, which scrubs `MARKET_DATA_ORDER_*` for the whole session — it hardcodes the 15-field list.
12. **Update `agent/src/api/settings_routes.py`**: `_build_source_orders` (`:408-435`) iterates `registry._DEFAULT_CHAINS`, so it follows automatically; verify `_validate_source_order_update` (`:438-470`) still accepts a permutation of the two remaining chains.

**Exit criteria:** importing `backtest.loaders.registry` yields exactly the US/CA chains plus the `index` chain (D1); `_detect_market("AAPL")`, `("AAPL.US")`, `("TD.TO")`, `("PNG.V")`, `("^SPX")` are correct and `_detect_market("600519.SH")` fails loud.

---

### Phase 2 — Data loaders

**Directory:** `agent/backtest/loaders/` (42 files; 28 registered loaders).

| Action | Files | Note |
|---|---|---|
| **Keep** | `base.py`, `registry.py`, `_http.py`, `_symbol_utils.py`, `local_loader.py`, `yahoo_loader.py`, `yahoo_client.py`, `yfinance_loader.py`, `stooq_loader.py`, `sina_loader.py`, `finnhub_loader.py`, `alphavantage_loader.py`, `tiingo_loader.py`, `fmp_loader.py` | `yahoo`/`yfinance`/`local` serve both markets |
| **Keep, constrain to US** | `eastmoney_loader.py`, `akshare_loader.py`, `longbridge.py` | drop their `a_share`/`hk_equity`/`futures`/`fund`/`macro`/`forex` entries from the `markets` set; keep `us_equity` only. Pending decision **D2** |
| **Delete** | `tushare.py`, `tushare_fundamentals.py`, `baostock_loader.py`, `mootdx_loader.py`, `tencent_loader.py`, `gildata_loader.py`, `futu.py`, `india_broker_loader.py`, `pykrx_loader.py`, `okx.py`, `binance_loader.py`, `ccxt_loader.py`, `nobitex.py`, `wallex.py`, `mt5_loader.py`, `tickerall_loader.py`, `qveris_loader.py`, `cn_adjust.py`, `eastmoney_client.py` (if unused by the US path) | 18-19 files |
| **Review** | `fundamentals_loader.py`, `_fundamental_schema.py`, `tushare_fundamentals.py`, `sec_edgar_client.py`, `sec_frames.py`, `rsshub_events.py` | SEC/fundamentals path is US-required; `tushare_fundamentals.py` is not |
| **Cache** | `base.py:469` `_LOADER_CACHE_VERSION = 7` | Bump to 8. Cached frames keyed by the old source set can otherwise be served into a build whose chain no longer contains their source. |

Also required:

1. **`pyproject.toml` package data** (`[tool.setuptools.package-data]`) and `[project.optional-dependencies]`: delete `longbridge`, `mt5`, `zerodha`, `upbit`, `krx`, `ashare` extras. Delete `tushare`, `akshare`, `ccxt` from base `dependencies` (pending **D2**).
2. **`tools/requirements-loader-health.txt`** currently installs `akshare`, `baostock`, `mootdx`, `pykrx`, `ccxt`, `yfinance` → trim to `yfinance` (+ pandas/numpy/requests/pydantic/PyYAML/certifi/httpx).
3. **`.github/workflows/loader-health.yml`** probes every public source → trim to the surviving US/CA chain.
4. **`agent/requirements.txt:34-40`** lists `tushare`, `akshare`, `ccxt` under "Data Providers" → update. Regenerate `requirements-lock.txt` and `requirements-channels-lock.txt`.
5. **`agent/SKILL.md`** states "28 sources" and "10 engines" — recount after this phase.

**Exit criteria:** `python -c "from backtest.loaders.registry import FALLBACK_CHAINS; print(FALLBACK_CHAINS)"` shows only the US/CA chains plus `index`; every surviving loader declares `markets ⊆ {us_equity, ca_equity}`; no `tushare`/`akshare` import remains in a US/CA code path.

---

### Phase 3 — Backtest engines and execution rules

**Directory:** `agent/backtest/engines/` (14 files).

| Action | Files |
|---|---|
| **Keep** | `base.py`, `global_equity.py` (already parameterised `market=`, and already used for `us`/`ca`/`hk`/`uk`/`index` — keep only the `us`/`ca` branches), `composite.py`, `_market_hooks.py`, `options_portfolio.py` |
| **Delete** | `china_a.py`, `china_futures.py`, `india_equity.py`, `korea_equity.py`, `vietnam_equity.py`, `crypto.py`, `forex.py`, `futures_base.py`, `global_futures.py` — **9 files** |

Then rewire the two dispatch points:

1. **`agent/backtest/runner.py:1513-1608`** (`_select_engine`): keep the composite branch, the `us_equity`/`ca_equity` `GlobalEquityEngine` branch, the `options_portfolio` branch, and the `index` branch (**D1** keeps it). Delete the `china_futures`/`global_futures`, `forex`, `india_equity`, `korea_equity`, `vietnam_equity`, `crypto`, and `china_a` branches.
2. **`agent/backtest/engines/composite.py:27-83`** (`_build_rule_engines`): reduce to the `us_equity`, `ca_equity`, and `index` (→ `GlobalEquityEngine(market="us")`) branches. The `ar_equity` `raise ValueError(...)` branch becomes an unknown-market rejection.
3. **`_MARKET_TO_SOURCE`** (`runner.py:846-875`): trim to the two markets; the `"tushare"` default (`:875`) must change to a failing default.
4. **`MARKET_BENCHMARKS`** (`benchmark.py:22-31`): keep `us_equity: "SPY"`, `ca_equity: "XIC.TO"`; delete `hk_equity`, `a_share`, `crypto`, `futures`, and `forex`.
5. **Composite currency guard** (`composite.py:87-126`, `_reject_mixed_currency`): this is the mechanism that refuses a USD/CAD mix. It becomes *more* important after slimming, because US+CA is the only remaining cross-currency pair. Keep it, and add a test that a `["AAPL", "TD.TO"]` basket is refused rather than summing USD and CAD.
6. **`agent/backtest/binance_*` / `perpetual_*`** (`binance_account_reconciliation.py`, `binance_shadow_evidence.py`, `binance_tolerance_calibration.py`, `perpetual_evidence.py`, `perpetual_risk.py`): **delete all five**. They are crypto-only.
7. **Annualisation / trading calendars**: `agent/backtest/metrics.py` and any `bars_per_year` table containing China/HK/India/Korea/Vietnam exchange holidays → trim. `agent/src/live/runtime/triggers.py:66-110` keeps `_US_EQUITY_HOLIDAYS`; add a Canadian holiday set if **D3** enables CA live triggers.

**Exit criteria:** `git grep -l "ChinaAEngine\|CryptoEngine\|ForexEngine\|IndiaEquityEngine\|KoreaEquityEngine\|VietnamEquityEngine\|GlobalFuturesEngine\|ChinaFuturesEngine"` matches only tests pending deletion.

---

### Phase 4 — Factor universes, benchmarks, and the alpha zoo

1. **`agent/src/factors/base.py:44-52`** — trim the `Market` enum (`EQUITY_US`, `EQUITY_CN`, `EQUITY_HK`, `EQUITY_IN`, `EQUITY_KR`, `CRYPTO`, `FUTURES`) to `EQUITY_US`. Check every `vwap`/`Market` consumer for a `match` that now needs `assertNever` or a documented default.
2. **Delete `agent/src/factors/zoo/gtja191/`** — 192 files. All 100 declared universes are `["equity_cn"]`; it is A-share only. Also delete `wiki/research-lab/posts/alpha-191-in-2026.html`, the GTJA card copy in `wiki/research-lab/index.html:76-78` and `wiki/alpha-library/index.html:127,147`, the `--universe csi300` examples in `wiki/scripts/build_alpha_library.py:84,211`, and `agent/scripts/w4a_patch_blog.py`.
3. **Trim universes in the remaining zoos:**
   - `alpha101` (102 files): `"universe": ["equity_us", "equity_in", "equity_kr"]` → `["equity_us"]`
   - `qlib158` (155 files): `["equity_us", "equity_cn", "equity_hk", "equity_in", "equity_kr"]` → `["equity_us"]`
   - `academic` (13 files): includes `crypto` in at least one → `["equity_us"]`
   - `fundamental` (5 files): `["equity_us", "equity_cn", "equity_hk"]` → `["equity_us"]`
   This is a mechanical, scriptable edit — write a one-off script rather than 275 hand edits, and commit the script under `agent/scripts/`.
4. **Bench universes:** `agent/src/api/alpha_routes.py:116` `_BENCH_UNIVERSES = {"csi300", "sp500", "btc-usdt"}` → `{"sp500"}`. Same for `agent/src/factors/cli_handlers.py:81` `_UNIVERSE_CHOICES` and the `:107` legacy map, `agent/src/factors/bench_runner.py:151`, `bench_runner_strict.py:334`, `compare_runner.py:102`.
5. **`agent/src/tools/alpha_bench_tool.py`**: delete `_load_csi300_panel` (`:309`), `_CSI300_FETCH_WORKERS` (`:61`), `_CSI300_FALLBACK_CODES` (`:286`), and the `csi300` universe key (`:74`, `:135`). Keep `_load_sp500_panel` and `_SP500_FALLBACK_CODES`.
6. **`agent/src/tools/autopilot_tool.py:185`** `"csi300": ["000300.SH"]` → delete the key.
7. **`agent/src/tools/sdm_register_tool.py:52`** description mentions `CSI300, SP500, BTC` → reword.

**Exit criteria:** `grep -r '"universe"' agent/src/factors/zoo` shows only `["equity_us"]`; `csi300` appears nowhere outside `CHANGELOG.md`.

---

### Phase 5 — Agent tools

`agent/src/tools/__init__.py:34-73` discovers tools by walking the package, so deleting a module removes its tool. No registry list to edit.

**Delete — A-share / Greater China (11 tools + 2 support modules):**

| File | Tool name |
|---|---|
| `block_trades_tool.py` | `get_block_trades` |
| `dragon_tiger_tool.py` | `get_dragon_tiger` |
| `margin_trading_tool.py` | `get_margin_trading` |
| `northbound_tool.py` | `get_northbound_flow` |
| `shareholder_count_tool.py` | `get_shareholder_count` |
| `lockup_expiry_tool.py` | `get_lockup_expiry` |
| `sector_tool.py` | `get_sector_info` |
| `market_screener_tool.py` | `screen_market` (A-share full-market list) |
| `research_reports_tool.py` | `get_research_reports` |
| `iwencai_tool.py` | `iwencai_search` |
| `taiwan_stock_data_tool.py` | `get_taiwan_stock_data` |
| `tushare_fallbacks.py` | (support module) |
| `trade_journal_parsers.py` | keep the parser, delete the A-share code→suffix map (`:29-32`) and `_qualify_a_share` (`:278`) |

`market_screener_tool.py` deserves a second look: `screen_market` is a *useful* capability (screen a market by fundamentals/price). If a US screen is wanted, rewrite it against the SP500 universe instead of deleting it. **Decision D5.**

**Keep, but strip the dead branches:**

| File | Action |
|---|---|
| `fund_flow_tool.py` | keep US branch; drop A-share/HK |
| `financial_statements_tool.py:666` | keep `us`/SEC path; drop `a_share`/`hk`/`uk` suffix branches |
| `stock_news_tool.py:40-45` | keep Yahoo US; drop the Eastmoney/`.SH`/`.SZ`/`.BJ` and `.HK` paths |
| `etf_holdings_tool.py` | keep SEC path; drop Eastmoney A-share |
| `symbol_search_tool.py:138-166` | trim `_MARKET_BY_SUFFIX` to `US`, `TO`, `V`; trim `_EASTMONEY_SUFFIX_BY_MARKET`; **keep `_CANADIAN_SYMBOL_RE:56`** |
| `shadow_account_tool.py:211` | default markets `("china_a","hk","us","crypto")` → `("us","ca")`; same for `shadow_account/extractor.py:52-58` |
| `research_papers_tool.py:210-212` | drop JP/KR/IN market tags |
| `web_search_tool.py:36` | Aliyun IQS is a China-hosted provider; review whether to keep as a search backend (**D6**) |

**Keep unchanged:** `sec_filings_tool.py`, `options_chain_tool.py`, `options_payoff_tool.py`, `options_pricing_tool.py`, `stock_profile_tool.py`, `get_fundamentals_tool.py`, `institutional_holdings_tool.py`, `fred_macro_tool.py`, `backtest_tool.py`, `market_data_tool.py`, `technical_indicator_tool.py`, `factor_analysis_tool.py`, `correlation` tooling, `quantlib_tool.py`, all shell/file/memory/skill tools.

**Exit criteria:** `build_registry()` returns no tool whose docstring names A-share/HK/Taiwan.

---

### Phase 6 — Broker connectors and the live gate

**Delete 11 connector packages:** `okx/`, `binance/`, `upbit/`, `dhan/`, `shoonya/`, `zerodha/`, `kis/`, `toss/`, `scalable/`, `trading212/`, `mt5/`.

**Keep 7:** `alpaca/` (US), `ibkr/` (the only Canada-capable one), `robinhood/` (US), `tiger/` (US branch), `longbridge/` (US branch), `futu/` (reconfigure to US), `etoro/` (pending **D4**).

**Reconfigure `futu/`:** `profiles.py:34,50,65,82` and `sdk.py:90,117` default `filter_trdmarket="HK"`. That default becomes a US market filter, or the connector is deleted.

**Cross-cutting files that enumerate all 18 connectors and will break on import:**

| File | Lines | Action |
|---|---|---|
| `agent/src/trading/profiles.py` | 8-46 | trim imports; `BUILTIN_PROFILES` → 6-7 entries |
| `agent/src/trading/service.py` | 16-32 (`_SDK_CONNECTOR_MODULES`), 663-695 (`_order_classification`), 792-1240 (eToro copy-trading) | trim module list; `_order_classification` keeps US/CA only; eToro block depends on **D4** |
| `agent/src/trading/onboarding.py` | 52-204 (`_BUILTIN`) | trim dict; **add missing `ibkr` and `robinhood` entries** (both kept; see §2.4 gap 5) |
| `agent/src/live/registry.py` | 26-43 (imports), 50-70 (`_BROKER_CURATED_MAPS`) | trim |
| `agent/src/config/schema.py` | 15 (`LIVE_BROKER_SERVER_KEYS = {"robinhood","ibkr","scalable"}`) | drop `scalable`; also trim the scaled seed at `:240+` |
| `agent/src/portfolio/compatibility.py` | 47-112 (`_COMPATIBILITY`) | trim to surviving brokers |
| `agent/src/portfolio/service.py` | 49 (`_LOADER_MARKET_SUFFIXES`) | trim suffix set to `{"US", "TO", "V"}` — the last of the drifting classifiers from §2.2 |
| `agent/src/tools/trading_connector_tool.py` | 847-1200 (`etoro_*` block) | depends on **D4** |
| `agent/backtest/loaders/registry.py` | — | `futu`/`longbridge` loader entries follow Phase 2 |

**Close the Canada gaps (§2.4):** under the recommended **D3 (data + backtest only)**, this is a documentation step, not a code step:

1. Record the limitation in the docs/skill surface: Canada is **market-data + backtest only**; there is no live-trading path. §2.4 gaps 1–4 stay open as documented limitations.
2. Do **not** add `CA_EQUITY`/`CA_ETF`, the `_ASSET_CLASS_MARKET` row, or the `ca_equity` `MARKET_SPECS` entry in this refactor.

   *Only if D3 is later flipped to build a Canada live path* (a follow-on, not part of this plan):
   1. Add `CA_EQUITY` and `CA_ETF` to `AssetClass` (`agent/src/live/mandate/model.py:34-42`).
   2. Add the `CA_EQUITY` row to `_ASSET_CLASS_MARKET` (`agent/src/live/enforcement.py:58-66`).
   3. Add a `ca_equity` entry to `MARKET_SPECS` (`agent/src/live/runtime/triggers.py:96-110`) — TSX regular hours 09:30-16:00 America/Toronto, plus a Canadian holiday set (mirror `_US_EQUITY_HOLIDAYS` at `:66-88`).
   4. Decide whether `PreTradeAdvisoryInterface`, `pending_action.py:145` (`broker: Literal["alpaca"]`), and `flatten.py:96` (hardcoded `"broker": "robinhood"`) need a Canada/IBKR path.

**Regenerate the README broker matrix:** it is generated by `agent/src/trading/capability_matrix.py` between markers at `README.md:423-497`. Run `PYTHONPATH=agent python -m src.trading.capability_matrix` after editing profiles; `agent/tests/test_readme_counts.py` fails otherwise.

**Exit criteria:** `list_profiles()` returns only the surviving set; `broker_supports_live_runner` is accurate; the README matrix is regenerated and matches.

---

### Phase 7 — Agent prompts and skills

1. **`agent/SKILL.md`** (the agent's own guide):
   - `:78-93` backtesting section — the engine/market list becomes US + Canada only.
   - `:92` factor-universe paragraph — drop India/Korea.
   - `:196-215` tool table — remove the 11 deleted tools; the market footnote ("A-share symbols require `TUSHARE_TOKEN`. HK/US/Canada/crypto are free") becomes "US and Canada are free".
   - `:272`, `:309-325` connector-profile CLI — trim to surviving profiles.
   - The "28 sources" / "10 engines" counts at `:4, 11, 56, 60, 77, 79, 153, 223`.
2. **`agent/src/agent/context.py`**:
   - `:104-106` benchmark mapping — `A-shares → CSI 300` deleted; keep `US → SPY`, add `Canada → XIC.TO`.
   - `:146-153` trade-journal / Shadow market split → US/CA.
   - `:160-161` — the Canadian ticker examples (`BTO.TO`, `ETHX-B.TO`, `VET.TO`, `GC=F`) are already the target shape; drop `GC=F` (futures).
3. **`agent/src/agent/resolution_context.py:15-40`** (`_MARKET_PATTERNS` for literal market words in user messages) and `candidate_market()` (`:145-159`) → US/CA only.
4. **`agent/src/agent/grounding/identity.py`**: `_VENUE_PREFIXES` (`:158`), `_infer_venue` (`:241-299`) → keep `.US` → `us`, `.TO` → `toronto`, `.V` → `tsx_venture`. `_infer_currency` (`:301-330`) → keep USD/CAD. Delete `.SH`/`.SZ`/`.HK`/`.BA`/`.L`/`.VN`/`.KS`/`.KQ`/`.NS`/`.BO`.
5. **`agent/src/skills/data-routing/SKILL.md`** — the router skill. Source→market table (`:17-44`), capability→tool table (`:48-74`, contains every A-share flow tool), source-priority per market (`:90-105`), symbol-format table (`:110-120`). This file is the single highest-value prompt edit; get it right first.
6. **`agent/src/skills/strategy-generate/SKILL.md:88-115`** — "Market Detection" table.
7. **Delete these bundled skills** (from `agent/src/skills/`):
   - China/HK: `akshare/`, `tushare/`, `eastmoney/`, `mootdx/`, `ashare-pre-st-filter/`, `hk-connect-flow/`, `adr-hshare/`, `convertible-bond/`, `regulatory-knowledge/`, `sector-rotation/`, `sentiment-analysis/`, `earnings-forecast/`, `financial-statement/`, `fund-analysis/`, `etf-analysis/`, `trade-journal/`, `fundamental-filter/`, `chanlun/`, `pine-script/`, `corporate-events/`
   - Crypto: `ccxt/`, `okx-market/`, `crypto-derivatives/`, `defi-yield/`, `onchain-analysis/`, `stablecoin-flow/`, `token-unlock-treasury/`, `perp-funding-basis/`, `liquidation-heatmap/`
   - Futures/FX: `commodity-analysis/`, `vnpy-export/`, `global-macro/`
   - `agent/skills/ashare-mootdx/` — an orphan with no `SKILL.md` and zero references; delete unconditionally.
   Re-audit `hedging-strategy/`, `cross-market-strategy/` (its `example_signal_engine.py:15-28` hardcodes a_share/hk/ca parameters), and `market-microstructure/` (mentions A-share call auction) after the list above is gone.
8. **`agent/src/swarm/presets/*.yaml`** — 20 preset teams; `global_equities_desk.yaml` and any market-split preset need trimming. Audit each preset's role instructions for named markets.
9. **`agent/src/tools/swarm_tool.py:42-43`** — Chinese routing keywords `"港美.*A股"`, `"A股.*加密"`.
10. **Skill-count assertions:** `agent/tests/test_distribution_skill_manifest.py:108` counts "N market-data sources"; `test_readme_counts.py:604-664` parses the README data-source table. Both fail until the counts are updated.

**Exit criteria:** no bundled skill describes a market outside US/CA; the data-routing skill's tables are accurate against the new chains.

---

### Phase 8 — Frontend

**Trim these enumerations to `us_equity` / `ca_equity` / `other`:**

| File | Lines | What |
|---|---|---|
| `frontend/src/lib/positions.ts` | 7-21 | `AssetClass` union (13 → 3) |
| | 39-53 | `EQUITY_SUFFIX_MAP` → keep `.US`, `.TO`, `.V` |
| | 55-62 | delete `CRYPTO_QUOTE_SUFFIXES`, `FUTURES_EXCHANGE_SUFFIXES` |
| | 127 | `classifyAssetClass()` — drop the crypto-pair / 6-letter forex heuristics |
| `frontend/src/components/run/PositionsTab.tsx` | 25-39 | `ASSET_CLASS_LABEL_KEYS` |
| `frontend/src/components/settings/SourcePrioritySettings.tsx` | 24-45 | market label map (15 → 2) |
| `frontend/src/lib/api.ts` | 1223-1237 | `SectorAssetClass` union; `:1225` `SourceOrderEntry` market union |
| `frontend/src/stores/agent.ts` | 34 | `MARKET_DATA_TOOL` regex — drop the A-share-only tool names |
| `frontend/src/pages/Correlation.tsx` | 11 | hardcoded A-share defaults `000001.SZ,600519.SH,...` → US/CA tickers |
| `frontend/src/pages/AlphaZoo.tsx` | — | universe selector → `sp500` only |
| `frontend/src/components/chat/WelcomeScreen.tsx` | 18-31 | `multiMarketBacktest` category is "A-Share Backtest"; prompts use `000001.SZ`/`600519.SH` → rewrite to US/CA |

**i18n:** every removed key must be removed from **all 9** locale files (`en, zh-CN, ja, ko, ar, es, de, pt-BR, id`), or `frontend/src/i18n/__tests__/i18n.test.ts` fails. Keys to edit:

- `settings.sourcePriority.markets.*` (`en.json:783-798`, 15 markets)
- `settings.dataSources.tushareDesc` / `baostockDesc` (`:367-368`) and `tushareTokenDesc` / `gildataTokenDesc` (`:836-837`)
- `runDetail.positions.assetClass.*` (`:1110-1124`, 13 classes)
- `alphaZoo.universeOption.*` (`:1420-1428`)
- `alphaZoo.zooCardDesc.gtja191` (`:1412`)
- `welcome.categories.multiMarketBacktest` (`:243`) and `welcome.examples.*` (`:253-301`)
- `home.featureBacktestDesc` (`:1630`) — "Multiple data sources covering A-shares quantitative analysis"

**Verification:** `cd frontend && npm run build && npm test`.

---

### Phase 9 — Docs, wiki, packaging, CI

**README (7 files, must stay in sync):** `README.md`, `README_zh.md`, `README_ja.md`, `README_ko.md`, `README_ar.md`, `README_es.md`, `README_id.md`.

- Market/engine tree at `README.md:312` and translations at `:63, 130, 278/444/445/460` → US + Canada.
- Data-sources table at `README.md:547-570` → the surviving loadsers; `test_readme_counts.py:604-664` parses this.
- Broker matrix at `README.md:423-497` → regenerated in Phase 6.
- The News log (`README.md:53-270`) is saturated with A-share/HK/Korea/India/Vietnam/Argentina/crypto items. **Recommended:** keep the log (it is history) but add one dated entry at the top stating the fork's US/CA scope. Rewriting 200 lines × 7 languages is a large diff for little value. **Decision D7.**
- Feature table at `README.md:306-313` lists "A / HK / US / Canada / UK / India / Korea equities, crypto, futures, and forex" → US + Canada.

**Wiki (static site, deployed via Cloudflare Pages):**

- `wiki/docs/content.js:108, 166, 294` — engine list, A-share credentials note, A-share pre-ST screening.
- `wiki/research-lab/posts/alpha-191-in-2026.html` + its card (`wiki/research-lab/index.html:76-78`) — delete with the gtja191 zoo (Phase 4).
- `wiki/alpha-library/index.html:127,147` and `wiki/scripts/build_alpha_library.py:84,211`.
- `wiki/tutorials/vibe-trading-beginner-zh.html:580,709` — mixed SP500/A-share; edit.
- Images: `wiki/assets/feature-cross-market-data-backtesting.png` may need replacement.

**Packaging:**

- `docker-compose.yml` — remove the Taiwan-specific `VIBE_TW_STOCK_DB` env and the `tw-stock` read-only volume.
- `Dockerfile` — review for `tushare`/`akshare`/`mootdx` installs.
- `MANIFEST.in` — ships all 6 README translations and `agent/.env.example`; update if translations are dropped.
- `agent/.env.example:181-210` — data-source block, `MARKET_DATA_ORDER_A_SHARE` example, Futu/Longbridge notes.
- `desktop/electron/requirements-windows-lock.txt` — review.

**Misc:**

- `CONTRIBUTING.md:135` — `alpha bench --universe csi300` example.
- `.github/dependabot.yml` — check for `longbridge`/`pykrx` entries.
- `CHANGELOG.md` — do not rewrite; add a `## Unreleased` entry describing the scope reduction.

---

### Phase 10 — Tests and the scope gate

**Delete tests that cover deleted behaviour.** ~150-200 files across:

- engines: `test_china_a_engine.py`, `test_china_futures_engine.py`, `test_china_futures_pricing_assumptions.py`, `test_india_equity_engine.py`, `test_korea_equity_engine.py`, `test_vietnam_equity*.py`, `test_uk_*.py`, `test_crypto_engine.py`, `test_forex_engine.py`, `test_global_futures_engine.py`, `test_perpetual_risk.py`, `test_argentina_market_routing.py`
- loaders: `test_tushare_*.py`, `test_akshare_*.py`, `test_baostock_*.py`, `test_mootdx_loader.py`, `test_tencent_loader.py`, `test_gildata_loader.py`, `test_pykrx_loader.py`, `test_eastmoney_*.py` (keep only the US paths), `test_futu_loader*.py`, `test_ccxt_*.py`, `test_okx_*.py`, `test_binance_*.py`, `test_mt5_*.py`, `test_tickerall_loader.py`, `test_qveris_*.py`, `test_nobitex_loader.py`, `test_wallex_loader.py`, `test_india_broker_loader.py`, `test_zerodha_*.py`, `test_dhan_period_reject.py`, `test_shoonya_*.py`
- tools: `test_block_trades_*.py`, `test_dragon_tiger_tool.py`, `test_fund_flow_tool.py`, `test_margin_trading_*.py`, `test_northbound_tool.py`, `test_shareholder_count_tool.py`, `test_lockup_expiry_*.py`, `test_taiwan_stock_data_tool.py`, `test_iwencai_tool.py`, `test_sector_tool.py`, `test_research_reports_tool.py`, `test_tushare_fallbacks.py`
- connectors: `test_sdk_connectors_kis.py`, `test_sdk_connectors_toss.py`, `test_sdk_connectors_upbit.py`, `test_scalable_connector.py`, `test_trading212_connector.py`, `test_etoro_*.py` (if **D4** drops eToro), `test_mt5_connector*.py`
- factors: `test_factors/test_gtja191_*.py` (~12), `test_factors/test_india_universe.py`, `test_factors/test_korea_universe.py`
- evals: `agent/evals/harness/cases/identity/explicit_a_share.json` and `cases/identity/fixtures/identity/a_h_hengrui.v1.json`. The harness itself is market-agnostic — keep it, and either re-point the harness tests at a US/CA case or make an empty case directory valid.

**Rewrite (do not delete) tests that encode a multi-market world:**

- `test_market_detection.py`, `test_classification.py`, `test_market_identity_parity.py`, `test_load_equity_aliases.py`, `test_composite_market_rules.py`, `test_composite_currency_guard.py`, `test_cross_market_annualization.py`, `test_local_prefix_routing.py`, `test_local_source_routing.py`, `test_source_order_overrides.py`, `test_volume_unit_consistency.py`, `test_loader_volume_units.py`, `test_price_caliber.py`, `test_price_limit_lookahead.py`, `test_registry.py`, `test_market_data_serving_source.py`, `test_data_routing_sources_subset.py`, `test_env_schema.py:120-139`, `test_settings_api.py:663-705`, `test_ui_services.py`
  Each keeps: the US path, the Canada path, and the **rejection** of a now-unsupported symbol.

**Must stay green and gain coverage:** `test_global_equity_engine.py`, `test_equity_regression.py`, `test_correlation*.py`, `test_metrics_inf_zero_equity.py`, `test_symbol_search` / Canada-alias tests, `test_yfinance_*.py`.

**Add — the scope gate.** A test (plus a grep gate in `tools/ci_grep_gates.sh`) that fails if a removed market string reappears in shipped code. Suggested deny-list, scoped to `agent/src`, `agent/backtest`, `frontend/src` — **not** `CHANGELOG.md`, `agent/tests`, or this plan:

```
a_share  hk_equity  india_equity  kr_equity  vietnam_equity  ar_equity  uk_equity
csi300   tushare  akshare  pykrx  mootdx  baostock  gildata  tickerall  qveris
nobitex  wallex  okx  binance  ccxt  mt5  TUSHARE_TOKEN
600519.SH  000300.SH  000001.SZ  0700.HK  RELIANCE.NS  005930.KS  VIC.VN  -USDT  BTCUSDT
```

The gate greps case-insensitively (`grep -in`), so the lowercase entries match `akshare`/`tushare`/`pykrx` as they appear in code and `TUSHARE_TOKEN` stays in env-var case for clarity. Make the deny-list a **single file** (`tools/us-ca-scope-deny.json`, created in Phase 0) so it is auditable and extensible; intentional mentions with reasons can be recorded as an allowlist alongside it.

**Exit criteria:** the scope gate passes; the rewritten routing tests cover US accept, CA accept, non-US/CA reject.

---

## 6. Open decisions

| ID | Decision | Recommendation |
|---|---|---|
| **D0** | Delete vs. gate vs. hybrid | **Hybrid** — delete region-only modules, keep the dispatch tables in their current shape |
| **D1** | Keep the `index` market and `^SPX`/`^VIX` symbols? | **Keep.** Benchmarks resolve through `yfinance`, but index symbols are used by correlation and regime analysis and are US-native |
| **D2** | Keep `akshare` and `longbridge` for their US branches? | **Drop both.** Their US coverage duplicates `yahoo`/`yfinance`; the loading cost and dependency weight outweigh the fallback value. Drop `eastmoney_loader` too if its US path is unexercised |
| **D3** | Canada live trading, or data + backtest only? | **Data + backtest only for now.** Closes §2.4 as "documented limitation" rather than building a Canada live path against a single broker. The `AssetClass.CA_EQUITY` / `_ASSET_CLASS_MARKET` / `ca_equity` `MARKET_SPECS` additions in Phase 6 are deferred — do them only if a live CA path is later wanted |
| **D4** | Keep `etoro`? | **Drop.** It is a global multi-asset connector that is neither US-primary nor Canada-capable, and it carries a large copy-trading surface (`service.py:792-1240`) |
| **D5** | Delete `screen_market` or port it to SP500? | **Port it.** A US market screen is a genuine capability and the SP500 universe code already exists for `alpha_bench` |
| **D6** | Keep Aliyun IQS for web search? | **Keep as a secondary backend** (it is a search provider, not a market). Review only for credential/maintenance cost |
| **D7** | Rewrite the README news log, or note the fork scope? | **Note the scope, keep the log.** 200 lines × 7 languages is disproportionate |

---

## 7. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **Upstream divergence.** Deleting files that upstream actively edits makes future syncs merge-hostile | High | Phase 1 step 3: a replayable prune script; keep the refactor on a long-lived branch; re-run rather than merge |
| **Silent fallback.** `resolve_loader()` walks a chain; if a removed source is still referenced anywhere, it fails *quietly* into the next source | High | Phase 2 releases the cache version; the scope gate covers source names; Phase 2 exit check asserts every loader's `markets` set |
| **Default market.** Two classifiers default to `a_share` / `tushare`. Leaving either is a silent misroute, not a crash | High | Phase 1 steps 6-7 make both fail loud |
| **Cross-currency arithmetic.** US (USD) + Canada (CAD) is now the only possible mixed basket | High | `_reject_mixed_currency` (`composite.py:87`) already exists; add a regression test for `["AAPL", "TD.TO"]` |
| **Stale loader cache.** Cached frames from removed sources | Medium | Bump `_LOADER_CACHE_VERSION` (`base.py:469`) |
| **i18n parity.** 9 locale files must move together | Medium | The parity test catches it; do the edits file-by-file in one commit |
| **README count tests.** `test_readme_counts.py` and `test_distribution_skill_manifest.py` parse prose | Medium | Update counts in the same commit as the corresponding deletion |
| **Under-deletion.** `qveris`, `tickerall`, `nobitex`, `wallex` are key-gated and easy to miss | Medium | The scope gate's deny-list includes each source name |
| **Over-deletion.** `macro` (FRED) and `index` are region-neutral and easy to cut by accident | Medium | Decisions D1/D6; `fred_macro_tool.py` is independent of the `macro` loader chain |
| **Broken generated artefacts.** `capability_matrix.py` writes into `README.md` between markers | Low | Regenerate after Phase 6; the test fails loudly |

---

## 8. Verification plan

Per phase, run the smallest covering set (see the repo's own `AGENTS.md` / `dsh-pre-push-checks` discipline — do not reflexively run the full suite):

| Phase | Commands |
|---|---|
| 1, 2 | `PYTHONPATH=agent python -m pytest agent/tests/test_registry.py agent/tests/test_market_detection.py agent/tests/test_env_schema.py agent/tests/test_source_order_overrides.py -q` |
| 3 | `PYTHONPATH=agent python -m pytest agent/tests/test_global_equity_engine.py agent/tests/test_equity_regression.py agent/tests/test_composite_currency_guard.py agent/tests/test_metrics_inf_zero_equity.py -q` |
| 4 | `PYTHONPATH=agent python -m pytest agent/tests/test_factors -q` |
| 5 | `PYTHONPATH=agent python -m pytest agent/tests/test_market_data_tool.py agent/tests/test_symbol_search_tool.py agent/tests/test_financial_statements_tool.py -q` |
| 6 | `PYTHONPATH=agent python -m pytest agent/tests/test_capability_matrix.py agent/tests/test_sdk_connectors.py agent/tests/test_readme_counts.py agent/tests/test_mandate_model.py -q` |
| 7, 9 | `PYTHONPATH=agent python -m pytest agent/tests/test_distribution_skill_manifest.py agent/tests/test_readme_counts.py -q` |
| 8 | `cd frontend && npm run build && npm test` |
| All | The scope gate + a full US/CA smoke: one backtest on `AAPL`/`SPY`, one on `TD.TO`/`XIC.TO`, one rejected `600519.SH` |

**Acceptance criteria for the whole refactor:**

1. `FALLBACK_CHAINS` has exactly `us_equity`, `ca_equity`, and the region-neutral `index` chain (D1).
2. An end-to-end backtest runs on a US basket and on a Canada basket, and a mixed USD/CAD basket is refused with the existing currency error.
3. Every non-US/CA symbol is rejected with an actionable message, not silently routed.
4. `list_profiles()` returns only brokers that can trade at least one of the two markets.
5. The bundled skill set contains no skill describing another market.
6. The frontend builds, its tests pass, and no locale file mentions a removed market.
7. The scope gate is green and registered in `tools/ci_grep_gates.sh`.
8. `git ls-files | wc -l` is materially lower (target: **-600 to -800 files**, dominated by gtja191, the deleted loaders/engines/connectors/tools/skills, and their tests).

---

## 9. Optional follow-on (out of scope here)

- **Prune UI locales.** 9 frontend + 5 desktop locales. Cutting to `en` only (or `en` + `zh-CN`) removes ~8 × ~1,900 JSON lines and the desktop locale matrix. Unrelated to market scope; decide separately.
- **Prune LLM providers.** `agent/src/providers/llm_providers.json` lists 25 providers, ~10 of them China-hosted (`siliconflow-cn`, `dashscope`/`qwen`, `zhipu`/`glm`, `moonshot`/`kimi-coding`, `minimax`, `mimo`, `spark`, `zai`, `modelscope`). None constrain market support; this is hygiene only.
- **Prune IM channels.** 6 of 16 are China-market IM (`qq`, `napcat`, `weixin`, `wecom`, `feishu`, `dingtalk`) plus their probe helpers (`qq_probe.py`, `dingtalk_probe.py`, `dingtalk_media.py`). Not market-related; decide based on the user base.
- **Remove the `mcp<1.30` pin.** `pyproject.toml:70-78` caps `mcp` solely for IBKR's OAuth metadata quirk. If IBKR goes, the cap goes.

---

## 10. Suggested order

```
Phase 0  baseline + branch                        (0.5 day)
Phase 1  markets / symbols / chains / env          (1-2 days)   ← highest leverage
Phase 2  loaders + deps                            (1-2 days)
Phase 3  engines + execution rules                 (1 day)
Phase 4  factor universes + zoo                    (0.5 day, scripted)
Phase 5  agent tools                               (1 day)
Phase 6  brokers + live gate + CA gaps             (2 days)     ← most cross-cutting
Phase 7  prompts + skills + swarm presets          (1-2 days)
Phase 8  frontend + i18n                           (1-2 days)
Phase 9  docs / wiki / packaging / CI              (1 day)
Phase 10 tests + scope gate                        (2-3 days, threaded through)
```

Phases 1-3 are the load-bearing ones: an agent run and a backtest must work end-to-end after Phase 3 before any of the cosmetic phases begin. Phases 4-9 are largely independent of each other and can be parallelised or landed as separate PRs once 1-3 are in.
