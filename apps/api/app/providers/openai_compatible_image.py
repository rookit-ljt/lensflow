import base64
import binascii
from typing import Any, ClassVar

import httpx

from ..config import Settings
from .base import (
    GenerationRequest,
    GenerationResult,
    ensure_no_image_context,
    prompt_with_text_context,
)


class OpenAICompatibleImageProvider:
    """Calls an OpenAI-compatible POST /images/generations endpoint."""

    name = "openai_compatible"
    dalle2_sizes: ClassVar[set[str]] = {"256x256", "512x512", "1024x1024"}

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client

    def generate(self, request: GenerationRequest) -> GenerationResult:
        api_key = self.settings.image_api_key.strip()
        model = (request.model or self.settings.image_model).strip()
        if not api_key:
            raise RuntimeError("未配置 IMAGE_API_KEY，无法调用图片模型")
        if not model:
            raise RuntimeError("未配置图片模型；请设置 IMAGE_MODEL")
        ensure_no_image_context(request, "OpenAI-compatible 图片接口")

        parameters = request.parameters or {}
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt_with_text_context(request),
            "n": self._count(parameters.get("count")),
            "size": self._size(model, parameters.get("size")),
            "response_format": "url",
        }
        endpoint = f"{self.settings.image_base_url.rstrip('/')}/images/generations"
        headers = {"Authorization": f"Bearer {api_key}"}
        if self.client is not None:
            response = self.client.post(endpoint, headers=headers, json=payload)
        else:
            with httpx.Client(timeout=self.settings.image_request_timeout_seconds) as client:
                response = client.post(endpoint, headers=headers, json=payload)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"图片模型调用失败（{response.status_code}）：{self._error_detail(response)}"
            ) from exc

        body = response.json()
        output_url = self._output_url(body)
        request_id = response.headers.get("x-request-id") or body.get("id") or request.generation_id
        return GenerationResult(provider_job_id=str(request_id), output_url=output_url)

    @classmethod
    def _size(cls, model: str, value: object) -> str:
        requested = str(value) if value else "1024x1024"
        if model.lower() == "dall-e-2":
            return requested if requested in cls.dalle2_sizes else "1024x1024"
        return requested

    @staticmethod
    def _count(value: object) -> int:
        return min(max(value if isinstance(value, int) else 1, 1), 10)

    @staticmethod
    def _output_url(body: dict[str, Any]) -> str:
        try:
            item = body["data"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("图片模型返回了无法识别的数据结构") from exc
        url = item.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url
        encoded = item.get("b64_json")
        if isinstance(encoded, str):
            try:
                base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise RuntimeError("图片模型返回了损坏的 Base64 数据") from exc
            return f"data:image/png;base64,{encoded}"
        raise RuntimeError("图片模型没有返回图片 URL 或 Base64 数据")

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
            error = body.get("error", {})
            return str(error.get("message") or body.get("message") or response.text)
        except ValueError:
            return response.text or "未知错误"
