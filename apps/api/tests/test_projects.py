import uuid

from conftest import authenticated_client


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
        assert list_response.json()[0]["id"] == generation["id"]

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
