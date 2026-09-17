import json

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.conftest import API, agent_tokens, customer2_tokens, customer_tokens, headers  # noqa: F401


def create_ticket(client, tokens, title="Chat with me"):
    return client.post(
        f"{API}/tickets",
        json={"title": title, "description": "Details about the problem.", "priority": "medium"},
        headers=headers(tokens),
    )


def claim(client, tokens, ticket_id):
    return client.post(f"{API}/tickets/{ticket_id}/claim", headers=headers(tokens))


def ws_url(ticket_id, tokens):
    # Relative URL required: starlette 1.6's TestClient drops the upgrade on absolute ws URLs.
    return f"{API}/tickets/{ticket_id}/ws?token={tokens['access_token']}"


def send_frame(client, url, frame):
    """One-shot WS client: connect, optionally send a frame, return the frames received."""
    with client.websocket_connect(url) as ws:
        received = [ws.receive_json()]  # connect.ack always arrives first
        if frame is not None:
            ws.send_text(json.dumps(frame))
            received.append(ws.receive_json())
    return received


# ---------- REST history: authorization ----------


def test_history_requires_auth(client, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    assert client.get(f"{API}/tickets/{ticket['id']}/messages").status_code == 401


def test_history_invisible_to_strangers(client, customer_tokens, customer2_tokens, agent_tokens):
    """Not a participant → 404, indistinguishable from a nonexistent ticket."""
    ticket = create_ticket(client, customer_tokens).json()

    stranger = client.get(f"{API}/tickets/{ticket['id']}/messages", headers=headers(customer2_tokens))
    assert stranger.status_code == 404

    unassigned_agent = client.get(f"{API}/tickets/{ticket['id']}/messages", headers=headers(agent_tokens))
    assert unassigned_agent.status_code == 404


def test_history_for_participants_and_admin(client, admin_tokens, agent_tokens, customer_tokens, customer2_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])

    for tokens in (customer_tokens, agent_tokens, admin_tokens):
        response = client.get(f"{API}/tickets/{ticket['id']}/messages", headers=headers(tokens))
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 0


def test_history_is_chronological_and_paginated(client, agent_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])
    for i in range(5):
        client.post(
            f"{API}/tickets/{ticket['id']}/messages",
            json={"body": f"msg {i}"},
            headers=headers(customer_tokens),
        )

    page = client.get(f"{API}/tickets/{ticket['id']}/messages?limit=3&offset=0", headers=headers(customer_tokens)).json()
    assert page["total"] == 5 and len(page["items"]) == 3
    assert [m["body"] for m in page["items"]] == ["msg 0", "msg 1", "msg 2"]

    page2 = client.get(f"{API}/tickets/{ticket['id']}/messages?limit=3&offset=3", headers=headers(customer_tokens)).json()
    assert [m["body"] for m in page2["items"]] == ["msg 3", "msg 4"]


# ---------- REST history: closed tickets ----------


def test_closed_ticket_history_stays_readable(client, agent_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])
    client.post(f"{API}/tickets/{ticket['id']}/messages", json={"body": "before close"}, headers=headers(customer_tokens))
    client.post(f"{API}/tickets/{ticket['id']}/close", headers=headers(customer_tokens))

    response = client.get(f"{API}/tickets/{ticket['id']}/messages", headers=headers(agent_tokens))
    assert response.status_code == 200
    assert [m["body"] for m in response.json()["items"]] == ["before close"]


# ---------- REST posting (same authorization as the socket) ----------


def test_rest_post_participants_only(client, agent_tokens, customer_tokens, customer2_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])

    ok = client.post(f"{API}/tickets/{ticket['id']}/messages", json={"body": "hello"}, headers=headers(customer_tokens))
    assert ok.status_code == 201
    assert ok.json()["sender_id"] == client.get(f"{API}/users/me", headers=headers(customer_tokens)).json()["id"]

    stranger = client.post(f"{API}/tickets/{ticket['id']}/messages", json={"body": "hi"}, headers=headers(customer2_tokens))
    assert stranger.status_code == 404


def test_rest_post_rejected_on_closed_ticket(client, agent_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])
    client.post(f"{API}/tickets/{ticket['id']}/close", headers=headers(customer_tokens))

    response = client.post(f"{API}/tickets/{ticket['id']}/messages", json={"body": "too late"}, headers=headers(agent_tokens))
    assert response.status_code == 403


