from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Select, and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import Authorship, Campus, Course, Person, Publication
from app.publication_enrichment import enrich_publication
from app.schemas import (
    AuthorRef,
    CampusOut,
    CourseOut,
    HealthResponse,
    NewsItem,
    NewsSource,
    Paginated,
    PersonOut,
    PersonSummary,
    PublicationOut,
    PublicationType,
    PublicationTypeMeta,
    ReadyResponse,
    SearchHit,
    SearchHitType,
    SearchResponse,
)

router = APIRouter()


# === Хелпер пагинации ===

def _replace_page(request: Request, new_page: int) -> str:
    q = dict(request.query_params)
    q["page"] = str(new_page)
    base = str(request.url).split("?", 1)[0]
    return f"{base}?{urlencode(q, doseq=True)}"


async def paginate(
    session: AsyncSession,
    query: Select[Any],
    page: int,
    page_size: int,
    request: Request,
) -> tuple[list[Any], int, str | None, str | None]:
    count_q = select(func.count()).select_from(query.order_by(None).subquery())
    total = (await session.execute(count_q)).scalar_one()

    offset = (page - 1) * page_size
    rows = (await session.execute(query.limit(page_size).offset(offset))).all()

    last_page = max(1, (total + page_size - 1) // page_size) if total else 1
    next_url = _replace_page(request, page + 1) if page < last_page else None
    prev_url = _replace_page(request, page - 1) if page > 1 else None
    return rows, total, next_url, prev_url


# === Health (проверка живости сервиса) ===

@router.get("/health", response_model=HealthResponse, tags=["health"])
async def get_health() -> HealthResponse:
    return HealthResponse(status="ok", version=settings.app_version)


@router.get("/ready", response_model=ReadyResponse, tags=["health"])
async def get_ready(db: AsyncSession = Depends(get_session)):
    try:
        await db.execute(text("SELECT 1"))
        return ReadyResponse(status="ok", checks={"db": "ok"})
    except Exception:
        return JSONResponse(
            status_code=503,
            content=ReadyResponse(status="degraded", checks={"db": "down"}).model_dump(),
        )


# === Мета (справочники) ===

_PUB_TYPE_LABELS = {
    PublicationType.ARTICLE: "Научная статья",
    PublicationType.BOOK: "Книга",
    PublicationType.PREPRINT: "Препринт",
    PublicationType.CHAPTER: "Глава в книге",
    PublicationType.CONFERENCE: "Доклад на конференции",
    PublicationType.THESIS: "Диссертация / ВКР",
    PublicationType.OTHER: "Другое",
}


@router.get("/meta/campuses", response_model=list[CampusOut], tags=["meta"])
async def list_campuses(db: AsyncSession = Depends(get_session)) -> list[CampusOut]:
    rows = (await db.execute(select(Campus).order_by(Campus.campus_name))).scalars().all()
    return [CampusOut(campus_id=r.campus_id, campus_name=r.campus_name) for r in rows]


@router.get("/meta/publication-types", response_model=list[PublicationTypeMeta], tags=["meta"])
async def list_publication_types() -> list[PublicationTypeMeta]:
    return [PublicationTypeMeta(code=t.value, label=_PUB_TYPE_LABELS[t]) for t in PublicationType]


# === Преподаватели ===

_ORDERING_MAP = {
    "full_name": Person.full_name.asc(),
    "-full_name": Person.full_name.desc(),
    "publications_total": Person.publications_total.asc(),
    "-publications_total": Person.publications_total.desc(),
}


def _person_to_summary(p: Person, campus_name: str | None) -> PersonSummary:
    return PersonSummary(
        person_id=p.person_id,
        full_name=p.full_name,
        avatar=p.avatar,
        profile_url=p.profile_url,
        primary_unit=p.primary_unit,
        campus_name=campus_name,
        publications_total=p.publications_total,
        languages=p.languages,
    )


def _person_to_full(p: Person, campus_name: str | None) -> PersonOut:
    return PersonOut(
        person_id=p.person_id,
        full_name=p.full_name,
        avatar=p.avatar,
        profile_url=p.profile_url,
        primary_unit=p.primary_unit,
        campus_name=campus_name,
        publications_total=p.publications_total,
        languages=p.languages,
        contacts=p.contacts,
        positions=p.positions,
        relations=p.relations,
        education=p.education,
        work_experience=p.work_experience,
        awards=p.awards,
        interests=p.interests,
        grants=[
            {"title": g.get("title", ""), "year": g.get("year"), "role": g.get("role")}
            for g in p.grants if isinstance(g, dict)
        ],
        editorial_staff=p.editorial_staff,
        conferences=p.conferences,
        bio_notes=p.bio_notes,
        research_ids={k: str(v) for k, v in p.research_ids.items()},
        patents=p.patents,
        parsed_at=p.parsed_at,
    )


async def _ensure_person(db: AsyncSession, person_id: int) -> None:
    res = await db.execute(select(Person.person_id).where(Person.person_id == person_id))
    if res.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"Person {person_id} not found"},
        )


