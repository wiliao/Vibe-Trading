---
name: strategy-generate
description: Create, modify, and optimize quantitative trading strategies, then backtest and evaluate them.
category: strategy
---

## Workflow

1. **Requirements parsing**: parse user intent, extract instrument codes, time range, and strategy logic, then write `config.json`
2. **Strategy design**: think through the 5 questions of data / signal / position sizing / backtest / validation
3. **Strategy coding**: write `code/signal_engine.py` (following the `SignalEngine` contract)
4. **Syntax check**: `bash("python -c \"import ast; ast.parse(open('code/signal_engine.py').read()); print('OK')\"")`
5. **Run backtest**: call the `backtest` tool (built into the engine; no need to write `run_backtest.py`)
6. **Evaluate results**: read `artifacts/metrics.csv` and judge by the review criteria
7. **Iterative fixing**: if results are poor, modify with `edit_file` → run `backtest` → re-evaluate

**You only need to write `signal_engine.py` and `config.json`. The `backtest` tool automatically handles data loading and backtest execution.**

## Requirements Parsing

Extract the following from the user's description:
- **Instrument codes**: process them according to the normalization rules below
- **Time range**: if the user does not specify dates, default to **10 years back from today** (for example, if today is `2026-03-18`, then `start_date=2016-03-18`, `end_date=2026-03-18`)
- **Indicator warm-up**: a long lookback (MA200, a 252-day z-score) needs bars from *before* the requested period. Move `start_date` back to load them **and declare the boundary with `warmup_bars`** — the requested period is what gets graded, and undeclared warm-up bars are graded too. Silently backdating `start_date` by a year turns a 10-year backtest into an 11-year one that still calls itself 10 years: the extra year's trades, CAGR and benchmark all enter the report, the run succeeds, and the numbers look internally consistent
- **Strategy logic**: entry / exit conditions and indicator parameters

**If critical information is missing, you must ask the user instead of guessing:**
- Instrument not specified → ask which instrument they want to backtest (offer several popular suggestions)
- Strategy description is vague (for example, "help me build a strategy") → provide 2-3 strategy directions for the user to choose from
- Mixed markets but not clearly specified → confirm the data source

**Write `config.json` first, then write code.** `config.json` must be placed in the root of `run_dir`.

## Strategy Design

Before writing code, think through these 5 questions:

1. **Data requirements**: what fields are needed (basic OHLCV only, daily valuation fields such as `pe/pb/roe`, or statement fields such as `income_total_revenue` / `fina_indicator_roe`?), data frequency (daily), and market (which determines the data source)
2. **Signal logic**: what are the entry conditions? What are the exit conditions? Direction (long / short / long-short)? Are there filters (volume, trend confirmation, and so on)?
3. **Position management**: equal-weight allocation or scaling in/out? Risk control (stop-loss, maximum position)? In portfolio strategies, once top N names are selected, each weight = 1/N
4. **Backtest parameters**: time range, initial capital (default 1,000,000), commission (default 0.1%)
5. **Validation checklist**: signal consistency (no NaN signals), position check (normalized to prevent leverage), and completeness of generated artifacts

There is no need to output a JSON design document. Express these design decisions directly in code.

## `SignalEngine` Contract

```python
class SignalEngine:
    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """
        Args:
            data_map: code -> DataFrame (columns: open, high, low, close, volume, DatetimeIndex)
                     For this US/Canada build no extra columns are merged in: the
                     retired legacy `extra_fields` / `fundamental_fields` provider
                     paths are not available, so read only OHLCV here and pre-compute any
                     fundamental inputs with the `get_fundamentals` tool.
        Returns:
            code -> signal Series, value range [-1.0, 1.0]
            1.0 = fully long, 0.5 = half position, 0.0 = flat, -1.0 = fully short
            Portfolio strategy: selected stocks split weights equally (for example top 10 -> each 0.1)
            Legacy integer signals {-1, 0, 1} remain compatible (treated as -100% / 0% / 100%)
        """
```

**Hard constraints:**
- The signal `Series` index must align exactly with the input `DataFrame` index
- Include all required imports (`numpy`, `pandas`, and so on)
- Do not hardcode dates or stock codes (read them from `config.json`)
- Do not include an `if __name__ == "__main__"` block
- Pure pandas / numpy implementation, with no external signal libraries
- Output plain Python code, not Markdown fences

## Quality Checklist

Self-check after writing `signal_engine.py`:
- [ ] All imports are included (`numpy`, `pandas`, `typing`, and so on)
- [ ] No undefined variables
- [ ] Signal logic is consistent with the strategy description
- [ ] Boundary handling: for empty data or insufficient history before the lookback window, use `fillna(0)` or skip
- [ ] Portfolio strategy: once N stocks are selected, each weight = 1/N (for example top 10 → each 0.1), unselected names = 0
- [ ] Signal values stay within `[-1.0, 1.0]`

## Instrument Code Normalization

