from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class NewsSource(str, Enum):
    hse_portal = "hse_portal"
    publication = "publication"


class NewsItem(BaseModel):
    id: str
    title: str
    url: str | None = None
    published_at: datetime
    source: NewsSource
    person_ids: list[int] = []
    topics: list[str] = []
