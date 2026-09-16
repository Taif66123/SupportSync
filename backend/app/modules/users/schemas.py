from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.users.models import Role


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime


class StaffCreateIn(BaseModel):
    """Admin creates support staff accounts. Customers self-register via /auth/register."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    role: Role

    def model_post_init(self, __context: object) -> None:
        if self.role is Role.CUSTOMER:
            raise ValueError("use POST /auth/register to create customers")


class UserRolePatchIn(BaseModel):
    role: Role


class UserStatusPatchIn(BaseModel):
    is_active: bool


class UserFilter(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    q: str | None = Field(default=None, max_length=100)
