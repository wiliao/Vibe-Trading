"""Read-only ETF look-through: fund search + constituent holdings (SEC N-PORT).

An ETF price series says nothing about what the fund actually owns. This tool
answers that second question from free, no-auth SEC filings, and — because every
ETF holdings disclosure is *stale by construction* — stamps every answer with the
report period it belongs to.

Registered funds file Form NPORT-P, whose ``primary_doc.xml`` carries the
**entire** portfolio (``invstOrSecs/invstOrSec``) plus total/net assets. Three
verified facts drive the US path:

* ``company_tickers.json`` (used by :mod:`backtest.loaders.sec_edgar_client`)
  does **not** list most ETFs — IVV, VOO, ARKK and XLK are all absent, because
  the reporting entity is the trust, not the fund. The ticker index that does
  cover them is the Investment Company Series and Class file, which maps
  ``Class Ticker -> (CIK, Series ID, Series Name, Entity Name)``.
* A trust files one NPORT-P per series per period (iShares Trust files
  hundreds), so the filing list must be filtered by ``Series ID``. The only
  endpoint that does that is the EDGAR browse CGI in ``output=atom`` mode.
* ``repPdEnd`` is the fund's **fiscal year end**, not the report period.
  IVV's amendment ``0002071691-26-015790`` carries ``repPdEnd`` 2026-03-31 with
  ``repPdDate`` 2025-09-30, and EDGAR's own "Period of Report" for it reads
  2025-09-30. ``repPdDate`` is therefore the as-of date; reading ``repPdEnd``
  would have stamped September holdings with a March date.
* The newest *filed* document is not the newest *period*: that same amendment
  was filed 2026-07-13, two months after the 2026-03-31 report. Filings are
  therefore ranked by their indexed period, not by filing date.
* Disclosure lags: IVV's period ending 2026-03-31 was filed 2026-05-28.

Everything routes through :mod:`backtest.loaders._http` so the SEC per-host
throttle, session and User-Agent policy are the project's existing ones, not a
second stack. No optional package is required.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import threading
from datetime import date, datetime
from typing import Any

from defusedxml import ElementTree as DefusedET

from backtest.loaders import sec_edgar_client
from backtest.loaders._http import throttled_get
from src.agent.tools import BaseTool
from src.tools._result_paging import fit_records

logger = logging.getLogger(__name__)

# ── SEC endpoints ────────────────────────────────────────────────────────────

# Ticker -> (CIK, Series ID, Series Name) for every registered fund share class.
# Published per calendar year; the current year is tried first and the previous
# year is the fallback for the window early in January before it is posted.
_SEC_SERIES_INDEX_URL = (
    "https://www.sec.gov/files/investment/data/other/"
    "investment-company-series-class-information/"
    "investment-company-series-class-{year}.csv"
)
# The only EDGAR index that can be filtered to a single fund series.
_SEC_BROWSE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
_SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
# Full-text search: the one endpoint that reports each accession's period of
# report in bulk, so the newest *period* can be picked without downloading a
# half-megabyte filing per candidate.
_SEC_FTS_URL = "https://efts.sec.gov/LATEST/search-index"

_NPORT_HOST_KEY = "sec"

# ── Result shaping ───────────────────────────────────────────────────────────

# A broad-market U.S. fund can run past a thousand names, so the cap is set high
# enough to clear a real full portfolio; ``fit_records`` still pages the answer
# down to one result's worth, so a large cap costs nothing per response.
_MAX_TOP_N = 6000
_DEFAULT_TOP_N = 25
_MAX_LOOKUP = 40
_DEFAULT_LOOKUP = 10
# NPORT-P filings are quarterly; ten entries is ~2.5 years of report periods.
_SEC_FILING_COUNT = 10

_MODES = ("lookup", "holdings")

# The SEC N-PORT filing publishes no expense ratio, so it is declared missing
# rather than estimated.
_NOTE_LAG = (
    "ETF holdings are disclosed with a lag. 'as_of' is the report period the "
    "holdings belong to, NOT today's portfolio."
)


def _error(message: str) -> str:
    """Build the failure envelope as a JSON string.

    Args:
        message: Human-readable error description.

    Returns:
        A ``{"ok": false, "error": ...}`` JSON string.
    """
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


# ── HTTP transport (reuses the shared per-host throttles) ────────────────────


def _sec_get_text(url: str, params: dict[str, Any] | None = None) -> str:
    """GET an SEC URL as text through the shared ``"sec"`` throttle bucket.

    The frozen SEC client only decodes JSON, while both endpoints this tool
    needs return XML/CSV, so the transport is reused rather than reimplemented:
    same bucket, same interval floor, same contact User-Agent (env-overridable
    via ``VIBE_TRADING_SEC_UA``).

    Args:
        url: Fully-qualified ``sec.gov`` URL.
        params: Optional query parameters.

    Returns:
        The decoded response body.

    Raises:
        requests.RequestException: Network failure or non-2xx status.
    """
    response = throttled_get(
        url,
        host_key=_NPORT_HOST_KEY,
        min_interval=sec_edgar_client._min_interval(),
        params=params,
        headers={"User-Agent": sec_edgar_client._user_agent()},
        timeout=60.0,
    )
    response.raise_for_status()
    return response.text


# ── US: series/class ticker index ────────────────────────────────────────────

_US_INDEX_CACHE: tuple[int, list[dict[str, Any]]] | None = None
_US_INDEX_LOCK = threading.Lock()


def _parse_series_index(body: str) -> list[dict[str, Any]]:
    """Parse the SEC series/class CSV into ticker-bearing fund records.

    The header carries a UTF-8 BOM and the columns are ``Reporting File
    Number``, ``CIK Number``, ``Entity Name``, ``Entity Org Type``, ``Series
    ID``, ``Series Name``, ``Class ID``, ``Class Name``, ``Class Ticker`` and
    address fields. Rows without a ticker are share classes that cannot be
    searched by symbol and are dropped.

    A row carrying more fields than the header lands under ``DictReader``'s
    rest-key as a *list*, so values are type-checked rather than assumed to be
    strings — one malformed row would otherwise take the whole US path down.

    Args:
        body: Decoded CSV text.

    Returns:
        A list of ``{ticker, cik, series_id, series_name, class_id, class_name,
        entity_name, file_number}`` dicts.
    """
    rows: list[dict[str, Any]] = []
    for raw in csv.DictReader(io.StringIO(body)):
        record = {
            (k or "").lstrip("﻿").strip(): (v.strip() if isinstance(v, str) else "")
            for k, v in raw.items()
        }
        ticker = record.get("Class Ticker", "")
        series_id = record.get("Series ID", "")
        if not ticker or not series_id:
            continue
        rows.append(
            {
                "ticker": ticker.upper(),
                "cik": record.get("CIK Number") or None,
                "series_id": series_id,
                "series_name": record.get("Series Name") or None,
                "class_id": record.get("Class ID") or None,
                # Vanguard's ETF share classes sit inside a mutual fund whose
                # series name says "Fund" (VOO -> "Vanguard 500 Index Fund"),
                # so the class name is the only ETF signal on those rows.
                "class_name": record.get("Class Name") or None,
                "entity_name": record.get("Entity Name") or None,
                "file_number": record.get("Reporting File Number") or None,
            }
        )
    return rows


def _us_series_index() -> tuple[int, list[dict[str, Any]]]:
    """Return ``(index_year, records)`` for the SEC series/class index, memoized.

    Returns:
        The calendar year of the file actually used and its parsed records.

    Raises:
        RuntimeError: When neither the current nor the previous year's file can
            be fetched.
    """
    global _US_INDEX_CACHE
    if _US_INDEX_CACHE is not None:
        return _US_INDEX_CACHE
    with _US_INDEX_LOCK:
        if _US_INDEX_CACHE is None:
            this_year = date.today().year
            failures: list[str] = []
            for year in (this_year, this_year - 1):
                try:
                    body = _sec_get_text(_SEC_SERIES_INDEX_URL.format(year=year))
                except Exception as exc:  # noqa: BLE001 - try the older vintage
                    failures.append(f"{year}: {exc}")
                    continue
                records = _parse_series_index(body)
                if records:
                    _US_INDEX_CACHE = (year, records)
                    break
                failures.append(f"{year}: index parsed to zero rows")
            else:
                raise RuntimeError(
                    "SEC investment-company series/class index unavailable ("
                    + "; ".join(failures)
                    + ")"
                )
    return _US_INDEX_CACHE


def _is_etf_class(record: dict[str, Any]) -> bool:
    """Report whether an index row looks like an exchange-traded share class.

    The SEC series/class file has no ETF flag, so the only available signal is
    the wording: an ETF is named one either in its series name (``iShares
    Semiconductor ETF``) or in its class name (VOO is ``ETF Shares`` of the
    ``Vanguard 500 Index Fund``). This is a ranking heuristic only — nothing is
    dropped on the strength of it, and the underlying names are returned so the
    caller can judge for itself.

    Args:
        record: One parsed index row.

    Returns:
        ``True`` when either name carries the word "ETF".
    """
    return "ETF" in f"{record.get('series_name') or ''} {record.get('class_name') or ''}".upper()


def _us_match(query: str, limit: int) -> list[dict[str, Any]]:
    """Find fund share classes by exact ticker, then by name substring.

    A theme query such as "semiconductor" matches far more mutual fund share
    classes than ETFs, and the index is in filer order, so an unranked answer
    fills the whole first page with non-ETF classes and hides SOXX/SMH/XSD
    behind it. Name matches are therefore ordered ETFs-first, index order kept
    within each group. Exact ticker hits still outrank everything.

    Args:
        query: A ticker, a fund name, or a theme keyword.
        limit: Maximum matches to return.

    Returns:
        Matching index records, exact ticker hits first and ETF share classes
        ahead of other classes.
    """
    _, records = _us_series_index()
    needle = query.strip().upper()
    exact = [r for r in records if r["ticker"] == needle]
    if len(exact) >= limit:
        return exact[:limit]
    seen = {id(r) for r in exact}
    partial = [
        r
        for r in records
        if id(r) not in seen
        and (
            needle in (r["series_name"] or "").upper()
            or needle in (r["entity_name"] or "").upper()
            or (len(needle) >= 2 and r["ticker"].startswith(needle))
        )
    ]
    partial.sort(key=lambda r: not _is_etf_class(r))
    return (exact + partial)[:limit]


# ── US: N-PORT filing index + holdings ───────────────────────────────────────


def _local_name(tag: str) -> str:
    """Strip the XML namespace from a tag, returning its local name."""
    return tag.rpartition("}")[2]


def _us_nport_filings(series_id: str) -> list[dict[str, Any]]:
    """List a fund series' NPORT-P filings, newest first.

    Args:
        series_id: SEC series identifier, e.g. ``"S000004310"``.

    Returns:
        A list of ``{form, accession, filing_date}`` dicts. Empty when the
        series has filed none.

    Raises:
        requests.RequestException: Network failure or non-2xx status.
    """
    body = _sec_get_text(
        _SEC_BROWSE_URL,
        params={
            "action": "getcompany",
            "CIK": series_id,
            "type": "NPORT-P",
            "dateb": "",
            "owner": "include",
            "count": str(_SEC_FILING_COUNT),
            "output": "atom",
        },
    )
    try:
        root = DefusedET.fromstring(body.encode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - a malformed feed is a data error
        raise RuntimeError(f"EDGAR filing feed did not parse: {exc}") from exc

    filings: list[dict[str, Any]] = []
    for element in root.iter():
        if _local_name(element.tag) != "content":
            continue
        fields = {_local_name(c.tag): (c.text or "").strip() for c in element}
        accession = fields.get("accession-number")
        if not accession:
            continue
        filings.append(
            {
                "form": fields.get("filing-type") or None,
                "accession": accession,
                "filing_date": fields.get("filing-date") or None,
            }
        )
    return filings


def _us_indexed_periods(series_id: str) -> dict[str, str]:
    """Map accession -> period of report for a series, from EDGAR full-text search.

    The atom filing index carries no period, and the newest-filed NPORT-P is
    routinely an amendment of an older period, so the periods are read from the
    full-text index in one request instead of by downloading each candidate
    filing. This is a best-effort enrichment: a failure returns an empty map and
    the caller falls back to filing order.

    Args:
        series_id: SEC series identifier, e.g. ``"S000004310"``.

    Returns:
        Mapping of accession number to ``YYYY-MM-DD`` period of report.
    """
    try:
        body = _sec_get_text(_SEC_FTS_URL, params={"q": f'"{series_id}"', "forms": "NPORT-P"})
        payload = json.loads(body)
    except Exception as exc:  # noqa: BLE001 - enrichment only, never fatal
        logger.warning("EDGAR full-text period lookup failed for %s: %s", series_id, exc)
        return {}

    hits = ((payload.get("hits") or {}).get("hits") or []) if isinstance(payload, dict) else []
    periods: dict[str, str] = {}
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        accession = str(hit.get("_id") or "").split(":", 1)[0]
        period = (hit.get("_source") or {}).get("period_ending")
        if accession and period:
            periods[accession] = str(period)
    return periods


def _select_nport_filing(filings: list[dict[str, Any]], periods: dict[str, str]) -> dict[str, Any]:
    """Pick the filing covering the newest report period, newest vintage first.

    Args:
        filings: Atom-derived filings for one series, newest filed first.
        periods: Accession -> period of report, possibly empty or partial.

    Returns:
        The chosen filing dict, annotated with ``indexed_period``,
        ``period_source`` ("edgar_full_text_index" when a period was known,
        "filing_order" when the newest-filed had to be assumed) and
        ``candidates_without_period``, the number of listed filings the index
        could not date.
    """
    dated = [f for f in filings if periods.get(f["accession"])]
    undated = len(filings) - len(dated)
    if not dated:
        chosen = dict(filings[0])
        chosen["indexed_period"] = None
        chosen["period_source"] = "filing_order"
        chosen["candidates_without_period"] = undated
        return chosen
    # Newest period wins; among filings for the same period the latest vintage
    # wins, so an amendment supersedes the original it corrects.
    chosen = dict(
        max(dated, key=lambda f: (periods[f["accession"]], f["filing_date"] or ""))
    )
    chosen["indexed_period"] = periods[chosen["accession"]]
    chosen["period_source"] = "edgar_full_text_index"
    # The full-text index lags EDGAR's own filing feed, so a just-filed report
    # can be listed with no period yet. Such filings are skipped by the ranking
    # above, which would otherwise quietly answer with the previous quarter —
    # the count is surfaced so a stale answer is visibly stale.
    chosen["candidates_without_period"] = undated
    return chosen


def _nport_document_url(cik: str, accession: str) -> str:
    """Build the ``primary_doc.xml`` URL for one N-PORT accession.

    Args:
        cik: The registrant CIK, padded or not; leading zeros are dropped.
        accession: Accession number such as ``"0002071691-26-012459"``.

    Returns:
        The fully-qualified EDGAR archive URL.
    """
    return (
        f"{_SEC_ARCHIVES_BASE}/{str(cik).lstrip('0') or '0'}/"
        f"{accession.replace('-', '')}/primary_doc.xml"
    )


def _text_of(parent: Any, name: str) -> str | None:
    """Return the stripped text of ``parent``'s first child named ``name``."""
    if parent is None:
        return None
    for child in parent:
        if _local_name(child.tag) == name:
            text = (child.text or "").strip()
            return text or None
    return None


