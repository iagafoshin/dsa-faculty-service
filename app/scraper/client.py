from __future__ import annotations

from typing import Any

import requests

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0 Safari/537.36"
)

BASE_URL = "https://www.hse.ru"

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
