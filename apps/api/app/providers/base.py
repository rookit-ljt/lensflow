from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class GenerationContext:
    node_id: str
    title: str
    kind: str
    text: str | None = None
    image_url: str | None = None


@dataclass(frozen=True)
class GenerationRequest:
    generation_id: str
    shot_id: str
    title: str
    prompt: str
    duration_seconds: int
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 1200
    parameters: dict[str, Any] | None = None
    contexts: tuple[GenerationContext, ...] = ()


@dataclass(frozen=True)
class GenerationResult:
    provider_job_id: str
    output_url: str | None = None
    output_text: str | None = None


class VideoProvider(Protocol):
    name: str

    def generate(self, request: GenerationRequest) -> GenerationResult: ...


class TextProvider(Protocol):
    name: str

    def generate(self, request: GenerationRequest) -> GenerationResult: ...


class ImageProvider(Protocol):
    name: str

    def generate(self, request: GenerationRequest) -> GenerationResult: ...


def prompt_with_text_context(request: GenerationRequest) -> str:
    references = [
        f"参考文本 {index}（{context.title}）：\n{context.text}"
        for index, context in enumerate(request.contexts, start=1)
        if context.kind == "text" and context.text
    ]
    if not references:
        return request.prompt
    return "\n\n".join([*references, f"请结合以上参考完成以下任务：\n{request.prompt}"])


def ensure_no_image_context(request: GenerationRequest, provider_name: str) -> None:
    if any(context.kind == "image" and context.image_url for context in request.contexts):
        raise RuntimeError(f"{provider_name} 当前接口不支持连线图片引用；请改用 Gemini 图片模型")
