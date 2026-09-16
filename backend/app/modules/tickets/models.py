from datetime import datetime
from enum import StrEnum

from sqlalchemy import Column, DateTime, Enum as SAEnum, String, Text
from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Ticket(SQLModel, table=True):
    __tablename__ = "tickets"

    id: int | None = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="users.id")
    agent_id: int | None = Field(default=None, foreign_key="users.id")
    title: str = Field(sa_column=Column(String(200), nullable=False))
    description: str = Field(sa_column=Column(Text, nullable=False))
    status: TicketStatus = Field(
        default=TicketStatus.OPEN,
        sa_column=Column(SAEnum(TicketStatus, name="ticket_status", native_enum=False, length=20), nullable=False, index=True),
    )
    priority: TicketPriority = Field(
        default=TicketPriority.MEDIUM,
        sa_column=Column(SAEnum(TicketPriority, name="ticket_priority", native_enum=False, length=20), nullable=False, index=True),
    )
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False))
    closed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    __table_args__ = ()
