"""NER + ключевые фразы из академического текста.

Архитектура: spaCy (`ru_core_news_lg` + `en_core_web_sm`) даёт NER-сущности
и noun-chunks, KeyBERT — ключевые фразы с MMR-разнообразием. Списки
объединяются, нормализуются, дедуплицируются по подстроке, фильтруются
по стоп-словам — финальный топ возвращается по KeyBERT-скору.

Все модели грузятся лениво — первый вызов `extract_topics` пойдёт долго,
дальше быстро.
"""
from __future__ import annotations

import logging
import re
import string
from typing import Any

import spacy
import torch
from keybert import KeyBERT
from sentence_transformers import SentenceTransformer

from app.nlp.lemmatize import normalize_phrase
from app.nlp.stopwords import EN_STOPWORDS, JUNK_PHRASES, ORG_INDICATORS, RU_STOPWORDS

logger = logging.getLogger(__name__)

EMBED_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# Типы сущностей spaCy, которые считаем потенциальными тегами.
# ORG специально исключён: названия организаций — это не профессиональные
# интересы, а контекст («Институт когнитивных нейронаук» ≠ когнитивные
# нейронауки). Их собираем отдельно в reject-набор (см. _SPACY_REJECT_TYPES).
_SPACY_ENTITY_TYPES = {"PRODUCT", "WORK_OF_ART", "LAW", "EVENT", "NORP"}

# Типы сущностей spaCy, которые отсекаем — если КandyBERT выдал фразу,
# текстуально совпадающую с одной из этих сущностей, выбрасываем.
# GPE — англ. геополит. сущности (en_core_web_sm), LOC — её русский аналог
# (ru_core_news_lg).
_SPACY_REJECT_TYPES = {"ORG", "GPE", "LOC", "DATE"}

# Лениво-инициализируемые синглтоны.
_device: str | None = None
_nlp_ru: Any = None
_nlp_en: Any = None
_st_model: SentenceTransformer | None = None
_keybert: KeyBERT | None = None


def get_device() -> str:
    global _device
    if _device is None:
        if torch.backends.mps.is_available():
            _device = "mps"
        elif torch.cuda.is_available():
            _device = "cuda"
        else:
            _device = "cpu"
        logger.info("NLP device: %s", _device)
    return _device


def _get_spacy_ru():
    global _nlp_ru
    if _nlp_ru is None:
        _nlp_ru = spacy.load("ru_core_news_lg")
    return _nlp_ru


def _get_spacy_en():
    global _nlp_en
    if _nlp_en is None:
        _nlp_en = spacy.load("en_core_web_sm")
    return _nlp_en


def get_sentence_transformer() -> SentenceTransformer:
    """Общий загрузчик SentenceTransformer — используется и KeyBERT'ом, и
    отдельным embedder'ом (шаг 5). Модель кэшируется в HF на диске."""
    global _st_model
    if _st_model is None:
        _st_model = SentenceTransformer(EMBED_MODEL_NAME, device=get_device())
    return _st_model


def _get_keybert() -> KeyBERT:
    global _keybert
    if _keybert is None:
        _keybert = KeyBERT(model=get_sentence_transformer())
    return _keybert


# === Языковое детектирование ===

_CYR_RE = re.compile(r"[А-Яа-яЁё]")
_LAT_RE = re.compile(r"[A-Za-z]")


def detect_lang(text: str) -> str:
    """Простая эвристика по соотношению кириллицы/латиницы."""
    cyr = len(_CYR_RE.findall(text))
    lat = len(_LAT_RE.findall(text))
    total = cyr + lat
    if total == 0:
        return "ru"
    cyr_ratio = cyr / total
    if cyr_ratio > 0.8:
        return "ru"
    if cyr_ratio < 0.2:
        return "en"
    return "mixed"


# === Нормализация и фильтрация кандидатов ===

