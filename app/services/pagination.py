from typing import Any
from urllib.parse import urlencode

from fastapi import Request
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


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
    rows_q = query.limit(page_size).offset(offset)
    rows = (await session.execute(rows_q)).all()

    last_page = max(1, (total + page_size - 1) // page_size) if total else 1
    next_url = _replace_page(request, page + 1) if page < last_page else None
    prev_url = _replace_page(request, page - 1) if page > 1 else None

    return rows, total, next_url, prev_url
