from datetime import datetime
from enum import StrEnum

from sqlalchemy import Column, DateTime, Enum as SAEnum, String
from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class Role(StrEnum):
    CUSTOMER = "customer"
    AGENT = "agent"  # display name: Support Agent (see CONTEXT.md)
    ADMIN = "admin"


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(
        sa_column=Column(String(320), unique=True, index=True, nullable=False)
    )
    hashed_password: str = Field(sa_column=Column(String(255), nullable=False))
    full_name: str = Field(sa_column=Column(String(200), nullable=False))
    role: Role = Field(
        default=Role.CUSTOMER,
        sa_column=Column(SAEnum(Role, name="user_role", native_enum=False, length=20), nullable=False),
    )
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=utcnow),
    )
