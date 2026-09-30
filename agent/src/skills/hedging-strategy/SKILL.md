---
name: hedging-strategy
description: Hedging strategy design (beta hedge / option protection / tail risk / cross-asset hedging), including hedge-ratio calculation and cost evaluation.
category: asset-class
---
# Hedging Strategy Design

## Overview

Design systematic hedging plans for existing positions, covering linear hedges (futures / ETFs) and nonlinear hedges (options). Output hedge ratios, cost estimates, and execution plans. Core principle: hedging does not eliminate risk; it exchanges unknown losses for known costs.

## Core Concepts

### 1. Beta Hedging (Index ETFs / Listed Options)

**Principle:** hedge portfolio systematic risk (beta) with an index ETF or listed index options while preserving single-stock alpha.

**Hedge ratio calculation:**

```python
# Minimum-variance hedge ratio
hedge_ratio = beta_portfolio * (portfolio_value / hedge_value)

# Example: hold a USD 10 million US equity portfolio, beta = 1.2 vs the S&P 500
# Hedge with SPY: at USD 600/share the hedge notional per share is USD 600
# Required short notional = 1.2 x 10,000,000 = USD 12,000,000
# -> short ~20,000 SPY shares, or buy puts sized to the same notional

# Beta estimation method
import numpy as np
# OLS regression: portfolio_returns = alpha + beta * index_returns + epsilon
beta = np.cov(portfolio_returns, index_returns)[0][1] / np.var(index_returns)
```

**US / Canada beta hedging instruments:**

| Instrument | Proxy | Sizing unit | Suitable Scale |
|------|------|---------|---------|
| S&P 500 ETF (SPY / IVV / VOO) | US large-cap beta | 1 share | Any size |
| Nasdaq-100 ETF (QQQ) | US growth beta | 1 share | Any size |
| S&P/TSX 60 or Composite ETF (XIU.TO / XIC.TO) | Canadian beta | 1 share | Any size |
| Listed ETF puts (SPY / QQQ) | Non-linear beta hedge | 100 shares / contract | Any size |
| VIX calls | Tail / convexity hedge | 100 multiplier | Small notional |

**Note:** this build has no index-futures execution path, so express the beta hedge with the ETF itself (short sale) or with listed ETF options. Where a short sale is used, check borrow availability and the stock-loan fee before sizing.

### 2. Option Hedging Strategies

#### Protective Put

```
Hold the underlying + buy a put option
```

- **Cost:** option premium (typically 1-3% of underlying value per month)
- **Protection range:** fully protected below the strike price
- **Applicable scenario:** worried about a large drawdown but do not want to sell the position

**US-listed ETF example (SPY options):**
```python
# Hold 10,000 shares of SPY (about USD 6,000,000 at USD 600/share)
# Buy 100 SPY put contracts (100 shares each, strike 570)
# Premium ≈ USD 12/share × 100 shares/contract × 100 contracts = USD 120,000
# Cost ratio = 120,000 / 6,000,000 = 2.0%
# Protection effect: losses are capped once SPY falls below 570
```

#### Collar

```
Hold the underlying + buy an OTM put + sell an OTM call
```

- **Cost:** close to zero-cost (the call premium offsets the put premium)
- **Trade-off:** gives up upside above the call strike
- **Applicable scenario:** willing to cap upside in exchange for free downside protection

**Parameter selection guide:**

| Parameter | Aggressive | Balanced | Conservative |
|------|--------|--------|--------|
| Put strike | ATM-5% | ATM-8% | ATM-10% |
| Call strike | ATM+8% | ATM+5% | ATM+3% |
| Net cost | Slightly positive | Near zero | Slightly negative (income) |
| Maximum downside loss | -5% | -8% | -10% |
| Maximum upside gain | +8% | +5% | +3% |

#### Put Spread (Bear Put Spread Hedge)

```
Buy a higher-strike put + sell a lower-strike put
```

- **Cost:** 30-50% cheaper than buying a naked put
- **Protection range:** only between the two strikes; no protection below the lower strike
- **Applicable scenario:** hedging against moderate drawdowns while being cost-sensitive

