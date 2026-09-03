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


# ── Message compaction (remediation #1) ────────────────────────────────────────
# _compact_messages is a pure function over a message list — no Mongo needed,
# consistent with this file's existing "pure functions, no Mongo" scope.

def _msgs(*specs: tuple[str, str]) -> list[object]:
    """Build a message list from (kind, name_or_content) pairs.

    kind is "human" (content only) or any agent/supervisor name (content is
    auto-generated from an incrementing counter unless a third element is
    supplied via _named).
    """
    from langchain_core.messages import AIMessage, HumanMessage

    out: list[object] = []
    for i, (kind, content) in enumerate(specs):
        if kind == "human":
            out.append(HumanMessage(content=content, id=f"h{i}"))
        else:
            out.append(AIMessage(content=content, name=kind, id=f"m{i}"))
    return out


def test_compact_keeps_only_latest_message_per_agent_name() -> None:
    from src.domains.intelligence.agents.hub_writer import _compact_messages

    messages = _msgs(
        ("human", "start"),
        ("d_forecaster", "first pass"),
        ("supervisor", "route to d_forecaster again"),
        ("d_forecaster", "second pass"),
        ("supervisor", "route to d_forecaster again"),
        ("d_forecaster", "third pass"),
    )
    updates = _compact_messages(messages)

    from langchain_core.messages import RemoveMessage
    removed_ids = {u.id for u in updates if isinstance(u, RemoveMessage)}
    # The two earlier d_forecaster messages are removed; the latest survives
    # untouched (no truncation needed, no RemoveMessage/replacement for it).
    assert removed_ids == {"m1", "m3"}
    assert not any(isinstance(u, RemoveMessage) and u.id == "m5" for u in updates)


def test_compact_never_touches_human_or_supervisor_messages() -> None:
    from src.domains.intelligence.agents.hub_writer import _compact_messages

    messages = _msgs(
        ("human", "q1"),
        ("human", "q2"),
        ("supervisor", "route a"),
        ("supervisor", "route b"),
        ("f_auditor", "out"),
    )
    updates = _compact_messages(messages)
    removed_ids = {u.id for u in updates}
    assert removed_ids.isdisjoint({"h0", "h1", "m2", "m3"})


def test_compact_preserves_agent_name_set_for_cycle_guard() -> None:
    """Compaction must never shrink the *set* of agent names the supervisor's
    cycle guard (_progress_signature/_agent_has_run) keys off — only redundant
    repeat-visits are pruned, so applying the updates can't change that set."""
    from langgraph.graph.message import add_messages

    from src.domains.intelligence.agents.hub_writer import _compact_messages
    from src.domains.intelligence.agents.supervisor import (
        _agent_has_run,
        _progress_signature,
    )

    messages = _msgs(
        ("human", "start"),
        ("d_forecaster", "v1"),
        ("d_forecaster", "v2"),
        ("k_stockkeeper", "v1"),
    )
    before_sig = _progress_signature(messages, {})
    updates = _compact_messages(messages)
    after = add_messages(messages, updates)
    after_sig = _progress_signature(after, {})

    assert before_sig == after_sig
    assert _agent_has_run(after, "d_forecaster")
    assert _agent_has_run(after, "k_stockkeeper")
    assert len(after) < len(messages)  # the redundant d_forecaster copy is gone


def test_compact_truncates_long_surviving_content() -> None:
    from src.domains.intelligence.agents.hub_writer import (
        _COMPACT_CONTENT_CHARS,
        _compact_messages,
    )

    long_content = "x" * (_COMPACT_CONTENT_CHARS + 500)
    messages = _msgs(("human", "start"), ("g_reporter", long_content))
    updates = _compact_messages(messages)

    assert len(updates) == 1
    replacement = updates[0]
    assert replacement.id == "m1"
    assert len(replacement.content) <= _COMPACT_CONTENT_CHARS + len("…[compacted]")
    assert replacement.content.endswith("…[compacted]")


@pytest.mark.asyncio
async def test_hub_writer_node_only_compacts_past_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Below _COMPACT_THRESHOLD, the node's messages update is absent entirely —
    the common short/fast-pathed flow is byte-for-byte unchanged."""
    from src.domains.intelligence.agents import hub_writer as hw

    monkeypatch.setattr(hw, "get_mongo_db", lambda: None)
    node = hw.make_hub_writer_node()

    short_messages = _msgs(("human", "start"), ("d_forecaster", "out"))
    state = {
        "messages": short_messages, "context": {}, "gen_ui_payloads": [],
        "session_id": "s1",
    }
    result = await node(state)
    assert "messages" not in result


# ── Step registry — the post-step hook point (Phase 1) ────────────────────────

@pytest.mark.asyncio
async def test_registering_a_fourth_step_does_not_touch_the_built_in_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new cross-cutting concern attaches as one more entry in
    HUB_WRITER_STEPS — proving the extension point works without editing
    _compaction_step / _genui_step / _insight_step."""
    from src.domains.intelligence.agents import hub_writer as hw

    async def fake_step(ctx: hw._StepContext) -> hw.HubWriterStepResult:
        return hw.HubWriterStepResult(
            context={"custom_marker": ctx.session_id},
            handoffs=[{"agent_id": "Z", "status": "ok"}],
        )

    monkeypatch.setattr(hw, "get_mongo_db", lambda: None)
    monkeypatch.setattr(hw, "HUB_WRITER_STEPS", [*hw.HUB_WRITER_STEPS, fake_step])

    node = hw.make_hub_writer_node()
    state = {
        "messages": _msgs(("human", "start")),
        "context": {}, "gen_ui_payloads": [], "session_id": "s-ext",
    }
    result = await node(state)

    assert result["context"]["custom_marker"] == "s-ext"
    assert result["handoffs"] == [{"agent_id": "Z", "status": "ok"}]


@pytest.mark.asyncio
async def test_step_context_is_shared_read_only_not_chained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Steps read only from the shared _StepContext, never from a prior
    step's HubWriterStepResult — so step order among independent steps
    cannot change the outcome for unrelated keys."""
    from src.domains.intelligence.agents import hub_writer as hw

    monkeypatch.setattr(hw, "get_mongo_db", lambda: None)

    seen_contexts: list[dict[str, object]] = []

    async def spy_step(ctx: hw._StepContext) -> hw.HubWriterStepResult:
        seen_contexts.append(dict(ctx.state["context"]))
        return hw.HubWriterStepResult()

    monkeypatch.setattr(hw, "HUB_WRITER_STEPS", [*hw.HUB_WRITER_STEPS, spy_step])
    node = hw.make_hub_writer_node()
    state = {
        "messages": [], "context": {"advice": "buy low"},
        "gen_ui_payloads": [], "session_id": "s2",
    }
    await node(state)

    # spy_step saw the ORIGINAL state context, not anything the built-in
    # steps (which ran before it) added to updated_context.
    assert seen_contexts == [{"advice": "buy low"}]
