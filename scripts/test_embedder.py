"""Smoke-тест эмбеддера: семантически близкие фразы должны иметь
высокий cosine, далёкая по теме — низкий.

Запуск:
    python scripts/test_embedder.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.nlp.embedder import embed_batch  # noqa: E402
from app.nlp.extractor import get_device  # noqa: E402


def cosine(a: list[float], b: list[float]) -> float:
    """Для нормализованных векторов cosine == dot product."""
    return sum(x * y for x, y in zip(a, b))


def main() -> None:
    print(f"NLP device: {get_device()}")
    texts = [
        "блокчейн и распределённые системы",
        "blockchain and distributed systems",
        "теория категорий в алгебре",
    ]
    vecs = embed_batch(texts)

    print()
    print(f"{'':<37} {'A':>8} {'B':>8} {'C':>8}")
    labels = ["A", "B", "C"]
    for i, (label, text) in enumerate(zip(labels, texts)):
        row = "  ".join(f"{cosine(vecs[i], vecs[j]):>8.3f}" for j in range(3))
        print(f"{label}  {text:<35} {row}")

    sim_ab = cosine(vecs[0], vecs[1])
    sim_ac = cosine(vecs[0], vecs[2])
    sim_bc = cosine(vecs[1], vecs[2])
    print()
    print(f"A↔B (ru/en blockchain):     {sim_ab:.3f}  ожидается > 0.7")
    print(f"A↔C (blockchain vs алгебра): {sim_ac:.3f}  ожидается заметно ниже")
    print(f"B↔C (blockchain vs алгебра): {sim_bc:.3f}  ожидается заметно ниже")


if __name__ == "__main__":
    main()
