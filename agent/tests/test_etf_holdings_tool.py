"""Tests for etf_holdings_tool: routing, parsing, as-of honesty, degradation.

Every fixture below is a trimmed copy of a real payload captured from the live
endpoint, and all HTTP is mocked at the module's transport seam
(:func:`_sec_get_text`), so no test touches the network.

The regressions these tests exist for:

* N-PORT's ``repPdEnd`` is the fund's fiscal year end, not the report period.
  IVV's amendment carries ``repPdEnd`` 2026-03-31 with ``repPdDate``
  2025-09-30, so reading the wrong tag stamps September holdings with a March
  date — and picking the newest *filed* document returns that September
  portfolio when a March one exists.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import src.tools.etf_holdings_tool as etf
from src.tools.etf_holdings_tool import EtfHoldingsTool

# ── Fixtures shaped exactly like the live payloads ───────────────────────────

_SERIES_CSV = (
    "﻿Reporting File Number,CIK Number,Entity Name,Entity Org Type,Series ID,"
    "Series Name,Class ID,Class Name,Class Ticker,Address_1,Address_2,City,State,Zip Code\n"
    "811-09729,0001100663,iSHARES TRUST,30,S000004310,iShares Core S&P 500 ETF,"
    "C000012040,iShares Core S&P 500 ETF,IVV,400 HOWARD STREET,,SAN FRANCISCO,CA,94105\n"
    "811-09729,0001100663,iSHARES TRUST,30,S000004354,iShares Semiconductor ETF,"
    "C000012084,iShares Semiconductor ETF,SOXX,400 HOWARD STREET,,SAN FRANCISCO,CA,94105\n"
    "811-00001,0000000001,NO TICKER TRUST,30,S000000001,Unlisted Series,C000000001,"
    "Class A,,1 MAIN ST,,NEW YORK,NY,10001\n"
)

_ATOM = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <company-info><cik>0001100663</cik><conformed-name>iSHARES TRUST</conformed-name></company-info>
  <entry>
    <content type="text/xml">
      <accession-number>0002071691-26-015790</accession-number>
      <filing-date>2026-07-13</filing-date>
      <filing-type>NPORT-P/A</filing-type>
    </content>
  </entry>
  <entry>
    <content type="text/xml">
      <accession-number>0002071691-26-012459</accession-number>
      <filing-date>2026-05-28</filing-date>
      <filing-type>NPORT-P</filing-type>
    </content>
  </entry>
</feed>
"""

# The amendment was filed later but covers an earlier period.
_FTS = json.dumps(
    {
        "hits": {
            "total": {"value": 2, "relation": "eq"},
            "hits": [
                {
                    "_id": "0002071691-26-015790:primary_doc.xml",
                    "_source": {"period_ending": "2025-09-30", "file_date": "2026-07-13"},
                },
                {
                    "_id": "0002071691-26-012459:primary_doc.xml",
                    "_source": {"period_ending": "2026-03-31", "file_date": "2026-05-28"},
                },
            ],
        }
    }
)


def _nport(series_id: str, rep_pd_date: str, rep_pd_end: str) -> str:
    """Build an N-PORT document with two holdings, real tag names and namespace."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nport">
  <headerData><submissionType>NPORT-P</submissionType></headerData>
  <formData>
    <genInfo>
      <regName>iShares Trust</regName>
      <seriesName>iShares Core S&amp;P 500 ETF</seriesName>
      <seriesId>{series_id}</seriesId>
      <repPdEnd>{rep_pd_end}</repPdEnd>
      <repPdDate>{rep_pd_date}</repPdDate>
    </genInfo>
    <fundInfo>
      <totAssets>721570012380.01</totAssets>
      <netAssets>720543356320.99</netAssets>
    </fundInfo>
    <invstOrSecs>
      <invstOrSec>
        <name>NVIDIA Corp.</name>
        <title>NVIDIA Corp.</title>
        <cusip>67066G104</cusip>
        <identifiers><isin value="US67066G1040"/><other otherDesc="x" value="y"/></identifiers>
        <balance>312526688.00000000</balance>
        <units>NS</units>
        <curCd>USD</curCd>
        <valUSD>54504654387.20000000</valUSD>
        <pctVal>7.564382338558</pctVal>
        <payoffProfile>Long</payoffProfile>
        <assetCat>EC</assetCat>
        <invCountry>US</invCountry>
      </invstOrSec>
      <invstOrSec>
        <name>CBRE Group, Inc.</name>
        <cusip>12504L109</cusip>
        <identifiers><isin value="US12504L1098"/></identifiers>
        <valUSD>506139381.54000000</valUSD>
        <pctVal>0.070244125783</pctVal>
        <assetCat>EC</assetCat>
      </invstOrSec>
    </invstOrSecs>
  </formData>
</edgarSubmission>
"""


