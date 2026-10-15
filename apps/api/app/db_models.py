import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class ProjectStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ShotStatus(str, enum.Enum):
    DRAFT = "draft"
    READY = "ready"
    GENERATING = "generating"
    REVIEW = "review"
    APPROVED = "approved"


class GenerationStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AgentThreadStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class AgentRunStatus(str, enum.Enum):
    THINKING = "thinking"
    PLANNING = "planning"
    WAITING_USER = "waiting_user"
    WAITING_APPROVAL = "waiting_approval"
    EXECUTING = "executing"
    WAITING_EXTERNAL_JOB = "waiting_external_job"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentMessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class AgentApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AgentInterruptStatus(str, enum.Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(320))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    identities: Mapped[list["UserIdentity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    uploads: Mapped[list["StoredUpload"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(back_populates="user")
    wallet: Mapped["UserWallet | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="sessions")


class UserIdentity(Base):
    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="uq_user_identity_provider_subject"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32), index=True)
    provider_subject: Mapped[str] = mapped_column(String(255), index=True)
    provider_email: Mapped[str] = mapped_column(String(320))
    profile_name: Mapped[str] = mapped_column(String(160), default="")
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="identities")


class StoredUpload(Base):
    __tablename__ = "stored_uploads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="uploads")
    asset: Mapped["Asset | None"] = relationship(back_populates="source_upload", uselist=False)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus), default=ProjectStatus.DRAFT
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    shots: Mapped[list["Shot"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Shot.sequence_number"
    )
    user: Mapped[User | None] = relationship(back_populates="projects")
    agent_threads: Mapped[list["AgentThread"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Shot(Base):
    __tablename__ = "shots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    visual_prompt: Mapped[str] = mapped_column(Text, default="")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[ShotStatus] = mapped_column(Enum(ShotStatus), default=ShotStatus.DRAFT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="shots")
    generations: Mapped[list["Generation"]] = relationship(
        back_populates="shot", cascade="all, delete-orphan", order_by="Generation.created_at"
    )


class Generation(Base):
    __tablename__ = "generations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    shot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(80), default="mock")
    kind: Mapped[str] = mapped_column(String(32), default="video")
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, default=1200)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    status: Mapped[GenerationStatus] = mapped_column(
        Enum(GenerationStatus), default=GenerationStatus.QUEUED, index=True
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)
    celery_task_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    provider_job_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    output_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_credits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    shot: Mapped[Shot] = relationship(back_populates="generations")
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="source_generation", cascade="all, delete-orphan"
    )


class Asset(Base):
    """Project-scoped media registry for uploads and generation outputs."""

    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    shot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shots.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_upload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stored_uploads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_generation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), default="image", index=True)
    role: Mapped[str] = mapped_column(String(40), default="reference", index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer, default=0)
    url: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="assets")
    project: Mapped[Project | None] = relationship(back_populates="assets")
    source_upload: Mapped[StoredUpload | None] = relationship(back_populates="asset")
    source_generation: Mapped[Generation | None] = relationship(back_populates="assets")


