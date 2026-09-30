---
name: market-microstructure
description: "Market microstructure: bid-ask spread analysis, order-flow toxicity metrics (VPIN / Kyle lambda), liquidity measures (Amihud / Roll), price-impact models, limit-order-book analysis, and US / Canada opening and closing auction mechanics."
category: analysis
---

# Market Microstructure

## Overview

Study the micro-level mechanisms of price formation: who is trading, how they are trading, and how trades affect prices. For quantitative strategies, this matters because it improves transaction-cost estimation, identifies informed trading, and optimizes execution.

Applicable scenarios:
- Precise estimation of strategy trading costs (instead of simply assuming a flat 0.1% fee)
- Designing large-order execution strategies (`TWAP / VWAP / IS`)
- Detecting order-flow toxicity (avoid time windows dominated by informed traders)
- Quantifying liquidity risk (flash-crash warning)
- Capturing US / Canada market-structure features (opening auction / closing auction / block prints)

## Core Concepts

### Bid-Ask Spread

**Three measurements:**
| Metric | Formula | Meaning |
|------|------|------|
| Quoted spread | `Ask - Bid` | Best spread shown in the limit order book |
| Effective spread | `2 × |trade price - mid price|` | Actual spread paid by the trader |
| Realized spread | `2 × direction × (trade price - mid price 5min later)` | True market-maker profit |

```
US equity example:
  Instrument: AAPL
  Best bid: 228.40  Best ask: 228.42
  Quoted spread: 0.02 USD = 0.01%

  Instrument: a mid-cap industrial
  Best bid: 41.05  Best ask: 41.08
  Quoted spread: 0.03 USD = 0.07%

Spread decomposition (Roll):
  Spread = adverse-selection cost + inventory cost + order-processing cost
  Estimate the split from your own trade sample; do not assume a fixed
  adverse-selection share — it varies by name, venue and regime

Spread drivers:
  - Larger market cap -> smaller spread (mega-cap 0.01% vs small-cap 0.5%)
  - Higher volatility -> wider spread (market-maker risk premium)
  - Higher volume -> narrower spread (greater competition)
  - Higher information asymmetry -> wider spread (adverse selection)
```

### Order-Flow Toxicity Metrics

**VPIN (Volume-Synchronized Probability of Informed Trading):**
```
Principle: replace clock time with volume time to measure the probability of informed trading

Calculation steps:
  1. Bucket trades by fixed volume (Volume Bucket)
     Bucket size V = average daily volume / 50 (about 5-10 minutes per bucket)

  2. Classify buy and sell volume in each bucket (Bulk Volume Classification):
     buy_volume = V × Φ(ΔP / σ)  (standard normal CDF)
     sell_volume = V - buy_volume

  3. Compute order-flow imbalance:
     OI_i = |buy_volume_i - sell_volume_i|

  4. VPIN = Σ(OI_i) / (n × V)  (n=50-bucket rolling window)

Interpretation:
  VPIN < 0.3 -> normal, low informed-trading share
  VPIN 0.3-0.5 -> caution, informed trading rising
  VPIN > 0.5 -> dangerous, high probability that major information is about to be released

US equities usage:
  A sudden VPIN spike in a stock may foreshadow:
  - informed trading ahead of a major announcement
  - institutional position building / distribution
  VPIN was elevated in the run-up to the 2010 US Flash Crash, and the metric
  is best read as a relative, per-name signal against its own history
```

**Kyle's Lambda (price impact coefficient)**:
```
Model: ΔP = λ × OrderFlow + ε
  where OrderFlow = buy volume - sell volume

Estimation method:
  1. Compute ΔP and OrderFlow in 5-minute windows
  2. Regress ΔP = α + λ × OrderFlow
  3. λ = price change caused by one unit of order flow

Interpretation:
  Large λ -> poor liquidity, high impact
  Small λ -> good liquidity, large orders can be executed cheaply

Typical US equity values:
  Large cap (S&P 500): λ ≈ 0.001-0.005
  Mid cap (S&P 400): λ ≈ 0.005-0.02
  Small cap (Russell 2000): λ ≈ 0.02-0.1
```

### Liquidity Measures

| Metric | Formula | Advantages | Disadvantages |
|------|------|------|------|
| Amihud illiquidity | `|R_t| / Volume_t` | Requires only daily data | Sensitive to extreme returns |
| Roll implied spread | `2√(-Cov(R_t, R_{t-1}))` | Requires only daily data | Fails when covariance is positive |
| LOT zero-return ratio | zero-return days / total days | Intuitive | Too coarse |
| Turnover ratio | volume / free float | Simple and intuitive | Does not reflect price impact |
| Traded value | average daily notional | Absolute liquidity | Does not reflect relative impact |

