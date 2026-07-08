from __future__ import annotations

import json
import operator
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, field_validator
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


# ---------------------------------------------------------------------------
# Generative UI — type-safe contract between backend and chat window
# ---------------------------------------------------------------------------

class GenUIPayload(BaseModel):
    """
    Envelope for a Generative UI component rendered inside the client chat window.

    ``component_id`` must exactly match a key registered in the frontend
    component registry (e.g. ``"InvoiceCard"``, ``"CashFlowChart"``).
    ``props`` carries the component's required properties; the shape is
    validated at runtime against the registry entry on the client side.
    ``fallback_text`` is rendered whenever the component cannot be mounted
    (unknown id, render error, reduced-motion mode, etc.).
    """

    component_id: str = Field(
        ...,
        min_length=1,
        description="Frontend registry key for the component to render",
    )
    props: dict[str, Any] = Field(
        ...,
        description="Component-specific props matching the component's required properties",
    )
    fallback_text: str = Field(
        ...,
        min_length=1,
        description="Plain-text fallback shown when the component cannot be rendered",
    )

    @field_validator("component_id")
    @classmethod
    def _no_whitespace(cls, v: str) -> str:
        if v != v.strip():
            raise ValueError("component_id must not have leading or trailing whitespace")
        return v


class AgentHOutput(BaseModel):
    """Structured output for Agent H (Financial Advisor), used as the Gemini 2.5
    Flash ``response_schema`` for native structured-output generation.

    The advisor returns a conversational ``narrative_response`` and, when a
    figure is better shown than described, an optional list of ``ui_widgets``
    (Generative UI components from the frontend registry). The agent node folds
    ``ui_widgets`` into the orchestrator's ``gen_ui_payloads`` so the chat client
    renders them inline beneath the narrative.
    """

    narrative_response: str = Field(
        ...,
        min_length=1,
        description=(
            "The advisor's natural-language guidance for the SME, in Markdown. "
            "This is always shown to the user; never leave it empty."
        ),
    )
    ui_widgets: list[GenUIPayload] = Field(
        default_factory=list,
        description=(
            "Optional Generative UI widgets to render alongside the narrative. "
            "Each widget's component_id MUST be one of the components defined in "
            "the GenUI catalog. Omit entirely when no visual aid adds value."
        ),
    )


class KeyFinding(BaseModel):
    """A single key metric distilled from agent analysis for GenUI metric badges."""

    metric: str = Field(..., min_length=1, description="Short label (e.g. 'Runway', 'Regime')")
    value: str = Field(
        ..., min_length=1,
        description="Formatted display value (e.g. '4 Months', 'KES 1.2M')",
    )


class CompositeGenUIPayload(BaseModel):
    """
    Extended GenUI envelope separating deterministic computed figures (props) from
    LLM-generated contextual key findings (findings).

    props    — deterministic agent-computed data forwarded directly to the component.
    findings — LLM-generated KeyFinding bullet points surfaced as metric badges.
    """

    component_id: str = Field(..., min_length=1)
    props: dict[str, Any] = Field(...)
    findings: list[KeyFinding] = Field(default_factory=list)
    fallback_text: str = Field(..., min_length=1)

    @field_validator("component_id")
    @classmethod
    def _no_whitespace(cls, v: str) -> str:
        if v != v.strip():
            raise ValueError("component_id must not have leading or trailing whitespace")
        return v

    def to_gen_ui_payload(self) -> GenUIPayload:
        """Downcast to GenUIPayload, merging findings into props for the state accumulator."""
        return GenUIPayload(
            component_id=self.component_id,
            props={**self.props, "findings": [f.model_dump() for f in self.findings]},
            fallback_text=self.fallback_text,
        )


class AgentHandoff(BaseModel):
    """Typed provenance envelope an agent's output publishes (A2A P1).

    Additive to the raw ``context[context_key]`` write — the envelope records
    *which* agent produced *what*, with a ``status`` so a downstream consumer (or
    the planner / Agent J) can tell an ``ok`` result from a ``degraded`` one
    without re-deriving it, and ``depends_on`` for lineage. ``payload`` is left
    empty by default (the data lives in context under ``context_key``); it exists
    for callers that want to attach a compact provenance snapshot. See
    docs/A2A_PROTOCOL.md §4.1.
    """

    agent_id: str
    context_key: str
    status: Literal["ok", "degraded", "empty", "error"] = "ok"
    payload: dict[str, Any] = Field(default_factory=dict)
    produced_at: str = ""
    depends_on: list[str] = Field(default_factory=list)


