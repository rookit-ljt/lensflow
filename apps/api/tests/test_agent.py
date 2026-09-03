import json
import uuid

import httpx
from conftest import authenticated_client

from app.agent_runtime import (
    AgentPlanResult,
    AgentRuntimeStream,
    AgentState,
    SimpleAgentRuntime,
    parse_confirmation_request,
)
from app.config import Settings
from app.database import SessionLocal
from app.db_models import AgentRun, AgentRunStatus


def test_simple_agent_runtime_sends_context_and_history() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"x-request-id": "agent-request-1"},
            json={"choices": [{"message": {"content": "当前镜头需要加强动作连续性。"}}]},
        )

    settings = Settings(
        agent_provider="qwen",
        agent_model="qwen-agent",
        qwen_api_key="secret",
        qwen_text_base_url="https://models.example/v1",
        _env_file=None,
    )
    state: AgentState = {
        "thread_id": "thread-1",
        "run_id": "run-1",
        "messages": [{"role": "user", "content": "分析当前镜头"}],
        "context": {"project_id": "project-1"},
        "context_text": "项目：沿海失踪案\n当前镜头：海岸公路",
        "status": "thinking",
        "current_step": "compose_response",
        "pending_actions": [],
        "tool_calls": [],
        "errors": [],
    }
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = SimpleAgentRuntime(settings, client).invoke(state)

    assert result.model == "qwen-agent"
    assert result.provider_job_id == "agent-request-1"
    assert captured["messages"][2]["content"].endswith("当前镜头：海岸公路")
    assert captured["messages"][3] == {"role": "user", "content": "分析当前镜头"}
    assert "绝不能声称已经创建审批卡片" in captured["messages"][1]["content"]


def test_simple_agent_runtime_streams_openai_chunks() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            text=(
                'data: {"choices":[{"delta":{"content":"第一段"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"，第二段"}}]}\n\n'
                "data: [DONE]\n\n"
            ),
            headers={"content-type": "text/event-stream"},
        )

    settings = Settings(
        agent_provider="qwen",
        agent_model="qwen-agent",
        qwen_api_key="secret",
        qwen_text_base_url="https://models.example/v1",
        _env_file=None,
    )
    state: AgentState = {
        "thread_id": "thread-1",
        "run_id": "run-1",
        "messages": [{"role": "user", "content": "继续"}],
        "context": {"project_id": "project-1"},
        "context_text": "当前镜头：雨夜码头",
        "status": "thinking",
        "current_step": "compose_response",
        "pending_actions": [],
        "tool_calls": [],
        "errors": [],
    }
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        stream = SimpleAgentRuntime(settings, client).stream(state)
        chunks = list(stream.chunks)

    assert chunks == ["第一段", "，第二段"]
    assert captured["stream"] is True


def test_parse_confirmation_request_normalizes_single_and_multi_options() -> None:
    content = """我建议先确定输出方向。\n[[AGENT_CONFIRMATION]]
    {"title":"输出方向","description":"请选择生成方式","message":"请先选择一种生成方式",
    "kind":"multi","decision_key":"style_choice","options":[
      {"id":"t2v","label":"文生视频","description":"从文字开始","value":"text_to_video"},
      {"id":"i2v","label":"图片生视频","caption":"使用参考图","value":"image_to_video"}
    ]}[[/AGENT_CONFIRMATION]]"""

    parsed = parse_confirmation_request(content)

    assert parsed is not None
    assert parsed["kind"] == "multi_select"
    assert parsed["decision_key"] == "llm_confirmation"
    assert parsed["options"][0]["value"] == "text_to_video"
    assert parsed["options"][0]["caption"] == "从文字开始"


