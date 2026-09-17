"""M4: confirmation emails (Celery on the Redis broker, ADR 0006).

Hermetic by design: the enqueue seam is tested with a stubbed `.delay()`, so
no broker is needed. The task→delivery path is tested by calling the task's
run function directly (a worker is exercised in the live smoke, not pytest).
"""

import logging

from app.modules.emails import tasks
from app.modules.tickets import service as tickets_service
from app.modules.tickets.models import Ticket
from app.modules.users import service as users_service
from tests.conftest import API, customer_tokens, headers  # noqa: F401


def make_customer(session):
    """A real customer row in the harness DB (it starts empty every test)."""
    import itertools

    counter = getattr(make_customer, "_n", 0) + 1
    make_customer._n = counter
    return users_service.create_customer(
        session,
        email=f"mailer{counter}@example.com",
        password="passw0rd!",
        full_name="Mail Tester",
    )


def test_enqueue_is_commit_gated_and_rollback_discards(session, monkeypatch):
    """The same discipline as notifications: the queue fills at request time,
    publishes exactly on commit; a rollback discards it."""
    published = []
    monkeypatch.setattr(tasks.send_ticket_confirmation, "delay", lambda *a: published.append(a))

    customer = make_customer(session)
    session.commit()  # persist the user first (queue is empty — nothing publishes)

    tickets_service.create_ticket(session, customer=customer, title="Email smoke", description="d", priority="medium")
    assert session.info.get(tasks._QUEUE_KEY), "request staged pre-commit"
    assert published == [], "nothing published before the commit"

    session.commit()  # plays get_session's commit-on-success
    assert len(published) == 1
    to, ticket_id, title = published[0]
    assert to.endswith("@example.com")
    assert title == "Email smoke"


def test_rollback_discards_the_email(session, monkeypatch):
    published = []
    monkeypatch.setattr(tasks.send_ticket_confirmation, "delay", lambda *a: published.append(a))

    customer = make_customer(session)
    session.commit()
    tickets_service.create_ticket(session, customer=customer, title="Never sent", description="d", priority="low")
    session.rollback()
    assert session.info.get(tasks._QUEUE_KEY) is None
    assert published == []


def test_enqueue_fails_open_without_broker(session, monkeypatch, caplog):
    """A broker outage logs once and never raises — the ticket already exists."""
    tasks._outage.reset()

    def boom(*_a):
        raise ConnectionError("broker down")

    monkeypatch.setattr(tasks.send_ticket_confirmation, "delay", boom)
    customer = make_customer(session)
    session.commit()
    tickets_service.create_ticket(session, customer=customer, title="Broker down", description="d", priority="low")
    with caplog.at_level(logging.WARNING, logger="app.modules.emails.tasks"):
        session.commit()  # after_commit runs _flush → .delay raises → swallowed
    assert any("fail-open" in r.message for r in caplog.records)


def test_task_delivers_via_console_backend(caplog):
    """Calling the task's run function directly: delivery renders + logs."""
    with caplog.at_level(logging.INFO, logger="app.modules.emails.delivery"):
        tasks.send_ticket_confirmation.run("lena@example.com", 42, "Printer on fire")
    assert any("EMAIL to=lena@example.com" in r.message for r in caplog.records)
    assert any("Ticket #42" in r.message for r in caplog.records)


def test_emails_disabled_skips_queueing(session, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.emails_enabled", False)
    ticket = Ticket(id=999, customer_id=1, title="t", description="d")
    tasks.queue_confirmation(session, ticket=ticket, to="x@example.com")
    assert session.info.get(tasks._QUEUE_KEY) is None