@pytest.fixture(autouse=True)
def _clear_caches():
    """Reset the process-wide memoized SEC index between tests."""
    etf._US_INDEX_CACHE = None
    yield
    etf._US_INDEX_CACHE = None


def _sec_router(url, params=None):
    """Serve the SEC fixtures by URL, mirroring the live endpoint layout."""
    if "series-class" in url:
        return _SERIES_CSV
    if "browse-edgar" in url:
        return _ATOM
    if "search-index" in url:
        return _FTS
    if "015790" in url:
        return _nport("S000004310", "2025-09-30", "2026-03-31")
    return _nport("S000004310", "2026-03-31", "2026-03-31")


class TestUsHoldings:
    """N-PORT parsing, period selection and the as-of contract."""

    def test_report_period_comes_from_rep_pd_date_not_rep_pd_end(self):
        parsed = etf._parse_nport(_nport("S000004310", "2025-09-30", "2026-03-31"))
        assert parsed["as_of"] == "2025-09-30"
        assert parsed["fiscal_year_end"] == "2026-03-31"

    def test_newest_period_wins_over_newest_filing_date(self):
        with patch.object(etf, "_sec_get_text", side_effect=_sec_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="IVV", top_n=5))
        assert payload["ok"] is True
        # The amendment was filed 2026-07-13 but covers 2025-09-30; the answer
        # must be the 2026-03-31 original.
        assert payload["as_of"] == "2026-03-31"
        assert payload["data"]["filing"]["accession"] == "0002071691-26-012459"
        assert payload["data"]["filing"]["period_source"] == "edgar_full_text_index"

    def test_falls_back_to_filing_order_when_periods_unknown(self):
        chosen = etf._select_nport_filing(
            [
                {"form": "NPORT-P/A", "accession": "A", "filing_date": "2026-07-13"},
                {"form": "NPORT-P", "accession": "B", "filing_date": "2026-05-28"},
            ],
            {},
        )
        assert chosen["accession"] == "A"
        assert chosen["period_source"] == "filing_order"

    def test_a_filing_the_index_cannot_date_is_counted_not_silently_skipped(self):
        # EDGAR's full-text index lags the filing feed, so the newest NPORT-P
        # can be listed with no period yet. Ranking by period drops it, which
        # would answer with last quarter's portfolio and look authoritative.
        thin_fts = json.dumps(
            {
                "hits": {
                    "hits": [
                        {
                            "_id": "0002071691-26-012459:primary_doc.xml",
                            "_source": {"period_ending": "2026-03-31"},
                        }
                    ]
                }
            }
        )

        def router(url, params=None):
            return thin_fts if "search-index" in url else _sec_router(url, params)

        with patch.object(etf, "_sec_get_text", side_effect=router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="IVV"))
        assert payload["data"]["filing"]["candidates_without_period"] == 1
        assert "WARNING" in payload["notes"]

    def test_a_fully_indexed_filing_list_carries_no_warning(self):
        with patch.object(etf, "_sec_get_text", side_effect=_sec_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="IVV"))
        assert payload["data"]["filing"]["candidates_without_period"] == 0
        assert "WARNING" not in payload["notes"]

    def test_envelope_carries_lag_coverage_and_full_portfolio_count(self):
        with patch.object(etf, "_sec_get_text", side_effect=_sec_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="ivv", top_n=1))
        assert payload["coverage"] == "full_portfolio"
        assert payload["data"]["filing"]["disclosure_lag_days"] == 58
        assert payload["data"]["holdings_in_filing"] == 2
        assert payload["data"]["fund"]["net_assets_usd"] == 720543356320.99

    def test_holdings_are_ranked_by_weight_and_omit_absent_fields(self):
        with patch.object(etf, "_sec_get_text", side_effect=_sec_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="IVV"))
        holdings = payload["data"]["holdings"]
        assert [h["name"] for h in holdings] == ["NVIDIA Corp.", "CBRE Group, Inc."]
        assert holdings[0]["pct_of_net_assets"] == 7.564382338558
        assert holdings[0]["isin"] == "US67066G1040"
        # The second holding reports no balance/units; those keys are absent
        # rather than defaulted to zero.
        assert "balance" not in holdings[1]
        assert "ticker" not in holdings[0]

    def test_series_mismatch_refuses_to_attribute_the_filing(self):
        def router(url, params=None):
            if "primary_doc" in url:
                return _nport("S000099999", "2026-03-31", "2026-03-31")
            return _sec_router(url, params)

        with patch.object(etf, "_sec_get_text", side_effect=router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="IVV"))
        assert payload["ok"] is False
        assert "S000099999" in payload["error"]

    def test_unlisted_ticker_names_the_uit_gap(self):
        with patch.object(etf, "_sec_get_text", side_effect=_sec_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="holdings", symbol="SPY"))
        assert payload["ok"] is False
        assert "SPY" in payload["error"]

    def test_document_url_drops_cik_padding_and_accession_dashes(self):
        assert etf._nport_document_url("0001100663", "0002071691-26-012459") == (
            "https://www.sec.gov/Archives/edgar/data/1100663/"
            "000207169126012459/primary_doc.xml"
        )

    def test_large_portfolio_is_paged_not_truncated(self):
        many = "".join(
            f"<invstOrSec><name>Holding {i}</name><cusip>{i:09d}</cusip>"
            f"<valUSD>1000.0</valUSD><pctVal>{100 - i * 0.1}</pctVal>"
            f"<assetCat>EC</assetCat><invCountry>US</invCountry>"
            f"<payoffProfile>Long</payoffProfile><curCd>USD</curCd>"
            f"<units>NS</units><balance>10.0</balance></invstOrSec>"
            for i in range(150)
        )
        doc = _nport("S000004310", "2026-03-31", "2026-03-31").replace(
            "</invstOrSecs>", many + "</invstOrSecs>"
        )

        def router(url, params=None):
            return doc if "primary_doc" in url else _sec_router(url, params)

        with patch.object(etf, "_sec_get_text", side_effect=router):
            text = EtfHoldingsTool().execute(mode="holdings", symbol="IVV", top_n=200)
        payload = json.loads(text)
        assert len(text) <= 10_000
        assert payload["paging"]["complete"] is False
        assert payload["paging"]["next_offset"] == payload["paging"]["returned"]
        assert payload["data"]["holdings_in_filing"] == 152


