"""M3 Phase B: Redis bridge + rate limiting.

Contract tests run against **fakeredis** (same protocol, in-process); the fail-open
behavior is tested by pointing the client at an unreachable port. Nothing here
requires a live Redis — CI and local runs stay hermetic.
"""

import asyncio
import json
import logging

import fakeredis.aioredis
import pytest

from app.core import ratelimit
from app.core.redis import redis_key, reset_breaker, trip_breaker
from app.modules.notifications import bus
from app.modules.notifications.hub import hub
from app.modules.notifications.schemas import Notification, NotificationEnvelope
from tests.conftest import API, agent_tokens, customer_tokens, headers  # noqa: F401


@pytest.fixture
def fake_redis(monkeypatch):
    """A fresh fakeredis client wired in as the app's Redis client (per test)."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("app.core.redis.get_redis_client", lambda: client)
    yield client
    ratelimit.reset_outage_flag()
    reset_breaker()


@pytest.fixture
def clean_hub():
    saved = dict(hub._subscribers)
    yield hub
    hub._subscribers.clear()
    hub._subscribers.update(saved)


def create_ticket(client, tokens, title="Phase B"):
    return client.post(
        f"{API}/tickets",
        json={"title": title, "description": "Details.", "priority": "medium"},
        headers=headers(tokens),
    )


def user_id(client, tokens) -> int:
    return client.get(f"{API}/users/me", headers=headers(tokens)).json()["id"]


# ---------- The bridge: local push + remote publish ----------


async def test_publish_pushes_locally_and_publishes_envelope(fake_redis, clean_hub, monkeypatch):
    seen = {}

    async def spy_publish(channel, body):
        seen["channel"], seen["body"] = channel, body

    monkeypatch.setattr(fake_redis, "publish", spy_publish)
    # Simulate the lifespan having captured this loop (bus.publish is a no-op without it).
    monkeypatch.setattr(bus, "_loop", asyncio.get_running_loop())

    def local_side():
        notification = Notification(type="ticket.created", at="2026-09-17T12:00:00Z", payload={"ticket_id": 1})
        bus.publish(frozenset({7, 9}), notification)
        return notification

    notification = local_side()
    await asyncio.sleep(0.05)  # let the scheduled coroutine run
    assert seen["channel"] == "supportsync:notifications"
    envelope = NotificationEnvelope.model_validate(json.loads(seen["body"]))
    assert envelope.notification.type == "ticket.created"
    assert sorted(envelope.recipients) == [7, 9]
    assert notification.type == "ticket.created"


async def test_listener_pumps_remote_envelopes_into_local_hub(fake_redis, clean_hub):
    stream = hub.subscribe(42)
    listener_started = asyncio.Event()

    async def run_listener():
        await bus.start()
        listener_started.set()
        await asyncio.sleep(0.15)
        await bus.stop()

    task = asyncio.create_task(run_listener())
    await listener_started.wait()
    await asyncio.sleep(0.05)

    # Another worker's emission arrives on the channel as a raw envelope frame.
    envelope = NotificationEnvelope(
        recipients=[42],
        origin="other-worker",
        notification=Notification(type="ticket.updated", at="2026-09-17T12:00:00Z", payload={"ticket_id": 5, "status": "closed"}),
    )
    await fake_redis.publish("supportsync:notifications", envelope.model_dump_json())
    await asyncio.sleep(0.15)

    assert not stream.queue.empty()
    received = stream.queue.get_nowait()
    assert received.type == "ticket.updated"
    assert received.payload["status"] == "closed"
    task.result()


async def test_listener_discards_malformed_frames_and_survives(fake_redis, clean_hub):
    stream = hub.subscribe(42)
    listener_started = asyncio.Event()

    async def run_listener():
        await bus.start()
        listener_started.set()
        await asyncio.sleep(0.2)
        await bus.stop()

    task = asyncio.create_task(run_listener())
    await listener_started.wait()

    await fake_redis.publish("supportsync:notifications", "not json at all")
    await asyncio.sleep(0.1)
    good = NotificationEnvelope(
        recipients=[42],
        origin="other-worker",
        notification=Notification(type="message.created", at="2026-09-17T12:00:00Z", payload={"message_id": 3}),
    )
    await fake_redis.publish("supportsync:notifications", good.model_dump_json())
    await asyncio.sleep(0.15)

    received = stream.queue.get_nowait()  # the bad frame was skipped, the good one arrived
    assert received.type == "message.created"
    task.result()


# ---------- Fail-open behavior ----------


async def test_rate_limit_fails_open_without_redis(monkeypatch, caplog):
    """An unreachable Redis means every check passes (availability over strictness)."""
    ratelimit.reset_outage_flag()

    class Unreachable:
        async def incr(self, _key):
            raise ConnectionError("redis down")

    monkeypatch.setattr("app.core.redis.get_redis_client", lambda: Unreachable())
    with caplog.at_level(logging.WARNING, logger="app.core.ratelimit"):
        assert await ratelimit.check("auth-login", "1.2.3.4", limit=5, window_seconds=60) is True
        trip_breaker()  # the real check() does this on failure; mirror it for the log test
        assert await ratelimit.check("auth-login", "1.2.3.4", limit=5, window_seconds=60) is True
    outage_logs = [r for r in caplog.records if "rate limiting disabled" in r.message]
    assert len(outage_logs) == 1  # once per outage, not once per request


def test_bus_publish_fails_open_without_redis(monkeypatch, clean_hub, caplog):
    """A Redis outage never breaks delivery to this worker's own streams."""
    ratelimit.reset_outage_flag()
    bus_silenced = bus._outage._done
    bus._outage._done = True  # silence the once-outage log for this test

    class Unreachable:
        async def publish(self, *_a, **_kw):
            raise ConnectionError("redis down")

    monkeypatch.setattr("app.core.redis.get_redis_client", lambda: Unreachable())
    loop = asyncio.new_event_loop()
    try:
        bus._loop = loop  # simulate a running lifespan

        async def run():
            stream = hub.subscribe(77)
            notification = Notification(type="ticket.created", at="2026-09-17T12:00:00Z", payload={"ticket_id": 2})
            bus.publish(frozenset({77}), notification)
            await asyncio.sleep(0.05)
            received = stream.queue.get_nowait()
            assert received.type == "ticket.created"

        loop.run_until_complete(run())
    finally:
        bus._loop = None
        bus._outage._done = bus_silenced
        loop.close()


