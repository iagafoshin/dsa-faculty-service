"""Concrete named paginated envelopes so /openapi.json uses PaginatedFoo names."""
from __future__ import annotations

from app.schemas.course import Course
from app.schemas.news import NewsItem
from app.schemas.pagination import Paginated
from app.schemas.person import PersonSummary
from app.schemas.publication import Publication


class PaginatedPersonSummary(Paginated[PersonSummary]):
    pass


class PaginatedPublication(Paginated[Publication]):
    pass


class PaginatedCourse(Paginated[Course]):
    pass


class PaginatedNewsItem(Paginated[NewsItem]):
    pass
