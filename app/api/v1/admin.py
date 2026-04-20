from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.database import AsyncSessionLocal
from app.models import ScrapeJob
from app.schemas.admin import ScrapeJobCreated, ScrapeJobStatus, ScrapeStatus

router = APIRouter()


async def _run_scrape(limit: int | None, campus_id: str | None, job_id: str) -> None:
    from app.scraper.crawler import crawl_and_ingest
    await crawl_and_ingest(limit, campus_id, job_id, AsyncSessionLocal)


@router.post("/scrape", response_model=ScrapeJobCreated, status_code=202)
async def run_scrape(
    background: BackgroundTasks,
    limit: int | None = Query(None, ge=1, le=20000),
    campus_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> ScrapeJobCreated:
    job_id = str(uuid.uuid4())
    job = ScrapeJob(
        job_id=job_id,
        status=ScrapeStatus.queued.value,
        limit_count=limit,
        campus_id=campus_id,
        processed=0,
        total=None,
        started_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()

    background.add_task(_run_scrape, limit, campus_id, job_id)

    return ScrapeJobCreated(
        job_id=job_id, status=ScrapeStatus.queued, estimated_profiles=limit,
    )


@router.get("/scrape/{job_id}", response_model=ScrapeJobStatus)
async def get_scrape_status(job_id: str, db: AsyncSession = Depends(get_db)) -> ScrapeJobStatus:
    job = await db.get(ScrapeJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"Job {job_id} not found"},
        )
    return ScrapeJobStatus(
        job_id=job.job_id, status=ScrapeStatus(job.status),
        processed=job.processed, total=job.total, error=job.error,
        started_at=job.started_at, finished_at=job.finished_at,
    )
