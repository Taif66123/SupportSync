"""Ticket-confirmation email: the Celery task + the commit-gated enqueue.

The same discipline as live notifications (M3): queue_confirmation() stashes
the request on session.info and SQLAlchemy's after_commit hook publishes it —
a rolled-back ticket never produces an email. Enqueue failures are fail-open
(ADR 0006): a broker outage logs once and the ticket still succeeds. The task
itself retries with bounded exponential backoff so a dead SMTP host cannot
spin a task forever.
"""

import logging

from sqlalchemy import event
from sqlmodel import Session

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.redis import OutageLog
from app.modules.emails import delivery
from app.modules.tickets.models import Ticket

logger = logging.getLogger(__name__)
_outage = OutageLog()

_QUEUE_KEY = "_email_queue"


@celery_app.task(
    name="emails.send_ticket_confirmation",
    max_retries=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def send_ticket_confirmation(to: str, ticket_id: int, title: str) -> None:
    delivery.send_confirmation(to, ticket_id, title)


def queue_confirmation(session: Session, *, ticket: Ticket, to: str) -> None:
    """Enqueue the confirmation email, published only when this session commits."""
    if not settings.emails_enabled:
        return
    queue = session.info.setdefault(_QUEUE_KEY, [])
    queue.append((to, ticket.id, ticket.title))
    _arm_once(session)


def drain(session: Session) -> None:
    """Test seam: flush the queue without waiting for a commit."""
    _flush(session)


def _arm_once(session: Session) -> None:
    if event.contains(session, "after_commit", _flush):
        return
    event.listen(session, "after_commit", _flush)
    event.listen(session, "after_rollback", _discard_queued)


def _flush(session: Session) -> None:
    for to, ticket_id, title in session.info.pop(_QUEUE_KEY, []):
        try:
            send_ticket_confirmation.delay(to, ticket_id, title)
        except Exception:  # noqa: BLE001 — fail open: the ticket already exists
            _outage.warn(logger, "email broker unreachable — confirmation email skipped (fail-open)")


def _discard_queued(session: Session) -> None:
    session.info.pop(_QUEUE_KEY, None)