def test_rest_post_validates_body(client, agent_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])

    assert client.post(f"{API}/tickets/{ticket['id']}/messages", json={"body": ""}, headers=headers(customer_tokens)).status_code == 422
    assert client.post(f"{API}/tickets/{ticket['id']}/messages", json={"body": "x" * 4001}, headers=headers(customer_tokens)).status_code == 422


# ---------- WebSocket ----------


def test_ws_rejects_bad_token(client, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    url = f"/api/v1/tickets/{ticket['id']}/ws?token=not-a-jwt"
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(url):
            pass


def test_ws_rejects_non_participant_before_accept(client, customer_tokens, customer2_tokens):
    """An invisible ticket must look exactly like a nonexistent one — never 403."""
    ticket = create_ticket(client, customer_tokens).json()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(ws_url(ticket["id"], customer2_tokens)):
            pass


def test_ws_unassigned_agent_rejected(client, agent_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(ws_url(ticket["id"], agent_tokens)):
            pass


def test_ws_connect_ack_and_can_send(client, agent_tokens, customer_tokens, admin_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])

    frames = send_frame(client, ws_url(ticket["id"], customer_tokens), None)
    assert frames[0] == {"type": "connect.ack", "can_send": True}

    # Admin is a read-only observer: connected, but can_send is False.
    frames = send_frame(client, ws_url(ticket["id"], admin_tokens), None)
    assert frames[0] == {"type": "connect.ack", "can_send": False}


def test_ws_message_delivered_instantly_to_room(client, agent_tokens, customer_tokens):
    """Two live sockets in one room: a sender's frame reaches the other participant immediately."""
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])

    with client.websocket_connect(ws_url(ticket["id"], customer_tokens)) as customer_ws:
        assert customer_ws.receive_json() == {"type": "connect.ack", "can_send": True}
        with client.websocket_connect(ws_url(ticket["id"], agent_tokens)) as agent_ws:
            assert agent_ws.receive_json() == {"type": "connect.ack", "can_send": True}

            customer_ws.send_text(json.dumps({"type": "message.send", "body": "hello agent"}))
            delivered = agent_ws.receive_json()
            assert delivered["type"] == "message.new"
            assert delivered["message"]["body"] == "hello agent"
            assert delivered["message"]["ticket_id"] == ticket["id"]

            # The sender also sees their own message echoed back (all room members).
            echoed = customer_ws.receive_json()
            assert echoed["type"] == "message.new"
            assert echoed["message"]["body"] == "hello agent"


def test_ws_message_persists_to_history(client, agent_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])
    send_frame(client, ws_url(ticket["id"], customer_tokens), {"type": "message.send", "body": "remember me"})

    history = client.get(f"{API}/tickets/{ticket['id']}/messages", headers=headers(agent_tokens)).json()
    assert history["total"] == 1
    assert history["items"][0]["body"] == "remember me"


def test_ws_admin_read_only(client, admin_tokens, agent_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])

    frames = send_frame(client, ws_url(ticket["id"], admin_tokens), {"type": "message.send", "body": "observe only"})
    assert frames[1]["type"] == "error"
    assert frames[1]["code"] == "forbidden"

    history = client.get(f"{API}/tickets/{ticket['id']}/messages", headers=headers(customer_tokens)).json()
    assert history["total"] == 0  # nothing was persisted


def test_ws_send_on_closed_ticket_rejected_connection_stays_open(client, agent_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])
    client.post(f"{API}/tickets/{ticket['id']}/close", headers=headers(customer_tokens))

    with client.websocket_connect(ws_url(ticket["id"], customer_tokens)) as ws:
        assert ws.receive_json() == {"type": "connect.ack", "can_send": True}
        ws.send_text(json.dumps({"type": "message.send", "body": "one more?"}))
        error = ws.receive_json()
        assert error == {
            "type": "error",
            "code": "forbidden",
            "message": "this ticket is closed — its chat is read-only",
        }


def test_ws_pre_assignment_messages_buffer(client, agent_tokens, customer_tokens):
    """Customer may chat into an unassigned ticket; messages buffer (history) until claim."""
    ticket = create_ticket(client, customer_tokens).json()
    send_frame(client, ws_url(ticket["id"], customer_tokens), {"type": "message.send", "body": "before claim"})

    claim(client, agent_tokens, ticket["id"])
    history = client.get(f"{API}/tickets/{ticket['id']}/messages", headers=headers(agent_tokens)).json()
    assert [m["body"] for m in history["items"]] == ["before claim"]


