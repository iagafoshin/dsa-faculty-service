"""Idempotent upserts for person / publication / authorship / course."""
from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Authorship, Course, Person, Publication
from app.services import mapping


async def _existing_person_ids(session: AsyncSession, candidates: Iterable[int]) -> set[int]:
    ids = {c for c in candidates if c is not None}
    if not ids:
        return set()
    rows = (
        await session.execute(select(Person.person_id).where(Person.person_id.in_(ids)))
    ).scalars().all()
    return set(rows)


async def upsert_person_core(session: AsyncSession, raw: dict[str, Any]) -> int:
    """Upsert ONLY the persons row. Pass 1 of seed."""
    payload = mapping.person_from_raw(raw)
    stmt = (
        pg_insert(Person)
        .values(**payload)
        .on_conflict_do_update(
            index_elements=[Person.person_id],
            set_={k: v for k, v in payload.items() if k != "person_id"},
        )
    )
    await session.execute(stmt)
    return payload["person_id"]


async def upsert_person_dependents(session: AsyncSession, raw: dict[str, Any]) -> None:
    """Upsert publications, authorships, courses for a person. Pass 2 of seed."""
    meta = raw.get("meta") or {}
    person_id = meta.get("person_id")
    if person_id is None:
        return
    person_id = int(person_id)

    pubs_raw = (raw.get("research") or {}).get("publications") or []
    pending_auths: list[dict[str, Any]] = []
    for item in pubs_raw:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        pub_payload = mapping.publication_from_raw(item)
        await session.execute(
            pg_insert(Publication)
            .values(**pub_payload)
            .on_conflict_do_nothing(index_elements=[Publication.id])
        )
        pending_auths.extend(mapping.authorships_from_raw(item))

    candidate_ids = {a["person_id"] for a in pending_auths if a["person_id"] is not None}
    present = await _existing_person_ids(session, candidate_ids)
    for a in pending_auths:
        if a["person_id"] is not None and a["person_id"] not in present:
            a["person_id"] = None
        await session.execute(
            pg_insert(Authorship)
            .values(**a)
            .on_conflict_do_nothing(
                index_elements=[Authorship.publication_id, Authorship.position]
            )
        )

    courses_raw = (raw.get("teaching") or {}).get("courses") or []
    await session.execute(delete(Course).where(Course.person_id == person_id))
    for item in courses_raw:
        if not isinstance(item, dict):
            continue
        await session.execute(
            pg_insert(Course).values(**mapping.course_from_raw(person_id, item))
        )


async def upsert_person(session: AsyncSession, raw: dict[str, Any]) -> int:
    """One-shot upsert: person + pubs + auths + courses. Used by scraper."""
    person_id = await upsert_person_core(session, raw)
    await upsert_person_dependents(session, raw)
    return person_id


async def person_exists(session: AsyncSession, person_id: int) -> bool:
    q = select(Person.person_id).where(Person.person_id == person_id)
    res = await session.execute(q)
    return res.scalar_one_or_none() is not None
