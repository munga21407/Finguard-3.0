"""Sprint 6 — S6-6 receipt OCR multi-pass + config-driven taxonomy.

Hermetic: the vision client is monkeypatched. Covers the higher-fidelity
re-scan trigger, the no-retry fast path, retry-failure fallback, and the
configurable expense taxonomy (schema clamp + tuning validation).
"""
from __future__ import annotations

import pytest

from src.domains.intelligence import tuning as tmod
from src.domains.intelligence.schemas import (
    ReceiptExtraction,
    effective_receipt_categories,
)
from src.domains.intelligence.tools import vision_ocr
from src.domains.intelligence.tuning import (
    AgentTuning,
    ReceiptTuning,
    validate_agent_tuning,
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture(autouse=True)
def _reset_overlay():
    tmod.clear_db_overlay()
    yield
    tmod.clear_db_overlay()


def _extraction(conf: float, merchant: str = "M") -> ReceiptExtraction:
    return ReceiptExtraction(merchant_name=merchant, total_amount=10.0, confidence=conf)


# ── tuning defaults + validation ───────────────────────────────────────────────

def test_receipt_tuning_defaults_match_base_taxonomy() -> None:
    rt = ReceiptTuning()
    assert rt.categories == ("supplies", "services", "utilities", "travel", "other")
    assert rt.ocr_min_confidence == 0.6
    assert rt.hifi_retry_enabled is True


def test_validation_rejects_missing_other_fallback() -> None:
    bad = AgentTuning(receipt=ReceiptTuning(categories=("supplies", "services")))
    problems = validate_agent_tuning(bad)
    assert any("other" in p for p in problems)


def test_validation_rejects_out_of_range_confidence() -> None:
    bad = AgentTuning(receipt=ReceiptTuning(ocr_min_confidence=1.5))
    problems = validate_agent_tuning(bad)
    assert any("ocr_min_confidence" in p for p in problems)


# ── config-driven taxonomy (schema clamp) ──────────────────────────────────────

def test_operator_added_category_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    tmod.set_db_overlay(
        {"receipt": ReceiptTuning(categories=("supplies", "payroll", "other"))}
    )
    assert "payroll" in effective_receipt_categories()
    # A value now in the configured set survives the schema clamp.
    assert ReceiptExtraction(suggested_category="payroll").suggested_category == "payroll"
    # A value outside it still clamps to "other".
    assert ReceiptExtraction(suggested_category="travel").suggested_category == "other"


# ── multi-pass retry ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_high_confidence_skips_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    async def _fake(*_a, **kw):
        calls.append(kw)
        return _extraction(0.95)

    monkeypatch.setattr(vision_ocr, "generate_vision_content", _fake)
    out = await vision_ocr.extract_receipt(_PNG)
    assert out.confidence == 0.95
    assert len(calls) == 1  # no second pass


@pytest.mark.asyncio
async def test_low_confidence_triggers_hifi_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    # The second pass only runs when a distinct retry model is configured
    # (VISION_RETRY_MODEL is empty/disabled by default).
    monkeypatch.setattr(vision_ocr.settings, "VISION_RETRY_MODEL", "hifi-model")
    calls: list[str | None] = []

    async def _fake(*_a, **kw):
        calls.append(kw.get("model"))
        # First pass (default model) low; retry (hifi model) high.
        return _extraction(0.9, "pro") if kw.get("model") else _extraction(0.3, "flash")

    monkeypatch.setattr(vision_ocr, "generate_vision_content", _fake)
    out = await vision_ocr.extract_receipt(_PNG)
    assert len(calls) == 2
    assert calls[0] is None  # first pass = default model
    assert calls[1] == vision_ocr.settings.VISION_RETRY_MODEL
    assert out.merchant_name == "pro"  # higher-confidence read wins


@pytest.mark.asyncio
async def test_retry_failure_keeps_first_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vision_ocr.settings, "VISION_RETRY_MODEL", "hifi-model")

    async def _fake(*_a, **kw):
        if kw.get("model"):
            raise RuntimeError("hifi model down")
        return _extraction(0.3, "flash")

    monkeypatch.setattr(vision_ocr, "generate_vision_content", _fake)
    out = await vision_ocr.extract_receipt(_PNG)
    assert out.merchant_name == "flash"  # first read preserved on retry failure


@pytest.mark.asyncio
async def test_retry_disabled_by_config(monkeypatch: pytest.MonkeyPatch) -> None:
    tmod.set_db_overlay({"receipt": ReceiptTuning(hifi_retry_enabled=False)})
    calls: list[dict] = []

    async def _fake(*_a, **kw):
        calls.append(kw)
        return _extraction(0.1)

    monkeypatch.setattr(vision_ocr, "generate_vision_content", _fake)
    out = await vision_ocr.extract_receipt(_PNG)
    assert len(calls) == 1  # retry suppressed even though confidence is low
    assert out.confidence == 0.1
