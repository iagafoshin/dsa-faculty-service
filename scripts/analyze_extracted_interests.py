"""Анализ качества `Person.interests_extracted`.

Считает агрегаты (сколько тегов на персону, частые/редкие, подозрительные
паттерны) + выгружает стратифицированную выборку из 100 персон
с тегами для ручной оценки.

Output → stdout (перенаправь в файл при необходимости).

Запуск:
    DATABASE_URL=postgresql+asyncpg://postgres:CHANGE_ME@localhost:5433/hse_faculty \\
        python scripts/analyze_extracted_interests.py
"""
from __future__ import annotations

import asyncio
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.database import AsyncSessionLocal  # noqa: E402
from app.models import Person  # noqa: E402

OUTPUT = Path(__file__).resolve().parent.parent / "notes" / "extracted_interests_sample.md"


def _is_year_prefix(tag: str) -> bool:
    return bool(re.match(r"^(19|20)\d{2}\b", tag))


def _has_any_digit(tag: str) -> bool:
    return bool(re.search(r"\d", tag))


def _avg_word_len(tag: str) -> float:
    tokens = tag.split()
    if not tokens:
        return 0.0
    return sum(len(t) for t in tokens) / len(tokens)


async def main() -> None:
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(Person).where(Person.embedding.is_not(None))
        )).scalars().all()

    persons = list(rows)
    total_persons = len(persons)
    all_tags: list[str] = []
    for p in persons:
        all_tags.extend(p.interests_extracted or [])

    total_tags = len(all_tags)
    unique_tags = len(set(all_tags))
    avg_per_person = total_tags / total_persons if total_persons else 0

    # Распределение количества тегов на персону
    per_person_counts = Counter(len(p.interests_extracted) for p in persons)

    # Подозрительные паттерны
    year_starts = sum(1 for t in all_tags if _is_year_prefix(t))
    with_any_digit = sum(1 for t in all_tags if _has_any_digit(t))
    short_words = sum(1 for t in all_tags if _avg_word_len(t) < 4.5)
    one_word = sum(1 for t in all_tags if len(t.split()) == 1)
    three_word = sum(1 for t in all_tags if len(t.split()) == 3)

    # Топ-частых
    counter = Counter(all_tags)
    top_50 = counter.most_common(50)
    rare = sum(1 for _, c in counter.items() if c == 1)

    # Стратифицированный сэмпл 100 персон
    random.seed(42)
    rich = [p for p in persons if (p.publications_total or 0) > 30]
    medium = [p for p in persons if 5 <= (p.publications_total or 0) <= 30]
    thin = [p for p in persons if (p.publications_total or 0) < 5]
    n_rich = min(35, len(rich))
    n_medium = min(35, len(medium))
    n_thin = min(30, len(thin))
    sample = (
        random.sample(rich, n_rich)
        + random.sample(medium, n_medium)
        + random.sample(thin, n_thin)
    )
    sample.sort(key=lambda p: p.full_name)

    lines: list[str] = []
    lines.append("# Качество extracted_interests — анализ + выборка 100 персон")
    lines.append("")
    lines.append("Автогенерируется `scripts/analyze_extracted_interests.py`.")
    lines.append("")
    lines.append("## Агрегаты по всем enriched персонам")
    lines.append("")
    lines.append(f"- Всего enriched персон: **{total_persons}**")
    lines.append(f"- Всего тегов: **{total_tags}**")
    lines.append(f"- Уникальных тегов: **{unique_tags}** ({unique_tags/total_tags*100:.1f}% от всех)")
    lines.append(f"- Среднее тегов на персону: **{avg_per_person:.1f}**")
    lines.append(f"- «Одноразовых» тегов (встречаются 1 раз): {rare} ({rare/unique_tags*100:.1f}% от уникальных)")
    lines.append("")
    lines.append("### Распределение тегов на персону")
    lines.append("")
    lines.append("| Количество тегов | Сколько персон |")
    lines.append("|---|---|")
    for n in sorted(per_person_counts):
        lines.append(f"| {n} | {per_person_counts[n]} |")
    lines.append("")
    lines.append("### Подозрительные паттерны (потенциальный «мусор»)")
    lines.append("")
    lines.append(f"- Тегов, начинающихся с года (`2020 ...`, `2024 ...`): **{year_starts}** ({year_starts/total_tags*100:.1f}%)")
    lines.append(f"- Тегов с любой цифрой внутри: **{with_any_digit}** ({with_any_digit/total_tags*100:.1f}%)")
    lines.append(f"- Тегов со средней длиной слова <4.5 симв (намёк на служебные слова): {short_words} ({short_words/total_tags*100:.1f}%)")
    lines.append(f"- Однословных тегов: {one_word} ({one_word/total_tags*100:.1f}%)")
    lines.append(f"- 3-словных тегов: {three_word} ({three_word/total_tags*100:.1f}%)")
    lines.append("")
    lines.append("### Top-50 самых частых тегов")
    lines.append("")
    lines.append("| # | freq | тег |")
    lines.append("|---|---|---|")
    for i, (tag, freq) in enumerate(top_50, 1):
        # экранируем pipe в теге
        safe = tag.replace("|", "\\|")
        lines.append(f"| {i} | {freq} | {safe} |")
    lines.append("")
    lines.append(f"## Выборка {len(sample)} персон (стратифицированно по числу публикаций)")
    lines.append("")
    lines.append(f"35 «богатых» (>30 публикаций), 35 средних (5–30), 30 тонких (<5).")
    lines.append("Все enriched — пропускающие фильтр контекста ≥500 символов.")
    lines.append("Сэмпл воспроизводимый (`random.seed(42)`).")
    lines.append("")

    for p in sample:
        lines.append(f"### {p.full_name}")
        lines.append("")
        lines.append(f"- Подразделение: {p.primary_unit or '—'}")
        lines.append(f"- Публикаций: {p.publications_total or 0}")
        tags = p.interests_extracted or []
        lines.append(f"- Тегов ({len(tags)}):")
        if tags:
            for tag in tags:
                lines.append(f"  - {tag}")
        else:
            lines.append("  - (пусто)")
        lines.append("")

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"saved → {OUTPUT}")
    print(f"persons: {total_persons}, tags: {total_tags}, unique: {unique_tags}, sample: {len(sample)}")


if __name__ == "__main__":
    asyncio.run(main())