# Дополнительные знаки к string.punctuation: типографские кавычки/тире/буллит.
_STRIP_CHARS = string.punctuation + "«»“”‘’„–—•·"
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(tag: str) -> str:
    tag = tag.lower().strip()
    tag = tag.strip(_STRIP_CHARS)
    # ё → е для устойчивого матчинга со стоп-фразами (pymorphy склонен
    # возвращать «приглашённый», а HSE в большинстве мест пишет «е»).
    tag = tag.replace("ё", "е")
    tag = _WHITESPACE_RE.sub(" ", tag).strip()
    return tag


def _dedupe_substrings(tags: list[str]) -> list[str]:
    """Если есть «машинное обучение» и «обучение» — оставляем только длинный."""
    sorted_tags = sorted(set(tags), key=lambda t: (-len(t), t))
    kept: list[str] = []
    for t in sorted_tags:
        if any(t != longer and t in longer for longer in kept):
            continue
        kept.append(t)
    return kept


def _collect_spacy_candidates(doc) -> tuple[list[str], list[str]]:
    """Возвращает `(candidates, rejects)`: первое — кандидаты в теги (entities
    нужных типов + noun_chunks), второе — тексты ORG/GPE/LOC/DATE сущностей
    для последующего отсева в `apply_filters`.
    """
    candidates: list[str] = []
    rejects: list[str] = []
    for ent in doc.ents:
        if ent.label_ in _SPACY_ENTITY_TYPES:
            candidates.append(ent.text)
        elif ent.label_ in _SPACY_REJECT_TYPES:
            rejects.append(ent.text)
    try:
        for nc in doc.noun_chunks:
            if 1 <= len(nc.text.split()) <= 4:
                candidates.append(nc.text)
    except NotImplementedError:
        # ru_core_news_lg не реализует noun_chunks — для русского
        # роль n-грамм играет KeyBERT.
        pass
    return candidates, rejects


# === Post-processing фильтры (v2) ===

# Служебные предлоги/частицы, с которых тег начинаться не должен.
_SERVICE_PREFIXES: set[str] = {
    "в", "с", "на", "по", "при", "для", "из", "к", "у", "от", "со",
    "об", "о", "под", "над", "до", "после", "за", "из-за",
    "г", "гг", "ходе", "том", "тех", "то", "та", "те",
    "the", "of", "in", "on", "at", "by", "to", "for", "from",
}

_NUMERIC_CHARS = set("0123456789 .,–—-/")
_GG_RE = re.compile(r"\bгг?\.?\b", re.IGNORECASE)
# 4-значный год (1900-2099) в начале тега. Такие теги почти всегда мусор
# вида «2020 году научно», «2024 центр пространственного» — обрезки
# биографий или дат событий.
_LEADING_YEAR_RE = re.compile(r"^(?:19|20)\d{2}\b")

# «Стаж N лет/год/года/месяцев» — десятки одинаковых записей в HSE-биографиях.
_TENURE_RE = re.compile(r"^стаж\s*\d", re.IGNORECASE)

# Теги, начинающиеся с «интересы …» — это сам заголовок секции,
# KeyBERT тянет его как ключевую фразу.
_INTERESTS_PREFIX_RE = re.compile(r"^интерес[ыа]?\s+", re.IGNORECASE)


def _contains_org_indicator(tag: str) -> bool:
    """Substring-проверка против ORG_INDICATORS. Для очень коротких токенов
    (< 4 симв) — word-boundary (иначе «рана» содержит «ран»). Для 4+ симв —
    обычная подстрока, ловит все падежи: «школ» → «школа/школу/школы»."""
    for ind in ORG_INDICATORS:
        if len(ind) < 4:
            if re.search(rf"\b{re.escape(ind)}\b", tag):
                return True
        elif ind in tag:
            return True
    return False


def _numeric_ratio(tag: str) -> float:
    if not tag:
        return 0.0
    n = sum(1 for c in tag if c in _NUMERIC_CHARS)
    for m in _GG_RE.finditer(tag):
        n += len(m.group())
    return n / len(tag)


