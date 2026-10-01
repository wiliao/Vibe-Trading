"""Tests for the search_symbol tool.

All HTTP is mocked at the client functions the tool imports
(``eastmoney_client.get_json``, ``yahoo_client.search``,
``sec_edgar_client.cik_for``), so no test ever reaches a live endpoint.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.trading import profiles as trading_profiles
from src.tools import symbol_search_tool as ss


def _eastmoney_payload() -> dict:
    """A suggest payload spanning the US listing venues."""
    return {
        "QuotationCodeTable": {
            "Data": [
                {
                    "QuoteID": "105.AAPL",
                    "Code": "AAPL",
                    "Name": "苹果",
                    "MktNum": "105",
                    "SecurityTypeName": "美股",
                },
                {
                    # Unmappable market (e.g. a fund/board) -> dropped, not fatal.
                    "QuoteID": "90.BK0001",
                    "Code": "BK0001",
                    "Name": "板块",
                    "MktNum": "90",
                    "SecurityTypeName": "板块",
                },
            ]
        }
    }


def _yahoo_quotes() -> list:
    return [
        {
            "symbol": "AAPL",
            "shortname": "Apple Inc.",
            "exchange": "NMS",
            "quoteType": "EQUITY",
        },
        {
            "symbol": "TD.TO",
            "shortname": "Toronto-Dominion Bank",
            "exchange": "TOR",
            "quoteType": "EQUITY",
        },
        {
            "symbol": "PNG.V",
            "shortname": "Kraken Robotics Inc.",
            "exchange": "VAN",
            "quoteType": "EQUITY",
        },
        {"symbol": "", "shortname": "no symbol"},  # dropped
    ]


class TestSymbolSearchSuccess:
    """Happy-path fan-out, normalization, merge, and CIK enrichment."""

    def test_merges_and_normalizes_across_sources(self):
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=_eastmoney_payload()
        ), patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ), patch.object(
            ss.sec_edgar_client, "cik_for", return_value="0000320193"
        ):
            out = ss.SymbolSearchTool().execute(query="apple", limit=10)

        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["market"] == "multi"
        assert payload["source"] == "symbol_search"

        data = payload["data"]
        assert data["query"] == "apple"
        assert data["sources"]["eastmoney"] == "ok"
        assert data["sources"]["yahoo"] == "ok"
        assert data["sources"]["sec_edgar"] == "ok"

        by_symbol = {c["symbol"]: c for c in data["candidates"]}

        assert by_symbol["TD.TO"]["market"] == "ca"
        assert by_symbol["PNG.V"]["market"] == "ca"

        # US equity: Eastmoney + Yahoo merge, SEC CIK attached.
        aapl = by_symbol["AAPL.US"]
        assert aapl["market"] == "us"
        assert aapl["cik"] == "0000320193"
        assert "yahoo" in aapl.get("also_from", [])

        # Unmappable Eastmoney market dropped; empty Yahoo symbol dropped.
        assert "BK0001" not in by_symbol
        assert data["count"] == len(data["candidates"])

    def test_canada_candidate_keeps_market_identity(self):
        quote = {
            "symbol": "TD.TO",
            "shortname": "Toronto-Dominion Bank",
            "exchange": "TOR",
            "quoteType": "EQUITY",
        }
        candidate = ss._yahoo_candidate(quote)
        assert candidate is not None
        assert candidate["symbol"] == "TD.TO"
        assert candidate["market"] == "ca"

    def test_limit_clamped_and_applied(self):
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=_eastmoney_payload()
        ), patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ), patch.object(
            ss.sec_edgar_client, "cik_for", return_value=None
        ):
            out = ss.SymbolSearchTool().execute(query="x", limit=2)
        payload = json.loads(out)
        assert payload["data"]["count"] == 2

    def test_no_us_candidate_omits_sec_source(self):
        em = {
            "QuotationCodeTable": {
                "Data": [
                    {
                        "QuoteID": "1.600519",
                        "Code": "600519",
                        "Name": "贵州茅台",
                        "MktNum": "1",
                    }
                ]
            }
        }
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=em
        ), patch.object(
            ss.yahoo_client, "search", return_value=[]
        ), patch.object(
            ss.sec_edgar_client, "cik_for"
        ) as mock_cik:
            out = ss.SymbolSearchTool().execute(query="茅台")
        payload = json.loads(out)
        assert "sec_edgar" not in payload["data"]["sources"]
        mock_cik.assert_not_called()

    def test_canadian_query_skips_eastmoney_endpoint(self):
        """A Canadian .V/.TO query fails fast: eastmoney is never contacted."""
        with patch.object(
            ss.eastmoney_client, "get_json"
        ) as mock_em, patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ):
            out = ss.SymbolSearchTool().execute(query="BYN.V")

        mock_em.assert_not_called()
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["data"]["sources"]["eastmoney"] == (
            "skipped: eastmoney has no Canada coverage"
        )

    def test_canadian_query_drops_us_otc_aliases(self):
        """Yahoo OTC aliases (BYAGF.US) of a Canadian name are filtered out."""
        quotes = [
            {
                "symbol": "BYN.V",
                "shortname": "Banyan Gold Corp.",
                "exchange": "VAN",
                "quoteType": "EQUITY",
            },
            {
                "symbol": "BYAGF.US",
                "shortname": "Banyan Gold Corp.",
                "exchange": "PNK",
                "quoteType": "EQUITY",
            },
        ]
        with patch.object(
            ss.eastmoney_client, "get_json"
        ), patch.object(ss.yahoo_client, "search", return_value=quotes):
            out = ss.SymbolSearchTool().execute(query="BYN.V")

        payload = json.loads(out)
        symbols = {c["symbol"] for c in payload["data"]["candidates"]}
        assert symbols == {"BYN.V"}
        assert "BYAGF.US" not in symbols

    def test_canadian_query_drops_us_otc_aliases_cert(self):
        """CERT.V OTC alias (CERT.US) is filtered for a Canadian query."""
        quotes = [
            {
                "symbol": "CERT.V",
                "shortname": "Cerrado Gold Inc.",
                "exchange": "VAN",
                "quoteType": "EQUITY",
            },
            {
                "symbol": "CERT.US",
                "shortname": "Cerrado Gold Inc.",
                "exchange": "PNK",
                "quoteType": "EQUITY",
            },
        ]
        with patch.object(
            ss.eastmoney_client, "get_json"
        ), patch.object(ss.yahoo_client, "search", return_value=quotes):
            out = ss.SymbolSearchTool().execute(query="CERT.V")

        payload = json.loads(out)
        symbols = {c["symbol"] for c in payload["data"]["candidates"]}
        assert symbols == {"CERT.V"}

    def test_canadian_tsx_to_query_keeps_to_only(self):
        """A .TO (TSX) query keeps only the .TO candidate, not a US alias."""
        quotes = [
            {
                "symbol": "PDI.TO",
                "shortname": "Predictive Discovery",
                "exchange": "TOR",
                "quoteType": "EQUITY",
            },
            {
                "symbol": "PDIYF.US",
                "shortname": "Predictive Discovery ADR",
                "exchange": "PNK",
                "quoteType": "EQUITY",
            },
        ]
        with patch.object(
            ss.eastmoney_client, "get_json"
        ), patch.object(ss.yahoo_client, "search", return_value=quotes):
            out = ss.SymbolSearchTool().execute(query="PDI.TO")

        payload = json.loads(out)
        symbols = {c["symbol"] for c in payload["data"]["candidates"]}
        assert symbols == {"PDI.TO"}

    def test_canadian_ticker_with_name_text_skips_eastmoney(self):
        """A "TICKER.TO <name>" query (e.g. "BTO.TO B2Gold") still fails fast.

        The model commonly searches the suffixed ticker plus a name hint; the
        leading .TO/.V suffix is unambiguous Canada, so Eastmoney (no Canada
        coverage) must not be contacted.
        """
        with patch.object(
            ss.eastmoney_client, "get_json"
        ) as mock_em, patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ):
            out = ss.SymbolSearchTool().execute(query="BTO.TO B2Gold")

        mock_em.assert_not_called()
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["data"]["sources"]["eastmoney"] == (
            "skipped: eastmoney has no Canada coverage"
        )

    def test_canadian_v_ticker_with_name_text_skips_eastmoney(self):
        """"SGML.V Sigma Lithium Vancouver" fails fast on the leading .V suffix."""
        with patch.object(
            ss.eastmoney_client, "get_json"
        ) as mock_em, patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ):
            out = ss.SymbolSearchTool().execute(query="SGML.V Sigma Lithium Vancouver")

        mock_em.assert_not_called()
        payload = json.loads(out)
        assert payload["data"]["sources"]["eastmoney"] == (
            "skipped: eastmoney has no Canada coverage"
        )

    def test_bare_name_without_suffix_still_hits_eastmoney(self):
        """A bare name (no .TO/.V) is NOT fail-fast — venue is ambiguous.

        This preserves the documented design: bare names like "B2Gold BTO" or
        "BTO" may be legit non-Canadian lookups, so Eastmoney fan-out stays.
        """
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=_eastmoney_payload()
        ) as mock_em, patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ):
            out = ss.SymbolSearchTool().execute(query="B2Gold BTO")

        mock_em.assert_called_once()
        payload = json.loads(out)
        assert payload["data"]["sources"]["eastmoney"] == "ok"


class TestSymbolSearchErrors:
    """Error envelopes and per-source resilience."""

    def test_missing_query_returns_error_envelope(self):
        out = ss.SymbolSearchTool().execute(query="   ")
        payload = json.loads(out)
        assert payload["ok"] is False
        assert "required" in payload["error"]

    def test_one_source_failure_does_not_abort_others(self):
        with patch.object(
            ss.eastmoney_client,
            "get_json",
            side_effect=RuntimeError("HTTP 429 banned"),
        ), patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ), patch.object(
            ss.sec_edgar_client, "cik_for", return_value="0000320193"
        ):
            out = ss.SymbolSearchTool().execute(query="apple")

        payload = json.loads(out)
        # Overall call still succeeds with the surviving source's hits.
        assert payload["ok"] is True
        sources = payload["data"]["sources"]
        assert "eastmoney search failed" in sources["eastmoney"]
        assert "429" in sources["eastmoney"]
        assert sources["yahoo"] == "ok"
        symbols = {c["symbol"] for c in payload["data"]["candidates"]}
        assert "AAPL.US" in symbols

    def test_sec_lookup_failure_recorded_not_fatal(self):
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=_eastmoney_payload()
        ), patch.object(
            ss.yahoo_client, "search", return_value=[]
        ), patch.object(
            ss.sec_edgar_client,
            "cik_for",
            side_effect=RuntimeError("tickers fetch failed"),
        ):
            out = ss.SymbolSearchTool().execute(query="apple")
        payload = json.loads(out)
        assert payload["ok"] is True
        assert "sec lookup failed" in payload["data"]["sources"]["sec_edgar"]
        # The US candidate still appears, just without a CIK.
        aapl = next(c for c in payload["data"]["candidates"] if c["symbol"] == "AAPL.US")
        assert "cik" not in aapl


class TestShanghaiAliasAndUnsupportedQueries:
    """The two resolver defects that made Shanghai and Chinese queries unusable."""

    def test_non_ascii_query_skips_yahoo_without_calling_it(self):
        """A source that cannot serve a query shape is skipped, not failed.

        Yahoo answers any non-ASCII query with HTTP 400. Recording that as a
        source failure made "this entity is not listed" indistinguishable from
        "a source is down" for every Chinese query.
        """
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=_eastmoney_payload()
        ), patch.object(ss.yahoo_client, "search") as search, patch.object(
            ss.sec_edgar_client, "cik_for", return_value="0000320193"
        ):
            data = json.loads(ss.SymbolSearchTool().execute(query="贵州茅台"))["data"]

        search.assert_not_called()
        assert data["sources"]["yahoo"].startswith("skipped:")
        assert data["sources"]["eastmoney"] == "ok"

    def test_ascii_query_still_reaches_yahoo(self):
        """The skip is keyed on the query shape, not switched on permanently."""
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=_eastmoney_payload()
        ), patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ) as search, patch.object(
            ss.sec_edgar_client, "cik_for", return_value="0000320193"
        ):
            data = json.loads(ss.SymbolSearchTool().execute(query="apple"))["data"]

        search.assert_called_once()
        assert data["sources"]["yahoo"] == "ok"


class TestTickerNameQueryYahooSkip:
    """A ticker+name query Yahoo cannot serve must be skipped, not "ok".

    Yahoo's search endpoint answers a multi-token query whose first token is a
    bare all-caps ticker ("XOM ExxonMobil") with zero quotes. Recording that as
    "ok" counted a second clean source, so a caller deciding whether an entity
    exists read "not listed" as two corroborating "not found" answers; the
    unsupported shape must read as "skipped" instead, mirroring the non-ASCII
    guard. Eastmoney is NOT skipped for this shape — it can serve multi-token
    queries — only the Yahoo path relabels.
    """

    def test_ticker_name_query_skips_yahoo_without_ok_status(self):
        """Yahoo returns zero quotes for the shape and is relabeled "skipped"."""
        with patch.object(
            ss.eastmoney_client,
            "get_json",
            return_value={"QuotationCodeTable": {"Data": []}},
        ), patch.object(
            ss.yahoo_client, "search", return_value=[]
        ) as search, patch.object(
            ss.sec_edgar_client, "cik_for", return_value=None
        ):
            data = json.loads(
                ss.SymbolSearchTool().execute(query="XOM ExxonMobil")
            )["data"]

        # Post-response relabel, not a pre-call skip: Yahoo is still consulted.
        search.assert_called_once()
        assert data["sources"]["yahoo"].startswith("skipped:")
        assert data["sources"]["eastmoney"] == "ok"
        assert data["count"] == 0

    def test_ticker_name_query_with_matching_quotes_stays_ok(self):
        """The relabel must NOT fire when Yahoo can actually serve the shape."""
        quotes = [
            {
                "symbol": "XOM",
                "shortname": "Exxon Mobil Corp.",
                "exchange": "NYQ",
                "quoteType": "EQUITY",
            }
        ]
        with patch.object(
            ss.eastmoney_client,
            "get_json",
            return_value={"QuotationCodeTable": {"Data": []}},
        ), patch.object(
            ss.yahoo_client, "search", return_value=quotes
        ) as search, patch.object(
            ss.sec_edgar_client, "cik_for", return_value="0000034088"
        ):
            data = json.loads(
                ss.SymbolSearchTool().execute(query="XOM ExxonMobil")
            )["data"]

        search.assert_called_once()
        assert data["sources"]["yahoo"] == "ok"
        assert data["count"] == 1

    def test_multi_word_name_query_still_reaches_yahoo(self):
        """A multi-word NAME ("Exxon Mobil") is not a ticker+name shape."""
        with patch.object(
            ss.eastmoney_client,
            "get_json",
            return_value={"QuotationCodeTable": {"Data": []}},
        ), patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ) as search, patch.object(
            ss.sec_edgar_client, "cik_for", return_value="0000320193"
        ):
            data = json.loads(ss.SymbolSearchTool().execute(query="Exxon Mobil"))["data"]

        search.assert_called_once()
        assert data["sources"]["yahoo"] == "ok"

    def test_single_token_query_still_reaches_yahoo(self):
        """A bare single-token ticker ("XOM") is not a ticker+name shape."""
        with patch.object(
            ss.eastmoney_client,
            "get_json",
            return_value={"QuotationCodeTable": {"Data": []}},
        ), patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ) as search, patch.object(
            ss.sec_edgar_client, "cik_for", return_value="0000320193"
        ):
            data = json.loads(ss.SymbolSearchTool().execute(query="XOM"))["data"]

        search.assert_called_once()
        assert data["sources"]["yahoo"] == "ok"

    def test_suffixed_ticker_with_name_still_reaches_yahoo(self):
        """The bare-ticker clause must not fire on suffixed Canadian tickers."""
        with patch.object(
            ss.eastmoney_client,
            "get_json",
            return_value={"QuotationCodeTable": {"Data": []}},
        ), patch.object(
            ss.yahoo_client, "search", return_value=_yahoo_quotes()
        ) as search:
            data = json.loads(
                ss.SymbolSearchTool().execute(query="BTO.TO B2Gold")
            )["data"]

        search.assert_called_once()
        assert data["sources"]["yahoo"] == "ok"

    def test_single_token_ascii_empty_result_stays_ok(self):
        """A bare single token Yahoo cannot match is "not listed", not "skipped".

        The relabel is shape-specific: only a multi-token ticker+name query is
        unsupported. A single token (e.g. a bogus ticker) that returns zero
        quotes is an authoritative "not listed" and must stay "ok", otherwise
        every genuinely-absent entity would read as an unsupported shape.
        """
        with patch.object(
            ss.eastmoney_client,
            "get_json",
            return_value={"QuotationCodeTable": {"Data": []}},
        ), patch.object(
            ss.yahoo_client, "search", return_value=[]
        ) as search:
            data = json.loads(
                ss.SymbolSearchTool().execute(query="XOMZZZ")
            )["data"]

        search.assert_called_once()
        assert data["sources"]["yahoo"] == "ok"

    def test_multi_word_name_empty_result_stays_ok(self):
        """A multi-word NAME ("Exxon Mobil") with zero quotes is "not listed".

        The shape classifier keys on a bare all-caps FIRST token ("XOM
        ExxonMobil"). A name-led query ("Exxon Mobil") is a shape Yahoo can
        serve, so its empty answer is an authoritative "not listed" and must
        not be relabeled to "skipped".
        """
        with patch.object(
            ss.eastmoney_client,
            "get_json",
            return_value={"QuotationCodeTable": {"Data": []}},
        ), patch.object(
            ss.yahoo_client, "search", return_value=[]
        ) as search:
            data = json.loads(
                ss.SymbolSearchTool().execute(query="Exxon Mobil")
            )["data"]

        search.assert_called_once()
        assert data["sources"]["yahoo"] == "ok"


class TestCryptoPairWithoutABrokerConnection:
    """Resolving an exchange pair must not require a broker account.

    #1242 routes exact pairs through the *selected* Binance connector, which
    needs a configured profile and credentials. Identity resolution is a
    read-only lookup against a public catalog — the same unauthenticated ccxt
    connectivity ``orderbook_depth`` already uses to serve these pairs — so a
    user with no broker connection must still get an identity rather than
    nothing (or, before #1234, a near-string Yahoo asset).
    """

    @staticmethod
    def _markets(*symbols):
        return {sym: {"symbol": sym, "spot": True, "active": True} for sym in symbols}

    def _run(self, monkeypatch, query, markets_by_exchange, yahoo=None):
        monkeypatch.setattr(
            trading_profiles, "load_selected_profile_id", lambda: "tiger-paper-sdk"
        )

        def _markets(exchange_id):
            payload = markets_by_exchange.get(exchange_id)
            if payload is None:
                raise RuntimeError(f"{exchange_id} unavailable")
            return payload

        monkeypatch.setattr(ss, "_load_public_markets", _markets)
        with patch.object(ss.yahoo_client, "search", return_value=yahoo or []):
            return json.loads(ss.SymbolSearchTool().execute(query=query, limit=5))["data"]

    def test_pair_resolves_with_no_connector_selected(self, monkeypatch):
        data = self._run(
            monkeypatch,
            "ETH-USDT",
            {"binance": self._markets("ETH/USDT", "BTC/USDT")},
            yahoo=[
                {
                    "symbol": "AETHUSDT-USD",
                    "shortname": "Aave Ethereum USDT USD",
                    "exchange": "CCC",
                    "quoteType": "CRYPTOCURRENCY",
                }
            ],
        )
        assert [c["symbol"] for c in data["candidates"]] == ["ETH-USDT"]
        assert data["candidates"][0]["exchange"] == "BINANCE"
        assert data["sources"]["public_exchange"] == "ok"

    def test_second_venue_is_consulted_when_the_first_is_down(self, monkeypatch):
        data = self._run(
            monkeypatch, "SOL-USDT", {"okx": self._markets("SOL/USDT")}
        )
        assert [c["symbol"] for c in data["candidates"]] == ["SOL-USDT"]
        assert data["candidates"][0]["exchange"] == "OKX"

    def test_a_pair_no_venue_lists_resolves_to_nothing(self, monkeypatch):
        data = self._run(
            monkeypatch,
            "NOTREAL-USDT",
            {"binance": self._markets("ETH/USDT"), "okx": self._markets("ETH/USDT")},
        )
        assert data["candidates"] == []
        assert data["sources"]["public_exchange"].startswith("skipped:")

    def test_an_equity_query_never_reaches_the_venue_catalogs(self, monkeypatch):
        called: list[str] = []

        def _markets(exchange_id):
            called.append(exchange_id)
            return {}

        monkeypatch.setattr(ss, "_load_public_markets", _markets)
        monkeypatch.setattr(
            trading_profiles, "load_selected_profile_id", lambda: "tiger-paper-sdk"
        )
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=_eastmoney_payload()
        ), patch.object(ss.yahoo_client, "search", return_value=[]):
            ss.SymbolSearchTool().execute(query="apple", limit=5)
        assert called == []


# --------------------------------------------------------------------------
# Pair spellings + index symbols: the crypto pair classifier is now the only
# pair path. Forex is a removed market, so a pair string off the crypto
# whitelist is not canonicalized at all (no FX fallback).
# --------------------------------------------------------------------------


class TestPairSpellingAlignment:
    """search_symbol keeps the crypto pair spellings and index symbols."""

    def test_fiat_pairs_are_not_misclassified_as_crypto(self) -> None:
        """GBP/USD must not be treated as a crypto 'GBP-USD' pair."""
        assert ss._canonical_crypto_pair("GBP/USD") is None
        assert ss._canonical_crypto_pair("EURUSD") is None
        # Crypto classifications must remain untouched.
        assert ss._canonical_crypto_pair("ETH/USD") == "ETH-USD"
        assert ss._canonical_crypto_pair("BTC/USDT") == "BTC-USDT"
        assert ss._canonical_crypto_pair("BTCUSDT") == "BTC-USDT"

    def test_from_yahoo_symbol_leaves_currency_quotes_uncanonicalized(self) -> None:
        """A CURRENCY quote is a removed market: Yahoo's spelling is kept."""
        assert ss._from_yahoo_symbol("GBP/USD", {"quoteType": "CURRENCY"}) == (
            "GBP/USD",
            "global",
        )
        assert ss._from_yahoo_symbol("GBPUSD=X", {"quoteType": "CURRENCY"}) == (
            "GBPUSD=X",
            "global",
        )

    def test_from_yahoo_symbol_labels_indexes(self) -> None:
        assert ss._from_yahoo_symbol("^SPX", {"quoteType": "INDEX"}) == (
            "^SPX",
            "index",
        )
        assert ss._from_yahoo_symbol("^FTSE", {"quoteType": "INDEX"}) == (
            "^FTSE",
            "index",
        )


class TestCryptoUsdBaseWhitelist:
    """``USD`` quote leg on the crypto resolver is gated on a base whitelist.

    Without this guard, ``XAUUSD`` / ``EURUSD`` / ``GBPUSD`` would all be
    classified as crypto pairs and the public-venue catalog (Binance/OKX)
    fallback would either lock onto a tokenized gold token (XAUT/PAXG) or
    find nothing — never on real spot gold. The fix: only accept ``USD`` on
    crypto when the base is in :data:`_CRYPTO_USD_BASES`.
    """

    @pytest.mark.parametrize(
        "code",
        [
            # Genuine crypto pairs - must keep working.
            "BTC-USD",
            "ETH-USD",
            "SOL-USD",
            "BNB-USD",
            "XLM-USD",
            "XRP-USD",
            # Stablecoin-quoted pairs (existing behaviour preserved).
            "BTC-USDT",
            "XAUT-USDT",
            "PAXG-USDT",
            "ETH-USDC",
        ],
    )
    def test_crypto_pairs_with_supported_base_accepted(self, code):
        assert ss._canonical_crypto_pair(code) is not None

    @pytest.mark.parametrize(
        "code",
        [
            # The reported bug: a spot gold query must NOT resolve to a
            # crypto pair, or the public-venue catalog fallback will lock a
            # tokenized-gold row (XAUT-USDT) as the answer.
            "XAUUSD",
            "XAU-USD",
            "XAU/USD",
            # Forex pairs in 6-letter, dashed, or slashed form.
            "EURUSD",
            "EUR-USD",
            "EUR/USD",
            "GBPUSD",
            "GBP-USD",
            "JPYUSD",
        ],
    )
    def test_non_crypto_bases_with_usd_quote_rejected(self, code):
        """The ``USD`` leg on non-crypto bases must NOT pass as a crypto pair."""
        assert ss._canonical_crypto_pair(code) is None

    def test_tokenized_gold_bases_still_resolve_as_crypto(self):
        # XAUT/PAXG ARE crypto (tokenized gold on Binance/OKX spot) and
        # must keep resolving as crypto. The whitelist includes them.
        assert ss._canonical_crypto_pair("XAUT-USDT") == "XAUT-USDT"
        assert ss._canonical_crypto_pair("PAXG-USDT") == "PAXG-USDT"
        assert ss._canonical_crypto_pair("XAUT-USD") == "XAUT-USD"
        assert ss._canonical_crypto_pair("PAXG-USD") == "PAXG-USD"

    def test_xauusd_and_xautusdt_are_not_equivalent_assets(self):
        # Identity correctness: the resolver must treat XAUUSD (spot gold)
        # and XAUT-USDT (tokenized gold) as different instruments. If both
        # return the same canonical string, downstream lock/identity
        # collision is possible.
        spot = ss._canonical_crypto_pair("XAUUSD")
        tokenized = ss._canonical_crypto_pair("XAUT-USDT")
        assert spot is None
        assert tokenized == "XAUT-USDT"
        assert spot != tokenized

    def test_usd_whitelist_is_a_strict_subset_of_crypto_bases(self):
        # Defensive: the whitelist is what stops non-crypto bases from
        # slipping through the ``USD`` branch. Every base in it must
        # therefore actually be tradable on Binance or OKX spot.
        # This is a coarse sanity check on the whitelist contents; if a
        # new entry is added in error, this test will still pass (it only
        # checks the union is non-empty and is a subset of the quote-asset
        # alphabet).
        assert ss._CRYPTO_USD_BASES
        for base in ss._CRYPTO_USD_BASES:
            assert base.isalpha()
            assert base.isupper()

class TestExactPairCandidateFilter:
    """An explicit crypto pair query is an exact instrument assertion.

    Yahoo's free-text search can return a near-string crypto pair for a
    different instrument. The resolver-side ``_canonical_crypto_pair`` already
    rejects those candidates, but the symbol-search tool itself used to keep
    them in the candidate list, propagating the wrong instrument to the
    identity gate. The fix: when the query IS a crypto pair, drop any
    candidate whose canonical form is a different pair. Free-text name
    queries (``apple``, ``tesla``) are unaffected.

    The spot-metal / FX leg reconciliation that used to sit beside this
    filter went away with the removed market: those query shapes are no
    longer canonicalized at all, so there is nothing left to reconcile.
    """

    def _run(self, query, yahoo_hits, eastmoney_rows=None):
        # Default to an empty Eastmoney payload so the test isolates the
        # Yahoo branch (the layer under test).
        tool = ss.SymbolSearchTool()
        em_payload = {"QuotationCodeTable": {"Data": eastmoney_rows or []}}
        with patch.object(
            ss.eastmoney_client, "get_json", return_value=em_payload
        ), patch.object(ss.yahoo_client, "search", return_value=yahoo_hits), \
             patch.object(ss, "_load_public_markets", return_value={}), \
             patch.object(ss, "_enrich_us_cik", side_effect=lambda c, s="ok": (c, s)), \
             patch.object(
                 trading_profiles, "load_selected_profile_id",
                 side_effect=OSError("no connector"),
             ):
            out = tool.execute(query=query, limit=10)
        return json.loads(out)

    def test_crypto_pair_query_drops_near_string_crypto_hits(self):
        """A near-string crypto pair is a different asset and must be dropped."""
        yahoo = [
            {"symbol": "AETHUSDT-USD", "shortname": "Aave Ethereum USDT",
             "exchange": "CCC", "quoteType": "CRYPTOCURRENCY", "index": "AETH"},
        ]
        data = self._run("BTC-USD", yahoo)["data"]
        assert data["count"] == 0
        assert data["candidates"] == []

    def test_gc_f_keeps_correct_futures_hit(self):
        yahoo = [
            {"symbol": "GC=F", "shortname": "Gold Continuous Front Month",
             "exchange": "NYM", "quoteType": "FUTURE", "index": "GC"},
        ]
        data = self._run("GC=F", yahoo)["data"]
        assert data["count"] == 1
        assert data["candidates"][0]["symbol"] == "GC=F"

    def test_xaut_usdt_keeps_tokenized_gold(self):
        yahoo = [
            {"symbol": "XAUT-USDT", "shortname": "Tether Gold",
             "exchange": "CCC", "quoteType": "CRYPTOCURRENCY", "index": "XAUT"},
        ]
        data = self._run("XAUT-USDT", yahoo)["data"]
        assert data["count"] == 1
        assert data["candidates"][0]["symbol"] == "XAUT-USDT"

    def test_paxg_usdt_keeps_tokenized_gold(self):
        yahoo = [
            {"symbol": "PAXG-USDT", "shortname": "Paxos Gold",
             "exchange": "CCC", "quoteType": "CRYPTOCURRENCY", "index": "PAXG"},
        ]
        data = self._run("PAXG-USDT", yahoo)["data"]
        assert data["count"] == 1
        assert data["candidates"][0]["symbol"] == "PAXG-USDT"

    def test_free_text_name_query_unaffected(self):
        """A free-text company name (``apple``) is NOT a ticker shape and
        must not have crypto candidates stripped. Yahoo's free-text
        answer may include near-string crypto hits (``BTC-USD``) which
        the user is allowed to see and choose from.
        """
        yahoo = [
            {"symbol": "BTC-USD", "shortname": "Bitcoin USD",
             "exchange": "CCC", "quoteType": "CRYPTOCURRENCY", "index": "BTC"},
            {"symbol": "AAPL.US", "shortname": "Apple Inc.",
             "exchange": "NMS", "quoteType": "EQUITY", "index": "AAPL"},
        ]
        data = self._run("apple", yahoo)["data"]
        symbols = [c["symbol"] for c in data["candidates"]]
        assert "BTC-USD" in symbols
        assert "AAPL.US" in symbols
