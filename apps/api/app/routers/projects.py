from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from ..auth import CurrentUser
from ..config import get_settings
from ..db_models import (
    AgentApprovalStatus,
    AgentInterruptStatus,
    AgentRun,
    AgentRunStatus,
    AgentThread,
    Asset,
    Feedback,
    Generation,
    GenerationStatus,
    Project,
    Shot,
    StoredUpload,
    Workflow,
)
from ..deps import (
    DatabaseSession,
    get_owned_generation,
    get_owned_project,
    get_owned_shot,
)
from ..schemas import (
    FeedbackCreate,
    FeedbackRead,
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
)
from ..uploads import find_uploaded_image
from ..workflows import get_or_create_workflow

settings = get_settings()

router = APIRouter()


@router.get("/api/projects", response_model=list[ProjectRead], tags=["projects"])
def list_projects(session: DatabaseSession, user: CurrentUser) -> list[Project]:
    return list(
        session.scalars(
            select(Project)
            .where(Project.user_id == user.id)
            .order_by(Project.updated_at.desc())
        )
    )


@router.post(
    "/api/projects",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    tags=["projects"],
)
def create_project(
    payload: ProjectCreate,
    session: DatabaseSession,
    user: CurrentUser,
) -> Project:
    project = Project(user_id=user.id, name=payload.name, description=payload.description)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.get("/api/projects/{project_id}", response_model=ProjectDetail, tags=["projects"])
