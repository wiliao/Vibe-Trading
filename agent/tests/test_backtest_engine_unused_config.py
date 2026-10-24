"""Engine-specific configuration warnings use the actual selected rule books.

US/CA adaptation of the upstream test: the rule books this fork ships are
``GlobalEquityEngine`` (US and Canada submarkets) and ``CompositeEngine``, so
the "key nobody in the selected rules reads" case is an options-engine setting
in an equity run rather than a crypto fee in a crypto run.
"""

import json
from pathlib import Path

import pandas as pd

from backtest.engines.composite import CompositeEngine
from backtest.engines.global_equity import GlobalEquityEngine
from backtest.runner import _AutoLoader, _create_market_engine

_BARS = pd.DataFrame(
    {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0},
    index=pd.date_range("2024-01-01", periods=6),
)


class _FlatSignalEngine:
    """Signal engine that never trades, so the run exercises the rules only."""

    def generate(self, data_map: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        return {code: pd.Series(0.0, index=_BARS.index) for code in data_map}


def test_unused_options_setting_is_visible_in_real_run_card(tmp_path: Path) -> None:
    config = {
        "codes": ["AAPL.US"],
        "source": "yahoo",
        "start_date": "2024-01-01",
        "end_date": "2024-01-06",
        "initial_cash": 1000,
        "options_config": {"iv": 0.3},
    }
    engine = _create_market_engine("yahoo", config, config["codes"])
    assert isinstance(engine, GlobalEquityEngine)
    # This key does not configure US equities: the genuine slippage remains the default.
    assert engine.slippage_us == 0.0005

    engine.run_backtest(
        config, _AutoLoader({"AAPL.US": _BARS}), _FlatSignalEngine(), tmp_path
    )
    card = json.loads((tmp_path / "run_card.json").read_text())
    assert any(
        "options_config" in warning and "unused" in warning
        for warning in card["warnings"]
    )


def test_active_settings_are_not_reported_unused() -> None:
    config = {
        "codes": ["SHOP.TO"],
        "ca_commission": 0.001,
        "slippage_ca": 0.002,
        "content_filter_warnings": [],
        "model_training_cutoff": "2023-12-31",
    }
    engine = _create_market_engine("yahoo", config, config["codes"])
    assert engine.ca_commission == 0.001
    assert engine.slippage_ca == 0.002
    assert not config.get("_run_card_unrecognized_config_warning")


def test_canadian_rules_ignore_the_unsupported_us_commission_key() -> None:
    config = {"codes": ["SHOP.TO"], "commission": 0.001}
    engine = _create_market_engine("yahoo", config, config["codes"])
    assert isinstance(engine, GlobalEquityEngine)
    warning = config.get("_run_card_unrecognized_config_warning")
    assert warning is not None and "commission" in warning


def test_composite_includes_config_read_by_its_actual_subengines() -> None:
    config = {"codes": ["AAPL.US", "^GSPC"], "slippage_us": 0.001}
    engine = _create_market_engine("auto", config, config["codes"])
    assert isinstance(engine, CompositeEngine)
    assert engine._rule_engines["us_equity"].slippage_us == 0.001
    assert engine._rule_engines["index"].slippage_us == 0.001
    assert not config.get("_run_card_unrecognized_config_warning")
