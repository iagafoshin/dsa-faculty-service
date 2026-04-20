"""Raw scraped/sample JSON → ORM-ready payloads.

Shape reference: one entry in `data/sample_100_persons.json`.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from dateutil import parser as dateparser

from app.schemas.publication import PublicationType

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


def _interest_to_str(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("label") or item.get("text") or "").strip()
    return str(item).strip()


def _grant_to_dict(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"title": str(item), "year": None, "role": None}

    title = item.get("title") or item.get("text") or ""
    year = item.get("year")
    if year is None:
        years = item.get("years") or {}
        if isinstance(years, dict):
            year = years.get("end") or years.get("start")
    role = item.get("role")
    return {
        "title": str(title).strip(),
        "year": int(year) if isinstance(year, int) else (int(year) if isinstance(year, str) and year.isdigit() else None),
        "role": role,
    }


def _editorial_to_str(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("text") or item.get("journal") or "").strip()
    return str(item).strip()


def _conference_to_str(item: Any) -> str:
    if isinstance(item, dict):
        desc = item.get("description") or ""
        year = item.get("year")
        if year:
            return f"{year}: {desc}".strip()
        return str(desc).strip()
    return str(item).strip()


def _research_id_to_str(v: Any) -> str:
    if isinstance(v, dict):
        return str(v.get("value") or v.get("url") or "")
    return str(v)


def _manager_to_ref(raw: dict[str, Any]) -> dict[str, Any]:
    url = raw.get("url") or ""
    person_id: int | None = None
    m = re.search(r"/persons/(\d+)", url)
    if m:
        try:
            person_id = int(m.group(1))
        except ValueError:
            person_id = None
    return {
        "person_id": person_id,
        "name": raw.get("name") or "",
        "url": url or None,
        "role": raw.get("role"),
    }


def _parse_course_level(meta: str | None) -> str | None:
    if not meta:
        return None
    first = meta.split(";", 1)[0].strip()
    return first or None


def person_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten the messy raw JSON shape into kwargs for the Person ORM model.

    Raises ValueError if the record has no usable person_id.
    """
    meta = raw.get("meta") or {}
    if meta.get("person_id") is None:
        raise ValueError("missing meta.person_id")
    identity = raw.get("identity") or {}
    contacts = raw.get("contacts") or {}
    positions_block = raw.get("positions") or {}
    education_block = raw.get("education") or {}
    experience_block = raw.get("experience") or {}
    research_block = raw.get("research") or {}

    employment = positions_block.get("employment") or []
    primary_unit: str | None = None
    if employment:
        units = (employment[0] or {}).get("units") or []
        if units:
            primary_unit = (units[0] or {}).get("name")

    managers_raw = positions_block.get("managers") or []
    managers = [_manager_to_ref(m) for m in managers_raw if isinstance(m, dict)]

    interests = [
        s for s in (_interest_to_str(i) for i in education_block.get("professional_interests") or [])
        if s
    ]

    research_ids_raw = meta.get("research_ids") or {}
    research_ids = {k: _research_id_to_str(v) for k, v in research_ids_raw.items()}

    grants = [_grant_to_dict(g) for g in research_block.get("grants") or []]
    editorial = [s for s in (_editorial_to_str(x) for x in research_block.get("editorial_staff") or []) if s]
    conferences = [s for s in (_conference_to_str(x) for x in research_block.get("conferences") or []) if s]

    return {
        "person_id": int(meta["person_id"]),
        "full_name": identity.get("full_name") or "",
        "avatar": identity.get("avatar"),
        "profile_url": meta.get("profile_url") or f"https://www.hse.ru/org/persons/{meta['person_id']}",
        "primary_unit": primary_unit,
        "campus_id": None,
        "publications_total": int(research_block.get("publications_total") or 0),
        "languages": identity.get("languages") or [],
        "contacts": {
            "phones": contacts.get("phones"),
            "address": contacts.get("address"),
            "hours": contacts.get("hours"),
            "timetable_url": contacts.get("timetable_url"),
        },
        "positions": employment,
        "relations": {"managers": managers},
        "education": {
            "degrees": education_block.get("degrees") or [],
            "extra_education": [
                (e.get("text") if isinstance(e, dict) else str(e))
                for e in education_block.get("extra_education") or []
            ],
        },
        "work_experience": experience_block.get("work_experience") or [],
        "awards": education_block.get("awards") or [],
        "interests": interests,
        "grants": grants,
        "editorial_staff": editorial,
        "conferences": conferences,
        "bio_notes": positions_block.get("employment_addition") or [],
        "research_ids": research_ids,
        "parsed_at": _parse_iso(meta.get("parsed_at")),
    }


def publication_from_raw(item: dict[str, Any]) -> dict[str, Any]:
    language_raw = item.get("language")
    if isinstance(language_raw, dict):
        language = language_raw.get("name")
    else:
        language = language_raw

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


def authorships_from_raw(pub_item: dict[str, Any]) -> list[dict[str, Any]]:
    authors_block = pub_item.get("authorsByType") or {}
    authors = authors_block.get("author") or []
    pub_id = str(pub_item["id"])
    out: list[dict[str, Any]] = []
    for k, a in enumerate(authors):
        if not isinstance(a, dict):
            continue
        title = a.get("title")
        if isinstance(title, dict):
            display_name = _strip_html(title.get("ru") or title.get("en") or "")
        else:
            display_name = _strip_html(str(title) if title is not None else "")
        if not display_name:
            display_name = a.get("altName") or a.get("otherName") or ""
        author_id_raw = a.get("id")
        person_id: int | None = None
        if isinstance(author_id_raw, (int, str)) and str(author_id_raw).isdigit():
            person_id = int(author_id_raw)
        out.append({
            "publication_id": pub_id,
            "position": k,
            "person_id": person_id,
            "display_name": display_name,
            "href": a.get("href"),
        })
    return out


def course_from_raw(person_id: int, item: dict[str, Any]) -> dict[str, Any]:
    meta_str = item.get("meta")
    return {
        "person_id": person_id,
        "title": item.get("title") or "",
        "url": item.get("url"),
        "academic_year": item.get("academic_year"),
        "language": item.get("language"),
        "level": _parse_course_level(meta_str),
        "raw_meta": meta_str,
    }
