import uuid

from conftest import authenticated_client

from app.database import SessionLocal
from app.db_models import AgentInterrupt, AgentInterruptStatus, AgentRun, AgentRunStatus


def test_create_project_and_shot() -> None:
    with authenticated_client() as client:
        project_response = client.post(
            "/api/projects",
            json={"name": "沿海失踪案", "description": "第一集制作项目"},
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]

        shot_response = client.post(
            f"/api/projects/{project_id}/shots",
            json={
                "sequence_number": 1,
                "title": "海岸公路",
                "description": "车辆沿海岸线行驶。",
                "visual_prompt": "清晨冷雾，远景，缓慢横移。",
                "duration_seconds": 4,
            },
        )
        assert shot_response.status_code == 201
        shot_id = shot_response.json()["id"]

        update_response = client.patch(
            f"/api/shots/{shot_id}",
            json={"visual_prompt": "清晨冷雾，远景，车辆缓慢驶过。", "duration_seconds": 6},
        )
        assert update_response.status_code == 200

        generation_response = client.post(
            f"/api/shots/{shot_id}/generations",
            json={"provider": "mock"},
        )
        assert generation_response.status_code == 202
        generation = generation_response.json()
        assert generation["status"] == "succeeded"
        assert generation["progress"] == 100
        assert generation["output_url"].startswith("mock://")

        assets_response = client.get(f"/api/projects/{project_id}/assets")
        assert assets_response.status_code == 200
        generation_assets = assets_response.json()
        assert any(
            asset["source_generation_id"] == generation["id"]
            and asset["role"] == "generation"
            for asset in generation_assets
        )

        text_generation_response = client.post(
            f"/api/shots/{shot_id}/generations",
            json={
                "provider": "mock",
                "kind": "text",
                "node_id": str(uuid.uuid4()),
                "prompt": "写一段海岸公路分镜",
                "model": "mock-text",
                "temperature": 0.6,
                "max_tokens": 800,
            },
        )
        assert text_generation_response.status_code == 202
        text_generation = text_generation_response.json()
        assert text_generation["kind"] == "text"
        assert text_generation["output_text"] == "文本生成结果：写一段海岸公路分镜"
        assert text_generation["output_url"] is None

        list_response = client.get(f"/api/shots/{shot_id}/generations")
        assert list_response.status_code == 200
        generation_ids = [item["id"] for item in list_response.json()]
        assert generation["id"] in generation_ids
        assert text_generation["id"] in generation_ids

        workflow_response = client.get(f"/api/shots/{shot_id}/workflow")
        assert workflow_response.status_code == 200
        workflow = workflow_response.json()
        assert len(workflow["nodes"]) == 3
        assert len(workflow["edges"]) == 2
        assert any(node["type"] == "generator" for node in workflow["nodes"])

        note_id = str(uuid.uuid4())
        workflow["nodes"].append(
            {
                "id": note_id,
                "type": "generator",
                "version": "1.0",
                "position": {"x": 210, "y": 480},
                "config": {
                    "mode": "image",
                    "prompt": "保留雨夜氛围",
                    "aspect_ratio": "16:9",
                    "resolution": "2K",
                },
            }
        )
        save_response = client.put(
            f"/api/shots/{shot_id}/workflow",
            json={
                "schema_version": workflow["schema_version"],
                "nodes": workflow["nodes"],
                "edges": workflow["edges"],
                "viewport": {"x": 12, "y": 24, "zoom": 0.9},
            },
        )
        assert save_response.status_code == 200
        saved = save_response.json()
        assert any(node["id"] == note_id for node in saved["nodes"])
        assert saved["viewport"]["zoom"] == 0.9
        assert saved["revision"] == workflow["revision"] + 1

        run_response = client.post(f"/api/shots/{shot_id}/run")
        assert run_response.status_code == 202
        run_results = run_response.json()
        assert run_results
        assert all(item["status"] == "succeeded" for item in run_results)
        assert any(item["kind"] == "image" for item in run_results)

        revisioned_payload = {
            "schema_version": saved["schema_version"],
            "nodes": saved["nodes"],
            "edges": saved["edges"],
            "viewport": saved["viewport"],
            "base_revision": saved["revision"],
            "operation_id": "test-workflow-operation-1",
        }
        revisioned_save = client.put(
            f"/api/shots/{shot_id}/workflow", json=revisioned_payload
        )
        assert revisioned_save.status_code == 200

        revisioned = revisioned_save.json()
        assert revisioned["revision"] == saved["revision"] + 1

        idempotent_retry = client.put(
            f"/api/shots/{shot_id}/workflow", json=revisioned_payload
        )
        assert idempotent_retry.status_code == 200
        assert idempotent_retry.json()["revision"] == revisioned["revision"]

        stale_save = client.put(
            f"/api/shots/{shot_id}/workflow",
            json={**revisioned_payload, "operation_id": "test-workflow-operation-2"},
        )
        assert stale_save.status_code == 409

        detail_response = client.get(f"/api/projects/{project_id}")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["name"] == "沿海失踪案"
    assert detail["shots"][0]["title"] == "海岸公路"
    assert detail["shots"][0]["duration_seconds"] == 6


