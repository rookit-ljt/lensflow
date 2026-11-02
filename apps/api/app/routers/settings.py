from __future__ import annotations

import uuid

import httpx
from fastapi import APIRouter, HTTPException

from ..agent_runtime import SimpleAgentRuntime
from ..auth import AdminUser, CurrentUser
from ..config import get_settings
from ..providers import OpenAICompatibleTextProvider, QwenTextProvider
from ..providers.base import GenerationRequest
from ..runtime_settings import apply_settings, settings_view
from ..schemas import (
    HealthResponse,
    ProviderCapabilityRead,
    RuntimeSettingsRead,
    RuntimeSettingsTestRead,
    RuntimeSettingsTestRequest,
    RuntimeSettingsUpdate,
)

settings = get_settings()

QWEN_TEXT_MODELS = (
    "qwen3.7-plus",
    "qwen3.7-max",
    "qwen3.7-flash",
    "qwen-plus",
)
QWEN_IMAGE_MODELS = (
    "qwen-image-2.1-pro",
    "qwen-image-2.0-pro",
    "qwen-image-2.0",
    "qwen-image-plus",
    "qwen-image",
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="ai-video-studio-api", version="0.1.0")


@router.get("/api/providers", response_model=list[ProviderCapabilityRead], tags=["system"])
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
        "qwen": "通义千问图片模型",
    }
    # Qwen is the default image provider. Do not add a second generic
    # capability for it below; the dedicated entry includes all supported
    # Qwen image models and should be shown only once in the dropdown.
    if settings.image_provider in provider_labels and settings.image_provider != "qwen":
        capabilities.append(
            ProviderCapabilityRead(
                id=settings.image_provider,
                kind="image",
                label=provider_labels[settings.image_provider],
                configured=bool(
                    (settings.qwen_api_key if settings.image_provider == "qwen" else settings.image_api_key).strip()
                    and settings.image_model.strip()
                ),
                model=settings.image_model,
                models=[settings.image_model] if settings.image_model else [],
                requires_api_key=True,
            )
        )
    qwen_image = ProviderCapabilityRead(
        id="qwen",
        kind="image",
        label="阿里云百炼 · 千问图片",
        configured=bool(settings.qwen_api_key.strip() and settings.qwen_image_model.strip()),
        model=settings.qwen_image_model,
        models=list(dict.fromkeys((settings.qwen_image_model, *QWEN_IMAGE_MODELS))),
        requires_api_key=True,
    )
    mock_image = ProviderCapabilityRead(
        id="mock",
        kind="image",
        label="Mock 图片流程",
        configured=True,
        model="mock-image",
        models=["mock-image"],
        requires_api_key=False,
    )
    # Put a configured Qwen capability first so a newly opened image model
    # selector presents the real default before the Mock fallback.
    if qwen_image.configured:
        capabilities.extend((qwen_image, mock_image))
    else:
        capabilities.extend((mock_image, qwen_image))
    return capabilities


def _ensure_runtime_settings_enabled() -> None:
    if settings.environment != "development" or not settings.runtime_settings_enabled:
        raise HTTPException(status_code=403, detail="运行时模型配置仅在开发环境开放")


@router.get("/api/settings", response_model=RuntimeSettingsRead, tags=["settings"])
def get_runtime_settings(_user: CurrentUser) -> RuntimeSettingsRead:
    _ensure_runtime_settings_enabled()
    return RuntimeSettingsRead(**settings_view(settings))


@router.put("/api/settings", response_model=RuntimeSettingsRead, tags=["settings"])
def update_runtime_settings(payload: RuntimeSettingsUpdate, _user: AdminUser) -> RuntimeSettingsRead:
    _ensure_runtime_settings_enabled()
    try:
        apply_settings(settings, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RuntimeSettingsRead(**settings_view(settings))


@router.post("/api/settings/test", response_model=RuntimeSettingsTestRead, tags=["settings"])
def test_runtime_settings(payload: RuntimeSettingsTestRequest, _user: AdminUser) -> RuntimeSettingsTestRead:
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
        if payload.test_tool_calling:
            temporary.agent_provider = payload.provider
            temporary.agent_model = model
            temporary.agent_temperature = 0
            temporary.agent_max_tokens = 1600
            SimpleAgentRuntime(temporary).test_tool_calling()
            return RuntimeSettingsTestRead(
                ok=True,
                provider=payload.provider,
                model=model,
                message="工具调用测试成功：ask_user 参数校验通过。未创建问题卡、节点或生成任务。",
                tool_calling=True,
            )
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
        return RuntimeSettingsTestRead(
            ok=False,
            provider=payload.provider,
            model=payload.model,
            message=safe_message,
            tool_calling=False if payload.test_tool_calling else None,
        )
    return RuntimeSettingsTestRead(
        ok=True,
        provider=payload.provider,
        model=payload.model,
        message="连接成功，模型可以正常响应。",
    )
