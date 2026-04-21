from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas.publication import Publication, PublicationType
from app.services.publication_enrichment import (
    absolutize_url,
    clean_html,
    enrich_publication,
)

FIXTURES = Path(__file__).parent / "fixtures" / "json" / "publications"


def load_fixture(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


def _base_from_raw(raw: dict) -> Publication:
    return Publication(
        id=str(raw["id"]),
        title=raw["title"],
        type=PublicationType(raw["type"]),
        year=raw.get("year"),
    )


def test_clean_html_removes_tags_and_entities():
    assert clean_html("<p>Hello&nbsp;world</p>") == "Hello world"
    assert clean_html("text <i>italic</i> more") == "text italic more"
    assert clean_html(None) is None
    assert clean_html("") is None
    assert clean_html("  <br/>  ") is None


def test_absolutize_url():
    assert (
        absolutize_url("/pubs/share/direct/x.docx")
        == "https://publications.hse.ru/pubs/share/direct/x.docx"
    )
    assert absolutize_url("https://example.com/x") == "https://example.com/x"
    assert absolutize_url("http://example.com/x") == "http://example.com/x"
    assert absolutize_url(None) is None
    assert absolutize_url("") is None


def test_enrich_article_with_doi():
    raw = load_fixture("ARTICLE_with_doi.json")
    base = _base_from_raw(raw)
    enriched = enrich_publication(base, raw)

    assert enriched.doi_url == "https://doi.org/10.18572/1811-1475-2022-7-58-64"
    assert enriched.external_url == "https://www.elibrary.ru/item.asp?id=49159091"
    assert enriched.abstract_ru is not None
    assert enriched.abstract_ru.startswith("В статье анализируется")
    assert "<p>" not in enriched.abstract_ru
    assert "&nbsp;" not in enriched.abstract_ru
    assert enriched.venue == "Юридический мир 2022 № 7 С. 58–64"
    assert enriched.citation is not None
    assert enriched.citation.startswith("Абакумова Е. В.")
    assert len(enriched.authors) == 1
    assert enriched.authors[0].display_name == "Абакумова Е. В."


def test_enrich_article_no_doi():
    raw = load_fixture("ARTICLE.json")
    base = _base_from_raw(raw)
    enriched = enrich_publication(base, raw)

    assert enriched.doi_url is None
    assert enriched.document_url is not None
    assert enriched.document_url.startswith("https://")
    assert enriched.document_url.endswith(".docx")
    assert enriched.abstract_ru is not None
    assert enriched.abstract_en is not None
    assert "<" not in enriched.abstract_ru
    assert "<" not in enriched.abstract_en
    assert "&nbsp;" not in enriched.abstract_ru
    assert "&nbsp;" not in enriched.abstract_en


def test_enrich_book_with_editors():
    raw = load_fixture("BOOK.json")
    base = _base_from_raw(raw)
    enriched = enrich_publication(base, raw)

    assert enriched.publisher == "Просвещение"
    assert enriched.external_url is not None
    assert enriched.external_url.startswith("https://prosv.ru/")

    assert len(enriched.authors) == 24
    assert len(enriched.editors) >= 2

    hse_authors = [a for a in enriched.authors if a.is_hse_person]
    assert len(hse_authors) >= 5

    expected_hse_ids = {25477, 305052776, 137306335, 204488, 4433000, 65855647}
    found_ids = {a.person_id for a in hse_authors}
    assert expected_hse_ids.issubset(found_ids)

    for author in enriched.authors:
        if not author.is_hse_person:
            assert author.person_id is None


def test_enrich_chapter_ignores_parent_book_data():
    raw = load_fixture("CHAPTER.json")
    base = _base_from_raw(raw)
    enriched = enrich_publication(base, raw)

    assert enriched.venue is not None
    assert "<i>" not in enriched.venue
    assert "</i>" not in enriched.venue

    assert enriched.citation is not None
    assert enriched.citation.startswith("Абанкина И. В.")

    assert not any(f.startswith("parent_book") for f in type(enriched).model_fields)


def test_enrich_preprint_minimal():
    raw = load_fixture("PREPRINT.json")
    base = _base_from_raw(raw)
    enriched = enrich_publication(base, raw)

    assert enriched.type == PublicationType(raw["type"])


def test_enrich_with_empty_raw_returns_base():
    base = Publication(id="x", title="t", type=PublicationType.ARTICLE, year=2020)

    for raw_val in ({}, None):
        enriched = enrich_publication(base, raw_val)
        assert enriched.abstract_ru is None
        assert enriched.abstract_en is None
        assert enriched.venue is None
        assert enriched.citation is None
        assert enriched.publisher is None
        assert enriched.doi_url is None
        assert enriched.document_url is None
        assert enriched.external_url is None
        assert enriched.cover_url is None
        assert enriched.editors == []
        assert enriched.translators == []
