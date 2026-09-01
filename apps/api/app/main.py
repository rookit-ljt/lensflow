import base64
import binascii
import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .agent_canvas import CanvasPatchError
from .agent_service import (
    append_agent_event,
    execute_agent_run,
    fail_agent_approval,
    resolve_agent_approval,
    resolve_agent_interrupt,
    resume_agent_run,
)
from .agent_skills import get_skill, list_skills
from .auth import (
    CurrentUser,
    clear_auth_cookie,
    create_auth_session,
    hash_password,
    normalize_email,
    session_token_hash,
    set_auth_cookie,
    verify_password,
)
from .config import get_settings
from .database import (
    Base,
    SessionLocal,
    engine,
    ensure_auth_columns,
    ensure_generation_columns,
    ensure_workflow_columns,
    get_session,
)
from .db_models import (
    AgentApproval,
    AgentApprovalStatus,
    AgentEvent,
    AgentInterrupt,
    AgentInterruptStatus,
    AgentMessage,
    AgentMessageRole,
    AgentRun,
    AgentRunStatus,
    AgentThread,
    Asset,
    AuthSession,
    Feedback,
    Generation,
    GenerationStatus,
    Project,
    Shot,
    ShotStatus,
    StoredUpload,
    User,
    UserIdentity,
    Workflow,
    WorkflowNode,
)
from .google_identity import GoogleIdentityError, verify_google_id_token
from .providers import OpenAICompatibleTextProvider, QwenTextProvider
from .providers.base import GenerationRequest
from .runtime_settings import apply_settings, settings_view
from .schemas import (
    AgentApprovalDecision,
    AgentApprovalDecisionResult,
    AgentApprovalRead,
    AgentEventRead,
    AgentInterruptRead,
    AgentInterruptResume,
    AgentInterruptResumeResult,
    AgentMessageRead,
    AgentRunCreate,
    AgentRunRead,
    AgentSkillRead,
    AgentThreadCreate,
    AgentThreadRead,
    AssetRead,
    AuthGoogleCredential,
    AuthLogin,
    AuthRegister,
    FeedbackCreate,
    FeedbackRead,
    GenerationCreate,
    GenerationRead,
    HealthResponse,
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
    ProviderCapabilityRead,
    RuntimeSettingsRead,
    RuntimeSettingsTestRead,
    RuntimeSettingsUpdate,
    ShotCreate,
    ShotRead,
    ShotUpdate,
    UploadRead,
    UserRead,
    WorkflowRead,
    WorkflowWrite,
)
from .tasks import generate_shot
from .uploads import detect_image_type, find_uploaded_image, store_uploaded_image
from .video_frames import extract_last_video_frame
from .workflows import WorkflowVersionConflict, get_or_create_workflow, replace_workflow


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_generation_columns()
    ensure_auth_columns()
    ensure_workflow_columns()
    yield


settings = get_settings()
DatabaseSession = Annotated[Session, Depends(get_session)]
QWEN_TEXT_MODELS = (
    "qwen3.7-plus",
    "qwen3.7-max",
    "qwen3.7-flash",
    "qwen-plus",
)
QWEN_IMAGE_MODELS = (
    "qwen-image-2.0-pro",
    "qwen-image-2.0",
    "qwen-image-plus",
    "qwen-image",
)
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Project, shot and workflow control plane for LibTV.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="libtv-api", version="0.1.0")


def _owned_project(session: Session, user: User, project_id: uuid.UUID) -> Project:
    project = session.scalar(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _owned_shot(session: Session, user: User, shot_id: uuid.UUID) -> Shot:
    shot = session.scalar(
        select(Shot)
        .join(Project, Project.id == Shot.project_id)
        .where(Shot.id == shot_id, Project.user_id == user.id)
    )
    if shot is None:
        raise HTTPException(status_code=404, detail="Shot not found")
    return shot


def _owned_thread(session: Session, user: User, thread_id: uuid.UUID) -> AgentThread:
    thread = session.scalar(
        select(AgentThread)
        .join(Project, Project.id == AgentThread.project_id)
        .where(AgentThread.id == thread_id, Project.user_id == user.id)
    )
    if thread is None:
        raise HTTPException(status_code=404, detail="Agent thread not found")
    return thread


def _owned_run(session: Session, user: User, run_id: uuid.UUID) -> AgentRun:
    run = session.scalar(
        select(AgentRun)
        .join(AgentThread, AgentThread.id == AgentRun.thread_id)
        .join(Project, Project.id == AgentThread.project_id)
        .where(AgentRun.id == run_id, Project.user_id == user.id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


def _owned_generation(session: Session, user: User, generation_id: uuid.UUID) -> Generation:
    generation = session.scalar(
        select(Generation)
        .join(Shot, Shot.id == Generation.shot_id)
        .join(Project, Project.id == Shot.project_id)
        .where(Generation.id == generation_id, Project.user_id == user.id)
    )
    if generation is None:
        raise HTTPException(status_code=404, detail="Generation not found")
    return generation


def _owned_asset(session: Session, user: User, asset_id: uuid.UUID) -> Asset:
    asset = session.scalar(
        select(Asset).where(Asset.id == asset_id, Asset.user_id == user.id)
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


def _workflow_contains_cycle(edges: list[object]) -> bool:
    adjacency: dict[object, list[object]] = {}
    for edge in edges:
        source = edge.source
        target = edge.target
        adjacency.setdefault(source, []).append(target)
    visiting: set[object] = set()
    visited: set[object] = set()

    def visit(node: object) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in adjacency.get(node, [])):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in adjacency)


def _config_references_asset(
    value: object,
    asset_id: uuid.UUID,
    source_upload_id: uuid.UUID | None,
) -> bool:
    """Recognize asset references persisted inside workflow node JSON configs."""
    asset_value = str(asset_id)
    upload_value = str(source_upload_id) if source_upload_id is not None else None
    if isinstance(value, list):
        return any(
            _config_references_asset(item, asset_id, source_upload_id)
            for item in value
        )
    if not isinstance(value, dict):
        return False
    for key, item in value.items():
        if key == "asset_id" and str(item) == asset_value:
            return True
        if upload_value is not None and key in {"id", "source_upload_id"} and str(item) == upload_value:
            return True
        if _config_references_asset(item, asset_id, source_upload_id):
            return True
    return False


def _asset_reference_count(session: Session, asset: Asset) -> int:
    if asset.project_id is None:
        return 0
    configs = session.scalars(
        select(WorkflowNode.config)
        .join(Workflow, Workflow.id == WorkflowNode.workflow_id)
        .join(Shot, Shot.id == Workflow.shot_id)
        .where(Shot.project_id == asset.project_id)
    )
    return sum(
        1
        for config in configs
        if _config_references_asset(config, asset.id, asset.source_upload_id)
    )


def _require_owned_upload(session: Session, user: User, upload_id: uuid.UUID) -> None:
    owner_id = session.scalar(
        select(StoredUpload.user_id).where(StoredUpload.id == upload_id)
    )
    if owner_id == user.id:
        return
    if owner_id is None:
        first_user_id = session.scalar(select(User.id).order_by(User.created_at, User.id).limit(1))
        if first_user_id == user.id:
            return
    raise HTTPException(status_code=404, detail="Upload not found")


def _enqueue_generation(
    session: Session,
    generation: Generation,
    background_tasks: BackgroundTasks,
) -> Generation:
    """Dispatch a persisted generation using the configured local/worker mode."""
    generation_id = generation.id
    if generation.provider == "local_h3" and settings.celery_task_always_eager:
        generation.celery_task_id = f"background-{generation_id}"
        session.commit()
        session.refresh(generation)
        background_tasks.add_task(generate_shot.run, str(generation_id))
        return generation

    try:
        task_result = generate_shot.delay(str(generation_id))
    except Exception as exc:
        session.expire_all()
        failed = session.get(Generation, generation_id)
        if failed is None:
            raise HTTPException(status_code=500, detail="Generation record was lost") from exc
        failed.status = GenerationStatus.FAILED
        failed.error = f"任务队列不可用：{exc}"
        session.commit()
        raise HTTPException(status_code=503, detail="Generation queue is unavailable") from exc

    session.expire_all()
    queued = session.get(Generation, generation_id)
    if queued is None:
        raise HTTPException(status_code=500, detail="Generation record was lost")
    queued.celery_task_id = task_result.id
    session.commit()
    session.refresh(queued)
    return queued


@app.post(
    "/api/auth/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    tags=["auth"],
)
def register_user(
    payload: AuthRegister,
    response: Response,
    session: DatabaseSession,
) -> User:
    email = normalize_email(payload.email)
    if session.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="该邮箱已经注册")
    is_first_user = int(session.scalar(select(func.count(User.id))) or 0) == 0
    user = User(
        email=email,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
    )
    session.add(user)
    try:
        session.flush()
        if is_first_user:
            session.execute(
                update(Project).where(Project.user_id.is_(None)).values(user_id=user.id)
            )
        token = create_auth_session(session, user, settings)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="该邮箱已经注册") from exc
    session.refresh(user)
    set_auth_cookie(response, token, settings)
    return user


