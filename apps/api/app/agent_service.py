import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agent_canvas import (
    CanvasPatchError,
    apply_canvas_patch,
    compile_canvas_patch,
    is_canvas_operation_request,
)
from .agent_context import build_agent_context
from .agent_runtime import AgentState, create_agent_runtime
from .config import get_settings
from .database import SessionLocal
from .db_models import (
    AgentApproval,
    AgentApprovalStatus,
    AgentEvent,
    AgentInterrupt,
    AgentInterruptStatus,
    AgentMessage,
    AgentMessageRole,
    AgentRun,
    AgentRunStatus,
    AgentThread,
    Generation,
    GenerationStatus,
    Shot,
)
from .schemas import AgentApprovalRead, AgentInterruptRead
from .tasks import generate_shot
from .workflows import load_workflow


def append_agent_event(
    session: Session,
    run: AgentRun,
    event_type: str,
    payload: dict[str, object] | None = None,
) -> AgentEvent:
    last_sequence = session.scalar(
        select(func.max(AgentEvent.sequence)).where(AgentEvent.run_id == run.id)
    )
    event = AgentEvent(
        run_id=run.id,
        sequence=int(last_sequence or 0) + 1,
        event_type=event_type,
        payload=payload or {},
    )
    session.add(event)
    return event


def requires_visual_style_choice(message: str) -> bool:
    normalized = message.strip().lower()
    asset_terms = ("角色及场景", "角色和场景", "角色设计", "场景设计", "美术资产")
    action_terms = ("生成", "创建", "设计", "制作")
    return any(term in normalized for term in asset_terms) and any(
        term in normalized for term in action_terms
    )


def requires_node_generation_confirmation(
    message: str,
    selected_node_ids: list[str],
) -> bool:
    """Recognize explicit execution requests without confusing them with node creation."""

    if not selected_node_ids:
        return False
    normalized = "".join(message.strip().lower().split())
    explicit_phrases = (
        "生成当前节点",
        "运行当前节点",
        "执行当前节点",
        "生成选中节点",
        "运行选中节点",
        "执行选中节点",
        "生成这个节点",
        "运行这个节点",
        "执行这个节点",
    )
    return any(phrase in normalized for phrase in explicit_phrases) or normalized in {
        "开始生成",
        "开始运行",
        "执行生成",
    }


def create_node_generation_interrupt(
    session: Session,
    run: AgentRun,
    thread: AgentThread,
) -> AgentInterrupt:
    """Pause before a potentially billable model invocation."""

    snapshot = run.context_snapshot
    shot_id = snapshot.get("shot_id")
    selected_node_ids = [str(value) for value in snapshot.get("selected_node_ids", [])]
    if not shot_id or not selected_node_ids:
        raise CanvasPatchError("生成节点前，请先在当前镜头中选中一个生成节点")
    workflow = load_workflow(session, uuid.UUID(str(shot_id)))
    if workflow is None:
        raise CanvasPatchError("当前镜头还没有可执行的画布")
    selected_id = selected_node_ids[0]
    node = next((item for item in workflow.nodes if str(item.id) == selected_id), None)
    if node is None or node.type != "generator":
        raise CanvasPatchError("当前选中的不是可执行生成节点")
    config = node.config if isinstance(node.config, dict) else {}
    mode = str(config.get("mode") or "")
    if mode not in {"text", "image", "video"}:
        raise CanvasPatchError("当前节点尚未配置文本、图片或视频生成类型")
    prompt = str(config.get("prompt") or "").strip()
    shot = session.get(Shot, workflow.shot_id)
    prompt_preview = (prompt or (shot.visual_prompt if shot else "")).strip()
    if not prompt_preview:
        raise CanvasPatchError("当前节点还没有可用于生成的 Prompt")

    provider = str(config.get("provider") or "自动选择")
    model = str(config.get("model") or "服务端默认模型")
    tool_message = AgentMessage(
        thread_id=thread.id,
        run_id=run.id,
        role=AgentMessageRole.TOOL,
        content=f"已读取当前{mode}节点配置：{provider} · {model}",
        message_type="tool_result",
        message_metadata={
            "tool_name": "read_selected_node",
            "status": "succeeded",
            "node_id": selected_id,
            "mode": mode,
        },
    )
    session.add(tool_message)
    session.flush()
    append_agent_event(
        session,
        run,
        "tool.started",
        {"tool_name": "read_selected_node", "node_id": selected_id},
    )
    _append_completed_message_event(session, run, tool_message)
    append_agent_event(
        session,
        run,
        "tool.completed",
        {"tool_name": "read_selected_node", "node_id": selected_id, "status": "succeeded"},
    )

    last_sequence = session.scalar(
        select(func.max(AgentInterrupt.sequence)).where(AgentInterrupt.run_id == run.id)
    )
    interrupt = AgentInterrupt(
        run_id=run.id,
        sequence=int(last_sequence or 0) + 1,
        kind="single_select",
        decision_key="generate_selected_node",
        title="确认启动模型生成",
        description="Agent 已读取当前节点配置。启动后可能产生模型调用费用，请确认是否继续。",
        payload={
            "presentation": "generation_confirmation",
            "node_id": selected_id,
            "mode": mode,
            "provider": provider,
            "model": model,
            "prompt_preview": prompt_preview[:280],
            "options": [
                {
                    "id": "confirm",
                    "label": "开始生成",
                    "caption": f"使用 {provider} · {model}",
                    "tone": "cyan",
                },
                {
                    "id": "cancel",
                    "label": "暂不生成",
                    "caption": "保留当前节点配置，不创建任务",
                    "tone": "slate",
                },
            ],
            "confirm_label": "确认选择",
        },
    )
    session.add(interrupt)
    session.flush()
    interrupt_payload = AgentInterruptRead.model_validate(interrupt).model_dump(mode="json")
    message = AgentMessage(
        thread_id=thread.id,
        run_id=run.id,
        role=AgentMessageRole.ASSISTANT,
        content="节点已准备就绪。确认后我会创建生成任务，并把进度交还给画布跟踪。",
        message_type="interrupt",
        message_metadata={"interrupt": interrupt_payload},
    )
    session.add(message)
    session.flush()
    run.status = AgentRunStatus.WAITING_USER
    run.current_step = "wait_for_generation_confirmation"
    _append_completed_message_event(session, run, message)
    append_agent_event(session, run, "interrupt.created", {"interrupt": interrupt_payload})
    session.commit()
    return interrupt