def test_llm_confirmation_pauses_and_resumes_with_user_choice(monkeypatch) -> None:
    states: list[AgentState] = []

    class ConfirmationRuntime:
        def stream(self, state: AgentState) -> AgentRuntimeStream:
            states.append(state)
            if len(states) == 1:
                content = (
                    "为了稳定生成，请先确定方向。"
                    '[[AGENT_CONFIRMATION]]{"title":"生成方式","description":"请选择输入方式",'
                    '"message":"先选一种生成方式，我再继续规划。","kind":"single_select",'
                    '"options":[{"id":"text","label":"文生视频","caption":"从 Prompt 开始"},'
                    '{"id":"image","label":"图片生视频","caption":"使用参考图"}]}'
                    "[[/AGENT_CONFIRMATION]]"
                )
            else:
                content = "收到你的选择，我会按该方向继续规划。"
            return AgentRuntimeStream(
                chunks=(content,),
                provider="mock",
                model="test-agent",
                provider_job_id=state["run_id"],
            )

    monkeypatch.setattr("app.agent_service.create_agent_runtime", lambda _: ConfirmationRuntime())
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "确认协议测试"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={"sequence_number": 1, "title": "测试镜头"},
        ).json()
        workflow = client.get(f"/api/shots/{shot['id']}/workflow").json()
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads", json={"title": "确认对话"}
        ).json()
        first = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "帮我规划这个镜头",
                "context": {
                    "project_id": project["id"],
                    "shot_id": shot["id"],
                    "selected_node_ids": [],
                    "canvas_version": workflow["updated_at"],
                },
            },
        ).json()
        assert client.get(f"/api/agent/runs/{first['id']}").json()["status"] == "waiting_user"
        pending = client.get(f"/api/agent/threads/{thread['id']}/pending-interrupt").json()
        assert pending["decision_key"] == "llm_confirmation"
        assert pending["payload"]["options"][1]["label"] == "图片生视频"

        resumed = client.post(
            f"/api/agent/runs/{first['id']}/resume",
            json={
                "interrupt_id": pending["id"],
                "response": {"option_id": "image"},
            },
        )
        assert resumed.status_code == 200
        assert client.get(f"/api/agent/runs/{first['id']}").json()["status"] == "completed"
        messages = client.get(f"/api/agent/threads/{thread['id']}/messages").json()

    assert len(states) == 2
    assert states[1]["messages"][-1]["content"] == "我选择“图片生视频”", states[1]["messages"]
    assert messages[-1]["content"] == "收到你的选择，我会按该方向继续规划。"


def test_agent_thread_run_and_events(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agent_service.create_agent_runtime",
        lambda _: SimpleAgentRuntime(Settings(agent_provider="mock", _env_file=None)),
    )
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "Agent 测试项目"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={
                "sequence_number": 1,
                "title": "雨夜码头",
                "description": "角色走向仓库。",
                "visual_prompt": "雨夜，冷色，远景。",
            },
        ).json()
        workflow = client.get(f"/api/shots/{shot['id']}/workflow").json()
        thread_response = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "镜头讨论"},
        )
        assert thread_response.status_code == 201
        thread = thread_response.json()

        run_response = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "分析当前镜头",
                "context": {
                    "project_id": project["id"],
                    "shot_id": shot["id"],
                    "selected_node_ids": [workflow["nodes"][0]["id"]],
                    "canvas_version": workflow["updated_at"],
                },
            },
        )
        assert run_response.status_code == 201
        run_id = run_response.json()["id"]

        run = client.get(f"/api/agent/runs/{run_id}").json()
        messages = client.get(f"/api/agent/threads/{thread['id']}/messages").json()
        events = client.get(f"/api/agent/runs/{run_id}/events").json()

    assert run["status"] == "completed"
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert "已读取当前项目与画布上下文" in messages[-1]["content"]
    assert any(event["event_type"] == "message.delta" for event in events)
    assert events[-1]["event_type"] == "run.completed"


