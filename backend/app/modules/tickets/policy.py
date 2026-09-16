"""The single source of truth for who may do what to a ticket, and who may see which tickets.

One declarative table (RULES) drives every action endpoint, the priority change, and the
table-driven tests. Do not add role/status `if` branches in services or routers — extend
the table instead (ADR 0001, docs/adr/0001).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement, and_, or_
from sqlmodel import Session, select

from app.core.errors import Conflict, Forbidden
from app.modules.tickets.models import Ticket, TicketStatus
from app.modules.users.models import Role, User

Action = Literal["claim", "assign", "resolve", "reopen", "close", "change_priority"]


@dataclass(frozen=True)
class Rule:
    action: Action
    roles: frozenset[Role]  # who may attempt the action at all
    owner_roles: frozenset[Role]  # subset of `roles` restricted to their own tickets
    from_statuses: frozenset[TicketStatus]  # legal source statuses
    to_status: TicketStatus | None = None  # None = status unchanged
    requires_unassigned: bool = False  # fails with Conflict if a Support Agent is already assigned
    sets_agent_to_actor: bool = False  # claim: the acting agent becomes the assignee
    sets_agent_from_param: bool = False  # assign: the assignee comes from the request payload


RULES: tuple[Rule, ...] = (
    Rule(
        action="claim",
        roles=frozenset({Role.AGENT}),
        owner_roles=frozenset(),
        from_statuses=frozenset({TicketStatus.OPEN}),
        to_status=TicketStatus.IN_PROGRESS,
        requires_unassigned=True,
        sets_agent_to_actor=True,
    ),
    Rule(
        action="assign",
        roles=frozenset({Role.ADMIN}),
        owner_roles=frozenset(),
        from_statuses=frozenset({TicketStatus.OPEN}),
        to_status=TicketStatus.IN_PROGRESS,
        requires_unassigned=True,
        sets_agent_from_param=True,
    ),
    Rule(
        action="resolve",
        roles=frozenset({Role.AGENT}),
        owner_roles=frozenset(),
        from_statuses=frozenset({TicketStatus.IN_PROGRESS}),
        to_status=TicketStatus.RESOLVED,
    ),
    Rule(
        action="reopen",
        roles=frozenset({Role.AGENT}),
        owner_roles=frozenset(),
        from_statuses=frozenset({TicketStatus.RESOLVED}),
        to_status=TicketStatus.IN_PROGRESS,
    ),
    Rule(
        action="close",
        roles=frozenset({Role.CUSTOMER, Role.AGENT, Role.ADMIN}),
        owner_roles=frozenset({Role.CUSTOMER}),
        from_statuses=frozenset({TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED}),
        to_status=TicketStatus.CLOSED,
    ),
    Rule(
        action="change_priority",
        roles=frozenset({Role.AGENT, Role.ADMIN}),
        owner_roles=frozenset(),
        from_statuses=frozenset({TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED}),
    ),
)


def ensure(user: User, action: Action, ticket: Ticket) -> Rule:
    """The interface for action endpoints. Returns the matching Rule (with the transition to
    apply) or raises: NotFound is handled upstream by visibility, Forbidden for wrong
    role/ownership, Conflict for an illegal source status.
    """
    for rule in RULES:
        if rule.action != action or user.role not in rule.roles:
            continue
        if user.role in rule.owner_roles and ticket.customer_id != user.id:
            continue
        if ticket.status not in rule.from_statuses:
            raise Conflict(f"cannot {action} a ticket in status '{ticket.status.value}'")
        return rule
    raise Forbidden(f"you are not allowed to {action} this ticket")


def scoped(user: User) -> Sequence[ColumnElement[bool]]:
    """The interface for reads: visibility conditions for `user`, AND-composed.

    Customer sees their own tickets; Support Agent sees the Queue (open, unassigned) plus
    tickets assigned to them; Admin sees everything. Used by both the list query and the
    single-ticket lookup (invisible → 404).
    """
    if user.role is Role.CUSTOMER:
        return (Ticket.customer_id == user.id,)
    if user.role is Role.AGENT:
        return (
            or_(
                and_(Ticket.status == TicketStatus.OPEN, Ticket.agent_id.is_(None)),
                Ticket.agent_id == user.id,
            ),
        )
    return ()


def get_visible(session: Session, user: User, ticket_id: int) -> Ticket | None:
    statement = select(Ticket).where(Ticket.id == ticket_id, *scoped(user))
    return session.exec(statement).first()
