"""Unit test for Agent J (Executive Summarizer) section collection.

``_collect_sections`` decides which agent outputs feed the executive summary —
pure over the context dict. It must include non-empty agent outputs, exclude the
operational/scaffolding keys, and skip empty or scalar values.
"""
from __future__ import annotations

from src.domains.intelligence.agents.j_summarizer import _collect_sections


def test_collect_includes_agent_outputs_excludes_noise() -> None:
    ctx = {
        "forecast": {"runway": "6 Months"},      # real agent output → kept
        "watchdog_analysis": {"state": "HEALTHY"},  # real agent output → kept
        "audit_trail": "session=… ts=…",          # skip key → dropped
        "current_intent": "GENERATE_INSIGHT",      # skip key → dropped
        "empty_dict": {},                           # empty → dropped
        "empty_list": [],                           # empty → dropped
        "scalar_note": "not a dict or list",        # scalar → dropped
    }
    sections = _collect_sections(ctx)
    assert "forecast" in sections
    assert "watchdog_analysis" in sections
    assert "audit_trail" not in sections
    assert "current_intent" not in sections
    assert "empty_dict" not in sections
    assert "empty_list" not in sections
    assert "scalar_note" not in sections


def test_collect_empty_context_returns_empty() -> None:
    assert _collect_sections({}) == {}
