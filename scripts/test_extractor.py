"""Smoke-тест экстрактора тегов на фиксированной выборке из 5 персон.

Person_id захардкожены, чтобы будущие итерации экстрактора сравнивались
с этой же выборкой (см. notes/extractor_v*_sample.txt). При смене выборки
обязательно обновляй и notes/.

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

# Зафиксированная выборка для воспроизводимых сравнений итераций.
# Это первые 5 алфавитно отсортированных персон с publications_total > 5
# после скрейпа --limit=500 без фильтров. Не менять без обновления
# notes/extractor_v*_sample.txt.
SAMPLE_PERSON_IDS: list[int] = [
    25477,      # Абанкина Ирина Всеволодовна
    203662,     # Абанкина Татьяна Всеволодовна
    32509610,   # Абашкин Василий Львович
    203698,     # Абдрахманова Гульнара Ибрагимовна
    305052776,  # Абдуллаев Александр Максимович
]


async def main() -> None:
    print(f"NLP device: {get_device()}")
    async with AsyncSessionLocal() as s:
        for pid in SAMPLE_PERSON_IDS:
            p = await s.get(Person, pid)
            if p is None:
                print(f"\n=== person_id={pid} НЕ НАЙДЕНА в БД ===")
                continue

            pubs = (await s.execute(
                select(Publication)
                .join(Authorship, Authorship.publication_id == Publication.id)
                .where(Authorship.person_id == p.person_id)
                .order_by(Publication.year.desc().nullslast())
                .limit(30)
            )).scalars().all()

            ctx = build_person_context(p, pubs)
            tags = extract_topics(ctx, person_name=p.full_name)

            print(f"\n=== {p.full_name} ({p.primary_unit}) — person_id={pid} ===")
            print(f"Context preview: {ctx[:200]}...")
            print(f"Tags ({len(tags)}): {tags}")


if __name__ == "__main__":
    asyncio.run(main())
