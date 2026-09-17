from sqlmodel import Session

from app.core.errors import NotFound
from app.modules.chat import policy, repository
from app.modules.chat.models import Message
from app.modules.notifications import service as notifications
from app.modules.tickets.models import Ticket
from app.modules.users.models import User


def history(session: Session, user: User, ticket: Ticket, *, limit: int, offset: int) -> tuple[list[Message], int]:
    policy.ensure(ticket, user, "read")
    return repository.list_for_ticket(session, ticket.id, limit=limit, offset=offset)


def post(session: Session, user: User, ticket: Ticket, *, body: str) -> Message:
    """Persist one chat message. Sending before a Support Agent is assigned is
    deliberately allowed — messages are buffered in the table, and only participants
    (plus read-only Admins) ever see them (milestone boundary)."""
    policy.ensure(ticket, user, "send")
    message = Message(ticket_id=ticket.id, sender_id=user.id, body=body)
    message = repository.create(session, message)
    # The conversation's other participant hears about it (notifications/policy.py).
    notifications.notify(
        session,
        actor=user,
        ticket=ticket,
        notification_type="message.created",
        payload={
            "ticket_id": ticket.id,
            "message_id": message.id,
            "sender_id": message.sender_id,
            "body": message.body,
            "created_at": message.created_at.isoformat() if message.created_at else None,
        },
    )
    return message


def mark_read(session: Session, user: User, ticket: Ticket, message_id: int) -> Message | None:
    """Advance `user`'s read marker on this ticket's chat.

    Receipts are for the conversation's participants, so they use the send rules
    (admins are observers and never generate receipts; a closed chat is over, and
    its final receipts were broadcast before the close). The marker is monotonic —
    returns the message when the marker advanced (worth broadcasting) or None when
    the request was a no-op (marker already at or beyond that message).
    """
    policy.ensure(ticket, user, "send")
    message = repository.get_message(session, message_id)
    if message is None or message.ticket_id != ticket.id:
        raise NotFound("message not found")
    advanced = repository.upsert_read_state(session, ticket.id, user.id, message_id)
    return message if advanced else None


def read_states(session: Session, user: User, ticket: Ticket) -> list[dict]:
    """Read markers for the ticket's chat, for displaying ✓✓ state and unread counts."""
    policy.ensure(ticket, user, "read")
    return repository.list_read_states(session, ticket.id)
