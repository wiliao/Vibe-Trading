"""Tests for loader registry and fallback chain logic."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import importlib
from threading import Event
from types import ModuleType
from unittest.mock import patch

import pytest

from backtest.loaders import registry
from backtest.loaders.base import DataLoaderProtocol, NoAvailableSourceError
from backtest.loaders.registry import (
    _ensure_registered,
    FALLBACK_CHAINS,
    LOADER_REGISTRY,
    VALID_SOURCES,
    get_loader_cls_with_fallback,
    register,
    resolve_loader,
)


# ---------------------------------------------------------------------------
# Helpers — fake loaders
# ---------------------------------------------------------------------------


class _FakeAvailableLoader:
    name = "fake_available"
    markets = {"us_equity"}
    requires_auth = False

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {}


class _FakeUnavailableLoader:
    name = "fake_unavailable"
    markets = {"us_equity"}
    requires_auth = True

    def is_available(self) -> bool:
        return False

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {}


class _FakeInitErrorLoader:
    """Mimics a key-gated loader with a missing token: blows up in ``__init__``."""

    name = "fake_init_error"
    markets = {"us_equity"}
    requires_auth = True

    def __init__(self) -> None:
        raise RuntimeError("api init error — token not set")

    def is_available(self) -> bool:  # pragma: no cover — never reached
        return False

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {}


class _FakeLocalLoader:
    """Mimics the real local loader: broad ``markets``, unavailable without
    a Data Bridge config."""

    name = "local"
    markets = {"us_equity", "ca_equity"}
    requires_auth = False

    def is_available(self) -> bool:
        return False

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {}


# ---------------------------------------------------------------------------
# @register decorator
# ---------------------------------------------------------------------------


class TestRegisterDecorator:
    def test_register_adds_to_registry(self) -> None:
        with patch.dict(LOADER_REGISTRY, {}, clear=True):
            register(_FakeAvailableLoader)
            assert "fake_available" in LOADER_REGISTRY
            assert LOADER_REGISTRY["fake_available"] is _FakeAvailableLoader

    def test_register_returns_class_unchanged(self) -> None:
        with patch.dict(LOADER_REGISTRY, {}, clear=True):
            result = register(_FakeAvailableLoader)
            assert result is _FakeAvailableLoader


@pytest.mark.parametrize("entrypoint", ["market", "source"])
def test_concurrent_cold_readers_wait_for_registration(
    monkeypatch: pytest.MonkeyPatch, entrypoint: str
) -> None:
    """Cold readers must wait for one complete import pass, including skips."""
    importing = Event()
    release = Event()
    reader_started = Event()
    imports: list[str] = []
    real_import = importlib.import_module

    def controlled_import(name: str, package: str | None = None) -> ModuleType:
        if not name.startswith("backtest.loaders."):
            return real_import(name, package)
        imports.append(name)
        if name == "backtest.loaders.yahoo_loader":
            importing.set()
            if not release.wait(5):
                raise RuntimeError("loader import was never released")
        if name == "backtest.loaders.fmp_loader":
            raise ImportError("optional dependency unavailable")
        if name == "backtest.loaders.local_loader":
            register(_FakeAvailableLoader)
        return ModuleType(name)

    def read_loader() -> type:
        reader_started.set()
        if entrypoint == "source":
            return get_loader_cls_with_fallback(_FakeAvailableLoader.name)
        return type(resolve_loader("us_equity"))

    monkeypatch.setattr(registry, "_registered", False)
    monkeypatch.setattr(registry, "LOADER_REGISTRY", {})
    monkeypatch.setitem(FALLBACK_CHAINS, "us_equity", [_FakeAvailableLoader.name])
    monkeypatch.setattr(importlib, "import_module", controlled_import)

    # Keep initialization inside its first import while a public reader enters.
    # Always release the importer before joining threads or restoring patches.
    with ThreadPoolExecutor(max_workers=2) as pool:
        initializer = pool.submit(_ensure_registered)
        try:
            assert importing.wait(5)
            reader = pool.submit(read_loader)
            assert reader_started.wait(5)
            with pytest.raises(TimeoutError):
                reader.result(timeout=0.1)
        finally:
            release.set()
        initializer.result(timeout=5)
        assert reader.result(timeout=5) is _FakeAvailableLoader

    assert registry._registered is True
    assert len(imports) == len(set(imports)), "initialization ran more than once"
    completed_imports = imports[:]
    assert read_loader() is _FakeAvailableLoader
    assert imports == completed_imports, "warm readers must not repeat imports"


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_fake_loader_satisfies_protocol(self) -> None:
        assert isinstance(_FakeAvailableLoader(), DataLoaderProtocol)

    def test_missing_method_fails_protocol(self) -> None:
        class BadLoader:
            name = "bad"

        assert not isinstance(BadLoader(), DataLoaderProtocol)


# ---------------------------------------------------------------------------
# FALLBACK_CHAINS
# ---------------------------------------------------------------------------


class TestFallbackChains:
    def test_all_expected_markets_present(self) -> None:
        assert set(FALLBACK_CHAINS.keys()) == {"us_equity", "ca_equity", "index"}

    def test_us_equity_chain_ordered_by_ip_ban_risk(self) -> None:
        """Equity chains lead with throttle-tolerant public sources and trail
        with key-gated REST fallbacks, in the exact reviewed order."""
        assert FALLBACK_CHAINS["us_equity"] == [
            "yahoo",
            "stooq",
            "sina",
            "eastmoney",
            "yfinance",
            "tiingo",
            "fmp",
            "finnhub",
            "alphavantage",
            "local",
        ]

    def test_canada_chain_uses_only_compatible_sources(self) -> None:
        assert FALLBACK_CHAINS["ca_equity"] == ["yahoo", "yfinance", "local"]

    def test_index_chain_uses_only_compatible_sources(self) -> None:
        assert FALLBACK_CHAINS["index"] == ["yahoo", "yfinance", "local"]

    def test_chains_are_non_empty(self) -> None:
        for market, chain in FALLBACK_CHAINS.items():
            assert len(chain) > 0, f"Fallback chain for {market} is empty"

    def test_us_equity_includes_sina_fallback(self) -> None:
        """'sina' must be reachable for US equities (after yahoo/stooq)."""
        chain = FALLBACK_CHAINS["us_equity"]
        assert "sina" in chain
        assert chain.index("sina") > chain.index("yahoo")
        assert chain.index("sina") > chain.index("stooq")


# ---------------------------------------------------------------------------
# VALID_SOURCES
# ---------------------------------------------------------------------------


class TestValidSources:
    def test_includes_surviving_loaders(self) -> None:
        surviving = {
            "eastmoney",
            "sina",
            "stooq",
            "yahoo",
            "finnhub",
            "alphavantage",
            "tiingo",
            "fmp",
            "yfinance",
            "local",
        }
        assert surviving <= VALID_SOURCES

    def test_covers_all_registered_loaders(self) -> None:
        """Every registered loader name must be an accepted config source."""
        _ensure_registered()
        missing = set(LOADER_REGISTRY) - VALID_SOURCES
        assert not missing, f"loaders missing from VALID_SOURCES: {missing}"


# ---------------------------------------------------------------------------
# resolve_loader
# ---------------------------------------------------------------------------


class TestResolveLoader:
    def test_returns_first_available(self) -> None:
        with patch.dict(
            LOADER_REGISTRY,
            {"fake_unavailable": _FakeUnavailableLoader, "fake_available": _FakeAvailableLoader},
            clear=True,
        ):
            with patch.dict(
                FALLBACK_CHAINS,
                {"us_equity": ["fake_unavailable", "fake_available"]},
            ):
                loader = resolve_loader("us_equity")
                assert loader.name == "fake_available"

    def test_raises_when_none_available(self) -> None:
        with patch.dict(
            LOADER_REGISTRY, {"fake_unavailable": _FakeUnavailableLoader}, clear=True
        ):
            with patch.dict(FALLBACK_CHAINS, {"us_equity": ["fake_unavailable"]}):
                with pytest.raises(NoAvailableSourceError):
                    resolve_loader("us_equity")

    def test_unknown_market_raises(self) -> None:
        with patch.dict(LOADER_REGISTRY, {}, clear=True):
            with pytest.raises(NoAvailableSourceError):
                resolve_loader("martian_stocks")


# ---------------------------------------------------------------------------
# get_loader_cls_with_fallback
# ---------------------------------------------------------------------------


class TestGetLoaderWithFallback:
    def test_returns_requested_if_available(self) -> None:
        with patch.dict(LOADER_REGISTRY, {"fake_available": _FakeAvailableLoader}, clear=True):
            cls = get_loader_cls_with_fallback("fake_available")
            assert cls is _FakeAvailableLoader

    def test_falls_back_when_unavailable(self) -> None:
        with patch.dict(
            LOADER_REGISTRY,
            {"fake_unavailable": _FakeUnavailableLoader, "fake_available": _FakeAvailableLoader},
            clear=True,
        ):
            with patch.dict(
                FALLBACK_CHAINS,
                {"us_equity": ["fake_unavailable", "fake_available"]},
            ):
                cls = get_loader_cls_with_fallback("fake_unavailable")
                assert cls is _FakeAvailableLoader

    def test_unknown_source_raises(self) -> None:
        with patch.dict(LOADER_REGISTRY, {}, clear=True):
            with pytest.raises(NoAvailableSourceError):
                get_loader_cls_with_fallback("nonexistent")

    def test_no_fallback_raises(self) -> None:
        with patch.dict(LOADER_REGISTRY, {"fake_unavailable": _FakeUnavailableLoader}, clear=True):
            with patch.dict(FALLBACK_CHAINS, {"us_equity": ["fake_unavailable"]}):
                with pytest.raises(NoAvailableSourceError):
                    get_loader_cls_with_fallback("fake_unavailable")

    def test_explicit_local_does_not_fall_through_to_network(self) -> None:
        """An explicit unavailable 'local' request must raise, never silently
        degrade to an unrelated network loader via its broad markets."""
        with patch.dict(
            LOADER_REGISTRY,
            {"local": _FakeLocalLoader, "fake_available": _FakeAvailableLoader},
            clear=True,
        ):
            with patch.dict(FALLBACK_CHAINS, {"us_equity": ["fake_available"]}):
                with pytest.raises(NoAvailableSourceError) as excinfo:
                    get_loader_cls_with_fallback("local")
        msg = str(excinfo.value)
        assert "local" in msg
        assert "data-bridge" in msg.lower() or "config" in msg.lower()


# ---------------------------------------------------------------------------
# Loaders that explode in __init__ must not poison the fallback chain.
# ---------------------------------------------------------------------------


class TestInitErrorFallback:
    def test_resolve_loader_skips_init_error(self) -> None:
        with patch.dict(
            LOADER_REGISTRY,
            {"fake_init_error": _FakeInitErrorLoader, "fake_available": _FakeAvailableLoader},
            clear=True,
        ):
            with patch.dict(
                FALLBACK_CHAINS,
                {"us_equity": ["fake_init_error", "fake_available"]},
            ):
                loader = resolve_loader("us_equity")
                assert loader.name == "fake_available"

    def test_get_loader_cls_falls_back_when_requested_init_errors(self) -> None:
        with patch.dict(
            LOADER_REGISTRY,
            {"fake_init_error": _FakeInitErrorLoader, "fake_available": _FakeAvailableLoader},
            clear=True,
        ):
            with patch.dict(
                FALLBACK_CHAINS,
                {"us_equity": ["fake_init_error", "fake_available"]},
            ):
                cls = get_loader_cls_with_fallback("fake_init_error")
                assert cls is _FakeAvailableLoader
