"""Universe loaders disclose constituent provenance and degradation."""

from __future__ import annotations

import pytest

from src.tools import alpha_bench_tool as tool


@pytest.mark.parametrize(
    ("codes", "source", "source_date", "degraded"),
    [
        (["AAPL"], "wikipedia", tool._SP500_CONSTITUENT_SOURCE_DATE, False),
        ([], "hand-picked fallback", None, True),
    ],
)
def test_sp500_source_date_matches_the_roster(
    monkeypatch: pytest.MonkeyPatch,
    codes: list[str],
    source: str,
    source_date: str | None,
    degraded: bool,
) -> None:
    """SP500 metadata never assigns Wikipedia's date to a fallback list."""

    class _Loader:
        def fetch(self, *_args, **_kwargs) -> dict:
            return {}

    import backtest.loaders.registry as registry

    monkeypatch.setattr(tool, "_fetch_sp500_constituents", lambda: (codes, {}))
    monkeypatch.setattr(registry, "resolve_loader", lambda _market: _Loader())

    panel = tool._load_sp500_panel("2024-01-01", "2024-01-31")

    assert panel["_meta"]["constituent_source"] == source
    assert panel["_meta"]["constituent_source_date"] == source_date
    assert panel["_meta"]["degraded"] is degraded
