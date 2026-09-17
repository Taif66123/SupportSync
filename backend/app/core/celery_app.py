"""The Celery application (M4): one worker on the Redis broker.

Redis already runs for the notification bridge, so the broker is free
infrastructure (ADR 0006). Publishing is deliberately fire-and-forget: one
attempt, short connect timeout, no retry policy — a down broker must never
block or fail an HTTP request (the same fail-open decision as everything
else Redis here; the caller logs and moves on).
"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "supportsync",
    broker=settings.redis_url,
    include=["app.modules.emails.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Fire-and-forget publishing: one attempt, fail fast, no retry loop.
    task_publish_retry=False,
    broker_connection_timeout=1.0,
    broker_transport_options={"socket_connect_timeout": 1.0},
)
