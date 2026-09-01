import base64
import uuid

from conftest import authenticated_client
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal
from app.db_models import Generation


def _create_generation(client: TestClient, kind: str) -> dict[str, object]:
    project = client.post("/api/projects", json={"name": f"{kind} 下载测试"}).json()
    shot = client.post(
        f"/api/projects/{project['id']}/shots",
        json={"sequence_number": 1, "title": "下载镜头"},
    ).json()
    response = client.post(
        f"/api/shots/{shot['id']}/generations",
        json={"provider": "mock", "kind": kind, "prompt": "下载测试"},
    )
    assert response.status_code == 202
    return response.json()


def test_download_image_data_url() -> None:
    content = b"not-a-real-png-but-downloadable"
    with authenticated_client() as client:
        generation = _create_generation(client, "image")
        with SessionLocal() as session:
            record = session.get(Generation, uuid.UUID(str(generation["id"])))
            assert record is not None
            record.output_url = (
                "data:image/png;base64," + base64.b64encode(content).decode("ascii")
            )
            session.commit()

        response = client.get(f"/api/generations/{generation['id']}/download")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"].endswith('.png"')


def test_download_video_data_url_uses_video_filename() -> None:
    content = b"small-video-payload"
    with authenticated_client() as client:
        generation = _create_generation(client, "video")
        with SessionLocal() as session:
            record = session.get(Generation, uuid.UUID(str(generation["id"])))
            assert record is not None
            record.output_url = (
                "data:video/mp4;base64," + base64.b64encode(content).decode("ascii")
            )
            session.commit()

        response = client.get(f"/api/generations/{generation['id']}/download")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["content-disposition"].endswith('.mp4"')


def test_download_rejects_non_media_generation() -> None:
    with authenticated_client() as client:
        generation = _create_generation(client, "text")
        response = client.get(f"/api/generations/{generation['id']}/download")

    assert response.status_code == 409


def test_extract_video_last_frame_creates_upload(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_directory", str(tmp_path))
    png = b"\x89PNG\r\n\x1a\nlast-frame"
    monkeypatch.setattr("app.main.extract_last_video_frame", lambda _: png)

    with authenticated_client() as client:
        generation = _create_generation(client, "video")
        response = client.post(f"/api/generations/{generation['id']}/last-frame")
        assert response.status_code == 201
        upload = response.json()
        image_response = client.get(upload["url"])

    assert upload["kind"] == "image"
    assert upload["content_type"] == "image/png"
    assert upload["filename"].startswith("video-last-frame-")
    assert image_response.content == png


def test_extract_last_frame_rejects_image_generation() -> None:
    with authenticated_client() as client:
        generation = _create_generation(client, "image")
        response = client.post(f"/api/generations/{generation['id']}/last-frame")

    assert response.status_code == 422
    assert response.json()["detail"] == "只能从视频生成结果中截取末帧"
