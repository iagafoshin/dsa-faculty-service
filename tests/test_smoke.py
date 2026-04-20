from __future__ import annotations

import pytest

GET_ENDPOINTS = [
    "/api/v1/health",
    "/api/v1/ready",
    "/api/v1/persons",
    "/api/v1/publications",
    "/api/v1/news",
    "/api/v1/meta/campuses",
    "/api/v1/meta/publication-types",
]


@pytest.mark.parametrize("path", GET_ENDPOINTS)
async def test_get_endpoints_ok(client, path):
    r = await client.get(path)
    assert r.status_code < 300, f"{path} -> {r.status_code} {r.text[:200]}"
    r.json()


async def test_person_25477(client):
    r = await client.get("/api/v1/persons/25477")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Абанкина" in body["full_name"]
    assert body["publications_total"] > 150


async def test_person_25477_publications(client):
    r = await client.get("/api/v1/publications?author_person_id=25477&page_size=1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] > 150


async def test_person_courses_25477(client):
    r = await client.get("/api/v1/persons/25477/courses?page_size=5")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] > 0
    assert len(body["results"]) > 0


async def test_person_publications_endpoint_25477(client):
    r = await client.get("/api/v1/persons/25477/publications?page_size=5")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] > 150
    first = body["results"][0]
    assert first["id"]
    assert first["type"]


async def test_persons_q_ordering(client):
    r = await client.get("/api/v1/persons?q=Абанкина&ordering=-publications_total")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] >= 1
    assert any(p["person_id"] == 25477 for p in body["results"])


async def test_persons_bad_ordering(client):
    r = await client.get("/api/v1/persons?ordering=bogus")
    assert r.status_code == 400


async def test_search_abankina(client):
    r = await client.get("/api/v1/search?q=Абанкина")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert any(
        hit["type"] == "person" and hit.get("person", {}).get("person_id") == 25477
        for hit in body["results"]
    )


async def test_news_returns_publications(client):
    r = await client.get("/api/v1/news?page_size=5")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "results" in body
    for item in body["results"]:
        assert item["source"] == "publication"


async def test_scrape_job_404(client):
    r = await client.get("/api/v1/admin/scrape/does-not-exist")
    assert r.status_code == 404
