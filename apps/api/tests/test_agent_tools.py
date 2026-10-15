import copy
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest
from conftest import admin_client, authenticated_client
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from test_agent_questions import FIRST_FRAME_ACTION, FORM, answers, start_question_run, state

from app.agent_canvas import CanvasPatchError
from app.agent_runtime import SimpleAgentRuntime
from app.agent_service import build_provider_messages, resolve_agent_interrupt
from app.agent_tools import AskUserArguments, ask_user_tool, model_capabilities, plan_canvas_tool
from app.config import Settings
from app.database import Base, SessionLocal
from app.db_models import (
    AgentInterrupt,
    AgentMessage,
    AgentRun,
    AgentRunStatus,
    AgentThread,
    Project,
)

ARGUMENTS = {**FORM, "schema_version": "1.0", "form_id": "creative_direction", "title": "确认方向"}


def configuration(**values):
    return Settings(**{
        "agent_provider": "qwen", "qwen_api_key": "test-key", "agent_model": "qwen-test",
        "_env_file": None, **values,
    })


def tool_response(arguments=None, *, name="ask_user", call_id="call_questions", count=1):
    return {"id": "provider-request", "choices": [{"finish_reason": "tool_calls", "message": {
        "content": None,
        "tool_calls": [{"id": call_id, "type": "function", "function": {
            "name": name, "arguments": json.dumps(ARGUMENTS if arguments is None else arguments),
        }}] * count,
    }}]}


def text_response(content):
    return {"choices": [{"message": {"content": content}}]}


def test_contract_reuses_questions_and_returns_only_user_facing_text():
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=tool_response())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = SimpleAgentRuntime(configuration(), client).respond(state())
    assert captured[0]["tools"] == [ask_user_tool(), plan_canvas_tool()]
    assert "response_format" not in captured[0]
    assert captured[0]["tool_choice"] == "auto"
    assert captured[0]["parallel_tool_calls"] is False
    assert captured[0]["enable_thinking"] is False
    assert result.protocol == "tool_calling" and result.tool_call_id == "call_questions"
    assert list(result.chunks) == [FORM["message"]]
    assert result.confirmation["tool_arguments"] == json.dumps(ARGUMENTS)
    assert len(result.confirmation["questions"]) == 3


@pytest.mark.parametrize("patch", [
    {"schema_version": "2.0"}, {"questions": []}, {"form_id": ""},
    {"questions": [FORM["questions"][0]] * 2},
    {"questions": [{**FORM["questions"][0], "kind": "unknown"}]},
    {"questions": [{**FORM["questions"][0], "options": []}]},
    {"questions": [{**FORM["questions"][0], "options": [{"id": "a", "label": "a"}] * 2}]},
    {"unknown": "forbidden"},
])
def test_tool_contract_rejects_invalid_input(patch):
    with pytest.raises(ValidationError):
        AskUserArguments.model_validate({**ARGUMENTS, **patch})


@pytest.mark.parametrize("name,count", [("delete_canvas", 1), ("ask_user", 2)])
def test_unauthorized_or_multiple_calls_are_rejected_without_execution(name, count):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=tool_response(name=name, count=count))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(RuntimeError):
        SimpleAgentRuntime(configuration(), client).respond(state())
    assert len(calls) == 1


@pytest.mark.parametrize("repair", [True, False])
def test_invalid_arguments_repair_is_bounded(repair):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=tool_response(None if repair and len(calls) == 2 else {"questions": []}))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        if repair:
            assert SimpleAgentRuntime(configuration(agent_tool_protocol="tool_calling"), client).respond(state()).confirmation
        else:
            with pytest.raises(RuntimeError, match="已停止本轮"):
                SimpleAgentRuntime(configuration(agent_tool_protocol="tool_calling"), client).respond(state())
    assert len(calls) == 2


def test_stable_question_ids_reject_reworded_question():
    current = state()
    current["context"]["answered_question_keys"] = ["creative_direction/format"]
    reworded = copy.deepcopy(ARGUMENTS)
    reworded["questions"][0]["title"] = "换个说法问相同问题"
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=tool_response(reworded)))) as client,
        pytest.raises(RuntimeError, match="已停止本轮"),
    ):
        SimpleAgentRuntime(configuration(), client).respond(current)


