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
    display_name_en: str | None = None
    href: str | None = None
    is_hse_person: bool = False
    position: int


class Publication(BaseModel):
    id: str
    title: str
    type: PublicationType
    year: int | None = None
    language: str | None = None
    url: str | None = None
    authors: list[AuthorRef] = []
    created_at: datetime | None = None

    abstract_ru: str | None = None
    abstract_en: str | None = None

    venue: str | None = None
    citation: str | None = None
    publisher: str | None = None

    doi_url: str | None = None
    document_url: str | None = None
    external_url: str | None = None
    cover_url: str | None = None

    editors: list[AuthorRef] = []
    translators: list[AuthorRef] = []
