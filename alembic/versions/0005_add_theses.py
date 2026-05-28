"""add theses + thesis_supervisors

Revision ID: 0005_add_theses
Revises: 0004_publication_extras_columns
Create Date: 2026-05-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005_add_theses"
down_revision = "0004_publication_extras_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "theses",
        sa.Column("thesis_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("level", sa.String(), nullable=True),
        sa.Column("student", sa.String(), nullable=True),
        sa.Column("program", sa.String(), nullable=True),
        sa.Column("program_url", sa.String(), nullable=True),
        sa.Column("org_unit", sa.String(), nullable=True),
        sa.Column("has_en_version", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("raw", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_theses_year", "theses", ["year"])
    op.create_index(
        "ix_theses_title_trgm",
        "theses",
        ["title"],
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )

    op.create_table(
        "thesis_supervisors",
        sa.Column("thesis_id", sa.BigInteger(), nullable=False),
        sa.Column("person_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["thesis_id"], ["theses.thesis_id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"], ["persons.person_id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("thesis_id", "person_id"),
    )
    op.create_index(
        "ix_thesis_supervisors_person_id", "thesis_supervisors", ["person_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_thesis_supervisors_person_id", table_name="thesis_supervisors")
    op.drop_table("thesis_supervisors")
    op.drop_index("ix_theses_title_trgm", table_name="theses")
    op.drop_index("ix_theses_year", table_name="theses")
    op.drop_table("theses")
