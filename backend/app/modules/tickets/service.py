from datetime import UTC, datetime

from sqlmodel import Session

from app.core.errors import Conflict, NotFound
from app.modules.tickets import policy, repository
from app.modules.tickets.models import Ticket, TicketPriority, TicketStatus
from app.modules.tickets.policy import Action
from app.modules.emails import tasks as emails
from app.modules.notifications import service as notifications
from app.modules.tickets.schemas import TicketFilter
from app.modules.users import service as users
from app.modules.users.models import User


def create_ticket(session: Session, *, customer: User, title: str, description: str, priority: TicketPriority) -> Ticket:
    ticket = Ticket(customer_id=customer.id, title=title.strip(), description=description, priority=priority)
    ticket = repository.create(session, ticket)
    # Every active Agent subscribes to new Queue tickets (notifications/policy.py).
    notifications.notify(
        session,
        actor=customer,
        ticket=ticket,
        notification_type="ticket.created",
        payload={
            "ticket_id": ticket.id,
            "title": ticket.title,
            "priority": ticket.priority.value if hasattr(ticket.priority, "value") else str(ticket.priority),
            "customer_id": ticket.customer_id,
            "status": ticket.status.value if hasattr(ticket.status, "value") else str(ticket.status),
        },
    )
    # Confirmation email to the customer, commit-gated like notifications (ADR 0006).
    emails.queue_confirmation(session, ticket=ticket, to=customer.email)
    return ticket


def list_tickets(
    session: Session,
    user: User,
    filters: TicketFilter,
    *,
    limit: int,
    offset: int,
) -> tuple[list[Ticket], int]:
    return repository.list_scoped(
        session,
        user,
        status=filters.status,
        priority=filters.priority,
        mine_only=filters.mine,
        limit=limit,
        offset=offset,
    )


def get_ticket(session: Session, user: User, ticket_id: int) -> Ticket:
    ticket = policy.get_visible(session, user, ticket_id)
    if ticket is None:
        raise NotFound("ticket not found")
    return ticket


def act(session: Session, user: User, action: Action, ticket_id: int, *, assignee_id: int | None = None) -> Ticket:
    ticket = get_ticket(session, user, ticket_id)  # invisible → 404
    rule = policy.ensure(user, action, ticket)

    assignee = None
    if rule.sets_agent_to_actor:
        assignee = user
    elif rule.sets_agent_from_param:
        if assignee_id is None:
            raise NotFound("agent not found")
        assignee = users.get_agent(session, assignee_id)
        if assignee is None:
            raise NotFound("agent not found")

    now = datetime.now(UTC)
    values: dict = {"updated_at": now}
    if rule.to_status is not None:
        values["status"] = rule.to_status
    if rule.to_status is TicketStatus.CLOSED:
        values["closed_at"] = now
    if assignee is not None:
        values["agent_id"] = assignee.id

    moved = repository.transition(
        session,
        ticket.id,
        from_statuses=rule.from_statuses,
        requires_unassigned=rule.requires_unassigned,
        values=values,
    )
    if not moved:
        raise Conflict("ticket changed state concurrently, try again")
    session.refresh(ticket)
    if rule.to_status is not None:  # a real status transition — the milestone's "status update"
        notifications.notify(
            session,
            actor=user,
            ticket=ticket,
            notification_type="ticket.updated",
            payload={
                "ticket_id": ticket.id,
                "title": ticket.title,
                "status": ticket.status.value if hasattr(ticket.status, "value") else str(ticket.status),
                "agent_id": ticket.agent_id,
                "closed_at": ticket.closed_at.isoformat() if ticket.closed_at else None,
            },
        )
    return ticket


def change_priority(session: Session, user: User, ticket_id: int, priority: TicketPriority) -> Ticket:
    ticket = get_ticket(session, user, ticket_id)
    policy.ensure(user, "change_priority", ticket)  # role + source-status guard
    ticket.priority = priority
    session.add(ticket)
    session.flush()
    session.refresh(ticket)
    return ticket