@pytest.mark.parametrize("invalid", [
    tool_response({"questions": []}),
    text_response('```json\n{"next_action":"plan_canvas"}\n```'),
    text_response("计划已提交审批，请在画布中查看审批卡片。"),
    {"choices": [{"finish_reason": "length", "message": {"content": "truncated"}}]},
    text_response(None),
    {"choices": []},
])
@pytest.mark.parametrize("next_step", ["questions", "plan"])
def test_auto_repairs_invalid_responses_without_mentions(invalid, next_step):
    requests = []
    repaired = FORM if next_step == "questions" else {
        "message": "准备节点计划。", "questions": [], "next_action": "plan_canvas",
    }

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            assert "tools" in payload
            return httpx.Response(200, json=invalid)
        assert "tools" not in payload
        assert payload["response_format"] == {"type": "json_object"}
        assert "校验" in payload["messages"][-1]["content"]
        return httpx.Response(200, json=text_response(json.dumps(repaired)))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = SimpleAgentRuntime(configuration(), client).respond(state())
    assert len(requests) == 2
    assert result.fallback_reason == "invalid_tool_response"
    assert result.protocol == "json"
    assert bool(result.confirmation) is (next_step == "questions")
    assert result.next_action == ("plan_canvas" if next_step == "plan" else "reply")


def test_auto_repair_remains_bounded_and_diagnostics_do_not_echo_arguments(caplog):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=tool_response({"questions": "private-reference-content"})
                              if len(requests) == 1 else text_response("not-json"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(RuntimeError) as error:
        SimpleAgentRuntime(configuration(), client).respond(state())
    assert len(requests) == 2
    assert "已停止本轮" in str(error.value)
    assert "private-reference-content" not in caplog.text + str(error.value)
    assert "questions" in caplog.text


def test_tools_can_request_plan_without_fabricating_an_approval():
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=tool_response(
        {"message": "根据你的回答准备首帧计划。"}, name="plan_canvas",
    )))) as client:
        result = SimpleAgentRuntime(configuration(), client).respond(state())
    assert result.next_action == "plan_canvas"
    assert result.confirmation is None


@pytest.mark.parametrize("repaired", [True, False])
def test_tool_plan_and_invalid_unselected_update_reach_real_approval_only_after_validation(monkeypatch, repaired):
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(200, json=tool_response({"message": "准备首帧。"}, name="plan_canvas"))
        if len(requests) == 3:
            assert any("没有执行任何操作" in m.get("content", "") for m in payload["messages"])
        actions = [FIRST_FRAME_ACTION] if repaired and len(requests) == 3 else [{
            "type": "update_node_config", "target": "selected", "config_patch": {"prompt": "wrong target"},
        }]
        return httpx.Response(200, json=text_response(json.dumps({"summary": "准备首帧", "actions": actions})))

    with httpx.Client(transport=httpx.MockTransport(handler)) as llm, authenticated_client() as client:
        monkeypatch.setattr("app.agent_service.create_agent_runtime", lambda _: SimpleAgentRuntime(configuration(), llm))
        shot, before, thread, run = start_question_run(client)
        assert len(requests) == 3  # one routing call, at most two planning calls
        status = client.get(f"/api/agent/runs/{run['id']}").json()["status"]
        assert status == ("waiting_approval" if repaired else "failed")
        approval = client.get(f"/api/agent/threads/{thread['id']}/pending-approval").json()
        if repaired:
            assert approval["status"] == "pending"
            assert approval["patch"]["operations"][0]["type"] == "create_node"
        else:
            assert approval is None
        assert client.get(f"/api/shots/{shot['id']}/workflow").json()["nodes"] == before["nodes"]
        assert client.get(f"/api/shots/{shot['id']}/generations").json() == []