@app.post("/api/auth/login", response_model=UserRead, tags=["auth"])
def login_user(payload: AuthLogin, response: Response, session: DatabaseSession) -> User:
    user = session.scalar(select(User).where(User.email == normalize_email(payload.email)))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")
    token = create_auth_session(session, user, settings)
    session.commit()
    set_auth_cookie(response, token, settings)
    return user


@app.post("/api/auth/google", response_model=UserRead, tags=["auth"])
def login_with_google(
    payload: AuthGoogleCredential,
    response: Response,
    session: DatabaseSession,
) -> User:
    if not settings.google_client_id.strip():
        raise HTTPException(status_code=503, detail="Google 登录尚未配置")
    try:
        google_identity = verify_google_id_token(
            payload.credential,
            settings.google_client_id,
        )
    except GoogleIdentityError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    identity = session.scalar(
        select(UserIdentity)
        .where(
            UserIdentity.provider == "google",
            UserIdentity.provider_subject == google_identity.subject,
        )
        .options(selectinload(UserIdentity.user))
    )
    if identity is not None:
        user = identity.user
        if not user.is_active:
            raise HTTPException(status_code=403, detail="账号已被停用")
        identity.provider_email = google_identity.email
        identity.profile_name = google_identity.name
        identity.avatar_url = google_identity.picture
    else:
        existing_user = session.scalar(select(User).where(User.email == google_identity.email))
        if existing_user is not None:
            raise HTTPException(
                status_code=409,
                detail="该邮箱已有密码账号，请继续使用邮箱密码登录",
            )
        is_first_user = int(session.scalar(select(func.count(User.id))) or 0) == 0
        display_name = (google_identity.name or google_identity.email.split("@", 1)[0])[:80]
        user = User(
            email=google_identity.email,
            display_name=display_name,
            password_hash="external$google",
        )
        session.add(user)
        session.flush()
        session.add(
            UserIdentity(
                user_id=user.id,
                provider="google",
                provider_subject=google_identity.subject,
                provider_email=google_identity.email,
                profile_name=google_identity.name,
                avatar_url=google_identity.picture,
            )
        )
        if is_first_user:
            session.execute(
                update(Project).where(Project.user_id.is_(None)).values(user_id=user.id)
            )

    try:
        token = create_auth_session(session, user, settings)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Google 账号关联冲突，请重试") from exc
    session.refresh(user)
    set_auth_cookie(response, token, settings)
    return user


@app.get("/api/auth/me", response_model=UserRead, tags=["auth"])
def get_current_user(user: CurrentUser) -> User:
    return user


