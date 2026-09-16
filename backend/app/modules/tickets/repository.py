from datetime import UTC, datetime

from sqlalchemy import func, update
from sqlmodel import Session, select

from app.modules.tickets.models import Ticket, TicketPriority, TicketStatus
from app.modules.tickets.policy import scoped
from app.modules.users.models import User


def create(session: Session, ticket: Ticket) -> Ticket:
    session.add(ticket)
    session.flush()
    session.refresh(ticket)
    return ticket


def list_scoped(
    session: Session,
    user: User,
    *,
    status: TicketStatus | None,
    priority: TicketPriority | None,
    mine_only: bool,
    limit: int,
    offset: int,
) -> tuple[list[Ticket], int]:
    query = select(Ticket).where(*scoped(user))
    if status is not None:
        query = query.where(Ticket.status == status)
    if priority is not None:
        query = query.where(Ticket.priority == priority)
    if mine_only:
        query = query.where(Ticket.agent_id == user.id)

    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    items = list(session.exec(query.order_by(Ticket.created_at.desc(), Ticket.id.desc()).offset(offset).limit(limit)))
    return items, total


def transition(
    session: Session,
    ticket_id: int,
    *,
    from_statuses: frozenset[TicketStatus],
    requires_unassigned: bool,
    values: dict,
) -> bool:
    """Atomic conditional update: succeeds only if the ticket is still in one of
    `from_statuses` (and unassigned, when required). Returns False when the state moved
    underneath us — e.g. two agents claiming the same ticket.
    """
    statement = update(Ticket).where(Ticket.id == ticket_id, Ticket.status.in_(from_statuses))
    if requires_unassigned:
        statement = statement.where(Ticket.agent_id.is_(None))
    result = session.execute(statement.values(**values))
    return result.rowcount > 0


def count_by_status(session: Session) -> dict[TicketStatus, int]:
    rows = session.exec(select(Ticket.status, func.count()).group_by(Ticket.status))
    return dict(rows)
