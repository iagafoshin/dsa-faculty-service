"""SQLAlchemy-модели (таблицы БД) для Faculty Service."""
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Campus(Base):
    __tablename__ = "campuses"

    campus_id: Mapped[str] = mapped_column(primary_key=True)
    campus_name: Mapped[str] = mapped_column(nullable=False)


class Person(Base, TimestampMixin):
    __tablename__ = "persons"

    person_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    avatar: Mapped[str | None] = mapped_column(String, nullable=True)
    profile_url: Mapped[str] = mapped_column(String, nullable=False)
    primary_unit: Mapped[str | None] = mapped_column(String, nullable=True)

    campus_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("campuses.campus_id", ondelete="SET NULL"),
        nullable=True,
    )

    publications_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    languages: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    contacts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    positions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    relations: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    education: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    work_experience: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    awards: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    interests: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    grants: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    editorial_staff: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    conferences: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    bio_notes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    research_ids: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    patents: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))

    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    campus = relationship("Campus", lazy="joined")

    __table_args__ = (
        Index(
            "ix_persons_full_name_trgm",
            "full_name",
            postgresql_using="gin",
            postgresql_ops={"full_name": "gin_trgm_ops"},
        ),
        Index("ix_persons_primary_unit", "primary_unit"),
        Index("ix_persons_publications_total", "publications_total"),
        Index("ix_persons_interests_gin", "interests", postgresql_using="gin"),
        Index("ix_persons_languages_gin", "languages", postgresql_using="gin"),
    )


class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    authorships = relationship("Authorship", back_populates="publication", cascade="all, delete-orphan")

    __table_args__ = (
        Index(
            "ix_publications_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index("ix_publications_year", "year"),
        Index("ix_publications_created_at_desc", text("created_at DESC")),
        Index("ix_publications_type", "type"),
    )


class Authorship(Base):
    __tablename__ = "authorships"

    publication_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("publications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)

    person_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("persons.person_id", ondelete="SET NULL"),
        nullable=True,
    )
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    href: Mapped[str | None] = mapped_column(String, nullable=True)

    publication = relationship("Publication", back_populates="authorships")
    person = relationship("Person", lazy="joined")

    __table_args__ = (
        Index("ix_authorships_person_id", "person_id"),
        Index("ix_authorships_publication_id", "publication_id"),
    )


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("persons.person_id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    academic_year: Mapped[str | None] = mapped_column(String, nullable=True)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    level: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_meta: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_courses_person_year", "person_id", "academic_year"),
    )


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    limit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    campus_id: Mapped[str | None] = mapped_column(String, nullable=True)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