def merge_context(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Reducer for ``OrchestratorState.context`` — shallow per-key merge, right wins.

    Replaces the default last-write-**replace** channel behaviour so that when
    several agents run in one parallel stage (A2A P4), each can land *its own*
    key without clobbering a sibling's write. Given the invariant that every
    agent writes only the keys it owns (disjoint across agents — see
    ``agent_registry.write_keys`` and its contract test), this merge is
    conflict-free and reproduces the old full-dict-carry accumulation while being
    parallel-safe. See docs/A2A_PROTOCOL.md §4.3.

    Note: a shallow merge cannot *delete* a key — nothing in the graph relies on
    removing a context key mid-session (agent outputs are write-once).
    """
    return {**left, **right}


class OrchestratorState(TypedDict):
    """Shared state threaded through every node in the LangGraph.

    ``messages`` accumulates standard LangChain BaseMessage objects
    (HumanMessage, AIMessage, ToolMessage) via the add_messages reducer.

    ``gen_ui_payloads`` accumulates structured GenUIPayload envelopes
    alongside the conversational messages; the operator.add reducer
    appends new payloads without overwriting earlier ones, so the full
    render history is preserved for the session.

    ``context`` uses the :func:`merge_context` reducer (per-key merge) rather
    than plain replacement, so an agent returns only the keys it owns and the
    reducer reassembles the accumulated dict — the enabler for parallel fan-out.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    gen_ui_payloads: Annotated[list[GenUIPayload], operator.add]
    error_messages: Annotated[list[str], operator.add]
    # A2A P1 — append-only log of AgentHandoff envelopes (as dicts). operator.add
    # concatenation is parallel-safe: hub_writer emits each agent's handoff once.
    handoffs: Annotated[list[dict[str, Any]], operator.add]
    next: str                        # which node the supervisor routes to next
    context: Annotated[dict[str, Any], merge_context]  # accumulated across nodes
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


class GenUIArtifact(BaseModel):
    """Written to `intelligence_hub` for each GenUI payload emitted in a session."""

    component_id: str
    props: dict[str, Any]
    fallback_text: str
    session_id: str
    ttl_expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# HTTP request / response models
# ---------------------------------------------------------------------------

_MAX_INPUT_CHARS = 2000
_MAX_CONTEXT_BYTES = 102_400  # 100 KB


class InsightRequest(BaseModel):
    query: str = Field(..., max_length=_MAX_INPUT_CHARS)
    context: dict[str, Any] = Field(default_factory=dict)
    user_id: str | None = None

    @field_validator("context")
    @classmethod
    def _context_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v, default=str)) > _MAX_CONTEXT_BYTES:
            raise ValueError("context payload must not exceed 100 KB")
        return v


class ActionRequest(BaseModel):
    intent: str = Field(..., max_length=_MAX_INPUT_CHARS)
    payload: dict[str, Any] = Field(default_factory=dict)
    user_id: str | None = None

    @field_validator("payload")
    @classmethod
    def _payload_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v, default=str)) > _MAX_CONTEXT_BYTES:
            raise ValueError("payload must not exceed 100 KB")
        return v


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
    # A2A P1 — per-agent provenance envelopes accumulated during the run.
    handoffs: list[dict[str, Any]] = Field(default_factory=list)


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
    subtotal: float | None = Field(default=None, ge=0.0)
    tax: float | None = Field(default=None, ge=0.0)
    total: float | None = Field(default=None, ge=0.0)
    line_items: list[ExtractedLineItem] = []
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class WatchdogAnalysis(BaseModel):
    account_id: str
    period_days: int = Field(..., gt=0)
    hidden_states: list[int]
    state_labels: list[str]
    current_state: str
    state_probabilities: list[float]
    anomaly_detected: bool
    anomaly_score: float = Field(..., ge=0.0, le=1.0)
    isolation_score: float = Field(..., ge=0.0, le=1.0)
    is_duplicate: bool
    duplicate_match_score: float = Field(..., ge=0.0, le=1.0)
    vc_id: str | None
    event_published: bool
    summary: str
    # Anomaly-model provenance (Sprint 4 — honesty): "persisted" = the customer's
    # weekly-retrained IsolationForest; "on_the_fly" = a degraded per-call fit for
    # a brand-new customer with no persisted model yet. ``degraded`` mirrors this
    # so the UI can flag a lower-confidence result.
    isolation_model: str = "persisted"
    degraded: bool = False

    @field_validator("state_probabilities")
    @classmethod
    def _probabilities_bounded(cls, v: list[float]) -> list[float]:
        if any(p < -1e-6 or p > 1.0 + 1e-6 for p in v):
            raise ValueError("Each state probability must be in [0.0, 1.0]")
        return v


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


_MAX_SME_TAX_LIABILITY_KES = 1_000_000_000.0   # 1B KES — hallucination guard


