"""
Intelligence domain router.

Endpoints:
  POST /api/v1/intelligence/ai-insights  — read-only analysis orchestration
  POST /api/v1/intelligence/ai-actions   — state-changing action orchestration
  POST /api/v1/intelligence/intent       — focused invoice generation (Agent A + hub writer)
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from langchain_core.messages import HumanMessage

from src.domains.intelligence.orchestrator import build_graph, build_invoice_graph
from src.domains.intelligence.schemas import (
    ActionRequest,
    InsightRequest,
    IntentRequest,
    IntentResponse,
    OrchestrationResponse,
)

router = APIRouter()


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
