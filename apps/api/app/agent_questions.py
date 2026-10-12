"""Validated question forms shared by model output and human-in-the-loop resume."""

import re
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]


class QuestionOption(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: Identifier
    label: Label
    caption: str = Field(default="", max_length=400)


class AgentQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: Identifier
    title: Label
    description: str = Field(default="", max_length=1500)
    kind: Literal["single_select", "multi_select", "text"]
    required: bool = True
    options: list[QuestionOption] = Field(default_factory=list, max_length=8)

    @field_validator("options", mode="before")
    @classmethod
    def normalize_options(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, dict):
            normalized = []
            for idx, (key, val) in enumerate(v.items()):
                if isinstance(val, dict):
                    item = dict(val)
                    item.setdefault("id", str(key or f"opt_{idx + 1}"))
                    item.setdefault(
                        "label",
                        str(val.get("label") or val.get("name") or val.get("title") or val.get("text") or key),
                    )
                    normalized.append(item)
                elif isinstance(val, str):
                    normalized.append({"id": str(key or f"opt_{idx + 1}"), "label": val})
            return normalized
        if isinstance(v, list):
            normalized = []
            for idx, item in enumerate(v):
                if isinstance(item, str):
                    normalized.append({"id": f"opt_{idx + 1}", "label": item})
                elif isinstance(item, dict):
                    d = dict(item)
                    d.setdefault("id", f"opt_{idx + 1}")
                    d.setdefault(
                        "label",
                        str(item.get("label") or item.get("name") or item.get("title") or item.get("text") or f"Option {idx + 1}"),
                    )
                    normalized.append(d)
                else:
                    normalized.append(item)
            return normalized
        return v

    @model_validator(mode="after")
    def valid_options(self) -> Self:
        if self.kind == "text":
            self.options = []
            return self
        if len(self.options) < 2:
            raise ValueError("选择题需要至少两个选项；开放问题请用 text")
        if len({item.id for item in self.options}) != len(self.options):
            raise ValueError("同一问题的选项 ID 不能重复")
        return self


class AgentReply(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: Annotated[str, StringConstraints(min_length=1, max_length=16000)]
    questions: list[AgentQuestion] = Field(max_length=5)
    next_action: Literal["reply", "plan_canvas"] = "reply"

    @model_validator(mode="after")
    def unique_questions(self) -> Self:
        if self.next_action == "plan_canvas" and self.questions:
            raise ValueError("还有待答问题时先提问，不能同时请求画布计划")
        if len({item.id for item in self.questions}) != len(self.questions):
            raise ValueError("问题 ID 不能重复")
        if len({normalized_question_title(item.title) for item in self.questions}) != len(self.questions):
            raise ValueError("同一轮不能重复询问相同问题")
        # This is an output guard, not an action router: a prose claim must
        # never implicitly authorize a plan. Ask the model to repair it using
        # next_action, then let the service create the actual approval record.
        if self.next_action == "reply" and re.search(
            r"(?:已(?:经)?[^。！？\n]{0,24}提交[^。！？\n]{0,8}(?:审批|批准)|"
            r"(?:审批|批准)卡片[^。！？\n]{0,8}已(?:经)?(?:创建|生成|提交)|"
            r"请[^。！？\n]{0,16}(?:查看|点击)[^。！？\n]{0,12}(?:审批|批准)卡片|"
            r"已(?:经)?[^。！？\n]{0,20}(?:应用|修改|创建)[^。！？\n]{0,12}(?:画布|节点)|"
            r"已(?:经)?[^。！？\n]{0,20}(?:启动|开始)[^。！？\n]{0,12}(?:图片|视频|生成)任务|"
            r"(?:画布|节点|图片|视频)生成任务[^。！？\n]{0,12}已(?:经)?(?:创建|启动|提交))",
            self.message,
        ):
            raise ValueError("聊天文字不能声称已提交审批；需要计划时返回 next_action=plan_canvas")
        return self

    def confirmation(self) -> dict[str, object] | None:
        if not self.questions:
            return None
        return {
            "kind": "question_form",
            "decision_key": "llm_questions",
            "title": "确认创作方向",
            "description": "选择或填写你的想法，回答后继续。",
            "message": self.message,
            "questions": [question.model_dump() for question in self.questions],
        }


class QuestionAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question_id: Identifier
    option_ids: list[Identifier] = Field(default_factory=list, max_length=8)
    text: str = Field(default="", max_length=2000)
    skipped: bool = False


class QuestionFormResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[QuestionAnswer] = Field(min_length=1, max_length=5)


def resolve_question_answers(
    questions: list[dict], response: dict,
) -> dict[str, object]:
    form = QuestionFormResponse.model_validate(response)
    definitions = [AgentQuestion.model_validate(question) for question in questions]
    answers = {answer.question_id: answer for answer in form.answers}
    if len(answers) != len(form.answers) or set(answers) != {q.id for q in definitions}:
        raise ValueError("请回答每个问题或明确跳过，不要提交未知或重复的问题")
    resolved = []
    summaries = []
    for question in definitions:
        answer = answers[question.id]
        available = {option.id: option for option in question.options}
        ids = answer.option_ids
        if len(set(ids)) != len(ids) or any(value not in available for value in ids):
            raise ValueError("请选择有效且不重复的选项")
        if question.kind == "single_select" and len(ids) > 1:
            raise ValueError("单选问题只能选择一个选项")
        if answer.skipped and (ids or answer.text):
            raise ValueError("跳过问题时不能同时提交答案")
        if not answer.skipped and not ids and not answer.text:
            raise ValueError("请选择、填写答案或明确跳过该问题")
        if answer.text and ids:
            raise ValueError("自定义回答与选项不能同时提交")
        labels = [available[value].label for value in ids]
        value = "已跳过（未作选择）" if answer.skipped else answer.text or "、".join(labels)
        summaries.append(f"{question.title}：{value}")
        resolved.append({
            **answer.model_dump(), "title": question.title, "labels": labels,
        })
    return {"answers": resolved, "label": "\n".join(summaries)}


def normalized_question_title(title: str) -> str:
    return re.sub(r"[\W_]+", "", title).casefold()
