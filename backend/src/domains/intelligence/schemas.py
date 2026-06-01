from __future__ import annotations

import operator
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
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
    error_messages: Annotated[list[str], operator.add]
    next: str                        # which node the supervisor routes to next
    context: dict[str, Any]          # arbitrary data accumulated across nodes
    session_id: str
    user_id: str | None
    mode: str                        # "insights" | "actions"


# ---------------------------------------------------------------------------
# MongoDB intelligence_hub cache document
# ---------------------------------------------------------------------------

class InsightArtifact(BaseModel):
    """Written to `intelligence_hub` collection after each agent invocation."""

    agent_id: str                   # "A" .. "J"
    intent: str                     # e.g. "GENERATE_INVOICE"
    payload: dict[str, Any]         # agent output serialised as dict
    ttl_expires_at: datetime        # when this cached insight expires
    created_at: datetime = Field(default_factory=datetime.utcnow)


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
    state_probabilities: list[float]   # Forward-algorithm P(S_T | O_1..T)
    anomaly_detected: bool
    anomaly_score: float               # Weighted HMM score
    isolation_score: float             # IsolationForest outlier score
    is_duplicate: bool                 # rapidfuzz duplicate detection
    duplicate_match_score: float       # rapidfuzz similarity 0-1
    vc_id: str | None                  # MongoDB trust_log document ID
    event_published: bool
    summary: str


# ---------------------------------------------------------------------------
# Passthrough for existing AgentRun HTTP model
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Chat / service schemas
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str  # "user" | "model"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    system: str | None = None
    max_tokens: int = 1024


class ChatResponse(BaseModel):
    content: str
    model: str
    input_tokens: int
    output_tokens: int


class AgentFOutput(BaseModel):
    """Structured output produced by Agent F — Tax Auditor."""
    tax_type: str                  # e.g. "VAT", "CORPORATE_TAX", "PAYE"
    tax_liability: float           # KES amount owed for the audit period
    effective_tax_rate: float      # Effective rate as a percentage 0-100
    compliance_flags: list[str]    # Specific compliance issues identified
    kra_references: list[str]      # KRA document sections cited
    audit_summary: str             # Human-readable findings narrative


class AgentGOutput(BaseModel):
    """Structured output produced by Agent G — Credit Strategist."""
    bankability_score: int         # 0-100; higher = more creditworthy
    risk_tier: str                 # "LOW" | "MEDIUM" | "HIGH"
    strategic_narrative: str       # Executive narrative with recommendations


class AgentRunCreate(BaseModel):
    agent_name: str
    input_data: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# /intent endpoint request & response
# ---------------------------------------------------------------------------

class IntentRequest(BaseModel):
    user_input: str
    intent: str = "GENERATE_INVOICE"
    context: dict[str, Any] = {}
    correlation_id: str | None = None
    user_id: str | None = None


class IntentResponse(BaseModel):
    session_id: str
    intent: str
    invoice_payload: dict[str, Any] | None = None
    hub_artifact_id: str | None = None


# ---------------------------------------------------------------------------
# AgentRun HTTP response
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
