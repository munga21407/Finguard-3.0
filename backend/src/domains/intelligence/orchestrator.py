"""
Main LangGraph StateGraph — Supervisor / ReAct loop.

Topology:
  [START] → supervisor ──┐
     ↑                   │ conditional edge (state["next"])
     └── any agent ◄─────┘
     ↓ when next == "FINISH"
   [END]

Every agent node unconditionally returns to the supervisor after executing.
The supervisor decides whether to invoke another agent or terminate.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

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
from src.domains.intelligence.agents.supervisor import make_supervisor_node
from src.domains.intelligence.schemas import OrchestratorState

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
    "FINISH":       END,
}


def build_invoice_graph():
    """
    Minimal two-node graph for the /intent endpoint.

    Topology: START → a_generator → hub_writer → END

    Agent A uses the Gemini client internally; the `llm` arg is not needed.
    Hub writer upserts the extracted invoice into `intelligence_hub`.
    """
    workflow = StateGraph(OrchestratorState)
    workflow.add_node("a_generator", make_a_generator_node())
    workflow.add_node("hub_writer", make_hub_writer_node())
    workflow.add_edge(START, "a_generator")
    workflow.add_edge("a_generator", "hub_writer")
    workflow.add_edge("hub_writer", END)
    return workflow.compile()


def build_graph():
    """Compile and return the full supervisor-based LangGraph StateGraph."""
    workflow = StateGraph(OrchestratorState)

    # Register nodes — all agents use Gemini internally; no llm arg needed
    workflow.add_node("supervisor",    make_supervisor_node())
    workflow.add_node("a_generator",   make_a_generator_node())
    workflow.add_node("b_classifier",  make_b_classifier_node())
    workflow.add_node("c_reconciler",  make_c_reconciler_node())
    workflow.add_node("d_forecaster",  make_d_forecaster_node())
    workflow.add_node("e_watchdog",    make_e_watchdog_node())
    workflow.add_node("f_auditor",     make_f_auditor_node())
    workflow.add_node("g_reporter",    make_g_reporter_node())
    workflow.add_node("h_advisor",     make_h_advisor_node())
    workflow.add_node("i_integrator",  make_i_integrator_node())
    workflow.add_node("j_summarizer",  make_j_summarizer_node())

    # Supervisor → conditional fan-out based on state["next"]
    workflow.add_conditional_edges(
        "supervisor",
        lambda state: state.get("next", "FINISH"),
        AGENT_NODE_MAP,
    )

    # Every agent unconditionally returns to supervisor
    for agent_name in AGENT_NODE_MAP:
        if agent_name != "FINISH":
            workflow.add_edge(agent_name, "supervisor")

    workflow.set_entry_point("supervisor")
    return workflow.compile()
