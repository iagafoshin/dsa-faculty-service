"""Векторные эмбеддинги текста через sentence-transformers.

Используем ту же модель `paraphrase-multilingual-MiniLM-L12-v2`, что и
KeyBERT в extractor — экземпляр шарится через `get_sentence_transformer()`,
HuggingFace-кэш на диске тоже общий. 384-dim, нормализованные (cosine = dot).
"""
from __future__ import annotations

import logging

from app.nlp.extractor import get_sentence_transformer

logger = logging.getLogger(__name__)


def embed(text: str) -> list[float]:
    """Эмбеддит одну строку → нормализованный list[float] длины 384."""
    model = get_sentence_transformer()
    arr = model.encode(
        text,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return arr.tolist()


def embed_batch(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    """Батчевая версия. Возвращает list[list[float]] длины len(texts)."""
    if not texts:
        return []
    model = get_sentence_transformer()
    arr = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return arr.tolist()
