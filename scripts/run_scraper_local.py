"""Run the scraper CLI-style against the DB (bypasses the admin endpoint).

Usage (inside container):
    python scripts/run_scraper_local.py --limit=5 --campus-id=1125608
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timezone

from app.database import AsyncSessionLocal  # noqa: E402
from app.models import ScrapeJob  # noqa: E402
from app.scraper.crawler import crawl_and_ingest  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--campus-id", dest="campus_id", type=str, default=None)
    return p.parse_args()


async def main() -> None:
    args = parse_args()
    job_id = str(uuid.uuid4())

    async with AsyncSessionLocal() as s:
        s.add(
            ScrapeJob(
                job_id=job_id,
                status="queued",
                limit_count=args.limit,
                campus_id=args.campus_id,
                processed=0,
                started_at=datetime.now(timezone.utc),
            )
        )
        await s.commit()

    print(f"▶️  Scrape job {job_id} — limit={args.limit} campus_id={args.campus_id}")
    await crawl_and_ingest(args.limit, args.campus_id, job_id, AsyncSessionLocal)

    async with AsyncSessionLocal() as s:
        job = await s.get(ScrapeJob, job_id)
        print(
            f"✅ status={job.status} processed={job.processed} total={job.total} "
            f"started={job.started_at} finished={job.finished_at} error={job.error}"
        )


if __name__ == "__main__":
    asyncio.run(main())
