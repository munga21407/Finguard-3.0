"""Per-request context (request id + client IP) for the audit trail.

A lightweight ``contextvars``-backed store populated once per request by
:class:`RequestContextMiddleware`, so any code deep in the call stack — notably
``AuditService.record`` — can attach *who/where* metadata without threading a
``Request`` object through every signature.

The request id is also bound into structlog's contextvars, so the JSON
operational logs and the durable audit rows share the same ``request_id`` and
can be correlated after the fact.
"""
from __future__ import annotations

import contextvars
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_REQUEST_ID_HEADER = "x-request-id"

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "audit_request_id", default=None
)
_client_ip: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "audit_client_ip", default=None
)


def get_request_id() -> str | None:
    """The current request's id, or ``None`` outside a request (e.g. workers)."""
    return _request_id.get()


def get_client_ip() -> str | None:
    """Best-effort source IP of the current request, or ``None`` outside one."""
    return _client_ip.get()


def _resolve_client_ip(request: Request) -> str | None:
    """Left-most ``X-Forwarded-For`` entry (the real client behind nginx), else
    the direct peer. Mirrors ``identity.router._client_ip`` so audit rows and the
    login-lockout key agree on what "the client" is."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else None


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Populate the request-context vars and echo the request id back.

    Honours an inbound ``X-Request-ID`` (set by nginx / a calling service) so a
    request can be traced end-to-end; otherwise mints a fresh uuid4. The id is
    bound into structlog so every log line in the request carries it, and is
    returned in the response ``X-Request-ID`` header for client-side correlation.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get(_REQUEST_ID_HEADER) or uuid.uuid4().hex
        ip = _resolve_client_ip(request)

        id_token = _request_id.set(request_id)
        ip_token = _client_ip.set(ip)
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
            _client_ip.reset(ip_token)
            _request_id.reset(id_token)

        response.headers[_REQUEST_ID_HEADER] = request_id
        return response
