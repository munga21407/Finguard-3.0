"""
Dependency factories for the intelligence domain.

Provides FastAPI-injectable factories that resolve session handles and the
compiled LangGraph so no global state leaks between requests.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.postgres import get_db

# Re-export so router only imports from here
DBSession = Annotated[AsyncSession, Depends(get_db)]
