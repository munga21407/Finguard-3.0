"""Dual-path /conversation endpoint + background task status polling.

  POST /conversation                         — cached VC read OR force-refresh dispatch
  GET  /conversation/{session_id}/status     — poll background graph run status
  POST /conversation/{session_id}/resume     — retry a failed run from its last checkpoint
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from langchain_core.messages import HumanMessage
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from src.core.config import settings
from src.domains.identity.dependencies import RequireIntelligenceRead
from src.domains.intelligence.routers._common import (
    _TASK_STATUS_TTL,
    _collect_gen_ui_from_messages,
    logger,
)
from src.domains.intelligence.schemas import (
    GenUIPayload,
    InsightArtifact,
    OrchestratorState,
)
from src.infrastructure.cache.redis import get_redis
from src.infrastructure.database.mongodb import get_mongo_db

router = APIRouter()


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
        Writes ``task_status:{session_id} = "pending"`` to Redis, then hands
        the graph invocation off to FastAPI BackgroundTasks so the HTTP
        response returns immediately.  The background task updates the Redis
        key to ``"completed:{artifact_id}"`` or ``"failed:{reason}"``
        so the client can poll ``GET /conversation/{session_id}/status``.
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
        from src.domains.intelligence.security.vc_issuer import VCError, verify_vc

        try:
            claims = verify_vc(vc_token)
        except VCError as exc:
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

    async def refresh(
        self,
        intent: str,
        user_id: str | None,
        background_tasks: BackgroundTasks,
        context: dict[str, Any] | None = None,
        mode: str = "insights",
    ) -> str:
        """
        Dispatch a LangGraph run as a background task and return the session_id.

        Writes ``task_status:{session_id} = "pending"`` to Redis before
        dispatching so the status endpoint immediately returns a known state.
        The background task updates this key to ``"completed"`` or ``"failed"``.
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
            "gen_ui_payloads": [],
            "error_messages": [],
            "handoffs": [],
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

        # Write initial status before handing off — the client can poll
        # immediately after receiving the session_id.
        redis_client = get_redis()
        await redis_client.setex(
            f"task_status:{session_id}",
            _TASK_STATUS_TTL,
            json.dumps({"status": "pending"}),
        )
        # Record the owning user so the status endpoint can reject cross-user
        # polling of someone else's session (IDOR protection).
        await redis_client.setex(
            f"task_owner:{session_id}", _TASK_STATUS_TTL, user_id or ""
        )

        background_tasks.add_task(_graph_background_task, state, session_id)

        logger.info(
            "conversation: background refresh dispatched",
            session_id=session_id,
            intent=intent,
            user_id=user_id,
        )
        return session_id


