from __future__ import annotations

import base64
import binascii
import sys
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import CurrentUser
from ..config import get_settings
from ..credits_service import (
    InsufficientCreditsError,
    calculate_generation_cost,
    freeze_credits,
    get_or_create_wallet,
    refund_credits,
)
from ..db_models import (
    AgentApproval,
    Asset,
    Generation,
    GenerationStatus,
    Shot,
    ShotStatus,
    StoredUpload,
    User,
    WorkflowNode,
)
from ..deps import (
    DatabaseSession,
    get_owned_generation,
    get_owned_shot,
)
from ..schemas import (
    GenerationCreate,
    GenerationRead,
    UploadRead,
)
from ..tasks import generate_shot
from ..uploads import store_uploaded_image
from ..video_frames import extract_last_video_frame as default_extract_last_video_frame
from ..workflows import get_or_create_workflow, load_workflow

settings = get_settings()

router = APIRouter()


def _get_extract_last_video_frame():
    main_mod = sys.modules.get("app.main")
    return getattr(main_mod, "extract_last_video_frame", default_extract_last_video_frame) if main_mod else default_extract_last_video_frame


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


def enqueue_approved_generations(
    session: Session,
    approval: AgentApproval,
    background_tasks: BackgroundTasks,
    user: User,
) -> list[Generation]:
    """Start generator nodes created or changed by an approved Agent patch."""
    patch = approval.patch or {}
    shot_id = patch.get("shot_id")
    if not shot_id:
        return []
    shot = session.get(Shot, uuid.UUID(str(shot_id)))
    if shot is None:
        raise HTTPException(status_code=404, detail="Agent 计划目标镜头不存在")
    if shot.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Agent 计划目标镜头不存在")
    workflow = load_workflow(session, shot.id)
    if workflow is None:
        return []
    node_ids: list[uuid.UUID] = []
    for operation in patch.get("operations", []):
        if not isinstance(operation, dict):
            continue
        if operation.get("type") not in {"create_node", "update_node_config", "bind_asset"}:
            continue
        raw_id = operation.get("node_id")
        try:
            node_id = uuid.UUID(str(raw_id))
        except (TypeError, ValueError):
            continue
        if node_id not in node_ids:
            node_ids.append(node_id)

    created: list[Generation] = []
    for node_id in node_ids:
        node = session.get(WorkflowNode, node_id)
        if node is None or node.workflow_id != workflow.id or node.type != "generator":
            continue
        config = node.config if isinstance(node.config, dict) else {}
        mode = str(config.get("mode") or "").strip()
        prompt = str(config.get("prompt") or "").strip()
        if mode not in {"image", "video", "text"} or not prompt:
            continue
        active = session.scalar(select(Generation).where(
            Generation.node_id == str(node.id),
            Generation.status.in_([GenerationStatus.QUEUED, GenerationStatus.RUNNING]),
        ))
        if active is not None:
            continue
        default_provider = (
            "local_h3" if mode == "video"
            else "qwen" if mode == "image" and settings.qwen_api_key.strip()
            else settings.image_provider if mode == "image"
            else settings.text_provider
        )
        provider = str(config.get("provider") or default_provider)
        if provider not in {"mock", "openai_compatible", "ark_seedream", "google_genai", "qwen", "local_h3"}:
            provider = "mock"
        parameters = {
            key: value for key, value in config.items()
            if key not in {"mode", "provider", "model", "prompt", "temperature", "max_tokens"}
        }
        payload = GenerationCreate(
            provider=provider,
            kind=mode,
            node_id=node.id,
            prompt=prompt,
            model=str(config.get("model") or "") or None,
            temperature=float(config.get("temperature", 0.7)),
            max_tokens=int(config.get("max_tokens", 2400)),
            parameters=parameters,
        )
        created.append(create_generation(shot.id, payload, background_tasks, session, user))
    return created


