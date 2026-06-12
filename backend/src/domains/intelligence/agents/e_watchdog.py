"""
Agent E — Budget Watchdog.

Pipeline:
  1. Fetch recent daily ledger data from PostgreSQL using its own session.
  2. Discretize cash-flow observations for HMM emission symbols.
  3. Run the Forward algorithm to obtain P(S_T | O_1..T) — probability
     distribution over HEALTHY / STABLE / CRITICAL states.
  4. Run Viterbi to decode the most-likely state sequence.
  5. Run IsolationForest on transaction amounts to score outlier severity.
  6. Run rapidfuzz to detect duplicate invoices / receipt scans.
  7. Issue a Verifiable Credential (VC) to trust_log before resolving.
  8. Publish an anomaly event to RabbitMQ when state is CRITICAL.
  9. Ask Gemini for a human-readable summary.
"""
from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field as PydanticField
from rapidfuzz import fuzz
from sklearn.ensemble import IsolationForest  # type: ignore[import-untyped]

from sqlalchemy import text

from src.core.config import settings
from src.core.logging import logger
from src.core.metrics import (
    AGENT_E_ANOMALY_SCORE,
    AGENT_E_STATE_PROBABILITY,
    AGENT_LLM_LATENCY,
    AGENT_LLM_PROCESSING,
)
from src.domains.intelligence.llm_client import get_gemini_client
from src.domains.intelligence.prompts.e_watchdog import WATCHDOG_SYSTEM
from src.domains.intelligence.schemas import (
    CompositeGenUIPayload,
    KeyFinding,
    OrchestratorState,
    WatchdogAnalysis,
)
from src.domains.intelligence.security.vc_issuer import issue_vc
from src.domains.intelligence.tools.event_publisher import make_event_publisher
from src.domains.intelligence.tools.sql_executor import make_sql_executor
from src.infrastructure.database.postgres import AsyncSessionLocal

# ---------------------------------------------------------------------------
# Hidden states
# ---------------------------------------------------------------------------
STATE_LABELS = ["HEALTHY", "STABLE", "CRITICAL"]
STATE_HEALTHY, STATE_STABLE, STATE_CRITICAL = 0, 1, 2

# ---------------------------------------------------------------------------
# HMM parameters
# Emission: Gaussian (mean, std) per state over normalised spending ratio.
# Spending ratio = actual_daily_spend / daily_budget_allowance.
# ---------------------------------------------------------------------------
EMISSION_PARAMS: list[tuple[float, float]] = [
    (0.55, 0.15),   # HEALTHY:  typically ≤70% of budget
    (0.85, 0.12),   # STABLE:   around 85-90% of budget
    (1.20, 0.22),   # CRITICAL: over budget by 20%+
]

# Row-stochastic transition matrix A[from][to]
TRANSITION: np.ndarray = np.array([
    [0.85, 0.13, 0.02],
    [0.10, 0.78, 0.12],
    [0.05, 0.20, 0.75],
], dtype=float)

# Initial state distribution π
INITIAL_PI: np.ndarray = np.array([0.80, 0.15, 0.05])

# Duplicate-detection threshold (rapidfuzz token_sort_ratio, 0-100)
DUPLICATE_THRESHOLD = 88.0

# IsolationForest minimum samples before scoring
ISOLATION_MIN_SAMPLES = 5


# ---------------------------------------------------------------------------
# Gemini structured output schema (local — mirrors KeyFinding for Gemini compat)
# ---------------------------------------------------------------------------

class _WatchdogFinding(BaseModel):
    metric: str
    value: str


class _WatchdogLLMOutput(BaseModel):
    current_state: str
    anomaly_detected: bool
    summary: str
    findings: list[_WatchdogFinding] = PydanticField(default_factory=list)


# ---------------------------------------------------------------------------
# HMM maths
# ---------------------------------------------------------------------------

def _gaussian_log_prob(x: float, mean: float, std: float) -> float:
    return -0.5 * ((x - mean) / std) ** 2 - math.log(std * math.sqrt(2 * math.pi))


def _forward_algorithm(observations: list[float]) -> np.ndarray:
    """
    Forward algorithm — returns the normalised state probability distribution
    P(S_T | O_1..T) at the final time step.

    Uses log-space accumulation to avoid float underflow on long sequences.
    """
    n = len(STATE_LABELS)
    seq_len = len(observations)

    # Alpha in log-space: log P(O_1..t, S_t=s)
    log_alpha = np.full((seq_len, n), -np.inf)

    # Initialisation
    for s in range(n):
        m, sd = EMISSION_PARAMS[s]
        log_alpha[0, s] = (
            math.log(INITIAL_PI[s] + 1e-300) + _gaussian_log_prob(observations[0], m, sd)
        )

    log_trans = np.log(TRANSITION + 1e-300)

    # Recursion
    for t in range(1, seq_len):
        for s in range(n):
            m, sd = EMISSION_PARAMS[s]
            emit = _gaussian_log_prob(observations[t], m, sd)
            log_alpha[t, s] = np.logaddexp.reduce(log_alpha[t - 1] + log_trans[:, s]) + emit

    # Normalise final slice to a probability distribution
    final_log = log_alpha[seq_len - 1]
    # Subtract log-sum-exp for numerical stability
    log_z = np.logaddexp.reduce(final_log)
    probs = np.exp(final_log - log_z)
    return probs


