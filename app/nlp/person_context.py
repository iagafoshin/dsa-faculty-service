"""Сборка текстового контекста персоны/публикации для NER+embedding."""
from __future__ import annotations

from typing import Any, Iterable

from app.models import Person, Publication
from app.publication_enrichment import clean_html

_MAX_PERSON_CTX = 5000


def _extract_abstract(raw: dict[str, Any] | None) -> str | None:
    if not raw:
        return None
    annotation = raw.get("annotation") or {}
    return clean_html(annotation.get("ru")) or clean_html(annotation.get("en"))


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
    person: Person, publications: list[Publication],
) -> str:
    """Склеивает имя, интересы, биографию, опыт, заголовки и абстракты
    последних публикаций в один текст (~5000 символов).
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
        abstract = _extract_abstract(pub.raw)
        if title and abstract:
            pub_lines.append(f"{title}. {abstract}")
        elif title:
            pub_lines.append(title)
        elif abstract:
            pub_lines.append(abstract)
    if pub_lines:
        parts.append(" ".join(pub_lines))

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

    abstract = _extract_abstract(pub.raw)
    if abstract:
        parts.append(abstract)

    raw = pub.raw or {}
    description = raw.get("description") or {}
    venue = clean_html(description.get("api"))
    if venue:
        parts.append(venue)

    return "\n\n".join(parts)
