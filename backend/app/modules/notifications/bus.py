"""The Redis bridge between workers (M3 Phase B).

Design (per the codebase-design skill): Redis is a **bridge, not a replacement**.
The in-process hub remains this worker's fan-out; pub/sub carries events *across*
workers so every worker's local hub hears about everything. Callers of
notifications.service.notify() never learn Redis exists — the emit contract is
unchanged from Phase A, and the SSE stream endpoint doesn't change either.

The pub/sub frame is an internal envelope (schemas.NotificationEnvelope):
recipients ride with the notification because recipients are *subscriptions*
resolved once at emit time — the listener is a dumb pump with no DB access.
Each envelope carries the emitting worker's `origin`; listeners drop their own
frames (the local hub already has them — otherwise every event would double).

The emit path is sync (it runs inside SQLAlchemy's after_commit hook, possibly in
a worker thread); the Redis publish is async. The bridge captures the main loop
at lifespan startup and schedules publishes onto it fire-and-forget. Without a
captured loop (unit tests, plain script) the bridge is a no-op passthrough:
purely local delivery, no Redis dependency.

Fail-open: any Redis failure degrades to local delivery and is logged once per
outage, never per event. Failures also trip the shared Redis breaker
(app.core.redis) so a down Redis costs one dial per cooldown, not one per event.
"""

import asyncio
import contextlib
import json
import logging
import uuid

from app.core import redis as redis_module
from app.core.redis import CHANNEL, redis_ok, trip_breaker
from app.modules.notifications.hub import hub
from app.modules.notifications.schemas import Notification, NotificationEnvelope

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_loop: asyncio.AbstractEventLoop | None = None
_origin: str = uuid.uuid4().hex  # this process's identity on the channel
_logged_outage = False


def publish(recipients: frozenset[int] | set[int], notification: Notification) -> None:
    """Deliver one committed notification: local hub now, other workers via Redis.

    Safe to call from any thread. Without a running app lifespan (tests) this is
    exactly Phase A's local fan-out.
    """
    hub.push_many(recipients, notification)
    if _loop is None or _loop.is_closed():
        return
    if not redis_ok():
        return  # breaker tripped: remote fan-out paused, local delivery already done
    envelope = NotificationEnvelope(recipients=sorted(recipients), origin=_origin, notification=notification)
    future = asyncio.run_coroutine_threadsafe(_publish_remote(envelope), _loop)
    future.add_done_callback(_log_publish_failure)


async def _publish_remote(envelope: NotificationEnvelope) -> None:
    try:
        # Via the module attribute so test doubles can patch app.core.redis.get_redis_client.
        client = redis_module.get_redis_client()
        await client.publish(CHANNEL, envelope.model_dump_json())
    except Exception:  # noqa: BLE001 — fail open: local delivery already happened
        trip_breaker()
        _log_outage()


def _log_publish_failure(future: asyncio.Future) -> None:
    with contextlib.suppress(asyncio.CancelledError):
        if future.exception() is not None:
            trip_breaker()
            _log_outage()


async def start() -> None:
    """Capture the main loop and spawn this worker's listener task (app lifespan)."""
    global _task, _loop, _logged_outage
    _loop = asyncio.get_running_loop()
    _logged_outage = False
    if _task is None or _task.done():
        _task = asyncio.create_task(_listen())


async def stop() -> None:
    global _task, _loop
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
    _loop = None


async def _listen() -> None:
    """Pull cross-worker envelopes off the channel into this worker's local hub.

    Runs for the whole process lifetime. The shared breaker gates the dial: a down
    Redis costs one subscribe attempt per cooldown (a sleeping task, not a spin),
    and recovery self-heals on the next probe.
    """
    pubsub = None
    try:
        while True:
            if not redis_ok():
                await asyncio.sleep(redis_module.BREAKER_COOLDOWN_SECONDS)
                continue
            try:
                pubsub = await redis_module.start_listener()
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        envelope = NotificationEnvelope.model_validate(json.loads(message["data"]))
                    except Exception:  # noqa: BLE001 — a malformed frame must not kill the listener
                        logger.warning("discarding malformed notification frame on %s", CHANNEL)
                        continue
                    if envelope.origin == _origin:
                        continue  # our own publish — the local hub already delivered it
                    hub.push_many(envelope.recipients, envelope.notification)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — fail open: the process stays healthy without Redis
                trip_breaker()
                logger.warning("notification listener stopped (Redis unreachable?) — local delivery only")
            finally:
                await redis_module.stop_listener(pubsub)
                pubsub = None
            # Stream ended without an error (no breaker trip): pause briefly so an
            # odd clean-exit can't become a tight resubscribe loop. Real failures
            # are gated above by the breaker's cooldown instead.
            await asyncio.sleep(0.1)
    except asyncio.CancelledError:
        pass
    finally:
        await redis_module.stop_listener(pubsub)


def _log_outage() -> None:
    global _logged_outage
    if not _logged_outage:
        logger.warning("Redis unreachable — notification fan-out degraded to local delivery (fail-open)")
        _logged_outage = True
