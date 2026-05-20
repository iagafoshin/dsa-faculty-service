"""CLI-запуск скрейпа.

Примеры:
    python -m app.scraper --limit=5
    python -m app.scraper --limit=100 --campus-ids=1125608
    python -m app.scraper --letters=А,Б,В
    python -m app.scraper --campus-ids=1125608,1125610 --letters=А

Создаёт запись ScrapeJob, запускает краулер, печатает итоговый статус.
То же самое, что POST /api/v1/admin/scrape, только из терминала.
"""
from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import datetime, timezone

from app.database import AsyncSessionLocal
from app.models import ScrapeJob
from app.scraper.crawler import crawl_and_ingest


def _split_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()] or None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=5)
    p.add_argument(
        "--campus-ids", dest="campus_ids", type=str, default=None,
        help="Через запятую, например: 1125608,1125610",
    )
    p.add_argument(
        "--letters", type=str, default=None,
        help="Через запятую, например: А,Б,В",
    )
    return p.parse_args()


async def main() -> None:
    args = parse_args()
    campus_ids = _split_csv(args.campus_ids)
    letters = _split_csv(args.letters)
    job_id = str(uuid.uuid4())

    async with AsyncSessionLocal() as s:
        s.add(
            ScrapeJob(
                job_id=job_id,
                status="queued",
                limit_count=args.limit,
                campus_id=",".join(campus_ids) if campus_ids else None,
                processed=0,
                started_at=datetime.now(timezone.utc),
            )
        )
        await s.commit()

    print(
        f"▶️  Scrape job {job_id} — limit={args.limit} "
        f"campus_ids={campus_ids} letters={letters}"
    )
    await crawl_and_ingest(args.limit, campus_ids, letters, job_id, AsyncSessionLocal)

    async with AsyncSessionLocal() as s:
        job = await s.get(ScrapeJob, job_id)
        print(
            f"✅ status={job.status} processed={job.processed} total={job.total} "
            f"started={job.started_at} finished={job.finished_at} error={job.error}"
        )


if __name__ == "__main__":
    asyncio.run(main())
