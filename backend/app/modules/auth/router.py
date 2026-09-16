from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from app.core.database import get_session
from app.modules.auth import service
from app.modules.auth.schemas import LoginIn, RefreshIn, RegisterIn, TokenOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(data: RegisterIn, session: Annotated[Session, Depends(get_session)]) -> TokenOut:
    return service.register(session, data)


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, session: Annotated[Session, Depends(get_session)]) -> TokenOut:
    return service.login(session, data)


@router.post("/refresh", response_model=TokenOut)
def refresh(data: RefreshIn, session: Annotated[Session, Depends(get_session)]) -> TokenOut:
    return service.refresh(session, data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(data: RefreshIn, session: Annotated[Session, Depends(get_session)]) -> None:
    service.logout(session, data.refresh_token)
