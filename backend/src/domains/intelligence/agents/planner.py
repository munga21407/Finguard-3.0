"""Planner node — multi-domain DAG execution (A2A P4).

When the supervisor names ≥2 target agents (``context["_planner_targets"]``), the
graph routes here instead of to a single agent. The planner turns those targets
into a staged dependency DAG (``agent_registry.build_plan`` + a terminal Agent J
summary) and fans each stage out in parallel via LangGraph ``Send``. Between
stages control returns here (``hub_writer`` routes back) to advance the pointer.

Design (docs/A2A_PROTOCOL.md §4.4):
  * **Criticality** — before a stage runs, each agent is checked against the
    accumulated context: a *required* dependency that no upstream stage produced
    → the agent is **skipped** (its output would be a hallucination); an agent
    whose own output is already present → skipped as ``already_produced`` (makes
    the planner idempotent and replan-safe). Optional deps never gate.
  * **Empty-stage collapse** — the node advances past fully-skipped stages so the
    dispatch edge only ever sees a non-empty batch or a truly drained plan.
  * **Replan** — a consumer may append ``context["_replan_targets"]``; when the
    plan drains, the planner merges them and rebuilds (bounded by
    ``settings.A2A_MAX_REPLANS``). Already-produced agents are skipped on rebuild.

All planner bookkeeping keys are ``_``-prefixed so they never reach the hub or
perturb the supervisor's progress signature.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.types import Send

from src.core.config import settings
from src.core.logging import logger
from src.core.metrics import PLANNER_REPLANS, PLANNER_STAGE_OUTCOME
from src.domains.intelligence.agent_registry import (
    agent_node_names,
    build_plan,
    context_key_for,
    required_dependency_keys,
)
from src.domains.intelligence.schemas import OrchestratorState

# agent_id ("A".."J") ↔ graph node-name correspondence, sourced from the registry
# (A2A P5). The planner works in agent_id space (build_plan's currency) but
# dispatches to graph node names.
_AGENT_TO_NODE: dict[str, str] = agent_node_names()
_NODE_TO_AGENT: dict[str, str] = {node: aid for aid, node in _AGENT_TO_NODE.items()}


@dataclass(frozen=True)
class StageResolution:
    """Which agents in a stage should run now, and which were skipped (+ why)."""

    run: list[str]                       # agent_ids to dispatch
    skipped: list[tuple[str, str]]       # (agent_id, reason)


def build_full_plan(target_nodes: list[str]) -> list[list[str]]:
    """Node-name targets → staged plan of agent_ids, with a terminal J stage.

    Agent J is excluded from dependency planning (it depends on nothing, so
    build_plan would place it in stage 0) and appended as the final stage so the
    executive summary always runs last, over every produced output.
    """
    ids = {
        _NODE_TO_AGENT[n]
        for n in target_nodes
        if n in _NODE_TO_AGENT and n != "j_summarizer"
    }
    stages = build_plan(ids) if ids else []
    plan = [sorted(stage) for stage in stages]
    plan.append(["J"])
    return plan


def resolve_stage(stage_agents: list[str], context: dict[str, Any]) -> StageResolution:
    """Apply criticality + idempotency to one stage against the current context."""
    run: list[str] = []
    skipped: list[tuple[str, str]] = []
    for agent_id in stage_agents:
        own_key = context_key_for(agent_id)
        if own_key is not None and own_key in context:
            skipped.append((agent_id, "already_produced"))
            PLANNER_STAGE_OUTCOME.labels(outcome="already_produced").inc()
            continue
        missing = [k for k in required_dependency_keys(agent_id) if k not in context]
        if missing:
            skipped.append((agent_id, f"missing_required:{','.join(missing)}"))
            PLANNER_STAGE_OUTCOME.labels(outcome="missing_required").inc()
            continue
        run.append(agent_id)
        PLANNER_STAGE_OUTCOME.labels(outcome="run").inc()
    return StageResolution(run=run, skipped=skipped)


def _advance_to_next_runnable(
    plan: list[list[str]], stage: int, context: dict[str, Any]
) -> tuple[int, list[str], list[list[str]]]:
    """Walk stages from ``stage`` collapsing fully-skipped ones.

    Returns ``(stage_index, dispatch_node_names, newly_skipped)``. ``dispatch`` is
    empty only when the plan is drained.
    """
    newly_skipped: list[list[str]] = []
    while stage < len(plan):
        res = resolve_stage(plan[stage], context)
        newly_skipped.extend([aid, reason] for aid, reason in res.skipped)
        if res.run:
            return stage, [_AGENT_TO_NODE[a] for a in res.run], newly_skipped
        stage += 1
    return stage, [], newly_skipped


def make_planner_node() -> Any:
    async def planner_node(state: OrchestratorState) -> dict[str, Any]:
        ctx = state["context"]
        updates: dict[str, Any] = {}

        plan: list[list[str]] | None = ctx.get("_plan")
        if plan is None:
            plan = build_full_plan(list(ctx.get("_planner_targets") or []))
            updates["_plan"] = plan
            stage = 0
        else:
            stage = int(ctx.get("_stage", 0)) + 1

        # ── Replan: plan drained but a consumer asked for more work ──────────
        if stage >= len(plan):
            replan = list(ctx.get("_replan_targets") or [])
            used = int(ctx.get("_replans_used", 0))
            if replan and used < settings.A2A_MAX_REPLANS:
                merged = list(ctx.get("_planner_targets") or []) + replan
                plan = build_full_plan(merged)
                updates["_plan"] = plan
                updates["_planner_targets"] = merged
                updates["_replans_used"] = used + 1
                updates["_replan_targets"] = []          # consumed
                stage = 0
                PLANNER_REPLANS.inc()
                logger.info(
                    "planner: replanning", replan_targets=replan, replans_used=used + 1
                )

        stage, dispatch, newly_skipped = _advance_to_next_runnable(plan, stage, ctx)

        skipped = list(ctx.get("_planner_skipped") or []) + newly_skipped
        updates["_stage"] = stage
        updates["_current_dispatch"] = dispatch
        updates["_planner_skipped"] = skipped
        if not dispatch:
            updates["_planner_done"] = True

        if dispatch:
            msg = f"[planner] Stage {stage}: dispatching {', '.join(dispatch)}."
        else:
            msg = "[planner] DAG complete."
        logger.info(msg, stage=stage, dispatch=dispatch, skipped=newly_skipped)
        return {
            "messages": [AIMessage(content=msg, name="planner")],
            "context": updates,
        }

    return planner_node


def planner_dispatch(state: OrchestratorState) -> list[Send] | str:
    """Conditional edge out of the planner: fan out the current stage, or finish.

    Returns one ``Send`` per agent in the resolved stage (parallel dispatch), or
    ``END`` when the plan is drained (dispatch empty). The planner node has
    already collapsed fully-skipped stages, so an empty dispatch means *done*.
    """
    dispatch = list(state["context"].get("_current_dispatch") or [])
    if dispatch:
        return [Send(node, state) for node in dispatch]
    return END


def after_hub_writer(state: OrchestratorState) -> str:
    """Conditional edge out of hub_writer: back to the planner mid-DAG, else supervisor."""
    ctx = state["context"]
    if ctx.get("_plan") is not None and not ctx.get("_planner_done"):
        return "planner"
    return "supervisor"