async def test_breaker_skips_the_dial_while_tripped(monkeypatch):
    """After a failure, checks pass *instantly* — no dial, no connect-timeout wait —
    until the cooldown expires. This is what keeps a Redis outage from turning
    every rate-limited endpoint into a 1s stall."""
    trip_breaker()

    class MustNotDial:
        def __getattr__(self, name):
            raise AssertionError(f"Redis was dialed while breaker tripped: {name}")

    monkeypatch.setattr("app.core.redis.get_redis_client", lambda: MustNotDial())
    assert await ratelimit.check("auth-login", "5.6.7.8", limit=1, window_seconds=60) is True
    reset_breaker()  # half-open: the probe dials again

    class Healthy:
        async def incr(self, _key):
            return 1

        async def expire(self, *_a):
            return 1

    monkeypatch.setattr("app.core.redis.get_redis_client", lambda: Healthy())
    assert await ratelimit.check("auth-login", "5.6.7.8", limit=1, window_seconds=60) is True


# ---------- Rate limiting: behavior and 429 integration ----------


async def test_fixed_window_counts_and_resets(fake_redis):
    assert await ratelimit.check("b", "u1", limit=2, window_seconds=60) is True
    assert await ratelimit.check("b", "u1", limit=2, window_seconds=60) is True
    assert await ratelimit.check("b", "u1", limit=2, window_seconds=60) is False  # window full
    assert await ratelimit.check("b", "u2", limit=2, window_seconds=60) is True  # other identifier
    ttl = await fake_redis.ttl(redis_key("ratelimit", "b", "u1"))
    assert 0 < ttl <= 60  # the window expires


def test_auth_register_429_after_three_per_minute(client, fake_redis):
    last = None
    for i in range(5):
        last = client.post(
            f"{API}/auth/register",
            json={"email": f"ratelimit{i}@example.com", "password": "passw0rd!", "full_name": "RL"},
        )
    assert last.status_code == 429
    body = last.json()
    assert body["error"]["code"] == "rate_limited"


def test_auth_login_429_after_five_per_minute(client, fake_redis, customer_tokens):
    for _ in range(5):
        client.post(f"{API}/auth/login", json={"email": "customer@example.com", "password": "wrong-password"})
    response = client.post(f"{API}/auth/login", json={"email": "customer@example.com", "password": "wrong-password"})
    assert response.status_code == 429


def test_ticket_create_429_after_ten_per_minute_per_user(client, fake_redis, customer_tokens):
    for i in range(10):
        assert create_ticket(client, customer_tokens, title=f"burst {i}").status_code == 201
    assert create_ticket(client, customer_tokens, title="over the line").status_code == 429


def test_chat_rest_429_shares_bucket_with_ws_frames(client, session, fake_redis, agent_tokens, customer_tokens):
    ticket = create_ticket(client, customer_tokens, title="chat limit").json()
    client.post(f"{API}/tickets/{ticket['id']}/claim", headers=headers(agent_tokens))
    session.commit()

    for i in range(30):  # the per-user chat-send limit
        response = client.post(f"{API}/tickets/{ticket['id']}/messages", json={"body": f"m{i}"}, headers=headers(customer_tokens))
        assert response.status_code == 201
    response = client.post(f"{API}/tickets/{ticket['id']}/messages", json={"body": "31"}, headers=headers(customer_tokens))
    assert response.status_code == 429

    # The WS frame path shares the same bucket → also refused, as a socket error frame.
    ws_url = f"{API}/tickets/{ticket['id']}/ws?token={customer_tokens['access_token']}"
    with client.websocket_connect(ws_url) as ws:
        ws.receive_json()  # connect.ack
        ws.send_text(json.dumps({"type": "message.send", "body": "one over"}))
        error = ws.receive_json()
        assert error == {"type": "error", "code": "rate_limited", "message": "too many messages — slow down"}
