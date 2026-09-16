"""Demo data: one admin (from settings), two Support Agents, two Customers, and a
handful of tickets across the lifecycle. Idempotent — skips when the admin exists.

Run: python -m app.seeds.demo
"""

from sqlmodel import Session

from app.core.config import settings
from app.core.database import engine
from app.modules.tickets.models import Ticket, TicketPriority, TicketStatus
from app.modules.users import service as users
from app.modules.users.models import Role, User

AGENTS = [
    ("maya.chen@supportsflow.local", "Maya Chen"),
    ("omar.hassan@supportsflow.local", "Omar Hassan"),
]
CUSTOMERS = [
    ("lena@example.com", "Lena Fischer"),
    ("tom@example.com", "Tom Alvarez"),
]
TICKETS = [
    ("Cannot reset my password", "The reset email never arrives, checked spam too.", TicketPriority.HIGH, None, None),
    ("Billing shows duplicate charge", "I was charged twice for the September invoice.", TicketPriority.HIGH, 1, TicketStatus.IN_PROGRESS),
    ("Dark mode toggle missing", "Can't find the dark mode switch in settings.", TicketPriority.LOW, None, None),
    ("Export to CSV broken", "Export button spins forever and produces an empty file.", TicketPriority.MEDIUM, 1, TicketStatus.RESOLVED),
    ("Feature request: keyboard shortcuts", "Would love shortcuts for the ticket queue.", TicketPriority.LOW, 2, TicketStatus.IN_PROGRESS),
]


def run() -> None:
    with Session(engine) as session:
        if users.get_by_email(session, settings.admin_email) is not None:
            print("Seed skipped: admin already exists")
            return

        admin = users.create_staff(
            session,
            email=settings.admin_email,
            password=settings.admin_password.get_secret_value(),
            full_name="SupportSync Admin",
            role=Role.ADMIN,
        )
        agent_rows = [
            users.create_staff(session, email=email, password="agent123!", full_name=name, role=Role.AGENT)
            for email, name in AGENTS
        ]
        customer_rows = [
            users.create_customer(session, email=email, password="customer123!", full_name=name)
            for email, name in CUSTOMERS
        ]

        for title, description, priority, agent_index, status in TICKETS:
            ticket = Ticket(
                customer_id=customer_rows[0].id,
                agent_id=agent_rows[agent_index].id if agent_index is not None else None,
                title=title,
                description=description,
                priority=priority,
                status=status or TicketStatus.OPEN,
            )
            session.add(ticket)

        session.commit()
        print(f"Seeded: 1 admin ({admin.email}), {len(agent_rows)} agents, {len(customer_rows)} customers, {len(TICKETS)} tickets")


if __name__ == "__main__":
    run()
