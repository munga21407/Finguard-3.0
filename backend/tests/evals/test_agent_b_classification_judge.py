"""Agent B — real-model classification accuracy over the golden set.

Non-blocking / nightly (needs ``RUN_LLM_EVALS=1`` + ``FIREWORKS_API_KEY``): Agent B's
category is produced by Gemini, so this measures accuracy against the immutable
``CLASSIFICATION_CASES`` baseline rather than gating a PR. The deterministic
*guards* (every entry covered, taxonomy-clamped) are pinned separately and DO
block CI in ``tests/domains/intelligence/test_sprint4_guards.py``.
"""
from __future__ import annotations

import os

import pytest

from src.domains.intelligence.agents.b_classifier import _classify_via_llm
from tests.evals.datasets import CLASSIFICATION_CASES

pytestmark = [
    pytest.mark.llm_judge,
    pytest.mark.skipif(
        not os.getenv("RUN_LLM_EVALS"),
        reason="LLM-judge evals are nightly/opt-in — set RUN_LLM_EVALS=1 (needs FIREWORKS_API_KEY)",
    ),
]

# Accuracy floor over the golden set — below this, classification quality has
# regressed enough to investigate (never blocks a PR; nightly signal only).
_MIN_ACCURACY = 0.8


@pytest.mark.asyncio
async def test_classification_accuracy_over_golden_set() -> None:
    entries = [
        {
            "entry_id": case.id,
            "narrative": case.narrative,
            "amount": case.amount,
            "transaction_type": case.transaction_type,
        }
        for case in CLASSIFICATION_CASES
    ]
    expected = {case.id: case.expected_category for case in CLASSIFICATION_CASES}

    results = await _classify_via_llm(entries)
    predicted = {c.entry_id: c.category for c in results}

    correct = sum(1 for eid, exp in expected.items() if predicted.get(eid) == exp)
    accuracy = correct / len(expected)

    misses = {
        eid: (predicted.get(eid), exp) for eid, exp in expected.items()
        if predicted.get(eid) != exp
    }
    assert accuracy >= _MIN_ACCURACY, f"accuracy {accuracy:.0%} < {_MIN_ACCURACY:.0%}; misses={misses}"