class AgentFOutput(BaseModel):
    """Structured output produced by Agent F — Tax Auditor."""
    tax_type: str
    tax_liability: float = Field(..., ge=0.0)
    effective_tax_rate: float = Field(..., ge=0.0, le=100.0)
    compliance_flags: list[str]
    kra_references: list[str]
    audit_summary: str

    @field_validator("tax_liability")
    @classmethod
    def _tax_liability_sme_bounds(cls, v: float) -> float:
        if v > _MAX_SME_TAX_LIABILITY_KES:
            raise ValueError(
                f"tax_liability {v:,.0f} KES exceeds the SME context ceiling of "
                f"{_MAX_SME_TAX_LIABILITY_KES:,.0f} KES — likely an LLM hallucination"
            )
        return v

    @field_validator("effective_tax_rate")
    @classmethod
    def _tax_rate_bounds(cls, v: float) -> float:
        # Kenya's statutory maximum is 30 % CIT; flag anomalies above 35 %
        # (allow some headroom for blended rates and penalties).
        if v > 35.0:
            raise ValueError(
                f"effective_tax_rate {v:.2f}% exceeds 35% — "
                "verify that this is not a hallucinated value"
            )
        return v


class AgentGOutput(BaseModel):
    """Structured output produced by Agent G — Credit Strategist."""
    bankability_score: int = Field(..., ge=0, le=100)
    risk_tier: Literal["LOW", "MEDIUM", "HIGH"]   # rejects any other string
    strategic_narrative: str


class SummaryBullet(BaseModel):
    """One executive-summary bullet: a bold label + its plain-language text.

    Structured (Sprint 5) so Agent J no longer parses ``•``/``**`` out of a raw
    string — the bullet count and labels come straight from this model.
    """

    label: str
    text: str


class ExecutiveSummary(BaseModel):
    """Agent J's structured executive summary — 3-5 labelled bullets."""

    bullets: list[SummaryBullet] = []


# Base expense taxonomy the receipt scanner may assign — kept aligned with the
# frontend ReceiptScanner form's <select> so the suggested value is always a
# valid option the user can accept without re-mapping. Operators may *extend*
# this set at runtime via the ``receipt`` tuning section (S6-6); use
# ``effective_receipt_categories()`` — not this constant — anywhere the live set
# matters. This constant remains the safe fallback if tuning is unavailable.
RECEIPT_CATEGORIES: tuple[str, ...] = (
    "supplies",
    "services",
    "utilities",
    "travel",
    "other",
)


def effective_receipt_categories() -> tuple[str, ...]:
    """The live receipt taxonomy (config override or the base fallback).

    Reads the ``receipt`` tuning section lazily so this central schema module
    never imports the tuning layer at load time; any failure degrades to the
    base :data:`RECEIPT_CATEGORIES`.
    """
    try:
        from src.domains.intelligence.tuning import get_receipt_tuning  # noqa: PLC0415

        cats = get_receipt_tuning().categories
        return cats or RECEIPT_CATEGORIES
    except Exception:
        return RECEIPT_CATEGORIES


class ReceiptExtraction(BaseModel):
    """Structured output from Gemini vision OCR of a receipt image.

    ``suggested_category`` is produced by the *same* vision call as the OCR
    fields (Sprint 3: one Gemini call instead of a second classification call);
    the validator clamps any off-taxonomy value to ``"other"``.
    """

    merchant_name: str | None = None
    date: str | None = None
    total_amount: float | None = Field(default=None, ge=0.0)
    currency: str = "KES"
    kra_pin: str | None = None
    line_items: list[str] = []
    suggested_category: str = "other"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("suggested_category")
    @classmethod
    def _clamp_category(cls, v: str) -> str:
        candidate = (v or "other").strip().lower()
        return candidate if candidate in effective_receipt_categories() else "other"


class TransactionClassification(BaseModel):
    """A single ledger entry annotated with its Gemini-assigned category."""

    entry_id: str
    category: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


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
    match_score: float = Field(..., ge=0.0, le=1.0)
    match_reason: str


class ReconciliationScoringResult(BaseModel):
    """Gemini structured output for the Pass 2 semantic scoring step."""

    candidates: list[ReconciliationCandidate]


