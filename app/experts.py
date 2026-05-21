"""Векторный поиск экспертов по теме (`GET /api/v1/experts/search`).

Запрос эмбеддится моделью, затем pgvector косинусным расстоянием по
HNSW-индексу `persons.embedding` подбирает ближайшие профили. Для каждого
найденного — последние 3 публикации в одной батч-выборке.

`app.nlp.*` импортируется ЛЕНИВО (внутри функции эндпоинта) — чтобы
прод-Docker без `torch`/`sentence-transformers` мог стартовать. Эндпоинт
вернёт 500 если nlp-зависимости отсутствуют.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Authorship, Campus, Person, Publication
from app.schemas import ExpertHit, ExpertSearchResponse, PublicationOut, PublicationType

router = APIRouter()


@router.get(
    "/experts/search",
    response_model=ExpertSearchResponse,
    tags=["experts"],
    summary="Find experts by topic (vector search)",
    description=(
        "Embeds the query, then ranks persons by cosine similarity over "
        "`persons.embedding` (HNSW index). `matched_topics` is the intersection "
        "of query keyphrases and the person's `interests_extracted`."
    ),
)
async def search_experts(
    q: str = Query(..., min_length=2, description="Free-text query, e.g. 'machine learning'"),
    limit: int = Query(10, ge=1, le=50),
    campus_id: str | None = Query(None, description="Restrict to one campus."),
    db: AsyncSession = Depends(get_session),
) -> ExpertSearchResponse:
    # Lazy imports: nlp deps (torch, sentence-transformers, spacy, keybert) тяжёлые
    # и не ставятся в прод-Dockerfile. Эндпоинт работает только там, где они есть.
    from app.nlp.embedder import embed
    from app.nlp.extractor import extract_topics

    q_vec = embed(q)
    query_tags = extract_topics(q)
    query_tags_set = {t.lower() for t in query_tags}

    base = (
        select(
            Person,
            Campus.campus_name,
            (1 - Person.embedding.cosine_distance(q_vec)).label("score"),
        )
        .outerjoin(Campus, Person.campus_id == Campus.campus_id)
        .where(Person.embedding.is_not(None))
    )
    if campus_id:
        base = base.where(Person.campus_id == campus_id)
    base = base.order_by(Person.embedding.cosine_distance(q_vec)).limit(limit)
    rows = (await db.execute(base)).all()

    person_ids = [row[0].person_id for row in rows]
    top_pubs_by_person: dict[int, list[Publication]] = {pid: [] for pid in person_ids}
    if person_ids:
        pub_rows = (await db.execute(
            select(Authorship.person_id, Publication)
            .join(Publication, Authorship.publication_id == Publication.id)
            .where(Authorship.person_id.in_(person_ids))
            .order_by(
                Authorship.person_id,
                Publication.year.desc().nullslast(),
                Publication.id,
            )
        )).all()
        for pid, pub in pub_rows:
            if len(top_pubs_by_person[pid]) < 3:
                top_pubs_by_person[pid].append(pub)

    hits: list[ExpertHit] = []
    for person, campus_name, score in rows:
        person_tags_lower = {t.lower() for t in (person.interests_extracted or [])}
        matched = sorted(query_tags_set & person_tags_lower)

        top_pubs = [
            PublicationOut(
                id=p.id,
                title=p.title,
                type=PublicationType(p.type),
                year=p.year,
                language=p.language,
                url=p.url,
                created_at=p.created_at,
                authors=[],
            )
            for p in top_pubs_by_person.get(person.person_id, [])
        ]

        hits.append(ExpertHit(
            person_id=person.person_id,
            full_name=person.full_name,
            avatar=person.avatar,
            profile_url=person.profile_url,
            primary_unit=person.primary_unit,
            campus_name=campus_name,
            score=float(score),
            matched_topics=matched,
            top_publications=top_pubs,
        ))

    return ExpertSearchResponse(query=q, query_tags=query_tags, results=hits)
