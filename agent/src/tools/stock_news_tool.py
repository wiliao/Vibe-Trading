"""Read-only news tool: per-stock financial headlines.

US headlines come from Yahoo Finance's public v1 search-news surface via the
frozen, IP-throttled :mod:`backtest.loaders.yahoo_client`.

The tool never re-implements provider plumbing and never issues an un-throttled
request: every outbound call goes through a frozen client.

A failure from the upstream is reported as an error envelope; the tool never
raises out of :meth:`StockNewsTool.execute`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from backtest.loaders import yahoo_client

from src.agent.tools import BaseTool

logger = logging.getLogger(__name__)

# Suffixes that route to Yahoo's search-news surface.
_YAHOO_SUFFIXES = ("US",)

# Bounds so a noisy upstream can never return an unbounded payload.
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 50
# Per-article body trim so the envelope stays compact for the LLM.
_SNIPPET_CHARS = 280


def _clamp_limit(raw: Any) -> int:
    """Coerce a caller-supplied ``limit`` into the supported ``1.._MAX_LIMIT`` range.

    Args:
        raw: The raw ``limit`` value from the tool arguments (any type).

    Returns:
        An integer in ``[1, _MAX_LIMIT]``, falling back to ``_DEFAULT_LIMIT``
        when ``raw`` is missing or non-numeric.
    """
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        return _DEFAULT_LIMIT
    if value < 1:
        return 1
    return min(value, _MAX_LIMIT)


def _suffix_of(code: str) -> str:
    """Return the upper-cased exchange suffix of a symbol, or ``""`` when none."""
    if "." not in code:
        return ""
    return code.rpartition(".")[2].strip().upper()


def _bare_query(code: str) -> str:
    """Strip any exchange suffix to the bare code used as a news search term."""
    return code.strip().split(".", 1)[0].strip()


def _snippet(text: Any) -> str:
    """Trim an article body to a bounded plain-text snippet.

    Args:
        text: Raw body/summary value (any type).

    Returns:
        A whitespace-collapsed snippet capped at ``_SNIPPET_CHARS`` characters,
        or ``""`` when ``text`` is not a usable string.
    """
    if not isinstance(text, str):
        return ""
    collapsed = " ".join(text.split())
    if len(collapsed) <= _SNIPPET_CHARS:
        return collapsed
    return collapsed[:_SNIPPET_CHARS].rstrip() + "…"


def _yahoo_article(raw: dict[str, Any]) -> dict[str, Any]:
    """Project one Yahoo search-news item into the shared article shape.

    Args:
        raw: A single news dict from :func:`yahoo_client.search_news`.

    Returns:
        A flat ``{title, url, source, published, snippet}`` record.
    """
    published = None
    try:
        timestamp = float(raw.get("providerPublishTime"))
        published = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (TypeError, ValueError, OSError, OverflowError):
        pass
    return {
        "title": _snippet(raw.get("title")),
        "url": raw.get("link"),
        "source": raw.get("publisher"),
        "published": published,
        "snippet": _snippet(raw.get("summary")),
    }


def _fetch_yahoo_news(query: str, limit: int) -> list[dict[str, Any]]:
    """Fetch US news articles for a query via Yahoo search.

    Args:
        query: Free-text search term (bare ticker or keyword).
        limit: Maximum number of records to return.

    Returns:
        A capped list of compact article records; empty when none.

    Raises:
        requests.RequestException: Network/HTTP failure, propagated to caller.
    """
    articles = yahoo_client.search_news(query, limit)
    return [
        _yahoo_article(article) for article in articles if isinstance(article, dict)
    ][:limit]


class StockNewsTool(BaseTool):
    """Read-only per-stock financial news headlines."""

    name = "get_stock_news"
    description = (
        "Fetch recent financial news headlines for a US-listed stock, read-only "
        "and no auth, from Yahoo Finance. Returns ARTICLES "
        "(title/url/source/published/snippet) under 'articles'. Use scope "
        "'stock' with a 'code'. "
        'Example: {"code": "AAPL.US", "scope": "stock", "limit": 10}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "US symbol whose news to fetch, e.g. 'AAPL.US'. Required "
                    "when scope='stock'. The '.US' exchange suffix is required."
                ),
            },
            "scope": {
                "type": "string",
                "enum": ["stock"],
                "description": (
                    "'stock' (default) for one security named by 'code'."
                ),
                "default": "stock",
            },
            "limit": {
                "type": "integer",
                "description": (
                    "Maximum number of headlines to return (1-50). Default 20."
                ),
                "default": _DEFAULT_LIMIT,
            },
        },
        "required": [],
    }

    def execute(self, **kwargs: Any) -> str:
        """Fetch news headlines for one stock.

        Args:
            **kwargs: ``scope`` ('stock', default 'stock'), ``code`` (required
                when scope='stock'), and optional ``limit`` (1-50).

        Returns:
            A JSON string envelope. On success:
            ``{"ok": true, "market": <market>, "source": <source>,
            "data": {...}}``. On failure: ``{"ok": false, "error": "..."}``.
        """
        scope = kwargs.get("scope", "stock")
        if scope != "stock":
            return self._error(f"invalid scope: {scope!r}; expected 'stock'")

        limit = _clamp_limit(kwargs.get("limit"))

        return self._run_stock(kwargs.get("code"), limit)

    def _run_stock(self, code_arg: Any, limit: int) -> str:
        """Fetch single-security headlines, routing by exchange suffix.

        Args:
            code_arg: Raw ``code`` argument (any type).
            limit: Maximum number of headlines.

        Returns:
            A success or error JSON envelope.
        """
        if not isinstance(code_arg, str) or not code_arg.strip():
            return self._error(
                "missing required parameter: code (required when scope='stock')"
            )

        code = code_arg.strip()
        suffix = _suffix_of(code)
        query = _bare_query(code)
        if not query:
            return self._error(f"invalid code: {code!r}")

        if suffix in _YAHOO_SUFFIXES:
            return self._stock_via_yahoo(code, query, limit)
        return self._error(
            f"unsupported market for code {code!r}; expected suffix "
            f"{_YAHOO_SUFFIXES[0]}"
        )

    def _stock_via_yahoo(self, code: str, query: str, limit: int) -> str:
        """Fetch US news articles from Yahoo for one code."""
        try:
            articles = _fetch_yahoo_news(query, limit)
        except Exception as exc:  # noqa: BLE001 - surface any fetch failure as envelope
            logger.warning("yahoo news fetch failed for %s: %s", code, exc)
            return self._error(f"yahoo news fetch failed: {exc}")
        return self._ok(
            "us",
            "yahoo",
            {"scope": "stock", "code": code, "articles": articles},
        )

    @staticmethod
    def _ok(market: str, source: str, data: dict[str, Any]) -> str:
        """Render a success envelope as a JSON string.

        Args:
            market: Market label (e.g. ``"us"``).
            source: Upstream provider name (``"yahoo"``).
            data: The payload mapping.

        Returns:
            ``{"ok": true, "market": ..., "source": ..., "data": ...}`` as JSON.
        """
        return json.dumps(
            {"ok": True, "market": market, "source": source, "data": data},
            ensure_ascii=False,
        )

    @staticmethod
    def _error(message: str) -> str:
        """Render a failure envelope as a JSON string.

        Args:
            message: Human-readable error text.

        Returns:
            ``{"ok": false, "error": message}`` as a JSON string.
        """
        return json.dumps({"ok": False, "error": message}, ensure_ascii=False)
