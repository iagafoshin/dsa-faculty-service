"""One-shot backfill для миграции 0004.

Для каждой публикации читает `raw` JSONB → вычисляет новые колонки
(abstract_ru/en, doi_url, editors, ...) через ту же логику, что
теперь работает при scrape (см. app.scraper.ingest._publication_payload).
Заодно проставляет authorships.display_name_en и .is_hse_person.

Запуск (из venv с .[nlp]):

    DATABASE_URL=postgresql+asyncpg://postgres:CHANGE_ME@localhost:5433/hse_faculty \\
        python scripts/backfill_publication_extras.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update  # noqa: E402

from app.database import AsyncSessionLocal  # noqa: E402
from app.models import Authorship, Publication  # noqa: E402
from app.scraper.ingest import _extract_author, _publication_payload  # noqa: E402

PUB_FIELDS = (
    "abstract_ru", "abstract_en", "venue", "citation", "publisher",
    "doi_url", "document_url", "external_url", "cover_url",
    "editors", "translators",
)


async def main() -> None:
    async with AsyncSessionLocal() as s:
        pubs = (await s.execute(select(Publication))).scalars().all()
        total = len(pubs)
        print(f"backfilling {total} publications...")

        for i, pub in enumerate(pubs, start=1):
            payload = _publication_payload(pub.raw or {})
            pub_update = {k: payload[k] for k in PUB_FIELDS}
            await s.execute(
                update(Publication).where(Publication.id == pub.id).values(**pub_update)
            )

            # Authorships для этой публикации — обновляем display_name_en и is_hse_person
            authors_raw = (pub.raw.get("authorsByType") if pub.raw else None) or {}
            for pos, raw_author in enumerate(authors_raw.get("author") or []):
                if not isinstance(raw_author, dict):
                    continue
                author = _extract_author(raw_author, pos, restrict_to_hse=False)
                await s.execute(
                    update(Authorship)
                    .where(
                        Authorship.publication_id == pub.id,
                        Authorship.position == pos,
                    )
                    .values(
                        display_name_en=author["display_name_en"],
                        is_hse_person=author["is_hse_person"],
                    )
                )

            if i % 500 == 0:
                await s.commit()
                print(f"  {i}/{total}")

        await s.commit()
        print(f"done: {total} publications backfilled")


if __name__ == "__main__":
    asyncio.run(main())
