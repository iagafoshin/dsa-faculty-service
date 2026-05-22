"""Запись (upsert) одного спарсенного преподавателя + его публикаций, авторств и курсов в БД.

Доп. поля публикаций (абстракт, DOI, редакторы, обложка) и обогащение
авторов (display_name_en, is_hse_person) парсятся здесь — один раз при
upsert, потом просто читаются из колонок (без парсинга на read-path).
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from dateutil import parser as dateparser
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Authorship, Course, Person, Publication
from app.schemas import PublicationType

PUBS_BASE = "https://publications.hse.ru"
HSE_BASE = "https://www.hse.ru"

_PUB_TYPES = {t.value for t in PublicationType}
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_EDITOR_ROLES = ("cmn_editor", "resp_editor", "sci_editor")
_TRANSLATOR_ROLES = ("translator", "trn_editor")


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return dateparser.isoparse(str(value))
    except (ValueError, TypeError):
        return None


def _clean_html(s: str | None) -> str | None:
    """Убирает HTML-теги, декодирует entities, схлопывает whitespace. None если пусто."""
    if not s:
        return None
    decoded = html.unescape(s)
    stripped = _HTML_TAG_RE.sub("", decoded)
    cleaned = _WHITESPACE_RE.sub(" ", stripped).strip()
    return cleaned or None


def _absolutize(url: str | None, base: str = PUBS_BASE) -> str | None:
    if not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return base + url
    return base + "/" + url


def _coerce_pub_type(raw_type: Any) -> str:
    if isinstance(raw_type, str) and raw_type in _PUB_TYPES:
        return raw_type
    return PublicationType.OTHER.value


def _extract_author(raw: dict[str, Any], position: int, *, restrict_to_hse: bool) -> dict[str, Any]:
    """Парсит одну авторскую запись из raw.authorsByType.<role>.

    `restrict_to_hse=True` — person_id ставим только для is_hse_person.
    Используется для editors/translators (JSONB-хранение, без FK).
    `restrict_to_hse=False` — person_id для любого digit id.
    Используется для authorships, где FK-проверка обнулит несуществующих
    в таблице persons после вставки.
    """
    title = raw.get("title") or {}
    if isinstance(title, dict):
        display_name = (_clean_html(title.get("ru") or title.get("en") or "") or "")
        display_name_en = (title.get("en") or "").strip() or None
    else:
        display_name = _clean_html(str(title or "")) or ""
        display_name_en = None
    if not display_name:
        display_name = raw.get("altName") or raw.get("otherName") or ""

    raw_href = raw.get("href")
    href = _absolutize(raw_href, base=HSE_BASE) if raw_href else None

    is_hse_person = str(raw.get("enVersionStatus") or "") == "2" and href is not None

    person_id: int | None = None
    if restrict_to_hse:
        if is_hse_person:
            try:
                person_id = int(raw["id"])
            except (KeyError, ValueError, TypeError):
                person_id = None
    else:
        author_id = raw.get("id")
        if isinstance(author_id, (int, str)) and str(author_id).isdigit():
            person_id = int(author_id)

    return {
        "person_id": person_id,
        "display_name": display_name,
        "display_name_en": display_name_en,
        "href": href,
        "is_hse_person": is_hse_person,
        "position": position,
    }


def _collect_role_authors(authors_by_type: dict[str, Any], roles: tuple[str, ...]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    position = 0
    for role in roles:
        for entry in authors_by_type.get(role) or []:
            if isinstance(entry, dict):
                out.append(_extract_author(entry, position, restrict_to_hse=True))
                position += 1
    return out


def _publication_payload(item: dict[str, Any]) -> dict[str, Any]:
    language_raw = item.get("language")
    language = language_raw.get("name") if isinstance(language_raw, dict) else language_raw

    documents = item.get("documents") or {}
    description = item.get("description") or {}
    annotation = item.get("annotation") or {}
    publisher_obj = item.get("publisher") or {}
    publisher_title = publisher_obj.get("title") or {}
    authors_by_type = item.get("authorsByType") or {}

    def _doc_href(key: str) -> str | None:
        doc = documents.get(key)
        if not doc:
            return None
        return _absolutize(doc.get("href"))

    return {
        "id": str(item["id"]),
        "title": item.get("title") or "",
        "type": _coerce_pub_type(item.get("type")),
        "year": item.get("year") if isinstance(item.get("year"), int) else None,
        "language": language,
        "url": None,
        "created_at": _parse_iso(item.get("createdAt")),
        "raw": item,
        # Доп. поля — парсятся один раз при upsert, на read-path просто читаются из колонок
        "abstract_ru": _clean_html(annotation.get("ru")),
        "abstract_en": _clean_html(annotation.get("en")),
        "venue": _clean_html(description.get("api")),
        "citation": _clean_html(description.get("main")),
        "publisher": _clean_html(publisher_title.get("ru")),
        "doi_url": _doc_href("DOI"),
        "document_url": _doc_href("DOCUMENT"),
        "external_url": _doc_href("OTHER_URL"),
        "cover_url": _doc_href("COVER"),
        "editors": _collect_role_authors(authors_by_type, _EDITOR_ROLES),
        "translators": _collect_role_authors(authors_by_type, _TRANSLATOR_ROLES),
    }


def _authorship_payloads(pub_item: dict[str, Any]) -> list[dict[str, Any]]:
    authors = (pub_item.get("authorsByType") or {}).get("author") or []
    pub_id = str(pub_item["id"])
    out: list[dict[str, Any]] = []
    for k, a in enumerate(authors):
        if not isinstance(a, dict):
            continue
        author = _extract_author(a, k, restrict_to_hse=False)
        out.append({
            "publication_id": pub_id,
            "position": k,
            "person_id": author["person_id"],
            "display_name": author["display_name"],
            "display_name_en": author["display_name_en"],
            "href": author["href"],
            "is_hse_person": author["is_hse_person"],
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
        # При конфликте на publications.id перезаписываем все доп. поля,
        # чтобы они отражали свежий raw (HSE может обновить публикацию).
        pub_payload = _publication_payload(item)
        pub_update = {k: v for k, v in pub_payload.items() if k != "id"}
        await session.execute(
            pg_insert(Publication)
            .values(**pub_payload)
            .on_conflict_do_update(index_elements=[Publication.id], set_=pub_update)
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
            # display_name_en и is_hse_person — обновляем безусловно из свежего raw.
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[Authorship.publication_id, Authorship.position],
                    set_={
                        "person_id": func.coalesce(Authorship.person_id, stmt.excluded.person_id),
                        "display_name_en": stmt.excluded.display_name_en,
                        "is_hse_person": stmt.excluded.is_hse_person,
                    },
                )
            )

    await session.execute(delete(Course).where(Course.person_id == person_id))
    for item in courses:
        if not isinstance(item, dict):
            continue
        await session.execute(pg_insert(Course).values(**_course_payload(person_id, item)))

    return person_id