def _viterbi(observations: list[float]) -> list[int]:
    """Viterbi algorithm — returns the most-likely hidden state sequence."""
    n = len(STATE_LABELS)
    seq_len = len(observations)

    log_trans = np.log(TRANSITION + 1e-300)
    log_pi = np.log(INITIAL_PI + 1e-300)

    dp = np.full((seq_len, n), -np.inf)
    backptr = np.zeros((seq_len, n), dtype=int)

    for s in range(n):
        m, sd = EMISSION_PARAMS[s]
        dp[0, s] = log_pi[s] + _gaussian_log_prob(observations[0], m, sd)

    for t in range(1, seq_len):
        for s in range(n):
            m, sd = EMISSION_PARAMS[s]
            emit = _gaussian_log_prob(observations[t], m, sd)
            candidates = dp[t - 1] + log_trans[:, s]
            backptr[t, s] = int(np.argmax(candidates))
            dp[t, s] = candidates[backptr[t, s]] + emit

    path = [int(np.argmax(dp[seq_len - 1]))]
    for t in range(seq_len - 1, 0, -1):
        path.insert(0, backptr[t, path[0]])
    return path


def _weighted_anomaly_score(states: list[int]) -> float:
    """Exponentially-weighted anomaly score; higher weight on recent states."""
    if not states:
        return 0.0
    weights = [math.exp(0.1 * i) for i in range(len(states))]
    total_w = sum(weights)
    # Normalise: max state index is 2, so divide by 2 to bound to [0, 1]
    score = sum(w * s for w, s in zip(weights, states, strict=False)) / (total_w * 2)
    return round(score, 4)


# ---------------------------------------------------------------------------
# IsolationForest anomaly scoring
# ---------------------------------------------------------------------------

def _isolation_score(amounts: list[float]) -> float:
    """
    Fit IsolationForest on historical amounts and score the most recent one.
    Returns a value in [0, 1] where 1 = most anomalous.
    Requires at least ISOLATION_MIN_SAMPLES observations.
    """
    if len(amounts) < ISOLATION_MIN_SAMPLES:
        return 0.0
    x = np.array(amounts, dtype=float).reshape(-1, 1)
    clf = IsolationForest(contamination="auto", random_state=42, n_estimators=100)
    clf.fit(x)
    # decision_function: negative = anomalous, positive = normal
    raw = float(clf.decision_function(x[-1:].reshape(1, -1))[0])
    # Map to [0, 1]: clamp and flip sign
    return round(float(max(0.0, min(1.0, -raw))), 4)


# ---------------------------------------------------------------------------
# rapidfuzz duplicate detection
# ---------------------------------------------------------------------------

def _detect_duplicate(
    candidate: dict[str, Any],
    reference_list: list[dict[str, Any]],
) -> tuple[bool, float]:
    """
    Compare candidate against a list of reference records using token_sort_ratio.
    Returns (is_duplicate, best_match_score_0_to_1).
    """
    c_key = " ".join(str(candidate.get(k, "")) for k in ("vendor", "amount", "invoice_number"))
    best = 0.0
    for ref in reference_list:
        r_key = " ".join(str(ref.get(k, "")) for k in ("vendor", "amount", "invoice_number"))
        score = fuzz.token_sort_ratio(c_key, r_key)
        if score > best:
            best = score
    is_dup = best >= DUPLICATE_THRESHOLD
    return is_dup, round(best / 100.0, 4)


# ---------------------------------------------------------------------------
# Database helpers (own session — thread-isolated per SYSTEM_OVERVIEW.md)
# ---------------------------------------------------------------------------

