import time
from collections.abc import Callable
from typing import Any, ClassVar

import httpx

from ..config import Settings
from .base import (
    GenerationRequest,
    GenerationResult,
    prompt_with_text_context,
)


class QwenImageProvider:
    """Generates and edits images through Alibaba Cloud Model Studio."""

    name = "qwen"
    multimodal_models: ClassVar[set[str]] = {
        "qwen-image-2.0-pro",
        "qwen-image-2.0",
        "qwen-image-3.0-pro",
        "qwen-image-3.0",
    }
    text_to_image_models: ClassVar[set[str]] = {"qwen-image-plus", "qwen-image"}
    sizes: ClassVar[dict[str, str]] = {
        "16:9": "1664*928",
        "9:16": "928*1664",
        "1:1": "1328*1328",
        "4:3": "1472*1104",
        "3:4": "1104*1472",
        "21:9": "1664*720",
    }

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.client = client
        self.sleep = sleep

    def generate(self, request: GenerationRequest) -> GenerationResult:
        api_key = self.settings.qwen_api_key.strip()
        model = (request.model or self.settings.qwen_image_model).strip()
        if not api_key:
            raise RuntimeError("未配置 QWEN_API_KEY，无法调用千问图片模型")
        if not model:
            raise RuntimeError("未配置千问图片模型；请设置 QWEN_IMAGE_MODEL")
        image_contexts = tuple(
            context
            for context in request.contexts
            if context.kind == "image" and context.image_url
        )[:3]
        if image_contexts and model not in self.multimodal_models:
            model = self.settings.qwen_image_edit_model.strip()
        if model in self.multimodal_models:
            return self._generate_multimodal(request, model, image_contexts, api_key)
        if model not in self.text_to_image_models:
            raise RuntimeError(f"暂不支持千问图片模型 {model}")
        return self._generate_text_to_image(request, model, api_key)

    def _generate_multimodal(
        self,
        request: GenerationRequest,
        model: str,
        image_contexts: tuple[Any, ...],
        api_key: str,
    ) -> GenerationResult:
        parameters = request.parameters or {}
        content = [
            {"image": context.image_url}
            for context in image_contexts
            if context.image_url
        ]
        content.append({"text": prompt_with_text_context(request)})
        model_parameters: dict[str, Any] = {
            "size": self._size(parameters.get("aspect_ratio")),
            "n": min(max(parameters.get("count", 1), 1), 6),
            "prompt_extend": bool(parameters.get("prompt_extend", True)),
            "watermark": bool(parameters.get("watermark", self.settings.image_watermark)),
        }
        negative_prompt = parameters.get("negative_prompt")
        if isinstance(negative_prompt, str) and negative_prompt.strip():
            model_parameters["negative_prompt"] = negative_prompt.strip()
        seed = parameters.get("seed")
        if isinstance(seed, int) and seed >= 0:
            model_parameters["seed"] = seed
        payload = {
            "model": model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": model_parameters,
        }
        endpoint = (
            f"{self.settings.qwen_image_base_url.rstrip('/')}"
            "/services/aigc/multimodal-generation/generation"
        )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if self.client is not None:
            return self._post_multimodal(self.client, endpoint, headers, payload, request)
        with httpx.Client(timeout=self.settings.qwen_request_timeout_seconds) as client:
            return self._post_multimodal(client, endpoint, headers, payload, request)

    def _generate_text_to_image(
        self,
        request: GenerationRequest,
        model: str,
        api_key: str,
    ) -> GenerationResult:

        parameters = request.parameters or {}
        payload = {
            "model": model,
            "input": {"prompt": prompt_with_text_context(request)},
            "parameters": {
                "size": self._size(parameters.get("aspect_ratio")),
                "n": 1,
                "prompt_extend": bool(parameters.get("prompt_extend", True)),
                "watermark": bool(parameters.get("watermark", self.settings.image_watermark)),
            },
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        endpoint = (
            f"{self.settings.qwen_image_base_url.rstrip('/')}"
            "/services/aigc/text2image/image-synthesis"
        )

        if self.client is not None:
            return self._submit_and_poll(self.client, endpoint, headers, payload, request)
        with httpx.Client(timeout=self.settings.qwen_request_timeout_seconds) as client:
            return self._submit_and_poll(client, endpoint, headers, payload, request)

    def _post_multimodal(
        self,
        client: httpx.Client,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        request: GenerationRequest,
    ) -> GenerationResult:
        response = client.post(endpoint, headers=headers, json=payload)
        self._raise_for_status(response, "千问图片生成或编辑失败")
        body = response.json()
        output_url = self._output_url(body.get("output", {}))
        request_id = (
            response.headers.get("x-request-id")
            or body.get("request_id")
            or request.generation_id
        )
        return GenerationResult(provider_job_id=str(request_id), output_url=output_url)

    def _submit_and_poll(
        self,
        client: httpx.Client,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        request: GenerationRequest,
    ) -> GenerationResult:
        response = client.post(endpoint, headers=headers, json=payload)
        self._raise_for_status(response, "千问图片任务创建失败")
        body = response.json()
        task_id = body.get("output", {}).get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("千问图片接口没有返回 task_id")

        task_endpoint = f"{self.settings.qwen_image_base_url.rstrip('/')}/tasks/{task_id}"
        deadline = time.monotonic() + self.settings.qwen_request_timeout_seconds
        poll_headers = {"Authorization": headers["Authorization"]}
        while time.monotonic() < deadline:
            task_response = client.get(task_endpoint, headers=poll_headers)
            self._raise_for_status(task_response, "千问图片任务查询失败")
            task_body = task_response.json()
            output = task_body.get("output", {})
            status = str(output.get("task_status", "")).upper()
            if status == "SUCCEEDED":
                output_url = self._output_url(output)
                request_id = task_body.get("request_id") or task_id or request.generation_id
                return GenerationResult(
                    provider_job_id=str(request_id),
                    output_url=output_url,
                )
            if status in {"FAILED", "CANCELED", "UNKNOWN"}:
                detail = task_body.get("message") or output.get("message") or status
                raise RuntimeError(f"千问图片生成失败：{detail}")
            self.sleep(self.settings.qwen_image_poll_interval_seconds)
        raise RuntimeError("千问图片生成超时，请稍后重试")

    @classmethod
    def _size(cls, value: object) -> str:
        return cls.sizes.get(str(value), cls.sizes["16:9"])

    @staticmethod
    def _output_url(output: dict[str, Any]) -> str:
        try:
            url = output["choices"][0]["message"]["content"][0]["image"]
        except (KeyError, IndexError, TypeError):
            url = None
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url
        try:
            url = output["results"][0]["url"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("千问图片任务返回了无法识别的数据结构") from exc
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise RuntimeError("千问图片任务没有返回有效图片 URL")
        return url

    @staticmethod
    def _raise_for_status(response: httpx.Response, message: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                body = response.json()
                detail = body.get("message") or body.get("code") or response.text
            except ValueError:
                detail = response.text or "未知错误"
            raise RuntimeError(f"{message}（{response.status_code}）：{detail}") from exc
