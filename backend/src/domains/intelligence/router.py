"""
Intelligence domain router.

Endpoints:
  POST /api/v1/intelligence/ai-insights   — read-only analysis orchestration
  POST /api/v1/intelligence/ai-actions    — state-changing action orchestration
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from langchain_core.messages import HumanMessage

from src.domains.intelligence.dependencies import LLM, get_llm
from src.domains.intelligence.orchestrator import build_graph
from src.domains.intelligence.schemas import (
    ActionRequest,
    InsightRequest,
    OrchestrationResponse,
)

router = APIRouter()


async def _run_orchestrator(
    initial_message: str,
    context: dict,
    user_id: str | None,
    mode: str,
    llm,
) -> OrchestrationResponse:
    session_id = str(uuid.uuid4())
    graph = build_graph(llm)

    initial_state = {
        "messages": [HumanMessage(content=initial_message)],
        "next": "supervisor",
        "context": context,
        "session_id": session_id,
        "user_id": user_id,
        "mode": mode,
    }

    final_state = await graph.ainvoke(initial_state)

    # Collect the names of all agents that spoke (exclude supervisor)
    agents_invoked = list({
        m.name
        for m in final_state["messages"]
        if hasattr(m, "name") and m.name and m.name != "supervisor"
    })

    # The last non-supervisor AI message is the final answer
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


@router.post("/ai-insights", response_model=OrchestrationResponse)
async def ai_insights(request: InsightRequest, llm: LLM) -> OrchestrationResponse:
    """Run the multi-agent orchestrator in read-only insights mode."""
    return await _run_orchestrator(
        initial_message=request.query,
        context=request.context,
        user_id=request.user_id,
        mode="insights",
        llm=llm,
    )


@router.post("/ai-actions", response_model=OrchestrationResponse)
async def ai_actions(request: ActionRequest, llm: LLM) -> OrchestrationResponse:
    """Run the multi-agent orchestrator in actions mode (may publish events)."""
    return await _run_orchestrator(
        initial_message=request.intent,
        context=request.payload,
        user_id=request.user_id,
        mode="actions",
        llm=llm,
    )
