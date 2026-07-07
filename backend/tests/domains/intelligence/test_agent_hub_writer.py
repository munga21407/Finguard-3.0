"""Unit tests for the agent registry that drives hub_writer + Agent J.

``resolve_artifacts`` / ``ttl_for`` / ``executive_summary_keys`` decide how every
agent's output is persisted to ``intelligence_hub`` and summarised by Agent J —
pure functions over the context dict, no Mongo needed.

Includes the Sprint-2 contract test: adding one registry entry surfaces the new
agent in both hub_writer and Agent J with **zero edits** to their source.
"""
from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest

from src.domains.intelligence import agent_registry
from src.domains.intelligence.agent_registry import (
    AGENT_REGISTRY,
    AgentDescriptor,
    executive_summary_keys,
    resolve_artifacts,
    ttl_for,
)
from src.domains.intelligence.agents import j_summarizer

# ── TTL policy ────────────────────────────────────────────────────────────────

def test_ttl_minutes_agents() -> None:
    assert ttl_for("C") == timedelta(minutes=10)
    assert ttl_for("E") == timedelta(minutes=30)
    assert ttl_for("J") == timedelta(minutes=30)


def test_ttl_hour_agents() -> None:
    assert ttl_for("A") == timedelta(hours=1)
    assert ttl_for("F") == timedelta(hours=24)
    assert ttl_for("G") == timedelta(hours=24)


def test_ttl_unknown_agent_defaults_to_one_hour() -> None:
    assert ttl_for("ZZ") == timedelta(hours=1)


# ── Artifact resolution ───────────────────────────────────────────────────────

def test_resolve_none_when_no_recognised_output() -> None:
    assert resolve_artifacts({}) == []
    assert resolve_artifacts({"unrelated": 1}) == []


def test_resolve_executive_summary_string_wrapped() -> None:
    (art,) = resolve_artifacts({"executive_summary": "all good"})
    assert (art.agent_id, art.intent) == ("J", "EXECUTIVE_SUMMARY")
    assert art.payload == {"summary": "all good"}


def test_resolve_orders_by_priority_and_persists_all() -> None:
    # Persist-all: both present outputs are returned; J (highest priority) first.
    arts = resolve_artifacts({"executive_summary": {"k": 1}, "advice": {"x": 2}})
    assert arts[0].agent_id == "J"
    assert {a.agent_id for a in arts} == {"J", "H"}


def test_resolve_invoice_and_classification() -> None:
    (a,) = resolve_artifacts({"extracted_invoice": {"total": 100}})
    assert (a.agent_id, a.intent, a.payload) == ("A", "GENERATE_INVOICE", {"total": 100})

    (b,) = resolve_artifacts({"classified_transactions": [{"id": "1"}]})
    assert (b.agent_id, b.intent) == ("B", "CLASSIFY_TRANSACTIONS")
    assert b.payload == {"classifications": [{"id": "1"}]}   # list wrapped into a dict


def test_resolve_reporter_merges_export_blobs() -> None:
    (g,) = resolve_artifacts(
        {
            "credit_strategy_result": {"score": 80},
            "credit_report_pdf_b64": "PDF==",
            "credit_forecast_xlsx_b64": "XLSX==",
        }
    )
    assert (g.agent_id, g.intent) == ("G", "REPORT_GENERATION")
    assert g.payload["pdf_export_b64"] == "PDF==" and g.payload["xlsx_export_b64"] == "XLSX=="


def test_executive_summary_keys_order_matches_registry() -> None:
    keys = executive_summary_keys()
    assert keys[0] == "advice"                 # summary_order 0
    assert "executive_summary" not in keys     # J excludes its own output
    assert set(keys) == {
        d.context_key for d in AGENT_REGISTRY if d.in_executive_summary
    }


# ── Sprint-2 contract: one registry entry, zero edits elsewhere ───────────────

def test_new_agent_surfaces_via_registry_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Registering a dummy agent surfaces it in both hub_writer resolution and
    Agent J's section collection without touching either module's source."""
    dummy = AgentDescriptor(
        agent_id="Z", context_key="dummy_output", intent="DUMMY_INTENT",
        ttl=timedelta(minutes=7), priority=99, summary_order=99,
    )
    patched = (*AGENT_REGISTRY, dummy)
    monkeypatch.setattr(agent_registry, "AGENT_REGISTRY", patched)
    monkeypatch.setattr(
        agent_registry, "_BY_AGENT", {d.agent_id: d for d in patched}
    )

    # hub_writer side (resolve_artifacts reads AGENT_REGISTRY directly).
    (art,) = resolve_artifacts({"dummy_output": {"n": 1}})
    assert (art.agent_id, art.intent, art.ttl) == ("Z", "DUMMY_INTENT", timedelta(minutes=7))
    assert ttl_for("Z") == timedelta(minutes=7)

    # Agent J side (_collect_sections calls executive_summary_keys() at runtime).
    sections = j_summarizer._collect_sections({"dummy_output": {"n": 1}})
    assert "dummy_output" in sections


def test_registry_descriptor_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        AGENT_REGISTRY[0].agent_id = "X"  # type: ignore[misc]
