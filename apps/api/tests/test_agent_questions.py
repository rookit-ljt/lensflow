import json
import uuid

import httpx
import pytest
from conftest import authenticated_client
from pydantic import ValidationError

from app.agent_questions import AgentReply, resolve_question_answers
from app.agent_runtime import AgentRuntimeStream, SimpleAgentRuntime
from app.config import Settings
from app.database import SessionLocal
from app.db_models import AgentRun, AgentRunStatus

FORM = {
    "message": "先确认这三个问题，再继续准备分镜。",
    "questions": [
        {"id": "format", "title": "你想制作什么？", "kind": "single_select", "options": [
            {"id": "image", "label": "一张图片", "caption": "定格战斗瞬间"},
            {"id": "video", "label": "一段短视频", "caption": "呈现连续的战斗镜头"},
        ]},
        {"id": "reference", "title": "哪些内容需要保持一致？", "kind": "multi_select", "options": [
            {"id": "character", "label": "角色外观"},
            {"id": "scene", "label": "场景风格"},
        ]},
        {"id": "setting", "title": "故事发生在哪里？", "kind": "text", "options": []},
    ],
}


def state():
    return {
        "thread_id": "thread", "run_id": "run", "messages": [{"role": "user", "content": "孙悟空大战齐天大圣"}],
        "context": {}, "context_text": "当前项目：新故事", "status": "thinking",
        "current_step": "compose_response", "pending_actions": [], "tool_calls": [], "errors": [],
    }


def settings():
    return Settings(agent_provider="qwen", qwen_api_key="test-key", agent_model="test-model", _env_file=None)


def test_structured_reply_schema_supports_all_question_kinds():
    reply = AgentReply.model_validate(FORM)
    assert reply.confirmation()["kind"] == "question_form"
    assert len(reply.questions) == 3
    assert AgentReply.model_validate({"message": "剧本已准备好。", "questions": []}).confirmation() is None


@pytest.mark.parametrize("questions", [
    [FORM["questions"][0], FORM["questions"][0]],
    [{"id": "q", "title": "重复选项", "kind": "single_select", "options": [
        {"id": "a", "label": "甲"}, {"id": "a", "label": "乙"},
    ]}],
    [{"id": "q", "title": "缺少选项", "kind": "single_select", "options": []}],
])
def test_structured_reply_rejects_invalid_ids_and_options(questions):
    with pytest.raises(ValidationError):
        AgentReply.model_validate({"message": "确认", "questions": questions})


def answers():
    return {"answers": [
        {"question_id": "format", "option_ids": ["video"]},
        {"question_id": "reference", "option_ids": ["character", "scene"]},
        {"question_id": "setting", "text": "花果山，傍晚"},
    ]}


def test_form_answers_retain_question_mapping_and_custom_text():
    resolved = resolve_question_answers(FORM["questions"], answers())
    assert resolved["answers"][1]["labels"] == ["角色外观", "场景风格"]
    assert "故事发生在哪里？：花果山，傍晚" in resolved["label"]


def test_skip_and_custom_choice_are_explicit_not_approval():
    response = answers()
    response["answers"][0] = {"question_id": "format", "text": "竖屏连环画"}
    response["answers"][1] = {"question_id": "reference", "skipped": True}
    resolved = resolve_question_answers(FORM["questions"], response)
    assert resolved["answers"][0]["text"] == "竖屏连环画"
    assert resolved["answers"][1]["labels"] == []
    assert "未作选择" in resolved["label"]


def test_all_skipped_questions_have_no_selected_values():
    result = resolve_question_answers(FORM["questions"], {"answers": [
        {"question_id": question["id"], "skipped": True} for question in FORM["questions"]
    ]})
    assert all(answer["skipped"] and not answer["labels"] for answer in result["answers"])


@pytest.mark.parametrize("submitted", [[], answers()["answers"][:1], answers()["answers"] + [answers()["answers"][0]]])
def test_partial_or_duplicate_question_submissions_are_rejected(submitted):
    with pytest.raises(ValueError):
        resolve_question_answers(FORM["questions"], {"answers": submitted})


@pytest.mark.parametrize("invalid", [
    {"question_id": "format", "option_ids": ["forged"]},
    {"question_id": "format", "option_ids": ["video", "image"]},
    {"question_id": "format", "option_ids": ["video", "video"]},
    {"question_id": "format", "text": " "},
    {"question_id": "format", "text": "x" * 2001},
    {"question_id": "format", "option_ids": ["video"], "text": "custom"},
    {"question_id": "format", "option_ids": ["video"], "skipped": True},
    {"question_id": "unknown", "text": "foreign question"},
])
def test_invalid_answers_rejected_before_resume(invalid):
    response = answers()
    response["answers"][0] = invalid
    with pytest.raises(ValueError):
        resolve_question_answers(FORM["questions"], response)


def test_runtime_validates_json_without_exposing_protocol_text():
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(FORM)}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = SimpleAgentRuntime(settings(), client).respond(state())
    assert result.structured
    assert list(result.chunks) == [FORM["message"]]
    assert len(result.confirmation["questions"]) == 3
    assert captured[0]["response_format"] == {"type": "json_object"}
    assert captured[0]["stream"] is False


def test_invalid_model_output_is_repaired_once():
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        content = "请告诉我你想做什么？" if len(calls) == 1 else json.dumps(FORM)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = SimpleAgentRuntime(settings(), client).respond(state())
    assert len(calls) == 2
    assert result.confirmation is not None


