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
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

import httpcore
import httpx
import structlog
from httpcore._backends.auto import AutoBackend
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


def _assert_ip_public(ip_str: str, host: str) -> None:
    """Raise BlockedURLError if ``ip_str`` is not a routable public address."""
    ip = ipaddress.ip_address(ip_str)
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


async def _resolve_and_pin(url: str) -> str:
    """Validate the URL, resolve DNS once, and return a single public IP to pin to.

    Returning the validated IP — rather than only asserting and letting httpx
    re-resolve the hostname when it connects — closes the DNS-rebinding TOCTOU
    hole.  Without pinning, an attacker-controlled name can answer with a public
    IP for this check and an internal IP (127.0.0.1, 169.254.169.254, …) for the
    request httpx makes microseconds later.  The caller feeds the returned IP to
    a pinned transport so the socket connects to exactly the address we cleared.

    Every address the resolver returns is validated: a host that answers with a
    mix of public and internal addresses is rejected outright rather than raced.
    """
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

    resolved_ips = [str(info[4][0]) for info in infos]
    if not resolved_ips:
        raise BlockedURLError(f"blocked URL: no addresses resolved for {host!r}")
    for ip_str in resolved_ips:
        _assert_ip_public(ip_str, host)

    # All resolved addresses are public; pin the first so the actual connection
    # cannot re-resolve to a different (rebind-injected) address.
    return resolved_ips[0]


class _PinnedIPBackend(httpcore.AsyncNetworkBackend):
    """Network backend that connects every TCP socket to a pre-validated IP.

    httpcore normally re-resolves the hostname when it opens a connection; this
    backend ignores the hostname and dials the IP that ``_resolve_and_pin``
    already cleared, defeating DNS rebinding.  TLS is unaffected — httpcore still
    drives SNI and certificate verification from the URL's original hostname, so
    HTTPS connections to the pinned IP are validated against the real host.
    """

    def __init__(self, pinned_ip: str) -> None:
        self._pinned_ip = pinned_ip
        self._delegate = AutoBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        return await self._delegate.connect_tcp(
            self._pinned_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise BlockedURLError("blocked URL: unix-socket connections are not permitted")

    async def sleep(self, seconds: float) -> None:
        await self._delegate.sleep(seconds)


class _PinnedTransport(httpx.AsyncHTTPTransport):
    """AsyncHTTPTransport whose connection pool dials only one validated IP."""

    def __init__(self, pinned_ip: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # httpx builds an httpcore.AsyncConnectionPool in the parent __init__;
        # swap its network backend for the IP-pinned one so no re-resolution
        # can occur between our validation and the socket connect.
        self._pool._network_backend = _PinnedIPBackend(pinned_ip)


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
            # SSRF guard: resolve + validate the target once, then pin the socket
            # to the cleared IP so DNS rebinding cannot swap in an internal
            # address after the check.  Redirects stay disabled so a public URL
            # cannot 30x-bounce elsewhere either.
            pinned_ip = await _resolve_and_pin(url)
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                transport=_PinnedTransport(pinned_ip, retries=0),
            ) as client:
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