def test_followup_after_answers_keeps_context_and_can_plan_via_json_repair(monkeypatch):
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(200, json=tool_response())
        if len(requests) == 2:
            return httpx.Response(200, json=text_response(json.dumps({
                "message": "方案已整理，可以继续准备首帧。", "questions": [],
            })))
        if len(requests) == 3:
            assert "tools" in payload
            assert "creative_direction/format" in payload["messages"][2]["content"]
            return httpx.Response(200, json=tool_response({"questions": []}))
        if len(requests) == 4:
            assert "tools" not in payload
            assert any("花果山，傍晚" in str(m.get("content", "")) for m in payload["messages"])
            return httpx.Response(200, json=text_response(json.dumps({
                "message": "准备首帧计划。", "questions": [], "next_action": "plan_canvas",
            })))
        return httpx.Response(200, json=text_response(json.dumps({"summary": "首帧计划", "actions": [FIRST_FRAME_ACTION]})))

    with httpx.Client(transport=httpx.MockTransport(handler)) as llm, authenticated_client() as client:
        monkeypatch.setattr("app.agent_service.create_agent_runtime", lambda _: SimpleAgentRuntime(configuration(), llm))
        shot, before, thread, run = start_question_run(client)
        url = f"/api/agent/threads/{thread['id']}"
        pending = client.get(f"{url}/pending-interrupt").json()
        assert client.post(f"/api/agent/runs/{run['id']}/resume", json={
            "interrupt_id": pending["id"], "response": answers(),
        }).status_code == 200
        followup = client.post(f"{url}/runs", json={"message": "以选中", "context": {
            "project_id": thread["project_id"], "shot_id": shot["id"], "selected_node_ids": [],
        }})
        assert followup.status_code == 201, followup.text
        assert len(requests) == 5
        assert client.get(f"{url}/pending-approval").json()["status"] == "pending"
        assert client.get(f"{url}/pending-interrupt").json() is None
        assert client.get(f"/api/shots/{shot['id']}/workflow").json()["nodes"] == before["nodes"]
        assert client.get(f"/api/shots/{shot['id']}/generations").json() == []
        events = client.get(f"/api/agent/runs/{followup.json()['id']}/events").json()
        assert any(e["event_type"] == "protocol.fallback" for e in events)


@pytest.mark.parametrize("fallback_valid", [True, False])
def test_explicit_unsupported_tools_fallback_total_budget_is_two(fallback_valid):
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(400, json={"error": {"message": "tools is not supported by this model"}})
        assert "tools" not in payload and payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json=text_response(json.dumps(FORM) if fallback_valid else "invalid"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        if fallback_valid:
            result = SimpleAgentRuntime(configuration(), client).respond(state())
            assert result.protocol == "json" and result.fallback_reason == "tools_unsupported"
        else:
            with pytest.raises(RuntimeError):
                SimpleAgentRuntime(configuration(), client).respond(state())
    assert len(requests) == 2


@pytest.mark.parametrize("status,message", [(401, "unauthorized tools"), (429, "rate limit"),
    (503, "tools unavailable"), (400, "invalid tools schema"), (400, "unsupported model"),
    (400, "tools schema has unsupported keywords")])
def test_other_provider_errors_never_downgrade(status, message):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": message}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(RuntimeError):
        SimpleAgentRuntime(configuration(), client).respond(state())
    assert len(calls) == 1


def test_no_call_is_plain_reply_not_keyword_form():
    content = "问题是：请告诉我这个画面是否自然？"
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=text_response(content)))) as client:
        result = SimpleAgentRuntime(configuration(), client).respond(state())
    assert list(result.chunks) == [content]
    assert result.structured and result.confirmation is None


