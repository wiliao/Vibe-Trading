from __future__ import annotations

from decimal import Decimal

import pytest

from src.portfolio.compatibility import adapt_and_validate_payloads
from src.portfolio.config import PortfolioSettingsStore
from src.portfolio.normalization import normalize_position
from src.portfolio.service import PORTFOLIO_VALUATION_VERSION, PortfolioService
from src.portfolio.store import PortfolioStore
from src.trading.connectors.futu import sdk as futu_sdk

USD_CAD = Decimal("1.25")
SNAPSHOT_AT = "2000-01-01T00:00:00+00:00"


def _settings_store(tmp_path) -> PortfolioSettingsStore:
    settings = PortfolioSettingsStore(tmp_path / "portfolio.json")
    settings.connection_store.ensure(
        "futu-test",
        "futu-live-sdk-readonly",
        "Synthetic Futu",
    )
    settings.save(
        {
            "display_currency": "USD",
            "sources": [
                {
                    "connection_id": "futu-test",
                    "label": "Synthetic Futu",
                    "order": 0,
                }
            ],
        }
    )
    return settings


def _service(tmp_path, account: dict, position: dict) -> PortfolioService:
    return PortfolioService(
        PortfolioStore(tmp_path / "portfolio.sqlite3"),
        settings_store=_settings_store(tmp_path),
        get_account=lambda profile_id: {"assets": [account]},
        get_positions=lambda profile_id: {"positions": [position]},
        get_quote=lambda *args, **kwargs: {},
        fx_fetcher=lambda: (USD_CAD, SNAPSHOT_AT),
    )


def test_futu_cad_position_and_account_total_are_converted_to_usd(tmp_path) -> None:
    account = futu_sdk._account_to_dict(
        {
            "total_assets": "1600",
            "cash": "800",
            "market_val": "800",
            "currency": "CAD",
        }
    )
    position = futu_sdk._position_to_dict(
        {
            "code": "SHOP.TO",
            "qty": "100",
            "cost_price": "10",
            "market_val": "800",
            "pl_val": "-200",
            "position_market": "CA",
            "currency": "CAD",
        }
    )

    snapshot = _service(tmp_path, account, position).refresh()
    holding = snapshot["positions"][0]

    assert holding["symbol"] == "SHOP.TO"
    assert holding["market"] == "CA"
    assert holding["currency"] == "CAD"
    assert holding["price_currency"] == "CAD"
    assert holding["market_value_usd"] == pytest.approx(640.0)
    assert holding["unrealized_pnl_usd"] == pytest.approx(-160.0)
    assert snapshot["totals"]["usd"] == pytest.approx(1280.0)
    assert snapshot["totals"]["cad"] == pytest.approx(1600.0)


def test_account_currency_propagates_cad_onto_rows_that_declare_none() -> None:
    """The CAD path is the account's declared currency, not a ticker guess.

    A Canadian row that declares no currency of its own inherits the account's
    CAD, so the valuation uses the USD/CAD rate instead of assuming USD.
    """
    account, positions = adapt_and_validate_payloads(
        "futu",
        {"account": {"currency": "CAD", "total_equity": "1600"}},
        {"positions": [{"symbol": "SHOP.TO", "quantity": 100, "market_val": "800"}]},
    )

    assert account["account"]["currency"] == "CAD"
    assert positions["positions"][0]["currency"] == "CAD"


def test_a_market_without_currency_keeps_the_usd_fallback() -> None:
    """A venue name alone never decides the valuation currency."""
    row = normalize_position(
        "examplebroker",
        {
            "symbol": "SYNTHETIC",
            "market": "TSE",
            "quantity": 2,
            "market_price": 10,
        },
    )

    assert row["currency"] == "USD"
    assert row["price_currency"] == "USD"


def test_legacy_valuation_snapshots_do_not_mix_with_current_history(tmp_path) -> None:
    store = PortfolioStore(tmp_path / "portfolio.sqlite3")
    store.save_snapshot(
        {
            "snapshot_id": "legacy-v1",
            "created_at": "1999-12-31T23:00:00+00:00",
            "complete": True,
            "totals": {"usd": 1600.0, "cad": 2000.0},
            "accounts": [
                {
                    "source_id": "futu-test",
                    "broker": "futu",
                    "status": "ok",
                }
            ],
            "positions": [],
        }
    )
    account = futu_sdk._account_to_dict(
        {"total_assets": "1600", "cash": "800", "currency": "CAD"}
    )
    position = futu_sdk._position_to_dict(
        {
            "code": "SHOP.TO",
            "qty": "100",
            "cost_price": "10",
            "market_val": "800",
            "position_market": "CA",
            "currency": "CAD",
        }
    )
    service = _service(tmp_path, account, position)

    assert service.latest() is None

    current = service.refresh()

    assert current["valuation_version"] == PORTFOLIO_VALUATION_VERSION
    assert [row["id"] for row in service.history()] == [current["snapshot_id"]]
    assert [row["id"] for row in store.history()] == [
        "legacy-v1",
        current["snapshot_id"],
    ]
