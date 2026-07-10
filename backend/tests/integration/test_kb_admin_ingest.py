"""Integration: admin KRA upload → finguard.knowledge_base semantic retrieval.

Asserts that posting a document through the guarded admin route lands chunks in
the pgvector knowledge base AND that they surface as the nearest neighbour to a
semantic query — i.e. the upload pipeline (chunk → embed → HNSW store) is wired
end to end and queryable by Agent F's Tax RAG.

Gemini embedding is replaced with a deterministic fake so the test is hermetic of
the network; pgvector is required, so the test self-skips when the extension /
``finguard.knowledge_base`` table is absent (e.g. on stock postgres:16 in CI).
"""
from __future__ import annotations

import hashlib

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.domains.identity.models import UserRole

_EMBED_DIM = 768


def _fake_embed(value: str) -> list[float]:
    """Deterministic 768-dim pseudo-embedding — same text → same vector."""
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return [digest[i % len(digest)] / 255.0 for i in range(_EMBED_DIM)]


def _vec_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in vector) + "]"


async def _pgvector_ready(session: AsyncSession) -> bool:
    ext = await session.execute(
        text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    )
    if ext.first() is None:
        return False
    tbl = await session.execute(
        text("SELECT to_regclass('finguard.knowledge_base')")
    )
    return tbl.scalar() is not None


@pytest.mark.asyncio
async def test_admin_upload_surfaces_in_semantic_query(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_as,
    monkeypatch,
) -> None:
    if not await _pgvector_ready(db_session):
        pytest.skip("pgvector / finguard.knowledge_base unavailable")

    auth_as(UserRole.ADMIN)

    # Avoid real Gemini calls: patch the neutral facade the admin route embeds
    # through, returning a deterministic vector per chunk.
    async def _fake_generate_embedding(text, *, task_type=None, output_dimensionality=None):
        return _fake_embed(text)

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "src.domains.intelligence.routers.admin.generate_embedding",
        _fake_generate_embedding,
    )

    body = (
        b"SECTION 1: VAT RATE\n"
        b"The standard value added tax rate in Kenya is sixteen percent (16%)."
    )

    res = await client.post(
        "/api/v1/intelligence/admin/knowledge-base/ingest",
        files={"file": ("vat_rules.txt", body, "text/plain")},
    )
    assert res.status_code == 201, res.text
    payload = res.json()
    assert payload["inserted"] >= 1
    assert payload["document_title"] == "Vat Rules"

    # The stored chunk must be retrievable as the nearest semantic match.
    stored = await db_session.execute(
        text(
            "SELECT content FROM finguard.knowledge_base "
            "WHERE document_title = :t ORDER BY created_at DESC LIMIT 1"
        ),
        {"t": "Vat Rules"},
    )
    content = stored.scalar_one()
    assert "16%" in content

    nearest = await db_session.execute(
        text(
            "SELECT content FROM finguard.knowledge_base "
            "ORDER BY vector_embeddings <-> CAST(:q AS vector) LIMIT 1"
        ),
        {"q": _vec_literal(_fake_embed(content))},
    )
    assert nearest.scalar_one() == content


@pytest.mark.asyncio
async def test_non_admin_cannot_ingest(
    client: AsyncClient,
    auth_as,
) -> None:
    auth_as(UserRole.ACCOUNTANT)
    res = await client.post(
        "/api/v1/intelligence/admin/knowledge-base/ingest",
        files={"file": ("vat.txt", b"SECTION 1: VAT\n16%", "text/plain")},
    )
    assert res.status_code == 403