def create_visual_style_interrupt(
    session: Session,
    run: AgentRun,
    thread: AgentThread,
) -> AgentInterrupt:
    options = [
        {
            "id": "cinematic",
            "label": "影视质感",
            "caption": "克制色彩、自然光比、电影镜头语言",
            "tone": "slate",
        },
        {
            "id": "saturated_realism",
            "label": "高饱和写实",
            "caption": "强烈色彩、清晰主体、商业大片冲击力",
            "tone": "amber",
        },
        {
            "id": "western_realism",
            "label": "欧美写实",
            "caption": "冷峻肤质、纪实布光、硬朗环境细节",
            "tone": "steel",
        },
        {
            "id": "retro_dv",
            "label": "复古 DV",
            "caption": "低保真颗粒、手持视角、年代化偏色",
            "tone": "cyan",
        },
        {
            "id": "wong_kar_wai",
            "label": "王家卫电影",
            "caption": "霓虹色偏、拖影快门、情绪化构图",
            "tone": "magenta",
        },
        {
            "id": "clean_realism",
            "label": "唯美写实",
            "caption": "柔和肤色、通透空气感、精致商业光线",
            "tone": "ivory",
        },
    ]
    last_sequence = session.scalar(
        select(func.max(AgentInterrupt.sequence)).where(AgentInterrupt.run_id == run.id)
    )
    interrupt = AgentInterrupt(
        run_id=run.id,
        sequence=int(last_sequence or 0) + 1,
        kind="single_select",
        decision_key="visual_style",
        title="确定视觉画风",
        description="先锁定角色与场景的共同视觉基准，再继续生成画布节点。",
        payload={
            "presentation": "visual_style",
            "options": options,
            "confirm_label": "确认画风",
        },
    )
    session.add(interrupt)
    session.flush()
    interrupt_payload = AgentInterruptRead.model_validate(interrupt).model_dump(mode="json")
    message = AgentMessage(
        thread_id=thread.id,
        run_id=run.id,
        role=AgentMessageRole.ASSISTANT,
        content="在创建角色和场景节点前，先确定这组资产的统一视觉画风。",
        message_type="interrupt",
        message_metadata={"interrupt": interrupt_payload},
    )
    session.add(message)
    session.flush()
    run.status = AgentRunStatus.WAITING_USER
    run.current_step = "wait_for_visual_style"
    append_agent_event(
        session,
        run,
        "skill.loaded",
        {"skill": "visual_style_design", "label": "画风设计"},
    )
    _append_completed_message_event(session, run, message)
    append_agent_event(session, run, "interrupt.created", {"interrupt": interrupt_payload})
    session.commit()
    return interrupt


