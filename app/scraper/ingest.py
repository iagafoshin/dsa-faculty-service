"""Запись (upsert) одного спарсенного преподавателя + его публикаций, авторств и курсов в БД."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from dateutil import parser as dateparser
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Authorship, Course, Person, Publication
from app.schemas import PublicationType

_PUB_TYPES = {t.value for t in PublicationType}
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return dateparser.isoparse(str(value))
    except (ValueError, TypeError):
        return None


def _strip_html(s: str | None) -> str:
    if not s:
        return ""
    return _HTML_TAG_RE.sub("", s).strip()


def _coerce_pub_type(raw_type: Any) -> str:
    if isinstance(raw_type, str) and raw_type in _PUB_TYPES:
        return raw_type
    return PublicationType.OTHER.value


def _publication_payload(item: dict[str, Any]) -> dict[str, Any]:
    language_raw = item.get("language")
    language = language_raw.get("name") if isinstance(language_raw, dict) else language_raw
    return {
        "id": str(item["id"]),
        "title": item.get("title") or "",
        "type": _coerce_pub_type(item.get("type")),
        "year": item.get("year") if isinstance(item.get("year"), int) else None,
        "language": language,
        "url": None,
        "created_at": _parse_iso(item.get("createdAt")),
        "raw": item,
    }


def _authorship_payloads(pub_item: dict[str, Any]) -> list[dict[str, Any]]:
    authors = (pub_item.get("authorsByType") or {}).get("author") or []
    pub_id = str(pub_item["id"])
    out: list[dict[str, Any]] = []
    for k, a in enumerate(authors):
        if not isinstance(a, dict):
            continue
        title = a.get("title")
        if isinstance(title, dict):
            display_name = _strip_html(title.get("ru") or title.get("en") or "")
        else:
            display_name = _strip_html(str(title or ""))
        if not display_name:
            display_name = a.get("altName") or a.get("otherName") or ""
        author_id = a.get("id")
        person_id: int | None = None
        if isinstance(author_id, (int, str)) and str(author_id).isdigit():
            person_id = int(author_id)
        out.append({
            "publication_id": pub_id,
            "position": k,
            "person_id": person_id,
            "display_name": display_name,
            "href": a.get("href"),
        })
    return out


def _course_payload(person_id: int, item: dict[str, Any]) -> dict[str, Any]:
    meta = item.get("meta")
    level = meta.split(";", 1)[0].strip() if meta else None
    return {
        "person_id": person_id,
        "title": item.get("title") or "",
        "url": item.get("url"),
        "academic_year": item.get("academic_year"),
        "language": item.get("language"),
        "level": level or None,
        "raw_meta": meta,
    }


async def upsert_person(session: AsyncSession, data: dict[str, Any]) -> int:
    """Записывает одного преподавателя + его публикации, авторства и курсы в БД.

    `data` — плоский dict из app.scraper.profile.scrape_one_profile:
    колонки Person на верхнем уровне, плюс `_publications` и `_courses`.
    """
    publications = data.pop("_publications", [])
    courses = data.pop("_courses", [])
    person_id = int(data["person_id"])

    person_update = {k: v for k, v in data.items() if k != "person_id"}
    await session.execute(
        pg_insert(Person).values(**data).on_conflict_do_update(
            index_elements=[Person.person_id], set_=person_update,
        )
    )

    pending_auths: list[dict[str, Any]] = []
    for item in publications:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        await session.execute(
            pg_insert(Publication)
            .values(**_publication_payload(item))
            .on_conflict_do_nothing(index_elements=[Publication.id])
        )
        pending_auths.extend(_authorship_payloads(item))

    if pending_auths:
        candidates = {a["person_id"] for a in pending_auths if a["person_id"] is not None}
        present: set[int] = set()
        if candidates:
            rows = (await session.execute(
                select(Person.person_id).where(Person.person_id.in_(candidates))
            )).scalars().all()
            present = set(rows)
        for a in pending_auths:
            if a["person_id"] is not None and a["person_id"] not in present:
                a["person_id"] = None
            stmt = pg_insert(Authorship).values(**a)
            # При конфликте делаем backfill `person_id`: если в БД уже лежит
            # authorship с person_id=NULL (соавтор был неизвестен на момент его
            # вставки), а теперь у нас есть валидный id — проставляем его.
            # Остальные поля (display_name, href) не трогаем.
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[Authorship.publication_id, Authorship.position],
                    set_={"person_id": func.coalesce(Authorship.person_id, stmt.excluded.person_id)},
                )
            )

    await session.execute(delete(Course).where(Course.person_id == person_id))
    for item in courses:
        if not isinstance(item, dict):
            continue
        await session.execute(pg_insert(Course).values(**_course_payload(person_id, item)))

    return person_id
