"""Tests for financial_statements_tool: envelope shape, dispatch, isolation.

All HTTP is mocked at the functions the tool imports. US requests route through
SEC EDGAR ``cik_for`` / ``get_company_facts``. No test touches a live endpoint.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from src.tools.financial_statements_tool import FinancialStatementsTool

_SEC_FACTS = {
    "facts": {
        "us-gaap": {
            "Revenues": {
                "label": "Revenues",
                "units": {
                    "USD": [
                        {
                            "end": "2023-09-30",
                            "val": 383285000000,
                            "fy": 2023,
                            "fp": "FY",
                            "form": "10-K",
                            "accn": "a1",
                        },
                        {
                            "end": "2024-09-28",
                            "val": 391035000000,
                            "fy": 2024,
                            "fp": "FY",
                            "form": "10-K",
                            "accn": "a2",
                        },
                    ]
                },
            },
            "NetIncomeLoss": {
                "label": "Net Income",
                "units": {
                    "USD": [
                        {
                            "end": "2024-06-29",
                            "val": 21448000000,
                            "fy": 2024,
                            "fp": "Q3",
                            "form": "10-Q",
                            "accn": "q3",
                        },
                        {
                            "end": "2024-09-28",
                            "val": 93736000000,
                            "fy": 2024,
                            "fp": "FY",
                            "form": "10-K",
                            "accn": "a2",
                        },
                    ]
                },
            },
            "Assets": {
                "label": "Assets",
                "units": {
                    "USD": [
                        {
                            "end": "2024-09-28",
                            "val": 364980000000,
                            "fy": 2024,
                            "fp": "FY",
                            "form": "10-K",
                            "accn": "a2",
                        },
                    ]
                },
            },
        }
    }
}


class TestSuccessEnvelope:
    """A resolvable symbol yields the ok envelope with parsed periods."""

    def test_us_uses_sec_companyfacts(self):
        with patch(
            "src.tools.financial_statements_tool.cik_for",
            return_value="0000320193",
        ) as mock_cik, patch(
            "src.tools.financial_statements_tool.get_company_facts",
            return_value=_SEC_FACTS,
        ) as mock_facts:
            text = FinancialStatementsTool().execute(
                code="AAPL.US", statement="income", period="annual"
            )

        mock_cik.assert_called_once_with("AAPL")
        mock_facts.assert_called_once_with("0000320193")

        payload = json.loads(text)
        assert payload["ok"] is True
        assert payload["market"] == "us"
        assert payload["source"] == "sec_edgar"

        periods = payload["data"]["AAPL.US"]["periods"]
        assert periods[0]["REPORT_DATE"] == "2024-09-28"
        assert periods[0]["FORM"] == "10-K"
        assert periods[0]["Revenues"] == 391035000000.0
        assert periods[0]["NetIncomeLoss"] == 93736000000.0
        assert periods[0]["_units"] == {
            "Revenues": "USD",
            "NetIncomeLoss": "USD",
        }

    def test_us_quarter_keeps_10q_points(self):
        with patch(
            "src.tools.financial_statements_tool.cik_for",
            return_value="0000320193",
        ), patch(
            "src.tools.financial_statements_tool.get_company_facts",
            return_value=_SEC_FACTS,
        ):
            text = FinancialStatementsTool().execute(
                code="AAPL.US", statement="income", period="quarter"
            )

        payload = json.loads(text)
        periods = payload["data"]["AAPL.US"]["periods"]
        dates = [row["REPORT_DATE"] for row in periods]
        assert "2024-06-29" in dates
        q3 = next(row for row in periods if row["REPORT_DATE"] == "2024-06-29")
        assert q3["FORM"] == "10-Q"
        assert q3["NetIncomeLoss"] == 21448000000.0


class TestAllFailedSurfacesError:
    """When the fetch fails, the envelope is ok=false.

    The failure detail stays in the per-code result AND is mirrored to a
    top-level ``error`` so a nested fetch failure is never masked by a
    top-level ``ok: true``.
    """

    def test_sec_failure_yields_top_level_ok_false(self):
        with patch(
            "src.tools.financial_statements_tool.cik_for",
            return_value="0000320193",
        ), patch(
            "src.tools.financial_statements_tool.get_company_facts",
            side_effect=RuntimeError("HTTP 429"),
        ):
            text = FinancialStatementsTool().execute(
                code="AAPL.US", statement="income"
            )

        payload = json.loads(text)
        assert payload["ok"] is False
        assert "429" in payload["error"]
        assert "429" in payload["data"]["AAPL.US"]["error"]

    def test_unresolvable_us_symbol_yields_ok_false(self):
        with patch(
            "src.tools.financial_statements_tool.cik_for",
            return_value=None,
        ):
            text = FinancialStatementsTool().execute(code="ZZZZ.US")

        payload = json.loads(text)
        assert payload["ok"] is False
        assert payload["error"] == "ticker not found in SEC company table"
        assert payload["data"]["ZZZZ.US"]["error"] == "ticker not found in SEC company table"

    def test_empty_sec_payload_yields_no_periods_but_ok_true(self):
        # An empty-but-well-formed payload is data (zero periods), not a fetch
        # failure, so the envelope stays ok=true.
        with patch(
            "src.tools.financial_statements_tool.cik_for",
            return_value="0000000001",
        ), patch(
            "src.tools.financial_statements_tool.get_company_facts",
            return_value={"facts": {}},
        ):
            text = FinancialStatementsTool().execute(code="ZZZZ.US")

        payload = json.loads(text)
        assert payload["ok"] is True
        assert "error" not in payload
        assert payload["data"]["ZZZZ.US"]["periods"] == []


class TestErrorEnvelope:
    """Input validation returns the ok=false envelope before any HTTP."""

    def test_missing_code_rejected(self):
        payload = json.loads(FinancialStatementsTool().execute())
        assert payload["ok"] is False
        assert "code" in payload["error"]

    def test_blank_code_rejected(self):
        payload = json.loads(FinancialStatementsTool().execute(code="   "))
        assert payload["ok"] is False

    def test_unknown_suffix_rejected(self):
        payload = json.loads(FinancialStatementsTool().execute(code="BTC-USDT"))
        assert payload["ok"] is False
        assert "suffix" in payload["error"]

    def test_non_us_suffix_rejected(self):
        # Phase 5 removed every non-US statement path, so a Hong Kong code that
        # the Eastmoney branch used to serve is refused before any fetch.
        payload = json.loads(FinancialStatementsTool().execute(code="00700.HK"))
        assert payload["ok"] is False
        assert payload["error"] == "code must carry a supported suffix: .US"

    def test_invalid_statement_rejected(self):
        payload = json.loads(
            FinancialStatementsTool().execute(code="AAPL.US", statement="equity")
        )
        assert payload["ok"] is False
        assert "statement" in payload["error"]

    def test_invalid_period_rejected(self):
        payload = json.loads(
            FinancialStatementsTool().execute(code="AAPL.US", period="ttm")
        )
        assert payload["ok"] is False
        assert "period" in payload["error"]