### 3. Tail-Risk Hedging

**Far OTM put strategy:**

```python
# Buy deep OTM puts (delta ≈ -0.05 ~ -0.10)
# Characteristics: expires worthless most of the time, but pays off massively during black swans

# Parameters
otm_put_strike = current_price * 0.85  # 15% OTM
cost_per_month = portfolio_value * 0.003  # about 0.3% / month
expected_payoff_in_crash = portfolio_value * 0.10  # ~10% payoff in a severe selloff

# Cost management: ongoing spend of about 3.6% / year, profitable only in tail events
# Taleb-style hedge: lose small amounts often, make large gains occasionally
```

**VIX call strategy (US equities / options market):**

```python
# Buy OTM VIX calls (strike = current VIX + 10)
# If VIX jumps from 15 to 40, call value explodes
# Naturally negatively correlated with an equity portfolio

# Canadian-sleeve substitutes:
# There is no VIX-equivalent index listed in Canada, so alternatives are:
# 1. Buy OTM puts on the TSX proxy ETF (XIU.TO / XIC.TO) where listed
# 2. Go long volatility: buy a straddle on a liquid US ETF
# 3. Allocate to a gold ETF (GLD / MNT.TO) as a safe-haven asset
```

### 4. Cross-Asset Hedging

**Stock-bond hedge:**

| Stock/Bond Mix | Expected Volatility | Applicable Scenario |
|---------|-----------|---------|
| 80/20 | ~15% | Bull market environment, small bond buffer |
| 60/40 | ~10% | Classic allocation, suitable for most environments |
| 40/60 | ~7% | Bear market environment, bond-led |
| Risk Parity | ~8% | Volatility-balanced allocation |

**Note:** stock-bond correlation is not stable. In 2022, US stocks and bonds both fell (rising rates), and the traditional 60/40 mix failed. Treat the sign of the stock-bond correlation as regime-dependent and re-estimate it from the sample window you are using.

**Stock-commodity hedge (equities + commodity-linked assets):**
- During rising inflation: commodity-linked equities rise while broad equities come under pressure → they hedge inflation risk
- During falling inflation: equities rise while commodity-linked assets come under pressure → equities drive returns
- Gold ETF (`GLD` / `MNT.TO`): low correlation with US/Canada equities and effective for tail-risk hedging

### 5. Hedge-Ratio Calculation Methods

**Comparison of three methods:**

```python
import numpy as np
from scipy import stats

# Method 1: OLS regression (simplest)
slope, intercept, r, p, se = stats.linregress(hedge_returns, portfolio_returns)
hedge_ratio_ols = slope

# Method 2: Minimum variance
covariance = np.cov(portfolio_returns, hedge_returns)[0][1]
variance_hedge = np.var(hedge_returns)
hedge_ratio_mv = covariance / variance_hedge

# Method 3: EWMA (exponentially weighted, more sensitive)
lambda_param = 0.94  # RiskMetrics default
ewma_cov = pd.Series(portfolio_returns * hedge_returns).ewm(alpha=1-lambda_param).mean()
ewma_var = pd.Series(hedge_returns**2).ewm(alpha=1-lambda_param).mean()
hedge_ratio_ewma = ewma_cov / ewma_var

# Selection guidance:
# Static hedge (monthly rebalance) -> OLS
# Dynamic hedge (weekly rebalance) -> EWMA
# Theoretical analysis -> minimum variance
```

### 6. Hedging Cost Evaluation

**Cost components:**

| Cost Item | Futures Hedge | Options Hedge | Cross-Asset Hedge |
|--------|---------|---------|-----------|
| Direct cost | Margin usage + fees | Premium | Allocation to lower-yield assets |
| Opportunity cost | Basis cost (discount / premium) | Time decay (Theta) | Earn less in a bull market |
| Hidden cost | Roll cost | Volatility premium | Rebalancing transaction costs |
| Annualized estimate | 2-5% (including basis) | 3-8% (depends on IV) | 1-3% (opportunity cost) |

**Cost-benefit decision framework:**