def test_short_followup_to_canvas_proposal_creates_real_approval(monkeypatch) -> None:
    class FollowupRuntime:
        def stream(self, state: AgentState) -> AgentRuntimeStream:
            return AgentRuntimeStream(
                chunks=iter((
                    "### 画布更新计划\n新增两个图片节点并连接。确认后将显示审批卡片。",
                )),
                provider="mock",
                model="mock-agent",
                provider_job_id=state["run_id"],
            )

        def plan(self, state: AgentState) -> AgentPlanResult:
            assert state["messages"][-1]["content"] == "2"
            assert any("画布更新计划" in item["content"] for item in state["messages"][:-1])
            return AgentPlanResult(
                summary="准备新增并连接两个图片节点。",
                risk_level="low",
                actions=[
                    {
                        "type": "create_node",
                        "temp_id": "node_1",
                        "node_type": "generator",
                        "mode": "image",
                        "prompt": "罗盘指引",
                        "description": "新增罗盘指引图片节点",
                    },
                    {
                        "type": "create_node",
                        "temp_id": "node_2",
                        "node_type": "generator",
                        "mode": "image",
                        "prompt": "踏入迷雾",
                        "description": "新增踏入迷雾图片节点",
                    },
                    {
                        "type": "connect_nodes",
                        "source": "node_1",
                        "target": "node_2",
                        "description": "连接后续两个节点",
                    },
                ],
                provider="mock",
                model="mock-agent",
                provider_job_id=state["run_id"],
            )

    monkeypatch.setattr("app.agent_service.create_agent_runtime", lambda _: FollowupRuntime())
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "多轮计划确认"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={"sequence_number": 1, "title": "开场镜头"},
        ).json()
        workflow = client.get(f"/api/shots/{shot['id']}/workflow").json()
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "后续镜头规划"},
        ).json()
        first = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "规划一下后续镜头",
                "context": {
                    "project_id": project["id"],
                    "shot_id": shot["id"],
                    "selected_node_ids": [],
                    "canvas_version": workflow["updated_at"],
                },
            },
        ).json()
        assert client.get(f"/api/agent/runs/{first['id']}").json()["status"] == "completed"

        second = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "2",
                "context": {
                    "project_id": project["id"],
                    "shot_id": shot["id"],
                    "selected_node_ids": [],
                    "canvas_version": workflow["updated_at"],
                },
            },
        ).json()
        waiting = client.get(f"/api/agent/runs/{second['id']}").json()
        pending = client.get(
            f"/api/agent/threads/{thread['id']}/pending-approval"
        ).json()
        events = client.get(f"/api/agent/runs/{second['id']}/events").json()

    assert waiting["status"] == "waiting_approval"
    assert pending is not None
    assert [item["type"] for item in pending["patch"]["operations"]] == [
        "create_node",
        "create_node",
        "connect_nodes",
    ]
    assert any(event["event_type"] == "approval.required" for event in events)


def test_agent_run_can_be_cancelled(monkeypatch) -> None:
    monkeypatch.setattr("app.main.execute_agent_run", lambda _: None)
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "Agent 取消测试"}).json()
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "可取消对话"},
        ).json()
        run = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "生成很长的分析",
                "context": {
                    "project_id": project["id"],
                    "selected_node_ids": [],
                },
            },
        ).json()
        cancel_response = client.post(f"/api/agent/runs/{run['id']}/cancel")
        events = client.get(f"/api/agent/runs/{run['id']}/events").json()

    assert cancel_response.status_code == 202
    assert cancel_response.json()["status"] == "cancelled"
    assert events[-1]["event_type"] == "run.cancelled"


def test_cancelled_stream_keeps_partial_assistant_message(monkeypatch) -> None:
    class CancellingRuntime:
        def stream(self, state: AgentState) -> AgentRuntimeStream:
            def chunks():
                yield "已经生成的部分"
                with SessionLocal() as session:
                    run = session.get(AgentRun, uuid.UUID(state["run_id"]))
                    assert run is not None
                    run.status = AgentRunStatus.CANCELLED
                    session.commit()
                yield "不应写入的部分"

            return AgentRuntimeStream(
                chunks=chunks(),
                provider="mock",
                model="mock-agent",
                provider_job_id=state["run_id"],
            )

    monkeypatch.setattr("app.agent_service.create_agent_runtime", lambda _: CancellingRuntime())
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "部分回答测试"}).json()
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "部分回答"},
        ).json()
        run = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "开始回答",
                "context": {
                    "project_id": project["id"],
                    "selected_node_ids": [],
                },
            },
        ).json()
        messages = client.get(f"/api/agent/threads/{thread['id']}/messages").json()

    assert run["status"] == "thinking"
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "已经生成的部分"
    assert messages[-1]["message_metadata"]["cancelled"] is True


