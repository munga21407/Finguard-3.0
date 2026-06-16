"""
Receipt Scanner endpoint — POST /intelligence/receipts/scan.

Validation paths (type/empty/size) need no Gemini.  The happy path mocks the
vision OCR + categoriser so the test is hermetic and deterministic.
"""
from __future__ import annotations

from collections.abc import Callable

import pytest
from httpx import AsyncClient

import src.domains.intelligence.agents.receipt_scanner as scanner
from src.domains.identity.models import User, UserRole
from src.domains.intelligence.schemas import ReceiptExtraction

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # valid PNG magic + filler


@pytest.mark.asyncio
async def test_scan_rejects_unsupported_type(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.MANAGER)
    res = await client.post(
        "/api/v1/intelligence/receipts/scan",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 415


@pytest.mark.asyncio
async def test_scan_rejects_empty_file(
    client: AsyncClient, auth_as: Callable[..., User]
) -> None:
    auth_as(UserRole.MANAGER)
    res = await client.post(
        "/api/v1/intelligence/receipts/scan",
        files={"file": ("receipt.png", b"", "image/png")},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_scan_happy_path_returns_extraction_and_category(
    client: AsyncClient,
    auth_as: Callable[..., User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_as(UserRole.MANAGER)

    async def _fake_extract(image_bytes: bytes, mime_type: str | None = None) -> ReceiptExtraction:
        return ReceiptExtraction(
            merchant_name="Nairobi Hardware Ltd",
            date="2026-06-13",
            total_amount=3750.0,
            currency="KES",
            kra_pin="P051234567X",
            line_items=["cement", "nails"],
            confidence=0.95,
        )

    # Mock the categoriser's LLM call to deterministically return "supplies".
    async def _fake_text(*args: object, **kwargs: object) -> str:
        return "supplies"

    monkeypatch.setattr(scanner, "extract_receipt", _fake_extract)
    monkeypatch.setattr(scanner, "generate_text_content", _fake_text)

    res = await client.post(
        "/api/v1/intelligence/receipts/scan",
        files={"file": ("receipt.png", _PNG_BYTES, "image/png")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["extraction"]["merchant_name"] == "Nairobi Hardware Ltd"
    assert body["extraction"]["total_amount"] == 3750.0
    assert body["extraction"]["kra_pin"] == "P051234567X"
    assert body["suggested_category"] == "supplies"
    assert body["error"] is None


@pytest.mark.asyncio
async def test_scan_degrades_to_empty_form_on_ocr_failure(
    client: AsyncClient,
    auth_as: Callable[..., User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Gemini OCR failure must NOT 500 — it returns an empty form + error."""
    auth_as(UserRole.MANAGER)

    async def _boom(image_bytes: bytes, mime_type: str | None = None) -> ReceiptExtraction:
        raise RuntimeError("gemini timeout")

    async def _fake_text(*args: object, **kwargs: object) -> str:
        return "other"

    monkeypatch.setattr(scanner, "extract_receipt", _boom)
    monkeypatch.setattr(scanner, "generate_text_content", _fake_text)

    res = await client.post(
        "/api/v1/intelligence/receipts/scan",
        files={"file": ("receipt.png", _PNG_BYTES, "image/png")},
    )
    assert res.status_code == 200
    body = res.json()
    # Empty extraction + populated error so the user can still fill the form.
    assert body["extraction"]["merchant_name"] is None
    assert body["error"] is not None
    assert "gemini timeout" in body["error"]
