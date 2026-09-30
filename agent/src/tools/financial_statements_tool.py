"""Read-only financial-statements tool: three statements + key indicators.

Pulls a single stock's balance sheet, income statement, cash-flow statement, or
key per-period indicators from US SEC EDGAR companyfacts XBRL, resolved by
ticker->CIK. SEC requests go through the shared EDGAR client
(``host_key="sec"``).

The tool is read-only and self-contained: ``execute`` returns a JSON-string
envelope and never raises for a recoverable per-request failure — a bad symbol
or a transient HTTP error is reported inside the envelope.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backtest.loaders import sec_frames
from backtest.loaders.sec_edgar_client import cik_for, get_company_facts
from src.agent.tools import BaseTool
from src.tools._result_paging import fit_records

logger = logging.getLogger(__name__)

_SEC_CONCEPTS: dict[str, tuple[str, ...]] = {
    "balance": (
        "Assets",
        "AssetsCurrent",
        "CashAndCashEquivalentsAtCarryingValue",
        "Liabilities",
        "LiabilitiesCurrent",
        "LongTermDebtAndFinanceLeaseObligationsCurrentAndNoncurrent",
        "StockholdersEquity",
    ),
    "income": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "GrossProfit",
        "OperatingIncomeLoss",
        "NetIncomeLoss",
        "EarningsPerShareBasic",
        "EarningsPerShareDiluted",
    ),
    "cashflow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInFinancingActivities",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
    ),
    "indicators": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "NetIncomeLoss",
        "Assets",
        "Liabilities",
        "StockholdersEquity",
        "EarningsPerShareDiluted",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ),
}

# --- Shared limits / validation ------------------------------------------

_VALID_STATEMENTS = ("balance", "income", "cashflow", "indicators")
_VALID_PERIODS = ("annual", "quarter")

# Defensive caps so a payload can never blow up the LLM context.
_MAX_PERIODS = 40
_MAX_FIELDS_PER_PERIOD = 200


def _error(message: str) -> str:
    """Build the failure envelope as a JSON string.

    Args:
        message: Human-readable error description.

    Returns:
        A ``{"ok": false, "error": ...}`` JSON string.
    """
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _truncate_period(record: dict[str, Any]) -> dict[str, Any]:
    """Cap one period's field count so a single record stays context-safe.

    Args:
        record: A flat period dict (field name -> value).

    Returns:
        A new dict with at most :data:`_MAX_FIELDS_PER_PERIOD` items, preserving
        insertion order. The original is never mutated.
    """
    items = list(record.items())
    if len(items) <= _MAX_FIELDS_PER_PERIOD:
        return dict(items)
    return dict(items[:_MAX_FIELDS_PER_PERIOD])


def _cap_periods(periods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cap each period's field count, keeping every period.

    The record count is no longer clipped here: ``execute`` pages whole periods
    against the result-size budget, so clipping at the parser would put the
    older history permanently out of reach of any ``offset``.

    Args:
        periods: Period records as returned by the provider parser.

    Returns:
        A new list of field-capped records, one per input period.
    """
    return [_truncate_period(record) for record in periods]


def _to_number(value: Any) -> float | None:
    """Coerce a numeric provider cell to float, preserving missing values."""
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_sec_unit(units: dict[str, Any]) -> tuple[str, list[Any]]:
    """Pick the SEC XBRL unit bucket with the most reported rows."""
    best_key = ""
    best_rows: list[Any] = []
    for key, rows in units.items():
        if isinstance(rows, list) and len(rows) >= len(best_rows):
            best_key, best_rows = str(key), rows
    return best_key, best_rows


def _sec_instant_matches(row: dict[str, Any], period: str) -> bool:
    """Return whether an instant (balance-sheet) fact belongs in the cadence.

    Instant facts carry no span, so their cadence can only be read off the
    filing they came from: a fiscal-year-end balance sheet is the one reported
    on a 10-K.

    Args:
        row: One SEC ``companyfacts`` unit row with no ``start``.
        period: ``"annual"`` or ``"quarter"``.

    Returns:
        ``True`` when the fact should be kept.
    """
    if period != "annual":
        return True
    fp = str(row.get("fp") or "").upper()
    form = str(row.get("form") or "").upper()
    return fp == "FY" or form == "10-K"


