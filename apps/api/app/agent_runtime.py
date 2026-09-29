import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, Protocol, TypedDict

import httpx
from pydantic import ValidationError

from .agent_questions import AgentReply, normalized_question_title
from .agent_tools import (
    AskUserArguments,
    PlanCanvasArguments,
    ask_user_tool,
    model_capabilities,
    plan_canvas_tool,
    tools_not_supported,
)
from .config import Settings
from .providers.openai_compatible import OpenAICompatibleTextProvider

_CONFIRMATION_START = "[[AGENT_CONFIRMATION]]"
_CONFIRMATION_END = "[[/AGENT_CONFIRMATION]]"
logger = logging.getLogger(__name__)


def _validation_detail(exc: Exception, stage: str) -> str:
    """Diagnostics must not echo model text, references, or credentials."""
    if isinstance(exc, ValidationError):
        fields = []
        for error in exc.errors(include_input=False, include_context=False, include_url=False)[:5]:
            location = re.sub(r"[^a-zA-Z0-9_.-]", "", ".".join(map(str, error["loc"])))[:100]
            fields.append(f"{location or 'response'}:{error['type']}")
        return f"{stage} 字段校验失败（{', '.join(fields)}）"
    return f"{stage} 校验失败（{type(exc).__name__}）"


def _conversation_content(body: dict) -> str:
    content = body["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("模型返回空内容")
    return content.strip()


def parse_confirmation_request(content: str) -> dict[str, Any] | None:
    """Parse the strict confirmation envelope emitted by the LLM.

    The envelope is deliberately opt-in so ordinary questions remain normal
    chat messages. Keeping parsing server-side means the model cannot create a
    real canvas operation; it can only ask the user for a bounded decision.
    """

    start = content.find(_CONFIRMATION_START)
    if start < 0:
        return _parse_natural_confirmation_request(content)
    end = content.find(_CONFIRMATION_END, start + len(_CONFIRMATION_START))
    if end < 0:
        return _parse_natural_confirmation_request(content)
    raw = content[start + len(_CONFIRMATION_START) : end].strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return _parse_natural_confirmation_request(content)
    if not isinstance(payload, dict):
        return _parse_natural_confirmation_request(content)

    kind = str(payload.get("kind") or payload.get("selection_mode") or "single_select")
    if kind in {"single", "radio"}:
        kind = "single_select"
    elif kind in {"multi", "checkbox", "multiple"}:
        kind = "multi_select"
    if kind not in {"single_select", "multi_select"}:
        return _parse_natural_confirmation_request(content)
    raw_options = payload.get("options")
    if not isinstance(raw_options, list) or not 2 <= len(raw_options) <= 8:
        return _parse_natural_confirmation_request(content)

    options: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_options):
        if not isinstance(item, dict):
            return _parse_natural_confirmation_request(content)
        option_id = str(item.get("id") or f"option_{index + 1}").strip()
        label = str(item.get("label") or "").strip()
        if not label or option_id in seen_ids:
            return _parse_natural_confirmation_request(content)
        seen_ids.add(option_id)
        options.append(
            {
                "id": option_id[:80],
                "label": label[:160],
                "caption": str(item.get("caption") or item.get("description") or "").strip()[:300],
                "value": item.get("value", label),
                "tone": str(item.get("tone") or "slate")[:30],
            }
        )
    title = str(payload.get("title") or "请确认下一步").strip()[:160]
    description = str(payload.get("description") or "请选择一个方案后继续。").strip()[:2000]
    message = str(payload.get("message") or payload.get("summary") or description).strip()[:4000]
    decision_key = str(payload.get("decision_key") or "llm_confirmation").strip()[:80]
    if not title or not description:
        return None
    return {
        "title": title,
        "description": description,
        "message": message,
        "kind": kind,
        "decision_key": decision_key if decision_key.startswith("llm_") else "llm_confirmation",
        "options": options,
        "confirm_label": str(payload.get("confirm_label") or "确认选择").strip()[:40],
    }