```
Amihud calculation (US / Canada equities):
  ILLIQ = (1/D) × Σ(|R_d| / VOL_d)  (D=trading days, monthly)

  Normalization: ILLIQ × 10^6 (for readability)

  Screening rules:
    ILLIQ < 0.5 -> high liquidity (large-cap blue chips)
    ILLIQ 0.5-5 -> medium liquidity
    ILLIQ > 5 -> low liquidity (trade cautiously)

  Strategy application:
    - Liquidity factor: low-liquidity stocks tend to earn long-run excess return (liquidity premium)
    - Liquidity monitor: sudden rise in ILLIQ -> warning of liquidity drying up
```

## Analysis Framework

### 1. Price-Impact Models

**Power-law impact**:

> **Naming.** This is the concave impact term from the Almgren-Chriss
> literature, and it is neither linear (the exponent is 0.6, not 1) nor
> Almgren-Chriss *optimal execution* — no trading trajectory, no
> permanent/temporary split and no risk-aversion parameter is computed here or
> anywhere in this repo. The tested implementation is
> `src.quantlib.impact.sqrt_impact`; call it rather than retyping the formula.

```
Model: impact = η × σ × (Q / V)^0.6
  η: impact coefficient, about 0.5-1.5 for large-cap US equities (higher for small caps)
  σ: daily volatility
  Q: traded quantity (shares)
  V: average daily volume (shares)

Example:
  Sell 100,000 shares of AAPL
  Average daily volume 50,000,000 shares, daily volatility 1.8%
  impact = 1.0 × 0.018 × (100000/5000000)^0.6
         = 0.018 × 0.0085
         = 0.015% (1.5bp, acceptable)

  Sell 100,000 shares of a small-cap stock
  Average daily volume 500,000 shares, daily volatility 3.0%
  impact = 1.0 × 0.03 × (100000/500000)^0.6
         = 0.03 × 0.076
         = 0.23% (23bp, should be executed in slices)

Execution-splitting methods:
  TWAP: uniform in clock time -> simple but ignores market state
  VWAP: volume-profile execution -> better matches market rhythm
  IS: minimize Implementation Shortfall -> optimal but requires real-time optimization
```

**Nonlinear impact (square-root model)**:
```
impact = σ × √(Q / (ADV × T))
  σ: daily volatility
  Q: total trade size
  ADV: average daily traded value
  T: execution days

Applicable to: large trades (Q/ADV > 5%)
```

### 2. Limit Order Book Analysis

```
Depth metrics:
  Level 1 depth: queue size at the best bid and best ask
  Level 5 depth: total queue size across the first 5 levels
  Depth asymmetry: (Bid depth - Ask depth) / (Bid depth + Ask depth)
    > 0 -> stronger bid side, price tends to rise
    < 0 -> stronger ask side, price tends to fall

Resilience:
  The speed at which the book recovers after a large-order impact
  Fast recovery -> good liquidity, temporary impact
  Slow recovery -> poor liquidity, persistent impact

US equity LOB characteristics (regular session 9:30-16:00 ET):
  - The shallowest depth is in the first 15 minutes after the open (highest information asymmetry)
  - Depth improves from 10:00-10:30 (institutions begin participating)
  - Best depth is from 14:00-15:30 (most intraday information has been digested)
  - During the 15:50-16:00 closing auction, depth changes sharply (late-day rebalancing / index flows)
  - On the TSX the closing auction runs into the 16:00 close, and the TSXV book is materially thinner

Order-book imbalance signal:
  OIR = (Bid_vol - Ask_vol) / (Bid_vol + Ask_vol)
  Rolling 5-minute OIR > 0.3 -> short-term bullish signal (accuracy about 55-60%)
  Note: large orders are often rapidly added and canceled (icebergs / spoofing), so OIR signals need filtering
```

### 3. Flash-Crash Mechanism and Prevention