async def _fetch_spending_ratios(
    account_id: str,
    session: Any,
    period_days: int = 30,
) -> list[float]:
    """Query daily spending vs active budget; return list of ratios."""
    since = (datetime.now(UTC) - timedelta(days=period_days)).isoformat()

    spending_result = await session.execute(
        text("""
            SELECT
                DATE_TRUNC('day', le.created_at) AS day,
                SUM(le.amount)                   AS spent
            FROM ledger_entries le
            WHERE le.account_id = :account_id
              AND le.transaction_type = 'debit'
              AND le.created_at >= :since
            GROUP BY 1
            ORDER BY 1
        """),
        {"account_id": account_id, "since": since},
    )
    rows = spending_result.mappings().all()

    budget_result = await session.execute(
        text("""
            SELECT amount / :period_days AS daily_budget
            FROM budgets
            WHERE period_start <= NOW() AND period_end >= NOW()
            LIMIT 1
        """),
        {"period_days": float(period_days)},
    )
    budget_row = budget_result.mappings().first()
    daily_budget = float(budget_row["daily_budget"]) if budget_row else 1.0

    ratios = [float(r["spent"]) / max(daily_budget, 1e-9) for r in rows]
    return ratios if ratios else [0.5]


async def _fetch_recent_amounts(session: Any, limit: int = 50) -> list[float]:
    """Fetch recent ledger debit amounts for IsolationForest training."""
    executor = make_sql_executor(session)
    rows = await executor.ainvoke({"query": f"""
        SELECT amount
        FROM ledger_entries
        WHERE transaction_type = 'debit'
        ORDER BY created_at DESC
        LIMIT {limit}
    """})
    return [float(r["amount"]) for r in rows]


async def _fetch_recent_invoices(session: Any, limit: int = 30) -> list[dict[str, Any]]:
    """Fetch recent invoice metadata for duplicate detection."""
    executor = make_sql_executor(session)
    rows = await executor.ainvoke({"query": f"""
        SELECT invoice_number, total AS amount,
               customer_id::text AS vendor
        FROM invoices
        ORDER BY created_at DESC
        LIMIT {limit}
    """})
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------

