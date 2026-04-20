from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class PublicationType(str, Enum):
    ARTICLE = "ARTICLE"
    BOOK = "BOOK"
    PREPRINT = "PREPRINT"
    CHAPTER = "CHAPTER"
    CONFERENCE = "CONFERENCE"
    THESIS = "THESIS"
    OTHER = "OTHER"


class AuthorRef(BaseModel):
    person_id: int | None = None
    display_name: str
    href: str | None = None
    position: int


class Publication(BaseModel):
    id: str
    title: str
    type: PublicationType
    year: int | None = None
    language: str | None = None
    authors: list[AuthorRef] = []
    url: str | None = None
    created_at: datetime | None = None
