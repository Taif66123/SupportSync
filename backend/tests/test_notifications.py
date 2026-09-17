import asyncio
import json

import pytest

from app.modules.notifications import router as notifications_router
from app.modules.notifications import service as notifications_service
from app.modules.notifications.hub import Subscriber, hub
from app.modules.notifications.schemas import Notification
from tests.conftest import API, admin_tokens, agent_tokens, customer2_tokens, customer_tokens, headers  # noqa: F401


@pytest.fixture
def clean_hub():
    """Snapshot/restore the process-wide hub so tests never see each other's streams."""
    saved = dict(hub._subscribers)
    yield hub
    hub._subscribers.clear()
    hub._subscribers.update(saved)


def create_ticket(client, tokens, title="Notify me", **overrides):
    payload = {"title": title, "description": "Details about the problem.", "priority": "medium", **overrides}
    return client.post(f"{API}/tickets", json=payload, headers=headers(tokens))


def claim(client, tokens, ticket_id):
    return client.post(f"{API}/tickets/{ticket_id}/claim", headers=headers(tokens))


def user_id(client, tokens) -> int:
    return client.get(f"{API}/users/me", headers=headers(tokens)).json()["id"]


def subscribe(user_id: int) -> Subscriber:
    return hub.subscribe(user_id)


def drain(subscriber: Subscriber) -> list[dict]:
    items = []
    while not subscriber.queue.empty():
        items.append(subscriber.queue.get_nowait().model_dump(mode="json"))
    return items


# ---------- The stream endpoint ----------


def test_stream_requires_auth(client):
    assert client.get(f"{API}/notifications/stream").status_code == 401
    assert client.get(f"{API}/notifications/stream?token=not-a-jwt").status_code == 401


def test_stream_connects_with_header_or_query_token(client, session, customer_tokens):
    """The endpoint accepts both auth styles and answers with an SSE StreamingResponse.
    Invoked directly: starlette 1.6's TestClient runs an app call to completion, so an
    infinite SSE stream cannot be opened over the test HTTP transport at all — the
    frame shape is covered by the bounded async unit test below."""
    token = customer_tokens["access_token"]
    from fastapi.security import HTTPAuthorizationCredentials

    async def call():
        with_header = await notifications_router.stream(
            session=session,
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
            token=None,
        )
        with_query = await notifications_router.stream(session=session, credentials=None, token=token)
        return with_header, with_query

    with_header, with_query = asyncio.run(call())
    for response in (with_header, with_query):
        assert response.status_code == 200
        assert response.media_type == "text/event-stream"
    # The response body was never consumed, so _stream's finally never ran and the
    # subscriber is still registered — remove it explicitly (test-only leak).
    hub._subscribers.pop(user_id(client, customer_tokens), None)


def test_sse_frames_connect_event_and_keepalive_shape():
    """The wire shape: `: connected`, then event/data frames, then keep-alive comments."""

    async def scenario():
        subscriber = hub.subscribe(4242)
        frames = notifications_router._stream(subscriber)
        first = await frames.__anext__()
        assert first == ": connected\n\n"

        subscriber.queue.put_nowait(
            Notification(type="ticket.created", at="2026-09-17T12:00:00Z", payload={"ticket_id": 1})
        )
        event_frame = await frames.__anext__()
        assert event_frame.startswith("event: ticket.created\ndata: ")
        assert event_frame.endswith("\n\n")
        assert '"ticket_id":1' in event_frame.replace(" ", "")

        # Idle past the keep-alive timeout → comment frame, stream stays open.
        notifications_router._KEEPALIVE_SECONDS = 0.01
        try:
            keepalive = await asyncio.wait_for(frames.__anext__(), timeout=2)
        finally:
            notifications_router._KEEPALIVE_SECONDS = 15
        assert keepalive == ": keep-alive\n\n"

        await frames.aclose()  # finally → hub.unsubscribe

    asyncio.run(scenario())
    assert 4242 not in hub._subscribers  # the finally in _stream removed this stream


# ---------- Emission gating (publish only after commit) ----------


def test_notifications_publish_only_after_commit(client, session, agent_tokens, customer_tokens):
    """Direct seam test: notify() queues on the session; only commit/drain publishes.
    (create_ticket already queued the real automatic emission — that one is
    committed and drained first so the gate is tested in isolation.)"""
    from app.modules.tickets import service as tickets_service
    from app.modules.users import service as users_service

    agent_id = user_id(client, agent_tokens)
    agent = subscribe(agent_id)
    ticket = create_ticket(client, customer_tokens).json()
    session.commit()  # publishes the automatic emission
    assert [n["type"] for n in drain(agent)] == ["ticket.created"]

    actor = users_service.get_active(session, user_id(client, customer_tokens))
    target = tickets_service.get_ticket(session, users_service.get_active(session, agent_id), ticket["id"])

    notifications_service.notify(
        session, actor=actor, ticket=target, notification_type="ticket.created", payload={"ticket_id": ticket["id"]}
    )
    assert drain(agent) == []  # armed but gated — nothing published before commit

    session.commit()  # what the app's get_session does after a successful request
    queued = drain(agent)
    assert [n["type"] for n in queued] == ["ticket.created"]
    assert queued[0]["payload"]["ticket_id"] == ticket["id"]


