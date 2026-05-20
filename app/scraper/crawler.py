"""Обходит страницы кампусов/букв на ВШЭ → собирает URL профилей → пишет в БД."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import ScrapeJob
from app.scraper import parser
from app.scraper.client import BASE_URL, get
from app.scraper.ingest import upsert_person
from app.scraper.profile import scrape_one_profile

START_URL = "https://www.hse.ru/org/persons/"


def _replace_udept(url: str, new_udept: str) -> str:
    if "udept=" not in url:
        return url
    return re.sub(r"udept=\d+", f"udept={new_udept}", url)


def _fetch_tree(url: str):
    resp = get(url)
    return parser.make_tree(resp.text)


def list_profile_urls(
    campus_ids: list[str] | None = None,
    letters: list[str] | None = None,
    limit: int | None = None,
) -> list[tuple[str, str | None]]:
    """Собирает URL профилей. Возвращает пары `(url, source_campus_id)`,
    чтобы краулер мог проставить кампус в Person при upsert.

    Если `campus_ids` пуст — обходит все кампусы. Если `letters` пуст — все буквы.
    """
    tree = _fetch_tree(START_URL)
    if tree is None:
        return []

    letter_nodes = tree.xpath("//div[contains(@class, 'abc-filter__letter')]//a")
    letter_templates: list[tuple[str, str]] = []
    for a in letter_nodes:
        href = a.get("href")
        if not href:
            continue
        url = urljoin(START_URL, href)
        letter_text = "".join(a.xpath(".//text()")).strip()
        if letters and letter_text not in letters:
            continue
        letter_templates.append((url, letter_text))

    # Без явного списка кампусов делаем один проход без фильтра udept:
    # HSE отдаст профили со всех кампусов сразу. Авто-разведка фильтра
    # `filter_topunits` подмешивает id отделений, а не реальных кампусов —
    # они ломают FK на Person.campus_id, поэтому их не трогаем.
    resolved_campus_ids: list[str | None] = list(campus_ids) if campus_ids else [None]

    out: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for cid in resolved_campus_ids:
        for tmpl_url, _letter in letter_templates:
            letter_url = _replace_udept(tmpl_url, cid) if cid else tmpl_url
            try:
                t = _fetch_tree(letter_url)
            except Exception:
                continue
            for href in t.xpath("//div[contains(@class, 'content__person-text')]//a/@href"):
                full = urljoin(BASE_URL, href)
                if full not in seen:
                    seen.add(full)
                    out.append((full, cid))
                    if limit is not None and len(out) >= limit:
                        return out
    return out


async def _is_cancelling(session_factory: async_sessionmaker, job_id: str) -> bool:
    """Читает статус задачи в свежей сессии — обходит кеширование identity-map SQLAlchemy."""
    async with session_factory() as s:
        job = await s.get(ScrapeJob, job_id)
        return job is not None and job.status == "cancelling"


async def _finalize(
    session_factory: async_sessionmaker, job_id: str, **fields,
) -> None:
    async with session_factory() as s:
        job = await s.get(ScrapeJob, job_id)
        if job is None:
            return
        for k, v in fields.items():
            setattr(job, k, v)
        await s.commit()


async def crawl_and_ingest(
    limit: int | None,
    campus_ids: list[str] | None,
    letters: list[str] | None,
    job_id: str,
    session_factory: async_sessionmaker,
) -> None:
    try:
        url_pairs = await asyncio.to_thread(list_profile_urls, campus_ids, letters, limit)
    except Exception as e:
        await _finalize(
            session_factory, job_id,
            status="failed",
            error=f"URL enumeration failed: {e!r}",
            finished_at=datetime.now(timezone.utc),
        )
        return

    total = len(url_pairs)
    if await _is_cancelling(session_factory, job_id):
        await _finalize(
            session_factory, job_id,
            status="cancelled", total=total,
            finished_at=datetime.now(timezone.utc),
        )
        return
    await _finalize(session_factory, job_id, status="running", total=total)

    processed = 0
    cancelled = False
    try:
        async with session_factory() as s:
            for idx, (url, cid) in enumerate(url_pairs, start=1):
                if await _is_cancelling(session_factory, job_id):
                    cancelled = True
                    break

                try:
                    raw = await asyncio.to_thread(scrape_one_profile, url)
                except Exception:
                    raw = None
                if raw is not None:
                    if cid is not None:
                        raw["campus_id"] = cid
                    try:
                        await upsert_person(s, raw)
                    except Exception:
                        await s.rollback()
                processed += 1

                if idx % 10 == 0:
                    await s.commit()
                    await _finalize(session_factory, job_id, processed=processed)
            await s.commit()

        await _finalize(
            session_factory, job_id,
            processed=processed,
            status="cancelled" if cancelled else "done",
            finished_at=datetime.now(timezone.utc),
        )
    except Exception as e:
        await _finalize(
            session_factory, job_id,
            status="failed",
            error=str(e)[:500],
            processed=processed,
            finished_at=datetime.now(timezone.utc),
        )


__all__ = ["list_profile_urls", "crawl_and_ingest"]
