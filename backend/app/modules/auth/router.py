from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.rate_limit_dependencies import limit_per_ip
from app.modules.auth import service
from app.modules.auth.schemas import LoginIn, RefreshIn, RegisterIn, TokenOut

router = APIRouter(prefix="/auth", tags=["auth"])

# Brute-force pressure points (M3 Phase B): per-IP fixed windows, fail-open.
_register_limited = limit_per_ip("auth-register", limit=3, window_seconds=60)
_login_limited = limit_per_ip("auth-login", limit=5, window_seconds=60)
_refresh_limited = limit_per_ip("auth-refresh", limit=30, window_seconds=60)


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(_register_limited)])
def register(data: RegisterIn, session: Annotated[Session, Depends(get_session)]) -> TokenOut:
    return service.register(session, data)


@router.post("/login", response_model=TokenOut, dependencies=[Depends(_login_limited)])
def login(data: LoginIn, session: Annotated[Session, Depends(get_session)]) -> TokenOut:
    return service.login(session, data)


@router.post("/refresh", response_model=TokenOut, dependencies=[Depends(_refresh_limited)])
def refresh(data: RefreshIn, session: Annotated[Session, Depends(get_session)]) -> TokenOut:
    return service.refresh(session, data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(data: RefreshIn, session: Annotated[Session, Depends(get_session)]) -> None:
    service.logout(session, data.refresh_token)