def _parse_natural_confirmation_request(content: str) -> dict[str, Any] | None:
    """Best-effort fallback for models that ask a choice in ordinary prose."""

    confirmation_terms = (
        "需要向您确认",
        "请您确认",
        "需要确认",
        "请选择",
        "请告诉我",
        "请决定",
        "需要您选择",
        "可多选",
    )
    if not any(term in content for term in confirmation_terms):
        return None

    lines = [line.strip() for line in content.splitlines() if line.strip()]
    question_index = next(
        (index for index, line in enumerate(lines) if "？" in line or "?" in line),
        None,
    )
    if question_index is None:
        question_index = next(
            (index for index, line in enumerate(lines) if any(term in line for term in confirmation_terms)),
            None,
        )
    if question_index is None:
        return None
    line = lines[question_index].lstrip("-*• ")
    if re.match(r"^(?:\d+[.)、]|[A-Za-z][.)])\s*", line):
        return None
    if "：" in line or ":" in line:
        heading, body = re.split(r"[：:]", line, maxsplit=1)
    else:
        heading, body = "创作方向", line
    body = body.strip()

    candidates: list[str] = []
    # Numbered, lettered, or bulleted options immediately following a
    # question are the most reliable natural-language representation.
    for option_line in lines[question_index + 1 : question_index + 8]:
        match = re.match(r"^(?:[-*•]|\d+[.)、]|[A-Za-z][.)])\s*(.+)$", option_line)
        if match:
            value = match.group(1).strip(" ，,。？！?：:")
            if len(value) >= 2:
                candidates.append(value)
        elif candidates:
            break

    # Inline alternatives: “A 还是 B”, “A 或者 B”, and “A、B，还是 C”.
    if len(candidates) < 2:
        alternatives = re.split(r"\s*(?:还是|或者|或)\s*", body, maxsplit=1)
        if len(alternatives) == 2:
            first, second = alternatives
            first_parts = re.split(r"[、,，]\s*", first)
            candidates = [
                part.strip(" ，,。？！?：:")
                for part in first_parts
                if part.strip(" ，,。？！?：:")
            ]
            candidates.append(second.strip(" ，,。？！?：:"))

    # Yes/no questions are also a decision and should not fall back to a
    # free-form chat response.
    if len(candidates) < 2 and (
        body.startswith(("是否", "要不要", "需不需要", "可以吗", "确认吗"))
        or body.endswith(("吗？", "吗?"))
    ):
        candidates = ["是，继续", "否，我要调整"]

    # Remove question prefixes from the first option and discard malformed
    # fragments. A single natural question without alternatives stays prose.
    if candidates:
        candidates[0] = re.sub(
            r"^(?:您是指|你是指|您希望|你希望|希望是|是否|要不要)\s*",
            "",
            candidates[0],
        )
    candidates = [item.rstrip("？?") for item in candidates if len(item) >= 2]
    if len(candidates) < 2:
        return None
    options = [
        {
            "id": f"natural_{index + 1}",
            "label": item[:160],
            "caption": "根据你的选择继续规划",
            "value": item,
            "tone": ("amber", "cyan", "steel", "magenta")[index % 4],
        }
        for index, item in enumerate(candidates[:6])
    ]
    return {
        "title": heading.strip()[:160] or "请确认创作方向",
        "description": "请先确认这一项，Agent 会根据你的选择继续提问和规划。",
        "message": f"请确认“{heading.strip()}”的选择。",
        "kind": "single_select",
        "decision_key": "llm_natural_confirmation",
        "options": options,
        "confirm_label": "确认并继续",
    }


class AgentState(TypedDict):
    """Serializable state contract that can later become a LangGraph State."""

    thread_id: str
    run_id: str
    messages: list[dict[str, str]]
    provider_messages: NotRequired[list[dict[str, Any]]]
    context: dict[str, Any]
    context_text: str
    status: str
    current_step: str
    pending_actions: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    errors: list[dict[str, Any]]


@dataclass(frozen=True)
class AgentRuntimeResult:
    content: str
    provider: str
    model: str
    provider_job_id: str


@dataclass(frozen=True)
class AgentRuntimeStream:
    chunks: Iterable[str]
    provider: str
    model: str
    provider_job_id: str
    confirmation: dict[str, Any] | None = None
    structured: bool = False
    next_action: Literal["reply", "plan_canvas"] = "reply"
    protocol: Literal["text", "json", "tool_calling"] = "text"
    tool_call_id: str | None = None
    fallback_reason: str | None = None


@dataclass(frozen=True)
class AgentPlanResult:
    summary: str
    risk_level: str
    actions: list[dict[str, Any]]
    provider: str
    model: str
    provider_job_id: str


class AgentRuntime(Protocol):
    def respond(self, state: AgentState) -> AgentRuntimeStream: ...

    def invoke(self, state: AgentState) -> AgentRuntimeResult: ...

    def stream(self, state: AgentState) -> AgentRuntimeStream: ...

    def plan(self, state: AgentState) -> AgentPlanResult: ...


