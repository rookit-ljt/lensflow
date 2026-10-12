"""Versioned conversation tools; no direct canvas mutation or generation."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agent_questions import AgentQuestion, AgentReply, Identifier, Label
from .config import Settings


class AskUserArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    form_id: Identifier
    message: str = Field(min_length=1, max_length=16000)
    title: Label
    description: str = Field(default="", max_length=1500)
    questions: list[AgentQuestion] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_questions(self):
        # Reuse uniqueness/option checks and the false-approval output guard.
        AgentReply(message=self.message, questions=self.questions)
        return self

    def confirmation(self, call_id: str, raw_arguments: str) -> dict:
        return {
            **self.model_dump(), "kind": "question_form", "decision_key": "llm_questions",
            "protocol": "tool_calling", "tool_name": "ask_user", "tool_call_id": call_id,
            "tool_arguments": raw_arguments,
        }


def ask_user_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "继续创作前需要用户选择或补充信息时，展示问题卡并暂停 Agent。"
            "不修改画布、不启动生成。一次合并当前必要的 1–5 题。",
            "parameters": AskUserArguments.model_json_schema(),
        },
    }


class PlanCanvasArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=16000)


def plan_canvas_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "plan_canvas",
            "description": "用户希望创建或修改画布，必要问题已回答时请求准备计划。"
            "仅进入服务端计划校验和审批流程，不代表批准，不修改节点、不启动生成。"
            "新建节点不要求已有选中节点。与 ask_user 互斥，每轮最多调用一个工具。",
            "parameters": PlanCanvasArguments.model_json_schema(),
        },
    }


def model_capabilities(settings: Settings, provider: str, model: str) -> dict[str, bool]:
    # Unknown OpenAI-compatible gateways are not assumed to implement tools.
    defaults = {"tool_calling": provider == "qwen", "structured_output": True}
    override = settings.agent_model_capabilities.get(f"{provider}:{model}")
    if override is not None:
        defaults.update(override.model_dump(exclude_none=True))
    return defaults


def tools_not_supported(response) -> bool:
    """Only explicit capability errors permit downgrade, never auth/rate/server errors."""
    if response.status_code not in {400, 422}:
        return False
    text = response.text.casefold()
    # Rejected parameter schemas are not evidence that the model lacks tools.
    if "schema" in text or ".function.parameters" in text:
        return False
    return any(term in text for term in ("tools", "tool_choice", "tool calling", "function calling")) and any(
        term in text for term in ("not support", "unsupported", "not allowed", "unknown parameter",
                                  "unrecognized", "不支持")
    )


def tool_exchange(payload: dict, response: dict) -> list[dict]:
    """Rebuild an atomic call/result pair from trusted, persisted interrupt data."""
    call_id = payload["tool_call_id"]
    return [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": call_id, "type": "function", "function": {
                "name": "ask_user", "arguments": payload["tool_arguments"],
            },
        }]},
        {"role": "tool", "tool_call_id": call_id, "content": json.dumps({
            "schema_version": payload["schema_version"], "form_id": payload["form_id"],
            "answers": response["answers"],
        }, ensure_ascii=False)},
    ]