@router.get("/persons", response_model=Paginated[PersonSummary], tags=["persons"])
async def list_persons(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
    campus_id: str | None = None,
    has_publications: bool | None = None,
    language: str | None = None,
    ordering: str = "full_name",
    db: AsyncSession = Depends(get_session),
):
    if ordering not in _ORDERING_MAP:
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_request", "message": f"Invalid ordering: {ordering}"},
        )

    query = select(Person, Campus.campus_name).outerjoin(Campus, Person.campus_id == Campus.campus_id)

    filters = []
    if q:
        filters.append(Person.full_name.ilike(f"%{q}%"))
    if campus_id:
        filters.append(Person.campus_id == campus_id)
    if has_publications is True:
        filters.append(Person.publications_total > 0)
    elif has_publications is False:
        filters.append(Person.publications_total == 0)
    if language:
        filters.append(Person.languages.contains([language]))
    if filters:
        query = query.where(and_(*filters))

    query = query.order_by(_ORDERING_MAP[ordering], Person.person_id.asc())

    rows, total, next_url, prev_url = await paginate(db, query, page, page_size, request)
    results = [_person_to_summary(p, campus_name) for (p, campus_name) in rows]
    return Paginated[PersonSummary](
        count=total, page=page, page_size=page_size,
        next=next_url, previous=prev_url, results=results,
    )


@router.get("/persons/{person_id}", response_model=PersonOut, tags=["persons"])
async def get_person(person_id: int, db: AsyncSession = Depends(get_session)) -> PersonOut:
    stmt = select(Person, Campus.campus_name).outerjoin(
        Campus, Person.campus_id == Campus.campus_id
    ).where(Person.person_id == person_id)
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"Person {person_id} not found"},
        )
    person, campus_name = row
    return _person_to_full(person, campus_name)


@router.get("/persons/{person_id}/publications", response_model=Paginated[PublicationOut], tags=["persons"])
async def list_person_publications(
    request: Request,
    person_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    year_from: int | None = Query(None, ge=1900),
    year_to: int | None = Query(None, ge=1900),
    type: PublicationType | None = None,
    db: AsyncSession = Depends(get_session),
):
    await _ensure_person(db, person_id)

    base = (
        select(Publication)
        .join(Authorship, Authorship.publication_id == Publication.id)
        .where(Authorship.person_id == person_id)
        .distinct()
    )
    if year_from is not None:
        base = base.where(Publication.year >= year_from)
    if year_to is not None:
        base = base.where(Publication.year <= year_to)
    if type is not None:
        base = base.where(Publication.type == type.value)

    base = base.order_by(Publication.year.desc().nullslast(), Publication.id.asc())

    rows, total, next_url, prev_url = await paginate(db, base, page, page_size, request)
    pubs = [r[0] for r in rows]
    authors_map = await _attach_authors(db, pubs)

    results = [
        enrich_publication(
            PublicationOut(
                id=p.id, title=p.title, type=PublicationType(p.type),
                year=p.year, language=p.language, authors=authors_map.get(p.id, []),
                url=p.url, created_at=p.created_at,
            ),
            p.raw,
        )
        for p in pubs
    ]
    return Paginated[PublicationOut](
        count=total, page=page, page_size=page_size,
        next=next_url, previous=prev_url, results=results,
    )


