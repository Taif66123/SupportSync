from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.modules.users.models import Role, User


def create(session: Session, user: User) -> User:
    session.add(user)
    session.flush()
    session.refresh(user)
    return user


def get_by_email(session: Session, email: str) -> User | None:
    return session.exec(select(User).where(User.email == email)).first()


def get(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def list_users(
    session: Session,
    *,
    role: Role | None,
    is_active: bool | None,
    q: str | None,
    limit: int,
    offset: int,
) -> tuple[list[User], int]:
    query = select(User)
    if role is not None:
        query = query.where(User.role == role)
    if is_active is not None:
        query = query.where(User.is_active == is_active)
    if q:
        pattern = f"%{q.lower()}%"
        query = query.where(or_(func.lower(User.email).like(pattern), func.lower(User.full_name).like(pattern)))

    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    items = list(session.exec(query.order_by(User.created_at.desc(), User.id.desc()).offset(offset).limit(limit)))
    return items, total
