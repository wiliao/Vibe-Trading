---
name: US & Canada Money Flow Review
description: Post-close North American flow review — consolidated and off-venue volume, fund and order-size flow, margin balances and the day's biggest movers.
markets: [us, ca]
suggested_schedule: "0 18 * * 1-5"
suggested_timezone: America/New_York
data_capabilities:
  - Exchange and consolidated-tape volume, turnover and closing prices for the session
  - Off-venue and dark-pool volume shares published for the session
  - Fund creation and redemption flow for broad-market and sector ETFs
  - Per-stock and per-sector money flow broken down by order size
  - Margin debt and securities-lending balances in aggregate and by name
  - Sector and industry performance rankings for the session
  - Daily price, volume and turnover history for individual US and Canadian tickers
variables:
  watchlist: (no watch list configured)
---

# US and Canada money flow review

Review where money actually went in the US and Canadian equity session that
just closed.

Resolve the current date from the run environment and confirm the session date
from the retrieved data itself. On a holiday or a half-day the newest available
session may not be today — say which date the report covers, and say it in the
first line.

## Inputs

- Watch list: {{watchlist}}

The watch list only adds a final cross-reference section. The rest of the
report is market-wide and runs with or without it.

## Data to gather

1. The session's consolidated volume, turnover and closing prints for the major
   US and Canadian indices, and the share of that volume executed away from the
   primary listing venue, at whatever granularity the source publishes.
2. Fund flow for broad-market and sector ETFs: creations, redemptions and net
   flow for the session.
3. Money flow by order size, both at the sector level and for the day's most
   active names.
4. Margin debt and securities-lending balances, in aggregate and for any name
   that moved sharply.
5. Sector and industry performance for the session, ranked, for both markets.
6. The day's largest gainers and decliners, the names that closed at a new
   52-week extreme, and the turnover behind them.
7. For each watch-list symbol, its session return, turnover, and whether it
   appeared in any of the above.

## Method

- US and Canadian venues apply different halt, tick-size and settlement rules,
  and a stock can trade on more than one venue. Determine the venue and
  currency from the retrieved data rather than assuming one convention for both
  markets, and label every figure with its venue and currency.
- Off-venue prints identify a venue type, not an investor. Describe what the
  data literally shows — this share of volume executed away from the listing
  venue — and do not name or characterise who was behind it.
- Fund-flow data is reported net and often revised. Use the figure the source
  published for the session and say which vintage it is; do not reconstruct an
  intraday path from an end-of-day number.
- Cross-check the day's story: a sector leading on performance but not on money
  flow, or a big mover with no matching flow, is worth one line as a
  contradiction rather than being smoothed over.
- Report flow in the currency and unit the source used, and label the unit. A
  Canadian figure in Canadian dollars is not a US figure.

## When data is missing

A source that returns nothing, errors out, or is not configured is a fact to
report, not a gap to fill.

- Name every missing item explicitly in a `Data gaps` section, with the reason
  when the failure gave one.
- Continue using only the evidence actually retrieved.
- Never substitute a value from memory, from a general prior, from a
  third-party summary, or from an earlier run of this playbook. A flow number
  that did not come back on this run does not appear in this report.
- Never present a stale figure as current. Several of these series are
  published at different times after the close and some only monthly; if the
  newest available record is from a previous session, print its date beside it
  and label it as the previous session, not as today.
- If a whole section has no evidence, keep its heading and write
  `no data retrieved` under it.
- Every figure carries its session date, its unit, and the source it came from.

## Output

Markdown, in this order:

1. `## Session` — the date this report covers and the index closes for it.
2. `## Participation` — consolidated volume and the off-venue share, with the
   granularity stated.
3. `## Fund flow` — ranked table: fund or sector, session return, net flow, unit.
4. `## Sector flow` — ranked table: sector, session return, net flow, unit.
5. `## Movers` — largest gainers and decliners, any new 52-week extreme, and
   the turnover behind them.
6. `## Margin balances` — aggregate change and any notable per-stock change.
7. `## Watch list cross-reference` — omit when no watch list was supplied.
8. `## Data gaps` — always present; write `none` when nothing was missing.
9. `## Verdict` — the machine-readable tail, and the only section
   nothing may follow. One line per symbol tracked this run:
   `- SYMBOL: STATE - one short reason`, with STATE one of `ACTIVE`, `QUIET`.
   When nothing moved, write the heading with no lines under it; that
   is a real answer, not an absence. This section reports state, not
   advice: the Boundaries above still apply.

## Boundaries

- Factual review of one session. No buy, sell, or hold calls, no price
  targets, no next-day predictions.
- Do not place, modify, or cancel any order, and do not touch a live trading
  connector.
- Do not attribute flows to a named institution, fund, or individual. Report
  the disclosed venue and amount.
- Concentrated buying is an observation, not a signal. Say what was reported
  and stop there.