@app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["auth"])
def logout_user(request: Request, response: Response, session: DatabaseSession) -> Response:
    token = request.cookies.get(settings.auth_cookie_name)
    if token:
        auth_session = session.scalar(
            select(AuthSession).where(AuthSession.token_hash == session_token_hash(token))
        )
        if auth_session is not None:
            session.delete(auth_session)
            session.commit()
    clear_auth_cookie(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@app.get("/api/providers", response_model=list[ProviderCapabilityRead], tags=["system"])
def list_provider_capabilities(_user: CurrentUser) -> list[ProviderCapabilityRead]:
    capabilities = [
        ProviderCapabilityRead(
            id="openai_compatible",
            kind="text",
            label="当前文本服务",
            configured=bool(settings.text_api_key.strip() and settings.text_model.strip()),
            model=settings.text_model,
            models=[settings.text_model] if settings.text_model else [],
            requires_api_key=True,
        ),
        ProviderCapabilityRead(
            id="qwen",
            kind="text",
            label="阿里云百炼 · 千问文本",
            configured=bool(settings.qwen_api_key.strip() and settings.qwen_text_model.strip()),
            model=settings.qwen_text_model,
            models=list(dict.fromkeys((settings.qwen_text_model, *QWEN_TEXT_MODELS))),
            requires_api_key=True,
        ),
        ProviderCapabilityRead(
            id="mock",
            kind="image",
            label="Mock 图片流程",
            configured=True,
            model="mock-image",
            models=["mock-image"],
            requires_api_key=False,
        ),
        ProviderCapabilityRead(
            id="local_h3",
            kind="video",
            label="本地 MiniMax H3",
            configured=bool(settings.local_video_base_url.strip()),
            model=settings.local_video_model,
            models=[settings.local_video_model],
            requires_api_key=False,
        ),
        ProviderCapabilityRead(
            id="mock",
            kind="video",
            label="Mock 视频流程",
            configured=True,
            model="mock-video",
            models=["mock-video"],
            requires_api_key=False,
        ),
    ]
    provider_labels = {
        "ark_seedream": "火山方舟 Seedream",
        "google_genai": "Google Gemini 图片模型",
        "openai_compatible": "OpenAI-compatible 图片模型",
    }
    if settings.image_provider in provider_labels:
        capabilities.append(
            ProviderCapabilityRead(
                id=settings.image_provider,
                kind="image",
                label=provider_labels[settings.image_provider],
                configured=bool(settings.image_api_key.strip() and settings.image_model.strip()),
                model=settings.image_model,
                models=[settings.image_model] if settings.image_model else [],
                requires_api_key=True,
            )
        )
    capabilities.append(
        ProviderCapabilityRead(
            id="qwen",
            kind="image",
            label="阿里云百炼 · 千问图片",
            configured=bool(settings.qwen_api_key.strip() and settings.qwen_image_model.strip()),
            model=settings.qwen_image_model,
            models=list(dict.fromkeys((settings.qwen_image_model, *QWEN_IMAGE_MODELS))),
            requires_api_key=True,
        )
    )
    return capabilities


def _ensure_runtime_settings_enabled() -> None:
    if settings.environment != "development" or not settings.runtime_settings_enabled:
        raise HTTPException(status_code=403, detail="运行时模型配置仅在开发环境开放")


@app.get("/api/settings", response_model=RuntimeSettingsRead, tags=["settings"])
def get_runtime_settings(_user: CurrentUser) -> RuntimeSettingsRead:
    _ensure_runtime_settings_enabled()
    return RuntimeSettingsRead(**settings_view(settings))


@app.put("/api/settings", response_model=RuntimeSettingsRead, tags=["settings"])
def update_runtime_settings(payload: RuntimeSettingsUpdate, _user: CurrentUser) -> RuntimeSettingsRead:
    _ensure_runtime_settings_enabled()
    try:
        apply_settings(settings, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RuntimeSettingsRead(**settings_view(settings))


@app.post("/api/settings/test", response_model=RuntimeSettingsTestRead, tags=["settings"])
def test_runtime_settings(payload: RuntimeSettingsUpdate, _user: CurrentUser) -> RuntimeSettingsTestRead:
    _ensure_runtime_settings_enabled()
    if payload.kind != "text":
        return RuntimeSettingsTestRead(
            ok=False,
            provider=payload.provider,
            model=payload.model,
            message="图片模型不会在设置页发起计费请求，请保存后在图片节点中验证。",
        )
    try:
        api_key = payload.api_key.strip()
        if not api_key:
            api_key = settings.qwen_api_key if payload.provider == "qwen" else settings.text_api_key
        if not api_key:
            raise ValueError("请输入 API Key")
        model = payload.model.strip()
        base_url = (payload.base_url or "").strip()
        temporary = settings.model_copy(deep=True)
        if payload.provider == "qwen":
            temporary.qwen_api_key = api_key
            temporary.qwen_text_model = model
            if base_url:
                temporary.qwen_text_base_url = base_url
            provider = QwenTextProvider(temporary)
        else:
            temporary.text_api_key = api_key
            temporary.text_model = model
            if base_url:
                temporary.text_base_url = base_url
            provider = OpenAICompatibleTextProvider(temporary)
        provider.generate(
            GenerationRequest(
                generation_id=f"settings-test-{uuid.uuid4().hex}",
                shot_id="settings-test",
                title="设置连通性测试",
                prompt="请只回复：连接成功。不要补充其他内容。",
                duration_seconds=1,
                model=model,
                temperature=0,
                max_tokens=32,
            )
        )
    except (RuntimeError, ValueError, httpx.HTTPError) as exc:
        safe_message = str(exc).replace(api_key, "***") if api_key else str(exc)
        return RuntimeSettingsTestRead(ok=False, provider=payload.provider, model=payload.model, message=safe_message)
    return RuntimeSettingsTestRead(ok=True, provider=payload.provider, model=payload.model, message="连接成功，模型可以正常响应。")


@app.post(
    "/api/uploads",
    response_model=UploadRead,
    status_code=status.HTTP_201_CREATED,
    tags=["uploads"],
)
async def upload_image(
    request: Request,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    session: DatabaseSession,
    user: CurrentUser,
    project_id: uuid.UUID | None = None,
) -> UploadRead:
    if project_id is not None:
        _owned_project(session, user, project_id)
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > settings.upload_max_bytes:
        raise HTTPException(status_code=413, detail="图片不能超过 10MB")
    buffer = bytearray()
    async for chunk in request.stream():
        if len(buffer) + len(chunk) > settings.upload_max_bytes:
            raise HTTPException(status_code=413, detail="图片不能超过 10MB")
        buffer.extend(chunk)
    content = bytes(buffer)
    if not content:
        raise HTTPException(status_code=422, detail="上传图片内容为空")
    media_type = detect_image_type(content)
    if media_type is None:
        raise HTTPException(status_code=415, detail="仅支持 PNG、JPG、WebP 和 GIF 图片")

    upload_id = uuid.uuid4()
    store_uploaded_image(settings, upload_id, content, media_type)
    upload = StoredUpload(
        id=upload_id,
        user_id=user.id,
        filename=filename,
        content_type=media_type,
        size=len(content),
    )
    session.add(upload)
    asset = Asset(
        user_id=user.id,
        project_id=project_id,
        source_upload_id=upload_id,
        kind="image",
        role="reference",
        filename=filename,
        content_type=media_type,
        size=len(content),
        url=str(request.url_for("read_upload", upload_id=upload_id)),
        metadata_json={"source": "upload"},
    )
    session.add(asset)
    session.commit()
    return UploadRead(
        id=upload_id,
        asset_id=asset.id,
        filename=filename,
        content_type=media_type,
        size=len(content),
        url=str(request.url_for("read_upload", upload_id=upload_id)),
    )


@app.get(
    "/api/projects/{project_id}/assets",
    response_model=list[AssetRead],
    tags=["assets"],
)
def list_project_assets(
    project_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
    kind: str | None = Query(default=None, max_length=32),
    q: str | None = Query(default=None, max_length=120),
) -> list[Asset]:
    _owned_project(session, user, project_id)
    statement = (
        select(Asset)
        .where(Asset.project_id == project_id)
        .order_by(Asset.created_at.desc())
    )
    if kind:
        statement = statement.where(Asset.kind == kind)
    if q:
        statement = statement.where(Asset.filename.ilike(f"%{q}%"))
    return list(session.scalars(statement))


@app.get(
    "/api/assets/{asset_id}",
    response_model=AssetRead,
    tags=["assets"],
)
def get_asset(
    asset_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> Asset:
    return _owned_asset(session, user, asset_id)


@app.delete(
    "/api/assets/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["assets"],
)
def delete_asset(
    asset_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> Response:
    asset = _owned_asset(session, user, asset_id)
    reference_count = _asset_reference_count(session, asset)
    if reference_count:
        raise HTTPException(
            status_code=409,
            detail=f"资产仍被 {reference_count} 个画布节点引用，请先从节点移除",
        )

    source_upload = asset.source_upload
    upload_path = None
    if source_upload is not None:
        located = find_uploaded_image(settings, source_upload.id)
        upload_path = located[0] if located is not None else None

    session.delete(asset)
    if source_upload is not None:
        session.delete(source_upload)
    session.commit()
    if upload_path is not None:
        upload_path.unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/uploads/{upload_id}", name="read_upload", tags=["uploads"])
def read_upload(
    upload_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> FileResponse:
    _require_owned_upload(session, user, upload_id)
    located = find_uploaded_image(settings, upload_id)
    if located is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    path, media_type = located
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/api/projects", response_model=list[ProjectRead], tags=["projects"])
def list_projects(session: DatabaseSession, user: CurrentUser) -> list[Project]:
    return list(
        session.scalars(
            select(Project)
            .where(Project.user_id == user.id)
            .order_by(Project.updated_at.desc())
        )
    )


@app.post(
    "/api/projects",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    tags=["projects"],
)
def create_project(
    payload: ProjectCreate,
    session: DatabaseSession,
    user: CurrentUser,
) -> Project:
    project = Project(user_id=user.id, name=payload.name, description=payload.description)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@app.get("/api/projects/{project_id}", response_model=ProjectDetail, tags=["projects"])
def get_project(
    project_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> Project:
    statement = (
        select(Project)
        .where(Project.id == project_id, Project.user_id == user.id)
        .options(selectinload(Project.shots))
    )
    project = session.scalar(statement)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.get("/api/projects/{project_id}/export", tags=["projects"])
def export_project(
    project_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> Response:
    """Export a portable JSON backup of project structure and run metadata."""
    project = _owned_project(session, user, project_id)
    shots = list(
        session.scalars(
            select(Shot).where(Shot.project_id == project_id).order_by(Shot.sequence_number)
        )
    )
    assets = list(
        session.scalars(
            select(Asset).where(Asset.project_id == project_id).order_by(Asset.created_at)
        )
    )
    workflows = []
    for shot in shots:
        workflow = get_or_create_workflow(session, shot)
        workflows.append({
            "id": str(workflow.id),
            "shot_id": str(workflow.shot_id),
            "schema_version": workflow.schema_version,
            "revision": workflow.revision,
            "viewport": workflow.viewport,
            "nodes": [
                {
                    "id": str(node.id),
                    "type": node.type,
                    "version": node.version,
                    "position": {"x": node.position_x, "y": node.position_y},
                    "config": node.config,
                }
                for node in workflow.nodes
            ],
            "edges": [
                {
                    "id": str(edge.id),
                    "source": str(edge.source),
                    "target": str(edge.target),
                    "source_handle": edge.source_handle,
                    "target_handle": edge.target_handle,
                }
                for edge in workflow.edges
            ],
        })
    generations = list(
        session.scalars(
            select(Generation)
            .join(Shot, Shot.id == Generation.shot_id)
            .where(Shot.project_id == project_id)
            .order_by(Generation.created_at)
        )
    )
    threads = list(
        session.scalars(
            select(AgentThread).where(AgentThread.project_id == project_id).order_by(AgentThread.created_at)
        )
    )

    def iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    export = {
        "format": "libtv-project-backup",
        "version": "1.0",
        "exported_at": datetime.now(UTC).isoformat(),
        "project": {
            "id": str(project.id),
            "name": project.name,
            "description": project.description,
            "status": project.status.value,
            "created_at": iso(project.created_at),
            "updated_at": iso(project.updated_at),
        },
        "shots": [
            {
                "id": str(shot.id),
                "sequence_number": shot.sequence_number,
                "title": shot.title,
                "description": shot.description,
                "visual_prompt": shot.visual_prompt,
                "duration_seconds": shot.duration_seconds,
                "status": shot.status.value,
                "created_at": iso(shot.created_at),
                "updated_at": iso(shot.updated_at),
            }
            for shot in shots
        ],
        "workflows": workflows,
        "assets": [
            {
                "id": str(asset.id),
                "shot_id": str(asset.shot_id) if asset.shot_id else None,
                "source_generation_id": str(asset.source_generation_id) if asset.source_generation_id else None,
                "kind": asset.kind,
                "role": asset.role,
                "filename": asset.filename,
                "content_type": asset.content_type,
                "size": asset.size,
                "url": asset.url,
                "metadata": asset.metadata_json,
                "created_at": iso(asset.created_at),
            }
            for asset in assets
        ],
        "generations": [
            {
                "id": str(item.id),
                "shot_id": str(item.shot_id),
                "node_id": item.node_id,
                "provider": item.provider,
                "kind": item.kind,
                "model": item.model,
                "input_text": item.input_text,
                "parameters": item.parameters,
                "status": item.status.value,
                "progress": item.progress,
                "provider_job_id": item.provider_job_id,
                "output_url": item.output_url,
                "output_text": item.output_text,
                "error": item.error,
                "created_at": iso(item.created_at),
                "updated_at": iso(item.updated_at),
            }
            for item in generations
        ],
        "agent_threads": [
            {
                "id": str(thread.id),
                "title": thread.title,
                "summary": thread.summary,
                "status": thread.status.value,
                "messages": [
                    {
                        "id": str(message.id),
                        "run_id": str(message.run_id) if message.run_id else None,
                        "role": message.role.value,
                        "content": message.content,
                        "message_type": message.message_type,
                        "metadata": message.message_metadata,
                        "created_at": iso(message.created_at),
                    }
                    for message in thread.messages
                ],
            }
            for thread in threads
        ],
        "note": "资产 URL 指向当前部署；此 JSON 不包含二进制文件，请同时备份 uploads 目录或对象存储。",
    }
    content = json.dumps(export, ensure_ascii=False, indent=2, default=str)
    filename = f"libtv-project-{project.id.hex[:8]}.json"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post(
    "/api/feedback",
    response_model=FeedbackRead,
    status_code=status.HTTP_201_CREATED,
    tags=["feedback"],
)
def submit_feedback(
    payload: FeedbackCreate,
    session: DatabaseSession,
    user: CurrentUser,
) -> Feedback:
    """Store a beta user's issue report with only the selected runtime context."""
    project_id = payload.project_id
    shot_id = payload.shot_id
    generation_id = payload.generation_id
    if project_id:
        _owned_project(session, user, project_id)
    if shot_id:
        shot = _owned_shot(session, user, shot_id)
        if project_id and shot.project_id != project_id:
            raise HTTPException(status_code=400, detail="镜头不属于当前项目")
        project_id = project_id or shot.project_id
    if generation_id:
        generation = _owned_generation(session, user, generation_id)
        if shot_id and generation.shot_id != shot_id:
            raise HTTPException(status_code=400, detail="生成任务不属于当前镜头")
        if not shot_id:
            shot_id = generation.shot_id
        if not project_id:
            project_id = session.scalar(
                select(Shot.project_id).where(Shot.id == generation.shot_id)
            )
    feedback = Feedback(
        user_id=user.id,
        project_id=project_id,
        shot_id=shot_id,
        generation_id=generation_id,
        category=payload.category,
        message=payload.message.strip(),
        context_json=payload.context,
    )
    session.add(feedback)
    session.commit()
    session.refresh(feedback)
    return feedback


@app.get(
    "/api/agent/skills",
    response_model=list[AgentSkillRead],
    tags=["agent"],
)
def list_agent_skills(user: CurrentUser) -> list[dict[str, object]]:
    # The catalog is curated application metadata; requiring an authenticated
    # session keeps it aligned with the Chat Agent surface.
    return list_skills()


@app.get(
    "/api/projects/{project_id}/agent/threads",
    response_model=list[AgentThreadRead],
    tags=["agent"],
)
def list_agent_threads(
    project_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> list[AgentThread]:
    _owned_project(session, user, project_id)
    statement = (
        select(AgentThread)
        .where(AgentThread.project_id == project_id)
        .order_by(AgentThread.updated_at.desc())
    )
    return list(session.scalars(statement))


@app.post(
    "/api/projects/{project_id}/agent/threads",
    response_model=AgentThreadRead,
    status_code=status.HTTP_201_CREATED,
    tags=["agent"],
)
def create_agent_thread(
    project_id: uuid.UUID,
    payload: AgentThreadCreate,
    session: DatabaseSession,
    user: CurrentUser,
) -> AgentThread:
    _owned_project(session, user, project_id)
    thread = AgentThread(project_id=project_id, title=payload.title)
    session.add(thread)
    session.commit()
    session.refresh(thread)
    return thread


@app.get(
    "/api/agent/threads/{thread_id}/messages",
    response_model=list[AgentMessageRead],
    tags=["agent"],
)
def list_agent_messages(
    thread_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> list[AgentMessage]:
    _owned_thread(session, user, thread_id)
    statement = (
        select(AgentMessage)
        .where(AgentMessage.thread_id == thread_id)
        .order_by(AgentMessage.created_at)
    )
    return list(session.scalars(statement))


@app.get(
    "/api/agent/threads/{thread_id}/pending-approval",
    response_model=AgentApprovalRead | None,
    tags=["agent"],
)
def get_pending_agent_approval(
    thread_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> AgentApproval | None:
    _owned_thread(session, user, thread_id)
    statement = (
        select(AgentApproval)
        .join(AgentRun, AgentRun.id == AgentApproval.run_id)
        .where(
            AgentRun.thread_id == thread_id,
            AgentApproval.status == AgentApprovalStatus.PENDING,
        )
        .order_by(AgentApproval.created_at.desc())
    )
    return session.scalar(statement)


@app.get(
    "/api/agent/threads/{thread_id}/pending-interrupt",
    response_model=AgentInterruptRead | None,
    tags=["agent"],
)
def get_pending_agent_interrupt(
    thread_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> AgentInterrupt | None:
    _owned_thread(session, user, thread_id)
    statement = (
        select(AgentInterrupt)
        .join(AgentRun, AgentRun.id == AgentInterrupt.run_id)
        .where(
            AgentRun.thread_id == thread_id,
            AgentInterrupt.status == AgentInterruptStatus.PENDING,
        )
        .order_by(AgentInterrupt.created_at.desc())
    )
    return session.scalar(statement)


@app.post(
    "/api/agent/threads/{thread_id}/runs",
    response_model=AgentRunRead,
    status_code=status.HTTP_201_CREATED,
    tags=["agent"],
)
def create_agent_run(
    thread_id: uuid.UUID,
    payload: AgentRunCreate,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    user: CurrentUser,
) -> AgentRun:
    thread = _owned_thread(session, user, thread_id)
    if payload.context.project_id != thread.project_id:
        raise HTTPException(status_code=409, detail="Agent context does not belong to this thread")
    if payload.context.skill_id and get_skill(payload.context.skill_id) is None and not payload.context.skill_prompt:
        raise HTTPException(status_code=409, detail="Agent skill is not available")
    if payload.context.shot_id is not None:
        shot = session.get(Shot, payload.context.shot_id)
        if shot is None or shot.project_id != thread.project_id:
            raise HTTPException(status_code=409, detail="Agent shot context is invalid")

    active_run = session.scalar(
        select(AgentRun).where(
            AgentRun.thread_id == thread_id,
            AgentRun.status.in_([
                AgentRunStatus.THINKING,
                AgentRunStatus.PLANNING,
                AgentRunStatus.WAITING_USER,
                AgentRunStatus.WAITING_APPROVAL,
                AgentRunStatus.EXECUTING,
                AgentRunStatus.WAITING_EXTERNAL_JOB,
            ]),
        )
    )
    if active_run is not None:
        raise HTTPException(status_code=409, detail="Chat Agent 仍在处理上一条消息")

    context_snapshot = payload.context.model_dump(mode="json")
    run = AgentRun(
        thread_id=thread.id,
        status=AgentRunStatus.THINKING,
        current_step="load_context",
        context_snapshot=context_snapshot,
        canvas_version=payload.context.canvas_version,
    )
    session.add(run)
    session.flush()
    user_message = AgentMessage(
        thread_id=thread.id,
        run_id=run.id,
        role=AgentMessageRole.USER,
        content=payload.message.strip(),
        message_type="text",
        message_metadata={"context": context_snapshot},
    )
    session.add(user_message)
    session.flush()
    append_agent_event(
        session,
        run,
        "message.created",
        {"message_id": str(user_message.id), "role": "user"},
    )
    if not thread.summary:
        thread.summary = payload.message.strip()[:240]
    session.commit()
    session.refresh(run)
    background_tasks.add_task(execute_agent_run, str(run.id))
    return run


@app.get(
    "/api/agent/runs/{run_id}",
    response_model=AgentRunRead,
    tags=["agent"],
)
def get_agent_run(
    run_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> AgentRun:
    return _owned_run(session, user, run_id)


@app.post(
    "/api/agent/runs/{run_id}/cancel",
    response_model=AgentRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["agent"],
)
def cancel_agent_run(
    run_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> AgentRun:
    run = _owned_run(session, user, run_id)
    if run.status in {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
    }:
        return run
    run.status = AgentRunStatus.CANCELLED
    run.current_step = "cancelled"
    run.completed_at = datetime.now(UTC)
    if run.approval is not None and run.approval.status == AgentApprovalStatus.PENDING:
        run.approval.status = AgentApprovalStatus.REJECTED
        run.approval.decision_feedback = "run_cancelled"
        run.approval.resolved_at = datetime.now(UTC)
    for interrupt in run.interrupts:
        if interrupt.status == AgentInterruptStatus.PENDING:
            interrupt.status = AgentInterruptStatus.CANCELLED
            interrupt.resolved_at = datetime.now(UTC)
    append_agent_event(session, run, "run.cancelled", {"status": "cancelled"})
    session.commit()
    session.refresh(run)
    return run


@app.post(
    "/api/agent/runs/{run_id}/approval",
    response_model=AgentApprovalDecisionResult,
    tags=["agent"],
)
def decide_agent_approval(
    run_id: uuid.UUID,
    payload: AgentApprovalDecision,
    session: DatabaseSession,
    user: CurrentUser,
) -> dict[str, object]:
    _owned_run(session, user, run_id)
    run = session.scalar(
        select(AgentRun)
        .where(AgentRun.id == run_id)
        .options(selectinload(AgentRun.approval))
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    was_pending = (
        run.status == AgentRunStatus.WAITING_APPROVAL
        and run.approval is not None
        and run.approval.status == AgentApprovalStatus.PENDING
    )
    try:
        approval, canvas_version, canvas_revision = resolve_agent_approval(
            session,
            run,
            decision=payload.decision,
            feedback=payload.feedback,
        )
    except CanvasPatchError as exc:
        if was_pending:
            fail_agent_approval(session, run_id, str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.refresh(run)
    session.refresh(approval)
    return {
        "run": run,
        "approval": approval,
        "canvas_version": canvas_version,
        "canvas_revision": canvas_revision,
    }


@app.post(
    "/api/agent/runs/{run_id}/resume",
    response_model=AgentInterruptResumeResult,
    tags=["agent"],
)
def resume_agent_interrupt(
    run_id: uuid.UUID,
    payload: AgentInterruptResume,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    user: CurrentUser,
) -> dict[str, object]:
    _owned_run(session, user, run_id)
    run = session.scalar(
        select(AgentRun)
        .where(AgentRun.id == run_id)
        .options(selectinload(AgentRun.interrupts))
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    try:
        interrupt = resolve_agent_interrupt(
            session,
            run,
            payload.interrupt_id,
            payload.response,
        )
    except CanvasPatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    event_cursor = int(
        session.scalar(
            select(func.max(AgentEvent.sequence)).where(AgentEvent.run_id == run.id)
        )
        or 0
    )
    session.refresh(run)
    session.refresh(interrupt)
    background_tasks.add_task(resume_agent_run, str(run.id))
    return {"run": run, "interrupt": interrupt, "event_cursor": event_cursor}


@app.get(
    "/api/agent/runs/{run_id}/events",
    response_model=list[AgentEventRead],
    tags=["agent"],
)
def list_agent_events(
    run_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> list[AgentEvent]:
    _owned_run(session, user, run_id)
    statement = (
        select(AgentEvent)
        .where(AgentEvent.run_id == run_id)
        .order_by(AgentEvent.sequence)
    )
    return list(session.scalars(statement))


@app.get("/api/agent/runs/{run_id}/events/stream", tags=["agent"])
def stream_agent_events(
    run_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
    after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    _owned_run(session, user, run_id)

    def event_stream():
        last_sequence = after
        while True:
            with SessionLocal() as event_session:
                events = list(
                    event_session.scalars(
                        select(AgentEvent)
                        .where(
                            AgentEvent.run_id == run_id,
                            AgentEvent.sequence > last_sequence,
                        )
                        .order_by(AgentEvent.sequence)
                    )
                )
                run = event_session.get(AgentRun, run_id)
                for event in events:
                    last_sequence = event.sequence
                    event_data = AgentEventRead.model_validate(event).model_dump(mode="json")
                    yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                terminal = run is None or run.status in {
                    AgentRunStatus.WAITING_USER,
                    AgentRunStatus.WAITING_APPROVAL,
                    AgentRunStatus.COMPLETED,
                    AgentRunStatus.FAILED,
                    AgentRunStatus.CANCELLED,
                }
            if terminal:
                break
            time.sleep(0.35)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post(
    "/api/projects/{project_id}/shots",
    response_model=ShotRead,
    status_code=status.HTTP_201_CREATED,
    tags=["shots"],
)
def create_shot(
    project_id: uuid.UUID,
    payload: ShotCreate,
    session: DatabaseSession,
    user: CurrentUser,
) -> Shot:
    _owned_project(session, user, project_id)

    shot = Shot(project_id=project_id, **payload.model_dump())
    session.add(shot)
    session.commit()
    session.refresh(shot)
    return shot


@app.patch("/api/shots/{shot_id}", response_model=ShotRead, tags=["shots"])
def update_shot(
    shot_id: uuid.UUID,
    payload: ShotUpdate,
    session: DatabaseSession,
    user: CurrentUser,
) -> Shot:
    shot = _owned_shot(session, user, shot_id)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(shot, field, value)

    session.commit()
    session.refresh(shot)
    return shot


@app.post(
    "/api/shots/{shot_id}/generations",
    response_model=GenerationRead,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["generations"],
)
def create_generation(
    shot_id: uuid.UUID,
    payload: GenerationCreate,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    user: CurrentUser,
) -> Generation:
    shot = _owned_shot(session, user, shot_id)
    prompt = (payload.prompt or shot.visual_prompt).strip()
    if not prompt:
        raise HTTPException(status_code=409, detail="Generation needs a prompt before execution")
    if payload.kind == "video" and payload.provider not in {"mock", "local_h3"}:
        raise HTTPException(status_code=422, detail="Unsupported video provider")
    if (
        payload.kind == "video"
        and payload.provider == "local_h3"
        and not settings.local_video_base_url.strip()
    ):
        raise HTTPException(status_code=409, detail="LOCAL_VIDEO_BASE_URL 尚未配置")
    if payload.kind == "image" and payload.provider not in {
        "mock",
        "ark_seedream",
        "google_genai",
        "openai_compatible",
        "qwen",
    }:
        raise HTTPException(status_code=422, detail="Unsupported image provider")
    if payload.provider == "qwen" and not settings.qwen_api_key.strip():
        raise HTTPException(status_code=409, detail="QWEN_API_KEY 尚未配置")
    if (
        payload.kind == "image"
        and payload.provider not in {"mock", "qwen"}
        and not settings.image_api_key
    ):
        raise HTTPException(status_code=409, detail="IMAGE_API_KEY 尚未配置")
    if (
        payload.kind == "image"
        and payload.provider not in {"mock", "qwen"}
        and payload.provider != settings.image_provider
    ):
        raise HTTPException(status_code=409, detail="请求的图片 Provider 与服务端配置不一致")
    if payload.kind == "text" and payload.provider not in {"mock", "openai_compatible", "qwen"}:
        raise HTTPException(status_code=422, detail="Unsupported text provider")
    if (
        payload.kind == "text"
        and payload.provider == "openai_compatible"
        and not settings.text_api_key.strip()
    ):
        raise HTTPException(status_code=409, detail="TEXT_API_KEY 尚未配置")

    active_generation = session.scalar(
        select(Generation).where(
            Generation.shot_id == shot_id,
            Generation.status.in_([GenerationStatus.QUEUED, GenerationStatus.RUNNING]),
        )
    )
    if active_generation is not None:
        raise HTTPException(status_code=409, detail="Shot already has an active generation")

    generation = Generation(
        shot_id=shot_id,
        provider=payload.provider,
        kind=payload.kind,
        node_id=str(payload.node_id) if payload.node_id else None,
        model=payload.model or (
            settings.qwen_text_model
            if payload.kind == "text" and payload.provider == "qwen"
            else settings.qwen_image_model
            if payload.kind == "image" and payload.provider == "qwen"
            else settings.text_model
            if payload.kind == "text"
            else settings.image_model
            if payload.kind == "image"
            else settings.local_video_model
            if payload.kind == "video" and payload.provider == "local_h3"
            else None
        ),
        input_text=prompt,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        parameters=payload.parameters,
    )
    session.add(generation)
    session.commit()
    return _enqueue_generation(session, generation, background_tasks)


@app.get(
    "/api/shots/{shot_id}/generations",
    response_model=list[GenerationRead],
    tags=["generations"],
)
def list_generations(
    shot_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> list[Generation]:
    _owned_shot(session, user, shot_id)
    statement = (
        select(Generation)
        .where(Generation.shot_id == shot_id)
        .order_by(Generation.created_at.desc())
    )
    return list(session.scalars(statement))


@app.get(
    "/api/generations/{generation_id}",
    response_model=GenerationRead,
    tags=["generations"],
)
def get_generation(
    generation_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> Generation:
    return _owned_generation(session, user, generation_id)


@app.post(
    "/api/generations/{generation_id}/retry",
    response_model=GenerationRead,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["generations"],
)
def retry_generation(
    generation_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    user: CurrentUser,
) -> Generation:
    source = _owned_generation(session, user, generation_id)
    if source.status != GenerationStatus.FAILED:
        raise HTTPException(status_code=409, detail="只有失败或已取消的任务可以重试")
    active_generation = session.scalar(
        select(Generation).where(
            Generation.shot_id == source.shot_id,
            Generation.status.in_([GenerationStatus.QUEUED, GenerationStatus.RUNNING]),
        )
    )
    if active_generation is not None:
        raise HTTPException(status_code=409, detail="当前镜头已有生成任务正在处理")
    parameters = dict(source.parameters or {})
    parameters.pop("cancel_requested", None)
    retry = Generation(
        shot_id=source.shot_id,
        provider=source.provider,
        kind=source.kind,
        model=source.model,
        node_id=source.node_id,
        input_text=source.input_text,
        temperature=source.temperature,
        max_tokens=source.max_tokens,
        parameters=parameters,
    )
    session.add(retry)
    session.commit()
    return _enqueue_generation(session, retry, background_tasks)


@app.post(
    "/api/generations/{generation_id}/cancel",
    response_model=GenerationRead,
    tags=["generations"],
)
def cancel_generation(
    generation_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> Generation:
    generation = _owned_generation(session, user, generation_id)
    if generation.status not in {GenerationStatus.QUEUED, GenerationStatus.RUNNING}:
        return generation
    generation.parameters = {
        **(generation.parameters or {}),
        "cancel_requested": True,
    }
    generation.status = GenerationStatus.FAILED
    generation.error = "任务已取消，可点击重试继续生成"
    generation.updated_at = datetime.now(UTC)
    generation.shot.status = ShotStatus.READY
    session.commit()
    session.refresh(generation)
    return generation


@app.post(
    "/api/generations/{generation_id}/last-frame",
    response_model=UploadRead,
    status_code=status.HTTP_201_CREATED,
    tags=["generations"],
)
def extract_generation_last_frame(
    generation_id: uuid.UUID,
    request: Request,
    session: DatabaseSession,
    user: CurrentUser,
) -> UploadRead:
    generation = _owned_generation(session, user, generation_id)
    if generation.kind != "video":
        raise HTTPException(status_code=422, detail="只能从视频生成结果中截取末帧")
    if generation.status != GenerationStatus.SUCCEEDED or not generation.output_url:
        raise HTTPException(status_code=409, detail="视频尚未生成完成")

    try:
        content = extract_last_video_frame(generation.output_url)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    upload_id = uuid.uuid4()
    store_uploaded_image(settings, upload_id, content, "image/png")
    filename = f"video-last-frame-{generation.id.hex[:8]}.png"
    upload = StoredUpload(
        id=upload_id,
        user_id=user.id,
        filename=filename,
        content_type="image/png",
        size=len(content),
    )
    session.add(upload)
    asset = Asset(
        user_id=user.id,
        project_id=generation.shot.project_id,
        shot_id=generation.shot_id,
        source_upload_id=upload_id,
        source_generation_id=generation.id,
        kind="image",
        role="last_frame",
        filename=filename,
        content_type="image/png",
        size=len(content),
        url=str(request.url_for("read_upload", upload_id=upload_id)),
        metadata_json={"source": "video_last_frame"},
    )
    session.add(asset)
    session.commit()
    return UploadRead(
        id=upload_id,
        asset_id=asset.id,
        filename=filename,
        content_type="image/png",
        size=len(content),
        url=str(request.url_for("read_upload", upload_id=upload_id)),
    )


@app.get("/api/generations/{generation_id}/download", tags=["generations"])
async def download_generation(
    generation_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> Response:
    generation = _owned_generation(session, user, generation_id)
    if generation.status != GenerationStatus.SUCCEEDED or not generation.output_url:
        raise HTTPException(status_code=409, detail="Generation output is not ready")
    if generation.kind not in {"image", "video"}:
        raise HTTPException(status_code=422, detail="Only image and video outputs can be downloaded")

    source_url = generation.output_url
    default_media_type = "image/png" if generation.kind == "image" else "video/mp4"
    filename_prefix = f"libtv-{generation.kind}-{generation.id.hex[:8]}"

    if source_url.startswith("data:"):
        header, separator, payload = source_url.partition(",")
        if not separator or ";base64" not in header:
            raise HTTPException(status_code=502, detail="Generation output data is invalid")
        media_type = header[5:].split(";", 1)[0] or default_media_type
        try:
            content = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=502, detail="Generation output data is invalid") from exc
        extension = _media_extension(media_type, generation.kind)
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename_prefix}.{extension}"'},
        )

    if urlsplit(source_url).scheme not in {"http", "https"}:
        raise HTTPException(status_code=502, detail="Generation output URL is not downloadable")

    client = httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10))
    try:
        upstream = await client.send(client.build_request("GET", source_url), stream=True)
        upstream.raise_for_status()
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail="Failed to fetch generation output") from exc

    media_type = upstream.headers.get("content-type", default_media_type).split(";", 1)[0]
    extension = _media_extension(media_type, generation.kind)
    headers = {
        "Content-Disposition": f'attachment; filename="{filename_prefix}.{extension}"',
    }

    async def stream_output():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(stream_output(), media_type=media_type, headers=headers)


def _media_extension(media_type: str, kind: str) -> str:
    extensions = {
        "image/gif": "gif",
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "video/mp4": "mp4",
        "video/quicktime": "mov",
        "video/webm": "webm",
    }
    return extensions.get(media_type.lower(), "png" if kind == "image" else "mp4")


@app.get(
    "/api/shots/{shot_id}/workflow",
    response_model=WorkflowRead,
    tags=["workflows"],
)
def get_workflow(
    shot_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> Workflow:
    shot = _owned_shot(session, user, shot_id)
    return get_or_create_workflow(session, shot)


@app.put(
    "/api/shots/{shot_id}/workflow",
    response_model=WorkflowRead,
    tags=["workflows"],
)
def save_workflow(
    shot_id: uuid.UUID,
    payload: WorkflowWrite,
    session: DatabaseSession,
    user: CurrentUser,
) -> Workflow:
    shot = _owned_shot(session, user, shot_id)
    if len(payload.nodes) > 200 or len(payload.edges) > 500:
        raise HTTPException(status_code=422, detail="Workflow is too large")

    node_ids = [node.id for node in payload.nodes]
    edge_ids = [edge.id for edge in payload.edges]
    if len(node_ids) != len(set(node_ids)) or len(edge_ids) != len(set(edge_ids)):
        raise HTTPException(status_code=422, detail="Workflow contains duplicate ids")
    node_id_set = set(node_ids)
    if any(
        edge.source not in node_id_set
        or edge.target not in node_id_set
        or edge.source == edge.target
        for edge in payload.edges
    ):
        raise HTTPException(status_code=422, detail="Workflow contains an invalid edge")
    if _workflow_contains_cycle(payload.edges):
        raise HTTPException(status_code=422, detail="Workflow 不能形成循环连线")

    workflow = get_or_create_workflow(session, shot)
    try:
        return replace_workflow(session, workflow, payload)
    except WorkflowVersionConflict as cause:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(cause)) from cause
