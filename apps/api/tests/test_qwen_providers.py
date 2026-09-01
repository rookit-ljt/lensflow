import json

import httpx

from app.config import Settings
from app.providers.base import GenerationContext, GenerationRequest
from app.providers.qwen_image import QwenImageProvider
from app.providers.qwen_text import QwenTextProvider
from app.schemas import GenerationCreate


def generation_request(**overrides: object) -> GenerationRequest:
    values = {
        "generation_id": "generation-1",
        "shot_id": "shot-1",
        "title": "海岸公路",
        "prompt": "雨夜站台，电影构图",
        "duration_seconds": 5,
    }
    values.update(overrides)
    return GenerationRequest(**values)


def test_generation_schema_accepts_qwen_provider() -> None:
    payload = GenerationCreate(provider="qwen", kind="text", prompt="生成分镜")

    assert payload.provider == "qwen"


def test_qwen_text_provider_uses_compatible_endpoint() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"x-request-id": "qwen-text-1"},
            json={"choices": [{"message": {"content": "第一镜：雨夜站台。"}}]},
        )

    settings = Settings(
        qwen_api_key="qwen-secret",
        qwen_text_base_url="https://qwen.example/compatible-mode/v1",
        qwen_text_model="qwen3.7-plus",
        _env_file=None,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = QwenTextProvider(settings, client).generate(generation_request())

    assert captured["url"] == "https://qwen.example/compatible-mode/v1/chat/completions"
    assert captured["authorization"] == "Bearer qwen-secret"
    assert captured["body"]["model"] == "qwen3.7-plus"
    assert result.provider_job_id == "qwen-text-1"
    assert result.output_text == "第一镜：雨夜站台。"


def test_qwen_image_provider_creates_and_polls_task() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        assert request.headers["authorization"] == "Bearer qwen-secret"
        if request.method == "POST":
            body = json.loads(request.content)
            assert request.headers["x-dashscope-async"] == "enable"
            assert body["model"] == "qwen-image-plus"
            assert body["parameters"]["size"] == "1664*928"
            return httpx.Response(200, json={"output": {"task_id": "task-123"}})
        return httpx.Response(
            200,
            json={
                "request_id": "qwen-image-1",
                "output": {
                    "task_status": "SUCCEEDED",
                    "results": [{"url": "https://cdn.example/qwen.png"}],
                },
            },
        )

    settings = Settings(
        qwen_api_key="qwen-secret",
        qwen_image_base_url="https://qwen.example/api/v1",
        qwen_image_model="qwen-image-plus",
        _env_file=None,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = QwenImageProvider(settings, client, sleep=lambda _: None).generate(
            generation_request(parameters={"aspect_ratio": "16:9"})
        )

    assert calls == [
        (
            "POST",
            "https://qwen.example/api/v1/services/aigc/text2image/image-synthesis",
        ),
        ("GET", "https://qwen.example/api/v1/tasks/task-123"),
    ]
    assert result.provider_job_id == "qwen-image-1"
    assert result.output_url == "https://cdn.example/qwen.png"


def test_qwen_image_provider_auto_uses_edit_model_for_connected_image() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "request_id": "qwen-edit-1",
                "output": {
                    "choices": [{
                        "message": {
                            "content": [{"image": "https://cdn.example/qwen-edited.png"}]
                        }
                    }]
                },
            },
        )

    settings = Settings(
        qwen_api_key="qwen-secret",
        qwen_image_base_url="https://qwen.example/api/v1",
        qwen_image_model="qwen-image-plus",
        qwen_image_edit_model="qwen-image-2.0-pro",
        _env_file=None,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = QwenImageProvider(settings, client).generate(
            generation_request(
                model="qwen-image-plus",
                contexts=(
                    GenerationContext(
                        node_id="image-node",
                        title="角色参考图",
                        kind="image",
                        image_url="data:image/png;base64,ZmFrZS1wbmc=",
                    ),
                ),
            )
        )

    assert captured["url"].endswith("/services/aigc/multimodal-generation/generation")
    assert captured["body"]["model"] == "qwen-image-2.0-pro"
    content = captured["body"]["input"]["messages"][0]["content"]
    assert content[0]["image"].startswith("data:image/png;base64,")
    assert content[-1]["text"] == "雨夜站台，电影构图"
    assert result.output_url == "https://cdn.example/qwen-edited.png"
