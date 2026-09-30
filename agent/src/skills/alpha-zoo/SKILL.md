---
name: alpha-zoo
description: Browse and bench the bundled alpha zoos — prebuilt cross-sectional factor libraries (Kakushadze 101, GTJA 191, Qlib 158, Fama-French / Carhart). Use when the user asks "which alphas exist", wants metadata on a named alpha, or wants to run IC/IR on a whole zoo over a universe.
category: research
---
# Alpha Zoo

## Purpose

When the user asks about prebuilt cross-sectional alphas — Qlib 158, Kakushadze 101, Fama-French / Carhart — or wants to bench a whole zoo on an investable universe (S&P 500, S&P/TSX Composite, ...), this skill orients you. The zoo is the curated library; the bench is the evaluator.

## Tools Available

| Tool | When to use |
|------|------|
| `alpha_zoo` | Browse the library. `action=list_alphas` to enumerate (filterable by zoo / theme / universe), `action=get_alpha` for one alpha's metadata, `action=health` for registry load status. |
| `alpha_bench` | Run IC / IR on one alpha or a whole zoo over a universe + period. Emits an HTML report. |
| `factor_analysis` | Ad-hoc factor evaluation from a user-supplied factor CSV + return CSV. Use this when the user has their own factor (not in the zoo). |

## Decision Tree

- "list all momentum alphas" → `alpha_zoo` with `action=list_alphas, theme=momentum`.
- "show me gtja191_alpha_001" → `alpha_zoo` with `action=get_alpha, alpha_id=gtja191_alpha_001`.
- "bench the whole alpha101 zoo on the S&P 500 from 2020 to 2024" → `alpha_bench` with `zoo=alpha101, universe=sp500, period=2020-2024`.
- "is the registry healthy" → `alpha_zoo` with `action=health` — surfaces `loaded`, `failed`, and per-error reasons.
- User uploads `my_factor.csv` → `factor_analysis` (zoo tools are for prebuilt alphas only).

## Zoo Inventory

| Zoo | Description | Approx. count |
|------|------|------|
| `qlib158` | Microsoft Qlib's `Alpha158` feature handler. Mix of momentum, reversal, volume, and microstructure. | ~154 |
| `alpha101` | Kakushadze's 2015 formulaic alphas. Short-horizon price-volume and microstructure combinations. | ~101 |
| `academic` | Fama-French 5 + Carhart momentum, Jegadeesh reversal, 52-week-high, Amihud illiquidity, Harvey-Siddique skew, betting-against-beta, correlation-rewiring stability. | ~12 |
| `fundamental` | PIT-safe earnings yield, ROE, gross profitability, and asset growth from daily fundamental panels. | ~4 |

Counts are nominal; check `alpha_zoo action=health` for the live count currently loaded.

## Constraints

- **No per-stock per-date factor values are surfaced to the agent.** IC results are aggregate stats (mean / std / IR / positive-ratio); the HTML report shows top-N by IR plus formulas, never the underlying panel.
- **Lookahead is banned in the operator set.** `delta(df, d)` requires `d >= 1`; the negative-shift `Ref(df, -n)` form does not exist. See `docs/alpha-zoo/spec.md` for the full operator catalogue.
- **Universe loaders may not be wired for every market yet.** When `alpha_bench` returns `universe loader for X not yet implemented`, that's the W2 scaffold — the universe is recognised but the data pull lands in W4.
- **Do not expose absolute filesystem paths in agent output.** The bench tool writes to `~/.vibe-trading/reports/` by default; refer to it by that shorthand, not by the resolved absolute path.
- **`alpha_zoo` is read-only.** `alpha_bench` writes a single HTML file per run — no scratch state elsewhere.

## Common Pitfalls

- Filter mismatch on `list_alphas`: theme / universe must match the alpha's declared metadata exactly (e.g. `equity_us`, not `us` or `usa`).
- Calling `alpha_bench` with both `alpha_id` and `zoo` set — they are mutually exclusive; pick one.
- Empty registry (`loaded=0`) means no zoo modules are populated yet; treat it as "zoos pending W3 porting" rather than a bug.

## Reference

- Operator catalogue: `docs/alpha-zoo/spec.md`
- Registry contract: `src/factors/registry.py` (frozen; do not modify)
- IC / layered NAV math: `src/factors/factor_analysis_core.py`
