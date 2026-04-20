from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models import Authorship, Publication
from app.schemas.envelopes import PaginatedNewsItem
from app.schemas.news import NewsItem, NewsSource
from app.services.pagination import paginate

router = APIRouter()


@router.get("/news", response_model=PaginatedNewsItem)
async def list_news(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    since: datetime | None = None,
    source: Literal["all", "publication", "hse_portal"] = "all",
    person_id: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> PaginatedNewsItem:
    if source == "hse_portal":
        return PaginatedNewsItem(
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
    return PaginatedNewsItem(
        count=total, page=page, page_size=page_size,
        next=next_url, previous=prev_url, results=results,
    )
