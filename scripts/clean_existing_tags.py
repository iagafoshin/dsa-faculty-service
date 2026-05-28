"""One-shot: чистка `persons.interests_extracted` БЕЗ перезапуска KeyBERT.

Берём текущие теги, прогоняем через apply_filters + normalize_phrase
(те же правила, что и в основном pipeline), пишем обратно. Это даёт
быстрый preview результата нормализации до полного re-embed —
особенно полезно когда KeyBERT-этап занимает 20-30 минут.

Запуск:
    DATABASE_URL=... .venv/bin/python -m scripts.clean_existing_tags
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from sqlalchemy import func, select, update
from tqdm import tqdm

# Гарантируем, что app/ виден при запуске как `python scripts/clean_existing_tags.py`
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.database import AsyncSessionLocal  # noqa: E402
from app.models import Person  # noqa: E402
from app.nlp.extractor import apply_filters  # noqa: E402


async def main() -> None:
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(Person.person_id, Person.full_name, Person.interests_extracted)
            .where(func.jsonb_array_length(Person.interests_extracted) > 0)
        )).all()

    print(f"persons with non-empty tags: {len(rows)}")
    total_before = 0
    total_after = 0

    async with AsyncSessionLocal() as s:
        pbar = tqdm(rows, desc="clean", unit="p")
        for pid, name, raw_tags in pbar:
            if not isinstance(raw_tags, list):
                continue
            total_before += len(raw_tags)
            cleaned = apply_filters(list(raw_tags), person_name=name or "")
            total_after += len(cleaned)
            await s.execute(
                update(Person)
                .where(Person.person_id == pid)
                .values(interests_extracted=cleaned)
            )
        await s.commit()

    print(f"tags: {total_before} -> {total_after}  (dropped {total_before - total_after})")


if __name__ == "__main__":
    asyncio.run(main())