def test_canvas_patch_waits_for_approval_then_updates_selected_node(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agent_service.create_agent_runtime",
        lambda _: SimpleAgentRuntime(Settings(agent_provider="mock", _env_file=None)),
    )
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "Agent 画布审批"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={"sequence_number": 1, "title": "码头", "visual_prompt": "雨夜"},
        ).json()
        before = client.get(f"/api/shots/{shot['id']}/workflow").json()
        generator = next(node for node in before["nodes"] if node["type"] == "generator")
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "画布操作"},
        ).json()

        created = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "把当前节点提示词改成：电影感雨夜码头",
                "context": {
                    "project_id": project["id"],
                    "shot_id": shot["id"],
                    "selected_node_ids": [generator["id"]],
                    "canvas_version": before["updated_at"],
                },
            },
        )
        assert created.status_code == 201
        run = client.get(f"/api/agent/runs/{created.json()['id']}").json()
        pending = client.get(
            f"/api/agent/threads/{thread['id']}/pending-approval"
        ).json()
        unchanged = client.get(f"/api/shots/{shot['id']}/workflow").json()

        assert run["status"] == "waiting_approval"
        assert pending["patch"]["operations"][0]["type"] == "update_node_config"
        assert generator["config"] == next(
            node["config"] for node in unchanged["nodes"] if node["id"] == generator["id"]
        )

        decision = client.post(
            f"/api/agent/runs/{run['id']}/approval",
            json={"decision": "approve"},
        )
        after = client.get(f"/api/shots/{shot['id']}/workflow").json()

    assert decision.status_code == 200
    assert decision.json()["approval"]["status"] == "approved"
    assert decision.json()["canvas_revision"] == after["revision"]
    updated = next(node for node in after["nodes"] if node["id"] == generator["id"])
    assert updated["config"]["prompt"] == "电影感雨夜码头"
    assert after["updated_at"] != before["updated_at"]


def test_canvas_patch_updates_selected_prompt_node_content(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agent_service.create_agent_runtime",
        lambda _: SimpleAgentRuntime(Settings(agent_provider="mock", _env_file=None)),
    )
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "Agent 文本节点"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={"sequence_number": 1, "title": "提示词镜头", "visual_prompt": "旧提示词"},
        ).json()
        workflow = client.get(f"/api/shots/{shot['id']}/workflow").json()
        prompt_node = next(node for node in workflow["nodes"] if node["type"] == "prompt")
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "文本节点编辑"},
        ).json()

        created = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "把当前文本节点内容改成：新的镜头提示",
                "context": {
                    "project_id": project["id"],
                    "shot_id": shot["id"],
                    "selected_node_ids": [prompt_node["id"]],
                    "canvas_version": workflow["updated_at"],
                    "canvas_revision": workflow["revision"],
                },
            },
        )
        assert created.status_code == 201
        run = client.get(f"/api/agent/runs/{created.json()['id']}").json()
        assert run["status"] == "waiting_approval"
        assert run["approval"]["patch"]["operations"][0]["config_patch"] == {
            "detail": "新的镜头提示"
        }

        decision = client.post(
            f"/api/agent/runs/{run['id']}/approval",
            json={"decision": "approve"},
        )
        after = client.get(f"/api/shots/{shot['id']}/workflow").json()

    assert decision.status_code == 200
    updated_prompt = next(node for node in after["nodes"] if node["id"] == prompt_node["id"])
    assert updated_prompt["config"]["detail"] == "新的镜头提示"


