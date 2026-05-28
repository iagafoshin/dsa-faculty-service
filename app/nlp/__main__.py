"""CLI-входная точка: `python -m app.nlp <command> [options]`.

Команды:
    enrich-persons       — для всех персон в БД извлекает теги и эмбеддит профиль
    enrich-publications  — то же для публикаций

Архитектура наполнения:
- keyset-pagination по PK (Person.person_id / Publication.id) — без offset-сдвигов на больших объёмах
- публикации/курсы персоны подгружаются ОДНИМ запросом на батч (без N+1)
- extract_topics_batch + embed_batch — реальный батчинг spaCy/SentenceTransformer
- одна транзакция на батч
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from tqdm import tqdm

from app.database import AsyncSessionLocal
from app.models import Authorship, Course, Person, Publication, Thesis, ThesisSupervisor
from app.nlp.embedder import embed_batch
from app.nlp.extractor import extract_topics_batch, get_device
from app.nlp.person_context import build_person_context, build_publication_context

logger = logging.getLogger(__name__)

# Минимальная длина текста контекста персоны для запуска NER+embedding.
# Меньше — это профили без публикаций / с пустыми био / 1-2 строки и
# теги/эмбеддинг будут шумом ("начал работать", "году").
PERSON_MIN_CONTEXT_LEN = 500


async def _fetch_pubs_for_persons(
    s: AsyncSession, person_ids: list[int], per_person: int = 30,
) -> dict[int, list[Publication]]:
    """{person_id: [Publication до per_person штук, отсортированных по году DESC]}.
    Один SQL-запрос на весь батч вместо N+1.
    """
    rows = (await s.execute(
        select(Authorship.person_id, Publication)
        .join(Publication, Authorship.publication_id == Publication.id)
        .where(Authorship.person_id.in_(person_ids))
        .order_by(
            Authorship.person_id,
            Publication.year.desc().nullslast(),
            Publication.id,
        )
    )).all()
    out: dict[int, list[Publication]] = {pid: [] for pid in person_ids}
    for pid, pub in rows:
        if len(out[pid]) < per_person:
            out[pid].append(pub)
    return out


async def _fetch_courses_for_persons(
    s: AsyncSession, person_ids: list[int],
) -> dict[int, list[Course]]:
    """{person_id: [Course, ...]} — ВСЕ курсы персон в батче за один запрос.
    Дедуп по title происходит позже, в build_person_context.
    """
    rows = (await s.execute(
        select(Course)
        .where(Course.person_id.in_(person_ids))
        .order_by(Course.person_id, Course.academic_year.desc().nullslast())
    )).scalars().all()
    out: dict[int, list[Course]] = {pid: [] for pid in person_ids}
    for c in rows:
        out[c.person_id].append(c)
    return out


async def _fetch_theses_for_persons(
    s: AsyncSession, person_ids: list[int], per_person: int = 50,
) -> dict[int, list[Thesis]]:
    """{person_id: [Thesis, ...]} — ВКР персон в батче, отсортированы по году DESC."""
    rows = (await s.execute(
        select(ThesisSupervisor.person_id, Thesis)
        .join(Thesis, ThesisSupervisor.thesis_id == Thesis.thesis_id)
        .where(ThesisSupervisor.person_id.in_(person_ids))
        .order_by(
            ThesisSupervisor.person_id,
            Thesis.year.desc().nullslast(),
            Thesis.thesis_id,
        )
    )).all()
    out: dict[int, list[Thesis]] = {pid: [] for pid in person_ids}
    for pid, t in rows:
        if len(out[pid]) < per_person:
            out[pid].append(t)
    return out


async def enrich_persons(
    sample: int | None = None, batch: int = 100, only_empty: bool = False,
) -> None:
    print(f"NLP device: {get_device()}")
    async with AsyncSessionLocal() as s:
        count_q = select(func.count(Person.person_id))
        if only_empty:
            count_q = count_q.where(Person.embedding.is_(None))
        total = (await s.execute(count_q)).scalar_one()
        if sample is not None:
            total = min(total, sample)
        print(f"persons to process: {total}")

        last_id = 0
        processed = 0
        enriched = 0
        skipped = 0
        pbar = tqdm(total=total, desc="persons", unit="p")

        while True:
            if sample is not None and processed >= sample:
                break

            q = (
                select(Person)
                .where(Person.person_id > last_id)
                .order_by(Person.person_id)
                .limit(batch)
            )
            if only_empty:
                q = q.where(Person.embedding.is_(None))
            persons: list[Person] = list((await s.execute(q)).scalars().all())
            if not persons:
                break

            if sample is not None:
                remaining = sample - processed
                if len(persons) > remaining:
                    persons = persons[:remaining]

            person_ids = [p.person_id for p in persons]
            pubs_by_person = await _fetch_pubs_for_persons(s, person_ids)
            courses_by_person = await _fetch_courses_for_persons(s, person_ids)
            theses_by_person = await _fetch_theses_for_persons(s, person_ids)

            contexts_all = [
                build_person_context(
                    p,
                    pubs_by_person.get(p.person_id, []),
                    courses_by_person.get(p.person_id, []),
                    theses_by_person.get(p.person_id, []),
                )
                for p in persons
            ]

            # Делим на «годных» (контекст ≥ MIN) и «пропущенных».
            qualified: list[tuple[Person, str]] = []
            skipped_persons: list[Person] = []
            for p, ctx in zip(persons, contexts_all):
                if len(ctx) >= PERSON_MIN_CONTEXT_LEN:
                    qualified.append((p, ctx))
                else:
                    skipped_persons.append(p)

            # Для пропущенных явно сбрасываем поля, чтобы старые шумные
            # значения из прошлых прогонов не оставались в БД.
            for p in skipped_persons:
                await s.execute(
                    update(Person)
                    .where(Person.person_id == p.person_id)
                    .values(interests_extracted=[], embedding=None)
                )

            if qualified:
                q_persons = [x[0] for x in qualified]
                q_contexts = [x[1] for x in qualified]
                q_names = [p.full_name for p in q_persons]
                tags_list = extract_topics_batch(q_contexts, person_names=q_names)
                vectors = embed_batch(q_contexts)
                for p, tags, vec in zip(q_persons, tags_list, vectors):
                    await s.execute(
                        update(Person)
                        .where(Person.person_id == p.person_id)
                        .values(interests_extracted=tags, embedding=vec)
                    )

            await s.commit()

            last_id = person_ids[-1]
            processed += len(persons)
            enriched += len(qualified)
            skipped += len(skipped_persons)
            pbar.update(len(persons))

        pbar.close()
        print(
            f"done: persons enriched = {enriched}, "
            f"skipped {skipped} persons due to insufficient context "
            f"(<{PERSON_MIN_CONTEXT_LEN} chars)"
        )


async def enrich_publications(
    sample: int | None = None, batch: int = 200, only_empty: bool = False,
) -> None:
    print(f"NLP device: {get_device()}")
    async with AsyncSessionLocal() as s:
        # Считаем только публикации с непустым title (NOT NULL по схеме, но
        # фильтруем и пустые строки — context из них не сложится).
        count_q = select(func.count(Publication.id)).where(Publication.title != "")
        if only_empty:
            count_q = count_q.where(Publication.embedding.is_(None))
        total = (await s.execute(count_q)).scalar_one()
        if sample is not None:
            total = min(total, sample)
        print(f"publications to process: {total}")

        last_id = ""  # PK — строка, keyset-пагинация лексикографически
        processed = 0
        pbar = tqdm(total=total, desc="publications", unit="p")

        while True:
            if sample is not None and processed >= sample:
                break

            q = (
                select(Publication)
                .where(Publication.id > last_id, Publication.title != "")
                .order_by(Publication.id)
                .limit(batch)
            )
            if only_empty:
                q = q.where(Publication.embedding.is_(None))
            pubs: list[Publication] = list((await s.execute(q)).scalars().all())
            if not pubs:
                break

            if sample is not None:
                remaining = sample - processed
                if len(pubs) > remaining:
                    pubs = pubs[:remaining]

            contexts = [build_publication_context(p) for p in pubs]
            tags_list = extract_topics_batch(contexts)
            vectors = embed_batch(contexts)

            for p, tags, vec in zip(pubs, tags_list, vectors):
                await s.execute(
                    update(Publication)
                    .where(Publication.id == p.id)
                    .values(topics=tags, embedding=vec)
                )
            await s.commit()

            last_id = pubs[-1].id
            processed += len(pubs)
            pbar.update(len(pubs))

        pbar.close()
        print(f"done: publications enriched = {processed}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.nlp")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser(
        "enrich-persons",
        help="NER + embedding для персон (Person.interests_extracted, Person.embedding)",
    )
    p1.add_argument("--sample", type=int, default=None,
                    help="ограничить общее число обрабатываемых записей")
    p1.add_argument("--batch", type=int, default=100,
                    help="размер батча (default 100)")
    p1.add_argument("--only-empty", action="store_true",
                    help="пропускать записи где embedding IS NOT NULL")

    p2 = sub.add_parser(
        "enrich-publications",
        help="NER + embedding для публикаций (Publication.topics, Publication.embedding)",
    )
    p2.add_argument("--sample", type=int, default=None)
    p2.add_argument("--batch", type=int, default=200)
    p2.add_argument("--only-empty", action="store_true")

    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.cmd == "enrich-persons":
        asyncio.run(enrich_persons(
            sample=args.sample, batch=args.batch, only_empty=args.only_empty,
        ))
    elif args.cmd == "enrich-publications":
        asyncio.run(enrich_publications(
            sample=args.sample, batch=args.batch, only_empty=args.only_empty,
        ))


if __name__ == "__main__":
    main()
