"""Table-driven tests for the ticket policy — pure units, no database.

The expected grid below is deliberately written by hand (not derived from RULES):
it is the independent specification of ADR 0001 that RULES must match.
"""

import pytest

from app.core.errors import Conflict, Forbidden
from app.modules.tickets.models import Ticket, TicketStatus
from app.modules.tickets.policy import RULES, ensure
from app.modules.users.models import Role, User

STATUSES = list(TicketStatus)
ROLES = list(Role)


def make_user(role: Role, user_id: int = 1) -> User:
    return User(id=user_id, email=f"{role.value}@t.io", hashed_password="x", full_name="T", role=role)


def make_ticket(status: TicketStatus, *, customer_id: int = 100, agent_id: int | None = None) -> Ticket:
    return Ticket(
        id=1, customer_id=customer_id, agent_id=agent_id, title="t", description="d", status=status
    )


EXPECTED = [
    # (role, action, status, owns_ticket, expected) — expected: "ok", "forbidden", "conflict"
    # claim
    (Role.AGENT, "claim", TicketStatus.OPEN, False, "ok"),
    (Role.AGENT, "claim", TicketStatus.IN_PROGRESS, False, "conflict"),
    (Role.AGENT, "claim", TicketStatus.RESOLVED, False, "conflict"),
    (Role.AGENT, "claim", TicketStatus.CLOSED, False, "conflict"),
    (Role.CUSTOMER, "claim", TicketStatus.OPEN, True, "forbidden"),
    (Role.ADMIN, "claim", TicketStatus.OPEN, False, "forbidden"),
    # assign
    (Role.ADMIN, "assign", TicketStatus.OPEN, False, "ok"),
    (Role.ADMIN, "assign", TicketStatus.IN_PROGRESS, False, "conflict"),
    (Role.AGENT, "assign", TicketStatus.OPEN, False, "forbidden"),
    (Role.CUSTOMER, "assign", TicketStatus.OPEN, True, "forbidden"),
    # resolve
    (Role.AGENT, "resolve", TicketStatus.IN_PROGRESS, False, "ok"),
    (Role.AGENT, "resolve", TicketStatus.OPEN, False, "conflict"),
    (Role.AGENT, "resolve", TicketStatus.RESOLVED, False, "conflict"),
    (Role.ADMIN, "resolve", TicketStatus.IN_PROGRESS, False, "forbidden"),
    (Role.CUSTOMER, "resolve", TicketStatus.IN_PROGRESS, True, "forbidden"),
    # reopen
    (Role.AGENT, "reopen", TicketStatus.RESOLVED, False, "ok"),
    (Role.AGENT, "reopen", TicketStatus.IN_PROGRESS, False, "conflict"),
    (Role.AGENT, "reopen", TicketStatus.OPEN, False, "conflict"),
    (Role.CUSTOMER, "reopen", TicketStatus.RESOLVED, True, "forbidden"),
    (Role.ADMIN, "reopen", TicketStatus.RESOLVED, False, "forbidden"),
    # close — customers only on their own tickets, from any non-closed status
    (Role.CUSTOMER, "close", TicketStatus.OPEN, True, "ok"),
    (Role.CUSTOMER, "close", TicketStatus.IN_PROGRESS, True, "ok"),
    (Role.CUSTOMER, "close", TicketStatus.RESOLVED, True, "ok"),
    (Role.CUSTOMER, "close", TicketStatus.CLOSED, True, "conflict"),
    (Role.CUSTOMER, "close", TicketStatus.OPEN, False, "forbidden"),
    (Role.AGENT, "close", TicketStatus.IN_PROGRESS, False, "ok"),
    (Role.AGENT, "close", TicketStatus.RESOLVED, False, "ok"),
    (Role.AGENT, "close", TicketStatus.CLOSED, False, "conflict"),
    (Role.ADMIN, "close", TicketStatus.OPEN, False, "ok"),
    (Role.ADMIN, "close", TicketStatus.CLOSED, False, "conflict"),
    # change_priority
    (Role.AGENT, "change_priority", TicketStatus.OPEN, False, "ok"),
    (Role.AGENT, "change_priority", TicketStatus.IN_PROGRESS, False, "ok"),
    (Role.AGENT, "change_priority", TicketStatus.RESOLVED, False, "ok"),
    (Role.AGENT, "change_priority", TicketStatus.CLOSED, False, "conflict"),
    (Role.ADMIN, "change_priority", TicketStatus.IN_PROGRESS, False, "ok"),
    (Role.CUSTOMER, "change_priority", TicketStatus.OPEN, True, "forbidden"),
]


@pytest.mark.parametrize(("role", "action", "status", "owns", "expected"), EXPECTED)
def test_policy_grid(role, action, status, owns, expected):
    user = make_user(role, user_id=1)
    ticket = make_ticket(status, customer_id=1 if owns else 999)

    if expected == "ok":
        ensure(user, action, ticket)
    elif expected == "forbidden":
        with pytest.raises(Forbidden):
            ensure(user, action, ticket)
    else:
        with pytest.raises(Conflict):
            ensure(user, action, ticket)


def test_rules_invariants():
    actions = [rule.action for rule in RULES]
    assert len(actions) == len(set(actions)), "one rule per action"

    for rule in RULES:
        assert TicketStatus.CLOSED not in rule.from_statuses, "closed is terminal (ADR 0001)"
        assert rule.owner_roles <= rule.roles, "owner_roles must be a subset of roles"

    close = next(rule for rule in RULES if rule.action == "close")
    assert Role.CUSTOMER in close.owner_roles, "customers may only close their own tickets"
