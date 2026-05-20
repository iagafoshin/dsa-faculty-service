from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_session
from app.models import ScrapeJob
from app.schemas import ScrapeJobCreated, ScrapeJobStatus, ScrapeStatus
from app.scraper.crawler import crawl_and_ingest

router = APIRouter()


@router.post("/scrape", response_model=ScrapeJobCreated, status_code=202, tags=["admin"])
async def run_scrape(
    background: BackgroundTasks,
    limit: int | None = Query(None, ge=1, le=20000, description="Лимит профилей."),
    campus_ids: list[str] | None = Query(
        None,
        description="Кампусы для обхода (например 1125608=Москва). Пусто — все.",
    ),
    letters: list[str] | None = Query(
        None,
        description="Буквы фамилии (А, Б, В, ...). Пусто — все.",
    ),
    db: AsyncSession = Depends(get_session),
) -> ScrapeJobCreated:
    job_id = str(uuid.uuid4())
    job = ScrapeJob(
        job_id=job_id,
        status=ScrapeStatus.queued.value,
        limit_count=limit,
        campus_id=",".join(campus_ids) if campus_ids else None,
        processed=0,
        total=None,
        started_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()

    background.add_task(
        crawl_and_ingest, limit, campus_ids, letters, job_id, AsyncSessionLocal,
    )

    return ScrapeJobCreated(
        job_id=job_id, status=ScrapeStatus.queued, estimated_profiles=limit,
    )


@router.get("/scrape/{job_id}", response_model=ScrapeJobStatus, tags=["admin"])
async def get_scrape_status(job_id: str, db: AsyncSession = Depends(get_session)) -> ScrapeJobStatus:
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


@router.post("/scrape/{job_id}/cancel", response_model=ScrapeJobStatus, tags=["admin"])
async def cancel_scrape(job_id: str, db: AsyncSession = Depends(get_session)) -> ScrapeJobStatus:
    job = await db.get(ScrapeJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"Job {job_id} not found"},
        )
    if job.status in (ScrapeStatus.done.value, ScrapeStatus.failed.value, ScrapeStatus.cancelled.value):
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict", "message": f"Job already finished with status: {job.status}"},
        )
    if job.status in (ScrapeStatus.queued.value, ScrapeStatus.running.value):
        job.status = ScrapeStatus.cancelling.value
        await db.commit()
    return ScrapeJobStatus(
        job_id=job.job_id, status=ScrapeStatus(job.status),
        processed=job.processed, total=job.total, error=job.error,
        started_at=job.started_at, finished_at=job.finished_at,
    )
