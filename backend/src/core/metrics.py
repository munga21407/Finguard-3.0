"""
Central Prometheus metric registry for FinGuard 3.0.

All custom metrics are defined here and imported by the modules that update
them.  prometheus_client registers each metric in the default registry on
first import, so importing this module anywhere at process startup is
sufficient to make every metric available at /metrics.

Naming convention: finguard_<subsystem>_<unit>_<suffix>
  • _seconds      → latency / duration
  • _total        → monotonic counter
  • _pending      → current backlog gauge

D3 Milestone spec-required names are also defined below under their own
section so dashboard queries that reference those exact names work out of
the box alongside the existing finguard_* series.

Sprint 6 additions:
  • time_llm_call(agent, model) — async context manager that times an LLM
    call and records the result in both AGENT_LLM_LATENCY and AGENT_LLM_PROCESSING.
    Usage:
        async with time_llm_call("e_watchdog", settings.GEMINI_MODEL):
            resp = await client.aio.models.generate_content(...)
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from prometheus_client import Counter, Gauge, Histogram

# ── Agent E — HMM + LLM ───────────────────────────────────────────────────────

# End-to-end latency of each Gemini API call, broken down by agent and model.
# Use histogram_quantile(0.95, ...) in Grafana for P95 SLO tracking.
AGENT_LLM_LATENCY = Histogram(
    "finguard_agent_llm_duration_seconds",
    "Wall-clock time waiting for an LLM response, per agent and model",
    labelnames=["agent", "model"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0],
)

# ── D3-spec canonical names ────────────────────────────────────────────────────
# These use the exact metric names and label names mandated by Milestone D3.
# Both series are updated in parallel with the finguard_* equivalents above so
# every Grafana query referencing either naming convention works.

# Canonical LLM processing histogram — label is `agent_id` per spec.
AGENT_LLM_PROCESSING = Histogram(
    "agent_llm_processing_seconds",
    "LLM API call duration per agent (canonical D3 metric name)",
    labelnames=["agent_id", "model"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0],
)

# Weighted anomaly score from Agent E's HMM/Viterbi pass. Updated each run.
# 0.0 = fully HEALTHY, 1.0 = fully CRITICAL.
AGENT_E_ANOMALY_SCORE = Gauge(
    "finguard_agent_e_hmm_anomaly_score",
    "Agent E HMM weighted anomaly score from the most recent watchdog run (0=healthy, 1=critical)",
)

# Per-state probability vector P(S_T | O_1..T) from the Forward algorithm.
# label: state ∈ {HEALTHY, STABLE, CRITICAL}
AGENT_E_STATE_PROBABILITY = Gauge(
    "finguard_agent_e_state_probability",
    "Agent E HMM posterior state probability from the most recent Forward pass",
    labelnames=["state"],
)

# ── Outbox projector ──────────────────────────────────────────────────────────

# Duration of a single project_once() call (DB read + RabbitMQ publishes).
OUTBOX_SYNC_DURATION = Histogram(
    "finguard_outbox_sync_duration_seconds",
    "Wall-clock time for one outbox projection batch (read unpublished + publish all)",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

# Canonical outbox latency histogram — exact name mandated by Milestone D3.
OUTBOX_SYNC_LATENCY = Histogram(
    "outbox_sync_latency_seconds",
    "Outbox projection batch duration (canonical D3 metric name)",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

# Number of events in the outbox that have not yet been published. A growing
# value indicates the RabbitMQ publisher is falling behind.
OUTBOX_PENDING_EVENTS = Gauge(
    "finguard_outbox_pending_events",
    "Current count of outbox events that have not yet been published to RabbitMQ",
)

# Monotonic count of events successfully forwarded.
OUTBOX_EVENTS_PUBLISHED = Counter(
    "finguard_outbox_events_published_total",
    "Total outbox events successfully published to RabbitMQ since process start",
)

# ── AMQP consumer (watchdog) ──────────────────────────────────────────────────

# Messages consumed from each aio-pika queue, broken down by disposition.
# status: processed | skipped (duplicate) | error (nack'd)
AMQP_MESSAGES_CONSUMED = Counter(
    "finguard_amqp_messages_consumed_total",
    "Total RabbitMQ messages consumed by the aio-pika consumer processes",
    labelnames=["queue", "status"],
)

# ── Helper: LLM call timer ─────────────────────────────────────────────────────


@asynccontextmanager
async def time_llm_call(agent: str, model: str) -> AsyncGenerator[None, None]:
    """
    Async context manager that records LLM wall-clock time in both histograms.

    Usage:
        async with time_llm_call("e_watchdog", settings.GEMINI_MODEL):
            resp = await gemini_client.aio.models.generate_content(...)
    """
    t0 = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - t0
        AGENT_LLM_LATENCY.labels(agent=agent, model=model).observe(elapsed)
        AGENT_LLM_PROCESSING.labels(agent_id=agent, model=model).observe(elapsed)