def _record_sec_fact(
    bucket: dict[tuple[Any, Any], dict[str, Any]],
    row: dict[str, Any],
    concept_name: str,
    value: float,
    unit_key: str,
) -> None:
    """Merge one fact into the period record identified by its ``(start, end)``.

    A period is filed once as the primary period and then repeated as a
    comparative in later filings, which may restate it. The earliest filing
    carries the correct fiscal label, the latest carries the current value, so
    both are kept and both dates are surfaced.

    Args:
        bucket: Period records keyed by :func:`sec_frames.frame_key`.
        row: One SEC ``companyfacts`` unit row.
        concept_name: The us-gaap concept this value belongs to.
        value: The parsed numeric value.
        unit_key: The unit bucket the value came from (e.g. ``"USD"``).
    """
    key = sec_frames.frame_key(row)
    filed = str(row.get("filed") or "")
    record = bucket.get(key)
    if record is None:
        days = sec_frames.span_days(row)
        record = bucket[key] = {
            "REPORT_DATE": row.get("end"),
            "PERIOD_START": row.get("start"),
            "PERIOD_DAYS": days,
            "PERIOD_TYPE": sec_frames.classify_span(days),
            "FISCAL_YEAR": row.get("fy"),
            "FISCAL_PERIOD": row.get("fp"),
            "FORM": row.get("form"),
            "ACCESSION": row.get("accn"),
            "FILED": filed or None,
            "LAST_FILED": filed or None,
            "_units": {},
            "_filed": {},
        }
    if filed and filed < (record["FILED"] or filed):
        record["FISCAL_YEAR"] = row.get("fy")
        record["FISCAL_PERIOD"] = row.get("fp")
        record["FORM"] = row.get("form")
        record["ACCESSION"] = row.get("accn")
        record["FILED"] = filed
    if filed > (record["LAST_FILED"] or ""):
        record["LAST_FILED"] = filed
    if filed >= record["_filed"].get(concept_name, ""):
        record["_filed"][concept_name] = filed
        record[concept_name] = value
        record["_units"][concept_name] = unit_key


def _synthesize_fiscal_q4(
    frames: dict[tuple[Any, Any], dict[str, Any]],
    annual_frames: dict[tuple[Any, Any], dict[str, Any]],
) -> None:
    """Derive fiscal Q4 rows, which issuers report only inside the 10-K.

    Flow concepts are never filed as a standalone Q4 duration frame, so without
    this the fourth quarter simply vanishes from a quarterly series. It is
    derived as ``FY - (Q1 + Q2 + Q3)``, the same way
    :mod:`backtest.loaders.fundamentals_loader` derives it for the PIT panel,
    and marked ``DERIVED`` so a computed figure is never mistaken for a filed
    one.

    Args:
        frames: True-quarter period records; synthesized rows are added here.
        annual_frames: Full-year period records used as the raw material.
    """
    quarter_ends = {
        record["REPORT_DATE"]
        for record in frames.values()
        if record["PERIOD_TYPE"] == sec_frames.QUARTER
    }
    for (start, end), annual in annual_frames.items():
        if not start or end in quarter_ends:
            continue
        inside = [
            record
            for record in frames.values()
            if record["PERIOD_TYPE"] == sec_frames.QUARTER
            and record["PERIOD_START"]
            and record["PERIOD_START"] >= start
            and record["REPORT_DATE"] < end
        ]
        if len(inside) != 3:
            continue
        values = {
            concept: annual[concept] - sum(quarter[concept] for quarter in inside)
            for concept in annual["_units"]
            if all(concept in quarter for quarter in inside)
        }
        if not values:
            continue
        q4_start = max(quarter["REPORT_DATE"] for quarter in inside)
        filed = max(
            [annual["FILED"] or ""] + [quarter["FILED"] or "" for quarter in inside]
        )
        record = {
            "REPORT_DATE": end,
            "PERIOD_START": q4_start,
            "PERIOD_DAYS": sec_frames.span_days({"start": q4_start, "end": end}),
            "PERIOD_TYPE": sec_frames.QUARTER,
            "FISCAL_YEAR": annual["FISCAL_YEAR"],
            "FISCAL_PERIOD": "Q4",
            "FORM": annual["FORM"],
            "ACCESSION": annual["ACCESSION"],
            "FILED": filed or None,
            "LAST_FILED": filed or None,
            "DERIVED": "FY - (Q1 + Q2 + Q3)",
            "_units": {concept: annual["_units"][concept] for concept in values},
            "_filed": {},
        }
        record.update(values)
        frames[(q4_start, end)] = record


