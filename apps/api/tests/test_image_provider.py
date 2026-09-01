import httpx

from app.config import Settings
from app.providers.base import GenerationRequest
from app.providers.openai_compatible_image import OpenAICompatibleImageProvider


def test_openai_compatible_image_provider_normalizes_dalle2_size() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["authorization"]
        captured["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={"created": 123, "data": [{"url": "https://cdn.example.test/image.png"}]},
            headers={"x-request-id": "image-request-1"},
        )

    settings = Settings(
        image_api_key="secret-test-key",
        image_base_url="https://example.test/v1",
        image_model="dall-e-2",
        _env_file=None,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleImageProvider(settings, client)
        result = provider.generate(
            GenerationRequest(
                generation_id="generation-1",
                shot_id="shot-1",
                title="海岸公路",
                prompt="雨夜站台，电影构图",
                duration_seconds=5,
                parameters={"size": "2K", "count": 1},
            )
        )

    assert captured["authorization"] == "Bearer secret-test-key"
    assert '"size":"1024x1024"' in str(captured["body"])
    assert result.provider_job_id == "image-request-1"
    assert result.output_url == "https://cdn.example.test/image.png"


def test_openai_compatible_image_provider_requires_key() -> None:
    provider = OpenAICompatibleImageProvider(
        Settings(image_api_key="", image_model="dall-e-2", _env_file=None)
    )
    request = GenerationRequest(
        generation_id="generation-1",
        shot_id="shot-1",
        title="海岸公路",
        prompt="雨夜站台",
        duration_seconds=5,
    )

    try:
        provider.generate(request)
    except RuntimeError as exc:
        assert "IMAGE_API_KEY" in str(exc)
    else:
        raise AssertionError("missing image key should fail")