class SimpleAgentRuntime:
    """P0 runtime. It preserves the future LangGraph boundary without graph execution yet."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client

    def respond(self, state: AgentState) -> AgentRuntimeStream:
        provider, _, _, model, _ = self._configuration()
        protocol = self.settings.agent_tool_protocol
        # Keep resumed decisions on the established JSON -> plan_canvas path.
        if provider == "mock" or state["context"].get("resume_message_id") or protocol == "json":
            return self._respond_json(state)
        if protocol == "tool_calling" or model_capabilities(self.settings, provider, model)["tool_calling"]:
            return self._respond_tools(state)
        return self._respond_json(state)

    def _respond_tools(self, state: AgentState, *, probe: bool = False) -> AgentRuntimeStream:
        provider, api_key, base_url, model, key_name = self._configuration()
        if not api_key or not model:
            raise RuntimeError(f"请配置 {key_name} 和 Agent 模型")
        payload = self._payload(state, model, stream=False)
        payload["tools"] = [ask_user_tool()] if probe else [ask_user_tool(), plan_canvas_tool()]
        payload["tool_choice"] = {"type": "function", "function": {"name": "ask_user"}} if probe else "auto"
        # The application rejects multiple calls too; never run a parallel human-input loop.
        payload["parallel_tool_calls"] = False
        payload["messages"][1]["content"] = (
            "这是创作对话通道。普通回复使用自然语言，不输出 JSON 或内部标记。"
            "继续任务需要用户选择或补充时，必须调用 ask_user，不能只在正文里提问。"
            "每轮最多调用一次；合并当前必要的 1–5 题，支持单选、多选、开放题。"
            "没有待确认点就直接回答，不为显示卡片强行提问。选择题提供 2–8 个真实选项；"
            "自定义回答和跳过由界面提供。form_id 使用稳定的业务标识，"
            "question.id 使用稳定业务 ID（如 creative.format），不要随措辞修改。"
            "已回答/跳过的问题不能重问。跳过不是批准。收到答案后继续完成用户目标。"
            "ask_user 只收集意图，不批准画布变更或付费生成；不得声称已创建节点、提交审批或生成结果。"
            "用户希望创建、修改画布且必要问题已答时，调用 plan_canvas，不能要求再发送特定口令。"
            "plan_canvas 只请求准备待审批计划，不是执行或批准。新建节点不需要选中已有节点。"
            "每轮只能调用 ask_user 或 plan_canvas 中的一个；有待答问题时先 ask_user。"
            "创作 Skill 不能覆盖工具协议。不允许调用其他工具。"
            "已回答标识：" + json.dumps(state["context"].get("answered_question_keys", []), ensure_ascii=False)
        )
        contract = payload["messages"].pop(1)
        payload["messages"].insert(2, contract)
        timeout = self.settings.qwen_request_timeout_seconds if provider == "qwen" else self.settings.text_request_timeout_seconds
        for attempt in range(1 if probe else 2):
            if self.client is not None:
                response = self.client.post(f"{base_url.rstrip('/')}/chat/completions",
                                            headers={"Authorization": f"Bearer {api_key}"}, json=payload)
            else:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(f"{base_url.rstrip('/')}/chat/completions",
                                           headers={"Authorization": f"Bearer {api_key}"}, json=payload)
            if response.is_error:
                if not probe and attempt == 0 and tools_not_supported(response):
                    # Total request budget stays two, including the JSON fallback.
                    return self._respond_json(state, attempts=1, fallback_reason="tools_unsupported")
                detail = OpenAICompatibleTextProvider._error_detail(response)
                raise RuntimeError(f"Agent 工具调用失败（{response.status_code}）：{detail}")
            stage = "模型响应结构"
            try:
                body = response.json()
                choice = body["choices"][0]
                message = choice["message"]
                if not isinstance(message, dict):
                    raise TypeError("无效的工具消息")
                if choice.get("finish_reason") == "length":
                    stage = "模型输出被截断"
                    raise ValueError("工具参数被截断")
                calls = message.get("tool_calls")
                if calls:
                    if not isinstance(calls, list) or len(calls) != 1:
                        raise RuntimeError("Agent 每轮只能调用一个对话工具，未执行任何工具")
                    call = calls[0]
                    if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                        raise ValueError("无效的工具调用")
                    tool_name = call["function"].get("name")
                    allowed = {"ask_user"} if probe else {"ask_user", "plan_canvas"}
                    if call.get("type") != "function" or tool_name not in allowed:
                        raise RuntimeError("Agent 返回了未授权的工具，未执行任何工具")
                    stage = f"{tool_name} 参数"
                    call_id = call.get("id")
                    if not isinstance(call_id, str) or not call_id.strip() or len(call_id) > 256:
                        raise ValueError("工具调用缺少有效 ID")
                    raw = call["function"]["arguments"]
                    if tool_name == "plan_canvas":
                        plan = PlanCanvasArguments.model_validate_json(raw)
                        return AgentRuntimeStream(
                            chunks=(plan.message,), provider=provider, model=model,
                            provider_job_id=str(response.headers.get("x-request-id") or body.get("id") or state["run_id"]),
                            structured=True, next_action="plan_canvas", protocol="tool_calling",
                        )
                    form = AskUserArguments.model_validate_json(raw)
                    answered = set(state["context"].get("answered_question_keys", []))
                    answered_ids = set(state["context"].get("answered_question_ids", []))
                    answered_titles = {normalized_question_title(str(title))
                                       for title in state["context"].get("answered_question_titles", [])}
                    if any(f"{form.form_id}/{q.id}" in answered or q.id in answered_ids
                           or normalized_question_title(q.title) in answered_titles for q in form.questions):
                        stage = "重复询问已答问题"
                        raise ValueError("重复询问已答问题")
                    return AgentRuntimeStream(
                        chunks=(form.message,), provider=provider, model=model,
                        provider_job_id=str(response.headers.get("x-request-id") or body.get("id") or state["run_id"]),
                        confirmation=form.confirmation(call_id, raw), structured=True,
                        protocol="tool_calling", tool_call_id=call_id,
                    )
                if probe:
                    stage = "缺少 ask_user 调用"
                    raise ValueError("模型没有返回 ask_user 工具调用")
                stage = "普通回复"
                content = _conversation_content(body)
                if content.startswith(("{", "```json")) or "[[AGENT_CONFIRMATION]]" in content:
                    stage = "工具模式返回了协议文本"
                    raise ValueError("工具模式不能输出协议 JSON")
                AgentReply(message=content, questions=[])  # retain the false-approval guard
                return AgentRuntimeStream(
                    chunks=(content,), provider=provider, model=model,
                    provider_job_id=str(response.headers.get("x-request-id") or body.get("id") or state["run_id"]),
                    structured=True, protocol="tool_calling",
                )
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                detail = _validation_detail(exc, stage)
                logger.warning("agent_response_invalid run=%s attempt=%s detail=%s", state["run_id"], attempt + 1, detail)
                if probe or attempt == 1:
                    raise RuntimeError(f"Agent {detail}，已停止本轮，未执行画布操作。请重试。") from None
                if (self.settings.agent_tool_protocol == "auto"
                        and model_capabilities(self.settings, provider, model)["structured_output"]):
                    # Repair any invalid conversation response, not just turns
                    # with mentions. Still only two provider requests total.
                    return self._respond_json(state, attempts=1, fallback_reason="invalid_tool_response",
                                              repair_detail=detail)
                payload["messages"].append({"role": "system", "content":
                    f"上次输出无效：{detail}。请使用 ask_user 的完整合法参数（不得重问已答问题），"
                    "需要准备画布计划则调用 plan_canvas，普通讨论直接自然语言回答。"
                    "不要在正文返回 JSON、内部标记或未完成的操作声明。"})
        raise RuntimeError("Agent 未能返回有效工具调用")

    def test_tool_calling(self) -> AgentRuntimeStream:
        """Opt-in, one-request capability probe; does not persist or execute anything."""
        return self._respond_tools({
            "thread_id": "settings-test", "run_id": "settings-test", "messages": [{
                "role": "user", "content": "请调用 ask_user，询问输出是图片还是视频。这是协议测试，不执行创作。",
            }], "context": {}, "context_text": "模型连接测试", "status": "thinking",
            "current_step": "probe", "pending_actions": [], "tool_calls": [], "errors": [],
        }, probe=True)

    def _respond_json(self, state: AgentState, *, attempts: int = 2,
                      fallback_reason: str | None = None, repair_detail: str | None = None) -> AgentRuntimeStream:
        """Validate a whole model turn before exposing any text or question UI.

        JSON mode plus schema validation replaces keyword-triggered question
        guessing. One repair attempt is permitted; an invalid response fails
        visibly instead of silently presenting questions as ordinary text.
        """
        provider, api_key, base_url, model, key_name = self._configuration()
        if provider == "mock":
            latest = state["messages"][-1]["content"]
            if not state["context"].get("answered_question_titles") and any(
                word in latest for word in ("制作", "大战", "做一条")
            ):
                reply = AgentReply.model_validate({
                    "message": "这是演示模式。先确认两个方向，再继续准备创作方案。",
                    "questions": [
                        {"id": "format", "title": "你想制作什么？", "kind": "single_select", "options": [
                            {"id": "image", "label": "一张图片", "caption": "定格一个精彩瞬间"},
                            {"id": "video", "label": "一段短视频", "caption": "呈现连续的动作和镜头"},
                        ]},
                        {"id": "references", "title": "哪些内容需要保持一致？", "kind": "multi_select", "options": [
                            {"id": "character", "label": "角色外观", "caption": "面容、服装和道具"},
                            {"id": "scene", "label": "场景风格", "caption": "环境、建筑与光线"},
                            {"id": "motion", "label": "动作连续性", "caption": "镜头之间的动作衔接"},
                        ]},
                    ],
                })
                return AgentRuntimeStream(
                    chunks=(reply.message,), provider="mock", model="mock-agent",
                    provider_job_id=state["run_id"], confirmation=reply.confirmation(), structured=True,
                )
            if state["context"].get("answered_question_titles"):
                return AgentRuntimeStream(
                    chunks=("已收到你的回答。演示模式不会调用付费模型；你可以继续细化分镜，或让我创建画布节点。",),
                    provider="mock", model="mock-agent", provider_job_id=state["run_id"], structured=True,
                )
            return self.stream(state)
        if not api_key:
            raise RuntimeError(f"未配置 {key_name}，无法调用 Chat Agent")
        if not model:
            raise RuntimeError("未配置 Agent 文本模型")
        if not model_capabilities(self.settings, provider, model)["structured_output"]:
            raise RuntimeError("当前模型配置声明不支持结构化输出，无法使用 JSON 协议继续")
        payload = self._payload(state, model, stream=False)
        payload["response_format"] = {"type": "json_object"}
        payload["messages"][1]["content"] = (
            "这是创作对话与受控计划路由通道。你只能起草、提问或请求生成计划，不得声称已创建节点或审批。"
            "每一轮都必须返回一个有效 JSON 对象：message 是简短回答，questions 是需要用户回答的问题数组，"
            "next_action 为 reply 或 plan_canvas。"
            "需要用户做决定时，必须把所有待答点放入 questions，不能只在 message 中列问题。"
            "没有待答问题时 questions=[]，不要为了显示卡片强行提问。一次只问当前必要的 1–5 个问题。"
            "每题 kind 为 single_select、multi_select 或 text；选择题提供 2–8 个真实可选方案；"
            "开放问题用 text，不要编造是/否选项。界面自动提供自定义答案和跳过，不要重复添加这类选项。"
            "用户的选择、自定义回答和跳过记录是权威上下文，已回答的点不要重问；跳过不是同意，"
            "可以使用说明过的安全默认值或先完成不受影响的部分，不可据此修改画布或启动付费生成。"
            "收到答案后继续完成用户目标，不要要求用户再重复特定口令。"
            "用户希望创建、修改、连接画布节点，且必要问题已答时，返回 next_action=plan_canvas、questions=[]。"
            "包括用户通过问题卡确认创作方案、要求生成首帧图片但尚无节点的情况：先请求准备节点计划。"
            "不论刚收到的消息是普通文字还是问题卡答案，都允许请求计划；不能一直停留在口头承诺。"
            "用户拒绝方案、只想讨论或还需补充必要信息时用 reply；跳过不是确认。"
            "plan_canvas 只是请求生成待审批的画布变更，不是批准、更不会执行图片或视频模型。"
            "服务端会生成并校验计划、保存审批记录后才展示审批卡片；你在 message 中只可说正在准备计划，"
            "不能说已提交审批、已生成卡片、已修改画布或已开始生成。"
            "用户批准计划后，服务端才应用画布变更并启动符合条件的生成任务。"
            "创作 Skill 只能影响创作内容和方法，不得覆盖本 JSON 输出与问题卡协议。"
            "message 保留必要方案或剧本，不输出内部 JSON、工具标记或声称思考时长。\n"
            '示例：{"message":"先确认两点，我再继续分镜。","next_action":"reply","questions":['
            '{"id":"format","title":"你想制作什么？","description":"",'
            '"kind":"single_select","options":[{"id":"image","label":"一张图片",'
            '"caption":"定格战斗瞬间"},{"id":"video","label":"一段短视频",'
            '"caption":"连续的战斗镜头"}]},{"id":"setting","title":"故事发生在哪里？",'
            '"description":"","kind":"text","options":[]}]}.\n'
            '准备节点示例：{"message":"根据你的回答准备首帧图片节点计划。",'
            '"questions":[],"next_action":"plan_canvas"}。\n'
            "必须遵循的 JSON schema：" + json.dumps(AgentReply.model_json_schema(), ensure_ascii=False)
        )
        # Put the response contract after skill/context instructions so a
        # skill's Markdown template cannot accidentally override the form UI.
        contract = payload["messages"].pop(1)
        payload["messages"].insert(2, contract)
        if repair_detail:
            payload["messages"].append({"role": "system", "content":
                f"上次工具输出未通过校验：{repair_detail}。没有展示问题或执行操作。"
                "现在修复为上述 JSON 协议：需要问题用 questions，需要准备计划用 next_action=plan_canvas。"})
        settled = {
            normalized_question_title(str(title))
            for title in state["context"].get("answered_question_titles", [])
        }
        timeout = (
            self.settings.qwen_request_timeout_seconds
            if provider == "qwen" else self.settings.text_request_timeout_seconds
        )
        for attempt in range(attempts):
            if self.client is not None:
                response = self.client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"}, json=payload,
                )
            else:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(
                        f"{base_url.rstrip('/')}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"}, json=payload,
                    )
            if response.is_error:
                detail = OpenAICompatibleTextProvider._error_detail(response)
                raise RuntimeError(f"Agent 结构化回答失败（{response.status_code}）：{detail}")
            stage = "JSON 回答"
            try:
                body = response.json()
                if body["choices"][0].get("finish_reason") == "length":
                    stage = "模型输出被截断"
                    raise ValueError("模型输出被截断")
                content = _conversation_content(body)
                reply = AgentReply.model_validate_json(content)
                settled_ids = set(state["context"].get("answered_question_ids", []))
                if any(q.id in settled_ids or normalized_question_title(q.title) in settled for q in reply.questions):
                    stage = "重复询问已答问题"
                    raise ValueError("重复询问已回答或跳过的问题；请使用已提交的答案继续")
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                detail = _validation_detail(exc, stage)
                logger.warning("agent_response_invalid run=%s attempt=%s detail=%s", state["run_id"], attempt + 1, detail)
                if attempt == attempts - 1:
                    raise RuntimeError(
                        f"Agent {detail}，自动修复后仍无效，已停止本轮，未执行画布操作。请重试。"
                    ) from None
                payload["messages"].append({
                    "role": "system",
                    "content": f"上次输出校验失败：{detail}。"
                    "请重新返回完整有效 JSON。需要准备画布节点时用 next_action=plan_canvas、questions=[]，"
                    "不要声称已提交审批；若仍需讨论或用户拒绝则用 reply。"
                    "不要重问这些问题：" + json.dumps(sorted(settled), ensure_ascii=False),
                })
                continue
            return AgentRuntimeStream(
                chunks=(reply.message,), provider=provider, model=model,
                provider_job_id=str(response.headers.get("x-request-id") or body.get("id") or state["run_id"]),
                confirmation=reply.confirmation(), structured=True, next_action=reply.next_action,
                protocol="json", fallback_reason=fallback_reason,
            )
        raise RuntimeError("Agent 未能生成有效回答")

    def invoke(self, state: AgentState) -> AgentRuntimeResult:
        provider, api_key, base_url, model, key_name = self._configuration()
        if provider == "mock":
            latest = state["messages"][-1]["content"]
            return AgentRuntimeResult(
                content=f"已读取当前项目与画布上下文。关于“{latest}”，我建议先明确目标，再逐项检查当前镜头和节点。",
                provider="mock",
                model="mock-agent",
                provider_job_id=state["run_id"],
            )

        if not api_key:
            raise RuntimeError(f"未配置 {key_name}，无法调用 Chat Agent")
        if not model:
            raise RuntimeError("未配置 Agent 文本模型")

        payload = self._payload(state, model, stream=False)
        endpoint = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}
        if self.client is not None:
            response = self.client.post(endpoint, headers=headers, json=payload)
        else:
            timeout = (
                self.settings.qwen_request_timeout_seconds
                if provider == "qwen"
                else self.settings.text_request_timeout_seconds
            )
            with httpx.Client(timeout=timeout) as client:
                response = client.post(endpoint, headers=headers, json=payload)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = OpenAICompatibleTextProvider._error_detail(response)
            raise RuntimeError(f"Chat Agent 调用失败（{response.status_code}）：{detail}") from exc

        body = response.json()
        content = OpenAICompatibleTextProvider._content(body)
        request_id = response.headers.get("x-request-id") or body.get("id") or state["run_id"]
        return AgentRuntimeResult(
            content=content,
            provider=provider,
            model=model,
            provider_job_id=str(request_id),
        )

    def stream(self, state: AgentState) -> AgentRuntimeStream:
        provider, api_key, base_url, model, key_name = self._configuration()
        if provider == "mock":
            latest = state["messages"][-1]["content"]
            content = (
                f"已读取当前项目与画布上下文。关于“{latest}”，"
                "我建议先明确目标，再逐项检查当前镜头和节点。"
            )
            return AgentRuntimeStream(
                chunks=(chunk for chunk in (content[:18], content[18:42], content[42:])),
                provider="mock",
                model="mock-agent",
                provider_job_id=state["run_id"],
            )
        if not api_key:
            raise RuntimeError(f"未配置 {key_name}，无法调用 Chat Agent")
        if not model:
            raise RuntimeError("未配置 Agent 文本模型")

        payload = self._payload(state, model, stream=True)
        endpoint = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}

        def iter_chunks() -> Iterable[str]:
            timeout = (
                self.settings.qwen_request_timeout_seconds
                if provider == "qwen"
                else self.settings.text_request_timeout_seconds
            )
            owned_client = self.client is None
            client = self.client or httpx.Client(timeout=timeout)
            try:
                with client.stream("POST", endpoint, headers=headers, json=payload) as response:
                    if response.is_error:
                        response.read()
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        detail = OpenAICompatibleTextProvider._error_detail(response)
                        raise RuntimeError(
                            f"Chat Agent 调用失败（{response.status_code}）：{detail}"
                        ) from exc
                    for line in response.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line.removeprefix("data:").strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            body = json.loads(data)
                            content = body["choices"][0]["delta"].get("content")
                        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                            continue
                        if isinstance(content, str) and content:
                            yield content
            finally:
                if owned_client:
                    client.close()

        return AgentRuntimeStream(
            chunks=iter_chunks(),
            provider=provider,
            model=model,
            provider_job_id=state["run_id"],
        )

    def plan(self, state: AgentState) -> AgentPlanResult:
        provider, api_key, base_url, model, key_name = self._configuration()
        if provider == "mock":
            return self._mock_plan(state)
        if not api_key:
            raise RuntimeError(f"未配置 {key_name}，无法调用 Chat Agent")
        if not model:
            raise RuntimeError("未配置 Agent 文本模型")

        selected = state["context"].get("selected_node_ids", [])
        plan_prompt = """你是 CanvasPatch 计划编译器。只返回一个 JSON 对象，禁止 Markdown。
