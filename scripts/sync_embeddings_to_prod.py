"""Sync NLP-обогащений (interests_extracted, topics, embedding) из
локальной БД в прод-БД.

ИДЕЯ: NLP-batch (enrich-persons / enrich-publications) — тяжёлая операция
на 1-2 часа с torch/MPS. На VPS её гонять не хочется (нет GPU, тратится
RAM). Считаем локально (с M-series MPS), потом переносим колонки
embedding + interests_extracted + topics на прод. Идемпотентно — можно
гонять заново после новых enrich'ей.

Использование:

  # 1. На локальной машине открой SSH-туннель к проду:
  ssh -L 5434:127.0.0.1:5433 user@your-vps.example.ru
  # (это пробрасывает порт 5434 локалки → 127.0.0.1:5433 проде, где у нас
  # биндится prod-Postgres)

  # 2. В отдельном терминале:
  DATABASE_URL_LOCAL='postgresql+asyncpg://postgres:LOCAL_PWD@localhost:5433/hse_faculty' \\
  DATABASE_URL_PROD='postgresql+asyncpg://postgres:PROD_PWD@localhost:5434/hse_faculty' \\
  python scripts/sync_embeddings_to_prod.py

Скрипт перенесёт:
  - persons.interests_extracted, persons.embedding
  - publications.topics, publications.embedding
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.models import Person, Publication  # noqa: E402

BATCH = 500


async def _sync_persons(local_sess_maker, prod_sess_maker) -> None:
    async with local_sess_maker() as local:
        rows = (await local.execute(
            select(Person.person_id, Person.embedding, Person.interests_extracted)
            .where(Person.embedding.is_not(None))
        )).all()
    print(f"persons to sync: {len(rows)}")
    if not rows:
        return

    async with prod_sess_maker() as prod:
        for i, (pid, emb, tags) in enumerate(rows, start=1):
            await prod.execute(
                update(Person)
                .where(Person.person_id == pid)
                .values(embedding=emb, interests_extracted=tags or [])
            )
            if i % BATCH == 0:
                await prod.commit()
                print(f"  persons: {i}/{len(rows)}")
        await prod.commit()
    print(f"persons done ({len(rows)})")


async def _sync_publications(local_sess_maker, prod_sess_maker) -> None:
    # Публикации читаем порциями (их ~71k), чтобы не съесть RAM.
    async with local_sess_maker() as local:
        total = (await local.execute(
            select(Publication.id).where(Publication.embedding.is_not(None))
        )).scalars().all()
    total_n = len(total)
    print(f"publications to sync: {total_n}")
    if not total_n:
        return

    last_id = ""
    processed = 0
    async with prod_sess_maker() as prod:
        while True:
            async with local_sess_maker() as local:
                chunk = (await local.execute(
                    select(Publication.id, Publication.embedding, Publication.topics)
                    .where(Publication.embedding.is_not(None))
                    .where(Publication.id > last_id)
                    .order_by(Publication.id)
                    .limit(BATCH)
                )).all()
            if not chunk:
                break
            for pid, emb, topics in chunk:
                await prod.execute(
                    update(Publication)
                    .where(Publication.id == pid)
                    .values(embedding=emb, topics=topics or [])
                )
            await prod.commit()
            processed += len(chunk)
            last_id = chunk[-1][0]
            print(f"  publications: {processed}/{total_n}")
    print(f"publications done ({processed})")


async def main() -> None:
    local_url = os.environ.get("DATABASE_URL_LOCAL")
    prod_url = os.environ.get("DATABASE_URL_PROD")
    if not local_url or not prod_url:
        print("ERROR: задай DATABASE_URL_LOCAL и DATABASE_URL_PROD")
        sys.exit(1)

    print(f"LOCAL: {local_url.split('@')[-1]}")
    print(f"PROD : {prod_url.split('@')[-1]}")
    print()

    local_engine = create_async_engine(local_url, pool_pre_ping=True)
    prod_engine = create_async_engine(prod_url, pool_pre_ping=True)
    local_sess = async_sessionmaker(local_engine, expire_on_commit=False)
    prod_sess = async_sessionmaker(prod_engine, expire_on_commit=False)

    try:
        await _sync_persons(local_sess, prod_sess)
        print()
        await _sync_publications(local_sess, prod_sess)
    finally:
        await local_engine.dispose()
        await prod_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
