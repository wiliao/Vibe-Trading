"""Tests for the direct-SDK trading connectors (Tiger, Longbridge, Alpaca, Futu).

Layer A is read-only; these tests exercise the parts that do not require the
optional broker SDKs or live credentials: profile registration, the paper/live
identity guard, config resolution, read/write classification, secret redaction,
and the service dispatch degrading cleanly when nothing is configured.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.live.classification import ToolClass
from src.trading.connectors.longbridge import credentials as lb_credentials
from src.trading import profiles, service
from src.trading.connectors.alpaca import sdk as al
from src.trading.connectors.alpaca.classification import ALPACA_TOOL_CLASS
from src.trading.connectors.futu import sdk as ft
from src.trading.connectors.futu.classification import FUTU_TOOL_CLASS
from src.trading.connectors.longbridge import sdk as lb
from src.trading.connectors.longbridge.classification import LONGBRIDGE_TOOL_CLASS
from src.trading.connectors.tiger import sdk as tg
from src.trading.connectors.tiger.classification import TIGER_TOOL_CLASS

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Profile registration
# --------------------------------------------------------------------------- #


def test_sdk_profiles_registered() -> None:
    """All broker connectors register paper and read-only live profiles."""
    ids = {p.id for p in profiles.list_profiles()}
    assert {
        "tiger-paper-sdk", "tiger-live-sdk-readonly",
        "longbridge-paper-sdk", "longbridge-live-sdk-readonly",
        "alpaca-paper-sdk", "alpaca-live-sdk-readonly",
        "futu-paper-sdk", "futu-live-sdk-readonly",
    } <= ids


def test_no_discriminator_brokers_expose_no_live_trade_profile() -> None:
    """Brokers without a runtime paper/live discriminator (Longbridge) must NOT
    register any live order-placing profile — the Longbridge precedent. A
    ``*-live-trade`` profile here would be a red-line regression."""
    ids = {p.id for p in profiles.list_profiles()}
    for broker in ("longbridge",):
        assert f"{broker}-live-trade" not in ids
        # No live profile for these brokers may advertise an order capability.
        for p in profiles.list_profiles():
            if p.connector == broker and p.environment == "live":
                assert not any(".place" in cap or "requires_mandate" in cap for cap in p.capabilities)


@pytest.mark.parametrize(
    "profile_id, connector, environment",
    [
        ("tiger-paper-sdk", "tiger", "paper"),
        ("tiger-live-sdk-readonly", "tiger", "live"),
        ("longbridge-paper-sdk", "longbridge", "paper"),
        ("longbridge-live-sdk-readonly", "longbridge", "live"),
        ("alpaca-paper-sdk", "alpaca", "paper"),
        ("alpaca-live-sdk-readonly", "alpaca", "live"),
        ("futu-paper-sdk", "futu", "paper"),
        ("futu-live-sdk-readonly", "futu", "live"),
    ],
)
def test_sdk_profiles_are_readonly_broker_sdk(profile_id, connector, environment) -> None:
    """Layer A profiles are broker_sdk transport and strictly read-only."""
    profile = profiles.profile_by_id(profile_id)
    assert profile.connector == connector
    assert profile.environment == environment
    assert profile.transport == "broker_sdk"
    assert profile.readonly is True
    # No order-placing / mandate-gated capability is advertised in Layer A.
    assert not any(".place" in cap or "requires_mandate" in cap for cap in profile.capabilities)


# --------------------------------------------------------------------------- #
# Tiger paper/live identity guard (17-digit account rule)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "account, is_paper",
    [
        ("20191106192858300", True),   # 17-digit paper
        ("51230321", False),            # prime/standard
        ("U12300123", False),           # global
        ("", False),
        ("2019110619285830", False),    # 16 digits
        ("201911061928583000", False),  # 18 digits
    ],
)
def test_tiger_is_paper_account(account, is_paper) -> None:
    assert tg.is_paper_account(account) is is_paper


def test_tiger_paper_profile_rejects_live_account() -> None:
    """A paper profile pointed at a non-17-digit account fails closed."""
    cfg = tg.TigerConfig(tiger_id="x", private_key_path="x", account="U12300123", profile="paper")
    with pytest.raises(tg.TigerProfileMismatchError):
        tg._assert_profile(cfg)


def test_tiger_live_profile_rejects_paper_account() -> None:
    """A live profile pointed at a 17-digit paper account fails closed."""
    cfg = tg.TigerConfig(tiger_id="x", private_key_path="x", account="20191106192858300", profile="live-readonly")
    with pytest.raises(tg.TigerProfileMismatchError):
        tg._assert_profile(cfg)


def test_tiger_paper_profile_accepts_paper_account() -> None:
    cfg = tg.TigerConfig(tiger_id="x", private_key_path="x", account="20191106192858300", profile="paper")
    tg._assert_profile(cfg)  # must not raise


# --------------------------------------------------------------------------- #
# Config resolution
# --------------------------------------------------------------------------- #


def test_tiger_build_config_merges_profile_then_overrides(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(tg, "get_runtime_root", lambda: tmp_path)
    cfg = tg.build_config({"profile": "paper"}, {"account": "20191106192858300"})
    assert cfg.profile == "paper"
    assert cfg.account == "20191106192858300"


def test_tiger_invalid_profile_rejected() -> None:
    with pytest.raises(tg.TigerConfigError):
        tg.TigerConfig.from_mapping({"profile": "live-trade-now"})


def test_longbridge_build_config_and_region(monkeypatch, tmp_path) -> None:
    for env_name in (
        "LONGBRIDGE_APP_KEY",
        "LONGBRIDGE_APP_SECRET",
        "LONGBRIDGE_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(lb, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(lb_credentials, "get_runtime_root", lambda: tmp_path)
    cfg = lb.build_config({"profile": "live-readonly", "region": "cn"}, None)
    assert cfg.profile == "live-readonly"
    assert cfg.region == "cn"


def test_longbridge_invalid_region_rejected() -> None:
    with pytest.raises(lb.LongbridgeConfigError):
        lb.LongbridgeConfig.from_mapping({"region": "moon"})


def test_longbridge_with_overrides_preserves_atomic_credentials() -> None:
    cfg = lb.LongbridgeConfig(
        app_key="atomic-key",
        app_secret="atomic-secret",
        access_token="atomic-token",
        _credential_source="environment",
    )

    updated = cfg.with_overrides(
        app_key="ignored-key", profile="live-readonly", region="cn"
    )

    assert (updated.app_key, updated.app_secret, updated.access_token) == (
        "atomic-key",
        "atomic-secret",
        "atomic-token",
    )
    assert updated._credential_source == "environment"
    assert updated.profile == "live-readonly"
    assert updated.region == "cn"


def test_longbridge_public_config_redacts_secrets() -> None:
    """Secret material must never appear in status payloads or config reprs."""
    values = {
        "app_key": "repr-distinctive-app-key-7f31",
        "app_secret": "repr-distinctive-app-secret-8a42",
        "access_token": "repr-distinctive-access-token-9b53",
    }
    cfg = lb.LongbridgeConfig(**values)
    pub = lb._public_config(cfg)
    assert pub["app_secret"] == "***redacted***"
    assert pub["access_token"] == "***redacted***"
    assert pub["app_key"].endswith("***")
    assert all(value not in repr(cfg) for value in values.values())
    assert all(value not in repr(pub) for value in values.values())


def _set_longbridge_environment(monkeypatch, values) -> None:
    for field, env_name in {
        "app_key": "LONGBRIDGE_APP_KEY",
        "app_secret": "LONGBRIDGE_APP_SECRET",
        "access_token": "LONGBRIDGE_ACCESS_TOKEN",
    }.items():
        monkeypatch.setenv(env_name, values[field])


def test_connector_uses_environment_credentials(monkeypatch, tmp_path) -> None:
    values = {
        "app_key": "connector-environment-key",
        "app_secret": "connector-environment-secret",
        "access_token": "connector-environment-token",
    }
    _set_longbridge_environment(monkeypatch, values)
    monkeypatch.setattr(lb, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(lb_credentials, "get_runtime_root", lambda: tmp_path)

    cfg = lb.build_config({"profile": "live-readonly", "region": "cn"}, None)

    assert (cfg.app_key, cfg.app_secret, cfg.access_token) == tuple(values.values())
    assert cfg.profile == "live-readonly"
    assert cfg.region == "cn"
    monkeypatch.setattr(lb, "longbridge_available", lambda: False)
    assert lb.check_status(cfg)["credential_source"] == "environment"


def test_connector_reports_conflict_without_sdk_call(monkeypatch, tmp_path) -> None:
    environment = {
        "app_key": "conflict-environment-key",
        "app_secret": "conflict-environment-secret",
        "access_token": "conflict-environment-token",
    }
    runtime_file = {
        "app_key": "conflict-file-key",
        "app_secret": "conflict-file-secret",
        "access_token": "conflict-file-token",
    }
    _set_longbridge_environment(monkeypatch, environment)
    (tmp_path / "longbridge.json").write_text(json.dumps(runtime_file), encoding="utf-8")
    monkeypatch.setattr(lb, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(lb_credentials, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(
        lb,
        "_trade_context",
        lambda cfg: (_ for _ in ()).throw(AssertionError("SDK must not initialize")),
    )

    report = lb.check_status(lb.build_config())

    assert report["configured"] is False
    assert report["connection_state"] == "error"
    assert report["credential_source"] is None
    assert report["error_code"] == "credentials_conflict"
    assert all(
        field in report["error"]
        for field in ("app_key", "app_secret", "access_token")
    )
    with pytest.raises(lb.LongbridgeConfigError, match="sources conflict"):
        lb._require_resolved_config(lb.build_config())


def test_connector_status_redacts_credentials(monkeypatch, tmp_path) -> None:
    values = {
        "app_key": "status-sensitive-key",
        "app_secret": "status-sensitive-secret",
        "access_token": "status-sensitive-token",
    }
    secret_exception = RuntimeError(
        "authentication failed for " + "/".join(values.values())
    )
    _set_longbridge_environment(monkeypatch, values)
    monkeypatch.setattr(lb, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(lb_credentials, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(lb, "longbridge_available", lambda: True)
    monkeypatch.setattr(
        lb,
        "_trade_context",
        lambda cfg: SimpleNamespace(
            account_balance=lambda: (_ for _ in ()).throw(secret_exception)
        ),
    )

    report = lb.check_status(lb.build_config())
    serialized = str(report)

    assert report["configured"] is True
    assert report["connection_state"] == "error"
    assert report["error_code"] == "authentication_failed"
    assert report["error"] == "Longbridge authentication failed."
    assert all(value not in serialized for value in values.values())
    assert report["error"].__class__ is str
    assert secret_exception not in _exception_chain_from_payload(report)


def _exception_chain_from_payload(payload) -> tuple[BaseException, ...]:
    """Return exceptions publicly reachable from a returned payload."""
    seen: set[int] = set()
    found: list[BaseException] = []
    pending = list(payload.values()) if isinstance(payload, dict) else [payload]
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, BaseException):
            found.append(value)
            if value.__cause__ is not None:
                pending.append(value.__cause__)
            if value.__context__ is not None:
                pending.append(value.__context__)
        elif isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set)):
            pending.extend(value)
    return tuple(found)


# --------------------------------------------------------------------------- #
# Read/write classification (live gate input)
# --------------------------------------------------------------------------- #


def test_tiger_order_ops_classified_write() -> None:
    for name in ("place_order", "cancel_order", "modify_order"):
        assert TIGER_TOOL_CLASS[name] is ToolClass.WRITE
    for name in ("get_assets", "get_positions", "get_bars"):
        assert TIGER_TOOL_CLASS[name] is ToolClass.READ


def test_longbridge_order_ops_classified_write() -> None:
    for name in ("submit_order", "cancel_order", "replace_order"):
        assert LONGBRIDGE_TOOL_CLASS[name] is ToolClass.WRITE
    for name in ("account_balance", "stock_positions", "candlesticks"):
        assert LONGBRIDGE_TOOL_CLASS[name] is ToolClass.READ


# --------------------------------------------------------------------------- #
# Service dispatch degrades cleanly when nothing is configured
# --------------------------------------------------------------------------- #


def test_service_check_connection_unconfigured_tiger(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(tg, "get_runtime_root", lambda: tmp_path)
    result = service.check_connection("tiger-paper-sdk")
    assert result["status"] == "error"
    assert "not configured" in result["error"]
    assert result["connector"] == "tiger"
    assert result["transport"] == "broker_sdk"


def test_service_check_connection_unconfigured_longbridge(monkeypatch, tmp_path) -> None:
    for env_name in (
        "LONGBRIDGE_APP_KEY",
        "LONGBRIDGE_APP_SECRET",
        "LONGBRIDGE_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(lb, "get_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(lb_credentials, "get_runtime_root", lambda: tmp_path)
    result = service.check_connection("longbridge-paper-sdk")
    assert result["status"] == "error"
    assert "not configured" in result["error"]
    assert result["connector"] == "longbridge"
    assert result["transport"] == "broker_sdk"


# --------------------------------------------------------------------------- #
# Alpaca
# --------------------------------------------------------------------------- #


def test_alpaca_paper_live_host_and_flag() -> None:
    assert al.AlpacaConfig(profile="paper").is_paper is True
    assert al.AlpacaConfig(profile="paper").host == al.PAPER_HOST
    assert al.AlpacaConfig(profile="live-readonly").is_paper is False
    assert al.AlpacaConfig(profile="live-readonly").host == al.LIVE_HOST


def test_alpaca_invalid_feed_rejected() -> None:
    with pytest.raises(al.AlpacaConfigError):
        al.AlpacaConfig.from_mapping({"feed": "nasdaq"})


def test_alpaca_redacts_secrets() -> None:
    cfg = al.AlpacaConfig(api_key="AKFOURCHARS", secret_key="topsecret")
    pub = al._public_config(cfg)
    assert pub["secret_key"] == "***redacted***"
    assert "topsecret" not in str(pub)
    assert pub["api_key"].endswith("***")


def test_alpaca_classification() -> None:
    assert ALPACA_TOOL_CLASS["submit_order"] is ToolClass.WRITE
    assert ALPACA_TOOL_CLASS["cancel_order_by_id"] is ToolClass.WRITE
    assert ALPACA_TOOL_CLASS["get_account"] is ToolClass.READ


def test_alpaca_service_unconfigured(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(al, "get_runtime_root", lambda: tmp_path)
    result = service.check_connection("alpaca-paper-sdk")
    assert result["status"] == "error"
    assert result["connector"] == "alpaca"
    assert result["transport"] == "broker_sdk"


# --------------------------------------------------------------------------- #
# Futu (local OpenD gateway)
# --------------------------------------------------------------------------- #


def test_futu_trd_env_mapping() -> None:
    assert ft.FutuConfig(profile="paper").trd_env_name == "SIMULATE"
    assert ft.FutuConfig(profile="live-readonly").trd_env_name == "REAL"


def test_futu_classification() -> None:
    assert FUTU_TOOL_CLASS["place_order"] is ToolClass.WRITE
    assert FUTU_TOOL_CLASS["modify_order"] is ToolClass.WRITE
    assert FUTU_TOOL_CLASS["unlock_trade"] is ToolClass.WRITE
    assert FUTU_TOOL_CLASS["position_list_query"] is ToolClass.READ


def test_futu_service_unconfigured_gateway_down(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ft, "get_runtime_root", lambda: tmp_path)
    result = service.check_connection("futu-paper-sdk")
    # OpenD gateway is not running in CI → clean error, not a crash.
    assert result["status"] == "error"
    assert result["connector"] == "futu"
    assert result["transport"] == "broker_sdk"


# --------------------------------------------------------------------------- #
# Live gate: order ops are WRITE-pinned through the real classifier + registry
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "broker, order_op",
    [
        ("tiger", "place_order"),
        ("longbridge", "submit_order"),
        ("alpaca", "submit_order"),
        ("futu", "place_order"),
    ],
)
def test_order_ops_write_pinned_via_registry(broker, order_op) -> None:
    """Every broker's order op resolves WRITE through the shared classifier."""
    from src.live import registry
    from src.live.classification import classify_tool

    curated = registry._BROKER_CURATED_MAPS[broker]
    assert classify_tool(order_op, None, curated) is ToolClass.WRITE


