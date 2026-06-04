from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from google.genai import types
from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import logger
from src.domains.intelligence.llm_client import get_gemini_client
from src.domains.intelligence.models import AgentRun, AgentRunStatus
from src.domains.intelligence.schemas import AgentRunCreate, ChatRequest, ChatResponse


class IntelligenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def chat(self, request: ChatRequest) -> ChatResponse:
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
            contents=contents,
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