def test_agent_first_workflow_can_start_empty() -> None:
    with authenticated_client() as client:
        project_response = client.post(
            "/api/projects",
            json={"name": "Agent 首次创作", "description": ""},
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["id"]
        shot_response = client.post(
            f"/api/projects/{project_id}/shots",
            json={
                "sequence_number": 1,
                "title": "第一个镜头",
                "description": "",
                "visual_prompt": "一只猫在窗边看雪。",
                "duration_seconds": 5,
            },
        )
        assert shot_response.status_code == 201
        shot_id = shot_response.json()["id"]

        workflow_response = client.get(f"/api/shots/{shot_id}/workflow?empty=true")
        assert workflow_response.status_code == 200
        workflow = workflow_response.json()
        assert workflow["nodes"] == []
        assert workflow["edges"] == []

        # Once materialized, a regular read keeps the intentionally empty
        # workflow instead of applying the legacy starter template.
        regular_response = client.get(f"/api/shots/{shot_id}/workflow")
        assert regular_response.status_code == 200
        assert regular_response.json()["nodes"] == []


def test_delete_project_removes_project_and_canvas_data() -> None:
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "待删除项目"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={"sequence_number": 1, "title": "开场"},
        ).json()
        workflow = client.get(f"/api/shots/{shot['id']}/workflow").json()
        assert workflow["nodes"]

        deleted = client.delete(f"/api/projects/{project['id']}")
        assert deleted.status_code == 204
        assert client.get(f"/api/projects/{project['id']}").status_code == 404
        assert client.get(f"/api/shots/{shot['id']}/workflow").status_code == 404
        assert all(item["id"] != project["id"] for item in client.get("/api/projects").json())


def test_delete_project_cancels_paused_agent_runs() -> None:
    """Paused question/approval runs must not make dashboard deletion impossible."""
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "可删除的暂停项目"}).json()
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "等待确认"},
        ).json()
        # Create an actual waiting-user run through the public API in mock mode.
        run = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "请先确认创作方向",
                "context": {"project_id": project["id"]},
            },
        ).json()
        with SessionLocal() as session:
            db_run = session.get(AgentRun, uuid.UUID(run["id"]))
            db_run.status = AgentRunStatus.WAITING_USER
            interrupt = AgentInterrupt(
                run_id=db_run.id,
                sequence=1,
                kind="question_form",
                decision_key="test",
                title="确认方向",
                payload={"questions": []},
                status=AgentInterruptStatus.PENDING,
            )
            session.add(interrupt)
            session.commit()
            run_id = db_run.id

        deleted = client.delete(f"/api/projects/{project['id']}")
        assert deleted.status_code == 204, deleted.text
        with SessionLocal() as session:
            assert session.get(AgentRun, run_id) is None


def test_delete_project_still_blocks_provider_work() -> None:
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "生成中的项目"}).json()
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "生成中"},
        ).json()
        run = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={"message": "处理", "context": {"project_id": project["id"]}},
        ).json()
        with SessionLocal() as session:
            db_run = session.get(AgentRun, uuid.UUID(run["id"]))
            db_run.status = AgentRunStatus.THINKING
            session.commit()
        blocked = client.delete(f"/api/projects/{project['id']}")
        assert blocked.status_code == 409
        assert "任务处理中" in blocked.json()["detail"]
