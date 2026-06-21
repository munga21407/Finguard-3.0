"""Orchestration endpoints.

  POST /ai-insights  — read-only analysis orchestration (idempotent)
  POST /ai-actions   — state-changing action orchestration (idempotent)
  POST /intent       — focused invoice generation (Agent A → hub writer)
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

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
    ActionFeedItem,
    ActionRequest,
    AgentTelemetry,
    InsightFeedItem,
    InsightRequest,
    IntentRequest,
    IntentResponse,
    NotificationItem,
    OrchestrationResponse,
)
from src.domains.intelligence.service import IntelligenceService
from src.infrastructure.database.postgres import get_db

router = APIRouter()

DBSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/ai-insights", response_model=OrchestrationResponse)
async def ai_insights(
    request: InsightRequest,
    current_user: RequireIntelligenceRead,
    db: DBSession,
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

    # ── 5. Record the run so the dashboard insights feed can read it ──────
    await IntelligenceService(db).record_orchestration_run(
        mode="insights",
        query=request.query,
        response=response,
        triggered_by=str(current_user.id),
    )

    return response


@router.post("/ai-actions", response_model=OrchestrationResponse)
async def ai_actions(
    request: ActionRequest,
    current_user: RequireIntelligenceAct,
    db: DBSession,
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

    # ── 5. Record the run so the dashboard actions feed can read it ───────
    await IntelligenceService(db).record_orchestration_run(
        mode="actions",
        query=request.intent,
        response=response,
        triggered_by=str(current_user.id),
    )

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


@router.get("/insights", response_model=list[InsightFeedItem])
async def list_insights(
    db: DBSession,
    _: RequireIntelligenceRead,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[InsightFeedItem]:
    """Recent read-only analysis items for the dashboard insights feed.

    Cheap structured read over persisted ``/ai-insights`` runs — does NOT
    re-run the orchestrator. Empty until insight orchestrations have run.
    """
    return await IntelligenceService(db).list_insights(limit=limit)


@router.get("/actions", response_model=list[ActionFeedItem])
async def list_actions(
    db: DBSession,
    _: RequireIntelligenceRead,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[ActionFeedItem]:
    """Recent actionable items for the dashboard action centre.

    Cheap structured read over persisted ``/ai-actions`` runs — does NOT
    re-run the orchestrator. Empty until action orchestrations have run.
    """
    return await IntelligenceService(db).list_actions(limit=limit)


@router.get("/notifications", response_model=list[NotificationItem])
async def list_notifications(
    db: DBSession,
    _: RequireIntelligenceRead,
    limit: int = Query(default=15, ge=1, le=50),
) -> list[NotificationItem]:
    """Recent agent activity for the top-bar notification bell."""
    return await IntelligenceService(db).list_notifications(limit=limit)


@router.get("/agents", response_model=list[AgentTelemetry])
async def list_agent_telemetry(
    db: DBSession,
    _: RequireIntelligenceRead,
) -> list[AgentTelemetry]:
    """Per-agent run statistics for the agent-status widgets."""
    return await IntelligenceService(db).list_agent_telemetry()
