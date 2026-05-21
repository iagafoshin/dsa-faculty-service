"""NLP-слой: NER + ключевые фразы (extractor) + sentence embeddings (embedder).

Удобный re-export, чтобы внешний код мог писать `from app.nlp import ...`.
"""
from app.nlp.embedder import embed, embed_batch
from app.nlp.extractor import (
    apply_filters,
    detect_lang,
    extract_topics,
    extract_topics_batch,
    get_device,
    get_sentence_transformer,
)
from app.nlp.person_context import build_person_context, build_publication_context

__all__ = [
    "apply_filters",
    "build_person_context",
    "build_publication_context",
    "detect_lang",
    "embed",
    "embed_batch",
    "extract_topics",
    "extract_topics_batch",
    "get_device",
    "get_sentence_transformer",
]
