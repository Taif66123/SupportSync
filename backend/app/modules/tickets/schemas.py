from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.tickets.models import TicketPriority, TicketStatus


class TicketCreateIn(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    priority: TicketPriority


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    agent_id: int | None
    title: str
    description: str
    status: TicketStatus
    priority: TicketPriority
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None


class TicketFilter(BaseModel):
    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    mine: bool = False  # agents/admins: only tickets assigned to me (no-op for customers, who only see their own)


class AssignIn(BaseModel):
    agent_id: int


class PriorityIn(BaseModel):
    priority: TicketPriority
