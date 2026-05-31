"""
Agent E — Budget Watchdog.

Pipeline:
  1. Fetch recent daily spending from PostgreSQL (via sql_executor tool).
  2. Normalise against the active budget to get spending ratios.
  3. Run a Gaussian Hidden Markov Model (Viterbi) to decode the hidden state
     sequence (NORMAL / ELEVATED / ANOMALOUS).
  4. If the current state is ANOMALOUS, publish a VC-issuer hook event via
     RabbitMQ so downstream systems (card issuer, alerting) can react.
  5. Ask Claude to write a human-readable assessment.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.domains.intelligence.prompts.e_watchdog import WATCHDOG_SYSTEM
from src.domains.intelligence.schemas import OrchestratorState, WatchdogAnalysis
from src.domains.intelligence.tools.event_publisher import make_event_publisher
from src.domains.intelligence.tools.sql_executor import make_sql_executor
from src.infrastructure.database.postgres import AsyncSessionLocal

# ---------------------------------------------------------------------------
# HMM parameters (3 hidden states: NORMAL=0, ELEVATED=1, ANOMALOUS=2)
# Spending ratio thresholds that define each emission distribution (Gaussian).
# ---------------------------------------------------------------------------
STATE_LABELS = ["NORMAL", "ELEVATED", "ANOMALOUS"]

# Gaussian emission: (mean, std) for each state
EMISSION_PARAMS: list[tuple[float, float]] = [
    (0.60, 0.15),   # NORMAL:    typically 60% of budget ± 15%
    (0.90, 0.12),   # ELEVATED:  around 90% of budget
    (1.25, 0.20),   # ANOMALOUS: over budget by 25%+
]

# Row-stochastic transition matrix  [from_state][to_state]
TRANSITION = np.array([
    [0.85, 0.13, 0.02],
    [0.10, 0.78, 0.12],
    [0.05, 0.20, 0.75],
], dtype=float)

# Initial state distribution
INITIAL_PI = np.array([0.80, 0.15, 0.05])


def _gaussian_log_prob(x: float, mean: float, std: float) -> float:
    return -0.5 * ((x - mean) / std) ** 2 - math.log(std * math.sqrt(2 * math.pi))


def _viterbi(observations: list[float]) -> list[int]:
    """Viterbi algorithm returning the most-likely hidden state sequence."""
    n_states = len(STATE_LABELS)
    T = len(observations)

    # Log probabilities
    log_trans = np.log(TRANSITION + 1e-10)
    log_pi = np.log(INITIAL_PI + 1e-10)

    # dp[t][s] = max log-prob of state sequence ending in state s at time t
    dp = np.full((T, n_states), -np.inf)
    backptr = np.zeros((T, n_states), dtype=int)

    # Initialise
    for s in range(n_states):
        mean, std = EMISSION_PARAMS[s]
        dp[0][s] = log_pi[s] + _gaussian_log_prob(observations[0], mean, std)

    # Forward pass
    for t in range(1, T):
        for s in range(n_states):
            mean, std = EMISSION_PARAMS[s]
            emit = _gaussian_log_prob(observations[t], mean, std)
            candidates = dp[t - 1] + log_trans[:, s]
            backptr[t][s] = int(np.argmax(candidates))
            dp[t][s] = candidates[backptr[t][s]] + emit

    # Backtrack
    path = [int(np.argmax(dp[T - 1]))]
    for t in range(T - 1, 0, -1):
        path.insert(0, backptr[t][path[0]])
    return path


async def _fetch_spending_ratios(
    account_id: str,
    session: Any,
    period_days: int = 30,
) -> list[float]:
    """Query daily spending vs budget and return ratio list."""
    since = (datetime.now(timezone.utc) - timedelta(days=period_days)).isoformat()
    sql = f"""
        SELECT
            DATE_TRUNC('day', le.created_at) AS day,
            SUM(le.amount)                   AS spent
        FROM ledger_entries le
        WHERE le.account_id = '{account_id}'
          AND le.transaction_type = 'debit'
          AND le.created_at >= '{since}'
        GROUP BY 1
        ORDER BY 1
    """
    executor = make_sql_executor(session)
    rows = await executor.ainvoke({"query": sql})

    # Fetch budget for this account
    budget_sql = f"""
        SELECT amount / {period_days}.0 AS daily_budget
        FROM budgets
        WHERE period_start <= NOW() AND period_end >= NOW()
        LIMIT 1
    """
    budget_rows = await executor.ainvoke({"query": budget_sql})
    daily_budget = float(budget_rows[0]["daily_budget"]) if budget_rows else 1.0

    ratios = [float(r["spent"]) / max(daily_budget, 1.0) for r in rows]
    return ratios if ratios else [0.5]  # default to NORMAL if no data yet


def _compute_anomaly_score(states: list[int]) -> float:
    """Weighted score: higher weight on recent states (exponential decay)."""
    if not states:
        return 0.0
    weights = [math.exp(0.1 * i) for i in range(len(states))]
    total_w = sum(weights)
    score = sum(w * s for w, s in zip(weights, states)) / (total_w * 2)  # normalise to 0-1
    return round(score, 4)


def make_e_watchdog_node(llm: ChatAnthropic):
    async def e_watchdog_node(state: OrchestratorState) -> dict:
        account_id: str = state["context"].get("account_id", "")
        period_days: int = state["context"].get("watchdog_period_days", 30)
        mode: str = state.get("mode", "insights")

        async with AsyncSessionLocal() as session:
            ratios = await _fetch_spending_ratios(account_id, session, period_days)

        # Run HMM decoder
        hidden_states = _viterbi(ratios)
        state_labels = [STATE_LABELS[s] for s in hidden_states]
        current_state = state_labels[-1]
        anomaly_detected = current_state == "ANOMALOUS"
        anomaly_score = _compute_anomaly_score(hidden_states)

        # Publish VC-issuer hook if anomaly detected and in actions mode
        event_published = False
        if anomaly_detected and mode == "actions":
            publisher = make_event_publisher(mode)
            await publisher.ainvoke({
                "exchange": "finguard.intelligence",
                "routing_key": "intelligence.watchdog.anomaly",
                "payload": {
                    "account_id": account_id,
                    "anomaly_score": anomaly_score,
                    "current_state": current_state,
                    "period_days": period_days,
                },
            })
            event_published = True

        # Ask Claude for a human-readable assessment
        prompt_data = json.dumps({
            "spending_ratios": ratios[-14:],   # last 14 days only
            "hidden_states": state_labels[-14:],
            "current_state": current_state,
            "anomaly_score": anomaly_score,
        }, indent=2)
        response = await llm.ainvoke([
            SystemMessage(content=WATCHDOG_SYSTEM),
            HumanMessage(content=f"Analysis data:\n{prompt_data}"),
        ])

        try:
            raw = response.content
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json").strip()
            llm_output = json.loads(raw)
            summary = llm_output.get("summary", response.content)
        except json.JSONDecodeError:
            summary = response.content

        analysis = WatchdogAnalysis(
            account_id=account_id,
            period_days=period_days,
            hidden_states=hidden_states,
            state_labels=state_labels,
            current_state=current_state,
            anomaly_detected=anomaly_detected,
            anomaly_score=anomaly_score,
            event_published=event_published,
            summary=summary,
        )
        state["context"]["watchdog_analysis"] = analysis.model_dump()

        return {
            "messages": [AIMessage(content=summary, name="e_watchdog")],
            "context": state["context"],
        }

    return e_watchdog_node
