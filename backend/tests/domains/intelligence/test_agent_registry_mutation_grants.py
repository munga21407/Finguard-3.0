"""Round-2 remediation — declarative mutation-capability matrix:
agent_registry.AgentDescriptor.mutations / mutation_kinds.

A different axis from TOOL_GRANTS (which scopes *what resource* within a
tool); this scopes *what kind of side effect* an agent may have at all
("proposal" / "event" / "direct_write"). Pure unit tests over the declarative
data — no DB/Mongo/network needed.
"""
from __future__ import annotations

from src.domains.intelligence.agent_registry import mutation_kinds


def test_b_is_direct_write_only() -> None:
    """B dispatches a Celery task that persists categories directly — no
    proposal gate (low blast-radius: metadata, not money/stock)."""
    assert mutation_kinds("B") == {"direct_write"}


def test_c_has_both_direct_write_and_proposal() -> None:
    """Pass 1 (deterministic) auto-applies; Pass 2 (LLM-judged) proposes."""
    assert mutation_kinds("C") == {"direct_write", "proposal"}


def test_e_has_event_and_direct_write_never_proposal() -> None:
    """E publishes anomaly events and triggers a background ML fit — neither
    is a financial/inventory write, so E has no 'proposal' capability."""
    kinds = mutation_kinds("E")
    assert kinds == {"event", "direct_write"}
    assert "proposal" not in kinds


def test_k_is_proposal_only() -> None:
    """Every K stock adjustment goes through ProposalService — no direct
    write, no event capability."""
    assert mutation_kinds("K") == {"proposal"}


def test_read_only_and_narrative_agents_have_no_mutation_capability() -> None:
    for agent_id in ("A", "D", "F", "G", "H", "I", "J"):
        assert mutation_kinds(agent_id) == frozenset(), agent_id


def test_unknown_agent_gets_no_mutation_capability_fail_closed() -> None:
    assert mutation_kinds("ZZ") == frozenset()
