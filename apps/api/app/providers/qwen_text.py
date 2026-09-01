import httpx

from ..config import Settings
from .openai_compatible import OpenAICompatibleTextProvider


class QwenTextProvider(OpenAICompatibleTextProvider):
    """Calls Qwen through Alibaba Cloud Model Studio's OpenAI-compatible API."""

    name = "qwen"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        super().__init__(
            settings,
            client,
            api_key=settings.qwen_api_key,
            base_url=settings.qwen_text_base_url,
            default_model=settings.qwen_text_model,
            api_key_name="QWEN_API_KEY",
            provider_label="千问文本模型",
        )