def test_reject_canvas_patch_keeps_workflow_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agent_service.create_agent_runtime",
        lambda _: SimpleAgentRuntime(Settings(agent_provider="mock", _env_file=None)),
    )
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "Agent 拒绝审批"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={"sequence_number": 1, "title": "街道"},
        ).json()
        before = client.get(f"/api/shots/{shot['id']}/workflow").json()
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "拒绝画布操作"},
        ).json()
        created = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "新增一个图片节点",
                "context": {
                    "project_id": project["id"],
                    "shot_id": shot["id"],
                    "selected_node_ids": [],
                    "canvas_version": before["updated_at"],
                },
            },
        ).json()
        run = client.get(f"/api/agent/runs/{created['id']}").json()
        decision = client.post(
            f"/api/agent/runs/{run['id']}/approval",
            json={"decision": "reject"},
        )
        after = client.get(f"/api/shots/{shot['id']}/workflow").json()

    assert decision.status_code == 200
    assert decision.json()["approval"]["status"] == "rejected"
    assert len(after["nodes"]) == len(before["nodes"])
    assert after["updated_at"] == before["updated_at"]


def test_approved_canvas_patch_can_create_and_connect_node(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agent_service.create_agent_runtime",
        lambda _: SimpleAgentRuntime(Settings(agent_provider="mock", _env_file=None)),
    )
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "Agent 新增节点"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={"sequence_number": 1, "title": "天台"},
        ).json()
        before = client.get(f"/api/shots/{shot['id']}/workflow").json()
        selected = next(node for node in before["nodes"] if node["type"] == "generator")
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "新增并连接"},
        ).json()
        created = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "新增一个图片节点，并把当前节点连接到它",
                "context": {
                    "project_id": project["id"],
                    "shot_id": shot["id"],
                    "selected_node_ids": [selected["id"]],
                    "canvas_version": before["updated_at"],
                    "canvas_center": {"x": 520, "y": 340},
                },
            },
        ).json()
        run = client.get(f"/api/agent/runs/{created['id']}").json()
        assert [operation["type"] for operation in run["approval"]["patch"]["operations"]] == [
            "create_node",
            "connect_nodes",
        ]
        approved = client.post(
            f"/api/agent/runs/{run['id']}/approval",
            json={"decision": "approve"},
        )
        after = client.get(f"/api/shots/{shot['id']}/workflow").json()

    assert approved.status_code == 200
    assert len(after["nodes"]) == len(before["nodes"]) + 1
    assert len(after["edges"]) == len(before["edges"]) + 1
    created_node = next(node for node in after["nodes"] if node["id"] not in {
        item["id"] for item in before["nodes"]
    })
    assert created_node["config"]["mode"] == "image"
    assert created_node["position"] == {"x": 375.0, "y": 261.0}


def test_canvas_patch_rejects_stale_canvas_version(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agent_service.create_agent_runtime",
        lambda _: SimpleAgentRuntime(Settings(agent_provider="mock", _env_file=None)),
    )
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "Agent 版本冲突"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={"sequence_number": 1, "title": "车站"},
        ).json()
        before = client.get(f"/api/shots/{shot['id']}/workflow").json()
        generator = next(node for node in before["nodes"] if node["type"] == "generator")
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "冲突保护"},
        ).json()
        created = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "把当前节点提示词改成：清晨车站",
                "context": {
                    "project_id": project["id"],
                    "shot_id": shot["id"],
                    "selected_node_ids": [generator["id"]],
                    "canvas_version": before["updated_at"],
                },
            },
        ).json()
        run = client.get(f"/api/agent/runs/{created['id']}").json()
        save = client.put(
            f"/api/shots/{shot['id']}/workflow",
            json={
                "schema_version": before["schema_version"],
                "nodes": before["nodes"],
                "edges": before["edges"],
                "viewport": before["viewport"],
            },
        )
        assert save.status_code == 200
        decision = client.post(
            f"/api/agent/runs/{run['id']}/approval",
            json={"decision": "approve"},
        )
        failed_run = client.get(f"/api/agent/runs/{run['id']}").json()

    assert decision.status_code == 409
    assert "画布在计划生成后已发生变化" in decision.json()["detail"]
    assert failed_run["status"] == "failed"


