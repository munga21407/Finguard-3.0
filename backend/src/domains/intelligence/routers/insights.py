"""Orchestration endpoints.

  POST /ai-insights  — read-only analysis orchestration (idempotent)
  POST /ai-actions   — state-changing action orchestration (idempotent)
  POST /intent       — focused invoice generation (Agent A → hub writer)
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, HTTPException, status
from langchain_core.messages import HumanMessage

from src.domains.identity.dependencies import (
    RequireIntelligenceAct,
    RequireIntelligenceRead,
)
from src.domains.intelligence.orchestrator import build_invoice_graph
from src.domains.intelligence.routers._common import (
    _check_idempotency_cache,
    _claim_idempotency_slot,
    _run_orchestrator,
    _store_idempotency_result,
    logger,
)
from src.domains.intelligence.schemas import (
    ActionRequest,
    InsightRequest,
    IntentRequest,
    IntentResponse,
    OrchestrationResponse,
)

router = APIRouter()


@router.post("/ai-insights", response_model=OrchestrationResponse)
async def ai_insights(
    request: InsightRequest,
    current_user: RequireIntelligenceRead,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        description=(
            "Client-supplied UUID that deduplicates requests. "
            "A second POST with the same key within 24 hours returns the "
            "cached response without re-running the LangGraph workflow."
        ),
    ),
) -> OrchestrationResponse:
    """
    Run the multi-agent orchestrator in read-only insights mode.

    Idempotency
    -----------
    Supply a unique ``Idempotency-Key`` header (UUID recommended).  If a
    completed response for this key already exists in Redis it is returned
    immediately — no Gemini call is made.  A 409 is returned if a concurrent
    request with the same key is still being processed.
    """
    # ── 1. Cache read ──────────────────────────────────────────────────────
    cached = await _check_idempotency_cache(idempotency_key)
    if cached is not None:
        logger.info("ai_insights: idempotency cache hit", key=idempotency_key)
        return cached

    # ── 2. Claim the slot atomically (SETNX) ───────────────────────────────
    if not await _claim_idempotency_slot(idempotency_key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Request with this Idempotency-Key is already in progress.",
        )

    # ── 3. Execute orchestrator ────────────────────────────────────────────
    response = await _run_orchestrator(
        initial_message=request.query,
        context=request.context,
        user_id=str(current_user.id),
        mode="insights",
    )

    # ── 4. Persist result (overwrites the sentinel with 24 h TTL) ─────────
    await _store_idempotency_result(idempotency_key, response)

    return response


@router.post("/ai-actions", response_model=OrchestrationResponse)
async def ai_actions(
    request: ActionRequest,
    current_user: RequireIntelligenceAct,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        description=(
            "Client-supplied UUID that deduplicates state-changing requests. "
            "Critical for preventing duplicate M-Pesa payments or double "
            "invoice generation from retried HTTP calls."
        ),
    ),
) -> OrchestrationResponse:
    """
    Run the multi-agent orchestrator in actions mode (may publish events).

    Idempotency
    -----------
    Supply a unique ``Idempotency-Key`` header.  Re-submitting the same key
    within 24 hours returns the original response without re-executing any
    side-effecting agents.
    """
    # ── 1. Cache read ──────────────────────────────────────────────────────
    cached = await _check_idempotency_cache(idempotency_key)
    if cached is not None:
        logger.info("ai_actions: idempotency cache hit", key=idempotency_key)
        return cached

    # ── 2. Claim the slot atomically (SETNX) ───────────────────────────────
    if not await _claim_idempotency_slot(idempotency_key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Request with this Idempotency-Key is already in progress.",
        )

    # ── 3. Execute orchestrator ────────────────────────────────────────────
    response = await _run_orchestrator(
        initial_message=request.intent,
        context=request.payload,
        user_id=str(current_user.id),
        mode="actions",
    )

    # ── 4. Persist result ─────────────────────────────────────────────────
    await _store_idempotency_result(idempotency_key, response)

    return response


@router.post("/intent", response_model=IntentResponse)
async def invoke_intent(
    request: IntentRequest,
    current_user: RequireIntelligenceAct,
) -> IntentResponse:
    """
    Focused invoice-generation graph: Agent A → Hub Writer → END.
    Returns the extracted invoice payload and the MongoDB artifact ID.
    """
    session_id = str(uuid.uuid4())

    initial_state = {
        "messages": [HumanMessage(content=request.user_input)],
        "next": "a_generator",
        "context": {**request.context, "document_text": request.user_input},
        "session_id": session_id,
        "user_id": str(current_user.id),
        "mode": "actions",
    }

    graph = build_invoice_graph()
    final_state = await graph.ainvoke(initial_state)

    context = final_state.get("context", {})
    return IntentResponse(
        session_id=session_id,
        intent=request.intent,
        invoice_payload=context.get("extracted_invoice"),
        hub_artifact_id=context.get("hub_artifact_id"),
    )
