"""
Intelligence domain router.

Endpoints:
  POST /api/v1/intelligence/ai-insights        — read-only analysis orchestration
  POST /api/v1/intelligence/ai-actions         — state-changing action orchestration
  POST /api/v1/intelligence/intent             — focused invoice generation (Agent A + hub writer)
  POST /api/v1/intelligence/conversation       — dual-path: cached read OR force-refresh dispatch
  GET  /api/v1/intelligence/conversation/{session_id}/status — poll background task status
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, status
from langchain_core.messages import HumanMessage
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field, ValidationError

from src.domains.identity.dependencies import CurrentUser
from src.domains.intelligence.orchestrator import (
    GraphRecursionError,
    build_invoice_graph,
    run_graph,
)
from src.domains.intelligence.schemas import (
    ActionRequest,
    GenUIPayload,
    InsightArtifact,
    InsightRequest,
    IntentRequest,
    IntentResponse,
    OrchestrationResponse,
    OrchestratorState,
)
from src.infrastructure.cache.redis import get_redis
from src.infrastructure.database.mongodb import get_mongo_db

logger = structlog.get_logger(__name__)
router = APIRouter()

_TASK_STATUS_TTL = 3600  # seconds — 1 hour

# ---------------------------------------------------------------------------
# Incremental GenUI block parser
# ---------------------------------------------------------------------------

# Agents embed structured UI payloads inside ```genui fences so that normal
# markdown text and structured component directives can coexist in the same
# message without ambiguity.  The regex is non-greedy so consecutive fences
# are each matched independently.
_GENUI_BLOCK_RE = re.compile(r"```genui\s*\n(.*?)\n```", re.DOTALL)


def _parse_gen_ui_blocks(text: str) -> tuple[str, list[GenUIPayload]]:
    """
    Incrementally scan *text* for ```genui ... ``` fences and extract valid
    GenUIPayload objects.

    Returns ``(clean_text, payloads)`` where:
    - ``clean_text`` has every successfully parsed fence removed so only
      standard markdown remains for the chat window renderer.
    - ``payloads`` is the ordered list of validated GenUIPayload objects.

    Fences that fail JSON parsing or Pydantic validation are left as-is in
    ``clean_text`` so the raw content is never silently dropped.
    """
    payloads: list[GenUIPayload] = []

    def _replacer(match: re.Match) -> str:  # type: ignore[type-arg]
        json_str = match.group(1).strip()
        try:
            data = json.loads(json_str)
            payload = GenUIPayload(**data)
            payloads.append(payload)
            return ""  # strip the fence from the visible text
        except Exception:
            return match.group(0)  # keep malformed fences as plain text

    clean_text = _GENUI_BLOCK_RE.sub(_replacer, text).strip()
    return clean_text, payloads


def _collect_gen_ui_from_messages(
    messages: list[Any],
) -> list[GenUIPayload]:
    """
    Walk every message in *messages*, apply _parse_gen_ui_blocks to string
    content, and return the deduplicated union of all extracted payloads.

    Deduplication is by (component_id, fallback_text) so that the same
    component rendered twice in one session is only transmitted once.
    """
    seen: set[tuple[str, str]] = set()
    collected: list[GenUIPayload] = []
    for msg in messages:
        content = getattr(msg, "content", None)
        if not isinstance(content, str):
            continue
        _, payloads = _parse_gen_ui_blocks(content)
        for p in payloads:
            key = (p.component_id, p.fallback_text)
            if key not in seen:
                seen.add(key)
                collected.append(p)
    return collected

# Idempotency key constants
_IDEM_PREFIX = "idempotency:"
_IDEM_LOCK_SENTINEL = "__processing__"
_IDEM_LOCK_TTL = 300        # 5 min — max in-flight guard; expires on crash
_IDEM_RESULT_TTL = 86_400   # 24 h — cache successful responses


# ---------------------------------------------------------------------------
# Idempotency helpers
# ---------------------------------------------------------------------------

async def _check_idempotency_cache(
    idempotency_key: str,
) -> OrchestrationResponse | None:
    """
    Check Redis for a previously completed response for this key.

    Returns:
        OrchestrationResponse — cached hit; return immediately to caller.
        None                  — cache miss; proceed with orchestration.

    Raises:
        HTTPException(409)    — a concurrent request with the same key is
                                currently in-flight.
    """
    redis_client = get_redis()
    raw: str | None = await redis_client.get(f"{_IDEM_PREFIX}{idempotency_key}")

    if raw is None:
        return None

    if raw == _IDEM_LOCK_SENTINEL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A request with this Idempotency-Key is already being processed. "
                "Retry in a few seconds or use a new key for a different request."
            ),
        )

    try:
        return OrchestrationResponse.model_validate_json(raw)
    except Exception:
        # Corrupted/stale cache entry — treat as miss and reprocess.
        logger.warning("idempotency: cache entry corrupt, reprocessing", key=idempotency_key)
        return None


async def _claim_idempotency_slot(idempotency_key: str) -> bool:
    """
    Attempt to claim the idempotency slot using SET NX (atomic SETNX).

    Returns True if we won the race and may proceed with orchestration.
    Returns False if a concurrent request already holds the slot.

    The sentinel value expires after _IDEM_LOCK_TTL seconds so a worker
    crash does not block the key permanently.
    """
    redis_client = get_redis()
    return bool(
        await redis_client.set(
            f"{_IDEM_PREFIX}{idempotency_key}",
            _IDEM_LOCK_SENTINEL,
            nx=True,
            ex=_IDEM_LOCK_TTL,
        )
    )


async def _store_idempotency_result(
    idempotency_key: str,
    response: OrchestrationResponse,
) -> None:
    """Overwrite the sentinel with the full response and extend TTL to 24 h."""
    redis_client = get_redis()
    await redis_client.set(
        f"{_IDEM_PREFIX}{idempotency_key}",
        response.model_dump_json(),
        ex=_IDEM_RESULT_TTL,
    )


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

    initial_state: dict[str, Any] = {
        "messages": [HumanMessage(content=initial_message)],
        "gen_ui_payloads": [],
        "error_messages": [],
        "next": "supervisor",
        "context": context,
        "session_id": session_id,
        "user_id": user_id,
        "mode": mode,
    }

    try:
        final_state = await run_graph(initial_state)

    except GraphRecursionError:
        logger.warning(
            "orchestrator: recursion limit exceeded",
            session_id=session_id,
            mode=mode,
        )
        raise HTTPException(
            status_code=508,   # Loop Detected
            detail=(
                "The AI workflow exceeded its maximum recursion limit. "
                "Please simplify your request or try again."
            ),
        )

    except ValidationError as exc:
        logger.error(
            "orchestrator: agent output failed schema validation",
            session_id=session_id,
            error_count=exc.error_count(),
            errors=exc.errors(include_url=False),
        )
        raise HTTPException(
            status_code=422,
            detail=(
                f"An agent produced output that failed validation "
                f"({exc.error_count()} error(s)). "
                "The request can be retried — this is usually a transient LLM issue."
            ),
        )

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

        background_tasks.add_task(_graph_background_task, state)

        logger.info(
            "conversation: background refresh dispatched",
            session_id=session_id,
            intent=intent,
            user_id=user_id,
        )
        return session_id


async def _graph_background_task(state: OrchestratorState) -> None:
    """
    Fire-and-forget wrapper executed by FastAPI BackgroundTasks.

    Uses ``graph.astream(stream_mode="values")`` so that after every node
    completes the full accumulated state snapshot is available.  The supervisor
    writes ``state["next"]`` before routing, so each snapshot lets us emit a
    localized ``running:<agent_node>`` update to Redis DB 0 — the frontend
    polls this via ``GET /conversation/{session_id}/status`` to show which
    agent is actively compiling data.

    On completion the Redis key is updated to ``"completed"`` and includes:
    - ``artifact_id``         — MongoDB key written by hub_writer
    - ``genui_artifact_ids``  — MongoDB keys for GenUI payloads (hub_writer)
    - ``gen_ui_payloads``     — serialized payloads for immediate client use
    - ``active_node``         — cleared to null
    """
    session_id: str = state["session_id"]
    redis_client = get_redis()

    try:
        from src.domains.intelligence.orchestrator import build_graph

        graph = build_graph()
        config: dict[str, Any] = {"recursion_limit": 25}

        final_state: dict[str, Any] = {}
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


# ---------------------------------------------------------------------------
# Existing endpoints
# ---------------------------------------------------------------------------

@router.post("/ai-insights", response_model=OrchestrationResponse)
async def ai_insights(
    request: InsightRequest,
    current_user: CurrentUser,
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
    current_user: CurrentUser,
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
    current_user: CurrentUser,
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


# ---------------------------------------------------------------------------
# Dual-path /conversation endpoint
# ---------------------------------------------------------------------------

@router.post("/conversation", response_model=ConversationResponse)
async def conversation(
    request: ConversationRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
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


# ---------------------------------------------------------------------------
# Background task status polling
# ---------------------------------------------------------------------------

@router.get("/conversation/{session_id}/status", response_model=TaskStatusResponse)
async def conversation_status(
    session_id: str,
    current_user: CurrentUser,
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
    )