def execute_agent_run(run_id: str) -> None:
    settings = get_settings()
    with SessionLocal() as session:
        run = session.get(AgentRun, uuid.UUID(run_id))
        if run is None or run.status != AgentRunStatus.THINKING:
            return
        thread = session.get(AgentThread, run.thread_id)
        if thread is None:
            return

        try:
            append_agent_event(session, run, "run.started", {"step": "load_context"})
            session.commit()

            snapshot = run.context_snapshot
            context_text = build_agent_context(
                session,
                project_id=uuid.UUID(str(snapshot["project_id"])),
                shot_id=(
                    uuid.UUID(str(snapshot["shot_id"])) if snapshot.get("shot_id") else None
                ),
                selected_node_ids=[str(value) for value in snapshot.get("selected_node_ids", [])],
                mentions=[item for item in snapshot.get("mentions", []) if isinstance(item, dict)],
                skill_id=str(snapshot.get("skill_id")) if snapshot.get("skill_id") else None,
                skill_prompt=str(snapshot.get("skill_prompt")) if snapshot.get("skill_prompt") else None,
            )
            run.current_step = "compose_response"
            append_agent_event(
                session,
                run,
                "context.loaded",
                {
                    "shot_id": snapshot.get("shot_id"),
                    "selected_node_ids": snapshot.get("selected_node_ids", []),
                },
            )
            session.commit()

            recent_messages = list(
                session.scalars(
                    select(AgentMessage)
                    .where(
                        AgentMessage.thread_id == thread.id,
                        AgentMessage.role.in_([
                            AgentMessageRole.USER,
                            AgentMessageRole.ASSISTANT,
                        ]),
                    )
                    .order_by(AgentMessage.created_at.desc())
                    .limit(settings.agent_history_messages)
                )
            )
            ordered_messages = list(reversed(recent_messages))
            current_user_message = next(
                (
                    message
                    for message in ordered_messages
                    if message.run_id == run.id and message.role == AgentMessageRole.USER
                ),
                None,
            )
            if current_user_message is not None:
                ordered_messages = [
                    message for message in ordered_messages if message.id != current_user_message.id
                ] + [current_user_message]
            messages = [
                {"role": message.role.value, "content": message.content}
                for message in ordered_messages
            ]
            state: AgentState = {
                "thread_id": str(thread.id),
                "run_id": str(run.id),
                "messages": messages,
                "context": snapshot,
                "context_text": context_text,
                "status": run.status.value,
                "current_step": run.current_step,
                "pending_actions": [],
                "tool_calls": [],
                "errors": [],
            }
            latest_message = messages[-1]["content"]
            if requires_visual_style_choice(latest_message):
                create_visual_style_interrupt(session, run, thread)
                return

            selected_node_ids = [str(value) for value in snapshot.get("selected_node_ids", [])]
            if requires_node_generation_confirmation(latest_message, selected_node_ids):
                create_node_generation_interrupt(session, run, thread)
                return

            runtime = create_agent_runtime(settings)
            if is_canvas_operation_request(latest_message, selected_node_ids, messages):
                run.status = AgentRunStatus.PLANNING
                run.current_step = "compile_canvas_patch"
                append_agent_event(session, run, "plan.started", {"step": run.current_step})
                session.commit()

                result = runtime.plan(state)
                shot_id = snapshot.get("shot_id")
                if not shot_id:
                    raise CanvasPatchError("画布变更需要明确的镜头上下文")
                workflow = load_workflow(session, uuid.UUID(str(shot_id)))
                if workflow is None:
                    raise CanvasPatchError("当前镜头还没有可修改的画布")
                current_canvas_version = workflow.updated_at.isoformat()
                run.canvas_version = current_canvas_version
                patch = compile_canvas_patch(
                    result.actions,
                    workflow=workflow,
                    selected_node_ids=selected_node_ids,
                    base_canvas_version=current_canvas_version,
                    base_revision=workflow.revision,
                    canvas_center=snapshot.get("canvas_center"),
                )
                approval = AgentApproval(
                    run_id=run.id,
                    summary=result.summary[:2000],
                    risk_level=result.risk_level,
                    patch=patch.model_dump(mode="json"),
                )
                session.add(approval)
                run.provider = result.provider
                run.model = result.model
                run.status = AgentRunStatus.WAITING_APPROVAL
                run.current_step = "wait_for_approval"
                assistant_message = AgentMessage(
                    thread_id=thread.id,
                    run_id=run.id,
                    role=AgentMessageRole.ASSISTANT,
                    content=result.summary,
                    message_type="approval_request",
                    message_metadata={
                        "provider": result.provider,
                        "model": result.model,
                        "provider_job_id": result.provider_job_id,
                        "partial": False,
                    },
                )
                session.add(assistant_message)
                session.flush()
                approval_payload = AgentApprovalRead.model_validate(approval).model_dump(mode="json")
                append_agent_event(
                    session,
                    run,
                    "message.completed",
                    {
                        "message_id": str(assistant_message.id),
                        "role": assistant_message.role.value,
                        "content": assistant_message.content,
                        "message_type": assistant_message.message_type,
                        "message_metadata": assistant_message.message_metadata,
                        "created_at": assistant_message.created_at.isoformat()
                        if assistant_message.created_at
                        else datetime.now(UTC).isoformat(),
                    },
                )
                append_agent_event(
                    session,
                    run,
                    "approval.required",
                    {"approval": approval_payload},
                )
                session.commit()
                return

            result = runtime.stream(state)
            run.provider = result.provider
            run.model = result.model
            append_agent_event(
                session,
                run,
                "message.started",
                {"role": "assistant", "provider": result.provider, "model": result.model},
            )
            session.commit()

            content_parts: list[str] = []
            assistant_message: AgentMessage | None = None
            for chunk in result.chunks:
                session.refresh(run)
                if run.status == AgentRunStatus.CANCELLED:
                    if assistant_message is not None:
                        assistant_message.message_metadata = {
                            **assistant_message.message_metadata,
                            "partial": True,
                            "cancelled": True,
                        }
                        session.commit()
                    return
                content_parts.append(chunk)
                content = "".join(content_parts)
                if assistant_message is None:
                    assistant_message = AgentMessage(
                        thread_id=thread.id,
                        run_id=run.id,
                        role=AgentMessageRole.ASSISTANT,
                        content=content,
                        message_type="text",
                        message_metadata={
                            "provider": result.provider,
                            "model": result.model,
                            "provider_job_id": result.provider_job_id,
                            "partial": True,
                        },
                    )
                    session.add(assistant_message)
                    session.flush()
                else:
                    assistant_message.content = content
                append_agent_event(
                    session,
                    run,
                    "message.delta",
                    {
                        "message_id": str(assistant_message.id),
                        "role": "assistant",
                        "delta": chunk,
                        "content_length": len(content),
                    },
                )
                session.commit()

            session.refresh(run)
            if run.status == AgentRunStatus.CANCELLED:
                if assistant_message is not None:
                    assistant_message.message_metadata = {
                        **assistant_message.message_metadata,
                        "partial": True,
                        "cancelled": True,
                    }
                    session.commit()
                return
            content = "".join(content_parts).strip()
            if not content or assistant_message is None:
                raise RuntimeError("Chat Agent 返回了空内容")

            assistant_message.content = content
            assistant_message.message_metadata = {
                "provider": result.provider,
                "model": result.model,
                "provider_job_id": result.provider_job_id,
                "partial": False,
            }
            run.status = AgentRunStatus.COMPLETED
            run.current_step = "completed"
            run.completed_at = datetime.now(UTC)
            thread.updated_at = datetime.now(UTC)
            append_agent_event(
                session,
                run,
                "message.completed",
                {
                    "message_id": str(assistant_message.id),
                    "role": assistant_message.role.value,
                    "content": assistant_message.content,
                    "message_type": assistant_message.message_type,
                    "message_metadata": assistant_message.message_metadata,
                    "created_at": assistant_message.created_at.isoformat()
                    if assistant_message.created_at
                    else datetime.now(UTC).isoformat(),
                },
            )
            append_agent_event(session, run, "run.completed", {"status": run.status.value})
            session.commit()
        except Exception as exc:  # noqa: BLE001 - background runs must persist every failure
            session.rollback()
            run = session.get(AgentRun, uuid.UUID(run_id))
            if run is None:
                return
            if run.status == AgentRunStatus.CANCELLED:
                return
            run.status = AgentRunStatus.FAILED
            run.current_step = "failed"
            run.error = str(exc)
            run.completed_at = datetime.now(UTC)
            append_agent_event(session, run, "run.failed", {"error": str(exc)})
            session.commit()


