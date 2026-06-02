"""
Agent J — Executive Summarizer.

Responsibility:
    Synthesise all findings accumulated in `state["context"]` into a concise
    (≤ 5 bullet) executive summary targeted at C-suite readers.  Always the
    last agent invoked before FINISH.

    Output written to `context["executive_summary"]` (plain text) and
    returned as the final AIMessage visible to the API caller.

Implementation notes (TODO):
    1. Build a summary prompt that enumerates populated context keys.
    2. Pass only non-empty context sections to Claude to stay within token budget.
    3. Use claude-haiku-4-5 for cost efficiency — summaries don't need deep
       reasoning, only clear distillation.
    4. Optionally translate the summary to the user's preferred locale
       (read from CRM customer profile).
"""
from __future__ import annotations

from langchain_core.messages import AIMessage

from src.domains.intelligence.schemas import OrchestratorState


def make_j_summarizer_node(llm=None):  # llm kept for signature compatibility
    async def j_summarizer_node(state: OrchestratorState) -> dict:
        # TODO: implement — see module docstring
        return {
            "messages": [
                AIMessage(content="[j_summarizer] Not yet implemented.", name="j_summarizer")
            ],
            "context": state["context"],
        }

    return j_summarizer_node
