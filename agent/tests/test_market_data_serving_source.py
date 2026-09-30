"""An unavailable loader must not take credit for a substitute's data (#1491)."""

import pandas as pd
import pytest

from backtest.loaders import registry
from src.market_data import fetch_market_data


def _bars():
    return pd.DataFrame(
        {"close": [10.0], "volume": [100.0]},
        index=pd.DatetimeIndex(["2026-09-01"], name="trade_date"),
    )


@pytest.mark.parametrize("requested", ["tiingo", "sina"])
@pytest.mark.parametrize("availability", ["unavailable", "constructor_error", "available"])
def test_real_registry_substitution_reports_serving_source(monkeypatch, requested, availability):
    """Exercise the real resolver, including unavailable optional SDKs."""

    class Requested:
        name = requested
        markets = {"us_equity"}
        volume_units = {"us_equity": "shares"}

        def __init__(self):
            if availability == "constructor_error":
                raise RuntimeError("optional SDK cannot initialize")

        def is_available(self):
            return availability == "available"

        def fetch(self, codes, start, end, interval="1D"):
            assert availability == "available"
            return {code: _bars() for code in codes}

    class Serving:
        name = "yahoo"
        markets = {"us_equity"}
        volume_units = {"us_equity": "shares"}

        def is_available(self):
            return True

        def fetch(self, codes, start, end, interval="1D"):
            return {code: _bars() for code in codes}

    monkeypatch.setattr(registry, "_ensure_registered", lambda: None)
    monkeypatch.setattr(registry, "LOADER_REGISTRY", {requested: Requested, "yahoo": Serving})
    monkeypatch.setattr(registry, "FALLBACK_CHAINS", {"us_equity": ["yahoo", requested]})
    out = fetch_market_data(
        codes=["AAPL.US"],
        start_date="2026-09-01",
        end_date="2026-09-02",
        source=requested,
        include_provenance=True,
    )
    provenance = out["_provenance"]["AAPL.US"]
    available = availability == "available"
    assert provenance["source"] == (requested if available else "yahoo")
    assert provenance["requested_source"] == requested
    assert provenance["fallback_used"] is (not available)
    assert provenance["volume_unit"] == "shares"
    # The caliber follows the source that actually served, not the one requested.
    caliber_by_source = {
        "sina": "raw",
        "tiingo": "split_dividend",
        "yahoo": "split_dividend",
    }
    assert provenance["adjustment"] == caliber_by_source[provenance["source"]]


def test_substituted_partial_batch_keeps_each_serving_source():
    """A resolver substitution and later fetch fallback both retain identity."""
    calls = []

    class Yahoo:
        name = "yahoo"

        def fetch(self, codes, start, end, interval="1D"):
            calls.append((self.name, codes))
            return {"AAPL.US": _bars()}

    class Sina:
        name = "sina"

        def fetch(self, codes, start, end, interval="1D"):
            calls.append((self.name, codes))
            return {code: _bars() for code in codes}

    out = fetch_market_data(
        codes=["AAPL.US", "MSFT.US"],
        start_date="2026-09-01",
        end_date="2026-09-02",
        source="tiingo",
        include_provenance=True,
        loader_resolver=lambda source: Yahoo if source == "tiingo" else Sina,
        fallback_chain_provider=lambda source: ["sina"],
    )
    assert calls == [("yahoo", ["AAPL.US", "MSFT.US"]), ("sina", ["MSFT.US"])]
    first, second = (out["_provenance"][code] for code in ["AAPL.US", "MSFT.US"])
    assert (first["source"], first["adjustment"], first["fallback_used"]) == (
        "yahoo",
        "split_dividend",
        True,
    )
    assert (second["source"], second["adjustment"], second["fallback_used"]) == ("sina", "raw", True)
