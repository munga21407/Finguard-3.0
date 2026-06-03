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


class ReceiptExtraction(BaseModel):
    """Structured output from Gemini vision OCR of a receipt image."""

    merchant_name: str | None = None
    date: str | None = None              # ISO-8601 or free-form date string
    total_amount: float | None = None
    currency: str = "KES"
    kra_pin: str | None = None           # Kenya Revenue Authority PIN
    line_items: list[str] = []           # Raw line item descriptions
    confidence: float = 0.0


class TransactionClassification(BaseModel):
    """A single ledger entry annotated with its Gemini-assigned category."""

    entry_id: str
    category: str
    confidence: float = 0.0


class BatchClassificationResult(BaseModel):
    """Gemini-structured output for a batch of transaction classifications."""

    classifications: list[TransactionClassification]


# ---------------------------------------------------------------------------
# Agent C — Reconciliation Detective schemas
# ---------------------------------------------------------------------------

class ReconciliationCandidate(BaseModel):
    """Single candidate match scored by Gemini in Pass 2."""

    transaction_id: str
    invoice_id: str
    match_score: float       # 0.0–1.0; Gemini-assigned semantic confidence
    match_reason: str


class ReconciliationScoringResult(BaseModel):
    """Gemini structured output for the Pass 2 semantic scoring step."""

    candidates: list[ReconciliationCandidate]


class ReconciliationMatch(BaseModel):
    """A confirmed match between an M-Pesa transaction and an invoice."""

    transaction_id: str
    invoice_id: str
    match_type: str          # "exact" | "fuzzy" | "semantic"
    match_score: float
    amount: float            # M-Pesa payment amount in KES
    new_invoice_status: str  # "paid" | "partially_paid"


class ReconciliationReport(BaseModel):
    """Written to context["reconciliation_report"] after Agent C completes."""

    total_transactions: int
    matched_exact: int
    matched_fuzzy: int
    unmatched: int
    matches: list[ReconciliationMatch]
    run_at: str              # ISO-8601 timestamp


# ---------------------------------------------------------------------------
# Agent D — Cash-Flow Forecaster schemas
# ---------------------------------------------------------------------------

class ForecastDataPoint(BaseModel):
    """One day in the 30-day projection."""

    date: str                    # ISO-8601 date
    baseline_net_flow: float     # Holt-Winters projected net flow (KES)
    scheduled_payment: float     # Invoice amounts due this day (KES)
    projected_balance: float     # Running cumulative balance (KES)


class RegimeAnalysis(BaseModel):
    """Gemini Semantic Regime Detector output."""

    regime: str                  # Boom | Normal | Stress | Liquidity Crunch | Recovery
    confidence: float            # 0.0–1.0
    risk_factors: list[str]
    advisory_warnings: list[str]
    narrative: str               # 2-3 sentence human-readable assessment


class CashFlowForecast(BaseModel):
    """Written to context["forecast"] after Agent D completes."""

    horizon_days: int
    current_balance: float
    data_points: list[ForecastDataPoint]
    regime: RegimeAnalysis
    model_used: str              # holt_winters_seasonal | holt_winters_trend | linear_trend | flat
    generated_at: str            # ISO-8601 timestamp


class CoVeSQLQuery(BaseModel):
    """Result of the Chain-of-Verification Text-to-SQL workflow."""

    original_query: str
    sql: str
    explanation: str             # Plain-English translation of the SQL
    audit_passed: bool
    audit_notes: str
    results: list[dict[str, Any]] | None = None


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
