"""Tests for the stock-news tool.

No request leaves the process: the Yahoo
:func:`backtest.loaders.yahoo_client.search_news` helper is mocked so the real
client + tool parsing run fully offline.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from backtest.loaders import yahoo_client
from src.tools.stock_news_tool import (
    StockNewsTool,
    _bare_query,
    _clamp_limit,
    _snippet,
    _suffix_of,
)


def _yahoo_news() -> list[dict[str, Any]]:
    """A Yahoo search result list with two news articles."""
    return [
        {
            "title": "Apple unveils new products",
            "publisher": "Reuters",
            "link": "https://example.com/apple-products",
            "providerPublishTime": 1704067200,
            "summary": "Apple announced a new product lineup. " * 30,
            "relatedTickers": ["AAPL"],
        },
        {
            "title": "Apple shares rise",
            "publisher": "Bloomberg",
            "link": "https://example.com/apple-shares",
            "providerPublishTime": 1704153600,
            "relatedTickers": ["AAPL"],
        },
    ]


class TestHelpers:
    def test_suffix_of(self) -> None:
        assert _suffix_of("600519.SH") == "SH"
        assert _suffix_of("AAPL.US") == "US"
        assert _suffix_of("NOSUFFIX") == ""

    def test_bare_query(self) -> None:
        assert _bare_query("600519.SH") == "600519"
        assert _bare_query(" AAPL.US ") == "AAPL"

    def test_clamp_limit(self) -> None:
        assert _clamp_limit(None) == 20
        assert _clamp_limit("garbage") == 20
        assert _clamp_limit(0) == 1
        assert _clamp_limit(999) == 50
        assert _clamp_limit(5) == 5

    def test_snippet_trims(self) -> None:
        assert _snippet(None) == ""
        long = "x" * 400
        out = _snippet(long)
        assert len(out) <= 281
        assert out.endswith("…")

    def test_search_news_filters_to_dict_items(self, monkeypatch) -> None:
        def fake_get_json(url: str, **kwargs: Any) -> dict[str, Any]:
            assert url == yahoo_client._SEARCH_BASE
            assert kwargs["host_key"] == yahoo_client.HOST_KEY
            assert kwargs["params"] == {"q": "apple", "newsCount": 2}
            return {"news": [_yahoo_news()[0], "garbage", _yahoo_news()[1]]}

        monkeypatch.setattr(yahoo_client, "throttled_get_json", fake_get_json)

        articles = yahoo_client.search_news("apple", 2)

        assert articles == _yahoo_news()


class TestToolContract:
    def test_name_and_schema(self) -> None:
        tool = StockNewsTool()
        assert tool.name == "get_stock_news"
        assert tool.is_readonly is True
        assert tool.parameters["required"] == []
        assert tool.parameters["properties"]["scope"]["enum"] == ["stock"]
        # Description must advertise the article contract the tool returns.
        desc = tool.description.lower()
        assert "yahoo finance" in desc
        assert "title/url/source/published/snippet" in desc
        assert "matches" not in desc


class TestExecuteSuccess:
    def test_us_stock_via_yahoo_returns_articles(self) -> None:
        tool = StockNewsTool()
        with patch.object(
            yahoo_client, "search_news", return_value=_yahoo_news()
        ) as srch:
            out = json.loads(tool.execute(code="AAPL.US", limit=1))

        srch.assert_called_once_with("AAPL", 1)
        assert out["ok"] is True
        assert out["market"] == "us"
        assert out["source"] == "yahoo"
        assert len(out["data"]["articles"]) == 1
        first = out["data"]["articles"][0]
        assert first == {
            "title": "Apple unveils new products",
            "url": "https://example.com/apple-products",
            "source": "Reuters",
            "published": "2024-01-01 00:00:00",
            "snippet": ("Apple announced a new product lineup. " * 30)[:280].rstrip()
            + "…",
        }

    def test_yahoo_empty_news_returns_empty_articles(self) -> None:
        with patch.object(yahoo_client, "search_news", return_value=[]):
            out = json.loads(StockNewsTool().execute(code="AAPL.US"))

        assert out["ok"] is True
        assert out["data"]["articles"] == []

    def test_yahoo_limit_is_clamped_before_request(self) -> None:
        with patch.object(yahoo_client, "search_news", return_value=[]) as srch:
            out = json.loads(StockNewsTool().execute(code="AAPL.US", limit=999))

        assert out["ok"] is True
        srch.assert_called_once_with("AAPL", 50)


class TestExecuteError:
    def test_missing_code_when_stock_scope(self) -> None:
        out = json.loads(StockNewsTool().execute(scope="stock"))
        assert out["ok"] is False
        assert "code" in out["error"]

    def test_invalid_scope(self) -> None:
        out = json.loads(StockNewsTool().execute(scope="weird"))
        assert out["ok"] is False
        assert "invalid scope" in out["error"]

    def test_unsupported_market(self) -> None:
        out = json.loads(StockNewsTool().execute(code="BTC-USDT"))
        assert out["ok"] is False
        assert "unsupported market" in out["error"]

    def test_non_us_suffix_is_rejected(self) -> None:
        # Phase 5 removed every non-US news path, so a Hong Kong code the Yahoo
        # branch used to serve is refused rather than silently rerouted.
        out = json.loads(StockNewsTool().execute(code="00700.HK"))
        assert out["ok"] is False
        assert "unsupported market" in out["error"]
        assert "expected suffix US" in out["error"]

    def test_yahoo_failure_envelope(self) -> None:
        tool = StockNewsTool()
        with patch.object(
            yahoo_client, "search_news", side_effect=RuntimeError("yahoo 429")
        ):
            out = json.loads(tool.execute(code="AAPL.US"))

        assert out["ok"] is False
        assert "yahoo 429" in out["error"]
        assert "yahoo news fetch failed" in out["error"]
