import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database.postgres import Base


class AgentRunStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus), default=AgentRunStatus.PENDING, nullable=False
    )
    input_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentEModel(Base):
    """A persisted, serialized Agent E IsolationForest, one per customer.

    Agent E's anomaly model used to be re-fit on every scoring call (noisy,
    wasteful, no per-customer memory).  The ``batch.retrain_agent_e_models``
    Celery task now fits one forest per customer over the trailing 90 days of
    categorized transactions and upserts its serialized bytes here, keyed by
    ``customer_id``.  The watchdog loads the row at scoring time and only falls
    back to an on-the-fly fit (plus an async background fit) for a brand-new
    customer with no model yet.

    Lives in the ``finguard`` schema alongside the pgvector knowledge base.
    Retraining upserts in place and bumps ``version``.
    """

    __tablename__ = "agent_e_models"
    __table_args__ = ({"schema": "finguard"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, index=True
    )
    model_type: Mapped[str] = mapped_column(String(100), nullable=False, default="isolation_forest")
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    n_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KnowledgeBase(Base):
    """
    KRA knowledge-base chunks used by the Tax RAG service (Agent F).

    Each row is one document section with a pre-computed Gemini
    text-embedding-004 vector (768 dims) stored via pgvector.
    The pgvector `<->` (L2) operator in tax_rag_service.py queries this table.
    """

    __tablename__ = "knowledge_base"
    __table_args__ = (
        Index(
            "ix_knowledge_base_vector_embeddings",
            "vector_embeddings",
            postgresql_using="ivfflat",
            postgresql_ops={"vector_embeddings": "vector_l2_ops"},
        ),
        {"schema": "finguard"},
    )

    kb_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_title: Mapped[str] = mapped_column(String(512), nullable=False)
    section_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    vector_embeddings: Mapped[Any] = mapped_column(Vector(768), nullable=False)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
