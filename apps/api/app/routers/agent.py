from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ..agent_canvas import CanvasPatchError
from ..agent_service import (
    append_agent_event,
    fail_agent_approval,
    normalize_pending_interrupt,
    resolve_agent_approval,
    resolve_agent_interrupt,
    resume_agent_run,
)
from ..agent_service import (
    execute_agent_run as default_execute_agent_run,
)
from ..agent_skills import get_skill, list_skills
from ..auth import CurrentUser
from ..config import get_settings
from ..credits_service import (
    InsufficientCreditsError,
    calculate_agent_run_cost,
    freeze_credits,
)
from ..database import SessionLocal
from ..db_models import (
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
    Shot,
)
from ..deps import (
    DatabaseSession,
    get_owned_project,
    get_owned_run,
    get_owned_thread,
)
from ..routers.generations import enqueue_approved_generations
from ..schemas import (
    AgentApprovalDecision,
    AgentApprovalDecisionResult,
    AgentApprovalRead,
    AgentEventRead,
    AgentInterruptRead,
    AgentInterruptResume,
    AgentInterruptResumeResult,
    AgentMessageRead,
    AgentRunCreate,
    AgentRunRead,
    AgentSkillRead,
    AgentThreadCreate,
    AgentThreadRead,
)

settings = get_settings()

router = APIRouter(tags=["agent"])

_AGENT_RUN_CREATE_LOCK = threading.Lock()


def _get_execute_agent_run():
    main_mod = sys.modules.get("app.main")
    return getattr(main_mod, "execute_agent_run", default_execute_agent_run) if main_mod else default_execute_agent_run


@router.get(
    "/api/agent/skills",
    response_model=list[AgentSkillRead],
)
def list_agent_skills(user: CurrentUser) -> list[dict[str, object]]:
    return list_skills()