@router.get("/persons/{person_id}/courses", response_model=Paginated[CourseOut], tags=["persons"])
async def list_person_courses(
    request: Request,
    person_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    academic_year: str | None = None,
    db: AsyncSession = Depends(get_session),
):
    await _ensure_person(db, person_id)

    query = select(Course).where(Course.person_id == person_id)
    if academic_year:
        query = query.where(Course.academic_year == academic_year)
    query = query.order_by(Course.academic_year.desc().nullslast(), Course.id.asc())

    rows, total, next_url, prev_url = await paginate(db, query, page, page_size, request)
    results = [CourseOut.model_validate(r[0]) for r in rows]
    return Paginated[CourseOut](
        count=total, page=page, page_size=page_size,
        next=next_url, previous=prev_url, results=results,
    )


# === Публикации ===

_PUB_ORDERING = {
    "year": Publication.year.asc(),
    "-year": Publication.year.desc(),
    "created_at": Publication.created_at.asc(),
    "-created_at": Publication.created_at.desc(),
}


async def _attach_authors(db: AsyncSession, pubs: list[Publication]) -> dict[str, list[AuthorRef]]:
    if not pubs:
        return {}
    pub_ids = [p.id for p in pubs]
    rows = (
        await db.execute(
            select(Authorship)
            .where(Authorship.publication_id.in_(pub_ids))
            .order_by(Authorship.publication_id, Authorship.position)
        )
    ).scalars().all()
    out: dict[str, list[AuthorRef]] = {}
    for a in rows:
        out.setdefault(a.publication_id, []).append(
            AuthorRef(
                person_id=a.person_id, display_name=a.display_name,
                href=a.href, position=a.position,
            )
        )
    return out


@router.get("/publications", response_model=Paginated[PublicationOut], tags=["publications"])
async def list_publications(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    type: PublicationType | None = None,
    author_person_id: int | None = None,
    ordering: str = "-created_at",
    db: AsyncSession = Depends(get_session),
):
    if ordering not in _PUB_ORDERING:
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_request", "message": f"Invalid ordering: {ordering}"},
        )

    base = select(Publication)
    if author_person_id is not None:
        base = (
            base.join(Authorship, Authorship.publication_id == Publication.id)
            .where(Authorship.person_id == author_person_id)
            .distinct()
        )

    filters = []
    if q:
        filters.append(Publication.title.ilike(f"%{q}%"))
    if year_from is not None:
        filters.append(Publication.year >= year_from)
    if year_to is not None:
        filters.append(Publication.year <= year_to)
    if type is not None:
        filters.append(Publication.type == type.value)
    if filters:
        base = base.where(and_(*filters))

    base = base.order_by(_PUB_ORDERING[ordering], Publication.id.asc())

    rows, total, next_url, prev_url = await paginate(db, base, page, page_size, request)
    pubs = [r[0] for r in rows]
    authors_map = await _attach_authors(db, pubs)

    results = [
        enrich_publication(
            PublicationOut(
                id=p.id, title=p.title, type=PublicationType(p.type),
                year=p.year, language=p.language,
                authors=authors_map.get(p.id, []), url=p.url, created_at=p.created_at,
            ),
            p.raw,
        )
        for p in pubs
    ]
    return Paginated[PublicationOut](
        count=total, page=page, page_size=page_size,
        next=next_url, previous=prev_url, results=results,
    )


@router.get("/publications/{pub_id}", response_model=PublicationOut, tags=["publications"])
async def get_publication(pub_id: str, db: AsyncSession = Depends(get_session)) -> PublicationOut:
    pub = await db.get(Publication, pub_id)
    if pub is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"Publication {pub_id} not found"},
        )
    authors_map = await _attach_authors(db, [pub])
    base = PublicationOut(
        id=pub.id, title=pub.title, type=PublicationType(pub.type),
        year=pub.year, language=pub.language,
        authors=authors_map.get(pub.id, []), url=pub.url, created_at=pub.created_at,
    )
    return enrich_publication(base, pub.raw)


# === Поиск ===

