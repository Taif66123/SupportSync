import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlmodel import Session

from app.core.database import get_session
from app.core.errors import Unauthorized
from app.modules.auth.dependencies import authenticate_token, get_optional_credentials
from app.modules.notifications.hub import hub
from app.modules.notifications.hub import Subscriber
from app.modules.users.models import User

router = APIRouter(prefix="/notifications", tags=["notifications"])

_KEEPALIVE_SECONDS = 15  # comment frames keep proxies from closing an idle stream


@router.get("/stream")
async def stream(
    session: Annotated[Session, Depends(get_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(get_optional_credentials)],
    token: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    """Live notification stream (Server-Sent Events), one per client session.

    Auth works like the chat socket: a Bearer header, or `?token=<access token>`
    for browser EventSource, which cannot set headers. Events are ephemeral push —
    no history, no replay; clients fetch current state after reconnecting.
    """
    user: User | None = None
    if credentials is not None:
        user = authenticate_token(session, credentials.credentials)
    if user is None and token:
        user = authenticate_token(session, token)
    if user is None:
        raise Unauthorized("missing or invalid token")

    subscriber = hub.subscribe(user.id)
    return StreamingResponse(
        _stream(subscriber),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream(subscriber: Subscriber) -> AsyncIterator[str]:
    """Yield SSE frames from the subscriber's queue; keep-alive comments when idle."""
    try:
        yield ": connected\n\n"
        while True:
            try:
                notification = await asyncio.wait_for(subscriber.queue.get(), timeout=_KEEPALIVE_SECONDS)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            data = notification.model_dump_json()
            yield f"event: {notification.type}\ndata: {data}\n\n"
    finally:
        hub.unsubscribe(subscriber)
