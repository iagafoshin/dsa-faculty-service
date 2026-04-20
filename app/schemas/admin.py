from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class ScrapeStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class ScrapeJobCreated(BaseModel):
    job_id: str
    status: ScrapeStatus
    estimated_profiles: int | None = None


class ScrapeJobStatus(BaseModel):
    job_id: str
    status: ScrapeStatus
    processed: int
    total: int | None = None
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
