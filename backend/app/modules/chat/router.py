import json
from typing import Annotated, Any

import jwt
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlmodel import Session

from app.core.database import get_session
from app.core.errors import AppError
from app.core.rate_limit_dependencies import (
    CHAT_SEND_BUCKET,
    CHAT_SEND_LIMIT,
    CHAT_SEND_WINDOW_SECONDS,
    limit_per_user,
)
from app.core.ratelimit import check as rate_limit_check
from app.core.security import decode_access_token
from app.modules.auth.dependencies import get_current_user
from app.modules.chat import policy, service
from app.modules.chat.connections import registry
from app.modules.chat.schemas import (
    ConnectAck,
    ErrorFrame,
    MessageIn,
    MessageNew,
    MessageOut,
    MessagePage,
    ReadReceipt,
    ReadStateOut,
    ReadUpTo,
    TypingStart,
    TypingUpdate,
)
from app.modules.tickets.models import Ticket
from app.modules.users import service as users
from app.modules.users.models import User
from app.utils.pagination import LimitOffset, limit_offset

router = APIRouter(prefix="/tickets", tags=["chat"])

_WS_CLOSE_POLICY = 1008  # policy violation: bad token or invisible/forbidden ticket


@router.get("/{ticket_id}/messages", response_model=MessagePage)
def history(
    ticket_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
    page: Annotated[LimitOffset, Depends(limit_offset)],
) -> MessagePage:
    """Message history for one ticket, oldest first. Invisible ticket → 404."""
    ticket = policy.get_chat(session, user, ticket_id)
    items, total = service.history(session, user, ticket, limit=page.limit, offset=page.offset)
    return MessagePage(
        items=[MessageOut.model_validate(m) for m in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/{ticket_id}/messages", status_code=201, response_model=MessageOut,
             dependencies=[Depends(limit_per_user(CHAT_SEND_BUCKET, limit=CHAT_SEND_LIMIT, window_seconds=CHAT_SEND_WINDOW_SECONDS))])
def post_message(
    ticket_id: int,
    payload: MessageIn,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> MessageOut:
    """Post one message over plain HTTP (same rules as the socket; useful for
    clients that are not connected, tests, and retries). Invisible ticket → 404."""
    ticket = policy.get_chat(session, user, ticket_id)
    message = service.post(session, user, ticket, body=payload.body)
    return MessageOut.model_validate(message)


@router.get("/{ticket_id}/messages/read-states", response_model=list[ReadStateOut])
def read_states(
    ticket_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[ReadStateOut]:
    """Per-participant read markers for this ticket's chat. Invisible ticket → 404."""
    ticket = policy.get_chat(session, user, ticket_id)
    return [ReadStateOut(**state) for state in service.read_states(session, user, ticket)]


@router.websocket("/{ticket_id}/ws")
async def chat_socket(
    websocket: WebSocket,
    ticket_id: int,
    token: Annotated[str, Query()],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    """Per-ticket chat socket.

    Auth: `?token=<access token>` — browsers cannot set headers on a WebSocket handshake.
    Authorization runs before accept: a bad token or an invisible ticket is rejected with
    close code 1008, so the chat's existence is never leaked.

    The wire contract lives in schemas.py: client frames are `MessageIn` / `TypingStart` /
    `ReadUpTo`, server frames are `ConnectAck` / `MessageNew` / `TypingUpdate` /
    `ReadReceipt` / `ErrorFrame`. A connection owns its transaction — each accepted send
    commits exactly one message.
    """
    user = _authenticate(session, token)
    if user is None:
        await websocket.close(code=_WS_CLOSE_POLICY, reason="invalid or expired token")
        return
    try:
        ticket = policy.get_chat(session, user, ticket_id)
    except AppError:
        await websocket.close(code=_WS_CLOSE_POLICY, reason="ticket not found")
        return

    await websocket.accept()
    room = registry.room(ticket_id)
    room.add(user.id, websocket)
    try:
        await _send(websocket, ConnectAck(can_send=policy.can(user, "send")))
        while True:
            raw = await websocket.receive_text()
            await _handle_frame(session, user, ticket, ticket_id, raw, websocket)
    except WebSocketDisconnect:
        pass
    finally:
        room.remove(user.id, websocket)
        registry.drop_room_if_empty(ticket_id)


async def _send(
    websocket: WebSocket,
    frame: ConnectAck | MessageNew | TypingUpdate | ReadReceipt | ErrorFrame,
) -> None:
    await websocket.send_json(frame.model_dump(mode="json"))


async def _handle_frame(
    session: Session,
    user: User,
    ticket: Ticket,
    ticket_id: int,
    raw: str,
    websocket: WebSocket,
) -> None:
    try:
        frame: Any = json.loads(raw)
    except json.JSONDecodeError:
        await _send(websocket, ErrorFrame(code="invalid_json", message="frames must be valid JSON objects"))
        return
    if not isinstance(frame, dict) or frame.get("type") not in ("message.send", "typing.start", "read.up-to"):
        await _send(websocket, ErrorFrame(code="unknown_type", message='expected message.send, typing.start or read.up-to'))
        return

    if frame["type"] == "read.up-to":
        try:
            read_up_to = ReadUpTo.model_validate(frame)
        except Exception:
            await _send(websocket, ErrorFrame(code="invalid_body", message="read.up-to needs an integer message_id >= 1"))
            return
        try:
            message = service.mark_read(session, user, ticket, read_up_to.message_id)
        except AppError as exc:
            await _send(websocket, ErrorFrame(code=exc.code, message=exc.message))
            return
        if message is not None:  # a backwards / repeat read is a silent no-op
            session.commit()  # commit the marker before telling the room about it
            await registry.broadcast(ticket_id, ReadReceipt(user_id=user.id, message_id=message.id))
        return

    if frame["type"] == "typing.start":
        try:
            TypingStart.model_validate(frame)
        except Exception:
            await _send(websocket, ErrorFrame(code="invalid_body", message="typing.start takes no fields"))
            return
        # Typing uses exactly the send rules: on a closed ticket nobody may type either.
        try:
            policy.ensure(ticket, user, "send")
        except AppError as exc:
            await _send(websocket, ErrorFrame(code=exc.code, message=exc.message))
            return
        # Ephemeral: broadcast only, never persisted — and never echoed to the typist.
        await registry.broadcast(ticket_id, TypingUpdate(user_id=user.id), exclude=user.id)
        return

    try:
        message_in = MessageIn.model_validate(frame)
    except Exception:
        await _send(websocket, ErrorFrame(code="invalid_body", message="body must be 1..4000 characters"))
        return

    if not await rate_limit_check(CHAT_SEND_BUCKET, str(user.id), limit=CHAT_SEND_LIMIT, window_seconds=CHAT_SEND_WINDOW_SECONDS):
        # Same bucket as the REST twin; the socket stays open, unlike HTTP's 429.
        await _send(websocket, ErrorFrame(code="rate_limited", message="too many messages — slow down"))
        return

    try:
        message = service.post(session, user, ticket, body=message_in.body)
    except AppError as exc:
        # e.g. Forbidden on a closed ticket — the connection stays open for reading.
        await _send(websocket, ErrorFrame(code=exc.code, message=exc.message))
        return

    session.commit()  # the WS connection owns its transaction boundary: commit per message
    await registry.broadcast(ticket_id, MessageNew(message=MessageOut.model_validate(message)))


def _authenticate(session: Session, token: str) -> User | None:
    """Handshake auth — mirrors get_current_user, returns None instead of raising."""
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None
    return users.get_active(session, user_id)
