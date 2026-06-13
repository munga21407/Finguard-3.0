"""SSRF guard on the agent HTTP-caller tool."""
from __future__ import annotations

import pytest

from src.domains.intelligence.tools.http_caller import make_http_caller


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost:8000/internal",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://10.0.0.5/",                            # private range
        "file:///etc/passwd",                          # disallowed scheme
        "ftp://example.com/resource",                  # disallowed scheme
    ],
)
@pytest.mark.asyncio
async def test_http_caller_blocks_unsafe_urls(url: str) -> None:
    caller = make_http_caller()
    result = await caller.ainvoke({"method": "GET", "url": url})
    # Blocked requests surface as the tool's error envelope, never a real call.
    assert result["status_code"] == 0
    assert "block" in str(result["data"]).lower()