def get_project(
    project_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> Project:
    statement = (
        select(Project)
        .where(Project.id == project_id, Project.user_id == user.id)
        .options(selectinload(Project.shots))
    )
    project = session.scalar(statement)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete(
    "/api/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["projects"],
)
def delete_project(
    project_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> Response:
    """Permanently remove a project and all of its owned production data."""
    project = get_owned_project(session, user, project_id)

    paused_runs = list(
        session.scalars(
            select(AgentRun)
            .join(AgentThread, AgentThread.id == AgentRun.thread_id)
            .where(
                AgentThread.project_id == project_id,
                AgentRun.status.in_([
                    AgentRunStatus.WAITING_USER,
                    AgentRunStatus.WAITING_APPROVAL,
                ]),
            )
        )
    )
    now = datetime.now(UTC)
    for run in paused_runs:
        run.status = AgentRunStatus.CANCELLED
        run.current_step = "cancelled_by_project_delete"
        run.completed_at = now
        if run.approval is not None and run.approval.status == AgentApprovalStatus.PENDING:
            run.approval.status = AgentApprovalStatus.REJECTED
            run.approval.decision_feedback = "project_deleted"
            run.approval.resolved_at = now
        for interrupt in run.interrupts:
            if interrupt.status == AgentInterruptStatus.PENDING:
                interrupt.status = AgentInterruptStatus.CANCELLED
                interrupt.resolved_at = now

    active_run = session.scalar(
        select(AgentRun.id)
        .join(AgentThread, AgentThread.id == AgentRun.thread_id)
        .where(
            AgentThread.project_id == project_id,
            AgentRun.status.in_([
                AgentRunStatus.THINKING,
                AgentRunStatus.PLANNING,
                AgentRunStatus.EXECUTING,
                AgentRunStatus.WAITING_EXTERNAL_JOB,
            ]),
        )
    )
    if active_run is not None:
        raise HTTPException(status_code=409, detail="项目仍有 Agent 任务处理中，请先停止后再删除")

    active_generation = session.scalar(
        select(Generation.id)
        .join(Shot, Shot.id == Generation.shot_id)
        .where(
            Shot.project_id == project_id,
            Generation.status.in_([GenerationStatus.QUEUED, GenerationStatus.RUNNING]),
        )
    )
    if active_generation is not None:
        raise HTTPException(status_code=409, detail="项目仍有视频或图片任务处理中，请等待完成或取消后再删除")

    session.execute(
        update(Feedback)
        .where(Feedback.project_id == project_id)
        .values(project_id=None, shot_id=None, generation_id=None)
    )

    workflows = list(
        session.scalars(
            select(Workflow)
            .join(Shot, Shot.id == Workflow.shot_id)
            .where(Shot.project_id == project_id)
            .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
        )
    )
    for workflow in workflows:
        session.delete(workflow)

    upload_paths = []
    project_assets = list(session.scalars(select(Asset).where(Asset.project_id == project_id)))
    for asset in project_assets:
        if asset.source_upload_id is None:
            continue
        located = find_uploaded_image(settings, asset.source_upload_id)
        if located is not None:
            upload_paths.append(located[0])
        upload = session.get(StoredUpload, asset.source_upload_id)
        if upload is not None:
            session.delete(upload)

    session.delete(project)
    session.commit()
    for path in upload_paths:
        path.unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/projects/{project_id}/export", tags=["projects"])
def export_project(
    project_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
) -> Response:
    """Export a portable JSON backup of project structure and run metadata."""
    project = get_owned_project(session, user, project_id)
    shots = list(
        session.scalars(
            select(Shot).where(Shot.project_id == project_id).order_by(Shot.sequence_number)
        )
    )
    assets = list(
        session.scalars(
            select(Asset).where(Asset.project_id == project_id).order_by(Asset.created_at)
        )
    )
    workflows = []
    for shot in shots:
        workflow = get_or_create_workflow(session, shot)
        workflows.append({
            "id": str(workflow.id),
            "shot_id": str(workflow.shot_id),
            "schema_version": workflow.schema_version,
            "revision": workflow.revision,
            "viewport": workflow.viewport,
            "nodes": [
                {
                    "id": str(node.id),
                    "type": node.type,
                    "version": node.version,
                    "position": {"x": node.position_x, "y": node.position_y},
                    "config": node.config,
                }
                for node in workflow.nodes
            ],
            "edges": [
                {
                    "id": str(edge.id),
                    "source": str(edge.source),
                    "target": str(edge.target),
                    "source_handle": edge.source_handle,
                    "target_handle": edge.target_handle,
                }
                for edge in workflow.edges
            ],
        })
    generations = list(
        session.scalars(
            select(Generation)
            .join(Shot, Shot.id == Generation.shot_id)
            .where(Shot.project_id == project_id)
            .order_by(Generation.created_at)
        )
    )
    threads = list(
        session.scalars(
            select(AgentThread).where(AgentThread.project_id == project_id).order_by(AgentThread.created_at)
        )
    )

    def iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    export = {
        "format": "ai-video-studio-project-backup",
        "version": "1.0",
        "exported_at": datetime.now(UTC).isoformat(),
        "project": {
            "id": str(project.id),
            "name": project.name,
            "description": project.description,
            "status": project.status.value,
            "created_at": iso(project.created_at),
            "updated_at": iso(project.updated_at),
        },
        "shots": [
            {
                "id": str(shot.id),
                "sequence_number": shot.sequence_number,
                "title": shot.title,
                "description": shot.description,
                "visual_prompt": shot.visual_prompt,
                "duration_seconds": shot.duration_seconds,
                "status": shot.status.value,
                "created_at": iso(shot.created_at),
                "updated_at": iso(shot.updated_at),
            }
            for shot in shots
        ],
        "workflows": workflows,
        "assets": [
            {
                "id": str(asset.id),
                "shot_id": str(asset.shot_id) if asset.shot_id else None,
                "source_generation_id": str(asset.source_generation_id) if asset.source_generation_id else None,
                "kind": asset.kind,
                "role": asset.role,
                "filename": asset.filename,
                "content_type": asset.content_type,
                "size": asset.size,
                "url": asset.url,
                "metadata": asset.metadata_json,
                "created_at": iso(asset.created_at),
            }
            for asset in assets
        ],
        "generations": [
            {
                "id": str(item.id),
                "shot_id": str(item.shot_id),
                "node_id": item.node_id,
                "provider": item.provider,
                "kind": item.kind,
                "model": item.model,
                "input_text": item.input_text,
                "parameters": item.parameters,
                "status": item.status.value,
                "progress": item.progress,
                "provider_job_id": item.provider_job_id,
                "output_url": item.output_url,
                "output_text": item.output_text,
                "error": item.error,
                "created_at": iso(item.created_at),
                "updated_at": iso(item.updated_at),
            }
            for item in generations
        ],
        "agent_threads": [
            {
                "id": str(thread.id),
                "title": thread.title,
                "summary": thread.summary,
                "status": thread.status.value,
                "messages": [
                    {
                        "id": str(message.id),
                        "run_id": str(message.run_id) if message.run_id else None,
                        "role": message.role.value,
                        "content": message.content,
                        "message_type": message.message_type,
                        "metadata": message.message_metadata,
                        "created_at": iso(message.created_at),
                    }
                    for message in thread.messages
                ],
            }
            for thread in threads
        ],
        "note": "资产 URL 指向当前部署；此 JSON 不包含二进制文件，请同时备份 uploads 目录或对象存储。",
    }
    content = json.dumps(export, ensure_ascii=False, indent=2, default=str)
    filename = f"ai-video-studio-project-{project.id.hex[:8]}.json"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/api/feedback",
    response_model=FeedbackRead,
    status_code=status.HTTP_201_CREATED,
    tags=["feedback"],
)
def submit_feedback(
    payload: FeedbackCreate,
    session: DatabaseSession,
    user: CurrentUser,
) -> Feedback:
    """Store a beta user's issue report with only the selected runtime context."""
    project_id = payload.project_id
    shot_id = payload.shot_id
    generation_id = payload.generation_id
    if project_id:
        get_owned_project(session, user, project_id)
    if shot_id:
        shot = get_owned_shot(session, user, shot_id)
        if project_id and shot.project_id != project_id:
            raise HTTPException(status_code=400, detail="镜头不属于当前项目")
        project_id = project_id or shot.project_id
    if generation_id:
        generation = get_owned_generation(session, user, generation_id)
        if shot_id and generation.shot_id != shot_id:
            raise HTTPException(status_code=400, detail="生成任务不属于当前镜头")
        if not shot_id:
            shot_id = generation.shot_id
        if not project_id:
            project_id = session.scalar(
                select(Shot.project_id).where(Shot.id == generation.shot_id)
            )
    feedback = Feedback(
        user_id=user.id,
        project_id=project_id,
        shot_id=shot_id,
        generation_id=generation_id,
        category=payload.category,
        message=payload.message.strip(),
        context_json=payload.context,
    )
    session.add(feedback)
    session.commit()
    session.refresh(feedback)
    return feedback
