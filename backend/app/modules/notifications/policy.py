"""The single source of truth for who gets notified about what.

Same declarative-table discipline as the tickets and chat policies (ADR 0002).
Recipients are *subscriptions*, evaluated once — when the event fires, with the
real ticket in hand: everybody whose role (and, where relevant, relationship to
the ticket) matches. Admins observe but are never notified. The "subtract the
actor" rule lives in the emitter, not here — this table answers "who is
interested", not "who did it".
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sqlmodel import Session

from app.modules.tickets.models import Ticket
from app.modules.users import service as users_service
from app.modules.users.models import Role

NotificationType = Literal["ticket.created", "ticket.updated", "message.created"]


def _all_agents(_session: Session, _ticket: Ticket) -> frozenset[int]:
    # Any active Support Agent may act on a new Queue ticket — all of them subscribe.
    return frozenset(users_service.list_active_ids_by_role(_session, Role.AGENT))


def _participants(_session: Session, ticket: Ticket) -> frozenset[int]:
    """The conversation around a ticket: its Customer + assigned Agent."""
    ids = {ticket.customer_id}
    if ticket.agent_id is not None:
        ids.add(ticket.agent_id)
    return frozenset(ids)


@dataclass(frozen=True)
class NotificationRule:
    notification_type: NotificationType
    subscribers: Callable[[Session, Ticket], frozenset[int]]  # user ids interested in this ticket


RULES: tuple[NotificationRule, ...] = (
    NotificationRule(notification_type="ticket.created", subscribers=_all_agents),
    NotificationRule(notification_type="ticket.updated", subscribers=_participants),
    NotificationRule(notification_type="message.created", subscribers=_participants),
)


def recipients(session: Session, notification_type: NotificationType, ticket: Ticket) -> frozenset[int]:
    """User ids that should hear about this event."""
    for rule in RULES:
        if rule.notification_type == notification_type:
            return rule.subscribers(session, ticket)
    raise ValueError(f"unknown notification type: {notification_type}")
