from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .agent_service import execute_agent_run
from .config import get_settings
from .credits_service import refund_credits
from .database import (
    Base,
    SessionLocal,
    engine,
    ensure_auth_columns,
    ensure_generation_columns,
    ensure_workflow_columns,
)
from .db_models import Generation, GenerationStatus, ShotStatus
from .google_identity import verify_google_id_token
from .routers import (
    agent_router,
    assets_router,
    auth_router,
    credits_router,
    generations_router,
    projects_router,
    settings_router,
    workflows_router,
)
from .video_frames import extract_last_video_frame

settings = get_settings()


def _fail_interrupted_generations() -> None:
    """Fail generations left non-terminal by a previous process death.

    Eager tasks run inside this API process: a restart (--reload, Ctrl-C or a
    crash) kills in-flight provider calls and orphans queued/running rows.
    The frontend polls those rows forever because they never reach a terminal
    state. Worker mode is skipped: a live worker may still own those tasks.
    """
    if not settings.celery_task_always_eager:
        return
    with SessionLocal() as session:
        orphans = list(
            session.scalars(
                select(Generation).where(
                    Generation.status.in_([GenerationStatus.QUEUED, GenerationStatus.RUNNING])
                )
            )
        )
        if not orphans:
            return
        for generation in orphans:
            generation.status = GenerationStatus.FAILED
            generation.error = "服务重启导致生成中断，请点击重试"
            if (
                generation.cost_credits > 0
                and generation.shot is not None
                and generation.shot.project.user_id is not None
            ):
                refund_credits(
                    session=session,
                    user_id=generation.shot.project.user_id,
                    amount=generation.cost_credits,
                    biz_type=f"{generation.kind}_generation",
                    biz_id=str(generation.id),
                    description="服务重启生成中断，预扣积分已自动返还",
                )
            if generation.shot is not None:
                generation.shot.status = ShotStatus.READY
        session.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_generation_columns()
    ensure_auth_columns()
    ensure_workflow_columns()
    _fail_interrupted_generations()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Project, shot and workflow control plane for AI Video Studio.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载各领域业务路由
app.include_router(settings_router)
app.include_router(auth_router)
app.include_router(credits_router)
app.include_router(assets_router)
app.include_router(projects_router)
app.include_router(workflows_router)
app.include_router(generations_router)
app.include_router(agent_router)

__all__ = [
    "_fail_interrupted_generations",
    "app",
    "execute_agent_run",
    "extract_last_video_frame",
    "settings",
    "verify_google_id_token",
]
