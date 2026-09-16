from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from app.core.database import get_session
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.tickets import service
from app.modules.tickets.models import Ticket, TicketPriority
from app.modules.tickets.policy import Action
from app.modules.tickets.schemas import (
    AssignIn,
    PriorityIn,
    TicketCreateIn,
    TicketFilter,
    TicketOut,
)
from app.modules.users.models import Role, User
from app.utils.pagination import LimitOffset, Page, limit_offset

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
def create_ticket(
    data: TicketCreateIn,
    session: Annotated[Session, Depends(get_session)],
    customer: Annotated[User, Depends(require_role(Role.CUSTOMER))],
) -> Ticket:
    return service.create_ticket(
        session, customer=customer, title=data.title, description=data.description, priority=data.priority
    )


@router.get("", response_model=Page[TicketOut])
def list_tickets(
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
    filters: Annotated[TicketFilter, Depends()],
    page: Annotated[LimitOffset, Depends(limit_offset)],
) -> Page[TicketOut]:
    items, total = service.list_tickets(session, user, filters, limit=page.limit, offset=page.offset)
    return Page(items=[TicketOut.model_validate(t) for t in items], total=total, limit=page.limit, offset=page.offset)


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket(
    ticket_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> Ticket:
    return service.get_ticket(session, user, ticket_id)


@router.post("/{ticket_id}/claim", response_model=TicketOut)
def claim(
    ticket_id: int,
    session: Annotated[Session, Depends(get_session)],
    agent: Annotated[User, Depends(require_role(Role.AGENT))],
) -> Ticket:
    return service.act(session, agent, "claim", ticket_id)


@router.post("/{ticket_id}/assign", response_model=TicketOut)
def assign(
    ticket_id: int,
    data: AssignIn,
    session: Annotated[Session, Depends(get_session)],
    admin: Annotated[User, Depends(require_role(Role.ADMIN))],
) -> Ticket:
    return service.act(session, admin, "assign", ticket_id, assignee_id=data.agent_id)


@router.post("/{ticket_id}/resolve", response_model=TicketOut)
def resolve(
    ticket_id: int,
    session: Annotated[Session, Depends(get_session)],
    agent: Annotated[User, Depends(require_role(Role.AGENT))],
) -> Ticket:
    return service.act(session, agent, "resolve", ticket_id)


@router.post("/{ticket_id}/reopen", response_model=TicketOut)
def reopen(
    ticket_id: int,
    session: Annotated[Session, Depends(get_session)],
    agent: Annotated[User, Depends(require_role(Role.AGENT))],
) -> Ticket:
    return service.act(session, agent, "reopen", ticket_id)


@router.post("/{ticket_id}/close", response_model=TicketOut)
def close(
    ticket_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> Ticket:
    return service.act(session, user, "close", ticket_id)


@router.patch("/{ticket_id}/priority", response_model=TicketOut)
def change_priority(
    ticket_id: int,
    data: PriorityIn,
    session: Annotated[Session, Depends(get_session)],
    staff: Annotated[User, Depends(require_role(Role.AGENT, Role.ADMIN))],
) -> Ticket:
    return service.change_priority(session, staff, ticket_id, data.priority)