@router.post(
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
    shot = get_owned_shot(session, user, shot_id)
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

    cost = calculate_generation_cost(
        kind=payload.kind,
        provider=payload.provider,
        model=payload.model,
        parameters=payload.parameters,
    )
    generation_id = uuid.uuid4()
    if cost > 0:
        try:
            freeze_credits(
                session=session,
                user=user,
                amount=cost,
                biz_type=f"{payload.kind}_generation",
                biz_id=str(generation_id),
                description=f"{payload.kind} 生成任务预扣积分",
            )
        except InsufficientCreditsError as exc:
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))

    generation = Generation(
        id=generation_id,
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
        cost_credits=cost,
    )
    session.add(generation)
    session.commit()
    return _enqueue_generation(session, generation, background_tasks)


@router.post(
    "/api/shots/{shot_id}/run",
    response_model=list[GenerationRead],
    status_code=status.HTTP_202_ACCEPTED,
    tags=["generations"],
)
def run_shot_workflow(
    shot_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    user: CurrentUser,
) -> list[Generation]:
    """Run generator nodes in workflow order for the local eager runner."""
    shot = get_owned_shot(session, user, shot_id)
    if not settings.celery_task_always_eager:
        raise HTTPException(status_code=409, detail="整条镜头运行目前需要 CELERY_TASK_ALWAYS_EAGER=true")
    workflow = get_or_create_workflow(session, shot)
    nodes = {node.id: node for node in workflow.nodes}
    incoming: dict[uuid.UUID, list[uuid.UUID]] = {node_id: [] for node_id in nodes}
    outgoing: dict[uuid.UUID, list[uuid.UUID]] = {node_id: [] for node_id in nodes}
    for edge in workflow.edges:
        if edge.source in nodes and edge.target in nodes:
            incoming[edge.target].append(edge.source)
            outgoing[edge.source].append(edge.target)
    ready = [node_id for node_id, sources in incoming.items() if not sources]
    ordered: list[uuid.UUID] = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for target in outgoing[current]:
            incoming[target].remove(current)
            if not incoming[target]:
                ready.append(target)
    if len(ordered) != len(nodes):
        raise HTTPException(status_code=409, detail="工作流存在循环连线，无法运行")

    candidate_payloads: list[GenerationCreate] = []
    total_estimated_cost = 0
    for node_id in ordered:
        node = nodes[node_id]
        if node.type != "generator":
            continue
        mode = str(node.config.get("mode") or "").strip()
        if mode not in {"text", "image", "video"}:
            continue
        provider = str(node.config.get("provider") or "mock")
        if provider not in {"mock", "openai_compatible", "ark_seedream", "google_genai", "qwen", "local_h3"}:
            provider = "mock"
        prompt = str(node.config.get("prompt") or shot.visual_prompt or "").strip()
        if not prompt:
            continue
        model_name = str(node.config.get("model") or "") or None
        node_params = {
            "context_source_node_ids": [str(source_id) for source_id in outgoing if node_id in outgoing[source_id]],
            **{key: value for key, value in node.config.items() if key not in {"mode", "provider", "model", "prompt"}},
        }
        total_estimated_cost += calculate_generation_cost(mode, provider, model_name, node_params)
        candidate_payloads.append(
            GenerationCreate(
                provider=provider,
                kind=mode,
                node_id=node.id,
                prompt=prompt,
                model=model_name,
                temperature=float(node.config.get("temperature", 0.7)),
                max_tokens=int(node.config.get("max_tokens", 2400)),
                parameters=node_params,
            )
        )
    if not candidate_payloads:
        raise HTTPException(status_code=409, detail="当前镜头没有可运行的生成节点")

    wallet = get_or_create_wallet(session, user)
    if total_estimated_cost > 0 and wallet.balance < total_estimated_cost:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"积分不足：整镜头运行预计需要 {total_estimated_cost} 积分，当前可用 {wallet.balance} 积分",
        )

    results: list[Generation] = []
    for payload in candidate_payloads:
        results.append(create_generation(shot_id, payload, background_tasks, session, user))
    return results


