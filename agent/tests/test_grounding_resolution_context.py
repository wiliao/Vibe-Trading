"""Context-aware identity resolution without rewriting the user request.

The surviving markets are US and Canada, so the dual-listing scenarios here use
issuers that really do trade on both (Ballard Power, Shopify) instead of the
removed A-share / Hong Kong pair.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.agent.grounding import GroundingLedger


def _resolver_payload(query: str, candidates: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "ok": True,
            "source": "symbol_search",
            "data": {
                "query": query,
                "candidates": candidates,
                "sources": {"yahoo": "ok", "stooq": "ok"},
            },
        },
        ensure_ascii=False,
    )


def _ballard_candidates() -> list[dict[str, Any]]:
    return [
        {
            "symbol": "BLDP.US",
            "name": "Ballard Power",
            "market": "us",
            "source": "yahoo",
        },
        {
            "symbol": "BLDP.TO",
            "name": "Ballard Power",
            "market": "ca",
            "source": "yahoo",
        },
    ]


def _shopify_candidates() -> list[dict[str, Any]]:
    return [
        {
            "symbol": "SHOP.US",
            "name": "Shopify",
            "market": "us",
            "source": "yahoo",
        },
        {
            "symbol": "SHOP.TO",
            "name": "Shopify",
            "market": "ca",
            "source": "yahoo",
        },
    ]


def _ingest(
    ledger: GroundingLedger,
    query: str,
    candidates: list[dict[str, Any]],
    call_id: str = "resolve",
) -> None:
    ledger.ingest_tool_result(
        tool_name="search_symbol",
        arguments={"query": query},
        result=_resolver_payload(query, candidates),
        call_id=call_id,
        success=True,
    )


def test_explicit_canada_context_locks_the_canada_candidate(tmp_path: Path) -> None:
    message = "请分析加股BLDP的最新财务情况"
    ledger = GroundingLedger(run_dir=tmp_path, user_message=message)

    _ingest(ledger, "BLDP", _ballard_candidates())

    assert ledger.resolution_context.raw_user_message == message
    assert ledger.authorized_symbols == {"BLDP.TO"}
    record = ledger.identity_summary()["records"][0]
    assert record["status"] == "locked"
    assert record["resolution_constraints"] == [
        {
            "dimension": "market",
            "value": "ca",
            "source_message_id": "current_user_message",
            "source_span": [3, 5],
            "explicit": True,
        }
    ]
    assert message not in json.dumps(record, ensure_ascii=False)
    artifact = (tmp_path / "artifacts" / "grounding_evidence.json").read_text()
    assert message not in artifact


def test_explicit_us_canada_comparison_keeps_both_candidates(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="比较BLDP 美股/加股 两地上市表现",
    )

    _ingest(ledger, "BLDP", _ballard_candidates())

    assert ledger.identity_status == "ambiguous"
    assert ledger.authorized_symbols == set()
    constraints = ledger.identity_summary()["records"][0]["resolution_constraints"]
    assert {item["value"] for item in constraints} == {"us", "ca"}


def test_no_explicit_market_remains_fail_closed(tmp_path: Path) -> None:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="分析BLDP")

    _ingest(ledger, "BLDP", _ballard_candidates())

    assert ledger.identity_status == "ambiguous"
    assert ledger.authorized_symbols == set()


def test_explicit_us_market_in_english_locks_the_us_candidate(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="Analyze the US stock ABC",
    )
    candidates = [
        {"symbol": "ABC.US", "name": "ABC", "market": "us", "source": "yahoo"},
        {
            "symbol": "ABC.TO",
            "name": "ABC",
            "market": "ca",
            "source": "yahoo",
        },
    ]

    _ingest(ledger, "ABC", candidates)

    assert ledger.authorized_symbols == {"ABC.US"}


def test_negated_market_is_not_used_as_positive_authorization(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="不要看加股BLDP",
    )

    _ingest(ledger, "BLDP", _ballard_candidates())

    assert ledger.identity_status == "ambiguous"
    assert ledger.authorized_symbols == set()


def test_constraint_mismatch_stays_fail_closed(tmp_path: Path) -> None:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="只看加股BLDP")

    _ingest(ledger, "BLDP", [_ballard_candidates()[0]])

    assert ledger.identity_status == "ambiguous"
    assert ledger.authorized_symbols == set()


def test_one_ambiguous_entity_does_not_retract_another_lock(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="加股BLDP；比较 SHOP 美股/加股",
    )

    _ingest(ledger, "BLDP", _ballard_candidates(), "ballard")
    _ingest(ledger, "SHOP", _shopify_candidates(), "shopify")

    assert ledger.authorized_symbols == {"BLDP.TO"}
    assert (
        ledger.authorize_tool_call(
            "get_market_data",
            {"codes": ["BLDP.TO"]},
            batch_authorized_symbols=ledger.authorized_symbols,
            batch_identity_status=ledger.identity_status,
            call_id="prices",
        ).allowed
        is True
    )


def test_market_constraints_stay_attached_to_their_named_clause(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="我的持仓包括加股BLDP，美股SHOP",
    )

    _ingest(ledger, "BLDP", _ballard_candidates(), "ballard")
    _ingest(ledger, "SHOP", _shopify_candidates(), "shopify")

    assert ledger.authorized_symbols == {"BLDP.TO", "SHOP.US"}


def test_current_follow_up_constraint_applies_to_prior_subjects(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="都只看 加股",
        history=[
            {"role": "user", "content": "比较BLDP和SHOP"},
            {"role": "assistant", "content": "你希望看哪个市场？"},
        ],
    )

    _ingest(ledger, "BLDP", _ballard_candidates(), "ballard")
    _ingest(ledger, "SHOP", _shopify_candidates(), "shopify")

    assert ledger.authorized_symbols == {"BLDP.TO", "SHOP.TO"}


def test_named_constraint_overrides_current_global_constraint(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="都只看加股，SHOP看美股",
    )

    _ingest(ledger, "SHOP", _shopify_candidates())

    assert ledger.authorized_symbols == {"SHOP.US"}


def test_stale_global_history_does_not_authorize_a_new_turn(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="分析BLDP",
        history=[{"role": "user", "content": "都只看加股"}],
    )

    _ingest(ledger, "BLDP", _ballard_candidates())

    assert ledger.identity_status == "ambiguous"
    assert ledger.authorized_symbols == set()


def test_named_history_constraint_can_follow_its_subject(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="继续分析",
        history=[{"role": "user", "content": "只看加股BLDP"}],
    )

    _ingest(ledger, "BLDP", _ballard_candidates())

    assert ledger.authorized_symbols == {"BLDP.TO"}


def test_latest_named_history_constraint_wins(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="继续分析BLDP",
        history=[
            {"role": "user", "content": "只看美股BLDP"},
            {"role": "assistant", "content": "好的"},
            {"role": "user", "content": "改为加股BLDP"},
        ],
    )

    _ingest(ledger, "BLDP", _ballard_candidates())

    assert ledger.authorized_symbols == {"BLDP.TO"}


def test_current_reset_discards_history_constraints(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="忽略之前的市场限制，分析BLDP",
        history=[{"role": "user", "content": "只看加股BLDP"}],
    )

    _ingest(ledger, "BLDP", _ballard_candidates())

    assert ledger.identity_status == "ambiguous"
    assert ledger.authorized_symbols == set()


def test_feature_flag_can_restore_previous_resolution_behavior(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="只看加股BLDP",
        contextual_identity_constraints=False,
    )

    _ingest(ledger, "BLDP", _ballard_candidates())

    assert ledger.identity_status == "ambiguous"
    assert ledger.authorized_symbols == set()