@router.get(
    "/api/projects/{project_id}/agent/threads",
    response_model=list[AgentThreadRead],
)
def list_agent_threads(
    project_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> list[AgentThread]:
    get_owned_project(session, user, project_id)
    statement = (
        select(AgentThread)
        .where(AgentThread.project_id == project_id)
        .order_by(AgentThread.updated_at.desc())
    )
    return list(session.scalars(statement))


@router.post(
    "/api/projects/{project_id}/agent/threads",
    response_model=AgentThreadRead,
    status_code=status.HTTP_201_CREATED,
)
def create_agent_thread(
    project_id: uuid.UUID,
    payload: AgentThreadCreate,
    session: DatabaseSession,
    user: CurrentUser,
) -> AgentThread:
    get_owned_project(session, user, project_id)
    thread = AgentThread(project_id=project_id, title=payload.title)
    session.add(thread)
    session.commit()
    session.refresh(thread)
    return thread


@router.get(
    "/api/agent/threads/{thread_id}/messages",
    response_model=list[AgentMessageRead],
)
def list_agent_messages(
    thread_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> list[AgentMessage]:
    get_owned_thread(session, user, thread_id)
    statement = (
        select(AgentMessage)
        .where(AgentMessage.thread_id == thread_id)
        .order_by(AgentMessage.created_at)
    )
    return list(session.scalars(statement))


@router.get(
    "/api/agent/threads/{thread_id}/active-run",
    response_model=AgentRunRead | None,
)
def get_active_agent_run(
    thread_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> AgentRun | None:
    """Return the durable run a chat should reattach to after reopening."""
    get_owned_thread(session, user, thread_id)
    return session.scalar(
        select(AgentRun)
        .where(
            AgentRun.thread_id == thread_id,
            AgentRun.status.in_([
                AgentRunStatus.THINKING,
                AgentRunStatus.PLANNING,
                AgentRunStatus.WAITING_USER,
                AgentRunStatus.WAITING_APPROVAL,
                AgentRunStatus.EXECUTING,
                AgentRunStatus.WAITING_EXTERNAL_JOB,
            ]),
        )
        .order_by(AgentRun.created_at.desc())
    )


@router.get(
    "/api/agent/threads/{thread_id}/pending-approval",
    response_model=AgentApprovalRead | None,
)
def get_pending_agent_approval(
    thread_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> AgentApproval | None:
    get_owned_thread(session, user, thread_id)
    statement = (
        select(AgentApproval)
        .join(AgentRun, AgentRun.id == AgentApproval.run_id)
        .where(
            AgentRun.thread_id == thread_id,
            AgentApproval.status == AgentApprovalStatus.PENDING,
        )
        .order_by(AgentApproval.created_at.desc())
    )
    return session.scalar(statement)


@router.get(
    "/api/agent/threads/{thread_id}/pending-interrupt",
    response_model=AgentInterruptRead | None,
)
def get_pending_agent_interrupt(
    thread_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> AgentInterrupt | None:
    get_owned_thread(session, user, thread_id)
    statement = (
        select(AgentInterrupt)
        .join(AgentRun, AgentRun.id == AgentInterrupt.run_id)
        .where(
            AgentRun.thread_id == thread_id,
            AgentInterrupt.status == AgentInterruptStatus.PENDING,
        )
        .order_by(AgentInterrupt.created_at.desc())
    )
    interrupt = session.scalar(statement)
    if interrupt is not None and normalize_pending_interrupt(interrupt):
        session.commit()
        session.refresh(interrupt)
    return interrupt


@router.post(
    "/api/agent/threads/{thread_id}/runs",
    response_model=AgentRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_agent_run(
    thread_id: uuid.UUID,
    payload: AgentRunCreate,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    user: CurrentUser,
) -> AgentRun:
    thread = get_owned_thread(session, user, thread_id)
    if payload.context.project_id != thread.project_id:
        raise HTTPException(status_code=409, detail="Agent context does not belong to this thread")
    if payload.context.skill_id and get_skill(payload.context.skill_id) is None and not payload.context.skill_prompt:
        raise HTTPException(status_code=409, detail="Agent skill is not available")
    if payload.context.shot_id is not None:
        shot = session.get(Shot, payload.context.shot_id)
        if shot is None or shot.project_id != thread.project_id:
            raise HTTPException(status_code=409, detail="Agent shot context is invalid")

    with _AGENT_RUN_CREATE_LOCK:
        active_run = session.scalar(
            select(AgentRun).where(
                AgentRun.thread_id == thread_id,
                AgentRun.status.in_([
                    AgentRunStatus.THINKING,
                    AgentRunStatus.PLANNING,
                    AgentRunStatus.WAITING_USER,
                    AgentRunStatus.WAITING_APPROVAL,
                    AgentRunStatus.EXECUTING,
                    AgentRunStatus.WAITING_EXTERNAL_JOB,
                ]),
            )
        )
        if active_run is not None:
            raise HTTPException(status_code=409, detail="Chat Agent 仍在处理上一条消息")

        context_snapshot = payload.context.model_dump(mode="json")
        run = AgentRun(
            thread_id=thread.id,
            status=AgentRunStatus.THINKING,
            current_step="load_context",
            context_snapshot=context_snapshot,
            canvas_version=payload.context.canvas_version,
        )
        session.add(run)
        session.flush()

        agent_cost = calculate_agent_run_cost(settings.agent_provider)
        if agent_cost > 0:
            try:
                freeze_credits(
                    session=session,
                    user=user,
                    amount=agent_cost,
                    biz_type="agent_run",
                    biz_id=str(run.id),
                    description="Chat Agent 思考与对话预扣积分",
                )
            except InsufficientCreditsError as exc:
                raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))
        user_message = AgentMessage(
            thread_id=thread.id,
            run_id=run.id,
            role=AgentMessageRole.USER,
            content=payload.message.strip(),
            message_type="text",
            message_metadata={"context": context_snapshot},
        )
        session.add(user_message)
        session.flush()
        append_agent_event(
            session,
            run,
            "message.created",
            {"message_id": str(user_message.id), "role": "user"},
        )
        if not thread.summary:
            thread.summary = payload.message.strip()[:240]
        session.commit()
        session.refresh(run)

    executor = _get_execute_agent_run()
    background_tasks.add_task(executor, str(run.id))
    return run


@router.get(
    "/api/agent/runs/{run_id}",
    response_model=AgentRunRead,
)
def get_agent_run(
    run_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> AgentRun:
    return get_owned_run(session, user, run_id)


@router.post(
    "/api/agent/runs/{run_id}/cancel",
    response_model=AgentRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def cancel_agent_run(
    run_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> AgentRun:
    run = get_owned_run(session, user, run_id)
    if run.status in {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
    }:
        return run
    run.status = AgentRunStatus.CANCELLED
    run.current_step = "cancelled"
    run.completed_at = datetime.now(UTC)
    if run.approval is not None and run.approval.status == AgentApprovalStatus.PENDING:
        run.approval.status = AgentApprovalStatus.REJECTED
        run.approval.decision_feedback = "run_cancelled"
        run.approval.resolved_at = datetime.now(UTC)
    for interrupt in run.interrupts:
        if interrupt.status == AgentInterruptStatus.PENDING:
            interrupt.status = AgentInterruptStatus.CANCELLED
            interrupt.resolved_at = datetime.now(UTC)
    append_agent_event(session, run, "run.cancelled", {"status": "cancelled"})
    session.commit()
    session.refresh(run)
    return run


@router.post(
    "/api/agent/runs/{run_id}/approval",
    response_model=AgentApprovalDecisionResult,
)
def decide_agent_approval(
    run_id: uuid.UUID,
    payload: AgentApprovalDecision,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    user: CurrentUser,
) -> dict[str, object]:
    get_owned_run(session, user, run_id)
    run = session.scalar(
        select(AgentRun)
        .where(AgentRun.id == run_id)
        .options(selectinload(AgentRun.approval))
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    was_pending = (
        run.status == AgentRunStatus.WAITING_APPROVAL
        and run.approval is not None
        and run.approval.status == AgentApprovalStatus.PENDING
    )
    try:
        approval, canvas_version, canvas_revision = resolve_agent_approval(
            session,
            run,
            decision=payload.decision,
            feedback=payload.feedback,
        )
        generated = (
            enqueue_approved_generations(session, approval, background_tasks, user)
            if payload.decision == "approve"
            else []
        )
        if generated:
            result_message = session.scalar(
                select(AgentMessage)
                .where(
                    AgentMessage.run_id == run.id,
                    AgentMessage.message_type == "operation_result",
                )
                .order_by(AgentMessage.created_at.desc())
            )
            if result_message is not None:
                result_message.content = (
                    f"已应用 {len(approval.patch.get('operations', []))} 项画布变更，"
                    f"并启动 {len(generated)} 个{('图片' if generated[0].kind == 'image' else '视频' if generated[0].kind == 'video' else '文本')}生成任务。"
                )
                result_message.message_metadata = {
                    **(result_message.message_metadata or {}),
                    "generation_ids": [str(item.id) for item in generated],
                }
                session.commit()
    except CanvasPatchError as exc:
        if was_pending:
            fail_agent_approval(session, run_id, str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.refresh(run)
    session.refresh(approval)
    return {
        "run": run,
        "approval": approval,
        "canvas_version": canvas_version,
        "canvas_revision": canvas_revision,
        "generations": generated,
    }


@router.post(
    "/api/agent/runs/{run_id}/resume",
    response_model=AgentInterruptResumeResult,
)
def resume_agent_interrupt(
    run_id: uuid.UUID,
    payload: AgentInterruptResume,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    user: CurrentUser,
) -> dict[str, object]:
    get_owned_run(session, user, run_id)
    run = session.scalar(
        select(AgentRun)
        .where(AgentRun.id == run_id)
        .options(selectinload(AgentRun.interrupts))
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    try:
        interrupt = resolve_agent_interrupt(
            session,
            run,
            payload.interrupt_id,
            payload.response,
        )
    except CanvasPatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    event_cursor = int(
        session.scalar(
            select(func.max(AgentEvent.sequence)).where(AgentEvent.run_id == run.id)
        )
        or 0
    )
    session.refresh(run)
    session.refresh(interrupt)
    background_tasks.add_task(resume_agent_run, str(run.id))
    return {"run": run, "interrupt": interrupt, "event_cursor": event_cursor}


@router.get(
    "/api/agent/runs/{run_id}/events",
    response_model=list[AgentEventRead],
)
def list_agent_events(
    run_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> list[AgentEvent]:
    get_owned_run(session, user, run_id)
    statement = (
        select(AgentEvent)
        .where(AgentEvent.run_id == run_id)
        .order_by(AgentEvent.sequence)
    )
    return list(session.scalars(statement))


@router.get("/api/agent/runs/{run_id}/events/stream")
def stream_agent_events(
    run_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
    after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    get_owned_run(session, user, run_id)

    def event_stream():
        last_sequence = after
        while True:
            with SessionLocal() as event_session:
                events = list(
                    event_session.scalars(
                        select(AgentEvent)
                        .where(
                            AgentEvent.run_id == run_id,
                            AgentEvent.sequence > last_sequence,
                        )
                        .order_by(AgentEvent.sequence)
                    )
                )
                run = event_session.get(AgentRun, run_id)
                for event in events:
                    last_sequence = event.sequence
                    event_data = AgentEventRead.model_validate(event).model_dump(mode="json")
                    yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                terminal = run is None or run.status in {
                    AgentRunStatus.WAITING_USER,
                    AgentRunStatus.WAITING_APPROVAL,
                    AgentRunStatus.COMPLETED,
                    AgentRunStatus.FAILED,
                    AgentRunStatus.CANCELLED,
                }
            if terminal:
                break
            time.sleep(0.35)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
