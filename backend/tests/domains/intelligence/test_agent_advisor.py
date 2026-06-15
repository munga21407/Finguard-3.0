"""Unit test for Agent H (Financial Advisor) role resolution.

``_resolve_user_role`` decides the advice persona. The context-supplied role
takes precedence (lowercased) and an absent user resolves to the safe default
``"viewer"`` without a DB hit.
"""
from __future__ import annotations

import pytest

from src.domains.intelligence.agents.h_advisor import _resolve_user_role


@pytest.mark.asyncio
async def test_context_role_takes_precedence_and_is_lowercased() -> None:
    assert await _resolve_user_role(user_id="anything", ctx_role="ADMIN") == "admin"


@pytest.mark.asyncio
async def test_no_user_defaults_to_viewer() -> None:
    assert await _resolve_user_role(user_id=None, ctx_role=None) == "viewer"
