from app.models.base import Base, TimestampMixin
from app.models.campus import Campus
from app.models.person import Person
from app.models.publication import Publication
from app.models.authorship import Authorship
from app.models.course import Course
from app.models.scrape_job import ScrapeJob

__all__ = [
    "Base",
    "TimestampMixin",
    "Campus",
    "Person",
    "Publication",
    "Authorship",
    "Course",
    "ScrapeJob",
]
