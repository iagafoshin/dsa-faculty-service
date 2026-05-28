"""Скрейпер ВКР (выпускных квалификационных работ) с hse.ru.

Хитрый API ВШЭ: `https://www.hse.ru/n/vkr/api/?supervisorId={id}` отдаёт
ВСЕ ВКР, где данная персона указана научруком, одним JSON-ответом без
пагинации. Один запрос на персону.

Пишем в `theses` + `thesis_supervisors` (M2M, у работы бывает 2+ научрука).
Upsert по `thesis_id`, при коллизии — обновляем поля; supervisor-связи
сначала чистим для этой персоны, потом пишем заново.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Person, Thesis, ThesisSupervisor
from app.scraper.client import get

logger = logging.getLogger(__name__)

VKR_API_URL = "https://www.hse.ru/n/vkr/api/"
_PERSON_URL_RE = re.compile(r"/org/persons/(\d+)")


def fetch_theses_for_person(person_id: int) -> list[dict[str, Any]]:
    """Возвращает все ВКР, где person_id — научрук. Без пагинации."""
    resp = get(VKR_API_URL, params={"supervisorId": person_id})
    payload = resp.json()
    if not payload.get("success"):
        logger.warning("vkr api returned success=false for supervisor %s", person_id)
        return []
    return payload.get("data") or []


def _extract_supervisor_ids(item: dict[str, Any]) -> list[tuple[int, str | None]]:
    """Из `supervisors: [{url, name}]` → `[(person_id, name), ...]`."""
    out: list[tuple[int, str | None]] = []
    for s in item.get("supervisors") or []:
        if not isinstance(s, dict):
            continue
        url = s.get("url") or ""
        m = _PERSON_URL_RE.search(url)
        if not m:
            continue
        out.append((int(m.group(1)), s.get("name")))
    return out


def _thesis_payload(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        thesis_id = int(item["id"])
    except (KeyError, ValueError, TypeError):
        return None
    title = (item.get("title") or "").strip()
    if not title:
        return None

    org_unit = (item.get("orgUnit") or {}).get("title") if isinstance(item.get("orgUnit"), dict) else None
    program_obj = item.get("learnProgram") or {}
    program = program_obj.get("title") if isinstance(program_obj, dict) else None
    program_url = program_obj.get("url") if isinstance(program_obj, dict) else None
    year = item.get("year") if isinstance(item.get("year"), int) else None

    return {
        "thesis_id": thesis_id,
        "title": title,
        "year": year,
        "level": item.get("level") or None,
        "student": item.get("student") or None,
        "program": program,
        "program_url": program_url,
        "org_unit": org_unit,
        "has_en_version": bool(item.get("hasEnVersion")),
        "raw": item,
    }


async def upsert_theses_for_person(
    session: AsyncSession, person_id: int, items: list[dict[str, Any]],
) -> int:
    """Пишет ВКР этой персоны: upsert по thesis_id, потом перебивает её
    supervisor-связи. Связи других научруков не трогаем — они будут
    дописаны, когда дойдём до них в общем проходе.
    """
    # Кэш существующих person_id — чтобы не падать на FK, если один из
    # сонаучруков ещё не заскрейплен в persons.
    known_ids: set[int] = set()
    candidate_ids: set[int] = {person_id}
    for it in items:
        candidate_ids.update(pid for pid, _ in _extract_supervisor_ids(it))
    if candidate_ids:
        rows = (await session.execute(
            select(Person.person_id).where(Person.person_id.in_(candidate_ids))
        )).scalars().all()
        known_ids = set(rows)

    if person_id not in known_ids:
        logger.warning("supervisor %s not in persons table — skipping", person_id)
        return 0

    written = 0
    for item in items:
        payload = _thesis_payload(item)
        if payload is None:
            continue

        # Upsert thesis row.
        update_fields = {k: v for k, v in payload.items() if k != "thesis_id"}
        await session.execute(
            pg_insert(Thesis)
            .values(**payload)
            .on_conflict_do_update(
                index_elements=[Thesis.thesis_id], set_=update_fields,
            )
        )

        # Connect this person; ALSO record co-supervisors that exist in persons.
        for sup_pid, sup_name in _extract_supervisor_ids(item):
            if sup_pid not in known_ids:
                continue
            stmt = pg_insert(ThesisSupervisor).values(
                thesis_id=payload["thesis_id"],
                person_id=sup_pid,
                display_name=sup_name,
            )
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[ThesisSupervisor.thesis_id, ThesisSupervisor.person_id],
                    set_={"display_name": stmt.excluded.display_name},
                )
            )
        written += 1

    return written


__all__ = ["fetch_theses_for_person", "upsert_theses_for_person"]
