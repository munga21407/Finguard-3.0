"""
Resilient HTTP client tool for LangGraph agents.

Wraps httpx.AsyncClient with tenacity exponential-backoff retry so transient
network hiccups and rate-limit responses (429) never crash the LangGraph
execution.  Retry policy:
  - Retries on HTTP 429 or any 5xx response.
  - Retries on connection / timeout errors.
  - Up to 4 attempts, doubling wait from 1 s (max 30 s) with full jitter.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog
from langchain_core.tools import tool
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from src.domains.intelligence.observability import traced_tool

logger = structlog.get_logger(__name__)

# Default client-level timeout (connect + read) in seconds.
_DEFAULT_TIMEOUT = 15.0

# SSRF guard — only these schemes are permitted, and the resolved host must be a
# public address.  This tool issues requests on behalf of an LLM-driven agent,
# so an attacker who influences the URL must not be able to reach internal
# services or the cloud metadata endpoint (169.254.169.254).
_ALLOWED_SCHEMES = frozenset({"http", "https"})


class BlockedURLError(ValueError):
    """Raised when a requested URL fails the SSRF safety checks."""


async def _assert_public_url(url: str) -> None:
    """Reject non-http(s) schemes and any host that resolves to a non-public IP."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise BlockedURLError(f"blocked URL scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise BlockedURLError("blocked URL: missing host")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise BlockedURLError(f"blocked URL: DNS resolution failed for {host!r}") from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise BlockedURLError(
                f"blocked URL: {host} resolves to non-public address {ip}"
            )


# ---------------------------------------------------------------------------
# Retry predicate
# ---------------------------------------------------------------------------

def _should_retry(exc: BaseException) -> bool:
    """Retry on 429 / 5xx status codes or on network-level failures."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))


# ---------------------------------------------------------------------------
# Internal retried transport
# ---------------------------------------------------------------------------

# traced_tool sits ABOVE @retry so it records one observation per logical call —
# total time including all retry attempts, and the final success/error outcome.
@traced_tool("http_request")
@retry(
    retry=retry_if_exception(_should_retry),
    stop=stop_after_attempt(4),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
async def _send_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict[str, str],
    params: dict[str, str] | None,
    body: dict[str, Any] | None,
) -> httpx.Response:
    response = await client.request(
        method=method.upper(),
        url=url,
        headers=headers,
        params=params or {},
        json=body,
    )
    response.raise_for_status()
    return response


# ---------------------------------------------------------------------------
# LangGraph-compatible tool factory
# ---------------------------------------------------------------------------

def make_http_caller(timeout: float = _DEFAULT_TIMEOUT) -> Any:
    """
    Return a LangChain @tool that makes resilient outbound HTTP calls.

    Args:
        timeout: Per-request connect + read timeout in seconds.

    Usage inside an agent node::

        caller = make_http_caller()
        result = await caller.ainvoke({
            "method": "GET",
            "url": "https://api.example.com/endpoint",
            "headers": {"Authorization": "Bearer <token>"},
            "params": {"account": "12345"},
        })
    """

    @tool
    async def http_call(
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a resilient outbound HTTP request with automatic retry.

        Retries automatically on HTTP 429 / 5xx responses and network errors
        (up to 4 attempts, exponential back-off with jitter).

        Args:
            method:  HTTP verb — GET, POST, PUT, PATCH, DELETE.
            url:     Absolute URL of the remote endpoint.
            headers: Optional request headers dict (e.g. Authorization).
            params:  Optional URL query-string parameters.
            body:    Optional JSON-serialisable request body (POST/PUT/PATCH).

        Returns:
            dict with keys ``status_code`` (int), ``data`` (parsed JSON or raw
            text), and ``url`` (final resolved URL after redirects).
        """
        resolved_headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **(headers or {}),
        }

        logger.debug(
            "http_caller: outbound request",
            method=method.upper(),
            url=url,
            has_body=body is not None,
        )

        try:
            # SSRF guard: validate the target before any network call.  Redirects
            # are disabled so a public URL cannot 30x-bounce into an internal host.
            await _assert_public_url(url)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await _send_with_retry(
                    client, method, url, resolved_headers, params, body
                )

            logger.debug(
                "http_caller: response received",
                status_code=response.status_code,
                url=str(response.url),
            )

            try:
                data: Any = response.json()
            except json.JSONDecodeError:
                data = response.text

            return {
                "status_code": response.status_code,
                "data": data,
                "url": str(response.url),
            }

        except httpx.HTTPStatusError as exc:
            logger.warning(
                "http_caller: non-retryable HTTP error",
                status_code=exc.response.status_code,
                url=url,
            )
            return {
                "status_code": exc.response.status_code,
                "data": {"error": str(exc)},
                "url": url,
            }
        except Exception as exc:
            logger.error("http_caller: request failed after retries", url=url, error=str(exc))
            return {
                "status_code": 0,
                "data": {"error": str(exc)},
                "url": url,
            }

    return http_call
