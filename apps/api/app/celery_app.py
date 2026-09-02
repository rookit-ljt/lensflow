from celery import Celery

from .config import get_settings

settings = get_settings()
celery_app = Celery(
    "ai-video-studio",
    broker=settings.rabbitmq_url,
    include=["app.tasks"],
)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_store_eager_result=False,
    timezone="Asia/Shanghai",
)
