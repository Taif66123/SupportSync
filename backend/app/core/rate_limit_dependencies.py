"""Reusable rate-limit dependencies (M3 Phase B).

Two flavors cover every endpoint: per-IP for public endpoints (no user to key on)
and per-user for authenticated ones. Limits live here, next to the mechanism, so
an endpoint says only *that* it's limited, not how.
"""

from typing import Annotated

from fastapi import Depends, Request

from app.core import ratelimit
from app.core.errors import RateLimited
from app.modules.auth.dependencies import get_current_user
from app.modules.users.models import User

# The chat-send bucket is shared by the REST twin and WS frames — one home for the
# numbers so they can never diverge.
CHAT_SEND_BUCKET = "chat-send"
CHAT_SEND_LIMIT = 30
CHAT_SEND_WINDOW_SECONDS = 60


def _client_ip(request: Request) -> str:
    # Direct socket address: there is no trusted proxy in this deployment, so
    # honoring X-Forwarded-For would be an IP-spoofing hole.
    return request.client.host if request.client else "unknown"


def limit_per_ip(bucket: str, *, limit: int, window_seconds: int):
    async def checker(request: Request) -> None:
        if not await ratelimit.check(bucket, _client_ip(request), limit=limit, window_seconds=window_seconds):
            raise RateLimited("too many requests — slow down")

    return checker


def limit_per_user(bucket: str, *, limit: int, window_seconds: int):
    async def checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if not await ratelimit.check(bucket, str(user.id), limit=limit, window_seconds=window_seconds):
            raise RateLimited("too many requests — slow down")
        return user

    return checker
