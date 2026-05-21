"""HTTP-клиенты к hse.ru — общий (для HTML-страниц профилей) и
к скрытому API publications.hse.ru/api/searchPubs.
"""
from __future__ import annotations

from typing import Any

import requests

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0 Safari/537.36"
)

BASE_URL = "https://www.hse.ru"
PUBS_API_URL = "https://publications.hse.ru/api/searchPubs"

_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT})
        _session = s
    return _session


def get(url: str, **kwargs: Any) -> requests.Response:
    timeout = kwargs.pop("timeout", 30)
    resp = session().get(url, timeout=timeout, **kwargs)
    resp.raise_for_status()
    return resp


def post_json(url: str, payload: dict[str, Any], **kwargs: Any) -> requests.Response:
    timeout = kwargs.pop("timeout", 30)
    headers = kwargs.pop("headers", {}) or {}
    headers.setdefault("Accept", "application/json, text/plain, */*")
    headers.setdefault("Content-Type", "application/json;charset=utf-8")
    headers.setdefault("Referer", "https://www.hse.ru/")
    resp = session().post(url, json=payload, headers=headers, timeout=timeout, **kwargs)
    resp.raise_for_status()
    return resp


# === publications.hse.ru ===

def fetch_publications_page(person_id: int, page: int = 1, count: int = 50) -> dict[str, Any]:
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
    resp = post_json(PUBS_API_URL, payload)
    return resp.json().get("result", {})


def fetch_publications(
    person_id: int, per_page: int = 50, max_pages: int | None = None,
) -> tuple[list[dict], int | None]:
    """Все публикации персоны c пагинацией через скрытый API ВШЭ."""
    items: list[dict[str, Any]] = []
    page = 1
    total: int | None = None
    while True:
        result = fetch_publications_page(person_id, page=page, count=per_page)
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