```python
# Is the hedge worth it?
hedge_cost_annual = 0.04           # 4% annualized
expected_loss_without_hedge = 0.15 # 15% expected max loss without hedge
prob_of_loss = 0.25                # 25% probability

expected_loss = expected_loss_without_hedge * prob_of_loss  # = 3.75%

# If hedge_cost > expected_loss -> hedge is relatively expensive
# If hedge_cost < expected_loss -> hedge is cost-effective
# Here 4% > 3.75%, so the hedge is marginally expensive, but it may still be worth it because of tail risk
```

## Analysis Framework

### Five-Step Hedging Design Process

1. **Identify the risk**: what kind of risk does the portfolio face? Systematic (beta) or idiosyncratic (single-name events)?
2. **Choose the instrument**: linear (futures / ETF) or nonlinear (options)? This depends on the risk shape and budget
3. **Calculate the ratio**: determine the number of hedge contracts or option lots
4. **Evaluate the cost**: what is the annualized cost, and is it acceptable?
5. **Monitor and adjust**: hedge ratios require dynamic adjustment (beta changes, options expire)

### Risk Scenario → Hedge Instrument Mapping

| Risk Scenario | Recommended Instrument | Cost Level |
|---------|---------|---------|
| Systematic broad-market selloff | Short index ETF (SPY / XIU.TO) or buy index puts | Low (fees + borrow) |
| Moderate drawdown (5-10%) | Collar / Put Spread | Low (zero-cost collar) |
| Black swan (>20% crash) | Far OTM put / VIX calls | Medium (continuous spending) |
| Rising rates | Reduce duration; Treasury ETF (TLT) as the rate expression — bond futures are not wired into this build | Low |
| Currency depreciation | Quantify CAD/USD exposure of the Canadian sleeve — FX execution is not available in this build | n/a |
| Inflation upside surprise | Allocate to gold or commodity-linked equities / ETFs | Low (opportunity cost) |

## Output Format

```
## Hedging Plan — [Portfolio Name]

### Portfolio Overview
- Portfolio size: [USD / CAD notional]
- Portfolio beta: [X.XX] (vs [benchmark index])
- Main risk: [systematic / sector concentration / tail]

### Hedging Plan
- Instrument: [short IF futures / Collar / Put Spread / ...]
- Hedge ratio: [X.XX]
- Number of contracts / option lots: [N]
- Hedge coverage: [X%] (full / partial hedge)

### Cost Evaluation
- Direct cost: [USD / CAD per year]
- Annualized cost ratio: [X%]
- Margin / premium usage: [USD / CAD]

### Scenario Analysis
| Market Move | PnL Without Hedge | PnL With Hedge | Hedge Effect |
|---------|-----------|-----------|---------|
| Down 10% | -X | -X | Reduce loss by X |
| Down 20% | -X | -X | Reduce loss by X |
| Up 10% | +X | +X | Give up X of upside |

### Execution Notes
- Entry timing: [specific time / condition]
- Rebalance frequency: [monthly / quarterly / event-driven]
- Exit condition: [risk resolution criterion]
```

## Notes

- This build has no index-futures execution path: size beta hedges against the ETF's ADV and listed-option open interest instead. Option-implied vol is retrievable for **US-listed underlyings only** (`get_options_chain`); for a Canada-only name, state the vol assumption you used and label it an assumption
- Option liquidity is concentrated in near-month and near-the-money contracts; deep OTM options have wide bid-ask spreads
- Beta is unstable: beta tends to be lower in bull markets and higher in bear markets (meaning the hedge is least sufficient when it is needed most)
- Collar strategies cap upside, so large rallies in the underlying can materially drag portfolio performance
- Tail hedging (far OTM puts) loses money most of the time and requires discipline to execute continuously; do not abandon it halfway because it "feels wasteful"
- Correlations in cross-asset hedges can change violently during crises (trending toward 1), failing exactly when they are needed most
- Hedge plans should be re-evaluated regularly (at least monthly) for beta and cost
- This framework is for research backtesting only, does not constitute investment advice, and does not involve live trading execution
