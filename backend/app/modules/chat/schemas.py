from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.utils.pagination import Page


class MessageOut(BaseModel):
    """One chat message, as delivered over both the WebSocket and the history endpoint."""

    model_config = {"from_attributes": True}

    id: int
    ticket_id: int
    sender_id: int
    body: str
    created_at: datetime


MessagePage = Page[MessageOut]


class MessageIn(BaseModel):
    """Client → server chat frame."""

    type: Literal["message.send"] = "message.send"
    body: str = Field(min_length=1, max_length=4000)


class TypingStart(BaseModel):
    """Client → server. Ephemeral: broadcast to the room's other participants,
    never persisted. Authorization = exactly the same rules as message.send."""

    type: Literal["typing.start"] = "typing.start"


class ReadUpTo(BaseModel):
    """Client → server: "I have read everything up to this message id."

    Must reference a message of this ticket; markers are monotonic (never move
    backwards); authorization = the send rules (participants only).
    """

    type: Literal["read.up-to"] = "read.up-to"
    message_id: int = Field(ge=1)


class ConnectAck(BaseModel):
    """Server → client, right after accept: whether this user may send on this ticket."""

    type: Literal["connect.ack"] = "connect.ack"
    can_send: bool


class MessageNew(BaseModel):
    """Server → client, broadcast to everyone in the room when a message is persisted."""

    type: Literal["message.new"] = "message.new"
    message: MessageOut


class ErrorFrame(BaseModel):
    """Server → client, on a bad frame or a rejected send (the socket stays open)."""

    type: Literal["error"] = "error"
    code: str
    message: str


class TypingUpdate(BaseModel):
    """Server → client, to everyone in the room except the typist."""

    type: Literal["typing.start"] = "typing.start"
    user_id: int


class ReadReceipt(BaseModel):
    """Server → client, broadcast to the whole room including the reader."""

    type: Literal["read.receipt"] = "read.receipt"
    user_id: int
    message_id: int


class ReadStateOut(BaseModel):
    """One participant's read marker, as served by the REST read-states endpoint."""

    user_id: int
    last_read_message_id: int
    updated_at: datetime