def resolve_agent_approval(
    session: Session,
    run: AgentRun,
    *,
    decision: str,
    feedback: str | None,
) -> tuple[AgentApproval, str | None, int | None]:
    approval = run.approval
    if approval is None:
        raise CanvasPatchError("该运行没有待确认的画布变更")
    if run.status != AgentRunStatus.WAITING_APPROVAL or approval.status != AgentApprovalStatus.PENDING:
        raise CanvasPatchError("该画布变更已经处理")

    now = datetime.now(UTC)
    approval.decision_feedback = feedback
    approval.resolved_at = now
    if decision == "reject":
        approval.status = AgentApprovalStatus.REJECTED
        run.status = AgentRunStatus.COMPLETED
        run.current_step = "approval_rejected"
        run.completed_at = now
        message = AgentMessage(
            thread_id=run.thread_id,
            run_id=run.id,
            role=AgentMessageRole.ASSISTANT,
            content="已取消本次画布变更，没有修改任何节点。",
            message_type="operation_result",
            message_metadata={"decision": "rejected"},
        )
        session.add(message)
        session.flush()
        append_agent_event(
            session,
            run,
            "approval.resolved",
            {"approval_id": str(approval.id), "decision": "reject"},
        )
        _append_completed_message_event(session, run, message)
        append_agent_event(session, run, "run.completed", {"status": run.status.value})
        session.commit()
        return approval, None, None

    run.status = AgentRunStatus.EXECUTING
    run.current_step = "apply_canvas_patch"
    append_agent_event(
        session,
        run,
        "approval.resolved",
        {"approval_id": str(approval.id), "decision": "approve"},
    )
    workflow = apply_canvas_patch(session, approval)
    approval.status = AgentApprovalStatus.APPROVED
    run.status = AgentRunStatus.COMPLETED
    run.current_step = "completed"
    run.completed_at = now
    canvas_version = workflow.updated_at.isoformat()
    operation_count = len(approval.patch.get("operations", []))
    message = AgentMessage(
        thread_id=run.thread_id,
        run_id=run.id,
        role=AgentMessageRole.ASSISTANT,
        content=f"已应用 {operation_count} 项画布变更。",
        message_type="operation_result",
        message_metadata={
            "decision": "approved",
            "canvas_version": canvas_version,
            "canvas_revision": workflow.revision,
        },
    )
    session.add(message)
    session.flush()
    append_agent_event(
        session,
        run,
        "canvas.patch.applied",
        {
            "approval_id": str(approval.id),
            "operation_count": operation_count,
            "shot_id": str(workflow.shot_id),
            "canvas_version": canvas_version,
            "canvas_revision": workflow.revision,
        },
    )
    _append_completed_message_event(session, run, message)
    append_agent_event(session, run, "run.completed", {"status": run.status.value})
    session.commit()
    return approval, canvas_version, workflow.revision