def make_e_watchdog_node(llm: Any = None) -> Any:  # llm kept for signature compatibility
    async def e_watchdog_node(state: OrchestratorState) -> dict[str, Any]:
        account_id: str = state["context"].get("account_id", "")
        period_days: int = state["context"].get("watchdog_period_days", 30)
        mode: str = state.get("mode", "insights")
        candidate_invoice: dict[str, Any] = state["context"].get("candidate_invoice", {})

        # Agent E creates and tears down its own session (thread-isolated pool)
        async with AsyncSessionLocal() as session:
            ratios = await _fetch_spending_ratios(account_id, session, period_days)
            amounts = await _fetch_recent_amounts(session)
            recent_invoices = await _fetch_recent_invoices(session)

        # ── HMM ──────────────────────────────────────────────────────────────
        state_probs: np.ndarray = _forward_algorithm(ratios)
        hidden_states: list[int] = _viterbi(ratios)
        state_labels: list[str] = [STATE_LABELS[s] for s in hidden_states]
        current_state: str = state_labels[-1]
        anomaly_detected: bool = current_state == STATE_LABELS[STATE_CRITICAL]
        anomaly_score: float = _weighted_anomaly_score(hidden_states)

        # Publish HMM results to Prometheus (observed after each watchdog run).
        AGENT_E_ANOMALY_SCORE.set(anomaly_score)
        for label, prob in zip(STATE_LABELS, state_probs.tolist(), strict=False):
            AGENT_E_STATE_PROBABILITY.labels(state=label).set(prob)

        # ── IsolationForest ──────────────────────────────────────────────────
        iso_score: float = _isolation_score(amounts)

        # ── rapidfuzz duplicate detection ─────────────────────────────────
        is_dup, dup_score = _detect_duplicate(candidate_invoice, recent_invoices)

        # ── Verifiable Credential ─────────────────────────────────────────
        # Issue a VC for EVERY invocation in "actions" mode — not only when
        # anomalies are detected.  This creates a complete, tamper-evident
        # audit trail in MongoDB trust_log for every expense event processed
        # by the watchdog consumer, satisfying SOC-2 CC6 / CC7 requirements.
        vc_id: str | None = None
        if mode == "actions":
            try:
                vc_id = await issue_vc(
                    agent_id="E",
                    operation="budget_watchdog_audit",
                    operation_summary=(
                        f"Expense event processed | "
                        f"Budget state: {current_state} | "
                        f"anomaly_detected: {anomaly_detected} | "
                        f"anomaly_score: {anomaly_score:.4f} | "
                        f"isolation_score: {iso_score:.4f} | "
                        f"duplicate_detected: {is_dup} | "
                        f"period_days: {period_days}"
                    ),
                    payload={
                        "account_id": account_id,
                        "current_state": current_state,
                        "state_probabilities": state_probs.tolist(),
                        "anomaly_detected": anomaly_detected,
                        "anomaly_score": anomaly_score,
                        "isolation_score": iso_score,
                        "is_duplicate": is_dup,
                        "duplicate_match_score": dup_score,
                        "period_days": period_days,
                        "observations_count": len(ratios),
                    },
                )
                logger.info(
                    "Agent E: VC issued",
                    vc_id=vc_id,
                    current_state=current_state,
                    anomaly_detected=anomaly_detected,
                )
            except Exception as exc:
                logger.warning("Agent E: VC issuance failed", error=str(exc))

        # ── RabbitMQ event ────────────────────────────────────────────────
        event_published = False
        if (anomaly_detected or iso_score > 0.7) and mode == "actions":
            try:
                publisher = make_event_publisher(mode)
                await publisher.ainvoke({
                    "exchange": "finguard.intelligence",
                    "routing_key": "intelligence.watchdog.anomaly",
                    "payload": {
                        "account_id": account_id,
                        "anomaly_score": anomaly_score,
                        "isolation_score": iso_score,
                        "current_state": current_state,
                        "is_duplicate": is_dup,
                        "vc_id": vc_id,
                        "period_days": period_days,
                    },
                })
                event_published = True
            except Exception as exc:
                logger.warning("Watchdog event publish failed", error=str(exc))

        # ── Gemini structured narrative + findings ────────────────────────
        prompt_data = json.dumps({
            "spending_ratios": ratios[-14:],
            "hidden_states": state_labels[-14:],
            "current_state": current_state,
            "state_probabilities": state_probs.tolist(),
            "anomaly_score": anomaly_score,
            "isolation_score": iso_score,
            "is_duplicate": is_dup,
            "duplicate_match_score": dup_score,
        }, indent=2)
        full_prompt = f"{WATCHDOG_SYSTEM}\n\nAnalysis data:\n{prompt_data}"
        llm_output: _WatchdogLLMOutput | None = None
        try:
            from google.genai import types as genai_types
            _t0 = time.monotonic()
            gemini_resp = await get_gemini_client().aio.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=full_prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_WatchdogLLMOutput,
                ),
            )
            _elapsed = time.monotonic() - _t0
            AGENT_LLM_LATENCY.labels(agent="e_watchdog", model=settings.GEMINI_MODEL).observe(
                _elapsed
            )
            AGENT_LLM_PROCESSING.labels(agent_id="e_watchdog", model=settings.GEMINI_MODEL).observe(
                _elapsed
            )
            llm_output = _WatchdogLLMOutput.model_validate_json(gemini_resp.text or "{}")
        except Exception as exc:
            logger.warning("Agent E: Gemini structured output failed", error=str(exc))

        summary: str
        llm_findings: list[_WatchdogFinding]
        if llm_output is not None:
            summary = llm_output.summary
            llm_findings = llm_output.findings
        else:
            summary = (
                f"Budget state: {current_state} | "
                f"anomaly score: {anomaly_score:.2f} | "
                f"isolation score: {iso_score:.2f}"
            )
            llm_findings = []

        analysis = WatchdogAnalysis(
            account_id=account_id,
            period_days=period_days,
            hidden_states=hidden_states,
            state_labels=state_labels,
            current_state=current_state,
            state_probabilities=state_probs.tolist(),
            anomaly_detected=anomaly_detected,
            anomaly_score=anomaly_score,
            isolation_score=iso_score,
            is_duplicate=is_dup,
            duplicate_match_score=dup_score,
            vc_id=vc_id,
            event_published=event_published,
            summary=summary,
        )

        updated_context = dict(state["context"])
        updated_context["watchdog_analysis"] = analysis.model_dump()
        updated_context["budget_watchdog_result"] = analysis.model_dump()

        # ── CompositeGenUIPayload ─────────────────────────────────────────
        candidate: dict = state["context"].get("candidate_invoice", {})
        composite = CompositeGenUIPayload(
            component_id="BudgetWatchdogMeter",
            props={
                "anomaly_detected": anomaly_detected,
                "anomaly_score": anomaly_score,
                "isolation_score": iso_score,
                "is_duplicate": is_dup,
                "duplicate_match_score": dup_score,
                "vc_id": vc_id,
                "current_state": current_state,
                "state_probabilities": dict(zip(STATE_LABELS, state_probs.tolist())),
                "summary": summary,
                **({"invoice_a": candidate} if candidate else {}),
            },
            findings=[KeyFinding(metric=f.metric, value=f.value) for f in llm_findings],
            fallback_text=(
                f"Watchdog: {current_state} state | "
                f"anomaly score {anomaly_score:.2f} | "
                f"{'Duplicate detected' if is_dup else 'No duplicate'} "
                f"(match {dup_score:.0%})."
            ),
        )

        return {
            "messages": [AIMessage(content=summary, name="e_watchdog")],
            "context": updated_context,
            "gen_ui_payloads": [composite.to_gen_ui_payload()],
        }

    return e_watchdog_node
