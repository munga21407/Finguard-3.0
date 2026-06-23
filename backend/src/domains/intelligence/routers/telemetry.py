"""Frontend operational telemetry ingest.

  POST /genui/error — record a GenUI widget render crash reported by the
                      frontend error boundary (GenUiBoundary).

Generative widgets are rendered from LLM-shaped structures, so a malformed or
unexpected structure can crash a single widget in the browser.  The boundary
catches it and posts here so the failure lands in operational telemetry (logs +
a Prometheus counter) instead of dying silently in the user's console.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, status

from src.core.metrics import GENUI_RENDER_ERRORS
from src.domains.identity.dependencies import CurrentUser
from src.domains.intelligence.schemas import GenUiErrorReport

router = APIRouter()

logger = structlog.get_logger(__name__)


@router.post("/genui/error", status_code=status.HTTP_202_ACCEPTED)
async def report_genui_error(
    report: GenUiErrorReport, current_user: CurrentUser
) -> dict[str, str]:
    """Record a GenUI render crash from the frontend error boundary.

    Fire-and-forget from the client's perspective: it returns 202 and never
    fails the page.  Attribution (who saw the crash) comes from the authenticated
    session, so the report cannot be spoofed for an arbitrary user.
    """
    GENUI_RENDER_ERRORS.labels(component_id=report.component_id).inc()
    logger.warning(
        "genui_render_error",
        component_id=report.component_id,
        message=report.message,
        component_stack=report.component_stack,
        pathname=report.pathname,
        reported_by=str(current_user.id),
    )
    return {"status": "accepted"}
