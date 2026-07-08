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
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

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


def make_hub_writer_node() -> Any:
    async def hub_writer_node(state: OrchestratorState) -> dict[str, Any]:
        now = datetime.now(UTC)
        db = get_mongo_db()
        session_id: str = state.get("session_id", "")
        updated_context = dict(state["context"])

        # --- GenUI payloads ------------------------------------------------
        gen_ui_payloads: list[GenUIPayload] = state.get("gen_ui_payloads") or []
        if gen_ui_payloads:
            written_ids = await _persist_gen_ui_payloads(db, gen_ui_payloads, session_id, now)
            if written_ids:
                updated_context["hub_genui_artifact_ids"] = written_ids
                logger.info(
                    "hub_writer: persisted GenUI payloads",
                    count=len(written_ids),
                    artifact_ids=written_ids,
                    session_id=session_id,
                )

        # --- Agent insight artifacts ----------------------------------------
        # Every present agent output is persisted (not just the top-priority one);
        # the registry yields them highest-priority first, so the first written id
        # preserves the legacy ``hub_artifact_id`` semantics.
        artifacts = resolve_artifacts(state["context"])
        if not artifacts:
            if not gen_ui_payloads:
                logger.warning(
                    "hub_writer: no recognizable agent key in context and no "
                    "GenUI payloads — passing state through unmodified",
                    session_id=session_id,
                )
            return {"context": updated_context}

        # A2A P1 — emit a typed provenance handoff the first time each agent's
        # output appears (dedup via _handed_off so re-runs of hub_writer across
        # planner stages don't re-emit). ``degraded`` is inferred from the output
        # payload (e.g. Agent E's watchdog_analysis.degraded).
        handed_off: set[str] = set(state["context"].get("_handed_off") or [])
        new_handoffs: list[dict[str, Any]] = []

        insight_ids: list[str] = []
        for art in artifacts:
            artifact_id = await _persist_insight(
                db, art.agent_id, art.intent, art.payload,
                now + art.ttl, now, session_id,
            )
            if artifact_id is not None:
                insight_ids.append(artifact_id)
            if art.agent_id not in handed_off:
                status: Literal["ok", "degraded", "empty", "error"] = (
                    "degraded" if bool(art.payload.get("degraded")) else "ok"
                )
                new_handoffs.append(make_handoff(art.agent_id, status=status))
                handed_off.add(art.agent_id)

        if insight_ids:
            updated_context["hub_artifact_id"] = insight_ids[0]   # highest priority
            updated_context["hub_artifact_ids"] = insight_ids
        updated_context["_handed_off"] = sorted(handed_off)

        result: dict[str, Any] = {"context": updated_context}
        if new_handoffs:
            result["handoffs"] = new_handoffs
        return result

    return hub_writer_node
