"""Tool-level observability for the intelligence domain.

`traced_tool` wraps an agent's high-risk tool calls — read-only Text-to-SQL,
outbound HTTP (Daraja / CBK / Metropol), and pgvector RAG — to record their
latency and success/error outcome on the `/metrics` endpoint, attributed to the
calling agent via the same `current_agent_id` contextvar used for LLM metrics.

Standard logs tell you a tool ran; these metrics tell you it took 4 seconds or
that the Daraja call has started failing — exactly the signals that are
invisible in per-line logs across a multi-agent graph.
"""
from __future__ import annotations

import functools
import time
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

from src.core.metrics import AGENT_TOOL_DURATION
from src.domains.intelligence.llm_client import current_agent_id

_P = ParamSpec("_P")
_R = TypeVar("_R")


def traced_tool(
    tool_name: str,
) -> Callable[[Callable[_P, Awaitable[_R]]], Callable[_P, Awaitable[_R]]]:
    """Decorate an async tool function to record per-call latency and outcome.

    Records into `AGENT_TOOL_DURATION{tool, agent, status}` where ``agent`` is the
    node currently executing (``"unknown"`` outside the graph, e.g. a Celery
    batch task) and ``status`` is ``"success"`` or ``"error"``. The duration is
    observed even on failure (a hung call shows up as a long ``error`` sample),
    and the original exception is always re-raised — telemetry is transparent to
    the caller.
    """

    def decorator(func: Callable[_P, Awaitable[_R]]) -> Callable[_P, Awaitable[_R]]:
        @functools.wraps(func)
        async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            agent = current_agent_id()
            start = time.monotonic()
            status = "success"
            try:
                return await func(*args, **kwargs)
            except BaseException:
                status = "error"
                raise
            finally:
                AGENT_TOOL_DURATION.labels(
                    tool=tool_name, agent=agent, status=status
                ).observe(time.monotonic() - start)

        return wrapper

    return decorator
