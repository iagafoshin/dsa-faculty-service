"""Pydantic-схемы ответов API Faculty Service."""
from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict


# === Пагинация ===

T = TypeVar("T")


class Paginated(BaseModel, Generic[T]):
    count: int
    page: int
    page_size: int
    next: str | None = None
    previous: str | None = None
    results: list[T]


# === Health / справочники ===

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str


class ReadyResponse(BaseModel):
    status: str
    checks: dict[str, str]


class CampusOut(BaseModel):
    campus_id: str
    campus_name: str


class PublicationTypeMeta(BaseModel):
    code: str
    label: str


# === Преподаватель ===

class PersonSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    person_id: int
    full_name: str
    avatar: str | None = None
    profile_url: str
    primary_unit: str | None = None
    campus_name: str | None = None
    publications_total: int = 0
    languages: list[str] = []


class Contacts(BaseModel):
    phones: str | None = None
    address: str | None = None
    hours: str | None = None
    timetable_url: str | None = None


class PositionUnit(BaseModel):
    name: str | None = None
    url: str | None = None


class Position(BaseModel):
    title: str | None = None
    units: list[PositionUnit] = []


class PersonRef(BaseModel):
    person_id: int | None = None
    name: str
    url: str | None = None
    role: str | None = None


class Relations(BaseModel):
    managers: list[PersonRef] = []


class Degree(BaseModel):
    year: int | None = None
    text: str


class Education(BaseModel):
    degrees: list[Degree] = []
    extra_education: list[str] = []


class Grant(BaseModel):
    title: str
    year: int | None = None
    role: str | None = None


class Patent(BaseModel):
    """Запись из таблицы «Авторские права и патенты» на странице ВШЭ.

    Все поля опциональны — в исходной таблице бывают строки разной структуры.
    Поля ``number`` и ``registration`` могут содержать URL вместе с текстом,
    тогда значение сериализуется как ``{"text": ..., "url": ...}``.
    """
    title: str | None = None
    number: Any = None
    kind: str | None = None
    registration: Any = None
    authors: list[str] = []
    year: int | None = None


class PersonOut(PersonSummary):
    contacts: Contacts = Contacts()
    positions: list[Position] = []
    relations: Relations = Relations()
    education: Education = Education()
    work_experience: list[str] = []
    awards: list[str] = []
    interests: list[str] = []
    grants: list[Grant] = []
    editorial_staff: list[str] = []
    conferences: list[str] = []
    bio_notes: list[str] = []
    research_ids: dict[str, str] = {}
    patents: list[Patent] = []
    parsed_at: datetime | None = None


# === Публикации ===

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


class PublicationOut(BaseModel):
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


# === Курсы ===

class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str
    url: str | None = None
    academic_year: str | None = None
    language: str | None = None
    level: str | None = None
    raw_meta: str | None = None


class CourseHit(BaseModel):
    """Один результат поиска по курсам — курс + краткие данные ведущего."""
    model_config = ConfigDict(from_attributes=True)

    course_id: int
    title: str
    academic_year: str | None = None
    language: str | None = None
    level: str | None = None
    person_id: int
    person_name: str
    person_unit: str | None = None
    person_avatar: str | None = None


# === Новости ===

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


# === Поиск ===

class SearchHitType(str, Enum):
    person = "person"
    publication = "publication"


class SearchHit(BaseModel):
    type: SearchHitType
    score: float = 1.0
    person: PersonSummary | None = None
    publication: PublicationOut | None = None


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchHit]


# === Эксперты — векторный поиск по теме ===

class ExpertHit(BaseModel):
    person_id: int
    full_name: str
    avatar: str | None = None
    profile_url: str
    primary_unit: str | None = None
    campus_name: str | None = None
    score: float
    matched_topics: list[str] = []
    top_publications: list[PublicationOut] = []


class ExpertSearchResponse(BaseModel):
    query: str
    query_tags: list[str] = []
    results: list[ExpertHit]


# === Публикации — векторный поиск ===

class PublicationHit(BaseModel):
    """Одна публикация в результатах семантического поиска."""
    publication: PublicationOut
    score: float


class PublicationSemanticResponse(BaseModel):
    query: str
    results: list[PublicationHit]


# === Админ (скрейп-задачи) ===

class ScrapeStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cancelling = "cancelling"
    cancelled = "cancelled"


class ScrapeJobCreated(BaseModel):
    job_id: str
    status: ScrapeStatus
    estimated_profiles: int | None = None


class ScrapeJobStatus(BaseModel):
    job_id: str
    status: ScrapeStatus
    processed: int
    total: int | None = None
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