@router.get("/search", response_model=SearchResponse, tags=["search"])
async def search(
    q: str = Query(..., min_length=2),
    type: Literal["all", "persons", "publications"] = "all",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
) -> SearchResponse:
    pattern = f"%{q}%"
    offset = (page - 1) * page_size
    results: list[SearchHit] = []

    want_persons = type in ("all", "persons")
    want_pubs = type in ("all", "publications")

    person_count = 0
    pub_count = 0
    if want_persons:
        person_count = (
            await db.execute(
                select(func.count()).select_from(
                    select(Person.person_id).where(Person.full_name.ilike(pattern)).subquery()
                )
            )
        ).scalar_one()
    if want_pubs:
        pub_count = (
            await db.execute(
                select(func.count()).select_from(
                    select(Publication.id).where(Publication.title.ilike(pattern)).subquery()
                )
            )
        ).scalar_one()

    total = person_count + pub_count
    remaining = page_size

    if want_persons and remaining > 0 and offset < person_count:
        p_offset = offset
        p_limit = min(remaining, person_count - p_offset)
        stmt = (
            select(Person, Campus.campus_name)
            .outerjoin(Campus, Person.campus_id == Campus.campus_id)
            .where(Person.full_name.ilike(pattern))
            .order_by(Person.publications_total.desc(), Person.full_name.asc())
            .limit(p_limit).offset(p_offset)
        )
        for p, campus_name in (await db.execute(stmt)).all():
            results.append(
                SearchHit(
                    type=SearchHitType.person, score=1.0,
                    person=_person_to_summary(p, campus_name),
                )
            )
        remaining = page_size - len(results)

    if want_pubs and remaining > 0:
        pub_offset = max(0, offset - person_count) if want_persons else offset
        if want_persons and offset < person_count:
            pub_offset = 0
        stmt = (
            select(Publication)
            .where(Publication.title.ilike(pattern))
            .order_by(Publication.year.desc().nullslast(), Publication.id.asc())
            .limit(remaining).offset(pub_offset)
        )
        for pub in (await db.execute(stmt)).scalars().all():
            results.append(
                SearchHit(
                    type=SearchHitType.publication, score=1.0,
                    publication=PublicationOut(
                        id=pub.id, title=pub.title, type=PublicationType(pub.type),
                        year=pub.year, language=pub.language, authors=[],
                        url=pub.url, created_at=pub.created_at,
                    ),
                )
            )

    return SearchResponse(query=q, total=total, results=results)


# === Новости ===

@router.get("/news", response_model=Paginated[NewsItem], tags=["news"])
async def list_news(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    since: datetime | None = None,
    source: Literal["all", "publication", "hse_portal"] = "all",
    person_id: int | None = None,
    db: AsyncSession = Depends(get_session),
) -> Paginated[NewsItem]:
    if source == "hse_portal":
        return Paginated[NewsItem](
            count=0, page=page, page_size=page_size, next=None, previous=None, results=[]
        )

    base = select(Publication).where(Publication.created_at.is_not(None))
    filters = []
    if since is not None:
        filters.append(Publication.created_at >= since)
    if person_id is not None:
        base = (
            base.join(Authorship, Authorship.publication_id == Publication.id)
            .where(Authorship.person_id == person_id)
            .distinct()
        )
    if filters:
        base = base.where(and_(*filters))
    base = base.order_by(Publication.created_at.desc())

    rows, total, next_url, prev_url = await paginate(db, base, page, page_size, request)
    pubs = [r[0] for r in rows]

    pub_ids = [p.id for p in pubs]
    persons_by_pub: dict[str, list[int]] = {}
    if pub_ids:
        auth_rows = (
            await db.execute(
                select(Authorship.publication_id, Authorship.person_id)
                .where(Authorship.publication_id.in_(pub_ids))
                .where(Authorship.person_id.is_not(None))
            )
        ).all()
        for pid, aid in auth_rows:
            persons_by_pub.setdefault(pid, []).append(aid)

    results = [
        NewsItem(
            id=p.id,
            title=p.title,
            url=p.url,
            published_at=p.created_at,
            source=NewsSource.publication,
            person_ids=persons_by_pub.get(p.id, []),
            topics=[],
        )
        for p in pubs
    ]
    return Paginated[NewsItem](
        count=total, page=page, page_size=page_size,
        next=next_url, previous=prev_url, results=results,
    )