class TestUsLookup:
    """Ticker/name search over the SEC series-class index."""

    def test_exact_ticker_ranks_first_and_name_search_works(self):
        with patch.object(etf, "_sec_get_text", side_effect=_sec_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="lookup", query="semiconductor"))
        assert payload["market"] == "US"
        assert payload["data"]["matches"][0]["ticker"] == "SOXX"
        assert payload["data"]["matches"][0]["series_id"] == "S000004354"

    def test_missing_fields_are_declared_never_estimated(self):
        with patch.object(etf, "_sec_get_text", side_effect=_sec_router):
            payload = json.loads(EtfHoldingsTool().execute(mode="lookup", query="IVV"))
        assert "expense_ratio" in payload["missing_fields"]
        assert "expense_ratio" not in payload["data"]["matches"][0]
        assert payload["as_of"] == {"index_year": etf.date.today().year}

    def test_rows_without_a_ticker_are_dropped(self):
        records = etf._parse_series_index(_SERIES_CSV)
        assert {r["ticker"] for r in records} == {"IVV", "SOXX"}

    def test_etf_share_classes_outrank_mutual_fund_classes_on_a_theme_query(self):
        # Live check: "semiconductor" matches 31 classes, and in filer order the
        # first eight are Fidelity mutual fund classes, so an unranked default
        # page of ten never reaches SOXX/SMH/XSD.
        csv_body = (
            _SERIES_CSV
            + "811-03010,0000315700,FIDELITY ADVISOR SERIES VII,30,S000005327,"
            "Fidelity Advisor Semiconductors Fund,C000014549,Class A,FELAX,"
            "245 SUMMER STREET,,BOSTON,MA,02210\n"
            # VOO's ETF-ness is only visible in the class name.
            "811-02652,0000036405,VANGUARD INDEX FUNDS,30,S000002839,"
            "Vanguard 500 Semiconductor Index Fund,C000092055,ETF Shares,VOO,"
            "PO BOX 2600,V26,VALLEY FORGE,PA,19482\n"
        )

        def router(url, params=None):
            return csv_body if "series-class" in url else _sec_router(url, params)

        with patch.object(etf, "_sec_get_text", side_effect=router):
            payload = json.loads(
                EtfHoldingsTool().execute(mode="lookup", query="semiconductor", limit=3)
            )
        assert [m["ticker"] for m in payload["data"]["matches"]] == ["SOXX", "VOO", "FELAX"]

    def test_a_row_with_more_fields_than_the_header_does_not_kill_the_index(self):
        # csv.DictReader files the overflow under a None key as a *list*; the
        # whole US path used to die on ``.strip()`` if the SEC ever emitted one.
        records = etf._parse_series_index(
            _SERIES_CSV + "811-1,0000000002,STRAY TRUST,30,S000000002,Stray ETF,"
            "C000000002,Class A,STRY,1 MAIN ST,,NEW YORK,NY,10001,extra,extra2\n"
        )
        assert {r["ticker"] for r in records} == {"IVV", "SOXX", "STRY"}

    def test_index_falls_back_to_the_previous_year(self):
        seen: list[str] = []

        def router(url, params=None):
            seen.append(url)
            if f"{etf.date.today().year}.csv" in url:
                raise RuntimeError("404 not posted yet")
            return _SERIES_CSV

        with patch.object(etf, "_sec_get_text", side_effect=router):
            year, records = etf._us_series_index()
        assert year == etf.date.today().year - 1
        assert len(records) == 2
        assert len(seen) == 2


