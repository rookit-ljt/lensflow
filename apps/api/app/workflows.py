import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from .db_models import Shot, Workflow, WorkflowEdge, WorkflowNode
from .schemas import WorkflowWrite


class WorkflowVersionConflict(RuntimeError):
    """Raised when a full workflow save is based on an obsolete revision."""


def _stable_id(shot_id: uuid.UUID, key: str) -> uuid.UUID:
    return uuid.uuid5(shot_id, key)


def _default_nodes(shot: Shot) -> list[WorkflowNode]:
    definitions = [
        (
            "shot",
            "shot",
            40,
            190,
            {"eyebrow": "SHOT INPUT", "title": shot.title, "detail": shot.description or "尚未填写"},
        ),
        (
            "prompt",
            "prompt",
            350,
            90,
            {"eyebrow": "PROMPT", "title": "镜头提示", "detail": shot.visual_prompt or "尚未填写"},
        ),
        (
            "generator",
            "generator",
            720,
            190,
            {
                "mode": None,
                "prompt": "",
                "aspect_ratio": "16:9",
                "resolution": "2K",
                "quality": "标准",
                "count": 1,
                "duration_seconds": 5,
                "panorama": False,
                "seed": -1,
            },
        ),
    ]
    return [
        WorkflowNode(
            id=_stable_id(shot.id, key),
            type=node_type,
            version="1.0",
            position_x=x,
            position_y=y,
            config=config,
        )
        for key, node_type, x, y, config in definitions
    ]


def _default_edges(shot_id: uuid.UUID) -> list[WorkflowEdge]:
    definitions = [
        ("shot-prompt", "shot", "prompt"),
        ("prompt-generator", "prompt", "generator"),
    ]
    return [
        WorkflowEdge(
            id=_stable_id(shot_id, key),
            source=_stable_id(shot_id, source),
            target=_stable_id(shot_id, target),
        )
        for key, source, target in definitions
    ]


def load_workflow(session: Session, shot_id: uuid.UUID) -> Workflow | None:
    statement = (
        select(Workflow)
        .where(Workflow.shot_id == shot_id)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
    )
    return session.scalar(statement)


def get_or_create_workflow(session: Session, shot: Shot) -> Workflow:
    workflow = load_workflow(session, shot.id)
    if workflow is not None:
        return workflow

    workflow = Workflow(shot_id=shot.id, schema_version="1.0")
    session.add(workflow)
    session.flush()
    for node in _default_nodes(shot):
        node.workflow_id = workflow.id
        session.add(node)
    for edge in _default_edges(shot.id):
        edge.workflow_id = workflow.id
        session.add(edge)
    session.commit()
    created = load_workflow(session, shot.id)
    if created is None:
        raise RuntimeError("Workflow creation failed")
    return created


def replace_workflow(session: Session, workflow: Workflow, payload: WorkflowWrite) -> Workflow:
    if workflow.last_operation_id == payload.operation_id:
        saved = load_workflow(session, workflow.shot_id)
        if saved is None:
            raise RuntimeError("Workflow save failed")
        return saved
    if payload.base_revision is not None and payload.base_revision != workflow.revision:
        raise WorkflowVersionConflict(
            f"Workflow revision conflict: expected {payload.base_revision}, current {workflow.revision}"
        )
    session.execute(delete(WorkflowEdge).where(WorkflowEdge.workflow_id == workflow.id))
    session.execute(delete(WorkflowNode).where(WorkflowNode.workflow_id == workflow.id))
    session.flush()

    workflow.schema_version = payload.schema_version
    workflow.viewport = payload.viewport.model_dump()
    workflow.revision += 1
    workflow.last_operation_id = payload.operation_id
    workflow.last_operation_at = datetime.now(UTC)
    workflow.updated_at = datetime.now(UTC)
    for node in payload.nodes:
        session.add(
            WorkflowNode(
                id=node.id,
                workflow_id=workflow.id,
                type=node.type,
                version=node.version,
                position_x=node.position.x,
                position_y=node.position.y,
                config=node.config,
            )
        )
    for edge in payload.edges:
        session.add(
            WorkflowEdge(
                id=edge.id,
                workflow_id=workflow.id,
                source=edge.source,
                target=edge.target,
                source_handle=edge.source_handle,
                target_handle=edge.target_handle,
            )
        )
    session.commit()
    session.expire_all()
    saved = load_workflow(session, workflow.shot_id)
    if saved is None:
        raise RuntimeError("Workflow save failed")
    return saved
