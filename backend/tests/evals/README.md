# Agent evaluation harness

Evals for the financial agents, split by what's being tested:

| File | What | Blocking? | Needs |
|---|---|---|---|
| `test_agent_f_tax_evals.py` | Agent F **deterministic numbers** (VAT/CIT/AML math, golden KRA scenarios) | **Yes — gates CI** | nothing (pure functions) |
| `test_agent_f_narrative_judge.py` | Agent F **LLM-written narrative** grounding (LLM-as-judge) | No — nightly/opt-in | `RUN_LLM_EVALS=1` + `GEMINI_API_KEY` |
| `test_supervisor_trajectory.py` | Supervisor **routing contract** (allowlist holds, bad routes → FINISH, errors degrade) | **Yes — gates CI** | nothing (LLM mocked) |
| `test_supervisor_context_window.py` | Supervisor **routing-context window** (head+tail bounding, truncation, flat cost) | **Yes — gates CI** | nothing (pure function) |
| `test_supervisor_routing_judge.py` | Supervisor **real-model routing accuracy** over golden `ROUTING_CASES` | No — nightly/opt-in | `RUN_LLM_EVALS=1` + `GEMINI_API_KEY` |
| `datasets.py` | Golden scenarios with hand-derived expected outputs (`TAX_CASES`, `AML_CASES`, `ROUTING_CASES`) | — | — |

**Output vs trajectory.** The Agent-F evals check *outputs* (is the final number/narrative right?).
The supervisor evals check the *trajectory* (did the agent take the right step?): the deterministic
pair pins the routing contract with the LLM mocked, and the nightly judge measures whether the real
model routes the golden queries to the correct agent (accuracy threshold, never gates a PR).

## Why split

Agent F computes its financial figures in pure Python (`_calculate_tax_liability`
+ an AML threshold check); the LLM only writes prose. So the **numbers** are
tested with fast, free, deterministic asserts that block the build — no
LLM-as-judge needed to check arithmetic (it would be slower, flakier, and cost
tokens). LLM-as-judge is reserved for the **narrative**, which is
non-deterministic and therefore non-blocking.

The deterministic suite is what catches silent drift like a wrong VAT threshold
(`test_regulatory_constants_pinned`).

## Running

```bash
# Deterministic gate (what CI runs on every PR, via `pytest tests/`):
uv run pytest tests/evals/test_agent_f_tax_evals.py -v

# LLM-judge (nightly / local opt-in — costs tokens):
RUN_LLM_EVALS=1 GEMINI_API_KEY=... uv run pytest tests/evals -m llm_judge -v
```

In CI the deterministic evals run inside the existing `backend-lint-test` job
(they live under `tests/`). The LLM-judge runs in the scheduled, non-blocking
`llm-evals` job.

## Extending

Add scenarios to `datasets.py` with the arithmetic in each `note` so a reviewer
can re-derive the expected figure. Add new judge criteria (e.g. citation
grounding — does the summary cite only KRA references actually retrieved?) as
further `llm_judge`-marked tests.