@pytest.mark.parametrize("protocol,provider,override,expected", [
    ("auto", "qwen", {}, True), ("json", "qwen", {}, False),
    ("auto", "openai_compatible", {}, False),
    ("tool_calling", "openai_compatible", {}, True),
    ("auto", "qwen", {"qwen:qwen-test": {"tool_calling": False}}, False),
    ("auto", "openai_compatible", {"openai_compatible:qwen-test": {"tool_calling": True}}, True),
    ("tool_calling", "qwen", {"qwen:qwen-test": {"tool_calling": False}}, True),
])
def test_protocol_selection_and_capabilities(protocol, provider, override, expected):
    def handler(request):
        payload = json.loads(request.content)
        assert ("tools" in payload) is expected
        return httpx.Response(200, json=tool_response() if expected else text_response(json.dumps(FORM)))

    cfg = configuration(agent_tool_protocol=protocol, agent_provider=provider,
                        text_api_key="test-key", agent_model_capabilities=override)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        SimpleAgentRuntime(cfg, client).respond(state())
    assert model_capabilities(cfg, provider, "qwen-test")["structured_output"] is True


@pytest.mark.parametrize("approve", [True, False])
def test_tool_interrupt_resume_reconstructs_pair_and_preserves_canvas_approval(monkeypatch, approve):
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(200, json=tool_response())
        transcript = payload["messages"]
        # Even with a one-message history limit the complete pair is present.
        assert transcript[-2]["role"] == "assistant"
        assert transcript[-2]["tool_calls"][0]["id"] == "call_questions"
        assert transcript[-1]["role"] == "tool" and transcript[-1]["tool_call_id"] == "call_questions"
        assert json.loads(transcript[-1]["content"])["answers"][0]["labels"] == ["一段短视频"]
        assert not any(m["role"] == "user" and "我的回答" in m["content"] for m in transcript)
        assert "tools" not in payload
        content = {"message": "准备节点计划。", "questions": [], "next_action": "plan_canvas"} if len(requests) == 2 else {
            "summary": "创建首帧节点", "actions": [FIRST_FRAME_ACTION],
        }
        return httpx.Response(200, json=text_response(json.dumps(content)))

    with httpx.Client(transport=httpx.MockTransport(handler)) as llm, authenticated_client() as client:
        monkeypatch.setattr("app.agent_service.create_agent_runtime", lambda _: SimpleAgentRuntime(configuration(), llm))
        shot, before, thread, run = start_question_run(client)
        url = f"/api/agent/threads/{thread['id']}"
        pending = client.get(f"{url}/pending-interrupt").json()
        assert pending["payload"]["protocol"] == "tool_calling"
        assert pending["payload"]["form_id"] == "creative_direction"
        assert client.get(f"{url}/pending-interrupt").json()["id"] == pending["id"]  # refresh
        initial_messages = client.get(f"{url}/messages").json()
        assert all("tool_calls" not in m["content"] for m in initial_messages)
        assert initial_messages[-1]["content"] == FORM["message"]
        monkeypatch.setattr("app.agent_service.get_settings", lambda: configuration(agent_history_messages=1))
        response = client.post(f"/api/agent/runs/{run['id']}/resume", json={
            "interrupt_id": pending["id"], "response": answers(),
        })
        assert response.status_code == 200, response.text
        assert len(requests) == 3
        assert client.get(f"/api/shots/{shot['id']}/workflow").json()["nodes"] == before["nodes"]
        approval = client.get(f"{url}/pending-approval").json()
        assert approval["status"] == "pending"
        assert client.post(f"/api/agent/runs/{run['id']}/resume", json={
            "interrupt_id": pending["id"], "response": answers(),
        }).status_code == 409
        assert len(requests) == 3
        resolved_messages = client.get(f"{url}/messages").json()
        question_message = next(m for m in resolved_messages if m["message_type"] == "interrupt")
        assert question_message["message_metadata"]["protocol"] == "tool_calling"
        assert question_message["message_metadata"]["tool_call_id"] == "call_questions"
        # Builder also works on complete history without duplicating question prose.
        with SessionLocal() as session:
            messages = list(session.scalars(select(AgentMessage).where(
                AgentMessage.thread_id == uuid.UUID(thread["id"]),
            ).order_by(AgentMessage.created_at)))
            transcript = build_provider_messages(session, messages)
            assert len([m for m in transcript if m["role"] == "tool"]) == 1
            assert not any(m.get("content") == FORM["message"] for m in transcript)
            interrupt = session.get(AgentInterrupt, uuid.UUID(pending["id"]))
            assert interrupt.response["answers"][0]["question_id"] == "format"
        result = client.post(f"/api/agent/runs/{run['id']}/approval", json={
            "decision": "approve" if approve else "reject",
        })
        assert result.status_code == 200
        after = client.get(f"/api/shots/{shot['id']}/workflow").json()
        assert (len(after["nodes"]) > len(before["nodes"])) is approve
        generations = client.get(f"/api/shots/{shot['id']}/generations").json()
        assert (len(generations) == 1) is approve
        if approve:
            assert generations[0]["kind"] == "image"
            assert generations[0]["node_id"] in {node["id"] for node in after["nodes"]}