def test_rollback_discards_queued_notifications(client, session, agent_tokens, customer_tokens):
    from app.modules.tickets import service as tickets_service
    from app.modules.users import service as users_service

    agent = subscribe(user_id(client, agent_tokens))
    ticket = create_ticket(client, customer_tokens).json()
    actor = users_service.get_active(session, user_id(client, customer_tokens))
    target = tickets_service.get_ticket(session, actor, ticket["id"])

    notifications_service.notify(
        session, actor=actor, ticket=target, notification_type="ticket.created", payload={"ticket_id": ticket["id"]}
    )
    session.rollback()
    assert drain(agent) == []


# ---------- Business emissions (milestone recipients) ----------


def test_agent_notified_on_new_ticket(client, session, agent_tokens, customer_tokens):
    agent_id = user_id(client, agent_tokens)
    agent = subscribe(agent_id)
    ticket = create_ticket(client, customer_tokens, priority="high").json()
    session.commit()  # production commits after the request; the test harness needs it explicit

    queued = drain(agent)
    assert [n["type"] for n in queued] == ["ticket.created"]
    assert queued[0]["payload"]["ticket_id"] == ticket["id"]
    assert queued[0]["payload"]["priority"] == "high"


def test_actor_is_never_notified(client, session, customer_tokens):
    customer = subscribe(user_id(client, customer_tokens))
    create_ticket(client, customer_tokens)
    session.commit()
    assert drain(customer) == []  # you don't hear about your own action


def test_customer_notified_on_status_update(client, session, agent_tokens, customer_tokens):
    customer_id = user_id(client, customer_tokens)
    customer = subscribe(customer_id)
    ticket = create_ticket(client, customer_tokens).json()
    session.commit()
    drain(customer)  # discard the (agent-targeted) created event if any

    claim(client, agent_tokens, ticket["id"])
    session.commit()

    queued = drain(customer)
    assert [n["type"] for n in queued] == ["ticket.updated"]
    assert queued[0]["payload"]["status"] == "in_progress"


def test_agent_notified_when_customer_closes_ticket(client, session, agent_tokens, customer_tokens):
    agent = subscribe(user_id(client, agent_tokens))
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])
    session.commit()
    drain(agent)

    client.post(f"{API}/tickets/{ticket['id']}/close", headers=headers(customer_tokens))
    session.commit()

    queued = drain(agent)
    assert [n["type"] for n in queued] == ["ticket.updated"]
    assert queued[0]["payload"]["status"] == "closed"


def test_message_created_notifies_other_participant_via_rest_and_ws(client, session, agent_tokens, customer_tokens):
    agent_id = user_id(client, agent_tokens)
    agent = subscribe(agent_id)
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])
    session.commit()
    drain(agent)

    client.post(f"{API}/tickets/{ticket['id']}/messages", json={"body": "rest ping"}, headers=headers(customer_tokens))
    session.commit()
    queued = drain(agent)
    assert [n["type"] for n in queued] == ["message.created"]
    assert queued[0]["payload"]["body"] == "rest ping"

    # Same emission from the WebSocket path (the handler commits per frame itself).
    ws_url = f"{API}/tickets/{ticket['id']}/ws?token={customer_tokens['access_token']}"
    with client.websocket_connect(ws_url) as ws:
        ws.receive_json()  # connect.ack
        ws.send_text(json.dumps({"type": "message.send", "body": "ws ping"}))
        ws.receive_json()  # own message.new echo
    queued = drain(agent)
    assert [n["type"] for n in queued] == ["message.created"]
    assert queued[0]["payload"]["body"] == "ws ping"


def test_admins_are_never_notified(client, session, admin_tokens, agent_tokens, customer_tokens):
    admin = subscribe(user_id(client, admin_tokens))
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])
    client.post(f"{API}/tickets/{ticket['id']}/messages", json={"body": "hi"}, headers=headers(agent_tokens))
    session.commit()
    assert drain(admin) == []


def test_multiple_streams_same_user_all_notified(client, session, agent_tokens, customer_tokens):
    agent_id = user_id(client, agent_tokens)
    first, second = subscribe(agent_id), subscribe(agent_id)
    create_ticket(client, customer_tokens)
    session.commit()
    assert len(drain(first)) == 1
    assert len(drain(second)) == 1


def test_deactivated_agents_not_notified(client, session, admin_tokens, agent_tokens, customer_tokens, customer2_tokens):
    agent_id = user_id(client, agent_tokens)
    agent = subscribe(agent_id)
    client.patch(
        f"{API}/users/{agent_id}/status", json={"is_active": False}, headers=headers(admin_tokens)
    )
    create_ticket(client, customer_tokens)
    session.commit()
    assert drain(agent) == []  # subscription set resolves active agents only