async def _graph_background_task(
    state: OrchestratorState | None, session_id: str
) -> None:
    """
    Fire-and-forget wrapper executed by FastAPI BackgroundTasks.

    Uses ``graph.astream(stream_mode="values")`` so that after every node
    completes the full accumulated state snapshot is available.  The supervisor
    writes ``state["next"]`` before routing, so each snapshot lets us emit a
    localized ``running:<agent_node>`` update to Redis DB 0 — the frontend
    polls this via ``GET /conversation/{session_id}/status`` to show which
    agent is actively compiling data.

    ``state`` is ``None`` for a **resume** (see the ``/resume`` endpoint):
    with checkpointing enabled, ``astream(None, config=...)`` with the same
    ``thread_id`` continues from the last checkpoint instead of restarting at
    ``START`` — LangGraph's own resume convention, not something this
    function implements itself. ``session_id`` doubles as ``thread_id``
    either way (see ``orchestrator.graph_config``).

    On completion the Redis key is updated to ``"completed"`` and includes:
    - ``artifact_id``         — MongoDB key written by hub_writer
    - ``genui_artifact_ids``  — MongoDB keys for GenUI payloads (hub_writer)
    - ``gen_ui_payloads``     — serialized payloads for immediate client use
    - ``active_node``         — cleared to null
    """
    redis_client = get_redis()

    try:
        from src.domains.intelligence.orchestrator import (
            build_graph,
            graph_config,
            try_fast_path,
        )

        config = graph_config(session_id)
        final_state: dict[str, Any] = {}

        # Fast path only applies to a fresh dispatch (state is not None) — a
        # resume (state is None) always continues via the full graph's
        # checkpoint, per the plan's documented resume-simplification: the
        # extra hub_writer -> supervisor -> FINISH hop it costs on resume is
        # the same overhead every non-fast-pathed request already pays.
        fast_result = await try_fast_path(dict(state)) if state is not None else None

        if fast_result is not None:
            final_state = fast_result
        else:
            graph = build_graph()
            prev_active: str = ""

            # stream_mode="values" yields the FULL accumulated state after every
            # node, so the last snapshot IS the final state — no second ainvoke.
            async for snapshot in graph.astream(state, config=config, stream_mode="values"):
                final_state = snapshot

                # supervisor sets state["next"] immediately before the agent runs,
                # so "next == b_classifier" means b_classifier is about to start.
                current_next: str = snapshot.get("next", "FINISH") or "FINISH"
                active_label = (
                    f"running:{current_next}" if current_next != "FINISH" else ""
                )

                if active_label != prev_active:
                    await redis_client.setex(
                        f"task_status:{session_id}",
                        _TASK_STATUS_TTL,
                        json.dumps(
                            {"status": "running", "active_node": active_label or None}
                        ),
                    )
                    prev_active = active_label

        # --- Collect GenUI payloads -----------------------------------------
        # 1. Payloads the graph accumulated in state["gen_ui_payloads"]
        state_payloads: list[GenUIPayload] = list(
            final_state.get("gen_ui_payloads") or []
        )
        # 2. Payloads embedded as ```genui fences in agent message content
        msg_payloads = _collect_gen_ui_from_messages(
            final_state.get("messages", [])
        )

        # Merge: state payloads first (already validated by Pydantic in the
        # graph), then message-embedded payloads that aren't already present.
        seen: set[str] = {p.component_id for p in state_payloads}
        all_gen_ui = list(state_payloads)
        for p in msg_payloads:
            if p.component_id not in seen:
                seen.add(p.component_id)
                all_gen_ui.append(p)

        ctx = final_state.get("context", {})
        artifact_id: str | None = ctx.get("hub_artifact_id")
        genui_artifact_ids: list[str] | None = ctx.get("hub_genui_artifact_ids")

        status_payload: dict[str, Any] = {
            "status": "completed",
            "artifact_id": artifact_id,
            "genui_artifact_ids": genui_artifact_ids,
            "gen_ui_payloads": [p.model_dump() for p in all_gen_ui],
            "active_node": None,
        }
        await redis_client.setex(
            f"task_status:{session_id}",
            _TASK_STATUS_TTL,
            json.dumps(status_payload, default=str),
        )
        logger.info(
            "conversation: background graph completed",
            session_id=session_id,
            artifact_id=artifact_id,
            gen_ui_count=len(all_gen_ui),
            error_count=len(final_state.get("error_messages", [])),
        )

    except Exception as exc:
        error_msg = str(exc)[:500]  # cap Redis value size
        status_payload = {
            "status": "failed",
            "detail": error_msg,
            "active_node": None,
            # Checkpointed progress exists iff checkpointing is on — the client
            # can call POST /conversation/{session_id}/resume instead of
            # re-submitting the whole request from scratch.
            "resumable": settings.LANGGRAPH_CHECKPOINTING_ENABLED,
        }
        await redis_client.setex(
            f"task_status:{session_id}",
            _TASK_STATUS_TTL,
            json.dumps(status_payload),
        )
        logger.error(
            "conversation: background graph failed",
            session_id=session_id,
            error=error_msg,
        )


# ---------------------------------------------------------------------------
# HTTP schemas for the /conversation endpoint
# ---------------------------------------------------------------------------

class ConversationRequest(BaseModel):
    intent: str = Field(default="GENERATE_INSIGHT", max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)
    user_id: str | None = None
    vc_token: str | None = None     # Required only for Path 1 (read without refresh)
    force_refresh: bool = False
    mode: str = Field(default="insights", max_length=64)


class ConversationResponse(BaseModel):
    session_id: str | None = None
    refreshing: bool
    artifact: dict[str, Any] | None = None
    # Populated on Path 1 (cached read) when the artifact carries GenUI data.
    # Always empty on Path 2 dispatches — poll the status endpoint instead.
    gen_ui_payloads: list[dict[str, Any]] = []


class TaskStatusResponse(BaseModel):
    session_id: str
    status: str                      # "pending" | "running" | "completed" | "failed"
    artifact_id: str | None = None
    # Which agent node is actively compiling, e.g. "running:b_classifier".
    # Null when status is "pending", "completed", or "failed".
    active_node: str | None = None
    # Structured GenUI payloads ready to render in the chat window.
    gen_ui_payloads: list[dict[str, Any]] = []
    detail: str | None = None
    # True only when status == "failed" and a checkpointed run can be
    # continued via POST /conversation/{session_id}/resume instead of
    # re-submitting the request from scratch.
    resumable: bool = False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/conversation", response_model=ConversationResponse)
