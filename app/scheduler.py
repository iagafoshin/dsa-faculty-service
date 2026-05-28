"""APScheduler-обёртка для периодического обновления данных HSE.

Активируется через ENV: `SCHEDULE_DAYS=7` запускает full-update job
каждые 7 суток. `SCHEDULE_DAYS=0` (default) — scheduler не стартует.

Что делает full-update:
1. Запускает scrape всех преподавателей (через `crawl_and_ingest`)
2. Догоняет ВКР для новых преподов (если есть)
3. enrich-persons (новый NLP-проход)

Этап (3) тяжёлый (CPU + KeyBERT/SentenceTransformer), может занять
20-30 мин — поэтому весь джоб помечен как `max_instances=1`
(параллельные запуски невозможны).

Полный re-embed мы НЕ делаем (только новые/изменённые персоны),
потому что повторные прогоны на одних и тех же контекстах смысла
не имеют — embedding deterministic.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def run_full_update(
    limit: int | None = None,
    job_id_prefix: str = "scheduled",
) -> str:
    """Полный цикл обновления: scrape → ВКР → enrich пустых embedding'ов.

    `limit` — лимит профилей для крawler'а (None = вся HSE).
    `job_id_prefix` — «scheduled» для авто-фаеров, «manual» для ручного
    запуска из /admin (различимо в таблице джобов).

    Возвращает `job_id` созданной записи `ScrapeJob`.
    """
    from app.database import AsyncSessionLocal
    from app.models import ScrapeJob
    from app.schemas import ScrapeStatus
    from app.scraper.crawler import crawl_and_ingest

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    job_id = f"{job_id_prefix}-{ts}-{uuid.uuid4().hex[:6]}"
    logger.info("full-update job starting: %s (limit=%s)", job_id, limit)

    # Записываем ScrapeJob в БД, чтобы было видно в /admin
    async with AsyncSessionLocal() as s:
        s.add(ScrapeJob(
            job_id=job_id,
            status=ScrapeStatus.queued.value,
            limit_count=limit,
            campus_id=None,
            processed=0,
            total=None,
            started_at=datetime.now(timezone.utc),
        ))
        await s.commit()

    try:
        await crawl_and_ingest(
            limit=limit, campus_ids=None, letters=None,
            job_id=job_id, session_factory=AsyncSessionLocal,
        )
    except Exception:
        logger.exception("scrape failed (job %s)", job_id)
        return job_id

    # ВКР + enrich лежат за NLP-стеком. Если он недоступен (прод-docker без
    # torch) — пропускаем, scrape отработал и это уже полезно.
    try:
        from app.scraper.theses_cli import scrape_all as scrape_theses_all
        await scrape_theses_all(only_empty=True, delay=0.15)
    except ImportError:
        logger.info("ВКР-скрейпер недоступен в этой инсталляции; пропускаем")
    except Exception:
        logger.exception("theses scrape failed (job %s)", job_id)

    try:
        from app.nlp.__main__ import enrich_persons
        await enrich_persons(only_empty=True)
    except ImportError:
        logger.info("NLP-стек недоступен в этой инсталляции; пропускаем enrich")
    except Exception:
        logger.exception("enrich failed (job %s)", job_id)

    logger.info("full-update job done: %s", job_id)
    return job_id


# Алиас для APScheduler — он зовёт без аргументов, дефолты подходят.
_run_full_update = run_full_update


def start_scheduler_if_enabled() -> AsyncIOScheduler | None:
    """Стартует APScheduler если SCHEDULE_DAYS > 0. Идемпотентно."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    if settings.schedule_days <= 0:
        logger.info("scheduler disabled (SCHEDULE_DAYS=0)")
        return None

    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        _run_full_update,
        trigger=IntervalTrigger(days=settings.schedule_days),
        id="hse-full-update",
        max_instances=1,
        coalesce=True,         # пропущенные фаер'ы объединяются в один
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "scheduler started: full-update every %s day(s)", settings.schedule_days,
    )

    if settings.schedule_run_on_startup:
        # Стартует один прогон в фоне; не блокирует event loop запуска
        asyncio.create_task(_run_full_update())

    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def get_schedule_info() -> dict[str, Any] | None:
    """Информация для /admin: когда следующий запуск, сколько days-интервал."""
    if _scheduler is None:
        return None
    job = _scheduler.get_job("hse-full-update")
    if job is None:
        return None
    return {
        "interval_days": settings.schedule_days,
        "next_run_time": job.next_run_time,
    }