可用动作严格限定为：
1. {"type":"update_node_config","target":"selected","config_patch":{...},"description":"..."}
2. {"type":"create_node","temp_id":"node_1","node_type":"generator","mode":"text|image|video|null","prompt":"...","description":"..."}
3. {"type":"connect_nodes","source":"selected","target":"node_1","description":"..."}
4. {"type":"bind_asset","target":"selected","asset_id":"资产目录中的 UUID","role":"reference|first_frame|last_frame","description":"..."}
资产绑定规则：只能使用真实资产目录中的 UUID；普通参考图 role=reference；视频首帧/尾帧分别使用 first_frame/last_frame；资产绑定不会启动模型生成。用户显式引用的画布节点不是资产，必须通过 connect_nodes 连接，不能把节点 UUID 当作 asset_id。
返回结构：{"summary":"...","risk_level":"low","actions":[...]}
规则：不得删除节点、不得启动模型生成、不得产生付费调用；更新节点只能使用 target=selected，可更新生成节点的 prompt/model/参数，也可更新文本节点的 text_content 或 prompt 节点的 detail；用户明确要求新增、创建、添加或“生成一个节点”时创建节点；如果用户明确说“新增/新建一个角色或节点，不是修改”，必须使用 create_node，禁止生成 update_node_config；只有用户明确要求连接时才连接。用户使用“继续、确认、执行、满意、同意、可以、好的、1、2、3”等短回复或“我的回答”问题卡答案时，必须结合此前创作方案和原始目标理解需求，并把方案转换为上述受支持动作。用户要求生成首帧图片、视频等但没有选中节点时，可先准备对应类型的 create_node 计划；只创建节点和填写提示词，不调用生成模型。没有选中节点但计划中只有一个 create_node 时，若需要绑定资产，bind_asset 的 target 可以省略或使用该临时节点。节点 prompt 必须包含此前确定的角色、风格、场景等具体内容，不能把“确认，开始生成”当作提示词。拒绝或跳过不是批准，不得据此扩大操作范围。assistant 之前描述的计划只是上下文，不代表动作已经执行；summary 只描述将要修改的内容，不得说已创建节点、已生成图片/视频。不得返回超出动作白名单的镜头、项目或数据库操作。没有足够上下文时 actions 返回空数组。"""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": plan_prompt},
                {
                    "role": "system",
                    "content": (
                        f"当前选中节点：{json.dumps(selected, ensure_ascii=False)}\n"
                        + ("没有选中节点：禁止 update_node_config，禁止 selected 端点。新建内容用 create_node。\n"
                           if not selected else "")
                        + f"真实上下文：\n{state['context_text']}"
                    ),
                },
                *state.get("provider_messages", state["messages"]),
            ],
            "temperature": 0.1,
            "max_tokens": min(self.settings.agent_max_tokens, 1600),
            "stream": False,
        }
        endpoint = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}
        timeout = (
            self.settings.qwen_request_timeout_seconds
            if provider == "qwen"
            else self.settings.text_request_timeout_seconds
        )
        if self.client is not None:
            response = self.client.post(endpoint, headers=headers, json=payload)
        else:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(endpoint, headers=headers, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = OpenAICompatibleTextProvider._error_detail(response)
            raise RuntimeError(f"Agent 计划生成失败（{response.status_code}）：{detail}") from exc

        body = response.json()
        content = OpenAICompatibleTextProvider._content(body)
        plan = self._parse_plan_json(content)
        request_id = response.headers.get("x-request-id") or body.get("id") or state["run_id"]
        return AgentPlanResult(
            summary=str(plan.get("summary") or "准备更新当前画布"),
            risk_level="low",
            actions=plan.get("actions") if isinstance(plan.get("actions"), list) else [],
            provider=provider,
            model=model,
            provider_job_id=str(request_id),
        )

    @staticmethod
    def _parse_plan_json(content: str) -> dict[str, Any]:
        cleaned = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            content.strip(),
            flags=re.IGNORECASE,
        )
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                raise RuntimeError("Agent 没有返回有效的画布计划") from None
            try:
                parsed = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as exc:
                raise RuntimeError("Agent 返回的画布计划不是有效 JSON") from exc
        if not isinstance(parsed, dict):
            raise TypeError("Agent 返回的画布计划格式无效")
        return parsed

    @staticmethod
    def _mock_plan(state: AgentState) -> AgentPlanResult:
        message = state["messages"][-1]["content"].strip()
        actions: list[dict[str, Any]] = []
        create_requested = "节点" in message and any(
            word in message for word in ("新增", "新建", "创建", "添加", "插入", "生成")
        )
        connect_requested = any(word in message for word in ("连接", "连线", "接到", "连到"))
        update_requested = any(word in message for word in ("修改", "改成", "设置", "替换", "优化"))
        asset_requested = any(word in message for word in ("资产", "素材", "参考图", "首帧", "尾帧"))
        if asset_requested and state["context"].get("selected_node_ids"):
            asset_match = re.search(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                state["context_text"],
                flags=re.IGNORECASE,
            )
            if asset_match:
                role = "last_frame" if "尾帧" in message else "first_frame" if "首帧" in message else "reference"
                actions.append({
                    "type": "bind_asset",
                    "target": "selected",
                    "asset_id": asset_match.group(0),
                    "role": role,
                    "description": f"绑定资产为{role}",
                })
        if update_requested and state["context"].get("selected_node_ids"):
            value = message
            for marker in ("改成", "设置为", "替换为", "：", ":"):
                if marker in value:
                    value = value.split(marker, 1)[1].strip().lstrip("：:，, ")
                    break
            actions.append({
                "type": "update_node_config",
                "target": "selected",
                "config_patch": {"prompt": value or message},
                "description": "更新当前选中节点的提示词",
            })
        if create_requested:
            mode = next((kind for word, kind in (
                ("图片", "image"), ("视频", "video"), ("文本", "text")
            ) if word in message), None)
            actions.append({
                "type": "create_node",
                "temp_id": "node_1",
                "node_type": "generator",
                "mode": mode,
                "prompt": "",
                "description": f"新增{mode or '空白'}生成节点",
            })
        if connect_requested and create_requested and state["context"].get("selected_node_ids"):
            actions.append({
                "type": "connect_nodes",
                "source": "selected",
                "target": "node_1",
                "description": "连接当前节点与新节点",
            })
        return AgentPlanResult(
            summary="将按你的要求更新当前画布，应用前需要确认。",
            risk_level="low",
            actions=actions,
            provider="mock",
            model="mock-agent",
            provider_job_id=state["run_id"],
        )

    def _configuration(self) -> tuple[str, str, str, str, str]:
        provider = self.settings.agent_provider.strip() or self.settings.text_provider.strip()
        if provider == "mock":
            return provider, "", "", "mock-agent", ""
        if provider == "qwen":
            return (
                provider,
                self.settings.qwen_api_key.strip(),
                self.settings.qwen_text_base_url,
                (self.settings.agent_model or self.settings.qwen_text_model).strip(),
                "QWEN_API_KEY",
            )
        if provider == "openai_compatible":
            return (
                provider,
                self.settings.text_api_key.strip(),
                self.settings.text_base_url,
                (self.settings.agent_model or self.settings.text_model).strip(),
                "TEXT_API_KEY",
            )
        raise RuntimeError(f"Agent 不支持 Provider：{provider}")

    def _payload(self, state: AgentState, model: str, *, stream: bool) -> dict[str, Any]:
        return {
            "model": model,
            "messages": [
                {"role": "system", "content": self.settings.agent_system_prompt},
                {
                    "role": "system",
                    "content": (
                        "本次调用是只读对话通道。你可以分析、建议和起草内容，但绝不能声称已经创建审批卡片、"
                        "CanvasPatch、节点、连线或生成任务，也不能承诺界面即将自动弹出卡片。"
                        "只有服务端进入受控工具分支时才会真实产生这些界面状态。若用户希望执行操作，"
                        "请让用户明确说出要创建、修改、连接或生成哪个节点。\n"
                        "当你的回答需要用户在两个或更多方案中做决定，必须在回答末尾追加且仅追加以下结构化标记；"
                        "不需要决定时禁止输出该标记。标记内只能是有效 JSON，不要放 Markdown：\n"
                        "[[AGENT_CONFIRMATION]]{\"title\":\"问题标题\",\"description\":\"为什么需要选择\","
                        "\"message\":\"给用户看的简短说明\",\"kind\":\"single_select\","
                        "\"decision_key\":\"llm_confirmation\",\"options\":[{\"id\":\"a\","
                        "\"label\":\"方案 A\",\"caption\":\"说明\",\"value\":\"a\"},"
                        "{\"id\":\"b\",\"label\":\"方案 B\",\"caption\":\"说明\",\"value\":\"b\"}],"
                        "\"confirm_label\":\"确认选择\"}[[/AGENT_CONFIRMATION]]\n"
                        "kind 只能是 single_select 或 multi_select；单选使用 radio，多选使用 checkbox。"
                    ),
                },
                {
                    "role": "system",
                    "content": f"以下是本次只读的真实创作上下文：\n\n{state['context_text']}",
                },
                *state.get("provider_messages", state["messages"]),
            ],
            "temperature": self.settings.agent_temperature,
            "max_tokens": self.settings.agent_max_tokens,
            "stream": stream,
            # Keep resumable tool history independent of provider-specific reasoning traces.
            **({"enable_thinking": False} if self.settings.agent_provider == "qwen" else {}),
        }


def create_agent_runtime(
    settings: Settings,
    client: httpx.Client | None = None,
) -> AgentRuntime:
    return SimpleAgentRuntime(settings, client)
