"""SSRF guard on the agent HTTP-caller tool."""
from __future__ import annotations

import socket

import pytest

from src.domains.intelligence.tools import http_caller
from src.domains.intelligence.tools.http_caller import (
    BlockedURLError,
    _resolve_and_pin,
    make_http_caller,
)


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


def _fake_getaddrinfo(addresses: list[str]):
    """Build a socket.getaddrinfo stand-in returning the given IP literals."""

    def _impl(host, port, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port))
            for addr in addresses
        ]

    return _impl


@pytest.mark.asyncio
async def test_resolve_and_pin_blocks_rebinding_to_internal(monkeypatch) -> None:  # noqa: ANN001
    """A name resolving to an internal address is rejected even if it looks public.

    Pins the DNS-rebinding bypass: ``_resolve_and_pin`` validates the resolved
    address itself rather than trusting the hostname, so a public-looking name
    that answers with 169.254.169.254 (cloud metadata) is blocked.
    """
    monkeypatch.setattr(
        http_caller.socket,
        "getaddrinfo",
        _fake_getaddrinfo(["169.254.169.254"]),
    )
    with pytest.raises(BlockedURLError):
        await _resolve_and_pin("https://totally-legit.example.com/data")


@pytest.mark.asyncio
async def test_resolve_and_pin_blocks_mixed_public_and_internal(monkeypatch) -> None:  # noqa: ANN001
    """A host answering with BOTH a public and an internal A record is rejected.

    Every resolved address must clear the guard — otherwise an attacker races
    the connection toward the unvalidated internal record.
    """
    monkeypatch.setattr(
        http_caller.socket,
        "getaddrinfo",
        _fake_getaddrinfo(["8.8.8.8", "127.0.0.1"]),
    )
    with pytest.raises(BlockedURLError):
        await _resolve_and_pin("https://mixed.example.com/data")


@pytest.mark.asyncio
async def test_resolve_and_pin_returns_validated_public_ip(monkeypatch) -> None:  # noqa: ANN001
    """A wholly-public resolution returns the pinned IP the socket will dial."""
    monkeypatch.setattr(
        http_caller.socket,
        "getaddrinfo",
        _fake_getaddrinfo(["93.184.216.34"]),
    )
    pinned = await _resolve_and_pin("https://example.com/path")
    assert pinned == "93.184.216.34"
