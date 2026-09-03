"""Signed audit trail for proposal decisions (remediation #4).

Every ``AgentActionProposal`` approve/reject already gets a plain, unsigned row
in ``audit_logs`` (written by the router). ``_issue_decision_vc`` adds a
best-effort, Ed25519-signed copy in ``trust_log`` — mirroring the pattern
already proven at ``e_watchdog.py``: never let a Mongo hiccup affect the
already-committed Postgres decision.

Hermetic: tests `_issue_decision_vc` directly against an unpersisted
`AgentActionProposal` instance with `issue_vc` monkeypatched — no DB/Mongo
needed. `ProposalService.approve()`/`reject()` calling this at the right point
is covered structurally by `tests/integration/test_agent_proposal_workflow.py`
(DB-dependent) — this file isolates the VC-issuance behavior itself.
"""
from __future__ import annotations

import uuid

import pytest

from src.domains.intelligence import proposal_service
from src.domains.intelligence.models import AgentActionProposal, ProposalStatus


def _proposal(**overrides: object) -> AgentActionProposal:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "agent_label": "k_stockkeeper",
        "action_type": "stock.adjustment",
        "payload": {"product_ref": "SKU-1", "quantity": 5.0},
        "status": ProposalStatus.APPLIED,
        "applied_ref": "movement-123",
    }
    defaults.update(overrides)
    return AgentActionProposal(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_issue_decision_vc_signs_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    async def fake_issue_vc(**kwargs: object) -> str:
        calls.append(kwargs)
        return "trust-log-id"

    monkeypatch.setattr(proposal_service, "issue_vc", fake_issue_vc)

    proposal = _proposal()
    reviewer_id = uuid.uuid4()
    await proposal_service._issue_decision_vc(proposal, "proposal.approved", reviewer_id)

    assert len(calls) == 1
    call = calls[0]
    assert call["agent_id"] == "k_stockkeeper"
    assert call["operation"] == "proposal.approved"
    payload = call["payload"]
    assert isinstance(payload, dict)
    assert payload["proposal_id"] == str(proposal.id)
    assert payload["action_type"] == "stock.adjustment"
    assert payload["reviewer_id"] == str(reviewer_id)
    assert payload["applied_ref"] == "movement-123"


@pytest.mark.asyncio
async def test_issue_decision_vc_never_raises_on_mongo_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_issue_vc(**_kwargs: object) -> str:
        raise RuntimeError("MongoDB client not initialised")

    monkeypatch.setattr(proposal_service, "issue_vc", failing_issue_vc)

    proposal = _proposal(status=ProposalStatus.REJECTED, applied_ref=None)
    # Must not raise — a signed-copy failure can never affect an
    # already-committed Postgres decision.
    await proposal_service._issue_decision_vc(
        proposal, "proposal.rejected", uuid.uuid4()
    )
