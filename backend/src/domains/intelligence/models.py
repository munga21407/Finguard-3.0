import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
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


class ProposalStatus(enum.StrEnum):
    """Human-in-the-loop lifecycle for an agent-proposed, value-changing action.

    The agentic twin of :class:`~src.domains.finance.models.ExpenseApprovalStatus`::

        PROPOSED ─approve─▶ APPLIED
             └────reject──▶ REJECTED

    An agent is always the *maker*: it lands the proposal at PROPOSED with no side
    effect.  A human holding the action's domain permission is the *checker*;
    approving fires the deferred write exactly once (see ``ProposalService``).
    ``native_enum=False`` stores the value as a plain varchar so the column needs
    no PostgreSQL enum type (idempotent migration).
    """

    PROPOSED = "proposed"
    APPLIED = "applied"
    REJECTED = "rejected"


class AgentActionProposal(Base):
    """A value-changing action an agent proposed, awaiting a human sign-off.

    Persists the ephemeral :class:`ProposedStockAction` so a *second* human (≠ the
    person who triggered the agent) can release it.  Segregation of duties is
    enforced in the service layer (``reviewed_by`` ≠ ``triggered_by``); the
    *authority* to approve is enforced at the endpoint via the action's domain
    permission (e.g. ``inventory:adjust``).  ``payload`` holds the exact tool
    arguments so approval can replay the write through the same guarded path.
    """

    __tablename__ = "agent_action_proposals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # The maker: which agent proposed this (denormalised label, matches audit).
    agent_label: Mapped[str] = mapped_column(String(50), nullable=False)
    # "<domain>.<verb>" e.g. "stock.adjustment" — selects the approval permission.
    action_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # Exact tool arguments to replay the guarded write on approval.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # SHA-256 of `payload` at creation time (vc_issuer.payload_hash). Re-checked at
    # approval so a proposal whose payload was altered after the maker proposed it
    # (a manual DB edit, a future bug) is refused rather than silently replayed —
    # see ProposalService.approve.
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(ProposalStatus, native_enum=False, length=20),
        default=ProposalStatus.PROPOSED,
        nullable=False,
        index=True,
    )
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The human who ran the agent (the requester). Strict SoD: cannot self-approve.
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Resulting movement / expense id once applied (audit back-reference).
    applied_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


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


class AgentConfig(Base):
    """Runtime overrides for agent tuning, one row per tuning section.

    The env + code-default layer (``intelligence/tuning.py``) is the floor;
    this table is the **runtime-tunable overlay** an operator changes without a
    redeploy or restart. ``section`` is one of reconciler / watchdog / auditor /
    bankability; ``payload`` is a partial JSON override for that section's
    dataclass. Section-level precedence is env > this table > code default
    (see ``intelligence/db_tuning.py``).

    Lives in the ``finguard`` schema alongside the other agent tables.
    """

    __tablename__ = "agent_config"
    __table_args__ = ({"schema": "finguard"},)

    section: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TaxRateSchedule(Base):
    """Effective-dated Kenya tax rates for Agent F.

    So a historical audit uses period-correct rates, each ``rate_key`` (e.g.
    ``vat_rate``, ``cit_rate``, ``aml_reporting_threshold_kes``) can have several
    rows with different ``effective_from`` dates. Agent F picks, per key, the row
    with the greatest ``effective_from <= as_of``; when no row exists it falls
    back to the ``AuditorTuning`` value (env > agent_config > default).

    Lives in the ``finguard`` schema.
    """

    __tablename__ = "tax_rate_schedule"
    __table_args__ = (
        PrimaryKeyConstraint("rate_key", "effective_from", name="pk_tax_rate_schedule"),
        {"schema": "finguard"},
    )

    rate_key: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[Any] = mapped_column(Date, nullable=False)
    rate: Mapped[Any] = mapped_column(Numeric(20, 6), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ClassificationFeedback(Base):
    """A user correction to an Agent B transaction classification (Sprint 5).

    When a user overrides the suggested category, the narrative + the corrected
    label are stored here with a 768-dim embedding of the narrative, so future
    classifications can retrieve the nearest past corrections as few-shot
    examples (vector similarity) — breaking Agent B's zero-shot accuracy ceiling.

    Lives in the ``finguard`` schema alongside the pgvector knowledge base.
    """

    __tablename__ = "classification_feedback"
    __table_args__ = (
        Index(
            "ix_classification_feedback_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_ops={"embedding": "vector_l2_ops"},
        ),
        {"schema": "finguard"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_category: Mapped[str | None] = mapped_column(String(64))
    corrected_category: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[Any | None] = mapped_column(Vector(768), nullable=True)
    corrected_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KnowledgeBase(Base):
    """
    KRA knowledge-base chunks used by the Tax RAG service (Agent F).

    Each row is one document section with a pre-computed the model
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
        # Idempotent ingest key: ``ON CONFLICT (document_title, section_key)``
        # in the KRA ingest pipeline relies on this. Declared on the ORM (not
        # just migration 0001) so the test schema built via ``create_all`` has it.
        UniqueConstraint(
            "document_title", "section_key", name="uq_knowledge_base_title_section"
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
