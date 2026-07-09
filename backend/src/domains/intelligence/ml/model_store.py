"""Persistence + (de)serialization for Agent E's per-customer IsolationForest.

Previously Agent E fit a fresh ``IsolationForest`` on every scoring call: noisy
(per-call randomness), wasteful (re-fits N estimators on the hot path), and with
no per-customer memory.  This module splits the concern into pure, unit-testable
pieces plus a thin DB layer keyed by ``customer_id`` (``finguard.agent_e_models``):

  * ``train_isolation_forest(amounts)`` — fit a forest (or ``None`` if too few
    samples) with ``contamination="auto"``.
  * ``predict_is_anomaly(model, amount)`` — direct ``.predict()`` inference
    (IsolationForest returns ``-1`` for an outlier, ``1`` for an inlier).
  * ``score_amount(model, amount)`` — map ``decision_function`` to the ``[0, 1]``
    outlier scale the watchdog already publishes downstream.
  * ``serialize_model`` / ``deserialize_model`` — joblib round-trip to bytes.

``save_model`` / ``load_model`` upsert and read the ``agent_e_models`` row for a
customer.
"""
from __future__ import annotations

import io
import uuid
from typing import TYPE_CHECKING

import joblib  # type: ignore[import-untyped]
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.intelligence.models import AgentEModel

if TYPE_CHECKING:  # sklearn is heavy; import it lazily at call time (see below)
    from sklearn.ensemble import IsolationForest  # type: ignore[import-untyped]

MODEL_TYPE = "isolation_forest"

# Minimum observations before a forest is worth fitting (matches the legacy
# inline threshold).  Below this, the watchdog stays on its on-the-fly path.
ISOLATION_MIN_SAMPLES = 5
_N_ESTIMATORS = 100
_RANDOM_STATE = 42


def train_isolation_forest(amounts: list[float]) -> IsolationForest | None:
    """Fit an IsolationForest on historical amounts, or ``None`` if too few."""
    from sklearn.ensemble import IsolationForest  # noqa: PLC0415

    if len(amounts) < ISOLATION_MIN_SAMPLES:
        return None
    x = np.array(amounts, dtype=float).reshape(-1, 1)
    clf = IsolationForest(
        contamination="auto", random_state=_RANDOM_STATE, n_estimators=_N_ESTIMATORS
    )
    clf.fit(x)
    return clf


def predict_is_anomaly(model: IsolationForest, amount: float) -> bool:
    """Direct ``.predict()`` inference — ``True`` when the amount is an outlier.

    IsolationForest's ``predict`` returns ``-1`` for anomalies and ``1`` for
    inliers; we surface that as a boolean for the watchdog.
    """
    label = int(model.predict(np.array([[float(amount)]]))[0])
    return label == -1


def score_amount(model: IsolationForest, amount: float) -> float:
    """Score one amount in ``[0, 1]`` where 1 = most anomalous.

    ``decision_function`` is negative for outliers and positive for inliers, so
    we flip the sign and clamp — the mapping the legacy ``_isolation_score``
    applied, kept so downstream thresholds/props are unchanged.
    """
    raw = float(model.decision_function(np.array([[float(amount)]]))[0])
    return round(float(max(0.0, min(1.0, -raw))), 4)


def serialize_model(model: IsolationForest) -> bytes:
    buf = io.BytesIO()
    joblib.dump(model, buf)
    return buf.getvalue()


def deserialize_model(payload: bytes) -> IsolationForest:
    return joblib.load(io.BytesIO(payload))


async def save_model(
    session: AsyncSession,
    customer_id: uuid.UUID,
    model: IsolationForest,
    n_samples: int,
) -> None:
    """Upsert a serialized model for ``customer_id`` (bumps version on update)."""
    existing = await session.scalar(
        select(AgentEModel).where(AgentEModel.customer_id == customer_id)
    )
    payload = serialize_model(model)
    if existing is None:
        session.add(
            AgentEModel(
                customer_id=customer_id,
                model_type=MODEL_TYPE,
                payload=payload,
                n_samples=n_samples,
                version=1,
            )
        )
    else:
        existing.payload = payload
        existing.n_samples = n_samples
        existing.version += 1
    await session.commit()


async def load_model(
    session: AsyncSession, customer_id: uuid.UUID
) -> tuple[IsolationForest, int] | None:
    """Return ``(model, n_samples)`` for ``customer_id`` or ``None`` if absent."""
    row = await session.scalar(
        select(AgentEModel).where(AgentEModel.customer_id == customer_id)
    )
    if row is None:
        return None
    return deserialize_model(row.payload), row.n_samples
