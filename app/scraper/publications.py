"""Fetch publications from publications.hse.ru hidden API."""
from __future__ import annotations

from typing import Any

from app.scraper.client import post_json

API_URL = "https://publications.hse.ru/api/searchPubs"


def fetch_page(person_id: int, page: int = 1, count: int = 50) -> dict[str, Any]:
    filter_params = (
        f'"acceptLanguage":"ru"|'
        f'"pubsAuthor": {person_id}|'
        f'"widgetName": "AuthorSearch"'
    )
    payload = {
        "type": "ANY",
        "filterParams": filter_params,
        "paginationParams": {
            "publsSort": ["YEAR_DESC", "TITLE_ASC"],
            "publsCount": count,
            "pageId": page,
        },
    }
    resp = post_json(API_URL, payload)
    return resp.json().get("result", {})


def fetch_all(person_id: int, per_page: int = 50, max_pages: int | None = None) -> tuple[list[dict], int | None]:
    items: list[dict[str, Any]] = []
    page = 1
    total: int | None = None
    while True:
        result = fetch_page(person_id, page=page, count=per_page)
        items.extend(result.get("items") or [])
        if total is None:
            total = result.get("total")
        more = result.get("more", False)
        remaining = result.get("remaining", 0)
        if not more or remaining <= 0 or not result.get("items"):
            break
        if max_pages is not None and page >= max_pages:
            break
        page += 1
    return items, total
