"""Intelligence HTTP routers, split by concern.

``router.py`` aggregates these sub-routers into the single ``router`` that
``main.py`` mounts under ``/api/v1/intelligence``:

- :mod:`insights`       — orchestration endpoints (ai-insights / ai-actions / intent)
- :mod:`receipts`       — multimodal receipt OCR scan
- :mod:`conversations`  — dual-path cached-read / background-refresh + status polling
- :mod:`_common`        — shared GenUI parsing, idempotency, and orchestrator helpers
"""
