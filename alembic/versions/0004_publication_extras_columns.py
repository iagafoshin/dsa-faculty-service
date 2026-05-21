"""publication extras as columns (abstract, doi, editors, etc.); authorship richness

Revision ID: 0004_publication_extras_columns
Revises: 0003_add_nlp_fields
Create Date: 2026-05-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_publication_extras_columns"
down_revision = "0003_add_nlp_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Раньше эти поля доставались из publications.raw на каждый GET через
    # app/publication_enrichment.py. Теперь — обычные колонки, парсятся
    # один раз при upsert в scraper/ingest.py.
    op.add_column("publications", sa.Column("abstract_ru", sa.Text(), nullable=True))
    op.add_column("publications", sa.Column("abstract_en", sa.Text(), nullable=True))
    op.add_column("publications", sa.Column("venue", sa.Text(), nullable=True))
    op.add_column("publications", sa.Column("citation", sa.Text(), nullable=True))
    op.add_column("publications", sa.Column("publisher", sa.Text(), nullable=True))
    op.add_column("publications", sa.Column("doi_url", sa.Text(), nullable=True))
    op.add_column("publications", sa.Column("document_url", sa.Text(), nullable=True))
    op.add_column("publications", sa.Column("external_url", sa.Text(), nullable=True))
    op.add_column("publications", sa.Column("cover_url", sa.Text(), nullable=True))
    op.add_column(
        "publications",
        sa.Column(
            "editors", JSONB(),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "publications",
        sa.Column(
            "translators", JSONB(),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # Дополнительные поля авторства, которые раньше доставались из raw
    # в enrich_publication. Теперь хранятся прямо в authorships.
    op.add_column("authorships", sa.Column("display_name_en", sa.Text(), nullable=True))
    op.add_column(
        "authorships",
        sa.Column(
            "is_hse_person", sa.Boolean(),
            nullable=False, server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("authorships", "is_hse_person")
    op.drop_column("authorships", "display_name_en")
    op.drop_column("publications", "translators")
    op.drop_column("publications", "editors")
    op.drop_column("publications", "cover_url")
    op.drop_column("publications", "external_url")
    op.drop_column("publications", "document_url")
    op.drop_column("publications", "doi_url")
    op.drop_column("publications", "publisher")
    op.drop_column("publications", "citation")
    op.drop_column("publications", "venue")
    op.drop_column("publications", "abstract_en")
    op.drop_column("publications", "abstract_ru")
