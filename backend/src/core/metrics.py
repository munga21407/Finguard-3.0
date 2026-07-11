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
        async with time_llm_call("e_watchdog", settings.LLM_MODEL):
            resp = await client.chat.completions.create(...)
"""
from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from prometheus_client import Counter, Gauge, Histogram

# ── Agent E — HMM + LLM ───────────────────────────────────────────────────────

# End-to-end latency of each the model API call, broken down by agent and model.
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

# Per-agent token consumption. kind ∈ {prompt, completion}. Lets Grafana show
# which agent burns the most context (e.g. Agent B/C dumping ledger_entries).
AGENT_LLM_TOKENS = Counter(
    "agent_llm_tokens_total",
    "LLM tokens consumed per agent and model, split into prompt vs completion",
    labelnames=["agent_id", "model", "kind"],
)

# Frontend GenUI widget render crashes reported via the error boundary, labelled
# by the widget component id so a consistently-failing generative widget is visible.
GENUI_RENDER_ERRORS = Counter(
    "finguard_genui_render_errors_total",
    "GenUI widget render crashes reported from the frontend error boundary",
    labelnames=["component_id"],
)

# Estimated per-agent LLM spend (tokens × configured the model list price). USD.
AGENT_LLM_COST_USD = Counter(
    "agent_llm_cost_usd_total",
    "Estimated LLM cost in USD per agent and model (list-price approximation)",
    labelnames=["agent_id", "model"],
)

# LLM call outcomes per agent. status ∈ {success, error}.
AGENT_LLM_CALLS = Counter(
    "agent_llm_calls_total",
    "LLM calls per agent and model, by outcome",
    labelnames=["agent_id", "model", "status"],
)

# Duration + implicit count of agent tool calls (read-only SQL, outbound HTTP,
# pgvector RAG), labelled by tool, the calling agent, and outcome. The
# histogram's _count per {tool, agent, status} gives both latency and a
# success/error breakdown for error-rate alerting — so no separate counter.
AGENT_TOOL_DURATION = Histogram(
    "agent_tool_duration_seconds",
    "Duration of an agent tool call, per tool, calling agent, and outcome",
    labelnames=["tool", "agent", "status"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
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

# Monotonic count of failed publish attempts (each increments an event's retry_count).
OUTBOX_EVENTS_RETRIED = Counter(
    "finguard_outbox_events_retried_total",
    "Total outbox publish attempts that failed and bumped an event's retry_count",
)

# Monotonic count of events moved to the dead-letter table after exhausting retries.
OUTBOX_EVENTS_DEAD_LETTERED = Counter(
    "finguard_outbox_events_dead_lettered_total",
    "Total outbox events moved to outbox_dead_letters after exceeding OUTBOX_MAX_RETRIES",
)

# ── AMQP consumer (watchdog) ──────────────────────────────────────────────────

# Messages consumed from each aio-pika queue, broken down by disposition.
# status: processed | skipped (duplicate) | error (nack'd)
AMQP_MESSAGES_CONSUMED = Counter(
    "finguard_amqp_messages_consumed_total",
    "Total RabbitMQ messages consumed by the aio-pika consumer processes",
    labelnames=["queue", "status"],
)

# ── Hub writer ────────────────────────────────────────────────────────────────

# Incremented each time the MongoDB intelligence_hub upsert fails.
# Alert rule: rate(finguard_hub_write_errors_total[5m]) > 0
HUB_WRITE_ERRORS = Counter(
    "finguard_hub_write_errors_total",
    "Total MongoDB upsert failures in hub_writer_node — artifacts not persisted",
)

# ── LLM circuit-breaker observability ────────────────────────────────────────

# Incremented each time an LLM call exceeds the 30-second hard timeout.
# Alert rule: rate(finguard_llm_timeouts_total[5m]) > 0.1
LLM_TIMEOUT_COUNTER = Counter(
    "finguard_llm_timeouts_total",
    "Total LLM API calls that exceeded the 30-second hard timeout and "
    "tripped the circuit breaker",
)

# Incremented each time the primary LLM provider fails and the failover client
# routes a call to the backup provider. label ``result`` ∈ {backup_ok, backup_failed}.
# Alert rule: a sustained rate signals the primary (e.g. a scaled-to-zero
# deployment) is unhealthy: rate(finguard_llm_failover_total[5m]) > 0.
LLM_FAILOVER_COUNTER = Counter(
    "finguard_llm_failover_total",
    "Times the primary LLM provider failed and the call was routed to the backup",
    ["capability", "result"],
)

# ── Supervisor routing cost ───────────────────────────────────────────────────

# How each supervisor routing decision was made. method ∈
# {llm, heuristic, cache, requested, single_agent_finish}. Every non-"llm"
# outcome is a saved LLM routing call — track the ratio to size the Sprint-3 win:
#   sum(rate(agent_supervisor_routes_total{method!="llm"}[5m]))
#     / sum(rate(agent_supervisor_routes_total[5m]))
SUPERVISOR_ROUTES = Counter(
    "agent_supervisor_routes_total",
    "Supervisor routing decisions by how the next hop was chosen",
    labelnames=["method"],
)

# ── Helper: LLM call timer ─────────────────────────────────────────────────────


@asynccontextmanager
async def time_llm_call(agent: str, model: str) -> AsyncGenerator[None, None]:
    """
    Async context manager that records LLM wall-clock time in both histograms.

    Usage:
        async with time_llm_call("e_watchdog", settings.LLM_MODEL):
            resp = await client.chat.completions.create(...)
    """
    t0 = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - t0
        AGENT_LLM_LATENCY.labels(agent=agent, model=model).observe(elapsed)
        AGENT_LLM_PROCESSING.labels(agent_id=agent, model=model).observe(elapsed)
