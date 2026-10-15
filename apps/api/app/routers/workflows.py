from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from ..auth import CurrentUser
from ..db_models import Shot, Workflow
from ..deps import (
    DatabaseSession,
    get_owned_project,
    get_owned_shot,
    workflow_contains_cycle,
)
from ..schemas import (
    ShotCreate,
    ShotRead,
    ShotUpdate,
    WorkflowRead,
    WorkflowWrite,
)
from ..workflows import (
    WorkflowVersionConflict,
    get_or_create_workflow,
    load_workflow,
    replace_workflow,
)

router = APIRouter()


@router.post(
    "/api/projects/{project_id}/shots",
    response_model=ShotRead,
    status_code=status.HTTP_201_CREATED,
    tags=["shots"],
)
def create_shot(
    project_id: uuid.UUID,
    payload: ShotCreate,
    session: DatabaseSession,
    user: CurrentUser,
) -> Shot:
    get_owned_project(session, user, project_id)

    shot = Shot(project_id=project_id, **payload.model_dump())
    session.add(shot)
    session.commit()
    session.refresh(shot)
    return shot


@router.patch("/api/shots/{shot_id}", response_model=ShotRead, tags=["shots"])
def update_shot(
    shot_id: uuid.UUID,
    payload: ShotUpdate,
    session: DatabaseSession,
    user: CurrentUser,
) -> Shot:
    shot = get_owned_shot(session, user, shot_id)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(shot, field, value)

    session.commit()
    session.refresh(shot)
    return shot


@router.get(
    "/api/shots/{shot_id}/workflow",
    response_model=WorkflowRead,
    tags=["workflows"],
)
def get_workflow(
    shot_id: uuid.UUID,
    session: DatabaseSession,
    user: CurrentUser,
    empty: bool = Query(False, description="Create an empty workflow for Agent-first projects"),
) -> Workflow:
    shot = get_owned_shot(session, user, shot_id)
    if empty and load_workflow(session, shot_id) is None:
        workflow = Workflow(shot_id=shot.id, schema_version="1.0")
        session.add(workflow)
        session.commit()
        session.refresh(workflow)
        return workflow
    return get_or_create_workflow(session, shot)


@router.put(
    "/api/shots/{shot_id}/workflow",
    response_model=WorkflowRead,
    tags=["workflows"],
)
def save_workflow(
    shot_id: uuid.UUID,
    payload: WorkflowWrite,
    session: DatabaseSession,
    user: CurrentUser,
) -> Workflow:
    shot = get_owned_shot(session, user, shot_id)
    if len(payload.nodes) > 200 or len(payload.edges) > 500:
        raise HTTPException(status_code=422, detail="Workflow is too large")

    node_ids = [node.id for node in payload.nodes]
    edge_ids = [edge.id for edge in payload.edges]
    if len(node_ids) != len(set(node_ids)) or len(edge_ids) != len(set(edge_ids)):
        raise HTTPException(status_code=422, detail="Workflow contains duplicate ids")
    node_id_set = set(node_ids)
    if any(
        edge.source not in node_id_set
        or edge.target not in node_id_set
        or edge.source == edge.target
        for edge in payload.edges
    ):
        raise HTTPException(status_code=422, detail="Workflow contains an invalid edge")
    if workflow_contains_cycle(payload.edges):
        raise HTTPException(status_code=422, detail="Workflow 不能形成循环连线")

    workflow = get_or_create_workflow(session, shot)
    try:
        return replace_workflow(session, workflow, payload)
    except WorkflowVersionConflict as cause:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(cause)) from cause
