"""Sprint 4 — deterministic guards that don't trust the LLM's word.

  * Agent F: machine-verified AML / VAT-registration flags are always present.
  * Agent B: every input transaction gets a valid taxonomy category, even when
    Gemini omits one or returns an out-of-taxonomy label.
"""
from __future__ import annotations

import pytest

import src.domains.intelligence.agents.b_classifier as b
from src.domains.intelligence.agents.f_auditor import _inject_deterministic_flags

# ── Agent F: deterministic compliance-flag injection ──────────────────────────

def test_aml_flag_injected_over_threshold() -> None:
    out = _inject_deterministic_flags(
        [], max_single_tx=2_000_000, aml_threshold=1_000_000,
        annual_revenue=0, vat_threshold=5_000_000, tax_type="VAT",
    )
    assert "AML_REPORTING_REQUIRED" in out


def test_vat_gap_injected_when_unassessed() -> None:
    out = _inject_deterministic_flags(
        [], max_single_tx=0, aml_threshold=1_000_000,
        annual_revenue=6_000_000, vat_threshold=5_000_000, tax_type="CORPORATE_TAX",
    )
    assert "VAT_REGISTRATION_REQUIRED" in out


def test_vat_gap_not_injected_when_comprehensive() -> None:
    out = _inject_deterministic_flags(
        [], max_single_tx=0, aml_threshold=1_000_000,
        annual_revenue=6_000_000, vat_threshold=5_000_000, tax_type="COMPREHENSIVE",
    )
    assert "VAT_REGISTRATION_REQUIRED" not in out


def test_no_duplicate_flags() -> None:
    out = _inject_deterministic_flags(
        ["AML_REPORTING_REQUIRED: existing"], max_single_tx=2_000_000,
        aml_threshold=1_000_000, annual_revenue=0, vat_threshold=5_000_000, tax_type="VAT",
    )
    assert sum("AML_REPORTING_REQUIRED" in f for f in out) == 1


# ── Agent B: classification coverage/taxonomy guards ──────────────────────────

def _entry(eid: str) -> dict[str, object]:
    return {"entry_id": eid, "narrative": "n", "amount": 1.0, "transaction_type": "debit"}


@pytest.mark.asyncio
async def test_classifier_guards_coverage_and_taxonomy(monkeypatch: pytest.MonkeyPatch) -> None:
    valid_category = list(b.TRANSACTION_TAXONOMY)[0]

    async def fake_gen(_prompt: str, _schema: type, **_k: object) -> object:
        return b.BatchClassificationResult(classifications=[
            b.TransactionClassification(entry_id="1", category=valid_category, confidence=0.9),
            b.TransactionClassification(entry_id="2", category="not_a_real_category", confidence=0.9),
            # entry "3" deliberately omitted by the model
        ])

    monkeypatch.setattr(b, "generate_structured_content", fake_gen)

    result = await b._classify_via_gemini([_entry("1"), _entry("2"), _entry("3")])
    by_id = {c.entry_id: c for c in result}

    assert set(by_id) == {"1", "2", "3"}                 # every input covered
    assert by_id["1"].category == valid_category         # valid label preserved
    assert by_id["2"].category == "other"                # out-of-taxonomy clamped
    assert by_id["3"].category == "other" and by_id["3"].confidence == 0.0  # missing → other
    assert all(c.category in b.TRANSACTION_TAXONOMY for c in result)
