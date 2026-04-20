"""Crawl HSE campus/letter pages → profile URLs → ingest via services.ingest."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.scraper import parser
from app.scraper.client import BASE_URL, get
from app.scraper.profile import scrape_one_profile
from app.services.ingest import upsert_person

START_URL = "https://www.hse.ru/org/persons/"


def _replace_udept(url: str, new_udept: str) -> str:
    if "udept=" not in url:
        return url
    return re.sub(r"udept=\d+", f"udept={new_udept}", url)


def _fetch_tree(url: str):
    resp = get(url)
    return parser.make_tree(resp.text)


def list_profile_urls(
    campus_id: str | None = None,
    letters: list[str] | None = None,
    limit: int | None = None,
) -> list[str]:
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

    campus_ids: list[str | None]
    if campus_id:
        campus_ids = [campus_id]
    else:
        campus_lis = tree.xpath("//div[contains(@class, 'filter_topunits')]//li[@hse-value]")
        campus_ids = [li.get("hse-value") for li in campus_lis] or [None]

    out: list[str] = []
    seen: set[str] = set()
    for cid in campus_ids:
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
                    out.append(full)
                    if limit is not None and len(out) >= limit:
                        return out
    return out


async def crawl_and_ingest(
    limit: int | None,
    campus_id: str | None,
    job_id: str,
    session_factory: async_sessionmaker,
) -> None:
    from app.models import ScrapeJob

    try:
        urls = await asyncio.to_thread(list_profile_urls, campus_id, None, limit)
    except Exception as e:
        async with session_factory() as s:
            job = await s.get(ScrapeJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error = f"URL enumeration failed: {e!r}"
                job.finished_at = datetime.now(timezone.utc)
                await s.commit()
        return

    total = len(urls)

    async with session_factory() as s:
        job = await s.get(ScrapeJob, job_id)
        if job is not None:
            job.status = "running"
            job.total = total
            await s.commit()

    processed = 0
    try:
        async with session_factory() as s:
            for idx, url in enumerate(urls, start=1):
                try:
                    raw = await asyncio.to_thread(scrape_one_profile, url)
                except Exception:
                    raw = None
                if raw is not None and raw.get("meta", {}).get("person_id"):
                    try:
                        await upsert_person(s, raw)
                    except Exception:
                        await s.rollback()
                processed += 1
                if idx % 10 == 0:
                    await s.commit()
                    job = await s.get(ScrapeJob, job_id)
                    if job is not None:
                        job.processed = processed
                        await s.commit()
            await s.commit()

        async with session_factory() as s:
            job = await s.get(ScrapeJob, job_id)
            if job is not None:
                job.processed = processed
                job.status = "done"
                job.finished_at = datetime.now(timezone.utc)
                await s.commit()
    except Exception as e:  # pragma: no cover - background safety net
        async with session_factory() as s:
            job = await s.get(ScrapeJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error = str(e)[:500]
                job.processed = processed
                job.finished_at = datetime.now(timezone.utc)
                await s.commit()


__all__ = ["list_profile_urls", "crawl_and_ingest"]
