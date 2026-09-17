"""In-process notification hub: user_id → live SSE subscribers.

Pure fan-out — no database, no business rules (recipients are computed by
notifications/policy before publish). For the single-process M3 Phase A
deployment this hub is complete; Phase B's Redis pub/sub replaces only the
cross-process gap, keeping the emit contract identical.
"""

import asyncio
from dataclasses import dataclass, field

from app.modules.notifications.schemas import Notification


@dataclass
class Subscriber:
    user_id: int
    queue: asyncio.Queue[Notification | None] = field(default_factory=asyncio.Queue)


class NotificationHub:
    def __init__(self) -> None:
        self._subscribers: dict[int, list[Subscriber]] = {}

    def subscribe(self, user_id: int) -> Subscriber:
        subscriber = Subscriber(user_id=user_id)
        self._subscribers.setdefault(user_id, []).append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        streams = self._subscribers.get(subscriber.user_id)
        if streams is None:
            return
        # Only drop this exact stream — a user may legitimately have several open.
        if subscriber in streams:
            streams.remove(subscriber)
        if not streams:
            del self._subscribers[subscriber.user_id]

    def push(self, user_id: int, notification: Notification) -> None:
        for subscriber in self._subscribers.get(user_id, []):
            subscriber.queue.put_nowait(notification)

    def push_many(self, user_ids: frozenset[int] | set[int], notification: Notification) -> None:
        for user_id in user_ids:
            self.push(user_id, notification)


hub = NotificationHub()
