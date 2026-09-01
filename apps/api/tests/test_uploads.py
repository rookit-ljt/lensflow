import uuid

from conftest import authenticated_client

from app.config import get_settings
from app.database import SessionLocal
from app.db_models import Asset, Generation
from app.generation_context import resolve_generation_contexts
from app.uploads import store_uploaded_image

PNG_CONTENT = b"\x89PNG\r\n\x1a\nsmall-test-image"


def test_upload_and_read_image(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_directory", str(tmp_path))

    with authenticated_client() as client:
        response = client.post(
            "/api/uploads",
            params={"filename": "reference.png"},
            content=PNG_CONTENT,
            headers={"Content-Type": "image/png"},
        )
        assert response.status_code == 201
        upload = response.json()

        image_response = client.get(upload["url"])

    assert upload["filename"] == "reference.png"
    assert upload["kind"] == "image"
    assert upload["content_type"] == "image/png"
    assert image_response.status_code == 200
    assert image_response.content == PNG_CONTENT
    assert image_response.headers["content-type"] == "image/png"


def test_upload_registers_project_asset(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_directory", str(tmp_path))

    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "素材库测试"}).json()
        response = client.post(
            "/api/uploads",
            params={"filename": "角色.png", "project_id": project["id"]},
            content=PNG_CONTENT,
            headers={"Content-Type": "image/png"},
        )
        assert response.status_code == 201
        upload = response.json()

        assets_response = client.get(f"/api/projects/{project['id']}/assets")

    assert upload["asset_id"]
    assert assets_response.status_code == 200
    assets = assets_response.json()
    assert len(assets) == 1
    assert assets[0]["id"] == upload["asset_id"]
    assert assets[0]["source_upload_id"] == upload["id"]
    assert assets[0]["role"] == "reference"


def test_project_asset_can_be_deleted_when_unused(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_directory", str(tmp_path))

    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "删除素材测试"}).json()
        upload = client.post(
            "/api/uploads",
            params={"filename": "待删除.png", "project_id": project["id"]},
            content=PNG_CONTENT,
            headers={"Content-Type": "image/png"},
        ).json()

        response = client.delete(f"/api/assets/{upload['asset_id']}")
        assets = client.get(f"/api/projects/{project['id']}/assets").json()
        missing_upload = client.get(upload["url"])

    assert response.status_code == 204
    assert assets == []
    assert missing_upload.status_code == 404


def test_project_asset_delete_is_blocked_while_canvas_references_it(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_directory", str(tmp_path))

    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "素材引用保护"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={"sequence_number": 1, "title": "镜头一"},
        ).json()
        upload = client.post(
            "/api/uploads",
            params={"filename": "角色.png", "project_id": project["id"]},
            content=PNG_CONTENT,
            headers={"Content-Type": "image/png"},
        ).json()
        workflow = client.get(f"/api/shots/{shot['id']}/workflow").json()
        workflow["nodes"].append({
            "id": str(uuid.uuid4()),
            "type": "generator",
            "version": "1.0",
            "position": {"x": 120, "y": 120},
            "config": {"uploaded_assets": [upload]},
        })
        saved = client.put(
            f"/api/shots/{shot['id']}/workflow",
            json={
                "schema_version": workflow["schema_version"],
                "nodes": workflow["nodes"],
                "edges": workflow["edges"],
                "viewport": workflow["viewport"],
            },
        )
        assert saved.status_code == 200

        response = client.delete(f"/api/assets/{upload['asset_id']}")

    assert response.status_code == 409
    assert "画布节点引用" in response.json()["detail"]


def test_upload_rejects_unsupported_content(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_directory", str(tmp_path))

    with authenticated_client() as client:
        response = client.post(
            "/api/uploads",
            params={"filename": "notes.txt"},
            content=b"not an image",
            headers={"Content-Type": "text/plain"},
        )

    assert response.status_code == 415
    assert "PNG" in response.json()["detail"]


def test_uploaded_image_becomes_generation_context(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_directory", str(tmp_path))
    upload_id = uuid.uuid4()
    store_uploaded_image(settings, upload_id, PNG_CONTENT, "image/png")
    generation = Generation(
        parameters={
            "uploaded_assets": [
                {"id": str(upload_id), "filename": "角色参考.png"},
            ]
        }
    )

    with SessionLocal() as session:
        contexts = resolve_generation_contexts(session, generation)

    assert len(contexts) == 1
    assert contexts[0].node_id == f"upload:{upload_id}"
    assert contexts[0].title == "角色参考.png"
    assert contexts[0].image_url is not None
    assert contexts[0].image_url.startswith("data:image/png;base64,")


def test_generated_project_asset_becomes_generation_context() -> None:
    asset_id = uuid.uuid4()
    asset = Asset(
        id=asset_id,
        user_id=uuid.uuid4(),
        kind="image",
        role="generation",
        filename="生成图片.png",
        content_type="image/png",
        size=0,
        url="data:image/png;base64,aW1hZ2U=",
        metadata_json={"source": "generation"},
    )
    generation = Generation(
        parameters={
            "uploaded_assets": [
                {
                    "id": str(asset_id),
                    "asset_id": str(asset_id),
                    "filename": asset.filename,
                },
            ],
        }
    )

    with SessionLocal() as session:
        session.add(asset)
        session.commit()
        contexts = resolve_generation_contexts(session, generation)

    assert len(contexts) == 1
    assert contexts[0].node_id == f"upload:{asset_id}"
    assert contexts[0].title == "生成图片.png"
    assert contexts[0].image_url == asset.url
