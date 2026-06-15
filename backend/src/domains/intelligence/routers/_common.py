"""Shared helpers for the intelligence routers.

Holds the cross-endpoint machinery that previously lived inline in the monolithic
router module: the incremental GenUI fence parser, the Redis idempotency
helpers, and the ``_run_orchestrator`` wrapper used by the synchronous
orchestration endpoints.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

import structlog
from fastapi import HTTPException, status
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from src.domains.intelligence.orchestrator import (
    GraphRecursionError,
    run_graph,
)
from src.domains.intelligence.schemas import (
    GenUIPayload,
    OrchestrationResponse,
)
from src.infrastructure.cache.redis import get_redis

logger = structlog.get_logger(__name__)

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
    raw: str | None = await redis_client.get(  # type: ignore[assignment]
        f"{_IDEM_PREFIX}{idempotency_key}"
    )

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

    except GraphRecursionError as exc:
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
        ) from exc

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
        ) from exc

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
