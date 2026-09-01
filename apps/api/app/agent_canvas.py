import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db_models import AgentApproval, Asset, Shot, Workflow, WorkflowEdge, WorkflowNode
from .schemas import CanvasPatch
from .workflows import load_workflow

ALLOWED_CONFIG_FIELDS = {
    "aspect_ratio",
    "count",
    "detail",
    "duration_seconds",
    "mode",
    "model",
    "negative_prompt",
    "output_length",
    "panorama",
    "prompt",
    "provider",
    "quality",
    "resolution",
    "seed",
    "temperature",
    "text_content",
    "title",
    "camera_motion",
    "compiled_prompt",
    "first_frame_node_id",
    "height",
    "intent_prompt",
    "last_frame_node_id",
    "preset",
    "prompt_schema",
    "reference_bindings",
    "source_generation_id",
    "source_image_url",
    "steps",
    "uploaded_assets",
    "video_reference_mode",
    "width",
}
ALLOWED_MODES = {None, "text", "image", "video", "audio"}


class CanvasPatchError(RuntimeError):
    pass


class CanvasVersionConflict(CanvasPatchError):
    pass


def is_canvas_operation_request(
    message: str,
    selected_node_ids: list[str],
    messages: list[dict[str, str]] | None = None,
) -> bool:
    """Require explicit action language so ordinary design discussion remains chat."""

    normalized = message.strip().lower()
    if any(word in normalized for word in ("怎么", "如何", "为什么", "能否", "可以吗", "分析", "建议")):
        return False
    create = "节点" in normalized and any(
        word in normalized for word in ("新增", "新建", "创建", "添加", "插入", "生成")
    )
    connect = bool(selected_node_ids) and any(
        word in normalized for word in ("连接", "连线", "接到", "连到")
    )
    update = bool(selected_node_ids) and any(
        word in normalized for word in ("修改", "改成", "设置", "替换", "优化", "重写")
    ) and any(word in normalized for word in ("节点", "提示词", "prompt", "模型", "比例", "分辨率"))
    asset_bind = bool(selected_node_ids) and any(
        word in normalized for word in ("资产", "素材", "参考图", "首帧", "尾帧")
    ) and any(
        word in normalized for word in ("绑定", "引用", "使用", "设置", "设为", "设成", "添加", "作为")
    )
    if create or connect or update or asset_bind:
        return True

    history = messages or []
    previous_assistant = next(
        (
            item.get("content", "")
            for item in reversed(history[:-1])
            if item.get("role") == "assistant"
        ),
        "",
    )
    if not previous_assistant:
        return False
    has_pending_canvas_proposal = any(
        marker in previous_assistant
        for marker in (
            "画布更新计划",
            "画布修改计划",
            "更新画布",
            "修改画布",
            "审批卡片",
            "新增节点",
            "创建节点",
        )
    )
    if not has_pending_canvas_proposal:
        return False
    compact = "".join(normalized.split())
    explicit_followup = any(
        marker in compact
        for marker in (
            "执行刚才",
            "按刚才",
            "应用计划",
            "应用这个计划",
            "就这样改",
            "生成审批",
            "确认执行",
        )
    )
    short_confirmation = compact in {
        "继续",
        "确认",
        "同意",
        "执行",
        "批准",
        "可以",
        "好的",
        "好",
        "1",
        "2",
        "3",
    }
    return explicit_followup or short_confirmation