@router.get(
    "/api/shots/{shot_id}/generations",
    response_model=list[GenerationRead],
    tags=["generations"],
)
def list_generations(
    shot_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> list[Generation]:
    get_owned_shot(session, user, shot_id)
    statement = (
        select(Generation)
        .where(Generation.shot_id == shot_id)
        .order_by(Generation.created_at.desc())
    )
    return list(session.scalars(statement))


@router.get(
    "/api/generations/{generation_id}",
    response_model=GenerationRead,
    tags=["generations"],
)
def get_generation(
    generation_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> Generation:
    return get_owned_generation(session, user, generation_id)


@router.post(
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
    source = get_owned_generation(session, user, generation_id)
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
    cost = calculate_generation_cost(
        kind=source.kind,
        provider=source.provider,
        model=source.model,
        parameters=parameters,
    )
    retry_id = uuid.uuid4()
    if cost > 0:
        try:
            freeze_credits(
                session=session,
                user=user,
                amount=cost,
                biz_type=f"{source.kind}_generation",
                biz_id=str(retry_id),
                description=f"{source.kind} 任务重试预扣积分",
            )
        except InsufficientCreditsError as exc:
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))

    retry = Generation(
        id=retry_id,
        shot_id=source.shot_id,
        provider=source.provider,
        kind=source.kind,
        model=source.model,
        node_id=source.node_id,
        input_text=source.input_text,
        temperature=source.temperature,
        max_tokens=source.max_tokens,
        parameters=parameters,
        cost_credits=cost,
    )
    session.add(retry)
    session.commit()
    return _enqueue_generation(session, retry, background_tasks)


@router.post(
    "/api/generations/{generation_id}/cancel",
    response_model=GenerationRead,
    tags=["generations"],
)
def cancel_generation(
    generation_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> Generation:
    generation = get_owned_generation(session, user, generation_id)
    if generation.status not in {GenerationStatus.QUEUED, GenerationStatus.RUNNING}:
        return generation
    generation.parameters = {
        **(generation.parameters or {}),
        "cancel_requested": True,
    }
    generation.status = GenerationStatus.FAILED
    generation.error = "任务已取消，可点击重试继续生成"
    generation.updated_at = datetime.now(UTC)
    if generation.cost_credits > 0:
        refund_credits(
            session=session,
            user_id=user.id,
            amount=generation.cost_credits,
            biz_type=f"{generation.kind}_generation",
            biz_id=str(generation.id),
            description=f"{generation.kind} 任务已取消，积分原路返还",
        )
    generation.shot.status = ShotStatus.READY
    session.commit()
    session.refresh(generation)
    return generation


@router.post(
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
    generation = get_owned_generation(session, user, generation_id)
    if generation.kind != "video":
        raise HTTPException(status_code=422, detail="只能从视频生成结果中截取末帧")
    if generation.status != GenerationStatus.SUCCEEDED or not generation.output_url:
        raise HTTPException(status_code=409, detail="视频尚未生成完成")

    extractor = _get_extract_last_video_frame()
    try:
        content = extractor(generation.output_url)
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


@router.get("/api/generations/{generation_id}/download", tags=["generations"])
async def download_generation(
    generation_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> Response:
    generation = get_owned_generation(session, user, generation_id)
    if generation.status != GenerationStatus.SUCCEEDED or not generation.output_url:
        raise HTTPException(status_code=409, detail="Generation output is not ready")
    if generation.kind not in {"image", "video"}:
        raise HTTPException(status_code=422, detail="Only image and video outputs can be downloaded")

    source_url = generation.output_url
    default_media_type = "image/png" if generation.kind == "image" else "video/mp4"
    filename_prefix = f"ai-video-studio-{generation.kind}-{generation.id.hex[:8]}"

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


# 别名兼容
_enqueue_approved_generations = enqueue_approved_generations
