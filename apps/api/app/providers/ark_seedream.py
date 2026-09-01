from typing import Any

import httpx

from ..config import Settings
from .base import (
    GenerationRequest,
    GenerationResult,
    ensure_no_image_context,
    prompt_with_text_context,
)


class ArkSeedreamImageProvider:
    """Synchronous image generation through Volcengine Ark's ImageGenerations API."""

    name = "ark_seedream"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client

    def generate(self, request: GenerationRequest) -> GenerationResult:
        api_key = self.settings.image_api_key.strip()
        model = (request.model or self.settings.image_model).strip()
        if not api_key:
            raise RuntimeError("未配置 IMAGE_API_KEY，无法调用 Seedream 图片模型")
        if not model:
            raise RuntimeError("未配置图片模型；请设置 IMAGE_MODEL")
        ensure_no_image_context(request, "Seedream")

        parameters = request.parameters or {}
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt_with_text_context(request),
            "size": str(parameters.get("size") or "2K"),
            "sequential_image_generation": "disabled",
            "stream": False,
            "response_format": "url",
            "watermark": bool(parameters.get("watermark", self.settings.image_watermark)),
        }
        seed = parameters.get("seed")
        if isinstance(seed, int) and seed >= 0:
            payload["seed"] = seed

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
                f"Seedream 调用失败（{response.status_code}）：{self._error_detail(response)}"
            ) from exc

        body = response.json()
        output_url = self._output_url(body)
        request_id = response.headers.get("x-request-id") or body.get("id") or request.generation_id
        return GenerationResult(provider_job_id=str(request_id), output_url=output_url)

    @staticmethod
    def _output_url(body: dict[str, Any]) -> str:
        try:
            url = body["data"][0]["url"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Seedream 返回了无法识别的数据结构") from exc
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise RuntimeError("Seedream 没有返回可下载的图片 URL")
        return url

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
            error = body.get("error", {})
            return str(error.get("message") or body.get("message") or response.text)
        except ValueError:
            return response.text or "未知错误"
