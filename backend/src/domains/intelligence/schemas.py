from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel
from typing_extensions import TypedDict

from src.domains.intelligence.models import AgentRunStatus

# ---------------------------------------------------------------------------
# LangGraph shared state
# ---------------------------------------------------------------------------

AGENT_NAMES = Literal[
    "a_generator",
    "b_classifier",
    "c_reconciler",
    "d_forecaster",
    "e_watchdog",
    "f_auditor",
    "g_reporter",
    "h_advisor",
    "i_integrator",
    "j_summarizer",
    "FINISH",
]


class OrchestratorState(TypedDict):
    """Shared state threaded through every node in the LangGraph."""

    messages: Annotated[list[BaseMessage], add_messages]
    next: str                        # which node the supervisor routes to next
    context: dict[str, Any]          # arbitrary data accumulated across nodes
    session_id: str
    user_id: str | None
    mode: str                        # "insights" | "actions"


# ---------------------------------------------------------------------------
# HTTP request / response models
# ---------------------------------------------------------------------------

class InsightRequest(BaseModel):
    query: str
    context: dict[str, Any] = {}
    user_id: str | None = None


class ActionRequest(BaseModel):
    intent: str
    payload: dict[str, Any] = {}
    user_id: str | None = None


class AgentMessage(BaseModel):
    role: str
    content: str
    agent: str | None = None


class OrchestrationResponse(BaseModel):
    session_id: str
    mode: str
    answer: str
    agents_invoked: list[str]
    context: dict[str, Any]


# ---------------------------------------------------------------------------
# Agent-specific output models
# ---------------------------------------------------------------------------

class ExtractedLineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float
    total: float


class ExtractedInvoice(BaseModel):
    vendor: str | None
    customer: str | None
    invoice_number: str | None
    issue_date: str | None
    due_date: str | None
    currency: str = "KES"
    subtotal: float | None
    tax: float | None
    total: float | None
    line_items: list[ExtractedLineItem] = []
    confidence: float = 0.0


class WatchdogAnalysis(BaseModel):
    account_id: str
    period_days: int
    hidden_states: list[int]
    state_labels: list[str]
    current_state: str
    anomaly_detected: bool
    anomaly_score: float
    event_published: bool
    summary: str


# ---------------------------------------------------------------------------
# Passthrough for existing AgentRun HTTP model
# ---------------------------------------------------------------------------

class AgentRunResponse(BaseModel):
    id: uuid.UUID
    agent_name: str
    status: AgentRunStatus
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