def fail_agent_approval(session: Session, run_id: uuid.UUID, error: str) -> None:
    session.rollback()
    run = session.get(AgentRun, run_id)
    if run is None:
        return
    if run.approval is not None:
        run.approval.status = AgentApprovalStatus.REJECTED
        run.approval.decision_feedback = error
        run.approval.resolved_at = datetime.now(UTC)
    run.status = AgentRunStatus.FAILED
    run.current_step = "canvas_patch_failed"
    run.error = error
    run.completed_at = datetime.now(UTC)
    append_agent_event(session, run, "canvas.patch.failed", {"error": error})
    append_agent_event(session, run, "run.failed", {"error": error})
    session.commit()


def resolve_agent_interrupt(
    session: Session,
    run: AgentRun,
    interrupt_id: uuid.UUID,
    response: dict[str, object],
) -> AgentInterrupt:
    interrupt = session.get(AgentInterrupt, interrupt_id)
    if interrupt is None or interrupt.run_id != run.id:
        raise CanvasPatchError("待确认的问题不存在")
    if (
        run.status != AgentRunStatus.WAITING_USER
        or interrupt.status != AgentInterruptStatus.PENDING
    ):
        raise CanvasPatchError("该选择已经处理")
    if interrupt.kind != "single_select":
        raise CanvasPatchError("当前只支持单选确认")

    option_id = str(response.get("option_id") or "")
    options = interrupt.payload.get("options", [])
    selected = next(
        (
            option
            for option in options
            if isinstance(option, dict) and str(option.get("id")) == option_id
        ),
        None,
    )
    if selected is None:
        raise CanvasPatchError("请选择有效选项")

    resolved_response = {
        "option_id": option_id,
        "label": str(selected.get("label") or option_id),
        "value": selected.get("value", option_id),
    }
    interrupt.response = resolved_response
    interrupt.status = AgentInterruptStatus.RESOLVED
    interrupt.resolved_at = datetime.now(UTC)

    messages = list(
        session.scalars(
            select(AgentMessage)
            .where(
                AgentMessage.run_id == run.id,
                AgentMessage.message_type == "interrupt",
            )
            .order_by(AgentMessage.created_at.desc())
        )
    )
    interrupt_payload = AgentInterruptRead.model_validate(interrupt).model_dump(mode="json")
    for message in messages:
        metadata_interrupt = message.message_metadata.get("interrupt", {})
        if isinstance(metadata_interrupt, dict) and metadata_interrupt.get("id") == str(interrupt.id):
            message.message_metadata = {"interrupt": interrupt_payload}
            break

    if interrupt.decision_key == "visual_style":
        decision_content = f"我选择“{resolved_response['label']}”画风"
    elif interrupt.decision_key == "generate_selected_node":
        decision_content = (
            "我确认开始生成当前节点"
            if option_id == "confirm"
            else "我选择暂不生成当前节点"
        )
    else:
        decision_content = f"我选择“{resolved_response['label']}”"

    decision_message = AgentMessage(
        thread_id=run.thread_id,
        run_id=run.id,
        role=AgentMessageRole.USER,
        content=decision_content,
        message_type="decision",
        message_metadata={
            "interrupt_id": str(interrupt.id),
            "decision_key": interrupt.decision_key,
            "response": resolved_response,
        },
    )
    session.add(decision_message)
    session.flush()
    run.status = AgentRunStatus.PLANNING
    run.current_step = "resume_interrupt"
    append_agent_event(
        session,
        run,
        "interrupt.resolved",
        {
            "interrupt_id": str(interrupt.id),
            "decision_key": interrupt.decision_key,
            "response": resolved_response,
        },
    )
    append_agent_event(
        session,
        run,
        "message.created",
        {"message_id": str(decision_message.id), "role": "user"},
    )
    session.commit()
    return interrupt


