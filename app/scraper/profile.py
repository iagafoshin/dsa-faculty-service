"""Scrape one person profile into the sample_100_persons.json shape."""
from __future__ import annotations

import datetime
from typing import Any

from app.scraper import parser
from app.scraper.client import BASE_URL, get
from app.scraper.publications import fetch_all


def scrape_one_profile(url: str, base_url: str = BASE_URL) -> dict[str, Any] | None:
    resp = get(url)
    tree = parser.make_tree(resp.text)
    if tree is None:
        return None

    person_id = parser.get_person_id(tree, url=url)
    full_name = parser.parse_full_name(tree)
    avatar = parser.parse_avatar(tree, base_url=base_url)
    languages = parser.parse_languages(tree) or []
    contacts = parser.parse_contacts(tree, base_url=base_url) or {}
    managers = parser.parse_managers(tree, base_url=base_url) or []
    research_ids = parser.parse_research_ids(tree, base_url=base_url) or {}
    employment = parser.parse_employment(tree, base_url=base_url) or []
    employment_traits = parser.parse_employment_traits(tree) or []
    employment_addition = parser.parse_employment_addition(tree) or []
    degrees = parser.parse_degrees(tree) or []
    professional_interests = parser.parse_professional_interests(tree, base_url=base_url) or []
    extra_education = parser.parse_extra_education(tree) or []
    awards = parser.parse_awards(tree) or []
    work_experience = parser.parse_work_experience(tree) or []
    theses = parser.parse_theses(tree, base_url=base_url) or []
    courses = parser.parse_courses(tree, base_url=base_url) or []
    grants = parser.parse_grants(tree) or []
    editorial_staff = parser.parse_editorial_staff(tree) or []
    conferences = parser.parse_conferences(tree, base_url=base_url) or []
    news = parser.parse_news(tree, base_url=base_url) or []

    publications: list[dict[str, Any]] = []
    publications_total = 0
    if person_id is not None:
        try:
            pubs, total = fetch_all(person_id, per_page=50)
            publications = pubs
            publications_total = total if total is not None else len(pubs)
        except Exception:
            publications = []
            publications_total = 0

    return {
        "meta": {
            "person_id": person_id,
            "parsed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "research_ids": research_ids,
            "profile_url": url,
        },
        "identity": {
            "full_name": full_name,
            "avatar": avatar,
            "languages": languages,
        },
        "contacts": contacts,
        "positions": {
            "employment": employment,
            "employment_traits": employment_traits,
            "employment_addition": employment_addition,
            "managers": managers,
        },
        "education": {
            "degrees": degrees,
            "extra_education": extra_education,
            "awards": awards,
            "professional_interests": professional_interests,
        },
        "experience": {"work_experience": work_experience},
        "teaching": {"theses": theses, "courses": courses},
        "research": {
            "grants": grants,
            "editorial_staff": editorial_staff,
            "conferences": conferences,
            "publications_total": publications_total,
            "publications": publications,
        },
        "news": news,
    }
