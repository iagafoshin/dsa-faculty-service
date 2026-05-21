"""Сборка текстового контекста персоны/публикации для NER+embedding."""
from __future__ import annotations

from typing import Any, Iterable

from app.models import Course, Person, Publication

_MAX_PERSON_CTX = 5000


def _take_lines(items: Iterable[Any], limit: int | None = None) -> list[str]:
    """Превращает iterable в список строк, пустые отбрасывает."""
    lines: list[str] = []
    for x in items or []:
        s = str(x).strip()
        if s:
            lines.append(s)
            if limit is not None and len(lines) >= limit:
                break
    return lines


def build_person_context(
    person: Person,
    publications: list[Publication],
    courses: list[Course],
) -> str:
    """Склеивает имя, интересы, биографию, опыт, заголовки и абстракты
    последних публикаций + уникальные названия преподаваемых курсов
    в один текст (~5000 символов).
    """
    parts: list[str] = [person.full_name]

    interests = _take_lines(person.interests)
    if interests:
        parts.append("Интересы: " + "; ".join(interests))

    bio = _take_lines(person.bio_notes)
    if bio:
        parts.append(" ".join(bio))

    experience = _take_lines(person.work_experience, limit=5)
    if experience:
        parts.append(" ".join(experience))

    pub_lines: list[str] = []
    for pub in publications[:30]:
        title = (pub.title or "").strip()
        abstract = pub.abstract_ru or pub.abstract_en
        if title and abstract:
            pub_lines.append(f"{title}. {abstract}")
        elif title:
            pub_lines.append(title)
        elif abstract:
            pub_lines.append(abstract)
    if pub_lines:
        parts.append(" ".join(pub_lines))

    # Уникальные курсы — один title раз (курс может вестись несколько лет /
    # в разных группах, но семантически это один и тот же сигнал).
    seen_titles: set[str] = set()
    course_lines: list[str] = []
    for c in courses:
        title = (c.title or "").strip()
        if title and title not in seen_titles:
            seen_titles.add(title)
            course_lines.append(title)
    if course_lines:
        parts.append("Преподаваемые курсы:\n" + "\n".join(course_lines))

    text = "\n\n".join(parts)
    if len(text) > _MAX_PERSON_CTX:
        text = text[:_MAX_PERSON_CTX]
    return text


def build_publication_context(pub: Publication) -> str:
    """Контекст одной публикации = заголовок + абстракт + venue."""
    parts: list[str] = []
    title = (pub.title or "").strip()
    if title:
        parts.append(title)

    abstract = pub.abstract_ru or pub.abstract_en
    if abstract:
        parts.append(abstract)

    if pub.venue:
        parts.append(pub.venue)

    return "\n\n".join(parts)