def _merge_sec_instants(
    frames: dict[tuple[Any, Any], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fold instant facts into the duration period ending on the same day.

    ``indicators`` mixes balance-sheet concepts (instant) with income-statement
    concepts (duration); without merging, one reporting period would come back
    as two half-populated rows.

    Args:
        frames: All period records for the requested cadence.

    Returns:
        One record per reporting period.
    """
    durations = [
        record
        for record in frames.values()
        if record["PERIOD_TYPE"] != sec_frames.INSTANT
    ]
    instants = {
        record["REPORT_DATE"]: record
        for record in frames.values()
        if record["PERIOD_TYPE"] == sec_frames.INSTANT
    }
    if not durations:
        return list(instants.values())
    for record in durations:
        instant = instants.get(record["REPORT_DATE"])
        if instant is None:
            continue
        for concept, unit_key in instant["_units"].items():
            record.setdefault(concept, instant[concept])
            record["_units"].setdefault(concept, unit_key)
    covered = {record["REPORT_DATE"] for record in durations}
    return durations + [
        record for end, record in instants.items() if end not in covered
    ]


def _fetch_sec_statement(code: str, *, statement: str, period: str) -> dict[str, Any]:
    """Fetch one US statement from SEC companyfacts, shaped as flat periods.

    Args:
        code: US symbol with ``.US`` suffix, e.g. ``"AAPL.US"``.
        statement: One of :data:`_VALID_STATEMENTS`.
        period: ``"annual"`` or ``"quarter"``.

    Returns:
        ``{"periods": [...]}`` on success or ``{"error": ...}`` on failure.
    """
    ticker = code.rsplit(".", 1)[0].strip().upper()
    try:
        cik = cik_for(ticker)
    except Exception as exc:  # noqa: BLE001 - surface provider failures as envelope
        logger.warning("SEC ticker lookup failed for %s: %s", code, exc)
        return {"error": f"SEC ticker lookup failed: {exc}"}
    if not cik:
        return {"error": "ticker not found in SEC company table"}

    try:
        facts = get_company_facts(cik)
    except Exception as exc:  # noqa: BLE001 - one bad fetch must not kill the call
        logger.warning("SEC companyfacts fetch failed for %s: %s", code, exc)
        return {"error": f"SEC companyfacts request failed: {exc}"}

    gaap = (facts.get("facts") or {}).get("us-gaap") if isinstance(facts, dict) else None
    if not isinstance(gaap, dict):
        return {"periods": []}

    # Keyed on the ``(start, end)`` span, never on ``end`` alone: a 10-Q files
    # the true quarter and the year-to-date frame under the same end date, and
    # the same fy/fp/form/accn, so any narrower key silently lets one overwrite
    # the other.
    frames: dict[tuple[Any, Any], dict[str, Any]] = {}
    annual_frames: dict[tuple[Any, Any], dict[str, Any]] = {}
    for concept_name in _SEC_CONCEPTS[statement]:
        concept = gaap.get(concept_name)
        units = concept.get("units") if isinstance(concept, dict) else None
        if not isinstance(units, dict):
            continue
        unit_key, rows = _pick_sec_unit(units)
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = _to_number(row.get("val"))
            if not row.get("end") or value is None:
                continue
            kind = sec_frames.classify_span(sec_frames.span_days(row))
            if kind == sec_frames.YTD:
                continue
            if kind == sec_frames.INSTANT:
                if not _sec_instant_matches(row, period):
                    continue
                bucket = frames
            elif kind == sec_frames.ANNUAL:
                # A full year is the annual cadence, and the raw material for a
                # synthesized fiscal Q4 when the cadence is quarterly.
                bucket = frames if period == "annual" else annual_frames
            else:
                if period == "annual":
                    continue
                bucket = frames
            _record_sec_fact(bucket, row, concept_name, value, unit_key)

    if period == "quarter":
        _synthesize_fiscal_q4(frames, annual_frames)

    periods = sorted(
        _merge_sec_instants(frames),
        key=lambda row: str(row.get("REPORT_DATE") or ""),
        reverse=True,
    )
    for record in periods:
        record.pop("_filed", None)
    return {"periods": _cap_periods(periods)}


def _classify_market(code: str) -> str | None:
    """Classify a symbol's suffix into ``us`` or ``None``.

    Args:
        code: Symbol with a market suffix (e.g. ``"AAPL.US"``).

    Returns:
        ``"us"``, or ``None`` when the suffix is unrecognized.
    """
    suffix = code.rpartition(".")[2].strip().upper()
    if suffix == "US":
        return "us"
    return None


class FinancialStatementsTool(BaseTool):
    """Fetch a stock's three financial statements or key per-period indicators."""

    name = "get_financial_statements"
    description = (
        "Fetch a single stock's financial statements: balance sheet, income "
        "statement, cash-flow statement, or key per-period indicators (margins, "
        "ROE, EPS, etc.). US equities only (.US), sourced from SEC EDGAR "
        "companyfacts. Reports come back newest-first as flat per-period rows. Use "
        'this to read fundamentals before building a valuation or screen. Example: '
        '{"code": "AAPL.US", "statement": "income", "period": "annual"}.'
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Single US symbol with a market suffix, e.g. 'AAPL.US'.",
            },
            "statement": {
                "type": "string",
                "enum": list(_VALID_STATEMENTS),
                "description": (
                    "Which report to fetch: 'balance' (balance sheet), 'income' "
                    "(income statement), 'cashflow' (cash-flow statement), or "
                    "'indicators' (key per-period indicators)."
                ),
                "default": "indicators",
            },
            "period": {
                "type": "string",
                "enum": list(_VALID_PERIODS),
                "description": (
                    "Reporting cadence: 'annual' (annual reports) or 'quarter' "
                    "(quarterly reports)."
                ),
                "default": "annual",
            },
            "offset": {
                "type": "integer",
                "description": (
                    "Index of the first period to return, newest first; "
                    "defaults to 0. Periods are returned whole and only as many "
                    "as fit one result — read paging.total and paging.next_offset "
                    "in the response and call again to continue."
                ),
            },
        },
        "required": ["code"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Validate inputs, fetch the statement, and return a JSON envelope.

        Args:
            **kwargs: ``code`` (str, required), ``statement`` (one of balance|
                income|cashflow|indicators, default 'indicators'), ``period``
                (annual|quarter, default 'annual'), ``offset`` (int, default 0).

        Returns:
            A JSON string ``{"ok": true, "market": str, "source": str,
            "statement": str, "period": str, "data": {...}}`` when the fetch
            yields data, ``{"ok": false, "error": ...}`` when validation fails,
            or the same envelope with ``ok: false`` plus a top-level ``error``
            when the fetch failed (so a nested fetch error is never masked by a
            top-level ``ok: true``).
        """
        code = kwargs.get("code")
        if not isinstance(code, str) or not code.strip():
            return _error("code must be a non-empty symbol string")
        code = code.strip()

        statement = kwargs.get("statement", "indicators")
        if statement not in _VALID_STATEMENTS:
            return _error(f"statement must be one of {list(_VALID_STATEMENTS)}")

        period = kwargs.get("period", "annual")
        if period not in _VALID_PERIODS:
            return _error(f"period must be one of {list(_VALID_PERIODS)}")

        market = _classify_market(code)
        if market is None:
            return _error("code must carry a supported suffix: .US")

        # Validated before the fetch: a malformed offset must not burn a live
        # SEC request, and must not be masked by a fetch error.
        try:
            offset = max(int(kwargs.get("offset") or 0), 0)
        except (TypeError, ValueError):
            return _error("offset must be an integer")

        result = _fetch_sec_statement(code, statement=statement, period=period)
        source = "sec_edgar"

        # The fetch failed iff its result carries an ``error``. Surface that as a
        # top-level ``ok: false`` so a nested failure is never masked by
        # ``ok: true``.
        if "error" in result:
            return json.dumps(
                {
                    "ok": False,
                    "market": market,
                    "source": source,
                    "statement": statement,
                    "period": period,
                    "data": {code: result},
                    "error": result["error"],
                },
                ensure_ascii=False,
            )

        # Page whole periods. A raw character cut lands mid-record, and the
        # model reads the periods that survived as the issuer's full history.
        periods = result.get("periods") or []

        def _build(page: list[dict[str, Any]], paging: dict[str, Any]) -> dict[str, Any]:
            return {
                "ok": True,
                "market": market,
                "source": source,
                "statement": statement,
                "period": period,
                "paging": paging,
                "data": {code: dict(result, periods=page)},
            }

        return fit_records(periods, offset, _build, max_records=_MAX_PERIODS)
