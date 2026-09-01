import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict

import httpx

from .config import Settings
from .providers.openai_compatible import OpenAICompatibleTextProvider


class AgentState(TypedDict):
    """Serializable state contract that can later become a LangGraph State."""

    thread_id: str
    run_id: str
    messages: list[dict[str, str]]
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


@dataclass(frozen=True)
class AgentPlanResult:
    summary: str
    risk_level: str
    actions: list[dict[str, Any]]
    provider: str
    model: str
    provider_job_id: str


class AgentRuntime(Protocol):
    def invoke(self, state: AgentState) -> AgentRuntimeResult: ...

    def stream(self, state: AgentState) -> AgentRuntimeStream: ...

    def plan(self, state: AgentState) -> AgentPlanResult: ...


class SimpleAgentRuntime:
    """P0 runtime. It preserves the future LangGraph boundary without graph execution yet."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client

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
资产绑定规则：只能使用真实资产目录中的 UUID；普通参考图 role=reference；视频首帧/尾帧分别使用 first_frame/last_frame；资产绑定不会启动模型生成。
返回结构：{"summary":"...","risk_level":"low","actions":[...]}
规则：不得删除节点、不得启动模型生成、不得产生付费调用；更新节点只能使用 target=selected，可更新生成节点的 prompt/model/参数，也可更新文本节点的 text_content 或 prompt 节点的 detail；用户明确要求新增、创建、添加或“生成一个节点”时创建节点；只有用户明确要求连接时才连接。用户使用“继续、确认、执行、1、2、3”等短回复时，必须结合紧邻的上一条 assistant 消息理解其确认的画布方案，并把方案转换为上述受支持动作。assistant 之前描述的计划只是上下文，不代表动作已经执行；不得返回超出动作白名单的镜头、项目或数据库操作。没有足够上下文时 actions 返回空数组。"""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": plan_prompt},
                {
                    "role": "system",
                    "content": (
                        f"当前选中节点：{json.dumps(selected, ensure_ascii=False)}\n"
                        f"真实上下文：\n{state['context_text']}"
                    ),
                },
                *state["messages"],
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
                        "请让用户明确说出要创建、修改、连接或生成哪个节点。"
                    ),
                },
                {
                    "role": "system",
                    "content": f"以下是本次只读的真实创作上下文：\n\n{state['context_text']}",
                },
                *state["messages"],
            ],
            "temperature": self.settings.agent_temperature,
            "max_tokens": self.settings.agent_max_tokens,
            "stream": stream,
        }


def create_agent_runtime(
    settings: Settings,
    client: httpx.Client | None = None,
) -> AgentRuntime:
    return SimpleAgentRuntime(settings, client)