def test_cancelled_inflight_call_never_creates_interrupt(monkeypatch):
    def handler(request):
        with SessionLocal() as session:
            run = session.scalar(select(AgentRun).where(AgentRun.status == AgentRunStatus.THINKING))
            run.status = AgentRunStatus.CANCELLED
            session.commit()
        return httpx.Response(200, json=tool_response())

    with httpx.Client(transport=httpx.MockTransport(handler)) as llm, authenticated_client() as client:
        monkeypatch.setattr("app.agent_service.create_agent_runtime", lambda _: SimpleAgentRuntime(configuration(), llm))
        _, _, thread, run = start_question_run(client)
        assert client.get(f"/api/agent/runs/{run['id']}").json()["status"] == "cancelled"
        assert client.get(f"/api/agent/threads/{thread['id']}/pending-interrupt").json() is None


def test_capability_probe_is_one_request_without_persistence(monkeypatch):
    calls = []

    def probe(self):
        def handler(request):
            payload = json.loads(request.content)
            calls.append(payload)
            assert payload["tool_choice"]["function"]["name"] == "ask_user"
            return httpx.Response(200, json=tool_response())
        with httpx.Client(transport=httpx.MockTransport(handler)) as llm:
            return SimpleAgentRuntime(self.settings, llm)._respond_tools(state(), probe=True)

    monkeypatch.setattr(SimpleAgentRuntime, "test_tool_calling", probe)
    with admin_client() as client:
        before = client.get("/api/projects").json()
        result = client.post("/api/settings/test", json={
            "provider": "qwen", "kind": "text", "model": "test-model",
            "api_key": "test-key", "test_tool_calling": True,
        })
        assert result.status_code == 200 and result.json()["tool_calling"] is True
        assert client.get("/api/projects").json() == before
    assert len(calls) == 1


def test_concurrent_tabs_can_claim_tool_interrupt_only_once(tmp_path):
    # Independent database connections, not the in-memory test StaticPool.
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent-resume.db'}",
                           connect_args={"check_same_thread": False, "timeout": 10})
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            project = Project(name="Concurrency test")
            thread = AgentThread(project=project)
            run = AgentRun(thread=thread, status=AgentRunStatus.WAITING_USER)
            interrupt = AgentInterrupt(run=run, sequence=1, kind="question_form",
                decision_key="llm_questions", title="确认方向",
                payload={"presentation": "question_form", **AskUserArguments.model_validate(ARGUMENTS).confirmation(
                    "call_questions", json.dumps(ARGUMENTS))})
            session.add(interrupt)
            session.commit()
            run_id, interrupt_id = run.id, interrupt.id
        ready = Barrier(2)

        def submit():
            with Session(engine) as session:
                run = session.get(AgentRun, run_id)
                pending = session.get(AgentInterrupt, interrupt_id)
                assert pending.status.value == "pending"
                # Both tabs have read the pending state before either submits.
                ready.wait(timeout=10)
                try:
                    resolve_agent_interrupt(session, run, interrupt_id, answers())
                    return "accepted"
                except CanvasPatchError:
                    session.rollback()
                    return "already_handled"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        assert sorted(results) == ["accepted", "already_handled"]
        with Session(engine) as session:
            decisions = list(session.scalars(select(AgentMessage).where(AgentMessage.message_type == "decision")))
            assert len(decisions) == 1
            assert session.get(AgentRun, run_id).context_snapshot["resume_message_id"] == str(decisions[0].id)
    finally:
        engine.dispose()
