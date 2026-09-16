from dataclasses import dataclass
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


@dataclass
class LimitOffset:
    limit: int
    offset: int


def limit_offset(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> LimitOffset:
    return LimitOffset(limit=limit, offset=offset)
