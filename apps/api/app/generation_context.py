import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db_models import Asset, Generation, GenerationStatus, StoredUpload, User, WorkflowNode
from .providers.base import GenerationContext
from .uploads import uploaded_image_data_url
from .workflows import load_workflow


def resolve_generation_contexts(
    session: Session,
    generation: Generation,
) -> tuple[GenerationContext, ...]:
    raw_source_ids = generation.parameters.get("context_source_node_ids", [])
    raw_uploads = generation.parameters.get("uploaded_assets", [])
    has_sources = isinstance(raw_source_ids, list) and bool(raw_source_ids)
    has_uploads = isinstance(raw_uploads, list) and bool(raw_uploads)
    if not has_sources and not has_uploads:
        return ()

    contexts: list[GenerationContext] = []
    seen: set[str] = set()
    if has_sources:
        workflow = load_workflow(session, generation.shot_id)
        nodes = {str(node.id): node for node in workflow.nodes} if workflow is not None else {}
        history = list(
            session.scalars(
                select(Generation)
                .where(
                    Generation.shot_id == generation.shot_id,
                    Generation.status == GenerationStatus.SUCCEEDED,
                    Generation.id != generation.id,
                )
                .order_by(Generation.created_at.desc())
            )
        )
        latest_by_node: dict[str, Generation] = {}
        latest_image: Generation | None = None
        for item in history:
            if item.node_id and item.node_id not in latest_by_node:
                latest_by_node[item.node_id] = item
            if latest_image is None and item.kind == "image" and item.output_url:
                latest_image = item

        for raw_source_id in raw_source_ids[:12]:
            source_id = str(raw_source_id)
            if source_id in seen or source_id not in nodes:
                continue
            seen.add(source_id)
            context = _node_context(nodes[source_id], generation, latest_by_node, latest_image)
            if context is not None:
                contexts.append(context)

    if has_uploads:
        settings = get_settings()
        for item in raw_uploads[:8]:
            if not isinstance(item, dict):
                continue
            raw_asset_id = item.get("asset_id")
            registered_asset: Asset | None = None
            if raw_asset_id:
                try:
                    registered_asset = session.get(Asset, uuid.UUID(str(raw_asset_id)))
                except ValueError:
                    registered_asset = None
            try:
                upload_id = uuid.UUID(str(item.get("id", "")))
            except ValueError:
                upload_id = registered_asset.source_upload_id if registered_asset is not None else None
            if registered_asset is not None:
                upload_id = registered_asset.source_upload_id
            if generation.shot is not None:
                project_owner_id = generation.shot.project.user_id
                if (
                    registered_asset is not None
                    and registered_asset.project_id is not None
                    and registered_asset.project_id != generation.shot.project_id
                ):
                    continue
                asset_owner_id = registered_asset.user_id if registered_asset is not None else None
                upload_owner_id = session.scalar(
                    select(StoredUpload.user_id).where(StoredUpload.id == upload_id)
                ) if upload_id is not None else None
                reference_owner_id = asset_owner_id or upload_owner_id
                if reference_owner_id != project_owner_id:
                    first_user_id = session.scalar(
                        select(User.id).order_by(User.created_at, User.id).limit(1)
                    )
                    if reference_owner_id is not None or project_owner_id != first_user_id:
                        continue
            # Keep this identifier aligned with the frontend reference binding.
            # Uploaded assets use their upload id; generated assets use their
            # registry id in the same `upload:*` namespace.
            node_id = f"upload:{item.get('id') or upload_id}"
            if node_id in seen:
                continue
            image_url = (
                uploaded_image_data_url(settings, upload_id)
                if upload_id is not None
                else registered_asset.url if registered_asset is not None and registered_asset.kind == "image" else None
            )
            if image_url is None:
                continue
            seen.add(node_id)
            contexts.append(
                GenerationContext(
                    node_id=node_id,
                    title=str(item.get("filename") or "上传图片")[:160],
                    kind="image",
                    image_url=image_url,
                )
            )
    return tuple(contexts)


def _node_context(
    node: WorkflowNode,
    generation: Generation,
    latest_by_node: dict[str, Generation],
    latest_image: Generation | None,
) -> GenerationContext | None:
    source_id = str(node.id)
    config = node.config or {}
    title = str(config.get("title") or _default_title(node.type))
    source_generation = latest_by_node.get(source_id)

    if source_generation is not None and source_generation.output_url:
        return GenerationContext(
            node_id=source_id,
            title=title,
            kind="image",
            image_url=source_generation.output_url,
        )
    if node.type == "review" and latest_image is not None and latest_image.output_url:
        return GenerationContext(
            node_id=source_id,
            title="图片",
            kind="image",
            image_url=latest_image.output_url,
        )

    text = _node_text(node, generation, source_generation)
    if not text:
        return None
    return GenerationContext(node_id=source_id, title=title, kind="text", text=text)


def _node_text(
    node: WorkflowNode,
    generation: Generation,
    source_generation: Generation | None,
) -> str:
    config = node.config or {}
    if source_generation is not None and source_generation.output_text:
        return source_generation.output_text.strip()
    if node.type == "shot":
        return str(config.get("text_content") or generation.shot.description or "").strip()
    if node.type == "prompt":
        return str(generation.shot.visual_prompt or config.get("detail") or "").strip()
    return str(
        config.get("text_content")
        or config.get("prompt")
        or config.get("detail")
        or ""
    ).strip()


def _default_title(node_type: str) -> str:
    return {
        "shot": "文本",
        "prompt": "提示词",
        "generator": "生成结果",
        "review": "图片",
    }.get(node_type, node_type)