# ---------- Read receipts ----------


def test_read_receipt_broadcast_and_rest_states(client, agent_tokens, customer_tokens, admin_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])
    agent_id = client.get(f"{API}/users/me", headers=headers(agent_tokens)).json()["id"]

    # No markers until somebody reads.
    states = client.get(f"{API}/tickets/{ticket['id']}/messages/read-states", headers=headers(customer_tokens))
    assert states.status_code == 200 and states.json() == []

    sent = client.post(f"{API}/tickets/{ticket['id']}/messages", json={"body": "please read"}, headers=headers(customer_tokens))
    message_id = sent.json()["id"]

    frames = send_frame(client, ws_url(ticket["id"], agent_tokens), {"type": "read.up-to", "message_id": message_id})
    assert frames[1] == {"type": "read.receipt", "user_id": agent_id, "message_id": message_id}

    states = client.get(f"{API}/tickets/{ticket['id']}/messages/read-states", headers=headers(customer_tokens)).json()
    assert len(states) == 1
    assert states[0]["user_id"] == agent_id
    assert states[0]["last_read_message_id"] == message_id

    # Admin is a read-only observer: may view read states, but never generates them.
    admin_view = client.get(f"{API}/tickets/{ticket['id']}/messages/read-states", headers=headers(admin_tokens))
    assert admin_view.status_code == 200


def test_read_up_to_reaches_other_participant_live(client, agent_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])
    agent_id = client.get(f"{API}/users/me", headers=headers(agent_tokens)).json()["id"]

    with client.websocket_connect(ws_url(ticket["id"], customer_tokens)) as customer_ws:
        assert customer_ws.receive_json() == {"type": "connect.ack", "can_send": True}
        customer_ws.send_text(json.dumps({"type": "message.send", "body": "receipts test"}))
        message_id = customer_ws.receive_json()["message"]["id"]

        with client.websocket_connect(ws_url(ticket["id"], agent_tokens)) as agent_ws:
            assert agent_ws.receive_json() == {"type": "connect.ack", "can_send": True}
            agent_ws.send_text(json.dumps({"type": "read.up-to", "message_id": message_id}))
            # The receipt goes to the whole room, including the reader...
            assert agent_ws.receive_json() == {"type": "read.receipt", "user_id": agent_id, "message_id": message_id}
            # ...and the other participant sees the same receipt.
            assert customer_ws.receive_json() == {"type": "read.receipt", "user_id": agent_id, "message_id": message_id}


def test_read_up_to_monotonic_and_silent(client, agent_tokens, customer_tokens):
    """A repeat or backwards read is a silent no-op — no second receipt is broadcast."""
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])
    ids = [
        client.post(f"{API}/tickets/{ticket['id']}/messages", json={"body": body}, headers=headers(customer_tokens)).json()["id"]
        for body in ("one", "two")
    ]

    with client.websocket_connect(ws_url(ticket["id"], agent_tokens)) as ws:
        assert ws.receive_json() == {"type": "connect.ack", "can_send": True}
        ws.send_text(json.dumps({"type": "read.up-to", "message_id": ids[1]}))
        assert ws.receive_json()["type"] == "read.receipt"

        # Repeat read of the same message: no reply frame at all — the next frame
        # this socket gets is its own receipt for the newer message below.
        ws.send_text(json.dumps({"type": "read.up-to", "message_id": ids[1]}))
        ws.send_text(json.dumps({"type": "read.up-to", "message_id": ids[0]}))  # backwards
        ws.send_text(json.dumps({"type": "message.send", "body": "ping"}))
        next_frame = ws.receive_json()
        assert next_frame["type"] == "message.new"  # nothing about the no-op reads

    states = client.get(f"{API}/tickets/{ticket['id']}/messages/read-states", headers=headers(customer_tokens)).json()
    assert states[0]["last_read_message_id"] == ids[1]  # marker never moved backwards