def _resume_selected_node_generation(
    session: Session,
    run: AgentRun,
    thread: AgentThread,
    interrupt: AgentInterrupt,
) -> Generation | None:
    response = interrupt.response or {}
    if response.get("option_id") == "cancel":
        now = datetime.now(UTC)
        run.status = AgentRunStatus.COMPLETED
        run.current_step = "generation_cancelled_by_user"
        run.completed_at = now
        message = AgentMessage(
            thread_id=thread.id,
            run_id=run.id,
            role=AgentMessageRole.ASSISTANT,
            content="已保留当前节点配置，没有创建生成任务。",
            message_type="operation_result",
            message_metadata={"tool_name": "generate_selected_node", "status": "cancelled"},
        )
        session.add(message)
        session.flush()
        append_agent_event(
            session,
            run,
            "tool.cancelled",
            {"tool_name": "generate_selected_node", "reason": "user_cancelled"},
        )
        _append_completed_message_event(session, run, message)
        append_agent_event(session, run, "run.completed", {"status": run.status.value})
        return None
    if response.get("option_id") != "confirm":
        raise CanvasPatchError("请选择是否启动当前节点生成")

    snapshot = run.context_snapshot
    shot_id = snapshot.get("shot_id")
    selected_node_ids = [str(value) for value in snapshot.get("selected_node_ids", [])]
    if not shot_id or not selected_node_ids:
        raise CanvasPatchError("生成节点前，请先选中当前镜头中的生成节点")
    workflow = load_workflow(session, uuid.UUID(str(shot_id)))
    if workflow is None:
        raise CanvasPatchError("当前镜头还没有可执行的画布")
    node = next(
        (item for item in workflow.nodes if str(item.id) == selected_node_ids[0]),
        None,
    )
    if node is None or node.type != "generator":
        raise CanvasPatchError("准备生成的节点已不存在")
    shot = session.get(Shot, workflow.shot_id)
    if shot is None:
        raise CanvasPatchError("当前镜头已不存在")

    active_generation = session.scalar(
        select(Generation).where(
            Generation.shot_id == shot.id,
            Generation.status.in_([GenerationStatus.QUEUED, GenerationStatus.RUNNING]),
        )
    )
    if active_generation is not None:
        raise CanvasPatchError("当前镜头已有生成任务在执行，请等待完成后再试")

    settings = get_settings()
    config = node.config if isinstance(node.config, dict) else {}
    mode = str(config.get("mode") or "")
    provider, model = _resolve_agent_generation_provider(settings, mode, config)
    prompt = str(config.get("prompt") or shot.visual_prompt or "").strip()
    if not prompt:
        raise CanvasPatchError("当前节点还没有可用于生成的 Prompt")
    upstream_ids = [
        str(edge.source) for edge in workflow.edges if str(edge.target) == str(node.id)
    ]
    parameters = _agent_generation_parameters(mode, config, upstream_ids, node.id)
    output_length = str(config.get("output_length") or "中等")
    max_tokens = 1200 if output_length == "简短" else 4000 if output_length == "详细" else 2400
    generation = Generation(
        shot_id=shot.id,
        provider=provider,
        kind=mode,
        node_id=str(node.id),
        model=model,
        input_text=prompt,
        temperature=_number_value(config.get("temperature"), 0.7),
        max_tokens=max_tokens,
        parameters=parameters,
    )
    session.add(generation)
    session.flush()

    run.provider = provider
    run.model = model
    run.status = AgentRunStatus.COMPLETED
    run.current_step = "generation_created"
    run.completed_at = datetime.now(UTC)
    append_agent_event(
        session,
        run,
        "tool.started",
        {
            "tool_name": "generate_selected_node",
            "node_id": str(node.id),
            "generation_id": str(generation.id),
        },
    )
    message = AgentMessage(
        thread_id=thread.id,
        run_id=run.id,
        role=AgentMessageRole.ASSISTANT,
        content=f"已创建{mode}生成任务，画布会继续显示任务进度与结果。",
        message_type="operation_result",
        message_metadata={
            "tool_name": "generate_selected_node",
            "status": "submitted",
            "node_id": str(node.id),
            "generation_id": str(generation.id),
            "provider": provider,
            "model": model,
        },
    )
    session.add(message)
    session.flush()
    append_agent_event(
        session,
        run,
        "generation.created",
        {
            "generation_id": str(generation.id),
            "shot_id": str(shot.id),
            "node_id": str(node.id),
            "kind": mode,
            "provider": provider,
            "model": model,
            "status": generation.status.value,
        },
    )
    append_agent_event(
        session,
        run,
        "tool.completed",
        {
            "tool_name": "generate_selected_node",
            "generation_id": str(generation.id),
            "status": "submitted",
        },
    )
    _append_completed_message_event(session, run, message)
    append_agent_event(session, run, "run.completed", {"status": run.status.value})
    return generation


