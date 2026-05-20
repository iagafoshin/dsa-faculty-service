"""Smoke-тест экстрактора тегов: для 5 случайных персон с публикациями
строит контекст, прогоняет NER+KeyBERT, печатает теги для проверки глазами.

Запуск (после `pip install -e .[nlp]` и `docker compose up -d db`):

    DATABASE_URL=postgresql+asyncpg://postgres:CHANGE_ME@localhost:5433/hse_faculty \\
        python scripts/test_extractor.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.database import AsyncSessionLocal  # noqa: E402
from app.models import Authorship, Person, Publication  # noqa: E402
from app.nlp.extractor import extract_topics, get_device  # noqa: E402
from app.nlp.person_context import build_person_context  # noqa: E402


async def main() -> None:
    print(f"NLP device: {get_device()}")
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(Person).where(Person.publications_total > 5).limit(5)
        )).scalars().all()

        if not rows:
            print("Нет персон с publications_total > 5 — заполни БД скрейпом.")
            return

        for p in rows:
            pubs = (await s.execute(
                select(Publication)
                .join(Authorship, Authorship.publication_id == Publication.id)
                .where(Authorship.person_id == p.person_id)
                .order_by(Publication.year.desc().nullslast())
                .limit(30)
            )).scalars().all()

            ctx = build_person_context(p, pubs)
            tags = extract_topics(ctx)

            print(f"\n=== {p.full_name} ({p.primary_unit}) ===")
            print(f"Context preview: {ctx[:200]}...")
            print(f"Tags ({len(tags)}): {tags}")


if __name__ == "__main__":
    asyncio.run(main())
