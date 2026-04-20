from enum import Enum

from pydantic import BaseModel

from app.schemas.person import PersonSummary
from app.schemas.publication import Publication


class SearchHitType(str, Enum):
    person = "person"
    publication = "publication"


class SearchHit(BaseModel):
    type: SearchHitType
    score: float = 1.0
    person: PersonSummary | None = None
    publication: Publication | None = None


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchHit]