def compile_canvas_patch(
    actions: list[dict[str, Any]],
    *,
    workflow: Workflow,
    selected_node_ids: list[str],
    base_canvas_version: str | None,
    base_revision: int | None = None,
    canvas_center: dict[str, Any] | None = None,
) -> CanvasPatch:
    if not actions:
        raise CanvasPatchError("Agent 没有生成可执行的画布变更，请选中节点并明确要修改的内容")
    if len(actions) > 10:
        raise CanvasPatchError("单次画布变更不能超过 10 项")
    if any(not isinstance(action, dict) for action in actions):
        raise CanvasPatchError("Agent 计划中包含无效动作")

    existing = {str(node.id): node for node in workflow.nodes}
    selected_id = selected_node_ids[0] if selected_node_ids else None
    if selected_id is not None and selected_id not in existing:
        raise CanvasPatchError("选中的节点已不存在，请刷新画布后重试")

    priority = {"create_node": 0, "update_node_config": 1, "bind_asset": 2, "connect_nodes": 3}
    actions = sorted(actions, key=lambda item: priority.get(str(item.get("type")), 9))
    temp_nodes: dict[str, uuid.UUID] = {}
    for index, action in enumerate(actions, start=1):
        if action.get("type") != "create_node":
            continue
        temp_id = str(action.get("temp_id") or f"node_{index}")
        if temp_id in temp_nodes:
            raise CanvasPatchError("Agent 计划中存在重复的临时节点")
        temp_nodes[temp_id] = uuid.uuid4()
    operations: list[dict[str, Any]] = []
    if (
        canvas_center
        and isinstance(canvas_center.get("x"), (int, float))
        and isinstance(canvas_center.get("y"), (int, float))
    ):
        # Center coordinates are sent in React Flow's world space. Keep the
        # node body centered and stack additional nodes below it.
        next_x = float(canvas_center["x"]) - 145
        next_y = float(canvas_center["y"]) - 79
    else:
        next_x = max((node.position_x for node in workflow.nodes), default=0) + 390
        next_y = min((node.position_y for node in workflow.nodes), default=160)

    for index, action in enumerate(actions, start=1):
        action_type = action.get("type")
        description = str(action.get("description") or "更新画布")[:240]
        operation_id = f"op-{index}"

        if action_type == "update_node_config":
            if action.get("target") != "selected" or selected_id is None:
                raise CanvasPatchError("更新节点配置前，请先在画布中选中一个节点")
            target = existing[selected_id]
            raw_patch = action.get("config_patch")
            if not isinstance(raw_patch, dict) or not raw_patch:
                raise CanvasPatchError("节点配置变更不能为空")
            config_patch = _safe_config(raw_patch)
            # The Agent speaks in terms of prompt/content. Normalize that
            # shorthand to the storage key used by fixed canvas nodes.
            if target.type == "shot" and "prompt" in config_patch:
                config_patch["text_content"] = config_patch.pop("prompt")
            elif target.type == "prompt" and "prompt" in config_patch:
                config_patch["detail"] = config_patch.pop("prompt")
            operations.append({
                "type": "update_node_config",
                "id": operation_id,
                "description": description,
                "node_id": selected_id,
                "config_patch": config_patch,
            })
            continue

        if action_type == "create_node":
            if action.get("node_type", "generator") != "generator":
                raise CanvasPatchError("P1 当前只允许新增生成节点")
            temp_id = str(action.get("temp_id") or f"node_{index}")
            mode = action.get("mode")
            if mode == "audio":
                raise CanvasPatchError("音频生成尚未接入，请先创建文本、图片或视频节点")
            if mode not in ALLOWED_MODES:
                raise CanvasPatchError("新节点包含不支持的生成类型")
            node_id = temp_nodes[temp_id]
            config = {
                "mode": mode,
                "prompt": str(action.get("prompt") or "")[:12_000],
                "aspect_ratio": "16:9",
                "resolution": "2K",
                "quality": "标准",
                "count": 1,
                "duration_seconds": 5,
                "panorama": False,
                "seed": -1,
            }
            operations.append({
                "type": "create_node",
                "id": operation_id,
                "description": description,
                "node_id": node_id,
                "node_type": "generator",
                "position": {"x": next_x, "y": next_y},
                "config": config,
            })
            next_y += 300
            continue

        if action_type == "connect_nodes":
            source = _resolve_endpoint(action.get("source"), selected_id, temp_nodes, existing)
            target = _resolve_endpoint(action.get("target"), selected_id, temp_nodes, existing)
            if source == target:
                raise CanvasPatchError("不能把节点连接到自身")
            all_edges = {(str(edge.source), str(edge.target)) for edge in workflow.edges}
            all_edges.update(
                (str(item["source"]), str(item["target"]))
                for item in operations
                if item["type"] == "connect_nodes"
            )
            if (str(source), str(target)) in all_edges:
                raise CanvasPatchError("画布中已存在这条连线")
            operations.append({
                "type": "connect_nodes",
                "id": operation_id,
                "description": description,
                "edge_id": uuid.uuid4(),
                "source": source,
                "target": target,
            })
            continue

        if action_type == "bind_asset":
            if action.get("target", "selected") != "selected" or selected_id is None:
                raise CanvasPatchError("绑定资产前，请先在画布中选中一个生成节点")
            role = str(action.get("role") or "reference")
            if role not in {"reference", "first_frame", "last_frame"}:
                raise CanvasPatchError("资产绑定位置只支持参考图、首帧或尾帧")
            try:
                asset_id = uuid.UUID(str(action.get("asset_id") or ""))
            except ValueError as exc:
                raise CanvasPatchError("资产引用 ID 无效") from exc
            target = existing[selected_id]
            if target.type != "generator":
                raise CanvasPatchError("资产只能绑定到生成节点")
            operations.append({
                "type": "bind_asset",
                "id": operation_id,
                "description": description,
                "node_id": uuid.UUID(selected_id),
                "asset_id": asset_id,
                "role": role,
            })
            continue

        raise CanvasPatchError(f"不支持的画布动作：{action_type}")

    return CanvasPatch.model_validate({
        "version": "1.0",
        "shot_id": workflow.shot_id,
        "base_canvas_version": base_canvas_version,
        "base_revision": base_revision,
        "operation_id": uuid.uuid4().hex,
        "operations": operations,
    })


