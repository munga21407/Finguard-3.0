"""
Hub Writer node — MongoDB intelligence_hub upsert.

Reads every agent output present in `state["context"]`, wraps each in an
InsightArtifact, and upserts them into the `intelligence_hub` collection.
The document key is `"<agent_id>:<intent>"` so repeated invocations refresh the
cached artifact rather than creating duplicates.

Which context keys map to which agent/intent/TTL is defined once, declaratively,
in `agent_registry.AGENT_REGISTRY` — this node just iterates it, so adding an
agent requires no edit here.

GenUI payloads from `state["gen_ui_payloads"]` are persisted separately
under the key `"genui:<session_id>:<component_id>"` with a 1-hour TTL.

The node's own behavior (message compaction, GenUI persistence, insight
persistence) is itself a small ordered registry of independent steps —
see ``HUB_WRITER_STEPS`` below — so a future cross-cutting concern attaches
as a new step without editing the existing ones.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from langchain_core.messages import BaseMessage, HumanMessage, RemoveMessage

from src.core.logging import logger
from src.core.metrics import HUB_WRITE_ERRORS
from src.domains.intelligence.agent_registry import make_handoff, resolve_artifacts
from src.domains.intelligence.schemas import (
    GenUIArtifact,
    GenUIPayload,
    InsightArtifact,
    OrchestratorState,
)
from src.infrastructure.database.mongodb import get_mongo_db

COLLECTION = "intelligence_hub"

# GenUI payloads are session-scoped UI state; 1 h matches the shortest agent TTL
_GENUI_TTL_HOURS = 1

# ── Message-list compaction ───────────────────────────────────────────────────
# state["messages"] is append-only (LangGraph's add_messages reducer) with no
# built-in limit — bounded today only by the supervisor's 25-hop recursion
# ceiling, not by design. Below this threshold, compaction never fires, so the
# common short/single-agent flow (including every fast-pathed request) is
# byte-for-byte unchanged.
_COMPACT_THRESHOLD = 12
_COMPACT_CONTENT_CHARS = 2000


def _compact_messages(messages: list[Any]) -> list[Any]:
    """Prune redundant repeat-visits from a long session's message history.

    Keeps every ``HumanMessage`` (cheap — sessions rarely carry more than one
    or two, and both ``a_generator`` and ``k_stockkeeper``/the fast-path
    classifier scan for a specific one) and every supervisor message (already
    short via its own windowing). For any other named agent that produced more
    than one message, keeps only the most recent and emits a ``RemoveMessage``
    for the rest — this can never shrink the *set* of agent names, so the
    supervisor's cycle guard (``_progress_signature``/``_agent_has_run``, which
    key off exactly that set) behaves identically before and after compaction.
    Long surviving content is truncated as a belt-and-suspenders cap.

    Returns only the ``RemoveMessage``/replacement entries to fold into the
    ``messages`` state update — never touches ``HumanMessage``/supervisor
    entries, so it is a no-op list when nothing needs pruning.
    """
    latest_by_name: dict[str, BaseMessage] = {}
    for m in messages:
        name = getattr(m, "name", None)
        if name and name != "supervisor" and not isinstance(m, HumanMessage):
            latest_by_name[name] = m  # last write wins — messages are in order

    updates: list[Any] = []
    for m in messages:
        name = getattr(m, "name", None)
        if not name or name == "supervisor" or isinstance(m, HumanMessage):
            continue
        if m is not latest_by_name[name]:
            updates.append(RemoveMessage(id=m.id))
        elif isinstance(m.content, str) and len(m.content) > _COMPACT_CONTENT_CHARS:
            updates.append(
                m.model_copy(
                    update={"content": m.content[:_COMPACT_CONTENT_CHARS] + "…[compacted]"}
                )
            )
    return updates


async def _persist_insight(
    db: Any,
    agent_id: str,
    intent: str,
    payload: dict[str, Any],
    ttl_expires_at: datetime,
    now: datetime,
    session_id: str,
) -> str | None:
    """Upsert one InsightArtifact; return its ``_id`` or None on failure."""
    artifact = InsightArtifact(
        agent_id=agent_id,
        intent=intent,
        payload=payload,
        ttl_expires_at=ttl_expires_at,
        created_at=now,
    )
    doc: dict[str, Any] = artifact.model_dump()
    doc["_id"] = f"{agent_id}:{intent}"          # idempotent compound key
    doc["type"] = "insight"
    doc["ttl_expires_at"] = doc["ttl_expires_at"].isoformat()
    doc["created_at"] = doc["created_at"].isoformat()

    try:
        await db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    except Exception as exc:
        HUB_WRITE_ERRORS.inc()
        logger.error(
            "hub_writer: MongoDB upsert failed — artifact NOT persisted",
            artifact_id=doc["_id"],
            agent_id=agent_id,
            intent=intent,
            session_id=session_id,
            error=str(exc),
            exc_info=True,
        )
        return None
    return str(doc["_id"])


async def _persist_gen_ui_payloads(
    db: Any,
    payloads: list[GenUIPayload],
    session_id: str,
    now: datetime,
) -> list[str]:
    """
    Upsert each GenUIPayload into `intelligence_hub` and return the written IDs.

    Document key: ``"genui:<session_id>:<component_id>"``
    Repeated renders of the same component within a session refresh the
    document rather than creating duplicates; props always reflect the
    latest invocation.
    """
    artifact_ids: list[str] = []
    ttl_expires_at = now + timedelta(hours=_GENUI_TTL_HOURS)

    for payload in payloads:
        artifact = GenUIArtifact(
            component_id=payload.component_id,
            props=payload.props,
            fallback_text=payload.fallback_text,
            session_id=session_id,
            ttl_expires_at=ttl_expires_at,
            created_at=now,
        )
        doc: dict[str, Any] = artifact.model_dump()
        doc["_id"] = f"genui:{session_id}:{payload.component_id}"
        doc["type"] = "gen_ui"
        doc["ttl_expires_at"] = doc["ttl_expires_at"].isoformat()
        doc["created_at"] = doc["created_at"].isoformat()

        try:
            await db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)
            artifact_ids.append(doc["_id"])
        except Exception as exc:
            HUB_WRITE_ERRORS.inc()
            logger.error(
                "hub_writer: GenUI payload upsert failed — artifact NOT persisted",
                artifact_id=doc["_id"],
                component_id=payload.component_id,
                session_id=session_id,
                error=str(exc),
                exc_info=True,
            )

    return artifact_ids


# ── Step registry (post-step hook point) ──────────────────────────────────────
# Each step reads only from the shared, read-only _StepContext below — never
# from another step's result — so a new cross-cutting concern registers as one
# more entry in HUB_WRITER_STEPS without editing any existing step's code.

@dataclass(frozen=True)
class _StepContext:
    state: OrchestratorState
    db: Any
    now: datetime
    session_id: str


@dataclass
class HubWriterStepResult:
    """Uniform partial-update shape every step returns — mirrors what a
    LangGraph node itself returns, so the node loop just accumulates them."""

    context: dict[str, Any] = field(default_factory=dict)
    messages: list[Any] = field(default_factory=list)
    handoffs: list[dict[str, Any]] = field(default_factory=list)


HubWriterStep = Callable[[_StepContext], Awaitable[HubWriterStepResult]]


async def _compaction_step(ctx: _StepContext) -> HubWriterStepResult:
    messages: list[Any] = ctx.state.get("messages") or []
    updates = _compact_messages(messages) if len(messages) > _COMPACT_THRESHOLD else []
    return HubWriterStepResult(messages=updates)


async def _genui_step(ctx: _StepContext) -> HubWriterStepResult:
    gen_ui_payloads: list[GenUIPayload] = ctx.state.get("gen_ui_payloads") or []
    if not gen_ui_payloads:
        return HubWriterStepResult()

    written_ids = await _persist_gen_ui_payloads(
        ctx.db, gen_ui_payloads, ctx.session_id, ctx.now
    )
    if not written_ids:
        return HubWriterStepResult()

    logger.info(
        "hub_writer: persisted GenUI payloads",
        count=len(written_ids),
        artifact_ids=written_ids,
        session_id=ctx.session_id,
    )
    return HubWriterStepResult(context={"hub_genui_artifact_ids": written_ids})


async def _insight_step(ctx: _StepContext) -> HubWriterStepResult:
    """Persist every present agent output (not just the top-priority one); the
    registry yields them highest-priority first, so the first written id
    preserves the legacy ``hub_artifact_id`` semantics. Emits one handoff the
    first time each agent's output appears (dedup via ``_handed_off`` so
    re-runs of hub_writer across planner stages don't re-emit)."""
    artifacts = resolve_artifacts(ctx.state["context"])
    if not artifacts:
        if not (ctx.state.get("gen_ui_payloads") or []):
            logger.warning(
                "hub_writer: no recognizable agent key in context and no "
                "GenUI payloads — passing state through unmodified",
                session_id=ctx.session_id,
            )
        return HubWriterStepResult()

    handed_off: set[str] = set(ctx.state["context"].get("_handed_off") or [])
    new_handoffs: list[dict[str, Any]] = []
    insight_ids: list[str] = []

    for art in artifacts:
        artifact_id = await _persist_insight(
            ctx.db, art.agent_id, art.intent, art.payload,
            ctx.now + art.ttl, ctx.now, ctx.session_id,
        )
        if artifact_id is not None:
            insight_ids.append(artifact_id)
        if art.agent_id not in handed_off:
            status: Literal["ok", "degraded", "empty", "error"] = (
                "degraded" if bool(art.payload.get("degraded")) else "ok"
            )
            new_handoffs.append(make_handoff(art.agent_id, status=status))
            handed_off.add(art.agent_id)

    context_update: dict[str, Any] = {}
    if insight_ids:
        context_update["hub_artifact_id"] = insight_ids[0]   # highest priority
        context_update["hub_artifact_ids"] = insight_ids
    context_update["_handed_off"] = sorted(handed_off)
    return HubWriterStepResult(context=context_update, handoffs=new_handoffs)


# Ordered extension point. Append here (production) or monkeypatch this list
# (tests — mirrors agent_registry.AGENT_REGISTRY's own test convention, see
# test_new_agent_surfaces_via_registry_only) to attach a new cross-cutting
# concern without touching any step above.
HUB_WRITER_STEPS: list[HubWriterStep] = [
    _compaction_step,
    _genui_step,
    _insight_step,
]


def make_hub_writer_node() -> Any:
    async def hub_writer_node(state: OrchestratorState) -> dict[str, Any]:
        ctx = _StepContext(
            state=state,
            db=get_mongo_db(),
            now=datetime.now(UTC),
            session_id=state.get("session_id", ""),
        )
        updated_context = dict(state["context"])
        messages: list[Any] = []
        handoffs: list[dict[str, Any]] = []

        for step in HUB_WRITER_STEPS:
            result = await step(ctx)
            updated_context.update(result.context)
            messages.extend(result.messages)
            handoffs.extend(result.handoffs)

        out: dict[str, Any] = {"context": updated_context}
        if handoffs:
            out["handoffs"] = handoffs
        if messages:
            out["messages"] = messages
        return out

    return hub_writer_node
