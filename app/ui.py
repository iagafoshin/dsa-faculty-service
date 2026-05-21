"""HTML-страницы (Jinja2 + Tailwind via CDN) поверх существующего JSON API.

Роуты живут в корне (`/`, `/persons`, `/publications`, `/persons/{id}`).
JSON-API остаётся под `/api/v1/...`.

Для секции «Эксперты» на главной нужны NLP-зависимости — в прод-Docker
их нет, в этом случае секция покажет «не удалось получить данные»
вместо краша.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Authorship, Campus, Course, Person, Publication

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


# === helpers ===

PUB_TYPES = ["ARTICLE", "BOOK", "PREPRINT", "CHAPTER", "CONFERENCE", "THESIS", "OTHER"]


async def _list_campuses(db: AsyncSession) -> list[dict[str, str]]:
    rows = (await db.execute(select(Campus).order_by(Campus.campus_name))).scalars().all()
    return [{"campus_id": r.campus_id, "campus_name": r.campus_name} for r in rows]


async def _list_units(db: AsyncSession) -> list[str]:
    """Уникальные значения primary_unit (для datalist-автокомплита).

    Берём только те подразделения, где есть хотя бы один enriched-эксперт —
    подсказывать факультеты без векторного поиска бессмысленно.
    """
    rows = (await db.execute(
        select(Person.primary_unit, func.count())
        .where(Person.primary_unit.is_not(None))
        .where(Person.embedding.is_not(None))
        .group_by(Person.primary_unit)
        .order_by(func.count().desc(), Person.primary_unit.asc())
    )).all()
    return [u for u, _ in rows]


def _pub_to_dict(p: Publication) -> dict[str, Any]:
    return {
        "id": p.id,
        "title": p.title,
        "year": p.year,
        "type": p.type,
        "language": p.language,
        "publisher": p.publisher,
        "abstract_ru": p.abstract_ru,
        "abstract_en": p.abstract_en,
        "doi_url": p.doi_url,
        "document_url": p.document_url,
        "external_url": p.external_url,
        "authors": [],  # заполняется отдельно
    }


async def _attach_authors(db: AsyncSession, pubs: list[Publication]) -> None:
    if not pubs:
        return
    pub_ids = [p.id for p in pubs]
    rows = (await db.execute(
        select(Authorship)
        .where(Authorship.publication_id.in_(pub_ids))
        .order_by(Authorship.publication_id, Authorship.position)
    )).scalars().all()
    by_pub: dict[str, list[dict[str, Any]]] = {}
    for a in rows:
        by_pub.setdefault(a.publication_id, []).append({
            "person_id": a.person_id,
            "display_name": a.display_name,
            "is_hse_person": a.is_hse_person,
        })
    for p in pubs:  # type: ignore[assignment]
        p._authors_for_template = by_pub.get(p.id, [])  # type: ignore[attr-defined]


# === GET / (home — search) ===

@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    q: str | None = None,
    campus_id: str | None = None,
    faculty: str | None = None,
    db: AsyncSession = Depends(get_session),
):
    faculty = (faculty or "").strip()

    ctx: dict[str, Any] = {
        "request": request,
        "q": q,
        "campus_id": campus_id,
        "faculty": faculty,
        "campuses": await _list_campuses(db),
        "units": await _list_units(db),
        "experts": [],
        "experts_error": None,
        "publications": [],
        "publications_total": 0,
        "courses": [],
        "persons": [],
    }

    if q and len(q) >= 2:
        like = f"%{q}%"

        # Experts (vector) + faculty/campus filters
        try:
            from app.nlp.embedder import embed
            q_vec = embed(q)

            exp_stmt = (
                select(
                    Person,
                    Campus.campus_name,
                    (1 - Person.embedding.cosine_distance(q_vec)).label("score"),
                )
                .outerjoin(Campus, Person.campus_id == Campus.campus_id)
                .where(Person.embedding.is_not(None))
            )
            if campus_id:
                exp_stmt = exp_stmt.where(Person.campus_id == campus_id)
            if faculty:
                exp_stmt = exp_stmt.where(Person.primary_unit.ilike(f"%{faculty}%"))
            exp_stmt = exp_stmt.order_by(Person.embedding.cosine_distance(q_vec)).limit(20)
            exp_rows = (await db.execute(exp_stmt)).all()

            # top-3 публикаций каждого
            exp_ids = [r[0].person_id for r in exp_rows]
            top_pubs: dict[int, list[Publication]] = {pid: [] for pid in exp_ids}
            if exp_ids:
                pub_rows = (await db.execute(
                    select(Authorship.person_id, Publication)
                    .join(Publication, Authorship.publication_id == Publication.id)
                    .where(Authorship.person_id.in_(exp_ids))
                    .order_by(Authorship.person_id, Publication.year.desc().nullslast(), Publication.id)
                )).all()
                for pid, pub in pub_rows:
                    if len(top_pubs[pid]) < 3:
                        top_pubs[pid].append(pub)

            q_tokens = [t.lower() for t in q.split() if len(t) > 2]
            for person, c_name, score in exp_rows:
                matched: list[str] = []
                for topic in (person.interests_extracted or []):
                    if any(tok in topic.lower() for tok in q_tokens):
                        matched.append(topic)
                ctx["experts"].append({
                    "person_id": person.person_id,
                    "full_name": person.full_name,
                    "profile_url": person.profile_url,
                    "avatar": person.avatar,
                    "primary_unit": person.primary_unit,
                    "campus_name": c_name,
                    "score": float(score),
                    "matched_topics": matched,
                    "top_publications": [
                        {"year": p.year, "title": p.title}
                        for p in top_pubs.get(person.person_id, [])
                    ],
                })
        except Exception as e:
            ctx["experts_error"] = str(e)

        # Publications — семантический поиск (vector) + фильтры год/тип.
        # На главной важно «по смыслу» — для курсовой важно найти статью по
        # теме, даже если конкретные слова не в title. Точный ILIKE-поиск
        # доступен на /publications.
        try:
            from app.nlp.embedder import embed as _embed_pub
            q_vec_pub = _embed_pub(q)
            sem_pub_q = (
                select(
                    Publication,
                    (1 - Publication.embedding.cosine_distance(q_vec_pub)).label("score"),
                )
                .where(Publication.embedding.is_not(None))
            )
            sem_pub_q = sem_pub_q.order_by(
                Publication.embedding.cosine_distance(q_vec_pub)
            ).limit(5)
            rows_pub = (await db.execute(sem_pub_q)).all()
            pubs = [r[0] for r in rows_pub]
            await _attach_authors(db, pubs)
            ctx["publications"] = [
                {
                    **_pub_to_dict(p),
                    "authors": p._authors_for_template,  # type: ignore[attr-defined]
                    "score": float(score),
                }
                for p, score in rows_pub
            ]
            ctx["publications_total"] = len(rows_pub)  # vector — топ-K, total не имеет смысла
        except Exception as e:
            # Fallback на ILIKE если NLP-стек недоступен (прод-Docker без torch)
            ctx["publications_error"] = str(e)
            pub_q = select(Publication).where(Publication.title.ilike(like)).order_by(
                Publication.year.desc().nullslast(), Publication.id.asc()
            ).limit(5)
            pubs = list((await db.execute(pub_q)).scalars().all())
            await _attach_authors(db, pubs)
            ctx["publications"] = [
                {**_pub_to_dict(p), "authors": p._authors_for_template, "score": None}  # type: ignore[attr-defined]
                for p in pubs
            ]

        # Courses (ILIKE)
        crs_q = (
            select(Course, Person)
            .join(Person, Person.person_id == Course.person_id)
            .where(Course.title.ilike(like))
            .order_by(Course.academic_year.desc().nullslast(), Course.id.desc())
            .limit(5)
        )
        for c, p in (await db.execute(crs_q)).all():
            ctx["courses"].append({
                "course_id": c.id,
                "title": c.title,
                "academic_year": c.academic_year,
                "level": c.level,
                "language": c.language,
                "person_id": p.person_id,
                "person_name": p.full_name,
                "person_unit": p.primary_unit,
            })

        # Persons (ILIKE)
        per_q = (
            select(Person, Campus.campus_name)
            .outerjoin(Campus, Person.campus_id == Campus.campus_id)
            .where(Person.full_name.ilike(like))
        )
        if campus_id:
            per_q = per_q.where(Person.campus_id == campus_id)
        if faculty:
            per_q = per_q.where(Person.primary_unit.ilike(f"%{faculty}%"))
        per_q = per_q.order_by(Person.publications_total.desc().nullslast(), Person.full_name.asc()).limit(5)
        for person, c_name in (await db.execute(per_q)).all():
            ctx["persons"].append({
                "person_id": person.person_id,
                "full_name": person.full_name,
                "avatar": person.avatar,
                "primary_unit": person.primary_unit,
                "publications_total": person.publications_total,
                "campus_name": c_name,
            })

    return templates.TemplateResponse(request, "home.html", ctx)


# === GET /persons (list) ===

@router.get("/persons", response_class=HTMLResponse)
async def persons_list(
    request: Request,
    q: str | None = None,
    campus_id: str | None = None,
    has_publications: str | None = None,
    ordering: str = "-publications_total",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
):
    _ORDER = {
        "full_name": Person.full_name.asc(),
        "-full_name": Person.full_name.desc(),
        "publications_total": Person.publications_total.asc(),
        "-publications_total": Person.publications_total.desc(),
    }

    base = select(Person, Campus.campus_name).outerjoin(Campus, Person.campus_id == Campus.campus_id)
    filters = []
    if q:
        filters.append(Person.full_name.ilike(f"%{q}%"))
    if campus_id:
        filters.append(Person.campus_id == campus_id)
    if has_publications == "true":
        filters.append(Person.publications_total > 0)
    elif has_publications == "false":
        filters.append(Person.publications_total == 0)
    if filters:
        base = base.where(and_(*filters))

    total = (await db.execute(
        select(func.count()).select_from(base.order_by(None).subquery())
    )).scalar_one()
    total_pages = max(1, (total + page_size - 1) // page_size)

    order_expr = _ORDER.get(ordering, Person.publications_total.desc())
    base = base.order_by(order_expr, Person.person_id.asc()).limit(page_size).offset((page - 1) * page_size)
    rows = (await db.execute(base)).all()

    results = [{
        "person_id": p.person_id,
        "full_name": p.full_name,
        "avatar": p.avatar,
        "primary_unit": p.primary_unit,
        "publications_total": p.publications_total,
        "languages": p.languages or [],
        "campus_name": c_name,
    } for p, c_name in rows]

    def pagination_url(new_page: int) -> str:
        params = {"page": new_page, "page_size": page_size, "ordering": ordering}
        if q: params["q"] = q
        if campus_id: params["campus_id"] = campus_id
        if has_publications: params["has_publications"] = has_publications
        return "/persons?" + urlencode(params)

    return templates.TemplateResponse(request, "persons.html", {
        "q": q, "campus_id": campus_id, "has_publications": has_publications,
        "ordering": ordering, "page": page, "total": total, "total_pages": total_pages,
        "results": results, "campuses": await _list_campuses(db),
        "pagination_url": pagination_url,
    })


# === GET /publications (list) ===

@router.get("/publications", response_class=HTMLResponse)
async def publications_list(
    request: Request,
    q: str | None = None,
    year_from: str | None = None,
    year_to: str | None = None,
    type: str | None = None,
    ordering: str = "-created_at",
    semantic: str | None = None,  # checkbox: "on" если включён vector mode
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
):
    def _to_int(s: str | None) -> int | None:
        if not s or not s.strip():
            return None
        try:
            return int(s.strip())
        except ValueError:
            return None

    year_from_i = _to_int(year_from)
    year_to_i = _to_int(year_to)
    type = (type or "").strip() or None
    is_semantic = bool(semantic) and bool(q) and len(q) >= 2

    _ORDER = {
        "year": Publication.year.asc(),
        "-year": Publication.year.desc(),
        "created_at": Publication.created_at.asc(),
        "-created_at": Publication.created_at.desc(),
    }

    error: str | None = None
    results: list[dict[str, Any]] = []
    total = 0
    total_pages = 1

    if is_semantic:
        # Vector mode: top-K по cosine, без пагинации; фильтры применяются.
        try:
            from app.nlp.embedder import embed as _embed
            q_vec = _embed(q)
            sem_q = select(
                Publication,
                (1 - Publication.embedding.cosine_distance(q_vec)).label("score"),
            ).where(Publication.embedding.is_not(None))
            if year_from_i is not None:
                sem_q = sem_q.where(Publication.year >= year_from_i)
            if year_to_i is not None:
                sem_q = sem_q.where(Publication.year <= year_to_i)
            if type:
                sem_q = sem_q.where(Publication.type == type)
            sem_q = sem_q.order_by(Publication.embedding.cosine_distance(q_vec)).limit(page_size)
            rows = (await db.execute(sem_q)).all()
            pubs = [r[0] for r in rows]
            await _attach_authors(db, pubs)
            results = [
                {**_pub_to_dict(p), "authors": p._authors_for_template, "score": float(s)}  # type: ignore[attr-defined]
                for p, s in rows
            ]
            total = len(results)
        except Exception as e:
            error = f"Семантический поиск недоступен: {e}. Используется обычный поиск."
            is_semantic = False  # fallback на ILIKE ниже

    if not is_semantic:
        base = select(Publication)
        filters = []
        if q:
            filters.append(Publication.title.ilike(f"%{q}%"))
        if year_from_i is not None:
            filters.append(Publication.year >= year_from_i)
        if year_to_i is not None:
            filters.append(Publication.year <= year_to_i)
        if type:
            filters.append(Publication.type == type)
        if filters:
            base = base.where(and_(*filters))

        total = (await db.execute(
            select(func.count()).select_from(base.order_by(None).subquery())
        )).scalar_one()
        total_pages = max(1, (total + page_size - 1) // page_size)

        order_expr = _ORDER.get(ordering, Publication.created_at.desc())
        base = base.order_by(order_expr, Publication.id.asc()).limit(page_size).offset((page - 1) * page_size)
        pubs = list((await db.execute(base)).scalars().all())
        await _attach_authors(db, pubs)
        results = [
            {**_pub_to_dict(p), "authors": p._authors_for_template, "score": None}  # type: ignore[attr-defined]
            for p in pubs
        ]

    def pagination_url(new_page: int) -> str:
        params: dict[str, Any] = {"page": new_page, "page_size": page_size, "ordering": ordering}
        if q: params["q"] = q
        if year_from_i is not None: params["year_from"] = year_from_i
        if year_to_i is not None: params["year_to"] = year_to_i
        if type: params["type"] = type
        # semantic-режим не имеет пагинации, но если активен и юзер всё-таки
        # формирует URL — флаг прокидываем (на всякий случай).
        if semantic: params["semantic"] = "on"
        return "/publications?" + urlencode(params)

    return templates.TemplateResponse(request, "publications.html", {
        "q": q, "year_from": year_from_i, "year_to": year_to_i,
        "type": type, "ordering": ordering,
        "is_semantic": is_semantic, "semantic_error": error,
        "page": page, "total": total, "total_pages": total_pages,
        "results": results, "pub_types": PUB_TYPES,
        "pagination_url": pagination_url,
    })


# === GET /persons/{id} (profile) ===

@router.get("/persons/{person_id}", response_class=HTMLResponse)
async def person_profile(
    request: Request,
    person_id: int,
    pub_page: int = Query(1, ge=1),
    course_page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_session),
):
    row = (await db.execute(
        select(Person, Campus.campus_name)
        .outerjoin(Campus, Person.campus_id == Campus.campus_id)
        .where(Person.person_id == person_id)
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")
    p, c_name = row

    # данные персоны
    person_data = {
        "person_id": p.person_id,
        "full_name": p.full_name,
        "avatar": p.avatar,
        "profile_url": p.profile_url,
        "primary_unit": p.primary_unit,
        "campus_name": c_name,
        "publications_total": p.publications_total,
        "languages": p.languages or [],
        "contacts": p.contacts or {},
        "positions": p.positions or [],
        "relations": p.relations or {},
        "education": p.education or {"degrees": [], "extra_education": []},
        "work_experience": p.work_experience or [],
        "awards": p.awards or [],
        "interests": p.interests or [],
        "grants": p.grants or [],
        "editorial_staff": p.editorial_staff or [],
        "conferences": p.conferences or [],
        "bio_notes": p.bio_notes or [],
        "research_ids": p.research_ids or {},
        "patents": p.patents or [],
    }

    PUB_PAGE_SIZE = 10
    pub_q = (
        select(Publication)
        .join(Authorship, Authorship.publication_id == Publication.id)
        .where(Authorship.person_id == person_id)
        .distinct()
    )
    pub_total = (await db.execute(
        select(func.count()).select_from(pub_q.order_by(None).subquery())
    )).scalar_one()
    pub_pages = max(1, (pub_total + PUB_PAGE_SIZE - 1) // PUB_PAGE_SIZE)
    pub_q = pub_q.order_by(Publication.year.desc().nullslast(), Publication.id.asc())
    pub_q = pub_q.limit(PUB_PAGE_SIZE).offset((pub_page - 1) * PUB_PAGE_SIZE)
    pubs = list((await db.execute(pub_q)).scalars().all())
    pubs_data = [_pub_to_dict(pub) for pub in pubs]

    CRS_PAGE_SIZE = 20
    crs_q = select(Course).where(Course.person_id == person_id)
    course_total = (await db.execute(
        select(func.count()).select_from(crs_q.order_by(None).subquery())
    )).scalar_one()
    course_pages = max(1, (course_total + CRS_PAGE_SIZE - 1) // CRS_PAGE_SIZE)
    crs_q = crs_q.order_by(Course.academic_year.desc().nullslast(), Course.id.desc())
    crs_q = crs_q.limit(CRS_PAGE_SIZE).offset((course_page - 1) * CRS_PAGE_SIZE)
    courses = [{
        "title": c.title, "academic_year": c.academic_year,
        "level": c.level, "language": c.language,
    } for c in (await db.execute(crs_q)).scalars().all()]

    return templates.TemplateResponse(request, "profile.html", {
        "person": person_data,
        "pubs": pubs_data, "pub_total": pub_total, "pub_page": pub_page, "pub_pages": pub_pages,
        "courses": courses, "course_total": course_total, "course_page": course_page, "course_pages": course_pages,
    })
