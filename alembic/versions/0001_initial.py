"""initial schema: persons, publications, authorships, courses, campuses, scrape_jobs

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-20
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


SEED_CAMPUSES = [
    ("1125608", "Москва"),
    ("1125609", "Санкт-Петербург"),
    ("1125610", "Нижний Новгород"),
    ("1125611", "Пермь"),
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "campuses",
        sa.Column("campus_id", sa.String(), primary_key=True),
        sa.Column("campus_name", sa.String(), nullable=False),
    )

    op.create_table(
        "persons",
        sa.Column("person_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("avatar", sa.String(), nullable=True),
        sa.Column("profile_url", sa.String(), nullable=False),
        sa.Column("primary_unit", sa.String(), nullable=True),
        sa.Column(
            "campus_id",
            sa.String(),
            sa.ForeignKey("campuses.campus_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("publications_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("languages", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("contacts", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("positions", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("relations", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("education", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("work_experience", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("awards", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("interests", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("grants", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("editorial_staff", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("conferences", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("bio_notes", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("research_ids", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.execute(
        "CREATE INDEX ix_persons_full_name_trgm ON persons USING gin (full_name gin_trgm_ops)"
    )
    op.create_index("ix_persons_primary_unit", "persons", ["primary_unit"])
    op.create_index("ix_persons_publications_total", "persons", ["publications_total"])
    op.execute("CREATE INDEX ix_persons_interests_gin ON persons USING gin (interests)")
    op.execute("CREATE INDEX ix_persons_languages_gin ON persons USING gin (languages)")

    op.create_table(
        "publications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.execute(
        "CREATE INDEX ix_publications_title_trgm ON publications USING gin (title gin_trgm_ops)"
    )
    op.create_index("ix_publications_year", "publications", ["year"])
    op.execute("CREATE INDEX ix_publications_created_at_desc ON publications (created_at DESC)")
    op.create_index("ix_publications_type", "publications", ["type"])

    op.create_table(
        "authorships",
        sa.Column(
            "publication_id",
            sa.String(),
            sa.ForeignKey("publications.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column(
            "person_id",
            sa.BigInteger(),
            sa.ForeignKey("persons.person_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("href", sa.String(), nullable=True),
    )
    op.create_index("ix_authorships_person_id", "authorships", ["person_id"])
    op.create_index("ix_authorships_publication_id", "authorships", ["publication_id"])

    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "person_id",
            sa.BigInteger(),
            sa.ForeignKey("persons.person_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("academic_year", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("level", sa.String(), nullable=True),
        sa.Column("raw_meta", sa.String(), nullable=True),
    )
    op.create_index("ix_courses_person_year", "courses", ["person_id", "academic_year"])

    op.create_table(
        "scrape_jobs",
        sa.Column("job_id", sa.String(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("limit_count", sa.Integer(), nullable=True),
        sa.Column("campus_id", sa.String(), nullable=True),
        sa.Column("processed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    for cid, name in SEED_CAMPUSES:
        op.execute(
            sa.text("INSERT INTO campuses (campus_id, campus_name) VALUES (:i, :n)")
            .bindparams(i=cid, n=name)
        )


def downgrade() -> None:
    op.drop_table("scrape_jobs")
    op.drop_index("ix_courses_person_year", table_name="courses")
    op.drop_table("courses")
    op.drop_index("ix_authorships_publication_id", table_name="authorships")
    op.drop_index("ix_authorships_person_id", table_name="authorships")
    op.drop_table("authorships")
    op.drop_index("ix_publications_type", table_name="publications")
    op.execute("DROP INDEX IF EXISTS ix_publications_created_at_desc")
    op.drop_index("ix_publications_year", table_name="publications")
    op.execute("DROP INDEX IF EXISTS ix_publications_title_trgm")
    op.drop_table("publications")
    op.execute("DROP INDEX IF EXISTS ix_persons_languages_gin")
    op.execute("DROP INDEX IF EXISTS ix_persons_interests_gin")
    op.drop_index("ix_persons_publications_total", table_name="persons")
    op.drop_index("ix_persons_primary_unit", table_name="persons")
    op.execute("DROP INDEX IF EXISTS ix_persons_full_name_trgm")
    op.drop_table("persons")
    op.drop_table("campuses")
