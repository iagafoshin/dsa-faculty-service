"""HTML-страницы (Jinja2 + Tailwind via CDN) поверх существующего JSON API.

Роуты живут в корне (`/`, `/persons`, `/publications`, `/persons/{id}`).
JSON-API остаётся под `/api/v1/...`.

Для секции «Эксперты» на главной нужны NLP-зависимости — в прод-Docker
их нет, в этом случае секция покажет «не удалось получить данные»
вместо краша.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin_auth import require_admin_basic
from app.database import AsyncSessionLocal, get_session
from app.models import Authorship, Campus, Course, Person, Publication, ScrapeJob
from app.routes import _attach_authors  # shared dict[str, list[AuthorRef]] builder
from app.schemas import AuthorRef, ScrapeStatus
from app.scraper.crawler import crawl_and_ingest
from app.vector_search import (
    TEACHER_FILTER_SQL,
    compute_matched_topics,
    faculty_filter_sql,
    vector_search_persons,
    vector_search_publications,
)

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


# === helpers ===

PUB_TYPES = ["ARTICLE", "BOOK", "PREPRINT", "CHAPTER", "CONFERENCE", "THESIS", "OTHER"]

# Бейджи релевантности для UI. Числовой cosine score прячем — он
# выглядит как «вероятность» и сбивает с толку (0.3 для эмбеддингов
# MiniLM это норма «слабого матча», а не «33%»). Юзеру важна категория.
SCORE_TIER_STRONG = 0.60   # ≥ — «высокое»
SCORE_TIER_MEDIUM = 0.45   # ≥ — «среднее»
SCORE_TIER_WEAK = 0.30     # ≥ — «слабое»; ниже — отбрасываем


def _score_tier(score: float) -> tuple[str, str] | None:
    """Возвращает (label, css_class) или None если score нужно скрыть."""
    if score >= SCORE_TIER_STRONG:
        return "высокое совпадение", "tier-strong"
    if score >= SCORE_TIER_MEDIUM:
        return "среднее совпадение", "tier-medium"
    if score >= SCORE_TIER_WEAK:
        return "слабое совпадение", "tier-weak"
    return None


# Определение «запрос похож на ФИО».
# Базовый случай — 1-3 слова с заглавной кириллицы («Иванов», «Кузнецов Сергей
# Олегович», «Иванов И П»). Сюда же добавляем lowercase-вариант для одиночных
# слов («паринов») — типичная опечатка, юзер ищет фамилию. Для 2+ слов lowercase
# уже значит topic («машинное обучение»), не имя.
_NAME_TOKEN_RE = re.compile(r"^[А-ЯЁ][а-яё]+\.?$|^[А-ЯЁ]\.?$")
_LOWER_SURNAME_RE = re.compile(r"^[а-яё]{4,}$")


def looks_like_name_query(q: str) -> bool:
    words = (q or "").strip().split()
    if not (1 <= len(words) <= 3):
        return False
    if all(_NAME_TOKEN_RE.fullmatch(w) for w in words):
        return True
    # Lowercase-фамилия одним словом — даём шанс ILIKE-секции.
    if len(words) == 1 and _LOWER_SURNAME_RE.fullmatch(words[0]):
        return True
    return False


async def _list_campuses(db: AsyncSession) -> list[dict[str, str]]:
    rows = (await db.execute(select(Campus).order_by(Campus.campus_name))).scalars().all()
    return [{"campus_id": r.campus_id, "campus_name": r.campus_name} for r in rows]


async def _resolve_campus_id(db: AsyncSession, campus_input: str) -> str | None:
    """Сопоставляет введённое имя кампуса с campus_id. Substring-match: «моск» →
    «Москва» → её id. Возвращает None если ничего не нашли.
    """
    campus_input = (campus_input or "").strip()
    if not campus_input:
        return None
    row = (await db.execute(
        select(Campus.campus_id)
        .where(Campus.campus_name.ilike(f"%{campus_input}%"))
        .limit(1)
    )).first()
    return row[0] if row else None


_UNIT_MIN_PERSONS = 30  # порог для datalist — мелочь типа «лаборатория …» только шумит


async def _list_units(db: AsyncSession) -> list[str]:
    """Крупные `primary_unit` для datalist-автокомплита.

    Только подразделения с >= _UNIT_MIN_PERSONS эмбедденных преподов —
    это ~17 ключевых факультетов/институтов. Мелкие лаборатории, базовые
    кафедры РАН и центры (20-30 человек на каждый, десятки штук) только
    раздували datalist и студент в них не ориентируется. Свободный ввод
    в input всё равно работает — datalist это подсказки, не whitelist.
    """
    rows = (await db.execute(
        select(Person.primary_unit, func.count())
        .where(Person.primary_unit.is_not(None))
        .where(Person.embedding.is_not(None))
        .group_by(Person.primary_unit)
        .having(func.count() >= _UNIT_MIN_PERSONS)
        .order_by(func.count().desc(), Person.primary_unit.asc())
    )).all()
    return [u for u, _ in rows]


def _pub_to_dict(p: Publication, authors: list[AuthorRef] | None = None) -> dict[str, Any]:
    # HSE publications API: raw.status == 2 → «accepted for publication» /
    # forthcoming. Такие записи приходят с предполагаемым годом выхода
    # (бывает в БУДУЩЕМ — отсюда статьи 2027 года в выдаче 2026-го).
    # Дополнительно ставим флаг если year > текущего на всякий случай
    # (некоторые status=1 тоже могут оказаться future-year по ошибке).
    raw_status = str((p.raw or {}).get("status") or "")
    is_forthcoming = raw_status == "2" or (
        p.year is not None and p.year > datetime.now(timezone.utc).year
    )
    return {
        "id": p.id,
        "title": p.title,
        "year": p.year,
        "type": p.type,
        "language": p.language,
        "publisher": p.publisher,
        "venue": p.venue,
        "citation": p.citation,
        "abstract_ru": p.abstract_ru,
        "abstract_en": p.abstract_en,
        "doi_url": p.doi_url,
        "document_url": p.document_url,
        "external_url": p.external_url,
        "cover_url": p.cover_url,
        "editors": p.editors or [],
        "translators": p.translators or [],
        "authors": authors or [],
        "is_forthcoming": is_forthcoming,
    }


# === GET / (home — search) ===

_EXP_PAGE_SIZE = 5
_EXP_MAX_PAGE = 10  # после top-50 cosine-score обычно уже мусорный

# Запросы-примеры для главной (показываются под полем поиска при пустом q).
# Проверены руками после full re-embed с ВКР-контекстом — даём ровно те,
# что стабильно выдают «высокое» / «среднее» совпадение в топе.
_EXAMPLE_QUERIES = [
    "Машинное обучение для медицинских изображений",
    "Дообучение LLM для финансовой аналитики",
    "Анализ временных рядов в эконометрике",
    "Квантовые алгоритмы оптимизации",
    "Веб-приложение для обучения программированию",
]


async def _fetch_card_stats(
    db: AsyncSession, person_ids: list[int],
) -> dict[int, dict[str, int]]:
    """Уникальные курсы + ВКР по списку person_id — одним батчем.

    Для карточек на главной: видеть «Публикаций · Курсов · ВКР» в одну
    строку. БД-агрегат вместо N+1, индексы по person_id уже есть.
    """
    if not person_ids:
        return {}
    out: dict[int, dict[str, int]] = {pid: {"courses": 0, "theses": 0} for pid in person_ids}

    from app.models import Course, ThesisSupervisor
    course_rows = (await db.execute(
        select(Course.person_id, func.count(func.distinct(Course.title)))
        .where(Course.person_id.in_(person_ids))
        .group_by(Course.person_id)
    )).all()
    for pid, n in course_rows:
        out[pid]["courses"] = int(n)

    thesis_rows = (await db.execute(
        select(ThesisSupervisor.person_id, func.count())
        .where(ThesisSupervisor.person_id.in_(person_ids))
        .group_by(ThesisSupervisor.person_id)
    )).all()
    for pid, n in thesis_rows:
        out[pid]["theses"] = int(n)

    return out


def _extra_units(person: Person) -> list[str]:
    """Все уникальные имена `positions[].units[].name`, кроме primary_unit.

    Используется на карточках как чипсы — у совмещённых преподов второй
    факультет тоже виден.
    """
    seen: set[str] = set()
    out: list[str] = []
    primary = (person.primary_unit or "").strip()
    for pos in person.positions or []:
        if not isinstance(pos, dict):
            continue
        for u in pos.get("units") or []:
            name = (u.get("name") or "").strip() if isinstance(u, dict) else ""
            if name and name != primary and name not in seen:
                seen.add(name)
                out.append(name)
    return out


_BROWSE_ORDER = {
    "full_name": (Person.full_name.asc(), "имя ↑"),
    "-full_name": (Person.full_name.desc(), "имя ↓"),
    "publications_total": (Person.publications_total.asc(), "публикаций ↑"),
    "-publications_total": (Person.publications_total.desc(), "публикаций ↓"),
}
_BROWSE_PAGE_SIZE = 20


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    q: str | None = None,
    # Кампус приходит как свободный текст ("моск" / "Санкт-Петербург") и
    # резолвится в campus_id ниже. Старый параметр `campus_id=` поддерживаем
    # для совместимости с закладками и редиректом со старого /persons.
    campus: str | None = None,
    campus_id: str | None = None,
    faculty: str | None = None,
    exp_page: int = Query(1, ge=1, le=_EXP_MAX_PAGE),
    # Browse-mode параметры (когда q пустой — листаем всех преподов).
    page: int = Query(1, ge=1),
    ordering: str = "-publications_total",
    has_publications: str | None = None,
    db: AsyncSession = Depends(get_session),
):
    faculty = (faculty or "").strip()
    campus = (campus or "").strip()
    # Если пришёл свободный текст в `campus`, резолвим в id; иначе используем
    # старый campus_id напрямую.
    if campus and not campus_id:
        campus_id = await _resolve_campus_id(db, campus)
    is_name_query = looks_like_name_query(q or "")

    def exp_page_url(new_page: int) -> str:
        params: dict[str, Any] = {"exp_page": new_page}
        if q: params["q"] = q
        if campus_id: params["campus_id"] = campus_id
        if faculty: params["faculty"] = faculty
        return "/?" + urlencode(params) + "#experts"

    ctx: dict[str, Any] = {
        "request": request,
        "q": q,
        "campus_id": campus_id,
        "campus": campus,
        "faculty": faculty,
        "is_name_query": is_name_query,
        "campuses": await _list_campuses(db),
        "units": await _list_units(db),
        "experts": [],
        "experts_error": None,
        "exp_page": exp_page,
        "exp_max_page": _EXP_MAX_PAGE,
        "exp_has_next": False,
        "exp_page_url": exp_page_url,
        "publications": [],
        "publications_total": 0,
        "courses": [],
        "persons": [],
        "example_queries": _EXAMPLE_QUERIES,
        # Browse-mode (заполнится ниже если q пустой)
        "browse_results": [],
        "browse_total": 0,
        "browse_page": page,
        "browse_total_pages": 1,
        "browse_ordering": ordering,
        "browse_has_publications": has_publications,
        "browse_order_options": [(k, label) for k, (_, label) in _BROWSE_ORDER.items()],
        "browse_pagination_url": lambda _p: "/",
    }

    if not q:
        # === Browse mode: листаем всех преподов (бывший /persons) ===
        base = (
            select(Person, Campus.campus_name)
            .outerjoin(Campus, Person.campus_id == Campus.campus_id)
            .where(TEACHER_FILTER_SQL)
        )
        if campus_id:
            base = base.where(Person.campus_id == campus_id)
        if faculty:
            base = base.where(faculty_filter_sql(faculty))
        if has_publications == "true":
            base = base.where(Person.publications_total > 0)
        elif has_publications == "false":
            base = base.where(Person.publications_total == 0)

        total = (await db.execute(
            select(func.count()).select_from(base.order_by(None).subquery())
        )).scalar_one()
        ctx["browse_total"] = total
        ctx["browse_total_pages"] = max(1, (total + _BROWSE_PAGE_SIZE - 1) // _BROWSE_PAGE_SIZE)

        order_expr = _BROWSE_ORDER.get(ordering, _BROWSE_ORDER["-publications_total"])[0]
        base = base.order_by(order_expr, Person.person_id.asc())
        base = base.limit(_BROWSE_PAGE_SIZE).offset((page - 1) * _BROWSE_PAGE_SIZE)
        rows = (await db.execute(base)).all()
        stats = await _fetch_card_stats(db, [p.person_id for p, _ in rows])
        for person, c_name in rows:
            s = stats.get(person.person_id, {"courses": 0, "theses": 0})
            ctx["browse_results"].append({
                "person_id": person.person_id,
                "full_name": person.full_name,
                "avatar": person.avatar,
                "primary_unit": person.primary_unit,
                "extra_units": _extra_units(person),
                "publications_total": person.publications_total,
                "courses_count": s["courses"],
                "theses_count": s["theses"],
                "campus_name": c_name,
            })

        def browse_pagination_url(new_page: int) -> str:
            params: dict[str, Any] = {"page": new_page, "ordering": ordering}
            if campus_id: params["campus_id"] = campus_id
            if faculty: params["faculty"] = faculty
            if has_publications: params["has_publications"] = has_publications
            return "/?" + urlencode(params)
        ctx["browse_pagination_url"] = browse_pagination_url

    elif q and len(q) >= 2:
        like = f"%{q}%"

        # === Experts (vector) с пагинацией ===
        # Вектор бежим всегда — но в шаблоне его секцию покажем как
        # secondary («Возможно, по теме»), если ILIKE по фамилии что-то нашёл.
        # Так и lowercase-фамилии («паринов»), и «правильные» topic-запросы
        # обрабатываются единообразно.
        try:
            # Запрашиваем page_size+1 чтобы понять, есть ли следующая страница.
            exp_rows, top_pubs = await vector_search_persons(
                db, q,
                limit=_EXP_PAGE_SIZE + 1,
                offset=(exp_page - 1) * _EXP_PAGE_SIZE,
                campus_id=campus_id, primary_unit=faculty or None,
            )
            ctx["exp_has_next"] = (
                len(exp_rows) > _EXP_PAGE_SIZE and exp_page < _EXP_MAX_PAGE
            )
            exp_rows = exp_rows[:_EXP_PAGE_SIZE]
            exp_stats = await _fetch_card_stats(db, [p.person_id for p, _, _ in exp_rows])
            experts_list: list[dict[str, Any]] = []
            for person, c_name, score in exp_rows:
                tier = _score_tier(float(score))
                if tier is None:
                    continue  # шум — не показываем
                es = exp_stats.get(person.person_id, {"courses": 0, "theses": 0})
                experts_list.append({
                    "person_id": person.person_id,
                    "full_name": person.full_name,
                    "profile_url": person.profile_url,
                    "avatar": person.avatar,
                    "primary_unit": person.primary_unit,
                    "extra_units": _extra_units(person),
                    "campus_name": c_name,
                    "publications_total": person.publications_total,
                    "courses_count": es["courses"],
                    "theses_count": es["theses"],
                    "score": float(score),
                    "tier_label": tier[0],
                    "tier_class": tier[1],
                    "matched_topics": compute_matched_topics(
                        q, person.interests_extracted, person.interests,
                    ),
                    "top_publications": [
                        {"year": p.year, "title": p.title}
                        for p in top_pubs.get(person.person_id, [])
                    ],
                })
            ctx["experts"] = experts_list
        except Exception as e:
            # Postgres помечает транзакцию как aborted при любой SQL-ошибке;
            # без rollback все последующие запросы в этой же сессии упадут
            # с InFailedSQLTransactionError.
            await db.rollback()
            ctx["experts_error"] = str(e)

        # === Publications + Courses === (vector / ILIKE — fallback)
        try:
            pub_rows = await vector_search_publications(db, q, limit=5)
            pubs = [p for p, _ in pub_rows]
            authors_by_pub = await _attach_authors(db, pubs)
            ctx["publications"] = [
                {
                    **_pub_to_dict(p, authors_by_pub.get(p.id, [])),
                    "score": score,
                }
                for p, score in pub_rows
            ]
            ctx["publications_total"] = len(pub_rows)
        except Exception as e:
            # Fallback на ILIKE если NLP-стек недоступен (прод-Docker без torch)
            await db.rollback()
            ctx["publications_error"] = str(e)
            pubs = list((await db.execute(
                select(Publication).where(Publication.title.ilike(like))
                .order_by(Publication.year.desc().nullslast(), Publication.id.asc())
                .limit(5)
            )).scalars().all())
            authors_by_pub = await _attach_authors(db, pubs)
            ctx["publications"] = [
                {**_pub_to_dict(p, authors_by_pub.get(p.id, [])), "score": None}
                for p in pubs
            ]

        crs_q = (
            select(Course, Person)
            .join(Person, Person.person_id == Course.person_id)
            .where(Course.title.ilike(like))
            .order_by(Course.academic_year.desc().nullslast(), Course.id.desc())
            .limit(5)
        )
        for c, p in (await db.execute(crs_q)).all():
            ctx["courses"].append({
                "course_id": c.id,
                "title": c.title,
                "academic_year": c.academic_year,
                "level": c.level,
                "language": c.language,
                "person_id": p.person_id,
                "person_name": p.full_name,
                "person_unit": p.primary_unit,
            })

        # Persons (ILIKE по ФИО) — только преподаватели, как и vector
        # При name-режиме поднимаем лимит до 10 (юзер ищет конкретного человека —
        # помогаем найти даже одного из десятков «Ивановых»).
        per_limit = 10 if is_name_query else 5
        per_q = (
            select(Person, Campus.campus_name)
            .outerjoin(Campus, Person.campus_id == Campus.campus_id)
            .where(Person.full_name.ilike(like))
            .where(TEACHER_FILTER_SQL)
        )
        if campus_id:
            per_q = per_q.where(Person.campus_id == campus_id)
        if faculty:
            per_q = per_q.where(faculty_filter_sql(faculty))
        per_q = per_q.order_by(
            Person.publications_total.desc().nullslast(), Person.full_name.asc()
        ).limit(per_limit)
        per_rows = (await db.execute(per_q)).all()
        per_stats = await _fetch_card_stats(db, [p.person_id for p, _ in per_rows])
        for person, c_name in per_rows:
            ps = per_stats.get(person.person_id, {"courses": 0, "theses": 0})
            ctx["persons"].append({
                "person_id": person.person_id,
                "full_name": person.full_name,
                "avatar": person.avatar,
                "primary_unit": person.primary_unit,
                "extra_units": _extra_units(person),
                "publications_total": person.publications_total,
                "courses_count": ps["courses"],
                "theses_count": ps["theses"],
                "campus_name": c_name,
            })

    return templates.TemplateResponse(request, "home.html", ctx)


# === GET /persons → 301 на новую главную (browse-режим теперь там) ===

@router.get("/persons")
async def persons_list_redirect(
    q: str | None = None,
    campus_id: str | None = None,
    has_publications: str | None = None,
    ordering: str | None = None,
    page: int | None = None,
):
    params: dict[str, Any] = {}
    if q: params["q"] = q
    if campus_id: params["campus_id"] = campus_id
    if has_publications: params["has_publications"] = has_publications
    if ordering: params["ordering"] = ordering
    if page: params["page"] = page
    target = "/" + ("?" + urlencode(params) if params else "")
    return RedirectResponse(target, status_code=301)


# === GET /publications (list) ===

@router.get("/publications", response_class=HTMLResponse)
async def publications_list(
    request: Request,
    q: str | None = None,
    year_from: str | None = None,
    year_to: str | None = None,
    type: str | None = None,
    ordering: str = "-created_at",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
):
    def _to_int(s: str | None) -> int | None:
        if not s or not s.strip():
            return None
        try:
            return int(s.strip())
        except ValueError:
            return None

    year_from_i = _to_int(year_from)
    year_to_i = _to_int(year_to)
    type = (type or "").strip() or None
    # Если есть запрос — всегда vector mode (фильтры year/type применяются
    # внутри vector_search_publications). Без запроса — обычная пагинация
    # по списку с фильтрами. Чекбокс «семантический режим» убран — он
    # дублировал смысл и путал.
    is_semantic = bool(q) and len(q) >= 2

    _ORDER = {
        "year": Publication.year.asc(),
        "-year": Publication.year.desc(),
        "created_at": Publication.created_at.asc(),
        "-created_at": Publication.created_at.desc(),
    }

    error: str | None = None
    results: list[dict[str, Any]] = []
    total = 0
    total_pages = 1

    if is_semantic:
        # Vector mode: top-K по cosine, без пагинации; фильтры применяются.
        try:
            rows = await vector_search_publications(
                db, q,
                limit=page_size,
                year_from=year_from_i, year_to=year_to_i,
                pub_type=type,
            )
            pubs = [p for p, _ in rows]
            authors_by_pub = await _attach_authors(db, pubs)
            results = [
                {**_pub_to_dict(p, authors_by_pub.get(p.id, [])), "score": score}
                for p, score in rows
            ]
            total = len(results)
        except Exception as e:
            error = f"Семантический поиск недоступен: {e}. Используется обычный поиск."
            is_semantic = False  # fallback на ILIKE ниже

    if not is_semantic:
        base = select(Publication)
        filters = []
        if q:
            filters.append(Publication.title.ilike(f"%{q}%"))
        if year_from_i is not None:
            filters.append(Publication.year >= year_from_i)
        if year_to_i is not None:
            filters.append(Publication.year <= year_to_i)
        if type:
            filters.append(Publication.type == type)
        if filters:
            base = base.where(and_(*filters))

        total = (await db.execute(
            select(func.count()).select_from(base.order_by(None).subquery())
        )).scalar_one()
        total_pages = max(1, (total + page_size - 1) // page_size)

        order_expr = _ORDER.get(ordering, Publication.created_at.desc())
        base = base.order_by(order_expr, Publication.id.asc()).limit(page_size).offset((page - 1) * page_size)
        pubs = list((await db.execute(base)).scalars().all())
        authors_by_pub = await _attach_authors(db, pubs)
        results = [
            {**_pub_to_dict(p, authors_by_pub.get(p.id, [])), "score": None}
            for p in pubs
        ]

    def pagination_url(new_page: int) -> str:
        params: dict[str, Any] = {"page": new_page, "page_size": page_size, "ordering": ordering}
        if q: params["q"] = q
        if year_from_i is not None: params["year_from"] = year_from_i
        if year_to_i is not None: params["year_to"] = year_to_i
        if type: params["type"] = type
        return "/publications?" + urlencode(params)

    return templates.TemplateResponse(request, "publications.html", {
        "q": q, "year_from": year_from_i, "year_to": year_to_i,
        "type": type, "ordering": ordering,
        "is_semantic": is_semantic, "semantic_error": error,
        "page": page, "total": total, "total_pages": total_pages,
        "results": results, "pub_types": PUB_TYPES,
        "pagination_url": pagination_url,
    })


# === GET /persons/{id} (profile) ===

@router.get("/persons/{person_id}", response_class=HTMLResponse)
async def person_profile(
    request: Request,
    person_id: int,
    pub_page: int = Query(1, ge=1),
    course_page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_session),
):
    row = (await db.execute(
        select(Person, Campus.campus_name)
        .outerjoin(Campus, Person.campus_id == Campus.campus_id)
        .where(Person.person_id == person_id)
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")
    p, c_name = row

    # данные персоны
    person_data = {
        "person_id": p.person_id,
        "full_name": p.full_name,
        "avatar": p.avatar,
        "profile_url": p.profile_url,
        "primary_unit": p.primary_unit,
        "campus_name": c_name,
        "publications_total": p.publications_total,
        "languages": p.languages or [],
        "contacts": p.contacts or {},
        "positions": p.positions or [],
        "relations": p.relations or {},
        "education": p.education or {"degrees": [], "extra_education": []},
        "work_experience": p.work_experience or [],
        "awards": p.awards or [],
        "interests": p.interests or [],
        "grants": p.grants or [],
        "editorial_staff": p.editorial_staff or [],
        "conferences": p.conferences or [],
        "bio_notes": p.bio_notes or [],
        "research_ids": p.research_ids or {},
        "patents": p.patents or [],
    }

    PUB_PAGE_SIZE = 10
    pub_q = (
        select(Publication)
        .join(Authorship, Authorship.publication_id == Publication.id)
        .where(Authorship.person_id == person_id)
        .distinct()
    )
    pub_total = (await db.execute(
        select(func.count()).select_from(pub_q.order_by(None).subquery())
    )).scalar_one()
    pub_pages = max(1, (pub_total + PUB_PAGE_SIZE - 1) // PUB_PAGE_SIZE)
    pub_q = pub_q.order_by(Publication.year.desc().nullslast(), Publication.id.asc())
    pub_q = pub_q.limit(PUB_PAGE_SIZE).offset((pub_page - 1) * PUB_PAGE_SIZE)
    pubs = list((await db.execute(pub_q)).scalars().all())
    pubs_data = [_pub_to_dict(pub) for pub in pubs]

    # Курсы: грузим ВСЕ, группируем по title, потом пагинируем уже
    # дедуплицированный список. Один курс часто читается несколько
    # лет / на нескольких программах — в БД из-за этого 3-5 строк
    # на «Машинное обучение», на профиле это выглядело как спам.
    CRS_PAGE_SIZE = 20
    all_courses = (await db.execute(
        select(Course)
        .where(Course.person_id == person_id)
        .order_by(Course.academic_year.desc().nullslast(), Course.id.desc())
    )).scalars().all()

    courses_by_title: dict[str, dict[str, Any]] = {}
    for c in all_courses:
        title = (c.title or "").strip()
        if not title:
            continue
        bucket = courses_by_title.setdefault(title, {
            "title": title,
            "years": [],
            "levels": set(),
            "languages": set(),
        })
        if c.academic_year and c.academic_year not in bucket["years"]:
            bucket["years"].append(c.academic_year)
        if c.level:
            bucket["levels"].add(c.level)
        if c.language:
            bucket["languages"].add(c.language)

    course_total = len(courses_by_title)
    course_pages = max(1, (course_total + CRS_PAGE_SIZE - 1) // CRS_PAGE_SIZE)

    # Сортировка по самому свежему academic_year группы (DESC).
    def _latest_year(item: dict[str, Any]) -> str:
        return max(item["years"], default="")
    deduped = sorted(courses_by_title.values(), key=_latest_year, reverse=True)
    start = (course_page - 1) * CRS_PAGE_SIZE
    courses = [
        {
            "title": item["title"],
            "years": item["years"],
            "levels": sorted(item["levels"]),
            "languages": sorted(item["languages"]),
            "times_taught": len(item["years"]),
        }
        for item in deduped[start:start + CRS_PAGE_SIZE]
    ]

    return templates.TemplateResponse(request, "profile.html", {
        "person": person_data,
        "pubs": pubs_data, "pub_total": pub_total, "pub_page": pub_page, "pub_pages": pub_pages,
        "courses": courses, "course_total": course_total, "course_page": course_page, "course_pages": course_pages,
    })


# === Админ-вкладка скрейпера ===
#
# UI-роуты НЕ проверяют X-Admin-Token (мы не можем установить заголовок
# из HTML-формы). Для прод-деплоя закрывайте /admin через reverse-proxy
# (basic-auth, IP-allowlist и т.п.) либо просто не открывайте порт UI наружу.

ADMIN_LETTERS = list("АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯ")
ADMIN_RUNNING_STATUSES = {
    ScrapeStatus.queued.value,
    ScrapeStatus.running.value,
    ScrapeStatus.cancelling.value,
}


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    _: str = Depends(require_admin_basic),
    db: AsyncSession = Depends(get_session),
):
    from app.scheduler import get_schedule_info
    # Список последних 20 джобов
    rows = (await db.execute(
        select(ScrapeJob).order_by(ScrapeJob.started_at.desc()).limit(20)
    )).scalars().all()
    return templates.TemplateResponse(request, "admin.html", {
        "campuses": await _list_campuses(db),
        "letters": ADMIN_LETTERS,
        "jobs": rows,
        "running_statuses": ADMIN_RUNNING_STATUSES,
        "schedule_info": get_schedule_info(),
    })


@router.post("/admin/scrape", response_class=HTMLResponse)
async def admin_scrape_start(
    background: BackgroundTasks,
    campus_ids: list[str] | None = Form(default=None),
    letters: str = Form(default=""),
    limit: str = Form(default=""),
    _: str = Depends(require_admin_basic),
    db: AsyncSession = Depends(get_session),
):
    # Параметры из формы — нормализуем
    campus_ids_clean = [c for c in (campus_ids or []) if c.strip()] or None
    letters_clean = [c.strip() for c in letters.split(",") if c.strip()] or None
    try:
        limit_i: int | None = int(limit) if limit.strip() else None
    except ValueError:
        limit_i = None

    job_id = str(uuid.uuid4())
    job = ScrapeJob(
        job_id=job_id,
        status=ScrapeStatus.queued.value,
        limit_count=limit_i,
        campus_id=",".join(campus_ids_clean) if campus_ids_clean else None,
        processed=0,
        total=None,
        started_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()

    background.add_task(
        crawl_and_ingest,
        limit_i, campus_ids_clean, letters_clean, job_id, AsyncSessionLocal,
    )
    # 303 See Other — после POST уводит на GET страницы джоба
    return RedirectResponse(f"/admin/scrape/{job_id}", status_code=303)


@router.get("/admin/scrape/{job_id}", response_class=HTMLResponse)
async def admin_job_view(
    request: Request, job_id: str,
    _: str = Depends(require_admin_basic),
    db: AsyncSession = Depends(get_session),
):
    job = await db.get(ScrapeJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return templates.TemplateResponse(request, "admin_job.html", {
        "job": job,
        "is_running": job.status in ADMIN_RUNNING_STATUSES,
    })


@router.post("/admin/scrape/{job_id}/cancel", response_class=HTMLResponse)
async def admin_job_cancel(
    job_id: str,
    _: str = Depends(require_admin_basic),
    db: AsyncSession = Depends(get_session),
):
    job = await db.get(ScrapeJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in (ScrapeStatus.queued.value, ScrapeStatus.running.value):
        job.status = ScrapeStatus.cancelling.value
        await db.commit()
    return RedirectResponse(f"/admin/scrape/{job_id}", status_code=303)
