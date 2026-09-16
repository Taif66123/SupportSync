from datetime import UTC, datetime

from sqlmodel import Session

from app.core.config import settings
from app.core.errors import Unauthorized
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.modules.auth import repository as refresh_tokens
from app.modules.auth.schemas import LoginIn, RegisterIn, TokenOut
from app.modules.users import service as users
from app.modules.users.models import Role, User


def register(session: Session, data: RegisterIn) -> TokenOut:
    """Open self-registration — always creates a Customer (see CONTEXT.md)."""
    user = users.create_customer(session, email=data.email, password=data.password, full_name=data.full_name)
    return issue_pair(session, user)


def login(session: Session, data: LoginIn) -> TokenOut:
    user = users.get_by_email(session, data.email)
    if user is None or not verify_password(data.password, user.hashed_password):
        raise Unauthorized("invalid email or password")
    if not user.is_active:
        raise Unauthorized("this account is deactivated")
    return issue_pair(session, user)


def refresh(session: Session, raw_token: str) -> TokenOut:
    """Rotate: revoke the presented token and issue a new pair, atomically (one request transaction).

    A rotated (revoked) token is rejected — reuse after rotation is treated as a compromise.
    """
    stored = refresh_tokens.get_by_hash(session, hash_refresh_token(raw_token))
    if stored is None or not stored.is_usable():
        raise Unauthorized("invalid or expired refresh token")
    user = users.get_active(session, stored.user_id)
    if user is None:
        raise Unauthorized("invalid or expired refresh token")

    refresh_tokens.revoke(session, stored, at=datetime.now(UTC))
    return issue_pair(session, user)


def logout(session: Session, raw_token: str) -> None:
    stored = refresh_tokens.get_by_hash(session, hash_refresh_token(raw_token))
    if stored is not None:
        refresh_tokens.revoke(session, stored, at=datetime.now(UTC))


def revoke_all_for_user(session: Session, *, user_id: int) -> None:
    refresh_tokens.revoke_all_for_user(session, user_id=user_id)


def issue_pair(session: Session, user: User) -> TokenOut:
    raw, token_hash, expires_at = generate_refresh_token()
    refresh_tokens.create(session, user_id=user.id, token_hash=token_hash, expires_at=expires_at)
    return TokenOut(
        access_token=create_access_token(user_id=user.id, role=user.role.value),
        refresh_token=raw,
        expires_in=settings.access_token_expire_minutes * 60,
    )
