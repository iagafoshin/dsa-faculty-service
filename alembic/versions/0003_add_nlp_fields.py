"""add nlp fields (interests_extracted, topics, embedding vector)

Revision ID: 0003_add_nlp_fields
Revises: 0002_add_patents_to_persons
Create Date: 2026-05-20
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_add_nlp_fields"
down_revision = "0002_add_patents_to_persons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column(
        "persons",
        sa.Column(
            "interests_extracted",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "persons",
        sa.Column("embedding", Vector(384), nullable=True),
    )

    op.add_column(
        "publications",
        sa.Column(
            "topics",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "publications",
        sa.Column("embedding", Vector(384), nullable=True),
    )

    op.create_index(
        "ix_persons_interests_extracted_gin",
        "persons",
        ["interests_extracted"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_publications_topics_gin",
        "publications",
        ["topics"],
        postgresql_using="gin",
    )

    op.execute(
        "CREATE INDEX ix_persons_embedding_hnsw "
        "ON persons USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX ix_publications_embedding_hnsw "
        "ON publications USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_publications_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_persons_embedding_hnsw")
    op.drop_index("ix_publications_topics_gin", table_name="publications")
    op.drop_index("ix_persons_interests_extracted_gin", table_name="persons")
    op.drop_column("publications", "embedding")
    op.drop_column("publications", "topics")
    op.drop_column("persons", "embedding")
    op.drop_column("persons", "interests_extracted")
