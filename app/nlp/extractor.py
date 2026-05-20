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

from app.nlp.stopwords import EN_STOPWORDS, RU_STOPWORDS

logger = logging.getLogger(__name__)

EMBED_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# Типы сущностей spaCy, которые считаем потенциальными тегами.
_SPACY_ENTITY_TYPES = {"ORG", "PRODUCT", "WORK_OF_ART", "LAW", "EVENT", "NORP"}

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
    tag = _WHITESPACE_RE.sub(" ", tag).strip()
    return tag


def _is_garbage(tag: str, stopwords: set[str]) -> bool:
    if len(tag) < 3:
        return True
    if tag.isdigit():
        return True
    if tag in stopwords:
        return True
    tokens = tag.split()
    if tokens and all(t in stopwords for t in tokens):
        return True
    return False


def _dedupe_substrings(tags: list[str]) -> list[str]:
    """Если есть «машинное обучение» и «обучение» — оставляем только длинный."""
    sorted_tags = sorted(set(tags), key=lambda t: (-len(t), t))
    kept: list[str] = []
    for t in sorted_tags:
        if any(t != longer and t in longer for longer in kept):
            continue
        kept.append(t)
    return kept


def _collect_spacy_candidates(doc) -> list[str]:
    out: list[str] = []
    for ent in doc.ents:
        if ent.label_ in _SPACY_ENTITY_TYPES:
            out.append(ent.text)
    for nc in doc.noun_chunks:
        if 1 <= len(nc.text.split()) <= 4:
            out.append(nc.text)
    return out


def _combine_and_rank(
    spacy_tags: list[str],
    keybert_pairs: list[tuple[str, float]],
    max_tags: int,
) -> list[str]:
    """Объединяет кандидатов, фильтрует, возвращает топ по итоговому скору.

    spaCy-кандидатам даём базовый скор 0.6 (NER приоритетнее низкорейтинговых
    фраз KeyBERT), KeyBERT — фактический скор. При совпадении берём max.
    """
    stopwords = RU_STOPWORDS | EN_STOPWORDS
    candidates: dict[str, float] = {}

    for tag in spacy_tags:
        norm = _normalize(tag)
        if not norm or _is_garbage(norm, stopwords):
            continue
        candidates[norm] = max(candidates.get(norm, 0.0), 0.6)

    for tag, score in keybert_pairs:
        norm = _normalize(tag)
        if not norm or _is_garbage(norm, stopwords):
            continue
        candidates[norm] = max(candidates.get(norm, 0.0), float(score))

    kept = _dedupe_substrings(list(candidates.keys()))
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


def extract_topics(text: str, max_tags: int = 15) -> list[str]:
    """Извлекает до `max_tags` тегов из одного текста."""
    if not text or len(text) < 50:
        return []
    lang = detect_lang(text)

    spacy_tags: list[str] = []
    if lang in ("ru", "mixed"):
        spacy_tags.extend(_collect_spacy_candidates(_get_spacy_ru()(text)))
    if lang in ("en", "mixed"):
        spacy_tags.extend(_collect_spacy_candidates(_get_spacy_en()(text)))

    keybert_pairs = _keybert_keywords(text, max_tags)
    return _combine_and_rank(spacy_tags, keybert_pairs, max_tags)


def extract_topics_batch(texts: list[str], max_tags: int = 15) -> list[list[str]]:
    """Батчевая версия. SpaCy через `nlp.pipe`, KeyBERT по очереди
    (у него нет true-batch API)."""
    if not texts:
        return []

    langs = [detect_lang(t) for t in texts]
    spacy_per_text: list[list[str]] = [[] for _ in texts]

    def _run_pipe(nlp, indices: list[int]) -> None:
        if not indices:
            return
        chunks = [texts[i] for i in indices]
        for idx, doc in zip(indices, nlp.pipe(chunks)):
            spacy_per_text[idx].extend(_collect_spacy_candidates(doc))

    _run_pipe(_get_spacy_ru(), [i for i, l in enumerate(langs) if l in ("ru", "mixed")])
    _run_pipe(_get_spacy_en(), [i for i, l in enumerate(langs) if l in ("en", "mixed")])

    out: list[list[str]] = []
    for i, text in enumerate(texts):
        if not text or len(text) < 50:
            out.append([])
            continue
        kb_pairs = _keybert_keywords(text, max_tags)
        out.append(_combine_and_rank(spacy_per_text[i], kb_pairs, max_tags))
    return out
