"""Replayable US/CA deletion set (docs/refactor-plan.md, Phase 1 step 3).

After an upstream sync re-introduces region-only files, re-run this script to
re-apply the deletions:

    python agent/scripts/us_ca_prune.py --check     # list + verify (default)
    python agent/scripts/us_ca_prune.py --apply     # delete the listed paths

Each entry is ``(path, kind, phase, reason)`` where ``kind`` is ``"file"`` or
``"dir"`` and ``path`` is relative to the repository root. Phases map to the
workstreams in the refactor plan; files deleted in Phase 1 itself (the trim of
``registry.py`` / ``_market_hooks.py`` / ``market_data.py`` tables) are data
edits, not file deletions, so they do not appear here.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# (path, kind, phase, reason)
DELETIONS: list[tuple[str, str, str, str]] = [
    # --- Phase 2: data loaders -------------------------------------------------
    ("agent/backtest/loaders/tushare.py", "file", "2", "A-share/fund loader"),
    ("agent/backtest/loaders/tushare_fundamentals.py", "file", "2", "A-share fundamentals"),
    ("agent/backtest/loaders/baostock_loader.py", "file", "2", "A-share BaoStock source"),
    ("agent/backtest/loaders/mootdx_loader.py", "file", "2", "A-share TDX source"),
    ("agent/backtest/loaders/tencent_loader.py", "file", "2", "A-share/HK Tencent source"),
    ("agent/backtest/loaders/gildata_loader.py", "file", "2", "A-share key-gated vendor"),
    ("agent/backtest/loaders/futu.py", "file", "2", "HK Futu broker feed"),
    ("agent/backtest/loaders/india_broker_loader.py", "file", "2", "India broker feed"),
    ("agent/backtest/loaders/pykrx_loader.py", "file", "2", "Korea KRX source"),
    ("agent/backtest/loaders/okx.py", "file", "2", "crypto OKX exchange"),
    ("agent/backtest/loaders/binance_loader.py", "file", "2", "crypto Binance exchange"),
    ("agent/backtest/loaders/ccxt_loader.py", "file", "2", "crypto generic CCXT"),
    ("agent/backtest/loaders/nobitex.py", "file", "2", "Iran Toman crypto"),
    ("agent/backtest/loaders/wallex.py", "file", "2", "Iran Toman crypto"),
    ("agent/backtest/loaders/mt5_loader.py", "file", "2", "forex/futures MetaTrader bridge"),
    ("agent/backtest/loaders/tickerall_loader.py", "file", "2", "premium aggregator"),
    ("agent/backtest/loaders/qveris_loader.py", "file", "2", "premium aggregator"),
    ("agent/backtest/loaders/cn_adjust.py", "file", "2", "A-share adjustment factors"),
    # eastmoney_client.py is conditional (kept if the US eastmoney path uses it).

    # --- Phase 3: backtest engines + crypto evidence --------------------------
    ("agent/backtest/engines/china_a.py", "file", "3", "A-share engine"),
    ("agent/backtest/engines/china_futures.py", "file", "3", "China futures engine"),
    ("agent/backtest/engines/india_equity.py", "file", "3", "India engine"),
    ("agent/backtest/engines/korea_equity.py", "file", "3", "Korea engine"),
    ("agent/backtest/engines/vietnam_equity.py", "file", "3", "Vietnam engine"),
    ("agent/backtest/engines/crypto.py", "file", "3", "crypto engine"),
    ("agent/backtest/engines/forex.py", "file", "3", "forex engine"),
    ("agent/backtest/engines/futures_base.py", "file", "3", "futures base"),
    ("agent/backtest/engines/global_futures.py", "file", "3", "global futures engine"),
    ("agent/backtest/binance_account_reconciliation.py", "file", "3", "crypto-only"),
    ("agent/backtest/binance_shadow_evidence.py", "file", "3", "crypto-only"),
    ("agent/backtest/binance_tolerance_calibration.py", "file", "3", "crypto-only"),
    ("agent/backtest/perpetual_evidence.py", "file", "3", "crypto-only"),
    ("agent/backtest/perpetual_risk.py", "file", "3", "crypto-only"),

    # --- Phase 4: factor zoo ---------------------------------------------------
    ("agent/src/factors/zoo/gtja191", "dir", "4", "192 A-share-only alphas"),
    ("wiki/research-lab/posts/alpha-191-in-2026.html", "file", "4", "GTJA191 post"),
    ("agent/scripts/w4a_patch_blog.py", "file", "4", "GTJA191 blog patcher"),

    # --- Phase 5: agent tools --------------------------------------------------
    ("agent/src/tools/block_trades_tool.py", "file", "5", "A-share block trades"),
    ("agent/src/tools/dragon_tiger_tool.py", "file", "5", "A-share dragon/tiger"),
    ("agent/src/tools/margin_trading_tool.py", "file", "5", "A-share margin"),
    ("agent/src/tools/northbound_tool.py", "file", "5", "A-share northbound flow"),
    ("agent/src/tools/shareholder_count_tool.py", "file", "5", "A-share holders"),
    ("agent/src/tools/lockup_expiry_tool.py", "file", "5", "A-share lockup"),
    ("agent/src/tools/sector_tool.py", "file", "5", "A-share sector info"),
    ("agent/src/tools/research_reports_tool.py", "file", "5", "A-share reports"),
    ("agent/src/tools/iwencai_tool.py", "file", "5", "A-share iwencai search"),
    ("agent/src/tools/taiwan_stock_data_tool.py", "file", "5", "Taiwan market"),
    ("agent/src/tools/tushare_fallbacks.py", "file", "5", "A-share fallback support"),
    # market_screener_tool.py is ported to SP500 (decision D5), not deleted.

    # --- Phase 6: broker connectors -------------------------------------------
    ("agent/src/trading/connectors/okx", "dir", "6", "crypto connector"),
    ("agent/src/trading/connectors/binance", "dir", "6", "crypto connector"),
    ("agent/src/trading/connectors/upbit", "dir", "6", "Korea crypto connector"),
    ("agent/src/trading/connectors/dhan", "dir", "6", "India connector"),
    ("agent/src/trading/connectors/shoonya", "dir", "6", "India connector"),
    ("agent/src/trading/connectors/zerodha", "dir", "6", "India connector"),
    ("agent/src/trading/connectors/kis", "dir", "6", "Korea connector"),
    ("agent/src/trading/connectors/toss", "dir", "6", "Korea connector"),
    ("agent/src/trading/connectors/scalable", "dir", "6", "EU connector"),
    ("agent/src/trading/connectors/trading212", "dir", "6", "EU connector"),
    ("agent/src/trading/connectors/mt5", "dir", "6", "MetaTrader connector"),

    # --- Phase 7: bundled skills ----------------------------------------------
    # China / HK
    ("agent/src/skills/akshare", "dir", "7", "A-share skill"),
    ("agent/src/skills/tushare", "dir", "7", "A-share skill"),
    ("agent/src/skills/eastmoney", "dir", "7", "A-share skill"),
    ("agent/src/skills/mootdx", "dir", "7", "A-share skill"),
    ("agent/src/skills/ashare-pre-st-filter", "dir", "7", "A-share skill"),
    ("agent/src/skills/hk-connect-flow", "dir", "7", "HK skill"),
    ("agent/src/skills/adr-hshare", "dir", "7", "HK/ADR skill"),
    ("agent/src/skills/convertible-bond", "dir", "7", "A-share skill"),
    ("agent/src/skills/regulatory-knowledge", "dir", "7", "A-share skill"),
    ("agent/src/skills/sector-rotation", "dir", "7", "A-share skill"),
    ("agent/src/skills/sentiment-analysis", "dir", "7", "A-share skill"),
    ("agent/src/skills/earnings-forecast", "dir", "7", "A-share skill"),
    ("agent/src/skills/financial-statement", "dir", "7", "A-share skill"),
    ("agent/src/skills/fund-analysis", "dir", "7", "A-share skill"),
    ("agent/src/skills/etf-analysis", "dir", "7", "A-share skill"),
    ("agent/src/skills/trade-journal", "dir", "7", "A-share skill"),
    ("agent/src/skills/fundamental-filter", "dir", "7", "A-share skill"),
    ("agent/src/skills/chanlun", "dir", "7", "A-share skill"),
    ("agent/src/skills/pine-script", "dir", "7", "A-share skill"),
    ("agent/src/skills/corporate-events", "dir", "7", "A-share skill"),
    # Crypto
    ("agent/src/skills/ccxt", "dir", "7", "crypto skill"),
    ("agent/src/skills/okx-market", "dir", "7", "crypto skill"),
    ("agent/src/skills/crypto-derivatives", "dir", "7", "crypto skill"),
    ("agent/src/skills/defi-yield", "dir", "7", "crypto skill"),
    ("agent/src/skills/onchain-analysis", "dir", "7", "crypto skill"),
    ("agent/src/skills/stablecoin-flow", "dir", "7", "crypto skill"),
    ("agent/src/skills/token-unlock-treasury", "dir", "7", "crypto skill"),
    ("agent/src/skills/perp-funding-basis", "dir", "7", "crypto skill"),
    ("agent/src/skills/liquidation-heatmap", "dir", "7", "crypto skill"),
    # Futures / FX
    ("agent/src/skills/commodity-analysis", "dir", "7", "futures skill"),
    ("agent/src/skills/vnpy-export", "dir", "7", "futures skill"),
    ("agent/src/skills/global-macro", "dir", "7", "macro/FX skill"),
    # Orphan (no SKILL.md, no references)
    ("agent/skills/ashare-mootdx", "dir", "7", "orphan A-share skill"),
]


def _resolve(path: str) -> Path:
    return REPO_ROOT / path


def check() -> int:
    """Report each deletion and whether the path currently exists."""
    missing = 0
    for path, kind, phase, reason in DELETIONS:
        p = _resolve(path)
        marker = "PRESENT" if p.exists() else "gone   "
        if not p.exists():
            missing += 1
        print(f"[{marker}] ({phase}) {kind:<4} {path:<55} {reason}")
    print(f"\n{len(DELETIONS)} deletions, {missing} already absent.")
    return 0


def apply_deletions() -> int:
    """Delete every listed path that still exists."""
    removed = 0
    for path, kind, _phase, reason in DELETIONS:
        p = _resolve(path)
        if not p.exists():
            continue
        if kind == "dir":
            shutil.rmtree(p)
        else:
            p.unlink()
        removed += 1
        print(f"removed ({kind}) {path}  # {reason}")
    print(f"\n{removed} paths removed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay the US/CA deletion set.")
    parser.add_argument("--apply", action="store_true", help="delete listed paths (default: check only)")
    args = parser.parse_args(argv)
    return apply_deletions() if args.apply else check()


if __name__ == "__main__":
    sys.exit(main())