def apply_canvas_patch(session: Session, approval: AgentApproval) -> Workflow:
    patch = CanvasPatch.model_validate(approval.patch)
    workflow = load_workflow(session, patch.shot_id)
    if workflow is None:
        raise CanvasPatchError("目标画布不存在")
    if workflow.last_operation_id == patch.operation_id:
        return workflow
    if patch.base_revision is not None:
        if patch.base_revision != workflow.revision:
            raise CanvasVersionConflict("画布在计划生成后已发生变化，请重新让 Agent 生成计划")
    elif not _same_canvas_version(patch.base_canvas_version, workflow.updated_at):
        raise CanvasVersionConflict("画布在计划生成后已发生变化，请重新让 Agent 生成计划")

    nodes = {node.id: node for node in workflow.nodes}
    for operation in patch.operations:
        if operation.type == "update_node_config":
            node = nodes.get(operation.node_id)
            if node is None:
                raise CanvasPatchError("待修改的节点已不存在")
            node.config = {**node.config, **_safe_config(operation.config_patch)}
        elif operation.type == "create_node":
            if operation.node_id in nodes:
                raise CanvasPatchError("待创建的节点 ID 已存在")
            node = WorkflowNode(
                id=operation.node_id,
                workflow_id=workflow.id,
                type="generator",
                version="1.0",
                position_x=operation.position.x,
                position_y=operation.position.y,
                config=_safe_config(operation.config),
            )
            session.add(node)
            nodes[node.id] = node
        elif operation.type == "connect_nodes":
            if operation.source not in nodes or operation.target not in nodes:
                raise CanvasPatchError("待连接的节点已不存在")
            session.add(WorkflowEdge(
                id=operation.edge_id,
                workflow_id=workflow.id,
                source=operation.source,
                target=operation.target,
            ))
        elif operation.type == "bind_asset":
            node = nodes.get(operation.node_id)
            if node is None or node.type != "generator":
                raise CanvasPatchError("待绑定资产的生成节点已不存在")
            asset = session.scalar(
                select(Asset).where(
                    Asset.id == operation.asset_id,
                    Asset.project_id == workflow_shot_project_id(session, workflow.shot_id),
                )
            )
            if asset is None:
                raise CanvasPatchError("资产不存在，或不属于当前项目")
            if asset.kind != "image":
                raise CanvasPatchError("当前只支持将图片资产绑定为参考图或首尾帧")
            mode = str((node.config or {}).get("mode") or "")
            if mode not in {"image", "video"}:
                raise CanvasPatchError("图片资产只能绑定到图片或视频生成节点")
            if operation.role in {"first_frame", "last_frame"} and mode != "video":
                raise CanvasPatchError("首帧和尾帧只能绑定到视频生成节点")
            current = node.config if isinstance(node.config, dict) else {}
            raw_assets = current.get("uploaded_assets", [])
            uploaded_assets = [item for item in raw_assets if isinstance(item, dict)] if isinstance(raw_assets, list) else []
            if not any(str(item.get("asset_id")) == str(asset.id) for item in uploaded_assets):
                if len(uploaded_assets) >= 8:
                    raise CanvasPatchError("一个节点最多绑定 8 个图片资产")
                uploaded_assets.append({
                    "id": str(asset.source_upload_id or asset.id),
                    "asset_id": str(asset.id),
                    "filename": asset.filename,
                    "kind": asset.kind,
                    "content_type": asset.content_type,
                    "size": asset.size,
                    "url": asset.url,
                })
            next_config = {**current, "uploaded_assets": uploaded_assets}
            if operation.role in {"first_frame", "last_frame"}:
                next_config["video_reference_mode"] = "keyframe"
                next_config[
                    "first_frame_node_id" if operation.role == "first_frame" else "last_frame_node_id"
                ] = f"upload:{asset.source_upload_id or asset.id}"
            node.config = next_config

    workflow.updated_at = datetime.now(UTC)
    workflow.revision += 1
    workflow.last_operation_id = patch.operation_id
    workflow.last_operation_at = datetime.now(UTC)
    session.flush()
    return workflow