- US stocks: a bare uppercase ticker (`AAPL`) or uppercase letters + `.US` (`AAPL.US`); the loaders accept both and normalize internally
- Canadian stocks: Yahoo ticker + `.TO` for TSX or `.V` for TSXV, such as `TD.TO` or `PNG.V`
- Indices: Yahoo `^` symbols, such as `^GSPC`, `^GSPTSE`, `^NDX` or `^VIX` (index-level series; not tradable equity)

## Market Detection and Data Sources

| Pattern | Market | source | Extra Fields |
|------|------|--------|----------|
| `^[A-Z][A-Z0-9.-]*$` (bare) or `^[A-Z][A-Z0-9.-]*\.US$` | US equity | `auto` → yahoo / yfinance / stooq / sina / eastmoney, then key-gated tiingo / fmp / finnhub / alphavantage / local | `null` |
| `^[A-Z0-9&.-]+\.(TO\|V)$` | Canada equity (TSX / TSXV) | `auto` → yahoo / yfinance / local | `null` |
| `^\^[A-Z0-9]+$` | Index | `auto` → yahoo / yfinance / local | `null` |

**`extra_fields` selection logic**: `extra_fields` and `fundamental_fields` were
legacy-provider-only options and are dead for this US/Canada build — leave both `null` in
`config.json`. Pull fundamentals with the `get_fundamentals` tool (PIT-safe SEC
panels, filed-date anchored) or `get_financial_statements` and bake the values you
need into `signal_engine.py` instead of asking the runner to fetch them.

**`fundamental_fields` selection logic**: do not use it. The runner's enrichment
path routes through the retired legacy provider, so a US/Canada run that sets it
fails rather than enriching. Use the `get_fundamentals` tool for PIT-safe SEC
statement panels; on daily frames only, since an announcement date carries no time
of day.


## `config.json` Format

```json
{
  "source": "auto",
  "codes": ["AAPL.US"],
  "start_date": "2016-03-18",
  "end_date": "2026-03-18",
  "warmup_bars": 0,
  "interval": "1D",
  "initial_cash": 1000000,
  "commission": 0.001,
  "extra_fields": null,
  "fundamental_fields": null,
  "optimizer": null,
  "optimizer_params": {},
  "engine": "daily",
  "position_adjustment": "rebalance",
  "rebalance_mask": null,
  "rebalance_tolerance": 0.05,
  "validation": null
}
```

- `source`: `"auto"` (recommended, auto-select by code format) / `"yahoo"` / `"yfinance"` / `"stooq"` / `"sina"` / `"eastmoney"` / `"tiingo"` / `"fmp"` / `"finnhub"` / `"alphavantage"` / `"local"`
  - `"auto"` supports mixed US + Canada instruments. For example, `["AAPL.US", "TD.TO"]` is routed to the US and Canada fallback chains respectively
- `interval`: candlestick interval, default `"1D"`. Supported values: `"1m"` / `"5m"` / `"15m"` / `"30m"` / `"1H"` / `"4H"` / `"1D"` / `"1W"` / `"1M"` (weekly and monthly bars are built from daily ones; `"1M"` is a month, `"1m"` a minute)
  - The annualization factor for minute backtests is inferred automatically from `source` (252 trading days for US and Canadian equities)
  - Minute backtests can be very data-heavy. Recommended limits are no more than 30 days for `1m`, or 1 year for `1H`
- `warmup_bars`: how many leading bars exist only to prime the indicators. They are loaded and fed to `SignalEngine.generate()`, then excluded from trades, the equity curve, the benchmark and every metric. Default `0` grades the whole loaded window.
  - Use it whenever you widen `start_date` for an indicator's lookback. `start_date` is the **data** window; `start_date` plus `warmup_bars` is the **evaluation** window, and the report describes the second one.
  - Size it from the longest lookback in the strategy, plus a margin: MA200 needs at least 200 daily bars, a 252-day rolling z-score needs 252. Then set `start_date` far enough back to supply them.
  - `evaluation_start_date` (`"YYYY-MM-DD"`) is the same instruction stated as a date, for when the user names the period rather than the lookback. Declare one or the other — declaring both is rejected.