def test_generate_image_node_wording_enters_approval_flow(monkeypatch) -> None:
    """Regression: natural Chinese '生成一个节点' must not fall through to plain chat."""

    monkeypatch.setattr(
        "app.agent_service.create_agent_runtime",
        lambda _: SimpleAgentRuntime(Settings(agent_provider="mock", _env_file=None)),
    )
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "自然语言新增节点"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={"sequence_number": 1, "title": "海岸公路"},
        ).json()
        workflow = client.get(f"/api/shots/{shot['id']}/workflow").json()
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "节点生成"},
        ).json()
        created = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "再生成一个图片节点，图片生成为一个白骨精角色",
                "context": {
                    "project_id": project["id"],
                    "shot_id": shot["id"],
                    "selected_node_ids": [],
                    "canvas_version": workflow["updated_at"],
                },
            },
        ).json()
        run = client.get(f"/api/agent/runs/{created['id']}").json()

    assert run["status"] == "waiting_approval"
    operation = run["approval"]["patch"]["operations"][0]
    assert operation["type"] == "create_node"
    assert operation["config"]["mode"] == "image"


def test_planner_rebases_stale_client_version_to_current_workflow(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agent_service.create_agent_runtime",
        lambda _: SimpleAgentRuntime(Settings(agent_provider="mock", _env_file=None)),
    )
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "Agent 版本重定基"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={"sequence_number": 1, "title": "旧客户端"},
        ).json()
        workflow = client.get(f"/api/shots/{shot['id']}/workflow").json()
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "版本重定基"},
        ).json()
        created = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "生成一个图片节点",
                "context": {
                    "project_id": project["id"],
                    "shot_id": shot["id"],
                    "selected_node_ids": [],
                    "canvas_version": "2000-01-01T00:00:00+00:00",
                },
            },
        ).json()
        run = client.get(f"/api/agent/runs/{created['id']}").json()
        decision = client.post(
            f"/api/agent/runs/{run['id']}/approval",
            json={"decision": "approve"},
        )

    assert run["canvas_version"] == workflow["updated_at"]
    assert run["approval"]["patch"]["base_canvas_version"] == workflow["updated_at"]
    assert decision.status_code == 200


def test_visual_asset_run_resumes_from_choice_then_requests_patch_approval() -> None:
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "多轮确认项目"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={"sequence_number": 1, "title": "污染实验室"},
        ).json()
        workflow = client.get(f"/api/shots/{shot['id']}/workflow").json()
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "角色场景设计"},
        ).json()
        created = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "为当前镜头生成角色及场景设计",
                "context": {
                    "project_id": project["id"],
                    "shot_id": shot["id"],
                    "selected_node_ids": [],
                    "canvas_version": workflow["updated_at"],
                },
            },
        ).json()
        waiting = client.get(f"/api/agent/runs/{created['id']}").json()
        interrupt = client.get(
            f"/api/agent/threads/{thread['id']}/pending-interrupt"
        ).json()

        assert waiting["status"] == "waiting_user"
        assert interrupt["kind"] == "single_select"
        assert interrupt["decision_key"] == "visual_style"
        assert len(interrupt["payload"]["options"]) == 6

        resumed = client.post(
            f"/api/agent/runs/{created['id']}/resume",
            json={
                "interrupt_id": interrupt["id"],
                "response": {"option_id": "saturated_realism"},
            },
        )
        planned = client.get(f"/api/agent/runs/{created['id']}").json()
        messages = client.get(f"/api/agent/threads/{thread['id']}/messages").json()
        events = client.get(f"/api/agent/runs/{created['id']}/events").json()

        assert resumed.status_code == 200
        assert resumed.json()["interrupt"]["status"] == "resolved"
        assert resumed.json()["event_cursor"] > 0
        assert planned["status"] == "waiting_approval"
        assert len(planned["approval"]["patch"]["operations"]) == 2
        assert all(
            operation["type"] == "create_node"
            for operation in planned["approval"]["patch"]["operations"]
        )
        assert any(message["message_type"] == "decision" for message in messages)
        interrupt_message = next(
            message for message in messages if message["message_type"] == "interrupt"
        )
        assert interrupt_message["message_metadata"]["interrupt"]["status"] == "resolved"
        assert {event["event_type"] for event in events} >= {
            "skill.loaded",
            "interrupt.created",
            "interrupt.resolved",
            "run.resumed",
            "approval.required",
        }

        approved = client.post(
            f"/api/agent/runs/{created['id']}/approval",
            json={"decision": "approve"},
        )
        after = client.get(f"/api/shots/{shot['id']}/workflow").json()

    assert approved.status_code == 200
    assert len(after["nodes"]) == len(workflow["nodes"]) + 2


