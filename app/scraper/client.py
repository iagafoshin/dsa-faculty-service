from __future__ import annotations

import time
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


def _with_retries(method: str, url: str, **kwargs: Any) -> requests.Response:
    last_exc: Exception | None = None
    delays = [1, 2, 4]
    for i in range(4):
        try:
            resp = session().request(method, url, timeout=kwargs.pop("timeout", 30), **kwargs)
            if resp.status_code >= 500:
                raise requests.HTTPError(f"{resp.status_code} from {url}")
            return resp
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            last_exc = e
            if i == len(delays):
                break
            time.sleep(delays[i])
    assert last_exc is not None
    raise last_exc


def get(url: str, **kwargs: Any) -> requests.Response:
    resp = _with_retries("GET", url, **kwargs)
    resp.raise_for_status()
    return resp


def post_json(url: str, payload: dict[str, Any], **kwargs: Any) -> requests.Response:
    headers = kwargs.pop("headers", {}) or {}
    headers.setdefault("Accept", "application/json, text/plain, */*")
    headers.setdefault("Content-Type", "application/json;charset=utf-8")
    headers.setdefault("Referer", "https://www.hse.ru/")
    resp = _with_retries("POST", url, json=payload, headers=headers, **kwargs)
    resp.raise_for_status()
    return resp
