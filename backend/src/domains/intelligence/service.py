from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from google.genai import types
from langchain_core.messages import HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import logger
from src.domains.intelligence.llm_client import get_gemini_client
from src.domains.intelligence.models import AgentRun, AgentRunStatus
from src.domains.intelligence.schemas import (
    ActionFeedItem,
    AgentRunCreate,
    AgentTelemetry,
    ChatRequest,
    ChatResponse,
    InsightFeedItem,
    NotificationItem,
    OrchestrationResponse,
)

# ── AgentRun → dashboard feed mapping (pure, DB-free for unit testing) ─────────

def _run_summary(run: AgentRun) -> str:
    """Best-effort human summary of a persisted agent run."""
    output = run.output_data or {}
    answer = output.get("answer")
    if isinstance(answer, str) and answer.strip():
        return answer.strip()
    if run.error:
        return run.error
    return "No summary available."


def insight_from_run(run: AgentRun) -> InsightFeedItem:
    return InsightFeedItem(
        id=run.id,
        agent=run.agent_name,
        summary=_run_summary(run),
        created_at=run.created_at,
    )


def action_from_run(run: AgentRun) -> ActionFeedItem:
    return ActionFeedItem(
        id=run.id,
        agent=run.agent_name,
        summary=_run_summary(run),
        status=run.status,
        created_at=run.created_at,
    )


def aggregate_telemetry(runs: list[AgentRun]) -> list[AgentTelemetry]:
    """Group runs (newest-first) into per-agent statistics. Pure for testing."""
    by_agent: dict[str, list[AgentRun]] = {}
    for r in runs:
        by_agent.setdefault(r.agent_name, []).append(r)

    telemetry: list[AgentTelemetry] = []
    for agent, agent_runs in by_agent.items():
        latest = agent_runs[0]  # input is newest-first
        telemetry.append(
            AgentTelemetry(
                agent=agent,
                total_runs=len(agent_runs),
                completed=sum(1 for r in agent_runs if r.status == AgentRunStatus.COMPLETED),
                failed=sum(1 for r in agent_runs if r.status == AgentRunStatus.FAILED),
                running=sum(
                    1
                    for r in agent_runs
                    if r.status in (AgentRunStatus.RUNNING, AgentRunStatus.PENDING)
                ),
                last_status=latest.status,
                last_run_at=latest.created_at,
            )
        )
    telemetry.sort(
        key=lambda t: t.last_run_at or datetime.min.replace(tzinfo=UTC), reverse=True
    )
    return telemetry


class IntelligenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def chat(self, request: ChatRequest) -> ChatResponse:
        # Intentional BaseLLMClient.raw() escape hatch: role-based multi-turn
        # chat (Content/Part history + system_instruction + max_output_tokens) is
        # not modelled by the neutral interface. The agent graph uses the
        # interface; only this standalone chat service touches the SDK directly.
        client = get_gemini_client()

        # Map messages to Gemini Content objects (role must be "user" or "model")
        contents = [
            types.Content(
                role=m.role,
                parts=[types.Part(text=m.content)],
            )
            for m in request.messages
        ]
        config_kwargs: dict[str, Any] = {"max_output_tokens": request.max_tokens}
        if request.system:
            config_kwargs["system_instruction"] = request.system
        config = types.GenerateContentConfig(**config_kwargs)

        response = await client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            # google-genai stubs type `contents` with an invariant list union,
            # so a plain list[Content] is rejected though valid at runtime.
            contents=contents,  # type: ignore[arg-type]
            config=config,
        )

        usage = response.usage_metadata
        return ChatResponse(
            content=response.text or "",
            model=settings.GEMINI_MODEL,
            input_tokens=usage.prompt_token_count or 0 if usage else 0,
            output_tokens=usage.candidates_token_count or 0 if usage else 0,
        )

    async def run_agent(self, data: AgentRunCreate, triggered_by: str | None = None) -> AgentRun:
        import uuid

        run = AgentRun(
            agent_name=data.agent_name,
            triggered_by=uuid.UUID(triggered_by) if triggered_by else None,
            input_data=data.input_data,
        )
        self._session.add(run)
        await self._session.flush()
        await self._session.refresh(run)

        run.status = AgentRunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        await self._session.flush()

        try:
            result = await self._dispatch_agent(run.agent_name, run.input_data)
            run.status = AgentRunStatus.COMPLETED
            run.output_data = result
        except Exception as exc:
            run.status = AgentRunStatus.FAILED
            run.error = str(exc)
        finally:
            run.completed_at = datetime.now(UTC)

        await self._session.commit()
        return run

    async def _dispatch_agent(self, agent_name: str, input_data: dict[str, Any]) -> dict[str, Any]:
        """
        Invoke the full LangGraph orchestrator, routing the supervisor to the
        requested agent first via the 'next' state key.

        The surrounding `run_agent` already handles AgentRun status writes and
        the session commit, so this method only needs to return the final output.
        """
        from src.domains.intelligence.orchestrator import build_graph

        session_id = str(_uuid.uuid4())
        query = input_data.get("query", input_data.get("intent", agent_name))

        initial_state = {
            "messages": [HumanMessage(content=str(query))],
            "gen_ui_payloads": [],
            "error_messages": [],
            "next": "supervisor",
            "context": {**input_data, "requested_agent": agent_name},
            "session_id": session_id,
            "user_id": input_data.get("user_id"),
            "mode": input_data.get("mode", "insights"),
        }

        try:
            graph = build_graph()
            final_state = await graph.ainvoke(initial_state)
        except Exception as exc:
            logger.error(
                "LangGraph invocation failed",
                agent_name=agent_name,
                session_id=session_id,
                error=str(exc),
            )
            raise

        agents_invoked: list[str] = list({
            m.name
            for m in final_state["messages"]
            if hasattr(m, "name") and m.name
        })

        logger.info(
            "LangGraph dispatch completed",
            agent_name=agent_name,
            session_id=session_id,
            agents_invoked=agents_invoked,
            error_count=len(final_state.get("error_messages", [])),
        )

        return {
            "session_id": session_id,
            "context": final_state.get("context", {}),
            "agents_invoked": agents_invoked,
            "error_messages": final_state.get("error_messages", []),
        }

    # ── Dashboard feeds ───────────────────────────────────────────────────────

    async def record_orchestration_run(
        self,
        *,
        mode: str,
        query: str,
        response: OrchestrationResponse,
        triggered_by: str | None = None,
    ) -> AgentRun:
        """Persist a completed orchestration so the dashboard feeds can read it.

        Stores the narrative answer and the invoked agents; the ``mode`` in
        ``input_data`` is what splits the insights feed from the actions feed.
        """
        agents = response.agents_invoked or []
        run = AgentRun(
            agent_name=agents[0] if agents else "supervisor",
            triggered_by=_uuid.UUID(triggered_by) if triggered_by else None,
            status=AgentRunStatus.COMPLETED,
            input_data={"mode": mode, "query": query},
            output_data={
                "session_id": response.session_id,
                "answer": response.answer,
                "agents_invoked": agents,
            },
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return run

    async def _recent_runs(self, mode: str, limit: int) -> list[AgentRun]:
        # Fetch a small recent window and filter by mode in Python so the query
        # stays portable across the generic JSON column (no JSONB path operators).
        stmt = (
            select(AgentRun)
            .order_by(AgentRun.created_at.desc())
            .limit(max(limit * 5, 50))
        )
        result = await self._session.execute(stmt)
        runs = result.scalars().all()
        filtered = [r for r in runs if (r.input_data or {}).get("mode") == mode]
        return filtered[:limit]

    async def list_insights(self, limit: int = 10) -> list[InsightFeedItem]:
        runs = await self._recent_runs("insights", limit)
        return [insight_from_run(r) for r in runs]

    async def list_actions(self, limit: int = 10) -> list[ActionFeedItem]:
        runs = await self._recent_runs("actions", limit)
        return [action_from_run(r) for r in runs]

    async def list_notifications(self, limit: int = 15) -> list[NotificationItem]:
        """Recent agent runs (any mode) mapped to bell-feed notifications."""
        stmt = (
            select(AgentRun)
            .order_by(AgentRun.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [
            NotificationItem(
                id=r.id,
                agent=r.agent_name,
                message=_run_summary(r),
                created_at=r.created_at,
            )
            for r in result.scalars().all()
        ]

    async def list_agent_telemetry(self) -> list[AgentTelemetry]:
        """Aggregate the recent agent-run log into per-agent run statistics."""
        stmt = (
            select(AgentRun)
            .order_by(AgentRun.created_at.desc())
            .limit(1000)
        )
        result = await self._session.execute(stmt)
        return aggregate_telemetry(list(result.scalars().all()))