def test_visual_style_interrupt_rejects_unknown_option() -> None:
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "无效选项"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={"sequence_number": 1, "title": "测试镜头"},
        ).json()
        workflow = client.get(f"/api/shots/{shot['id']}/workflow").json()
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "选项校验"},
        ).json()
        created = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "生成角色和场景设计",
                "context": {
                    "project_id": project["id"],
                    "shot_id": shot["id"],
                    "selected_node_ids": [],
                    "canvas_version": workflow["updated_at"],
                },
            },
        ).json()
        interrupt = client.get(
            f"/api/agent/threads/{thread['id']}/pending-interrupt"
        ).json()
        invalid = client.post(
            f"/api/agent/runs/{created['id']}/resume",
            json={
                "interrupt_id": interrupt["id"],
                "response": {"option_id": "not-a-style"},
            },
        )
        run = client.get(f"/api/agent/runs/{created['id']}").json()

    assert invalid.status_code == 409
    assert run["status"] == "waiting_user"


def test_agent_can_confirm_and_run_selected_generation_node() -> None:
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "Agent 生成工具"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={"sequence_number": 1, "title": "雨夜车站"},
        ).json()
        workflow = client.get(f"/api/shots/{shot['id']}/workflow").json()
        generator = next(node for node in workflow["nodes"] if node["type"] == "generator")
        generator["config"] = {
            **generator["config"],
            "mode": "image",
            "provider": "mock",
            "model": "mock-image",
            "prompt": "雨夜车站，电影感远景",
        }
        saved = client.put(
            f"/api/shots/{shot['id']}/workflow",
            json={
                "schema_version": workflow["schema_version"],
                "nodes": workflow["nodes"],
                "edges": workflow["edges"],
                "viewport": workflow["viewport"],
            },
        ).json()
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "生成当前节点"},
        ).json()
        created = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "生成当前节点",
                "context": {
                    "project_id": project["id"],
                    "shot_id": shot["id"],
                    "selected_node_ids": [generator["id"]],
                    "canvas_version": saved["updated_at"],
                },
            },
        ).json()
        waiting = client.get(f"/api/agent/runs/{created['id']}").json()
        interrupt = client.get(
            f"/api/agent/threads/{thread['id']}/pending-interrupt"
        ).json()

        assert waiting["status"] == "waiting_user"
        assert interrupt["decision_key"] == "generate_selected_node"
        assert interrupt["payload"]["presentation"] == "generation_confirmation"
        assert interrupt["payload"]["node_id"] == generator["id"]

        resumed = client.post(
            f"/api/agent/runs/{created['id']}/resume",
            json={
                "interrupt_id": interrupt["id"],
                "response": {"option_id": "confirm"},
            },
        )
        completed = client.get(f"/api/agent/runs/{created['id']}").json()
        generations = client.get(f"/api/shots/{shot['id']}/generations").json()
        messages = client.get(f"/api/agent/threads/{thread['id']}/messages").json()
        events = client.get(f"/api/agent/runs/{created['id']}/events").json()

    assert resumed.status_code == 200
    assert completed["status"] == "completed"
    assert generations[0]["node_id"] == generator["id"]
    assert generations[0]["kind"] == "image"
    assert generations[0]["provider"] == "mock"
    assert generations[0]["status"] == "succeeded"
    assert any(message["role"] == "tool" for message in messages)
    assert {event["event_type"] for event in events} >= {
        "tool.started",
        "tool.completed",
        "generation.created",
        "run.completed",
    }


