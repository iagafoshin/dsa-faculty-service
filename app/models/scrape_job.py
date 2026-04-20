from datetime import datetime

from sqlalchemy import DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    limit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    campus_id: Mapped[str | None] = mapped_column(String, nullable=True)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
