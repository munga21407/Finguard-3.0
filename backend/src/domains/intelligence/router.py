"""
Intelligence domain router.

Endpoints:
  POST /api/v1/intelligence/ai-insights        — read-only analysis orchestration
  POST /api/v1/intelligence/ai-actions         — state-changing action orchestration
  POST /api/v1/intelligence/intent             — focused invoice generation (Agent A + hub writer)
  POST /api/v1/intelligence/conversation       — dual-path: cached read OR force-refresh dispatch
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks
from langchain_core.messages import HumanMessage
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from src.domains.intelligence.orchestrator import build_graph, build_invoice_graph
from src.domains.intelligence.schemas import (
    ActionRequest,
    InsightArtifact,
    InsightRequest,
    IntentRequest,
    IntentResponse,
    OrchestrationResponse,
    OrchestratorState,
)
from src.infrastructure.database.mongodb import get_mongo_db

logger = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Shared orchestrator helper
# ---------------------------------------------------------------------------

async def _run_orchestrator(
    initial_message: str,
    context: dict[str, Any],
    user_id: str | None,
    mode: str,
) -> OrchestrationResponse:
    session_id = str(uuid.uuid4())
    graph = build_graph()

    initial_state = {
        "messages": [HumanMessage(content=initial_message)],
        "next": "supervisor",
        "context": context,
        "session_id": session_id,
        "user_id": user_id,
        "mode": mode,
    }

    final_state = await graph.ainvoke(initial_state)

    agents_invoked = list({
        m.name
        for m in final_state["messages"]
        if hasattr(m, "name") and m.name and m.name != "supervisor"
    })

    answer = next(
        (
            m.content
            for m in reversed(final_state["messages"])
            if hasattr(m, "name") and m.name != "supervisor"
        ),
        "No answer produced.",
    )

    return OrchestrationResponse(
        session_id=session_id,
        mode=mode,
        answer=answer,
        agents_invoked=agents_invoked,
        context=final_state.get("context", {}),
    )


# ---------------------------------------------------------------------------
# ConversationOrchestrator — dual-path read / refresh
# ---------------------------------------------------------------------------

class ConversationOrchestrator:
    """
    Controls the two data-access paths for the /conversation endpoint.

    Path 1 — Decoupled Read:
        Checks MongoDB ``intelligence_hub`` for a non-expired InsightArtifact
        that matches the supplied Verifiable Credential token.  Returns the
        cached insight without touching the LangGraph runtime.

    Path 2 — On-Demand Refresh:
        Builds a fresh OrchestratorState, attaches an audit-trail string, and
        hands the graph invocation off to FastAPI BackgroundTasks so the HTTP
        response returns immediately with a session_id the client can poll.
    """

    def __init__(self, db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
        self._db = db

    # ── Path 1 ──────────────────────────────────────────────────────────────

    async def read_artifact(
        self,
        vc_token: str,
        intent: str,
    ) -> InsightArtifact | None:
        """
        Verify the VC token and return a cached InsightArtifact if one exists
        and has not expired.

        Returns None when the token is invalid, expired, or no artifact is
        cached for the (agent_id, intent) pair.
        """
        from jose import JWTError

        from src.domains.intelligence.security.vc_issuer import verify_vc

        try:
            claims = verify_vc(vc_token)
        except JWTError as exc:
            logger.warning("conversation: VC token verification failed", error=str(exc))
            return None

        agent_id: str = claims.get("agent_id", claims.get("sub", ""))
        artifact_key = f"{agent_id}:{intent}"
        now_iso = datetime.now(UTC).isoformat()

        doc = await self._db["intelligence_hub"].find_one(
            {"_id": artifact_key, "ttl_expires_at": {"$gt": now_iso}},
            {"_id": 0},
        )
        if doc is None:
            return None

        try:
            return InsightArtifact(**doc)
        except Exception as exc:
            logger.warning(
                "conversation: InsightArtifact parse failed",
                artifact_key=artifact_key,
                error=str(exc),
            )
            return None

    # ── Path 2 ──────────────────────────────────────────────────────────────

    def refresh(
        self,
        intent: str,
        user_id: str | None,
        background_tasks: BackgroundTasks,
        context: dict[str, Any] | None = None,
        mode: str = "insights",
    ) -> str:
        """
        Dispatch a LangGraph run as a background task and return the session_id.

        The caller can use the session_id to poll ``agent_runs`` for completion
        status once the background task finishes.
        """
        session_id = str(uuid.uuid4())
        audit_trail = (
            f"session={session_id} "
            f"intent={intent} "
            f"user={user_id or 'anonymous'} "
            f"ts={datetime.now(UTC).isoformat()}"
        )

        state: OrchestratorState = {
            "messages": [HumanMessage(content=intent)],
            "error_messages": [],
            "next": "supervisor",
            "context": {
                "current_intent": intent,
                "audit_trail": audit_trail,
                **(context or {}),
            },
            "session_id": session_id,
            "user_id": user_id,
            "mode": mode,
        }

        background_tasks.add_task(_graph_background_task, state)

        logger.info(
            "conversation: background refresh dispatched",
            session_id=session_id,
            intent=intent,
            user_id=user_id,
        )
        return session_id


async def _graph_background_task(state: OrchestratorState) -> None:
    """Fire-and-forget wrapper executed by FastAPI BackgroundTasks."""
    session_id: str = state["session_id"]
    try:
        graph = build_graph()
        final_state = await graph.ainvoke(state)
        logger.info(
            "conversation: background graph completed",
            session_id=session_id,
            error_count=len(final_state.get("error_messages", [])),
        )
    except Exception as exc:
        logger.error(
            "conversation: background graph failed",
            session_id=session_id,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# HTTP schemas for the /conversation endpoint
# ---------------------------------------------------------------------------

class ConversationRequest(BaseModel):
    intent: str = "GENERATE_INSIGHT"
    context: dict[str, Any] = {}
    user_id: str | None = None
    vc_token: str | None = None     # Required only for Path 1 (read without refresh)
    force_refresh: bool = False
    mode: str = "insights"


class ConversationResponse(BaseModel):
    session_id: str | None = None
    refreshing: bool
    artifact: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Existing endpoints
# ---------------------------------------------------------------------------

@router.post("/ai-insights", response_model=OrchestrationResponse)
async def ai_insights(request: InsightRequest) -> OrchestrationResponse:
    """Run the multi-agent orchestrator in read-only insights mode."""
    return await _run_orchestrator(
        initial_message=request.query,
        context=request.context,
        user_id=request.user_id,
        mode="insights",
    )


@router.post("/ai-actions", response_model=OrchestrationResponse)
async def ai_actions(request: ActionRequest) -> OrchestrationResponse:
    """Run the multi-agent orchestrator in actions mode (may publish events)."""
    return await _run_orchestrator(
        initial_message=request.intent,
        context=request.payload,
        user_id=request.user_id,
        mode="actions",
    )


@router.post("/intent", response_model=IntentResponse)
async def invoke_intent(request: IntentRequest) -> IntentResponse:
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
        "user_id": request.user_id,
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


# ---------------------------------------------------------------------------
# Dual-path /conversation endpoint
# ---------------------------------------------------------------------------

@router.post("/conversation", response_model=ConversationResponse)
async def conversation(
    request: ConversationRequest,
    background_tasks: BackgroundTasks,
) -> ConversationResponse:
    """
    Dual-path insight delivery endpoint.

    **Path 1 — Decoupled Read** (``force_refresh=false``):
        Verifies the supplied ``vc_token`` and returns the latest non-expired
        InsightArtifact from MongoDB if one exists.  Returns ``refreshing=true``
        with a new ``session_id`` when no fresh artifact is cached (transparent
        fallback to Path 2).

    **Path 2 — On-Demand Refresh** (``force_refresh=true``):
        Builds an OrchestratorState with the supplied ``intent`` and an
        auto-generated audit-trail string, then dispatches the full LangGraph
        worker via FastAPI BackgroundTasks.  Returns immediately with the
        ``session_id`` for the caller to poll.
    """
    db: AsyncIOMotorDatabase = get_mongo_db()  # type: ignore[type-arg]
    orchestrator = ConversationOrchestrator(db)

    # ── Path 2 (explicit refresh) ──────────────────────────────────────────
    if request.force_refresh:
        session_id = orchestrator.refresh(
            intent=request.intent,
            user_id=request.user_id,
            background_tasks=background_tasks,
            context=request.context,
            mode=request.mode,
        )
        return ConversationResponse(session_id=session_id, refreshing=True, artifact=None)

    # ── Path 1 (read cache) ────────────────────────────────────────────────
    if request.vc_token:
        artifact = await orchestrator.read_artifact(
            vc_token=request.vc_token,
            intent=request.intent,
        )
        if artifact is not None:
            return ConversationResponse(
                session_id=None,
                refreshing=False,
                artifact=artifact.model_dump(mode="json"),
            )

    # Cache miss — transparently fall through to Path 2
    session_id = orchestrator.refresh(
        intent=request.intent,
        user_id=request.user_id,
        background_tasks=background_tasks,
        context=request.context,
        mode=request.mode,
    )
    return ConversationResponse(session_id=session_id, refreshing=True, artifact=None)
