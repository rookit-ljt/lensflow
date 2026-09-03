"""Local-only runtime model settings used by the internal beta UI.

The values are persisted in the ignored root ``.env`` file so a developer can
configure a provider without editing several files or restarting the API.
This module deliberately exposes only masked/configured state to clients.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from .config import Settings

ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


def settings_view(settings: Settings) -> dict[str, object]:
    return {
        "runtime_enabled": settings.runtime_settings_enabled and settings.environment == "development",
        "environment": settings.environment,
        "text_provider": settings.text_provider,
        "text_model": settings.text_model,
        "text_base_url": settings.text_base_url,
        "text_configured": bool(settings.text_api_key.strip() and settings.text_model.strip()),
        "image_provider": settings.image_provider,
        "image_model": settings.image_model,
        "image_base_url": settings.image_base_url,
        "image_configured": bool(settings.image_api_key.strip() and settings.image_model.strip()),
        "agent_provider": settings.agent_provider,
        "agent_model": settings.agent_model,
        "qwen_text_model": settings.qwen_text_model,
        "qwen_text_base_url": settings.qwen_text_base_url,
        "qwen_configured": bool(settings.qwen_api_key.strip() and settings.qwen_text_model.strip()),
        "qwen_image_model": settings.qwen_image_model,
        "qwen_image_base_url": settings.qwen_image_base_url,
        "qwen_image_configured": bool(settings.qwen_api_key.strip() and settings.qwen_image_model.strip()),
        "local_video_model": settings.local_video_model,
        "local_video_base_url": settings.local_video_base_url,
        "local_video_request_timeout_seconds": settings.local_video_request_timeout_seconds,
        "local_video_configured": bool(settings.local_video_base_url.strip() and settings.local_video_model.strip()),
    }


def _clean(value: str | None) -> str:
    value = (value or "").strip()
    if "\n" in value or "\r" in value:
        raise ValueError("配置值不能包含换行符")
    return value


def _dotenv_value(value: str) -> str:
    # Quoting keeps keys containing #, spaces, or shell punctuation intact.
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _write_env_values(values: dict[str, str]) -> None:
    ROOT_ENV.parent.mkdir(parents=True, exist_ok=True)
    original = ROOT_ENV.read_text(encoding="utf-8") if ROOT_ENV.exists() else ""
    lines = original.splitlines()
    seen: set[str] = set()
    output: list[str] = []
    pattern = re.compile(r"^(\s*(?:export\s+)?)([A-Z][A-Z0-9_]*)\s*=.*$")
    for line in lines:
        match = pattern.match(line)
        if not match or match.group(2) not in values:
            output.append(line)
            continue
        key = match.group(2)
        output.append(f"{match.group(1)}{key}={_dotenv_value(values[key])}")
        seen.add(key)
    for key, value in values.items():
        if key not in seen:
            output.append(f"{key}={_dotenv_value(value)}")
    ROOT_ENV.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def apply_settings(settings: Settings, *, provider: Literal["qwen", "openai_compatible", "local_h3"], kind: Literal["text", "image", "video"], api_key: str, model: str, base_url: str | None, apply_to_agent: bool) -> None:
    api_key = _clean(api_key)
    model = _clean(model)
    base_url = _clean(base_url)
    if provider == "local_h3" and kind == "video":
        if not model:
            raise ValueError("请输入视频模型名称")
        settings.local_video_model = model
        settings.local_video_base_url = base_url or settings.local_video_base_url
        _write_env_values({
            "LOCAL_VIDEO_MODEL": settings.local_video_model,
            "LOCAL_VIDEO_BASE_URL": settings.local_video_base_url,
        })
        return
    if not api_key:
        if provider == "qwen":
            api_key = settings.qwen_api_key
        elif kind == "text":
            api_key = settings.text_api_key
        else:
            api_key = settings.image_api_key
    if not api_key:
        raise ValueError("请输入 API Key")
    if not model:
        raise ValueError("请输入模型名称")

    values: dict[str, str] = {}
    if provider == "qwen":
        settings.qwen_api_key = api_key
        values["QWEN_API_KEY"] = settings.qwen_api_key
        if kind == "text":
            settings.qwen_text_model = model
            values["QWEN_TEXT_MODEL"] = settings.qwen_text_model
            if base_url:
                settings.qwen_text_base_url = base_url
                values["QWEN_TEXT_BASE_URL"] = settings.qwen_text_base_url
            if apply_to_agent:
                settings.agent_provider = "qwen"
                settings.agent_model = model
                values["AGENT_PROVIDER"] = settings.agent_provider
                values["AGENT_MODEL"] = settings.agent_model
        else:
            settings.qwen_image_model = model
            values["QWEN_IMAGE_MODEL"] = settings.qwen_image_model
            if base_url:
                settings.qwen_image_base_url = base_url
                values["QWEN_IMAGE_BASE_URL"] = settings.qwen_image_base_url
    elif kind == "text":
        settings.text_provider = "openai_compatible"
        settings.text_api_key = api_key
        settings.text_model = model
        values.update({"TEXT_PROVIDER": settings.text_provider, "TEXT_API_KEY": settings.text_api_key, "TEXT_MODEL": settings.text_model})
        if base_url:
            settings.text_base_url = base_url
            values["TEXT_BASE_URL"] = settings.text_base_url
        if apply_to_agent:
            settings.agent_provider = "openai_compatible"
            settings.agent_model = model
            values["AGENT_PROVIDER"] = settings.agent_provider
            values["AGENT_MODEL"] = settings.agent_model
    else:
        settings.image_provider = "openai_compatible"
        settings.image_api_key = api_key
        settings.image_model = model
        values.update({"IMAGE_PROVIDER": settings.image_provider, "IMAGE_API_KEY": settings.image_api_key, "IMAGE_MODEL": settings.image_model})
        if base_url:
            settings.image_base_url = base_url
            values["IMAGE_BASE_URL"] = settings.image_base_url
    _write_env_values(values)


class RuntimeSettingsPayload(BaseModel):
    provider: Literal["qwen", "openai_compatible", "local_h3"]
    kind: Literal["text", "image", "video"] = "text"
    api_key: str = ""
    model: str
    base_url: str | None = None
    apply_to_agent: bool = True
