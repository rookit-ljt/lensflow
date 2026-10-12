import uuid

from sqlalchemy import select

from .celery_app import celery_app
from .config import get_settings
from .credits_service import refund_credits, settle_credits
from .database import SessionLocal
from .db_models import Asset, Generation, GenerationStatus, ShotStatus
from .generation_context import resolve_generation_contexts
from .providers import (
    ArkSeedreamImageProvider,
    GoogleGenAIImageProvider,
    LocalH3VideoProvider,
    MockImageProvider,
    MockTextProvider,
    MockVideoProvider,
    OpenAICompatibleImageProvider,
    OpenAICompatibleTextProvider,
    QwenImageProvider,
    QwenTextProvider,
)
from .providers.base import GenerationRequest


@celery_app.task(name="ai-video-studio.generate_shot")
def generate_shot(generation_id: str) -> None:
    with SessionLocal() as session:
        generation = session.get(Generation, uuid.UUID(generation_id))
        if generation is None:
            return

        # A queued task can be cancelled before the worker starts. Keep the
        # terminal state written by the cancel endpoint instead of reviving it.
        if generation.status != GenerationStatus.QUEUED:
            return

        shot = generation.shot
        generation.status = GenerationStatus.RUNNING
        generation.progress = 15
        shot.status = ShotStatus.GENERATING
        session.commit()

        try:
            settings = get_settings()
            contexts = resolve_generation_contexts(session, generation)
            if (
                generation.kind == "image"
                and generation.provider == "qwen"
                and any(context.kind == "image" and context.image_url for context in contexts)
                and generation.model not in QwenImageProvider.multimodal_models
            ):
                generation.model = settings.qwen_image_edit_model
            if generation.kind == "text":
                if generation.provider == "mock":
                    provider = MockTextProvider()
                elif generation.provider == "qwen":
                    provider = QwenTextProvider(settings)
                else:
                    provider = OpenAICompatibleTextProvider(settings)
            elif generation.kind == "image":
                if generation.provider == "mock":
                    provider = MockImageProvider()
                elif generation.provider == "ark_seedream":
                    provider = ArkSeedreamImageProvider(settings)
                elif generation.provider == "google_genai":
                    provider = GoogleGenAIImageProvider(settings)
                elif generation.provider == "qwen":
                    provider = QwenImageProvider(settings)
                else:
                    provider = OpenAICompatibleImageProvider(settings)
            else:
                provider = (
                    LocalH3VideoProvider(settings)
                    if generation.provider == "local_h3"
                    else MockVideoProvider()
                )
            result = provider.generate(
                GenerationRequest(
                    generation_id=str(generation.id),
                    shot_id=str(shot.id),
                    title=shot.title,
                    prompt=generation.input_text or shot.visual_prompt,
                    duration_seconds=shot.duration_seconds,
                    model=generation.model,
                    temperature=generation.temperature,
                    max_tokens=generation.max_tokens,
                    parameters=generation.parameters,
                    contexts=contexts,
                )
            )
            session.refresh(generation)
            # Providers may not support hard cancellation. The API marks the
            # generation cancelled while the provider call is in flight; once
            # it returns, discard the result and keep the terminal state.
            if (generation.parameters or {}).get("cancel_requested"):
                shot.status = ShotStatus.READY
                if generation.cost_credits > 0 and shot.project.user_id is not None:
                    refund_credits(
                        session=session,
                        user_id=shot.project.user_id,
                        amount=generation.cost_credits,
                        biz_type=f"{generation.kind}_generation",
                        biz_id=str(generation.id),
                        description=f"{generation.kind} 任务已取消，积分原路返还",
                    )
                session.commit()
                return
            generation.status = GenerationStatus.SUCCEEDED
            generation.progress = 100
            generation.provider_job_id = result.provider_job_id
            generation.output_url = result.output_url
            generation.output_text = result.output_text
            if generation.cost_credits > 0 and shot.project.user_id is not None:
                settle_credits(
                    session=session,
                    user_id=shot.project.user_id,
                    amount=generation.cost_credits,
                    biz_type=f"{generation.kind}_generation",
                    biz_id=str(generation.id),
                    description=f"{generation.kind} 生成成功扣除积分",
                )
            if result.output_url and generation.kind in {"image", "video"}:
                asset = session.scalar(
                    select(Asset).where(
                        Asset.source_generation_id == generation.id,
                        Asset.role == "generation",
                    )
                )
                values = {
                    "user_id": shot.project.user_id,
                    "project_id": shot.project_id,
                    "shot_id": shot.id,
                    "source_generation_id": generation.id,
                    "kind": generation.kind,
                    "role": "generation",
                    "filename": f"ai-video-studio-{generation.kind}-{generation.id.hex[:8]}",
                    "content_type": "video/mp4" if generation.kind == "video" else "image/png",
                    "size": 0,
                    "url": result.output_url,
                    "metadata_json": {
                        "provider": generation.provider,
                        "model": generation.model,
                    },
                }
                if asset is None and shot.project.user_id is not None:
                    session.add(Asset(**values))
                elif asset is not None:
                    for key, value in values.items():
                        setattr(asset, key, value)
            shot.status = (
                ShotStatus.REVIEW
                if generation.kind in {"image", "video"}
                else ShotStatus.READY
            )
        except Exception as exc:  # noqa: BLE001 - task boundary persists provider failures
            session.refresh(generation)
            if (generation.parameters or {}).get("cancel_requested"):
                shot.status = ShotStatus.READY
                if generation.cost_credits > 0 and shot.project.user_id is not None:
                    refund_credits(
                        session=session,
                        user_id=shot.project.user_id,
                        amount=generation.cost_credits,
                        biz_type=f"{generation.kind}_generation",
                        biz_id=str(generation.id),
                        description=f"{generation.kind} 任务已取消，积分原路返还",
                    )
                session.commit()
                return
            generation.status = GenerationStatus.FAILED
            generation.error = str(exc)
            shot.status = ShotStatus.READY
            if generation.cost_credits > 0 and shot.project.user_id is not None:
                refund_credits(
                    session=session,
                    user_id=shot.project.user_id,
                    amount=generation.cost_credits,
                    biz_type=f"{generation.kind}_generation",
                    biz_id=str(generation.id),
                    description=f"{generation.kind} 生成失败，积分原路返还",
                )
        session.commit()