def test_agent_generation_confirmation_can_be_cancelled() -> None:
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "Agent 取消生成"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={"sequence_number": 1, "title": "空镜"},
        ).json()
        workflow = client.get(f"/api/shots/{shot['id']}/workflow").json()
        generator = next(node for node in workflow["nodes"] if node["type"] == "generator")
        generator["config"] = {
            **generator["config"],
            "mode": "image",
            "provider": "mock",
            "model": "mock-image",
            "prompt": "清晨海面",
        }
        saved = client.put(
            f"/api/shots/{shot['id']}/workflow",
            json={
                "schema_version": workflow["schema_version"],
                "nodes": workflow["nodes"],
                "edges": workflow["edges"],
                "viewport": workflow["viewport"],
            },
        ).json()
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "取消生成"},
        ).json()
        run = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "运行当前节点",
                "context": {
                    "project_id": project["id"],
                    "shot_id": shot["id"],
                    "selected_node_ids": [generator["id"]],
                    "canvas_version": saved["updated_at"],
                },
            },
        ).json()
        interrupt = client.get(
            f"/api/agent/threads/{thread['id']}/pending-interrupt"
        ).json()
        cancelled = client.post(
            f"/api/agent/runs/{run['id']}/resume",
            json={
                "interrupt_id": interrupt["id"],
                "response": {"option_id": "cancel"},
            },
        )
        completed = client.get(f"/api/agent/runs/{run['id']}").json()
        generations = client.get(f"/api/shots/{shot['id']}/generations").json()

    assert cancelled.status_code == 200
    assert completed["status"] == "completed"
    assert generations == []


def test_agent_can_bind_asset_as_video_first_frame_after_approval(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agent_service.create_agent_runtime",
        lambda _: SimpleAgentRuntime(Settings(agent_provider="mock", _env_file=None)),
    )
    png = b"\x89PNG\r\n\x1a\nasset"
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "Agent 资产绑定"}).json()
        shot = client.post(
            f"/api/projects/{project['id']}/shots",
            json={"sequence_number": 1, "title": "首帧镜头"},
        ).json()
        workflow = client.get(f"/api/shots/{shot['id']}/workflow").json()
        generator = next(node for node in workflow["nodes"] if node["type"] == "generator")
        generator["config"] = {
            **generator["config"],
            "mode": "video",
            "provider": "local_h3",
            "model": "minimax-h3-local",
        }
        saved = client.put(
            f"/api/shots/{shot['id']}/workflow",
            json={
                "schema_version": workflow["schema_version"],
                "nodes": workflow["nodes"],
                "edges": workflow["edges"],
                "viewport": workflow["viewport"],
            },
        ).json()
        upload = client.post(
            "/api/uploads",
            params={"filename": "角色首帧.png", "project_id": project["id"]},
            content=png,
            headers={"Content-Type": "image/png"},
        ).json()
        thread = client.post(
            f"/api/projects/{project['id']}/agent/threads",
            json={"title": "Agent 资产引用"},
        ).json()
        created = client.post(
            f"/api/agent/threads/{thread['id']}/runs",
            json={
                "message": "把这个素材设为当前视频节点首帧",
                "context": {
                    "project_id": project["id"],
                    "shot_id": shot["id"],
                    "selected_node_ids": [generator["id"]],
                    "canvas_version": saved["updated_at"],
                    "canvas_revision": saved["revision"],
                },
            },
        )
        run = client.get(f"/api/agent/runs/{created.json()['id']}").json()
        assert run["status"] == "waiting_approval"
        operation = run["approval"]["patch"]["operations"][0]
        assert operation["type"] == "bind_asset"
        assert operation["asset_id"] == upload["asset_id"]
        assert operation["role"] == "first_frame"

        decision = client.post(
            f"/api/agent/runs/{run['id']}/approval",
            json={"decision": "approve"},
        )
        after = client.get(f"/api/shots/{shot['id']}/workflow").json()

    assert decision.status_code == 200
    updated = next(node for node in after["nodes"] if node["id"] == generator["id"])
    assert updated["config"]["video_reference_mode"] == "keyframe"
    assert updated["config"]["first_frame_node_id"] == f"upload:{upload['id']}"
    assert updated["config"]["uploaded_assets"][0]["asset_id"] == upload["asset_id"]
