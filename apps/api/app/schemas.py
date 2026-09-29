import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .db_models import (
    AgentApprovalStatus,
    AgentInterruptStatus,
    AgentMessageRole,
    AgentRunStatus,
    AgentThreadStatus,
    GenerationStatus,
    ProjectStatus,
    ShotStatus,
)


class AuthRegister(BaseModel):
    email: str = Field(
        min_length=5,
        max_length=320,
        pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
    )
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=2, max_length=80)


class AuthLogin(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class AuthGoogleCredential(BaseModel):
    credential: str = Field(min_length=100, max_length=8192)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    created_at: datetime


class ShotBase(BaseModel):
    sequence_number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)
    description: str = ""
    visual_prompt: str = ""
    duration_seconds: int = Field(default=5, ge=1, le=60)


class ShotCreate(ShotBase):
    pass


class ShotUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    visual_prompt: str | None = None
    duration_seconds: int | None = Field(default=None, ge=1, le=60)
    status: ShotStatus | None = None


class ShotRead(ShotBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    status: ShotStatus
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectRead):
    shots: list[ShotRead]


class FeedbackCreate(BaseModel):
    category: str = Field(default="general", min_length=1, max_length=40)
    message: str = Field(min_length=1, max_length=4000)
    project_id: uuid.UUID | None = None
    shot_id: uuid.UUID | None = None
    generation_id: uuid.UUID | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID | None
    shot_id: uuid.UUID | None
    generation_id: uuid.UUID | None
    category: str
    message: str
    context_json: dict[str, Any]
    created_at: datetime


class UploadRead(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID | None = None
    filename: str
    kind: Literal["image"] = "image"
    content_type: str
    size: int
    url: str


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID | None
    shot_id: uuid.UUID | None
    source_upload_id: uuid.UUID | None
    source_generation_id: uuid.UUID | None
    kind: str
    role: str
    filename: str
    content_type: str
    size: int
    url: str
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class GenerationCreate(BaseModel):
    provider: str = Field(
        default="mock",
        pattern="^(mock|openai_compatible|ark_seedream|google_genai|qwen|local_h3)$",
    )
    kind: str = Field(default="video", pattern="^(text|image|video)$")
    node_id: uuid.UUID | None = None
    prompt: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, max_length=160)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=1200, ge=1, le=32_000)
    parameters: dict[str, Any] = Field(default_factory=dict)


class GenerationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shot_id: uuid.UUID
    provider: str
    kind: str
    model: str | None
    node_id: str | None
    input_text: str | None
    temperature: float
    max_tokens: int
    parameters: dict[str, Any]
    status: GenerationStatus
    progress: int
    celery_task_id: str | None
    provider_job_id: str | None
    output_url: str | None
    output_text: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class WorkflowPosition(BaseModel):
    x: float
    y: float


class WorkflowNodeWrite(BaseModel):
    id: uuid.UUID
    type: str = Field(min_length=1, max_length=80)
    version: str = "1.0"
    position: WorkflowPosition
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdgeWrite(BaseModel):
    id: uuid.UUID
    source: uuid.UUID
    target: uuid.UUID
    source_handle: str | None = None
    target_handle: str | None = None


class WorkflowViewport(BaseModel):
    x: float = 30
    y: float = 90
    zoom: float = Field(default=0.78, gt=0)


class WorkflowWrite(BaseModel):
    schema_version: str = "1.0"
    nodes: list[WorkflowNodeWrite]
    edges: list[WorkflowEdgeWrite]
    viewport: WorkflowViewport = Field(default_factory=WorkflowViewport)
    base_revision: int | None = Field(default=None, ge=0)
    operation_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1, max_length=120)


class WorkflowRead(WorkflowWrite):
    # Write-only idempotency key; reads expose the committed key separately.
    operation_id: str | None = None
    id: uuid.UUID
    shot_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    revision: int
    last_operation_id: str | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ProviderCapabilityRead(BaseModel):
    id: str
    kind: str
    label: str
    configured: bool
    model: str
    models: list[str] = Field(default_factory=list)
    requires_api_key: bool


class RuntimeSettingsRead(BaseModel):
    """Safe, non-secret view of the model configuration used by the UI."""

    runtime_enabled: bool
    environment: str
    text_provider: str
    text_model: str
    text_base_url: str
    text_configured: bool
    image_provider: str
    image_model: str
    image_base_url: str
    image_configured: bool
    agent_provider: str
    agent_model: str
    agent_tool_protocol: Literal["auto", "tool_calling", "json"] = "auto"
    agent_capabilities: dict[str, bool] = Field(default_factory=dict)
    qwen_text_model: str
    qwen_text_base_url: str
    qwen_configured: bool
    qwen_image_model: str
    qwen_image_base_url: str
    qwen_image_configured: bool
    local_video_model: str
    local_video_base_url: str
    local_video_request_timeout_seconds: float
    local_video_configured: bool