```
Flash-crash characteristics:
  1. Price drops more than 5% within minutes
  2. Volume first expands, then collapses (liquidity evaporates)
  3. Bid-ask spread widens sharply (market makers pull quotes)
  4. Followed by a V-shaped rebound (not always fully recovered)

Triggers:
  - Large market order + thin liquidity -> punches through multiple levels instantly
  - Stop-loss chain -> initial selloff triggers more stop orders
  - Algo resonance -> multiple trend-following algos sell simultaneously
  - ETF discount arbitrage -> ETF redemption and constituent selling intensify the drop

Preventive measures:
  1. Use limit orders instead of market orders: specify the maximum acceptable price
  2. Monitor VPIN: if VPIN breaks above 0.5 -> stop trading
  3. Liquidity threshold: exclude instruments with Amihud > 10
  4. Spread monitor: if spread widens suddenly to >5x normal -> pause orders
  5. Time avoidance: do not execute large orders in the first 15 minutes after open or the last 5 minutes before close

Flash-crash reference cases (US):
  2010-05-06: the US Flash Crash — major indices fell roughly 9% intraday and
    rebounded within minutes as liquidity evaporated
  2015-08-24: pre-open ETF pricing broke down (ETFs traded far below NAV before
    the underlying market opened)
  Pattern: liquidity dries up -> LULD / circuit-breaker halts trigger -> the
  reopening auction concentrates the imbalance
```

### 4. US / Canada Market-Structure Specifics

```
Opening auction / opening cross (9:30 ET):
  Pre-open: orders can be entered and canceled, mostly probing quotes (low reference value)
  Final minutes before 9:30: orders are locked in, so real intent is revealed
  Signal: a large imbalance in the published opening imbalance -> likely
    gap-up or gap-down open
  Execution: the opening cross prints a single price; a market-on-open order
    cannot be canceled after the cutoff and may fill away from the last pre-open print
  Risk: the final auction price may deviate from expectation in a thin name

Closing auction (15:50-16:00 ET on NYSE, the 16:00 cross on Nasdaq):
  Feature: the closing price is decided in the auction, with concentrated
    institutional rebalancing and index-fund flows
  Signal: closing-auction volume > 10% of the whole day -> institutions are rebalancing
  Strategy application:
  - VWAP algos should finish most of execution before 15:45, leaving a small residual for the close
  - Avoid placing large orders after 15:50 in names with a thin closing book

Block prints:
  **There is no dedicated block-trade feed in this build.** Reconstruct
  large-print proxies from volume clusters in the bars (`get_market_data` +
  `src.quantlib.microstructure`) and label the result a proxy, never a reported block.

  Discount = (large-print price - closing price) / closing price
  Discount < -5%: seller is eager to exit -> short-term bearish
  Discount > -2%: traded near market price -> may be turnover rather than reduction

  Institutional corroboration comes from 13F filings (`get_institutional_holdings`),
  which lag by up to 45 days — treat it as confirmation, not a same-day signal.
```

## Output Format

Microstructure analysis report:
```
=== Liquidity Diagnosis ===
Instrument: AAPL
Date: 2026-03-28
Average daily traded value: USD 12.5 billion  Turnover ratio: 0.85%
Amihud: 0.32 (high liquidity)
Effective spread: 0.02% (1bp)
Kyle Lambda: 0.001

=== Order-Flow Analysis ===
VPIN: 0.28 (normal)
Order-book imbalance (OIR): +0.12 (mild bid-side bias)
Large-print proxy: net buying (volume-cluster estimate, not a reported block)

=== Trading-Cost Estimate ===
Planned trade size: 500,000 shares (about USD 114 million)
Estimated impact cost: 0.08% (USD 91k)
Commission: 0.01% (USD 11k)
Regulatory fees (sell side): <0.01%
Total one-way transaction cost: about 0.10%

=== Execution Suggestion ===
Recommended strategy: VWAP
Execution window: 10:00-15:45 (avoid the open and the closing auction)
Number of slices: 5-8 (about 60k-100k shares per slice)
Time sensitivity: low (VPIN is normal, no urgency to execute)
```

## Notes

1. **Data requirement is high**: microstructure analysis requires tick-level / Level-2 data, while ordinary daily data only supports rough measures such as Amihud / Roll
2. **No L2 ladder in this build**: there is no live ten-level depth feed. Score depth from a stated proxy (turnover, ADV) and say it is a proxy, or leave it out; tick-level data would require a separate vendor
3. **Spoofing is prohibited**: US and Canadian regulators prohibit programmatic quote-cancel manipulation (`spoofing` / layering), so microstructure signals here are for analysis and cost estimation, not for HFT strategies
4. **VPIN calibration**: bucket size has a large impact on results and must be adjusted for instrument liquidity; one parameter does not fit all
5. **Settlement and halts**: US and Canadian equities settle T+1, and both markets use LULD bands and market-wide circuit breakers rather than fixed daily price limits — do not import limit-up/limit-down assumptions from other market structures
6. **Illusion of liquidity**: high turnover in a thin or promotionally traded small-cap (often on the TSXV) does not represent genuine depth

## Dependencies

```bash
pip install pandas numpy scipy
```
