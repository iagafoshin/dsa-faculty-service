"""Скрейпинг одного профиля ВШЭ → плоский dict под `upsert_person`."""
from __future__ import annotations

import datetime
from typing import Any

from app.scraper import parser
from app.scraper.client import BASE_URL, fetch_publications, get


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
    if isinstance(year, str):
        year = int(year) if year.isdigit() else None
    elif not isinstance(year, int):
        year = None
    return {"title": str(title).strip(), "year": year, "role": item.get("role")}


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
    person_id = raw.get("person_id")
    if person_id is None:
        person_id = parser.extract_person_id_from_url(url)
    return {
        "person_id": person_id,
        "name": raw.get("name") or "",
        "url": url or None,
        "role": raw.get("role"),
    }


def _compose(tree, url: str, base_url: str, publications_enabled: bool) -> dict[str, Any] | None:
    if tree is None:
        return None

    person_id = parser.get_person_id(tree, url=url)
    if person_id is None:
        return None

    full_name = parser.parse_full_name(tree)
    avatar = parser.parse_avatar(tree, base_url=base_url)
    languages = parser.parse_languages(tree) or []
    contacts = parser.parse_contacts(tree, base_url=base_url) or {}
    managers_raw = parser.parse_managers(tree, base_url=base_url) or []
    research_ids_raw = parser.parse_research_ids(tree, base_url=base_url) or {}
    positions = parser.parse_positions(tree, base_url=base_url) or []
    employment_addition = parser.parse_employment_addition(tree) or []
    degrees = parser.parse_degrees(tree) or []
    interests_raw = parser.parse_professional_interests(tree, base_url=base_url) or []
    extra_education = parser.parse_extra_education(tree) or []
    awards = parser.parse_awards(tree) or []
    work_experience = parser.parse_work_experience(tree) or []
    courses = parser.parse_courses(tree, base_url=base_url) or []
    grants_raw = parser.parse_grants(tree) or []
    editorial_raw = parser.parse_editorial_staff(tree) or []
    conferences_raw = parser.parse_conferences(tree, base_url=base_url) or []
    patents = parser.parse_patents(tree, base_url=base_url) or []

    publications: list[dict[str, Any]] = []
    publications_total = 0
    if publications_enabled:
        try:
            pubs, _ = fetch_publications(person_id, per_page=50)
            publications = pubs
            # Считаем только те, где этот человек реально автор (а не редактор/
            # переводчик). Совпадает с тем, что хранится в `authorships` для него.
            for item in pubs:
                authors = (item.get("authorsByType") or {}).get("author") or []
                for a in authors:
                    if not isinstance(a, dict):
                        continue
                    aid = a.get("id")
                    if aid is not None and str(aid).isdigit() and int(aid) == person_id:
                        publications_total += 1
                        break
        except Exception:
            pass

    primary_unit = None
    if positions:
        units = (positions[0] or {}).get("units") or []
        if units:
            primary_unit = (units[0] or {}).get("name")

    extra_edu_flat = [
        (e.get("text") if isinstance(e, dict) else str(e))
        for e in extra_education
    ]

    return {
        "person_id": int(person_id),
        "full_name": full_name or "",
        "avatar": avatar,
        "profile_url": url,
        "primary_unit": primary_unit,
        "publications_total": publications_total,
        "languages": languages,
        "contacts": {
            "phones": contacts.get("phones"),
            "address": contacts.get("address"),
            "hours": contacts.get("hours"),
            "timetable_url": contacts.get("timetable_url"),
        },
        "positions": positions,
        "relations": {"managers": [_manager_to_ref(m) for m in managers_raw if isinstance(m, dict)]},
        "education": {"degrees": degrees, "extra_education": extra_edu_flat},
        "work_experience": work_experience,
        "awards": awards,
        "interests": [s for s in (_interest_to_str(i) for i in interests_raw) if s],
        "grants": [_grant_to_dict(g) for g in grants_raw],
        "editorial_staff": [s for s in (_editorial_to_str(x) for x in editorial_raw) if s],
        "conferences": [s for s in (_conference_to_str(x) for x in conferences_raw) if s],
        "bio_notes": employment_addition,
        "research_ids": {k: _research_id_to_str(v) for k, v in research_ids_raw.items()},
        "patents": [p for p in patents if isinstance(p, dict)],
        "parsed_at": datetime.datetime.now(datetime.timezone.utc),
        "_publications": publications,
        "_courses": courses,
    }


def scrape_one_profile(url: str, base_url: str = BASE_URL) -> dict[str, Any] | None:
    """Скачивает страницу профиля с ВШЭ и возвращает плоский dict для upsert_person."""
    resp = get(url)
    tree = parser.make_tree(resp.text)
    return _compose(tree, url=url, base_url=base_url, publications_enabled=True)
