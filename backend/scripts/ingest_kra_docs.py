"""
KRA Document Ingestion Pipeline — Sprint 4.

Reads KRA tax regulation documents from scripts/kra_docs/ (or a custom
directory), chunks them into semantic sections, generates 768-dimensional
Gemini text-embedding-004 vectors, and bulk-inserts them into the
finguard.knowledge_base table.

Design decisions:
  - Standalone (no app settings module import) — reads env vars directly.
  - Recursive character splitter mirrors LangChain's strategy without the
    LangChain dependency in the scripts package.
  - Embedding batches of 5 with tenacity exponential backoff for Google API
    rate limits (default quota: 1,500 calls/min).
  - Idempotent via ON CONFLICT DO NOTHING on the (document_title, section_key)
    unique constraint added in migration 0004.
  - Supports .txt and .md files natively; optional pypdf for .pdf files.

Usage (from backend/):
    python -m scripts.ingest_kra_docs
    python -m scripts.ingest_kra_docs --docs scripts/kra_docs
    python -m scripts.ingest_kra_docs --docs /path/to/docs --dry-run
    python -m scripts.ingest_kra_docs --chunk-size 1000 --overlap 150
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import asyncpg  # noqa: F401 — imported to validate asyncpg is present at startup
from google import genai
from google.genai import types as genai_types
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# ---------------------------------------------------------------------------
# Minimal logging (before app settings are available)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ingest_kra")

# ---------------------------------------------------------------------------
# Environment-sourced configuration (standalone — avoids importing app settings)
# ---------------------------------------------------------------------------
_DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://finguard:finguard@localhost:5432/finguard",
)
_GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

EMBEDDING_MODEL = "text-embedding-004"
EMBEDDING_DIM = 768

# Chunking defaults (overridable via CLI)
DEFAULT_CHUNK_SIZE = 800   # characters per chunk
DEFAULT_OVERLAP = 120      # overlap between consecutive chunks

# Gemini API batching — conservative default for rate limits
EMBED_BATCH_SIZE = 5       # texts per embed_content call
MAX_EMBED_RETRIES = 6
EMBED_WAIT_MIN = 2.0       # seconds (first retry)
EMBED_WAIT_MAX = 64.0      # seconds (max back-off)

# Separators in priority order — prefer semantic over syntactic splits
_SEPARATORS = ["\n\n\n", "\n\n", "\n", ". ", "? ", "! ", " ", ""]


# ---------------------------------------------------------------------------
# Recursive character text splitter
# ---------------------------------------------------------------------------

def _split_text(
    text: str,
    separators: list[str],
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """
    Recursively split `text` into chunks of at most `chunk_size` characters,
    with `chunk_overlap` characters carried over to the next chunk for context
    continuity.

    Mirrors the algorithm used by LangChain RecursiveCharacterTextSplitter
    without the dependency.
    """
    # Find the first separator that produces manageable splits
    separator = ""
    remaining_separators = separators[:]
    for sep in remaining_separators:
        if sep == "" or sep in text:
            separator = sep
            remaining_separators = separators[separators.index(sep) + 1:]
            break

    splits = text.split(separator) if separator else list(text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for split in splits:
        split_len = len(split)
        if split_len > chunk_size:
            # This fragment is too large — recurse
            if current:
                chunks.append(separator.join(current))
                # Carry overlap
                overlap_parts: list[str] = []
                overlap_len = 0
                for part in reversed(current):
                    if overlap_len + len(part) > chunk_overlap:
                        break
                    overlap_parts.insert(0, part)
                    overlap_len += len(part)
                current = overlap_parts
                current_len = overlap_len
            sub = _split_text(split, remaining_separators, chunk_size, chunk_overlap)
            chunks.extend(sub)
            continue

        if current_len + split_len + len(separator) > chunk_size and current:
            chunks.append(separator.join(current))
            # Carry overlap
            overlap_parts = []
            overlap_len = 0
            for part in reversed(current):
                if overlap_len + len(part) + len(separator) > chunk_overlap:
                    break
                overlap_parts.insert(0, part)
                overlap_len += len(part)
            current = overlap_parts
            current_len = sum(len(p) for p in current)

        current.append(split)
        current_len += split_len + len(separator)

    if current:
        chunks.append(separator.join(current))

    return [c.strip() for c in chunks if c.strip()]


# ---------------------------------------------------------------------------
# Document loader
# ---------------------------------------------------------------------------

def _load_document(path: Path) -> str:
    """Load a .txt, .md, or .pdf file and return its text content."""
    suffix = path.suffix.lower()

    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace")

    if suffix == ".pdf":
        try:
            import pypdf  # type: ignore[import-untyped]

            reader = pypdf.PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(pages)
        except ImportError:
            log.warning(
                "pypdf not installed — skipping PDF file %s. "
                "Install with: uv add pypdf",
                path.name,
            )
            return ""

    log.warning("Unsupported file type %s — skipping", path.suffix)
    return ""


def _infer_section_key(chunk: str, chunk_index: int) -> str:
    """
    Extract a section key from the chunk heading (e.g. 'SECTION 3: VAT RATE').
    Falls back to a positional key when no heading is detected.
    """
    for line in chunk.split("\n")[:3]:
        stripped = line.strip()
        if stripped.startswith("SECTION") and ":" in stripped:
            # e.g. "SECTION 3: VAT RATE" → "section_3_vat_rate"
            key = stripped.lower().replace(" ", "_").replace(":", "").replace(".", "")
            # Keep only alphanumeric + underscore, trim length
            key = "".join(c if c.isalnum() or c == "_" else "_" for c in key)[:120]
            return f"{key}_{chunk_index}"
    return f"chunk_{chunk_index:05d}"


# ---------------------------------------------------------------------------
# Gemini embedding with exponential backoff
# ---------------------------------------------------------------------------

@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=1, min=EMBED_WAIT_MIN, max=EMBED_WAIT_MAX),
    stop=stop_after_attempt(MAX_EMBED_RETRIES),
    reraise=True,
)
async def _embed_batch(
    client: genai.Client,
    texts: list[str],
) -> list[list[float]]:
    """
    Embed a batch of texts using Gemini text-embedding-004 (768 dims).
    Retried up to MAX_EMBED_RETRIES times with exponential back-off to handle
    Google API rate limits and transient network errors.
    """
    response = await client.aio.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=texts,
        config=genai_types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=EMBEDDING_DIM,
        ),
    )
    return [list(emb.values) for emb in response.embeddings]


# ---------------------------------------------------------------------------
# Database upsert
# ---------------------------------------------------------------------------

async def _upsert_chunks(
    session: AsyncSession,
    document_title: str,
    chunks: list[str],
    embeddings: list[list[float]],
    source_file: str,
) -> tuple[int, int]:
    """
    Insert chunks into finguard.knowledge_base with ON CONFLICT DO NOTHING.
    Returns (inserted_count, skipped_count).
    """
    insert_sql = text("""
        INSERT INTO finguard.knowledge_base
            (document_title, section_key, content, vector_embeddings, metadata_payload)
        VALUES
            (:title, :section_key, :content, :embedding::vector, :metadata::jsonb)
        ON CONFLICT (document_title, section_key) DO NOTHING
    """)

    import json

    inserted = 0
    skipped = 0

    for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=False)):
        section_key = _infer_section_key(chunk, idx)
        vec_literal = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
        metadata = json.dumps({
            "source_file": source_file,
            "chunk_index": idx,
            "char_length": len(chunk),
        })

        result = await session.execute(
            insert_sql,
            {
                "title": document_title,
                "section_key": section_key,
                "content": chunk,
                "embedding": vec_literal,
                "metadata": metadata,
            },
        )
        if result.rowcount > 0:
            inserted += 1
        else:
            skipped += 1

    await session.commit()
    return inserted, skipped


# ---------------------------------------------------------------------------
# Per-document pipeline
# ---------------------------------------------------------------------------

async def _process_document(
    path: Path,
    client: genai.Client | None,
    session: AsyncSession,
    chunk_size: int,
    chunk_overlap: int,
    dry_run: bool,
) -> dict[str, Any]:
    log.info("Processing %s", path.name)

    raw_text = _load_document(path)
    if not raw_text.strip():
        log.warning("  Empty or unreadable — skipping")
        return {"file": path.name, "chunks": 0, "inserted": 0, "skipped": 0}

    # Chunk
    chunks = _split_text(raw_text, _SEPARATORS, chunk_size, chunk_overlap)
    log.info("  %d chunks created (avg %d chars)", len(chunks), sum(len(c) for c in chunks) // max(len(chunks), 1))

    if dry_run:
        for i, chunk in enumerate(chunks[:3]):
            log.info("  [dry-run] chunk %d: %s…", i, chunk[:120].replace("\n", " "))
        return {"file": path.name, "chunks": len(chunks), "inserted": 0, "skipped": 0}

    if not _GEMINI_API_KEY:
        log.error("  GEMINI_API_KEY not set — cannot generate embeddings")
        return {"file": path.name, "chunks": len(chunks), "inserted": 0, "skipped": 0, "error": "no_api_key"}

    # Embed in batches
    document_title = path.stem.replace("_", " ").title()
    all_embeddings: list[list[float]] = []

    for batch_start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[batch_start : batch_start + EMBED_BATCH_SIZE]
        t0 = time.monotonic()
        try:
            batch_vecs = await _embed_batch(client, batch)
        except Exception as exc:
            log.error("  Embedding failed after retries: %s", exc)
            return {"file": path.name, "chunks": len(chunks), "inserted": 0, "skipped": 0, "error": str(exc)}
        elapsed = time.monotonic() - t0
        all_embeddings.extend(batch_vecs)
        log.debug(
            "  Embedded batch %d-%d in %.2fs",
            batch_start,
            batch_start + len(batch) - 1,
            elapsed,
        )

    # Validate dimensions
    bad = [(i, len(v)) for i, v in enumerate(all_embeddings) if len(v) != EMBEDDING_DIM]
    if bad:
        log.error("  Unexpected embedding dimensions at indices %s — skipping file", bad[:5])
        return {"file": path.name, "chunks": len(chunks), "inserted": 0, "skipped": 0, "error": "bad_dims"}

    # Upsert
    inserted, skipped = await _upsert_chunks(
        session, document_title, chunks, all_embeddings, path.name
    )
    log.info("  Inserted %d, skipped %d (already present)", inserted, skipped)
    return {"file": path.name, "chunks": len(chunks), "inserted": inserted, "skipped": skipped}


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

async def _run(
    docs_dir: Path,
    chunk_size: int,
    chunk_overlap: int,
    dry_run: bool,
) -> None:
    if not docs_dir.exists():
        log.error("Documents directory does not exist: %s", docs_dir)
        sys.exit(1)

    source_files = sorted(
        f for f in docs_dir.iterdir()
        if f.is_file() and f.suffix.lower() in (".txt", ".md", ".pdf")
    )
    if not source_files:
        log.warning("No .txt / .md / .pdf files found in %s", docs_dir)
        return

    log.info("Found %d document(s) in %s", len(source_files), docs_dir)

    client = genai.Client(api_key=_GEMINI_API_KEY) if not dry_run else None

    engine = create_async_engine(_DATABASE_URL, pool_pre_ping=True, pool_size=3)
    SessionFactory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )

    totals = {"chunks": 0, "inserted": 0, "skipped": 0, "errors": 0}

    async with SessionFactory() as session:
        for path in source_files:
            result = await _process_document(
                path, client, session, chunk_size, chunk_overlap, dry_run
            )
            totals["chunks"] += result.get("chunks", 0)
            totals["inserted"] += result.get("inserted", 0)
            totals["skipped"] += result.get("skipped", 0)
            if "error" in result:
                totals["errors"] += 1

    await engine.dispose()

    log.info(
        "Ingestion complete — %d files | %d chunks | %d inserted | %d skipped | %d errors",
        len(source_files),
        totals["chunks"],
        totals["inserted"],
        totals["skipped"],
        totals["errors"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest KRA tax documents into the Finguard knowledge_base."
    )
    parser.add_argument(
        "--docs",
        type=Path,
        default=Path(__file__).parent / "kra_docs",
        help="Directory containing .txt / .md / .pdf KRA documents (default: scripts/kra_docs/)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"Maximum characters per chunk (default: {DEFAULT_CHUNK_SIZE})",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=DEFAULT_OVERLAP,
        help=f"Overlap characters between consecutive chunks (default: {DEFAULT_OVERLAP})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and chunk documents; skip embedding and database writes.",
    )
    args = parser.parse_args()

    if not dry_run_check(args):
        return

    asyncio.run(
        _run(
            docs_dir=args.docs,
            chunk_size=args.chunk_size,
            chunk_overlap=args.overlap,
            dry_run=args.dry_run,
        )
    )


def dry_run_check(args: argparse.Namespace) -> bool:
    if not args.dry_run and not _GEMINI_API_KEY:
        log.error(
            "GEMINI_API_KEY environment variable is not set.\n"
            "Either set it or run with --dry-run to validate chunking without API calls."
        )
        return False
    return True


if __name__ == "__main__":
    main()
