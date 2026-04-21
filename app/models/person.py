from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


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