class ReconciliationMatch(BaseModel):
    """A confirmed match between an incoming settlement and an invoice.

    ``source`` identifies the settlement rail the ``transaction_id`` refers to —
    an M-Pesa transaction or a bank statement line — so the persistence step can
    record the Payment with the right vault and provenance FK.
    """

    transaction_id: str
    invoice_id: str
    match_type: str          # "exact" | "fuzzy" | "semantic"
    match_score: float = Field(..., ge=0.0, le=1.0)
    amount: float = Field(..., ge=0.0)
    new_invoice_status: str  # "paid" | "partially_paid"
    source: Literal["mpesa", "bank"] = "mpesa"


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

    regime: Literal["Boom", "Normal", "Stress", "Liquidity Crunch", "Recovery"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    risk_factors: list[str]
    advisory_warnings: list[str]
    narrative: str


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
    user_input: str = Field(..., max_length=_MAX_INPUT_CHARS)
    intent: str = Field(default="GENERATE_INVOICE", max_length=128)
    context: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None
    user_id: str | None = None

    @field_validator("context")
    @classmethod
    def _context_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v, default=str)) > _MAX_CONTEXT_BYTES:
            raise ValueError("context payload must not exceed 100 KB")
        return v


class IntentResponse(BaseModel):
    session_id: str
    intent: str
    invoice_payload: dict[str, Any] | None = None
    hub_artifact_id: str | None = None


class ReceiptScanResponse(BaseModel):
    """Returned by POST /intelligence/receipts/scan.

    Carries the OCR'd receipt fields and a suggested expense category for the
    user to review.  No persistence happens here — the reviewed values are sent
    to POST /finance/receipts to create the expense.
    """
    session_id: str
    extraction: ReceiptExtraction
    suggested_category: str
    error: str | None = None


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


# ---------------------------------------------------------------------------
# Dashboard feeds — GET /intelligence/insights and /intelligence/actions
# ---------------------------------------------------------------------------
# Cheap, structured reads over the persisted AgentRun log so always-on dashboard
# widgets don't re-run the LLM orchestrator on every render. Populated when the
# /ai-insights and /ai-actions orchestration endpoints record their runs.

class InsightFeedItem(BaseModel):
    """One read-only analysis item for the IntelligenceInsights widget."""
    id: uuid.UUID
    agent: str
    summary: str
    created_at: datetime


class ActionFeedItem(BaseModel):
    """One actionable item for the AiActionCenter widget."""
    id: uuid.UUID
    agent: str
    summary: str
    status: AgentRunStatus
    created_at: datetime


class NotificationItem(BaseModel):
    """One bell-feed notification for the TopNavBar, from a recent agent run."""
    id: uuid.UUID
    agent: str
    message: str
    created_at: datetime


class AgentTelemetry(BaseModel):
    """Per-agent run statistics for the AgentStatus / AgentIntegrations widgets."""
    agent: str
    total_runs: int
    completed: int
    failed: int
    running: int
    last_status: AgentRunStatus | None
    last_run_at: datetime | None


class GenUiErrorReport(BaseModel):
    """A GenUI widget render crash reported from the frontend error boundary.

    Dispatched by ``GenUiBoundary.componentDidCatch`` when an unexpected LLM
    structure makes a generative widget throw, so the failure surfaces in
    operational telemetry instead of dying silently in the browser console.
    """

    component_id: str = Field(max_length=120)
    message: str = Field(max_length=2000)
    # React component stack; truncated client-side, capped again here.
    component_stack: str | None = Field(default=None, max_length=8000)
    # Path the widget rendered on, for correlating with a dashboard view.
    pathname: str | None = Field(default=None, max_length=512)


class KnowledgeIngestResponse(BaseModel):
    """Result of an admin knowledge-base document upload.

    ``inserted`` vs ``skipped`` reflects the ON CONFLICT DO NOTHING upsert — a
    re-uploaded document whose sections already exist reports ``skipped``.
    """

    document_title: str
    chunks: int
    inserted: int
    skipped: int


# ── Admin: agent tuning + effective-dated tax rates ────────────────────────────

class AgentTuningView(BaseModel):
    """Effective (env > DB > default) tuning for each agent section — read-only view."""

    reconciler: dict[str, Any]
    watchdog: dict[str, Any]
    auditor: dict[str, Any]
    bankability: dict[str, Any]
    classifier: dict[str, Any]
    receipt: dict[str, Any]


class AgentTuningSectionUpdate(BaseModel):
    """Partial override payload for one tuning section (agent_config row)."""

    payload: dict[str, Any] = Field(default_factory=dict)


class AdminTuningActionResponse(BaseModel):
    """Result of an admin tuning / tax-rate mutation."""

    target: str
    status: str


class TaxRateUpsert(BaseModel):
    """Set/replace an effective-dated tax rate for Agent F."""

    rate: float = Field(..., ge=0.0)
    effective_from: date
    note: str | None = Field(default=None, max_length=512)


class TaxRateView(BaseModel):
    rate_key: str
    rate: float
    effective_from: date
    note: str | None = None