def _safe_config(raw: dict[str, Any]) -> dict[str, Any]:
    unknown = set(raw) - ALLOWED_CONFIG_FIELDS
    if unknown:
        raise CanvasPatchError(f"节点配置包含未授权字段：{', '.join(sorted(unknown))}")
    safe: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        else:
            raise CanvasPatchError(f"节点配置字段 {key} 的值无效")
    if "mode" in safe and safe["mode"] not in ALLOWED_MODES:
        raise CanvasPatchError("节点生成类型无效")
    return safe


def workflow_shot_project_id(session: Session, shot_id: uuid.UUID) -> uuid.UUID:
    project_id = session.scalar(select(Shot.project_id).where(Shot.id == shot_id))
    if project_id is None:
        raise CanvasPatchError("目标镜头不存在")
    return project_id


def _resolve_endpoint(
    value: Any,
    selected_id: str | None,
    temp_nodes: dict[str, uuid.UUID],
    existing: dict[str, WorkflowNode],
) -> uuid.UUID:
    key = str(value or "")
    if key == "selected":
        if selected_id is None:
            raise CanvasPatchError("连接节点前，请先选中起始节点")
        return uuid.UUID(selected_id)
    if key in temp_nodes:
        return temp_nodes[key]
    if key in existing:
        return uuid.UUID(key)
    raise CanvasPatchError("连线引用了未知节点")


def _same_canvas_version(expected: str | None, actual: datetime) -> bool:
    if not expected:
        return False
    try:
        parsed = datetime.fromisoformat(expected)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if actual.tzinfo is None:
        actual = actual.replace(tzinfo=UTC)
    return abs((parsed.astimezone(UTC) - actual.astimezone(UTC)).total_seconds()) < 0.001
