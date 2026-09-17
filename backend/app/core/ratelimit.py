"""Fixed-window rate limiting over Redis (M3 Phase B) — the limit deferred since M1.

One tiny interface (`check`) is the whole module surface: callers name a bucket,
pass the identifier, and get True/False. Key shape, window math, and the failure
policy live here.

Failure policy is **fail open** (user decision, same as the bus): an unreachable
Redis skips the check and logs once per outage — availability over strictness.

Fixed window (INCR + EXPIRE on first hit) is deliberate: two commands, no Lua,
no sliding-window bookkeeping. At this project's scale the boundary burst a
fixed window allows is irrelevant.
"""

import logging

from app.core.redis import redis_key, redis_ok, trip_breaker

logger = logging.getLogger(__name__)

_logged_outage = False


async def check(bucket: str, identifier: str, *, limit: int, window_seconds: int) -> bool:
    """True = allowed, False = over the `limit` for this `window_seconds` window.

    Async to match the app's single (async) Redis client — a sync call here would
    either block the event loop or, worse, silently return un-awaited coroutines.
    Never raises — fail open. A down Redis also trips the shared breaker so later
    checks skip the dial entirely instead of paying a connect timeout per request.
    """
    global _logged_outage
    if not redis_ok():
        return True
    try:
        key = redis_key("ratelimit", bucket, identifier)
        # Lazy import: tests patch app.core.redis.get_redis_client with a fakeredis client.
        from app.core.redis import get_redis_client

        client = get_redis_client()
        # INCR returns the new count: 1 means first hit in this window → set the TTL.
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_seconds)
        return int(count) <= limit
    except Exception:  # noqa: BLE001 — fail open
        trip_breaker()
        if not _logged_outage:
            logger.warning("Redis unreachable — rate limiting disabled (fail-open)")
            _logged_outage = True
        return True


def reset_outage_flag() -> None:
    """Test seam: let a fresh test observe the once-per-outage log again."""
    global _logged_outage
    _logged_outage = False
