import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .agent_skills import get_skill
from .db_models import Asset, Generation, Project, Shot, Workflow


def build_agent_context(
    session: Session,
    *,
    project_id: uuid.UUID,
    shot_id: uuid.UUID | None,
    selected_node_ids: list[str],
    mentions: list[dict[str, object]] | None = None,
    skill_id: str | None = None,
    skill_prompt: str | None = None,
) -> str:
    project = session.get(Project, project_id)
    if project is None:
        raise RuntimeError("Agent 项目上下文不存在")

    lines = [
        f"项目：{project.name}",
        f"项目说明：{project.description or '未填写'}",
    ]
    skill = get_skill(skill_id)
    if skill is not None or skill_prompt:
        lines.extend([
            "",
            f"当前启用 Skill：{skill['name'] if skill else skill_id or '自定义 Skill'}",
            f"Skill 目标：{skill['description'] if skill else '按用户提供的创作规则工作'}",
            f"Skill 运行规则：{skill_prompt or skill['instruction']}",
            (
                "Skill 可以根据用户 Prompt 请求创建或更新节点，并把生成 Prompt 交给图片/视频模型流程；"
                "任何画布修改和模型调用仍需遵循现有计划、审批和任务状态流程。"
            ),
        ])
    assets = list(
        session.scalars(
            select(Asset)
            .where(Asset.project_id == project_id)
            .order_by(Asset.created_at.desc())
            .limit(80)
        )
    )
    lines.append(
        "项目资产目录："
        + (
            "；".join(
                f"{asset.id} | {asset.filename} | {asset.kind} | {asset.role}"
                for asset in assets
            )
            or "暂无资产"
        )
    )
    explicit_mentions = mentions or []
    if explicit_mentions:
        lines.extend(["", "用户显式引用（优先使用这些对象，不要仅凭名称猜测）："])
        workflow_for_mentions = None
        if shot_id is not None:
            workflow_for_mentions = session.scalar(
                select(Workflow)
                .where(Workflow.shot_id == shot_id)
                .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
            )
        for mention in explicit_mentions:
            mention_type = str(mention.get("type") or "")
            mention_id = str(mention.get("id") or "")
            mention_label = str(mention.get("label") or mention_id)
            if mention_type == "asset":
                try:
                    asset = session.get(Asset, uuid.UUID(mention_id))
                except ValueError:
                    asset = None
                if asset is not None and asset.project_id == project_id:
                    lines.append(
                        f"- 资产 @{mention_label}: {asset.id} | {asset.filename} | {asset.kind} | {asset.role} | URL {asset.url}"
                    )
                else:
                    lines.append(f"- 资产 @{mention_label}: 未找到或不属于当前项目")
            elif mention_type == "node":
                node = next(
                    (item for item in (workflow_for_mentions.nodes if workflow_for_mentions else [])
                     if str(item.id) == mention_id),
                    None,
                )
                if node is not None:
                    config = json.dumps(node.config, ensure_ascii=False, default=str)
                    if len(config) > 2_000:
                        config = f"{config[:2_000]}…"
                    lines.append(f"- 节点 @{mention_label}: {node.id} | {node.type} | {config}")
                else:
                    lines.append(f"- 节点 @{mention_label}: 当前镜头中未找到")
            elif mention_type == "shot":
                try:
                    mentioned_shot = session.get(Shot, uuid.UUID(mention_id))
                except ValueError:
                    mentioned_shot = None
                if mentioned_shot is not None and mentioned_shot.project_id == project_id:
                    lines.append(f"- 镜头 @{mention_label}: {mentioned_shot.id} | {mentioned_shot.title}")
                else:
                    lines.append(f"- 镜头 @{mention_label}: 未找到或不属于当前项目")
            elif mention_type == "generation":
                try:
                    generation = session.get(Generation, uuid.UUID(mention_id))
                except ValueError:
                    generation = None
                generation_shot = session.get(Shot, generation.shot_id) if generation else None
                if generation is not None and generation_shot is not None and generation_shot.project_id == project_id:
                    lines.append(
                        f"- 生成结果 @{mention_label}: {generation.id} | {generation.kind} | {generation.status.value} | {generation.output_url or '暂无输出'}"
                    )
                else:
                    lines.append(f"- 生成结果 @{mention_label}: 未找到或不属于当前项目")
    shots = list(
        session.scalars(
            select(Shot).where(Shot.project_id == project_id).order_by(Shot.sequence_number)
        )
    )
    lines.append(
        "镜头目录："
        + ("；".join(f"{shot.sequence_number}. {shot.title}" for shot in shots) or "暂无镜头")
    )
    if shot_id is None:
        lines.append("当前没有选中镜头。")
        return "\n".join(lines)

    shot = session.get(Shot, shot_id)
    if shot is None or shot.project_id != project_id:
        raise RuntimeError("Agent 镜头上下文不存在或不属于当前项目")
    lines.extend(
        [
            "",
            f"当前镜头：{shot.sequence_number}. {shot.title}",
            f"镜头描述：{shot.description or '未填写'}",
            f"镜头提示词：{shot.visual_prompt or '未填写'}",
            f"镜头时长：{shot.duration_seconds} 秒",
            f"镜头状态：{shot.status.value}",
        ]
    )

    workflow = session.scalar(
        select(Workflow)
        .where(Workflow.shot_id == shot_id)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
    )
    if workflow is None:
        lines.append("画布：尚未创建工作流。")
    else:
        selected = {str(node_id) for node_id in selected_node_ids}
        nodes_by_id = {str(node.id): node for node in workflow.nodes}
        lines.append(
            f"画布概况：{len(workflow.nodes)} 个节点，{len(workflow.edges)} 条连线，"
            f"schema {workflow.schema_version}。"
        )
        if selected:
            for node_id in selected:
                node = nodes_by_id.get(node_id)
                if node is None:
                    lines.append(f"选中节点 {node_id}：当前画布中未找到。")
                    continue
                config = json.dumps(node.config, ensure_ascii=False, default=str)
                if len(config) > 4_000:
                    config = f"{config[:4_000]}…"
                upstream = [
                    str(edge.source) for edge in workflow.edges if str(edge.target) == node_id
                ]
                downstream = [
                    str(edge.target) for edge in workflow.edges if str(edge.source) == node_id
                ]
                lines.extend(
                    [
                        "",
                        f"选中节点：{node_id}",
                        f"节点类型：{node.type}",
                        f"节点配置：{config}",
                        f"上游节点：{', '.join(upstream) or '无'}",
                        f"下游节点：{', '.join(downstream) or '无'}",
                    ]
                )

    generation = session.scalar(
        select(Generation)
        .where(Generation.shot_id == shot_id)
        .order_by(Generation.created_at.desc())
    )
    if generation is not None:
        lines.extend(
            [
                "",
                "最近生成任务：",
                f"- 类型/模型：{generation.kind} / {generation.model or '默认模型'}",
                f"- Provider/状态：{generation.provider} / {generation.status.value}",
                f"- 所属节点：{generation.node_id or '镜头级'}",
                f"- 错误：{generation.error or '无'}",
            ]
        )
        if generation.output_text:
            lines.append(f"- 文本结果：{generation.output_text[:3_000]}")
        if generation.output_url:
            lines.append(f"- 结果地址：{generation.output_url}")

    lines.append(
        "\n权限：普通对话只读；明确的画布或资产操作会生成受控计划，必须经过用户批准后才会修改画布。"
    )
    return "\n".join(lines)
