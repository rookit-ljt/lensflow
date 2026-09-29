import uuid

from conftest import authenticated_client

from app.database import SessionLocal
from app.db_models import Generation, GenerationStatus
from app.main import _fail_interrupted_generations


def _generation_status(generation_id: str) -> str:
    with SessionLocal() as session:
        record = session.get(Generation, uuid.UUID(generation_id))
        assert record is not None
        session.refresh(record)
        return record.status.value


def _create_image_generation(client, project_name: str) -> str:
    project = client.post("/api/projects", json={"name": project_name}).json()
    shot = client.post(
        f"/api/projects/{project['id']}/shots",
        json={"sequence_number": 1, "title": "中断恢复镜头"},
    ).json()
    response = client.post(
        f"/api/shots/{shot['id']}/generations",
        json={"provider": "mock", "kind": "image", "prompt": "中断恢复测试"},
    )
    assert response.status_code == 202
    return str(response.json()["id"])


def test_recovery_fails_orphaned_running_generation() -> None:
    with authenticated_client() as client:
        orphan_id = _create_image_generation(client, "中断恢复 · 孤儿任务")
        with SessionLocal() as session:
            record = session.get(Generation, uuid.UUID(orphan_id))
            assert record is not None
            record.status = GenerationStatus.RUNNING
            record.error = None
            session.commit()

        assert _generation_status(orphan_id) == "running"
        _fail_interrupted_generations()

    assert _generation_status(orphan_id) == "failed"
    with SessionLocal() as session:
        record = session.get(Generation, uuid.UUID(orphan_id))
        assert record is not None
        assert record.error is not None and "服务重启" in record.error


def test_recovery_keeps_terminal_generations() -> None:
    with authenticated_client() as client:
        succeeded_id = _create_image_generation(client, "中断恢复 · 终态任务")
        assert _generation_status(succeeded_id) == "succeeded"

        _fail_interrupted_generations()

    assert _generation_status(succeeded_id) == "succeeded"