class RuntimeSettingsUpdate(BaseModel):
    provider: Literal["qwen", "openai_compatible", "local_h3"]
    kind: Literal["text", "image", "video"] = "text"
    api_key: str = Field(default="", max_length=512)
    model: str = Field(min_length=1, max_length=160)
    base_url: str | None = Field(default=None, max_length=500)
    apply_to_agent: bool = True


class RuntimeSettingsTestRequest(RuntimeSettingsUpdate):
    test_tool_calling: bool = False


class RuntimeSettingsTestRead(BaseModel):
    ok: bool
    provider: str
    model: str
    message: str
    tool_calling: bool | None = None


class AgentThreadCreate(BaseModel):
    title: str = Field(default="创作 Agent", min_length=1, max_length=160)


class AgentThreadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    summary: str
    status: AgentThreadStatus
    created_at: datetime
    updated_at: datetime


class AgentMention(BaseModel):
    type: Literal["asset", "node", "shot", "generation"]
    id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=240)


class AgentSkillRead(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    category: str
    tags: list[str]
    source: str
    source_url: str
    stars: int | None
    license: str
    featured: bool


class AgentContextInput(BaseModel):
    project_id: uuid.UUID
    shot_id: uuid.UUID | None = None
    selected_node_ids: list[str] = Field(default_factory=list, max_length=20)
    canvas_version: str | None = Field(default=None, max_length=80)
    canvas_revision: int | None = Field(default=None, ge=0)
    canvas_center: WorkflowPosition | None = None
    mentions: list[AgentMention] = Field(default_factory=list, max_length=24)
    skill_id: str | None = Field(default=None, max_length=120)
    skill_prompt: str | None = Field(default=None, max_length=12_000)


class AgentRunCreate(BaseModel):
    message: str = Field(min_length=1, max_length=12_000)
    context: AgentContextInput


class AgentInterruptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    sequence: int
    kind: str
    decision_key: str
    status: AgentInterruptStatus
    title: str
    description: str
    payload: dict[str, Any]
    response: dict[str, Any] | None
    created_at: datetime
    resolved_at: datetime | None


class AgentInterruptResume(BaseModel):
    interrupt_id: uuid.UUID
    response: dict[str, Any]


class UpdateNodeConfigOperation(BaseModel):
    type: Literal["update_node_config"]
    id: str
    description: str
    node_id: uuid.UUID
    config_patch: dict[str, Any]


class CreateNodeOperation(BaseModel):
    type: Literal["create_node"]
    id: str
    description: str
    node_id: uuid.UUID
    node_type: Literal["generator"] = "generator"
    position: WorkflowPosition
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectNodesOperation(BaseModel):
    type: Literal["connect_nodes"]
    id: str
    description: str
    edge_id: uuid.UUID
    source: uuid.UUID
    target: uuid.UUID


class BindAssetOperation(BaseModel):
    type: Literal["bind_asset"]
    id: str
    description: str
    node_id: uuid.UUID
    asset_id: uuid.UUID
    role: Literal["reference", "first_frame", "last_frame"] = "reference"


CanvasPatchOperation = Annotated[
    UpdateNodeConfigOperation | CreateNodeOperation | ConnectNodesOperation | BindAssetOperation,
    Field(discriminator="type"),
]


class CanvasPatch(BaseModel):
    version: Literal["1.0"] = "1.0"
    shot_id: uuid.UUID
    base_canvas_version: str | None = None
    base_revision: int | None = Field(default=None, ge=0)
    operation_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1, max_length=120)
    operations: list[CanvasPatchOperation] = Field(min_length=1, max_length=10)


class AgentApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    status: AgentApprovalStatus
    summary: str
    risk_level: str
    patch: CanvasPatch
    decision_feedback: str | None
    created_at: datetime
    resolved_at: datetime | None


class AgentApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    feedback: str | None = Field(default=None, max_length=1000)


class AgentApprovalDecisionResult(BaseModel):
    run: "AgentRunRead"
    approval: AgentApprovalRead
    canvas_version: str | None = None
    canvas_revision: int | None = None
    generations: list[GenerationRead] = Field(default_factory=list)


class AgentInterruptResumeResult(BaseModel):
    run: "AgentRunRead"
    interrupt: AgentInterruptRead
    event_cursor: int


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: uuid.UUID
    status: AgentRunStatus
    current_step: str
    context_snapshot: dict[str, Any]
    canvas_version: str | None
    provider: str | None
    model: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    approval: AgentApprovalRead | None = None


class AgentMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: uuid.UUID
    run_id: uuid.UUID | None
    role: AgentMessageRole
    content: str
    message_type: str
    message_metadata: dict[str, Any]
    created_at: datetime


class AgentEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    sequence: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
