"""Unit tests for the hub_writer pure helpers (TTL policy + artifact extraction).

``_ttl_delta`` and ``_extract_payload_and_intent`` decide how every agent's
output is persisted to ``intelligence_hub`` — pure functions over the context
dict, no Mongo needed.
"""
from __future__ import annotations

from datetime import timedelta

from src.domains.intelligence.agents.hub_writer import (
    _extract_payload_and_intent,
    _ttl_delta,
)


def test_ttl_minutes_agents() -> None:
    assert _ttl_delta("C") == timedelta(minutes=10)
    assert _ttl_delta("E") == timedelta(minutes=30)
    assert _ttl_delta("J") == timedelta(minutes=30)   # minutes dict wins over hours


def test_ttl_hour_agents() -> None:
    assert _ttl_delta("A") == timedelta(hours=1)
    assert _ttl_delta("F") == timedelta(hours=24)
    assert _ttl_delta("G") == timedelta(hours=24)


def test_ttl_unknown_agent_defaults_to_one_hour() -> None:
    assert _ttl_delta("ZZ") == timedelta(hours=1)


def test_extract_none_when_no_recognised_output() -> None:
    assert _extract_payload_and_intent({}) is None
    assert _extract_payload_and_intent({"unrelated": 1}) is None


def test_extract_executive_summary_string_wrapped() -> None:
    agent, intent, payload = _extract_payload_and_intent({"executive_summary": "all good"})
    assert (agent, intent) == ("J", "EXECUTIVE_SUMMARY")
    assert payload == {"summary": "all good"}


def test_extract_summary_takes_priority_over_others() -> None:
    # J is checked first — a context carrying both still resolves to the summary.
    agent, _, _ = _extract_payload_and_intent(
        {"executive_summary": {"k": 1}, "advice": {"x": 2}}
    )
    assert agent == "J"


def test_extract_invoice_and_classification() -> None:
    a_agent, a_intent, a_payload = _extract_payload_and_intent(
        {"extracted_invoice": {"total": 100}}
    )
    assert (a_agent, a_intent, a_payload) == ("A", "GENERATE_INVOICE", {"total": 100})

    b_agent, b_intent, _ = _extract_payload_and_intent(
        {"classified_transactions": [{"id": "1"}]}
    )
    assert (b_agent, b_intent) == ("B", "CLASSIFY_TRANSACTIONS")


def test_extract_reporter_merges_export_blobs() -> None:
    agent, intent, payload = _extract_payload_and_intent(
        {
            "credit_strategy_result": {"score": 80},
            "credit_report_pdf_b64": "PDF==",
            "credit_forecast_xlsx_b64": "XLSX==",
        }
    )
    assert (agent, intent) == ("G", "REPORT_GENERATION")
    assert payload["pdf_export_b64"] == "PDF==" and payload["xlsx_export_b64"] == "XLSX=="
