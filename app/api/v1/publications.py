from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models import Authorship, Publication
from app.schemas.envelopes import PaginatedPublication
from app.schemas.publication import AuthorRef, Publication as PublicationSchema, PublicationType
from app.services.pagination import paginate

router = APIRouter()

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


@router.get("/publications", response_model=PaginatedPublication)
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
    db: AsyncSession = Depends(get_db),
) -> Paginated[PublicationSchema]:
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
        PublicationSchema(
            id=p.id, title=p.title, type=PublicationType(p.type),
            year=p.year, language=p.language,
            authors=authors_map.get(p.id, []), url=p.url, created_at=p.created_at,
        )
        for p in pubs
    ]
    return PaginatedPublication(
        count=total, page=page, page_size=page_size,
        next=next_url, previous=prev_url, results=results,
    )


@router.get("/publications/{pub_id}", response_model=PublicationSchema)
async def get_publication(pub_id: str, db: AsyncSession = Depends(get_db)) -> PublicationSchema:
    pub = await db.get(Publication, pub_id)
    if pub is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"Publication {pub_id} not found"},
        )
    authors_map = await _attach_authors(db, [pub])
    return PublicationSchema(
        id=pub.id, title=pub.title, type=PublicationType(pub.type),
        year=pub.year, language=pub.language,
        authors=authors_map.get(pub.id, []), url=pub.url, created_at=pub.created_at,
    )
