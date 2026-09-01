from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_name: str = "LibTV API"
    environment: str = "development"
    # Runtime settings are intentionally limited to local development. In a
    # deployed environment configuration should come from secrets management.
    runtime_settings_enabled: bool = True
    database_url: str = f"sqlite:///{API_ROOT / 'libtv.db'}"
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]
    auth_cookie_name: str = "libtv_session"
    auth_session_days: int = 30
    auth_cookie_secure: bool = False
    google_client_id: str = ""
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672//"
    celery_task_always_eager: bool = True
    default_provider: str = "mock"
    text_provider: str = "openai_compatible"
    text_api_key: str = ""
    text_base_url: str = "https://api.openai.com/v1"
    text_model: str = ""
    text_system_prompt: str = "你是专业的影视创作助手。请直接输出可用于创作流程的中文结果，不要解释你的工作过程。"
    text_request_timeout_seconds: float = 90
    image_provider: str = "ark_seedream"
    image_api_key: str = ""
    image_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    image_model: str = "doubao-seedream-4-0-250828"
    image_request_timeout_seconds: float = 180
    image_watermark: bool = True
    local_video_base_url: str = "http://127.0.0.1:8787"
    local_video_model: str = "minimax-h3-local"
    local_video_request_timeout_seconds: float = 1800
    local_video_poll_interval_seconds: float = 2
    qwen_api_key: str = ""
    qwen_text_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_text_model: str = "qwen3.7-plus"
    qwen_image_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    qwen_image_model: str = "qwen-image-plus"
    qwen_image_edit_model: str = "qwen-image-2.0-pro"
    qwen_request_timeout_seconds: float = 300
    qwen_image_poll_interval_seconds: float = 1
    upload_directory: str = str(API_ROOT / "uploads")
    upload_max_bytes: int = 10 * 1024 * 1024
    agent_provider: str = "qwen"
    agent_model: str = ""
    agent_temperature: float = 0.45
    agent_max_tokens: int = 2800
    agent_history_messages: int = 20
    agent_system_prompt: str = (
        "你是 LibTV 画布中的影视创作 Agent。你会收到真实的项目、镜头、节点、连线和生成任务上下文。"
        "请用简洁、可执行的中文回答，优先引用当前镜头和节点中的具体信息。"
        "你不能直接修改画布或启动付费生成；明确的画布操作请求会进入独立的受控计划流程，"
        "生成 CanvasPatch 并等待用户批准后才执行。普通对话中禁止自行编写 CanvasPatch、禁止声称已经提交审批，"
        "也不得声称未经批准的操作已经完成；只有界面真实显示审批卡片才代表计划已创建。"
    )

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