async def conversation(
    request: ConversationRequest,
    background_tasks: BackgroundTasks,
    current_user: RequireIntelligenceRead,
) -> ConversationResponse:
    """
    Dual-path insight delivery endpoint.

    **Path 1 — Decoupled Read** (``force_refresh=false``):
        Verifies the supplied ``vc_token`` and returns the latest non-expired
        InsightArtifact from MongoDB if one exists.  Falls through to Path 2
        on cache miss.

    **Path 2 — On-Demand Refresh** (``force_refresh=true``):
        Writes ``task_status:{session_id} = pending`` to Redis, dispatches the
        full LangGraph worker via FastAPI BackgroundTasks, and returns the
        ``session_id`` immediately for the caller to poll
        ``GET /conversation/{session_id}/status``.
    """
    db: AsyncIOMotorDatabase = get_mongo_db()  # type: ignore[type-arg]
    orchestrator = ConversationOrchestrator(db)

    authenticated_user_id = str(current_user.id)

    # ── Path 2 (explicit refresh) ──────────────────────────────────────────
    if request.force_refresh:
        session_id = await orchestrator.refresh(
            intent=request.intent,
            user_id=authenticated_user_id,
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
    session_id = await orchestrator.refresh(
        intent=request.intent,
        user_id=authenticated_user_id,
        background_tasks=background_tasks,
        context=request.context,
        mode=request.mode,
    )
    return ConversationResponse(session_id=session_id, refreshing=True, artifact=None)


@router.get("/conversation/{session_id}/status", response_model=TaskStatusResponse)
async def conversation_status(
    session_id: str,
    current_user: RequireIntelligenceRead,
) -> TaskStatusResponse:
    """
    Return the current execution status of a background graph run.

    Status values:
      - ``"pending"``   — task is queued, no node has started yet
      - ``"running"``   — graph is mid-execution; ``active_node`` identifies
                          which agent is currently compiling data, e.g.
                          ``"running:b_classifier"`` or ``"running:e_watchdog"``
      - ``"completed"`` — graph finished; ``artifact_id`` is set when hub_writer
                          persisted an insight artifact; ``gen_ui_payloads``
                          carries all structured UI components ready to render
      - ``"failed"``    — graph raised an unhandled exception; ``detail``
                          contains a truncated error message

    Returns 404 if the session_id is unknown or the 1-hour TTL has expired.

    Poll this endpoint at ~1 s intervals while ``status == "running"`` and
    render ``active_node`` as a typing indicator in the chat UI.  Stop polling
    when status transitions to ``"completed"`` or ``"failed"``.
    """
    redis_client = get_redis()

    # IDOR guard: a session may only be polled by the user who created it.
    # Return 404 (not 403) on mismatch so the existence of others' sessions is
    # not revealed.
    owner: str | None = await redis_client.get(f"task_owner:{session_id}")  # type: ignore[assignment]
    if owner is not None and owner != str(current_user.id):
        raise HTTPException(
            status_code=404,
            detail="Session not found or status has expired.",
        )

    raw: str | None = await redis_client.get(f"task_status:{session_id}")  # type: ignore[assignment]

    if raw is None:
        raise HTTPException(
            status_code=404,
            detail="Session not found or status has expired.",
        )

    try:
        payload: dict[str, Any] = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        payload = {"status": "pending"}

    return TaskStatusResponse(
        session_id=session_id,
        status=payload.get("status", "pending"),
        artifact_id=payload.get("artifact_id"),
        active_node=payload.get("active_node"),
        gen_ui_payloads=payload.get("gen_ui_payloads") or [],
        detail=payload.get("detail"),
        resumable=bool(payload.get("resumable")),
    )


@router.post(
    "/conversation/{session_id}/resume", response_model=TaskStatusResponse
)
async def conversation_resume(
    session_id: str,
    background_tasks: BackgroundTasks,
    current_user: RequireIntelligenceRead,
) -> TaskStatusResponse:
    """
    Retry a failed background graph run from its last LangGraph checkpoint
    instead of re-submitting the request (and re-paying every prior LLM/tool
    call) from scratch.

    Requires ``LANGGRAPH_CHECKPOINTING_ENABLED`` and a session whose last
    known status is ``"failed"`` with ``resumable=true`` (see
    ``GET /conversation/{session_id}/status``). Re-dispatches the same
    background task with ``state=None`` so LangGraph continues from the last
    completed node — see ``_graph_background_task``.
    """
    redis_client = get_redis()

    owner: str | None = await redis_client.get(f"task_owner:{session_id}")  # type: ignore[assignment]
    if owner is not None and owner != str(current_user.id):
        raise HTTPException(
            status_code=404,
            detail="Session not found or status has expired.",
        )

    raw: str | None = await redis_client.get(f"task_status:{session_id}")  # type: ignore[assignment]
    if raw is None:
        raise HTTPException(
            status_code=404,
            detail="Session not found or status has expired.",
        )

    try:
        payload: dict[str, Any] = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        payload = {}

    if payload.get("status") != "failed" or not payload.get("resumable"):
        raise HTTPException(
            status_code=409,
            detail="Session is not in a resumable failed state.",
        )

    await redis_client.setex(
        f"task_status:{session_id}",
        _TASK_STATUS_TTL,
        json.dumps({"status": "pending"}),
    )
    background_tasks.add_task(_graph_background_task, None, session_id)

    logger.info("conversation: background resume dispatched", session_id=session_id)

    return TaskStatusResponse(session_id=session_id, status="pending")
