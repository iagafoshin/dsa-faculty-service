"""Сборка текстового контекста персоны/публикации для NER+embedding."""
from __future__ import annotations

from typing import Any, Iterable

from app.models import Course, Person, Publication, Thesis

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
    theses: list[Thesis] | None = None,
) -> str:
    """Склеивает имя, интересы, биографию, опыт, заголовки и абстракты
    последних публикаций + уникальные названия преподаваемых курсов
    + темы курируемых ВКР (если есть) в один текст (~5000 символов).

    Порядок секций важен: при усечении до _MAX_PERSON_CTX в конце урежется
    хвост публикаций, а не интересы / ВКР / курсы — это самый плотный
    «студенто-релевантный» сигнал и должен оставаться приоритетным.
    """
    parts: list[str] = [person.full_name]

    interests = _take_lines(person.interests)
    if interests:
        parts.append("Интересы: " + "; ".join(interests))

    # Темы ВКР — высочайший по релевантности студентскому домену сигнал
    # (студенты ищут научрука именно под такие формулировки). Берём до 50
    # последних работ, чтобы не съесть весь context.
    if theses:
        thesis_titles: list[str] = []
        seen_t: set[str] = set()
        for t in theses[:50]:
            title = (t.title or "").strip()
            if title and title not in seen_t:
                seen_t.add(title)
                thesis_titles.append(title)
        if thesis_titles:
            parts.append("Темы ВКР: " + "; ".join(thesis_titles))

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
    # БЕЗ заголовка «Преподаваемые курсы:» — в v3 убрали, потому что
    # KeyBERT тянул сам header в топ-тегов («преподаваемые курсы» — 144 раза).
    seen_titles: set[str] = set()
    course_lines: list[str] = []
    for c in courses:
        title = (c.title or "").strip()
        if title and title not in seen_titles:
            seen_titles.add(title)
            course_lines.append(title)
    if course_lines:
        parts.append("\n".join(course_lines))

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
