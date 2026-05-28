"""Хелперы для векторного поиска по persons / publications.

Используются и из JSON-эндпоинтов (`app.experts`), и из HTML-страниц
(`app.ui`). NLP-зависимости импортируются лениво — `torch` /
`sentence-transformers` тяжёлые и не ставятся в прод-Docker. Если
их нет в окружении, helper'ы поднимут ImportError; вызывающий код
сам решает, как с этим быть (JSON-endpoint падает в 500, UI ловит
и показывает graceful fallback).
"""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Authorship, Campus, Person, Publication


# Подбор научрука — отсекаем нерелевантные роли (менеджеры, лаборанты,
# инженеры, эксперты-аналитики, аспиранты, стажёры-исследователи и т.п.).
# Whitelist по подстроке в `positions[].title`: достаточно одной подходящей
# должности, чтобы персона прошла фильтр (у многих ВШЭ-шников их 2-3).
TEACHER_TITLE_RE = (
    r"(преподавател|доцент|профессор|ассистент|"
    r"научный сотрудник|научный руководител|"
    r"академическ\w+ руководител|заведующий кафедр)"
)
TEACHER_FILTER_SQL = text(
    "EXISTS ("
    " SELECT 1 FROM jsonb_array_elements(persons.positions) p"
    " WHERE lower(p->>'title') ~ :teacher_re"
    ")"
).bindparams(teacher_re=TEACHER_TITLE_RE)


def faculty_filter_sql(faculty: str):
    """SQL-фильтр «есть подразделение, содержащее <faculty>».

    Препод может работать на нескольких факультетах: `positions` содержит
    `[{title, units: [{name, url}, ...]}]`. `primary_unit` — только первый
    из них; чтобы не упускать совмещённых, бежим по всем `units[].name`.
    """
    return text(
        "EXISTS ("
        " SELECT 1 FROM jsonb_array_elements(persons.positions) p,"
        "             jsonb_array_elements(p->'units') u"
        " WHERE lower(u->>'name') LIKE :faculty_like"
        ")"
    ).bindparams(faculty_like=f"%{faculty.lower()}%")


async def vector_search_persons(
    db: AsyncSession,
    q: str,
    *,
    limit: int = 20,
    offset: int = 0,
    campus_id: str | None = None,
    primary_unit: str | None = None,
    has_publications: bool | None = None,
    top_pubs_per_person: int = 3,
) -> tuple[list[tuple[Person, str | None, float]], dict[int, list[Publication]]]:
    """Топ-N экспертов по cosine + топ-K публикаций каждого.

    Возвращает:
        (rows, top_pubs_by_person)
        где rows — [(Person, campus_name, score), ...]
        top_pubs_by_person — {person_id: [Publication, ...]} (≤ top_pubs_per_person)
    """
    from app.nlp.embedder import embed
    q_vec = embed(q)

    stmt = (
        select(
            Person,
            Campus.campus_name,
            (1 - Person.embedding.cosine_distance(q_vec)).label("score"),
        )
        .outerjoin(Campus, Person.campus_id == Campus.campus_id)
        .where(Person.embedding.is_not(None))
        .where(TEACHER_FILTER_SQL)
    )
    if campus_id:
        stmt = stmt.where(Person.campus_id == campus_id)
    if primary_unit:
        # primary_unit — это имя параметра ради обратной совместимости
        # с /experts/search; фильтр теперь идёт по ЛЮБОМУ из units всех
        # позиций (совмещённые преподаватели больше не теряются).
        stmt = stmt.where(faculty_filter_sql(primary_unit))
    if has_publications is True:
        stmt = stmt.where(Person.publications_total > 0)
    elif has_publications is False:
        stmt = stmt.where(Person.publications_total == 0)
    stmt = stmt.order_by(Person.embedding.cosine_distance(q_vec)).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).all()

    person_ids = [r[0].person_id for r in rows]
    top_pubs: dict[int, list[Publication]] = {pid: [] for pid in person_ids}
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
            if len(top_pubs[pid]) < top_pubs_per_person:
                top_pubs[pid].append(pub)

    return rows, top_pubs


async def vector_search_publications(
    db: AsyncSession,
    q: str,
    *,
    limit: int = 20,
    year_from: int | None = None,
    year_to: int | None = None,
    pub_type: str | None = None,
    language: str | None = None,
) -> list[tuple[Publication, float]]:
    """Топ-N публикаций по cosine. Фильтры применяются ВМЕСТЕ с
    ORDER BY — HNSW-индекс сначала достаёт ближайших по вектору,
    Postgres потом отрезает несоответствующих фильтрам.
    """
    from app.nlp.embedder import embed
    q_vec = embed(q)

    stmt = (
        select(
            Publication,
            (1 - Publication.embedding.cosine_distance(q_vec)).label("score"),
        )
        .where(Publication.embedding.is_not(None))
    )
    if year_from is not None:
        stmt = stmt.where(Publication.year >= year_from)
    if year_to is not None:
        stmt = stmt.where(Publication.year <= year_to)
    if pub_type:
        stmt = stmt.where(Publication.type == pub_type)
    if language:
        stmt = stmt.where(Publication.language == language)
    stmt = stmt.order_by(Publication.embedding.cosine_distance(q_vec)).limit(limit)
    rows = (await db.execute(stmt)).all()
    return [(p, float(s)) for p, s in rows]


def compute_matched_topics(
    query: str,
    interests_extracted: list[str] | None,
    interests_raw: list[str] | None = None,
) -> list[str]:
    """Substring-сопоставление токенов запроса с тегами персоны.

    Приоритет: сначала ищем в `interests_raw` (HSE-listed — всегда чистые
    и в нормальной форме типа «теория графов»). Если там пусто или мало —
    дополняем `interests_extracted` (KeyBERT, может содержать обрезки).

    На коротких запросах (2-4 слова) KeyBERT возвращает [], поэтому
    пересечение query_tags ∩ interests было бы пустым. Подстрока — даёт
    сигнал даже на 1 слово.
    """
    query_tokens = [t.lower() for t in query.split() if len(t) > 2]
    if not query_tokens:
        return []

    def _match(topics: list[str] | None) -> list[str]:
        out: list[str] = []
        for topic in topics or []:
            tl = str(topic).lower()
            if any(token in tl for token in query_tokens):
                out.append(str(topic))
        return out

    raw_hits = _match(interests_raw)
    if len(raw_hits) >= 3:
        return raw_hits[:6]

    # Дополняем извлечёнными тегами, дедуп по подстроке.
    extra = _match(interests_extracted)
    raw_lower = [t.lower() for t in raw_hits]
    deduped_extra = [t for t in extra if not any(t.lower() in r or r in t.lower() for r in raw_lower)]
    return (raw_hits + deduped_extra)[:6]
