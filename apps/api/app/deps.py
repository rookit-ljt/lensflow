from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_session
from .auth import AdminUser, CurrentUser, require_admin, require_user
from .db_models import (
    AgentRun,
    AgentThread,
    Asset,
    Generation,
    Project,
    Shot,
    StoredUpload,
    User,
    Workflow,
    WorkflowNode,
)

DatabaseSession = Annotated[Session, Depends(get_session)]


def get_owned_project(session: Session, user: User, project_id: uuid.UUID) -> Project:
    project = session.scalar(
        select(Project).where(Project.id == project_id, Project.user_id == user.id)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def get_owned_shot(session: Session, user: User, shot_id: uuid.UUID) -> Shot:
    shot = session.scalar(
        select(Shot)
        .join(Project, Project.id == Shot.project_id)
        .where(Shot.id == shot_id, Project.user_id == user.id)
    )
    if shot is None:
        raise HTTPException(status_code=404, detail="Shot not found")
    return shot


def get_owned_thread(session: Session, user: User, thread_id: uuid.UUID) -> AgentThread:
    thread = session.scalar(
        select(AgentThread)
        .join(Project, Project.id == AgentThread.project_id)
        .where(AgentThread.id == thread_id, Project.user_id == user.id)
    )
    if thread is None:
        raise HTTPException(status_code=404, detail="Agent thread not found")
    return thread


def get_owned_run(session: Session, user: User, run_id: uuid.UUID) -> AgentRun:
    run = session.scalar(
        select(AgentRun)
        .join(AgentThread, AgentThread.id == AgentRun.thread_id)
        .join(Project, Project.id == AgentThread.project_id)
        .where(AgentRun.id == run_id, Project.user_id == user.id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


def get_owned_generation(session: Session, user: User, generation_id: uuid.UUID) -> Generation:
    generation = session.scalar(
        select(Generation)
        .join(Shot, Shot.id == Generation.shot_id)
        .join(Project, Project.id == Shot.project_id)
        .where(Generation.id == generation_id, Project.user_id == user.id)
    )
    if generation is None:
        raise HTTPException(status_code=404, detail="Generation not found")
    return generation


def get_owned_asset(session: Session, user: User, asset_id: uuid.UUID) -> Asset:
    asset = session.scalar(
        select(Asset).where(Asset.id == asset_id, Asset.user_id == user.id)
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


def require_owned_upload(session: Session, user: User, upload_id: uuid.UUID) -> None:
    owner_id = session.scalar(
        select(StoredUpload.user_id).where(StoredUpload.id == upload_id)
    )
    if owner_id == user.id:
        return
    if owner_id is None:
        first_user_id = session.scalar(select(User.id).order_by(User.created_at, User.id).limit(1))
        if first_user_id == user.id:
            return
    raise HTTPException(status_code=404, detail="Upload not found")


def workflow_contains_cycle(edges: list[object]) -> bool:
    adjacency: dict[object, list[object]] = {}
    for edge in edges:
        source = getattr(edge, "source", None)
        target = getattr(edge, "target", None)
        if source is not None and target is not None:
            adjacency.setdefault(source, []).append(target)
    visiting: set[object] = set()
    visited: set[object] = set()

    def visit(node: object) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in adjacency.get(node, [])):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in adjacency)


def config_references_asset(
    value: object,
    asset_id: uuid.UUID,
    source_upload_id: uuid.UUID | None,
) -> bool:
    """Recognize asset references persisted inside workflow node JSON configs."""
    asset_value = str(asset_id)
    upload_value = str(source_upload_id) if source_upload_id is not None else None
    if isinstance(value, list):
        return any(
            config_references_asset(item, asset_id, source_upload_id)
            for item in value
        )
    if not isinstance(value, dict):
        return False
    for key, item in value.items():
        if key == "asset_id" and str(item) == asset_value:
            return True
        if upload_value is not None and key in {"id", "source_upload_id"} and str(item) == upload_value:
            return True
        if config_references_asset(item, asset_id, source_upload_id):
            return True
    return False


def asset_reference_count(session: Session, asset: Asset) -> int:
    if asset.project_id is None:
        return 0
    configs = session.scalars(
        select(WorkflowNode.config)
        .join(Workflow, Workflow.id == WorkflowNode.workflow_id)
        .join(Shot, Shot.id == Workflow.shot_id)
        .where(Shot.project_id == asset.project_id)
    )
    return sum(
        1
        for config in configs
        if config_references_asset(config, asset.id, asset.source_upload_id)
    )


# 别名兼容
_owned_project = get_owned_project
_owned_shot = get_owned_shot
_owned_thread = get_owned_thread
_owned_run = get_owned_run
_owned_generation = get_owned_generation
_owned_asset = get_owned_asset
_require_owned_upload = require_owned_upload
_workflow_contains_cycle = workflow_contains_cycle
_config_references_asset = config_references_asset
_asset_reference_count = asset_reference_count

__all__ = [
    "DatabaseSession",
    "CurrentUser",
    "AdminUser",
    "require_user",
    "require_admin",
    "get_owned_project",
    "get_owned_shot",
    "get_owned_thread",
    "get_owned_run",
    "get_owned_generation",
    "get_owned_asset",
    "require_owned_upload",
    "workflow_contains_cycle",
    "config_references_asset",
    "asset_reference_count",
]
