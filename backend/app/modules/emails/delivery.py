"""Pluggable confirmation-email delivery: console in dev, SMTP via env in prod.

Pure rendering + transport — no Celery, no sessions. The console backend
"delivers" by logging, so dev needs no SMTP host; switching to SMTP is a
single env var (`EMAIL_BACKEND=smtp` plus host/from settings).
"""

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def render_confirmation(ticket_id: int, title: str) -> tuple[str, str]:
    subject = f"[SupportSync] Ticket #{ticket_id} received"
    body = (
        f"We received your support ticket and our team is on it.\n\n"
        f"Ticket:  #{ticket_id} — {title}\n"
        f"Status:  open (you can follow progress and chat with the agent in the app).\n\n"
        f"— SupportSync"
    )
    return subject, body


def send_confirmation(to: str, ticket_id: int, title: str) -> None:
    subject, body = render_confirmation(ticket_id, title)

    if settings.email_backend == "console":
        logger.info("EMAIL to=%s\n%s\n%s", to, subject, body)
        return

    if settings.email_backend == "smtp":
        message = EmailMessage()
        message["From"] = settings.email_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=10) as smtp:
            if settings.email_smtp_user:
                smtp.starttls()
                smtp.login(settings.email_smtp_user, settings.email_smtp_password.get_secret_value())
            smtp.send_message(message)
        logger.info("confirmation email sent to %s (ticket #%s)", to, ticket_id)
        return

    raise ValueError(f"unknown EMAIL_BACKEND: {settings.email_backend}")
