"""JSON-эндпоинты векторного поиска: `/experts/search` и
`/publications/semantic-search`.

Сам vector-SQL живёт в `app/vector_search.py` — этот же helper зовут и
HTML-страницы из `app/ui.py`. Здесь только сериализация в схемы.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Authorship
from app.schemas import (
    AuthorRef,
    ExpertHit,
    ExpertSearchResponse,
    PublicationHit,
    PublicationOut,
    PublicationSemanticResponse,
    PublicationType,
)
from app.vector_search import (
    compute_matched_topics,
    vector_search_persons,
    vector_search_publications,
)

router = APIRouter()


def _pub_to_out(p, authors: list[AuthorRef] | None = None) -> PublicationOut:
    return PublicationOut(
        id=p.id,
        title=p.title,
        type=PublicationType(p.type),
        year=p.year,
        language=p.language,
        url=p.url,
        created_at=p.created_at,
        authors=authors or [],
        abstract_ru=p.abstract_ru,
        abstract_en=p.abstract_en,
        venue=p.venue,
        citation=p.citation,
        publisher=p.publisher,
        doi_url=p.doi_url,
        document_url=p.document_url,
        external_url=p.external_url,
        cover_url=p.cover_url,
        editors=p.editors,
        translators=p.translators,
    )


@router.get(
    "/experts/search",
    response_model=ExpertSearchResponse,
    tags=["experts"],
    summary="Find experts by topic (vector search)",
    description=(
        "Embeds the query, then ranks persons by cosine similarity over "
        "`persons.embedding` (HNSW). Returns top hits with their top-3 recent "
        "publications. `matched_topics` is substring-matched against the "
        "person's `interests_extracted` — short queries (1-2 words) still "
        "produce signal."
    ),
)
async def search_experts(
    q: str = Query(..., min_length=2, description="Free-text query"),
    limit: int = Query(10, ge=1, le=50),
    campus_id: str | None = Query(None, description="Restrict to one campus."),
    primary_unit: str | None = Query(None, description="Substring filter on primary unit (faculty)."),
    has_publications: bool | None = Query(None, description="Only persons with (or without) publications."),
    db: AsyncSession = Depends(get_session),
) -> ExpertSearchResponse:
    rows, top_pubs_by_person = await vector_search_persons(
        db, q,
        limit=limit,
        campus_id=campus_id,
        primary_unit=primary_unit,
        has_publications=has_publications,
    )

    # query_tags оставлен в ответе для дебага/UI (показывает что NER извлёк
    # из запроса), но matched_topics строится через substring — он надёжнее
    # на коротких запросах.
    from app.nlp.extractor import extract_topics
    query_tags = extract_topics(q)

    hits = [
        ExpertHit(
            person_id=person.person_id,
            full_name=person.full_name,
            avatar=person.avatar,
            profile_url=person.profile_url,
            primary_unit=person.primary_unit,
            campus_name=campus_name,
            score=float(score),
            matched_topics=compute_matched_topics(
                q, person.interests_extracted, person.interests,
            ),
            top_publications=[
                _pub_to_out(p) for p in top_pubs_by_person.get(person.person_id, [])
            ],
        )
        for person, campus_name, score in rows
    ]
    return ExpertSearchResponse(query=q, query_tags=query_tags, results=hits)


@router.get(
    "/publications/semantic-search",
    response_model=PublicationSemanticResponse,
    tags=["publications"],
    summary="Semantic search over publications (vector)",
    description=(
        "Embeds the query, ranks publications by cosine similarity over "
        "`publications.embedding` (HNSW). Supports filters: year range, type, "
        "language — applied alongside the vector ordering."
    ),
)
async def semantic_search_publications(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, ge=1, le=50),
    year_from: int | None = Query(None, ge=1900, le=2100),
    year_to: int | None = Query(None, ge=1900, le=2100),
    type: str | None = Query(None, description="ARTICLE / BOOK / PREPRINT / ..."),
    language: str | None = Query(None, description="e.g. рус, англ"),
    db: AsyncSession = Depends(get_session),
) -> PublicationSemanticResponse:
    rows = await vector_search_publications(
        db, q,
        limit=limit,
        year_from=year_from, year_to=year_to,
        pub_type=type, language=language,
    )

    # Подгружаем авторов одной батч-выборкой.
    pub_ids = [p.id for p, _ in rows]
    authors_by_pub: dict[str, list[AuthorRef]] = {pid: [] for pid in pub_ids}
    if pub_ids:
        a_rows = (await db.execute(
            select(Authorship)
            .where(Authorship.publication_id.in_(pub_ids))
            .order_by(Authorship.publication_id, Authorship.position)
        )).scalars().all()
        for a in a_rows:
            authors_by_pub.setdefault(a.publication_id, []).append(AuthorRef(
                person_id=a.person_id,
                display_name=a.display_name,
                display_name_en=a.display_name_en,
                href=a.href,
                is_hse_person=a.is_hse_person,
                position=a.position,
            ))

    hits = [
        PublicationHit(
            publication=_pub_to_out(p, authors_by_pub.get(p.id, [])),
            score=score,
        )
        for p, score in rows
    ]
    return PublicationSemanticResponse(query=q, results=hits)