def _child(parent: Any, name: str) -> Any:
    """Return ``parent``'s first child element named ``name``, or ``None``."""
    if parent is None:
        return None
    for element in parent:
        if _local_name(element.tag) == name:
            return element
    return None


def _to_float(value: Any) -> float | None:
    """Coerce a reported value to ``float``, or ``None`` when non-numeric."""
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _parse_nport_holding(node: Any) -> dict[str, Any]:
    """Shape one ``invstOrSec`` element into a holding record.

    Absent fields are omitted rather than defaulted, so a missing identifier is
    visibly missing instead of silently zero or blank.

    Args:
        node: An ``invstOrSec`` element.

    Returns:
        A holding dict keyed by ``name`` / ``pct_of_net_assets`` / ``value_usd``
        and whatever identifiers the filer supplied.
    """
    identifiers = _child(node, "identifiers")
    isin = ticker = None
    if identifiers is not None:
        for element in identifiers:
            local = _local_name(element.tag)
            if local == "isin":
                isin = (element.get("value") or "").strip() or None
            elif local == "ticker":
                ticker = (element.get("value") or "").strip() or None

    holding: dict[str, Any] = {
        "name": _text_of(node, "name"),
        "title": _text_of(node, "title"),
        "cusip": _text_of(node, "cusip"),
        "isin": isin,
        "ticker": ticker,
        # pctVal is already expressed in percent: IVV's Merck line reports
        # 0.5329 against valUSD 3.84e9 / netAssets 7.21e11.
        "pct_of_net_assets": _to_float(_text_of(node, "pctVal")),
        "value_usd": _to_float(_text_of(node, "valUSD")),
        "balance": _to_float(_text_of(node, "balance")),
        "balance_units": _text_of(node, "units"),
        "currency": _text_of(node, "curCd"),
        "payoff_profile": _text_of(node, "payoffProfile"),
        "asset_category": _text_of(node, "assetCat"),
        "issuer_category": _text_of(node, "issuerCat"),
        "country": _text_of(node, "invCountry"),
    }
    return {k: v for k, v in holding.items() if v is not None}


