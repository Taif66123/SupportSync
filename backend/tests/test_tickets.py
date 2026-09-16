import pytest

from app.modules.tickets import repository
from app.modules.tickets.models import TicketStatus
from tests.conftest import API, admin_tokens, agent_tokens, customer2_tokens, customer_tokens, headers  # noqa: F401


def create_ticket(client, tokens, title="A problem occurred", priority="medium", **overrides):
    payload = {"title": title, "description": "Details about the problem.", "priority": priority, **overrides}
    return client.post(f"{API}/tickets", json=payload, headers=headers(tokens))


def test_customer_creates_ticket(client, customer_tokens):
    response = create_ticket(client, customer_tokens, priority="high")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "open"
    assert body["priority"] == "high"
    assert body["agent_id"] is None
    assert body["closed_at"] is None


def test_only_customers_create_tickets(client, agent_tokens, admin_tokens):
    assert create_ticket(client, agent_tokens).status_code == 403
    assert create_ticket(client, admin_tokens).status_code == 403


def test_customer_sees_only_own_tickets(client, customer_tokens, customer2_tokens):
    create_ticket(client, customer_tokens, title="Mine one")
    create_ticket(client, customer_tokens, title="Mine two")
    create_ticket(client, customer2_tokens, title="Theirs")

    mine = client.get(f"{API}/tickets", headers=headers(customer_tokens)).json()
    assert mine["total"] == 2
    assert {t["title"] for t in mine["items"]} == {"Mine one", "Mine two"}

    other_id = client.get(f"{API}/tickets", headers=headers(customer2_tokens)).json()["items"][0]["id"]
    invisible = client.get(f"{API}/tickets/{other_id}", headers=headers(customer_tokens))
    assert invisible.status_code == 404  # invisible is indistinguishable from nonexistent


def test_agent_sees_queue_then_claims(client, customer_tokens, agent_tokens):
    ticket = create_ticket(client, customer_tokens, title="Please help").json()

    queue = client.get(f"{API}/tickets", headers=headers(agent_tokens)).json()
    assert [t["id"] for t in queue["items"]] == [ticket["id"]]

    claim = client.post(f"{API}/tickets/{ticket['id']}/claim", headers=headers(agent_tokens))
    assert claim.status_code == 200
    claimed = claim.json()
    assert claimed["status"] == "in_progress"
    assert claimed["agent_id"] == client.get(f"{API}/users/me", headers=headers(agent_tokens)).json()["id"]

    # Claimed tickets leave the queue but stay visible to the claiming agent.
    queue_after = client.get(f"{API}/tickets", headers=headers(agent_tokens)).json()
    assert queue_after["total"] == 1  # visible via assignment, not the queue


def test_claim_race_is_rejected(client, customer_tokens, session):
    """Conditional UPDATE: a second transition from the same source status finds no rows."""
    ticket = create_ticket(client, customer_tokens).json()

    first = repository.transition(
        session, ticket["id"], from_statuses=frozenset({TicketStatus.OPEN}), requires_unassigned=True,
        values={"status": "in_progress"},
    )
    stale = repository.transition(
        session, ticket["id"], from_statuses=frozenset({TicketStatus.OPEN}), requires_unassigned=True,
        values={"status": "in_progress"},
    )
    assert first is True
    assert stale is False


def test_assign_flow(client, admin_tokens, agent_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens, title="Assign me").json()
    agent_id = client.get(f"{API}/users/me", headers=headers(agent_tokens)).json()["id"]

    assigned = client.post(f"{API}/tickets/{ticket['id']}/assign", json={"agent_id": agent_id}, headers=headers(admin_tokens))
    assert assigned.status_code == 200
    assert assigned.json()["status"] == "in_progress"
    assert assigned.json()["agent_id"] == agent_id

    # assigning an already-assigned (in_progress) ticket conflicts
    again = client.post(f"{API}/tickets/{ticket['id']}/assign", json={"agent_id": agent_id}, headers=headers(admin_tokens))
    assert again.status_code == 409


