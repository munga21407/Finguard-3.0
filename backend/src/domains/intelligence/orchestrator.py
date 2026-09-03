"""
Main LangGraph StateGraph — Supervisor / ReAct loop.

Topology:
  [START] → supervisor ──┐
     ↑                   │ conditional edge (state["next"])
     └── hub_writer ◄────┘ ← any agent routes here first
          ↑
       any agent
     ↓ when next == "FINISH"
   [END]

Every agent node routes unconditionally through hub_writer (MongoDB upsert)
before returning control to the supervisor.  The supervisor decides whether
to invoke another agent or terminate.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.errors import (
    GraphRecursionError as GraphRecursionError,  # explicit re-export for callers
)
from langgraph.graph import END, START, StateGraph

from src.core.config import settings
from src.domains.intelligence.agent_registry import read_only_route
from src.domains.intelligence.agents.a_generator import make_a_generator_node
from src.domains.intelligence.agents.b_classifier import make_b_classifier_node
from src.domains.intelligence.agents.c_reconciler import make_c_reconciler_node
from src.domains.intelligence.agents.d_forecaster import make_d_forecaster_node
from src.domains.intelligence.agents.e_watchdog import make_e_watchdog_node
from src.domains.intelligence.agents.f_auditor import make_f_auditor_node
from src.domains.intelligence.agents.g_reporter import make_g_reporter_node
from src.domains.intelligence.agents.h_advisor import make_h_advisor_node
from src.domains.intelligence.agents.hub_writer import make_hub_writer_node
from src.domains.intelligence.agents.i_integrator import make_i_integrator_node
from src.domains.intelligence.agents.j_summarizer import make_j_summarizer_node
from src.domains.intelligence.agents.k_stockkeeper import make_k_stockkeeper_node
from src.domains.intelligence.agents.planner import (
    after_hub_writer,
    make_planner_node,
    planner_dispatch,
)
from src.domains.intelligence.agents.receipt_scanner import (
    make_receipt_classifier_node,
    make_receipt_ocr_node,
)
from src.domains.intelligence.agents.supervisor import make_supervisor_node
from src.domains.intelligence.llm_client import agent_context
from src.domains.intelligence.schemas import OrchestratorState
from src.infrastructure.database.checkpointer import get_checkpointer


def _tracked(name: str, node: Any) -> Any:
    """Wrap a graph node so every LLM call inside it attributes to ``name``.

    Sets the ``current_agent_id`` contextvar for the node's execution, which the
    the model client reads to label per-agent latency/token/cost metrics — central
    attribution with no per-agent edits.  Pure pass-through for non-LLM nodes.
    """

    async def _wrapped(state: Any) -> Any:
        with agent_context(name):
            return await node(state)

    return _wrapped


# Mapping from state["next"] value → graph node name
AGENT_NODE_MAP: dict[str, str] = {
    "a_generator": "a_generator",
    "b_classifier": "b_classifier",
    "c_reconciler": "c_reconciler",
    "d_forecaster": "d_forecaster",
    "e_watchdog":   "e_watchdog",
    "f_auditor":    "f_auditor",
    "g_reporter":   "g_reporter",
    "h_advisor":    "h_advisor",
    "i_integrator": "i_integrator",
    "j_summarizer": "j_summarizer",
    "k_stockkeeper": "k_stockkeeper",
    "FINISH":       END,
}


def build_invoice_graph() -> Any:
    """
    Minimal two-node graph for the /intent endpoint.

    Topology: START → a_generator → hub_writer → END

    Agent A uses the the model client internally; the `llm` arg is not needed.
    Hub writer upserts the extracted invoice into `intelligence_hub`.
    """
    workflow = StateGraph(OrchestratorState)
    workflow.add_node("a_generator", _tracked("a_generator", make_a_generator_node()))
    workflow.add_node("hub_writer", _tracked("hub_writer", make_hub_writer_node()))
    workflow.add_edge(START, "a_generator")
    workflow.add_edge("a_generator", "hub_writer")
    workflow.add_edge("hub_writer", END)
    return workflow.compile()


def build_receipt_graph() -> Any:
    """
    Receipt-scanning graph for the /receipts/scan endpoint — decoupled from the
    invoice graph (Agent A).

    Topology: START → receipt_ocr → receipt_classifier → END

    receipt_ocr runs the model vision over the uploaded image; receipt_classifier
    suggests an expense category from the extracted fields.  Each node degrades
    gracefully so a model hiccup yields an empty/low-confidence form for the
    user to complete rather than an HTTP 500.
    """
    workflow = StateGraph(OrchestratorState)
    workflow.add_node("receipt_ocr", _tracked("receipt_ocr", make_receipt_ocr_node()))
    workflow.add_node(
        "receipt_classifier", _tracked("receipt_classifier", make_receipt_classifier_node())
    )
    workflow.add_edge(START, "receipt_ocr")
    workflow.add_edge("receipt_ocr", "receipt_classifier")
    workflow.add_edge("receipt_classifier", END)
    return workflow.compile()


# Node factories eligible for the fast-path bypass — keep in sync with the
# `read_only=True` entries in agent_registry.AGENT_REGISTRY.
_FAST_PATH_NODE_FACTORIES: dict[str, Any] = {
    "d_forecaster": make_d_forecaster_node,
    "f_auditor": make_f_auditor_node,
}


def build_fast_path_graph(node_name: str) -> Any:
    """
    Single-agent bypass graph for a read-only domain agent (Agent D / F today).

    Topology: START → <node_name> → hub_writer → END

    Mirrors build_invoice_graph/build_receipt_graph (no supervisor node), but
    — unlike them — compiles with checkpointer=get_checkpointer() so a
    fast-pathed run's replay/resume behaviour stays consistent with the full
    graph's (see try_fast_path / orchestrator module docstring plan notes).
    """
    factory = _FAST_PATH_NODE_FACTORIES[node_name]
    workflow = StateGraph(OrchestratorState)
    workflow.add_node(node_name, _tracked(node_name, factory()))
    workflow.add_node("hub_writer", _tracked("hub_writer", make_hub_writer_node()))
    workflow.add_edge(START, node_name)
    workflow.add_edge(node_name, "hub_writer")
    workflow.add_edge("hub_writer", END)
    return workflow.compile(checkpointer=get_checkpointer())


def _first_human_text(messages: list[Any]) -> str:
    for m in messages:
        if isinstance(m, HumanMessage):
            return " ".join(str(m.content).lower().split())
    return ""


async def try_fast_path(state: dict[str, Any]) -> dict[str, Any] | None:
    """
    Classify ``state``'s initial intent and, if it strictly matches exactly one
    read-only agent (agent_registry.read_only_route), run that agent directly
    via build_fast_path_graph — skipping the supervisor graph entirely.

    Returns the final graph state on a fast-path hit, or None if the intent is
    ambiguous, multi-domain, or not tagged read_only — callers should fall back
    to the normal build_graph()/run_graph() path unchanged in that case.

    Never fires if state["context"]["requested_agent"] is already set — that's
    a different, existing short-circuit honoured inside the supervisor node
    itself (see agents/supervisor.py), and callers that already know their
    target agent explicitly (service.py._dispatch_agent) check
    agent_registry.descriptor_for_agent(...).read_only directly instead of
    going through this classifier.
    """
    if state.get("context", {}).get("requested_agent"):
        return None
    node_name = read_only_route(_first_human_text(state.get("messages", [])))
    if node_name is None:
        return None
    graph = build_fast_path_graph(node_name)
    return await graph.ainvoke(state, config=graph_config(state["session_id"]))


_RECURSION_LIMIT = 25   # maximum supervisor ↔ agent round-trips per session


def graph_config(session_id: str) -> dict[str, Any]:
    """Shared LangGraph run config: recursion ceiling + checkpointer thread_id.

    ``thread_id`` is only meaningful when a checkpointer is actually compiled
    into the graph (``LANGGRAPH_CHECKPOINTING_ENABLED``); harmless to always
    set it otherwise. ``session_id`` doubles as ``thread_id`` — every call
    site already mints a fresh one per run (see ``run_graph``/callers), so a
    checkpointed run and its thread are 1:1 today (no cross-request resume
    beyond the explicit resume path in ``routers/conversations.py``).
    """
    return {
        "recursion_limit": _RECURSION_LIMIT,
        "configurable": {"thread_id": session_id},
    }


async def run_graph(state: dict[str, Any]) -> dict[str, Any]:
    """
    Invoke the full supervisor graph with the native LangGraph recursion limit.

    Centralises the run config so every call site (HTTP router, background
    task, tests) uses the same ceiling and checkpointer thread_id.

    Raises:
        GraphRecursionError — if the graph exceeds _RECURSION_LIMIT hops.
            Callers should catch this and return a 508 / degraded response.
    """
    graph = build_graph()
    return await graph.ainvoke(state, config=graph_config(state["session_id"]))


def build_graph() -> Any:
    """Compile and return the full supervisor-based LangGraph StateGraph."""
    workflow = StateGraph(OrchestratorState)

    # Register nodes — all agents use the model internally; no llm arg needed.
    # _tracked wraps each so its LLM calls attribute to the agent on /metrics.
    workflow.add_node("supervisor",    _tracked("supervisor",   make_supervisor_node()))
    workflow.add_node("a_generator",   _tracked("a_generator",  make_a_generator_node()))
    workflow.add_node("b_classifier",  _tracked("b_classifier", make_b_classifier_node()))
    workflow.add_node("c_reconciler",  _tracked("c_reconciler", make_c_reconciler_node()))
    workflow.add_node("d_forecaster",  _tracked("d_forecaster", make_d_forecaster_node()))
    workflow.add_node("e_watchdog",    _tracked("e_watchdog",   make_e_watchdog_node()))
    workflow.add_node("f_auditor",     _tracked("f_auditor",    make_f_auditor_node()))
    workflow.add_node("g_reporter",    _tracked("g_reporter",   make_g_reporter_node()))
    workflow.add_node("h_advisor",     _tracked("h_advisor",    make_h_advisor_node()))
    workflow.add_node("i_integrator",  _tracked("i_integrator", make_i_integrator_node()))
    workflow.add_node("j_summarizer",  _tracked("j_summarizer", make_j_summarizer_node()))
    workflow.add_node("k_stockkeeper", _tracked("k_stockkeeper", make_k_stockkeeper_node()))
    workflow.add_node("hub_writer",    _tracked("hub_writer",   make_hub_writer_node()))

    # Supervisor → conditional fan-out based on state["next"]. When the A2A
    # planner is enabled, "planner" becomes a reachable route (multi-domain).
    supervisor_routes: dict[str, str] = dict(AGENT_NODE_MAP)
    if settings.A2A_PLANNER_ENABLED:
        workflow.add_node("planner", _tracked("planner", make_planner_node()))
        supervisor_routes["planner"] = "planner"
    workflow.add_conditional_edges(
        "supervisor",
        lambda state: state.get("next", "FINISH"),
        supervisor_routes,  # type: ignore[arg-type]
    )

    # Every agent persists its output to intelligence_hub before handing
    # control back to the supervisor.
    for agent_name in AGENT_NODE_MAP:
        if agent_name != "FINISH":
            workflow.add_edge(agent_name, "hub_writer")

    if settings.A2A_PLANNER_ENABLED:
        # Mid-DAG, hub_writer returns to the planner to advance the next stage;
        # otherwise (single-agent flow, or DAG drained) back to the supervisor.
        workflow.add_conditional_edges(
            "hub_writer",
            after_hub_writer,
            {"planner": "planner", "supervisor": "supervisor"},
        )
        # Planner fans the current stage out via Send, or routes to END when the
        # DAG (incl. the terminal Agent-J summary) is drained.
        agent_nodes = [n for n in AGENT_NODE_MAP if n != "FINISH"]
        workflow.add_conditional_edges(
            "planner",
            planner_dispatch,
            [*agent_nodes, END],
        )
    else:
        # hub_writer always returns to supervisor; supervisor then decides
        # whether to route to another agent or emit FINISH → END.
        workflow.add_edge("hub_writer", "supervisor")

    workflow.set_entry_point("supervisor")
    return workflow.compile(checkpointer=get_checkpointer())
