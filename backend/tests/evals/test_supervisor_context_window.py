"""
Deterministic eval for the Supervisor routing-context window (CV-3 — gates CI).

The supervisor used to feed the *entire* growing transcript into every routing
call, making the prompt cost O(hops) and inviting lost-in-the-middle misroutes.
``_windowed_messages`` bounds the context to the original intent (head) plus the
most recent agent results (tail), with a per-message char cap. These tests pin
that contract: head retention, tail retention, middle dropping, truncation,
de-duplication, and — the point of the change — cost that stays flat as the
conversation grows.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from src.domains.intelligence.agents.supervisor import _MAX_MSG_CHARS, _windowed_messages


def _conversation(n_steps: int) -> list:
    """Original human intent followed by ``n_steps`` agent messages."""
    msgs: list = [HumanMessage(content="ORIGINAL INTENT")]
    msgs += [AIMessage(content=f"step {i}", name="a_generator") for i in range(n_steps)]
    return msgs


def test_keeps_intent_and_recent_drops_middle() -> None:
    out = _windowed_messages(_conversation(10), keep_last=3)
    assert "ORIGINAL INTENT" in out                 # head/intent always retained
    assert "step 9" in out and "step 8" in out and "step 7" in out  # recent tail kept
    assert "step 5" not in out                       # stale middle dropped
    assert len(out.splitlines()) <= 4                # head(1) + tail(3)


def test_truncates_oversized_message() -> None:
    big = "x" * (_MAX_MSG_CHARS + 500)
    out = _windowed_messages([HumanMessage(content=big)])
    assert "…[truncated]" in out
    assert len(out) < len(big)


def test_empty_messages_returns_empty_string() -> None:
    assert _windowed_messages([]) == ""


def test_head_in_tail_is_not_duplicated() -> None:
    out = _windowed_messages([HumanMessage(content="solo")], keep_last=4)
    assert out.count("solo") == 1                    # head/tail overlap deduped


def test_cost_is_bounded_regardless_of_history_length() -> None:
    short = _windowed_messages(_conversation(5), keep_last=4)
    long = _windowed_messages(_conversation(500), keep_last=4)
    # The whole point of CV-3: rendered size is flat in conversation length.
    assert len(long.splitlines()) == len(short.splitlines())
    assert len(long) < 2000                           # no unbounded prompt growth
