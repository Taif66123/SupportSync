"""The single Redis connection surface for the whole app.

Everything Redis-shaped (pub/sub bus, rate limiting, later: background tasks)
goes through this module's client, so config, key naming, and failure policy
live in exactly one place.

Failure policy is **fail open** (user decision): when Redis is unreachable,
pub/sub fan-out degrades to local delivery and rate limiting skips its check —
availability over strictness, both logged once per outage, never per request.

Fail open is also made *cheap* by a tiny circuit breaker: the first failure trips
it for a cooldown, so a down Redis costs one real dial (one connect timeout) and
then callers skip Redis instantly instead of paying the dial on every request.
"""

import contextlib
import time
from collections.abc import AsyncIterator
from functools import lru_cache

import redis.asyncio as redis
from redis.asyncio.client import PubSub as AsyncPubSub

from app.core.config import settings

CHANNEL = "supportsync:notifications"

KEY_PREFIX = "supportsync:"


def redis_key(*parts: str) -> str:
    """Namespaced key builder — every Redis key the app touches starts here."""
    return KEY_PREFIX + ":".join(parts)


@lru_cache
def get_redis_client() -> redis.Redis:
    """The process-wide async client. Created lazily; connecting is deferred until
    the first command (redis-py default), so a cold Redis never blocks startup —
    which is exactly what fail-open wants."""
    return redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
        health_check_interval=30,
    )


async def start_listener() -> AsyncPubSub:
    """Subscribe to the app channel; returns the pubsub object to pull messages from."""
    client = get_redis_client()
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe(CHANNEL)
    return pubsub


async def stop_listener(pubsub: AsyncPubSub | None) -> None:
    """Best-effort teardown — cleanup must never mask the failure that brought us
    here or kill the listener that calls it from its own finally block."""
    if pubsub is None:
        return
    with contextlib.suppress(Exception):
        await pubsub.unsubscribe(CHANNEL)
    with contextlib.suppress(Exception):
        await pubsub.aclose()


# --- The failure breaker ---

BREAKER_COOLDOWN_SECONDS = 30.0


class _Breaker:
    """Open (tripped) = callers must skip Redis and fail open; closed = dial.

    After the cooldown one probe is allowed through: Redis back ⇒ healthy again,
    still down ⇒ it trips on that probe's failure. Deliberately not a half-open
    state machine with counters — one timestamp is the whole mechanism.
    """

    __slots__ = ("_tripped_at",)

    def __init__(self) -> None:
        self._tripped_at: float | None = None

    @property
    def is_open(self) -> bool:
        return self._tripped_at is not None and (
            time.monotonic() - self._tripped_at
        ) < BREAKER_COOLDOWN_SECONDS

    def trip(self) -> None:
        self._tripped_at = time.monotonic()

    def reset(self) -> None:
        self._tripped_at = None


_breaker = _Breaker()


def redis_ok() -> bool:
    """True while Redis is considered healthy. False = skip Redis entirely (no
dial, no wait) and fail open, until the cooldown expires and a probe dials."""
    return not _breaker.is_open


def trip_breaker() -> None:
    """Record a Redis failure: fail open instantly for the cooldown window."""
    _breaker.trip()


def reset_breaker() -> None:
    """Test seam: treat Redis as healthy again (a fresh process starts healthy)."""
    _breaker.reset()


__all__ = [
    "CHANNEL",
    "AsyncPubSub",
    "get_redis_client",
    "redis_key",
    "redis_ok",
    "reset_breaker",
    "start_listener",
    "stop_listener",
    "trip_breaker",
]