def _parse_nport(xml_text: str) -> dict[str, Any]:
    """Parse an N-PORT ``primary_doc.xml`` into fund metadata plus holdings.

    Args:
        xml_text: The raw filing document.

    Returns:
        ``{series_id, series_name, registrant, as_of, fiscal_year_end,
        total_assets_usd, net_assets_usd, holdings}``.

    Raises:
        RuntimeError: When the document is not parseable XML.
    """
    try:
        root = DefusedET.fromstring(xml_text.encode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - a malformed filing is a data error
        raise RuntimeError(f"N-PORT document did not parse: {exc}") from exc

    form_data = _child(root, "formData")
    gen_info = _child(form_data, "genInfo")
    fund_info = _child(form_data, "fundInfo")
    securities = _child(form_data, "invstOrSecs")

    holdings = []
    if securities is not None:
        holdings = [
            _parse_nport_holding(node)
            for node in securities
            if _local_name(node.tag) == "invstOrSec"
        ]

    return {
        "series_id": _text_of(gen_info, "seriesId"),
        "series_name": _text_of(gen_info, "seriesName"),
        "registrant": _text_of(gen_info, "regName"),
        # repPdDate is the date the holdings are reported as of; repPdEnd is the
        # fund's fiscal year end. They diverge (IVV: repPdEnd 2026-03-31 with
        # repPdDate 2025-09-30 on the amendment), and EDGAR's own "Period of
        # Report" tracks repPdDate, so that is the as-of.
        "as_of": _text_of(gen_info, "repPdDate"),
        "fiscal_year_end": _text_of(gen_info, "repPdEnd"),
        "total_assets_usd": _to_float(_text_of(fund_info, "totAssets")),
        "net_assets_usd": _to_float(_text_of(fund_info, "netAssets")),
        "holdings": holdings,
    }


def _lag_days(as_of: str | None, filing_date: str | None) -> int | None:
    """Return the whole days between a report period end and its filing date."""
    if not as_of or not filing_date:
        return None
    try:
        return (
            datetime.strptime(filing_date, "%Y-%m-%d").date()
            - datetime.strptime(as_of, "%Y-%m-%d").date()
        ).days
    except ValueError:
        return None


# ── Mode handlers ────────────────────────────────────────────────────────────


def _lookup_us(query: str, limit: int, offset: int) -> str:
    """Search US fund share classes by ticker or name and render the envelope."""
    try:
        index_year, _ = _us_series_index()
        matches = _us_match(query, limit)
    except Exception as exc:  # noqa: BLE001 - surface any fetch failure as envelope
        return _error(f"SEC series/class index lookup failed: {exc}")

    def build(page: list[Any], paging: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "mode": "lookup",
            "market": "US",
            "source": "sec_investment_company_series_class_index",
            "as_of": {"index_year": index_year},
            "missing_fields": ["net_assets", "expense_ratio"],
            "notes": (
                "The SEC series/class index carries identity only. Call "
                "mode='holdings' for net assets and the portfolio; no free SEC "
                "endpoint publishes an expense ratio."
            ),
            "paging": paging,
            "data": {"query": query, "matches": page},
        }

    return fit_records(matches, offset, build)


def _holdings_us(symbol: str, top_n: int, offset: int) -> str:
    """Fetch and render one US ETF's latest N-PORT portfolio."""
    try:
        matches = _us_match(symbol, 1)
    except Exception as exc:  # noqa: BLE001 - surface as envelope
        return _error(f"SEC series/class index lookup failed: {exc}")
    if not matches or matches[0]["ticker"] != symbol.strip().upper():
        return _error(
            f"'{symbol}' is not a fund share class in the SEC series/class index. "
            "Note that unit investment trusts (SPY among them) do not appear there "
            "and file no NPORT-P. Use mode='lookup' to find the right ticker."
        )
    fund = matches[0]

    try:
        filings = _us_nport_filings(fund["series_id"])
    except Exception as exc:  # noqa: BLE001 - surface as envelope
        return _error(f"EDGAR NPORT-P filing index request failed: {exc}")
    if not filings:
        return _error(f"no NPORT-P filing found for {fund['ticker']} ({fund['series_id']})")

    filing = _select_nport_filing(filings, _us_indexed_periods(fund["series_id"]))
    document_url = _nport_document_url(fund["cik"] or "0", filing["accession"])
    try:
        parsed = _parse_nport(_sec_get_text(document_url))
    except Exception as exc:  # noqa: BLE001 - surface as envelope
        return _error(f"N-PORT document request failed: {exc}")

    if parsed["series_id"] and parsed["series_id"] != fund["series_id"]:
        return _error(
            f"filing {filing['accession']} reports series {parsed['series_id']}, "
            f"expected {fund['series_id']} — refusing to attribute it to {fund['ticker']}"
        )

    holdings = parsed["holdings"]
    total_holdings = len(holdings)
    holdings = sorted(
        holdings, key=lambda h: h.get("pct_of_net_assets") or 0.0, reverse=True
    )[:top_n]
    # The document is primary; the full-text index is only how the filing was
    # chosen, so a disagreement is reported rather than reconciled silently.
    as_of = parsed["as_of"] or filing["indexed_period"]

    notes = _NOTE_LAG
    if filing["candidates_without_period"]:
        notes += (
            f" WARNING: {filing['candidates_without_period']} of the "
            f"{len(filings)} listed NPORT-P filings carry no period in EDGAR's "
            "full-text index and were skipped when picking the newest period. "
            "If one of them is a just-filed report the index has not caught up "
            "with, a newer portfolio than this one exists."
        )

    def build(page: list[Any], paging: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "mode": "holdings",
            "market": "US",
            "source": "sec_nport",
            "as_of": as_of,
            "coverage": "full_portfolio",
            "notes": notes,
            "missing_fields": ["expense_ratio"],
            "paging": paging,
            "data": {
                "symbol": fund["ticker"],
                "fund": {
                    "series_name": parsed["series_name"] or fund["series_name"],
                    "registrant": parsed["registrant"] or fund["entity_name"],
                    "cik": fund["cik"],
                    "series_id": fund["series_id"],
                    "class_id": fund["class_id"],
                    "fiscal_year_end": parsed["fiscal_year_end"],
                    "total_assets_usd": parsed["total_assets_usd"],
                    "net_assets_usd": parsed["net_assets_usd"],
                },
                "filing": {
                    "form": filing["form"],
                    "accession": filing["accession"],
                    "filing_date": filing["filing_date"],
                    "disclosure_lag_days": _lag_days(as_of, filing["filing_date"]),
                    "period_source": filing["period_source"],
                    "indexed_period": filing["indexed_period"],
                    "candidates_without_period": filing["candidates_without_period"],
                    "document_url": document_url,
                },
                "holdings_in_filing": total_holdings,
                "holdings_returned_of_top_n": len(holdings),
                "holdings": page,
            },
        }

    return fit_records(holdings, offset, build)


class EtfHoldingsTool(BaseTool):
    """Look through an ETF to its constituents, or search the ETF universe."""

    name = "etf_holdings"
    description = (
        "ETF look-through for U.S.-listed funds. mode='holdings' returns an ETF's "
        "constituent holdings (security, weight, market value) — the FULL "
        "portfolio from the fund's SEC N-PORT filing. mode='lookup' searches "
        "funds by ticker, name or theme and returns their identity and size. "
        "Every answer carries 'as_of', the report period the holdings belong to — "
        "ETF holdings are disclosed with a lag and are never live. Fields the "
        "source does not publish (expense ratio in particular) are listed under "
        "'missing_fields' and never estimated. "
        'Examples: {"mode": "holdings", "symbol": "IVV", "top_n": 20} or '
        '{"mode": "lookup", "query": "semiconductor"}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": list(_MODES),
                "description": (
                    "'lookup' searches the ETF universe by ticker/name/theme; "
                    "'holdings' returns one fund's constituent holdings."
                ),
            },
            "symbol": {
                "type": "string",
                "description": (
                    "Required for mode='holdings'. A U.S. ETF ticker such as "
                    "'IVV', 'SOXX' or 'ARKK'."
                ),
            },
            "query": {
                "type": "string",
                "description": (
                    "Required for mode='lookup'. A ticker, fund name or theme "
                    "keyword, e.g. 'IVV' or 'semiconductor'."
                ),
            },
            "top_n": {
                "type": "integer",
                "description": (
                    "For mode='holdings', how many largest holdings by weight to "
                    f"consider (1-{_MAX_TOP_N}). Defaults to {_DEFAULT_TOP_N}."
                ),
                "default": _DEFAULT_TOP_N,
            },
            "limit": {
                "type": "integer",
                "description": (
                    f"For mode='lookup', maximum matches (1-{_MAX_LOOKUP}). "
                    f"Defaults to {_DEFAULT_LOOKUP}."
                ),
                "default": _DEFAULT_LOOKUP,
            },
            "offset": {
                "type": "integer",
                "description": (
                    "Index of the first record to return. Records are returned "
                    "whole and only as many as fit one result — read "
                    "paging.next_offset and call again to continue."
                ),
                "default": 0,
            },
        },
        "required": ["mode"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Route to the requested mode, returning a JSON envelope.

        Args:
            **kwargs: ``mode`` ("lookup"|"holdings", required), ``symbol``
                (required for holdings), ``query`` (required for lookup),
                ``top_n``, ``limit`` and ``offset``.

        Returns:
            A JSON string. On success ``{"ok": true, "mode", "market",
            "source", "as_of", "coverage"?, "missing_fields", "paging",
            "data"}``; on failure ``{"ok": false, "error": str}``.
        """
        mode = kwargs.get("mode")
        if mode not in _MODES:
            return _error(f"mode must be one of {list(_MODES)}")

        try:
            offset = max(int(kwargs.get("offset") or 0), 0)
        except (TypeError, ValueError):
            return _error("offset must be an integer")

        if mode == "lookup":
            query = kwargs.get("query")
            if not isinstance(query, str) or not query.strip():
                return _error("'query' is required and must be a non-empty string for mode='lookup'")
            limit = _clamp(kwargs.get("limit", _DEFAULT_LOOKUP), _DEFAULT_LOOKUP, _MAX_LOOKUP)
            return _lookup_us(query, limit, offset)

        symbol = kwargs.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            return _error("'symbol' is required and must be a non-empty string for mode='holdings'")
        top_n = _clamp(kwargs.get("top_n", _DEFAULT_TOP_N), _DEFAULT_TOP_N, _MAX_TOP_N)
        return _holdings_us(symbol, top_n, offset)


def _clamp(value: Any, default: int, maximum: int) -> int:
    """Coerce a requested count into ``1..maximum``, falling back to ``default``."""
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(1, min(n, maximum))