def test_unknown_op_does_not_classify_read() -> None:
    """An unmapped op resolves to UNKNOWN (never READ); the registry then treats
    UNKNOWN as WRITE (fail-closed) when wrapping the live channel."""
    from src.live import registry
    from src.live.classification import classify_tool

    curated = registry._BROKER_CURATED_MAPS["alpaca"]
    verdict = classify_tool("some_unmapped_future_tool", None, curated)
    assert verdict is not ToolClass.READ
    assert verdict in (ToolClass.WRITE, ToolClass.UNKNOWN)


# --------------------------------------------------------------------------- #
# Period mapping (generic token → per-SDK token)
# --------------------------------------------------------------------------- #


def test_period_maps_distinguish_minute_from_month() -> None:
    """The 1m (minute) vs 1M (month) tokens must not collide in any map."""
    assert tg._PERIOD_MAP["1m"] == "1min" and tg._PERIOD_MAP["1M"] == "month"
    assert ft._KLTYPE_MAP["1m"] == "K_1M" and ft._KLTYPE_MAP["1M"] == "K_MON"


# --------------------------------------------------------------------------- #
# Read-path mapping with stubbed SDK clients (no broker SDK installed)
# --------------------------------------------------------------------------- #


class _FakeLbTrade:
    def today_orders(self):
        return [
            {"order_id": "1", "symbol": "700.HK", "status": "NewStatus", "quantity": 100},
            {"order_id": "2", "symbol": "700.HK", "status": "FilledStatus", "quantity": 100},
            {"order_id": "3", "symbol": "AAPL.US", "status": "CanceledStatus", "quantity": 5},
        ]


