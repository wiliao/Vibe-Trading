"""Backtest engines for the US / Canada equity build.

  - BaseEngine: ABC for bar-by-bar execution with market rules
  - GlobalEquityEngine: US and Canada equity (``market="us" | "ca"``)
  - CompositeEngine: multi-market engine with a shared capital pool
  - options_portfolio: European/American options (Black-Scholes)
  - _market_hooks: shared symbol -> market classification helpers

Inheritance:
  BaseEngine
  ├── GlobalEquityEngine
  └── CompositeEngine (delegates to sub-engines as rule providers)
"""
