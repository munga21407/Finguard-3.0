"""Agent E IsolationForest model store — pure train/predict/serialize (no DB).

The DB upsert/load (``save_model``/``load_model``) needs Postgres and is covered
by integration tests; the train/predict/score/serialize round-trip is pure and
verified here, including that a *deserialized* model flags anomalies via
``.predict()`` identically to the original (no on-the-fly compute).
"""
from __future__ import annotations

from src.domains.intelligence.ml.model_store import (
    ISOLATION_MIN_SAMPLES,
    deserialize_model,
    predict_is_anomaly,
    score_amount,
    serialize_model,
    train_isolation_forest,
)

# Tight cluster around 100 with one extreme outlier.
_AMOUNTS = [100.0, 101.0, 99.0, 100.5, 98.5, 101.5, 100.2, 5000.0]


def test_too_few_samples_returns_none() -> None:
    assert train_isolation_forest([1.0] * (ISOLATION_MIN_SAMPLES - 1)) is None


def test_trains_with_enough_samples() -> None:
    assert train_isolation_forest([10.0, 11.0, 9.0, 10.5, 10.2, 9.8]) is not None


def test_predict_flags_outlier_not_inlier() -> None:
    model = train_isolation_forest(_AMOUNTS)
    assert model is not None
    assert predict_is_anomaly(model, 5000.0) is True
    assert predict_is_anomaly(model, 100.0) is False


def test_outlier_scores_higher_than_inlier() -> None:
    model = train_isolation_forest(_AMOUNTS)
    assert model is not None
    inlier = score_amount(model, 100.0)
    outlier = score_amount(model, 5000.0)
    assert 0.0 <= inlier <= 1.0
    assert 0.0 <= outlier <= 1.0
    assert outlier > inlier


def test_serialize_roundtrip_preserves_predict_and_score() -> None:
    model = train_isolation_forest(_AMOUNTS)
    assert model is not None
    restored = deserialize_model(serialize_model(model))
    for amt in (100.0, 250.0, 5000.0):
        assert predict_is_anomaly(restored, amt) == predict_is_anomaly(model, amt)
        assert score_amount(restored, amt) == score_amount(model, amt)


def test_serialized_model_infers_without_on_the_fly_fit(monkeypatch) -> None:
    """A deserialized model flags anomalies via `.predict()` without ever fitting.

    Guards the core refactor: inference must run on the persisted weights, never
    re-train on the hot path. We trip a tripwire if `IsolationForest.fit` is
    called after deserialization.
    """
    from sklearn.ensemble import IsolationForest  # noqa: PLC0415

    blob = serialize_model(train_isolation_forest(_AMOUNTS))  # fit happens here, pre-patch
    restored = deserialize_model(blob)

    def _no_fit(*_a, **_k):  # pragma: no cover - only runs on regression
        raise AssertionError("IsolationForest.fit called during inference path")

    monkeypatch.setattr(IsolationForest, "fit", _no_fit)

    assert predict_is_anomaly(restored, 5000.0) is True
    assert predict_is_anomaly(restored, 100.0) is False