def test_longbridge_open_orders_filters_terminal(monkeypatch) -> None:
    monkeypatch.setattr(lb, "_trade_context", lambda cfg: _FakeLbTrade())
    out = lb.get_open_orders(lb.LongbridgeConfig(app_key="k", app_secret="s", access_token="t"))
    ids = [o["order_id"] for o in out["open_orders"]]
    assert ids == ["1"]  # filled + cancelled dropped


def test_longbridge_status_normalization_variants() -> None:
    """Terminal-status filtering must work across SDK string forms."""
    for terminal in ("Filled", "FilledStatus", "OrderStatus.Filled", "CANCELED", "Rejected"):
        assert not lb._is_open_order({"status": terminal})
    for live in ("NewStatus", "PartialFilledStatus", "PartialFilled", "WaitToNew"):
        assert lb._is_open_order({"status": live})


class _FakeTigerQuote:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_bars(self, symbols, period=None, limit=None):
        self.calls.append({"period": period, "limit": limit})
        return []


def test_tiger_history_month_does_not_collapse_to_minute(monkeypatch) -> None:
    """Regression: ``1M`` (month) must map to ``month``, not ``1min``."""
    fake = _FakeTigerQuote()
    monkeypatch.setattr(tg, "_quote_client", lambda cfg: fake)
    monkeypatch.setattr(tg, "_assert_profile", lambda cfg: None)
    cfg = tg.TigerConfig(tiger_id="x", private_key_path="x", account="20191106192858300", profile="paper")
    tg.get_historical_bars("AAPL", config=cfg, period="1M", limit=12)
    assert fake.calls[-1]["period"] == "month"
    assert fake.calls[-1]["limit"] == 12


def test_trading_history_tool_exposes_period_and_limit() -> None:
    from src.tools.trading_connector_tool import TradingHistoryTool

    props = TradingHistoryTool.parameters["properties"]
    assert "period" in props and "limit" in props