class Feedback(Base):
    """Small, project-scoped feedback record for beta-user issue reports."""

    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    shot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shots.id", ondelete="SET NULL"), nullable=True, index=True
    )
    generation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(String(40), default="general", index=True)
    message: Mapped[str] = mapped_column(Text)
    context_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    shot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), unique=True, index=True
    )
    schema_version: Mapped[str] = mapped_column(String(20), default="1.0")
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_operation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_operation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    viewport: Mapped[dict[str, float]] = mapped_column(
        JSON, default=lambda: {"x": 30.0, "y": 90.0, "zoom": 0.78}
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    nodes: Mapped[list["WorkflowNode"]] = relationship(
        cascade="all, delete-orphan", order_by="WorkflowNode.created_at"
    )
    edges: Mapped[list["WorkflowEdge"]] = relationship(
        cascade="all, delete-orphan", order_by="WorkflowEdge.created_at"
    )


class WorkflowNode(Base):
    __tablename__ = "workflow_nodes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(80))
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    position_x: Mapped[float] = mapped_column(Float)
    position_y: Mapped[float] = mapped_column(Float)
    config: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def position(self) -> dict[str, float]:
        return {"x": self.position_x, "y": self.position_y}


class WorkflowEdge(Base):
    __tablename__ = "workflow_edges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[uuid.UUID] = mapped_column(Uuid)
    target: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_handle: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_handle: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentThread(Base):
    __tablename__ = "agent_threads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(160), default="创作 Agent")
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[AgentThreadStatus] = mapped_column(
        Enum(AgentThreadStatus), default=AgentThreadStatus.ACTIVE, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="agent_threads")
    messages: Mapped[list["AgentMessage"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", order_by="AgentMessage.created_at"
    )
    runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", order_by="AgentRun.created_at"
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_threads.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus), default=AgentRunStatus.THINKING, index=True
    )
    current_step: Mapped[str] = mapped_column(String(80), default="load_context")
    context_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    canvas_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    thread: Mapped[AgentThread] = relationship(back_populates="runs")
    messages: Mapped[list["AgentMessage"]] = relationship(back_populates="run")
    events: Mapped[list["AgentEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentEvent.sequence"
    )
    approval: Mapped["AgentApproval | None"] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )
    interrupts: Mapped[list["AgentInterrupt"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentInterrupt.sequence"
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_threads.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    role: Mapped[AgentMessageRole] = mapped_column(Enum(AgentMessageRole), index=True)
    content: Mapped[str] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(String(40), default="text")
    message_metadata: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )

    thread: Mapped[AgentThread] = relationship(back_populates="messages")
    run: Mapped[AgentRun | None] = relationship(back_populates="messages")


class AgentEvent(Base):
    __tablename__ = "agent_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[AgentRun] = relationship(back_populates="events")


class AgentApproval(Base):
    """Durable interrupt payload for the future LangGraph pause/resume boundary."""

    __tablename__ = "agent_approvals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[AgentApprovalStatus] = mapped_column(
        Enum(AgentApprovalStatus), default=AgentApprovalStatus.PENDING, index=True
    )
    summary: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(20), default="low")
    patch: Mapped[dict[str, object]] = mapped_column(JSON)
    decision_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[AgentRun] = relationship(back_populates="approval")


class AgentInterrupt(Base):
    """General human-in-the-loop checkpoint, compatible with LangGraph interrupts."""

    __tablename__ = "agent_interrupts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    decision_key: Mapped[str] = mapped_column(String(80))
    status: Mapped[AgentInterruptStatus] = mapped_column(
        Enum(AgentInterruptStatus), default=AgentInterruptStatus.PENDING, index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    response: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[AgentRun] = relationship(back_populates="interrupts")


class UserWallet(Base):
    __tablename__ = "user_wallets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    balance: Mapped[int] = mapped_column(Integer, default=0)
    frozen: Mapped[int] = mapped_column(Integer, default=0)
    total_earned: Mapped[int] = mapped_column(Integer, default=0)
    total_spent: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="wallet")
    transactions: Mapped[list["CreditTransaction"]] = relationship(
        back_populates="wallet", cascade="all, delete-orphan", order_by="CreditTransaction.created_at.desc()"
    )


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_wallets.id", ondelete="CASCADE"), index=True
    )
    amount: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(32))  # freeze, unfreeze, consume, refund, grant, redeem
    biz_type: Mapped[str] = mapped_column(String(32))  # text_generation, image_generation, video_generation, agent_run, gift, code, admin
    biz_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    wallet: Mapped[UserWallet] = relationship(back_populates="transactions")


class CreditCardCode(Base):
    __tablename__ = "credit_card_codes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    credits: Mapped[int] = mapped_column(Integer)
    is_redeemed: Mapped[bool] = mapped_column(Boolean, default=False)
    redeemed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

