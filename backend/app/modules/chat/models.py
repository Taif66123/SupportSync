from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: int | None = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="tickets.id")
    sender_id: int = Field(sa_column=Column(ForeignKey("users.id"), nullable=False))
    body: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False))

    __table_args__ = (Index("ix_messages_ticket_created", "ticket_id", "created_at"),)


class TicketReadState(SQLModel, table=True):
    """Per-participant read marker for ticket chat.

    One row per (ticket, user): the id of the last message that user has seen.
    Scales with participants (2 per ticket), not messages. Rows are created lazily
    on first receipt; only chat participants (customer + assigned agent) track read
    state — admins are read-only observers and never do.
    """

    __tablename__ = "ticket_read_states"
    __table_args__ = (UniqueConstraint("ticket_id", "user_id", name="uq_read_state_ticket_user"),)

    id: int | None = Field(default=None, primary_key=True)
    ticket_id: int = Field(
        sa_column=Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    )
    user_id: int = Field(sa_column=Column(Integer, ForeignKey("users.id"), nullable=False))
    last_read_message_id: int = Field(sa_column=Column(Integer, ForeignKey("messages.id"), nullable=False))
    updated_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False))
