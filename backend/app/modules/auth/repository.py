from datetime import UTC, datetime

from sqlmodel import Session, select

from app.modules.auth.models import RefreshToken


def create(session: Session, *, user_id: int, token_hash: str, expires_at: datetime) -> RefreshToken:
    token = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    session.add(token)
    session.flush()
    return token


def get_by_hash(session: Session, token_hash: str) -> RefreshToken | None:
    return session.exec(select(RefreshToken).where(RefreshToken.token_hash == token_hash)).first()


def revoke(session: Session, token: RefreshToken, *, at: datetime) -> None:
    token.revoked_at = at
    session.add(token)
    session.flush()


def revoke_all_for_user(session: Session, *, user_id: int, at: datetime | None = None) -> None:
    at = at or datetime.now(UTC)
    tokens = session.exec(
        select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
    )
    for token in tokens:
        token.revoked_at = at
        session.add(token)
    session.flush()
