from sqlmodel import Session

from app.core.errors import Conflict, NotFound
from app.core.security import hash_password
from app.modules.users import repository
from app.modules.users.models import Role, User
from app.modules.users.schemas import UserFilter


def create_customer(session: Session, *, email: str, password: str, full_name: str) -> User:
    return _create(session, email=email, password=password, full_name=full_name, role=Role.CUSTOMER)


def create_staff(session: Session, *, email: str, password: str, full_name: str, role: Role) -> User:
    if role is Role.CUSTOMER:
        raise Conflict("staff accounts cannot have the customer role")
    return _create(session, email=email, password=password, full_name=full_name, role=role)


def _create(session: Session, *, email: str, password: str, full_name: str, role: Role) -> User:
    email = email.strip().lower()
    if repository.get_by_email(session, email) is not None:
        raise Conflict("email is already registered")
    user = User(email=email, hashed_password=hash_password(password), full_name=full_name.strip(), role=role)
    return repository.create(session, user)


def get_by_email(session: Session, email: str) -> User | None:
    return repository.get_by_email(session, email.strip().lower())


def get_active(session: Session, user_id: int) -> User | None:
    user = repository.get(session, user_id)
    if user is None or not user.is_active:
        return None
    return user


def get_agent(session: Session, user_id: int) -> User | None:
    """A Support Agent that can be assigned tickets."""
    user = get_active(session, user_id)
    if user is None or user.role is not Role.AGENT:
        return None
    return user


def list_users(session: Session, filters: UserFilter, *, limit: int, offset: int) -> tuple[list[User], int]:
    return repository.list_users(
        session,
        role=filters.role,
        is_active=filters.is_active,
        q=filters.q,
        limit=limit,
        offset=offset,
    )


def change_role(session: Session, *, actor: User, target_id: int, new_role: Role) -> User:
    """The self-change guard below is what guarantees at least one active admin always
    remains: the actor must be an active Admin and can never be the target.
    """
    target = _get_or_404(session, target_id)
    if target.id == actor.id:
        raise Conflict("you cannot change your own role")
    target.role = new_role
    session.flush()
    session.refresh(target)
    return target


def set_active(session: Session, *, actor: User, target_id: int, is_active: bool) -> User:
    target = _get_or_404(session, target_id)
    if target.id == actor.id and not is_active:
        raise Conflict("you cannot deactivate your own account")
    target.is_active = is_active
    session.flush()
    if not is_active:
        # Deactivating always terminates sessions — invariant belongs here, not in the router,
        # so any future caller (CLI, background job) gets the same guarantee automatically.
        from app.modules.auth import service as _auth  # local import avoids circular dep at module level
        _auth.revoke_all_for_user(session, user_id=target.id)
    session.refresh(target)
    return target


def _get_or_404(session: Session, user_id: int) -> User:
    user = repository.get(session, user_id)
    if user is None:
        raise NotFound("user not found")
    return user
