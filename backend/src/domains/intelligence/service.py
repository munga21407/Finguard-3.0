from datetime import UTC, datetime
from typing import Any

from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
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
        config = (
            types.GenerateContentConfig(system_instruction=request.system)
            if request.system
            else types.GenerateContentConfig(max_output_tokens=request.max_tokens)
        )

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
        raise NotImplementedError(f"Agent '{agent_name}' not implemented")
