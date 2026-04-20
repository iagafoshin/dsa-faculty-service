from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Paginated(BaseModel, Generic[T]):
    count: int
    page: int
    page_size: int
    next: str | None = None
    previous: str | None = None
    results: list[T]