def _resolve_agent_generation_provider(
    settings: Any,
    mode: str,
    config: dict[str, Any],
) -> tuple[str, str | None]:
    configured_provider = str(config.get("provider") or "").strip()
    configured_model = str(config.get("model") or "").strip() or None
    if mode == "text":
        provider = configured_provider or (
            "qwen" if settings.qwen_api_key.strip() else
            "openai_compatible" if settings.text_api_key.strip() else
            "mock"
        )
        if provider not in {"mock", "qwen", "openai_compatible"}:
            raise CanvasPatchError("当前文本节点使用了不支持的 Provider")
        if provider == "qwen" and not settings.qwen_api_key.strip():
            raise CanvasPatchError("QWEN_API_KEY 尚未配置")
        if provider == "openai_compatible" and not settings.text_api_key.strip():
            raise CanvasPatchError("TEXT_API_KEY 尚未配置")
        model = configured_model or (
            settings.qwen_text_model if provider == "qwen" else
            settings.text_model if provider == "openai_compatible" else
            "mock-text"
        )
        return provider, model
    if mode == "image":
        provider = configured_provider or (
            "qwen" if settings.qwen_api_key.strip() else
            settings.image_provider if settings.image_api_key.strip() else
            "mock"
        )
        if provider not in {
            "mock", "qwen", "openai_compatible", "ark_seedream", "google_genai"
        }:
            raise CanvasPatchError("当前图片节点使用了不支持的 Provider")
        if provider == "qwen" and not settings.qwen_api_key.strip():
            raise CanvasPatchError("QWEN_API_KEY 尚未配置")
        if provider not in {"mock", "qwen"}:
            if not settings.image_api_key.strip():
                raise CanvasPatchError("IMAGE_API_KEY 尚未配置")
            if provider != settings.image_provider:
                raise CanvasPatchError("当前图片节点 Provider 与服务端配置不一致")
        model = configured_model or (
            settings.qwen_image_model if provider == "qwen" else
            settings.image_model if provider != "mock" else
            "mock-image"
        )
        return provider, model
    if mode == "video":
        provider = configured_provider or (
            "local_h3" if settings.local_video_base_url.strip() else "mock"
        )
        if provider not in {"mock", "local_h3"}:
            raise CanvasPatchError("当前视频节点使用了不支持的 Provider")
        if provider == "local_h3" and not settings.local_video_base_url.strip():
            raise CanvasPatchError("LOCAL_VIDEO_BASE_URL 尚未配置")
        return provider, configured_model or (
            settings.local_video_model if provider == "local_h3" else "mock-video"
        )
    raise CanvasPatchError("当前节点尚未配置文本、图片或视频生成类型")


def _agent_generation_parameters(
    mode: str,
    config: dict[str, Any],
    upstream_ids: list[str],
    node_id: uuid.UUID,
) -> dict[str, Any]:
    if mode == "text":
        return {"context_source_node_ids": upstream_ids}
    uploaded_assets = config.get("uploaded_assets", [])
    safe_uploads = uploaded_assets if isinstance(uploaded_assets, list) else []
    if mode == "image":
        return {
            "size": str(config.get("resolution") or "2K"),
            "aspect_ratio": str(config.get("aspect_ratio") or "16:9"),
            "count": int(_number_value(config.get("count"), 1)),
            "seed": int(_number_value(config.get("seed"), -1)),
            "negative_prompt": str(config.get("negative_prompt") or ""),
            "prompt_extend": True,
            "context_source_node_ids": upstream_ids,
            "uploaded_assets": safe_uploads,
        }
    return {
        "preset": str(config.get("preset") or "custom"),
        "width": int(_number_value(config.get("width"), 256)),
        "height": int(_number_value(config.get("height"), 256)),
        "duration_seconds": int(_number_value(config.get("duration_seconds"), 1)),
        "steps": int(_number_value(config.get("steps"), 4)),
        "seed": int(_number_value(config.get("seed"), 42)),
        "camera_motion": str(config.get("camera_motion") or "自动"),
        "output_name": f"libtv-{str(node_id)[:8]}",
        "video_reference_mode": str(config.get("video_reference_mode") or "text"),
        "first_frame_node_id": str(config.get("first_frame_node_id") or ""),
        "last_frame_node_id": str(config.get("last_frame_node_id") or ""),
        "reference_image_node_ids": config.get("reference_image_node_ids", []),
        "reference_bindings": config.get("reference_bindings", []),
        "prompt_schema": config.get("prompt_schema"),
        "intent_prompt": config.get("intent_prompt"),
        "context_source_node_ids": upstream_ids,
        "uploaded_assets": safe_uploads,
    }


def _number_value(value: Any, fallback: float) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else fallback


def _dispatch_agent_generation(session: Session, generation: Generation) -> None:
    settings = get_settings()
    generation_id = generation.id
    if generation.provider == "local_h3" and settings.celery_task_always_eager:
        generation.celery_task_id = f"agent-background-{generation_id}"
        session.commit()
        generate_shot.run(str(generation_id))
        return
    try:
        task_result = generate_shot.delay(str(generation_id))
    except Exception as exc:  # noqa: BLE001 - queue failures belong to the Generation record
        session.expire_all()
        failed = session.get(Generation, generation_id)
        if failed is not None:
            failed.status = GenerationStatus.FAILED
            failed.error = f"Task dispatch failed: {exc}"
            session.commit()
        return
    session.expire_all()
    refreshed = session.get(Generation, generation_id)
    if refreshed is not None:
        refreshed.celery_task_id = task_result.id
        session.commit()