def apply_filters(
    tags: list[str],
    person_name: str = "",
    ner_rejects: set[str] | None = None,
) -> list[str]:
    """Прогоняет кандидатов через 9 правил v2-итерации.

    Порядок проверок выбран так, чтобы максимально дешёвые/частые отсевы шли
    первыми (стоп-имя, ORG-маркеры), дедупликация по подстроке — последней.
    """
    stopwords = RU_STOPWORDS | EN_STOPWORDS

    name_tokens: set[str] = set()
    if person_name:
        for word in re.split(r"\s+", person_name.lower()):
            cleaned = word.strip(_STRIP_CHARS)
            if len(cleaned) > 3:
                name_tokens.add(cleaned)

    rejects = {r.lower() for r in (ner_rejects or set())}

    keep: list[str] = []
    for raw_tag in tags:
        tag = (raw_tag or "").strip()
        if not tag:
            continue

        # Лемматизация в им.п. — делаем РАНЬШЕ всех фильтров, чтобы стоп-слова
        # и JUNK_PHRASES матчили нормализованные формы («стаж года» → «стаж год»
        # → стоп; «эволюционной разработки» → «эволюционная разработка»).
        tag = normalize_phrase(tag)
        # _normalize ещё раз: подровнять пробелы, заменить ё→е, убрать
        # хвостовые знаки (нормализация фразы могла оставить «- » вокруг дефиса).
        tag = _normalize(tag)
        # Схлопнуть «слово - слово» обратно в «слово-слово» (после лемматизации
        # pymorphy3 ставит пробелы вокруг дефиса).
        tag = re.sub(r"\s*-\s*", "-", tag)

        # Шаблоны-паразиты по регэкспам (более прицельные, чем JUNK_PHRASES)
        if _TENURE_RE.match(tag):
            continue
        if _INTERESTS_PREFIX_RE.match(tag):
            # Берём то, что после «интересы » — это и есть фактический интерес.
            tag = _INTERESTS_PREFIX_RE.sub("", tag, count=1).strip()
            if not tag:
                continue

        # (2) имя/фамилия персоны
        if any(nt in tag for nt in name_tokens):
            continue

        # (3) маркеры организаций — высший приоритет
        if _contains_org_indicator(tag):
            continue

        # (4) тексты ORG/GPE/LOC/DATE из spaCy
        if any(rej and rej in tag for rej in rejects):
            continue

        tokens = tag.split()
        if not tokens:
            continue

        # (5) служебный префикс или слишком короткое первое слово
        first = tokens[0]
        if len(first) < 3 or first in _SERVICE_PREFIXES:
            continue

        # (5b) первый токен — 4-значный год (тег вроде «2020 году научно»)
        if _LEADING_YEAR_RE.match(tag):
            continue

        # (6) доля цифр/служебных знаков >= 40%
        if _numeric_ratio(tag) >= 0.4:
            continue

        # (7) шаблоны-паразиты
        if any(j in tag for j in JUNK_PHRASES):
            continue

        # (9) min длина 4 + хотя бы одно содержательное слово ≥4 симв
        if len(tag) < 4:
            continue
        if not any(len(t) >= 4 for t in tokens):
            continue

        # Существующая проверка стоп-слов (одиночные мусорные слова
        # или фразы, целиком из стоп-слов).
        if tag in stopwords:
            continue
        if all(t in stopwords for t in tokens):
            continue

        keep.append(tag)

    # (8) дедуп по подстроке — длинный поглощает короткий. После лемматизации
    # это особенно важно: «машинное обучение» и «обучение машинное» сольются.
    return _dedupe_substrings(keep)


