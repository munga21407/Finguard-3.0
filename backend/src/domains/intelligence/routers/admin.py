"""Intelligence admin — KRA knowledge-base ingestion.

  POST /admin/knowledge-base/ingest — upload a .txt regulatory document; it is
  chunked, embedded, and stored in the pgvector ``finguard.knowledge_base``
  HNSW index that Agent F's Tax RAG queries.

Restricted to ``USER_MANAGE`` (ADMIN / OWNER) so only operators can mutate the
regulatory corpus without terminal access. The chunk/embed/upsert pipeline is the
exact same code path as the ``scripts.ingest_kra_docs`` CLI — imported lazily so
the app start-up never pulls the script's module-level side effects.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.logging import logger
from src.domains.identity.dependencies import RequireUserManage
from src.domains.intelligence.llm_client import generate_embedding
from src.domains.intelligence.schemas import KnowledgeIngestResponse
from src.infrastructure.database.postgres import get_db

router = APIRouter()

DBSession = Annotated[AsyncSession, Depends(get_db)]

# Plain-text regulatory configs only; capped well under the nginx body limit.
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_ALLOWED_SUFFIXES = (".txt", ".md")
_EMBED_DIM = 768


async def _facade_embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of chunks through the app's neutral LLM facade.

    Injected into ``ingest_text_buffer`` so the admin route never touches a vendor
    SDK client — it goes through ``generate_embedding`` (retry/timeout/telemetry +
    L2-normalization) like every other embedding call.
    """
    return [
        await generate_embedding(
            t, task_type="RETRIEVAL_DOCUMENT", output_dimensionality=_EMBED_DIM
        )
        for t in texts
    ]


@router.post(
    "/admin/knowledge-base/ingest",
    response_model=KnowledgeIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_knowledge_base(
    current_user: RequireUserManage,
    db: DBSession,
    file: Annotated[UploadFile, File()],
) -> KnowledgeIngestResponse:
    """Ingest an uploaded KRA document into the Tax RAG knowledge base.

    Guarded by ``USER_MANAGE``. Validates the upload is a UTF-8 ``.txt``/``.md``
    document under 5 MB, then runs it through the shared chunk → embed → pgvector
    upsert pipeline. Idempotent: re-uploading the same content reports the
    sections as ``skipped`` (ON CONFLICT DO NOTHING).
    """
    filename = file.filename or "uploaded_document.txt"
    if not filename.lower().endswith(_ALLOWED_SUFFIXES):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only .txt or .md regulatory documents are accepted.",
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(raw) > _MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {_MAX_BYTES // (1024 * 1024)} MB limit.",
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400, detail="File must be UTF-8 encoded text."
        ) from exc

    if not settings.FIREWORKS_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding service is not configured (FIREWORKS_API_KEY unset).",
        )

    # Lazy/dynamic import — keeps the script's module-level setup out of app boot.
    from scripts.ingest_kra_docs import ingest_text_buffer  # noqa: PLC0415

    document_title = filename.rsplit(".", 1)[0].replace("_", " ").title()
    try:
        result = await ingest_text_buffer(
            session=db,
            embed_batch=_facade_embed_batch,
            document_title=document_title,
            raw_text=text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "KB ingest failed", document_title=document_title, error=str(exc)
        )
        raise HTTPException(
            status_code=502, detail=f"Ingestion pipeline failed: {exc}"
        ) from exc

    logger.info(
        "KB document ingested via admin upload",
        actor_id=str(current_user.id),
        document_title=document_title,
        inserted=result["inserted"],
        skipped=result["skipped"],
    )
    return KnowledgeIngestResponse(**result)