class TestArgumentValidation:
    """Bad input yields the error envelope rather than an exception."""

    @pytest.mark.parametrize(
        "kwargs,fragment",
        [
            ({}, "mode must be one of"),
            ({"mode": "nope"}, "mode must be one of"),
            ({"mode": "lookup"}, "'query' is required"),
            ({"mode": "lookup", "query": "   "}, "'query' is required"),
            ({"mode": "holdings"}, "'symbol' is required"),
            ({"mode": "lookup", "query": "IVV", "offset": "x"}, "offset must be an integer"),
        ],
    )
    def test_invalid_arguments(self, kwargs, fragment):
        payload = json.loads(EtfHoldingsTool().execute(**kwargs))
        assert payload["ok"] is False
        assert fragment in payload["error"]

    @pytest.mark.parametrize(
        "value,expected",
        [(None, 25), (0, 1), (-5, 1), (10_000, 6000), ("30", 30), ("junk", 25)],
    )
    def test_top_n_is_clamped(self, value, expected):
        assert etf._clamp(value, 25, etf._MAX_TOP_N) == expected

    def test_top_n_ceiling_clears_a_real_full_portfolio(self):
        # A broad-market US fund can run past a thousand names; the ceiling has
        # to clear the largest real book with headroom, or a top_n cut would hand
        # back a truncated portfolio.
        assert etf._MAX_TOP_N >= 2031

    def test_tool_contract(self):
        tool = EtfHoldingsTool()
        assert tool.name == "etf_holdings"
        assert tool.is_readonly is True
        assert tool.check_available() is True
        assert tool.parameters["required"] == ["mode"]
        assert json.dumps(tool.to_openai_schema())