def _combine_and_rank(
    spacy_tags: list[str],
    keybert_pairs: list[tuple[str, float]],
    max_tags: int,
    person_name: str = "",
    ner_rejects: set[str] | None = None,
) -> list[str]:
    """Объединяет кандидатов, прогоняет через v2-фильтры, возвращает топ
    по итоговому скору.

    spaCy-кандидатам даём базовый скор 0.6 (NER приоритетнее низкорейтинговых
    фраз KeyBERT), KeyBERT — фактический скор. При совпадении берём max.
    """
    candidates: dict[str, float] = {}

    for tag in spacy_tags:
        norm = _normalize(tag)
        if not norm:
            continue
        candidates[norm] = max(candidates.get(norm, 0.0), 0.6)

    for tag, score in keybert_pairs:
        norm = _normalize(tag)
        if not norm:
            continue
        candidates[norm] = max(candidates.get(norm, 0.0), float(score))

    kept = apply_filters(list(candidates.keys()), person_name=person_name, ner_rejects=ner_rejects)
    kept.sort(key=lambda t: -candidates.get(t, 0.0))
    return kept[:max_tags]


# === Публичный API ===

def _keybert_keywords(text: str, max_tags: int) -> list[tuple[str, float]]:
    try:
        return _get_keybert().extract_keywords(
            text,
            keyphrase_ngram_range=(1, 3),
            top_n=max_tags * 2,
            use_mmr=True,
            diversity=0.5,
        )
    except Exception:
        logger.warning("KeyBERT extract_keywords failed", exc_info=True)
        return []


def extract_topics(
    text: str,
    max_tags: int = 15,
    person_name: str = "",
) -> list[str]:
    """Извлекает до `max_tags` тегов из одного текста.

    `person_name` пробрасывается в фильтр имени-персоны (см. apply_filters).
    """
    if not text or len(text) < 50:
        return []
    lang = detect_lang(text)

    spacy_tags: list[str] = []
    ner_rejects: set[str] = set()
    if lang in ("ru", "mixed"):
        c, r = _collect_spacy_candidates(_get_spacy_ru()(text))
        spacy_tags.extend(c)
        ner_rejects.update(s.lower() for s in r)
    if lang in ("en", "mixed"):
        c, r = _collect_spacy_candidates(_get_spacy_en()(text))
        spacy_tags.extend(c)
        ner_rejects.update(s.lower() for s in r)

    keybert_pairs = _keybert_keywords(text, max_tags)
    return _combine_and_rank(
        spacy_tags, keybert_pairs, max_tags,
        person_name=person_name, ner_rejects=ner_rejects,
    )


def extract_topics_batch(
    texts: list[str],
    max_tags: int = 15,
    person_names: list[str] | None = None,
) -> list[list[str]]:
    """Батчевая версия. SpaCy через `nlp.pipe`, KeyBERT по очереди.

    `person_names` (если задан) — список той же длины, что и `texts`;
    каждое имя пробрасывается в свой apply_filters.
    """
    if not texts:
        return []
    if person_names is not None and len(person_names) != len(texts):
        raise ValueError("person_names length must match texts length")

    langs = [detect_lang(t) for t in texts]
    spacy_per_text: list[list[str]] = [[] for _ in texts]
    rejects_per_text: list[set[str]] = [set() for _ in texts]

    def _run_pipe(nlp, indices: list[int]) -> None:
        if not indices:
            return
        chunks = [texts[i] for i in indices]
        for idx, doc in zip(indices, nlp.pipe(chunks)):
            c, r = _collect_spacy_candidates(doc)
            spacy_per_text[idx].extend(c)
            rejects_per_text[idx].update(s.lower() for s in r)

    _run_pipe(_get_spacy_ru(), [i for i, l in enumerate(langs) if l in ("ru", "mixed")])
    _run_pipe(_get_spacy_en(), [i for i, l in enumerate(langs) if l in ("en", "mixed")])

    out: list[list[str]] = []
    for i, text in enumerate(texts):
        if not text or len(text) < 50:
            out.append([])
            continue
        kb_pairs = _keybert_keywords(text, max_tags)
        pname = person_names[i] if person_names else ""
        out.append(_combine_and_rank(
            spacy_per_text[i], kb_pairs, max_tags,
            person_name=pname, ner_rejects=rejects_per_text[i],
        ))
    return out
