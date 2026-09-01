import json

import httpx

from app.config import Settings
from app.providers.base import GenerationContext, GenerationRequest
from app.providers.openai_compatible import OpenAICompatibleTextProvider


def test_openai_compatible_text_provider() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://models.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            headers={"x-request-id": "request-123"},
            json={"choices": [{"message": {"content": "第一镜：海岸公路。"}}]},
        )

    settings = Settings(
        text_api_key="secret",
        text_base_url="https://models.example/v1",
        text_model="story-model",
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleTextProvider(settings, client)

    result = provider.generate(
        GenerationRequest(
            generation_id="generation-1",
            shot_id="shot-1",
            title="海岸公路",
            prompt="生成分镜",
            duration_seconds=5,
        )
    )

    assert result.provider_job_id == "request-123"
    assert result.output_text == "第一镜：海岸公路。"


def test_openai_compatible_text_provider_sends_multimodal_context() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "完成"}}]})

    settings = Settings(
        text_api_key="secret",
        text_base_url="https://models.example/v1",
        text_model="vision-model",
        _env_file=None,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleTextProvider(settings, client)
        provider.generate(
            GenerationRequest(
                generation_id="generation-2",
                shot_id="shot-1",
                title="动作设计",
                prompt="设计运镜",
                duration_seconds=5,
                contexts=(
                    GenerationContext(
                        node_id="text-node",
                        title="剧本",
                        kind="text",
                        text="孙悟空大战哥斯拉",
                    ),
                    GenerationContext(
                        node_id="image-node",
                        title="角色图",
                        kind="image",
                        image_url="data:image/png;base64,ZmFrZS1wbmc=",
                    ),
                ),
            )
        )

    content = captured["messages"][1]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "text"
    assert content[2]["type"] == "image_url"
    assert content[-1]["text"].endswith("设计运镜")
