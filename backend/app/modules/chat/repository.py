from sqlmodel import Session, func, select

from app.modules.chat.models import Message, TicketReadState
from app.utils.time import utcnow


def create(session: Session, message: Message) -> Message:
    session.add(message)
    session.flush()
    session.refresh(message)
    return message


def list_for_ticket(session: Session, ticket_id: int, *, limit: int, offset: int) -> tuple[list[Message], int]:
    """History in chronological order (oldest first) — matches how a conversation reads."""
    total = session.exec(select(func.count()).where(Message.ticket_id == ticket_id)).one()
    items = list(
        session.exec(
            select(Message)
            .where(Message.ticket_id == ticket_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .offset(offset)
            .limit(limit)
        )
    )
    return items, total


def get_message(session: Session, message_id: int) -> Message | None:
    return session.get(Message, message_id)


def get_read_state(session: Session, ticket_id: int, user_id: int) -> TicketReadState | None:
    return session.exec(
        select(TicketReadState).where(
            TicketReadState.ticket_id == ticket_id,
            TicketReadState.user_id == user_id,
        )
    ).first()


def upsert_read_state(session: Session, ticket_id: int, user_id: int, message_id: int) -> bool:
    """Advance the user's read marker to `message_id`, never backwards (monotonic).

    Returns True when the marker moved (a receipt is worth broadcasting), False when
    this was a no-op. Read-then-write without a row lock: the uq_read_state_ticket_user
    unique constraint is the hard safety net against a concurrent first-insert; losing
    that race just means the newer marker wins, which is the desired outcome.
    """
    state = get_read_state(session, ticket_id, user_id)
    if state is None:
        session.add(TicketReadState(ticket_id=ticket_id, user_id=user_id, last_read_message_id=message_id))
        session.flush()
        return True
    if message_id > state.last_read_message_id:
        state.last_read_message_id = message_id
        state.updated_at = utcnow()
        session.flush()
        return True
    return False


def list_read_states(session: Session, ticket_id: int) -> list[dict]:
    states = list(
        session.exec(
            select(TicketReadState).where(TicketReadState.ticket_id == ticket_id).order_by(TicketReadState.user_id)
        )
    )
    return [
        {"user_id": s.user_id, "last_read_message_id": s.last_read_message_id, "updated_at": s.updated_at}
        for s in states
    ]
