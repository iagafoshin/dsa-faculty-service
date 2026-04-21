"""
Enrich Publication response objects with fields extracted from raw JSONB.

All fields added here are derived from the existing `raw` column stored in DB.
No scraping, no migrations. This module is pure functional: raw dict in, enriched
Publication out.
"""

import html
import re
from typing import Any

from app.schemas.publication import AuthorRef, Publication

PUBS_BASE = "https://publications.hse.ru"
HSE_BASE = "https://www.hse.ru"

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

_EDITOR_ROLES = ("cmn_editor", "resp_editor", "sci_editor")
_TRANSLATOR_ROLES = ("translator", "trn_editor")


def clean_html(s: str | None) -> str | None:
    """Strip HTML tags and decode HTML entities. Return None if input is falsy or empty after cleaning."""
    if not s:
        return None
    decoded = html.unescape(s)
    stripped = _HTML_TAG_RE.sub("", decoded)
    cleaned = _WHITESPACE_RE.sub(" ", stripped).strip()
    return cleaned or None


def absolutize_url(url: str | None, base: str = PUBS_BASE) -> str | None:
    """Return absolute URL. If url is None/empty, return None. If absolute, return as-is."""
    if not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return base + url
    return base + "/" + url


def _author_from_raw(raw_author: dict[str, Any], position: int) -> AuthorRef:
    """Build an AuthorRef from one entry of raw.authorsByType.* list."""
    title = raw_author.get("title") or {}
    display_name = (title.get("ru") or "").strip()
    display_name_en_raw = (title.get("en") or "").strip()
    display_name_en = display_name_en_raw or None

    raw_href = raw_author.get("href")
    href = absolutize_url(raw_href, base=HSE_BASE) if raw_href else None

    ev_status = str(raw_author.get("enVersionStatus") or "")
    is_hse_person = ev_status == "2" and href is not None

    person_id: int | None = None
    if is_hse_person:
        try:
            person_id = int(raw_author["id"])
        except (KeyError, ValueError, TypeError):
            person_id = None

    return AuthorRef(
        person_id=person_id,
        display_name=display_name,
        display_name_en=display_name_en,
        href=href,
        is_hse_person=is_hse_person,
        position=position,
    )


def _collect_authors(authors_by_type: dict[str, Any], roles: tuple[str, ...]) -> list[AuthorRef]:
    """Collect AuthorRef entries from the given roles, skipping None lists."""
    result: list[AuthorRef] = []
    position = 0
    for role in roles:
        entries = authors_by_type.get(role)
        if not entries:
            continue
        for entry in entries:
            result.append(_author_from_raw(entry, position))
            position += 1
    return result


def enrich_publication(base: Publication, raw: dict[str, Any] | None) -> Publication:
    """Build a new Publication with enrichment fields filled from raw JSONB.

    Pure function — does not mutate `base`. If `raw` is empty/None, returns base unchanged.
    """
    if not raw:
        return base

    documents = raw.get("documents") or {}
    description = raw.get("description") or {}
    annotation = raw.get("annotation") or {}
    publisher_obj = raw.get("publisher") or {}
    publisher_title = publisher_obj.get("title") or {}
    authors_by_type = raw.get("authorsByType") or {}

    abstract_ru = clean_html(annotation.get("ru"))
    abstract_en = clean_html(annotation.get("en"))

    venue = clean_html(description.get("api"))
    citation = clean_html(description.get("main"))

    publisher = clean_html(publisher_title.get("ru"))

    def _doc_href(key: str) -> str | None:
        doc = documents.get(key)
        if not doc:
            return None
        return absolutize_url(doc.get("href"))

    doi_url = _doc_href("DOI")
    document_url = _doc_href("DOCUMENT")
    external_url = _doc_href("OTHER_URL")
    cover_url = _doc_href("COVER")

    authors_raw = authors_by_type.get("author")
    if authors_raw:
        authors = [_author_from_raw(a, i) for i, a in enumerate(authors_raw)]
    else:
        authors = base.authors

    editors = _collect_authors(authors_by_type, _EDITOR_ROLES)
    translators = _collect_authors(authors_by_type, _TRANSLATOR_ROLES)

    return base.model_copy(update={
        "authors": authors,
        "abstract_ru": abstract_ru,
        "abstract_en": abstract_en,
        "venue": venue,
        "citation": citation,
        "publisher": publisher,
        "doi_url": doi_url,
        "document_url": document_url,
        "external_url": external_url,
        "cover_url": cover_url,
        "editors": editors,
        "translators": translators,
    })
