from datetime import datetime, timezone

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.domains.intelligence.models import AgentRun, AgentRunStatus
from src.domains.intelligence.schemas import AgentRunCreate, ChatRequest, ChatResponse


class IntelligenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        response = self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=request.max_tokens,
            system=request.system or "You are a helpful financial assistant for Finguard.",
            messages=[{"role": m.role, "content": m.content} for m in request.messages],
        )
        return ChatResponse(
            content=response.content[0].text,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
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
        run.started_at = datetime.now(timezone.utc)
        await self._session.flush()

        try:
            result = await self._dispatch_agent(run.agent_name, run.input_data)
            run.status = AgentRunStatus.COMPLETED
            run.output_data = result
        except Exception as exc:
            run.status = AgentRunStatus.FAILED
            run.error = str(exc)
        finally:
            run.completed_at = datetime.now(timezone.utc)

        await self._session.commit()
        return run

    async def _dispatch_agent(self, agent_name: str, input_data: dict) -> dict:
        # TODO: implement individual agent handlers
        raise NotImplementedError(f"Agent '{agent_name}' not implemented")
