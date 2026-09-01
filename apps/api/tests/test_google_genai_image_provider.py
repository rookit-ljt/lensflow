from types import SimpleNamespace

from app.config import Settings
from app.providers.base import GenerationContext, GenerationRequest
from app.providers.google_genai_image import GoogleGenAIImageProvider
from app.schemas import GenerationCreate


class FakeModels:
    def __init__(self) -> None:
        self.call: dict[str, object] = {}

    def generate_content(self, **kwargs: object) -> SimpleNamespace:
        self.call = kwargs
        return SimpleNamespace(
            response_id="gemini-request-1",
            parts=[
                SimpleNamespace(
                    inline_data=SimpleNamespace(data=b"fake-png", mime_type="image/png")
                )
            ],
        )


def test_generation_schema_accepts_google_genai_provider() -> None:
    payload = GenerationCreate(provider="google_genai", kind="image", prompt="雨夜站台")

    assert payload.provider == "google_genai"


def test_google_genai_image_provider_maps_image_config_and_response() -> None:
    models = FakeModels()
    client = SimpleNamespace(models=models)
    settings = Settings(
        image_api_key="secret-test-key",
        image_base_url="https://example.test/google",
        image_model="gemini-3.1-flash-image",
        _env_file=None,
    )
    provider = GoogleGenAIImageProvider(settings, client)

    result = provider.generate(
        GenerationRequest(
            generation_id="generation-1",
            shot_id="shot-1",
            title="海岸公路",
            prompt="雨夜站台，电影构图",
            duration_seconds=5,
            parameters={"size": "2K", "aspect_ratio": "16:9"},
        )
    )

    config = models.call["config"]
    assert models.call["model"] == "gemini-3.1-flash-image"
    assert config.response_modalities == ["IMAGE"]
    assert config.image_config.aspect_ratio == "16:9"
    assert config.image_config.image_size == "2K"
    assert result.provider_job_id == "gemini-request-1"
    assert result.output_url == "data:image/png;base64,ZmFrZS1wbmc="


def test_google_genai_image_provider_sends_connected_text_and_image_context() -> None:
    models = FakeModels()
    client = SimpleNamespace(models=models)
    provider = GoogleGenAIImageProvider(
        Settings(
            image_api_key="secret-test-key",
            image_base_url="https://example.test/google",
            image_model="gemini-3.1-flash-image",
            _env_file=None,
        ),
        client,
    )

    provider.generate(
        GenerationRequest(
            generation_id="generation-2",
            shot_id="shot-1",
            title="合成画面",
            prompt="让两个角色同框",
            duration_seconds=5,
            contexts=(
                GenerationContext(
                    node_id="text-node",
                    title="剧情",
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

    contents = models.call["contents"]
    assert [part.text for part in contents if part.text]
    assert any(part.inline_data and part.inline_data.data == b"fake-png" for part in contents)
    assert "让两个角色同框" in contents[-1].text
