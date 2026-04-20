"""Seed DB from data/sample_100_persons.json — real HSE data.

Two-pass approach (per AGENT_PROMPT spec):
  Pass 1: insert all persons rows (so FK lookups work).
  Pass 2: insert publications, authorships, courses.

Usage (inside container):
    python scripts/seed_from_sample.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from sqlalchemy import func, select, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import AsyncSessionLocal  # noqa: E402
from app.models import Authorship, Course, Person, Publication  # noqa: E402
from app.services.ingest import upsert_person_core, upsert_person_dependents  # noqa: E402

SAMPLE_PATH = os.environ.get("SAMPLE_PATH", "/code/data/sample_100_persons.json")


async def main() -> None:
    path = Path(SAMPLE_PATH)
    if not path.exists():
        raise SystemExit(f"Sample file not found: {path}")

    print(f"Loading {path} ...")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    persons_raw = data.get("persons") if isinstance(data, dict) else data
    if not isinstance(persons_raw, list):
        raise SystemExit("Unexpected shape — expected dict with 'persons' list")

    print(f"Found {len(persons_raw)} raw persons in sample")

    async with AsyncSessionLocal() as session:
        existing = (await session.execute(select(func.count(Person.person_id)))).scalar_one()
        if existing > 0:
            print(f"DB has {existing} persons — truncating ...")
            await session.execute(
                text("TRUNCATE persons, publications, authorships, courses RESTART IDENTITY CASCADE")
            )
            await session.commit()

        # Pass 1: persons only
        inserted = 0
        skipped = 0
        for raw in persons_raw:
            try:
                await upsert_person_core(session, raw)
                inserted += 1
            except ValueError:
                skipped += 1
                continue
            except Exception as e:
                print(f"  ! person insert failed: {e!r}")
                await session.rollback()
                skipped += 1
                continue
            if inserted % 25 == 0:
                await session.commit()
        await session.commit()
        print(f"Pass 1: inserted {inserted} persons (skipped {skipped})")

        # Pass 2: dependents
        done = 0
        for raw in persons_raw:
            try:
                await upsert_person_dependents(session, raw)
                done += 1
            except Exception as e:
                pid = (raw.get("meta") or {}).get("person_id")
                print(f"  ! dependents failed for {pid}: {e!r}")
                await session.rollback()
                continue
            if done % 10 == 0:
                await session.commit()
        await session.commit()
        print(f"Pass 2: processed {done} persons")

        persons_n = (await session.execute(select(func.count(Person.person_id)))).scalar_one()
        pubs_n = (await session.execute(select(func.count(Publication.id)))).scalar_one()
        auths_n = (await session.execute(select(func.count(Authorship.publication_id)))).scalar_one()
        courses_n = (await session.execute(select(func.count(Course.id)))).scalar_one()
        print(f"\n✅ persons={persons_n}, publications={pubs_n}, authorships={auths_n}, courses={courses_n}")


if __name__ == "__main__":
    asyncio.run(main())
