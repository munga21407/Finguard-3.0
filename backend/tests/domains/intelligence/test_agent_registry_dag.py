"""A2A P2 — execution-DAG contract + ``build_plan`` unit tests.

Two concerns:

1. **Registry contract** — the shipped ``consumes`` edges form a valid DAG:
   every ``Dependency.key`` has a producer, and the whole graph is acyclic. A
   violation here is a registry *bug*, so these guard future edits.
2. **``build_plan`` behaviour** — transitive required-closure, parallel staging,
   optional deps excluded from ordering, and cycle/unknown-target errors.

All hermetic — the registry is pure data, no DB or LLM.
"""
from __future__ import annotations

import dataclasses

import pytest

from src.domains.intelligence import agent_registry
from src.domains.intelligence.agent_registry import (
    AGENT_REGISTRY,
    Dependency,
    DependencyError,
    build_plan,
)

# context_keys actually produced by some agent — the valid dependency targets.
_PRODUCED_KEYS = {d.context_key for d in AGENT_REGISTRY}


# ── 1. Registry contract ──────────────────────────────────────────────────────

def test_every_dependency_key_has_a_producer() -> None:
    """No ``consumes`` edge may point at a key no agent produces (dangling dep)."""
    for desc in AGENT_REGISTRY:
        for dep in desc.consumes:
            assert dep.key in _PRODUCED_KEYS, (
                f"agent {desc.agent_id} consumes unknown key {dep.key!r}"
            )


def test_full_registry_dag_is_acyclic() -> None:
    """Planning every agent at once must not raise — proves the graph is acyclic."""
    plan = build_plan({d.agent_id for d in AGENT_REGISTRY})
    # Every agent appears exactly once across the stages.
    planned = [a for stage in plan for a in stage]
    assert sorted(planned) == sorted(d.agent_id for d in AGENT_REGISTRY)
    assert len(planned) == len(set(planned)), "an agent was staged twice"


def test_no_agent_depends_on_itself() -> None:
    for desc in AGENT_REGISTRY:
        assert desc.context_key not in {dep.key for dep in desc.consumes}


# ── 2. build_plan behaviour ───────────────────────────────────────────────────

def test_single_target_no_deps_is_one_stage() -> None:
    # Agent B (classifier) consumes nothing.
    assert build_plan({"B"}) == [{"B"}]


def test_required_dep_pulled_in_and_ordered_before_consumer() -> None:
    # G requires forecast (D); audit (F) is optional and must NOT be pulled in.
    plan = build_plan({"G"})
    assert plan == [{"D"}, {"G"}]


def test_optional_dep_not_forced_into_plan() -> None:
    plan = build_plan({"G"})
    assert "F" not in {a for stage in plan for a in stage}


def test_independent_targets_share_one_parallel_stage() -> None:
    # D and F have no required deps → both land in stage 0 (run concurrently);
    # G (requires D) follows. Mirrors the board-pack example in §5 of the doc.
    plan = build_plan({"D", "F", "G"})
    assert plan[0] == {"D", "F"}
    assert plan[1] == {"G"}
    assert len(plan) == 2


def test_optional_producer_as_explicit_target_does_not_gate_consumer() -> None:
    # F is only an *optional* dep of G, so even when both are targets G must not
    # be ordered after F — they may run in the same stage as D.
    plan = build_plan({"F", "G"})
    stage_of = {a: i for i, stage in enumerate(plan) for a in stage}
    assert stage_of["G"] > stage_of["D"]      # required edge respected
    assert stage_of["F"] <= stage_of["G"]     # optional edge does not push G later


def test_unknown_target_raises() -> None:
    with pytest.raises(DependencyError):
        build_plan({"Z"})


def test_dangling_dependency_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = dataclasses.replace(
        agent_registry._BY_AGENT["G"],
        consumes=(Dependency("no_such_key", required=True),),
    )
    patched = tuple(bad if d.agent_id == "G" else d for d in AGENT_REGISTRY)
    monkeypatch.setattr(agent_registry, "AGENT_REGISTRY", patched)
    monkeypatch.setattr(
        agent_registry, "_BY_AGENT", {d.agent_id: d for d in patched}
    )
    monkeypatch.setattr(
        agent_registry, "_BY_KEY", {d.context_key: d for d in patched}
    )
    with pytest.raises(DependencyError):
        build_plan({"G"})


def test_cycle_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Forge a cycle: D requires G's output and G requires D's → unsatisfiable.
    d_desc = agent_registry._BY_AGENT["D"]
    g_desc = agent_registry._BY_AGENT["G"]
    d_cyc = dataclasses.replace(
        d_desc, consumes=(Dependency("credit_strategy_result", required=True),)
    )
    g_cyc = dataclasses.replace(
        g_desc, consumes=(Dependency("forecast", required=True),)
    )
    patched = tuple(
        {"D": d_cyc, "G": g_cyc}.get(d.agent_id, d) for d in AGENT_REGISTRY
    )
    monkeypatch.setattr(agent_registry, "AGENT_REGISTRY", patched)
    monkeypatch.setattr(
        agent_registry, "_BY_AGENT", {d.agent_id: d for d in patched}
    )
    monkeypatch.setattr(
        agent_registry, "_BY_KEY", {d.context_key: d for d in patched}
    )
    with pytest.raises(DependencyError, match="cycle"):
        build_plan({"G"})