def resume_agent_run(run_id: str) -> None:
    """P1 resume adapter; later maps directly to LangGraph Command(resume=...)."""

    settings = get_settings()
    with SessionLocal() as session:
        run = session.get(AgentRun, uuid.UUID(run_id))
        if (
            run is None
            or run.status != AgentRunStatus.PLANNING
            or run.current_step != "resume_interrupt"
        ):
            return
        thread = session.get(AgentThread, run.thread_id)
        if thread is None:
            return
        try:
            interrupt = session.scalar(
                select(AgentInterrupt)
                .where(
                    AgentInterrupt.run_id == run.id,
                    AgentInterrupt.status == AgentInterruptStatus.RESOLVED,
                )
                .order_by(AgentInterrupt.sequence.desc())
            )
            if interrupt is None:
                raise CanvasPatchError("无法恢复未知的确认步骤")
            if interrupt.decision_key == "generate_selected_node":
                generation = _resume_selected_node_generation(session, run, thread, interrupt)
                session.commit()
                if generation is not None:
                    _dispatch_agent_generation(session, generation)
                return
            if interrupt.decision_key != "visual_style":
                raise CanvasPatchError("无法恢复未知的确认步骤")
            response = interrupt.response or {}
            style_label = str(response.get("label") or "统一写实")
            snapshot = run.context_snapshot
            shot_id = snapshot.get("shot_id")
            if not shot_id:
                raise CanvasPatchError("创建视觉资产需要镜头上下文")
            workflow = load_workflow(session, uuid.UUID(str(shot_id)))
            if workflow is None:
                raise CanvasPatchError("当前镜头还没有可修改的画布")
            original_message = session.scalar(
                select(AgentMessage)
                .where(
                    AgentMessage.run_id == run.id,
                    AgentMessage.role == AgentMessageRole.USER,
                    AgentMessage.message_type == "text",
                )
                .order_by(AgentMessage.created_at)
                .limit(1)
            )
            goal = original_message.content if original_message is not None else "当前镜头"
            actions = [
                {
                    "type": "create_node",
                    "temp_id": "character_asset",
                    "node_type": "generator",
                    "mode": "image",
                    "prompt": f"{style_label}风格，角色资产设计：{goal}",
                    "description": f"新增角色设计图片节点 · {style_label}",
                },
                {
                    "type": "create_node",
                    "temp_id": "scene_asset",
                    "node_type": "generator",
                    "mode": "image",
                    "prompt": f"{style_label}风格，场景资产设计：{goal}",
                    "description": f"新增场景设计图片节点 · {style_label}",
                },
            ]
            current_canvas_version = workflow.updated_at.isoformat()
            run.canvas_version = current_canvas_version
            run.current_step = "compile_canvas_patch"
            append_agent_event(
                session,
                run,
                "run.resumed",
                {"interrupt_id": str(interrupt.id), "decision_key": interrupt.decision_key},
            )
            append_agent_event(session, run, "plan.started", {"step": run.current_step})
            patch = compile_canvas_patch(
                actions,
                workflow=workflow,
                selected_node_ids=[
                    str(value) for value in snapshot.get("selected_node_ids", [])
                ],
                base_canvas_version=current_canvas_version,
                base_revision=workflow.revision,
                canvas_center=snapshot.get("canvas_center"),
            )
            approval = AgentApproval(
                run_id=run.id,
                summary=f"已按“{style_label}”画风准备角色与场景两个图片节点。",
                risk_level="low",
                patch=patch.model_dump(mode="json"),
            )
            session.add(approval)
            run.provider = "orchestrator"
            run.model = settings.agent_model or "rule-based-resume"
            run.status = AgentRunStatus.WAITING_APPROVAL
            run.current_step = "wait_for_approval"
            message = AgentMessage(
                thread_id=thread.id,
                run_id=run.id,
                role=AgentMessageRole.ASSISTANT,
                content=approval.summary,
                message_type="approval_request",
                message_metadata={
                    "provider": run.provider,
                    "model": run.model,
                    "partial": False,
                },
            )
            session.add(message)
            session.flush()
            approval_payload = AgentApprovalRead.model_validate(approval).model_dump(mode="json")
            _append_completed_message_event(session, run, message)
            append_agent_event(
                session,
                run,
                "approval.required",
                {"approval": approval_payload},
            )
            session.commit()
        except Exception as exc:  # noqa: BLE001 - resume failures must remain observable
            session.rollback()
            run = session.get(AgentRun, uuid.UUID(run_id))
            if run is None:
                return
            run.status = AgentRunStatus.FAILED
            run.current_step = "resume_failed"
            run.error = str(exc)
            run.completed_at = datetime.now(UTC)
            append_agent_event(session, run, "run.failed", {"error": str(exc)})
            session.commit()


def _append_completed_message_event(
    session: Session,
    run: AgentRun,
    message: AgentMessage,
) -> None:
    append_agent_event(
        session,
        run,
        "message.completed",
        {
            "message_id": str(message.id),
            "role": message.role.value,
            "content": message.content,
            "message_type": message.message_type,
            "message_metadata": message.message_metadata,
            "created_at": message.created_at.isoformat()
            if message.created_at
            else datetime.now(UTC).isoformat(),
        },
    )
