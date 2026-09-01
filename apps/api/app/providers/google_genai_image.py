import base64
import binascii
import re
from typing import Any

from google import genai
from google.genai import types

from ..config import Settings
from .base import GenerationRequest, GenerationResult


class GoogleGenAIImageProvider:
    """Generates images through the Google Gen AI SDK's Vertex AI protocol."""

    name = "google_genai"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self.client = client

    def generate(self, request: GenerationRequest) -> GenerationResult:
        api_key = self.settings.image_api_key.strip()
        model = (request.model or self.settings.image_model).strip()
        if not api_key:
            raise RuntimeError("未配置 IMAGE_API_KEY，无法调用 Gemini 图片模型")
        if not model:
            raise RuntimeError("未配置图片模型；请设置 IMAGE_MODEL")

        parameters = request.parameters or {}
        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=self._aspect_ratio(parameters.get("aspect_ratio")),
                image_size=self._image_size(parameters.get("size")),
            ),
        )

        client = self.client or genai.Client(
            api_key=api_key,
            vertexai=True,
            http_options={
                "base_url": self.settings.image_base_url.rstrip("/"),
                "timeout": int(self.settings.image_request_timeout_seconds * 1000),
            },
        )
        try:
            response = client.models.generate_content(
                model=model,
                contents=self._contents(request),
                config=config,
            )
        except Exception as exc:
            raise RuntimeError(f"Gemini 图片模型调用失败：{self._error_detail(exc)}") from exc
        finally:
            if self.client is None:
                client.close()

        output_url = self._output_url(response)
        request_id = getattr(response, "response_id", None) or request.generation_id
        return GenerationResult(provider_job_id=str(request_id), output_url=output_url)

    @classmethod
    def _contents(cls, request: GenerationRequest) -> str | list[types.Part]:
        if not request.contexts:
            return request.prompt
        parts: list[types.Part] = []
        for index, context in enumerate(request.contexts, start=1):
            if context.kind == "text" and context.text:
                parts.append(types.Part.from_text(text=f"参考文本 {index}（{context.title}）：\n{context.text}"))
            elif context.kind == "image" and context.image_url:
                parts.append(types.Part.from_text(text=f"参考图片 {index}（{context.title}）："))
                parts.append(cls._image_part(context.image_url))
        parts.append(types.Part.from_text(text=f"请结合以上全部参考素材完成以下任务：\n{request.prompt}"))
        return parts

    @staticmethod
    def _image_part(image_url: str) -> types.Part:
        match = re.fullmatch(r"data:(image/[\w.+-]+);base64,(.+)", image_url, re.DOTALL)
        if match:
            try:
                data = base64.b64decode(match.group(2), validate=True)
            except (ValueError, binascii.Error) as exc:
                raise RuntimeError("引用图片的 Base64 数据已损坏") from exc
            return types.Part.from_bytes(data=data, mime_type=match.group(1))
        if image_url.startswith(("http://", "https://")):
            return types.Part.from_uri(file_uri=image_url)
        raise RuntimeError("引用图片格式不受支持")

    @staticmethod
    def _aspect_ratio(value: object) -> str:
        supported = {"1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"}
        requested = str(value) if value else "16:9"
        return requested if requested in supported else "16:9"

    @staticmethod
    def _image_size(value: object) -> str:
        requested = str(value).upper() if value else "2K"
        return requested if requested in {"0.5K", "1K", "2K", "4K"} else "2K"

    @staticmethod
    def _output_url(response: Any) -> str:
        for part in getattr(response, "parts", None) or []:
            inline_data = getattr(part, "inline_data", None)
            data = getattr(inline_data, "data", None)
            if not data:
                continue
            mime_type = getattr(inline_data, "mime_type", None) or "image/png"
            if isinstance(data, bytes):
                encoded = base64.b64encode(data).decode("ascii")
            elif isinstance(data, str):
                try:
                    base64.b64decode(data, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise RuntimeError("Gemini 返回了损坏的 Base64 图片数据") from exc
                encoded = data
            else:
                continue
            return f"data:{mime_type};base64,{encoded}"
        raise RuntimeError("Gemini 没有返回图片；请确认模型支持 IMAGE 输出")

    @staticmethod
    def _error_detail(exc: Exception) -> str:
        code = getattr(exc, "code", None)
        message = getattr(exc, "message", None) or str(exc) or exc.__class__.__name__
        return f"{code} {message}" if code else str(message)