@pytest.mark.parametrize("content", ["plain question?", json.dumps({"message": "hi"}), json.dumps(FORM)])
def test_invalid_or_repeated_questions_fail_bounded_instead_of_loop(content):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    current = state()
    current["context"]["answered_question_titles"] = ["你想制作什么？"]
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(RuntimeError, match="已停止本轮"),
    ):
        SimpleAgentRuntime(settings(), client).respond(current)
    assert len(calls) == 2


def test_plain_answer_has_no_forced_question():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {
            "content": json.dumps({"message": "这是一段完整的开场剧本。", "questions": []}),
        }}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = SimpleAgentRuntime(settings(), client).respond(state())
    assert result.confirmation is None


def test_question_form_resumes_multiple_rounds_with_latest_answer(monkeypatch):
    states = []

    class Runtime:
        def respond(self, current):
            states.append(current)
            if len(states) == 1:
                reply = AgentReply.model_validate(FORM)
            elif len(states) == 2:
                reply = AgentReply.model_validate({
                    "message": "收到，补充一个时长即可。", "questions": [{
                        "id": "duration", "title": "想做多长？", "kind": "text", "options": [],
                    }],
                })
            else:
                reply = AgentReply.model_validate({"message": "按你的全部回答，下面开始分镜。", "questions": []})
            return AgentRuntimeStream(
                chunks=(reply.message,), provider="mock", model="test", provider_job_id=current["run_id"],
                confirmation=reply.confirmation(), structured=True,
            )

    monkeypatch.setattr("app.agent_service.create_agent_runtime", lambda _: Runtime())
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "分页问题测试"}).json()
        shot = client.post(f"/api/projects/{project['id']}/shots", json={"sequence_number": 1, "title": "开场"}).json()
        thread = client.post(f"/api/projects/{project['id']}/agent/threads", json={"title": "测试"}).json()
        run = client.post(f"/api/agent/threads/{thread['id']}/runs", json={
            "message": "孙悟空大战齐天大圣", "context": {"project_id": project["id"], "shot_id": shot["id"]},
        }).json()
        endpoint = f"/api/agent/runs/{run['id']}/resume"
        pending = client.get(f"/api/agent/threads/{thread['id']}/pending-interrupt").json()
        assert pending["kind"] == "question_form"
        assert client.get(f"/api/agent/runs/{run['id']}").json()["status"] == "waiting_user"
        assert client.post(endpoint, json={"interrupt_id": pending["id"], "response": {"answers": []}}).status_code == 409
        submitted = client.post(endpoint, json={"interrupt_id": pending["id"], "response": answers()})
        assert submitted.status_code == 200
        assert client.post(endpoint, json={"interrupt_id": pending["id"], "response": answers()}).status_code == 409
        second = client.get(f"/api/agent/threads/{thread['id']}/pending-interrupt").json()
        assert second["id"] != pending["id"]
        assert second["sequence"] == 2
        response = client.post(endpoint, json={"interrupt_id": second["id"], "response": {
            "answers": [{"question_id": "duration", "text": "5秒"}],
        }})
        assert response.status_code == 200
        assert client.get(f"/api/agent/runs/{run['id']}").json()["status"] == "completed"
        assert client.get(f"/api/agent/threads/{thread['id']}/pending-interrupt").json() is None
        assert client.get(f"/api/agent/threads/{thread['id']}/pending-approval").json() is None
        events = client.get(f"/api/agent/runs/{run['id']}/events").json()
        assert not any('"questions"' in str(event["payload"].get("delta", "")) for event in events)
        messages = client.get(f"/api/agent/threads/{thread['id']}/messages").json()
        stored = [item for item in messages if item["message_type"] == "interrupt"]
        assert all(item["message_metadata"]["interrupt"]["status"] == "resolved" for item in stored)
    assert len(states) == 3
    assert "花果山，傍晚" in states[1]["messages"][-1]["content"]
    assert states[2]["messages"][-1]["content"] == "我的回答：\n想做多长？：5秒"
    assert "角色外观、场景风格" in states[2]["context_text"]
    assert states[2]["context"]["answered_question_titles"][-1] == "想做多长？"


def test_cancelled_run_does_not_publish_late_question_form(monkeypatch):
    class Runtime:
        def respond(self, current):
            with SessionLocal() as session:
                run = session.get(AgentRun, uuid.UUID(current["run_id"]))
                run.status = AgentRunStatus.CANCELLED
                session.commit()
            reply = AgentReply.model_validate(FORM)
            return AgentRuntimeStream(
                chunks=(reply.message,), provider="mock", model="test", provider_job_id=current["run_id"],
                confirmation=reply.confirmation(), structured=True,
            )

    monkeypatch.setattr("app.agent_service.create_agent_runtime", lambda _: Runtime())
    with authenticated_client() as client:
        project = client.post("/api/projects", json={"name": "取消问题测试"}).json()
        thread = client.post(f"/api/projects/{project['id']}/agent/threads", json={"title": "取消"}).json()
        run = client.post(f"/api/agent/threads/{thread['id']}/runs", json={
            "message": "讨论创意", "context": {"project_id": project["id"]},
        }).json()
        assert client.get(f"/api/agent/runs/{run['id']}").json()["status"] == "cancelled"
        assert client.get(f"/api/agent/threads/{thread['id']}/pending-interrupt").json() is None
        messages = client.get(f"/api/agent/threads/{thread['id']}/messages").json()
        assert not any(message["role"] == "assistant" for message in messages)
