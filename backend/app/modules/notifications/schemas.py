from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Notification(BaseModel):
    """One pushed event on the SSE stream.

    `at` is UTC; `payload` is a small, self-sufficient snapshot so the client can
    render (or decide to fetch) without a second round trip.
    """

    type: Literal["ticket.created", "ticket.updated", "message.created"]
    at: datetime
    payload: dict


class NotificationOut(BaseModel):
    """The SSE wire shape (`data:` line): event + payload, `at` ISO-8601 UTC."""

    type: str
    at: datetime
    payload: dict


class NotificationEnvelope(BaseModel):
    """Internal pub/sub frame between workers (never exposed to clients).

    Recipients ride with the notification because they are subscriptions, resolved
    once at emit time; the cross-worker listener is a dumb pump with no DB access.
    `origin` is the emitting worker's identity — listeners skip their own frames
    (their local hub already delivered them).
    """

    recipients: list[int]
    origin: str
    notification: Notification
