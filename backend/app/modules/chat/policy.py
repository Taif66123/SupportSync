"""The single source of truth for who may use per-ticket chat, and how.

Same declarative spirit as tickets/policy.py (ADR 0002) but deliberately separate —
chat authorization is its own domain (milestone boundary), so this table must never
grow an import of the tickets policy.

Roles: participants = the ticket's Customer + assigned Support Agent, who may read and
send. Admin is a read-only observer. Everyone else must never learn the chat exists
(invisible → NotFound). Sending on a closed ticket is Forbidden — closed is terminal
(ADR 0001). Sending before an Agent claims is allowed: messages buffer in the table
until the chat has its agent.
"""

from dataclasses import dataclass
from typing import Literal

from sqlmodel import Session, select

from app.core.errors import Forbidden, NotFound
from app.modules.tickets.models import Ticket, TicketStatus
from app.modules.users.models import Role, User

Capability = Literal["read", "send"]


@dataclass(frozen=True)
class ChatRule:
    roles: frozenset[Role]  # which roles this row applies to
    capabilities: frozenset[Capability]  # what those roles may do on a matching ticket
    only_own: bool  # customers: restricted to tickets they created
    only_assigned: bool  # agents: restricted to tickets assigned to them


RULES: tuple[ChatRule, ...] = (
    ChatRule(roles=frozenset({Role.CUSTOMER}), capabilities=frozenset({"read", "send"}), only_own=True, only_assigned=False),
    ChatRule(roles=frozenset({Role.AGENT}), capabilities=frozenset({"read", "send"}), only_own=False, only_assigned=True),
    ChatRule(roles=frozenset({Role.ADMIN}), capabilities=frozenset({"read"}), only_own=False, only_assigned=False),
)


def _rule_for(user: User) -> ChatRule | None:
    for rule in RULES:
        if user.role in rule.roles:
            return rule
    return None


def can(user: User, capability: Capability) -> bool:
    """Role-level capability check (no ticket loaded) — used for connect acknowledgements."""
    rule = _rule_for(user)
    return rule is not None and capability in rule.capabilities


def get_chat(session: Session, user: User, ticket_id: int) -> Ticket:
    """Load the ticket `user` may chat on, or raise NotFound.

    Invisible to this user (unknown role, not a participant) → NotFound, so the chat's
    existence is never leaked — same contract as tickets/policy.get_visible.
    """
    rule = _rule_for(user)
    if rule is None:
        raise NotFound("ticket not found")

    statement = select(Ticket).where(Ticket.id == ticket_id)
    if rule.only_own:
        statement = statement.where(Ticket.customer_id == user.id)
    if rule.only_assigned:
        statement = statement.where(Ticket.agent_id == user.id)

    ticket = session.exec(statement).first()
    if ticket is None:
        raise NotFound("ticket not found")
    return ticket


def ensure(ticket: Ticket, user: User, capability: Capability) -> None:
    """Raise Forbidden when `user` lacks `capability` on `ticket`."""
    rule = _rule_for(user)
    if rule is None or capability not in rule.capabilities:
        raise Forbidden("you are not allowed to send messages in this chat")
    if capability == "send" and ticket.status is TicketStatus.CLOSED:
        raise Forbidden("this ticket is closed — its chat is read-only")
