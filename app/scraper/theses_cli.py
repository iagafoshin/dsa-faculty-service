"""CLI: `python -m app.scraper.theses_cli` — скрейпит ВКР по супервайзерам.

Команды:
    one    — один person_id (отладка)
    all    — все преподаватели (whitelist по позициям, как в поиске)

Использует API `https://www.hse.ru/n/vkr/api/?supervisorId=X` через
синхронный requests-клиент, обёрнутый в asyncio.to_thread, чтобы не
блокировать сессию.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time

from sqlalchemy import func, select, text
from tqdm import tqdm

from app.database import AsyncSessionLocal
from app.models import Person, ThesisSupervisor
from app.scraper.theses import fetch_theses_for_person, upsert_theses_for_person

logger = logging.getLogger(__name__)

# Тот же whitelist, что в app/vector_search.py — гоняем ВКР только для
# реально преподающих, чтобы не делать ~5k лишних запросов на менеджеров.
TEACHER_TITLE_RE = (
    r"(преподавател|доцент|профессор|ассистент|"
    r"научный сотрудник|научный руководител|"
    r"академическ\w+ руководител|заведующий кафедр)"
)

_TEACHER_FILTER = text(
    "EXISTS ("
    " SELECT 1 FROM jsonb_array_elements(persons.positions) p"
    " WHERE lower(p->>'title') ~ :teacher_re"
    ")"
).bindparams(teacher_re=TEACHER_TITLE_RE)


async def scrape_one(person_id: int, delay: float = 0.0) -> int:
    async with AsyncSessionLocal() as s:
        items = await asyncio.to_thread(fetch_theses_for_person, person_id)
        if delay:
            await asyncio.sleep(delay)
        n = await upsert_theses_for_person(s, person_id, items)
        await s.commit()
        return n


async def scrape_all(
    *, only_empty: bool = False, sample: int | None = None, delay: float = 0.2,
) -> None:
    async with AsyncSessionLocal() as s:
        q = select(Person.person_id).where(_TEACHER_FILTER)
        if only_empty:
            # Пропускаем тех, у кого уже что-то записано в thesis_supervisors.
            q = q.where(~Person.person_id.in_(
                select(ThesisSupervisor.person_id).distinct()
            ))
        q = q.order_by(Person.person_id)
        if sample:
            q = q.limit(sample)
        person_ids = (await s.execute(q)).scalars().all()

    print(f"persons to scrape: {len(person_ids)}")
    total_written = 0
    failures = 0
    start = time.monotonic()

    pbar = tqdm(person_ids, desc="VKR", unit="person")
    for pid in pbar:
        try:
            async with AsyncSessionLocal() as s:
                items = await asyncio.to_thread(fetch_theses_for_person, pid)
                n = await upsert_theses_for_person(s, pid, items)
                await s.commit()
                total_written += n
        except Exception as e:
            failures += 1
            logger.warning("person %s failed: %s", pid, e)
        if delay:
            await asyncio.sleep(delay)

    elapsed = time.monotonic() - start
    print(
        f"done: persons={len(person_ids)} "
        f"theses_written={total_written} "
        f"failures={failures} "
        f"elapsed={elapsed:.0f}s"
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.scraper.theses_cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("one", help="скрейп одного person_id")
    p1.add_argument("person_id", type=int)

    p2 = sub.add_parser("all", help="скрейп всех преподавателей")
    p2.add_argument("--sample", type=int, default=None,
                    help="ограничить N персонами (для отладки)")
    p2.add_argument("--only-empty", action="store_true",
                    help="пропускать тех, у кого уже есть ВКР в БД")
    p2.add_argument("--delay", type=float, default=0.2,
                    help="пауза между запросами, сек (default 0.2 → ~5 req/s)")

    return p


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _build_parser().parse_args()
    if args.cmd == "one":
        n = asyncio.run(scrape_one(args.person_id))
        print(f"theses written: {n}")
    elif args.cmd == "all":
        asyncio.run(scrape_all(
            only_empty=args.only_empty, sample=args.sample, delay=args.delay,
        ))


if __name__ == "__main__":
    main()
