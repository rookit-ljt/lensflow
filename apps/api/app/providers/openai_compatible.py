from typing import Any

import httpx

from ..config import Settings
from .base import GenerationRequest, GenerationResult


class OpenAICompatibleTextProvider:
    """Calls any provider implementing the OpenAI chat-completions contract."""

    name = "openai_compatible"

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        api_key_name: str = "TEXT_API_KEY",
        provider_label: str = "文本模型",
    ) -> None:
        self.settings = settings
        self.client = client
        self.api_key = settings.text_api_key if api_key is None else api_key
        self.base_url = settings.text_base_url if base_url is None else base_url
        self.default_model = settings.text_model if default_model is None else default_model
        self.api_key_name = api_key_name
        self.provider_label = provider_label

    def generate(self, request: GenerationRequest) -> GenerationResult:
        api_key = self.api_key.strip()
        model = (request.model or self.default_model).strip()
        if not api_key:
            raise RuntimeError(f"未配置 {self.api_key_name}，无法调用{self.provider_label}")
        if not model:
            raise RuntimeError("未配置文本模型；请设置 TEXT_MODEL 或在节点中选择模型")

        user_content: str | list[dict[str, Any]] = request.prompt
        if request.contexts:
            content_parts: list[dict[str, Any]] = []
            for index, context in enumerate(request.contexts, start=1):
                if context.kind == "text" and context.text:
                    content_parts.append({
                        "type": "text",
                        "text": f"参考文本 {index}（{context.title}）：\n{context.text}",
                    })
                elif context.kind == "image" and context.image_url:
                    content_parts.append({"type": "text", "text": f"参考图片 {index}（{context.title}）"})
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": context.image_url},
                    })
            content_parts.append({
                "type": "text",
                "text": f"请结合以上全部参考素材完成以下任务：\n{request.prompt}",
            })
            user_content = content_parts

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": self.settings.text_system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
        }
        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}

        if self.client is not None:
            response = self.client.post(endpoint, headers=headers, json=payload)
        else:
            with httpx.Client(timeout=self.settings.text_request_timeout_seconds) as client:
                response = client.post(endpoint, headers=headers, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = self._error_detail(response)
            raise RuntimeError(f"文本模型调用失败（{response.status_code}）：{detail}") from exc

        body = response.json()
        output = self._content(body)
        request_id = response.headers.get("x-request-id") or body.get("id") or request.generation_id
        return GenerationResult(provider_job_id=str(request_id), output_text=output)

    @staticmethod
    def _content(body: dict[str, Any]) -> str:
        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("文本模型返回了无法识别的数据结构") from exc
        if not isinstance(content, str) or not content.strip():
            finish_reason = choice.get("finish_reason")
            reasoning = choice.get("message", {}).get("reasoning_content")
            if finish_reason == "length" and reasoning:
                raise RuntimeError("模型的推理过程耗尽了输出额度，请选择更长篇幅后重试")
            raise RuntimeError("文本模型返回了空内容")
        return content.strip()

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
            error = body.get("error", {})
            return str(error.get("message") or body.get("message") or response.text)
        except ValueError:
            return response.text or "未知错误"
