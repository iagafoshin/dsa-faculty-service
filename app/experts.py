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
from app.schemas import (
    ExpertHit,
    ExpertSearchResponse,
    PublicationHit,
    PublicationOut,
    PublicationSemanticResponse,
    PublicationType,
)

router = APIRouter()


def compute_matched_topics(query: str, person_topics: list[str]) -> list[str]:
    """Substring-сопоставление токенов запроса с тегами персоны.

    Берёт токены длиннее 2 симв., нижний регистр, и возвращает теги, в
    которых встретился любой токен запроса как подстрока. Это работает
    на коротких запросах (2–4 слова), где KeyBERT почти всегда возвращает
    пустой список — точное совпадение по подстроке всегда даёт сигнал.
    """
    query_tokens = [t.lower() for t in query.split() if len(t) > 2]
    if not query_tokens:
        return []
    matched: list[str] = []
    for topic in person_topics or []:
        topic_lower = topic.lower()
        if any(token in topic_lower for token in query_tokens):
            matched.append(topic)
    return matched


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
    primary_unit: str | None = Query(None, description="Substring filter on primary unit (faculty)."),
    has_publications: bool | None = Query(None, description="Only persons with (or without) publications."),
    db: AsyncSession = Depends(get_session),
) -> ExpertSearchResponse:
    # Lazy imports: nlp deps (torch, sentence-transformers, spacy, keybert) тяжёлые
    # и не ставятся в прод-Dockerfile. Эндпоинт работает только там, где они есть.
    from app.nlp.embedder import embed
    from app.nlp.extractor import extract_topics

    q_vec = embed(q)
    # query_tags ещё нужен в ответе (для UI/дебага), но matched_topics
    # больше НЕ опирается на их пересечение — на коротких запросах KeyBERT
    # почти всегда возвращает []. Substring-сопоставление работает всегда.
    query_tags = extract_topics(q)

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
    if primary_unit:
        base = base.where(Person.primary_unit.ilike(f"%{primary_unit}%"))
    if has_publications is True:
        base = base.where(Person.publications_total > 0)
    elif has_publications is False:
        base = base.where(Person.publications_total == 0)
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
        matched = compute_matched_topics(q, person.interests_extracted)

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


# === Vector search по публикациям ===

@router.get(
    "/publications/semantic-search",
    response_model=PublicationSemanticResponse,
    tags=["publications"],
    summary="Semantic search over publications (vector)",
    description=(
        "Embeds the query, ranks publications by cosine similarity over "
        "`publications.embedding` (HNSW index). Supports filters: year range, "
        "type, language — applied alongside the vector ordering."
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
    from app.nlp.embedder import embed

    q_vec = embed(q)

    base = (
        select(
            Publication,
            (1 - Publication.embedding.cosine_distance(q_vec)).label("score"),
        )
        .where(Publication.embedding.is_not(None))
    )
    if year_from is not None:
        base = base.where(Publication.year >= year_from)
    if year_to is not None:
        base = base.where(Publication.year <= year_to)
    if type:
        base = base.where(Publication.type == type)
    if language:
        base = base.where(Publication.language == language)
    base = base.order_by(Publication.embedding.cosine_distance(q_vec)).limit(limit)

    rows = (await db.execute(base)).all()

    # Подгружаем авторов одной батч-выборкой (как в routes.list_publications)
    pubs = [r[0] for r in rows]
    pub_ids = [p.id for p in pubs]
    authors_by_pub: dict[str, list] = {pid: [] for pid in pub_ids}
    if pub_ids:
        from app.schemas import AuthorRef  # внутри, чтобы не плодить top-level импорты
        rows_a = (await db.execute(
            select(Authorship)
            .where(Authorship.publication_id.in_(pub_ids))
            .order_by(Authorship.publication_id, Authorship.position)
        )).scalars().all()
        for a in rows_a:
            authors_by_pub.setdefault(a.publication_id, []).append(AuthorRef(
                person_id=a.person_id,
                display_name=a.display_name,
                display_name_en=a.display_name_en,
                href=a.href,
                is_hse_person=a.is_hse_person,
                position=a.position,
            ))

    hits: list[PublicationHit] = []
    for p, score in rows:
        pub_out = PublicationOut(
            id=p.id,
            title=p.title,
            type=PublicationType(p.type),
            year=p.year,
            language=p.language,
            url=p.url,
            created_at=p.created_at,
            authors=authors_by_pub.get(p.id, []),
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
        hits.append(PublicationHit(publication=pub_out, score=float(score)))

    return PublicationSemanticResponse(query=q, results=hits)
