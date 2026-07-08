"""
Supervisor node — the ReAct loop controller.

Uses Gemini structured output to inspect the current conversation state
and decide which agent node to invoke next, or whether the task is complete.

Loop-escape strategy
--------------------
Two layers:
  1. **Cycle guard (S6-4):** a benign loop — the supervisor routing to the same
     agent that yields no new output/context — is detected and terminated
     *gracefully* (FINISH with partial results) before it burns hops. See
     ``_progress_signature`` / the cycle guard inside ``_route``.
  2. **Recursion ceiling (last resort):** LangGraph's native recursion limit
     (``{"recursion_limit": 25}`` in ``orchestrator.run_graph``) still backstops
     any pathological path the guard misses. The previous manual hop-counter
     (``context["_supervisor_hop_count"]``) was removed — it was fragile because
     any context overwrite reset it; the cycle guard keys off *progress*, not a
     raw counter, so an overwrite can't hide a genuine stall.

Failure handling
----------------
Every failure path logs the error with full context and routes to FINISH
rather than crashing the backend.  Pydantic ``ValidationError`` on the
Gemini response is caught explicitly and also routes to FINISH.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, ValidationError

from src.core.config import settings
from src.core.logging import logger
from src.core.metrics import SUPERVISOR_ROUTES
from src.domains.intelligence.llm_client import generate_structured_content
from src.domains.intelligence.prompts.supervisor import (
    SUPERVISOR_HUMAN,
    SUPERVISOR_SYSTEM,
    SUPERVISOR_TARGETS_ADDENDUM,
)
from src.domains.intelligence.schemas import OrchestratorState

VALID_NEXT = frozenset({
    "a_generator", "b_classifier", "c_reconciler", "d_forecaster",
    "e_watchdog", "f_auditor", "g_reporter", "h_advisor",
    "i_integrator", "j_summarizer", "FINISH",
})

# ── Deterministic keyword router (Sprint 3 — cut per-hop LLM routing cost) ─────
# A clear single-agent intent skips the Gemini routing call entirely. Each entry
# is (agent_node, keyword/phrase set); the initial user message is scored against
# every set and a *strict* single winner (score ≥ 1, no tie) short-circuits the
# LLM. Ambiguous / multi-agent intents fall through to Gemini as before.
_KEYWORD_ROUTES: tuple[tuple[str, frozenset[str]], ...] = (
    ("a_generator", frozenset({"extract invoice", "parse invoice", "generate invoice",
                               "invoice from", "scan invoice"})),
    ("b_classifier", frozenset({"classify", "categorize", "categorise",
                                "classification", "categorization"})),
    ("c_reconciler", frozenset({"reconcile", "reconciliation", "match payment",
                                "match the payment", "mpesa", "bank statement"})),
    ("d_forecaster", frozenset({"forecast", "cash flow", "cashflow", "runway",
                                "projection", "project cash"})),
    ("e_watchdog", frozenset({"budget", "watchdog", "anomaly", "overspend",
                              "duplicate invoice", "over budget"})),
    ("f_auditor", frozenset({"tax", "vat", "kra", "tax audit", "tax compliance",
                             "corporate income tax"})),
    ("g_reporter", frozenset({"bankability", "credit strategy", "credit score",
                              "loan readiness", "credit report"})),
    ("h_advisor", frozenset({"advice", "advise", "recommend", "what should i",
                             "should i", "recommendation"})),
    ("i_integrator", frozenset({"exchange rate", "fx rate", "forex",
                                "external data", "credit bureau"})),
    ("j_summarizer", frozenset({"executive summary", "summarize", "summarise",
                                "summary of", "overview"})),
)

# Bounded cache of the initial routing decision, keyed by normalised intent text,
# so repeated identical intents skip even the Gemini call. Process-global; only
# the first hop is cached (later hops depend on accumulated state).
_ROUTE_CACHE_MAX = 256
_INITIAL_ROUTE_CACHE: OrderedDict[str, str] = OrderedDict()


def _normalise_intent(text: str) -> str:
    return " ".join(text.lower().split())


def _first_intent_text(messages: list[Any]) -> str:
    for m in messages:
        if isinstance(m, HumanMessage):
            return _normalise_intent(str(m.content))
    return ""


def _heuristic_route(intent_text: str) -> str | None:
    """Return the single clear agent for ``intent_text``, or None if ambiguous."""
    if not intent_text:
        return None
    scored: list[tuple[int, str]] = []
    for node, keywords in _KEYWORD_ROUTES:
        score = sum(1 for kw in keywords if kw in intent_text)
        if score:
            scored.append((score, node))
    if not scored:
        return None
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None  # tie — let Gemini decide
    return scored[0][1]


def _cache_get(intent_text: str) -> str | None:
    node = _INITIAL_ROUTE_CACHE.get(intent_text)
    if node is not None:
        _INITIAL_ROUTE_CACHE.move_to_end(intent_text)
    return node


def _cache_put(intent_text: str, node: str) -> None:
    if not intent_text:
        return
    _INITIAL_ROUTE_CACHE[intent_text] = node
    _INITIAL_ROUTE_CACHE.move_to_end(intent_text)
    while len(_INITIAL_ROUTE_CACHE) > _ROUTE_CACHE_MAX:
        _INITIAL_ROUTE_CACHE.popitem(last=False)


def reset_route_cache() -> None:
    """Clear the initial-route cache (tests / operational reset)."""
    _INITIAL_ROUTE_CACHE.clear()


def _agent_has_run(messages: list[Any], node: str) -> bool:
    return any(getattr(m, "name", None) == node for m in messages)


# ── Cycle guard (Sprint 6, S6-4) ──────────────────────────────────────────────
# LangGraph's recursion_limit is the *last* line of defence — hitting it raises
# GraphRecursionError (surfaced as a 508). A benign loop (supervisor keeps
# routing to the same agent that produces no new output/context) should instead
# terminate gracefully with a partial result. We detect that by hashing the
# session's "progress" — the set of agents that have produced output plus the
# public context keys — and counting how many times in a row the supervisor
# picks the *same* next node while that signature is unchanged.
_MAX_STALLED_REPEATS = 2   # 3rd identical route with no progress → FINISH
_ROUTE_HISTORY_MAX = 12    # bounded per-session decision trail


def _progress_signature(messages: list[Any], context: dict[str, Any]) -> str:
    """A cheap, JSON-safe marker of how far the session has actually advanced.

    Changes only when a *new* agent produces output or a *new* public context
    key appears — the two things that constitute real progress. Internal
    bookkeeping keys (``_``-prefixed) are excluded so the guard's own trail
    doesn't perturb the signature.
    """
    agent_names = sorted(
        {
            str(getattr(m, "name", ""))
            for m in messages
            if getattr(m, "name", None) not in (None, "supervisor")
        }
    )
    ctx_keys = sorted(k for k in context if not k.startswith("_"))
    return "|".join(agent_names) + "#" + "|".join(ctx_keys)

# ── Routing-context window bounds ─────────────────────────────────────────────
# The supervisor only needs the user's original intent plus the most recent
# agent results to choose the next hop.  Feeding the entire transcript on every
# hop grows the routing prompt O(hops) — inflating token cost and degrading the
# decision via lost-in-the-middle — so we keep head + tail and cap each message.
_KEEP_LAST_MESSAGES = 4
_MAX_MSG_CHARS = 600


def _format_message(m: Any) -> str:
    """Render one message as ``[Type] content`` with a per-message char cap."""
    content = str(getattr(m, "content", ""))
    if len(content) > _MAX_MSG_CHARS:
        content = content[:_MAX_MSG_CHARS] + " …[truncated]"
    return f"[{m.__class__.__name__}] {content}"


def _windowed_messages(messages: list[Any], *, keep_last: int = _KEEP_LAST_MESSAGES) -> str:
    """Bound the routing context to the first message (intent) + last ``keep_last``.

    De-duplicates by object identity so a short conversation whose head and tail
    overlap is not repeated.  Cost is O(1) in conversation length per hop instead
    of O(hops), and the per-message truncation caps any single verbose agent
    payload before it reaches the model.
    """
    if not messages:
        return ""
    head = messages[:1]
    tail = messages[-keep_last:] if keep_last > 0 else []
    seen: set[int] = set()
    chosen: list[Any] = []
    for m in (*head, *tail):
        if id(m) not in seen:
            seen.add(id(m))
            chosen.append(m)
    return "\n".join(_format_message(m) for m in chosen)


class _SupervisorDecision(BaseModel):
    next: str
    reason: str
    # A2A P4: for a multi-domain request the model may name ≥2 leaf agents here;
    # the planner expands their dependencies into a parallel DAG. Empty for a
    # single-agent request (the common case), and ignored unless the planner flag
    # is on — so single-domain routing is byte-for-byte unchanged.
    targets: list[str] = []


def make_supervisor_node(llm: Any = None) -> Any:  # llm kept for signature compat
    async def supervisor_node(state: OrchestratorState) -> dict[str, Any]:
        context = dict(state.get("context", {}))

        # ── requested_agent short-circuit (initial routing only) ──────────────
        # Honours context["requested_agent"] set by the HTTP router or a test
        # fixture to bypass the Gemini routing call when the first target is
        # already known.  Detects "initial call" by the absence of any prior
        # agent AIMessages — this is resilient to context overwrites unlike the
        # removed manual hop counter.
        is_initial_call = not any(
            hasattr(m, "name") and m.name not in (None, "supervisor")
            for m in state["messages"]
        )
        def _route(node: str, reason: str, method: str) -> dict[str, Any]:
            if node != "FINISH":
                # ── Cycle guard: break a benign loop before the recursion ceiling ──
                sig = _progress_signature(state["messages"], context)
                history: list[list[str]] = list(context.get("_route_history") or [])
                repeat = 0
                for entry in reversed(history):
                    if entry == [node, sig]:
                        repeat += 1
                    else:
                        break
                if repeat >= _MAX_STALLED_REPEATS:
                    logger.warning(
                        "Supervisor: cycle detected — terminating with partial results",
                        node=node,
                        repeats=repeat,
                        session_id=state.get("session_id"),
                    )
                    SUPERVISOR_ROUTES.labels(method="cycle_break").inc()
                    return {
                        "messages": [AIMessage(
                            content=(
                                f"Cycle detected: routed to '{node}' repeatedly with no "
                                "new context — terminating with partial results."
                            ),
                            name="supervisor",
                        )],
                        "next": "FINISH",
                        "context": context,
                    }
                history.append([node, sig])
                context["_route_history"] = history[-_ROUTE_HISTORY_MAX:]
                context["_route_origin"] = node
            SUPERVISOR_ROUTES.labels(method=method).inc()
            return {
                "messages": [AIMessage(content=reason, name="supervisor")],
                "next": node,
                "context": context,
            }

        requested_agent = context.get("requested_agent")
        if is_initial_call and requested_agent and requested_agent in VALID_NEXT:
            logger.info(
                "Supervisor: honouring requested_agent",
                requested_agent=requested_agent,
                session_id=state.get("session_id"),
            )
            return _route(
                requested_agent, f"Routing to requested agent: {requested_agent}", "requested"
            )

        intent_text = _first_intent_text(state["messages"])

        # ── Deterministic short-circuits (no Gemini) ──────────────────────────
        if is_initial_call:
            cached = _cache_get(intent_text)
            if cached is not None and cached in VALID_NEXT:
                return _route(cached, f"Cached route → {cached}", "cache")
            heuristic = _heuristic_route(intent_text)
            if heuristic is not None:
                _cache_put(intent_text, heuristic)
                return _route(heuristic, f"Keyword route → {heuristic}", "heuristic")
        else:
            # Single-agent flow: the heuristically/requested-routed agent has run,
            # so terminate without spending a Gemini call to (re)decide FINISH.
            origin = context.get("_route_origin")
            if (
                isinstance(origin, str)
                and origin in VALID_NEXT
                and _agent_has_run(state["messages"], origin)
            ):
                return _route("FINISH", "Single-agent flow complete.", "single_agent_finish")

        # ── Build prompt ──────────────────────────────────────────────────────
        system = SUPERVISOR_SYSTEM.format(
            mode=state.get("mode", "insights"),
            agent_table=supervisor_agent_table(),
        )
        if settings.A2A_PLANNER_ENABLED:
            system += SUPERVISOR_TARGETS_ADDENDUM
        human = SUPERVISOR_HUMAN.format(messages=_windowed_messages(state["messages"]))
        full_prompt = f"{system}\n\n{human}"

        # ── LLM call with exhaustive fallback ─────────────────────────────────
        next_node = "FINISH"
        reason = "Routing completed."
        targets_raw: list[str] = []

        try:
            decision = await generate_structured_content(full_prompt, _SupervisorDecision)
            targets_raw = list(decision.targets)

            # Validate the routed node against the known-safe allowlist
            if decision.next not in VALID_NEXT:
                logger.warning(
                    "Supervisor: LLM returned unknown route — defaulting to FINISH",
                    llm_next=decision.next,
                    session_id=state.get("session_id"),
                )
                next_node = "FINISH"
                reason = f"Unknown route '{decision.next}' rejected — terminating."
            else:
                next_node = decision.next
                reason = decision.reason

        except ValidationError as exc:
            logger.error(
                "Supervisor: Pydantic validation failed on LLM response — routing to FINISH",
                error=str(exc),
                session_id=state.get("session_id"),
            )
            reason = "Supervisor decision failed schema validation — terminating."

        except Exception as exc:
            logger.error(
                "Supervisor: Unexpected error during routing — routing to FINISH",
                error=str(exc),
                error_type=type(exc).__name__,
                session_id=state.get("session_id"),
            )
            reason = f"Routing error ({type(exc).__name__}) — terminating."

        # ── Multi-domain fan-out (A2A P4, flag-gated) ─────────────────────────
        # ≥2 distinct valid leaf targets → hand off to the planner, which expands
        # their dependency DAG and runs stages in parallel. Never triggers on the
        # deterministic single-agent paths above (they don't produce targets).
        if settings.A2A_PLANNER_ENABLED and next_node != "FINISH":
            seen: set[str] = set()
            valid_targets: list[str] = []
            for t in targets_raw:
                if t in VALID_NEXT and t != "FINISH" and t not in seen:
                    seen.add(t)
                    valid_targets.append(t)
            if len(valid_targets) >= 2:
                context["_planner_targets"] = valid_targets
                return _route(
                    "planner",
                    f"Multi-domain request → planning {valid_targets}.",
                    "planner",
                )

        # Cache a clean initial routing decision so an identical intent skips the
        # LLM next time (never cache FINISH / error fallbacks).
        if is_initial_call and next_node in VALID_NEXT and next_node != "FINISH":
            _cache_put(intent_text, next_node)

        return _route(next_node, reason, "gemini")

    return supervisor_node
