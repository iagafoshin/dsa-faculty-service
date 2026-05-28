"""Лемматизация русских тегов в именительный падеж — для презентабельности.

KeyBERT выдаёт фразы как они встретились в тексте: «эволюционной разработки
программного обеспечения». Для UI это выглядит коряво. Прогоняем фразу
через pymorphy3 — каждое существительное в (nomn, sing), каждое
прилагательное/причастие согласуем с ближайшим существительным справа
(одинаковый род и число) — получаем «эволюционная разработка программного
обеспечения».

Минимум зависимостей: только pymorphy3 (уже в requirements).
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import pymorphy3

_morph: Any = None

_NOUN = "NOUN"
_ADJ_LIKE = {"ADJF", "PRTF"}  # ADJS/ADVB не трогаем — у них нет падежа в нашем смысле
_TOKEN_RE = re.compile(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*|[A-Za-z0-9]+|[^\s]")
_CYR_RE = re.compile(r"[А-Яа-яЁё]")


def _get_morph():
    global _morph
    if _morph is None:
        _morph = pymorphy3.MorphAnalyzer()
    return _morph


@lru_cache(maxsize=20000)
def _parse_token(token: str) -> Any:
    """Лучший parse для слова. Cached — KeyBERT повторяет токены."""
    parses = _get_morph().parse(token)
    return parses[0] if parses else None


def _inflect_noun(token: str) -> str:
    """Существительное → (nomn, sing). Если pymorphy не уверен — оставляем."""
    p = _parse_token(token)
    if p is None or p.tag.POS != _NOUN:
        return token
    try:
        # Pluralia tantum (например, «нейросети» = pl. only): не пытаемся sing.
        target = {"nomn"}
        if "Pltm" not in p.tag:
            target.add("sing")
        infl = p.inflect(target)
        return infl.word if infl else token
    except (ValueError, AttributeError):
        return token


def _inflect_adj_to_match(adj_token: str, noun_parse: Any) -> str:
    """Прилагательное → (nomn) с согласованием рода и числа по существительному."""
    p = _parse_token(adj_token)
    if p is None or p.tag.POS not in _ADJ_LIKE:
        return adj_token
    target = {"nomn"}
    if noun_parse is not None:
        # gender только для sing — у plural рода нет
        is_plur = "plur" in noun_parse.tag or "Pltm" in noun_parse.tag
        if is_plur:
            target.add("plur")
        else:
            target.add("sing")
            gender = noun_parse.tag.gender
            if gender:
                target.add(gender)
    else:
        target.add("sing")
    try:
        infl = p.inflect(target)
        return infl.word if infl else adj_token
    except (ValueError, AttributeError):
        return adj_token


def _normalize_run(tokens: list[str]) -> list[str]:
    """Лемматизирует только головную часть фразы — до первого существительного
    включительно — в именительный падеж. Всё после неё оставляем как есть
    (это родительный комплимент: «теория **игр**», «методы **оптимизации**»,
    «обучение с **подкреплением**» — менять там падежи разрушает смысл).

    Слева до головного существительного допускаются прилагательные/причастия
    (согласуем по роду/числу) и наречия с дефисом («процедурно-параметрическая»).
    """
    head_idx: int | None = None
    head_parse: Any = None
    for i, tok in enumerate(tokens):
        # Дефисные — смотрим последнюю часть как «реальную» POS
        if "-" in tok:
            last_part = tok.rsplit("-", 1)[-1]
            p = _parse_token(last_part)
        else:
            p = _parse_token(tok)
        if p is not None and p.tag.POS == _NOUN:
            head_idx = i
            head_parse = p
            break

    if head_idx is None:
        # Существительного в фразе нет — лемматизация бессмысленна.
        return list(tokens)

    # Лемматизируем голову.
    head_token = tokens[head_idx]
    head_lemma = _inflect_noun(head_token) if "-" not in head_token else "-".join(
        _inflect_noun(p) if (parse := _parse_token(p)) and parse.tag.POS == _NOUN else p
        for p in head_token.split("-")
    )
    head_parse_nomn = _parse_token(head_lemma)

    # Согласуем токены ПЕРЕД головой (прил./причастия). Дефисные — последнюю часть.
    prefix: list[str] = []
    for tok in tokens[:head_idx]:
        if "-" in tok:
            parts = tok.split("-")
            last_p = _parse_token(parts[-1])
            if last_p is not None and last_p.tag.POS in _ADJ_LIKE:
                parts[-1] = _inflect_adj_to_match(parts[-1], head_parse_nomn)
            prefix.append("-".join(parts))
        else:
            p = _parse_token(tok)
            if p is not None and p.tag.POS in _ADJ_LIKE:
                prefix.append(_inflect_adj_to_match(tok, head_parse_nomn))
            else:
                # Неизвестная часть речи / предлог / наречие — оставляем как есть.
                prefix.append(tok)

    suffix = list(tokens[head_idx + 1:])
    return prefix + [head_lemma] + suffix


def normalize_phrase(phrase: str) -> str:
    """Приводит русскую часть фразы к (им.п., согласованной). Английские
    и смешанные токены не трогаем.
    """
    tokens = _TOKEN_RE.findall(phrase)
    # Группируем подряд идущие русские/нерусские токены, чтобы _normalize_run
    # работал только на однородных русских участках.
    out: list[str] = []
    buf: list[str] = []
    buf_is_ru: bool | None = None
    for tok in tokens:
        is_ru = bool(_CYR_RE.search(tok))
        if buf_is_ru is None:
            buf_is_ru = is_ru
        if is_ru == buf_is_ru:
            buf.append(tok)
        else:
            out.extend(_normalize_run(buf) if buf_is_ru else buf)
            buf = [tok]
            buf_is_ru = is_ru
    if buf:
        out.extend(_normalize_run(buf) if buf_is_ru else buf)
    return " ".join(out)


__all__ = ["normalize_phrase"]