def test_read_up_to_authorization(client, agent_tokens, customer_tokens, customer2_tokens, admin_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])
    other_ticket = create_ticket(client, customer_tokens, title="second").json()
    claim(client, agent_tokens, other_ticket["id"])
    other_message = client.post(f"{API}/tickets/{other_ticket['id']}/messages", json={"body": "x"}, headers=headers(customer_tokens)).json()["id"]

    # Admin: connected observer, but receipts use the send rules.
    frames = send_frame(client, ws_url(ticket["id"], admin_tokens), {"type": "read.up-to", "message_id": 1})
    assert frames[1]["type"] == "error" and frames[1]["code"] == "forbidden"

    # Stranger: invisible ticket, indistinguishable from nonexistent.
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(ws_url(ticket["id"], customer2_tokens)):
            pass

    # Participant, but the message belongs to a different ticket → not_found.
    frames = send_frame(client, ws_url(ticket["id"], agent_tokens), {"type": "read.up-to", "message_id": other_message})
    assert frames[1]["type"] == "error" and frames[1]["code"] == "not_found"


# ---------- Typing indicators (ephemeral) ----------


def test_ws_typing_broadcast_to_others_not_typist(client, agent_tokens, customer_tokens):
    """Others in the room see the typing update; the typist is not echoed, proven by
    their next received frame being their own message.new (not a typing frame)."""
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])
    customer_id = client.get(f"{API}/users/me", headers=headers(customer_tokens)).json()["id"]

    with client.websocket_connect(ws_url(ticket["id"], customer_tokens)) as customer_ws:
        assert customer_ws.receive_json() == {"type": "connect.ack", "can_send": True}
        with client.websocket_connect(ws_url(ticket["id"], agent_tokens)) as agent_ws:
            assert agent_ws.receive_json() == {"type": "connect.ack", "can_send": True}

            customer_ws.send_text(json.dumps({"type": "typing.start"}))
            assert agent_ws.receive_json() == {"type": "typing.start", "user_id": customer_id}

            customer_ws.send_text(json.dumps({"type": "message.send", "body": "typed then sent"}))
            assert customer_ws.receive_json()["type"] == "message.new"  # no typing echo came first
            delivered = agent_ws.receive_json()
            assert delivered["type"] == "message.new"
            assert delivered["message"]["body"] == "typed then sent"


def test_ws_typing_not_persisted(client, agent_tokens, customer_tokens):
    """typing.start never lands in history — and the sender gets no reply for it."""
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])

    with client.websocket_connect(ws_url(ticket["id"], customer_tokens)) as ws:
        assert ws.receive_json() == {"type": "connect.ack", "can_send": True}
        ws.send_text(json.dumps({"type": "typing.start"}))
        # No response of any kind; the very next frame must be the message echo.
        ws.send_text(json.dumps({"type": "message.send", "body": "real message"}))
        frame = ws.receive_json()
        assert frame["type"] == "message.new"
        assert frame["message"]["body"] == "real message"

    history = client.get(f"{API}/tickets/{ticket['id']}/messages", headers=headers(agent_tokens)).json()
    assert history["total"] == 1  # only the real message


def test_ws_typing_rejected_on_closed_ticket(client, agent_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])
    client.post(f"{API}/tickets/{ticket['id']}/close", headers=headers(customer_tokens))

    frames = send_frame(client, ws_url(ticket["id"], customer_tokens), {"type": "typing.start"})
    assert frames[1] == {
        "type": "error",
        "code": "forbidden",
        "message": "this ticket is closed — its chat is read-only",
    }


def test_ws_admin_cannot_type(client, admin_tokens, agent_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    claim(client, agent_tokens, ticket["id"])

    frames = send_frame(client, ws_url(ticket["id"], admin_tokens), {"type": "typing.start"})
    assert frames[1]["type"] == "error"
    assert frames[1]["code"] == "forbidden"


def test_ws_rejects_malformed_frames(client, customer_tokens):
    ticket = create_ticket(client, customer_tokens).json()
    with client.websocket_connect(ws_url(ticket["id"], customer_tokens)) as ws:
        assert ws.receive_json()["type"] == "connect.ack"

        ws.send_text("this is not json")
        assert ws.receive_json()["code"] == "invalid_json"

        ws.send_text(json.dumps({"type": "message.typing"}))
        assert ws.receive_json()["code"] == "unknown_type"

        ws.send_text(json.dumps({"type": "message.send", "body": ""}))
        assert ws.receive_json()["code"] == "invalid_body"
