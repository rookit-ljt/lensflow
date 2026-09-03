from pathlib import Path

from app.config import Settings
from app.runtime_settings import apply_settings, settings_view


def test_local_video_settings_are_persisted_without_an_api_key(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    monkeypatch.setattr("app.runtime_settings.ROOT_ENV", env_file)
    settings = Settings(_env_file=None)

    apply_settings(
        settings,
        provider="local_h3",
        kind="video",
        api_key="",
        model="h3-preview",
        base_url="http://127.0.0.1:8787",
        apply_to_agent=False,
    )

    assert settings.local_video_model == "h3-preview"
    assert settings.local_video_base_url == "http://127.0.0.1:8787"
    assert "LOCAL_VIDEO_MODEL=\"h3-preview\"" in env_file.read_text(encoding="utf-8")
    assert settings_view(settings)["local_video_configured"] is True
