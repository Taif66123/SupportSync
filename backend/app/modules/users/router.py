from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from app.core.database import get_session
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.users import service
from app.modules.users.models import Role, User
from app.modules.users.schemas import StaffCreateIn, UserFilter, UserOut, UserRolePatchIn, UserStatusPatchIn
from app.utils.pagination import LimitOffset, Page, limit_offset

router = APIRouter(prefix="/users", tags=["users"])

Admin = Annotated[User, Depends(require_role(Role.ADMIN))]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_staff(
    data: StaffCreateIn,
    session: Annotated[Session, Depends(get_session)],
    _admin: Admin,
) -> User:
    return service.create_staff(session, email=data.email, password=data.password, full_name=data.full_name, role=data.role)


@router.get("", response_model=Page[UserOut])
def list_users(
    session: Annotated[Session, Depends(get_session)],
    _admin: Admin,
    filters: Annotated[UserFilter, Depends()],
    page: Annotated[LimitOffset, Depends(limit_offset)],
) -> Page[UserOut]:
    items, total = service.list_users(session, filters, limit=page.limit, offset=page.offset)
    return Page(items=[UserOut.model_validate(u) for u in items], total=total, limit=page.limit, offset=page.offset)


@router.get("/me", response_model=UserOut)
def me(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user


@router.patch("/{user_id}/role", response_model=UserOut)
def change_role(
    user_id: int,
    data: UserRolePatchIn,
    session: Annotated[Session, Depends(get_session)],
    admin: Admin,
) -> User:
    return service.change_role(session, actor=admin, target_id=user_id, new_role=data.role)


@router.patch("/{user_id}/status", response_model=UserOut)
def set_status(
    user_id: int,
    data: UserStatusPatchIn,
    session: Annotated[Session, Depends(get_session)],
    admin: Admin,
) -> User:
    return service.set_active(session, actor=admin, target_id=user_id, is_active=data.is_active)
