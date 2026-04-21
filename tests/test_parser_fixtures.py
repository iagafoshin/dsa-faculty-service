"""End-to-end parser checks driven by tests/fixtures/manifest.yaml.

Each fixture tag maps to a set of expected values (exact person_id/full_name
and `*_min` minima for list lengths). The tests are parametrized over every
tag in the manifest so adding a new fixture + manifest entry is one-line.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from lxml import html

from app.scraper.parser import make_tree
from app.scraper.profile import scrape_from_tree

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "html"
MANIFEST_PATH = Path(__file__).parent / "fixtures" / "manifest.yaml"


def _load_manifest() -> dict[str, dict[str, Any]]:
    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8")) or {}


def _load_fixture(tag: str):
    path = FIXTURES_DIR / f"{tag}.html"
    if not path.exists():
        raise FileNotFoundError(path)
    return make_tree(path.read_text(encoding="utf-8"))


def _load_manifest_items():
    manifest = _load_manifest()
    return [(tag, expected) for tag, expected in sorted(manifest.items())]


@pytest.fixture(scope="session")
def manifest() -> dict[str, dict[str, Any]]:
    return _load_manifest()


def test_all_fixtures_have_manifest_entries(manifest):
    fixture_files = {p.stem for p in FIXTURES_DIR.glob("*.html")}
    manifest_tags = set(manifest.keys())
    assert fixture_files == manifest_tags, (
        f"fixtures missing from manifest: {fixture_files - manifest_tags}; "
        f"manifest tags with no fixture: {manifest_tags - fixture_files}"
    )


@pytest.mark.parametrize("fixture_tag,expected", _load_manifest_items())
def test_parse_fixture(fixture_tag: str, expected: dict[str, Any]):
    tree = _load_fixture(fixture_tag)
    result = scrape_from_tree(tree, url=expected["url"])

    # Identity
    assert result["meta"]["person_id"] == expected.get("person_id"), (
        f"{fixture_tag}: person_id mismatch — got "
        f"{result['meta']['person_id']!r}, expected {expected.get('person_id')!r}"
    )
    assert result["identity"]["full_name"] == expected["full_name"], (
        f"{fixture_tag}: full_name mismatch — got "
        f"{result['identity']['full_name']!r}, expected {expected['full_name']!r}"
    )

    # profile_url echoed back through meta
    assert result["meta"]["profile_url"] == expected["url"]

    # Sections with min-count assertions
    positions = result["positions"]["employment"]
    if "positions_min" in expected:
        assert len(positions) >= expected["positions_min"], (
            f"{fixture_tag}: positions {len(positions)} < "
            f"{expected['positions_min']}"
        )

    awards = result["education"]["awards"]
    if "awards_min" in expected:
        assert len(awards) >= expected["awards_min"], (
            f"{fixture_tag}: awards {len(awards)} < {expected['awards_min']}"
        )

    confs = result["research"]["conferences"]
    if "has_conferences" in expected:
        if expected["has_conferences"]:
            assert len(confs) > 0, f"{fixture_tag}: expected conferences, got 0"
        else:
            assert len(confs) == 0, (
                f"{fixture_tag}: expected no conferences, got {len(confs)}"
            )
    if "conferences_min" in expected:
        assert len(confs) >= expected["conferences_min"], (
            f"{fixture_tag}: conferences {len(confs)} < "
            f"{expected['conferences_min']}"
        )

    patents = result["patents"]
    if "has_patents" in expected:
        if expected["has_patents"]:
            assert len(patents) > 0, f"{fixture_tag}: expected patents, got 0"
        else:
            assert len(patents) == 0, (
                f"{fixture_tag}: expected no patents, got {len(patents)}"
            )
    if "patents_min" in expected:
        assert len(patents) >= expected["patents_min"], (
            f"{fixture_tag}: patents {len(patents)} < "
            f"{expected['patents_min']}"
        )

    we = result["experience"]["work_experience"]
    if "work_experience_entries_min" in expected:
        assert len(we) >= expected["work_experience_entries_min"], (
            f"{fixture_tag}: work_experience {len(we)} < "
            f"{expected['work_experience_entries_min']}"
        )

    grants = result["research"]["grants"]
    if "grants_min" in expected:
        assert len(grants) >= expected["grants_min"], (
            f"{fixture_tag}: grants {len(grants)} < {expected['grants_min']}"
        )


@pytest.mark.parametrize("fixture_tag,expected", _load_manifest_items())
def test_positions_titles_are_split_not_joined(
    fixture_tag: str, expected: dict[str, Any]
):
    """Each position title should be a single role, not a comma-joined list.

    Regression test for the original bug where a multi-title `<li>` became a
    single string like `"руководитель департамента, профессор:"`.
    """
    tree = _load_fixture(fixture_tag)
    result = scrape_from_tree(tree, url=expected["url"])
    for idx, pos in enumerate(result["positions"]["employment"]):
        title = pos.get("title") or ""
        assert "," not in title, (
            f"{fixture_tag}: positions[{idx}].title contains comma — "
            f"titles should be split: {title!r}"
        )
        assert not title.endswith(":"), (
            f"{fixture_tag}: positions[{idx}].title ends with colon: {title!r}"
        )


def test_admin_aleskerov_positions_split_example():
    """Headline regression: two separate titles on a single multi-title <li>."""
    tree = _load_fixture("admin_aleskerov")
    result = scrape_from_tree(tree, url="https://www.hse.ru/org/persons/140159")
    titles = [p["title"].lower() for p in result["positions"]["employment"]]
    assert "руководитель департамента" in titles
    assert "профессор" in titles


def test_admin_aleskerov_patents_fields():
    """Patent rows carry the canonical set of keys and the Авторы list is split."""
    tree = _load_fixture("admin_aleskerov")
    result = scrape_from_tree(tree, url="https://www.hse.ru/org/persons/140159")
    patents = result["patents"]
    assert len(patents) > 0
    first = patents[0]
    expected_keys = {"number", "kind", "title", "registration", "authors", "year"}
    assert expected_keys.issubset(first.keys()), (
        f"patent keys {set(first.keys())} missing {expected_keys - set(first.keys())}"
    )
    assert isinstance(first["authors"], list)
    assert len(first["authors"]) >= 2


def test_abankina_i_conferences_structured():
    """Conferences carry both legacy `description` and new `title/location/talk_title`."""
    tree = _load_fixture("rich_humanities_abankina_i")
    result = scrape_from_tree(tree, url="https://www.hse.ru/org/persons/25477")
    confs = result["research"]["conferences"]
    assert len(confs) > 0
    structured = [c for c in confs if c.get("title") and c.get("location")]
    # At least some conferences should parse fully structured.
    assert len(structured) >= 5
    sample = structured[0]
    assert sample["year"] is not None
    assert sample["description"]  # legacy field preserved
    assert "links" in sample


def test_technical_neznanov_work_experience_has_year_prefixes():
    """Per-entry strings should include a year-range prefix, not be one blob."""
    tree = _load_fixture("technical_neznanov")
    result = scrape_from_tree(tree, url="https://www.hse.ru/org/persons/4113483")
    we = result["experience"]["work_experience"]
    # Expect multiple entries, most with a year pattern at the start.
    assert len(we) >= 5
    year_prefixed = [s for s in we if s[:4].isdigit() or s[:7].replace(".", "").isdigit()]
    assert len(year_prefixed) >= 3


def test_manager_person_id_extracted_from_url():
    """Managers should carry a person_id parsed from their profile URL."""
    tree = _load_fixture("econ_semenikhin")
    result = scrape_from_tree(tree, url="https://www.hse.ru/org/persons/101503035")
    managers = result["positions"]["managers"]
    assert managers, "expected at least one manager in fixture"
    target = next(
        (m for m in managers if (m.get("url") or "").endswith("/13869964/")),
        None,
    )
    assert target is not None, f"expected /13869964/ manager, got {managers}"
    assert target["person_id"] == 13869964


def test_admin_aleskerov_manager_person_ids_by_url_shape():
    """/org/persons/<digits> yields int; /staff/<non-numeric-slug> yields None."""
    tree = _load_fixture("admin_aleskerov")
    result = scrape_from_tree(tree, url="https://www.hse.ru/org/persons/140159")
    managers = result["positions"]["managers"]
    org_persons = next(
        (m for m in managers if "/org/persons/" in (m.get("url") or "")),
        None,
    )
    assert org_persons is not None
    assert isinstance(org_persons["person_id"], int)
    non_numeric_staff = next(
        (m for m in managers
         if "/staff/" in (m.get("url") or "")
         and not (m["url"].rstrip("/").split("/")[-1]).isdigit()),
        None,
    )
    if non_numeric_staff is not None:
        assert non_numeric_staff["person_id"] is None


def test_staff_slug_without_id_still_parses_name():
    """Profiles hosted at /staff/<slug> may lack numeric IDs but still have a name."""
    for tag in ("staff_slug_empty", "staff_slug_minimal", "staff_slug_no_id"):
        tree = _load_fixture(tag)
        result = scrape_from_tree(tree, url=f"https://www.hse.ru/staff/{tag}")
        assert result["meta"]["person_id"] is None, f"{tag}: should have null id"
        assert result["identity"]["full_name"], f"{tag}: should still have full_name"