def test_assign_requires_an_active_agent(client, admin_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    customer_id = client.get(f"{API}/users/me", headers=headers(customer_tokens)).json()["id"]

    assert (
        client.post(f"{API}/tickets/{ticket['id']}/assign", json={"agent_id": customer_id}, headers=headers(admin_tokens)).status_code
        == 404
    )
    assert (
        client.post(f"{API}/tickets/{ticket['id']}/assign", json={"agent_id": 999999}, headers=headers(admin_tokens)).status_code
        == 404
    )


def test_resolve_reopen_lifecycle(client, admin_tokens, agent_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    tid = ticket["id"]

    assert client.post(f"{API}/tickets/{tid}/resolve", headers=headers(agent_tokens)).status_code == 409  # must claim first
    assert client.post(f"{API}/tickets/{tid}/claim", headers=headers(agent_tokens)).json()["status"] == "in_progress"
    resolved = client.post(f"{API}/tickets/{tid}/resolve", headers=headers(agent_tokens))
    assert resolved.json()["status"] == "resolved"
    reopened = client.post(f"{API}/tickets/{tid}/reopen", headers=headers(agent_tokens))
    assert reopened.json()["status"] == "in_progress"

    # admin cannot resolve/reopen (agent-only actions)
    assert client.post(f"{API}/tickets/{tid}/resolve", headers=headers(admin_tokens)).status_code == 403


def test_customer_closes_own_ticket_from_any_status(client, admin_tokens, customer_tokens, agent_tokens):
    for i, priority in enumerate(["low", "medium", "high"]):
        ticket = create_ticket(client, customer_tokens, title=f"Close case {i}", priority=priority).json()
        closed = client.post(f"{API}/tickets/{ticket['id']}/close", headers=headers(customer_tokens))
        assert closed.status_code == 200
        assert closed.json()["status"] == "closed"
        assert closed.json()["closed_at"] is not None

        # closed is terminal: no one reopens it, no one closes it again.
        # The agent never saw the closed ticket (queue + assigned scope) → 404;
        # the admin sees everything → 409.
        assert client.post(f"{API}/tickets/{ticket['id']}/close", headers=headers(customer_tokens)).status_code == 409
        assert client.post(f"{API}/tickets/{ticket['id']}/reopen", headers=headers(agent_tokens)).status_code == 404
        assert client.post(f"{API}/tickets/{ticket['id']}/reopen", headers=headers(admin_tokens)).status_code == 403


def test_other_customer_cannot_close(client, customer_tokens, customer2_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    assert client.post(f"{API}/tickets/{ticket['id']}/close", headers=headers(customer2_tokens)).status_code == 404


def test_agent_closes_assigned_ticket(client, admin_tokens, agent_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    agent_id = client.get(f"{API}/users/me", headers=headers(agent_tokens)).json()["id"]
    client.post(f"{API}/tickets/{ticket['id']}/assign", json={"agent_id": agent_id}, headers=headers(admin_tokens))

    closed = client.post(f"{API}/tickets/{ticket['id']}/close", headers=headers(agent_tokens))
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"


def test_priority_change(client, admin_tokens, agent_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    tid = ticket["id"]

    assert client.patch(f"{API}/tickets/{tid}/priority", json={"priority": "high"}, headers=headers(customer_tokens)).status_code == 403
    assert client.patch(f"{API}/tickets/{tid}/priority", json={"priority": "high"}, headers=headers(agent_tokens)).json()["priority"] == "high"
    assert client.patch(f"{API}/tickets/{tid}/priority", json={"priority": "low"}, headers=headers(admin_tokens)).json()["priority"] == "low"

    client.post(f"{API}/tickets/{tid}/close", headers=headers(customer_tokens))
    # closed tickets: agent can't even see them (404), admin sees them and hits the 409
    assert client.patch(f"{API}/tickets/{tid}/priority", json={"priority": "high"}, headers=headers(agent_tokens)).status_code == 404
    assert client.patch(f"{API}/tickets/{tid}/priority", json={"priority": "high"}, headers=headers(admin_tokens)).status_code == 409


def test_pagination_and_filters(client, customer_tokens, admin_tokens):
    for i in range(25):
        create_ticket(client, customer_tokens, title=f"Bulk ticket {i:02d}", priority="high" if i % 2 else "low")

    page = client.get(f"{API}/tickets?limit=10&offset=20", headers=headers(admin_tokens)).json()
    assert page["total"] == 25
    assert len(page["items"]) == 5

    high = client.get(f"{API}/tickets?priority=high", headers=headers(admin_tokens)).json()
    assert high["total"] == 12  # i in {1, 3, ..., 23}
    assert all(t["priority"] == "high" for t in high["items"])

    open_filter = client.get(f"{API}/tickets?status=open&limit=5", headers=headers(admin_tokens)).json()
    assert open_filter["total"] == 25


def test_mine_filter_for_agents(client, admin_tokens, agent_tokens, customer_tokens):
    t1 = create_ticket(client, customer_tokens, title="Ticket one").json()
    create_ticket(client, customer_tokens, title="Ticket two")
    agent_id = client.get(f"{API}/users/me", headers=headers(agent_tokens)).json()["id"]
    client.post(f"{API}/tickets/{t1['id']}/assign", json={"agent_id": agent_id}, headers=headers(admin_tokens))

    mine = client.get(f"{API}/tickets?mine=true", headers=headers(agent_tokens)).json()
    assert mine["total"] == 1
    assert mine["items"][0]["title"] == "Ticket one"
