from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from app.core.database import get_session
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_access_token
from app.modules.users import service as users
from app.modules.users.models import Role, User

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    session: Annotated[Session, Depends(get_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise Unauthorized("missing bearer token")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthorized("invalid token") from exc

    user = users.get_active(session, int(payload["sub"]))
    if user is None:
        raise Unauthorized("unknown or deactivated user")
    return user


def get_optional_credentials(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> HTTPAuthorizationCredentials | None:
    """Bearer credentials if present, None otherwise — for endpoints (SSE) that
    accept header-or-query-token auth instead of raising on a missing header."""
    return credentials


def authenticate_token(session: Session, token: str) -> User | None:
    """Token auth for handshake-style endpoints (WebSocket /?token=, SSE) where
    browsers cannot always set headers. Returns None instead of raising; callers
    decide the rejection shape (WS close 1008, HTTP 401, …)."""
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None
    return users.get_active(session, user_id)


def require_role(*allowed: Role):
    def checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in allowed:
            raise Forbidden("insufficient role")
        return user

    return checker
