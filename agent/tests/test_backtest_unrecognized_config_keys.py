"""Regression tests for unrecognized backtest config keys (#1934).

An agent-written ``initial_capital`` used to validate cleanly (extras are
allowed so engine keys flow through) and then be silently dropped by the
engine, so the run proceeded at 10x the intended capital while reporting
confident metrics. The lint is deliberately path-wide: a key is flagged only
when nothing on the backtest path reads it, so engine-namespaced keys like
``options_config`` (read by the options portfolio engine, not the equity
engines) are not false-flagged.
"""

from __future__ import annotations

from backtest.runner import _known_config_keys, _unrecognized_config_warning


def test_misspelled_capital_key_is_flagged_and_other_engine_keys_are_not() -> None:
    config = {
        "codes": ["AAPL.US"],
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "options_config": {"iv": 0.3},
        "source": "yahoo",
        "interval": "1D",
    }
    warning = _unrecognized_config_warning(config)
    assert warning is not None
    assert "'initial_capital'" in warning
    # The misspelling is pointed at the key the engine actually reads.
    assert "'initial_cash'" in warning
    # options_config is a real options-portfolio engine key, so the path-wide
    # lint must not flag it on an equity run (per-engine namespacing is a
    # separate, wider change); this case pins that conservative contract down.
    assert "'options_config'" not in warning


def test_engine_keys_and_runner_internals_are_not_flagged() -> None:
    config = {
        "codes": ["SHOP.TO"],
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "initial_cash": 100000,
        "slippage_us": 0.0005,
        "slippage_ca": 0.001,
        "ca_commission": 0.001,
        "leverage": 2.0,
        "options_config": {"iv": 0.3},
        "source": "yahoo",
        "engine": "composite",
        "interval": "1D",
        "_run_card_effective_sources": {"SHOP.TO": "yahoo"},
    }
    assert _unrecognized_config_warning(config) is None


def test_known_keys_cover_engine_and_loader_reads() -> None:
    known = _known_config_keys()
    for key in ("initial_cash", "slippage_us", "slippage_ca", "ca_commission", "benchmark"):
        assert key in known


def test_shared_path_config_is_not_reported_as_ignored() -> None:
    """Constraints and provenance have real readers outside engine modules."""
    assert _unrecognized_config_warning({
        "constraints": [{"type": "turnover_aware", "max_turnover": 0.1}],
        "model_training_cutoff": "2023-12-31",
    }) is None
