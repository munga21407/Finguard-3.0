"""
Dependency factories for the intelligence domain.

Provides FastAPI-injectable factories that resolve session handles, the
compiled LangGraph, and per-request context so no global state leaks between
requests.
"""
from __future__ import annotations

from typing import Annotated, AsyncIterator

from fastapi import Depends
from langchain_anthropic import ChatAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.infrastructure.cache.redis import get_redis
from src.infrastructure.database.mongodb import get_mongo_db
from src.infrastructure.database.postgres import get_db

# Re-export so router only imports from here
DBSession = Annotated[AsyncSession, Depends(get_db)]


def get_llm() -> ChatAnthropic:
    """Return a configured Claude model handle."""
    return ChatAnthropic(
        model="claude-sonnet-4-6",
        api_key=settings.ANTHROPIC_API_KEY,
        max_tokens=4096,
    )


LLM = Annotated[ChatAnthropic, Depends(get_llm)]
