"""
Intelligence domain router — aggregates the concern-specific sub-routers.

Endpoints (all mounted under ``/api/v1/intelligence`` by ``main.py``):
  POST /ai-insights                            — read-only analysis orchestration
  POST /ai-actions                             — state-changing action orchestration
  POST /intent                                 — focused invoice generation (Agent A + hub writer)
  POST /receipts/scan                          — multimodal receipt OCR
  POST /conversation                           — dual-path: cached read OR force-refresh dispatch
  GET  /conversation/{session_id}/status       — poll background task status
  POST /genui/error                            — frontend GenUI render-crash telemetry
  POST /admin/knowledge-base/ingest            — admin: upload a KRA doc into Tax RAG

The implementations live in the ``routers`` package (``insights``, ``receipts``,
``conversations``, ``telemetry``, ``admin``) with shared helpers in
``routers._common``. This module just composes them so ``main.py`` and every
route path stay unchanged.
"""
from __future__ import annotations

from fastapi import APIRouter

from src.domains.intelligence.routers.admin import router as admin_router
from src.domains.intelligence.routers.admin_tuning import router as admin_tuning_router
from src.domains.intelligence.routers.conversations import router as conversations_router
from src.domains.intelligence.routers.insights import router as insights_router
from src.domains.intelligence.routers.receipts import router as receipts_router
from src.domains.intelligence.routers.telemetry import router as telemetry_router

router = APIRouter()
router.include_router(insights_router)
router.include_router(receipts_router)
router.include_router(conversations_router)
router.include_router(telemetry_router)
router.include_router(admin_router)
router.include_router(admin_tuning_router)
