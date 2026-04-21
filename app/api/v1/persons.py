from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models import Authorship, Campus, Course, Person, Publication
from app.schemas.course import Course as CourseSchema
from app.schemas.envelopes import PaginatedCourse, PaginatedPersonSummary, PaginatedPublication
from app.schemas.person import Person as PersonSchema
from app.schemas.person import PersonSummary
from app.schemas.publication import AuthorRef, Publication as PublicationSchema, PublicationType
from app.services.pagination import paginate
from app.services.publication_enrichment import enrich_publication

router = APIRouter()

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
        languages=list(p.languages or []),
    )


def _person_to_full(p: Person, campus_name: str | None) -> PersonSchema:
    return PersonSchema(
        person_id=p.person_id,
        full_name=p.full_name,
        avatar=p.avatar,
        profile_url=p.profile_url,
        primary_unit=p.primary_unit,
        campus_name=campus_name,
        publications_total=p.publications_total,
        languages=list(p.languages or []),
        contacts=(p.contacts or {}),
        positions=list(p.positions or []),
        relations=(p.relations or {"managers": []}),
        education=(p.education or {"degrees": [], "extra_education": []}),
        work_experience=list(p.work_experience or []),
        awards=list(p.awards or []),
        interests=list(p.interests or []),
        grants=[
            {"title": g.get("title", ""), "year": g.get("year"), "role": g.get("role")}
            for g in (p.grants or []) if isinstance(g, dict)
        ],
        editorial_staff=list(p.editorial_staff or []),
        conferences=list(p.conferences or []),
        bio_notes=list(p.bio_notes or []),
        research_ids={k: str(v) for k, v in (p.research_ids or {}).items()},
        patents=list(p.patents or []),
        parsed_at=p.parsed_at,
    )


@router.get("/persons", response_model=PaginatedPersonSummary)
async def list_persons(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
    campus_id: str | None = None,
    has_publications: bool | None = None,
    language: str | None = None,
    ordering: str = "full_name",
    db: AsyncSession = Depends(get_db),
) -> Paginated[PersonSummary]:
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
    return PaginatedPersonSummary(
        count=total, page=page, page_size=page_size,
        next=next_url, previous=prev_url, results=results,
    )


@router.get("/persons/{person_id}", response_model=PersonSchema)
async def get_person(person_id: int, db: AsyncSession = Depends(get_db)) -> PersonSchema:
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


async def _ensure_person(db: AsyncSession, person_id: int) -> None:
    res = await db.execute(select(Person.person_id).where(Person.person_id == person_id))
    if res.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"Person {person_id} not found"},
        )


@router.get("/persons/{person_id}/publications", response_model=PaginatedPublication)
async def list_person_publications(
    request: Request,
    person_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    year_from: int | None = Query(None, ge=1900),
    year_to: int | None = Query(None, ge=1900),
    type: PublicationType | None = None,
    db: AsyncSession = Depends(get_db),
) -> Paginated[PublicationSchema]:
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
    pub_ids = [p.id for p in pubs]
    authors_map: dict[str, list[AuthorRef]] = {}
    if pub_ids:
        auth_rows = (
            await db.execute(
                select(Authorship).where(Authorship.publication_id.in_(pub_ids))
                .order_by(Authorship.publication_id, Authorship.position)
            )
        ).scalars().all()
        for a in auth_rows:
            authors_map.setdefault(a.publication_id, []).append(
                AuthorRef(
                    person_id=a.person_id, display_name=a.display_name,
                    href=a.href, position=a.position,
                )
            )

    results = [
        enrich_publication(
            PublicationSchema(
                id=p.id, title=p.title, type=PublicationType(p.type),
                year=p.year, language=p.language, authors=authors_map.get(p.id, []),
                url=p.url, created_at=p.created_at,
            ),
            p.raw,
        )
        for p in pubs
    ]
    return PaginatedPublication(
        count=total, page=page, page_size=page_size,
        next=next_url, previous=prev_url, results=results,
    )


@router.get("/persons/{person_id}/courses", response_model=PaginatedCourse)
async def list_person_courses(
    request: Request,
    person_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    academic_year: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> Paginated[CourseSchema]:
    await _ensure_person(db, person_id)

    query = select(Course).where(Course.person_id == person_id)
    if academic_year:
        query = query.where(Course.academic_year == academic_year)
    query = query.order_by(Course.academic_year.desc().nullslast(), Course.id.asc())

    rows, total, next_url, prev_url = await paginate(db, query, page, page_size, request)
    results = [CourseSchema.model_validate(r[0]) for r in rows]
    return PaginatedCourse(
        count=total, page=page, page_size=page_size,
        next=next_url, previous=prev_url, results=results,
    )