- `extra_fields`: must be `null` for US and Canadian symbols (the legacy valuation fields are retired); fetch valuation inputs with the `get_fundamentals` tool instead
- `fundamental_fields`: must be `null` (the legacy statement-enrichment path is retired); fetch PIT-safe SEC panels with the `get_fundamentals` tool instead
- `optimizer`: optional, one of `"equal_volatility"` / `"risk_parity"` / `"mean_variance"` / `"max_diversification"` / `"turnover_aware"` / `null` (equal-weight by default)
- `optimizer_params`: optimizer parameters, such as `{"lookback": 60}`. `mean_variance` additionally supports `{"risk_free": 0.0}`; `turnover_aware` supports `{"risk_aversion": 1.0, "turnover_penalty": 0.5}` (L1 penalty on weight changes; tune to data frequency)
- `engine`: backtest engine, default `"daily"`. For options strategies, set `"options"` (requires `OptionsSignalEngine`)
- `position_adjustment`: **always state this explicitly** — the two modes produce different books from the same signals, and neither is right for every strategy.
  - `"rebalance"` executes every target change with market fills and weighted-average entry accounting. It also re-sizes whenever the held weight has drifted from the target, and a strategy restates its target on every bar, so a constant target means a fill on every bar: measured on a 40-bar rising series, a constant 20% target produced **40 fills instead of 1**, with the fees, slippage and transaction taxes that follow. Use `rebalance_mask` when the strategy has its own execution cadence.
  - `"hold"` keeps a same-direction position until it exits or reverses, so the weight drifts with price and a requested resize is **not executed**. Dropped requests are counted in the report as `dropped_target_adjustment_count`, with the first twenty listed, so a rebalance count that does not match the trade log is explained rather than silent.
  - Rule of thumb: `"rebalance"` when the target weight itself carries the strategy (optimizers, risk budgets, continuous scaling); `"hold"` when entries and exits carry it and the weight in between is incidental.
- `rebalance_mask`: optional execution schedule used only under `"rebalance"`. Use a pandas offset alias such as `"MS"`, `"W-FRI"`, or `"QS"`, or an explicit ISO-date list such as `["2026-01-02", "2026-02-02"]`. Each period/date selects the first aligned trading bar on or after it; ordinary bars HOLD even when the dense target is zero. An alias must not be finer than the aligned bar interval; `W-FRI` starts a Friday-anchored period and normally executes on the following Monday. Omit it to preserve every-bar execution. Do not combine it with `"hold"`.
- `rebalance_tolerance`: drift band around the target, as a fraction of it, used only under `"rebalance"`. A resize executes once the held weight has moved further than this from its target; a **changed** target breaches any sane band on its own, so target changes always execute. Default `0.0` means no band, and then the resize test is decided by the slippage width alone — measured on a constant 20% target over 60 bars, `0.0` produced 60 fills, `0.02` produced 12, and `0.05` produced 5 while the weight never left 0.21. Use `rebalance_mask`, not tolerance, to express a strategy's execution cadence. `0.05` is a reasonable starting point, not a recommendation with evidence behind it — it is your modelling choice and the report records the value the run used.
- `initial_cash`: default 1,000,000
- `commission`: default 0.1%
- `validation`: optional statistical validation after backtest completes. Omit to skip. Example:
  ```json
  "validation": {
    "monte_carlo": {"n_simulations": 1000},
    "bootstrap": {"n_bootstrap": 1000, "confidence": 0.95},
    "walk_forward": {"n_windows": 5}
  }
  ```
  - `monte_carlo`: permutation test — shuffles trade order to compute p-value (is Sharpe significantly better than random?)
  - `bootstrap`: resamples daily returns to compute Sharpe 95% confidence interval
  - `walk_forward`: splits equity curve into N windows, checks performance consistency
  - Each key is optional — include only the validations you want
  - Can also run standalone on past results: `python -m backtest.validation <run_dir>`

## Review Criteria

### Hard Gates (any failure → `passed=false`)

1. `artifacts/metrics.csv` exists and is non-empty
2. `artifacts/equity.csv` exists and is non-empty
3. `exit_code == 0` (backtest exits normally)
4. The `equity` column in `equity.csv` contains no `NaN` values
5. `trade_count > 0` (zero trades = signal bug)

### Scoring Rules

- Successful backtest + complete artifacts + at least 1 trade → `score ≥ 60` → **passed**
- Poor return / low Sharpe alone should not push the score below 60; they are optimization suggestions only
- `score ≥ 60` = `passed=true`

### Bug Categories (reduce the score)

1. **Zero trades** (`trade_count=0`): signal-logic bug, conditions may be too strict
2. **Late first trade** (first trade > 2 years after backtest start): data-filtering bug or overly long lookback window
3. **Capital utilization < 50%**: position-management bug, portfolio is flat most of the time
4. **Open position at the end** (positions still open when backtest ends): exit-signal timing bug

### `action_items` Format

If improvements are needed after evaluation, write `action_items`:
- Format: `"Change X from A to B"` or `"Add X logic in signal_engine.py"`
- Must be specific down to parameter values, file names, and function names
- At least 2 items
- Examples:
  - `"Change short MA from 5 to 10 days to reduce whipsaw signals"`
  - `"Add stop-loss: force close when loss exceeds 5%"`
  - `"Add volume filter in signal_engine.py: only trigger buy on high volume"`

## Cross-Market Strategies

When the user requests a backtest with codes from **both surviving markets** (e.g. `["AAPL.US", "TD.TO"]`):
- Set `source: "auto"` in `config.json`
- The `CompositeEngine` handles calendar alignment, shared capital, and per-market rules automatically
- Use volatility-adjusted weights so high-vol names don't dominate the risk budget
- See the [cross-market-strategy](../cross-market-strategy/SKILL.md) skill for per-market parameters, vol-adjustment, and example code

## Supporting Files

- [examples.md](examples.md) — example call sequence
