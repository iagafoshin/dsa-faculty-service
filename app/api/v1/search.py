from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models import Campus, Person, Publication
from app.schemas.person import PersonSummary
from app.schemas.publication import Publication as PublicationSchema, PublicationType
from app.schemas.search import SearchHit, SearchHitType, SearchResponse

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=2),
    type: Literal["all", "persons", "publications"] = "all",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
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

    # Persons first, then publications. Compute slice within each source.
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
                    person=PersonSummary(
                        person_id=p.person_id, full_name=p.full_name, avatar=p.avatar,
                        profile_url=p.profile_url, primary_unit=p.primary_unit,
                        campus_name=campus_name, publications_total=p.publications_total,
                        languages=list(p.languages or []),
                    ),
                )
            )
        remaining = page_size - len(results)

    if want_pubs and remaining > 0:
        consumed_persons = min(offset, person_count) + (len(results) if want_persons else 0)
        pub_offset = max(0, offset + (page_size - remaining) - person_count) if want_persons else offset
        # When we've already passed all persons, `offset - person_count` is the starting point in pubs.
        if want_persons:
            pub_offset = max(0, offset - person_count)
            # if we still have persons on this page, pubs start at 0
            if offset < person_count:
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
                    publication=PublicationSchema(
                        id=pub.id, title=pub.title, type=PublicationType(pub.type),
                        year=pub.year, language=pub.language, authors=[],
                        url=pub.url, created_at=pub.created_at,
                    ),
                )
            )

    return SearchResponse(query=q, total=total, results=results)
