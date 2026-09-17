from datetime import UTC, datetime

from sqlalchemy import event
from sqlmodel import Session

from app.modules.notifications import policy
from app.modules.notifications.bus import publish as publish_notification
from app.modules.notifications.policy import NotificationType
from app.modules.notifications.schemas import Notification
from app.modules.tickets.models import Ticket
from app.modules.users.models import User

_QUEUE_KEY = "_notification_queue"


def notify(
    session: Session,
    *,
    actor: User,
    ticket: Ticket,
    notification_type: NotificationType,
    payload: dict,
) -> None:
    """Queue one notification, published only when this session's transaction commits.

    Recipients are resolved once, here, from the real ticket (and the actor is
    subtracted — nobody is notified about their own action). A subscriber's client
    must never hear about data it cannot yet fetch, so publishing is gated on
    after_commit; a rollback silently discards the queue. The queue rides on
    session.info, so its lifecycle is the session's lifecycle.
    """
    recipients = policy.recipients(session, notification_type, ticket) - {actor.id}
    queue = session.info.setdefault(_QUEUE_KEY, [])
    queue.append((recipients, Notification(type=notification_type, at=datetime.now(UTC), payload=payload)))
    _arm_once(session)


def drain(session: Session) -> None:
    """Test seam: publish whatever is queued for this session without waiting for commit."""
    for recipients, notification in session.info.pop(_QUEUE_KEY, []):
        publish_notification(recipients, notification)


def _arm_once(session: Session) -> None:
    if event.contains(session, "after_commit", _publish_queued):
        return
    event.listen(session, "after_commit", _publish_queued)
    event.listen(session, "after_rollback", _discard_queued)


def _publish_queued(session: Session) -> None:
    for recipients, notification in session.info.pop(_QUEUE_KEY, []):
        publish_notification(recipients, notification)


def _discard_queued(session: Session) -> None:
    session.info.pop(_QUEUE_KEY, None)
